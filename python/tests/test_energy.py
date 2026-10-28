"""Bilan énergétique : profil natif, calcul et validation."""

import pytest

from lsim.energy import device_energy, profile

SECOND = 1_000_000_000


def test_profile_matches_rak4631_datasheet():
    p = profile()
    assert p.supply_v == pytest.approx(3.3)        # RAK4631, tension nominale
    assert p.rx_ma_125khz == pytest.approx(17.0)   # RAK4631, Rx LoRa
    assert p.rx_ma_250khz == pytest.approx(17.0)
    assert p.rx_ma_500khz == pytest.approx(17.0)
    assert p.sleep_ua == pytest.approx(2.0)        # RAK4631, veille LoRa et BLE
    assert p.mcu_run_ma == pytest.approx(0.0)      # inclus dans les courants module


def test_one_second_tx_then_sleep_matches_hand_computation():
    # 1 s à 14 dBm (point module 17 dBm, 92 mA), 3599 s de veille à 2,0 µA, 3,3 V.
    r = device_energy(tx_power_dbm=14.0, bandwidth_hz=125_000,
                      airtime_ns=SECOND, total_ns=3600 * SECOND)
    charge = 0.092 + 2.0e-6 * 3599
    assert r.energy_j == pytest.approx(3.3 * charge, rel=1e-9)
    assert r.average_current_ua == pytest.approx(charge / 3600 * 1e6, rel=1e-9)


def test_energy_is_monotonic_in_airtime():
    values = [device_energy(tx_power_dbm=14.0, bandwidth_hz=125_000,
                            airtime_ns=a * SECOND // 10, total_ns=3600 * SECOND).energy_j
              for a in range(0, 50, 5)]
    assert values == sorted(values)
    assert values[0] < values[-1]


def test_no_activity_gives_sleep_current_only():
    r = device_energy(tx_power_dbm=14.0, bandwidth_hz=125_000, airtime_ns=0,
                      total_ns=1000 * SECOND)
    assert r.average_current_ua == pytest.approx(2.0, rel=1e-9)


@pytest.mark.parametrize("kwargs", [
    dict(tx_power_dbm=float("nan"), bandwidth_hz=125_000, airtime_ns=0, total_ns=SECOND),
    dict(tx_power_dbm=14.0, bandwidth_hz=868_000, airtime_ns=0, total_ns=SECOND),
    dict(tx_power_dbm=14.0, bandwidth_hz=125_000, airtime_ns=-1, total_ns=SECOND),
    dict(tx_power_dbm=14.0, bandwidth_hz=125_000, airtime_ns=0, total_ns=0),
    dict(tx_power_dbm=14.0, bandwidth_hz=125_000, airtime_ns=2 * SECOND, total_ns=SECOND),
    dict(tx_power_dbm=22.0, bandwidth_hz=125_000, airtime_ns=0, total_ns=SECOND),
])
def test_rejects_invalid_inputs(kwargs):
    with pytest.raises(ValueError):
        device_energy(**kwargs)
