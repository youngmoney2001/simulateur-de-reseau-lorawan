"""LinkADRReq de sous-bande : octets, passerelle annoncée, émission après jointure, acquittement.

Les octets attendus viennent de la spécification LoRaWAN (LinkADRReq : DataRate/TXPower sur
un octet, ChMask sur 2 octets en petit-boutiste, Redundancy = ChMaskCntl << 4 | NbTrans).
"""

import pytest

from lsim import mac
from lsim.gwmp import Rxpk
from lsim.join_server import DeviceKeys
from lsim.join_store import DurableJoinStore
from lsim.plan import get_plan
from lsim.security import (
    DownlinkContext, JoinRequest, UplinkContext, UplinkFrame, encode_join_request,
    open_downlink, seal_uplink,
)
from lsim.serve import build_handler, effective_sub_band, link_adr_payload, _mac_answers
from lsim.basicstation import router_config

US915 = get_plan("US915")
EU868 = get_plan("EU868")
AU915 = get_plan("AU915")
NET_ID = bytes([0x13, 0x00, 0x00])
JOIN_EUI = bytes.fromhex("1122334455667788")
DEV = bytes.fromhex("0102030405060708")
NWK = bytes(range(0x10, 0x20))
APP = bytes(range(0x40, 0x50))
INTEGRITY = bytes(range(16))
DATA_KEY = bytes(range(0x80, 0xA0))


# ------------------------------------------------------------------ octets du LinkADRReq

def test_link_adr_payload_bytes_sub_band_2():
    # CID 0x03 ; DataRate 15 / TXPower 15 = 0xFF ; ChMask 0x0002 LE ; ChMaskCntl 5 << 4 | NbTrans 0
    assert link_adr_payload(US915, 2) == bytes([0x03, 0xFF, 0x02, 0x00, 0x50])


def test_link_adr_payload_bytes_sub_band_8_and_au915():
    assert link_adr_payload(US915, 8) == bytes([0x03, 0xFF, 0x80, 0x00, 0x50])
    assert link_adr_payload(AU915, 1) == bytes([0x03, 0xFF, 0x01, 0x00, 0x50])


def test_link_adr_payload_round_trips_through_codec():
    [cmd] = mac.decode_all(link_adr_payload(US915, 3), downlink=True)
    assert cmd == mac.LinkAdrReq(data_rate=15, tx_power=15, ch_mask=0b100, ch_mask_cntl=5,
                                 nb_trans=0)


def test_link_adr_payload_refused_for_eu868():
    with pytest.raises(ValueError):
        link_adr_payload(EU868, 1)


def test_effective_sub_band_defaults_and_refusals():
    assert effective_sub_band(US915, None) == 1
    assert effective_sub_band(AU915, 4) == 4
    assert effective_sub_band(EU868, None) is None
    with pytest.raises(ValueError):
        effective_sub_band(EU868, 1)
    with pytest.raises(ValueError):
        effective_sub_band(US915, 9)


# ------------------------------------------------------------------ passerelle annoncée

def test_router_config_announces_sub_band_channels():
    conf = router_config(US915, 0x13, "sx1301/1", sub_band=2)["sx1301_conf"][0]
    # Sous-bande 2 : 125 kHz 903,9 à 905,3 MHz ; 500 kHz 904,6 MHz (canal 65).
    assert conf["radio_0"] == {"enable": True, "freq": 904_600_000}
    assert conf["chan_multiSF_0"] == {"enable": True, "radio": 0, "if": -700_000}
    assert conf["chan_multiSF_7"] == {"enable": True, "radio": 0, "if": 700_000}
    assert conf["radio_1"] == {"enable": True, "freq": 904_600_000}
    assert conf["chan_Lora_std"] == {"enable": True, "radio": 1, "if": 0,
                                     "bandwidth": 500_000, "spread_factor": 8}


def test_router_config_sub_band_8_uses_its_own_500khz_channel():
    # AU915 sous-bande 8 : 125 kHz 926,4 à 927,8 MHz (canaux 56-63), centre 927,1 MHz ;
    # 500 kHz canal 71 = 915,9 + 1,6 × 7 = 927,1 MHz.
    conf = router_config(AU915, 0x13, "sx1301/1", sub_band=8)["sx1301_conf"][0]
    assert conf["radio_0"]["freq"] == 927_100_000
    assert conf["radio_1"]["freq"] == 927_100_000
    assert conf["chan_Lora_std"]["enable"] is True


def test_router_config_default_is_unchanged_for_eu868():
    conf = router_config(EU868, 0x13, "sx1301/1")["sx1301_conf"][0]
    assert conf["chan_Lora_std"]["enable"] is False
    assert conf["radio_1"]["enable"] is False


# ------------------------------------------------------------------ émission après jointure

def _rxpk(payload, freq, datr, tmst=1_000_000):
    return Rxpk(tmst=tmst, freq_mhz=freq, chan=0, rfch=0, crc_ok=True, datr=datr, codr="4/5",
                rssi=-60, lsnr=7.0, payload=payload)


def _join(handler, freq=903.9, datr="SF7BW125"):
    wire = encode_join_request(JoinRequest(JOIN_EUI, DEV, (1).to_bytes(2, "little")), NWK)
    outcome = handler.handle(_rxpk(wire, freq, datr))
    assert outcome.issue == "join_accepted"


@pytest.fixture
def store(tmp_path):
    return DurableJoinStore(tmp_path / "join.sqlite", INTEGRITY, DATA_KEY)


def test_join_queues_link_adr_and_first_downlink_carries_it(store):
    handler = build_handler(store, {DEV: DeviceKeys(NWK, app_key=APP)}, NET_ID, US915, 2)
    _join(handler)
    with store.transaction() as tx:
        rec = tx.session_by_eui(DEV)
        assert tx.queue_length(DEV) == 1
    # Uplink non confirmé (DR0 SF10/125, canal 8 à 903,9 MHz) : le downlink RX1 porte FOpts.
    wire = seal_uplink(
        UplinkFrame(dev_addr=rec.dev_addr, fcnt=0, payload=b"", fport=None, confirmed=False,
                    ack=False),
        rec.keys, UplinkContext(fcnt32=0, conf_fcnt=0, tx_dr=0, tx_ch=8))
    outcome = handler.handle(_rxpk(wire, 903.9, "SF10BW125"))
    assert outcome.txpk is not None
    # RX1 du canal 8 : 923,3 MHz, débit RX1 SF10/500 (RX1DROffset 0, DR0 → DR10).
    assert outcome.txpk.freq_mhz == pytest.approx(923.3)
    frame = open_downlink(outcome.txpk.payload, rec.keys,
                          DownlinkContext(conf_fcnt=0, nfcnt32=0, afcnt32=0))
    assert frame.fport is None and frame.payload == b""
    assert frame.fopts == link_adr_payload(US915, 2)[:]
    assert mac.decode_all(frame.fopts, downlink=True)[0].ch_mask == 0b10


def test_queued_link_adr_sent_once(store):
    handler = build_handler(store, {DEV: DeviceKeys(NWK, app_key=APP)}, NET_ID, US915, 2)
    _join(handler)
    with store.transaction() as tx:
        rec = tx.session_by_eui(DEV)
    for fcnt in (0, 1):
        wire = seal_uplink(
            UplinkFrame(dev_addr=rec.dev_addr, fcnt=fcnt, payload=b"", fport=None,
                        confirmed=False, ack=False),
            rec.keys, UplinkContext(fcnt32=fcnt, conf_fcnt=0, tx_dr=0, tx_ch=8))
        outcome = handler.handle(_rxpk(wire, 903.9, "SF10BW125"))
    assert outcome.txpk is None          # la commande est partie au premier uplink seulement


def test_eu868_join_queues_nothing(store):
    handler = build_handler(store, {DEV: DeviceKeys(NWK, app_key=APP)}, NET_ID, EU868)
    _join(handler, freq=868.1, datr="SF7BW125")
    with store.transaction() as tx:
        assert tx.queue_length(DEV) == 0


def test_build_handler_refuses_sub_band_on_eu868(store):
    with pytest.raises(ValueError):
        build_handler(store, {}, NET_ID, EU868, 1)


# ------------------------------------------------------------------ acquittement

def test_link_adr_ans_is_decoded_from_fopts():
    ans = mac.encode(mac.LinkAdrAns(channel_mask_ack=True, data_rate_ack=True, power_ack=True))
    [decoded] = _mac_answers(ans)
    assert decoded == mac.LinkAdrAns(True, True, True)


def test_malformed_fopts_do_not_break_logging():
    assert _mac_answers(b"\xff\xff\xff") == []
    assert _mac_answers(b"") == []
