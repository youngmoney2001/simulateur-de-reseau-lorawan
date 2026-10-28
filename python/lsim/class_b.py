"""Moteur de classe B LoRaWAN 1.1 (beacon, ping slots) : binding de l'API C.

Le dispositif est un objet immuable : chaque beacon renvoie un nouvel objet. Aucun calcul
de timing n'est fait en Python ; voir core/include/lsim/class_b.hpp pour les règles.
Temps en nanosecondes entières sur l'horloge locale du dispositif.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
from enum import IntEnum

from lsim._native import (
    LIB,
    _CClassBDevice,
    _CClassBGatewayInfo,
    _CClassBPingSlot,
    _U8P,
)
from lsim.lora import StatusError

BEACON_PERIOD_NS = 128_000_000_000
BEACON_RESERVED_NS = 2_120_000_000
SLOT_NS = 30_000_000
SLOTS_PER_WINDOW = 4096
MAX_PERIODICITY = 7
MAX_DRIFT_PPM = 1000


class BeaconState(IntEnum):
    NOT_SYNCHRONIZED = 0
    SYNCHRONIZED = 1  # beacon reçu depuis moins de 128 s
    BEACON_LESS = 2   # 128 s à 2 h sans beacon : fonctionnement sans balise
    LOST = 3          # 2 h ou plus : quitter la classe B


@dataclass(frozen=True)
class PingSlot:
    start_ns: int
    slot_index: int
    beacon_time_s: int
    beacon_period_start_ns: int
    # Élargissement de la fenêtre de chaque côté (dérive × temps depuis le beacon).
    window_half_ns: int


@dataclass(frozen=True)
class GatewayInfo:
    """GwSpecific décodé. Coordonnées présentes seulement si info_desc vaut 0, 1 ou 2."""

    info_desc: int
    has_coordinates: bool
    latitude_deg: float
    longitude_deg: float


@dataclass(frozen=True)
class ClassBDevice:
    dev_addr: int
    periodicity: int = 0
    synchronized: bool = False
    last_beacon_rx_ns: int = 0
    last_beacon_time_s: int = 0
    clock_drift_ppm: int = 0

    def __post_init__(self) -> None:
        if isinstance(self.dev_addr, bool) or not 0 <= self.dev_addr < 2**32:
            raise ValueError("dev_addr doit être un entier sur 32 bits")
        if isinstance(self.periodicity, bool) or not 0 <= self.periodicity <= MAX_PERIODICITY:
            raise ValueError(f"periodicity doit être comprise entre 0 et {MAX_PERIODICITY}")
        if isinstance(self.clock_drift_ppm, bool) or not 0 <= self.clock_drift_ppm <= MAX_DRIFT_PPM:
            raise ValueError(f"clock_drift_ppm doit être compris entre 0 et {MAX_DRIFT_PPM}")

    def _native(self) -> _CClassBDevice:
        c = _CClassBDevice()
        c.synchronized = 1 if self.synchronized else 0
        c.last_beacon_rx_ns = self.last_beacon_rx_ns
        c.last_beacon_time_s = self.last_beacon_time_s
        c.dev_addr = self.dev_addr
        c.periodicity = self.periodicity
        c.clock_drift_ppm = self.clock_drift_ppm
        return c

    def on_beacon(self, rx_ns: int, beacon_time_s: int) -> "ClassBDevice":
        """Beacon reçu à `rx_ns` (horloge locale) : renvoie le dispositif resynchronisé."""
        if isinstance(rx_ns, bool) or not 0 <= rx_ns < 2**64:
            raise ValueError("rx_ns doit être un entier non négatif sur 64 bits")
        if not 0 <= beacon_time_s < 2**32:
            raise ValueError("beacon_time_s doit être un entier sur 32 bits")
        c = self._native()
        status = LIB.lsim_classb_on_beacon(ctypes.byref(c), rx_ns, beacon_time_s)
        if status != 0:
            raise StatusError(status)
        return ClassBDevice(
            dev_addr=self.dev_addr,
            periodicity=self.periodicity,
            synchronized=bool(c.synchronized),
            last_beacon_rx_ns=int(c.last_beacon_rx_ns),
            last_beacon_time_s=int(c.last_beacon_time_s),
            clock_drift_ppm=self.clock_drift_ppm,
        )

    def beacon_state(self, now_ns: int) -> BeaconState:
        c = self._native()
        out = ctypes.c_uint8(0)
        status = LIB.lsim_classb_beacon_state(ctypes.byref(c), now_ns, ctypes.byref(out))
        if status != 0:
            raise StatusError(status)
        return BeaconState(out.value)

    def next_ping_slot(self, now_ns: int) -> PingSlot:
        """Prochain ping slot débutant à `now_ns` ou après. Lève StatusError si indisponible."""
        c = self._native()
        out = _CClassBPingSlot()
        status = LIB.lsim_classb_next_ping_slot(ctypes.byref(c), now_ns, ctypes.byref(out))
        if status != 0:
            raise StatusError(status)
        return PingSlot(
            start_ns=int(out.start_ns),
            slot_index=int(out.slot_index),
            beacon_time_s=int(out.beacon_time_s),
            beacon_period_start_ns=int(out.beacon_period_start_ns),
            window_half_ns=int(out.window_half_ns),
        )


def decode_beacon(frame: bytes, *, rfu_len: int = 2) -> int:
    """Décode la partie commune d'un beacon (EU868 : rfu_len=2, US915 : rfu_len=3).

    Renvoie BeaconCommon.Time (secondes GPS modulo 2^32). Lève StatusError si le CRC-16 est faux.
    """
    if not isinstance(frame, (bytes, bytearray)):
        raise ValueError("frame doit être une séquence d'octets")
    if rfu_len not in (2, 3):
        raise ValueError("rfu_len doit valoir 2 ou 3")
    buf = (ctypes.c_uint8 * len(frame)).from_buffer_copy(bytes(frame))
    out = ctypes.c_uint32(0)
    status = LIB.lsim_classb_decode_beacon(buf, len(frame), rfu_len, ctypes.byref(out))
    if status != 0:
        raise StatusError(status)
    return int(out.value)


def decode_beacon_full(frame: bytes, *, rfu_len: int = 2, gw_rfu_len: int = 0) -> tuple[int, GatewayInfo | None]:
    """Décode un beacon complet : renvoie (BeaconCommon.Time, GatewayInfo ou None).

    EU868 : rfu_len=2, gw_rfu_len=0 ; US915 : rfu_len=3, gw_rfu_len=1. Une trame sans
    GwSpecific renvoie None. Lève StatusError si un CRC-16 est faux.
    """
    if not isinstance(frame, (bytes, bytearray)):
        raise ValueError("frame doit être une séquence d'octets")
    if rfu_len not in (2, 3) or gw_rfu_len not in (0, 1):
        raise ValueError("rfu_len doit valoir 2 ou 3, gw_rfu_len 0 ou 1")
    buf = (ctypes.c_uint8 * len(frame)).from_buffer_copy(bytes(frame))
    out = _CClassBGatewayInfo()
    status = LIB.lsim_classb_decode_beacon_full(buf, len(frame), rfu_len, gw_rfu_len, ctypes.byref(out))
    if status != 0:
        raise StatusError(status)
    gw = None
    if out.present:
        gw = GatewayInfo(
            info_desc=int(out.info_desc),
            has_coordinates=bool(out.has_coordinates),
            latitude_deg=float(out.latitude_deg),
            longitude_deg=float(out.longitude_deg),
        )
    return int(out.time_s), gw


def us902_channel(beacon_time_s: int) -> tuple[int, int]:
    """US902-928 : (indice 0..7, fréquence en Hz) du beacon et du ping slot de la période.

    Formule : floor(beacon_time / 128) mod 8 (RP002-1.0.2 : définitions de beacon_time, de
    beacon_period = 128 s et de floor ; table des canaux 0 à 6 ; ping slot « follows beacon
    channel »). L'équation seule n'apparaît pas dans l'extrait lu (voir docs/ROADMAP.md).
    """
    if not 0 <= beacon_time_s < 2**32:
        raise ValueError("beacon_time_s doit être un entier sur 32 bits")
    idx = ctypes.c_uint8(0)
    freq = ctypes.c_uint32(0)
    status = LIB.lsim_classb_us902_channel(beacon_time_s, ctypes.byref(idx), ctypes.byref(freq))
    if status != 0:
        raise StatusError(status)
    return int(idx.value), int(freq.value)


def ping_offset(beacon_time_s: int, dev_addr: int, periodicity: int) -> int:
    """pingOffset de la période (AES-128 zéro-clé, voir class_b.hpp)."""
    if not 0 <= beacon_time_s < 2**32 or not 0 <= dev_addr < 2**32:
        raise ValueError("beacon_time_s et dev_addr doivent être des entiers sur 32 bits")
    if isinstance(periodicity, bool) or not 0 <= periodicity <= MAX_PERIODICITY:
        raise ValueError(f"periodicity doit être comprise entre 0 et {MAX_PERIODICITY}")
    out = ctypes.c_uint32(0)
    status = LIB.lsim_classb_ping_offset(beacon_time_s, dev_addr, periodicity, ctypes.byref(out))
    if status != 0:
        raise StatusError(status)
    return int(out.value)
