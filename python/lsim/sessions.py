"""Cycle de vie des sessions LoRaWAN : jointures, renouvellement, rejet des trames périmées.

Une **session** commence à un `Join-Accept` accepté et se termine au suivant. Trois règles y sont
attachées, et ce module les tient séparément :

1. **Une jointure acceptée avance la session.** Les compteurs (`FCntUp`, `NFCntDown`, `AFCntDown`)
   repartent de zéro, l'identité du terminal ne change pas (`fcnt.DeviceCounters.renew_session`).
2. **Une jointure rejouée ne l'avance pas.** Un `Join-Accept` dont le `JoinNonce` n'est pas
   strictement supérieur au dernier accepté, ou dont l'instant n'est pas strictement postérieur,
   est refusé. Ses compteurs ne sont pas remis à zéro : rien n'a été accepté.
3. **Une trame d'une session périmée n'est plus reçue.** Un uplink émis avec les clés de la
   session *n* alors que la session *n+1* est ouverte ne peut pas être déchiffré par le réseau :
   il est rejeté, sans ACK.

Ce module ne fait ni cryptographie ni échange de clés : il ordonne les sessions et dit ce qui est
accepté. Il est piloté par `lsim.retransmissions` (champ `session_joins_s` du scénario).
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from typing import Optional, Sequence


class JoinRejected(ValueError):
    """`Join-Accept` refusé : rejeu, nonce non croissant ou instant déjà utilisé."""


@dataclass(frozen=True)
class JoinAccept:
    """Un `Join-Accept` proposé : instant, numéro de session visé, `JoinNonce`."""

    at_ns: int
    nonce: int

    def __post_init__(self) -> None:
        if isinstance(self.at_ns, bool) or not isinstance(self.at_ns, int) or self.at_ns < 0:
            raise ValueError("at_ns doit être un entier positif ou nul")
        if isinstance(self.nonce, bool) or not isinstance(self.nonce, int) or self.nonce < 0:
            raise ValueError("nonce doit être un entier positif ou nul")


@dataclass(frozen=True)
class AcceptedSession:
    """Une session acceptée : son rang, son instant d'ouverture, le nonce qui l'a ouverte."""

    index: int
    opened_ns: int
    nonce: int


@dataclass(frozen=True)
class SessionTimeline:
    """Sessions acceptées, dans l'ordre. La première s'ouvre à `joins[0].at_ns`."""

    sessions: tuple[AcceptedSession, ...] = ()

    @classmethod
    def from_join_times(cls, joins_s: Sequence[int] = ()) -> "SessionTimeline":
        """Construit la timeline à partir d'instants en secondes, nonces déduits de l'ordre."""
        timeline = cls()
        for rang, instant_s in enumerate(joins_s):
            if isinstance(instant_s, bool) or not isinstance(instant_s, int) or instant_s < 0:
                raise ValueError("session_joins_s doit contenir des entiers positifs")
            timeline = timeline.accept(JoinAccept(at_ns=instant_s * 1_000_000_000,
                                                  nonce=rang))
        return timeline

    # --- lecture ---------------------------------------------------------------------------

    @property
    def count(self) -> int:
        return len(self.sessions)

    @property
    def last(self) -> Optional[AcceptedSession]:
        return self.sessions[-1] if self.sessions else None

    @property
    def next_nonce(self) -> int:
        return 0 if self.last is None else self.last.nonce + 1

    def session_at(self, t_ns: int) -> int:
        """Numéro de la session en vigueur à `t_ns`.

        0 désigne la session ouverte **avant** le scénario (aucune jointure déclarée) ; chaque
        jointure acceptée en ouvre une de plus : la première porte le numéro 1. C'est ce qui
        distingue « pas encore joint » de « première jointure », et ce qui rend une trame de la
        session 0 périmée dès la jointure.
        """
        instants = [s.opened_ns for s in self.sessions]
        return bisect_right(instants, t_ns)

    def current(self) -> int:
        return 0 if not self.sessions else self.sessions[-1].index

    def opened_at(self, index: int) -> Optional[int]:
        for session in self.sessions:
            if session.index == index:
                return session.opened_ns
        return None

    # --- écriture --------------------------------------------------------------------------

    def accept(self, join: JoinAccept) -> "SessionTimeline":
        """Ajoute la jointure si elle est recevable ; lève `JoinRejected` sinon.

        Refus explicites : `JoinNonce` non strictement croissant (rejeu), instant non
        strictement postérieur à la dernière session (ordre impossible), nonce déjà consommé.
        """
        dernier = self.last
        if dernier is not None:
            if join.nonce <= dernier.nonce:
                raise JoinRejected(f"JoinNonce {join.nonce} déjà consommé "
                                   f"(dernier accepté : {dernier.nonce})")
            if join.at_ns <= dernier.opened_ns:
                raise JoinRejected("une nouvelle session doit s'ouvrir après la précédente "
                                   f"({join.at_ns} <= {dernier.opened_ns})")
        session = AcceptedSession(index=self.count + 1, opened_ns=join.at_ns, nonce=join.nonce)
        return SessionTimeline(self.sessions + (session,))

    def is_stale(self, session: int, t_ns: int) -> bool:
        """Vrai quand `session` n'est plus la session en vigueur à `t_ns`."""
        return session < self.session_at(t_ns)
