"""Export GeoJSON : projection locale, validation de l'origine, couverture native."""

import math
from pathlib import Path

import pytest

from lsim.export import run_scenario
from lsim.geo import EARTH_RADIUS_M, coverage_radius_m, to_geojson
from lsim.radio import LinkBudget, LogDistanceModel, receiver_sensitivity_dbm
from lsim.scenario import load_scenario

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "quartier_sf9.yaml"
DOUALA = (4.0511, 9.7679)


def test_coverage_matches_link_budget_formula():
    sc = load_scenario(EXAMPLE)
    sens = receiver_sensitivity_dbm(9, 125_000)
    mapl = LinkBudget(tx_power_dbm=14.0, rx_antenna_gain_dbi=2.15).max_allowable_path_loss_db(sens)
    p = sc.propagation()
    model = LogDistanceModel(frequency_hz=p.frequency_hz, reference_distance_m=p.reference_distance_m,
                             exponent=p.exponent)
    assert coverage_radius_m(sc, 9, 14.0) == pytest.approx(model.range_m(mapl))
    # Ordre de grandeur attendu : bien au-delà des 3 km du quartier simulé.
    assert coverage_radius_m(sc, 9, 14.0) > 3000


def test_north_offset_maps_to_latitude():
    sc = load_scenario(EXAMPLE)
    doc = to_geojson(run_scenario(sc), sc, *DOUALA)
    # Passerelle à l'origine locale : même point que l'origine géographique.
    gw = doc["features"][0]["geometry"]["coordinates"]
    assert gw[0] == pytest.approx(DOUALA[1]) and gw[1] == pytest.approx(DOUALA[0])


def test_projection_scale_is_correct():
    lat0, lon0 = DOUALA
    dlat_deg = math.degrees(1000.0 / EARTH_RADIUS_M)
    dlon_deg = math.degrees(1000.0 / (EARTH_RADIUS_M * math.cos(math.radians(lat0))))
    assert dlat_deg == pytest.approx(0.0089932, rel=1e-5)  # 1 000 m = 1/111,19 km par degré
    assert dlon_deg > dlat_deg  # à cette latitude, un degré de longitude est plus court


def test_feature_collection_contents():
    sc = load_scenario(EXAMPLE)
    run = run_scenario(sc)
    doc = to_geojson(run, sc, *DOUALA)
    kinds = [f["properties"]["kind"] for f in doc["features"]]
    assert kinds.count("gateway") == 1
    assert kinds.count("coverage") == len(sc.model.groups)
    assert kinds.count("device") == len(run.rows)
    assert doc["properties"]["scenario_sha256"] == sc.sha256
    assert doc["properties"]["total_received"] == run.totals.received
    ring = next(f for f in doc["features"] if f["properties"]["kind"] == "coverage")["geometry"]["coordinates"][0]
    assert ring[0] == ring[-1]  # anneau fermé


@pytest.mark.parametrize("lat, lon", [(float("nan"), 9.0), (0.0, 181.0), (85.0, 0.0)])
def test_invalid_origin_refused(lat, lon):
    sc = load_scenario(EXAMPLE)
    with pytest.raises(ValueError):
        to_geojson(run_scenario(sc), sc, lat, lon)
