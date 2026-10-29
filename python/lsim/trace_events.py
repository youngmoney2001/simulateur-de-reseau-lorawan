"""Trace par transmission et événements du protocole, sur la même horloge que le moteur.

Le cœur natif produit une entrée par émission (début, fin, issue à la passerelle). Ce module
en dérive les événements de la couche protocole, avec les temporisations de la spécification :

- join-request : même issue que l'émission ; join-accept à fin + JOIN_ACCEPT_DELAY1 (5 s) ;
- uplink de données : issue de l'émission ; un uplink accepté par la passerelle ouvre une
  fenêtre RX1 à fin + RECEIVE_DELAY1 (1 s) ;
- downlink (un seul par uplink accepté, comme `lsim.uplink`) : si une charge est en file
  (`downlink_every`), sinon ACK seul si l'uplink est confirmé.

Modèle de la passerelle (demi-duplex, un émetteur) :
- elle n'émet qu'un downlink à la fois : un downlink qui tombe pendant un autre attend la fin de
  celui-ci. S'il ne peut partir qu'après la fenêtre RX1 du dispositif (1 s), il est perdu
  (`rx_window_missed`, issue `gateway_busy`), sans retransmission ;
- pendant une émission de downlink, elle ne reçoit pas : une trame montante qui la chevauche est
  perdue (issue `lost_gateway_busy`). Les émissions de downlink dépendent des uplinks reçus, et
  inversement : le calcul itère jusqu'à un point fixe, sinon il échoue (pas de résultat faux).

Modèle du dispositif :
- demi-duplex : s'il émet à nouveau pendant sa fenêtre RX1, la fenêtre est manquée
  (`rx_window_missed`, issue `device_transmitting`) ;
- réception du downlink par réciprocité : RSSI descendant = RSSI montant - P_dispositif
  + P_passerelle + G_dispositif (le gain d'antenne passerelle s'annule). Reçu si ce RSSI atteint
  la sensibilité du débit RX1 du plan (référence SX1276, `lsim.radio`) plus
  `device_rx_offset_db` (écart du récepteur réel, à renseigner depuis sa fiche technique).

Limites assumées : une seule passerelle ; backhaul passerelle -> serveur et transmission du
join-accept par le serveur sans perte (issue `delivered`) ; les downlinks ne sont pas testés
contre les brouillages du dispositif hors de la passerelle elle-même.

Les dates sont en nanosecondes entières, issues du moteur, sans recalcul flottant.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional, Sequence

from lsim.gwmp_server import JOIN_ACCEPT_DELAY1_US
from lsim.lora import RadioConfig, time_on_air_ns
from lsim.plan import RECEIVE_DELAY1_US, Plan, get_plan
from lsim.radio import receiver_sensitivity_dbm
from lsim.scenario import Scenario

if TYPE_CHECKING:  # annotations seulement : évite le cycle avec closed_loop / downlink_plan
    from lsim.closed_loop import MacByteAccounting, MacQueueCounters
from lsim.mesh import MESH_ENVELOPE_DOWN_BYTES, MESH_ENVELOPE_UP_BYTES
from lsim import mac as lsim_mac
from lsim.mac import DevStatusReq, DeviceTimeAns, DeviceTimeReq, LinkCheckAns, LinkCheckReq
from lsim import mac_plan
from lsim.mac_plan import MacSchedule, device_status_request_due, uplink_requests
from lsim.mesh_pass import mesh_pass
from lsim.simulator import (
    MAX_TRACE_RECORDS,
    Counters,
    DownlinkRule,
    GatewayLoad,
    TxRecord,
    simulate_multi_downlinks,
    simulate_uplinks_trace,
)

NS_PER_US = 1_000
RECEIVE_DELAY1_NS = RECEIVE_DELAY1_US * NS_PER_US
JOIN_ACCEPT_DELAY1_NS = JOIN_ACCEPT_DELAY1_US * NS_PER_US
# Durée de la fenêtre RX1 du dispositif (hypothèse, 1 s).
RX1_WINDOW_NS = 1_000_000_000
# Borne des événements par run (contrat d'API : 200 000).
MAX_EVENTS = 200_000
# Trame downlink sans charge : MHDR (1) + DevAddr (4) + FCtrl (1) + FCnt (2) + MIC (4).
ACK_FRAME_BYTES = 12
# Trame downlink avec charge : ACK_FRAME_BYTES + FPort (1) + charge.
DATA_FRAME_OVERHEAD_BYTES = 13
# Join-accept sans CFList : MHDR (1) + AppNonce (3) + NetID (3) + DevAddr (4) + DLSettings (1)
# + RxDelay (1) + MIC (4).
JOIN_ACCEPT_BYTES = 17
MAX_ITERATIONS = 12

_UPLINK_OUTCOME = {
    TxRecord.OUTCOME_LOST_SENSITIVITY: "lost_sensitivity",
    TxRecord.OUTCOME_LOST_COLLISION: "lost_collision",
    TxRecord.OUTCOME_RECEIVED: "received",
    TxRecord.OUTCOME_LOST_GATEWAY_BUSY: "lost_gateway_busy",
}
_HOP_OUTCOME = {
    TxRecord.OUTCOME_LOST_SENSITIVITY: "lost_sensitivity",
    TxRecord.OUTCOME_LOST_COLLISION: "lost_collision",
    TxRecord.OUTCOME_RECEIVED: "delivered",
    TxRecord.OUTCOME_LOST_GATEWAY_BUSY: "not_listened",
}


@dataclass(frozen=True)
class ProtocolOptions:
    """Comportement applicatif et paramètres de réception, hors moteur radio."""

    join: bool = False              # première émission de chaque dispositif = join-request
    confirmed_uplinks: bool = False  # uplinks de données confirmés (ACK attendu)
    downlink_every: int = 0         # 0 : aucune charge en file ; N : une charge par N uplinks acceptés
    downlink_payload_bytes: int = 10  # charge des downlinks de données (hypothèse)
    gateway_tx_power_dbm: float = 14.0    # puissance d'émission de la passerelle (downlink)
    device_antenna_gain_dbi: float = 0.0  # gain d'antenne du dispositif (réception downlink)
    device_rx_offset_db: float = 0.0      # écart de sensibilité du récepteur réel (0 = SX1276)


@dataclass(frozen=True)
class DeviceRadio:
    """Paramètres radio d'un dispositif : fréquence, DR montant, RX1 et puissance d'émission."""

    freq_hz: int
    dr: Optional[int]        # None si aucun plan régional
    rx1_hz: int              # fréquence de la fenêtre RX1 (égale à freq_hz sans plan)
    tx_power_dbm: float = 14.0
    rx1_sf: int = 7          # SF du débit RX1 (récepteur du dispositif)
    rx1_bw_hz: int = 125_000


@dataclass(frozen=True)
class HopEvent:
    from_id: str
    to_id: str
    t_ns: int
    freq_hz: int
    dr: Optional[int]
    rssi_dbm: Optional[float]
    outcome: str


@dataclass(frozen=True)
class ProtocolEvent:
    seq: int
    t_ns: int
    kind: str
    device_index: int
    gateway_index: int
    hops: tuple[HopEvent, ...]
    outcome: str


@dataclass(frozen=True)
class TraceRun:
    per_device: tuple[Counters, ...]
    totals: Counters
    gateway: GatewayLoad
    records: tuple[TxRecord, ...]
    events: tuple[ProtocolEvent, ...]
    gateway_tx: tuple[tuple[int, int], ...]  # émissions de la passerelle [début, fin) (ns)
    # Boucle fermée seulement (None sur le chemin historique) :
    mac_queue: Optional[MacQueueCounters] = None  # file MAC (commandes ponctuelles)
    mac_bytes: Optional[MacByteAccounting] = None  # octets réservés / émis / confirmés


@dataclass(frozen=True)
class _Job:
    """Réponse de la passerelle attendue pour une trame montante reçue."""

    record: int           # index dans la trace
    device: int
    kind: str             # join_accept | ack | downlink
    content: str          # issue si reçue : delivered | ack_only | data | data_ack
    t_open: int           # ouverture de la fenêtre RX1 du dispositif
    airtime_ns: int       # durée d'émission du downlink
    rx1_hz: int
    received: bool        # réception par le dispositif (réciprocité)
    device_missed: bool   # le dispositif émet pendant sa fenêtre RX1
    fopts: bytes = b""    # commandes MAC en FOpts du downlink (LinkCheckAns, DevStatusReq)
    link_margin: int = 0  # marge rapportée par LinkCheckAns (dB, si présente)
    carries_ds: bool = False  # le downlink porte DevStatusReq (réponse attendue si reçue)


def _dev(i: int) -> str:
    return f"dev:{i}"


_DATR = re.compile(r"^SF(\d+)BW(\d+)$")


def _radio(plan: Optional[Plan], freq_hz: int, sf: int, tx_power_dbm: float) -> DeviceRadio:
    if plan is None:
        return DeviceRadio(freq_hz=freq_hz, dr=None, rx1_hz=freq_hz, tx_power_dbm=tx_power_dbm,
                           rx1_sf=sf, rx1_bw_hz=125_000)
    dr = next((i for i, (s, bw, _) in enumerate(plan.dr_table()) if s == sf and bw == 125), None)
    rx1_hz, rx1_sf, rx1_bw_hz = freq_hz, sf, 125_000
    if dr is not None:
        try:
            ch = plan.channel_index(freq_hz / 1_000_000)
            rx1_mhz, rx1_datr = plan.rx1(dr, ch)
            rx1_hz = round(rx1_mhz * 1_000_000)
            m = _DATR.match(rx1_datr)
            if m is not None:
                rx1_sf, rx1_bw_hz = int(m.group(1)), int(m.group(2)) * 1000
        except ValueError:
            rx1_hz = freq_hz
    return DeviceRadio(freq_hz=freq_hz, dr=dr, rx1_hz=rx1_hz, tx_power_dbm=tx_power_dbm,
                       rx1_sf=rx1_sf, rx1_bw_hz=rx1_bw_hz)


def _rx2_spreading_factor(scenario: Scenario) -> int:
    """SF du repli RX2 des descentes : celui du plan régional des groupes (12 sans plan, valeur
    EU868 par défaut). Un seul SF par scénario : des régions aux RX2 différentes sont refusées."""
    sfs = set()
    for g in scenario.model.groups:
        if g.region is None:
            continue
        try:
            sfs.add(get_plan(g.region).rx2_spreading_factor())
        except ValueError:
            continue
    if len(sfs) > 1:
        raise ValueError("descentes : les régions du scénario ont des RX2 différentes "
                         f"(SF {sorted(sfs)}) ; un seul débit de repli par scénario")
    return sfs.pop() if sfs else 12


def device_radios(scenario: Scenario) -> tuple[DeviceRadio, ...]:
    """Paramètres radio de chaque dispositif, dans l'ordre de `Scenario.deploy`."""
    _devices, group_of, _ = scenario.deploy()
    by_name = {g.name: g for g in scenario.model.groups}
    radios = []
    for name in group_of:
        g = by_name[name]
        plan: Optional[Plan] = None
        if g.region is not None:
            try:
                plan = get_plan(g.region)
            except ValueError:
                plan = None
        radios.append(_radio(plan, g.channel_freq_hz, g.spreading_factor, g.tx_power_dbm))
    return tuple(radios)


def _downlink_airtime_ns(radio: DeviceRadio, payload_bytes: int) -> int:
    """Temps d'antenne d'un downlink sur le débit RX1 (CR 4/5, en-tête explicite, sans CRC)."""
    sf, bw = radio.rx1_sf, radio.rx1_bw_hz
    symbol_s = (2 ** sf) / bw
    config = RadioConfig(spreading_factor=sf, bandwidth_hz=bw, coding_rate=1, crc_on=False,
                         explicit_header=True, low_data_rate_optimize=symbol_s > 0.016)
    return time_on_air_ns(config, payload_bytes)


def _received_by_device(r: TxRecord, radio: DeviceRadio, options: ProtocolOptions) -> bool:
    """Réciprocité : RSSI descendant = RSSI montant - P_dev + P_gw + G_dev."""
    rssi_dl = (r.rssi_dbm - radio.tx_power_dbm + options.gateway_tx_power_dbm
               + options.device_antenna_gain_dbi)
    threshold = receiver_sensitivity_dbm(radio.rx1_sf, radio.rx1_bw_hz) + options.device_rx_offset_db
    return rssi_dl >= threshold


def _join_roles(records: Sequence[TxRecord], joined: dict[int, int],
                options: ProtocolOptions) -> list[bool]:
    """Rôle de chaque émission : join-request tant que le dispositif n'a pas reçu son join-accept.

    `joined[d]` : instant (ns) où le join-accept de d est entièrement reçu (fin de transmission).
    Une émission démarrée avant cet instant est une join-request, sinon une donnée. Identique au
    multi (`engine.cpp`, `joined_at`).
    """
    if not options.join:
        return [False] * len(records)
    return [not (r.device_index in joined and r.start_ns >= joined[r.device_index])
            for r in records]


def _joined_times(jobs: Sequence[_Job], starts: Sequence[Optional[int]]) -> dict[int, int]:
    """Instant de réception complète du premier join-accept délivré, par dispositif."""
    out: dict[int, int] = {}
    for k, job in enumerate(jobs):
        start = starts[k]
        if job.kind != "join_accept" or start is None or job.device_missed or not job.received:
            continue
        end = start + job.airtime_ns
        out[job.device] = min(out.get(job.device, end), end)
    return out


_MAC_NAME = {LinkCheckReq: "LinkCheckReq", DevStatusReq: "DevStatusReq", DeviceTimeReq: "DeviceTimeReq"}


def _mac_ranks(records: Sequence[TxRecord]) -> list[int]:
    """Rang 1-based de chaque émission parmi les émissions de son dispositif (ordre de trace)."""
    count: dict[int, int] = defaultdict(int)
    ranks = []
    for r in records:
        count[r.device_index] += 1
        ranks.append(count[r.device_index])
    return ranks


def _link_margin_db(r: TxRecord, installation_db: int) -> int:
    """Marge rapportée par LinkCheckAns : RSSI montant - sensibilité de réception (SX1276, 125 kHz,
    SF de l'émission) - marge d'installation, en dB entiers par défaut, bornée à 0..254.
    Indicative : c'est la marge au-dessus du seuil de perte du simulateur, pas la marge SNR
    normative."""
    margin = math.floor(r.rssi_dbm - receiver_sensitivity_dbm(r.spreading_factor, 125_000)
                        - installation_db)
    return max(0, min(254, margin))


def _downlink_jobs(records: Sequence[TxRecord], radios: Sequence[DeviceRadio],
                   options: ProtocolOptions, roles: Sequence[bool],
                   mac: Optional[MacSchedule] = None) -> list[_Job]:
    """Une réponse attendue par uplink reçu, dans l'ordre de la trace (un seul downlink par uplink).

    Avec `mac` :
    - un LinkCheckReq reçu est acquitté par un LinkCheckAns (downlink dédié s'il n'y en a pas) ;
    - un uplink reçu de rang multiple de `device_status_every` porte une DevStatusReq (downlink
      dédié s'il n'y en a pas). Elle est décidée par le rang, pas par le dispositif.
    Les FOpts allongent la trame, donc le temps d'antenne du downlink.
    """
    if options.downlink_every < 0:
        raise ValueError("downlink_every doit être positif ou nul")
    if not 0 <= options.downlink_payload_bytes <= 242:
        raise ValueError("downlink_payload_bytes doit être compris entre 0 et 242")

    by_device: dict[int, list[int]] = defaultdict(list)
    for i, r in enumerate(records):
        by_device[r.device_index].append(i)
    next_start: dict[int, int] = {}
    for idxs in by_device.values():
        for a, b in zip(idxs, idxs[1:]):
            next_start[a] = records[b].start_ns

    ranks = _mac_ranks(records)
    jobs: list[_Job] = []
    accepted: dict[int, int] = defaultdict(int)
    for i, r in enumerate(records):
        d = r.device_index
        radio = radios[d]
        is_join = roles[i]
        if r.outcome != TxRecord.OUTCOME_RECEIVED:
            continue

        margin: Optional[int] = None
        carries_ds = False
        if is_join:
            t_open = r.end_ns + JOIN_ACCEPT_DELAY1_NS
            kind, content = "join_accept", "delivered"
            base = JOIN_ACCEPT_BYTES
            fopts = b""
        else:
            accepted[d] += 1
            wants_answer = mac is not None and LinkCheckReq() in uplink_requests(mac, ranks[i])
            wants_time = mac is not None and DeviceTimeReq() in uplink_requests(mac, ranks[i])
            carries_ds = mac is not None and device_status_request_due(mac, ranks[i])
            if wants_answer:
                margin = _link_margin_db(r, mac.link_margin_installation_db)
            queued = options.downlink_every > 0 and accepted[d] % options.downlink_every == 0
            if queued:
                kind = "downlink"
                content = "data_ack" if options.confirmed_uplinks else "data"
                base = DATA_FRAME_OVERHEAD_BYTES + options.downlink_payload_bytes
            elif options.confirmed_uplinks:
                kind, content = "ack", "ack_only"
                base = ACK_FRAME_BYTES
            elif wants_answer or wants_time:
                kind, content = "mac_answer", "delivered"
                base = ACK_FRAME_BYTES
            elif carries_ds:
                kind, content = "downlink", "delivered"  # downlink MAC seul
                base = ACK_FRAME_BYTES
            else:
                continue
            t_open = r.end_ns + RECEIVE_DELAY1_NS
            # DeviceTimeAns : heure GPS au début de la fenêtre RX1 (époque GPS en t = 0 de la simulation).
            fopts = _downlink_fopts(margin, carries_ds,
                                    device_time_ns=t_open if wants_time else None)
        airtime = _downlink_airtime_ns(radio, base + len(fopts))

        nxt = next_start.get(i)
        jobs.append(_Job(
            record=i, device=d, kind=kind, content=content, t_open=t_open, airtime_ns=airtime,
            rx1_hz=radio.rx1_hz,
            received=_received_by_device(r, radio, options),
            device_missed=nxt is not None and nxt < t_open + RX1_WINDOW_NS,
            fopts=fopts, link_margin=margin or 0, carries_ds=carries_ds,
        ))
    return jobs


def _downlink_fopts(margin: Optional[int], carries_ds: bool,
                    device_time_ns: Optional[int] = None) -> bytes:
    """FOpts d'un downlink : LinkCheckAns (si `margin` n'est pas None), DevStatusReq (si
    `carries_ds`), DeviceTimeAns (si `device_time_ns` n'est pas None : heure GPS, époque en t = 0).
    Ordre CID croissant (LinkCheckAns 0x02, DevStatusReq 0x06, DeviceTimeAns 0x0D) ; jamais
    tronqué (15 octets au plus)."""
    cmds: list = []
    if margin is not None:
        cmds.append(LinkCheckAns(margin, 1))
    if carries_ds:
        cmds.append(DevStatusReq())
    if device_time_ns is not None:
        cmds.append(DeviceTimeAns(seconds=device_time_ns // 1_000_000_000,
                                  fraction=(device_time_ns % 1_000_000_000) * 256 // 1_000_000_000))
    fopts = b""
    for cmd in cmds:
        fopts = lsim_mac.append_fopts(fopts, cmd)
    return fopts


def _schedule_gateway(jobs: Sequence[_Job]) -> tuple[list[Optional[int]], list[tuple[int, int]]]:
    """Sérialise les downlinks sur la passerelle (un émetteur). Retourne (début par job ou None si
    perdu faute de fenêtre, intervalles d'émission)."""
    order = sorted(range(len(jobs)), key=lambda k: (jobs[k].t_open, k))
    starts: list[Optional[int]] = [None] * len(jobs)
    intervals: list[tuple[int, int]] = []
    busy_until = None
    for k in order:
        job = jobs[k]
        start = job.t_open if busy_until is None else max(job.t_open, busy_until)
        if start - job.t_open >= RX1_WINDOW_NS:
            continue  # la passerelle ne peut plus émettre dans la fenêtre du dispositif
        starts[k] = start
        busy_until = start + job.airtime_ns
        intervals.append((start, busy_until))
    return starts, intervals


def _events(records: Sequence[TxRecord], radios: Sequence[DeviceRadio], jobs: Sequence[_Job],
            starts: Sequence[Optional[int]], roles: Sequence[bool],
            mac: Optional[MacSchedule] = None) -> tuple[ProtocolEvent, ...]:
    """Événements dans l'ordre temporel, à partir de la trace et de la planification."""
    pending: list[tuple[int, int, str, int, tuple[HopEvent, ...], str]] = []

    def add(t: int, kind: str, device: int, hops: list[HopEvent], outcome: str) -> None:
        pending.append((t, len(pending), kind, device, tuple(hops), outcome))

    job_of = {job.record: k for k, job in enumerate(jobs)}
    ranks = _mac_ranks(records)
    # DevStatusAns : émise dans l'uplink suivant une DevStatusReq reçue. Confirmée seulement si
    # cet uplink est lui-même reçu par la passerelle ; sinon elle n'apparaît pas dans la trace.
    next_of: dict[int, int] = {}
    last_of: dict[int, int] = {}
    for i, r in enumerate(records):
        prev = last_of.get(r.device_index)
        if prev is not None:
            next_of[prev] = i
        last_of[r.device_index] = i
    ds_answer_at: set[int] = set()
    for k, job in enumerate(jobs):
        if not job.carries_ds or starts[k] is None or job.device_missed or not job.received:
            continue
        j = next_of.get(job.record)
        if j is not None and not roles[j] and records[j].outcome == TxRecord.OUTCOME_RECEIVED:
            ds_answer_at.add(j)
    for i, r in enumerate(records):
        d = r.device_index
        radio = radios[d]
        is_join = roles[i]
        hops = [HopEvent(_dev(d), "gw:0", r.start_ns, radio.freq_hz, radio.dr, r.rssi_dbm,
                         _HOP_OUTCOME[r.outcome])]
        if r.outcome == TxRecord.OUTCOME_RECEIVED:
            hops.append(HopEvent("gw:0", "ns", r.end_ns, radio.freq_hz, radio.dr, None,
                                 "delivered"))
        add(r.start_ns, "join_request" if is_join else "uplink", d, hops,
            _UPLINK_OUTCOME[r.outcome])
        if mac is not None and not is_join:
            for cmd in uplink_requests(mac, ranks[i]):
                # Annotation : la trame est déjà dessinée par l'événement uplink ; pas de saut dupliqué.
                add(r.start_ns, "mac_request", d, [], _MAC_NAME[type(cmd)])
        if i in ds_answer_at:
            add(r.start_ns, "mac_answer", d, [], "DevStatusAns")

        k = job_of.get(i)
        if k is None:
            continue
        job = jobs[k]
        start = starts[k]
        if start is None:
            hop = HopEvent("gw:0", _dev(d), job.t_open, job.rx1_hz, None, None, "not_listened")
            add(job.t_open, "rx_window_missed", d, [hop], "gateway_busy")
            continue
        if job.device_missed:
            hop = HopEvent("gw:0", _dev(d), start, job.rx1_hz, None, None, "not_listened")
            add(job.t_open, "rx_window_missed", d, [hop], "device_transmitting")
            continue
        ok = job.received
        down_hop = HopEvent("gw:0", _dev(d), start, job.rx1_hz, None, None,
                            "delivered" if ok else "lost_sensitivity")
        if job.kind == "join_accept":
            down = [HopEvent("ns", "gw:0", start, job.rx1_hz, None, None, "delivered"), down_hop]
        else:
            down = [down_hop]
        add(start, job.kind, d, down, job.content if ok else "lost_sensitivity")
        # Commandes MAC portées par un downlink reçu. Un job `mac_answer` est déjà l'événement de
        # sa réponse LinkCheckAns ; une DevStatusReq est toujours annotée. Un downlink perdu
        # n'apporte ni réponse ni requête.
        if ok and job.fopts:
            cmds = lsim_mac.decode_all(job.fopts, downlink=True)
            # Une seule réponse par descente, même si elle acquitte plusieurs requêtes.
            answers = [c for c in cmds if isinstance(c, (LinkCheckAns, DeviceTimeAns))]
            if answers and job.kind != "mac_answer":
                add(start, "mac_answer", d, [], "delivered")
            for cmd in cmds:
                if isinstance(cmd, DevStatusReq):
                    add(start, "mac_request", d, [], "DevStatusReq")

    if len(pending) > MAX_EVENTS:
        raise ValueError(f"trop d'événements ({len(pending)} ; limite {MAX_EVENTS})")
    pending.sort(key=lambda e: (e[0], e[1]))
    return tuple(
        ProtocolEvent(seq=k, t_ns=t, kind=kind, device_index=d, gateway_index=0,
                      hops=hops, outcome=outcome)
        for k, (t, _order, kind, d, hops, outcome) in enumerate(pending)
    )


def _plan(records: Sequence[TxRecord], radios: Sequence[DeviceRadio], options: ProtocolOptions,
          joined: dict[int, int], mac: Optional[MacSchedule] = None):
    """Une passe de planification : rôles, downlinks, émissions passerelle, jointures obtenues."""
    roles = _join_roles(records, joined, options)
    jobs = _downlink_jobs(records, radios, options, roles, mac)
    starts, busy = _schedule_gateway(jobs)
    return roles, jobs, starts, busy, _joined_times(jobs, starts)


def build_protocol_events(records: Sequence[TxRecord], radios: Sequence[DeviceRadio],
                          options: ProtocolOptions,
                          mac: Optional[MacSchedule] = None) -> tuple[ProtocolEvent, ...]:
    """Événements dérivés d'une trace déjà produite (sans nouvelle itération du moteur).

    Les émissions passerelle sont celles des downlinks planifiés à partir de cette trace : seul
    l'état des jointures est itéré. Pour une trace cohérente avec le moteur, utiser `build_trace`.
    """
    joined: dict[int, int] = {}
    for _ in range(MAX_ITERATIONS):
        roles, jobs, starts, _busy, new_joined = _plan(records, radios, options, joined, mac)
        if new_joined == joined:
            return _events(records, radios, jobs, starts, roles, mac)
        joined = new_joined
    raise RuntimeError("pas de point fixe pour les jointures (build_protocol_events)")


def _schedule_of(scenario: Scenario) -> Optional[MacSchedule]:
    """Calendrier MAC du scénario ; None si le bloc `mac:` est absent ou désactivé."""
    m = scenario.model.mac
    if m is None or (m.link_check_every == 0 and m.device_status_every == 0
                     and m.device_time_every == 0):
        return None
    return MacSchedule(link_check_every=m.link_check_every,
                       device_status_every=m.device_status_every,
                       link_margin_installation_db=m.link_margin_installation_db,
                       device_time_every=m.device_time_every)


def mac_reservations(scenario: Scenario, devices) -> tuple[tuple[int, int, int], ...]:
    """Calendrier des octets MAC réservés : triplets (index de dispositif, rang, octets).

    Calculé avant la simulation, à partir du scénario seul : même scénario, mêmes réservations. Les
    réservations sont conservatrices (voir `lsim.mac_plan`).
    """
    schedule = _schedule_of(scenario)
    if schedule is None:
        return ()
    out = []
    for i, d in enumerate(devices):
        for rank, extra in mac_plan.reservations(schedule, d.messages):
            out.append((i, rank, extra))
    return tuple(out)


def _native_plan_applies(options: ProtocolOptions, mac: Optional[MacSchedule]) -> bool:
    """Planification des descentes en natif (S0) : passerelle unique, sans jointure ni commande MAC.

    Ces cas sont couverts par la parité avec la version Python (`tests/test_downlink_plan_parity.py`).
    Les autres restent sur la version Python.
    """
    return not options.join and mac is None


def _build_trace_native(devices, radios, gateway, propagation, environment,
                        options: ProtocolOptions) -> TraceRun:
    """Trace causale (S1) : une seule exécution, descentes planifiées à la fin de chaque trame.

    Pas de point fixe : l'occupation passerelle utilisée par le moteur est celle que produit le
    planificateur natif sur la trace obtenue (contrôle d'égalité, sans itération).
    """
    from lsim.downlink_plan import plan_native, simulate_causal
    result, busy = simulate_causal(devices, gateway, propagation, environment, radios, options)
    events, plan_busy = plan_native(result.records, radios, options)
    if tuple(plan_busy) != tuple(busy):
        raise RuntimeError("occupation passerelle incohérente entre le moteur et le planificateur")
    if len(events) > MAX_EVENTS:
        raise ValueError(f"trop d'événements ({len(events)} ; limite {MAX_EVENTS})")
    return TraceRun(per_device=result.per_device, totals=result.totals,
                    gateway=result.gateway, records=result.records, events=events,
                    gateway_tx=tuple(busy))


def build_trace(scenario: Scenario, options: ProtocolOptions = ProtocolOptions()) -> TraceRun:
    """Déploie le scénario et calcule la trace cohérente avec les émissions de la passerelle.

    Point fixe : les trames montantes dépendent des émissions passerelle, qui dépendent des
    uplinks reçus. L'itération s'arrête quand les émissions utilisées par le moteur sont celles
    que produit la trace obtenue. Pas de convergence en `MAX_ITERATIONS` : erreur explicite.
    """
    devices, group_of, _indices = scenario.deploy()
    if sum(d.messages for d in devices) > MAX_TRACE_RECORDS:
        raise ValueError(f"trace limitée à {MAX_TRACE_RECORDS} émissions par simulation")
    radios = device_radios(scenario)
    gateway, propagation, environment = scenario.gateway(), scenario.propagation(), scenario.environment
    from lsim.mac_loop import closed_loop_applies  # import local : évite un cycle
    if closed_loop_applies(scenario):
        # LinkADR / DutyCycle : une seule exécution native, descentes créées par le moteur.
        return _build_trace_closed_loop(scenario, devices, group_of, radios, gateway, propagation,
                                        environment, options)
    mac = _schedule_of(scenario)
    reservations = mac_reservations(scenario, devices)

    if _native_plan_applies(options, mac):
        return _build_trace_native(devices, radios, gateway, propagation, environment, options)

    return _build_trace_python(devices, radios, gateway, propagation, environment, reservations,
                               options, mac)


def build_trace_closed_loop(scenario: Scenario, options: ProtocolOptions = ProtocolOptions()) -> TraceRun:
    """Trace produite par la boucle fermée, même sans LinkADR ni DutyCycle.

    Sert à vérifier la parité avec le chemin historique (`build_trace`) sur les réservations MAC.
    `build_trace` n'emprunte ce chemin que si `closed_loop_applies` est vrai.
    """
    devices, group_of, _indices = scenario.deploy()
    if sum(d.messages for d in devices) > MAX_TRACE_RECORDS:
        raise ValueError(f"trace limitée à {MAX_TRACE_RECORDS} émissions par simulation")
    return _build_trace_closed_loop(scenario, devices, group_of, device_radios(scenario),
                                    scenario.gateway(), scenario.propagation(),
                                    scenario.environment, options)


def _build_trace_closed_loop(scenario, devices, group_of, radios, gateway, propagation, environment,
                             options: ProtocolOptions) -> TraceRun:
    """Boucle fermée S2/S3 : une exécution, uplinks, réservations MAC et descentes du moteur natif."""
    from lsim.closed_loop import OUTCOME_CODES, simulate_closed_loop
    from lsim.mac_loop import (
        check_closed_loop, loop_options, loop_regions, mac_byte_accounting, mac_slots,
    )
    check_closed_loop(scenario, options)
    schedule = _schedule_of(scenario)
    out = simulate_closed_loop(devices, gateway, propagation, environment, radios,
                               loop_regions(scenario, group_of), loop_options(scenario, options),
                               mac=mac_slots(schedule, devices))
    records = tuple(
        TxRecord(u.device, u.start_ns, u.end_ns, u.spreading_factor, u.rssi_dbm,
                 OUTCOME_CODES[u.outcome])
        for u in out.uplinks)
    events = _closed_loop_events(out, radios, options, schedule)
    return TraceRun(per_device=out.per_device, totals=out.totals, gateway=out.load, records=records,
                    events=events, gateway_tx=out.busy, mac_queue=out.mac_queue,
                    mac_bytes=mac_byte_accounting(schedule, devices, out.uplinks))


def _closed_loop_events(out, radios: Sequence[DeviceRadio], options: ProtocolOptions,
                        mac: Optional[MacSchedule] = None) -> tuple[ProtocolEvent, ...]:
    """Événements de la boucle fermée, au même format et au même ordre que `_events`.

    Pour chaque uplink : l'uplink, ses requêtes du calendrier, la réponse DevStatusAns s'il y a
    lieu, puis la descente qui lui répond (le moteur en crée au plus une par uplink reçu).
    """
    from lsim.closed_loop import (
        ANSWER_DEVICE_STATUS, CMD_DEVICE_STATUS, CMD_DEVICE_TIME, CMD_DUTY_CYCLE, CMD_LINK_ADR,
        CMD_LINK_CHECK, OUTCOME_CODES,
    )
    pending: list[tuple[int, int, str, int, tuple[HopEvent, ...], str]] = []

    def add(t: int, kind: str, device: int, hops: list[HopEvent], outcome: str) -> None:
        pending.append((t, len(pending), kind, device, tuple(hops), outcome))

    down_of = {dl.uplink: dl for dl in out.downlinks}
    rank_of: dict[int, int] = defaultdict(int)
    for a, u in enumerate(out.uplinks):
        rank_of[u.device] += 1
        code = OUTCOME_CODES[u.outcome]
        radio = radios[u.device]
        hops = [HopEvent(_dev(u.device), "gw:0", u.start_ns, radio.freq_hz, radio.dr, u.rssi_dbm,
                         _HOP_OUTCOME[code])]
        received = code == TxRecord.OUTCOME_RECEIVED
        if received:
            hops.append(HopEvent("gw:0", "ns", u.end_ns, radio.freq_hz, radio.dr, None, "delivered"))
        add(u.start_ns, "uplink", u.device, hops, _UPLINK_OUTCOME[code])
        if mac is not None:
            for cmd in uplink_requests(mac, rank_of[u.device]):
                add(u.start_ns, "mac_request", u.device, [], _MAC_NAME[type(cmd)])
        if received:
            # Réponses portées par cet uplink : confirmées parce qu'il est reçu.
            if u.answer_mask & 1:
                add(u.start_ns, "mac_answer", u.device, [], "LinkADRAns")
            if u.answer_mask & 2:
                add(u.start_ns, "mac_answer", u.device, [], "DutyCycleAns")
            if u.answer_mask & ANSWER_DEVICE_STATUS:
                add(u.start_ns, "mac_answer", u.device, [], "DevStatusAns")

        dl = down_of.get(a)
        if dl is None:
            continue
        radio = radios[dl.device]
        dev = _dev(dl.device)
        if dl.start_ns is None:
            hop = HopEvent("gw:0", dev, dl.t_open_ns, radio.rx1_hz, None, None, "not_listened")
            add(dl.t_open_ns, "rx_window_missed", dl.device, [hop], "gateway_busy")
            continue
        if dl.device_missed:
            hop = HopEvent("gw:0", dev, dl.start_ns, radio.rx1_hz, None, None, "not_listened")
            add(dl.t_open_ns, "rx_window_missed", dl.device, [hop], "device_transmitting")
            continue
        ok = dl.delivered
        down_hop = HopEvent("gw:0", dev, dl.start_ns, radio.rx1_hz, None, None,
                            "delivered" if ok else "lost_sensitivity")
        answers = bool(dl.commands & (CMD_LINK_CHECK | CMD_DEVICE_TIME))
        if dl.kind == "ack":
            kind, content = "ack", "ack_only"
        elif dl.kind == "data":
            kind = "downlink"
            content = "data_ack" if options.confirmed_uplinks else "data"
        elif answers:
            kind, content = "mac_answer", "delivered"  # downlink MAC seul portant une réponse
        else:
            kind, content = "downlink", "delivered"  # downlink MAC seul
        add(dl.start_ns, kind, dl.device, [down_hop], content if ok else "lost_sensitivity")
        if ok:
            # Une réponse par descente, même si elle acquitte plusieurs requêtes (comme `_events`).
            if answers and kind != "mac_answer":
                add(dl.start_ns, "mac_answer", dl.device, [], "delivered")
            if dl.commands & CMD_LINK_ADR:
                add(dl.start_ns, "mac_request", dl.device, [], "LinkADRReq")
            if dl.commands & CMD_DUTY_CYCLE:
                add(dl.start_ns, "mac_request", dl.device, [], "DutyCycleReq")
            if dl.commands & CMD_DEVICE_STATUS:
                add(dl.start_ns, "mac_request", dl.device, [], "DevStatusReq")

    if len(pending) > MAX_EVENTS:
        raise ValueError(f"trop d'événements ({len(pending)} ; limite {MAX_EVENTS})")
    pending.sort(key=lambda e: (e[0], e[1]))
    return tuple(
        ProtocolEvent(seq=k, t_ns=t, kind=kind, device_index=d, gateway_index=0, hops=hops,
                      outcome=outcome)
        for k, (t, _order, kind, d, hops, outcome) in enumerate(pending))


def _build_trace_python(devices, radios, gateway, propagation, environment, reservations,
                        options: ProtocolOptions, mac: Optional[MacSchedule]) -> TraceRun:
    """Point fixe Python (oracle, et chemin avec jointure ou MAC) : voir `build_trace`."""
    busy: list[tuple[int, int]] = []
    joined: dict[int, int] = {}
    for _ in range(MAX_ITERATIONS):
        result = simulate_uplinks_trace(devices, gateway, propagation, environment,
                                        gateway_busy=busy, reservations=reservations)
        roles, jobs, starts, new_busy, new_joined = _plan(result.records, radios, options, joined,
                                                          mac)
        if new_busy == busy and new_joined == joined:
            events = _events(result.records, radios, jobs, starts, roles, mac)
            return TraceRun(
                per_device=result.per_device,
                totals=result.totals,
                gateway=result.gateway,
                records=result.records,
                events=events,
                gateway_tx=tuple(busy),
            )
        busy, joined = new_busy, new_joined
    raise RuntimeError(
        f"pas de point fixe entre trames montantes et émissions passerelle "
        f"après {MAX_ITERATIONS} itérations")


# --- Passerelles multiples -------------------------------------------------------------------

_MULTI_UPLINK_OUTCOME = {0: "lost_sensitivity", 1: "lost_collision", 2: "received",
                         3: "lost_gateway_busy"}
# Saut mesh (journal natif) -> issue de l'événement `mesh_hop`.
_MESH_HOP_OUTCOME = {"received": "delivered", "lost_collision": "lost_collision",
                     "lost_half_duplex": "lost_half_duplex", "suppressed": "suppressed"}
MESH_BAND_HZ = 2_400_000_000
_MULTI_HOP_OUTCOME = {0: "lost_sensitivity", 1: "lost_collision", 2: "delivered", 3: "not_listened"}
_MULTI_DOWNLINK_OUTCOME = {0: "delivered", 1: "lost_sensitivity", 2: "gateway_busy",
                           3: "device_transmitting"}


# Retour mesh : bornes de la boucle à point fixe (ordonnancement des descentes ↔ trace).
MAX_MESH_RETURN_ITERATIONS = 64
# Une trame mesh (enveloppe comprise) fait 255 o au plus (`lsim.mesh.forward_frames`).
MAX_MESH_UPLINK_PAYLOAD_BYTES = 255 - MESH_ENVELOPE_UP_BYTES - DATA_FRAME_OVERHEAD_BYTES  # 228
MAX_MESH_DOWNLINK_PAYLOAD_BYTES = 255 - MESH_ENVELOPE_DOWN_BYTES - DATA_FRAME_OVERHEAD_BYTES  # 227


def mesh_payload_problem(scenario: Scenario, options: ProtocolOptions) -> Optional[tuple[str, str]]:
    """(champ, message) si une charge ne tient pas dans une trame mesh, sinon None.

    Refus anticipé : sans cela, la passe mesh échoue à l'exécution. Montant : seulement si un
    relais achemine (taille « device »). Descente : charge des downlinks de données.
    """
    cfg = scenario.model.mesh
    if cfg is None:
        return None
    if options.downlink_every > 0 and options.downlink_payload_bytes > MAX_MESH_DOWNLINK_PAYLOAD_BYTES:
        return ("protocol.downlink_payload_bytes",
                f"charge de descente de {options.downlink_payload_bytes} o : une trame mesh "
                f"est bornée à 255 o, enveloppe de {MESH_ENVELOPE_DOWN_BYTES} o et en-tête "
                f"comprises (maximum {MAX_MESH_DOWNLINK_PAYLOAD_BYTES} o sur mesh)")
    relays = any(g.mesh and g.name != cfg.border for g in scenario.gateway_models())
    if relays and cfg.frame_size == "device":
        biggest = max((g.payload_bytes for g in scenario.model.groups), default=0)
        if biggest > MAX_MESH_UPLINK_PAYLOAD_BYTES:
            return ("scenario",
                    f"charge montante de {biggest} o : une trame relayée est bornée à 255 o, "
                    f"enveloppe de {MESH_ENVELOPE_UP_BYTES} o comprise (maximum "
                    f"{MAX_MESH_UPLINK_PAYLOAD_BYTES} o sur mesh)")
    return None
# Départ au plus tôt d'une descente qui n'est pas acheminée (sentinelle natif : jamais).
MESH_NEVER_NS = (1 << 63) - 1


@dataclass(frozen=True)
class MeshLoad:
    """Charge mesh d'une passerelle relais : ses émissions (uplink et descente) sur la bande 2,4 GHz.

    `transmissions` : sauts émis ; `busy_ns` : somme de leur durée ; `lost_collision` et
    `lost_half_duplex` : ses émissions perdues à la réception ; `suppressed` : copies abandonnées
    (doublon déjà relayé). Les passes uplink et descente ne partagent pas le temps d'antenne.
    """

    transmissions: int = 0
    busy_ns: int = 0
    lost_collision: int = 0
    lost_half_duplex: int = 0
    suppressed: int = 0


@dataclass(frozen=True)
class MultiTraceRun:
    """Trace multi-passerelles : totaux et charges issus du même calcul natif que les événements.

    Mesh : `totals.received` et `per_device[i].received` sont les trames remises au LNS (après
    relais) ; `lost_mesh` (et `lost_mesh_by_device`) compte les trames décodées puis perdues sur le
    mesh. Hors mesh : `lost_mesh`, `lost_mesh_by_device` et `mesh_loads` valent None. Avec mesh,
    `mesh_loads` vaut None pour chaque passerelle sans mesh.
    """

    per_device: tuple[Counters, ...]
    totals: Counters
    per_gateway: tuple  # GatewayRxCounters, dans l'ordre de `gateway_names`
    gateway_names: tuple[str, ...]
    events: tuple[ProtocolEvent, ...]
    lost_mesh: Optional[int] = None
    lost_mesh_by_device: Optional[tuple[int, ...]] = None
    mesh_loads: Optional[tuple[Optional[MeshLoad], ...]] = None  # `gateway_names` ; None sans mesh


def _finite_or_none(x: float) -> Optional[float]:
    return float(x) if x == x and abs(x) != float("inf") else None


def _message_index(devices, trace) -> tuple[list[int], dict[tuple[int, int], int]]:
    """Indice d'émission (ordre du moteur : dispositifs dans l'ordre, puis k) de chaque
    enregistrement de trace, et index (dispositif, fin) -> enregistrement."""
    offsets, acc = [], 0
    for d in devices:
        offsets.append(acc)
        acc += d.messages
    if len(trace) != acc:
        raise RuntimeError("trace : nombre d'émissions incohérent")
    rank = [0] * len(devices)
    msg_of = [0] * len(trace)
    rec_by_end: dict[tuple[int, int], int] = {}
    for i in sorted(range(len(trace)), key=lambda i: (trace[i].device_index, trace[i].start_ns)):
        d = trace[i].device_index
        msg_of[i] = offsets[d] + rank[d]
        rank[d] += 1
        rec_by_end[(d, trace[i].end_ns)] = i
    return msg_of, rec_by_end


@dataclass(frozen=True)
class _MeshReturn:
    ready: list                # départ au plus tôt par émission (natif : -1 ou instant ; NEVER)
    status: dict               # descente (indice) -> "mesh" | "lost_mesh" | "uplink_lost"
    arrival: dict              # descente (indice) -> arrivée au relais (si "mesh")
    t_border: dict             # descente (indice) -> départ à la frontière
    routes: dict               # descente (indice) -> MeshDownlinkRoute


def _downlink_phy_bytes(dl, options: ProtocolOptions) -> int:
    if dl.join:
        return JOIN_ACCEPT_BYTES
    if dl.data:
        return DATA_FRAME_OVERHEAD_BYTES + options.downlink_payload_bytes
    return ACK_FRAME_BYTES


def _downlink_requests(scenario: Scenario, models, options: ProtocolOptions, result,
                       delay_in: dict, msg_of: list[int], rec_by_end: dict):
    """Descentes à acheminer sur le mesh : une par descente vers un relais.

    `delay_in` : pour chaque émission (message) remise au LNS, délai de sa copie utile jusqu'à la
    frontière. Une descente dont l'uplink n'y figure pas n'est pas émise (`uplink_lost`).
    """
    border = scenario.model.mesh.border
    relays = {g.name for g in models if g.mesh and g.name != border}
    names = [g.name for g in models]
    requests = []
    pre_status: dict = {}
    msg_dl: dict = {}
    for j, dl in enumerate(result.downlinks):
        name = names[dl.gateway_index]
        if name not in relays:
            continue
        delay = JOIN_ACCEPT_DELAY1_NS if dl.join else RECEIVE_DELAY1_NS
        i = rec_by_end.get((dl.device_index, dl.t_open_ns - delay))
        if i is None:
            raise RuntimeError("retour mesh : émission d'origine introuvable")
        m = msg_of[i]
        msg_dl[j] = m
        if m not in delay_in:
            pre_status[j] = "uplink_lost"
            continue
        requests.append((j, name, result.trace[i].end_ns + delay_in[m],
                         _downlink_phy_bytes(dl, options)))
    return requests, pre_status, msg_dl


def _mesh_return(result, mesh, requests, pre_status: dict, msg_dl: dict,
                 n_messages: int) -> _MeshReturn:
    """Départs au plus tôt des descentes à partir de la passe mesh jointe."""
    ready = [-1] * n_messages
    status: dict = {}
    arrival: dict = {}
    t_border: dict = {}
    for j in pre_status:
        status[j] = pre_status[j]
        ready[msg_dl[j]] = MESH_NEVER_NS
    for j, _name, t0, _phy in requests:
        route = mesh.downlinks[j]
        t_border[j] = t0
        if route.delivered:
            status[j] = "mesh"
            arrival[j] = route.arrival_ns
            ready[msg_dl[j]] = route.arrival_ns
        else:
            status[j] = "lost_mesh"
            ready[msg_dl[j]] = MESH_NEVER_NS
    return _MeshReturn(ready=ready, status=status, arrival=arrival, t_border=t_border,
                       routes=dict(mesh.downlinks))


def _mesh_loads(models, mesh) -> tuple[Optional[MeshLoad], ...]:
    """Charge mesh par passerelle (émetteur = passerelle) : sauts montants et descendants, tous
    dans la passe jointe. None pour une passerelle sans mesh."""
    counts = {g.name: [0, 0, 0, 0, 0] for g in models if g.mesh}  # tx, busy, coll, hd, suppr
    for h in mesh.mesh_result.hops:
        c = counts[h.sender_id]
        if h.outcome == "suppressed":
            c[4] += 1
            continue
        c[0] += 1
        c[1] += h.t_end_ns - h.t_start_ns
        if h.outcome == "lost_collision":
            c[2] += 1
        elif h.outcome == "lost_half_duplex":
            c[3] += 1
    return tuple(MeshLoad(*counts[g.name]) if g.mesh else None for g in models)


def _direct_deliverer(decoded_mask: int, models, border: str) -> Optional[int]:
    """Index de la passerelle qui remet directement une trame décodée (None si aucune)."""
    decoders = [g for g in range(len(models)) if (decoded_mask >> g) & 1]
    for g in decoders:
        if models[g].name == border:
            return g
    for g in decoders:
        if not models[g].mesh:
            return g
    return None


def build_multi_trace(scenario: Scenario, options: ProtocolOptions = ProtocolOptions()) -> MultiTraceRun:
    """Trace des passerelles multiples (déduplication serveur, downlinks par la meilleure passerelle).

    Join (`options.join`) : une trame montante est une join-request tant que le dispositif n'est pas
    jointé ; la join-request décodée reçoit un join-accept à fin + 5 s par la meilleure passerelle, et
    le dispositif est jointé si ce join-accept lui parvient. Une join-request perdue est répétée à
    l'émission suivante. Ce n'est pas la règle du mono (première émission seulement) : voir docs.

    Mesh (`scenario.model.mesh`) : la passe mesh (`mesh_pass`, la même que `run_scenario`) relaie
    chaque copie vers la frontière. Un événement `mesh_hop` par émission mesh (ou copie supprimée),
    à l'instant d'émission. Une trame décodée mais non remise est une perte `lost_mesh`.
    Descentes vers un relais : acheminées depuis la frontière sur le mesh (un événement
    `mesh_downlink_hop` par saut descendant) ; elles partent au plus tôt à leur arrivée au relais.
    Perdue sur le mesh : outcome `lost_mesh`. Arrivée après la fenêtre RX1 : `mesh_late`. Une
    descente d'un uplink non remis au LNS n'est pas émise. Ces descentes occupent la passerelle
    relais comme les autres. Boucle à point fixe (descentes ↔ trace), bornée par
    `MAX_MESH_RETURN_ITERATIONS`.

    Les totaux, les compteurs par dispositif et la charge par passerelle viennent du même appel natif
    (`simulate_multi_downlinks`) que les événements : ils concordent par construction.
    """
    problem = mesh_payload_problem(scenario, options)
    if problem is not None:
        raise ValueError(problem[1])
    devices, _group_of, _indices = scenario.deploy()
    if sum(d.messages for d in devices) > MAX_TRACE_RECORDS:
        raise ValueError(f"trace limitée à {MAX_TRACE_RECORDS} émissions par simulation")
    radios = device_radios(scenario)
    models = scenario.gateway_models()
    names = tuple(g.name for g in models)
    gateways = scenario.gateways()
    rule = DownlinkRule(ack_uplinks=options.confirmed_uplinks, every=options.downlink_every,
                        payload_bytes=options.downlink_payload_bytes,
                        gateway_tx_power_dbm=options.gateway_tx_power_dbm,
                        device_antenna_gain_dbi=options.device_antenna_gain_dbi,
                        device_rx_offset_db=options.device_rx_offset_db,
                        join=options.join, rx2_sf=_rx2_spreading_factor(scenario))
    mesh = None
    plan: Optional[_MeshReturn] = None
    if scenario.model.mesh is None:
        result = simulate_multi_downlinks(devices, gateways, scenario.propagation(), rule,
                                          scenario.environment)
    else:
        # Point fixe sur (départs au plus tôt des descentes, délai frontière de chaque uplink) :
        # la passe jointe (montant et descente partagent le temps d'antenne) dépend des descentes,
        # qui dépendent des arrivées à la frontière. Les émissions sont indexées par message,
        # stables d'une itération à l'autre (seul leur résultat change).
        total = sum(d.messages for d in devices)
        ready: list = [-1] * total
        delay_in: dict = {m: 0 for m in range(total)}  # hypothèse initiale : frontière directe
        for _ in range(MAX_MESH_RETURN_ITERATIONS):
            result = simulate_multi_downlinks(devices, gateways, scenario.propagation(), rule,
                                              scenario.environment, dl_ready_ns=ready)
            msg_of, rec_by_end = _message_index(devices, result.trace)
            requests, pre_status, msg_dl = _downlink_requests(scenario, models, options, result,
                                                              delay_in, msg_of, rec_by_end)
            mesh = mesh_pass(scenario, devices, models, result.trace, with_hops=True,
                             downlinks=requests)
            decoded = {i for i, r in enumerate(result.trace) if r.outcome == 2}
            if not mesh.delivered_frames <= decoded:
                raise RuntimeError("mesh : trame remise sans avoir été décodée (incohérent)")
            plan = _mesh_return(result, mesh, requests, pre_status, msg_dl, total)
            delay_out = {msg_of[i]: mesh.border_delay_ns[i] for i in mesh.delivered_frames}
            if plan.ready == ready and delay_out == delay_in:
                break
            ready, delay_in = plan.ready, delay_out
        else:
            raise RuntimeError("retour mesh : pas de point fixe après "
                               f"{MAX_MESH_RETURN_ITERATIONS} itérations")
    delivered: frozenset = mesh.delivered_frames if mesh is not None else frozenset()
    pending: list[tuple[int, int, str, int, int, tuple[HopEvent, ...], str]] = []

    def add(t: int, kind: str, device: int, gw: int, hops: list[HopEvent], outcome: str) -> None:
        pending.append((t, len(pending), kind, device, gw, tuple(hops), outcome))

    for i_rec, r in enumerate(result.trace):
        d = r.device_index
        radio = radios[d]
        best = r.best_gateway
        to_id = f"gw:{names[best]}" if best >= 0 else "gw:none"
        hops = [HopEvent(_dev(d), to_id, r.start_ns, radio.freq_hz, radio.dr,
                         _finite_or_none(r.best_rssi_dbm), _MULTI_HOP_OUTCOME[r.outcome])]
        outcome = _MULTI_UPLINK_OUTCOME[r.outcome]
        if mesh is not None and r.outcome == 2:
            if i_rec in delivered and i_rec in mesh.via_mesh_frames:
                # Remise par la frontière, après le délai de la copie utile (saut mesh inclus).
                arrival = r.end_ns + mesh.border_delay_ns.get(i_rec, 0)
                hops.append(HopEvent(f"gw:{scenario.model.mesh.border}", "ns", arrival,
                                     radio.freq_hz, radio.dr, None, "delivered"))
            elif i_rec in delivered:
                # Remise directe : la passerelle qui remet est la frontière si elle a décodé,
                # sinon une passerelle à backhaul IP (le « meilleur » RSSI peut être un relais).
                deliverer = _direct_deliverer(r.decoded_mask, models, scenario.model.mesh.border)
                src = f"gw:{names[deliverer]}" if deliverer is not None else to_id
                hops.append(HopEvent(src, "ns", r.end_ns, radio.freq_hz, radio.dr, None, "delivered"))
            else:
                outcome = "lost_mesh"
        elif r.outcome == 2 and best >= 0:
            hops.append(HopEvent(to_id, "ns", r.end_ns, radio.freq_hz, radio.dr, None, "delivered"))
        kind = "join_request" if r.join_request else "uplink"
        add(r.start_ns, kind, d, max(best, 0), hops, outcome)

    if mesh is not None:
        idx_of = {name: k for k, name in enumerate(names)}
        for h in mesh.uplink_hops:
            d = result.trace[h.frame_id].device_index
            hop = HopEvent(f"gw:{h.sender_id}", f"gw:{h.receiver_id}", h.t_start_ns, MESH_BAND_HZ,
                           None, None, _MESH_HOP_OUTCOME[h.outcome])
            add(h.t_start_ns, "mesh_hop", d, idx_of[h.sender_id], [hop],
                _MESH_HOP_OUTCOME[h.outcome])
        for j, route in plan.routes.items():
            dl = result.downlinks[j]
            for h in route.hops:
                hop = HopEvent(f"gw:{h.sender_id}", f"gw:{h.receiver_id}", h.t_start_ns,
                               MESH_BAND_HZ, None, None, _MESH_HOP_OUTCOME[h.outcome])
                add(h.t_start_ns, "mesh_downlink_hop", dl.device_index, idx_of[h.sender_id],
                    [hop], _MESH_HOP_OUTCOME[h.outcome])

    for j, dl in enumerate(result.downlinks):
        d, g = dl.device_index, dl.gateway_index
        radio = radios[d]
        gw_id = f"gw:{names[g]}"
        if dl.join:
            kind = "join_accept"
        else:
            kind = "downlink" if dl.data else "ack"
        st = plan.status.get(j) if plan is not None else None
        if st == "uplink_lost":
            continue  # pas d'uplink au LNS : pas de descente
        if st == "lost_mesh":
            t0 = plan.t_border[j]
            hop = HopEvent("ns", gw_id, t0, radio.rx1_hz, None, None, "lost_mesh")
            add(t0, kind, d, g, [hop], "lost_mesh")
            continue
        # Arrivée après la fin de RX2 (RX1 et RX2 de 1 s chacune, à partir de t_open) : « tardive ».
        late = (st == "mesh" and dl.outcome == 2
                and plan.arrival[j] > dl.t_open_ns + 2 * RECEIVE_DELAY1_NS)
        if dl.outcome in (2, 3):
            hop = HopEvent(gw_id, _dev(d), dl.t_open_ns, radio.rx1_hz, None, None, "not_listened")
            outcome = "mesh_late" if late else _MULTI_DOWNLINK_OUTCOME[dl.outcome]
            add(dl.t_open_ns, "rx_window_missed", d, g, [hop], outcome)
            continue
        start = dl.start_ns
        ok = dl.outcome == 0
        hop = HopEvent(gw_id, _dev(d), start, radio.rx1_hz, None, None,
                       "delivered" if ok else "lost_sensitivity")
        if ok:
            if dl.join:
                outcome = "delivered"
            elif dl.data:
                # Même libellé que le mono : une charge sur uplink confirmé porte aussi l'ACK.
                outcome = "data_ack" if options.confirmed_uplinks else "data"
            else:
                outcome = "ack_only"
        else:
            outcome = "lost_sensitivity"
        if dl.join:
            # Même forme que le mono : le join-accept passe d'abord par le serveur (sans perte).
            hops = [HopEvent("ns", gw_id, start, radio.rx1_hz, None, None, "delivered"), hop]
        else:
            hops = [hop]
        add(start, kind, d, g, hops, outcome)

    if len(pending) > MAX_EVENTS:
        raise ValueError(f"trop d'événements ({len(pending)} ; limite {MAX_EVENTS})")
    pending.sort(key=lambda e: (e[0], e[1]))
    events = tuple(
        ProtocolEvent(seq=k, t_ns=t, kind=kind, device_index=d, gateway_index=g,
                      hops=hops, outcome=outcome)
        for k, (t, _order, kind, d, g, hops, outcome) in enumerate(pending)
    )
    net = result.network
    if mesh is None:
        totals = Counters(net.sent, net.received, net.lost_sensitivity, net.lost_collision,
                          net.airtime_ns, net.lost_gateway_busy)
        return MultiTraceRun(per_device=result.per_device, totals=totals,
                             per_gateway=result.per_gateway, gateway_names=names, events=events)
    # Mesh : remises au LNS par dispositif ; le reste des trames décodées est « lost_mesh ».
    per_device, lost_by_device = [], []
    for d, c in enumerate(result.per_device):
        got = mesh.delivered_by_device[d]
        if got > c.received:
            raise RuntimeError("mesh : plus de trames remises que de trames décodées")
        lost_by_device.append(c.received - got)
        per_device.append(Counters(c.sent, got, c.lost_sensitivity, c.lost_collision,
                                   c.airtime_ns, c.lost_gateway_busy))
    received = len(delivered)
    totals = Counters(net.sent, received, net.lost_sensitivity, net.lost_collision,
                      net.airtime_ns, net.lost_gateway_busy)
    return MultiTraceRun(per_device=tuple(per_device), totals=totals,
                         per_gateway=result.per_gateway, gateway_names=names, events=events,
                         lost_mesh=net.received - received,
                         lost_mesh_by_device=tuple(lost_by_device),
                         mesh_loads=_mesh_loads(models, mesh))


# Descentes reçues par le dispositif (ce qui consomme sa réception).
_DELIVERED_DOWNLINK_OUTCOMES = frozenset({"delivered", "data", "data_ack", "ack_only"})


def downlink_airtime_by_device(scenario: Scenario, events: Sequence[ProtocolEvent],
                               options: ProtocolOptions = ProtocolOptions()) -> tuple[int, ...]:
    """Airtime total (ns) des descendantes effectivement reçues, par dispositif.

    Dérivé des événements de la trace (même convention de longueur que les jobs de downlink) :
    join-accept, données (en-tête + `downlink_payload_bytes`), ACK seul. Les descendantes perdues
    (`lost_sensitivity`) et les fenêtres manquées ne consomment pas de réception.
    """
    radios = device_radios(scenario)
    total = [0] * len(radios)
    for ev in events:
        if ev.outcome not in _DELIVERED_DOWNLINK_OUTCOMES or ev.kind not in (
                "join_accept", "downlink", "ack"):
            continue
        if ev.kind == "join_accept":
            nbytes = JOIN_ACCEPT_BYTES
        elif ev.kind == "ack":
            nbytes = ACK_FRAME_BYTES
        else:
            nbytes = DATA_FRAME_OVERHEAD_BYTES + options.downlink_payload_bytes
        total[ev.device_index] += _downlink_airtime_ns(radios[ev.device_index], nbytes)
    return tuple(total)
