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
