"""Clés et trames sécurisées LoRaWAN 1.1, calculées par le cœur natif.

Convention d'octets : tous les identifiants et nonces sont passés en ordre de
transmission (LSB first), c'est-à-dire l'inverse de l'affichage TTN/LoRa Alliance.
Les secrets (NwkKey, AppKey, clés de session) sont des `bytes` de 16 octets ;
aucune valeur n'est journalisée ni affichée dans `repr`.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass, field
from typing import Optional

from lsim._native import (
    _CDownlinkContext,
    LIB,
    _CJoinAccept,
    _CJoinKeys,
    _CJoinRequest,
    _CSessionKeys11,
    _CUplinkContext,
    _CUplinkFrame,
)
from lsim.lora import StatusError

MAX_FRM_PAYLOAD = 242
_U8 = ctypes.c_uint8


def _bytes_arg(name: str, value: bytes, size: int) -> ctypes.Array:
    if not isinstance(value, (bytes, bytearray)) or len(value) != size:
        raise ValueError(f"{name} doit être une séquence de {size} octets")
    return (_U8 * size).from_buffer_copy(bytes(value))


def _check(status: int) -> None:
    if status != 0:
        raise StatusError(status)


@dataclass(frozen=True)
class JoinKeys:
    js_enc_key: bytes = field(repr=False)
    js_int_key: bytes = field(repr=False)

    def __repr__(self) -> str:
        return "JoinKeys(<secret>)"


@dataclass(frozen=True)
class SessionKeys11:
    f_nwk_s_int_key: bytes = field(repr=False)
    s_nwk_s_int_key: bytes = field(repr=False)
    nwk_s_enc_key: bytes = field(repr=False)
    app_s_key: bytes = field(repr=False)

    def __repr__(self) -> str:
        return "SessionKeys11(<secret>)"

    def _to_c(self) -> _CSessionKeys11:
        out = _CSessionKeys11()
        out.f_nwk_s_int_key[:] = list(self.f_nwk_s_int_key)
        out.s_nwk_s_int_key[:] = list(self.s_nwk_s_int_key)
        out.nwk_s_enc_key[:] = list(self.nwk_s_enc_key)
        out.app_s_key[:] = list(self.app_s_key)
        return out


def derive_join_keys(nwk_key: bytes, dev_eui: bytes) -> JoinKeys:
    """Clés de jointure (JSEncKey, JSIntKey) à partir de NwkKey et DevEUI."""
    key = _bytes_arg("nwk_key", nwk_key, 16)
    eui = _bytes_arg("dev_eui", dev_eui, 8)
    out = _CJoinKeys()
    _check(LIB.lsim_derive_join_keys(
        ctypes.cast(key, ctypes.POINTER(_U8)),
        ctypes.cast(eui, ctypes.POINTER(_U8)),
        ctypes.byref(out)))
    return JoinKeys(bytes(out.js_enc_key), bytes(out.js_int_key))


def derive_session_keys_11(nwk_key: bytes, app_key: bytes, join_nonce: bytes,
                           join_eui: bytes, dev_nonce: bytes) -> SessionKeys11:
    """Clés de session 1.1 après un join-accept (entrées en ordre de transmission)."""
    arrays = [
        _bytes_arg("nwk_key", nwk_key, 16),
        _bytes_arg("app_key", app_key, 16),
        _bytes_arg("join_nonce", join_nonce, 3),
        _bytes_arg("join_eui", join_eui, 8),
        _bytes_arg("dev_nonce", dev_nonce, 2),
    ]
    ptrs = [ctypes.cast(a, ctypes.POINTER(_U8)) for a in arrays]
    out = _CSessionKeys11()
    _check(LIB.lsim_derive_session_keys_11(*ptrs, ctypes.byref(out)))
    return SessionKeys11(
        bytes(out.f_nwk_s_int_key), bytes(out.s_nwk_s_int_key),
        bytes(out.nwk_s_enc_key), bytes(out.app_s_key))


@dataclass(frozen=True)
class UplinkFrame:
    """Trame uplink de données, en clair côté application.

    fport None : pas de FPort, la charge doit alors être vide.
    """

    dev_addr: int
    fcnt: int
    payload: bytes = b""
    fport: Optional[int] = None
    fopts: bytes = b""  # MAC commands piggybackés, 0..15 octets, interdits avec FPort 0
    confirmed: bool = False
    adr: bool = False
    adr_ack_req: bool = False
    ack: bool = False
    class_b: bool = False

    def __post_init__(self) -> None:
        if not 0 <= self.dev_addr <= 0xFFFFFFFF:
            raise ValueError("dev_addr doit tenir sur 32 bits")
        if not 0 <= self.fcnt <= 0xFFFF:
            raise ValueError("fcnt doit tenir sur 16 bits (le compteur complet va dans UplinkContext)")
        if not isinstance(self.payload, (bytes, bytearray)):
            raise ValueError("payload doit être de type bytes")
        if len(self.payload) > MAX_FRM_PAYLOAD:
            raise ValueError(f"payload limité à {MAX_FRM_PAYLOAD} octets")
        if not isinstance(self.fopts, (bytes, bytearray)) or len(self.fopts) > 15:
            raise ValueError("fopts doit être de type bytes, 15 octets au plus")
        if self.fport is None:
            if self.payload:
                raise ValueError("une charge sans FPort est interdite")
        elif not 0 <= self.fport <= 255:
            raise ValueError("fport doit être compris entre 0 et 255")
        if self.fport == 0 and self.fopts:
            raise ValueError("FOpts interdits avec FPort 0")

    def __repr__(self) -> str:
        return (f"UplinkFrame(dev_addr=0x{self.dev_addr:08X}, fcnt={self.fcnt}, "
                f"fport={self.fport}, len={len(self.payload)})")

    def _to_c(self) -> _CUplinkFrame:
        c = _CUplinkFrame()
        c.dev_addr = self.dev_addr
        c.mtype = 4 if self.confirmed else 2
        c.adr = int(self.adr)
        c.adr_ack_req = int(self.adr_ack_req)
        c.ack = int(self.ack)
        c.class_b = int(self.class_b)
        c.fcnt = self.fcnt
        c.has_fport = 0 if self.fport is None else 1
        c.fport = 0 if self.fport is None else self.fport
        c.payload_len = len(self.payload)
        c.payload[:len(self.payload)] = list(self.payload)
        c.fopts_len = len(self.fopts)
        c.fopts[:len(self.fopts)] = list(self.fopts)
        return c


@dataclass(frozen=True)
class UplinkContext:
    """Contexte 1.1 du MIC et du chiffrement, fourni par le serveur de réseau."""

    fcnt32: int
    conf_fcnt: int = 0
    tx_dr: int = 0
    tx_ch: int = 0

    def __post_init__(self) -> None:
        if not 0 <= self.fcnt32 <= 0xFFFFFFFF:
            raise ValueError("fcnt32 doit tenir sur 32 bits")
        if not 0 <= self.conf_fcnt <= 0xFFFF:
            raise ValueError("conf_fcnt doit tenir sur 16 bits")
        if not 0 <= self.tx_dr <= 255 or not 0 <= self.tx_ch <= 255:
            raise ValueError("tx_dr et tx_ch doivent tenir sur 8 bits")

    def _to_c(self) -> _CUplinkContext:
        c = _CUplinkContext()
        c.conf_fcnt = self.conf_fcnt
        c.tx_dr = self.tx_dr
        c.tx_ch = self.tx_ch
        c.fcnt32 = self.fcnt32
        return c


def seal_uplink(frame: UplinkFrame, keys: SessionKeys11, ctx: UplinkContext) -> bytes:
    """Chiffre la charge puis calcule le MIC 1.1 ; retourne la trame PHY."""
    cap = 1 + 7 + len(frame.fopts) + 1 + len(frame.payload) + 4  # MHDR, FHDR, FOpts, FPort, charge, MIC
    buf = (_U8 * cap)()
    written = ctypes.c_size_t(0)
    cf = frame._to_c()
    ck = keys._to_c()
    cc = ctx._to_c()
    _check(LIB.lsim_seal_uplink(ctypes.byref(cf), ctypes.byref(ck), ctypes.byref(cc),
                                buf, cap, ctypes.byref(written)))
    return bytes(buf[:written.value])


def open_uplink(wire: bytes, keys: SessionKeys11, ctx: UplinkContext) -> UplinkFrame:
    """Vérifie le MIC puis déchiffre. Lève StatusError si le MIC est faux."""
    if not isinstance(wire, (bytes, bytearray)) or not 12 <= len(wire) <= 255:
        raise ValueError("trame PHY de 12 à 255 octets attendue")
    src = (_U8 * len(wire)).from_buffer_copy(bytes(wire))
    ck = keys._to_c()
    cc = ctx._to_c()
    out = _CUplinkFrame()
    _check(LIB.lsim_open_uplink(ctypes.cast(src, ctypes.POINTER(_U8)), len(wire),
                                ctypes.byref(ck), ctypes.byref(cc), ctypes.byref(out)))
    n = out.payload_len
    return UplinkFrame(
        dev_addr=out.dev_addr,
        fcnt=out.fcnt,
        payload=bytes(out.payload[:n]),
        fopts=bytes(out.fopts[:out.fopts_len]),
        fport=out.fport if out.has_fport else None,
        confirmed=out.mtype in (4, 5),
        adr=bool(out.adr),
        adr_ack_req=bool(out.adr_ack_req),
        ack=bool(out.ack),
        class_b=bool(out.class_b),
    )


@dataclass(frozen=True)
class DownlinkContext:
    """Contexte downlink 1.1 : ConfFCnt, NFCntDwn (sans FPort ou FPort 0), AFCntDwn (FPort > 0)."""

    conf_fcnt: int = 0
    nfcnt32: int = 0
    afcnt32: int = 0

    def __post_init__(self) -> None:
        if not 0 <= self.conf_fcnt <= 0xFFFF:
            raise ValueError("conf_fcnt doit tenir sur 16 bits")
        for name in ("nfcnt32", "afcnt32"):
            if not 0 <= getattr(self, name) <= 0xFFFFFFFF:
                raise ValueError(f"{name} doit tenir sur 32 bits")

    def _to_c(self) -> _CDownlinkContext:
        c = _CDownlinkContext()
        c.conf_fcnt = self.conf_fcnt
        c.nfcnt32 = self.nfcnt32
        c.afcnt32 = self.afcnt32
        return c


def seal_downlink(frame: UplinkFrame, keys: SessionKeys11, ctx: DownlinkContext) -> bytes:
    """Chiffre FOpts et charge (compteur selon FPort), puis calcule le MIC downlink 1.1."""
    cap = 1 + 7 + len(frame.fopts) + 1 + len(frame.payload) + 4
    buf = (_U8 * cap)()
    written = ctypes.c_size_t(0)
    cf = frame._to_c()
    ck = keys._to_c()
    cc = ctx._to_c()
    _check(LIB.lsim_seal_downlink(ctypes.byref(cf), ctypes.byref(ck), ctypes.byref(cc),
                                  buf, cap, ctypes.byref(written)))
    return bytes(buf[:written.value])


def open_downlink(wire: bytes, keys: SessionKeys11, ctx: DownlinkContext) -> UplinkFrame:
    """Vérifie le MIC downlink puis déchiffre. Lève StatusError si le MIC est faux."""
    if not isinstance(wire, (bytes, bytearray)) or not 12 <= len(wire) <= 255:
        raise ValueError("trame PHY de 12 à 255 octets attendue")
    src = (_U8 * len(wire)).from_buffer_copy(bytes(wire))
    ck = keys._to_c()
    cc = ctx._to_c()
    out = _CUplinkFrame()
    _check(LIB.lsim_open_downlink(ctypes.cast(src, ctypes.POINTER(_U8)), len(wire),
                                  ctypes.byref(ck), ctypes.byref(cc), ctypes.byref(out)))
    n = out.payload_len
    return UplinkFrame(
        dev_addr=out.dev_addr,
        fcnt=out.fcnt,
        payload=bytes(out.payload[:n]),
        fopts=bytes(out.fopts[:out.fopts_len]),
        fport=out.fport if out.has_fport else None,
        confirmed=out.mtype in (4, 5),
        adr=bool(out.adr),
        adr_ack_req=bool(out.adr_ack_req),
        ack=bool(out.ack),
        class_b=bool(out.class_b),
    )


# ------------------------------------------------------------- Jointure 1.1


@dataclass(frozen=True)
class JoinRequest:
    """Join-request : identifiants en ordre de transmission (LSB first)."""

    join_eui: bytes
    dev_eui: bytes
    dev_nonce: bytes

    def __post_init__(self) -> None:
        _bytes_arg("join_eui", self.join_eui, 8)
        _bytes_arg("dev_eui", self.dev_eui, 8)
        _bytes_arg("dev_nonce", self.dev_nonce, 2)

    def _to_c(self) -> _CJoinRequest:
        c = _CJoinRequest()
        c.join_eui[:] = list(self.join_eui)
        c.dev_eui[:] = list(self.dev_eui)
        c.dev_nonce[:] = list(self.dev_nonce)
        return c


@dataclass(frozen=True)
class JoinAccept:
    """Join-accept en clair. dl_settings bit 7 = OptNeg (1.1 si 1)."""

    join_nonce: bytes
    net_id: bytes
    dev_addr: int
    dl_settings: int = 0
    rx_delay: int = 0
    cflist: Optional[bytes] = None

    def __post_init__(self) -> None:
        _bytes_arg("join_nonce", self.join_nonce, 3)
        _bytes_arg("net_id", self.net_id, 3)
        if not 0 <= self.dev_addr <= 0xFFFFFFFF:
            raise ValueError("dev_addr doit tenir sur 32 bits")
        if not 0 <= self.dl_settings <= 255 or not 0 <= self.rx_delay <= 255:
            raise ValueError("dl_settings et rx_delay doivent tenir sur 8 bits")
        if self.cflist is not None:
            _bytes_arg("cflist", self.cflist, 16)

    def __repr__(self) -> str:
        return (f"JoinAccept(dev_addr=0x{self.dev_addr:08X}, "
                f"optneg={bool(self.dl_settings & 0x80)}, "
                f"cflist={self.cflist is not None})")

    def _to_c(self) -> _CJoinAccept:
        c = _CJoinAccept()
        c.join_nonce[:] = list(self.join_nonce)
        c.net_id[:] = list(self.net_id)
        c.dev_addr = self.dev_addr
        c.dl_settings = self.dl_settings
        c.rx_delay = self.rx_delay
        c.has_cflist = 0 if self.cflist is None else 1
        if self.cflist is not None:
            c.cflist[:] = list(self.cflist)
        return c


def encode_join_request(req: JoinRequest, nwk_key: bytes) -> bytes:
    """Join-request complète (23 octets), MIC 1.1 calculé avec NwkKey."""
    key = _bytes_arg("nwk_key", nwk_key, 16)
    out = (_U8 * 23)()
    _check(LIB.lsim_encode_join_request(ctypes.byref(req._to_c()),
                                        ctypes.cast(key, ctypes.POINTER(_U8)), out))
    return bytes(out)


def decode_join_request(wire: bytes, nwk_key: bytes) -> JoinRequest:
    """Vérifie le MIC d'une join-request (serveur). Lève StatusError sinon."""
    if not isinstance(wire, (bytes, bytearray)):
        raise ValueError("wire doit être de type bytes")
    key = _bytes_arg("nwk_key", nwk_key, 16)
    src = (_U8 * max(len(wire), 1)).from_buffer_copy(bytes(wire) or b"\x00")
    out = _CJoinRequest()
    _check(LIB.lsim_decode_join_request(ctypes.cast(src, ctypes.POINTER(_U8)), len(wire),
                                        ctypes.cast(key, ctypes.POINTER(_U8)),
                                        ctypes.byref(out)))
    return JoinRequest(bytes(out.join_eui), bytes(out.dev_eui), bytes(out.dev_nonce))


def encode_join_accept(accept: JoinAccept, nwk_key: bytes, dev_eui: bytes,
                       join_eui: bytes, dev_nonce: bytes) -> bytes:
    """Join-accept chiffré côté serveur : 17 octets, ou 33 avec CFList."""
    key = _bytes_arg("nwk_key", nwk_key, 16)
    deui = _bytes_arg("dev_eui", dev_eui, 8)
    jeui = _bytes_arg("join_eui", join_eui, 8)
    dn = _bytes_arg("dev_nonce", dev_nonce, 2)
    cap = 33
    out = (_U8 * cap)()
    written = ctypes.c_size_t(0)
    _check(LIB.lsim_encode_join_accept(
        ctypes.byref(accept._to_c()), ctypes.cast(key, ctypes.POINTER(_U8)),
        ctypes.cast(deui, ctypes.POINTER(_U8)), ctypes.cast(jeui, ctypes.POINTER(_U8)),
        ctypes.cast(dn, ctypes.POINTER(_U8)), out, cap, ctypes.byref(written)))
    return bytes(out[:written.value])


def encode_rejoin_join_accept(accept: JoinAccept, nwk_key: bytes, dev_eui: bytes,
                              join_eui: bytes, rejoin_type: int, rjcount: int) -> bytes:
    """Join-accept déclenché par une rejoin-request (1.1 §6.2.4.4) : 17 ou 33 octets.

    Chiffré avec JSEncKey, MIC JSIntKey, JoinReqType = rejoin_type, RJcount remplace DevNonce.
    """
    if rejoin_type not in (0, 1, 2):
        raise ValueError("rejoin_type doit valoir 0, 1 ou 2")
    if not 0 <= rjcount <= 0xFFFF:
        raise ValueError("rjcount doit tenir sur 16 bits")
    if not accept.dl_settings & 0x80:
        raise ValueError("OptNeg (bit 7 de dl_settings) requis pour un join-accept de rejoin")
    key = _bytes_arg("nwk_key", nwk_key, 16)
    deui = _bytes_arg("dev_eui", dev_eui, 8)
    jeui = _bytes_arg("join_eui", join_eui, 8)
    cap = 33
    out = (_U8 * cap)()
    written = ctypes.c_size_t(0)
    _check(LIB.lsim_encode_rejoin_join_accept(
        ctypes.byref(accept._to_c()), ctypes.cast(key, ctypes.POINTER(_U8)),
        ctypes.cast(deui, ctypes.POINTER(_U8)), ctypes.cast(jeui, ctypes.POINTER(_U8)),
        rejoin_type, rjcount, out, cap, ctypes.byref(written)))
    return bytes(out[:written.value])


def decode_rejoin_join_accept(wire: bytes, nwk_key: bytes, dev_eui: bytes, join_eui: bytes,
                              rejoin_type: int, rjcount: int) -> JoinAccept:
    """Ouvre un join-accept de rejoin côté device. MIC JSIntKey vérifié avant exposition."""
    if not isinstance(wire, (bytes, bytearray)) or len(wire) not in (17, 33):
        raise ValueError("join-accept de 17 ou 33 octets attendu")
    if rejoin_type not in (0, 1, 2):
        raise ValueError("rejoin_type doit valoir 0, 1 ou 2")
    key = _bytes_arg("nwk_key", nwk_key, 16)
    deui = _bytes_arg("dev_eui", dev_eui, 8)
    jeui = _bytes_arg("join_eui", join_eui, 8)
    src = (_U8 * len(wire)).from_buffer_copy(bytes(wire))
    out = _CJoinAccept()
    _check(LIB.lsim_decode_rejoin_join_accept(
        ctypes.cast(src, ctypes.POINTER(_U8)), len(wire),
        ctypes.cast(key, ctypes.POINTER(_U8)), ctypes.cast(deui, ctypes.POINTER(_U8)),
        ctypes.cast(jeui, ctypes.POINTER(_U8)), rejoin_type, rjcount, ctypes.byref(out)))
    return JoinAccept(
        join_nonce=bytes(out.join_nonce), net_id=bytes(out.net_id), dev_addr=out.dev_addr,
        dl_settings=out.dl_settings, rx_delay=out.rx_delay,
        cflist=bytes(out.cflist) if out.has_cflist else None)


def decode_join_accept(wire: bytes, nwk_key: bytes, dev_eui: bytes, join_eui: bytes,
                       dev_nonce: bytes) -> JoinAccept:
    """Ouvre un join-accept côté device. MIC vérifié avant exposition des champs."""
    if not isinstance(wire, (bytes, bytearray)) or len(wire) not in (17, 33):
        raise ValueError("join-accept de 17 ou 33 octets attendu")
    key = _bytes_arg("nwk_key", nwk_key, 16)
    deui = _bytes_arg("dev_eui", dev_eui, 8)
    jeui = _bytes_arg("join_eui", join_eui, 8)
    dn = _bytes_arg("dev_nonce", dev_nonce, 2)
    src = (_U8 * len(wire)).from_buffer_copy(bytes(wire))
    out = _CJoinAccept()
    _check(LIB.lsim_decode_join_accept(
        ctypes.cast(src, ctypes.POINTER(_U8)), len(wire),
        ctypes.cast(key, ctypes.POINTER(_U8)), ctypes.cast(deui, ctypes.POINTER(_U8)),
        ctypes.cast(jeui, ctypes.POINTER(_U8)), ctypes.cast(dn, ctypes.POINTER(_U8)),
        ctypes.byref(out)))
    return JoinAccept(
        join_nonce=bytes(out.join_nonce),
        net_id=bytes(out.net_id),
        dev_addr=out.dev_addr,
        dl_settings=out.dl_settings,
        rx_delay=out.rx_delay,
        cflist=bytes(out.cflist) if out.has_cflist else None,
    )
