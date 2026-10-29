"""Plan KR920-923 (RP002-1.0.2 §2.8) : canaux par défaut, débits, RX1, RX2, charges N, passerelle."""

import pytest

from lsim import basicstation
from lsim.kr920 import KR920
from lsim.plan import get_plan, plan_names


def test_kr920_is_registered_and_selectable():
    assert "KR920" in plan_names()
    assert get_plan("KR920") is KR920


def test_default_channels_922_1_922_3_922_5():
    assert KR920.channel_index(922.1) == 0
    assert KR920.channel_index(922.3) == 1
    assert KR920.channel_index(922.5) == 2
    with pytest.raises(ValueError):
        KR920.channel_index(923.3)          # canal étendu (CFList) : hors plan
    with pytest.raises(ValueError):
        KR920.rx1(0, 3)                     # indice de canal hors plan


@pytest.mark.parametrize("datr, dr", [
    ("SF12BW125", 0), ("SF11BW125", 1), ("SF10BW125", 2),
    ("SF9BW125", 3), ("SF8BW125", 4), ("SF7BW125", 5),
])
def test_uplink_and_downlink_data_rates(datr, dr):
    assert KR920.data_rate_index(datr) == dr
    assert KR920.dr_datr(dr) == datr


def test_no_dr6_in_kr920():
    with pytest.raises(ValueError):
        KR920.dr_datr(6)
    with pytest.raises(ValueError):
        KR920.data_rate_index("SF7BW250")


@pytest.mark.parametrize("tx_dr, tx_ch, freq, rx1_datr", [
    (0, 0, 922.1, "SF12BW125"),   # même canal, RX1DROffset 0
    (2, 1, 922.3, "SF10BW125"),
    (5, 2, 922.5, "SF7BW125"),
])
def test_rx1_same_channel_same_data_rate(tx_dr, tx_ch, freq, rx1_datr):
    assert KR920.rx1(tx_dr, tx_ch) == (freq, rx1_datr)


def test_rx2_default_is_921_9_dr0():
    assert KR920.rx2() == (921_900_000, "SF12BW125")
    assert KR920.dl_settings == 0x80       # OptNeg, RX2DataRate 0


def test_max_payload_without_fopts_n_is_conservative():
    assert [KR920.max_frm_payload(dr) for dr in range(6)] == [51, 51, 51, 115, 222, 222]
    assert KR920.queue_payload_max == 51


def test_gateway_announces_three_default_channels():
    cfg = basicstation.router_config(KR920, net_id=0x000013, hwspec="sx1301/1")
    assert cfg["region"] == "KR920"
    assert cfg["freq_range"] == [921_900_000, 922_500_000]
    assert len(cfg["sx1301_conf"]) == 1
