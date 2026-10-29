"""Trace par transmission (cœur natif) et événements du protocole, même horloge."""

import ctypes
from collections import Counter
from pathlib import Path

import pytest

from lsim import _native
from lsim.scenario import load_scenario
from lsim.simulator import (
    EndDevice,
    Gateway,
    Propagation,
    TxRecord,
    simulate_uplinks,
    simulate_uplinks_trace,
)
from lsim.radio import receiver_sensitivity_dbm
from lsim.trace_events import (
    JOIN_ACCEPT_DELAY1_NS,
    RECEIVE_DELAY1_NS,
    ProtocolOptions,
    build_protocol_events,
    DeviceRadio,
    build_trace,
)

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "quartier_sf9.yaml"
RADIO = DeviceRadio(freq_hz=868_100_000, dr=None, rx1_hz=868_100_000)


def _rec(device: int, start: int, end: int, outcome: int) -> TxRecord:
    return TxRecord(device, start, end, 7, -90.0, outcome)


@pytest.fixture(scope="module")
def quartier():
    return load_scenario(EXAMPLE)


def test_trace_matches_native_counters():
    devices = [EndDevice(x_m=100.0 * i, period_ns=1_000_000_000, messages=3) for i in range(4)]
    devices.append(EndDevice(x_m=9e5, messages=2))  # sous la sensibilité
    gw, prop = Gateway(), Propagation()
    traced = simulate_uplinks_trace(devices, gw, prop)
    plain = simulate_uplinks(devices, gw, prop)
    assert traced.totals == plain.totals
    assert traced.per_device == plain.per_device
    assert len(traced.records) == plain.totals.sent
    outcomes = Counter(r.outcome for r in traced.records)
    assert outcomes[TxRecord.OUTCOME_RECEIVED] == plain.totals.received
    assert outcomes[TxRecord.OUTCOME_LOST_COLLISION] == plain.totals.lost_collision
    assert outcomes[TxRecord.OUTCOME_LOST_SENSITIVITY] == plain.totals.lost_sensitivity
    starts = [r.start_ns for r in traced.records]
    assert starts == sorted(starts)
    assert all(r.end_ns > r.start_ns for r in traced.records)


def test_trace_capacity_reports_required_size():
    # Appel direct : tampon trop petit -> statut 308 et taille requise dans record_count.
    devices = [EndDevice(messages=2), EndDevice(messages=1, x_m=50.0)]
    c_devs = (_native._CEndDevice * 2)()
    for i, d in enumerate(devices):
        c_devs[i].spreading_factor = 7
        c_devs[i].payload_bytes = d.payload_bytes
        c_devs[i].tx_power_dbm = 14.0
        c_devs[i].period_ns = d.period_ns
        c_devs[i].messages = d.messages
        c_devs[i].duty_cycle = 1.0
        c_devs[i].x_m = d.x_m
    gw = _native._CGateway(0.0, 0.0, 0.0)
    prop = _native._CPropagation(868.1e6, 1.0, 2.7, 6.0, 0.0, 0)
    stats = (_native._CDeviceStats * 2)()
    tot = _native._CSimStats()
    count = ctypes.c_size_t(0)
    status = _native.LIB.lsim_simulate_uplinks_trace(
        c_devs, 2, ctypes.byref(gw), ctypes.byref(prop), None, stats, ctypes.byref(tot),
        None, 0, ctypes.byref(count), None, 0)
    assert status == 308
    assert count.value == 3


def test_trace_refuses_oversized_run_before_allocation():
    with pytest.raises(ValueError):
        simulate_uplinks_trace([EndDevice(messages=10_000)] * 10_000, Gateway(), Propagation())


def test_join_accept_and_ack_use_engine_times(quartier):
    run = build_trace(quartier, ProtocolOptions(join=True, confirmed_uplinks=True))
    received_ends = {(r.device_index, r.end_ns) for r in run.records
                     if r.outcome == TxRecord.OUTCOME_RECEIVED}
    joins = [e for e in run.events if e.kind == "join_request"]
    assert len(joins) == len(quartier.deploy()[0])
    for e in run.events:
        if e.kind == "join_accept":
            assert (e.device_index, e.t_ns - JOIN_ACCEPT_DELAY1_NS) in received_ends
        elif e.kind in ("ack", "downlink"):
            assert (e.device_index, e.t_ns - RECEIVE_DELAY1_NS) in received_ends
    accepted = sum(1 for e in joins if e.outcome == "received")
    assert sum(1 for e in run.events if e.kind == "join_accept") == accepted


def test_one_downlink_per_accepted_uplink(quartier):
    run = build_trace(quartier, ProtocolOptions(confirmed_uplinks=True, downlink_every=3))
    received = sum(1 for r in run.records if r.outcome == TxRecord.OUTCOME_RECEIVED)
    # Chaque uplink accepté produit une réponse ou une fenêtre manquée, jamais deux.
    down = [e for e in run.events if e.kind in ("ack", "downlink", "rx_window_missed")]
    assert len(down) == received
    # Charge en file : une sur trois des uplinks acceptés de chaque dispositif.
    accepted = Counter(r.device_index for r in run.records
                       if r.outcome == TxRecord.OUTCOME_RECEIVED)
    expected = sum(n // 3 for n in accepted.values())
    assert sum(1 for e in run.events if e.kind == "downlink") == expected


def test_no_protocol_option_no_downlink_events(quartier):
    run = build_trace(quartier, ProtocolOptions())
    assert {e.kind for e in run.events} <= {"uplink", "lost_sensitivity", "lost_collision"}
    assert not any(e.kind.startswith(("join", "ack", "downlink")) for e in run.events)
    assert len(run.events) == len(run.records)


def test_events_are_sequential_and_sorted(quartier):
    run = build_trace(quartier, ProtocolOptions(join=True, confirmed_uplinks=True,
                                                downlink_every=2))
    assert [e.seq for e in run.events] == list(range(len(run.events)))
    times = [e.t_ns for e in run.events]
    assert times == sorted(times)


def test_deterministic(quartier):
    opts = ProtocolOptions(join=True, confirmed_uplinks=True, downlink_every=4)
    assert build_trace(quartier, opts).events == build_trace(quartier, opts).events


def test_device_transmitting_misses_rx1_window():
    # Émission 0 (reçue), puis nouvelle émission à 1,5 s : RX1 (ouvre à 1,04 s) manquée.
    end0 = 41_216_000
    records = [_rec(0, 0, end0, TxRecord.OUTCOME_RECEIVED),
               _rec(0, 1_500_000_000, 1_541_216_000, TxRecord.OUTCOME_RECEIVED)]
    events = build_protocol_events(records, [RADIO], ProtocolOptions(confirmed_uplinks=True))
    kinds = [e.kind for e in events]
    assert kinds.count("rx_window_missed") == 1
    missed = next(e for e in events if e.kind == "rx_window_missed")
    assert missed.t_ns == end0 + RECEIVE_DELAY1_NS
    assert missed.hops[0].outcome == "not_listened"


def test_rx1_delivered_when_device_is_silent():
    end0 = 41_216_000
    records = [_rec(0, 0, end0, TxRecord.OUTCOME_RECEIVED),
               _rec(0, 3_000_000_000, 3_041_216_000, TxRecord.OUTCOME_LOST_COLLISION)]
    events = build_protocol_events(records, [RADIO], ProtocolOptions(confirmed_uplinks=True))
    ack = [e for e in events if e.kind == "ack"]
    assert len(ack) == 1
    assert ack[0].t_ns == end0 + RECEIVE_DELAY1_NS
    assert ack[0].hops[0].to_id == "dev:0"
    assert ack[0].hops[0].outcome == "delivered"  # RSSI descendant au-dessus de la sensibilité


def test_lost_uplink_gets_no_downlink():
    records = [_rec(0, 0, 41_216_000, TxRecord.OUTCOME_LOST_SENSITIVITY)]
    events = build_protocol_events(records, [RADIO], ProtocolOptions(confirmed_uplinks=True,
                                                                     downlink_every=1))
    assert [e.kind for e in events] == ["uplink"]
    assert events[0].outcome == "lost_sensitivity"


def test_negative_downlink_every_rejected():
    with pytest.raises(ValueError):
        build_protocol_events([], [], ProtocolOptions(downlink_every=-1))


def test_protocol_options_bounds_and_unknown_fields():
    from pydantic import ValidationError

    from lsim.api_contract import ProtocolOptionsIn

    assert ProtocolOptionsIn().downlink_every == 0
    with pytest.raises(ValidationError):
        ProtocolOptionsIn(downlink_every=10_001)
    with pytest.raises(ValidationError):
        ProtocolOptionsIn(ack=True)  # champ inconnu refusé


def _ack_event(rssi_up: float, **opts):
    records = [_rec(0, 0, 41_216_000, TxRecord.OUTCOME_RECEIVED)]
    records[0] = TxRecord(0, 0, 41_216_000, 7, rssi_up, TxRecord.OUTCOME_RECEIVED)
    events = build_protocol_events(records, [RADIO],
                                   ProtocolOptions(confirmed_uplinks=True, **opts))
    return next(e for e in events if e.kind in ("ack", "downlink", "join_accept"))


def test_downlink_lost_below_device_sensitivity():
    # Réciprocité : RSSI descendant = RSSI montant - 14 + 14 + 0 = RSSI montant (SF7, 125 kHz).
    sens = receiver_sensitivity_dbm(7, 125_000)
    lost = _ack_event(sens - 1.0)
    assert lost.outcome == "lost_sensitivity"
    assert lost.hops[-1].outcome == "lost_sensitivity"
    ok = _ack_event(sens + 1.0)
    assert ok.outcome == "ack_only"
    assert ok.hops[-1].outcome == "delivered"


def test_gateway_power_changes_downlink_reception():
    sens = receiver_sensitivity_dbm(7, 125_000)
    weak = _ack_event(sens - 3.0)  # 14 dBm : perdu
    assert weak.outcome == "lost_sensitivity"
    strong = _ack_event(sens - 3.0, gateway_tx_power_dbm=20.0)  # +6 dB : reçu
    assert strong.outcome == "ack_only"
    antenna = _ack_event(sens - 3.0, device_antenna_gain_dbi=5.0)  # +5 dBi : reçu
    assert antenna.outcome == "ack_only"
    antenna_lo = _ack_event(sens - 3.0, device_antenna_gain_dbi=-5.0)  # -5 dBi : perdu
    assert antenna_lo.outcome == "lost_sensitivity"


def test_downlink_outcomes_partition_scenario(quartier):
    run = build_trace(quartier, ProtocolOptions(join=True, confirmed_uplinks=True,
                                                downlink_every=5))
    received = sum(1 for r in run.records if r.outcome == TxRecord.OUTCOME_RECEIVED)
    down = [e for e in run.events
            if e.kind in ("ack", "downlink", "join_accept", "rx_window_missed")]
    delivered = [e for e in down if e.hops[-1].outcome == "delivered"]
    lost = [e for e in down if e.hops[-1].outcome == "lost_sensitivity"]
    missed = [e for e in down if e.kind == "rx_window_missed"]
    assert len(delivered) + len(lost) + len(missed) == len(down)
    assert len(down) == received  # une réponse par uplink accepté (join compris)
    assert all(e.outcome == "lost_sensitivity" for e in lost)
    assert all(e.outcome != "lost_sensitivity" for e in delivered)


def test_gateway_serializes_downlinks_and_drops_late_ones():
    from lsim.trace_events import _Job, _schedule_gateway, RX1_WINDOW_NS

    def job(t_open, airtime):
        return _Job(record=0, device=0, kind="ack", content="ack_only", t_open=t_open,
                    airtime_ns=airtime, rx1_hz=868_100_000, received=True, device_missed=False)

    # Deux réponses qui tombent presque ensemble : la seconde attend la fin de la première.
    starts, busy = _schedule_gateway([job(1_000_000_000, 300_000_000),
                                      job(1_050_000_000, 300_000_000)])
    assert starts == [1_000_000_000, 1_300_000_000]
    assert busy == [(1_000_000_000, 1_300_000_000), (1_300_000_000, 1_600_000_000)]

    # Une réponse qui ne peut partir qu'après la fenêtre RX1 du dispositif est perdue.
    starts, busy = _schedule_gateway([job(1_000_000_000, 1_500_000_000),
                                      job(1_100_000_000, 100_000_000)])
    assert starts[0] == 1_000_000_000
    assert starts[1] is None
    assert len(busy) == 1
    assert RX1_WINDOW_NS == 1_000_000_000


def test_uplink_overlapping_gateway_transmission_is_lost():
    busy = [(100_000_000, 200_000_000)]
    devices = [EndDevice(x_m=10.0, messages=1, start_offset_ns=0)]
    traced = simulate_uplinks_trace(devices, Gateway(), Propagation(), gateway_busy=busy)
    assert traced.records[0].outcome == TxRecord.OUTCOME_RECEIVED  # pas de chevauchement
    devices = [EndDevice(x_m=10.0, messages=1, start_offset_ns=150_000_000)]
    traced = simulate_uplinks_trace(devices, Gateway(), Propagation(), gateway_busy=busy)
    assert traced.records[0].outcome == TxRecord.OUTCOME_LOST_GATEWAY_BUSY
    assert traced.totals.lost_gateway_busy == 1
    assert traced.per_device[0].lost_gateway_busy == 1


def test_trace_is_consistent_with_gateway_transmissions(quartier):
    # Invariants du point fixe : la passerelle n'émet jamais deux downlinks à la fois, et aucune
    # trame reçue ne chevauche une de ses émissions.
    run = build_trace(quartier, ProtocolOptions(join=True, confirmed_uplinks=True,
                                                downlink_every=3))
    tx = sorted(run.gateway_tx)
    assert all(a_end <= b_start for (_, a_end), (b_start, _) in zip(tx, tx[1:]))
    for r in run.records:
        overlapping = any(s < r.end_ns and r.start_ns < e for s, e in tx)
        if r.outcome == TxRecord.OUTCOME_RECEIVED:
            assert not overlapping
        if r.outcome == TxRecord.OUTCOME_LOST_GATEWAY_BUSY:
            assert overlapping
    assert run.totals.lost_gateway_busy > 0  # le demi-duplex a un effet mesurable


def test_device_rx_offset_creates_downlink_losses(quartier):
    default = build_trace(quartier, ProtocolOptions(confirmed_uplinks=True))
    assert not any(e.outcome == "lost_sensitivity" for e in default.events)
    harsh = build_trace(quartier, ProtocolOptions(confirmed_uplinks=True,
                                                  device_rx_offset_db=40.0))
    assert any(e.outcome == "lost_sensitivity" for e in harsh.events)


def test_downlink_payload_and_offset_bounds():
    with pytest.raises(ValueError):
        build_protocol_events([], [], ProtocolOptions(downlink_payload_bytes=243))
    from lsim.api_contract import ProtocolOptionsIn
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ProtocolOptionsIn(downlink_payload_bytes=300)
