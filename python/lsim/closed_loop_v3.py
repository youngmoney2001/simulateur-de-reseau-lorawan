"""Pont ctypes vers `lsim_simulate_closed_loop_v3` (boucle fermée, ABI v3, étape 6.3).

La fonction native est exportée par `liblsim_core` et définie dans `core/src/c_api_closed_loop_v3.cpp`.
Ce module ne modifie aucun chemin existant : v1, v2 et gw2 restent dans `closed_loop.py`.

Deux modes, choisis par la présence de `channels` :
- historique (`channels=None`) : configuration canal absente, défauts du moteur, équivalent à v2 ;
- explicite (`channels=[ChannelConfigV3, ...]`) : plan EU868 RP002-1.0.5, un élément par dispositif.
  Un dispositif absent de la liste reçoit `present = 0` (valeurs par défaut du moteur).

Les erreurs natives lèvent `lsim.lora.StatusError` avec le code de statut (base 1000 pour les codes
de configuration canal). Les capacités de sortie sont dimensionnées par défaut sur le nombre total
d'émissions ; `trace_capacity` peut être ajusté, et une capacité insuffisante lève une erreur.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass, field
from typing import Mapping, Optional, Sequence

from lsim._native import (
    LIB,
    _CDeviceStats,
    _CEndDevice,
    _CGateway,
    _CGatewayV2,
    _CInterval,
    _CPropagation,
    _CSimStats,
)
from lsim.closed_loop import (
    _CLoopDownlink,
    _CLoopMac,
    _CLoopOptions,
    _CLoopRegion,
    _CLoopUplink,
    _CMacCounters,
    _KIND_NAMES,
    _OUTCOMES,
    LoopDownlink,
    LoopOptions,
    LoopRegion,
    LoopUplink,
    MacQueueCounters,
    MacSlot,
)
from lsim.downlink_plan import _CPlanDevice, _CPlanOptions
from lsim.lora import StatusError
from lsim.simulator import MAX_END_DEVICES, Counters, GatewayLoad, _c_end_devices

# Constantes publiques (c_api.h, bloc v3).
CHANNEL_PLAN_NONE = 0
CHANNEL_PLAN_EU868_RP002_1_0_5 = 1
ABI_VERSION_V3 = 3
CHANNEL_MAX = 80          # emplacements de canaux (A1 : 80 ; 16 à 79 refusés)
CHANNEL_SUPPORTED = 16    # canaux acceptés par le modèle EU868
NO_INDEX = 0xFFFFFFFF
STATUS_NONE = 0xFF

_TRACE_KINDS = {0: "uplink", 1: "link_adr_ans", 2: "exclusion", 3: "adr_decision",
                4: "link_adr_req", 5: "downlink", 6: "apply"}
_TRACE_ORIGINS = {0: "normative", 1: "simulator_policy", 2: "radio"}
_TRACE_ACTIONS = {0: "created", 1: "renewed", 2: "expired"}
_TRACE_TARGETS = {0: "data_rate", 1: "power", 2: "channel", 3: "mask"}
_TRACE_LOSSES = {0: "none", 1: "device_transmitting", 2: "no_gateway_slot", 3: "below_sensitivity"}


class _CChannelDeviceV3(ctypes.Structure):
    """`lsim_channel_device_v3` (128 octets)."""

    _fields_ = [
        ("struct_size", ctypes.c_uint32),
        ("abi_version", ctypes.c_uint32),
        ("device_index", ctypes.c_uint32),
        ("present", ctypes.c_uint32),
        ("dr_mask", ctypes.c_uint8 * CHANNEL_MAX),
        ("enabled", ctypes.c_uint8 * 10),
        ("server_defined", ctypes.c_uint8 * 10),
        ("reserved", ctypes.c_uint8 * 12),
    ]


class _CChannelTerminalV3(ctypes.Structure):
    """`lsim_channel_terminal_v3` (112 octets)."""

    _fields_ = [
        ("struct_size", ctypes.c_uint32),
        ("abi_version", ctypes.c_uint32),
        ("device_index", ctypes.c_uint32),
        ("dr", ctypes.c_uint8),
        ("power_index", ctypes.c_uint8),
        ("reserved0", ctypes.c_uint16),
        ("dr_mask", ctypes.c_uint8 * CHANNEL_MAX),
        ("enabled", ctypes.c_uint8 * 10),
        ("reserved1", ctypes.c_uint8 * 6),
    ]


class _CLoopTraceV3(ctypes.Structure):
    """`lsim_loop_trace_v3` (40 octets)."""

    _fields_ = [
        ("t_ns", ctypes.c_int64),
        ("device", ctypes.c_uint32),
        ("uplink", ctypes.c_uint32),
        ("downlink", ctypes.c_uint32),
        ("kind", ctypes.c_uint8),
        ("origin", ctypes.c_uint8),
        ("action", ctypes.c_uint8),
        ("target", ctypes.c_uint8),
        ("loss", ctypes.c_uint8),
        ("status", ctypes.c_uint8),
        ("dr", ctypes.c_uint8),
        ("power_index", ctypes.c_uint8),
        ("channel_mask", ctypes.c_uint16),
        ("value", ctypes.c_uint16),
        ("flag", ctypes.c_uint8),
        ("reason_channel", ctypes.c_uint8),
        ("reason_dr", ctypes.c_uint8),
        ("reason_power", ctypes.c_uint8),
        ("reserved", ctypes.c_uint32),
    ]


class _CClosedLoopV3Args(ctypes.Structure):
    """`lsim_closed_loop_v3_args` (272 octets, `terminal_count` au décalage 264)."""

    _fields_ = [
        ("struct_size", ctypes.c_uint32),
        ("abi_version", ctypes.c_uint32),
        ("channel_plan", ctypes.c_uint32),
        ("trace_enabled", ctypes.c_uint32),
        ("trace_element_size", ctypes.c_uint32),
        ("terminal_element_size", ctypes.c_uint32),
        ("reserved0", ctypes.c_uint32),
        ("reserved1", ctypes.c_uint32),
        ("devices", ctypes.POINTER(_CEndDevice)),
        ("device_count", ctypes.c_size_t),
        ("radios", ctypes.POINTER(_CPlanDevice)),
        ("regions", ctypes.POINTER(_CLoopRegion)),
        ("gateway", ctypes.POINTER(_CGatewayV2)),
        ("prop", ctypes.POINTER(_CPropagation)),
        ("env", ctypes.c_void_p),
        ("options", ctypes.POINTER(_CLoopOptions)),
        ("mac", ctypes.POINTER(_CLoopMac)),
        ("mac_count", ctypes.c_size_t),
        ("channels", ctypes.POINTER(_CChannelDeviceV3)),
        ("channel_count", ctypes.c_size_t),
        ("per_device", ctypes.POINTER(_CDeviceStats)),
        ("totals", ctypes.POINTER(_CSimStats)),
        ("uplinks", ctypes.POINTER(_CLoopUplink)),
        ("uplink_capacity", ctypes.c_size_t),
        ("uplink_count", ctypes.POINTER(ctypes.c_size_t)),
        ("downlinks", ctypes.POINTER(_CLoopDownlink)),
        ("downlink_capacity", ctypes.c_size_t),
        ("downlink_count", ctypes.POINTER(ctypes.c_size_t)),
        ("busy", ctypes.POINTER(_CInterval)),
        ("busy_capacity", ctypes.c_size_t),
        ("busy_count", ctypes.POINTER(ctypes.c_size_t)),
        ("mac_counters", ctypes.POINTER(_CMacCounters)),
        ("trace", ctypes.POINTER(_CLoopTraceV3)),
        ("trace_capacity", ctypes.c_size_t),
        ("trace_count", ctypes.POINTER(ctypes.c_size_t)),
        ("terminals", ctypes.POINTER(_CChannelTerminalV3)),
        ("terminal_capacity", ctypes.c_size_t),
        ("terminal_count", ctypes.POINTER(ctypes.c_size_t)),
    ]


LIB.lsim_simulate_closed_loop_v3.restype = ctypes.c_int32
LIB.lsim_simulate_closed_loop_v3.argtypes = [ctypes.POINTER(_CClosedLoopV3Args)]


@dataclass(frozen=True)
class ChannelConfigV3:
    """Configuration canal d'un dispositif (mode explicite).

    `dr_masks` : canal -> masque des débits DR0..DR7 (bit k = DRk) ; un canal absent est non défini.
    `enabled` : canaux actifs (sous-ensemble des canaux définis).
    `server_defined` : vue serveur (canaux que le serveur croit définis).
    """

    device: int
    dr_masks: Mapping[int, int]
    enabled: Sequence[int]
    server_defined: Sequence[int]


@dataclass(frozen=True)
class TerminalChannelState:
    """État canal final d'un terminal (sortie native, pas la vue serveur)."""

    device: int
    dr: int
    power_index: int
    dr_masks: Mapping[int, int]  # canaux définis côté terminal, masque non nul
    enabled: tuple[int, ...]     # canaux actifs côté terminal


@dataclass(frozen=True)
class TraceEventV3:
    """Événement de trace v3 (sentinelles converties en None)."""

    t_ns: int
    device: int
    uplink: int
    downlink: Optional[int]      # LinkAdrReq, Downlink, Apply
    kind: str
    origin: str
    action: str
    target: str
    loss: str                    # non « none » seulement pour Downlink
    status: Optional[int]        # LinkAdrAns et Apply
    dr: int
    power_index: int
    channel_mask: int
    value: int
    flag: bool
    reason_channel: int
    reason_dr: int
    reason_power: int


@dataclass(frozen=True)
class ClosedLoopV3Outcome:
    per_device: tuple[Counters, ...]
    totals: Counters
    load: GatewayLoad
    uplinks: tuple[LoopUplink, ...]
    downlinks: tuple[LoopDownlink, ...]
    busy: tuple[tuple[int, int], ...]
    mac_queue: MacQueueCounters
    terminals: tuple[TerminalChannelState, ...]
    trace: tuple[TraceEventV3, ...] = field(default_factory=tuple)


def _ptr(array, ctype):
    """Pointeur sur un tableau ctypes (None si absent) : affectation explicite aux champs POINTER."""
    return None if array is None else ctypes.cast(array, ctypes.POINTER(ctype))


def _element(config: ChannelConfigV3) -> _CChannelDeviceV3:
    e = _CChannelDeviceV3()
    e.struct_size = ctypes.sizeof(_CChannelDeviceV3)
    e.abi_version = ABI_VERSION_V3
    e.device_index = config.device
    e.present = 1
    for ch, mask in config.dr_masks.items():
        if not 0 <= ch < CHANNEL_MAX:
            raise ValueError(f"canal {ch} hors de 0..{CHANNEL_MAX - 1}")
        e.dr_mask[ch] = mask
    for ch in config.enabled:
        if not 0 <= ch < CHANNEL_MAX:
            raise ValueError(f"canal actif {ch} hors de 0..{CHANNEL_MAX - 1}")
        e.enabled[ch // 8] |= 1 << (ch % 8)
    for ch in config.server_defined:
        if not 0 <= ch < CHANNEL_MAX:
            raise ValueError(f"canal de vue serveur {ch} hors de 0..{CHANNEL_MAX - 1}")
        e.server_defined[ch // 8] |= 1 << (ch % 8)
    return e


def _absent(index: int) -> _CChannelDeviceV3:
    e = _CChannelDeviceV3()
    e.struct_size = ctypes.sizeof(_CChannelDeviceV3)
    e.abi_version = ABI_VERSION_V3
    e.device_index = index
    e.present = 0
    return e


def _terminal(t: _CChannelTerminalV3) -> TerminalChannelState:
    masks = {ch: int(t.dr_mask[ch]) for ch in range(CHANNEL_MAX) if t.dr_mask[ch] != 0}
    enabled = tuple(ch for ch in range(CHANNEL_MAX) if (t.enabled[ch // 8] >> (ch % 8)) & 1)
    return TerminalChannelState(int(t.device_index), int(t.dr), int(t.power_index), masks, enabled)


def _trace(e: _CLoopTraceV3) -> TraceEventV3:
    return TraceEventV3(
        t_ns=int(e.t_ns),
        device=int(e.device),
        uplink=int(e.uplink),
        downlink=None if e.downlink == NO_INDEX else int(e.downlink),
        kind=_TRACE_KINDS[e.kind],
        origin=_TRACE_ORIGINS[e.origin],
        action=_TRACE_ACTIONS.get(e.action, "none"),
        target=_TRACE_TARGETS.get(e.target, "none"),
        loss=_TRACE_LOSSES[e.loss],
        status=None if e.status == STATUS_NONE else int(e.status),
        dr=int(e.dr),
        power_index=int(e.power_index),
        channel_mask=int(e.channel_mask),
        value=int(e.value),
        flag=bool(e.flag),
        reason_channel=int(e.reason_channel),
        reason_dr=int(e.reason_dr),
        reason_power=int(e.reason_power),
    )


def simulate_closed_loop_v3(
    devices: Sequence,
    gateway,
    propagation,
    radios: Sequence,
    regions: Sequence[LoopRegion],
    options: LoopOptions,
    *,
    mac: Sequence[MacSlot] = (),
    channels: Optional[Sequence[ChannelConfigV3]] = None,
    trace: bool = False,
    capacity: Optional[int] = None,
    trace_capacity: Optional[int] = None,
) -> ClosedLoopV3Outcome:
    """Boucle fermée v3 en une seule exécution native.

    `devices`, `radios`, `regions` : un élément par dispositif, même ordre. `channels=None` active le
    mode historique ; une liste active le plan EU868 explicite. `trace=True` produit la trace v3.
    `capacity` : uplinks, descentes et occupations (défaut : deux fois le nombre d'émissions) ;
    `trace_capacity` (défaut : 64 événements par émission et 1024). Une capacité insuffisante lève
    `StatusError` avec le code natif.
    """
    n = len(devices)
    if n > MAX_END_DEVICES:
        raise ValueError(f"au plus {MAX_END_DEVICES} dispositifs par simulation")
    if len(radios) != n or len(regions) != n:
        raise ValueError("devices, radios et regions ont des longueurs différentes")
    planned = sum(int(d.messages) for d in devices)
    cap = capacity if capacity is not None else max(1, 2 * planned + 1)
    tcap = trace_capacity if trace_capacity is not None else 64 * planned + 1024

    c_devs = _c_end_devices(devices) if n else None
    absolute = getattr(gateway, "absolute_sensitivity", None)
    if absolute is not None:
        c_gw = absolute.to_c(gateway)
    else:
        c_gw = _CGatewayV2()
        c_gw.base = _CGateway(gateway.x_m, gateway.y_m, gateway.antenna_gain_dbi,
                              getattr(gateway, "rx_sensitivity_offset_db", 0.0))
        c_gw.sensitivity_model = 0
    c_prop = _CPropagation(propagation.frequency_hz, propagation.reference_distance_m,
                           propagation.exponent, propagation.capture_threshold_db,
                           propagation.shadowing_sigma_db, propagation.shadowing_seed)

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

    c_mac = (_CLoopMac * max(1, len(mac)))()
    for k, m in enumerate(mac):
        c_mac[k].device_index = m.device
        c_mac[k].rank = m.rank
        c_mac[k].extra_bytes = m.extra_bytes
        c_mac[k].flags = m.flags

    # Configuration canal : absente (historique) ou un élément par dispositif.
    if channels is None:
        plan = CHANNEL_PLAN_NONE
        c_channels = None
        n_channels = 0
        keep_channels = None
    else:
        plan = CHANNEL_PLAN_EU868_RP002_1_0_5
        by_device = {c.device: c for c in channels}
        keep_channels = (_CChannelDeviceV3 * max(1, n))()
        for i in range(n):
            keep_channels[i] = _element(by_device[i]) if i in by_device else _absent(i)
        c_channels = keep_channels
        n_channels = n

    c_stats = (_CDeviceStats * max(1, n))()
    c_tot = _CSimStats()
    c_ups = (_CLoopUplink * max(1, cap))()
    c_dls = (_CLoopDownlink * max(1, cap))()
    c_busy = (_CInterval * max(1, cap))()
    c_trace = (_CLoopTraceV3 * max(1, tcap if trace else 1))()
    c_terms = (_CChannelTerminalV3 * max(1, n))()
    n_ups = ctypes.c_size_t(0)
    n_dls = ctypes.c_size_t(0)
    n_busy = ctypes.c_size_t(0)
    n_trace = ctypes.c_size_t(0)
    n_terms = ctypes.c_size_t(0)
    c_mq = _CMacCounters()

    args = _CClosedLoopV3Args()
    args.struct_size = ctypes.sizeof(_CClosedLoopV3Args)
    args.abi_version = ABI_VERSION_V3
    args.channel_plan = plan
    args.trace_enabled = 1 if trace else 0
    args.trace_element_size = ctypes.sizeof(_CLoopTraceV3)
    args.terminal_element_size = ctypes.sizeof(_CChannelTerminalV3)
    args.devices = _ptr(c_devs, _CEndDevice)
    args.device_count = n
    args.radios = _ptr(c_radios if n else None, _CPlanDevice)
    args.regions = _ptr(c_regions if n else None, _CLoopRegion)
    args.gateway = ctypes.pointer(c_gw)
    args.prop = ctypes.pointer(c_prop)
    args.env = None
    args.options = ctypes.pointer(c_opt)
    args.mac = _ptr(c_mac if mac else None, _CLoopMac)
    args.mac_count = len(mac)
    args.channels = _ptr(c_channels, _CChannelDeviceV3)
    args.channel_count = n_channels
    args.per_device = _ptr(c_stats if n else None, _CDeviceStats)
    args.totals = ctypes.pointer(c_tot)
    args.uplinks = _ptr(c_ups, _CLoopUplink)
    args.uplink_capacity = cap
    args.uplink_count = ctypes.pointer(n_ups)
    args.downlinks = _ptr(c_dls, _CLoopDownlink)
    args.downlink_capacity = cap
    args.downlink_count = ctypes.pointer(n_dls)
    args.busy = _ptr(c_busy, _CInterval)
    args.busy_capacity = cap
    args.busy_count = ctypes.pointer(n_busy)
    args.mac_counters = ctypes.pointer(c_mq)
    args.trace = _ptr(c_trace if trace else None, _CLoopTraceV3)
    args.trace_capacity = tcap if trace else 0
    args.trace_count = ctypes.pointer(n_trace)
    args.terminals = _ptr(c_terms, _CChannelTerminalV3)
    args.terminal_capacity = n
    args.terminal_count = ctypes.pointer(n_terms)

    status = LIB.lsim_simulate_closed_loop_v3(ctypes.pointer(args))
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
    mq = MacQueueCounters(c_mq.enqueued, c_mq.dispatched, c_mq.delivered, c_mq.dispatch_lost,
                          c_mq.deferred, c_mq.expired, c_mq.pending_at_end)
    terms = tuple(_terminal(c_terms[k]) for k in range(n_terms.value))
    events = tuple(_trace(c_trace[k]) for k in range(n_trace.value)) if trace else ()
    return ClosedLoopV3Outcome(per, tot, load, ups, dls, busy, mq, terms, events)
