"""Catalogue des passerelles : règles de publication et capacités mesh."""

import pytest

from lsim.gateway_profiles import CATALOG, can_relay, can_simulate_radio, get_profile


def test_keys_are_unique_and_sourced():
    keys = [p.key for p in CATALOG]
    assert len(keys) == len(set(keys))
    for p in CATALOG:
        assert p.source  # URL ou document fourni, nommé
        if p.is_host:
            assert p.access_bands == () and p.mesh_bands == ()
        else:
            assert p.access_bands


def test_rak5148_datasheet_values():
    p = get_profile("rak5148")
    assert p.tx_power_max_dbm == 27.0
    assert p.rx_sensitivity_min_dbm == -132.0
    assert p.max_channels is None          # non publié : jamais deviné
    assert p.mesh_bands == ("ISM2400",)
    assert "RAK5148-211" in p.model and "RAK5148-221" in p.model
    assert any("-110 dBm" in n and "-106 dBm" in n for n in p.notes)
    assert can_simulate_radio(p)


def test_rak7391_is_host_without_radio_values():
    p = get_profile("rak7391")
    assert p.is_host
    assert p.tx_power_max_dbm is None and p.rx_sensitivity_min_dbm is None
    assert p.max_channels is None and p.access_bands == () and p.mesh_bands == ()
    assert not can_relay(p)
    assert not can_simulate_radio(p)


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
