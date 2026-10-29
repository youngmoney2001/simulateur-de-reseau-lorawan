"""Scénarios multi-passerelles et relais mesh dans `run_scenario`."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from lsim.export import run_scenario
from lsim.scenario import Scenario, ScenarioModel, load_scenario

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "mesh_relais_quartier.yaml"


def _base(gateways, mesh=None, radius=500.0, count=40):
    d = {
        "schema_version": 1,
        "name": "test mesh",
        "seed": 7,
        "gateways": gateways,
        "propagation": {"frequency_hz": 868100000, "exponent": 2.7},
        "groups": [{
            "name": "c", "count": count,
            "placement": {"type": "disk", "radius_m": radius},
            "spreading_factor": 9, "payload_bytes": 20, "tx_power_dbm": 14,
            "period_s": 900, "messages": 4, "start_spread_s": 900,
        }],
    }
    if mesh is not None:
        d["mesh"] = mesh
    return d


def _scenario(d):
    return Scenario(ScenarioModel.model_validate(d))


RELAY = {"x_m": 0, "y_m": 0, "profile": "rak5148", "mesh": True}
BORDER = {"name": "frontiere", "x_m": 0, "y_m": 0, "profile": "rak5148", "mesh": True}


def test_example_file_is_valid_and_declares_mesh():
    s = load_scenario(EXAMPLE)
    assert s.is_multi_gateway
    assert s.model.mesh is not None and s.model.mesh.border == "frontiere"
    assert [g.name for g in s.gateway_models()] == [
        "frontiere", "relais-1", "relais-2", "ip-ouest"]


def test_legacy_single_gateway_is_unchanged():
    d = _base([{"name": "gw", "x_m": 0, "y_m": 0}])
    d.pop("gateways")
    d["gateway"] = {"x_m": 0, "y_m": 0}
    s = _scenario(d)
    assert not s.is_multi_gateway
    assert len(s.gateway_models()) == 1


@pytest.mark.parametrize("mutate, message", [
    (lambda d: d.update(mesh={"border": "absente"}), "mesh.border"),
    (lambda d: d.update(mesh={"border": "frontiere"}, gateways=[
        {"name": "frontiere", "x_m": 0, "y_m": 0}]), "mesh: true"),
    (lambda d: d.update(gateways=[{"name": "r", "x_m": 0, "y_m": 0, "mesh": True}]),
     "profil"),
    (lambda d: d.update(gateways=[{"name": "r", "x_m": 0, "y_m": 0, "profile": "rak7249",
                                   "mesh": True}]), "profil"),
    (lambda d: d.update(gateways=[{"name": "r", "x_m": 0, "y_m": 0, "profile": "inconnu"}]),
     "inconnu"),
    (lambda d: d.update(gateways=[{"x_m": 0, "y_m": 0}]), "nom"),
    (lambda d: d.update(gateways=[{"name": "a", "x_m": 0, "y_m": 0},
                                  {"name": "a", "x_m": 1, "y_m": 0}]), "uniques"),
    (lambda d: d.update(gateway={"x_m": 0, "y_m": 0}), "pas les deux"),
])
def test_invalid_mesh_declarations_are_refused(mutate, message):
    d = _base([{"name": "x", "x_m": 0, "y_m": 0}])
    d.pop("gateways", None)
    d["gateways"] = [{"name": "a", "x_m": 0, "y_m": 0}]
    d.pop("mesh", None)
    mutate(d)
    with pytest.raises((ValidationError, ValueError), match=message):
        _scenario(d)


def test_mesh_block_without_gateways_list_is_refused():
    d = _base([{"name": "x", "x_m": 0, "y_m": 0}])
    d.pop("gateways")
    d["mesh"] = {"border": "x"}
    with pytest.raises((ValidationError, ValueError), match="gateways"):
        _scenario(d)


def test_mesh_run_invariants_on_example_scaled_down(tmp_path):
    text = EXAMPLE.read_text(encoding="utf-8").replace("count: 300", "count: 40")
    path = tmp_path / "small.yaml"
    path.write_text(text, encoding="utf-8")
    run = run_scenario(load_scenario(path))
    m = run.mesh
    assert m is not None
    # Remises : sans saut, ou après saut ; une trame n'est comptée qu'une fois.
    assert m.delivered == m.direct + m.via_mesh
    assert m.delivered <= m.frames <= run.totals.sent
    assert run.totals.received == m.delivered
    assert sum(r.received for r in run.rows) == m.delivered
    # Une copie confiée au mesh finit relayée, supprimée ou sans route (au plus une issue).
    assert m.suppressed + m.no_route <= m.copies_on_mesh
    # Chaque saut effectif est une émission ; un saut perdu en est une.
    assert sum(n for _, n in m.hop_losses) <= m.transmissions
    assert m.transmissions >= m.via_mesh
    assert run.gateway is None


def test_border_only_mesh_delivers_every_decoded_frame():
    d = _base([BORDER, {"name": "ip", "x_m": 500, "y_m": 0}], mesh={"border": "frontiere"})
    run = run_scenario(_scenario(d))
    assert run.mesh.copies_on_mesh == 0
    assert run.mesh.transmissions == 0
    assert run.mesh.delivered == run.mesh.frames
    assert run.mesh.via_mesh == 0


def test_relay_out_of_range_of_border_loses_copies_as_no_route():
    far_border = {"name": "frontiere", "x_m": 60_000, "y_m": 0, "profile": "rak5148", "mesh": True}
    d = _base([far_border, {"name": "relais", **RELAY}], mesh={"border": "frontiere"}, radius=300)
    run = run_scenario(_scenario(d))
    assert run.mesh.frames > 0
    assert run.mesh.delivered == 0
    assert run.mesh.no_route == run.mesh.copies_on_mesh
    assert run.mesh.hop_losses == ()
    assert run.mesh.transmissions == 0


def test_no_mesh_multi_gateway_matches_network_dedup():
    d = _base([{"name": "a", "x_m": 0, "y_m": 0}, {"name": "b", "x_m": 1500, "y_m": 0}])
    run = run_scenario(_scenario(d))
    assert run.mesh is None
    assert run.gateway is None
    assert run.totals.received == sum(r.received for r in run.rows)


def test_geojson_multi_gateway_has_one_coverage_per_gateway(tmp_path):
    from lsim.geo import to_geojson

    s = load_scenario(EXAMPLE)
    doc = to_geojson(run_scenario(s), s, 4.0511, 9.7679)
    gateways = [f for f in doc["features"] if f["properties"].get("kind") == "gateway"]
    names = [f["properties"]["name"] for f in gateways]
    assert names == ["frontiere", "relais-1", "relais-2", "ip-ouest"]
    assert [f["properties"]["mesh"] for f in gateways] == [True, True, True, False]
    cov = [f["properties"] for f in doc["features"] if f["properties"].get("kind") == "coverage"]
    assert {p["gateway"] for p in cov} == set(names)
    assert len(cov) == len(names) * len(s.model.groups)


def test_geojson_single_gateway_keeps_legacy_name():
    from lsim.geo import to_geojson

    d = _base([{"name": "gw", "x_m": 0, "y_m": 0}])
    d.pop("gateways")
    d["gateway"] = {"x_m": 0, "y_m": 0}
    s = _scenario(d)
    doc = to_geojson(run_scenario(s), s, 4.0511, 9.7679)
    gw = [f["properties"] for f in doc["features"] if f["properties"].get("kind") == "gateway"]
    assert [g["name"] for g in gw] == ["passerelle"]


def test_wall_on_relay_path_removes_mesh_delivery(tmp_path):
    # Dispositifs autour du relais (800 m) ; le mur est entre la frontière et le relais,
    # donc il coupe le lien mesh sans couper l'accès des dispositifs au relais.
    def scenario_dict():
        d = _base([BORDER, {"name": "relais", "x_m": 800, "y_m": 0, "profile": "rak5148",
                            "mesh": True}],
                  mesh={"border": "frontiere"}, radius=100)
        d["groups"][0]["placement"]["center_x_m"] = 800
        return d

    open_run = run_scenario(_scenario(scenario_dict()))
    walled = scenario_dict()
    walled["environment"] = {
        "gateway_height_m": 15, "device_height_m": 1.5,
        "obstacles": [{"x_min_m": 300, "y_min_m": -300, "x_max_m": 500, "y_max_m": 300,
                       "height_m": 30, "attenuation_db": 60}],
    }
    import yaml

    path = tmp_path / "walled.yaml"
    path.write_text(yaml.safe_dump(walled, allow_unicode=True), encoding="utf-8")
    closed_run = run_scenario(load_scenario(path))
    # Ouvert : le relais a une route et relaie. Mur : aucune route, copies perdues sans route.
    assert open_run.mesh.copies_on_mesh > 0
    assert open_run.mesh.no_route == 0
    assert open_run.mesh.transmissions > 0
    assert closed_run.mesh.copies_on_mesh > 0
    assert closed_run.mesh.no_route == closed_run.mesh.copies_on_mesh
    assert closed_run.mesh.transmissions == 0


def test_downlink_windows_partition_delivered_frames():
    s = load_scenario(EXAMPLE)
    m = run_scenario(s).mesh
    assert m.dl_rx1 + m.dl_rx2 + m.dl_missed == m.delivered
    assert m.dl_mesh_airtime_ns > 0


def test_frame_size_fixed_is_available_for_comparison(tmp_path):
    text = EXAMPLE.read_text(encoding="utf-8").replace("count: 300", "count: 40")
    text = text.replace("  payload_bytes: 32\n", "  frame_size: fixed\n  payload_bytes: 32\n")
    path = tmp_path / "fixed.yaml"
    path.write_text(text, encoding="utf-8")
    run = run_scenario(load_scenario(path))
    assert run.mesh is not None and run.mesh.copies_on_mesh > 0


def test_frame_size_defaults_to_device_payload():
    from lsim.scenario import MeshModel

    assert MeshModel(border="x").frame_size == "device"
    assert MeshModel(border="x").payload_bytes == 32


def test_mesh_shadowing_is_a_scenario_field_with_bounds():
    base = _base([BORDER, {"name": "ip", "x_m": 500, "y_m": 0}],
                 mesh={"border": "frontiere", "shadowing_sigma_db": 6.0})
    assert _scenario(base).model.mesh.shadowing_sigma_db == 6.0
    with pytest.raises(ValidationError):
        _scenario(_base([BORDER], mesh={"border": "frontiere", "shadowing_sigma_db": 31.0}))
    with pytest.raises(ValidationError):
        _scenario(_base([BORDER], mesh={"border": "frontiere", "shadowing_sigma_db": -0.5}))


def test_mesh_shadowing_changes_routing_inputs_deterministically():
    text = EXAMPLE.read_text(encoding="utf-8").replace("count: 300", "count: 40")
    text_sh = text.replace("max_hops: 8", "max_hops: 8\n  shadowing_sigma_db: 8")
    assert text_sh != text
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        p1 = Path(tmp) / "a.yaml"
        p1.write_text(text_sh, encoding="utf-8")
        r1 = run_scenario(load_scenario(p1))
        r2 = run_scenario(load_scenario(p1))
    assert r1.mesh is not None
    assert r1.mesh.delivered == r2.mesh.delivered
    assert r1.mesh.transmissions == r2.mesh.transmissions


def test_host_profile_is_refused_as_radio_gateway():
    d = _base([{"name": "h", "x_m": 0, "y_m": 0, "profile": "rak7391"},
               {"name": "ip", "x_m": 500, "y_m": 0}])
    with pytest.raises(ValidationError, match="hôte sans radio"):
        _scenario(d)


RELAY_1 = {"name": "relais-1", "x_m": 1200, "y_m": 0, "profile": "rak5148", "mesh": True}
RELAY_2 = {"name": "relais-2", "x_m": 2400, "y_m": 0, "profile": "rak5148", "mesh": True}


def _relay_needed(sigma=None):
    """Frontière seule à portée des dispositifs (tx -14 dBm) : le mesh doit sauver les trames."""
    mesh = {"border": "frontiere"}
    if sigma is not None:
        mesh["shadowing_sigma_db"] = sigma
    d = _base([BORDER, RELAY_1, RELAY_2], mesh=mesh, radius=3500, count=150)
    d["groups"][0]["tx_power_dbm"] = -14
    return d


def test_shadowing_changes_delivery_when_relays_are_needed():
    """Sensibilité : sans shadowing, toutes les trames relayées arrivent ; avec 8 dB, des
    relais tombent sous la sensibilité et des trames sont perdues (graine 7, déterministe)."""
    r0 = run_scenario(_scenario(_relay_needed(0.0)))
    r8 = run_scenario(_scenario(_relay_needed(8.0)))
    assert r0.mesh.via_mesh > 0
    assert r0.mesh.delivered == r0.mesh.frames
    assert r8.mesh.delivered < r0.mesh.delivered
    assert r8.mesh.frames == r0.mesh.frames


def test_shadowing_is_inert_when_border_hears_every_frame():
    """Exemple livré : la frontière entend toutes les trames en direct, le mesh ne sert qu'à
    des copies redondantes. Le shadowing ne change donc pas la livraison."""
    text = EXAMPLE.read_text(encoding="utf-8").replace("count: 300", "count: 40")
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        outs = []
        for sigma in (0, 30):
            p = Path(tmp) / f"s{sigma}.yaml"
            p.write_text(text.replace("max_hops: 8", f"max_hops: 8\n  shadowing_sigma_db: {sigma}"),
                         encoding="utf-8")
            outs.append(run_scenario(load_scenario(p)).mesh)
    for m in outs:
        assert m.via_mesh == 0 and m.direct == m.frames
    assert outs[0].delivered == outs[1].delivered


def test_export_balances_with_mesh_losses_and_matches_the_trace(tmp_path):
    """Trames décodées à l'accès puis perdues sur le mesh : comptées dans `mesh.lost_mesh`, de sorte
    que sent = received + pertes accès + lost_mesh, et égales à la trace API."""
    from pathlib import Path

    from lsim.trace_events import ProtocolOptions, build_multi_trace

    text = (Path(__file__).resolve().parents[2] / "examples" / "mesh_relais_quartier.yaml"
            ).read_text(encoding="utf-8")
    text = text.replace("  spreading_factor: 9\n  bandwidth_khz", "  spreading_factor: 12\n  bandwidth_khz")
    path = tmp_path / "lossy.yaml"
    path.write_text(text, encoding="utf-8")
    sc = load_scenario(path)
    run = run_scenario(sc)
    t = run.totals
    assert run.mesh is not None and run.mesh.lost_mesh > 0, "le scénario doit perdre des trames mesh"
    assert t.sent == t.received + t.lost_sensitivity + t.lost_collision + t.lost_gateway_busy \
        + run.mesh.lost_mesh
    assert run.mesh.lost_mesh == build_multi_trace(sc, ProtocolOptions()).lost_mesh
    assert run.mesh.frames == run.mesh.delivered + run.mesh.lost_mesh


def test_relay_module_alone_cannot_serve_sub_ghz_sensors():
    """Un relais RAK5148 seul ne reçoit pas les capteurs EU868 : refusé à la validation."""
    def scenario(profile, region):
        border = {"name": "frontiere", "x_m": 0, "y_m": 0, "profile": "rak5146-rak5148", "mesh": True}
        d = _base([border, {"name": "relais", "x_m": 800, "y_m": 0, "profile": profile, "mesh": True}],
                  mesh={"border": "frontiere", "spreading_factor": 9, "bandwidth_khz": 203, "max_hops": 2})
        d["groups"][0]["region"] = region
        return d
    with pytest.raises(ValidationError, match="sans accès EU868"):
        _scenario(scenario("rak5148", "EU868"))
    _scenario(scenario("rak5146-rak5148", "EU868"))          # relais composite : accepté
    _scenario(scenario("rak5148", None))                     # sans région : le moteur ne contraint pas
