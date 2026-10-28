"""Trames de données 1.1 (EU868) : compteurs 32 bits, rejeu, MIC, ACK, file de downlinks.

Le dispositif est simulé avec les primitives du cœur C (`seal_uplink`, `open_downlink`) et les
clés de session dérivées comme le ferait le dispositif (même JoinNonce, DevNonce, JoinEUI).
"""

import os
import sqlite3
import stat

import pytest


from lsim.gwmp import Rxpk
from lsim.join_server import DeviceKeys, JoinServer
from lsim.join_store import QUEUE_LIMIT, DurableJoinStore, QueueFullError
from lsim.gwmp_server import JoinUplinkHandler
from lsim.security import (
    DownlinkContext, JoinRequest, UplinkContext, UplinkFrame, derive_session_keys_11,
    encode_join_request, open_downlink, seal_uplink,
)
from lsim.plan import get_plan
from lsim.sealed import IntegrityError
from lsim.uplink import DataUplinkHandler, UplinkRouter, reconstruct_fcnt32

NET_ID = bytes([0x13, 0x00, 0x00])
JOIN_EUI = bytes.fromhex("1122334455667788")
DEV = bytes.fromhex("0102030405060708")
NWK = bytes(range(0x10, 0x20))
APP = bytes(range(0x40, 0x50))
INTEGRITY = bytes(range(16))
DATA_KEY = bytes(range(0x80, 0xA0))
TX_DR = 5          # SF7BW125 (DR5, RP002-1.0.2 tableau 8)
TX_CH = 0          # 868,10 MHz (canal par défaut 0)
TMST = 1_000_000


class Env:
    def __init__(self, tmp_path, app_key=APP, plan=None, data_key=DATA_KEY):
        self.plan = plan if plan is not None else get_plan("EU868")
        self.store = DurableJoinStore(tmp_path / "join.sqlite", INTEGRITY, data_key)
        self.join = JoinServer(self.store, NET_ID, self._keys(app_key),
                               dl_settings=self.plan.dl_settings)
        self.router = UplinkRouter(JoinUplinkHandler(self.join, self.plan),
                                   DataUplinkHandler(self.store, self.plan))

    @staticmethod
    def _keys(app_key):
        def provider(dev_eui):
            if dev_eui != DEV:
                raise KeyError("dispositif inconnu")
            return DeviceKeys(NWK, app_key=app_key)
        return provider

    def join_device(self, dev_nonce=1):
        """Jointure : retourne (DevAddr, clés de session côté dispositif)."""
        wire = encode_join_request(JoinRequest(JOIN_EUI, DEV, dev_nonce.to_bytes(2, "little")), NWK)
        out = self.join.handle_join_request(wire)
        keys = derive_session_keys_11(NWK, APP, out.join_nonce.to_bytes(3, "little"),
                                      JOIN_EUI, out.dev_nonce)
        return out.dev_addr, keys

    def session(self, dev_addr):
        with self.store.transaction() as tx:
            return tx.session_by_addr(dev_addr)

    def handle(self, wire, *, tmst=TMST, freq=868.1, datr="SF7BW125"):
        return self.router.handle(Rxpk(tmst=tmst, freq_mhz=freq, chan=0, rfch=0, crc_ok=True,
                                       datr=datr, codr="4/5", rssi=-60, lsnr=7.0, payload=wire))


def up(keys, dev_addr, fcnt32, payload=b"", fport=None, confirmed=False, ack=False, conf=0,
       dr=TX_DR, ch=TX_CH):
    frame = UplinkFrame(dev_addr=dev_addr, fcnt=fcnt32 & 0xFFFF, payload=payload, fport=fport,
                        confirmed=confirmed, ack=ack)
    return seal_uplink(frame, keys, UplinkContext(fcnt32=fcnt32, conf_fcnt=conf,
                                                  tx_dr=dr, tx_ch=ch))


def open_dl(txpk, keys, conf=0, nfcnt=0, afcnt=0):
    return open_downlink(txpk.payload, keys, DownlinkContext(conf_fcnt=conf, nfcnt32=nfcnt,
                                                             afcnt32=afcnt))


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


# Compteurs

def test_reconstruct_fcnt32_rules():
    assert reconstruct_fcnt32(-1, 0) == (0, False)
    assert reconstruct_fcnt32(5, 6) == (6, False)
    assert reconstruct_fcnt32(5, 5) == (5, True)                    # retransmission
    assert reconstruct_fcnt32(0xFFFF, 0) == (0x10000, False)        # débordement 16 bits
    assert reconstruct_fcnt32(0x1FFFE, 0x0001) == (0x20001, False)  # deuxième tour
    assert reconstruct_fcnt32(10, 0) == (65536, False)              # delta mod 2^16, pas de limite


def test_unconfirmed_uplink_is_verified_and_delivered(env):
    addr, keys = env.join_device()
    outcome = env.handle(up(keys, addr, 0, b"hello", fport=1))
    assert outcome.issue == "data_accepted"
    assert outcome.txpk is None
    assert outcome.delivery.payload == b"hello"
    assert outcome.delivery.fport == 1 and outcome.delivery.fcnt == 0
    assert outcome.delivery.dev_eui == DEV and outcome.delivery.confirmed is False
    assert env.session(addr).fcnt_up == 0


def test_confirmed_uplink_is_acknowledged_in_rx1(env):
    addr, keys = env.join_device()
    for n in range(6):
        assert env.handle(up(keys, addr, n, b"x", fport=1)).issue == "data_accepted"
    outcome = env.handle(up(keys, addr, 6, b"c", fport=1, confirmed=True), tmst=TMST)
    assert outcome.issue == "data_accepted"
    txpk = outcome.txpk
    assert txpk.tmst == TMST + 1_000_000             # RECEIVE_DELAY1 = 1 s (RP002 §2.3)
    assert txpk.freq_mhz == 868.1 and txpk.datr == "SF7BW125"   # RX1 = même canal, RX1DROffset 0
    ack = open_dl(txpk, keys, conf=6, nfcnt=0)         # ConfFCnt = FCnt de l'uplink acquitté
    assert ack.ack is True and ack.fport is None and ack.confirmed is False


def test_counter_is_32_bit_across_16_bit_rollover(env):
    addr, keys = env.join_device()
    with env.store.transaction() as tx:
        tx.save_counters(addr, 0xFFFF, 0, 0, None)     # état : dernier FCnt 0xFFFF accepté
    outcome = env.handle(up(keys, addr, 0x10000, b"roll", fport=1))
    assert outcome.issue == "data_accepted"
    assert outcome.delivery.fcnt == 0x10000
    assert env.session(addr).fcnt_up == 0x10000


def test_replayed_uplink_is_refused(env):
    addr, keys = env.join_device()
    wire = up(keys, addr, 0, b"once", fport=1)
    assert env.handle(wire).issue == "data_accepted"
    outcome = env.handle(wire)
    assert outcome.issue == "data_replay"
    assert outcome.delivery is None and outcome.txpk is None


def test_stale_counter_is_refused_and_state_unchanged(env):
    addr, keys = env.join_device()
    for n in range(7):
        env.handle(up(keys, addr, n, b"x", fport=1))
    stale = up(keys, addr, 3, b"old", fport=1)
    assert env.handle(stale).issue == "data_mic_failed"
    assert env.session(addr).fcnt_up == 6


def test_tampered_mic_changes_nothing(env):
    addr, keys = env.join_device()
    wire = bytearray(up(keys, addr, 0, b"data", fport=1))
    wire[-1] ^= 0x01
    before = env.session(addr)
    outcome = env.handle(bytes(wire))
    assert outcome.issue == "data_mic_failed"
    assert outcome.delivery is None
    assert env.session(addr) == before


def test_unknown_dev_addr_is_refused(env):
    addr, keys = env.join_device()
    assert env.handle(up(keys, addr ^ 0x1, 0, b"x", fport=1)).issue == "data_unknown_addr"


def test_channel_or_rate_outside_default_eu868_plan_is_refused(env):
    addr, keys = env.join_device()
    wire = up(keys, addr, 0, b"x", fport=1)
    # Canal réseau non par défaut : le MIC 1.1 exige TxCh, indisponible hors plan par défaut.
    assert env.handle(wire, freq=868.7).issue == "data_unsupported_channel"
    assert env.handle(wire, datr="SF7BW500").issue == "data_unsupported_channel"
    assert env.session(addr).fcnt_up == -1


def test_wrong_tx_dr_breaks_mic(env):
    addr, keys = env.join_device()
    wire = up(keys, addr, 0, b"x", fport=1, dr=TX_DR)
    # Débit annoncé par la passerelle différent de celui utilisé par le dispositif : MIC faux.
    assert env.handle(wire, datr="SF8BW125").issue == "data_mic_failed"


def test_duplicate_unconfirmed_copy_is_dropped(env):
    addr, keys = env.join_device()
    wire = up(keys, addr, 0, b"x", fport=1)
    env.handle(wire)
    assert env.handle(wire).issue == "data_replay"


def test_retransmitted_confirmed_uplink_is_acknowledged_again(env):
    addr, keys = env.join_device()
    wire = up(keys, addr, 0, b"c", fport=1, confirmed=True)
    first = env.handle(wire)
    assert first.issue == "data_accepted" and first.delivery is not None
    again = env.handle(wire)
    assert again.issue == "data_ack_repeated"
    assert again.delivery is None
    assert again.txpk is not None
    assert open_dl(again.txpk, keys, conf=0, nfcnt=1).ack is True
    assert env.session(addr).fcnt_up == 0


# Downlinks et file

def test_queued_downlink_is_sent_in_rx1_on_next_uplink(env):
    addr, keys = env.join_device()
    env.store.enqueue_downlink(DEV, 1, False, b"cmd")
    outcome = env.handle(up(keys, addr, 0, b"ping", fport=1))
    assert outcome.issue == "data_accepted"
    dl = open_dl(outcome.txpk, keys, afcnt=0)           # FPort > 0 : AFCntDown
    assert dl.fport == 1 and dl.payload == b"cmd" and dl.confirmed is False
    state = env.session(addr)
    assert (state.afcnt_down, state.nfcnt_down) == (1, 0)
    with env.store.transaction() as tx:
        assert tx.queue_length(DEV) == 0


def test_downlink_queue_is_fifo(env):
    addr, keys = env.join_device()
    env.store.enqueue_downlink(DEV, 2, False, b"first")
    env.store.enqueue_downlink(DEV, 2, False, b"second")
    first = env.handle(up(keys, addr, 0, b"a", fport=1))
    second = env.handle(up(keys, addr, 1, b"b", fport=1))
    assert open_dl(first.txpk, keys, afcnt=0).payload == b"first"
    assert open_dl(second.txpk, keys, afcnt=1).payload == b"second"


def test_no_downlink_consumes_no_counter(env):
    addr, keys = env.join_device()
    assert env.handle(up(keys, addr, 0, b"x", fport=1)).txpk is None
    state = env.session(addr)
    assert (state.nfcnt_down, state.afcnt_down) == (0, 0)


def test_confirmed_downlink_is_pending_until_next_uplink(env):
    addr, keys = env.join_device()
    env.store.enqueue_downlink(DEV, 3, True, b"must-ack")
    outcome = env.handle(up(keys, addr, 0, b"x", fport=1))
    dl = open_dl(outcome.txpk, keys, afcnt=0)
    assert dl.confirmed is True and dl.payload == b"must-ack"
    assert env.session(addr).pending_conf == 0
    # Le dispositif acquitte le downlink confirmé : ACK=1, ConfFCnt = compteur AFCntDown 0.
    ack_up = up(keys, addr, 1, b"y", fport=1, ack=True, conf=0)
    assert env.handle(ack_up).issue == "data_accepted"
    assert env.session(addr).pending_conf is None


def test_wrong_conf_fcnt_in_ack_breaks_mic(env):
    addr, keys = env.join_device()
    env.store.enqueue_downlink(DEV, 3, True, b"must-ack")
    env.handle(up(keys, addr, 0, b"x", fport=1))
    assert env.handle(up(keys, addr, 1, b"y", fport=1, ack=True, conf=7)).issue == "data_mic_failed"
    assert env.session(addr).pending_conf == 0


def test_confirmed_downlink_is_clear_when_device_does_not_ack(env):
    addr, keys = env.join_device()
    env.store.enqueue_downlink(DEV, 3, True, b"lost?")
    env.handle(up(keys, addr, 0, b"x", fport=1))
    env.handle(up(keys, addr, 1, b"y", fport=1, ack=False))
    assert env.session(addr).pending_conf is None


def test_fport_above_zero_needs_app_key(tmp_path):
    env = Env(tmp_path, app_key=None)
    addr, keys = env.join_device()
    with pytest.raises(ValueError):
        env.store.enqueue_downlink(DEV, 1, False, b"x")
    # Uplink FPort > 0 : le MIC se vérifie sans AppSKey ; la charge n'est pas livrée.
    outcome = env.handle(up(keys, addr, 0, b"secret", fport=1))
    assert outcome.issue == "data_accepted"
    assert outcome.delivery.payload is None and outcome.delivery.fport == 1


def test_fport_zero_mac_payload_is_not_delivered(env):
    addr, keys = env.join_device()
    outcome = env.handle(up(keys, addr, 0, b"\x02", fport=0))
    assert outcome.issue == "data_accepted" and outcome.delivery.payload is None


def test_queue_limit_per_device(env):
    env.join_device()
    for _ in range(QUEUE_LIMIT):
        env.store.enqueue_downlink(DEV, 1, False, b"x")
    with pytest.raises(QueueFullError):
        env.store.enqueue_downlink(DEV, 1, False, b"x")


def test_rejoin_replaces_session_and_queue(env):
    addr, keys = env.join_device(dev_nonce=1)
    env.store.enqueue_downlink(DEV, 1, False, b"stale")
    env.handle(up(keys, addr, 0, b"x", fport=1))
    addr2, keys2 = env.join_device(dev_nonce=2)
    assert addr2 != addr
    assert env.session(addr) is None
    state = env.session(addr2)
    assert state.fcnt_up == -1
    with env.store.transaction() as tx:
        assert tx.queue_length(DEV) == 0
    assert env.handle(up(keys2, addr2, 0, b"new", fport=1)).delivery.payload == b"new"
    assert env.handle(up(keys, addr, 1, b"old", fport=1)).issue == "data_unknown_addr"


# Stockage

def test_database_is_created_0600(tmp_path):
    DurableJoinStore(tmp_path / "new.sqlite", INTEGRITY)
    assert stat.S_IMODE(os.stat(tmp_path / "new.sqlite").st_mode) == 0o600


def test_database_open_to_others_is_refused(tmp_path):
    path = tmp_path / "old.sqlite"
    DurableJoinStore(path, INTEGRITY)
    os.chmod(path, 0o644)
    with pytest.raises(PermissionError):
        DurableJoinStore(path, INTEGRITY)


def test_enqueue_cli_helper_validates_input(tmp_path, monkeypatch):
    from lsim import serve
    monkeypatch.setenv("LSIM_INTEGRITY_KEY", INTEGRITY.hex())
    monkeypatch.setenv("LSIM_DATA_KEY", DATA_KEY.hex())
    env = Env(tmp_path)
    env.join_device()
    db = tmp_path / "join.sqlite"
    dev_hex = DEV.hex()
    with pytest.raises(ValueError):
        serve.enqueue_downlink(db, dev_hex, 0, "00", False)            # FPort 0 interdit
    with pytest.raises(ValueError):
        serve.enqueue_downlink(db, dev_hex, 1, "00" * 52, False)       # > 51 octets (DR0)
    assert serve.enqueue_downlink(db, dev_hex, 1, "00" * 51, False) == 1


# Bout en bout sur UDP (Semtech GWMP) : PUSH_DATA d'un uplink confirmé → ACK en PULL_RESP.

def test_confirmed_uplink_over_udp_gets_ack_in_pull_resp(tmp_path):
    import asyncio
    import base64
    import json

    from lsim import gwmp
    from lsim.gwmp_server import start_server

    env = Env(tmp_path)
    addr, keys = env.join_device()
    gw = bytes.fromhex("aabbccddeeff0011")
    deliveries = []

    def rxpk_dict(wire):
        return {"tmst": 2_000_000, "chan": 0, "rfch": 0, "freq": 868.1, "stat": 1,
                "modu": "LORA", "datr": "SF7BW125", "codr": "4/5", "rssi": -60, "lsnr": 7.0,
                "size": len(wire), "data": base64.b64encode(wire).decode()}

    class Client(asyncio.DatagramProtocol):
        def __init__(self):
            self.queue = asyncio.Queue()

        def datagram_received(self, data, _addr):
            self.queue.put_nowait(data)

    async def scenario():
        transport, server = await start_server(
            env.router, "127.0.0.1", 0, on_delivery=deliveries.append)
        port = transport.get_extra_info("sockname")[1]
        loop = asyncio.get_running_loop()
        client_t, client = await loop.create_datagram_endpoint(
            Client, remote_addr=("127.0.0.1", port))
        try:
            client_t.sendto(gwmp.build_pull_data(b"\x00\x01", gw))
            assert await asyncio.wait_for(client.queue.get(), 5)           # PULL_ACK
            wire = up(keys, addr, 0, b"udp", fport=1, confirmed=True)
            client_t.sendto(gwmp.build_push_data(b"\x00\x02", gw, [rxpk_dict(wire)]))
            assert await asyncio.wait_for(client.queue.get(), 5) == b"\x02\x00\x02\x01"  # PUSH_ACK
            resp = await asyncio.wait_for(client.queue.get(), 5)           # PULL_RESP (ACK)
            assert resp[3] == gwmp.PULL_RESP
            txpk = json.loads(resp[4:])["txpk"]
            assert txpk["tmst"] == 2_000_000 + 1_000_000
            ack = open_downlink(base64.b64decode(txpk["data"]), keys,
                                DownlinkContext(conf_fcnt=0, nfcnt32=0, afcnt32=0))
            assert ack.ack is True
            await server.drain()
            assert server.stats["data_accepted"] == 1
            assert len(deliveries) == 1 and deliveries[0].payload == b"udp"
        finally:
            client_t.close()
            transport.close()

    asyncio.run(scenario())


# Région US915 de bout en bout : jointure sur canal 64, ACK et file selon le plan.

def test_us915_join_ack_and_queue_limit(tmp_path):
    from lsim.us915 import US915
    env = Env(tmp_path, plan=US915)
    # Jointure sur le canal 64 (903,0 MHz, DR4) : join-accept en RX1 à 923,3 MHz, DR13.
    wire = encode_join_request(JoinRequest(JOIN_EUI, DEV, (1).to_bytes(2, "little")), NWK)
    outcome = env.router.handle(Rxpk(tmst=TMST, freq_mhz=903.0, chan=64, rfch=0, crc_ok=True,
                                     datr="SF8BW500", codr="4/5", rssi=-60, lsnr=7.0,
                                     payload=wire))
    assert outcome.issue == "join_accepted"
    assert outcome.txpk.freq_mhz == pytest.approx(923.3)
    assert outcome.txpk.datr == "SF7BW500"
    addr, keys = env.join_device(dev_nonce=2)
    # Uplink confirmé sur 902,3 MHz (canal 0, DR0) : ACK en RX1 sur 923,3 MHz / SF10 500 kHz.
    ack_outcome = env.router.handle(Rxpk(
        tmst=TMST, freq_mhz=902.3, chan=0, rfch=0, crc_ok=True, datr="SF10BW125", codr="4/5",
        rssi=-60, lsnr=7.0,
        payload=up(keys, addr, 0, b"us", fport=1, confirmed=True, dr=0, ch=0)))
    assert ack_outcome.issue == "data_accepted"
    assert ack_outcome.txpk.freq_mhz == pytest.approx(923.3)
    assert ack_outcome.txpk.datr == "SF10BW500"
    assert open_dl(ack_outcome.txpk, keys, conf=0, nfcnt=0).ack is True
    # File : 222 octets acceptés, 223 refusés (plus petite N des fenêtres RX1 du plan).
    env.store.enqueue_downlink(DEV, 1, False, b"\x00" * 222, US915)
    with pytest.raises(ValueError):
        env.store.enqueue_downlink(DEV, 1, False, b"\x00" * 223, US915)


# Chiffrement au repos (lsim.sealed)

def test_session_keys_are_not_plaintext_in_database(env):
    addr, keys = env.join_device()
    env.store.enqueue_downlink(DEV, 1, False, b"SECRET-PAYLOAD")
    raw = bytearray()
    conn = sqlite3.connect(env.store._path)
    try:
        for (blob,) in conn.execute("SELECT sealed FROM sessions"):
            raw += bytes(blob)
        for (blob,) in conn.execute("SELECT payload FROM downlink_queue"):
            raw += bytes(blob)
    finally:
        conn.close()
    for secret in (keys.nwk_s_enc_key, keys.f_nwk_s_int_key, keys.s_nwk_s_int_key, keys.app_s_key):
        assert bytes(secret) not in bytes(raw)
    assert b"SECRET-PAYLOAD" not in bytes(raw)


def test_moved_session_record_is_refused(env):
    addr_a, _ = env.join_device(dev_nonce=1)
    conn = sqlite3.connect(env.store._path)
    try:
        conn.execute("UPDATE sessions SET dev_addr = dev_addr + 1 WHERE dev_addr = ?", (addr_a,))
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(IntegrityError):
        env.session(addr_a + 1)


def test_tampered_session_record_is_refused(env):
    addr, _ = env.join_device()
    conn = sqlite3.connect(env.store._path)
    try:
        (blob,) = conn.execute("SELECT sealed FROM sessions WHERE dev_addr = ?", (addr,)).fetchone()
        bad = bytearray(blob)
        bad[-1] ^= 0x01
        conn.execute("UPDATE sessions SET sealed = ? WHERE dev_addr = ?", (bytes(bad), addr))
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(IntegrityError):
        env.session(addr)


def test_wrong_data_key_is_refused(tmp_path):
    env = Env(tmp_path)
    addr, _ = env.join_device()
    other = DurableJoinStore(tmp_path / "join.sqlite", INTEGRITY, bytes(range(1, 33)))
    with pytest.raises(IntegrityError):
        with other.transaction() as tx:
            tx.session_by_addr(addr)


def test_store_without_data_key_refuses_sessions(tmp_path):
    store = DurableJoinStore(tmp_path / "nokey.sqlite", INTEGRITY)
    with pytest.raises(RuntimeError):
        with store.transaction() as tx:
            tx.session_by_addr(1)


def test_data_key_must_be_32_bytes(tmp_path):
    with pytest.raises(ValueError):
        DurableJoinStore(tmp_path / "bad.sqlite", INTEGRITY, bytes(16))


def test_legacy_plaintext_database_is_refused(tmp_path):
    path = tmp_path / "legacy.sqlite"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE sessions (dev_addr INTEGER PRIMARY KEY, dev_eui BLOB NOT NULL, "
                 "f_nwk_s_int_key BLOB NOT NULL)")
    conn.commit()
    conn.close()
    os.chmod(path, 0o600)
    with pytest.raises(ValueError, match="format de développement"):
        DurableJoinStore(path, INTEGRITY, DATA_KEY)


def test_serve_requires_data_key(tmp_path, monkeypatch):
    from lsim import serve
    monkeypatch.setenv("LSIM_INTEGRITY_KEY", INTEGRITY.hex())
    monkeypatch.delenv("LSIM_DATA_KEY", raising=False)
    with pytest.raises(ValueError, match="LSIM_DATA_KEY"):
        serve.open_store(tmp_path / "x.sqlite")
