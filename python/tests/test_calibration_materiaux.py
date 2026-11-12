"""Calibration des matériaux : remplacer P.2040-4 par une mesure.

La table du moteur vient de la recommandation UIT-R P.2040-4 (diélectriques). À 868 MHz,
12 des 15 matériaux sortent de la plage documentée : la valeur est extrapolée, et le
moteur le signale. Une mesure vaut mieux qu'une extrapolation, et elle se déclare dans
l'environnement (`material_calibration`).

Deux propriétés sont vérifiées ici, et elles sont distinctes :

1. la mesure **remplace** la recommandation — l'atténuation de l'obstacle est bien
   `loss_db_per_m × épaisseur`, pas la valeur de la table ;
2. une mesure **n'est pas une extrapolation** — l'avertissement P.2040-4 ne porte que
   sur la table, et le faire porter sur un relevé ferait douter d'une valeur solide.

Aucun `parametrize` : chaque cas est une fonction nommée.
"""

import pathlib
import tempfile
import warnings

import pytest

_SCENARIO = """schema_version: 1
name: mur de beton
seed: 4
gateway:
  x_m: -600
  y_m: 0
environment:
  gateway_height_m: 5.0
  device_height_m: 1.5
{CALIB}  obstacles:
    - x_min_m: -1
      y_min_m: -400
      x_max_m: 1
      y_max_m: 400
      height_m: 20.0
      material: concrete
      thickness_m: 0.25
groups:
  - name: derriere le mur
    count: 4
    placement:
      type: disk
      radius_m: 100
      center_x_m: 1500
      center_y_m: 0
    spreading_factor: 10
    payload_bytes: 10
    tx_power_dbm: 14.0
    period_s: 3600
    start_spread_s: 120
    messages: 1
"""


def _calibration(db_par_m: float, provenance: str = "mesure in situ, Douala") -> str:
    return (f"  material_calibration:\n"
            f"    concrete:\n"
            f"      loss_db_per_m: {db_par_m}\n"
            f"      provenance: \"{provenance}\"\n")


def _scenario(dossier: str, calib: str = "") -> str:
    p = pathlib.Path(dossier) / "mur.yaml"
    p.write_text(_SCENARIO.format(CALIB=calib), encoding="utf-8")
    return str(p)


def _attenuation(chemin: str) -> float:
    from lsim.scenario import load_scenario

    return load_scenario(chemin).environment.obstacles[0].attenuation_db


# --- La mesure remplace la recommandation ------------------------------------------------------

def test_une_mesure_remplace_la_valeur_de_la_table():
    with tempfile.TemporaryDirectory() as d:
        sans = _attenuation(_scenario(d))
        avec = _attenuation(_scenario(d, _calibration(60.0)))
    # 0,25 m de béton : la table P.2040-4 donne environ 9 dB (extrapolé à 868 MHz),
    # la mesure 60 dB/m en donne exactement 15.
    assert avec == pytest.approx(60.0 * 0.25)
    assert sans != pytest.approx(avec), "sans la mesure, la table s'applique"
    assert sans == pytest.approx(8.977, abs=0.01)


def test_une_mesure_n_est_pas_une_extrapolation():
    """L'avertissement P.2040-4 porte sur la table, pas sur un relevé.

    Le laisser porter sur une mesure ferait douter d'une valeur solide — et
    l'inverse, le taire pour la table, cacherait une extrapolation.
    """
    from lsim.scenario import load_scenario

    with tempfile.TemporaryDirectory() as d:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            load_scenario(_scenario(d))
            assert any("P.2040-4" in str(x.message) for x in w), "la table doit être signalée"
            w.clear()
            load_scenario(_scenario(d, _calibration(60.0)))
            assert not any("P.2040-4" in str(x.message) for x in w), "une mesure n'est pas extrapolée"


def test_l_effet_se_voit_sur_le_run():
    """Une perte plus forte fait tomber la liaison : la mesure change le résultat."""
    from lsim.export import run_scenario
    from lsim.scenario import load_scenario

    with tempfile.TemporaryDirectory() as d:
        leger = run_scenario(load_scenario(_scenario(d, _calibration(0.0))))
        lourd = run_scenario(load_scenario(_scenario(d, _calibration(200.0))))
    assert leger.totals.received == 4, "0 dB/m : le mur ne coûte rien"
    assert lourd.totals.received == 0, "50 dB : plus rien ne passe"
    assert lourd.totals.lost_sensitivity == 4


# --- Validation --------------------------------------------------------------------------------

def test_provenance_obligatoire():
    from lsim.scenario import EnvironmentModel

    with pytest.raises(ValueError):
        EnvironmentModel(material_calibration={"concrete": {"loss_db_per_m": 12.5}})
    for vide in ("", "   "):
        with pytest.raises(ValueError):
            EnvironmentModel(
                material_calibration={"concrete": {"loss_db_per_m": 12.5, "provenance": vide}})


def test_materiau_inconnu_est_refuse():
    from lsim.scenario import EnvironmentModel

    with pytest.raises(ValueError):
        EnvironmentModel(
            material_calibration={"béton": {"loss_db_per_m": 12.5, "provenance": "mesure"}})


def test_perte_negative_est_refusee():
    from lsim.scenario import EnvironmentModel

    with pytest.raises(ValueError):
        EnvironmentModel(
            material_calibration={"concrete": {"loss_db_per_m": -1.0, "provenance": "mesure"}})


def test_un_obstacle_sans_materiau_n_est_pas_calibre():
    """La calibration porte sur un matériau ; une atténuation saisie reste la saisie."""
    from lsim.scenario import EnvironmentModel, ObstacleModel

    env = EnvironmentModel(
        obstacles=[ObstacleModel(x_min_m=0, y_min_m=0, x_max_m=1, y_max_m=1, height_m=5,
                                 attenuation_db=7.5)],
        material_calibration={"concrete": {"loss_db_per_m": 60.0, "provenance": "mesure"}})
    assert env.obstacles[0].attenuation_db == 7.5


# --- Empreinte ---------------------------------------------------------------------------------

def test_une_calibration_vide_ne_pese_pas_dans_l_empreinte():
    """Sans mesure déclarée, l'empreinte est celle d'avant la possibilité."""
    from lsim.scenario import load_scenario

    with tempfile.TemporaryDirectory() as d:
        sans = load_scenario(_scenario(d))
        vide = load_scenario(_scenario(d, "  material_calibration: {}\n"))
    assert sans.sha256 == vide.sha256


def test_une_calibration_reelle_change_l_empreinte():
    """Deux modèles différents ne peuvent pas partager une empreinte."""
    from lsim.scenario import load_scenario

    with tempfile.TemporaryDirectory() as d:
        sans = load_scenario(_scenario(d))
        avec = load_scenario(_scenario(d, _calibration(60.0)))
    assert sans.sha256 != avec.sha256
