"""Événements de trace produits par la couche MAC de l'ACK.

Avant cet incrément, les ACK d'un scénario à retransmissions venaient du planificateur du cœur :
la trace ne montrait donc pas les ACK réellement émis par `lsim.ack_mac` (tardifs ou dupliqués),
alors que leur airtime était bien imposée au moteur. Ce fichier vérifie que la trace et le plan
MAC racontent la même chose, et que le vocabulaire reste celui du contrat d'API.

| Ce qui est vérifié | Test |
|---|---|
| une émission = un événement `ack`, aux instants de l'occupation | `test_every_mac_emission_becomes_an_ack_event` |
| ACK tardif : `not_listened` | `test_a_late_ack_is_an_event_nobody_listens_to` |
| ACK dupliqué : la copie est `suppressed` | `test_a_duplicate_ack_is_suppressed_in_the_trace` |
| ACK non décodable : `lost_sensitivity` | `test_an_undecodable_ack_is_lost_sensitivity` |
| terminal en émission : `device_transmitting` | `test_an_ack_sent_while_the_device_transmits_is_device_transmitting` |
| vocabulaire contenu dans `lsim.api_contract` | `test_the_event_vocabulary_stays_in_the_api_contract` |
| chemin du cœur inchangé quand la couche MAC n'est pas active | `test_the_core_path_keeps_its_events` |
"""

import typing

import yaml

from lsim import api_contract
from lsim.ack_mac import AckTiming, plan_acks
from lsim.retransmissions import _mac_ack_events
from lsim.scenario import load_scenario
from lsim.trace_events import DeviceRadio, ProtocolOptions, TxRecord, build_trace

EXEMPLES = "docs/exemples"


def _trace(nom, offset=0.0, **reglages):
    data = yaml.safe_load(open(f"{EXEMPLES}/{nom}", encoding="utf-8"))
    data["retransmissions"].update(reglages)
    return build_trace(load_scenario(yaml.safe_dump(data)),
                       ProtocolOptions(device_rx_offset_db=offset))


def _acks(trace):
    return [e for e in trace.events if e.kind == "ack"]


# --- une émission, un événement ----------------------------------------------------------------

def test_every_mac_emission_becomes_an_ack_event():
    trace = _trace("retransmissions_ack_tardif.yaml")
    resultat = trace.retransmissions
    acks = _acks(trace)
    assert len(acks) == resultat.acks_planned == 6
    # Même horloge que l'occupation passerelle : chaque événement commence une émission connue.
    debuts = {debut for debut, _fin in resultat.gateway_tx}
    assert all(e.t_ns in debuts for e in acks)
    # Trace triée et séquence contiguë, comme le reste du chemin.
    assert [e.seq for e in trace.events] == list(range(len(trace.events)))
    assert [e.t_ns for e in trace.events] == sorted(e.t_ns for e in trace.events)


def test_a_late_ack_is_an_event_nobody_listens_to():
    trace = _trace("retransmissions_ack_tardif.yaml")
    acks = _acks(trace)
    assert {e.outcome for e in acks} == {"not_listened"}
    assert all(h.outcome == "not_listened" for e in acks for h in e.hops)
    assert all(h.from_id == "gw:0" and h.to_id.startswith("dev:") for e in acks for h in e.hops)


def test_a_duplicate_ack_is_suppressed_in_the_trace():
    trace = _trace("retransmissions_ack_duplique.yaml")
    acks = _acks(trace)
    issues = [e.outcome for e in acks]
    assert issues.count("ack_only") == 2
    assert issues.count("suppressed") == 2
    # Chaque copie rejetée suit de près celle qui a été acceptée, et le saut est « delivered ».
    assert all(h.outcome == "delivered" for e in acks for h in e.hops)
    assert acks[1].t_ns - acks[0].t_ns > 0


def test_an_undecodable_ack_is_lost_sensitivity():
    trace = _trace("retransmissions_ack_perdu.yaml", offset=10.0, ack_delay_ms=1000)
    acks = _acks(trace)
    issues = [e.outcome for e in acks]
    assert "lost_sensitivity" in issues
    assert issues.count("ack_only") == trace.retransmissions.acks_received
    assert all(h.outcome == "lost_sensitivity" for e in acks if e.outcome == "lost_sensitivity"
               for h in e.hops)


def test_an_ack_sent_while_the_device_transmits_is_device_transmitting():
    """Cas construit : le terminal émet exactement à l'ouverture de RX1 de sa trame précédente."""
    radio = DeviceRadio(freq_hz=868_100_000, dr=3, rx1_hz=868_100_000)
    # La première trame finit à 0,1 s : RX1 ouvre à 1,1 s. La seconde transmission commence
    # exactement à cette ouverture — le terminal ne peut donc pas écouter.
    records = (
        TxRecord(0, 0, 100_000_000, 9, -70.0, 2),
        TxRecord(0, 1_100_000_000, 1_200_000_000, 9, -70.0, 2),
    )
    plan = plan_acks(records, (radio, radio), ProtocolOptions(), AckTiming(),
                     fcnt_up=(0, 1))
    assert plan.outcomes[0].window.value == "window_missed"
    evenements = _mac_ack_events(records, plan, (radio, radio))
    premier = evenements[0]
    assert premier.kind == "ack" and premier.outcome == "device_transmitting"
    assert premier.hops[0].outcome == "not_listened"


# --- contrats et non-régression -----------------------------------------------------------------

def test_the_event_vocabulary_stays_in_the_api_contract():
    """Aucune valeur hors du contrat : les mêmes literals servent à l'API et à la studio."""
    kinds = set(typing.get_args(api_contract.EventKind))
    hop_outcomes = set(typing.get_args(api_contract.HopOutcome))
    # Issues d'un événement `ack` de la couche MAC : celles du chemin du cœur, plus les deux
    # qu'il ne sait pas produire (tardif écouté par personne, copie rejetée par le compteur).
    issues_ack = {"ack_only", "lost_sensitivity", "device_transmitting", "not_listened",
                  "suppressed"}
    for trace in (_trace("retransmissions_ack_tardif.yaml"),
                  _trace("retransmissions_ack_duplique.yaml"),
                  _trace("retransmissions_ack_perdu.yaml", offset=10.0, ack_delay_ms=1000)):
        for evenement in trace.events:
            assert evenement.kind in kinds, evenement.kind
            if evenement.kind == "ack":
                assert evenement.outcome in issues_ack, evenement.outcome
            assert len(evenement.outcome) <= 64        # TraceEvent.outcome : max_length=64
            for hop in evenement.hops:
                assert hop.outcome in hop_outcomes, hop.outcome


def test_the_core_path_keeps_its_events():
    """Sans couche MAC, la trace garde exactement les événements du planificateur du cœur."""
    trace = _trace("retransmissions_ack_tardif.yaml", ack_delay_ms=0)
    acks = _acks(trace)
    assert [e.outcome for e in acks] == ["ack_only", "ack_only"]
    assert trace.retransmissions.acks_planned == 2
    # Et aucun événement d'ACK en double : une émission, un événement.
    assert len(acks) == trace.retransmissions.acks_planned
