"""Jointure OTAA dans le moteur radio : transport, fenêtres RX1/RX2, pertes, rejeu.

Ce qui est vérifié ici est le **transport** de la jointure, pas son authentification : aucun test
n'affirme qu'un `MIC` est validé ni qu'une clé est dérivée.

**Fenêtres.** RX1 (`JOIN_ACCEPT_DELAY1`, 5 s) puis RX2 (`JOIN_ACCEPT_DELAY2`, 6 s) : RX2 n'est émise
que si RX1 n'a pas abouti. Si RX1 est reçue, il n'y a **aucune** émission RX2. Le rejeu d'un
Join-Accept est un autre mécanisme : une émission supplémentaire du même message, reçue puis refusée.

| Ce qui est vérifié | Test |
|---|---|
| Join-Request de 23 octets, reçu, session ouverte | `test_a_join_request_received_opens_a_session` |
| RX1 reçue : une seule émission, aucune RX2 | `test_rx1_delivered_emits_no_rx2` |
| RX1 manquée : RX2 en secours, session ouverte | `test_rx1_missed_falls_back_to_rx2` |
| RX1 et RX2 manquées : aucune session | `test_both_windows_missed_open_nothing` |
| Rejeu : copie reçue puis refusée, pas de seconde session | `test_a_replayed_accept_does_not_renew` |
| Un terminal joint, un autre non | `test_terminals_join_independently` |
| Une seule jointure acceptée = une seule session | `test_one_accepted_join_opens_exactly_one_session` |
| Join-Request perdu : aucune session, compteurs intacts | `test_a_lost_join_request_renews_nothing` |
| Collision de deux Join-Request simultanés | `test_colliding_join_requests_open_nothing` |
| Deux tentatives : une seule session par terminal | `test_a_retry_joins_after_a_collision` |
| Événements `join_request` / `join_accept` et leurs issues | `test_the_trace_carries_the_radio_join` |
| Empreinte et validation du scénario | `test_the_hash_and_the_validation` |
"""

import types

import pytest
import yaml
from pydantic import ValidationError

from lsim.join import (JOIN_ACCEPT_BYTES, JOIN_ACCEPT_DELAY1_NS, JOIN_ACCEPT_DELAY2_NS,
                       JOIN_REQUEST_BYTES, JOIN_WINDOW_NS, JoinRadioOptions, accept_airtime_ns,
                       join_request_device, simulate_joins)
from lsim.scenario import load_scenario
from lsim.sessions import SessionTimeline
from lsim.trace_events import ProtocolOptions, build_trace, device_radios

EXEMPLE = "docs/exemples/retransmissions_ack_tardif.yaml"


def _brut(modifier=None, exemple=EXEMPLE, **reglages):
    data = yaml.safe_load(open(exemple, encoding="utf-8"))
    if modifier is not None:
        modifier(data)
    reglages.setdefault("join_requests_s", [10])
    data["retransmissions"].update({"ack_delay_ms": 0, **reglages})
    return data


def _scenario(modifier=None, exemple=EXEMPLE, **reglages):
    return load_scenario(yaml.safe_dump(_brut(modifier, exemple, **reglages)))


def _trace(modifier=None, exemple=EXEMPLE, options=ProtocolOptions(), **reglages):
    return build_trace(_scenario(modifier, exemple, **reglages), options)


def _loin(data):
    data["groups"][0]["placement"] = {"type": "explicit", "positions": [[20000.0, 0.0]]}


def _deux(positions):
    def modifier(data):
        data["groups"][0]["count"] = len(positions)
        data["groups"][0]["placement"] = {"type": "explicit", "positions": positions}

    return modifier


def _lent(data):
    """Trames de 51 octets en SF12 : une transmission couvre plus d'une seconde."""
    data["groups"][0].update({"spreading_factor": 12, "payload_bytes": 51, "period_s": 60,
                              "messages": 3, "start_spread_s": 4})
    data["retransmissions"].update({"ack_delay_ms": 2500, "retries": 2})


# --- transport ----------------------------------------------------------------------------------

def test_the_join_request_goes_through_the_radio_engine():
    scenario = _scenario()
    devices, _, _ = scenario.deploy()
    radio = device_radios(scenario)[0]
    clone = join_request_device(devices[0], 10_000_000_000)
    assert clone.payload_bytes == JOIN_REQUEST_BYTES == 23
    assert clone.messages == 1 and clone.start_offset_ns == 10_000_000_000
    assert clone.payload_bytes > devices[0].payload_bytes
    assert accept_airtime_ns(radio) > 0 and JOIN_ACCEPT_BYTES == 33


def test_a_join_request_received_opens_a_session():
    trace = _trace()
    tentatives = trace.retransmissions.joins
    assert len(tentatives) == 1
    tentative = tentatives[0]
    assert tentative.request_outcome == "received"
    assert tentative.accept_outcome == "delivered"
    assert tentative.session == 1
    assert [a.session for a in trace.retransmissions.attempts] == [0, 1]
    assert [a.f_cnt_up for a in trace.retransmissions.attempts] == [0, 0]


# --- fenêtres RX1 / RX2 -------------------------------------------------------------------------

def test_rx1_delivered_emits_no_rx2():
    tentative = _trace().retransmissions.joins[0]
    assert [e.window for e in tentative.accepts] == ["rx1"]
    assert tentative.accepts[0].outcome == "delivered"
    # RX1 tombe exactement JOIN_ACCEPT_DELAY1 après la fin du Join-Request.
    assert tentative.accepts[0].at_ns == tentative.request_end_ns + JOIN_ACCEPT_DELAY1_NS
    assert tentative.accept_window == "rx1"


def test_rx1_missed_falls_back_to_rx2():
    """Le terminal émet une trame de 51 octets en SF12 : elle couvre l'instant de RX1.

    La requête est placée à 56 s, dans un trou du calendrier ; RX1 à 62,48 s tombe dans la trame
    émise de 60,54 à 63,00 s, RX2 à 63,48 s est libre. Cas de bout en bout, sans calendrier fabriqué.
    """
    trace = _trace(_lent, join_requests_s=[56])
    tentative = trace.retransmissions.joins[0]
    assert tentative.request_outcome == "received"
    assert [(e.window, e.outcome) for e in tentative.accepts] == [
        ("rx1", "not_listened"), ("rx2", "delivered")]
    # RX1 est bien émise — la passerelle ne sait pas que le terminal n'écoute pas — et occupe
    # l'émetteur pendant tout son temps de vol (33 o en SF12 : 1,81 s), donc au-delà de
    # l'ouverture de RX2. RX2 est décalée à la fin de l'émission de RX1 (D3.13), tout en
    # restant dans sa fenêtre d'une seconde.
    radio = device_radios(_scenario(_lent, join_requests_s=[56]))[0]
    assert tentative.accepts[1].at_ns == tentative.accepts[0].at_ns + accept_airtime_ns(radio)
    assert (tentative.request_end_ns + JOIN_ACCEPT_DELAY2_NS
            <= tentative.accepts[1].at_ns
            < tentative.request_end_ns + JOIN_ACCEPT_DELAY2_NS + JOIN_WINDOW_NS)
    assert tentative.accept_window == "rx2"
    assert tentative.session == 1
    # Les événements de trace suivent les émissions réellement faites, fenêtre par fenêtre.
    emissions = [(e.t_ns, e.hops[0].outcome) for e in trace.events if e.kind == "join_accept"]
    assert emissions == [(tentative.accepts[0].at_ns, "not_listened"),
                         (tentative.accepts[1].at_ns, "delivered")]


def test_both_windows_missed_open_nothing():
    """Terminal à 9 km avec récepteur dégradé de 10 dB : requête reçue, descente sous la sensibilité."""
    def loin(data):
        data["groups"][0]["placement"] = {"type": "explicit", "positions": [[9000.0, 0.0]]}

    trace = _trace(loin, options=ProtocolOptions(device_rx_offset_db=10))
    tentative = trace.retransmissions.joins[0]
    assert tentative.request_outcome == "received"
    assert [(e.window, e.outcome) for e in tentative.accepts] == [
        ("rx1", "lost_sensitivity"), ("rx2", "lost_sensitivity")]
    assert tentative.session == 0
    assert {a.session for a in trace.retransmissions.attempts} == {0}
    # Deux émissions ont bien eu lieu, aucune n'a été écoutée.
    evenements = [e for e in trace.events if e.kind == "join_accept"]
    assert len(evenements) == 2 and all(e.hops[0].outcome == "lost_sensitivity"
                                        for e in evenements)


def test_the_rx2_fallback_can_be_disabled():
    trace = _trace(_lent, join_requests_s=[56], join_accept_rx2_fallback=False)
    tentative = trace.retransmissions.joins[0]
    assert [(e.window, e.outcome) for e in tentative.accepts] == [("rx1", "not_listened")]
    assert tentative.session == 0
    assert [e.kind for e in trace.events if e.kind == "join_accept"] == ["join_accept"]


def test_a_replayed_accept_does_not_renew():
    trace = _trace(join_accept_replays=1)
    tentative = trace.retransmissions.joins[0]
    assert [e.window for e in tentative.accepts] == ["rx1", "replay"]
    assert tentative.accept_replays == 1              # émission reçue puis refusée
    assert tentative.session == 1
    assert {a.session for a in trace.retransmissions.attempts} == {0, 1}
    # Le rejeu apparaît en trace comme une émission refusée, pas comme une seconde jointure.
    rejeux = [e for e in trace.events if e.kind == "join_accept"
              and e.hops[0].outcome == "suppressed"]
    assert len(rejeux) == 1


# --- plusieurs terminaux ------------------------------------------------------------------------

def test_terminals_join_independently():
    trace = _trace(_deux([[100.0, 0.0], [20000.0, 0.0]]))
    par_terminal = {j.device: (j.request_outcome, j.session) for j in trace.retransmissions.joins}
    assert par_terminal == {0: ("received", 1), 1: ("lost_sensitivity", 0)}
    # Le terminal joint change de session ; l'autre reste en session 0.
    assert {(a.device, a.session) for a in trace.retransmissions.attempts} == {(0, 0), (0, 1),
                                                                              (1, 0)}


def test_one_accepted_join_opens_exactly_one_session():
    trace = _trace(join_accept_replays=2)
    tentative = trace.retransmissions.joins[0]
    assert tentative.session == 1
    assert tentative.accept_replays == 2
    # Une seule session ouverte : la trace ne contient qu'une transition 0 → 1.
    sessions = [a.session for a in trace.retransmissions.attempts]
    assert sessions.count(1) >= 1 and max(sessions) == 1


# --- pertes et collisions -----------------------------------------------------------------------

def test_a_lost_join_request_renews_nothing():
    trace = _trace(_loin)
    tentative = trace.retransmissions.joins[0]
    assert tentative.request_outcome == "lost_sensitivity"
    assert tentative.accepts == () and tentative.session == 0
    assert {a.session for a in trace.retransmissions.attempts} == {0}
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
    assert [(j.device, j.request_ns // 1_000_000_000, j.request_outcome) for j in joints] == [
        (0, 10, "received"), (1, 10, "lost_collision"), (1, 20, "received")]
    assert sorted({j.session for j in joints if j.session}) == [1]
    assert {a.session for a in trace.retransmissions.attempts} == {0, 1}


# --- cas construit ------------------------------------------------------------------------------

def test_a_window_can_be_closed_by_a_transmission():
    """Cas construit : le calendrier de données est fabriqué pour couvrir RX1 seulement."""
    scenario = _scenario()
    devices, _, _ = scenario.deploy()
    radios = device_radios(scenario)

    def joue(occupation=()):
        return simulate_joins(devices, scenario.gateway(), scenario.propagation(), radios,
                              ProtocolOptions(), scenario.environment, [(0, 10_000_000_000)],
                              {}, data_attempts=occupation,
                              join_options=JoinRadioOptions(requests_s=(10,)))

    rx1 = None
    premiere = joue()
    rx1 = premiere.attempts[0].accepts[0].at_ns
    occupation = [types.SimpleNamespace(device=0, start_ns=rx1 - 100_000_000,
                                        end_ns=rx1 + 100_000_000)]
    resultat = joue(occupation)
    assert [(e.window, e.outcome) for e in resultat.attempts[0].accepts] == [
        ("rx1", "not_listened"), ("rx2", "delivered")]
    assert resultat.attempts[0].session == 1


# --- trace --------------------------------------------------------------------------------------

def test_the_trace_carries_the_radio_join():
    trace = _trace()
    evenements = [(e.kind, e.t_ns // 1_000_000_000, e.hops[0].outcome) for e in trace.events
                  if e.kind.startswith("join")]
    assert evenements == [("join_request", 10, "received"), ("join_accept", 15, "delivered")]
    assert [e.seq for e in trace.events] == list(range(len(trace.events)))


def test_a_lost_request_leaves_no_accept_event():
    trace = _trace(_loin)
    assert [e.kind for e in trace.events if e.kind.startswith("join")] == ["join_request"]
    assert trace.events[0].hops[0].outcome == "lost_sensitivity"


# --- scénario -----------------------------------------------------------------------------------

def test_the_hash_and_the_validation():
    data = yaml.safe_load(open(EXEMPLE, encoding="utf-8"))
    reference = load_scenario(yaml.safe_dump(
        {**data, "retransmissions": {**data["retransmissions"], "ack_delay_ms": 0}}))
    sans = _scenario(join_requests_s=[])
    avec = _scenario()
    assert sans.sha256 == reference.sha256
    assert avec.sha256 != reference.sha256

    with pytest.raises(ValidationError, match="ensemble"):
        _scenario(session_joins_s=[10])
    with pytest.raises(ValidationError):
        _scenario(join_retries=4)
    with pytest.raises(ValidationError):
        _scenario(join_accept_replays=3)
    with pytest.raises(ValidationError, match="croissants"):
        _scenario(join_requests_s=[20, 10])


def test_the_options_validate_the_windows():
    assert JoinRadioOptions(requests_s=(10,)).rx2_fallback is True
    with pytest.raises(ValueError, match="join_accept_replays"):
        JoinRadioOptions(requests_s=(10,), accept_replays=3)
