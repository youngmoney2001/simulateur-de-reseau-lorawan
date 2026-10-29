"""Plusieurs passerelles : réception indépendante et déduplication serveur (moteur natif)."""

import pytest

from lsim.simulator import (
    EndDevice,
    Gateway,
    Propagation,
    simulate_uplinks,
    simulate_uplinks_multi,
)


def test_second_gateway_rescues_far_device():
    dev = [EndDevice(x_m=20000.0)]
    solo = simulate_uplinks_multi(dev, [Gateway()], Propagation())
    assert solo.network.received == 0
    assert solo.network.lost_sensitivity == 1

    pair = simulate_uplinks_multi(dev, [Gateway(), Gateway(x_m=20000.0, y_m=100.0)], Propagation())
    assert pair.network.received == 1
    assert pair.network.lost_sensitivity == 0
    assert pair.per_gateway[0].lost_sensitivity == 1
    assert pair.per_gateway[1].received == 1


def test_duplicate_copies_are_delivered_once():
    res = simulate_uplinks_multi([EndDevice(x_m=10.0)],
                                 [Gateway(), Gateway(x_m=0.0, y_m=50.0)], Propagation())
    assert res.network.sent == 1
    assert res.network.received == 1
    assert res.network.duplicates == 1
    assert res.per_device[0].received == 1
    assert res.per_gateway[0].received == 1
    assert res.per_gateway[1].received == 1


def test_single_gateway_matches_single_path():
    devices = [EndDevice(x_m=100.0 + 4000.0 * k, y_m=50.0 * k, spreading_factor=7 + k % 3,
                         messages=3, period_ns=2_000_000_000, start_offset_ns=150_000_000 * k)
               for k in range(6)]
    single = simulate_uplinks(devices, Gateway(), Propagation())
    multi = simulate_uplinks_multi(devices, [Gateway()], Propagation())
    assert multi.network.sent == single.totals.sent
    assert multi.network.received == single.totals.received
    assert multi.network.lost_sensitivity == single.totals.lost_sensitivity
    assert multi.network.lost_collision == single.totals.lost_collision
    assert multi.network.duplicates == 0
    assert len(multi.per_device) == len(devices)


def test_gateway_count_bounds():
    with pytest.raises(ValueError):
        simulate_uplinks_multi([EndDevice(x_m=10.0)], [], Propagation())
    with pytest.raises(ValueError):
        simulate_uplinks_multi([EndDevice(x_m=10.0)], [Gateway()] * 65, Propagation())
