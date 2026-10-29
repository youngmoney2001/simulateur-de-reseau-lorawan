"""Bilan énergétique d'un dispositif, calculé par le cœur natif.

Profils (identifiants stables) :
- 0 : RAK4631 (module RAKwireless, nRF52840 + Semtech SX1262), fiche RAK. MCU inclus.
- 1 : SX1262 (Semtech, datasheet) + STM32L072 (ST, fiche). MCU séparé.
Sources et valeurs détaillées : `core/include/lsim/energy.hpp`.

Le temps d'antenne vient des résultats de simulation (`airtime_ns`). Les fenêtres de
réception et le traitement MCU : `device_energy` les reçoit de l'appelant ;
`device_energy_class_a` calcule les deux fenêtres RX1/RX2 par uplink.
"""

from __future__ import annotations

import ctypes
import math
from dataclasses import dataclass

from lsim._native import LIB as _LIB
from lsim.lora import StatusError

PROFILE_RAK4631 = 0
PROFILE_SX1262_STM32L072 = 1
PROFILE_NAMES = {
    PROFILE_RAK4631: "RAK4631 (nRF52840 + SX1262, module)",
    PROFILE_SX1262_STM32L072: "SX1262 (datasheet) + STM32L072 (MCU)",
}

_VALID_BW_HZ = (125_000, 250_000, 500_000)
_U64_MAX = 2**64 - 1
_U16_MAX = 2**16 - 1


@dataclass(frozen=True)
class Profile:
    profile_id: int
    name: str
    supply_v: float
    rx_ma_125khz: float
    rx_ma_250khz: float
    rx_ma_500khz: float
    sleep_ua: float
    mcu_run_ma: float


@dataclass(frozen=True)
class EnergyResult:
    energy_j: float
    average_current_ua: float


def _check_status(status: int) -> None:
    if status != 0:
        raise StatusError(status)


def _profile_id(profile_id: int) -> int:
    if not isinstance(profile_id, int) or isinstance(profile_id, bool):
        raise ValueError("profile_id doit être un entier")
    if not 0 <= profile_id < _LIB.lsim_energy_profile_count():
        raise ValueError("profile_id inconnu (0 : RAK4631, 1 : SX1262 + STM32L072)")
    return profile_id


def _ns(name: str, value: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= _U64_MAX:
        raise ValueError(f"{name} doit être un entier ns dans [0 ; 2^64-1]")
    return value


def _bandwidth(bandwidth_hz: int) -> int:
    if bandwidth_hz not in _VALID_BW_HZ:
        raise ValueError("bandwidth_hz doit valoir 125000, 250000 ou 500000")
    return bandwidth_hz


def profile(profile_id: int = PROFILE_RAK4631) -> Profile:
    """Paramètres d'un profil (valeurs natives)."""
    pid = _profile_id(profile_id)
    vals = [ctypes.c_double(0.0) for _ in range(6)]
    _check_status(_LIB.lsim_energy_profile(pid, *[ctypes.byref(v) for v in vals]))
    return Profile(pid, PROFILE_NAMES[pid], *(v.value for v in vals))


def tx_current_ma(tx_power_dbm: float, profile_id: int = PROFILE_RAK4631) -> float:
    """Courant d'émission (mA) : point du profil de puissance >= demandée."""
    if not math.isfinite(tx_power_dbm):
        raise ValueError("tx_power_dbm doit être un nombre fini")
    out = ctypes.c_double(0.0)
    _check_status(_LIB.lsim_energy_tx_current_ma(
        _profile_id(profile_id), tx_power_dbm, ctypes.byref(out)))
    return out.value


def device_energy(*, tx_power_dbm: float, bandwidth_hz: int, airtime_ns: int, total_ns: int,
                  rx_ns: int = 0, mcu_active_ns: int = 0,
                  profile_id: int = PROFILE_RAK4631) -> EnergyResult:
    """Énergie (J) et courant moyen (µA) d'un dispositif sur `total_ns`.

    `airtime_ns` : émission. `rx_ns` : fenêtres de réception (0 si non modélisées).
    `mcu_active_ns` : traitement MCU (0 si non modélisé). Le reste est en veille.
    """
    if not math.isfinite(tx_power_dbm):
        raise ValueError("tx_power_dbm doit être un nombre fini")
    energy = ctypes.c_double(0.0)
    avg = ctypes.c_double(0.0)
    _check_status(_LIB.lsim_energy_device(
        _profile_id(profile_id), tx_power_dbm, _bandwidth(bandwidth_hz),
        _ns("airtime_ns", airtime_ns), _ns("rx_ns", rx_ns), _ns("mcu_active_ns", mcu_active_ns),
        _ns("total_ns", total_ns), ctypes.byref(energy), ctypes.byref(avg)))
    return EnergyResult(energy_j=energy.value, average_current_ua=avg.value)


def device_energy_class_a(*, tx_power_dbm: float, bandwidth_hz: int, spreading_factor: int,
                          preamble_symbols: int, uplinks: int, airtime_ns: int, total_ns: int,
                          rx_window_ns: int = 0, downlink_ns_total: int = 0,
                          mcu_ns_per_uplink: int = 0,
                          profile_id: int = PROFILE_RAK4631) -> EnergyResult:
    """Classe A : deux fenêtres RX1 (1 s) et RX2 (2 s) par uplink.

    `rx_window_ns` : durée d'ouverture de chaque fenêtre ; 0 = durée du préambule.
    `downlink_ns_total` : airtime des downlinks reçus, ajouté en majorant.
    """
    if not math.isfinite(tx_power_dbm):
        raise ValueError("tx_power_dbm doit être un nombre fini")
    if not isinstance(spreading_factor, int) or not 7 <= spreading_factor <= 12:
        raise ValueError("spreading_factor doit valoir 7 à 12")
    if not isinstance(preamble_symbols, int) or not 0 <= preamble_symbols <= _U16_MAX:
        raise ValueError("preamble_symbols doit être un entier dans [0 ; 65535]")
    energy = ctypes.c_double(0.0)
    avg = ctypes.c_double(0.0)
    _check_status(_LIB.lsim_energy_device_class_a(
        _profile_id(profile_id), tx_power_dbm, _bandwidth(bandwidth_hz), spreading_factor,
        preamble_symbols, _ns("uplinks", uplinks), _ns("airtime_ns", airtime_ns),
        _ns("rx_window_ns", rx_window_ns), _ns("downlink_ns_total", downlink_ns_total),
        _ns("mcu_ns_per_uplink", mcu_ns_per_uplink), _ns("total_ns", total_ns),
        ctypes.byref(energy), ctypes.byref(avg)))
    return EnergyResult(energy_j=energy.value, average_current_ua=avg.value)
