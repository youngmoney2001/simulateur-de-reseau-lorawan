"""Bilan de liaison et propagation, calculés par le cœur natif.

Toutes les entrées sont validées ici avant l'appel natif ; le natif revalide
et renvoie un statut, qui est transformé en exception explicite.
"""

from __future__ import annotations

import ctypes
import math
from dataclasses import dataclass

from lsim._native import LIB as _LIB
from lsim.lora import StatusError

_VALID_BW_HZ = (125_000, 250_000, 500_000)


def _check(status: int, value: float) -> float:
    if status != 0:
        raise StatusError(status)
    return value


def _require_finite(name: str, x: float) -> float:
    if not math.isfinite(x):
        raise ValueError(f"{name} doit être un nombre fini")
    return float(x)


def receiver_sensitivity_dbm(spreading_factor: int, bandwidth_hz: int = 125_000) -> float:
    """Sensibilité récepteur SX1276 (dBm). Seul 125 kHz est calibré."""
    if not 7 <= spreading_factor <= 12:
        raise ValueError("spreading_factor doit être compris entre 7 et 12")
    if bandwidth_hz not in _VALID_BW_HZ:
        raise ValueError("bandwidth_hz doit valoir 125000, 250000 ou 500000")
    out = ctypes.c_double(0.0)
    status = _LIB.lsim_receiver_sensitivity_dbm(spreading_factor, bandwidth_hz, ctypes.byref(out))
    return _check(status, out.value)


def free_space_path_loss_db(distance_m: float, frequency_hz: float) -> float:
    """Perte en espace libre (dB)."""
    d = _require_finite("distance_m", distance_m)
    f = _require_finite("frequency_hz", frequency_hz)
    out = ctypes.c_double(0.0)
    status = _LIB.lsim_free_space_path_loss_db(d, f, ctypes.byref(out))
    return _check(status, out.value)


@dataclass(frozen=True)
class LogDistanceModel:
    """PL(d) = PL(d0) + 10 n log10(d / d0), avec PL(d0) en espace libre."""

    frequency_hz: float = 868.1e6
    reference_distance_m: float = 1.0
    exponent: float = 2.0

    def __post_init__(self) -> None:
        _require_finite("frequency_hz", self.frequency_hz)
        _require_finite("reference_distance_m", self.reference_distance_m)
        _require_finite("exponent", self.exponent)
        if not 1.0 <= self.exponent <= 6.0:
            raise ValueError("exponent doit être compris entre 1 et 6")
        if self.reference_distance_m <= 0 or self.frequency_hz <= 0:
            raise ValueError("reference_distance_m et frequency_hz doivent être > 0")

    def path_loss_db(self, distance_m: float) -> float:
        d = _require_finite("distance_m", distance_m)
        if d <= 0:
            raise ValueError("distance_m doit être > 0")
        out = ctypes.c_double(0.0)
        status = _LIB.lsim_log_distance_path_loss_db(
            d, self.frequency_hz, self.reference_distance_m, self.exponent, ctypes.byref(out)
        )
        return _check(status, out.value)

    def range_m(self, max_path_loss_db: float) -> float:
        """Portée maximale (m) pour une perte maximale donnée."""
        pl = _require_finite("max_path_loss_db", max_path_loss_db)
        out = ctypes.c_double(0.0)
        status = _LIB.lsim_max_range_m(
            pl, self.frequency_hz, self.reference_distance_m, self.exponent, ctypes.byref(out)
        )
        return _check(status, out.value)


@dataclass(frozen=True)
class LinkBudget:
    """Bilan de liaison : la MAPL (perte maximale admissible) en découle."""

    tx_power_dbm: float = 14.0
    tx_antenna_gain_dbi: float = 0.0
    rx_antenna_gain_dbi: float = 0.0
    cable_losses_db: float = 0.0
    fade_margin_db: float = 0.0

    def __post_init__(self) -> None:
        for name in ("tx_power_dbm", "tx_antenna_gain_dbi", "rx_antenna_gain_dbi",
                     "cable_losses_db", "fade_margin_db"):
            _require_finite(name, getattr(self, name))
        if self.cable_losses_db < 0 or self.fade_margin_db < 0:
            raise ValueError("pertes et marges ne peuvent pas être négatives")

    def max_allowable_path_loss_db(self, rx_sensitivity_dbm: float) -> float:
        s = _require_finite("rx_sensitivity_dbm", rx_sensitivity_dbm)
        out = ctypes.c_double(0.0)
        status = _LIB.lsim_max_allowable_path_loss_db(
            self.tx_power_dbm, self.tx_antenna_gain_dbi, self.rx_antenna_gain_dbi,
            self.cable_losses_db, self.fade_margin_db, s, ctypes.byref(out),
        )
        return _check(status, out.value)
