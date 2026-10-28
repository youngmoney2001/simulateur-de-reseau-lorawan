"""Profils régionaux : validation, règle du plus restrictif, profil EU868."""

import math

import pytest

from lsim.regions import EU868, PROFILES, RegionProfile, SubBand, erp_from_eirp, load_profile

TEST_BANDS = (
    SubBand("A", 863_000_000, 865_000_000, 0.001, 14.0),
    SubBand("B", 865_000_001, 868_000_000, 0.01, 14.0),
)


def test_profile_requires_official_source():
    with pytest.raises(ValueError):
        load_profile("XX", None, TEST_BANDS)
    with pytest.raises(ValueError):
        load_profile("XX", "   ", TEST_BANDS)
    assert load_profile("XX", "source de test", TEST_BANDS).code == "XX"


def test_band_lookup_and_outside_plan():
    prof = load_profile("XX", "source de test", TEST_BANDS)
    assert prof.band_for(864_000_000, 10.0).name == "A"
    assert prof.band_for(866_000_000, 10.0).name == "B"
    assert prof.band_for(900_000_000, 10.0) is None
    with pytest.raises(ValueError):
        prof.duty_cycle_for(900_000_000, 14.0)


def test_most_restrictive_applicable_band_wins():
    prof = RegionProfile("XX", "src", (
        SubBand("LOOSE", 863_000_000, 870_000_000, 0.10, 27.0),
        SubBand("TIGHT", 868_000_000, 868_600_000, 0.01, 14.0),
    ))
    # Dans les deux sous-bandes : la plus restrictive gouverne.
    assert prof.band_for(868_100_000, 10.0).name == "TIGHT"
    # Puissance au-dessus de la PIRE de TIGHT : seule LOOSE s'applique.
    assert prof.band_for(868_100_000, 20.0).name == "LOOSE"


@pytest.mark.parametrize("dc", [0.0, -0.1, 1.5, float("nan")])
def test_invalid_duty_cycle_refused(dc):
    with pytest.raises(ValueError):
        SubBand("A", 863_000_000, 865_000_000, dc, 14.0)


def test_invalid_frequency_bounds_refused():
    with pytest.raises(ValueError):
        SubBand("A", 865_000_000, 863_000_000, 0.01, 14.0)
    with pytest.raises(ValueError):
        SubBand("A", 863.0e6, 865_000_000, 0.01, 14.0)  # float refusé


# ------------------------------------------------------------------- EU868

def test_eu868_is_registered_with_full_source():
    assert PROFILES["EU868"] is EU868
    assert "ETSI EN 300 220-2 V3.2.1" in EU868.source
    assert "RP002" in EU868.source


@pytest.mark.parametrize("freq", [868_100_000, 868_300_000, 868_500_000])
def test_eu868_default_channels_are_one_percent(freq):
    # Canaux par défaut (RP002 §2.4.2) : sous-bande M, 1 % à 16 dBm EIRP.
    assert EU868.duty_cycle_for(freq, 16.0) == pytest.approx(0.01)


def test_eu868_rx2_is_most_restrictive_subband_at_869_525():
    # RX2 869,525 MHz (RP002 §2.4.8) : sous-bandes O (0,1 %) et P (10 %) se recouvrent.
    # Une émission à 16 dBm EIRP (ERP 13,85 dBm) reste dans O ; P exige plus de 25 mW.
    band = EU868.band_for(869_525_000, erp_from_eirp(16.0))
    assert band.name in {"O", "P", "QP"}
    assert EU868.duty_cycle_for(869_525_000, 16.0) == pytest.approx(0.001)


def test_eu868_p_band_requires_high_power():
    # Au-delà de 25 mW ERP, seule la sous-bande P (500 mW) s'applique.
    band = EU868.band_for(869_500_000, 20.0)
    assert band.name == "P"
    assert band.duty_cycle == pytest.approx(0.10)


def test_eu868_max_eirp_is_within_25mw_erp():
    # EIRP maximal 16 dBm => ERP 13,85 dBm, sous 25 mW (13,98 dBm).
    assert erp_from_eirp(16.0) <= 10 * math.log10(25.0)


def test_eu868_gap_between_subbands_is_outside_plan():
    # 869,2 à 869,4 MHz : aucune sous-bande dans la table ETSI.
    assert EU868.band_for(869_300_000, 10.0) is None


def test_eu868_boundary_865_uses_most_restrictive():
    # 865,0 MHz : appartient à K (0,1 %) et à L (1 %) ; K gouverne.
    assert EU868.duty_cycle_for(865_000_000, 14.0) == pytest.approx(0.001)


# -------------------------------------------- liaison scénario -> profil régional

def _group(**kw):
    from lsim.scenario import DiskPlacement, GroupModel
    base = dict(name="g", count=1, placement=DiskPlacement(type="disk", radius_m=10))
    base.update(kw)
    return GroupModel(**base)


def test_group_without_region_keeps_declared_duty_cycle():
    assert _group(duty_cycle=0.5).effective_duty_cycle == 0.5


def test_group_region_applies_subband_duty_cycle():
    g = _group(region="EU868", channel_freq_hz=868_100_000, tx_power_dbm=14.0)
    assert g.effective_duty_cycle == pytest.approx(0.01)


def test_group_region_takes_most_restrictive_of_declared_and_band():
    g = _group(region="EU868", channel_freq_hz=868_100_000, duty_cycle=0.005)
    assert g.effective_duty_cycle == pytest.approx(0.005)


def test_group_region_rejects_channel_outside_plan():
    with pytest.raises(ValueError):
        _group(region="EU868", channel_freq_hz=900_000_000)


def test_group_unknown_region_rejected():
    with pytest.raises(ValueError):
        _group(region="US915", channel_freq_hz=868_100_000)


# ------------------------------------------- plans de canaux RP002-1.0.0

import pytest as _pt  # noqa: E402  (import local aux blocs de canaux)
from lsim.regions import DiscreteChannel, US915, AU915, AS923, KR920, IN865, RU864  # noqa: E402


@_pt.mark.parametrize("prof", [US915, AU915, AS923, KR920, IN865, RU864])
def test_every_new_profile_cites_rp002(prof):
    assert "RP002-1.0.0" in prof.source


def test_channel_validation_refuses_invalid_values():
    with _pt.raises(ValueError):
        DiscreteChannel(902_300_000, 300_000, 0, 3, True)      # largeur non LoRa
    with _pt.raises(ValueError):
        DiscreteChannel(902_300_000, 125_000, 4, 3, True)      # DR inversés
    with _pt.raises(ValueError):
        DiscreteChannel(902.3e6, 125_000, 0, 3, True)          # float refusé


def test_us915_plan_matches_rp002_frequencies():
    up125 = [c for c in US915.channels if c.uplink and c.bw_hz == 125_000]
    up500 = [c for c in US915.channels if c.uplink and c.bw_hz == 500_000]
    down = [c for c in US915.channels if not c.uplink]
    assert len(up125) == 64 and len(up500) == 8 and len(down) == 8
    assert up125[0].freq_hz == 902_300_000 and up125[-1].freq_hz == 914_900_000
    assert up500[0].freq_hz == 903_000_000 and up500[-1].freq_hz == 914_200_000
    assert down[0].freq_hz == 923_300_000 and down[-1].freq_hz == 927_500_000
    assert all((c.dr_min, c.dr_max) == (0, 3) for c in up125)
    assert all(c.dr_min == c.dr_max == 4 for c in up500)
    assert all((c.dr_min, c.dr_max) == (8, 13) for c in down)


def test_us915_dwell_time_and_conducted_power():
    assert US915.dwell_time_ms == 400
    assert US915.power_basis == "conducted"
    assert US915.channel_at(902_300_000).max_eirp_dbm == pytest.approx(30.0)
    assert US915.channel_at(903_000_000).max_eirp_dbm == pytest.approx(26.0)
    assert US915.duty_cycle_limit(902_300_000, 14.0) is None  # pas de duty cycle


def test_au915_plan_and_recommended_interval():
    assert AU915.channel_at(915_200_000).freq_hz == 915_200_000
    assert AU915.channel_at(927_800_000) is not None
    assert AU915.channel_at(915_900_000).dr_min == 6
    assert AU915.channel_at(927_100_000, uplink=True) is not None
    assert AU915.recommended_interval_s == pytest.approx(20.0)
    assert AU915.power_basis == "eirp"


def test_as923_defaults_and_no_documented_subband():
    defaults = [c.freq_hz for c in AS923.channels if c.is_default]
    assert defaults == [923_200_000, 923_400_000]
    assert AS923.duty_cycle_limit(923_200_000, 16.0) is None
    assert AS923.power_basis is None  # limites par pays : texte local requis


def test_kr920_eirp_by_subrange_and_defaults():
    assert KR920.channel_at(920_900_000).max_eirp_dbm == pytest.approx(10.0)
    assert KR920.channel_at(921_900_000).max_eirp_dbm == pytest.approx(10.0)
    assert KR920.channel_at(922_100_000).max_eirp_dbm == pytest.approx(14.0)
    assert KR920.channel_at(923_300_000).max_eirp_dbm == pytest.approx(14.0)
    assert len(KR920.channels) == 13
    assert [c.freq_hz for c in KR920.channels if c.is_default] == [922_100_000, 922_300_000, 922_500_000]


def test_in865_defaults_and_gazette_power_limit():
    assert [c.freq_hz for c in IN865.channels] == [865_062_500, 865_402_500, 865_985_000]
    # GSR 564(E) : 4 W ERP => EIRP = 10 log10(4000) + 2,15 ≈ 38,17 dBm
    assert IN865.channels[0].max_eirp_dbm == pytest.approx(38.17, abs=0.01)
    assert IN865.power_basis == "eirp"
    assert "GSR 564(E)" in IN865.source


def test_ru864_defaults_and_annex11_power():
    # Annexe 11 (décision GKRF 07-20-03-001) : 25 mW ERP => 16,13 dBm EIRP.
    assert [c.freq_hz for c in RU864.channels] == [868_900_000, 869_100_000]
    assert all(c.max_eirp_dbm == pytest.approx(16.13, abs=0.01) for c in RU864.channels)
    # Duty cycle appliqué par prudence (à confirmer) sur 864–865 et 868,7–869,2 MHz.
    assert RU864.duty_cycle_for(864_500_000, 16.0) == pytest.approx(0.001)
    assert RU864.duty_cycle_for(868_900_000, 16.0) == pytest.approx(0.001)
    assert "à confirmer" in RU864.source  # statut partiel explicite, aussi dans la chaîne source
    with pytest.raises(ValueError):
        RU864.duty_cycle_for(865_500_000, 16.0)  # 865–868 MHz : non couvert par l'annexe 11 lue


def test_au915_source_cites_acma_item_58():
    assert "F2023C00524" in AU915.source
    assert "item 58" in AU915.source
    assert AU915.channel_at(915_200_000).max_eirp_dbm == pytest.approx(30.0)


def test_scenario_in865_power_limit():
    _group(region="IN865", channel_freq_hz=865_062_500, tx_power_dbm=30.0)
    with pytest.raises(ValueError):
        _group(region="IN865", channel_freq_hz=865_062_500, tx_power_dbm=39.0)


def test_every_profile_is_registered():
    from lsim.regions import PROFILES
    assert set(PROFILES) == {"EU868", "US915", "AU915", "AS923", "AS923JP", "KR920", "IN865", "RU864"}


def test_as923jp_channels_power_and_zone_duty():
    from lsim.regions import AS923JP
    assert [c.freq_hz for c in AS923JP.channels] == [923_200_000, 923_400_000]
    # 20 mW + 3 dBi => 16,01 dBm EIRP
    assert AS923JP.channels[0].max_eirp_dbm == pytest.approx(16.01, abs=0.01)
    # 922,4–923,4 MHz : 360 s/h (10 %), à confirmer pour la partie 2
    assert AS923JP.duty_cycle_for(923_200_000, 16.0) == pytest.approx(0.10)
    # 920,5–922,4 MHz : pas de limite de duty cycle (écoute de porteuse non modélisée)
    assert AS923JP.duty_cycle_for(921_000_000, 16.0) == pytest.approx(1.0)
    assert "ARIB STD-T108" in AS923JP.source


def test_scenario_as923jp_power_limit():
    _group(region="AS923JP", channel_freq_hz=923_200_000, tx_power_dbm=16.0, duty_cycle=1.0)
    assert _group(region="AS923JP", channel_freq_hz=923_200_000, tx_power_dbm=16.0).effective_duty_cycle == pytest.approx(0.10)
    with pytest.raises(ValueError):
        _group(region="AS923JP", channel_freq_hz=923_200_000, tx_power_dbm=20.0)


# ------------------------------------------- liaison scénario -> canaux

def test_scenario_us915_channel_must_exist_in_plan():
    _group(region="US915", channel_freq_hz=902_300_000)
    with pytest.raises(ValueError):
        _group(region="US915", channel_freq_hz=902_250_000)     # hors grille
    with pytest.raises(ValueError):
        _group(region="US915", channel_freq_hz=923_300_000)     # canal descendant seulement


def test_scenario_au915_eirp_above_channel_limit_refused():
    _group(region="AU915", channel_freq_hz=915_200_000, tx_power_dbm=30.0)
    with pytest.raises(ValueError):
        _group(region="AU915", channel_freq_hz=915_200_000, tx_power_dbm=31.0)


def test_scenario_us915_conducted_power_not_checked_against_eirp():
    # Base conduite : la PIRE de scénario n'est pas comparée à la limite conduite.
    _group(region="US915", channel_freq_hz=902_300_000, tx_power_dbm=36.0)


def test_scenario_as923_keeps_declared_duty_cycle():
    g = _group(region="AS923", channel_freq_hz=923_200_000, duty_cycle=0.2)
    assert g.effective_duty_cycle == pytest.approx(0.2)
