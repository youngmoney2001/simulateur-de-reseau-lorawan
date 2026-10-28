"""Moteur de session dispositif OTAA LoRaWAN 1.1 (cœur natif, désigné par un handle).

Les clés de session sont passées au cœur à l'activation et ne sont jamais renvoyées
par ce module. Cycle d'un uplink : `begin_uplink` -> `receive_downlink` (0 ou 1 fois)
-> `end_uplink`. Voir core/include/lsim/session.hpp pour les règles.
"""

from __future__ import annotations

import ctypes
import threading
from dataclasses import dataclass, field
from enum import IntEnum

from lsim._native import LIB, _CSessionInfo, _CSessionKeys, _CSessionUplinkEnd, _CSessionUplinkPlan
from lsim.lora import StatusError

MAX_EXPONENT = 15
_STATUS_UNKNOWN_HANDLE = 786  # 780 + 6


class SessionState(IntEnum):
    NO_SESSION = 0
    ACTIVE = 1
    NEEDS_JOIN = 2


@dataclass(frozen=True)
class SessionKeys:
    """Clés LoRaWAN 1.1 de session (16 octets chacune). Jamais affichées dans repr()."""

    f_nwk_s_int_key: bytes = field(repr=False)
    s_nwk_s_int_key: bytes = field(repr=False)
    nwk_s_enc_key: bytes = field(repr=False)
    app_s_key: bytes = field(repr=False)

    def __post_init__(self) -> None:
        for name in ("f_nwk_s_int_key", "s_nwk_s_int_key", "nwk_s_enc_key", "app_s_key"):
            value = getattr(self, name)
            if not isinstance(value, (bytes, bytearray)) or len(value) != 16:
                raise ValueError(f"{name} doit être une séquence de 16 octets")


@dataclass(frozen=True)
class UplinkPlan:
    fcnt32: int
    rekey_ind: bool
    ack_req: bool
    default_channels_reenabled: bool


@dataclass(frozen=True)
class SessionSnapshot:
    state: SessionState
    dev_addr: int
    fcnt_up: int
    nf_cnt_dwn: int
    af_cnt_dwn: int
    dr: int
    tx_power_index: int
    ack_cnt: int
    cycle_open: bool


def _check(status: int) -> None:
    if status != 0:
        raise StatusError(status)


def _check_exponent(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MAX_EXPONENT:
        raise ValueError(f"{name} doit être un entier entre 0 et {MAX_EXPONENT}")


class DeviceSession:
    """Session d'un dispositif. À fermer avec `close()` ou `with`."""

    def __init__(self) -> None:
        handle = ctypes.c_uint64(0)
        _check(LIB.lsim_session_create(ctypes.byref(handle)))
        self._handle = handle.value
        self._lock = threading.Lock()

    def __enter__(self) -> "DeviceSession":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        if self._handle:
            LIB.lsim_session_destroy(self._handle)
            self._handle = 0

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:  # pragma: no cover - interpréteur en cours d'arrêt
            pass

    def _require_open(self) -> int:
        if not self._handle:
            raise StatusError(_STATUS_UNKNOWN_HANDLE)
        return self._handle

    def join_accepted(self, keys: SessionKeys, *, dev_addr: int, dr: int, min_dr: int,
                      tx_power_index: int, default_tx_power_index: int) -> None:
        """Join-accept traité : compteurs à zéro, rekey en attente, ADR_ACK réinitialisé."""
        if not isinstance(dev_addr, int) or isinstance(dev_addr, bool) or not 0 <= dev_addr < 2**32:
            raise ValueError("dev_addr doit être un entier sur 32 bits")
        for name, value in (("dr", dr), ("min_dr", min_dr), ("tx_power_index", tx_power_index),
                            ("default_tx_power_index", default_tx_power_index)):
            _check_exponent(name, value)
        c = _CSessionKeys()
        c.f_nwk_s_int_key[:] = list(keys.f_nwk_s_int_key)
        c.s_nwk_s_int_key[:] = list(keys.s_nwk_s_int_key)
        c.nwk_s_enc_key[:] = list(keys.nwk_s_enc_key)
        c.app_s_key[:] = list(keys.app_s_key)
        with self._lock:
            handle = self._require_open()
            _check(LIB.lsim_session_join_accepted(
                handle, ctypes.byref(c), dev_addr, dr, min_dr, tx_power_index,
                default_tx_power_index))

    def begin_uplink(self, *, adr_ack_limit_exp: int, adr_ack_delay_exp: int) -> UplinkPlan:
        """Ouvre un cycle d'uplink. ADRACKReq est décidé ici (il fait partie de la trame)."""
        _check_exponent("adr_ack_limit_exp", adr_ack_limit_exp)
        _check_exponent("adr_ack_delay_exp", adr_ack_delay_exp)
        out = _CSessionUplinkPlan()
        with self._lock:
            handle = self._require_open()
            _check(LIB.lsim_session_begin_uplink(
                handle, adr_ack_limit_exp, adr_ack_delay_exp, ctypes.byref(out)))
        return UplinkPlan(
            fcnt32=int(out.fcnt32),
            rekey_ind=bool(out.rekey_ind),
            ack_req=bool(out.ack_req),
            default_channels_reenabled=bool(out.default_channels_reenabled),
        )

    def receive_downlink(self, *, fcnt32: int, uses_nf: bool = True, conf_received: bool = False,
                         server_version: int = 0) -> None:
        """Trame descendante reçue pendant le cycle courant (compteur déjà authentifié)."""
        if not isinstance(fcnt32, int) or isinstance(fcnt32, bool) or not 0 <= fcnt32 < 2**32:
            raise ValueError("fcnt32 doit être un entier sur 32 bits")
        with self._lock:
            handle = self._require_open()
            _check(LIB.lsim_session_receive_downlink(
                handle, 1 if uses_nf else 0, fcnt32, 1 if conf_received else 0, server_version))

    def end_uplink(self) -> SessionState:
        """Clôt le cycle : commit des compteurs, rekey, ADR_ACK_CNT."""
        out = _CSessionUplinkEnd()
        with self._lock:
            handle = self._require_open()
            _check(LIB.lsim_session_end_uplink(handle, ctypes.byref(out)))
        return SessionState(out.state)

    def snapshot(self) -> SessionSnapshot:
        out = _CSessionInfo()
        with self._lock:
            handle = self._require_open()
            _check(LIB.lsim_session_snapshot(handle, ctypes.byref(out)))
        return SessionSnapshot(
            state=SessionState(out.state),
            dev_addr=int(out.dev_addr),
            fcnt_up=int(out.fcnt_up),
            nf_cnt_dwn=int(out.nf_cnt_dwn),
            af_cnt_dwn=int(out.af_cnt_dwn),
            dr=int(out.dr),
            tx_power_index=int(out.tx_power_index),
            ack_cnt=int(out.ack_cnt),
            cycle_open=bool(out.cycle_open),
        )
