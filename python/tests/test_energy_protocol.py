"""Énergie avec protocole : l'airtime des descendantes reçues vient de la trace (`lsim.trace_events`)."""

import pytest

from lsim.energy_report import device_energies, device_energies_protocol
from lsim.scenario import Scenario, ScenarioModel
from lsim.trace_events import ProtocolOptions, build_trace, downlink_airtime_by_device

BASE = {
    "schema_version": 1, "name": "energie", "seed": 5,
    "gateway": {"x_m": 0, "y_m": 0, "antenna_gain_dbi": 2.15},
    "propagation": {"frequency_hz": 868100000, "exponent": 2.7},
    "groups": [{
        "name": "c", "count": 40, "placement": {"type": "disk", "radius_m": 2000},
        "spreading_factor": 9, "payload_bytes": 20, "tx_power_dbm": 14,
        "period_s": 900, "messages": 3, "start_spread_s": 900,
    }],
}


def _scenario():
    return Scenario(ScenarioModel.model_validate(BASE))


def test_without_downlink_the_protocol_energy_equals_the_energy_model():
    sc = _scenario()
    devices, _, _ = sc.deploy()
    zero = [0] * len(devices)
    sent = [1] * len(devices)
    got = device_energies_protocol(devices, zero, sent, "rak4631")
    ref = device_energies(devices, "rak4631")
    assert len(got) == len(ref)
    for g, r in zip(got, ref):
        assert g.energy_per_message_j == pytest.approx(r.energy_per_message_j, rel=1e-12)
        assert g.average_current_ua == pytest.approx(r.average_current_ua, rel=1e-12)


def test_received_downlink_airtime_raises_the_energy_per_message():
    sc = _scenario()
    devices, _, _ = sc.deploy()
    n = len(devices)
    sent = [3] * n
    base = device_energies_protocol(devices, [0] * n, sent, "rak4631")
    dl = [10_000_000_000] * n  # 10 s de réception au total, soit 3,3 s par message
    more = device_energies_protocol(devices, dl, sent, "rak4631")
    for a, b in zip(base, more):
        if a.energy_per_message_j is not None:
            assert b.energy_per_message_j > a.energy_per_message_j
            assert b.average_current_ua > a.average_current_ua


def test_length_mismatch_is_refused():
    devices, _, _ = _scenario().deploy()
    with pytest.raises(ValueError):
        device_energies_protocol(devices, [0], [1], "rak4631")


def test_trace_downlink_airtime_is_zero_without_protocol_and_positive_with_downlinks():
    sc = _scenario()
    tr = build_trace(sc, ProtocolOptions())
    assert set(downlink_airtime_by_device(sc, tr.events, ProtocolOptions())) == {0}
    opts = ProtocolOptions(downlink_every=1)
    tr = build_trace(sc, opts)
    air = downlink_airtime_by_device(sc, tr.events, opts)
    received = [sum(1 for e in tr.events if e.kind == "downlink" and e.device_index == d
                    and e.outcome != "lost_sensitivity") for d in range(len(air))]
    assert any(received)
    for d, count in enumerate(received):
        assert (air[d] > 0) == (count > 0)
