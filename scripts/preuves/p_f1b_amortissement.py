#!/usr/bin/env python3
"""D3.2 — F1-b : les amortissements d'état accélèrent-ils le point fixe ? (rejeu)

Objet : convertir en mesure un résultat qui n'était que *rapporté* — « les deux variantes
d'amortissement (`intersection`, `union`) ne convergent pas, même à 128 itérations ».

Méthode : la boucle à point fixe de `_build_trace_python` est réimplémentée **à l'identique** ici
(mêmes deux appels, même critère d'arrêt : `new_busy == busy and new_joined == joined`), avec un
paramètre d'amortissement. Aucune modification du code de production : `simulate_uplinks_trace` et
`_plan` sont appelés tels quels.

Variantes :
  none  — `busy ← new_busy`            (référence, comportement publié)
  inter — `busy ← busy ∩ new_busy`
  union — `busy ← busy ∪ new_busy`

Usage : p_f1b_amortissement.py <racine_du_dépôt> <fichier_json_de_sortie> [maxit]
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(sys.argv[1])
OUT = Path(sys.argv[2])
MAXIT = int(sys.argv[3]) if len(sys.argv) > 3 else 128
sys.path.insert(0, str(ROOT / "python"))

from lsim.scenario import load_scenario          # noqa: E402
from lsim.trace_events import (                  # noqa: E402
    ProtocolOptions, _plan, device_radios, simulate_uplinks_trace,
)

SOURCE = "quartier_sf9.yaml"
COUNT = 2000
JEUX = {
    "join": (dict(join=True), (7, 19, 36)),
    "join+conf+dl1": (dict(join=True, confirmed_uplinks=True, downlink_every=1), (0, 7, 36)),
}


def boucle(devices, radios, gateway, propagation, environment, options, amortissement, maxit):
    """Réplique de la boucle de `_build_trace_python`, avec amortissement optionnel."""
    busy: list = []
    joined: dict = {}
    for iteration in range(1, maxit + 1):
        resultat = simulate_uplinks_trace(devices, gateway, propagation, environment,
                                          gateway_busy=busy, reservations=())
        _roles, _jobs, _starts, new_busy, new_joined = _plan(resultat.records, radios, options,
                                                             joined, None)
        if new_busy == busy and new_joined == joined:
            return True, iteration
        if amortissement == "inter":
            ensemble = set(busy)
            busy = [b for b in new_busy if b in ensemble]
        elif amortissement == "union":
            busy = sorted(set(busy) | set(new_busy))
        else:
            busy = new_busy
        joined = new_joined
    return False, maxit


def main() -> int:
    tmp = Path(tempfile.mkdtemp()) / "examples"
    shutil.copytree(ROOT / "examples", tmp)
    base = (tmp / SOURCE).read_text(encoding="utf-8").replace("count: 500", f"count: {COUNT}", 1)

    resultats = []
    for jeu, (kwargs, graines) in JEUX.items():
        for graine in graines:
            chemin = tmp / f"n{COUNT}_{jeu}_{graine}.yaml"
            chemin.write_text(base.replace("seed: 42", f"seed: {graine}", 1), encoding="utf-8")
            scenario = load_scenario(chemin)
            devices, _group_of, _indices = scenario.deploy()
            radios = device_radios(scenario)
            gateway, propagation = scenario.gateway(), scenario.propagation()
            environment = scenario.environment
            options = ProtocolOptions(**kwargs)
            for amortissement in ("none", "inter", "union"):
                converge, iterations = boucle(devices, radios, gateway, propagation, environment,
                                              options, amortissement, MAXIT)
                entree = {
                    "config": {"source": SOURCE, "count": COUNT, "graine": graine, "jeu": jeu,
                               "options": {"join": kwargs.get("join", False),
                                           "confirmed_uplinks": kwargs.get("confirmed_uplinks",
                                                                           False),
                                           "downlink_every": kwargs.get("downlink_every", 0)},
                               "amortissement": amortissement, "maxit": MAXIT},
                    "converge": converge, "iterations": iterations,
                }
                resultats.append(entree)
                print(f"{jeu:15s} graine {graine:2d} {amortissement:5s} "
                      f"converge={converge!s:5s} itérations={iterations}", flush=True)
    OUT.write_text(json.dumps(resultats, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"\nJSON : {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
