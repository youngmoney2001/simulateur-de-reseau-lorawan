"""Simulation des liaisons montantes, calculée par le cœur natif.

Python prépare et lit les données ; le moteur (file d'événements, collisions,
capture) est entièrement dans le cœur C++. Les limites (10 000 dispositifs,
5 000 000 transmissions) sont appliquées par le natif.
"""

from __future__ import annotations

import ctypes
import dataclasses
import math
from dataclasses import dataclass
from enum import IntEnum
from typing import Optional, Sequence

from lsim._native import (
    LIB,
    _CDeviceStats,
    _CDownlinkPlan,
    _CDownlinkStats,
    _CSimStats,
    _CInterval,
    _CTxRecord,
    _CEndDevice,
    _CEnvironment,
    _CGateway,
    _CGatewayRxStats,
    _CDownlinkRecord,
    _CDownlinkRule,
    _CMultiTxRecord,
    _CNetworkStats,
    _CObstacle,
    _CPropagation,
)
from lsim.environment import Environment
from lsim.lora import StatusError

MAX_END_DEVICES = 10_000
MAX_TRACE_RECORDS = 200_000  # borne de trace (cœur : statut 309)
MAX_DOWNLINKS_PER_DEVICE = 100_000
MAX_RX_WINDOW_NS = 10_000_000_000
MAX_PERIODICITY = 7
MAX_DRIFT_PPM = 1000
_NS_PER_MIN = 60_000_000_000


class DeviceClass(IntEnum):
    """Classe LoRaWAN : A (réception après chaque uplink), B (ping slots), C (écoute continue)."""

    A = 0
    B = 1
    C = 2


@dataclass(frozen=True)
class DownlinkRequests:
    """Requêtes de downlink d'un dispositif : la k-ième part à first + k × period.

    Classe B : la balise est supposée reçue à chaque période de 128 s depuis le temps 0.
    rx_window_ns : durée RX1, hypothèse de modélisation (la spec ne la fixe pas ici).
    """

    device_class: DeviceClass
    count: int
    first_request_ns: int = 0
    request_period_ns: int = 0
    rx_window_ns: int = 1_000_000_000
    dev_addr: int = 0
    periodicity: int = 0
    clock_drift_ppm: int = 0

    def __post_init__(self) -> None:
        try:
            cls = DeviceClass(self.device_class)
        except ValueError as exc:
            raise ValueError("device_class doit valoir A, B ou C") from exc
        object.__setattr__(self, "device_class", cls)
        if isinstance(self.count, bool) or not 0 <= self.count <= MAX_DOWNLINKS_PER_DEVICE:
            raise ValueError(f"count doit être compris entre 0 et {MAX_DOWNLINKS_PER_DEVICE}")
        if self.first_request_ns < 0:
            raise ValueError("first_request_ns doit être positif ou nul")
        if self.count > 1 and self.request_period_ns <= 0:
            raise ValueError("request_period_ns doit être strictement positif si count > 1")
        if not 0 <= self.rx_window_ns <= MAX_RX_WINDOW_NS:
            raise ValueError("rx_window_ns doit être compris entre 0 et 10 s")
        if not 0 <= self.dev_addr < 2**32:
            raise ValueError("dev_addr doit être un entier sur 32 bits")
        if not 0 <= self.periodicity <= MAX_PERIODICITY:
            raise ValueError(f"periodicity doit être compris entre 0 et {MAX_PERIODICITY}")
        if not 0 <= self.clock_drift_ppm <= MAX_DRIFT_PPM:
            raise ValueError(f"clock_drift_ppm doit être compris entre 0 et {MAX_DRIFT_PPM}")


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
    duty_cycle: float = 1.0  # rapport cyclique maximal, ]0, 1] ; 1 = sans limite
    downlink: Optional[DownlinkRequests] = None  # requêtes de downlink (None = aucune)

    def __post_init__(self) -> None:
        if not 0.0 < self.duty_cycle <= 1.0:
            raise ValueError("duty_cycle doit être dans ]0, 1]")
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
    lost_gateway_busy: int = 0  # reçue pendant une émission de la passerelle (demi-duplex)


@dataclass(frozen=True)
class DownlinkCounters:
    """Downlinks : requêtes, livrées (fenêtre utilisable avant la fin de l'observation), latence."""

    requested: int = 0
    delivered: int = 0
    latency_sum_ns: int = 0
    latency_max_ns: int = 0

    @property
    def delivery_ratio(self) -> float:
        return self.delivered / self.requested if self.requested else 0.0

    @property
    def mean_latency_ns(self) -> float:
        return self.latency_sum_ns / self.delivered if self.delivered else 0.0


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
    downlink_per_device: tuple[DownlinkCounters, ...] = ()
    downlink_totals: DownlinkCounters = DownlinkCounters()


def _gateway_rx(s) -> GatewayRxCounters:
    return GatewayRxCounters(s.received, s.lost_sensitivity, s.lost_collision,
                             s.lost_gateway_busy, s.audible_frames, s.busy_ns,
                             s.peak_concurrent, s.observation_ns)


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


def environment_path_loss_matrix(positions: Sequence[tuple[float, float]],
                                 propagation: Propagation,
                                 environment: Environment) -> tuple[float, ...]:
    """Pertes de propagation totales (dB) entre toutes les paires de points, relief et obstacles.

    Résultat à plat : `out[i * n + j]`, émetteur i, récepteur j ; diagonale 0. Les deux
    extrémités sont à la hauteur passerelle (cas du mesh entre passerelles). Pas de shadowing.
    """
    n = len(positions)
    if not 1 <= n <= 64:
        raise ValueError("entre 1 et 64 points")
    env = dataclasses.replace(environment, device_height_m=environment.gateway_height_m)
    c_prop = _CPropagation(propagation.frequency_hz, propagation.reference_distance_m,
                           propagation.exponent, propagation.capture_threshold_db, 0.0, 0)
    xs = (ctypes.c_double * n)(*[float(p[0]) for p in positions])
    ys = (ctypes.c_double * n)(*[float(p[1]) for p in positions])
    c_env, keep = _c_environment(env)
    out = (ctypes.c_double * (n * n))()
    status = LIB.lsim_env_path_loss_matrix(ctypes.byref(c_prop), ctypes.byref(c_env), n, xs, ys, out)
    del keep
    if status != 0:
        raise StatusError(status)
    return tuple(out)


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


@dataclass(frozen=True)
class TxRecord:
    """Une transmission de la trace native. outcome : 0 sous sensibilité, 1 collision, 2 reçue."""

    device_index: int
    start_ns: int
    end_ns: int
    spreading_factor: int
    rssi_dbm: float
    outcome: int

    OUTCOME_LOST_SENSITIVITY = 0
    OUTCOME_LOST_COLLISION = 1
    OUTCOME_RECEIVED = 2
    OUTCOME_LOST_GATEWAY_BUSY = 3  # passerelle en émission pendant la trame


@dataclass(frozen=True)
class TraceResult:
    """Compteurs et trace par transmission, produits par le même appel natif."""

    per_device: tuple[Counters, ...]
    totals: Counters
    gateway: GatewayLoad
    records: tuple[TxRecord, ...]


def _c_end_devices(devices: Sequence[EndDevice]) -> ctypes.Array:
    c_devs = (_CEndDevice * len(devices))()
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
        c.duty_cycle = d.duty_cycle
    return c_devs


def simulate_uplinks_trace(devices: Sequence[EndDevice], gateway: Gateway,
                           propagation: Propagation,
                           environment: Optional[Environment] = None,
                           gateway_busy: Sequence[tuple[int, int]] = ()) -> TraceResult:
    """Comme `simulate_uplinks`, avec une entrée de trace par transmission.

    `gateway_busy` : périodes [début, fin) pendant lesquelles la passerelle émet (ns). Une trame
    reçue qui les chevauche est perdue (demi-duplex, issue LOST_GATEWAY_BUSY).

    Les temps de la trace (début, fin) sont ceux du moteur, en nanosecondes. La trace
    est bornée par le cœur (statut 309 au-delà de 200 000 émissions).
    """
    if len(gateway_busy) > MAX_TRACE_RECORDS:
        raise ValueError("trop de périodes d'émission passerelle")
    c_busy = None
    if gateway_busy:
        c_busy = (_CInterval * len(gateway_busy))()
        for k, (start, end) in enumerate(gateway_busy):
            c_busy[k].start_ns = start
            c_busy[k].end_ns = end
    if len(devices) > MAX_END_DEVICES:
        raise ValueError(f"au plus {MAX_END_DEVICES} dispositifs par simulation")
    n = len(devices)
    c_devs = _c_end_devices(devices)
    c_gw = _CGateway(gateway.x_m, gateway.y_m, gateway.antenna_gain_dbi)
    c_prop = _CPropagation(propagation.frequency_hz, propagation.reference_distance_m,
                           propagation.exponent, propagation.capture_threshold_db,
                           propagation.shadowing_sigma_db, propagation.shadowing_seed)
    c_stats = (_CDeviceStats * n)()
    c_tot = _CSimStats()
    keep: list[object] = []
    if environment is None:
        c_env_ref = None
    else:
        c_env_struct, keep = _c_environment(environment)
        c_env_ref = ctypes.byref(c_env_struct)

    # Taille requise : le cœur la renvoie en cas de tampon insuffisant (statut 308).
    capacity = sum(d.messages for d in devices)
    if capacity > MAX_TRACE_RECORDS:
        raise ValueError(f"trace limitée à {MAX_TRACE_RECORDS} émissions par simulation")
    count = ctypes.c_size_t(0)
    records = (_CTxRecord * capacity)() if capacity else None
    status = LIB.lsim_simulate_uplinks_trace(
        c_devs if n else None, n, ctypes.byref(c_gw), ctypes.byref(c_prop), c_env_ref,
        c_stats if n else None, ctypes.byref(c_tot), records, capacity, ctypes.byref(count),
        c_busy, len(gateway_busy))
    del keep
    if status != 0:
        raise StatusError(status)

    per = tuple(
        Counters(s.sent, s.received, s.lost_sensitivity, s.lost_collision, s.airtime_ns,
                 s.lost_gateway_busy)
        for s in c_stats
    )
    tot = Counters(c_tot.sent, c_tot.received, c_tot.lost_sensitivity, c_tot.lost_collision,
                   c_tot.airtime_ns, c_tot.lost_gateway_busy)
    load = GatewayLoad(c_tot.gateway_busy_ns, c_tot.gateway_peak_concurrent,
                       c_tot.observation_ns, c_tot.gateway_utilization)
    trace = tuple(
        TxRecord(r.device_index, r.start_ns, r.end_ns, r.spreading_factor, r.rssi_dbm, r.outcome)
        for r in (records[:count.value] if records is not None else ())
    )
    return TraceResult(per, tot, load, trace)


@dataclass(frozen=True)
class NetworkCounters:
    """Compteurs réseau après déduplication serveur (une livraison par trame)."""

    sent: int
    received: int
    duplicates: int
    lost_sensitivity: int
    lost_collision: int
    lost_gateway_busy: int
    airtime_ns: int


@dataclass(frozen=True)
class GatewayRxCounters:
    """Trames décodées ou perdues à une passerelle donnée, et sa charge de réception.

    La charge porte sur les trames audibles (RSSI >= sensibilité) : union des intervalles
    (`busy_ns`), simultanéité maximale (`peak_concurrent`), sur la fenêtre d'observation.
    """

    received: int
    lost_sensitivity: int
    lost_collision: int
    lost_gateway_busy: int
    audible_frames: int = 0
    busy_ns: int = 0
    peak_concurrent: int = 0
    observation_ns: int = 0

    @property
    def utilization(self) -> float:
        return self.busy_ns / self.observation_ns if self.observation_ns > 0 else 0.0


@dataclass(frozen=True)
class MultiTxRecord:
    """Issue réseau d'une émission. outcome : 0 sensibilité, 1 collision, 2 reçue, 3 passerelle occupée."""

    device_index: int
    start_ns: int
    end_ns: int
    spreading_factor: int
    receivers: int
    best_gateway: int      # -1 si aucune passerelle ne décode
    best_rssi_dbm: float
    outcome: int
    decoded_mask: int = 0  # bit g : la passerelle g a décodé la trame (g < 64)
    join_request: bool = False  # join-request d'un dispositif non jointé (rule.join)


@dataclass(frozen=True)
class MultiGatewayResult:
    per_device: tuple[Counters, ...]
    network: NetworkCounters
    per_gateway: tuple[GatewayRxCounters, ...]
    trace: tuple[MultiTxRecord, ...] = ()


MAX_GATEWAYS = 64


def simulate_uplinks_multi(devices: Sequence[EndDevice], gateways: Sequence[Gateway],
                           propagation: Propagation,
                           environment: Optional[Environment] = None,
                           gateway_busy: Optional[Sequence[Sequence[tuple[int, int]]]] = None,
                           with_trace: bool = False) -> MultiGatewayResult:
    """Simule les liaisons montantes vers plusieurs passerelles, avec déduplication serveur.

    Chaque passerelle reçoit indépendamment (sensibilité, collision, puis demi-duplex à son
    propre RSSI). Une trame est livrée au serveur si au moins une passerelle la décode ; les copies
    sont comptées.

    `gateway_busy` : pour chaque passerelle, ses périodes d'émission [début, fin) en ns (liste de
    même longueur que `gateways`). `with_trace` : renvoie une entrée par émission.
    """
    if len(devices) > MAX_END_DEVICES:
        raise ValueError(f"au plus {MAX_END_DEVICES} dispositifs par simulation")
    if not 1 <= len(gateways) <= MAX_GATEWAYS:
        raise ValueError(f"entre 1 et {MAX_GATEWAYS} passerelles")
    if gateway_busy is not None and len(gateway_busy) != len(gateways):
        raise ValueError("gateway_busy doit compter une liste par passerelle")
    n = len(devices)
    g_count = len(gateways)
    total_messages = sum(d.messages for d in devices)
    if with_trace and total_messages > MAX_TRACE_RECORDS:
        raise ValueError(f"trace limitée à {MAX_TRACE_RECORDS} émissions")
    c_devs = _c_end_devices(devices)
    c_gws = (_CGateway * g_count)(*[
        _CGateway(g.x_m, g.y_m, g.antenna_gain_dbi) for g in gateways])
    c_prop = _CPropagation(propagation.frequency_hz, propagation.reference_distance_m,
                           propagation.exponent, propagation.capture_threshold_db,
                           propagation.shadowing_sigma_db, propagation.shadowing_seed)
    c_stats = (_CDeviceStats * n)()
    c_tot = _CNetworkStats()
    c_gw_stats = (_CGatewayRxStats * g_count)()
    # Périodes passerelle : tableau plat et compte par passerelle ; NULL si aucune.
    c_busy, c_busy_counts, n_busy = None, None, 0
    if gateway_busy is not None:
        flat = [(a, b) for per in gateway_busy for (a, b) in per]
        n_busy = len(flat)
        if n_busy > MAX_TRACE_RECORDS:
            raise ValueError("trop de périodes d'émission passerelle")
        c_busy = (_CInterval * max(n_busy, 1))()
        for k, (a, b) in enumerate(flat):
            c_busy[k].start_ns = a
            c_busy[k].end_ns = b
        c_busy_counts = (ctypes.c_size_t * g_count)(*[len(per) for per in gateway_busy])
    c_records = (_CMultiTxRecord * max(total_messages, 1))() if with_trace else None
    c_record_count = ctypes.c_size_t(0)
    if environment is None:
        c_env_ref, keep = None, []
    else:
        c_env_struct, keep = _c_environment(environment)
        c_env_ref = ctypes.byref(c_env_struct)
    status = LIB.lsim_simulate_uplinks_multi(
        c_devs if n else None, n, c_gws, g_count, ctypes.byref(c_prop), c_env_ref,
        c_stats if n else None, ctypes.byref(c_tot), c_gw_stats,
        c_busy, c_busy_counts,
        c_records, total_messages if with_trace else 0,
        ctypes.byref(c_record_count) if with_trace else None)
    del keep
    if status != 0:
        raise StatusError(status)
    per = tuple(
        Counters(s.sent, s.received, s.lost_sensitivity, s.lost_collision, s.airtime_ns,
                 s.lost_gateway_busy)
        for s in c_stats
    )
    network = NetworkCounters(c_tot.sent, c_tot.received, c_tot.duplicates,
                              c_tot.lost_sensitivity, c_tot.lost_collision,
                              c_tot.lost_gateway_busy, c_tot.airtime_ns)
    per_gw = tuple(_gateway_rx(s) for s in c_gw_stats)
    trace: tuple[MultiTxRecord, ...] = ()
    if with_trace:
        trace = tuple(
            MultiTxRecord(r.device_index, r.start_ns, r.end_ns, r.spreading_factor, r.receivers,
                          r.best_gateway, r.best_rssi_dbm, r.outcome, r.decoded_mask)
            for r in c_records[:c_record_count.value])
    return MultiGatewayResult(per_device=per, network=network, per_gateway=per_gw, trace=trace)


@dataclass(frozen=True)
class DownlinkRule:
    """Règle de downlink multi-passerelles (voir lsim/engine.hpp)."""

    ack_uplinks: bool = False
    every: int = 0
    payload_bytes: int = 10
    gateway_tx_power_dbm: float = 14.0
    device_antenna_gain_dbi: float = 0.0
    device_rx_offset_db: float = 0.0
    join: bool = False  # join-request décodée -> join-accept (17 octets, fin + 5 s)


@dataclass(frozen=True)
class DownlinkRecord:
    """Downlink planifié. outcome : 0 reçu, 1 sous la sensibilité, 2 passerelle hors RX1,
    3 dispositif en émission. start_ns/end_ns = -1 si non émis. join : join-accept."""

    device_index: int
    gateway_index: int
    data: bool
    t_open_ns: int
    start_ns: int
    end_ns: int
    outcome: int
    join: bool = False


@dataclass(frozen=True)
class MultiDownlinkResult:
    per_device: tuple[Counters, ...]
    network: NetworkCounters
    per_gateway: tuple[GatewayRxCounters, ...]
    trace: tuple[MultiTxRecord, ...]
    downlinks: tuple[DownlinkRecord, ...]


def simulate_multi_downlinks(devices: Sequence[EndDevice], gateways: Sequence[Gateway],
                             propagation: Propagation, rule: DownlinkRule,
                             environment: Optional[Environment] = None) -> MultiDownlinkResult:
    """Passerelles multiples avec downlinks et demi-duplex par passerelle (calcul exact, C++).

    Chaque uplink décodé est acquitté ou reçoit une charge par la meilleure passerelle décodeuse.
    Chaque passerelle sérialise ses downlinks ; elle ne décode pas pendant les siens.
    """
    if len(devices) > MAX_END_DEVICES:
        raise ValueError(f"au plus {MAX_END_DEVICES} dispositifs par simulation")
    if not 1 <= len(gateways) <= MAX_GATEWAYS:
        raise ValueError(f"entre 1 et {MAX_GATEWAYS} passerelles")
    if not 0 <= rule.payload_bytes <= 242:
        raise ValueError("charge de downlink entre 0 et 242 octets")
    if rule.every < 0:
        raise ValueError("every doit être positif ou nul")
    n = len(devices)
    g_count = len(gateways)
    total_messages = sum(d.messages for d in devices)
    if total_messages > MAX_TRACE_RECORDS:
        raise ValueError(f"trace limitée à {MAX_TRACE_RECORDS} émissions")
    c_devs = _c_end_devices(devices)
    c_gws = (_CGateway * g_count)(*[
        _CGateway(g.x_m, g.y_m, g.antenna_gain_dbi) for g in gateways])
    c_prop = _CPropagation(propagation.frequency_hz, propagation.reference_distance_m,
                           propagation.exponent, propagation.capture_threshold_db,
                           propagation.shadowing_sigma_db, propagation.shadowing_seed)
    c_rule = _CDownlinkRule(1 if rule.ack_uplinks else 0, rule.every, rule.payload_bytes,
                            rule.gateway_tx_power_dbm, rule.device_antenna_gain_dbi,
                            rule.device_rx_offset_db, 1 if rule.join else 0)
    c_stats = (_CDeviceStats * n)()
    c_tot = _CNetworkStats()
    c_gw_stats = (_CGatewayRxStats * g_count)()
    c_records = (_CMultiTxRecord * max(total_messages, 1))()
    c_record_count = ctypes.c_size_t(0)
    # Les downlinks sont au plus une par uplink décodé : borne = nombre d'émissions.
    c_dls = (_CDownlinkRecord * max(total_messages, 1))()
    c_dl_count = ctypes.c_size_t(0)
    if environment is None:
        c_env_ref, keep = None, []
    else:
        c_env_struct, keep = _c_environment(environment)
        c_env_ref = ctypes.byref(c_env_struct)
    status = LIB.lsim_simulate_uplinks_multi_dl(
        c_devs if n else None, n, c_gws, g_count, ctypes.byref(c_prop), ctypes.byref(c_rule),
        c_env_ref, c_stats if n else None, ctypes.byref(c_tot), c_gw_stats,
        c_records, total_messages, ctypes.byref(c_record_count),
        c_dls, total_messages, ctypes.byref(c_dl_count))
    del keep
    if status != 0:
        raise StatusError(status)
    per = tuple(
        Counters(s.sent, s.received, s.lost_sensitivity, s.lost_collision, s.airtime_ns,
                 s.lost_gateway_busy)
        for s in c_stats
    )
    network = NetworkCounters(c_tot.sent, c_tot.received, c_tot.duplicates,
                              c_tot.lost_sensitivity, c_tot.lost_collision,
                              c_tot.lost_gateway_busy, c_tot.airtime_ns)
    per_gw = tuple(_gateway_rx(s) for s in c_gw_stats)
    trace = tuple(
        MultiTxRecord(r.device_index, r.start_ns, r.end_ns, r.spreading_factor, r.receivers,
                      r.best_gateway, r.best_rssi_dbm, r.outcome, r.decoded_mask,
                      bool(r.join_request))
        for r in c_records[:c_record_count.value])
    dls = tuple(
        DownlinkRecord(r.device_index, r.gateway_index, bool(r.data), r.t_open_ns, r.start_ns,
                       r.end_ns, r.outcome, bool(r.join))
        for r in c_dls[:c_dl_count.value])
    return MultiDownlinkResult(per_device=per, network=network, per_gateway=per_gw,
                               trace=trace, downlinks=dls)


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
    c_devs = _c_end_devices(devices)
    c_gw = _CGateway(gateway.x_m, gateway.y_m, gateway.antenna_gain_dbi)
    c_prop = _CPropagation(propagation.frequency_hz, propagation.reference_distance_m,
                           propagation.exponent, propagation.capture_threshold_db,
                           propagation.shadowing_sigma_db, propagation.shadowing_seed)
    c_stats = (_CDeviceStats * n)()
    c_tot = _CSimStats()
    c_dl_stats = (_CDownlinkStats * n)()
    c_dl_tot = _CDownlinkStats()
    # Plans de downlink : tableau aligné sur les dispositifs ; NULL si aucun n'en demande.
    c_plans = None
    if any(d.downlink is not None and d.downlink.count > 0 for d in devices):
        c_plans = (_CDownlinkPlan * n)()
        for i, d in enumerate(devices):
            p = c_plans[i]
            if d.downlink is None:
                continue
            p.device_class = int(d.downlink.device_class)
            p.count = d.downlink.count
            p.first_request_ns = d.downlink.first_request_ns
            p.request_period_ns = d.downlink.request_period_ns
            p.rx_window_ns = d.downlink.rx_window_ns
            p.dev_addr = d.downlink.dev_addr
            p.periodicity = d.downlink.periodicity
            p.clock_drift_ppm = d.downlink.clock_drift_ppm
    if environment is None:
        c_env_ref, keep = None, []
    else:
        c_env_struct, keep = _c_environment(environment)
        c_env_ref = ctypes.byref(c_env_struct)
    status = LIB.lsim_simulate_downlinks_env(
        c_devs if n else None, c_plans, n, ctypes.byref(c_gw), ctypes.byref(c_prop),
        c_env_ref, c_stats if n else None, ctypes.byref(c_tot),
        c_dl_stats if n else None, ctypes.byref(c_dl_tot))
    del keep
    if status != 0:
        raise StatusError(status)

    per = tuple(
        Counters(s.sent, s.received, s.lost_sensitivity, s.lost_collision, s.airtime_ns,
                 s.lost_gateway_busy)
        for s in c_stats
    )
    tot = Counters(c_tot.sent, c_tot.received, c_tot.lost_sensitivity, c_tot.lost_collision,
                   c_tot.airtime_ns, c_tot.lost_gateway_busy)
    load = GatewayLoad(c_tot.gateway_busy_ns, c_tot.gateway_peak_concurrent,
                       c_tot.observation_ns, c_tot.gateway_utilization)
    dl_per = tuple(
        DownlinkCounters(s.requested, s.delivered, s.latency_sum_ns, s.latency_max_ns)
        for s in c_dl_stats
    )
    dl_tot = DownlinkCounters(c_dl_tot.requested, c_dl_tot.delivered, c_dl_tot.latency_sum_ns,
                              c_dl_tot.latency_max_ns)
    return SimulationResult(per_device=per, totals=tot, gateway=load,
                            downlink_per_device=dl_per, downlink_totals=dl_tot)
