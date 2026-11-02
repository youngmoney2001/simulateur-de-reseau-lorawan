"""Retransmissions des uplinks confirmés (LoRaWAN 1.0.4, classe A, passerelle unique).

Un uplink confirmé n'est acquitté que si la passerelle le reçoit **et** si une trame d'acquittement
atteint le terminal dans sa fenêtre de réception. Tant que ce n'est pas le cas, le terminal réémet
la même trame après RX2, dans la limite de ses tentatives.

Ce module ne réimplémente pas la radio : il **pilote** le moteur existant (`simulate_causal` +
`plan_native`), qui décide des réceptions, des collisions, de l'occupation passerelle et de la
livraison des descentes. Il n'ajoute que des transmissions et observe.

Trois notions sont tenues distinctes, et ne doivent pas être confondues :

1. **Livraison de la descente** (`DownlinkDelivery`) — verdict du planificateur pour la descente
   qu'il a placée dans la fenêtre RX1 : livrée, perdue sous la sensibilité, fenêtre manquée parce
   que le terminal émettait, ou parce que la passerelle n'avait pas de créneau.
2. **Réception de l'ACK** (`AckReception`) — la descente est livrée *et* elle tombe dans la fenêtre
   de réception de la trame considérée. C'est la réception effective par le terminal.
3. **Acquittement logique** (`acked`) — la réception ci-dessus concerne bien cette trame.

La troisième étape est la plus faible : le cœur ne modélise pas le contenu de la trame ACK (ni
FCntUp, ni le type de message). L'appariement se fait donc par fenêtre, ce qui est exact tant qu'un
seul ACK est attendu par fenêtre — c'est le cas ici. Une véritable représentation MAC (FCntUp dans
l'ACK, acquittement d'une trame précise, ACK dupliqué ignoré par son FCntDown) est préparée par
`AckFrame` : le jour où le cœur expose ces champs, seule `_match_ack` change. Aucune structure ABI
n'est modifiée par ce module.
"""

from __future__ import annotations

from dataclasses import dataclass, replace as _replace
from enum import Enum
from typing import Optional, Sequence

from lsim.downlink_plan import plan_native, simulate_causal

RX1_DELAY_NS = 1_000_000_000       # RECEIVE_DELAY1 (cœur : downlink_plan.cpp)
RX1_WINDOW_NS = 1_000_000_000      # durée de la fenêtre RX1 (hypothèse du cœur)
RX2_DELAY_NS = 2_000_000_000       # RECEIVE_DELAY2 (hypothèse du cœur, classe A)
MAX_RETRIES = 7                    # LoRaWAN : 0..7 réémissions au-delà de la première
MAX_ITERATIONS = 32


class DownlinkDelivery(str, Enum):
    """Verdict du planificateur pour la descente placée dans la fenêtre de réception."""

    NONE = "none"                      # uplink non reçu : aucune descente ne peut en découler
    NOT_SCHEDULED = "not_scheduled"    # uplink reçu, mais le planificateur n'a trouvé aucun créneau
    DELIVERED = "delivered"            # reçue au-dessus de la sensibilité du terminal
    LOST_SENSITIVITY = "lost_sensitivity"  # émise, sous la sensibilité : non décodable
    DEVICE_TRANSMITTING = "device_transmitting"  # le terminal émettait : fenêtre non écoutée
    GATEWAY_BUSY = "gateway_busy"      # la passerelle n'avait pas de créneau


class AckReception(str, Enum):
    """Ce que le terminal a effectivement reçu, distinct de la livraison de la descente."""

    NONE = "none"            # rien n'a été planifié : pas d'ACK
    MISSED = "missed"        # fenêtre manquée (terminal en émission, ou passerelle occupée)
    UNDECODABLE = "undecodable"  # descente émise mais sous la sensibilité
    RECEIVED = "received"    # ACK reçu et décodable dans la fenêtre de cette trame


@dataclass(frozen=True)
class AckFrame:
    """Représentation minimale d'un ACK, prête pour une évolution MAC complète.

    Le cœur n'expose aujourd'hui ni `f_cnt_up` ni `f_cnt_down` : ces champs restent donc `None` et
    l'appariement se fait par fenêtre. Les ajouter ne changera pas les structures ABI ; seule la
    fonction `_match_ack` du module utilisera alors ces champs.
    """

    frame_counter_up: Optional[int] = None    # trame acquittée (None : non modélisé)
    frame_counter_down: Optional[int] = None  # numéro de la descente (None : non modélisé)
    confirmed: bool = True

    @property
    def is_explicit(self) -> bool:
        """Vrai quand l'ACK porte de quoi s'apparier sans passer par la fenêtre."""
        return self.frame_counter_up is not None


@dataclass(frozen=True)
class RetransmissionOptions:
    """Paramètres des retransmissions. `retries = 0` n'ajoute aucune transmission."""

    enabled: bool = True
    retries: int = 3
    retransmit_delay_ms: int = 3_000   # après la fin de l'émission, donc après RX2
    enforce_duty_cycle: bool = True

    def __post_init__(self) -> None:
        if not 0 <= self.retries <= MAX_RETRIES:
            raise ValueError(f"retries doit être dans [0, {MAX_RETRIES}]")
        if self.retransmit_delay_ms < RX2_DELAY_NS // 1_000_000:
            raise ValueError(
                f"retransmit_delay_ms doit couvrir la fenêtre RX2 "
                f"({RX2_DELAY_NS // 1_000_000} ms au minimum)")

    @property
    def effective_retries(self) -> int:
        return self.retries if self.enabled else 0


@dataclass(frozen=True)
class Attempt:
    """Une transmission d'une trame (initiale ou réémission) et ce qu'elle a produit."""

    device: int
    frame: int        # rang de la trame du terminal (0-based)
    attempt: int      # 0 = émission initiale
    start_ns: int
    end_ns: int
    received: bool                 # reçue par la passerelle
    delivery: DownlinkDelivery     # verdict du planificateur sur la descente RX1
    ack: AckReception              # ce que le terminal a effectivement reçu
    acked: bool                    # cette trame est logiquement acquittée après cet essai

    @property
    def ack_frame(self) -> Optional[AckFrame]:
        """ACK associé, quand il y en a un. Aucun numéro de trame n'est inventé."""
        return AckFrame() if self.ack is AckReception.RECEIVED else None


@dataclass(frozen=True)
class RetransmissionResult:
    attempts: tuple[Attempt, ...]
    frames: int                    # trames nominales (une par message)
    transmissions: int             # transmissions effectives (initiales + réémissions)
    retransmissions: int           # transmissions au-delà de la première
    received: int                  # transmissions reçues par la passerelle
    network_frames: int            # trames distinctes reçues (après déduplication réseau)
    frames_delivered: int          # trames acquittées au moins une fois (bout en bout)
    duplicates: int                # réceptions au-delà de la première d'une même trame
    blocked_by_duty_cycle: int     # réémissions refusées par le rapport cyclique
    acks_planned: int
    acks_received: int
    lost_sensitivity: int
    lost_collision: int
    lost_gateway_busy: int
    gateway_utilization: float
    observation_ns: int
    energy_j: float
    # Renseignés seulement si `with_engine_output=True` : indices **virtuels** (calendrier).
    trace: object = None
    events: tuple = ()
    gateway_tx: tuple = ()  # émissions passerelle planifiées, en ns

    @property
    def delivery_ratio(self) -> float:
        return 0.0 if self.frames == 0 else self.frames_delivered / self.frames


# --- représentation « une entrée par transmission » ----------------------------------------

def _virtual(device, start_ns: int):
    """Un terminal réduit à une seule transmission, à l'instant voulu.

    Le moteur ne prend en entrée que des calendriers périodiques ; une réémission n'en est pas un.
    On la représente donc comme un terminal à une transmission, à la même position, au même débit
    et avec le même frontal : collisions, sensibilité et occupation restent celles du moteur.
    L'équivalence avec un terminal périodique est vérifiée par un test C++ de l'API.
    """
    return _replace(device, start_offset_ns=int(start_ns), messages=1,
                    downlink=None, duty_cycle=1.0, rf=device.rf)


def _airtime_ns(device) -> int:
    from lsim.lora import RadioConfig, time_on_air_ns

    config = RadioConfig(spreading_factor=device.spreading_factor, bandwidth_hz=125_000,
                         coding_rate=1, low_data_rate_optimize=device.spreading_factor >= 11)
    return time_on_air_ns(config, device.payload_bytes)


def _base_schedule(devices, gateway, propagation, radios, options, environment=None) -> list[Attempt]:
    """Émissions initiales, telles que le moteur les place réellement."""
    if not devices:
        return []
    result, _busy = simulate_causal(list(devices), gateway, propagation, environment, radios,
                                    options)
    rang = [0] * len(devices)
    attempts = []
    for record in result.records:
        device = record.device_index
        attempts.append(Attempt(device=device, frame=rang[device], attempt=0,
                                start_ns=record.start_ns, end_ns=record.end_ns,
                                received=record.outcome == 2, delivery=DownlinkDelivery.NONE,
                                ack=AckReception.NONE, acked=False))
        rang[device] += 1
    return attempts


# --- décision de livraison, puis réception de l'ACK ----------------------------------------

def _deliveries(events, recues: set[int], transmissions: int) -> dict[int, DownlinkDelivery]:
    """Étape 1 : que fait le planificateur de la descente, transmission par transmission.

    `plan_native` n'émet aucun événement `ack` quand `DownlinkScheduler::on_received` ne renvoie
    aucun créneau. Une transmission reçue sans descente est donc « non planifiée », ce qui n'est
    pas la même chose qu'un uplink perdu : c'est la distinction que la directive exige.
    """
    verdict: dict[int, DownlinkDelivery] = {
        index: (DownlinkDelivery.NOT_SCHEDULED if index in recues else DownlinkDelivery.NONE)
        for index in range(transmissions)}
    for event in events:
        if not 0 <= event.device_index < transmissions:
            continue
        if event.kind == "rx_window_missed":
            verdict[event.device_index] = (DownlinkDelivery.DEVICE_TRANSMITTING
                                           if event.outcome == "device_transmitting"
                                           else DownlinkDelivery.GATEWAY_BUSY)
        elif event.kind == "ack":
            verdict[event.device_index] = (DownlinkDelivery.DELIVERED
                                           if event.outcome == "ack_only"
                                           else DownlinkDelivery.LOST_SENSITIVITY)
    return verdict


def _match_ack(schedule, events) -> set[int]:
    """Indices des transmissions dont l'ACK a été **reçu** par le terminal.

    Étape 2 (réception) puis étape 3 (appariement à la trame). `plan_native` dit si la descente est
    livrée, pas de quelle trame elle est l'acquittement : le cœur ouvrant RX1 à `fin + 1 s` pendant
    une seconde, l'appariement se fait par cette fenêtre, terminal physique par terminal physique.

    Le jour où `AckFrame.is_explicit` sera vrai, cette fonction n'aura plus qu'à comparer
    `frame_counter_up` — la signature est déjà la bonne.
    """
    par_terminal: dict[int, list[int]] = {}
    for index, attempt in enumerate(schedule):
        par_terminal.setdefault(attempt.device, []).append(index)
    for indices in par_terminal.values():
        indices.sort(key=lambda i: schedule[i].end_ns)

    recus: set[int] = set()
    for event in events:
        if event.kind != "ack" or event.outcome != "ack_only":
            continue  # perdu ou fenêtre manquée : pas de réception
        if not 0 <= event.device_index < len(schedule):
            continue
        physique = schedule[event.device_index].device
        retenu = None
        for index in par_terminal.get(physique, []):
            ouverture = schedule[index].end_ns + RX1_DELAY_NS
            if ouverture <= event.t_ns <= ouverture + RX1_WINDOW_NS:
                retenu = index
        if retenu is not None:
            recus.add(retenu)
    return recus


def _prune_acknowledged(schedule):
    """Retire les réémissions qu'un ACK reçu avant leur départ rend impossibles.

    Le calendrier ne fait que croître pendant la recherche du point fixe ; une trame peut donc
    garder une réémission devenue sans objet quand l'itération suivante lui attribue son ACK. Un
    terminal qui a reçu l'ACK dans sa fenêtre RX1 ne réémet pas : le calendrier final ne doit pas
    contenir cette transmission, sinon les réceptions en double seraient un artefact de calcul et
    non un fait de réseau.
    """
    par_trame: dict[tuple[int, int], list] = {}
    for attempt in schedule:
        par_trame.setdefault((attempt.device, attempt.frame), []).append(attempt)
    garde = []
    for essais in par_trame.values():
        essais.sort(key=lambda a: a.attempt)
        ack_avant: int | None = None   # instant du dernier ACK reçu, avant l'essai courant
        for essai in essais:
            if ack_avant is not None and essai.start_ns >= ack_avant:
                continue  # ACK déjà reçu à cet instant : pas de réémission
            garde.append(essai)
            if essai.acked:
                ack_avant = essai.end_ns + RX1_DELAY_NS
    garde.sort(key=lambda a: (a.start_ns, a.device, a.attempt))
    return garde


def _simulate(schedule, devices, gateway, propagation, radios, options, environment=None):
    if not schedule:
        return None, (), ()
    virt = [_virtual(devices[a.device], a.start_ns) for a in schedule]
    vrad = [radios[a.device] for a in schedule]
    result, _busy = simulate_causal(virt, gateway, propagation, environment, vrad, options)
    events, planned = plan_native(result.records, vrad, options)
    return result, events, planned


# --- simulation ----------------------------------------------------------------------------

def simulate_confirmed_uplinks(devices: Sequence, gateway, propagation, radios, options,
                               retransmit: RetransmissionOptions = RetransmissionOptions(),
                               energy_profile: Optional[str] = None, environment=None,
                               with_engine_output: bool = False) -> RetransmissionResult:
    """Uplinks confirmés avec réémissions ; renvoie les compteurs mesurés.

    `devices`, `radios` : un élément par terminal, même ordre (comme `simulate_causal`).
    `options` : `ProtocolOptions` ; `confirmed_uplinks` est forcé (un ACK par trame reçue).
    `environment` : obstacles et relief, transmis tel quel au moteur.

    `with_engine_output=True` ajoute `trace` et `events` (moteur, indices **virtuels**) au
    résultat : c'est ce dont `build_trace` a besoin pour produire une `TraceRun` cohérente. Les
    indices virtuels y sont ceux du calendrier, pas ceux des terminaux.
    """
    devices = list(devices)
    radios = list(radios)
    if len(radios) != len(devices):
        raise ValueError("un paramètre radio par dispositif")

    options = _replace(options, confirmed_uplinks=True)
    schedule = _base_schedule(devices, gateway, propagation, radios, options, environment)
    if not schedule:
        return RetransmissionResult((), 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0.0, 0, 0.0)

    frames = len(schedule)
    blocked: set[tuple[int, int, int]] = set()
    budget = retransmit.effective_retries
    vu: set[tuple] = set()
    result = None
    events: tuple = ()
    planned: tuple = ()

    for _iteration in range(MAX_ITERATIONS):
        result, events, planned = _simulate(schedule, devices, gateway, propagation, radios,
                                            options, environment)
        recues = {record.device_index for record in result.records if record.outcome == 2}
        livraisons = _deliveries(events, recues, len(schedule))
        recus = _match_ack(schedule, events)

        mis_a_jour = []
        for index, attempt in enumerate(schedule):
            delivery = livraisons.get(index, DownlinkDelivery.NONE)
            if index in recus:
                ack = AckReception.RECEIVED
            elif delivery in (DownlinkDelivery.DEVICE_TRANSMITTING, DownlinkDelivery.GATEWAY_BUSY):
                ack = AckReception.MISSED
            elif delivery is DownlinkDelivery.LOST_SENSITIVITY:
                ack = AckReception.UNDECODABLE
            elif delivery is DownlinkDelivery.NOT_SCHEDULED:
                ack = AckReception.MISSED  # aucun créneau RX1 : rien n'a été reçu
            else:
                ack = AckReception.NONE
            mis_a_jour.append(_replace(attempt, received=index in recues, delivery=delivery,
                                       ack=ack, acked=ack is AckReception.RECEIVED))
        schedule = mis_a_jour

        acquittees = {(a.device, a.frame) for a in schedule if a.acked}
        dernier: dict[tuple[int, int], int] = {}
        for index, attempt in enumerate(schedule):
            cle = (attempt.device, attempt.frame)
            if cle not in dernier or attempt.attempt > schedule[dernier[cle]].attempt:
                dernier[cle] = index

        nouvelles = []
        for index in sorted(dernier.values()):
            attempt = schedule[index]
            cle = (attempt.device, attempt.frame)
            if cle in acquittees or attempt.attempt >= budget:
                continue
            debut = attempt.end_ns + retransmit.retransmit_delay_ms * 1_000_000
            if retransmit.enforce_duty_cycle and devices[attempt.device].duty_cycle < 1.0:
                airtime = _airtime_ns(devices[attempt.device])
                ecoule = sum(a.end_ns - a.start_ns for a in schedule if a.device == attempt.device)
                if ecoule + airtime > devices[attempt.device].duty_cycle * debut:
                    blocked.add((attempt.device, attempt.frame, attempt.attempt))
                    continue
            nouvelles.append(Attempt(device=attempt.device, frame=attempt.frame,
                                     attempt=attempt.attempt + 1, start_ns=debut,
                                     end_ns=debut + (attempt.end_ns - attempt.start_ns),
                                     received=False, delivery=DownlinkDelivery.NONE,
                                     ack=AckReception.NONE, acked=False))
        if not nouvelles:
            break
        schedule = schedule + nouvelles
        schedule = _prune_acknowledged(schedule)
        signature = tuple((a.device, a.frame, a.attempt, a.start_ns) for a in schedule)
        if signature in vu:
            raise RuntimeError("pas de point fixe des réémissions : calendrier répété à l'identique")
        vu.add(signature)
    else:
        raise RuntimeError(f"pas de point fixe des réémissions après {MAX_ITERATIONS} itérations")

    assert result is not None
    acquittees = {(a.device, a.frame) for a in schedule if a.acked}
    receptions: dict[tuple[int, int], int] = {}
    for attempt in schedule:
        if attempt.received:
            receptions[(attempt.device, attempt.frame)] = receptions.get(
                (attempt.device, attempt.frame), 0) + 1
    # Déduplication réseau : une trame reçue plusieurs fois n'est livrée qu'une fois à
    # l'application. Le doublon compte les réceptions au-delà de la première — c'est un fait de
    # réseau, distinct de la réémission MAC qui l'a provoqué.
    network_frames = len(receptions)
    duplicates = sum(n - 1 for n in receptions.values())

    energie = 0.0
    if energy_profile is not None:
        from lsim.energy_report import device_energies

        for attempt in schedule:
            mesure = device_energies([_virtual(devices[attempt.device], attempt.start_ns)],
                                     energy_profile)[0]
            if mesure.energy_per_message_j is not None:
                energie += float(mesure.energy_per_message_j)

    return RetransmissionResult(
        attempts=tuple(schedule),
        frames=frames,
        transmissions=len(schedule),
        retransmissions=len(schedule) - frames,
        received=sum(1 for a in schedule if a.received),
        network_frames=network_frames,
        frames_delivered=len(acquittees),
        duplicates=duplicates,
        blocked_by_duty_cycle=len(blocked),
        acks_planned=sum(1 for a in schedule if a.delivery not in (
            DownlinkDelivery.NONE, DownlinkDelivery.NOT_SCHEDULED)),
        acks_received=sum(1 for a in schedule if a.ack is AckReception.RECEIVED),
        lost_sensitivity=result.totals.lost_sensitivity,
        lost_collision=result.totals.lost_collision,
        lost_gateway_busy=result.totals.lost_gateway_busy,
        gateway_utilization=result.gateway.utilization,
        observation_ns=result.gateway.observation_ns,
        energy_j=energie,
        trace=result if with_engine_output else None,
        events=events if with_engine_output else (),
        gateway_tx=tuple(planned) if with_engine_output else (),
    )
