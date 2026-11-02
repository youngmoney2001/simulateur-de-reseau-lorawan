"""Périmètre RF : ce que chaque chemin expose réellement (D3.2, RF-YAML / MULTI-V4 / M3 / GEO-RF).

Ces tests figent les limites décrites dans `docs/RF_MODEL.md` §7 à §9. Ils ne demandent aucune
fonctionnalité nouvelle : ils interdisent qu'une capacité RF apparaisse ou disparaisse par
inadvertance sur un chemin qui ne la documente pas.
"""

import inspect
from pathlib import Path

import pytest
from pydantic import ValidationError

from lsim.export import run_scenario
from lsim.geo import to_geojson
from lsim.scenario import ScenarioModel, load_scenario
from lsim.simulator import (
    simulate_multi_downlinks,
    simulate_uplinks,
    simulate_uplinks_multi,
    simulate_uplinks_trace,
)

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "quartier_sf9.yaml"
DOUALA = (4.0511, 9.7679)


def _raw():
    return {
        "schema_version": 1, "name": "perimetre-rf", "seed": 1,
        "gateway": {"x_m": 0, "y_m": 0},
        "propagation": {"frequency_hz": 868_100_000, "reference_distance_m": 1.0, "exponent": 2.7},
        "groups": [{
            "name": "d", "count": 2,
            "placement": {"type": "disk", "radius_m": 500},
            "spreading_factor": 9, "payload_bytes": 10, "tx_power_dbm": 14.0,
            "period_s": 10, "messages": 2,
        }],
    }


def test_scenario_refuses_an_rf_key_at_root():
    raw = _raw()
    raw["rf"] = {"device_antenna_gain_dbi": 3.0}
    with pytest.raises(ValidationError):
        ScenarioModel.model_validate(raw)


def test_scenario_refuses_an_rf_key_inside_a_group():
    raw = _raw()
    raw["groups"][0]["rf"] = {"antenna_gain_dbi": 3.0}
    with pytest.raises(ValidationError):
        ScenarioModel.model_validate(raw)


def test_uplink_paths_without_frontend_stay_without_one():
    # Ces chemins n'ont aucun paramètre de frontal : ni `device_rf`, ni `gateway_rf`.
    for fonction in (simulate_uplinks, simulate_uplinks_multi):
        params = inspect.signature(fonction).parameters
        assert not [nom for nom in params if "rf" in nom.lower()], fonction.__name__


def test_trace_and_multi_downlink_paths_accept_both_frontends():
    for fonction in (simulate_uplinks_trace, simulate_multi_downlinks):
        params = inspect.signature(fonction).parameters
        assert "device_rf" in params and "gateway_rf" in params, fonction.__name__


def test_geojson_carries_no_radio_frontend_field():
    scenario = load_scenario(EXAMPLE)
    doc = to_geojson(run_scenario(scenario), scenario, *DOUALA)
    assert set(doc["properties"]) == {
        "environment", "origin", "pdr", "scenario_name", "scenario_sha256",
        "total_received", "total_sent",
    }
    cles = {cle for entite in doc["features"] for cle in entite["properties"]}
    assert not cles & {"gain", "eirp", "cable", "cable_loss_db", "rf", "frontend",
                       "antenna_gain_dbi"}
