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
        spreading_factor=sf, bandwidth_hz=125_000, coding_rate=1), payload)
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


def test_overhearing_relay_suppresses_its_duplicate():
    # Frontière en (0,0), relais R1 en (800,0) et R2 en (400,400) : R2 entend R1 vers la
    # frontière, puis reçoit sa propre copie après la fin de l'émission de R1.
    nodes = [MeshNode("border", 0.0, 0.0), MeshNode("r1", 800.0, 0.0),
             MeshNode("r2", 400.0, 400.0)]
    graph = build_mesh(nodes, border_id="border", radio=RADIO, path_loss=STEEP)
    air = RADIO.airtime_ns
    frames = [MeshFrame(7, "r1", 0), MeshFrame(7, "r2", air + air // 2)]
    result = forward_frames(frames, graph, RADIO)
    assert result.transmissions == 1
    assert result.suppressed == 1
    assert result.lost_collision == 0
    assert result.delivered == 1
    states = sorted(d.copy_state for d in result.deliveries)
    assert states == ["forwarded", "suppressed"] or states == ["suppressed", "forwarded"]


def test_without_suppression_both_copies_are_relayed():
    nodes = [MeshNode("border", 0.0, 0.0), MeshNode("r1", 800.0, 0.0),
             MeshNode("r2", 400.0, 400.0)]
    graph = build_mesh(nodes, border_id="border", radio=RADIO, path_loss=STEEP)
    air = RADIO.airtime_ns
    frames = [MeshFrame(7, "r1", 0), MeshFrame(7, "r2", air + air // 2)]
    result = forward_frames(frames, graph, RADIO, suppress_duplicates=False)
    assert result.transmissions == 2
    assert result.suppressed == 0
    assert result.delivered == 1


def test_obstacle_on_mesh_link_removes_route_when_native_loss_is_used():
    # Même géométrie que le test précédent, exposant 4 : sans obstacle, le relais à 800 m
    # atteint la frontière. Un mur de 60 dB entre les deux supprime la route.
    from lsim.environment import Environment, Obstacle
    from lsim.simulator import Propagation, environment_path_loss_matrix

    nodes = [MeshNode("border", 0.0, 0.0), MeshNode("r1", 800.0, 0.0)]
    plain = build_mesh(nodes, border_id="border", radio=RADIO, path_loss=STEEP)
    assert plain.route("r1") == ("border",)

    wall = Obstacle(x_min_m=300.0, y_min_m=-200.0, x_max_m=500.0, y_max_m=200.0,
                    height_m=40.0, attenuation_db=60.0)
    env = Environment(obstacles=(wall,))
    prop = Propagation(frequency_hz=2.4e9, exponent=4.0)
    matrix = environment_path_loss_matrix([(0.0, 0.0), (800.0, 0.0)], prop, env)
    assert matrix[0 * 2 + 1] >= STEEP.path_loss_db(800.0) + 60.0 - 1e-6  # mur traversé
    walled = build_mesh(nodes, border_id="border", radio=RADIO, path_loss_db=matrix)
    assert walled.route("r1") is None


def test_lorawan_phy_size_matches_spec_layout():
    from lsim.mesh import MESH_ENVELOPE_UP_BYTES, lorawan_phy_bytes

    assert lorawan_phy_bytes(0) == 12        # MHDR + FHDR + MIC, sans FPort ni charge
    assert lorawan_phy_bytes(20) == 33       # + FPort 1 + charge 20
    assert MESH_ENVELOPE_UP_BYTES == 14      # enveloppe mesh en montant
    with pytest.raises(ValueError):
        lorawan_phy_bytes(243)


def test_frame_size_changes_airtime_of_relayed_frame():
    nodes = [MeshNode("border", 0.0, 0.0), MeshNode("r1", 800.0, 0.0)]
    graph = build_mesh(nodes, border_id="border", radio=RADIO, path_loss=STEEP)
    short = forward_frames([MeshFrame(1, "r1", 0, payload_bytes=10)], graph, RADIO).deliveries[0]
    long = forward_frames([MeshFrame(1, "r1", 0, payload_bytes=47)], graph, RADIO).deliveries[0]
    assert short.latency_ns == time_on_air_ns(12, 203_000, 10)
    assert long.latency_ns == time_on_air_ns(12, 203_000, 47)
    assert long.latency_ns > short.latency_ns


def test_downlink_window_thresholds():
    from lsim.mesh import downlink_window

    air = 1_000_000_000  # 1 s par saut
    assert downlink_window(0, 0, air) == "rx1"          # frontière elle-même
    assert downlink_window(0, 1, 900_000_000) == "rx1"  # 0,9 s : RX1
    assert downlink_window(0, 1, air) == "rx1"          # 1,0 s pile : début de RX1 inclus
    assert downlink_window(0, 1, air + 1) == "rx2"      # au-delà de RX1 : RX2
    assert downlink_window(1_000_000_000, 1, air) == "rx2"     # aller-retour 2 s pile : RX2
    assert downlink_window(1_000_000_001, 1, air) == "missed"  # aller-retour > 2 s


# ----------------------------------------------------------- shadowing entre passerelles mesh

def _path_loss_offsets(base, shadowed, n):
    """Écart entre liaisons sans et avec shadowing : rssi_base - rssi_shadowed, par (i, j)."""
    return {(i, j): base.rssi[i * n + j] - shadowed.rssi[i * n + j]
            for i in range(n) for j in range(n) if i != j}


def test_mesh_shadowing_is_reciprocal_and_matches_pair_draw():
    from lsim.mesh import pair_shadowing_db
    nodes = _line(4, 500.0)
    base = build_mesh(nodes, border_id="g0", radio=RADIO, path_loss=STEEP)
    shadowed = build_mesh(nodes, border_id="g0", radio=RADIO, path_loss=STEEP,
                          shadowing_sigma_db=6.0, shadowing_seed=42)
    n = len(nodes)
    off = _path_loss_offsets(base, shadowed, n)
    for i in range(n):
        for j in range(i + 1, n):
            # Un seul tirage par paire : les deux sens reçoivent la même valeur.
            assert off[(i, j)] == pytest.approx(off[(j, i)], abs=1e-9)
            assert off[(i, j)] == pytest.approx(pair_shadowing_db(42, i, j, n, 6.0), abs=1e-9)
    # Les paires ne partagent pas toutes la même valeur.
    assert len({round(v, 6) for v in off.values()}) > 2


def test_mesh_shadowing_is_deterministic_per_seed_and_zero_is_identity():
    nodes = _line(3, 400.0)
    a = build_mesh(nodes, border_id="g0", radio=RADIO, path_loss=STEEP,
                   shadowing_sigma_db=4.0, shadowing_seed=9)
    b = build_mesh(nodes, border_id="g0", radio=RADIO, path_loss=STEEP,
                   shadowing_sigma_db=4.0, shadowing_seed=9)
    c = build_mesh(nodes, border_id="g0", radio=RADIO, path_loss=STEEP,
                   shadowing_sigma_db=4.0, shadowing_seed=10)
    base = build_mesh(nodes, border_id="g0", radio=RADIO, path_loss=STEEP)
    zero = build_mesh(nodes, border_id="g0", radio=RADIO, path_loss=STEEP,
                      shadowing_sigma_db=0.0, shadowing_seed=9)
    assert list(a.rssi) == list(b.rssi)
    assert list(a.rssi) != list(c.rssi)
    assert list(zero.rssi) == list(base.rssi)


def test_mesh_shadowing_bounds_are_checked():
    nodes = _line(2, 300.0)
    with pytest.raises(ValueError):
        build_mesh(nodes, border_id="g0", radio=RADIO, shadowing_sigma_db=-1.0)
    with pytest.raises(ValueError):
        build_mesh(nodes, border_id="g0", radio=RADIO, shadowing_sigma_db=31.0)


def _invariants(result):
    sent = [h for h in result.hops if h.outcome != "suppressed"]
    assert len(sent) == result.transmissions
    assert sum(h.outcome == "suppressed" for h in result.hops) == result.suppressed
    assert sum(h.outcome == "lost_collision" for h in result.hops) == result.lost_collision
    assert sum(h.outcome == "lost_half_duplex" for h in result.hops) == result.lost_half_duplex


def test_hop_log_records_relay_and_suppressed_copy():
    nodes = [MeshNode("border", 0.0, 0.0), MeshNode("r1", 800.0, 0.0),
             MeshNode("r2", 400.0, 400.0)]
    graph = build_mesh(nodes, border_id="border", radio=RADIO, path_loss=STEEP)
    air = RADIO.airtime_ns
    frames = [MeshFrame(7, "r1", 0), MeshFrame(7, "r2", air + air // 2)]
    result = forward_frames(frames, graph, RADIO, with_hops=True)
    _invariants(result)
    sent = [h for h in result.hops if h.outcome != "suppressed"]
    assert [(h.sender_id, h.receiver_id, h.outcome, h.t_start_ns, h.t_end_ns) for h in sent] == [
        ("r1", "border", "received", 0, air)]
    (supp,) = [h for h in result.hops if h.outcome == "suppressed"]
    assert supp.sender_id == "r2" and supp.t_start_ns == supp.t_end_ns == air + air // 2


def test_hop_log_does_not_change_the_result():
    nodes = [MeshNode("border", 0.0, 0.0), MeshNode("r1", 800.0, 0.0),
             MeshNode("r2", 400.0, 400.0)]
    graph = build_mesh(nodes, border_id="border", radio=RADIO, path_loss=STEEP)
    frames = [MeshFrame(k, "r1" if k % 2 else "r2", 1_000 * k) for k in range(40)]
    plain = forward_frames(frames, graph, RADIO)
    logged = forward_frames(frames, graph, RADIO, with_hops=True)
    assert plain.deliveries == logged.deliveries
    assert (plain.transmissions, plain.suppressed) == (logged.transmissions, logged.suppressed)
    assert plain.hops == ()
    _invariants(logged)


def test_hop_log_reports_collisions_on_the_intended_hop():
    # Même géométrie que le test de capture : g1 et g3 émettent vers g2 en même temps.
    nodes = [MeshNode("g0", 0.0, 0.0), MeshNode("g2", 800.0, 0.0),
             MeshNode("g1", 1600.0, 0.0), MeshNode("g3", 800.0, 400.0)]
    graph = build_mesh(nodes, border_id="g0", radio=RADIO, path_loss=STEEP)
    frames = [MeshFrame(1, "g1", 0), MeshFrame(2, "g3", 0)]
    result = forward_frames(frames, graph, RADIO, with_hops=True)
    _invariants(result)
    lost = [h for h in result.hops if h.outcome == "lost_collision"]
    assert [(h.sender_id, h.receiver_id) for h in lost] == [("g1", "g2")]


def test_hop_log_grows_past_the_initial_buffer():
    # Chaîne de 8 sauts : chaque trame produit 8 émissions, donc plus de 4 × trames. Le natif
    # répond « tampon trop petit » et le journal est relu avec la taille requise.
    nodes = _line(MAX_HOPS + 1, 800.0)
    graph = build_mesh(nodes, border_id="g0", radio=RADIO, path_loss=STEEP)
    air = RADIO.airtime_ns
    frames = [MeshFrame(k, f"g{MAX_HOPS}", 12 * air * k) for k in range(50)]  # sans chevauchement
    result = forward_frames(frames, graph, RADIO, with_hops=True)
    assert len(result.hops) > 4 * len(frames)  # réessai déclenché (copies perdues en route incluses)
    assert result.delivered == len(frames)
    _invariants(result)
