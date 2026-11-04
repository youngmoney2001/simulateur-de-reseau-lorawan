#!/usr/bin/env python3
"""Preuve D3.15 — D-I3-1 : la fréquence rapportée d'un Join-Accept émis en RX2 est celle de RX1.

Chemin exercé : `build_trace` (chemin retransmissions), avec repli RX2 du Join-Accept actif.
La vérité terrain est lue dans le moteur (`simulate_confirmed_uplinks(..., with_engine_output=True)`),
qui expose pour chaque acceptation émise sa fenêtre réelle ; la trace, elle, rapporte une fréquence.

Constat : un Join-Accept réellement émis en RX2 (fenêtre « rx2 » côté moteur) est rapporté à la
fréquence RX1 (868,1 MHz au lieu de 869,525 MHz). Cause lue dans `lsim/trace_events.py` : le
`HopEvent` y code `radio.rx1_hz` sans distinguer la fenêtre.

Usage (depuis la racine du dépôt) :
    LSIM_LIBRARY=build_i1/liblsim_core.so PYTHONPATH=python python3 scripts/preuves/p_d_i3_1_frequence_join_accept.py

Épinglé sous `xfail(strict=True)` dans
`python/tests/test_d315_global.py::test_d_i3_1_le_join_accept_rx2_est_rapporte_sa_frequence`.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "python"))

from lsim.scenario import Scenario, ScenarioModel
from lsim.trace_events import build_trace, ProtocolOptions, device_radios
from lsim.retransmissions import simulate_confirmed_uplinks

sc = Scenario(ScenarioModel.model_validate({
  "schema_version": 1, "name": "d315-e2e", "seed": 11,
  "gateway": {"x_m": 0, "y_m": 0, "antenna_gain_dbi": 2.15},
  "propagation": {"frequency_hz": 868100000, "exponent": 2.7},
  "retransmissions": {"enabled": True, "retries": 1, "retransmit_delay_ms": 3000,
                      "enforce_duty_cycle": False,
                      "join_requests_s": [0], "join_retries": 1,
                      "join_accept_rx2_fallback": True},
  "groups": [
    {"name": f"sf{sf}", "count": 1, "region": "EU868",
     "placement": {"type": "disk", "radius_m": r},
     "spreading_factor": sf, "payload_bytes": 20, "tx_power_dbm": 14.0,
     "period_s": 30, "messages": 4, "start_spread_s": 10}
    for sf, r in ((7, 500), (9, 1000), (11, 1500), (12, 1900))
  ],
}))
devices, _g, _i = sc.deploy()
radios = device_radios(sc)
opts = ProtocolOptions(confirmed_uplinks=True, downlink_every=1, downlink_payload_bytes=40,
                       gateway_tx_power_dbm=27.0, rx2_fallback=True)
res = simulate_confirmed_uplinks(devices, sc.gateway(), sc.propagation(), radios, opts,
                                 sc.model.retransmissions.options(), with_engine_output=True)
verite = {}
for t in getattr(res, "joins", ()):
    for e in t.accepts:
        if e.outcome == "delivered":
            verite[(t.device, e.at_ns)] = e.window

run = build_trace(sc, opts)
print("RX2 réel =", radios[0].rx2_hz, "| RX1 =", radios[0].rx1_hz)
print("\nJoin-Accept dans la trace :")
for e in run.events:
    if e.kind == "join_accept":
        for h in e.hops:
            fen = verite.get((e.device_index, e.t_ns), "?")
            print(f"  dev={e.device_index} t={e.t_ns/1e6:9.3f} ms freq={h.freq_hz} "
                  f"issue={h.outcome}  fenêtre réelle={fen}")
