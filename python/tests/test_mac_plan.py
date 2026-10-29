"""Calendrier MAC (phase 1) : règles par rang, réservations d'octets et encodage."""

import pytest

from lsim import mac
from lsim.mac import DevStatusReq, LinkCheckReq
from lsim.mac_plan import (
    MacSchedule,
    device_status_request_due,
    reserved_extra_bytes,
    reservations,
    uplink_fopts,
    uplink_requests,
)


def test_disabled_schedule_requests_and_reserves_nothing():
    s = MacSchedule()
    assert not s.enabled
    assert all(uplink_requests(s, n) == [] for n in range(1, 50))
    assert all(not device_status_request_due(s, n) for n in range(1, 50))
    assert all(reserved_extra_bytes(s, n) == 0 for n in range(1, 50))
    assert reservations(s, 49) == []


def test_link_check_every_three_uplinks():
    s = MacSchedule(link_check_every=3)
    assert [n for n in range(1, 13) if uplink_requests(s, n)] == [3, 6, 9, 12]
    assert uplink_requests(s, 3) == [LinkCheckReq()]


def test_device_status_request_is_decided_by_uplink_rank_not_by_uplink_content():
    s = MacSchedule(device_status_every=2)
    assert [n for n in range(1, 9) if device_status_request_due(s, n)] == [2, 4, 6, 8]
    # Jamais un DevStatusReq dans un uplink : c'est une commande de descente.
    assert all(uplink_requests(s, n) == [] for n in range(1, 20))


def test_link_check_reservation_is_certain_at_its_rank():
    s = MacSchedule(link_check_every=4)
    assert reserved_extra_bytes(s, 4) == 1
    assert reserved_extra_bytes(s, 5) == 0
    assert uplink_fopts(s, 4) == mac.encode(LinkCheckReq())


def test_device_status_answer_is_reserved_conservatively_in_the_next_uplink():
    # DevStatusAns = 3 octets, réservés dans l'uplink suivant chaque requête planifiée.
    s = MacSchedule(device_status_every=3)
    assert reserved_extra_bytes(s, 3) == 0          # la requête part après l'uplink 3, pas dedans
    assert reserved_extra_bytes(s, 4) == 3          # réservation conservatrice dans l'uplink 4
    assert reserved_extra_bytes(s, 5) == 0
    assert reserved_extra_bytes(s, 1) == 0          # rang 1 : aucune requête précédente


def test_both_reservations_add_up_and_stay_within_fopts():
    s = MacSchedule(link_check_every=4, device_status_every=3)
    assert reserved_extra_bytes(s, 4) == 1 + 3
    # LinkCheckReq aux rangs 4 et 8 ; requêtes planifiées aux rangs 3 et 6 -> réponses réservées
    # aux rangs 4 et 7. Rang 4 : 1 + 3 octets.
    assert reservations(s, 8) == [(4, 4), (7, 3), (8, 1)]
    # Dans tous les cas, la réservation tient dans les 15 octets de FOpts.
    assert all(reserved_extra_bytes(s, n) <= 15 for n in range(1, 200))


def test_reservations_list_matches_the_per_rank_rule():
    s = MacSchedule(link_check_every=5, device_status_every=4)
    got = reservations(s, 12)
    assert got == [(r, reserved_extra_bytes(s, r)) for r in range(1, 13)
                   if reserved_extra_bytes(s, r)]


def test_uplink_fopts_decode_as_uplink_commands():
    s = MacSchedule(link_check_every=1)
    fopts = uplink_fopts(s, 1)
    assert mac.decode_all(fopts, downlink=False) == [LinkCheckReq()]


def test_device_status_req_encodes_as_downlink_command():
    assert mac.decode_all(mac.encode(DevStatusReq()), downlink=True) == [DevStatusReq()]


def test_schedule_is_reproducible():
    s = MacSchedule(link_check_every=5, device_status_every=7)
    assert reservations(s, 200) == reservations(s, 200)


def test_bounds_and_input_types_are_refused():
    with pytest.raises(ValueError):
        MacSchedule(link_check_every=1001)
    with pytest.raises(ValueError):
        MacSchedule(device_status_every=-1)
    with pytest.raises(ValueError):
        MacSchedule(link_check_every=True)
    with pytest.raises(ValueError):
        MacSchedule(link_margin_installation_db=61)
    with pytest.raises(ValueError):
        uplink_requests(MacSchedule(link_check_every=1), 0)
    with pytest.raises(ValueError):
        reserved_extra_bytes(MacSchedule(device_status_every=1), 0)


def test_device_time_req_is_planned_and_reserved_at_its_rank():
    from lsim.mac import DeviceTimeReq
    s = MacSchedule(device_time_every=3)
    assert s.enabled
    assert [n for n in range(1, 10) if uplink_requests(s, n)] == [3, 6, 9]
    assert uplink_requests(s, 3) == [DeviceTimeReq()]
    assert reserved_extra_bytes(s, 3) == 1
    assert reserved_extra_bytes(s, 4) == 0


def test_link_check_and_device_time_share_an_uplink_in_cid_order():
    from lsim.mac import DeviceTimeReq
    s = MacSchedule(link_check_every=3, device_time_every=3)
    assert uplink_requests(s, 3) == [LinkCheckReq(), DeviceTimeReq()]
    assert reserved_extra_bytes(s, 3) == 2
    assert mac.decode_all(uplink_fopts(s, 3), downlink=False) == [LinkCheckReq(), DeviceTimeReq()]
