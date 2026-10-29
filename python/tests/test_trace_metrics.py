"""Indicateurs de trace (`lsim.trace_metrics`) et règles de remise au LNS (`trace_events`)."""

from pathlib import Path

import pytest

from lsim.trace_events import ProtocolEvent, HopEvent, _direct_deliverer
from lsim.trace_metrics import GatewayMetrics, gateway_metrics, report_fields


def _uplink(t, gw, arrive, outcome="delivered", device=0):
    hops = (HopEvent("dev:0", gw, t, 868100000, 3, None, "delivered"),
            HopEvent(gw, "ns", arrive, 868100000, 3, None, outcome))
    return ProtocolEvent(seq=0, t_ns=t, kind="uplink", device_index=device, gateway_index=0,
                         hops=hops, outcome="data")


def test_latency_is_attributed_to_the_gateway_that_delivered():
    events = [_uplink(0, "gw:frontiere", 100_000_000),
              _uplink(0, "gw:relais-1", 300_000_000)]
    m = gateway_metrics(events, ["frontiere", "relais-1", "ip"])
    assert m["frontiere"].latency_samples_ms == [100.0]
    assert m["relais-1"].latency_samples_ms == [300.0]
    assert m["ip"].latency_samples_ms == []


def test_percentiles_use_the_nearest_rank_and_none_without_samples():
    g = GatewayMetrics(latency_samples_ms=[10.0, 20.0, 30.0, 40.0])
    assert g.percentile_ms(0.5) == 20.0          # rang ceil(0.5*4) = 2
    assert g.percentile_ms(0.95) == 40.0         # rang 4
    assert GatewayMetrics().percentile_ms(0.5) is None
    assert report_fields(GatewayMetrics()) == {"latency_samples": 0, "latency_p50_ms": None,
                                               "latency_p95_ms": None}


def test_lost_or_joined_uplinks_do_not_count_as_latency():
    lost = _uplink(0, "gw:frontiere", 50, outcome="lost_mesh")
    join = ProtocolEvent(seq=1, t_ns=0, kind="join_request", device_index=0, gateway_index=0,
                         hops=(HopEvent("ns", "gw:frontiere", 9, 1, None, None, "delivered"),),
                         outcome="delivered")
    m = gateway_metrics([lost, join], ["frontiere"])
    assert m["frontiere"].latency_samples_ms == []


def test_mesh_hops_give_inbound_links_by_sender_and_ignore_suppressed_copies():
    def mesh(sender, receiver, outcome):
        hop = HopEvent(f"gw:{sender}", f"gw:{receiver}", 5, 2_400_000_000, None, None, outcome)
        return ProtocolEvent(seq=0, t_ns=5, kind="mesh_hop", device_index=0, gateway_index=0,
                             hops=(hop,), outcome=outcome)

    events = [mesh("relais-1", "frontiere", "delivered"),
              mesh("relais-1", "frontiere", "delivered"),
              mesh("relais-2", "frontiere", "delivered"),
              mesh("relais-2", "frontiere", "suppressed")]
    m = gateway_metrics(events, ["frontiere", "relais-1", "relais-2"])
    assert m["frontiere"].inbound == {"relais-1": 2, "relais-2": 1}
    fields = report_fields(m["frontiere"])
    assert fields["mesh_inbound"] == [{"from_gateway": "relais-1", "delivered": 2},
                                      {"from_gateway": "relais-2", "delivered": 1}]


def test_a_relay_is_never_named_as_a_direct_deliverer():
    # Décodée par le relais (bit 1) et par la frontière (bit 0) : la frontière remet.
    models = [_Model("frontiere", mesh=True), _Model("relais-1", mesh=True)]
    assert _direct_deliverer(0b11, models, "frontiere") == 0
    # Décodée par le relais seul : aucune remise directe possible.
    assert _direct_deliverer(0b10, models, "frontiere") is None
    # Décodée par une passerelle à backhaul IP, sans frontière : elle remet.
    models = [_Model("frontiere", mesh=True), _Model("ip-ouest", mesh=False)]
    assert _direct_deliverer(0b10, models, "frontiere") == 1


class _Model:
    def __init__(self, name, mesh):
        self.name, self.mesh = name, mesh


@pytest.mark.parametrize("q,expected", [(0.01, 1.0), (1.0, 4.0)])
def test_extreme_quantiles(q, expected):
    assert GatewayMetrics(latency_samples_ms=[1.0, 2.0, 3.0, 4.0]).percentile_ms(q) == expected


EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "mesh_relais_quartier.yaml"


def test_example_relays_never_deliver_and_relayed_frames_arrive_after_their_mesh_delay():
    from lsim.scenario import load_scenario
    from lsim.trace_events import build_multi_trace
    s = load_scenario(EXAMPLE)
    mt = build_multi_trace(s)
    border = s.model.mesh.border
    relays = {g.name for g in s.gateway_models() if g.mesh and g.name != border}  # sans backhaul IP
    assert relays == {"relais-1", "relais-2"}
    ns_hops = [(ev, h) for ev in mt.events if ev.kind == "uplink" for h in ev.hops
               if h.to_id == "ns" and h.outcome == "delivered"]
    assert ns_hops
    for ev, h in ns_hops:
        assert h.from_id != "gw:none"
        assert h.from_id[len("gw:"):] not in relays, "un relais remet directement au LNS"
    relayed_late = [h.t_ns - ev.t_ns for ev, h in ns_hops
                    if h.from_id == f"gw:{border}" and h.t_ns - ev.t_ns > 185_344_000]
    assert relayed_late, "aucune trame relayée remise après un délai mesh"
    assert all(h.t_ns >= ev.t_ns for ev, h in ns_hops)
