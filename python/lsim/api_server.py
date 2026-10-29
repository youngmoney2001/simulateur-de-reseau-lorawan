"""Serveur HTTP de l'API v1 (contrat : `docs/API_CONTRACT.md`, formes : `lsim.api_contract`).

Bibliothèque standard uniquement. Un calcul à la fois (file bornée) dans un fil dédié ; les
requêtes HTTP sont traitées en parallèle. Les runs vivent en mémoire de ce processus : ils
disparaissent au redémarrage (limite v1, documentée).

Périmètre v1 (refus explicite, code `validation_error`) : scénarios multi-passerelles, mesh,
environnement (relief, obstacles). `build_trace` ne lit que la première passerelle : servir ces
scénarios donnerait une trace fausse sans erreur visible.

Jetons : `python -m lsim.api_server issue-token --tokens FICHIER --owner NOM` affiche le jeton une
seule fois ; le fichier ne contient que son SHA-256. Le serveur écoute sur 127.0.0.1 par défaut :
hors machine de confiance, il faut un relais HTTPS (le jeton circule dans l'en-tête).
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import hmac
import json
import logging
import os
import queue
import re
import secrets
import sys
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, urlsplit

from pydantic import ValidationError

from lsim.api_contract import (
    API_VERSION, MAX_BODY_BYTES, MAX_PAGE_SIZE, MAX_TRACE_EVENTS_PER_RUN, DevicePage, DeviceRowOut,
    GatewayLoadOut, Problem, RunCreate, RunStatus, RunSummary, Totals, TracePage, TraceEvent,
    ValidateRequest, ValidateResponse, list_regions,
)
from lsim.export import RunResult, run_scenario
from lsim.scenario import Scenario
from lsim.trace_events import ProtocolOptions, TraceRun, build_trace

log = logging.getLogger("lsim.api")

MAX_RUNS_PER_OWNER = 20
MAX_RUNS_TOTAL = 200
MAX_QUEUE = 16
MAX_ACTIVE_PER_OWNER = 4
DEFAULT_PAGE = 100
_RUN_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_TERMINAL = ("done", "failed", "cancelled")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, field: Optional[str] = None) -> None:
        super().__init__(message)
        self.status, self.code, self.message, self.field = status, code, message, field


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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


# --- Runs --------------------------------------------------------------------------------------

@dataclass
class Run:
    run_id: str
    owner: str
    state: str = "queued"
    progress: float = 0.0
    scenario_sha256: Optional[str] = None
    seed: int = 0
    trace_events: Optional[int] = None
    problem: Optional[dict[str, Any]] = None
    cancel: bool = False
    summary: Optional[dict[str, Any]] = None
    devices: list[dict[str, Any]] = field(default_factory=list)
    event_seqs: list[int] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    scenario: Optional[Scenario] = None
    options: Optional[ProtocolOptions] = None
    energy_profile: Optional[str] = None


def _problem(code: str, message: str, field_name: Optional[str] = None) -> dict[str, Any]:
    return Problem(code=code, message=message, field=field_name).model_dump(exclude_none=True)


def _check_scenario_supported(model: Any) -> None:
    if model.gateways is not None or model.mesh is not None:
        raise ApiError(422, "validation_error",
                       "multi-passerelles et mesh : non exposés par l'API v1 (voir docs/USAGE.md)")
    if model.environment is not None:
        raise ApiError(422, "validation_error",
                       "environnement (relief, obstacles) : non exposé par l'API v1")


def _totals_out(c: Any) -> Totals:
    return Totals(sent=c.sent, received=c.received, lost_sensitivity=c.lost_sensitivity,
                  lost_collision=c.lost_collision, airtime_ns=c.airtime_ns,
                  lost_gateway_busy=c.lost_gateway_busy)


def _summary_dict(run_id: str, result: RunResult) -> dict[str, Any]:
    if result.gateway is None:
        raise RuntimeError("charge passerelle absente en mono-passerelle")
    g = result.gateway
    return RunSummary(
        run_id=run_id, scenario_sha256=result.scenario_sha256, seed=result.seed,
        totals=_totals_out(result.totals), pdr=result.pdr,
        gateway=GatewayLoadOut(busy_ns=g.busy_ns, peak_concurrent=g.peak_concurrent,
                               observation_ns=g.observation_ns, utilization=g.utilization),
        energy_profile=result.energy_profile,
    ).model_dump(exclude_none=True)


def _devices_list(result: RunResult) -> list[dict[str, Any]]:
    out = []
    for r in result.rows:
        out.append(DeviceRowOut(
            device_index=r.device_index, group=r.group, index_in_group=r.index_in_group,
            x_m=r.x_m, y_m=r.y_m, spreading_factor=r.spreading_factor, sent=r.sent,
            received=r.received, lost_sensitivity=r.lost_sensitivity,
            lost_collision=r.lost_collision, airtime_ns=r.airtime_ns,
            energy_per_message_j=r.energy_per_message_j,
            average_current_ua=r.average_current_ua,
        ).model_dump(exclude_none=True))
    return out


def _events_list(trace: TraceRun) -> list[dict[str, Any]]:
    out = []
    for ev in trace.events:
        out.append(TraceEvent(
            seq=ev.seq, t_ns=ev.t_ns, kind=ev.kind, device_index=ev.device_index,
            gateway_index=ev.gateway_index, outcome=ev.outcome,
            hops=[{"from_id": h.from_id, "to_id": h.to_id, "t_ns": h.t_ns, "freq_hz": h.freq_hz,
                   "dr": h.dr, "rssi_dbm": h.rssi_dbm, "outcome": h.outcome}
                  for h in ev.hops],
        ).model_dump(exclude_none=True))
    return out


class RunService:
    """Files de calcul et état des runs. Un seul calcul à la fois."""

    def __init__(self, max_queue: int = MAX_QUEUE) -> None:
        self._lock = threading.Lock()
        self._runs: dict[str, Run] = {}
        self._queue: "queue.Queue[str]" = queue.Queue(maxsize=max_queue)
        self._stopping = threading.Event()
        self._worker = threading.Thread(target=self._loop, name="lsim-run-worker", daemon=True)
        self._worker.start()

    def close(self) -> None:
        self._stopping.set()
        self._worker.join(timeout=5)

    def create(self, owner: str, body: dict[str, Any]) -> Run:
        try:
            req = RunCreate.model_validate(body)
        except ValidationError as exc:
            raise _validation_error(exc) from None
        _check_scenario_supported(req.scenario)
        try:
            scenario = Scenario(req.scenario)
        except ValueError as exc:
            raise ApiError(422, "validation_error", str(exc)) from None
        with self._lock:
            owned = [r for r in self._runs.values() if r.owner == owner]
            active = [r for r in owned if r.state not in _TERMINAL]
            if len(active) >= MAX_ACTIVE_PER_OWNER:
                raise ApiError(422, "limit_exceeded", "trop de runs en cours pour ce jeton")
            if len(owned) >= MAX_RUNS_PER_OWNER:
                self._evict_oldest_terminal(owned, MAX_RUNS_PER_OWNER)
            if len(self._runs) >= MAX_RUNS_TOTAL:
                self._evict_oldest_terminal(list(self._runs.values()), MAX_RUNS_TOTAL)
            if len(self._runs) >= MAX_RUNS_TOTAL:
                raise ApiError(422, "limit_exceeded", "capacité de runs atteinte")
            run = Run(run_id=secrets.token_urlsafe(16), owner=owner, seed=scenario.model.seed,
                      scenario_sha256=scenario.sha256, scenario=scenario,
                      options=ProtocolOptions(**req.protocol.model_dump()),
                      energy_profile=req.energy_profile)
            try:
                self._queue.put_nowait(run.run_id)
            except queue.Full:
                raise ApiError(422, "limit_exceeded", "file de calcul pleine") from None
            self._runs[run.run_id] = run
            return run

    def _evict_oldest_terminal(self, runs: list[Run], limit: int) -> None:
        terminal = [r for r in runs if r.state in _TERMINAL]
        for r in terminal[: max(0, len(runs) - limit + 1)]:
            self._runs.pop(r.run_id, None)

    def get(self, owner: str, run_id: str) -> Run:
        if not _RUN_ID.match(run_id):
            raise ApiError(404, "not_found", "run inconnu")
        with self._lock:
            run = self._runs.get(run_id)
        if run is None or run.owner != owner:
            raise ApiError(404, "not_found", "run inconnu")
        return run

    def status(self, run: Run) -> dict[str, Any]:
        with self._lock:
            return RunStatus(
                run_id=run.run_id, state=run.state, progress=run.progress,
                scenario_sha256=run.scenario_sha256, trace_events=run.trace_events,
                problem=Problem(**run.problem) if run.problem else None,
            ).model_dump(exclude_none=True)

    def cancel_or_delete(self, owner: str, run_id: str) -> None:
        run = self.get(owner, run_id)
        with self._lock:
            if run.state in _TERMINAL:
                self._runs.pop(run_id, None)
            else:
                run.cancel = True
                if run.state == "queued":
                    run.state = "cancelled"

    def _loop(self) -> None:
        while not self._stopping.is_set():
            try:
                run_id = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            with self._lock:
                run = self._runs.get(run_id)
                if run is None or run.cancel:
                    if run is not None:
                        run.state = "cancelled"
                    continue
                run.state = "running"
            try:
                self._compute(run)
            except ApiError as exc:
                self._fail(run, exc.code, exc.message)
            except ValueError as exc:
                msg = str(exc)
                if "trace limitée" in msg:
                    self._fail(run, "limit_exceeded", msg)
                else:
                    log.error("run %s : valeur refusée", run.run_id, exc_info=True)
                    self._fail(run, "run_failed", "échec du calcul")
            except Exception:
                log.error("run %s : échec", run.run_id, exc_info=True)
                self._fail(run, "run_failed", "échec du calcul")

    def _fail(self, run: Run, code: str, message: str) -> None:
        with self._lock:
            run.problem = _problem(code, message)
            run.state = "failed"
            run.scenario = None

    def _compute(self, run: Run) -> None:
        assert run.scenario is not None and run.options is not None
        result = run_scenario(run.scenario, energy_profile=run.energy_profile)
        self._set_progress(run, 0.5)
        if run.cancel:
            return self._cancel(run)
        trace = build_trace(run.scenario, run.options)
        if len(trace.events) > MAX_TRACE_EVENTS_PER_RUN:
            raise ApiError(422, "limit_exceeded", "événements au-delà de la borne du run")
        if trace.totals.sent != result.totals.sent or trace.totals.received != result.totals.received:
            raise RuntimeError("trace et totaux ne concordent pas")
        events = _events_list(trace)
        devices = _devices_list(result)
        summary = _summary_dict(run.run_id, result)
        with self._lock:
            if run.cancel:
                run.state = "cancelled"
                run.scenario = None
                return
            run.summary = summary
            run.devices = devices
            run.events = events
            run.event_seqs = [e["seq"] for e in events]
            run.trace_events = len(events)
            run.progress = 1.0
            run.state = "done"
            run.scenario = None
            run.options = None

    def _cancel(self, run: Run) -> None:
        with self._lock:
            run.state = "cancelled"
            run.scenario = None

    def _set_progress(self, run: Run, value: float) -> None:
        with self._lock:
            run.progress = value

    def summary(self, run: Run) -> dict[str, Any]:
        with self._lock:
            if run.state != "done" or run.summary is None:
                raise ApiError(409, "conflict", "run non terminé avec succès")
            return dict(run.summary)

    def devices_page(self, run: Run, cursor: int, limit: int) -> dict[str, Any]:
        with self._lock:
            if run.state != "done":
                raise ApiError(409, "conflict", "run non terminé avec succès")
            items = run.devices[cursor:cursor + limit]
            nxt = cursor + limit if cursor + limit < len(run.devices) else None
        return DevicePage(items=items, next_cursor=nxt).model_dump()  # next_cursor : null en fin

    def events_page(self, run: Run, cursor: int, limit: int) -> dict[str, Any]:
        with self._lock:
            if run.state != "done":
                raise ApiError(409, "conflict", "run non terminé avec succès")
            start = bisect.bisect_left(run.event_seqs, cursor)
            end = min(start + limit, len(run.events))
            items = run.events[start:end]
            nxt = run.event_seqs[end] if end < len(run.events) else None
        return TracePage(items=items, next_cursor=nxt).model_dump()  # next_cursor : null en fin


def _validation_error(exc: ValidationError) -> ApiError:
    err = exc.errors()[0]
    loc = ".".join(str(p) for p in err.get("loc", ()))
    msg = str(err.get("msg", "invalide"))
    code = "terrain_not_allowed" if "terrain" in msg.lower() else "validation_error"
    return ApiError(422, code, f"{loc} : {msg}" if loc else msg, loc or None)


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


# --- HTTP --------------------------------------------------------------------------------------

class ApiServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], tokens: TokenStore, service: RunService) -> None:
        super().__init__(address, _Handler)
        self.tokens = tokens
        self.service = service


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "lsim-api"
    sys_version = ""

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
        try:
            status, body = self._route(method)
        except ApiError as exc:
            status, body = exc.status, _problem(exc.code, exc.message, exc.field)
        except Exception:
            log.error("erreur interne", exc_info=True)
            status, body = 500, _problem("run_failed", "erreur interne")
        self._send(status, body)

    def _send(self, status: int, body: Optional[dict[str, Any]]) -> None:
        data = b"" if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        if status >= 400:
            # Corps éventuellement non lu (erreur avant lecture) : pas de réutilisation du socket.
            self.close_connection = True
        self.send_response(status)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
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

        if method == "GET" and rest == "regions":
            return 200, list_regions().model_dump()
        if method == "POST" and rest == "scenarios/validate":
            return 200, self._validate()
        if method == "POST" and rest == "runs":
            run = svc.create(owner, self._json_body())
            return 202, svc.status(run)

        m = re.fullmatch(r"runs/([^/]+)(?:/(summary|devices|events))?", rest)
        if m is None:
            raise ApiError(404, "not_found", "route inconnue")
        run = svc.get(owner, m.group(1))
        action = m.group(2)
        if method == "GET" and action is None:
            return 200, svc.status(run)
        if method == "DELETE" and action is None:
            svc.cancel_or_delete(owner, m.group(1))
            return 204, None
        if method == "GET" and action == "summary":
            return 200, svc.summary(run)
        if method == "GET" and action in ("devices", "events"):
            cursor, limit = _page_params(query)
            if action == "devices":
                return 200, svc.devices_page(run, cursor, limit)
            return 200, svc.events_page(run, cursor, limit)
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
            _check_scenario_supported(req.scenario)
            scenario = Scenario(req.scenario)
        except (ApiError, ValueError) as exc:
            code = exc.code if isinstance(exc, ApiError) else "validation_error"
            msg = exc.message if isinstance(exc, ApiError) else str(exc)
            return ValidateResponse(valid=False, problems=[
                Problem(code=code, message=msg)]).model_dump(exclude_none=True)
        return ValidateResponse(valid=True, scenario_sha256=scenario.sha256).model_dump(
            exclude_none=True)


def _refuse_constant(name: str) -> None:
    raise ValueError(f"constante JSON refusée : {name}")


def make_server(host: str, port: int, tokens_path: Path, max_queue: int = MAX_QUEUE) -> ApiServer:
    return ApiServer((host, port), TokenStore(tokens_path), RunService(max_queue))


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
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)

    if args.cmd == "issue-token":
        token = TokenStore(args.tokens).issue(args.owner, args.expires_at)
        print(token)
        return 0
    if args.cmd == "revoke":
        n = TokenStore(args.tokens).revoke(args.owner)
        print(f"{n} jeton(s) révoqué(s)")
        return 0
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(message)s")
    server = make_server(args.host, args.port, args.tokens)
    log.info("API %s sur %s:%d", API_VERSION, args.host, args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        server.service.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
