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


def test_the_environment_block_is_only_emitted_when_something_was_set():
    """Un scénario vierge n'émet aucun bloc : c'est ce qui garde son empreinte.

    Le shadowing n'appartient pas au bloc `environment` mais à `propagation`, et n'est émis
    que s'il est non nul — la clé absente, c'est le comportement d'avant.
    """
    from lsim.study_contract import EnvironmentSettings, Obstacle

    mur = Obstacle(x_min_m=4900, y_min_m=-300, x_max_m=5100, y_max_m=300,
                   height_m=12, attenuation_db=6)
    vierge = compile_session([node("frontiere", "border"), SENSOR],
                             configs(frontiere=cfg("EU868")), seed=3,
                             environment=EnvironmentSettings())
    assert "environment" not in vierge.body["scenario"]
    assert "propagation" not in vierge.body["scenario"]

    avec_mur = compile_session([node("frontiere", "border"), SENSOR],
                               configs(frontiere=cfg("EU868")), seed=3,
                               environment=EnvironmentSettings(obstacles=[mur]))
    assert avec_mur.body["scenario"]["environment"]["obstacles"][0] == {
        "x_min_m": 4900.0, "y_min_m": -300.0, "x_max_m": 5100.0, "y_max_m": 300.0,
        "height_m": 12.0, "attenuation_db": 6.0}
    # Le shadowing n'est pas encore réglé : `propagation` reste absent.
    assert "propagation" not in avec_mur.body["scenario"]

    avec_sigma = compile_session([node("frontiere", "border"), SENSOR],
                                 configs(frontiere=cfg("EU868")), seed=3,
                                 environment=EnvironmentSettings(shadowing_sigma_db=4.0))
    assert avec_sigma.body["scenario"]["propagation"] == {"shadowing_sigma_db": 4.0}
    # Un sigma non nul suffit à faire émettre le bloc, hauteurs comprises : le run ne serait
    # pas celui d'avant sinon.
    assert avec_sigma.body["scenario"]["environment"]["gateway_height_m"] == 15.0


def test_a_wall_made_of_a_material_carries_the_material_not_the_attenuation():
    """Matériau + épaisseur d'un côté, atténuation saisie de l'autre : jamais les deux."""
    from lsim.study_contract import EnvironmentSettings, Obstacle

    mur = Obstacle(x_min_m=0, y_min_m=0, x_max_m=10, y_max_m=10,
                   material="concrete", thickness_m=0.2)
    out = compile_session([node("frontiere", "border"), SENSOR],
                          configs(frontiere=cfg("EU868")), seed=3,
                          environment=EnvironmentSettings(obstacles=[mur]))
    o = out.body["scenario"]["environment"]["obstacles"][0]
    assert o["material"] == "concrete" and o["thickness_m"] == 0.2
    assert "attenuation_db" not in o


def test_the_environment_is_announced_in_the_notes():
    """Ce qui change le run est dit dans les notes, pas seulement dans le scénario."""
    from lsim.study_contract import EnvironmentSettings, Obstacle

    mur = Obstacle(x_min_m=0, y_min_m=0, x_max_m=10, y_max_m=10, attenuation_db=6)
    out = compile_session([node("frontiere", "border"), SENSOR],
                          configs(frontiere=cfg("EU868")), seed=3,
                          environment=EnvironmentSettings(obstacles=[mur],
                                                          shadowing_sigma_db=4.0))
    notes = [n for n in out.notes if n.startswith("environnement")]
    assert len(notes) == 1
    assert "1 obstacle" in notes[0] and "4 dB" in notes[0]
    # Sans environnement réglé, aucune note : annoncer un réglage absent est un mensonge.
    vierge = compile_session([node("frontiere", "border"), SENSOR],
                             configs(frontiere=cfg("EU868")), seed=3)
    assert not [n for n in vierge.notes if n.startswith("environnement")]


# --- Calibration matériau depuis l'atelier -----------------------------------------------------

def _compile(environment=None):
    return compile_session([node("frontiere", "border"), SENSOR],
                           configs(frontiere=cfg("EU868")), seed=3,
                           environment=environment)


def test_a_measured_material_loss_is_compiled_into_the_environment_block():
    """Une perte mesurée déclarée dans l'atelier atteint le scénario, et le scénario la valide.

    Sans ce chemin, la seule façon d'entrer une mesure restait d'éditer le YAML à la main —
    l'atelier, lui, en était réduit à la table extrapolée.
    """
    from lsim.study_contract import EnvironmentSettings, MaterialCalibration

    out = _compile(EnvironmentSettings(material_calibration={
        "concrete": MaterialCalibration(loss_db_per_m=60.0, provenance="banc 2026-03")}))
    bloc = out.body["scenario"]["environment"]["material_calibration"]
    assert bloc == {"concrete": {"loss_db_per_m": 60.0, "provenance": "banc 2026-03"}}
    # Le scénario compilé doit rester valide pour le moteur : c'est lui qui tranche.
    ScenarioModel.model_validate(out.body["scenario"])


def test_a_calibration_alone_is_enough_to_emit_the_block():
    """Une calibration seule fait sortir le bloc : sinon elle serait silencieusement perdue.

    `est_vierge` ne regardait que les obstacles, le sigma et les hauteurs. Une session qui ne
    réglait qu'une mesure compilait donc un scénario sans bloc `environment` du tout.
    """
    from lsim.study_contract import EnvironmentSettings, MaterialCalibration

    out = _compile(EnvironmentSettings(material_calibration={
        "concrete": MaterialCalibration(loss_db_per_m=60.0, provenance="banc 2026-03")}))
    assert "environment" in out.body["scenario"]


def test_an_empty_calibration_changes_nothing():
    """Aucune mesure déclarée : aucun bloc `material_calibration`, empreinte comprise."""
    from lsim.study_contract import EnvironmentSettings, Obstacle

    mur = Obstacle(x_min_m=0, y_min_m=0, x_max_m=10, y_max_m=10,
                   material="concrete", thickness_m=0.25)
    sans = _compile(EnvironmentSettings(obstacles=[mur]))
    avec_vide = _compile(EnvironmentSettings(obstacles=[mur], material_calibration={}))
    assert "material_calibration" not in sans.body["scenario"]["environment"]
    assert "material_calibration" not in avec_vide.body["scenario"]["environment"]


def test_a_calibration_changes_the_scenario_fingerprint():
    """Deux scénarios qui ne diffèrent que par une mesure n'ont pas la même empreinte.

    L'empreinte se lit sur un scénario chargé, pas sur le modèle nu : c'est `Scenario` qui
    décide ce qui entre dans le hachage.
    """
    import tempfile
    import pathlib
    import yaml
    from lsim.scenario import load_scenario
    from lsim.study_contract import EnvironmentSettings, MaterialCalibration, Obstacle

    mur = Obstacle(x_min_m=0, y_min_m=0, x_max_m=10, y_max_m=10,
                   material="concrete", thickness_m=0.25)

    def empreinte(env):
        with tempfile.TemporaryDirectory() as d:
            chemin = pathlib.Path(d) / "session.yaml"
            chemin.write_text(
                yaml.safe_dump(_compile(env).body["scenario"], allow_unicode=True,
                               sort_keys=False), encoding="utf-8")
            return load_scenario(chemin).sha256

    table = empreinte(EnvironmentSettings(obstacles=[mur]))
    mesure = empreinte(EnvironmentSettings(obstacles=[mur], material_calibration={
        "concrete": MaterialCalibration(loss_db_per_m=60.0, provenance="banc 2026-03")}))
    assert table != mesure


def test_a_calibration_from_the_atelier_really_changes_the_loss():
    """La mesure remplace la table dans le calcul — ce n'est pas un champ décoratif.

    Béton, 0,25 m : la table P.2040-4 (extrapolée à 868 MHz) et une mesure à 60 dB/m ne
    donnent pas la même perte. Le chiffre exact vient du moteur, il n'est pas recopié ici.
    """
    from lsim.scenario import _obstacle_attenuation
    from lsim.study_contract import EnvironmentSettings, MaterialCalibration, Obstacle

    mur = Obstacle(x_min_m=0, y_min_m=0, x_max_m=10, y_max_m=10,
                   material="concrete", thickness_m=0.25)
    out = _compile(EnvironmentSettings(obstacles=[mur], material_calibration={
        "concrete": MaterialCalibration(loss_db_per_m=60.0, provenance="banc 2026-03")}))
    modele = ScenarioModel.model_validate(out.body["scenario"])
    o = modele.environment.obstacles[0]
    f_hz = modele.propagation.frequency_hz

    par_table = _obstacle_attenuation(o, f_hz)
    par_mesure = _obstacle_attenuation(o, f_hz, modele.environment.material_calibration)
    # 60 dB/m x 0,25 m, exactement.
    assert par_mesure == pytest.approx(15.0)
    assert par_table != pytest.approx(par_mesure)


def test_the_note_names_measured_materials_instead_of_claiming_the_table():
    """La note annonce « P.2040-4 » — faux dès qu'une mesure s'applique."""
    from lsim.study_contract import EnvironmentSettings, MaterialCalibration, Obstacle

    mur = Obstacle(x_min_m=0, y_min_m=0, x_max_m=10, y_max_m=10,
                   material="concrete", thickness_m=0.25)
    mesuree = _compile(EnvironmentSettings(obstacles=[mur], material_calibration={
        "concrete": MaterialCalibration(loss_db_per_m=60.0, provenance="banc 2026-03")}))
    note = next(n for n in mesuree.notes if n.startswith("environnement"))
    assert "mesuré" in note and "concrete" in note

    table = _compile(EnvironmentSettings(obstacles=[mur]))
    note_table = next(n for n in table.notes if n.startswith("environnement"))
    assert "UIT-R P.2040-4" in note_table and "mesuré" not in note_table


def test_an_unknown_material_is_refused_at_the_atelier():
    """Un matériau hors catalogue est refusé à la saisie, pas au run.

    « beton » pour « concrete » produirait sinon une calibration sans effet : le mur
    resterait sur une valeur extrapolée en laissant croire à une mesure.
    """
    from lsim.study_contract import EnvironmentSettings, MaterialCalibration

    with pytest.raises(ValidationError, match="matériau inconnu"):
        EnvironmentSettings(material_calibration={
            "beton": MaterialCalibration(loss_db_per_m=60.0, provenance="banc")})


def test_a_measurement_without_provenance_is_refused():
    """Même règle que sur un relevé d'énergie : un chiffre sans origine se présente comme
    une donnée du moteur."""
    from lsim.study_contract import MaterialCalibration

    with pytest.raises(ValidationError):
        MaterialCalibration(loss_db_per_m=60.0, provenance="   ")
    with pytest.raises(ValidationError):
        MaterialCalibration(loss_db_per_m=-1.0, provenance="banc")
