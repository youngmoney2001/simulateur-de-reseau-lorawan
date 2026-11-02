#!/usr/bin/env python3
"""D3.2 — F6/M2 : `d0` agit-il sur le modèle, et pourquoi l'exemple ne le voit-il pas ?

Le script du dépôt (`scripts/preuves/sonde_d0.py`) conclut « d0 n'agit qu'en présence d'un
relief » à partir d'une comparaison de **résultats de bout en bout**. La mesure directe du modèle
montre pourtant un décalage de `PL` de `(20 − 10n)·log10(d0₂/d0₁)`.

Cette sonde sépare les deux questions :
  1. le modèle : `PL(d)` pour `d0 = 1` et `d0 = 10` ;
  2. l'exemple : marge de chaque terminal par rapport à la sensibilité de son débit — c'est elle
     qui explique qu'aucune issue ne bascule.

Aucune modification de production ; lecture seule sur le dépôt.

Usage : p_d0_marge.py <racine_du_dépôt>
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(sys.argv[1])
sys.path.insert(0, str(ROOT / "python"))

from lsim.radio import LogDistanceModel, receiver_sensitivity_dbm   # noqa: E402
from lsim.scenario import load_scenario                            # noqa: E402
from lsim.trace_events import simulate_uplinks_trace               # noqa: E402


def main() -> int:
    print("=== 1. le modèle : PL(d) à n = 2,7 ===")
    for n in (2.7, 2.0):
        pour_1 = LogDistanceModel(frequency_hz=868.1e6, reference_distance_m=1.0, exponent=n)
        pour_10 = LogDistanceModel(frequency_hz=868.1e6, reference_distance_m=10.0, exponent=n)
        for d in (1000.0, 3000.0):
            a, b = pour_1.path_loss_db(d), pour_10.path_loss_db(d)
            print(f"  n={n}  d={d:6.0f} m : d0=1 -> {a:11.6f} dB | d0=10 -> {b:11.6f} dB "
                  f"| écart {b - a:+.6f} dB")

    print("\n=== 2. l'exemple : marge réelle des trames avant la sensibilité ===")
    tmp = Path(tempfile.mkdtemp()) / "examples"
    shutil.copytree(ROOT / "examples", tmp)
    for nom in ("quartier_sf9.yaml", "quartier_relief_sf9.yaml"):
        scenario = load_scenario(tmp / nom)
        devices, _group_of, _indices = scenario.deploy()
        resultat = simulate_uplinks_trace(devices, scenario.gateway(), scenario.propagation(),
                                         scenario.environment)
        marges = sorted(r.rssi_dbm - receiver_sensitivity_dbm(r.spreading_factor, 125_000)
                        for r in resultat.records)
        n = len(marges)
        proches = sum(1 for m in marges if abs(m) < 7.0)
        print(f"  {nom} : {n} trames émises")
        print(f"    marge min / médiane / max : {marges[0]:+.3f} / {marges[n // 2]:+.3f} "
              f"/ {marges[-1]:+.3f} dB")
        print(f"    trames à moins de 7 dB du seuil : {proches}  "
              f"(une bascule de 7 dB en déplacerait au plus {proches})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
