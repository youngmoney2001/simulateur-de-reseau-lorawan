"""RX1DROffset — table RX1 à deux dimensions (I5-c).

Avant ce lot, `Plan.rx1()` lisait une table **plate** `DR montant -> DR RX1`, c'est-à-dire la
colonne RX1DROffset = 0. Un terminal réglé sur un offset non nul recevait donc une descente
calculée à l'offset 0 : le serveur acquittait `RXParamSetupReq` sans l'appliquer.

Valeurs de référence : `docs/I5_C_RX1_DROFFSET.md` §7.2, issues de RP002-1.0.4 telles que
transcrites indépendamment par LoRaMac-node v4.7.1 (Lora-net) et lorawan-stack v3.37.0 (TTI),
concordantes sur US915 et AU915.
"""

import re

import pytest

from lsim.plan import Rx1DrOffsetOutOfRangeError, get_plan

# (SF, bande en Hz) d'un débit « SF12BW500 »
def _sf_bw(datr):
    m = re.match(r"^SF(\d+)BW(\d+)$", datr)
    return int(m.group(1)), int(m.group(2)) * 1000


# RP002-1.0.4, `DatarateOffsetsUS915[5][4]` : colonnes = offsets 0..3, lignes = DR 0..4.
US915_TABLE = {
    0: (10, 9, 8, 8),
    1: (11, 10, 9, 8),
    2: (12, 11, 10, 9),
    3: (13, 12, 11, 10),
    4: (13, 13, 12, 11),
}

# Bornes d'offset par région.
OFFSET_MAX = {"EU868": 5, "US915": 3, "AU915": 5, "AS923": 5,
              "IN865": 5, "KR920": 5, "RU864": 5}


# ---------------------------------------------------------------------------
# T-C-1 — non-régression : l'offset 0 reproduit exactement l'ancien comportement
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("region", sorted(OFFSET_MAX))
def test_offset_zero_reproduit_l_ancienne_table(region):
    """La colonne 0 est celle que le serveur utilisait déjà, avant la table à deux dimensions."""
    plan = get_plan(region)
    for dr in sorted(plan._uplink_datr.values()):
        # L'appel historique, sans argument d'offset, doit rester valide et identique.
        assert plan.rx1(dr, 0) == plan.rx1(dr, 0, 0)


@pytest.mark.parametrize("region", sorted(OFFSET_MAX))
def test_rx1_reste_appelable_sans_offset(region):
    """`rx1_dr_offset` est optionnel : aucun appelant existant n'a besoin d'être modifié."""
    plan = get_plan(region)
    dr = min(plan._uplink_datr.values())
    freq_mhz, datr = plan.rx1(dr, 0)
    assert freq_mhz > 0
    assert _sf_bw(datr)[0] >= 7


# ---------------------------------------------------------------------------
# T-C-2 — parité de la table complète, pas seulement de l'offset 0
# ---------------------------------------------------------------------------

def test_us915_table_complete_par_offset():
    """Un test qui ne vérifierait que l'offset 0 laisserait passer une colonne entière fausse."""
    plan = get_plan("US915")
    for dr, colonne in US915_TABLE.items():
        for offset, attendu in enumerate(colonne):
            assert plan.rx1_dr_for(dr, offset) == attendu, (
                f"US915 DR{dr} offset {offset} : DR{plan.rx1_dr_for(dr, offset)} "
                f"au lieu de DR{attendu}")
    assert plan.rx1_dr_offset_max == 3


@pytest.mark.parametrize("region", sorted(OFFSET_MAX))
def test_la_borne_d_offset_vit_avec_les_donnees(region):
    """La borne n'est pas déclarée deux fois : elle se déduit de la largeur des lignes."""
    assert get_plan(region).rx1_dr_offset_max == OFFSET_MAX[region]


@pytest.mark.parametrize("region", sorted(OFFSET_MAX))
def test_offset_non_nul_ne_sort_jamais_du_plan(region):
    """Pour tout offset admis, le DR RX1 doit exister dans la table descendante de la région."""
    plan = get_plan(region)
    for dr in sorted(plan._uplink_datr.values()):
        for offset in range(plan.rx1_dr_offset_max + 1):
            rx1_dr = plan.rx1_dr_for(dr, offset)
            assert rx1_dr in plan._downlink_datr, (
                f"{region} DR{dr} offset {offset} -> DR{rx1_dr} absent du plan descendant")


# ---------------------------------------------------------------------------
# T-C-3 — refus explicite hors bornes, avec contrôle positif
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("region", sorted(OFFSET_MAX))
def test_offset_hors_bornes_est_refuse(region):
    plan = get_plan(region)
    borne = OFFSET_MAX[region]
    # Contrôle négatif.
    with pytest.raises(Rx1DrOffsetOutOfRangeError) as exc:
        plan.rx1_dr_for(0, borne + 1)
    assert region in str(exc.value)
    # Contrôle positif : dans les bornes, la même construction réussit.
    assert isinstance(plan.rx1_dr_for(0, borne), int)


def test_refus_nomme_la_region_et_la_borne():
    """Le message doit être actionnable : quelle région, quelle borne."""
    with pytest.raises(Rx1DrOffsetOutOfRangeError, match=r"US915.*0\.\.3"):
        get_plan("US915").rx1_dr_for(0, 4)


@pytest.mark.parametrize("region", sorted(OFFSET_MAX))
def test_rx1_refuse_aussi_hors_bornes(region):
    """Le refus doit atteindre l'API publique, pas seulement l'accesseur interne."""
    with pytest.raises(Rx1DrOffsetOutOfRangeError):
        get_plan(region).rx1(0, 0, OFFSET_MAX[region] + 1)


# ---------------------------------------------------------------------------
# T-C-4 — effet physique : le SF et la bande suivent l'offset, pas seulement le DR
# ---------------------------------------------------------------------------

def test_us915_offset_change_le_sf_de_rx1():
    """US915 DR0 : SF10/500 à l'offset 0, SF11/500 à l'offset 1, SF12/500 à l'offset 2.

    Le piège d'I5-b était de vérifier le DR et pas la modulation : un test qui ne regarde
    que l'indice de débit peut passer alors que le SF produit est faux.
    """
    plan = get_plan("US915")
    attendu = {0: (10, 500_000), 1: (11, 500_000), 2: (12, 500_000), 3: (12, 500_000)}
    for offset, (sf, bw) in attendu.items():
        _, datr = plan.rx1(0, 0, offset)
        assert _sf_bw(datr) == (sf, bw), (
            f"US915 DR0 offset {offset} : {datr} au lieu de SF{sf}/{bw // 1000}")


def test_eu868_offset_change_le_sf_de_rx1():
    """EU868 `clamp(dr - offset, 0, 7)` : DR5 -> SF7 à l'offset 0, SF12 à l'offset 5."""
    plan = get_plan("EU868")
    attendu = {0: (7, 125_000), 1: (8, 125_000), 2: (9, 125_000),
               3: (10, 125_000), 4: (11, 125_000), 5: (12, 125_000)}
    for offset, (sf, bw) in attendu.items():
        _, datr = plan.rx1(5, 0, offset)
        assert _sf_bw(datr) == (sf, bw), (
            f"EU868 DR5 offset {offset} : {datr} au lieu de SF{sf}/{bw // 1000}")


def test_kr920_le_plafond_de_clamp_est_inobservable_depuis_les_montants():
    """KR920 plafonne à DR5, les autres régions arithmétiques à DR7 — mais cela ne se voit pas.

    Les DR montants de KR920 vont de 0 à 5. Comme `RX1_DR = clamp(DR − offset, 0, dr_max)` et
    que `DR − offset <= 5` quel que soit l'offset, le plafond n'est jamais atteint : un
    plafond de 7 produirait exactement les mêmes valeurs. La différence n'est donc pas
    testable depuis les seules montantes, et ce test le constate au lieu de le simuler.

    Elle ne deviendrait observable que si le serveur admettait un DR montant supérieur à 5
    dans KR920, ce qui n'est pas le cas.
    """
    plan = get_plan("KR920")
    assert max(plan._uplink_datr.values()) == 5
    for dr in sorted(plan._uplink_datr.values()):
        for offset in range(plan.rx1_dr_offset_max + 1):
            # Le plafond 5 vs 7 est sans effet : la valeur est déjà bornee par `dr - offset`.
            assert plan.rx1_dr_for(dr, offset) == max(0, dr - offset)
    # La profondeur, elle, est bien observable.
    assert plan.rx1_dr_for(5, 5) == 0
    assert plan.rx1_dr_for(5, 0) == 5


# ---------------------------------------------------------------------------
# T-C-5 — la borne de file suit l'offset
# ---------------------------------------------------------------------------

def test_la_limite_de_file_suit_l_offset():
    """US915 : DR8 (N = 53) n'est atteint qu'à partir de l'offset 2.

    La propriété `queue_payload_max` garde le sens historique (offset 0) pour ne rien
    changer au comportement par défaut ; c'est `queue_payload_max_for` qui suit l'offset.
    """
    plan = get_plan("US915")
    assert plan.queue_payload_max == 222                 # offset 0, inchangé
    assert plan.queue_payload_max_for(0) == 222
    assert plan.queue_payload_max_for(1) == 129
    assert plan.queue_payload_max_for(2) == 53
    assert plan.queue_payload_max_for(3) == 53


# ---------------------------------------------------------------------------
# T-C-6 — réglage de déploiement : l'offset du groupe atteint la radio du terminal
# ---------------------------------------------------------------------------

def _scenario(region: str, rx1_dr_offset=None, sf: int = 9):
    """Scénario minimal d'un groupe de 4 terminaux, avec ou sans RX1DROffset."""
    from lsim.plan import get_plan
    from lsim.scenario import Scenario, ScenarioModel
    from lsim.trace_events import ProtocolOptions, build_trace  # noqa: F401

    ch = get_plan(region).uplink_channels_hz()[0]
    group = {
        "name": "g0", "count": 4, "region": region, "channel_freq_hz": ch,
        "placement": {"type": "disk", "radius_m": 1500.0},
        "spreading_factor": sf, "payload_bytes": 20, "tx_power_dbm": 14.0,
        "period_s": 900, "messages": 3, "start_spread_s": 900,
    }
    if rx1_dr_offset is not None:
        group["rx1_dr_offset"] = rx1_dr_offset
    return Scenario(ScenarioModel.model_validate({
        "schema_version": 1, "name": "m", "seed": 1,
        "gateway": {"x_m": 0, "y_m": 0, "antenna_gain_dbi": 2.15},
        "groups": [group],
    }))


@pytest.mark.parametrize("offset,sf_attendu", [(0, 9), (1, 10), (2, 11), (3, 12), (4, 12), (5, 12)])
def test_eu868_l_offset_du_groupe_change_le_sf_de_rx1(offset, sf_attendu):
    """Bout en bout : EU868 SF9 (DR3), `RX1_DR = clamp(3 - offset, 0, 7)`.

    offsets 3, 4 et 5 donnent tous DR0 (SF12) : la saturation du clamp est volontaire et
    conforme, ce n'est pas un écrasement de borne.
    """
    radio = _radio_of("EU868", offset)
    assert radio.rx1_sf == sf_attendu
    assert radio.rx1_bw_hz == 125_000


@pytest.mark.parametrize("offset,sf_attendu", [(0, 9), (1, 10), (2, 11), (3, 12)])
def test_us915_l_offset_du_groupe_change_le_sf_et_garde_la_bande(offset, sf_attendu):
    """US915 : la bande descendante (500 kHz) ne bouge pas, seul le SF suit l'offset."""
    radio = _radio_of("US915", offset)
    assert radio.rx1_sf == sf_attendu
    assert radio.rx1_bw_hz == 500_000


def _radio_of(region: str, offset):
    from lsim.trace_events import device_radios
    return device_radios(_scenario(region, offset))[0]


def test_sans_offset_le_comportement_est_inchange():
    """Contrôle positif : sans le champ, on retrouve exactement l'ancien comportement."""
    from lsim.trace_events import device_radios
    assert device_radios(_scenario("EU868"))[0].rx1_sf == 9
    assert device_radios(_scenario("EU868", 0))[0].rx1_sf == 9


def test_offset_hors_bornes_regionales_refuse_a_la_lecture_du_scenario():
    """US915 n'admet que 0..3 ; le refus a lieu à la lecture, pas à la simulation."""
    import pydantic
    with pytest.raises(pydantic.ValidationError, match="RX1DROffset 4"):
        _scenario("US915", 4)
    # Contrôle positif : 3 est accepté.
    assert _scenario("US915", 3) is not None


def test_le_hash_du_scenario_exclut_l_offset_par_defaut():
    """Un scénario écrit avant l'introduction du champ garde la même empreinte."""
    assert _scenario("EU868").sha256 == _scenario("EU868", 0).sha256
    # Un offset non nul, lui, change l'empreinte : c'est une configuration différente.
    assert _scenario("EU868").sha256 != _scenario("EU868", 2).sha256


# ---------------------------------------------------------------------------
# T-S-1..T-S-3 — chemin scenario : les deux regimes (§14)
#
# Sans ADR, le moteur suit la table de radios, que Python calcule avec l'offset : l'offset
# atteint la descente. Avec LinkADR, le DR courant du terminal prime, la table est ignoree, et
# le chemin scenario ne peut pas transmettre l'offset (§14.2) : il est refuse explicitement
# plutot qu'ignore en silence (arbitrage bbb3).
#
# Observable : `TraceRun.gateway_tx`, les intervalles d'emission de la passerelle. Avec un seul
# terminal sans contention, leur longueur est exactement l'airtime de la descente RX1.
# ---------------------------------------------------------------------------

def _scenario_mac(rx1_dr_offset, mac, count=1, messages=1):
    """Scenario EU868 minimal, un groupe, avec un bloc `mac:`."""
    from lsim.plan import get_plan
    from lsim.scenario import Scenario, ScenarioModel

    ch = get_plan("EU868").uplink_channels_hz()[0]
    group = {
        "name": "g0", "count": count, "region": "EU868", "channel_freq_hz": ch,
        "placement": {"type": "disk", "radius_m": 100.0},
        "spreading_factor": 9, "payload_bytes": 20, "tx_power_dbm": 14.0,
        "period_s": 3600, "messages": messages,
    }
    if rx1_dr_offset is not None:
        group["rx1_dr_offset"] = rx1_dr_offset
    return Scenario(ScenarioModel.model_validate({
        "schema_version": 1, "name": "m", "seed": 1,
        "gateway": {"x_m": 0, "y_m": 0, "antenna_gain_dbi": 2.15},
        "groups": [group], "mac": mac,
    }))


def _airtime_descente(scenario, options=None):
    """Longueur de la premiere emission de la passerelle (= airtime de la descente RX1).

    LinkADR seul ne cree aucune descente quand il n y a rien a emettre : il faut des
    uplinks confirmes pour en obtenir une (voir T-S-3).
    """
    from lsim.trace_events import ProtocolOptions, build_trace_closed_loop

    run = build_trace_closed_loop(scenario, options or ProtocolOptions())
    assert run.gateway_tx, "aucune emission de la passerelle : la descente n a pas eu lieu"
    debut, fin = run.gateway_tx[0]
    return fin - debut


# Airtimes mesures (ns) : un pas de SF double l'airtime. Controle positif obligatoire
# (dixieme garde-fou) : le test n'affirme pas « ca change », mais « chaque pas le double ».
AIRTIMES = {0: 144_384_000, 1: 288_768_000, 2: 577_536_000, 3: 1_155_072_000}


@pytest.mark.parametrize("offset", [0, 1, 2, 3])
def test_adr_inactif_l_offset_allonge_la_descente(offset):
    """T-S-1 : sans ADR, l'offset atteint la descente - clamp(DR3 - offset, 0, 5)."""
    assert _airtime_descente(_scenario_mac(offset, {"duty_cycle_exponent": 1})) == AIRTIMES[offset]


def test_adr_inactif_la_descente_croit_avec_l_offset():
    """T-S-1 bis : relation strictement croissante, interdit un decrochage partiel."""
    precedent = 0
    for offset in range(4):
        air = _airtime_descente(_scenario_mac(offset, {"duty_cycle_exponent": 1}))
        assert air > precedent
        precedent = air


@pytest.mark.parametrize("offset", [1, 2, 3, 4, 5])
def test_adr_actif_avec_offset_non_nul_est_refuse(offset):
    """T-S-2 : avec LinkADR l'offset serait ignore en silence - refus explicite (bbb3)."""
    with pytest.raises(ValueError, match="RX1DROffset"):
        _airtime_descente(_scenario_mac(offset, {"link_adr": True}))


def test_adr_actif_sans_offset_est_accepte():
    """T-S-3 : controle positif - LinkADR sans offset reste accepte, aucune regression.

    Uplinks confirmes : sans eux, LinkADR n a rien a emettre, il n y a aucune descente a
    mesurer et le test passerait pour rien.
    """
    from lsim.trace_events import ProtocolOptions

    air = _airtime_descente(_scenario_mac(None, {"link_adr": True}),
                             ProtocolOptions(confirmed_uplinks=True))
    # L ADR n a pas encore deplore le SF au premier uplink : airtime de SF9.
    assert air == AIRTIMES[0]
