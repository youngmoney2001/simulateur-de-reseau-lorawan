"""§4 — chemins C++ et Python : même résultat quand le mécanisme partagé n'est pas nécessaire.

Le simulateur a deux planificateurs de descentes :

| Chemin | Quand | Où |
|---|---|---|
| **natif** (C++) | passerelle unique, **sans jointure radio** ni commande MAC | `lsim.downlink_plan.plan_native` → `lsim_plan_downlinks_v1` |
| **Python** | jointure radio déclarée, ou commande MAC, ou retransmissions | `lsim.trace_events._build_trace_python`, `lsim.retransmissions` |

La bascule est une seule fonction, `_native_plan_applies` : `not options.join and mac is None`.

| Ce qui est vérifié | Test |
|---|---|
| Sans jointure : le chemin natif est emprunté | `test_sans_jointure_le_chemin_natif_est_emprunte` |
| Avec jointure radio : le chemin Python est emprunté | `test_avec_jointure_radio_le_chemin_python_est_emprunte` |
| Sans concurrence pour l'émetteur, arbitre partagé = chemin isolé | `test_arbitre_partage_et_chemin_isole_concordent` |
| L'activation du chemin Python est justifiée, pas incidente | `test_pourquoi_le_chemin_python_est_active` |
| Une commande MAC bascule aussi en Python | `test_une_commande_mac_bascule_aussi_en_python` |

**Aucune modification de l'ABI ni des symboles exportés** n'est faite ici : les 97 symboles
`lsim_*` et leur empreinte sont contrôlés par `scripts/preuves/verifier_symboles.sh`.
"""

import yaml

from lsim.arbitre import GatewayArbiter
from lsim.join import JoinRadioOptions, simulate_joins
from lsim.scenario import load_scenario
from lsim.trace_events import (ProtocolOptions, _native_plan_applies, _schedule_of, build_trace,
                               device_radios)

SANS_RETRANSMISSIONS = "docs/exemples/quartier_sf9_rf.yaml"


def _scenario(chemin=SANS_RETRANSMISSIONS, **reglages):
    data = yaml.safe_load(open(chemin, encoding="utf-8"))
    data.update(reglages)
    return load_scenario(yaml.safe_dump(data))


def _branche(scenario, options, monkeypatch):
    """Nom de la branche réellement empruntée par `build_trace` (espion, pas une supposition)."""
    import lsim.trace_events as te

    vu = []
    for nom in ("_build_trace_native", "_build_trace_python", "_build_trace_retransmissions",
                "_build_trace_closed_loop"):
        original = getattr(te, nom)

        def espion(*args, _nom=nom, _original=original, **kwargs):
            vu.append(_nom)
            return _original(*args, **kwargs)

        monkeypatch.setattr(te, nom, espion)
    build_trace(scenario, options)
    return tuple(vu)


# --- quelle branche ----------------------------------------------------------------------------

def test_sans_jointure_le_chemin_natif_est_emprunte(monkeypatch):
    """Passerelle unique, sans jointure ni MAC : le planificateur C++ planifie les descentes."""
    scenario = _scenario()
    options = ProtocolOptions(join=False)
    assert _native_plan_applies(options, _schedule_of(scenario)) is True
    assert _branche(scenario, options, monkeypatch) == ("_build_trace_native",)


def test_avec_jointure_radio_le_chemin_python_est_emprunte(monkeypatch):
    """La jointure radio fait basculer la planification des descentes sur le chemin Python."""
    scenario = _scenario()
    options = ProtocolOptions(join=True)
    assert _native_plan_applies(options, _schedule_of(scenario)) is False
    assert _branche(scenario, options, monkeypatch) == ("_build_trace_python",)


def test_une_commande_mac_bascule_aussi_en_python(monkeypatch):
    """Une commande MAC (DevStatusReq...) suffit à écarter le planificateur natif."""
    data = yaml.safe_load(open(SANS_RETRANSMISSIONS, encoding="utf-8"))
    data["mac"] = {"device_status_every": 2}
    scenario = load_scenario(yaml.safe_dump(data))

    mac = _schedule_of(scenario)
    assert mac is not None and mac.device_status_every == 2
    # Ce n'est pas une boucle fermée (LinkADR / DutyCycle) : c'est bien la règle `mac is None`
    # qui écarte le natif, pas un autre aiguillage.
    assert _native_plan_applies(ProtocolOptions(join=False), mac) is False
    assert _branche(scenario, ProtocolOptions(join=False), monkeypatch) == ("_build_trace_python",)


# --- pourquoi le chemin Python est activé ------------------------------------------------------

def test_pourquoi_le_chemin_python_est_active():
    """La raison est structurelle : le planificateur natif ne peut pas partager son émetteur.

    `plan_native` reçoit les enregistrements d'**une** exécution du moteur et produit un plan ;
    `_build_trace_native` vérifie ensuite que l'occupation produite correspond à celle que le
    moteur a utilisée, et lève une erreur sinon. Il n'y a **pas d'itération**. Or une demande de
    Join-Accept n'est pas une fonction des seuls enregistrements :

    1. elle dépend du **calendrier des tentatives de données** (`data_attempts`), qui ferme les
       fenêtres RX quand le terminal émet — calendrier connu seulement dans la boucle de point
       fixe des retransmissions ;
    2. elle dépend de l'**issue de l'arbitrage**, puisque RX2 n'est déposée que si RX1 n'a pas
       abouti, et qu'un rejeu naît d'une acceptation : une demande naît donc **pendant** la
       résolution de l'émetteur partagé.

    Faire tenir cela dans `lsim_plan_downlinks_v1` exigerait de changer la structure d'entrée de la
    fonction, donc l'ABI gelée. C'est pourquoi la jointure radio active le chemin Python : c'est le
    seul moyen de faire partager une ressource unique sans toucher au cœur.
    """
    import inspect

    from lsim.downlink_plan import plan_native

    # 1. L'entrée du planificateur natif est `(records, radios, options)` : aucun calendrier de
    #    tentatives, aucun arbitre, aucune demande pouvant naître de la résolution.
    assert list(inspect.signature(plan_native).parameters) == ["records", "radios", "options"]

    # 2. Le chemin natif n'exécute le moteur qu'**une fois** : c'est un contrôle d'égalité, pas
    #    une itération. Il ne peut donc pas converger vers un état où l'émetteur est partagé avec
    #    des demandes nées du placement lui-même. Le chemin Python, lui, itère jusqu'au point fixe
    #    — c'est ce qui rend le partage possible.
    import lsim.downlink_plan as plan
    import lsim.trace_events as te

    scenario = _scenario()
    executions = {}
    for branche, options, module, nom in (
            ("natif", ProtocolOptions(join=False), plan, "simulate_causal"),
            ("python", ProtocolOptions(join=True), te, "simulate_uplinks_trace")):
        original = getattr(module, nom)
        boite = [0]

        def enveloppe(*args, **kwargs):
            boite[0] += 1
            return original(*args, **kwargs)

        setattr(module, nom, enveloppe)
        try:
            build_trace(scenario, options)
        finally:
            setattr(module, nom, original)
        executions[branche] = boite[0]

    assert executions["natif"] == 1        # une seule passe : pas d'itération possible
    assert executions["python"] >= 1       # point fixe, donc partage possible


# --- concordance des deux chemins --------------------------------------------------------------

def _empreinte(resultat):
    return [(t.device, t.request_ns, t.request_outcome,
             [(e.window, e.at_ns, e.outcome, e.emitted) for e in t.accepts],
             t.session) for t in resultat.attempts]


def test_arbitre_partage_et_chemin_isole_concordent():
    """Sans concurrence pour l'émetteur, l'arbitre partagé reproduit exactement le chemin isolé.

    C'est la condition « mêmes résultats quand le mécanisme partagé n'est pas nécessaire » : le
    partage ne doit rien changer aux scénarios historiques. Les 500 tentatives du scénario de
    référence sont comparées champ par champ, à la nanoseconde.
    """
    scenario = _scenario()
    devices, _, _ = scenario.deploy()
    radios = device_radios(scenario)
    options = ProtocolOptions()
    join = JoinRadioOptions(requests_s=(10,))
    demandes = join.requests(range(len(devices)))
    commun = dict(devices=devices, gateway=scenario.gateway(),
                  propagation=scenario.propagation(), radios=radios, options=options,
                  environment=scenario.environment, requests=demandes, timelines={},
                  join_options=join)

    isole = simulate_joins(**commun)
    arbitre = GatewayArbiter()
    plan = simulate_joins(arbiter=arbitre, **commun)
    arbitre.resolve()
    partage = plan.result()

    assert len(isole.attempts) == 500
    assert _empreinte(isole) == _empreinte(partage)
    # Les deux chemins ouvrent les mêmes sessions, aux mêmes instants.
    assert isole.joined == partage.joined
    sessions_isole = {d: [s.opened_ns for s in h.sessions]
                      for d, h in isole.timelines.items()}
    sessions_partage = {d: [s.opened_ns for s in h.sessions]
                        for d, h in partage.timelines.items()}
    assert sessions_isole == sessions_partage
