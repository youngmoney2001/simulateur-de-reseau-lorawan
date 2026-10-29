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


def uplink_airtime_ns(d: object) -> int:
    """Airtime moyen d'un uplink du dispositif `d`, FOpts LinkCheckReq compris.

    Le moteur allonge de 1 octet les uplinks de rang multiple de N (`link_check_every`) ; la
    moyenne par message vaut donc `plain + (with_fopts - plain) / N`.
    """
    cfg = RadioConfig(spreading_factor=d.spreading_factor, bandwidth_hz=_BANDWIDTH_HZ)
    plain = time_on_air_ns(cfg, d.payload_bytes)
    period = getattr(d, "link_check_every", 0)
    if not period:
        return plain
    with_fopts = time_on_air_ns(cfg, d.payload_bytes + 1)
    return plain + round((with_fopts - plain) / period)


def device_energies_protocol(devices: Sequence[object], dl_airtime_ns: Sequence[int],
                             sent: Sequence[int],
                             profile: str = DEFAULT_ENERGY_PROFILE,
                             ul_airtime_ns: Optional[Sequence[int]] = None,
                             ) -> tuple[DeviceEnergy, ...]:
    """Énergie par message avec l'airtime des downlinks reçus (issu de la trace).

    `sent[i]` : uplinks émis par le dispositif i ; `dl_airtime_ns[i]` : airtime total des downlinks
    qu'il a reçus. Chaque message porte la part moyenne de ce airtime (`dl_airtime / sent`). Les
    fenêtres RX1/RX2 restent comptées par le modèle classe A ; seul le temps de réception effectif
    des trames descendantes s'ajoute. Sans downlink, le résultat égale `device_energies`.
    `ul_airtime_ns[i]` (optionnel) : airtime total des uplinks émis, tel que compté par le moteur
    (FOpts inclus) ; sinon l'airtime moyen de `uplink_airtime_ns`.
    """
    if not (len(devices) == len(dl_airtime_ns) == len(sent)):
        raise ValueError("devices, dl_airtime_ns et sent doivent avoir la même longueur")
    if ul_airtime_ns is not None and len(ul_airtime_ns) != len(devices):
        raise ValueError("ul_airtime_ns doit avoir la même longueur que devices")
    pid = ENERGY_PROFILES[_check_name(profile)]
    out = []
    for i, d in enumerate(devices):
        if ul_airtime_ns is not None and sent[i]:
            airtime = ul_airtime_ns[i] // sent[i]
        else:
            airtime = uplink_airtime_ns(d)
        per_message = dl_airtime_ns[i] // sent[i] if sent[i] else 0
        try:
            r = device_energy_class_a(
                tx_power_dbm=d.tx_power_dbm, bandwidth_hz=_BANDWIDTH_HZ,
                spreading_factor=d.spreading_factor, preamble_symbols=_PREAMBLE_SYMBOLS,
                uplinks=1, airtime_ns=airtime, total_ns=d.period_ns,
                downlink_ns_total=per_message, profile_id=pid)
        except (ValueError, StatusError):
            out.append(DeviceEnergy(i, None, None))
            continue
        out.append(DeviceEnergy(i, r.energy_j, r.average_current_ua))
    return tuple(out)


def device_energies(devices: Sequence[object], profile: str = DEFAULT_ENERGY_PROFILE
                    ) -> tuple[DeviceEnergy, ...]:
    """Énergie par message pour chaque dispositif (`EndDevice` de `Scenario.deploy()`)."""
    pid = ENERGY_PROFILES[_check_name(profile)]
    out = []
    for i, d in enumerate(devices):
        airtime = uplink_airtime_ns(d)
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

