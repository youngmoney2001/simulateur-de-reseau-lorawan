"""Basic Station (protocole LNS, WebSocket) : adaptateur vers le cœur transport-agnostique.

Le cœur (`lsim.uplink`, `lsim.join_server`) reçoit des `Rxpk` (même forme que la passerelle
Semtech) et produit des `Txpk`. Ce module ne contient que la traduction de messages JSON et la
gestion des connexions :

- découverte : `…/router-info` reçoit `{"router": EUI}` et répond `router`, `muxs`, `uri` ;
- session de données : `version` → `router_config` (plan régional, DRs, sx1301_conf) ;
- `jreq` / `updf` : reconstruits en trame LoRaWAN (champs little-endian sur l'air), puis traités
  par le cœur ; un downlink devient `dnmsg` (classe A) avec `RxDelay` = délai RX1 du cœur
  (5 s pour le join-accept, 1 s pour les données) et `RX2` du plan ;
- `dntxed` : compté ; `timesync` : répondu avec `gpstime` ; `propdf` et inconnus : comptés.

Hypothèses (à valider sur une vraie passerelle) : EUI au format « AA-BB-… » (ou 16 hex, ou
entier) ; MIC et DevAddr en entier signé 32 bits, octets sur l'air en petit-boutiste ; ID6 non
pris en charge dans `router`. `sx1301_conf` décrit 8 canaux (sous-bande 0 du plan) sur un
concentrateur ; les autres canaux ne sont pas configurés (limite documentée).
"""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
import re
import ssl
import time
from collections import Counter
from concurrent.futures import Executor
from typing import Any, Callable, Optional

from lsim import wsproto
from lsim.gwmp import Rxpk
from lsim.plan import Plan
from lsim.uplink import Delivery, Outcome
from lsim.wsproto import CLOSE_PROTOCOL, HttpError, WsConnection, WsError

log = logging.getLogger("lsim.basicstation")

DISCOVERY_SUFFIX = "/router-info"
MAX_MESSAGE_BYTES = 16384           # un updf ≤ 255 octets tient largement ; plafond mémoire
DEFAULT_IDLE_TIMEOUT_S = 300.0
DEFAULT_MAX_CONNECTIONS = 1024
MAX_INFLIGHT_PER_CONNECTION = 32
DEFAULT_PORT_WS = 8887             # port de déploiement (choix, non normatif)
DEFAULT_HWSPEC = "sx1302/1"          # concentrateurs RAKwireless actuels (à confirmer par passerelle)
JOIN_EUI_RANGE = (0, 2**64 - 1)
_GPS_EPOCH_UNIX_S = 315_964_800      # 1980-01-06 00:00:00 UTC
_GPS_LEAP_S = 18                     # écart GPS - UTC depuis 2017
_MAX_TEXT = 64

_EUI_RE = re.compile(r"^[0-9A-Fa-f]{16}$")


# --- Identifiants et nombres ----------------------------------------------------------------

def parse_eui(value: Any) -> bytes:
    """EUI-64 (« AA-BB-… », 16 hex, ou entier) -> 8 octets, ordre d'affichage (poids fort d'abord)."""
    if isinstance(value, bool):
        raise ValueError("EUI invalide")
    if isinstance(value, int):
        if not 0 <= value < 2**64:
            raise ValueError("EUI hors plage")
        return value.to_bytes(8, "big")
    if isinstance(value, str):
        cleaned = value.replace("-", "").replace(":", "")
        if _EUI_RE.match(cleaned):
            return bytes.fromhex(cleaned)
    raise ValueError("EUI invalide")


def format_eui(eui: bytes) -> str:
    return "-".join(f"{b:02X}" for b in eui)


def _int(value: Any, lo: int, hi: int, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        raise ValueError(f"{what} hors bornes")
    return value


def _num(value: Any, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{what} non numérique")
    return float(value)


def _hex(value: Any, max_bytes: int, what: str) -> bytes:
    if not isinstance(value, str) or len(value) % 2 or len(value) > 2 * max_bytes:
        raise ValueError(f"{what} : hexadécimal invalide")
    try:
        return bytes.fromhex(value)
    except ValueError:
        raise ValueError(f"{what} : hexadécimal invalide") from None


def _s32_le(value: Any, what: str) -> bytes:
    """Entier signé 32 bits (DevAddr ou MIC) -> 4 octets petit-boutistes."""
    return (_int(value, -2**31, 2**32 - 1, what) & 0xFFFFFFFF).to_bytes(4, "little")


# --- Messages montants -> Rxpk --------------------------------------------------------------

def _radio(msg: dict, plan: Plan) -> tuple[str, float, int, float, float]:
    upinfo = msg.get("upinfo")
    if not isinstance(upinfo, dict):
        raise ValueError("upinfo absent")
    dr = _int(msg.get("DR"), 0, 15, "DR")
    freq = _int(msg.get("Freq"), 1, 2**32 - 1, "Freq")
    xtime = _int(upinfo.get("xtime", 0), -2**63, 2**63 - 1, "xtime")
    rctx = _int(upinfo.get("rctx", 0), -2**63, 2**63 - 1, "rctx")
    rssi = _num(upinfo.get("rssi", 0), "rssi")
    snr = _num(upinfo.get("snr", 0), "snr")
    return plan.dr_datr(dr), freq / 1_000_000, xtime, rctx, rssi, snr


def _rxpk(payload: bytes, datr: str, freq_mhz: float, xtime: int, rssi: float, snr: float) -> Rxpk:
    return Rxpk(tmst=xtime & 0xFFFFFFFF, freq_mhz=freq_mhz, chan=0, rfch=0, crc_ok=True,
                datr=datr, codr="4/5", rssi=round(rssi), lsnr=snr, payload=payload)


def jreq_to_wire(msg: dict) -> bytes:
    """Reconstruit la join-request (MHdr, JoinEUI, DevEUI, DevNonce, MIC) telle qu'émise."""
    mhdr = _int(msg.get("MHdr"), 0, 255, "MHdr")
    if mhdr >> 5 != 0:
        raise ValueError("MHdr : join-request attendue")
    join_eui = parse_eui(msg.get("JoinEui"))
    dev_eui = parse_eui(msg.get("DevEui"))
    dev_nonce = _int(msg.get("DevNonce"), 0, 0xFFFF, "DevNonce")
    mic = _s32_le(msg.get("MIC"), "MIC")
    return (bytes([mhdr]) + join_eui[::-1] + dev_eui[::-1]
            + dev_nonce.to_bytes(2, "little") + mic)


def updf_to_wire(msg: dict) -> bytes:
    """Reconstruit la trame de données (MHdr, DevAddr, FCtrl, FCnt, FOpts, FPort, FRMPayload, MIC)."""
    mhdr = _int(msg.get("MHdr"), 0, 255, "MHdr")
    if mhdr >> 5 not in (0b010, 0b100):
        raise ValueError("MHdr : uplink de données attendu")
    dev_addr = _s32_le(msg.get("DevAddr"), "DevAddr")
    fctrl = _int(msg.get("FCtrl"), 0, 255, "FCtrl")
    fcnt = _int(msg.get("FCnt"), 0, 0xFFFF, "FCnt")
    fopts = _hex(msg.get("FOpts", ""), 15, "FOpts")
    if len(fopts) != fctrl & 0x0F:
        raise ValueError("FOpts : longueur incohérente avec FCtrl")
    fport = _int(msg.get("FPort", -1), -1, 255, "FPort")
    frm = _hex(msg.get("FRMPayload", ""), 255, "FRMPayload")
    if fport == -1:
        if frm:
            raise ValueError("FRMPayload sans FPort")
        body = b""
    else:
        body = bytes([fport]) + frm
    mic = _s32_le(msg.get("MIC"), "MIC")
    return (bytes([mhdr]) + dev_addr + bytes([fctrl]) + fcnt.to_bytes(2, "little")
            + fopts + body + mic)


def uplink_to_rxpk(msg: dict, plan: Plan) -> tuple[Rxpk, int, int]:
    """jreq ou updf -> (Rxpk pour le cœur, xtime, rctx). Lève ValueError si invalide."""
    kind = msg.get("msgtype")
    wire = jreq_to_wire(msg) if kind == "jreq" else updf_to_wire(msg)
    datr, freq_mhz, xtime, rctx, rssi, snr = _radio(msg, plan)
    return _rxpk(wire, datr, freq_mhz, xtime, rssi, snr), xtime, rctx


# --- Configuration de la passerelle ---------------------------------------------------------

def sx1301_conf(channels_hz: tuple[int, ...]) -> dict:
    """Un concentrateur, 8 canaux : radio_0 au centre des canaux, IF = canal - centre."""
    block = tuple(channels_hz[:8])
    if not block:
        raise ValueError("aucun canal montant")
    center = round((min(block) + max(block)) / 2 / 100_000) * 100_000
    ifs = [ch - center for ch in block]
    if any(abs(value) > 1_000_000 for value in ifs):
        raise ValueError("canaux trop éloignés pour un concentrateur")
    conf: dict[str, Any] = {
        "radio_0": {"enable": True, "freq": center},
        "radio_1": {"enable": False, "freq": 0},
        "chan_FSK": {"enable": False, "radio": 0, "if": 0},
        "chan_Lora_std": {"enable": False, "radio": 0, "if": 0,
                          "bandwidth": 125_000, "spread_factor": 7},
    }
    for index in range(8):
        if index < len(block):
            conf[f"chan_multiSF_{index}"] = {"enable": True, "radio": 0, "if": ifs[index]}
        else:
            conf[f"chan_multiSF_{index}"] = {"enable": False, "radio": 0, "if": 0}
    return conf


def router_config(plan: Plan, net_id: int, hwspec: str) -> dict:
    lo, hi = plan.freq_range_hz()
    return {
        "msgtype": "router_config",
        "NetID": [net_id],
        "JoinEui": [list(JOIN_EUI_RANGE)],
        "region": plan.name,
        "hwspec": hwspec,
        "freq_range": [lo, hi],
        "DRs": [list(row) for row in plan.dr_table()],
        "sx1301_conf": [sx1301_conf(plan.uplink_channels_hz())],
        "nocca": False,
        "nodc": False,
        "nodwell": False,
    }


def downlink_message(outcome: Outcome, rxpk_tmst: int, xtime: int, rctx: int,
                     plan: Plan, diid: int) -> dict:
    """dnmsg classe A à partir du Txpk du cœur. RxDelay = écart RX1 en secondes entières."""
    txpk = outcome.txpk
    if txpk is None or outcome.dev_eui is None:
        raise ValueError("downlink incomplet")
    delay_us = (txpk.tmst - rxpk_tmst) % 2**32
    rx_delay = round(delay_us / 1_000_000)
    if not 1 <= rx_delay <= 15:
        raise ValueError(f"RxDelay hors plage : {rx_delay} s")
    rx2_hz, rx2_datr = plan.rx2()
    return {
        "msgtype": "dnmsg",
        "DevEui": format_eui(outcome.dev_eui[::-1]),       # core : ordre de transmission
        "dC": 0,
        "diid": diid,
        "pdu": txpk.payload.hex(),
        "RxDelay": rx_delay,
        "RX1DR": plan.dr_of_downlink_datr(txpk.datr),
        "RX1Freq": round(txpk.freq_mhz * 1_000_000),
        "RX2DR": plan.dr_of_downlink_datr(rx2_datr),
        "RX2Freq": rx2_hz,
        "priority": 0,
        "xtime": xtime,
        "rctx": rctx,
    }


def _gps_time_us() -> int:
    unix_us = time.time_ns() // 1000
    return unix_us - _GPS_EPOCH_UNIX_S * 1_000_000 + _GPS_LEAP_S * 1_000_000


def _safe_text(value: Any) -> str:
    if not isinstance(value, str):
        return "?"
    return "".join(c for c in value[:_MAX_TEXT] if c.isprintable())


def _parse_object(text: str, *, typed: bool = True) -> dict:
    try:
        doc = json.loads(text)
    except (ValueError, RecursionError):
        raise ValueError("JSON invalide") from None
    if not isinstance(doc, dict):
        raise ValueError("objet JSON attendu")
    if typed and not isinstance(doc.get("msgtype"), str):
        raise ValueError("message sans msgtype")
    return doc


# --- Serveur ---------------------------------------------------------------------------------

class BasicStationServer:
    """Connexions Basic Station ; une connexion = une passerelle (identifiée par son `version`)."""

    def __init__(self, handler, plan: Plan, *, net_id: int, uri: str,
                 muxs_eui: bytes = bytes(7) + b"\x01",
                 hwspec: str = DEFAULT_HWSPEC,
                 executor: Optional[Executor] = None,
                 max_connections: int = DEFAULT_MAX_CONNECTIONS,
                 idle_timeout_s: float = DEFAULT_IDLE_TIMEOUT_S,
                 on_delivery: Optional[Callable[[Delivery], None]] = None) -> None:
        self._handler = handler
        self._plan = plan
        self._net_id = net_id
        self._uri = uri
        self._muxs = muxs_eui
        self._hwspec = hwspec
        self._executor = executor
        self._max_connections = max_connections
        self._idle = idle_timeout_s
        self._on_delivery = on_delivery
        self._open = 0
        self._diid = itertools.count(1)
        self.stats: Counter[str] = Counter()

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            if self._open >= self._max_connections:
                self.stats["refused_overload"] += 1
                writer.write(wsproto.http_error_response(503, "trop de connexions"))
                await writer.drain()
                return
            self._open += 1
            try:
                await self._session(reader, writer)
            finally:
                self._open -= 1
        except (ConnectionError, OSError):
            self.stats["connection_error"] += 1
        finally:
            if not writer.is_closing():
                writer.close()

    async def _session(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            method, target, headers = await wsproto.read_request(reader)
            key = wsproto.check_upgrade(method, headers)
        except HttpError as exc:
            self.stats["http_rejected"] += 1
            writer.write(wsproto.http_error_response(exc.status, exc.reason))
            await writer.drain()
            return
        writer.write(wsproto.handshake_response(key))
        await writer.drain()
        conn = WsConnection(reader, writer, max_message=MAX_MESSAGE_BYTES,
                            idle_timeout_s=self._idle)
        try:
            if target.split("?", 1)[0].endswith(DISCOVERY_SUFFIX):
                await self._discovery(conn)
            else:
                await self._data(conn)
        except WsError as exc:
            self.stats["ws_protocol_error"] += 1
            log.info("connexion fermée : %s", exc)
            await conn.close(exc.code)
        except asyncio.TimeoutError:
            self.stats["handshake_timeout"] += 1
            log.info("connexion fermée : premier message absent")
        except ValueError as exc:
            self.stats["protocol_error"] += 1
            log.info("message refusé : %s", exc)
            await conn.close(CLOSE_PROTOCOL)
        except Exception:  # noqa: BLE001 - une session défaillante ne doit pas remonter à asyncio
            self.stats["session_error"] += 1
            log.exception("erreur inattendue dans une session Basic Station")
        finally:
            await conn.close()

    async def _discovery(self, conn: WsConnection) -> None:
        text = await asyncio.wait_for(conn.recv_text(), wsproto.HANDSHAKE_TIMEOUT_S)
        if text is None:
            return
        self.stats["discovery"] += 1
        try:
            doc = _parse_object(text, typed=False)
            router = parse_eui(doc.get("router"))
        except ValueError:
            self.stats["discovery_rejected"] += 1
            await conn.send_text(json.dumps({"error": "identité de passerelle invalide"}))
            return
        reply = {"router": format_eui(router), "muxs": format_eui(self._muxs), "uri": self._uri}
        await conn.send_text(json.dumps(reply))

    async def _data(self, conn: WsConnection) -> None:
        text = await asyncio.wait_for(conn.recv_text(), wsproto.HANDSHAKE_TIMEOUT_S)
        if text is None:
            return
        version = _parse_object(text)
        if version["msgtype"] != "version":
            raise WsError(CLOSE_PROTOCOL, "version attendu en premier")
        self.stats["sessions"] += 1
        log.info("passerelle connectée : modèle %s, station %s, protocole %s",
                 _safe_text(version.get("model")), _safe_text(version.get("station")),
                 version.get("protocol") if isinstance(version.get("protocol"), int) else "?")
        await conn.send_text(json.dumps(router_config(self._plan, self._net_id, self._hwspec)))
        pending: set[asyncio.Task] = set()
        while True:
            text = await conn.recv_text()
            if text is None:
                break
            try:
                msg = _parse_object(text)
            except ValueError:
                self.stats["bad_json"] += 1
                continue
            kind = msg["msgtype"]
            if kind in ("jreq", "updf"):
                if len(pending) >= MAX_INFLIGHT_PER_CONNECTION:
                    self.stats["dropped_overload"] += 1
                    continue
                task = asyncio.ensure_future(self._uplink(conn, msg))
                pending.add(task)
                task.add_done_callback(pending.discard)
            elif kind == "dntxed":
                self.stats["dntxed"] += 1
            elif kind == "timesync":
                self.stats["timesync"] += 1
                if "txtime" in msg:
                    reply = {"msgtype": "timesync", "txtime": msg["txtime"],
                             "gpstime": _gps_time_us()}
                    await conn.send_text(json.dumps(reply))
            elif kind == "version":
                self.stats["version_repeated"] += 1
            elif kind == "propdf":
                self.stats["propdf_ignored"] += 1
            else:
                self.stats["unknown_msgtype"] += 1
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    async def _uplink(self, conn: WsConnection, msg: dict) -> None:
        kind = msg["msgtype"]
        try:
            rxpk, xtime, rctx = uplink_to_rxpk(msg, self._plan)
        except ValueError as exc:
            self.stats[f"invalid_{kind}"] += 1
            log.debug("%s refusé : %s", kind, exc)
            return
        loop = asyncio.get_running_loop()
        try:
            outcome = await loop.run_in_executor(self._executor, self._handler.handle, rxpk)
        except Exception:  # noqa: BLE001 - une erreur interne ne doit pas arrêter la session
            self.stats["handler_error"] += 1
            log.exception("erreur de traitement d'un paquet Basic Station")
            return
        self.stats[outcome.issue] += 1
        if outcome.txpk is not None:
            try:
                dn = downlink_message(outcome, rxpk.tmst, xtime, rctx, self._plan,
                                      next(self._diid))
            except ValueError as exc:
                self.stats["downlink_not_sent"] += 1
                log.warning("downlink non émis : %s", exc)
            else:
                try:
                    await conn.send_text(json.dumps(dn, separators=(",", ":")))
                    self.stats["downlink_sent"] += 1
                except ConnectionError:
                    self.stats["downlink_connection_lost"] += 1
        if outcome.delivery is not None and self._on_delivery is not None:
            try:
                self._on_delivery(outcome.delivery)
            except Exception:  # noqa: BLE001 - un consommateur défaillant ne bloque pas le serveur
                self.stats["delivery_callback_error"] += 1
                log.exception("erreur dans le consommateur des livraisons")


def make_ssl_context(cert: str, key: str) -> ssl.SSLContext:
    """TLS serveur (wss) : TLS 1.2 minimum."""
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(cert, key)
    return context


async def start_basicstation_server(server: BasicStationServer, host: str, port: int,
                                    ssl_context: Optional[ssl.SSLContext] = None
                                    ) -> asyncio.AbstractServer:
    return await asyncio.start_server(server.handle_client, host, port, ssl=ssl_context,
                                      limit=wsproto.MAX_HEADER_BYTES)
