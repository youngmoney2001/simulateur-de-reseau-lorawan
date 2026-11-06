#!/usr/bin/env python3
"""Balayage de graines du chemin de trace (diagnostic F1).

    LSIM_LIBRARY=build/liblsim_core.so python3 scripts/preuves/balayage_graines.py --seeds 40

Le script ne corrige rien : il compte les échecs de convergence (`RuntimeError` de point fixe) sur
les exemples du dépôt, pour chaque graine et chaque jeu d'options de trace.

État au 2026-10-31 : F1 est OUVERT et NON REPRODUIT — sur 40 graines de `quartier_sf9.yaml` puis
sur 3 exemples × 12 graines × 2 jeux d'options, aucune erreur n'a été observée. Ce script sert à
refaire la mesure, pas à la déclarer close.
"""
from __future__ import annotations

import argparse
import itertools
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))

try:
    from lsim.scenario import load_scenario  # noqa: E402
    from lsim.trace_events import ProtocolOptions, build_trace  # noqa: E402
except ModuleNotFoundError as exc:  # pragma: no cover - garde d'environnement
    raise SystemExit(f"dépendance absente ({exc.name}) : utiliser l'interpréteur du projet "
                     "(PYTHON=/chemin/vers/python)") from exc

EXAMPLES = ("quartier_sf9.yaml", "quartier_relief_sf9.yaml", "mesh_relais_quartier.yaml")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, default=40, help="nombre de graines (0..N-1)")
    parser.add_argument("--examples", nargs="*", default=list(EXAMPLES))
    parser.add_argument("--options", choices=("defaut", "confirme", "deux"), default="deux")
    args = parser.parse_args()

    jeux = {
        "defaut": [("defaut", ProtocolOptions())],
        "confirme": [("confirme", ProtocolOptions(confirmed_uplinks=True, downlink_every=2))],
        "deux": [("defaut", ProtocolOptions()),
                 ("confirme", ProtocolOptions(confirmed_uplinks=True, downlink_every=2))],
    }[args.options]

    failures, runs = [], 0
    with tempfile.TemporaryDirectory() as raw:
        # Les scénarios à relief référencent un CSV voisin : on copie tout le répertoire.
        directory = Path(raw) / "examples"
        shutil.copytree(ROOT / "examples", directory)
        for name in args.examples:
            source = (ROOT / "examples" / name).read_text(encoding="utf-8")
            if "seed: 42" not in source:
                raise SystemExit(f"{name} : aucune ligne `seed: 42` à remplacer")
            for seed, (label, options) in itertools.product(range(args.seeds), jeux):
                path = directory / f"{Path(name).stem}.{seed}.{label}.yaml"
                path.write_text(source.replace("seed: 42", f"seed: {seed}", 1), encoding="utf-8")
                runs += 1
                try:
                    build_trace(load_scenario(path), options)
                except RuntimeError as exc:
                    failures.append((name, seed, label, str(exc)[:80]))

    print(f"runs : {runs} | échecs de convergence : {len(failures)}")
    for failure in failures:
        print("   ", failure)
    if failures:
        print("F1 est REPRODUIT : consigner les graines ci-dessus avant toute correction.")
    else:
        print("F1 NON REPRODUIT avec ce balayage : ne pas conclure à l'absence du défaut, "
              "la paramétrisation d'origine n'est pas connue.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
