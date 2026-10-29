"""Plan EU868 (RP002-1.0.2 §2.4) : débits, canaux, charges, RX1, file."""

import pytest

from lsim.eu868 import EU868


@pytest.mark.parametrize("datr,dr", [
    ("SF12BW125", 0), ("SF11BW125", 1), ("SF10BW125", 2), ("SF9BW125", 3),
    ("SF8BW125", 4), ("SF7BW125", 5), ("SF7BW250", 6),
])
def test_data_rate_table_matches_rp002_table_8(datr, dr):
    assert EU868.data_rate_index(datr) == dr


@pytest.mark.parametrize("datr", ["SF7BW500", "FSK50", "SF6BW125", ""])
def test_unknown_data_rate_is_refused(datr):
    with pytest.raises(ValueError):
        EU868.data_rate_index(datr)


def test_default_channels_are_868_10_868_30_868_50():
    assert [EU868.channel_index(f) for f in (868.1, 868.3, 868.5)] == [0, 1, 2]


def test_non_default_channel_is_refused():
    with pytest.raises(ValueError):
        EU868.channel_index(868.7)


def test_max_payload_without_fopts_repeater_compatible_table_12():
    assert [EU868.max_frm_payload(dr) for dr in range(7)] == [51, 51, 51, 115, 222, 222, 222]
    assert EU868.queue_payload_max == 51


def test_max_payload_rejects_dr_outside_plan():
    with pytest.raises(ValueError):
        EU868.max_frm_payload(7)


def test_rx1_is_same_channel_and_same_data_rate():
    assert EU868.rx1(5, 0) == (868.1, "SF7BW125")
    assert EU868.rx1(6, 2) == (868.5, "SF7BW250")


def test_dl_settings_rx2_is_dr0():
    assert EU868.dl_settings & 0x0F == 0
