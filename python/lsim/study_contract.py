"""Contrat du panneau d'étude (brouillon, `docs/STUDY_PANEL_SPEC.md` §7) : formes des données.

Brouillon : aucune route n'est encore servie. Les schémas sont dans `schemas/api/study-draft/`,
séparés de `schemas/api/v1` tant que le serveur ne les implémente pas. Règles de sécurité portées
par les types :

- une clé ou un secret ne s'exprime que par la valeur `"******"` (aucune clé réelle en sortie) ;
- la soumission d'un exercice ne porte aucun résultat : le serveur note l'état qu'il détient ;
- le catalogue d'exercices ne contient ni critères détaillés ni solution ;
- toutes les tailles sont bornées (commandes, sorties, nombre d'équipements, critères).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

MAX_NODES = 64                         # même borne que le mesh (kMaxGateways côté natif)
MASKED = "******"
ID_PATTERN = r"^[a-z][a-z0-9-]{0,31}$"           # identifiant d'équipement
EXERCISE_PATTERN = r"^[a-z0-9][a-z0-9-]{2,63}$"
SESSION_PATTERN = r"^[A-Za-z0-9_-]{8,64}$"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


Mode = Literal["user", "privileged", "config", "config-if"]
NodeKind = Literal["sensor", "relay", "border", "server"]


class SessionCreate(_Strict):
    exercise_id: Optional[str] = Field(default=None, pattern=EXERCISE_PATTERN)


class SessionOut(_Strict):
    session_id: str = Field(pattern=SESSION_PATTERN)
    exercise_id: Optional[str] = Field(default=None, pattern=EXERCISE_PATTERN)


class CliRequest(_Strict):
    node_id: str = Field(pattern=ID_PATTERN)
    command: str = Field(max_length=256)  # une ligne ; vide = rien à faire


class CliError(_Strict):
    column: int = Field(ge=0, le=256)     # position fautive (marqueur `^`)
    message: str = Field(max_length=200)


class CliResponse(_Strict):
    node_id: str = Field(pattern=ID_PATTERN)
    mode: Mode
    prompt: str = Field(max_length=80)    # p. ex. « gw1(config-if)# »
    output: str = Field(max_length=8000)
    error: Optional[CliError] = None


class Node(_Strict):
    id: str = Field(pattern=ID_PATTERN)
    kind: NodeKind
    name: str = Field(min_length=1, max_length=64)
    x_m: float = Field(ge=-1_000_000, le=1_000_000)
    y_m: float = Field(ge=-1_000_000, le=1_000_000)


class NodeState(_Strict):
    """État résumé d'un équipement : jamais de clé réelle (`keys` ne vaut que « ****** »)."""

    node_id: str = Field(pattern=ID_PATTERN)
    hostname: str = Field(min_length=1, max_length=64)
    region: Optional[str] = Field(default=None, max_length=16)
    configured: bool
    keys: Optional[Literal["******"]] = None


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


class SubmitResult(_Strict):
    exercise_id: str = Field(pattern=EXERCISE_PATTERN)
    score: int = Field(ge=0, le=1000)     # somme des critères réussis, moins les indices
    max_score: int = Field(ge=1, le=1000)
    hints_used: int = Field(ge=0, le=10)
    criteria: list[CriterionResult] = Field(max_length=50)


_MODELS: dict[str, type[BaseModel]] = {
    "study_session_create": SessionCreate,
    "study_session": SessionOut,
    "study_cli_request": CliRequest,
    "study_cli_response": CliResponse,
    "study_topology": SessionTopology,
    "study_exercise_list": ExerciseList,
    "study_submit_request": SubmitRequest,
    "study_submit_result": SubmitResult,
}


def schemas() -> dict[str, dict]:
    return {name: model.model_json_schema() for name, model in _MODELS.items()}


def write_schemas(directory: Path) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    for name, schema in sorted(schemas().items()):
        path = directory / f"{name}.schema.json"
        path.write_text(json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                        encoding="utf-8")
        written.append(path)
    return written


if __name__ == "__main__":  # python -m lsim.study_contract <dossier>
    import sys

    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("schemas/api/study-draft")
    for p in write_schemas(target):
        print(p)
