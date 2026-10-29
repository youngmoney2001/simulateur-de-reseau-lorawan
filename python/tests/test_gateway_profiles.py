"""Catalogue des passerelles : règles de publication et capacités mesh."""

import pytest

from lsim.gateway_profiles import CATALOG, can_relay, get_profile


def test_keys_are_unique_and_sourced():
    keys = [p.key for p in CATALOG]
    assert len(keys) == len(set(keys))
    for p in CATALOG:
        assert p.source.startswith("https://")
        assert p.access_bands


def test_rak7249_documented_values():
    p = get_profile("rak7249")
    assert p.rx_sensitivity_min_dbm == -139.0
    assert p.tx_power_max_dbm == 27.0
    assert "EU868" in p.access_bands


def test_undocumented_mesh_cannot_relay():
    p = get_profile("rak7249")
    assert p.mesh_bands == ()
    assert can_relay(p) is False


def test_unknown_profile_is_refused():
    with pytest.raises(KeyError):
        get_profile("inconnu")
