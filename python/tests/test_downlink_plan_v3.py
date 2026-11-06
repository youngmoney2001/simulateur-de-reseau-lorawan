"""I6-c — enveloppe `lsim_plan_downlinks_v3` : validation de N par fenêtre dans le cœur.

Le jalon I6-c porte dans le cœur C++ la règle d'éligibilité par fenêtre (R-N1…R-N4) déjà
implémentée côté Python. Avant lui, les deux moteurs divergeaient dès que la charge dépassait
N : le cœur émettait des descentes intransportables (EU868 : 260 émissions là où l'oracle en
produisait 0).

Ce fichier vérifie trois choses, dans cet ordre :

1. **la parité** — les deux moteurs coïncident, sur les sept régions et des deux côtés de la
   limite N (T-C-5, T-C-6) ;
2. **la règle** — une fenêtre inéligible n'est jamais réservée, et l'inéligibilité de RX1 ne
   clôt pas l'examen de RX2 (T-C-9, T-C-10) ;
3. **la frontière** — les refus sont explicites, jamais un repli silencieux vers la v2
   (T-C-2 à T-C-4), et un ACK n'est jamais refusé pour capacité (T-C-8).

Aucune dégradation silencieuse n'est acceptée : passer `limits = None` à la v3 est **rejeté**.
Qui veut le comportement sans contrainte appelle `plan_native_v2` — c'est le seul moyen, et il
est explicite (arbitrages bbb3 et bbb5).
"""

import dataclasses

import pytest

from lsim.downlink_plan import (LSIM_PLAN_DOWNLINKS_V3_ABI_VERSION, LIB, DeviceLimits,
                                _CPlanDeviceLimits, _CPlanDeviceRx2, _CPlanDownlinksV3Args,
                                plan_native, plan_native_v2, plan_native_v3)
from lsim.plan import get_plan
from lsim.scenario import Scenario, ScenarioModel
from lsim.trace_events import (MOTIF_NO_WINDOW_CAPACITY, MOTIFS_CAPACITE, MOTIFS_TEMPOREL,
                               ProtocolOptions, _downlink_jobs, _events,
                               _schedule_gateway_with_motifs, _table_rx2, device_radios)

# Sept régions, avec les réglages retenus par le recalibrage D3.15-R. US915 et AU915 emploient
# deux groupes de SF : voir `docs/D315_RECALIBRAGE.md` §C.2.
REGLAGES = {
    "EU868": dict(sfs=(11,), count=60, spread=60),
    "US915": dict(sfs=(10, 7), count=30, spread=2.0),
    "AS923": dict(sfs=(7,), count=60, spread=60),
    "AU915": dict(sfs=(10, 8), count=30, spread=3.0),
    "IN865": dict(sfs=(7,), count=60, spread=60),
    "KR920": dict(sfs=(9,), count=60, spread=60),
    "RU864": dict(sfs=(10,), count=60, spread=60),
}

REGIONS = tuple(REGLAGES)
CHARGE_CONFORME = 40     # sous N(RX2) de toutes les régions : 51 ou 53
CHARGE_HISTORIQUE = 120  # au-delà de N(RX2) : le régime où les moteurs divergeaient


def _canal(region):
    return get_plan(region).uplink_channels_hz()[0]


def _scene(region, sfs, count, spread, period=5, messages=20, rayon=600):
    """Scène recalibrée. Un groupe par SF : plusieurs SF ⇒ plusieurs groupes."""
    f0 = _canal(region)
    groupes = [
        {"name": f"g{i}", "count": count, "region": region, "channel_freq_hz": f0,
         "placement": {"type": "disk", "radius_m": rayon}, "spreading_factor": sf,
         "payload_bytes": 20, "tx_power_dbm": 14.0, "period_s": period,
         "messages": messages, "start_spread_s": spread}
        for i, sf in enumerate(sfs)]
    return Scenario(ScenarioModel.model_validate({
        "schema_version": 1, "name": "i6c", "seed": 11,
        "gateway": {"x_m": 0, "y_m": 0, "antenna_gain_dbi": 2.15},
        "propagation": {"frequency_hz": f0, "exponent": 2.7}, "groups": groupes}))


def _options(charge, every=1, repli=True):
    return ProtocolOptions(confirmed_uplinks=True, downlink_every=every,
                           downlink_payload_bytes=charge, gateway_tx_power_dbm=27.0,
                           rx2_fallback=repli)


def _course(region, charge, every=1):
    """Trace, radios, limites et planification des deux moteurs sur la même scène."""
    p = REGLAGES[region]
    scenario = _scene(region, p["sfs"], p["count"], p["spread"])
    radios = device_radios(scenario)
    devices, _, _ = scenario.deploy()
    records = _trace(devices, scenario)
    limits = tuple(DeviceLimits(r.rx1_max_payload or 0, r.rx2_max_payload or 0) for r in radios)
    options = _options(charge, every)
    rx2 = _table_rx2(radios)
    evenements_coeur, occupation_coeur = plan_native_v3(records, radios, options, rx2, limits)
    jobs = _downlink_jobs(records, radios, options, [False] * len(records), None)
    starts, fenetres, occupation_oracle, motifs = _schedule_gateway_with_motifs(jobs, options)
    evenements_oracle = _events(records, radios, jobs, starts, [False] * len(records), None,
                               fenetres, options)
    return dict(records=records, radios=radios, limits=limits, options=options, rx2=rx2,
                coeur=(evenements_coeur, occupation_coeur),
                oracle=(evenements_oracle, occupation_oracle), fenetres=fenetres, motifs=motifs)


def _trace(devices, scenario):
    from lsim.simulator import simulate_uplinks_trace
    return simulate_uplinks_trace(devices, scenario.gateway(), scenario.propagation(),
                                  scenario.environment, gateway_busy=()).records


def _sauts_descendants(evenements):
    return tuple(sorted((e.t_ns, e.device_index, h.freq_hz, h.outcome)
                        for e in evenements for h in e.hops
                        if h.to_id.startswith("dev:")))


# ------------------------------------------------------------------------- T-C-1 disposition

def test_disposition_ctypes_conforme_au_harnais_abi():
    """Les structures ctypes épousent exactement l'en-tête C.

    `argtypes` et `restype` sont déclarés explicitement : sans eux, ctypes convertit chaque
    entier en `c_int` 32 bits et tronque un `size_t` ou un pointeur (défaut déjà rencontré :
    faute de segmentation).
    """
    import ctypes

    assert LSIM_PLAN_DOWNLINKS_V3_ABI_VERSION == 1
    # Deux int32 puis deux mots de réservation : 8 + 16 = 24 octets, alignés sur 8.
    assert ctypes.sizeof(_CPlanDeviceLimits) == 24
    assert [n for n, _ in _CPlanDeviceLimits._fields_] == ["rx1_max_payload", "rx2_max_payload",
                                                           "reserved"]
    noms = [n for n, _ in _CPlanDownlinksV3Args._fields_]
    # L'ordre des champs est celui de `c_api.h` : une inversion échangerait deux pointeurs.
    assert noms[:4] == ["struct_size", "abi_version", "uplinks", "uplink_count"]
    assert noms.index("limits") == noms.index("rx2_count") + 1
    assert noms.index("limits_count") == noms.index("limits") + 1
    assert noms[-1] == "reserved"
    assert LIB.lsim_plan_downlinks_v3.restype == ctypes.c_int32
    assert LIB.lsim_plan_downlinks_v3.argtypes == [ctypes.POINTER(_CPlanDownlinksV3Args)]


# ----------------------------------------------------------------- T-C-2 à T-C-4 refus explicites

def test_limits_absent_est_rejete_sans_degrader_vers_v2():
    """T-C-2 : `limits = None` est rejeté, il ne dégrade pas silencieusement vers la v2.

    C'est tout l'objet de l'arbitrage bbb5 : un appelant qui croit fournir des limites et n'en
    fournit pas doit échouer bruyamment, pas obtenir un calcul sans contrainte.
    """
    c = _course("EU868", CHARGE_CONFORME)
    with pytest.raises(ValueError, match="limits est obligatoire"):
        plan_native_v3(c["records"], c["radios"], c["options"], c["rx2"], None)


@pytest.mark.parametrize("region", REGIONS)
def test_limits_de_mauvaise_longueur_est_rejete(region):
    """T-C-3 : un comptage inexact est refusé **sans lire une seule entrée**.

    Un pointeur ne dit pas la longueur de son tableau : sans ce contrôle, le cœur lirait
    `device_count` entrées quelle que soit la taille réellement fournie.
    """
    c = _course(region, CHARGE_CONFORME)
    tronque = c["limits"][:-1]
    with pytest.raises(ValueError):
        plan_native_v3(c["records"], c["radios"], c["options"], c["rx2"], tronque)


@pytest.mark.parametrize("valeur", (-1, 243, 999, 1 << 20))
def test_n_hors_bornes_est_rejete(valeur):
    """T-C-4 : aucune sentinelle — un N hors `[0, 242]` est refusé, pas interprété.

    Une valeur réservée qui signifierait « pas de contrainte » serait une sentinelle, et donc
    un repli silencieux déguisé. L'absence de contrainte s'exprime en appelant la v2.
    """
    c = _course("EU868", CHARGE_CONFORME)
    for borne in ("rx1", "rx2"):
        mauvais = (DeviceLimits(valeur, 51) if borne == "rx1"
                   else DeviceLimits(51, valeur))
        limites = (mauvais,) + c["limits"][1:]
        with pytest.raises(ValueError):
            plan_native_v3(c["records"], c["radios"], c["options"], c["rx2"], limites)


# ------------------------------------------------------------------------- T-C-5 / T-C-6 parité

@pytest.mark.parametrize("region", REGIONS)
def test_parite_a_charge_conforme(region):
    """T-C-5 : les deux moteurs coïncident quand la charge tient dans N.

    C'était déjà vrai avant I6-c dans les sept régions ; c'est la non-régression de référence.
    """
    c = _course(region, CHARGE_CONFORME)
    (ev_c, occ_c), (ev_o, occ_o) = c["coeur"], c["oracle"]
    assert tuple(occ_c) == tuple(occ_o), f"{region} : occupation"
    assert _sauts_descendants(ev_c) == _sauts_descendants(ev_o), f"{region} : sauts descendants"
    assert (tuple((e.kind, e.outcome) for e in ev_c)
            == tuple((e.kind, e.outcome) for e in ev_o)), f"{region} : motifs de refus"


@pytest.mark.parametrize("region", REGIONS)
def test_parite_au_dela_de_n_la_divergence_historique_disparait(region):
    """T-C-6 : au-delà de N, le cœur n'émet plus ce qui est intransportable.

    C'est le défaut que I6-c corrige, région par région. Avant lui : EU868 260 contre 0,
    KR920 54 contre 0, RU864 320 contre 0, AS923 211 contre 371, IN865 211 contre 371,
    US915 220 contre 200, AU915 240 contre 220.
    """
    c = _course(region, CHARGE_HISTORIQUE)
    (ev_c, occ_c), (ev_o, occ_o) = c["coeur"], c["oracle"]
    assert tuple(occ_c) == tuple(occ_o), (
        f"{region} : occupation divergente au-delà de N "
        f"({len(occ_c)} émissions cœur contre {len(occ_o)} oracle)")
    assert _sauts_descendants(ev_c) == _sauts_descendants(ev_o), f"{region} : sauts descendants"


# ------------------------------------------------------------------------- T-C-7 non-régression

@pytest.mark.parametrize("region", REGIONS)
def test_la_v3_egale_la_v2_quand_la_charge_tient(region):
    """T-C-7 : à charge conforme, activer la contrainte ne change rien — elle ne mord pas.

    S'il y avait une divergence ici, la règle R-N1 serait mal bornée : elle refuserait des
    trames légales.
    """
    c = _course(region, CHARGE_CONFORME)
    _, occ_v2 = plan_native_v2(c["records"], c["radios"], c["options"], c["rx2"])
    _, occ_v3 = plan_native_v3(c["records"], c["radios"], c["options"], c["rx2"], c["limits"])
    assert tuple(occ_v3) == tuple(occ_v2), f"{region} : la v3 modifie un calcul conforme"


def test_la_v1_reste_inchangee():
    """T-C-7 : la v1 ne replie jamais et ne connaît aucune limite — comportement figé."""
    c = _course("EU868", CHARGE_CONFORME)
    _, occ_v1 = plan_native(c["records"], c["radios"], c["options"])
    _, occ_v2 = plan_native_v2(c["records"], c["radios"], c["options"], None)
    assert tuple(occ_v1) == tuple(occ_v2), "la v1 doit rester le comportement de la v2 sans RX2"


# ----------------------------------------------------------------- T-C-8 ACK hors de la contrainte

@pytest.mark.parametrize("region", REGIONS)
def test_un_ack_nest_jamais_refuse_pour_capacite(region):
    """T-C-8 : la contrainte ne porte que sur les descentes applicatives.

    Garde-fou 14 : ne pas confondre les contraintes du Join-Accept et celles des charges
    applicatives. Un ACK pur n'est pas une descente applicative : même avec N nul partout, il
    doit être émis.
    """
    c = _course(region, CHARGE_CONFORME, every=0)   # every=0 : aucun downlink de données
    nuls = tuple(DeviceLimits(0, 0) for _ in c["radios"])
    # Nuls des deux côtés : l'oracle lit N sur les radios, le cœur sur la table.
    radios_nuls = tuple(dataclasses.replace(r, rx1_max_payload=0, rx2_max_payload=0)
                        for r in c["radios"])
    _, occ = plan_native_v3(c["records"], c["radios"], c["options"], c["rx2"], nuls)
    jobs = _downlink_jobs(c["records"], radios_nuls, c["options"],
                          [False] * len(c["records"]), None)
    _debuts, fenetres, occ_oracle, motifs = _schedule_gateway_with_motifs(jobs, c["options"])
    assert len(occ) > 0, f"{region} : les ACK ont été refusés pour capacité"
    assert tuple(occ) == tuple(occ_oracle), f"{region} : parité sur les ACK seuls"
    assert not [m for m in motifs if m in MOTIFS_CAPACITE], (
        f"{region} : motif de capacité sur un ACK : "
        f"{[m for m in motifs if m in MOTIFS_CAPACITE]}")


# ------------------------------------------------------------- T-C-9 / T-C-10 la règle elle-même

@pytest.mark.parametrize("valeur, attend_emission", ((39, False), (40, True), (41, True)))
def test_la_frontiere_de_n_est_exacte(valeur, attend_emission):
    """T-C-9 : la fenêtre est éligible dès que la charge tient dans N, et pas avant.

    `charge <= N`, bornes incluses. Une règle stricte (`<`) décalerait la frontière d'un octet
    et rejetterait des trames légales.
    """
    c = _course("EU868", CHARGE_CONFORME)
    n = valeur
    radios_n = tuple(dataclasses.replace(r, rx1_max_payload=n, rx2_max_payload=n)
                     for r in c["radios"])
    n_limites = tuple(DeviceLimits(n, n) for _ in c["radios"])
    _, occ = plan_native_v3(c["records"], c["radios"], c["options"], c["rx2"], n_limites)
    jobs = _downlink_jobs(c["records"], radios_n, c["options"],
                          [False] * len(c["records"]), None)
    _debuts, _f, occ_oracle, motifs = _schedule_gateway_with_motifs(jobs, c["options"])
    assert bool(occ) is attend_emission, (
        f"N={n} pour une charge de {CHARGE_CONFORME} : {len(occ)} émission(s)")
    assert tuple(occ) == tuple(occ_oracle), f"N={n} : parité"
    if not attend_emission:
        assert set(m for m in motifs if m) == {MOTIF_NO_WINDOW_CAPACITY}


def test_aucune_fenetre_eligible_n_reserve_rien():
    """T-C-9 : une fenêtre inéligible n'est **jamais demandée** — elle n'occupe pas l'émetteur.

    R-N2. C'est la différence entre « refusé » et « demandé puis manqué » : une fenêtre
    inéligible ne doit laisser aucune trace dans l'occupation, sinon elle bloquerait les
    descentes suivantes pour une émission qui n'a jamais eu lieu.
    """
    c = _course("EU868", CHARGE_CONFORME)
    nuls = tuple(DeviceLimits(0, 0) for _ in c["radios"])
    _, occ = plan_native_v3(c["records"], c["radios"], c["options"], c["rx2"], nuls)
    assert not occ, (
        f"des fenêtres inéligibles ont réservé l'émetteur : {len(occ)} occupation(s)")


def test_rx1_ineligible_rx2_eligible_la_rx2_est_emise():
    """T-C-10 : l'inéligibilité de RX1 ne clôt pas l'examen — RX2 est demandée (R-N3).

    Une charge trop lourde pour RX1 mais qui tient dans RX2 n'est pas perdue : le terminal
    ouvre RX2 comme le protocole le prévoit, et le cœur doit l'examiner.
    """
    c = _course("EU868", CHARGE_CONFORME)
    # RX1 inéligible (N = 39 < 40), RX2 éligible (N = 51 ≥ 40).
    radios_n = tuple(dataclasses.replace(r, rx1_max_payload=39, rx2_max_payload=51)
                     for r in c["radios"])
    limites = tuple(DeviceLimits(39, 51) for _ in c["radios"])
    _, occ = plan_native_v3(c["records"], c["radios"], c["options"], c["rx2"], limites)
    jobs = _downlink_jobs(c["records"], radios_n, c["options"],
                          [False] * len(c["records"]), None)
    _debuts, fenetres, occ_oracle, motifs = _schedule_gateway_with_motifs(jobs, c["options"])
    assert fenetres.count("rx1") == 0, "une RX1 inéligible a été émise"
    assert fenetres.count("rx2") > 0, "RX1 inéligible : RX2 aurait dû être examinée et émise"
    assert tuple(occ) == tuple(occ_oracle), "parité sur le report RX1 → RX2"
    assert not [m for m in motifs if m in MOTIFS_CAPACITE], (
        f"motif de capacité alors que RX2 pouvait porter la trame")


def test_rx1_manquee_pour_occupation_mais_rx2_ineligible_ne_replie_pas():
    """T-C-10 : RX2 inéligible n'est pas davantage demandée (R-N2).

    Le cas se présente quand RX1 est perdue pour cause d'occupation **et** que RX2 ne peut pas
    porter la trame : aucune descente n'est émise, et l'émetteur n'est pas réservé pour autant.
    """
    c = _course("EU868", CHARGE_CONFORME)
    # RX1 éligible (51), RX2 inéligible (39 < 40) : le repli est impossible.
    radios_n = tuple(dataclasses.replace(r, rx1_max_payload=51, rx2_max_payload=39)
                     for r in c["radios"])
    limites = tuple(DeviceLimits(51, 39) for _ in c["radios"])
    _, occ = plan_native_v3(c["records"], c["radios"], c["options"], c["rx2"], limites)
    jobs = _downlink_jobs(c["records"], radios_n, c["options"],
                          [False] * len(c["records"]), None)
    _debuts, fenetres, occ_oracle, motifs = _schedule_gateway_with_motifs(jobs, c["options"])
    assert fenetres.count("rx2") == 0, "un repli a été émis alors que RX2 ne pouvait pas porter"
    assert tuple(occ) == tuple(occ_oracle), "parité sur le refus de repli"
    # Et la cause est bien la capacité, pas l'occupation : les deux familles sont disjointes.
    assert not set(MOTIFS_CAPACITE) & set(MOTIFS_TEMPOREL)
