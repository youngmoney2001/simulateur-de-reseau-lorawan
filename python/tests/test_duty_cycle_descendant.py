"""D3.14 — Rapport cyclique **descendant** : espacement par passerelle et par sous-bande.

Arbitrages appliqués :

- **A1** : l'espacement suit l'émission, `repos = airtime × (1 − d) / d`, formule déjà celle
  de la boucle fermée du moteur (`core/src/engine.cpp`, l. 2019-2031). Il n'est **pas**
  fusionné avec `DutyCycleLedger`, qui est un budget cumulatif montant.
- **A3** : l'état est indexé par `(passerelle, sous-bande)`, réservé **une seule fois** au
  moment où l'émission est acceptée ; une émission refusée ne consomme rien.

| Ce qui est vérifié | Test |
|---|---|
| Le repos vaut `airtime × (1 − d) / d` | `test_le_repos_suit_l_airtime_emis` |
| Deux émissions d'une sous-bande sont espacées | `test_deux_emissions_dune_sous_bande_sont_espacees` |
| L'attente reste dans la fenêtre : émission retardée | `test_l_attente_qui_tient_dans_la_fenetre_emet_plus_tard` |
| L'attente sort de la fenêtre : refus `duty_cycle` | `test_l_attente_qui_sort_de_la_fenetre_est_refusee` |
| Une fenêtre manquée **sans** attente reste `window_missed` | `test_une_fenetre_manquee_sans_attente_reste_window_missed` |
| Une émission refusée ne consomme rien | `test_une_emission_refusee_ne_consomme_rien` |
| `not_needed` et `window_missed` ne consomment rien | `test_not_needed_et_window_missed_ne_consomment_rien` |
| `allow_late` émet après l'attente | `test_allow_late_emet_apres_l_attente` |
| Deux sous-bandes ont des états distincts | `test_deux_sous_bandes_ont_des_etats_distincts` |
| Deux passerelles ont des états distincts | `test_deux_passerelles_ont_des_etats_distincts` |
| RX1 et RX2 ne sont pas dans la même sous-bande (EU868) | `test_rx1_et_rx2_ne_partagent_pas_la_sous_bande` |
| Un ACK et un Join-Accept de même fréquence partagent l'état | `test_ack_et_join_accept_de_meme_frequence_partagent_l_etat` |
| Une fréquence hors plan est refusée | `test_une_frequence_hors_plan_est_refusee` |
| Une fréquence non renseignée ne contraint rien | `test_une_frequence_non_renseignee_ne_contraint_rien` |
| Une région sans sous-bandes ne contraint rien | `test_une_region_sans_sous_bandes_ne_contraint_rien` |
| `nouvelle_passe` repart de zéro | `test_nouvelle_passe_repart_de_zero` |
| Bande O (0,1 %) contre bande P (10 %), bout en bout | `test_bande_o_et_bande_p_espanacent_differemment` |
| Sans région : comportement inchangé | `test_sans_region_aucune_contrainte_nest_appliquee` |
| `enforce_duty_cycle: false` désactive | `test_enforce_duty_cycle_false_desactive_la_contrainte` |
| Le point fixe ne cumule pas les passes | `test_le_point_fixe_ne_cumule_pas_les_passes` |
| Le chemin natif n'applique pas la contrainte | `test_le_chemin_natif_napplique_pas_la_contrainte` |
| Un Join-Accept est compté une seule fois | `test_le_join_accept_est_compte_une_seule_fois` |
| Les rejeux sont refusés par la sous-bande | `test_les_rejeux_sont_refuses_par_le_rapport_cyclique` |
| RX2 de secours : sous-bande distincte, aucun retard | `test_la_rx2_de_secours_nest_pas_retardee_par_la_rx1` |
| Un Join-Accept refusé n'ouvre aucune session | `test_un_join_accept_refuse_nouvre_aucune_session` |
"""

from __future__ import annotations

import pytest
import yaml

from lsim.arbitre import (DUTY_CYCLE, HORS_PLAN, NOT_NEEDED, WINDOW_MISSED, DownlinkDutyCycle,
                          EmissionRequest, GatewayArbiter)
from lsim.join import (JOIN_ACCEPT_DELAY1_NS, JOIN_ACCEPT_DELAY2_NS, JOIN_WINDOW_NS,
                       JoinRadioOptions, simulate_joins)
from lsim.power import TxChain
from lsim.regions import PROFILES
from lsim.scenario import load_scenario
from lsim.trace_events import ProtocolOptions, build_trace, device_radios

SECONDE = 1_000_000_000

EU = PROFILES["EU868"]
RX1_HZ = 868_100_000     # canal par défaut EU868 : sous-bande M, 1 %
RX2_HZ = 869_525_000     # repli régional : sous-bande O à 14 dBm, P à 27 dBm
HORS_BANDE_HZ = 869_850_000   # bandes Q (25 mW) et QP (5 mW) : aucune n'accepte 27 dBm

TARDIF = "docs/exemples/retransmissions_ack_tardif.yaml"
NOMINAL = "docs/exemples/retransmissions_nominal.yaml"


def _duty(conduite: float = 14.0, region: str = "EU868", actif: bool = True):
    return DownlinkDutyCycle(PROFILES[region] if region else None, TxChain(conduite), actif)


def _emettre(arbitre, label, debut, duree, freq=RX1_HZ, passerelle=0, fenetre=None,
             allow_late=False, condition=None):
    return arbitre.demand(EmissionRequest(label=label, device=0, ready_ns=debut,
                                          duration_ns=duree, freq_hz=freq, gateway=passerelle,
                                          window=fenetre, allow_late=allow_late,
                                          condition=condition))


# --------------------------------------------------------------------- la règle

def test_le_repos_suit_l_airtime_emis():
    d = _duty()
    assert d.repos_ns(1 * SECONDE, 0.01) == 99 * SECONDE      # 1 %  : 99 fois l'airtime
    assert d.repos_ns(1 * SECONDE, 0.001) == 999 * SECONDE    # 0,1 % : 999 fois
    assert d.repos_ns(1 * SECONDE, 0.10) == 9 * SECONDE       # 10 %  : 9 fois
    assert d.repos_ns(1 * SECONDE, 1.0) == 0                  # aucune contrainte
    with pytest.raises(ValueError):
        d.repos_ns(1 * SECONDE, 0.0)


def test_deux_emissions_dune_sous_bande_sont_espacees():
    d = _duty()
    arbitre = GatewayArbiter(duty_cycle=d)
    _emettre(arbitre, "ack", 0, 1 * SECONDE)
    _emettre(arbitre, "ack", 2 * SECONDE, 1 * SECONDE)
    (premiere, seconde) = arbitre.resolve()
    assert (premiere.start_ns, premiere.end_ns) == (0, 1 * SECONDE)
    # 1 % dans la bande M : repos de 99 s après une émission d'une seconde.
    assert seconde.start_ns == 100 * SECONDE
    assert seconde.verdict == "emitted"


def test_l_attente_qui_tient_dans_la_fenetre_emet_plus_tard():
    d = _duty()
    arbitre = GatewayArbiter(duty_cycle=d)
    _emettre(arbitre, "ack", 0, 1 * SECONDE)
    _emettre(arbitre, "ack", 2 * SECONDE, 1 * SECONDE, fenetre=(2 * SECONDE, 200 * SECONDE))
    (_, seconde) = arbitre.resolve()
    assert seconde.verdict == "emitted"
    assert seconde.start_ns == 100 * SECONDE
    assert d.consommations() == 2


def test_l_attente_qui_sort_de_la_fenetre_est_refusee():
    d = _duty()
    arbitre = GatewayArbiter(duty_cycle=d)
    _emettre(arbitre, "ack", 0, 1 * SECONDE)
    _emettre(arbitre, "ack", 2 * SECONDE, 1 * SECONDE, fenetre=(2 * SECONDE, 50 * SECONDE))
    (_, seconde) = arbitre.resolve()
    assert seconde.verdict == DUTY_CYCLE
    assert not seconde.emitted
    # Refusée : aucune occupation, aucune consommation.
    assert arbitre.occupation == ((0, 1 * SECONDE),)
    assert d.consommations() == 1
    assert d.refus() == 1


def test_une_fenetre_manquee_sans_attente_reste_window_missed():
    """Sans attente réglementaire, la cause est l'occupation : le verdict ne change pas."""
    d = _duty()
    arbitre = GatewayArbiter(duty_cycle=d)
    # Une première émission longue dans une **autre** sous-bande, donc sans espacement.
    _emettre(arbitre, "ack", 0, 100 * SECONDE, freq=RX2_HZ)
    _emettre(arbitre, "ack", 2 * SECONDE, 1 * SECONDE, fenetre=(2 * SECONDE, 50 * SECONDE))
    (_, seconde) = arbitre.resolve()
    assert seconde.verdict == WINDOW_MISSED
    assert d.refus() == 0            # l'espacement n'a jamais été en cause
    assert d.consommations() == 1


def test_une_emission_refusee_ne_consomme_rien():
    d = _duty()
    arbitre = GatewayArbiter(duty_cycle=d)
    _emettre(arbitre, "ack", 0, 1 * SECONDE)
    _emettre(arbitre, "ack", 2 * SECONDE, 1 * SECONDE, fenetre=(2 * SECONDE, 50 * SECONDE))
    # Une troisième, prête bien plus tard : elle est acceptée, l'état n'ayant pas bougé.
    _emettre(arbitre, "ack", 101 * SECONDE, 1 * SECONDE)
    (_, refusee, troisieme) = arbitre.resolve()
    assert refusee.verdict == DUTY_CYCLE
    assert troisieme.verdict == "emitted"
    assert troisieme.start_ns == 101 * SECONDE    # pas 200 s : le refus n'a rien réservé
    assert d.consommations() == 2


def test_not_needed_et_window_missed_ne_consomment_rien():
    d = _duty()
    arbitre = GatewayArbiter(duty_cycle=d)
    _emettre(arbitre, "ack", 0, 1 * SECONDE, condition=lambda: False)
    _emettre(arbitre, "ack", 1 * SECONDE, 1 * SECONDE, fenetre=(0, SECONDE // 2))
    (premiere, seconde) = arbitre.resolve()
    assert (premiere.verdict, seconde.verdict) == (NOT_NEEDED, WINDOW_MISSED)
    assert arbitre.occupation == ()
    assert d.consommations() == 0


def test_allow_late_emet_apres_l_attente():
    d = _duty()
    arbitre = GatewayArbiter(duty_cycle=d)
    _emettre(arbitre, "ack", 0, 1 * SECONDE)
    _emettre(arbitre, "ack", 2 * SECONDE, 1 * SECONDE,
             fenetre=(2 * SECONDE, 50 * SECONDE), allow_late=True)
    (_, seconde) = arbitre.resolve()
    assert seconde.verdict == "late"          # émise, mais hors fenêtre
    assert seconde.start_ns == 100 * SECONDE
    assert d.consommations() == 2             # une émission réelle consomme


# ---------------------------------------------------------- séparation de l'état

def test_deux_sous_bandes_ont_des_etats_distincts():
    d = _duty()
    arbitre = GatewayArbiter(duty_cycle=d)
    _emettre(arbitre, "ack", 0, 1 * SECONDE, freq=RX1_HZ)          # bande M, 1 %
    _emettre(arbitre, "ack", 2 * SECONDE, 1 * SECONDE, freq=RX2_HZ)  # bande O, 0,1 %
    (premiere, seconde) = arbitre.resolve()
    assert premiere.start_ns == 0
    assert seconde.start_ns == 2 * SECONDE     # l'état de M ne retarde pas O
    assert d.etat() == {(0, "M"): (1 * SECONDE, 1 * SECONDE),
                        (0, "O"): (3 * SECONDE, 1 * SECONDE)}


def test_deux_passerelles_ont_des_etats_distincts():
    d = _duty()
    arbitre = GatewayArbiter(duty_cycle=d)
    _emettre(arbitre, "ack", 0, 1 * SECONDE, passerelle=0)
    _emettre(arbitre, "ack", 2 * SECONDE, 1 * SECONDE, passerelle=1)
    (premiere, seconde) = arbitre.resolve()
    assert premiere.start_ns == 0
    # Même fréquence, même sous-bande, mais l'état est **par passerelle** : aucune attente.
    assert seconde.start_ns == 2 * SECONDE
    assert set(d.etat()) == {(0, "M"), (1, "M")}


def test_rx1_et_rx2_ne_partagent_pas_la_sous_bande():
    """En EU868, RX1 (868,1 MHz) est en bande M et RX2 (869,525 MHz) en bande O ou P."""
    d = _duty()
    assert d.regle(RX1_HZ) == ("M", 0.01)
    assert d.regle(RX2_HZ) == ("O", 0.001)
    d27 = _duty(conduite=27.0)
    # Conséquence directe du tableau ETSI, et non un choix du simulateur : la bande M
    # (868,0-868,6 MHz) plafonne à 25 mW de PAR, soit 16,13 dBm de PIRE. Une passerelle
    # réglée sur la puissance publiée de ses fiches (27 dBm) ne peut donc **pas** émettre
    # en RX1 sur les canaux par défaut : c'est hors plan, pas hors quota.
    assert d27.regle(RX1_HZ) == (HORS_PLAN, None)
    assert d27.regle(RX2_HZ) == ("P", 0.10)     # la PIRE départage O et P


def test_ack_et_join_accept_de_meme_frequence_partagent_l_etat():
    """Deux natures de descente, une seule sous-bande : le même état, une seule réservation."""
    d = _duty()
    arbitre = GatewayArbiter(duty_cycle=d)
    _emettre(arbitre, "join_accept", 0, 1 * SECONDE, freq=RX1_HZ)
    _emettre(arbitre, "ack", 2 * SECONDE, 1 * SECONDE, freq=RX1_HZ)
    (premiere, seconde) = arbitre.resolve()
    assert seconde.start_ns == 100 * SECONDE
    assert d.etat() == {(0, "M"): (101 * SECONDE, 1 * SECONDE)}
    assert d.consommations() == 2


# ------------------------------------------------------------------- les limites

def test_une_frequence_hors_plan_est_refusee():
    """869,85 MHz à 27 dBm : ni la bande Q (25 mW) ni la bande QP (5 mW) ne l'acceptent."""
    d = _duty(conduite=27.0)
    assert d.regle(HORS_BANDE_HZ) == (HORS_PLAN, None)
    arbitre = GatewayArbiter(duty_cycle=d)
    _emettre(arbitre, "ack", 0, 1 * SECONDE, freq=HORS_BANDE_HZ)
    (premiere,) = arbitre.resolve()
    assert premiere.verdict == DUTY_CYCLE
    assert d.refus_hors_plan() == 1
    assert d.refus() == 0
    assert arbitre.occupation == ()


def test_une_frequence_non_renseignee_ne_contraint_rien():
    """`rx2_hz = 0` : aucun plan régional. Ni contrainte, ni refus (ce n'est pas hors plan)."""
    d = _duty()
    assert d.regle(0) == (None, None)
    assert d.regle(None) == (None, None)
    arbitre = GatewayArbiter(duty_cycle=d)
    _emettre(arbitre, "ack", 0, 1 * SECONDE, freq=0)
    _emettre(arbitre, "ack", 2 * SECONDE, 1 * SECONDE, freq=0)
    (premiere, seconde) = arbitre.resolve()
    assert seconde.start_ns == 2 * SECONDE
    assert d.consommations() == 0


def test_une_region_sans_sous_bandes_ne_contraint_rien():
    """US915 n'a pas de sous-bandes : ni contrainte, ni erreur."""
    d = _duty(region="US915")
    assert d.regle(RX2_HZ) == (None, None)
    arbitre = GatewayArbiter(duty_cycle=d)
    _emettre(arbitre, "ack", 0, 1 * SECONDE)
    _emettre(arbitre, "ack", 2 * SECONDE, 1 * SECONDE)
    (_, seconde) = arbitre.resolve()
    assert seconde.start_ns == 2 * SECONDE


def test_nouvelle_passe_repart_de_zero():
    d = _duty()
    arbitre = GatewayArbiter(duty_cycle=d)
    _emettre(arbitre, "ack", 0, 1 * SECONDE)
    _emettre(arbitre, "ack", 2 * SECONDE, 1 * SECONDE)
    arbitre.resolve()
    assert d.consommations() == 2

    neuve = d.nouvelle_passe()
    assert neuve.consommations() == 0
    assert neuve.etat() == {}
    assert neuve.eirp_dbm == pytest.approx(d.eirp_dbm)      # même règle
    second = GatewayArbiter(duty_cycle=neuve)
    _emettre(second, "ack", 2 * SECONDE, 1 * SECONDE)
    (emission,) = second.resolve()
    assert emission.start_ns == 2 * SECONDE                 # état vierge : aucune attente


# --------------------------------------------------------------- bout en bout

def _brut(exemple=TARDIF, region=None, puissance=None, **reglages):
    data = yaml.safe_load(open(exemple, encoding="utf-8"))
    if region is not None:
        for groupe in data["groups"]:
            groupe["region"] = region
    if puissance is not None:
        data["gateway"]["tx_power_dbm"] = puissance
    data["retransmissions"].update({"retries": 1, **reglages})
    return yaml.safe_dump(data)


def _arrondis(occupations, precision: int = 4):
    return [(round(debut / 1e9, precision), round((fin - debut) / 1e9, precision))
            for debut, fin in occupations]


def test_bande_o_et_bande_p_espanacent_differemment():
    """Même scénario, même trame : 14 dBm (bande O, 0,1 %) contre 27 dBm (bande P, 10 %)."""
    sans_region = build_trace(load_scenario(_brut()), ProtocolOptions()).retransmissions
    bande_o = build_trace(load_scenario(_brut(region="EU868")), ProtocolOptions()).retransmissions
    bande_p = build_trace(load_scenario(_brut(region="EU868", puissance=27)),
                          ProtocolOptions()).retransmissions

    # Un ACK de 0,1444 s en RX2 : repos de 999 × l'airtime en bande O, de 9 × en bande P.
    assert _arrondis(bande_o.gateway_tx)[0][1] == pytest.approx(0.1444, abs=1e-4)
    assert _arrondis(bande_p.gateway_tx)[0][1] == pytest.approx(0.1444, abs=1e-4)
    ecart_o = (bande_o.gateway_tx[1][0] - bande_o.gateway_tx[0][0]) / 1e9
    ecart_p = (bande_p.gateway_tx[1][0] - bande_p.gateway_tx[0][0]) / 1e9
    assert ecart_o == pytest.approx(0.144384 * 1000, abs=1e-3)   # 144,384 s
    assert ecart_p == pytest.approx(0.144384 * 10, abs=1e-3)     # 1,4438 s
    # Sans région, rien ne change : c'est la référence historique.
    assert _arrondis(sans_region.gateway_tx) == [(4.988, 0.1444), (8.1324, 0.1444), (64.988, 0.1444), (68.1324, 0.1444)]


def test_sans_region_aucune_contrainte_nest_appliquee():
    """Sans région déclarée, la sous-bande est indéfinie : aucune contrainte, aucune erreur."""
    data = yaml.safe_load(open(TARDIF, encoding="utf-8"))
    data["retransmissions"].update({"retries": 1})
    attendu = _arrondis(build_trace(load_scenario(yaml.safe_dump(data)),
                                    ProtocolOptions()).retransmissions.gateway_tx)
    for groupe in data["groups"]:
        groupe["region"] = None
    assert _arrondis(build_trace(load_scenario(yaml.safe_dump(data)),
                                 ProtocolOptions()).retransmissions.gateway_tx) == attendu


def test_enforce_duty_cycle_false_desactive_la_contrainte():
    """Une seule clef pour les deux sens : elle éteint aussi la contrainte descendante."""
    libre = build_trace(load_scenario(_brut(region="EU868")),
                        ProtocolOptions()).retransmissions
    eteint = build_trace(load_scenario(_brut(region="EU868", enforce_duty_cycle=False)),
                         ProtocolOptions()).retransmissions
    assert len(libre.gateway_tx) < len(eteint.gateway_tx)
    assert _arrondis(eteint.gateway_tx) == [(4.988, 0.1444), (8.1324, 0.1444), (64.988, 0.1444), (68.1324, 0.1444)]


def test_le_point_fixe_ne_cumule_pas_les_passes():
    """Avec jointures radio, la contrainte est active **sans** refuser ce qu'elle a autorisé.

    Le point fixe rejoue la même chronologie : si l'état survivait d'une passe à l'autre, la
    seconde passe refuserait les émissions de la première et la session ne s'ouvrirait pas.
    La jointure est demandée à 300 s parce qu'à 10 s le Join-Request lui-même est bloqué par
    le budget **montant** de la bande M (1 %) : l'espacement descendant n'y est pour rien.
    """
    data = yaml.safe_load(open(NOMINAL, encoding="utf-8"))
    for groupe in data["groups"]:
        groupe["region"] = "EU868"
    data["retransmissions"].update({"retries": 1, "join_requests_s": [300]})
    scenario = load_scenario(yaml.safe_dump(data))
    radios = device_radios(scenario)
    assert radios[0].rx1_hz == RX1_HZ and radios[0].rx2_hz == RX2_HZ

    premier = build_trace(scenario, ProtocolOptions()).retransmissions
    second = build_trace(scenario, ProtocolOptions()).retransmissions
    # Le Join-Accept est émis en RX1 (bande M) et la session s'ouvre : la contrainte
    # descendante n'a rien refusé de ce que la passe précédente avait autorisé.
    assert [(e.window, e.outcome) for j in premier.joins for e in j.accepts] == [
        ("rx1", "delivered")]
    assert max(j.session for j in premier.joins) == 1
    # Et le résultat est reproductible : le point fixe converge, il ne dérive pas.
    assert _arrondis(second.gateway_tx) == _arrondis(premier.gateway_tx)


def test_sans_nouvelle_passe_un_etat_conserve_refuserait_la_suite():
    """Contre-épreuve : c'est pour éviter ce refus que chaque passe repart de zéro."""
    d = _duty()
    premiere = GatewayArbiter(duty_cycle=d)
    _emettre(premiere, "ack", 0, 1 * SECONDE)
    premiere.resolve()

    # Le **même** objet à la passe suivante : la même émission, rejouée, est refusée.
    suivante = GatewayArbiter(duty_cycle=d)
    _emettre(suivante, "ack", 0, 1 * SECONDE, fenetre=(0, 10 * SECONDE))
    (emission,) = suivante.resolve()
    assert emission.verdict == DUTY_CYCLE
    assert suivante.occupation == ()
    assert d.refus() == 1


def test_le_chemin_natif_napplique_pas_la_contrainte():
    """Le planificateur du cœur (`_schedule_gateway`) ne reçoit aucun état : A4, ABI inchangé.

    La preuve est structurelle et mesurable : le planificateur du cœur construit son propre
    `GatewayArbiter`, donc sans `duty_cycle`, et place deux descentes de la même sous-bande
    sans aucun espacement réglementaire.
    """
    from lsim.trace_events import _Job, _schedule_gateway

    travaux = [_Job(record=0, device=0, kind="downlink", content="data", t_open=2 * SECONDE,
                    airtime_ns=1 * SECONDE, rx1_hz=RX1_HZ, received=True, device_missed=False),
               _Job(record=1, device=1, kind="downlink", content="data", t_open=3 * SECONDE,
                    airtime_ns=1 * SECONDE, rx1_hz=RX1_HZ, received=True, device_missed=False)]
    debuts, occupations = _schedule_gateway(travaux)
    # Aucun espacement : la seconde descente suit la première, et non 100 s plus tard.
    assert debuts == [2 * SECONDE, 3 * SECONDE]
    assert [tuple(o) for o in occupations] == [(2 * SECONDE, 3 * SECONDE),
                                               (3 * SECONDE, 4 * SECONDE)]
    assert _schedule_gateway(travaux) == (debuts, occupations)   # sans état : reproductible


# ------------------------------------------------------------- la jointure radio

def _join_duty(region="EU868", conduite=14.0, occupation=(), duty=None, accept_replays=0):
    """Joue une jointure dans un arbitre où `occupation` est imposée et `duty` actif."""
    data = yaml.safe_load(open(TARDIF, encoding="utf-8"))
    for groupe in data["groups"]:
        groupe["region"] = region
    data["retransmissions"].update({"retries": 1, "ack_delay_ms": 0})
    scenario = load_scenario(yaml.safe_dump(data))
    devices, _, _ = scenario.deploy()
    radios = device_radios(scenario)
    etat = duty if duty is not None else DownlinkDutyCycle(PROFILES[region], TxChain(conduite))
    arbitre = GatewayArbiter(occupation=occupation, duty_cycle=etat)
    plan = simulate_joins(devices, scenario.gateway(), scenario.propagation(), radios,
                          ProtocolOptions(), scenario.environment, [(0, 300 * SECONDE)], {},
                          join_options=JoinRadioOptions(requests_s=(300,),
                                                        accept_replays=accept_replays),
                          arbiter=arbitre)
    arbitre.resolve()
    return plan.result(), arbitre, etat, radios


def test_le_join_accept_est_compte_une_seule_fois():
    """Une acceptation = une consommation, pas une par fenêtre ni une par passe."""
    resultat, _arbitre, d, radios = _join_duty()
    tentative = resultat.attempts[0]
    assert [(e.window, e.outcome) for e in tentative.accepts] == [("rx1", "delivered")]
    assert tentative.session == 1
    assert d.consommations() == 1
    # Une seule clé : la sous-bande de RX1 (868,1 MHz → bande M), jamais celle de RX2.
    assert set(d.etat()) == {(0, "M")}


def test_les_rejeux_sont_refuses_par_le_rapport_cyclique():
    """`JOIN_REPLAY_DELAY_NS` vaut 1 s ; la bande M impose 24,43 s de repos après 0,2468 s.

    Le rejeu n'est donc pas émis, et l'issue le dit : `duty_cycle`, pas `gateway_busy` —
    la passerelle était libre, c'est la sous-bande qui l'interdisait.
    """
    resultat, _arbitre, d, _radios = _join_duty(accept_replays=2)
    tentative = resultat.attempts[0]
    assert [(e.window, e.outcome) for e in tentative.accepts] == [
        ("rx1", "delivered"), ("replay", DUTY_CYCLE), ("replay", DUTY_CYCLE)]
    assert tentative.session == 1                 # une seule session : les rejeux n'en ouvrent pas
    assert d.consommations() == 1                 # seules les émissions réelles sont comptées
    assert d.refus() == 2


def test_la_rx2_de_secours_nest_pas_retardee_par_la_rx1():
    """RX1 est en bande M, RX2 en bande O : l'échec de RX1 ne consomme rien pour RX2."""
    sans = _join_duty()
    rx1 = sans[0].attempts[0].request_end_ns + JOIN_ACCEPT_DELAY1_NS
    rx2 = sans[0].attempts[0].request_end_ns + JOIN_ACCEPT_DELAY2_NS
    couvrir = [(rx1 - SECONDE // 10, rx1 + JOIN_WINDOW_NS + SECONDE // 5)]
    resultat, arbitre, d, radios = _join_duty(occupation=couvrir)
    tentative = resultat.attempts[0]
    assert [(e.window, e.outcome) for e in tentative.accepts] == [
        ("rx1", "gateway_busy"), ("rx2", "delivered")]
    # RX2 part dès que l'émetteur se libère, **sans** un instant de plus : l'état de la
    # bande M, où RX1 a échoué, ne la concerne pas. Le retard observable (0,2 s) est celui
    # de l'occupation imposée, pas celui de la sous-bande.
    assert tentative.accepts[1].at_ns == couvrir[0][1]
    assert d.consommations() == 1
    assert set(d.etat()) == {(0, "O")}


def test_un_join_accept_refuse_nouvre_aucune_session():
    """Une émission antérieure dans la même sous-bande épuise le droit : aucune session."""
    d = DownlinkDutyCycle(EU, TxChain(14.0))
    # 60 s d'émission déjà jouées dans les deux sous-bandes de la jointure : 5 940 s de repos
    # en bande M (1 %), 59 940 s en bande O (0,1 %). RX1 **et** RX2 tombent donc après.
    d.consommer(0, RX1_HZ, 0, 60 * SECONDE)
    d.consommer(0, RX2_HZ, 0, 60 * SECONDE)
    assert d.repos_ns(60 * SECONDE, 0.01) == 5940 * SECONDE
    assert d.repos_ns(60 * SECONDE, 0.001) == 59_940 * SECONDE
    resultat, arbitre, d, _radios = _join_duty(duty=d)
    tentative = resultat.attempts[0]
    assert [(e.window, e.outcome) for e in tentative.accepts] == [
        ("rx1", DUTY_CYCLE), ("rx2", DUTY_CYCLE)]
    assert tentative.session == 0
    assert arbitre.occupation_par_etiquette("join_accept") == ()
    assert d.refus() == 2
