"""Codec GWMP (Semtech UDP v2) : formats d'en-tête, JSON strict, rejets."""

import base64
import json

import pytest

from lsim import gwmp
from lsim.gwmp import ProtocolError, Txpk

EUI = bytes.fromhex("aabbccddeeff0011")
TOKEN = b"\x12\x34"


def _rxpk(**over):
    base = {"tmst": 3512348611, "chan": 2, "rfch": 0, "freq": 868.1, "stat": 1,
            "modu": "LORA", "datr": "SF7BW125", "codr": "4/5", "rssi": -35, "lsnr": 5.1,
            "size": 4, "data": base64.b64encode(b"\x01\x02\x03\x04").decode()}
    base.update(over)
    return base


def test_pull_data_layout_and_parse():
    wire = gwmp.build_pull_data(TOKEN, EUI)
    assert wire == b"\x02\x12\x34\x02" + EUI
    msg = gwmp.parse_upstream(wire)
    assert isinstance(msg, gwmp.PullData) and msg.gateway_eui == EUI and msg.token == TOKEN


def test_push_data_parses_rxpk_fields():
    wire = gwmp.build_push_data(TOKEN, EUI, [_rxpk()])
    msg = gwmp.parse_upstream(wire)
    assert isinstance(msg, gwmp.PushData)
    (rx,) = msg.rxpk
    assert rx.tmst == 3512348611 and rx.datr == "SF7BW125" and rx.codr == "4/5"
    assert rx.payload == b"\x01\x02\x03\x04" and rx.crc_ok is True
    assert rx.freq_mhz == pytest.approx(868.1) and rx.rssi == -35


def test_ack_builders_match_spec_layout():
    assert gwmp.build_push_ack(TOKEN) == b"\x02\x12\x34\x01"
    assert gwmp.build_pull_ack(TOKEN) == b"\x02\x12\x34\x04"


def test_pull_resp_carries_txpk_json():
    txpk = Txpk(tmst=1000, freq_mhz=868.1, datr="SF7BW125", codr="4/5", payload=b"\xAA" * 17)
    wire = gwmp.build_pull_resp(TOKEN, txpk)
    assert wire[:4] == b"\x02\x12\x34\x03"
    doc = json.loads(wire[4:])
    t = doc["txpk"]
    assert t["imme"] is False and t["tmst"] == 1000 and t["size"] == 17
    assert base64.b64decode(t["data"]) == b"\xAA" * 17
    assert t["ipol"] is True and t["ncrc"] is True and "powe" not in t


def test_tx_ack_with_and_without_error():
    ok = gwmp.parse_upstream(b"\x02\x12\x34\x05" + EUI)
    assert isinstance(ok, gwmp.TxAck) and ok.error is None
    bad = gwmp.parse_upstream(b"\x02\x12\x34\x05" + EUI + b'{"txpk_ack":{"error":"TOO_LATE"}}')
    assert bad.error == "TOO_LATE"


@pytest.mark.parametrize("wire", [
    b"",                                            # vide
    b"\x01\x12\x34\x02" + EUI,                      # mauvaise version
    b"\x02\x12\x34\x07" + EUI,                      # identifiant inconnu
    b"\x02\x12\x34\x02" + EUI + b"\x00",            # PULL_DATA trop long
    b"\x02\x12\x34\x00" + EUI,                      # PUSH_DATA sans JSON
    b"\x02\x12\x34\x00" + EUI + b"[1,2]",           # JSON non objet
    b"\x02\x12\x34\x00" + EUI + b"{nope}",          # JSON invalide
    b"\x02\x12\x34\x00" + EUI + b'{"rxpk":[{"x":NaN}]}',   # constante interdite
    b"\x02\x12\x34\x00" + EUI + b'{"rxpk":[{"x":Infinity}]}',
])
def test_malformed_datagrams_are_rejected(wire):
    with pytest.raises(ProtocolError):
        gwmp.parse_upstream(wire)


def _push_with(**over):
    return gwmp.build_push_data(TOKEN, EUI, [_rxpk(**over)])


@pytest.mark.parametrize("over", [
    {"modu": "FSK"},                    # FSK non supporté
    {"size": 5},                        # taille incohérente avec le payload
    {"data": "!!!!"},                   # base64 invalide
    {"tmst": -1},
    {"tmst": 2**32},
    {"freq": 1e9},
    {"rssi": 1000},
    {"lsnr": float("nan")},
    {"stat": 2},
    {"chan": 1.5},
    {"datr": 125},
])
def test_invalid_rxpk_fields_are_rejected(over):
    with pytest.raises(ProtocolError):
        gwmp.parse_upstream(_push_with(**over))


def test_too_many_rxpk_rejected():
    many = [_rxpk() for _ in range(gwmp.MAX_RXPK_PER_PUSH + 1)]
    with pytest.raises(ProtocolError):
        gwmp.parse_upstream(gwmp.build_push_data(TOKEN, EUI, many))


def test_oversize_datagram_rejected():
    with pytest.raises(ProtocolError):
        gwmp.parse_upstream(b"\x02\x12\x34\x00" + EUI + b"{" + b" " * gwmp.MAX_DATAGRAM_BYTES + b"}")


def test_builders_validate_arguments():
    with pytest.raises(ValueError):
        gwmp.build_pull_data(b"\x00", EUI)
    with pytest.raises(ValueError):
        gwmp.build_pull_data(TOKEN, b"\x00" * 4)
    with pytest.raises(ValueError):
        gwmp.build_pull_resp(TOKEN, Txpk(tmst=2**32, freq_mhz=868.1, datr="SF7BW125",
                                         codr="4/5", payload=b"x"))
    with pytest.raises(ValueError):
        gwmp.build_pull_resp(TOKEN, Txpk(tmst=0, freq_mhz=868.1, datr="SF7BW125",
                                         codr="4/5", payload=b"x" * 256))
