"""WebSocket serveur (RFC 6455) minimal, sans dépendance : transport des messages Basic Station.

Périmètre volontairement réduit :
- handshake HTTP/1.1 GET avec Upgrade, version 13, clé de 16 octets ; tout autre cas : 400/404 ;
- trames texte, fragmentées ou non ; trames binaires refusées (1003) ;
- trames de contrôle ping (pong renvoyé), pong ignoré, close (écho puis fermeture) ;
- client obligatoirement masqué (RFC 6455 §5.1) ; RSV1-3 à 0 ; longueurs bornées AVANT lecture
  de la charge, pour que la mémoire reste plafonnée par `max_message` ;
- UTF-8 vérifié ; délai d'inactivité borné.

Limites : pas d'extensions (permessage-deflate), pas de sous-protocoles, pas de TLS ici
(`lsim.basicstation` fournit le contexte SSL). Source : RFC 6455 ; ce module n'est pas une copie.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import struct
from typing import Optional

GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
OP_CONT, OP_TEXT, OP_BINARY, OP_CLOSE, OP_PING, OP_PONG = 0x0, 0x1, 0x2, 0x8, 0x9, 0xA
MAX_HEADER_BYTES = 8192
HANDSHAKE_TIMEOUT_S = 10.0

CLOSE_NORMAL = 1000
CLOSE_PROTOCOL = 1002
CLOSE_UNSUPPORTED = 1003
CLOSE_INVALID_DATA = 1007
CLOSE_TOO_BIG = 1009


class WsError(Exception):
    """Violation du protocole ; `code` est le code de fermeture à envoyer."""

    def __init__(self, code: int, reason: str = "") -> None:
        super().__init__(reason or str(code))
        self.code = code


class HttpError(Exception):
    def __init__(self, status: int, reason: str) -> None:
        super().__init__(reason)
        self.status = status
        self.reason = reason


def accept_key(client_key: str) -> str:
    digest = hashlib.sha1(client_key.encode("ascii") + GUID).digest()
    return base64.b64encode(digest).decode("ascii")


async def read_request(reader: asyncio.StreamReader) -> tuple[str, str, dict[str, str]]:
    """Lit l'en-tête HTTP ; retourne (méthode, cible, en-têtes en minuscules)."""
    try:
        raw = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), HANDSHAKE_TIMEOUT_S)
    except asyncio.LimitOverrunError:
        raise HttpError(431, "en-têtes trop volumineux") from None
    except (asyncio.IncompleteReadError, asyncio.TimeoutError, ConnectionError):
        raise HttpError(400, "requête incomplète") from None
    if len(raw) > MAX_HEADER_BYTES:
        raise HttpError(431, "en-têtes trop volumineux")
    try:
        text = raw[:-4].decode("ascii")
    except UnicodeDecodeError:
        raise HttpError(400, "en-têtes non ASCII") from None
    lines = text.split("\r\n")
    parts = lines[0].split(" ")
    if len(parts) != 3 or parts[2] != "HTTP/1.1":
        raise HttpError(400, "ligne de requête invalide")
    headers: dict[str, str] = {}
    for line in lines[1:]:
        name, sep, value = line.partition(":")
        if not sep or not name or name != name.strip():
            raise HttpError(400, "en-tête invalide")
        key = name.lower()
        if key in headers:
            raise HttpError(400, "en-tête dupliqué")
        headers[key] = value.strip()
    return parts[0], parts[1], headers


def check_upgrade(method: str, headers: dict[str, str]) -> str:
    """Valide la requête de mise à jour ; retourne la clé Sec-WebSocket-Key."""
    if method != "GET":
        raise HttpError(405, "GET attendu")
    if "upgrade" not in headers.get("connection", "").lower():
        raise HttpError(400, "Connection: Upgrade attendu")
    if headers.get("upgrade", "").lower() != "websocket":
        raise HttpError(400, "Upgrade: websocket attendu")
    if headers.get("sec-websocket-version") != "13":
        raise HttpError(426, "version WebSocket 13 attendue")
    key = headers.get("sec-websocket-key", "")
    try:
        if len(base64.b64decode(key, validate=True)) != 16:
            raise ValueError
    except ValueError:
        raise HttpError(400, "Sec-WebSocket-Key invalide") from None
    return key


def handshake_response(key: str) -> bytes:
    return (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {accept_key(key)}\r\n\r\n"
    ).encode("ascii")


def http_error_response(status: int, reason: str) -> bytes:
    body = reason.encode("utf-8")
    head = (f"HTTP/1.1 {status} {_STATUS_TEXT.get(status, 'Error')}\r\n"
            "Connection: close\r\nContent-Type: text/plain; charset=utf-8\r\n"
            f"Content-Length: {len(body)}\r\n\r\n")
    return head.encode("ascii") + body


_STATUS_TEXT = {400: "Bad Request", 404: "Not Found", 405: "Method Not Allowed",
                426: "Upgrade Required", 431: "Request Header Fields Too Large",
                503: "Service Unavailable"}


def encode_frame(opcode: int, payload: bytes = b"", *, mask: bool = False, fin: bool = True) -> bytes:
    """Trame sortante. Le serveur n'applique pas de masque ; `mask=True` sert aux clients (tests)."""
    head = bytearray([(0x80 if fin else 0) | opcode])
    n = len(payload)
    mask_bit = 0x80 if mask else 0
    if n < 126:
        head.append(mask_bit | n)
    elif n <= 0xFFFF:
        head.append(mask_bit | 126)
        head += struct.pack(">H", n)
    else:
        head.append(mask_bit | 127)
        head += struct.pack(">Q", n)
    if not mask:
        return bytes(head) + payload
    key = bytes(range(0x5A, 0x5E))           # clé fixe : suffisant pour des tests de format
    return bytes(head) + key + _unmask(payload, key)     # XOR involutif


def _unmask(data: bytes, key: bytes) -> bytes:
    n = len(data)
    if n == 0:
        return b""
    rep = (key * (n // 4 + 1))[:n]
    return (int.from_bytes(data, "big") ^ int.from_bytes(rep, "big")).to_bytes(n, "big")


class WsConnection:
    """Connexion WebSocket côté serveur, après handshake.

    `recv_text` renvoie None à la fermeture propre du client ; il lève WsError sur violation
    (le code est à envoyer dans la fermeture). Les écritures sont une trame par appel
    (`writer.write` sans attente intermédiaire) : pas d'entrelacement entre tâches.
    """

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, *,
                 max_message: int, idle_timeout_s: float) -> None:
        self._reader = reader
        self._writer = writer
        self._max = max_message
        self._idle = idle_timeout_s
        self.closed = False

    async def _read_frame(self) -> tuple[bool, int, bytes]:
        try:
            head = await asyncio.wait_for(self._reader.readexactly(2), self._idle)
        except asyncio.TimeoutError:
            raise WsError(CLOSE_NORMAL, "inactivité") from None
        except (asyncio.IncompleteReadError, ConnectionError):
            raise WsError(CLOSE_NORMAL, "connexion coupée") from None
        b0, b1 = head
        if b0 & 0x70:
            raise WsError(CLOSE_PROTOCOL, "RSV non nul")
        fin = bool(b0 & 0x80)
        opcode = b0 & 0x0F
        if not b1 & 0x80:
            raise WsError(CLOSE_PROTOCOL, "trame client non masquée")
        length = b1 & 0x7F
        try:
            if length == 126:
                length = struct.unpack(">H", await self._reader.readexactly(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", await self._reader.readexactly(8))[0]
                if length >> 63:
                    raise WsError(CLOSE_PROTOCOL, "longueur invalide")
            if opcode & 0x8:
                if not fin or length > 125:
                    raise WsError(CLOSE_PROTOCOL, "trame de contrôle invalide")
            elif length > self._max:
                raise WsError(CLOSE_TOO_BIG, "message trop grand")
            key = await self._reader.readexactly(4)
            payload = await self._reader.readexactly(length)
        except (asyncio.IncompleteReadError, ConnectionError):
            raise WsError(CLOSE_NORMAL, "connexion coupée") from None
        return fin, opcode, _unmask(payload, key)

    async def recv_text(self) -> Optional[str]:
        """Message texte suivant ; None si le client ferme. Les pings reçus reçoivent un pong."""
        buffer = bytearray()
        started = False
        while True:
            fin, opcode, payload = await self._read_frame()
            if opcode == OP_PING:
                await self._send_raw(encode_frame(OP_PONG, payload))
                continue
            if opcode == OP_PONG:
                continue
            if opcode == OP_CLOSE:
                await self.close(CLOSE_NORMAL)
                return None
            if opcode == OP_BINARY:
                raise WsError(CLOSE_UNSUPPORTED, "trame binaire non prise en charge")
            if opcode == OP_TEXT:
                if started:
                    raise WsError(CLOSE_PROTOCOL, "fragmentation invalide")
                started = True
            elif opcode == OP_CONT:
                if not started:
                    raise WsError(CLOSE_PROTOCOL, "continuation sans début")
            else:
                raise WsError(CLOSE_PROTOCOL, "opcode inconnu")
            if len(buffer) + len(payload) > self._max:
                raise WsError(CLOSE_TOO_BIG, "message trop grand")
            buffer += payload
            if fin:
                try:
                    return bytes(buffer).decode("utf-8")
                except UnicodeDecodeError:
                    raise WsError(CLOSE_INVALID_DATA, "UTF-8 invalide") from None

    async def send_text(self, text: str) -> None:
        await self._send_raw(encode_frame(OP_TEXT, text.encode("utf-8")))

    async def close(self, code: int = CLOSE_NORMAL) -> None:
        if not self.closed:
            self.closed = True
            try:
                await self._send_raw(encode_frame(OP_CLOSE, struct.pack(">H", code)))
                self._writer.close()
                await self._writer.wait_closed()
            except (ConnectionError, OSError):
                pass

    async def _send_raw(self, data: bytes) -> None:
        if self.closed and not data.startswith(b"\x88"):
            raise ConnectionError("connexion fermée")
        self._writer.write(data)
        await self._writer.drain()
