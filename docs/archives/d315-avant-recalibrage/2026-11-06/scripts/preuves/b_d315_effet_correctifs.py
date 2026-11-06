#!/usr/bin/env python3
"""Preuve D3.15 — effet mesuré des correctifs D-I3-1 et D-I3-2 sur les résultats.

Compare, sur la même chronologie, le comportement **corrigé** et le comportement **antérieur**,
obtenu en neutralisant le correctif sans toucher au code :

  - D-I3-2 (sensibilité) : `_decodable` est appelé avec `en_rx2=False` quoi qu'il arrive, ce qui
    reproduit exactement l'ancien comportement (seuil RX1 appliqué à toutes les fenêtres).
  - D-I3-1 (fréquence)  : on compte les Join-Accept dont la fréquence rapportée change.

Résultat principal, et il est contre-intuitif : **sous le budget de liaison par défaut le défaut
D-I3-2 ne change AUCUN résultat.** La raison est arithmétique — l'asymétrie passerelle/terminal
(P_gw 27 dBm contre P_dev 14 dBm, soit +13 dB au descendant) dépasse l'écart de sensibilité entre
RX1 et RX2 dans tous les profils livrés. Le défaut devient observable dès que cette asymétrie se
réduit : le tableau ci-dessous situe le basculement vers 14 dBm de puissance passerelle.

Usage (depuis la racine du dépôt) :
    LSIM_LIBRARY=build_i1/liblsim_core.so PYTHONPATH=python \
        python3 scripts/preuves/b_d315_effet_correctifs.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "python"))

import lsim.ack_mac as am
from lsim.ack_mac import AckTiming, plan_acks
from lsim.plan import get_plan
from lsim.radio import receiver_sensitivity_dbm
from lsim.scenario import Scenario, ScenarioModel
from lsim.simulator import simulate_uplinks_trace
from lsim.trace_events import ProtocolOptions, device_radios

RAYON = 40_000   # m : place une partie des terminaux dans la bande marginale


def scene(region="EU868", sf=10, count=60, period=5, messages=20, spread=60, rayon=RAYON):
    hz = get_plan(region).uplink_channels_hz()[0]
    return Scenario(ScenarioModel.model_validate({
        "schema_version": 1, "name": "effet", "seed": 11,
        "gateway": {"x_m": 0, "y_m": 0, "antenna_gain_dbi": 2.15},
        "propagation": {"frequency_hz": hz, "exponent": 2.7},
        "groups": [{"name": "g0", "count": count, "region": region, "channel_freq_hz": hz,
                    "placement": {"type": "disk", "radius_m": rayon},
                    "spreading_factor": sf, "payload_bytes": 20, "tx_power_dbm": 14.0,
                    "period_s": period, "messages": messages, "start_spread_s": spread}]}))


def _records_et_radios(sc):
    radios = device_radios(sc)
    devices, _, _ = sc.deploy()
    res = simulate_uplinks_trace(devices, sc.gateway(), sc.propagation(), sc.environment,
                                 gateway_busy=())
    # `plan_acks` attend une radio **par enregistrement**, pas par terminal.
    return res.records, [radios[r.device_index] for r in res.records]


def acks_recus(records, par_enregistrement, pgw, forcer_ancien):
    """Nombre d'ACK reçus, avec ou sans le correctif D-I3-2."""
    original = am._decodable
    if forcer_ancien:
        def _ancien(rssi, radio, options, en_rx2=False):
            return original(rssi, radio, options, en_rx2=False)
        am._decodable = _ancien
    try:
        options = ProtocolOptions(confirmed_uplinks=True, downlink_every=1,
                                  downlink_payload_bytes=60, gateway_tx_power_dbm=pgw)
        plan = plan_acks(records, par_enregistrement, options, AckTiming(delay_ms=1500))
        return sum(1 for o in plan.outcomes if o.received)
    finally:
        am._decodable = original


def balayage_puissance():
    print("D-I3-2 — effet sur les ACK reçus, selon la puissance d'émission de la passerelle")
    print("EU868 SF7 montant : RX1 SF7BW125 (-123 dBm) contre RX2 SF12BW125 (-136 dBm)")
    print(f"seuil RX1 = {receiver_sensitivity_dbm(7, 125_000):.0f} dBm | "
          f"seuil RX2 = {receiver_sensitivity_dbm(12, 125_000):.0f} dBm")
    print(f"\n{'P_gw (dBm)':>11s} {'reçus avant':>12s} {'reçus après':>12s} {'écart':>7s}")
    records, par = _records_et_radios(scene(region="EU868", sf=7))
    for pgw in (27.0, 20.0, 14.0, 13.0, 10.0, 7.0, 0.0):
        avant = acks_recus(records, par, pgw, True)
        apres = acks_recus(records, par, pgw, False)
        print(f"{pgw:11.1f} {avant:12d} {apres:12d} {apres - avant:+7d}")
    print("\nLecture : à 27 dBm (défaut) l'asymétrie passerelle/terminal couvre déjà l'écart")
    print("RX1/RX2, donc le défaut était LATENT. Il double les ACK reçus à 7 dBm.")


def effet_d_i3_1():
    """D-I3-1 : combien de Join-Accept changent de fréquence rapportée."""
    from lsim.join import RX2
    from lsim.retransmissions import simulate_confirmed_uplinks
    from lsim.trace_events import build_trace

    sc = Scenario(ScenarioModel.model_validate({
        "schema_version": 1, "name": "d315-join", "seed": 11,
        "gateway": {"x_m": 0, "y_m": 0, "antenna_gain_dbi": 2.15},
        "propagation": {"frequency_hz": get_plan("EU868").uplink_channels_hz()[0],
                        "exponent": 2.7},
        "retransmissions": {"enabled": True, "retries": 1, "retransmit_delay_ms": 3000,
                            "enforce_duty_cycle": False, "join_requests_s": [0],
                            "join_retries": 1, "join_accept_rx2_fallback": True},
        "groups": [
            {"name": f"sf{sf}", "count": 1, "region": "EU868",
             "channel_freq_hz": get_plan("EU868").uplink_channels_hz()[0],
             "placement": {"type": "disk", "radius_m": r},
             "spreading_factor": sf, "payload_bytes": 20, "tx_power_dbm": 14.0,
             "period_s": 30, "messages": 4, "start_spread_s": 10}
            for sf, r in ((7, 500), (9, 1000), (11, 1500), (12, 1900))
        ]}))
    radios = device_radios(sc)
    run = build_trace(sc, ProtocolOptions(confirmed_uplinks=True, downlink_every=1,
                                          downlink_payload_bytes=60, gateway_tx_power_dbm=27.0,
                                          rx2_fallback=True))
    devices, _g, _i = sc.deploy()
    res = simulate_confirmed_uplinks(devices, sc.gateway(), sc.propagation(), radios,
                                     ProtocolOptions(confirmed_uplinks=True, downlink_every=1,
                                                     downlink_payload_bytes=60,
                                                     gateway_tx_power_dbm=27.0,
                                                     rx2_fallback=True),
                                     sc.model.retransmissions.options(), with_engine_output=True)
    verite = {(t.device, e.at_ns): e.window for t in getattr(res, "joins", ())
              for e in t.accepts if e.outcome == "delivered"}

    print("\n\nD-I3-1 — fréquence rapportée des Join-Accept (EU868 : RX1 868,1 MHz / RX2 869,525 MHz)")
    changes = 0
    for e in run.events:
        if e.kind != "join_accept":
            continue
        fenetre = verite.get((e.device_index, e.t_ns))
        for h in e.hops:
            attendu = radios[e.device_index].rx2_hz if fenetre == RX2 else radios[e.device_index].rx1_hz
            if h.freq_hz != attendu:
                changes += 1
            print(f"  dev={e.device_index} t={e.t_ns / 1e6:9.3f} ms freq={h.freq_hz} "
                  f"fenêtre={fenetre} attendu={attendu}")
    print(f"écarts restants : {changes} (0 attendu après correction)")


if __name__ == "__main__":
    balayage_puissance()
    effet_d_i3_1()
