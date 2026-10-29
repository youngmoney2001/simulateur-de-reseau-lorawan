"""Plan RU864-870 : canaux par défaut, débits, RX1, RX2, charges N, passerelle."""

import pytest

from lsim import basicstation
from lsim.plan import get_plan, plan_names
from lsim.ru864 import RU864


def test_ru864_is_registered_and_selectable():
    assert "RU864" in plan_names()
    assert get_plan("RU864") is RU864


def test_default_channels_868_9_and_869_1():
    assert RU864.channel_index(868.9) == 0
    assert RU864.channel_index(869.1) == 1
    with pytest.raises(ValueError):
        RU864.channel_index(868.3)          # canal EU868 : hors plan RU864
    with pytest.raises(ValueError):
        RU864.rx1(0, 2)                     # indice de canal hors plan


@pytest.mark.parametrize("datr, dr", [
    ("SF12BW125", 0), ("SF11BW125", 1), ("SF10BW125", 2),
    ("SF9BW125", 3), ("SF8BW125", 4), ("SF7BW125", 5),
])
def test_uplink_and_downlink_data_rates(datr, dr):
    assert RU864.data_rate_index(datr) == dr
    assert RU864.dr_datr(dr) == datr


def test_dr6_not_retained():
    with pytest.raises(ValueError):
        RU864.dr_datr(6)
    with pytest.raises(ValueError):
        RU864.data_rate_index("SF7BW250")


@pytest.mark.parametrize("tx_dr, tx_ch, freq, rx1_datr", [
    (0, 0, 868.9, "SF12BW125"),   # même canal, RX1DROffset 0
    (3, 1, 869.1, "SF9BW125"),
    (5, 0, 868.9, "SF7BW125"),
])
def test_rx1_same_channel_same_data_rate(tx_dr, tx_ch, freq, rx1_datr):
    assert RU864.rx1(tx_dr, tx_ch) == (freq, rx1_datr)


def test_rx2_default_is_869_1_dr0():
    assert RU864.rx2() == (869_100_000, "SF12BW125")
    assert RU864.dl_settings == 0x80       # OptNeg, RX2DataRate 0


def test_max_payload_without_fopts_n():
    assert [RU864.max_frm_payload(dr) for dr in range(6)] == [51, 51, 51, 115, 222, 222]
    assert RU864.queue_payload_max == 51


def test_gateway_announces_both_default_channels():
    cfg = basicstation.router_config(RU864, net_id=0x000013, hwspec="sx1301/1")
    assert cfg["region"] == "RU864"
    assert cfg["freq_range"] == [868_900_000, 869_100_000]
    assert len(cfg["sx1301_conf"]) == 1
