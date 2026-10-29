"""Contrat d'API v1 : schémas publiés à jour, pas de lecture de fichier serveur, bornes."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from lsim.api_contract import (
    ApiScenario, MAX_PAGE_SIZE, MAX_TRACE_EVENTS_PER_RUN, RunCreate, TraceEvent,
    list_regions, schemas,
)

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = ROOT / "schemas" / "api" / "v1"

BASE = {
    "schema_version": 1,
    "name": "test",
    "groups": [{"name": "g", "count": 2, "placement": {"type": "disk", "radius_m": 100}}],
}


def test_published_schemas_match_the_code():
    for name, schema in schemas().items():
        path = SCHEMA_DIR / f"{name}.schema.json"
        assert path.exists(), f"schéma absent : {path.name} (lancer python -m lsim.api_contract)"
        assert json.loads(path.read_text(encoding="utf-8")) == json.loads(json.dumps(schema)), (
            f"{path.name} désynchronisé du code (relancer python -m lsim.api_contract)")


def test_no_stray_schema_files():
    expected = {f"{name}.schema.json" for name in schemas()}
    assert {p.name for p in SCHEMA_DIR.glob("*.schema.json")} == expected


def test_scenario_with_terrain_path_is_refused():
    # Chemin relatif valide : la règle d'API doit tout de même le refuser.
    body = dict(BASE, environment={"terrain": {"type": "dem_csv", "path": "carte.csv"}})
    with pytest.raises(ValidationError) as err:
        ApiScenario.model_validate(body)
    assert "terrain" in str(err.value)


def test_plain_scenario_is_accepted():
    ApiScenario.model_validate(BASE)


def test_run_create_rejects_unknown_energy_profile():
    with pytest.raises(ValidationError):
        RunCreate.model_validate({"scenario": BASE, "energy_profile": "inconnu"})


def test_responses_forbid_unknown_fields():
    with pytest.raises(ValidationError):
        TraceEvent.model_validate({"seq": 0, "t_ns": 0, "kind": "uplink",
                                   "device_index": 0, "outcome": "ok", "session_key": "x"})


def test_trace_limits_are_documented_values():
    assert MAX_TRACE_EVENTS_PER_RUN == 200_000
    assert MAX_PAGE_SIZE == 500


def test_region_list_covers_every_plan_and_is_serialisable():
    regions = list_regions()
    names = [r.name for r in regions.regions]
    assert names == sorted(names) and "RU864" in names and "US915" in names
    for r in regions.regions:
        assert r.rx2_hz > 0 and r.max_payload_by_dr
        json.dumps(r.model_dump())
    us = next(r for r in regions.regions if r.name == "US915")
    assert us.sub_bands is True
