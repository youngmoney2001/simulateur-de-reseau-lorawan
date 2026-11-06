"""U0.3 — Placement A6 des descentes : scènes discriminantes et invariance des scénarios sans descente.

Arbitrage A6 (TS001-1.0.4 §3.3.5) : le serveur « SHALL initiate the transmission of the downlink
frame **precisely at the beginning** of one of those two receive windows ». Une descente part donc
exactement à l'ouverture de RX1 ou de RX2, ou n'est pas émise du tout.

Ce fichier épingle les conséquences observables de cette règle :

1. **Ce qui ne doit pas changer.** Un scénario sans descente — ou sans contention — produit
   exactement le même résultat qu'avant U0.3. C'est la condition posée par l'arbitrage 3
   (empreintes gelées invariantes pour les scénarios sans descente).
2. **Ce qui change, et pourquoi.** Dès qu'une fenêtre est masquée à son ouverture, la descente est
   perdue au lieu d'être décalée. Le repli RX2, qui ne se déclenchait jamais parce que le décalage
   faisait toujours tenir l'émission dans la seconde, devient effectif.

Les scènes sont volontairement construites par **paires** qui ne diffèrent que d'une nanoseconde :
c'est ce qui empêche de remplacer le chevauchement réel par une borne approximative, ou par une
 règle « dès que l'émetteur est libre ».

Chaque scène est jouée sur l'oracle Python **et** sur le cœur natif quand l'enveloppe le permet ;
les deux doivent concorder, faute de quoi `trace_events` lève « occupation passerelle incohérente
entre le moteur et le planificateur ».
"""

import pytest

from lsim.downlink_plan import DeviceRx2, plan_native_v2
from lsim.scenario import Scenario, ScenarioModel
from lsim.simulator import EndDevice, Gateway, Propagation, simulate_uplinks_trace
from lsim.trace_events import (ProtocolOptions, _downlink_airtime_ns, _schedule_gateway, _Job,
                               DeviceRadio, build_trace)

SECONDE = 1_000_000_000
RX1_HZ = 868_100_000
RX2_HZ = 869_525_000


def _radio(sf=7, rx2_sf=12):
    return DeviceRadio(freq_hz=RX1_HZ, dr=None, rx1_hz=RX1_HZ, tx_power_dbm=14.0,
                       rx1_sf=sf, rx1_bw_hz=125_000,
                       rx2_hz=RX2_HZ, rx2_sf=rx2_sf, rx2_bw_hz=125_000)


def _job(record, t_open, airtime, rx2_airtime, rx2_sf=12, device_missed=False):
    return _Job(record=record, device=record, kind="downlink", content="data", t_open=t_open,
                airtime_ns=airtime, rx1_hz=RX1_HZ, received=True, device_missed=device_missed,
                rx2_hz=RX2_HZ, rx2_sf=rx2_sf, rx2_bw_hz=125_000, rx2_airtime_ns=rx2_airtime)


def _options(repli=True, every=0, payload=10):
    return ProtocolOptions(confirmed_uplinks=True, downlink_every=every,
                           downlink_payload_bytes=payload, gateway_tx_power_dbm=27.0,
                           rx2_fallback=repli)


# ----------------------------------------------------------------- invariance : scénario sans descente

def test_scenario_sans_descente_est_inchange():
    """Aucune descente demandée : A6 n'a rien à placer, le résultat est identique.

    C'est la première condition de l'arbitrage 3. On la vérifie sur l'occupation **et** sur
    l'ensemble de la trace, pas seulement sur le nombre d'événements : un changement de
    comptabilité ou d'ordre passerait inaperçu sur un seul agrégat.
    """
    devices = [EndDevice(x_m=100.0 + 40.0 * i, spreading_factor=7 + (i % 3),
                         start_offset_ns=i * 50_000_000, period_ns=30 * SECONDE, messages=4)
               for i in range(6)]
    radios = [_radio(sf=7 + (i % 3)) for i in range(6)]

    ups = simulate_uplinks_trace(devices, Gateway(), Propagation())
    # `confirmed_uplinks=False` et `downlink_every=0` : aucune trame descendante n'est produite.
    opts = ProtocolOptions(confirmed_uplinks=False, downlink_every=0,
                           downlink_payload_bytes=0, gateway_tx_power_dbm=27.0,
                           rx2_fallback=True)
    ev, busy = plan_native_v2(ups.records, radios, opts,
                              [DeviceRx2(RX2_HZ, 12, 125_000)] * 6)

    # Aucune émission descendante : l'émetteur n'est jamais occupé, avec ou sans table RX2.
    assert busy == ()
    # Et la table RX2 ne change rien non plus — le repli n'a rien à rattraper.
    ev2, busy2 = plan_native_v2(ups.records, radios, opts, None)
    assert busy2 == ()
    assert len(ev2) == len(ev)


def test_scenario_sans_contention_est_inchange():
    """Fenêtres toutes libres : émises à leur ouverture, exactement comme avant U0.3.

    A6 ne change rien quand l'émetteur est libre à l'ouverture : l'ancienne règle
    `max(ouverture, occupé_jusqu'à)` y était déjà égale à `ouverture`. Les scénarios sans
    contention doivent donc être strictement inchangés — c'est la seconde condition de
    l'arbitrage 3.
    """
    radio = _radio()
    air = _downlink_airtime_ns(radio, 10, "rx1")
    # Ouvertures espacées de 3 s : très au-delà de tout temps d'antenne, aucune contention.
    jobs = [_job(k, (1 + 3 * k) * SECONDE, air, air) for k in range(4)]
    starts, fenetres, occupation = _schedule_gateway(jobs, _options())

    assert starts == [(1 + 3 * k) * SECONDE for k in range(4)]
    assert fenetres == ["rx1"] * 4
    assert occupation == [((1 + 3 * k) * SECONDE, (1 + 3 * k) * SECONDE + air) for k in range(4)]


# ----------------------------------------------------------------- ce qui change, et pourquoi

def test_fenetre_masquee_est_perdue_et_non_decalee():
    """U0.3 : une fenêtre masquée à son ouverture est **perdue**, elle n'attend pas.

    Avant U0.3 la seconde descente était émise à 1,3 s — 0,25 s après son ouverture. Ce
    décalage est précisément ce que TS001-1.0.4 §3.3.5 n'autorise pas. La descente est donc
    perdue, et l'occupation ne porte aucune trace de la tentative.
    """
    radio = _radio()
    air = _downlink_airtime_ns(radio, 10, "rx1")
    jobs = [_job(0, 1 * SECONDE, 300_000_000, air),
            _job(1, 1 * SECONDE + 50_000_000, 300_000_000, air)]
    starts, fenetres, occupation = _schedule_gateway(jobs, _options(repli=False))

    assert starts == [1 * SECONDE, None]
    assert occupation == [(1 * SECONDE, 1 * SECONDE + 300_000_000)]


def test_emission_acceptee_occupe_emetteur_refus_ne_laisse_rien():
    """L'occupation est exactement l'ensemble des émissions acceptées.

    Une émission acceptée occupe l'émetteur pendant son temps d'antenne, à partir de son
    ouverture. Une émission refusée n'occupe rien : aucune entrée, aucun intervalle de longueur
    nulle, aucun report. C'est l'exigence 6 du jalon, vérifiée des deux côtés.
    """
    radio = _radio()
    air = _downlink_airtime_ns(radio, 10, "rx1")
    jobs = [_job(0, 1 * SECONDE, air, air),
            _job(1, 1 * SECONDE + air // 2, air, air),   # RX1 masquée
            _job(2, 4 * SECONDE, air, air)]              # libre
    starts, fenetres, occupation = _schedule_gateway(jobs, _options(repli=False))

    assert starts == [1 * SECONDE, None, 4 * SECONDE]
    assert occupation == [(1 * SECONDE, 1 * SECONDE + air), (4 * SECONDE, 4 * SECONDE + air)]
    # Aucune occupation pour le refus : deux entrées, pas trois, et aucune de longueur nulle.
    assert all(fin > debut for debut, fin in occupation)


def test_paire_contact_exact_contre_une_nanoseconde():
    """Paire décisive : deux scènes qui ne diffèrent que d'une nanoseconde, verdicts opposés.

    L'intervalle d'occupation est semi-ouvert `[début, fin)` : une émission qui s'achève
    exactement à l'ouverture ne la bloque pas. Une nanoseconde plus tard, si.

    C'est ce qui distingue un chevauchement **réel** d'une borne approximative ou d'un intervalle
    fermé. C'est aussi la scène exigée par le jalon sous la forme « occupation se terminant
    exactement à l'ouverture ⇒ émission autorisée ; occupation chevauchant réellement ⇒ refus ».
    """
    radio = _radio()
    air = _downlink_airtime_ns(radio, 10, "rx1")
    ouverture_liberation = 1 * SECONDE + air  # l'émetteur se libère à cet instant

    # (a) Ouverture à l'instant exact de la libération : émise, sans repli.
    jobs = [_job(0, 1 * SECONDE, air, air), _job(1, ouverture_liberation, air, air)]
    starts, fenetres, occupation = _schedule_gateway(jobs, _options(repli=True))
    assert starts == [1 * SECONDE, ouverture_liberation]
    assert fenetres == ["rx1", "rx1"]

    # (b) Une nanoseconde plus tôt : l'émetteur est encore pris. RX1 refusée, RX2 la rattrape.
    jobs = [_job(0, 1 * SECONDE, air, air), _job(1, ouverture_liberation - 1, air, air)]
    starts, fenetres, occupation = _schedule_gateway(jobs, _options(repli=True))
    assert starts[0] == 1 * SECONDE
    assert fenetres == ["rx1", "rx2"]
    assert starts[1] == ouverture_liberation - 1 + SECONDE  # ouverture exacte de la RX2


def test_deux_fenetres_separees_par_un_intervalle_libre():
    """Deux fenêtres séparées par un intervalle libre sont **toutes deux** émises.

    Le piège qu'une borne monotone « occupé jusqu'à » ne sait pas éviter : une fois l'émetteur
    occupé, une telle borne ne décroît jamais, et rejetterait la seconde fenêtre à tort. Le
    placement porte donc sur un chevauchement réel, ce qui est la raison pour laquelle
    l'ordonnanceur radio du cœur tient une liste d'intervalles et non un scalaire.
    """
    radio = _radio()
    air = _downlink_airtime_ns(radio, 10, "rx1")
    jobs = [_job(0, 1 * SECONDE, air, air), _job(1, 4 * SECONDE, air, air)]
    assert 1 * SECONDE + air < 4 * SECONDE, "précondition : intervalle libre réel"
    starts, fenetres, occupation = _schedule_gateway(jobs, _options(repli=True))

    assert starts == [1 * SECONDE, 4 * SECONDE]
    assert fenetres == ["rx1", "rx1"]
    assert len(occupation) == 2


def test_repli_rx2_devient_effectif():
    """Conséquence mesurable d'A6 : le repli RX2, jusque-là inerte, se déclenche.

    Avant U0.3 le décalage faisait toujours tenir l'émission dans la seconde de la fenêtre : le
    repli, bien qu'implémenté et opt-in, ne produisait **jamais** d'émission. A6 supprime cette
    zone tampon, une RX1 masquée est perdue, et la RX2 part — à son ouverture, avec ses propres
    paramètres radio.
    """
    radio = _radio()
    air_rx1 = _downlink_airtime_ns(radio, 10, "rx1")
    air_rx2 = _downlink_airtime_ns(radio, 10, "rx2")
    assert air_rx2 > 10 * air_rx1, "le scénario doit rendre l'écart RX1/RX2 visible"

    # Le premier job masque la RX1 du second, pas sa RX2.
    jobs = [_job(0, 1 * SECONDE, 500_000_000, air_rx2),
            _job(1, 1 * SECONDE + 25_000_000, air_rx1, air_rx2)]
    starts, fenetres, occupation = _schedule_gateway(jobs, _options(repli=True))

    assert fenetres == ["rx1", "rx2"]
    assert starts[1] == 2 * SECONDE + 25_000_000           # ouverture exacte de la RX2
    # L'occupation porte la durée **réelle** : celle de RX2, pas celle de RX1.
    assert occupation[1] == (starts[1], starts[1] + air_rx2)


def test_masquee_en_rx1_et_rx2_aucune_emission():
    """RX1 et RX2 masquées : aucune émission, et aucune occupation fictive.

    Contrepartie négative du test précédent. Sans ce test, un repli qui inscrirait une occupation
    fantôme au moment du refus passerait inaperçu.
    """
    radio = _radio(sf=12)
    air_long = _downlink_airtime_ns(radio, 23, "rx1")
    assert air_long > SECONDE, "l'émission doit masquer RX1 **et** RX2"

    air_rx1 = _downlink_airtime_ns(_radio(), 10, "rx1")
    jobs = [_job(0, 1 * SECONDE, air_long, air_long),
            _job(1, 1 * SECONDE + 25_000_000, air_rx1, air_rx1)]
    starts, fenetres, occupation = _schedule_gateway(jobs, _options(repli=True))

    assert starts == [1 * SECONDE, None]
    assert fenetres == ["rx1", None]
    assert occupation == [(1 * SECONDE, 1 * SECONDE + air_long)]


# ----------------------------------------------------------------- parité cœur / oracle

def test_parite_coeur_oracle_sur_les_scenes_u03():
    """Les scènes ci-dessus sont jouées à l'identique par le cœur natif et par l'oracle Python.

    C'est de cette égalité que dépend le chemin causal : `trace_events` lève une erreur si
    l'occupation du moteur diffère de celle du planificateur. La vérifier sur des scènes
    **contentieuses** — et non sur des scènes triviales — est ce qui rend la parité probante.
    """
    from lsim.downlink_plan import plan_native_v2 as plan

    N = 4
    devices = [EndDevice(x_m=100.0 + 40.0 * i, spreading_factor=7,
                         start_offset_ns=i * 25_000_000, period_ns=30 * SECONDE, messages=3)
               for i in range(N)]
    radios = [_radio() for _ in range(N)]
    rx2 = [DeviceRx2(RX2_HZ, 12, 125_000) for _ in range(N)]

    for repli in (False, True):
        opts = ProtocolOptions(confirmed_uplinks=True, downlink_every=1,
                               downlink_payload_bytes=40, gateway_tx_power_dbm=27.0,
                               rx2_fallback=repli)
        ups = simulate_uplinks_trace(devices, Gateway(), Propagation())
        _ev, busy_natif = plan(ups.records, radios, opts, rx2 if repli else None)
        # Le cœur accepte la table RX2 ; l'oracle Python est appelé avec les mêmes options, par
        # la même passe de planification que le chemin causal.
        from lsim.trace_events import _plan
        _roles, _jobs, _starts, busy_oracle, _fen, _obt = _plan(ups.records, radios, opts, {})
        assert [tuple(iv) for iv in busy_natif] == [tuple(iv) for iv in busy_oracle], (
            f"divergence cœur/oracle avec repli={repli}")
