"""Registre serveur des DevNonce et RJcount par dispositif (état côté cœur natif).

Le registre est désigné par un identifiant entier opaque : aucun pointeur interne
n'est exposé. Un message n'est accepté que si son MIC est valide ET son compteur
strictement croissant ; un MIC faux ne modifie jamais l'état. Les clés sont passées
à chaque appel et ne sont pas conservées par ce module.
"""

from __future__ import annotations

import ctypes
import os
import threading
from pathlib import Path

from lsim._native import LIB, _CJoinRequest, _CRejoin02, _CRejoin1, _U8P
from lsim.lora import StatusError
from lsim.rejoin import Rejoin02, Rejoin1
from lsim.security import JoinRequest

MAX_DEVICES = 10_000
_STATUS_BUFFER_TOO_SMALL = 706  # 700 + RegistryStatus::BufferTooSmall


def _bytes(name: str, value: bytes, size: int) -> ctypes.Array:
    if not isinstance(value, (bytes, bytearray)) or len(value) != size:
        raise ValueError(f"{name} doit être une séquence de {size} octets")
    return (ctypes.c_uint8 * size).from_buffer_copy(bytes(value))


def _wire(data: bytes) -> tuple[ctypes.Array, int]:
    if not isinstance(data, (bytes, bytearray)):
        raise ValueError("data doit être de type bytes")
    buf = (ctypes.c_uint8 * max(len(data), 1)).from_buffer_copy(bytes(data) or b"\x00")
    return buf, len(data)


def _check(status: int) -> None:
    if status != 0:
        raise StatusError(status)


class JoinRegistry:
    """Compteurs de jointure d'un serveur. À fermer avec `close()` ou `with`."""

    def __init__(self, max_devices: int = 10_000) -> None:
        if isinstance(max_devices, bool) or not isinstance(max_devices, int) or not 1 <= max_devices <= MAX_DEVICES:
            raise ValueError(f"max_devices doit être compris entre 1 et {MAX_DEVICES}")
        handle = ctypes.c_uint64(0)
        _check(LIB.lsim_registry_create(max_devices, ctypes.byref(handle)))
        self._handle = handle.value
        self._lock = threading.Lock()

    def __enter__(self) -> "JoinRegistry":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        if getattr(self, "_handle", 0):
            LIB.lsim_registry_destroy(self._handle)
            self._handle = 0

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:  # pragma: no cover - destructeur : ne jamais lever
            pass

    def accept_join_request(self, wire: bytes, nwk_key: bytes) -> JoinRequest:
        """Join-request acceptée (MIC et DevNonce croissant) ; lève StatusError sinon."""
        key = _bytes("nwk_key", nwk_key, 16)
        buf, n = _wire(wire)
        out = _CJoinRequest()
        with self._lock:
            _check(LIB.lsim_registry_accept_join_request(
                self._handle, ctypes.cast(buf, _U8P), n, ctypes.cast(key, _U8P), ctypes.byref(out)))
        return JoinRequest(bytes(out.join_eui), bytes(out.dev_eui), bytes(out.dev_nonce))

    def accept_rejoin_02(self, wire: bytes, s_nwk_s_int_key: bytes) -> Rejoin02:
        key = _bytes("s_nwk_s_int_key", s_nwk_s_int_key, 16)
        buf, n = _wire(wire)
        out = _CRejoin02()
        with self._lock:
            _check(LIB.lsim_registry_accept_rejoin_02(
                self._handle, ctypes.cast(buf, _U8P), n, ctypes.cast(key, _U8P), ctypes.byref(out)))
        return Rejoin02(out.rejoin_type, bytes(out.net_id), bytes(out.dev_eui), out.rjcount0)

    def accept_rejoin_1(self, wire: bytes, js_int_key: bytes) -> Rejoin1:
        key = _bytes("js_int_key", js_int_key, 16)
        buf, n = _wire(wire)
        out = _CRejoin1()
        with self._lock:
            _check(LIB.lsim_registry_accept_rejoin_1(
                self._handle, ctypes.cast(buf, _U8P), n, ctypes.cast(key, _U8P), ctypes.byref(out)))
        return Rejoin1(bytes(out.join_eui), bytes(out.dev_eui), out.rjcount1)

    def on_join_accepted(self, dev_eui: bytes) -> None:
        """Join-accept traité : RJcount0 du dispositif repart de zéro."""
        eui = _bytes("dev_eui", dev_eui, 8)
        with self._lock:
            _check(LIB.lsim_registry_on_join_accepted(self._handle, ctypes.cast(eui, _U8P)))

    @property
    def device_count(self) -> int:
        count = ctypes.c_uint64(0)
        with self._lock:
            _check(LIB.lsim_registry_device_count(self._handle, ctypes.byref(count)))
        return count.value

    def export_state(self, integrity_key: bytes) -> bytes:
        """Sauvegarde protégée par AES-CMAC (clé d'intégrité de 16 octets, fournie par l'appelant)."""
        key = _bytes("integrity_key", integrity_key, 16)
        kp = ctypes.cast(key, _U8P)
        needed = ctypes.c_size_t(0)
        with self._lock:
            # Première passe : taille requise (BufferTooSmall attendu, sans écriture).
            status = LIB.lsim_registry_export(self._handle, kp, None, 0, ctypes.byref(needed))
            if status not in (0, _STATUS_BUFFER_TOO_SMALL):
                _check(status)
            if needed.value == 0:
                return b""
            buf = (ctypes.c_uint8 * needed.value)()
            written = ctypes.c_size_t(0)
            _check(LIB.lsim_registry_export(self._handle, kp, buf, needed.value, ctypes.byref(written)))
        return bytes(buf[:written.value])

    @classmethod
    def import_state(cls, blob: bytes, integrity_key: bytes) -> "JoinRegistry":
        """Recharge une sauvegarde. Lève StatusError (707 : falsifiée, 708 : format, 709 : incohérente) sans rien créer."""
        if not isinstance(blob, (bytes, bytearray)) or len(blob) == 0:
            raise ValueError("blob doit être une séquence d'octets non vide")
        key = _bytes("integrity_key", integrity_key, 16)
        buf, n = _wire(bytes(blob))
        handle = ctypes.c_uint64(0)
        _check(LIB.lsim_registry_import(ctypes.cast(key, _U8P), ctypes.cast(buf, _U8P), n, ctypes.byref(handle)))
        reg = cls.__new__(cls)
        reg._handle = handle.value
        reg._lock = threading.Lock()
        return reg

    def save(self, path: str | os.PathLike, integrity_key: bytes) -> None:
        """Écriture atomique : fichier temporaire, fsync, puis remplacement (os.replace)."""
        data = self.export_state(integrity_key)
        target = Path(path)
        tmp = target.with_name(target.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, target)
        except BaseException:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass
            raise

    @classmethod
    def load(cls, path: str | os.PathLike, integrity_key: bytes) -> "JoinRegistry":
        return cls.import_state(Path(path).read_bytes(), integrity_key)
