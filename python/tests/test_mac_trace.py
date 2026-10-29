"""Commandes MAC dans la trace (phase 1) : LinkCheckReq/Ans, DevStatusReq, FOpts et airtime."""

import copy

import pytest

from lsim.mac import DevStatusReq, LinkCheckAns, decode_all
from lsim.scenario import Scenario, ScenarioModel
from lsim.trace_events import ProtocolOptions, build_trace

BASE = {
    "schema_version": 1, "name": "mac", "seed": 7,
    "gateway": {"x_m": 0, "y_m": 0, "antenna_gain_dbi": 2.15},
    "propagation": {"frequency_hz": 868100000, "exponent": 2.7},
    "groups": [{
        "name": "c", "count": 6, "placement": {"type": "disk", "radius_m": 800},
        "spreading_factor": 7, "payload_bytes": 12, "tx_power_dbm": 14,
        "period_s": 600, "messages": 6, "start_spread_s": 600,
    }],
}


def _scenario(mac=None, extra=None):
    raw = copy.deepcopy(BASE)
    if mac is not None:
        raw["mac"] = mac
    if extra:
        raw.update(extra)
    return Scenario(ScenarioModel.model_validate(raw))


def _kinds(tr, kind):
    return [e for e in tr.events if e.kind == kind]


def test_without_mac_block_the_trace_has_no_mac_events():
    tr = build_trace(_scenario(), ProtocolOptions(confirmed_uplinks=True))
    assert not _kinds(tr, "mac_request") and not _kinds(tr, "mac_answer")


def test_disabled_mac_block_leaves_the_trace_unchanged():
    ref = build_trace(_scenario(), ProtocolOptions(confirmed_uplinks=True))
    off = build_trace(_scenario({"link_check_every": 0, "device_status_every": 0}),
                      ProtocolOptions(confirmed_uplinks=True))
    assert [(e.kind, e.t_ns, e.outcome) for e in ref.events] == \
        [(e.kind, e.t_ns, e.outcome) for e in off.events]


def test_link_check_request_is_answered_by_a_downlink_with_link_check_ans():
    tr = build_trace(_scenario({"link_check_every": 2}), ProtocolOptions())
    reqs = _kinds(tr, "mac_request")
    answers = _kinds(tr, "mac_answer")
    received = [r for r in tr.records if r.outcome == 2]
    # Chaque uplink reçu de rang pair porte une requête ; chacune reçoit une réponse délivrée.
    assert len(reqs) > 0
    assert all(r.outcome == "LinkCheckReq" for r in reqs)
    assert len(answers) == len(reqs) <= len(received)
    assert all(a.outcome == "delivered" for a in answers)
    # La réponse part après l'uplink qui la sollicite (fenêtre RX1).
    assert min(a.t_ns for a in answers) > min(r.t_ns for r in reqs)


def test_answer_downlink_is_longer_than_a_plain_ack():
    plain = build_trace(_scenario(), ProtocolOptions(confirmed_uplinks=True))
    mac = build_trace(_scenario({"link_check_every": 1}), ProtocolOptions(confirmed_uplinks=True))
    # Même trafic montant : les FOpts (LinkCheckAns, 3 octets) allongent les ACK émis.
    assert mac.gateway_tx and plain.gateway_tx
    gw_mac = sum(end - start for start, end in mac.gateway_tx)
    gw_plain = sum(end - start for start, end in plain.gateway_tx)
    assert gw_mac > gw_plain


def test_device_status_request_rides_on_every_second_downlink():
    opts = ProtocolOptions(downlink_every=1)
    tr = build_trace(_scenario({"device_status_every": 2}), opts)
    reqs = _kinds(tr, "mac_request")
    assert reqs and all(r.outcome == "DevStatusReq" for r in reqs)
    downs = [e for e in tr.events if e.kind == "downlink" and e.outcome == "data"]
    # Une requête par période : jamais plus que la moitié des downlinks émis.
    assert len(reqs) <= (len(downs) + 1) // 2 + 1
    assert len(reqs) < len(downs) or not downs


def test_mac_fopts_decode_to_the_expected_commands():
    # Vérifie le codage des FOpts de réponse, indépendamment de la trace.
    from lsim.trace_events import _downlink_fopts
    from lsim.mac_plan import MacSchedule

    sched = MacSchedule(link_check_every=1, device_status_every=2)
    assert decode_all(_downlink_fopts(sched, 1, 12), downlink=True) == [LinkCheckAns(12, 1)]
    assert decode_all(_downlink_fopts(sched, 2, 12), downlink=True) == [
        LinkCheckAns(12, 1), DevStatusReq()]
    assert _downlink_fopts(sched, 1, None) == b""
    with pytest.raises(ValueError):
        MacSchedule(link_check_every=-1)


def test_mac_with_several_gateways_is_refused():
    raw = copy.deepcopy(BASE)
    raw["mac"] = {"link_check_every": 1}
    raw["gateways"] = [{"name": "a", "x_m": 0, "y_m": 0}, {"name": "b", "x_m": 500, "y_m": 0}]
    with pytest.raises(ValueError, match="passerelle unique"):
        ScenarioModel.model_validate(raw)


def test_mac_trace_is_reproducible():
    a = build_trace(_scenario({"link_check_every": 2, "device_status_every": 3}),
                    ProtocolOptions(downlink_every=2))
    b = build_trace(_scenario({"link_check_every": 2, "device_status_every": 3}),
                    ProtocolOptions(downlink_every=2))
    assert a.events == b.events


def test_uplinks_carrying_link_check_req_are_longer_in_the_engine():
    # Charge 12 octets, SF7 : 13 octets franchissent un bloc de symboles (20 -> 25) ; rang pair = FOpts.
    from lsim.simulator import simulate_uplinks_trace
    sc = _scenario({"link_check_every": 2})
    devices, _, _ = sc.deploy()
    tr = simulate_uplinks_trace(devices, sc.gateway(), sc.propagation())
    by_dev = {}
    for r in tr.records:
        by_dev.setdefault(r.device_index, []).append(r)
    for recs in by_dev.values():
        durations = [r.end_ns - r.start_ns for r in recs]
        assert durations[1] > durations[0] and durations[3] > durations[2]
        assert durations[0] == durations[2] == durations[4]
    # Le temps d'antenne compté par le moteur est la somme des émissions.
    for d, c in enumerate(tr.per_device):
        assert c.airtime_ns == sum(r.end_ns - r.start_ns for r in by_dev[d])


def test_link_margin_is_rssi_above_threshold_minus_installation():
    from lsim.mac_plan import MacSchedule
    from lsim.radio import receiver_sensitivity_dbm
    from lsim.simulator import TxRecord
    from lsim.trace_events import _link_margin_db

    s7 = receiver_sensitivity_dbm(7, 125_000)
    rec = TxRecord(0, 0, 1, 7, s7 + 10.4, TxRecord.OUTCOME_RECEIVED)
    assert _link_margin_db(rec, 0) == 10          # floor, en dB entiers
    assert _link_margin_db(rec, 3) == 7           # marge d'installation soustraite
    low = TxRecord(0, 0, 1, 7, s7 - 5.0, TxRecord.OUTCOME_RECEIVED)
    assert _link_margin_db(low, 0) == 0           # borne basse
    high = TxRecord(0, 0, 1, 7, 300.0, TxRecord.OUTCOME_RECEIVED)  # hors plage physique : borné
    assert _link_margin_db(high, 0) == 254        # borne haute
    assert MacSchedule(link_margin_installation_db=60).link_margin_installation_db == 60
    with pytest.raises(ValueError):
        MacSchedule(link_margin_installation_db=61)


def test_installation_margin_is_reported_in_link_check_ans():
    from lsim.mac import LinkCheckAns, decode_all
    from lsim.trace_events import _downlink_fopts
    from lsim.mac_plan import MacSchedule
    sched = MacSchedule(link_check_every=1, link_margin_installation_db=5)
    assert decode_all(_downlink_fopts(sched, 1, 9), downlink=True) == [LinkCheckAns(9, 1)]


def test_engine_airtime_feeds_the_uplink_energy():
    from lsim.energy_report import device_energies_protocol, uplink_airtime_ns
    from lsim.simulator import EndDevice
    plain = EndDevice(payload_bytes=12, spreading_factor=7)
    with_mac = EndDevice(payload_bytes=12, spreading_factor=7, link_check_every=4)
    assert uplink_airtime_ns(plain) < uplink_airtime_ns(with_mac) < 2 * uplink_airtime_ns(plain)
    devs = [with_mac]
    base = device_energies_protocol(devs, [0], [8], "rak4631")
    # Airtime réel compté : 6 émissions sans FOpts, 2 avec (rangs 4 et 8).
    t_plain = uplink_airtime_ns(plain)
    t_with = uplink_airtime_ns(EndDevice(payload_bytes=13, spreading_factor=7))
    counted = device_energies_protocol(devs, [0], [8], "rak4631", [6 * t_plain + 2 * t_with])
    assert counted[0].energy_per_message_j is not None and base[0].energy_per_message_j is not None


def test_end_device_link_check_bounds():
    from lsim.simulator import EndDevice
    with pytest.raises(ValueError):
        EndDevice(link_check_every=1001)
    with pytest.raises(ValueError):
        EndDevice(payload_bytes=255, link_check_every=1)
    assert EndDevice(payload_bytes=254, link_check_every=1).link_check_every == 1
