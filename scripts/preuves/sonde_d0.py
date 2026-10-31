#!/usr/bin/env python3
"""Sonde F6 / M2 : effet de `reference_distance_m` (d0) avec et sans relief.

    LSIM_LIBRARY=build/liblsim_core.so python3 scripts/preuves/sonde_d0.py

Diagnostic seul : le script ne corrige rien et ne modifie aucun fichier du dépôt (les scénarios
sont réécrits dans un répertoire temporaire). Attendu au commit 68176d6 :
  - sans relief : d0 = 1 et d0 = 10 donnent des sorties IDENTIQUES (d0 s'annule dans le modèle) ;
  - avec relief : les sorties DIFFÈRENT (d0 entre dans le calcul).
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))

try:
    from lsim.export import run_scenario  # noqa: E402
except ModuleNotFoundError as exc:  # pragma: no cover - garde d'environnement
    raise SystemExit(f"dépendance absente ({exc.name}) : utiliser l'interpréteur du projet "
                     "(PYTHON=/chemin/vers/python)") from exc
from lsim.scenario import load_scenario  # noqa: E402


def digest(run) -> tuple:
    rows = [(r.device_index, r.received, r.lost_sensitivity, r.lost_collision, round(r.pdr, 12))
            for r in run.rows]
    return rows, repr(run.totals), repr(run.gateway)


def run_at(directory: Path, source: Path, d0: float):
    target = directory / f"{source.stem}_d0_{d0:g}{source.suffix}"
    text = source.read_text(encoding="utf-8")
    if "reference_distance_m: 1" not in text:
        raise SystemExit(f"{source.name} : aucune ligne `reference_distance_m: 1` à remplacer")
    target.write_text(text.replace("reference_distance_m: 1", f"reference_distance_m: {d0:g}", 1),
                      encoding="utf-8")
    return digest(run_scenario(load_scenario(target)))


def compare(directory: Path, name: str) -> bool:
    source = directory / name
    if not source.is_file():
        raise SystemExit(f"scénario absent : {name}")
    return run_at(directory, source, 1.0) == run_at(directory, source, 10.0)


def main() -> int:
    with tempfile.TemporaryDirectory() as raw:
        directory = Path(raw) / "examples"
        shutil.copytree(ROOT / "examples", directory)
        sans_relief = compare(directory, "quartier_sf9.yaml")
        avec_relief = compare(directory, "quartier_relief_sf9.yaml")

    print(f"sans relief : d0 = 1 et d0 = 10 identiques ? {sans_relief}   (attendu : True)")
    print(f"avec relief : d0 = 1 et d0 = 10 identiques ? {avec_relief}  (attendu : False)")
    if sans_relief and not avec_relief:
        print("CONFORME au constat F6/M2 : d0 n'agit qu'en présence d'un relief.")
        return 0
    print("ÉCART au constat F6/M2 : le comportement de d0 a changé ; mettre à jour le registre.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
