#!/usr/bin/env python3
"""Preuve D3.15 — §4 : effet de la charge et de la taille des trames sur le repli RX2.

Pour chaque (région, SF montant, taille de trame descendante), on rejoue la **même** chronologie
de bout en bout avec le repli RX2 activé puis désactivé, et on relève :

  - rx1 / rx2 / aucune : où chaque descente a finalement été émise ;
  - livrées           : descentes dont l'issue est « delivered » dans le cœur ;
  - occupation        : temps d'antenne cumulé de l'émetteur (secondes) ;
  - delta             : occupation(repli) − occupation(sans repli), en % — le **coût** du repli ;
  - gain              : livrées(repli) − livrées(sans repli) — le **bénéfice** du repli.

La même scène est rejouée deux fois : seule l'option de repli change, donc toute différence lui
est imputable, pas à la chronologie.

Usage (depuis la racine du dépôt) :
    LSIM_LIBRARY=build_i1/liblsim_core.so PYTHONPATH=python \
        python3 scripts/preuves/b_d315_charge.py [region ...]
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "python"))

from lsim.plan import get_plan
from lsim.scenario import Scenario, ScenarioModel
from lsim.simulator import simulate_uplinks_trace
from lsim.trace_events import (ProtocolOptions, _downlink_jobs, _events, _schedule_gateway,
                               device_radios)

REGIONS = ("EU868", "US915", "AS923", "AU915", "IN865", "KR920", "RU864")
TRAMES = (20, 60, 120, 240)
SFS = (7, 8, 9, 10, 11, 12)
SCENE = dict(count=60, period=5, messages=20, spread=60, rayon=600)


def _canal(region):
    return get_plan(region).uplink_channels_hz()[0]


def construire(region, sf):
    return Scenario(ScenarioModel.model_validate({
        "schema_version": 1, "name": "d315-charge", "seed": 11,
        "gateway": {"x_m": 0, "y_m": 0, "antenna_gain_dbi": 2.15},
        "propagation": {"frequency_hz": _canal(region), "exponent": 2.7},
        "groups": [{"name": "g0", "count": SCENE["count"], "region": region,
                    "channel_freq_hz": _canal(region),
                    "placement": {"type": "disk", "radius_m": SCENE["rayon"]},
                    "spreading_factor": sf, "payload_bytes": 20, "tx_power_dbm": 14.0,
                    "period_s": SCENE["period"], "messages": SCENE["messages"],
                    "start_spread_s": SCENE["spread"]}],
    }))


def mesurer(scenario, radios, records, charge, repli):
    options = ProtocolOptions(confirmed_uplinks=True, downlink_every=1,
                              downlink_payload_bytes=charge, gateway_tx_power_dbm=27.0,
                              rx2_fallback=repli)
    jobs = _downlink_jobs(records, radios, options, [False] * len(records), None)
    starts, fenetres, occupation = _schedule_gateway(jobs, options)
    roles = [False] * len(records)
    evenements = _events(records, radios, jobs, starts, roles, None, fenetres, options)
    livrees = sum(1 for e in evenements for h in e.hops
                  if h.to_id.startswith("dev:") and h.outcome in ("delivered", "received"))
    occ = sum(b - a for a, b in occupation) / 1e9
    return dict(jobs=len(jobs), rx1=fenetres.count("rx1"), rx2=fenetres.count("rx2"),
                aucune=fenetres.count(None), livrees=livrees, occupation=occ,
                debit=radios[0])


def main(regions):
    for region in regions:
        print(f"\n=== {region} ===")
        print("SF  RX1             RX2            | trame | repli :  rx1   rx2  aucune  livr "
              "| sans  :  rx1  aucune  livr |   occ(s)  Δocc   Δlivr")
        for sf in SFS:
            scenario = construire(region, sf)
            radios = device_radios(scenario)
            devices, _, _ = scenario.deploy()
            res = simulate_uplinks_trace(devices, scenario.gateway(), scenario.propagation(),
                                         scenario.environment, gateway_busy=())
            r0 = radios[0]
            entete = (f"{sf:<3d} SF{r0.rx1_sf}/BW{r0.rx1_bw_hz // 1000:<3d}   "
                      f"SF{r0.rx2_sf}/BW{r0.rx2_bw_hz // 1000:<3d}      |")
            for charge in TRAMES:
                avec = mesurer(scenario, radios, res.records, charge, True)
                sans = mesurer(scenario, radios, res.records, charge, False)
                delta = (100.0 * (avec["occupation"] - sans["occupation"]) / sans["occupation"]
                         if sans["occupation"] else 0.0)
                print(f"{entete} {charge:5d} |       {avec['rx1']:5d} {avec['rx2']:5d} "
                      f"{avec['aucune']:6d} {avec['livrees']:5d} |        {sans['rx1']:5d} "
                      f"{sans['aucune']:6d} {sans['livrees']:5d} | {avec['occupation']:8.1f} "
                      f"{delta:+6.1f}% {avec['livrees'] - sans['livrees']:+5d}")


if __name__ == "__main__":
    main(tuple(a.upper() for a in sys.argv[1:]) or REGIONS)
