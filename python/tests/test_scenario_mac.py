"""Bloc `mac:` du scénario : validation, empreinte et compatibilité (phase 1, sans effet moteur encore)."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from lsim.scenario import MacModel, load_scenario

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "mesh_relais_quartier.yaml"


def test_existing_scenario_has_no_mac_block_and_keeps_its_hash():
    sc = load_scenario(EXAMPLE)
    assert sc.model.mac is None
    assert sc.model.model_dump(mode="json")["mac"] is None


def test_mac_block_changes_hash_and_is_validated(tmp_path):
    text = EXAMPLE.read_text(encoding="utf-8")
    plain = tmp_path / "plain.yaml"
    plain.write_text(text, encoding="utf-8")
    with_mac = tmp_path / "mac.yaml"
    with_mac.write_text(text + "mac:\n  link_check_every: 5\n  device_status_every: 10\n", encoding="utf-8")
    a, b = load_scenario(plain), load_scenario(with_mac)
    assert a.sha256 != b.sha256
    assert b.model.mac.link_check_every == 5
    assert b.model.mac.device_status_every == 10


def test_mac_defaults_are_disabled():
    m = MacModel()
    assert m.link_check_every == 0 and m.device_status_every == 0


def test_mac_bounds_and_unknown_fields_are_refused():
    with pytest.raises(ValidationError):
        MacModel(link_check_every=1001)
    with pytest.raises(ValidationError):
        MacModel(link_check_every=-1)
    with pytest.raises(ValidationError):
        MacModel(unknown_field=1)
