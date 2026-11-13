"""Profil énergie déclaré dans le scénario YAML (energy.profile) et priorité sur la CLI."""

from pathlib import Path
from typing import get_args

import pyarrow.parquet as pq
import pytest
from pydantic import ValidationError

from lsim.__main__ import main
from lsim.energy_report import ENERGY_PROFILES
from lsim.scenario import EnergyModel, ScenarioModel, load_scenario

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "quartier_sf9.yaml"
EXAMPLE_SHA256 = "07a43b99824497c7"  # hash historique : inchangé sans bloc energy


def _with_energy(profile: str, tmp_path: Path) -> Path:
    text = EXAMPLE.read_text(encoding="utf-8")
    path = tmp_path / "scenario_energy.yaml"
    path.write_text(f"energy:\n  profile: {profile}\n" + text, encoding="utf-8")
    return path


def test_example_hash_unchanged_without_energy_block():
    assert load_scenario(EXAMPLE).sha256.startswith(EXAMPLE_SHA256)
    assert load_scenario(EXAMPLE).energy_profile is None


def test_energy_block_changes_hash_and_is_exposed(tmp_path):
    base = load_scenario(EXAMPLE)
    with_profile = load_scenario(_with_energy("sx1262-stm32l072", tmp_path))
    assert with_profile.sha256 != base.sha256
    assert with_profile.energy_profile == "sx1262-stm32l072"


def _litteral_profil() -> tuple:
    """Le Literal des profils du catalogue, `Optional` déballé.

    `profile` est devenu optionnel : un scénario peut déclarer un relevé à la place. Le
    garde-fou doit donc ôter `NoneType` avant de comparer, sinon il cesse de protéger
    contre une divergence entre le YAML et le catalogue — et c'est précisément ce qu'il
    vérifie depuis le début.
    """
    args = get_args(EnergyModel.model_fields["profile"].annotation)
    return next((get_args(a) for a in args if get_args(a)), args)


def test_profile_names_match_energy_report():
    assert set(_litteral_profil()) == set(ENERGY_PROFILES)


def test_energy_requires_either_a_catalogue_profile_or_a_measurement():
    """Ni l'un ni l'autre, ou les deux : refusé. Un rapport ne doit pas avoir à choisir."""
    releve = {"supply_v": 3.3, "rx_ma_125khz": 17.0, "rx_ma_250khz": 17.0,
              "rx_ma_500khz": 17.0, "sleep_ua": 2.0, "provenance": "relevé banc",
              "tx_points": [{"dbm": 14.0, "ma": 92.0}]}
    with pytest.raises(ValidationError):
        EnergyModel()
    with pytest.raises(ValidationError):
        EnergyModel(profile="rak4631", measured=releve)
    EnergyModel(profile="rak4631")
    EnergyModel(measured=releve)


def test_measured_energy_requires_a_provenance():
    """Un relevé sans provenance serait présenté comme une donnée du moteur."""
    base = {"supply_v": 3.3, "rx_ma_125khz": 17.0, "rx_ma_250khz": 17.0,
            "rx_ma_500khz": 17.0, "sleep_ua": 2.0,
            "tx_points": [{"dbm": 14.0, "ma": 92.0}]}
    EnergyModel(measured=dict(base, provenance="relevé banc"))
    for mauvaise in ("", "   "):
        with pytest.raises(ValidationError):
            EnergyModel(measured=dict(base, provenance=mauvaise))


def test_unknown_profile_is_rejected():
    with pytest.raises(ValidationError):
        EnergyModel(profile="foo")
    with pytest.raises(ValidationError):
        EnergyModel(profile="rak4631", extra=1)


def test_yaml_profile_used_when_cli_flag_absent(tmp_path):
    scenario = _with_energy("sx1262-stm32l072", tmp_path)
    out = tmp_path / "out.parquet"
    assert main(["run", str(scenario), "-o", str(out)]) == 0
    meta = pq.read_metadata(out).metadata
    assert meta[b"lsim.energy_profile"] == b"sx1262-stm32l072"


def test_cli_flag_overrides_yaml_profile(tmp_path):
    scenario = _with_energy("sx1262-stm32l072", tmp_path)
    out = tmp_path / "out.parquet"
    assert main(["run", str(scenario), "-o", str(out), "--energy-profile", "rak4631"]) == 0
    assert pq.read_metadata(out).metadata[b"lsim.energy_profile"] == b"rak4631"


def test_run_without_any_profile_has_no_energy_columns(tmp_path):
    out = tmp_path / "out.parquet"
    assert main(["run", str(EXAMPLE), "-o", str(out)]) == 0
    assert b"lsim.energy_profile" not in (pq.read_metadata(out).metadata or {})
