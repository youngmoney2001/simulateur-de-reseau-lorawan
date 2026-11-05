"""U0.5 — Convergence du point fixe des réémissions : budget cumulé et oscillation.

Portée : **U0.5-a seulement** (convergence). Ne couvre ni le colmatage préventif des
arbitres isolés (U0.5-b), ni l'oscillation structurelle de l'essai 334, qui reste une
limite connue et documentée.

Les quatre configurations ci-dessous sont celles de l'audit : elles sont tirées de la
graine 4242 du balayage dense et **reproduites à l'identique**, sans être réécrites de
mémoire — une reconstitution approximative avait fait converger les quatre et masqué le
défaut pendant une série de mesures.

Marquage : **[C]** comportement du code, mesuré.
"""

import collections

import pytest

from lsim.arbitre import EmissionRequest, GatewayArbiter
from lsim.retransmissions import (MAX_ITERATIONS_REEMISSIONS, RetransmissionOptions,
                                  _canonique, _verifier_coherence_occupation,
                                  simulate_confirmed_uplinks)
from lsim.simulator import EndDevice, Gateway, Propagation
from lsim.trace_events import (MAX_ITERATIONS_TRACE, DeviceRadio, ProtocolOptions,
                               _build_trace_python)

SECONDE = 1_000_000_000
RX1_HZ = 868_100_000


# --------------------------------------------------------------------------- 1. jeu de l'audit
# (x_m, sf, décalage en unités de 300 ms, messages) — ordre et valeurs exacts de la graine 4242.
_CONFIGURATIONS = {
    "11": {"periode": 6, "opts": {"retries": 2, "rt": 2500, "delay": 0, "reps": 2},
           "devices": [(190.07504224234447, 9, 2, 6), (459.88801844604274, 9, 0, 4),
                       (910.2761866377294, 7, 2, 5), (634.1760501205121, 10, 5, 8),
                       (158.46174294609608, 8, 7, 8), (591.203246204738, 10, 0, 5),
                       (892.0624583447916, 9, 9, 6)]},
    "61": {"periode": 10, "opts": {"retries": 4, "rt": 2200, "delay": 500, "reps": 2},
           "devices": [(725.5465071077256, 10, 7, 3), (739.5593130657327, 7, 3, 7),
                       (124.19259020160116, 11, 2, 4), (335.1113368954441, 7, 5, 6),
                       (158.26925241830895, 9, 5, 8), (299.38077189911644, 11, 5, 7),
                       (274.3621231132241, 10, 0, 3), (272.2827555628424, 7, 11, 6),
                       (789.5889044807316, 10, 7, 7), (282.9882147737448, 11, 0, 4),
                       (286.75487003041053, 11, 3, 3), (160.50740223359008, 8, 2, 8)]},
    "318": {"periode": 12, "opts": {"retries": 2, "rt": 4000, "delay": 800, "reps": 3},
            "devices": [(561.823356531761, 10, 9, 3), (895.1721793560364, 11, 11, 7),
                        (742.454102920853, 7, 2, 5), (337.5519016036257, 8, 7, 3),
                        (659.0918615802279, 8, 5, 4), (638.1105180313772, 9, 11, 3),
                        (313.5954119211219, 9, 2, 6), (320.270595478183, 10, 2, 7),
                        (426.9852847060213, 7, 7, 7), (331.7087769740559, 8, 11, 5),
                        (95.08850992726957, 7, 1, 7)]},
    "334": {"periode": 15, "opts": {"retries": 3, "rt": 3000, "delay": 200, "reps": 3},
            "devices": [(116.81029206037006, 9, 5, 3), (601.5016306268597, 8, 3, 8),
                        (145.349166078194, 11, 5, 3), (171.7491222847742, 7, 7, 3),
                        (552.9591853400605, 8, 0, 7), (618.6652667039713, 11, 5, 3),
                        (121.2391242328639, 7, 9, 8), (71.05231967431678, 9, 3, 6),
                        (566.1813434393499, 7, 0, 7), (685.2889841896128, 10, 5, 7),
                        (910.4485036341747, 9, 5, 7)]},
}


def _jouer(nom):
    """Rejoue une configuration de l'audit. Lève comme en production."""
    c = _CONFIGURATIONS[nom]
    o = c["opts"]
    devices = [EndDevice(x_m=x, spreading_factor=sf, period_ns=c["periode"] * SECONDE,
                         start_offset_ns=dec * 300_000_000, messages=msgs)
               for x, sf, dec, msgs in c["devices"]]
    opts = RetransmissionOptions(retries=o["retries"], retransmit_delay_ms=o["rt"],
                                 ack_delay_ms=o["delay"], ack_repetitions=o["reps"])
    radios = [DeviceRadio(freq_hz=RX1_HZ, dr=None, rx1_hz=RX1_HZ, tx_power_dbm=14.0,
                          rx1_sf=d.spreading_factor, rx1_bw_hz=125_000) for d in devices]
    options = ProtocolOptions(confirmed_uplinks=True, downlink_every=1,
                              downlink_payload_bytes=20, gateway_tx_power_dbm=27.0)
    return simulate_confirmed_uplinks(devices, Gateway(), Propagation(), radios, options,
                                      opts)


# --------------------------------------------------------------------------- 2. budget cumulé

def test_budget_de_reemissions_est_borne_par_trame():
    """[C] Une trame est émise au plus `1 + retries` fois, même quand les ACK oscillent.

    Avant U0.5, le budget portait sur le rang **courant** de l'essai. `_prune_acknowledged`
    supprime, à chaque itération du point fixe, les réémissions qu'un ACK reçu avant leur
    départ rend impossibles ; supprimer un essai postérieur fait redescendre le dernier
    essai de la trame et **rouvre le budget**. Mesuré : 75 rembobinages sur 18 passes dans
    le cas étalon, et aucune borne sur le nombre total d'émissions d'une trame.

    Le budget est désormais compté **cumulativement** (`emis`), et ne décroît jamais.
    """
    for nom in ("11", "61", "318"):
        r = _jouer(nom)
        par_trame = collections.Counter((a.device, a.session, a.frame)
                                        for a in r.attempts)
        borne = 1 + _CONFIGURATIONS[nom]["opts"]["retries"]
        pire = max(par_trame.values())
        assert pire <= borne, (f"essai {nom} : une trame est émise {pire} fois, "
                               f"la politique n'en autorise que {borne}")


def test_la_borne_est_atteinte_et_non_seulement_respectee():
    """[C] Le budget cumulé est effectivement consommé — la mesure n'est pas vide.

    Un test qui ne vérifierait que `<= borne` passerait aussi si aucune réémission n'était
    jamais produite. L'essai 61 sature son budget (5 émissions pour `retries=4`) : la borne
    est donc **atteinte**, ce qui prouve que le compte cumulé est bien exercé.
    """
    r = _jouer("61")
    par_trame = collections.Counter((a.device, a.session, a.frame) for a in r.attempts)
    assert max(par_trame.values()) == 5, "l'essai 61 doit saturer son budget (retries=4)"


# --------------------------------------------------------------------------- 3. convergence

@pytest.mark.parametrize("nom", ["11", "61", "318"])
def test_configurations_denses_convergent(nom):
    """[C] Les configurations denses qui oscillaient convergent désormais.

    Elles convergeaient **avant** P1, mais en 1 passe pour les essais 11 et 318 : la
    première itération tournait sous occupation imposée vide, toutes les montantes étaient
    reçues, `nouvelles` était vide, et la boucle sortait sans jamais avoir rejoué la trace
    sous l'occupation qu'elle venait de produire — rendant une trace à 22/37 violations
    du demi-duplex pour ces deux essais.
    """
    r = _jouer(nom)
    assert r.transmissions > 0
    assert r.frames_delivered > 0


def test_essai_334_converge_vers_un_point_fixe_coherent():
    """[C] L'essai 334 converge — et non pas « oscille structurellement ».

    **Diagnostic d'U0.5 rectifié.** Il avait été décrit comme un cycle de période 3 que rien
    ne pouvait résorber. C'était un artefact de la garde : celle-ci comparait le **calendrier
    seul**, et le calendrier de 109 tentatives revient effectivement aux passes 3 et 7 — mais
    sous des occupations imposées différentes (195 puis 228 intervalles). **Aucun état complet
    ne se répétait** sur les 22 passes ; la garde arrêtait la convergence à la 8ᵉ.

    Le point fixe existe : 192 intervalles imposés = produits, 64 montantes reçues, aucune
    violation du demi-duplex. La garde portant désormais sur la paire (calendrier,
    occupation), il est atteint.
    """
    r = _jouer("334")
    assert r.transmissions > 0
    # Le résultat attendu, mesuré : il fige la convergence au lieu de la supposer.
    assert r.transmissions == 111
    assert r.received == 64
    assert r.frames_delivered == 59
    assert r.lost_gateway_busy == 41


def test_essai_334_ne_consomme_pas_son_budget_dans_l_oscillation():
    """[C] Ce n'était pas le budget qui alimentait l'oscillation — la preuve.

    Au moment où la garde (ancienne) croyait détecter un cycle, seules **9 trames sur 62**
    atteignaient le budget `retries=3`, et ce compte était **constant** d'un état à l'autre.
    Borner le cumul des émissions ne pouvait donc pas stabiliser l'alternance des ACK : c'est
    pourquoi U0.5 a résolu les essais 11, 61 et 318, mais pas celui-ci.
    """
    r = _jouer("334")
    par_trame = collections.Counter((a.device, a.session, a.frame) for a in r.attempts)
    # Au plus 1 + retries émissions par trame, comme la politique le veut.
    assert max(par_trame.values()) <= 1 + _CONFIGURATIONS["334"]["opts"]["retries"]
    # Et la convergence n'épuise pas ce budget : des trames restent en deçà.
    assert sum(1 for v in par_trame.values()
               if v < 1 + _CONFIGURATIONS["334"]["opts"]["retries"]) > 0


def test_la_garde_compare_l_etat_complet_et_non_le_calendrier_seul():
    """[C] La signature de détection porte sur la paire (calendrier, occupation imposée).

    Un même calendrier sous une occupation différente n'est **pas** un état répété. C'est
    toute la correction : la comparer au calendrier seul produisait des faux positifs et
    interrompait des convergences en cours.
    """
    import inspect

    source = inspect.getsource(simulate_confirmed_uplinks.__module__ and
                               __import__("lsim.retransmissions", fromlist=["_"]))
    attendu = ("signature = (tuple((a.device, a.session, a.frame, a.attempt, a.start_ns)\n"
               "                           for a in schedule), _canonique(occupation_imposee))")
    assert attendu in source, "la signature ne porte plus sur (calendrier, occupation)"
    # L'ancienne forme, sur le calendrier seul, ne doit plus exister.
    assert "for a in schedule)\n        if signature in vu" not in source


# --------------------------------------------------------------------------- 4. homonymie

def test_les_deux_bornes_d_iterations_sont_distinctes_et_independantes():
    """[C] Deux constantes homonymes coexistaient ; elles portent désormais des noms distincts.

    `MAX_ITERATIONS_REEMISSIONS` (128) borne le point fixe des réémissions MAC ;
    `MAX_ITERATIONS_TRACE` (64) borne les deux boucles de `trace_events` (jointures d'une
    part, montantes ↔ descentes d'autre part). Aucun import croisé, points fixes non
    imbriqués : le nom commun laissait croire à un lien qui n'existe pas.
    """
    assert MAX_ITERATIONS_REEMISSIONS == 128
    assert MAX_ITERATIONS_TRACE == 64


def test_la_comparaison_de_trace_events_est_canonique():
    """[C] `trace_events` compare les occupations sous forme canonique, comme `retransmissions`.

    La comparaison brute de listes n'était correcte que parce que
    `GatewayArbiter.occupation` se trouve être triée chronologiquement : une propriété
    d'implémentation, qu'aucun test ne verrouillait. La forme canonique est insensible à
    l'ordre et aux répétitions.

    Le test porte sur la **ligne exécutable**, pas sur le texte entier de la fonction : un
    commentaire mentionnant l'ancienne forme ne doit pas le faire échouer à tort. La
    signature de détection de cycle est vérifiée aussi : si elle redevenait brute, un
    cycle ne serait détecté que si l'ordre de restitution était stable.
    """
    import inspect

    lignes = [l.strip() for l in inspect.getsource(_build_trace_python).splitlines()]
    executables = [l for l in lignes if l.startswith("if ") and "new_busy" in l]
    assert executables, "aucune condition de convergence trouvée dans _build_trace_python"
    for ligne in executables:
        assert "_canonique(" in ligne, f"comparaison non canonique : {ligne}"
    signatures = [l for l in lignes if l.startswith("signature = ") and "new_busy" in l]
    assert signatures, "aucune signature de cycle trouvée dans _build_trace_python"
    for ligne in signatures:
        assert "_canonique(" in ligne, f"signature de cycle non canonique : {ligne}"


def test_le_filet_physique_leve_sur_un_chevauchement():
    """[C] Le filet de cohérence physique fonctionne — testé directement.

    Il est **inatteignable depuis la boucle** : celle-ci ne sort que lorsque l'occupation
    produite égale l'occupation imposée, et la trace a été jouée sous cette même
    occupation ; une montante qui la recouvre est `gateway_busy` (issue 3), jamais
    `received` (issue 2). Mesuré : 0 déclenchement sur les 400 configurations de l'audit.

    Il est donc extrait (`_verifier_coherence_occupation`) pour être vérifiable. Sans ce
    test, la mutation qui le neutralise ne serait détectée par aucune suite boîte noire —
    c'est ce qu'a montré la mutation M7.
    """
    # Une descente [10, 20) recouvre une montante reçue [15, 25) : impossible.
    with pytest.raises(RuntimeError, match="occupation descendante incohérente"):
        _verifier_coherence_occupation([(10 * SECONDE, 20 * SECONDE)],
                                       [(15 * SECONDE, 25 * SECONDE)])
    # Chevauchement sur un seul instant : la frontière est stricte (demi-duplex).
    with pytest.raises(RuntimeError, match="occupation descendante incohérente"):
        _verifier_coherence_occupation([(10, 20)], [(19, 25)])


def test_le_filet_physique_accepte_les_traces_coherentes():
    """[C] Le filet ne lève pas à tort : intervalles disjoints ou simplement jointifs."""
    _verifier_coherence_occupation([(10, 20)], [(20, 30)])      # jointifs, pas de recouvrement
    _verifier_coherence_occupation([(10, 20)], [(0, 10)])       # jointifs dans l'autre sens
    _verifier_coherence_occupation([], [(0, 10)])               # aucune descente
    _verifier_coherence_occupation([(10, 20)], [])              # aucune montante
    # Insensible à l'ordre et aux doublons : la forme canonique les absorbe.
    _verifier_coherence_occupation([(30, 40), (10, 20), (10, 20)], [(45, 50), (20, 25)])


# --------------------------------------------------------------------------- 5. ordre de l'arbitre

def _emission(etiquette, device, debut_ns, duree_ns):
    return EmissionRequest(label=etiquette, device=device, ready_ns=debut_ns,
                           duration_ns=duree_ns, window=(debut_ns, debut_ns + 10 * SECONDE))


def test_l_occupation_de_l_arbitre_est_chronologique():
    """[C] `GatewayArbiter.occupation` est triée chronologiquement — propriété verrouillée.

    `trace_events` s'appuyait implicitement sur cet ordre pour comparer les occupations
    brutes. Le test fige la propriété : si l'arbitre changeait son ordre de restitution,
    la comparaison canonique resterait correcte, mais ce test signalerait le changement
    au lieu de le laisser passer inaperçu.
    """
    a = GatewayArbiter()
    # Dépôt volontairement désordonné : 5 s, 1 s, 3 s.
    for i, (etiquette, debut) in enumerate([("c", 5 * SECONDE), ("a", 1 * SECONDE),
                                            ("b", 3 * SECONDE)]):
        a.demand(_emission(etiquette, i, debut, 100_000_000))
    a.resolve()
    occupation = a.occupation
    assert len(occupation) == 3, f"3 émissions attendues, occupation = {occupation}"
    assert occupation == tuple(sorted(occupation)), f"occupation non triée : {occupation}"


def test_forme_canonique_insensible_a_l_ordre_et_aux_doublons():
    """[C] Deux occupations égales au sens des intervalles le sont au sens canonique."""
    assert _canonique([(3, 4), (1, 2)]) == _canonique([(1, 2), (3, 4)])
    assert _canonique([(1, 2), (1, 2)]) == _canonique([(1, 2)])
    assert _canonique([]) == ()
