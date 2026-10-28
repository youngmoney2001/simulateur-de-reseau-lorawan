"""Export GeoJSON géoréférencé des résultats, pour la carte 3D (CesiumJS).

Les coordonnées locales (mètres, passerelle à l'origine du scénario) sont
converties en longitude/latitude autour d'une origine géographique, par
projection équirectangulaire locale (suffisante à l'échelle d'un déploiement,
quelques dizaines de kilomètres). Les portées de couverture sont calculées par
le cœur natif (bilan de liaison + modèle log-distance).
"""

from __future__ import annotations

import base64
import math
import sys
from array import array
from typing import Any

from lsim.export import RunResult
from lsim.radio import LinkBudget, LogDistanceModel, receiver_sensitivity_dbm
from lsim.scenario import Scenario
from lsim.simulator import Gateway, coverage_radii

EARTH_RADIUS_M = 6_371_000.0
_CIRCLE_VERTICES = 96


def _to_lonlat(x_m: float, y_m: float, origin_lat: float, origin_lon: float) -> tuple[float, float]:
    lat = origin_lat + math.degrees(y_m / EARTH_RADIUS_M)
    lon = origin_lon + math.degrees(x_m / (EARTH_RADIUS_M * math.cos(math.radians(origin_lat))))
    return lon, lat


def _validate_origin(lat: float, lon: float) -> None:
    if not (math.isfinite(lat) and math.isfinite(lon)):
        raise ValueError("origine géographique non finie")
    if not -80.0 <= lat <= 80.0 or not -180.0 <= lon <= 180.0:
        raise ValueError("origine hors domaine (latitude ±80, longitude ±180)")


COVERAGE_AZIMUTHS = 180
COVERAGE_STEP_M = 25.0
DEM_FORMAT = "lsim-dem-v1"


def _mapl_db(scenario: Scenario, spreading_factor: int, tx_power_dbm: float) -> float:
    gw = scenario.model.gateway
    sensitivity = receiver_sensitivity_dbm(spreading_factor, 125_000)
    budget = LinkBudget(tx_power_dbm=tx_power_dbm, rx_antenna_gain_dbi=gw.antenna_gain_dbi)
    return budget.max_allowable_path_loss_db(sensitivity)


def coverage_radius_m(scenario: Scenario, spreading_factor: int, tx_power_dbm: float) -> float:
    """Portée (m) pour un SF et une puissance donnés, via le bilan de liaison natif.

    Log-distance seul, sans relief ni obstacle : c'est une borne haute de la portée réelle.
    """
    p = scenario.propagation()
    model = LogDistanceModel(frequency_hz=p.frequency_hz,
                             reference_distance_m=p.reference_distance_m,
                             exponent=p.exponent)
    return model.range_m(_mapl_db(scenario, spreading_factor, tx_power_dbm))


def coverage_ring(scenario: Scenario, spreading_factor: int, tx_power_dbm: float,
                  origin_lat: float, origin_lon: float) -> tuple[list[list[float]], str, float]:
    """Anneau de couverture (lon/lat) et modèle utilisé.

    Avec environnement : portée réelle par azimut (relief et obstacles, calcul natif).
    Sans environnement : cercle log-distance, identique au calcul précédent.
    Retourne (anneau fermé, nom du modèle, portée maximale en m).
    """
    gw = scenario.model.gateway
    env = scenario.environment
    if env is None:
        radius = coverage_radius_m(scenario, spreading_factor, tx_power_dbm)
        ring = []
        for k in range(_CIRCLE_VERTICES + 1):
            a = 2.0 * math.pi * k / _CIRCLE_VERTICES
            ring.append(list(_to_lonlat(gw.x_m + radius * math.cos(a), gw.y_m + radius * math.sin(a),
                                        origin_lat, origin_lon)))
        return ring, "log_distance", radius

    radii = coverage_radii(
        Gateway(x_m=gw.x_m, y_m=gw.y_m, antenna_gain_dbi=gw.antenna_gain_dbi),
        scenario.propagation(), _mapl_db(scenario, spreading_factor, tx_power_dbm), env,
        COVERAGE_STEP_M, COVERAGE_AZIMUTHS)
    ring = []
    for k, r in enumerate(radii):
        a = 2.0 * math.pi * k / COVERAGE_AZIMUTHS
        ring.append(list(_to_lonlat(gw.x_m + r * math.cos(a), gw.y_m + r * math.sin(a),
                                    origin_lat, origin_lon)))
    ring.append(list(ring[0]))
    return ring, "environment", max(radii)


def to_dem_document(scenario: Scenario, origin_lat: float, origin_lon: float) -> dict[str, Any]:
    """MNT du scénario pour la carte : grille float32 little-endian encodée en base64.

    Les coordonnées locales restent celles du scénario ; l'origine géographique
    permet à la carte de projeter la grille. Lève ValueError sans relief déclaré.
    """
    _validate_origin(origin_lat, origin_lon)
    env = scenario.environment
    if env is None or env.terrain is None:
        raise ValueError("le scénario ne déclare pas de relief")
    t = env.terrain
    raw = array("f", t.z)
    if sys.byteorder == "big":
        raw.byteswap()
    return {
        "format": DEM_FORMAT,
        "origin": {"latitude": origin_lat, "longitude": origin_lon},
        "origin_x_m": t.origin_x_m,
        "origin_y_m": t.origin_y_m,
        "cell_m": t.cell_m,
        "nx": t.nx,
        "ny": t.ny,
        "encoding": "float32-le-base64",
        "z": base64.b64encode(raw.tobytes()).decode("ascii"),
        "sha256": t.sha256,
    }


def to_geojson(run: RunResult, scenario: Scenario, origin_lat: float, origin_lon: float) -> dict[str, Any]:
    """Construit une FeatureCollection : passerelle, couvertures par groupe, dispositifs."""
    _validate_origin(origin_lat, origin_lon)
    features: list[dict[str, Any]] = []
    gw = scenario.model.gateway
    env = scenario.environment
    features.append({
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": list(_to_lonlat(gw.x_m, gw.y_m, origin_lat, origin_lon))},
        "properties": {"kind": "gateway", "name": "passerelle",
                       "height_m": env.gateway_height_m if env is not None else None},
    })

    for group in scenario.model.groups:
        ring, model_name, radius = coverage_ring(
            scenario, group.spreading_factor, group.tx_power_dbm, origin_lat, origin_lon)
        # `model` : "environment" = portée réelle (relief, obstacles) ; "log_distance" = cercle
        # sans environnement. `range_m` est la portée maximale sur les azimuts.
        features.append({
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [ring]},
            "properties": {"kind": "coverage", "group": group.name,
                           "spreading_factor": group.spreading_factor,
                           "tx_power_dbm": group.tx_power_dbm,
                           "range_m": round(radius, 1),
                           "model": model_name},
        })

    if env is not None:
        for i, o in enumerate(env.obstacles):
            corners = [(o.x_min_m, o.y_min_m), (o.x_max_m, o.y_min_m),
                       (o.x_max_m, o.y_max_m), (o.x_min_m, o.y_max_m), (o.x_min_m, o.y_min_m)]
            ring = [list(_to_lonlat(x, y, origin_lat, origin_lon)) for x, y in corners]
            features.append({
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [ring]},
                "properties": {"kind": "obstacle", "index": i, "height_m": o.height_m,
                               "attenuation_db": o.attenuation_db},
            })

    for r in run.rows:
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": list(_to_lonlat(r.x_m, r.y_m, origin_lat, origin_lon))},
            "properties": {"kind": "device", "device_index": r.device_index, "group": r.group,
                           "spreading_factor": r.spreading_factor, "sent": r.sent,
                           "received": r.received, "lost_sensitivity": r.lost_sensitivity,
                           "lost_collision": r.lost_collision,
                           "pdr": r.pdr},
        })

    return {
        "type": "FeatureCollection",
        "features": features,
        "properties": {
            "scenario_name": run.scenario_name,
            "scenario_sha256": run.scenario_sha256,
            "origin": {"latitude": origin_lat, "longitude": origin_lon},
            "total_sent": run.totals.sent,
            "total_received": run.totals.received,
            "pdr": run.pdr,
            "environment": None if env is None else {
                "gateway_height_m": env.gateway_height_m,
                "device_height_m": env.device_height_m,
                "terrain": env.terrain is not None,
                "terrain_sha256": env.terrain.sha256 if env.terrain is not None else None,
                "obstacles": len(env.obstacles),
            },
        },
    }
