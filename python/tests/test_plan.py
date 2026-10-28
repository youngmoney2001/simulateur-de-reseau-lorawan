"""Plans régionaux : registre, US915 (RP002 §2.5), RX1 modulo 8, charges de file."""

import pytest

from lsim.plan import get_plan, plan_names
from lsim.us915 import US915


def test_registry_lists_both_regions():
    assert plan_names() == ["EU868", "US915"]
    assert get_plan("US915") is US915


def test_unknown_region_is_refused():
    with pytest.raises(ValueError):
        get_plan("AU915")


def test_us_channel_frequencies_rp002():
    assert US915.channel_index(902.3) == 0
    assert US915.channel_index(914.9) == 63
    assert US915.channel_index(903.0) == 64
    assert US915.channel_index(914.2) == 71
    with pytest.raises(ValueError):
        US915.channel_index(915.0)


def test_us_uplink_data_rates():
    assert US915.data_rate_index("SF10BW125") == 0
    assert US915.data_rate_index("SF7BW125") == 3
    assert US915.data_rate_index("SF8BW500") == 4
    with pytest.raises(ValueError):
        US915.data_rate_index("SF12BW125")     # réservé à EU868 (DR0 EU) : hors plan US


@pytest.mark.parametrize("tx_ch,freq", [(0, 923.3), (1, 923.9), (7, 927.5), (8, 923.3),
                                         (70, 926.9), (71, 927.5)])
def test_us_rx1_channel_is_tx_channel_modulo_8(tx_ch, freq):
    assert US915.rx1(0, tx_ch)[0] == pytest.approx(freq)


@pytest.mark.parametrize("tx_dr,rx1_datr", [
    (0, "SF10BW500"), (1, "SF9BW500"), (2, "SF8BW500"), (3, "SF7BW500"), (4, "SF7BW500"),
])
def test_us_rx1_data_rate_offset_zero(tx_dr, rx1_datr):
    # RP002 (RX1DROffset 0) : DR0→DR10, DR1→DR11, DR2→DR12, DR3→DR13, DR4→DR13.
    assert US915.rx1(tx_dr, 0)[1] == rx1_datr


def test_us_queue_limit_is_smallest_rx1_payload():
    assert US915.queue_payload_max == 222
    assert US915.dl_settings & 0x0F == 8          # RX2 par défaut DR8


def test_us_rejects_tx_channel_out_of_plan():
    with pytest.raises(ValueError):
        US915.rx1(0, 72)
