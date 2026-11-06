"""P1 — refus explicite d'une configuration radio sans DR montant.

Décision P1 : quand un (région, SF, bande) ne correspond à aucun DR montant du plan, la
radio est **refusée avant la simulation**. Aucun DR de substitution n'est inventé, et aucun
repli silencieux vers une modulation générique ne subsiste — c'est précisément le
comportement que `UnsupportedUplinkDataRateError` remplace.

Ces tests sont **ajoutés** : aucun test existant n'est modifié.
"""

from __future__ import annotations

import pytest

from lsim.plan import UnsupportedUplinkDataRateError, get_plan
from lsim.trace_events import _radio


# ------------------------------------------------------------------ contrat d'erreur (O2)

def test_l_exception_herite_de_value_error():
    """Un appelant qui intercepte `ValueError` reste correct : le contrat n'est pas rompu."""
    assert issubclass(UnsupportedUplinkDataRateError, ValueError)


def test_l_exception_expose_la_region_le_sf_et_le_contexte():
    """Région, SF demandé et SF disponibles : le diagnostic doit être actionnable."""
    with pytest.raises(UnsupportedUplinkDataRateError) as exc:
        _radio(get_plan("US915"), 903_900_000, 11, 14.0)
    e = exc.value
    assert e.region == "US915"
    assert e.spreading_factor == 11
    assert e.bandwidth_hz == 125_000
    assert e.available == (7, 8, 9, 10)
    assert "US915" in str(e) and "SF11" in str(e)
    for sf in e.available:
        assert f"SF{sf}" in str(e)


# ------------------------------------------------------------------ le refus

@pytest.mark.parametrize("region, sf, attendus", [
    # US915 : montants SF10, SF9, SF8, SF7 — SF11 n'existe qu'en **descendant** (DR9).
    ("US915", 11, (7, 8, 9, 10)),
    ("US915", 12, (7, 8, 9, 10)),
    # EU868 : montants SF7 à SF12 — SF5 et SF6 n'y figurent pas.
    ("EU868", 5, (7, 8, 9, 10, 11, 12)),
    ("EU868", 6, (7, 8, 9, 10, 11, 12)),
])
def test_un_sf_sans_dr_montant_est_refuse(region, sf, attendus):
    with pytest.raises(UnsupportedUplinkDataRateError) as exc:
        _radio(get_plan(region), 868_100_000, sf, 14.0)
    assert exc.value.available == attendus


def test_le_refus_precede_la_simulation():
    """Le refus a lieu à la construction de la radio, jamais pendant la planification."""
    plan = get_plan("US915")
    # `_radio` est le constructeur de radio : s'il lève, aucune chronologie n'a été bâtie.
    with pytest.raises(UnsupportedUplinkDataRateError):
        _radio(plan, 903_900_000, 11, 14.0)


# ------------------------------------------------------------------ ce qui reste licite

@pytest.mark.parametrize("region, sf", [
    ("US915", 7), ("US915", 8), ("US915", 9), ("US915", 10),
    ("EU868", 11), ("EU868", 12),
    ("AU915", 11), ("IN865", 7), ("KR920", 9), ("RU864", 10), ("AS923", 7),
])
def test_un_sf_conforme_n_est_pas_refuse(region, sf):
    """Garde-fou : P1 ne doit pas rejeter ce qui est valide."""
    radio = _radio(get_plan(region), 868_100_000, sf, 14.0)
    assert radio.dr is not None


def test_sans_region_aucun_refus():
    """Sans plan il n'y a pas de N, donc rien à résoudre : le cas reste licite."""
    radio = _radio(None, 868_100_000, 11, 14.0)
    assert radio.dr is None and radio.rx1_sf == 11


def test_les_sept_regions_couvrent_les_sf_de_reference():
    """Contrôle de non-régression : les SF employés par les scènes sont tous valides,
    **sauf** US915 à SF11, qui est l'anomalie que P1 révèle et que la migration D3.15
    corrige (SF 11 → 10)."""
    scenes = {"EU868": 11, "US915": 11, "AS923": 7, "AU915": 7,
              "IN865": 7, "KR920": 9, "RU864": 10}
    refuses = []
    for region, sf in scenes.items():
        try:
            _radio(get_plan(region), 868_100_000, sf, 14.0)
        except UnsupportedUplinkDataRateError:
            refuses.append(region)
    assert refuses == ["US915"]
