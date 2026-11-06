"""Consolidation MAC de l'ACK : compteurs, taxonomie, classes d'écoute, cohérence des traces.

Ces tests portent sur le quatrième incrément (après la couche ACK elle-même) :

| Sujet | Ce qui est vérifié |
|---|---|
| identité | `FCntUp` identifie la trame, pas la tentative ; les réémissions le partagent |
| série descendante | `FCntDown` est **par terminal**, commence à 0 et croît d'un ACK émis par trame |
| taxonomie | standard / tardif / perdu / dupliqué partitionnent les émissions, sans recouvrement |
| classes | A et B écoutent RX1/RX2, C écoute en continu ; le montant ne dépend pas de la classe |
| cohérence | chaque ACK émis par la couche est dans l'occupation passerelle de la trace |
| hash | les nouveaux champs à leur valeur par défaut ne changent aucun hash existant |
"""

import pytest
from pydantic import ValidationError

from lsim.ack_mac import AckSort
from lsim.retransmissions import (
    AckReception,
    RetransmissionOptions,
    RetransmissionResult,
    simulate_confirmed_uplinks,
)
from lsim.scenario import Scenario, ScenarioModel, load_scenario
from lsim.trace_events import ProtocolOptions, build_trace, device_radios

EXEMPLES = "docs/exemples"
BASE = {
    "schema_version": 1, "name": "consolidation", "seed": 1,
    "gateway": {"x_m": 0, "y_m": 0},
    "propagation": {"frequency_hz": 868_100_000, "reference_distance_m": 1.0, "exponent": 2.7,
                    "capture_threshold_db": 6},
    "groups": [{"name": "terminal", "count": 1,
                "placement": {"type": "explicit", "positions": [[100.0, 0.0]]},
                "spreading_factor": 9, "payload_bytes": 12, "tx_power_dbm": 14,
                "period_s": 60, "messages": 2, "start_spread_s": 10}],
    "retransmissions": {"retries": 2},
}


def _scenario(**retransmissions):
    """Scénario minimal à deux messages ; les réglages ACK sont passés en arguments."""
    data = {**BASE, "retransmissions": {**BASE["retransmissions"], **retransmissions}}
    return load_scenario(__import__("yaml").safe_dump(data))


def _resultat(**retransmissions):
    scenario = _scenario(**retransmissions)
    devices, _noms, _idx = scenario.deploy()
    return simulate_confirmed_uplinks(
        devices, scenario.gateway(), scenario.propagation(), device_radios(scenario),
        ProtocolOptions(), scenario.model.retransmissions.options())


# --- identité de trame -----------------------------------------------------------------------

def test_fcnt_up_identifies_the_frame_not_the_attempt():
    """Deux trames, un compteur qui ne repart pas de zéro : l'identité n'est pas un rang."""
    resultat = _resultat(ack_delay_ms=2500, fcnt_up_start=1000)
    par_trame: dict[int, set] = {}
    for attempt in resultat.attempts:
        par_trame.setdefault(attempt.frame, set()).add(attempt.f_cnt_up)
    assert sorted(par_trame) == [0, 1]
    # Toutes les réémissions d'une trame portent le même compteur, et un seul.
    assert all(len(compteurs) == 1 for compteurs in par_trame.values())
    assert [next(iter(par_trame[t])) for t in (0, 1)] == [1000, 1001]
    # Une réémission existe bien : sans elle, le test ne prouverait rien sur le partage.
    assert resultat.retransmissions == 4


def test_fcnt_down_is_a_per_device_series():
    """`FCntDown` est une série par terminal : deux terminaux ont chacun la leur."""
    data = {**BASE,
            "groups": [{**BASE["groups"][0], "count": 2,
                        "placement": {"type": "explicit", "positions": [[100.0, 0.0], [120.0, 0.0]]}}],
            "retransmissions": {"retries": 0}}
    scenario = load_scenario(__import__("yaml").safe_dump(data))
    devices, _noms, _idx = scenario.deploy()
    resultat = simulate_confirmed_uplinks(
        devices, scenario.gateway(), scenario.propagation(), device_radios(scenario),
        ProtocolOptions(), scenario.model.retransmissions.options())
    series: dict[int, list[int]] = {}
    for attempt in resultat.attempts:
        if attempt.ack is AckReception.RECEIVED:
            series.setdefault(attempt.device, []).append(attempt.f_cnt_down)
    assert sorted(series) == [0, 1]
    for compteurs in series.values():
        assert compteurs == [0, 1]        # chaque série repart de zéro, indépendamment


def test_the_ack_frame_carries_the_real_identity():
    resultat = _resultat(ack_delay_ms=0, fcnt_up_start=7)
    recus = [a for a in resultat.attempts if a.ack is AckReception.RECEIVED]
    assert recus, "aucun ACK reçu : le test ne prouverait rien"
    for attempt in recus:
        frame = attempt.ack_frame
        assert frame is not None and frame.is_explicit
        assert frame.frame_counter_up == attempt.f_cnt_up
        assert frame.frame_counter_down == attempt.f_cnt_down


# --- taxonomie --------------------------------------------------------------------------------

def test_the_taxonomy_partitions_every_emission():
    """Chaque émission tombe dans exactement une classe ; la somme égale les ACK émis."""
    for reglages in ({"ack_delay_ms": 2500}, {"ack_delay_ms": 0}, {"ack_repetitions": 2}):
        resultat = _resultat(**reglages)
        total = (resultat.ack_standard + resultat.ack_late + resultat.ack_lost
                 + resultat.ack_duplicate)
        assert total == resultat.acks_planned, reglages
        assert resultat.ack_not_sent <= resultat.frames


def test_a_repeated_ack_is_rejected_by_the_downlink_counter():
    """Deux copies, même `FCntDown` : la seconde est un doublon, pas un second acquittement."""
    simple = _resultat(ack_repetitions=1)
    double = _resultat(ack_repetitions=2)
    assert double.acks_planned == 2 * simple.acks_planned
    assert double.ack_standard == simple.ack_standard
    assert double.ack_duplicate == simple.acks_planned
    assert double.ack_duplicates_ignored == double.ack_duplicate
    assert double.frames_delivered == simple.frames_delivered
    # Les copies partagent bien le compteur descendant de leur ACK.
    par_uplink = {}
    for attempt in double.attempts:
        if attempt.ack is AckReception.RECEIVED:
            par_uplink.setdefault(attempt.frame, set()).add(attempt.f_cnt_down)
    assert all(len(valeurs) == 1 for valeurs in par_uplink.values())


def test_a_late_ack_is_neither_standard_nor_lost():
    resultat = _resultat(ack_delay_ms=2500)
    assert resultat.ack_late == resultat.acks_planned > 0
    assert resultat.ack_standard == 0
    assert resultat.ack_lost == 0


# --- classes d'écoute --------------------------------------------------------------------------

def _avec_classe(classe, **retransmissions):
    data = {**BASE, "retransmissions": {**BASE["retransmissions"], **retransmissions}}
    data["groups"] = [{**BASE["groups"][0], "device_class": classe}]
    return load_scenario(__import__("yaml").safe_dump(data))


def test_class_c_hears_a_late_ack_that_class_a_misses():
    """Même scénario, même retard : seule la règle d'écoute change, et elle change tout."""
    resultats = {}
    for classe in ("A", "B", "C"):
        scenario = _avec_classe(classe, ack_delay_ms=2500)
        resultats[classe] = build_trace(scenario).retransmissions
    assert resultats["A"].frames_delivered == 0
    assert resultats["A"].ack_late == 6
    assert resultats["B"].frames_delivered == 0     # l'ACK est une descente de classe A
    assert resultats["B"].ack_late == 6
    assert resultats["C"].frames_delivered == 2
    assert resultats["C"].ack_standard == 2


def test_the_device_class_only_changes_the_ack_reception():
    """À calendrier identique, la classe ne déplace aucune émission montante.

    Les émissions **initiales** fixent le calendrier ; les réémissions, elles, dépendent
    légitimement de l'ACK reçu — c'est la boucle de bout en bout, pas une fuite de la règle
    d'écoute dans la radio.
    """
    empreintes, livrees = [], []
    for classe in ("A", "B", "C"):
        scenario = _avec_classe(classe, ack_delay_ms=2500)
        resultat = build_trace(scenario).retransmissions
        empreintes.append(tuple((a.device, a.frame, a.start_ns, a.end_ns)
                                for a in resultat.attempts if a.attempt == 0))
        livrees.append(resultat.frames_delivered)
    assert len(set(empreintes)) == 1       # mêmes uplinks, mêmes instants
    assert livrees == [0, 0, 2]            # seule la réception de l'ACK change


def test_an_unknown_device_class_is_refused():
    data = {**BASE, "groups": [{**BASE["groups"][0], "device_class": "D"}]}
    with pytest.raises(ValidationError):
        ScenarioModel.model_validate(data)


# --- cohérence des traces ----------------------------------------------------------------------

def test_every_ack_emission_is_in_the_gateway_occupancy():
    """Ce que la couche MAC émet apparaît dans l'occupation de la trace, sans trou."""
    scenario = _scenario(ack_delay_ms=2500)
    trace = build_trace(scenario)
    resultat = trace.retransmissions
    assert resultat.gateway_tx, "aucune occupation : le test ne prouverait rien"
    assert all(fin > debut for debut, fin in resultat.gateway_tx)
    # 6 ACK tardifs émis ⇒ 6 intervalles d'occupation pour un terminal unique.
    assert len(resultat.gateway_tx) == resultat.acks_planned == 6


def test_the_taxonomy_counts_reach_the_trace():
    scenario = _scenario(ack_repetitions=2)
    trace = build_trace(scenario)
    resultat = trace.retransmissions
    assert resultat.ack_standard == 2
    assert resultat.ack_duplicate == 2
    assert resultat.ack_duplicates_ignored == 2


# --- validation et stabilité du hash -----------------------------------------------------------

def test_the_counters_are_validated():
    with pytest.raises(ValidationError):
        ScenarioModel.model_validate({**BASE, "retransmissions": {"fcnt_up_start": -1}})
    with pytest.raises(ValidationError):
        ScenarioModel.model_validate({**BASE, "retransmissions": {"fcnt_up_start": 2**32}})
    with pytest.raises(ValueError):
        RetransmissionOptions(fcnt_up_start=-1)


def test_the_new_defaults_are_excluded_from_the_hash():
    implicite = Scenario(model=ScenarioModel.model_validate(BASE))
    explicite = Scenario(model=ScenarioModel.model_validate(
        {**BASE, "retransmissions": {**BASE["retransmissions"], "fcnt_up_start": 0,
                                     "ack_delay_ms": 0, "ack_repetitions": 1},
         "groups": [{**BASE["groups"][0], "device_class": "A"}]}))
    assert implicite.sha256 == explicite.sha256
    # Et les exemples écrits avant ces champs gardent leur empreinte.
    assert load_scenario(f"{EXEMPLES}/retransmissions_ack_tardif.yaml").sha256 == \
        "cee60ffc20154e7b34419b7f47b5c317702fb39f3bfe02928bf3fd1004805a49"
    # Une valeur non par défaut décrit un autre scénario.
    autre = Scenario(model=ScenarioModel.model_validate(
        {**BASE, "retransmissions": {**BASE["retransmissions"], "fcnt_up_start": 1000}}))
    assert autre.sha256 != implicite.sha256
    classe_c = Scenario(model=ScenarioModel.model_validate(
        {**BASE, "groups": [{**BASE["groups"][0], "device_class": "C"}]}))
    assert classe_c.sha256 != implicite.sha256
