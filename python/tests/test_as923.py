"""Plan AS923 (RP002-1.0.2 §2.7) : canaux par défaut, débits, RX1, RX2, charges N, passerelle."""

import pytest

from lsim import basicstation
from lsim.as923 import AS923
from lsim.plan import get_plan, plan_names


def test_as923_is_registered_and_selectable():
    assert "AS923" in plan_names()
    assert get_plan("AS923") is AS923


def test_default_channels_923_2_and_923_4():
    assert AS923.channel_index(923.2) == 0
    assert AS923.channel_index(923.4) == 1
    with pytest.raises(ValueError):
        AS923.channel_index(923.6)          # pas de CFList : canal hors plan
    with pytest.raises(ValueError):
        AS923.rx1(0, 2)                     # indice de canal hors plan


@pytest.mark.parametrize("datr, dr", [
    ("SF12BW125", 0), ("SF11BW125", 1), ("SF10BW125", 2), ("SF9BW125", 3),
    ("SF8BW125", 4), ("SF7BW125", 5), ("SF7BW250", 6),
])
def test_uplink_data_rates(datr, dr):
    assert AS923.data_rate_index(datr) == dr
    assert AS923.dr_datr(dr) == datr


def test_fsk_dr7_is_not_managed():
    with pytest.raises(ValueError):
        AS923.dr_datr(7)
    with pytest.raises(ValueError):
        AS923.data_rate_index("FSK")


@pytest.mark.parametrize("tx_dr, tx_ch, freq, rx1_datr", [
    (0, 0, 923.2, "SF12BW125"),   # même canal, RX1DROffset 0
    (0, 1, 923.4, "SF12BW125"),
    (5, 1, 923.4, "SF7BW125"),
    (6, 0, 923.2, "SF7BW250"),
])
def test_rx1_same_channel_same_data_rate(tx_dr, tx_ch, freq, rx1_datr):
    assert AS923.rx1(tx_dr, tx_ch) == (freq, rx1_datr)


def test_rx2_default_is_923_2_dr2():
    assert AS923.rx2() == (923_200_000, "SF10BW125")
    assert AS923.dl_settings == 0x82       # OptNeg, RX2DataRate 2


def test_max_payload_without_fopts_n():
    # N = M - 8 ; M = 59, 59, 59, 123, 230, 230, 230 (RP002-1.0.2 tableau 53)
    assert [AS923.max_frm_payload(dr) for dr in range(7)] == [51, 51, 51, 115, 222, 222, 222]
    assert AS923.queue_payload_max == 51   # plus petite N des fenêtres RX1 atteignables


def test_gateway_announces_both_default_channels():
    cfg = basicstation.router_config(AS923, net_id=0x000013, hwspec="sx1301/1")
    assert cfg["region"] == "AS923"
    assert cfg["freq_range"] == [923_200_000, 923_400_000]
    assert len(cfg["sx1301_conf"]) == 1
