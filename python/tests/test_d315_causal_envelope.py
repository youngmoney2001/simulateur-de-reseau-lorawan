"""I4 — enveloppe causale (variante C : pointeurs typés exclusifs).

Contrat : `docs/CAUSAL_ABI_ENVELOPE.md`.

Trois familles de contrôles.

1. **Équivalence sur une chronologie radio commune.** Les huit configurations demandées par la
   revue sont jouées par l'entrée plate correspondante **et** par l'enveloppe, avec les mêmes
   objets C, et les deux sorties sont comparées : enregistrements, occupation passerelle,
   compteurs par terminal et totaux. Comparer deux exécutions séparées ne prouverait rien —
   c'est la même trace qui alimente les deux chemins.

   Les huit configurations couvrent {passerelle v1, passerelle v2} x {sans RX2, avec RX2} x
   {sans frontaux, avec frontaux}, plus un scénario sans région et un scénario saturé où le
   repli RX2 est effectivement exercé.

2. **Validation.** Chaque règle est testée isolément, et l'on vérifie qu'un refus ne déréférence
   aucune table.

3. **Discrimination.** Retirer l'enveloppe ou affaiblir une seule règle fait échouer le test
   correspondant. Vérifié par révocation lors du développement (consigné au §6 du contrat).
"""

import ctypes

import pytest

from lsim.gateway_sensitivity import SX1303_DATASHEET
from lsim.rf import DeviceRf, GatewayRf
from lsim.downlink_plan import (CAUSAL_ABI_VERSION, LIB, _CCausalArgs, _CPlanDevice,
                                _CPlanDeviceRx2, _CPlanOptions, _CInterval, _CTxRecord,
                                DeviceRx2, simulate_causal)
from lsim.plan import get_plan
from lsim.scenario import Scenario, ScenarioModel
from lsim.simulator import Gateway, _c_end_devices
from lsim.trace_events import ProtocolOptions, device_radios
from lsim import _native as N

# Refus de validation de l'enveloppe : LSIM_STATUS_PLAN_BASE + 1.
REFUS = 951
# Refus du moteur (frontaux ou sensibilité invalides) : LSIM_STATUS_SIM_BASE + InvalidInput.
MOTEUR = 301

RAYON = 900


# --------------------------------------------------------------------------- scénarios

def _scene(region=None, sf=10, count=12, period=30, messages=6, spread=10):
    """Scène calme. Sans région par défaut : c'est le cas historique."""
    hz = 868_100_000 if region is None else get_plan(region).uplink_channels_hz()[0]
    groupe = {"name": "g0", "count": count, "channel_freq_hz": hz,
              "placement": {"type": "disk", "radius_m": RAYON},
              "spreading_factor": sf, "payload_bytes": 20, "tx_power_dbm": 14.0,
              "period_s": period, "messages": messages, "start_spread_s": spread}
    if region is not None:
        groupe["region"] = region
        groupe["channel_freq_hz"] = get_plan(region).uplink_channels_hz()[0]
    return Scenario(ScenarioModel.model_validate({
        "schema_version": 1, "name": "i4", "seed": 11,
        "gateway": {"x_m": 0, "y_m": 0, "antenna_gain_dbi": 2.15},
        "propagation": {"frequency_hz": hz, "exponent": 2.7},
        "groups": [groupe]}))


def _scene_saturee():
    """Scène EU868 saturée : des fenêtres RX1 sont manquées, le repli RX2 est exercé.

    Trouvé empiriquement (40 terminaux, SF7, descentes de 200 octets). Sur la scène calme de
    `_scene`, aucune RX1 n'est manquée : la table RX2 y est transmise mais inerte, et le test
    d'équivalence ne détecterait pas qu'elle aurait cessé de l'être. C'est pourquoi un garde-fou
    d'utilité l'épingle plus bas.
    """
    return Scenario(ScenarioModel.model_validate({
        "schema_version": 1, "name": "i4-sature", "seed": 7,
        "gateway": {"x_m": 0, "y_m": 0, "antenna_gain_dbi": 2.15},
        "propagation": {"frequency_hz": 868_100_000, "exponent": 2.7},
        "groups": [{"name": "g0", "count": 40, "region": "EU868",
                    "channel_freq_hz": 868_100_000,
                    "placement": {"type": "disk", "radius_m": 800},
                    "spreading_factor": 7, "payload_bytes": 20, "tx_power_dbm": 14.0,
                    "period_s": 5, "messages": 20, "start_spread_s": 5}]}))


# ------------------------------------------------------------ objets C partagés par les 2 chemins

def _objets_c(scenario, options):
    """Construit UNE fois les objets C que les deux chemins recevront."""
    radios = device_radios(scenario)
    devices, _, _ = scenario.deploy()
    n = len(devices)
    capacity = sum(d.messages for d in devices)

    c_devs = _c_end_devices(devices)
    c_gw = N._CGateway(scenario.gateway().x_m, scenario.gateway().y_m,
                       scenario.gateway().antenna_gain_dbi)
    p = scenario.propagation()
    c_prop = N._CPropagation(p.frequency_hz, p.reference_distance_m, p.exponent,
                             p.capture_threshold_db, p.shadowing_sigma_db, p.shadowing_seed)
    c_env = None
    if scenario.environment is not None:
        from lsim.simulator import _c_environment
        c_env_struct, _keep = _c_environment(scenario.environment)
        c_env = ctypes.pointer(c_env_struct)
    c_radios = (_CPlanDevice * max(1, n))()
    for i, d in enumerate(radios):
        c_radios[i].freq_hz = d.freq_hz
        c_radios[i].dr = -1 if d.dr is None else d.dr
        c_radios[i].rx1_hz = d.rx1_hz
        c_radios[i].tx_power_dbm = d.tx_power_dbm
        c_radios[i].rx1_sf = d.rx1_sf
        c_radios[i].rx1_bw_hz = d.rx1_bw_hz
    c_opt = _CPlanOptions(1 if options.confirmed_uplinks else 0, options.downlink_every,
                          options.downlink_payload_bytes, options.gateway_tx_power_dbm,
                          options.device_antenna_gain_dbi, options.device_rx_offset_db)
    return dict(n=n, capacity=capacity, c_devs=c_devs, c_gw=c_gw, c_prop=c_prop, c_env=c_env,
                c_radios=c_radios, c_opt=c_opt, radios=radios)


def _sorties(n, capacity):
    return ((N._CDeviceStats * max(1, n))(), N._CSimStats(),
            (_CTxRecord * max(1, capacity))(), (_CInterval * max(1, capacity))())


def _lire(n, capacity, c_stats, c_tot, records, busy, count, n_busy):
    """Normalise les sorties en tuples comparables — tout est comparé, rien n'est laissé de côté."""
    return (
        # enregistrements : index, dates, durée, sortie, puissance reçue, SF
        tuple((records[i].device_index, records[i].start_ns, records[i].end_ns,
               records[i].spreading_factor, records[i].rssi_dbm, records[i].outcome)
              for i in range(count.value)),
        # occupation passerelle (les fenêtres radio planifiées)
        tuple((busy[i].start_ns, busy[i].end_ns) for i in range(n_busy.value)),
        # compteurs par terminal
        tuple((c_stats[i].sent, c_stats[i].received, c_stats[i].lost_sensitivity,
               c_stats[i].lost_collision, c_stats[i].airtime_ns, c_stats[i].lost_gateway_busy)
              for i in range(n)),
        # totaux
        (c_tot.sent, c_tot.received, c_tot.lost_sensitivity, c_tot.lost_collision,
         c_tot.airtime_ns, c_tot.gateway_busy_ns, c_tot.gateway_peak_concurrent,
         c_tot.observation_ns, c_tot.lost_gateway_busy),
    )


# ----------------------------------------------------------------- tables optionnelles

def _table_rx2(o):
    """Une table RX2 complète, dérivée des radios de la scène.

    `DeviceRx2` est un simple dataclass sans `to_c()` : la structure C est remplie champ par
    champ, exactement comme le fait `simulate_causal` en production.
    """
    table = []
    for r in o["radios"]:
        c = _CPlanDeviceRx2()
        c.rx2_hz = r.rx2_hz
        c.rx2_sf = r.rx2_sf
        c.rx2_bw_hz = r.rx2_bw_hz
        table.append(c)
    return tuple(table)


def _frontaux(o):
    """Frontaux terminaux complets. `present` vient de `to_c()`, jamais posé à la main."""
    return tuple(DeviceRf(antenna_gain_dbi=2.0, cable_loss_db=0.5).to_c() for _ in range(o["n"]))


def _frontal_passerelle():
    return GatewayRf(antenna_gain_dbi=3.0, cable_loss_db=1.0).to_c()


def _passerelle_v2(o):
    """Passerelle v2 avec seuils complets — un modèle activé sans seuil est refusé (301)."""
    return SX1303_DATASHEET.to_c(Gateway(x_m=o["c_gw"].x_m, y_m=o["c_gw"].y_m,
                                         antenna_gain_dbi=o["c_gw"].antenna_gain_dbi,
                                         rx_sensitivity_offset_db=0.0))


# ---------------------------------------------------- les deux chemins, mêmes objets C

def _jouer_plate(o, passerelle, rx2, device_rf, gateway_rf):
    """Appelle l'entrée plate correspondant exactement à la configuration."""
    n, capacity = o["n"], o["capacity"]
    c_stats, c_tot, records, busy = _sorties(n, capacity)
    count, n_busy = ctypes.c_size_t(0), ctypes.c_size_t(0)

    c_rx2 = None
    n_rx2 = 0
    if rx2 is not None:
        c_rx2 = (_CPlanDeviceRx2 * n)()
        for i, r in enumerate(rx2):
            c_rx2[i] = r
        n_rx2 = n
    c_dev_rf = None
    n_dev_rf = 0
    if device_rf is not None:
        c_dev_rf = (N._CDeviceRf * n)()
        for i, e in enumerate(device_rf):
            c_dev_rf[i] = e
        n_dev_rf = n

    base = [o["c_devs"] if n else None, n, ctypes.byref(passerelle), ctypes.byref(o["c_prop"]),
            ctypes.byref(o["c_env"][0]) if o["c_env"] is not None else None,
            c_stats if n else None, ctypes.byref(c_tot), records, capacity, ctypes.byref(count),
            o["c_radios"] if n else None, ctypes.byref(o["c_opt"]), busy, capacity,
            ctypes.byref(n_busy)]
    if n_rx2 or n_dev_rf or gateway_rf is not None:
        # v3 réunit RX2 et frontaux. Sans aucune des deux extensions : v1 (ou gw2).
        if isinstance(passerelle, N._CGatewayV2):
            statut = LIB.lsim_simulate_uplinks_causal_gw2_v3(
                *(base + [c_rx2, n_rx2, c_dev_rf if n_dev_rf else None, n_dev_rf, gateway_rf]))
        else:
            statut = LIB.lsim_simulate_uplinks_causal_v3(
                *(base + [c_rx2, n_rx2, c_dev_rf if n_dev_rf else None, n_dev_rf, gateway_rf]))
    elif isinstance(passerelle, N._CGatewayV2):
        statut = LIB.lsim_simulate_uplinks_causal_gw2(*base)
    else:
        statut = LIB.lsim_simulate_uplinks_causal_v1(*base)
    return statut, _lire(n, capacity, c_stats, c_tot, records, busy, count, n_busy)


def _jouer_enveloppe(o, passerelle, rx2, device_rf, gateway_rf):
    """Appelle l'enveloppe avec les mêmes objets C et les mêmes tables."""
    n, capacity = o["n"], o["capacity"]
    c_stats, c_tot, records, busy = _sorties(n, capacity)
    count, n_busy = ctypes.c_size_t(0), ctypes.c_size_t(0)

    args = _CCausalArgs()
    args.struct_size = ctypes.sizeof(_CCausalArgs)
    args.abi_version = CAUSAL_ABI_VERSION
    args.devices = o["c_devs"] if n else None
    args.device_count = n
    if isinstance(passerelle, N._CGatewayV2):
        args.gateway_v2 = ctypes.pointer(passerelle)
    else:
        args.gateway = ctypes.pointer(passerelle)
    args.prop = ctypes.pointer(o["c_prop"])
    args.env = o["c_env"]
    args.radios = o["c_radios"] if n else None
    args.options = ctypes.pointer(o["c_opt"])
    args.per_device = c_stats if n else None
    args.totals = ctypes.pointer(c_tot)
    args.records = records
    args.record_capacity = capacity
    args.record_count = ctypes.pointer(count)
    args.busy_out = busy
    args.busy_capacity = capacity
    args.busy_count = ctypes.pointer(n_busy)

    if rx2 is not None:
        c_rx2 = (_CPlanDeviceRx2 * n)()
        for i, r in enumerate(rx2):
            c_rx2[i] = r
        args.rx2 = c_rx2
        args.rx2_count = n
    if device_rf is not None:
        c_dev_rf = (N._CDeviceRf * n)()
        for i, e in enumerate(device_rf):
            c_dev_rf[i] = e
        args.device_rf = c_dev_rf
        args.device_rf_count = n
    if gateway_rf is not None:
        args.gateway_rf = ctypes.pointer(gateway_rf)

    statut = LIB.lsim_simulate_uplinks_causal(ctypes.byref(args))
    return statut, _lire(n, capacity, c_stats, c_tot, records, busy, count, n_busy)


# ================================================ 1. équivalence sur une chronologie commune
#
# Les huit configurations de la revue : {v1, v2} x {sans RX2, avec RX2} x {sans frontaux, avec
# frontaux}. Scène saturée pour que le repli RX2 soit effectivement exercé.

CONFIGURATIONS = ("v1_nue", "v1_rx2", "v1_frontaux", "v1_rx2_frontaux",
                  "v2_nue", "v2_rx2", "v2_frontaux", "v2_rx2_frontaux")


@pytest.mark.parametrize("configuration", CONFIGURATIONS)
def test_enveloppe_et_entree_plate_produisent_la_meme_chronologie(configuration):
    """L'enveloppe ne change rien : mêmes enregistrements, mêmes fenêtres, mêmes compteurs.

    Les deux chemins reçoivent les MÊMES objets C et les MÊMES tables. Une divergence sur un seul
    enregistrement, une seule fenêtre d'occupation ou un seul compteur échoue ici.
    """
    scenario = _scene_saturee()
    options = ProtocolOptions(confirmed_uplinks=True, downlink_every=1,
                              downlink_payload_bytes=200, gateway_tx_power_dbm=27.0,
                              rx2_fallback=True)
    o = _objets_c(scenario, options)

    v2 = configuration.startswith("v2")
    passerelle = _passerelle_v2(o) if v2 else o["c_gw"]
    avec_rx2 = "rx2" in configuration
    avec_frontaux = "frontaux" in configuration
    rx2 = _table_rx2(o) if avec_rx2 else None
    dev_rf = _frontaux(o) if avec_frontaux else None
    gw_rf = _frontal_passerelle() if avec_frontaux else None

    statut_plate, sortie_plate = _jouer_plate(o, passerelle, rx2, dev_rf, gw_rf)
    statut_env, sortie_env = _jouer_enveloppe(o, passerelle, rx2, dev_rf, gw_rf)

    assert statut_plate == 0, f"[{configuration}] entrée plate : statut {statut_plate}"
    assert statut_env == 0, f"[{configuration}] enveloppe : statut {statut_env}"

    # Garde-fou d'utilité : sur cette scène, la table RX2 change le résultat. Sans lui, une scène
    # trop calme ferait passer le test même si l'enveloppe cessait de transmettre RX2.
    if avec_rx2:
        _, sans_rx2 = _jouer_plate(o, passerelle, None, dev_rf, gw_rf)
        assert sans_rx2 != sortie_plate, (
            f"[{configuration}] scène inerte : la table RX2 ne change rien, le test ne "
            "prouverait pas qu'elle est transmise")

    # Comparaison composant par composant, pour que l'écart soit lisible.
    for etiquette, a, b in (("enregistrements", sortie_plate[0], sortie_env[0]),
                            ("occupation passerelle", sortie_plate[1], sortie_env[1]),
                            ("compteurs par terminal", sortie_plate[2], sortie_env[2]),
                            ("totaux", sortie_plate[3], sortie_env[3])):
        assert a == b, f"[{configuration}] divergence sur les {etiquette}"
    assert sortie_env == sortie_plate, f"[{configuration}] divergence non localisée"


def test_equivalence_sur_une_scene_sans_region():
    """Scénario historique : sans région, la table RX2 est vide et rien ne doit changer."""
    scenario = _scene(region=None, sf=9)
    options = ProtocolOptions(confirmed_uplinks=True, downlink_every=2,
                              downlink_payload_bytes=60, gateway_tx_power_dbm=27.0)
    o = _objets_c(scenario, options)
    assert all(r.rx2_hz == 0 for r in o["radios"]), "sans région, aucune RX2 renseignée"

    for passerelle in (o["c_gw"], _passerelle_v2(o)):
        statut_plate, sortie_plate = _jouer_plate(o, passerelle, None, None, None)
        statut_env, sortie_env = _jouer_enveloppe(o, passerelle, None, None, None)
        assert statut_plate == statut_env == 0
        assert sortie_env == sortie_plate


def test_les_deux_passerelles_ne_donnent_pas_le_meme_resultat():
    """Garde-fou : v1 et v2 doivent différer, sinon le paramètre `passerelle` ne serait pas testé.

    Sans cette assertion, une enveloppe qui ignorerait `gateway_v2` passerait l'équivalence v2 en
    renvoyant le résultat v1. Les seuils sont volontairement sourds (−70 dBm) : avec les valeurs publiées SX1303,
    comme avec des seuils très sensibles, cette scène ne perd aucune trame en sensibilité et
    les deux modèles donnent le même résultat — le garde-fou ne prouverait rien.
    """
    from lsim.gateway_sensitivity import AbsoluteSensitivity

    sourde = AbsoluteSensitivity(points=tuple((125_000, sf, -70.0) for sf in range(7, 13)),
                                 source="test")
    scenario = _scene_saturee()
    options = ProtocolOptions(confirmed_uplinks=True, downlink_every=1,
                              downlink_payload_bytes=200, gateway_tx_power_dbm=27.0)
    o = _objets_c(scenario, options)
    gw_v2 = sourde.to_c(Gateway(x_m=o["c_gw"].x_m, y_m=o["c_gw"].y_m,
                                antenna_gain_dbi=o["c_gw"].antenna_gain_dbi,
                                rx_sensitivity_offset_db=0.0))
    _, v1 = _jouer_plate(o, o["c_gw"], None, None, None)
    _, v2 = _jouer_plate(o, gw_v2, None, None, None)
    assert v1 != v2, "passerelle v1 et v2 donnent le même résultat : le paramètre est inerte"


def test_la_production_passe_par_lenveloppe():
    """`simulate_causal` (chemin de production) appelle l'enveloppe, et non une entrée plate.

    Garde-fou : sans lui, l'enveloppe resterait une structure jamais exercée et les tests
    d'équivalence ci-dessus ne prouveraient rien de ce que fait réellement le simulateur.
    """
    import inspect

    source = inspect.getsource(simulate_causal)
    assert "lsim_simulate_uplinks_causal(" in source, (
        "`simulate_causal` n'appelle pas l'enveloppe causale")
    for entree in ("causal_v1", "causal_v3", "causal_gw2_v3", "causal_gw2_v2", "causal_v2",
                   "causal_gw2("):
        assert f"LIB.lsim_simulate_uplinks_{entree}" not in source, (
            f"`simulate_causal` appelle encore l'entrée plate {entree}")


# ======================================================================= 2. validation

def _args_valides(o, v2=False):
    """Enveloppe minimale valide. Les compteurs de sortie restent lisibles après l'appel."""
    n, capacity = o["n"], o["capacity"]
    c_stats, c_tot, records, busy = _sorties(n, capacity)
    args = _CCausalArgs()
    args.struct_size = ctypes.sizeof(_CCausalArgs)
    args.abi_version = CAUSAL_ABI_VERSION
    args.devices = o["c_devs"] if n else None
    args.device_count = n
    if v2:
        args.gateway_v2 = ctypes.pointer(_passerelle_v2(o))
    else:
        args.gateway = ctypes.pointer(o["c_gw"])
    args.gateway = ctypes.pointer(o["c_gw"]) if not v2 else None
    args.prop = ctypes.pointer(o["c_prop"])
    args.env = o["c_env"]
    args.radios = o["c_radios"] if n else None
    args.options = ctypes.pointer(o["c_opt"])
    args.per_device = c_stats if n else None
    args.totals = ctypes.pointer(c_tot)
    args.records = records
    args.record_capacity = capacity
    args.record_count = ctypes.pointer(ctypes.c_size_t(0))
    args.busy_out = busy
    args.busy_capacity = capacity
    args.busy_count = ctypes.pointer(ctypes.c_size_t(0))
    # Les compteurs doivent rester attribués à l'objet : sinon ramassés avant la lecture.
    args._sorties = (c_stats, c_tot, records, busy)
    return args


@pytest.mark.parametrize("v2", (False, True))
def test_enveloppe_valide_reussit(v2):
    o = _objets_c(_scene(), ProtocolOptions())
    assert LIB.lsim_simulate_uplinks_causal(ctypes.byref(_args_valides(o, v2=v2))) == 0


@pytest.mark.parametrize("champ,valeur", (("struct_size", 191), ("struct_size", 0),
                                          ("struct_size", 193), ("abi_version", 2),
                                          ("abi_version", 0)))
def test_taille_et_version_sont_verifiees(champ, valeur):
    o = _objets_c(_scene(), ProtocolOptions())
    args = _args_valides(o)
    setattr(args, champ, valeur)
    assert LIB.lsim_simulate_uplinks_causal(ctypes.byref(args)) == REFUS


def test_args_null_est_refuse():
    assert LIB.lsim_simulate_uplinks_causal(None) == REFUS


def test_les_deux_passerelles_sont_exclusives():
    """Exactement une passerelle : ni aucune, ni les deux."""
    o = _objets_c(_scene(), ProtocolOptions())

    aucune = _args_valides(o)
    aucune.gateway = None
    assert LIB.lsim_simulate_uplinks_causal(ctypes.byref(aucune)) == REFUS

    les_deux = _args_valides(o)
    les_deux.gateway_v2 = ctypes.pointer(_passerelle_v2(o))
    assert LIB.lsim_simulate_uplinks_causal(ctypes.byref(les_deux)) == REFUS

    # La passerelle v2 seule est acceptée : c'est elle qui remplace gw2 et gw2_v3.
    v2_seule = _args_valides(o, v2=True)
    assert LIB.lsim_simulate_uplinks_causal(ctypes.byref(v2_seule)) == 0


@pytest.mark.parametrize("table", ("rx2", "device_rf"))
def test_pointeur_et_compte_sont_solidaires(table):
    """Une table est fournie entièrement ou pas du tout : aucun compte orphelin.

    C'est la règle qui interdit de lire une longueur qui n'est pas celle du tableau pointé
    (`DOWNLINK_PLAN_ABI_V2.md` §2.3).
    """
    o = _objets_c(_scene(), ProtocolOptions())
    n = o["n"]
    if table == "rx2":
        tableau = (_CPlanDeviceRx2 * n)()
    else:
        tableau = (N._CDeviceRf * n)()

    # Compte sans pointeur.
    orphelin = _args_valides(o)
    setattr(orphelin, f"{table}_count", n)
    assert LIB.lsim_simulate_uplinks_causal(ctypes.byref(orphelin)) == REFUS

    # Pointeur sans compte.
    sans_compte = _args_valides(o)
    setattr(sans_compte, table, tableau)
    assert LIB.lsim_simulate_uplinks_causal(ctypes.byref(sans_compte)) == REFUS

    # Longueur annoncée différente de celle attendue.
    mauvaise = _args_valides(o)
    setattr(mauvaise, table, tableau)
    setattr(mauvaise, f"{table}_count", n + 1)
    assert LIB.lsim_simulate_uplinks_causal(ctypes.byref(mauvaise)) == REFUS


def test_un_refus_ne_derefence_aucune_table():
    """Un refus doit être décidé avant tout accès : les sorties restent telles quelles.

    On passe des pointeurs VOLONTAIREMENT invalides avec un compte cohérent : si la validation
    lisait les tables avant de refuser, l'accès se produirait.
    """
    o = _objets_c(_scene(), ProtocolOptions())
    args = _args_valides(o)
    args.abi_version = 2  # refus garanti, avant toute lecture
    args.rx2 = ctypes.cast(0x1, ctypes.POINTER(_CPlanDeviceRx2))  # adresse non mappée
    args.rx2_count = o["n"]
    args.device_rf = ctypes.cast(0x1, ctypes.POINTER(N._CDeviceRf))
    args.device_rf_count = o["n"]
    assert LIB.lsim_simulate_uplinks_causal(ctypes.byref(args)) == REFUS


def test_passerelle_v2_sans_seuil_est_refusee_par_le_moteur():
    """Le modèle absolu activé sans seuil est refusé par le moteur (301), pas par l'enveloppe.

    Ce test distingue un refus de validation de l'enveloppe (951) d'un refus du moteur (301) :
    l'enveloppe ne doit pas masquer le second.
    """
    o = _objets_c(_scene_saturee(), ProtocolOptions())
    gw2 = N._CGatewayV2()
    gw2.base.x_m = o["c_gw"].x_m
    gw2.base.y_m = o["c_gw"].y_m
    gw2.base.antenna_gain_dbi = o["c_gw"].antenna_gain_dbi
    gw2.sensitivity_model = 1  # modèle absolu, `present` laissé à zéro

    args = _args_valides(o)
    args.gateway = None
    args.gateway_v2 = ctypes.pointer(gw2)
    assert LIB.lsim_simulate_uplinks_causal(ctypes.byref(args)) == MOTEUR


def test_les_champs_sont_des_pointeurs_types():
    """Sûreté de typage (variante C) : chaque table a son propre type, jamais `void*`.

    Passer la mauvaise structure à un champ lève `TypeError` au lieu de corrompre la mémoire.
    C'est la propriété qui distingue la variante C de la variante B écartée.
    """
    champs = {nom: typ for nom, typ in _CCausalArgs._fields_}
    for nom in ("rx2", "device_rf", "gateway_rf"):
        assert champs[nom] is not ctypes.c_void_p, f"{nom} : void* interdit"
    # Et les trois types sont distincts : une confusion est une erreur, pas une conversion.
    assert len({champs["rx2"], champs["device_rf"], champs["gateway_rf"]}) == 3

    args = _CCausalArgs()
    with pytest.raises(TypeError):
        args.device_rf = (_CPlanDeviceRx2 * 1)()  # tableau RX2 là où l'on attend des frontaux


def test_la_disposition_python_egale_celle_du_harnais_abi():
    """Les tailles et décalages ctypes doivent égaler ceux épinglés par `static_assert`."""
    attendu = {"struct_size": 0, "abi_version": 4, "devices": 8, "device_count": 16,
               "gateway": 24, "gateway_v2": 32, "prop": 40, "env": 48, "radios": 56,
               "options": 64, "per_device": 72, "totals": 80, "records": 88,
               "record_capacity": 96, "record_count": 104, "busy_out": 112,
               "busy_capacity": 120, "busy_count": 128, "rx2": 136, "rx2_count": 144,
               "device_rf": 152, "device_rf_count": 160, "gateway_rf": 168, "reserved": 176}
    assert ctypes.sizeof(_CCausalArgs) == 192
    for nom, decalage in attendu.items():
        assert getattr(_CCausalArgs, nom).offset == decalage, f"{nom} : décalage"
