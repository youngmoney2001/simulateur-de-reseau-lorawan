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


# --- Puissance appliquée, et la convention qui l'exprime -----------------------------------------

def test_device_power_reduction_is_a_drop_not_an_absolute_level():
    """`reduction_db` est un écart, signé, jamais une puissance absolue.

    Un index plus haut est une puissance plus basse (`adr.cpp` : l'index monte tant qu'il
    reste de la marge). Une hausse donne donc une réduction **négative** — la cacher derrière
    une valeur absolue ferait perdre le sens de la commande.
    """
    from lsim.trace_events import DevicePower

    baisse = DevicePower(first_index=0, last_index=7, step_db=2.0)
    assert baisse.reduction_db == 14.0          # 7 crans de 2 dB retirés
    hausse = DevicePower(first_index=5, last_index=2, step_db=2.0)
    assert hausse.reduction_db == -6.0          # le serveur a rendu de la puissance
    assert DevicePower(first_index=3, last_index=3, step_db=2.0).reduction_db == 0.0


def _scenario_adr(mac=None):
    from lsim.scenario import Scenario, ScenarioModel
    raw = {"schema_version": 1, "name": "puissance", "seed": 1,
           "gateway": {"x_m": 0, "y_m": 0},
           "propagation": {"frequency_hz": 868100000, "exponent": 2.7},
           "groups": [{"name": "c", "count": 3, "placement": {"type": "disk", "radius_m": 120},
                       "spreading_factor": 12, "payload_bytes": 10, "tx_power_dbm": 14,
                       "period_s": 60, "messages": 130, "start_spread_s": 20,
                       "region": "EU868"}]}
    if mac is not None:
        raw["mac"] = mac
    return Scenario(ScenarioModel.model_validate(raw))


def test_adr_trace_carries_the_power_the_loop_applied():
    """Sans ADR, rien ne décide de puissance : le champ est absent, pas recopié."""
    from lsim.trace_events import build_trace

    sans = build_trace(_scenario_adr())
    assert sans.device_power is None, (
        "hors boucle fermée, annoncer une puissance ferait croire à une décision du serveur")

    avec = build_trace(_scenario_adr(mac={"link_adr": True}))
    assert avec.device_power is not None and len(avec.device_power) == 3
    for p in avec.device_power.values():
        assert p.step_db > 0
    assert max(p.reduction_db for p in avec.device_power.values()) > 0, (
        "sur un lien qui le permet, le serveur doit avoir retiré de la puissance")
