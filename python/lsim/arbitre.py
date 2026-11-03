"""Arbitre radio partagé : un émetteur de passerelle, un budget réglementaire par terminal.

Ce module est la **source de vérité unique** pour deux questions que trois implémentations
indépendantes traitaient chacune de son côté avant D3.13 :

| Question | Avant D3.13 | Après |
|---|---|---|
| la passerelle peut-elle émettre à cet instant ? | `busy_until` local dans `trace_events._schedule_gateway`, `busy_until` local dans `ack_mac.plan_acks`, et **rien du tout** dans `join._evaluer` | `GatewayArbiter` |
| le terminal a-t-il le droit réglementaire d'émettre ? | espacement par le moteur pour les terminaux périodiques ; **jamais appliqué** aux Join-Request ni aux réémissions | `DutyCycleLedger` |

L'arbitre ne décide **ni** de la sensibilité (le moteur, `_decodable`), **ni** de l'écoute du
terminal (`ack_mac`, `join`), **ni** du verdict de compteur (`lsim.fcnt`). Il décide de
l'**occupation** : qui émet, quand, et combien de temps.

## Règles d'arbitrage retenues

1. **Un seul émetteur.** À tout instant, la passerelle n'émet qu'une descente. Toute descente —
   Join-Accept RX1, Join-Accept RX2, rejeu, ACK, downlink de données, réponse MAC — passe par
   `GatewayArbiter`.
2. **File monotone.** `début = max(instant_prêt, occupé_jusqu'à)` ; `occupé_jusqu'à` ne décroît
   jamais dans une passe. C'est le modèle « une file d'émission » : une descente retardée reste
   derrière celles qui la précèdent. C'est aussi, au bit près, la règle historique de
   `_schedule_gateway` et du planificateur du cœur C++, dont la parité est exigée par
   `tests/test_downlink_plan_parity.py`.
3. **Ordre chronologique, évalué en file d'événements.** Les demandes sont placées par
   `instant_prêt` croissant ; une demande née du placement d'une autre (RX2 après un RX1 manqué)
   entre dans la file à son propre instant, donc **avant** les demandes déjà déposées qui sont
   plus tardives. Deux demandes prêtes au même instant sont départagées par priorité
   décroissante, puis par rang de dépôt.
4. **Aucune priorité protocolaire inventée.** LoRaWAN ne définit pas d'ordre entre un Join-Accept
   et l'ACK d'un autre terminal. `ArbitrationPolicy.priority` est donc **vide par défaut** : à
   instant égal, l'ordre est celui du dépôt, et rien d'autre. Une politique explicite reste
   configurable, à charge pour l'appelant de la justifier.
5. **Une émission hors fenêtre n'a pas lieu**, sauf demande contraire. Quand
   `début >= fin de fenêtre`, le verdict est `window_missed` et **aucune occupation n'est
   enregistrée** : la passerelle n'a rien émis. La couche MAC demande `allow_late=True` pour
   l'ACK retardé, qui est une émission réelle que personne n'écoute — elle occupe l'émetteur.
6. **Le rapport cyclique montant est un budget, pas un espacement.** `DutyCycleLedger`
   applique `airtime_cumulé + airtime <= rapport × instant`, la règle déjà utilisée par
   `retransmissions` pour les réémissions. Une émission refusée n'est **pas** une émission :
   ni occupation, ni compteur `sent`, ni événement de transmission.
7. **Le rapport cyclique descendant est un espacement, pas un budget.** Depuis D3.14,
   `DownlinkDutyCycle` applique `début >= fin + airtime × (1 − d) / d` — la formule de la
   boucle fermée du moteur — par **passerelle et par sous-bande**. Les deux mécanismes ne
   sont pas fusionnés : l'un borne un total, l'autre espace deux émissions consécutives.
   Une émission refusée ne consomme rien non plus : l'état n'est réservé **qu'une seule
   fois**, au moment où l'émission est acceptée.

## Règle de départ et durée d'occupation

C'est la seule formule d'occupation du simulateur ; elle est appliquée par `GatewayArbiter._placer`,
à l'identique pour un Join-Accept RX1, un Join-Accept RX2, un rejeu, un ACK ou un downlink.

```
ouverture = fenêtre[0] si fenêtre else ready_ns            # la fenêtre ne peut pas être anticipée
début     = max(ready_ns, ouverture, occupé_jusqu'à)       # la passerelle n'émet qu'une descente
fermeture = fenêtre[1] si fenêtre else None

si fermeture est définie et début >= fermeture :
    allow_late  -> verdict LATE           (émise, occupée, mais plus écoutée — l'ACK retardé)
    sinon       -> verdict WINDOW_MISSED  (rien n'est émis, aucune occupation)
sinon :
    verdict EMITTED

fin = début + duration_ns
occupation = (début, fin)                                  # inscrite seulement si émise
occupé_jusqu'à = max(occupé_jusqu'à, fin)                  # monotone : ne décroît jamais
```

Deux conséquences, assumées et testées :

- **La durée d'occupation est le temps d'antenne seul**, sans garde ni temps de retournement. Une
  émission commence à `début` et libère l'émetteur à `début + duration_ns`, exactement.
- **Une émission peut dépasser sa fenêtre par la fin.** La condition porte sur le **début**
  (`début < fermeture`), pas sur la fin : une descente commencée dans la fenêtre est émise en
  entier, même si `fin > fermeture`, et elle occupe l'émetteur au-delà. Le terminal, lui, cesse
  d'écouter à la fermeture — c'est la couche MAC (`ack_mac`, `join`) qui le décide, pas l'arbitre.
  Ces deux grandeurs ne sont donc pas redondantes : l'arbitre mesure l'occupation, la couche MAC
  mesure l'écoute.

Le verdict `NOT_NEEDED`, lui, n'entre pas dans cette formule : il est décidé **avant** le calcul du
départ, quand `EmissionRequest.condition` est devenue fausse au moment du placement (un terminal
déjà joint ne reçoit pas de second Join-Accept). Aucune occupation, aucune réaction.

## Hypothèses explicites

- **Fenêtre RX1 d'une seconde** (`RX1_WINDOW_NS`) : hypothèse du simulateur, déjà celle du cœur
  C++ et du point fixe Python. LoRaWAN fixe le délai d'ouverture, pas la durée d'écoute.
- **Demi-duplex de la passerelle** : une trame montante qui chevauche une émission descendante
  est perdue (`LOST_GATEWAY_BUSY`). C'est le moteur qui l'applique, sur l'occupation produite par
  l'arbitre — c'est la boucle de point fixe de `_build_trace_python` et de `_simulate_confirmed`.
- **Un seul émetteur par passerelle** : ni cartes radio multiples, ni descentes simultanées sur
  plusieurs canaux.

## Limite à ne pas masquer

L'arbitre est **Python**. Le planificateur du cœur C++ (`DownlinkScheduler`, `lsim_plan_downlinks_v1`)
reste utilisé quand ni jointure radio ni couche MAC n'est active ; il applique la même règle de
file monotone et la parité est vérifiée test par test. Dès qu'une jointure radio est déclarée, les
descentes passent par cet arbitre : c'est le seul moyen de faire partager une ressource unique
sans modifier l'ABI du cœur.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence

from lsim.power import GATEWAY_TX_POWER_DEFAULT_DBM, TxChain

# Verdicts de l'arbitre. Un seul moyen de les distinguer : l'occupation.
EMITTED = "emitted"              # émise dans la fenêtre : l'émetteur est occupé
LATE = "late"                    # émise hors fenêtre (demandé) : occupée, mais non écoutée
WINDOW_MISSED = "window_missed"  # émetteur occupé au-delà de la fenêtre : **aucune** émission
NOT_NEEDED = "not_needed"        # devenue sans objet avant d'être émise : **aucune** émission
DUTY_CYCLE = "duty_cycle"        # refusée par le rapport cyclique : **aucune** émission

VERDICTS = (EMITTED, LATE, WINDOW_MISSED, NOT_NEEDED, DUTY_CYCLE)

#: Réaction au placement d'une demande : `(émission, déposer) -> None`. `déposer` renvoie le
#: ticket de la nouvelle demande, ce qui permet à l'appelant de la retrouver après résolution.
Reaktion = Callable[["Emission", Callable[["EmissionRequest"], int]], None]


@dataclass(frozen=True)
class ArbitrationPolicy:
    """Règles de sélection entre demandes concurrentes.

    `priority` : étiquette → priorité (la plus grande gagne). **Vide par défaut** : LoRaWAN ne
    définit pas d'ordre universel entre un Join-Accept et l'ACK d'un autre terminal, et le
    simulateur n'en invente pas. Une politique non vide doit être justifiée par l'appelant.
    """

    priority: dict = field(default_factory=dict)

    def priority_of(self, label: str, demande: Optional[int] = None) -> int:
        if demande is not None:
            return demande
        return int(self.priority.get(label, 0))


@dataclass(frozen=True)
class EmissionRequest:
    """Une demande d'émission sur l'émetteur de la passerelle.

    `label` : nature de la descente (`join_accept`, `ack`, `downlink`, `mac_answer`...).
    `ready_ns` : premier instant où l'émission est possible (ouverture de fenêtre, ou instant
    demandé par la couche MAC). `duration_ns` : temps d'antenne.
    `window` : `(ouverture, fermeture)` ; `None` = aucune contrainte de fenêtre (classe C, ou
    émission dont le retard est assumé par l'appelant — c'est le cas de l'ACK tardif).
    `allow_late` : émettre même si le placement tombe après la fenêtre. Sans cela, une demande
    hors fenêtre n'est **pas** émise (`window_missed`).
    `priority` : priorité explicite ; `None` = celle de la politique pour cette étiquette.
    `condition` : évaluée **au moment du placement**. Fausse ⇒ la demande est devenue sans objet
    (un terminal déjà joint ne reçoit pas de second Join-Accept) : verdict `not_needed`, aucune
    occupation, et aucune réaction (`ensuite` n'est pas appelée).
    `freq_hz` : fréquence de l'émission. Elle seule détermine la sous-bande réglementaire, donc
    la contrainte de rapport cyclique descendant (`DownlinkDutyCycle`). `None` : la demande
    n'est pas rattachée à une fréquence, aucune contrainte n'est appliquée.
    `gateway` : indice de la passerelle émettrice. L'état de rapport cyclique est **par
    passerelle** : deux passerelles ne partagent pas le droit d'émettre d'une sous-bande.
    """

    label: str
    device: int
    ready_ns: int
    duration_ns: int
    window: Optional[tuple[int, int]] = None
    allow_late: bool = False
    priority: Optional[int] = None
    condition: Optional[Callable[[], bool]] = None
    freq_hz: Optional[int] = None
    gateway: int = 0

    def __post_init__(self) -> None:
        if self.duration_ns <= 0:
            raise ValueError("une émission a un temps d'antenne strictement positif")
        if self.window is not None:
            ouverture, fermeture = self.window
            if fermeture <= ouverture:
                raise ValueError("la fenêtre d'émission est d'une durée strictement positive")


@dataclass(frozen=True)
class Emission:
    """La décision de l'arbitre pour une demande.

    `emitted` est la seule chose à retenir pour l'occupation. `start_ns` / `end_ns` valent
    l'instant qui aurait été retenu même sans émission : une fenêtre manquée reste datée, pour
    la trace (`rx_window_missed`).
    """

    ticket: int
    label: str
    device: int
    ready_ns: int
    duration_ns: int
    window: Optional[tuple[int, int]]
    start_ns: int
    end_ns: int
    verdict: str

    @property
    def emitted(self) -> bool:
        """L'émetteur a-t-il réellement occupé la ressource ?"""
        return self.verdict in (EMITTED, LATE)

    @property
    def in_window(self) -> bool:
        """Émise **pendant** la fenêtre du terminal (un ACK tardif ne l'est pas)."""
        return self.verdict == EMITTED

    @property
    def window_missed(self) -> bool:
        return self.verdict == WINDOW_MISSED


class GatewayArbiter:
    """L'unique émetteur de la passerelle : occupation, placement, verdicts.

    Deux temps : on **dépose** les demandes (`demand`), puis on **résout** (`resolve`). Le dépôt
    séparé est ce qui permet à plusieurs producteurs — ACK, Join-Accept, downlinks — de concourir
    pour la même ressource dans l'ordre chronologique, sans qu'aucun ne soit servi avant l'autre.

    La résolution est une **file d'événements** : une demande peut en engendrer une autre (RX2
    après un RX1 manqué, rejeu après une acceptation). La demande née entre dans la file à son
    propre instant, donc avant les demandes déjà déposées qui sont plus tardives : l'ordre reste
    chronologique du début à la fin, sans vague artificielle.

    Un arbitre est **à usage unique** : une fois la passe résolue, on n'y ajoute plus rien de
    nouveau venu de l'extérieur. Chaque itération du point fixe en crée un nouveau, ce qui
    garantit qu'aucune occupation d'une passe précédente ne survit indûment à la suivante.
    """

    def __init__(self, policy: ArbitrationPolicy = ArbitrationPolicy(),
                 occupation: Sequence[tuple[int, int]] = (),
                 duty_cycle: Optional["DownlinkDutyCycle"] = None):
        self.policy = policy
        self.duty_cycle = duty_cycle
        self._requetes: dict[int, EmissionRequest] = {}
        self._ensuite: dict[int, Reaktion] = {}
        self._emissions: dict[int, Emission] = {}
        self._ordre: list[int] = []
        self._occupation: list[tuple[int, int]] = list(occupation)
        self._occupe_jusqua = max((fin for _debut, fin in occupation), default=0)
        self._ticket = 0
        self._file: list[tuple[int, int, int]] = []
        self._resolu = False

    # --- dépôt ---------------------------------------------------------------------------

    def demand(self, request: EmissionRequest, ensuite: Optional[Reaktion] = None) -> int:
        """Dépose une demande ; renvoie son ticket.

        `ensuite` est appelée juste après le placement, avec l'`Emission` décidée et une fonction
        `déposer` : c'est le mécanisme par lequel une fenêtre de secours (RX2) ou un rejeu naît
        du résultat de l'émission précédente.
        """
        ticket = self._ticket
        self._ticket += 1
        self._requetes[ticket] = request
        if ensuite is not None:
            self._ensuite[ticket] = ensuite
        # `heappush` et non `append` : la file est un tas, y compris pendant la résolution — une
        # demande née du placement d'une autre doit pouvoir être placée avant les demandes déjà
        # déposées qui sont plus tardives.
        heapq.heappush(self._file, (request.ready_ns,
                                    -self.policy.priority_of(request.label, request.priority),
                                    ticket))
        return ticket

    def demand_all(self, requests: Sequence[EmissionRequest],
                   ensuite: Optional[Reaktion] = None) -> list[int]:
        return [self.demand(demande, ensuite) for demande in requests]

    # --- résolution ----------------------------------------------------------------------

    def resolve(self) -> tuple[Emission, ...]:
        """Place toutes les demandes en attente, dans l'ordre chronologique.

        La méthode est idempotente et rappelable : une demande née pendant la résolution est
        placée dans le même appel, à son propre instant.
        """
        heapq.heapify(self._file)
        suivi: set[int] = set()
        while self._file:
            _pret, _prio, ticket = heapq.heappop(self._file)
            if ticket in suivi:
                continue
            suivi.add(ticket)
            emission = self._placer(ticket, self._requetes[ticket])
            self._emissions[ticket] = emission
            self._ordre.append(ticket)
            reaction = self._ensuite.get(ticket)
            # Une fenêtre manquée déclenche quand même sa réaction : c'est ainsi que RX2 naît
            # d'une RX1 que l'émetteur n'a pas pu placer. Seule une demande devenue sans objet
            # (`not_needed`) n'engendre ni secours ni rejeu.
            if reaction is not None and emission.verdict is not NOT_NEEDED:
                reaction(emission, self.demand)
        self._resolu = True
        return tuple(self._emissions[t] for t in self._ordre)

    def _placer(self, ticket: int, demande: EmissionRequest) -> Emission:
        if demande.condition is not None and not demande.condition():
            return Emission(ticket, demande.label, demande.device, demande.ready_ns,
                            demande.duration_ns, demande.window, demande.ready_ns,
                            demande.ready_ns, NOT_NEEDED)
        ouverture = demande.window[0] if demande.window is not None else demande.ready_ns
        debut = max(demande.ready_ns, ouverture, self._occupe_jusqua)
        fermeture = demande.window[1] if demande.window is not None else None
        # Rapport cyclique descendant. La contrainte porte sur le **début**, comme
        # l'occupation de l'émetteur : la sous-bande impose une attente, on ne l'anticipe pas.
        # Ce n'est pas un report : si l'attente sort l'émission de sa fenêtre, le verdict est
        # DUTY_CYCLE et **rien n'est émis** — ni occupation, ni consommation de la sous-bande.
        attente = False
        if self.duty_cycle is not None:
            cle, _limite = self.duty_cycle.regle(demande.freq_hz)
            if cle == HORS_PLAN:
                # Fréquence hors des bandes désignées : ce n'est pas une question de quota.
                self.duty_cycle.refuse(hors_plan=True)
                return Emission(ticket, demande.label, demande.device, demande.ready_ns,
                                demande.duration_ns, demande.window, debut, debut, DUTY_CYCLE)
            libre = self.duty_cycle.libre_le(demande.gateway, demande.freq_hz, debut)
            if libre > debut:
                attente = True
                debut = libre
        if fermeture is not None and debut >= fermeture:
            if not demande.allow_late:
                # La passerelle n'a rien émis : aucune occupation, aucun temps d'antenne.
                if attente:
                    # C'est l'attente réglementaire, et non l'occupation de l'émetteur, qui a
                    # fait manquer la fenêtre : le verdict le dit.
                    self.duty_cycle.refuse()
                    return Emission(ticket, demande.label, demande.device, demande.ready_ns,
                                    demande.duration_ns, demande.window, debut, debut,
                                    DUTY_CYCLE)
                return Emission(ticket, demande.label, demande.device, demande.ready_ns,
                                demande.duration_ns, demande.window, debut, debut,
                                WINDOW_MISSED)
            verdict = LATE
        else:
            verdict = EMITTED
        fin = debut + demande.duration_ns
        self._occupation.append((debut, fin))
        self._occupe_jusqua = max(self._occupe_jusqua, fin)
        if self.duty_cycle is not None:
            # Réservation **unique**, au moment où l'émission est acceptée. Une demande
            # refusée n'atteint jamais cette ligne : elle ne consomme donc rien.
            self.duty_cycle.consommer(demande.gateway, demande.freq_hz, debut, fin)
        return Emission(ticket, demande.label, demande.device, demande.ready_ns,
                        demande.duration_ns, demande.window, debut, fin, verdict)

    # --- lecture -------------------------------------------------------------------------

    def emission(self, ticket: int) -> Emission:
        """Décision d'un ticket. Lève `RuntimeError` si la passe n'est pas résolue."""
        if not self._resolu:
            raise RuntimeError("arbitre non résolu : appeler `resolve()` avant de lire")
        return self._emissions[ticket]

    def emissions(self, tickets: Sequence[int]) -> tuple[Emission, ...]:
        return tuple(self.emission(ticket) for ticket in tickets)

    @property
    def resolved(self) -> bool:
        return self._resolu

    @property
    def occupation(self) -> tuple[tuple[int, int], ...]:
        """Intervalles d'occupation **des émissions réellement faites**, dans l'ordre de placement.

        Une demande `window_missed` ou `not_needed` n'y figure pas : elle n'a rien émis.
        """
        return tuple(self._occupation)

    @property
    def emissions_faites(self) -> tuple[Emission, ...]:
        """Les émissions qui ont réellement occupé l'émetteur, dans l'ordre chronologique."""
        return tuple(e for e in (self._emissions[t] for t in self._ordre) if e.emitted)

    def occupation_par_etiquette(self, label: str) -> tuple[tuple[int, int], ...]:
        return tuple((e.start_ns, e.end_ns) for e in self.emissions_faites if e.label == label)


#: Clé d'état d'une émission dont la fréquence n'entre dans aucune sous-bande du plan.
#: Une telle émission est **refusée** : émettre hors des bandes désignées n'est pas une
#: question de quota.
HORS_PLAN = "hors_plan"


@dataclass(frozen=True)
class _Derniere:
    """Dernière émission d'une sous-bande : sa fin et son temps d'antenne."""

    fin_ns: int
    airtime_ns: int


class DownlinkDutyCycle:
    """Espacement réglementaire **descendant**, par passerelle et par sous-bande.

    Deux mécanismes de rapport cyclique coexistent, volontairement **non fusionnés** parce
    qu'ils ne mesurent pas la même chose :

    | | `DutyCycleLedger` (montant) | `DownlinkDutyCycle` (descendant) |
    |---|---|---|
    | nature | **budget cumulatif** | **espacement** entre deux émissions |
    | portée | un terminal | une passerelle **et** une sous-bande |
    | règle | `cumul + airtime <= rapport × instant` | `début >= fin + airtime × (1 − d) / d` |
    | origine | cumul depuis `t = 0`, droit qui croît avec le temps | dernière émission de la sous-bande |
    | source | règle des réémissions (`retransmissions`) | boucle fermée du moteur, `core/src/engine.cpp` l. 2019-2031 |

    Le premier borne un **total**, le second espace deux **émissions consécutives**. Les
    fusionner reviendrait à choisir arbitrairement l'une des deux sémantiques ; ils sont donc
    distincts, et chacun est documenté à sa place.

    **Règle retenue (A1).** Le repos suit l'émission **réellement émise** :

        repos = airtime × (1 − d) / d

    où `d` est la limite de la sous-bande et `airtime` le temps d'antenne de l'émission qui
    vient d'avoir lieu. C'est exactement la formule de la boucle fermée du moteur, appliquée
    cette fois à l'émetteur de la passerelle. Une limite de 1 % impose donc un repos de 99 fois
    le temps d'antenne ; une limite de 10 %, 9 fois.

    **État (A3).** L'état est indexé par `(passerelle, sous-bande)` : RX1, RX2, un ACK, un
    Join-Accept et ses rejeux partagent le même état dès qu'ils tombent dans la même
    sous-bande. Une émission **refusée ne consomme rien** : ni occupation, ni repos — la
    passerelle n'a rien émis. Le contrôle a lieu **une seule fois**, au moment où l'émission
    est acceptée (`GatewayArbiter._placer`).

    **Portée.** `profile = None` (région inconnue ou non déclarée), `enabled = False` ou
    `freq_hz = None` : **aucune contrainte**, l'objet ne refuse jamais rien. Un profil sans
    sous-bandes (US915, AU915) ne contraint rien non plus.
    """

    def __init__(self, profile=None, tx: Optional[TxChain] = None, enabled: bool = True):
        self._profile = profile
        self._tx = tx if tx is not None else TxChain(GATEWAY_TX_POWER_DEFAULT_DBM)
        self._enabled = bool(enabled)
        self._etat: dict[tuple[int, str], _Derniere] = {}
        self._regles: dict[int, tuple[Optional[str], Optional[float]]] = {}
        self._consommations = 0
        self._refus = 0
        self._refus_hors_plan = 0

    # --- règle ---------------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return self._enabled and self._profile is not None

    @property
    def eirp_dbm(self) -> float:
        """PIRE de la passerelle : c'est elle qui départage les sous-bandes (O contre P)."""
        return self._tx.eirp_dbm

    def regle(self, freq_hz: Optional[int]) -> tuple[Optional[str], Optional[float]]:
        """`(clé d'état, limite)` pour une fréquence.

        - `(None, None)` : aucune contrainte ;
        - `(HORS_PLAN, None)` : fréquence hors du plan, émission refusée ;
        - `(nom de sous-bande, limite)` : contrainte d'espacement.

        `freq_hz = 0` vaut « fréquence non renseignée » (convention de `DeviceRadio.rx2_hz`,
        qui vaut 0 tant qu'aucun plan régional ne définit RX2) et ne contraint rien.
        """
        if not freq_hz or not self.enabled:
            return None, None
        cle = int(freq_hz)
        if cle not in self._regles:
            self._regles[cle] = self._resoudre(cle)
        return self._regles[cle]

    def _resoudre(self, freq_hz: int) -> tuple[Optional[str], Optional[float]]:
        if not getattr(self._profile, "sub_bands", ()):
            return None, None                      # région sans sous-bandes : rien à appliquer
        bandes = self._profile.applicable(freq_hz, self._tx.erp_dbm)
        if not bandes:
            return HORS_PLAN, None                 # hors des bandes désignées
        bande = min(bandes, key=lambda b: b.duty_cycle)
        return bande.name, bande.duty_cycle

    # --- espacement ----------------------------------------------------------------------

    @staticmethod
    def repos_ns(airtime_ns: int, limite: float) -> int:
        """Repos imposé après une émission de `airtime_ns` dans une sous-bande à `limite`."""
        if limite >= 1.0:
            return 0
        if limite <= 0.0:
            raise ValueError("la limite de rapport cyclique est dans ]0, 1]")
        return int(round(airtime_ns * (1.0 - limite) / limite))

    def libre_le(self, gateway: int, freq_hz: Optional[int], debut: int) -> int:
        """Premier instant d'émission autorisé, à partir de `debut`."""
        cle, limite = self.regle(freq_hz)
        if cle is None or limite is None:
            return debut
        derniere = self._etat.get((int(gateway), cle))
        if derniere is None:
            return debut
        return max(debut, derniere.fin_ns + self.repos_ns(derniere.airtime_ns, limite))

    def consommer(self, gateway: int, freq_hz: Optional[int], debut: int, fin: int) -> None:
        """Enregistre une émission **acceptée**. Une émission refusée n'appelle jamais ceci."""
        cle, _limite = self.regle(freq_hz)
        if cle is None or cle == HORS_PLAN:
            return
        self._etat[(int(gateway), cle)] = _Derniere(int(fin), int(fin) - int(debut))
        self._consommations += 1

    def refuse(self, hors_plan: bool = False) -> None:
        if hors_plan:
            self._refus_hors_plan += 1
        else:
            self._refus += 1

    # --- lecture -------------------------------------------------------------------------

    def consommations(self) -> int:
        """Nombre d'émissions descendantes comptabilisées, toutes sous-bandes confondues."""
        return self._consommations

    def refus(self) -> int:
        """Émissions refusées par l'espacement (hors plan exclu)."""
        return self._refus

    def refus_hors_plan(self) -> int:
        """Émissions refusées parce que leur fréquence n'entre dans aucune sous-bande."""
        return self._refus_hors_plan

    def etat(self) -> dict[tuple[int, str], tuple[int, int]]:
        """Copie de l'état : `(passerelle, sous-bande) -> (fin, temps d'antenne)`."""
        return {cle: (d.fin_ns, d.airtime_ns) for cle, d in self._etat.items()}

    def nouvelle_passe(self) -> "DownlinkDutyCycle":
        """Même règle, état vierge.

        Le point fixe de `retransmissions` **rejoue la même chronologie** à chaque passe : y
        laisser survivre l'état de la passe précédente compterait deux fois les mêmes
        émissions et refuserait, à la passe suivante, ce que la précédente avait autorisé.
        """
        return DownlinkDutyCycle(self._profile, self._tx, self._enabled)


class DutyCycleLedger:
    """Budget réglementaire d'émission, par terminal.

    Règle appliquée — la même que `retransmissions` pour les réémissions, reprise à l'identique :
    `airtime_cumulé + airtime <= rapport_cyclique × instant`.

    **Grandeurs et unités.** `rapport` : sans dimension, dans `]0, 1]` (1 % = 0,01). `airtime`
    et `instant` : **nanosecondes entières**, comptées depuis l'origine de la simulation
    (`t = 0`), jamais des secondes ni des millisecondes. Le produit `rapport × instant` est donc
    un temps d'antenne autorisé, exprimé en nanosecondes.

    **Fenêtre temporelle.** Le budget est **cumulatif depuis l'origine**, il ne s'agit **pas**
    d'une fenêtre glissante : `airtime_cumulé` est la somme de toutes les émissions du terminal
    depuis `t = 0`, mise en regard d'un droit qui croît linéairement avec le temps
    (`rapport × instant`). Un terminal qui émet tôt épuise son budget et le reconstitue en
    attendant ; c'est le comportement déjà vérifié pour les réémissions.

    **Portée.** Le budget est **global au terminal** : il comptabilise ses émissions réelles
    (données, réémissions, Join-Request), parce que la contrainte réglementaire porte sur
    l'occupation de la sous-bande et non sur la nature de la trame. Il est **isolé par terminal** :
    le budget de l'un ne limite pas l'autre.

    **Portée.** Ce budget est **montant** : il ne s'applique qu'aux émissions du terminal. Le
    rapport cyclique **descendant** de la passerelle n'est **pas** modélisé ici : il l'est depuis
    D3.14 par `DownlinkDutyCycle`, qui est un espacement et non un budget. Les deux grandeurs ne
    se cumulent pas : un terminal qui émet et une passerelle qui répond n'épuisent pas le même
    droit, et les deux mécanismes restent séparés à dessein.

    `rapport = 1.0` (défaut) : aucune contrainte, le ledger ne refuse jamais rien.
    """

    def __init__(self, rapports: Optional[dict[int, float]] = None):
        self._rapports: dict[int, float] = {}
        self._emissions: dict[int, list[tuple[int, int]]] = {}
        self._refusees: dict[int, int] = {}
        for terminal, rapport in (rapports or {}).items():
            self.register(terminal, rapport)

    def register(self, device: int, duty_cycle: float) -> None:
        if not 0.0 < duty_cycle <= 1.0:
            raise ValueError("le rapport cyclique est dans ]0, 1]")
        self._rapports[int(device)] = float(duty_cycle)

    def rapport(self, device: int) -> float:
        return self._rapports.get(int(device), 1.0)

    def record(self, device: int, start_ns: int, end_ns: int) -> None:
        """Enregistre une émission **réellement faite**."""
        device = int(device)
        if end_ns < start_ns:
            raise ValueError("intervalle d'émission invalide")
        self._emissions.setdefault(device, []).append((int(start_ns), int(end_ns)))

    def consumed_ns(self, device: int, until_ns: Optional[int] = None) -> int:
        """Temps d'antenne déjà consommé (totalement, ou jusqu'à un instant)."""
        bornes = self._emissions.get(int(device), ())
        if until_ns is None:
            return sum(fin - debut for debut, fin in bornes)
        return sum(min(fin, until_ns) - debut
                   for debut, fin in bornes if min(fin, until_ns) > debut)

    def allows(self, device: int, at_ns: int, duration_ns: int) -> bool:
        """Le terminal peut-il émettre `duration_ns` à partir de `at_ns` ?

        `cumul + duration_ns <= rapport × at_ns`, toutes grandeurs en nanosecondes, le cumul étant
        pris depuis l'origine de la simulation (budget cumulatif, non glissant).
        """
        rapport = self.rapport(device)
        if rapport >= 1.0:
            return True
        return self.consumed_ns(device) + duration_ns <= rapport * at_ns

    def refuse(self, device: int) -> None:
        self._refusees[int(device)] = self._refusees.get(int(device), 0) + 1

    def refusees(self, device: Optional[int] = None) -> int:
        if device is not None:
            return self._refusees.get(int(device), 0)
        return sum(self._refusees.values())

    def emissions(self, device: int) -> tuple[tuple[int, int], ...]:
        return tuple(self._emissions.get(int(device), ()))
