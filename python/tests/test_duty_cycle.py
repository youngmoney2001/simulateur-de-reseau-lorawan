"""Rapport cyclique par dispositif : décalage des émissions, validation, scénario."""

import pytest

from lsim.scenario import GroupModel
from lsim.simulator import EndDevice, Gateway, Propagation, simulate_uplinks


def test_duty_cycle_delays_next_frames():
    dev = EndDevice(x_m=10.0, messages=3, period_ns=100_000_000, duty_cycle=0.1)
    res = simulate_uplinks([dev], Gateway(), Propagation())
    a = res.per_device[0].airtime_ns // 3
    assert res.gateway.observation_ns == 21 * a


def test_default_duty_cycle_is_unlimited():
    dev = EndDevice(x_m=10.0, messages=3, period_ns=100_000_000)
    res = simulate_uplinks([dev], Gateway(), Propagation())
    a = res.per_device[0].airtime_ns // 3
    assert res.gateway.observation_ns == 200_000_000 + a


@pytest.mark.parametrize("value", [0.0, -0.1, 1.01, float("nan")])
def test_invalid_duty_cycle_rejected(value):
    with pytest.raises(ValueError):
        EndDevice(duty_cycle=value)


def test_scenario_group_duty_cycle_validated():
    assert GroupModel.model_fields["duty_cycle"].default == 1.0
    with pytest.raises(ValueError):
        GroupModel(name="g", count=1, placement={"type": "disk", "radius_m": 10},
                   duty_cycle=0.0)
