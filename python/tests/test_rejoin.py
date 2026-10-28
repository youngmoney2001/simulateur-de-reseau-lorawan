"""Rejoin-request 1.1 via le cœur natif : vecteurs calculés hors du code (cryptography, RFC 4493)."""

import pytest

from lsim import StatusError
from lsim import rejoin

KEY = bytes.fromhex("2b7e151628aed2a6abf7158809cf4f3c")
DEV_EUI = bytes.fromhex("0807060504030201")


def test_type0_vector_matches_independent_cmac():
    msg = rejoin.Rejoin02(rejoin_type=0, net_id=bytes.fromhex("130000"), dev_eui=DEV_EUI, rjcount0=5)
    wire = rejoin.encode_02(msg, KEY)
    assert wire.hex() == "c00013000008070605040302010500a6d032e8"
    assert rejoin.decode_02(wire, KEY) == msg


def test_type1_vector_matches_independent_cmac():
    msg = rejoin.Rejoin1(join_eui=bytes.fromhex("1122334455667788"), dev_eui=DEV_EUI, rjcount1=0x0102)
    wire = rejoin.encode_1(msg, KEY)
    assert wire.hex() == "c001112233445566778808070605040302010201" "62acc0c3"
    assert rejoin.decode_1(wire, KEY) == msg


def test_tampered_counter_rejected_and_no_fields_exposed():
    wire = bytearray(rejoin.encode_02(
        rejoin.Rejoin02(0, bytes.fromhex("130000"), DEV_EUI, 5), KEY))
    wire[13] ^= 0x01
    with pytest.raises(StatusError) as e:
        rejoin.decode_02(bytes(wire), KEY)
    assert e.value.code == 655


def test_wrong_key_type_is_rejected():
    # Un message type 1 ne s'ouvre pas avec une clé différente (JSIntKey ≠ SNwkSIntKey).
    wire = rejoin.encode_1(rejoin.Rejoin1(bytes(8), DEV_EUI, 1), KEY)
    other = bytes([KEY[0] ^ 0xFF]) + KEY[1:]
    with pytest.raises(StatusError) as e:
        rejoin.decode_1(wire, other)
    assert e.value.code == 655


def test_type_and_range_checks():
    with pytest.raises(ValueError):
        rejoin.Rejoin02(rejoin_type=1, net_id=bytes(3), dev_eui=DEV_EUI, rjcount0=0)
    with pytest.raises(ValueError):
        rejoin.Rejoin02(rejoin_type=0, net_id=bytes(3), dev_eui=DEV_EUI, rjcount0=0x10000)
    with pytest.raises(ValueError):
        rejoin.Rejoin1(join_eui=bytes(7), dev_eui=DEV_EUI, rjcount1=0)


def test_truncated_message_rejected():
    with pytest.raises(StatusError) as e:
        rejoin.decode_1(b"\xc0\x01\x00", KEY)
    assert e.value.code == 652
