"""Simulation des liaisons montantes, calculée par le cœur natif.

Python prépare et lit les données ; le moteur (file d'événements, collisions,
capture) est entièrement dans le cœur C++. Les limites (10 000 dispositifs,
5 000 000 transmissions) sont appliquées par le natif.
"""

from __future__ import annotations

import ctypes
import math
from dataclasses import dataclass
from typing import Sequence

from lsim._native import (
    LIB,
    _CDeviceStats,
    _CEndDevice,
    _CGateway,
    _CPropagation,
)
from lsim.lora import StatusError

MAX_END_DEVICES = 10_000
_NS_PER_MIN = 60_000_000_000


@dataclass(frozen=True)
class EndDevice:
    x_m: float = 0.0
    y_m: float = 0.0
    spreading_factor: int = 7
    payload_bytes: int = 10
    tx_power_dbm: float = 14.0
    start_offset_ns: int = 0
    period_ns: int = 60 * _NS_PER_MIN
    messages: int = 1

    def __post_init__(self) -> None:
        for name in ("x_m", "y_m", "tx_power_dbm"):
            if not math.isfinite(getattr(self, name)):
                raise ValueError(f"{name} doit être un nombre fini")
        if not 7 <= self.spreading_factor <= 12:
            raise ValueError("spreading_factor doit être compris entre 7 et 12")
        if not 0 <= self.payload_bytes <= 255:
            raise ValueError("payload_bytes doit être compris entre 0 et 255")
        if self.start_offset_ns < 0:
            raise ValueError("start_offset_ns doit être positif ou nul")
        if self.period_ns <= 0:
            raise ValueError("period_ns doit être strictement positif")
        if self.messages < 1:
            raise ValueError("messages doit être au moins 1")


@dataclass(frozen=True)
class Gateway:
    x_m: float = 0.0
    y_m: float = 0.0
    antenna_gain_dbi: float = 0.0


@dataclass(frozen=True)
class Propagation:
    frequency_hz: float = 868.1e6
    reference_distance_m: float = 1.0
    exponent: float = 2.7
    capture_threshold_db: float = 6.0

    def __post_init__(self) -> None:
        for name in ("frequency_hz", "reference_distance_m", "exponent", "capture_threshold_db"):
            if not math.isfinite(getattr(self, name)):
                raise ValueError(f"{name} doit être un nombre fini")
        if self.frequency_hz <= 0 or self.reference_distance_m <= 0:
            raise ValueError("frequency_hz et reference_distance_m doivent être > 0")
        if not 1.0 <= self.exponent <= 6.0:
            raise ValueError("exponent doit être compris entre 1 et 6")
        if self.capture_threshold_db < 0:
            raise ValueError("capture_threshold_db doit être positif ou nul")


@dataclass(frozen=True)
class Counters:
    sent: int = 0
    received: int = 0
    lost_sensitivity: int = 0
    lost_collision: int = 0


@dataclass(frozen=True)
class SimulationResult:
    per_device: tuple[Counters, ...]
    totals: Counters


def simulate_uplinks(devices: Sequence[EndDevice], gateway: Gateway,
                     propagation: Propagation) -> SimulationResult:
    """Simule les liaisons montantes vers une passerelle et retourne les compteurs."""
    if len(devices) > MAX_END_DEVICES:
        raise ValueError(f"au plus {MAX_END_DEVICES} dispositifs par simulation")
    n = len(devices)
    c_devs = (_CEndDevice * n)()
    for i, d in enumerate(devices):
        c = c_devs[i]
        c.x_m = d.x_m
        c.y_m = d.y_m
        c.spreading_factor = d.spreading_factor
        c.payload_bytes = d.payload_bytes
        c.tx_power_dbm = d.tx_power_dbm
        c.start_offset_ns = d.start_offset_ns
        c.period_ns = d.period_ns
        c.messages = d.messages

    c_gw = _CGateway(gateway.x_m, gateway.y_m, gateway.antenna_gain_dbi)
    c_prop = _CPropagation(propagation.frequency_hz, propagation.reference_distance_m,
                           propagation.exponent, propagation.capture_threshold_db)
    c_stats = (_CDeviceStats * n)()
    c_tot = _CDeviceStats()
    status = LIB.lsim_simulate_uplinks(
        c_devs if n else None, n, ctypes.byref(c_gw), ctypes.byref(c_prop),
        c_stats if n else None, ctypes.byref(c_tot))
    if status != 0:
        raise StatusError(status)

    per = tuple(
        Counters(s.sent, s.received, s.lost_sensitivity, s.lost_collision) for s in c_stats
    )
    tot = Counters(c_tot.sent, c_tot.received, c_tot.lost_sensitivity, c_tot.lost_collision)
    return SimulationResult(per_device=per, totals=tot)
