"""Compilation d'une topologie de session en scénario (`lsim.study_compile`), sans serveur."""

import pytest
from pydantic import ValidationError

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
    assert all(g.profile == "rak5146-rak5148" for g in model.gateways)   # accès sous-GHz + mesh 2,4 GHz


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


def test_the_energy_note_names_the_run_material_and_the_devices_that_differ():
    """La note d'énergie décrit le run qu'on obtient, pas seulement le profil par défaut.

    Depuis qu'un capteur peut porter le sien, annoncer « profil rak4631 » sans plus de
    précision décrit un run qui n'est plus le sien : deux matériels dans une même session,
    et la note se tait sur celui qui fait exception. Un courant moyen se vérifie en
    sachant de quel matériel il vient.
    """
    def capteur(nid, modele):
        s = SensorSettings(spreading_factor=9, period_s=60)
        if modele:
            s = s.model_copy(update={"energy_profile": modele})
        return node(nid, "sensor", x=500, sensor=s)

    def note(*capteurs):
        out = compile_session([node("frontiere", "border"), *capteurs],
                              configs(frontiere=cfg("EU868")), seed=0)
        return next(n for n in out.notes if n.startswith("énergie"))

    # Aucun modèle propre : la note reste celle d'avant, à l'identique.
    seule = note(capteur("c1", None), capteur("c2", None))
    assert seule == ("énergie des capteurs : profil rak4631 (RAK4631 (nRF52840 + SX1262, "
                     "module)) — le courant moyen est celui de ce matériel")

    # Un capteur déroge : il est nommé, avec le libellé du moteur.
    deroge = note(capteur("c1", "sx1262-stm32l072"), capteur("c2", None))
    assert "matériel propre à c1 : sx1262-stm32l072 (SX1262 (datasheet) + STM32L072 (MCU))" in deroge

    # Répéter le profil du run n'est pas une dérogation : la note ne fait pas de doublon.
    repete = note(capteur("c1", "rak4631"), capteur("c2", "sx1262-stm32l072"))
    assert "c1" not in repete and "c2 : sx1262-stm32l072" in repete


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


def test_compiled_notes_state_software_reserve_and_radio_limit():
    """Notes de compilation : relais provisoire signalé ; sensibilité non prise en compte, dite explicitement."""
    nodes = [node("frontiere", "border"), node("relais-1", "relay", x=1200), SENSOR]
    out = compile_session(nodes, configs(
        frontiere=cfg("EU868", mesh={"bandwidth_khz": "812"}),
        **{"relais-1": cfg("EU868", mesh={"bandwidth_khz": "812"})}), seed=0)
    text = " | ".join(out.notes)
    assert "rak5146-rak5148" in text and "à valider" in text
    assert "sensibilité des récepteurs" in text and "decalage-uniforme-v1" in text and "non calibré" in text


def test_no_software_reserve_without_relay():
    out = compile_session([node("passerelle", "border"), SENSOR], configs(passerelle=cfg("EU868")), seed=0)
    assert not any("compatibilité logicielle" in n for n in out.notes)
    assert any("sensibilité des récepteurs" in n for n in out.notes)


def test_the_chosen_profile_reaches_the_scenario_and_the_default_does_not():
    """Le modèle posé descend jusqu'aux passerelles du scénario : c'est là qu'il décale le seuil.

    Sans modèle, le champ est **absent** du scénario, pas vide : un scénario écrit avant cette
    fonctionnalité doit garder son empreinte. Le relais, lui, garde la valeur historique — un
    réseau mesh exige une radio mesh documentée, et le scénario refuse un modèle qui ne l'a pas.
    """
    from lsim.study_compile import MESH_PROFILE

    gw = Node(id="frontiere", kind="border", name="frontiere", x_m=0, y_m=0,
              gateway_profile="rak7249")
    out = compile_session([gw, SENSOR], configs(frontiere=cfg("EU868")), seed=3)
    assert next(g["profile"] for g in out.body["scenario"]["gateways"]
                if g["name"] == "frontiere") == "rak7249"

    # Sans modèle : aucun `profile` émis.
    out_vierge = compile_session([node("frontiere", "border"), SENSOR],
                                 configs(frontiere=cfg("EU868")), seed=3)
    assert "profile" not in out_vierge.body["scenario"]["gateways"][0]

    # Le relais porte la valeur historique, faute de quoi le scénario le refuse.
    relais = node("relais-1", "relay", x=1200)
    out_mesh = compile_session([Node(id="frontiere", kind="border", name="frontiere",
                                     x_m=0, y_m=0, gateway_profile="rak7249"), relais, SENSOR],
                               configs(frontiere=cfg("EU868"), **{"relais-1": cfg("EU868")}),
                               seed=3)
    assert next(g["profile"] for g in out_mesh.body["scenario"]["gateways"]
                if g["name"] == "relais-1") == MESH_PROFILE


def test_an_unknown_gateway_profile_is_refused_at_the_source():
    """Un modèle hors catalogue ne doit pas atteindre le scénario : le contrat le refuse."""
    with pytest.raises(ValidationError) as err:
        Node(id="frontiere", kind="border", name="f", x_m=0, y_m=0,
             gateway_profile="invente")
    assert "gateway_profile" in str(err.value)
    # Et un capteur n'en porte jamais : le serveur le refuse, la compilation n'a pas à
    # choisir quoi en faire. Le modèle fautif est nommé — sans lui, l'apprenant voit un
    # refus sans savoir quelle valeur le cause.
    with pytest.raises(ValidationError) as capteur:
        Node(id="c1", kind="sensor", name="c", x_m=0, y_m=0, gateway_profile="rak7249")
    assert "rak7249" in str(capteur.value) and "pas une passerelle" in str(capteur.value)
