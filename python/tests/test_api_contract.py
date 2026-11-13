"""Contrat d'API v1 : schémas publiés à jour, pas de lecture de fichier serveur, bornes."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from lsim.api_contract import (
    ApiScenario, MAX_PAGE_SIZE, MAX_TRACE_EVENTS_PER_RUN, RunCreate, TraceEvent,
    ENERGY_PROFILES, list_energy_profiles, list_regions, schemas,
    list_gateway_profiles,
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


def test_energy_profile_list_comes_from_the_engine_not_from_the_interface():
    """Les libellés exposés sont ceux du module d'énergie : les recopier les ferait dériver.

    Attention aux deux `ENERGY_PROFILES` : celui du contrat est le tuple des noms admis par
    l'API, celui du module d'énergie est la table nom -> identifiant. C'est la table qui
    donne les libellés, et c'est elle que l'interface ne doit pas recopier.
    """
    from lsim.energy_report import ENERGY_PROFILES as TABLE
    from lsim.energy_report import PROFILE_NAMES

    listed = list_energy_profiles()
    names = [p.name for p in listed.profiles]
    assert set(names) == set(ENERGY_PROFILES) == set(TABLE), (names, ENERGY_PROFILES)
    for p in listed.profiles:
        assert p.label == PROFILE_NAMES[TABLE[p.name]]
        json.dumps(p.model_dump())


def test_gateway_profile_list_comes_from_the_catalog_not_from_the_interface():
    """Le catalogue exposé est celui des fiches constructeur, avec ce que chacune change.

    Deux pièges : `CATALOG` est un **tuple** (pas un dict), et le décalage de sensibilité
    n'existe que si la fiche publie son point de mesure. Trois des quatre modèles ne
    décalent rien — le dire ici évite que l'interface ne vende un choix qui n'en est pas un.
    """
    from lsim.gateway_profiles import (CATALOG, can_relay, can_simulate_radio,
                                       rx_sensitivity_offset_db, software_status)

    listed = list_gateway_profiles()
    assert [p.name for p in listed.profiles] == [p.key for p in CATALOG]
    for p in listed.profiles:
        src = next(c for c in CATALOG if c.key == p.name)
        assert p.model == src.model                    # libellé : celui de la fiche
        assert p.sensitivity_offset_db == rx_sensitivity_offset_db(src)
        assert p.can_relay is can_relay(src)
        assert p.can_simulate_radio is can_simulate_radio(src)
        assert list(p.access_bands) == list(src.access_bands)
        assert p.software_status == software_status(src)
        json.dumps(p.model_dump())
    # Le décalage n'est réel que si la fiche publie son point de mesure : c'est la seule
    # différence entre un modèle qui change le run et un modèle qui le calcule à l'identique.
    decales = [p.name for p in listed.profiles if p.sensitivity_published]
    assert decales, "aucun modèle ne publie son point de mesure : le réglage ne servirait à rien"
    for p in listed.profiles:
        assert (p.sensitivity_offset_db != 0.0) == (p.name in decales)


def test_schema_generation_from_the_command_line_is_reproducible(tmp_path):
    """`python -m lsim.api_contract DIR` reproduit octet pour octet les schémas publiés, deux fois."""
    env = {**os.environ, "PYTHONPATH": str(ROOT / "python")}
    outs = []
    for name in ("first", "second"):
        out = tmp_path / name
        subprocess.run([sys.executable, "-m", "lsim.api_contract", str(out)], check=True,
                       env=env, cwd=ROOT, capture_output=True)
        outs.append(out)
    published = sorted(p.name for p in SCHEMA_DIR.glob("*.schema.json"))
    assert sorted(p.name for p in outs[0].glob("*.json")) == published
    for name in published:
        generated = (outs[0] / name).read_bytes()
        assert generated == (outs[1] / name).read_bytes(), name
        assert generated == (SCHEMA_DIR / name).read_bytes(), (
            f"{name} : relancer python -m lsim.api_contract schemas/api/v1")


def _summary(**load):
    base = {"run_id": "run-abcdefgh", "scenario_sha256": "0" * 64, "seed": 1,
            "totals": {"sent": 10, "received": 8, "lost_sensitivity": 1, "lost_collision": 1,
                       "airtime_ns": 1000, "lost_gateway_busy": 0}}
    base.update(load)
    return base


GW = {"busy_ns": 0, "peak_concurrent": 0, "observation_ns": 1, "utilization": 0.0}
GWS = [{"name": "a", "received": 8, "lost_sensitivity": 1, "lost_collision": 1,
        "lost_gateway_busy": 0, "audible_frames": 10, "busy_ns": 0, "peak_concurrent": 0,
        "observation_ns": 1}]


def test_run_summary_accepts_exactly_one_load_shape():
    from lsim.api_contract import RunSummary
    RunSummary.model_validate(_summary(gateway=GW))       # mono-passerelle
    RunSummary.model_validate(_summary(gateways=GWS))     # multi-passerelles
    with pytest.raises(ValidationError):
        RunSummary.model_validate(_summary())             # aucun des deux
    with pytest.raises(ValidationError):
        RunSummary.model_validate(_summary(gateway=GW, gateways=GWS))  # les deux


def test_terrain_id_pattern_refuses_paths():
    from lsim.api_contract import RunCreate
    for bad in ("../x", "a/b", "A", "", "x" * 65):
        with pytest.raises(ValidationError):
            RunCreate(scenario=BASE, terrain_id=bad)
    RunCreate(scenario=BASE, terrain_id="quartier-1_a")


def test_every_public_model_is_published():
    """Aucun modèle public ne doit rester hors du contrat.

    Un schéma qu'on oublie de publier n'échoue nulle part : le client qui le consomme
    le reconstruit à la main, et la première divergence passe inaperçue. Ce test rend
    l'oubli impossible — c'est lui qui répond à « était-ce volontaire ? ».
    """
    import inspect

    from pydantic import BaseModel

    from lsim import api_contract, study_contract

    for module, publies in ((api_contract, api_contract._MODELS),
                            (study_contract, study_contract.MODELS)):
        assert set(schemas()) >= set(publies), f"{module.__name__} non publié dans v1"
        definis = {
            obj
            for _, obj in inspect.getmembers(module, inspect.isclass)
            if issubclass(obj, BaseModel)
            and obj.__module__ == module.__name__
            and obj is not BaseModel
            and not obj.__name__.startswith("_")   # les classes de base ne sont pas un contrat
        }
        assert definis, f"aucun modèle trouvé dans {module.__name__}"
        manquants = sorted(o.__name__ for o in definis - set(publies.values()))
        assert not manquants, (
            f"{module.__name__} : modèles non publiés : {', '.join(manquants)}")
