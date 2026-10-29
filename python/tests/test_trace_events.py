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
        None, 0, ctypes.byref(count))
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
    down = [e for e in run.events if e.kind in ("ack", "downlink")]
    assert len(down) == received  # un downlink par uplink accepté, jamais deux
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
    assert ack[0].hops[0].outcome == "sent"


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
