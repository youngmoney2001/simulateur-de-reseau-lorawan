"""Bilan énergétique : profils natifs, calcul, classe A et validation."""

import pytest

from lsim.energy import (
    PROFILE_RAK4631,
    PROFILE_SX1262_STM32L072,
    device_energy,
    device_energy_class_a,
    profile,
    tx_current_ma,
)
from lsim.lora import StatusError

SECOND = 1_000_000_000


def test_rak_profile_matches_datasheet():
    p = profile(PROFILE_RAK4631)
    assert p.supply_v == pytest.approx(3.3)
    assert p.rx_ma_125khz == pytest.approx(17.0)
    assert p.rx_ma_500khz == pytest.approx(17.0)
    assert p.sleep_ua == pytest.approx(2.0)
    assert p.mcu_run_ma == pytest.approx(0.0)  # inclus dans les courants module


def test_sx_stm32_profile_values():
    p = profile(PROFILE_SX1262_STM32L072)
    assert p.supply_v == pytest.approx(3.3)
    assert p.rx_ma_125khz == pytest.approx(4.6)
    assert p.sleep_ua == pytest.approx(0.59)          # 0,16 + 0,43
    assert p.mcu_run_ma == pytest.approx(2.976)       # 93 µA/MHz × 32 MHz


def test_tx_current_uses_next_published_point():
    assert tx_current_ma(14.0, PROFILE_RAK4631) == pytest.approx(92.0)
    assert tx_current_ma(14.0, PROFILE_SX1262_STM32L072) == pytest.approx(90.0)
    assert tx_current_ma(15.0, PROFILE_SX1262_STM32L072) == pytest.approx(95.0)
    assert tx_current_ma(22.0, PROFILE_SX1262_STM32L072) == pytest.approx(118.0)


def test_tx_above_last_point_is_rejected():
    with pytest.raises(StatusError):
        tx_current_ma(21.0, PROFILE_RAK4631)
    with pytest.raises(StatusError):
        tx_current_ma(22.5, PROFILE_SX1262_STM32L072)


def test_rak_one_second_tx_then_sleep():
    # Q = 0,092 + 2,0e-6 × 3599 = 0,099198 C ; E = 3,3 × Q = 0,3273534 J.
    r = device_energy(tx_power_dbm=14.0, bandwidth_hz=125_000, airtime_ns=SECOND,
                      total_ns=3600 * SECOND)
    assert r.energy_j == pytest.approx(0.3273534, rel=1e-9)
    assert r.average_current_ua == pytest.approx(0.099198 / 3600 * 1e6, rel=1e-9)


def test_sx_one_second_tx_then_sleep():
    # Q = 0,090 + 0,59e-6 × 3599 = 0,09212341 C ; E = 0,304007253 J.
    r = device_energy(tx_power_dbm=14.0, bandwidth_hz=125_000, airtime_ns=SECOND,
                      total_ns=3600 * SECOND, profile_id=PROFILE_SX1262_STM32L072)
    assert r.energy_j == pytest.approx(0.304007253, rel=1e-9)


def test_class_a_preamble_window():
    # Préambule SF7/125 kHz = 12,544 ms ; 10 uplinks de 100 ms.
    # Q = 0,092 + 0,017 × 0,25088 + 2,0e-6 × 3598,74912 = 0,10346245824 C.
    r = device_energy_class_a(tx_power_dbm=14.0, bandwidth_hz=125_000, spreading_factor=7,
                              preamble_symbols=8, uplinks=10, airtime_ns=100_000_000,
                              total_ns=3600 * SECOND)
    assert r.energy_j == pytest.approx(0.10346245824 * 3.3, rel=1e-9)


def test_class_a_explicit_window_and_downlink():
    # Fenêtres de 1 s, plus 0,5 s de downlink ; Q = 0,0046 × 2,5 + 0,59e-6 × 7,5 = 0,011504425 C.
    r = device_energy_class_a(tx_power_dbm=14.0, bandwidth_hz=125_000, spreading_factor=7,
                              preamble_symbols=8, uplinks=1, airtime_ns=0,
                              rx_window_ns=SECOND, downlink_ns_total=SECOND // 2,
                              total_ns=10 * SECOND, profile_id=PROFILE_SX1262_STM32L072)
    assert r.energy_j == pytest.approx(0.011504425 * 3.3, rel=1e-9)


@pytest.mark.parametrize("bad", [-1, 2**64])
def test_out_of_range_ns_is_rejected(bad):
    with pytest.raises(ValueError):
        device_energy(tx_power_dbm=14.0, bandwidth_hz=125_000, airtime_ns=bad, total_ns=SECOND)


def test_invalid_bandwidth_and_profile_are_rejected():
    with pytest.raises(ValueError):
        device_energy(tx_power_dbm=14.0, bandwidth_hz=200_000, airtime_ns=0, total_ns=SECOND)
    with pytest.raises(ValueError):
        profile(7)
    with pytest.raises(ValueError):
        profile(True)


def test_invalid_spreading_factor_is_rejected():
    with pytest.raises(ValueError):
        device_energy_class_a(tx_power_dbm=14.0, bandwidth_hz=125_000, spreading_factor=6,
                              preamble_symbols=8, uplinks=1, airtime_ns=0, total_ns=SECOND)


def test_non_finite_power_is_rejected():
    with pytest.raises(ValueError):
        device_energy(tx_power_dbm=float("nan"), bandwidth_hz=125_000, airtime_ns=0,
                      total_ns=SECOND)
