"""U0.4 — Occupation radio : source unique, refus sans réservation, et mécanismes MAC non contournables.

Le jalon porte sur la **cohérence** de l'occupation entre les chemins de simulation, pas sur de
nouvelles règles radio. Trois propriétés sont épinglées ici :

1. **Une source.** L'occupation publiée par le chemin causal est celle de l'ordonnanceur radio,
   dérivée et non reconstituée. Avant U0.4, le moteur entretenait une liste `planned` alimentée par
   les valeurs de retour du planificateur : le placement décidait sur un état, le demi-duplex
   lisait l'autre, et rien ne vérifiait leur égalité.

2. **Un refus ne réserve rien.** Une demande non émise n'inscrit aucun intervalle, ni dans
   l'ordonnanceur radio, ni dans l'arbitre Python. C'est l'exigence 6 du mandat.

3. **Aucun contournement silencieux.** Les mécanismes MAC — ACK, Join-Accept, réémission — passent
   par un émetteur unique (`GatewayArbiter`) ou par l'ordonnanceur radio. Une demande ne peut pas
   être émise par-dessus une émission déjà acceptée, quel que soit le producteur.

Les scènes sont construites par paires ne différant que d'une nanoseconde, comme en U0.3 : c'est
ce qui interdit de remplacer le chevauchement réel par une borne approximative.

Marquage : **[C]** comportement vérifié du code, **[N]** exigence normative (TS001-1.0.4).
"""

import pytest

from lsim.arbitre import (DECALE, EXACTE, DownlinkDutyCycle, EmissionRequest, GatewayArbiter)
from lsim.downlink_plan import DeviceRx2, plan_native_v2, simulate_causal
from lsim.simulator import EndDevice, Gateway, Propagation
from lsim.trace_events import DeviceRadio, ProtocolOptions

SECONDE = 1_000_000_000
RX1_HZ = 868_100_000
RX2_HZ = 869_525_000


def _radio(sf=7, rx2_sf=12):
    return DeviceRadio(freq_hz=RX1_HZ, dr=None, rx1_hz=RX1_HZ, tx_power_dbm=14.0,
                       rx1_sf=sf, rx1_bw_hz=125_000,
                       rx2_hz=RX2_HZ, rx2_sf=rx2_sf, rx2_bw_hz=125_000)


def _options(repli=False, charge=20):
    return ProtocolOptions(confirmed_uplinks=True, downlink_every=1,
                           downlink_payload_bytes=charge, gateway_tx_power_dbm=27.0,
                           rx2_fallback=repli)


def _table(n, sf=12):
    return [DeviceRx2(RX2_HZ, sf, 125_000) for _ in range(n)]


# --------------------------------------------------------------------------- 1. source unique

def test_occupation_causale_egale_celle_du_planificateur():
    """[C] Le moteur causal et le planificateur par lot publient exactement la même occupation.

    C'est l'égalité que le point fixe de `trace_events` exige déjà ; elle est épinglée ici comme
   	test de premier niveau, pour qu'une divergence se lise sans remonter au point fixe.
    """
    devices = [EndDevice(x_m=100.0 + 30.0 * i, spreading_factor=7,
                         start_offset_ns=i * 50_000_000,
                         period_ns=10 * SECONDE, messages=8) for i in range(12)]
    radios = [_radio() for _ in devices]
    options = _options(repli=True)
    table = _table(len(devices))

    trace_c, busy_c = simulate_causal(devices, Gateway(), Propagation(), None, radios,
                                      options, None, None, table)
    trace_p, busy_p = plan_native_v2(trace_c.records, radios, options, table)

    assert tuple(busy_c) == tuple(busy_p)
    assert len(busy_c) == 56            # valeur de référence P5 (U0.3), non modifiée par U0.4
    # Croissante et disjointe : contrat exigé par `transmitting_in`, désormais garanti par
    # construction et non par accident d'ordre d'insertion.
    for a, b in zip(busy_c, busy_c[1:]):
        assert a[1] <= b[0]


def test_scenario_sans_descente_ne_publie_aucune_occupation():
    """[C] Aucune descente ⇒ aucune occupation, et aucune perte pour cause d'émission passerelle.

    Invariance exigée par l'arbitrage 3 (empreintes gelées).
    """
    devices = [EndDevice(x_m=100.0 + 30.0 * i, spreading_factor=7,
                         start_offset_ns=i * 50_000_000,
                         period_ns=10 * SECONDE, messages=8) for i in range(12)]
    radios = [_radio() for _ in devices]
    options = ProtocolOptions(confirmed_uplinks=False, downlink_every=0,
                              downlink_payload_bytes=0, gateway_tx_power_dbm=27.0,
                              rx2_fallback=False)

    _trace, busy = simulate_causal(devices, Gateway(), Propagation(), None, radios,
                                   options, None, None, _table(len(devices)))
    assert busy == ()
    reçus = sum(1 for r in _trace.records if r.outcome == 2)
    assert reçus == 96


# --------------------------------------------------------------------------- 2. refus sans réservation

def test_demande_hors_fenetre_ne_reserve_aucune_ressource():
    """[C] Une demande dont la fenêtre est masquée n'est pas émise et n'inscrit aucun intervalle.

    Exigence 6 du mandat U0.4. On compare l'occupation de l'arbitre avant et après : elle doit
    être identique, au nanoseconde près.
    """
    occupation_initiale = ((10 * SECONDE, 10 * SECONDE + 500_000_000),)
    arbitre = GatewayArbiter(occupation=occupation_initiale, regle_placement=DECALE)

    # Une demande prête avant l'occupation existante, mais dont la fenêtre se ferme avant la fin
    # de celle-ci : le placement tomberait après la fermeture, la demande n'est pas émise.
    demande = EmissionRequest(label="ack", device=0, ready_ns=10 * SECONDE,
                              duration_ns=56_576_000,
                              window=(10 * SECONDE, 10 * SECONDE + 500_000_000),
                              allow_late=False, freq_hz=RX1_HZ)
    arbitre.demand(demande)
    emissions = arbitre.resolve()

    non_emises = [e for e in emissions if not e.emitted]
    assert non_emises, "la demande aurait dû être refusée"
    # **Aucune** occupation supplémentaire : un refus ne réserve rien.
    assert arbitre.occupation == tuple(sorted(occupation_initiale))


def test_arbitre_amorce_par_une_occupation_est_respectee():
    """[C] Une occupation fournie à l'arbitre est effectivement respectée par les demandes.

    C'est le mécanisme par lequel un producteur tardif (ACK, join) voit l'occupation déjà établie
    au lieu de la ignorer. Sans lui, un `GatewayArbiter()` neuf permettrait d'émettre par-dessus
    des descentes déjà acceptées.
    """
    occupe = ((5 * SECONDE, 5 * SECONDE + 300_000_000),)
    arbitre = GatewayArbiter(occupation=occupe, regle_placement=DECALE)

    # Une demande qui tombe **dans** l'intervalle occupé.
    dedans = EmissionRequest(label="downlink", device=0, ready_ns=5 * SECONDE + 100_000_000,
                             duration_ns=56_576_000,
                             window=(5 * SECONDE, 6 * SECONDE),
                             allow_late=True, freq_hz=RX1_HZ)
    # Une demande **après** l'intervalle occupé.
    apres = EmissionRequest(label="downlink", device=0, ready_ns=6 * SECONDE,
                            duration_ns=56_576_000,
                            window=(6 * SECONDE, 7 * SECONDE),
                            allow_late=True, freq_hz=RX1_HZ)
    arbitre.demand(dedans)
    arbitre.demand(apres)
    emissions = arbitre.resolve()

    émises = [(e.start_ns, e.end_ns)
              for e in emissions if e.emitted]
    # L'émission « dedans » est repoussée **après** la fin de l'occupation : elle ne la chevauche
    # jamais. Le placement exact (A6) interdirait ce report ; c'est la règle DECALE, encore
    # utilisée par les couches MAC non migrées, qui l'autorise.
    for debut, fin in émises:
        assert not (debut < occupe[0][1] and occupe[0][0] < fin), \
            "une émission chevauche l'occupation fournie"
    # Deux demandes, deux émissions : aucune n'a été perdue.
    assert len(émises) == 2


def test_ack_ne_peut_pas_emettre_par_dessus_une_occupation_imposee():
    """[C] Un ACK déposé dans un arbitre partagé ne peut pas être émis pendant une émission.

    Exigence du mandat : « les mécanismes ACK, join et réémission ne peuvent pas contourner
    silencieusement l'état d'occupation ». Le contournement consisterait à créer un arbitre neuf,
    ignorant l'occupation ; celle-ci est justement le paramètre qui l'interdit.
    """
    occupation = [(2 * SECONDE, 2 * SECONDE + 400_000_000)]
    arbitre_partage = GatewayArbiter(occupation=occupation, regle_placement=DECALE)

    ack = EmissionRequest(label="ack", device=0, ready_ns=2 * SECONDE + 50_000_000,
                          duration_ns=56_576_000,
                          window=(2 * SECONDE, 2 * SECONDE + 500_000_000),
                          allow_late=True, freq_hz=RX1_HZ)
    arbitre_partage.demand(ack)
    emissions = arbitre_partage.resolve()
    émise = [e for e in emissions if e.emitted]
    assert émise
    debut = émise[0].start_ns
    fin = debut + ack.duration_ns
    # L'ACK n'empiète pas sur l'émission déjà acceptée.
    assert not (debut < occupation[0][1] and occupation[0][0] < fin)
    assert debut >= occupation[0][1]


# --------------------------------------------------------------------------- 3. écart d'une nanoseconde

def test_contact_exact_et_chevauchement_d_un_nanoseconde():
    """[C] Paire discriminante : libération à l'ouverture, puis une nanoseconde plus tôt.

    Une borne approximative ou une comparaison `<=` au lieu de `<` donnerait le même résultat pour
    les deux scènes. C'est le test qui interdit cette confusion.
    """
    duree = 300_000_000
    occupation = ((1 * SECONDE, 1 * SECONDE + duree),)

    def _place(ready_ns):
        arbitre = GatewayArbiter(occupation=occupation, regle_placement=DECALE)
        arbitre.demand(EmissionRequest(label="downlink", device=0, ready_ns=ready_ns,
                                       duration_ns=56_576_000,
                                       window=(ready_ns, ready_ns + 10 * SECONDE),
                                       allow_late=True, freq_hz=RX1_HZ))
        emissions = arbitre.resolve()
        émise = [e for e in emissions if e.emitted]
        return émise[0].start_ns if émise else None

    # (a) Prêt **exactement** à la libération : aucun décalage.
    assert _place(1 * SECONDE + duree) == 1 * SECONDE + duree
    # (b) Prêt une nanoseconde avant : repoussé à la libération — et pas à autre chose.
    assert _place(1 * SECONDE + duree - 1) == 1 * SECONDE + duree


def test_deux_fenetres_separees_par_un_intervalle_libre_ne_se_bloquent_pas():
    """[C] Deux émissions disjointes sont toutes deux possibles, sans attente superflue.

    Une borne monotone « occupé jusqu'à » les bloquerait ; le chevauchement réel ne le fait pas.
    """
    arbitre = GatewayArbiter(regle_placement=DECALE)
    for k in (0, 1):
        arbitre.demand(EmissionRequest(label="downlink", device=0, ready_ns=k * 10 * SECONDE,
                                       duration_ns=56_576_000,
                                       window=(k * 10 * SECONDE, k * 10 * SECONDE + 5 * SECONDE),
                                       allow_late=True, freq_hz=RX1_HZ))
    emissions = arbitre.resolve()
    émises = sorted(e.start_ns for e in emissions if e.emitted)
    assert émises == [0, 10 * SECONDE], "la seconde émission a été retardée sans raison"
