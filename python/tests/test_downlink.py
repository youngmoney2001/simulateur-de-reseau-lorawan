"""Classes B et C : décodage GwSpecific, canal US902, dérive, downlinks via le moteur natif."""

import pytest

from lsim import class_b
from lsim.class_b import ClassBDevice, decode_beacon_full, us902_channel
from lsim.lora import StatusError
from lsim.simulator import (
    DeviceClass,
    DownlinkRequests,
    EndDevice,
    Gateway,
    Propagation,
    simulate_uplinks,
)

EU_BEACON = bytes.fromhex("00000000 02CCA27E 00012000008103DE55".replace(" ", ""))
US_BEACON = bytes.fromhex("000000" "000002CC" "A27E" "00" "012000008103" "00" "50D4")
SEC = 1_000_000_000


def test_gwspecific_eu_example():
    t, gw = decode_beacon_full(EU_BEACON, rfu_len=2, gw_rfu_len=0)
    assert t == 0xCC020000
    assert gw is not None and gw.has_coordinates and gw.info_desc == 0
    assert gw.latitude_deg == pytest.approx(8193 * 90 / 2**23)
    assert gw.longitude_deg == pytest.approx(229632 * 180 / 2**23)


def test_gwspecific_us_example():
    t, gw = decode_beacon_full(US_BEACON, rfu_len=3, gw_rfu_len=1)
    assert t == 0xCC020000
    assert gw is not None and gw.latitude_deg == pytest.approx(8193 * 90 / 2**23)


def test_gwspecific_crc_error_and_length():
    bad = bytearray(EU_BEACON)
    bad[9] ^= 0x01
    with pytest.raises(StatusError):
        decode_beacon_full(bytes(bad), rfu_len=2, gw_rfu_len=0)
    with pytest.raises(StatusError):
        decode_beacon_full(EU_BEACON[:12], rfu_len=2, gw_rfu_len=0)


def test_beacon_without_gwspecific():
    t, gw = decode_beacon_full(EU_BEACON[:8], rfu_len=2, gw_rfu_len=0)
    assert t == 0xCC020000 and gw is None


def test_us902_channel_hopping():
    assert us902_channel(0) == (0, 923_300_000)
    assert us902_channel(128) == (1, 923_900_000)
    assert us902_channel(7 * 128) == (7, 927_500_000)
    assert us902_channel(8 * 128) == (0, 923_300_000)


def test_drift_widens_ping_window_and_validates():
    d = ClassBDevice(dev_addr=0, periodicity=7, clock_drift_ppm=10).on_beacon(0, 0)
    slot = d.next_ping_slot(0)
    assert slot.window_half_ns == -(-slot.start_ns * 10 // 1_000_000)
    assert ClassBDevice(dev_addr=0, periodicity=7).on_beacon(0, 0).next_ping_slot(0).window_half_ns == 0
    with pytest.raises(ValueError):
        ClassBDevice(dev_addr=0, clock_drift_ppm=1001)


def test_downlink_requests_validation():
    with pytest.raises(ValueError):
        DownlinkRequests(device_class=5, count=1)
    with pytest.raises(ValueError):
        DownlinkRequests(device_class=DeviceClass.A, count=2, request_period_ns=0)
    with pytest.raises(ValueError):
        DownlinkRequests(device_class=DeviceClass.B, count=1, periodicity=8)
    with pytest.raises(ValueError):
        DownlinkRequests(device_class=DeviceClass.A, count=1, rx_window_ns=11 * SEC)


def _device(cls, **kw):
    return EndDevice(
        x_m=100.0, y_m=0.0, messages=3, period_ns=60 * SEC,
        downlink=DownlinkRequests(device_class=cls, count=1, first_request_ns=10 * SEC, **kw),
    )


def test_engine_class_c_is_immediate_and_class_a_waits_for_uplink():
    gw, prop = Gateway(), Propagation()
    res = simulate_uplinks([_device(DeviceClass.C)], gw, prop)
    assert res.downlink_totals.delivered == 1
    assert res.downlink_per_device[0].latency_sum_ns == 0

    res = simulate_uplinks([_device(DeviceClass.A)], gw, prop)
    lat = res.downlink_per_device[0].latency_sum_ns
    assert 51 * SEC <= lat < 52 * SEC  # prochain uplink à 60 s, RX1 à 1 s après la fin


def test_engine_class_b_latency_matches_ping_slot():
    res = simulate_uplinks([_device(DeviceClass.B, periodicity=7)], Gateway(), Propagation())
    expected = class_b.ping_offset(0, 0, 7)
    slot0 = 2_120_000_000 + expected * 30_000_000
    assert res.downlink_per_device[0].latency_sum_ns == slot0 - 10 * SEC


def test_engine_without_downlink_keeps_counters_zero():
    res = simulate_uplinks([EndDevice(x_m=100.0)], Gateway(), Propagation())
    assert res.downlink_totals.requested == 0
    assert res.totals.sent == 1
