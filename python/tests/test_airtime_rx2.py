"""A5 — le temps d'antenne d'une descente suit la fenêtre **réellement émise**.

RX1 et RX2 ne sont pas la même fenêtre : RX2 est le repli régional (`DLSettings`), avec sa propre
fréquence et son propre débit. En EU868, RX2 est en SF12 BW125 là où RX1 suit le SF montant ; un
Join-Accept de 33 octets y occupe l'émetteur **1,8104 s** contre **0,2468 s** en RX1, et un ACK de
12 octets **0,9912 s** contre **0,1444 s**. Employer le débit de RX1 pour une émission en RX2
sous-estimait l'occupation d'un facteur 7 — donc, par ricochet, tout budget réglementaire assis
dessus.

Ce fichier est la **première étape obligatoire** de D3.14 : il valide la correction de l'airtime
avant toute activation du contrôle descendant.

| Ce qui est vérifié | Test |
|---|---|
| Le plan régional renseigne RX2 (fréquence, SF, BW) | `test_le_plan_regional_renseigne_la_fenetre_rx2` |
| Sans plan : RX2 reste une hypothèse du simulateur | `test_sans_plan_regional_rx2_reste_une_hypothese` |
| `downlink_phy` choisit le débit de la fenêtre | `test_downlink_phy_choisit_le_debit_de_la_fenetre` |
| Join-Accept : RX1 ≠ RX2, ordre de grandeur | `test_airtime_join_accept_suit_la_fenetre` |
| ACK : RX1 ≠ RX2, ordre de grandeur | `test_airtime_ack_suit_la_fenetre` |
| Un Join-Accept RX2 occupe l'émetteur selon RX2 | `test_un_join_accept_rx2_occupe_selon_rx2` |
| Une RX1 manquée n'occupe rien, et pas à la durée de RX2 | `test_une_rx1_manquee_noccupe_rien` |
| Un rejeu garde le débit de la fenêtre qui l'a porté | `test_un_rejeu_garde_le_debit_de_la_fenetre_source` |
| ACK visé en RX1 : airtime RX1 | `test_un_ack_vise_en_rx1_prend_l_airtime_de_rx1` |
| ACK visé en RX2 : airtime RX2 | `test_un_ack_vise_en_rx2_prend_l_airtime_de_rx2` |
| ACK tardif : conserve le débit programmé par le réseau | `test_un_ack_tardif_garde_le_debit_programme` |
| Descentes de données : RX1 | `test_les_descentes_de_donnees_restent_en_rx1` |

**Hypothèse résiduelle, documentée :** pour un ACK, la fenêtre est déterminée par l'instant **prêt**
(`ready_ns`), connu avant le placement. Une copie retardée par l'émetteur peut glisser dans la
fenêtre suivante ; son temps d'antenne reste alors celui de la fenêtre visée. Le cas est testé
(`test_un_ack_retarde_par_la_file_garde_le_debit_vise`).
"""

import yaml

from lsim.arbitre import GatewayArbiter
from lsim.join import (JOIN_ACCEPT_DELAY1_NS, JOIN_ACCEPT_DELAY2_NS, RX1, RX2, JoinRadioOptions,
                       accept_airtime_ns, simulate_joins)
from lsim.scenario import load_scenario
from lsim.trace_events import (ProtocolOptions, _downlink_airtime_ns, build_trace, device_radios,
                               downlink_phy)

ACK_TARDIF = "docs/exemples/retransmissions_ack_tardif.yaml"
NOMINAL = "docs/exemples/retransmissions_nominal.yaml"
SECONDE = 1_000_000_000

# Valeurs de référence, EU868, plans vérifiés sur RP002-1.0.5 :
#   RX1 = 868,100 MHz SF9 BW125 · RX2 = 869,525 MHz SF12 BW125 (`plan.rx2()`).
AIRTIME_JOIN_RX1 = 246_784_000      # 0,2468 s
AIRTIME_JOIN_RX2 = 1_810_432_000    # 1,8104 s
AIRTIME_ACK_RX1 = 144_384_000       # 0,1444 s
AIRTIME_ACK_RX2 = 991_232_000       # 0,9912 s


def _scenario(region=None, base=ACK_TARDIF):
    data = yaml.safe_load(open(base, encoding="utf-8"))
    if region is not None:
        data["groups"][0]["region"] = region
    return load_scenario(yaml.safe_dump(data))


def _radio(region="EU868"):
    return device_radios(_scenario(region))[0]


def _join_arbitre(scenario, occupation=(), **reglages):
    """Joue une jointure dans un arbitre où `occupation` est déjà imposée."""
    devices, _, _ = scenario.deploy()
    radios = device_radios(scenario)
    options = JoinRadioOptions(requests_s=(10,), **reglages)
    arbitre = GatewayArbiter(occupation=occupation)
    plan = simulate_joins(devices, scenario.gateway(), scenario.propagation(), radios,
                          ProtocolOptions(), scenario.environment, [(0, 10 * SECONDE)], {},
                          join_options=options, arbiter=arbitre)
    arbitre.resolve()
    return plan.result(), arbitre


# --- le plan régional renseigne RX2 ------------------------------------------------------------

def test_le_plan_regional_renseigne_la_fenetre_rx2():
    """EU868 : RX2 = 869,525 MHz SF12 BW125, distinct de RX1."""
    radio = _radio("EU868")
    assert downlink_phy(radio, RX1) == (868_100_000, 9, 125_000)
    assert downlink_phy(radio, RX2) == (869_525_000, 12, 125_000)
    # RX2 n'est pas RX1 : ni la même fréquence, ni le même débit.
    assert radio.rx2_hz != radio.rx1_hz and radio.rx2_sf != radio.rx1_sf


def test_sans_plan_regional_rx2_reste_une_hypothese():
    """Sans plan, RX2 n'est pas renseignée : SF12 BW125 est l'hypothèse du simulateur."""
    radio = device_radios(_scenario())[0]      # aucun champ `region`
    assert radio.rx2_hz == 0                   # fréquence non renseignée, explicitement
    assert (radio.rx2_sf, radio.rx2_bw_hz) == (12, 125_000)
    # Le débit de repli reste l'hypothèse EU868 déjà utilisée par `_rx2_spreading_factor`.
    assert downlink_phy(radio, RX2) == (0, 12, 125_000)


def test_downlink_phy_choisit_le_debit_de_la_fenetre():
    """`downlink_phy` retourne la physique de la fenêtre demandée, et seulement celle-là."""
    radio = _radio("EU868")
    assert downlink_phy(radio, RX1) != downlink_phy(radio, RX2)
    # Un rejeu réémet la même trame : il garde la fenêtre qui l'a portée (RX1 par défaut).
    assert downlink_phy(radio, "replay") == downlink_phy(radio, RX1)
    # Toute fenêtre inconnue retombe sur RX1, sans lever : c'est le débit programmé.
    assert downlink_phy(radio, "late") == downlink_phy(radio, RX1)


# --- temps d'antenne --------------------------------------------------------------------------

def test_airtime_join_accept_suit_la_fenetre():
    """Join-Accept de 33 octets : 0,2468 s en RX1, 1,8104 s en RX2 (facteur 7,34)."""
    radio = _radio("EU868")
    assert accept_airtime_ns(radio, RX1) == AIRTIME_JOIN_RX1
    assert accept_airtime_ns(radio, RX2) == AIRTIME_JOIN_RX2
    assert accept_airtime_ns(radio, RX2) > 7 * accept_airtime_ns(radio, RX1)
    # Défaut : RX1, pour ne rien changer aux appelants historiques.
    assert accept_airtime_ns(radio) == AIRTIME_JOIN_RX1


def test_airtime_ack_suit_la_fenetre():
    """ACK de 12 octets : 0,1444 s en RX1, 0,9912 s en RX2 (facteur 6,87)."""
    radio = _radio("EU868")
    assert _downlink_airtime_ns(radio, 12, RX1) == AIRTIME_ACK_RX1
    assert _downlink_airtime_ns(radio, 12, RX2) == AIRTIME_ACK_RX2
    assert _downlink_airtime_ns(radio, 12, RX2) > 6 * _downlink_airtime_ns(radio, 12, RX1)
    assert _downlink_airtime_ns(radio, 12) == AIRTIME_ACK_RX1      # défaut RX1


# --- occupation réellement produite -----------------------------------------------------------

def test_un_join_accept_rx2_occupe_selon_rx2():
    """RX1 couverte, RX2 libre : l'émission de secours occupe 1,8104 s, pas 0,2468 s."""
    scenario = _scenario("EU868")
    from lsim.join import JOIN_WINDOW_NS

    rx1 = _join_arbitre(scenario)[0].attempts[0].request_end_ns + JOIN_ACCEPT_DELAY1_NS
    # L'émetteur est occupé sur toute la fenêtre RX1 et au-delà.
    resultat, arbitre = _join_arbitre(
        scenario, occupation=[(rx1 - SECONDE // 10, rx1 + JOIN_WINDOW_NS + SECONDE // 5)])
    tentative = resultat.attempts[0]
    assert [(e.window, e.outcome) for e in tentative.accepts] == [
        (RX1, "gateway_busy"), (RX2, "delivered")]
    join = arbitre.occupation_par_etiquette("join_accept")
    assert join == ((tentative.accepts[1].at_ns,
                     tentative.accepts[1].at_ns + AIRTIME_JOIN_RX2),)


def test_une_rx1_manquee_noccupe_rien():
    """Une RX1 que l'émetteur n'a pas pu placer n'occupe rien, et surtout pas la durée de RX2."""
    scenario = _scenario("EU868")
    from lsim.join import JOIN_WINDOW_NS

    rx1 = _join_arbitre(scenario)[0].attempts[0].request_end_ns + JOIN_ACCEPT_DELAY1_NS
    resultat, arbitre = _join_arbitre(
        scenario, occupation=[(rx1 - SECONDE // 10, rx1 + JOIN_WINDOW_NS + SECONDE // 5)])
    occupations = arbitre.occupation_par_etiquette("join_accept")
    # Une seule émission de Join-Accept : RX1 n'a **rien** émis.
    assert len(occupations) == 1
    assert AIRTIME_JOIN_RX1 not in (fin - debut for debut, fin in occupations)


def test_un_rejeu_garde_le_debit_de_la_fenetre_source():
    """Un rejeu réémet la même trame : même débit, donc même temps d'antenne que l'acceptation."""
    resultat, arbitre = _join_arbitre(_scenario("EU868"), accept_replays=2)
    tentative = resultat.attempts[0]
    assert [(e.window, e.outcome) for e in tentative.accepts] == [
        (RX1, "delivered"), ("replay", "replayed"), ("replay", "replayed")]
    occupations = arbitre.occupation_par_etiquette("join_accept")
    # Acceptation en RX1 : les deux rejeux la suivent au même débit.
    assert [fin - debut for debut, fin in occupations] == [AIRTIME_JOIN_RX1] * 3


# --- ACK : la fenêtre visée décide du débit ---------------------------------------------------

def _ack_occupations(delay_ms, retries=1):
    data = yaml.safe_load(open(NOMINAL, encoding="utf-8"))
    data["retransmissions"].update({"ack_delay_ms": delay_ms, "retries": retries})
    resultat = build_trace(load_scenario(yaml.safe_dump(data)), ProtocolOptions()).retransmissions
    return [fin - debut for debut, fin in resultat.gateway_tx]


def test_un_ack_vise_en_rx1_prend_l_airtime_de_rx1():
    """`ack_delay_ms: 0` → l'ACK est prêt à l'ouverture de RX1 : débit RX1."""
    assert _ack_occupations(0) == [AIRTIME_ACK_RX1] * 2


def test_un_ack_vise_en_rx2_prend_l_airtime_de_rx2():
    """`ack_delay_ms: 1500` → l'ACK est prêt dans RX2 : débit RX2, 6,87 fois plus long.

    Avant la correction, cette émission était chronométrée au débit RX1 : l'occupation de la
    passerelle était sous-estimée d'un facteur 7.
    """
    assert _ack_occupations(1500) == [AIRTIME_ACK_RX2] * 2


def test_un_ack_tardif_garde_le_debit_programme():
    """Au-delà de RX2, le réseau garde le débit qu'il a programmé (RX1) : défaut historique."""
    assert _ack_occupations(2600) == [AIRTIME_ACK_RX1] * 4   # 2 trames × (ACK + réémission)


def test_un_ack_retarde_par_la_file_garde_le_debit_vise():
    """Hypothèse résiduelle, testée : une copie retardée garde le débit de la fenêtre visée.

    Deux copies prêtes au même instant, la seconde poussée après la première : toutes deux
    chronométrées au débit de RX1, alors que la seconde atterrit en réalité plus tard.
    """
    data = yaml.safe_load(open(NOMINAL, encoding="utf-8"))
    data["retransmissions"].update({"ack_delay_ms": 0, "retries": 1, "ack_repetitions": 2})
    resultat = build_trace(load_scenario(yaml.safe_dump(data)), ProtocolOptions()).retransmissions
    durees = [fin - debut for debut, fin in resultat.gateway_tx]
    assert set(durees) == {AIRTIME_ACK_RX1}
    # Les deux copies se suivent dans la file : la seconde part à la fin de la première.
    assert resultat.gateway_tx[1][0] == resultat.gateway_tx[0][1]


# --- descentes de données ---------------------------------------------------------------------

def test_les_descentes_de_donnees_restent_en_rx1():
    """Une descente de données est émise dans la fenêtre RX1 : débit RX1, et non celui de RX2."""
    data = yaml.safe_load(open(NOMINAL, encoding="utf-8"))
    data["retransmissions"].update({"retries": 1})
    scenario = load_scenario(yaml.safe_dump(data))
    radio = device_radios(scenario)[0]
    resultat = build_trace(scenario, ProtocolOptions(downlink_every=1)).retransmissions
    assert resultat.gateway_tx
    durees = {fin - debut for debut, fin in resultat.gateway_tx}
    assert len(durees) == 1
    (observee,) = durees
    # La charge est celle du scénario : on compare les deux fenêtres pour la **même** trame.
    for charge in range(1, 60):
        if _downlink_airtime_ns(radio, charge, RX1) == observee:
            break
    else:
        raise AssertionError("durée observée absente des temps d'antenne RX1 : %d" % observee)
    assert _downlink_airtime_ns(radio, charge, RX2) != observee
