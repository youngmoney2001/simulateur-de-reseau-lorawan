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

Sessions et file de downlinks (couche données) : la session (clés de session 1.1 et compteurs)
est créée dans la transaction du join-accept ; l'ancienne session du même DevEUI est supprimée
dans la même transaction. Les clés de session sont stockées en clair : le fichier est créé en
mode 0600 et son mode est vérifié à l'ouverture. Ce choix est à valider (voir la documentation).

Sécurité du fichier : une base existante accessible par le groupe ou les autres est refusée.
"""

from __future__ import annotations

import os
import sqlite3
import stat
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional, Union

from lsim.registry import JoinRegistry
from lsim.rejoin import Rejoin02, Rejoin1
from lsim.security import JoinRequest, SessionKeys11

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
CREATE TABLE IF NOT EXISTS sessions (
    dev_addr INTEGER PRIMARY KEY,
    dev_eui BLOB NOT NULL UNIQUE,
    f_nwk_s_int_key BLOB NOT NULL,
    s_nwk_s_int_key BLOB NOT NULL,
    nwk_s_enc_key BLOB NOT NULL,
    app_s_key BLOB,
    fcnt_up INTEGER NOT NULL,
    nfcnt_down INTEGER NOT NULL,
    afcnt_down INTEGER NOT NULL,
    pending_conf INTEGER
);
CREATE TABLE IF NOT EXISTS downlink_queue (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    dev_eui BLOB NOT NULL,
    fport INTEGER NOT NULL,
    confirmed INTEGER NOT NULL,
    payload BLOB NOT NULL
);
CREATE INDEX IF NOT EXISTS downlink_queue_eui ON downlink_queue (dev_eui, seq);
"""

_BUSY_TIMEOUT_S = 30.0
QUEUE_LIMIT = 32              # downlinks en attente par dispositif
_DB_MODE_MASK = 0o077         # aucun accès groupe / autres


@dataclass(frozen=True)
class SessionRecord:
    """Session 1.1 persistée. `has_app_key` faux : app_s_key est absente (FPort > 0 impossible)."""
    dev_addr: int
    dev_eui: bytes
    keys: SessionKeys11 = field(repr=False)
    has_app_key: bool
    fcnt_up: int                  # -1 : aucun uplink reçu
    nfcnt_down: int
    afcnt_down: int
    pending_conf: Optional[int]   # compteur 32 bits du downlink confirmé non acquitté


@dataclass(frozen=True)
class QueueItem:
    seq: int
    fport: int
    confirmed: bool
    payload: bytes = field(repr=False)


class QueueFullError(OverflowError):
    """File de downlinks pleine pour ce dispositif."""


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

    # Sessions

    def put_session(self, dev_eui: bytes, dev_addr: int, keys: SessionKeys11,
                    has_app_key: bool) -> None:
        """Remplace la session du dispositif (rejoin : l'ancienne disparaît dans la transaction)."""
        self._conn.execute("DELETE FROM sessions WHERE dev_eui = ? OR dev_addr = ?",
                           (dev_eui, dev_addr))
        self._conn.execute(
            "INSERT INTO sessions (dev_addr, dev_eui, f_nwk_s_int_key, s_nwk_s_int_key,"
            " nwk_s_enc_key, app_s_key, fcnt_up, nfcnt_down, afcnt_down, pending_conf)"
            " VALUES (?, ?, ?, ?, ?, ?, -1, 0, 0, NULL)",
            (dev_addr, dev_eui, keys.f_nwk_s_int_key, keys.s_nwk_s_int_key, keys.nwk_s_enc_key,
             keys.app_s_key if has_app_key else None))
        # Une file de la session précédente ne doit pas survivre au rejoin.
        self._conn.execute("DELETE FROM downlink_queue WHERE dev_eui = ?", (dev_eui,))

    def session_by_addr(self, dev_addr: int) -> Optional[SessionRecord]:
        return self._session("WHERE dev_addr = ?", dev_addr)

    def session_by_eui(self, dev_eui: bytes) -> Optional[SessionRecord]:
        return self._session("WHERE dev_eui = ?", dev_eui)

    def _session(self, where: str, value) -> Optional[SessionRecord]:
        row = self._conn.execute(
            "SELECT dev_addr, dev_eui, f_nwk_s_int_key, s_nwk_s_int_key, nwk_s_enc_key,"
            " app_s_key, fcnt_up, nfcnt_down, afcnt_down, pending_conf FROM sessions " + where,
            (value,)).fetchone()
        if row is None:
            return None
        has_app = row[5] is not None
        keys = SessionKeys11(
            f_nwk_s_int_key=bytes(row[2]), s_nwk_s_int_key=bytes(row[3]),
            nwk_s_enc_key=bytes(row[4]),
            app_s_key=bytes(row[5]) if has_app else bytes(16))
        return SessionRecord(dev_addr=row[0], dev_eui=bytes(row[1]), keys=keys,
                             has_app_key=has_app, fcnt_up=row[6], nfcnt_down=row[7],
                             afcnt_down=row[8], pending_conf=row[9])

    def save_counters(self, dev_addr: int, fcnt_up: int, nfcnt_down: int, afcnt_down: int,
                      pending_conf: Optional[int]) -> None:
        self._conn.execute(
            "UPDATE sessions SET fcnt_up = ?, nfcnt_down = ?, afcnt_down = ?, pending_conf = ?"
            " WHERE dev_addr = ?",
            (fcnt_up, nfcnt_down, afcnt_down, pending_conf, dev_addr))

    # File de downlinks

    def enqueue(self, dev_eui: bytes, fport: int, confirmed: bool, payload: bytes) -> int:
        count = self._conn.execute(
            "SELECT COUNT(*) FROM downlink_queue WHERE dev_eui = ?", (dev_eui,)).fetchone()[0]
        if count >= QUEUE_LIMIT:
            raise QueueFullError(f"file pleine ({QUEUE_LIMIT} downlinks)")
        cur = self._conn.execute(
            "INSERT INTO downlink_queue (dev_eui, fport, confirmed, payload) VALUES (?, ?, ?, ?)",
            (dev_eui, fport, 1 if confirmed else 0, payload))
        return cur.lastrowid

    def queue_head(self, dev_eui: bytes) -> Optional[QueueItem]:
        row = self._conn.execute(
            "SELECT seq, fport, confirmed, payload FROM downlink_queue WHERE dev_eui = ?"
            " ORDER BY seq LIMIT 1", (dev_eui,)).fetchone()
        if row is None:
            return None
        return QueueItem(seq=row[0], fport=row[1], confirmed=bool(row[2]), payload=bytes(row[3]))

    def dequeue(self, seq: int) -> None:
        self._conn.execute("DELETE FROM downlink_queue WHERE seq = ?", (seq,))

    def queue_length(self, dev_eui: bytes) -> int:
        return self._conn.execute(
            "SELECT COUNT(*) FROM downlink_queue WHERE dev_eui = ?", (dev_eui,)).fetchone()[0]


class DurableJoinStore:
    """Registre de jointure persistant. Plusieurs processus peuvent l'ouvrir simultanément."""

    def __init__(self, path: Union[str, Path], integrity_key: bytes) -> None:
        self._path = str(path)
        self._key = _check_key(integrity_key)
        _secure_file(self._path)
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

    def enqueue_downlink(self, dev_eui: bytes, fport: int, confirmed: bool,
                         payload: bytes) -> int:
        """Ajoute un downlink à la file ; refuse si la session n'a pas la clé applicative (FPort > 0)."""
        with self.transaction() as tx:
            session = tx.session_by_eui(dev_eui)
            if session is None:
                raise KeyError("aucune session pour ce DevEUI")
            if fport > 0 and not session.has_app_key:
                raise ValueError("clé applicative absente : FPort > 0 impossible")
            return tx.enqueue(dev_eui, fport, confirmed, payload)

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


def _secure_file(path: str) -> None:
    """Crée la base en mode 0600 ; refuse une base existante lisible par d'autres utilisateurs."""
    if path == ":memory:":
        return
    if os.path.exists(path):
        mode = stat.S_IMODE(os.stat(path).st_mode)
        if mode & _DB_MODE_MASK:
            raise PermissionError(
                f"{path} : mode {oct(mode)} trop ouvert (attendu 0600 : clés de session)")
        return
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)


def _check_key(key: bytes) -> bytes:
    if not isinstance(key, (bytes, bytearray)) or len(key) != 16:
        raise ValueError("integrity_key doit faire 16 octets")
    return bytes(key)
