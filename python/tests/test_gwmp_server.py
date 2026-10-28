"""Serveur GWMP : acquittements, routes, join-accept décodable par le dispositif (UDP réel)."""

import asyncio
import base64
import json

import pytest

from lsim import gwmp
from lsim.gwmp import Txpk
from lsim.gwmp_server import JOIN_ACCEPT_DELAY1_US, GwmpServer, JoinUplinkHandler, start_server
from lsim.join_server import DeviceKeys, JoinServer
from lsim.join_store import DurableJoinStore
from lsim.security import JoinRequest, decode_join_accept, encode_join_request

NET_ID = bytes([0x13, 0x00, 0x00])
JOIN_EUI = bytes.fromhex("1122334455667788")
DEV = bytes.fromhex("0102030405060708")
GW = bytes.fromhex("aabbccddeeff0011")
NWK = bytes(range(0x10, 0x20))
INTEGRITY = bytes(range(16))


def _keys(dev_eui):
    if dev_eui != DEV:
        raise KeyError("inconnu")
    return DeviceKeys(NWK)


def _join_wire(dev_nonce: int = 1) -> bytes:
    req = JoinRequest(JOIN_EUI, DEV, dev_nonce.to_bytes(2, "little"))
    return encode_join_request(req, NWK)


def _handler(tmp_path) -> JoinUplinkHandler:
    store = DurableJoinStore(tmp_path / "join.sqlite", INTEGRITY)
    return JoinUplinkHandler(JoinServer(store, NET_ID, _keys))


def _join_rxpk(wire: bytes, tmst: int = 1_000_000) -> dict:
    return {"tmst": tmst, "chan": 0, "rfch": 0, "freq": 868.1, "stat": 1, "modu": "LORA",
            "datr": "SF7BW125", "codr": "4/5", "rssi": -60, "lsnr": 7.0,
            "size": len(wire), "data": base64.b64encode(wire).decode()}


class _Client(asyncio.DatagramProtocol):
    def __init__(self):
        self.queue: asyncio.Queue = asyncio.Queue()

    def datagram_received(self, data, addr):
        self.queue.put_nowait(data)


async def _recv(queue, timeout=5.0) -> bytes:
    return await asyncio.wait_for(queue.get(), timeout)


def test_join_accept_is_delivered_in_rx1_and_decodes_on_device(tmp_path):
    async def scenario():
        transport, server = await start_server(_handler(tmp_path), "127.0.0.1", 0)
        port = transport.get_extra_info("sockname")[1]
        loop = asyncio.get_running_loop()
        client_t, client = await loop.create_datagram_endpoint(
            _Client, remote_addr=("127.0.0.1", port))
        try:
            client_t.sendto(gwmp.build_pull_data(b"\x00\x01", GW))
            assert await _recv(client.queue) == b"\x02\x00\x01\x04"          # PULL_ACK
            wire = _join_wire(7)
            client_t.sendto(gwmp.build_push_data(b"\x00\x02", GW, [_join_rxpk(wire)]))
            assert await _recv(client.queue) == b"\x02\x00\x02\x01"          # PUSH_ACK
            resp = await _recv(client.queue)                                 # PULL_RESP
            assert resp[:4][3] == gwmp.PULL_RESP
            txpk = json.loads(resp[4:])["txpk"]
            assert txpk["tmst"] == 1_000_000 + JOIN_ACCEPT_DELAY1_US
            assert txpk["freq"] == pytest.approx(868.1) and txpk["datr"] == "SF7BW125"
            accept = base64.b64decode(txpk["data"])
            decoded = decode_join_accept(accept, NWK, DEV, JOIN_EUI, (7).to_bytes(2, "little"))
            assert decoded.dev_addr >> 25 == 0x13
            await server.drain()
            assert server.stats["join_accepted"] == 1
        finally:
            client_t.close()
            transport.close()
    asyncio.run(scenario())


def test_replayed_join_gets_no_second_accept(tmp_path):
    async def scenario():
        transport, server = await start_server(_handler(tmp_path), "127.0.0.1", 0)
        port = transport.get_extra_info("sockname")[1]
        loop = asyncio.get_running_loop()
        client_t, client = await loop.create_datagram_endpoint(
            _Client, remote_addr=("127.0.0.1", port))
        try:
            client_t.sendto(gwmp.build_pull_data(b"\x00\x01", GW))
            await _recv(client.queue)                                        # PULL_ACK
            wire = _join_wire(3)
            for token in (b"\x00\x05", b"\x00\x06"):
                client_t.sendto(gwmp.build_push_data(token, GW, [_join_rxpk(wire)]))
            received = []
            try:
                while True:
                    received.append(await _recv(client.queue, timeout=0.5))
            except asyncio.TimeoutError:
                pass
            types = sorted(d[3] for d in received)
            assert types.count(gwmp.PUSH_ACK) == 2
            assert types.count(gwmp.PULL_RESP) == 1                          # un seul join-accept
            await server.drain()
            assert server.stats["join_accepted"] == 1
            assert server.stats["join_rejected"] == 1
        finally:
            client_t.close()
            transport.close()
    asyncio.run(scenario())


def test_invalid_push_is_acked_but_not_processed(tmp_path):
    async def scenario():
        transport, server = await start_server(_handler(tmp_path), "127.0.0.1", 0)
        port = transport.get_extra_info("sockname")[1]
        loop = asyncio.get_running_loop()
        client_t, client = await loop.create_datagram_endpoint(
            _Client, remote_addr=("127.0.0.1", port))
        try:
            client_t.sendto(b"\x02\x00\x09\x00" + GW + b"{pas du json")
            assert await _recv(client.queue) == b"\x02\x00\x09\x01"          # PUSH_ACK quand même
            client_t.sendto(b"\x09garbage")                                  # rien : jeté
            await asyncio.sleep(0.1)
            assert server.stats["dropped_invalid"] == 2
            assert server.stats["join_accepted"] == 0
        finally:
            client_t.close()
            transport.close()
    asyncio.run(scenario())


def test_no_route_means_no_downlink(tmp_path):
    async def scenario():
        transport, server = await start_server(_handler(tmp_path), "127.0.0.1", 0)
        port = transport.get_extra_info("sockname")[1]
        loop = asyncio.get_running_loop()
        client_t, client = await loop.create_datagram_endpoint(
            _Client, remote_addr=("127.0.0.1", port))
        try:
            client_t.sendto(gwmp.build_push_data(b"\x00\x07", GW, [_join_rxpk(_join_wire(4))]))
            await _recv(client.queue)                                       # PUSH_ACK seulement
            await server.drain()
            assert server.stats["join_accepted"] == 1
            assert server.stats["downlink_no_route"] == 1
            with pytest.raises(asyncio.TimeoutError):
                await _recv(client.queue, timeout=0.3)
        finally:
            client_t.close()
            transport.close()
    asyncio.run(scenario())


def test_stale_route_is_not_used(tmp_path):
    now = [0.0]
    handler = _handler(tmp_path)
    server = GwmpServer(handler, pull_timeout_s=10.0, clock=lambda: now[0])
    server._register(GW, ("192.0.2.1", 1700))
    now[0] = 11.0
    server._downlink(GW, Txpk(tmst=1, freq_mhz=868.1, datr="SF7BW125", codr="4/5", payload=b"x"))
    assert server.stats["downlink_no_route"] == 1


def test_rx1_timestamp_wraps_modulo_32_bits(tmp_path):
    handler = _handler(tmp_path)
    from lsim.gwmp import Rxpk
    rx = Rxpk(tmst=2**32 - 1, freq_mhz=868.1, chan=0, rfch=0, crc_ok=True, datr="SF7BW125",
              codr="4/5", rssi=-60, lsnr=7.0, payload=_join_wire(9))
    issue, txpk = handler.handle(rx)
    assert issue == "join_accepted"
    assert txpk.tmst == (2**32 - 1 + JOIN_ACCEPT_DELAY1_US) % 2**32


def test_rejoin_and_data_are_counted_not_answered(tmp_path):
    from lsim.gwmp import Rxpk
    handler = _handler(tmp_path)

    def rx(payload):
        return Rxpk(tmst=1, freq_mhz=868.1, chan=0, rfch=0, crc_ok=True, datr="SF7BW125",
                    codr="4/5", rssi=-60, lsnr=7.0, payload=payload)
    assert handler.handle(rx(bytes([0xC0]) + b"\x00" * 18)) == ("rejoin_unanswered", None)
    assert handler.handle(rx(bytes([0x40]) + b"\x00" * 10)) == ("data_unhandled", None)
