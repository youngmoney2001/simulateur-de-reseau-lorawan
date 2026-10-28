"""Export GeoJSON géoréférencé des résultats, pour la carte 3D (CesiumJS).

Les coordonnées locales (mètres, passerelle à l'origine du scénario) sont
converties en longitude/latitude autour d'une origine géographique, par
projection équirectangulaire locale (suffisante à l'échelle d'un déploiement,
quelques dizaines de kilomètres). Les portées de couverture sont calculées par
le cœur natif (bilan de liaison + modèle log-distance).
"""

from __future__ import annotations

import math
from typing import Any

from lsim.export import RunResult
from lsim.radio import LinkBudget, LogDistanceModel, receiver_sensitivity_dbm
from lsim.scenario import Scenario

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


def coverage_radius_m(scenario: Scenario, spreading_factor: int, tx_power_dbm: float) -> float:
    """Portée (m) pour un SF et une puissance donnés, via le bilan de liaison natif."""
    p = scenario.propagation()
    gw = scenario.model.gateway
    sensitivity = receiver_sensitivity_dbm(spreading_factor, 125_000)
    budget = LinkBudget(tx_power_dbm=tx_power_dbm, rx_antenna_gain_dbi=gw.antenna_gain_dbi)
    mapl = budget.max_allowable_path_loss_db(sensitivity)
    model = LogDistanceModel(frequency_hz=p.frequency_hz,
                             reference_distance_m=p.reference_distance_m,
                             exponent=p.exponent)
    return model.range_m(mapl)


def to_geojson(run: RunResult, scenario: Scenario, origin_lat: float, origin_lon: float) -> dict[str, Any]:
    """Construit une FeatureCollection : passerelle, couvertures par groupe, dispositifs."""
    _validate_origin(origin_lat, origin_lon)
    features: list[dict[str, Any]] = []
    gw = scenario.model.gateway
    features.append({
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": list(_to_lonlat(gw.x_m, gw.y_m, origin_lat, origin_lon))},
        "properties": {"kind": "gateway", "name": "passerelle"},
    })

    for group in scenario.model.groups:
        radius = coverage_radius_m(scenario, group.spreading_factor, group.tx_power_dbm)
        ring = []
        for k in range(_CIRCLE_VERTICES + 1):
            a = 2.0 * math.pi * k / _CIRCLE_VERTICES
            ring.append(list(_to_lonlat(gw.x_m + radius * math.cos(a), gw.y_m + radius * math.sin(a),
                                        origin_lat, origin_lon)))
        features.append({
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [ring]},
            "properties": {"kind": "coverage", "group": group.name,
                           "spreading_factor": group.spreading_factor,
                           "tx_power_dbm": group.tx_power_dbm,
                           "range_m": round(radius, 1)},
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
        },
    }
