"""Énergie mesurée : entrer un relevé au lieu d'une fiche constructeur.

Les deux profils du moteur viennent de fiches : bons pour comparer deux architectures,
insuffisants pour garantir une autonomie. Ce fichier vérifie qu'un relevé peut les
remplacer **de bout en bout** — YAML, calcul, rapport — et surtout qu'il est étiqueté :
des courants mesurés présentés comme une donnée du moteur seraient pires qu'une absence,
parce qu'on leur ferait confiance sans le savoir.

Aucun `parametrize` : chaque cas est une fonction nommée.
"""

import pathlib
import tempfile

import pytest

from lsim.energy import MeasuredProfile, device_energy, device_energy_class_a
from lsim.energy_report import device_energies

# Relevé équivalent au profil RAK4631 du catalogue (3,3 V ; 92 mA à +14 dBm ; Rx 17 mA ;
# veille 2,0 µA). Il sert de référence : à courants identiques, les deux chemins doivent
# rendre exactement la même chose.
RELEVE_RAK = MeasuredProfile(
    supply_v=3.3, rx_ma_125khz=17.0, rx_ma_250khz=17.0, rx_ma_500khz=17.0, sleep_ua=2.0,
    mcu_run_ma=0.0, provenance="relevé banc, 2026-03",
    tx_points=((14.0, 92.0), (17.0, 92.0), (20.0, 125.0)))

ARGS = dict(tx_power_dbm=14.0, bandwidth_hz=125_000, airtime_ns=50_000_000,
            total_ns=3_600_000_000_000)

_SCENARIO = """schema_version: 1
name: energie mesuree
seed: 11
gateway:
  x_m: 0
  y_m: 0
energy:
  measured:
    supply_v: 3.3
    rx_ma_125khz: 17.0
    rx_ma_250khz: 17.0
    rx_ma_500khz: 17.0
    sleep_ua: 2.0
    provenance: "releve banc, 2026-03, pince Keysight"
    tx_points:
      - {dbm: 14.0, ma: 92.0}
      - {dbm: 20.0, ma: 125.0}
groups:
  - name: capteurs
    count: 3
    placement:
      type: disk
      radius_m: 500
    spreading_factor: 9
    payload_bytes: 10
    tx_power_dbm: 14.0
    period_s: 600
    messages: 2
"""


def _scenario(dossier: str) -> str:
    p = pathlib.Path(dossier) / "mesure.yaml"
    p.write_text(_SCENARIO, encoding="utf-8")
    return str(p)


# --- Concordance avec le catalogue -------------------------------------------------------------

def test_un_releve_egal_au_catalogue_rend_la_meme_chose():
    """À courants identiques, le relevé doit reproduire le profil trait pour trait.

    C'est la seule preuve que le nouveau chemin calcule la même grandeur : un écart
    signifierait une divergence, pas une mesure.
    """
    from lsim.energy import PROFILE_RAK4631

    catalogue = device_energy(profile_id=PROFILE_RAK4631, **ARGS)
    mesure = device_energy(measured=RELEVE_RAK, **ARGS)
    assert mesure.energy_j == pytest.approx(catalogue.energy_j, rel=1e-12)
    assert mesure.average_current_ua == pytest.approx(catalogue.average_current_ua, rel=1e-12)


def test_meme_concordance_en_classe_a():
    from lsim.energy import PROFILE_RAK4631

    args = dict(tx_power_dbm=14.0, bandwidth_hz=125_000, spreading_factor=9,
                preamble_symbols=8, uplinks=24, airtime_ns=50_000_000,
                total_ns=86_400_000_000_000)
    a = device_energy_class_a(profile_id=PROFILE_RAK4631, **args)
    b = device_energy_class_a(measured=RELEVE_RAK, **args)
    assert b.energy_j == pytest.approx(a.energy_j, rel=1e-12)


def test_le_resultat_porte_la_provenance():
    """Le résultat dit d'où viennent les courants — sinon le rapport ne peut pas le dire."""
    mesure = device_energy(measured=RELEVE_RAK, **ARGS)
    assert mesure.provenance == "relevé banc, 2026-03"
    assert device_energy(profile_id=0, **ARGS).provenance is None


# --- Validation --------------------------------------------------------------------------------

def test_provenance_vide_est_refusee():
    for vide in ("", "   "):
        with pytest.raises(ValueError):
            MeasuredProfile(supply_v=3.3, rx_ma_125khz=17.0, rx_ma_250khz=17.0,
                            rx_ma_500khz=17.0, sleep_ua=2.0, mcu_run_ma=0.0, provenance=vide,
                            tx_points=((14.0, 92.0),))


def test_points_d_emission_non_croissants_sont_refuses():
    with pytest.raises(ValueError):
        MeasuredProfile(supply_v=3.3, rx_ma_125khz=17.0, rx_ma_250khz=17.0, rx_ma_500khz=17.0,
                        sleep_ua=2.0, mcu_run_ma=0.0, provenance="relevé",
                        tx_points=((20.0, 125.0), (14.0, 92.0)))


def test_trop_de_points_est_refuse():
    with pytest.raises(ValueError):
        MeasuredProfile(supply_v=3.3, rx_ma_125khz=17.0, rx_ma_250khz=17.0, rx_ma_500khz=17.0,
                        sleep_ua=2.0, mcu_run_ma=0.0, provenance="relevé",
                        tx_points=tuple((float(10 + k), 90.0 + k) for k in range(5)))


# --- De bout en bout, depuis le YAML -----------------------------------------------------------

def test_un_releve_declare_dans_le_yaml_est_calcule_sans_option():
    """Un relevé écrit dans le scénario est une demande de calcul, pas un réglage en attente."""
    from lsim.export import run_scenario
    from lsim.scenario import load_scenario

    with tempfile.TemporaryDirectory() as d:
        r = run_scenario(load_scenario(_scenario(d)))
    assert r.energy_profile is None
    assert r.energy_provenance == "releve banc, 2026-03, pince Keysight"
    assert all(ligne.energy_per_message_j is not None for ligne in r.rows)
    assert all(ligne.average_current_ua is not None for ligne in r.rows)


def test_un_profil_nomme_prime_sur_le_releve_sans_etre_etiquete_mesure():
    """Une option explicite gagne — et la provenance ne voyage pas, puisqu'elle n'a pas servi.

    Sans cette règle, « --energy-profile rak4631 » serait ignoré en silence ; et sans la
    seconde moitié, un rapport afficherait « relevé » en face de chiffres du catalogue.
    """
    from lsim.export import run_scenario
    from lsim.scenario import load_scenario

    with tempfile.TemporaryDirectory() as d:
        chemin = _scenario(d)
        mesure = run_scenario(load_scenario(chemin))
        catalogue = run_scenario(load_scenario(chemin),
                                 energy_profile="sx1262-stm32l072")
    assert catalogue.energy_profile == "sx1262-stm32l072"
    assert catalogue.energy_provenance is None, "la provenance ne s'applique pas"
    assert abs(catalogue.rows[0].energy_per_message_j
               - mesure.rows[0].energy_per_message_j) > 1e-9


def test_le_rapport_nomme_la_provenance_et_pas_un_profil_du_catalogue():
    """Le résumé du rapport ne doit pas présenter une mesure comme une fiche constructeur.

    On lit la ligne de résumé plutôt que le PDF rendu : c'est elle qui porte le
    libellé, et la tester directement évite d'ajouter une dépendance de rendu à la
    suite pour vérifier une chaîne de caractères.
    """
    from lsim.export import run_scenario
    from lsim.report import _ENERGY_SUMMARY_LABEL, _summary_rows
    from lsim.scenario import load_scenario

    with tempfile.TemporaryDirectory() as d:
        mesure = run_scenario(load_scenario(_scenario(d)))
        catalogue = run_scenario(load_scenario(_scenario(d)),
                                 energy_profile="sx1262-stm32l072")

    ligne_mesure = dict(_summary_rows(mesure))[_ENERGY_SUMMARY_LABEL]
    ligne_catalogue = dict(_summary_rows(catalogue))[_ENERGY_SUMMARY_LABEL]
    assert "RAK4631" not in ligne_mesure, "un relevé ne s'affiche pas comme le catalogue"
    assert "relevé" in ligne_mesure and "pince Keysight" in ligne_mesure
    assert "SX1262" in ligne_catalogue


def test_device_energies_accepte_un_releve():
    from lsim.scenario import load_scenario

    with tempfile.TemporaryDirectory() as d:
        scenario = load_scenario(_scenario(d))
        devices, _groups, _indices = scenario.deploy()
        energies = device_energies(devices, None, scenario.measured_energy())
    assert len(energies) == 3
    assert all(e.energy_per_message_j is not None for e in energies)
