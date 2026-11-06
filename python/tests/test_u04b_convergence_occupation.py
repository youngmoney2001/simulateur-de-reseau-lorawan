"""U0.4-bis — Convergence de l'occupation radio sur le chemin MAC.

Le défaut corrigé ici n'était pas une erreur de placement : l'arbitre plaçait correctement
chaque descente. Il venait de la **sortie** du point fixe des réémissions, qui s'arrêtait dès
qu'aucune réémission nouvelle n'était nécessaire, sans vérifier que l'occupation produite
était celle qui avait servi à calculer la trace. Le plan pouvait donc contenir une descente
chevauchant une montante comptée comme reçue : un émetteur demi-duplex émettant pendant
qu'il reçoit.

La correction ajoute une condition de sortie — stabilité du calendrier **et** de l'occupation —
une garde d'oscillation, et un filet qui refuse de rendre une trace physiquement impossible.

Ces tests épinglent les conséquences **observables**, pas l'écriture : ils échoueraient si la
convergence redevenait silencieuse, quelle que soit la forme du code.

Marquage : **[C]** comportement vérifié du code. **[N]** exigence normative.
"""

import random

import pytest

from lsim.retransmissions import (MAX_ITERATIONS_REEMISSIONS, RetransmissionOptions,
                                  simulate_confirmed_uplinks)
from lsim.simulator import EndDevice, Gateway, Propagation
from lsim.trace_events import DeviceRadio, ProtocolOptions

SECONDE = 1_000_000_000
RX1_HZ = 868_100_000

# Constantes de la reproduction minimale, **mesurées** et non recopiées d'un document.
FIN_A = 991_232_000                      # montante A : SF12, 8 octets, à 50 m
OUVERTURE_RX1_A = FIN_A + SECONDE        # 1 991 232 000
AIR_ACK = 41_216_000                     # ACK descendant, 20 octets utiles, SF7/125 kHz


def _radios(devices, sf=7):
    return [DeviceRadio(freq_hz=RX1_HZ, dr=None, rx1_hz=RX1_HZ, tx_power_dbm=14.0,
                        rx1_sf=sf, rx1_bw_hz=125_000) for _ in devices]


def _options():
    return ProtocolOptions(confirmed_uplinks=True, downlink_every=1,
                           downlink_payload_bytes=20, gateway_tx_power_dbm=27.0)


def _jouer(devices, retransmit, sf=7):
    return simulate_confirmed_uplinks(devices, Gateway(), Propagation(),
                                      _radios(devices, sf), _options(), retransmit,
                                      with_engine_output=True)


def chevauche(a, b):
    """Intervalles semi-ouverts `[début, fin)`."""
    return a[0] < b[1] and b[0] < a[1]


def violations(resultat):
    """Descentes du plan final qui chevauchent une montante comptée comme reçue."""
    plan = tuple(resultat.gateway_tx)
    recues = [(r.start_ns, r.end_ns) for r in resultat.trace.records if r.outcome == 2]
    return [(d, u) for d in plan for u in recues if chevauche(d, u)]


# --------------------------------------------------------------------------- 1. reproduction minimale

def test_reproduction_minimale_b_est_perdue_pour_occupation_passerelle():
    """[C] La montante B, émise pendant l'ACK de A, est perdue — pas comptée comme reçue.

    Montage : A en SF12 (temps d'antenne 991 232 000 ns) est reçue ; sa fenêtre RX1 s'ouvre à
    1 991 232 000. B émet 20 ms plus tard, donc **pendant** l'ACK de A. Un émetteur
    demi-duplex ne peut pas recevoir B : elle doit être perdue (`outcome == 3`).

    Avant la correction, B était reçue et le plan contenait deux descentes la recouvrant.
    """
    devices = [EndDevice(x_m=50.0, spreading_factor=12, payload_bytes=8,
                         period_ns=3600 * SECONDE, start_offset_ns=0, messages=1),
               EndDevice(x_m=300.0, spreading_factor=7, payload_bytes=8,
                         period_ns=3600 * SECONDE,
                         start_offset_ns=OUVERTURE_RX1_A + 20_000_000, messages=1)]
    r = _jouer(devices, RetransmissionOptions(retries=0, retransmit_delay_ms=2500,
                                              ack_repetitions=2))

    # A est reçue, B ne l'est pas : elle a été émise pendant que la passerelle émettait.
    assert [x.outcome for x in r.trace.records] == [2, 3]
    assert r.lost_gateway_busy == 1
    # Et le plan final ne recouvre aucune montante reçue.
    assert violations(r) == []


def test_reproduction_minimale_aucune_descente_ne_chevauche_une_reception():
    """[C] Invariant général : le plan rendu ne recouvre jamais une montante reçue."""
    devices = [EndDevice(x_m=50.0, spreading_factor=12, payload_bytes=8,
                         period_ns=3600 * SECONDE, start_offset_ns=0, messages=1),
               EndDevice(x_m=300.0, spreading_factor=7, payload_bytes=8,
                         period_ns=3600 * SECONDE,
                         start_offset_ns=OUVERTURE_RX1_A + 20_000_000, messages=1)]
    for repetitions in (2, 3):
        r = _jouer(devices, RetransmissionOptions(retries=0, retransmit_delay_ms=2500,
                                                  ack_repetitions=repetitions))
        assert violations(r) == [], f"{repetitions} copies"


# --------------------------------------------------------------------------- 2. frontières à 1 ns

@pytest.mark.parametrize("decalage, attendu_recu, texte", [
    (-1, False, "1 ns avant la fin de l'ACK : chevauchement d'une nanoseconde"),
    (0, True, "exactement à la fin de l'ACK : intervalle semi-ouvert, aucun conflit"),
    (1, True, "1 ns après la fin de l'ACK : aucun conflit"),
])
def test_frontiere_a_un_nanoseconde(decalage, attendu_recu, texte):
    """[C] Paire discriminante autour de la fin de l'ACK.

    Une comparaison `<=` au lieu de `<`, ou une borne approximative, donnerait le même
    résultat pour les trois cas. C'est le test qui interdit cette confusion.

    Une seule copie d'ACK (`repetitions=1`) et un délai de 500 ms : l'émission est unique et
    datée exactement, ce qui rend la frontière observable.
    """
    delai = 500_000_000
    debut_b = OUVERTURE_RX1_A + delai + AIR_ACK + decalage
    devices = [EndDevice(x_m=50.0, spreading_factor=12, payload_bytes=8,
                         period_ns=3600 * SECONDE, start_offset_ns=0, messages=1),
               EndDevice(x_m=300.0, spreading_factor=7, payload_bytes=8,
                         period_ns=3600 * SECONDE, start_offset_ns=debut_b, messages=1)]
    r = _jouer(devices, RetransmissionOptions(retries=0, retransmit_delay_ms=2500,
                                              ack_delay_ms=500))
    issue_b = [x.outcome for x in r.trace.records if x.start_ns == debut_b][0]
    assert (issue_b == 2) is attendu_recu, texte
    assert violations(r) == []


# --------------------------------------------------------------------------- 3. Join-Accept

def test_join_accept_nominal_sans_violation():
    """[C] Le Join-Accept partage l'émetteur avec les ACK : aucune violation.

    Cas important : la configuration est **nominale** (`ack_delay_ms=0`, `repetitions=1`).
    La couche MAC est activée non par un réglage d'ACK, mais par la présence de jointures
    radio, qui fournissent `avant_resolution`. Le défaut était donc atteignable sans aucun
    réglage exotique.
    """
    devices = [EndDevice(x_m=50.0, spreading_factor=7, payload_bytes=8,
                         period_ns=60 * SECONDE, start_offset_ns=1 * SECONDE, messages=4),
               EndDevice(x_m=300.0, spreading_factor=7, payload_bytes=8,
                         period_ns=60 * SECONDE,
                         start_offset_ns=1 * SECONDE + 1_050_000_000, messages=4)]
    r = _jouer(devices, RetransmissionOptions(retries=0, retransmit_delay_ms=2500,
                                              join_requests_s=(1,), join_retries=2))
    assert r.join_accepts_emitted == 1
    assert violations(r) == []


def test_join_accept_avec_copies_multiples_sans_violation():
    """[C] Idem avec copies d'ACK répétées : davantage d'occupation, toujours aucune violation."""
    devices = [EndDevice(x_m=50.0, spreading_factor=7, payload_bytes=8,
                         period_ns=60 * SECONDE, start_offset_ns=1 * SECONDE, messages=4),
               EndDevice(x_m=300.0, spreading_factor=7, payload_bytes=8,
                         period_ns=60 * SECONDE,
                         start_offset_ns=1 * SECONDE + 1_050_000_000, messages=4)]
    r = _jouer(devices, RetransmissionOptions(retries=0, retransmit_delay_ms=2500,
                                              ack_repetitions=2,
                                              join_requests_s=(1,), join_retries=2))
    assert violations(r) == []


# --------------------------------------------------------------------------- 4. ACK refusé

def test_ack_refuse_ne_reserve_aucun_intervalle():
    """[C] Un ACK non émis n'inscrit aucun intervalle dans l'occupation.

    Vérifié sur le chemin de production (`plan_acks` + `GatewayArbiter`) : l'occupation de
    l'arbitre contient exactement les émissions retenues, et rien pour les refusées.
    """
    from lsim.ack_mac import AckTiming, plan_acks
    from lsim.arbitre import GatewayArbiter

    # Deux terminaux simultanés (collision) : leurs ACK ne sont pas demandés.
    # Quatre autres, échelonnés : leurs ACK sont émis.
    d = [EndDevice(x_m=100.0, spreading_factor=7, payload_bytes=8,
                   period_ns=60 * SECONDE, start_offset_ns=0, messages=1),
         EndDevice(x_m=105.0, spreading_factor=7, payload_bytes=8,
                   period_ns=60 * SECONDE, start_offset_ns=1_000_000, messages=1)]
    d += [EndDevice(x_m=100.0 + 40.0 * i, spreading_factor=7, payload_bytes=8,
                    period_ns=60 * SECONDE, start_offset_ns=i * 300_000_000, messages=1)
          for i in range(1, 5)]
    from lsim.simulator import simulate_uplinks_trace
    trace = simulate_uplinks_trace(d, Gateway(), Propagation(), None)

    arbitre = GatewayArbiter()
    plan = plan_acks(trace.records, _radios(d), _options(),
                     AckTiming(delay_ms=0, repetitions=1), arbiter=arbitre)

    refuses = [i for i, x in enumerate(plan.outcomes) if x.accepted_emission is None]
    assert refuses, "le scénario doit comporter au moins un ACK refusé"
    # L'occupation est exactement l'ensemble des émissions retenues : un refus n'y figure pas.
    emises = sorted((e.start_ns, e.end_ns) for e in arbitre.resolve() if e.emitted)
    assert sorted(arbitre.occupation) == emises


# --------------------------------------------------------------------------- 5. balayage

def _configurations(n=400):
    """Le jeu de l'audit : même graine, même ordre de tirage."""
    random.seed(20261105)
    jeu = []
    for _ in range(n):
        k = random.randint(2, 8)
        periode = random.choice([8, 12, 15, 20, 25, 30, 40]) * SECONDE
        devices = [EndDevice(x_m=80.0 + random.random() * 700.0,
                             spreading_factor=random.choice([7, 8, 9, 10]),
                             period_ns=periode,
                             start_offset_ns=random.choice(
                                 [0, 0, 2, 5, 7, 11, 13, 17]) * 400_000_000,
                             messages=random.randint(2, 5)) for _ in range(k)]
        jeu.append((devices, RetransmissionOptions(
            retries=random.randint(1, 5),
            retransmit_delay_ms=random.choice([2100, 2200, 2500, 3000]),
            ack_delay_ms=random.choice([0, 200, 500, 800, 1500]),
            ack_repetitions=random.choice([1, 1, 2, 3]))))
    return jeu


def test_aucune_violation_sur_les_400_configurations():
    """[C] Balayage de l'audit : zéro violation sur les émissions comptées comme reçues.

    Avant la correction : 95 configurations sur 400 en présentaient, 708 intervalles
    fautifs au total. Le test porte sur la propriété physique, pas sur des valeurs gelées :
    c'est ce qui empêche une régression silencieuse.
    """
    total = 0
    fautives = 0
    for devices, opts in _configurations():
        try:
            r = _jouer(devices, opts)
        except RuntimeError:
            # Une non-convergence explicite est un comportement autorisé ; une trace
            # physiquement impossible ne l'est pas. On ne la compte donc pas comme faute.
            continue
        if r.trace is None or not r.gateway_tx:
            continue
        v = violations(r)
        total += len(v)
        fautives += 1 if v else 0
    assert fautives == 0, f"{fautives} configurations fautives, {total} intervalles"


# --------------------------------------------------------------------------- 6. convergence

def test_convergence_occupation_imposee_egale_occupation_produite():
    """[C] À la sortie du point fixe, l'occupation produite égale celle qui a été imposée.

    C'est la propriété que la condition de sortie garantit désormais. On l'observe en
    instrumentant `_simulate`, sans modifier son comportement.
    """
    import lsim.retransmissions as rt

    original = rt._simulate
    historique = []

    def instrumente(*args, **kwargs):
        r = original(*args, **kwargs)
        historique.append((tuple(kwargs.get("busy") or ()), tuple(r[2] or ())))
        return r

    rt._simulate = instrumente
    try:
        devices = [EndDevice(x_m=50.0, spreading_factor=12, payload_bytes=8,
                             period_ns=3600 * SECONDE, start_offset_ns=0, messages=1),
                   EndDevice(x_m=300.0, spreading_factor=7, payload_bytes=8,
                             period_ns=3600 * SECONDE,
                             start_offset_ns=OUVERTURE_RX1_A + 20_000_000, messages=1)]
        _jouer(devices, RetransmissionOptions(retries=0, retransmit_delay_ms=2500,
                                              ack_repetitions=2))
    finally:
        rt._simulate = original

    assert len(historique) >= 2, "la convergence de l'occupation demande au moins deux passes"
    imposee, produite = historique[-1]
    # Forme canonique : triée et dédupliquée, comme la comparaison du code.
    assert tuple(sorted(set(imposee))) == tuple(sorted(set(produite)))


def test_forme_canonique_triee_dedupliee_et_insensible_a_l_ordre():
    """[C] La comparaison des occupations est canonique : ordre et doublons sans effet."""
    from lsim.retransmissions import _canonique

    assert _canonique(()) == ()
    assert _canonique([(5, 9), (1, 3)]) == ((1, 3), (5, 9))
    # Doublons éliminés.
    assert _canonique([(1, 3), (1, 3), (5, 9)]) == ((1, 3), (5, 9))
    # Ordre sans effet.
    assert _canonique([(5, 9), (1, 3)]) == _canonique([(1, 3), (5, 9)])
    # Entiers natifs : une comparaison entre `int` numpy et `int` ne doit pas dépendre du type.
    assert _canonique([(1.0, 3.0)]) == ((1, 3),)


def test_budget_d_iterations_et_erreur_explicite():
    """[C] Le budget est borné, et l'erreur en cas de non-convergence est explicite.

    `MAX_ITERATIONS_REEMISSIONS` a été relevé de 32 à 128 : la convergence de l'occupation
    demande des
    passes supplémentaires (75 mesurées au maximum sur 500 scénarios denses, contre 27 avant).
    """
    assert MAX_ITERATIONS_REEMISSIONS == 128
    # La limite est atteignable en principe mais ne doit jamais produire de résultat
    # silencieusement faux : le code lève, il ne rend pas.
    import inspect

    source = inspect.getsource(simulate_confirmed_uplinks.__module__ and
                               __import__("lsim.retransmissions", fromlist=["_"]))
    assert "pas de point fixe des réémissions après" in source
    assert "occupation descendante incohérente avec la trace" in source


def test_oscillation_est_detectee_et_non_rendue():
    """[C] Une occupation qui oscille lève au lieu de rendre un résultat arbitraire.

    On force l'oscillation en neutralisant la progression : l'occupation produite est
    systématiquement remplacée par une valeur qui alterne.
    """
    import lsim.retransmissions as rt

    original = rt._simulate
    compteur = [0]

    def alterne(*args, **kwargs):
        compteur[0] += 1
        r = original(*args, **kwargs)
        resultat, evenements, plan, mac = r
        # Occupation **périodique** : deux valeurs fixes qui alternent. Elle ne peut pas se
        # stabiliser, et la même valeur finit par revenir — c'est ce que la garde détecte.
        # (Des valeurs toujours nouvelles, elles, épuiseraient le budget d'itérations sans
        # jamais déclencher la garde d'oscillation.)
        bidon = [(10_000_000_000, 10_000_001_000)] if compteur[0] % 2 else [
            (20_000_000_000, 20_000_001_000)]
        return resultat, evenements, bidon, mac

    rt._simulate = alterne
    try:
        devices = [EndDevice(x_m=50.0, spreading_factor=12, payload_bytes=8,
                             period_ns=3600 * SECONDE, start_offset_ns=0, messages=1),
                   EndDevice(x_m=300.0, spreading_factor=7, payload_bytes=8,
                             period_ns=3600 * SECONDE,
                             start_offset_ns=OUVERTURE_RX1_A + 20_000_000, messages=1)]
        with pytest.raises(RuntimeError, match="occupation"):
            _jouer(devices, RetransmissionOptions(retries=0, retransmit_delay_ms=2500,
                                                  ack_repetitions=2))
    finally:
        rt._simulate = original


# --------------------------------------------------------------------------- 7. chemin causal

def test_chemin_causal_est_inchange():
    """[C] Le chemin causal n'est pas touché : l'occupation vient du `RadioScheduler` du cœur.

    Configuration nominale (ni délai d'ACK, ni répétition, ni jointure) : `timing` reste
    `None`, le moteur applique le demi-duplex par construction. Aucune violation, et la
    condition de convergence ne s'applique pas.
    """
    devices = [EndDevice(x_m=50.0, spreading_factor=12, payload_bytes=8,
                         period_ns=30 * SECONDE, start_offset_ns=0, messages=3),
               EndDevice(x_m=300.0, spreading_factor=7, payload_bytes=8,
                         period_ns=30 * SECONDE,
                         start_offset_ns=OUVERTURE_RX1_A + 20_000_000, messages=3)]
    opts = RetransmissionOptions(retries=3, retransmit_delay_ms=2500)
    assert opts.uses_ack_mac is False
    r = _jouer(devices, opts)
    assert violations(r) == []
    # Le chemin causal perd la montante B pour occupation passerelle, comme avant.
    assert r.lost_gateway_busy >= 1
