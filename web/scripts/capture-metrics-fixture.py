#!/usr/bin/env python3
"""Régénère `web/tests/fixtures/run-metrics.json`, la matière du test de parité JS.

Le test `web/tests/metrics.test.mjs` compare les indicateurs affichés à des valeurs
recalculées à la main depuis les compteurs du serveur. Ce fixture est donc la sortie **brute**
de l'API — `GET /runs/{id}/summary` et `GET /runs/{id}/devices` —, pas une reconstitution.
Le régénérer après un changement du contrat de run, et recalculer alors les attentes du test.

Usage (depuis la racine du dépôt) :

    PYTHONPATH=python LSIM_LIBRARY=$PWD/build/liblsim_core.so \
      ./pyenv/bin/python web/scripts/capture-metrics-fixture.py

Le scénario exerce volontairement plusieurs branches à la fois : trois passerelles (donc un
tableau `gateways`, pas un bloc `gateway`), deux groupes de SF différents (la ventilation par
groupe a deux lignes), et un profil énergie (les trois indicateurs d'énergie sont présents).
"""

import contextlib
import json
import pathlib
import tempfile
import threading
import time
import urllib.error
import urllib.request

import lsim.api_server as srv

RACINE = pathlib.Path(__file__).resolve().parent.parent.parent
SORTIE = RACINE / "web" / "tests" / "fixtures" / "run-metrics.json"

SCENARIO = {
    "schema_version": 1,
    "name": "fixture indicateurs",
    "seed": 7,
    "energy": {"profile": "rak4631"},
    "propagation": {"frequency_hz": 868_100_000, "exponent": 2.7},
    "gateways": [
        {"name": "gw-nord", "x_m": 0, "y_m": 0, "antenna_gain_dbi": 2.15},
        {"name": "gw-est", "x_m": 2500, "y_m": 400, "antenna_gain_dbi": 2.15},
        {"name": "gw-ouest", "x_m": -2200, "y_m": -600, "antenna_gain_dbi": 2.15},
    ],
    "groups": [
        {"name": "capteurs-proches", "count": 12,
         "placement": {"type": "disk", "radius_m": 800, "center_x_m": 300, "center_y_m": 200},
         "spreading_factor": 7, "payload_bytes": 12, "tx_power_dbm": 14,
         "period_s": 300, "messages": 6, "start_spread_s": 300},
        {"name": "capteurs-lointains", "count": 10,
         "placement": {"type": "disk", "radius_m": 2500, "center_x_m": 400, "center_y_m": 0},
         "spreading_factor": 12, "payload_bytes": 24, "tx_power_dbm": 14,
         "period_s": 60, "messages": 10, "start_spread_s": 60},
    ],
}


class Client:
    """Client HTTP minimal : le serveur tourne en thread, dans le même processus."""

    def __init__(self, serveur, jeton):
        self.host, self.port = serveur.server_address[0], serveur.server_address[1]
        self.jeton = jeton

    def call(self, methode, chemin, corps=None):
        donnees = json.dumps(corps).encode() if corps is not None else None
        req = urllib.request.Request(f"http://{self.host}:{self.port}{chemin}",
                                     data=donnees, method=methode)
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", f"Bearer {self.jeton}")
        try:
            with urllib.request.urlopen(req) as r:
                brut = r.read().decode()
                return r.status, (json.loads(brut) if brut else None)
        except urllib.error.HTTPError as e:
            brut = e.read().decode()
            return e.code, (json.loads(brut) if brut else None)


@contextlib.contextmanager
def serveur_ephemere():
    tmp = pathlib.Path(tempfile.mkdtemp())
    jetons = tmp / "tokens.json"
    srv.TokenStore(jetons).issue("alice")
    serveur = srv.make_server("127.0.0.1", 0, jetons, runs_db=":memory:")
    thread = threading.Thread(target=serveur.serve_forever, daemon=True)
    thread.start()
    try:
        yield Client(serveur, srv.TokenStore(jetons).issue("alice"))
    finally:
        serveur.shutdown()


def attendre_fin(client, run_id, delai=300):
    echeance = time.time() + delai
    while time.time() < echeance:
        _, etat = client.call("GET", f"/api/v1/runs/{run_id}")
        if etat and etat.get("state") == "done":
            return etat
        if etat and etat.get("state") == "failed":
            raise RuntimeError(f"run échoué : {etat}")
        time.sleep(0.2)
    raise TimeoutError(run_id)


def main():
    with serveur_ephemere() as client:
        statut, cree = client.call("POST", "/api/v1/runs",
                                   {"scenario": SCENARIO, "energy_profile": "rak4631"})
        if statut != 202:
            raise SystemExit(f"création refusée ({statut}) : {cree}")
        run_id = cree["run_id"]
        attendre_fin(client, run_id)
        _, resume = client.call("GET", f"/api/v1/runs/{run_id}/summary")
        _, dispositifs = client.call("GET", f"/api/v1/runs/{run_id}/devices?limit=500")

    fixture = {"run_id": run_id, "summary": resume, "devices": dispositifs["items"]}
    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(json.dumps(fixture, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"écrit {SORTIE.relative_to(RACINE)} — run {run_id}")
    print(f"  {len(dispositifs['items'])} dispositifs, "
          f"{len(resume.get('gateways', []))} passerelles, "
          f"{len({d['group'] for d in dispositifs['items']})} groupes")
    print(f"  totaux : {json.dumps(resume['totals'], ensure_ascii=False)}")


if __name__ == "__main__":
    main()
