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
_KIND_RX_PARAM_SETUP_REQ = 11
_KIND_RX_PARAM_SETUP_ANS = 12
_KIND_NEW_CHANNEL_REQ = 13
_KIND_NEW_CHANNEL_ANS = 14
_KIND_RX_TIMING_SETUP_REQ = 15
_KIND_RX_TIMING_SETUP_ANS = 16
_KIND_DEVICE_TIME_REQ = 17
_KIND_DEVICE_TIME_ANS = 18
_KIND_FORCE_REJOIN_REQ = 19
_KIND_REJOIN_PARAM_SETUP_REQ = 20
_KIND_REJOIN_PARAM_SETUP_ANS = 21
_KIND_DL_CHANNEL_REQ = 22
_KIND_DL_CHANNEL_ANS = 23
_KIND_ADR_PARAM_SETUP_REQ = 24
_KIND_ADR_PARAM_SETUP_ANS = 25

MAX_FREQ_100HZ = 0xFFFFFF


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


def _check_freq(name: str, freq_100hz: int) -> None:
    """Fréquence en pas de 100 Hz : 0 (canal désactivé) ou >= 100 MHz (1 000 000)."""
    _uint(name, freq_100hz, 24)
    if freq_100hz not in (0,) and freq_100hz < 1_000_000:
        raise ValueError(f"{name} : fréquence inférieure à 100 MHz réservée")


@dataclass(frozen=True)
class RxParamSetupReq:
    """Downlink : RX2 (débit et fréquence) et offset RX1.

    freq_100hz : fréquence en pas de 100 Hz (869 525 000 Hz = 8 695 250).
    """

    rx2_data_rate: int
    rx1_dr_offset: int
    freq_100hz: int

    def __post_init__(self) -> None:
        _uint("rx2_data_rate", self.rx2_data_rate, 4)
        if _uint("rx1_dr_offset", self.rx1_dr_offset, 3) > 7:
            raise ValueError("rx1_dr_offset doit être compris entre 0 et 7")
        _check_freq("freq_100hz", self.freq_100hz)


@dataclass(frozen=True)
class RxParamSetupAns:
    """Uplink : acquittement des trois champs de RXParamSetupReq."""

    channel_ack: bool = False
    rx2_data_rate_ack: bool = False
    rx1_dr_offset_ack: bool = False


@dataclass(frozen=True)
class NewChannelReq:
    """Downlink : création ou modification d'un canal (hors plan fixe uniquement)."""

    ch_index: int
    freq_100hz: int
    min_dr: int
    max_dr: int

    def __post_init__(self) -> None:
        if _uint("ch_index", self.ch_index, 4) > 15:
            raise ValueError("ch_index doit être compris entre 0 et 15")
        _check_freq("freq_100hz", self.freq_100hz)
        _uint("min_dr", self.min_dr, 4)
        _uint("max_dr", self.max_dr, 4)


@dataclass(frozen=True)
class NewChannelAns:
    """Uplink : acquittement de la plage de débits et de la fréquence."""

    dr_range_ack: bool = False
    channel_freq_ack: bool = False


@dataclass(frozen=True)
class RxTimingSetupReq:
    """Downlink : délai entre la fin de l'uplink et RX1, en secondes (0 et 1 valent 1 s)."""

    delay: int

    def __post_init__(self) -> None:
        if _uint("delay", self.delay, 4) > 15:
            raise ValueError("delay doit être compris entre 0 et 15")


@dataclass(frozen=True)
class RxTimingSetupAns:
    """Uplink, sans charge utile."""


@dataclass(frozen=True)
class DeviceTimeReq:
    """Uplink, sans charge utile : demande de l'heure réseau."""


@dataclass(frozen=True)
class DeviceTimeAns:
    """Downlink : secondes depuis l'époque GPS (32 bits) et fraction en 1/256 s."""

    seconds: int
    fraction: int

    def __post_init__(self) -> None:
        _uint("seconds", self.seconds, 32)
        _uint("fraction", self.fraction, 8)


@dataclass(frozen=True)
class ForceRejoinReq:
    """Downlink, sans réponse : demande de rejoin immédiat (type 0 ou 2)."""

    period: int
    max_retries: int
    rejoin_type: int
    dr: int

    def __post_init__(self) -> None:
        if _uint("period", self.period, 3) > 7:
            raise ValueError("period doit être compris entre 0 et 7")
        if _uint("max_retries", self.max_retries, 3) > 7:
            raise ValueError("max_retries doit être compris entre 0 et 7")
        if _uint("rejoin_type", self.rejoin_type, 3) > 2:
            raise ValueError("rejoin_type doit valoir 0, 1 ou 2 (3 à 7 sont RFU)")
        _uint("dr", self.dr, 4)


@dataclass(frozen=True)
class AdrParamSetupReq:
    """Downlink : ADR_ACK_LIMIT = 2**limit_exp et ADR_ACK_DELAY = 2**delay_exp (0..15 chacun)."""

    limit_exp: int
    delay_exp: int

    def __post_init__(self) -> None:
        _uint("limit_exp", self.limit_exp, 4)
        _uint("delay_exp", self.delay_exp, 4)


@dataclass(frozen=True)
class AdrParamSetupAns:
    """Uplink, sans charge utile."""


@dataclass(frozen=True)
class RejoinParamSetupReq:
    """Downlink : rejoin type 0 au plus tous les 2**C+4 uplinks et 2**T+10 s (C = max_count_n, T = max_time_n)."""

    max_time_n: int
    max_count_n: int

    def __post_init__(self) -> None:
        _uint("max_time_n", self.max_time_n, 4)
        _uint("max_count_n", self.max_count_n, 4)


@dataclass(frozen=True)
class RejoinParamSetupAns:
    """Uplink : time_ok est vrai si la limitation temporelle est acceptée."""

    time_ok: bool = False


@dataclass(frozen=True)
class DlChannelReq:
    """Downlink : fréquence RX1 du canal ch_index, en pas de 100 Hz (>= 100 MHz)."""

    ch_index: int
    freq_100hz: int

    def __post_init__(self) -> None:
        if _uint("ch_index", self.ch_index, 4) > 15:
            raise ValueError("ch_index doit être compris entre 0 et 15")
        _uint("freq_100hz", self.freq_100hz, 24)
        if self.freq_100hz < 1_000_000:
            raise ValueError("freq_100hz : fréquence inférieure à 100 MHz réservée")


@dataclass(frozen=True)
class DlChannelAns:
    """Uplink : channel_freq_ok et uplink_freq_exists (bits 0 et 1)."""

    channel_freq_ok: bool = False
    uplink_freq_exists: bool = False


MacCommand = Union[
    LinkCheckReq, LinkCheckAns, LinkAdrReq, LinkAdrAns, DutyCycleReq, DutyCycleAns,
    DevStatusReq, DevStatusAns, RekeyInd, RekeyConf,
    RxParamSetupReq, RxParamSetupAns, NewChannelReq, NewChannelAns,
    RxTimingSetupReq, RxTimingSetupAns, DeviceTimeReq, DeviceTimeAns, ForceRejoinReq,
    RejoinParamSetupReq, RejoinParamSetupAns, DlChannelReq, DlChannelAns,
    AdrParamSetupReq, AdrParamSetupAns,
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
    elif isinstance(cmd, RxParamSetupReq):
        c.kind = _KIND_RX_PARAM_SETUP_REQ
        c.rx2_data_rate, c.rx1_dr_offset, c.freq_100hz = cmd.rx2_data_rate, cmd.rx1_dr_offset, cmd.freq_100hz
    elif isinstance(cmd, RxParamSetupAns):
        c.kind = _KIND_RX_PARAM_SETUP_ANS
        c.ack_rx_channel = int(cmd.channel_ack)
        c.ack_rx2_data_rate = int(cmd.rx2_data_rate_ack)
        c.ack_rx1_dr_offset = int(cmd.rx1_dr_offset_ack)
    elif isinstance(cmd, NewChannelReq):
        c.kind = _KIND_NEW_CHANNEL_REQ
        c.ch_index, c.freq_100hz = cmd.ch_index, cmd.freq_100hz
        c.min_dr, c.max_dr = cmd.min_dr, cmd.max_dr
    elif isinstance(cmd, NewChannelAns):
        c.kind = _KIND_NEW_CHANNEL_ANS
        c.ack_dr_range = int(cmd.dr_range_ack)
        c.ack_channel_freq = int(cmd.channel_freq_ack)
    elif isinstance(cmd, RxTimingSetupReq):
        c.kind = _KIND_RX_TIMING_SETUP_REQ
        c.rx_delay = cmd.delay
    elif isinstance(cmd, RxTimingSetupAns):
        c.kind = _KIND_RX_TIMING_SETUP_ANS
    elif isinstance(cmd, DeviceTimeReq):
        c.kind = _KIND_DEVICE_TIME_REQ
    elif isinstance(cmd, DeviceTimeAns):
        c.kind = _KIND_DEVICE_TIME_ANS
        c.device_time_s, c.device_time_frac = cmd.seconds, cmd.fraction
    elif isinstance(cmd, ForceRejoinReq):
        c.kind = _KIND_FORCE_REJOIN_REQ
        c.rejoin_period, c.rejoin_max_retries = cmd.period, cmd.max_retries
        c.rejoin_type, c.data_rate = cmd.rejoin_type, cmd.dr
    elif isinstance(cmd, RejoinParamSetupReq):
        c.kind = _KIND_REJOIN_PARAM_SETUP_REQ
        c.max_time_n, c.max_count_n = cmd.max_time_n, cmd.max_count_n
    elif isinstance(cmd, RejoinParamSetupAns):
        c.kind = _KIND_REJOIN_PARAM_SETUP_ANS
        c.ack_time_ok = int(cmd.time_ok)
    elif isinstance(cmd, AdrParamSetupReq):
        c.kind = _KIND_ADR_PARAM_SETUP_REQ
        c.adr_limit_exp, c.adr_delay_exp = cmd.limit_exp, cmd.delay_exp
    elif isinstance(cmd, AdrParamSetupAns):
        c.kind = _KIND_ADR_PARAM_SETUP_ANS
    elif isinstance(cmd, DlChannelReq):
        c.kind = _KIND_DL_CHANNEL_REQ
        c.ch_index, c.freq_100hz = cmd.ch_index, cmd.freq_100hz
    elif isinstance(cmd, DlChannelAns):
        c.kind = _KIND_DL_CHANNEL_ANS
        c.ack_channel_freq = int(cmd.channel_freq_ok)
        c.ack_uplink_freq_exists = int(cmd.uplink_freq_exists)
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
    if k == _KIND_RX_PARAM_SETUP_REQ:
        return RxParamSetupReq(c.rx2_data_rate, c.rx1_dr_offset, c.freq_100hz)
    if k == _KIND_RX_PARAM_SETUP_ANS:
        return RxParamSetupAns(bool(c.ack_rx_channel), bool(c.ack_rx2_data_rate), bool(c.ack_rx1_dr_offset))
    if k == _KIND_NEW_CHANNEL_REQ:
        return NewChannelReq(c.ch_index, c.freq_100hz, c.min_dr, c.max_dr)
    if k == _KIND_NEW_CHANNEL_ANS:
        return NewChannelAns(bool(c.ack_dr_range), bool(c.ack_channel_freq))
    if k == _KIND_RX_TIMING_SETUP_REQ:
        return RxTimingSetupReq(c.rx_delay)
    if k == _KIND_RX_TIMING_SETUP_ANS:
        return RxTimingSetupAns()
    if k == _KIND_DEVICE_TIME_REQ:
        return DeviceTimeReq()
    if k == _KIND_DEVICE_TIME_ANS:
        return DeviceTimeAns(c.device_time_s, c.device_time_frac)
    if k == _KIND_FORCE_REJOIN_REQ:
        return ForceRejoinReq(c.rejoin_period, c.rejoin_max_retries, c.rejoin_type, c.data_rate)
    if k == _KIND_REJOIN_PARAM_SETUP_REQ:
        return RejoinParamSetupReq(c.max_time_n, c.max_count_n)
    if k == _KIND_REJOIN_PARAM_SETUP_ANS:
        return RejoinParamSetupAns(bool(c.ack_time_ok))
    if k == _KIND_ADR_PARAM_SETUP_REQ:
        return AdrParamSetupReq(c.adr_limit_exp, c.adr_delay_exp)
    if k == _KIND_ADR_PARAM_SETUP_ANS:
        return AdrParamSetupAns()
    if k == _KIND_DL_CHANNEL_REQ:
        return DlChannelReq(c.ch_index, c.freq_100hz)
    if k == _KIND_DL_CHANNEL_ANS:
        return DlChannelAns(bool(c.ack_channel_freq), bool(c.ack_uplink_freq_exists))
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
