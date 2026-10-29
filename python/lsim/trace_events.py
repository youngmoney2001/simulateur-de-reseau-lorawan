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

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional, Sequence

from lsim.gwmp_server import JOIN_ACCEPT_DELAY1_US
from lsim.lora import RadioConfig, time_on_air_ns
from lsim.plan import RECEIVE_DELAY1_US, Plan, get_plan
from lsim.radio import receiver_sensitivity_dbm
from lsim.scenario import Scenario
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


def _downlink_jobs(records: Sequence[TxRecord], radios: Sequence[DeviceRadio],
                   options: ProtocolOptions) -> list[_Job]:
    """Une réponse attendue par uplink reçu, dans l'ordre de la trace (un seul downlink par uplink)."""
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

    jobs: list[_Job] = []
    joined: set[int] = set()
    accepted: dict[int, int] = defaultdict(int)
    for i, r in enumerate(records):
        d = r.device_index
        radio = radios[d]
        is_join = options.join and d not in joined
        joined.add(d)
        if r.outcome != TxRecord.OUTCOME_RECEIVED:
            continue

        if is_join:
            t_open = r.end_ns + JOIN_ACCEPT_DELAY1_NS
            kind, content = "join_accept", "delivered"
            airtime = _downlink_airtime_ns(radio, JOIN_ACCEPT_BYTES)
        else:
            accepted[d] += 1
            queued = options.downlink_every > 0 and accepted[d] % options.downlink_every == 0
            if queued:
                kind = "downlink"
                content = "data_ack" if options.confirmed_uplinks else "data"
                airtime = _downlink_airtime_ns(
                    radio, DATA_FRAME_OVERHEAD_BYTES + options.downlink_payload_bytes)
            elif options.confirmed_uplinks:
                kind, content = "ack", "ack_only"
                airtime = _downlink_airtime_ns(radio, ACK_FRAME_BYTES)
            else:
                continue
            t_open = r.end_ns + RECEIVE_DELAY1_NS

        nxt = next_start.get(i)
        jobs.append(_Job(
            record=i, device=d, kind=kind, content=content, t_open=t_open, airtime_ns=airtime,
            rx1_hz=radio.rx1_hz,
            received=_received_by_device(r, radio, options),
            device_missed=nxt is not None and nxt < t_open + RX1_WINDOW_NS,
        ))
    return jobs


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
            starts: Sequence[Optional[int]], options: ProtocolOptions) -> tuple[ProtocolEvent, ...]:
    """Événements dans l'ordre temporel, à partir de la trace et de la planification."""
    pending: list[tuple[int, int, str, int, tuple[HopEvent, ...], str]] = []

    def add(t: int, kind: str, device: int, hops: list[HopEvent], outcome: str) -> None:
        pending.append((t, len(pending), kind, device, tuple(hops), outcome))

    job_of = {job.record: k for k, job in enumerate(jobs)}
    joined: set[int] = set()
    for i, r in enumerate(records):
        d = r.device_index
        radio = radios[d]
        is_join = options.join and d not in joined
        joined.add(d)
        hops = [HopEvent(_dev(d), "gw:0", r.start_ns, radio.freq_hz, radio.dr, r.rssi_dbm,
                         _HOP_OUTCOME[r.outcome])]
        if r.outcome == TxRecord.OUTCOME_RECEIVED:
            hops.append(HopEvent("gw:0", "ns", r.end_ns, radio.freq_hz, radio.dr, None,
                                 "delivered"))
        add(r.start_ns, "join_request" if is_join else "uplink", d, hops,
            _UPLINK_OUTCOME[r.outcome])

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

    if len(pending) > MAX_EVENTS:
        raise ValueError(f"trop d'événements ({len(pending)} ; limite {MAX_EVENTS})")
    pending.sort(key=lambda e: (e[0], e[1]))
    return tuple(
        ProtocolEvent(seq=k, t_ns=t, kind=kind, device_index=d, gateway_index=0,
                      hops=hops, outcome=outcome)
        for k, (t, _order, kind, d, hops, outcome) in enumerate(pending)
    )


def build_protocol_events(records: Sequence[TxRecord], radios: Sequence[DeviceRadio],
                          options: ProtocolOptions) -> tuple[ProtocolEvent, ...]:
    """Événements dérivés d'une trace déjà produite (sans nouvelle itération du moteur).

    Les émissions passerelle sont celles des downlinks planifiés à partir de cette trace. Pour
    une trace cohérente avec ces émissions, utiliser `build_trace`.
    """
    jobs = _downlink_jobs(records, radios, options)
    starts, _intervals = _schedule_gateway(jobs)
    return _events(records, radios, jobs, starts, options)


def build_trace(scenario: Scenario, options: ProtocolOptions = ProtocolOptions()) -> TraceRun:
    """Déploie le scénario et calcule la trace cohérente avec les émissions de la passerelle.

    Point fixe : les trames montantes dépendent des émissions passerelle, qui dépendent des
    uplinks reçus. L'itération s'arrête quand les émissions utilisées par le moteur sont celles
    que produit la trace obtenue. Pas de convergence en `MAX_ITERATIONS` : erreur explicite.
    """
    devices, _group_of, _indices = scenario.deploy()
    if sum(d.messages for d in devices) > MAX_TRACE_RECORDS:
        raise ValueError(f"trace limitée à {MAX_TRACE_RECORDS} émissions par simulation")
    radios = device_radios(scenario)
    gateway, propagation, environment = scenario.gateway(), scenario.propagation(), scenario.environment

    busy: list[tuple[int, int]] = []
    for _ in range(MAX_ITERATIONS):
        result = simulate_uplinks_trace(devices, gateway, propagation, environment,
                                        gateway_busy=busy)
        jobs = _downlink_jobs(result.records, radios, options)
        starts, new_busy = _schedule_gateway(jobs)
        if new_busy == busy:
            events = _events(result.records, radios, jobs, starts, options)
            return TraceRun(
                per_device=result.per_device,
                totals=result.totals,
                gateway=result.gateway,
                records=result.records,
                events=events,
                gateway_tx=tuple(busy),
            )
        busy = new_busy
    raise RuntimeError(
        f"pas de point fixe entre trames montantes et émissions passerelle "
        f"après {MAX_ITERATIONS} itérations")


# --- Passerelles multiples -------------------------------------------------------------------

_MULTI_UPLINK_OUTCOME = {0: "lost_sensitivity", 1: "lost_collision", 2: "received",
                         3: "lost_gateway_busy"}
_MULTI_HOP_OUTCOME = {0: "lost_sensitivity", 1: "lost_collision", 2: "delivered", 3: "not_listened"}
_MULTI_DOWNLINK_OUTCOME = {0: "delivered", 1: "lost_sensitivity", 2: "gateway_busy",
                           3: "device_transmitting"}


@dataclass(frozen=True)
class MultiTraceRun:
    """Trace multi-passerelles : totaux et charges issus du même calcul natif que les événements."""

    per_device: tuple[Counters, ...]
    totals: Counters
    per_gateway: tuple  # GatewayRxCounters, dans l'ordre de `gateway_names`
    gateway_names: tuple[str, ...]
    events: tuple[ProtocolEvent, ...]


def _finite_or_none(x: float) -> Optional[float]:
    return float(x) if x == x and abs(x) != float("inf") else None


def build_multi_trace(scenario: Scenario, options: ProtocolOptions = ProtocolOptions()) -> MultiTraceRun:
    """Trace des passerelles multiples (déduplication serveur, downlinks par la meilleure passerelle).

    Limites : le join n'est pas modélisé (refusé ici) ; le mesh n'est pas couvert (refusé en amont).
    Les totaux, les compteurs par dispositif et la charge par passerelle viennent du même appel
    natif (`simulate_multi_downlinks`) que les événements : ils concordent par construction.
    """
    if options.join:
        raise ValueError("join : non modélisé en multi-passerelles")
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
                        device_rx_offset_db=options.device_rx_offset_db)
    result = simulate_multi_downlinks(devices, gateways, scenario.propagation(), rule,
                                      scenario.environment)
    pending: list[tuple[int, int, str, int, int, tuple[HopEvent, ...], str]] = []

    def add(t: int, kind: str, device: int, gw: int, hops: list[HopEvent], outcome: str) -> None:
        pending.append((t, len(pending), kind, device, gw, tuple(hops), outcome))

    for r in result.trace:
        d = r.device_index
        radio = radios[d]
        best = r.best_gateway
        to_id = f"gw:{names[best]}" if best >= 0 else "gw:none"
        hops = [HopEvent(_dev(d), to_id, r.start_ns, radio.freq_hz, radio.dr,
                         _finite_or_none(r.best_rssi_dbm), _MULTI_HOP_OUTCOME[r.outcome])]
        if r.outcome == 2 and best >= 0:
            hops.append(HopEvent(to_id, "ns", r.end_ns, radio.freq_hz, radio.dr, None, "delivered"))
        add(r.start_ns, "uplink", d, max(best, 0), hops, _MULTI_UPLINK_OUTCOME[r.outcome])

    for dl in result.downlinks:
        d, g = dl.device_index, dl.gateway_index
        radio = radios[d]
        gw_id = f"gw:{names[g]}"
        kind = "downlink" if dl.data else "ack"
        if dl.outcome in (2, 3):
            hop = HopEvent(gw_id, _dev(d), dl.t_open_ns, radio.rx1_hz, None, None, "not_listened")
            add(dl.t_open_ns, "rx_window_missed", d, g, [hop], _MULTI_DOWNLINK_OUTCOME[dl.outcome])
            continue
        start = dl.start_ns
        ok = dl.outcome == 0
        hop = HopEvent(gw_id, _dev(d), start, radio.rx1_hz, None, None,
                       "delivered" if ok else "lost_sensitivity")
        if ok:
            outcome = "data" if dl.data else "ack_only"
        else:
            outcome = "lost_sensitivity"
        add(start, kind, d, g, [hop], outcome)

    if len(pending) > MAX_EVENTS:
        raise ValueError(f"trop d'événements ({len(pending)} ; limite {MAX_EVENTS})")
    pending.sort(key=lambda e: (e[0], e[1]))
    events = tuple(
        ProtocolEvent(seq=k, t_ns=t, kind=kind, device_index=d, gateway_index=g,
                      hops=hops, outcome=outcome)
        for k, (t, _order, kind, d, g, hops, outcome) in enumerate(pending)
    )
    net = result.network
    totals = Counters(net.sent, net.received, net.lost_sensitivity, net.lost_collision,
                      net.airtime_ns, net.lost_gateway_busy)
    return MultiTraceRun(per_device=result.per_device, totals=totals,
                         per_gateway=result.per_gateway, gateway_names=names, events=events)


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
        if ev.outcome == "lost_sensitivity" or ev.kind not in ("join_accept", "downlink", "ack"):
            continue
        if ev.kind == "join_accept":
            nbytes = JOIN_ACCEPT_BYTES
        elif ev.kind == "ack":
            nbytes = ACK_FRAME_BYTES
        else:
            nbytes = DATA_FRAME_OVERHEAD_BYTES + options.downlink_payload_bytes
        total[ev.device_index] += _downlink_airtime_ns(radios[ev.device_index], nbytes)
    return tuple(total)
