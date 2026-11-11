"""Routes du panneau d'étude : sessions, CLI par équipement, topologie, liaison à une simulation.

Serveur réel en fil (fixtures de `test_api_server`). Les réponses sont validées contre le contrat
du panneau (`lsim.study_contract`). Pas d'exercices dans cette version : leurs routes manquent.
"""

import re
from collections import Counter

import pytest

from lsim import study_session
from lsim.study_contract import (
    CliResponse, GatewaySettings, SessionOut, SessionTopology, SimulationBound,
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


def test_adr_run_binds_without_a_gateway_name_and_keeps_the_final_sf(api):
    """Un run ADR ne nomme aucune passerelle : la liaison ne doit pas échouer pour autant.

    La session y compile en forme `gateway` (singulier), seule forme que le moteur accepte avec
    un MAC actif — c'est le coût assumé de l'ADR. Refuser la liaison ferait échouer l'atelier sur
    **chaque** run ADR, y compris celui qu'il vient de lancer. Ce qu'on y gagne (le SF de fin
    par capteur) est justement ce que l'exercice note.
    """
    d = _scenario(count=3, messages=4)
    d["mac"] = {"link_adr": True}
    d["groups"][0]["region"] = "EU868"
    status, created = api.call("POST", "/api/v1/runs", {"scenario": d})
    assert status == 202
    assert _wait_done(api, created["run_id"])["state"] == "done"
    _, summary = api.call("GET", f"/api/v1/runs/{created['run_id']}/summary")
    assert not summary.get("gateways")            # voie mono-passerelle : aucun nom
    sid = _session(api)
    status, body = _link(api, sid, created["run_id"], [])
    assert status == 200, body
    assert body["linked"] == []                   # rien à lier, et ce n'est pas une erreur
    # Une liaison explicite, elle, reste stricte : le nom demandé n'existe pas dans le run.
    status, body = _link(api, sid, created["run_id"], [FRONT])
    assert status == 422 and body["field"] == "links"


def test_adr_exercise_is_graded_on_the_observed_datarate_not_the_checkbox(api):
    """La note ne bouge que si le **run** a vu le débit changer.

    Deux soumissions de la même session, à vingt puis quarante messages. Dans les deux cas la
    case ADR est cochée et le plan régional est posé : les vingt premiers points tombent. Les
    vingt derniers ne tombent que si le SF du dernier uplink est plus bas que celui du départ —
    à vingt messages la commande part mais le terminal ne l'applique pas encore.
    """
    status, created = api.call("POST", "/api/v1/sessions", {"exercise_id": "adr-debit-observe"})
    assert status == 201, created
    sid = created["session_id"]
    for cmd in ("enable", "configure terminal", "interface lora 0", "region EU868"):
        status, body = api.call("POST", f"/api/v1/sessions/{sid}/cli",
                                {"node_id": "frontiere", "command": cmd})
        assert status == 200 and not body.get("error"), body
    status, body = api.call("POST", f"/api/v1/sessions/{sid}/adr", {"adr": True})
    assert status == 200 and body["adr_possible"] is True, body

    def soumettre(messages):
        status, _ = api.call("POST", f"/api/v1/sessions/{sid}/nodes/capteur-1/sensor",
                             {"spreading_factor": 12, "messages": messages, "period_s": 60,
                              "start_spread_s": 20})
        assert status == 200
        status, started = api.call("POST", f"/api/v1/sessions/{sid}/simulate", {"seed": 7})
        assert status == 202
        assert _wait_done(api, started["run_id"])["state"] == "done"
        status, bound = api.call("POST", f"/api/v1/sessions/{sid}/simulation",
                                 {"run_id": started["run_id"]})
        assert status == 200, bound
        status, note = api.call("POST", "/api/v1/exercises/adr-debit-observe/submit",
                                {"session_id": sid})
        assert status == 200
        return {c["id"]: c["passed"] for c in note["criteria"]}, note["score"]

    # Vingt messages : la case est cochée, le serveur commande, mais le terminal n'applique pas.
    criteres, note = soumettre(20)
    assert criteres["region"] and criteres["adr"]
    assert not criteres["debit"]
    assert note == 20

    # Quarante messages : le run observe le changement, et lui seul fait la note.
    criteres, note = soumettre(40)
    assert criteres["debit"]
    assert note == 40


# --- Protocole du run : jointure OTAA et trames confirmées -------------------------------------

def _evenements(api, run_id):
    """Compte les événements d'un run terminé, toutes pages confondues."""
    vus, cursor = Counter(), 0
    while cursor is not None:
        _, page = api.call("GET", f"/api/v1/runs/{run_id}/events?limit=100&cursor={cursor}")
        for e in page["items"]:
            vus[e["kind"]] += 1
        cursor = page["next_cursor"]
    return vus


def _lancer(api, sid, seed=7):
    status, started = api.call("POST", f"/api/v1/sessions/{sid}/simulate", {"seed": seed})
    assert status == 202
    assert _wait_done(api, started["run_id"])["state"] == "done"
    return started["run_id"]


def test_join_and_confirmed_are_reflected_in_the_run(api):
    """Les deux réglages atteignent le run, et la trace le montre.

    Sans eux : six messages par capteur, tous en uplink. Avec eux : le premier message de
    chaque capteur devient une demande de jointure, et chaque uplink reçu appelle un ACK.
    """
    sid = _session_une_passerelle(api, capteurs=("c0", "c1", "c2"))
    for c in ("c0", "c1", "c2"):
        status, _ = api.call("POST", f"/api/v1/sessions/{sid}/nodes/{c}/sensor",
                             {"messages": 6, "period_s": 300, "start_spread_s": 20})
        assert status == 200
    _, topo = api.call("POST", f"/api/v1/sessions/{sid}/protocol", {"join": False,
                                                                  "confirmed": False})
    assert topo["join"] is False and topo["confirmed"] is False
    avant = _evenements(api, _lancer(api, sid))
    assert dict(avant) == {"uplink": 18}, dict(avant)

    _, topo = api.call("POST", f"/api/v1/sessions/{sid}/protocol", {"join": True,
                                                                  "confirmed": True})
    assert topo["join"] is True and topo["join_possible"] is True
    apres = _evenements(api, _lancer(api, sid))
    # Trois jointures : un join-request de plus que de capteurs, un terminal ayant dû
    # recommencer. Les données tombent de 18 à 15 : le premier message est la jointure.
    assert apres["join_request"] >= 3 and apres["join_accept"] >= 3, dict(apres)
    assert apres["uplink"] == 15, dict(apres)
    assert apres["ack"] > 0, dict(apres)


def test_join_is_refused_when_adr_is_on_and_says_why(api):
    """La jointure et l'ADR s'excluent (le moteur lève). Le souhait reste, la raison est dite.

    Sans quoi le run échouerait sur une exception que rien n'explique : le refus du moteur
    doit se lire **avant** le lancement.
    """
    sid = _session_une_passerelle(api, capteurs=("c0", "c1"))
    for c in ("c0", "c1"):
        status, _ = api.call("POST", f"/api/v1/sessions/{sid}/nodes/{c}/sensor",
                             {"messages": 6, "period_s": 300, "start_spread_s": 20})
        assert status == 200
    _, topo = api.call("POST", f"/api/v1/sessions/{sid}/protocol", {"join": True,
                                                                  "confirmed": False})
    assert topo["join_possible"] is True and topo["join_raison"] == ""
    _, topo = api.call("POST", f"/api/v1/sessions/{sid}/adr", {"adr": True})
    assert topo["adr_possible"] is True, topo
    # Le souhait est gardé, mais il n'est plus simulable, et c'est dit.
    assert topo["join"] is True
    assert topo["join_possible"] is False
    assert "ADR" in topo["join_raison"], topo["join_raison"]
    # Et le run part quand même, sans jointure : ce n'est pas une erreur de l'utilisateur.
    vus = _evenements(api, _lancer(api, sid))
    assert "join_request" not in vus, dict(vus)
    assert vus["uplink"] == 12, dict(vus)


def test_confirmed_uplinks_cost_is_visible_in_the_device_rows(api):
    """Une trame confirmée se paie : le capteur ouvre une fenêtre d'écoute pour l'ACK.

    Mesuré, pas supposé : le courant moyen monte parce que la réception est comptée. Dire
    « les trames confirmées sont plus sûres » sans montrer ce qu'elles coûtent serait
    présenter un avantage sans son prix.
    """
    sid = _session_une_passerelle(api, capteurs=("c0", "c1", "c2"))
    for c in ("c0", "c1", "c2"):
        status, _ = api.call("POST", f"/api/v1/sessions/{sid}/nodes/{c}/sensor",
                             {"messages": 6, "period_s": 300, "start_spread_s": 20})
        assert status == 200

    def courant(confirme):
        _, topo = api.call("POST", f"/api/v1/sessions/{sid}/protocol",
                           {"join": False, "confirmed": confirme})
        assert topo["confirmed"] is confirme
        run_id = _lancer(api, sid)
        _, page = api.call("GET", f"/api/v1/runs/{run_id}/devices")
        rows = page["items"]
        return sum(r["average_current_ua"] for r in rows) / len(rows)

    sans = courant(False)
    avec = courant(True)
    assert avec > sans, f"courant sans {sans} / avec {avec} : le coût devrait se voir"


def test_join_exercise_is_graded_on_the_observed_joins(api):
    """Une flotte qui joint au même instant n'émet rien : la note le constate, puis le voit cesser.

    Deux soumissions de la même session. La première, départs simultanés : les join-request se
    collisionnent, aucune jointure n'aboutit et **aucune donnée** ne sort. La seconde, après
    étalement des départs : quatre jointures acceptées, dix-neuf uplinks de données.

    Le point n'est pas de cocher une case : la jointure est activée dans les deux cas. C'est le
    run qui fait la note.
    """
    status, created = api.call("POST", "/api/v1/sessions", {"exercise_id": "join-flotte-etalee"})
    assert status == 201, created
    sid = created["session_id"]
    for cmd in ("enable", "configure terminal", "interface lora 0", "region EU868"):
        status, body = api.call("POST", f"/api/v1/sessions/{sid}/cli",
                                {"node_id": "frontiere", "command": cmd})
        assert status == 200 and not body.get("error"), body
    status, topo = api.call("POST", f"/api/v1/sessions/{sid}/protocol",
                            {"join": True, "confirmed": False})
    assert status == 200 and topo["join_possible"] is True, topo

    def soumettre(spread):
        for c in ("c0", "c1", "c2", "c3"):
            status, _ = api.call("POST", f"/api/v1/sessions/{sid}/nodes/{c}/sensor",
                                 {"messages": 6, "period_s": 300, "start_spread_s": spread})
            assert status == 200
        run_id = _lancer(api, sid)
        status, bound = api.call("POST", f"/api/v1/sessions/{sid}/simulation",
                                 {"run_id": run_id})
        assert status == 200, bound
        _, summary = api.call("GET", f"/api/v1/runs/{run_id}/summary")
        status, note = api.call("POST", "/api/v1/exercises/join-flotte-etalee/submit",
                                {"session_id": sid})
        assert status == 200
        return summary["event_kinds"], {c["id"]: c["passed"] for c in note["criteria"]}, \
            note["score"]

    # Départs simultanés : des dizaines de demandes, aucune acceptation, aucune donnée.
    natures, criteres, note = soumettre(0)
    assert natures.get("join_accept", 0) == 0, natures
    assert natures.get("uplink", 0) == 0, natures
    assert criteres["join"] is True
    assert criteres["acceptees"] is False and criteres["donnees"] is False
    assert note == 10

    # Départs étalés : la flotte joint, et les données sortent.
    natures, criteres, note = soumettre(10)
    assert natures.get("join_accept", 0) >= 4, natures
    assert natures.get("uplink", 0) >= 18, natures
    assert criteres["acceptees"] is True and criteres["donnees"] is True
    assert note == 40


def test_summary_counts_event_kinds_exactly(api):
    """`event_kinds` est compté à la fin du run, donc exact — pas borné par une relecture.

    Les événements sont stockés en JSON sans colonne de nature : les recompter à la demande
    obligerait à relire les corps et donc à borner. Un compte borné noterait un exercice sur
    un run partiellement lu sans le dire.
    """
    sid = _session_une_passerelle(api, capteurs=("c0", "c1"))
    for c in ("c0", "c1"):
        api.call("POST", f"/api/v1/sessions/{sid}/nodes/{c}/sensor",
                 {"messages": 5, "period_s": 300, "start_spread_s": 20})
    api.call("POST", f"/api/v1/sessions/{sid}/protocol", {"join": True, "confirmed": True})
    run_id = _lancer(api, sid)
    _, summary = api.call("GET", f"/api/v1/runs/{run_id}/summary")
    natures = summary["event_kinds"]
    events = _evenements(api, run_id)
    # Le compte du résumé égale le parcours effectif des événements servis.
    for kind, n in natures.items():
        assert n == events[kind], f"{kind} : résumé {n} vs parcours {events[kind]}"
    assert set(natures) == set(events), (sorted(natures), sorted(events))


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


# --- Réglages passerelle depuis l'atelier (POST /nodes/{id}/gateway) -----------------------------

def _gateway(api, sid, node, payload, token=None):
    status, body = api.call("POST", f"/api/v1/sessions/{sid}/nodes/{node}/gateway",
                            payload, token=token or api.alice)
    if status == 200:
        SessionTopology.model_validate(body)
    return status, body


def _etat(api, sid, node):
    """Réglages exposés d'un équipement, tels que la fenêtre les relit."""
    status, body = api.call("GET", f"/api/v1/sessions/{sid}/topology", token=api.alice)
    assert status == 200, body
    return next(s for s in body["states"] if s["node_id"] == node)["gateway"]


def test_reglages_passreelle_sous_bande_requires_a_sub_band_region(api):
    sid = _session(api)
    # Le refus doit être le même que celui du CLI, y compris le champ fautif.
    status, body = _gateway(api, sid, "frontiere", {"sub_band": 2})
    assert status == 422, body
    assert body["field"] == "sub_band"
    assert "US915" in body["message"]


def test_reglages_passreelle_sous_bande_sur_us915(api):
    sid = _session(api)
    _gateway(api, sid, "frontiere", {"region": "US915"})
    status, _ = _gateway(api, sid, "frontiere", {"sub_band": 2})
    assert status == 200
    assert _etat(api, sid, "frontiere")["sub_band"] == 2


def test_changer_de_region_hors_sous_bandes_efface_la_sous_bande(api):
    """Une sous-bande sur EU868 n'a pas de sens : elle ne survit pas au changement."""
    sid = _session(api)
    _gateway(api, sid, "frontiere", {"region": "US915", "sub_band": 2})
    assert _etat(api, sid, "frontiere")["sub_band"] == 2
    _gateway(api, sid, "frontiere", {"region": "EU868"})
    assert _etat(api, sid, "frontiere")["sub_band"] is None


def test_la_fenetre_et_le_cli_partagent_le_meme_etat(api):
    """Deux chemins, une seule configuration : ce que la fenêtre pose, le CLI le lit."""
    sid = _session(api)
    _gateway(api, sid, "frontiere", {"region": "US915", "tx_power_dbm": 20.0})
    # `show running-config` est une commande de mode privilégié : sans `enable`, la sortie
    # est vide et le test passerait à tort sur une configuration jamais écrite.
    body = _run_lines(api, sid, "frontiere", ["enable", "show running-config"])
    assert "US915" in body["output"]
    assert "tx-power 20" in body["output"]


def test_ce_que_le_cli_poser_la_fenetre_le_relit(api):
    """Et réciproquement : la fenêtre n'est pas un état parallèle."""
    sid = _session(api)
    # `region` et `sub-band` sont des commandes d'interface : sans `interface lora 0`,
    # elles n'existent pas et le test mesurerait autre chose que ce qu'il prétend.
    _run_lines(api, sid, "frontiere",
               ["enable", "configure terminal", "interface lora 0", "region AU915",
                "sub-band 5", "end"])
    etat = _etat(api, sid, "frontiere")
    assert etat["region"] == "AU915"
    assert etat["sub_band"] == 5


def test_relais_mode_sauts_et_bande(api):
    sid = _session(api)
    status, body = _gateway(api, sid, "relais-1",
                            {"mesh_mode": "relay", "mesh_max_hops": 2,
                             "mesh_bandwidth_khz": "1625"})
    assert status == 200, body
    etat = _etat(api, sid, "relais-1")
    assert etat["mesh_mode"] == "relay"
    assert etat["mesh_max_hops"] == 2
    assert etat["mesh_bandwidth_khz"] == "1625"


def test_les_bornes_sont_cellles_du_cli(api):
    """Un réglage refusé dans la fenêtre l'est aussi dans la console : mêmes bornes."""
    sid = _session(api)
    for payload, champ in [({"sub_band": 9}, "sub_band"),
                           ({"tx_power_dbm": 31.0}, "tx_power_dbm"),
                           ({"mesh_max_hops": 0}, "mesh_max_hops"),
                           ({"mesh_bandwidth_khz": "500"}, "mesh_bandwidth_khz"),
                           ({"mesh_mode": "pont"}, "mesh_mode")]:
        status, body = _gateway(api, sid, "frontiere", payload)
        assert status == 422, (payload, body)
        assert body["field"] == champ, (payload, body)


def test_un_champ_absent_n_efface_pas_le_reglage_en_place(api):
    """La fenêtre n'affiche pas l'antenne : elle ne doit pas pouvoir l'effacer."""
    sid = _session(api)
    _run_lines(api, sid, "frontiere",
               ["enable", "configure terminal", "interface lora 0", "antenna gain 7", "end"])
    _gateway(api, sid, "frontiere", {"region": "EU868"})
    body = _run_lines(api, sid, "frontiere", ["enable", "show running-config"])
    assert "antenna gain 7" in body["output"]


def test_reglages_passreelle_refuses_sur_un_capteur(api):
    sid = _session(api)
    status, body = _gateway(api, sid, "capteur-1", {"region": "EU868"})
    assert status == 422, body
    assert body["field"] == "node_id"


def test_equipement_inconnu_et_404(api):
    sid = _session(api)
    status, body = _gateway(api, sid, "fantome", {"region": "EU868"})
    assert status == 404, body


# --- Relief -----------------------------------------------------------------------------------
#
# Le relief etait une capacite entierement invisible : le moteur le simule, l'API le valide, et
# rien ne permettait de le choisir. Ces tests portent le trajet, pas le calcul — le calcul est
# du ressort du moteur et de `environment.py`.

def _set_terrain(api, sid, terrain_id, token=None):
    return api.call("POST", f"/api/v1/sessions/{sid}/terrain",
                    {"terrain_id": terrain_id}, token=token or api.alice)


@pytest.fixture()
def api_relief(tmp_path):
    """Serveur muni d'un catalogue : un relief `quartier`, et rien d'autre."""
    from test_api_server import _make_api
    import shutil
    from pathlib import Path
    catalog = tmp_path / "terrains"
    catalog.mkdir()
    # Un MNT minimal 2x2 : la grille doit etre complete et a pas carres (environment.py).
    (catalog / "quartier.csv").write_text(
        "x_m,y_m,z_m\n0,0,10\n0,100,12\n100,0,14\n100,100,16\n", encoding="utf-8")
    with _make_api(tmp_path, terrain_dir=catalog) as a:
        yield a


def test_le_catalogue_est_expose(api_relief):
    status, body = api_relief.call("GET", "/api/v1/terrains")
    assert status == 200, body
    assert [t["id"] for t in body["items"]] == ["quartier"]


def test_le_relief_choisi_est_relu_dans_la_topologie(api_relief):
    sid = _session(api_relief)
    status, body = _set_terrain(api_relief, sid, "quartier")
    assert status == 200, body
    assert body["terrain_id"] == "quartier"
    status, topo = api_relief.call("GET", f"/api/v1/sessions/{sid}/topology")
    assert status == 200, topo
    assert topo["terrain_id"] == "quartier"


def test_un_relief_inconnu_est_refuse(api_relief):
    sid = _session(api_relief)
    status, body = _set_terrain(api_relief, sid, "massif-inexistant")
    assert status == 422, body
    assert body["field"] == "terrain_id"
    # Refuse au moment du choix, pas au lancement du run : une erreur qui survient quand on
    # simule laisse croire que tout le reste etait pret.
    assert "catalogue" in body["message"]


def test_sans_catalogue_aucun_relief_n_est_proposable(api):
    status, body = api.call("GET", "/api/v1/terrains")
    assert status == 200, body
    assert body["items"] == []


def test_sans_catalogue_le_choix_est_refuse_sans_etre_muet(api):
    sid = _session(api)
    status, body = _set_terrain(api, sid, "quartier")
    assert status == 422, body
    assert "catalogue" in body["message"]


def test_retirer_le_relief_est_un_choix_et_non_une_erreur(api_relief):
    sid = _session(api_relief)
    _set_terrain(api_relief, sid, "quartier")
    status, body = _set_terrain(api_relief, sid, None)
    assert status == 200, body
    # `None` veut dire « pas de relief choisi », pas « terrain plat ». La distinction doit
    # rester lisible, sinon l'atelier afficherait « plat » la ou rien n'a ete decide.
    assert body["terrain_id"] is None


def test_le_relief_choisi_descend_jusquau_run(api_relief):
    # Deux equipements seulement : le jeu `NODES` du banc porte un relais, dont le scenario
    # exige une configuration mesh que ce test n'a pas a fournir.
    simple = [{"id": "frontiere", "kind": "border", "name": "Frontiere", "x_m": 0, "y_m": 0},
              {"id": "capteur-1", "kind": "sensor", "name": "Capteur", "x_m": 300, "y_m": 0}]
    sid = _session(api_relief, nodes=simple)
    _set_terrain(api_relief, sid, "quartier")
    status, body = api_relief.call("POST", f"/api/v1/sessions/{sid}/simulate", {"seed": 7})
    assert status == 202, body
    etat = _wait_done(api_relief, body["run_id"])
    # Le relief est accepte par le serveur de runs : c'est la preuve qu'il a traverse
    # la compilation et qu'il est resolvable dans le catalogue.
    assert etat["state"] == "done", etat.get("problem")


# --- Liaisons radio : la matrice des réceptions ---------------------------------------------
#
# Ces tests existent pour une raison précise : une conclusion précédente affirmait que la
# matrice par couple (capteur, passerelle) n'existait pas, faute de quoi les liaisons radio
# ne pouvaient pas être tracées. Elle était fausse, et c'est une exécution qui l'a montré,
# pas une relecture. On la fixe ici pour qu'une régression ne puisse pas la réintroduire.

def _scenario_compile(nodes, capteurs, seed=7):
    """Scénario compilé depuis une session réelle : la voie que prend le studio.

    On passe par `StudyService.compile`, pas par un scénario écrit à la main : ce sont les
    réglages d'équipement de la session qui font la topologie du run, et les inventer
    ici testerait autre chose que ce que l'atelier trace.
    """
    from lsim.api_server import _scenario_for, TerrainCatalog
    from lsim.api_contract import RunCreate
    from lsim.study_contract import Node, SensorSettings, SessionCreate

    svc = StudyService()
    sid = svc.create("alice", SessionCreate(nodes=[Node(**n) for n in nodes])).session_id
    for nid, reglages in capteurs.items():
        svc.set_sensor("alice", sid, nid, SensorSettings(**reglages))
    req = RunCreate.model_validate(svc.compile("alice", sid, seed).body)
    return _scenario_for(req.scenario, req.terrain_id, TerrainCatalog(None))


def test_rx_matrix_compte_chaque_decodeuse():
    """Trois passerelles autour d'un capteur : chacune décode, la matrice le dit trois fois.

    Les événements de trace, eux, ne citent que la **meilleure** passerelle. S'en servir pour
    tracer les liaisons dessinerait un trait là où trois passerelles ont décodé — une carte
    fausse d'un facteur trois, pas une carte imprécise.
    """
    from lsim.trace_events import build_multi_trace

    sc = _scenario_compile(
        [{"id": "gw-ouest", "kind": "border", "name": "Ouest", "x_m": -1200, "y_m": 0},
         {"id": "gw-est", "kind": "border", "name": "Est", "x_m": 1200, "y_m": 0},
         {"id": "gw-nord", "kind": "border", "name": "Nord", "x_m": 0, "y_m": 1600},
         {"id": "capt-1", "kind": "sensor", "name": "Capteur", "x_m": 0, "y_m": 0}],
        {"capt-1": {"period_s": 60.0, "messages": 5, "start_spread_s": 10.0,
                    "spreading_factor": 7}})

    mt = build_multi_trace(sc)
    assert mt.rx_matrix is not None, "la matrice doit être servie, y compris sans mesh"
    assert len(mt.rx_matrix) == 1, "un capteur, une ligne"
    ligne = mt.rx_matrix[0]
    assert len(ligne) == 3, "trois passerelles, trois colonnes"
    assert all(n >= 1 for n in ligne), (
        f"les trois passerelles encadrent le capteur : {ligne} devrait être non nul partout")
    # Et pourtant les événements ne citent qu'une seule passerelle : c'est tout le sujet.
    citees = {e.gateway_index for e in mt.events if e.gateway_index is not None}
    assert len(citees) == 1, (
        f"les événements ne portent que la meilleure passerelle ({citees}) : "
        "tracer d'après eux masquerait la macro-diversité")


def test_rx_matrix_concorde_avec_les_compteurs_par_passerelle():
    """Chaque colonne sommée retrouve `audible_frames` : la matrice ne dérive pas.

    `audible_frames` est un compteur indépendant, tenu par le cœur. Si la matrice et lui
    se contredisent, c'est que l'une des deux lectures est fausse.
    """
    from lsim.trace_events import build_multi_trace

    sc = _scenario_compile(
        [{"id": "gw-ouest", "kind": "border", "name": "Ouest", "x_m": -1200, "y_m": 0},
         {"id": "gw-est", "kind": "border", "name": "Est", "x_m": 1200, "y_m": 0},
         {"id": "capt-1", "kind": "sensor", "name": "Proche", "x_m": 0, "y_m": 0},
         {"id": "capt-2", "kind": "sensor", "name": "Lointain", "x_m": 900, "y_m": 400}],
        {"capt-1": {"period_s": 60.0, "messages": 6, "start_spread_s": 10.0,
                    "spreading_factor": 7},
         "capt-2": {"period_s": 60.0, "messages": 6, "start_spread_s": 10.0,
                    "spreading_factor": 7}})

    mt = build_multi_trace(sc)
    assert mt.rx_matrix is not None
    assert len(mt.rx_matrix) == 2, "un capteur, une ligne"
    for g, nom in enumerate(mt.gateway_names):
        somme = sum(ligne[g] for ligne in mt.rx_matrix)
        audible = mt.per_gateway[g].audible_frames
        assert somme == audible, (
            f"{nom} : la matrice compte {somme} réceptions, le compteur en annonce {audible}")


def _resume_multi_passerelles(api, messages=3, count=6):
    """Un run à deux passerelles, et son résumé."""
    d = _scenario(count=count, messages=messages)
    d.pop("gateway")
    d["gateways"] = [{"name": "gw-ouest", "x_m": -800, "y_m": 0, "antenna_gain_dbi": 2.15},
                     {"name": "gw-est", "x_m": 800, "y_m": 0, "antenna_gain_dbi": 2.15}]
    status, created = api.call("POST", "/api/v1/runs", {"scenario": d})
    assert status == 202, created
    assert _wait_done(api, created["run_id"])["state"] == "done"
    status, summary = api.call("GET", f"/api/v1/runs/{created['run_id']}/summary")
    assert status == 200, summary
    return summary


def test_run_mono_passerelle_ne_publie_pas_de_matrice(api):
    """Une seule colonne ne dirait rien de plus que le PDR : le champ est absent."""
    status, created = api.call("POST", "/api/v1/runs", {"scenario": _scenario(count=6, messages=3)})
    assert status == 202, created
    assert _wait_done(api, created["run_id"])["state"] == "done"
    status, summary = api.call("GET", f"/api/v1/runs/{created['run_id']}/summary")
    assert status == 200, summary
    assert summary.get("gateways") is None, "ce run est mono-passerelle"
    assert summary.get("rx_matrix") is None, (
        "sans `gateways`, une matrice à une colonne ne dirait rien de plus que le PDR")


def test_run_multi_passerelles_publie_une_matrice_lisible(api):
    """Le résumé publie la matrice, indexée comme `gateways` : c'est le contrat du tracé."""
    summary = _resume_multi_passerelles(api)
    rx = summary.get("rx_matrix")
    assert rx is not None, "un run multi-passerelles publie sa matrice"
    assert len(rx) == 6, "une ligne par dispositif"
    colonnes = {len(ligne) for ligne in rx}
    assert colonnes == {2}, (
        "une colonne par passerelle : l'ordre est celui de `gateways`, rien d'autre")
    # Et la somme d'une colonne retrouve le compteur de cette passerelle.
    for g, gw in enumerate(summary["gateways"]):
        somme = sum(ligne[g] for ligne in rx)
        assert somme == gw["audible_frames"], (
            f"{gw['name']} : la matrice compte {somme} réceptions, "
            f"le compteur en annonce {gw['audible_frames']}")


# --- ADR du serveur : le chemin qui manquait -----------------------------------------------------
#
# L'ADR est simulé (boucle fermée : LinkADRReq / LinkADRAns) mais n'avait **aucun** chemin d'accès
# depuis l'atelier : ni dans la fenêtre, ni au CLI. Il exige de plus une forme de scénario que
# l'atelier ne produisait jamais (`gateway` au lieu de `gateways`), ce que le schéma refuse avec
# `mac`. Ces tests tiennent le chemin, pas le mécanisme — le mécanisme a ses propres tests.

def _session_une_passerelle(api, capteurs=("capteur-1",), region="EU868"):
    """Une frontière, des capteurs, et le plan régional posé depuis la fenêtre."""
    noeuds = [{"id": "gw-seule", "kind": "border", "name": "Seule", "x_m": 0, "y_m": 0}]
    noeuds += [{"id": c, "kind": "sensor", "name": c, "x_m": 400 + 200 * i, "y_m": 0}
               for i, c in enumerate(capteurs)]
    sid = _session(api, nodes=noeuds)
    if region is not None:
        status, _ = api.call("POST", f"/api/v1/sessions/{sid}/nodes/gw-seule/gateway",
                             {"region": region}, token=api.alice)
        assert status == 200
    return sid


def test_adr_refuse_sans_plan_regional_et_le_dit(api):
    """Sans plan régional, `mac_loop.py` lève — le run échouerait. La raison est dite avant."""
    sid = _session_une_passerelle(api, region=None)
    _, topo = api.call("GET", f"/api/v1/sessions/{sid}/topology", token=api.alice)
    assert topo["adr_possible"] is False
    assert "plan régional" in topo["adr_raison"]


def test_adr_refuse_avec_plusieurs_passerelles_et_le_dit(api):
    """`mac.link_adr` n'existe qu'à passerelle unique : le schéma le refuse, pas nous."""
    sid = _session(api, nodes=[
        {"id": "gw-a", "kind": "border", "name": "A", "x_m": -500, "y_m": 0},
        {"id": "gw-b", "kind": "border", "name": "B", "x_m": 500, "y_m": 0},
        {"id": "capteur-1", "kind": "sensor", "name": "C1", "x_m": 0, "y_m": 0}])
    for g in ("gw-a", "gw-b"):
        api.call("POST", f"/api/v1/sessions/{sid}/nodes/{g}/gateway",
                 {"region": "EU868"}, token=api.alice)
    _, topo = api.call("GET", f"/api/v1/sessions/{sid}/topology", token=api.alice)
    assert topo["adr_possible"] is False
    assert "passerelle unique" in topo["adr_raison"]


def test_adr_refuse_avec_un_relais_et_le_dit(api):
    """La boucle fermée porte un seul `GatewayLoad` : le mesh lui est fermé."""
    sid = _session(api, nodes=[
        {"id": "frontiere", "kind": "border", "name": "F", "x_m": 0, "y_m": 0},
        {"id": "relais-1", "kind": "relay", "name": "R", "x_m": 1200, "y_m": 0},
        {"id": "capteur-1", "kind": "sensor", "name": "C1", "x_m": 1400, "y_m": 0}])
    for g in ("frontiere", "relais-1"):
        api.call("POST", f"/api/v1/sessions/{sid}/nodes/{g}/gateway",
                 {"region": "EU868"}, token=api.alice)
    _, topo = api.call("GET", f"/api/v1/sessions/{sid}/topology", token=api.alice)
    assert topo["adr_possible"] is False
    assert "relais" in topo["adr_raison"]


def test_adr_possible_une_passerelle_et_un_plan(api):
    sid = _session_une_passerelle(api)
    _, topo = api.call("GET", f"/api/v1/sessions/{sid}/topology", token=api.alice)
    assert topo["adr_possible"] is True and topo["adr_raison"] == ""


def test_le_souhait_adr_est_garde_meme_quand_il_nest_pas_possible(api):
    """Une session qui veut l'ADR sans le pouvoir garde son intention et lit la raison.

    Effacer le souhait au motif qu'il n'est pas réalisable ferait perdre à l'utilisateur ce
    qu'il voulait faire, sans rien lui apprendre de plus.
    """
    sid = _session(api, nodes=[
        {"id": "gw-a", "kind": "border", "name": "A", "x_m": -500, "y_m": 0},
        {"id": "gw-b", "kind": "border", "name": "B", "x_m": 500, "y_m": 0},
        {"id": "capteur-1", "kind": "sensor", "name": "C1", "x_m": 0, "y_m": 0}])
    status, topo = api.call("POST", f"/api/v1/sessions/{sid}/adr", {"adr": True}, token=api.alice)
    assert status == 200, topo
    assert topo["adr"] is True, "le souhait est enregistré"
    assert topo["adr_possible"] is False, "mais il n'est pas annoncé comme simulé"
    assert topo["adr_raison"], "et la raison est donnée"


def test_adr_bascule_le_scenario_sur_la_forme_mono(api):
    """`gateways` par défaut ; `gateway` + `mac` quand l'ADR est demandé.

    Changer de forme n'est pas un détail de sérialisation : la forme `gateways` porte le relais
    et la matrice des réceptions du §3, la forme `gateway` porte la boucle ADR. On ne peut pas
    avoir les deux.
    """
    sid = _session_une_passerelle(api)
    # La forme se lit sur un run terminé : c'est le seul endroit observable de bout en bout,
    # il n'existe pas de route qui serve le scénario compilé.
    api.call("POST", f"/api/v1/sessions/{sid}/adr", {"adr": False}, token=api.alice)
    status, r = api.call("POST", f"/api/v1/sessions/{sid}/simulate", {"seed": 7}, token=api.alice)
    assert status == 202, r
    assert _wait_done(api, r["run_id"], token=api.alice)["state"] == "done"
    _, avant = api.call("GET", f"/api/v1/runs/{r['run_id']}/summary", token=api.alice)
    assert avant.get("gateways") is not None, "sans ADR, la forme multi-passerelles est conservée"

    api.call("POST", f"/api/v1/sessions/{sid}/adr", {"adr": True}, token=api.alice)
    status, r2 = api.call("POST", f"/api/v1/sessions/{sid}/simulate", {"seed": 7}, token=api.alice)
    assert status == 202, r2
    assert _wait_done(api, r2["run_id"], token=api.alice)["state"] == "done"
    _, apres = api.call("GET", f"/api/v1/runs/{r2['run_id']}/summary", token=api.alice)
    assert apres.get("gateway") is not None, "avec ADR, le run passe en forme mono-passerelle"
    assert apres.get("rx_matrix") is None, "le coût est réel : plus de matrice des réceptions"


def test_adr_produit_des_linkadrreq_observables(api):
    """Le but de l'exercice : le serveur commande un changement de débit, et ça se voit.

    Sans l'ADR la trace ne porte que des uplinks. Avec, elle porte des `mac_request`
    `LinkADRReq` — c'est cette différence que l'exercice interrogera.
    """
    sid = _session_une_passerelle(api, capteurs=("capteur-a", "capteur-b"))
    for c in ("capteur-a", "capteur-b"):
        status, _ = api.call("POST", f"/api/v1/sessions/{sid}/nodes/{c}/sensor",
                             {"messages": 20, "start_spread_s": 60, "spreading_factor": 9,
                              "period_s": 300}, token=api.alice)
        assert status == 200

    def linkadr(adr):
        api.call("POST", f"/api/v1/sessions/{sid}/adr", {"adr": adr}, token=api.alice)
        status, r = api.call("POST", f"/api/v1/sessions/{sid}/simulate", {"seed": 7},
                             token=api.alice)
        assert status == 202, r
        assert _wait_done(api, r["run_id"], token=api.alice)["state"] == "done"
        _, ev = api.call("GET", f"/api/v1/runs/{r['run_id']}/events?limit=500", token=api.alice)
        return [e for e in ev["items"] if e.get("outcome") == "LinkADRReq"]

    assert linkadr(False) == [], "sans ADR, aucune commande LinkADRReq"
    reqs = linkadr(True)
    assert reqs, "avec ADR, le serveur émet des LinkADRReq"


# --- Modèle de passerelle --------------------------------------------------------------------
# Le modèle vit sur le nœud, pas dans la configuration CLI : c'est le matériel. Mais il se
# règle au même endroit que les autres réglages passerelle (`POST .../gateway`), sinon une
# passerelle posée depuis la palette resterait au seuil de référence sans pouvoir en changer.

def _gateway(api, sid, noeud, body):
    status, out = api.call("POST", f"/api/v1/sessions/{sid}/nodes/{noeud}/gateway", body)
    if status == 200:
        SessionTopology.model_validate(out)
    return status, out


def _modele_de(api, sid, noeud):
    status, topo = api.call("GET", f"/api/v1/sessions/{sid}/topology")
    assert status == 200, topo
    return next((n.get("gateway_profile") for n in topo["nodes"] if n["id"] == noeud), None)


def _environment(api, sid, body):
    status, out = api.call("POST", f"/api/v1/sessions/{sid}/environment", body)
    if status == 200:
        SessionTopology.model_validate(out)
    return status, out


def test_gateway_profile_is_set_read_and_cleared_through_the_same_route(api):
    sid = _session(api)

    status, _ = _gateway(api, sid, "frontiere", {"gateway_profile": "rak7249"})
    assert status == 200
    assert _modele_de(api, sid, "frontiere") == "rak7249"

    # Vide explicite : retour à la référence du moteur.
    status, _ = _gateway(api, sid, "frontiere", {"gateway_profile": None})
    assert status == 200
    assert _modele_de(api, sid, "frontiere") is None

    # Champ absent : rien ne change — un envoi partiel ne doit pas effacer le modèle posé.
    _gateway(api, sid, "frontiere", {"gateway_profile": "rak7249"})
    status, _ = _gateway(api, sid, "frontiere", {"region": "EU868"})
    assert status == 200
    assert _modele_de(api, sid, "frontiere") == "rak7249"


def test_gateway_profile_is_refused_on_a_sensor(api):
    """Les réglages passerelle n'existent que sur une passerelle — un capteur n'en a pas."""
    sid = _session(api)
    status, out = _gateway(api, sid, "capteur-1", {"gateway_profile": "rak7249"})
    assert status == 422, out


def test_an_unknown_gateway_profile_is_refused_by_the_route(api):
    """Un modèle hors catalogue est refusé ici, pas au run : l'erreur nomme le champ."""
    sid = _session(api)
    status, out = _gateway(api, sid, "frontiere", {"gateway_profile": "invente"})
    assert status == 422, out
    assert "gateway_profile" in str(out)


def test_the_environment_is_set_read_and_partially_applied(api):
    """Obstacles, shadowing et hauteurs : seul ce qui est envoyé change.

    Un envoi partiel ne doit pas effacer les murs posés, sinon régler le shadowing
    reviendrait à démolir le quartier.
    """
    sid = _session(api)

    mur = {"x_min_m": 400.0, "y_min_m": -300.0, "x_max_m": 600.0, "y_max_m": 300.0,
           "height_m": 12.0, "attenuation_db": 6.0}
    status, topo = _environment(api, sid, {"obstacles": [mur], "shadowing_sigma_db": 4.0})
    assert status == 200, topo
    env = topo["environment"]
    assert len(env["obstacles"]) == 1 and env["shadowing_sigma_db"] == 4.0
    assert env["obstacles"][0]["attenuation_db"] == 6.0

    # Envoi partiel : le mur reste.
    status, topo = _environment(api, sid, {"gateway_height_m": 40.0})
    assert status == 200, topo
    assert len(topo["environment"]["obstacles"]) == 1
    assert topo["environment"]["gateway_height_m"] == 40.0
    assert topo["environment"]["shadowing_sigma_db"] == 4.0   # inchangé


def test_an_unknown_material_is_refused_when_the_wall_is_built(api):
    """Un matériau hors catalogue se refuse à la pose du mur, pas au run."""
    sid = _session(api)
    status, out = _environment(api, sid, {"obstacles": [
        {"x_min_m": 0.0, "y_min_m": 0.0, "x_max_m": 10.0, "y_max_m": 10.0,
         "material": "carton", "thickness_m": 0.2}]})
    assert status == 422, out


def test_a_wall_cannot_carry_both_an_attenuation_and_a_material(api):
    sid = _session(api)
    status, _ = _environment(api, sid, {"obstacles": [
        {"x_min_m": 0.0, "y_min_m": 0.0, "x_max_m": 10.0, "y_max_m": 10.0,
         "attenuation_db": 5.0, "material": "concrete", "thickness_m": 0.2}]})
    assert status == 422


def test_the_material_catalogue_says_what_is_extrapolated(api):
    """À 868 MHz, 12 matériaux sur 15 sortent de la plage documentée : le dire.

    Sans cette mention, une perte affichée passerait pour mesurée alors que le moteur
    l'extrapole hors du Tableau 3 de l'UIT-R P.2040-4.
    """
    from lsim.api_contract import list_materials
    r = list_materials(868.1e6, 0.2)
    dans_la_plage = [m.name for m in r.materials if not m.extrapolated]
    assert dans_la_plage == ["air", "wood", "glass"], dans_la_plage
    assert len(r.materials) - len(dans_la_plage) == 12   # 12 des 15 extrapolés
    beton = next(m for m in r.materials if m.name == "concrete")
    assert beton.extrapolated and beton.loss_db > 0
