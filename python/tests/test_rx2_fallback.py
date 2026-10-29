"""Repli RX2 des descentes : une descente qui ne peut partir dans RX1 (passerelle occupée) tente
RX2, ouverte 1 s après RX1 avec le SF `rx2_sf`. Sans repli (rx2_sf = 0), elle est perdue."""

from pathlib import Path

import pytest

import lsim.trace_events as te
from lsim.scenario import load_scenario
from lsim.simulator import (
    EndDevice,
    Gateway,
    DownlinkRule,
    Propagation,
    StatusError,
    simulate_multi_downlinks,
)
from lsim.trace_events import ProtocolOptions, build_multi_trace

S = 1_000_000_000
EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "mesh_relais_quartier.yaml"


def _two_devices_sf12():
    """Deux uplinks SF12 non chevauchants (1,5 s d'écart) reçus par une passerelle."""
    return [
        EndDevice(x_m=50, y_m=0, spreading_factor=12, payload_bytes=10,
                  start_offset_ns=0, period_ns=600 * S, messages=1),
        EndDevice(x_m=50, y_m=0, spreading_factor=12, payload_bytes=10,
                  start_offset_ns=int(1.5 * S), period_ns=600 * S, messages=1),
    ]


def _busy_case(rx2_sf):
    # Le départ au plus tôt de la descente 0 (3,0 s) tombe après la fin de sa RX1 (2,99 s) : elle
    # est servie en RX2 si la passerelle est libre. La descente 0 occupe alors la passerelle et
    # bloque RX1 de la descente 1 (3,49 s) jusqu'à 3,99 s.
    return simulate_multi_downlinks(
        _two_devices_sf12(), [Gateway(0, 0, 0)], Propagation(),
        DownlinkRule(ack_uplinks=True, rx2_sf=rx2_sf), dl_ready_ns=[int(3.0 * S), -1])


def test_rx2_serves_a_downlink_whose_rx1_gateway_is_busy():
    result = _busy_case(rx2_sf=12)
    first = result.downlinks[0]
    assert first.rx_window == 2
    assert first.outcome == 0
    # RX2 : ouverte à t_open + 1 s, fenêtre de 1 s.
    assert S <= first.start_ns - first.t_open_ns < 2 * S
    # La seconde descente reste en RX1 (la passerelle n'est occupée que 0,99 s après 3,0 s).
    second = result.downlinks[1]
    assert second.rx_window == 1 and second.outcome == 0


def test_without_rx2_the_same_downlink_is_lost_as_gateway_busy():
    result = _busy_case(rx2_sf=0)
    first = result.downlinks[0]
    assert first.outcome == 2
    assert first.rx_window == 1
    assert not any(d.rx_window == 2 for d in result.downlinks)


def test_rx2_spreading_factor_is_validated():
    with pytest.raises(StatusError):
        simulate_multi_downlinks(_two_devices_sf12(), [Gateway(0, 0, 0)], Propagation(),
                                 DownlinkRule(ack_uplinks=True, rx2_sf=5))


def test_rx2_spreading_factor_comes_from_the_regional_plan(tmp_path):
    text = EXAMPLE.read_text(encoding="utf-8")
    path = tmp_path / "plan.yaml"
    path.write_text(text, encoding="utf-8")
    scenario = load_scenario(path)
    assert te._rx2_spreading_factor(scenario) == 12  # EU868 : RX2 par défaut en SF12 BW125
    # Le repli est transmis à la trace : la règle de build_multi_trace reprend ce SF.
    captured = []
    real = te.simulate_multi_downlinks

    def spy(*args, **kwargs):
        captured.append(args[3].rx2_sf)
        return real(*args, **kwargs)

    te.simulate_multi_downlinks = spy
    try:
        build_multi_trace(scenario, ProtocolOptions(confirmed_uplinks=True, downlink_every=1))
    finally:
        te.simulate_multi_downlinks = real
    assert captured and set(captured) == {12}
