"""Contrat Python de l'ABI v3 de la boucle fermée (étape 6.2.7) : configuration canal, sorties
terminales et trace v3.

Ce module ne transporte aucune requête et n'appelle aucune fonction C. Il décrit les formes des
structures `lsim_channel_device_v3`, `lsim_channel_terminal_v3` et `lsim_loop_trace_v3` de
`core/include/lsim/c_api.h`, et publie leurs schémas JSON dans `schemas/abi/v3/` (générés par
`write_schemas`, vérifiés par `python/tests/test_abi_v3_contract.py`).

La liaison ctypes à `lsim_simulate_closed_loop_v3` est dans `lsim/closed_loop_v3.py` (étape 6.3), seul
module qui la référence. Le chemin Python `scenario` (`mac.device_channels`, `mac.server_channel_plan`)
reste refusé et n'emprunte pas ce contrat.

Les valeurs numériques sont celles du contrat 6.1 gelé : la trace et les codes d'erreur sont
vérifiés contre l'en-tête C par les tests, pas seulement documentés.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

ABI_VERSION = 3

# Emplacements de canal de l'ABI (A1) et canaux réellement supportés par le moteur.
CHANNEL_ABI_SLOTS = 80            # indices 0..79
CHANNEL_SUPPORTED_MAX = 16        # indices 0..15 ; 16..79 refusés (INDEX_UNSUPPORTED)
MAX_END_DEVICES = 10_000          # kMaxEndDevices (code historique TooManyDevices)

# Sentinelles et constantes de la trace (valeurs brutes de l'ABI).
DOWNLINK_NO_INDEX = 0xFFFFFFFF    # `downlink` sans objet
STATUS_NONE = 0xFF                # `status` sans objet
FIELD_IGNORE = 15                 # DR ou puissance ignorés dans une LinkADRReq

# Codes d'erreur de la fonction v3 : LSIM_STATUS_CHANNEL_<NOM> = 1000 + n (A8 : codes historiques
# conservés, collision 800 conservée). Table complète, vérifiée contre c_api.h.
CHANNEL_STATUS_CODES: dict[str, int] = {
    "ARGS_SIZE": 1001,
    "ABI_VERSION": 1002,
    "ELEMENT_SIZE": 1003,
    "PLAN": 1004,
    "MODE": 1005,
    "DEVICE_INDEX": 1006,
    "PRESENT_FLAG": 1007,
    "FIELDS_WITHOUT_PRESENT": 1008,
    "RESERVED_NONZERO": 1009,
    "INDEX_UNSUPPORTED": 1010,
    "DR_MASK_INVALID": 1011,
    "ENABLED_UNDEFINED": 1012,
    "ENABLED_EMPTY": 1013,
    "SERVER_VIEW_EMPTY": 1014,
    "TRACE_MODE": 1015,
    "TRACE_BUFFER_TOO_SMALL": 1016,
    "TERMINAL_BUFFER_TOO_SMALL": 1017,
    "BUFFERS_ALIASED": 1018,
    "NULL_POINTER": 1019,
    "RANGE_OVERFLOW": 1020,
    "MISALIGNED": 1021,
}

# Valeurs des énumérations de la trace (LSIM_TRACE_*), reprises des énumérations internes.
TRACE_KIND_VALUES: dict[str, int] = {
    "uplink": 0, "link_adr_ans": 1, "exclusion": 2, "adr_decision": 3,
    "link_adr_req": 4, "downlink": 5, "apply": 6,
}
TRACE_ORIGIN_VALUES: dict[str, int] = {"normative": 0, "simulator_policy": 1, "radio": 2}
TRACE_ACTION_VALUES: dict[str, int] = {"created": 0, "renewed": 1, "expired": 2}
TRACE_TARGET_VALUES: dict[str, int] = {"data_rate": 0, "power": 1, "channel": 2, "mask": 3}
TRACE_LOSS_VALUES: dict[str, int] = {
    "none": 0, "device_transmitting": 1, "no_gateway_slot": 2, "below_sensitivity": 3,
}
TRACE_CHANNEL_REASON_VALUES: dict[str, int] = {
    "ok": 0, "rfu_cntl": 1, "undefined_channel": 2, "all_disabled": 3,
    "incompatible_with_data_rate": 4, "rfu_bits": 5,
}
TRACE_DR_REASON_VALUES: dict[str, int] = {
    "ok": 0, "ignored": 1, "unknown_dr": 2, "not_supported_by_channels": 3,
}
TRACE_POWER_REASON_VALUES: dict[str, int] = {"ok": 0, "ignored": 1, "reserved": 2}

# Types d'événements qui portent un indice de descente, un statut ACK, un motif de perte.
TRACE_KINDS_WITH_DOWNLINK = frozenset({"link_adr_req", "downlink", "apply"})
TRACE_KINDS_WITH_STATUS = frozenset({"link_adr_ans", "apply"})
TRACE_KINDS_WITH_REASONS = frozenset({"apply"})
TRACE_KINDS_WITH_VALUE = frozenset({"exclusion", "downlink"})  # `value` = 0 pour les autres types

# `value` d'un downlink = masque de commandes (kLoopCmd*) : seuls les cinq bits connus.
TRACE_DOWNLINK_COMMAND_BITS = {"link_adr": 0x01, "duty_cycle": 0x02, "link_check": 0x04,
                               "device_time": 0x08, "dev_status": 0x10}
TRACE_DOWNLINK_COMMAND_MASK = sum(TRACE_DOWNLINK_COMMAND_BITS.values())  # 0x1F

# Bornes de `value` pour une exclusion, par cible. Power : 8 à 14 sont des index réservés (RP002 Table 13),
# refusables par le terminal puis exclus ; 15 est la valeur ignorée et n'est jamais exclu.
TRACE_EXCLUSION_VALUE_MAX: dict[str, int] = {"data_rate": 15, "power": 14, "channel": 15, "mask": 65535}

# `flag` de link_adr_ans = indicateur d'acceptation complète : égal à (status == 0x07).
TRACE_LINK_ADR_ACCEPTED_STATUS = 0x07

ChannelPlanName = Literal["none", "eu868_rp002_1_0_5"]
TraceKind = Literal["uplink", "link_adr_ans", "exclusion", "adr_decision", "link_adr_req", "downlink", "apply"]
TraceOrigin = Literal["normative", "simulator_policy", "radio"]
TraceAction = Literal["created", "renewed", "expired"]
TraceTarget = Literal["data_rate", "power", "channel", "mask"]
TraceLoss = Literal["none", "device_transmitting", "no_gateway_slot", "below_sensitivity"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _code(name: str) -> str:
    """Nom complet du code d'erreur, pour les messages : « LSIM_STATUS_CHANNEL_X (1010) »."""
    return f"LSIM_STATUS_CHANNEL_{name} ({CHANNEL_STATUS_CODES[name]})"


class ChannelDefinitionV3(_Strict):
    """Débits supportés par un canal défini (dr_mask : bit n = DRn). Un canal absent n'est pas défini."""

    index: int = Field(ge=0, lt=CHANNEL_ABI_SLOTS)
    dr_mask: int = Field(ge=1, le=255)


class ChannelElementV3(_Strict):
    """Configuration d'un dispositif (une entrée par `device_index`).

    `present = false` : tous les autres champs doivent être vides ; le moteur applique les valeurs par
    défaut EU868 (canaux 0..2, DR0..DR5 ; vue serveur 0..2). `present = true` : configuration explicite.
    Les canaux 16..79 sont des emplacements de l'ABI mais sont refusés (A1).
    """

    device_index: int = Field(ge=0, lt=MAX_END_DEVICES)
    present: bool
    defined: list[ChannelDefinitionV3] = Field(default_factory=list, max_length=CHANNEL_ABI_SLOTS)
    enabled: list[int] = Field(default_factory=list, max_length=CHANNEL_ABI_SLOTS)
    server_defined: list[int] = Field(default_factory=list, max_length=CHANNEL_ABI_SLOTS)

    @model_validator(mode="after")
    def _rules(self) -> "ChannelElementV3":
        if not self.present:
            if self.defined or self.enabled or self.server_defined:
                raise ValueError(f"present = false : champs vides requis ({_code('FIELDS_WITHOUT_PRESENT')})")
            return self
        defined_idx = [d.index for d in self.defined]
        if len(set(defined_idx)) != len(defined_idx):
            raise ValueError(f"canal défini en double ({_code('DR_MASK_INVALID')})")
        for name, values in (("defined", defined_idx), ("enabled", self.enabled),
                             ("server_defined", self.server_defined)):
            if len(set(values)) != len(values):
                raise ValueError(f"{name} : indice en double")
            for v in values:
                if v >= CHANNEL_SUPPORTED_MAX:
                    raise ValueError(f"{name} : canal {v} hors de 0..15 ({_code('INDEX_UNSUPPORTED')})")
        if not self.enabled:
            raise ValueError(f"aucun canal actif ({_code('ENABLED_EMPTY')})")
        if not self.server_defined:
            raise ValueError(f"vue serveur vide ({_code('SERVER_VIEW_EMPTY')})")
        for ch in self.enabled:
            if ch not in defined_idx:
                raise ValueError(f"canal actif {ch} non défini ({_code('ENABLED_UNDEFINED')})")
        return self


class ChannelSetV3(_Strict):
    """Configuration canal d'un appel v3.

    Mode historique : `channel_plan = none` et aucun élément (équivalent à `channels = NULL`,
    `channel_count = 0`) : le moteur utilise son chemin historique, sans configuration.
    Mode explicite : `channel_plan = eu868_rp002_1_0_5` et exactement un élément par dispositif
    (`channel_count == device_count`, indices de dispositifs uniques et couvrant 0..device_count-1).
    """

    channel_plan: ChannelPlanName = "none"
    elements: Optional[list[ChannelElementV3]] = Field(default=None, max_length=MAX_END_DEVICES)

    @model_validator(mode="after")
    def _mode(self) -> "ChannelSetV3":
        has_elements = bool(self.elements)
        if self.channel_plan == "none" and has_elements:
            raise ValueError(f"élément canal sans plan EU868 ({_code('MODE')})")
        if self.channel_plan == "eu868_rp002_1_0_5" and not has_elements:
            raise ValueError(f"plan EU868 sans élément canal ({_code('MODE')})")
        return self

    @property
    def is_historical(self) -> bool:
        return self.channel_plan == "none" and not self.elements

    def validate_for_devices(self, device_count: int) -> None:
        """Vérifie la correspondance avec `device_count` : un élément par dispositif, sans doublon."""
        if self.is_historical:
            return
        elements = self.elements or []
        if len(elements) != device_count:
            raise ValueError(f"channel_count doit égaler device_count ({_code('MODE')})")
        indices = [e.device_index for e in elements]
        if len(set(indices)) != len(indices) or any(i >= device_count for i in indices):
            raise ValueError(f"device_index hors plage ou en double ({_code('DEVICE_INDEX')})")


class TerminalStateV3(_Strict):
    """État final d'un terminal (sortie). Les canaux définis et actifs sont listés explicitement."""

    device_index: int = Field(ge=0, lt=MAX_END_DEVICES)
    dr: int = Field(ge=0, le=255)
    power_index: int = Field(ge=0, le=255)
    defined: list[ChannelDefinitionV3] = Field(default_factory=list, max_length=CHANNEL_ABI_SLOTS)
    enabled: list[int] = Field(default_factory=list, max_length=CHANNEL_ABI_SLOTS)


def _trace_event_schema_extra(schema: dict, _cls: type) -> None:
    """Ajoute au schéma JSON les règles conditionnelles de la trace (miroir des validateurs Python)."""
    all_kinds = set(TRACE_KIND_VALUES)

    def when_kind(kinds, then):
        return {"if": {"properties": {"kind": {"enum": sorted(kinds)}}, "required": ["kind"]}, "then": then}

    def complement(kinds):
        return all_kinds - set(kinds)

    rules = [
        when_kind(TRACE_KINDS_WITH_DOWNLINK, {"required": ["downlink"], "properties": {"downlink": {
            "type": "integer", "minimum": 0, "maximum": 2**32 - 2}}}),
        when_kind(complement(TRACE_KINDS_WITH_DOWNLINK), {"properties": {"downlink": {"type": "null"}}}),
        when_kind(TRACE_KINDS_WITH_STATUS, {"required": ["status"], "properties": {"status": {
            "type": "integer", "minimum": 0, "maximum": 7}}}),
        when_kind(complement(TRACE_KINDS_WITH_STATUS), {"properties": {"status": {"type": "null"}}}),
        when_kind(complement({"downlink"}), {"properties": {"loss": {"const": "none"}}}),
        when_kind(complement(TRACE_KINDS_WITH_REASONS), {"properties": {
            "reason_channel": {"const": 0}, "reason_dr": {"const": 0}, "reason_power": {"const": 0}}}),
        when_kind(complement(TRACE_KINDS_WITH_VALUE), {"properties": {"value": {"const": 0}}}),
        when_kind({"downlink"}, {"properties": {"value": {"maximum": TRACE_DOWNLINK_COMMAND_MASK,
                                                          "minimum": 0}}}),
        when_kind({"link_adr_req"}, {"properties": {"flag": {"const": False}}}),
        {"if": {"properties": {"kind": {"const": "link_adr_ans"}, "status": {"const": TRACE_LINK_ADR_ACCEPTED_STATUS}},
                "required": ["kind", "status"]},
         "then": {"properties": {"flag": {"const": True}}}},
        {"if": {"properties": {"kind": {"const": "link_adr_ans"},
                               "status": {"not": {"const": TRACE_LINK_ADR_ACCEPTED_STATUS}}},
                "required": ["kind", "status"]},
         "then": {"properties": {"flag": {"const": False}}}},
        {"if": {"properties": {"kind": {"const": "downlink"}, "loss": {"const": "none"}},
                "required": ["kind", "loss"]},
         "then": {"properties": {"flag": {"const": True}}}},
        {"if": {"properties": {"kind": {"const": "downlink"}, "loss": {"not": {"const": "none"}}},
                "required": ["kind", "loss"]},
         "then": {"properties": {"flag": {"const": False}}}},
    ]
    for target, bound in TRACE_EXCLUSION_VALUE_MAX.items():
        rules.append({"if": {"properties": {"kind": {"const": "exclusion"}, "target": {"const": target}},
                             "required": ["kind", "target"]},
                      "then": {"properties": {"value": {"minimum": 0, "maximum": bound}}}})
    schema["allOf"] = rules


class TraceEventV3(_Strict):
    """Événement de trace v3 (sortie). Les sentinelles sont exprimées par `null` :
    `downlink` null = 0xFFFFFFFF, `status` null = 0xFF. Les autres champs sans objet valent 0.

    `value` : exclusion = valeur de la cible (bornes par cible, voir TRACE_EXCLUSION_VALUE_MAX) ;
    downlink = masque de commandes (0x01, 0x02, 0x04, 0x08, 0x10) ; 0 pour tous les autres types.
    `flag` : link_adr_ans = (status == 0x07) ; link_adr_req = false (sans objet) ; downlink = reçue.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, json_schema_extra=_trace_event_schema_extra)

    t_ns: int = Field(ge=0)
    device: int = Field(ge=0, lt=MAX_END_DEVICES)
    uplink: int = Field(ge=0, le=2**32 - 1)
    downlink: Optional[int] = Field(default=None, ge=0, le=2**32 - 2)
    kind: TraceKind
    origin: TraceOrigin
    action: TraceAction = "created"
    target: TraceTarget = "data_rate"
    loss: TraceLoss = "none"
    status: Optional[int] = Field(default=None, ge=0, le=7)
    dr: int = Field(ge=0, le=255)
    power_index: int = Field(ge=0, le=255)
    channel_mask: int = Field(ge=0, le=65535)
    value: int = Field(ge=0, le=65535)
    flag: bool = False
    reason_channel: int = Field(default=0, ge=0, le=5)
    reason_dr: int = Field(default=0, ge=0, le=3)
    reason_power: int = Field(default=0, ge=0, le=2)

    @model_validator(mode="after")
    def _flags_and_values(self) -> "TraceEventV3":
        if self.kind == "link_adr_ans" and self.flag != (self.status == TRACE_LINK_ADR_ACCEPTED_STATUS):
            raise ValueError("flag : égal à (status == 0x07) pour link_adr_ans")
        if self.kind == "link_adr_req" and self.flag:
            raise ValueError("flag : sans objet pour link_adr_req (doit être faux)")
        if self.kind not in TRACE_KINDS_WITH_VALUE and self.value != 0:
            raise ValueError(f"value : 0 requis pour {self.kind}")
        if self.kind == "downlink" and self.value & ~TRACE_DOWNLINK_COMMAND_MASK:
            raise ValueError(f"value : commandes hors des cinq bits connus (0x{TRACE_DOWNLINK_COMMAND_MASK:02X})")
        if self.kind == "exclusion":
            bound = TRACE_EXCLUSION_VALUE_MAX[self.target]
            if self.value > bound:
                raise ValueError(f"value : exclusion {self.target} au plus {bound}")
        return self

    @model_validator(mode="after")
    def _conditional_fields(self) -> "TraceEventV3":
        if (self.status is not None) != (self.kind in TRACE_KINDS_WITH_STATUS):
            raise ValueError("status : présent seulement pour link_adr_ans et apply (sinon sentinelle 0xFF)")
        if (self.downlink is not None) != (self.kind in TRACE_KINDS_WITH_DOWNLINK):
            raise ValueError("downlink : indice seulement pour link_adr_req, downlink et apply "
                             "(sinon sentinelle 0xFFFFFFFF)")
        if self.kind != "downlink" and self.loss != "none":
            raise ValueError("loss : cause de perte seulement pour downlink (sinon 0)")
        if self.kind == "downlink" and self.flag != (self.loss == "none"):
            raise ValueError("downlink : reçue (flag vrai) si et seulement si aucune cause de perte")
        if self.kind not in TRACE_KINDS_WITH_REASONS and (
                self.reason_channel or self.reason_dr or self.reason_power):
            raise ValueError("motifs reason_* : seulement pour apply (sinon 0)")
        return self


def trace_raw_downlink(event: TraceEventV3) -> int:
    """Valeur brute ABI de `downlink` (0xFFFFFFFF si sans objet)."""
    return DOWNLINK_NO_INDEX if event.downlink is None else event.downlink


def trace_raw_status(event: TraceEventV3) -> int:
    """Valeur brute ABI de `status` (0xFF si sans objet)."""
    return STATUS_NONE if event.status is None else event.status


# Schémas publiés. Les noms de fichiers suivent `schemas/abi/v3/<nom>.schema.json`.
PUBLISHED_MODELS: dict[str, type[BaseModel]] = {
    "closed_loop_v3_channel_set": ChannelSetV3,
    "closed_loop_v3_terminal_state": TerminalStateV3,
    "closed_loop_v3_trace_event": TraceEventV3,
}


def schemas() -> dict[str, dict]:
    return {name: model.model_json_schema() for name, model in sorted(PUBLISHED_MODELS.items())}


def write_schemas(directory: Path) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    for name, schema in schemas().items():
        path = directory / f"{name}.schema.json"
        path.write_text(json.dumps(schema, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        written.append(path)
    return written


if __name__ == "__main__":
    import sys

    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("schemas/abi/v3")
    for p in write_schemas(target):
        print(p)
