"""Rekey effectif (LoRaWAN 1.1 §5.10) : machines d'état dispositif et serveur.

Les états sont des objets immuables passés et renvoyés par l'appelant ; le cœur ne garde
aucun état. Voir core/include/lsim/rekey.hpp pour les règles.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
from enum import IntEnum

from lsim._native import LIB, _CRekeyDevice, _CRekeyServer, _U8P
from lsim.lora import StatusError


class DeviceRekeyState(IntEnum):
    IDLE = 0
    PENDING = 1
    CONFIRMED = 2
    NEEDS_JOIN = 3


class ServerAction(IntEnum):
    ACCEPT = 0
    ACCEPT_AND_CONFIRM = 1
    DISCARD = 2


@dataclass(frozen=True)
class DeviceRekey:
    state: DeviceRekeyState = DeviceRekeyState.IDLE
    uplinks: int = 0


@dataclass(frozen=True)
class ServerRekey:
    awaiting: bool = False


def _check(status: int) -> None:
    if status != 0:
        raise StatusError(status)


def device_join_accepted(state: DeviceRekey) -> DeviceRekey:
    c = _CRekeyDevice(int(state.state), state.uplinks)
    _check(LIB.lsim_rekey_device_join_accepted(ctypes.byref(c)))
    return DeviceRekey(DeviceRekeyState(c.state), int(c.uplinks))


def device_must_send_rekey_ind(state: DeviceRekey) -> bool:
    c = _CRekeyDevice(int(state.state), state.uplinks)
    out = ctypes.c_uint8(0)
    _check(LIB.lsim_rekey_device_must_send_rekey_ind(ctypes.byref(c), ctypes.byref(out)))
    return bool(out.value)


def device_uplink_completed(state: DeviceRekey, *, admin_limit: int, conf_received: bool = False,
                            server_version: int = 0) -> DeviceRekey:
    """Après chaque uplink et ses fenêtres de réception. admin_limit = ADR_ACK_LIMIT (1..2**64-1)."""
    if isinstance(admin_limit, bool) or not isinstance(admin_limit, int) or not 1 <= admin_limit < 2**64:
        raise ValueError("admin_limit doit être un entier entre 1 et 2**64-1")
    if isinstance(server_version, bool) or not isinstance(server_version, int) or not 0 <= server_version <= 255:
        raise ValueError("server_version doit être un octet")
    c = _CRekeyDevice(int(state.state), state.uplinks)
    _check(LIB.lsim_rekey_device_uplink_completed(ctypes.byref(c), admin_limit, int(bool(conf_received)),
                                                  server_version))
    return DeviceRekey(DeviceRekeyState(c.state), int(c.uplinks))


def server_join_accepted(state: ServerRekey) -> ServerRekey:
    c = _CRekeyServer(int(state.awaiting))
    _check(LIB.lsim_rekey_server_join_accepted(ctypes.byref(c)))
    return ServerRekey(bool(c.awaiting))


def server_on_uplink(state: ServerRekey, *, new_context: bool, has_rekey_ind: bool) -> tuple[ServerRekey, ServerAction]:
    c = _CRekeyServer(int(state.awaiting))
    action = ctypes.c_uint8(0)
    _check(LIB.lsim_rekey_server_on_uplink(ctypes.byref(c), int(bool(new_context)), int(bool(has_rekey_ind)),
                                           ctypes.byref(action)))
    return ServerRekey(bool(c.awaiting)), ServerAction(action.value)
