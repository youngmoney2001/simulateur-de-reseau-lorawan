"""Cadre des profils régionaux : validation, sous-bandes, refus sans source."""

import pytest

from lsim.regions import RegionProfile, SubBand, load_profile

TEST_BANDS = (
    SubBand("A", 863_000_000, 865_000_000, 0.001, 25.0),
    SubBand("B", 865_000_001, 868_000_000, 0.01, 25.0),
)


def test_profile_requires_official_source():
    with pytest.raises(ValueError):
        load_profile("XX", None, TEST_BANDS)
    with pytest.raises(ValueError):
        load_profile("XX", "   ", TEST_BANDS)
    assert load_profile("XX", "source de test", TEST_BANDS).code == "XX"


def test_band_lookup():
    prof = load_profile("XX", "source de test", TEST_BANDS)
    assert prof.band_for(864_000_000).name == "A"
    assert prof.band_for(866_000_000).name == "B"
    assert prof.band_for(900_000_000) is None


def test_overlapping_subbands_refused():
    with pytest.raises(ValueError):
        RegionProfile("XX", "src", (
            SubBand("A", 863_000_000, 865_000_000, 0.01, 14.0),
            SubBand("B", 864_000_000, 868_000_000, 0.01, 14.0),
        ))


@pytest.mark.parametrize("dc", [0.0, -0.1, 1.5, float("nan")])
def test_invalid_duty_cycle_refused(dc):
    with pytest.raises(ValueError):
        SubBand("A", 863_000_000, 865_000_000, dc, 14.0)


def test_invalid_frequency_bounds_refused():
    with pytest.raises(ValueError):
        SubBand("A", 865_000_000, 863_000_000, 0.01, 14.0)
    with pytest.raises(ValueError):
        SubBand("A", 863.0e6, 865_000_000, 0.01, 14.0)  # type float refusé


def test_no_region_shipped_without_verified_values():
    # Tant que la source officielle n'est pas vérifiée, aucun profil n'est livré.
    import lsim.regions as regions
    assert not any(isinstance(v, RegionProfile) for v in vars(regions).values())
