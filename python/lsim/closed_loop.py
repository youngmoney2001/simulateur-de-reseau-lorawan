"""Boucle fermée (S2, S3) : LinkADRReq, DutyCycleReq et réservations MAC (LinkCheck, DeviceTime,
DevStatus), pont vers `lsim_simulate_closed_loop_v2`.

Passerelle unique, sans jointure. Une seule exécution native : les
descentes sont créées dans le moteur, au fil des uplinks reçus. Le chemin causal S1
(`downlink_plan.simulate_causal`) reste la référence sans commande : `tests/test_closed_loop.py`
exige l'égalité des compteurs quand aucune commande n'est active.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass, field
from typing import Optional, Sequence

from lsim._native import (
    LIB,
    _CDeviceStats,
    _CEndDevice,
    _CEnvironment,
    _CGateway,
    _CInterval,
    _CPropagation,
    _CSimStats,
)
from lsim.downlink_plan import _CPlanDevice, _CPlanOptions
from lsim.lora import StatusError
from lsim.simulator import (
    MAX_END_DEVICES,
    MAX_TRACE_RECORDS,
    Counters,
    GatewayLoad,
    _c_end_devices,
    _c_environment,
)

LOOP_STATUS_PLAN_BASE = 950
CMD_LINK_ADR = 1
CMD_DUTY_CYCLE = 2
CMD_LINK_CHECK = 4
CMD_DEVICE_TIME = 8
CMD_DEVICE_STATUS = 16
MAC_LINK_CHECK = 1      # bits de `MacSlot.flags`
MAC_DEVICE_TIME = 2
MAC_DEVICE_STATUS = 4
ANSWER_DEVICE_STATUS = 4  # bit de `LoopUplink.answer_mask`
KIND_ACK = 1
KIND_DATA = 2
KIND_MAC = 3
_KIND_NAMES = {KIND_ACK: "ack", KIND_DATA: "data", KIND_MAC: "mac"}


class _CLoopRegion(ctypes.Structure):
    _fields_ = [("dr_sf", ctypes.c_uint8 * 16), ("max_dr", ctypes.c_uint8),
                ("max_tx_power_index", ctypes.c_uint8), ("power_step_tenth_db", ctypes.c_int32),
                ("max_eirp_dbm", ctypes.c_double), ("duty_limit", ctypes.c_double * 16)]


class _CLoopOptions(ctypes.Structure):
    _fields_ = [("protocol", _CPlanOptions), ("adr", ctypes.c_uint8),
                ("installation_margin_tenth_db", ctypes.c_int32), ("duty_cycle", ctypes.c_uint8),
                ("duty_cycle_exponent", ctypes.c_uint8)]


class _CLoopMac(ctypes.Structure):
    _fields_ = [("device_index", ctypes.c_uint32), ("rank", ctypes.c_uint32),
                ("extra_bytes", ctypes.c_uint8), ("flags", ctypes.c_uint8)]


class _CLoopUplink(ctypes.Structure):
    _fields_ = [("device_index", ctypes.c_uint32), ("start_ns", ctypes.c_int64),
                ("end_ns", ctypes.c_int64), ("spreading_factor", ctypes.c_uint8),
                ("dr", ctypes.c_int8), ("power_index", ctypes.c_uint8), ("rssi_dbm", ctypes.c_double),
                ("outcome", ctypes.c_uint8), ("answer_mask", ctypes.c_uint8),
                ("answer_ok", ctypes.c_uint8)]


class _CLoopDownlink(ctypes.Structure):
    _fields_ = [("uplink_index", ctypes.c_uint32), ("device_index", ctypes.c_uint32),
                ("kind", ctypes.c_uint8), ("commands", ctypes.c_uint8), ("t_open_ns", ctypes.c_int64),
                ("start_ns", ctypes.c_int64), ("air_ns", ctypes.c_int64),
                ("device_missed", ctypes.c_uint8), ("delivered", ctypes.c_uint8),
                ("req_dr", ctypes.c_uint8), ("req_power_index", ctypes.c_uint8)]


LIB.lsim_simulate_closed_loop_v2.restype = ctypes.c_int32
LIB.lsim_simulate_closed_loop_v2.argtypes = [
    ctypes.POINTER(_CEndDevice), ctypes.c_size_t, ctypes.POINTER(_CPlanDevice),
    ctypes.POINTER(_CLoopRegion), ctypes.POINTER(_CGateway), ctypes.POINTER(_CPropagation),
    ctypes.POINTER(_CEnvironment), ctypes.POINTER(_CLoopOptions),
    ctypes.POINTER(_CLoopMac), ctypes.c_size_t, ctypes.POINTER(_CDeviceStats),
    ctypes.POINTER(_CSimStats), ctypes.POINTER(_CLoopUplink), ctypes.c_size_t,
    ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(_CLoopDownlink), ctypes.c_size_t,
    ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(_CInterval), ctypes.c_size_t,
    ctypes.POINTER(ctypes.c_size_t),
]


@dataclass(frozen=True)
class LoopRegion:
    """Paramètres régionaux d'un dispositif (voir `LoopRegion` dans engine.hpp).

    `dr_sf[i]` : SF du débit i (0 = indisponible). `max_tx_power_index` : dernier index valide.
    `max_eirp_dbm` : PIRE de l'index 0 du plan (+inf si non définie). `duty_limit[i]` : limite
    réglementaire du duty cycle à l'index i, dans ]0, 1].
    """

    dr_sf: tuple[int, ...]
    max_dr: int
    max_tx_power_index: int = 0
    power_step_tenth_db: int = 20
    max_eirp_dbm: float = float("inf")
    duty_limit: tuple[float, ...] = (1.0,) * 16


@dataclass(frozen=True)
class LoopOptions:
    confirmed_uplinks: bool = False
    downlink_every: int = 0
    downlink_payload_bytes: int = 10
    gateway_tx_power_dbm: float = 14.0
    device_antenna_gain_dbi: float = 0.0
    device_rx_offset_db: float = 0.0
    adr: bool = False
    installation_margin_tenth_db: int = 0
    duty_cycle: bool = False
    duty_cycle_exponent: int = 0


@dataclass(frozen=True)
class MacSlot:
    """Calendrier MAC d'une émission (`device` : indice, `rank` : 1-based).

    `extra_bytes` : octets MAC réservés dans l'uplink (0..15). `flags` : MAC_LINK_CHECK,
    MAC_DEVICE_TIME, MAC_DEVICE_STATUS, dans la descente qui répond à cet uplink.
    """

    device: int
    rank: int
    extra_bytes: int
    flags: int


@dataclass(frozen=True)
class LoopUplink:
    device: int
    start_ns: int
    end_ns: int
    spreading_factor: int
    dr: Optional[int]          # None : pas de table régionale
    power_index: int
    rssi_dbm: float
    outcome: str
    answer_mask: int           # bit 0 LinkADRAns, bit 1 DutyCycleAns, bit 2 DevStatusAns
    answer_ok: int             # bit 0 débit acquitté, bit 1 puissance acquittée


@dataclass(frozen=True)
class LoopDownlink:
    uplink: int                # indice dans LoopOutcome.uplinks
    device: int
    kind: str                  # ack, data, mac
    commands: int              # CMD_* (commandes et réponses MAC portées)
    t_open_ns: int
    start_ns: Optional[int]    # None : pas de créneau passerelle dans la RX1
    air_ns: int
    device_missed: bool
    delivered: bool
    req_dr: int
    req_power_index: int


@dataclass(frozen=True)
class LoopOutcome:
    per_device: tuple[Counters, ...]
    totals: Counters
    load: GatewayLoad
    uplinks: tuple[LoopUplink, ...]
    downlinks: tuple[LoopDownlink, ...]
    busy: tuple[tuple[int, int], ...]


_OUTCOMES = {0: "lost_sensitivity", 1: "lost_collision", 2: "received", 3: "lost_gateway_busy"}
OUTCOME_CODES = {v: k for k, v in _OUTCOMES.items()}


def simulate_closed_loop(devices: Sequence, gateway, propagation, environment, radios: Sequence,
                         regions: Sequence[LoopRegion], options: LoopOptions,
                         mac: Sequence[MacSlot] = ()) -> LoopOutcome:
    """Boucle fermée S2 en une seule exécution native. Lève `StatusError` si le cœur refuse l'entrée.

    `devices`, `radios` et `regions` : un élément par dispositif, même ordre. `regions` n'est lu
    que si `options.adr` est vrai. Les capacités de sortie sont dimensionnées sur le nombre total
    d'émissions : aucune réexécution n'est nécessaire.
    """
    n = len(devices)
    if n > MAX_END_DEVICES:
        raise ValueError(f"au plus {MAX_END_DEVICES} dispositifs par simulation")
    if len(radios) != n:
        raise ValueError("un paramètre radio par dispositif")
    if len(regions) != n:
        raise ValueError("un jeu de paramètres régionaux par dispositif")
    capacity = sum(d.messages for d in devices)
    if capacity > MAX_TRACE_RECORDS:
        raise ValueError(f"trace limitée à {MAX_TRACE_RECORDS} émissions par simulation")
    c_mac = (_CLoopMac * max(1, len(mac)))()
    for k, m in enumerate(mac):
        c_mac[k].device_index = m.device
        c_mac[k].rank = m.rank
        c_mac[k].extra_bytes = m.extra_bytes
        c_mac[k].flags = m.flags

    c_devs = _c_end_devices(devices)
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

    c_radios = (_CPlanDevice * max(1, n))()
    for i, d in enumerate(radios):
        c_radios[i].freq_hz = d.freq_hz
        c_radios[i].dr = -1 if d.dr is None else d.dr
        c_radios[i].rx1_hz = d.rx1_hz
        c_radios[i].tx_power_dbm = d.tx_power_dbm
        c_radios[i].rx1_sf = d.rx1_sf
        c_radios[i].rx1_bw_hz = d.rx1_bw_hz

    c_regions = (_CLoopRegion * max(1, n))()
    for i, r in enumerate(regions):
        if len(r.dr_sf) != 16 or len(r.duty_limit) != 16:
            raise ValueError("une table régionale a 16 débits et 16 index de puissance")
        for k in range(16):
            c_regions[i].dr_sf[k] = r.dr_sf[k]
            c_regions[i].duty_limit[k] = r.duty_limit[k]
        c_regions[i].max_dr = r.max_dr
        c_regions[i].max_tx_power_index = r.max_tx_power_index
        c_regions[i].power_step_tenth_db = r.power_step_tenth_db
        c_regions[i].max_eirp_dbm = r.max_eirp_dbm

    c_opt = _CLoopOptions()
    c_opt.protocol = _CPlanOptions(1 if options.confirmed_uplinks else 0, options.downlink_every,
                                   options.downlink_payload_bytes, options.gateway_tx_power_dbm,
                                   options.device_antenna_gain_dbi, options.device_rx_offset_db)
    c_opt.adr = 1 if options.adr else 0
    c_opt.installation_margin_tenth_db = options.installation_margin_tenth_db
    c_opt.duty_cycle = 1 if options.duty_cycle else 0
    c_opt.duty_cycle_exponent = options.duty_cycle_exponent

    c_stats = (_CDeviceStats * max(1, n))()
    c_tot = _CSimStats()
    cap = max(1, capacity)
    c_ups = (_CLoopUplink * cap)()
    c_dls = (_CLoopDownlink * cap)()
    c_busy = (_CInterval * cap)()
    n_ups = ctypes.c_size_t(0)
    n_dls = ctypes.c_size_t(0)
    n_busy = ctypes.c_size_t(0)
    status = LIB.lsim_simulate_closed_loop_v2(
        c_devs if n else None, n, c_radios if n else None, c_regions if n else None,
        ctypes.byref(c_gw), ctypes.byref(c_prop), c_env_ref, ctypes.byref(c_opt),
        c_mac if mac else None, len(mac), c_stats if n else None, ctypes.byref(c_tot), c_ups, cap, ctypes.byref(n_ups),
        c_dls, cap, ctypes.byref(n_dls), c_busy, cap, ctypes.byref(n_busy))
    del keep
    if status != 0:
        raise StatusError(status)

    per = tuple(Counters(s.sent, s.received, s.lost_sensitivity, s.lost_collision, s.airtime_ns,
                         s.lost_gateway_busy) for s in c_stats[:n])
    tot = Counters(c_tot.sent, c_tot.received, c_tot.lost_sensitivity, c_tot.lost_collision,
                   c_tot.airtime_ns, c_tot.lost_gateway_busy)
    load = GatewayLoad(c_tot.gateway_busy_ns, c_tot.gateway_peak_concurrent,
                       c_tot.observation_ns, c_tot.gateway_utilization)
    ups = tuple(
        LoopUplink(u.device_index, u.start_ns, u.end_ns, u.spreading_factor,
                   None if u.dr < 0 else u.dr, u.power_index, u.rssi_dbm,
                   _OUTCOMES[u.outcome], u.answer_mask, u.answer_ok)
        for u in c_ups[:n_ups.value])
    dls = tuple(
        LoopDownlink(d.uplink_index, d.device_index, _KIND_NAMES[d.kind], d.commands, d.t_open_ns,
                     None if d.start_ns < 0 else d.start_ns, d.air_ns, bool(d.device_missed),
                     bool(d.delivered), d.req_dr, d.req_power_index)
        for d in c_dls[:n_dls.value])
    busy = tuple((c_busy[k].start_ns, c_busy[k].end_ns) for k in range(n_busy.value))
    return LoopOutcome(per, tot, load, ups, dls, busy)
