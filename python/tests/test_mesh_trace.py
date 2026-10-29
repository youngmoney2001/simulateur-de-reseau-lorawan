"""Trace mesh par saut : concordance avec `run_scenario` et avec le journal natif."""

from pathlib import Path

import pytest

from lsim.export import run_scenario
from lsim.scenario import load_scenario
from lsim.trace_events import MultiTraceRun, ProtocolOptions, build_multi_trace

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


DOWNLINK_OPTIONS = (ProtocolOptions(confirmed_uplinks=True), ProtocolOptions(downlink_every=1),
                    ProtocolOptions(join=True))


@pytest.mark.parametrize("opts", DOWNLINK_OPTIONS)
def test_mesh_downlinks_are_traced_by_hop(small, opts):
    trace = build_multi_trace(small, opts)
    down_hops = [e for e in trace.events if e.kind == "mesh_downlink_hop"]
    assert down_hops, "aucun saut descendant : la passe retour n'a rien acheminé"
    assert all(h.outcome in ("delivered", "lost_collision", "lost_half_duplex", "suppressed")
               for e in down_hops for h in e.hops)
    # Une descente mesh-servie ne part pas avant son arrivée au relais (dernier saut descendant).
    starts = [e for e in trace.events if e.kind in ("ack", "downlink", "join_accept")
              and e.outcome not in ("lost_mesh", "lost_sensitivity")]
    assert starts, "aucune descente servie"
    first_hop = {}
    for e in down_hops:
        first_hop[e.device_index] = min(first_hop.get(e.device_index, e.t_ns), e.t_ns)
    served_by_mesh = [e for e in starts if e.device_index in first_hop]
    assert served_by_mesh, "aucune descente acheminée par le mesh"
    assert all(e.t_ns >= first_hop[e.device_index] for e in served_by_mesh)


@pytest.mark.parametrize("opts", DOWNLINK_OPTIONS)
def test_mesh_loads_match_the_hop_log(small, opts):
    trace = build_multi_trace(small, opts)
    assert trace.mesh_loads is not None and len(trace.mesh_loads) == len(trace.gateway_names)
    assert trace.mesh_loads[trace.gateway_names.index("ip-ouest")] is None
    hop_kinds = ("mesh_hop", "mesh_downlink_hop")
    logged = [h for e in trace.events if e.kind in hop_kinds for h in e.hops]
    loads = [m for m in trace.mesh_loads if m is not None]
    assert len(loads) == len(trace.gateway_names) - 1  # tout sauf la passerelle IP (sans mesh)
    tx = sum(m.transmissions for m in loads)
    assert tx == sum(1 for h in logged if h.outcome != "suppressed")
    assert sum(m.suppressed for m in loads) == sum(
        1 for h in logged if h.outcome == "suppressed")
    assert sum(m.lost_collision for m in loads) == sum(
        1 for h in logged if h.outcome == "lost_collision")
    assert sum(m.lost_half_duplex for m in loads) == sum(
        1 for h in logged if h.outcome == "lost_half_duplex")
    assert all(m.busy_ns >= 0 for m in loads)


def test_mesh_fixed_point_is_deterministic(small):
    a = build_multi_trace(small, ProtocolOptions(confirmed_uplinks=True, downlink_every=1))
    b = build_multi_trace(small, ProtocolOptions(confirmed_uplinks=True, downlink_every=1))
    assert a.events == b.events and a.mesh_loads == b.mesh_loads


def test_mono_trace_has_no_mesh_loads():
    """Hors mesh, la charge mesh est absente (None) : invariant de contrat."""
    assert MultiTraceRun.__dataclass_fields__["mesh_loads"].default is None


def test_lost_downlink_on_mesh_is_traced_and_costs_no_airtime(small, monkeypatch):
    """Descente perdue sur le mesh : issue `lost_mesh`, hors comptage d'airtime de réception."""
    import dataclasses

    import lsim.trace_events as te
    from lsim.mesh_pass import MeshDownlinkRoute

    real_pass = te.mesh_pass

    def all_lost(*args, **kwargs):
        mp = real_pass(*args, **kwargs)
        lost = {k: MeshDownlinkRoute(False, None, "collision", v.hops)
                for k, v in mp.downlinks.items()}
        return dataclasses.replace(mp, downlinks=lost)

    monkeypatch.setattr(te, "mesh_pass", all_lost)
    opts = ProtocolOptions(confirmed_uplinks=True, downlink_every=1)
    trace = build_multi_trace(small, opts)
    lost = [e for e in trace.events if e.outcome == "lost_mesh" and e.kind in ("ack", "downlink")]
    assert lost, "aucune descente perdue sur le mesh"
    assert all(len(e.hops) == 1 and e.hops[0].from_id == "ns" for e in lost)
    # Les sauts du trajet restent au journal : la descente a bien été émise sur le mesh.
    assert any(e.kind == "mesh_downlink_hop" for e in trace.events)
    kept = tuple(e for e in trace.events if e.outcome != "lost_mesh")
    assert te.downlink_airtime_by_device(small, trace.events, opts) == \
        te.downlink_airtime_by_device(small, kept, opts)


def test_engine_ready_minus_one_is_identical_and_never_blocks_all(small):
    """Moteur : départ « -1 » = aucune contrainte (résultat identique à l'absence de tableau) ;
    `DL_READY_NEVER` = aucune descente émise (sentinelle de descente jamais acheminée)."""
    from lsim.simulator import DL_READY_NEVER, DownlinkRule, simulate_multi_downlinks

    devices, _, _ = small.deploy()
    total = sum(d.messages for d in devices)
    rule = DownlinkRule(ack_uplinks=True, every=1, payload_bytes=10)
    args = (devices, small.gateways(), small.propagation(), rule, small.environment)
    base = simulate_multi_downlinks(*args)
    same = simulate_multi_downlinks(*args, dl_ready_ns=[-1] * total)
    assert base.downlinks == same.downlinks and base.network == same.network
    assert base.per_device == same.per_device
    never = simulate_multi_downlinks(*args, dl_ready_ns=[DL_READY_NEVER] * total)
    assert never.downlinks and all(d.start_ns == -1 for d in never.downlinks)
    with pytest.raises(ValueError):
        simulate_multi_downlinks(*args, dl_ready_ns=[-1] * (total - 1))


def test_uplinks_and_downlinks_share_one_mesh_pass(small, monkeypatch):
    """Montant et descente partagent une seule passe mesh : même temps d'antenne, même charge."""
    import lsim.trace_events as te

    calls = []
    real_pass = te.mesh_pass

    def spy(*args, **kwargs):
        mp = real_pass(*args, **kwargs)
        calls.append((len(args[3]), len(kwargs.get("downlinks", ())), mp))
        return mp

    monkeypatch.setattr(te, "mesh_pass", spy)
    build_multi_trace(small, ProtocolOptions(confirmed_uplinks=True, downlink_every=1))
    base, n_dl, mp = calls[-1]
    assert n_dl > 0, "aucune descente dans la passe finale"
    frame_ids = {h.frame_id for h in mp.mesh_result.hops}
    assert any(f < base for f in frame_ids) and any(f >= base for f in frame_ids)
    assert all(h.frame_id < base for h in mp.uplink_hops)
