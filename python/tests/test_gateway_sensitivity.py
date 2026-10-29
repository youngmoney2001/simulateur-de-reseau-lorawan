"""Décalage de sensibilité par passerelle (modèle « decalage-uniforme-v1 ») : effet au seuil, moteur natif."""

import pytest

from lsim.gateway_profiles import SENSITIVITY_MODEL, get_profile, rx_sensitivity_offset_db
from lsim.simulator import EndDevice, Gateway, Propagation, simulate_uplinks_multi


def test_offsets_come_only_from_a_published_point_in_engine_bands():
    # RAK5146 : -139 dBm publié à SF12 / 125 kHz, référence moteur -136 dBm : décalage -3 dB.
    assert rx_sensitivity_offset_db(get_profile("rak5146-rak5148")) == pytest.approx(-3.0)
    # RAK5148 : point publié à SF12 / 203 kHz, hors des bandes du moteur : aucun décalage.
    assert rx_sensitivity_offset_db(get_profile("rak5148")) == 0.0
    # RAK7249 : sensibilité publiée sans SF ni bande : aucun décalage.
    assert rx_sensitivity_offset_db(get_profile("rak7249")) == 0.0
    assert SENSITIVITY_MODEL == "decalage-uniforme-v1"


# Propagation par défaut : PL(d) = 31,2 + 27 log10(d) dB, émission 14 dBm, SF12 (seuil moteur -136 dBm).
# À 28,6 km, RSSI ≈ -137,4 dBm : sous le seuil, perdu. À 22,0 km, RSSI ≈ -134,3 dBm : entre -136 et -133.
FAR = 28_600.0
NEAR = 22_000.0


def _res(distance_m, offset_db):
    dev = [EndDevice(x_m=distance_m, spreading_factor=12, payload_bytes=10)]
    return simulate_uplinks_multi(dev, [Gateway(rx_sensitivity_offset_db=offset_db)], Propagation())


def test_a_more_sensitive_gateway_receives_the_edge_device():
    assert _res(FAR, 0.0).network.received == 0
    assert _res(FAR, -3.0).network.received == 1


def test_a_less_sensitive_gateway_loses_a_device_it_received_before():
    assert _res(NEAR, 0.0).network.received == 1
    assert _res(NEAR, 3.0).network.received == 0


def test_offset_is_bounded_and_default_is_neutral():
    dev = [EndDevice(x_m=NEAR, spreading_factor=12)]
    base = simulate_uplinks_multi(dev, [Gateway()], Propagation())
    assert base.network.received == 1
    with pytest.raises(ValueError):
        simulate_uplinks_multi(dev, [Gateway(rx_sensitivity_offset_db=25.0)], Propagation())
