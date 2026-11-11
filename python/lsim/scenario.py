"""Scénarios reproductibles : description YAML validée, déploiement déterministe.

Un scénario décrit une passerelle, un modèle de propagation et des groupes de
dispositifs. Le déploiement aléatoire utilise un générateur graine (Mersenne
Twister, stable entre versions de Python pour `random()`) : même fichier, même
graine, mêmes positions et mêmes instants d'émission.

Le scénario canonique (JSON trié) est haché en SHA-256 ; ce hash est écrit dans
les résultats pour la traçabilité.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import warnings
from pathlib import Path
from typing import Annotated, Literal, Optional, Union

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from lsim.materials import MATERIAL_NAMES, traversal_loss
from lsim.environment import (
    MAX_OBSTACLES,
    Environment,
    Obstacle,
    Terrain,
    load_dem_csv,
)
from lsim.simulator import EndDevice, Gateway, Propagation
from lsim.gateway_sensitivity import (CATALOG, MODEL_ID, SF5_REGION, AbsoluteSensitivity,
                                     SensitivityError)
from lsim.gateway_profiles import (can_relay, can_simulate_radio, get_profile,
                                   rx_sensitivity_offset_db)

SCHEMA_VERSION = 1
MAX_DEVICES = 10_000
MAX_TRANSMISSIONS = 5_000_000
MAX_GATEWAYS = 64
_NS_PER_S = 1_000_000_000


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SensitivityPoint(_Strict):
    """Un seuil absolu publié (dBm) pour une bande et un SF."""

    bandwidth_hz: Literal[125000, 250000, 500000] = 125000
    sf: int = Field(ge=5, le=12)
    dbm: float = Field(ge=-160.0, le=-60.0)


class SensitivityModel(_Strict):
    """Sensibilité absolue de la passerelle (`sensibilite-par-sf-v2`), jamais déduite du relatif.

    Soit `profile` (nom du catalogue `lsim.gateway_sensitivity.CATALOG`), soit `points` explicites
    avec `source` et `conditions`. Une paire SF/bande absente est refusée à la validation.
    """

    model: Literal["sensibilite-par-sf-v2"]
    profile: Optional[str] = Field(None, min_length=1, max_length=64)
    source: Optional[str] = Field(None, min_length=1, max_length=500)
    conditions: Optional[str] = Field(None, min_length=1, max_length=500)
    points: Optional[list[SensitivityPoint]] = Field(None, min_length=1, max_length=24)

    def absolute(self) -> AbsoluteSensitivity:
        if (self.profile is None) == (self.points is None):
            raise ValueError("sensibilité : exactement un de « profile » ou « points »")
        if self.profile is not None:
            if self.profile not in CATALOG:
                raise ValueError(f"profil de sensibilité inconnu : {self.profile!r}")
            return CATALOG[self.profile]
        if self.source is None or self.conditions is None:
            raise ValueError("points explicites : « source » et « conditions » requises")
        try:
            return AbsoluteSensitivity(
                points=tuple((p.bandwidth_hz, p.sf, p.dbm) for p in self.points),
                source=self.source, conditions=self.conditions)
        except SensitivityError as exc:
            raise ValueError(str(exc)) from None


class GatewayModel(_Strict):
    x_m: float = 0.0
    y_m: float = 0.0
    antenna_gain_dbi: float = 0.0
    # Puissance d'émission de la passerelle, **conduite en sortie d'émetteur** (dBm), avant
    # câble et antenne : même convention que `group.tx_power_dbm` côté terminal. `None`
    # (défaut) : la valeur vient des options de protocole
    # (`ProtocolOptions.gateway_tx_power_dbm`, 14,0 dBm) — comportement historique inchangé.
    # La PIRE qui en découle (conduite + gain − perte) départage les sous-bandes ETSI : voir
    # `lsim.power`. Plafond : 27 dBm, puissance publiée des fiches du catalogue.
    tx_power_dbm: Optional[float] = Field(None, ge=-10.0, le=27.0)
    # Multi-passerelles seulement : nom unique, profil du catalogue, relais mesh.
    name: Optional[str] = Field(None, min_length=1, max_length=64)
    profile: Optional[str] = Field(None, min_length=1, max_length=64)
    mesh: bool = False
    # Sensibilité absolue (modèle sensibilite-par-sf-v2). Absent = modèle relatif, hash inchangé.
    sensitivity: Optional[SensitivityModel] = None
    # Frontal RF v4 de la passerelle (None = neutre). Le gain remplace `antenna_gain_dbi`.
    rf: Optional[RfModel] = None

    @model_validator(mode="after")
    def _rf_gain_not_duplicated(self) -> "GatewayModel":
        if (self.rf is not None and self.rf.antenna_gain_dbi is not None
                and "antenna_gain_dbi" in self.model_fields_set
                and abs(self.antenna_gain_dbi - self.rf.antenna_gain_dbi) > 1e-9):
            raise ValueError(
                "gateway : antenna_gain_dbi et rf.antenna_gain_dbi diffèrent — le gain du "
                "frontal remplacerait le champ scalaire ; n'en déclarer qu'un")
        return self


class MeshModel(_Strict):
    """Backhaul mesh 2,4 GHz : la passerelle frontière est reliée au LNS par le réseau."""

    border: str = Field(min_length=1, max_length=64)
    spreading_factor: int = Field(9, ge=5, le=12)  # défaut : SF9/203 kHz (voir docs/USAGE.md)
    bandwidth_khz: Literal[203, 406, 812, 1625] = 203
    coding_rate: int = Field(1, ge=1, le=4)
    # Taille relayée. « device » : trame LoRaWAN réelle du dispositif + enveloppe mesh
    # (14 o en montant). « fixed » : `payload_bytes` pour toutes les trames (hypothèse).
    frame_size: Literal["device", "fixed"] = "device"
    payload_bytes: int = Field(32, ge=0, le=255)  # utilisé seulement si frame_size = fixed
    capture_db: float = Field(6.0, ge=0.0, le=30.0)
    max_hops: int = Field(8, ge=1, le=8)
    # Suppression des doublons par identifiant de trame (défaut). `false` : chaque copie
    # reçue par un relais est relayée, pour comparer.
    suppress_duplicates: bool = True
    # Attente de chaque relais avant de transmettre une copie, en temps d'antenne mesh
    # (déterministe par relais et trame). 0 : pas d'attente, donc pas de suppression
    # entre relais qui reçoivent la même trame au même instant.
    relay_backoff_airtimes: int = Field(4, ge=0, le=64)
    # Shadowing log-normal des liaisons entre passerelles mesh : un tirage par paire,
    # réciproque, graine = propagation.shadowing_seed. 0 : liaisons déterministes.
    shadowing_sigma_db: float = Field(0.0, ge=0.0, le=30.0)


class PropagationModel(_Strict):
    frequency_hz: float = 868.1e6
    reference_distance_m: float = Field(1.0, gt=0)
    exponent: float = Field(2.7, ge=1.0, le=6.0)
    capture_threshold_db: float = Field(6.0, ge=0)
    # Shadowing log-normal par dispositif (0 = désactivé). Graine absente : la
    # graine du scénario est utilisée, ce qui rend le tirage reproductible.
    shadowing_sigma_db: float = Field(0.0, ge=0, le=30.0)
    shadowing_seed: Optional[int] = Field(None, ge=0, le=2**64 - 1)


class DiskPlacement(_Strict):
    type: Literal["disk"]
    radius_m: float = Field(gt=0)
    center_x_m: float = 0.0
    center_y_m: float = 0.0


class ExplicitPlacement(_Strict):
    type: Literal["explicit"]
    positions: list[tuple[float, float]] = Field(min_length=1)


Placement = Annotated[Union[DiskPlacement, ExplicitPlacement], Field(discriminator="type")]


class RetransmissionsModel(_Strict):
    """Retransmissions des uplinks confirmés (bloc `retransmissions:` du scénario).

    Absent : aucune réémission, comportement historique, hash inchangé. Présent : le scénario force
    les uplinks confirmés et réémet tant que l'ACK n'est pas reçu.

    `retries: 0` est accepté et n'ajoute aucune transmission : c'est le moteur actuel.
    """

    enabled: bool = True
    retries: int = Field(3, ge=0, le=7)
    retransmit_delay_ms: int = Field(3_000, ge=2_000, le=60_000)
    enforce_duty_cycle: bool = True
    # Profil énergétique utilisé pour le relevé d'énergie de la simulation (None : pas de relevé).
    energy_profile: Optional[str] = None
    # Comportement du réseau vis-à-vis de l'ACK. Par défaut : planificateur du cœur (RX1, un envoi).
    # Une valeur non nulle de `ack_delay_ms`, ou `ack_repetitions` > 1, active la couche MAC.
    ack_delay_ms: int = Field(0, ge=0, le=60_000)
    ack_repetitions: int = Field(1, ge=1, le=3)
    # La descente porte une charge utile applicative : elle consomme AFCntDown (`data_ack`).
    downlink_payload: bool = False
    # Instants (s) des Join-Accept acceptés : chacun ouvre une session et remet les compteurs à
    # zéro. Vide : une seule session, ouverte avant le scénario. Modèle **déclaré**, sans radio.
    session_joins_s: list[int] = Field(default_factory=list, max_length=16)
    # Instants (s) des Join-Request : la jointure passe alors par le moteur radio (temps de vol,
    # collisions, sensibilité) et n'ouvre une session que si le Join-Accept est reçu.
    join_requests_s: list[int] = Field(default_factory=list, max_length=16)
    join_retries: int = Field(1, ge=1, le=3)
    # RX2 est la fenêtre de secours de RX1 : elle n'est émise que si RX1 n'a pas abouti.
    join_accept_rx2_fallback: bool = True
    # Join-Accept rejoués après acceptation (même JoinNonce) : reçus puis refusés.
    join_accept_replays: int = Field(0, ge=0, le=2)

    @field_validator("session_joins_s", "join_requests_s")
    @classmethod
    def _jointures_croissantes(cls, valeurs: list[int], info) -> list[int]:
        nom = f"retransmissions.{info.field_name}"
        for valeur in valeurs:
            if not 0 <= valeur:
                raise ValueError(f"{nom} : instants positifs attendus")
        for precedent, suivant in zip(valeurs, valeurs[1:]):
            if suivant <= precedent:
                raise ValueError(f"{nom} : instants strictement croissants attendus")
        return valeurs

    @model_validator(mode="after")
    def _une_seule_forme_de_jointure(self):
        if self.session_joins_s and self.join_requests_s:
            raise ValueError("retransmissions : session_joins_s (déclaré) et join_requests_s "
                             "(radio) ne peuvent pas être utilisés ensemble")
        return self
    # Premier FCntUp de chaque terminal (compteur 32 bits, comme `lsim.session`).
    fcnt_up_start: int = Field(0, ge=0, le=2**32 - 1)
    # Premier compteur descendant de chaque terminal : départ des deux séries `NFCntDown` et
    # `AFCntDown` de la couche MAC (les deux partent de la même valeur de session).
    fcnt_down_start: int = Field(0, ge=0, le=2**32 - 1)

    @model_validator(mode="after")
    def _known_energy_profile(self) -> "RetransmissionsModel":
        if self.energy_profile is not None:
            from lsim.energy_report import profile_name
            try:
                profile_name(self.energy_profile)
            except ValueError as exc:
                raise ValueError(f"retransmissions.energy_profile : {exc}") from exc
        return self

    def options(self):
        from lsim.retransmissions import RetransmissionOptions
        return RetransmissionOptions(enabled=self.enabled, retries=self.retries,
                                     retransmit_delay_ms=self.retransmit_delay_ms,
                                     enforce_duty_cycle=self.enforce_duty_cycle,
                                     ack_delay_ms=self.ack_delay_ms,
                                     ack_repetitions=self.ack_repetitions,
                                     fcnt_up_start=self.fcnt_up_start,
                                     fcnt_down_start=self.fcnt_down_start,
                                     downlink_payload=self.downlink_payload,
                                     session_joins_s=tuple(self.session_joins_s),
                                     join_requests_s=tuple(self.join_requests_s),
                                     join_retries=self.join_retries,
                                     join_accept_rx2_fallback=self.join_accept_rx2_fallback,
                                     join_accept_replays=self.join_accept_replays)

    @property
    def is_active(self) -> bool:
        """Vrai quand des réémissions sont possibles : sinon le chemin historique suffit."""
        return self.enabled and self.retries > 0


class RfModel(_Strict):
    """Frontal RF v4 d'un groupe ou d'une passerelle (ABI v4).

    Les deux champs sont **indépendants** : un champ absent n'est pas un champ nul, c'est une
    donnée non fournie. Le bloc doit en déclarer au moins un.

    - terminal : la chaîne `gain - perte` s'applique au montant et au descendant (antenne
      réciproque), comptée une fois ;
    - passerelle : le gain présent **remplace** `gateway.antenna_gain_dbi`, la perte de câble
      s'ajoute (sémantique de `apply_gateway_rf` dans `core/src/c_api_ext.cpp`).
    """

    antenna_gain_dbi: Optional[float] = Field(None, ge=-40.0, le=40.0)
    cable_loss_db: Optional[float] = Field(None, ge=0.0, le=40.0)

    @model_validator(mode="after")
    def _at_least_one(self) -> "RfModel":
        if self.antenna_gain_dbi is None and self.cable_loss_db is None:
            raise ValueError(
                "rf : au moins un champ est requis (antenna_gain_dbi ou cable_loss_db)")
        return self

    def device(self):
        from lsim.rf import DeviceRf
        return DeviceRf(antenna_gain_dbi=self.antenna_gain_dbi, cable_loss_db=self.cable_loss_db)

    def gateway(self):
        from lsim.rf import GatewayRf
        return GatewayRf(antenna_gain_dbi=self.antenna_gain_dbi, cable_loss_db=self.cable_loss_db)


class GroupModel(_Strict):
    name: str = Field(min_length=1, max_length=64)
    count: Optional[int] = Field(default=None, ge=1, le=MAX_DEVICES)
    placement: Placement
    spreading_factor: int = Field(7, ge=5, le=12)
    payload_bytes: int = Field(10, ge=0, le=255)
    tx_power_dbm: float = 14.0
    period_s: float = Field(600.0, gt=0)
    messages: int = Field(1, ge=1)
    duty_cycle: float = Field(1.0, gt=0, le=1.0)
    # Profil régional optionnel (ex. « EU868 ») : le duty cycle effectif est alors
    # le plus restrictif entre `duty_cycle` et la sous-bande du canal `channel_freq_hz`.
    region: Optional[str] = None
    channel_freq_hz: int = Field(868_100_000, gt=0)
    # US915 / AU915 seulement : sous-bande 1 à 8 (8 canaux 125 kHz + 1 canal 500 kHz). Le canal
    # `channel_freq_hz` doit appartenir à cette sous-bande.
    sub_band: Optional[int] = Field(default=None, ge=1, le=8)
    start_spread_s: float = Field(0.0, ge=0)
    # Classe LoRaWAN du terminal : A et B ouvrent RX1/RX2 après chaque uplink ; C écoute en
    # continu. Les ping slots de la classe B ne sont pas modélisés ici : seul l'ACK (descente de
    # classe A) dépend de ce champ.
    device_class: Literal["A", "B", "C"] = "A"
    # Frontal RF v4 commun aux terminaux du groupe (None = neutre).
    rf: Optional[RfModel] = None
    # RX1DROffset des terminaux du groupe (RP002-1.0.4). 0 = réglage du serveur, valeur
    # historique : sans ce champ, le comportement est inchangé.
    # Borné ici à 7, largeur du champ MAC (DLsettings bits 6:4). La borne **régionale**, plus
    # stricte — US915 n'admet que 0..3 — est vérifiée à l'usage, contre le plan, car elle
    # dépend de `region` qui peut être absent.
    rx1_dr_offset: int = Field(0, ge=0, le=7)
    # Modèle de matériel du groupe (None : celui du scénario). Le matériel est une
    # propriété de l'équipement, pas du run : deux capteurs de matériel différent ne
    # consomment pas la même chose, et les comparer dans un même run est précisément
    # l'intérêt. Champ **optionnel** : un scénario écrit avant cette distinction garde
    # exactement ses chiffres, et son empreinte ne bouge pas.
    energy: Optional[EnergyModel] = None

    @property
    def effective_duty_cycle(self) -> float:
        if self.region is None:
            return self.duty_cycle
        from lsim.regions import PROFILES
        limit = PROFILES[self.region].duty_cycle_limit(self.channel_freq_hz, self.tx_power_dbm)
        return self.duty_cycle if limit is None else min(self.duty_cycle, limit)

    @model_validator(mode="after")
    def _sub_band_consistent(self) -> "GroupModel":
        if self.sub_band is None:
            return self
        from lsim.channel_mask import FAMILY, sub_band_channels
        from lsim.plan import get_plan
        if self.region not in FAMILY:
            raise ValueError("sub_band : réservé aux régions US915 et AU915")
        index = get_plan(self.region).channel_index(self.channel_freq_hz / 1_000_000)
        if index not in sub_band_channels(self.sub_band):
            raise ValueError(
                f"{self.region} : canal {self.channel_freq_hz} Hz hors de la sous-bande {self.sub_band}")
        return self

    @model_validator(mode="after")
    def _rx1_dr_offset_dans_les_bornes_regionales(self) -> "GroupModel":
        """La borne régionale de RX1DROffset est plus stricte que celle du champ MAC.

        US915 n'admet que 0..3 alors que le champ DLsettings en code 0..7. Refusé ici, à la
        lecture du scénario, plutôt qu'à la simulation : une valeur hors bornes est une
        erreur de configuration, pas une scène lente — et la refuser au plus tôt évite de
        produire une chronologie qui ne correspond à rien.
        """
        if self.region is None or self.rx1_dr_offset == 0:
            return self
        from lsim.plan import get_plan
        plan = get_plan(self.region)
        if self.rx1_dr_offset > plan.rx1_dr_offset_max:
            raise ValueError(
                f"groupe {self.name!r} : RX1DROffset {self.rx1_dr_offset} hors bornes pour "
                f"{self.region} (0..{plan.rx1_dr_offset_max}, RP002-1.0.4)")
        return self

    @model_validator(mode="after")
    def _region_known_and_in_plan(self) -> "GroupModel":
        if self.region is None:
            return self
        from lsim.regions import PROFILES
        if self.region not in PROFILES:
            raise ValueError(f"région inconnue : {self.region}")
        profile = PROFILES[self.region]
        self.effective_duty_cycle  # lève si le canal est hors sous-bandes
        if profile.channels:
            ch = profile.channel_at(self.channel_freq_hz)
            if ch is None:
                raise ValueError(f"{self.region} : canal {self.channel_freq_hz} Hz absent du plan")
            if profile.power_basis == "eirp" and ch.max_eirp_dbm is not None:
                # Comparaison en PIRE : `tx_power_dbm` est une puissance conduite, la
                # chaîne `gain - perte` du frontal s'ajoute (`lsim.power.device_tx`).
                # Sans bloc `rf`, la chaîne est nulle et le comportement est identique
                # à l'ancienne comparaison sur `tx_power_dbm` seul.
                from lsim.power import device_tx
                pire = device_tx(self).eirp_dbm
                if pire > ch.max_eirp_dbm + 1e-9:
                    raise ValueError(
                        f"{self.region} : PIRE {pire} dBm au-dessus de la limite "
                        f"{ch.max_eirp_dbm} dBm du canal")
        return self
        from lsim.regions import PROFILES
        if self.region not in PROFILES:
            raise ValueError(f"région inconnue : {self.region}")
        self.effective_duty_cycle  # lève si le canal est hors plan ou PIRE trop haute
        return self

    @model_validator(mode="after")
    def _count_matches_placement(self) -> "GroupModel":
        if isinstance(self.placement, ExplicitPlacement):
            n = len(self.placement.positions)
            if self.count is not None and self.count != n:
                raise ValueError("count doit égaler le nombre de positions explicites")
        elif self.count is None:
            raise ValueError("count est requis pour un placement disque")
        return self

    @property
    def device_count(self) -> int:
        if isinstance(self.placement, ExplicitPlacement):
            return len(self.placement.positions)
        return int(self.count or 0)


class ObstacleModel(_Strict):
    x_min_m: float
    y_min_m: float
    x_max_m: float
    y_max_m: float
    height_m: float = Field(gt=0, le=1000)
    # Soit `attenuation_db` (perte saisie), soit `material` + `thickness_m`
    # (perte calculée par UIT-R P.2040-4 à la fréquence de la propagation).
    attenuation_db: float = Field(0.0, ge=0, le=200)
    material: Optional[str] = Field(None, max_length=32)
    thickness_m: Optional[float] = Field(None, gt=0, le=10)

    @model_validator(mode="after")
    def _box_not_empty(self) -> "ObstacleModel":
        if not (self.x_min_m < self.x_max_m and self.y_min_m < self.y_max_m):
            raise ValueError("emprise de l'obstacle vide (min doit être < max)")
        if self.material is None:
            if self.thickness_m is not None:
                raise ValueError("thickness_m exige material")
        else:
            if self.thickness_m is None:
                raise ValueError("material exige thickness_m")
            if "attenuation_db" in self.model_fields_set:
                raise ValueError("attenuation_db et material sont exclusifs")
            if self.material not in MATERIAL_NAMES:
                raise ValueError(f"matériau inconnu : {self.material!r}")
        return self


class TerrainModel(_Strict):
    type: Literal["dem_csv"]
    # Chemin relatif au fichier de scénario ; pas de racine, pas de '..'.
    path: str = Field(min_length=1, max_length=255)

    @model_validator(mode="after")
    def _safe_relative(self) -> "TerrainModel":
        p = Path(self.path)
        if p.is_absolute() or ".." in p.parts or "\\" in self.path:
            raise ValueError("terrain.path doit être relatif, sans '..'")
        return self


class EnvironmentModel(_Strict):
    gateway_height_m: float = Field(15.0, gt=0, le=1000)
    device_height_m: float = Field(1.5, gt=0, le=1000)
    terrain: Optional[TerrainModel] = None
    obstacles: list[ObstacleModel] = Field(default_factory=list, max_length=MAX_OBSTACLES)


class EnergyModel(_Strict):
    """Profil énergie choisi par le scénario (optionnel ; la ligne de commande le remplace)."""
    profile: Literal["rak4631", "sx1262-stm32l072"]


class ChannelDefModel(_Strict):
    """Canal défini du terminal (RP002 EU863-870) : index 0..79, débits supportés dr_min..dr_max."""

    index: int = Field(ge=0, le=79)
    dr_min: int = Field(0, ge=0, le=7)
    dr_max: int = Field(7, ge=0, le=7)

    @model_validator(mode="after")
    def _range(self) -> "ChannelDefModel":
        if self.dr_min > self.dr_max:
            raise ValueError("canal : dr_min > dr_max")
        return self


class MacModel(_Strict):
    """Commandes MAC demandées par les dispositifs (optionnel ; 0 = désactivé).

    Phase 1 (passerelle unique), rangs 1-based des émissions du dispositif :
    - `link_check_every` : LinkCheckReq (1 octet) dans l'uplink de rang multiple de N ; reçue, elle
      est acquittée par un LinkCheckAns dans un downlink (dédié s'il n'y en a pas déjà un) ;
    - `device_status_every` : DevStatusReq dans le downlink répondant à un uplink reçu de rang
      multiple de N. Le dispositif répond par DevStatusAns (3 octets) dans son uplink suivant, si
      la requête lui parvient. Cette réponse est réservée conservativement dans cet uplink
      suivant : le temps d'antenne le compte, même si la requête n'est pas reçue.
    Les octets réservés allongent le temps d'antenne des émissions concernées (moteur natif) ; les
    octets émis effectivement n'apparaissent dans la trace qu'une fois confirmés.
    Refusé avec plusieurs passerelles ou un mesh.

    Marge de LinkCheckAns (indicative, pas la marge SNR normative) :
        M = clamp(floor(RSSI_UL - S_ref(SF, 125 kHz) - marge_installation), 0, 254)
    où S_ref est la sensibilité SX1276 utilisée par le simulateur pour décider de la perte : M
    mesure la marge au-dessus du seuil de réception, en dB. `link_margin_installation_db` est une
    marge d'installation soustraite (0 par défaut), comme dans l'ADR.
    """
    link_check_every: int = Field(0, ge=0, le=1000)
    device_status_every: int = Field(0, ge=0, le=1000)
    link_margin_installation_db: int = Field(0, ge=0, le=60)
    device_time_every: int = Field(0, ge=0, le=1000)
    # Boucle fermée (LinkADRReq / DutyCycleReq) : passerelle unique, sans jointure, plan régional
    # avec table TXPower (EU868 seulement, voir lsim.regions.POWER_TABLES). Décision ADR côté
    # serveur sur les 20 dernières trames reçues ; marge = `link_margin_installation_db`.
    # `duty_cycle_exponent` k : DutyCycleReq avec 1/2^k (None : pas de DutyCycleReq).
    link_adr: bool = False
    duty_cycle_exponent: Optional[int] = Field(None, ge=0, le=15)
    # Canaux (correction ChannelMask, étape 1) : deux vues strictement séparées.
    #   `device_channels` : capacité réelle du terminal (canaux définis et débits supportés) ;
    #   `server_channel_plan` : canaux que le serveur croit définis (sa propre vue).
    # Le moteur ne les utilise pas encore : tant que l'étape 3 n'est pas validée, toute valeur
    # est refusée explicitement (pas de paramètre silencieusement inactif).
    device_channels: Optional[list[ChannelDefModel]] = Field(None, max_length=80)
    server_channel_plan: Optional[list[int]] = Field(None, max_length=80)


class ScenarioModel(_Strict):
    schema_version: Literal[1]
    name: str = Field(min_length=1, max_length=128)
    seed: int = Field(0, ge=0, le=2**32 - 1)
    gateway: GatewayModel = GatewayModel()
    gateways: Optional[list[GatewayModel]] = Field(None, min_length=1, max_length=MAX_GATEWAYS)
    mesh: Optional[MeshModel] = None
    # Retransmissions des uplinks confirmés. Absent : comportement historique.
    retransmissions: Optional[RetransmissionsModel] = None
    propagation: PropagationModel = PropagationModel()
    environment: Optional[EnvironmentModel] = None
    energy: Optional[EnergyModel] = None
    mac: Optional[MacModel] = None
    groups: list[GroupModel] = Field(min_length=1)

    def _sensitivity_rules(self) -> None:
        """Sensibilité absolue et SF5/SF6 : refus explicites, aucun repli silencieux."""
        for g in self.groups:
            if g.spreading_factor == 6:
                raise ValueError(f"groupe {g.name!r} : SF6 non modélisé (en-tête implicite seulement)")
        sf5 = [g.name for g in self.groups if g.spreading_factor == 5]
        gws = [self.gateway, *(self.gateways or [])]
        if all(g.sensitivity is None for g in gws):
            if sf5:
                raise ValueError(f"groupe {sf5[0]!r} : SF5 exige le modèle {MODEL_ID} "
                                 "(bloc « sensitivity » de la passerelle)")
            return
        if self.gateways is not None or self.mesh is not None:
            raise ValueError(f"{MODEL_ID} : passerelle unique uniquement "
                             "(pas de « gateways » ni de mesh)")
        gw = self.gateway
        if gw.profile is not None:
            raise ValueError(f"{MODEL_ID} et profil de passerelle {gw.profile!r} incompatibles : "
                             "le seuil absolu remplace le décalage relatif, sans conversion")
        sens = gw.sensitivity.absolute()
        for g in self.groups:
            if g.spreading_factor == 5 and g.region != SF5_REGION:
                raise ValueError(f"groupe {g.name!r} : SF5 (DR13) réservé à la région {SF5_REGION}")
            if g.region not in (None, SF5_REGION):
                raise ValueError(f"groupe {g.name!r} : région {g.region!r} hors de {MODEL_ID} "
                                 f"({SF5_REGION} seulement)")
            try:
                sens.lookup(g.spreading_factor, 125_000)
            except SensitivityError as exc:
                raise ValueError(f"groupe {g.name!r} : {exc}") from None
        if self.mac is not None and sf5:
            raise ValueError(f"groupe {sf5[0]!r} : SF5 avec bloc « mac » refusé "
                             "(sensibilité du terminal NV)")

    @model_validator(mode="after")
    def _limits(self) -> "ScenarioModel":
        self._sensitivity_rules()
        names = [g.name for g in self.groups]
        if len(set(names)) != len(names):
            raise ValueError("les noms de groupes doivent être uniques")
        if self.mac is not None and (self.mac.device_channels is not None
                                     or self.mac.server_channel_plan is not None):
            raise ValueError("mac : « device_channels » et « server_channel_plan » ne sont pas "
                             "encore actifs dans le moteur (étape 3 de la correction ChannelMask)")
        if self.mac is not None and (self.mac.link_adr or self.mac.duty_cycle_exponent is not None):
            if self.gateways is not None or self.mesh is not None:
                raise ValueError("LinkADR/DutyCycle : passerelle unique uniquement "
                                 "(pas de « gateways » ni de mesh)")
        if self.mac is not None and (self.mac.link_check_every or self.mac.device_status_every
                                     or self.mac.device_time_every):
            if self.gateways is not None or self.mesh is not None:
                raise ValueError("commandes MAC : passerelle unique uniquement "
                                 "(pas de « gateways » ni de mesh)")
            # Réservation maximale d'une émission : LinkCheckReq (1) + DeviceTimeReq (1) + DevStatusAns (3),
            # plus LinkADRAns (2) et DutyCycleAns (1) si la boucle fermée les porte.
            extra = ((1 if self.mac.link_check_every else 0) + (1 if self.mac.device_time_every else 0)
                     + (3 if self.mac.device_status_every else 0))
            if self.mac.link_adr or self.mac.duty_cycle_exponent is not None:
                extra += 3
            for g in self.groups:
                if g.payload_bytes + extra > 255:
                    raise ValueError(f"groupe {g.name!r} : charge de {g.payload_bytes} octets + "
                                     f"{extra} octets MAC réservés dépasse 255")
        if self.gateways is None:
            if self.mesh is not None:
                raise ValueError("mesh exige la liste « gateways » (plusieurs passerelles)")
            if any(getattr(self.gateway, f) is not None for f in ("name", "profile")) or self.gateway.mesh:
                raise ValueError("nom, profil et mesh d'une passerelle exigent « gateways »")
        else:
            if "gateway" in self.model_fields_set:
                raise ValueError("utiliser « gateway » ou « gateways », pas les deux")
            gw_names = [g.name for g in self.gateways]
            if any(n is None for n in gw_names):
                raise ValueError("chaque passerelle de « gateways » doit avoir un nom")
            if len(set(gw_names)) != len(gw_names):
                raise ValueError("les noms de passerelles doivent être uniques")
            for g in self.gateways:
                if g.profile is not None:
                    try:
                        prof = get_profile(g.profile)
                    except KeyError:
                        raise ValueError(f"profil inconnu : {g.profile!r}") from None
                    if not can_simulate_radio(prof):
                        raise ValueError(
                            f"profil {g.profile!r} : hôte sans radio publiée, choisir un module "
                            "radio (voir docs/USAGE.md)")
                if g.mesh and (g.profile is None or not can_relay(get_profile(g.profile))):
                    raise ValueError(f"passerelle {g.name!r} : mesh exige un profil à radio mesh documentée")
            for g in self.gateways:
                if g.mesh and g.profile is not None:
                    prof = get_profile(g.profile)
                    for grp in self.groups:
                        if grp.region is not None and prof.access_bands and grp.region not in prof.access_bands:
                            raise ValueError(
                                f"passerelle {g.name!r} : profil {g.profile!r} sans accès {grp.region} "
                                "(un relais doit recevoir les capteurs de sa région ; le module mesh seul "
                                "ne suffit pas)")
            if self.mesh is not None:
                border = next((g for g in self.gateways if g.name == self.mesh.border), None)
                if border is None:
                    raise ValueError("mesh.border doit désigner une passerelle")
                if not border.mesh:
                    raise ValueError("la passerelle frontière doit avoir mesh: true")
                if sum(1 for g in self.gateways if g.mesh) < 1:
                    raise ValueError("au moins une passerelle doit avoir mesh: true")
        devices = sum(g.device_count for g in self.groups)
        if devices > MAX_DEVICES:
            raise ValueError(f"au plus {MAX_DEVICES} dispositifs (demandé : {devices})")
        transmissions = sum(g.device_count * g.messages for g in self.groups)
        if transmissions > MAX_TRANSMISSIONS:
            raise ValueError(f"au plus {MAX_TRANSMISSIONS} transmissions (demandé : {transmissions})")
        return self


class Scenario:
    """Scénario validé, prêt à être déployé et simulé."""

    def __init__(self, model: ScenarioModel, environment: Optional[Environment] = None) -> None:
        if model.environment is not None and environment is None:
            raise ValueError("environnement déclaré : charger le scénario avec load_scenario")
        self.model = model
        self.environment = environment
        dumped = model.model_dump(mode="json")
        if model.environment is None:
            # Sans environnement, le hash reste celui des scénarios antérieurs.
            dumped.pop("environment", None)
        elif environment is not None and environment.terrain is not None:
            dumped["environment"]["terrain_sha256"] = environment.terrain.sha256
        # Profil énergie absent : hash des scénarios antérieurs inchangé.
        if model.energy is None:
            dumped.pop("energy", None)
        # Frontaux RF absents : hash des scénarios antérieurs inchangé. Un bloc présent reste
        # haché (le scénario n'est alors plus identique à son équivalent sans RF, à dessein).
        self._strip_absent_rf(model, dumped)
        # Bloc MAC absent : hash des scénarios antérieurs inchangé.
        if model.mac is None:
            dumped.pop("mac", None)
        else:
            # Champs de la boucle fermée à leur valeur par défaut : hash inchangé.
            if not model.mac.link_adr:
                dumped["mac"].pop("link_adr", None)
            if model.mac.duty_cycle_exponent is None:
                dumped["mac"].pop("duty_cycle_exponent", None)
            # Champs de canaux absents : hash des scénarios antérieurs inchangé.
            if model.mac.device_channels is None:
                dumped["mac"].pop("device_channels", None)
            if model.mac.server_channel_plan is None:
                dumped["mac"].pop("server_channel_plan", None)
        # Multi-passerelles et mesh absents : hash des scénarios antérieurs inchangé.
        if model.gateways is None:
            dumped.pop("gateways", None)
        if model.mesh is None:
            dumped.pop("mesh", None)
        gw_dumps = ([dumped["gateway"]] if model.gateways is None else dumped.get("gateways", []))
        for gw_dump in gw_dumps:
            for key in ("name", "profile", "sensitivity"):
                if gw_dump.get(key) is None:
                    gw_dump.pop(key, None)
            if not gw_dump.get("mesh"):
                gw_dump.pop("mesh", None)
            # Puissance d'émission non déclarée : hors du hash, donc scénarios antérieurs
            # inchangés (elle est alors fournie par les options de protocole).
            if gw_dump.get("tx_power_dbm") is None:
                gw_dump.pop("tx_power_dbm", None)
        if model.gateways is not None:
            # `gateways` déclaré : le champ scalaire `gateway` subsiste à sa valeur par défaut
            # et reste haché tel quel (comportement historique, y compris ses valeurs nulles).
            # Seul le champ ajouté en est retiré, pour ne pas en déplacer l'empreinte.
            dumped["gateway"].pop("tx_power_dbm", None)
        if model.gateways is None:
            dumped["gateway"] = gw_dumps[0]
        # Champs optionnels à leur valeur par défaut : absents du hash (scénarios antérieurs inchangés).
        for group in dumped.get("groups", []):
            if group.get("duty_cycle") == 1.0:
                group.pop("duty_cycle", None)
            if group.get("sub_band") is None:
                group.pop("sub_band", None)
            if group.get("region") is None:
                group.pop("region", None)
                group.pop("channel_freq_hz", None)
            if group.get("device_class") == "A":
                group.pop("device_class", None)
            # RX1DROffset à 0 = réglage du serveur, donc absent du hash : un scénario écrit
            # avant l'introduction du champ garde exactement la même empreinte.
            if group.get("rx1_dr_offset") == 0:
                group.pop("rx1_dr_offset", None)
            # Modèle de matériel non déclaré : hors du hash, donc un scénario écrit avant
            # cette distinction garde exactement la même empreinte — et le même courant,
            # puisque le profil du run continue de s'appliquer.
            if group.get("energy") is None:
                group.pop("energy", None)
        # Champs de pavé optionnels absents : hash des scénarios antérieurs inchangé.
        for env_dump in ([dumped["environment"]] if "environment" in dumped else []):
            for ob in env_dump.get("obstacles", []):
                if ob.get("material") is None:
                    ob.pop("material", None)
                    ob.pop("thickness_m", None)
        prop = dumped.get("propagation", {})
        if prop.get("shadowing_sigma_db") == 0.0 and prop.get("shadowing_seed") is None:
            prop.pop("shadowing_sigma_db", None)
            prop.pop("shadowing_seed", None)
        canonical = json.dumps(dumped, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        self.sha256 = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @property
    def name(self) -> str:
        return self.model.name

    @property
    def energy_profile(self) -> Optional[str]:
        """Profil énergie déclaré dans le YAML, ou None."""
        return self.model.energy.profile if self.model.energy is not None else None

    def device_classes(self) -> list[str]:
        """Classe LoRaWAN de chaque terminal déployé, dans l'ordre de `deploy()`.

        Le groupe porte la classe ; le déploiement énumère les groupes dans l'ordre du fichier,
        donc l'alignement est direct. Aucune position n'est tirée : le compteur de chaque groupe
        suffit, et aucune consommation du générateur aléatoire n'est ajoutée.
        """
        classes: list[str] = []
        for groupe in self.model.groups:
            classes.extend([groupe.device_class] * groupe.device_count)
        return classes

    def deploy(self) -> tuple[list[EndDevice], list[str], list[int]]:
        """Retourne (dispositifs, nom de groupe par dispositif, index dans le groupe).

        Déterministe : l'ordre des groupes et des dispositifs est fixé par le fichier.
        """
        rng = random.Random(self.model.seed)
        devices: list[EndDevice] = []
        group_of: list[str] = []
        index_in_group: list[int] = []
        for g in self.model.groups:
            positions = _positions(g, rng)
            spread_ns = int(g.start_spread_s * _NS_PER_S)
            period_ns = int(round(g.period_s * _NS_PER_S))
            for i, (x, y) in enumerate(positions):
                offset = int(rng.random() * spread_ns) if spread_ns > 0 else 0
                devices.append(EndDevice(
                    x_m=x, y_m=y, spreading_factor=g.spreading_factor,
                    payload_bytes=g.payload_bytes, tx_power_dbm=g.tx_power_dbm,
                    start_offset_ns=offset, period_ns=period_ns, messages=g.messages,
                    duty_cycle=g.effective_duty_cycle,
                    rf=g.rf.device() if g.rf is not None else None,
                    energy_profile=(g.energy.profile if g.energy is not None else None)))
                group_of.append(g.name)
                index_in_group.append(i)
        return devices, group_of, index_in_group

    def gateway(self) -> Gateway:
        g = self.model.gateway
        return Gateway(x_m=g.x_m, y_m=g.y_m, antenna_gain_dbi=g.antenna_gain_dbi,
                       tx_power_dbm=g.tx_power_dbm,
                       absolute_sensitivity=None if g.sensitivity is None else g.sensitivity.absolute(),
                       rf=g.rf.gateway() if g.rf is not None else None)

    def gateway_models(self) -> list[GatewayModel]:
        """Toutes les passerelles, dans l'ordre du fichier (une seule si « gateway »)."""
        if self.model.gateways is not None:
            return list(self.model.gateways)
        return [self.model.gateway]

    def gateways(self) -> list[Gateway]:
        return [Gateway(x_m=g.x_m, y_m=g.y_m, antenna_gain_dbi=g.antenna_gain_dbi,
                        tx_power_dbm=g.tx_power_dbm,
                        rx_sensitivity_offset_db=(rx_sensitivity_offset_db(get_profile(g.profile))
                                                  if g.profile is not None else 0.0),
                        rf=g.rf.gateway() if g.rf is not None else None)
                for g in self.gateway_models()]

    @staticmethod
    def _strip_absent_rf(model, dumped) -> None:
        """Retire du hachage les blocs `rf:` absents : hash des scénarios antérieurs inchangé."""
        if model.retransmissions is None:
            dumped.pop("retransmissions", None)
        else:
            # Champs ajoutés par la couche MAC, à leur valeur par défaut : retirés du hachage,
            # comme pour `mac` — le hash des scénarios écrits avant eux reste inchangé.
            bloc = dumped["retransmissions"]
            if model.retransmissions.ack_delay_ms == 0:
                bloc.pop("ack_delay_ms", None)
            if model.retransmissions.ack_repetitions == 1:
                bloc.pop("ack_repetitions", None)
            if model.retransmissions.fcnt_up_start == 0:
                bloc.pop("fcnt_up_start", None)
            if model.retransmissions.fcnt_down_start == 0:
                bloc.pop("fcnt_down_start", None)
            if not model.retransmissions.downlink_payload:
                bloc.pop("downlink_payload", None)
            if not model.retransmissions.session_joins_s:
                bloc.pop("session_joins_s", None)
            if not model.retransmissions.join_requests_s:
                bloc.pop("join_requests_s", None)
            if model.retransmissions.join_retries == 1:
                bloc.pop("join_retries", None)
            if model.retransmissions.join_accept_rx2_fallback:
                bloc.pop("join_accept_rx2_fallback", None)
            if model.retransmissions.join_accept_replays == 0:
                bloc.pop("join_accept_replays", None)
        if model.gateway.rf is None:
            dumped["gateway"].pop("rf", None)
        for groupe, groupe_dump in zip(model.groups, dumped["groups"]):
            if groupe.rf is None:
                groupe_dump.pop("rf", None)
        if model.gateways is not None:
            for passerelle, passerelle_dump in zip(model.gateways, dumped["gateways"]):
                if passerelle.rf is None:
                    passerelle_dump.pop("rf", None)

    def retransmission_options(self):
        """Options de réémission du scénario, ou None si le bloc est absent ou désactivé."""
        return None if self.model.retransmissions is None else self.model.retransmissions.options()

    @property
    def is_multi_gateway(self) -> bool:
        return self.model.gateways is not None

    def propagation(self) -> Propagation:
        p = self.model.propagation
        seed = p.shadowing_seed if p.shadowing_seed is not None else self.model.seed
        return Propagation(frequency_hz=p.frequency_hz, reference_distance_m=p.reference_distance_m,
                           exponent=p.exponent, capture_threshold_db=p.capture_threshold_db,
                           shadowing_sigma_db=p.shadowing_sigma_db, shadowing_seed=seed)


def _positions(g: GroupModel, rng: random.Random) -> list[tuple[float, float]]:
    if isinstance(g.placement, ExplicitPlacement):
        return [(float(x), float(y)) for x, y in g.placement.positions]
    p = g.placement
    out: list[tuple[float, float]] = []
    for _ in range(int(g.count or 0)):
        # Uniforme sur le disque : r = R sqrt(u), theta = 2 pi v.
        r = p.radius_m * math.sqrt(rng.random())
        theta = 2.0 * math.pi * rng.random()
        out.append((p.center_x_m + r * math.cos(theta), p.center_y_m + r * math.sin(theta)))
    return out


def _obstacle_attenuation(o: ObstacleModel, frequency_hz: float) -> float:
    if o.material is None:
        return o.attenuation_db
    loss, extrapolated = traversal_loss(o.material, frequency_hz, o.thickness_m)
    if extrapolated:
        warnings.warn(
            f"matériau {o.material} : fréquence {frequency_hz:g} Hz hors de la plage documentée "
            "(UIT-R P.2040-4, Tableau 3)", stacklevel=3)
    if loss > 200.0:
        raise ValueError(f"atténuation calculée {loss:.1f} dB > 200 dB (matériau {o.material})")
    return loss


def _build_environment(model: EnvironmentModel, base_dir: Path,
                       frequency_hz: float) -> Environment:
    terrain: Optional[Terrain] = None
    if model.terrain is not None:
        root = base_dir.resolve()
        target = (root / model.terrain.path).resolve()
        if root not in target.parents:
            raise ValueError("terrain.path sort du dossier du scénario")
        if not target.is_file():
            raise ValueError(f"fichier de relief introuvable : {model.terrain.path}")
        terrain = load_dem_csv(target)
    obstacles = tuple(
        Obstacle(o.x_min_m, o.y_min_m, o.x_max_m, o.y_max_m, o.height_m,
                 _obstacle_attenuation(o, frequency_hz))
        for o in model.obstacles)
    return Environment(terrain=terrain, obstacles=obstacles,
                       gateway_height_m=model.gateway_height_m,
                       device_height_m=model.device_height_m)


def load_scenario(source: Union[str, Path]) -> Scenario:
    """Charge un scénario depuis un fichier YAML (chemin) ou une chaîne YAML.

    Utilise `yaml.safe_load` : aucun objet Python arbitraire n'est construit.
    Le relief (`terrain.path`) est lu relativement au dossier du fichier YAML ;
    pour une chaîne YAML, relativement au dossier courant.
    """
    base_dir = Path(".")
    if isinstance(source, Path) or (isinstance(source, str) and "\n" not in source
                                    and source.endswith((".yaml", ".yml"))):
        path = Path(source)
        text = path.read_text(encoding="utf-8")
        base_dir = path.parent
    else:
        text = str(source)
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("le scénario doit être un mapping YAML")
    model = ScenarioModel.model_validate(data)
    env = (_build_environment(model.environment, base_dir, model.propagation.frequency_hz)
           if model.environment else None)
    return Scenario(model, env)
