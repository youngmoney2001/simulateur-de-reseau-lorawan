"""Jointure OTAA dans le moteur radio : Join-Request en uplink, Join-Accept en descente.

Ce module fait passer la jointure par le **moteur causal**, au lieu de la déclarer acceptée. Il ne
fait ni cryptographie ni validation de `MIC` : il simule le **transport** de la jointure, pas son
authentification (voir `docs/MAC_CONSOLIDATION.md` §9 et §10).

Sémantique des fenêtres, telle que LoRaWAN la définit : après un Join-Request le terminal ouvre
**RX1** (`JOIN_ACCEPT_DELAY1`, 5 s) puis **RX2** (`JOIN_ACCEPT_DELAY2`, 6 s). RX2 est une fenêtre de
**secours**, pas une seconde copie systématique : si le Join-Accept est reçu en RX1, aucune émission
RX2 n'a lieu. Le réseau n'émet en RX2 que lorsque RX1 n'a pas abouti (terminal en émission, descente
sous la sensibilité, **ou passerelle déjà en émission**). Un Join-Accept **rejoué** est un cas
distinct : c'est une émission supplémentaire du même message (même `JoinNonce`), que le terminal
reçoit et refuse — elle ne crée aucune session.

| Étape | Ce que le moteur en fait |
|---|---|
| Join-Request | une transmission uplink de 23 octets (`lsim_encode_join_request`) : temps de vol, collision, sensibilité, couverture, placement causal, **et rapport cyclique du terminal** |
| Join-Accept | une descente de 33 octets (`lsim_encode_join_accept`), placée par l'arbitre radio partagé (`lsim.arbitre`) : RX1, puis RX2 en secours, puis rejeux éventuels |
| session | ouverte **seulement** si un Join-Accept est reçu, si le terminal écoutait et si son `JoinNonce` dépasse le dernier accepté |

## Ressources partagées (D3.13)

Le Join-Accept passe par le **même** `GatewayArbiter` que les ACK et les downlinks : une seule
file d'émission, `début = max(instant_prêt, occupé_jusqu'à)`. Trois conséquences, toutes mesurées :

1. un Join-Accept dont la fenêtre est couverte par une émission en cours **n'est pas émis**
   (`gateway_busy`) ; RX2 est alors tentée en secours ;
2. un Join-Accept émis **occupe** l'émetteur : un ACK demandé dans la seconde suivante est
   retardé, et une trame montante qui le chevauche est perdue (demi-duplex, par le point fixe) ;
3. une émission supprimée, retardée ou manquée **ne crée aucune session**.

Le Join-Request, lui, passe par `DutyCycleLedger` : le rapport cyclique configuré du terminal est
un budget (`airtime cumulé + airtime <= rapport × instant`), appliqué avant l'appel au moteur. Une
tentative refusée n'est **pas** une émission : elle n'entre pas dans la simulation, ne provoque
aucune collision et ne consomme aucun temps d'antenne.

## Causalité du jeu de tentatives

Le Join-Accept partage l'émetteur de la passerelle avec les ACK et les autres descentes. Son issue
n'est donc connue qu'**après** le placement partagé, jamais avant. Une tentative ne peut par
conséquent être retirée du calendrier que si une jointure a été **observée** — jamais sur une
prévision. Prévoir, ce serait retirer la tentative de secours d'un terminal qui, en fait, n'a pas
réussi à joindre.

Sur le chemin de l'arbitre partagé (`arbiter=` fourni), `simulate_joins` joue **toutes** les
tentatives, lit les succès dans `JoinResult.succes`, et l'appelant rejoue : les tentatives
postérieures à une jointure obtenue disparaissent au tour suivant. Au premier tour, rien n'est
observé : aucune tentative n'est supprimée. Une tentative postérieure à une jointure déjà obtenue
dans la même passe n'émet pas de Join-Accept (`EmissionRequest.condition`), donc elle ne coûte
rien d'autre que sa place dans le calendrier, une seule passe durant.

Sur le chemin **sans** arbitre partagé, la jointure s'arbitre seule : l'évaluateur y est le
placement définitif, de sorte que la passe de sélection y est causale — ce qu'elle a obtenu est ce
qui a été joué, sans prévision d'aucune sorte.

## Limites explicites

- **Aucune cryptographie** : ni clé, ni `MIC`, ni chiffrement. « Reçu » veut dire « décodable au
  niveau radio ».
- **La programmation causale est itérative et bornée.** Le point fixe est recherché en au plus 8
  tours ; un état qui se répète à l'identique lève `RuntimeError` plutôt que de rendre un résultat
  approximatif. La limite est le coût, pas l'exactitude : deux à trois tours en pratique.
- **Une seule jointure par terminal** : `join_requests_s` ne modélise pas le rejoint 1.1.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Optional, Sequence

from lsim.ack_mac import RX1_WINDOW_NS, _decodable
from lsim.arbitre import DUTY_CYCLE, EmissionRequest, GatewayArbiter
from lsim.downlink_plan import simulate_causal
from lsim.lora import RadioConfig, time_on_air_ns
from lsim.sessions import JoinAccept, SessionTimeline

JOIN_REQUEST_BYTES = 23      # `lsim_encode_join_request` : 23 octets exactement
JOIN_ACCEPT_BYTES = 33       # `lsim_encode_join_accept` : 33 octets (avec CFList)
JOIN_ACCEPT_DELAY1_NS = 5_000_000_000   # RX1 après le Join-Request
JOIN_ACCEPT_DELAY2_NS = 6_000_000_000   # RX2 : fenêtre de secours, pas une copie systématique
JOIN_RETRY_DELAY_NS = 10_000_000_000    # nouvelle tentative après un échec
JOIN_REPLAY_DELAY_NS = 1_000_000_000    # écart entre deux émissions du même Join-Accept
# Durée d'ouverture de la fenêtre de jointure : **hypothèse du simulateur**, la même que la
# fenêtre RX1 des données. LoRaWAN fixe le délai d'ouverture (`JOIN_ACCEPT_DELAY1/2`), pas la
# durée d'écoute du terminal.
JOIN_WINDOW_NS = RX1_WINDOW_NS

# `TxRecord.outcome` : 0 sous la sensibilité, 1 collision, 2 reçue, 3 passerelle occupée.
_UPLINK_OUTCOME = {0: "lost_sensitivity", 1: "lost_collision", 2: "received",
                   3: "lost_gateway_busy"}

RX1 = "rx1"
RX2 = "rx2"
REPLAY = "replay"


def _issue_non_emise(emission) -> str:
    """Issue d'une émission que l'arbitre n'a **pas** faite.

    Deux causes, deux issues : la fenêtre était couverte par une émission en cours
    (`gateway_busy`, rien n'occupe la sous-bande) ou la sous-bande l'interdisait
    (`duty_cycle`, rapport cyclique descendant). Les confondre ferait croire qu'une
    interdiction réglementaire est une contention d'émetteur.
    """
    return "duty_cycle" if emission.verdict == "duty_cycle" else "gateway_busy"

# Verdict de l'arbitre valant « refusée par le rapport cyclique descendant » (`lsim.arbitre`).
# Importé ici pour ne pas confondre, dans les issues, une fenêtre couverte par une émission en
# cours et une émission interdite par la sous-bande.
_VERDICT_DUTY_CYCLE = "duty_cycle"
BLOCKED_DUTY_CYCLE = "blocked_duty_cycle"   # tentative refusée par le rapport cyclique :
                                           # aucune émission


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
    `outcome` vaut `delivered`, `not_listened`, `lost_sensitivity`, `gateway_busy`,
    `duty_cycle` ou `replayed`.
    `gateway_busy` : la passerelle émettait déjà et n'a pas pu placer l'émission dans la fenêtre ;
    `duty_cycle` : la sous-bande l'interdisait (rapport cyclique descendant, D3.14). Dans les
    deux cas **rien n'a été émis**, la fenêtre est perdue, et aucune session n'est ouverte ;
    **rien n'a été émis**, et l'occupation de l'émetteur n'en porte aucune trace.
    """

    at_ns: int
    window: str
    outcome: str

    @property
    def received(self) -> bool:
        return self.outcome == "delivered"

    @property
    def emitted(self) -> bool:
        """L'émetteur a-t-il réellement produit cette émission ?

        `gateway_busy` : la fenêtre était couverte, **rien n'a été émis**. L'émission est datée
        (pour la trace) mais n'occupe pas la ressource.
        """
        return self.outcome != "gateway_busy"


@dataclass(frozen=True)
class JoinAttempt:
    """Une tentative de jointure, telle que le moteur l'a réellement jouée."""

    device: int
    request_ns: int
    request_end_ns: int
    request_outcome: str              # received | lost_sensitivity | lost_collision
                                      # | lost_gateway_busy | blocked_duty_cycle
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

    @property
    def emitted(self) -> bool:
        """La tentative a-t-elle réellement occupé la voie montante ?"""
        return self.request_outcome != BLOCKED_DUTY_CYCLE


@dataclass(frozen=True)
class JoinResult:
    """Résultat complet d'une campagne de jointures radio.

    `timelines` : une horloge de sessions **par terminal** — deux terminaux peuvent joindre à des
    instants différents sans que l'un fasse changer la session de l'autre.
    """

    attempts: tuple[JoinAttempt, ...] = ()
    timelines: dict = field(default_factory=dict)
    blocked_by_duty_cycle: int = 0   # tentatives refusées par le rapport cyclique
    # Succès **observés** au placement : terminal -> instant de la tentative qui a abouti. Vide
    # quand rien n'a abouti. C'est cette grandeur qui décide des tentatives suivantes, jamais une
    # prévision : voir « Causalité du jeu de tentatives » en tête de module.
    succes: dict = field(default_factory=dict)

    @property
    def joined(self) -> int:
        return sum(1 for tentative in self.attempts if tentative.joined)

    @property
    def failed(self) -> int:
        return sum(1 for tentative in self.attempts if not tentative.joined)

    @property
    def requests(self) -> int:
        return len(self.attempts)


class JoinPlan:
    """Join-Accept déposés auprès d'un arbitre partagé, en attente de résolution.

    Les émissions ne sont connues qu'après `arbitre.resolve()` : c'est l'arbitre qui décide si le
    Join-Accept tient dans sa fenêtre, face aux ACK et aux autres descentes déjà déposés.
    """

    def __init__(self, attentes, nonces, bloquees, timelines):
        self._attentes = attentes
        self._nonces = nonces
        self._bloquees = bloquees
        self._timelines = timelines

    def result(self) -> JoinResult:
        """Tentatives, sessions et succès **observés**, après résolution de l'arbitre."""
        tentatives, acceptations, succes = _clore(self._attentes, self._nonces)
        return _assembler(self._bloquees, tentatives, acceptations, self._timelines, succes)


def join_request_device(device, at_ns: int):
    """Le terminal réduit à un seul Join-Request, à l'instant voulu.

    Même mécanisme que `retransmissions._virtual` : le moteur ne prend en entrée que des calendriers
    périodiques, donc une transmission isolée est un terminal à une transmission. La trame pèse
    23 octets, ce qui allonge son temps de vol par rapport à une trame de données.

    Le rapport cyclique du terminal est transmis tel quel au moteur : il n'a aucun effet ici (une
    seule émission, donc aucun espacement à calculer), mais il ne doit pas être neutralisé — c'est
    `DutyCycleLedger` qui applique le budget, avant l'appel au moteur.
    """
    return replace(device, start_offset_ns=int(at_ns), messages=1, downlink=None,
                   payload_bytes=JOIN_REQUEST_BYTES, rf=device.rf)


def accept_airtime_ns(radio, window: str = RX1) -> int:
    """Temps de vol du Join-Accept, au débit de la fenêtre dans laquelle il est émise.

    RX2 est le repli régional : fréquence et débit **propres**, distincts de RX1 (`DLSettings`).
    Un Join-Accept émis en RX2 au SF12 occupe l'émettre bien plus longtemps que le même en RX1 au
    SF7 — le temps d'antenne suit donc la fenêtre réellement émise, sans quoi l'occupation de la
    passerelle, et par suite son budget réglementaire, seraient sous-estimés.
    Un rejeu réémettant la **même** trame, il garde le débit de la fenêtre qui l'a portée.
    """
    from lsim.trace_events import downlink_phy   # import local : évite un cycle d'importation

    _freq, sf, bw = downlink_phy(radio, window)
    config = RadioConfig(spreading_factor=sf, bandwidth_hz=bw, coding_rate=1,
                         low_data_rate_optimize=bw > 0 and (2 ** sf) / bw > 0.016)
    return time_on_air_ns(config, JOIN_ACCEPT_BYTES)


def join_request_airtime_ns(device) -> int:
    """Temps de vol du Join-Request (23 octets), au débit montant du terminal."""
    sf = device.spreading_factor
    config = RadioConfig(spreading_factor=sf, bandwidth_hz=125_000, coding_rate=1,
                         low_data_rate_optimize=sf >= 11)
    return time_on_air_ns(config, JOIN_REQUEST_BYTES)


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


class _Attente:
    """Une tentative dont les émissions sont déposées, en attente de résolution de l'arbitre."""

    __slots__ = ("device_index", "at_ns", "request_ns", "request_end_ns", "request_outcome",
                 "emissions", "accepte")

    def __init__(self, device_index: int, at_ns: int, request_ns: int, request_end_ns: int,
                 request_outcome: str):
        self.device_index = device_index
        self.at_ns = at_ns
        self.request_ns = request_ns
        self.request_end_ns = request_end_ns
        self.request_outcome = request_outcome
        self.emissions: list[AcceptEmission] = []
        self.accepte: Optional[tuple[int, int]] = None

    def finalize(self) -> JoinAttempt:
        return JoinAttempt(self.device_index, self.request_ns, self.request_end_ns,
                           self.request_outcome, tuple(self.emissions),
                           self.accepte[0] if self.accepte is not None else None,
                           self.accepte[1] if self.accepte is not None else None, 0, None)


def _deposer(device_index, at_ns, record, radio, options, data_attempts, join_options, arbitre,
             attente: _Attente, accepte_par: dict):
    """Dépose la demande RX1 d'une tentative ; RX2 et rejeux naîtront de la réaction.

    Fonction séparée pour que chaque tentative ait sa propre fermeture : les réactions sont
    appelées pendant la résolution, donc bien après la boucle qui les a créées.
    """
    # Le temps d'antenne suit la fenêtre émise : RX1 et RX2 n'ont ni le même débit ni la même
    # fréquence. Un rejeu garde celui de la fenêtre qui a porté l'acceptation — même trame.
    airtimes = {RX1: accept_airtime_ns(radio, RX1), RX2: accept_airtime_ns(radio, RX2)}

    def ecoute(instant: int, fenetre_emise: str = RX1) -> str:
        # Le seuil de sensibilité suit la fenêtre émise : RX2 a son propre débit régional, et le
        # juger avec le seuil de RX1 déclarerait perdue une acceptation que le terminal entend.
        # Même règle que `_seuil_dispositif` dans `trace_events` et `_decodable` dans `ack_mac`.
        if _transmitting(data_attempts, device_index, instant):
            return "not_listened"
        if not _decodable(record.rssi_dbm, radio, options, en_rx2=(fenetre_emise == RX2)):
            return "lost_sensitivity"
        return "delivered"

    def fenetre(instant: int, fenetre_emise: str = RX1) -> EmissionRequest:
        # La fréquence suit la fenêtre : RX1 et RX2 ne sont pas dans la même sous-bande, donc
        # n'ont pas le même droit d'émission. `rx2_hz = 0` quand aucun plan régional ne
        # définit RX2 : l'arbitre y lit « fréquence non renseignée », aucune contrainte.
        freq_hz = radio.rx1_hz if fenetre_emise == RX1 else radio.rx2_hz
        return EmissionRequest(label="join_accept", device=device_index, ready_ns=instant,
                               duration_ns=airtimes[fenetre_emise], freq_hz=freq_hz,
                               window=(instant, instant + JOIN_WINDOW_NS))

    def rejeux(deposer, depuis: int, fenetre_source: str) -> None:
        """Rejeu : mêmes octets, même JoinNonce, après l'acceptation. Reçu puis refusé.

        Même fenêtre que l'acceptation : c'est la même trame, au même débit.
        """
        for rang in range(join_options.accept_replays):
            deposer(fenetre(depuis + (rang + 1) * JOIN_REPLAY_DELAY_NS, fenetre_source),
                    ensuite=apres_rejeu(fenetre_source))

    def apres_rejeu(fenetre_source: str):
        """Réaction d'un rejeu, fermée sur la fenêtre de l'acceptation qui l'a déclenché.

        Le rejeu rejoue la même trame au même débit : son seuil de sensibilité est donc celui de
        la fenêtre source, d'où la fermeture — la réaction ne reçoit que l'émission.
        """
        def reaction(emission, deposer) -> None:
            if not emission.emitted:
                issue = _issue_non_emise(emission)
            else:
                brut = ecoute(emission.start_ns, fenetre_source)
                issue = "replayed" if brut == "delivered" else brut
            attente.emissions.append(AcceptEmission(emission.start_ns, REPLAY, issue))
        return reaction

    def apres_rx2(emission, deposer) -> None:
        if not emission.emitted:
            issue = _issue_non_emise(emission)
        else:
            issue = ecoute(emission.start_ns, RX2)
        attente.emissions.append(AcceptEmission(emission.start_ns, RX2, issue))
        if issue == "delivered":
            attente.accepte = (emission.start_ns, emission.end_ns)
            accepte_par[device_index] = emission.start_ns
            rejeux(deposer, emission.end_ns, RX2)

    def apres_rx1(emission, deposer) -> None:
        if not emission.emitted:
            # « La passerelle émettait déjà » n'est qu'une des causes : une émission refusée
            # par le rapport cyclique descendant n'a pas non plus eu lieu, mais la cause est
            # réglementaire et l'issue le dit.
            issue = _issue_non_emise(emission)
        else:
            issue = ecoute(emission.start_ns, RX1)
        attente.emissions.append(AcceptEmission(emission.start_ns, RX1, issue))
        if issue == "delivered":
            attente.accepte = (emission.start_ns, emission.end_ns)
            accepte_par[device_index] = emission.start_ns
            rejeux(deposer, emission.end_ns, RX1)
        elif join_options.rx2_fallback:
            # Fenêtre de secours : RX2 n'est émise que parce que RX1 n'a pas abouti.
            deposer(fenetre(record.end_ns + JOIN_ACCEPT_DELAY2_NS, RX2), ensuite=apres_rx2)

    demande = fenetre(record.end_ns + JOIN_ACCEPT_DELAY1_NS, RX1)
    # Un terminal déjà joint dans cette passe ne reçoit pas de second Join-Accept : la condition
    # est évaluée au moment du placement, quand l'issue des tentatives précédentes est connue.
    arbitre.demand(replace(demande, condition=lambda: device_index not in accepte_par),
                   ensuite=apres_rx1)


def _evaluer(candidats, enregistrements, radios, options, data_attempts, join_options, arbitre):
    """Dépose les demandes de Join-Accept auprès de l'arbitre.

    Renvoie les tentatives **en attente** : leurs émissions ne sont connues qu'après
    `arbitre.resolve()`. RX2 naît du placement de RX1 (secours) et les rejeux naissent d'une
    acceptation ; déposés depuis la réaction de l'arbitre, ils sont placés à leur propre instant
    dans la même file chronologique, devant les demandes déjà déposées qui sont plus tardives.
    """
    attentes: list[_Attente] = []
    accepte_par: dict[int, int] = {}
    for device_index, at_ns in candidats:
        record = enregistrements.get((device_index, at_ns))
        if record is None:
            continue
        attente = _Attente(device_index, at_ns, record.start_ns, record.end_ns,
                           _UPLINK_OUTCOME.get(record.outcome, "lost"))
        attentes.append(attente)
        if record.outcome != 2:
            continue
        _deposer(device_index, at_ns, record, radios[device_index], options, data_attempts,
                 join_options, arbitre, attente, accepte_par)
    return attentes


def _clore(attentes, nonces):
    """Attribue les `JoinNonce` et referme les tentatives, **après** résolution de l'arbitre."""
    tentatives: list[JoinAttempt] = []
    acceptations: list[tuple[int, int, int]] = []  # (terminal, instant d'ouverture, nonce)
    succes: dict[int, int] = {}                    # terminal -> instant de la réussite
    for attente in attentes:
        tentative = attente.finalize()
        if tentative.accept_end_ns is not None:
            nonce = nonces.get(attente.device_index, -1) + 1
            nonces[attente.device_index] = nonce
            tentative = replace(tentative, nonce=nonce)
            acceptations.append((attente.device_index, tentative.accept_end_ns, nonce))
            succes[attente.device_index] = attente.at_ns
        tentatives.append(tentative)
    return tentatives, acceptations, succes


def simulate_joins(devices, gateway, propagation, radios, options, environment,
                   requests: Sequence[tuple[int, int]], timelines=None,
                   data_attempts: Sequence = (),
                   join_options: JoinRadioOptions = JoinRadioOptions(),
                   arbiter: Optional[GatewayArbiter] = None,
                   ledger=None, succes_connu: Optional[dict] = None) -> JoinResult:
    """Joue les jointures déclarées dans le moteur causal.

    `requests` : `(terminal, instant du Join-Request)`, tentatives comprises. Dès qu'un terminal est
    joint, ses tentatives suivantes sont retirées du calendrier et la simulation est rejouée sans
    elles : une tentative qui n'a pas lieu ne doit pas provoquer de collision.
    `data_attempts` : calendrier des uplinks de données ; une émission en cours ferme la fenêtre.
    `timelines` : sessions ouvertes avant la jointure, par terminal.
    `arbiter` : émetteur partagé (`lsim.arbitre`). Fourni, les Join-Accept y sont **déposés** et
    la fonction renvoie un `JoinPlan`, à refermer après `arbitre.resolve()`. Sans arbitre, la
    jointure s'arbitre seule (contention entre Join-Accept seulement) et renvoie un `JoinResult`.
    `ledger` : budget de rapport cyclique par terminal (`DutyCycleLedger`). Fourni, une tentative
    qui le dépasse n'est **pas** émise : elle n'entre pas dans le moteur.
    `succes_connu` : succès **observés** au tour précédent (`terminal -> instant`). Uniquement
    sur le chemin de l'arbitre partagé, où il remplace la sonde : les tentatives postérieures à
    une jointure effectivement obtenue sont retirées, et **celles-là seulement**. Vide au premier
    tour, il ne retire rien — une tentative n'est jamais supprimée sur une prévision.
    """
    timelines = dict(timelines or {})
    if not requests:
        plan = JoinPlan([], {}, [], timelines) if arbiter is not None else None
        return plan if plan is not None else JoinResult(timelines=timelines)

    candidats = sorted(requests, key=lambda paire: (paire[1], paire[0]))
    nonces = {terminal: timeline.last.nonce for terminal, timeline in timelines.items()
              if timeline.last is not None}

    # Rapport cyclique : une tentative refusée n'est pas une émission. Elle est retirée du
    # calendrier **avant** l'appel au moteur, donc ne provoque aucune collision et ne consomme
    # aucun temps d'antenne.
    bloquees: list[JoinAttempt] = []
    if ledger is not None:
        gardees = []
        for device_index, at_ns in candidats:
            airtime = join_request_airtime_ns(devices[device_index])
            if not ledger.allows(device_index, at_ns, airtime):
                ledger.refuse(device_index)
                bloquees.append(JoinAttempt(device_index, at_ns, at_ns + airtime, BLOCKED_DUTY_CYCLE))
                continue
            gardees.append((device_index, at_ns))
        candidats = gardees

    copie = dict(nonces)

    if arbiter is None:
        # Sans arbitre partagé, la jointure s'arbitre seule : l'évaluateur **est** le placement
        # définitif. Le jeu de tentatives se déduit donc de ce qui a été réellement obtenu, à
        # chaque passe, sans prévision d'aucune sorte.
        enregistrements: dict = {}
        for _ in range(4):
            if not candidats:
                break
            enregistrements = _records(devices, gateway, propagation, radios, options,
                                       environment, candidats)
            sonde = GatewayArbiter()
            attentes = _evaluer(candidats, enregistrements, radios, options, data_attempts,
                                join_options, sonde)
            sonde.resolve()
            _tentatives, _acceptations, succes = _clore(attentes, dict(copie))
            restants = [(d, t) for (d, t) in candidats if d not in succes or t <= succes[d]]
            if len(restants) == len(candidats):
                break
            candidats = restants
        arbitre_local = GatewayArbiter()
        attentes = _evaluer(candidats, enregistrements if candidats else {}, radios, options,
                            data_attempts, join_options, arbitre_local)
        arbitre_local.resolve()
        tentatives, acceptations, succes = _clore(attentes, copie)
        return _assembler(bloquees, tentatives, acceptations, timelines, succes)

    # Arbitre partagé : **aucune sonde**. Le jeu de tentatives jouées se déduit des succès déjà
    # observés, jamais d'une prévision. Au premier tour il n'y en a aucun, donc toutes les
    # tentatives sont jouées ; une tentative postérieure à une jointure obtenue n'émet pas de
    # Join-Accept (condition de `EmissionRequest`) et elle est retirée du calendrier au tour
    # suivant, quand le succès est connu. La causalité est rétablie par itération, du côté de
    # l'appelant (`retransmissions.simulate_confirmed_uplinks`).
    if succes_connu:
        candidats = [(d, t) for (d, t) in candidats
                     if d not in succes_connu or t <= succes_connu[d]]
    if not candidats:
        return JoinPlan([], copie, bloquees, timelines)
    enregistrements = _records(devices, gateway, propagation, radios, options, environment,
                               candidats)
    attentes = _evaluer(candidats, enregistrements, radios, options, data_attempts,
                        join_options, arbiter)
    return JoinPlan(attentes, copie, bloquees, timelines)


def _assembler(bloquees, tentatives, acceptations, timelines, succes=None) -> JoinResult:
    """Ouvre les sessions, une horloge par terminal, et rattache chaque tentative à la sienne."""
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
    return JoinResult(tuple(bloquees) + tuple(corrigees), nouvelles,
                      blocked_by_duty_cycle=len(bloquees),
                      succes=dict(succes or {}))
