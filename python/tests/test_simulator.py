"""Simulateur de liaisons montantes via le cœur natif."""

import pytest

from lsim import StatusError
from lsim.simulator import EndDevice, Gateway, Propagation, simulate_uplinks

MIN = 60_000_000_000


def test_single_close_device_is_received():
    r = simulate_uplinks([EndDevice(x_m=10.0)], Gateway(), Propagation())
    assert r.totals.sent == 1 and r.totals.received == 1
    assert r.per_device[0].received == 1


def test_far_device_is_below_sensitivity():
    r = simulate_uplinks([EndDevice(x_m=1_000_000.0)], Gateway(), Propagation())
    assert r.totals.lost_sensitivity == 1 and r.totals.received == 0


def test_equal_power_same_instant_collides():
    devs = [EndDevice(x_m=100.0), EndDevice(x_m=100.0)]
    r = simulate_uplinks(devs, Gateway(), Propagation())
    assert r.totals.lost_collision == 2 and r.totals.received == 0


def test_capture_keeps_strong_signal():
    devs = [EndDevice(x_m=10.0), EndDevice(x_m=1000.0)]
    r = simulate_uplinks(devs, Gateway(), Propagation())
    assert r.per_device[0].received == 1
    assert r.per_device[1].lost_collision == 1


def test_totals_are_sum_of_devices_and_deterministic():
    devs = [
        EndDevice(x_m=10.0 + 37.0 * i, spreading_factor=7 + i % 3,
                  start_offset_ns=1_000_000 * i, period_ns=2_000_000_000, messages=3)
        for i in range(50)
    ]
    a = simulate_uplinks(devs, Gateway(), Propagation())
    b = simulate_uplinks(devs, Gateway(), Propagation())
    assert a == b
    assert a.totals.sent == 150
    for field in ("sent", "received", "lost_sensitivity", "lost_collision"):
        assert getattr(a.totals, field) == sum(getattr(c, field) for c in a.per_device)


def test_empty_network():
    r = simulate_uplinks([], Gateway(), Propagation())
    assert r.totals.sent == 0 and r.per_device == ()


def test_native_rejects_invalid_spreading_factor_and_zeros_totals():
    # Entrée vérifiée côté Python ; on contourne le contrôle pour tester le natif.
    dev = EndDevice(x_m=10.0)
    object.__setattr__(dev, "spreading_factor", 13)
    with pytest.raises(StatusError) as err:
        simulate_uplinks([dev], Gateway(), Propagation())
    assert err.value.code == 301


def test_device_count_limit_refused_before_allocation():
    with pytest.raises(ValueError):
        simulate_uplinks([EndDevice()] * 10_001, Gateway(), Propagation())


def test_period_and_offset_validation():
    with pytest.raises(ValueError):
        EndDevice(period_ns=0)
    with pytest.raises(ValueError):
        EndDevice(start_offset_ns=-1)
    with pytest.raises(ValueError):
        Propagation(exponent=0.5)
