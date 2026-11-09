"""Catalogue d'exercices notés du panneau d'étude (`docs/STUDY_PANEL_SPEC.md` §6).

Les critères et la solution restent côté serveur : le catalogue public ne donne que l'énoncé, le
total de points et le nombre d'indices. La note est calculée sur l'état que la session détient
(configurations CLI et compteurs du run lié) ; le client n'envoie jamais de résultat.

Vérifications disponibles :
- configuration (région, sous-bande, serveur, mode mesh, nombre de sauts) ;
- simulation liée : trames reçues, lien mesh observé entre deux passerelles, latence p95 remise
  au LNS par une passerelle (indicateurs publiés dans le résumé du run, `trace_metrics`) ;
- débit observé : SF de départ et SF du dernier uplink d'un capteur (`State.sf_final`). C'est la
  seule pièce qui dise si le serveur a *effectivement* changé le débit — une case cochée dans le
  formulaire dit ce qui a été demandé, pas ce qui a été commandé.

Indices : chaque exercice en a deux, révélés un à un à la demande. Chaque indice révélé retire
`HINT_PENALTY` points de la note (plancher 0). Le texte d'un indice ne quitte le serveur qu'à la
demande.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from lsim.study_cli import GatewayConfig
from lsim.study_contract import ExerciseList, ExerciseSummary, Node, SensorSettings


HINT_PENALTY = 2   # points retirés par indice révélé (§6, barème)


@dataclass(frozen=True)
class State:
    """État noté : copie des configurations et compteurs des équipements liés à un run."""

    configs: dict            # id -> GatewayConfig
    reports: dict            # id -> rapport de passerelle (seulement pour les équipements liés)
    # groupe (identifiant de l'équipement) -> {"spreading_factor", "final_spreading_factor"}
    # Vide avant la liaison d'un run, et sur la voie multi-passerelles qui n'observe pas la fin.
    devices: dict = field(default_factory=dict)
    adr: bool = False            # ADR demandé sur la session (le souhait, pas son effet)

    def config(self, node: str) -> Optional[GatewayConfig]:
        return self.configs.get(node)

    def sf_final(self, node: str) -> Optional[int]:
        """SF du dernier uplink de l'équipement, tel que le run l'a laissé.

        `None` quand le run n'observe pas la fin : ce n'est pas « pas de changement », c'est
        « rien de mesuré ». Un critère qui confondrait les deux noterait à côté.
        """
        d = self.devices.get(node)
        return None if d is None else d.get("final_spreading_factor")

    def sf_depart(self, node: str) -> Optional[int]:
        d = self.devices.get(node)
        return None if d is None else d.get("spreading_factor")


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
    hints: tuple = ()

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


def _mesh_bandwidth(node: str, value: str) -> Callable[[State], bool]:
    """Bande passante du mesh en kHz, telle que la rapporte la CLI (203, 406, 812, 1625)."""

    def check(st: State) -> bool:
        cfg = st.config(node)
        return cfg is not None and cfg.mesh.bandwidth_khz == value

    return check


def _received_at_least(node: str, count: int) -> Callable[[State], bool]:
    def check(st: State) -> bool:
        report = st.reports.get(node)
        return report is not None and report["received"] >= count

    return check


def _mesh_inbound(node: str, from_node: str) -> Callable[[State], bool]:
    """La passerelle liée à `node` a reçu par le mesh au moins une trame de la passerelle liée à
    `from_node`. Les liens du run sont nommés par passerelle : on passe par la liaison."""

    def check(st: State) -> bool:
        report, source = st.reports.get(node), st.reports.get(from_node)
        if report is None or source is None:
            return False
        return any(link["from_gateway"] == source["name"] and link["delivered"] >= 1
                   for link in report.get("mesh_inbound", []))

    return check


def _latency_p95_at_most(node: str, limit_ms: float) -> Callable[[State], bool]:
    def check(st: State) -> bool:
        report = st.reports.get(node)
        p95 = None if report is None else report.get("latency_p95_ms")
        return p95 is not None and p95 <= limit_ms

    return check


def _adr_active() -> Callable[[State], bool]:
    """L'ADR est demandé sur la session. C'est le souhait : son effet se lit dans `sf_final`."""
    return lambda st: st.adr


def _sf_a_baisse(node: str) -> Callable[[State], bool]:
    """Le run **observe** un débit plus rapide à la fin qu'au départ, sur cet équipement.

    C'est la pièce qui distingue « la case est cochée » de « le serveur a commandé » : une
    commande MAC ne porte que son nom, et les sauts d'un uplink portent le DR de départ figé.
    Seul le SF du dernier uplink le dit.

    Renvoie False quand le SF final est absent : rien de mesuré n'est pas « pas de changement »,
    et noter True sur une absence reviendrait à donner le point sans la preuve.
    """
    def check(st: State) -> bool:
        depart, fin = st.sf_depart(node), st.sf_final(node)
        if not isinstance(depart, int) or not isinstance(fin, int):
            return False
        return fin < depart      # SF plus bas = débit plus rapide

    return check


def _node(id_: str, kind: str, name: str, x: float, y: float) -> Node:
    return Node(id=id_, kind=kind, name=name, x_m=x, y_m=y)


def _sensor(x: float, tx_power_dbm: float = 14.0, messages: int = 1,
            spreading_factor: int = 7) -> Node:
    """Capteur de départ. Avec un relais, il émet à -10 dBm à 1500 m : la frontière ne l'entend
    pas, le relais (à 300 m) si, et la trame n'arrive au LNS que par le mesh."""
    return Node(id="capteur-1", kind="sensor", name="Capteur 1", x_m=x, y_m=0,
                sensor=SensorSettings(tx_power_dbm=tx_power_dbm, messages=messages,
                                      spreading_factor=spreading_factor,
                                      period_s=60.0 if messages > 1 else 600.0))


EXERCISES: tuple[Exercise, ...] = (
    Exercise(
        id="eu868-passerelle",
        title="Configurer une passerelle frontière sur EU868",
        statement=("Configurez la passerelle frontière frontiere pour le plan EU868 et déclarez son "
                   "serveur réseau : adresse 10.0.0.5, port montant 1700, port descendant 1701."),
        start_nodes=(_node("frontiere", "border", "Frontière", 0, 0), _sensor(500)),
        criteria=(
            Criterion("region", "Plan régional EU868 sur la passerelle frontière", 10,
                      _region("frontiere", "EU868")),
            Criterion("serveur", "Serveur réseau 10.0.0.5, ports 1700 et 1701", 10,
                      _lorawan_server("frontiere", "10.0.0.5", 1700, 1701)),
        ),
        hints=("Le plan régional se règle sur l'interface lora : cherchez la commande « region ».",
               "La commande « lorawan server » prend l'adresse, puis « up-port » et « down-port »."),
    ),
    Exercise(
        id="relais-deux-sauts",
        title="Ajouter un relais à deux sauts au plus",
        statement=("Configurez le relais relais-1 en mode relay, avec au plus deux sauts. Liez une "
                   "simulation : la frontière doit recevoir par le mesh des trames de relais-1."),
        start_nodes=(_node("frontiere", "border", "Frontière", 0, 0),
                     _node("relais-1", "relay", "Relais 1", 1200, 0),
                     _sensor(1500, tx_power_dbm=-10.0)),
        criteria=(
            Criterion("mode", "Relais en mode relay", 10, _mesh_mode("relais-1", "relay")),
            Criterion("sauts", "Au plus 2 sauts sur le relais", 10,
                      _max_hops_at_most("relais-1", 2)),
            Criterion("lien", "Lien mesh observé : relais-1 vers la frontière", 10,
                      _mesh_inbound("frontiere", "relais-1")),
        ),
        hints=("Le mode relais et le nombre de sauts se règlent sur l'interface mesh (« int mesh 0 »).",
               "Le lien n'apparaît dans le run que si relais-1 relaie vers la frontière : vérifiez "
               "que les deux équipements sont liés à leurs passerelles."),
    ),
    Exercise(
        id="us915-sous-bande",
        title="Choisir la sous-bande US915 et vérifier la réception",
        statement=("Configurez la passerelle frontière frontiere sur le plan US915, sous-bande 2. "
                   "Liez ensuite une simulation à la session : la frontière doit recevoir au moins "
                   "une trame."),
        start_nodes=(_node("frontiere", "border", "Frontière", 0, 0), _sensor(500)),
        criteria=(
            Criterion("region", "Plan régional US915", 10, _region("frontiere", "US915")),
            Criterion("sous-bande", "Sous-bande 2", 10, _sub_band("frontiere", 2)),
            Criterion("reception", "Au moins une trame reçue par la frontière", 10,
                      _received_at_least("frontiere", 1)),
        ),
        hints=("La sous-bande ne s'applique qu'aux plans US915 et AU915.",
               "La réception se lit dans le run : liez la frontière à la passerelle du même nom."),
    ),
    Exercise(
        id="latence-frontiere",
        title="Mesurer la latence de remise au LNS",
        statement=("Liez une simulation d'un réseau avec relais : la latence p95 des uplinks remis "
                   "au LNS par la frontière doit être au plus 300 ms."),
        start_nodes=(_node("frontiere", "border", "Frontière", 0, 0),
                     _node("relais-1", "relay", "Relais 1", 1200, 0),
                     _sensor(1500, tx_power_dbm=-10.0, messages=20)),
        criteria=(
            Criterion("latence", "Latence p95 de la frontière <= 300 ms", 20,
                      _latency_p95_at_most("frontiere", 300.0)),
        ),
        hints=("La latence est publiée par passerelle dans le résumé du run.",
               "Le délai d'une trame relayée dépend de la durée d'émission sur le mesh : la commande "
               "« bandwidth » de l'interface mesh (203, 406, 812 ou 1625 kHz) la raccourcit."),
    ),
    Exercise(
        id="au915-sous-bande",
        title="Configurer AU915 sur la sous-bande 5",
        statement=("Configurez la passerelle frontiere sur le plan AU915, sous-bande 5. Liez une "
                   "simulation : la frontiere doit recevoir au moins une trame."),
        start_nodes=(_node("frontiere", "border", "Frontière", 0, 0), _sensor(500)),
        criteria=(
            Criterion("region", "Plan régional AU915", 10, _region("frontiere", "AU915")),
            Criterion("sous-bande", "Sous-bande 5", 10, _sub_band("frontiere", 5)),
            Criterion("reception", "Au moins une trame reçue par la frontière", 10,
                      _received_at_least("frontiere", 1)),
        ),
        hints=("AU915 partage avec US915 la particularité des sous-bandes : la commande "
               "« sub-band » n'a d'effet que sur ces deux plans.",
               "Sous « int lora 0 » : « region AU915 » puis « sub-band 5 ». La réception se lit "
               "dans le run lié à la session."),
    ),
    Exercise(
        id="as923-sans-sous-bande",
        title="Configurer AS923 et son serveur réseau",
        statement=("Configurez la passerelle frontiere sur le plan AS923, puis déclarez son "
                   "serveur réseau : adresse 10.0.0.9, port montant 1700, port descendant 1701. "
                   "Liez une simulation : la frontiere doit recevoir au moins une trame."),
        start_nodes=(_node("frontiere", "border", "Frontière", 0, 0), _sensor(500)),
        criteria=(
            Criterion("region", "Plan régional AS923", 10, _region("frontiere", "AS923")),
            Criterion("serveur", "Serveur réseau 10.0.0.9, ports 1700 et 1701", 10,
                      _lorawan_server("frontiere", "10.0.0.9", 1700, 1701)),
            Criterion("reception", "Au moins une trame reçue par la frontière", 10,
                      _received_at_least("frontiere", 1)),
        ),
        hints=("AS923 n'a pas de sous-bande : la commande « sub-band » y est sans effet, ce plan "
               "ne la porte pas.",
               "La commande complète est « lorawan server <adresse> up-port <n> down-port <n> », "
               "depuis le mode configuration."),
    ),
    Exercise(
        id="relais-bande-large",
        title="Réduire la durée d'émission du mesh",
        statement=("Configurez le relais relais-1 en mode relay avec la bande passante la plus "
                   "large (1625 kHz). Liez une simulation : la frontière doit recevoir par le mesh "
                   "des trames de relais-1."),
        start_nodes=(_node("frontiere", "border", "Frontière", 0, 0),
                     _node("relais-1", "relay", "Relais 1", 1200, 0),
                     _sensor(1500, tx_power_dbm=-10.0)),
        criteria=(
            Criterion("mode", "Relais en mode relay", 10, _mesh_mode("relais-1", "relay")),
            Criterion("bande", "Bande passante du mesh à 1625 kHz", 10,
                      _mesh_bandwidth("relais-1", "1625")),
            Criterion("lien", "Lien mesh observé : relais-1 vers la frontière", 10,
                      _mesh_inbound("frontiere", "relais-1")),
        ),
        hints=("La bande passante se règle sous « int mesh 0 » ; les valeurs acceptées sont 203, "
               "406, 812 et 1625 kHz.",
               "Une bande plus large raccourcit l'émission mais réduit la portée : c'est le "
               "compromis que cet exercice demande d'appliquer à la valeur extrême."),
    ),
    Exercise(
        id="adr-debit-observe",
        title="Faire changer le débit par le serveur, et le prouver",
        statement=("Réglez le plan régional EU868 sur la passerelle frontiere, puis activez l'ADR "
                   "du serveur. Le capteur capteur-1 émet à 150 m, il part de SF12 et n'émet que "
                   "20 messages : est-ce assez pour que le serveur commande un changement ? "
                   "Lancez une simulation et lisez ce que le run a observé — le débit du dernier "
                   "uplink doit être plus rapide que celui du départ. La fenêtre du capteur porte "
                   "de quoi allonger l'observation si rien ne bouge."),
        start_nodes=(_node("frontiere", "border", "Frontière", 0, 0),
                     _sensor(150, messages=20, spreading_factor=12)),
        criteria=(
            Criterion("region", "Plan régional EU868 sur la passerelle frontière", 10,
                      _region("frontiere", "EU868")),
            Criterion("adr", "ADR activé sur la session", 10, _adr_active()),
            Criterion("debit", "Le run observe un débit plus rapide à la fin qu'au départ", 20,
                      _sf_a_baisse("capteur-1")),
        ),
        hints=("Une commande LinkADRReq ne porte que son nom : pour savoir si le débit a changé, "
               "lisez le SF du dernier uplink dans les résultats du run, pas la case ADR.",
               "Le serveur décide sur l'historique des uplinks reçus : à 20 messages la commande "
               "part mais le terminal ne l'applique pas encore. Augmentez le nombre de messages "
               "du capteur (40 suffisent à 150 m) et relancez."),
    ),

)

_BY_ID = {e.id: e for e in EXERCISES}
assert len(_BY_ID) == len(EXERCISES), "identifiants d'exercices en double"


def get(exercise_id: str) -> Optional[Exercise]:
    return _BY_ID.get(exercise_id)


def listing() -> ExerciseList:
    return ExerciseList(items=[
        ExerciseSummary(id=e.id, title=e.title, statement=e.statement,
                        max_points=e.max_points, hints_available=len(e.hints))
        for e in EXERCISES
    ])


def grade(exercise: Exercise, state: State) -> list[tuple[Criterion, bool]]:
    """Évalue chaque critère. Aucun état partiel n'est retenu : un critère est réussi ou non."""
    return [(c, bool(c.check(state))) for c in exercise.criteria]
