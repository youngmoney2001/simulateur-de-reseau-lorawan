"""Planification native des descentes (S0) : pont vers `lsim_plan_downlinks_v1`.

Équivalent natif de `trace_events._downlink_jobs`, `_schedule_gateway` et `_events` pour une passerelle
unique, sans jointure ni commande MAC. La version Python reste l'oracle : `tests/test_downlink_plan_parity.py`
exige l'égalité des événements et de l'occupation passerelle.
"""

from __future__ import annotations

import ctypes
from typing import Sequence

from lsim.gateway_sensitivity import MODEL_ID, SensitivityError
from lsim._native import (
    LIB,
    _CDeviceStats,
    _CEndDevice,
    _CEnvironment,
    _CGateway,
    _CGatewayV2,
    _CInterval,
    _CPropagation,
    _CSimStats,
    _CTxRecord,
)
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


def simulate_causal(devices, gateway, propagation, environment, radios, options):
    """Boucle fermée causale (S1) : trace et occupation passerelle, en une seule exécution.

    Chaque trame reçue planifie sa descente à sa fin (`lsim_simulate_uplinks_causal_v1`). Renvoie
    `(TraceResult, occupation)`. Lève `StatusError` si le cœur refuse l'entrée.
    `devices` et `radios` : même ordre (un `DeviceRadio` par dispositif). Pas de MAC ni de jointure.
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
    causal_fn = (LIB.lsim_simulate_uplinks_causal_gw2 if absolute is not None
                 else LIB.lsim_simulate_uplinks_causal_v1)
    status = causal_fn(
        c_devs if n else None, n, ctypes.byref(c_gw), ctypes.byref(c_prop), c_env_ref,
        c_stats if n else None, ctypes.byref(c_tot), records, capacity, ctypes.byref(count),
        c_radios if n else None, ctypes.byref(c_opt), busy, cap_busy, ctypes.byref(n_busy))
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
    cap_ev = max(4, 2 * len(records) + 2 * len(records))
    cap_busy = max(4, len(records) + 1)
    for _ in range(2):
        evs = (_CPlanEvent * cap_ev)()
        busy = (_CInterval * cap_busy)()
        n_ev = ctypes.c_size_t(0)
        n_busy = ctypes.c_size_t(0)
        status = LIB.lsim_plan_downlinks_v1(ups, len(records), devs, len(radios), ctypes.byref(opt),
                                            evs, cap_ev, ctypes.byref(n_ev), busy, cap_busy,
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
