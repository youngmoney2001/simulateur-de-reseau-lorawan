"""Plan IN865-867 : canaux par défaut, débits, RX1, RX2, charges N, passerelle."""

import pytest

from lsim import basicstation
from lsim.in865 import IN865
from lsim.plan import get_plan, plan_names


def test_in865_is_registered_and_selectable():
    assert "IN865" in plan_names()
    assert get_plan("IN865") is IN865


def test_default_channels():
    assert IN865.channel_index(865.0625) == 0
    assert IN865.channel_index(865.4025) == 1
    assert IN865.channel_index(865.985) == 2
    with pytest.raises(ValueError):
        IN865.channel_index(866.3)          # canal étendu (CFList) : hors plan
    with pytest.raises(ValueError):
        IN865.rx1(0, 3)                     # indice de canal hors plan


@pytest.mark.parametrize("datr, dr", [
    ("SF12BW125", 0), ("SF11BW125", 1), ("SF10BW125", 2),
    ("SF9BW125", 3), ("SF8BW125", 4), ("SF7BW125", 5),
])
def test_uplink_and_downlink_data_rates(datr, dr):
    assert IN865.data_rate_index(datr) == dr
    assert IN865.dr_datr(dr) == datr


def test_no_dr6_in_in865():
    with pytest.raises(ValueError):
        IN865.dr_datr(6)
    with pytest.raises(ValueError):
        IN865.data_rate_index("SF7BW250")


@pytest.mark.parametrize("tx_dr, tx_ch, freq, rx1_datr", [
    (0, 0, 865.0625, "SF12BW125"),   # même canal, RX1DROffset 0
    (2, 1, 865.4025, "SF10BW125"),
    (5, 2, 865.985, "SF7BW125"),
])
def test_rx1_same_channel_same_data_rate(tx_dr, tx_ch, freq, rx1_datr):
    assert IN865.rx1(tx_dr, tx_ch) == (freq, rx1_datr)


def test_rx2_default_is_866_55_dr2():
    assert IN865.rx2() == (866_550_000, "SF10BW125")
    assert IN865.dl_settings == 0x82       # OptNeg, RX2DataRate 2


def test_max_payload_without_fopts_n_is_conservative():
    assert [IN865.max_frm_payload(dr) for dr in range(6)] == [51, 51, 51, 115, 222, 222]
    assert IN865.queue_payload_max == 51


def test_gateway_announces_default_channels():
    cfg = basicstation.router_config(IN865, net_id=0x000013, hwspec="sx1301/1")
    assert cfg["region"] == "IN865"
    assert cfg["freq_range"] == [865_062_500, 866_550_000]
    assert len(cfg["sx1301_conf"]) == 1
