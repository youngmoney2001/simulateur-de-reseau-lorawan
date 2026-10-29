"""Service des sessions du panneau d'étude (`docs/STUDY_PANEL_SPEC.md` §6-7).

Une session regroupe des équipements (un état CLI par équipement), peut être liée à un exercice et
à une simulation terminée. Les sessions sont en mémoire : elles disparaissent au redémarrage, sont
bornées en nombre et expirent après inactivité. Tout accès est filtré par propriétaire ; un
identifiant d'un autre compte renvoie « inconnue » (404), jamais « interdite ».

Les équipements appartiennent à leur session : aucun n'est partagé entre comptes.
Les limites sont vérifiées et appliquées sous le même verrou : pas de dépassement en concurrence.

Le service ne connaît pas le serveur HTTP : `api_server` traduit `StudyError` en réponse.
"""

from __future__ import annotations

import secrets
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Optional

from lsim import study_cli, study_exercises
from lsim.study_contract import (
    AttemptList, AttemptOut, CliError, CliRequest, CliResponse, CriterionResult, HintOut,
    NodeState, SessionCreate, SessionOut, SessionTopology, SimulationBind, SimulationBound,
    SubmitResult,
)

SESSION_TTL_S = 4 * 3600
MAX_SESSIONS_PER_OWNER = 8
MAX_SESSIONS_TOTAL = 256
MAX_OUTPUT = 8000
CLI_NODE_KINDS = ("relay", "border")
MAX_ATTEMPTS = 50                  # journal borné par session (les plus anciennes sont retirées)


class StudyError(Exception):
    def __init__(self, status: int, code: str, message: str, field_name: Optional[str] = None):
        super().__init__(message)
        self.status, self.code, self.message, self.field = status, code, message, field_name


@dataclass
class _Study:
    owner: str
    last_used: float
    exercise_id: Optional[str] = None
    nodes: dict = field(default_factory=dict)       # id -> Node
    cli: dict = field(default_factory=dict)         # id -> study_cli.Session
    reports: dict = field(default_factory=dict)     # id -> rapport de passerelle lié
    run_id: Optional[str] = None
    hints_revealed: dict = field(default_factory=dict)   # exercice -> nombre d'indices révélés
    attempts: deque = field(default_factory=lambda: deque(maxlen=MAX_ATTEMPTS))
    attempt_count: int = 0


class StudyService:
    def __init__(self, *, clock: Callable[[], float] = time.monotonic,
                 wall_clock: Callable[[], float] = time.time) -> None:
        self._clock = clock                 # durée de vie des sessions (monotone)
        self._wall = wall_clock             # horodatage du journal
        self._lock = threading.Lock()
        self._sessions: dict[str, _Study] = {}

    # Accès (verrou tenu par l'appelant) -------------------------------------------------------

    def _purge_locked(self) -> None:
        now = self._clock()
        for sid in [k for k, st in self._sessions.items() if now - st.last_used > SESSION_TTL_S]:
            del self._sessions[sid]

    def _get_locked(self, owner: str, sid: str) -> _Study:
        self._purge_locked()
        st = self._sessions.get(sid)
        if st is None or st.owner != owner:
            raise StudyError(404, "not_found", "session inconnue")
        st.last_used = self._clock()
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
            self._sessions[sid] = _Study(
                owner=owner, last_used=self._clock(), exercise_id=req.exercise_id,
                nodes={n.id: n for n in nodes},
                cli={n.id: study_cli.new_session(n.id) for n in nodes})
        return SessionOut(session_id=sid, exercise_id=req.exercise_id)

    def topology(self, owner: str, sid: str) -> SessionTopology:
        with self._lock:
            st = self._get_locked(owner, sid)
            nodes = list(st.nodes.values())
            states = []
            for node in nodes:
                cli = st.cli[node.id]
                states.append(NodeState(
                    node_id=node.id, hostname=cli.config.hostname,
                    region=cli.config.lora.region,
                    configured=cli.config != study_cli.new_session(node.id).config))
        return SessionTopology(session_id=sid, nodes=nodes, states=states)

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
        return CliResponse(node_id=node.id, mode=result.mode, prompt=result.prompt,
                           output=output, error=error)

    # Liaison à une simulation -------------------------------------------------------------------

    def bind_run(self, owner: str, sid: str, req: SimulationBind, summary: dict) -> SimulationBound:
        """Lie le résumé d'un run terminé selon les associations explicites de la requête.

        Tout est validé avant la moindre modification : une association invalide ne laisse aucun
        équipement à moitié lié. `summary` vient de `RunService.summary` (propriétaire vérifié).
        """
        gateways = {g["name"]: g for g in summary.get("gateways") or []}
        seen_nodes: set[str] = set()
        seen_gateways: set[str] = set()
        with self._lock:
            st = self._get_locked(owner, sid)
            for link in req.links:
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
            for link in req.links:
                report = gateways[link.gateway]
                st.reports[link.node_id] = dict(report)
                st.cli[link.node_id].simulation = study_cli.counters_text(report)
                linked.append(link.node_id)
            for node_id, cli in st.cli.items():
                if node_id not in seen_nodes:
                    cli.simulation = None
            st.run_id = req.run_id
            unlinked = [n for n in st.nodes if n not in seen_nodes]
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
            st.attempts.append(AttemptOut(
                number=st.attempt_count, at=int(self._wall()), exercise_id=exercise_id,
                score=score, max_score=exercise.max_points, hints_used=hints_used,
                passed=[c.id for c in criteria if c.passed]))
        return result

    def attempts(self, owner: str, sid: str) -> AttemptList:
        with self._lock:
            st = self._get_locked(owner, sid)
            items = list(st.attempts)
        return AttemptList(items=items)
