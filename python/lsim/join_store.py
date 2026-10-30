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
dans la même transaction. Les clés de session, les compteurs et les charges en file sont chiffrés
au repos (AES-256-GCM, `lsim.sealed`) avec une clé de données distincte, fournie par l'appelant.
Le fichier est créé en mode 0600 et son mode est vérifié à l'ouverture.

Sécurité du fichier : une base existante accessible par le groupe ou les autres est refusée.
"""

from __future__ import annotations

import os
import struct
import sqlite3
import stat
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional, Union

from lsim.registry import JoinRegistry
from lsim.rejoin import Rejoin02, Rejoin1
from lsim.sealed import RecordSealer
from lsim.plan import Plan, get_plan
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
    sealed BLOB NOT NULL            -- clés et compteurs, chiffrés (lsim.sealed)
);
CREATE TABLE IF NOT EXISTS pending_sessions (
    dev_eui BLOB PRIMARY KEY,
    dev_addr INTEGER NOT NULL UNIQUE,
    sealed BLOB NOT NULL            -- contexte du dernier rejoin, en attente d'un uplink valide
);
CREATE TABLE IF NOT EXISTS downlink_queue (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    dev_eui BLOB NOT NULL,
    fport INTEGER NOT NULL,
    confirmed INTEGER NOT NULL,
    payload BLOB NOT NULL           -- charge applicative, chiffrée (lsim.sealed)
);
CREATE INDEX IF NOT EXISTS downlink_queue_eui ON downlink_queue (dev_eui, seq);
CREATE TABLE IF NOT EXISTS mac_pending (
    dev_eui BLOB NOT NULL,
    cid INTEGER NOT NULL,
    command BLOB NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (dev_eui, cid)
);
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


# Commande MAC à acquitter : renvoyée dans les FOpts du prochain downlink tant que le dispositif
# ne la confirme pas (LinkADRAns positif). TS001-1.0.4 §5 : l'émetteur décide de renvoyer quand il
# reçoit une nouvelle trame sans la réponse attendue ; il n'y a ni nombre maximal de réémissions
# ni délai exponentiel. Ce plafond est une politique d'implémentation facultative : None = aucun.
MAC_MAX_ATTEMPTS: Optional[int] = None


@dataclass(frozen=True)
class PendingMac:
    cid: int
    command: bytes = field(repr=False)
    attempts: int


class QueueFullError(OverflowError):
    """File de downlinks pleine pour ce dispositif."""


class Transaction:
    """Accès au registre et aux compteurs, à l'intérieur d'une transaction d'écriture."""

    def __init__(self, conn: sqlite3.Connection, registry: JoinRegistry,
                 sealer: Optional[RecordSealer]) -> None:
        self._conn = conn
        self.registry = registry
        self._sealer = sealer

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

    # Sessions (chiffrées) : un enregistrement scellé par dispositif, compteurs inclus.

    def _need_sealer(self) -> RecordSealer:
        if self._sealer is None:
            raise RuntimeError("clé de données absente : sessions et file indisponibles")
        return self._sealer

    @staticmethod
    def _session_aad(dev_addr: int, dev_eui: bytes) -> bytes:
        return b"lsim/session/v1" + dev_addr.to_bytes(4, "big") + bytes(dev_eui)

    def put_session(self, dev_eui: bytes, dev_addr: int, keys: SessionKeys11,
                    has_app_key: bool) -> None:
        """Remplace la session du dispositif (join-request : ancienne session, contexte en attente,
        commandes MAC et file disparaissent dans la transaction)."""
        sealer = self._need_sealer()
        self._conn.execute("DELETE FROM sessions WHERE dev_eui = ? OR dev_addr = ?",
                           (dev_eui, dev_addr))
        self._conn.execute("DELETE FROM pending_sessions WHERE dev_eui = ?", (dev_eui,))
        # Join-request : réinitialisation complète des paramètres MAC (1.1 §6.2.3).
        self._conn.execute("DELETE FROM mac_pending WHERE dev_eui = ?", (dev_eui,))
        plain = _encode_session(keys, has_app_key, fcnt_up=-1, nfcnt=0, afcnt=0, pending=None)
        self._conn.execute(
            "INSERT INTO sessions (dev_addr, dev_eui, sealed) VALUES (?, ?, ?)",
            (dev_addr, dev_eui, sealer.seal(plain, self._session_aad(dev_addr, dev_eui))))
        # Une file de la session précédente ne doit pas survivre au rejoin.
        self._conn.execute("DELETE FROM downlink_queue WHERE dev_eui = ?", (dev_eui,))

    @staticmethod
    def _pending_aad(dev_addr: int, dev_eui: bytes) -> bytes:
        return b"lsim/pending/v1" + dev_addr.to_bytes(4, "big") + bytes(dev_eui)

    def put_pending_session(self, dev_eui: bytes, dev_addr: int, keys: SessionKeys11,
                            has_app_key: bool) -> None:
        """Contexte issu d'un rejoin (1.1 §6.2.4) : l'ancienne session reste valide.

        Le nouveau est mis en attente jusqu'au premier uplink valide qui l'utilise. Un rejoin
        antérieur encore en attente est remplacé (l'ancienne session n'est pas touchée)."""
        sealer = self._need_sealer()
        self._conn.execute("DELETE FROM pending_sessions WHERE dev_eui = ?", (dev_eui,))
        plain = _encode_session(keys, has_app_key, fcnt_up=-1, nfcnt=0, afcnt=0, pending=None)
        self._conn.execute(
            "INSERT INTO pending_sessions (dev_eui, dev_addr, sealed) VALUES (?, ?, ?)",
            (dev_eui, dev_addr, sealer.seal(plain, self._pending_aad(dev_addr, dev_eui))))

    def pending_by_addr(self, dev_addr: int) -> Optional[SessionRecord]:
        sealer = self._need_sealer()
        row = self._conn.execute(
            "SELECT dev_eui, sealed FROM pending_sessions WHERE dev_addr = ?",
            (dev_addr,)).fetchone()
        if row is None:
            return None
        dev_eui, blob = bytes(row[0]), bytes(row[1])
        plain = sealer.open(blob, self._pending_aad(dev_addr, dev_eui))
        return _decode_session(dev_addr, dev_eui, plain)

    def promote_pending(self, dev_eui: bytes) -> SessionRecord:
        """Premier uplink valide du nouveau contexte : il remplace l'ancien, dans la transaction.

        L'ancienne session et sa file de downlinks disparaissent ; le contexte en attente
        devient la session. Lève ValueError s'il n'y a rien en attente."""
        sealer = self._need_sealer()
        row = self._conn.execute(
            "SELECT dev_addr, sealed FROM pending_sessions WHERE dev_eui = ?",
            (dev_eui,)).fetchone()
        if row is None:
            raise ValueError("aucun contexte en attente pour ce dispositif")
        dev_addr, blob = int(row[0]), bytes(row[1])
        plain = sealer.open(blob, self._pending_aad(dev_addr, dev_eui))
        self._conn.execute("DELETE FROM sessions WHERE dev_eui = ?", (dev_eui,))
        self._conn.execute("DELETE FROM pending_sessions WHERE dev_eui = ?", (dev_eui,))
        self._conn.execute(
            "INSERT INTO sessions (dev_addr, dev_eui, sealed) VALUES (?, ?, ?)",
            (dev_addr, dev_eui, sealer.seal(plain, self._session_aad(dev_addr, dev_eui))))
        # La file de downlinks est conservée : elle part sur le nouveau contexte.
        return _decode_session(dev_addr, dev_eui, plain)

    def pending_by_eui(self, dev_eui: bytes) -> Optional[SessionRecord]:
        row = self._conn.execute(
            "SELECT dev_addr FROM pending_sessions WHERE dev_eui = ?", (dev_eui,)).fetchone()
        return None if row is None else self.pending_by_addr(int(row[0]))

    def clear_mac_pending(self, dev_eui: bytes) -> None:
        """Commandes MAC en attente abandonnées : le dispositif réinitialise ses paramètres MAC."""
        self._conn.execute("DELETE FROM mac_pending WHERE dev_eui = ?", (dev_eui,))

    def session_by_addr(self, dev_addr: int) -> Optional[SessionRecord]:
        return self._session("WHERE dev_addr = ?", dev_addr)

    def session_by_eui(self, dev_eui: bytes) -> Optional[SessionRecord]:
        return self._session("WHERE dev_eui = ?", dev_eui)

    def _session(self, where: str, value) -> Optional[SessionRecord]:
        sealer = self._need_sealer()
        row = self._conn.execute(
            "SELECT dev_addr, dev_eui, sealed FROM sessions " + where, (value,)).fetchone()
        if row is None:
            return None
        dev_addr, dev_eui, blob = row[0], bytes(row[1]), bytes(row[2])
        plain = sealer.open(blob, self._session_aad(dev_addr, dev_eui))
        return _decode_session(dev_addr, dev_eui, plain)

    def save_counters(self, dev_addr: int, fcnt_up: int, nfcnt_down: int, afcnt_down: int,
                      pending_conf: Optional[int]) -> None:
        rec = self.session_by_addr(dev_addr)
        if rec is None:
            raise KeyError("aucune session à mettre à jour")
        sealer = self._need_sealer()
        plain = _encode_session(rec.keys, rec.has_app_key, fcnt_up=fcnt_up,
                                nfcnt=nfcnt_down, afcnt=afcnt_down, pending=pending_conf)
        self._conn.execute("UPDATE sessions SET sealed = ? WHERE dev_addr = ?",
                           (sealer.seal(plain, self._session_aad(dev_addr, rec.dev_eui)),
                            dev_addr))

    # File de downlinks (charges chiffrées, liées à DevEUI, FPort et ConfirmedFlag)

    @staticmethod
    def _queue_aad(dev_eui: bytes, fport: int, confirmed: bool) -> bytes:
        return b"lsim/queue/v1" + bytes(dev_eui) + bytes([fport, 1 if confirmed else 0])

    def enqueue(self, dev_eui: bytes, fport: int, confirmed: bool, payload: bytes) -> int:
        sealer = self._need_sealer()
        count = self._conn.execute(
            "SELECT COUNT(*) FROM downlink_queue WHERE dev_eui = ?", (dev_eui,)).fetchone()[0]
        if count >= QUEUE_LIMIT:
            raise QueueFullError(f"file pleine ({QUEUE_LIMIT} downlinks)")
        sealed = sealer.seal(payload, self._queue_aad(dev_eui, fport, confirmed))
        cur = self._conn.execute(
            "INSERT INTO downlink_queue (dev_eui, fport, confirmed, payload) VALUES (?, ?, ?, ?)",
            (dev_eui, fport, 1 if confirmed else 0, sealed))
        return cur.lastrowid

    def queue_head(self, dev_eui: bytes) -> Optional[QueueItem]:
        row = self._conn.execute(
            "SELECT seq, fport, confirmed, payload FROM downlink_queue WHERE dev_eui = ?"
            " ORDER BY seq LIMIT 1", (dev_eui,)).fetchone()
        if row is None:
            return None
        fport, confirmed = row[1], bool(row[2])
        payload = self._need_sealer().open(bytes(row[3]), self._queue_aad(dev_eui, fport, confirmed))
        return QueueItem(seq=row[0], fport=fport, confirmed=confirmed, payload=payload)

    def dequeue(self, seq: int) -> None:
        self._conn.execute("DELETE FROM downlink_queue WHERE seq = ?", (seq,))

    def queue_length(self, dev_eui: bytes) -> int:
        return self._conn.execute(
            "SELECT COUNT(*) FROM downlink_queue WHERE dev_eui = ?", (dev_eui,)).fetchone()[0]

    @staticmethod
    def _mac_aad(dev_eui: bytes, cid: int) -> bytes:
        return b"lsim/mac/v1" + bytes(dev_eui) + bytes([cid])

    def enqueue_mac(self, dev_eui: bytes, cid: int, command: bytes) -> None:
        """Met une commande MAC à acquitter (remplace une commande de même CID, compteur remis à 0)."""
        if not 0 <= cid <= 255 or not 1 <= len(command) <= 15:
            raise ValueError("commande MAC : CID 0..255 et 1 à 15 octets")
        sealed = self._need_sealer().seal(bytes(command), self._mac_aad(dev_eui, cid))
        self._conn.execute(
            "INSERT INTO mac_pending (dev_eui, cid, command, attempts) VALUES (?, ?, ?, 0)"
            " ON CONFLICT(dev_eui, cid) DO UPDATE SET command = excluded.command, attempts = 0",
            (dev_eui, cid, sealed))

    def pending_mac(self, dev_eui: bytes) -> list[PendingMac]:
        rows = self._conn.execute(
            "SELECT cid, command, attempts FROM mac_pending WHERE dev_eui = ? ORDER BY cid",
            (dev_eui,)).fetchall()
        sealer = self._need_sealer()
        return [PendingMac(cid=cid, command=sealer.open(bytes(blob), self._mac_aad(dev_eui, cid)),
                           attempts=attempts)
                for cid, blob, attempts in rows]

    def mac_attempted(self, dev_eui: bytes, cid: int) -> None:
        self._conn.execute(
            "UPDATE mac_pending SET attempts = attempts + 1 WHERE dev_eui = ? AND cid = ?",
            (dev_eui, cid))

    def mac_done(self, dev_eui: bytes, cid: int) -> None:
        self._conn.execute("DELETE FROM mac_pending WHERE dev_eui = ? AND cid = ?", (dev_eui, cid))


# Format interne d'une session (clair avant scellement) : clés, has_app, FCntUp, NFCntDown,
# AFCntDown, drapeau et valeur de la confirmation en attente.
_SESSION_FMT = ">16s16s16s16sBqIIBI"


def _encode_session(keys: SessionKeys11, has_app: bool, *, fcnt_up: int, nfcnt: int,
                    afcnt: int, pending: Optional[int]) -> bytes:
    return struct.pack(
        _SESSION_FMT, keys.f_nwk_s_int_key, keys.s_nwk_s_int_key, keys.nwk_s_enc_key,
        keys.app_s_key if has_app else bytes(16), 1 if has_app else 0,
        fcnt_up, nfcnt, afcnt, 0 if pending is None else 1, 0 if pending is None else pending)


def _decode_session(dev_addr: int, dev_eui: bytes, plain: bytes) -> SessionRecord:
    f_nwk, s_nwk, nwk_enc, app, has_app, fcnt_up, nfcnt, afcnt, pend_flag, pend = \
        struct.unpack(_SESSION_FMT, plain)
    keys = SessionKeys11(f_nwk_s_int_key=f_nwk, s_nwk_s_int_key=s_nwk, nwk_s_enc_key=nwk_enc,
                         app_s_key=app)
    return SessionRecord(dev_addr=dev_addr, dev_eui=dev_eui, keys=keys,
                         has_app_key=bool(has_app), fcnt_up=fcnt_up, nfcnt_down=nfcnt,
                         afcnt_down=afcnt, pending_conf=pend if pend_flag else None)


class DurableJoinStore:
    """Registre de jointure persistant. Plusieurs processus peuvent l'ouvrir simultanément."""

    def __init__(self, path: Union[str, Path], integrity_key: bytes,
                 data_key: Optional[bytes] = None) -> None:
        """`data_key` (32 octets) chiffre sessions et file ; sans elle, ces opérations sont refusées."""
        self._path = str(path)
        self._key = _check_key(integrity_key)
        self._sealer = RecordSealer(data_key) if data_key is not None else None
        _secure_file(self._path)
        conn = self._connect()
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=FULL")
            conn.executescript(_SCHEMA)
            cols = [row[1] for row in conn.execute("PRAGMA table_info(sessions)")]
            if "sealed" not in cols:
                raise ValueError(
                    "base au format de développement (sessions en clair) : supprimer le fichier "
                    "et relancer la jointure ; le format chiffré est requis")
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
                yield Transaction(conn, registry, self._sealer)
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
                         payload: bytes, plan: Optional[Plan] = None) -> int:
        """Ajoute un downlink à la file.

        Refuse : session absente ; FPort hors 1..223 ; FPort > 0 sans clé applicative ; charge
        au-delà de `plan.queue_payload_max` (la fenêtre RX1 la plus étroite du plan).
        """
        plan = plan if plan is not None else get_plan("EU868")
        if not 1 <= fport <= 223:
            raise ValueError("FPort applicatif : 1 à 223")
        if len(payload) > plan.queue_payload_max:
            raise ValueError(
                f"charge limitée à {plan.queue_payload_max} octets (plan {plan.name})")
        with self.transaction() as tx:
            session = tx.session_by_eui(dev_eui)
            if session is None:
                raise KeyError("aucune session pour ce DevEUI")
            if not session.has_app_key:
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
