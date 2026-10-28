"""Interface en ligne de commande : python -m lsim run scenario.yaml -o resultats.parquet"""

from __future__ import annotations

import argparse
import json
import sys

from lsim.export import run_scenario, write_parquet
from lsim.geo import to_geojson
from lsim.scenario import load_scenario


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lsim", description="Simulateur LoRaWAN")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="exécuter un scénario YAML")
    run.add_argument("scenario", help="fichier YAML du scénario")
    run.add_argument("-o", "--output", required=True, help="fichier Parquet de sortie")
    geo = sub.add_parser("geojson", help="exporter les résultats en GeoJSON géoréférencé")
    geo.add_argument("scenario", help="fichier YAML du scénario")
    geo.add_argument("-o", "--output", required=True, help="fichier GeoJSON de sortie")
    # Par défaut : Douala (Littoral, Cameroun).
    geo.add_argument("--origin", default="4.0511,9.7679",
                     help="origine latitude,longitude de la passerelle (défaut : Douala)")
    args = parser.parse_args(argv)

    if args.command == "geojson":
        return _geojson(args)

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


def _geojson(args: argparse.Namespace) -> int:
    try:
        lat_s, lon_s = args.origin.split(",")
        lat, lon = float(lat_s), float(lon_s)
        scenario = load_scenario(args.scenario)
        result = run_scenario(scenario)
        doc = to_geojson(result, scenario, lat, lon)
        with open(args.output, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False, separators=(",", ":"))
    except (ValueError, OSError) as exc:
        print(f"erreur : {exc}", file=sys.stderr)
        return 2
    print(f"carte : {args.output} ({len(doc['features'])} entités)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
