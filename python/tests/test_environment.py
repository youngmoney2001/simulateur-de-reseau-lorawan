"""Relief et obstacles : validation, MNT CSV, intégration simulateur, scénarios, GeoJSON."""

import json
import math
from pathlib import Path

import pytest

from lsim.environment import Environment, Obstacle, load_dem_csv
from lsim.export import run_scenario
from lsim.geo import to_geojson
from lsim.scenario import load_scenario
from lsim.simulator import EndDevice, Gateway, Propagation, simulate_uplinks
from lsim.status import describe

ROOT = Path(__file__).resolve().parents[2]


def _grid_csv(path: Path, nx: int, ny: int, cell: float, z_of=lambda x, y: 0.0) -> Path:
    lines = ["x_m,y_m,z_m"]
    for iy in range(ny):
        for ix in range(nx):
            x, y = ix * cell, iy * cell
            lines.append(f"{x},{y},{z_of(x, y)}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# ----------------------------------------------------------------- obstacles

def test_obstacle_rejects_empty_box_and_bad_values():
    with pytest.raises(ValueError):
        Obstacle(10.0, 0.0, 10.0, 5.0, 10.0)
    with pytest.raises(ValueError):
        Obstacle(0.0, 0.0, 1.0, 1.0, 0.0)
    with pytest.raises(ValueError):
        Obstacle(0.0, 0.0, 1.0, 1.0, float("nan"))
    with pytest.raises(ValueError):
        Obstacle(0.0, 0.0, 1.0, 1.0, 10.0, attenuation_db=-1.0)


def test_flat_environment_equals_no_environment():
    devs = [EndDevice(x_m=100.0 + 300.0 * i, spreading_factor=7 + i % 3) for i in range(20)]
    base = simulate_uplinks(devs, Gateway(), Propagation())
    flat = simulate_uplinks(devs, Gateway(), Propagation(), Environment())
    assert base == flat


def test_wall_blocks_reception_and_is_deterministic():
    devs = [EndDevice(x_m=1000.0)]
    wall = Obstacle(500.0, -50.0, 600.0, 50.0, 30.0, 200.0)
    free = simulate_uplinks(devs, Gateway(), Propagation())
    blocked = simulate_uplinks(devs, Gateway(), Propagation(), Environment(obstacles=(wall,)))
    again = simulate_uplinks(devs, Gateway(), Propagation(), Environment(obstacles=(wall,)))
    assert free.totals.received == 1
    assert blocked.totals.received == 0
    assert blocked == again


def test_tall_obstacle_off_path_has_no_effect():
    devs = [EndDevice(x_m=1000.0)]
    far = Obstacle(500.0, 5000.0, 600.0, 5100.0, 30.0, 200.0)
    base = simulate_uplinks(devs, Gateway(), Propagation())
    other = simulate_uplinks(devs, Gateway(), Propagation(), Environment(obstacles=(far,)))
    assert base == other


def test_obstacle_count_over_limit_is_refused():
    many = tuple(Obstacle(i, 0.0, i + 1.0, 1.0, 5.0) for i in range(10_001))
    with pytest.raises(ValueError):
        Environment(obstacles=many)


# ----------------------------------------------------------------- MNT CSV

def test_dem_csv_loads_regular_grid(tmp_path):
    p = _grid_csv(tmp_path / "dem.csv", 4, 3, 50.0, lambda x, y: x / 10.0 + y)
    t = load_dem_csv(p)
    assert (t.nx, t.ny, t.cell_m) == (4, 3, 50.0)
    assert t.origin_x_m == 0.0 and t.origin_y_m == 0.0
    assert t.z[1 * 4 + 2] == pytest.approx(2 * 50.0 / 10.0 + 50.0)
    assert len(t.sha256) == 64


def test_dem_csv_rejects_incomplete_grid(tmp_path):
    p = tmp_path / "dem.csv"
    p.write_text("x_m,y_m,z_m\n0,0,1\n50,0,1\n0,50,1\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_dem_csv(p)


def test_dem_csv_rejects_irregular_spacing(tmp_path):
    p = tmp_path / "dem.csv"
    p.write_text("x_m,y_m,z_m\n0,0,1\n50,0,1\n120,0,1\n0,50,1\n50,50,1\n120,50,1\n",
                 encoding="utf-8")
    with pytest.raises(ValueError):
        load_dem_csv(p)


def test_dem_csv_rejects_bad_header_and_nan(tmp_path):
    p = tmp_path / "dem.csv"
    p.write_text("a,b,c\n0,0,1\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_dem_csv(p)
    p.write_text("x_m,y_m,z_m\n0,0,nan\n50,0,1\n0,50,1\n50,50,1\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_dem_csv(p)


def test_terrain_ridge_reduces_reception(tmp_path):
    # Crête de 80 m entre la passerelle (0, 0) et le dispositif (1000, 0).
    p = _grid_csv(tmp_path / "dem.csv", 41, 3, 50.0,
                  lambda x, y: 80.0 if 480.0 <= x <= 520.0 else 0.0)
    t = load_dem_csv(p)
    devs = [EndDevice(x_m=1000.0)]
    flat = simulate_uplinks(devs, Gateway(), Propagation())
    ridge = simulate_uplinks(devs, Gateway(), Propagation(), Environment(terrain=t))
    assert flat.totals.received == 1
    assert ridge.totals.received == 0


# ----------------------------------------------------------------- scénarios

BASE = """
schema_version: 1
name: relief
seed: 3
groups:
  - name: g
    count: 5
    placement: {type: disk, radius_m: 800}
    spreading_factor: 9
    period_s: 600
    messages: 2
"""


def test_scenario_without_environment_keeps_example_hash():
    sc = load_scenario(ROOT / "examples" / "quartier_sf9.yaml")
    assert sc.sha256 == "07a43b998244" + sc.sha256[12:]
    assert sc.environment is None


def test_scenario_with_obstacles_and_terrain(tmp_path):
    _grid_csv(tmp_path / "dem.csv", 3, 3, 500.0)
    yaml_text = BASE + """
environment:
  gateway_height_m: 20
  terrain: {type: dem_csv, path: dem.csv}
  obstacles:
    - {x_min_m: 300, y_min_m: -20, x_max_m: 340, y_max_m: 20, height_m: 25, attenuation_db: 15}
"""
    f = tmp_path / "s.yaml"
    f.write_text(yaml_text, encoding="utf-8")
    sc = load_scenario(f)
    assert sc.environment is not None
    assert sc.environment.terrain is not None and sc.environment.gateway_height_m == 20.0
    assert len(sc.environment.obstacles) == 1
    res = run_scenario(sc)
    assert res.totals.sent > 0
    assert res.scenario_sha256 == sc.sha256


def test_scenario_hash_covers_environment(tmp_path):
    _grid_csv(tmp_path / "dem.csv", 3, 3, 500.0)
    hashes = []
    for h in (25, 26):
        f = tmp_path / f"s{h}.yaml"
        f.write_text(BASE + f"""
environment:
  terrain: {{type: dem_csv, path: dem.csv}}
  obstacles:
    - {{x_min_m: 100, y_min_m: 0, x_max_m: 140, y_max_m: 40, height_m: {h}}}
""", encoding="utf-8")
        hashes.append(load_scenario(f).sha256)
    assert hashes[0] != hashes[1]
    assert len(hashes[0]) == 64


def test_scenario_terrain_path_must_stay_inside(tmp_path):
    f = tmp_path / "s.yaml"
    for bad in ("../dem.csv", "/etc/passwd", "sub/../../dem.csv"):
        f.write_text(BASE + f"environment:\n  terrain: {{type: dem_csv, path: '{bad}'}}\n",
                     encoding="utf-8")
        with pytest.raises(ValueError):
            load_scenario(f)


def test_scenario_missing_terrain_file_is_refused(tmp_path):
    f = tmp_path / "s.yaml"
    f.write_text(BASE + "environment:\n  terrain: {type: dem_csv, path: absent.csv}\n",
                 encoding="utf-8")
    with pytest.raises(ValueError):
        load_scenario(f)


def test_scenario_rejects_unknown_environment_field(tmp_path):
    f = tmp_path / "s.yaml"
    f.write_text(BASE + "environment:\n  antenne: 3\n", encoding="utf-8")
    with pytest.raises(ValueError):  # pydantic ValidationError hérite de ValueError
        load_scenario(f)


def test_geojson_contains_obstacles(tmp_path):
    f = tmp_path / "s.yaml"
    f.write_text(BASE + """
environment:
  obstacles:
    - {x_min_m: 100, y_min_m: 0, x_max_m: 140, y_max_m: 40, height_m: 12}
""", encoding="utf-8")
    sc = load_scenario(f)
    doc = to_geojson(run_scenario(sc), sc, 4.0511, 9.7679)
    obs = [ft for ft in doc["features"] if ft["properties"].get("kind") == "obstacle"]
    assert len(obs) == 1
    assert obs[0]["properties"]["height_m"] == 12.0
    assert obs[0]["geometry"]["type"] == "Polygon"
    cov = [ft for ft in doc["features"] if ft["properties"].get("kind") == "coverage"]
    # Scénario avec obstacles : la couverture est la portée réelle par azimut.
    assert all(ft["properties"]["model"] == "environment" for ft in cov)
    json.dumps(doc)


def test_status_names_for_environment_codes():
    assert "obstacle" in describe(503)
    assert "relief" in describe(501)
    assert describe(305).startswith("environnement")


def test_dem_fast_and_python_paths_agree(tmp_path):
    from lsim.environment import _columns_python, load_dem_csv
    p = _grid_csv(tmp_path / "dem.csv", 25, 17, 20.0, lambda x, y: math.sin(x) + y / 7.0)
    fast = load_dem_csv(p)
    xs, ys, zs = _columns_python(p)
    assert len(zs) == fast.nx * fast.ny
    # zs est en double précision, la grille stocke en flottant simple : arrondi attendu.
    assert list(fast.z) == pytest.approx(list(zs), rel=1e-6, abs=1e-5)


def test_dem_unsorted_rows_give_same_grid(tmp_path):
    import random
    rows = ["x_m,y_m,z_m"]
    cells = [(ix * 10.0, iy * 10.0, float(ix * 3 + iy)) for ix in range(12) for iy in range(9)]
    ordered = list(cells)
    random.Random(5).shuffle(cells)
    rows += [f"{x},{y},{z}" for x, y, z in cells]
    shuffled = tmp_path / "shuffled.csv"
    shuffled.write_text("\n".join(rows) + "\n", encoding="utf-8")
    ref = tmp_path / "ref.csv"
    ref.write_text("x_m,y_m,z_m\n" + "\n".join(f"{x},{y},{z}" for x, y, z in ordered) + "\n",
                   encoding="utf-8")
    a = load_dem_csv(shuffled)
    b = load_dem_csv(ref)
    assert (a.nx, a.ny) == (b.nx, b.ny)
    assert list(a.z) == list(b.z)


def test_dem_duplicate_point_is_refused(tmp_path):
    p = tmp_path / "dup.csv"
    p.write_text("x_m,y_m,z_m\n0,0,1\n0,0,2\n10,0,1\n0,10,1\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_dem_csv(p)


def test_dem_bad_number_reports_line(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("x_m,y_m,z_m\n0,0,1\n10,0,abc\n0,10,1\n10,10,1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="ligne"):
        load_dem_csv(p)
