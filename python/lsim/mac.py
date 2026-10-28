"""Commandes MAC LoRaWAN 1.1, codées et décodées par le cœur natif.

Chaque commande est une dataclass immuable. Les bornes de champ sont vérifiées ici,
avant l'appel natif, car `ctypes` tronquerait silencieusement une valeur hors domaine.
Le sens (uplink ou downlink) est explicite à chaque décodage : le CID 0x02 désigne
LinkCheckReq en uplink et LinkCheckAns en downlink.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
from typing import Union

from lsim._native import LIB, _CMacCommand, _U8P
from lsim.lora import StatusError

MAX_COMMAND_BYTES = 6
MAX_FOPTS = 15

UPLINK = 0
DOWNLINK = 1

_KIND_LINK_CHECK_REQ = 1
_KIND_LINK_CHECK_ANS = 2
_KIND_LINK_ADR_REQ = 3
_KIND_LINK_ADR_ANS = 4
_KIND_DUTY_CYCLE_REQ = 5
_KIND_DUTY_CYCLE_ANS = 6
_KIND_DEV_STATUS_REQ = 7
_KIND_DEV_STATUS_ANS = 8
_KIND_REKEY_IND = 9
_KIND_REKEY_CONF = 10


def _uint(name: str, value: int, bits: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < (1 << bits):
        raise ValueError(f"{name} doit être un entier sur {bits} bits")
    return value


@dataclass(frozen=True)
class LinkCheckReq:
    """Uplink, sans charge utile."""


@dataclass(frozen=True)
class LinkCheckAns:
    """Downlink : marge en dB (0..254) et nombre de passerelles ayant reçu la requête."""

    margin: int
    gw_cnt: int

    def __post_init__(self) -> None:
        if isinstance(self.margin, bool) or not isinstance(self.margin, int) or not 0 <= self.margin <= 254:
            raise ValueError("margin doit être compris entre 0 et 254 (255 réservé)")
        _uint("gw_cnt", self.gw_cnt, 8)


@dataclass(frozen=True)
class LinkAdrReq:
    """Downlink : changement de débit, de puissance et de canaux.

    tx_power 15 et data_rate 15 signifient « ignorer le champ ».
    nb_trans 0 signifie « garder la valeur actuelle ».
    """

    data_rate: int
    tx_power: int
    ch_mask: int
    ch_mask_cntl: int = 0
    nb_trans: int = 1

    def __post_init__(self) -> None:
        _uint("data_rate", self.data_rate, 4)
        _uint("tx_power", self.tx_power, 4)
        _uint("ch_mask", self.ch_mask, 16)
        if _uint("ch_mask_cntl", self.ch_mask_cntl, 3) > 7:
            raise ValueError("ch_mask_cntl doit être compris entre 0 et 7")
        _uint("nb_trans", self.nb_trans, 4)


@dataclass(frozen=True)
class LinkAdrAns:
    """Uplink : acquittement des trois champs de LinkADRReq."""

    channel_mask_ack: bool = False
    data_rate_ack: bool = False
    power_ack: bool = False


@dataclass(frozen=True)
class DutyCycleReq:
    """Downlink : duty cycle agrégé 1 / 2**max_dcycle (0 = pas de limite)."""

    max_dcycle: int

    def __post_init__(self) -> None:
        _uint("max_dcycle", self.max_dcycle, 4)


@dataclass(frozen=True)
class DutyCycleAns:
    """Uplink, sans charge utile."""


@dataclass(frozen=True)
class DevStatusReq:
    """Downlink, sans charge utile."""


@dataclass(frozen=True)
class DevStatusAns:
    """Uplink : batterie (0 = externe, 255 = non mesurée) et marge de -32 à 31 dB."""

    battery: int
    margin: int

    def __post_init__(self) -> None:
        _uint("battery", self.battery, 8)
        if isinstance(self.margin, bool) or not isinstance(self.margin, int) or not -32 <= self.margin <= 31:
            raise ValueError("margin doit être compris entre -32 et 31")


@dataclass(frozen=True)
class RekeyInd:
    """Uplink : version LoRaWAN de l'appareil (seule la valeur 1 = 1.1 est acceptée)."""

    minor: int = 1

    def __post_init__(self) -> None:
        if self.minor != 1:
            raise ValueError("minor doit valoir 1 (LoRaWAN 1.1)")


@dataclass(frozen=True)
class RekeyConf:
    """Downlink : version LoRaWAN du serveur (seule la valeur 1 est acceptée)."""

    minor: int = 1

    def __post_init__(self) -> None:
        if self.minor != 1:
            raise ValueError("minor doit valoir 1 (LoRaWAN 1.1)")


MacCommand = Union[
    LinkCheckReq, LinkCheckAns, LinkAdrReq, LinkAdrAns, DutyCycleReq, DutyCycleAns,
    DevStatusReq, DevStatusAns, RekeyInd, RekeyConf,
]


def _to_c(cmd: MacCommand) -> _CMacCommand:
    c = _CMacCommand()
    if isinstance(cmd, LinkCheckReq):
        c.kind = _KIND_LINK_CHECK_REQ
    elif isinstance(cmd, LinkCheckAns):
        c.kind = _KIND_LINK_CHECK_ANS
        c.margin, c.gw_cnt = cmd.margin, cmd.gw_cnt
    elif isinstance(cmd, LinkAdrReq):
        c.kind = _KIND_LINK_ADR_REQ
        c.data_rate, c.tx_power = cmd.data_rate, cmd.tx_power
        c.ch_mask, c.ch_mask_cntl, c.nb_trans = cmd.ch_mask, cmd.ch_mask_cntl, cmd.nb_trans
    elif isinstance(cmd, LinkAdrAns):
        c.kind = _KIND_LINK_ADR_ANS
        c.ack_channel_mask = int(cmd.channel_mask_ack)
        c.ack_data_rate = int(cmd.data_rate_ack)
        c.ack_power = int(cmd.power_ack)
    elif isinstance(cmd, DutyCycleReq):
        c.kind = _KIND_DUTY_CYCLE_REQ
        c.max_dcycle = cmd.max_dcycle
    elif isinstance(cmd, DutyCycleAns):
        c.kind = _KIND_DUTY_CYCLE_ANS
    elif isinstance(cmd, DevStatusReq):
        c.kind = _KIND_DEV_STATUS_REQ
    elif isinstance(cmd, DevStatusAns):
        c.kind = _KIND_DEV_STATUS_ANS
        c.battery, c.dev_margin = cmd.battery, cmd.margin
    elif isinstance(cmd, RekeyInd):
        c.kind = _KIND_REKEY_IND
        c.lorawan_minor = cmd.minor
    elif isinstance(cmd, RekeyConf):
        c.kind = _KIND_REKEY_CONF
        c.lorawan_minor = cmd.minor
    else:
        raise TypeError("commande MAC inconnue")
    return c


def _from_c(c: _CMacCommand) -> MacCommand:
    k = c.kind
    if k == _KIND_LINK_CHECK_REQ:
        return LinkCheckReq()
    if k == _KIND_LINK_CHECK_ANS:
        return LinkCheckAns(c.margin, c.gw_cnt)
    if k == _KIND_LINK_ADR_REQ:
        return LinkAdrReq(c.data_rate, c.tx_power, c.ch_mask, c.ch_mask_cntl, c.nb_trans)
    if k == _KIND_LINK_ADR_ANS:
        return LinkAdrAns(bool(c.ack_channel_mask), bool(c.ack_data_rate), bool(c.ack_power))
    if k == _KIND_DUTY_CYCLE_REQ:
        return DutyCycleReq(c.max_dcycle)
    if k == _KIND_DUTY_CYCLE_ANS:
        return DutyCycleAns()
    if k == _KIND_DEV_STATUS_REQ:
        return DevStatusReq()
    if k == _KIND_DEV_STATUS_ANS:
        return DevStatusAns(c.battery, c.dev_margin)
    if k == _KIND_REKEY_IND:
        return RekeyInd(c.lorawan_minor)
    if k == _KIND_REKEY_CONF:
        return RekeyConf(c.lorawan_minor)
    raise StatusError(900)  # type inconnu renvoyé par le cœur : erreur interne


def _check(status: int) -> None:
    if status != 0:
        raise StatusError(status)


def encode(cmd: MacCommand) -> bytes:
    """CID et charge utile d'une commande (1 à 6 octets)."""
    c = _to_c(cmd)
    out = (ctypes.c_uint8 * MAX_COMMAND_BYTES)()
    n = ctypes.c_size_t(0)
    _check(LIB.lsim_mac_encode(ctypes.byref(c), out, ctypes.byref(n)))
    return bytes(out[: n.value])


def decode_one(data: bytes, downlink: bool) -> tuple[MacCommand, int]:
    """Décode la première commande de `data` ; renvoie (commande, octets consommés)."""
    if not isinstance(data, (bytes, bytearray)) or len(data) == 0:
        raise ValueError("data doit être une séquence d'au moins un octet")
    buf = (ctypes.c_uint8 * len(data)).from_buffer_copy(bytes(data))
    out = _CMacCommand()
    used = ctypes.c_size_t(0)
    _check(LIB.lsim_mac_decode(
        ctypes.cast(buf, _U8P), len(data), DOWNLINK if downlink else UPLINK,
        ctypes.byref(out), ctypes.byref(used)))
    return _from_c(out), used.value


def decode_all(data: bytes, downlink: bool) -> list[MacCommand]:
    """Décode un flux de commandes concaténées (champ FOpts ou charge utile MAC)."""
    cmds: list[MacCommand] = []
    rest = bytes(data)
    while rest:
        cmd, used = decode_one(rest, downlink)
        cmds.append(cmd)
        rest = rest[used:]
    return cmds


def append_fopts(fopts: bytes, cmd: MacCommand) -> bytes:
    """Ajoute une commande au champ FOpts (15 octets au plus) ; lève StatusError si plein."""
    if not isinstance(fopts, (bytes, bytearray)) or len(fopts) > MAX_FOPTS:
        raise ValueError("fopts doit être de type bytes, 15 octets au plus")
    encoded = encode(cmd)
    buf = (ctypes.c_uint8 * MAX_FOPTS)()
    for i, b in enumerate(fopts):
        buf[i] = b
    length = ctypes.c_uint8(len(fopts))
    cmd_buf = (ctypes.c_uint8 * len(encoded)).from_buffer_copy(encoded)
    _check(LIB.lsim_mac_append_fopts(
        buf, ctypes.byref(length), ctypes.cast(cmd_buf, _U8P), len(encoded)))
    return bytes(buf[: length.value])
