"""Plan AU915-928 (RP002) : canaux, débits, RX1, file, et parcours complet de données."""

import pytest

from lsim.au915 import AU915
from lsim.plan import get_plan, plan_names
from test_uplink import DEV, Env, open_dl, up


def test_registry_has_au915():
    assert "AU915" in plan_names()
    assert get_plan("AU915") is AU915


@pytest.mark.parametrize("freq,index", [(915.2, 0), (927.8, 63), (915.9, 64), (927.1, 71)])
def test_au_channel_frequencies(freq, index):
    assert AU915.channel_index(freq) == index


def test_au_channel_outside_plan_refused():
    with pytest.raises(ValueError):
        AU915.channel_index(927.9)


@pytest.mark.parametrize("datr,dr", [
    ("SF12BW125", 0), ("SF11BW125", 1), ("SF10BW125", 2), ("SF9BW125", 3),
    ("SF8BW125", 4), ("SF7BW125", 5), ("SF8BW500", 6),
])
def test_au_uplink_data_rates(datr, dr):
    assert AU915.data_rate_index(datr) == dr


def test_au_dr13_is_not_an_uplink_rate():
    with pytest.raises(ValueError):
        AU915.data_rate_index("SF7BW500")


@pytest.mark.parametrize("tx_dr,rx1_datr", [
    (0, "SF10BW500"), (1, "SF9BW500"), (2, "SF8BW500"), (3, "SF7BW500"),
    (4, "SF7BW500"), (5, "SF10BW500"), (6, "SF9BW500"),
])
def test_au_rx1_data_rate_offset_zero(tx_dr, rx1_datr):
    assert AU915.rx1(tx_dr, 0)[1] == rx1_datr


@pytest.mark.parametrize("tx_ch,freq", [(0, 923.3), (7, 927.5), (8, 923.3), (70, 926.9)])
def test_au_rx1_channel_is_tx_channel_modulo_8(tx_ch, freq):
    assert AU915.rx1(0, tx_ch)[0] == pytest.approx(freq)


def test_au_queue_limit_and_rx2():
    assert AU915.queue_payload_max == 222
    assert AU915.dl_settings & 0x0F == 8


def test_au915_end_to_end_join_ack_and_queue(tmp_path):
    env = Env(tmp_path, plan=AU915)
    addr, keys = env.join_device(dev_nonce=1)
    # Uplink confirmé sur 915,2 MHz (canal 0, DR0) : ACK en RX1 à 923,3 MHz / SF10 500 kHz.
    outcome = env.handle(up(keys, addr, 0, b"au", fport=1, confirmed=True, dr=0, ch=0),
                         freq=915.2, datr="SF12BW125")
    assert outcome.issue == "data_accepted"
    assert outcome.txpk.freq_mhz == pytest.approx(923.3)
    assert outcome.txpk.datr == "SF10BW500"
    assert open_dl(outcome.txpk, keys, conf=0, nfcnt=0).ack is True
    # File : 222 octets acceptés, 223 refusés.
    env.store.enqueue_downlink(DEV, 1, False, b"\x00" * 222, AU915)
    with pytest.raises(ValueError):
        env.store.enqueue_downlink(DEV, 1, False, b"\x00" * 223, AU915)
