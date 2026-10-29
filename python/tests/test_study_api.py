"""Routes du panneau d'étude : sessions, CLI par équipement, topologie, liaison à une simulation.

Serveur réel en fil (fixtures de `test_api_server`). Les réponses sont validées contre le contrat
du panneau (`lsim.study_contract`). Pas d'exercices dans cette version : leurs routes manquent.
"""

import re

import pytest

from lsim import study_session
from lsim.study_contract import (
    CliResponse, SessionOut, SessionTopology, SimulationBound,
)
from lsim.study_session import StudyService
from test_api_server import _make_api, _scenario, _wait_done

NODES = [
    {"id": "frontiere", "kind": "border", "name": "Frontière", "x_m": 0, "y_m": 0},
    {"id": "relais-1", "kind": "relay", "name": "Relais 1", "x_m": 1200, "y_m": 0},
    {"id": "capteur-1", "kind": "sensor", "name": "Capteur", "x_m": 300, "y_m": 0},
]


@pytest.fixture()
def api(tmp_path):
    with _make_api(tmp_path) as a:
        yield a


def _session(api, nodes=NODES, token=None):
    status, body = api.call("POST", "/api/v1/sessions", {"nodes": nodes}, token=token or api.alice)
    assert status == 201, body
    SessionOut.model_validate(body)
    return body["session_id"]


def _cli(api, sid, node, command, token=None):
    status, body = api.call("POST", f"/api/v1/sessions/{sid}/cli",
                            {"node_id": node, "command": command}, token=token or api.alice)
    if status == 200:
        CliResponse.model_validate(body)
    return status, body


def _run_lines(api, sid, node, lines):
    last = None
    for line in lines:
        status, last = _cli(api, sid, node, line)
        assert status == 200, last
    return last


# --- Création, topologie, propriétaire -------------------------------------------------------

def test_create_session_returns_an_opaque_id(api):
    sid = _session(api)
    assert re.fullmatch(r"^[A-Za-z0-9_-]{8,64}$", sid)


def test_exercise_id_is_refused_until_the_catalogue_exists(api):
    status, body = api.call("POST", "/api/v1/sessions", {"exercise_id": "ex-un-deux"})
    assert status == 422 and body["field"] == "exercise_id"


def test_duplicate_node_ids_are_refused(api):
    status, body = api.call("POST", "/api/v1/sessions", {"nodes": NODES + [NODES[0]]})
    assert status == 422 and body["field"] == "nodes"


def test_topology_lists_nodes_and_default_states(api):
    sid = _session(api)
    status, body = api.call("GET", f"/api/v1/sessions/{sid}/topology")
    assert status == 200
    topo = SessionTopology.model_validate(body)
    assert [n.id for n in topo.nodes] == ["frontiere", "relais-1", "capteur-1"]
    assert all(not s.configured and s.region is None and s.keys is None for s in topo.states)


def test_cli_changes_are_visible_in_topology(api):
    sid = _session(api)
    _run_lines(api, sid, "relais-1", ["en", "conf t", "int lora 0", "region EU868", "end"])
    _, body = api.call("GET", f"/api/v1/sessions/{sid}/topology")
    state = {s["node_id"]: s for s in body["states"]}["relais-1"]
    assert state["configured"] is True and state["region"] == "EU868"
    assert state["hostname"] == "relais-1"
    assert {s["node_id"]: s for s in body["states"]}["frontiere"]["configured"] is False


def test_modes_persist_between_requests(api):
    sid = _session(api)
    assert _cli(api, sid, "frontiere", "en")[1]["mode"] == "privileged"
    assert _cli(api, sid, "frontiere", "show version")[1]["mode"] == "privileged"


def test_cli_errors_are_reported_with_a_column_and_change_nothing(api):
    sid = _session(api)
    _run_lines(api, sid, "relais-1", ["en", "conf t", "int mesh 0"])
    status, body = _cli(api, sid, "relais-1", "max-hops 99")
    assert status == 200
    assert body["error"]["column"] == len("max-hops ") and body["mode"] == "config-if"
    assert body["prompt"] == "relais-1(config-if)#"


def test_running_config_contains_no_secret_and_no_simulation_result(api):
    sid = _session(api)
    _run_lines(api, sid, "relais-1", ["en"])
    _, body = _cli(api, sid, "relais-1", "show running-config")
    assert "key" not in body["output"].lower()


def test_cli_refuses_sensors_unknown_nodes_and_multi_line_commands(api):
    sid = _session(api)
    status, body = _cli(api, sid, "capteur-1", "en")
    assert status == 422 and body["field"] == "node_id"
    status, _ = _cli(api, sid, "absent", "en")
    assert status == 404
    status, body = api.call("POST", f"/api/v1/sessions/{sid}/cli",
                            {"node_id": "relais-1", "command": "en\nshow version"})
    assert status == 422


def test_other_owner_and_missing_session_are_unknown_not_forbidden(api):
    sid = _session(api)
    for method, path, body in [
        ("GET", f"/api/v1/sessions/{sid}/topology", None),
        ("POST", f"/api/v1/sessions/{sid}/cli", {"node_id": "relais-1", "command": "en"}),
    ]:
        status, _ = api.call(method, path, body, token=api.bob)
        assert status == 404
    status, _ = api.call("GET", "/api/v1/sessions/inconnue-000000/topology")
    assert status == 404


def test_session_routes_need_a_token(api):
    status, _ = api.call("POST", "/api/v1/sessions", {}, token=None)
    assert status == 401


# --- Liaison à une simulation réelle ---------------------------------------------------------

@pytest.fixture()
def multi_run(api):
    """Run terminé à deux passerelles nommées comme les équipements de la session."""
    d = _scenario(count=120, messages=4)
    d.pop("gateway")
    d["gateways"] = [{"name": "frontiere", "x_m": 0, "y_m": 0, "antenna_gain_dbi": 2.15},
                     {"name": "relais-1", "x_m": 2500, "y_m": 0, "antenna_gain_dbi": 2.15}]
    status, created = api.call("POST", "/api/v1/runs", {"scenario": d})
    assert status == 202
    assert _wait_done(api, created["run_id"])["state"] == "done"
    _, summary = api.call("GET", f"/api/v1/runs/{created['run_id']}/summary")
    return created["run_id"], summary


def _link(api, sid, run_id, links, token=None):
    return api.call("POST", f"/api/v1/sessions/{sid}/simulation",
                    {"run_id": run_id, "links": links}, token=token or api.alice)


FRONT = {"node_id": "frontiere", "gateway": "frontiere"}
RELAY = {"node_id": "relais-1", "gateway": "relais-1"}


def test_binding_links_only_the_explicit_associations(api, multi_run):
    run_id, _ = multi_run
    sid = _session(api)
    status, body = _link(api, sid, run_id, [FRONT, RELAY])
    assert status == 200
    bound = SimulationBound.model_validate(body)
    assert bound.linked == ["frontiere", "relais-1"]
    assert bound.unlinked == ["capteur-1"]


def test_a_name_match_without_an_explicit_link_links_nothing(api, multi_run):
    run_id, _ = multi_run
    sid = _session(api)
    _, body = _link(api, sid, run_id, [FRONT])        # relais-1 porte le nom d'une passerelle
    assert body["linked"] == ["frontiere"] and "relais-1" in body["unlinked"]
    _, body = _link(api, sid, run_id, [])              # sans association : tout est délié
    assert body["linked"] == []


def test_invalid_links_are_refused_and_change_nothing(api, multi_run):
    run_id, _ = multi_run
    sid = _session(api)
    _link(api, sid, run_id, [FRONT])
    cases = [
        [FRONT, {"node_id": "relais-1", "gateway": "inconnue"}],        # passerelle absente
        [FRONT, {"node_id": "absent", "gateway": "relais-1"}],          # équipement inconnu
        [FRONT, {"node_id": "capteur-1", "gateway": "relais-1"}],       # sans passerelle
        [FRONT, {"node_id": "relais-1", "gateway": "frontiere"}],       # passerelle deux fois
        [FRONT, {"node_id": "frontiere", "gateway": "relais-1"}],       # équipement deux fois
    ]
    for links in cases:
        status, body = _link(api, sid, run_id, links)
        assert status == 422 and body["field"] == "links", links
    # La liaison valide d'avant les refus est intacte : aucune liaison partielle, aucune perte.
    _run_lines(api, sid, "frontiere", ["en"])
    _, body = _cli(api, sid, "frontiere", "show lorawan counters")
    assert "received" in body["output"]


def test_show_counters_reads_the_real_run_report(api, multi_run):
    run_id, summary = multi_run
    sid = _session(api)
    _link(api, sid, run_id, [FRONT])
    report = {g["name"]: g for g in summary["gateways"]}["frontiere"]
    _run_lines(api, sid, "frontiere", ["en"])
    _, body = _cli(api, sid, "frontiere", "show lorawan counters")
    assert body.get("error") is None
    assert f"received {report['received']}\n" in body["output"]
    assert f"lost collision {report['lost_collision']}\n" in body["output"]


def test_show_mesh_counters_without_mesh_says_no_result(api, multi_run):
    run_id, _ = multi_run
    sid = _session(api)
    _link(api, sid, run_id, [FRONT])
    _run_lines(api, sid, "frontiere", ["en"])
    _, body = _cli(api, sid, "frontiere", "show mesh counters")
    assert "Aucun résultat" in body["output"]


def test_counters_are_absent_before_binding(api):
    sid = _session(api)
    _run_lines(api, sid, "frontiere", ["en"])
    _, body = _cli(api, sid, "frontiere", "show lorawan counters")
    assert "Aucun résultat" in body["output"]


def test_single_gateway_run_has_no_gateway_name_to_link(api):
    d = _scenario(count=20, messages=2)
    status, created = api.call("POST", "/api/v1/runs", {"scenario": d})
    assert status == 202
    assert _wait_done(api, created["run_id"])["state"] == "done"
    sid = _session(api)
    _, body = _link(api, sid, created["run_id"], [])
    assert body["linked"] == [] and body["unlinked"] == ["frontiere", "relais-1", "capteur-1"]
    status, body = _link(api, sid, created["run_id"], [FRONT])
    assert status == 422 and body["field"] == "links"


def test_binding_an_unknown_or_foreign_run_is_not_found(api, multi_run):
    run_id, _ = multi_run
    sid = _session(api)
    status, _ = _link(api, sid, "absent-run-01", [])
    assert status == 404
    status, _ = _link(api, sid, run_id, [], token=api.bob)
    assert status == 404


def test_exit_at_user_level_restarts_the_console_in_user_mode(api):
    sid = _session(api)
    _, body = _cli(api, sid, "frontiere", "exit")          # depuis le mode utilisateur
    assert body["mode"] == "user" and body["prompt"] == "frontiere>"
    assert "retour au mode utilisateur" in body["output"]
    _run_lines(api, sid, "frontiere", ["en"])               # « exit » : privilégié -> utilisateur
    _, body = _cli(api, sid, "frontiere", "exit")
    assert body["mode"] == "user" and "retour" not in body.get("output", "")


# --- Limites et expiration (service seul, horloge simulée) -----------------------------------

class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_sessions_are_capped_per_owner_and_in_total():
    svc = StudyService(clock=_Clock())
    from lsim.study_contract import SessionCreate
    for _ in range(study_session.MAX_SESSIONS_PER_OWNER):
        svc.create("alice", SessionCreate())
    with pytest.raises(study_session.StudyError) as exc:
        svc.create("alice", SessionCreate())
    assert exc.value.status == 429
    svc.create("bob", SessionCreate())  # un autre compte n'est pas bloqué par alice


def test_idle_sessions_expire_and_are_unknown_afterwards():
    clock = _Clock()
    svc = StudyService(clock=clock)
    from lsim.study_contract import SessionCreate
    sid = svc.create("alice", SessionCreate()).session_id
    clock.now += study_session.SESSION_TTL_S - 1
    svc.topology("alice", sid)                       # l'activité prolonge la vie de la session
    clock.now += study_session.SESSION_TTL_S - 1
    svc.topology("alice", sid)
    clock.now += study_session.SESSION_TTL_S + 1
    with pytest.raises(study_session.StudyError) as exc:
        svc.topology("alice", sid)
    assert exc.value.status == 404


def _race(attempts, call):
    """Lance `attempts` appels simultanés (barrière) ; `call(i)` reçoit l'indice de tentative."""
    import threading
    barrier = threading.Barrier(attempts)
    outcomes = []
    lock = threading.Lock()

    def worker(i):
        barrier.wait()
        try:
            call(i)
            status = "ok"
        except study_session.StudyError as exc:
            status = exc.status
        with lock:
            outcomes.append(status)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(attempts)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return outcomes


def test_concurrent_creates_never_exceed_the_per_owner_cap():
    from lsim.study_contract import SessionCreate
    svc = StudyService()
    outcomes = _race(3 * study_session.MAX_SESSIONS_PER_OWNER,
                     lambda _i: svc.create("alice", SessionCreate()))
    assert outcomes.count("ok") == study_session.MAX_SESSIONS_PER_OWNER
    assert outcomes.count(429) == 2 * study_session.MAX_SESSIONS_PER_OWNER


def test_concurrent_creates_never_exceed_the_total_cap(monkeypatch):
    from lsim.study_contract import SessionCreate
    monkeypatch.setattr(study_session, "MAX_SESSIONS_TOTAL", 5)
    svc = StudyService()
    outcomes = _race(12, lambda i: svc.create(f"owner{i}", SessionCreate()))
    assert outcomes.count("ok") == 5


def test_empty_session_creation_is_allowed_and_nodes_are_per_session(api):
    status, first = api.call("POST", "/api/v1/sessions", {})
    assert status == 201
    status, second = api.call("POST", "/api/v1/sessions", {"nodes": NODES})
    assert status == 201
    _, topo = api.call("GET", f"/api/v1/sessions/{first['session_id']}/topology")
    assert topo["nodes"] == []
    _, topo = api.call("GET", f"/api/v1/sessions/{second['session_id']}/topology")
    assert len(topo["nodes"]) == 3
