"""Modèle de sensibilité absolue `sensibilite-par-sf-v2` (ABI v2) : catalogue, trace, refus, scénario."""

import pytest

from lsim.gateway_sensitivity import (CATALOG, MODEL_ID, SX1303_DATASHEET, AbsoluteSensitivity,
                                     SensitivityError)
from lsim.geo import coverage_radius_m
from lsim.lora import StatusError
from lsim.scenario import load_scenario
from lsim.simulator import (EndDevice, Gateway, Propagation, simulate_uplinks,
                            simulate_uplinks_multi, simulate_uplinks_trace)

SF5_GROUP = ("  - name: g\n    count: 1\n    spreading_factor: 5\n    region: EU868\n"
             "    placement: {type: disk, radius_m: 10}\n")
SF7_GROUP = ("  - name: g\n    count: 1\n    spreading_factor: 7\n"
             "    placement: {type: disk, radius_m: 10}\n")


def _yaml(gateway_block: str, groups: str = SF5_GROUP, tail: str = "") -> str:
    return ("schema_version: 1\nname: t\n" + gateway_block + "groups:\n" + groups + tail)


PROFILE_SENS = ("gateway:\n  sensitivity:\n    model: sensibilite-par-sf-v2\n"
                "    profile: sx1303-datasheet\n")
EXPLICIT_SENS = ("gateway:\n  sensitivity:\n    model: sensibilite-par-sf-v2\n"
                 "    source: test\n    conditions: test\n    points:\n"
                 "      - {sf: 5, dbm: -100}\n      - {sf: 7, dbm: -100}\n")


# ------------------------------------------------------------------ catalogue
def test_catalog_sf5_value_and_sf6_is_not_documented():
    assert CATALOG["sx1303-datasheet"] is SX1303_DATASHEET
    assert SX1303_DATASHEET.lookup(5, 125_000) == -121.0
    with pytest.raises(SensitivityError, match="absente"):
        SX1303_DATASHEET.lookup(6, 125_000)


def test_missing_pair_is_refused_explicitly():
    with pytest.raises(SensitivityError, match="absente"):
        SX1303_DATASHEET.lookup(5, 250_000)


def test_sf6_point_is_refused_at_construction():
    with pytest.raises(SensitivityError, match="SF6"):
        AbsoluteSensitivity(points=((125_000, 6, -123.5),))


@pytest.mark.parametrize("points", [
    ((125_000, 5, -200.0),),                       # hors [-160, -60]
    ((125_000, 5, -100.0), (125_000, 5, -110.0)),  # doublon
    ((868_000, 5, -100.0),),                       # bande non supportée
    ((125_000, 13, -100.0),),                      # SF hors 5..12
])
def test_invalid_points_are_refused(points):
    with pytest.raises(SensitivityError):
        AbsoluteSensitivity(points=points)


def test_to_c_refuses_relative_offset():
    with pytest.raises(SensitivityError, match="décalage"):
        SX1303_DATASHEET.to_c(Gateway(rx_sensitivity_offset_db=2.0))


# ------------------------------------------------------------------ trace ABI v2
def _trace(absolute, distance_m=3000.0):
    dev = EndDevice(x_m=distance_m, spreading_factor=5, messages=1, payload_bytes=10)
    return simulate_uplinks_trace([dev], Gateway(absolute_sensitivity=absolute), Propagation())


def test_trace_sf5_uses_the_absolute_threshold():
    # RSSI à 3 km voisin de -110 dBm : reçue avec -121 dBm (catalogue), perdue avec -100 dBm.
    received = _trace(SX1303_DATASHEET)
    assert received.totals.received == 1
    assert -120.0 < received.records[0].rssi_dbm < -100.0
    lost = _trace(AbsoluteSensitivity(points=((125_000, 5, -100.0),)))
    assert lost.totals.received == 0 and lost.totals.lost_sensitivity == 1


def test_trace_sf5_without_absolute_model_is_refused_by_core():
    # ABI v1 : la table SX1276 n'a pas de SF5 ; refus explicite du cœur, aucun repli.
    with pytest.raises(StatusError):
        simulate_uplinks_trace([EndDevice(x_m=10.0, spreading_factor=5)], Gateway(), Propagation())


# ------------------------------------------------------------------ refus explicites
def test_simulate_uplinks_uses_the_trace_path_for_the_absolute_model():
    dev = [EndDevice(x_m=3000.0, spreading_factor=5, messages=2)]
    gw = Gateway(absolute_sensitivity=SX1303_DATASHEET)
    plain = simulate_uplinks(dev, gw, Propagation())
    traced = simulate_uplinks_trace(dev, gw, Propagation())
    assert plain.totals == traced.totals and plain.per_device == traced.per_device
    assert plain.totals.received == 2


def test_multi_gateway_refuses_the_absolute_model():
    gw = Gateway(absolute_sensitivity=SX1303_DATASHEET)
    with pytest.raises(SensitivityError, match=MODEL_ID):
        simulate_uplinks_multi([EndDevice(x_m=100.0, spreading_factor=7)], [gw], Propagation())


# ------------------------------------------------------------------ scénario
def test_scenario_sf5_without_model_is_refused():
    with pytest.raises(ValueError, match="SF5 exige"):
        load_scenario(_yaml(""))


def test_scenario_sf5_with_catalog_profile_loads_and_builds_gateway():
    scenario = load_scenario(_yaml(PROFILE_SENS))
    assert scenario.gateway().absolute_sensitivity == SX1303_DATASHEET


def test_scenario_sf5_with_explicit_points_loads():
    scenario = load_scenario(_yaml(EXPLICIT_SENS))
    assert scenario.gateway().absolute_sensitivity.lookup(5, 125_000) == -100.0


@pytest.mark.parametrize("yaml_text, message", [
    (_yaml(PROFILE_SENS, SF5_GROUP.replace("spreading_factor: 5", "spreading_factor: 6")),
     "SF6 non modélisé"),
    (_yaml(PROFILE_SENS, SF5_GROUP.replace("    region: EU868\n", "")),
     "réservé à la région"),
    (_yaml("gateway:\n  profile: rak7249\n  sensitivity:\n    model: sensibilite-par-sf-v2\n"
           "    profile: sx1303-datasheet\n"),
     "incompatibles"),
    (_yaml("gateway:\n  sensitivity:\n    model: sensibilite-par-sf-v2\n"
           "    profile: inconnu\n"),
     "profil de sensibilité inconnu"),
    (_yaml("gateway:\n  sensitivity:\n    model: sensibilite-par-sf-v2\n"
           "    profile: sx1303-datasheet\n    points: [{sf: 5, dbm: -100}]\n"),
     "exactement"),
    (_yaml("gateway:\n  sensitivity:\n    model: sensibilite-par-sf-v2\n"
           "    points: [{sf: 5, dbm: -100}]\n"),
     "source"),
    (_yaml("gateway:\n  sensitivity:\n    model: sensibilite-par-sf-v2\n    source: t\n"
           "    conditions: t\n    points: [{sf: 7, dbm: -100}]\n"),
     "absente"),
    (_yaml(EXPLICIT_SENS, SF5_GROUP, tail="mac:\n  link_adr: true\n"),
     "SF5 avec bloc « mac » refusé"),
])
def test_scenario_refusals(yaml_text, message):
    with pytest.raises(ValueError, match=message):
        load_scenario(yaml_text)


def test_scenario_multi_gateway_with_model_is_refused():
    text = ("schema_version: 1\nname: t\n"
            "gateways:\n  - {x_m: 0}\n  - {x_m: 1000}\n"
            "gateway:\n  sensitivity:\n    model: sensibilite-par-sf-v2\n    profile: sx1303-datasheet\n"
            "groups:\n" + SF7_GROUP)
    with pytest.raises(ValueError, match="passerelle unique"):
        load_scenario(text)


def test_scenario_sf7_groups_need_their_pair_in_the_profile():
    # Un profil explicite sans SF7 : le groupe SF7 est refusé (paire absente), pas déduit.
    text = _yaml(EXPLICIT_SENS.replace("      - {sf: 7, dbm: -100}\n", ""), SF7_GROUP)
    with pytest.raises(ValueError, match="absente"):
        load_scenario(text)


def test_geo_coverage_follows_the_absolute_threshold():
    strict = load_scenario(_yaml(EXPLICIT_SENS))
    catalog = load_scenario(_yaml(PROFILE_SENS))
    assert coverage_radius_m(catalog, 5, 14.0) > coverage_radius_m(strict, 5, 14.0) > 0


def test_model_changes_the_scenario_hash_only_when_present():
    base = load_scenario("schema_version: 1\nname: t\ngroups:\n" + SF7_GROUP)
    with_model = load_scenario(_yaml(PROFILE_SENS, SF7_GROUP))
    assert base.sha256 != with_model.sha256


def test_scenario_sf5_run_uses_the_absolute_engine():
    scenario = load_scenario(_yaml(PROFILE_SENS, SF5_GROUP.replace("count: 1", "count: 3")))
    from lsim.export import run_scenario
    result = run_scenario(scenario)
    assert result.totals.sent == 3 and result.totals.lost_collision + result.totals.received <= 3


def test_causal_trace_refuses_sf5_downlinks_explicitly():
    from lsim.trace_events import build_trace
    with pytest.raises(SensitivityError, match="descente vers RX1 SF5 refusée"):
        build_trace(load_scenario(_yaml(PROFILE_SENS)))


def test_causal_trace_native_absolute_path_sf7():
    # Chemin causal (descentes) avec SF7 : passe par lsim_simulate_uplinks_causal_gw2. Seuil absolu
    # -100 dBm, dispositifs à quelques mètres (RSSI ≈ -40 dBm) : la sensibilité ne limite pas ;
    # les deux émissions simultanées (départ à 0) entrent en collision, pas en perte de sensibilité.
    from lsim.trace_events import build_trace
    near = load_scenario(_yaml(EXPLICIT_SENS, SF7_GROUP.replace("count: 1", "count: 2")))
    run = build_trace(near)
    assert run.totals.sent == len(run.records) == 2
    assert all(r.outcome in (1, 2) and r.rssi_dbm > -100.0 for r in run.records)
    assert run.totals.lost_sensitivity == 0
