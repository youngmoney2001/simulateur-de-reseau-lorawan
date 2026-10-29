"""Service des sessions du panneau d'étude (`docs/STUDY_PANEL_SPEC.md` §6-7).

Une session regroupe des équipements (topologie, un état CLI par passerelle), peut être liée à un
exercice et à des simulations. Elle se simule elle-même : `simulate` compile la topologie et les
configurations en scénario (`study_compile`) et crée le run par le service des runs.

Persistance : chaque modification est écrite dans `study_store` (SQLite) sous le verrou du service ;
au démarrage, les sessions non expirées sont rechargées. Les sessions expirent après
`SESSION_TTL_S` d'inactivité, à partir de l'horloge injectée (`time.time` en production).

Tout accès est filtré par propriétaire ; un identifiant d'un autre compte renvoie « inconnue »
(404), jamais « interdite ». Les équipements appartiennent à leur session : aucun n'est partagé.
Les limites sont vérifiées et appliquées sous le même verrou : pas de dépassement en concurrence.

Le service ne connaît pas le serveur HTTP : `api_server` traduit `StudyError` en réponse.
"""

from __future__ import annotations

import dataclasses
import secrets
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Optional

from lsim import study_cli, study_exercises
from lsim.study_compile import CompileError, Compiled, compile_session
from lsim.study_contract import (
    MAX_NODES, AttemptList, AttemptOut, CliError, CliRequest, CliResponse, CriterionResult,
    GatewayLink, HintOut, Node, NodeState, Position, SensorSettings, SessionCreate, SessionList,
    SessionOut, SessionSummary, SessionTopology, SimulationBind, SimulationBound, SubmitResult,
)
from lsim.study_store import StudyStore

SESSION_TTL_S = 4 * 3600
MAX_SESSIONS_PER_OWNER = 8
MAX_SESSIONS_TOTAL = 256
MAX_OUTPUT = 8000
CLI_NODE_KINDS = ("relay", "border")
MAX_ATTEMPTS = 50                  # journal borné par session (les plus anciennes sont retirées)
MAX_COMPILED = 16                  # liaisons de compilation gardées par session
TOUCH_PERSIST_S = 60.0             # une lecture n'est écrite qu'à cette fréquence (expiration)


class StudyError(Exception):
    def __init__(self, status: int, code: str, message: str, field_name: Optional[str] = None):
        super().__init__(message)
        self.status, self.code, self.message, self.field = status, code, message, field_name


# Sérialisation (la configuration CLI ne porte aucun secret : voir study_cli) -------------------

def _cfg_to_dict(cfg: study_cli.GatewayConfig) -> dict:
    lw = cfg.lorawan
    return {
        "hostname": cfg.hostname,
        "lora": dataclasses.asdict(cfg.lora),
        "mesh": dataclasses.asdict(cfg.mesh),
        "eth": dataclasses.asdict(cfg.eth),
        "lorawan": {
            "net_id": lw.net_id,
            "server": list(lw.server) if lw.server is not None else None,
            "transport": lw.transport,
            "location": list(lw.location) if lw.location is not None else None,
        },
    }


def _cfg_from_dict(d: dict) -> study_cli.GatewayConfig:
    lw = d["lorawan"]
    return study_cli.GatewayConfig(
        hostname=d["hostname"],
        lora=study_cli.LoraIf(**d["lora"]),
        mesh=study_cli.MeshIf(**d["mesh"]),
        eth=study_cli.EthIf(**d["eth"]),
        lorawan=study_cli.LorawanCfg(
            net_id=lw["net_id"],
            server=tuple(lw["server"]) if lw["server"] is not None else None,
            transport=lw["transport"],
            location=tuple(lw["location"]) if lw["location"] is not None else None))


def _cli_to_dict(s: study_cli.Session) -> dict:
    return {"config": _cfg_to_dict(s.config), "startup": _cfg_to_dict(s.startup), "mode": s.mode,
            "iface": s.iface, "simulation": s.simulation, "closed": s.closed}


def _cli_from_dict(node_id: str, d: dict) -> study_cli.Session:
    return study_cli.Session(node_id=node_id, config=_cfg_from_dict(d["config"]),
                             startup=_cfg_from_dict(d["startup"]), mode=d["mode"], iface=d["iface"],
                             simulation=d["simulation"], closed=d["closed"])


@dataclass
class _Study:
    owner: str
    last_used: float
    saved_used: float = 0.0            # dernière valeur de `last_used` écrite en base
    exercise_id: Optional[str] = None
    nodes: dict = field(default_factory=dict)       # id -> Node
    cli: dict = field(default_factory=dict)         # id -> study_cli.Session
    reports: dict = field(default_factory=dict)     # id -> rapport de passerelle lié
    run_id: Optional[str] = None
    hints_revealed: dict = field(default_factory=dict)   # exercice -> nombre d'indices révélés
    attempts: deque = field(default_factory=lambda: deque(maxlen=MAX_ATTEMPTS))
    attempt_count: int = 0
    compiled: dict = field(default_factory=dict)    # run_id -> [GatewayLink] (compilation)


def _encode(st: _Study) -> dict:
    return {
        "exercise_id": st.exercise_id,
        "nodes": {nid: n.model_dump(mode="json") for nid, n in st.nodes.items()},
        "cli": {nid: _cli_to_dict(c) for nid, c in st.cli.items()},
        "reports": st.reports,
        "run_id": st.run_id,
        "hints_revealed": st.hints_revealed,
        "attempt_count": st.attempt_count,
        "compiled": {rid: [link.model_dump(mode="json") for link in links]
                     for rid, links in st.compiled.items()},
    }


def _decode(owner: str, last_used: float, body: dict, attempts: list[dict]) -> _Study:
    st = _Study(owner=owner, last_used=last_used, saved_used=last_used,
                exercise_id=body["exercise_id"],
                nodes={nid: Node.model_validate(n) for nid, n in body["nodes"].items()},
                cli={nid: _cli_from_dict(nid, c) for nid, c in body["cli"].items()},
                reports=body["reports"], run_id=body["run_id"],
                hints_revealed=body["hints_revealed"], attempt_count=body["attempt_count"],
                compiled={rid: [GatewayLink.model_validate(x) for x in links]
                          for rid, links in body["compiled"].items()})
    st.attempts.extend(AttemptOut.model_validate(a) for a in attempts)
    return st


class StudyService:
    def __init__(self, *, clock: Callable[[], float] = time.time,
                 store: Optional[StudyStore] = None) -> None:
        self._clock = clock                 # horloge murale : expiration et horodatage du journal
        self._lock = threading.Lock()
        self._store = store if store is not None else StudyStore(":memory:")
        self._sessions: dict[str, _Study] = {}
        now = self._clock()
        for sid, owner, used, body in self._store.load_sessions():
            if now - used > SESSION_TTL_S:
                self._store.delete_session(sid)
                continue
            self._sessions[sid] = _decode(owner, used, body, self._store.attempts(sid))

    def close(self) -> None:
        self._store.close()

    # Accès et persistance (verrou tenu par l'appelant) ----------------------------------------

    def _save(self, sid: str, st: _Study) -> None:
        st.saved_used = st.last_used
        self._store.save_session(sid, st.owner, st.last_used, _encode(st))

    def _purge_locked(self) -> None:
        now = self._clock()
        for sid in [k for k, st in self._sessions.items() if now - st.last_used > SESSION_TTL_S]:
            del self._sessions[sid]
            self._store.delete_session(sid)

    def _get_locked(self, owner: str, sid: str) -> _Study:
        self._purge_locked()
        st = self._sessions.get(sid)
        if st is None or st.owner != owner:
            raise StudyError(404, "not_found", "session inconnue")
        st.last_used = self._clock()
        if st.last_used - st.saved_used >= TOUCH_PERSIST_S:
            self._save(sid, st)
        return st

    # Sessions -----------------------------------------------------------------------------------

    def create(self, owner: str, req: SessionCreate) -> SessionOut:
        nodes = list(req.nodes)
        if req.exercise_id is not None:
            exercise = study_exercises.get(req.exercise_id)
            if exercise is None:
                raise StudyError(422, "validation_error", "exercice inconnu", "exercise_id")
            if nodes:
                raise StudyError(422, "validation_error",
                                 "la topologie vient de l'exercice : nodes doit être vide",
                                 "nodes")
            nodes = list(exercise.start_nodes)
        ids = [n.id for n in nodes]
        if len(set(ids)) != len(ids):
            raise StudyError(422, "validation_error", "identifiants d'équipements en double",
                             "nodes")
        with self._lock:
            self._purge_locked()
            owned = sum(1 for st in self._sessions.values() if st.owner == owner)
            if owned >= MAX_SESSIONS_PER_OWNER:
                raise StudyError(429, "limit_exceeded", "trop de sessions pour ce compte")
            if len(self._sessions) >= MAX_SESSIONS_TOTAL:
                raise StudyError(429, "limit_exceeded", "capacité des sessions atteinte")
            sid = secrets.token_urlsafe(16)
            st = _Study(owner=owner, last_used=self._clock(), exercise_id=req.exercise_id,
                        nodes={n.id: n for n in nodes},
                        cli={n.id: study_cli.new_session(n.id) for n in nodes})
            self._sessions[sid] = st
            self._save(sid, st)
        return SessionOut(session_id=sid, exercise_id=req.exercise_id)

    def _topology_locked(self, sid: str, st: _Study) -> SessionTopology:
        nodes = list(st.nodes.values())
        states = []
        for node in nodes:
            cli = st.cli[node.id]
            states.append(NodeState(
                node_id=node.id, hostname=cli.config.hostname,
                region=cli.config.lora.region,
                configured=cli.config != study_cli.new_session(node.id).config))
        return SessionTopology(session_id=sid, nodes=nodes, states=states)

    def topology(self, owner: str, sid: str) -> SessionTopology:
        with self._lock:
            st = self._get_locked(owner, sid)
            return self._topology_locked(sid, st)

    # Topologie : ajout, retrait, réglages de capteur ------------------------------------------

    def add_node(self, owner: str, sid: str, node: Node) -> SessionTopology:
        with self._lock:
            st = self._get_locked(owner, sid)
            if node.id in st.nodes:
                raise StudyError(422, "validation_error", "identifiant d'équipement déjà utilisé",
                                 "id")
            if len(st.nodes) >= MAX_NODES:
                raise StudyError(422, "limit_exceeded",
                                 f"au plus {MAX_NODES} équipements par session", "nodes")
            st.nodes[node.id] = node
            st.cli[node.id] = study_cli.new_session(node.id)
            self._save(sid, st)
            return self._topology_locked(sid, st)

    def move_node(self, owner: str, sid: str, node_id: str, pos: Position) -> SessionTopology:
        with self._lock:
            st = self._get_locked(owner, sid)
            node = st.nodes.get(node_id)
            if node is None:
                raise StudyError(404, "not_found", "équipement inconnu dans cette session")
            st.nodes[node_id] = node.model_copy(update={"x_m": pos.x_m, "y_m": pos.y_m})
            self._save(sid, st)
            return self._topology_locked(sid, st)

    def list_sessions(self, owner: str) -> SessionList:
        """Sessions du compte, les plus récentes d'abord. Jamais celles d'un autre compte."""
        with self._lock:
            self._purge_locked()
            now = self._clock()
            mine = [(sid, st) for sid, st in self._sessions.items() if st.owner == owner]
            mine.sort(key=lambda item: item[1].last_used, reverse=True)
            return SessionList(items=[
                SessionSummary(session_id=sid, exercise_id=st.exercise_id,
                               nodes=len(st.nodes), idle_s=max(0, int(now - st.last_used)))
                for sid, st in mine])

    def delete_session(self, owner: str, sid: str) -> None:
        with self._lock:
            self._get_locked(owner, sid)            # 404 si inconnue ou d'un autre compte
            del self._sessions[sid]
            self._store.delete_session(sid)

    def remove_node(self, owner: str, sid: str, node_id: str) -> None:
        with self._lock:
            st = self._get_locked(owner, sid)
            if node_id not in st.nodes:
                raise StudyError(404, "not_found", "équipement inconnu dans cette session")
            del st.nodes[node_id], st.cli[node_id]
            st.reports.pop(node_id, None)
            self._save(sid, st)

    def set_sensor(self, owner: str, sid: str, node_id: str,
                   settings: SensorSettings) -> SessionTopology:
        with self._lock:
            st = self._get_locked(owner, sid)
            node = st.nodes.get(node_id)
            if node is None:
                raise StudyError(404, "not_found", "équipement inconnu dans cette session")
            if node.kind != "sensor":
                raise StudyError(422, "validation_error", "réglages capteur : équipement non capteur",
                                 "node_id")
            st.nodes[node_id] = node.model_copy(update={"sensor": settings})
            self._save(sid, st)
            return self._topology_locked(sid, st)

    def cli(self, owner: str, sid: str, req: CliRequest) -> CliResponse:
        with self._lock:
            st = self._get_locked(owner, sid)
            node = st.nodes.get(req.node_id)
            if node is None:
                raise StudyError(404, "not_found", "équipement inconnu dans cette session")
            if node.kind not in CLI_NODE_KINDS:
                raise StudyError(422, "validation_error",
                                 "pas de CLI pour ce type d'équipement", "node_id")
            cli = st.cli[node.id]
            result = study_cli.execute(cli, req.command)
            output = result.output
            if cli.closed:  # « exit » au niveau utilisateur : la console redémarre en mode utilisateur
                cli.closed, cli.mode = False, "user"
                output = "% Session console fermée ; retour au mode utilisateur."
            if len(output) > MAX_OUTPUT:
                output = output[:MAX_OUTPUT - 40] + "\n% sortie tronquée"
            error = None
            if result.error is not None:
                column, message = result.error
                error = CliError(column=min(column, 256), message=message[:200])
            self._save(sid, st)
        return CliResponse(node_id=node.id, mode=result.mode, prompt=result.prompt,
                           output=output, error=error)

    # Simulation de la session -----------------------------------------------------------------

    def compile(self, owner: str, sid: str, seed: int) -> Compiled:
        """Compile la topologie et les configurations courantes. Lève `StudyError` (422)."""
        with self._lock:
            st = self._get_locked(owner, sid)
            nodes = list(st.nodes.values())
            configs = {nid: cli.config.copy() for nid, cli in st.cli.items()}
        try:
            return compile_session(nodes, configs, seed)
        except CompileError as exc:
            raise StudyError(422, "validation_error", exc.message, exc.field) from None

    def record_simulation(self, owner: str, sid: str, run_id: str, links: list[dict]) -> None:
        """Mémorise les liaisons d'un run créé par `compile` (appelé après sa création)."""
        with self._lock:
            st = self._get_locked(owner, sid)
            st.compiled[run_id] = [GatewayLink.model_validate(x) for x in links]
            while len(st.compiled) > MAX_COMPILED:
                del st.compiled[next(iter(st.compiled))]
            st.run_id = run_id
            self._save(sid, st)

    # Liaison à une simulation -------------------------------------------------------------------

    def bind_run(self, owner: str, sid: str, req: SimulationBind, summary: dict) -> SimulationBound:
        """Lie le résumé d'un run terminé selon les associations de la requête, ou, sans
        association, selon la compilation de la session si le run en vient.

        Tout est validé avant la moindre modification : une association invalide ne laisse aucun
        équipement à moitié lié. `summary` vient de `RunService.summary` (propriétaire vérifié).
        """
        gateways = {g["name"]: g for g in summary.get("gateways") or []}
        seen_nodes: set[str] = set()
        seen_gateways: set[str] = set()
        with self._lock:
            st = self._get_locked(owner, sid)
            if req.links:
                links = list(req.links)
            else:
                links = [link for link in st.compiled.get(req.run_id, [])
                         if link.node_id in st.nodes]
            for link in links:
                node = st.nodes.get(link.node_id)
                if node is None:
                    raise StudyError(422, "validation_error",
                                     f"équipement inconnu : {link.node_id}", "links")
                if node.kind not in CLI_NODE_KINDS:
                    raise StudyError(422, "validation_error",
                                     f"équipement sans passerelle : {link.node_id}", "links")
                if link.gateway not in gateways:
                    raise StudyError(422, "validation_error",
                                     f"passerelle absente du run : {link.gateway}", "links")
                if link.node_id in seen_nodes or link.gateway in seen_gateways:
                    raise StudyError(422, "validation_error",
                                     "équipement ou passerelle associé deux fois", "links")
                seen_nodes.add(link.node_id)
                seen_gateways.add(link.gateway)
            st.reports = {}
            linked = []
            for link in links:
                report = gateways[link.gateway]
                st.reports[link.node_id] = dict(report)
                st.cli[link.node_id].simulation = study_cli.counters_text(report)
                linked.append(link.node_id)
            for node_id, cli in st.cli.items():
                if node_id not in seen_nodes:
                    cli.simulation = None
            st.run_id = req.run_id
            unlinked = [n for n in st.nodes if n not in seen_nodes]
            self._save(sid, st)
        return SimulationBound(session_id=sid, run_id=req.run_id, linked=linked, unlinked=unlinked)

    # Exercices ----------------------------------------------------------------------------------

    @staticmethod
    def _exercise_for_session(st: _Study, exercise_id: str, field_name: str):
        exercise = study_exercises.get(exercise_id)
        if exercise is None:
            raise StudyError(404, "not_found", "exercice inconnu")
        if st.exercise_id != exercise_id:
            raise StudyError(422, "validation_error",
                             "session non liée à cet exercice", field_name)
        return exercise

    def hint(self, owner: str, sid: str, exercise_id: str) -> HintOut:
        """Révèle l'indice suivant de l'exercice lié à la session. Chaque indice coûte des points."""
        with self._lock:
            st = self._get_locked(owner, sid)
            exercise = self._exercise_for_session(st, exercise_id, "exercise_id")
            used = st.hints_revealed.get(exercise_id, 0)
            if used >= len(exercise.hints):
                raise StudyError(409, "conflict", "plus d'indice disponible pour cet exercice")
            st.hints_revealed[exercise_id] = used + 1
            self._save(sid, st)
        return HintOut(exercise_id=exercise_id, number=used + 1,
                       text=exercise.hints[used], penalty=study_exercises.HINT_PENALTY)

    def submit(self, owner: str, exercise_id: str, sid: str) -> SubmitResult:
        """Note la session pour l'exercice. Seul l'état détenu par le serveur est évalué.

        Chaque indice révélé retire `HINT_PENALTY` points (plancher 0). La tentative est
        journalisée avec ses résultats seulement : ni commande CLI, ni secret.
        """
        with self._lock:
            st = self._get_locked(owner, sid)
            exercise = self._exercise_for_session(st, exercise_id, "session_id")
            state = study_exercises.State(
                configs={nid: cli.config.copy() for nid, cli in st.cli.items()},
                reports={nid: dict(r) for nid, r in st.reports.items()})
            hints_used = st.hints_revealed.get(exercise_id, 0)
        graded = study_exercises.grade(exercise, state)
        criteria = [CriterionResult(id=c.id, label=c.label, passed=ok,
                                    points=c.points if ok else 0, max_points=c.points)
                    for c, ok in graded]
        score = max(0, sum(c.points for c in criteria)
                    - hints_used * study_exercises.HINT_PENALTY)
        result = SubmitResult(exercise_id=exercise_id, score=score,
                              max_score=exercise.max_points, hints_used=hints_used,
                              criteria=criteria)
        with self._lock:
            st = self._get_locked(owner, sid)
            st.attempt_count += 1
            attempt = AttemptOut(
                number=st.attempt_count, at=int(self._clock()), exercise_id=exercise_id,
                score=score, max_score=exercise.max_points, hints_used=hints_used,
                passed=[c.id for c in criteria if c.passed])
            st.attempts.append(attempt)
            self._store.add_attempt(sid, attempt.number, attempt.model_dump(mode="json"),
                                    keep=MAX_ATTEMPTS)
            self._save(sid, st)
        return result

    def attempts(self, owner: str, sid: str) -> AttemptList:
        with self._lock:
            st = self._get_locked(owner, sid)
            items = list(st.attempts)
        return AttemptList(items=items)
