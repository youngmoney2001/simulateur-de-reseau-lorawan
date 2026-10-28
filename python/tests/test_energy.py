"""Bilan énergétique : profil natif, calcul et validation."""

import pytest

from lsim.energy import device_energy, profile

SECOND = 1_000_000_000


def test_profile_matches_documented_sources():
    p = profile()
    assert p.supply_v == pytest.approx(3.3)
    assert p.rx_ma_125khz == pytest.approx(10.3)   # SX1276 Table 10, bande 1, 125 kHz
    assert p.rx_ma_250khz == pytest.approx(11.1)
    assert p.rx_ma_500khz == pytest.approx(12.6)
    assert p.sleep_ua == pytest.approx(0.63)       # 0,2 µA radio + 0,43 µA MCU Stop
    assert p.mcu_run_ma == pytest.approx(93e-3 * 32)


def test_one_second_tx_then_sleep_matches_hand_computation():
    # 1 s à 14 dBm (estimation 87 mA), 3599 s de veille à 0,63 µA, 3,3 V.
    r = device_energy(tx_power_dbm=14.0, bandwidth_hz=125_000,
                      airtime_ns=SECOND, total_ns=3600 * SECOND)
    charge = 0.087 + 0.63e-6 * 3599
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
    assert r.average_current_ua == pytest.approx(0.63, rel=1e-9)


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
