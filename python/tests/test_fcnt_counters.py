"""Compteurs de trame : rejeu, désynchronisation, débordement, reconstruction 16 bits.

Le module `lsim.fcnt` tient les primitives ; `lsim.ack_mac.plan_acks` les applique au plan des ACK
et `lsim.retransmissions` les expose dans la trace. Ce fichier couvre les deux niveaux, parce
qu'une primitive juste et un câblage faux donnent le même résultat visible : aucun des deux.

| Ce qui est vérifié | Test |
|---|---|
| rejeu d'un compteur déjà consommé | `test_a_consumed_counter_is_a_replay` |
| borne exacte `MAX_FCNT_GAP` (16 384 / 16 385) | `test_the_gap_boundary_is_the_specification_value` |
| débordement de la série 32 bits | `test_a_series_ends_at_two_to_the_thirty_two` |
| reconstruction du champ 16 bits | `test_the_sixteen_bit_field_wraps_once` |
| deux séries descendantes indépendantes | `test_the_two_downlink_series_do_not_move_together` |
| `fcnt_down_start` de bout en bout | `test_a_scenario_can_start_its_downlink_series` |
| série épuisée : aucun ACK, compté | `test_an_exhausted_series_emits_no_ack` |
| une copie est un rejeu, pas une désynchronisation | `test_a_copy_is_a_replay_not_a_gap` |
| réémission : nouveau `FCntDown`, même `FCntUp` | `test_a_retransmission_consumes_a_new_downlink_counter` |
| hash du scénario inchangé à la valeur par défaut | `test_the_start_does_not_change_the_hash_at_its_default` |
"""

from dataclasses import replace

import pytest
import yaml

from lsim.ack_mac import AckSort, AckTiming, plan_acks
from lsim.fcnt import (MAX_FCNT_GAP, MODULUS_32, CounterSeries, CounterVerdict,
                       DownlinkCounters, on_air)
from lsim.scenario import load_scenario
from lsim.trace_events import DeviceRadio, ProtocolOptions, TxRecord, build_trace

EXEMPLES = "docs/exemples"


def _radio():
    return DeviceRadio(freq_hz=868_100_000, dr=3, rx1_hz=868_100_000)


def _record(start_ns, end_ns, rssi=-70.0, device=0):
    return TxRecord(device, start_ns, end_ns, 9, rssi, 2)


# --- primitives ---------------------------------------------------------------------------------

def test_a_consumed_counter_is_a_replay():
    serie = CounterSeries(start=0).accept(7)
    assert serie.last == 7
    assert serie.reconstruct(7).verdict is CounterVerdict.REPLAY
    assert serie.accepts(7).verdict is CounterVerdict.REPLAY
    assert serie.accepts(6).verdict is CounterVerdict.REPLAY
    # Une valeur inférieure au départ de la session n'est pas authentique non plus.
    assert CounterSeries(start=10).accepts(9).verdict is CounterVerdict.REPLAY


def test_the_gap_boundary_is_the_specification_value():
    serie = CounterSeries(start=0, last=100)
    assert MAX_FCNT_GAP == 16_384
    assert serie.accepts(100 + MAX_FCNT_GAP).verdict is CounterVerdict.OK
    assert serie.accepts(100 + MAX_FCNT_GAP + 1).verdict is CounterVerdict.GAP
    # La désynchronisation ne fait pas avancer la série : le compteur reste exigible.
    assert serie.accept(100 + MAX_FCNT_GAP + 1).last == 100


def test_a_series_ends_at_two_to_the_thirty_two():
    serie = CounterSeries(start=MODULUS_32 - 2)
    assert serie.next_value == MODULUS_32 - 2
    serie = serie.accept(MODULUS_32 - 2)
    assert serie.next_value == MODULUS_32 - 1
    serie = serie.accept(MODULUS_32 - 1)
    assert serie.exhausted and serie.next_value is None
    assert serie.accepts(MODULUS_32).verdict is CounterVerdict.EXHAUSTED
    assert serie.reconstruct(0).verdict is CounterVerdict.EXHAUSTED


def test_the_sixteen_bit_field_wraps_once():
    # 65 535 puis 65 536 : le champ redescend à 0, le compteur 32 bits monte.
    serie = CounterSeries(start=0)
    for valeur in (65_534, 65_535):
        serie = serie.accept(valeur)
    controle = serie.reconstruct(0)
    assert controle.verdict is CounterVerdict.OK
    assert controle.counter32 == 65_536
    assert on_air(controle.counter32) == 0
    # Et le même champ, une fois accepté, est un doublon.
    assert serie.accept(65_536).reconstruct(0).verdict is CounterVerdict.REPLAY
    # Une série qui démarre au-delà du premier tour de 16 bits se replace correctement.
    assert CounterSeries(start=70_000).reconstruct(on_air(70_000)).counter32 == 70_000
    # Champ hors de [0, 65 536) : refusé, pas interprété.
    with pytest.raises(ValueError):
        serie.reconstruct(70_000)


def test_the_two_downlink_series_do_not_move_together():
    compteurs = DownlinkCounters.starting_at(0)
    controle, compteurs = compteurs.accept(True, 0)      # NFCntDown = 0
    assert controle.verdict is CounterVerdict.OK
    assert (compteurs.nf.last, compteurs.af.last) == (0, None)
    # La première descente applicative reste à 0 : les deux séries sont indépendantes.
    controle, compteurs = compteurs.accept(False, 0)
    assert controle.verdict is CounterVerdict.OK
    assert (compteurs.nf.last, compteurs.af.last) == (0, 0)
    # Un rejeu en NF ne consomme rien en AF.
    controle, compteurs = compteurs.accept(True, 0)
    assert controle.verdict is CounterVerdict.REPLAY
    assert (compteurs.nf.last, compteurs.af.last) == (0, 0)
    assert compteurs.name(True) == "NF" and compteurs.name(False) == "AF"


# --- plan des ACK -------------------------------------------------------------------------------

def test_a_copy_is_a_replay_not_a_gap():
    """La copie porte le même champ 16 bits : c'est un rejeu, pas un saut de 65 536."""
    records = (_record(0, 100_000_000),)
    plan = plan_acks(records, (_radio(),), ProtocolOptions(), AckTiming(repetitions=2))
    assert [e.sort for e in plan.outcomes[0].emissions] == [AckSort.STANDARD, AckSort.DUPLICATE]
    assert plan.outcomes[0].counter is CounterVerdict.OK
    assert plan.counts.duplicate == 1 and plan.counts.gap == 0


def test_an_exhausted_series_emits_no_ack():
    """Dernier compteur possible : un ACK ; le suivant ne peut plus être numéroté."""
    fin = MODULUS_32 - 1
    records = (_record(0, 100_000_000), _record(5_000_000_000, 5_100_000_000))
    plan = plan_acks(records, (_radio(), _radio()), ProtocolOptions(), AckTiming(),
                     fcnt_down_start=fin)
    premier, second = plan.outcomes
    assert premier.sort is AckSort.STANDARD and premier.f_cnt_down == fin
    assert second.sort is AckSort.NOT_SENT and second.emissions == ()
    assert second.counter is CounterVerdict.EXHAUSTED
    assert plan.counts.not_sent == 1 and plan.counts.emissions == 1


def test_a_retransmission_consumes_a_new_downlink_counter():
    """Deux tentatives de la même trame : même `FCntUp`, deux descentes numérotées."""
    records = (_record(0, 100_000_000), _record(3_000_000_000, 3_100_000_000))
    plan = plan_acks(records, (_radio(), _radio()), ProtocolOptions(), AckTiming(),
                     fcnt_up=(4, 4))
    premier, second = plan.outcomes
    assert (premier.f_cnt_up, second.f_cnt_up) == (4, 4)
    assert (premier.f_cnt_down, second.f_cnt_down) == (0, 1)
    assert premier.received and second.received
    assert plan.counts.standard == 2 and plan.counts.duplicate == 0


def test_a_scenario_can_start_its_downlink_series():
    """Classe C : les deux ACK sont reçus, donc leurs compteurs apparaissent dans les tentatives."""
    trace = _trace("retransmissions_ack_tardif.yaml", fcnt_down_start=1000, device_class="C")
    assert trace.retransmissions.ack_gap == 0
    assert trace.retransmissions.acks_planned == 2
    valeurs = [a.f_cnt_down for a in trace.retransmissions.attempts if a.f_cnt_down is not None]
    assert valeurs == [1000, 1001]
    # Sans le réglage, la même exécution numérote à partir de zéro.
    assert [a.f_cnt_down for a in _trace("retransmissions_ack_tardif.yaml",
                                         device_class="C").retransmissions.attempts
            if a.f_cnt_down is not None] == [0, 1]


def _trace(nom, device_class="A", **reglages):
    data = yaml.safe_load(open(f"{EXEMPLES}/{nom}", encoding="utf-8"))
    data["retransmissions"].update(reglages)
    data["groups"][0]["device_class"] = device_class
    return build_trace(load_scenario(yaml.safe_dump(data)))


def test_the_start_does_not_change_the_hash_at_its_default():
    data = yaml.safe_load(open(f"{EXEMPLES}/retransmissions_ack_tardif.yaml", encoding="utf-8"))
    sans = load_scenario(yaml.safe_dump(data))
    data["retransmissions"]["fcnt_down_start"] = 0
    avec = load_scenario(yaml.safe_dump(data))
    assert sans.sha256 == avec.sha256, "un champ à sa valeur par défaut ne doit pas entrer dans le hash"
    data["retransmissions"]["fcnt_down_start"] = 7
    assert load_scenario(yaml.safe_dump(data)).sha256 != sans.sha256


def test_the_retransmission_result_exposes_the_gap_counter():
    trace = _trace("retransmissions_ack_tardif.yaml", fcnt_down_start=0)
    assert trace.retransmissions.ack_gap == 0
    total = (trace.retransmissions.ack_standard + trace.retransmissions.ack_late
             + trace.retransmissions.ack_lost + trace.retransmissions.ack_duplicate
             + trace.retransmissions.ack_gap)
    assert total == trace.retransmissions.acks_planned
