"""Rejoin-request LoRaWAN 1.1 (types 0, 1, 2) via le cœur natif.

Les clés sont passées à chaque appel et ne sont jamais stockées par ce module.
Type 0 et 2 : MIC par SNwkSIntKey. Type 1 : MIC par JSIntKey.
Le garde anti-rejeu (RJcount, DevNonce) est un état serveur : il n'est pas exposé ici.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass

from lsim._native import LIB, _CRejoin02, _CRejoin1, _U8P
from lsim.lora import StatusError


def _bytes(name: str, value: bytes, size: int) -> ctypes.Array:
    if not isinstance(value, (bytes, bytearray)) or len(value) != size:
        raise ValueError(f"{name} doit être une séquence de {size} octets")
    return (ctypes.c_uint8 * size).from_buffer_copy(bytes(value))


def _u16(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 0xFFFF:
        raise ValueError(f"{name} doit tenir sur 16 bits")
    return value


def _check(status: int) -> None:
    if status != 0:
        raise StatusError(status)


@dataclass(frozen=True)
class Rejoin02:
    """Rejoin-request type 0 ou 2 : NetID (3 octets) et DevEUI (8 octets) en ordre de transmission."""

    rejoin_type: int
    net_id: bytes
    dev_eui: bytes
    rjcount0: int

    def __post_init__(self) -> None:
        if self.rejoin_type not in (0, 2):
            raise ValueError("rejoin_type doit valoir 0 ou 2")
        _bytes("net_id", self.net_id, 3)
        _bytes("dev_eui", self.dev_eui, 8)
        _u16("rjcount0", self.rjcount0)


@dataclass(frozen=True)
class Rejoin1:
    """Rejoin-request type 1 : JoinEUI et DevEUI (8 octets chacun) en ordre de transmission."""

    join_eui: bytes
    dev_eui: bytes
    rjcount1: int

    def __post_init__(self) -> None:
        _bytes("join_eui", self.join_eui, 8)
        _bytes("dev_eui", self.dev_eui, 8)
        _u16("rjcount1", self.rjcount1)


def encode_02(msg: Rejoin02, s_nwk_s_int_key: bytes) -> bytes:
    """Message type 0 ou 2 de 19 octets, MIC inclus."""
    f = _CRejoin02()
    f.rejoin_type = msg.rejoin_type
    f.net_id[:] = list(msg.net_id)
    f.dev_eui[:] = list(msg.dev_eui)
    f.rjcount0 = msg.rjcount0
    key = _bytes("s_nwk_s_int_key", s_nwk_s_int_key, 16)
    out = (ctypes.c_uint8 * 19)()
    _check(LIB.lsim_rejoin_encode_02(ctypes.byref(f), ctypes.cast(key, _U8P), out))
    return bytes(out)


def decode_02(data: bytes, s_nwk_s_int_key: bytes) -> Rejoin02:
    """Ouvre un message type 0 ou 2 ; lève StatusError si le MIC est invalide."""
    buf = (ctypes.c_uint8 * len(data)).from_buffer_copy(bytes(data)) if data else (ctypes.c_uint8 * 1)()
    key = _bytes("s_nwk_s_int_key", s_nwk_s_int_key, 16)
    out = _CRejoin02()
    _check(LIB.lsim_rejoin_decode_02(ctypes.cast(buf, _U8P), len(data), ctypes.cast(key, _U8P),
                                     ctypes.byref(out)))
    return Rejoin02(out.rejoin_type, bytes(out.net_id), bytes(out.dev_eui), out.rjcount0)


def encode_1(msg: Rejoin1, js_int_key: bytes) -> bytes:
    """Message type 1 de 24 octets, MIC inclus."""
    f = _CRejoin1()
    f.join_eui[:] = list(msg.join_eui)
    f.dev_eui[:] = list(msg.dev_eui)
    f.rjcount1 = msg.rjcount1
    key = _bytes("js_int_key", js_int_key, 16)
    out = (ctypes.c_uint8 * 24)()
    _check(LIB.lsim_rejoin_encode_1(ctypes.byref(f), ctypes.cast(key, _U8P), out))
    return bytes(out)


def decode_1(data: bytes, js_int_key: bytes) -> Rejoin1:
    """Ouvre un message type 1 ; lève StatusError si le MIC est invalide."""
    buf = (ctypes.c_uint8 * len(data)).from_buffer_copy(bytes(data)) if data else (ctypes.c_uint8 * 1)()
    key = _bytes("js_int_key", js_int_key, 16)
    out = _CRejoin1()
    _check(LIB.lsim_rejoin_decode_1(ctypes.cast(buf, _U8P), len(data), ctypes.cast(key, _U8P),
                                    ctypes.byref(out)))
    return Rejoin1(bytes(out.join_eui), bytes(out.dev_eui), out.rjcount1)
