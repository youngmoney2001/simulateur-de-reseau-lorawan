"""Jointure OTAA dans le moteur radio : transport, pertes, collisions, rejeu.

Ce qui est vérifié ici est le **transport** de la jointure, pas son authentification : aucun test
n'affirme qu'un `MIC` est validé ni qu'une clé est dérivée. Les scénarios s'appuient sur les fichiers
de `docs/exemples/` ; les cas qui exigent une condition impossible à écrire en YAML (terminal en
émission au moment du Join-Accept) sont construits à la main et signalés comme tels.

| Ce qui est vérifié | Test |
|---|---|
| Join-Request de 23 octets, reçu, session ouverte | `test_a_join_request_received_opens_a_session` |
| Join-Request perdu : aucune session, compteurs intacts | `test_a_lost_join_request_renews_nothing` |
| Collision de deux Join-Request simultanés | `test_colliding_join_requests_open_nothing` |
| Tentatives répétées : une seule session par terminal | `test_a_retry_joins_after_a_collision` |
| Join-Accept rejoué (copie RX2) : une seule session | `test_a_replayed_join_accept_is_rejected` |
| Terminal en émission : le Join-Accept n'est pas écouté | `test_an_accept_is_missed_when_the_device_transmits` |
| Événements `join_request` / `join_accept` et leurs issues | `test_the_trace_carries_the_radio_join` |
| Empreinte et validation du scénario | `test_the_hash_and_the_validation` |
"""

import dataclasses
import types

import pytest
import yaml
from pydantic import ValidationError

from lsim.join import (JOIN_ACCEPT_BYTES, JOIN_REQUEST_BYTES, JoinRadioOptions,
                       accept_airtime_ns, simulate_joins, join_request_device)
from lsim.scenario import load_scenario
from lsim.trace_events import ProtocolOptions, build_trace, device_radios

EXEMPLE = "docs/exemples/retransmissions_ack_tardif.yaml"


def _scenario(modifier=None, **reglages):
    data = yaml.safe_load(open(EXEMPLE, encoding="utf-8"))
    if modifier is not None:
        modifier(data)
    reglages.setdefault("join_requests_s", [10])
    data["retransmissions"].update({"ack_delay_ms": 0, **reglages})
    return load_scenario(yaml.safe_dump(data))


def _trace(modifier=None, **reglages):
    return build_trace(_scenario(modifier, **reglages))


def _loin(data):
    data["groups"][0]["placement"] = {"type": "explicit", "positions": [[20000.0, 0.0]]}


def _deux(positions):
    def modifier(data):
        data["groups"][0]["count"] = len(positions)
        data["groups"][0]["placement"] = {"type": "explicit", "positions": positions}

    return modifier


# --- transport ----------------------------------------------------------------------------------

def test_the_join_request_goes_through_the_radio_engine():
    scenario = _scenario()
    devices, _, _ = scenario.deploy()
    radio = device_radios(scenario)[0]
    clone = join_request_device(devices[0], 10_000_000_000)
    assert clone.payload_bytes == JOIN_REQUEST_BYTES == 23
    assert clone.messages == 1 and clone.start_offset_ns == 10_000_000_000
    # Le Join-Request est plus long qu'une trame de données du scénario : il occupe l'air.
    assert clone.payload_bytes > devices[0].payload_bytes
    assert accept_airtime_ns(radio) > 0 and JOIN_ACCEPT_BYTES == 33


def test_a_join_request_received_opens_a_session():
    trace = _trace()
    joints = trace.retransmissions.joins
    assert len(joints) == 1
    tentative = joints[0]
    assert tentative.request_outcome == "received"
    assert tentative.accept_outcome == "delivered"
    assert tentative.session == 1
    # Le Join-Accept part JOIN_ACCEPT_DELAY1 après la fin du Join-Request.
    assert tentative.accept_ns == tentative.request_end_ns + 5_000_000_000
    # Les trames d'avant la jointure restent en session 0, celles d'après en session 1.
    assert [a.session for a in trace.retransmissions.attempts] == [0, 1]
    # Une session neuve : FCntUp repart de zéro.
    assert [a.f_cnt_up for a in trace.retransmissions.attempts] == [0, 0]


def test_a_lost_join_request_renews_nothing():
    trace = _trace(_loin)
    tentative = trace.retransmissions.joins[0]
    assert tentative.request_outcome == "lost_sensitivity"
    assert tentative.accept_ns is None and tentative.session == 0
    assert {a.session for a in trace.retransmissions.attempts} == {0}
    # Aucune remise à zéro : les deux trames gardent leurs compteurs, réémissions comprises.
    assert sorted({a.f_cnt_up for a in trace.retransmissions.attempts}) == [0, 1]


def test_colliding_join_requests_open_nothing():
    trace = _trace(_deux([[100.0, 0.0], [100.0, 0.0]]))
    joints = trace.retransmissions.joins
    assert len(joints) == 2
    assert [j.request_outcome for j in joints] == ["lost_collision", "lost_collision"]
    assert all(j.session == 0 for j in joints)


def test_a_retry_joins_after_a_collision():
    trace = _trace(_deux([[100.0, 0.0], [300.0, 0.0]]), join_retries=2)
    joints = trace.retransmissions.joins
    # Trois tentatives : device 0 joint du premier coup, device 1 au second essai.
    assert [(j.device, j.request_ns // 1_000_000_000, j.request_outcome) for j in joints] == [
        (0, 10, "received"), (1, 10, "lost_collision"), (1, 20, "received")]
    # Chaque terminal a sa propre horloge : les deux ouvertures sont « session 1 » du terminal,
    # et aucune tentative réussie n'ouvre une deuxième session pour le même terminal.
    assert sorted({j.session for j in joints if j.session}) == [1]
    assert {a.session for a in trace.retransmissions.attempts} == {0, 1}


def test_a_replayed_join_accept_is_rejected():
    trace = _trace(join_accept_repetitions=2)
    tentative = trace.retransmissions.joins[0]
    assert tentative.accept_outcome == "delivered"
    assert tentative.accept_replays == 1          # la copie RX2 a été reçue puis refusée
    assert tentative.session == 1
    assert {a.session for a in trace.retransmissions.attempts} == {0, 1}


def test_an_accept_is_missed_when_the_device_transmits():
    """Cas construit : aucune trame de données ne tombe à 15,2 s dans les exemples livrés.

    Le calendrier de données est fabriqué à la main pour couvrir la fenêtre RX1 : c'est le seul
    moyen d'obtenir `not_listened` sans inventer un scénario irréaliste.
    """
    scenario = _scenario()
    devices, _, _ = scenario.deploy()
    radios = device_radios(scenario)
    def joue(occupation=()):
        return simulate_joins(devices, scenario.gateway(), scenario.propagation(), radios,
                              ProtocolOptions(), scenario.environment, [(0, 10_000_000_000)],
                              {}, data_attempts=occupation,
                              join_options=JoinRadioOptions(requests_s=(10,)))

    accept = joue().attempts[0].accept_ns                    # instant réel du Join-Accept
    occupation = [types.SimpleNamespace(device=0, start_ns=accept - 100_000_000,
                                        end_ns=accept + 100_000_000)]
    resultat = joue(occupation)
    assert resultat.attempts[0].request_outcome == "received"
    assert resultat.attempts[0].accept_outcome == "not_listened"
    assert resultat.attempts[0].session == 0
    assert resultat.timelines == {}


# --- trace --------------------------------------------------------------------------------------

def test_the_trace_carries_the_radio_join():
    trace = _trace()
    evenements = [(e.kind, e.t_ns // 1_000_000_000, e.hops[0].outcome) for e in trace.events
                  if e.kind.startswith("join")]
    assert evenements == [("join_request", 10, "received"), ("join_accept", 15, "delivered")]
    assert [e.seq for e in trace.events] == list(range(len(trace.events)))


def test_a_lost_request_leaves_no_accept_event():
    trace = _trace(_loin)
    evenements = [e.kind for e in trace.events if e.kind.startswith("join")]
    assert evenements == ["join_request"]
    assert trace.events[0].hops[0].outcome == "lost_sensitivity"


# --- scénario -----------------------------------------------------------------------------------

def test_the_hash_and_the_validation():
    data = yaml.safe_load(open(EXEMPLE, encoding="utf-8"))
    reference = load_scenario(yaml.safe_dump(
        {**data, "retransmissions": {**data["retransmissions"], "ack_delay_ms": 0}}))
    sans = _scenario(join_requests_s=[])
    avec = _scenario()
    # Une liste vide est retirée du hash ; une jointure déclarée le change.
    assert sans.sha256 == reference.sha256
    assert avec.sha256 != reference.sha256

    with pytest.raises(ValidationError, match="ensemble"):
        _scenario(session_joins_s=[10])
    with pytest.raises(ValidationError):
        _scenario(join_retries=4)
    with pytest.raises(ValidationError):
        _scenario(join_accept_repetitions=3)
    with pytest.raises(ValidationError, match="croissants"):
        _scenario(join_requests_s=[20, 10])
