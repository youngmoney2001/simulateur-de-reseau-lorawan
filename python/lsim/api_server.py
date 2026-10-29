"""Serveur HTTP de l'API v1 (contrat : `docs/API_CONTRACT.md`, formes : `lsim.api_contract`).

Bibliothèque standard uniquement (plus `cryptography` pour émettre un certificat de test hors de ce
module). Un calcul à la fois (file bornée) dans un fil dédié ; les requêtes HTTP sont traitées en
parallèle. Les runs sont stockés dans une base SQLite (WAL) : ils survivent au redémarrage ; un run
interrompu par un arrêt est marqué `failed`.

Totaux, compteurs par dispositif, charges et événements viennent d'un seul calcul par run
(`build_trace` en mono-passerelle, `build_multi_trace` en multi-passerelles) : ils concordent par
construction, et le serveur vérifie la somme des compteurs par dispositif avant de publier.

Périmètre : mono et multi-passerelles, environnement à obstacles (sans relief). Refusés
explicitement (`validation_error`) : mesh, join en multi-passerelles, énergie avec options
protocole ou multi-passerelles. Relief (`terrain`) : `terrain_not_allowed` (catalogue à venir).

Jetons : `python -m lsim.api_server issue-token --tokens FICHIER --owner NOM` affiche le jeton une
seule fois ; le fichier ne contient que son SHA-256. `serve` refuse de démarrer sur une adresse
non locale sans `--tls-cert` et `--tls-key` (le jeton circule dans l'en-tête).
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import logging
import math
import os
import queue
import re
import secrets
import ssl
import sqlite3
import sys
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, urlsplit

from pydantic import ValidationError

from lsim.api_contract import (
    API_VERSION, MAX_BODY_BYTES, MAX_PAGE_SIZE, MAX_TRACE_EVENTS_PER_RUN, DevicePage, DeviceRowOut,
    GatewayLoadOut, GatewayReportOut, Problem, RunCreate, RunStatus, RunSummary, Totals, TracePage,
    TraceEvent, ValidateRequest, ValidateResponse, list_regions,
)
from lsim.export import run_scenario
from lsim.scenario import Scenario, _build_environment
from lsim.trace_events import ProtocolOptions, build_multi_trace, build_trace

log = logging.getLogger("lsim.api")

MAX_RUNS_PER_OWNER = 20
MAX_RUNS_TOTAL = 200
MAX_QUEUE = 16
MAX_ACTIVE_PER_OWNER = 4
DEFAULT_PAGE = 100
DEFAULT_RATE_PER_MIN = 120      # requêtes authentifiées soutenues, par jeton
DEFAULT_RATE_BURST = 60         # rafale tolérée
_RUN_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_TERMINAL = ("done", "failed", "cancelled")
_LOOPBACK = ("127.0.0.1", "::1", "localhost")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, field: Optional[str] = None,
                 headers: Optional[dict[str, str]] = None) -> None:
        super().__init__(message)
        self.status, self.code, self.message, self.field = status, code, message, field
        self.headers = headers or {}


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _problem(code: str, message: str, field_name: Optional[str] = None) -> dict[str, Any]:
    return Problem(code=code, message=message, field=field_name).model_dump(exclude_none=True)


def _validation_error(exc: ValidationError) -> ApiError:
    err = exc.errors()[0]
    loc = ".".join(str(p) for p in err.get("loc", ()))
    msg = str(err.get("msg", "invalide"))
    code = "terrain_not_allowed" if "terrain" in msg.lower() else "validation_error"
    return ApiError(422, code, f"{loc} : {msg}" if loc else msg, loc or None)


# --- Jetons ------------------------------------------------------------------------------------

class TokenStore:
    """Jetons d'accès : seul le SHA-256 est stocké. Rechargé quand le fichier change."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._mtime: Optional[int] = None
        self._entries: list[dict[str, Any]] = []

    def _load_locked(self) -> None:
        try:
            st = self.path.stat()
        except FileNotFoundError:
            self._entries, self._mtime = [], None
            return
        if st.st_mtime_ns == self._mtime:
            return
        data = json.loads(self.path.read_text(encoding="utf-8"))
        entries = data.get("tokens")
        if not isinstance(entries, list):
            raise ValueError("fichier de jetons invalide")
        self._entries = entries
        self._mtime = st.st_mtime_ns

    def issue(self, owner: str, expires_at: Optional[int] = None) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", owner):
            raise ValueError("nom de propriétaire invalide")
        token = secrets.token_urlsafe(32)                     # 256 bits
        with self._lock:
            self._load_locked()
            entries = list(self._entries) + [{
                "owner": owner, "sha256": _sha256(token),
                "expires_at": expires_at, "revoked": False,
            }]
            self._write(entries)
        return token

    def revoke(self, owner: str) -> int:
        with self._lock:
            self._load_locked()
            count = 0
            entries = []
            for e in self._entries:
                if e.get("owner") == owner and not e.get("revoked"):
                    e = {**e, "revoked": True}
                    count += 1
                entries.append(e)
            self._write(entries)
            return count

    def _write(self, entries: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"tokens": entries}, fh)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.path)
        self._entries = entries
        self._mtime = self.path.stat().st_mtime_ns

    def resolve(self, bearer: str, now: Optional[int] = None) -> Optional[str]:
        now = int(time.time()) if now is None else now
        digest = _sha256(bearer)
        with self._lock:
            self._load_locked()
            owner: Optional[str] = None
            for e in self._entries:
                match = hmac.compare_digest(str(e.get("sha256", "")), digest)
                expired = e.get("expires_at") is not None and now >= int(e["expires_at"])
                if match and not e.get("revoked") and not expired:
                    owner = str(e["owner"])
            return owner


# --- Limite de débit ---------------------------------------------------------------------------

class RateLimiter:
    """Seau à jetons par propriétaire : `burst` requêtes d'un coup, puis `per_minute` par minute."""

    def __init__(self, per_minute: int = DEFAULT_RATE_PER_MIN, burst: int = DEFAULT_RATE_BURST,
                 clock=time.monotonic) -> None:
        if per_minute <= 0 or burst <= 0:
            raise ValueError("débit et rafale strictement positifs")
        self._rate = per_minute / 60.0
        self._burst = float(burst)
        self._clock = clock
        self._lock = threading.Lock()
        self._state: dict[str, tuple[float, float]] = {}

    def take(self, owner: str) -> Optional[float]:
        """None si la requête passe ; sinon, secondes avant la prochaine requête possible."""
        with self._lock:
            now = self._clock()
            tokens, last = self._state.get(owner, (self._burst, now))
            tokens = min(self._burst, tokens + (now - last) * self._rate)
            if tokens >= 1.0:
                self._state[owner] = (tokens - 1.0, now)
                return None
            self._state[owner] = (tokens, now)
            return (1.0 - tokens) / self._rate


# --- Stockage des runs (SQLite) ----------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    state TEXT NOT NULL,
    progress REAL NOT NULL,
    scenario_sha256 TEXT,
    seed INTEGER NOT NULL,
    trace_events INTEGER,
    problem TEXT,
    summary TEXT,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS runs_owner ON runs(owner);
CREATE TABLE IF NOT EXISTS devices (
    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    idx INTEGER NOT NULL,
    body TEXT NOT NULL,
    PRIMARY KEY (run_id, idx)
);
CREATE TABLE IF NOT EXISTS events (
    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    body TEXT NOT NULL,
    PRIMARY KEY (run_id, seq)
);
"""


class RunStore:
    """Persistance des runs. Non thread-safe : appelé uniquement sous le verrou de `RunService`."""

    def __init__(self, path: str) -> None:
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.execute("PRAGMA foreign_keys = ON")
        if path != ":memory:":
            self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.execute("PRAGMA synchronous = FULL")
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        self._conn.close()

    def _tx(self):
        conn = self._conn

        class _Tx:
            def __enter__(self):
                conn.execute("BEGIN IMMEDIATE")

            def __exit__(self, exc_type, *_):
                conn.execute("ROLLBACK" if exc_type else "COMMIT")
                return False
        return _Tx()

    @staticmethod
    def _row(r: tuple) -> dict[str, Any]:
        keys = ("run_id", "owner", "state", "progress", "scenario_sha256", "seed",
                "trace_events", "problem", "summary", "created_at")
        out = dict(zip(keys, r))
        out["problem"] = json.loads(out["problem"]) if out["problem"] else None
        out["summary"] = json.loads(out["summary"]) if out["summary"] else None
        return out

    _COLS = ("run_id, owner, state, progress, scenario_sha256, seed, trace_events, problem, "
             "summary, created_at")

    def insert_run(self, run_id: str, owner: str, seed: int, sha: str, created_at: int) -> None:
        self._conn.execute(
            "INSERT INTO runs (run_id, owner, state, progress, scenario_sha256, seed, created_at)"
            " VALUES (?, ?, 'queued', 0.0, ?, ?, ?)", (run_id, owner, sha, seed, created_at))

    def get_run(self, run_id: str) -> Optional[dict[str, Any]]:
        r = self._conn.execute(f"SELECT {self._COLS} FROM runs WHERE run_id = ?",
                               (run_id,)).fetchone()
        return self._row(r) if r else None

    def owner_runs(self, owner: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            f"SELECT {self._COLS} FROM runs WHERE owner = ? ORDER BY rowid", (owner,)).fetchall()
        return [self._row(r) for r in rows]

    def all_runs(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(f"SELECT {self._COLS} FROM runs ORDER BY rowid").fetchall()
        return [self._row(r) for r in rows]

    def set_state(self, run_id: str, state: str, progress: Optional[float] = None,
                  problem: Optional[dict[str, Any]] = None) -> None:
        self._conn.execute(
            "UPDATE runs SET state = ?, progress = COALESCE(?, progress), problem = ? "
            "WHERE run_id = ?",
            (state, progress, json.dumps(problem) if problem else None, run_id))

    def delete_run(self, run_id: str) -> None:
        self._conn.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))

    def save_done(self, run_id: str, summary: dict[str, Any], devices: list[dict[str, Any]],
                  events: list[dict[str, Any]]) -> None:
        with self._tx():
            self._conn.executemany(
                "INSERT INTO devices (run_id, idx, body) VALUES (?, ?, ?)",
                [(run_id, d["device_index"], json.dumps(d, ensure_ascii=False)) for d in devices])
            self._conn.executemany(
                "INSERT INTO events (run_id, seq, body) VALUES (?, ?, ?)",
                [(run_id, e["seq"], json.dumps(e, ensure_ascii=False, allow_nan=False))
                 for e in events])
            self._conn.execute(
                "UPDATE runs SET state = 'done', progress = 1.0, summary = ?, trace_events = ? "
                "WHERE run_id = ?",
                (json.dumps(summary, ensure_ascii=False), len(events), run_id))

    def devices_page(self, run_id: str, cursor: int, limit: int) -> tuple[list, Optional[int]]:
        rows = self._conn.execute(
            "SELECT idx, body FROM devices WHERE run_id = ? AND idx >= ? ORDER BY idx LIMIT ?",
            (run_id, cursor, limit + 1)).fetchall()
        nxt = rows[limit][0] if len(rows) > limit else None
        return [json.loads(b) for _, b in rows[:limit]], nxt

    def events_page(self, run_id: str, cursor: int, limit: int) -> tuple[list, Optional[int]]:
        rows = self._conn.execute(
            "SELECT seq, body FROM events WHERE run_id = ? AND seq >= ? ORDER BY seq LIMIT ?",
            (run_id, cursor, limit + 1)).fetchall()
        nxt = rows[limit][0] if len(rows) > limit else None
        return [json.loads(b) for _, b in rows[:limit]], nxt


# --- Runs --------------------------------------------------------------------------------------

@dataclass
class _Job:
    scenario: Scenario
    options: ProtocolOptions
    energy_profile: Optional[str]
    multi: bool


def _check_request(req: RunCreate) -> None:
    model = req.scenario
    if model.mesh is not None:
        raise ApiError(422, "validation_error",
                       "mesh : non exposé par l'API v1 (voir docs/API_CONTRACT.md)")
    multi = model.gateways is not None
    protocol = req.protocol
    protocol_active = protocol.join or protocol.confirmed_uplinks or protocol.downlink_every > 0
    if multi and protocol.join:
        raise ApiError(422, "validation_error",
                       "protocole.join : non modélisé en multi-passerelles", "protocol.join")
    if req.energy_profile is not None and (multi or protocol_active):
        raise ApiError(422, "validation_error",
                       "energy_profile : seulement en mono-passerelle, sans options protocole",
                       "energy_profile")


def _build_scenario(model: Any) -> Scenario:
    env = None
    if model.environment is not None:
        env = _build_environment(model.environment, Path("."), model.propagation.frequency_hz)
    return Scenario(model, environment=env)


def _summary_out(run_id: str, scenario: Scenario, totals, gateway_load, gateways,
                 energy_profile: Optional[str]) -> dict[str, Any]:
    body = dict(
        run_id=run_id, scenario_sha256=scenario.sha256, seed=scenario.model.seed,
        totals=Totals(sent=totals.sent, received=totals.received,
                      lost_sensitivity=totals.lost_sensitivity,
                      lost_collision=totals.lost_collision, airtime_ns=totals.airtime_ns,
                      lost_gateway_busy=totals.lost_gateway_busy).model_dump(),
        pdr=(totals.received / totals.sent) if totals.sent else None,
        energy_profile=energy_profile,
    )
    if gateways is None:
        body["gateway"] = GatewayLoadOut(
            busy_ns=gateway_load.busy_ns, peak_concurrent=gateway_load.peak_concurrent,
            observation_ns=gateway_load.observation_ns,
            utilization=gateway_load.utilization).model_dump()
    else:
        body["gateways"] = gateways
    return RunSummary(**body).model_dump(exclude_none=True)


class RunService:
    """Files de calcul et état des runs. Un seul calcul à la fois ; état sous un verrou unique."""

    def __init__(self, store: RunStore, max_queue: int = MAX_QUEUE,
                 limiter: Optional[RateLimiter] = None) -> None:
        self._lock = threading.RLock()
        self._store = store
        self.limiter = limiter or RateLimiter()
        self._queue: "queue.Queue[str]" = queue.Queue(maxsize=max_queue)
        self._pending: dict[str, _Job] = {}
        self._cancelled: set[str] = set()
        self._stopping = threading.Event()
        with self._lock:
            for r in self._store.all_runs():
                if r["state"] in ("queued", "running"):
                    self._store.set_state(r["run_id"], "failed",
                                          problem=_problem("run_failed",
                                                           "interrompu au redémarrage"))
        self._worker = threading.Thread(target=self._loop, name="lsim-run-worker", daemon=True)
        self._worker.start()

    def close(self) -> None:
        self._stopping.set()
        self._worker.join(timeout=10)

    # Création ---------------------------------------------------------------------------------

    def create(self, owner: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            req = RunCreate.model_validate(body)
        except ValidationError as exc:
            raise _validation_error(exc) from None
        _check_request(req)
        try:
            scenario = _build_scenario(req.scenario)
        except ValueError as exc:
            raise ApiError(422, "validation_error", str(exc)) from None
        job = _Job(scenario=scenario, options=ProtocolOptions(**req.protocol.model_dump()),
                   energy_profile=req.energy_profile, multi=req.scenario.gateways is not None)
        with self._lock:
            owned = self._store.owner_runs(owner)
            if sum(1 for r in owned if r["state"] not in _TERMINAL) >= MAX_ACTIVE_PER_OWNER:
                raise ApiError(422, "limit_exceeded", "trop de runs en cours pour ce jeton")
            if self._queue.full():
                raise ApiError(422, "limit_exceeded", "file de calcul pleine")
            if len(owned) >= MAX_RUNS_PER_OWNER and not self._evict(owned, MAX_RUNS_PER_OWNER):
                raise ApiError(422, "limit_exceeded", "trop de runs pour ce jeton")
            everything = self._store.all_runs()
            if len(everything) >= MAX_RUNS_TOTAL and not self._evict(everything, MAX_RUNS_TOTAL):
                raise ApiError(422, "limit_exceeded", "capacité de runs atteinte")
            run_id = secrets.token_urlsafe(16)
            self._store.insert_run(run_id, owner, scenario.model.seed, scenario.sha256,
                                   int(time.time()))
            self._pending[run_id] = job
            self._queue.put_nowait(run_id)
            return self._status(self._store.get_run(run_id))

    def _evict(self, runs: list[dict[str, Any]], limit: int) -> bool:
        """Supprime les runs terminés les plus anciens pour passer sous `limit`. False si impossible."""
        excess = len(runs) - limit + 1
        terminal = [r for r in runs if r["state"] in _TERMINAL]
        if len(terminal) < excess:
            return False
        for r in terminal[:excess]:
            self._store.delete_run(r["run_id"])
        return True

    # Lecture et suppression ------------------------------------------------------------------

    def _owned(self, owner: str, run_id: str) -> dict[str, Any]:
        if not _RUN_ID.match(run_id):
            raise ApiError(404, "not_found", "run inconnu")
        row = self._store.get_run(run_id)
        if row is None or row["owner"] != owner:
            raise ApiError(404, "not_found", "run inconnu")
        return row

    @staticmethod
    def _status(row: dict[str, Any]) -> dict[str, Any]:
        return RunStatus(
            run_id=row["run_id"], state=row["state"], progress=row["progress"],
            scenario_sha256=row["scenario_sha256"], trace_events=row["trace_events"],
            problem=Problem(**row["problem"]) if row["problem"] else None,
        ).model_dump(exclude_none=True)

    def status(self, owner: str, run_id: str) -> dict[str, Any]:
        with self._lock:
            return self._status(self._owned(owner, run_id))

    def cancel_or_delete(self, owner: str, run_id: str) -> None:
        with self._lock:
            row = self._owned(owner, run_id)
            if row["state"] in _TERMINAL:
                self._store.delete_run(run_id)
            elif row["state"] == "queued":
                self._cancelled.add(run_id)
                self._pending.pop(run_id, None)
                self._store.set_state(run_id, "cancelled")
            else:
                self._cancelled.add(run_id)

    def _done(self, owner: str, run_id: str) -> dict[str, Any]:
        row = self._owned(owner, run_id)
        if row["state"] != "done":
            raise ApiError(409, "conflict", "run non terminé avec succès")
        return row

    def summary(self, owner: str, run_id: str) -> dict[str, Any]:
        with self._lock:
            return dict(self._done(owner, run_id)["summary"])

    def devices_page(self, owner: str, run_id: str, cursor: int, limit: int) -> dict[str, Any]:
        with self._lock:
            self._done(owner, run_id)
            items, nxt = self._store.devices_page(run_id, cursor, limit)
        return DevicePage(items=items, next_cursor=nxt).model_dump()

    def events_page(self, owner: str, run_id: str, cursor: int, limit: int) -> dict[str, Any]:
        with self._lock:
            self._done(owner, run_id)
            items, nxt = self._store.events_page(run_id, cursor, limit)
        return TracePage(items=items, next_cursor=nxt).model_dump()

    # Calcul -----------------------------------------------------------------------------------

    def _loop(self) -> None:
        while not self._stopping.is_set():
            try:
                run_id = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            with self._lock:
                job = self._pending.pop(run_id, None)
                if job is None or run_id in self._cancelled:
                    self._cancelled.discard(run_id)
                    self._store.set_state(run_id, "cancelled")
                    continue
                self._store.set_state(run_id, "running", progress=0.0)
            try:
                payload = self._compute(run_id, job)
            except ApiError as exc:
                self._fail(run_id, exc.code, exc.message)
            except ValueError as exc:
                msg = str(exc)
                if "trace limitée" in msg or "trop d'événements" in msg:
                    self._fail(run_id, "limit_exceeded", msg)
                else:
                    log.error("run %s : valeur refusée", run_id, exc_info=True)
                    self._fail(run_id, "run_failed", "échec du calcul")
            except Exception:
                log.error("run %s : échec", run_id, exc_info=True)
                self._fail(run_id, "run_failed", "échec du calcul")
            else:
                with self._lock:
                    if run_id in self._cancelled:
                        self._cancelled.discard(run_id)
                        self._store.set_state(run_id, "cancelled")
                    else:
                        self._store.save_done(run_id, payload["summary"], payload["devices"],
                                              payload["events"])

    def _fail(self, run_id: str, code: str, message: str) -> None:
        with self._lock:
            self._cancelled.discard(run_id)
            self._store.set_state(run_id, "failed", problem=_problem(code, message))

    def _compute(self, run_id: str, job: _Job) -> dict[str, Any]:
        scenario = job.scenario
        devices, group_of, index_in_group = scenario.deploy()
        energy_rows: dict[int, Any] = {}
        if job.multi:
            mt = build_multi_trace(scenario, job.options)
            totals, per_device, events = mt.totals, mt.per_device, mt.events
            gateway_load, gateways = None, [
                GatewayReportOut(name=name, received=g.received, lost_sensitivity=g.lost_sensitivity,
                                 lost_collision=g.lost_collision,
                                 lost_gateway_busy=g.lost_gateway_busy,
                                 audible_frames=g.audible_frames, busy_ns=g.busy_ns,
                                 peak_concurrent=g.peak_concurrent,
                                 observation_ns=g.observation_ns).model_dump()
                for name, g in zip(mt.gateway_names, mt.per_gateway)]
        else:
            tr = build_trace(scenario, job.options)
            totals, per_device, events = tr.totals, tr.per_device, tr.events
            gateway_load, gateways = tr.gateway, None
        self._set(run_id, 0.7)
        if job.energy_profile is not None:
            res = run_scenario(scenario, energy_profile=job.energy_profile)
            energy_rows = {r.device_index: r for r in res.rows}
        if len(events) > MAX_TRACE_EVENTS_PER_RUN:
            raise ApiError(422, "limit_exceeded", "événements au-delà de la borne du run")

        rows = []
        for i, (dev, c) in enumerate(zip(devices, per_device)):
            e = energy_rows.get(i)
            rows.append(DeviceRowOut(
                device_index=i, group=group_of[i], index_in_group=index_in_group[i],
                x_m=dev.x_m, y_m=dev.y_m, spreading_factor=dev.spreading_factor,
                sent=c.sent, received=c.received, lost_sensitivity=c.lost_sensitivity,
                lost_collision=c.lost_collision, airtime_ns=c.airtime_ns,
                energy_per_message_j=getattr(e, "energy_per_message_j", None),
                average_current_ua=getattr(e, "average_current_ua", None),
            ).model_dump(exclude_none=True))
        # Invariant : la somme des compteurs par dispositif égale les totaux publiés.
        if (sum(r["sent"] for r in rows) != totals.sent
                or sum(r["received"] for r in rows) != totals.received):
            raise RuntimeError("compteurs par dispositif et totaux ne concordent pas")
        events_out = []
        for ev in events:
            events_out.append(TraceEvent(
                seq=ev.seq, t_ns=ev.t_ns, kind=ev.kind, device_index=ev.device_index,
                gateway_index=ev.gateway_index, outcome=ev.outcome,
                hops=[{"from_id": h.from_id, "to_id": h.to_id, "t_ns": h.t_ns,
                       "freq_hz": h.freq_hz, "dr": h.dr, "rssi_dbm": h.rssi_dbm,
                       "outcome": h.outcome} for h in ev.hops],
            ).model_dump(exclude_none=True))
        summary = _summary_out(run_id, scenario, totals, gateway_load, gateways,
                               job.energy_profile)
        self._set(run_id, 0.95)
        return {"summary": summary, "devices": rows, "events": events_out}

    def _set(self, run_id: str, progress: float) -> None:
        with self._lock:
            self._store.set_state(run_id, "running", progress=progress)


def _page_params(query: dict[str, list[str]]) -> tuple[int, int]:
    def one(name: str, default: int, lo: int, hi: int) -> int:
        raw = query.get(name, [str(default)])[0]
        if not re.fullmatch(r"\d{1,9}", raw):
            raise ApiError(422, "validation_error", f"{name} : entier attendu", name)
        value = int(raw)
        if not lo <= value <= hi:
            raise ApiError(422, "validation_error", f"{name} : hors bornes", name)
        return value
    return one("cursor", 0, 0, 10**9), one("limit", DEFAULT_PAGE, 1, MAX_PAGE_SIZE)


def _refuse_constant(name: str) -> None:
    raise ValueError(f"constante JSON refusée : {name}")


# --- HTTP --------------------------------------------------------------------------------------

class ApiServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], tokens: TokenStore, service: RunService,
                 tls_context: Optional[ssl.SSLContext] = None) -> None:
        super().__init__(address, _Handler)
        self.tokens = tokens
        self.service = service
        self._tls = tls_context

    def get_request(self):
        sock, addr = super().get_request()
        if self._tls is not None:
            # Poignée de main dans le fil de la requête (`_Handler.setup`), pas dans la boucle d'accept.
            sock = self._tls.wrap_socket(sock, server_side=True, do_handshake_on_connect=False)
        return sock, addr

    def handle_error(self, request, client_address) -> None:  # pas de trace vers le client
        log.debug("connexion refusée ou interrompue", exc_info=True)


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "lsim-api"
    sys_version = ""
    timeout = 30  # délai par opération : limite les connexions bloquées

    def setup(self) -> None:
        super().setup()
        if isinstance(self.request, ssl.SSLSocket):
            self.request.do_handshake()

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - signature imposée
        return  # pas de journal d'accès : les en-têtes contiennent des jetons

    def do_GET(self) -> None:
        self._handle("GET")

    def do_POST(self) -> None:
        self._handle("POST")

    def do_DELETE(self) -> None:
        self._handle("DELETE")

    def do_PUT(self) -> None:
        self._send(405, _problem("validation_error", "méthode non autorisée"))

    def do_PATCH(self) -> None:
        self._send(405, _problem("validation_error", "méthode non autorisée"))

    def _handle(self, method: str) -> None:
        headers: dict[str, str] = {}
        try:
            status, body = self._route(method)
        except ApiError as exc:
            status, body = exc.status, _problem(exc.code, exc.message, exc.field)
            headers = exc.headers
        except Exception:
            log.error("erreur interne", exc_info=True)
            status, body = 500, _problem("run_failed", "erreur interne")
        self._send(status, body, headers)

    def _send(self, status: int, body: Optional[dict[str, Any]],
              headers: Optional[dict[str, str]] = None) -> None:
        data = b"" if body is None else json.dumps(body, ensure_ascii=False,
                                                    allow_nan=False).encode("utf-8")
        if status >= 400:
            # Corps éventuellement non lu (erreur avant lecture) : pas de réutilisation du socket.
            self.close_connection = True
        self.send_response(status)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        if body is not None:
            self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        if data:
            self.wfile.write(data)

    def _owner(self) -> str:
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer ") or len(auth) > 200:
            raise ApiError(401, "unauthorized", "jeton absent ou invalide")
        owner = self.server.tokens.resolve(auth[len("Bearer "):].strip())  # type: ignore[attr-defined]
        if owner is None:
            raise ApiError(401, "unauthorized", "jeton absent ou invalide")
        return owner

    def _json_body(self) -> dict[str, Any]:
        length_raw = self.headers.get("Content-Length")
        if length_raw is None or not length_raw.isdigit():
            raise ApiError(422, "validation_error", "Content-Length requis")
        length = int(length_raw)
        if length > MAX_BODY_BYTES:
            raise ApiError(413, "limit_exceeded", "corps trop grand")
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw.decode("utf-8"), parse_constant=_refuse_constant)
        except (ValueError, UnicodeDecodeError):
            raise ApiError(422, "validation_error", "JSON invalide") from None
        if not isinstance(body, dict):
            raise ApiError(422, "validation_error", "objet JSON attendu")
        return body

    def _route(self, method: str) -> tuple[int, Optional[dict[str, Any]]]:
        parts = urlsplit(self.path)
        path = parts.path
        query = parse_qs(parts.query, keep_blank_values=True)
        base = f"/api/{API_VERSION}"
        if method == "GET" and path == f"{base}/health":
            return 200, {"status": "ok", "api_version": API_VERSION}

        if not path.startswith(base + "/"):
            raise ApiError(404, "not_found", "route inconnue")
        rest = path[len(base) + 1:]
        owner = self._owner()
        svc: RunService = self.server.service  # type: ignore[attr-defined]
        retry = svc.limiter.take(owner)
        if retry is not None:
            raise ApiError(429, "rate_limited", "trop de requêtes",
                           headers={"Retry-After": str(max(1, math.ceil(retry)))})

        if method == "GET" and rest == "regions":
            return 200, list_regions().model_dump()
        if method == "POST" and rest == "scenarios/validate":
            return 200, self._validate()
        if method == "POST" and rest == "runs":
            return 202, svc.create(owner, self._json_body())

        m = re.fullmatch(r"runs/([^/]+)(?:/(summary|devices|events))?", rest)
        if m is None:
            raise ApiError(404, "not_found", "route inconnue")
        run_id, action = m.group(1), m.group(2)
        if method == "GET" and action is None:
            return 200, svc.status(owner, run_id)
        if method == "DELETE" and action is None:
            svc.cancel_or_delete(owner, run_id)
            return 204, None
        if method == "GET" and action == "summary":
            return 200, svc.summary(owner, run_id)
        if method == "GET" and action in ("devices", "events"):
            cursor, limit = _page_params(query)
            if action == "devices":
                return 200, svc.devices_page(owner, run_id, cursor, limit)
            return 200, svc.events_page(owner, run_id, cursor, limit)
        raise ApiError(404, "not_found", "route inconnue")

    def _validate(self) -> dict[str, Any]:
        try:
            req = ValidateRequest.model_validate(self._json_body())
        except ValidationError as exc:
            err = _validation_error(exc)
            return ValidateResponse(valid=False, problems=[
                Problem(code=err.code, message=err.message, field=err.field),
            ]).model_dump(exclude_none=True)
        try:
            _check_request(RunCreate(scenario=req.scenario))
            scenario = _build_scenario(req.scenario)
        except (ApiError, ValueError) as exc:
            code = exc.code if isinstance(exc, ApiError) else "validation_error"
            msg = exc.message if isinstance(exc, ApiError) else str(exc)
            return ValidateResponse(valid=False, problems=[
                Problem(code=code, message=msg)]).model_dump(exclude_none=True)
        return ValidateResponse(valid=True, scenario_sha256=scenario.sha256).model_dump(
            exclude_none=True)


def make_tls_context(cert: Path, key: Path) -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(certfile=str(cert), keyfile=str(key))
    return ctx


def make_server(host: str, port: int, tokens_path: Path, *, runs_db: str = ":memory:",
                max_queue: int = MAX_QUEUE, rate_per_min: int = DEFAULT_RATE_PER_MIN,
                tls: Optional[ssl.SSLContext] = None) -> ApiServer:
    service = RunService(RunStore(runs_db), max_queue=max_queue,
                         limiter=RateLimiter(per_minute=rate_per_min))
    return ApiServer((host, port), TokenStore(tokens_path), service, tls_context=tls)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m lsim.api_server")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_issue = sub.add_parser("issue-token", help="émet un jeton (affiché une seule fois)")
    p_issue.add_argument("--tokens", required=True, type=Path)
    p_issue.add_argument("--owner", required=True)
    p_issue.add_argument("--expires-at", type=int, default=None, help="epoch (secondes), optionnel")
    p_revoke = sub.add_parser("revoke", help="révoque tous les jetons d'un propriétaire")
    p_revoke.add_argument("--tokens", required=True, type=Path)
    p_revoke.add_argument("--owner", required=True)
    p_serve = sub.add_parser("serve", help="démarre le serveur")
    p_serve.add_argument("--tokens", required=True, type=Path)
    p_serve.add_argument("--runs-db", required=True, help="fichier SQLite des runs")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8765)
    p_serve.add_argument("--tls-cert", type=Path, default=None)
    p_serve.add_argument("--tls-key", type=Path, default=None)
    p_serve.add_argument("--rate-per-minute", type=int, default=DEFAULT_RATE_PER_MIN)
    args = parser.parse_args(argv)

    if args.cmd == "issue-token":
        print(TokenStore(args.tokens).issue(args.owner, args.expires_at))
        return 0
    if args.cmd == "revoke":
        print(f"{TokenStore(args.tokens).revoke(args.owner)} jeton(s) révoqué(s)")
        return 0

    if (args.tls_cert is None) != (args.tls_key is None):
        parser.error("--tls-cert et --tls-key vont ensemble")
    if args.host not in _LOOPBACK and args.tls_cert is None:
        parser.error("adresse non locale sans TLS : fournir --tls-cert et --tls-key")
    tls = make_tls_context(args.tls_cert, args.tls_key) if args.tls_cert else None
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(message)s")
    server = make_server(args.host, args.port, args.tokens, runs_db=args.runs_db,
                         rate_per_min=args.rate_per_minute, tls=tls)
    scheme = "https" if tls else "http"
    log.info("API %s sur %s://%s:%d", API_VERSION, scheme, args.host, args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        server.service.close()
        server.service._store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
