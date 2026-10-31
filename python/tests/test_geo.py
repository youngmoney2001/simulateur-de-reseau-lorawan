"""Export GeoJSON : projection locale, validation de l'origine, couverture native."""

import json
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


# --- G1 : regroupement de la couverture par (passerelle × groupe) -----------------------------
#
# `geo.py` ne résout aucune configuration RF (limite R2b documentée) : la couverture y est déjà
# calculée par groupe, à partir du `tx_power_dbm` du groupe et du SF du groupe. Les tests ci-dessous
# vérifient donc le contrat réellement exposé — regroupement, indices, effectifs, format homogène —
# sans supposer de champs (`device_indices_in_group`, `eirp_dbm`) qui n'existent pas.

GROUPE_FORT = {"name": "fort", "count": 4, "tx_power_dbm": 14.0, "sf": 9,
               "positions": [[100.0, 0.0], [120.0, 0.0], [140.0, 0.0], [160.0, 0.0]]}
GROUPE_FAIBLE = {"name": "faible", "count": 3, "tx_power_dbm": 8.0, "sf": 9,
                 "positions": [[100.0, 50.0], [120.0, 50.0], [140.0, 50.0]]}
COUVERTURE_KEYS = {"kind", "group", "gateway", "spreading_factor", "tx_power_dbm", "range_m", "model"}


def _scenario(tmp_path, groups, gateways=None, seed=42):
    """Scénario YAML minimal : positions explicites, propagation identique à `EXAMPLE`."""
    doc = {
        "schema_version": 1,
        "name": "G1",
        "seed": seed,
        "propagation": {"frequency_hz": 868_100_000, "reference_distance_m": 1,
                        "exponent": 2.7, "capture_threshold_db": 6},
        "groups": [
            {"name": g["name"], "count": g["count"],
             "placement": {"type": "explicit", "positions": g["positions"]},
             "spreading_factor": g["sf"], "payload_bytes": 20,
             "tx_power_dbm": g["tx_power_dbm"], "period_s": 900,
             "messages": 1, "start_spread_s": 0}
            for g in groups
        ],
    }
    if gateways is None:
        doc["gateway"] = {"x_m": 0, "y_m": 0, "antenna_gain_dbi": 2.15}
    else:
        doc["gateways"] = [{"name": name, "x_m": x, "y_m": y, "antenna_gain_dbi": 2.15}
                           for name, x, y in gateways]
    path = tmp_path / "scenario.yaml"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return load_scenario(path)


def _features(doc, kind):
    return [f["properties"] for f in doc["features"] if f["properties"]["kind"] == kind]


def test_g1_homogeneous_group_keeps_the_historical_format(tmp_path):
    """Un groupe homogène (une passerelle, une configuration) produit une couverture au format exact."""
    sc = _scenario(tmp_path, [GROUPE_FORT])
    doc = to_geojson(run_scenario(sc), sc, *DOUALA)
    coverage = _features(doc, "coverage")
    assert len(coverage) == 1
    props = coverage[0]
    assert set(props) == COUVERTURE_KEYS  # aucune clé optionnelle ajoutée
    assert props["group"] == "fort"
    assert props["spreading_factor"] == 9
    assert props["tx_power_dbm"] == pytest.approx(14.0)
    assert props["model"] == "log_distance"
    assert props["range_m"] > 0


def test_g1_one_coverage_per_group_and_device_indices_partitioned(tmp_path):
    """Deux groupes distincts ⇒ deux couvertures, et les indices de terminaux restent ceux du scénario."""
    sc = _scenario(tmp_path, [GROUPE_FORT, GROUPE_FAIBLE])
    run = run_scenario(sc)
    doc = to_geojson(run, sc, *DOUALA)
    coverage = _features(doc, "coverage")
    assert [c["group"] for c in coverage] == ["fort", "faible"]  # ordre de déclaration conservé
    assert [c["tx_power_dbm"] for c in coverage] == [pytest.approx(14.0), pytest.approx(8.0)]

    devices = _features(doc, "device")
    assert [d["group"] for d in devices] == ["fort"] * 4 + ["faible"] * 3
    assert [d["device_index"] for d in devices] == list(range(7))
    # Partition : chaque terminal est rattaché au groupe de sa couverture, sans recouvrement.
    counts = {name: sum(1 for d in devices if d["group"] == name) for name in ("fort", "faible")}
    assert counts == {"fort": 4, "faible": 3}
    assert sum(counts.values()) == len(devices) == len(run.rows)


def test_g1_heterogeneous_groups_differ_only_by_power_losses(tmp_path):
    """Deux groupes homogènes qui ne diffèrent que par les pertes : rayon strictement plus court."""
    sc = _scenario(tmp_path, [GROUPE_FORT, GROUPE_FAIBLE])
    doc = to_geojson(run_scenario(sc), sc, *DOUALA)
    fort, faible = _features(doc, "coverage")
    # 6 dB de PIRE en moins, à peu près linéaire en distance pour un modèle log-distance.
    assert faible["range_m"] < fort["range_m"]
    ratio = faible["range_m"] / fort["range_m"]
    # `range_m` est arrondi au décimètre : la tolérance couvre cet arrondi, pas le modèle.
    assert ratio == pytest.approx(10 ** (-6.0 / (10 * sc.propagation().exponent)), rel=1e-4)
    # Le regroupement survit à l'écart de configuration : deux entrées, pas une fusion.
    assert {fort["group"], faible["group"]} == {"fort", "faible"}


def test_g1_cross_gateway_group_yields_one_coverage_per_gateway_and_group(tmp_path):
    """Deux passerelles, deux groupes ⇒ G × Σ configs couvertures, une par couple."""
    sc = _scenario(tmp_path, [GROUPE_FORT, GROUPE_FAIBLE],
                   gateways=[("ouest", 0, 0), ("est", 500, 0)])
    doc = to_geojson(run_scenario(sc), sc, *DOUALA)
    coverage = _features(doc, "coverage")
    assert len(coverage) == 4
    assert [(c["gateway"], c["group"]) for c in coverage] == [
        ("ouest", "fort"), ("ouest", "faible"), ("est", "fort"), ("est", "faible")]
    # À configuration égale, la géométrie du couple ne dépend pas de la passerelle (pas de RF résolue).
    par_couple = {(c["gateway"], c["group"]): c["range_m"] for c in coverage}
    assert par_couple[("ouest", "fort")] == pytest.approx(par_couple[("est", "fort")])
    assert par_couple[("ouest", "faible")] == pytest.approx(par_couple[("est", "faible")])
    assert par_couple[("ouest", "fort")] > par_couple[("ouest", "faible")]


def test_g1_groups_with_identical_configuration_are_not_merged(tmp_path):
    """Deux groupes de configuration identique restent deux entrées : le regroupement suit le groupe.

    Un groupe ne peut pas être hétérogène (une seule configuration RF par groupe dans `GroupModel`) :
    l'analogue réel de « deux groupes dont un hétérogène » est qu'un regroupement par configuration
    équivalente ne doit pas fusionner deux groupes distincts.
    """
    jumeau = dict(GROUPE_FORT, name="fort-bis", positions=[[300.0, 0.0], [320.0, 0.0],
                                                           [340.0, 0.0], [360.0, 0.0]])
    sc = _scenario(tmp_path, [GROUPE_FORT, jumeau])
    doc = to_geojson(run_scenario(sc), sc, *DOUALA)
    coverage = _features(doc, "coverage")
    assert [c["group"] for c in coverage] == ["fort", "fort-bis"]
    assert all(set(c) == COUVERTURE_KEYS for c in coverage)
    assert coverage[0]["range_m"] == pytest.approx(coverage[1]["range_m"])
    rings = [f["geometry"] for f in doc["features"] if f["properties"]["kind"] == "coverage"]
    assert rings[0] == rings[1]  # même configuration ⇒ même géométrie, mais deux entrées

    devices = _features(doc, "device")
    assert [d["group"] for d in devices] == ["fort"] * 4 + ["fort-bis"] * 4
    assert [d["device_index"] for d in devices] == list(range(8))


def test_g1_range_agrees_with_the_link_budget_and_the_ring_geometry(tmp_path):
    """La portée publiée, `coverage_radius_m` et le rayon de l'anneau projeté concordent."""
    sc = _scenario(tmp_path, [GROUPE_FAIBLE])
    doc = to_geojson(run_scenario(sc), sc, *DOUALA)
    props, geometry = next((f["properties"], f["geometry"]) for f in doc["features"]
                           if f["properties"]["kind"] == "coverage")
    expected = coverage_radius_m(sc, props["spreading_factor"], props["tx_power_dbm"])
    assert props["range_m"] == pytest.approx(expected)

    lat0, lon0 = DOUALA
    ring = geometry["coordinates"][0]
    assert ring[0] == ring[-1]
    # Coordonnées GeoJSON : [longitude, latitude].
    dists = [
        math.hypot((lon - lon0) * math.pi / 180 * EARTH_RADIUS_M * math.cos(math.radians(lat0)),
                   (lat - lat0) * math.pi / 180 * EARTH_RADIUS_M)
        for lon, lat in ring[:-1]
    ]
    assert min(dists) == pytest.approx(expected, rel=1e-6)
    assert max(dists) == pytest.approx(expected, rel=1e-6)
