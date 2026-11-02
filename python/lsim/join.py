"""Jointure OTAA dans le moteur radio : Join-Request en uplink, Join-Accept en descente.

Ce module fait passer la jointure par le **moteur causal**, au lieu de la déclarer acceptée. Il ne
fait ni cryptographie ni validation de `MIC` : il simule le **transport** de la jointure, pas son
authentification (voir `docs/MAC_CONSOLIDATION.md` §9).

Sémantique des fenêtres, telle que LoRaWAN la définit : après un Join-Request le terminal ouvre
**RX1** (`JOIN_ACCEPT_DELAY1`, 5 s) puis **RX2** (`JOIN_ACCEPT_DELAY2`, 6 s). RX2 est une fenêtre de
**secours**, pas une seconde copie systématique : si le Join-Accept est reçu en RX1, aucune émission
RX2 n'a lieu. Le réseau n'émet en RX2 que lorsque RX1 n'a pas abouti (terminal en émission, descente
sous la sensibilité). Un Join-Accept **rejoué** est un cas distinct : c'est une émission
supplémentaire du même message (même `JoinNonce`), que le terminal reçoit et refuse — elle ne crée
aucune session.

| Étape | Ce que le moteur en fait |
|---|---|
| Join-Request | une transmission uplink de 23 octets (`lsim_encode_join_request`) : temps de vol, collision, sensibilité, couverture, placement causal |
| Join-Accept | une descente de 33 octets (`lsim_encode_join_accept`), en RX1 ou — si RX1 a échoué — en RX2 |
| session | ouverte **seulement** si un Join-Accept est reçu, si le terminal écoutait et si son `JoinNonce` dépasse le dernier accepté |

Deux limites explicites (§9.4) : le Join-Accept n'est opposé ni à l'occupation de la passerelle par
les ACK de données, ni au temps de vol des autres descentes.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Optional, Sequence

from lsim.ack_mac import _decodable
from lsim.downlink_plan import simulate_causal
from lsim.lora import RadioConfig, time_on_air_ns
from lsim.sessions import JoinAccept, SessionTimeline

JOIN_REQUEST_BYTES = 23      # `lsim_encode_join_request` : 23 octets exactement
JOIN_ACCEPT_BYTES = 33       # `lsim_encode_join_accept` : 33 octets (avec CFList)
JOIN_ACCEPT_DELAY1_NS = 5_000_000_000   # RX1 après le Join-Request
JOIN_ACCEPT_DELAY2_NS = 6_000_000_000   # RX2 : fenêtre de secours, pas une copie systématique
JOIN_RETRY_DELAY_NS = 10_000_000_000    # nouvelle tentative après un échec
JOIN_REPLAY_DELAY_NS = 1_000_000_000    # écart entre deux émissions du même Join-Accept

# `TxRecord.outcome` : 0 sous la sensibilité, 1 collision, 2 reçue, 3 passerelle occupée.
_UPLINK_OUTCOME = {0: "lost_sensitivity", 1: "lost_collision", 2: "received",
                   3: "lost_gateway_busy"}

RX1 = "rx1"
RX2 = "rx2"
REPLAY = "replay"


@dataclass(frozen=True)
class JoinRadioOptions:
    """Jointures radio : instants de Join-Request, tentatives, fenêtres, rejeux.

    `rx2_fallback` : RX2 n'est émise que si RX1 n'a pas abouti. Ce n'est pas une répétition.
    `accept_replays` : nombre de Join-Accept **rejoués** (même `JoinNonce`) après une acceptation,
    pour éprouver le rejet. Distinct du mécanisme RX1/RX2.
    """

    requests_s: tuple[int, ...] = ()
    retries: int = 1                 # 1 à 3 tentatives par jointure déclarée
    rx2_fallback: bool = True        # RX2 en secours de RX1
    accept_replays: int = 0          # 0 à 2 Join-Accept rejoués après acceptation

    def __post_init__(self) -> None:
        for instant in self.requests_s:
            if isinstance(instant, bool) or not isinstance(instant, int) or instant < 0:
                raise ValueError("join_requests_s doit contenir des entiers positifs")
        for precedent, suivant in zip(self.requests_s, self.requests_s[1:]):
            if suivant <= precedent:
                raise ValueError("join_requests_s : instants strictement croissants attendus")
        if not 1 <= self.retries <= 3:
            raise ValueError("join_retries doit être dans [1, 3]")
        if not 0 <= self.accept_replays <= 2:
            raise ValueError("join_accept_replays doit être dans [0, 2]")

    @property
    def enabled(self) -> bool:
        return bool(self.requests_s)

    def requests(self, devices: Sequence[int]) -> list[tuple[int, int]]:
        """Tentatives, par terminal : `(terminal, instant)`, du plus ancien au plus récent."""
        return [(device, instant_s * 1_000_000_000 + essai * JOIN_RETRY_DELAY_NS)
                for instant_s in self.requests_s
                for device in devices
                for essai in range(self.retries)]


@dataclass(frozen=True)
class AcceptEmission:
    """Une émission de Join-Accept **réellement effectuée**, avec sa fenêtre et son issue.

    `window` vaut `rx1`, `rx2` (secours) ou `replay` (émission d'un message déjà consommé).
    `outcome` vaut `delivered`, `not_listened`, `lost_sensitivity` ou `replayed`.
    """

    at_ns: int
    window: str
    outcome: str

    @property
    def received(self) -> bool:
        return self.outcome == "delivered"


@dataclass(frozen=True)
class JoinAttempt:
    """Une tentative de jointure, telle que le moteur l'a réellement jouée."""

    device: int
    request_ns: int
    request_end_ns: int
    request_outcome: str              # received | lost_sensitivity | lost_collision | lost_gateway_busy
    accepts: tuple[AcceptEmission, ...] = ()
    accept_ns: Optional[int] = None   # début de l'émission **acceptée** (None : aucune)
    accept_end_ns: Optional[int] = None
    session: int = 0                  # session ouverte (0 : aucune)
    nonce: Optional[int] = None       # JoinNonce **du simulateur** (rang), pas une valeur de clé

    @property
    def accept_window(self) -> Optional[str]:
        for emission in self.accepts:
            if emission.received:
                return emission.window
        return None

    @property
    def accept_outcome(self) -> Optional[str]:
        """Issue de la dernière émission ; `delivered` si l'une d'elles a abouti."""
        if not self.accepts:
            return None
        if self.accept_window is not None:
            return "delivered"
        return self.accepts[-1].outcome

    @property
    def accept_replays(self) -> int:
        """Join-Accept rejoués **reçus puis refusés** (émissions de fenêtre `replay`)."""
        return sum(1 for emission in self.accepts
                   if emission.window == REPLAY and emission.outcome == "replayed")

    @property
    def joined(self) -> bool:
        return self.session > 0


@dataclass(frozen=True)
class JoinResult:
    """Résultat complet d'une campagne de jointures radio.

    `timelines` : une horloge de sessions **par terminal** — deux terminaux peuvent joindre à des
    instants différents sans que l'un fasse changer la session de l'autre.
    """

    attempts: tuple[JoinAttempt, ...] = ()
    timelines: dict = field(default_factory=dict)

    @property
    def joined(self) -> int:
        return sum(1 for tentative in self.attempts if tentative.joined)

    @property
    def failed(self) -> int:
        return sum(1 for tentative in self.attempts if not tentative.joined)

    @property
    def requests(self) -> int:
        return len(self.attempts)


def join_request_device(device, at_ns: int):
    """Le terminal réduit à un seul Join-Request, à l'instant voulu.

    Même mécanisme que `retransmissions._virtual` : le moteur ne prend en entrée que des calendriers
    périodiques, donc une transmission isolée est un terminal à une transmission. La trame pèse
    23 octets, ce qui allonge son temps de vol par rapport à une trame de données.
    """
    return replace(device, start_offset_ns=int(at_ns), messages=1, downlink=None,
                   duty_cycle=1.0, payload_bytes=JOIN_REQUEST_BYTES, rf=device.rf)


def accept_airtime_ns(radio) -> int:
    """Temps de vol du Join-Accept, au débit d'écoute RX1 du terminal."""
    config = RadioConfig(spreading_factor=radio.rx1_sf, bandwidth_hz=radio.rx1_bw_hz,
                         coding_rate=1, low_data_rate_optimize=radio.rx1_sf >= 11)
    return time_on_air_ns(config, JOIN_ACCEPT_BYTES)


def _transmitting(attempts, device: int, instant: int) -> bool:
    """Le terminal est-il en train d'émettre à cet instant ? Alors il n'écoute pas."""
    return any(a.device == device and a.start_ns <= instant < a.end_ns for a in attempts)


def _records(devices, gateway, propagation, radios, options, environment, candidats):
    """Fait jouer tous les Join-Request candidats dans le moteur causal."""
    clones, clone_radios = [], []
    for device_index, at_ns in candidats:
        clones.append(join_request_device(devices[device_index], at_ns))
        clone_radios.append(radios[device_index])
    resultat, _busy = simulate_causal(list(devices) + clones, gateway, propagation, environment,
                                      list(radios) + clone_radios, options)
    trouve = {}
    for record in resultat.records:
        if record.device_index >= len(devices):
            trouve[candidats[record.device_index - len(devices)]] = record
    return trouve


def _evaluer(candidats, enregistrements, radios, options, data_attempts, join_options, nonces):
    """Une passe : RX1, puis RX2 **seulement si RX1 a échoué**, puis rejeux éventuels.

    `nonces` porte, par terminal, le dernier JoinNonce accepté (muté ici).
    Renvoie `(tentatives, acceptations, succès par terminal)`.
    """
    tentatives: list[JoinAttempt] = []
    acceptations: list[tuple[int, int, int]] = []  # (terminal, instant d'ouverture, nonce)
    succes: dict[int, int] = {}                    # terminal -> instant de la réussite

    for device_index, at_ns in candidats:
        if device_index in succes:
            continue        # terminal déjà joint dans cette passe : la tentative n'est pas jouée
        record = enregistrements.get((device_index, at_ns))
        if record is None:
            continue
        radio = radios[device_index]
        airtime = accept_airtime_ns(radio)
        if record.outcome != 2:
            tentatives.append(JoinAttempt(device_index, record.start_ns, record.end_ns,
                                          _UPLINK_OUTCOME.get(record.outcome, "lost")))
            continue

        def ecoute(instant: int) -> str:
            if _transmitting(data_attempts, device_index, instant):
                return "not_listened"
            if not _decodable(record.rssi_dbm, radio, options):
                return "lost_sensitivity"
            return "delivered"

        emissions: list[AcceptEmission] = []
        accepte = None                                  # (début, fin) de l'émission acceptée
        rx1 = record.end_ns + JOIN_ACCEPT_DELAY1_NS
        issue = ecoute(rx1)
        emissions.append(AcceptEmission(rx1, RX1, issue))
        if issue == "delivered":
            accepte = (rx1, rx1 + airtime)
        elif join_options.rx2_fallback:
            # Fenêtre de secours : RX2 n'est émise que parce que RX1 n'a pas abouti.
            rx2 = record.end_ns + JOIN_ACCEPT_DELAY2_NS
            issue2 = ecoute(rx2)
            emissions.append(AcceptEmission(rx2, RX2, issue2))
            if issue2 == "delivered":
                accepte = (rx2, rx2 + airtime)

        nonce = nonces.get(device_index, -1) + 1
        if accepte is not None:
            acceptations.append((device_index, accepte[1], nonce))
            succes[device_index] = at_ns
            nonces[device_index] = nonce
            # Rejeu : mêmes octets, même JoinNonce, après l'acceptation. Reçu puis refusé.
            for rang in range(join_options.accept_replays):
                instant = accepte[1] + (rang + 1) * JOIN_REPLAY_DELAY_NS
                issue_rejeu = ecoute(instant)
                emissions.append(AcceptEmission(
                    instant, REPLAY, "replayed" if issue_rejeu == "delivered" else issue_rejeu))

        tentatives.append(JoinAttempt(
            device_index, record.start_ns, record.end_ns, "received", tuple(emissions),
            accepte[0] if accepte is not None else None,
            accepte[1] if accepte is not None else None,
            0, nonce if accepte is not None else None))
    return tentatives, acceptations, succes


def simulate_joins(devices, gateway, propagation, radios, options, environment,
                   requests: Sequence[tuple[int, int]], timelines=None,
                   data_attempts: Sequence = (),
                   join_options: JoinRadioOptions = JoinRadioOptions()) -> JoinResult:
    """Joue les jointures déclarées dans le moteur causal.

    `requests` : `(terminal, instant du Join-Request)`, tentatives comprises. Dès qu'un terminal est
    joint, ses tentatives suivantes sont retirées du calendrier et la simulation est rejouée sans
    elles : une tentative qui n'a pas lieu ne doit pas provoquer de collision.
    `data_attempts` : calendrier des uplinks de données ; une émission en cours ferme la fenêtre.
    `timelines` : sessions ouvertes avant la jointure, par terminal.
    """
    timelines = dict(timelines or {})
    if not requests:
        return JoinResult(timelines=timelines)

    candidats = sorted(requests, key=lambda paire: (paire[1], paire[0]))
    nonces = {terminal: timeline.last.nonce for terminal, timeline in timelines.items()
              if timeline.last is not None}
    tentatives: list[JoinAttempt] = []
    acceptations: list[tuple[int, int, int]] = []
    for _ in range(4):
        enregistrements = _records(devices, gateway, propagation, radios, options, environment,
                                   candidats)
        copie_nonces = dict(nonces)
        tentatives, acceptations, succes = _evaluer(
            candidats, enregistrements, radios, options, data_attempts, join_options,
            copie_nonces)
        restants = [(d, t) for (d, t) in candidats if d not in succes or t <= succes[d]]
        if len(restants) == len(candidats):
            nonces = copie_nonces
            break
        candidats = restants

    # Une horloge par terminal : le nonce y est un rang local, donc strictement croissant pour
    # `SessionTimeline.accept`, sans qu'un terminal avance la session d'un autre.
    nouvelles = dict(timelines)
    ouvertures: dict[tuple[int, int], int] = {}
    for terminal, instant, nonce in sorted(acceptations, key=lambda item: item[1]):
        courante = nouvelles.get(terminal, SessionTimeline())
        if courante.last is not None and instant <= courante.last.opened_ns:
            # Déjà ouverte lors d'une passe précédente : on ne rouvre pas la même session.
            ouvertures[(terminal, instant)] = next(
                (session.index for session in courante.sessions
                 if session.opened_ns == instant), courante.current())
            continue
        courante = courante.accept(JoinAccept(at_ns=instant, nonce=nonce))
        nouvelles[terminal] = courante
        ouvertures[(terminal, instant)] = courante.current()

    corrigees = []
    for tentative in tentatives:
        if tentative.accept_ns is not None and tentative.accept_end_ns is not None:
            index = ouvertures.get((tentative.device, tentative.accept_end_ns), 0)
            if index:
                tentative = replace(tentative, session=index)
        corrigees.append(tentative)
    return JoinResult(tuple(corrigees), nouvelles)
