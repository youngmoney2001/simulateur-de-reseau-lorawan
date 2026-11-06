"""Frontal RF v4 (R2b) : sémantique, validation, routage et comptage unique du gain.

Ces tests portent sur le pont Python **et** sur le cœur natif : un test qui ne vérifierait que
les dataclasses ne prouverait pas que le bon symbole est appelé. Les tests de routage remplacent
les fonctions natives par des espions et vérifient nommément quel point d'entrée est atteint.
"""

import ctypes
from unittest import mock

import pytest

from lsim import _native
from lsim.closed_loop import LoopOptions, LoopRegion
from lsim.closed_loop_v3 import simulate_closed_loop_v3
from lsim.rf import (HAS_ANTENNA_GAIN, HAS_CABLE_LOSS, MAX_ANTENNA_GAIN_DBI, MAX_CABLE_LOSS_DB,
                     DeviceRf, GatewayRf)
from lsim.simulator import (DownlinkRule, EndDevice, Gateway, Propagation,
                            multi_dl_native_function, simulate_multi_downlinks,
                            simulate_uplinks_trace, trace_native_function)
from lsim.trace_events import DeviceRadio

PROPAGATION = Propagation(frequency_hz=868.1e6, reference_distance_m=1.0, exponent=2.7)
S = 1_000_000_000
EU_REGION = LoopRegion(dr_sf=(12, 11, 10, 9, 8, 7) + (0,) * 10, max_dr=5,
                       max_tx_power_index=7, power_step_tenth_db=20)

TRACE_SYMBOLS = ("lsim_simulate_uplinks_trace_v2", "lsim_simulate_uplinks_trace_gw2",
                 "lsim_simulate_uplinks_trace_v3", "lsim_simulate_uplinks_trace_gw2_v2")


def _device(distance_m=1000.0, tx_power_dbm=14.0, spreading_factor=9):
    return EndDevice(x_m=distance_m, spreading_factor=spreading_factor, messages=1,
                     tx_power_dbm=tx_power_dbm)


def _rssi(device_rf=None, gateway_rf=None, gateway=None, device=None):
    result = simulate_uplinks_trace([device or _device()], gateway or Gateway(), PROPAGATION,
                                    device_rf=device_rf, gateway_rf=gateway_rf)
    return result.records[0].rssi_dbm


# ---------------------------------------------------------------- 1. Sémantique des frontaux

def test_empty_frontend_has_no_field_and_a_zero_chain():
    assert DeviceRf().present == 0
    assert DeviceRf().chain_db() == 0.0
    assert GatewayRf().present == 0


def test_presence_bits_are_independent():
    assert DeviceRf(antenna_gain_dbi=3.0).present == HAS_ANTENNA_GAIN
    assert DeviceRf(cable_loss_db=1.0).present == HAS_CABLE_LOSS
    assert DeviceRf(antenna_gain_dbi=3.0, cable_loss_db=1.0).present == (
        HAS_ANTENNA_GAIN | HAS_CABLE_LOSS)


def test_none_is_not_zero():
    """Un champ absent n'est pas un zéro : `0 dBi` est une valeur fournie, `None` ne l'est pas."""
    assert DeviceRf(antenna_gain_dbi=0.0).present == HAS_ANTENNA_GAIN
    assert DeviceRf().present == 0
    assert DeviceRf(antenna_gain_dbi=0.0).chain_db() == 0.0
    assert DeviceRf().chain_db() == 0.0


def test_chain_is_gain_minus_loss():
    assert DeviceRf(antenna_gain_dbi=3.0, cable_loss_db=1.5).chain_db() == 1.5
    assert DeviceRf(cable_loss_db=2.0).chain_db() == -2.0


@pytest.mark.parametrize("value", [MAX_ANTENNA_GAIN_DBI + 0.1, -MAX_ANTENNA_GAIN_DBI - 0.1,
                                   float("nan"), float("inf")])
def test_gain_out_of_bounds_is_refused(value):
    with pytest.raises(ValueError):
        DeviceRf(antenna_gain_dbi=value)
    with pytest.raises(ValueError):
        GatewayRf(antenna_gain_dbi=value)


@pytest.mark.parametrize("value", [-0.1, MAX_CABLE_LOSS_DB + 0.1, float("nan")])
def test_loss_out_of_bounds_is_refused(value):
    with pytest.raises(ValueError):
        DeviceRf(cable_loss_db=value)
    with pytest.raises(ValueError):
        GatewayRf(cable_loss_db=value)


def test_frontend_refuses_non_numeric_values():
    with pytest.raises(ValueError):
        DeviceRf(antenna_gain_dbi="3")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        DeviceRf(antenna_gain_dbi=True)  # type: ignore[arg-type]


# ---------------------------------------------------------------- 2. Routage des symboles

def test_selector_names_the_v2_family_without_frontend():
    assert trace_native_function(rf=False, absolute=False) is _native.LIB.lsim_simulate_uplinks_trace_v2
    assert trace_native_function(rf=False, absolute=True) is _native.LIB.lsim_simulate_uplinks_trace_gw2


def test_selector_names_the_v4_family_with_frontend():
    assert trace_native_function(rf=True, absolute=False) is _native.LIB.lsim_simulate_uplinks_trace_v3
    assert trace_native_function(rf=True, absolute=True) is _native.LIB.lsim_simulate_uplinks_trace_gw2_v2


def test_multi_dl_selector_switches_only_with_a_frontend():
    assert multi_dl_native_function(rf=False) is _native.LIB.lsim_simulate_uplinks_multi_dl
    assert multi_dl_native_function(rf=True) is _native.LIB.lsim_simulate_uplinks_multi_dl_v2


def _spy_all_trace_symbols():
    """Remplace les quatre points d'entrée de trace par des espions qui comptent les appels."""
    spies = {}
    for name in TRACE_SYMBOLS:
        spies[name] = mock.patch.object(_native.LIB, name, wraps=getattr(_native.LIB, name))
    started = {name: patcher.start() for name, patcher in spies.items()}
    return started, spies


def _stop(spies):
    for patcher in spies.values():
        patcher.stop()


def test_a_frontend_routes_to_v3_and_never_touches_the_old_entry_point():
    started, spies = _spy_all_trace_symbols()
    try:
        _rssi(device_rf=[DeviceRf(antenna_gain_dbi=3.0)])
        assert started["lsim_simulate_uplinks_trace_v3"].call_count == 1
        assert started["lsim_simulate_uplinks_trace_v2"].call_count == 0
        assert started["lsim_simulate_uplinks_trace_gw2"].call_count == 0
        assert started["lsim_simulate_uplinks_trace_gw2_v2"].call_count == 0
    finally:
        _stop(spies)


def test_without_a_frontend_the_old_entry_point_is_used_and_v4_stays_silent():
    started, spies = _spy_all_trace_symbols()
    try:
        _rssi()
        assert started["lsim_simulate_uplinks_trace_v2"].call_count == 1
        assert started["lsim_simulate_uplinks_trace_v3"].call_count == 0
        assert started["lsim_simulate_uplinks_trace_gw2_v2"].call_count == 0
    finally:
        _stop(spies)


def test_gateway_frontend_alone_also_routes_to_v3():
    started, spies = _spy_all_trace_symbols()
    try:
        _rssi(gateway_rf=GatewayRf(antenna_gain_dbi=6.0))
        assert started["lsim_simulate_uplinks_trace_v3"].call_count == 1
        assert started["lsim_simulate_uplinks_trace_v2"].call_count == 0
    finally:
        _stop(spies)


def test_absolute_sensitivity_with_a_frontend_routes_to_gw2_v2():
    from lsim.gateway_sensitivity import AbsoluteSensitivity

    absolute = AbsoluteSensitivity(points=((125_000, 9, -134.0), (125_000, 12, -137.0)))
    gateway = Gateway(absolute_sensitivity=absolute)
    started, spies = _spy_all_trace_symbols()
    try:
        _rssi(device_rf=[DeviceRf(antenna_gain_dbi=1.0)], gateway=gateway)
        assert started["lsim_simulate_uplinks_trace_gw2_v2"].call_count == 1
        assert started["lsim_simulate_uplinks_trace_gw2"].call_count == 0
        assert started["lsim_simulate_uplinks_trace_v3"].call_count == 0
    finally:
        _stop(spies)


def test_rf_path_never_calls_a_mesh_symbol():
    """Séparation stricte : le RF LoRaWAN n'emprunte jamais les points d'entrée du mesh."""
    mesh_symbols = ("lsim_mesh_airtime_ns", "lsim_mesh_forward", "lsim_mesh_routes")
    patchers = {name: mock.patch.object(_native.LIB, name,
                                        wraps=getattr(_native.LIB, name)) for name in mesh_symbols}
    started = {name: p.start() for name, p in patchers.items()}
    try:
        _rssi(device_rf=[DeviceRf(antenna_gain_dbi=3.0)], gateway_rf=GatewayRf(cable_loss_db=1.0))
        assert all(fn.call_count == 0 for fn in started.values())
    finally:
        for p in patchers.values():
            p.stop()


# ---------------------------------------------------------------- 3. Effet mesuré sur le montant

def test_device_gain_and_loss_act_once_on_the_uplink():
    neutral = _rssi()
    assert _rssi(device_rf=[DeviceRf(antenna_gain_dbi=3.0)]) - neutral == pytest.approx(3.0, abs=1e-9)
    assert _rssi(device_rf=[DeviceRf(cable_loss_db=2.0)]) - neutral == pytest.approx(-2.0, abs=1e-9)
    assert _rssi(device_rf=[DeviceRf(antenna_gain_dbi=3.0, cable_loss_db=1.0)]) - neutral == \
        pytest.approx(2.0, abs=1e-9)


def test_gateway_frontend_replaces_the_scalar_gain():
    neutral = _rssi(gateway=Gateway(antenna_gain_dbi=0.0))
    assert _rssi(gateway_rf=GatewayRf(antenna_gain_dbi=6.0),
                 gateway=Gateway(antenna_gain_dbi=3.0)) - neutral == pytest.approx(6.0, abs=1e-9)
    assert _rssi(gateway_rf=GatewayRf(cable_loss_db=2.0),
                 gateway=Gateway(antenna_gain_dbi=3.0)) - neutral == pytest.approx(1.0, abs=1e-9)


def test_partial_tables_are_refused_before_the_native_call():
    devices = [_device(), _device()]
    with pytest.raises(ValueError):
        simulate_uplinks_trace(devices, Gateway(), PROPAGATION, device_rf=[DeviceRf()])
    with pytest.raises(ValueError):
        simulate_multi_downlinks(devices, [Gateway(), Gateway()], PROPAGATION,
                                 DownlinkRule(ack_uplinks=True), device_rf=[DeviceRf()])


# ---------------------------------------------------------------- 4. Descente : un seul comptage

def test_device_gain_is_counted_once_in_the_downlink():
    """Marge construite : perdue si la chaîne est comptée une fois, reçue si elle est doublée."""
    device = EndDevice(x_m=12000.0, spreading_factor=12, messages=3)
    rssi_up = simulate_uplinks_trace([device], Gateway(), PROPAGATION).records[0].rssi_dbm
    sens_sf12 = -136.0
    chain = 10.0
    offset = (rssi_up - 14.0 + 0.0 + chain) - sens_sf12 + 5.0

    rule = DownlinkRule(ack_uplinks=True, gateway_tx_power_dbm=0.0, device_rx_offset_db=offset,
                        device_antenna_gain_dbi=30.0)  # scalaire ignoré quand la table existe
    out = simulate_multi_downlinks([device], [Gateway()], PROPAGATION, rule,
                                   device_rf=[DeviceRf(antenna_gain_dbi=chain)])
    # 1 = sous la sensibilité.
    assert out.downlinks[0].outcome == 1

    rule_ok = DownlinkRule(ack_uplinks=True, gateway_tx_power_dbm=0.0,
                           device_antenna_gain_dbi=30.0)
    out_ok = simulate_multi_downlinks([device], [Gateway()], PROPAGATION, rule_ok,
                                      device_rf=[DeviceRf(antenna_gain_dbi=chain)])
    assert out_ok.downlinks[0].outcome == 0

    # Ancien contrat : même issue avec le gain scalaire de la règle, sans table.
    legacy = DownlinkRule(ack_uplinks=True, gateway_tx_power_dbm=0.0,
                          device_rx_offset_db=offset, device_antenna_gain_dbi=chain)
    out_legacy = simulate_multi_downlinks([device], [Gateway()], PROPAGATION, legacy)
    assert out_legacy.downlinks[0].outcome == 1


def test_multi_dl_routes_to_v2_and_ignores_the_old_symbol():
    real_v1 = _native.LIB.lsim_simulate_uplinks_multi_dl
    real_v2 = _native.LIB.lsim_simulate_uplinks_multi_dl_v2
    with mock.patch.object(_native.LIB, "lsim_simulate_uplinks_multi_dl",
                           wraps=real_v1) as old, \
         mock.patch.object(_native.LIB, "lsim_simulate_uplinks_multi_dl_v2", wraps=real_v2) as new:
        simulate_multi_downlinks([_device()], [Gateway()], PROPAGATION,
                                 DownlinkRule(ack_uplinks=True),
                                 device_rf=[DeviceRf(antenna_gain_dbi=3.0)])
        assert new.call_count == 1
        assert old.call_count == 0
        simulate_multi_downlinks([_device()], [Gateway()], PROPAGATION,
                                 DownlinkRule(ack_uplinks=True))
        assert new.call_count == 1
        assert old.call_count == 1


def test_gateway_table_is_read_per_gateway():
    devices = [_device(1000.0)]
    gateways = [Gateway(antenna_gain_dbi=0.0), Gateway(antenna_gain_dbi=0.0)]
    base = simulate_multi_downlinks(devices, gateways, PROPAGATION,
                                    DownlinkRule(ack_uplinks=True))
    gains = simulate_multi_downlinks(devices, gateways, PROPAGATION,
                                     DownlinkRule(ack_uplinks=True),
                                     gateway_rf=[GatewayRf(antenna_gain_dbi=0.0),
                                                 GatewayRf(antenna_gain_dbi=6.0)])
    # La meilleure passerelle est celle qui a le plus de gain : le RSSI montant doit bouger.
    assert gains.trace[0].best_rssi_dbm - base.trace[0].best_rssi_dbm == pytest.approx(6.0, abs=1e-9)


# ---------------------------------------------------------------- 5. Boucle fermée v4

def _loop_scenario(messages=3, x_m=80.0):
    devices = [EndDevice(x_m=x_m, spreading_factor=12, messages=messages)]
    radios = [DeviceRadio(freq_hz=868_100_000, dr=None, rx1_hz=868_100_000)]
    return devices, radios, [EU_REGION]


def test_closed_loop_v4_with_an_empty_frontend_reproduces_v3():
    devices, radios, regions = _loop_scenario()
    v3 = simulate_closed_loop_v3(devices, Gateway(), Propagation(), radios, regions, LoopOptions())
    v4 = simulate_closed_loop_v3(devices, Gateway(), Propagation(), radios, regions, LoopOptions(),
                                 device_rf=[DeviceRf()])
    assert [u.rssi_dbm for u in v3.uplinks] == [u.rssi_dbm for u in v4.uplinks]
    assert v3.per_device == v4.per_device
    assert v3.totals == v4.totals


def test_closed_loop_v4_applies_the_device_gain():
    devices, radios, regions = _loop_scenario()
    neutral = simulate_closed_loop_v3(devices, Gateway(), Propagation(), radios, regions,
                                      LoopOptions(), device_rf=[DeviceRf()])
    gagne = simulate_closed_loop_v3(devices, Gateway(), Propagation(), radios, regions,
                                    LoopOptions(), device_rf=[DeviceRf(antenna_gain_dbi=6.0)])
    assert gagne.uplinks[0].rssi_dbm - neutral.uplinks[0].rssi_dbm == pytest.approx(6.0, abs=1e-9)


def test_closed_loop_v4_is_reached_through_the_native_symbol():
    devices, radios, regions = _loop_scenario()
    real = _native.LIB.lsim_simulate_closed_loop_v4
    with mock.patch.object(_native.LIB, "lsim_simulate_closed_loop_v4", wraps=real) as v4:
        simulate_closed_loop_v3(devices, Gateway(), Propagation(), radios, regions, LoopOptions(),
                                device_rf=[DeviceRf(cable_loss_db=1.0)])
        assert v4.call_count == 1


def test_closed_loop_refuses_a_partial_device_table():
    devices, radios, regions = _loop_scenario()
    devices = devices + devices
    radios = radios + radios
    regions = regions + regions
    with pytest.raises(ValueError):
        simulate_closed_loop_v3(devices, Gateway(), Propagation(), radios, regions, LoopOptions(),
                                device_rf=[DeviceRf()])


# ---------------------------------------------------------------- 6. Conversions et égalités

def test_to_c_encodes_presence_and_leaves_absent_fields_at_zero():
    gain_only = DeviceRf(antenna_gain_dbi=3.0, cable_loss_db=None).to_c()
    assert gain_only.present == HAS_ANTENNA_GAIN
    assert gain_only.antenna_gain_dbi == 3.0
    assert gain_only.cable_loss_db == 0.0  # jamais lue : le bit est absent

    loss_only = DeviceRf(cable_loss_db=1.0).to_c()
    assert loss_only.present == HAS_CABLE_LOSS
    assert loss_only.antenna_gain_dbi == 0.0

    gw = GatewayRf(antenna_gain_dbi=6.0, cable_loss_db=0.5).to_c()
    assert gw.present == (HAS_ANTENNA_GAIN | HAS_CABLE_LOSS)
    assert (gw.antenna_gain_dbi, gw.cable_loss_db) == (6.0, 0.5)


def test_neutral_rf_table_is_bit_for_bit_equal_to_no_table():
    """Une table fournie mais neutre doit produire exactement le résultat historique."""
    devices = [_device(1000.0), _device(2000.0)]
    plain = simulate_uplinks_trace(devices, Gateway(), PROPAGATION)
    neutral = simulate_uplinks_trace(devices, Gateway(), PROPAGATION,
                                     device_rf=[DeviceRf(), DeviceRf()])
    assert plain.records == neutral.records
    assert plain.per_device == neutral.per_device
    assert plain.totals == neutral.totals


def test_zero_gain_frontend_replaces_a_nonzero_scalar():
    """`0.0` est une valeur fournie : elle remplace le scalaire, elle ne l'ignore pas."""
    device = EndDevice(x_m=12000.0, spreading_factor=12, messages=3)
    rule = DownlinkRule(ack_uplinks=True, gateway_tx_power_dbm=0.0, device_antenna_gain_dbi=10.0)
    with_zero = simulate_multi_downlinks([device], [Gateway()], PROPAGATION, rule,
                                         device_rf=[DeviceRf(antenna_gain_dbi=0.0)])
    legacy = simulate_multi_downlinks([device], [Gateway()], PROPAGATION, rule)
    # Le scalaire à 10 dB n'est plus appliqué : la descente devient plus faible.
    assert with_zero.downlinks[0].outcome != legacy.downlinks[0].outcome


def test_multi_dl_gateway_cable_loss_lowers_the_best_rssi():
    devices = [_device(1000.0)]
    gateways = [Gateway(antenna_gain_dbi=0.0), Gateway(antenna_gain_dbi=0.0)]
    base = simulate_multi_downlinks(devices, gateways, PROPAGATION, DownlinkRule(ack_uplinks=True))
    attenue = simulate_multi_downlinks(devices, gateways, PROPAGATION,
                                       DownlinkRule(ack_uplinks=True),
                                       gateway_rf=[GatewayRf(cable_loss_db=2.0),
                                                   GatewayRf(cable_loss_db=2.0)])
    assert attenue.trace[0].best_rssi_dbm - base.trace[0].best_rssi_dbm == pytest.approx(-2.0, abs=1e-9)


def test_multi_dl_refuses_a_partial_gateway_table():
    with pytest.raises(ValueError):
        simulate_multi_downlinks([_device()], [Gateway(), Gateway()], PROPAGATION,
                                 DownlinkRule(ack_uplinks=True),
                                 gateway_rf=[GatewayRf(antenna_gain_dbi=3.0)])


def test_closed_loop_gateway_frontend_is_applied():
    devices, radios, regions = _loop_scenario()
    neutral = simulate_closed_loop_v3(devices, Gateway(antenna_gain_dbi=0.0), Propagation(),
                                      radios, regions, LoopOptions())
    gain = simulate_closed_loop_v3(devices, Gateway(antenna_gain_dbi=0.0), Propagation(),
                                   radios, regions, LoopOptions(),
                                   gateway_rf=GatewayRf(antenna_gain_dbi=4.0))
    assert gain.uplinks[0].rssi_dbm - neutral.uplinks[0].rssi_dbm == pytest.approx(4.0, abs=1e-9)


def test_closed_loop_device_cable_loss_is_applied_once():
    devices, radios, regions = _loop_scenario()
    neutral = simulate_closed_loop_v3(devices, Gateway(), Propagation(), radios, regions,
                                      LoopOptions(), device_rf=[DeviceRf()])
    perdu = simulate_closed_loop_v3(devices, Gateway(), Propagation(), radios, regions,
                                    LoopOptions(), device_rf=[DeviceRf(cable_loss_db=2.0)])
    assert perdu.uplinks[0].rssi_dbm - neutral.uplinks[0].rssi_dbm == pytest.approx(-2.0, abs=1e-9)
