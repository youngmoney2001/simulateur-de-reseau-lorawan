"""Commandes MAC 1.1 via le cœur natif : octets attendus, bornes et sens du décodage."""

import pytest

from lsim import StatusError
from lsim import mac
from lsim.mac import (
    DevStatusAns,
    DutyCycleReq,
    LinkAdrAns,
    LinkAdrReq,
    LinkCheckAns,
    LinkCheckReq,
    RekeyConf,
    RekeyInd,
)


def test_link_adr_req_wire_bytes():
    cmd = LinkAdrReq(data_rate=5, tx_power=2, ch_mask=0x00FF, ch_mask_cntl=0, nb_trans=1)
    assert mac.encode(cmd) == bytes.fromhex("03 52 FF 00 01".replace(" ", ""))
    back, used = mac.decode_one(mac.encode(cmd), downlink=True)
    assert back == cmd and used == 5


def test_same_cid_differs_by_direction():
    # 0x02 : LinkCheckReq (up, sans charge) ou LinkCheckAns (down, 2 octets).
    assert mac.decode_one(b"\x02", downlink=False) == (LinkCheckReq(), 1)
    assert mac.decode_one(b"\x02\x10\x01", downlink=True) == (LinkCheckAns(0x10, 1), 3)


def test_link_check_ans_reserved_255_rejected():
    with pytest.raises(ValueError):
        LinkCheckAns(255, 1)
    with pytest.raises(StatusError) as e:
        mac.decode_one(b"\x02\xff\x01", downlink=True)
    assert e.value.code == 603


def test_out_of_range_fields_rejected_before_native_call():
    with pytest.raises(ValueError):
        LinkAdrReq(data_rate=16, tx_power=0, ch_mask=0)
    with pytest.raises(ValueError):
        LinkAdrReq(data_rate=0, tx_power=0, ch_mask=0, ch_mask_cntl=8)
    with pytest.raises(ValueError):
        DutyCycleReq(16)
    with pytest.raises(ValueError):
        DevStatusAns(battery=0, margin=32)
    with pytest.raises(ValueError):
        RekeyInd(minor=0)


def test_dev_status_margin_signed_roundtrip():
    for margin in (-32, -1, 0, 31):
        data = mac.encode(DevStatusAns(battery=254, margin=margin))
        cmd, _ = mac.decode_one(data, downlink=False)
        assert cmd == DevStatusAns(battery=254, margin=margin)


def test_rfu_bits_rejected_on_decode():
    with pytest.raises(StatusError) as e:
        mac.decode_one(b"\x03\x07\x00\x00\x81", downlink=True)  # bit 7 de Redundancy
    assert e.value.code == 602
    with pytest.raises(StatusError) as e:
        mac.decode_one(b"\x03\x08", downlink=False)  # bits RFU de LinkADRAns
    assert e.value.code == 602


def test_truncated_and_unknown_commands():
    with pytest.raises(StatusError) as e:
        mac.decode_one(b"\x03\x52\xff", downlink=True)
    assert e.value.code == 602
    with pytest.raises(StatusError) as e:
        mac.decode_one(b"\x05\x00", downlink=True)  # RXParamSetup : non implémenté
    assert e.value.code == 604


def test_decode_all_walks_a_stream_with_mixed_commands():
    stream = mac.encode(LinkAdrAns(True, True, False)) + mac.encode(DevStatusAns(battery=200, margin=-5))
    cmds = mac.decode_all(stream, downlink=False)
    assert cmds == [LinkAdrAns(True, True, False), DevStatusAns(battery=200, margin=-5)]
    assert mac.decode_all(b"", downlink=True) == []


def test_fopts_append_limit_and_no_change_on_refusal():
    fopts = b""
    for _ in range(3):
        fopts = mac.append_fopts(fopts, DevStatusAns(battery=0, margin=0))  # 3 octets chacun
    fopts = mac.append_fopts(fopts, RekeyInd())  # 2 octets : 11
    assert len(fopts) == 11
    fopts = mac.append_fopts(fopts, LinkAdrAns())  # 13
    fopts = mac.append_fopts(fopts, LinkCheckReq())  # 14
    fopts = mac.append_fopts(fopts, LinkCheckReq())  # 15
    assert len(fopts) == 15
    with pytest.raises(StatusError) as e:
        mac.append_fopts(fopts, LinkCheckReq())
    assert e.value.code == 601
    assert len(fopts) == 15


def test_rekey_conf_downlink_format():
    assert mac.encode(RekeyConf()) == b"\x0b\x01"
    assert mac.decode_one(b"\x0b\x01", downlink=True) == (RekeyConf(), 2)
    with pytest.raises(StatusError) as e:
        mac.decode_one(b"\x0b\x00", downlink=True)
    assert e.value.code == 603


def test_duty_cycle_request_decode():
    assert mac.decode_one(b"\x04\x03", downlink=True) == (DutyCycleReq(3), 2)
