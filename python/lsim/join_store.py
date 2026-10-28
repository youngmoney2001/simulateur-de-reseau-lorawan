"""Persistance durable du registre de jointure, partageable entre processus (SQLite).

Principe :
- l'état du registre est celui du cœur natif (`JoinRegistry`), sérialisé par
  `export_state` (protégé par AES-CMAC) et stocké dans une seule ligne SQLite ;
- chaque opération s'exécute dans une transaction `BEGIN IMMEDIATE` : un seul écrivain à la
  fois, tous processus confondus. L'état est relu, modifié par le cœur natif, puis réécrit
  dans la même transaction ; en cas d'erreur (MIC faux, rejeu), la transaction est annulée
  et rien n'est écrit ;
- l'import vérifie le MIC de l'état avant tout usage : une base falsifiée est refusée.

Périmètre : un fichier sur un système local, partagé par des processus d'une même machine.
Le verrouillage SQLite n'est pas fiable sur NFS ou SMB : un déploiement multi-hôtes doit passer
par un unique processus serveur qui possède la base.

Les compteurs annexes (JoinNonce par dispositif, prochaine adresse) vivent dans la même base,
dans la même transaction que l'acceptation de la jointure.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator, Optional, Union

from lsim.registry import JoinRegistry
from lsim.rejoin import Rejoin02, Rejoin1
from lsim.security import JoinRequest

_SCHEMA = """
CREATE TABLE IF NOT EXISTS registry_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    blob BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS counters (
    name TEXT NOT NULL,
    scope BLOB NOT NULL,
    value INTEGER NOT NULL,
    PRIMARY KEY (name, scope)
);
CREATE TABLE IF NOT EXISTS device_addresses (
    dev_eui BLOB PRIMARY KEY,
    dev_addr INTEGER NOT NULL
);
"""

_BUSY_TIMEOUT_S = 30.0


class Transaction:
    """Accès au registre et aux compteurs, à l'intérieur d'une transaction d'écriture."""

    def __init__(self, conn: sqlite3.Connection, registry: JoinRegistry) -> None:
        self._conn = conn
        self.registry = registry

    def next_value(self, name: str, scope: bytes, limit: int) -> int:
        """Retourne la valeur courante puis l'incrémente ; OverflowError à `limit`."""
        row = self._conn.execute(
            "SELECT value FROM counters WHERE name = ? AND scope = ?", (name, scope)).fetchone()
        value = row[0] if row else 0
        if value >= limit:
            raise OverflowError(f"compteur {name} épuisé")
        self._conn.execute(
            "INSERT INTO counters (name, scope, value) VALUES (?, ?, ?) "
            "ON CONFLICT (name, scope) DO UPDATE SET value = excluded.value",
            (name, scope, value + 1))
        return value

    def set_device_address(self, dev_eui: bytes, dev_addr: int) -> None:
        self._conn.execute(
            "INSERT INTO device_addresses (dev_eui, dev_addr) VALUES (?, ?) "
            "ON CONFLICT (dev_eui) DO UPDATE SET dev_addr = excluded.dev_addr",
            (dev_eui, dev_addr))

    def device_address(self, dev_eui: bytes) -> Optional[int]:
        row = self._conn.execute(
            "SELECT dev_addr FROM device_addresses WHERE dev_eui = ?", (dev_eui,)).fetchone()
        return row[0] if row else None


class DurableJoinStore:
    """Registre de jointure persistant. Plusieurs processus peuvent l'ouvrir simultanément."""

    def __init__(self, path: Union[str, Path], integrity_key: bytes) -> None:
        self._path = str(path)
        self._key = _check_key(integrity_key)
        conn = self._connect()
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=FULL")
            conn.executescript(_SCHEMA)
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path, timeout=_BUSY_TIMEOUT_S, isolation_level=None)

    def _load(self, conn: sqlite3.Connection) -> JoinRegistry:
        row = conn.execute("SELECT blob FROM registry_state WHERE id = 1").fetchone()
        if row is None:
            return JoinRegistry()
        return JoinRegistry.import_state(bytes(row[0]), self._key)

    @contextmanager
    def transaction(self) -> Iterator[Transaction]:
        """Transaction d'écriture : l'état est validé et réécrit seulement si le bloc réussit."""
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            registry = self._load(conn)
            try:
                yield Transaction(conn, registry)
                blob = registry.export_state(self._key)
            finally:
                registry.close()
            conn.execute(
                "INSERT INTO registry_state (id, blob) VALUES (1, ?) "
                "ON CONFLICT (id) DO UPDATE SET blob = excluded.blob", (blob,))
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    # Opérations simples (une transaction chacune).

    def accept_join_request(self, wire: bytes, nwk_key: bytes) -> JoinRequest:
        with self.transaction() as tx:
            return tx.registry.accept_join_request(wire, nwk_key)

    def accept_rejoin_02(self, wire: bytes, s_nwk_s_int_key: bytes) -> Rejoin02:
        with self.transaction() as tx:
            return tx.registry.accept_rejoin_02(wire, s_nwk_s_int_key)

    def accept_rejoin_1(self, wire: bytes, js_int_key: bytes) -> Rejoin1:
        with self.transaction() as tx:
            return tx.registry.accept_rejoin_1(wire, js_int_key)

    def on_join_accepted(self, dev_eui: bytes) -> None:
        with self.transaction() as tx:
            tx.registry.on_join_accepted(dev_eui)

    def device_count(self) -> int:
        conn = self._connect()
        try:
            conn.execute("BEGIN")  # lecture cohérente : instantané de la transaction
            registry = self._load(conn)
            try:
                return registry.device_count
            finally:
                registry.close()
        finally:
            if conn.in_transaction:
                conn.execute("COMMIT")
            conn.close()


def _check_key(key: bytes) -> bytes:
    if not isinstance(key, (bytes, bytearray)) or len(key) != 16:
        raise ValueError("integrity_key doit faire 16 octets")
    return bytes(key)
