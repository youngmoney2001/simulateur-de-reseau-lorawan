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


def test_composite_relay_profile_is_sourced_and_carries_both_radios():
    """Relais RAK : RAK5146 pour les capteurs sous-GHz, RAK5148 pour le lien mesh 2,4 GHz."""
    p = get_profile("rak5146-rak5148")
    assert can_relay(p) and can_simulate_radio(p)
    assert "EU868" in p.access_bands and "US915" in p.access_bands
    assert p.mesh_bands == ("ISM2400",)
    assert p.rx_sensitivity_min_dbm == -139.0   # fiche RAK5146, SF12 / 125 kHz
    assert p.tx_power_max_dbm == 27.0
    assert p.max_channels == 8
    assert "RAK5146" in p.source and "RAK5148" in p.source


def test_mesh_only_module_has_no_sub_ghz_access():
    p = get_profile("rak5148")
    assert can_relay(p)
    assert p.access_bands == ("ISM2400",)


def test_software_status_is_separate_from_radio_fidelity():
    """Le profil composite est provisoire (compatibilité logicielle à valider) ; le RAK5148 seul est validé
    côté catalogue, sans que cela dise rien de la sensibilité (décalage distinct, voir test_gateway_sensitivity)."""
    from lsim.gateway_profiles import software_status
    composite = get_profile("rak5146-rak5148")
    assert composite.software_validated is False
    assert software_status(composite) == "à valider"
    assert any("décalage uniforme" in n and "non calibrée" in n for n in composite.notes)
    assert software_status(get_profile("rak5148")) == "validé"
