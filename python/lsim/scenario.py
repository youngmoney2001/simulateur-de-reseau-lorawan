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
from pathlib import Path
from typing import Annotated, Literal, Optional, Union

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from lsim.simulator import EndDevice, Gateway, Propagation

SCHEMA_VERSION = 1
MAX_DEVICES = 10_000
MAX_TRANSMISSIONS = 5_000_000
_NS_PER_S = 1_000_000_000


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GatewayModel(_Strict):
    x_m: float = 0.0
    y_m: float = 0.0
    antenna_gain_dbi: float = 0.0


class PropagationModel(_Strict):
    frequency_hz: float = 868.1e6
    reference_distance_m: float = Field(1.0, gt=0)
    exponent: float = Field(2.7, ge=1.0, le=6.0)
    capture_threshold_db: float = Field(6.0, ge=0)


class DiskPlacement(_Strict):
    type: Literal["disk"]
    radius_m: float = Field(gt=0)
    center_x_m: float = 0.0
    center_y_m: float = 0.0


class ExplicitPlacement(_Strict):
    type: Literal["explicit"]
    positions: list[tuple[float, float]] = Field(min_length=1)


Placement = Annotated[Union[DiskPlacement, ExplicitPlacement], Field(discriminator="type")]


class GroupModel(_Strict):
    name: str = Field(min_length=1, max_length=64)
    count: Optional[int] = Field(default=None, ge=1, le=MAX_DEVICES)
    placement: Placement
    spreading_factor: int = Field(7, ge=7, le=12)
    payload_bytes: int = Field(10, ge=0, le=255)
    tx_power_dbm: float = 14.0
    period_s: float = Field(600.0, gt=0)
    messages: int = Field(1, ge=1)
    start_spread_s: float = Field(0.0, ge=0)

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


class ScenarioModel(_Strict):
    schema_version: Literal[1]
    name: str = Field(min_length=1, max_length=128)
    seed: int = Field(0, ge=0, le=2**32 - 1)
    gateway: GatewayModel = GatewayModel()
    propagation: PropagationModel = PropagationModel()
    groups: list[GroupModel] = Field(min_length=1)

    @model_validator(mode="after")
    def _limits(self) -> "ScenarioModel":
        names = [g.name for g in self.groups]
        if len(set(names)) != len(names):
            raise ValueError("les noms de groupes doivent être uniques")
        devices = sum(g.device_count for g in self.groups)
        if devices > MAX_DEVICES:
            raise ValueError(f"au plus {MAX_DEVICES} dispositifs (demandé : {devices})")
        transmissions = sum(g.device_count * g.messages for g in self.groups)
        if transmissions > MAX_TRANSMISSIONS:
            raise ValueError(f"au plus {MAX_TRANSMISSIONS} transmissions (demandé : {transmissions})")
        return self


class Scenario:
    """Scénario validé, prêt à être déployé et simulé."""

    def __init__(self, model: ScenarioModel) -> None:
        self.model = model
        canonical = json.dumps(model.model_dump(mode="json"), sort_keys=True,
                               separators=(",", ":"), ensure_ascii=False)
        self.sha256 = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @property
    def name(self) -> str:
        return self.model.name

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
                    start_offset_ns=offset, period_ns=period_ns, messages=g.messages))
                group_of.append(g.name)
                index_in_group.append(i)
        return devices, group_of, index_in_group

    def gateway(self) -> Gateway:
        g = self.model.gateway
        return Gateway(x_m=g.x_m, y_m=g.y_m, antenna_gain_dbi=g.antenna_gain_dbi)

    def propagation(self) -> Propagation:
        p = self.model.propagation
        return Propagation(frequency_hz=p.frequency_hz, reference_distance_m=p.reference_distance_m,
                           exponent=p.exponent, capture_threshold_db=p.capture_threshold_db)


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


def load_scenario(source: Union[str, Path]) -> Scenario:
    """Charge un scénario depuis un fichier YAML (chemin) ou une chaîne YAML.

    Utilise `yaml.safe_load` : aucun objet Python arbitraire n'est construit.
    """
    if isinstance(source, Path) or (isinstance(source, str) and "\n" not in source
                                    and source.endswith((".yaml", ".yml"))):
        text = Path(source).read_text(encoding="utf-8")
    else:
        text = str(source)
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("le scénario doit être un mapping YAML")
    return Scenario(ScenarioModel.model_validate(data))
