"""Planification native des descentes (S0) : pont vers `lsim_plan_downlinks_v1`.

Équivalent natif de `trace_events._downlink_jobs`, `_schedule_gateway` et `_events` pour une passerelle
unique, sans jointure ni commande MAC. La version Python reste l'oracle : `tests/test_downlink_plan_parity.py`
exige l'égalité des événements et de l'occupation passerelle.
"""

from __future__ import annotations

import ctypes
from typing import Sequence

from lsim._native import LIB
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
