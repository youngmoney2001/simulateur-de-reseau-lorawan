"""Simulation d'une session : compilation de la topologie et de la configuration CLI, création du run,
liaison automatique et notation (routes `POST /sessions/{id}/simulate`, `nodes`, `sensor`)."""

import pytest

from lsim.study_contract import SimulateOut, SubmitResult
from test_api_server import _make_api, _wait_done


@pytest.fixture()
def api(tmp_path):
    with _make_api(tmp_path) as a:
        yield a


def _session(api, exercise=None, nodes=None):
    body = {}
    if exercise is not None:
        body["exercise_id"] = exercise
    if nodes is not None:
        body["nodes"] = nodes
    status, out = api.call("POST", "/api/v1/sessions", body, token=api.alice)
    assert status == 201, out
    return out["session_id"]


def _cli(api, sid, node, *lines):
    last = None
    for line in lines:
        status, last = api.call("POST", f"/api/v1/sessions/{sid}/cli",
                                {"node_id": node, "command": line})
        assert status == 200, last
        assert last.get("error") is None, (line, last)
    return last


def _simulate(api, sid, seed=0):
    return api.call("POST", f"/api/v1/sessions/{sid}/simulate", {"seed": seed})


def _sensor(x=500, **settings):
    return {"id": "capteur-1", "kind": "sensor", "name": "Capteur", "x_m": x, "y_m": 0,
            "sensor": settings or None}


def _border(name="frontiere", x=0, y=0):
    return {"id": name, "kind": "border", "name": "Frontière", "x_m": x, "y_m": y}


def _relay(name="relais-1", x=1200, y=0):
    return {"id": name, "kind": "relay", "name": "Relais", "x_m": x, "y_m": y}


# --- Compilation et run -------------------------------------------------------------------------

def test_a_session_simulates_its_own_topology_and_binds_the_result(api):
    sid = _session(api, nodes=[_border(), _sensor()])
    _cli(api, sid, "frontiere", "enable", "configure terminal", "interface lora 0",
         "region EU868", "exit", "lorawan server 10.0.0.5 up-port 1700 down-port 1701", "end")
    status, out = _simulate(api, sid)
    assert status == 202, out
    sim = SimulateOut.model_validate(out)
    assert sim.links and [link.node_id for link in sim.links] == ["frontiere"]
    assert any("non modélisés" in note for note in sim.notes)
    done = _wait_done(api, sim.run_id, token=api.alice)
    assert done["state"] == "done", done
    status, bound = api.call("POST", f"/api/v1/sessions/{sid}/simulation", {"run_id": sim.run_id})
    assert status == 200, bound
    assert bound["linked"] == ["frontiere"] and bound["unlinked"] == ["capteur-1"]
    # `show lorawan counters` lit désormais le résultat de ce run
    status, shown = api.call("POST", f"/api/v1/sessions/{sid}/cli",
                             {"node_id": "frontiere", "command": "show lorawan counters"})
    assert status == 200 and "received" in shown["output"], shown


def test_simulation_refuses_a_session_without_gateway_or_sensor(api):
    sid = _session(api, nodes=[_border()])
    status, body = _simulate(api, sid)
    assert status == 422 and body["field"] == "nodes" and "capteur" in body["message"]
    sid = _session(api, nodes=[_sensor()])
    status, body = _simulate(api, sid)
    assert status == 422 and "passerelle" in body["message"]


def test_simulation_applies_regional_defaults_and_says_so(api):
    sid = _session(api, nodes=[_border(), _sensor()])
    status, out = _simulate(api, sid)
    assert status == 202
    assert any("EU868 appliqué" in note for note in out["notes"])


def test_sensor_region_must_match_the_gateways(api):
    sid = _session(api, nodes=[_border(), _sensor(region="US915")])
    _cli(api, sid, "frontiere", "enable", "configure terminal", "interface lora 0", "region EU868",
         "exit", "end")
    status, body = _simulate(api, sid)
    assert status == 422 and body["field"] == "nodes" and "capteur-1" in body["message"]


# --- Édition de la topologie ----------------------------------------------------------------

def test_nodes_can_be_added_configured_and_removed(api):
    sid = _session(api, nodes=[_border()])
    status, out = api.call("POST", f"/api/v1/sessions/{sid}/nodes", _sensor(x=300))
    assert status == 201 and {n["id"] for n in out["nodes"]} == {"frontiere", "capteur-1"}
    status, out = api.call("POST", f"/api/v1/sessions/{sid}/nodes/capteur-1/sensor",
                           {"spreading_factor": 10, "payload_bytes": 12})
    assert status == 200
    sensor = next(n for n in out["nodes"] if n["id"] == "capteur-1")["sensor"]
    assert sensor["spreading_factor"] == 10 and sensor["payload_bytes"] == 12
    status, _ = api.call("DELETE", f"/api/v1/sessions/{sid}/nodes/capteur-1")
    assert status == 204
    status, out = api.call("GET", f"/api/v1/sessions/{sid}/topology")
    assert [n["id"] for n in out["nodes"]] == ["frontiere"]


def test_node_ids_are_unique_and_sensor_settings_only_on_sensors(api):
    sid = _session(api, nodes=[_border()])
    status, body = api.call("POST", f"/api/v1/sessions/{sid}/nodes", _border())
    assert status == 422 and body["field"] == "id"
    status, body = api.call("POST", f"/api/v1/sessions/{sid}/nodes",
                            dict(_border("gw2"), sensor={"spreading_factor": 9}))
    assert status == 422
    status, body = api.call("POST", f"/api/v1/sessions/{sid}/nodes/frontiere/sensor",
                            {"spreading_factor": 9})
    assert status == 422 and body["field"] == "node_id"


def test_unknown_node_or_other_owner_is_not_found(api):
    sid = _session(api, nodes=[_border()])
    status, _ = api.call("DELETE", f"/api/v1/sessions/{sid}/nodes/inconnu")
    assert status == 404
    status, _ = api.call("POST", f"/api/v1/sessions/{sid}/simulate", {"seed": 0}, token=api.bob)
    assert status == 404


# --- Réglages mesh et relais ---------------------------------------------------------------

def test_mesh_settings_of_the_border_and_relays_must_agree(api):
    sid = _session(api, nodes=[_border(), _relay(), _sensor(x=1500)])
    _cli(api, sid, "frontiere", "enable", "configure terminal", "interface lora 0", "region EU868",
         "exit", "interface mesh 0", "spreading-factor 9", "exit", "end")
    _cli(api, sid, "relais-1", "enable", "configure terminal", "interface mesh 0",
         "spreading-factor 10", "exit", "end")
    status, body = _simulate(api, sid)
    assert status == 422 and "SF mesh" in body["message"]


def test_relay_mode_must_match_its_role(api):
    sid = _session(api, nodes=[_border(), _relay(), _sensor(x=1500)])
    _cli(api, sid, "relais-1", "enable", "configure terminal", "interface mesh 0", "mode border",
         "exit", "end")
    status, body = _simulate(api, sid)
    assert status == 422 and "relais-1" in body["message"]


def test_a_relay_network_needs_exactly_one_border(api):
    sid = _session(api, nodes=[_relay(), _sensor(x=1500)])
    status, body = _simulate(api, sid)
    assert status == 422 and "frontière" in body["message"]


def test_a_stopped_gateway_leaves_the_run_and_is_not_linked(api):
    sid = _session(api, nodes=[_border(), _border("ip-ouest", x=-2500), _sensor()])
    _cli(api, sid, "ip-ouest", "enable", "configure terminal", "interface lora 0", "shutdown",
         "end")
    status, out = _simulate(api, sid)
    assert status == 202
    assert [link["node_id"] for link in out["links"]] == ["frontiere"]


def test_the_simulation_result_grades_the_relay_exercise(api):
    """Exercice relais : configuration par CLI, simulation, liaison automatique, notation."""
    sid = _session(api, exercise="relais-deux-sauts")
    _cli(api, sid, "frontiere", "enable", "configure terminal", "interface lora 0", "region EU868",
         "exit", "end")
    _cli(api, sid, "relais-1", "enable", "configure terminal", "interface mesh 0", "mode relay",
         "max-hops 2", "exit", "end")
    status, out = _simulate(api, sid)
    assert status == 202, out
    done = _wait_done(api, out["run_id"], token=api.alice)
    assert done["state"] == "done"
    status, bound = api.call("POST", f"/api/v1/sessions/{sid}/simulation", {"run_id": out["run_id"]})
    assert status == 200 and set(bound["linked"]) == {"frontiere", "relais-1"}
    status, result = api.call("POST", "/api/v1/exercises/relais-deux-sauts/submit",
                              {"session_id": sid}, token=api.alice)
    assert status == 200
    graded = SubmitResult.model_validate(result)
    passed = {c.id: c.passed for c in graded.criteria}
    assert passed == {"mode": True, "sauts": True, "lien": True}, graded
    assert graded.score == 30


def _run_and_grade(api, sid, exercise):
    status, out = _simulate(api, sid)
    assert status == 202, out
    done = _wait_done(api, out["run_id"], token=api.alice)
    assert done["state"] == "done", done
    status, bound = api.call("POST", f"/api/v1/sessions/{sid}/simulation", {"run_id": out["run_id"]})
    assert status == 200, bound
    status, result = api.call("POST", f"/api/v1/exercises/{exercise}/submit",
                              {"session_id": sid}, token=api.alice)
    assert status == 200, result
    return SubmitResult.model_validate(result)


def test_the_eu868_exercise_is_graded_on_its_configuration(api):
    sid = _session(api, exercise="eu868-passerelle")
    _cli(api, sid, "frontiere", "enable", "configure terminal", "interface lora 0", "region EU868",
         "exit", "lorawan server 10.0.0.5 up-port 1700 down-port 1701", "end")
    graded = _run_and_grade(api, sid, "eu868-passerelle")
    assert graded.score == 20 and all(c.passed for c in graded.criteria)


def test_the_us915_exercise_checks_the_sub_band_and_a_received_frame(api):
    sid = _session(api, exercise="us915-sous-bande")
    _cli(api, sid, "frontiere", "enable", "configure terminal", "interface lora 0", "region US915",
         "sub-band 2", "exit", "end")
    graded = _run_and_grade(api, sid, "us915-sous-bande")
    assert {c.id: c.passed for c in graded.criteria} == {
        "region": True, "sous-bande": True, "reception": True}, graded


def test_the_latency_exercise_reads_the_latency_of_the_simulation(api):
    sid = _session(api, exercise="latence-frontiere")
    graded = _run_and_grade(api, sid, "latence-frontiere")
    assert graded.score == 0 and not graded.criteria[0].passed   # mesh à 203 kHz : p95 ~ 790 ms

    sid = _session(api, exercise="latence-frontiere")
    _cli(api, sid, "frontiere", "enable", "configure terminal", "interface mesh 0", "bandwidth 812",
         "exit", "end")
    _cli(api, sid, "relais-1", "enable", "configure terminal", "interface mesh 0", "bandwidth 812",
         "exit", "end")
    graded = _run_and_grade(api, sid, "latence-frontiere")
    assert graded.score == 20 and graded.criteria[0].passed, graded


def test_mesh_bandwidth_must_agree_between_border_and_relays(api):
    sid = _session(api, nodes=[_border(), _relay(), _sensor(x=1500)])
    _cli(api, sid, "frontiere", "enable", "configure terminal", "interface mesh 0", "bandwidth 812",
         "exit", "end")
    _cli(api, sid, "relais-1", "enable", "configure terminal", "interface mesh 0", "bandwidth 406",
         "exit", "end")
    status, body = _simulate(api, sid)
    assert status == 422 and "bande mesh" in body["message"]


def test_a_payload_too_large_for_the_mesh_is_refused_at_simulation_creation(api):
    """La refus du mesh (charge > 228 o relayée) s'applique à la simulation de session, comme à
    `POST /runs` : refusé à la création, pas à l'exécution."""
    sid = _session(api, nodes=[_border(), _relay(), _sensor(x=1500, payload_bytes=240)])
    _cli(api, sid, "frontiere", "enable", "configure terminal", "interface lora 0", "region EU868",
         "exit", "end")
    status, body = _simulate(api, sid)
    assert status == 422, body
    assert body["field"] and "mesh" in body["message"].lower()


# --- Plan, liste et suppression des sessions -------------------------------------------------

def test_a_node_moves_on_the_plan_and_keeps_its_configuration(api):
    sid = _session(api, nodes=[_border()])
    _cli(api, sid, "frontiere", "enable", "configure terminal", "hostname gw-nord", "end")
    status, out = api.call("POST", f"/api/v1/sessions/{sid}/nodes/frontiere/position",
                           {"x_m": 120.5, "y_m": -40})
    assert status == 200
    node = out["nodes"][0]
    assert (node["x_m"], node["y_m"]) == (120.5, -40.0)
    assert out["states"][0]["hostname"] == "gw-nord"


def test_sessions_are_listed_per_owner_and_can_be_deleted(api):
    first = _session(api, nodes=[_border()])
    second = _session(api, exercise="eu868-passerelle")
    status, out = api.call("GET", "/api/v1/sessions")
    assert status == 200
    ids = [item["session_id"] for item in out["items"]]
    assert ids[0] == second and first in ids
    assert {i["session_id"]: i["nodes"] for i in out["items"]}[first] == 1
    bob_status, bob = api.call("GET", "/api/v1/sessions", token=api.bob)
    assert bob_status == 200 and bob["items"] == []
    status, _ = api.call("DELETE", f"/api/v1/sessions/{first}", token=api.bob)
    assert status == 404
    status, _ = api.call("DELETE", f"/api/v1/sessions/{first}")
    assert status == 204
    status, out = api.call("GET", "/api/v1/sessions")
    assert first not in [item["session_id"] for item in out["items"]]
    status, _ = api.call("GET", f"/api/v1/sessions/{first}/topology")
    assert status == 404
