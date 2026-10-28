"""Moteur de classe B LoRaWAN 1.1 (beacon, ping slots) : binding de l'API C.

Le dispositif est un objet immuable : chaque beacon renvoie un nouvel objet. Aucun calcul
de timing n'est fait en Python ; voir core/include/lsim/class_b.hpp pour les règles.
Temps en nanosecondes entières sur l'horloge locale du dispositif.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
from enum import IntEnum

from lsim._native import LIB, _CClassBDevice, _CClassBPingSlot, _U8P
from lsim.lora import StatusError

BEACON_PERIOD_NS = 128_000_000_000
BEACON_RESERVED_NS = 2_120_000_000
SLOT_NS = 30_000_000
SLOTS_PER_WINDOW = 4096
MAX_PERIODICITY = 7


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


@dataclass(frozen=True)
class ClassBDevice:
    dev_addr: int
    periodicity: int = 0
    synchronized: bool = False
    last_beacon_rx_ns: int = 0
    last_beacon_time_s: int = 0

    def __post_init__(self) -> None:
        if isinstance(self.dev_addr, bool) or not 0 <= self.dev_addr < 2**32:
            raise ValueError("dev_addr doit être un entier sur 32 bits")
        if isinstance(self.periodicity, bool) or not 0 <= self.periodicity <= MAX_PERIODICITY:
            raise ValueError(f"periodicity doit être comprise entre 0 et {MAX_PERIODICITY}")

    def _native(self) -> _CClassBDevice:
        c = _CClassBDevice()
        c.synchronized = 1 if self.synchronized else 0
        c.last_beacon_rx_ns = self.last_beacon_rx_ns
        c.last_beacon_time_s = self.last_beacon_time_s
        c.dev_addr = self.dev_addr
        c.periodicity = self.periodicity
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
