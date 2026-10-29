"""Calendrier des commandes MAC (phase 1) : sens, périodes, encodage et bornes."""

import pytest

from lsim import mac
from lsim.mac import DevStatusReq, LinkCheckReq
from lsim.mac_plan import (
    MacSchedule,
    downlink_fopts,
    downlink_requests,
    uplink_extra_bytes,
    uplink_fopts,
    uplink_requests,
)


def test_disabled_schedule_requests_nothing():
    s = MacSchedule()
    assert not s.enabled
    assert all(uplink_requests(s, n) == [] for n in range(1, 50))
    assert all(downlink_requests(s, n) == [] for n in range(1, 50))
    assert all(uplink_extra_bytes(s, n) == 0 for n in range(1, 50))


def test_link_check_every_three_uplinks():
    s = MacSchedule(link_check_every=3)
    got = [n for n in range(1, 13) if uplink_requests(s, n)]
    assert got == [3, 6, 9, 12]
    assert uplink_requests(s, 3) == [LinkCheckReq()]


def test_device_status_is_server_initiated_downlink_only():
    s = MacSchedule(device_status_every=2)
    assert [m for m in range(1, 7) if downlink_requests(s, m)] == [2, 4, 6]
    # Jamais un DevStatusReq dans un uplink : le dispositif ne peut pas l'émettre.
    assert all(uplink_requests(s, n) == [] for n in range(1, 20))
    assert downlink_fopts(s, 2) == mac.encode(DevStatusReq())


def test_uplink_fopts_decode_as_uplink_commands():
    s = MacSchedule(link_check_every=1)
    fopts = uplink_fopts(s, 1)
    assert mac.decode_all(fopts, downlink=False) == [LinkCheckReq()]
    assert uplink_extra_bytes(s, 1) == len(fopts) == 1


def test_downlink_fopts_decode_as_downlink_commands():
    s = MacSchedule(device_status_every=1)
    fopts = downlink_fopts(s, 1)
    assert mac.decode_all(fopts, downlink=True) == [DevStatusReq()]


def test_schedule_is_reproducible():
    s = MacSchedule(link_check_every=5, device_status_every=7)
    first = [(uplink_fopts(s, n), downlink_fopts(s, n)) for n in range(1, 200)]
    second = [(uplink_fopts(s, n), downlink_fopts(s, n)) for n in range(1, 200)]
    assert first == second


def test_bounds_and_input_types_are_refused():
    with pytest.raises(ValueError):
        MacSchedule(link_check_every=1001)
    with pytest.raises(ValueError):
        MacSchedule(device_status_every=-1)
    with pytest.raises(ValueError):
        MacSchedule(link_check_every=True)
    with pytest.raises(ValueError):
        uplink_requests(MacSchedule(link_check_every=1), 0)
    with pytest.raises(ValueError):
        downlink_requests(MacSchedule(device_status_every=1), 0)
