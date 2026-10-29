"""Persistance des sessions du panneau d'étude et de leur journal (SQLite).

Le fichier est celui des runs (`--runs-db`) : une seule base à sauvegarder. Chaque session est un
document JSON (topologie, configurations CLI, liaisons, indices, compteurs) ; chaque tentative est
une ligne du journal. Le service écrit à chaque modification, sous son verrou, et relit tout au
démarrage : les sessions survivent au redémarrage tant qu'elles ne sont pas expirées.

Ne contient aucun secret : la configuration CLI n'en porte pas (voir `study_cli`).
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS study_sessions (
    session_id TEXT PRIMARY KEY,
    owner      TEXT NOT NULL,
    last_used  REAL NOT NULL,
    body       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS study_sessions_owner ON study_sessions (owner);
CREATE TABLE IF NOT EXISTS study_attempts (
    session_id TEXT NOT NULL REFERENCES study_sessions (session_id) ON DELETE CASCADE,
    number     INTEGER NOT NULL,
    body       TEXT NOT NULL,
    PRIMARY KEY (session_id, number)
);
"""


class StudyStore:
    """Non thread-safe : appelé uniquement sous le verrou de `StudyService`."""

    def __init__(self, path: str) -> None:
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.execute("PRAGMA foreign_keys = ON")
        if path != ":memory:":
            self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.execute("PRAGMA synchronous = FULL")
            self._conn.execute("PRAGMA busy_timeout = 5000")
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        self._conn.close()

    def load_sessions(self) -> list[tuple[str, str, float, dict[str, Any]]]:
        rows = self._conn.execute(
            "SELECT session_id, owner, last_used, body FROM study_sessions").fetchall()
        return [(sid, owner, float(used), json.loads(body)) for sid, owner, used, body in rows]

    def save_session(self, sid: str, owner: str, last_used: float, body: dict[str, Any]) -> None:
        self._conn.execute(
            "INSERT INTO study_sessions (session_id, owner, last_used, body) VALUES (?, ?, ?, ?) "
            "ON CONFLICT (session_id) DO UPDATE SET last_used = excluded.last_used, "
            "body = excluded.body",
            (sid, owner, last_used, json.dumps(body, ensure_ascii=False)))

    def delete_session(self, sid: str) -> None:
        self._conn.execute("DELETE FROM study_attempts WHERE session_id = ?", (sid,))
        self._conn.execute("DELETE FROM study_sessions WHERE session_id = ?", (sid,))

    def add_attempt(self, sid: str, number: int, body: dict[str, Any], keep: int) -> None:
        """Ajoute une tentative et ne garde que les `keep` plus récentes de la session."""
        self._conn.execute(
            "INSERT INTO study_attempts (session_id, number, body) VALUES (?, ?, ?)",
            (sid, number, json.dumps(body, ensure_ascii=False)))
        self._conn.execute(
            "DELETE FROM study_attempts WHERE session_id = ? AND number <= ?",
            (sid, number - keep))

    def attempts(self, sid: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT body FROM study_attempts WHERE session_id = ? ORDER BY number", (sid,)).fetchall()
        return [json.loads(body) for (body,) in rows]
