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

from lsim.arbitre import DutyCycleLedger, GatewayArbiter
from lsim.downlink_plan import DeviceRx2, plan_native, plan_native_v2, simulate_causal
from lsim.sessions import SessionTimeline


def _table_rx2(radios) -> tuple[DeviceRx2, ...]:
    """Table RX2 du cœur, une entrée par dispositif — voir `lsim.trace_events._table_rx2`."""
    return tuple(DeviceRx2(rx2_hz=r.rx2_hz, rx2_sf=r.rx2_sf, rx2_bw_hz=r.rx2_bw_hz)
                 for r in radios)

RX1_DELAY_NS = 1_000_000_000       # RECEIVE_DELAY1 (cœur : downlink_plan.cpp)
RX1_WINDOW_NS = 1_000_000_000      # durée de la fenêtre RX1 (hypothèse du cœur)
RX2_DELAY_NS = 2_000_000_000       # RECEIVE_DELAY2 (hypothèse du cœur, classe A)
MAX_RETRIES = 7                    # LoRaWAN : 0..7 réémissions au-delà de la première
# Budget d'itérations du point fixe des réémissions. Relevé de 32 à 128 en U0.4-bis : la
# convergence de l'occupation radio (voir `_simulate_confirmed`) demande des passes
# supplémentaires — mesuré : 75 itérations au maximum sur 500 scénarios denses, contre 27
# avant. 128 laisse une marge de 1,7 × ; au-delà, l'erreur est explicite.
#
# Renommé en U0.5 (`MAX_ITERATIONS` → `MAX_ITERATIONS_REEMISSIONS`) : il existait une
# **seconde** constante homonyme, `trace_events.MAX_ITERATIONS = 64`, indépendante de
# celle-ci — aucun import croisé, points fixes non imbriqués. Le nom commun laissait croire
# qu'elles étaient liées. `trace_events` garde sa valeur de 64.
#
# Limite **empirique**, non démontrée. Depuis que la détection d'état répété porte sur la
# paire (calendrier, occupation) — et non plus sur le calendrier seul — la borne théorique
# d'atteinte du plafond est beaucoup plus grande : l'espace d'états est fini (le budget
# cumulé borne le calendrier, l'occupation en découle) mais vaste. Mesuré : **74 passes au
# plus** sur 1 500 scénarios denses, 23 sur le balayage de référence à 400, aucune
# configuration au plafond. La marge n'est que de 1,7 ×, et elle n'a **pas** été éprouvée
# au-delà de 16 terminaux. Le plafond reste le filet : il **lève** explicitement, il ne rend
# jamais un résultat silencieusement faux.
MAX_ITERATIONS_REEMISSIONS = 128


def _canonique(intervalles) -> tuple:
    """Forme canonique d'une occupation : triée, dédupliquée, entiers natifs.

    Deux occupations sont égales dès qu'elles contiennent les mêmes intervalles, quel que
    soit l'ordre de production ou d'éventuelles répétitions. Comparer les listes brutes
    rendrait la convergence dépendante de l'ordre d'insertion de l'arbitre — et donc
    d'un détail d'implémentation, pas de la physique.
    """
    if not intervalles:
        return ()
    return tuple(sorted({(int(d), int(f)) for d, f in intervalles}))


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
    """Représentation minimale d'un ACK, avec l'identité de trame quand elle est connue.

    Le cœur n'expose ni `f_cnt_up` ni `f_cnt_down` : ces compteurs sont tenus par le module
    (`Attempt.f_cnt_up`, `Attempt.f_cnt_down`), avec la sémantique de `lsim.session` — `FCntUp`
    identifie la trame (toutes ses réémissions le partagent), `FCntDown` est la série de descentes
    du terminal. `None` reste possible pour un appelant qui n'en fournit pas.
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
    # Comportement du réseau vis-à-vis de l'ACK. Valeurs par défaut : planificateur du cœur.
    # Les changer active la couche MAC (`lsim.ack_mac`), seule à pouvoir produire un ACK tardif
    # ou dupliqué : le cœur, lui, abandonne la descente hors fenêtre RX1.
    ack_delay_ms: int = 0
    ack_repetitions: int = 1
    # La descente porte une charge utile applicative (descente confirmée) au lieu d'un ACK seul :
    # elle consomme alors AFCntDown et son événement de trace est `data_ack`.
    downlink_payload: bool = False
    # Premier FCntUp d'un terminal (après jointure, le compteur ne repart pas de zéro).
    # Les réémissions d'une même trame réutilisent le même FCntUp : c'est l'identité de la trame.
    fcnt_up_start: int = 0
    # Premier compteur descendant de chaque terminal : départ des séries
    # `NFCntDown` / `AFCntDown` de la couche MAC.
    fcnt_down_start: int = 0
    # Instants (s) des `Join-Accept` acceptés. Vide : une seule session, celle du scénario.
    session_joins_s: tuple[int, ...] = ()
    # Jointures **radio** : instants (s) des Join-Request, tentatives, copies du Join-Accept.
    join_requests_s: tuple[int, ...] = ()
    join_retries: int = 1
    join_accept_rx2_fallback: bool = True
    join_accept_replays: int = 0

    def __post_init__(self) -> None:
        if not 0 <= self.fcnt_up_start < 2**32:
            raise ValueError("fcnt_up_start doit être dans [0, 2**32)")
        if not 0 <= self.fcnt_down_start < 2**32:
            raise ValueError("fcnt_down_start doit être dans [0, 2**32)")
        self.timeline        # valide les instants de jointure (croissants, positifs)
        self.join_options    # valide les jointures radio (bornes, ordre, exclusions)
        if not 0 <= self.retries <= MAX_RETRIES:
            raise ValueError(f"retries doit être dans [0, {MAX_RETRIES}]")
        if self.retransmit_delay_ms < RX2_DELAY_NS // 1_000_000:
            raise ValueError(
                f"retransmit_delay_ms doit couvrir la fenêtre RX2 "
                f"({RX2_DELAY_NS // 1_000_000} ms au minimum)")
        from lsim.ack_mac import AckTiming as _AckTiming
        _AckTiming(delay_ms=self.ack_delay_ms, repetitions=self.ack_repetitions)  # bornes

    @property
    def join_options(self):
        """Jointures radio déclarées, validées."""
        from lsim.join import JoinRadioOptions

        if self.session_joins_s and self.join_requests_s:
            raise ValueError("session_joins_s (déclaré) et join_requests_s (radio) sont exclusifs")
        return JoinRadioOptions(requests_s=self.join_requests_s, retries=self.join_retries,
                                rx2_fallback=self.join_accept_rx2_fallback,
                                accept_replays=self.join_accept_replays)

    @property
    def timeline(self) -> SessionTimeline:
        """Sessions ouvertes par les `Join-Accept` déclarés (aucune par défaut)."""
        return SessionTimeline.from_join_times(self.session_joins_s)

    @property
    def effective_retries(self) -> int:
        return self.retries if self.enabled else 0

    @property
    def uses_ack_mac(self) -> bool:
        """Vrai quand la couche MAC est nécessaire (ACK retardé ou répété)."""
        return self.ack_delay_ms != 0 or self.ack_repetitions != 1

    def ack_timing(self):
        from lsim.ack_mac import AckTiming
        return AckTiming(delay_ms=self.ack_delay_ms, repetitions=self.ack_repetitions)


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
    ack_ns: Optional[int] = None   # instant d'émission de l'ACK retenu (None : aucun)
    f_cnt_up: Optional[int] = None     # compteur montant de la trame (identique aux réémissions)
    f_cnt_down: Optional[int] = None   # compteur descendant de l'ACK retenu (None : aucun)
    session: int = 0                   # session de la trame ; FCntUp y repart de zéro

    @property
    def key(self) -> tuple[int, int, int]:
        """Identité de la trame : terminal, session, rang. `FCntUp` y repart de zéro."""
        return (self.device, self.session, self.frame)

    @property
    def ack_frame(self) -> Optional[AckFrame]:
        """ACK associé, quand il y en a un : il porte alors l'identité réelle de la trame."""
        if self.ack is not AckReception.RECEIVED:
            return None
        return AckFrame(frame_counter_up=self.f_cnt_up, frame_counter_down=self.f_cnt_down)


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
    acks_planned: int              # transmissions d'ACK effectivement émises
    acks_received: int
    ack_duplicates_ignored: int      # copies d'ACK reçues puis écartées (même FCntDown)
    # Taxonomie de l'ACK (une seule classe par émission, voir `lsim.ack_mac.AckSort`).
    ack_standard: int              # émissions acceptées par le terminal
    ack_late: int                  # émissions hors fenêtre : airtime consommée, personne n'écoute
    ack_lost: int                  # émissions dans une fenêtre écoutée mais non décodables
    ack_duplicate: int             # copies reçues puis rejetées par le contrôle de rejeu
    ack_not_sent: int              # trames sans ACK (uplink non reçu)
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
    ack_gap: int = 0        # ACK reçus puis rejetés par la fenêtre de rejeu
    rejected_stale_session: int = 0   # réémissions refusées : session déjà remplacée
    # Restitution du contrôle descendant (`lsim.arbitre.DownlinkDutyCycleReport`). `None`
    # quand aucune règle n'a été fournie. Il distingue expressément « aucune contrainte
    # applicable » (`active` faux) de « contrainte non évaluée faute de fréquence »
    # (`non_evaluees` non nul) et de « règle existante mais jamais appliquée parce que le
    # scénario est passé par le chemin natif du cœur » (`active` vrai, `engage` faux).
    duty_cycle: object = None
    joins: tuple = ()       # tentatives de jointure radio (vide si jointure déclarée ou absente)
    joins_blocked_by_duty_cycle: int = 0  # Join-Request refusés par le rapport cyclique
    join_accepts_emitted: int = 0     # Join-Accept réellement émis (RX1, RX2 et rejeux)

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


def _session_at(timelines, device: int, t_ns: int) -> int:
    """Numéro de session d'un terminal : chaque terminal a sa propre horloge de sessions."""
    if not timelines:
        return 0
    timeline = timelines.get(device)
    return 0 if timeline is None else timeline.session_at(t_ns)


def _is_stale(timelines, device: int, session: int, t_ns: int) -> bool:
    if not timelines:
        return False
    timeline = timelines.get(device)
    return timeline is not None and timeline.is_stale(session, t_ns)


def _base_schedule(devices, gateway, propagation, radios, options, environment=None,
                   fcnt_start: int = 0, timelines=None) -> list[Attempt]:
    """Émissions initiales, telles que le moteur les place réellement."""
    if not devices:
        return []
    result, _busy = simulate_causal(list(devices), gateway, propagation, environment, radios,
                                    options)
    # Un rang par (terminal, session) : `FCntUp` repart de zéro à chaque nouvelle session.
    rang: dict[tuple[int, int], int] = {}
    attempts = []
    for record in result.records:
        device = record.device_index
        session = _session_at(timelines, device, record.start_ns)
        cle = (device, session)
        compteur = rang.get(cle, 0)
        attempts.append(Attempt(device=device, frame=compteur, attempt=0,
                                start_ns=record.start_ns, end_ns=record.end_ns,
                                received=record.outcome == 2, delivery=DownlinkDelivery.NONE,
                                ack=AckReception.NONE, acked=False,
                                f_cnt_up=fcnt_start + compteur, session=session))
        rang[cle] = compteur + 1
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


def _verifier_coherence_occupation(planned, recues) -> None:
    """Lève si une descente planifiée recouvre une montante comptée comme reçue.

    Un émetteur demi-duplex ne peut émettre pendant qu'il reçoit. Si le plan final recouvre
    une montante reçue, le point fixe n'a pas abouti à une solution physique : on le dit, au
    lieu de rendre silencieusement une trace impossible.

    `planned` : intervalles d'occupation descendante. `recues` : intervalles des montantes
    comptées comme reçues. Les deux sont comparés sous forme canonique.

    Extraite de la boucle de point fixe pour être **testable directement** : le filet y est
    inatteignable par construction (voir le commentaire à l'endroit de l'appel), donc aucune
    suite de tests boîte noire ne peut en démontrer le fonctionnement.
    """
    for _d, _f in _canonique(planned):
        for _a, _b in _canonique(recues):
            if _d < _b and _a < _f:
                raise RuntimeError(
                    "occupation descendante incohérente avec la trace : une descente "
                    f"[{_d}, {_f}) chevauche une montante reçue [{_a}, {_b})")


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
        par_trame.setdefault(attempt.key, []).append(attempt)
    garde = []
    for essais in par_trame.values():
        essais.sort(key=lambda a: a.attempt)
        ack_avant: int | None = None   # instant du dernier ACK reçu, avant l'essai courant
        for essai in essais:
            if ack_avant is not None and essai.start_ns >= ack_avant:
                continue  # ACK déjà reçu à cet instant : pas de réémission
            garde.append(essai)
            if essai.acked:
                ack_avant = essai.ack_ns if essai.ack_ns is not None else essai.end_ns + RX1_DELAY_NS
    garde.sort(key=lambda a: (a.start_ns, a.device, a.attempt))
    return garde


def _simulate(schedule, devices, gateway, propagation, radios, options, environment=None,
              timing=None, busy=None, classes=None, fcnt_down_start: int = 0,
              payload: bool = False, arbiter=None, avant_resolution=None, duty_cycle=None):
    """Rejoue le calendrier. Sans `timing` : chemin causal du cœur, inchangé.

    Avec `timing` (ACK retardé ou répété, **ou descentes partagées avec une jointure radio**) : les
    transmissions sont simulées avec une occupation passerelle **imposée**, puis la couche
    `ack_mac` recalcule les ACK et la nouvelle occupation. C'est le seul moyen de faire exister un
    ACK hors fenêtre sans modifier le cœur, dont le planificateur abandonne ces descentes par
    construction ; c'est aussi le seul moyen de faire partager un émetteur unique entre les ACK et
    les Join-Accept, sans toucher à l'ABI.

    `arbiter` : émetteur partagé (`lsim.arbitre`). `avant_resolution` : appelée avec
    `(arbitre, calendrier courant)` juste avant la résolution, pour qu'un autre producteur
    (les jointures) dépose ses propres demandes dans la même passe chronologique.
    `duty_cycle` : espacement réglementaire descendant (`lsim.arbitre.DownlinkDutyCycle`),
    partagé par toutes les descentes de la passe. `None` : aucune contrainte.
    """
    if not schedule:
        return None, (), (), None
    virt = [_virtual(devices[a.device], a.start_ns) for a in schedule]
    vrad = [radios[a.device] for a in schedule]
    if timing is None:
        # Repli RX2 (I3) : les deux producteurs reçoivent la même table. Sans région, `rx2_hz`
        # est nul et la table est inerte — le comportement est celui d'avant I3.
        table = (_table_rx2(vrad) if getattr(options, "rx2_fallback", False) else None)
        result, _busy = simulate_causal(virt, gateway, propagation, environment, vrad, options,
                                        rx2=table)
        events, planned = (plan_native_v2(result.records, vrad, options, table)
                           if table is not None
                           else plan_native(result.records, vrad, options))
        return result, events, planned, None

    from lsim.ack_mac import plan_acks
    from lsim.simulator import simulate_uplinks_trace

    if avant_resolution is not None:
        def accroche(arbitre):
            avant_resolution(arbitre, schedule)
    else:
        accroche = None

    result = simulate_uplinks_trace(virt, gateway, propagation, environment,
                                    gateway_busy=tuple(busy or ()), device_rf=None)
    radios_par_enregistrement = [vrad[record.device_index] for record in result.records]
    # Identité et classe suivent l'entrée de calendrier, pas la position dans la trace moteur.
    plan = plan_acks(result.records, radios_par_enregistrement, options, timing,
                     classes=None if classes is None else
                     [classes[schedule[record.device_index].device]
                      for record in result.records],
                     fcnt_up=[schedule[record.device_index].f_cnt_up
                              for record in result.records],
                     fcnt_down_start=fcnt_down_start, payload=payload,
                     devices=[schedule[record.device_index].device
                              for record in result.records],
                     sessions=[schedule[record.device_index].session
                               for record in result.records],
                     arbiter=arbiter, avant_resolution=accroche)
    # Les ACK de la trace sont ceux que la couche a réellement émis, pas ceux du planificateur
    # du cœur : instants, copies et verdicts viennent du même plan que les compteurs.
    events = _mac_ack_events(result.records, plan, radios_par_enregistrement, payload=payload)
    return result, events, plan.busy, plan


# --- événements de trace des ACK de la couche MAC --------------------------------------------

#: Classe d'ACK → (issue de l'événement, issue du saut passerelle → terminal).
#: Le vocabulaire est celui des autres événements (`HopOutcome` de `lsim.api_contract`) :
#: un ACK tardif n'est écouté par personne (`not_listened`), une copie reçue puis rejetée par le
#: contrôle de rejeu est `suppressed` — le même mot que les doublons de maillage.
_MAC_ACK_EVENT = {
    "standard": ("ack_only", "delivered"),
    "late": ("not_listened", "not_listened"),
    "lost": ("lost_sensitivity", "lost_sensitivity"),
    "duplicate": ("suppressed", "delivered"),
    "gap": ("suppressed", "delivered"),
}


def _mac_ack_events(records, plan, radios, payload: bool = False):
    """Un événement `ack` par émission réellement faite, aux instants de la couche MAC.

    Les indices sont ceux des enregistrements moteur (virtuels) : `_build_trace_retransmissions`
    les ramène aux terminaux du scénario, comme pour les autres événements du chemin.
    """
    from lsim.ack_mac import AckSort, AckWindow
    from lsim.trace_events import HopEvent, ProtocolEvent, _dev

    evenements = []
    for position, record in enumerate(records):
        sortie = plan.outcomes[position]
        radio = radios[position]
        for emission in sortie.emissions:
            if emission.sort is AckSort.LOST and sortie.window is AckWindow.WINDOW_MISSED:
                issue, saut = "device_transmitting", "not_listened"
            elif payload and emission.sort is AckSort.STANDARD:
                issue, saut = "data_ack", "delivered"   # descente confirmée qui acquitte
            else:
                issue, saut = _MAC_ACK_EVENT[emission.sort.value]
            hop = HopEvent("gw:0", _dev(record.device_index), emission.start_ns, radio.rx1_hz,
                           None, None, saut)
            evenements.append((emission.start_ns, record.device_index, emission.copy,
                               ProtocolEvent(0, emission.start_ns, "ack", record.device_index, 0,
                                             (hop,), issue)))
    evenements.sort(key=lambda e: (e[0], e[1], e[2]))
    return tuple(_replace(evenement, seq=k)
                 for k, (_t, _d, _c, evenement) in enumerate(evenements))


# --- simulation ----------------------------------------------------------------------------

def _simulate_confirmed(devices: Sequence, gateway, propagation, radios, options,
                        retransmit: RetransmissionOptions = RetransmissionOptions(),
                        energy_profile: Optional[str] = None, environment=None,
                        with_engine_output: bool = False,
                        device_classes: Optional[Sequence[str]] = None,
                        timelines=None, avant_resolution=None,
                        duty_cycle=None) -> RetransmissionResult:
    """Uplinks confirmés avec réémissions ; renvoie les compteurs mesurés.

    `devices`, `radios` : un élément par terminal, même ordre (comme `simulate_causal`).
    `options` : `ProtocolOptions` ; `confirmed_uplinks` est forcé (un ACK par trame reçue).
    `environment` : obstacles et relief, transmis tel quel au moteur.

    `with_engine_output=True` ajoute `trace` et `events` (moteur, indices **virtuels**) au
    résultat : c'est ce dont `build_trace` a besoin pour produire une `TraceRun` cohérente. Les
    indices virtuels y sont ceux du calendrier, pas ceux des terminaux.
    `device_classes` : classe d'écoute (`A`, `B`, `C`) d'un élément par terminal, `None` = `A`.
    `retransmit.session_joins_s` ouvre des sessions : `FCntUp` et les séries descendantes repartent
    de zéro à chacune, et une trame dont la réémission tomberait après une jointure est abandonnée
    (`RetransmissionResult.rejected_stale_session`).
    `avant_resolution` : `(arbitre, calendrier) -> None`, appelée à chaque itération juste avant la
    résolution de l'émetteur partagé. C'est par là que les Join-Accept d'une jointure radio
    concourent avec les ACK pour la même ressource. Fournie, elle **impose** le planificateur
    Python (`lsim.ack_mac`) au lieu de celui du cœur : le cœur ne peut pas partager son émetteur
    avec une demande qu'il ne connaît pas.
    """
    devices = list(devices)
    radios = list(radios)
    if len(radios) != len(devices):
        raise ValueError("un paramètre radio par dispositif")
    if device_classes is not None:
        device_classes = list(device_classes)
        if len(device_classes) != len(devices):
            raise ValueError("une classe d'écoute par dispositif")

    options = _replace(options, confirmed_uplinks=True)
    if timelines is None:
        partage = retransmit.timeline          # jointures déclarées : une horloge commune
        timelines = ({device: partage for device in range(len(devices))}
                     if partage.sessions else {})
    schedule = _base_schedule(devices, gateway, propagation, radios, options, environment,
                              fcnt_start=retransmit.fcnt_up_start, timelines=timelines)
    if not schedule:
        return RetransmissionResult(
            attempts=(), frames=0, transmissions=0, retransmissions=0, received=0,
            network_frames=0, frames_delivered=0, duplicates=0, blocked_by_duty_cycle=0,
            acks_planned=0, acks_received=0, ack_duplicates_ignored=0,
            ack_standard=0, ack_late=0, ack_lost=0, ack_duplicate=0, ack_gap=0,
            ack_not_sent=0,
            lost_sensitivity=0, lost_collision=0, lost_gateway_busy=0,
            gateway_utilization=0.0, observation_ns=0, energy_j=0.0)

    frames = len(schedule)
    blocked: set[tuple[int, int, int, int]] = set()
    perimees = 0
    budget = retransmit.effective_retries
    vu: set[tuple] = set()
    # Nombre **cumulé** de réémissions déjà programmées pour chaque trame.
    #
    # Il ne peut pas être lu sur `attempt.attempt` : `_prune_acknowledged` supprime, à chaque
    # itération du point fixe, les réémissions qu'un ACK reçu avant leur départ rend impossibles.
    # Supprimer un essai postérieur fait redescendre le dernier essai de la trame vers un rang
    # antérieur, ce qui **rouvre le budget**. Comme l'ensemble des ACK reçus oscille avec
    # l'occupation — l'inconnue même du point fixe — le budget était rouvert indéfiniment et
    # aucune configuration assez dense ne pouvait converger (75 rembobinages mesurés sur
    # 18 passes dans le cas étalon). `emis` ne décroît jamais : une trame est émise au plus
    # `1 + budget` fois, comme le veut la politique de réémission.
    emis: dict[tuple[int, int, int], int] = {}
    result = None
    events: tuple = ()
    planned: tuple = ()

    # Descentes partagées (jointure radio) : le planificateur Python est imposé, seul à pouvoir
    # déposer dans un arbitre commun. `AckTiming()` — délai nul, une copie — reproduit le
    # comportement nominal du cœur ; il est remplacé par `retransmit.ack_timing()` si la couche
    # MAC est déjà nécessaire (ACK retardé ou répété).
    timing = retransmit.ack_timing() if (retransmit.uses_ack_mac
                                         or avant_resolution is not None) else None
    occupation: tuple = ()
    mac_plan = None
    dernier_devoir = duty_cycle
    # Occupations déjà produites, pour détecter une oscillation de l'**occupation** elle-même —
    # distincte de celle du calendrier, gardée plus bas.
    occupations_vues: set = set()
    for _iteration in range(MAX_ITERATIONS_REEMISSIONS):
        # L'occupation **imposée** à cette itération est conservée, pour être comparée à celle
        # qui en sortira. Sans cette capture, la comparaison serait vide de sens : `occupation`
        # est réaffecté plus bas, avant le test de sortie.
        occupation_imposee = occupation
        # Un émetteur neuf à chaque itération : aucune occupation d'une passe précédente ne
        # survit à la suivante, et la convergence se lit sur l'égalité des occupations.
        #
        # L'état de rapport cyclique descendant doit renaître de la même façon, et pour la
        # même raison : chaque itération **rejoue toute la chronologie** depuis l'origine,
        # en y ajoutant les réémissions décidées à l'itération précédente. Le laisser
        # survivre compterait deux fois les mêmes émissions et repousserait la première
        # d'autant d'espacements qu'il y a eu d'itérations — mesuré : 293,756 s attendus
        # contre 726,908 s obtenus après trois itérations, soit 3 × 144,384 s de trop.
        devoir = None if duty_cycle is None else duty_cycle.nouvelle_passe()
        dernier_devoir = devoir
        arbitre = GatewayArbiter(duty_cycle=devoir)
        result, events, planned, mac_plan = _simulate(
            schedule, devices, gateway, propagation, radios, options, environment,
            timing=timing, busy=occupation, classes=device_classes,
            fcnt_down_start=retransmit.fcnt_down_start,
            payload=retransmit.downlink_payload, arbiter=arbitre,
            avant_resolution=avant_resolution, duty_cycle=devoir)
        recues = {record.device_index for record in result.records if record.outcome == 2}

        if mac_plan is None:
            livraisons = _deliveries(events, recues, len(schedule))
            recus = _match_ack(schedule, events)
            instants = {}
            # Série descendante du chemin du cœur : un FCntDown par ACK réellement émis, par
            # terminal et dans l'ordre des émissions (le réseau numérote ses descentes).
            descendants = {}
            suivant: dict[tuple[int, int], int] = {}
            for index in sorted(range(len(schedule)), key=lambda i: (schedule[i].end_ns, i)):
                if livraisons.get(index) in (DownlinkDelivery.DELIVERED,
                                             DownlinkDelivery.LOST_SENSITIVITY):
                    # Série descendante par terminal **et par session** : une jointure remet
                    # NFCntDown/AFCntDown à zéro, comme FCntUp.
                    cle = (schedule[index].device, schedule[index].session)
                    descendants[index] = suivant.get(cle, 0)
                    suivant[cle] = descendants[index] + 1
        else:
            from lsim.ack_mac import AckSort, AckWindow
            # `LATE` n'a pas de verdict propre dans `DownlinkDelivery` : il est rangé avec les
            # pertes de sensibilité. La classe exacte reste dans `AckOutcome.sort`.
            correspondance = {
                AckSort.STANDARD: DownlinkDelivery.DELIVERED,
                AckSort.LATE: DownlinkDelivery.LOST_SENSITIVITY,
                AckSort.LOST: DownlinkDelivery.LOST_SENSITIVITY,
                AckSort.DUPLICATE: DownlinkDelivery.DELIVERED,
                AckSort.GAP: DownlinkDelivery.LOST_SENSITIVITY,
                AckSort.NOT_SENT: DownlinkDelivery.NONE,
            }
            # Indices virtuels depuis la position dans les enregistrements.
            livraisons, recus, instants, descendants = {}, set(), {}, {}
            for position, record in enumerate(result.records):
                sortie = mac_plan.outcomes[position]
                virtuel = record.device_index
                verdict = correspondance[sortie.sort]
                if sortie.window is AckWindow.WINDOW_MISSED:
                    verdict = DownlinkDelivery.DEVICE_TRANSMITTING
                livraisons[virtuel] = verdict
                if sortie.received:
                    recus.add(virtuel)
                    retenue = sortie.accepted_emission
                    instants[virtuel] = (retenue.start_ns if retenue is not None
                                         else sortie.first_emission_ns)
                    descendants[virtuel] = sortie.f_cnt_down
            occupation = tuple(planned)

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
                                       ack=ack, acked=ack is AckReception.RECEIVED,
                                       ack_ns=instants.get(index),
                                       f_cnt_down=descendants.get(index)))
        schedule = mis_a_jour

        acquittees = {a.key for a in schedule if a.acked}
        dernier: dict[tuple[int, int, int], int] = {}
        for index, attempt in enumerate(schedule):
            cle = attempt.key
            if cle not in dernier or attempt.attempt > schedule[dernier[cle]].attempt:
                dernier[cle] = index

        nouvelles = []
        for index in sorted(dernier.values()):
            attempt = schedule[index]
            cle = attempt.key
            # Le budget porte sur le compte cumulé, non sur le rang courant — voir `emis` plus
            # haut. Le rang reste le seul point de départ honnête pour une trame jamais
            # réémise : `attempt.attempt` y égale le nombre de réémissions déjà programmées.
            if cle in acquittees or emis.get(cle, attempt.attempt) >= budget:
                continue
            debut = attempt.end_ns + retransmit.retransmit_delay_ms * 1_000_000
            if _is_stale(timelines, attempt.device, attempt.session, debut):
                # Une jointure a ouvert une nouvelle session : une trame de l'ancienne ne peut plus
                # être reçue (les clés ont changé). Elle n'est ni émise ni acquittée.
                perimees += 1
                continue
            if retransmit.enforce_duty_cycle and devices[attempt.device].duty_cycle < 1.0:
                airtime = _airtime_ns(devices[attempt.device])
                ecoule = sum(a.end_ns - a.start_ns for a in schedule if a.device == attempt.device)
                if ecoule + airtime > devices[attempt.device].duty_cycle * debut:
                    blocked.add((attempt.device, attempt.session, attempt.frame,
                                 attempt.attempt))
                    continue
            nouvelles.append(Attempt(device=attempt.device, frame=attempt.frame,
                                     attempt=attempt.attempt + 1, start_ns=debut,
                                     end_ns=debut + (attempt.end_ns - attempt.start_ns),
                                     received=False, delivery=DownlinkDelivery.NONE,
                                     ack=AckReception.NONE, acked=False,
                                     f_cnt_up=attempt.f_cnt_up, session=attempt.session))
            emis[cle] = emis.get(cle, attempt.attempt) + 1
        # --- Convergence de l'occupation radio (chemin MAC seulement) -----------------------
        # Sans la seconde condition, la boucle pouvait sortir dès la première itération : le
        # plan venait d'être produit sous une occupation vide, la trace qui l'avait engendré
        # n'était jamais refaite avec lui, et une descente pouvait chevaucher une montante
        # comptée comme reçue — un émetteur demi-duplex émettant pendant qu'il reçoit.
        #
        # Le chemin causal (`mac_plan is None`) n'est **pas** concerné : son occupation vient
        # du `RadioScheduler` du cœur, qui applique le demi-duplex par construction (U0.4).
        # `occupation` n'y est jamais réaffecté : la comparaison n'y aurait pas de sens.
        #
        # L'arbitre n'est délibérément **pas** amorcé avec l'occupation précédente : il la
        # redérive depuis un émetteur libre. L'amorcer compterait deux fois la même émission,
        # puisqu'il la verrait comme occupée par lui-même.
        if not nouvelles:
            if mac_plan is None or _canonique(planned) == _canonique(occupation_imposee):
                break
            # Calendrier stable, occupation encore instable : on rejoue la trace avec
            # l'occupation produite. Le calendrier ne change pas, donc la garde d'oscillation
            # **du calendrier** ne s'applique pas ici ; c'est celle de l'occupation qui opère.
            cle_occupation = _canonique(planned)
            if cle_occupation in occupations_vues:
                raise RuntimeError(
                    "pas de point fixe de l'occupation radio : la même occupation revient "
                    "sans jamais égaler celle qui l'a produite")
            occupations_vues.add(cle_occupation)
            continue
        schedule = schedule + nouvelles
        schedule = _prune_acknowledged(schedule)
        # L'état du système est la **paire** (calendrier, occupation imposée), pas le
        # calendrier seul. Un même calendrier peut revenir sous des occupations différentes :
        # ce n'est pas un cycle, seulement une répétition d'une projection incomplète.
        #
        # La méprise a coûté un faux diagnostic : l'essai 334 était déclaré oscillant de
        # période 3 alors qu'aucun état complet ne se répétait sur ses 22 passes. La garde
        # l'arrêtait à la 8ᵉ ; il converge à la 22ᵉ (192 intervalles imposés = produits).
        #
        # L'occupation est prise sous forme canonique, comme la condition de sortie : deux
        # occupations couvrant les mêmes intervalles sont le même état, quel que soit l'ordre
        # de restitution de l'arbitre.
        signature = (tuple((a.device, a.session, a.frame, a.attempt, a.start_ns)
                           for a in schedule), _canonique(occupation_imposee))
        if signature in vu:
            raise RuntimeError(
                "pas de point fixe des réémissions : état répété à l'identique (même "
                "calendrier sous la même occupation)")
        vu.add(signature)
    else:
        raise RuntimeError(f"pas de point fixe des réémissions après {MAX_ITERATIONS_REEMISSIONS} itérations")

    # --- Le résultat rendu doit être physiquement possible ---------------------------------
    # Un émetteur demi-duplex ne peut émettre pendant qu'il reçoit. C'est le filet qui rend
    # la convergence vérifiable de l'extérieur, et non seulement espérée.
    #
    # Il est **inatteignable en l'état** : la boucle ne sort que lorsque l'occupation produite
    # égale l'occupation imposée, et la trace a été jouée sous cette même occupation — une
    # montante qui la recouvre est donc `gateway_busy` (issue 3), jamais `received` (issue 2).
    # Mesuré : 0 déclenchement sur les 400 configurations de l'audit. Il reste en place comme
    # garantie contre une régression future de la condition de sortie, et il est testable
    # directement (voir `_verifier_coherence_occupation`).
    if mac_plan is not None and result is not None:
        _verifier_coherence_occupation(
            planned,
            tuple((int(r.start_ns), int(r.end_ns))
                  for r in result.records if r.outcome == 2))

    assert result is not None
    acquittees = {a.key for a in schedule if a.acked}
    receptions: dict[tuple[int, int, int], int] = {}
    for attempt in schedule:
        if attempt.received:
            receptions[attempt.key] = receptions.get(attempt.key, 0) + 1
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

    # Taxonomie : le plan MAC donne les quatre classes ; le chemin du cœur n'en produit aucune
    # (il n'émet qu'un ACK standard par trame reçue, sans copie ni retard).
    if mac_plan is not None:
        _comptes = mac_plan.counts
    else:
        from lsim.ack_mac import AckCounts

        _comptes = AckCounts(standard=sum(1 for a in schedule
                                          if a.ack is AckReception.RECEIVED),
                             not_sent=sum(1 for a in schedule if not a.received))

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
        acks_planned=(mac_plan.emissions if mac_plan is not None else
                      sum(1 for a in schedule if a.delivery not in (
                          DownlinkDelivery.NONE, DownlinkDelivery.NOT_SCHEDULED))),
        ack_duplicates_ignored=(mac_plan.duplicates_ignored if mac_plan is not None else 0),
        ack_standard=_comptes.standard, ack_late=_comptes.late, ack_lost=_comptes.lost,
        ack_duplicate=_comptes.duplicate, ack_gap=_comptes.gap,
        ack_not_sent=_comptes.not_sent,
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
        rejected_stale_session=perimees,
        duty_cycle=(None if dernier_devoir is None else dernier_devoir.report()),
    )


def simulate_confirmed_uplinks(devices: Sequence, gateway, propagation, radios, options,
                               retransmit: RetransmissionOptions = RetransmissionOptions(),
                               energy_profile: Optional[str] = None, environment=None,
                               with_engine_output: bool = False,
                               device_classes: Optional[Sequence[str]] = None,
                               duty_cycle=None) -> RetransmissionResult:
    """Uplinks confirmés, avec jointures radio quand `join_requests_s` est déclaré.

    Sans `join_requests_s`, l'appel est exactement celui de `_simulate_confirmed` : aucune jointure
    n'est jouée et le résultat ne porte pas de `joins`. Avec, les Join-Request passent par le moteur
    causal (temps de vol, collision, sensibilité, **rapport cyclique**), les Join-Accept par
    l'arbitre radio partagé (`lsim.arbitre`), et une session n'est ouverte que si le Join-Accept est
    reçu et non rejoué. Les compteurs ne sont donc remis à zéro que dans ce cas.

    **Émetteur partagé.** Les Join-Accept sont déposés dans le **même** `GatewayArbiter` que les
    ACK et les downlinks, à l'intérieur de chaque itération du point fixe : la file est
    chronologique, une émission en cours en retarde une autre, une fenêtre couverte n'est pas
    émise. L'occupation qui en résulte — ACK **et** Join-Accept — est réinjectée au moteur à
    l'itération suivante : une trame montante qui chevauche une descente est perdue.
    """
    if not retransmit.join_options.enabled:
        return _simulate_confirmed(devices, gateway, propagation, radios, options, retransmit,
                                   energy_profile, environment, with_engine_output,
                                   device_classes, duty_cycle=duty_cycle)

    from lsim.join import simulate_joins

    devices = list(devices)
    radios = list(radios)
    options = _replace(options, confirmed_uplinks=True)
    demandes = retransmit.join_options.requests(range(len(devices)))
    rapports = {terminal: devices[terminal].duty_cycle for terminal in range(len(devices))}
    # Itération causale. Le Join-Accept partage l'émetteur avec les ACK : on ne peut donc pas
    # savoir, avant résolution, si une tentative aboutit. On joue **toutes** les tentatives, on lit
    # les succès observés, et on rejoue : les tentatives postérieures à une jointure effectivement
    # obtenue disparaissent du calendrier du tour suivant. Aucune tentative n'est jamais retirée
    # sur une prévision, et aucune tentative rendue nécessaire par un échec n'est supprimée.
    timelines: dict = {}
    succes: dict = {}
    jointures = None
    signatures = set()
    for _ in range(8):
        boite: dict = {}
        # État de rapport cyclique descendant **neuf à chaque passe** : le point fixe rejoue la
        # même chronologie, y laisser survivre l'état de la passe précédente compterait deux
        # fois les mêmes émissions et refuserait ce que la passe précédente avait autorisé.
        duty = None if duty_cycle is None else duty_cycle.nouvelle_passe()

        def avant_resolution(arbitre, programme, boite=boite, timelines=timelines,
                             succes=succes):
            """Dépose les Join-Accept dans la passe en cours, après les ACK, avant résolution."""
            # Budget réglementaire : il comptabilise les émissions déjà jouées du terminal, parce
            # que la contrainte porte sur l'occupation de la sous-bande et non sur la nature de la
            # trame. Une tentative refusée n'entre pas dans le moteur : elle n'émet rien.
            # `enforce_duty_cycle: false` désactive le budget comme il désactive celui des
            # réémissions — une seule clef pour la même règle.
            livre = None
            if retransmit.enforce_duty_cycle:
                livre = DutyCycleLedger(rapports)
                for essai in programme:
                    livre.record(essai.device, essai.start_ns, essai.end_ns)
            boite["plan"] = simulate_joins(devices, gateway, propagation, radios, options,
                                           environment, demandes, timelines,
                                           data_attempts=programme,
                                           join_options=retransmit.join_options,
                                           arbiter=arbitre, ledger=livre,
                                           succes_connu=succes)

        result = _simulate_confirmed(devices, gateway, propagation, radios, options, retransmit,
                                     energy_profile, environment, with_engine_output,
                                     device_classes, timelines=timelines,
                                     avant_resolution=avant_resolution, duty_cycle=duty)
        plan = boite.get("plan")
        if plan is None:
            break
        jointures = plan.result()
        if jointures.succes == succes and jointures.timelines == timelines:
            break
        signature = (tuple(sorted(jointures.succes.items())),
                     tuple(sorted((terminal, len(horloge.sessions))
                                  for terminal, horloge in jointures.timelines.items())))
        if signature in signatures:
            raise RuntimeError(
                "jointures radio sans point fixe : le jeu de tentatives se r\u00e9p\u00e8te "
                "\u00e0 l'identique")
        signatures.add(signature)
        succes, timelines = jointures.succes, jointures.timelines
    return _replace(result,
                    joins=jointures.attempts if jointures is not None else (),
                    joins_blocked_by_duty_cycle=(jointures.blocked_by_duty_cycle
                                                 if jointures is not None else 0),
                    join_accepts_emitted=sum(sum(1 for e in t.accepts if e.emitted)
                                             for t in jointures.attempts)
                    if jointures is not None else 0)
