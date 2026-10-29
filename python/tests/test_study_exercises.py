"""Catalogue et soumission des exercices notés (`lsim.study_exercises`, routes du panneau).

La note est calculée par le serveur sur l'état de la session. Le client n'envoie que
`session_id` : tout champ de résultat est refusé.
"""

import json

import pytest

from lsim import study_exercises
from lsim.study_contract import ExerciseList, SubmitResult
from test_api_server import _make_api, _scenario, _wait_done


@pytest.fixture()
def api(tmp_path):
    with _make_api(tmp_path) as a:
        yield a


def _session(api, exercise=None, nodes=None, token=None):
    body = {}
    if exercise is not None:
        body["exercise_id"] = exercise
    if nodes is not None:
        body["nodes"] = nodes
    status, out = api.call("POST", "/api/v1/sessions", body, token=token or api.alice)
    return status, out


def _cli(api, sid, node, *lines):
    last = None
    for line in lines:
        status, last = api.call("POST", f"/api/v1/sessions/{sid}/cli",
                                {"node_id": node, "command": line})
        assert status == 200, last
    return last


def _submit(api, exercise, sid, token=None, extra=None):
    body = {"session_id": sid}
    body.update(extra or {})
    return api.call("POST", f"/api/v1/exercises/{exercise}/submit", body,
                    token=token or api.alice)


def _points(result):
    return {c["id"]: c["passed"] for c in result["criteria"]}


# --- Catalogue -------------------------------------------------------------------------------

def test_catalogue_lists_exercises_without_criteria_or_solution(api):
    status, body = api.call("GET", "/api/v1/exercises")
    assert status == 200
    ExerciseList.model_validate(body)
    assert {e["id"] for e in body["items"]} == {e.id for e in study_exercises.EXERCISES}
    text = json.dumps(body, ensure_ascii=False)
    assert "criteria" not in text and "check" not in text
    for ex in study_exercises.EXERCISES:
        assert all(c.label not in text for c in ex.criteria)
        item = next(i for i in body["items"] if i["id"] == ex.id)
        assert item["max_points"] == ex.max_points
        assert item["hints_available"] == len(ex.hints) == 2


def test_catalogue_needs_a_token(api):
    status, _ = api.call("GET", "/api/v1/exercises", token=None)
    assert status == 401


# --- Création d'une session liée à un exercice -----------------------------------------------

def test_exercise_session_starts_with_the_exercise_topology(api):
    status, out = _session(api, exercise="relais-deux-sauts")
    assert status == 201 and out["exercise_id"] == "relais-deux-sauts"
    _, topo = api.call("GET", f"/api/v1/sessions/{out['session_id']}/topology")
    assert [n["id"] for n in topo["nodes"]] == ["frontiere", "relais-1"]


def test_exercise_session_refuses_its_own_topology_and_unknown_exercises(api):
    status, body = _session(api, exercise="eu868-passerelle", nodes=[
        {"id": "x", "kind": "border", "name": "X", "x_m": 0, "y_m": 0}])
    assert status == 422 and body["field"] == "nodes"
    status, body = _session(api, exercise="inconnu-000")
    assert status == 422 and body["field"] == "exercise_id"


def test_session_without_nodes_is_an_empty_topology(api):
    status, out = _session(api)
    assert status == 201
    _, topo = api.call("GET", f"/api/v1/sessions/{out['session_id']}/topology")
    assert topo["nodes"] == [] and topo["states"] == []


# --- Soumission ------------------------------------------------------------------------------

def test_empty_work_scores_zero_and_lists_every_criterion(api):
    _, out = _session(api, exercise="eu868-passerelle")
    status, body = _submit(api, "eu868-passerelle", out["session_id"])
    assert status == 200
    res = SubmitResult.model_validate(body)
    assert res.score == 0 and res.max_score == 20 and res.hints_used == 0
    assert [c.id for c in res.criteria] == ["region", "serveur"]
    assert not any(c.passed for c in res.criteria)


def test_full_configuration_scores_the_maximum(api):
    _, out = _session(api, exercise="eu868-passerelle")
    sid = out["session_id"]
    _cli(api, sid, "frontiere", "en", "conf t", "int lora 0", "region EU868", "exit",
         "lorawan server 10.0.0.5 up-port 1700 down-port 1701", "end")
    _, body = _submit(api, "eu868-passerelle", sid)
    assert body["score"] == 20 and all(c["passed"] for c in body["criteria"])


def test_partial_configuration_gets_partial_points(api):
    _, out = _session(api, exercise="eu868-passerelle")
    sid = out["session_id"]
    _cli(api, sid, "frontiere", "en", "conf t", "int lora 0", "region EU868", "end")
    _, body = _submit(api, "eu868-passerelle", sid)
    assert body["score"] == 10 and _points(body) == {"region": True, "serveur": False}


def test_wrong_value_does_not_pass(api):
    _, out = _session(api, exercise="eu868-passerelle")
    sid = out["session_id"]
    _cli(api, sid, "frontiere", "en", "conf t", "int lora 0", "region US915", "end")
    _, body = _submit(api, "eu868-passerelle", sid)
    assert _points(body)["region"] is False and body["score"] == 0


def test_mesh_criteria_read_the_relay_configuration(api):
    _, out = _session(api, exercise="relais-deux-sauts")
    sid = out["session_id"]
    _cli(api, sid, "relais-1", "en", "conf t", "int mesh 0", "mode relay", "max-hops 3", "end")
    _, body = _submit(api, "relais-deux-sauts", sid)
    assert _points(body) == {"mode": True, "sauts": False, "lien": False}
    assert body["score"] == 10 and body["max_score"] == 30
    _cli(api, sid, "relais-1", "conf t", "int mesh 0", "max-hops 2", "end")
    _, body = _submit(api, "relais-deux-sauts", sid)
    assert body["score"] == 20


@pytest.fixture()
def run_frontiere(api):
    d = _scenario(count=120, messages=4)
    d.pop("gateway")
    d["gateways"] = [{"name": "frontiere", "x_m": 0, "y_m": 0, "antenna_gain_dbi": 2.15},
                     {"name": "relais-1", "x_m": 2500, "y_m": 0, "antenna_gain_dbi": 2.15}]
    status, created = api.call("POST", "/api/v1/runs", {"scenario": d})
    assert status == 202
    assert _wait_done(api, created["run_id"])["state"] == "done"
    return created["run_id"]


def test_reception_criterion_needs_a_bound_simulation(api, run_frontiere):
    _, out = _session(api, exercise="us915-sous-bande")
    sid = out["session_id"]
    _cli(api, sid, "frontiere", "en", "conf t", "int lora 0", "region US915", "sub-band 2", "end")
    _, body = _submit(api, "us915-sous-bande", sid)
    assert _points(body)["reception"] is False and body["score"] == 20
    status, _ = api.call("POST", f"/api/v1/sessions/{sid}/simulation",
                         {"run_id": run_frontiere, "links": [
                             {"node_id": "frontiere", "gateway": "frontiere"}]})
    assert status == 200
    _, body = _submit(api, "us915-sous-bande", sid)
    assert _points(body)["reception"] is True and body["score"] == 30


def test_submit_refuses_a_session_of_another_exercise_or_no_exercise(api):
    _, out = _session(api, exercise="eu868-passerelle")
    status, body = _submit(api, "us915-sous-bande", out["session_id"])
    assert status == 422 and body["field"] == "session_id"
    _, plain = _session(api)
    status, body = _submit(api, "eu868-passerelle", plain["session_id"])
    assert status == 422 and body["field"] == "session_id"


def test_submit_unknown_exercise_or_foreign_session_is_not_found(api):
    _, out = _session(api, exercise="eu868-passerelle")
    status, _ = _submit(api, "inconnu-000", out["session_id"])
    assert status == 404
    status, _ = _submit(api, "eu868-passerelle", out["session_id"], token=api.bob)
    assert status == 404


def test_submit_carries_only_the_session_id(api):
    """Le client ne peut pas envoyer de score ni de critère : le contrat le refuse."""
    _, out = _session(api, exercise="eu868-passerelle")
    for extra in ({"score": 20}, {"criteria": []}, {"hints_used": 0}):
        status, _ = _submit(api, "eu868-passerelle", out["session_id"], extra=extra)
        assert status == 422


# --- Liens et latence observés dans un vrai run mesh ------------------------------------------

from test_api_server import _mesh_scenario  # noqa: E402


@pytest.fixture()
def mesh_run(api):
    status, created = api.call("POST", "/api/v1/runs", {"scenario": _mesh_scenario(count=200)})
    assert status == 202
    assert _wait_done(api, created["run_id"])["state"] == "done"
    return created["run_id"]


def _link(api, sid, run_id, links):
    status, body = api.call("POST", f"/api/v1/sessions/{sid}/simulation",
                            {"run_id": run_id, "links": links})
    assert status == 200, body
    return body


def test_relay_exercise_reaches_full_score_with_an_observed_mesh_link(api, mesh_run):
    _, out = _session(api, exercise="relais-deux-sauts")
    sid = out["session_id"]
    _cli(api, sid, "relais-1", "en", "conf t", "int mesh 0", "mode relay", "max-hops 2", "end")
    _link(api, sid, mesh_run, [{"node_id": "frontiere", "gateway": "frontiere"},
                               {"node_id": "relais-1", "gateway": "relais"}])
    _, body = _submit(api, "relais-deux-sauts", sid)
    assert _points(body)["lien"] is True and body["score"] == 30


def test_mesh_link_is_refused_when_the_relay_is_not_linked(api, mesh_run):
    _, out = _session(api, exercise="relais-deux-sauts")
    sid = out["session_id"]
    _cli(api, sid, "relais-1", "en", "conf t", "int mesh 0", "mode relay", "max-hops 2", "end")
    _link(api, sid, mesh_run, [{"node_id": "frontiere", "gateway": "frontiere"}])
    _, body = _submit(api, "relais-deux-sauts", sid)
    assert _points(body)["lien"] is False


def test_latency_exercise_reads_the_border_p95_of_the_real_run(api, mesh_run):
    _, out = _session(api, exercise="latence-frontiere")
    sid = out["session_id"]
    _, body = _submit(api, "latence-frontiere", sid)
    assert body["score"] == 0                      # rien n'est lié : aucune mesure
    _link(api, sid, mesh_run, [{"node_id": "frontiere", "gateway": "frontiere"}])
    _, body = _submit(api, "latence-frontiere", sid)
    assert _points(body) == {"latence": True} and body["score"] == 20


# --- Indices et pénalités --------------------------------------------------------------------

def test_hints_are_revealed_one_at_a_time_and_cost_points(api):
    _, out = _session(api, exercise="eu868-passerelle")
    sid = out["session_id"]
    status, body = api.call("POST", f"/api/v1/sessions/{sid}/hints",
                            {"exercise_id": "eu868-passerelle"})
    assert status == 200 and body["number"] == 1 and body["penalty"] == 2
    assert body["text"].startswith("Le plan régional")
    _cli(api, sid, "frontiere", "en", "conf t", "int lora 0", "region EU868", "end")
    _, res = _submit(api, "eu868-passerelle", sid)
    assert res["hints_used"] == 1 and res["score"] == 10 - 2
    status, body = api.call("POST", f"/api/v1/sessions/{sid}/hints",
                            {"exercise_id": "eu868-passerelle"})
    assert status == 200 and body["number"] == 2
    status, body = api.call("POST", f"/api/v1/sessions/{sid}/hints",
                            {"exercise_id": "eu868-passerelle"})
    assert status == 409                           # plus d'indice
    _cli(api, sid, "frontiere", "conf t", "lorawan server 10.0.0.5 up-port 1700 down-port 1701",
         "end")
    _, res = _submit(api, "eu868-passerelle", sid)
    assert res["hints_used"] == 2 and res["score"] == 20 - 4


def test_penalty_never_takes_the_score_below_zero(api):
    _, out = _session(api, exercise="eu868-passerelle")
    sid = out["session_id"]
    for _ in range(2):
        api.call("POST", f"/api/v1/sessions/{sid}/hints", {"exercise_id": "eu868-passerelle"})
    _, res = _submit(api, "eu868-passerelle", sid)
    assert res["score"] == 0 and res["hints_used"] == 2


def test_hint_refusals(api):
    _, out = _session(api, exercise="eu868-passerelle")
    sid = out["session_id"]
    status, body = api.call("POST", f"/api/v1/sessions/{sid}/hints",
                            {"exercise_id": "us915-sous-bande"})
    assert status == 422 and body["field"] == "exercise_id"
    status, _ = api.call("POST", f"/api/v1/sessions/{sid}/hints",
                         {"exercise_id": "inconnu-000"})
    assert status == 404
    status, _ = api.call("POST", f"/api/v1/sessions/{sid}/hints",
                         {"exercise_id": "eu868-passerelle"}, token=api.bob)
    assert status == 404


# --- Journal des tentatives ------------------------------------------------------------------

def test_attempts_log_results_only_and_never_commands(api):
    _, out = _session(api, exercise="eu868-passerelle")
    sid = out["session_id"]
    _cli(api, sid, "frontiere", "en", "conf t", "int lora 0", "region EU868", "end")
    _submit(api, "eu868-passerelle", sid)
    _cli(api, sid, "frontiere", "conf t", "lorawan server 10.0.0.5 up-port 1700 down-port 1701", "end")
    _submit(api, "eu868-passerelle", sid)
    status, body = api.call("GET", f"/api/v1/sessions/{sid}/attempts")
    assert status == 200
    items = body["items"]
    assert [i["number"] for i in items] == [1, 2]
    assert items[0]["passed"] == ["region"] and items[1]["passed"] == ["region", "serveur"]
    assert items[1]["score"] == 20 and items[1]["max_score"] == 20
    for item in items:
        assert set(item) == {"number", "at", "exercise_id", "score", "max_score",
                             "hints_used", "passed"}
    text = json.dumps(body, ensure_ascii=False)
    assert "region EU868" not in text and "10.0.0.5" not in text and "conf t" not in text


def test_attempts_are_private_to_their_session_and_owner(api):
    _, out = _session(api, exercise="eu868-passerelle")
    sid = out["session_id"]
    _submit(api, "eu868-passerelle", sid)
    status, _ = api.call("GET", f"/api/v1/sessions/{sid}/attempts", token=api.bob)
    assert status == 404
    _, out2 = _session(api, exercise="eu868-passerelle")
    _, body = api.call("GET", f"/api/v1/sessions/{out2['session_id']}/attempts")
    assert body["items"] == []


def test_run_summary_publishes_latency_and_observed_mesh_links(api, mesh_run):
    from lsim.api_contract import RunSummary
    _, summary = api.call("GET", f"/api/v1/runs/{mesh_run}/summary")
    RunSummary.model_validate(summary)
    gw = {g["name"]: g for g in summary["gateways"]}
    assert gw["frontiere"]["latency_samples"] > 0
    assert gw["frontiere"]["latency_p95_ms"] >= gw["frontiere"]["latency_p50_ms"] > 0
    assert gw["frontiere"]["mesh_inbound"] == [
        {"from_gateway": "relais", "delivered": gw["frontiere"]["mesh_inbound"][0]["delivered"]}]
    assert "mesh_inbound" not in gw["ip"] and gw["relais"]["latency_samples"] == 0
