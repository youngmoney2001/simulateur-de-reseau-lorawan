"""I2 — Repli RX2 dans l'oracle Python (`trace_events._schedule_gateway`).

RX1 reste prioritaire : RX2 n'est demandée que par la réaction d'une RX1 **non émise**. Le repli
est **opt-in** (`ProtocolOptions.rx2_fallback`) et n'opère que si la fenêtre de secours est
réellement renseignée — sans fréquence régionale il n'y a rien à émettre, et sans SF il n'y a pas
de fenêtre.

**Divergence connue avec le cœur C++** : le planificateur natif n'implémente **aucun** repli RX2
(écart D1 de l'audit). La parité ne peut donc pas porter sur un repli effectif ; elle est exigée
partout où les deux moteurs doivent se rejoindre — RX1, repli désactivé, absence de fréquence
régionale. Le cas « RX1 refusée puis RX2 acceptée » est épinglé par un `xfail(strict=True)` : il
passera au vert dès que le cœur implémentera le repli, et ce test devra alors être réécrit.
"""

import pytest

from lsim.downlink_plan import PLAN_STATUS_BASE, DeviceRx2, plan_native, plan_native_v2
from lsim.scenario import Scenario, ScenarioModel
from lsim.simulator import simulate_uplinks_trace
from lsim.trace_events import (ProtocolOptions, _downlink_airtime_ns, _downlink_jobs,
                               _events, _schedule_gateway, device_radios)

SECONDE = 1_000_000_000
RX1_HZ = 868_100_000
RX2_HZ = 869_525_000          # RP002-1.0.5, EU868 : RX2 par défaut


def _radio(rx2_hz=RX2_HZ, rx2_sf=12, rx2_bw_hz=125_000, sf=7):
    from lsim.trace_events import DeviceRadio
    return DeviceRadio(freq_hz=RX1_HZ, dr=None, rx1_hz=RX1_HZ, tx_power_dbm=14.0,
                       rx1_sf=sf, rx1_bw_hz=125_000, rx2_hz=rx2_hz, rx2_sf=rx2_sf,
                       rx2_bw_hz=rx2_bw_hz)


def _job(record, t_open, airtime, rx2_airtime, rx2_hz=RX2_HZ, rx2_sf=12, device_missed=False):
    from lsim.trace_events import _Job
    return _Job(record=record, device=record, kind="downlink", content="data", t_open=t_open,
                airtime_ns=airtime, rx1_hz=RX1_HZ, received=True, device_missed=device_missed,
                rx2_hz=rx2_hz, rx2_sf=rx2_sf, rx2_bw_hz=125_000, rx2_airtime_ns=rx2_airtime)


def _options(repli=True, every=2, payload=10):
    return ProtocolOptions(confirmed_uplinks=True, downlink_every=every,
                           downlink_payload_bytes=payload, gateway_tx_power_dbm=27.0,
                           rx2_fallback=repli)


def _options_satures(repli=True):
    """Descentes de 200 octets à chaque uplink reçu : l'émetteur sature, des RX1 sont perdues.

    Avec `downlink_every=2` et 10 octets, aucune fenêtre RX1 n'est manquée dans ce scénario : le
    repli n'aurait rien à rattraper et les tests de repli ne prouveraient rien.
    """
    return _options(repli=repli, every=1, payload=200)


# ------------------------------------------------------------------ l'unité : deux jobs, un émetteur
# Le premier job occupe [1 s, 1,5 s]. Le second ouvre à 1,1 s : sa fenêtre RX1 (1,1 s → 2,1 s)
# est déjà perdue, l'émetteur étant pris jusqu'à 1,5 s. Sa fenêtre RX2 ouvre à 2,1 s et ferme à
# 3,1 s : l'émetteur y est libre, la descente part **à l'ouverture**. C'est le cas « RX1 refusée
# puis RX2 acceptée ».
#
# U0.3 / A6 : la première descente durait 1,5 s, laissant l'émetteur pris jusqu'à 2,5 s ; la RX2
# (2,1 s) était alors émise à 2,5 s, soit 0,4 s après son ouverture. L'ancienne règle « attend la
# libération de l'émetteur » l'autorisait, A6 l'interdit. Le scénario est donc recalé pour que la
# RX2 soit réellement disponible à son ouverture — seul cas où une émission est légitime. Le cas
# symétrique, RX2 masquée donc refusée sans occupation, est épinglé plus bas par
# `test_rx2_aussi_masquee_est_refusee_sans_occupation`.

def _deux_jobs():
    radio = _radio()
    air_rx1 = _downlink_airtime_ns(radio, 10, "rx1")
    air_rx2 = _downlink_airtime_ns(radio, 10, "rx2")
    return [_job(0, 1 * SECONDE, int(0.5 * SECONDE), air_rx2),
            _job(1, int(1.1 * SECONDE), air_rx1, air_rx2)], air_rx1, air_rx2


def test_rx1_disponible_est_toujours_preferee():
    """Une RX1 plaçable est émise en RX1, et aucune RX2 n'est même demandée."""
    jobs, _a1, _a2 = _deux_jobs()
    starts, fenetres, occupation = _schedule_gateway(jobs, _options())
    assert starts[0] == 1 * SECONDE
    assert fenetres[0] == "rx1"
    # Une seule occupation pour ce job : RX2 n'est pas venue s'y ajouter.
    assert [iv for iv in occupation if iv[0] == 1 * SECONDE] == [
        (1 * SECONDE, int(1.5 * SECONDE))]


def test_rx1_refusee_puis_rx2_acceptee():
    """Le cœur du jalon : RX2 n'est émise que parce que RX1 n'a pas abouti."""
    jobs, _a1, air_rx2 = _deux_jobs()
    starts, fenetres, occupation = _schedule_gateway(jobs, _options())
    # RX2 s'ouvre une seconde après RX1 (RECEIVE_DELAY2), à 2,1 s. A6 : l'émission part à
    # l'ouverture, et non à la première libération de l'émetteur — intervenue dès 1,5 s.
    assert starts[1] == int(2.1 * SECONDE)
    assert fenetres[1] == "rx2"


def test_aucun_doublon_rx1_rx2():
    """Une seule émission acceptée par descente : jamais RX1 **et** RX2 pour le même job."""
    jobs, _a1, _a2 = _deux_jobs()
    _starts, fenetres, occupation = _schedule_gateway(jobs, _options())
    # Deux jobs, deux émissions : la RX2 du second ne double aucune RX1.
    assert len(occupation) == 2
    assert fenetres.count("rx2") == 1
    assert occupation[0][1] <= occupation[1][0]   # émetteur unique : jamais de chevauchement


def test_le_temps_d_antenne_suit_la_fenetre_reellement_emise():
    """L'occupation réservée est celle de RX2 (SF12), pas celle de RX1 (SF7).

    C'est le point que le repli ne doit pas manquer : au SF12 BW125, la même trame occupe
    l'émetteur une vingtaine de fois plus longtemps. Réserver la durée RX1 placerait des
    descentes imaginaires.
    """
    jobs, air_rx1, air_rx2 = _deux_jobs()
    assert air_rx2 > 10 * air_rx1, "le scénario doit rendre l'écart RX1/RX2 visible"
    _starts, _fen, occupation = _schedule_gateway(jobs, _options())
    debut_rx2 = int(2.1 * SECONDE)
    assert [iv for iv in occupation if iv[0] == debut_rx2] == [(debut_rx2, debut_rx2 + air_rx2)]


def test_contact_exact_a_l_ouverture_n_est_pas_un_chevauchement():
    """U0.3 / A6 : une occupation qui s'achève **exactement** à l'ouverture ne bloque pas.

    L'intervalle d'occupation est semi-ouvert `[début, fin)` : le contact n'est pas un
    chevauchement. Une règle qui compterait la borne de fin comme encore occupée — ou qui
    raisonnerait sur des intervalles fermés — rejetterait cette fenêtre à tort, alors que
    l'émetteur est libre à la nanoseconde même où elle s'ouvre.

    C'est le pendant exact du test homonyme du cœur C++ (`test_downlink_plan.cpp`, cas 14-D).
    """
    radio = _radio()
    air = _downlink_airtime_ns(radio, 10, "rx1")
    # Le premier job occupe [1 s, 1 s + air) ; le second ouvre à l'instant même de la libération.
    jobs = [_job(0, 1 * SECONDE, air, air), _job(1, 1 * SECONDE + air, air, air)]
    starts, fenetres, occupation = _schedule_gateway(jobs, _options())

    assert starts == [1 * SECONDE, 1 * SECONDE + air]   # les deux à leur ouverture exacte
    assert fenetres == ["rx1", "rx1"]                   # la seconde n'a pas eu besoin du repli
    assert len(occupation) == 2


def test_une_nanoseconde_de_trop_et_la_fenetre_est_perdue():
    """Paire de la scène précédente : une nanoseconde de chevauchement suffit à faire refuser.

    Seule une nanoseconde sépare les deux scènes, et pourtant les verdicts sont opposés. C'est ce
    qui distingue un chevauchement réel d'une approximation : une règle « à la nanoseconde près »
    n'aurait pas départagé les deux cas.

    Sans cette paire, un oracle qui rejetterait au contact exact passerait inaperçu : le test
    précédent échouerait, mais on pourrait le « corriger » en assouplissant la règle au lieu de
    la rendre exacte.
    """
    radio = _radio()
    air = _downlink_airtime_ns(radio, 10, "rx1")
    # Le second ouvre une nanoseconde avant la libération de l'émetteur : sa RX1 est refusée, sa
    # RX2 (une seconde plus tard) est libre et le rattrape — à l'ouverture de la RX2.
    jobs = [_job(0, 1 * SECONDE, air, air), _job(1, 1 * SECONDE + air - 1, air, air)]
    starts, fenetres, occupation = _schedule_gateway(jobs, _options())

    assert starts[0] == 1 * SECONDE
    assert starts[1] == 2 * SECONDE + air - 1   # ouverture exacte de la RX2
    assert fenetres == ["rx1", "rx2"]
    assert len(occupation) == 2


def test_rx2_aussi_masquee_est_refusee_sans_occupation():
    """U0.3 / A6 : une RX2 chevauchée à son ouverture est refusée, sans occupation fictive.

    C'est l'ancien réglage de `_deux_jobs` : la première descente durait 1,5 s et libérait
    l'émetteur à 2,5 s, soit 0,4 s **après** l'ouverture de la RX2 du second job (2,1 s).

    Avant U0.3 l'émission était décalée à 2,5 s et l'émetteur l'inscrivait. A6 l'interdit —
    TS001-1.0.4 §3.3.5 demande une émission « précisément au début » de la fenêtre. La descente
    est donc perdue et, point décisif, **aucune occupation n'est enregistrée** : l'émetteur ne
    porte aucune trace d'une tentative qui n'a pas abouti.

    Sans ce test, « repli RX2 accepté » et « occupation limitée aux émissions réelles » ne
    seraient pas départagés : un repli qui inscrirait une occupation fantôme passerait inaperçu.
    """
    jobs, _air_rx1, _air_rx2 = _deux_jobs()
    # On rétablit la descente longue du premier job : l'émetteur est pris de 1 s à 2,5 s.
    jobs[0] = _job(0, jobs[0].t_open, int(1.5 * SECONDE), _air_rx2)
    starts, fenetres, occupation = _schedule_gateway(jobs, _options())

    assert starts[0] == 1 * SECONDE          # la première, elle, est émise à son ouverture
    assert starts[1] is None                 # RX1 masquée, puis RX2 masquée à son ouverture
    assert fenetres[1] is None               # aucune fenêtre n'a abouti
    # Une seule occupation : celle de l'émission réellement acceptée. Rien pour les deux refus.
    assert occupation == [(1 * SECONDE, int(2.5 * SECONDE))]


def test_deux_fenetres_separees_par_un_intervalle_libre():
    """U0.3 / A6 : deux fenêtres séparées par un intervalle libre sont **toutes deux** émises.

    C'est le piège qu'une borne monotone « occupé jusqu'à » (`busy_until`) ne sait pas éviter :
    une fois l'émetteur occupé, une telle borne ne décroît jamais. Or ici la seconde fenêtre
    s'ouvre après la fin de la première, elle doit donc être acceptée **à son ouverture**.

    Le placement d'A6 porte sur un chevauchement réel, pas sur une borne : c'est précisément la
    différence avec la règle historique, et la raison pour laquelle le `RadioScheduler` du cœur
    tient une liste d'intervalles et non un scalaire.
    """
    radio = _radio()
    air = _downlink_airtime_ns(radio, 10, "rx1")
    # [1 s, 1 s + air) puis, bien plus tard, [4 s, 4 s + air) : aucun recouvrement possible.
    jobs = [_job(0, 1 * SECONDE, air, air), _job(1, 4 * SECONDE, air, air)]
    starts, fenetres, occupation = _schedule_gateway(jobs, _options())

    assert starts == [1 * SECONDE, 4 * SECONDE]   # chacune à son ouverture exacte
    assert fenetres == ["rx1", "rx1"]             # aucune n'a eu besoin du repli
    assert len(occupation) == 2


def test_la_frequence_emise_est_celle_de_rx2():
    """Une descente repliée n'est pas sur la fréquence de RX1 : les événements le disent.

    U0.4 : ce test **se sautait en silence** depuis U0.3. La descente du premier job était
    artificiellement allongée à 1,5 s, ce qui masquait la RX1 du second (1,3 s) **et** sa RX2
    (2,3 s) : `fenetres[1]` valait `None` et la garde `pytest.skip` se déclenchait. Le test ne
    vérifiait donc plus rien depuis le passage à A6, tout en comptant parmi les succès.

    La descente est ramenée à 0,5 s : elle masque la RX1 (ouverte à 1,3 s, émetteur pris
    jusqu'à 1,6 s) mais pas la RX2 (2,3 s). Et la garde `skip` est remplacée par une assertion,
    afin qu'un scénario devenu inopérant **échoue** au lieu de se taire.
    """
    from lsim.trace_events import TxRecord
    radio = _radio()
    air_rx2 = _downlink_airtime_ns(radio, 10, "rx2")
    r0 = TxRecord(device_index=0, start_ns=0, end_ns=100_000_000, spreading_factor=7,
                  outcome=TxRecord.OUTCOME_RECEIVED, rssi_dbm=-60.0)
    r1 = TxRecord(device_index=1, start_ns=200_000_000, end_ns=300_000_000, spreading_factor=7,
                  outcome=TxRecord.OUTCOME_RECEIVED, rssi_dbm=-60.0)
    records = [r0, r1]
    jobs = _downlink_jobs(records, (radio, radio), _options(), [False, False], None)
    # Le premier job est artificiellement allongé pour bloquer la fenêtre RX1 du second,
    # sans bloquer sa fenêtre de secours.
    duree_artificielle = int(0.5 * SECONDE)
    jobs[0] = _job(0, jobs[0].t_open, duree_artificielle, air_rx2)
    jobs[1] = _job(1, jobs[1].t_open, jobs[1].airtime_ns, air_rx2)

    # Préconditions explicites : la RX1 du second est masquée, sa RX2 ne l'est pas.
    fin_occupation = jobs[0].t_open + duree_artificielle
    assert jobs[1].t_open < fin_occupation, "la RX1 du second doit être masquée"
    assert jobs[1].t_open + SECONDE >= fin_occupation, "la RX2 du second doit rester libre"

    starts, fenetres, _occ = _schedule_gateway(jobs, _options())
    assert fenetres[1] == "rx2", "le second job doit être replié en RX2"
    events = _events(records, (radio, radio), jobs, starts, [False, False], None, fenetres,
                    _options())
    descendantes = [h for e in events if e.kind == "downlink" for h in e.hops
                    if h.from_id == "gw:0"]
    assert RX2_HZ in [h.freq_hz for h in descendantes]


@pytest.mark.parametrize("rx2_sf,rx2_hz,attendu", [
    (12, RX2_HZ, True),    # repli possible
    (0, RX2_HZ, False),    # aucun SF : pas de fenêtre de secours
    (12, 0, False),        # aucune fréquence régionale : rien à émettre
])
def test_le_repli_suppose_une_fenetre_rx2_renseignee(rx2_sf, rx2_hz, attendu):
    jobs, _a1, air_rx2 = _deux_jobs()
    jobs[1] = _job(1, jobs[1].t_open, jobs[1].airtime_ns, air_rx2, rx2_hz=rx2_hz, rx2_sf=rx2_sf)
    starts, fenetres, _occ = _schedule_gateway(jobs, _options())
    assert (fenetres[1] == "rx2") is attendu
    assert (starts[1] is not None) is attendu


def test_repli_desactive_reproduit_le_comportement_historique():
    """`rx2_fallback=False` (défaut) : la file ne contient que des RX1, comme avant I2."""
    jobs, _a1, _a2 = _deux_jobs()
    starts, fenetres, occupation = _schedule_gateway(jobs, _options(repli=False))
    assert starts == [1 * SECONDE, None]
    assert fenetres == ["rx1", None]
    assert len(occupation) == 1


def test_sans_options_le_resultat_est_celui_d_avant_i2():
    """`_schedule_gateway(jobs)` sans options : signature historique, aucun repli."""
    jobs, _a1, _a2 = _deux_jobs()
    starts, fenetres, occupation = _schedule_gateway(jobs)
    assert starts == [1 * SECONDE, None]
    assert fenetres == ["rx1", None]


@pytest.mark.parametrize("rx2_sf,rx2_bw_hz,rx2_hz", [
    (6, 125_000, RX2_HZ),      # SF hors 7..12
    (13, 125_000, RX2_HZ),
    (12, 100_000, RX2_HZ),     # largeur hors {125k, 250k, 500k}
    (12, 125_000, -1),         # fréquence négative
])
def test_rx2_invalide_est_refuse(rx2_sf, rx2_bw_hz, rx2_hz):
    """Mêmes bornes que `valid_rx2()` du cœur : refuser plutôt que calculer un airtime faux."""
    from lsim.trace_events import TxRecord
    radio = _radio(rx2_hz=rx2_hz, rx2_sf=rx2_sf, rx2_bw_hz=rx2_bw_hz)
    r = TxRecord(device_index=0, start_ns=0, end_ns=100_000_000, spreading_factor=7,
                 outcome=TxRecord.OUTCOME_RECEIVED, rssi_dbm=-60.0)
    with pytest.raises(ValueError):
        _downlink_jobs([r], (radio,), _options(), [False], None)


def test_rx2_invalide_est_sans_effet_tant_que_le_repli_est_desactive():
    """Hors opt-in, les paramètres RX2 ne sont ni validés ni utilisés : rien ne change."""
    from lsim.trace_events import TxRecord
    radio = _radio(rx2_sf=6)            # invalide, mais jamais lu
    r = TxRecord(device_index=0, start_ns=0, end_ns=100_000_000, spreading_factor=7,
                 outcome=TxRecord.OUTCOME_RECEIVED, rssi_dbm=-60.0)
    jobs = _downlink_jobs([r], (radio,), _options(repli=False), [False], None)
    assert jobs[0].rx2_airtime_ns == 0


def test_rx2_fallback_est_absent_du_repr():
    """Le `repr` de `ProtocolOptions` est une clé des empreintes gelées (`ed126d7f…`).

    Ce champ en est délibérément exclu pour que la référence continue de porter sur le
    comportement. Ce test épingle le choix : si le champ réapparaît dans le `repr`, l'empreinte
    change sans qu'aucun événement n'ait bougé.
    """
    assert "rx2_fallback" not in repr(ProtocolOptions())
    assert repr(ProtocolOptions(rx2_fallback=True)) == repr(ProtocolOptions())


# ---------------------------------------------------------------------- le scénario complet

def _scenario_sature():
    """EU868, 80 dispositifs toutes les 5 s, descentes de 200 octets : l'émetteur sature.

    La région EU868 est nécessaire : c'est elle qui renseigne `rx2_hz` (869,525 MHz). Sans
    région, `rx2_hz = 0` et le repli est inerte par construction — ce que couvre
    `test_le_repli_suppose_une_fenetre_rx2_renseignee`.
    """
    raw = {
        "schema_version": 1, "name": "rx2-sature", "seed": 7,
        "gateway": {"x_m": 0, "y_m": 0, "antenna_gain_dbi": 2.15},
        "propagation": {"frequency_hz": RX1_HZ, "exponent": 2.7},
        "groups": [{
            "name": "g0", "count": 80, "region": "EU868",
            "placement": {"type": "disk", "radius_m": 800},
            "spreading_factor": 7, "payload_bytes": 20, "tx_power_dbm": 14.0,
            "period_s": 5, "messages": 10, "start_spread_s": 5,
        }],
    }
    scenario = Scenario(ScenarioModel.model_validate(raw))
    devices, _g, _i = scenario.deploy()
    result = simulate_uplinks_trace(devices, scenario.gateway(), scenario.propagation(),
                                    scenario.environment, gateway_busy=())
    return result.records, device_radios(scenario)


def test_scenario_sature_demontre_le_repli():
    """Le repli est **réellement exercé** : des descentes partent en RX2, sur 869,525 MHz.

    Ce n'est pas un test de calcul d'airtime : la contention est construite pour que des fenêtres
    RX1 soient manquées, et l'on vérifie que RX2 en rattrape une partie.
    """
    records, radios = _scenario_sature()
    assert radios[0].rx2_hz == RX2_HZ

    sans = _downlink_jobs(records, radios, _options_satures(False), [False] * len(records), None)
    s0, f0, _o0 = _schedule_gateway(sans, _options_satures(False))
    assert any(s is None for s in s0), "scénario non saturé : aucune RX1 perdue, test inutile"

    avec = _downlink_jobs(records, radios, _options_satures(), [False] * len(records), None)
    s1, f1, o1 = _schedule_gateway(avec, _options_satures())
    assert f1.count("rx2") > 0, "le repli n'a jamais été exercé"

    # Chaque RX2 correspond à une RX1 qui n'a pas abouti : pas de doublon.
    assert f1.count("rx1") + f1.count("rx2") == sum(1 for s in s1 if s is not None)

    # Les RX2 sont émises sur la fréquence de la fenêtre de secours, distincte de RX1.
    jobs_rx2 = [k for k, f in enumerate(f1) if f == "rx2"]
    assert jobs_rx2
    assert all(avec[k].rx2_hz == RX2_HZ for k in jobs_rx2)
    # Et elles occupent l'émetteur de la durée RX2 (SF12), jamais de la durée RX1 (SF7).
    durees = {b - a for a, b in o1}
    air_rx2 = {avec[k].rx2_airtime_ns for k in jobs_rx2}
    assert air_rx2 <= durees, "aucune occupation ne porte la durée RX2"


def test_le_repli_coute_l_emetteur_et_peut_reduire_le_total():
    """Conséquence assumée, mesurée : au SF12, une RX2 bloque l'émetteur bien plus longtemps.

    En saturation, rattraper une descente en RX2 en empêche d'autres d'aboutir en RX1. Le repli
    est donc **coûteux**, pas gratuit : c'est un fait radio (RP002 EU868 : RX2 = SF12BW125), pas
    un défaut d'implémentation. Le test épingle l'ordre de grandeur pour qu'une régression de
    placement ne passe pas inaperçue.
    """
    records, radios = _scenario_sature()
    s0, _f0, _o0 = _schedule_gateway(
        _downlink_jobs(records, radios, _options_satures(False), [False] * len(records), None),
        _options_satures(False))
    s1, f1, _o1 = _schedule_gateway(
        _downlink_jobs(records, radios, _options_satures(), [False] * len(records), None),
        _options_satures())
    emis_sans = sum(1 for s in s0 if s is not None)
    emis_avec = sum(1 for s in s1 if s is not None)
    # Le repli augmente le nombre de jobs aboutis **ou** le réduit (coût d'émetteur) : dans ce
    # scénario il le réduit. On épingle que l'effet est mesuré et non nul, dans un sens ou l'autre.
    assert emis_avec != emis_sans
    assert f1.count("rx2") > 0


# ----------------------------------------------------------------------------- parité avec le cœur

def _scenario_simple():
    raw = {
        "schema_version": 1, "name": "parite-rx2", "seed": 3,
        "gateway": {"x_m": 0, "y_m": 0, "antenna_gain_dbi": 2.15},
        "propagation": {"frequency_hz": RX1_HZ, "exponent": 2.7},
        "groups": [{
            "name": "g0", "count": 30,
            "placement": {"type": "disk", "radius_m": 900},
            "spreading_factor": 7, "payload_bytes": 20, "tx_power_dbm": 14.0,
            "period_s": 30, "messages": 12, "start_spread_s": 30,
        }],
    }
    scenario = Scenario(ScenarioModel.model_validate(raw))
    devices, _g, _i = scenario.deploy()
    result = simulate_uplinks_trace(devices, scenario.gateway(), scenario.propagation(),
                                    scenario.environment, gateway_busy=())
    return result.records, device_radios(scenario)


def _rx2_des_radios(radios):
    """Table RX2 telle que la construit l'appelant : une entrée par dispositif.

    C'est cette table qui **active** le repli côté natif (la passer une enveloppe v2, c'est le
    demander). Sans région, `rx2_hz = 0` : le repli reste inerte des deux côtés.
    """
    return tuple(DeviceRx2(rx2_hz=r.rx2_hz, rx2_sf=r.rx2_sf, rx2_bw_hz=r.rx2_bw_hz)
                 for r in radios)


def _parite(options, avec_region=False):
    records, radios = _scenario_sature() if avec_region else _scenario_simple()
    # Repli activé ⇒ on alimente le cœur par l'enveloppe v2, sinon par la v1. Les deux doivent
    # produire les mêmes décisions que l'oracle Python.
    natif = (plan_native_v2(records, radios, options, _rx2_des_radios(radios))
             if options.rx2_fallback else plan_native(records, radios, options))
    jobs = _downlink_jobs(records, radios, options, [False] * len(records), None)
    starts, fenetres, busy = _schedule_gateway(jobs, options)
    events = _events(records, radios, jobs, starts, [False] * len(records), None, fenetres,
                    options)
    return natif, (events, tuple(busy))


@pytest.mark.parametrize("repli", [False, True])
def test_parite_rx1_accepte(repli):
    """Sans région, `rx2_hz = 0` : le repli est inerte, Python et le cœur se rejoignent."""
    natif, python = _parite(_options(repli=repli))
    assert natif == python


def test_parite_rx2_desactive():
    natif, python = _parite(_options(repli=False))
    assert natif == python


def test_parite_absence_de_frequence_regionale():
    """Scénario sans région : RX2 non renseignée, donc repli inerte des deux côtés."""
    records, radios = _scenario_simple()
    assert all(r.rx2_hz == 0 for r in radios)
    natif, python = _parite(_options(repli=True))
    assert natif == python


def test_parite_rx2_invalide_les_deux_moteurs_refusent():
    """Un RX2 hors bornes est refusé par les deux moteurs — chacun dans son idiome.

    Le cœur renvoie un code d'état, Python lève : ce n'est pas une divergence de **règle** (les
    bornes sont les mêmes), c'est une divergence de **canal d'erreur**, assumée et documentée.
    """
    records, radios = _scenario_sature()
    mauvais = tuple(DeviceRx2(rx2_hz=RX2_HZ, rx2_sf=6) for _ in radios)
    # Cœur : refus explicite, sans accéder à la mémoire — code 952 (InvalidRadio).
    with pytest.raises(ValueError, match=str(PLAN_STATUS_BASE + 2)):
        plan_native_v2(records, radios, _options(), mauvais)
    # Python : mêmes bornes, refus par une exception. On les exerce sur un jeu de radios
    # réellement invalide, pour ne pas tester la validation avec des valeurs saines.
    radios_invalides = tuple(
        r.__class__(**{**r.__dict__, "rx2_sf": 6}) for r in radios)
    with pytest.raises(ValueError, match="rx2_sf"):
        _downlink_jobs(records, radios_invalides, _options(), [False] * len(records), None)


def test_parite_repli_rx2_actif():
    """I1 : le cœur replie désormais — parité stricte sur un scénario qui exerce le repli.

    Ce test était un `xfail(strict=True)` en I2, quand le planificateur natif n'implémentait aucun
    repli (écart D1 de l'audit). Il est devenu une parité stricte : les deux moteurs doivent
    produire **exactement** les mêmes événements et la même occupation.
    """
    natif, python = _parite(_options_satures(repli=True), avec_region=True)
    assert natif == python
    # Contrôle positif : le scénario exerce réellement le repli, sinon le test ne prouve rien.
    records, radios = _scenario_sature()
    jobs = _downlink_jobs(records, radios, _options_satures(), [False] * len(records), None)
    _s, fenetres, _o = _schedule_gateway(jobs, _options_satures())
    assert fenetres.count("rx2") > 0, "aucun repli exercé côté Python : test inutile"


def test_le_coeur_replie_et_cela_se_voit():
    """Le repli natif est réel : la v2 avec table RX2 ne renvoie plus la v1.

    C'est la contre-épreuve du test qui, en I2, démontrait l'écart : le cœur reçoit les paramètres
    RX2 et les **utilise**. Sans table (v1 ou v2 à rx2 nul), il ne replie toujours pas.
    """
    records, radios = _scenario_sature()
    options = _options_satures()
    rx2 = _rx2_des_radios(radios)
    natif_v2 = plan_native_v2(records, radios, options, rx2)
    natif_v1 = plan_native(records, radios, options)
    assert natif_v2 != natif_v1, "le cœur n'a pas replié : la v2 renvoie encore la v1"
    # L'écart est bien dû au repli : la v2 place davantage de descentes.
    emis_v1 = sum(1 for e in natif_v1[0] if e.kind in ("downlink", "ack"))
    emis_v2 = sum(1 for e in natif_v2[0] if e.kind in ("downlink", "ack"))
    assert emis_v2 > 0
    # Et sans table, l'enveloppe v2 redevient la v1 : le repli est opt-in.
    assert plan_native_v2(records, radios, options) == natif_v1
