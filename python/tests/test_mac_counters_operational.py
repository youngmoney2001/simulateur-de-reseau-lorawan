"""Validation opérationnelle des compteurs de trame (D3.10).

Les tests de `test_fcnt_counters.py` vérifient les primitives et le plan ; ceux-ci vérifient ce qui
se **passe** dans une exécution complète : quelle série est consommée, ce que montre la trace, ce que
le terminal accepte après une nouvelle session, et ce que les réglages existants (ACK tardif,
dupliqué, réémission) produisent quand les compteurs sont exercés.

| Ce qui est vérifié | Test |
|---|---|
| `ack_only` consomme `NFCntDown` | `test_an_ack_only_downlink_consumes_nfcnt` |
| `data_ack` consomme `AFCntDown` | `test_a_downlink_with_payload_consumes_afcnt` |
| une nouvelle session ne rejette pas le compteur 0 | `test_a_new_session_restarts_both_counters` |
| un doublon reste un rejeu dans sa session | `test_a_duplicate_is_a_replay_inside_its_session` |
| série épuisée : aucun ACK, compté, et trace cohérente | `test_an_exhausted_series_is_visible_end_to_end` |
| ACK tardif en mode applicatif | `test_a_late_ack_stays_late_in_af_mode` |
| copies en mode applicatif | `test_copies_are_duplicates_in_af_mode` |
| réémissions intactes en mode applicatif | `test_retransmissions_are_unchanged_in_af_mode` |
| trace ↔ compteurs ↔ occupation | `test_the_trace_agrees_with_the_counters_in_both_series` |
| hash inchangé sans le réglage | `test_the_payload_switch_is_absent_from_the_hash_by_default` |
"""

import yaml

from lsim.ack_mac import AckSort, AckTiming, plan_acks
from lsim.fcnt import MODULUS_32, CounterVerdict, DeviceCounters
from lsim.scenario import load_scenario
from lsim.trace_events import DeviceRadio, ProtocolOptions, TxRecord, build_trace

EXEMPLES = "docs/exemples"


def _radio():
    return DeviceRadio(freq_hz=868_100_000, dr=3, rx1_hz=868_100_000)


def _record(start_ns, end_ns, rssi=-70.0, device=0):
    return TxRecord(device, start_ns, end_ns, 9, rssi, 2)


def _trace(nom, classe="A", **reglages):
    data = yaml.safe_load(open(f"{EXEMPLES}/{nom}", encoding="utf-8"))
    data["retransmissions"].update(reglages)
    data["groups"][0]["device_class"] = classe
    return build_trace(load_scenario(yaml.safe_dump(data)))


def _acks(trace):
    return [e for e in trace.events if e.kind == "ack"]


# --- quelle série est consommée ---------------------------------------------------------------

def test_an_ack_only_downlink_consumes_nfcnt():
    plan = plan_acks((_record(0, 100_000_000),), (_radio(),), ProtocolOptions(), AckTiming())
    assert [o.series for o in plan.outcomes] == ["NF"]
    trace = _trace("retransmissions_ack_tardif.yaml", classe="C")
    assert {e.outcome for e in _acks(trace)} == {"ack_only"}
    assert [a.f_cnt_down for a in trace.retransmissions.attempts] == [0, 1]


def test_a_downlink_with_payload_consumes_afcnt():
    plan = plan_acks((_record(0, 100_000_000),), (_radio(),), ProtocolOptions(), AckTiming(),
                     payload=True)
    assert [o.series for o in plan.outcomes] == ["AF"]
    trace = _trace("retransmissions_ack_tardif.yaml", classe="C", downlink_payload=True)
    assert {e.outcome for e in _acks(trace)} == {"data_ack"}
    assert [a.f_cnt_down for a in trace.retransmissions.attempts] == [0, 1]
    # Mêmes transmissions, même livraison : seule la série consommée change.
    assert trace.retransmissions.transmissions == 2
    assert trace.retransmissions.frames_delivered == 2
    assert trace.retransmissions.ack_standard == 2


def test_the_two_series_are_counted_separately():
    """Même départ de session, mais deux séries qui ne se mélangent pas."""
    nf = _trace("retransmissions_ack_tardif.yaml", classe="C", fcnt_down_start=100)
    af = _trace("retransmissions_ack_tardif.yaml", classe="C", fcnt_down_start=100,
                downlink_payload=True)
    assert [a.f_cnt_down for a in nf.retransmissions.attempts] == [100, 101]
    assert [a.f_cnt_down for a in af.retransmissions.attempts] == [100, 101]

    compteurs = DeviceCounters.of(downlink_start=100)
    assert compteurs.series(True).last is None and compteurs.series(False).last is None
    compteurs = DeviceCounters(compteurs.uplink, compteurs.nfcnt_down.accept(100),
                               compteurs.afcnt_down, 0)
    assert (compteurs.nfcnt_down.last, compteurs.afcnt_down.last) == (100, None)


# --- sessions -----------------------------------------------------------------------------------

def test_a_new_session_restarts_both_counters():
    terminal = DeviceCounters.of(downlink_start=0)
    terminal = DeviceCounters(terminal.uplink.accept(41),
                              terminal.nfcnt_down.accept(7),
                              terminal.afcnt_down.accept(3), terminal.session)
    renouvele = terminal.renew_session()
    assert renouvele.session == 1
    assert (renouvele.uplink.last, renouvele.nfcnt_down.last, renouvele.afcnt_down.last) == \
        (None, None, None)
    # Le compteur 0 de la nouvelle session n'est pas un rejeu de celui de l'ancienne.
    assert renouvele.nfcnt_down.reconstruct(0).verdict is CounterVerdict.OK


def test_a_duplicate_is_a_replay_inside_its_session():
    records = (_record(0, 100_000_000), _record(5_000_000_000, 5_100_000_000))
    plan = plan_acks(records, (_radio(), _radio()), ProtocolOptions(),
                     AckTiming(repetitions=2), sessions=(0, 0))
    premier, second = plan.outcomes
    assert premier.sort is AckSort.STANDARD and premier.session == 0
    # Les deux copies de la première trame : la seconde est un rejeu, dans la session 0.
    assert [e.sort for e in premier.emissions] == [AckSort.STANDARD, AckSort.DUPLICATE]
    assert second.session == 0


def test_a_second_session_does_not_inherit_the_first():
    """Même terminal, deux sessions : le compteur 0 de la session 1 est neuf, pas un rejeu."""
    records = (_record(0, 100_000_000), _record(5_000_000_000, 5_100_000_000))
    plan = plan_acks(records, (_radio(), _radio()), ProtocolOptions(), AckTiming(),
                     sessions=(0, 1))
    premier, second = plan.outcomes
    assert (premier.sort, second.sort) == (AckSort.STANDARD, AckSort.STANDARD)
    assert (premier.session, second.session) == (0, 1)
    # Chaque session numérote à partir du même départ.
    assert (premier.f_cnt_down, second.f_cnt_down) == (0, 0)


# --- débordement, tardif, copies, réémissions ----------------------------------------------------

def test_an_exhausted_series_is_visible_end_to_end():
    trace = _trace("retransmissions_ack_tardif.yaml", classe="C",
                   fcnt_down_start=MODULUS_32 - 1)
    resultat = trace.retransmissions
    assert resultat.acks_planned == 1                     # un seul ACK numérotable
    assert resultat.ack_standard == 1
    assert resultat.ack_not_sent >= 1                     # la série épuisée n'émet plus
    assert len(_acks(trace)) == resultat.acks_planned      # la trace ne montre que l'émis
    assert [e.t_ns for e in _acks(trace)] == [trace.retransmissions.gateway_tx[0][0]]


def test_a_late_ack_stays_late_in_af_mode():
    trace = _trace("retransmissions_ack_tardif.yaml", classe="A", downlink_payload=True)
    resultat = trace.retransmissions
    assert resultat.ack_late == resultat.acks_planned == 6
    assert resultat.acks_received == 0 and resultat.frames_delivered == 0
    assert {e.outcome for e in _acks(trace)} == {"not_listened"}


def test_copies_are_duplicates_in_af_mode():
    trace = _trace("retransmissions_ack_duplique.yaml", downlink_payload=True)
    resultat = trace.retransmissions
    assert (resultat.ack_standard, resultat.ack_duplicate) == (2, 2)
    assert resultat.ack_duplicates_ignored == 2
    issues = [e.outcome for e in _acks(trace)]
    assert issues.count("data_ack") == 2 and issues.count("suppressed") == 2


def test_retransmissions_are_unchanged_in_af_mode():
    trace = _trace("retransmissions_ack_tardif.yaml", downlink_payload=True)
    resultat = trace.retransmissions
    assert resultat.transmissions == 6 and resultat.retransmissions == 4
    assert resultat.frames == 2 and resultat.frames_delivered == 0
    assert [(a.device, a.frame, a.attempt) for a in resultat.attempts] == \
        [(0, 0, 0), (0, 0, 1), (0, 0, 2), (0, 1, 0), (0, 1, 1), (0, 1, 2)]


# --- trace, occupation, hash ---------------------------------------------------------------------

def test_the_trace_agrees_with_the_counters_in_both_series():
    for mode in (False, True):
        trace = _trace("retransmissions_ack_duplique.yaml", classe="C", downlink_payload=mode)
        resultat = trace.retransmissions
        acks = _acks(trace)
        assert len(acks) == resultat.acks_planned
        debuts = {debut for debut, _fin in resultat.gateway_tx}
        assert all(e.t_ns in debuts for e in acks)
        assert [e.seq for e in trace.events] == list(range(len(trace.events)))
        assert [e.t_ns for e in trace.events] == sorted(e.t_ns for e in trace.events)


def test_the_payload_switch_is_absent_from_the_hash_by_default():
    data = yaml.safe_load(open(f"{EXEMPLES}/retransmissions_ack_tardif.yaml", encoding="utf-8"))
    sans = load_scenario(yaml.safe_dump(data))
    data["retransmissions"]["downlink_payload"] = False
    avec = load_scenario(yaml.safe_dump(data))
    assert sans.sha256 == avec.sha256
    data["retransmissions"]["downlink_payload"] = True
    assert load_scenario(yaml.safe_dump(data)).sha256 != sans.sha256
