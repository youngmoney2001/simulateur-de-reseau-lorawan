"""Planification native des descentes (S0) : pont vers `lsim_plan_downlinks_v1`.

Équivalent natif de `trace_events._downlink_jobs`, `_schedule_gateway` et `_events` pour une passerelle
unique, sans jointure ni commande MAC. La version Python reste l'oracle : `tests/test_downlink_plan_parity.py`
exige l'égalité des événements et de l'occupation passerelle.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
from typing import Optional, Sequence

from lsim.gateway_sensitivity import MODEL_ID, SensitivityError
from lsim._native import (
    LIB,
    _CDeviceRf,
    _CDeviceStats,
    _CEndDevice,
    _CEnvironment,
    _CGateway,
    _CGatewayRf,
    _CGatewayV2,
    _CInterval,
    _CPropagation,
    _CSimStats,
    _CTxRecord,
)
from lsim.rf import device_table, gateway_entry
from lsim.lora import StatusError
from lsim.simulator import (
    MAX_END_DEVICES,
    MAX_TRACE_RECORDS,
    Counters,
    GatewayLoad,
    TraceResult,
    TxRecord,
    _c_end_devices,
    _c_environment,
)
from lsim.trace_events import HopEvent, ProtocolEvent

PLAN_STATUS_BASE = 950
_KINDS = {0: "uplink", 1: "ack", 2: "downlink", 3: "rx_window_missed"}
_OUTCOMES = {
    0: "received", 1: "lost_sensitivity", 2: "lost_collision", 3: "lost_gateway_busy",
    4: "ack_only", 5: "data", 6: "data_ack", 7: "gateway_busy", 8: "device_transmitting",
    9: "delivered", 10: "not_listened",
}
_OUTCOME_CODES = {v: k for k, v in _OUTCOMES.items()}
_TX_TO_UPLINK = {0: 0, 1: 1, 2: 2, 3: 3}


class _CPlanUplink(ctypes.Structure):
    _fields_ = [("device_index", ctypes.c_uint32), ("start_ns", ctypes.c_int64),
                ("end_ns", ctypes.c_int64), ("spreading_factor", ctypes.c_uint8),
                ("outcome", ctypes.c_uint8), ("rssi_dbm", ctypes.c_double)]


class _CPlanDevice(ctypes.Structure):
    _fields_ = [("freq_hz", ctypes.c_int64), ("dr", ctypes.c_int32), ("rx1_hz", ctypes.c_int64),
                ("tx_power_dbm", ctypes.c_double), ("rx1_sf", ctypes.c_uint8),
                ("rx1_bw_hz", ctypes.c_uint32)]


class _CPlanOptions(ctypes.Structure):
    _fields_ = [("confirmed_uplinks", ctypes.c_uint8), ("downlink_every", ctypes.c_uint32),
                ("downlink_payload_bytes", ctypes.c_uint32), ("gateway_tx_power_dbm", ctypes.c_double),
                ("device_antenna_gain_dbi", ctypes.c_double), ("device_rx_offset_db", ctypes.c_double)]


class _CPlanHop(ctypes.Structure):
    _fields_ = [("dir", ctypes.c_uint8), ("outcome", ctypes.c_uint8), ("has_rssi", ctypes.c_uint8),
                ("t_ns", ctypes.c_int64), ("freq_hz", ctypes.c_int64), ("dr", ctypes.c_int32),
                ("rssi_dbm", ctypes.c_double)]


class _CPlanEvent(ctypes.Structure):
    _fields_ = [("t_ns", ctypes.c_int64), ("device_index", ctypes.c_uint32), ("kind", ctypes.c_uint8),
                ("outcome", ctypes.c_uint8), ("hop_count", ctypes.c_uint8),
                ("hops", _CPlanHop * 2)]


class _CInterval(ctypes.Structure):
    _fields_ = [("start_ns", ctypes.c_int64), ("end_ns", ctypes.c_int64)]


LIB.lsim_plan_downlinks_v1.restype = ctypes.c_int32
LIB.lsim_plan_downlinks_v1.argtypes = [
    ctypes.POINTER(_CPlanUplink), ctypes.c_size_t, ctypes.POINTER(_CPlanDevice), ctypes.c_size_t,
    ctypes.POINTER(_CPlanOptions), ctypes.POINTER(_CPlanEvent), ctypes.c_size_t,
    ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(_CInterval), ctypes.c_size_t,
    ctypes.POINTER(ctypes.c_size_t),
]


# --------------------------------------------------------------------------- jalon I0 : enveloppe v2
LSIM_PLAN_DOWNLINKS_V2_ABI_VERSION = 1


@dataclass(frozen=True)
class DeviceRx2:
    """Paramètres de la seconde fenêtre de réception (RX2), par dispositif.

    Jalon I0 : ces valeurs sont **transportées et validées** par le cœur, elles ne modifient ni le
    placement ni le temps d'antenne — aucun repli RX2 n'est produit. Le repli reste opt-in :
    `rx2_sf = 0` signifie « aucune descente RX2 ».

    `rx2_hz = 0` : non renseigné (aucune contrainte). `rx2_bw_hz = 0` : reprend `rx1_bw_hz`.
    """

    rx2_hz: int = 0
    rx2_sf: int = 0
    rx2_bw_hz: int = 0


class _CPlanDeviceRx2(ctypes.Structure):
    _fields_ = [("rx2_hz", ctypes.c_int64), ("rx2_sf", ctypes.c_uint32),
                ("rx2_bw_hz", ctypes.c_uint32), ("reserved", ctypes.c_uint64 * 2)]


class _CPlanDownlinksV2Args(ctypes.Structure):
    _fields_ = [("struct_size", ctypes.c_uint32), ("abi_version", ctypes.c_uint32),
                ("uplinks", ctypes.POINTER(_CPlanUplink)), ("uplink_count", ctypes.c_size_t),
                ("devices", ctypes.POINTER(_CPlanDevice)), ("device_count", ctypes.c_size_t),
                ("options", ctypes.POINTER(_CPlanOptions)),
                ("rx2", ctypes.POINTER(_CPlanDeviceRx2)),
                ("events", ctypes.POINTER(_CPlanEvent)), ("event_capacity", ctypes.c_size_t),
                ("event_count", ctypes.POINTER(ctypes.c_size_t)),
                ("busy", ctypes.POINTER(_CInterval)), ("busy_capacity", ctypes.c_size_t),
                ("busy_count", ctypes.POINTER(ctypes.c_size_t)),
                ("rx2_count", ctypes.c_size_t), ("reserved", ctypes.c_uint64 * 2)]


LIB.lsim_plan_downlinks_v2.restype = ctypes.c_int32
LIB.lsim_plan_downlinks_v2.argtypes = [ctypes.POINTER(_CPlanDownlinksV2Args)]


LIB.lsim_simulate_uplinks_causal_v1.restype = ctypes.c_int32
LIB.lsim_simulate_uplinks_causal_v1.argtypes = [
    ctypes.POINTER(_CEndDevice), ctypes.c_size_t, ctypes.POINTER(_CGateway),
    ctypes.POINTER(_CPropagation), ctypes.POINTER(_CEnvironment),
    ctypes.POINTER(_CDeviceStats), ctypes.POINTER(_CSimStats),
    ctypes.POINTER(_CTxRecord), ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t),
    ctypes.POINTER(_CPlanDevice), ctypes.POINTER(_CPlanOptions),
    ctypes.POINTER(_CInterval), ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t),
]
LIB.lsim_simulate_uplinks_causal_gw2.restype = ctypes.c_int32
LIB.lsim_simulate_uplinks_causal_gw2.argtypes = [
    ctypes.POINTER(_CEndDevice), ctypes.c_size_t, ctypes.POINTER(_CGatewayV2),
    ctypes.POINTER(_CPropagation), ctypes.POINTER(_CEnvironment),
    ctypes.POINTER(_CDeviceStats), ctypes.POINTER(_CSimStats),
    ctypes.POINTER(_CTxRecord), ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t),
    ctypes.POINTER(_CPlanDevice), ctypes.POINTER(_CPlanOptions),
    ctypes.POINTER(_CInterval), ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t),
]
# Variantes v2 : mêmes entrées, plus les tables de frontaux (device_count entrées, complètes).
for _nom in ("lsim_simulate_uplinks_causal_v2", "lsim_simulate_uplinks_causal_gw2_v2"):
    _fn = getattr(LIB, _nom)
    _fn.restype = ctypes.c_int32
    _fn.argtypes = [
        ctypes.POINTER(_CEndDevice), ctypes.c_size_t,
        ctypes.POINTER(_CGatewayV2) if _nom.endswith("gw2_v2") else ctypes.POINTER(_CGateway),
        ctypes.POINTER(_CPropagation), ctypes.POINTER(_CEnvironment),
        ctypes.POINTER(_CDeviceStats), ctypes.POINTER(_CSimStats),
        ctypes.POINTER(_CTxRecord), ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t),
        ctypes.POINTER(_CPlanDevice), ctypes.POINTER(_CPlanOptions),
        ctypes.POINTER(_CInterval), ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t),
        ctypes.POINTER(_CDeviceRf), ctypes.c_size_t, ctypes.POINTER(_CGatewayRf),
    ]


def simulate_causal(devices, gateway, propagation, environment, radios, options,
                    device_rf=None, gateway_rf=None):
    """Boucle fermée causale (S1) : trace et occupation passerelle, en une seule exécution.

    Chaque trame reçue planifie sa descente à sa fin (`lsim_simulate_uplinks_causal_v1`). Renvoie
    `(TraceResult, occupation)`. Lève `StatusError` si le cœur refuse l'entrée.
    `devices` et `radios` : même ordre (un `DeviceRadio` par dispositif). Pas de MAC ni de jointure.

    `device_rf` / `gateway_rf` (v4) : frontaux RF, comme `simulate_uplinks_trace`. Sans frontal,
    l'entrée v1 est appelée : le résultat est celui de la base, à l'octet près.
    """
    n = len(devices)
    if n > MAX_END_DEVICES:
        raise ValueError(f"au plus {MAX_END_DEVICES} dispositifs par simulation")
    if len(radios) != n:
        raise ValueError("un paramètre radio par dispositif")
    for r in radios:
        # Descente vers un débit hors 7..12 (SF5, DR13) : sensibilité du dispositif NV, refus explicite.
        if not 7 <= r.rx1_sf <= 12:
            raise SensitivityError(f"descente vers RX1 SF{r.rx1_sf} refusée : sensibilité du "
                                   "dispositif NV (SF5 : uplink seulement)")
    capacity = sum(d.messages for d in devices)
    if capacity > MAX_TRACE_RECORDS:
        raise ValueError(f"trace limitée à {MAX_TRACE_RECORDS} émissions par simulation")
    c_devs = _c_end_devices(devices)
    absolute = getattr(gateway, "absolute_sensitivity", None)
    c_gw = (absolute.to_c(gateway) if absolute is not None
            else _CGateway(gateway.x_m, gateway.y_m, gateway.antenna_gain_dbi))
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
    c_radios = (_CPlanDevice * max(1, n))()
    for i, d in enumerate(radios):
        c_radios[i].freq_hz = d.freq_hz
        c_radios[i].dr = -1 if d.dr is None else d.dr
        c_radios[i].rx1_hz = d.rx1_hz
        c_radios[i].tx_power_dbm = d.tx_power_dbm
        c_radios[i].rx1_sf = d.rx1_sf
        c_radios[i].rx1_bw_hz = d.rx1_bw_hz
    c_opt = _CPlanOptions(1 if options.confirmed_uplinks else 0, options.downlink_every,
                          options.downlink_payload_bytes, options.gateway_tx_power_dbm,
                          options.device_antenna_gain_dbi, options.device_rx_offset_db)
    records = (_CTxRecord * max(1, capacity))()
    # Occupation passerelle : au plus une période par trame reçue (une descente au plus).
    cap_busy = max(1, capacity)
    count = ctypes.c_size_t(0)
    n_busy = ctypes.c_size_t(0)
    busy = (_CInterval * cap_busy)()
    # Frontaux : seules les tables effectivement demandées font basculer sur les entrées v2.
    with_rf = device_rf is not None or gateway_rf is not None
    c_dev_rf, n_dev_rf = device_table(device_rf, _CDeviceRf)
    c_gw_rf = gateway_entry(gateway_rf)
    if with_rf:
        causal_fn = (LIB.lsim_simulate_uplinks_causal_gw2_v2 if absolute is not None
                     else LIB.lsim_simulate_uplinks_causal_v2)
    else:
        causal_fn = (LIB.lsim_simulate_uplinks_causal_gw2 if absolute is not None
                     else LIB.lsim_simulate_uplinks_causal_v1)
    args = [c_devs if n else None, n, ctypes.byref(c_gw), ctypes.byref(c_prop), c_env_ref,
            c_stats if n else None, ctypes.byref(c_tot), records, capacity, ctypes.byref(count),
            c_radios if n else None, ctypes.byref(c_opt), busy, cap_busy, ctypes.byref(n_busy)]
    if with_rf:
        args += [c_dev_rf if n_dev_rf else None, n_dev_rf, c_gw_rf]
    status = causal_fn(*args)
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
        for r in records[:count.value]
    )
    occupation = tuple((busy[k].start_ns, busy[k].end_ns) for k in range(n_busy.value))
    return TraceResult(per, tot, load, trace), occupation


def plan_native(records, radios, options) -> tuple[tuple[ProtocolEvent, ...], tuple[tuple[int, int], ...]]:
    """Événements et occupation passerelle, calculés en natif à partir de la trace et des radios.

    `records` : `TxRecord` de la trace ; `radios` : `DeviceRadio` ; `options` : `ProtocolOptions`.
    Lève ValueError pour une entrée refusée par le cœur.
    """
    return _plan_native(records, radios, options, None, False)


def plan_native_v2(records, radios, options,
                   rx2: Optional[Sequence["DeviceRx2"]] = None,
                   ) -> tuple[tuple[ProtocolEvent, ...], tuple[tuple[int, int], ...]]:
    """Même calcul que `plan_native`, par l'enveloppe ABI versionnée `lsim_plan_downlinks_v2`.

    `rx2` : une entrée `DeviceRx2` par dispositif, ou None pour le comportement v1. Jalon I0 :
    les paramètres RX2 sont transmis et validés, ils ne changent ni le placement ni le temps
    d'antenne — le résultat est donc identique à celui de `plan_native`.
    """
    return _plan_native(records, radios, options, rx2, True)


def _plan_native(records, radios, options, rx2, use_v2):
    ups = (_CPlanUplink * max(1, len(records)))()
    for i, r in enumerate(records):
        ups[i].device_index = r.device_index
        ups[i].start_ns = r.start_ns
        ups[i].end_ns = r.end_ns
        ups[i].spreading_factor = r.spreading_factor
        ups[i].outcome = _TX_TO_UPLINK[r.outcome]
        ups[i].rssi_dbm = r.rssi_dbm
    devs = (_CPlanDevice * max(1, len(radios)))()
    for i, d in enumerate(radios):
        devs[i].freq_hz = d.freq_hz
        devs[i].dr = -1 if d.dr is None else d.dr
        devs[i].rx1_hz = d.rx1_hz
        devs[i].tx_power_dbm = d.tx_power_dbm
        devs[i].rx1_sf = d.rx1_sf
        devs[i].rx1_bw_hz = d.rx1_bw_hz
    opt = _CPlanOptions(1 if options.confirmed_uplinks else 0, options.downlink_every,
                        options.downlink_payload_bytes, options.gateway_tx_power_dbm,
                        options.device_antenna_gain_dbi, options.device_rx_offset_db)
    # Jalon I0 : table RX2 seulement si elle est fournie (None ⇒ comportement v1 à l'identique).
    c_rx2 = None
    if rx2 is not None:
        c_rx2 = (_CPlanDeviceRx2 * max(1, len(rx2)))()
        for i, r in enumerate(rx2):
            c_rx2[i].rx2_hz = r.rx2_hz
            c_rx2[i].rx2_sf = r.rx2_sf
            c_rx2[i].rx2_bw_hz = r.rx2_bw_hz
    cap_ev = max(4, 2 * len(records) + 2 * len(records))
    cap_busy = max(4, len(records) + 1)
    for _ in range(2):
        evs = (_CPlanEvent * cap_ev)()
        busy = (_CInterval * cap_busy)()
        n_ev = ctypes.c_size_t(0)
        n_busy = ctypes.c_size_t(0)
        if use_v2:
            # Champs pointeurs : des pointeurs réels, pas des `byref` (CArgObject non assignable).
            args = _CPlanDownlinksV2Args()
            args.struct_size = ctypes.sizeof(_CPlanDownlinksV2Args)
            args.abi_version = LSIM_PLAN_DOWNLINKS_V2_ABI_VERSION
            args.uplinks = ctypes.cast(ups, ctypes.POINTER(_CPlanUplink))
            args.uplink_count = len(records)
            args.devices = ctypes.cast(devs, ctypes.POINTER(_CPlanDevice))
            args.device_count = len(radios)
            args.options = ctypes.pointer(opt)
            # Sans rx2_count, le cœur lirait device_count entrées quelle que soit la taille réelle.
            args.rx2 = (ctypes.cast(c_rx2, ctypes.POINTER(_CPlanDeviceRx2))
                        if c_rx2 is not None else None)
            args.rx2_count = 0 if c_rx2 is None else len(rx2)
            args.events = ctypes.cast(evs, ctypes.POINTER(_CPlanEvent))
            args.event_capacity = cap_ev
            args.event_count = ctypes.pointer(n_ev)
            args.busy = ctypes.cast(busy, ctypes.POINTER(_CInterval))
            args.busy_capacity = cap_busy
            args.busy_count = ctypes.pointer(n_busy)
            status = LIB.lsim_plan_downlinks_v2(ctypes.byref(args))
        else:
            status = LIB.lsim_plan_downlinks_v1(ups, len(records), devs, len(radios),
                                                ctypes.byref(opt), evs, cap_ev,
                                                ctypes.byref(n_ev), busy, cap_busy,
                                                ctypes.byref(n_busy))
        if status == PLAN_STATUS_BASE + 4:  # capacité insuffisante : taille requise connue, on relance
            cap_ev, cap_busy = n_ev.value, n_busy.value
            continue
        if status != 0:
            raise ValueError(f"planification des descentes refusée (statut {status})")
        break
    else:  # pragma: no cover
        raise RuntimeError("capacité de planification non stabilisée")
    events = []
    for k in range(n_ev.value):
        e = evs[k]
        hops = []
        for h in range(e.hop_count):
            c = e.hops[h]
            if c.dir == 0:
                src, dst = f"dev:{e.device_index}", "gw:0"
            elif c.dir == 1:
                src, dst = "gw:0", "ns"
            else:
                src, dst = "gw:0", f"dev:{e.device_index}"
            hops.append(HopEvent(src, dst, c.t_ns, c.freq_hz, None if c.dr < 0 else c.dr,
                                 c.rssi_dbm if c.has_rssi else None, _OUTCOMES[c.outcome]))
        events.append(ProtocolEvent(seq=k, t_ns=e.t_ns, kind=_KINDS[e.kind],
                                    device_index=e.device_index, gateway_index=0,
                                    hops=tuple(hops), outcome=_OUTCOMES[e.outcome]))
    intervals = tuple((busy[k].start_ns, busy[k].end_ns) for k in range(n_busy.value))
    return tuple(events), intervals
