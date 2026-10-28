"""Protocole passerelle ↔ serveur Semtech UDP (GWMP, version 2), codec strict.

Source : PROTOCOL.TXT du dépôt Lora-net/packet_forwarder (Semtech), révision v1.4 (champ tmms).
Ce module ne fait aucune entrée/sortie réseau : il décode et encode les datagrammes.

Règles de sécurité :
- taille maximale d'un datagramme : MAX_DATAGRAM_BYTES ; au-delà, rejet sans lecture ;
- version et identifiant contrôlés avant toute analyse du JSON ;
- JSON : nombres non finis refusés, nombre de paquets borné, base64 strict, taille du
  payload vérifiée contre le champ `size` ;
- seuls les paquets LoRa sont acceptés (FSK non supporté, documenté).
"""

from __future__ import annotations

import base64
import binascii
import json
import math
from dataclasses import dataclass, field
from typing import Any, Optional

PROTOCOL_VERSION = 2
PUSH_DATA = 0x00
PUSH_ACK = 0x01
PULL_DATA = 0x02
PULL_RESP = 0x03
PULL_ACK = 0x04
TX_ACK = 0x05

MAX_DATAGRAM_BYTES = 4096      # choix de conception, pas une valeur du protocole
MAX_RXPK_PER_PUSH = 16         # choix de conception : bornes contre les datagrammes gonflés
MAX_PAYLOAD_BYTES = 255        # taille maximale d'un payload LoRa (PHY)
_EUI_LEN = 8

_RSSI_RANGE = (-250, 50)
_LSNR_RANGE = (-50.0, 50.0)
_FREQ_MHZ_RANGE = (30.0, 3000.0)
_TMST_MAX = 2**32 - 1


class ProtocolError(ValueError):
    """Datagramme GWMP invalide : à jeter, sans réponse."""


@dataclass(frozen=True)
class Rxpk:
    """Paquet reçu par la passerelle (champs utiles du PUSH_DATA)."""
    tmst: int
    freq_mhz: float
    chan: int
    rfch: int
    crc_ok: bool
    datr: str            # ex. « SF7BW125 »
    codr: str            # ex. « 4/5 »
    rssi: int
    lsnr: float
    payload: bytes = field(repr=False)


@dataclass(frozen=True)
class PushData:
    token: bytes
    gateway_eui: bytes
    rxpk: tuple[Rxpk, ...]


@dataclass(frozen=True)
class PullData:
    token: bytes
    gateway_eui: bytes


@dataclass(frozen=True)
class TxAck:
    token: bytes
    gateway_eui: bytes
    error: Optional[str]


@dataclass(frozen=True)
class Txpk:
    """Paquet à émettre. `tmst` : instant de déclenchement (compteur µs de la passerelle)."""
    tmst: int
    freq_mhz: float
    datr: str
    codr: str
    payload: bytes = field(repr=False)
    powe_dbm: Optional[int] = None     # absent : puissance par défaut de la passerelle
    ipol: bool = True                  # downlink : polarité inversée
    ncrc: bool = True                  # downlink : pas de CRC PHY


# --- Décodage ---------------------------------------------------------------------------

def parse_upstream(datagram: bytes) -> PushData | PullData | TxAck:
    """Analyse un datagramme gateway → serveur (PUSH_DATA, PULL_DATA ou TX_ACK)."""
    if not isinstance(datagram, (bytes, bytearray)):
        raise ProtocolError("datagramme non binaire")
    if len(datagram) > MAX_DATAGRAM_BYTES:
        raise ProtocolError("datagramme trop grand")
    if len(datagram) < 4:
        raise ProtocolError("datagramme trop court")
    if datagram[0] != PROTOCOL_VERSION:
        raise ProtocolError("version de protocole inconnue")
    token = bytes(datagram[1:3])
    identifier = datagram[3]
    if identifier == PUSH_DATA:
        if len(datagram) < 13:
            raise ProtocolError("PUSH_DATA trop court")
        eui = bytes(datagram[4:12])
        return PushData(token, eui, _parse_rxpk_object(bytes(datagram[12:])))
    if identifier == PULL_DATA:
        if len(datagram) != 12:
            raise ProtocolError("PULL_DATA de taille inattendue")
        return PullData(token, bytes(datagram[4:12]))
    if identifier == TX_ACK:
        if len(datagram) < 12:
            raise ProtocolError("TX_ACK trop court")
        eui = bytes(datagram[4:12])
        body = bytes(datagram[12:])
        return TxAck(token, eui, _parse_txack_error(body) if body else None)
    raise ProtocolError("identifiant de message inconnu")


def _load_json(body: bytes) -> dict[str, Any]:
    if not body.startswith(b"{") or not body.endswith(b"}"):
        raise ProtocolError("JSON attendu entre accolades")
    try:
        text = body.decode("utf-8")
        doc = json.loads(text, parse_constant=_reject_constant)
    except (UnicodeDecodeError, ValueError) as exc:
        raise ProtocolError("JSON invalide") from exc
    if not isinstance(doc, dict):
        raise ProtocolError("racine JSON non objet")
    return doc


def _reject_constant(name: str) -> None:
    raise ProtocolError(f"constante JSON interdite : {name}")


def _parse_rxpk_object(body: bytes) -> tuple[Rxpk, ...]:
    doc = _load_json(body)
    items = doc.get("rxpk", [])
    if not isinstance(items, list):
        raise ProtocolError("rxpk doit être un tableau")
    if len(items) > MAX_RXPK_PER_PUSH:
        raise ProtocolError("trop de paquets dans un PUSH_DATA")
    return tuple(_parse_rxpk(item) for item in items)


def _number(obj: dict, key: str, lo: float, hi: float, *, integer: bool) -> Any:
    value = obj.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProtocolError(f"champ {key} numérique attendu")
    if not math.isfinite(value):
        raise ProtocolError(f"champ {key} non fini")
    if integer and (not isinstance(value, int) and not float(value).is_integer()):
        raise ProtocolError(f"champ {key} entier attendu")
    if not lo <= value <= hi:
        raise ProtocolError(f"champ {key} hors bornes")
    return int(value) if integer else float(value)


def _parse_rxpk(item: Any) -> Rxpk:
    if not isinstance(item, dict):
        raise ProtocolError("rxpk non objet")
    if item.get("modu") != "LORA":
        raise ProtocolError("modulation non supportée (LoRa seulement)")
    datr = item.get("datr")
    codr = item.get("codr")
    if not isinstance(datr, str) or not isinstance(codr, str):
        raise ProtocolError("datr et codr textuels attendus")
    size = _number(item, "size", 0, MAX_PAYLOAD_BYTES, integer=True)
    data = item.get("data")
    if not isinstance(data, str):
        raise ProtocolError("champ data attendu")
    try:
        payload = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ProtocolError("base64 invalide") from exc
    if len(payload) != size:
        raise ProtocolError("taille du payload différente de size")
    stat = _number(item, "stat", -1, 1, integer=True)
    return Rxpk(
        tmst=_number(item, "tmst", 0, _TMST_MAX, integer=True),
        freq_mhz=_number(item, "freq", *_FREQ_MHZ_RANGE, integer=False),
        chan=_number(item, "chan", 0, 255, integer=True),
        rfch=_number(item, "rfch", 0, 255, integer=True),
        crc_ok=stat == 1,
        datr=datr,
        codr=codr,
        rssi=_number(item, "rssi", *_RSSI_RANGE, integer=True),
        lsnr=_number(item, "lsnr", *_LSNR_RANGE, integer=False),
        payload=payload,
    )


def _parse_txack_error(body: bytes) -> Optional[str]:
    doc = _load_json(body)
    ack = doc.get("txpk_ack")
    if not isinstance(ack, dict):
        raise ProtocolError("txpk_ack attendu")
    error = ack.get("error", "NONE")
    if not isinstance(error, str) or len(error) > 32:
        raise ProtocolError("champ error invalide")
    return None if error == "NONE" else error


# --- Encodage ---------------------------------------------------------------------------

def build_push_ack(token: bytes) -> bytes:
    return _header(token, PUSH_ACK)


def build_pull_ack(token: bytes) -> bytes:
    return _header(token, PULL_ACK)


def build_pull_resp(token: bytes, txpk: Txpk) -> bytes:
    """PULL_RESP : en-tête puis JSON {"txpk": {...}} (champs omis = défauts de la passerelle)."""
    fields: dict[str, Any] = {
        "imme": False,
        "tmst": _check_range(txpk.tmst, 0, _TMST_MAX, "tmst"),
        "freq": _check_range(txpk.freq_mhz, *_FREQ_MHZ_RANGE, "freq"),
        "modu": "LORA",
        "datr": txpk.datr,
        "codr": txpk.codr,
        "ipol": bool(txpk.ipol),
        "ncrc": bool(txpk.ncrc),
        "size": len(txpk.payload),
        "data": base64.b64encode(txpk.payload).decode("ascii"),
    }
    if len(txpk.payload) > MAX_PAYLOAD_BYTES:
        raise ValueError("payload trop grand pour la couche PHY")
    if txpk.powe_dbm is not None:
        fields["powe"] = _check_range(txpk.powe_dbm, -10, 30, "powe")
    body = json.dumps({"txpk": fields}, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    out = _header(token, PULL_RESP) + body
    if len(out) > MAX_DATAGRAM_BYTES:
        raise ValueError("PULL_RESP trop grand")
    return out


def build_pull_data(token: bytes, gateway_eui: bytes) -> bytes:
    """Utile pour les tests et les simulateurs de passerelle."""
    return _header(token, PULL_DATA) + _eui(gateway_eui)


def build_push_data(token: bytes, gateway_eui: bytes, rxpk: list[dict[str, Any]]) -> bytes:
    """Utile pour les tests et les simulateurs de passerelle (JSON fourni tel quel)."""
    body = json.dumps({"rxpk": rxpk}, separators=(",", ":")).encode("ascii")
    return _header(token, PUSH_DATA) + _eui(gateway_eui) + body


def _header(token: bytes, identifier: int) -> bytes:
    if not isinstance(token, (bytes, bytearray)) or len(token) != 2:
        raise ValueError("token de 2 octets attendu")
    return bytes([PROTOCOL_VERSION]) + bytes(token) + bytes([identifier])


def _eui(eui: bytes) -> bytes:
    if not isinstance(eui, (bytes, bytearray)) or len(eui) != _EUI_LEN:
        raise ValueError("EUI passerelle de 8 octets attendu")
    return bytes(eui)


def _check_range(value: float, lo: float, hi: float, name: str) -> float:
    if not math.isfinite(value) or not lo <= value <= hi:
        raise ValueError(f"{name} hors bornes")
    return value
