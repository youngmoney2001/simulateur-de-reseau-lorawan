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
        mac.decode_one(b"\x10\x00", downlink=True)  # PingSlotInfoReq : non implémenté
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


def test_rx_param_setup_req_roundtrip_and_bytes():
    from lsim.mac import NewChannelAns, NewChannelReq, RxParamSetupAns, RxParamSetupReq

    cmd = RxParamSetupReq(rx2_data_rate=3, rx1_dr_offset=2, freq_100hz=8_695_250)
    wire = mac.encode(cmd)
    assert wire == bytes([0x05, 0x23, 0xD2, 0xAD, 0x84])
    assert mac.decode_one(wire, downlink=True) == (cmd, 5)
    assert mac.decode_one(mac.encode(RxParamSetupAns(True, False, True)), downlink=False) == (
        RxParamSetupAns(True, False, True), 2)


def test_rx_param_setup_bounds():
    from lsim.mac import RxParamSetupReq

    with pytest.raises(ValueError):
        RxParamSetupReq(rx2_data_rate=0, rx1_dr_offset=8, freq_100hz=8_695_250)
    with pytest.raises(ValueError):
        RxParamSetupReq(rx2_data_rate=0, rx1_dr_offset=0, freq_100hz=500_000)  # < 100 MHz
    with pytest.raises(ValueError):
        RxParamSetupReq(rx2_data_rate=0, rx1_dr_offset=0, freq_100hz=0x1000000)


def test_new_channel_req_and_ans():
    from lsim.mac import NewChannelAns, NewChannelReq

    cmd = NewChannelReq(ch_index=3, freq_100hz=8_686_000, min_dr=0, max_dr=5)
    wire = mac.encode(cmd)
    assert wire[5] == 0x50  # MaxDR 7:4, MinDR 3:0
    assert mac.decode_one(wire, downlink=True) == (cmd, 6)
    # Fréquence 0 : désactivation du canal, acceptée.
    off = NewChannelReq(ch_index=3, freq_100hz=0, min_dr=0, max_dr=5)
    assert mac.decode_one(mac.encode(off), downlink=True)[0] == off
    assert mac.decode_one(mac.encode(NewChannelAns(True, True)), downlink=False) == (NewChannelAns(True, True), 2)
    with pytest.raises(ValueError):
        NewChannelReq(ch_index=16, freq_100hz=8_686_000, min_dr=0, max_dr=5)


def test_new_channel_ans_rfu_rejected():
    with pytest.raises(StatusError) as e:
        mac.decode_one(b"\x07\x04", downlink=False)
    assert e.value.code == 602


def test_rx_timing_setup_and_device_time():
    from lsim.mac import DeviceTimeAns, DeviceTimeReq, RxTimingSetupAns, RxTimingSetupReq

    assert mac.encode(RxTimingSetupReq(delay=5)) == b"\x08\x05"
    assert mac.decode_one(b"\x08\x05", downlink=True) == (RxTimingSetupReq(delay=5), 2)
    assert mac.encode(RxTimingSetupAns()) == b"\x08"
    assert mac.decode_one(b"\x08", downlink=False) == (RxTimingSetupAns(), 1)
    with pytest.raises(ValueError):
        RxTimingSetupReq(delay=16)
    # DeviceTimeAns : exemple de la spec (1139322288 s depuis l'époque GPS).
    wire = mac.encode(DeviceTimeAns(seconds=1_139_322_288, fraction=0x80))
    assert wire == bytes([0x0D]) + (1_139_322_288).to_bytes(4, "little") + b"\x80"
    assert mac.decode_one(wire, downlink=True) == (DeviceTimeAns(1_139_322_288, 0x80), 6)
    assert mac.encode(DeviceTimeReq()) == b"\x0d"
    assert mac.decode_one(b"\x0d", downlink=False) == (DeviceTimeReq(), 1)


def test_force_rejoin_fields_and_rfu():
    from lsim.mac import ForceRejoinReq

    cmd = ForceRejoinReq(period=2, max_retries=3, rejoin_type=2, dr=5)
    assert mac.encode(cmd) == bytes([0x0E, 0x25, 0x13])
    assert mac.decode_one(mac.encode(cmd), downlink=True) == (cmd, 3)
    with pytest.raises(ValueError):
        ForceRejoinReq(period=8, max_retries=0, rejoin_type=0, dr=0)
    with pytest.raises(StatusError) as e:
        mac.decode_one(bytes([0x0E, 0x35, 0x00]), downlink=True)  # type 3 : RFU
    assert e.value.code == 603


def test_rejoin_param_setup_and_dl_channel():
    from lsim.mac import DlChannelAns, DlChannelReq, RejoinParamSetupAns, RejoinParamSetupReq

    req = RejoinParamSetupReq(max_time_n=4, max_count_n=7)
    assert mac.encode(req) == b"\x0f\x47"
    assert mac.decode_one(b"\x0f\x47", downlink=True) == (req, 2)
    assert mac.decode_one(mac.encode(RejoinParamSetupAns(time_ok=True)), downlink=False) == (
        RejoinParamSetupAns(True), 2)
    dl = DlChannelReq(ch_index=2, freq_100hz=9_235_000)
    assert mac.decode_one(mac.encode(dl), downlink=True) == (dl, 5)
    with pytest.raises(ValueError):
        DlChannelReq(ch_index=2, freq_100hz=500_000)
    assert mac.decode_one(b"\x0a\x02", downlink=False) == (DlChannelAns(False, True), 2)  # bit 1 = fréquence montante
    with pytest.raises(StatusError) as e:
        mac.decode_one(b"\x0a\x04", downlink=False)  # bits RFU
    assert e.value.code == 602


def test_adr_param_setup():
    from lsim.mac import AdrParamSetupAns, AdrParamSetupReq

    req = AdrParamSetupReq(limit_exp=4, delay_exp=13)
    assert mac.encode(req) == b"\x0c\x4d"
    assert mac.decode_one(b"\x0c\x4d", downlink=True) == (req, 2)
    assert mac.encode(AdrParamSetupAns()) == b"\x0c"
    assert mac.decode_one(b"\x0c", downlink=False) == (AdrParamSetupAns(), 1)
    with pytest.raises(ValueError):
        AdrParamSetupReq(limit_exp=16, delay_exp=0)
    with pytest.raises(StatusError):
        mac.decode_one(b"\x0c", downlink=True)  # réponse incomplète

