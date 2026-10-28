"""Clés 1.1 et trames sécurisées via le cœur natif (vecteurs TTN, rejet du MIC)."""

import pytest

from lsim import StatusError
from lsim.security import (
    UplinkContext,
    SessionKeys11,
    UplinkFrame,
    derive_join_keys,
    derive_session_keys_11,
    open_uplink,
    seal_uplink,
)

# Vecteurs TTN 1.1 (entrées en ordre de transmission, voir test_crypto.cpp).
TTN_KEY = bytes.fromhex("bec499c69e9c939e413b663961636c61")
TTN_JN = bytes.fromhex("1c3bae")
TTN_JEUI = bytes.fromhex("4242222312000000")
TTN_DN = bytes.fromhex("6973")


def _ttn_keys():
    return derive_session_keys_11(TTN_KEY, TTN_KEY, TTN_JN, TTN_JEUI, TTN_DN)


def test_session_keys_match_ttn_vectors():
    k = _ttn_keys()
    assert k.f_nwk_s_int_key.hex() == "379084e7ce22ff191bff4b77536f2aa3"
    assert k.s_nwk_s_int_key.hex() == "63c59309d53485bc5164dbf71627aeb9"
    assert k.nwk_s_enc_key.hex() == "ce07a009a3970ac0519a099ed53e550b"


def test_keys_are_not_printed():
    k = _ttn_keys()
    assert "37908" not in repr(k)
    assert "<secret>" in repr(k)


def test_join_keys_have_expected_size_and_are_distinct():
    jk = derive_join_keys(TTN_KEY, bytes(8))
    assert len(jk.js_enc_key) == 16 and len(jk.js_int_key) == 16
    assert jk.js_enc_key != jk.js_int_key


def test_seal_uses_reference_ciphertext():
    # Clés toutes à 0x01 ; payload 01 02 03 04 ; FCnt 1 ; port 1.
    # Le chiffrement uplink de référence est cff30b4e (test_crypto.cpp).
    keys = SessionKeys11(*([b"\x01" * 16] * 4))
    frame = UplinkFrame(dev_addr=0x01020304, fcnt=1, payload=bytes([1, 2, 3, 4]), fport=1)
    wire = seal_uplink(frame, keys, UplinkContext(fcnt32=1))
    assert len(wire) == 1 + 7 + 1 + 4 + 4
    assert wire[9:13].hex() == "cff30b4e"


def test_roundtrip_and_fields():
    keys = _ttn_keys()
    frame = UplinkFrame(dev_addr=0x26011BDA, fcnt=5, payload=b"hello", fport=2, confirmed=True)
    ctx = UplinkContext(fcnt32=5)
    wire = seal_uplink(frame, keys, ctx)
    assert b"hello" not in wire
    out = open_uplink(wire, keys, ctx)
    assert out.payload == b"hello"
    assert out.fport == 2 and out.confirmed and out.fcnt == 5
    assert out.dev_addr == 0x26011BDA


def test_empty_frame_without_fport():
    keys = _ttn_keys()
    wire = seal_uplink(UplinkFrame(dev_addr=1, fcnt=0), keys, UplinkContext(fcnt32=0))
    assert len(wire) == 12
    assert open_uplink(wire, keys, UplinkContext(fcnt32=0)).fport is None


def test_port_zero_roundtrip():
    keys = _ttn_keys()
    frame = UplinkFrame(dev_addr=7, fcnt=3, payload=b"\x02\x05", fport=0)
    wire = seal_uplink(frame, keys, UplinkContext(fcnt32=3))
    assert open_uplink(wire, keys, UplinkContext(fcnt32=3)).payload == b"\x02\x05"


def test_bit_flip_is_rejected_with_mic_status():
    keys = _ttn_keys()
    ctx = UplinkContext(fcnt32=5)
    wire = bytearray(seal_uplink(UplinkFrame(dev_addr=9, fcnt=5, payload=b"abc", fport=1), keys, ctx))
    wire[10] ^= 0x01
    with pytest.raises(StatusError) as err:
        open_uplink(bytes(wire), keys, ctx)
    assert err.value.code == 202


def test_wrong_keys_rejected():
    keys = _ttn_keys()
    other = type(keys)(keys.f_nwk_s_int_key, keys.s_nwk_s_int_key, keys.nwk_s_enc_key,
                       b"\x00" * 16)
    ctx = UplinkContext(fcnt32=5)
    wire = seal_uplink(UplinkFrame(dev_addr=9, fcnt=5, payload=b"abc", fport=1), keys, ctx)
    # Clé d'application fausse : le MIC (clé d'intégrité) reste bon, le déchiffrement
    # donne autre chose ; la clé d'intégrité fausse, elle, rejette.
    assert open_uplink(wire, other, ctx).payload != b"abc"
    bad_int = type(keys)(b"\x00" * 16, keys.s_nwk_s_int_key, keys.nwk_s_enc_key, keys.app_s_key)
    with pytest.raises(StatusError) as err:
        open_uplink(wire, bad_int, ctx)
    assert err.value.code == 202


def test_counter_mismatch_is_reported():
    keys = _ttn_keys()
    wire = seal_uplink(UplinkFrame(dev_addr=9, fcnt=5, payload=b"a", fport=1), keys,
                       UplinkContext(fcnt32=5))
    with pytest.raises(StatusError) as err:
        open_uplink(wire, keys, UplinkContext(fcnt32=6))
    assert err.value.code == 203


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(dev_addr=-1, fcnt=0),
        dict(dev_addr=1, fcnt=0x10000),
        dict(dev_addr=1, fcnt=0, payload=b"x" * 243, fport=1),
        dict(dev_addr=1, fcnt=0, payload=b"x", fport=None),
        dict(dev_addr=1, fcnt=0, payload=b"x", fport=256),
    ],
)
def test_invalid_frames_refused_before_native(kwargs):
    with pytest.raises(ValueError):
        UplinkFrame(**kwargs)


def test_invalid_key_length_refused():
    with pytest.raises(ValueError):
        derive_session_keys_11(b"\x00" * 15, TTN_KEY, TTN_JN, TTN_JEUI, TTN_DN)


def test_fopts_roundtrip_encrypted_on_wire():
    keys = _ttn_keys()
    fopts = bytes([0x02, 0x03, 0x04])  # MAC commands (valeurs arbitraires de test)
    frame = UplinkFrame(dev_addr=0x26011BDA, fcnt=5, payload=b"app", fport=2, fopts=fopts)
    ctx = UplinkContext(fcnt32=5)
    wire = seal_uplink(frame, keys, ctx)
    # FOpts commencent à l'octet 8 : chiffrés sur le fil.
    assert wire[8:11] != fopts
    out = open_uplink(wire, keys, ctx)
    assert out.fopts == fopts
    assert out.payload == b"app"


def test_fopts_tampering_rejected():
    keys = _ttn_keys()
    frame = UplinkFrame(dev_addr=1, fcnt=5, fopts=b"\x02\x03")
    wire = bytearray(seal_uplink(frame, keys, UplinkContext(fcnt32=5)))
    wire[8] ^= 0x01
    with pytest.raises(StatusError):
        open_uplink(bytes(wire), keys, UplinkContext(fcnt32=5))


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(dev_addr=1, fcnt=0, fopts=b"x" * 16, fport=1),
        dict(dev_addr=1, fcnt=0, fopts=b"\x02", fport=0),
    ],
)
def test_invalid_fopts_refused(kwargs):
    with pytest.raises(ValueError):
        UplinkFrame(**kwargs)
