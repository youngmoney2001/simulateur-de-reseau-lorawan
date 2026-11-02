"""Cycle de vie des sessions : jointures, renouvellement, trames périmées.

`lsim.sessions` ordonne les `Join-Accept` ; `lsim.retransmissions` les applique au calendrier et
`lsim.ack_mac` numérote les descentes par (terminal, session). Ce fichier vérifie le tout de bout en
bout, pas seulement la primitive.

| Ce qui est vérifié | Test |
|---|---|
| numérotation des sessions dans le temps | `test_session_at_numbers_the_joins` |
| rejeu d'un `Join-Accept` refusé | `test_a_replayed_join_is_rejected` |
| renouvellements répétés, dans l'ordre | `test_repeated_renewals_are_ordered` |
| instants de jointure validés par le scénario | `test_the_scenario_validates_join_times` |
| une jointure déclarée ouvre une session visible | `test_a_declared_join_opens_a_session` |
| `FCntUp` et `FCntDown` repartent de zéro | `test_counters_restart_at_each_session` |
| une trame de l'ancienne session n'est plus réémise | `test_a_stale_frame_is_not_retransmitted` |
| aucune jointure = une seule session, hash inchangé | `test_the_hash_is_unchanged_without_joins` |
| la trace reste triée et séquentielle | `test_the_trace_stays_ordered_with_joins` |
"""

import pytest
import yaml
from pydantic import ValidationError

from lsim.scenario import load_scenario
from lsim.sessions import JoinAccept, JoinRejected, SessionTimeline
from lsim.trace_events import build_trace

EXEMPLE = "docs/exemples/retransmissions_ack_tardif.yaml"


def _scenario(**reglages):
    data = yaml.safe_load(open(EXEMPLE, encoding="utf-8"))
    for cle in ("messages", "start_spread_s"):
        if cle in reglages:
            data["groups"][0][cle] = reglages.pop(cle)
    data["retransmissions"].update(reglages)
    return load_scenario(yaml.safe_dump(data))


def _trace(**reglages):
    return build_trace(_scenario(**reglages))


# --- timeline -----------------------------------------------------------------------------------

def test_session_at_numbers_the_joins():
    timeline = SessionTimeline.from_join_times([0, 40])
    assert timeline.count == 2
    assert timeline.session_at(-1) == 0           # avant la première jointure
    assert timeline.session_at(0) == 1
    assert timeline.session_at(39_999_999_999) == 1
    assert timeline.session_at(40_000_000_000) == 2
    assert timeline.current() == 2
    assert [s.index for s in timeline.sessions] == [1, 2]
    assert timeline.opened_at(2) == 40_000_000_000
    # Aucune jointure : une seule session, celle du scénario.
    assert SessionTimeline().session_at(10**12) == 0
    assert SessionTimeline().current() == 0


def test_a_replayed_join_is_rejected():
    timeline = SessionTimeline.from_join_times([10])
    with pytest.raises(JoinRejected, match="JoinNonce"):
        timeline.accept(JoinAccept(at_ns=20_000_000_000, nonce=0))   # nonce déjà consommé
    with pytest.raises(JoinRejected, match="après la précédente"):
        timeline.accept(JoinAccept(at_ns=5_000_000_000, nonce=1))    # instant antérieur
    accepte = timeline.accept(JoinAccept(at_ns=20_000_000_000, nonce=1))
    assert accepte.count == 2 and accepte.current() == 2


def test_repeated_renewals_are_ordered():
    timeline = SessionTimeline()
    for rang in range(3):
        timeline = timeline.accept(JoinAccept(at_ns=(rang + 1) * 60_000_000_000, nonce=rang))
    assert [s.index for s in timeline.sessions] == [1, 2, 3]
    assert [s.opened_ns for s in timeline.sessions] == [60_000_000_000, 120_000_000_000,
                                                      180_000_000_000]
    assert timeline.session_at(59_999_999_999) == 0
    assert timeline.session_at(60_000_000_000) == 1
    assert timeline.session_at(180_000_000_000) == 3


def test_the_scenario_validates_join_times():
    with pytest.raises(ValidationError, match="croissants"):
        _scenario(session_joins_s=[40, 10])
    with pytest.raises(ValidationError, match="positifs"):
        _scenario(session_joins_s=[-1])
    assert _scenario(session_joins_s=[0, 40]).model.retransmissions.session_joins_s == [0, 40]


# --- de bout en bout ----------------------------------------------------------------------------

def test_a_declared_join_opens_a_session():
    trace = _trace(session_joins_s=[6], messages=3, start_spread_s=10, ack_delay_ms=0)
    joins = [e for e in trace.events if e.kind.startswith("join")]
    assert [(e.kind, e.t_ns // 1_000_000_000) for e in joins] == [
        ("join_request", 1), ("join_accept", 6)]
    resultat = trace.retransmissions
    assert {a.session for a in resultat.attempts} == {0, 1}
    assert [a.session for a in resultat.attempts] == sorted(a.session for a in resultat.attempts)


def test_counters_restart_at_each_session():
    trace = _trace(session_joins_s=[0, 40], messages=3, start_spread_s=10, ack_delay_ms=1)
    tries = [(a.session, a.frame, a.f_cnt_up, a.f_cnt_down) for a in trace.retransmissions.attempts]
    # Session 1 : une trame, compteurs 0/0. Session 2 : deux trames, 0 puis 1 dans chaque série.
    assert tries == [(1, 0, 0, 0), (2, 0, 0, 0), (2, 1, 1, 1)]


def test_a_stale_frame_is_not_retransmitted():
    """Une jointure à 5 s coupe la réémission prévue à 7 s : la trame de la session 0 est périmée."""
    trace = _trace(session_joins_s=[5], messages=2, start_spread_s=10,
                   ack_delay_ms=2500, retries=2)
    resultat = trace.retransmissions
    assert resultat.rejected_stale_session >= 1
    # Aucune tentative de la session 0 ne commence après la jointure.
    assert all(a.start_ns < 5_000_000_000 for a in resultat.attempts if a.session == 0)
    assert all(a.start_ns >= 5_000_000_000 for a in resultat.attempts if a.session == 1)


def test_the_hash_is_unchanged_without_joins():
    data = yaml.safe_load(open(EXEMPLE, encoding="utf-8"))
    sans = load_scenario(yaml.safe_dump(data))
    data["retransmissions"]["session_joins_s"] = []
    assert load_scenario(yaml.safe_dump(data)).sha256 == sans.sha256
    data["retransmissions"]["session_joins_s"] = [0]
    assert load_scenario(yaml.safe_dump(data)).sha256 != sans.sha256


def test_the_trace_stays_ordered_with_joins():
    trace = _trace(session_joins_s=[0, 40], messages=3, start_spread_s=10, ack_delay_ms=0)
    assert [e.seq for e in trace.events] == list(range(len(trace.events)))
    assert [e.t_ns for e in trace.events] == sorted(e.t_ns for e in trace.events)
    assert all(e.outcome for e in trace.events)
