"""Passerelles multiples avec downlinks : invariants du point fixe et demi-duplex par passerelle."""

from lsim.multi_trace import simulate_multi_with_downlinks
from lsim.simulator import EndDevice, Gateway, Propagation, simulate_uplinks_multi
from lsim.trace_events import ProtocolOptions


def _fleet(n=120):
    return [EndDevice(x_m=50.0 * k + 10.0, y_m=(k % 7) * 30.0, messages=8,
                      period_ns=60_000_000_000, start_offset_ns=k * 37_000_000)
            for k in range(n)]


GATEWAYS = [Gateway(), Gateway(x_m=3000.0, y_m=0.0), Gateway(x_m=6000.0, y_m=300.0)]


def test_no_downlink_matches_plain_multi_gateway():
    devs = _fleet()
    run = simulate_multi_with_downlinks(devs, GATEWAYS, Propagation(), None, ProtocolOptions())
    plain = simulate_uplinks_multi(devs, GATEWAYS, Propagation())
    assert run.downlinks == ()
    assert all(per == () or per == [] for per in run.gateway_tx)
    assert run.result.network == plain.network


def test_responder_is_not_transmitting_during_reception():
    devs = _fleet()
    run = simulate_multi_with_downlinks(devs, GATEWAYS, Propagation(), None,
                                        ProtocolOptions(confirmed_uplinks=True, downlink_every=2))
    assert run.downlinks, "scénario sans downlink : test sans portée"
    for r in run.result.trace:
        if r.outcome == 2:
            # Une trame décodée n'a pas été reçue pendant une émission de sa passerelle répondante.
            for a, b in run.gateway_tx[r.best_gateway]:
                assert not (a < r.end_ns and r.start_ns < b)


def test_each_gateway_serialises_its_downlinks():
    devs = _fleet()
    run = simulate_multi_with_downlinks(devs, GATEWAYS, Propagation(), None,
                                        ProtocolOptions(confirmed_uplinks=True, downlink_every=1))
    for per in run.gateway_tx:
        ordered = sorted(per)
        for (_, end_a), (start_b, _) in zip(ordered, ordered[1:]):
            assert end_a <= start_b


def _spread_fleet():
    """Trafic étalé sur la période : les downlinks tombent sur des émissions d'autres dispositifs."""
    return [EndDevice(x_m=20.0 * (k % 10), y_m=20.0 * (k // 10), messages=20,
                      period_ns=3_000_000_000, start_offset_ns=70_000_000 * k)
            for k in range(60)]


def test_duplex_costs_receptions_and_is_counted_per_gateway():
    devs = _spread_fleet()
    gws = [Gateway(), Gateway(x_m=60.0, y_m=40.0)]
    base = simulate_multi_with_downlinks(devs, gws, Propagation(), None, ProtocolOptions())
    busy = simulate_multi_with_downlinks(devs, gws, Propagation(), None,
                                         ProtocolOptions(confirmed_uplinks=True, downlink_every=1))
    assert base.result.network.lost_gateway_busy == 0
    assert busy.result.network.received <= base.result.network.received
    # Deux passerelles proches : une trame bloquée à l'une est souvent décodée par l'autre
    # (diversité). Le demi-duplex se voit donc par passerelle.
    assert sum(g.lost_gateway_busy for g in busy.result.per_gateway) > 0
    assert busy.result.network.lost_gateway_busy <= sum(
        g.lost_gateway_busy for g in busy.result.per_gateway)
    # Passerelle unique : la perte réseau due au demi-duplex doit apparaître.
    alone = simulate_multi_with_downlinks(devs, [Gateway()], Propagation(), None,
                                          ProtocolOptions(confirmed_uplinks=True, downlink_every=1))
    assert alone.result.network.lost_gateway_busy > 0


def test_fixed_point_oscillation_scenario_now_converges():
    # Scénario qui faisait osciller l'ancienne itération (pas de point fixe en 12 tours).
    devs = [EndDevice(x_m=20.0 * (k % 10), y_m=20.0 * (k // 10), messages=20,
                      period_ns=3_000_000_000, start_offset_ns=150_000_000 * k)
            for k in range(40)]
    run = simulate_multi_with_downlinks(devs, [Gateway(), Gateway(x_m=60.0, y_m=40.0)],
                                        Propagation(), None,
                                        ProtocolOptions(confirmed_uplinks=True, downlink_every=2))
    n = run.result.network
    assert n.received + n.lost_sensitivity + n.lost_collision + n.lost_gateway_busy == n.sent
    assert run.downlinks
