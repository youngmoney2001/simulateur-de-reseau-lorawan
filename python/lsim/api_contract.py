"""Contrat d'API moteur ↔ navigateur (v1) : modèles de requêtes, réponses et événements.

Ce module ne sert aucune requête. Il définit les formes de données échangées, et les schémas JSON
publiés dans `schemas/api/v1/` (générés par `write_schemas`, vérifiés par les tests). Le texte
normatif est dans `docs/API_CONTRACT.md`.

Principes :
- Le navigateur ne lit jamais de fichier du serveur : le relief passe par un catalogue côté serveur
  (`terrain` refusé dans le scénario d'API).
- Aucune clé de session ou de jointure ne figure dans une réponse.
- Les réponses de liste sont paginées ; aucune réponse n'excède `MAX_BODY_BYTES`.
- L'horloge de simulation est une lecture du journal d'événements (pas de calcul côté navigateur).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from lsim.plan import Plan, get_plan, plan_names
from lsim.scenario import ScenarioModel

API_VERSION = "v1"
MAX_BODY_BYTES = 262_144                 # corps de requête et réponses JSON non paginées
MAX_TRACE_EVENTS_PER_RUN = 200_000       # au-delà, le run est refusé (pas tronqué en silence)
MAX_PAGE_SIZE = 500                      # événements par page
MAX_HOPS_PER_EVENT = 8                   # appareil -> passerelle -> serveur -> passerelle -> appareil...
ENERGY_PROFILES = ("rak4631", "sx1262-stm32l072")

RunState = Literal["queued", "running", "done", "failed", "cancelled"]
ProblemCode = Literal[
    "validation_error", "not_found", "limit_exceeded", "terrain_not_allowed",
    "run_failed", "conflict", "unsupported_region", "unauthorized",
]
EventKind = Literal[
    "join_request", "join_accept", "uplink", "ack", "downlink",
    "lost_sensitivity", "lost_collision", "rx_window_missed",
]
HopOutcome = Literal["delivered", "lost_sensitivity", "lost_collision", "not_listened", "sent"]


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


class ValidateRequest(_Strict):
    scenario: ApiScenario


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


class RunCreate(_Strict):
    scenario: ApiScenario
    energy_profile: Optional[Literal["rak4631", "sx1262-stm32l072"]] = None
    protocol: ProtocolOptionsIn = ProtocolOptionsIn()


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
    spreading_factor: int = Field(ge=7, le=12)
    sent: int = Field(ge=0)
    received: int = Field(ge=0)
    lost_sensitivity: int = Field(ge=0)
    lost_collision: int = Field(ge=0)
    airtime_ns: int = Field(ge=0)
    energy_per_message_j: Optional[float] = None
    average_current_ua: Optional[float] = None


class RunSummary(_Strict):
    run_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,64}$")
    scenario_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    seed: int = Field(ge=0)
    totals: Totals
    pdr: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    gateway: GatewayLoadOut
    energy_profile: Optional[str] = None


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


# --- Schémas publiés --------------------------------------------------------------------------

_MODELS = {
    "scenario_input": ApiScenario,
    "validate_request": ValidateRequest,
    "validate_response": ValidateResponse,
    "run_create": RunCreate,
    "run_status": RunStatus,
    "run_summary": RunSummary,
    "device_page": DevicePage,
    "trace_page": TracePage,
    "trace_event": TraceEvent,
    "problem": Problem,
    "region_list": RegionList,
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
