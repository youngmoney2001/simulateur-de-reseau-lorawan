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
