"""Parité S0 : planification native des descentes = version Python (oracle), à l'instant près."""

import copy
import random

import pytest

from lsim.downlink_plan import plan_native
from lsim.scenario import Scenario, ScenarioModel
from lsim.trace_events import (ProtocolOptions, _downlink_jobs, _events, _schedule_gateway,
                               device_radios)
from lsim.simulator import simulate_uplinks_trace


def _python_plan(records, radios, options):
    jobs = _downlink_jobs(records, radios, options, [False] * len(records), None)
    starts, busy = _schedule_gateway(jobs)
    events = _events(records, radios, jobs, starts, [False] * len(records), None)
    return events, tuple(busy)


def _run(scenario, options):
    devices, _g, _i = scenario.deploy()
    radios = device_radios(scenario)
    result = simulate_uplinks_trace(devices, scenario.gateway(), scenario.propagation(),
                                    scenario.environment, gateway_busy=())
    records = result.records
    native = plan_native(records, radios, options)
    python = _python_plan(records, radios, options)
    return native, python, len(records)


def _random_scenario(rng):
    raw = {
        "schema_version": 1, "name": "parity", "seed": rng.randrange(1000),
        "gateway": {"x_m": 0, "y_m": 0, "antenna_gain_dbi": rng.choice([0.0, 2.15])},
        "propagation": {"frequency_hz": 868100000, "exponent": rng.choice([2.5, 2.7, 3.2])},
        "groups": [],
    }
    for g in range(rng.randint(1, 3)):
        raw["groups"].append({
            "name": f"g{g}", "count": rng.randint(1, 12),
            "placement": {"type": "disk", "radius_m": rng.choice([300, 900, 2500])},
            "spreading_factor": rng.randint(7, 12), "payload_bytes": rng.randint(1, 40),
            "tx_power_dbm": rng.choice([8.0, 14.0]),
            "period_s": rng.choice([60, 300, 600]), "messages": rng.randint(1, 12),
            "start_spread_s": rng.choice([0, 60, 600]),
        })
    return Scenario(ScenarioModel.model_validate(raw))


def _random_options(rng):
    return ProtocolOptions(
        confirmed_uplinks=rng.random() < 0.5,
        downlink_every=rng.choice([0, 0, 1, 2, 3]),
        downlink_payload_bytes=rng.randint(0, 40),
        gateway_tx_power_dbm=rng.choice([14.0, 27.0]),
        device_antenna_gain_dbi=rng.choice([0.0, 2.0]),
        device_rx_offset_db=rng.choice([0.0, 3.0, -2.0]),
    )


@pytest.mark.parametrize("seed", range(60))
def test_native_plan_equals_python_oracle_on_random_scenarios(seed):
    rng = random.Random(seed)
    scenario = _random_scenario(rng)
    options = _random_options(rng)
    (nev, nbusy), (pev, pbusy), n = _run(scenario, options)
    assert nbusy == pbusy, f"occupation passerelle différente (seed {seed})"
    assert nev == pev, f"événements différents (seed {seed}, {n} émissions)"


def test_native_plan_on_examples_matches_oracle():
    import glob
    from lsim.scenario import load_scenario
    for path in sorted(glob.glob("examples/*.yaml")):
        scenario = load_scenario(path)
        for options in (ProtocolOptions(), ProtocolOptions(confirmed_uplinks=True, downlink_every=2)):
            (nev, nbusy), (pev, pbusy), _ = _run(scenario, options)
            assert nbusy == pbusy, path
            assert nev == pev, path


def test_native_plan_rejects_invalid_options():
    scenario = _random_scenario(random.Random(1))
    devices, _g, _i = scenario.deploy()
    radios = device_radios(scenario)
    result = simulate_uplinks_trace(devices, scenario.gateway(), scenario.propagation(),
                                    scenario.environment, gateway_busy=())
    with pytest.raises(ValueError):
        plan_native(result.records, radios, ProtocolOptions(downlink_payload_bytes=243))


@pytest.mark.parametrize("seed", range(10))
def test_native_plan_equals_oracle_when_downlinks_are_lost(seed):
    # Décalage de récepteur énorme : aucune descente n'atteint le dispositif (branche sensibilité).
    rng = random.Random(500 + seed)
    scenario = _random_scenario(rng)
    options = ProtocolOptions(confirmed_uplinks=True, downlink_every=1, downlink_payload_bytes=10,
                              device_rx_offset_db=200.0)
    (nev, nbusy), (pev, pbusy), _ = _run(scenario, options)
    assert nbusy == pbusy
    assert nev == pev
    replies = [e for e in nev if e.kind in ("ack", "downlink")]
    assert replies, "scénario sans réponse : test non significatif"
    assert all(e.outcome == "lost_sensitivity" for e in replies)


def _dense_scenario(seed):
    rng = random.Random(2000 + seed)
    raw = {
        "schema_version": 1, "name": "busy", "seed": seed,
        "gateway": {"x_m": 0, "y_m": 0, "antenna_gain_dbi": 2.15},
        "propagation": {"frequency_hz": 868100000, "exponent": 2.7},
        "groups": [{
            "name": "d", "count": rng.randint(10, 40),
            "placement": {"type": "disk", "radius_m": rng.choice([400, 1500])},
            "spreading_factor": rng.choice([7, 9]), "payload_bytes": rng.randint(5, 40),
            "tx_power_dbm": rng.choice([8.0, 14.0]), "period_s": rng.choice([5, 10, 30]),
            "messages": rng.randint(10, 30), "start_spread_s": rng.choice([0, 5]),
        }],
    }
    scenario = Scenario(ScenarioModel.model_validate(raw))
    options = ProtocolOptions(confirmed_uplinks=True, downlink_every=rng.choice([1, 2]),
                              downlink_payload_bytes=rng.choice([40, 242]),
                              gateway_tx_power_dbm=27.0, device_rx_offset_db=rng.choice([0.0, 3.0]))
    return scenario, options


# Scénarios denses : 11 et 38 n'atteignaient pas le point fixe de la version Python (S0).
@pytest.mark.parametrize("seed", range(40))
def test_causal_trace_equals_python_fixed_point_when_it_converges(seed):
    from lsim.trace_events import _build_trace_python, build_trace
    scenario, options = _dense_scenario(seed)
    causal = build_trace(scenario, options)
    devices, _g, _i = scenario.deploy()
    try:
        fixed = _build_trace_python(devices, device_radios(scenario), scenario.gateway(),
                                    scenario.propagation(), scenario.environment, (), options, None)
    except RuntimeError:
        return  # pas de point fixe : seule la trace causale existe (cas 11 et 38)
    assert causal.records == fixed.records
    assert causal.gateway_tx == fixed.gateway_tx
    assert causal.events == fixed.events
    assert causal.per_device == fixed.per_device
    assert causal.totals == fixed.totals


@pytest.mark.parametrize("seed", [11, 38])
def test_causal_trace_resolves_scenarios_without_fixed_point(seed):
    from lsim.trace_events import build_trace
    scenario, options = _dense_scenario(seed)
    run = build_trace(scenario, options)
    radios = device_radios(scenario)
    nev, nbusy = plan_native(run.records, radios, options)
    pev, pbusy = _python_plan(run.records, radios, options)
    assert nbusy == pbusy == run.gateway_tx
    assert nev == pev
    assert any(e.kind == "downlink" for e in nev), "scénario sans descente : test non significatif"
