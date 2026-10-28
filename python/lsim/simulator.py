"""Simulation des liaisons montantes, calculée par le cœur natif.

Python prépare et lit les données ; le moteur (file d'événements, collisions,
capture) est entièrement dans le cœur C++. Les limites (10 000 dispositifs,
5 000 000 transmissions) sont appliquées par le natif.
"""

from __future__ import annotations

import ctypes
import math
from dataclasses import dataclass
from typing import Optional, Sequence

from lsim._native import (
    LIB,
    _CDeviceStats,
    _CSimStats,
    _CEndDevice,
    _CEnvironment,
    _CGateway,
    _CObstacle,
    _CPropagation,
)
from lsim.environment import Environment
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
    shadowing_sigma_db: float = 0.0
    shadowing_seed: int = 0

    def __post_init__(self) -> None:
        for name in ("frequency_hz", "reference_distance_m", "exponent", "capture_threshold_db",
                     "shadowing_sigma_db"):
            if not math.isfinite(getattr(self, name)):
                raise ValueError(f"{name} doit être un nombre fini")
        if self.frequency_hz <= 0 or self.reference_distance_m <= 0:
            raise ValueError("frequency_hz et reference_distance_m doivent être > 0")
        if not 1.0 <= self.exponent <= 6.0:
            raise ValueError("exponent doit être compris entre 1 et 6")
        if self.capture_threshold_db < 0:
            raise ValueError("capture_threshold_db doit être positif ou nul")
        if not 0.0 <= self.shadowing_sigma_db <= 30.0:
            raise ValueError("shadowing_sigma_db doit être compris entre 0 et 30 dB")
        if not 0 <= self.shadowing_seed < 2**64:
            raise ValueError("shadowing_seed doit être un entier sur 64 bits non signé")


@dataclass(frozen=True)
class Counters:
    sent: int = 0
    received: int = 0
    lost_sensitivity: int = 0
    lost_collision: int = 0
    airtime_ns: int = 0  # temps d'antenne cumulé des trames émises


@dataclass(frozen=True)
class GatewayLoad:
    """Charge de la passerelle, calculée par le cœur natif."""
    busy_ns: int = 0            # durée où au moins une trame arrive (union, sans double comptage)
    peak_concurrent: int = 0    # nombre maximal de trames simultanées
    observation_ns: int = 0     # fin de la dernière trame - début de la première
    utilization: float = 0.0    # busy_ns / observation_ns, dans [0, 1]


@dataclass(frozen=True)
class SimulationResult:
    per_device: tuple[Counters, ...]
    totals: Counters
    gateway: GatewayLoad = GatewayLoad()


def _c_environment(env: Environment) -> tuple[_CEnvironment, list[object]]:
    """Traduit l'environnement en structure C. Retourne aussi les tampons à garder vivants."""
    keep: list[object] = []
    c_env = _CEnvironment()
    c_env.gateway_height_m = env.gateway_height_m
    c_env.device_height_m = env.device_height_m
    if env.terrain is not None:
        t = env.terrain
        buf = (ctypes.c_float * len(t.z)).from_buffer(t.z)
        keep.append(buf)
        c_env.grid_z = ctypes.cast(buf, ctypes.POINTER(ctypes.c_float))
        c_env.grid_nx = t.nx
        c_env.grid_ny = t.ny
        c_env.grid_origin_x_m = t.origin_x_m
        c_env.grid_origin_y_m = t.origin_y_m
        c_env.grid_cell_m = t.cell_m
    if env.obstacles:
        c_obs = (_CObstacle * len(env.obstacles))()
        for i, o in enumerate(env.obstacles):
            c_obs[i].x_min_m = o.x_min_m
            c_obs[i].y_min_m = o.y_min_m
            c_obs[i].x_max_m = o.x_max_m
            c_obs[i].y_max_m = o.y_max_m
            c_obs[i].height_m = o.height_m
            c_obs[i].attenuation_db = o.attenuation_db
        keep.append(c_obs)
        c_env.obstacles = ctypes.cast(c_obs, ctypes.POINTER(_CObstacle))
        c_env.obstacle_count = len(env.obstacles)
    return c_env, keep


def coverage_radii(gateway: Gateway, propagation: Propagation, max_path_loss_db: float,
                   environment: Optional[Environment], step_m: float,
                   azimuths: int) -> tuple[float, ...]:
    """Portée réelle (m) par azimut autour de la passerelle, relief et obstacles inclus.

    Chaque valeur est la distance maximale où la perte totale reste sous
    `max_path_loss_db`. Le calcul et sa borne de travail sont dans le cœur natif.
    Le shadowing n'est pas appliqué à la couverture (portée médiane déterministe).
    """
    if not 1 <= azimuths <= 720:
        raise ValueError("azimuths doit être compris entre 1 et 720")
    if not math.isfinite(step_m) or step_m < 1.0:
        raise ValueError("step_m doit être supérieur ou égal à 1 m")
    if not math.isfinite(max_path_loss_db):
        raise ValueError("max_path_loss_db doit être un nombre fini")
    c_gw = _CGateway(gateway.x_m, gateway.y_m, gateway.antenna_gain_dbi)
    c_prop = _CPropagation(propagation.frequency_hz, propagation.reference_distance_m,
                           propagation.exponent, propagation.capture_threshold_db,
                           propagation.shadowing_sigma_db, propagation.shadowing_seed)
    keep: list[object] = []
    if environment is None:
        c_env_ref = None
    else:
        c_env_struct, keep = _c_environment(environment)
        c_env_ref = ctypes.byref(c_env_struct)
    out = (ctypes.c_double * azimuths)()
    status = LIB.lsim_coverage_radii(
        ctypes.byref(c_gw), ctypes.byref(c_prop), max_path_loss_db, c_env_ref,
        step_m, azimuths, out)
    del keep
    if status != 0:
        raise StatusError(status)
    return tuple(out)


def simulate_uplinks(devices: Sequence[EndDevice], gateway: Gateway,
                     propagation: Propagation,
                     environment: Optional[Environment] = None) -> SimulationResult:
    """Simule les liaisons montantes vers une passerelle et retourne les compteurs.

    `environment` optionnel : relief et obstacles. Sans environnement, le terrain est
    plat et sans obstacle (résultat identique au modèle log-distance seul).
    """
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
                           propagation.exponent, propagation.capture_threshold_db,
                           propagation.shadowing_sigma_db, propagation.shadowing_seed)
    c_stats = (_CDeviceStats * n)()
    c_tot = _CSimStats()
    if environment is None:
        c_env_ref, keep = None, []
    else:
        c_env_struct, keep = _c_environment(environment)
        c_env_ref = ctypes.byref(c_env_struct)
    status = LIB.lsim_simulate_uplinks_env(
        c_devs if n else None, n, ctypes.byref(c_gw), ctypes.byref(c_prop),
        c_env_ref, c_stats if n else None, ctypes.byref(c_tot))
    del keep
    if status != 0:
        raise StatusError(status)

    per = tuple(
        Counters(s.sent, s.received, s.lost_sensitivity, s.lost_collision, s.airtime_ns)
        for s in c_stats
    )
    tot = Counters(c_tot.sent, c_tot.received, c_tot.lost_sensitivity, c_tot.lost_collision,
                   c_tot.airtime_ns)
    load = GatewayLoad(c_tot.gateway_busy_ns, c_tot.gateway_peak_concurrent,
                       c_tot.observation_ns, c_tot.gateway_utilization)
    return SimulationResult(per_device=per, totals=tot, gateway=load)
