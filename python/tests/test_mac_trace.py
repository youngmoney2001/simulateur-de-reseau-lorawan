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
