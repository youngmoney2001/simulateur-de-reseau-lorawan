"""Trace par transmission et événements du protocole, sur la même horloge que le moteur.

Le cœur natif produit une entrée par émission (début, fin, issue à la passerelle). Ce module
en dérive les événements de la couche protocole, avec les temporisations de la spécification :

- join-request : même issue que l'émission ; join-accept à fin + JOIN_ACCEPT_DELAY1 (5 s) ;
- uplink de données : issue de l'émission ; un uplink accepté par la passerelle ouvre une
  fenêtre RX1 à fin + RECEIVE_DELAY1 (1 s) ;
- downlink (un seul par uplink accepté, comme `lsim.uplink`) : si une charge est en file
  (`downlink_every`), sinon ACK seul si l'uplink est confirmé.

Règles de modélisation (volontairement explicites) :
- la passerelle est supposée émettre à chaque fenêtre ; son propre duplex n'est pas modélisé ;
- le dispositif est en demi-duplex : s'il émet à nouveau pendant sa fenêtre RX1, la fenêtre est
  manquée (événement `rx_window_missed`, pas de retransmission) ;
- la réception des downlinks par le dispositif n'est pas simulée : ces sauts ont l'issue
  `sent` ; le backhaul passerelle -> serveur est sans perte (issue `delivered`).

Les dates sont en nanosecondes entières, issues du moteur, sans recalcul flottant.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Optional, Sequence

from lsim.gwmp_server import JOIN_ACCEPT_DELAY1_US
from lsim.plan import RECEIVE_DELAY1_US, Plan, get_plan
from lsim.scenario import Scenario
from lsim.simulator import (
    MAX_TRACE_RECORDS,
    Counters,
    GatewayLoad,
    TxRecord,
    simulate_uplinks_trace,
)

NS_PER_US = 1_000
RECEIVE_DELAY1_NS = RECEIVE_DELAY1_US * NS_PER_US
JOIN_ACCEPT_DELAY1_NS = JOIN_ACCEPT_DELAY1_US * NS_PER_US
# Durée supposée de la fenêtre RX1 (hypothèse, identique au moteur de downlink : 1 s).
RX1_WINDOW_NS = 1_000_000_000
# Borne des événements par run (contrat d'API : 200 000).
MAX_EVENTS = 200_000

_UPLINK_OUTCOME = {
    TxRecord.OUTCOME_LOST_SENSITIVITY: "lost_sensitivity",
    TxRecord.OUTCOME_LOST_COLLISION: "lost_collision",
    TxRecord.OUTCOME_RECEIVED: "received",
}
_HOP_OUTCOME = {
    TxRecord.OUTCOME_LOST_SENSITIVITY: "lost_sensitivity",
    TxRecord.OUTCOME_LOST_COLLISION: "lost_collision",
    TxRecord.OUTCOME_RECEIVED: "delivered",
}


@dataclass(frozen=True)
class ProtocolOptions:
    """Comportement applicatif du scénario, hors moteur radio."""

    join: bool = False              # première émission de chaque dispositif = join-request
    confirmed_uplinks: bool = False  # uplinks de données confirmés (ACK attendu)
    downlink_every: int = 0         # 0 : aucune charge en file ; N : une charge par N uplinks acceptés


@dataclass(frozen=True)
class DeviceRadio:
    """Paramètres radio d'un dispositif pour les sauts : fréquence, DR montant, RX1."""

    freq_hz: int
    dr: Optional[int]        # None si aucun plan régional
    rx1_hz: int              # fréquence de la fenêtre RX1 (égale à freq_hz sans plan)


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


def _dev(i: int) -> str:
    return f"dev:{i}"


def _radio(plan: Optional[Plan], freq_hz: int, sf: int) -> DeviceRadio:
    if plan is None:
        return DeviceRadio(freq_hz=freq_hz, dr=None, rx1_hz=freq_hz)
    dr = next((i for i, (s, bw, _) in enumerate(plan.dr_table()) if s == sf and bw == 125), None)
    rx1_hz = freq_hz
    if dr is not None:
        try:
            ch = plan.channel_index(freq_hz / 1_000_000)
            rx1_mhz, _ = plan.rx1(dr, ch)
            rx1_hz = round(rx1_mhz * 1_000_000)
        except ValueError:
            rx1_hz = freq_hz
    return DeviceRadio(freq_hz=freq_hz, dr=dr, rx1_hz=rx1_hz)


def device_radios(scenario: Scenario) -> tuple[DeviceRadio, ...]:
    """Paramètres radio de chaque dispositif, dans l'ordre de `Scenario.deploy`."""
    devices, group_of, _ = scenario.deploy()
    by_name = {g.name: g for g in scenario.model.groups}
    radios = []
    for _dev_spec, name in zip(devices, group_of):
        g = by_name[name]
        plan: Optional[Plan] = None
        if g.region is not None:
            try:
                plan = get_plan(g.region)
            except ValueError:
                plan = None
        radios.append(_radio(plan, g.channel_freq_hz, g.spreading_factor))
    return tuple(radios)


def build_protocol_events(records: Sequence[TxRecord], radios: Sequence[DeviceRadio],
                          options: ProtocolOptions) -> tuple[ProtocolEvent, ...]:
    """Dérive les événements du protocole de la trace (ordre temporel, `seq` séquentiel)."""
    if options.downlink_every < 0:
        raise ValueError("downlink_every doit être positif ou nul")

    # Prochaine émission du même dispositif : détection du demi-duplex sur la fenêtre RX1.
    by_device: dict[int, list[int]] = defaultdict(list)
    for i, r in enumerate(records):
        by_device[r.device_index].append(i)
    next_start: dict[int, int] = {}
    for idxs in by_device.values():
        for a, b in zip(idxs, idxs[1:]):
            next_start[a] = records[b].start_ns

    # (t, ordre de création, événement sans seq)
    pending: list[tuple[int, int, str, int, tuple[HopEvent, ...], str]] = []

    def add(t: int, kind: str, device: int, hops: list[HopEvent], outcome: str) -> None:
        pending.append((t, len(pending), kind, device, tuple(hops), outcome))

    joined: set[int] = set()
    accepted: dict[int, int] = defaultdict(int)
    for i, r in enumerate(records):
        d = r.device_index
        radio = radios[d]
        is_join = options.join and d not in joined
        joined.add(d)
        received = r.outcome == TxRecord.OUTCOME_RECEIVED

        hops = [HopEvent(_dev(d), "gw:0", r.start_ns, radio.freq_hz, radio.dr, r.rssi_dbm,
                         _HOP_OUTCOME[r.outcome])]
        if received:
            hops.append(HopEvent("gw:0", "ns", r.end_ns, radio.freq_hz, radio.dr, None,
                                 "delivered"))
        kind_up = "join_request" if is_join else "uplink"
        add(r.start_ns, kind_up, d, hops, _UPLINK_OUTCOME[r.outcome])

        if not received:
            continue

        # Fenêtre de réception du downlink : RX1 après l'uplink (1 s) ou après le join (5 s).
        if is_join:
            t_open = r.end_ns + JOIN_ACCEPT_DELAY1_NS
            kind, outcome = "join_accept", "sent"
        else:
            accepted[d] += 1
            queued = options.downlink_every > 0 and accepted[d] % options.downlink_every == 0
            if queued:
                kind = "downlink"
                outcome = "data_ack" if options.confirmed_uplinks else "data"
            elif options.confirmed_uplinks:
                kind, outcome = "ack", "ack_only"
            else:
                continue
            t_open = r.end_ns + RECEIVE_DELAY1_NS

        nxt = next_start.get(i)
        if nxt is not None and nxt < t_open + RX1_WINDOW_NS:
            # Le dispositif émet encore : sa fenêtre RX1 est manquée.
            missed = HopEvent("gw:0", _dev(d), t_open, radio.rx1_hz, None, None, "not_listened")
            add(t_open, "rx_window_missed", d, [missed], "device_transmitting")
            continue

        if is_join:
            down = [HopEvent("ns", "gw:0", t_open, radio.rx1_hz, None, None, "sent"),
                    HopEvent("gw:0", _dev(d), t_open, radio.rx1_hz, None, None, "sent")]
        else:
            down = [HopEvent("gw:0", _dev(d), t_open, radio.rx1_hz, None, None, "sent")]
        add(t_open, kind, d, down, outcome)

    if len(pending) > MAX_EVENTS:
        raise ValueError(f"trop d'événements ({len(pending)} ; limite {MAX_EVENTS})")
    pending.sort(key=lambda e: (e[0], e[1]))
    return tuple(
        ProtocolEvent(seq=k, t_ns=t, kind=kind, device_index=d, gateway_index=0,
                      hops=hops, outcome=outcome)
        for k, (t, _order, kind, d, hops, outcome) in enumerate(pending)
    )


def build_trace(scenario: Scenario, options: ProtocolOptions = ProtocolOptions()) -> TraceRun:
    """Déploie le scénario, lance le cœur (compteurs + trace) et dérive les événements."""
    devices, _group_of, _indices = scenario.deploy()
    if sum(d.messages for d in devices) > MAX_TRACE_RECORDS:
        raise ValueError(f"trace limitée à {MAX_TRACE_RECORDS} émissions par simulation")
    result = simulate_uplinks_trace(devices, scenario.gateway(), scenario.propagation(),
                                    scenario.environment)
    events = build_protocol_events(result.records, device_radios(scenario), options)
    return TraceRun(
        per_device=result.per_device,
        totals=result.totals,
        gateway=result.gateway,
        records=result.records,
        events=events,
    )
