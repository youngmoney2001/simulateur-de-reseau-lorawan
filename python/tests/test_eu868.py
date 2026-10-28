"""Plan EU868 (RP002-1.0.2) : débits, canaux par défaut, charges maximales, RX1."""

import pytest

from lsim import eu868


@pytest.mark.parametrize("datr,dr", [
    ("SF12BW125", 0), ("SF11BW125", 1), ("SF10BW125", 2), ("SF9BW125", 3),
    ("SF8BW125", 4), ("SF7BW125", 5), ("SF7BW250", 6),
])
def test_data_rate_table_matches_rp002_table_8(datr, dr):
    assert eu868.data_rate_index(datr) == dr


@pytest.mark.parametrize("datr", ["SF7BW500", "FSK50", "SF6BW125", ""])
def test_unknown_data_rate_is_refused(datr):
    with pytest.raises(ValueError):
        eu868.data_rate_index(datr)


def test_default_channels_are_868_10_868_30_868_50():
    assert [eu868.channel_index(f) for f in (868.1, 868.3, 868.5)] == [0, 1, 2]


def test_non_default_channel_is_refused():
    with pytest.raises(ValueError):
        eu868.channel_index(868.7)


def test_max_payload_without_fopts_repeater_compatible_table_12():
    assert [eu868.max_frm_payload(dr) for dr in range(7)] == [51, 51, 51, 115, 222, 222, 222]
    assert eu868.MAX_QUEUED_PAYLOAD == 51


def test_max_payload_rejects_dr_outside_plan():
    with pytest.raises(ValueError):
        eu868.max_frm_payload(7)


def test_receive_delay1_is_one_second():
    assert eu868.RECEIVE_DELAY1_US == 1_000_000
