"""Compilation d'une topologie de session en scénario (`lsim.study_compile`), sans serveur."""

import pytest

from lsim.channel_mask import sub_band_channels
from lsim.plan import get_plan
from lsim.scenario import ScenarioModel
from lsim.study_cli import GatewayConfig, LoraIf, MeshIf
from lsim.study_compile import CompileError, compile_session
from lsim.study_contract import Node, SensorSettings


def node(id_, kind, x=0.0, y=0.0, sensor=None):
    return Node(id=id_, kind=kind, name=id_, x_m=x, y_m=y, sensor=sensor)


def cfg(region=None, sub_band=None, shutdown=False, mesh=None, mesh_shutdown=False):
    c = GatewayConfig(hostname="gw")
    c.lora = LoraIf(region=region, sub_band=sub_band, shutdown=shutdown)
    c.mesh = MeshIf(shutdown=mesh_shutdown, **(mesh or {}))
    return c


def configs(**by_node):
    return dict(by_node)


SENSOR = node("capteur-1", "sensor", x=500)


def test_a_border_and_a_sensor_compile_to_a_valid_scenario():
    out = compile_session([node("frontiere", "border"), SENSOR],
                          configs(frontiere=cfg("EU868")), seed=3)
    model = ScenarioModel.model_validate(out.body["scenario"])
    assert model.seed == 3
    assert [g.name for g in model.gateways] == ["frontiere"]
    assert model.mesh is None
    group = model.groups[0]
    assert group.name == "capteur-1" and group.region == "EU868"
    assert group.channel_freq_hz == get_plan("EU868").uplink_channels_hz()[0]
    assert out.links == [{"node_id": "frontiere", "gateway": "frontiere"}]


def test_sensor_settings_become_the_group_parameters():
    settings = SensorSettings(spreading_factor=9, payload_bytes=20, tx_power_dbm=8.0,
                              period_s=300.0, messages=4, start_spread_s=60.0)
    out = compile_session([node("frontiere", "border"), node("c", "sensor", sensor=settings)],
                          configs(frontiere=cfg("EU868")), seed=0)
    group = ScenarioModel.model_validate(out.body["scenario"]).groups[0]
    assert (group.spreading_factor, group.payload_bytes, group.tx_power_dbm) == (9, 20, 8.0)
    assert (group.period_s, group.messages, group.start_spread_s) == (300.0, 4, 60.0)


def test_a_sensor_without_settings_takes_the_scenario_defaults():
    out = compile_session([node("frontiere", "border"), SENSOR],
                          configs(frontiere=cfg("EU868")), seed=0)
    group = ScenarioModel.model_validate(out.body["scenario"]).groups[0]
    assert (group.spreading_factor, group.payload_bytes, group.period_s) == (7, 10, 600.0)


def test_relays_compile_to_a_mesh_around_the_border():
    nodes = [node("frontiere", "border"), node("relais-1", "relay", x=1200), SENSOR]
    out = compile_session(nodes, configs(
        frontiere=cfg("EU868", mesh={"bandwidth_khz": "812"}),
        **{"relais-1": cfg("EU868", mesh={"max_hops": 2})}), seed=0)
    model = ScenarioModel.model_validate(out.body["scenario"])
    assert model.mesh.border == "frontiere"
    assert model.mesh.bandwidth_khz == 812
    assert model.mesh.max_hops == 2           # la plus petite valeur réglée
    assert model.mesh.spreading_factor == 9   # défaut du moteur
    assert {g.name: g.mesh for g in model.gateways} == {"frontiere": True, "relais-1": True}
    assert all(g.profile == "rak5148" for g in model.gateways)


@pytest.mark.parametrize("nodes, configuration, message", [
    ([SENSOR], {}, "aucune passerelle"),
    ([node("frontiere", "border")], {}, "aucun capteur"),
    ([node("relais-1", "relay"), SENSOR], {"relais-1": cfg("EU868")}, "exactement une frontière"),
    ([node("f", "border"), node("g", "border"), node("relais-1", "relay"), SENSOR],
     {"f": cfg("EU868"), "g": cfg("EU868"), "relais-1": cfg("EU868")}, "exactement une frontière"),
    ([node("frontiere", "border"), node("relais-1", "relay"), SENSOR],
     {"frontiere": cfg("EU868", mesh_shutdown=True), "relais-1": cfg("EU868")},
     "interface mesh arrêtée"),
    ([node("frontiere", "border"), SENSOR], {"frontiere": cfg("EU868", shutdown=True)},
     "toutes les passerelles sont arrêtées"),
    ([node("frontiere", "border"), SENSOR],
     {"frontiere": cfg("EU868", mesh={"mode": "relay"})}, "ne correspond pas au rôle border"),
    ([node("frontiere", "border"), node("f2", "border", x=50), SENSOR],
     {"frontiere": cfg("EU868"), "f2": cfg("US915", sub_band=2)}, "plans régionaux différents"),
    ([node("frontiere", "border"), node("c", "sensor", sensor=SensorSettings(region="US915"))],
     {"frontiere": cfg("EU868")}, "plan US915"),
])
def test_inconsistent_sessions_are_refused_with_a_reason(nodes, configuration, message):
    with pytest.raises(CompileError) as exc:
        compile_session(nodes, configuration, seed=0)
    assert message in exc.value.message


def test_mesh_settings_must_agree_between_border_and_relays():
    nodes = [node("frontiere", "border"), node("relais-1", "relay"), SENSOR]
    with pytest.raises(CompileError) as exc:
        compile_session(nodes, {"frontiere": cfg("EU868", mesh={"spreading_factor": 9}),
                                "relais-1": cfg("EU868", mesh={"spreading_factor": 10})}, seed=0)
    assert "SF mesh" in exc.value.message


def test_a_stopped_access_radio_leaves_the_run_and_a_relay_without_mesh_stays_an_access_gateway():
    nodes = [node("frontiere", "border"), node("relais-1", "relay", x=1200),
             node("ip-ouest", "border", x=-2500), SENSOR]
    out = compile_session(nodes, configs(
        frontiere=cfg("EU868"),
        **{"relais-1": cfg("EU868", mesh_shutdown=True), "ip-ouest": cfg("EU868", shutdown=True)},
    ), seed=0)
    model = ScenarioModel.model_validate(out.body["scenario"])
    assert [g.name for g in model.gateways] == ["frontiere", "relais-1"]
    assert model.mesh is None
    assert [link["node_id"] for link in out.links] == ["frontiere", "relais-1"]


def test_us915_defaults_the_sub_band_and_picks_a_channel_inside_it():
    out = compile_session([node("frontiere", "border"), SENSOR],
                          configs(frontiere=cfg("US915")), seed=0)
    model = ScenarioModel.model_validate(out.body["scenario"])
    group = model.groups[0]
    assert group.sub_band == 1
    index = get_plan("US915").uplink_channels_hz().index(group.channel_freq_hz)
    assert index in sub_band_channels(1)
    assert any("sous-bande non réglée, 1 appliquée" in note for note in out.notes)


def test_unset_region_defaults_to_eu868_with_a_note():
    out = compile_session([node("frontiere", "border"), SENSOR], configs(frontiere=cfg()), seed=0)
    assert ScenarioModel.model_validate(out.body["scenario"]).groups[0].region == "EU868"
    assert any("EU868 appliqué" in note for note in out.notes)


def test_the_unmodelled_settings_are_always_reported():
    out = compile_session([node("frontiere", "border"), SENSOR],
                          configs(frontiere=cfg("EU868")), seed=0)
    assert any("non modélisés" in note and "Ethernet" in note for note in out.notes)
