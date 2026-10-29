"""Basic Station : WebSocket (RFC 6455), messages LNS, parcours complet sur un serveur réel.

Les trames envoyées par la « passerelle » sont produites par les encodeurs du cœur
(`encode_join_request`, `seal_uplink`) puis converties en messages JSON : la reconstruction
doit retomber exactement sur les mêmes octets.
"""

import asyncio
import base64
import json
import struct
from types import SimpleNamespace

import pytest

from lsim import wsproto
from lsim.basicstation import (
    BasicStationServer, downlink_message, format_eui, jreq_to_wire, parse_eui,
    router_config, sx1301_conf, start_basicstation_server, updf_to_wire,
)
from lsim.plan import get_plan
from lsim.security import JoinRequest, decode_join_accept, derive_session_keys_11, encode_join_request
from test_uplink import APP, DEV, JOIN_EUI, NWK, Env, open_dl, up

KEY = base64.b64encode(bytes(range(16))).decode()
EU = get_plan("EU868")
US = get_plan("US915")
AU = get_plan("AU915")


# --- Client WebSocket de test ----------------------------------------------------------------

async def ws_open(port, path="/", key=KEY, extra=""):
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write((f"GET {path} HTTP/1.1\r\nHost: test\r\nUpgrade: websocket\r\n"
                  f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
                  f"Sec-WebSocket-Version: 13\r\n{extra}\r\n").encode())
    await writer.drain()
    head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)
    return reader, writer, head


async def ws_frame(reader):
    b0, b1 = await asyncio.wait_for(reader.readexactly(2), 5)
    length = b1 & 0x7F
    if length == 126:
        length = struct.unpack(">H", await reader.readexactly(2))[0]
    elif length == 127:
        length = struct.unpack(">Q", await reader.readexactly(8))[0]
    return b0 & 0x0F, await reader.readexactly(length)


async def send_json(writer, doc):
    writer.write(wsproto.encode_frame(wsproto.OP_TEXT, json.dumps(doc).encode(), mask=True))
    await writer.drain()


async def recv_json(reader):
    opcode, payload = await ws_frame(reader)
    assert opcode == wsproto.OP_TEXT, opcode
    return json.loads(payload)


async def close_code(reader):
    opcode, payload = await ws_frame(reader)
    assert opcode == wsproto.OP_CLOSE
    return struct.unpack(">H", payload[:2])[0] if len(payload) >= 2 else None


async def with_server(handler, body, *, plan=EU, uri="ws://127.0.0.1:8887/ws", **kwargs):
    server = BasicStationServer(handler, plan, net_id=0x13, uri=uri, **kwargs)
    listener = await start_basicstation_server(server, "127.0.0.1", 0)
    port = listener.sockets[0].getsockname()[1]
    try:
        await body(server, port)
    finally:
        listener.close()
        await listener.wait_closed()
    return server


# --- Handshake et trames ---------------------------------------------------------------------

def test_accept_key_matches_rfc6455_example():
    assert wsproto.accept_key("dGhlIHNhbXBsZSBub25jZQ==") == "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="


@pytest.mark.parametrize("size", [0, 1, 125, 126, 65535, 65536])
def test_masked_frame_roundtrip_all_length_forms(size):
    payload = bytes(i & 0xFF for i in range(size))

    async def run():
        reader = asyncio.StreamReader()
        reader.feed_data(wsproto.encode_frame(wsproto.OP_TEXT, payload, mask=True))
        reader.feed_eof()
        conn = wsproto.WsConnection(reader, None, max_message=1 << 20, idle_timeout_s=5)
        fin, opcode, data = await conn._read_frame()
        assert (fin, opcode, data) == (True, wsproto.OP_TEXT, payload)

    asyncio.run(run())


def test_http_rejections_use_proper_status():
    async def run(server, port):
        for head, status in [
            (b"POST /ws HTTP/1.1\r\nHost: t\r\n\r\n", b"405"),
            (b"GET /ws HTTP/1.1\r\nHost: t\r\n\r\n", b"400"),
        ]:
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(head)
            await writer.drain()
            assert (await asyncio.wait_for(reader.readline(), 5)).split()[1] == status
            writer.close()
        reader, writer, head_resp = await ws_open(port, extra="")  # contrôle : valide
        assert head_resp.startswith(b"HTTP/1.1 101")
        writer.close()
        reader, writer, head_resp = await ws_open(port, key=base64.b64encode(b"short").decode())
        assert head_resp.startswith(b"HTTP/1.1 400")
        writer.close()

    asyncio.run(with_server(None, run))


def test_wrong_websocket_version_is_426():
    async def run(server, port):
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write((f"GET /ws HTTP/1.1\r\nHost: t\r\nUpgrade: websocket\r\n"
                      f"Connection: Upgrade\r\nSec-WebSocket-Key: {KEY}\r\n"
                      f"Sec-WebSocket-Version: 8\r\n\r\n").encode())
        await writer.drain()
        assert (await reader.readline()).split()[1] == b"426"
        writer.close()

    asyncio.run(with_server(None, run))


def test_unmasked_client_frame_closes_with_1002():
    async def run(server, port):
        reader, writer, _ = await ws_open(port)
        writer.write(wsproto.encode_frame(wsproto.OP_TEXT, b'{"msgtype":"version"}'))  # sans masque
        await writer.drain()
        assert await close_code(reader) == 1002
        writer.close()

    asyncio.run(with_server(None, run))


def test_binary_frame_closes_with_1003_and_reserved_bits_with_1002():
    async def run(server, port):
        reader, writer, _ = await ws_open(port)
        writer.write(wsproto.encode_frame(wsproto.OP_BINARY, b"\x00", mask=True))
        await writer.drain()
        assert await close_code(reader) == 1003
        writer.close()
        reader, writer, _ = await ws_open(port)
        frame = bytearray(wsproto.encode_frame(wsproto.OP_TEXT, b"{}", mask=True))
        frame[0] |= 0x40                                                    # RSV1
        writer.write(bytes(frame))
        await writer.drain()
        assert await close_code(reader) == 1002
        writer.close()

    asyncio.run(with_server(None, run))


def test_oversized_message_closes_with_1009_before_reading_payload():
    async def run(server, port):
        reader, writer, _ = await ws_open(port)
        header = bytes([0x81, 0x80 | 127]) + struct.pack(">Q", 10**9) + b"\x00\x00\x00\x00"
        writer.write(header)                    # annonce 1 Go, n'envoie rien
        await writer.drain()
        assert await close_code(reader) == 1009
        writer.close()

    asyncio.run(with_server(None, run))


def test_invalid_utf8_closes_with_1007():
    async def run(server, port):
        reader, writer, _ = await ws_open(port)
        writer.write(wsproto.encode_frame(wsproto.OP_TEXT, b"\xff\xfe", mask=True))
        await writer.drain()
        assert await close_code(reader) == 1007
        writer.close()

    asyncio.run(with_server(None, run))


def test_ping_is_answered_with_pong():
    async def run(server, port):
        reader, writer, _ = await ws_open(port)
        writer.write(wsproto.encode_frame(wsproto.OP_PING, b"abc", mask=True))
        await writer.drain()
        assert await ws_frame(reader) == (wsproto.OP_PONG, b"abc")
        writer.close()

    asyncio.run(with_server(None, run))


# --- Conversions : vérité terrain = encodeurs du cœur -----------------------------------------

def test_jreq_reconstructs_the_exact_join_request():
    wire = encode_join_request(JoinRequest(JOIN_EUI, DEV, (5).to_bytes(2, "little")), NWK)
    msg = {"msgtype": "jreq", "MHdr": wire[0], "JoinEui": format_eui(JOIN_EUI[::-1]),
           "DevEui": format_eui(DEV[::-1]), "DevNonce": 5,
           "MIC": int.from_bytes(wire[19:23], "little", signed=True)}
    assert jreq_to_wire(msg) == wire


def test_updf_reconstructs_the_exact_data_frame():
    env = Env(_tmp())
    addr, keys = env.join_device(dev_nonce=1)
    wire = up(keys, addr, 7, b"data", fport=2, confirmed=True, ack=False, dr=5, ch=0)
    fctrl = wire[5]
    fopts_len = fctrl & 0x0F
    body = wire[8 + fopts_len:-4]
    msg = {"msgtype": "updf", "MHdr": wire[0],
           "DevAddr": int.from_bytes(wire[1:5], "little", signed=True),
           "FCtrl": fctrl, "FCnt": int.from_bytes(wire[6:8], "little"),
           "FOpts": wire[8:8 + fopts_len].hex(), "FPort": body[0], "FRMPayload": body[1:].hex(),
           "MIC": int.from_bytes(wire[-4:], "little", signed=True)}
    assert updf_to_wire(msg) == wire


def test_inconsistent_fopts_and_orphan_payload_are_refused():
    base = {"msgtype": "updf", "MHdr": 0x40, "DevAddr": 1, "FCtrl": 0x00, "FCnt": 0,
            "FOpts": "", "FPort": -1, "FRMPayload": "", "MIC": 0}
    updf_to_wire(base)                                                      # valide
    with pytest.raises(ValueError):
        updf_to_wire({**base, "FCtrl": 0x03})                               # FOpts annoncés, absents
    with pytest.raises(ValueError):
        updf_to_wire({**base, "FRMPayload": "00"})                          # charge sans FPort


@pytest.mark.parametrize("bad", ["", "AA-BB", "GG-" * 7 + "GG", True, 2**64, "00" * 9])
def test_eui_parsing_refuses_malformed(bad):
    with pytest.raises(ValueError):
        parse_eui(bad)


def test_eui_accepts_dashed_plain_and_integer_forms():
    expected = bytes.fromhex("0102030405060708")
    assert parse_eui("01-02-03-04-05-06-07-08") == expected
    assert parse_eui("0102030405060708") == expected
    assert parse_eui(0x0102030405060708) == expected


# --- router_config et sx1301_conf ------------------------------------------------------------

def test_router_config_uses_plan_tables():
    doc = router_config(US, net_id=0x13, hwspec="sx1302/1")
    assert doc["region"] == "US915" and doc["NetID"] == [0x13]
    assert len(doc["DRs"]) == 16 and len(doc["sx1301_conf"]) == 1
    assert doc["DRs"][4] == [8, 500, 0] and doc["DRs"][8] == [12, 500, 1]     # DR8 descendant seul
    assert doc["freq_range"] == [902_300_000, 927_500_000]
    assert json.dumps(doc)                                                    # sérialisable


@pytest.mark.parametrize("plan", [EU, US, AU])
def test_sx1301_conf_fits_one_concentrator(plan):
    conf = sx1301_conf(plan.uplink_channels_hz())
    radio = conf["radio_0"]["freq"]
    enabled = [conf[f"chan_multiSF_{i}"] for i in range(8) if conf[f"chan_multiSF_{i}"]["enable"]]
    assert len(enabled) == min(8, len(plan.uplink_channels_hz()))
    for ch, entry in zip(plan.uplink_channels_hz()[:8], enabled):
        assert radio + entry["if"] == ch                                       # IF = canal - centre


def test_sx1301_conf_refuses_channels_outside_one_radio():
    with pytest.raises(ValueError):
        sx1301_conf((868_000_000, 870_500_000))                               # écart > 1,2 MHz


# --- Downlink : RxDelay et RX2 ----------------------------------------------------------------

def test_downlink_message_carries_rx1_delay_and_rx2():
    txpk = SimpleNamespace(tmst=(1_000_000 + 5_000_000) % 2**32, freq_mhz=868.1,
                           datr="SF7BW125", payload=b"\x20\x01\x02")
    outcome = SimpleNamespace(txpk=txpk, dev_eui=DEV)
    msg = downlink_message(outcome, 1_000_000, 42, 7, EU, diid=3)
    assert msg["msgtype"] == "dnmsg" and msg["dC"] == 0 and msg["diid"] == 3
    assert msg["DevEui"] == format_eui(DEV[::-1]) and msg["pdu"] == "200102"
    assert msg["RxDelay"] == 5 and msg["RX1Freq"] == 868_100_000 and msg["RX1DR"] == 5
    assert msg["RX2Freq"] == 869_525_000 and msg["RX2DR"] == 0
    assert msg["xtime"] == 42 and msg["rctx"] == 7


# --- Parcours complet sur un serveur réel -----------------------------------------------------

def _tmp():
    import tempfile
    from pathlib import Path
    return Path(tempfile.mkdtemp())


def test_discovery_returns_uri_and_muxs():
    async def run(server, port):
        reader, writer, head = await ws_open(port, path="/router-info")
        assert head.startswith(b"HTTP/1.1 101")
        await send_json(writer, {"router": "AA-BB-CC-DD-EE-FF-00-11"})
        reply = await recv_json(reader)
        assert reply == {"router": "AA-BB-CC-DD-EE-FF-00-11", "muxs": "00-00-00-00-00-00-00-01",
                         "uri": "ws://127.0.0.1:8887/ws"}
        assert await close_code(reader) == 1000
        writer.close()

    asyncio.run(with_server(None, run))


def test_discovery_refuses_invalid_identity():
    async def run(server, port):
        reader, writer, _ = await ws_open(port, path="/router-info")
        await send_json(writer, {"router": "pas-une-eui"})
        assert "error" in await recv_json(reader)
        writer.close()

    asyncio.run(with_server(None, run))


def test_full_session_join_then_confirmed_uplink_gets_ack_in_rx1():
    env = Env(_tmp())

    async def run(server, port):
        reader, writer, _ = await ws_open(port)
        await send_json(writer, {"msgtype": "version", "station": "2.0.6", "model": "rak7289",
                                 "protocol": 2, "features": "prod"})
        config = await recv_json(reader)
        assert config["msgtype"] == "router_config" and config["region"] == "EU868"
        assert config["NetID"] == [0x13] and len(config["DRs"]) == 16

        # Join-request reçue sur 868,1 MHz / SF7BW125 (DR5), comme la passerelle la rapporte.
        join_wire = encode_join_request(JoinRequest(JOIN_EUI, DEV, (1).to_bytes(2, "little")), NWK)
        await send_json(writer, {
            "msgtype": "jreq", "MHdr": join_wire[0], "JoinEui": format_eui(JOIN_EUI[::-1]),
            "DevEui": format_eui(DEV[::-1]), "DevNonce": 1,
            "MIC": int.from_bytes(join_wire[19:23], "little", signed=True),
            "DR": 5, "Freq": 868_100_000,
            "upinfo": {"rctx": 0, "xtime": 2_000_000, "gpstime": 0, "rssi": -60, "snr": 7.0}})
        dn = await recv_json(reader)
        assert dn["msgtype"] == "dnmsg" and dn["RxDelay"] == 5          # join-accept : 5 s
        assert dn["RX1Freq"] == 868_100_000 and dn["RX1DR"] == 5 and dn["xtime"] == 2_000_000
        assert dn["RX2Freq"] == 869_525_000
        accept = bytes.fromhex(dn["pdu"])
        decoded = decode_join_accept(accept, NWK, DEV, JOIN_EUI, (1).to_bytes(2, "little"))
        keys = derive_session_keys_11(NWK, APP, decoded.join_nonce, JOIN_EUI,
                                      (1).to_bytes(2, "little"))
        addr = decoded.dev_addr

        # Uplink confirmé (DR5, canal 0) : ACK en RX1 à +1 s.
        wire = up(keys, addr, 0, b"hello", fport=1, confirmed=True, dr=5, ch=0)
        body = wire[8:-4]
        await send_json(writer, {
            "msgtype": "updf", "MHdr": wire[0], "DevAddr": int.from_bytes(wire[1:5], "little", signed=True),
            "FCtrl": wire[5], "FCnt": int.from_bytes(wire[6:8], "little"), "FOpts": "",
            "FPort": body[0], "FRMPayload": body[1:].hex(),
            "MIC": int.from_bytes(wire[-4:], "little", signed=True),
            "DR": 5, "Freq": 868_100_000,
            "upinfo": {"rctx": 0, "xtime": 3_000_000, "gpstime": 0, "rssi": -70, "snr": 5.0}})
        ack = await recv_json(reader)
        assert ack["RxDelay"] == 1 and ack["xtime"] == 3_000_000
        frame = open_dl(SimpleNamespace(payload=bytes.fromhex(ack["pdu"])), keys, conf=0, nfcnt=0)
        assert frame.ack is True

        # Message altéré : rejeté, sans réponse, connexion maintenue.
        await send_json(writer, {
            "msgtype": "updf", "MHdr": wire[0], "DevAddr": int.from_bytes(wire[1:5], "little", signed=True),
            "FCtrl": wire[5], "FCnt": 1, "FOpts": "", "FPort": 1, "FRMPayload": "00",
            "MIC": 12345, "DR": 5, "Freq": 868_100_000,
            "upinfo": {"rctx": 0, "xtime": 4_000_000, "gpstime": 0, "rssi": -70, "snr": 5.0}})
        await send_json(writer, {"msgtype": "dntxed", "diid": 1, "DevEui": format_eui(DEV[::-1]),
                                 "rctx": 0, "xtime": 0, "txtime": 0.0, "gpstime": 0})
        await asyncio.sleep(0.2)
        assert server.stats["data_mic_failed"] == 1 and server.stats["dntxed"] == 1
        assert server.stats["downlink_sent"] == 2
        writer.close()

    server = asyncio.run(with_server(env.router, run))
    assert server.stats["sessions"] == 1


def test_queued_downlink_is_sent_on_next_uplink():
    env = Env(_tmp())

    async def run(server, port):
        reader, writer, _ = await ws_open(port)
        await send_json(writer, {"msgtype": "version", "protocol": 2})
        await recv_json(reader)
        join_wire = encode_join_request(JoinRequest(JOIN_EUI, DEV, (1).to_bytes(2, "little")), NWK)
        await send_json(writer, {
            "msgtype": "jreq", "MHdr": join_wire[0], "JoinEui": format_eui(JOIN_EUI[::-1]),
            "DevEui": format_eui(DEV[::-1]), "DevNonce": 1,
            "MIC": int.from_bytes(join_wire[19:23], "little", signed=True),
            "DR": 5, "Freq": 868_100_000, "upinfo": {"xtime": 1_000_000}})
        accept = await recv_json(reader)
        decoded = decode_join_accept(bytes.fromhex(accept["pdu"]), NWK, DEV, JOIN_EUI,
                                     (1).to_bytes(2, "little"))
        keys = derive_session_keys_11(NWK, APP, decoded.join_nonce, JOIN_EUI, (1).to_bytes(2, "little"))
        env.store.enqueue_downlink(DEV, 1, False, b"cmd", EU)
        wire = up(keys, decoded.dev_addr, 0, b"x", fport=1, dr=5, ch=0)
        body = wire[8:-4]
        await send_json(writer, {
            "msgtype": "updf", "MHdr": wire[0], "DevAddr": int.from_bytes(wire[1:5], "little", signed=True),
            "FCtrl": wire[5], "FCnt": 0, "FOpts": "", "FPort": body[0],
            "FRMPayload": body[1:].hex(), "MIC": int.from_bytes(wire[-4:], "little", signed=True),
            "DR": 5, "Freq": 868_100_000, "upinfo": {"xtime": 2_000_000}})
        dn = await recv_json(reader)
        frame = open_dl(SimpleNamespace(payload=bytes.fromhex(dn["pdu"])), keys, conf=0, nfcnt=0)
        assert frame.payload == b"cmd" and frame.fport == 1
        writer.close()

    asyncio.run(with_server(env.router, run))


def test_unknown_msgtype_and_bad_json_do_not_end_session():
    async def run(server, port):
        reader, writer, _ = await ws_open(port)
        await send_json(writer, {"msgtype": "version"})
        await recv_json(reader)
        writer.write(wsproto.encode_frame(wsproto.OP_TEXT, b"{pas du json", mask=True))
        await send_json(writer, {"msgtype": "rmtsh"})
        await send_json(writer, {"msgtype": "timesync", "txtime": 77})
        reply = await recv_json(reader)
        assert reply["msgtype"] == "timesync" and reply["txtime"] == 77 and reply["gpstime"] > 0
        assert server.stats["bad_json"] == 1 and server.stats["unknown_msgtype"] == 1
        writer.close()

    asyncio.run(with_server(None, run))


def test_first_message_must_be_version():
    async def run(server, port):
        reader, writer, _ = await ws_open(port)
        await send_json(writer, {"msgtype": "updf"})
        assert await close_code(reader) == 1002
        writer.close()

    asyncio.run(with_server(None, run))


def test_connection_limit_refuses_with_503():
    async def run(server, port):
        r1, w1, _ = await ws_open(port)
        await send_json(w1, {"msgtype": "version"})
        await recv_json(r1)
        r2, w2 = await asyncio.open_connection("127.0.0.1", port)
        w2.write(b"GET /ws HTTP/1.1\r\nHost: t\r\n\r\n")
        await w2.drain()
        assert (await r2.readline()).split()[1] == b"503"
        w1.close()
        w2.close()

    asyncio.run(with_server(None, run, max_connections=1))


def test_uri_scheme_and_tls_pairing_are_checked_by_cli_layer():
    from lsim.serve import run_basicstation
    from pathlib import Path
    with pytest.raises(ValueError):
        run_basicstation("127.0.0.1", 0, Path("x.sqlite"), Path("k.json"), "000013", "EU868",
                         "http://nope")
    with pytest.raises(ValueError):
        run_basicstation("127.0.0.1", 0, Path("x.sqlite"), Path("k.json"), "000013", "EU868",
                         "ws://x", tls_cert="c.pem", tls_key=None)



def test_silent_client_is_disconnected_after_handshake_timeout(monkeypatch):
    monkeypatch.setattr(wsproto, "HANDSHAKE_TIMEOUT_S", 0.2)

    async def run(server, port):
        for path in ("/ws", "/router-info"):
            reader, writer, _ = await ws_open(port, path=path)
            # Aucun premier message : fermeture 1000 envoyée par le serveur, puis EOF.
            assert await asyncio.wait_for(reader.read(10), 5) == b"\x88\x02\x03\xe8"
            writer.close()
        await asyncio.sleep(0.05)
        assert server.stats["handshake_timeout"] == 2

    asyncio.run(with_server(None, run))
