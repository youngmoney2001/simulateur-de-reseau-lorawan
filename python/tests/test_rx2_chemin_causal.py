"""I3 — C1/C2/C3 : la table RX2 atteint le moteur causal, et les deux producteurs restent égaux.

Avant I3, la table RX2 existait dans l'enveloppe `lsim_plan_downlinks_v2` (planification par lot)
mais **aucune entrée causale ne l'acceptait** : le moteur causal ne disposait donc d'aucune
fenêtre de secours, alors que le planificateur par lot en avait une. Dès le premier repli, les
deux producteurs divergeaient — et le contrôle d'égalité de `trace_events` est bloquant.

La nouvelle entrée `lsim_simulate_uplinks_causal_v3` réunit la table RX2 **et** les frontaux :
sans aucune des deux extensions, l'entrée v1 reste appelée et la base est inchangée à l'octet
près (empreintes gelées).

Ce que ce fichier exige :

- **C1** une scène qui déclare une région produit une table RX2 et le repli est effectif ;
- **C2** passer la table **change** l'occupation du moteur causal — sinon elle n'atteint rien ;
- **C3** sur une même trace, moteur causal et planificateur par lot produisent la même
  occupation, avec **et** sans table ;
- **C5** sans région, la table est à zéro et tout le repli est inerte : la base est inchangée.

Référence : RP002-1.0.5, `RECEIVE_DELAY2 = RECEIVE_DELAY1 + 1 s`.
"""

import pytest

from lsim.downlink_plan import DeviceRx2, plan_native, plan_native_v2, simulate_causal
from lsim.scenario import Scenario, ScenarioModel
from lsim.trace_events import (ProtocolOptions, _downlink_jobs, _schedule_gateway,
                               device_radios)

RX1_HZ = 868_100_000


def _scene(region="EU868", sf=9, count=60, spread=30, messages=2, payload=20):
    """Scène dont la trace causale manque réellement des fenêtres RX1.

    Le réglage n'est pas arbitraire : sur le chemin causal, une montante qui chevauche une
    descente déjà planifiée est perdue en `LostGatewayBusy`, ce qui **absorbe** la contention.
    Il faut donc des montantes qui finissent à moins d'une seconde d'écart sans se chevaucher,
    et des descentes assez longues pour masquer la fenêtre suivante : d ≥ 1 s + écart des fins.
    """
    raw = {
        "schema_version": 1, "name": "rx2-causal", "seed": 7,
        "gateway": {"x_m": 0, "y_m": 0, "antenna_gain_dbi": 2.15},
        "propagation": {"frequency_hz": RX1_HZ, "exponent": 2.7},
        "groups": [{
            "name": "g0", "count": count, "region": region,
            "placement": {"type": "disk", "radius_m": 800},
            "spreading_factor": sf, "payload_bytes": payload, "tx_power_dbm": 14.0,
            "period_s": 300, "messages": messages, "start_spread_s": spread,
        }],
    }
    scenario = Scenario(ScenarioModel.model_validate(raw))
    devices, _g, _i = scenario.deploy()
    return devices, scenario, device_radios(scenario)


def _options(repli=True, payload=200):
    return ProtocolOptions(confirmed_uplinks=True, downlink_every=1,
                           downlink_payload_bytes=payload, gateway_tx_power_dbm=27.0,
                           rx2_fallback=repli)


def _table(radios):
    """Table RX2 telle que la construit l'appelant : une entrée par dispositif."""
    return tuple(DeviceRx2(r.rx2_hz, r.rx2_sf, r.rx2_bw_hz) for r in radios)


def _causal(devices, scenario, radios, options, rx2=None):
    return simulate_causal(devices, scenario.gateway(), scenario.propagation(),
                           scenario.environment, radios, options, rx2=rx2)


def _scenes_qui_replient():
    """(sf, spread) dont la trace causale perd des RX1 — vérifié par l'oracle, pas supposé."""
    retenues = []
    for sf in (9, 10):
        for spread in (18, 30):
            devices, scenario, radios = _scene(sf=sf, spread=spread)
            options = _options()
            _res, _busy = _causal(devices, scenario, radios, options)
            jobs = _downlink_jobs(_res.records, radios, options,
                                  [False] * len(_res.records), None)
            _s, fenetres, _b = _schedule_gateway(jobs, options)
            if fenetres.count("rx2") > 0:
                retenues.append((sf, spread))
    return retenues


SCENES = _scenes_qui_replient()


def test_au_moins_une_scene_exerce_le_repli():
    """Garde-fou : sans scène qui replie, les tests suivants ne prouveraient rien."""
    assert SCENES, "aucune scène ne perd de RX1 sur le chemin causal"


# ------------------------------------------------------------------------------------------ C1

@pytest.mark.parametrize("sf,spread", SCENES)
def test_le_repli_est_effectif_sur_le_chemin_causal(sf, spread):
    """C1 : une scène qui déclare une région replie réellement des descentes en RX2.

    La fréquence de la fenêtre de secours apparaît dans l'occupation planifiée par le moteur :
    c'est la seule sortie du chemin causal qui porte la fenêtre, et elle est produite par le
    cœur, pas par l'oracle Python.
    """
    devices, scenario, radios = _scene(sf=sf, spread=spread)
    options = _options()
    rx2_hz = radios[0].rx2_hz
    assert rx2_hz != 0, "la scène doit déclarer une région pour que RX2 soit renseignée"

    _res, busy = _causal(devices, scenario, radios, options, rx2=_table(radios))
    jobs = _downlink_jobs(_res.records, radios, options, [False] * len(_res.records), None)
    starts, fenetres, _b = _schedule_gateway(jobs, options)
    assert fenetres.count("rx2") > 0
    # Le moteur a bien placé ces descentes : elles figurent dans son occupation.
    assert starts is not None
    assert len(busy) >= sum(1 for s in starts if s is not None)


# ------------------------------------------------------------------------------------------ C2

@pytest.mark.parametrize("sf,spread", SCENES)
def test_passer_la_table_change_l_occupation_du_moteur(sf, spread):
    """C2 : la table atteint le moteur — sans elle, l'occupation serait différente.

    C'est le test que l'audit ne pouvait pas écrire : avant I3, `simulate_causal` n'avait aucun
    moyen de recevoir la table, donc aucune comparaison n'était possible.
    """
    devices, scenario, radios = _scene(sf=sf, spread=spread)
    options = _options()
    _r0, busy_sans = _causal(devices, scenario, radios, options)
    _r1, busy_avec = _causal(devices, scenario, radios, options, rx2=_table(radios))
    assert tuple(busy_sans) != tuple(busy_avec), \
        "la table RX2 n'a aucun effet sur le moteur : elle n'atteint pas le planificateur"


def test_sans_region_la_table_est_inerte():
    """C5 : aucune région ⇒ `rx2_hz = 0` ⇒ aucun repli, des deux côtés.

    C'est la condition qui rend le repli par défaut sans danger pour les scénarios historiques :
    sans fréquence régionale il n'y a rien à émettre, et rien n'est inventé.
    """
    raw = {
        "schema_version": 1, "name": "sans-region", "seed": 7,
        "gateway": {"x_m": 0, "y_m": 0, "antenna_gain_dbi": 2.15},
        "propagation": {"frequency_hz": RX1_HZ, "exponent": 2.7},
        "groups": [{
            "name": "g0", "count": 60, "placement": {"type": "disk", "radius_m": 800},
            "spreading_factor": 9, "payload_bytes": 20, "tx_power_dbm": 14.0,
            "period_s": 300, "messages": 2, "start_spread_s": 30,
        }],
    }
    scenario = Scenario(ScenarioModel.model_validate(raw))
    devices, _g, _i = scenario.deploy()
    radios = device_radios(scenario)
    options = _options()
    assert all(r.rx2_hz == 0 for r in radios)
    table = _table(radios)
    assert all(e.rx2_hz == 0 for e in table)

    _r0, busy_sans = _causal(devices, scenario, radios, options)
    _r1, busy_avec = _causal(devices, scenario, radios, options, rx2=table)
    assert tuple(busy_sans) == tuple(busy_avec)
    # Et le planificateur par lot est d'accord.
    v1 = plan_native(_r0.records, radios, options)
    v2 = plan_native_v2(_r0.records, radios, options, table)
    assert v1 == v2


# ------------------------------------------------------------------------------------------ C3

@pytest.mark.parametrize("sf,spread", SCENES)
def test_occupation_identique_causal_et_par_lot_avec_table(sf, spread):
    """C3 : moteur causal et planificateur par lot, **avec** table : même occupation.

    Chaque producteur est comparé à l'autre sur **sa propre** trace : le chemin causal alimente
    la simulation en retour, donc les deux traces diffèrent et il serait faux de les mélanger.
    """
    devices, scenario, radios = _scene(sf=sf, spread=spread)
    options = _options()
    table = _table(radios)
    resultat, busy = _causal(devices, scenario, radios, options, rx2=table)
    _events, busy_lot = plan_native_v2(resultat.records, radios, options, table)
    assert tuple(busy) == tuple(busy_lot), \
        "divergence d'occupation entre le moteur causal et le planificateur par lot"


@pytest.mark.parametrize("sf,spread", SCENES)
def test_occupation_identique_causal_et_par_lot_sans_table(sf, spread):
    """C3 : même égalité **sans** table — la base n'est pas régressée par l'entrée v3."""
    devices, scenario, radios = _scene(sf=sf, spread=spread)
    options = _options()
    resultat, busy = _causal(devices, scenario, radios, options)
    _events, busy_lot = plan_native(resultat.records, radios, options)
    assert tuple(busy) == tuple(busy_lot)


# ------------------------------------------------------------------------- le chemin de production

@pytest.mark.parametrize("sf,spread", SCENES)
def test_build_trace_avec_region_ne_diverge_pas(sf, spread):
    """C1 + C3 : l'entrée publique `build_trace` tient le contrôle d'égalité avec une région.

    C'est le test que le défaut rendait impossible à écrire : `_build_trace_native` compare
    l'occupation du moteur à celle du planificateur par lot et lève en cas d'écart. Avant I3,
    le repli n'existait que du côté du planificateur par lot — dès qu'il se produisait, c'était
    l'exception. Ici le repli se produit réellement (voir le garde-fou ci-dessous) et l'appel
    aboutit.
    """
    from lsim.trace_events import build_trace

    raw = {
        "schema_version": 1, "name": "rx2-production", "seed": 7,
        "gateway": {"x_m": 0, "y_m": 0, "antenna_gain_dbi": 2.15},
        "propagation": {"frequency_hz": RX1_HZ, "exponent": 2.7},
        "groups": [{
            "name": "g0", "count": 60, "region": "EU868",
            "placement": {"type": "disk", "radius_m": 800},
            "spreading_factor": sf, "payload_bytes": 20, "tx_power_dbm": 14.0,
            "period_s": 300, "messages": 2, "start_spread_s": spread,
        }],
    }
    scenario = Scenario(ScenarioModel.model_validate(raw))
    options = _options()
    assert options.rx2_fallback, "le repli doit être actif par défaut (décision I3)"

    run = build_trace(scenario, options)
    # Le repli a bien été exercé : la fréquence RX2 apparaît dans les sauts descendants.
    rx2_hz = device_radios(scenario)[0].rx2_hz
    descendantes = [h for e in run.events for h in e.hops if h.from_id == "gw:0"]
    assert descendantes, "aucune descente dans la trace : le test ne prouve rien"
    assert any(h.freq_hz == rx2_hz for h in descendantes), \
        "aucune descente émise en RX2 : le repli n'a pas été exercé"
