"""Les runs d'un chantier : liste, ordre, et ce qu'un run non terminé ne publie pas.

Ce que ce test garde, c'est la possibilité de **comparer deux réglages** sans les refaire : un
chantier se relance avec une autre graine ou un autre SF, et les deux runs restent consultables.
Sans cette liste, l'atelier ne connaît que le dernier run, et comparer veut dire se souvenir.

Le point le plus testé est le second : un run en cours n'a pas de résultat. Lui publier des zéros
ferait lire « aucun message reçu » là où il n'y a pas encore eu de mesure.
"""

import time

import pytest

from lsim.api_contract import SessionRunList
from lsim.study_contract import Node
from test_api_server import _make_api, _wait_done
from test_study_api import NODES as NODES_SESSION, _session

NODES = [
    {"id": "gw1", "kind": "border", "name": "Frontière", "x_m": 0, "y_m": 0},
    {"id": "c1", "kind": "sensor", "name": "Capteur 1", "x_m": 100, "y_m": 0},
]


@pytest.fixture()
def api(tmp_path):
    with _make_api(tmp_path) as a:
        yield a


def _lancer(api, sid, seed):
    status, body = api.call("POST", f"/api/v1/sessions/{sid}/simulate", {"seed": seed})
    assert status == 202, body
    return body["run_id"]


def _runs(api, sid, token=None):
    status, body = api.call("GET", f"/api/v1/sessions/{sid}/runs", token=token or api.alice)
    return status, body


# --- Ce que la liste doit à la comparaison ---------------------------------------------------

def test_un_chantier_neuf_ne_declare_aucun_run(api):
    sid = _session(api)
    status, body = _runs(api, sid)
    assert status == 200, body
    SessionRunList.model_validate(body)
    assert body["items"] == []


def test_deux_runs_restent_consultables_et_sont_dans_l_ordre_de_lancement(api):
    """Le plus récent d'abord : c'est celui qu'on vient de faire qu'on veut revoir."""
    sid = _session(api)
    premier = _lancer(api, sid, 7)
    _wait_done(api, premier)
    second = _lancer(api, sid, 8)
    _wait_done(api, second)

    status, body = _runs(api, sid)
    assert status == 200, body
    SessionRunList.model_validate(body)
    ids = [r["run_id"] for r in body["items"]]
    assert ids == [second, premier]
    # La graine distingue deux runs du même chantier : sans elle, « relancer » et « revoir »
    # se confondent.
    assert [r["seed"] for r in body["items"]] == [8, 7]


def test_un_run_termine_publie_ses_grands_nombres(api):
    sid = _session(api)
    run = _lancer(api, sid, 7)
    _wait_done(api, run)

    status, body = _runs(api, sid)
    assert status == 200, body
    item = body["items"][0]
    assert item["state"] == "done"
    assert 0.0 <= item["pdr"] <= 1.0
    assert item["sent"] >= item["received"] > 0
    assert item["created_at"] > 0


def test_un_run_non_termine_ne_publie_pas_de_zeros(api):
    """Pas de mesure ne veut pas dire mesure nulle : les chiffres sont absents, pas à zéro.

    Le run est posé dans le stockage sans être mis en file : c'est le seul moyen d'observer
    l'état « en cours » sans courir après le moteur, et l'invariant testé est celui du
    résumé, pas celui du travailleur.
    """
    svc = api.service
    run_id = "runencours0001"
    svc._store.insert_run(run_id, "alice", 3, "0" * 64, int(time.time()))
    vu = svc.resume("alice", run_id)

    assert vu["state"] == "queued"
    assert vu["seed"] == 3
    # Ni zéro, ni vide : la clé n'existe pas. « 0 reçu » se lirait comme une mesure.
    assert "pdr" not in vu
    assert "sent" not in vu
    assert "received" not in vu
    assert "downlink" not in vu
    # La validation du contrat passe : ces champs sont optionnels, pas obligatoires.
    SessionRunList.model_validate({"items": [vu]})


# --- Propriété et effacement ------------------------------------------------------------------

def test_un_run_d_un_autre_proprietaire_n_entre_pas_dans_la_liste(api):
    """La liste est celle du chantier **et** de son propriétaire : un run d'un autre jeton
    n'y apparaît pas, même si son identifiant est connu."""
    sid = _session(api)
    run = _lancer(api, sid, 7)
    _wait_done(api, run)

    autre = _session(api, token=api.bob)
    status, body = api.call("GET", f"/api/v1/sessions/{autre}/runs", token=api.bob)
    assert status == 200, body
    assert body["items"] == []
    # Le chantier d'Alice est invisible pour Bob, pas vide : c'est un 404, pas une liste.
    status, _ = _runs(api, sid, token=api.bob)
    assert status == 404


def test_un_run_evince_du_stockage_est_saute_sans_casser_la_liste(api):
    """L'historique du chantier n'est pas le stockage : un run effacé n'est plus là, et les
    autres restent lisibles."""
    sid = _session(api)
    premier = _lancer(api, sid, 7)
    _wait_done(api, premier)
    second = _lancer(api, sid, 8)
    _wait_done(api, second)

    assert api.call("DELETE", f"/api/v1/runs/{premier}")[0] == 204

    status, body = _runs(api, sid)
    assert status == 200, body
    assert [r["run_id"] for r in body["items"]] == [second]


def test_l_historique_du_chantier_est_borne():
    """Le chantier ne rattache que `MAX_COMPILED` runs : le plus ancien n'est pas perdu, il
    cesse d'être rattaché. Vérifié sur le service, sans lancer de run — la borne est celle
    du chantier, pas celle du moteur."""
    from lsim.study_contract import SessionCreate
    from lsim.study_session import MAX_COMPILED, StudyService

    svc = StudyService()
    sid = svc.create("alice", SessionCreate()).session_id
    for i in range(MAX_COMPILED + 3):
        svc.record_simulation("alice", sid, f"run{i:029d}", [])

    ids = svc.runs("alice", sid)
    assert len(ids) == MAX_COMPILED
    # Les plus récents sont gardés, dans l'ordre de lancement inversé.
    assert ids[0] == f"run{MAX_COMPILED + 2:029d}"
    assert ids[-1] == f"run{3:029d}"


def test_un_run_rappelle_ses_liaisons(api):
    """Les liaisons équipement <-> passerelle du run : sans elles, revoir un run afficherait
    des équipements sans jamais dire qui a entendu qui."""
    sid = _session(api)
    run = _lancer(api, sid, 7)
    _wait_done(api, run)

    status, body = _runs(api, sid)
    assert status == 200, body
    # Un équipement de la session et la passerelle qui l'a entendu, et rien d'autre : un
    # capteur ne figure pas dans les liaisons, il est entendu, il n'entend pas.
    relais = {n["id"] for n in NODES_SESSION if n["kind"] in ("border", "relay")}
    vu = {(l["node_id"], l["gateway"]) for l in body["items"][0]["links"]}
    assert vu == {(n, n) for n in relais}
