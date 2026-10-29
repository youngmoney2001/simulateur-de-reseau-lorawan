"""Calendrier des commandes MAC et réservations d'octets pour le temps d'antenne (phase 1).

Règles, toutes indexées par le rang 1-based de l'émission du dispositif (uplink de rang n) :

- LinkCheckReq (uplink) : le dispositif l'envoie dans l'uplink de rang n si n est multiple de
  `link_check_every`. Son octet est donc certain : il est réservé dans cette émission.
- DevStatusReq (descente) : le serveur la place dans le downlink répondant à l'uplink de rang n
  si n est multiple de `device_status_every` et si cet uplink est reçu. La requête n'est pas
  certaine (réception, fenêtre RX1).
- DevStatusAns (uplink) : le dispositif répond dans son uplink suivant (rang n + 1) si la requête
  lui est parvenue. Sa présence est conditionnelle : le calendrier ne réserve donc que la taille
  (3 octets) dans l'uplink n + 1, sans prétendre qu'elle sera émise. Si la requête n'arrive pas,
  l'octet réservé n'est pas transmis (réservation conservatrice).

Une période de 0 désactive la commande. Même scénario, mêmes réservations.
"""

from __future__ import annotations

from dataclasses import dataclass

from lsim import mac
from lsim.mac import LinkCheckReq, MacCommand

MAX_FOPTS = 15
# Tailles des commandes en FOpts : CID seul pour LinkCheckReq, CID + batterie + marge pour DevStatusAns.
LINK_CHECK_REQ_BYTES = 1
DEVICE_STATUS_ANS_BYTES = 3


def _check_period(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 1000:
        raise ValueError(f"{name} doit être un entier entre 0 et 1000")


def _check_rank(rank: int) -> None:
    if isinstance(rank, bool) or not isinstance(rank, int) or rank < 1:
        raise ValueError("rank doit être un entier positif (trame 1-based)")


@dataclass(frozen=True)
class MacSchedule:
    """Périodes des commandes MAC ; 0 = désactivé."""

    link_check_every: int = 0  # LinkCheckReq émise par le dispositif (uplink de rang multiple de N)
    device_status_every: int = 0  # DevStatusReq émise par le serveur (uplink reçu de rang multiple de N)
    link_margin_installation_db: int = 0  # marge d'installation soustraite de la marge rapportée

    def __post_init__(self) -> None:
        _check_period("link_check_every", self.link_check_every)
        _check_period("device_status_every", self.device_status_every)
        if (isinstance(self.link_margin_installation_db, bool)
                or not isinstance(self.link_margin_installation_db, int)
                or not 0 <= self.link_margin_installation_db <= 60):
            raise ValueError("link_margin_installation_db doit être un entier entre 0 et 60")

    @property
    def enabled(self) -> bool:
        return self.link_check_every > 0 or self.device_status_every > 0


def uplink_requests(schedule: MacSchedule, rank: int) -> list[MacCommand]:
    """Commandes que le dispositif place en FOpts de l'uplink de rang `rank` (certaines)."""
    _check_rank(rank)
    if schedule.link_check_every and rank % schedule.link_check_every == 0:
        return [LinkCheckReq()]
    return []


def device_status_request_due(schedule: MacSchedule, rank: int) -> bool:
    """Le serveur émet DevStatusReq dans le downlink répondant à l'uplink de rang `rank`, si ce
    uplink est reçu (la réception n'est pas garantie ici)."""
    _check_rank(rank)
    return bool(schedule.device_status_every) and rank % schedule.device_status_every == 0


def reserved_extra_bytes(schedule: MacSchedule, rank: int) -> int:
    """Octets MAC à réserver dans l'uplink de rang `rank` pour le temps d'antenne.

    LinkCheckReq : certain. DevStatusAns : réservé dans l'uplink suivant une requête planifiée
    (conservatif, même si la requête n'est pas reçue).
    """
    _check_rank(rank)
    extra = LINK_CHECK_REQ_BYTES * len(uplink_requests(schedule, rank))
    if rank >= 2 and device_status_request_due(schedule, rank - 1):
        extra += DEVICE_STATUS_ANS_BYTES
    if extra > MAX_FOPTS:
        raise ValueError("réservation au-delà de 15 octets de FOpts")
    return extra


def reservations(schedule: MacSchedule, messages: int) -> list[tuple[int, int]]:
    """Calendrier (rang, octets) des émissions d'un dispositif de `messages` émissions."""
    out = []
    for rank in range(1, messages + 1):
        extra = reserved_extra_bytes(schedule, rank)
        if extra:
            out.append((rank, extra))
    return out


def uplink_fopts(schedule: MacSchedule, rank: int) -> bytes:
    """FOpts certains de l'uplink de rang `rank` (LinkCheckReq seulement ; DevStatusAns dépend de la
    réception et n'est pas encodé ici)."""
    fopts = b""
    for cmd in uplink_requests(schedule, rank):
        fopts = mac.append_fopts(fopts, cmd)  # lève StatusError si le champ est plein
    return fopts

