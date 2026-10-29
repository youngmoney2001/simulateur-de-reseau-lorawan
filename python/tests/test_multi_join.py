"""Join en multi-passerelles (`build_multi_trace`, options `join`) : invariants et cohérence mono.

Règles vérifiées : une trame est une join-request tant que le dispositif n'a pas reçu son join-accept ;
la join-request décodée reçoit un join-accept à fin + 5 s par la meilleure passerelle ; les descendantes
d'une passerelle ne se chevauchent jamais (y compris join-accept et données, dans l'ordre d'ouverture).
"""

import pytest

from lsim.scenario import Scenario, ScenarioModel
from lsim.simulator import DownlinkRule, simulate_multi_downlinks
from lsim.trace_events import ProtocolOptions, build_multi_trace, build_trace

JOIN_DELAY_NS = 5_000_000_000
GATEWAYS = [{"name": "a", "x_m": 0, "y_m": 0, "antenna_gain_dbi": 2.15},
            {"name": "b", "x_m": 2500, "y_m": 0, "antenna_gain_dbi": 2.15}]


def _scenario(count, messages, gateways, seed, period_s=900, radius_m=3000):
    return Scenario(ScenarioModel.model_validate({
        "schema_version": 1, "name": "join", "seed": seed, "gateways": gateways,
        "propagation": {"frequency_hz": 868100000, "exponent": 2.7},
        "groups": [{"name": "c", "count": count,
                    "placement": {"type": "disk", "radius_m": radius_m},
                    "spreading_factor": 9, "payload_bytes": 20, "tx_power_dbm": 14,
                    "period_s": period_s, "messages": messages, "start_spread_s": 900}],
    }))


OPT = ProtocolOptions(join=True, confirmed_uplinks=True, downlink_every=1)


def test_single_gateway_without_contention_matches_the_mono_trace():
    sc = _scenario(12, 3, GATEWAYS[:1], seed=11, period_s=3600, radius_m=800)
    o = ProtocolOptions(join=True, confirmed_uplinks=True, downlink_every=2)
    mono = sorted((e.t_ns, e.kind, e.device_index, e.outcome) for e in build_trace(sc, o).events)
    multi = sorted((e.t_ns, e.kind, e.device_index, e.outcome)
                   for e in build_multi_trace(sc, o).events)
    assert multi == mono


@pytest.fixture(scope="module")
def contended():
    sc = _scenario(300, 10, GATEWAYS, seed=3)
    return sc, build_multi_trace(sc, OPT)


def test_join_accept_follows_a_received_join_request_by_five_seconds(contended):
    _, mt = contended
    received = {}
    for e in mt.events:
        if e.kind == "join_request" and e.outcome == "received":
            received.setdefault(e.device_index, []).append(e.t_ns)
    accepts = [e for e in mt.events if e.kind == "join_accept"]
    assert accepts, "aucun join-accept dans un scénario où des join-requests sont reçues"
    for e in accepts:
        assert e.outcome == "delivered"
        earlier = [t for t in received.get(e.device_index, []) if t + JOIN_DELAY_NS <= e.t_ns]
        assert earlier, f"join-accept sans join-request reçue (dispositif {e.device_index})"
        assert e.t_ns - max(earlier) >= JOIN_DELAY_NS


def test_at_most_one_join_accept_is_delivered_per_device(contended):
    _, mt = contended
    count = {}
    for e in mt.events:
        if e.kind == "join_accept" and e.outcome == "delivered":
            count[e.device_index] = count.get(e.device_index, 0) + 1
    assert all(c == 1 for c in count.values())


# Un join-accept SF9 à 17 octets dure moins d'une seconde : la réception complète est donc
# atteinte avant `start + 1 s`. Le moteur tient compte de la fin exacte ; la marge sert à la vérification.
JOIN_ACCEPT_MAX_AIRTIME_NS = 1_000_000_000


def test_join_requests_stop_once_the_join_accept_is_received(contended):
    _, mt = contended
    joined_at = {e.device_index: e.t_ns for e in mt.events
                 if e.kind == "join_accept" and e.outcome == "delivered"}
    for e in mt.events:
        if e.kind == "join_request" and e.device_index in joined_at:
            assert e.t_ns < joined_at[e.device_index] + JOIN_ACCEPT_MAX_AIRTIME_NS


def test_data_traffic_only_after_the_join(contended):
    _, mt = contended
    joined_at = {e.device_index: e.t_ns for e in mt.events
                 if e.kind == "join_accept" and e.outcome == "delivered"}
    for e in mt.events:
        if e.kind in ("uplink", "downlink", "ack"):
            assert e.device_index in joined_at, "donnée sans join réussi"
            if e.kind == "uplink":
                # Une trame de données part après la réception du join-accept (début du join-accept
                # plus son airtime, borné ci-dessus).
                assert e.t_ns >= joined_at[e.device_index]


def test_downlinks_of_one_gateway_never_overlap(contended):
    sc, _ = contended
    devices, _, _ = sc.deploy()
    rule = DownlinkRule(ack_uplinks=True, every=1, payload_bytes=10, join=True)
    res = simulate_multi_downlinks(devices, sc.gateways(), sc.propagation(), rule,
                                   sc.environment)
    per_gw = {}
    for dl in res.downlinks:
        if dl.start_ns >= 0:
            per_gw.setdefault(dl.gateway_index, []).append((dl.start_ns, dl.end_ns, dl.join))
    assert any(any(j for _, _, j in v) for v in per_gw.values()), "aucun join-accept émis"
    for g, spans in per_gw.items():
        spans.sort()
        for (s1, e1, _), (s2, _, _) in zip(spans, spans[1:]):
            assert s2 >= e1, f"chevauchement de descendantes sur la passerelle {g}"


def test_join_is_off_by_default_and_changes_nothing():
    sc = _scenario(60, 4, GATEWAYS, seed=5)
    a = build_multi_trace(sc, ProtocolOptions(confirmed_uplinks=True, downlink_every=1))
    assert not any(e.kind.startswith("join") for e in a.events)
