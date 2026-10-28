"""Métriques de charge passerelle et temps d'antenne, calculées par le cœur natif."""

from lsim.simulator import EndDevice, Gateway, Propagation, simulate_uplinks


def test_airtime_union_peak_and_utilization():
    devs = [EndDevice(x_m=10.0), EndDevice(x_m=10.0),
            EndDevice(x_m=10.0, start_offset_ns=1_000_000_000)]
    res = simulate_uplinks(devs, Gateway(), Propagation())
    a = res.per_device[0].airtime_ns
    assert a > 0
    assert res.per_device[1].airtime_ns == a
    assert res.totals.airtime_ns == 3 * a
    assert res.gateway.busy_ns == 2 * a
    assert res.gateway.observation_ns == 1_000_000_000 + a
    assert res.gateway.peak_concurrent == 2
    assert res.gateway.utilization == (2 * a) / (1_000_000_000 + a)


def test_no_traffic_gives_zero_load():
    res = simulate_uplinks([], Gateway(), Propagation())
    assert res.gateway.busy_ns == 0
    assert res.gateway.peak_concurrent == 0
    assert res.gateway.utilization == 0.0
    assert res.totals.airtime_ns == 0


def test_parquet_export_contains_airtime_and_gateway_load(tmp_path):
    pq = __import__("pytest").importorskip("pyarrow.parquet")
    from pathlib import Path

    from lsim.export import run_scenario, write_parquet
    from lsim.scenario import load_scenario

    root = Path(__file__).resolve().parents[2]
    run = run_scenario(load_scenario(root / "examples" / "quartier_sf9.yaml"))
    out = tmp_path / "run.parquet"
    write_parquet(run, out)
    table = pq.read_table(out)
    assert "airtime_ns" in table.column_names
    assert sum(table.column("airtime_ns").to_pylist()) == run.totals.airtime_ns
    meta = table.schema.metadata
    assert int(meta[b"lsim.gateway_peak_concurrent"]) == run.gateway.peak_concurrent
    assert float(meta[b"lsim.gateway_utilization"]) == run.gateway.utilization
