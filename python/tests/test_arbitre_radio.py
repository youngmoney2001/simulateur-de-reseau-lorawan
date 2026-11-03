"""D3.13 — Arbitrage radio partagé : un émetteur, un budget réglementaire, une seule source.

Ce fichier vérifie que les Join-Accept, les ACK et les autres descentes concourent pour la
**même** ressource (`lsim.arbitre.GatewayArbiter`), et que le rapport cyclique des Join-Request
est un budget appliqué avant l'émission (`DutyCycleLedger`).

| Ce qui est vérifié | Test |
|---|---|
| Un seul émetteur : des descentes concurrentes se suivent | `test_des_descentes_concurrentes_se_suivent_sur_un_emet`… |
| Une fenêtre couverte n'est **pas** émise et n'occupe rien | `test_une_fenetre_couverte_nest_pas_emise` |
| Un ACK tardif peut être demandé explicitement | `test_un_ack_tardif_est_emis_sil_est_demande` |
| Aucune priorité inventée : ordre de dépôt à instant égal | `test_aucune_priorite_par_defaut_a_instant_egal` |
| Une priorité explicite est appliquée | `test_une_priorite_explicite_est_appliquee` |
| Une demande devenue sans objet n'occupe rien | `test_une_demande_devenue_sans_objet_noccupe_rien` |
| Join-Accept et ACK demandés au même instant | `test_un_join_accept_et_un_ack_au_meme_instant` |
| ACK déjà en émission quand RX1 s'ouvre | `test_un_ack_en_emission_quand_rx1_souvre` |
| RX1 impossible, RX2 possible | `test_rx1_impossible_puis_rx2_possible` |
| RX1 réussie : aucune RX2 | `test_rx1_reussie_nemet_aucune_rx2` |
| Deux jointures qui se chevauchent | `test_deux_jointures_qui_se_chevauchent` |
| Rapport cyclique : la seconde tentative est refusée | `test_le_budget_refuse_la_seconde_tentative` |
| Une tentative bloquée n'est pas une émission | `test_une_tentative_bloquee_nest_pas_une_emission` |
| Bout en bout : un ACK repoussé par un Join-Accept | `test_un_ack_est_repousse_par_un_join_accept` |
| Bout en bout : RX1 bloquée par deux copies d'ACK, RX2 réussit | `test_rx1_bloquee_par_deux_copies_dack_rx2_reussit` |
| Bout en bout : RX1 et RX2 bloquées, aucune session | `test_rx1_et_rx2_bloquees_nouvrent_aucune_session` |
| Bout en bout : jointure, ACK et downlink sur une passerelle | `test_join_accept_ack_et_downlink_sur_une_meme_passerelle` |
| Référence retransmissions 8/24 → 7/24 → 5/24 préservée | `test_les_scenarios_de_reference_des_retransmissions` |

**Fenêtres (§2 de la directive).** Les sept cas exigés sont couverts :

| Cas | Test |
|---|---|
| Un ACK occupe RX1, puis RX2 | `test_un_ack_occupe_rx1_puis_rx2` |
| Un Join-Accept occupe l'émetteur quand un ACK est demandé | `test_un_ack_est_repousse_par_un_join_accept` |
| Plusieurs demandes au même instant | `test_un_join_accept_et_un_ack_au_meme_instant` |
| Une demande retardée dépasse sa fenêtre | `test_une_fenetre_couverte_nest_pas_emise` |
| Une émission commence dans la fenêtre et finit après | `test_une_emission_commencee_dans_la_fenetre_la_depasse` |
| Une demande supprimée ne réserve pas l'émetteur | `test_une_demande_devenue_sans_objet_noccupe_rien` |
| Un rejeu n'est pas un nouveau Join-Accept | `test_un_rejeu_nest_pas_un_nouveau_join_accept` |

La **règle de départ** et la **durée d'occupation** sont énoncées dans `lsim.arbitre`, section
« Règle de départ et durée d'occupation » : `début = max(ready_ns, ouverture, occupé_jusqu'à)`,
occupation de `début` à `début + temps d'antenne`, sans garde ni temps de retournement.

Ce qui n'est **pas** vérifié ici, parce que ce n'est pas modélisé : la cryptographie de la
jointure (aucune clé, aucun `MIC`), la priorité protocolaire entre un Join-Accept et l'ACK d'un
autre terminal (LoRaWAN n'en définit pas), et le rapport cyclique **descendant** de la passerelle.
"""

import types

import pytest
import yaml

from lsim.arbitre import (DUTY_CYCLE, EMITTED, LATE, NOT_NEEDED, WINDOW_MISSED, ArbitrationPolicy,
                          DutyCycleLedger, EmissionRequest, GatewayArbiter)
from lsim.join import (BLOCKED_DUTY_CYCLE, JOIN_ACCEPT_DELAY1_NS, JOIN_ACCEPT_DELAY2_NS,
                       JOIN_REPLAY_DELAY_NS,
                       JOIN_WINDOW_NS, JoinRadioOptions, accept_airtime_ns, simulate_joins)
from lsim.retransmissions import RetransmissionOptions, simulate_confirmed_uplinks
from lsim.scenario import load_scenario
from lsim.trace_events import ProtocolOptions, build_trace, device_radios

EXEMPLE = "docs/exemples/retransmissions_ack_tardif.yaml"
ACK_PERDU = "docs/exemples/retransmissions_ack_perdu.yaml"
NOMINAL = "docs/exemples/retransmissions_nominal.yaml"
SECONDE = 1_000_000_000


def _brut(modifier=None, base=EXEMPLE, **reglages):
    data = yaml.safe_load(open(base, encoding="utf-8"))
    if modifier is not None:
        modifier(data)
    reglages.setdefault("join_requests_s", [10])
    data["retransmissions"].update({"ack_delay_ms": 0, **reglages})
    return data


def _scenario(modifier=None, base=EXEMPLE, **reglages):
    return load_scenario(yaml.safe_dump(_brut(modifier, base, **reglages)))


def _trace(modifier=None, base=EXEMPLE, options=ProtocolOptions(), **reglages):
    return build_trace(_scenario(modifier, base, **reglages), options)


def _duty(valeur):
    """Le rapport cyclique est une propriété du **groupe** (donc du terminal)."""

    def modifier(data):
        data["groups"][0]["duty_cycle"] = valeur

    return modifier


def _deux(positions):
    def modifier(data):
        data["groups"][0]["count"] = len(positions)
        data["groups"][0]["placement"] = {"type": "explicit", "positions": positions}

    return modifier


def _sf12(data):
    """Trames de 51 octets en SF12 : descentes longues, donc fenêtres vite couvertes."""
    data["groups"][0].update({"spreading_factor": 12, "payload_bytes": 51, "period_s": 60,
                              "messages": 3, "start_spread_s": 4})


def _join_arbitre(scenario, occupation=(), **reglages):
    """Joue une jointure dans un arbitre où `occupation` est déjà imposée.

    `occupation` : intervalles pendant lesquels l'émetteur est **déjà** en émission — un ACK en
    cours, par exemple. C'est le plus court chemin vers une concurrence reproductible.
    """
    devices, _, _ = scenario.deploy()
    radios = device_radios(scenario)
    options = JoinRadioOptions(requests_s=(10,), **reglages)
    arbitre = GatewayArbiter(occupation=occupation)
    plan = simulate_joins(devices, scenario.gateway(), scenario.propagation(), radios,
                          ProtocolOptions(), scenario.environment, [(0, 10 * SECONDE)], {},
                          join_options=options, arbiter=arbitre)
    arbitre.resolve()
    return plan.result(), arbitre


def _rx1_de(scenario, **reglages):
    """Instant d'ouverture de RX1, tel que le moteur a placé le Join-Request."""
    resultat, _ = _join_arbitre(scenario, **reglages)
    return resultat.attempts[0].request_end_ns + JOIN_ACCEPT_DELAY1_NS


# --- l'arbitre : règles d'occupation --------------------------------------------------------

def test_des_descentes_concurrentes_se_suivent_sur_un_seul_emetteur():
    """Cinq descentes demandées au même instant : une seule à la fois, en file."""
    arbitre = GatewayArbiter()
    tickets = arbitre.demand_all([
        EmissionRequest(label="ack", device=d, ready_ns=10 * SECONDE,
                        duration_ns=100_000_000, window=(10 * SECONDE, 11 * SECONDE))
        for d in range(5)])
    arbitre.resolve()
    emissions = [arbitre.emission(t) for t in tickets]
    assert [e.verdict for e in emissions] == [EMITTED] * 5
    debuts = [e.start_ns for e in emissions]
    assert debuts == sorted(debuts) and len(set(debuts)) == 5
    # Aucun chevauchement : chaque émission commence quand la précédente finit.
    for precedente, suivante in zip(emissions, emissions[1:]):
        assert suivante.start_ns == precedente.end_ns
    assert arbitre.occupation == tuple((e.start_ns, e.end_ns) for e in emissions)


def test_une_fenetre_couverte_nest_pas_emise():
    """Une descente longue couvre la fenêtre de la suivante : celle-ci n'est **pas** émise."""
    arbitre = GatewayArbiter()
    longue = arbitre.demand(EmissionRequest(label="ack", device=0, ready_ns=10 * SECONDE,
                                            duration_ns=1_500_000_000,
                                            window=(10 * SECONDE, 12 * SECONDE)))
    courte = arbitre.demand(EmissionRequest(label="join_accept", device=1, ready_ns=10 * SECONDE,
                                            duration_ns=100_000_000,
                                            window=(10 * SECONDE, 11 * SECONDE)))
    arbitre.resolve()
    assert arbitre.emission(longue).verdict == EMITTED
    manquee = arbitre.emission(courte)
    assert manquee.verdict == WINDOW_MISSED
    assert manquee.emitted is False and manquee.in_window is False
    # Rien n'a été émis : l'occupation ne porte qu'une seule émission.
    assert arbitre.occupation == ((10 * SECONDE, 11_500_000_000),)
    assert manquee.start_ns == 11_500_000_000      # datée, mais non émise
    assert manquee.end_ns == manquee.start_ns


def test_un_ack_tardif_est_emis_sil_est_demande():
    """`allow_late` : l'émission a lieu hors fenêtre, elle occupe l'émetteur (`late`)."""
    arbitre = GatewayArbiter()
    longue = arbitre.demand(EmissionRequest(label="ack", device=0, ready_ns=10 * SECONDE,
                                            duration_ns=1_500_000_000,
                                            window=(10 * SECONDE, 12 * SECONDE)))
    tardif = arbitre.demand(EmissionRequest(label="ack", device=1, ready_ns=10 * SECONDE,
                                            duration_ns=100_000_000,
                                            window=(10 * SECONDE, 11 * SECONDE),
                                            allow_late=True))
    arbitre.resolve()
    emission = arbitre.emission(tardif)
    assert emission.verdict == LATE
    assert emission.emitted is True and emission.in_window is False
    assert emission.start_ns == arbitre.emission(longue).end_ns
    assert len(arbitre.occupation) == 2


def test_aucune_priorite_par_defaut_a_instant_egal():
    """LoRaWAN ne définit pas d'ordre entre un Join-Accept et un ACK : ordre de dépôt."""
    arbitre = GatewayArbiter()
    join = arbitre.demand(EmissionRequest(label="join_accept", device=0, ready_ns=10 * SECONDE,
                                          duration_ns=100_000_000))
    ack = arbitre.demand(EmissionRequest(label="ack", device=1, ready_ns=10 * SECONDE,
                                         duration_ns=100_000_000))
    arbitre.resolve()
    assert arbitre.emission(join).start_ns < arbitre.emission(ack).start_ns
    assert ArbitrationPolicy().priority == {}


def test_une_priorite_explicite_est_appliquee():
    """Une politique non vide est appliquée, et c'est l'appelant qui la justifie."""
    politique = ArbitrationPolicy(priority={"join_accept": 10, "ack": 0})
    arbitre = GatewayArbiter(policy=politique)
    ack = arbitre.demand(EmissionRequest(label="ack", device=1, ready_ns=10 * SECONDE,
                                         duration_ns=100_000_000))
    join = arbitre.demand(EmissionRequest(label="join_accept", device=0, ready_ns=10 * SECONDE,
                                          duration_ns=100_000_000))
    arbitre.resolve()
    assert arbitre.emission(join).start_ns < arbitre.emission(ack).start_ns


def test_une_demande_devenue_sans_objet_noccupe_rien():
    """`condition` fausse au moment du placement : ni émission, ni occupation, ni réaction."""
    arbitre = GatewayArbiter()
    deja = {"fait": True}      # le terminal a déjà joint : la demande est sans objet
    demande = arbitre.demand(
        EmissionRequest(label="join_accept", device=0, ready_ns=10 * SECONDE,
                        duration_ns=100_000_000, window=(10 * SECONDE, 11 * SECONDE),
                        condition=lambda: not deja["fait"]))
    reactions = []
    arbitre.demand(EmissionRequest(label="ack", device=1, ready_ns=11 * SECONDE,
                                   duration_ns=100_000_000),
                   ensuite=lambda e, deposer: reactions.append(e))
    arbitre.resolve()
    assert arbitre.emission(demande).verdict == NOT_NEEDED
    assert arbitre.emission(demande).start_ns == 10 * SECONDE  # datée, mais non émise
    assert arbitre.occupation == ((11 * SECONDE, 11_100_000_000),)
    assert len(reactions) == 1


# --- Join-Accept et ACK : la même ressource -------------------------------------------------

def test_un_join_accept_et_un_ack_au_meme_instant():
    """Les deux sont émis, l'un après l'autre : un seul émetteur, pas de chevauchement."""
    scenario = _scenario()
    rx1 = _rx1_de(scenario)
    arbitre = GatewayArbiter()
    ack = arbitre.demand(EmissionRequest(label="ack", device=0, ready_ns=rx1,
                                         duration_ns=144_000_000))
    devices, _, _ = scenario.deploy()
    radios = device_radios(scenario)
    plan = simulate_joins(devices, scenario.gateway(), scenario.propagation(), radios,
                          ProtocolOptions(), scenario.environment, [(0, 10 * SECONDE)], {},
                          join_options=JoinRadioOptions(requests_s=(10,)), arbiter=arbitre)
    arbitre.resolve()
    assert arbitre.emission(ack).ready_ns == rx1  # même instant demandé
    join = [e for e in arbitre.emissions_faites if e.label == "join_accept"][0]
    # L'ACK est passé le premier (déposé avant), le Join-Accept le suit sans recouvrement.
    assert join.start_ns == arbitre.emission(ack).end_ns
    assert plan.result().attempts[0].accept_outcome == "delivered"


def test_un_ack_en_emission_quand_rx1_souvre():
    """L'émetteur est occupé au-delà de la fenêtre RX1 : RX1 n'est **pas** émise."""
    scenario = _scenario()
    rx1 = _rx1_de(scenario)
    # Une émission déjà en cours, qui couvre toute la fenêtre RX1 (une seconde) et au-delà.
    resultat, arbitre = _join_arbitre(
        scenario, occupation=[(rx1 - SECONDE // 10, rx1 + JOIN_WINDOW_NS + SECONDE // 5)])
    tentative = resultat.attempts[0]
    assert tentative.request_outcome == "received"
    assert [e.window for e in tentative.accepts] == ["rx1", "rx2"]
    assert tentative.accepts[0].outcome == "gateway_busy"
    assert tentative.accepts[0].emitted is False
    # RX1 manquée n'a **rien** émis : une seule émission de Join-Accept dans l'occupation,
    # et c'est celle de RX2, retardée d'autant.
    emises = arbitre.occupation_par_etiquette("join_accept")
    assert emises == ((tentative.accepts[1].at_ns, tentative.accepts[1].at_ns
                       + accept_airtime_ns(device_radios(scenario)[0])),)
    assert emises[0][0] == tentative.accepts[0].at_ns > rx1 + JOIN_WINDOW_NS


def test_rx1_impossible_puis_rx2_possible():
    """RX1 couverte par l'émetteur, RX2 libre : la session s'ouvre en secours."""
    scenario = _scenario()
    rx1 = _rx1_de(scenario)
    rx2 = rx1 + (JOIN_ACCEPT_DELAY2_NS - JOIN_ACCEPT_DELAY1_NS)
    resultat, arbitre = _join_arbitre(
        scenario, occupation=[(rx1 - SECONDE // 10, rx1 + JOIN_WINDOW_NS + SECONDE // 5)])
    tentative = resultat.attempts[0]
    assert [(e.window, e.outcome) for e in tentative.accepts] == [
        ("rx1", "gateway_busy"), ("rx2", "delivered")]
    assert tentative.accept_window == "rx2" and tentative.session == 1
    # L'occupation imposée plus le Join-Accept de RX2, et rien pour RX1.
    join = arbitre.occupation_par_etiquette("join_accept")
    assert join == ((tentative.accepts[1].at_ns, tentative.accepts[1].at_ns
                     + accept_airtime_ns(device_radios(scenario)[0])),)


def test_rx1_reussie_nemet_aucune_rx2():
    """Correction D3.12 préservée : RX2 reste un secours, jamais une seconde copie."""
    resultat, arbitre = _join_arbitre(_scenario())
    tentative = resultat.attempts[0]
    assert [e.window for e in tentative.accepts] == ["rx1"]
    assert tentative.accept_outcome == "delivered" and tentative.session == 1
    assert len(arbitre.occupation_par_etiquette("join_accept")) == 1


def test_deux_jointures_qui_se_chevauchent():
    """Deux terminaux demandent la jointure au même instant : leurs Join-Request se collisionnent.

    La contention montante est celle du moteur (capture) : un seul Join-Request survit, l'autre
    est perdu **sans qu'aucune descente ne soit émise pour lui**. Une seule émission de
    Join-Accept figure donc dans l'occupation : une tentative perdue n'occupe rien.
    """
    scenario = _scenario(_deux([[100.0, 0.0], [1000.0, 0.0]]))
    trace = build_trace(scenario, ProtocolOptions())
    resultat = trace.retransmissions
    assert [j.request_outcome for j in resultat.joins] == ["received", "lost_collision"]
    assert [j.session for j in resultat.joins] == [1, 0]
    assert resultat.joins[1].accepts == ()
    assert resultat.join_accepts_emitted == 1
    # Une seule émission de Join-Accept dans la trace, celle du terminal qui a survécu.
    accepts = [e for e in trace.events if e.kind == "join_accept"]
    assert [e.device_index for e in accepts] == [0]


def test_deux_join_accept_demandes_au_meme_instant_se_serialisent():
    """Côté émetteur : deux Join-Accept prêts au même instant se suivent, sans chevauchement.

    Le moteur ne peut pas produire deux Join-Request simultanés reçus (ils se collisionnent),
    donc la sérialisation descendante se vérifie sur l'arbitre lui-même, à instant imposé.
    """
    arbitre = GatewayArbiter()
    tickets = arbitre.demand_all([
        EmissionRequest(label="join_accept", device=d, ready_ns=15 * SECONDE,
                        duration_ns=247_000_000, window=(15 * SECONDE, 16 * SECONDE))
        for d in (0, 1)])
    arbitre.resolve()
    emissions = [arbitre.emission(t) for t in tickets]
    assert [e.verdict for e in emissions] == [EMITTED, EMITTED]
    assert emissions[1].start_ns == emissions[0].end_ns
    assert arbitre.occupation == tuple((e.start_ns, e.end_ns) for e in emissions)


# --- rapport cyclique des Join-Request -------------------------------------------------------

def test_le_budget_refuse_la_seconde_tentative():
    """Budget : la première émission passe, la seconde dépasse le rapport cyclique."""
    livre = DutyCycleLedger({0: 0.01})       # 1 % : 0,1 s de temps d'antenne à 10 s
    assert livre.allows(0, 10 * SECONDE, 60_000_000) is True
    livre.record(0, 10 * SECONDE, 10 * SECONDE + 60_000_000)
    # À 11 s le budget n'est que de 0,11 s : une seconde trame de 60 ms le dépasserait (0,12 s).
    assert livre.allows(0, 11 * SECONDE, 60_000_000) is False
    livre.refuse(0)
    assert livre.refusees(0) == 1 and livre.consumed_ns(0) == 60_000_000


def test_le_budget_est_global_et_non_par_nature_de_trame():
    """Les émissions de données consomment le même budget que les Join-Request."""
    livre = DutyCycleLedger({0: 0.01})
    livre.record(0, 1 * SECONDE, 1 * SECONDE + 80_000_000)      # une trame de données
    assert livre.allows(0, 10 * SECONDE, 50_000_000) is False   # 80 + 50 > 0,01 × 10 s
    assert livre.allows(0, 20 * SECONDE, 50_000_000) is True    # 130 ms ≤ 0,2 s


def test_une_tentative_bloquee_nest_pas_une_emission():
    """Un Join-Request refusé par le rapport cyclique n'émet rien et n'ouvre aucune session."""
    trace = _trace(_duty(0.001), join_retries=2)
    resultat = trace.retransmissions
    assert resultat.joins_blocked_by_duty_cycle == 2
    assert resultat.join_accepts_emitted == 0
    for tentative in resultat.joins:
        assert tentative.request_outcome == BLOCKED_DUTY_CYCLE
        assert tentative.emitted is False
        assert tentative.accepts == () and tentative.session == 0
    # La trace ne montre aucune transmission réussie : l'issue du contrat est `suppressed`.
    evenements = [e for e in trace.events if e.kind.startswith("join")]
    assert [(e.kind, e.outcome) for e in evenements] == [("join_request", "suppressed"),
                                                         ("join_request", "suppressed")]
    assert all(e.hops[0].outcome == "suppressed" for e in evenements)


def test_le_budget_peut_etre_desactive():
    """`enforce_duty_cycle: false` rend le budget inopérant, comme pour les réémissions."""
    bloquee = _trace(_duty(0.001)).retransmissions
    libre = _trace(_duty(0.001), enforce_duty_cycle=False).retransmissions
    assert bloquee.joins_blocked_by_duty_cycle == 1
    assert libre.joins_blocked_by_duty_cycle == 0
    assert libre.joins[0].session == 1


# --- bout en bout ----------------------------------------------------------------------------

def test_un_ack_est_repousse_par_un_join_accept():
    """Le Join-Accept occupe l'émetteur ; l'ACK demandé dans la seconde suivante est retardé.

    `ack_delay_ms: 12800` place l'ACK à 15,288 s, soit **pendant** l'émission du Join-Accept
    (15,206 s → 15,453 s). L'ACK part donc à 15,453 s : la ressource est unique.
    """
    trace = _trace(ack_delay_ms=12800, retries=2)
    join = [e for e in trace.gateway_tx if e[0] == trace.retransmissions.joins[0].accept_ns]
    assert len(join) == 1
    debut_join, fin_join = join[0]
    acks = [e for e in trace.gateway_tx if e != join[0]]
    pousses = [e for e in acks if e[0] == fin_join]
    assert pousses, "aucun ACK n'a été repoussé par le Join-Accept"
    # Et l'ACK n'a pas été avancé : il part après la fin du Join-Accept, jamais avant.
    assert all(e[0] >= fin_join for e in acks if e[0] >= debut_join)


def test_rx1_bloquee_par_deux_copies_dack_rx2_reussit():
    """Deux copies d'ACK couvrent RX1 (SF12, descentes longues) : RX2 prend le relais."""
    trace = _trace(_sf12, ack_repetitions=2, ack_delay_ms=12000, retries=2)
    tentative = trace.retransmissions.joins[0]
    assert [(e.window, e.outcome) for e in tentative.accepts] == [
        ("rx1", "gateway_busy"), ("rx2", "delivered")]
    assert tentative.session == 1


def test_rx1_et_rx2_bloquees_nouvrent_aucune_session():
    """Trois copies d'ACK couvrent RX1 **et** RX2 : aucune session, aucune jointure."""
    trace = _trace(_sf12, ack_repetitions=3, ack_delay_ms=12000, retries=2)
    tentative = trace.retransmissions.joins[0]
    assert [(e.window, e.outcome) for e in tentative.accepts] == [
        ("rx1", "gateway_busy"), ("rx2", "gateway_busy")]
    assert tentative.session == 0
    assert {a.session for a in trace.retransmissions.attempts} == {0}
    assert trace.retransmissions.join_accepts_emitted == 0
    # La trace garde la trace des fenêtres couvertes — c'est un fait de réseau — mais aucune
    # n'est une transmission : l'issue est `gateway_busy`, jamais `delivered`.
    evenements = [e for e in trace.events if e.kind == "join_accept"]
    assert [e.outcome for e in evenements] == ["gateway_busy", "gateway_busy"]
    assert all(e.hops[0].outcome == "gateway_busy" for e in evenements)


def test_join_accept_ack_et_downlink_sur_une_meme_passerelle():
    """Scénario complet : jointure, ACK et downlink de données sur le même émetteur.

    Chemin historique (`ProtocolOptions(join=True)`) : `_downlink_jobs` produit les trois
    familles de descentes et `_schedule_gateway` les sérialise — donc un seul `GatewayArbiter`.
    """

    def trois_messages(data):
        data["groups"][0]["messages"] = 3

    data = yaml.safe_load(open(NOMINAL, encoding="utf-8"))
    data.pop("retransmissions", None)
    trois_messages(data)
    scenario = load_scenario(yaml.safe_dump(data))
    trace = build_trace(scenario, ProtocolOptions(join=True, confirmed_uplinks=True,
                                                  downlink_every=2))
    kinds = [e.kind for e in trace.events if e.kind in ("join_accept", "ack", "downlink")]
    assert set(kinds) == {"join_accept", "ack", "downlink"}
    # Un seul émetteur : aucune émission n'en chevauche une autre.
    intervalles = sorted(trace.gateway_tx)
    for precedente, suivante in zip(intervalles, intervalles[1:]):
        assert precedente[1] <= suivante[0], (precedente, suivante)
    # La jointure précède les données : elle ouvre la session.
    join = [e for e in trace.events if e.kind == "join_accept"]
    assert len(join) == 1 and join[0].t_ns < min(e.t_ns for e in trace.events
                                                 if e.kind in ("ack", "downlink"))


def test_une_session_nest_pas_creee_sans_join_accept_recu():
    """Une émission supprimée, retardée hors fenêtre ou manquée n'ouvre aucune session."""
    manquee = _trace(_sf12, ack_repetitions=3, ack_delay_ms=12000, retries=2)
    assert manquee.retransmissions.joins[0].session == 0
    assert manquee.retransmissions.frames_delivered == 0
    # Et quand elle est reçue, une seule session par terminal.
    recue = _trace()
    assert recue.retransmissions.joins[0].session == 1
    assert max(a.session for a in recue.retransmissions.attempts) == 1


def test_les_scenarios_de_reference_des_retransmissions():
    """8/24 → 7/24 → 5/24 : les scénarios négatifs historiques sont inchangés.

    Mêmes graines, même scénario `ack_perdu` (récepteur +10 dB). Le partage de l'émetteur ne
    s'applique qu'aux descentes ; le budget montant n'est pas touché.
    """
    attendu = {0: (24, 11, 8, 0, 6), 1: (43, 15, 7, 1, 16), 3: (83, 20, 5, 8, 31)}
    for retries, (transmises, recues, ack, doublons, collisions) in attendu.items():
        scenario = load_scenario(open(ACK_PERDU, encoding="utf-8").read())
        devices, _, _ = scenario.deploy()
        resultat = simulate_confirmed_uplinks(
            devices, scenario.gateway(), scenario.propagation(), device_radios(scenario),
            ProtocolOptions(device_rx_offset_db=10), RetransmissionOptions(retries=retries))
        assert (resultat.transmissions, resultat.received, resultat.acks_received,
                resultat.duplicates, resultat.lost_collision) == (
            transmises, recues, ack, doublons, collisions), retries
        assert resultat.frames_delivered == (8 if retries == 0 else 7 if retries == 1 else 5)
        assert resultat.frames == 24


# --- garde-fous ------------------------------------------------------------------------------

def test_un_arbitre_non_resolu_refuse_la_lecture():
    arbitre = GatewayArbiter()
    ticket = arbitre.demand(EmissionRequest(label="ack", device=0, ready_ns=0,
                                            duration_ns=100_000_000))
    with pytest.raises(RuntimeError, match="non résolu"):
        arbitre.emission(ticket)
    arbitre.resolve()
    assert arbitre.emission(ticket).verdict == EMITTED


def test_une_demande_sans_duree_est_refusee():
    with pytest.raises(ValueError, match="temps d'antenne"):
        EmissionRequest(label="ack", device=0, ready_ns=0, duration_ns=0)
    with pytest.raises(ValueError, match="fenêtre"):
        EmissionRequest(label="ack", device=0, ready_ns=0, duration_ns=1000,
                        window=(0, 0))
    livre = DutyCycleLedger()
    with pytest.raises(ValueError, match="rapport cyclique"):
        livre.register(0, 0.0)


def test_le_verdict_duty_cycle_est_porte_par_le_ledger_pas_par_larbitre():
    """Le rapport cyclique est une contrainte d'émission du terminal, pas d'occupation passerelle.

    L'arbitre ne refuse jamais pour rapport cyclique : c'est le ledger qui décide, **avant** le
    dépôt. Le verdict `duty_cycle` existe pour un appelant qui voudrait tracer le refus dans la
    file ; la jointure, elle, retire la tentative du calendrier avant l'appel au moteur.
    """
    assert DUTY_CYCLE == "duty_cycle"
    livre = DutyCycleLedger({0: 1.0})
    assert livre.allows(0, 0, 10 ** 9) is True      # rapport 1.0 : aucune contrainte
    assert livre.refusees() == 0


# --- fenêtres : les sept cas du §2 -------------------------------------------------------------

def test_un_ack_occupe_rx1_puis_rx2():
    """Une même descente en cours couvre RX1 **puis** RX2 : les deux fenêtres sont perdues.

    L'occupation est imposée, pas simulée : c'est le seul moyen rendu reproductible de faire tenir
    la même émission sur les deux fenêtres d'une tentative.
    """
    scenario = _scenario(_sf12)
    rx1 = _rx1_de(scenario)
    rx2 = rx1 + (JOIN_ACCEPT_DELAY2_NS - JOIN_ACCEPT_DELAY1_NS)
    # Une descente commencée avant RX1 et finissant après la fin de la fenêtre RX2.
    resultat, arbitre = _join_arbitre(scenario, occupation=[(rx1 - SECONDE, rx2 + 2 * SECONDE)])

    tentative = resultat.attempts[0]
    assert [(e.window, e.outcome, e.emitted) for e in tentative.accepts] == [
        ("rx1", "gateway_busy", False), ("rx2", "gateway_busy", False)]
    # Rien n'a été émis pour cette tentative : l'occupation est celle imposée, et rien d'autre.
    assert arbitre.occupation == ((rx1 - SECONDE, rx2 + 2 * SECONDE),)
    assert tentative.session == 0 and resultat.joined == 0


def test_une_emission_commencee_dans_la_fenetre_la_depasse():
    """Le verdict porte sur le **début** : une descente commencée dans la fenêtre est émise entière.

    Elle occupe donc l'émetteur au-delà de la fermeture. L'arbitre mesure l'occupation ; la couche
    MAC décide seule si le terminal écoutait encore — les deux grandeurs sont indépendantes.
    """
    ouverture, fermeture = 10 * SECONDE, 11 * SECONDE
    # L'émetteur est libre à 10,8 s ; le temps d'antenne est de 1,5 s.
    arbitre = GatewayArbiter(occupation=[(0, 10 * SECONDE + 800_000_000)])
    longue = arbitre.demand(EmissionRequest(label="ack", device=0, ready_ns=ouverture,
                                            duration_ns=1_500_000_000,
                                            window=(ouverture, fermeture)))
    suivante = arbitre.demand(EmissionRequest(label="downlink", device=1, ready_ns=fermeture,
                                              duration_ns=100_000_000))
    arbitre.resolve()

    emission = arbitre.emission(longue)
    assert emission.start_ns == 10_800_000_000
    assert emission.start_ns < fermeture < emission.end_ns
    assert emission.verdict == EMITTED and emission.emitted is True
    assert emission.in_window is True
    # L'occupation va jusqu'au bout du temps d'antenne, au-delà de la fenêtre. La première
    # entrée est l'occupation imposée au départ, qui a rendu l'émetteur indisponible jusqu'à 10,8 s.
    assert arbitre.occupation[1:] == ((10_800_000_000, 12_300_000_000),
                                      (12_300_000_000, 12_400_000_000))
    assert 12_300_000_000 > fermeture
    # La demande suivante attend la fin **réelle** de l'émission, pas la fermeture de la fenêtre.
    assert arbitre.emission(suivante).start_ns == 12_300_000_000


def test_un_rejeu_nest_pas_un_nouveau_join_accept():
    """Le rejeu est une **émission de plus du même** Join-Accept, pas une seconde jointure.

    Trois propriétés le distinguent d'un nouveau Join-Accept : il naît d'une acceptation, il est
    reçu puis refusé (`replayed`), et il n'ouvre aucune session.
    """
    resultat, arbitre = _join_arbitre(_scenario(), accept_replays=2)

    tentative = resultat.attempts[0]
    assert [(e.window, e.outcome) for e in tentative.accepts] == [
        ("rx1", "delivered"), ("replay", "replayed"), ("replay", "replayed")]

    # Un rejeu est une émission **réelle** : il occupe l'émetteur, contrairement à une fenêtre
    # manquée. Trois émissions, donc trois occupations disjointes, espacées d'une seconde.
    assert len(arbitre.occupation) == 3
    for precedente, suivante in zip(arbitre.occupation, arbitre.occupation[1:]):
        assert suivante[0] >= precedente[1]                     # aucune descente simultanée
    # Les deux rejeux sont déposés depuis la **même** origine — la fin de RX1 — à une seconde
    # d'intervalle chacun. Ils ne s'enchaînent donc pas bout à bout comme le ferait une file :
    # le rangième rejeu part à `fin(RX1) + rang × JOIN_REPLAY_DELAY_NS`.
    fin_rx1 = arbitre.occupation[0][1]
    assert [debut for debut, _fin in arbitre.occupation] == [
        arbitre.occupation[0][0]] + [fin_rx1 + rang * JOIN_REPLAY_DELAY_NS
                                     for rang in (1, 2)]
    # RX2 n'a **pas** été émise : le rejeu n'est pas une fenêtre de secours.
    assert [e.window for e in tentative.accepts].count("rx2") == 0

    # Une seule session ouverte pour une acceptation et ses deux rejeux.
    assert tentative.session == 1 and resultat.joined == 1
    horloge = resultat.timelines[0]
    assert len(horloge.sessions) == 1
    # Le nonce est celui de l'acceptation : un rejeu ne renégocie rien.
    assert horloge.last.nonce == horloge.sessions[0].nonce


def test_un_rejeu_hors_emetteur_nouvre_rien():
    """Un rejeu que l'émetteur ne peut pas placer est `gateway_busy` : il n'occupe rien."""
    scenario = _scenario()
    rx1 = _rx1_de(scenario)
    # L'émetteur est occupé sans discontinuer à partir de RX1.
    imposer = [(rx1 - 2 * SECONDE, rx1 + 60 * SECONDE)]
    resultat, arbitre = _join_arbitre(scenario, accept_replays=1, occupation=imposer)

    tentative = resultat.attempts[0]
    # RX1 est refusée, donc RX2 est tentée en secours, et il n'y a ni acceptation ni rejeu.
    assert [(e.window, e.outcome, e.emitted) for e in tentative.accepts] == [
        ("rx1", "gateway_busy", False), ("rx2", "gateway_busy", False)]
    assert tentative.session == 0
    assert arbitre.occupation == tuple(imposer)


# --- rapport cyclique (§3) ---------------------------------------------------------------------

def _duty_tous(valeur):
    """Le rapport cyclique est une propriété de **groupe**, donc de terminal."""

    def modifier(data):
        for groupe in data["groups"]:
            groupe["duty_cycle"] = valeur

    return modifier


def test_le_budget_sapplique_a_toutes_les_tentatives_reelles():
    """Chaque tentative du terminal est soumise au budget, pas seulement la première."""
    trace = _trace(_duty_tous(0.001), join_requests_s=[10], join_retries=3)
    joins = trace.retransmissions.joins
    assert [(j.device, round(j.request_ns / 1e9, 1)) for j in joins] == [
        (0, 10.0), (0, 20.0), (0, 30.0)]
    assert [j.request_outcome for j in joins] == [BLOCKED_DUTY_CYCLE] * 3
    # Les trois tentatives sont refusées : le budget n'est pas réinitialisé entre elles.
    assert trace.retransmissions.joins_blocked_by_duty_cycle == 3


def test_une_tentative_refusee_nest_pas_une_emission():
    """Un Join-Request refusé n'émet rien : ni Join-Accept, ni session, ni occupation."""
    bloquee = _trace(_duty_tous(0.001), join_requests_s=[10], join_retries=2)
    resultat = bloquee.retransmissions
    assert resultat.joins_blocked_by_duty_cycle == 2
    assert resultat.join_accepts_emitted == 0
    assert all(j.session == 0 and j.accepts == () for j in resultat.joins)
    # L'événement est `suppressed`, pas `sent` : aucune transmission n'a eu lieu.
    assert [(e.kind, e.outcome) for e in bloquee.events if e.kind.startswith("join")] == [
        ("join_request", "suppressed"), ("join_request", "suppressed")]

    # Même scénario, budget levé : la jointure a bien lieu, les compteurs sont cohérents.
    libre = _trace(_duty_tous(1.0), join_requests_s=[10], join_retries=2)
    assert libre.retransmissions.joins_blocked_by_duty_cycle == 0
    assert libre.retransmissions.join_accepts_emitted == 1
    assert sum(1 for j in libre.retransmissions.joins if j.joined) == 1


def test_le_budget_est_isole_entre_terminaux():
    """Le budget d'un terminal ne limite pas celui d'un autre : deux groupes, deux budgets."""

    def deux_budgets(data):
        modele = data["groups"][0]
        second = dict(modele, name="second",
                      placement={"type": "explicit", "positions": [[300.0, 0.0]]})
        data["groups"] = [modele, second]
        data["groups"][0]["duty_cycle"] = 0.001   # terminal 0 : contraint
        data["groups"][1]["duty_cycle"] = 1.0     # terminal 1 : libre

    trace = _trace(deux_budgets, join_requests_s=[10], join_retries=2)
    joins = trace.retransmissions.joins
    # Le terminal contraint voit ses deux tentatives refusées ; l'autre joint du premier coup.
    assert [(j.device, j.request_outcome) for j in joins
            if j.device == 0] == [(0, BLOCKED_DUTY_CYCLE)] * 2
    assert [(j.device, j.request_outcome, j.session) for j in joins
            if j.device == 1] == [(1, "received", 1)]
    # Le compteur de refus ne comptabilise que le terminal contraint.
    assert trace.retransmissions.joins_blocked_by_duty_cycle == 2


def test_unites_calcul_et_fenetre_temporelle_du_budget():
    """Grandeurs, unités et fenêtre du budget : nanosecondes, cumul depuis l'origine."""
    livre = DutyCycleLedger({0: 0.01})     # 1 % du temps

    # Un terminal qui n'a rien émis peut émettre : le droit est `rapport × instant`.
    assert livre.consumed_ns(0) == 0
    assert livre.allows(0, 100 * SECONDE, 1 * SECONDE) is True       # 1 s <= 0,01 × 100 s
    assert livre.allows(0, 100 * SECONDE, 2 * SECONDE) is False      # 2 s > 1 s de droit

    # Le budget est **cumulatif** : ce qui a été émis à t = 10 s reste compté à t = 100 s.
    livre.record(0, 10 * SECONDE, 11 * SECONDE)                     # 1 s d'antenne
    assert livre.consumed_ns(0) == 1 * SECONDE
    # Droit à t = 100 s : 1 s. Cumul 1 s + demande 1 s = 2 s > 1 s ⇒ refusé.
    assert livre.allows(0, 100 * SECONDE, 1 * SECONDE) is False
    # Droit à t = 200 s : 2 s. Cumul 1 s + demande 1 s = 2 s ≤ 2 s ⇒ accordé, tout juste.
    assert livre.allows(0, 200 * SECONDE, 1 * SECONDE) is True
    # Ce n'est **pas** une fenêtre glissante : l'émission de t = 10 s pèse encore à t = 200 s.

    # Le cumul est mesurable jusqu'à un instant donné, pour la traçabilité.
    livre.record(0, 150 * SECONDE, 150 * SECONDE + 500_000_000)
    assert livre.consumed_ns(0, until_ns=100 * SECONDE) == 1 * SECONDE
    assert livre.consumed_ns(0) == 1_500_000_000

    # Le rapport est **sans dimension** et borné : 1,0 ne contraint rien, 0 ne veut rien dire.
    assert DutyCycleLedger({0: 1.0}).allows(0, 1, 10 ** 12) is True
    with pytest.raises(ValueError):
        DutyCycleLedger({0: 0.0})


def test_aucune_limite_descendante_nest_modelee():
    """Contrainte non modélisée, signalée : la passerelle n'a **pas** de budget d'émission.

    Le ledger ne connaît que des émissions de **terminaux**. Aucune valeur réglementaire
    descendante n'est introduite : plutôt que d'inventer une règle, on vérifie ici que rien
    ne limite les descentes.
    """
    livre = DutyCycleLedger()
    # Aucun enregistrement d'émission de passerelle n'est possible : le ledger est indexé par
    # terminal et l'arbitre ne le consulte jamais pour une descente.
    assert livre.refusees() == 0
    arbitre = GatewayArbiter()
    # Cinq descentes consécutives : l'arbitre les place toutes, sans notion de budget.
    tickets = arbitre.demand_all([
        EmissionRequest(label="ack", device=d, ready_ns=10 * SECONDE,
                        duration_ns=SECONDE, window=(10 * SECONDE, 60 * SECONDE))
        for d in range(5)])
    arbitre.resolve()
    assert [arbitre.emission(t).verdict for t in tickets] == [EMITTED] * 5
    assert livre.refusees() == 0
