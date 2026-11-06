"""Sortie de référence sans MAC : run_scenario et build_trace sur examples/*.yaml.

Usage (depuis la racine du dépôt, PYTHONPATH=python, LSIM_LIBRARY=liblsim_core.so) :
    python scripts/mac_baseline_dump.py SORTIE.json
Comparer les fichiers produits par deux versions (ex. base 1f43370 et courante) : doivent être identiques."""

import json, sys, glob
from lsim.scenario import load_scenario
from lsim.export import run_scenario
out = {}
files = sorted(glob.glob("examples/*.yaml"))
for f in files:
    sc = load_scenario(f)
    for prof in (None, "rak4631"):
        try:
            r = run_scenario(sc, prof)
            out[f"{f}|{prof}"] = {
                "rows": [repr(x) for x in r.rows],
                "totals": repr(r.totals),
                "gateway": repr(r.gateway),
            }
        except Exception as e:
            out[f"{f}|{prof}"] = {"error": f"{type(e).__name__}: {e}"}
json.dump(out, open(sys.argv[1], "w"), indent=1, sort_keys=True, ensure_ascii=False)
print(len(out), "entries")
from lsim.trace_events import ProtocolOptions, build_trace
tr = {}
for f in files:
    sc = load_scenario(f)
    for opts in (ProtocolOptions(), ProtocolOptions(confirmed_uplinks=True, downlink_every=2)):
        key = f"{f}|{opts}"
        try:
            t = build_trace(sc, opts)
            tr[key] = {
                "events": [repr((e.kind, e.t_ns, e.outcome, getattr(e, "device_index", None), getattr(e, "hops", None))) for e in t.events],
                "gateway_tx": repr(t.gateway_tx),
                "per_device": [repr(c) for c in t.per_device] if hasattr(t, "per_device") else None,
            }
        except Exception as e:
            tr[key] = {"error": f"{type(e).__name__}: {e}"}
json.dump(tr, open(sys.argv[1] + ".trace.json", "w"), indent=1, sort_keys=True, ensure_ascii=False)
print("trace", len(tr))
