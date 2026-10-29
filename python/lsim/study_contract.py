"""Contrat du panneau d'étude (`docs/STUDY_PANEL_SPEC.md` §6-7) : formes des données.

Servi sous `/api/v1` (sessions, CLI, topologie, liaison, exercices, indices, journal) ; les schémas
sont publiés dans `schemas/api/v1` par `python -m lsim.api_contract schemas/api/v1`. Règles de
sécurité portées par les types :

- une clé ou un secret ne s'exprime que par la valeur `"******"` (aucune clé réelle en sortie) ;
- la soumission d'un exercice ne porte aucun résultat : le serveur note l'état qu'il détient ;
- le catalogue d'exercices ne contient ni critères détaillés, ni solution, ni texte d'indice ;
- toutes les tailles sont bornées (commandes, sorties, nombre d'équipements, critères).
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_NODES = 64                         # même borne que le mesh (kMaxGateways côté natif)
MASKED = "******"
ID_PATTERN = r"^[a-z][a-z0-9-]{0,31}$"           # identifiant d'équipement
EXERCISE_PATTERN = r"^[a-z0-9][a-z0-9-]{2,63}$"
SESSION_PATTERN = r"^[A-Za-z0-9_-]{8,64}$"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


Mode = Literal["user", "privileged", "config", "config-if"]
NodeKind = Literal["sensor", "relay", "border", "server"]


Region = Literal["EU868", "US915", "AU915", "AS923", "KR920", "IN865", "RU864"]


class SensorSettings(_Strict):
    """Réglages d'un capteur : un groupe de simulation. Les défauts sont ceux du scénario."""

    spreading_factor: int = Field(7, ge=7, le=12)
    payload_bytes: int = Field(10, ge=0, le=255)
    tx_power_dbm: float = Field(14.0, ge=-10.0, le=30.0)
    period_s: float = Field(600.0, gt=0, le=86400)
    messages: int = Field(1, ge=1, le=1000)
    start_spread_s: float = Field(0.0, ge=0, le=86400)
    region: Optional[Region] = None               # None : plan des passerelles
    channel_freq_hz: Optional[int] = Field(None, ge=137_000_000, le=3_000_000_000)


class Node(_Strict):
    id: str = Field(pattern=ID_PATTERN)
    kind: NodeKind
    name: str = Field(min_length=1, max_length=64)
    x_m: float = Field(ge=-1_000_000, le=1_000_000)
    y_m: float = Field(ge=-1_000_000, le=1_000_000)
    sensor: Optional[SensorSettings] = None      # seulement pour un capteur

    @model_validator(mode="after")
    def _sensor_settings_only_on_sensors(self) -> "Node":
        if self.sensor is not None and self.kind != "sensor":
            raise ValueError("réglages capteur sur un équipement qui n'est pas un capteur")
        return self


class SessionCreate(_Strict):
    """Sans exercice : `nodes` donne la topologie (vide = aucun équipement). Avec un exercice, la
    topologie de départ vient de l'exercice et `nodes` doit rester vide. Le CLI n'existe que pour
    `relay` et `border` (§4)."""

    exercise_id: Optional[str] = Field(default=None, pattern=EXERCISE_PATTERN)
    nodes: list[Node] = Field(default_factory=list, max_length=MAX_NODES)


class SessionOut(_Strict):
    session_id: str = Field(pattern=SESSION_PATTERN)
    exercise_id: Optional[str] = Field(default=None, pattern=EXERCISE_PATTERN)


class CliRequest(_Strict):
    node_id: str = Field(pattern=ID_PATTERN)
    command: str = Field(max_length=256, pattern=r"^[^\r\n\x00]*$")  # une ligne ; vide = rien


class CliError(_Strict):
    column: int = Field(ge=0, le=256)     # position fautive (marqueur `^`)
    message: str = Field(max_length=200)


class CliResponse(_Strict):
    node_id: str = Field(pattern=ID_PATTERN)
    mode: Mode
    prompt: str = Field(max_length=80)    # p. ex. « gw1(config-if)# »
    output: str = Field(max_length=8000)
    error: Optional[CliError] = None


class NodeState(_Strict):
    """État résumé d'un équipement : jamais de clé réelle (`keys` ne vaut que « ****** »)."""

    node_id: str = Field(pattern=ID_PATTERN)
    hostname: str = Field(min_length=1, max_length=64)
    region: Optional[str] = Field(default=None, max_length=16)
    configured: bool
    keys: Optional[Literal["******"]] = None


class GatewayLink(_Strict):
    """Association explicite : un équipement de la session et une passerelle du run (par nom,
    unique dans le scénario). Un équipement ou une passerelle n'apparaît qu'une fois."""

    node_id: str = Field(pattern=ID_PATTERN)
    gateway: str = Field(min_length=1, max_length=64)


class SimulationBind(_Strict):
    """Liaison d'une simulation terminée à la session.

    Sans `links`, seul un run créé par `POST /sessions/{id}/simulate` est lié, selon les liaisons de
    sa compilation. Tout autre run exige des associations explicites : sans elles, rien n'est lié.
    """

    run_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,64}$")
    links: list[GatewayLink] = Field(default_factory=list, max_length=MAX_NODES)


class SimulateRequest(_Strict):
    """Lance une simulation de la topologie de la session, avec sa configuration courante."""

    seed: int = Field(0, ge=0, le=2**32 - 1)


class SimulateOut(_Strict):
    """Run créé à partir de la session. `links` : liaisons à appliquer au résultat (une fois
    terminé) ; `notes` : défauts appliqués et réglages non modélisés."""

    run_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,64}$")
    state: str = Field(max_length=16)
    links: list[GatewayLink] = Field(max_length=MAX_NODES)
    notes: list[str] = Field(max_length=32)


class SimulationBound(_Strict):
    session_id: str = Field(pattern=SESSION_PATTERN)
    run_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,64}$")
    linked: list[str] = Field(max_length=MAX_NODES)     # identifiants d'équipements
    unlinked: list[str] = Field(max_length=MAX_NODES)


class SessionTopology(_Strict):
    session_id: str = Field(pattern=SESSION_PATTERN)
    nodes: list[Node] = Field(max_length=MAX_NODES)
    states: list[NodeState] = Field(max_length=MAX_NODES)


class ExerciseSummary(_Strict):
    """Catalogue : énoncé et nombre d'indices, sans critères ni solution."""

    id: str = Field(pattern=EXERCISE_PATTERN)
    title: str = Field(min_length=1, max_length=120)
    statement: str = Field(min_length=1, max_length=2000)
    max_points: int = Field(ge=1, le=1000)
    hints_available: int = Field(ge=0, le=10)


class ExerciseList(_Strict):
    items: list[ExerciseSummary] = Field(max_length=200)


class SubmitRequest(_Strict):
    """Dépôt : seule la session est envoyée. Le navigateur n'envoie jamais de résultat."""

    session_id: str = Field(pattern=SESSION_PATTERN)


class CriterionResult(_Strict):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    label: str = Field(min_length=1, max_length=200)
    passed: bool
    points: int = Field(ge=0, le=1000)
    max_points: int = Field(ge=0, le=1000)


class HintRequest(_Strict):
    """Demande du prochain indice de l'exercice lié à la session (un indice par demande)."""

    exercise_id: str = Field(pattern=EXERCISE_PATTERN)


class HintOut(_Strict):
    exercise_id: str = Field(pattern=EXERCISE_PATTERN)
    number: int = Field(ge=1, le=10)      # rang de l'indice, à partir de 1
    text: str = Field(min_length=1, max_length=400)
    penalty: int = Field(ge=0, le=100)    # points retirés à la note par cet indice


class AttemptOut(_Strict):
    """Une soumission journalisée : résultats uniquement. Aucune commande CLI, aucun secret."""

    number: int = Field(ge=1)              # rang de la tentative dans la session
    at: int = Field(ge=0)                  # instant de la soumission, secondes depuis l'époque
    exercise_id: str = Field(pattern=EXERCISE_PATTERN)
    score: int = Field(ge=0, le=1000)
    max_score: int = Field(ge=1, le=1000)
    hints_used: int = Field(ge=0, le=10)
    passed: list[str] = Field(max_length=50)   # identifiants des critères réussis


class AttemptList(_Strict):
    items: list[AttemptOut] = Field(max_length=50)


class SubmitResult(_Strict):
    exercise_id: str = Field(pattern=EXERCISE_PATTERN)
    score: int = Field(ge=0, le=1000)     # somme des critères réussis, moins les indices
    max_score: int = Field(ge=1, le=1000)
    hints_used: int = Field(ge=0, le=10)
    criteria: list[CriterionResult] = Field(max_length=50)


MODELS: dict[str, type[BaseModel]] = {
    "study_session_create": SessionCreate,
    "study_session": SessionOut,
    "study_cli_request": CliRequest,
    "study_cli_response": CliResponse,
    "study_topology": SessionTopology,
    "study_exercise_list": ExerciseList,
    "study_submit_request": SubmitRequest,
    "study_submit_result": SubmitResult,
    "study_simulation_bind": SimulationBind,
    "study_simulation_bound": SimulationBound,
    "study_simulate_request": SimulateRequest,
    "study_simulate": SimulateOut,
    "study_sensor": SensorSettings,
    "study_hint_request": HintRequest,
    "study_hint": HintOut,
    "study_attempt_list": AttemptList,
}


def schemas() -> dict[str, dict]:
    return {name: model.model_json_schema() for name, model in MODELS.items()}
