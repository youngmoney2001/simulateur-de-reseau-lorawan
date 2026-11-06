"""Boucle fermée S2 (pont Python) : parité sans commande avec le chemin causal S1, convergence ADR,
et refus des options invalides par le cœur."""

import pytest

from lsim.closed_loop import LoopOptions, LoopRegion, simulate_closed_loop
from lsim.downlink_plan import simulate_causal
from lsim.lora import StatusError
from lsim.simulator import EndDevice, Gateway, Propagation
from lsim.trace_events import DeviceRadio

S = 1_000_000_000
EU_REGION = LoopRegion(dr_sf=(12, 11, 10, 9, 8, 7) + (0,) * 10, max_dr=5, max_tx_power_index=7,
                       power_step_tenth_db=20)


def _radio():
    return DeviceRadio(freq_hz=868_100_000, dr=None, rx1_hz=868_100_000)


def test_no_command_parity_with_causal_path():
    devices = [EndDevice(x_m=100.0, period_ns=30 * S, messages=20),
               EndDevice(x_m=2500.0, spreading_factor=9, start_offset_ns=3 * S, period_ns=30 * S,
                         messages=20),
               EndDevice(x_m=900.0, start_offset_ns=7 * S, period_ns=30 * S, messages=20)]
    radios = [_radio(), _radio(), _radio()]
    gw, prop = Gateway(), Propagation()
    causal, busy = simulate_causal(devices, gw, prop, None, radios, LoopOptions())
    loop = simulate_closed_loop(devices, gw, prop, None, radios, [EU_REGION] * 3, LoopOptions())
    assert loop.downlinks == ()
    assert loop.busy == busy == ()
    assert loop.totals == causal.totals
    assert loop.per_device == causal.per_device
    assert len(loop.uplinks) == 60


def test_adr_converges_to_sf7_for_nearby_device():
    devices = [EndDevice(x_m=10.0, spreading_factor=12, period_ns=60 * S, messages=300)]
    out = simulate_closed_loop(devices, Gateway(), Propagation(), None, [_radio()], [EU_REGION],
                               LoopOptions(adr=True))
    assert out.uplinks[-1].spreading_factor == 7
    assert any(d.delivered and d.commands & 1 for d in out.downlinks)


def test_invalid_duty_cycle_exponent_is_refused_by_core():
    devices = [EndDevice(x_m=10.0, messages=2)]
    with pytest.raises(StatusError):
        simulate_closed_loop(devices, Gateway(), Propagation(), None, [_radio()], [EU_REGION],
                             LoopOptions(duty_cycle=True, duty_cycle_exponent=16))
