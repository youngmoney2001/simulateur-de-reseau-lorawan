"""Scénarios YAML : validation stricte, déploiement déterministe, export Parquet."""

from pathlib import Path

import pytest

from lsim.export import run_scenario, write_parquet
from lsim.scenario import MAX_DEVICES, load_scenario

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "quartier_sf9.yaml"

BASE = """
schema_version: 1
name: test
seed: 7
groups:
  - name: g
    count: 20
    placement: {type: disk, radius_m: 500}
    spreading_factor: 7
    period_s: 600
    messages: 2
    start_spread_s: 60
"""


def test_example_loads_and_runs():
    sc = load_scenario(EXAMPLE)
    run = run_scenario(sc)
    assert len(run.rows) == 500
    assert run.totals.sent == 500 * 10
    assert run.totals.sent == run.totals.received + run.totals.lost_sensitivity + run.totals.lost_collision
    assert sum(r.sent for r in run.rows) == run.totals.sent


def test_same_file_same_result_and_hash():
    a = run_scenario(load_scenario(EXAMPLE))
    b = run_scenario(load_scenario(EXAMPLE))
    assert a.scenario_sha256 == b.scenario_sha256
    assert a.rows == b.rows and a.totals == b.totals


def test_seed_changes_deployment():
    a = load_scenario(BASE)
    b = load_scenario(BASE.replace("seed: 7", "seed: 8"))
    assert a.deploy()[0][0].x_m != b.deploy()[0][0].x_m
    assert a.sha256 != b.sha256


def test_disk_placement_within_radius():
    devices, _, _ = load_scenario(BASE).deploy()
    assert len(devices) == 20
    assert all((d.x_m ** 2 + d.y_m ** 2) ** 0.5 <= 500.0 + 1e-9 for d in devices)
    assert all(0 <= d.start_offset_ns < 60_000_000_000 for d in devices)


def test_unknown_field_refused():
    with pytest.raises(ValueError):
        load_scenario(BASE + "\nextra_field: 1\n")


def test_safe_yaml_refuses_python_objects():
    with pytest.raises(Exception):
        load_scenario("!!python/object/apply:os.system ['echo x']")


def test_device_limit_refused():
    text = BASE.replace("count: 20", f"count: {MAX_DEVICES + 1}")
    with pytest.raises(ValueError):
        load_scenario(text)


def test_transmission_limit_refused():
    text = BASE.replace("count: 20", "count: 10000").replace("messages: 2", "messages: 1000")
    with pytest.raises(ValueError):
        load_scenario(text)


def test_explicit_count_must_match_positions():
    text = """
schema_version: 1
name: x
groups:
  - name: g
    count: 3
    placement: {type: explicit, positions: [[0, 0], [1, 1]]}
"""
    with pytest.raises(ValueError):
        load_scenario(text)


def test_duplicate_group_names_refused():
    text = BASE + """  - name: g
    count: 1
    placement: {type: explicit, positions: [[5, 5]]}
"""
    with pytest.raises(ValueError):
        load_scenario(text)


def test_parquet_roundtrip_keeps_totals_and_hash(tmp_path):
    pq = pytest.importorskip("pyarrow.parquet")
    run = run_scenario(load_scenario(EXAMPLE))
    out = tmp_path / "res.parquet"
    write_parquet(run, out)
    table = pq.read_table(out)
    assert table.num_rows == 500
    meta = {k.decode(): v.decode() for k, v in table.schema.metadata.items()}
    assert meta["lsim.scenario_sha256"] == run.scenario_sha256
    assert int(meta["lsim.total_sent"]) == run.totals.sent
    assert int(meta["lsim.total_received"]) == run.totals.received
    assert sum(table.column("received").to_pylist()) == run.totals.received


def test_cli_run(tmp_path, capsys):
    pytest.importorskip("pyarrow")
    from lsim.__main__ import main

    out = tmp_path / "cli.parquet"
    assert main(["run", str(EXAMPLE), "-o", str(out)]) == 0
    assert out.is_file()
    assert "PDR" in capsys.readouterr().out


def test_cli_reports_validation_error(tmp_path, capsys):
    from lsim.__main__ import main

    bad = tmp_path / "bad.yaml"
    bad.write_text("schema_version: 2\nname: x\ngroups: []\n", encoding="utf-8")
    assert main(["run", str(bad), "-o", str(tmp_path / "x.parquet")]) == 2
    assert "erreur" in capsys.readouterr().err
