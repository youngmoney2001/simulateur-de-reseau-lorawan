"""Registre serveur : rejeux refusés, MIC faux sans effet d'état, reset RJcount0, capacité."""

import pytest

from lsim import StatusError
from lsim import rejoin
from lsim.registry import JoinRegistry
from lsim.security import JoinRequest, encode_join_request

NWK = b"\x01" * 16
KEY = bytes.fromhex("2b7e151628aed2a6abf7158809cf4f3c")
DEV = bytes.fromhex("0807060504030201")
JOIN_EUI = bytes.fromhex("0102030405060708")


def _join(nonce: int, dev: bytes = DEV) -> bytes:
    return encode_join_request(JoinRequest(JOIN_EUI, dev, nonce.to_bytes(2, "little")), NWK)


def test_join_request_replay_and_order():
    with JoinRegistry() as reg:
        reg.accept_join_request(_join(1), NWK)
        with pytest.raises(StatusError) as e:
            reg.accept_join_request(_join(1), NWK)  # rejeu
        assert e.value.code == 704
        with pytest.raises(StatusError):
            reg.accept_join_request(_join(0), NWK)
        reg.accept_join_request(_join(2), NWK)
        assert reg.device_count == 1


def test_forged_mic_leaves_no_state():
    with JoinRegistry() as reg:
        wire = bytearray(_join(7))
        wire[-1] ^= 0x01
        with pytest.raises(StatusError) as e:
            reg.accept_join_request(bytes(wire), NWK)
        assert e.value.code == 702
        assert reg.device_count == 0
        reg.accept_join_request(_join(7), NWK)  # le vrai message passe toujours


def test_rejoin_02_counter_and_join_accept_reset():
    with JoinRegistry() as reg:
        def wire(count: int) -> bytes:
            return rejoin.encode_02(rejoin.Rejoin02(0, bytes.fromhex("130000"), DEV, count), KEY)

        reg.accept_rejoin_02(wire(5), KEY)
        with pytest.raises(StatusError) as e:
            reg.accept_rejoin_02(wire(5), KEY)
        assert e.value.code == 704
        reg.on_join_accepted(DEV)  # nouvelle session : compteur repart de zéro
        reg.accept_rejoin_02(wire(0), KEY)


def test_rejoin_1_uses_its_own_counter():
    with JoinRegistry() as reg:
        wire = rejoin.encode_1(rejoin.Rejoin1(JOIN_EUI, DEV, 3), KEY)
        reg.accept_rejoin_1(wire, KEY)
        with pytest.raises(StatusError) as e:
            reg.accept_rejoin_1(wire, KEY)
        assert e.value.code == 704
        with pytest.raises(StatusError) as e:
            reg.accept_rejoin_1(wire, bytes([KEY[0] ^ 0xFF]) + KEY[1:])
        assert e.value.code == 702


def test_capacity_refuses_new_device_only():
    with JoinRegistry(max_devices=1) as reg:
        reg.accept_join_request(_join(1), NWK)
        with pytest.raises(StatusError) as e:
            reg.accept_join_request(_join(1, bytes(range(8))), NWK)
        assert e.value.code == 705
        reg.accept_join_request(_join(2), NWK)  # dispositif existant toujours servi


def test_closed_handle_and_bad_parameters():
    reg = JoinRegistry()
    reg.close()
    with pytest.raises(StatusError) as e:
        reg.accept_join_request(_join(1), NWK)
    assert e.value.code == 740
    with pytest.raises(ValueError):
        JoinRegistry(max_devices=0)
    with pytest.raises(ValueError):
        JoinRegistry(max_devices=10**9)


def test_persistence_roundtrip_keeps_replay_protection(tmp_path):
    key = bytes(range(16))
    with JoinRegistry() as reg:
        reg.accept_join_request(_join(5), NWK)
        blob = reg.export_state(key)
        assert blob == reg.export_state(key)  # déterministe
        path = tmp_path / "reg.bin"
        reg.save(path, key)
    with JoinRegistry.load(path, key) as restored:
        assert restored.device_count == 1
        with pytest.raises(StatusError) as e:
            restored.accept_join_request(_join(5), NWK)
        assert e.value.code == 704
        restored.accept_join_request(_join(6), NWK)
    assert not (tmp_path / "reg.bin.tmp").exists()


def test_tampered_or_wrong_key_loads_nothing():
    key = bytes(range(16))
    with JoinRegistry() as reg:
        reg.accept_join_request(_join(5), NWK)
        blob = reg.export_state(key)
    bad = bytearray(blob)
    bad[12] ^= 0x01
    with pytest.raises(StatusError) as e:
        JoinRegistry.import_state(bytes(bad), key)
    assert e.value.code == 707
    with pytest.raises(StatusError) as e:
        JoinRegistry.import_state(blob, bytes(16))
    assert e.value.code == 707
    with pytest.raises(StatusError) as e:
        JoinRegistry.import_state(blob[:-1], key)
    assert e.value.code == 707
    with pytest.raises(StatusError) as e:
        JoinRegistry.import_state(blob[:10], key)
    assert e.value.code == 701
    with pytest.raises(ValueError):
        JoinRegistry.import_state(b"", key)

