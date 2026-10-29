"""Service des sessions du panneau d'étude (`docs/STUDY_PANEL_SPEC.md` §7).

Une session regroupe des équipements (un état CLI par équipement) et peut être liée à une
simulation terminée. Les sessions sont en mémoire : elles disparaissent au redémarrage, sont bornées
en nombre et expirent après inactivité. Tout accès est filtré par propriétaire ; un identifiant
d'un autre compte renvoie « inconnue » (404), jamais « interdite ».

Le service ne connaît pas le serveur HTTP : `api_server` traduit `StudyError` en réponse.
"""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from lsim import study_cli
from lsim.study_contract import (
    CliError, CliRequest, CliResponse, NodeState, SessionCreate, SessionOut, SessionTopology,
    SimulationBind, SimulationBound,
)

SESSION_TTL_S = 4 * 3600
MAX_SESSIONS_PER_OWNER = 8
MAX_SESSIONS_TOTAL = 256
MAX_OUTPUT = 8000
CLI_NODE_KINDS = ("relay", "border")


class StudyError(Exception):
    def __init__(self, status: int, code: str, message: str, field_name: Optional[str] = None):
        super().__init__(message)
        self.status, self.code, self.message, self.field = status, code, message, field_name


@dataclass
class _Study:
    owner: str
    created: float
    last_used: float
    nodes: dict = field(default_factory=dict)       # id -> Node
    cli: dict = field(default_factory=dict)         # id -> study_cli.Session
    run_id: Optional[str] = None


class StudyService:
    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
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

    # Opérations ---------------------------------------------------------------------------------

    def create(self, owner: str, req: SessionCreate) -> SessionOut:
        if req.exercise_id is not None:
            raise StudyError(422, "validation_error",
                             "aucun exercice disponible dans cette version", "exercise_id")
        ids = [n.id for n in req.nodes]
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
            now = self._clock()
            self._sessions[sid] = _Study(
                owner=owner, created=now, last_used=now,
                nodes={n.id: n for n in req.nodes},
                cli={n.id: study_cli.new_session(n.id) for n in req.nodes})
        return SessionOut(session_id=sid)

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

    def bind_run(self, owner: str, sid: str, req: SimulationBind, summary: dict) -> SimulationBound:
        """Lie le résumé d'un run terminé. `summary` vient de `RunService.summary` (propriétaire
        vérifié) ; un run mono-passerelle ne lie aucun équipement faute de nom de passerelle."""
        reports = {g["name"]: g for g in summary.get("gateways") or []}
        with self._lock:
            st = self._get_locked(owner, sid)
            linked, unlinked = [], []
            for node in st.nodes.values():
                cli = st.cli[node.id]
                if node.kind in CLI_NODE_KINDS and node.id in reports:
                    cli.simulation = study_cli.counters_text(reports[node.id])
                    linked.append(node.id)
                else:
                    cli.simulation = None
                    unlinked.append(node.id)
            st.run_id = req.run_id
        return SimulationBound(session_id=sid, run_id=req.run_id, linked=linked, unlinked=unlinked)
