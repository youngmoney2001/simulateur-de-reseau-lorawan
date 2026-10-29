"""Catalogue d'exercices notés du panneau d'étude (`docs/STUDY_PANEL_SPEC.md` §6).

Les critères et la solution restent côté serveur : le catalogue public ne donne que l'énoncé, le
total de points et le nombre d'indices. La note est calculée sur l'état que la session détient
(configurations CLI et compteurs du run lié) ; le client n'envoie jamais de résultat.

Vérifications disponibles : paramètres de configuration (région, sous-bande, serveur, mode mesh,
nombre de sauts) et une trame reçue par une passerelle dans le run lié. Une vérification de
connectivité ou de latence n'est pas encore disponible : elle ne figure donc pas au catalogue.
Les indices ne sont pas servis : `hints_available` vaut 0 (§7, point ouvert).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from lsim.study_cli import GatewayConfig
from lsim.study_contract import ExerciseList, ExerciseSummary, Node


@dataclass(frozen=True)
class State:
    """État noté : copie des configurations et compteurs des équipements liés à un run."""

    configs: dict            # id -> GatewayConfig
    reports: dict            # id -> rapport de passerelle (seulement pour les équipements liés)

    def config(self, node: str) -> Optional[GatewayConfig]:
        return self.configs.get(node)


@dataclass(frozen=True)
class Criterion:
    id: str
    label: str
    points: int
    check: Callable[[State], bool]


@dataclass(frozen=True)
class Exercise:
    id: str
    title: str
    statement: str
    start_nodes: tuple
    criteria: tuple

    @property
    def max_points(self) -> int:
        return sum(c.points for c in self.criteria)


def _region(node: str, value: str) -> Callable[[State], bool]:
    return lambda st: st.config(node) is not None and st.config(node).lora.region == value


def _sub_band(node: str, value: int) -> Callable[[State], bool]:
    return lambda st: st.config(node) is not None and st.config(node).lora.sub_band == value


def _lorawan_server(node: str, addr: str, up: int, down: int) -> Callable[[State], bool]:
    return lambda st: (st.config(node) is not None
                       and st.config(node).lorawan.server == (addr, up, down))


def _mesh_mode(node: str, value: str) -> Callable[[State], bool]:
    return lambda st: st.config(node) is not None and st.config(node).mesh.mode == value


def _max_hops_at_most(node: str, limit: int) -> Callable[[State], bool]:
    def check(st: State) -> bool:
        cfg = st.config(node)
        return cfg is not None and cfg.mesh.max_hops is not None and cfg.mesh.max_hops <= limit

    return check


def _received_at_least(node: str, count: int) -> Callable[[State], bool]:
    def check(st: State) -> bool:
        report = st.reports.get(node)
        return report is not None and report["received"] >= count

    return check


def _node(id_: str, kind: str, name: str, x: float, y: float) -> Node:
    return Node(id=id_, kind=kind, name=name, x_m=x, y_m=y)


EXERCISES: tuple[Exercise, ...] = (
    Exercise(
        id="eu868-passerelle",
        title="Configurer une passerelle frontière sur EU868",
        statement=("Configurez la passerelle frontière frontiere pour le plan EU868 et déclarez son "
                   "serveur réseau : adresse 10.0.0.5, port montant 1700, port descendant 1701."),
        start_nodes=(_node("frontiere", "border", "Frontière", 0, 0),),
        criteria=(
            Criterion("region", "Plan régional EU868 sur la passerelle frontière", 10,
                      _region("frontiere", "EU868")),
            Criterion("serveur", "Serveur réseau 10.0.0.5, ports 1700 et 1701", 10,
                      _lorawan_server("frontiere", "10.0.0.5", 1700, 1701)),
        ),
    ),
    Exercise(
        id="relais-deux-sauts",
        title="Ajouter un relais à deux sauts au plus",
        statement=("Configurez le relais relais-1 en mode relay, avec au plus deux sauts."),
        start_nodes=(_node("frontiere", "border", "Frontière", 0, 0),
                     _node("relais-1", "relay", "Relais 1", 1200, 0)),
        criteria=(
            Criterion("mode", "Relais en mode relay", 10, _mesh_mode("relais-1", "relay")),
            Criterion("sauts", "Au plus 2 sauts sur le relais", 10,
                      _max_hops_at_most("relais-1", 2)),
        ),
    ),
    Exercise(
        id="us915-sous-bande",
        title="Choisir la sous-bande US915 et vérifier la réception",
        statement=("Configurez la passerelle frontière frontiere sur le plan US915, sous-bande 2. "
                   "Liez ensuite une simulation à la session : la frontière doit recevoir au moins "
                   "une trame."),
        start_nodes=(_node("frontiere", "border", "Frontière", 0, 0),),
        criteria=(
            Criterion("region", "Plan régional US915", 10, _region("frontiere", "US915")),
            Criterion("sous-bande", "Sous-bande 2", 10, _sub_band("frontiere", 2)),
            Criterion("reception", "Au moins une trame reçue par la frontière", 10,
                      _received_at_least("frontiere", 1)),
        ),
    ),
)

_BY_ID = {e.id: e for e in EXERCISES}
assert len(_BY_ID) == len(EXERCISES), "identifiants d'exercices en double"


def get(exercise_id: str) -> Optional[Exercise]:
    return _BY_ID.get(exercise_id)


def listing() -> ExerciseList:
    return ExerciseList(items=[
        ExerciseSummary(id=e.id, title=e.title, statement=e.statement,
                        max_points=e.max_points, hints_available=0)
        for e in EXERCISES
    ])


def grade(exercise: Exercise, state: State) -> list[tuple[Criterion, bool]]:
    """Évalue chaque critère. Aucun état partiel n'est retenu : un critère est réussi ou non."""
    return [(c, bool(c.check(state))) for c in exercise.criteria]
