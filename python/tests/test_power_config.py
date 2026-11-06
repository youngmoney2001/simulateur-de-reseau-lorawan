"""A2 — Configuration de puissance : séparation des grandeurs et conversions.

Vérifie que la puissance du terminal, celle de la passerelle, les gains d'antenne et la
convention PIRE/PAR sont quatre choses distinctes, que les conversions sont exactes, et
que la valeur par défaut de la passerelle n'a pas bougé (compatibilité des scénarios).

Les seuils réglementaires sont ceux du tableau ETSI EN 300 220-2 V3.2.1, annexe B,
table B.1, tels que transcrits dans `lsim.regions.EU868`.
"""

from __future__ import annotations

import math

import pytest
import yaml

from lsim import power
from lsim.power import (GATEWAY_TX_POWER_DEFAULT_DBM, GATEWAY_TX_POWER_MAX_DBM,
                        TxChain, applicable_bands, device_tx, duty_cycle_limit,
                        eirp_from_erp, erp_from_eirp, gateway_tx, mw_to_dbm)
from lsim.regions import PROFILES
from lsim.scenario import load_scenario
from lsim.trace_events import ProtocolOptions

NOMINAL = "docs/exemples/retransmissions_nominal.yaml"
RX2_EU868 = 869_525_000       # repli régional EU868 (RP002-1.0.5, p. 38)
RX2_SF12_AIRTIME_JOIN_NS = 1_810_432_000  # mesuré en A5 (33 octets, SF12/BW125)


# ------------------------------------------------------------------ conversions

def test_erp_est_la_pire_moins_2_15_db():
    assert erp_from_eirp(14.0) == pytest.approx(11.85)
    assert eirp_from_erp(11.85) == pytest.approx(14.0)
    for valeur in (-10.0, 0.0, 14.0, 16.13, 27.0):
        assert eirp_from_erp(erp_from_eirp(valeur)) == pytest.approx(valeur)


def test_conversion_mw_dbm_des_paliers_etsi():
    assert mw_to_dbm(25.0) == pytest.approx(13.979400086720375)
    assert mw_to_dbm(500.0) == pytest.approx(26.989700043360187)
    assert mw_to_dbm(5.0) == pytest.approx(6.9897000433601875)
    with pytest.raises(ValueError):
        mw_to_dbm(0.0)


# ---------------------------------------------------------------------- TxChain

def test_la_chaine_n_est_comptee_qu_une_seule_fois():
    tx = TxChain(14.0, antenna_gain_dbi=2.15, cable_loss_db=1.0)
    assert tx.chain_db == pytest.approx(1.15)
    assert tx.eirp_dbm == pytest.approx(15.15)
    assert tx.erp_dbm == pytest.approx(13.0)


def test_from_eirp_et_from_erp_sont_inverses():
    for eirp, gain, perte in ((14.0, 0.0, 0.0), (27.0, 2.15, 1.0), (16.13, 5.0, 2.0)):
        tx = TxChain.from_eirp(eirp, gain, perte)
        assert tx.eirp_dbm == pytest.approx(eirp)
        tx2 = TxChain.from_erp(erp_from_eirp(eirp), gain, perte)
        assert tx2.eirp_dbm == pytest.approx(eirp)
        assert tx2.conducted_dbm == pytest.approx(tx.conducted_dbm)


def test_une_chaine_invalide_est_refusee():
    with pytest.raises(ValueError):
        TxChain(float("nan"))
    with pytest.raises(ValueError):
        TxChain(14.0, cable_loss_db=-1.0)


# ---------------------------------------------------- sélection des sous-bandes

def test_le_defaut_passerelle_tombe_dans_la_bande_o():
    """14 dBm conduits sans gain : PAR 15,3 mW, sous la limite de 25 mW de la bande O."""
    tx = TxChain(GATEWAY_TX_POWER_DEFAULT_DBM)
    assert tx.eirp_dbm == pytest.approx(14.0)
    assert tx.erp_mw == pytest.approx(15.311, abs=1e-3)
    assert [b.name for b in applicable_bands(PROFILES["EU868"], RX2_EU868, tx)] == ["O", "P"]
    assert duty_cycle_limit(PROFILES["EU868"], RX2_EU868, tx) == pytest.approx(0.001)


def test_le_plafond_constructeur_tombe_dans_la_bande_p():
    """27 dBm conduits sans gain : PAR 305 mW, au-dessus des 25 mW de O, sous les 500 mW de P."""
    tx = TxChain(GATEWAY_TX_POWER_MAX_DBM)
    assert [b.name for b in applicable_bands(PROFILES["EU868"], RX2_EU868, tx)] == ["P"]
    assert duty_cycle_limit(PROFILES["EU868"], RX2_EU868, tx) == pytest.approx(0.10)


def test_le_basculement_o_p_se_fait_a_25_mw_de_par():
    """Seuil exact : PAR = 25 mW, soit PIRE = 16,1294 dBm. De part et d'autre, la limite change."""
    seuil = eirp_from_erp(mw_to_dbm(25.0))
    assert seuil == pytest.approx(16.129400086720375)
    eu = PROFILES["EU868"]
    juste_en_dessous = TxChain.from_eirp(seuil - 1e-6)
    juste_au_dessus = TxChain.from_eirp(seuil + 1e-3)
    assert [b.name for b in applicable_bands(eu, RX2_EU868, juste_en_dessous)] == ["O", "P"]
    assert [b.name for b in applicable_bands(eu, RX2_EU868, juste_au_dessus)] == ["P"]
    assert duty_cycle_limit(eu, RX2_EU868, juste_en_dessous) == pytest.approx(0.001)
    assert duty_cycle_limit(eu, RX2_EU868, juste_au_dessus) == pytest.approx(0.10)


def test_la_pire_maximale_eu868_reste_sous_le_seuil_o_p():
    """Le plafond du plan EU868 (16 dBm PIRE, RP002) reste en bande O : 0,1 %, pas 10 %."""
    tx = TxChain.from_eirp(16.0)
    assert [b.name for b in applicable_bands(PROFILES["EU868"], RX2_EU868, tx)] == ["O", "P"]
    assert duty_cycle_limit(PROFILES["EU868"], RX2_EU868, tx) == pytest.approx(0.001)


def test_une_emission_hors_plan_leve_une_erreur():
    """869,850 MHz : bandes Q (25 mW) et QP (5 mW) ; 27 dBm PIRE n'entre dans aucune."""
    with pytest.raises(ValueError, match="hors plan"):
        duty_cycle_limit(PROFILES["EU868"], 869_850_000, TxChain.from_eirp(27.0))


def test_les_bandes_etsi_sont_exprimees_en_par():
    """La sélection se fait sur la PAR : la même PIRE en EIRP serait acceptée à 25 mW."""
    eu = PROFILES["EU868"]
    tx = TxChain.from_erp(mw_to_dbm(25.0))          # PAR exactement au plafond de O
    assert [b.name for b in applicable_bands(eu, RX2_EU868, tx)] == ["O", "P"]
    # 25 mW lus comme une PIRE : 13,979 dBm PIRE, soit 11,829 dBm PAR = 15,24 mW.
    tx_eirp = TxChain.from_eirp(mw_to_dbm(25.0))
    assert [b.name for b in applicable_bands(eu, RX2_EU868, tx_eirp)] == ["O", "P"]
    assert tx_eirp.erp_mw == pytest.approx(15.238, abs=1e-3)
    assert tx_eirp.eirp_mw == pytest.approx(25.0, abs=1e-6)


# ------------------------------------------------- configuration de la passerelle

def test_la_valeur_par_defaut_ne_bouge_pas():
    assert ProtocolOptions().gateway_tx_power_dbm == 14.0
    assert GATEWAY_TX_POWER_DEFAULT_DBM == 14.0
    assert GATEWAY_TX_POWER_MAX_DBM == 27.0


def test_sans_puissance_declarée_la_passerelle_prend_la_valeur_du_protocole():
    data = yaml.safe_load(open(NOMINAL, encoding="utf-8"))
    scenario = load_scenario(yaml.safe_dump(data))
    tx = gateway_tx(scenario.gateway())
    assert tx.conducted_dbm == 14.0
    assert tx.eirp_dbm == pytest.approx(14.0)


def test_la_puissance_declarée_dans_le_scenario_est_conduite():
    """`gateway.tx_power_dbm` est conduite en sortie d'émetteur : le gain s'ajoute."""
    data = yaml.safe_load(open(NOMINAL, encoding="utf-8"))
    data["gateway"]["tx_power_dbm"] = 27
    data["gateway"]["antenna_gain_dbi"] = 2.15
    scenario = load_scenario(yaml.safe_dump(data))
    tx = gateway_tx(scenario.gateway())
    assert tx.conducted_dbm == 27.0
    assert tx.antenna_gain_dbi == pytest.approx(2.15)
    assert tx.eirp_dbm == pytest.approx(29.15)


def test_le_frontal_rf_remplace_le_gain_scalaire():
    data = yaml.safe_load(open(NOMINAL, encoding="utf-8"))
    data["gateway"]["rx"] = None
    data["gateway"].pop("rx", None)
    data["gateway"]["rf"] = {"antenna_gain_dbi": 5.0, "cable_loss_db": 1.5}
    scenario = load_scenario(yaml.safe_dump(data))
    tx = gateway_tx(scenario.gateway())
    assert tx.antenna_gain_dbi == pytest.approx(5.0)
    assert tx.cable_loss_db == pytest.approx(1.5)
    assert tx.eirp_dbm == pytest.approx(14.0 + 5.0 - 1.5)


def test_le_repli_est_parametrable():
    scenario = load_scenario(open(NOMINAL, encoding="utf-8").read())
    assert gateway_tx(scenario.gateway(), fallback_dbm=27.0).conducted_dbm == 27.0


def test_les_bornes_de_puissance_sont_validees():
    data = yaml.safe_load(open(NOMINAL, encoding="utf-8"))
    data["gateway"]["tx_power_dbm"] = 30
    with pytest.raises(Exception):
        load_scenario(yaml.safe_dump(data))


def test_un_scenario_sans_puissance_garde_son_empreinte():
    """La puissance absente est retirée du hachage : l'empreinte du scénario ne bouge pas."""
    source = open(NOMINAL, encoding="utf-8").read()
    sans = load_scenario(source).sha256
    data = yaml.safe_load(source)
    data["gateway"]["tx_power_dbm"] = None
    assert load_scenario(yaml.safe_dump(data)).sha256 == sans
    data["gateway"]["tx_power_dbm"] = 20
    assert load_scenario(yaml.safe_dump(data)).sha256 != sans


# -------------------------------------------------------- puissance du terminal

def test_la_puissance_du_terminal_reste_distincte_de_celle_de_la_passerelle():
    data = yaml.safe_load(open(NOMINAL, encoding="utf-8"))
    data["gateway"]["tx_power_dbm"] = 27
    scenario = load_scenario(yaml.safe_dump(data))
    groupe = scenario.model.groups[0]
    assert device_tx(groupe).conducted_dbm == pytest.approx(groupe.tx_power_dbm) == 14.0
    assert gateway_tx(scenario.gateway()).conducted_dbm == 27.0
    assert device_tx(groupe).eirp_dbm != gateway_tx(scenario.gateway()).eirp_dbm


def test_la_pire_d_un_groupe_avec_frontal_inclut_la_chaine():
    data = yaml.safe_load(open(NOMINAL, encoding="utf-8"))
    data["groups"][0]["rf"] = {"antenna_gain_dbi": 2.0, "cable_loss_db": 0.5}
    scenario = load_scenario(yaml.safe_dump(data))
    tx = device_tx(scenario.model.groups[0])
    assert tx.conducted_dbm == pytest.approx(14.0)
    assert tx.eirp_dbm == pytest.approx(15.5)


def test_un_groupe_sans_frontal_garde_la_comparaison_historique():
    """Sans bloc `rf`, chaîne nulle : la PIRE égale la puissance conduite déclarée."""
    scenario = load_scenario(open(NOMINAL, encoding="utf-8").read())
    groupe = scenario.model.groups[0]
    assert groupe.rf is None
    assert device_tx(groupe).eirp_dbm == pytest.approx(groupe.tx_power_dbm)


# ------------------------------------------------- portée réglementaire du lien

def test_le_temps_de_liberation_depend_de_la_bande():
    """Conséquence directe : à 0,1 % un Join-Accept RX2 impose ~30 min d'attente, à 10 % ~16 s."""
    join_rx2_s = RX2_SF12_AIRTIME_JOIN_NS / 1e9
    basse = TxChain(GATEWAY_TX_POWER_DEFAULT_DBM)
    haute = TxChain(GATEWAY_TX_POWER_MAX_DBM)
    eu = PROFILES["EU868"]
    attente_o = join_rx2_s * (1 / duty_cycle_limit(eu, RX2_EU868, basse) - 1)
    attente_p = join_rx2_s * (1 / duty_cycle_limit(eu, RX2_EU868, haute) - 1)
    assert attente_o == pytest.approx(1808.6, abs=0.5)   # ~30 min
    assert attente_p == pytest.approx(16.29, abs=0.05)   # ~16 s
    assert math.isfinite(attente_o) and math.isfinite(attente_p)
