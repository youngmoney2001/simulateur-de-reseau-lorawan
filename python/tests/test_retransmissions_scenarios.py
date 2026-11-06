"""Scénarios de validation des retransmissions, pilotés par le YAML.

Huit situations sont couvertes. Trois le sont par des fichiers d'exemple exécutables
(`docs/exemples/retransmissions_*.yaml`) : le scénario est la source de vérité, pas le test.
Les autres sont construites dans ce fichier, faute d'un modèle de trame ACK complet dans le cœur.

| Cas | Support |
|---|---|
| 1. uplink reçu, ACK reçu → aucune réémission | YAML `retransmissions_nominal` |
| 2. uplink perdu → réémission → livraison | YAML `retransmissions_collision` |
| 3. uplink reçu, ACK perdu → réémission sans double livraison | YAML `retransmissions_doublons` |
| 4. ACK tardif | décision, sur des événements réels décalés |
| 5. ACK dupliqué | décision, sur des événements réels dupliqués |
| 6. collision pendant une réémission | scénario dense (graine 1) |
| 7. rapport cyclique dépassé | YAML `retransmissions_collision`, groupe `limite` |
| 8. limite de tentatives atteinte | scénarios 2 et 6 |

Les cas 4 et 5 sont validés à deux niveaux. Au niveau de la décision d'abord, sur des événements
réels décalés ou dupliqués. De bout en bout ensuite : `DownlinkScheduler` du cœur place toujours la
descente à `fin + RECEIVE_DELAY1` et n'émet qu'un ACK par trame reçue, donc il ne peut produire ni
ACK tardif ni ACK dupliqué ; la couche `lsim.ack_mac` les produit à sa place, en réutilisant la
sensibilité et l'airtime du cœur (`_downlink_airtime_ns`, `receiver_sensitivity_dbm`), et
`build_trace` l'expose par `ack_delay_ms` / `ack_repetitions`. Le cœur C++ reste inchangé.
"""

import pytest

from lsim.retransmissions import (
    RX1_DELAY_NS,
    RX1_WINDOW_NS,
    AckReception,
    DownlinkDelivery,
    RetransmissionOptions,
    _match_ack,
    simulate_confirmed_uplinks,
)
from lsim.scenario import Scenario, ScenarioModel, load_scenario
from lsim.trace_events import ProtocolOptions, build_trace, device_radios

EXEMPLES = "docs/exemples"


def _run(yaml_name, retries=None, device_rx_offset_db=0.0, **kwargs):
    """Charge un exemple YAML, le simule, et renvoie (scénario, résultat de réémission)."""
    scenario = load_scenario(f"{EXEMPLES}/{yaml_name}.yaml")
    devices, _noms, _idx = scenario.deploy()
    options = scenario.model.retransmissions.options()
    if retries is not None:
        options = RetransmissionOptions(enabled=options.enabled, retries=retries,
                                        retransmit_delay_ms=options.retransmit_delay_ms,
                                        enforce_duty_cycle=options.enforce_duty_cycle)
    resultat = simulate_confirmed_uplinks(
        devices, scenario.gateway(), scenario.propagation(), device_radios(scenario),
        ProtocolOptions(device_rx_offset_db=device_rx_offset_db), options,
        with_engine_output=True, **kwargs)
    return scenario, resultat


# --- cas 1 ----------------------------------------------------------------------------------

def test_case_1_received_uplink_with_received_ack_is_not_retransmitted():
    _scenario, res = _run("retransmissions_nominal")
    assert res.transmissions == res.frames == 2
    assert res.retransmissions == 0
    assert res.frames_delivered == 2
    assert all(a.attempt == 0 and a.received and a.acked for a in res.attempts)
    assert all(a.ack is AckReception.RECEIVED for a in res.attempts)


# --- cas 2, 7, 8 ----------------------------------------------------------------------------

def test_case_2_a_lost_uplink_is_retransmitted_then_delivered():
    _scenario, res = _run("retransmissions_collision")
    assert res.frames == 2
    # Les deux terminaux émettent à l'instant 0 : les deux trames sont perdues.
    premieres = [a for a in res.attempts if a.attempt == 0]
    assert len(premieres) == 2 and not any(a.received for a in premieres)
    assert all(a.delivery is DownlinkDelivery.NONE for a in premieres)
    # Une seule réémission a lieu : celle du terminal non bridé ; elle est reçue et acquittée.
    secondes = [a for a in res.attempts if a.attempt == 1]
    assert len(secondes) == 1
    assert secondes[0].received and secondes[0].acked
    assert res.frames_delivered == 1


def test_case_7_the_duty_cycle_refuses_the_retransmission():
    _scenario, res = _run("retransmissions_collision")
    assert res.blocked_by_duty_cycle == 1
    # Le terminal bridé n'a qu'une transmission : sa réémission a été refusée, pas forcée.
    par_terminal: dict[int, int] = {}
    for a in res.attempts:
        par_terminal[a.device] = par_terminal.get(a.device, 0) + 1
    assert sorted(par_terminal.values()) == [1, 2]


def test_case_8_the_attempt_bound_is_respected_exactly():
    # Scénario dense : la borne est effectivement atteinte par certaines trames.
    _scenario, res = _run("retransmissions_ack_perdu", retries=2, device_rx_offset_db=10.0)
    par_trame: dict[tuple[int, int], int] = {}
    for a in res.attempts:
        cle = (a.device, a.frame)
        par_trame[cle] = par_trame.get(cle, 0) + 1
    assert max(par_trame.values()) == 3          # 1 émission + 2 réémissions, jamais plus
    # Aucune trame n'est abandonnée avant sa borne : toutes ont 1 à 3 essais.
    assert min(par_trame.values()) >= 1
    assert len(par_trame) == res.frames


# --- cas 3 ----------------------------------------------------------------------------------

def test_case_3_a_lost_ack_causes_retransmission_without_double_delivery():
    """Uplink reçu, ACK perdu : la trame est réémise, reçue deux fois, livrée une seule."""
    _scenario, res = _run("retransmissions_ack_perdu", device_rx_offset_db=10.0)
    # Des ACK sont perdus alors que les uplinks sont passés.
    assert res.acks_received < res.received
    # Les trames correspondantes sont réémises et reçues une seconde fois : doublons réels.
    assert res.duplicates >= 5
    # Le réseau déduplique : moins de trames distinctes que de réceptions.
    assert res.network_frames == res.received - res.duplicates
    assert res.network_frames <= res.frames


def test_without_a_degraded_receiver_no_ack_is_ever_lost():
    """Fait mesuré, contre-intuitif : récepteur nominal ⇒ aucune perte d'ACK.

    Le planificateur causal livre l'ACK de toute trame qu'il reçoit. Tant que ce n'est pas modélisé
    autrement, une perte d'ACK n'existe que si le bilan descendant est dégradé — c'est pourquoi le
    scénario de duplication exige une hypothèse de récepteur explicite.
    """
    _scenario, res = _run("retransmissions_ack_perdu")
    assert res.received == res.acks_received
    assert res.duplicates == 0


def test_duplicates_are_counted_per_frame_not_per_transmission():
    _scenario, res = _run("retransmissions_ack_perdu", device_rx_offset_db=10.0)
    par_trame: dict[tuple[int, int], int] = {}
    for a in res.attempts:
        if a.received:
            cle = (a.device, a.frame)
            par_trame[cle] = par_trame.get(cle, 0) + 1
    attendu = sum(n - 1 for n in par_trame.values())
    assert res.duplicates == attendu
    assert res.network_frames == len(par_trame)


# --- cas 6 ----------------------------------------------------------------------------------

def test_case_6_a_retransmission_can_collide():
    raw = {
        "schema_version": 1, "name": "collision-réémission", "seed": 1,
        "gateway": {"x_m": 0, "y_m": 0},
        "propagation": {"frequency_hz": 868_100_000, "reference_distance_m": 1.0,
                        "exponent": 2.7, "capture_threshold_db": 6},
        "groups": [{"name": "g", "count": 6, "placement": {"type": "disk", "radius_m": 500},
                    "spreading_factor": 9, "payload_bytes": 30, "tx_power_dbm": 14,
                    "period_s": 4, "messages": 3, "start_spread_s": 12}],
    }
    scenario = Scenario(model=ScenarioModel.model_validate(raw))
    devices, _n, _i = scenario.deploy()
    res = simulate_confirmed_uplinks(devices, scenario.gateway(), scenario.propagation(),
                                     device_radios(scenario), ProtocolOptions(),
                                     RetransmissionOptions(retries=3), with_engine_output=True)
    # Une réémission perdue par collision : le verdict vient du moteur, pas du module.
    collisions = [i for i, a in enumerate(res.attempts)
                  if a.attempt > 0 and not a.received
                  and res.trace.records[i].outcome == 1]  # 1 = lost_collision
    assert collisions, "aucune réémission perdue par collision dans ce scénario"
    assert res.lost_collision >= len(collisions)


# --- cas 4 et 5 : au niveau de la décision --------------------------------------------------

def _evenements_reels():
    """Événements du moteur pour le scénario nominal, et le calendrier associé."""
    _scenario, res = _run("retransmissions_nominal")
    return res


def test_case_4_an_ack_outside_the_window_does_not_acknowledge():
    res = _evenements_reels()
    ack = [e for e in res.events if e.kind == "ack"][0]
    assert _match_ack(res.attempts, res.events), "ACK nominal non apparié"

    # Décalé après la fenêtre RX1 (+ 1 s de garde) : il ne doit plus rien acquitter.
    tardif = ack.__class__(**{**ack.__dict__,
                              "t_ns": ack.t_ns + RX1_WINDOW_NS + 1})
    assert not _match_ack(res.attempts, (tardif,)), "un ACK tardif a acquitté la trame"

    # Décalé avant l'ouverture de la fenêtre : idem.
    precoce = ack.__class__(**{**ack.__dict__, "t_ns": ack.t_ns - RX1_DELAY_NS})
    assert not _match_ack(res.attempts, (precoce,))


def test_case_5_a_duplicate_ack_acknowledges_only_once():
    res = _evenements_reels()
    ack = [e for e in res.events if e.kind == "ack"][0]
    simple = _match_ack(res.attempts, res.events)
    double = _match_ack(res.attempts, res.events + (ack,))
    # L'acquittement est un ensemble : recevoir deux fois le même ACK n'acquitte pas deux fois.
    assert double == simple
    assert sum(1 for a in res.attempts if a.acked) == len(simple)


# --- intégration YAML et build_trace --------------------------------------------------------

def test_the_yaml_block_drives_build_trace():
    scenario = load_scenario(f"{EXEMPLES}/retransmissions_doublons.yaml")
    trace = build_trace(scenario)
    assert trace.retransmissions is not None
    assert trace.retransmissions.transmissions > trace.retransmissions.frames
    # Une entrée de trace par transmission, indices physiques.
    assert len(trace.records) == trace.retransmissions.transmissions
    assert {r.device_index for r in trace.records} <= set(range(len(trace.per_device)))
    assert sum(c.sent for c in trace.per_device) == trace.retransmissions.transmissions
    assert sum(c.received for c in trace.per_device) == trace.retransmissions.received


def test_a_scenario_without_the_block_keeps_the_historic_behaviour():
    scenario = load_scenario("examples/quartier_sf9.yaml")
    assert scenario.model.retransmissions is None
    trace = build_trace(scenario)
    assert trace.retransmissions is None
    assert trace.totals.received == 4210


def test_zero_retries_is_the_engine_itself():
    """`retries: 0` n'ajoute aucune transmission : le scénario emprunte le chemin historique."""
    raw = {
        "schema_version": 1, "name": "zéro", "seed": 7, "gateway": {"x_m": 0, "y_m": 0},
        "propagation": {"frequency_hz": 868_100_000, "reference_distance_m": 1.0,
                        "exponent": 2.7, "capture_threshold_db": 6},
        "retransmissions": {"retries": 0},
        "groups": [{"name": "g", "count": 4, "placement": {"type": "disk", "radius_m": 800},
                    "spreading_factor": 9, "payload_bytes": 20, "tx_power_dbm": 14,
                    "period_s": 60, "messages": 2}],
    }
    scenario = Scenario(model=ScenarioModel.model_validate(raw))
    assert not scenario.model.retransmissions.is_active
    avec = build_trace(scenario)
    assert avec.retransmissions is None
    # Même scénario sans le bloc : trace identique, au champ près.
    sans_bloc = dict(raw)
    sans_bloc.pop("retransmissions")
    reference = build_trace(Scenario(model=ScenarioModel.model_validate(sans_bloc)))
    assert avec.totals == reference.totals
    assert [(r.device_index, r.start_ns, r.rssi_dbm, r.outcome) for r in avec.records] == \
           [(r.device_index, r.start_ns, r.rssi_dbm, r.outcome) for r in reference.records]


def test_invalid_parameters_are_refused_explicitly():
    from pydantic import ValidationError

    base = {
        "schema_version": 1, "name": "ko", "seed": 1, "gateway": {"x_m": 0, "y_m": 0},
        "propagation": {"frequency_hz": 868_100_000, "reference_distance_m": 1.0,
                        "exponent": 2.7},
        "groups": [{"name": "g", "count": 1, "placement": {"type": "disk", "radius_m": 10}}],
    }
    for bloc in ({"retries": 8}, {"retries": -1},
                 {"retransmit_delay_ms": 1_999}, {"retransmit_delay_ms": 60_001},
                 {"retries": 2, "inconnu": 1}, {"energy_profile": "inconnu"}):
        with pytest.raises(ValidationError):
            ScenarioModel.model_validate({**base, "retransmissions": bloc})


def test_the_block_is_excluded_from_the_hash_when_absent():
    base = {
        "schema_version": 1, "name": "hash", "seed": 1, "gateway": {"x_m": 0, "y_m": 0},
        "propagation": {"frequency_hz": 868_100_000, "reference_distance_m": 1.0,
                        "exponent": 2.7},
        "groups": [{"name": "g", "count": 1, "placement": {"type": "disk", "radius_m": 10}}],
    }
    sans = Scenario(model=ScenarioModel.model_validate(base))
    avec = Scenario(model=ScenarioModel.model_validate({**base, "retransmissions": {"retries": 2}}))
    assert avec.sha256 != sans.sha256
    # Et le hash sans bloc est celui d'un scénario qui n'en a jamais eu.
    assert sans.sha256 == Scenario(model=ScenarioModel.model_validate(base)).sha256


def test_the_ack_defaults_are_excluded_from_the_hash():
    """Les champs ACK à leur valeur par défaut ne changent pas le hash d'un scénario existant."""
    base = {
        "schema_version": 1, "name": "hash", "seed": 1, "gateway": {"x_m": 0, "y_m": 0},
        "propagation": {"frequency_hz": 868_100_000, "reference_distance_m": 1.0,
                        "exponent": 2.7},
        "groups": [{"name": "g", "count": 1, "placement": {"type": "disk", "radius_m": 10}}],
    }
    implicite = Scenario(model=ScenarioModel.model_validate(
        {**base, "retransmissions": {"retries": 2}}))
    explicite = Scenario(model=ScenarioModel.model_validate(
        {**base, "retransmissions": {"retries": 2, "ack_delay_ms": 0, "ack_repetitions": 1}}))
    assert explicite.sha256 == implicite.sha256
    # Une valeur non par défaut, elle, décrit un autre scénario.
    tardif = Scenario(model=ScenarioModel.model_validate(
        {**base, "retransmissions": {"retries": 2, "ack_delay_ms": 2_500}}))
    duplique = Scenario(model=ScenarioModel.model_validate(
        {**base, "retransmissions": {"retries": 2, "ack_repetitions": 2}}))
    assert tardif.sha256 != implicite.sha256
    assert duplique.sha256 != implicite.sha256
    # Référence figée : le hash de l'exemple écrit avant la couche MAC.
    assert load_scenario(f"{EXEMPLES}/retransmissions_nominal.yaml").sha256 == \
        "312a19b13190b0f9d76f0ffa677a4f44b6f7901e0501b0ebd07211eb0b11a948"


def test_the_energy_profile_of_the_scenario_is_used():
    scenario = load_scenario(f"{EXEMPLES}/retransmissions_doublons.yaml")
    devices, _n, _i = scenario.deploy()
    base = simulate_confirmed_uplinks(devices, scenario.gateway(), scenario.propagation(),
                                      device_radios(scenario), ProtocolOptions(),
                                      scenario.model.retransmissions.options())
    avec = simulate_confirmed_uplinks(devices, scenario.gateway(), scenario.propagation(),
                                      device_radios(scenario), ProtocolOptions(),
                                      scenario.model.retransmissions.options(),
                                      energy_profile="rak4631")
    assert base.energy_j == 0.0
    assert avec.energy_j > 0.0


# --- cas 4 et 5 de bout en bout : couche MAC de l'ACK ---------------------------------------

def test_case_4_a_late_ack_is_lost_end_to_end():
    """ACK émis après RX2 : transmis, consommé, jamais entendu, trame réémise jusqu'à la borne."""
    scenario = load_scenario(f"{EXEMPLES}/retransmissions_ack_tardif.yaml")
    trace = build_trace(scenario)
    res = trace.retransmissions

    assert res.frames == 2 and res.transmissions == 6      # 2 trames, 1 + 2 réémissions
    # Chaque tentative a bien déclenché un ACK : le réseau répond, mais trop tard.
    assert res.acks_planned == 6
    assert res.acks_received == 0
    assert res.frames_delivered == 0
    # L'ACK tardif occupe quand même la passerelle : c'est le coût du retard.
    assert trace.gateway_tx and len(trace.gateway_tx) == 6


def test_case_4_the_same_scenario_without_delay_delivers_everything():
    """Témoin : sans retard, le même scénario acquitte toutes ses trames. Le retard est la cause."""
    scenario = load_scenario(f"{EXEMPLES}/retransmissions_ack_tardif.yaml")
    devices, _n, _i = scenario.deploy()
    sans_retard = simulate_confirmed_uplinks(
        devices, scenario.gateway(), scenario.propagation(), device_radios(scenario),
        ProtocolOptions(), RetransmissionOptions(retries=2, ack_delay_ms=0))
    assert sans_retard.transmissions == 2
    assert sans_retard.acks_received == 2
    assert sans_retard.frames_delivered == 2


def test_case_4_a_moderate_delay_lands_in_rx2_and_is_received():
    scenario = load_scenario(f"{EXEMPLES}/retransmissions_ack_tardif.yaml")
    devices, _n, _i = scenario.deploy()
    for retard, fenetre in ((1_000, "rx2"), (1_500, "rx2")):
        res = simulate_confirmed_uplinks(
            devices, scenario.gateway(), scenario.propagation(), device_radios(scenario),
            ProtocolOptions(), RetransmissionOptions(retries=2, ack_delay_ms=retard))
        assert res.acks_received == res.frames, (retard, res)
        assert res.transmissions == res.frames


def test_case_5_a_duplicated_ack_acknowledges_once_end_to_end():
    """ACK émis deux fois : deux réceptions, **un seul** acquittement, aucune réémission."""
    scenario = load_scenario(f"{EXEMPLES}/retransmissions_ack_duplique.yaml")
    trace = build_trace(scenario)
    res = trace.retransmissions

    assert res.frames == 2
    assert res.transmissions == 2                 # aucun doublon d'uplink provoqué
    assert res.acks_planned == 4                  # deux émissions d'ACK par trame
    assert res.acks_received == 2                 # une par trame
    assert res.ack_duplicates_ignored == 2        # la seconde copie est écartée
    assert res.frames_delivered == 2
    assert res.duplicates == 0                    # et aucune duplication d'uplink côté réseau


def test_case_5_the_duplicate_costs_airtime():
    """Témoin : la répétition n'est pas gratuite, elle consomme la passerelle."""
    scenario = load_scenario(f"{EXEMPLES}/retransmissions_ack_duplique.yaml")
    devices, _n, _i = scenario.deploy()
    simple = simulate_confirmed_uplinks(
        devices, scenario.gateway(), scenario.propagation(), device_radios(scenario),
        ProtocolOptions(), RetransmissionOptions(retries=2, ack_repetitions=1))
    double = simulate_confirmed_uplinks(
        devices, scenario.gateway(), scenario.propagation(), device_radios(scenario),
        ProtocolOptions(), RetransmissionOptions(retries=2, ack_repetitions=2))
    assert double.acks_planned == 2 * simple.acks_planned
    assert double.ack_duplicates_ignored == double.acks_received
    assert double.gateway_utilization >= simple.gateway_utilization


def test_the_ack_mac_layer_reproduces_the_core_when_left_at_defaults():
    """Parité : à retard nul et sans répétition, la couche MAC redonne l'occupation du cœur."""
    from lsim.ack_mac import AckTiming, plan_acks
    from lsim.downlink_plan import simulate_causal

    for exemple in ("retransmissions_nominal", "retransmissions_collision"):
        scenario = load_scenario(f"{EXEMPLES}/{exemple}.yaml")
        devices, _n, _i = scenario.deploy()
        radios = device_radios(scenario)
        options = ProtocolOptions(confirmed_uplinks=True)
        _res, busy_moteur = simulate_causal(devices, scenario.gateway(),
                                            scenario.propagation(), None, radios, options)
        resultat, _ = simulate_causal(devices, scenario.gateway(), scenario.propagation(), None,
                                      radios, options)
        radios_par_enregistrement = [radios[r.device_index] for r in resultat.records]
        plan = plan_acks(resultat.records, radios_par_enregistrement, options, AckTiming())
        assert sorted(plan.busy) == sorted(busy_moteur), exemple
        assert plan.received == sum(1 for r in resultat.records if r.outcome == 2)


# --- réserve 2 : la dégradation du récepteur n'affecte que la descente ----------------------

def test_receiver_degradation_only_affects_the_downlink():
    """`device_rx_offset_db` dégrade la réception **descendante** et rien d'autre.

    Contrôle direct : à entrée identique, toutes les émissions montantes (instant, RSSI, issue)
    doivent être identiques quel que soit l'écart, et seuls les ACK changent.
    """
    from lsim.downlink_plan import simulate_causal

    scenario = load_scenario(f"{EXEMPLES}/retransmissions_ack_perdu.yaml")
    devices, _n, _i = scenario.deploy()
    radios = device_radios(scenario)

    empreintes = []
    for offset in (0.0, 5.0, 10.0, 20.0):
        resultat, _busy = simulate_causal(devices, scenario.gateway(), scenario.propagation(),
                                          None, radios,
                                          ProtocolOptions(confirmed_uplinks=True,
                                                          device_rx_offset_db=offset))
        empreintes.append(tuple((r.device_index, r.start_ns, r.end_ns, round(r.rssi_dbm, 9),
                                 r.outcome) for r in resultat.records))
    # Une seule empreinte distincte : le montant est strictement insensible à l'écart.
    assert len(set(empreintes)) == 1


def test_receiver_degradation_changes_the_ack_reception():
    """Contrepartie du test précédent : lui, il change bien quelque chose — la descente."""
    scenario = load_scenario(f"{EXEMPLES}/retransmissions_ack_perdu.yaml")
    devices, _n, _i = scenario.deploy()
    radios = device_radios(scenario)
    mesures = []
    for offset in (0.0, 10.0):
        res = simulate_confirmed_uplinks(devices, scenario.gateway(), scenario.propagation(),
                                         radios, ProtocolOptions(device_rx_offset_db=offset),
                                         RetransmissionOptions(retries=3))
        mesures.append((res.received, res.acks_received))
    # Les réémissions diffèrent d'un cas à l'autre : on ne compare donc que les ACK, seule
    # grandeur censée dépendre de l'écart de réception descendante.
    assert mesures[0][1] > mesures[1][1]


def test_receiver_degradation_never_touches_the_uplink_budget():
    """Vérification par la porte d'entrée du module : mêmes uplinks initiaux, mêmes issues."""
    scenario = load_scenario(f"{EXEMPLES}/retransmissions_ack_perdu.yaml")
    devices, _n, _i = scenario.deploy()
    radios = device_radios(scenario)
    initiaux = []
    for offset in (0.0, 20.0):
        res = simulate_confirmed_uplinks(devices, scenario.gateway(), scenario.propagation(),
                                         radios, ProtocolOptions(device_rx_offset_db=offset),
                                         RetransmissionOptions(retries=0))
        initiaux.append(tuple((a.device, a.frame, a.start_ns, a.end_ns, a.received)
                              for a in res.attempts))
    assert initiaux[0] == initiaux[1]
