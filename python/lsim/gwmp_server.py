"""Serveur réseau Semtech UDP (GWMP v2) : passerelles réelles ↔ serveur de jointure.

Comportement :
- PUSH_DATA : PUSH_ACK immédiat (même si le JSON est invalide, pour arrêter les renvois),
  puis traitement des paquets hors de la boucle réseau ;
- PULL_DATA : enregistrement de la route de la passerelle, PULL_ACK ;
- join-request valide : join-accept en PULL_RESP, à rxpk.tmst + JOIN_ACCEPT_DELAY1 (5 s,
  RP002-1.0.2 §2.3), sur la fenêtre RX1 du plan régional (`lsim.plan`) ;
- uplink de données valide : voir `lsim.uplink` (ACK et downlink en file, en RX1 à +1 s) ;
- rejoin (types 0, 1, 2) : comptés, sans réponse (limites documentées) ;
- tout ce qui est invalide est compté et jeté, sans réponse (pas d'amplification).
- une livraison (uplink de données accepté) est transmise au callback `on_delivery`.

Le traitement crypto/persistance est synchrone (SQLite) : il tourne dans un pool de threads,
avec un plafond de paquets en cours (`max_inflight`) : au-delà, les paquets sont comptés
comme abandonnés plutôt que de saturer la mémoire.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from collections import Counter, OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable, Optional

from lsim import gwmp
from lsim.gwmp import ProtocolError, PullData, PushData, Rxpk, TxAck, Txpk
from lsim.join_server import JoinServer
from lsim.lora import StatusError
from lsim.plan import Plan, get_plan
from lsim.uplink import Delivery, Outcome

log = logging.getLogger("lsim.gwmp")

JOIN_ACCEPT_DELAY1_US = 5_000_000      # RP002-1.0.2 §2.3 : JOIN_ACCEPT_DELAY1 = 5 s
MTYPE_JOIN_REQUEST = 0b000
MTYPE_REJOIN_REQUEST = 0b110
MAX_GATEWAYS = 4096                    # bornes mémoire de la table des passerelles
DEFAULT_PULL_TIMEOUT_S = 60.0          # route considérée morte au-delà (paramètre de conception)
DEFAULT_MAX_INFLIGHT = 64


class JoinUplinkHandler:
    """Transforme une join-request reçue en join-accept (ou rejet). RX1 selon le plan régional."""

    def __init__(self, join_server: JoinServer, plan: Optional[Plan] = None) -> None:
        self._join = join_server
        self._plan = plan if plan is not None else get_plan("EU868")

    def handle(self, rxpk: Rxpk) -> Outcome:
        if not rxpk.payload:
            return Outcome("invalid")
        mtype = rxpk.payload[0] >> 5
        if mtype == MTYPE_JOIN_REQUEST:
            try:
                tx_dr = self._plan.data_rate_index(rxpk.datr)
                tx_ch = self._plan.channel_index(rxpk.freq_mhz)
                rx1_freq, rx1_datr = self._plan.rx1(tx_dr, tx_ch)
            except ValueError:
                return Outcome("join_unsupported_channel")
            try:
                outcome = self._join.handle_join_request(rxpk.payload)
            except (StatusError, KeyError, ValueError):
                return Outcome("join_rejected")
            tmst = (rxpk.tmst + JOIN_ACCEPT_DELAY1_US) % (2**32)
            txpk = Txpk(tmst=tmst, freq_mhz=rx1_freq, datr=rx1_datr, codr=rxpk.codr,
                        payload=outcome.accept_wire)
            return Outcome("join_accepted", txpk=txpk)
        if mtype == MTYPE_REJOIN_REQUEST:
            return Outcome("rejoin_unanswered")
        return Outcome("data_unhandled")


@dataclass
class _Route:
    addr: tuple[str, int]
    last_pull: float


class GwmpServer(asyncio.DatagramProtocol):
    def __init__(self, handler, *,
                 pull_timeout_s: float = DEFAULT_PULL_TIMEOUT_S,
                 max_inflight: int = DEFAULT_MAX_INFLIGHT,
                 executor: Optional[ThreadPoolExecutor] = None,
                 clock: Callable[[], float] = time.monotonic,
                 on_delivery: Optional[Callable[[Delivery], None]] = None) -> None:
        self._handler = handler
        self._on_delivery = on_delivery
        self._pull_timeout = pull_timeout_s
        self._max_inflight = max_inflight
        self._executor = executor
        self._clock = clock
        self._routes: "OrderedDict[bytes, _Route]" = OrderedDict()
        self._inflight = 0
        self._transport: Optional[asyncio.DatagramTransport] = None
        self.stats: Counter[str] = Counter()
        self._tasks: set[asyncio.Task] = set()

    # asyncio.DatagramProtocol

    def connection_made(self, transport) -> None:  # type: ignore[override]
        self._transport = transport

    def datagram_received(self, data: bytes, addr) -> None:  # type: ignore[override]
        if len(data) > gwmp.MAX_DATAGRAM_BYTES:
            self.stats["dropped_oversize"] += 1
            return
        # Un PUSH_DATA avec un en-tête correct est acquitté même si son JSON est invalide.
        if len(data) >= 12 and data[0] == gwmp.PROTOCOL_VERSION and data[3] == gwmp.PUSH_DATA:
            self._send(gwmp.build_push_ack(data[1:3]), addr)
        try:
            msg = gwmp.parse_upstream(data)
        except ProtocolError:
            self.stats["dropped_invalid"] += 1
            return
        if isinstance(msg, PullData):
            self._register(msg.gateway_eui, addr)
            self._send(gwmp.build_pull_ack(msg.token), addr)
            self.stats["pull_data"] += 1
        elif isinstance(msg, TxAck):
            self.stats["tx_ack"] += 1
            if msg.error is not None:
                self.stats["tx_ack_error"] += 1
                log.warning("passerelle %s : émission refusée (%s)", msg.gateway_eui.hex(), msg.error)
        elif isinstance(msg, PushData):
            self.stats["push_data"] += 1
            self._spawn(self._process_push(msg))

    def error_received(self, exc: Exception) -> None:  # type: ignore[override]
        self.stats["socket_error"] += 1
        log.warning("erreur socket : %s", exc)

    # Traitement

    def _spawn(self, coro) -> None:
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _process_push(self, msg: PushData) -> None:
        loop = asyncio.get_running_loop()
        for rxpk in msg.rxpk:
            if not rxpk.crc_ok:
                self.stats["crc_failed"] += 1
                continue
            if self._inflight >= self._max_inflight:
                self.stats["dropped_overload"] += 1
                continue
            self._inflight += 1
            try:
                outcome = await loop.run_in_executor(self._executor, self._handler.handle, rxpk)
            except Exception:  # noqa: BLE001 - une erreur interne ne doit pas arrêter le serveur
                self.stats["handler_error"] += 1
                log.exception("erreur de traitement d'un paquet")
                continue
            finally:
                self._inflight -= 1
            self.stats[outcome.issue] += 1
            if outcome.txpk is not None:
                self._downlink(msg.gateway_eui, outcome.txpk)
            if outcome.delivery is not None and self._on_delivery is not None:
                try:
                    self._on_delivery(outcome.delivery)
                except Exception:  # noqa: BLE001 - un consommateur défaillant ne bloque pas le serveur
                    self.stats["delivery_callback_error"] += 1
                    log.exception("erreur dans le consommateur des livraisons")

    def _downlink(self, gateway_eui: bytes, txpk: Txpk) -> None:
        route = self._routes.get(gateway_eui)
        if route is None or self._clock() - route.last_pull > self._pull_timeout:
            self.stats["downlink_no_route"] += 1
            return
        token = secrets.token_bytes(2)
        self._send(gwmp.build_pull_resp(token, txpk), route.addr)
        self.stats["downlink_sent"] += 1

    def _register(self, gateway_eui: bytes, addr) -> None:
        if gateway_eui in self._routes:
            self._routes.move_to_end(gateway_eui)
        elif len(self._routes) >= MAX_GATEWAYS:
            self._routes.popitem(last=False)          # on évince la plus ancienne
            self.stats["route_evicted"] += 1
        self._routes[gateway_eui] = _Route(addr=(addr[0], addr[1]), last_pull=self._clock())

    def _send(self, data: bytes, addr) -> None:
        if self._transport is not None:
            self._transport.sendto(data, addr)

    async def drain(self) -> None:
        """Attend la fin des traitements en cours (tests et arrêt propre)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)


async def start_server(handler, host: str, port: int, **kwargs
                       ) -> tuple[asyncio.DatagramTransport, GwmpServer]:
    loop = asyncio.get_running_loop()
    protocol = GwmpServer(handler, **kwargs)
    transport, _ = await loop.create_datagram_endpoint(
        lambda: protocol, local_addr=(host, port))
    return transport, protocol
