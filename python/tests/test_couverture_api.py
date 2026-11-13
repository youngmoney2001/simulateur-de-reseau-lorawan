"""Route GET /api/v1/sessions/{sid}/coverage : ce que l'atelier et la carte consomment.

Le calcul reste dans le moteur ; la route ne fait que choisir le capteur de référence
et résoudre le relief du catalogue, que le service d'étude ne connaît pas.
"""

import shutil
from pathlib import Path

import pytest

from test_api_server import _make_api

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"

SESSION = {"nodes": [
    {"id": "gw", "kind": "border", "name": "Passerelle", "x_m": 0, "y_m": 0},
    {"id": "c1", "kind": "sensor", "name": "Capteur", "x_m": 600, "y_m": 0,
     "sensor": {"spreading_factor": 10, "tx_power_dbm": 14.0}},
]}


@pytest.fixture()
def api(tmp_path):
    with _make_api(tmp_path) as a:
        yield a


@pytest.fixture()
def api_relief(tmp_path):
    catalogue = tmp_path / "terrains"
    catalogue.mkdir()
    shutil.copy(EXAMPLES / "relief_quartier_dem.csv", catalogue / "quartier.csv")
    with _make_api(tmp_path, terrain_dir=catalogue) as a:
        yield a


def creer(api):
    status, body = api.call("POST", "/api/v1/sessions", SESSION)
    assert status == 201
    return body["session_id"]


def test_la_zone_d_une_session_vierge_est_un_disque(api):
    sid = creer(api)
    status, cov = api.call("GET", f"/api/v1/sessions/{sid}/coverage")
    assert status == 200
    assert cov["source"] == "capteurs" and cov["sf"] == 10
    zone = cov["gateways"][0]
    assert zone["node_id"] == "gw" and zone["modele"] == "log_distance"
    assert zone["antenna"] is None
    r = zone["paliers"][-1]["radii_m"]
    assert max(r) - min(r) < 1e-6


def test_les_trois_paliers_sont_publies(api):
    sid = creer(api)
    _, cov = api.call("GET", f"/api/v1/sessions/{sid}/coverage")
    paliers = cov["gateways"][0]["paliers"]
    assert [p["qualite"] for p in paliers] == ["excellent", "bon", "limite"]
    for proche, lointain in zip(paliers, paliers[1:]):
        assert max(proche["radii_m"]) < max(lointain["radii_m"])


def test_un_capteur_de_reference_peut_etre_demande(api):
    sid = creer(api)
    _, cov = api.call("GET", f"/api/v1/sessions/{sid}/coverage?sf=7&tx_power_dbm=14")
    assert cov["source"] == "demande" and cov["sf"] == 7
    _, defaut = api.call("GET", f"/api/v1/sessions/{sid}/coverage")
    assert max(cov["gateways"][0]["paliers"][-1]["radii_m"]) < max(
        defaut["gateways"][0]["paliers"][-1]["radii_m"])


def test_un_parametre_illisible_est_refuse_sans_etre_pris_pour_une_absence(api):
    sid = creer(api)
    for query, champ in (("?sf=99", "sf"), ("?sf=abc", "sf"),
                         ("?tx_power_dbm=1e9", "tx_power_dbm")):
        status, body = api.call("GET", f"/api/v1/sessions/{sid}/coverage{query}")
        assert status == 422, query
        assert body["field"] == champ, query


def test_le_relief_choisi_dans_l_atelier_entre_dans_la_zone(api_relief):
    """Le relief de la session est résolu côté serveur, pas deviné par l'atelier."""
    api = api_relief
    sid = creer(api)
    _, plat = api.call("GET", f"/api/v1/sessions/{sid}/coverage")
    assert plat["gateways"][0]["modele"] == "log_distance"

    status, _ = api.call("POST", f"/api/v1/sessions/{sid}/terrain",
                         {"terrain_id": "quartier"})
    assert status == 200
    _, creuse = api.call("GET", f"/api/v1/sessions/{sid}/coverage")
    zone = creuse["gateways"][0]
    assert zone["modele"] == "environment"
    r = zone["paliers"][-1]["radii_m"]
    assert max(r) - min(r) > 100.0      # un relief n'est pas un disque


def test_une_session_etrangere_est_refusee(api):
    sid = creer(api)
    status, _ = api.call("GET", f"/api/v1/sessions/{sid}/coverage", token=api.bob)
    assert status == 404
