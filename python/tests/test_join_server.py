"""Serveur de jointure et stockage durable : persistance, rejeu, falsification, concurrence."""

import multiprocessing as mp
import sqlite3

import pytest

from lsim.join_server import DeviceKeys, JoinServer
from lsim.join_store import DurableJoinStore
from lsim.lora import StatusError
from lsim.rejoin import Rejoin02, encode_02
from lsim.security import JoinRequest, decode_join_accept, encode_join_request

NET_ID = bytes([0x13, 0x00, 0x00])
JOIN_EUI = bytes.fromhex("1122334455667788")
INTEGRITY_KEY = bytes(range(16))
NWK_KEY = bytes(range(0x10, 0x20))
SINT_KEY = bytes(range(0x30, 0x40))
JSINT_KEY = bytes(range(0x50, 0x60))
DEV_A = bytes.fromhex("0102030405060708")
DEV_B = bytes.fromhex("8877665544332211")


def _keys(dev_eui: bytes) -> DeviceKeys:
    if dev_eui not in (DEV_A, DEV_B) and not dev_eui.startswith(b"\xaa"):
        raise KeyError("dispositif inconnu")
    return DeviceKeys(NWK_KEY, SINT_KEY, JSINT_KEY)


def _join(dev_eui: bytes, dev_nonce: int) -> bytes:
    req = JoinRequest(JOIN_EUI, dev_eui, dev_nonce.to_bytes(2, "little"))
    return encode_join_request(req, NWK_KEY)


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "joins.sqlite"


@pytest.fixture
def server(db_path):
    return JoinServer(DurableJoinStore(db_path, INTEGRITY_KEY), NET_ID, _keys)


def _raw_blob(path) -> bytes:
    conn = sqlite3.connect(path)
    try:
        return bytes(conn.execute("SELECT blob FROM registry_state WHERE id = 1").fetchone()[0])
    finally:
        conn.close()


def test_join_accept_is_decodable_by_the_device(server):
    out = server.handle_join_request(_join(DEV_A, 1))
    accept = decode_join_accept(out.accept_wire, NWK_KEY, DEV_A, JOIN_EUI,
                                (1).to_bytes(2, "little"))
    assert accept.dev_addr == out.dev_addr
    assert out.dev_addr >> 25 == 0x13          # NwkID = 7 bits du NetID
    assert accept.join_nonce == out.join_nonce.to_bytes(3, "little")
    assert accept.dl_settings & 0x80           # OptNeg : LoRaWAN 1.1


def test_replayed_join_request_is_rejected_and_state_unchanged(server, db_path):
    wire = _join(DEV_A, 7)
    server.handle_join_request(wire)
    before = _raw_blob(db_path)
    with pytest.raises(StatusError):
        server.handle_join_request(wire)
    assert _raw_blob(db_path) == before


def test_invalid_mic_does_not_modify_the_database(server, db_path):
    server.handle_join_request(_join(DEV_B, 1))
    wire = bytearray(_join(DEV_A, 3))
    wire[-1] ^= 0x01
    before = _raw_blob(db_path)
    with pytest.raises(StatusError):
        server.handle_join_request(bytes(wire))
    assert _raw_blob(db_path) == before


def test_unknown_device_is_refused_without_state_change(server, db_path):
    server.handle_join_request(_join(DEV_A, 1))
    before = _raw_blob(db_path)
    unknown = bytes.fromhex("0000000000000001")
    with pytest.raises(KeyError):
        server.handle_join_request(_join(unknown, 1))
    assert _raw_blob(db_path) == before


def test_join_nonce_increments_per_device(server):
    first = server.handle_join_request(_join(DEV_A, 1))
    second = server.handle_join_request(_join(DEV_A, 2))
    other = server.handle_join_request(_join(DEV_B, 1))
    assert (first.join_nonce, second.join_nonce, other.join_nonce) == (0, 1, 0)
    assert len({first.dev_addr, second.dev_addr, other.dev_addr}) == 3


def test_state_survives_restart(db_path):
    s1 = JoinServer(DurableJoinStore(db_path, INTEGRITY_KEY), NET_ID, _keys)
    s1.handle_join_request(_join(DEV_A, 9))
    s2 = JoinServer(DurableJoinStore(db_path, INTEGRITY_KEY), NET_ID, _keys)
    with pytest.raises(StatusError):
        s2.handle_join_request(_join(DEV_A, 9))        # le DevNonce est mémorisé
    out = s2.handle_join_request(_join(DEV_A, 10))
    assert out.join_nonce == 1                        # le compteur continue
    assert DurableJoinStore(db_path, INTEGRITY_KEY).device_count() == 1


def test_tampered_database_is_refused(server, db_path):
    server.handle_join_request(_join(DEV_A, 1))
    conn = sqlite3.connect(db_path)
    blob = bytearray(conn.execute("SELECT blob FROM registry_state WHERE id = 1").fetchone()[0])
    blob[-1] ^= 0x01
    conn.execute("UPDATE registry_state SET blob = ? WHERE id = 1", (bytes(blob),))
    conn.commit()
    conn.close()
    with pytest.raises(StatusError):
        DurableJoinStore(db_path, INTEGRITY_KEY).device_count()


def test_wrong_integrity_key_is_refused(server, db_path):
    server.handle_join_request(_join(DEV_A, 1))
    with pytest.raises(StatusError):
        DurableJoinStore(db_path, bytes(16)).device_count()


def test_rejoin_type_0_replay_is_rejected(server):
    msg = encode_02(Rejoin02(rejoin_type=0, net_id=NET_ID, dev_eui=DEV_A, rjcount0=5), SINT_KEY)
    assert len(msg) == 19
    server.handle_rejoin(msg)
    with pytest.raises(StatusError):
        server.handle_rejoin(msg)


def test_invalid_inputs_are_rejected(db_path):
    store = DurableJoinStore(db_path, INTEGRITY_KEY)
    with pytest.raises(ValueError):
        JoinServer(store, b"\x13\x00", _keys)
    with pytest.raises(ValueError):
        DurableJoinStore(db_path, b"short")
    server = JoinServer(store, NET_ID, _keys)
    with pytest.raises(ValueError):
        server.handle_join_request(b"\x00" * 10)


# --- Concurrence entre processus -------------------------------------------------------

def _race_worker(path, wire, barrier, queue):
    server = JoinServer(DurableJoinStore(path, INTEGRITY_KEY), NET_ID, _keys)
    barrier.wait()
    try:
        server.handle_join_request(wire)
        queue.put("accepted")
    except StatusError:
        queue.put("rejected")


def _distinct_worker(path, devices, queue):
    server = JoinServer(DurableJoinStore(path, INTEGRITY_KEY), NET_ID, _keys)
    addrs = []
    for dev in devices:
        addrs.append(server.handle_join_request(_join(dev, 1)).dev_addr)
    queue.put(addrs)


@pytest.mark.skipif("fork" not in mp.get_all_start_methods(), reason="fork indisponible")
def test_same_join_request_accepted_exactly_once_across_processes(db_path):
    DurableJoinStore(db_path, INTEGRITY_KEY)           # création du schéma
    ctx = mp.get_context("fork")
    n = 8
    barrier = ctx.Barrier(n)
    queue = ctx.Queue()
    wire = _join(DEV_A, 42)
    procs = [ctx.Process(target=_race_worker, args=(db_path, wire, barrier, queue))
             for _ in range(n)]
    for p in procs:
        p.start()
    results = [queue.get(timeout=120) for _ in range(n)]
    for p in procs:
        p.join(timeout=120)
    assert results.count("accepted") == 1
    assert results.count("rejected") == n - 1


@pytest.mark.skipif("fork" not in mp.get_all_start_methods(), reason="fork indisponible")
def test_concurrent_distinct_devices_all_registered_with_unique_addresses(db_path):
    DurableJoinStore(db_path, INTEGRITY_KEY)
    ctx = mp.get_context("fork")
    queue = ctx.Queue()
    groups = [[bytes([0xAA, p, d, 0, 0, 0, 0, 1]) for d in range(5)] for p in range(4)]
    procs = [ctx.Process(target=_distinct_worker, args=(db_path, g, queue)) for g in groups]
    for p in procs:
        p.start()
    addrs = []
    for _ in procs:
        addrs.extend(queue.get(timeout=120))
    for p in procs:
        p.join(timeout=120)
    assert len(addrs) == 20
    assert len(set(addrs)) == 20
    assert DurableJoinStore(db_path, INTEGRITY_KEY).device_count() == 20
