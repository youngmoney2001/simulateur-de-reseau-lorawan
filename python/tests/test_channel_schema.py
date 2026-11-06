"""Étape 1 ChannelMask : schéma `mac:` avec deux vues séparées (terminal et serveur).

Les champs sont validés, mais refusés explicitement par le moteur tant que l'étape 3 n'est pas
faite. Sans ces champs, la sérialisation (et donc le hash des scénarios) reste inchangée.
"""

import pytest
import yaml
from pydantic import ValidationError

from lsim.scenario import ChannelDefModel, MacModel, ScenarioModel


BASE = """schema_version: 1
name: canaux
seed: 1
gateway: {x_m: 0, y_m: 0, antenna_gain_dbi: 2.15}
groups:
  - name: g
    count: 4
    placement: {type: disk, radius_m: 3000}
    spreading_factor: 9
    payload_bytes: 20
    tx_power_dbm: 14
    period_s: 900
    messages: 5
    start_spread_s: 900
    region: EU868
"""


def _scenario_dict(mac: dict) -> dict:
    """Scénario de base (YAML du bloc de test) avec un bloc `mac:` fourni en dictionnaire."""
    data = yaml.safe_load(BASE)
    data["mac"] = mac
    return data


def test_channel_def_range_and_order():
    assert ChannelDefModel(index=0).dr_max == 7
    with pytest.raises(ValidationError):
        ChannelDefModel(index=80)
    with pytest.raises(ValidationError):
        ChannelDefModel(index=3, dr_min=5, dr_max=2)
    with pytest.raises(ValidationError):
        ChannelDefModel(index=3, dr_max=8)


def test_channel_fields_default_to_absent_in_dump():
    dumped = MacModel(link_adr=True).model_dump(mode="json")
    assert dumped["device_channels"] is None
    assert dumped["server_channel_plan"] is None


def test_channel_fields_are_refused_by_the_engine_until_step_3():
    with pytest.raises(ValidationError, match="étape 3"):
        ScenarioModel.model_validate(_scenario_dict({
            "link_adr": True,
            "device_channels": [{"index": 0}],
        }))
    with pytest.raises(ValidationError, match="étape 3"):
        ScenarioModel.model_validate(_scenario_dict({
            "server_channel_plan": [0, 1, 2],
        }))


def test_unknown_channel_keys_are_refused():
    with pytest.raises(ValidationError):
        ChannelDefModel.model_validate({"index": 0, "frequency_hz": 868100000})
