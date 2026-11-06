"""Frontal RF v4 : gain d'antenne et perte de câble, par terminal et par passerelle.

Un champ laissé à `None` **n'existe pas** : il n'est pas transmis au cœur et ne vaut pas 0 par
convention. Cette distinction est le contrat du bit `present` côté C (`LSIM_RF_HAS_ANTENNA_GAIN`,
`LSIM_RF_HAS_CABLE_LOSS`) : un gain absent n'est pas un gain nul, c'est une donnée non fournie.

L'antenne est réciproque : la chaîne `gain - perte` s'applique au montant comme au descendant,
et le gain n'est compté qu'une fois.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from ._native import _CDeviceRf, _CGatewayRf

# Bits de présence, alignés sur core/include/lsim/c_api.h.
HAS_ANTENNA_GAIN = 1
HAS_CABLE_LOSS = 2

MAX_ANTENNA_GAIN_DBI = 40.0
MAX_CABLE_LOSS_DB = 40.0


def _check(name: str, value: Optional[float], low: float, high: float) -> None:
    if value is None:
        return
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{name} doit être un nombre ou None")
    if not math.isfinite(value):
        raise ValueError(f"{name} doit être un nombre fini")
    if not low <= float(value) <= high:
        raise ValueError(f"{name} doit être compris entre {low} et {high}")


class _Frontend:
    """Partie commune : présence indépendante des deux champs, chaîne et conversion C."""

    antenna_gain_dbi: Optional[float]
    cable_loss_db: Optional[float]

    @property
    def present(self) -> int:
        bits = 0
        if self.antenna_gain_dbi is not None:
            bits |= HAS_ANTENNA_GAIN
        if self.cable_loss_db is not None:
            bits |= HAS_CABLE_LOSS
        return bits

    def chain_db(self) -> float:
        """Chaîne d'émission/réception : gain moins perte, champs absents ignorés."""
        gain = 0.0 if self.antenna_gain_dbi is None else float(self.antenna_gain_dbi)
        loss = 0.0 if self.cable_loss_db is None else float(self.cable_loss_db)
        return gain - loss

    def _to_struct(self, struct):
        out = struct()
        out.present = self.present
        # Les champs absents restent à zéro : ils ne sont pas lus par le cœur.
        out.antenna_gain_dbi = 0.0 if self.antenna_gain_dbi is None else float(self.antenna_gain_dbi)
        out.cable_loss_db = 0.0 if self.cable_loss_db is None else float(self.cable_loss_db)
        return out


@dataclass(frozen=True)
class DeviceRf(_Frontend):
    """Frontal d'un terminal. `None` = champ absent (jamais zéro implicite)."""

    antenna_gain_dbi: Optional[float] = None
    cable_loss_db: Optional[float] = None

    def __post_init__(self) -> None:
        _check("antenna_gain_dbi", self.antenna_gain_dbi, -MAX_ANTENNA_GAIN_DBI, MAX_ANTENNA_GAIN_DBI)
        _check("cable_loss_db", self.cable_loss_db, 0.0, MAX_CABLE_LOSS_DB)

    def to_c(self) -> _CDeviceRf:
        return self._to_struct(_CDeviceRf)


@dataclass(frozen=True)
class GatewayRf(_Frontend):
    """Frontal d'une passerelle. Le gain présent remplace le scalaire de la passerelle."""

    antenna_gain_dbi: Optional[float] = None
    cable_loss_db: Optional[float] = None

    def __post_init__(self) -> None:
        _check("antenna_gain_dbi", self.antenna_gain_dbi, -MAX_ANTENNA_GAIN_DBI, MAX_ANTENNA_GAIN_DBI)
        _check("cable_loss_db", self.cable_loss_db, 0.0, MAX_CABLE_LOSS_DB)

    def to_c(self) -> _CGatewayRf:
        return self._to_struct(_CGatewayRf)


def device_table(entries, struct):
    """Table C de frontaux : 0 entrée (None/vide) ou complète, jamais partielle."""
    if entries is None:
        return None, 0
    entries = tuple(entries)
    if not entries:
        return None, 0
    table = (struct * len(entries))()
    for i, entry in enumerate(entries):
        table[i] = entry.to_c()
    return table, len(entries)


def gateway_table(entries):
    """Table C de frontaux passerelles."""
    return device_table(entries, _CGatewayRf)


def gateway_entry(entry: Optional[GatewayRf]):
    """Frontal passerelle unique : None ou une entrée."""
    if entry is None:
        return None
    return entry.to_c()
