"""Interface en ligne de commande : python -m lsim run scenario.yaml -o resultats.parquet"""

from __future__ import annotations

import argparse
import sys

from lsim.export import run_scenario, write_parquet
from lsim.scenario import load_scenario


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lsim", description="Simulateur LoRaWAN")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="exécuter un scénario YAML")
    run.add_argument("scenario", help="fichier YAML du scénario")
    run.add_argument("-o", "--output", required=True, help="fichier Parquet de sortie")
    args = parser.parse_args(argv)

    try:
        scenario = load_scenario(args.scenario)
        result = run_scenario(scenario)
        write_parquet(result, args.output)
    except (ValueError, OSError) as exc:
        print(f"erreur : {exc}", file=sys.stderr)
        return 2

    t = result.totals
    pdr = f"{result.pdr * 100:.2f} %" if result.pdr is not None else "n/a"
    print(f"scénario : {result.scenario_name} (sha256 {result.scenario_sha256[:12]})")
    print(f"émises {t.sent}, reçues {t.received}, PDR {pdr}")
    print(f"pertes : sensibilité {t.lost_sensitivity}, collision {t.lost_collision}")
    print(f"résultats : {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
