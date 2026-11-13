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
class MeasuredProfile:
    """Un profil **mesuré**, fourni par l'appelant au lieu d'être pris au catalogue.

    C'est la seule manière d'entrer un relevé — banc ou terrain — dans le bilan. Les
    courants des deux profils du catalogue viennent de fiches constructeur : utiles pour
    comparer deux architectures, insuffisants pour garantir une autonomie.

    `provenance` est **obligatoire** et non vide : un rapport qui afficherait ces chiffres
    sans dire d'où ils viennent les présenterait comme une donnée du moteur. On exige donc
    une phrase — « relevé banc, 2026-03 », « campagne Douala, 12 points » — qui voyage
    avec le résultat.

    `tx_points` : couples (dBm, mA) triés par puissance croissante, 1 à 4 points. La règle
    d'émission est celle du catalogue : le point de puissance ≥ demandée, refus au-delà du
    dernier.
    """

    supply_v: float
    rx_ma_125khz: float
    rx_ma_250khz: float
    rx_ma_500khz: float
    sleep_ua: float
    provenance: str
    tx_points: tuple[tuple[float, float], ...]
    mcu_run_ma: float = 0.0

    def __post_init__(self) -> None:
        if not isinstance(self.provenance, str) or not self.provenance.strip():
            raise ValueError(
                "provenance obligatoire : d'où viennent ces courants ? "
                "(ex. « relevé banc, 2026-03 »)")
        for nom in ("supply_v", "rx_ma_125khz", "rx_ma_250khz", "rx_ma_500khz", "sleep_ua",
                    "mcu_run_ma"):
            v = getattr(self, nom)
            if not math.isfinite(v) or v < 0.0:
                raise ValueError(f"{nom} doit être un nombre fini et positif")
        if self.supply_v <= 0.0:
            raise ValueError("supply_v doit être > 0")
        if not self.tx_points or len(self.tx_points) > 4:
            raise ValueError("tx_points : de 1 à 4 points")
        precedant = None
        for dbm, ma in self.tx_points:
            if not math.isfinite(dbm) or not math.isfinite(ma) or ma < 0.0:
                raise ValueError("tx_points : couples (dBm, mA) finis, mA >= 0")
            if precedant is not None and dbm <= precedant:
                raise ValueError("tx_points : puissances strictement croissantes")
            precedant = dbm

    def to_c(self):
        dbm = (ctypes.c_double * len(self.tx_points))(*[p[0] for p in self.tx_points])
        ma = (ctypes.c_double * len(self.tx_points))(*[p[1] for p in self.tx_points])
        return dbm, ma


@dataclass(frozen=True)
class EnergyResult:
    energy_j: float
    average_current_ua: float
    provenance: str | None = None


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
                  profile_id: int = PROFILE_RAK4631,
                  measured: MeasuredProfile | None = None) -> EnergyResult:
    """Énergie (J) et courant moyen (µA) d'un dispositif sur `total_ns`.

    `airtime_ns` : émission. `rx_ns` : fenêtres de réception (0 si non modélisées).
    `mcu_active_ns` : traitement MCU (0 si non modélisé). Le reste est en veille.

    `measured` : un profil mesuré (`MeasuredProfile`) prime sur `profile_id`. Les deux
    chemins rendent le même type, mais le résultat d'un profil mesuré porte sa
    `provenance` : un rapport qui l'affiche doit pouvoir dire d'où viennent les courants.
    """
    if not math.isfinite(tx_power_dbm):
        raise ValueError("tx_power_dbm doit être un nombre fini")
    energy = ctypes.c_double(0.0)
    avg = ctypes.c_double(0.0)
    if measured is not None:
        dbm, ma = measured.to_c()
        _check_status(_LIB.lsim_energy_device_measured(
            measured.supply_v, measured.rx_ma_125khz, measured.rx_ma_250khz,
            measured.rx_ma_500khz, measured.sleep_ua, measured.mcu_run_ma,
            dbm, ma, len(measured.tx_points),
            tx_power_dbm, _bandwidth(bandwidth_hz), _ns("airtime_ns", airtime_ns),
            _ns("rx_ns", rx_ns), _ns("mcu_active_ns", mcu_active_ns),
            _ns("total_ns", total_ns), ctypes.byref(energy), ctypes.byref(avg)))
        return EnergyResult(energy_j=energy.value, average_current_ua=avg.value,
                            provenance=measured.provenance)
    _check_status(_LIB.lsim_energy_device(
        _profile_id(profile_id), tx_power_dbm, _bandwidth(bandwidth_hz),
        _ns("airtime_ns", airtime_ns), _ns("rx_ns", rx_ns), _ns("mcu_active_ns", mcu_active_ns),
        _ns("total_ns", total_ns), ctypes.byref(energy), ctypes.byref(avg)))
    return EnergyResult(energy_j=energy.value, average_current_ua=avg.value)


def device_energy_class_a(*, tx_power_dbm: float, bandwidth_hz: int, spreading_factor: int,
                          preamble_symbols: int, uplinks: int, airtime_ns: int, total_ns: int,
                          rx_window_ns: int = 0, downlink_ns_total: int = 0,
                          mcu_ns_per_uplink: int = 0,
                          profile_id: int = PROFILE_RAK4631,
                          measured: MeasuredProfile | None = None) -> EnergyResult:
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
    if measured is not None:
        dbm, ma = measured.to_c()
        _check_status(_LIB.lsim_energy_device_class_a_measured(
            measured.supply_v, measured.rx_ma_125khz, measured.rx_ma_250khz,
            measured.rx_ma_500khz, measured.sleep_ua, measured.mcu_run_ma,
            dbm, ma, len(measured.tx_points),
            tx_power_dbm, _bandwidth(bandwidth_hz), spreading_factor, preamble_symbols,
            _ns("uplinks", uplinks), _ns("airtime_ns", airtime_ns),
            _ns("rx_window_ns", rx_window_ns), _ns("downlink_ns_total", downlink_ns_total),
            _ns("mcu_ns_per_uplink", mcu_ns_per_uplink), _ns("total_ns", total_ns),
            ctypes.byref(energy), ctypes.byref(avg)))
        return EnergyResult(energy_j=energy.value, average_current_ua=avg.value,
                            provenance=measured.provenance)
    _check_status(_LIB.lsim_energy_device_class_a(
        _profile_id(profile_id), tx_power_dbm, _bandwidth(bandwidth_hz), spreading_factor,
        preamble_symbols, _ns("uplinks", uplinks), _ns("airtime_ns", airtime_ns),
        _ns("rx_window_ns", rx_window_ns), _ns("downlink_ns_total", downlink_ns_total),
        _ns("mcu_ns_per_uplink", mcu_ns_per_uplink), _ns("total_ns", total_ns),
        ctypes.byref(energy), ctypes.byref(avg)))
    return EnergyResult(energy_j=energy.value, average_current_ua=avg.value)
