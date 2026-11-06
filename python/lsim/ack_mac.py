"""Couche MAC de l'ACK : quand la passerelle émet, quand le terminal écoute, ce qu'il retient.

Le cœur planifie une descente unique à `fin + RECEIVE_DELAY1` et abandonne celle qui ne tient pas
dans la fenêtre RX1 (`DownlinkScheduler::on_received` renvoie `nullopt`). Ce modèle-là ne peut donc
produire **ni ACK tardif, ni ACK dupliqué** : ils sont impossibles par construction.

Cette couche les rend possibles, sans toucher au cœur ni à l'ABI :

- le réseau peut répondre avec un retard (`delay_ms`) — un serveur lent ne sait pas que la fenêtre
  est fermée : il émet quand même, l'airtime est consommée et la passerelle est bloquée ;
- le réseau peut répéter la trame d'acquittement (`repetitions`) — c'est le même `FCntDown` ; le
  terminal ne doit en retenir qu'un seul, les copies suivantes sont rejetées par le contrôle de
  rejeu (`FCntDown` strictement croissant), pas par une règle propre à cette couche.

**Identité de trame.** Chaque entrée porte un `f_cnt_up` fourni par l'appelant : toutes les
réémissions d'une même trame partagent le même `f_cnt_up`, et deux trames distinctes ne peuvent pas
le partager. Le réseau numérote ses descentes par terminal (`f_cnt_down`), pas globalement : deux
terminaux ont chacun leur série. Ces sémantiques sont celles de `lsim.session.DeviceSession`
(`begin_uplink` → `fcnt32`, `receive_downlink` → contrôle de rejeu) ; la couche ne crée pas de
compteurs concurrents, elle les transporte dans la trace.

**Taxonomie explicite.** Chaque *émission* d'ACK reçoit une classe, et les compteurs de la
projection les agrègent :

| Classe | Sens |
|---|---|
| `STANDARD` | émise dans une fenêtre écoutée (ou écoutée en continu), décodable, `FCntDown` inédit pour ce terminal |
| `LATE` | émise après la fermeture des fenêtres : l'airtime est consommée, personne n'écoute |
| `LOST` | émise dans une fenêtre écoutée mais non décodable, ou terminal indisponible (il émettait) |
| `DUPLICATE` | champ 16 bits identique à celui d'un ACK déjà accepté : rejeu, rejeté par le contrôle de compteur |
| `GAP` | champ 16 bits à plus de `MAX_FCNT_GAP` (16 384) du dernier accepté : désynchronisation, rejeté |
| `NOT_SENT` | aucun ACK : l'uplink n'a pas été reçu, ou la série descendante est épuisée |

**Classes d'écoute.** A et B ouvrent RX1 puis RX2 après un uplink ; l'ACK étant une descente de
classe A, B s'y comporte comme A — les *ping slots* de la classe B sont un autre mécanisme
(`core/include/lsim/class_b.hpp`), qui n'intervient pas ici. C écoute en continu : toute émission
postérieure à son uplink et hors de ses propres transmissions est reçue, sans contrainte de fenêtre.
Les trois mécanismes ne sont pas mélangés : la classe ne change que la règle d'écoute.

Trois fenêtres, conformes à la classe A de LoRaWAN 1.0.4 :

| Fenêtre | Ouverture | Durée |
|---|---|---|
| RX1 | `fin + RECEIVE_DELAY1` (1 s) | 1 s |
| RX2 | `fin + RECEIVE_DELAY2` (2 s) | 1 s |

La réception n'est **pas** recalculée ici : la recette radio (réciprocité, sensibilité, marge du
récepteur) est celle du cœur, reprise à l'identique et vérifiée par un test de parité contre
`plan_native`. Cette couche ne fait que replacer la transmission dans le temps et décider si elle
tombe dans une fenêtre écoutée.

Ce qui n'est **pas** modélisé ici : la fenêtre `MAX_FCNT_GAP` (un saut de compteur trop grand est
accepté), les compteurs 32 bits reconstruits depuis les 16 bits de la trame, et l'ACK `LATE` reste
rangé avec les pertes de sensibilité dans `DownlinkDelivery`, qui n'a pas de verdict « hors
fenêtre ».
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional, Sequence

from lsim.arbitre import EmissionRequest, GatewayArbiter
from lsim.fcnt import AF, NF, MODULUS_16, MODULUS_32, CounterSeries, CounterVerdict
from lsim.trace_events import DeviceRadio

RX1_DELAY_NS = 1_000_000_000
RX1_WINDOW_NS = 1_000_000_000
RX2_DELAY_NS = 2_000_000_000
RX2_WINDOW_NS = 1_000_000_000
ACK_FRAME_BYTES = 12            # kAckFrameBytes du cœur
MAX_ACK_DELAY_MS = 60_000
MAX_ACK_REPETITIONS = 3
MAX_FCNT = 2**32 - 1
DEVICE_CLASSES = ("A", "B", "C")
#: Classes qui ouvrent RX1/RX2 après un uplink (l'ACK est une descente de classe A).
WINDOWED_CLASSES = ("A", "B")


class AckWindow(str, Enum):
    """Fenêtre dans laquelle l'ACK a été entendu, ou raison pour laquelle il ne l'a pas été."""

    RX1 = "rx1"
    RX2 = "rx2"
    CONTINUOUS = "continuous"        # classe C : écoute permanente, hors réception fenêtrée
    LATE = "late"                    # émise après la fermeture des fenêtres
    NOT_DECODABLE = "not_decodable"  # sous la sensibilité du terminal
    WINDOW_MISSED = "window_missed"  # le terminal émettait pendant les fenêtres
    NOT_SENT = "not_sent"            # aucune réponse planifiée (uplink non retenu)


class AckSort(str, Enum):
    """Taxonomie explicite d'une émission d'ACK — une seule classe par émission."""

    STANDARD = "standard"
    LATE = "late"
    LOST = "lost"
    DUPLICATE = "duplicate"     # champ 16 bits déjà consommé : rejeu ou copie
    GAP = "gap"                 # plus de MAX_FCNT_GAP d'avance : désynchronisation
    NOT_SENT = "not_sent"


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
    f_cnt_up: int               # trame acquittée : identique pour toutes ses réémissions
    f_cnt_down: int             # série de descentes du terminal ; identique pour toutes les copies
    copy: int                   # 0 = première émission, 1.. = répétitions
    start_ns: int
    end_ns: int
    sort: AckSort               # classe explicite de cette émission


@dataclass(frozen=True)
class AckOutcome:
    """Ce que le terminal retient de l'ACK de cet uplink."""

    uplink_index: int
    device: int
    f_cnt_up: int
    f_cnt_down: Optional[int]    # None quand aucun ACK n'est émis
    emissions: tuple[AckEmission, ...]
    window: AckWindow
    received: bool
    duplicates_ignored: int      # copies reçues après la première, rejetées par le contrôle de rejeu
    sort: AckSort = AckSort.NOT_SENT
    series: str = NF             # série consommée : NFCntDown (ACK seul) ou AFCntDown
    counter: Optional[CounterVerdict] = None   # verdict du contrôle de compteur (None : pas d'ACK)
    session: int = 0             # session du terminal : un Join-Accept en ouvre une nouvelle

    @property
    def first_emission_ns(self) -> Optional[int]:
        return self.emissions[0].start_ns if self.emissions else None

    @property
    def accepted_emission(self) -> Optional[AckEmission]:
        """L'émission retenue par le terminal (la première de classe `STANDARD`)."""
        for emission in self.emissions:
            if emission.sort is AckSort.STANDARD:
                return emission
        return None


@dataclass(frozen=True)
class AckCounts:
    """Agrégat des classes d'émission : chaque émission compte dans exactement une classe."""

    standard: int = 0
    late: int = 0
    lost: int = 0
    duplicate: int = 0
    gap: int = 0           # reçues, décodables, mais hors de la fenêtre de rejeu
    not_sent: int = 0      # uplinks sans ACK : compte des trames, pas des émissions

    @property
    def emissions(self) -> int:
        return self.standard + self.late + self.lost + self.duplicate + self.gap


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

    @property
    def counts(self) -> AckCounts:
        valeurs = {classe: 0 for classe in AckSort}
        for outcome in self.outcomes:
            if not outcome.emissions:
                valeurs[AckSort.NOT_SENT] += 1
            for emission in outcome.emissions:
                valeurs[emission.sort] += 1
        return AckCounts(standard=valeurs[AckSort.STANDARD], late=valeurs[AckSort.LATE],
                         lost=valeurs[AckSort.LOST], duplicate=valeurs[AckSort.DUPLICATE],
                         gap=valeurs[AckSort.GAP], not_sent=valeurs[AckSort.NOT_SENT])

    def received_indices(self) -> set[int]:
        return {o.uplink_index for o in self.outcomes if o.received}


def _ack_airtime_ns(radio: DeviceRadio, window: str = "rx1") -> int:
    """Temps d'antenne d'une trame ACK, au débit de la fenêtre visée (même formule qu'ailleurs).

    RX2 est le repli régional : débit **propre**, distinct de RX1. Un ACK émis en RX2 au SF12
    occupe l'émetteur bien plus longtemps que le même en RX1 au SF7.
    """
    from lsim.trace_events import _downlink_airtime_ns

    return _downlink_airtime_ns(radio, ACK_FRAME_BYTES, window)


def _decodable(rssi_uplink_dbm: float, radio: DeviceRadio, options,
               en_rx2: bool = False) -> bool:
    """Réciprocité de `downlink_plan.cpp` : le terminal peut-il décoder la descente ?

    Même formule que le cœur, avec la même marge de récepteur — mais la sensibilité est celle de
    la fenêtre **dans laquelle le terminal écoute** (`en_rx2`), pas toujours celle de RX1. RX2 a
    son propre débit régional : sur EU868 il est au SF12BW125 alors que RX1 peut être au SF7BW125,
    soit 13 dB d'écart. Juger une descente reçue en RX2 avec le seuil de RX1 la déclarerait perdue
    alors que le dispositif l'entend.

    La fenêtre à utiliser n'est pas toujours `ou_ecoute` : en classe C l'écoute est continue et ne
    distingue plus RX1 de RX2, c'est la fenêtre visée qui a choisi la PHY. Voir `_en_rx2`.
    """
    from lsim.trace_events import _seuil_dispositif  # import local : `trace_events` réimporte ici

    rssi_down = (rssi_uplink_dbm - radio.tx_power_dbm + options.gateway_tx_power_dbm
                 + options.device_antenna_gain_dbi)
    return rssi_down >= _seuil_dispositif(radio, options, en_rx2)


def _en_rx2(debut: int, ou_ecoute: AckWindow, cible: AckWindow) -> bool:
    """La descente est-elle jugée au seuil de RX2 ?

    La règle est : **le seuil suit la PHY qui a servi à l'émettre**. Or c'est la fenêtre VISÉE
    (`cible`) qui fixe l'airtime et la fréquence dès la phase 1 de `plan_acks` — l'approximation
    documentée veut qu'une copie retardée garde l'airtime de la fenêtre visée.

    - classes A/B : l'émission aboutit dans la fenêtre que le terminal écoute, donc `ou_ecoute`
      et `cible` coïncident ; on suit la fenêtre écoutée, ce qui est la grandeur physique.
    - classe C : l'écoute est continue (`CONTINUOUS`), `ou_ecoute` ne distingue plus RX1 de RX2.
      Seule `cible` le peut, et c'est elle qui a choisi la PHY. Sans ce relais, une descente
      émise sur la fréquence RX2 au débit RX2 était jugée au seuil RX1 — la même incohérence
      interne que le défaut D-I3-2, par un autre chemin.

    Limite assumée : la classe C est modélisée par une écoute continue dès la fin de l'émission
    montante, sans fenêtre RX1 distincte. Cette modélisation n'a pas été confrontée à une source
    primaire LoRaWAN : elle n'est donc vérifiée que pour sa cohérence interne, pas pour sa
    conformité.
    """
    if ou_ecoute is AckWindow.CONTINUOUS:
        return cible is AckWindow.RX2
    return ou_ecoute is AckWindow.RX2


def _fenetre(debut: int, rx1: tuple[int, int], rx2: tuple[int, int]) -> AckWindow:
    if rx1[0] <= debut < rx1[1]:
        return AckWindow.RX1
    if rx2[0] <= debut < rx2[1]:
        return AckWindow.RX2
    return AckWindow.LATE


def plan_acks(records: Sequence, radios: Sequence[DeviceRadio], options, timing: AckTiming,
              classes: Optional[Sequence[str]] = None,
              fcnt_up: Optional[Sequence[int]] = None,
              fcnt_down_start: int = 0, uses_nf: bool = True,
              devices: Optional[Sequence[int]] = None,
              sessions: Optional[Sequence[int]] = None,
              payload: bool = False,
              arbiter: Optional["GatewayArbiter"] = None,
              avant_resolution: Optional[Callable[["GatewayArbiter"], None]] = None) -> AckPlan:
    """Planifie les ACK de `records` (réceptions montantes), selon `timing`.

    `arbiter` : émetteur partagé (`lsim.arbitre.GatewayArbiter`). Quand il est fourni, les ACK y
    sont déposés avec les autres descentes (Join-Accept, downlinks) : la ressource est unique et
    l'ordre est chronologique, sans priorité inventée. `None` : la couche arbitre seule.
    `avant_resolution` : appelée avec l'arbitre juste avant `resolve()`, pour qu'un autre
    producteur dépose ses propres demandes dans la même passe.

    `records` : `TxRecord` du moteur, dans l'ordre de la trace. Seuls les uplinks reçus
    (`outcome == 2`) déclenchent une réponse, comme dans le cœur.
    `radios` : un `DeviceRadio` par entrée de `records`, **dans le même ordre**.
    `classes` : classe d'écoute du terminal de chaque entrée (`A`, `B` ou `C`) ; `None` = `A`.
    `fcnt_up` : compteur de trame montante de chaque entrée ; `None` = rang de la trame par
    terminal, réémissions exclues (une entrée de même `f_cnt_up` = la même trame).
    `fcnt_down_start` : premier compteur de la série descendante de chaque terminal.
    `uses_nf` : la trame d'ACK ne porte pas de charge utile applicative ; elle consomme donc
    `NFCntDown` (`AFCntDown` reste intact). Un seul ACK par trame, sans FPort : c'est le cas réel.
    `devices` : terminal physique de chaque entrée, quand l'appelant simule une transmission par
    entrée (chemin des réémissions). Par défaut, `record.device_index`. **Les compteurs et l'écoute
    continue se lisent sur le terminal physique** : deux tentatives d'une même trame ne doivent pas
    ouvrir deux séries descendantes.
    `sessions` : numéro de session de chaque entrée (0 par défaut). Deux sessions d'un même terminal
    ont des séries **indépendantes** : une nouvelle jointure remet les compteurs à zéro sans que la
    nouvelle session soit rejetée comme rejeu de l'ancienne.
    `payload` : la trame descendante porte une charge utile applicative (descente confirmée) au lieu
    d'un ACK seul. Elle consomme alors `AFCntDown`, et l'événement de trace est `data_ack`.

    Le terminal ne lit **pas** le compteur 32 bits du réseau : il reçoit le champ de 16 bits et le
    replace dans sa série (`lsim.fcnt.CounterSeries.reconstruct`). Le doublon et la
    désynchronisation sont donc des verdicts de compteur, pas des règles de cette couche.

    Les intervalles renvoyés sont ceux des transmissions **réellement émises** : ils alimentent
    l'occupation passerelle, qui décide à son tour des pertes montantes.
    """
    if len(radios) != len(records):
        raise ValueError("un paramètre radio par enregistrement")
    if classes is not None and len(classes) != len(records):
        raise ValueError("une classe d'écoute par enregistrement")
    if fcnt_up is not None and len(fcnt_up) != len(records):
        raise ValueError("un compteur montant par enregistrement")
    if devices is not None and len(devices) != len(records):
        raise ValueError("un terminal physique par enregistrement")
    if sessions is not None and len(sessions) != len(records):
        raise ValueError("une session par enregistrement")

    for classe in (classes or ()):
        if classe not in DEVICE_CLASSES:
            raise ValueError(f"classe de terminal inconnue : {classe!r}")

    appareils = [record.device_index if devices is None else int(devices[index])
                 for index, record in enumerate(records)]
    sessions_lues = ([0] * len(records) if sessions is None
                     else [int(sessions[index]) for index in range(len(records))])
    if payload:
        uses_nf = False                      # descente applicative : AFCntDown
    serie_utilisee = NF if uses_nf else AF

    # Indices des transmissions de chaque terminal physique, pour l'écoute en continu.
    par_dispositif: dict[int, list[int]] = {}
    for index, appareil in enumerate(appareils):
        par_dispositif.setdefault(appareil, []).append(index)

    # L'émetteur est unique et partagé (`lsim.arbitre`) : les ACK y passent comme les Join-Accept
    # et les downlinks. Sans arbitre fourni, la couche en crée un pour elle seule : les instants
    # sont alors ceux d'avant D3.13 (`début = max(ouverture + retard, occupé_jusqu'à)`).
    arbitre = GatewayArbiter() if arbiter is None else arbiter
    outcomes: list[AckOutcome] = []
    # Demandes déposées, à relire après résolution : (tickets, radio, f_cnt_down).
    deposees: dict[int, tuple[list[int], object, int]] = {}
    # Séries de descentes et contrôle de rejeu, **par terminal et par session**.
    fcnt_down_suivant: dict[tuple[int, int], int] = {}
    dernier_accepte: dict[tuple[int, int], int] = {}

    # `fcnt_up` par défaut : rang de la trame du terminal (une entrée = une transmission).
    rangs: dict[int, int] = {}
    compteurs = []
    for index, record in enumerate(records):
        if fcnt_up is not None:
            compteurs.append(int(fcnt_up[index]))
            continue
        valeur = rangs.get(record.device_index, 0)
        rangs[record.device_index] = valeur + 1
        compteurs.append(valeur)

    # --- phase 1 : dépôt des demandes ------------------------------------------------------
    # Le compteur descendant se numérote ici, dans l'ordre des enregistrements : c'est le réseau
    # qui numérote ses descentes, indépendamment de l'instant où l'émetteur les place.
    for index, record in enumerate(records):
        appareil = appareils[index]
        session = sessions_lues[index]
        cle = (appareil, session)
        montant = compteurs[index]
        if record.outcome != 2:  # 2 = received
            outcomes.append(AckOutcome(index, appareil, montant, None, (), AckWindow.NOT_SENT,
                                       False, 0, AckSort.NOT_SENT, serie_utilisee, None, session))
            continue
        radio = radios[index]  # même ordre que `records`
        t_open = record.end_ns + RX1_DELAY_NS
        # Fenêtre **visée** par le réseau : elle découle de l'instant prêt, donc connue avant le
        # placement. Une copie retardée par l'émetteur peut glisser dans la fenêtre suivante ;
        # l'airtime reste alors celui de la fenêtre visée (approximation documentée et testée :
        # `test_l_airtime_suit_la_fenetre_visée`).
        pret = t_open + timing.delay_ms * 1_000_000
        cible = _fenetre(pret,
                         (t_open, t_open + RX1_WINDOW_NS),
                         (record.end_ns + RX2_DELAY_NS, record.end_ns + RX2_DELAY_NS + RX2_WINDOW_NS))
        airtime = _ack_airtime_ns(radio, "rx2" if cible is AckWindow.RX2 else "rx1")
        f_cnt_down = fcnt_down_suivant.get(cle, fcnt_down_start)
        if f_cnt_down >= MODULUS_32:
            # Série épuisée à 2^32 : le réseau ne peut plus numéroter de descente. La spécification
            # impose une nouvelle jointure ; la couche n'en invente pas, elle n'émet rien.
            outcomes.append(AckOutcome(index, appareil, montant, None, (), AckWindow.NOT_SENT,
                                       False, 0, AckSort.NOT_SENT, serie_utilisee,
                                       CounterVerdict.EXHAUSTED, session))
            continue
        fcnt_down_suivant[cle] = f_cnt_down + 1
        # Aucune fenêtre imposée à l'arbitre : un ACK retardé par l'émetteur est une émission
        # réelle, que la couche classe `LATE` elle-même une fois l'instant connu. Les copies se
        # suivent parce qu'elles partagent le même instant prêt et que la file est monotone.
        # Fréquence de la fenêtre visée : RX1 et RX2 ne sont pas dans la même sous-bande. Un
        # ACK `LATE` est émis après RX2, sur la fréquence de la dernière fenêtre écoutée.
        freq_hz = radio.rx2_hz if cible is not AckWindow.RX1 else radio.rx1_hz
        tickets = arbitre.demand_all([
            EmissionRequest(label="ack", device=appareil, ready_ns=pret, freq_hz=freq_hz,
                            duration_ns=airtime, window=None)
            for _copie in range(timing.repetitions)])
        # La fenêtre visée est mémorisée avec les tickets : c'est elle qui fixe l'airtime et la
        # fréquence de l'émission, donc la PHY réellement utilisée — le seuil doit la suivre.
        deposees[index] = (tickets, radio, f_cnt_down, cible)

    if avant_resolution is not None:
        avant_resolution(arbitre)
    arbitre.resolve()

    # --- phase 2 : classification, l'instant de chaque émission étant connu -----------------
    for index, record in enumerate(records):
        if index not in deposees:
            continue
        appareil = appareils[index]
        session = sessions_lues[index]
        cle = (appareil, session)
        classe = "A" if classes is None else classes[index]
        montant = compteurs[index]
        radio = radios[index]  # même ordre que `records`
        tickets, _radio, f_cnt_down, cible = deposees[index]
        creneaux = [(e.start_ns, e.end_ns) for e in arbitre.emissions(tickets)]

        # Le terminal écoutait-il ? RX1 puis RX2 pour A et B ; en continu pour C.
        rx1 = (record.end_ns + RX1_DELAY_NS, record.end_ns + RX1_DELAY_NS + RX1_WINDOW_NS)
        rx2 = (record.end_ns + RX2_DELAY_NS, record.end_ns + RX2_DELAY_NS + RX2_WINDOW_NS)

        # Émissions du terminal lui-même : il ne peut pas écouter en émettant.
        propres = [(records[k].start_ns, records[k].end_ns)
                   for k in par_dispositif.get(appareil, []) if k != index]

        def emet_a(instant: int) -> bool:
            return any(debut <= instant < fin for debut, fin in propres)

        def ecoute(instant: int) -> Optional[AckWindow]:
            """Fenêtre dans laquelle le terminal écoute à cet instant (None : il n'écoute pas)."""
            if classe == "C":
                if instant >= record.end_ns and not emet_a(instant):
                    return AckWindow.CONTINUOUS
                return None
            if emet_a(instant):
                return None
            fenetre = _fenetre(instant, rx1, rx2)
            return None if fenetre is AckWindow.LATE else fenetre

        serie = CounterSeries(start=fcnt_down_start, last=dernier_accepte.get(cle))
        verdict_compteur: Optional[CounterVerdict] = None
        emissions: list[AckEmission] = []
        fenetre_retenue: AckWindow = AckWindow.LATE
        accepte = False
        ignorees = 0
        for copie, (debut, fin) in enumerate(creneaux):
            ou_ecoute = ecoute(debut)
            if ou_ecoute is None:
                # Le terminal émet : il ne peut pas écouter. Sinon, il n'écoutait pas encore
                # (classe A/B hors fenêtre) : l'ACK est tardif.
                classe_emission = AckSort.LOST if emet_a(debut) else AckSort.LATE
            elif not _decodable(record.rssi_dbm, radio, options, en_rx2=_en_rx2(debut, ou_ecoute,
                                                                                cible)):
                # Seuil évalué **ici**, et non avant la boucle : la fenêtre écoutée n'est connue
                # qu'une fois l'instant d'émission connu. C'est la même règle que
                # `_seuil_dispositif` dans `trace_events`.
                classe_emission = AckSort.LOST
            else:
                # Le terminal ne voit que le champ de 16 bits : il le replace dans sa série.
                controle = serie.reconstruct(f_cnt_down % MODULUS_16)
                verdict_compteur = controle.verdict
                if controle.verdict is CounterVerdict.OK:
                    classe_emission = AckSort.STANDARD
                    accepte = True
                    fenetre_retenue = ou_ecoute
                    serie = serie.accept(controle.counter32)
                elif controle.verdict is CounterVerdict.REPLAY:
                    classe_emission = AckSort.DUPLICATE
                    ignorees += 1
                else:
                    classe_emission = AckSort.GAP
            emissions.append(AckEmission(index, appareil, montant, f_cnt_down, copie,
                                         debut, fin, classe_emission))

        if accepte:
            dernier_accepte[cle] = serie.last
            verdict_compteur = CounterVerdict.OK
        else:
            premiere = emissions[0]
            fenetre_retenue = (AckWindow.WINDOW_MISSED if emet_a(premiere.start_ns)
                               else AckWindow.LATE if premiere.sort is AckSort.LATE
                               else AckWindow.NOT_DECODABLE)

        verdict = AckSort.STANDARD if accepte else emissions[0].sort
        outcomes.append(AckOutcome(index, appareil, montant, f_cnt_down, tuple(emissions),
                                   fenetre_retenue, accepte, ignorees, verdict, serie_utilisee,
                                   verdict_compteur, session))

    # L'occupation rendue est celle de **toutes** les émissions réellement faites sur l'émetteur
    # partagé : les ACK, et les Join-Accept qu'un autre producteur aurait déposés. C'est elle qui
    # alimente le point fixe, donc les pertes montantes par demi-duplex.
    outcomes.sort(key=lambda o: o.uplink_index)
    return AckPlan(tuple(outcomes), arbitre.occupation)
