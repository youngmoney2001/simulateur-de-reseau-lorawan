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
    assert m.delivered == m.direct + m.via_mesh
    assert m.delivered <= m.frames <= run.totals.sent
    assert run.totals.received == m.delivered
    assert sum(r.received for r in run.rows) == m.delivered
    lost_copies = sum(n for _, n in m.losses)
    assert lost_copies <= m.copies_on_mesh
    # Chaque trame « via mesh » a au moins une copie remise.
    assert m.copies_on_mesh - lost_copies >= m.via_mesh
    assert run.gateway is None


def test_border_only_mesh_delivers_every_decoded_frame():
    d = _base([BORDER, {"name": "ip", "x_m": 500, "y_m": 0}], mesh={"border": "frontiere"})
    run = run_scenario(_scenario(d))
    assert run.mesh.copies_on_mesh == 0
    assert run.mesh.delivered == run.mesh.frames
    assert run.mesh.via_mesh == 0


def test_relay_out_of_range_of_border_loses_copies_as_no_route():
    far_border = {"name": "frontiere", "x_m": 60_000, "y_m": 0, "profile": "rak5148", "mesh": True}
    d = _base([far_border, {"name": "relais", **RELAY}], mesh={"border": "frontiere"}, radius=300)
    run = run_scenario(_scenario(d))
    assert run.mesh.frames > 0
    assert run.mesh.delivered == 0
    assert dict(run.mesh.losses) == {"no_route": run.mesh.copies_on_mesh}


def test_no_mesh_multi_gateway_matches_network_dedup():
    d = _base([{"name": "a", "x_m": 0, "y_m": 0}, {"name": "b", "x_m": 1500, "y_m": 0}])
    run = run_scenario(_scenario(d))
    assert run.mesh is None
    assert run.gateway is None
    assert run.totals.received == sum(r.received for r in run.rows)
