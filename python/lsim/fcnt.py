"""Compteurs de trame LoRaWAN : séries 32 bits, champ 16 bits, fenêtre de rejeu.

Trois mécanismes, rassemblés ici pour être testés une fois — avec leur statut normatif, qui n'est
pas le même pour les trois :

1. **16 bits sur l'air, 32 bits en session.** Le champ `FCnt` d'une trame est un entier de
   16 bits ; le récepteur le replace dans sa série 32 bits en prenant le plus petit candidat
   strictement supérieur au dernier compteur accepté. Un champ identique au dernier accepté est
   un **doublon**. Cette reconstruction est celle des spécifications 1.0.x ; en 1.0.4 les
   compteurs sont 32 bits, mais le champ de trame reste 16 bits et la règle de rejeu demeure.
2. **`MAX_FCNT_GAP = 16 384` — borne historique, pas une exigence actuelle.** La valeur est celle
   de MAX_FCNT_GAP des spécifications ≤ 1.0.3 ; les Paramètres régionaux (RP002) la déclarent
   « deprecated and removed from LoRaWAN 1.0.4 and subsequent versions ». Le simulateur l'applique
   comme **politique de rejeu explicite** (hypothèse de réseau, pas conformité), parce qu'il rejoue
   des trames à champ 16 bits : c'est `fcnt.MAX_FCNT_GAP`, une constante, et non un réglage caché.
   Une trame à plus de 16 384 du dernier accepté est rejetée (`GAP`).
3. **Deux séries descendantes en LoRaWAN 1.1.** `NFCntDown` numérote les trames sans charge utile
   applicative (commandes MAC, ACK seul), `AFCntDown` celles qui en portent une. Le contrôle de
   rejeu est **indépendant** par série. En 1.0.x, une seule série existe : la couche MAC du projet
   n'utilise que `NFCntDown`, puisque ses ACK ne portent pas de charge utile.

Ce module ne simule ni le chiffrement, ni la reconstruction depuis un journal de paquets : il
fournit les primitives, et `lsim.ack_mac` les applique au plan des ACK. Le cœur C++ garde sa
propre logique (`core/src/session.cpp`) ; ce module n'y touche pas.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

#: Écart maximal entre le compteur reçu et le dernier accepté (MAX_FCNT_GAP historique,
#: retiré de LoRaWAN 1.0.4 et suivants ; appliqué ici comme politique de rejeu explicite).
MAX_FCNT_GAP = 16_384

MODULUS_16 = 1 << 16
MODULUS_32 = 1 << 32

#: Nom des deux séries descendantes de LoRaWAN 1.1.
NF = "NF"   # NFCntDown : trame sans charge utile applicative
AF = "AF"   # AFCntDown : trame avec charge utile applicative


class CounterVerdict(str, Enum):
    """Verdict d'un contrôle de compteur."""

    OK = "ok"                 # compteur authentique, série avancée
    REPLAY = "replay"         # compteur déjà consommé : rejeu ou doublon
    GAP = "gap"               # plus de MAX_FCNT_GAP d'avance : désynchronisation
    EXHAUSTED = "exhausted"   # série épuisée à 2^32 : nouvelle jointure nécessaire


@dataclass(frozen=True)
class CounterCheck:
    """Résultat d'un contrôle : le verdict, la valeur 32 bits retenue, le champ 16 bits lu."""

    verdict: CounterVerdict
    counter32: int
    on_air: int

    @property
    def accepted(self) -> bool:
        return self.verdict is CounterVerdict.OK


@dataclass(frozen=True)
class CounterSeries:
    """Une série de compteurs 32 bits, monotone, jamais réutilisée.

    `start` est la valeur de la première trame de la session (après jointure, les compteurs
    repartent de zéro ; un scénario peut fixer un départ non nul pour représenter une session
    déjà en cours). `last` est le dernier compteur **accepté**, `None` avant le premier.
    """

    start: int = 0
    last: Optional[int] = None

    def __post_init__(self) -> None:
        if isinstance(self.start, bool) or not isinstance(self.start, int):
            raise ValueError("start doit être un entier")
        if not 0 <= self.start < MODULUS_32:
            raise ValueError("start doit être dans [0, 2^32)")
        if self.last is not None:
            if isinstance(self.last, bool) or not isinstance(self.last, int):
                raise ValueError("last doit être un entier")
            if not 0 <= self.last < MODULUS_32:
                raise ValueError("last doit être dans [0, 2^32)")
            if self.last < self.start:
                raise ValueError("last ne peut pas précéder le départ de la série")

    @property
    def next_value(self) -> Optional[int]:
        """Valeur que le réseau attribuera à la prochaine trame, `None` si la série est épuisée."""
        if self.last is None:
            return self.start
        suivant = self.last + 1
        return suivant if suivant < MODULUS_32 else None

    @property
    def exhausted(self) -> bool:
        return self.last is not None and self.next_value is None

    def accepts(self, counter32: int) -> CounterCheck:
        """Contrôle d'une valeur 32 bits connue (pas de reconstruction)."""
        if isinstance(counter32, bool) or not isinstance(counter32, int):
            raise ValueError("counter32 doit être un entier")
        on_air = counter32 % MODULUS_16 if 0 <= counter32 < MODULUS_32 else -1
        if not 0 <= counter32 < MODULUS_32:
            return CounterCheck(CounterVerdict.EXHAUSTED, counter32, on_air)
        if counter32 < self.start:
            return CounterCheck(CounterVerdict.REPLAY, counter32, on_air)
        if self.last is None:
            return CounterCheck(CounterVerdict.OK, counter32, on_air)
        if counter32 <= self.last:
            return CounterCheck(CounterVerdict.REPLAY, counter32, on_air)
        if counter32 - self.last > MAX_FCNT_GAP:
            return CounterCheck(CounterVerdict.GAP, counter32, on_air)
        return CounterCheck(CounterVerdict.OK, counter32, on_air)

    def accept(self, counter32: int) -> "CounterSeries":
        """Série avancée si la valeur est acceptée ; inchangée sinon."""
        controle = self.accepts(counter32)
        if not controle.accepted:
            return self
        return CounterSeries(start=self.start, last=counter32)

    def reconstruct(self, on_air: int) -> CounterCheck:
        """Replace un champ `FCnt` de 16 bits dans la série 32 bits, puis le contrôle.

        - champ identique au dernier accepté → `REPLAY` (doublon) ;
        - sinon, plus petit candidat strictement supérieur à `last` (ou au départ de la série) ;
        - candidat au-delà de 2^32 → `EXHAUSTED` ; écart > `MAX_FCNT_GAP` → `GAP`.
        """
        if isinstance(on_air, bool) or not isinstance(on_air, int):
            raise ValueError("on_air doit être un entier")
        if not 0 <= on_air < MODULUS_16:
            raise ValueError(f"on_air doit être dans [0, {MODULUS_16})")

        if self.last is None:
            candidat = on_air
            if candidat < self.start:
                # Départ de série au-delà du premier tour de 16 bits : on remonte par pas de
                # 65 536 jusqu'au premier candidat ≥ start.
                candidat += ((self.start - candidat + MODULUS_16 - 1) // MODULUS_16) * MODULUS_16
        else:
            if on_air == self.last % MODULUS_16:
                return CounterCheck(CounterVerdict.REPLAY, self.last, on_air)
            candidat = self.last - (self.last % MODULUS_16) + on_air
            if candidat <= self.last:
                candidat += MODULUS_16

        if candidat >= MODULUS_32:
            return CounterCheck(CounterVerdict.EXHAUSTED, candidat, on_air)
        controle = self.accepts(candidat)
        return CounterCheck(controle.verdict, candidat, on_air)


@dataclass(frozen=True)
class DownlinkCounters:
    """Les deux séries descendantes d'un terminal (LoRaWAN 1.1), indépendantes.

    `NF` : trames sans charge utile applicative (commandes MAC, ACK seul).
    `AF` : trames avec charge utile applicative.
    Les deux séries partent du même `start` — celui de la session — mais avancent séparément :
    un ACK consommé en `NF` ne décale pas la première descente applicative.
    """

    nf: CounterSeries = CounterSeries()
    af: CounterSeries = CounterSeries()

    def __post_init__(self) -> None:
        if self.nf.start != self.af.start:
            raise ValueError("les deux séries doivent partir du même compteur de session")

    @classmethod
    def starting_at(cls, start: int = 0) -> "DownlinkCounters":
        return cls(CounterSeries(start=start), CounterSeries(start=start))

    def series(self, uses_nf: bool) -> CounterSeries:
        return self.nf if uses_nf else self.af

    def name(self, uses_nf: bool) -> str:
        return NF if uses_nf else AF

    def next_value(self, uses_nf: bool) -> Optional[int]:
        return self.series(uses_nf).next_value

    def accept(self, uses_nf: bool, on_air: int) -> tuple[CounterCheck, "DownlinkCounters"]:
        """Reconstruit et contrôle un champ 16 bits reçu sur la série concernée."""
        controle = self.series(uses_nf).reconstruct(on_air)
        if not controle.accepted:
            return controle, self
        avancee = CounterSeries(start=self.nf.start, last=controle.counter32)
        if uses_nf:
            return controle, DownlinkCounters(avancee, self.af)
        return controle, DownlinkCounters(self.nf, avancee)


def on_air(counter32: int) -> int:
    """Champ `FCnt` de 16 bits d'un compteur 32 bits."""
    if not 0 <= counter32 < MODULUS_32:
        raise ValueError("counter32 doit être dans [0, 2^32)")
    return counter32 % MODULUS_16
