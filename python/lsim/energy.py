"""Bilan énergétique d'un dispositif, calculé par le cœur natif.

Sources des courants (détail dans `core/include/lsim/energy.hpp`) :
- SX1276 datasheet Rev. 4 : émission (Table 6, typ.), réception LoRa bande 1 (Table 10),
  veille (Table 6, 0,2 µA typ.) ;
- microcontrôleur de référence STM32L072 (fiche ST, valeurs « à partir de ») ;
- alimentation 3,3 V : hypothèse de référence.

Le temps d'antenne vient des résultats de simulation (`airtime_ns` par dispositif).
Les durées de réception et de traitement MCU ne sont pas issues du moteur : elles sont
à fournir par l'appelant.
"""

from __future__ import annotations

import ctypes
import math
from dataclasses import dataclass

from lsim._native import LIB as _LIB
from lsim.lora import StatusError

_VALID_BW_HZ = (125_000, 250_000, 500_000)
_U64_MAX = 2**64 - 1


@dataclass(frozen=True)
class Profile:
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


def profile() -> Profile:
    """Paramètres du profil par défaut (valeurs natives)."""
    vals = [ctypes.c_double(0.0) for _ in range(6)]
    status = _LIB.lsim_energy_profile(*[ctypes.byref(v) for v in vals])
    if status != 0:
        raise StatusError(status)
    return Profile(*(v.value for v in vals))


def _ns(name: str, value: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= _U64_MAX:
        raise ValueError(f"{name} doit être un entier ns dans [0 ; 2^64-1]")
    return value


def device_energy(*, tx_power_dbm: float, bandwidth_hz: int, airtime_ns: int, total_ns: int,
                  rx_ns: int = 0, mcu_active_ns: int = 0) -> EnergyResult:
    """Énergie (J) et courant moyen (µA) d'un dispositif sur `total_ns`.

    `airtime_ns` : émission. `rx_ns` : fenêtres de réception (0 si non modélisées).
    `mcu_active_ns` : traitement MCU (0 si non modélisé). Le reste est en veille.
    """
    if not math.isfinite(tx_power_dbm):
        raise ValueError("tx_power_dbm doit être un nombre fini")
    if bandwidth_hz not in _VALID_BW_HZ:
        raise ValueError("bandwidth_hz doit valoir 125000, 250000 ou 500000")
    airtime_ns = _ns("airtime_ns", airtime_ns)
    total_ns = _ns("total_ns", total_ns)
    rx_ns = _ns("rx_ns", rx_ns)
    mcu_active_ns = _ns("mcu_active_ns", mcu_active_ns)
    energy = ctypes.c_double(0.0)
    avg = ctypes.c_double(0.0)
    status = _LIB.lsim_energy_device(
        tx_power_dbm, bandwidth_hz, airtime_ns, rx_ns, mcu_active_ns, total_ns,
        ctypes.byref(energy), ctypes.byref(avg))
    if status != 0:
        raise StatusError(status)
    return EnergyResult(energy_j=energy.value, average_current_ua=avg.value)
