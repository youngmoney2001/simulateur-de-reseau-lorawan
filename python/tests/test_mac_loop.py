"""Bloc `mac:` → boucle fermée (LinkADRReq, DutyCycleReq) : chemin de trace, événements, refus."""

from collections import Counter

import pytest
from pydantic import ValidationError

from lsim.mac_loop import closed_loop_applies, loop_regions
from lsim.regions import power_table
from lsim.scenario import load_scenario
from lsim.trace_events import ProtocolOptions, build_trace

BASE = """schema_version: 1
name: boucle fermee
seed: 1
gateway: {x_m: 0, y_m: 0, antenna_gain_dbi: 2.15}
groups:
  - name: g
    count: 40
    placement: {type: disk, radius_m: 3000}
    spreading_factor: 9
    payload_bytes: 20
    tx_power_dbm: 14
    period_s: 900
    messages: 30
    start_spread_s: 900
    region: EU868
"""


def _scenario(mac: str, base: str = BASE):
    return load_scenario(base + mac)


def test_adr_trace_uses_closed_loop_and_emits_mac_events():
    sc = _scenario("mac:\n  link_adr: true\n  duty_cycle_exponent: 3\n  link_margin_installation_db: 2\n")
    assert closed_loop_applies(sc)
    tr = build_trace(sc, ProtocolOptions())
    assert len(tr.records) == 1200
    kinds = Counter(e.kind for e in tr.events)
    assert kinds["mac_request"] > 0
    requests = Counter(e.outcome for e in tr.events if e.kind == "mac_request")
    assert requests["LinkADRReq"] > 0
    assert requests["DutyCycleReq"] > 0
    answers = Counter(e.outcome for e in tr.events if e.kind == "mac_answer")
    assert answers["LinkADRAns"] > 0 and answers["DutyCycleAns"] > 0
    # Événements dans l'ordre temporel, numérotés.
    times = [e.t_ns for e in tr.events]
    assert times == sorted(times)
    assert [e.seq for e in tr.events] == list(range(len(tr.events)))


def test_adr_converges_for_some_devices_and_spreads_sf():
    sc = _scenario("mac:\n  link_adr: true\n")
    tr = build_trace(sc, ProtocolOptions())
    sfs = Counter(r.spreading_factor for r in tr.records)
    # Les proches passent à SF7 ; les plus éloignés gardent SF9.
    assert sfs[7] > 0 and sfs[9] > 0
    assert set(sfs) <= {7, 8, 9}


def test_duty_cycle_only_changes_spacing_not_sf():
    sc = _scenario("mac:\n  duty_cycle_exponent: 2\n")
    tr = build_trace(sc, ProtocolOptions())
    assert {r.spreading_factor for r in tr.records} == {9}
    assert any(e.kind == "mac_request" and e.outcome == "DutyCycleReq" for e in tr.events)


def test_without_new_fields_the_path_and_hash_are_unchanged():
    plain = _scenario("")
    mac_old = _scenario("mac:\n  link_check_every: 5\n")
    assert not closed_loop_applies(plain)
    assert not closed_loop_applies(mac_old)
    # Un champ à sa valeur par défaut n'entre pas dans l'empreinte ; activer LinkADR la modifie.
    explicit_off = _scenario("mac:\n  link_check_every: 5\n  link_adr: false\n")
    assert explicit_off.sha256 == mac_old.sha256
    with_adr = _scenario("mac:\n  link_adr: true\n")
    assert with_adr.sha256 != mac_old.sha256


def test_link_adr_requires_a_region_with_power_table():
    with pytest.raises(ValueError, match="plan régional"):
        build_trace(_scenario("mac:\n  link_adr: true\n", BASE.replace("    region: EU868\n", "")),
                    ProtocolOptions())
    # US915 : plan connu, sans table TXPower dans le registre : LinkADR refusé.
    assert power_table("US915") is None
    us = BASE.replace("    region: EU868\n", "    region: US915\n    sub_band: 1\n").replace(
        "tx_power_dbm: 14", "tx_power_dbm: 14").replace("spreading_factor: 9", "spreading_factor: 9")
    us = us.replace("    messages: 30\n", "    messages: 30\n    channel_freq_hz: 902300000\n")
    with pytest.raises(ValueError, match="sans table TXPower"):
        build_trace(_scenario("mac:\n  link_adr: true\n", us), ProtocolOptions())


def test_duty_cycle_without_region_uses_group_duty_only():
    sc = _scenario("mac:\n  duty_cycle_exponent: 1\n", BASE.replace("    region: EU868\n", ""))
    regions = loop_regions(sc, [g.name for g in sc.model.groups] * 40)
    assert regions[0].duty_limit[0] == 1.0
    tr = build_trace(sc, ProtocolOptions())
    assert len(tr.records) == 1200


def test_power_table_caps_index_zero_and_steps_two_db():
    sc = _scenario("mac:\n  link_adr: true\n")
    region = loop_regions(sc, ["g"])[0]
    table = power_table("EU868")
    assert table.max_eirp_dbm == 16.0 and table.step_db == 2.0 and table.max_index == 7
    assert region.max_tx_power_index == 7
    assert region.power_step_tenth_db == 20
    assert region.max_eirp_dbm == 16.0
    # Limite réglementaire à 868,1 MHz : sous-bande M (1 %) à la PIRE de chaque index.
    assert region.duty_limit[0] == pytest.approx(0.01)
    assert region.duty_limit[7] == pytest.approx(0.01)
    # Index réservés (8..15) : pas de limite définie, LinkADR les refusera.
    assert all(v == 1.0 for v in region.duty_limit[8:])


def test_closed_loop_refuses_join_and_gateways_and_accepts_reservations():
    sc = _scenario("mac:\n  link_adr: true\n")
    with pytest.raises(ValueError, match="jointure"):
        build_trace(sc, ProtocolOptions(join=True))
    # Les réservations MAC (LinkCheck, DeviceTime, DevStatus) passent dans la boucle fermée.
    combined = _scenario("mac:\n  link_adr: true\n  link_check_every: 5\n"
                         "  device_status_every: 4\n  device_time_every: 7\n")
    tr = build_trace(combined, ProtocolOptions())
    assert tr.totals.sent == sum(d.messages for d in combined.deploy()[0])
    assert any(e.kind == "mac_request" and e.outcome == "LinkCheckReq" for e in tr.events)
    with pytest.raises(ValidationError, match="passerelle unique"):
        load_scenario(BASE + "gateways:\n  - {x_m: 0, y_m: 0}\n  - {x_m: 900, y_m: 0}\n"
                      "mac:\n  link_adr: true\n")


def test_export_run_matches_trace_counters():
    from lsim.export import run_scenario

    sc = _scenario("mac:\n  link_adr: true\n  duty_cycle_exponent: 3\n")
    tr = build_trace(sc, ProtocolOptions())
    run = run_scenario(sc)
    assert run.totals == tr.totals
    assert len(run.rows) == 40


def test_reservations_closed_loop_matches_legacy_path():
    """Sans LinkADR ni DutyCycle, la boucle fermée reproduit le chemin historique : mêmes
    émissions (airtime des octets réservés), mêmes descentes, mêmes événements."""
    from lsim.trace_events import build_trace_closed_loop

    sc = _scenario("mac:\n  link_check_every: 3\n  device_status_every: 4\n  device_time_every: 5\n")
    legacy = build_trace(sc, ProtocolOptions())
    loop = build_trace_closed_loop(sc, ProtocolOptions())
    assert loop.records == legacy.records
    assert loop.totals == legacy.totals
    assert loop.per_device == legacy.per_device
    assert loop.gateway_tx == legacy.gateway_tx
    assert loop.events == legacy.events
    # Le scénario exerce bien les trois commandes (sinon la parité ne prouve rien).
    kinds = Counter((e.kind, e.outcome) for e in legacy.events)
    assert kinds[("mac_request", "LinkCheckReq")] > 0
    assert kinds[("mac_request", "DeviceTimeReq")] > 0
    assert kinds[("mac_request", "DevStatusReq")] > 0
    assert kinds[("mac_answer", "DevStatusAns")] > 0
    assert kinds[("mac_answer", "delivered")] > 0
    # Les octets réservés allongent l'airtime par rapport au même scénario sans MAC.
    plain = build_trace(_scenario(""), ProtocolOptions())
    assert legacy.totals.airtime_ns > plain.totals.airtime_ns
