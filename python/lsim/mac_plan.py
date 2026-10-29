"""Calendrier des commandes MAC initiées par le dispositif ou par le serveur (phase 1).

Sens des commandes (LoRaWAN 1.0.x) :
- le dispositif initie LinkCheckReq, en FOpts de l'uplink ;
- le serveur initie DevStatusReq, en FOpts de la descente ; le dispositif y répond
  par DevStatusAns dans un uplink ultérieur (réponses : étape suivante de la phase 1).

Calendrier déterministe :
- uplink de rang `n` (1-based) : LinkCheckReq si `n` est multiple de `link_check_every` ;
- descente de rang `m` (1-based) : DevStatusReq si `m` est multiple de `device_status_every`.
Une période de 0 désactive la commande. Même scénario, mêmes commandes.

Les octets ajoutés (`phy_extra_bytes`) doivent être comptés dans la durée de la trame ; ce
comptage dans le moteur est l'étape suivante de la phase 1.
"""

from __future__ import annotations

from dataclasses import dataclass

from lsim import mac
from lsim.mac import DevStatusReq, LinkCheckReq, MacCommand

MAX_FOPTS = 15


def _check_period(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 1000:
        raise ValueError(f"{name} doit être un entier entre 0 et 1000")


def _check_rank(rank: int) -> None:
    if isinstance(rank, bool) or not isinstance(rank, int) or rank < 1:
        raise ValueError("rank doit être un entier positif (trame 1-based)")


@dataclass(frozen=True)
class MacSchedule:
    """Périodes des commandes MAC ; 0 = désactivé."""

    link_check_every: int = 0  # LinkCheckReq, émise par le dispositif (uplink)
    device_status_every: int = 0  # DevStatusReq, émise par le serveur (descente)

    def __post_init__(self) -> None:
        _check_period("link_check_every", self.link_check_every)
        _check_period("device_status_every", self.device_status_every)

    @property
    def enabled(self) -> bool:
        return self.link_check_every > 0 or self.device_status_every > 0


def uplink_requests(schedule: MacSchedule, rank: int) -> list[MacCommand]:
    """Commandes que le dispositif place en FOpts de l'uplink de rang `rank`."""
    _check_rank(rank)
    if schedule.link_check_every and rank % schedule.link_check_every == 0:
        return [LinkCheckReq()]
    return []


def downlink_requests(schedule: MacSchedule, rank: int) -> list[MacCommand]:
    """Commandes que le serveur place en FOpts de la descente de rang `rank`."""
    _check_rank(rank)
    if schedule.device_status_every and rank % schedule.device_status_every == 0:
        return [DevStatusReq()]
    return []


def _encode(cmds: list[MacCommand]) -> bytes:
    fopts = b""
    for cmd in cmds:
        fopts = mac.append_fopts(fopts, cmd)  # lève StatusError si le champ est plein
    if len(fopts) > MAX_FOPTS:
        raise ValueError("FOpts au-delà de 15 octets")
    return fopts


def uplink_fopts(schedule: MacSchedule, rank: int) -> bytes:
    """FOpts de l'uplink de rang `rank` (vide si aucune demande)."""
    return _encode(uplink_requests(schedule, rank))


def downlink_fopts(schedule: MacSchedule, rank: int) -> bytes:
    """FOpts de la descente de rang `rank` (vide si aucune demande)."""
    return _encode(downlink_requests(schedule, rank))


def uplink_extra_bytes(schedule: MacSchedule, rank: int) -> int:
    """Octets que les commandes MAC ajoutent à l'uplink de rang `rank`."""
    return len(uplink_fopts(schedule, rank))
