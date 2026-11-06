"""Intégration native de `lsim_simulate_closed_loop_v3` (ABI v3, étape 6.3).

Chaque test appelle la bibliothèque compilée chargée par `lsim._native` (LSIM_LIBRARY ou build/).
Les tests de structures comparent les tailles et décalages à ceux des `static_assert` de
`core/tests/test_abi_v3_prep.cpp` et de `core/tests/test_closed_loop_v3_api.cpp`. Un test
Pydantic seul n'est pas une preuve de branchement natif.
"""

import ctypes
import os
from unittest import mock

import pytest

from lsim import _native
from lsim.closed_loop import LoopOptions, LoopRegion, MacSlot, simulate_closed_loop
from lsim.closed_loop_v3 import (
    ChannelConfigV3,
    _CChannelDeviceV3,
    _CChannelTerminalV3,
    _CClosedLoopV3Args,
    _CLoopTraceV3,
    simulate_closed_loop_v3,
)
from lsim.lora import StatusError
from lsim.simulator import EndDevice, Gateway, Propagation
from lsim.trace_events import DeviceRadio

S = 1_000_000_000
EU_REGION = LoopRegion(dr_sf=(12, 11, 10, 9, 8, 7) + (0,) * 10, max_dr=5, max_tx_power_index=7,
                       power_step_tenth_db=20)

# Codes natifs (c_api.h).
ST_TRACE_TOO_SMALL_UPLINK = 300 + 8
ST_CHANNEL_TRACE_TOO_SMALL = 1016
ST_CHANNEL_ENABLED_UNDEFINED = 1012
ST_CHANNEL_DR_MASK_INVALID = 1011


def _radio():
    return DeviceRadio(freq_hz=868_100_000, dr=None, rx1_hz=868_100_000)


def _scenario(messages=130, n=1, x_m=80.0):
    devices = [EndDevice(x_m=x_m + 40.0 * i, spreading_factor=12, start_offset_ns=20 * S * i,
                         period_ns=60 * S, messages=messages) for i in range(n)]
    return devices, [_radio() for _ in range(n)], [EU_REGION] * n


# --- Chargement et structures -----------------------------------------------------------------

def test_native_symbol_is_exported_and_callable():
    fn = _native.LIB.lsim_simulate_closed_loop_v3
    assert fn.restype is ctypes.c_int32
    assert len(fn.argtypes) == 1


def test_library_loaded_is_the_compiled_core_and_exports_the_symbol():
    path = os.path.realpath(_native.LIB._name)
    assert os.path.basename(path) == "liblsim_core.so" or os.path.basename(path).startswith("liblsim_core")
    assert os.path.exists(path)
    # Résolution du symbole exporté : l'accès à l'attribut lève AttributeError si le symbole manque.
    assert callable(_native.LIB.lsim_simulate_closed_loop_v3)


def test_python_call_reaches_the_native_symbol_with_v3_header():
    devices, radios, regions = _scenario(messages=2, n=1)
    real = _native.LIB.lsim_simulate_closed_loop_v3
    seen = {}

    def spy(args):
        seen["abi"] = args.contents.abi_version
        seen["size"] = args.contents.struct_size
        return real(args)

    with mock.patch.object(_native.LIB, "lsim_simulate_closed_loop_v3", side_effect=spy) as fn:
        out = simulate_closed_loop_v3(devices, Gateway(), Propagation(), radios, regions, LoopOptions())
    assert fn.call_count == 1
    assert seen == {"abi": 3, "size": 272}
    assert len(out.uplinks) == 2


def test_structure_sizes_match_c_static_asserts():
    assert ctypes.sizeof(_CChannelDeviceV3) == 128
    assert ctypes.sizeof(_CChannelTerminalV3) == 112
    assert ctypes.sizeof(_CLoopTraceV3) == 40
    assert ctypes.sizeof(_CClosedLoopV3Args) == 272


def test_structure_offsets_match_c_static_asserts():
    a = _CClosedLoopV3Args
    assert a.reserved1.offset == 28
    assert a.devices.offset == 32
    assert a.mac.offset == 96
    assert a.channels.offset == 112
    assert a.channel_count.offset == 120
    assert a.mac_counters.offset == 216
    assert a.trace.offset == 224
    assert a.trace_count.offset == 240
    assert a.terminals.offset == 248
    assert a.terminal_count.offset == 264
    assert _CChannelDeviceV3.dr_mask.offset == 16
    assert _CChannelDeviceV3.enabled.offset == 96
    assert _CChannelDeviceV3.server_defined.offset == 106
    assert _CChannelDeviceV3.reserved.offset == 116
    assert _CChannelTerminalV3.dr_mask.offset == 16
    assert _CChannelTerminalV3.enabled.offset == 96
    assert _CChannelTerminalV3.reserved1.offset == 106
    t = _CLoopTraceV3
    assert t.downlink.offset == 16 and t.kind.offset == 20 and t.flag.offset == 32
    assert t.reserved.offset == 36


# --- Parité historique -------------------------------------------------------------------------

def test_historical_mode_matches_v2_outcome():
    devices, radios, regions = _scenario(messages=130, n=2)
    opts = LoopOptions(adr=True, downlink_every=1)
    v2 = simulate_closed_loop(devices, Gateway(), Propagation(), None, radios, regions, opts, abi=2)
    v3 = simulate_closed_loop_v3(devices, Gateway(), Propagation(), radios, regions, opts)
    assert v3.per_device == v2.per_device
    assert v3.totals == v2.totals
    assert v3.uplinks == v2.uplinks
    assert v3.downlinks == v2.downlinks
    assert v3.busy == v2.busy
    assert v3.mac_queue == v2.mac_queue
    assert v3.trace == ()


def test_explicit_defaults_match_historical_with_trace():
    devices, radios, regions = _scenario(messages=130, n=2)
    opts = LoopOptions(adr=True, downlink_every=1)
    hist = simulate_closed_loop_v3(devices, Gateway(), Propagation(), radios, regions, opts, trace=True)
    defaults = [
        ChannelConfigV3(device=i, dr_masks={0: 0x3F, 1: 0x3F, 2: 0x3F}, enabled=(0, 1, 2),
                        server_defined=(0, 1, 2))
        for i in range(2)
    ]
    explicit = simulate_closed_loop_v3(devices, Gateway(), Propagation(), radios, regions, opts,
                                       channels=defaults, trace=True)
    assert explicit.per_device == hist.per_device
    assert explicit.uplinks == hist.uplinks
    assert explicit.downlinks == hist.downlinks
    assert explicit.trace == hist.trace


def test_trace_does_not_change_results():
    devices, radios, regions = _scenario(messages=40, n=2)
    opts = LoopOptions(adr=True, downlink_every=1)
    plain = simulate_closed_loop_v3(devices, Gateway(), Propagation(), radios, regions, opts)
    traced = simulate_closed_loop_v3(devices, Gateway(), Propagation(), radios, regions, opts, trace=True)
    assert plain.uplinks == traced.uplinks
    assert plain.downlinks == traced.downlinks
    assert plain.totals == traced.totals
    assert plain.trace == ()
    assert len(traced.trace) > 0


# --- Configuration canal, état terminal et ADR -------------------------------------------------

def test_adr_success_updates_terminal_state_and_trace():
    devices, radios, regions = _scenario(messages=130, n=1)
    out = simulate_closed_loop_v3(devices, Gateway(), Propagation(), radios, regions,
                                  LoopOptions(adr=True, downlink_every=1), trace=True)
    kinds = {e.kind for e in out.trace}
    assert {"uplink", "adr_decision", "link_adr_req", "downlink", "apply", "link_adr_ans"} <= kinds
    assert any(e.kind == "apply" and e.flag for e in out.trace)
    assert out.terminals[0].dr > 0
    for e in out.trace:
        if e.kind == "link_adr_ans":
            assert e.flag == (e.status == 0x07)
        if e.kind == "link_adr_req":
            assert e.flag is False and e.value == 0
        if e.kind != "downlink":
            assert e.loss == "none"
        if e.kind not in ("link_adr_ans", "apply"):
            assert e.status is None


def test_adr_refusal_creates_exclusion_and_keeps_low_data_rates():
    devices, radios, regions = _scenario(messages=130, n=1)
    refusing = ChannelConfigV3(device=0, dr_masks={0: 0x03, 1: 0x03, 2: 0x03}, enabled=(0, 1, 2),
                               server_defined=(0, 1, 2))
    out = simulate_closed_loop_v3(devices, Gateway(), Propagation(), radios, regions,
                                  LoopOptions(adr=True, downlink_every=1), channels=[refusing], trace=True)
    assert any(e.kind == "exclusion" and e.target == "data_rate" for e in out.trace)
    assert out.terminals[0].dr <= 1
    assert out.terminals[0].dr_masks == {0: 0x03, 1: 0x03, 2: 0x03}


def test_terminals_have_distinct_states_and_server_view_is_not_terminal_state():
    devices, radios, regions = _scenario(messages=2, n=3)
    channels = [
        ChannelConfigV3(device=0, dr_masks={0: 0x3F, 1: 0x3F, 2: 0x3F, 3: 0x3F}, enabled=(0, 1, 2),
                        server_defined=(0, 1, 2, 5)),
        ChannelConfigV3(device=1, dr_masks={c: 0x3F for c in range(6)}, enabled=(3, 4, 5),
                        server_defined=(3, 4, 5)),
    ]
    out = simulate_closed_loop_v3(devices, Gateway(), Propagation(), radios, regions,
                                  LoopOptions(), channels=channels)
    t0, t1, t2 = out.terminals
    assert t0.dr_masks == {0: 0x3F, 1: 0x3F, 2: 0x3F, 3: 0x3F}
    assert 5 not in t0.dr_masks           # vue serveur seule : pas dans l'état terminal
    assert t0.enabled == (0, 1, 2)
    assert t1.enabled == (3, 4, 5)
    assert t2.dr_masks == {0: 0x3F, 1: 0x3F, 2: 0x3F}   # dispositif absent : défauts moteur
    assert t2.enabled == (0, 1, 2)


def test_invalid_channel_configuration_is_refused_by_core_with_status():
    devices, radios, regions = _scenario(messages=2, n=1)
    bad = ChannelConfigV3(device=0, dr_masks={0: 0x01}, enabled=(5,), server_defined=(0,))
    with pytest.raises(StatusError) as err:
        simulate_closed_loop_v3(devices, Gateway(), Propagation(), radios, regions, LoopOptions(),
                                channels=[bad])
    assert err.value.code == ST_CHANNEL_ENABLED_UNDEFINED


def test_dr_mask_above_region_maximum_is_refused():
    devices, radios, regions = _scenario(messages=2, n=1)
    bad = ChannelConfigV3(device=0, dr_masks={0: 0x40}, enabled=(0,), server_defined=(0,))
    with pytest.raises(StatusError) as err:
        simulate_closed_loop_v3(devices, Gateway(), Propagation(), radios, regions, LoopOptions(),
                                channels=[bad])
    assert err.value.code == ST_CHANNEL_DR_MASK_INVALID


# --- Capacités et erreurs ----------------------------------------------------------------------

def test_uplink_capacity_error_raises_status_and_returns_nothing():
    devices, radios, regions = _scenario(messages=10, n=1)
    with pytest.raises(StatusError) as err:
        simulate_closed_loop_v3(devices, Gateway(), Propagation(), radios, regions, LoopOptions(),
                                capacity=1)
    assert err.value.code == ST_TRACE_TOO_SMALL_UPLINK


def test_trace_capacity_error_raises_channel_status():
    devices, radios, regions = _scenario(messages=40, n=1)
    with pytest.raises(StatusError) as err:
        simulate_closed_loop_v3(devices, Gateway(), Propagation(), radios, regions,
                                LoopOptions(adr=True), trace=True, trace_capacity=3)
    assert err.value.code == ST_CHANNEL_TRACE_TOO_SMALL


def test_too_many_devices_is_refused_before_native_call():
    devices, radios, regions = _scenario(messages=1, n=1)
    many = devices * 10_001
    with pytest.raises(ValueError):
        simulate_closed_loop_v3(many, Gateway(), Propagation(), radios * 10_001,
                                regions * 10_001, LoopOptions())


def test_channel_index_outside_native_array_is_refused_in_python():
    devices, radios, regions = _scenario(messages=1, n=1)
    bad = ChannelConfigV3(device=0, dr_masks={0: 1}, enabled=(80,), server_defined=(0,))
    with pytest.raises(ValueError):
        simulate_closed_loop_v3(devices, Gateway(), Propagation(), radios, regions, LoopOptions(),
                                channels=[bad])


def test_mac_counters_invariants_on_native_outcome():
    devices, radios, regions = _scenario(messages=20, n=2)
    mac = [MacSlot(device=0, rank=1, extra_bytes=0, flags=1), MacSlot(device=0, rank=2, extra_bytes=0, flags=2)]
    out = simulate_closed_loop_v3(devices, Gateway(), Propagation(), radios, regions,
                                  LoopOptions(adr=True, downlink_every=1), mac=mac)
    q = out.mac_queue
    assert q.enqueued == q.dispatched + q.expired + q.pending_at_end
    assert q.dispatched == q.delivered + q.dispatch_lost
