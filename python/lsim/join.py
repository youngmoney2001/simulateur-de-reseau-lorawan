"""Jointure OTAA dans le moteur radio : Join-Request en uplink, Join-Accept en descente.

Ce module fait passer la jointure par le **moteur causal**, au lieu de la déclarer acceptée. Il ne
fait ni cryptographie ni validation de `MIC` : il simule le **transport** de la jointure, pas son
authentification (voir `docs/MAC_CONSOLIDATION.md` §9).

| Étape | Ce que le moteur en fait |
|---|---|
| Join-Request | une transmission uplink de 23 octets (`lsim_encode_join_request`) : temps de vol, collision, sensibilité, couverture, placement causal |
| Join-Accept | une descente de 33 octets (`lsim_encode_join_accept`) émise à `JOIN_ACCEPT_DELAY1` (5 s), écoutée en RX1 ; copie éventuelle à 6 s en RX2 |
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
JOIN_ACCEPT_DELAY2_NS = 6_000_000_000   # RX2, pour une copie du même Join-Accept
JOIN_RETRY_DELAY_NS = 10_000_000_000    # nouvelle tentative après un échec

# `TxRecord.outcome` : 0 sous la sensibilité, 1 collision, 2 reçue, 3 passerelle occupée.
_UPLINK_OUTCOME = {0: "lost_sensitivity", 1: "lost_collision", 2: "received",
                   3: "lost_gateway_busy"}


@dataclass(frozen=True)
class JoinRadioOptions:
    """Jointures radio : instants de Join-Request, tentatives, copies du Join-Accept."""

    requests_s: tuple[int, ...] = ()
    retries: int = 1                 # 1 à 3 tentatives par jointure déclarée
    accept_repetitions: int = 1      # 1 (RX1) ou 2 (copie en RX2)

    def __post_init__(self) -> None:
        for instant in self.requests_s:
            if isinstance(instant, bool) or not isinstance(instant, int) or instant < 0:
                raise ValueError("join_requests_s doit contenir des entiers positifs")
        for precedent, suivant in zip(self.requests_s, self.requests_s[1:]):
            if suivant <= precedent:
                raise ValueError("join_requests_s : instants strictement croissants attendus")
        if not 1 <= self.retries <= 3:
            raise ValueError("join_retries doit être dans [1, 3]")
        if not 1 <= self.accept_repetitions <= 2:
            raise ValueError("join_accept_repetitions doit être dans [1, 2]")

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
class JoinAttempt:
    """Une tentative de jointure, telle que le moteur l'a réellement jouée."""

    device: int
    request_ns: int
    request_end_ns: int
    request_outcome: str              # received | lost_sensitivity | lost_collision | lost_gateway_busy
    accept_ns: Optional[int] = None   # instant d'émission du Join-Accept retenu
    accept_end_ns: Optional[int] = None
    accept_outcome: Optional[str] = None   # delivered | not_listened | lost_sensitivity | replayed
    session: int = 0                  # session ouverte (0 : aucune)
    nonce: Optional[int] = None       # JoinNonce **du simulateur** (rang), pas une valeur de clé
    accept_replays: int = 0           # copies reçues du même Join-Accept, refusées comme rejouées

    @property
    def joined(self) -> bool:
        return self.session > 0


@dataclass(frozen=True)
class JoinResult:
    """Résultat complet d'une campagne de jointures radio."""

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


def _evaluer(candidats, enregistrements, radios, options, data_attempts, repetitions,
             nonces: dict[int, int]):
    """Une passe : quelles tentatives reçoivent un Join-Accept, et lesquelles sont rejouées.

    `nonces` porte, par terminal, le dernier JoinNonce accepté (muté ici).
    Renvoie `(tentatives, acceptations, succès par terminal)`.
    """
    tentatives: list[JoinAttempt] = []
    acceptations: list[tuple[int, int, int]] = []  # (terminal, instant, nonce par terminal)
    succes: dict[int, int] = {}                   # terminal -> instant de la tentative réussie

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
        accept_ns = record.end_ns + JOIN_ACCEPT_DELAY1_NS
        copies = [record.end_ns + JOIN_ACCEPT_DELAY2_NS] if repetitions == 2 else []
        nonce = nonces.get(device_index, -1) + 1
        issue, retenu, debut, rejouees = None, None, None, 0
        for instant in [accept_ns] + copies:
            if _transmitting(data_attempts, device_index, instant):
                issue = issue or "not_listened"
                continue
            if not _decodable(record.rssi_dbm, radio, options):
                issue = issue or "lost_sensitivity"
                continue
            if retenu is not None:
                # Deuxième copie reçue du **même** Join-Accept : même JoinNonce, donc rejouée.
                issue = issue or "replayed"
                rejouees += 1
                continue
            retenu, debut, issue = nonce, instant, "delivered"
            acceptations.append((device_index, instant + airtime, nonce))
            succes[device_index] = at_ns
        if retenu is not None:
            nonces[device_index] = nonce
        tentatives.append(JoinAttempt(device_index, record.start_ns, record.end_ns, "received",
                                      debut or accept_ns, (debut or accept_ns) + airtime,
                                      issue or "lost", 0, retenu, rejouees))
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
    for _ in range(4):
        enregistrements = _records(devices, gateway, propagation, radios, options, environment,
                                   candidats)
        copie_nonces = dict(nonces)
        tentatives, acceptations, succes = _evaluer(
            candidats, enregistrements, radios, options, data_attempts,
            join_options.accept_repetitions, copie_nonces)
        restants = [(d, t) for (d, t) in candidats
                    if d not in succes or t <= succes[d]]
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
        if tentative.accept_outcome == "delivered" and tentative.accept_end_ns is not None:
            index = ouvertures.get((tentative.device, tentative.accept_end_ns), 0)
            if index:
                tentative = replace(tentative, session=index)
        corrigees.append(tentative)
    return JoinResult(tuple(corrigees), nouvelles)
