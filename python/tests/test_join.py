"""Jointure OTAA 1.1 via le cœur natif : vecteurs TTN et rejet avant exposition."""

import pytest

from lsim import StatusError
from lsim.security import (
    JoinAccept,
    JoinRequest,
    UplinkContext,
    UplinkFrame,
    decode_join_accept,
    decode_join_request,
    derive_session_keys_11,
    encode_join_accept,
    encode_join_request,
    open_uplink,
    seal_uplink,
)

KEY01 = b"\x01" * 16
# Vecteurs TTN (pkg/crypto/join_messages_test.go), octets en ordre de transmission.
JOIN_EUI = bytes.fromhex("0102030405060708")
DEV_NONCE = bytes.fromhex("0102")


def test_join_request_mic_matches_ttn():
    req = JoinRequest(join_eui=bytes.fromhex("0807060504030201"),
                      dev_eui=bytes.fromhex("0807060504030201"),
                      dev_nonce=bytes.fromhex("0201"))
    wire = encode_join_request(req, KEY01)
    assert len(wire) == 23
    assert wire[0] == 0x00
    assert wire[19:].hex() == "e6e10c55"
    assert decode_join_request(wire, KEY01) == req


def test_join_request_tamper_rejected():
    req = JoinRequest(JOIN_EUI, JOIN_EUI, DEV_NONCE)
    wire = bytearray(encode_join_request(req, KEY01))
    wire[9] ^= 0x01
    with pytest.raises(StatusError) as err:
        decode_join_request(bytes(wire), KEY01)
    assert err.value.code == 404


def test_join_request_wrong_key_rejected():
    req = JoinRequest(JOIN_EUI, JOIN_EUI, DEV_NONCE)
    wire = encode_join_request(req, KEY01)
    with pytest.raises(StatusError):
        decode_join_request(wire, b"\x02" * 16)


def test_join_accept_legacy_encrypted_block_matches_ttn():
    acc = JoinAccept(join_nonce=bytes([3, 2, 1]), net_id=bytes([3, 2, 1]),
                     dev_addr=0x01020304, dl_settings=0, rx_delay=1)
    wire = encode_join_accept(acc, KEY01, bytes(8), JOIN_EUI, DEV_NONCE)
    assert wire[0] == 0x20
    assert wire[1:].hex() == "c9fbb259e11649096a568a9e3b7117c3"
    assert decode_join_accept(wire, KEY01, bytes(8), JOIN_EUI, DEV_NONCE) == acc


@pytest.mark.parametrize("cflist", [None, bytes(range(16))])
def test_join_accept_optneg_roundtrip(cflist):
    dev_eui = bytes.fromhex("42004213424200" + "42")
    acc = JoinAccept(join_nonce=b"\x01\x02\x03", net_id=b"\x00\x00\x01",
                     dev_addr=0x26011BDA, dl_settings=0x80, rx_delay=1, cflist=cflist)
    wire = encode_join_accept(acc, KEY01, dev_eui, JOIN_EUI, DEV_NONCE)
    assert len(wire) == (17 if cflist is None else 33)
    assert decode_join_accept(wire, KEY01, dev_eui, JOIN_EUI, DEV_NONCE) == acc


def test_join_accept_wrong_context_rejected_in_11():
    dev_eui = bytes(range(8))
    acc = JoinAccept(join_nonce=b"\x01\x02\x03", net_id=b"\x00\x00\x01",
                     dev_addr=1, dl_settings=0x80)
    wire = encode_join_accept(acc, KEY01, dev_eui, JOIN_EUI, DEV_NONCE)
    with pytest.raises(StatusError) as err:
        decode_join_accept(wire, KEY01, dev_eui, JOIN_EUI, b"\x02\x02")
    assert err.value.code == 404
    with pytest.raises(StatusError):
        decode_join_accept(wire, KEY01, b"\xff" * 8, JOIN_EUI, DEV_NONCE)


def test_join_accept_bit_flip_rejected():
    acc = JoinAccept(join_nonce=b"\x01\x02\x03", net_id=b"\x00\x00\x01", dev_addr=7)
    wire = bytearray(encode_join_accept(acc, KEY01, bytes(8), JOIN_EUI, DEV_NONCE))
    wire[5] ^= 0x10
    with pytest.raises(StatusError) as err:
        decode_join_accept(bytes(wire), KEY01, bytes(8), JOIN_EUI, DEV_NONCE)
    assert err.value.code == 404


def test_join_accept_length_refused_before_native():
    with pytest.raises(ValueError):
        decode_join_accept(b"\x20" * 16, KEY01, bytes(8), JOIN_EUI, DEV_NONCE)
    with pytest.raises(ValueError):
        JoinAccept(join_nonce=b"\x01", net_id=b"\x00\x00\x01", dev_addr=1)
    with pytest.raises(ValueError):
        JoinRequest(JOIN_EUI, JOIN_EUI, b"\x01")


def test_end_to_end_join_then_uplink():
    app_key = b"\x02" * 16
    dev_eui = bytes.fromhex("4143421342004200")
    jn = bytes([0x1C, 0x3B, 0xAE])
    join_eui = bytes.fromhex("4242222312000000")
    dn = bytes.fromhex("6973")
    acc = JoinAccept(join_nonce=jn, net_id=bytes([0, 0, 1]), dev_addr=0x26011BDA,
                     dl_settings=0x80, rx_delay=1)
    accept_wire = encode_join_accept(acc, KEY01, dev_eui, join_eui, dn)
    got = decode_join_accept(accept_wire, KEY01, dev_eui, join_eui, dn)
    keys = derive_session_keys_11(KEY01, app_key, got.join_nonce, join_eui, dn)
    ctx = UplinkContext(fcnt32=1)
    wire = seal_uplink(UplinkFrame(dev_addr=got.dev_addr, fcnt=1, payload=b"join", fport=3),
                       keys, ctx)
    assert open_uplink(wire, keys, ctx).payload == b"join"
