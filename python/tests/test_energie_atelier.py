"""Énergie dans l'atelier : le profil du run, et celui que l'équipement s'approprie.

Un capteur peut porter son propre modèle de matériel, ou dire « celui du run ». La seconde
option n'a de sens que si le run **a** un profil : sans lui, le capteur garde un choix qui ne
mène à rien, et l'énergie n'est pas calculée — sans que rien ne le dise, une case vide se
lisant comme une mesure nulle.

Ce fichier est la preuve que la chaîne tient dans les deux sens : le profil du run descend
jusqu'au moteur, et le modèle propre d'un équipement **prime** sur lui. Deux capteurs de
matériel différent placés dans le même run y consomment deux choses différentes ; c'est
précisément l'intérêt du réglage, et c'est ce qui interdit de recopier l'un dans l'autre.
"""

import pytest

from lsim.api_contract import RunSummary, list_energy_profiles
from lsim.energy_report import ENERGY_PROFILES
from lsim.study_compile import ENERGY_PROFILE, compile_session
from lsim.study_contract import Node, SensorSettings
from lsim.study_cli import GatewayConfig
from test_api_server import _wait_done
from test_study_api import _make_api, _session

NODES = [
    {"id": "gw1", "kind": "border", "name": "Frontière", "x_m": 0, "y_m": 0},
    {"id": "c-run", "kind": "sensor", "name": "Capteur du run", "x_m": 100, "y_m": 0},
    {"id": "c-propre", "kind": "sensor", "name": "Capteur stm32", "x_m": 200, "y_m": 0},
]

# L'autre matériel du catalogue. Lu depuis le moteur, pas recopié : une liste écrite ici
# cesserait de valoir le jour où il en déclare un troisième.
AUTRE = next(n for n in sorted(ENERGY_PROFILES) if n != ENERGY_PROFILE)


@pytest.fixture()
def api(tmp_path):
    with _make_api(tmp_path) as a:
        yield a


def _corps_compile():
    """Le corps de `POST /runs` que l'atelier enverrait pour cette topologie."""
    nodes = [Node.model_validate(n) for n in NODES]
    conf = {n.id: GatewayConfig() for n in nodes if n.kind in ("border", "relay")}
    return compile_session(nodes, conf, 7).body


# --- Le profil du run ---------------------------------------------------------------------------

def test_le_defaut_annonce_est_celui_que_le_run_calcule():
    """« Celui du run » doit désigner le même matériel que celui du corps compilé.

    Rien ne liait les deux : le catalogue pouvait annoncer un défaut et le compilateur en
    écrire un autre, et l'interface aurait nommé un matériel que le run n'a pas utilisé. Le
    courant moyen affiché se serait alors lu avec une confiance qu'il n'avait pas.
    """
    annonce = list_energy_profiles().default
    assert annonce == _corps_compile()["energy_profile"]
    # Et il est dans le catalogue : un défaut hors liste n'aurait pas de libellé à afficher.
    assert annonce in [p.name for p in list_energy_profiles().profiles]

def test_le_run_d_atelier_declare_un_profil_d_energie():
    """Sans lui, « celui du run » serait un choix sans effet.

    C'est la dette qu'on croyait ouverte : `_simulate` crée le run avec `compiled.body`, donc
    un corps sans `energy_profile` donnait un run sans énergie du tout — et une case vide
    plutôt qu'un zéro, qu'on aurait pu lire comme « ce capteur ne consomme rien ».
    """
    assert _corps_compile()["energy_profile"] == ENERGY_PROFILE


def test_le_groupe_d_un_capteur_sans_modele_ne_declare_rien():
    """« Celui du run » ne s'écrit pas dans le scénario : le groupe reste celui d'avant.

    C'est ce qui garde son empreinte à un chantier écrit avant l'existence du réglage — et
    donc ses chiffres, le moteur ne faisant alors rien de plus.
    """
    groupes = {g["name"]: g for g in _corps_compile()["scenario"]["groups"]}
    assert "energy" not in groupes["c-run"]


def test_le_modele_choisi_s_ecrit_dans_le_groupe():
    nodes = [Node.model_validate(NODES[0]),
             Node(id="c1", kind="sensor", name="c1", x_m=100.0, y_m=0.0,
                  sensor=SensorSettings(energy_profile=AUTRE))]
    conf = {n.id: GatewayConfig() for n in nodes if n.kind in ("border", "relay")}
    groupe = compile_session(nodes, conf, 7).body["scenario"]["groups"][0]
    assert groupe["energy"] == {"profile": AUTRE}


# --- Bout en bout : du réglage posé dans l'atelier à l'énergie mesurée ---------------------------

def test_les_deux_materiels_ne_consomment_pas_la_meme_chose(api):
    """Deux capteurs identiques, deux matériels, un seul run : les chiffres diffèrent.

    C'est la seule preuve qui vaille : un profil lu mais ignoré donnerait deux fois le même
    résultat, et un test qui ne vérifierait que « l'énergie est présente » passerait quand
    même. L'écart, lui, ne peut venir que du matériel.
    """
    sid = _session(api, NODES)
    # Mêmes réglages partout, sauf le matériel ; les départs sont décalés pour que deux
    # capteurs à la même période ne se collisionnent pas.
    for i, (nid, modele) in enumerate((("c-run", None), ("c-propre", AUTRE))):
        reglage = {"period_s": 60, "messages": 3, "start_spread_s": 30 * i}
        if modele is not None:
            reglage["energy_profile"] = modele
        status, body = api.call("POST", f"/api/v1/sessions/{sid}/nodes/{nid}/sensor", reglage)
        assert status == 200, body

    status, body = api.call("POST", f"/api/v1/sessions/{sid}/simulate", {"seed": 7})
    assert status == 202, body
    _wait_done(api, body["run_id"])

    _, summary = api.call("GET", f"/api/v1/runs/{body['run_id']}/summary")
    RunSummary.model_validate(summary)
    # Le profil du run est celui qu'on a compilé : un résumé muet laisserait croire à un run
    # sans modèle, donc sans énergie.
    assert summary["energy_profile"] == ENERGY_PROFILE

    _, page = api.call("GET", f"/api/v1/runs/{body['run_id']}/devices")
    par_groupe = {r["group"]: r for r in page["items"]}

    # Le capteur sans modèle propre consomme quand même : le profil du run l'a porté.
    # « Pas de mesure » n'aurait pas dû devenir « pas d'énergie ».
    assert par_groupe["c-run"]["energy_per_message_j"] is not None
    assert par_groupe["c-run"]["average_current_ua"] is not None
    assert par_groupe["c-propre"]["energy_per_message_j"] is not None

    # Et les deux ne se confondent pas : le modèle propre a primé.
    assert par_groupe["c-run"]["average_current_ua"] != pytest.approx(
        par_groupe["c-propre"]["average_current_ua"], rel=1e-3)
