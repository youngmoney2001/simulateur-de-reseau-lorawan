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

TERRAIN_ID_PATTERN = r"^[a-z0-9_-]{1,64}$"  # identifiant de relief du catalogue serveur

from pydantic import BaseModel, ConfigDict, Field, model_validator
from lsim.materials import MATERIAL_NAMES

MAX_NODES = 64                         # même borne que le mesh (kMaxGateways côté natif)
# Obstacles par session de l'atelier. Le moteur en accepte 10 000 ; une session d'apprentissage
# n'en demande pas autant, et la borne garde la topologie échangeable en une seule requête.
MAX_OBSTACLES_ATELIER = 200
MASKED = "******"
ID_PATTERN = r"^[a-z][a-z0-9-]{0,31}$"           # identifiant d'équipement
EXERCISE_PATTERN = r"^[a-z0-9][a-z0-9-]{2,63}$"
SESSION_PATTERN = r"^[A-Za-z0-9_-]{8,64}$"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


Mode = Literal["user", "privileged", "config", "config-if"]
NodeKind = Literal["sensor", "relay", "border", "server"]


Region = Literal["EU868", "US915", "AU915", "AS923", "KR920", "IN865", "RU864"]

# Modèles de matériel connus du moteur. Définis ici, couche basse, pour que l'API en
# dérive son tuple au lieu de le recopier — deux listes séparées finissent par diverger.
EnergyProfileName = Literal["rak4631", "sx1262-stm32l072"]

# Modèles de passerelle du catalogue (`lsim.gateway_profiles`), couche basse : l'API en dérive
# sa liste au lieu de la recopier. Un test verrouille la concordance avec le catalogue.
GatewayProfileName = Literal["rak7249", "rak5148", "rak5146-rak5148", "rak7391"]


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
    # Modèle de matériel du capteur. `None` : celui du run — un chantier écrit avant cette
    # distinction garde donc exactement ses chiffres. Deux capteurs de matériel différent
    # ne consomment pas la même chose (mesuré : 10 à 11 % de courant moyen), et les
    # comparer dans un même run est précisément l'intérêt du réglage.
    energy_profile: Optional[EnergyProfileName] = None
    # Classe d'écoute et descentes à l'initiative du réseau. Les deux sont optionnels et
    # quittent le scénario compilé quand ils valent leur défaut : un chantier écrit avant
    # garde ses chiffres.
    device_class: DeviceClass = "A"
    downlink: Optional[DownlinkSettings] = None


# Classe d'écoute d'un capteur. « A » est le défaut et n'est **pas** écrit dans le scénario
# compilé : un chantier écrit avant garde donc ses chiffres et son empreinte.
DeviceClass = Literal["A", "B", "C"]


class DownlinkSettings(_Strict):
    """Le serveur veut envoyer une commande au terminal, sans que le terminal l'ait demandée.

    C'est le seul réglage de l'atelier que la classe d'écoute change vraiment. Un ACK est
    déclenché par un uplink : il tombe dans RX1 ou RX2 quelle que soit la classe. Ici la
    demande naît à un instant que le terminal n'a pas choisi, et la classe décide de la
    fenêtre — donc de l'attente.

    `count` > 1 exige `request_period_s` : sinon toutes les demandes partiraient au même
    instant, ce qui n'a pas de sens et que le moteur refuse.
    """

    count: int = Field(1, ge=1, le=100_000)
    first_request_s: float = Field(0.0, ge=0, le=86_400)
    request_period_s: float = Field(0.0, ge=0, le=86_400)
    # Classe B : 0 = un slot de ping toutes les ~0,96 s, 7 = un slot par période de 128 s.
    # Sans effet en A et en C — il est accepté partout pour qu'un chantier puisse changer de
    # classe sans perdre le réglage, mais il ne pèse que sur B.
    periodicity: int = Field(0, ge=0, le=7)
    clock_drift_ppm: int = Field(0, ge=0, le=1000)

    @model_validator(mode="after")
    def _une_periode_si_plusieurs(self) -> "DownlinkSettings":
        if self.count > 1 and self.request_period_s <= 0:
            raise ValueError("request_period_s doit être strictement positif si count > 1")
        return self


MeshBandwidth = Literal["203", "406", "812", "1625"]      # comme `MeshModel` (scénario)


class GatewaySettings(_Strict):
    """Réglages d'une passerelle exposés dans l'atelier 3D.

    Ce n'est **pas** toute la configuration : le gain d'antenne, la fréquence, le facteur
    d'étalement du mesh et l'arrêt d'interface restent au CLI, et la fenêtre le dit
    explicitement. Le partage est un choix, pas un oubli — ces quatre réglages-là sont ceux
    que réclament les exercices, les autres relèvent du dépannage.

    Les bornes sont exactement celles du CLI (`study_cli.COMMANDS`) : un réglage refusé dans
    la fenêtre l'est donc aussi dans la console, avec le même mot. Les deux chemins écrivent
    au même endroit (`Session.config`), ils ne peuvent pas diverger.
    """

    region: Optional[Region] = None
    sub_band: Optional[int] = Field(None, ge=1, le=8)      # US915 / AU915 seulement
    tx_power_dbm: Optional[float] = Field(None, ge=-10.0, le=30.0)
    mesh_mode: Optional[Literal["relay", "border"]] = None
    mesh_max_hops: Optional[int] = Field(None, ge=1, le=8)
    mesh_bandwidth_khz: Optional[MeshBandwidth] = None
    # Modèle de la passerelle, dans le catalogue `lsim.gateway_profiles`. Il n'appartient pas
    # à la configuration CLI — c'est le matériel — mais il se règle au même endroit, faute de
    # quoi une passerelle posée depuis la palette resterait au seuil de référence sans
    # pouvoir en changer. `None` : aucun modèle appliqué, comportement d'avant.
    gateway_profile: Optional[GatewayProfileName] = None


class Node(_Strict):
    id: str = Field(pattern=ID_PATTERN)
    kind: NodeKind
    name: str = Field(min_length=1, max_length=64)
    x_m: float = Field(ge=-1_000_000, le=1_000_000)
    y_m: float = Field(ge=-1_000_000, le=1_000_000)
    sensor: Optional[SensorSettings] = None      # seulement pour un capteur
    # Modèle de passerelle du catalogue. `None` : le run n'en applique aucun, et le seuil de
    # réception reste la référence du moteur — le comportement d'avant. Mesuré : un modèle
    # qui publie son point de sensibilité décale le seuil de 3 dB, et un run à la limite
    # passe alors de 0 à 20 trames reçues sur 20. Les fiches qui ne publient pas le point
    # (SF et bande) ne décalent rien : le catalogue le dit, l'interface doit le redire.
    gateway_profile: Optional[GatewayProfileName] = None

    @model_validator(mode="after")
    def _gateway_profile_only_on_gateways(self) -> "Node":
        if self.gateway_profile is not None and self.kind not in ("relay", "border"):
            # Le nom du modèle fautif : sans lui, l'apprenant voit un refus sans savoir
            # quel équipement ni quelle valeur le cause.
            raise ValueError(
                f"modèle de passerelle « {self.gateway_profile} » sur un équipement "
                f"qui n'est pas une passerelle (kind={self.kind})")
        return self

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
    # Réglages exposés dans la fenêtre de configuration, relus tels qu'ils sont.
    # `None` sur un capteur ou un serveur : rien à exposer, pas « réglages par défaut ».
    gateway: Optional[GatewaySettings] = None


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


class Position(_Strict):
    """Position d'un équipement sur le plan, en mètres."""

    x_m: float = Field(ge=-1_000_000, le=1_000_000)
    y_m: float = Field(ge=-1_000_000, le=1_000_000)


class SessionSummary(_Strict):
    session_id: str = Field(pattern=SESSION_PATTERN)
    exercise_id: Optional[str] = Field(default=None, pattern=EXERCISE_PATTERN)
    nodes: int = Field(ge=0, le=MAX_NODES)
    idle_s: int = Field(ge=0)              # secondes depuis la dernière activité


# --- Environnement radio : obstacles, shadowing, hauteurs d'antennes --------------------------
# Modélisés par le moteur (UIT-R P.2040-4 pour les matériaux, tirage log-normal pour le
# shadowing) mais jusque-là accessibles par le YAML seul. `None` veut dire « l'utilisateur n'a
# rien réglé », et le scénario compilé n'émet alors aucun bloc `environment` : un scénario
# écrit avant garde ses chiffres **et** son empreinte.

class Obstacle(_Strict):
    """Une boîte qui atténue. Soit une atténuation saisie, soit un matériau + une épaisseur.

    L'atténuation est le chemin principal : à 868 MHz, 13 des 15 matériaux du catalogue sont
    hors de la plage documentée du Tableau 3 de l'UIT-R P.2040-4, et la perte est alors
    extrapolée. Saisir ses dB reste la façon honnête de procéder ; le matériau est une
    commodité, et son caractère extrapolé est exposé par l'API.
    """

    x_min_m: float
    y_min_m: float
    x_max_m: float
    y_max_m: float
    height_m: float = Field(12.0, gt=0, le=1000)
    attenuation_db: float = Field(0.0, ge=0, le=200)
    material: Optional[str] = Field(None, max_length=32)
    thickness_m: Optional[float] = Field(None, gt=0, le=10)

    @model_validator(mode="after")
    def _box_not_empty(self) -> "Obstacle":
        if not (self.x_min_m < self.x_max_m and self.y_min_m < self.y_max_m):
            raise ValueError("emprise de l'obstacle vide (min doit être < max)")
        if self.material is None:
            if self.thickness_m is not None:
                raise ValueError("épaisseur sans matériau")
        else:
            if self.thickness_m is None:
                raise ValueError("matériau sans épaisseur")
            if "attenuation_db" in self.model_fields_set:
                raise ValueError("atténuation et matériau s'excluent")
        return self


class MaterialCalibration(_Strict):
    """Perte d'un matériau **mesurée**, en dB par mètre, à la place d'UIT-R P.2040-4.

    À 868 MHz, 12 des 15 matériaux du catalogue sortent de la plage documentée du Tableau 3 :
    la valeur de la table est alors extrapolée, et le moteur le dit. Une mesure vaut mieux
    qu'une extrapolation — encore faut-il pouvoir la déclarer depuis l'atelier, sinon la
    seule issue reste d'éditer le YAML à la main.

    `provenance` est obligatoire, pour la même raison que sur un relevé d'énergie : un
    chiffre sans origine se présente comme une donnée du moteur. C'est la contrepartie de
    la mention « extrapolé » affichée sur la table — taire l'origine dans les deux sens
    reviendrait au même.
    """

    loss_db_per_m: float = Field(ge=0, le=200)
    provenance: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def _provenance_non_vide(self) -> "MaterialCalibration":
        if not self.provenance.strip():
            raise ValueError("provenance : d'où vient cette mesure ?")
        return self


class EnvironmentSettings(_Strict):
    """Environnement radio d'une session.

    `shadowing_sigma_db` : écart-type du tirage log-normal, un tirage par dispositif. Mesuré
    à 10 km SF10 sans obstacle : à sigma 4 dB, 37 tirages sur 40 restent entendus ; à 8 dB,
    30 sur 40. Les hauteurs comptent aussi : face à un mur de 12 m, une passerelle à 40 m
    reçoit encore là où une passerelle à 15 m a tout perdu.
    """

    shadowing_sigma_db: float = Field(0.0, ge=0.0, le=30.0)
    gateway_height_m: float = Field(15.0, gt=0, le=1000)
    device_height_m: float = Field(1.5, gt=0, le=1000)
    obstacles: list[Obstacle] = Field(default_factory=list, max_length=MAX_OBSTACLES_ATELIER)
    # Pertes mesurées par matériau, qui remplacent P.2040-4 pour les obstacles concernés.
    # Vide : la table s'applique, exactement comme avant.
    material_calibration: dict[str, MaterialCalibration] = Field(
        default_factory=dict, max_length=len(MATERIAL_NAMES))

    @model_validator(mode="after")
    def _materiaux_connus(self) -> "EnvironmentSettings":
        # Refuser un matériau inconnu ici, et non au compile : une faute de frappe
        # (« beton » pour « concrete ») produirait sinon une calibration silencieusement
        # sans effet, et le mur resterait sur une valeur extrapolée.
        for nom in self.material_calibration:
            if nom not in MATERIAL_NAMES:
                raise ValueError(f"material_calibration : matériau inconnu : {nom!r}")
        return self

    def est_vierge(self) -> bool:
        """Rien n'a été réglé : le scénario compilé n'émet alors aucun bloc `environment`."""
        return (not self.obstacles and self.shadowing_sigma_db == 0.0
                and self.gateway_height_m == 15.0 and self.device_height_m == 1.5
                and not self.material_calibration)


class EnvironmentChoice(_Strict):
    """Réglage de l'environnement. Seuls les champs présents sont appliqués : une interface
    qui n'affiche pas les hauteurs ne doit pas pouvoir les remettre à leur défaut."""

    shadowing_sigma_db: Optional[float] = Field(None, ge=0.0, le=30.0)
    gateway_height_m: Optional[float] = Field(None, gt=0, le=1000)
    device_height_m: Optional[float] = Field(None, gt=0, le=1000)
    obstacles: Optional[list[Obstacle]] = Field(None, max_length=MAX_OBSTACLES_ATELIER)
    material_calibration: Optional[dict[str, MaterialCalibration]] = Field(
        None, max_length=len(MATERIAL_NAMES))

    @model_validator(mode="after")
    def _materiaux_connus(self) -> "EnvironmentChoice":
        if self.material_calibration:
            for nom in self.material_calibration:
                if nom not in MATERIAL_NAMES:
                    raise ValueError(f"material_calibration : matériau inconnu : {nom!r}")
        return self


class SessionList(_Strict):
    items: list[SessionSummary] = Field(max_length=8)   # au plus 8 par compte


class SessionTopology(_Strict):
    session_id: str = Field(pattern=SESSION_PATTERN)
    nodes: list[Node] = Field(max_length=MAX_NODES)
    states: list[NodeState] = Field(max_length=MAX_NODES)
    # Relief appliqué aux runs de cette session. `None` : le relief n'a pas été choisi, ce qui
    # n'est pas la même chose que « terrain plat » — le moteur ne simule rien de particulier,
    # et l'atelier doit pouvoir dire laquelle des deux situations se présente.
    terrain_id: Optional[str] = Field(default=None, pattern=TERRAIN_ID_PATTERN)
    # ADR du serveur (LinkADRReq) : demande de l'utilisateur, et ce qu'il en est.
    # `adr` dit ce qui est **demandé**, `adr_possible` et `adr_raison` ce que la session peut.
    # Les porter séparément évite qu'une session qui veut l'ADR se présente comme le simulant.
    adr: bool = False
    adr_possible: bool = False
    adr_raison: str = ""
    # Jointure OTAA et trames confirmées : même forme que l'ADR, et pour la même raison —
    # chacun dit ce qui est **demandé**, et `*_possible` / `*_raison` ce que le run fera.
    # Ce sont des options de protocole du run (`RunCreate.protocol`), pas des réglages
    # d'équipement : le moteur les applique à tous les dispositifs, ou à aucun.
    join: bool = False
    join_possible: bool = False
    join_raison: str = ""
    confirmed: bool = False
    confirmed_possible: bool = False
    confirmed_raison: str = ""
    # Environnement radio de la session : obstacles, shadowing, hauteurs d'antennes. Porté
    # par la topologie parce que le plan le dessine — il se lit au même endroit que les
    # équipements qu'il sépare.
    environment: EnvironmentSettings = Field(default_factory=EnvironmentSettings)
    # Historique annuler/rétablir. Il voyage avec la topologie, et non dans une route à
    # part : ainsi **chaque** réponse met les boutons à jour, et non seulement celles
    # d'annuler. `undo_label` nomme l'opération qui serait annulée — un « annuler » sans
    # objet est un bouton qu'on n'ose pas presser.
    #
    # L'historique vit côté serveur parce que le CLI y vit aussi : annuler « region US915 »
    # restaure la configuration de l'équipement, pas seulement la case que l'interface en
    # montrait.
    can_undo: bool = False
    can_redo: bool = False
    undo_label: str = Field("", max_length=120)
    redo_label: str = Field("", max_length=120)


class AdrChoice(_Strict):
    """Demande d'activation de l'ADR du serveur sur une session.

    Le client n'indique que son souhait : c'est le serveur qui sait si la topologie le permet
    (une seule passerelle, pas de relais, un plan régional), et qui dit pourquoi sinon.
    """

    adr: bool = False


class ProtocoleChoice(_Strict):
    """Demande de réglage protocolaire d'une session : jointure OTAA, trames confirmées.

    Comme `AdrChoice`, le client n'indique que son souhait. La jointure et l'ADR s'excluent
    (le moteur refuse le couple — `mac_loop.check_closed_loop`), et c'est le serveur qui le
    dit, avec la raison, plutôt que de laisser le run échouer.
    """

    join: bool = False
    confirmed: bool = False


class TerrainChoice(_Strict):
    """Choix du relief d'une session. Le client ne fournit jamais de chemin : le relief est
    résolu dans le catalogue du serveur, et un identifiant inconnu est refusé."""

    terrain_id: Optional[str] = Field(default=None, pattern=TERRAIN_ID_PATTERN)


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
    "study_position": Position,
    "study_session_list": SessionList,
    "study_hint_request": HintRequest,
    "study_hint": HintOut,
    "study_attempt_list": AttemptList,
    # Environnement radio de la session : l'atelier le dessine, le schéma le publie.
    "study_environment": EnvironmentSettings,
    "study_environment_choice": EnvironmentChoice,
    "study_obstacle": Obstacle,
    # Une mesure par matériau, publiée pour elle-même : l'atelier la saisit seule, sans
    # redéposer les murs.
    "study_material_calibration": MaterialCalibration,
    # Le reste du contrat, publié pour lui-même : un client qui lit un nœud, un état
    # résumé, un critère ou un rebond de passerelle doit pouvoir le valider sans
    # reconstruire la session entière.
    "study_node": Node,
    "study_node_state": NodeState,
    "study_gateway_settings": GatewaySettings,
    "study_downlink_settings": DownlinkSettings,
    "study_gateway_link": GatewayLink,
    "study_cli_error": CliError,
    "study_session_summary": SessionSummary,
    "study_adr_choice": AdrChoice,
    "study_protocole_choice": ProtocoleChoice,
    "study_terrain_choice": TerrainChoice,
    "study_exercise_summary": ExerciseSummary,
    "study_criterion_result": CriterionResult,
    "study_attempt_out": AttemptOut,
}


def schemas() -> dict[str, dict]:
    return {name: model.model_json_schema() for name, model in MODELS.items()}
