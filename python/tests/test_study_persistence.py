"""Persistance des sessions et du journal : les sessions survivent au redémarrage, l'expiration
s'applique à l'horloge réelle, le journal reste borné, et un run lié avant redémarrage se relie
encore."""

import pytest

from lsim import study_session
from lsim.study_contract import CliRequest, Node, SessionCreate, SimulationBind
from lsim.study_session import StudyError, StudyService
from lsim.study_store import StudyStore
from test_api_server import _make_api


class Clock:
    def __init__(self, now=1_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


def _service(path, clock):
    return StudyService(clock=clock, store=StudyStore(str(path)))


def _configure_border(svc, owner, sid):
    for line in ("enable", "configure terminal", "interface lora 0", "region EU868", "exit",
                 "lorawan server 10.0.0.5 up-port 1700 down-port 1701", "end"):
        out = svc.cli(owner, sid, CliRequest(node_id="frontiere", command=line))
        assert out.error is None, (line, out)


def _border_session(svc, owner="alice"):
    node = Node(id="frontiere", kind="border", name="Frontière", x_m=0, y_m=0)
    return svc.create(owner, SessionCreate(nodes=[node])).session_id


def test_sessions_and_their_configuration_survive_a_restart(tmp_path):
    clock = Clock()
    path = tmp_path / "runs.sqlite"
    svc = _service(path, clock)
    sid = svc.create("alice", SessionCreate(exercise_id="eu868-passerelle")).session_id
    _configure_border(svc, "alice", sid)
    first_hint = svc.hint("alice", sid, "eu868-passerelle")
    first = svc.submit("alice", "eu868-passerelle", sid)
    before = svc.topology("alice", sid).model_dump()
    svc.close()

    restarted = _service(path, clock)
    assert restarted.topology("alice", sid).model_dump() == before
    attempts = restarted.attempts("alice", sid).items
    assert [(a.number, a.score, a.hints_used) for a in attempts] == [(1, first.score, 1)]
    assert first.score == 18                                # 20 points moins un indice
    second_hint = restarted.hint("alice", sid, "eu868-passerelle")
    assert (first_hint.number, second_hint.number) == (1, 2)
    assert restarted.submit("alice", "eu868-passerelle", sid).hints_used == 2
    assert [a.number for a in restarted.attempts("alice", sid).items] == [1, 2]


def test_the_journal_is_bounded_in_storage_and_after_a_restart(tmp_path):
    clock = Clock()
    path = tmp_path / "runs.sqlite"
    svc = _service(path, clock)
    sid = svc.create("alice", SessionCreate(exercise_id="eu868-passerelle")).session_id
    for _ in range(study_session.MAX_ATTEMPTS + 5):
        svc.submit("alice", "eu868-passerelle", sid)
    svc.close()
    restarted = _service(path, clock)
    numbers = [a.number for a in restarted.attempts("alice", sid).items]
    assert numbers == list(range(6, study_session.MAX_ATTEMPTS + 6))
    restarted.close()


def test_a_session_idle_across_a_restart_expires_at_the_real_deadline(tmp_path):
    clock = Clock()
    path = tmp_path / "runs.sqlite"
    svc = _service(path, clock)
    sid = _border_session(svc)
    svc.close()
    clock.now += study_session.SESSION_TTL_S + 1
    restarted = _service(path, clock)
    with pytest.raises(StudyError) as exc:
        restarted.topology("alice", sid)
    assert exc.value.status == 404
    assert StudyStore(str(path)).load_sessions() == []


def test_reading_a_session_keeps_it_alive_across_a_restart(tmp_path):
    """Une lecture est écrite (au plus une fois par minute) : après redémarrage, l'expiration part
    de la dernière lecture, non de la création."""
    clock = Clock()
    path = tmp_path / "runs.sqlite"
    svc = _service(path, clock)
    sid = _border_session(svc)
    clock.now += study_session.SESSION_TTL_S - 100       # lecture à TTL - 100 s
    svc.topology("alice", sid)
    svc.close()
    clock.now += study_session.SESSION_TTL_S - 50        # redémarrage : TTL - 50 s d'inactivité
    restarted = _service(path, clock)
    assert restarted.topology("alice", sid).session_id == sid
    restarted.close()


def test_a_run_linked_before_a_restart_is_still_linked_from_its_compilation(tmp_path):
    clock = Clock()
    path = tmp_path / "runs.sqlite"
    svc = _service(path, clock)
    node = Node(id="relais-1", kind="relay", name="Relais", x_m=0, y_m=0)
    sid = svc.create("alice", SessionCreate(nodes=[node])).session_id
    svc.record_simulation("alice", sid, "runabcdefgh", [{"node_id": "relais-1", "gateway": "relais-1"}])
    svc.close()
    restarted = _service(path, clock)
    report = {"name": "relais-1", "received": 3, "lost_sensitivity": 0, "lost_collision": 0,
              "lost_gateway_busy": 0, "audible_frames": 3, "busy_ns": 1, "observation_ns": 2,
              "peak_concurrent": 1, "mesh_inbound": []}
    bound = restarted.bind_run("alice", sid, SimulationBind(run_id="runabcdefgh"),
                               {"gateways": [report]})
    assert bound.linked == ["relais-1"] and bound.unlinked == []
    restarted.close()


def test_the_api_keeps_sessions_across_a_server_restart(tmp_path):
    db = str(tmp_path / "runs.sqlite")
    with _make_api(tmp_path, runs_db=db) as api:
        status, out = api.call("POST", "/api/v1/sessions", {"nodes": [
            {"id": "frontiere", "kind": "border", "name": "Frontière", "x_m": 0, "y_m": 0}]})
        assert status == 201
        sid = out["session_id"]
        status, _ = api.call("POST", f"/api/v1/sessions/{sid}/cli",
                             {"node_id": "frontiere", "command": "enable"})
        assert status == 200
    with _make_api(tmp_path, runs_db=db) as api:
        status, out = api.call("GET", f"/api/v1/sessions/{sid}/topology")
        assert status == 200 and [n["id"] for n in out["nodes"]] == ["frontiere"]
        assert out["states"][0]["configured"] is False
        status, out = api.call("POST", f"/api/v1/sessions/{sid}/cli",
                               {"node_id": "frontiere", "command": "show version"})
        assert status == 200 and out["mode"] == "privileged"


def test_a_second_server_on_the_same_database_is_refused_until_the_first_closes(tmp_path):
    """Deux processus sur une même base divergeraient (sessions tenues en mémoire) : refusé."""
    from lsim import api_server as srv
    tokens = tmp_path / "tokens.json"
    srv.TokenStore(tokens).issue("alice")
    db = str(tmp_path / "runs.sqlite")
    first = srv.make_server("127.0.0.1", 0, tokens, runs_db=db)
    with pytest.raises(RuntimeError, match="déjà utilisée"):
        srv.make_server("127.0.0.1", 0, tokens, runs_db=db)
    first.server_close()
    first.service.close()
    first.study.close()
    second = srv.make_server("127.0.0.1", 0, tokens, runs_db=db)
    second.server_close()
    second.service.close()
    second.study.close()
