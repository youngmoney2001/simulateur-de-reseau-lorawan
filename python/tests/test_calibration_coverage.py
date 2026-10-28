"""Calibrage log-distance, couverture réelle par azimut, export du MNT."""

import base64
import json
import math
import random
from array import array
from pathlib import Path

import pytest

from lsim.__main__ import main
from lsim.calibration import calibrate_path_loss
from lsim.environment import Environment, Obstacle, load_dem_csv
from lsim.export import run_scenario
from lsim.geo import coverage_ring, to_dem_document, to_geojson
from lsim.radio import free_space_path_loss_db
from lsim.scenario import load_scenario
from lsim.simulator import Gateway, Propagation, coverage_radii

ROOT = Path(__file__).resolve().parents[2]
F = 868.1e6


def _write_measures(path: Path, n: float, pl0: float, noise: float, seed: int = 1,
                    count: int = 60) -> Path:
    rng = random.Random(seed)
    lines = ["distance_m,path_loss_db"]
    for i in range(count):
        d = 10.0 * 10 ** (i * 2.5 / count)  # 10 m à ~3 km, log-régulier
        pl = pl0 + 10.0 * n * math.log10(d) + rng.gauss(0.0, noise)
        lines.append(f"{d:.3f},{pl:.4f}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# ------------------------------------------------------------ calibrage

def test_calibration_recovers_exponent_noise_free(tmp_path):
    f = _write_measures(tmp_path / "m.csv", n=2.9, pl0=40.0, noise=0.0)
    rep = calibrate_path_loss(f, d0_m=1.0)
    # Mesures écrites avec 3 et 4 décimales : tolérance d'arrondi.
    assert rep.exponent == pytest.approx(2.9, abs=1e-3)
    assert rep.pl0_db == pytest.approx(40.0, abs=1e-3)
    assert rep.sigma_db == pytest.approx(0.0, abs=1e-3)
    assert rep.r2 == pytest.approx(1.0, abs=1e-6)


def test_calibration_noisy_estimates_within_tolerance(tmp_path):
    f = _write_measures(tmp_path / "m.csv", n=3.4, pl0=45.0, noise=6.0, count=400)
    rep = calibrate_path_loss(f, d0_m=1.0)
    assert rep.exponent == pytest.approx(3.4, abs=0.15)
    assert rep.sigma_db == pytest.approx(6.0, abs=0.8)
    assert 0.0 < rep.r2 < 1.0


def test_calibration_from_rssi_columns(tmp_path):
    f = tmp_path / "rssi.csv"
    rows = ["distance_m,tx_power_dbm,rssi_dbm,gain_db"]
    for i in range(20):
        d = 20.0 * (i + 1)
        pl = 30.0 + 27.0 * math.log10(d)  # n = 2.7
        rows.append(f"{d},14,{14 + 2 - pl},2")  # gain_db = 2 ; rssi = tx + gain - PL
    f.write_text("\n".join(rows) + "\n", encoding="utf-8")
    rep = calibrate_path_loss(f, d0_m=1.0)
    assert rep.exponent == pytest.approx(2.7, abs=1e-9)


def test_calibration_offset_reports_free_space_difference(tmp_path):
    f = _write_measures(tmp_path / "m.csv", n=2.0, pl0=free_space_path_loss_db(1.0, F) + 5.0,
                        noise=0.0)
    rep = calibrate_path_loss(f, d0_m=1.0)
    assert rep.offset_db == pytest.approx(5.0, abs=1e-3)


def test_calibration_refuses_insufficient_or_bad_data(tmp_path):
    few = tmp_path / "few.csv"
    few.write_text("distance_m,path_loss_db\n10,50\n20,55\n", encoding="utf-8")
    with pytest.raises(ValueError, match="au moins"):
        calibrate_path_loss(few)
    bad_cols = tmp_path / "cols.csv"
    bad_cols.write_text("d,pl\n1,2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="distance_m"):
        calibrate_path_loss(bad_cols)
    close = _write_measures(tmp_path / "close.csv", n=2.0, pl0=40.0, noise=0.0)
    with pytest.raises(ValueError, match="d0"):
        calibrate_path_loss(close, d0_m=50.0)
    nan_row = tmp_path / "nan.csv"
    rows = ["distance_m,path_loss_db"] + [f"{10 + i},{50 + i}" for i in range(12)]
    rows[5] = "15,nan"
    nan_row.write_text("\n".join(rows) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="ligne 6"):
        calibrate_path_loss(nan_row)


def test_calibrate_cli_prints_exponent(tmp_path, capsys):
    f = _write_measures(tmp_path / "m.csv", n=2.5, pl0=40.0, noise=0.0)
    assert main(["calibrate", str(f)]) == 0
    out = capsys.readouterr().out
    assert "2.500" in out and "propagation.exponent: 2.50" in out


# ------------------------------------------------------------ couverture réelle

def _prop() -> Propagation:
    return Propagation(frequency_hz=F, reference_distance_m=1.0, exponent=2.7)


def test_coverage_without_environment_matches_log_distance_range():
    from lsim.radio import LogDistanceModel
    p = _prop()
    model = LogDistanceModel(frequency_hz=F, reference_distance_m=1.0, exponent=2.7)
    mapl = 120.0
    radii = coverage_radii(Gateway(), p, mapl, None, 10.0, 12)
    expect = model.range_m(mapl)
    for r in radii:
        assert r == pytest.approx(expect, abs=10.0 + 1e-6)


def test_coverage_is_reduced_by_obstacle_only_in_its_direction():
    p = _prop()
    mapl = 120.0
    flat = coverage_radii(Gateway(), p, mapl, None, 10.0, 8)
    wall = Obstacle(300.0, -200.0, 320.0, 200.0, 40.0, 60.0)
    walled = coverage_radii(Gateway(), p, mapl, Environment(obstacles=(wall,)), 10.0, 8)
    assert walled[0] < 300.0 + 1.0
    assert walled[4] == pytest.approx(flat[4], abs=10.0 + 1e-6)
    assert all(w <= f + 1e-6 for w, f in zip(walled, flat))


def test_coverage_ring_reports_environment_model(tmp_path):
    f = tmp_path / "s.yaml"
    f.write_text("""
schema_version: 1
name: c
seed: 1
groups:
  - {name: g, count: 3, placement: {type: disk, radius_m: 100}, spreading_factor: 7, period_s: 600}
environment:
  obstacles:
    - {x_min_m: 200, y_min_m: -100, x_max_m: 230, y_max_m: 100, height_m: 40, attenuation_db: 30}
""", encoding="utf-8")
    sc = load_scenario(f)
    ring, model_name, radius = coverage_ring(sc, 7, 14.0, 4.05, 9.76)
    assert model_name == "environment"
    assert ring[0] == ring[-1] and len(ring) == 181
    assert radius > 0.0


def test_geojson_coverage_model_flags(tmp_path):
    sc = load_scenario(ROOT / "examples" / "quartier_sf9.yaml")
    doc = to_geojson(run_scenario(sc), sc, 4.0511, 9.7679)
    cov = [f for f in doc["features"] if f["properties"].get("kind") == "coverage"]
    assert cov[0]["properties"]["model"] == "log_distance"
    relief = load_scenario(ROOT / "examples" / "quartier_relief_sf9.yaml")
    doc2 = to_geojson(run_scenario(relief), relief, 4.0511, 9.7679)
    cov2 = [f for f in doc2["features"] if f["properties"].get("kind") == "coverage"]
    assert cov2[0]["properties"]["model"] == "environment"
    assert doc2["properties"]["environment"]["obstacles"] == 5
    json.dumps(doc2)


# ------------------------------------------------------------ MNT pour la carte

def test_dem_document_round_trips_grid(tmp_path):
    relief = load_scenario(ROOT / "examples" / "quartier_relief_sf9.yaml")
    dem = to_dem_document(relief, 4.0511, 9.7679)
    assert dem["format"] == "lsim-dem-v1"
    raw = base64.b64decode(dem["z"])
    values = array("f")
    values.frombytes(raw)
    assert len(values) == dem["nx"] * dem["ny"] == relief.environment.terrain.nx * relief.environment.terrain.ny
    assert values[0] == pytest.approx(relief.environment.terrain.z[0])
    assert dem["sha256"] == relief.environment.terrain.sha256


def test_dem_document_requires_terrain():
    sc = load_scenario(ROOT / "examples" / "quartier_sf9.yaml")
    with pytest.raises(ValueError):
        to_dem_document(sc, 4.0, 9.7)


def test_cli_writes_dem_file(tmp_path):
    out = tmp_path / "map.geojson"
    dem = tmp_path / "dem.json"
    rc = main(["geojson", str(ROOT / "examples" / "quartier_relief_sf9.yaml"),
               "-o", str(out), "--dem", str(dem)])
    assert rc == 0
    assert json.loads(dem.read_text())["format"] == "lsim-dem-v1"
    assert json.loads(out.read_text())["properties"]["environment"]["terrain"] is True


def test_dem_fast_path_matches_python_for_row_major(tmp_path):
    p = tmp_path / "d.csv"
    lines = ["x_m,y_m,z_m"] + [f"{ix * 5.0},{iy * 5.0},{ix + 2 * iy}"
                               for iy in range(7) for ix in range(9)]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    t = load_dem_csv(p)
    assert (t.nx, t.ny, t.cell_m) == (9, 7, 5.0)
    assert t.z[3 * 9 + 4] == pytest.approx(4 + 6)
