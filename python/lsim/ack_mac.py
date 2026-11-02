"""Couche MAC de l'ACK : quand la passerelle émet, quand le terminal écoute, ce qu'il retient.

Le cœur planifie une descente unique à `fin + RECEIVE_DELAY1` et abandonne celle qui ne tient pas
dans la fenêtre RX1 (`DownlinkScheduler::on_received` renvoie `nullopt`). Ce modèle-là ne peut donc
produire **ni ACK tardif, ni ACK dupliqué** : ils sont impossibles par construction.

Cette couche les rend possibles, sans toucher au cœur ni à l'ABI :

- le réseau peut répondre avec un retard (`delay_ms`) — un serveur lent ne sait pas que la fenêtre
  est fermée : il émet quand même, l'airtime est consommée et la passerelle est bloquée ;
- le réseau peut répéter la trame d'acquittement (`repetitions`) — c'est le même `FCntDown` ; le
  terminal ne doit en retenir qu'un seul, les copies suivantes sont ignorées.

Trois fenêtres, conformes à la classe A de LoRaWAN 1.0.4 :

| Fenêtre | Ouverture | Durée |
|---|---|---|
| RX1 | `fin + RECEIVE_DELAY1` (1 s) | 1 s |
| RX2 | `fin + RECEIVE_DELAY2` (2 s) | 1 s |

La réception n'est **pas** recalculée ici : la recette radio (réciprocité, sensibilité, marge du
récepteur) est celle du cœur, reprise à l'identique et vérifiée par un test de parité contre
`plan_native`. Cette couche ne fait que replacer la transmission dans le temps et décider si elle
tombe dans une fenêtre écoutée.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Sequence

from lsim.trace_events import DeviceRadio
from lsim.radio import receiver_sensitivity_dbm

RX1_DELAY_NS = 1_000_000_000
RX1_WINDOW_NS = 1_000_000_000
RX2_DELAY_NS = 2_000_000_000
RX2_WINDOW_NS = 1_000_000_000
ACK_FRAME_BYTES = 12            # kAckFrameBytes du cœur
MAX_ACK_DELAY_MS = 60_000
MAX_ACK_REPETITIONS = 3


class AckWindow(str, Enum):
    """Fenêtre dans laquelle l'ACK a été entendu, ou raison pour laquelle il ne l'a pas été."""

    RX1 = "rx1"
    RX2 = "rx2"
    LATE = "late"                    # émise après la fermeture des deux fenêtres
    NOT_DECODABLE = "not_decodable"  # sous la sensibilité du terminal
    WINDOW_MISSED = "window_missed"  # le terminal émettait pendant les deux fenêtres
    NOT_SENT = "not_sent"            # aucune réponse planifiée (uplink non retenu)


@dataclass(frozen=True)
class AckTiming:
    """Réglage du comportement du réseau vis-à-vis de l'ACK.

    `delay_ms = 0` et `repetitions = 1` reproduisent exactement le planificateur du cœur : la
    couche est alors court-circuitée par l'appelant.
    """

    delay_ms: int = 0
    repetitions: int = 1

    def __post_init__(self) -> None:
        if not 0 <= self.delay_ms <= MAX_ACK_DELAY_MS:
            raise ValueError(f"delay_ms doit être dans [0, {MAX_ACK_DELAY_MS}]")
        if not 1 <= self.repetitions <= MAX_ACK_REPETITIONS:
            raise ValueError(f"repetitions doit être dans [1, {MAX_ACK_REPETITIONS}]")

    @property
    def is_default(self) -> bool:
        return self.delay_ms == 0 and self.repetitions == 1


@dataclass(frozen=True)
class AckEmission:
    """Une transmission d'acquittement, telle que la passerelle l'a réellement émise."""

    uplink_index: int
    device: int
    frame_counter_down: int     # identique pour toutes les copies d'un même ACK
    copy: int                   # 0 = première émission, 1.. = répétitions
    start_ns: int
    end_ns: int


@dataclass(frozen=True)
class AckOutcome:
    """Ce que le terminal retient de l'ACK de cet uplink."""

    uplink_index: int
    device: int
    emissions: tuple[AckEmission, ...]
    window: AckWindow
    received: bool
    duplicates_ignored: int      # copies reçues après la première, écartées par FCntDown

    @property
    def first_emission_ns(self) -> Optional[int]:
        return self.emissions[0].start_ns if self.emissions else None


@dataclass(frozen=True)
class AckPlan:
    outcomes: tuple[AckOutcome, ...]
    busy: tuple[tuple[int, int], ...]

    @property
    def received(self) -> int:
        return sum(1 for o in self.outcomes if o.received)

    @property
    def emissions(self) -> int:
        return sum(len(o.emissions) for o in self.outcomes)

    @property
    def duplicates_ignored(self) -> int:
        return sum(o.duplicates_ignored for o in self.outcomes)

    def received_indices(self) -> set[int]:
        return {o.uplink_index for o in self.outcomes if o.received}


def _ack_airtime_ns(radio: DeviceRadio) -> int:
    """Temps d'antenne d'une trame ACK, par la fonction du planificateur (même formule)."""
    from lsim.trace_events import _downlink_airtime_ns

    return _downlink_airtime_ns(radio, ACK_FRAME_BYTES)


def _decodable(rssi_uplink_dbm: float, radio: DeviceRadio, options) -> bool:
    """Réciprocité de `downlink_plan.cpp` : le terminal peut-il décoder la descente ?

    Même formule que le cœur, avec la même sensibilité et la même marge de récepteur.
    """
    rssi_down = (rssi_uplink_dbm - radio.tx_power_dbm + options.gateway_tx_power_dbm
                 + options.device_antenna_gain_dbi)
    sensitivity = receiver_sensitivity_dbm(radio.rx1_sf, radio.rx1_bw_hz)
    return rssi_down >= sensitivity + options.device_rx_offset_db


def plan_acks(records: Sequence, radios: Sequence[DeviceRadio], options,
              timing: AckTiming) -> AckPlan:
    """Planifie les ACK de `records` (réceptions montantes), selon `timing`.

    `records` : `TxRecord` du moteur, dans l'ordre de la trace. Seuls les uplinks reçus
    (`outcome == 2`) déclenchent une réponse, comme dans le cœur.
    `radios` : un `DeviceRadio` par entrée de `records`, **dans le même ordre** — c'est
    `radios[record.device_index]` côté appelant quand la trace est celle des terminaux réels.

    Les intervalles renvoyés sont ceux des transmissions **réellement émises** : ils alimentent
    l'occupation passerelle, qui décide à son tour des pertes montantes.
    """
    par_dispositif: dict[int, list[int]] = {}
    for index, record in enumerate(records):
        par_dispositif.setdefault(record.device_index, []).append(index)

    busy_until = 0
    busy: list[tuple[int, int]] = []
    outcomes: list[AckOutcome] = []
    compteur_fcnt = 0

    for index, record in enumerate(records):
        if record.outcome != 2:  # 2 = received
            outcomes.append(AckOutcome(index, record.device_index, (), AckWindow.NOT_SENT,
                                       False, 0))
            continue
        radio = radios[index]  # même ordre que `records`
        airtime = _ack_airtime_ns(radio)
        t_open = record.end_ns + RX1_DELAY_NS
        premiere = max(t_open + timing.delay_ms * 1_000_000, busy_until)

        emissions: list[AckEmission] = []
        for copie in range(timing.repetitions):
            debut = premiere + copie * airtime
            emissions.append(AckEmission(index, record.device_index, compteur_fcnt, copie,
                                         debut, debut + airtime))
            busy.append((debut, debut + airtime))
            busy_until = max(busy_until, debut + airtime)
        compteur_fcnt += 1

        # Le terminal écoutait-il ? RX1 puis RX2, à partir de la fin de SA trame.
        rx1 = (record.end_ns + RX1_DELAY_NS, record.end_ns + RX1_DELAY_NS + RX1_WINDOW_NS)
        rx2 = (record.end_ns + RX2_DELAY_NS, record.end_ns + RX2_DELAY_NS + RX2_WINDOW_NS)
        debut = emissions[0].start_ns

        fenetre = AckWindow.LATE
        if rx1[0] <= debut < rx1[1]:
            fenetre = AckWindow.RX1
        elif rx2[0] <= debut < rx2[1]:
            fenetre = AckWindow.RX2

        if fenetre is AckWindow.LATE:
            outcomes.append(AckOutcome(index, record.device_index, tuple(emissions),
                                       AckWindow.LATE, False, 0))
            continue
        if not _decodable(record.rssi_dbm, radio, options):
            outcomes.append(AckOutcome(index, record.device_index, tuple(emissions),
                                       AckWindow.NOT_DECODABLE, False, 0))
            continue

        # Le terminal était-il en train d'émettre pendant cette fenêtre ? (classe A)
        indices = par_dispositif.get(record.device_index, [])
        suivants = [records[k].start_ns for k in indices if records[k].start_ns > record.end_ns]
        if suivants and min(suivants) < rx2[0] + RX2_WINDOW_NS:
            # Une trame suivante du même terminal commence avant la fin de RX2 : il ne peut pas
            # écouter les deux fenêtres.
            outcomes.append(AckOutcome(index, record.device_index, tuple(emissions),
                                       AckWindow.WINDOW_MISSED, False, 0))
            continue

        # Copies supplémentaires tombant dans une fenêtre écoutée : ignorées par FCntDown.
        ignorees = 0
        for emission in emissions[1:]:
            dans = any(a <= emission.start_ns < b for a, b in (rx1, rx2))
            if dans:
                ignorees += 1
        outcomes.append(AckOutcome(index, record.device_index, tuple(emissions), fenetre, True,
                                   ignorees))

    busy.sort()
    return AckPlan(tuple(outcomes), tuple(busy))
