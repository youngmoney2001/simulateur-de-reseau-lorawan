"""Backhaul mesh par relais : liens, routes, airtime, demi-duplex, collisions."""

import pytest

from lsim.gateway_profiles import can_relay, get_profile
from lsim.lora import RadioConfig
from lsim.lora import time_on_air_ns as native_time_on_air_ns
from lsim.mesh import (
    MAX_HOPS,
    MeshFrame,
    MeshNode,
    MeshRadio,
    build_mesh,
    forward_frames,
    sx1280_sensitivity_dbm,
    time_on_air_ns,
)
from lsim.radio import LogDistanceModel

# Exposant 4 : un lien de 800 m passe, un lien de 1600 m non (sensibilité -130 dBm).
STEEP = LogDistanceModel(frequency_hz=2.4e9, exponent=4.0)
RADIO = MeshRadio(spreading_factor=12, bandwidth_khz=203, payload_bytes=32)


def test_sensitivity_table_spot_checks():
    assert sx1280_sensitivity_dbm(12, 203) == -130
    assert sx1280_sensitivity_dbm(7, 1625) == -106
    assert sx1280_sensitivity_dbm(5, 812) == -105
    with pytest.raises(ValueError):
        sx1280_sensitivity_dbm(12, 125)
    with pytest.raises(ValueError):
        sx1280_sensitivity_dbm(4, 812)


@pytest.mark.parametrize("sf", [7, 9, 10, 11, 12])
@pytest.mark.parametrize("payload", [0, 10, 32, 51])
def test_airtime_matches_native_at_125_khz(sf, payload):
    mine = time_on_air_ns(sf, 125_000, payload, 1)
    native = native_time_on_air_ns(RadioConfig(
        spreading_factor=sf, bandwidth_hz=125_000, coding_rate=1,
        low_data_rate_optimize=(sf >= 11)), payload)
    assert mine == native


def _line(n: int, spacing_m: float) -> list[MeshNode]:
    return [MeshNode(f"g{i}", i * spacing_m, 0.0) for i in range(n)]


def test_route_follows_chain_to_border():
    nodes = _line(4, 800.0)
    graph = build_mesh(nodes, border_id="g0", radio=RADIO, path_loss=STEEP)
    assert graph.route("g0") == ()
    assert graph.route("g1") == ("g0",)
    assert graph.route("g3") == ("g2", "g1", "g0")


def test_hop_limit_is_eight():
    nodes = _line(MAX_HOPS + 2, 800.0)  # g9 est à 9 sauts
    graph = build_mesh(nodes, border_id=nodes[0].gateway_id, radio=RADIO, path_loss=STEEP)
    assert graph.route(f"g{MAX_HOPS}") is not None
    assert len(graph.route(f"g{MAX_HOPS}")) == MAX_HOPS
    assert graph.route(f"g{MAX_HOPS + 1}") is None


def test_no_route_when_out_of_range():
    nodes = [MeshNode("border", 0.0, 0.0), MeshNode("far", 5000.0, 0.0)]
    graph = build_mesh(nodes, border_id="border", radio=RADIO, path_loss=STEEP)
    assert graph.route("far") is None
    result = forward_frames([MeshFrame(1, "far", 0)], graph, RADIO)
    assert result.deliveries[0].loss == "no_route"


def test_border_and_relays_need_mesh_radio():
    nodes = [MeshNode("border", 0.0, 0.0), MeshNode("relay", 800.0, 0.0, mesh_capable=False)]
    graph = build_mesh(nodes, border_id="border", radio=RADIO, path_loss=STEEP)
    assert graph.route("relay") is None
    with pytest.raises(ValueError):
        build_mesh([MeshNode("b", 0, 0, mesh_capable=False)], border_id="b", radio=RADIO)


def test_frame_over_three_hops_latency_is_three_airtimes():
    graph = build_mesh(_line(4, 800.0), border_id="g0", radio=RADIO, path_loss=STEEP)
    result = forward_frames([MeshFrame(7, "g3", 1_000)], graph, RADIO)
    d = result.deliveries[0]
    assert d.delivered and d.hops == 3
    assert d.latency_ns == 3 * RADIO.airtime_ns


def test_border_receives_directly_with_zero_latency():
    graph = build_mesh(_line(2, 800.0), border_id="g0", radio=RADIO, path_loss=STEEP)
    d = forward_frames([MeshFrame(1, "g0", 0)], graph, RADIO).deliveries[0]
    assert d.delivered and d.hops == 0 and d.latency_ns == 0


def test_half_duplex_relay_loses_frame_received_while_transmitting():
    # g0 frontière, g1 relais au milieu. Trame 1 arrive à g1 depuis g2 pendant
    # qu'il relaie la trame 2 (reçue directement) : g1 ne reçoit pas la trame 1.
    nodes = [MeshNode("g0", 0.0, 0.0), MeshNode("g1", 800.0, 0.0), MeshNode("g2", 1600.0, 0.0)]
    graph = build_mesh(nodes, border_id="g0", radio=RADIO, path_loss=STEEP)
    air = RADIO.airtime_ns
    frames = [
        MeshFrame(1, "g2", 0),          # g2 -> g1 : [0, air]
        MeshFrame(2, "g1", air // 2),   # g1 -> g0 : [air/2, 3air/2]
    ]
    result = forward_frames(frames, graph, RADIO)
    by_id = {d.frame_id: d for d in result.deliveries}
    assert by_id[1].loss == "half_duplex"
    assert by_id[2].delivered


def test_equal_power_collision_loses_both_frames():
    # g1 et g3 sont à égale distance de g2 (relais) ; leurs trames arrivent en même temps.
    nodes = [MeshNode("g0", 0.0, 0.0), MeshNode("g2", 800.0, 0.0),
             MeshNode("g1", 1600.0, 0.0), MeshNode("g3", 800.0, 800.0)]
    graph = build_mesh(nodes, border_id="g0", radio=RADIO, path_loss=STEEP)
    frames = [MeshFrame(1, "g1", 0), MeshFrame(2, "g3", 0)]
    result = forward_frames(frames, graph, RADIO)
    assert result.count("collision") == 2
    assert result.delivered == 0


def test_capture_keeps_the_stronger_frame():
    # g3 est à 400 m de g2, g1 à 800 m : écart 12 dB > 6 dB, g3 survit.
    nodes = [MeshNode("g0", 0.0, 0.0), MeshNode("g2", 800.0, 0.0),
             MeshNode("g1", 1600.0, 0.0), MeshNode("g3", 800.0, 400.0)]
    graph = build_mesh(nodes, border_id="g0", radio=RADIO, path_loss=STEEP)
    frames = [MeshFrame(1, "g1", 0), MeshFrame(2, "g3", 0)]
    by_id = {d.frame_id: d for d in forward_frames(frames, graph, RADIO).deliveries}
    assert by_id[2].delivered
    assert by_id[1].loss == "collision"


def test_mesh_profile_is_documented_relay():
    p = get_profile("rak5148")
    assert can_relay(p)
    assert p.rx_sensitivity_min_dbm == -132.0
    assert get_profile("rak7249").mesh_bands == ()
