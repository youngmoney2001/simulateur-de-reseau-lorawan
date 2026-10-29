"""Trace mesh par saut : concordance avec `run_scenario` et avec le journal natif."""

from pathlib import Path

import pytest

from lsim.export import run_scenario
from lsim.scenario import load_scenario
from lsim.trace_events import ProtocolOptions, build_multi_trace

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "mesh_relais_quartier.yaml"


@pytest.fixture(scope="module", params=["small", "lossy"])
def small(request, tmp_path_factory):
    """« small » : exemple réduit. « lossy » : mesh SF12, des copies sont perdues sur le mesh
    (lost_mesh > 0), ce qui exerce la branche de perte mesh."""
    text = EXAMPLE.read_text(encoding="utf-8")
    if request.param == "small":
        text = text.replace("count: 300", "count: 40")
    else:
        text = text.replace("  spreading_factor: 9\n  bandwidth_khz", "  spreading_factor: 12\n  bandwidth_khz")
    path = tmp_path_factory.mktemp("mesh") / f"{request.param}.yaml"
    path.write_text(text, encoding="utf-8")
    return load_scenario(path)


@pytest.fixture(scope="module")
def run(small):
    return run_scenario(small)


@pytest.fixture(scope="module")
def trace(small):
    return build_multi_trace(small)


def test_lossy_variant_really_loses_frames_on_the_mesh(small, trace):
    if small.model.mesh.spreading_factor == 12:
        assert trace.lost_mesh > 0
        assert any(e.outcome == "lost_mesh" for e in trace.events if e.kind == "uplink")


def test_totals_and_devices_agree_with_run_scenario(run, trace):
    assert trace.totals.sent == run.totals.sent
    assert trace.totals.received == run.totals.received
    assert trace.totals.lost_collision == run.totals.lost_collision
    assert [c.received for c in trace.per_device] == [r.received for r in run.rows]


def test_every_sent_frame_has_exactly_one_outcome(trace):
    t = trace.totals
    assert t.sent == (t.received + t.lost_sensitivity + t.lost_collision
                      + t.lost_gateway_busy + trace.lost_mesh)
    assert sum(trace.lost_mesh_by_device) == trace.lost_mesh
    for c, lost in zip(trace.per_device, trace.lost_mesh_by_device):
        assert c.sent >= c.received + lost


def test_mesh_hop_events_match_the_native_log(run, trace):
    hops = [e for e in trace.events if e.kind == "mesh_hop"]
    sent = [e for e in hops if e.outcome != "suppressed"]
    assert len(sent) == run.mesh.transmissions
    assert sum(1 for e in hops if e.outcome == "suppressed") == run.mesh.suppressed
    collisions = sum(1 for e in hops if e.outcome == "lost_collision")
    half = sum(1 for e in hops if e.outcome == "lost_half_duplex")
    assert dict(run.mesh.hop_losses).get("collision", 0) == collisions
    assert dict(run.mesh.hop_losses).get("half_duplex", 0) == half


def test_mesh_hops_name_gateways_and_the_mesh_band(trace):
    hops = [e for e in trace.events if e.kind == "mesh_hop"]
    assert hops
    names = set(trace.gateway_names)
    for e in hops:
        (h,) = e.hops
        assert h.from_id[3:] in names and h.to_id[3:] in names
        assert h.freq_hz == 2_400_000_000
        assert e.gateway_index == trace.gateway_names.index(h.from_id[3:])


def test_frames_lost_on_the_mesh_are_not_counted_as_received(run, trace):
    assert trace.totals.received == run.totals.received
    assert trace.lost_mesh == trace.totals.sent - (trace.totals.received + trace.totals.lost_sensitivity
                                                   + trace.totals.lost_collision
                                                   + trace.totals.lost_gateway_busy)


def test_mesh_events_are_time_ordered(trace):
    times = [e.t_ns for e in trace.events]
    assert times == sorted(times)


def test_mesh_refuses_downlink_protocol_options(small):
    for opts in (ProtocolOptions(confirmed_uplinks=True), ProtocolOptions(downlink_every=1),
                 ProtocolOptions(join=True)):
        with pytest.raises(ValueError, match="mesh"):
            build_multi_trace(small, opts)
