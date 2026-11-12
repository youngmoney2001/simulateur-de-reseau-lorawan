"""Contrat d'API moteur ↔ navigateur (v1) : modèles de requêtes, réponses et événements.

Ce module ne sert aucune requête. Il définit les formes de données échangées, et les schémas JSON
publiés dans `schemas/api/v1/` (générés par `write_schemas`, vérifiés par les tests). Le texte
normatif est dans `docs/API_CONTRACT.md`.

Principes :
- Le navigateur ne lit jamais de fichier du serveur : le relief est désigné par `terrain_id`, résolu
  dans un catalogue côté serveur (un `terrain` avec chemin est refusé dans le scénario d'API).
- Aucune clé de session ou de jointure ne figure dans une réponse.
- Les réponses de liste sont paginées ; aucune réponse n'excède `MAX_BODY_BYTES`.
- L'horloge de simulation est une lecture du journal d'événements (pas de calcul côté navigateur).
"""

from __future__ import annotations

import json
from pathlib import Path
import typing
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from lsim import study_contract as _study_constants
from lsim.energy_report import profile_name
from lsim.plan import Plan, get_plan, plan_names
from lsim.scenario import ScenarioModel

API_VERSION = "v1"
MAX_BODY_BYTES = 262_144                 # corps de requête et réponses JSON non paginées
MAX_TRACE_EVENTS_PER_RUN = 200_000       # au-delà, le run est refusé (pas tronqué en silence)
MAX_PAGE_SIZE = 500                      # événements par page
MAX_HOPS_PER_EVENT = 8                   # appareil -> passerelle -> serveur -> passerelle -> appareil...
# Dérivé du `Literal` de la couche basse : une seule liste, donc pas de divergence.
ENERGY_PROFILES = typing.get_args(_study_constants.EnergyProfileName)
GATEWAY_PROFILES = typing.get_args(_study_constants.GatewayProfileName)
# Défini dans `study_contract`, couche basse : `api_contract` l'importe déjà, l'inverse
# créerait un cycle.
TERRAIN_ID_PATTERN = _study_constants.TERRAIN_ID_PATTERN

RunState = Literal["queued", "running", "done", "failed", "cancelled"]
ProblemCode = Literal[
    "validation_error", "not_found", "limit_exceeded", "terrain_not_allowed",
    "run_failed", "conflict", "unsupported_region", "unauthorized", "rate_limited",
    # « Rien à annuler » est un état de la session, pas une faute de l'utilisateur : le code le
    # dit, le message reste lisible, et l'interface n'a pas à deviner d'après le seul 409.
    "nothing_to_undo", "nothing_to_redo",
]
EventKind = Literal[
    "join_request", "join_accept", "uplink", "ack", "downlink",
    "lost_sensitivity", "lost_collision", "rx_window_missed", "mesh_hop", "mesh_downlink_hop",
    "mac_request", "mac_answer",
]
HopOutcome = Literal["delivered", "lost_sensitivity", "lost_collision", "lost_half_duplex",
                     "not_listened", "sent", "suppressed", "lost_mesh"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ApiScenario(ScenarioModel):
    """Scénario accepté par l'API : comme `ScenarioModel`, sans lecture de fichier serveur."""

    @model_validator(mode="after")
    def _no_server_files(self) -> "ApiScenario":
        if self.environment is not None and self.environment.terrain is not None:
            raise ValueError("terrain : utiliser un identifiant de catalogue, pas un chemin")
        return self


class Problem(_Strict):
    """Erreur au format problème (code stable, message lisible, champ éventuel)."""

    code: ProblemCode
    message: str = Field(max_length=500)
    field: Optional[str] = Field(default=None, max_length=200)


class ValidateResponse(_Strict):
    valid: bool
    scenario_sha256: Optional[str] = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    problems: list[Problem] = Field(default_factory=list, max_length=50)


class ProtocolOptionsIn(_Strict):
    """Comportement applicatif des événements (hors moteur radio) : voir `lsim.trace_events`."""

    join: bool = False                 # première émission de chaque dispositif = join-request
    confirmed_uplinks: bool = False    # uplinks de données confirmés (ACK attendu)
    downlink_every: int = Field(0, ge=0, le=10_000)  # 0 : aucune charge ; N : une par N uplinks
    downlink_payload_bytes: int = Field(10, ge=0, le=242)  # charge des downlinks de données
    gateway_tx_power_dbm: float = Field(14.0, ge=-10.0, le=27.0)  # downlink, réciprocité
    device_antenna_gain_dbi: float = Field(0.0, ge=-10.0, le=10.0)
    device_rx_offset_db: float = Field(0.0, ge=-30.0, le=40.0)  # écart du récepteur réel


class ValidateRequest(_Strict):
    scenario: ApiScenario
    terrain_id: Optional[str] = Field(default=None, pattern=TERRAIN_ID_PATTERN)
    # Optionnel : sans lui, seules les règles propres au scénario sont vérifiées (charge montante).
    protocol: Optional[ProtocolOptionsIn] = None


class RunCreate(_Strict):
    scenario: ApiScenario
    terrain_id: Optional[str] = Field(default=None, pattern=TERRAIN_ID_PATTERN)
    energy_profile: Optional[Literal["rak4631", "sx1262-stm32l072"]] = None
    protocol: ProtocolOptionsIn = ProtocolOptionsIn()


class TerrainInfo(_Strict):
    id: str = Field(pattern=TERRAIN_ID_PATTERN)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class TerrainList(_Strict):
    items: list[TerrainInfo] = Field(max_length=200)


class RunStatus(_Strict):
    run_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,64}$")
    state: RunState
    progress: float = Field(ge=0.0, le=1.0)
    scenario_sha256: Optional[str] = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    trace_events: Optional[int] = Field(default=None, ge=0, le=MAX_TRACE_EVENTS_PER_RUN)
    problem: Optional[Problem] = None


class Totals(_Strict):
    sent: int = Field(ge=0)
    received: int = Field(ge=0)
    lost_sensitivity: int = Field(ge=0)
    lost_collision: int = Field(ge=0)
    airtime_ns: int = Field(ge=0)
    lost_gateway_busy: int = Field(0, ge=0)  # reçue pendant une émission passerelle
    # Mesh seulement : décodée par une passerelle, mais non remise au LNS par le mesh.
    # Absent hors mesh. sent = received + lost_sensitivity + lost_collision + lost_gateway_busy + lost_mesh.
    lost_mesh: Optional[int] = Field(default=None, ge=0)


class GatewayLoadOut(_Strict):
    busy_ns: int = Field(ge=0)
    peak_concurrent: int = Field(ge=0)
    observation_ns: int = Field(ge=0)
    utilization: float = Field(ge=0.0, le=1.0)


class DeviceRowOut(_Strict):
    device_index: int = Field(ge=0)
    group: str = Field(max_length=64)
    index_in_group: int = Field(ge=0)
    x_m: float
    y_m: float
    spreading_factor: int = Field(ge=5, le=12)
    # Facteur d'étalement **à la fin du run**. Il ne diffère de `spreading_factor` que si le
    # serveur a commandé un changement de débit (ADR) et que le terminal l'a appliqué — c'est
    # donc la seule pièce qui réponde à « pourquoi ce capteur est-il passé de SF12 à SF7 ? ».
    #
    # Absent quand le run ne porte pas d'enregistrements d'émission (chemin multi-passerelles,
    # où l'ADR n'est de toute façon pas simulé) : un champ absent plutôt qu'une valeur qui
    # recopierait `spreading_factor` en laissant croire à une observation.
    final_spreading_factor: Optional[int] = Field(default=None, ge=5, le=12)
    # Puissance d'émission **appliquée** par la boucle fermée, en indices de puissance.
    # Même règle que le débit : ces champs n'existent que si le run les a observés, donc
    # absents hors ADR, plutôt que recopiés en laissant croire à une observation.
    #
    # La réduction affichable est `(final_power_index - power_index) * power_step_db`
    # décibels. C'est une **réduction**, jamais une puissance absolue : la base est la
    # puissance configurée du dispositif, et non la PIRE du plan (mesuré : un capteur réglé
    # sur 14 dBm émet le RSSI de 14 dBm à l'index 0, pas celui de 16 dBm).
    power_index: Optional[int] = Field(default=None, ge=0, le=15)
    final_power_index: Optional[int] = Field(default=None, ge=0, le=15)
    power_step_db: Optional[float] = Field(default=None, gt=0, le=10)
    # Canaux que le serveur a **laissés** au terminal à la fin du run. Même règle que le
    # débit et la puissance : ces champs n'existent que si la boucle fermée les a observés,
    # donc absents ailleurs, plutôt que recopiés depuis la configuration de départ — ce qui
    # publierait un plan de canaux que le serveur n'a pas arrêté.
    #
    # `enabled_channels` : canaux actifs. `channel_dr_masks` : canal -> masque des débits
    # DR0..DR7 (bit k = DRk admis), publié avec des clés textuelles, la JSON n'ayant pas de
    # clé entière. Un canal peut être défini sans être actif : c'est `enabled_channels` qui
    # dit ce que la trame suivante empruntera réellement.
    enabled_channels: Optional[list[int]] = Field(default=None, max_length=16)
    channel_dr_masks: Optional[dict[int, int]] = None
    sent: int = Field(ge=0)
    received: int = Field(ge=0)
    lost_sensitivity: int = Field(ge=0)
    lost_collision: int = Field(ge=0)
    airtime_ns: int = Field(ge=0)
    lost_mesh: Optional[int] = Field(default=None, ge=0)  # mesh seulement (voir Totals)
    energy_per_message_j: Optional[float] = None
    average_current_ua: Optional[float] = None
    # Descentes à l'initiative du réseau, **pour ce dispositif**. `None` : il n'en a demandé
    # aucune, ou le chemin de calcul ne les porte pas.
    #
    # `downlink_latency_s` est la moyenne des attentes de ses propres descentes. Jointe à
    # l'instant de la demande, que détient le scénario, elle dit **quand** la passerelle a
    # émis — c'est ce qui permet d'animer l'attente au lieu de la résumer en un chiffre.
    # La prudence est de mise : cette date d'arrivée est reconstituée de deux grandeurs
    # calculées par le run, ce n'est pas un événement lu dans la trace.
    downlink_delivered: Optional[int] = Field(default=None, ge=0)
    downlink_latency_s: Optional[float] = Field(default=None, ge=0.0)

    @model_validator(mode="after")
    def _latence_seulement_si_livree(self) -> "DeviceRowOut":
        if self.downlink_latency_s is not None and self.downlink_delivered is None:
            raise ValueError("downlink_latency_s exige downlink_delivered")
        return self


class MeshInboundOut(_Strict):
    """Lien mesh observé : sauts livrés depuis `from_gateway` vers cette passerelle."""

    from_gateway: str = Field(max_length=64)
    delivered: int = Field(ge=0)


class GatewayReportOut(_Strict):
    """Passerelle d'un run multi-passerelles : trames reçues et charge de réception."""

    name: str = Field(max_length=64)
    received: int = Field(ge=0)
    lost_sensitivity: int = Field(ge=0)
    lost_collision: int = Field(ge=0)
    lost_gateway_busy: int = Field(ge=0)
    audible_frames: int = Field(ge=0)
    busy_ns: int = Field(ge=0)
    peak_concurrent: int = Field(ge=0)
    observation_ns: int = Field(ge=0)
    # Mesh seulement (absents sinon) : émissions de la passerelle sur la bande mesh, uplinks et
    # descentes. Les pertes sont comptées sur l'émetteur ; les passes uplink et descente ne
    # partagent pas le temps d'antenne (voir docs/API_CONTRACT.md).
    mesh_transmissions: Optional[int] = Field(default=None, ge=0)
    mesh_busy_ns: Optional[int] = Field(default=None, ge=0)
    mesh_lost_collision: Optional[int] = Field(default=None, ge=0)
    mesh_lost_half_duplex: Optional[int] = Field(default=None, ge=0)
    mesh_suppressed: Optional[int] = Field(default=None, ge=0)
    # Indicateurs de trace (absents si aucune mesure). Latence : uplinks de donnée remis au LNS
    # par cette passerelle, de l'émission à la remise au LNS (saut mesh inclus).
    latency_samples: int = Field(0, ge=0)
    latency_p50_ms: Optional[float] = Field(default=None, ge=0)
    latency_p95_ms: Optional[float] = Field(default=None, ge=0)
    mesh_inbound: Optional[list[MeshInboundOut]] = Field(default=None, max_length=64)


class DutyCycleOut(_Strict):
    """Rapport cyclique d'un groupe : la limite réglementaire et sa source, pas le verdict.

    Le verdict est laissé à l'interface, et pour une raison mesurée : la limite se compare à une
    occupation **moyennée sur la fenêtre du texte réglementaire** (une heure chez ETSI), alors que
    le run s'observe sur sa propre fenêtre. Publier ici « conforme » ou « non conforme » donnerait
    à une comparaison de deux fenêtres différentes l'autorité du serveur. On publie donc la
    limite, sa source, la fréquence et la région : les deux termes de la comparaison, rien de plus.

    `limit` est **absente** (clé retirée, convention `exclude_none` de l'API) quand le plan
    régional ne déclare aucune sous-bande — cinq régions sur huit sont dans ce cas (US915,
    AU915, AS923, KR920, IN865). Ce n'est pas une limite permissive, c'est une limite absente :
    l'interface ne doit pas la traduire par « 100 % ».
    """

    group: str = Field(min_length=1, max_length=64)
    region: Optional[str] = Field(default=None, max_length=16)
    channel_freq_hz: int = Field(gt=0)
    eirp_dbm: float
    # None : aucune sous-bande déclarée pour cette fréquence dans ce plan.
    limit: Optional[float] = Field(default=None, gt=0.0, le=1.0)
    # Source officielle du plan régional ; absente seulement sans région déclarée.
    source: Optional[str] = None


class DownlinkOut(_Strict):
    """Descentes **à l'initiative du réseau** : le serveur veut envoyer à un instant donné.

    Ce n'est pas un ACK. Un ACK est déclenché par un uplink : il tombe dans RX1 ou RX2, et la
    classe d'écoute n'y change rien. Ici la demande naît au moment choisi par le réseau, et
    c'est la classe qui décide de la fenêtre — donc de l'attente. C'est la seule grandeur du
    simulateur que la classe détermine à elle seule.

    `latency_mean_s` / `latency_max_s` : délai entre l'instant voulu et l'instant d'émission.
    """

    requested: int = Field(ge=0)
    delivered: int = Field(ge=0)
    latency_mean_s: Optional[float] = Field(default=None, ge=0.0)
    latency_max_s: Optional[float] = Field(default=None, ge=0.0)

    @model_validator(mode="after")
    def _delivered_at_most_requested(self) -> "DownlinkOut":
        if self.delivered > self.requested:
            raise ValueError("delivered ne peut pas dépasser requested")
        return self


class SessionRunOut(_Strict):
    """Un run lancé depuis un chantier, avec de quoi le reconnaître et le comparer.

    Les grands nombres (`pdr`, `sent`, `received`, `downlink`) ne sont présents que si le run
    est **terminé** : un run en cours n'a pas de résultat, et publier des zéros le ferait
    croire mesuré à zéro plutôt que pas encore mesuré.
    """

    run_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,64}$")
    state: RunState
    seed: Optional[int] = Field(default=None, ge=0)
    # Horodatage POSIX écrit par le serveur au moment de la création du run.
    created_at: Optional[int] = Field(default=None, ge=0)
    pdr: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    sent: Optional[int] = Field(default=None, ge=0)
    received: Optional[int] = Field(default=None, ge=0)
    energy_profile: Optional[str] = None
    # Attente des descentes réseau : présente seulement si le run en a planifié. Un run sans
    # commande du serveur n'a pas d'attente, et `0` dirait « livré instantanément ».
    downlink: Optional[DownlinkOut] = None
    problem: Optional[Problem] = None
    # Liaisons équipement <-> passerelle de ce run. Elles sont nécessaires pour **le revoir**
    # tel qu'il a été mesuré : le plan les trace, et sans elles un run rouvert afficherait
    # des équipements sans jamais dire qui a entendu qui.
    links: list[_study_constants.GatewayLink] = Field(default_factory=list,
                                                      max_length=_study_constants.MAX_NODES)


class SessionRunList(_Strict):
    """Les runs d'un chantier, du plus récent au plus ancien.

    Borné à `MAX_COMPILED` (16) : c'est la profondeur de ce que le chantier rattache, et non
    une limite d'affichage. Un run plus ancien n'est pas effacé, il n'est plus rattaché.
    """

    items: list[SessionRunOut] = Field(max_length=32)


class RunSummary(_Strict):
    """Résumé d'un run. Exactement un des deux champs : `gateway` (mono-passerelle, champ présent
    depuis la v1) ou `gateways` (multi-passerelles, ajouté en v1 ; `gateway` est alors absent)."""

    run_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,64}$")
    scenario_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    seed: int = Field(ge=0)
    totals: Totals
    pdr: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    gateway: Optional[GatewayLoadOut] = None
    gateways: Optional[list[GatewayReportOut]] = Field(default=None, max_length=64)
    energy_profile: Optional[str] = None
    # Rapport cyclique par groupe. Absent si aucun groupe ne déclare de région : c'est le
    # cas de tout scénario écrit avant l'introduction du champ, dont l'empreinte ne bouge pas.
    duty_cycle: Optional[list[DutyCycleOut]] = Field(default=None, max_length=64)
    # Réceptions par couple (dispositif, passerelle) : `rx_matrix[d][g]` trames décodées par la
    # passerelle `g` pour le dispositif `d`, l'ordre des colonnes étant celui de `gateways`.
    #
    # C'est la seule grandeur publiée qui dise « qui a entendu qui ». L'événement servi ne
    # porte que la **meilleure** passerelle : s'en servir pour tracer les liaisons radio
    # dessinerait un trait là où trois passerelles ont décodé.
    #
    # Dispositifs dans l'ordre de `GET /runs/{id}/devices` (`device_index`), passerelles dans
    # celui de `gateways` — deux ordres que rien ne garantit égaux, d'où leur mention ici.
    # Absent sur un run mono-passerelle : l'unique colonne ne dirait rien de plus que le PDR.
    # Une ligne par dispositif (jusqu'à `MAX_DEVICES`), une colonne par passerelle
    # (jusqu'à `MAX_GATEWAYS`) : borner les lignes à 64 casserait tout run un peu peuplé.
    rx_matrix: Optional[list[list[int]]] = None
    # Nature des événements du run, comptée **à la fin du calcul** — quand ils sont encore
    # en mémoire, donc exacte et sans borne de lecture.
    #
    # Pourquoi un compte plutôt qu'un parcours à la demande : les événements sont stockés en
    # JSON, sans colonne de nature. Les recompter à la demande obligerait à relire les corps,
    # donc à borner — et un compte borné noterait un exercice sur un run tronqué sans le dire.
    #
    # C'est ce qui permet de répondre à « les quatre capteurs ont-ils obtenu leur join-accept ? »
    # par ce que le run a produit, jamais par ce que le formulaire a demandé.
    event_kinds: Optional[dict[str, int]] = Field(default=None, max_length=32)
    # Descentes à l'initiative du réseau. Absent si le run n'en a planifié aucune : un objet
    # de zéros dirait « aucune descente livrée », ce qui serait faux d'un run qui n'en a
    # jamais demandé. Voir `DownlinkOut`.
    downlink: Optional[DownlinkOut] = None

    @model_validator(mode="after")
    def _one_load_shape(self) -> "RunSummary":
        if (self.gateway is None) == (self.gateways is None):
            raise ValueError("exactement un de gateway ou gateways")
        return self

    @model_validator(mode="after")
    def _rx_matrix_carree(self) -> "RunSummary":
        """Une colonne par passerelle, ou pas de matrice du tout.

        Le tracé lit `rx_matrix[d][g]` à l'aveugle, en supposant qu'il y a autant de colonnes
        que de passerelles. Laisser passer une matrice bancale produirait des traits décalés
        d'un cran — une erreur impossible à voir sur la carte, et donc impossible à corriger.
        """
        if self.rx_matrix is None:
            return self
        if self.gateways is None:
            raise ValueError("rx_matrix sans gateways : une colonne unique ne dirait rien de plus")
        attendu = len(self.gateways)
        for d, ligne in enumerate(self.rx_matrix):
            if len(ligne) != attendu:
                raise ValueError(
                    f"rx_matrix[{d}] : {len(ligne)} colonnes pour {attendu} passerelles")
        return self


class DevicePage(_Strict):
    items: list[DeviceRowOut] = Field(max_length=MAX_PAGE_SIZE)
    next_cursor: Optional[int] = Field(default=None, ge=0)


class Hop(_Strict):
    """Un saut de la trame : émetteur -> récepteur, avec le résultat sur ce saut."""

    from_id: str = Field(max_length=64)
    to_id: str = Field(max_length=64)
    t_ns: int = Field(ge=0)
    freq_hz: int = Field(gt=0)
    dr: Optional[int] = Field(default=None, ge=0, le=15)
    rssi_dbm: Optional[float] = None
    outcome: HopOutcome


class TraceEvent(_Strict):
    seq: int = Field(ge=0)
    t_ns: int = Field(ge=0)
    kind: EventKind
    device_index: int = Field(ge=0)
    gateway_index: int = Field(default=0, ge=0)
    hops: list[Hop] = Field(default_factory=list, max_length=MAX_HOPS_PER_EVENT)
    outcome: str = Field(max_length=64)
    frame: Optional[dict] = Field(default=None)  # trame LoRaWAN reconstruite (frame_view)


class TracePage(_Strict):
    items: list[TraceEvent] = Field(max_length=MAX_PAGE_SIZE)
    next_cursor: Optional[int] = Field(default=None, ge=0)


class RegionInfo(_Strict):
    """Paramètres d'un plan régional, pour les panneaux de configuration (lecture seule)."""

    name: str = Field(max_length=16)
    uplink_channels_hz: list[int] = Field(max_length=72)
    data_rates: list[tuple[int, int, int]] = Field(max_length=16)  # (SF, BW kHz, DNONLY)
    rx2_hz: int = Field(gt=0)
    rx2_datr: str = Field(max_length=16)
    max_payload_by_dr: dict[str, int]
    sub_bands: bool


class PeriodiciteInfo(_Strict):
    """Une périodicité de ping slot (classe B) : 0 à 7, du plus bavard au plus rare.

    L'intervalle entre deux slots vient du moteur, pas d'une table recopiée : la période de
    balise est de 128 s, et une périodicité `k` ouvre `2**(7 - k)` slots par période.
    """

    value: int = Field(ge=0, le=7)
    slots_par_periode: int = Field(ge=1)
    intervalle_s: float = Field(gt=0)


class DeviceClassInfo(_Strict):
    """Une classe d'écoute, **et ce qu'elle change** — ou ne change pas.

    `change` est le point sensible. Un ACK, une réponse MAC ou une charge descendante
    périodique sont déclenchés par un uplink : ils tombent dans RX1 ou RX2 quelle que soit
    la classe. La classe ne pèse que sur les descentes à l'initiative du réseau. Le dire ici
    évite un sélecteur qui laisserait croire à un réglage général.

    `ordre` : rang indicatif d'attente, pour que l'interface puisse avertir. La classe B
    n'est pas « meilleure que A » : selon sa périodicité elle l'encadre. C'est `periodicity`
    qui décide, et l'intervalle est servi avec.
    """

    name: str = Field(max_length=1, pattern=r"^[ABC]$")
    label: str = Field(max_length=128)
    # Quand la fenêtre est ouverte, en une phrase. Vide de tout chiffre : les chiffres sont
    # mesurés par le run, pas promis par le catalogue.
    ouverture: str = Field(max_length=256)
    # Ce que la classe ne change **pas** : c'est le garde-fou contre un réglage qu'on croirait
    # général. Renseigné ici plutôt que dans l'interface, pour que les deux disent la même chose.
    ne_change_pas: str = Field(max_length=256)
    periodicites: tuple[PeriodiciteInfo, ...] = ()      # classe B seulement


class DeviceClassList(_Strict):
    classes: list[DeviceClassInfo] = Field(max_length=8)
    # Rappel servi avec la liste : une classe plus « réactive » coûte l'écoute, donc
    # l'énergie. Sans cette phrase, choisir C paraîtrait gratuit.
    cout: str = Field(max_length=256)


def classes_ecoute() -> DeviceClassList:
    """Les classes d'écoute et ce qu'elles changent, depuis le moteur.

    Source unique : `lsim.class_b` pour la période de balise et le nombre de slots. Rien
    n'est recopié, donc rien ne peut dériver du moteur.
    """
    from lsim.class_b import BEACON_PERIOD_NS

    periode_s = BEACON_PERIOD_NS / 1e9
    periodicites = tuple(
        PeriodiciteInfo(value=k, slots_par_periode=2 ** (7 - k),
                        intervalle_s=periode_s / 2 ** (7 - k))
        for k in range(8))
    return DeviceClassList(
        classes=[
            DeviceClassInfo(
                name="A",
                label="Classe A — écoute après avoir émis",
                ouverture="Juste après chacune de ses émissions (RX1, puis RX2 en repli). "
                          "Le reste du temps, le terminal dort.",
                ne_change_pas="Un ACK ou une réponse MAC : déclenchés par un uplink, ils "
                              "tombent dans RX1 ou RX2 quelle que soit la classe.",
            ),
            DeviceClassInfo(
                name="B",
                label="Classe B — écoute à des créneaux annoncés",
                ouverture="En plus de RX1/RX2, à des créneaux de ping réguliers calés sur "
                          "une balise de la passerelle, tous les 128 s.",
                ne_change_pas="Un ACK ou une réponse MAC : déclenchés par un uplink, ils "
                              "tombent dans RX1 ou RX2 quelle que soit la classe.",
                # Servies ici pour que l'interface n'ait pas à recalculer un intervalle, et
                # surtout pour qu'elle puisse montrer que la périodicité décide — une classe
                # B lente attend plus longtemps qu'une classe A.
                periodicites=periodicites,
            ),
            DeviceClassInfo(
                name="C",
                label="Classe C — écoute en permanence",
                ouverture="Presque tout le temps ; le terminal ne renonce à écouter que "
                          "pendant ses propres émissions.",
                ne_change_pas="Un ACK ou une réponse MAC : déclenchés par un uplink, ils "
                              "tombent dans RX1 ou RX2 quelle que soit la classe.",
            ),
        ],
        cout="Une classe plus réactive coûte l'écoute : C écoute en permanence, B à chaque "
             "créneau. Le surcoût d'énergie se lit dans le courant moyen du run, pas ici.",
    )


class RegionList(_Strict):
    regions: list[RegionInfo] = Field(max_length=16)


def region_info(plan: Plan) -> RegionInfo:
    """Décrit un plan (lecture seule). Les valeurs viennent des modules régionaux."""
    rx2_hz, rx2_datr = plan.rx2()
    payload = {}
    for dr in range(16):
        try:
            payload[str(dr)] = plan.max_frm_payload(dr)
        except ValueError:
            continue
    return RegionInfo(
        name=plan.name,
        uplink_channels_hz=list(plan.uplink_channels_hz()),
        data_rates=plan.dr_table(),
        rx2_hz=rx2_hz,
        rx2_datr=rx2_datr,
        max_payload_by_dr=payload,
        sub_bands=plan.name in ("US915", "AU915"),
    )


def list_regions() -> RegionList:
    return RegionList(regions=[region_info(get_plan(name)) for name in plan_names()])


class EnergyProfileInfo(_Strict):
    """Un modèle de matériel connu du moteur, pour les fenêtres de configuration.

    Le libellé vient du module d'énergie, seule source : le recopier dans l'interface le
    laisserait dériver du matériel réellement modélisé.
    """

    name: str = Field(max_length=32)
    label: str = Field(max_length=128)


class EnergyProfileList(_Strict):
    profiles: list[EnergyProfileInfo] = Field(max_length=16)


def list_energy_profiles() -> EnergyProfileList:
    return EnergyProfileList(profiles=[EnergyProfileInfo(name=name, label=profile_name(name))
                                       for name in ENERGY_PROFILES])


class GatewayProfileInfo(_Strict):
    """Un modèle de passerelle du catalogue, et **ce qu'il change** — pas seulement son nom.

    Trois des quatre modèles ne décalent pas le seuil de réception, leur fiche ne publiant
    pas le point (SF, bande) auquel la sensibilité est mesurée. Les présenter comme un choix
    sans le dire serait faire croire à une différence que le run ne calcule pas.
    """

    name: str = Field(max_length=32)
    vendor: str = Field(max_length=64)
    model: str = Field(max_length=128)
    sensitivity_offset_db: float = Field(ge=-60.0, le=60.0)   # décalage du seuil montant
    sensitivity_published: bool        # la fiche publie-t-elle le point (SF, bande) ?
    can_relay: bool                    # radio mesh documentée : peut-il être relais ?
    can_simulate_radio: bool           # radio d'accès publiée : sans elle, le scénario refuse
    access_bands: list[str] = Field(max_length=16)   # régions d'accès capteurs
    max_channels: Optional[int] = Field(None, ge=1, le=64)
    tx_power_max_dbm: Optional[float] = Field(None, ge=-10.0, le=30.0)
    software_status: str = Field(max_length=32)


class GatewayProfileList(_Strict):
    profiles: list[GatewayProfileInfo] = Field(max_length=16)


def list_gateway_profiles() -> GatewayProfileList:
    from lsim.gateway_profiles import (CATALOG, can_relay, can_simulate_radio,
                                       rx_sensitivity_offset_db, software_status)
    items = []
    for p in CATALOG:
        decalage = rx_sensitivity_offset_db(p)
        items.append(GatewayProfileInfo(
            name=p.key, vendor=p.vendor, model=p.model,
            sensitivity_offset_db=decalage,
            sensitivity_published=p.rx_sensitivity_point is not None,
            can_relay=can_relay(p), can_simulate_radio=can_simulate_radio(p),
            access_bands=list(p.access_bands),
            max_channels=p.max_channels, tx_power_max_dbm=p.tx_power_max_dbm,
            software_status=software_status(p)))
    return GatewayProfileList(profiles=items)


class MaterialInfo(_Strict):
    """Un matériau d'obstacle, avec la perte qu'il causerait réellement.

    `extrapolated` : la fréquence demandée sort de la plage documentée du matériau
    (UIT-R P.2040-4, Tableau 3). À 868 MHz c'est le cas de 13 matériaux sur 15 — seuls
    `air`, `wood` et `glass` sont dans la plage. Le dire ici évite qu'une interface affiche
    une perte en la laissant croire mesurée.
    """

    name: str = Field(max_length=32)
    loss_db: float = Field(ge=0.0, le=1e4)
    extrapolated: bool
    # Plage de fréquences documentée (Hz), quand le catalogue la connaît : c'est la borne
    # que l'utilisateur dépasse, autant la montrer.
    frequency_min_hz: Optional[float] = None
    frequency_max_hz: Optional[float] = None


class MaterialList(_Strict):
    frequency_hz: float
    thickness_m: float
    materials: list[MaterialInfo] = Field(max_length=64)


def list_materials(frequency_hz: float, thickness_m: float = 0.2) -> MaterialList:
    """Les matériaux du moteur, avec leur perte à la fréquence et à l'épaisseur demandées."""
    from lsim.materials import MATERIAL_NAMES, traversal_loss
    items = []
    for name in MATERIAL_NAMES:
        perte, extra = traversal_loss(name, frequency_hz, thickness_m)
        # `+ 0.0` : « air » renvoie -0.0, et un JSON qui affiche « -0.0 dB » pour une
        # traversée d'air se lit comme une erreur de signe.
        items.append(MaterialInfo(name=name,
                                  loss_db=round(max(perte, 0.0), 3) + 0.0,
                                  extrapolated=extra))
    return MaterialList(frequency_hz=frequency_hz, thickness_m=thickness_m,
                        materials=items)


# --- Schémas publiés --------------------------------------------------------------------------

from lsim.study_contract import MODELS as _STUDY_MODELS  # noqa: E402

_MODELS = {
    "scenario_input": ApiScenario,
    "validate_request": ValidateRequest,
    "validate_response": ValidateResponse,
    "run_create": RunCreate,
    "run_status": RunStatus,
    "run_summary": RunSummary,
    "session_run_list": SessionRunList,
    "device_page": DevicePage,
    "trace_page": TracePage,
    "trace_event": TraceEvent,
    "problem": Problem,
    "region_list": RegionList,
    "device_class_list": DeviceClassList,
    "material_list": MaterialList,
    "terrain_list": TerrainList,
    **_STUDY_MODELS,
}


def schemas() -> dict[str, dict]:
    """Schémas JSON (Draft 2020-12 via Pydantic) indexés par nom de fichier."""
    return {name: model.model_json_schema() for name, model in _MODELS.items()}


def write_schemas(directory: Path) -> list[Path]:
    """Écrit un fichier par schéma, JSON trié et indenté (diff stable)."""
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    for name, schema in sorted(schemas().items()):
        path = directory / f"{name}.schema.json"
        path.write_text(json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                        encoding="utf-8")
        written.append(path)
    return written


if __name__ == "__main__":  # python -m lsim.api_contract <dossier>
    import sys

    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("schemas/api/v1")
    for p in write_schemas(target):
        print(p)
