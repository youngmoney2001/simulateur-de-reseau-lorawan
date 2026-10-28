"""Énergie par message et courant moyen par dispositif, pour un profil au choix.

Hypothèses (classe A, un message par période du groupe) :
- une émission de durée `time_on_air` (125 kHz, CR 4/5, SF du groupe) à la puissance du groupe ;
- deux fenêtres RX1/RX2 ouvertes chacune pendant la durée du préambule ;
- le reste de la période en veille ; pas de traitement MCU modélisé (0).
Les profils et leurs sources : `core/include/lsim/energy.hpp`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from lsim.energy import (
    PROFILE_NAMES,
    PROFILE_RAK4631,
    PROFILE_SX1262_STM32L072,
    device_energy_class_a,
)
from lsim.lora import RadioConfig, StatusError, time_on_air_ns

# Nom CLI -> identifiant de profil natif. Le premier est le défaut.
ENERGY_PROFILES = {
    "rak4631": PROFILE_RAK4631,
    "sx1262-stm32l072": PROFILE_SX1262_STM32L072,
}
DEFAULT_ENERGY_PROFILE = "rak4631"

_PREAMBLE_SYMBOLS = 8
_BANDWIDTH_HZ = 125_000


@dataclass(frozen=True)
class DeviceEnergy:
    device_index: int
    energy_per_message_j: Optional[float]   # None : période trop courte pour la trame
    average_current_ua: Optional[float]


def profile_name(name: str) -> str:
    """Nom lisible du profil (lève ValueError si le nom est inconnu)."""
    return PROFILE_NAMES[ENERGY_PROFILES[_check_name(name)]]


def _check_name(name: str) -> str:
    if name not in ENERGY_PROFILES:
        raise ValueError(
            f"profil énergie inconnu : {name!r} (choix : {', '.join(ENERGY_PROFILES)})")
    return name


def device_energies(devices: Sequence[object], profile: str = DEFAULT_ENERGY_PROFILE
                    ) -> tuple[DeviceEnergy, ...]:
    """Énergie par message pour chaque dispositif (`EndDevice` de `Scenario.deploy()`)."""
    pid = ENERGY_PROFILES[_check_name(profile)]
    out = []
    for i, d in enumerate(devices):
        airtime = time_on_air_ns(
            RadioConfig(spreading_factor=d.spreading_factor, bandwidth_hz=_BANDWIDTH_HZ),
            d.payload_bytes)
        try:
            r = device_energy_class_a(
                tx_power_dbm=d.tx_power_dbm, bandwidth_hz=_BANDWIDTH_HZ,
                spreading_factor=d.spreading_factor, preamble_symbols=_PREAMBLE_SYMBOLS,
                uplinks=1, airtime_ns=airtime, total_ns=d.period_ns, profile_id=pid)
        except (ValueError, StatusError):
            out.append(DeviceEnergy(i, None, None))
            continue
        out.append(DeviceEnergy(i, r.energy_j, r.average_current_ua))
    return tuple(out)

