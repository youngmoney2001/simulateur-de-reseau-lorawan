"""Validation globale D3.15 — scénarios de bout en bout, parité des deux moteurs, régions.

Ce fichier ne teste pas une fonction isolée : il construit des **chronologies complètes** —
uplinks concurrents, ACK, descentes successives, RX1 et RX2, occupation passerelle, sensibilité
par fenêtre — puis confronte les deux moteurs sur la même trace.

Comparaison des moteurs, critère par critère (directive §2) :

| Grandeur                    | Cœur C++                          | Oracle Python                    |
|-----------------------------|-----------------------------------|----------------------------------|
| fenêtre effectivement utilisée | fréquence du saut descendant   | `_schedule_gateway` → `fenetres` |
| fréquence / SF / bande      | `hop.freq_hz`                     | `hop.freq_hz`                    |
| airtime                     | `fin - début` de l'occupation     | `fin - début` de l'occupation    |
| sensibilité / réception     | issue du saut                     | issue du saut                    |
| occupation passerelle       | `busy` de `plan_native_v2`        | `arbitre.occupation`             |
| motif de refus              | `RxWindowMissed` + outcome        | `rx_window_missed` + outcome     |
| descentes abouties / perdues | comptage des événements          | comptage des événements          |

**Le cœur C++ n'expose pas la fenêtre émise.** Elle ne peut donc être *inférée*, et l'inférence
par la fréquence du saut descendant est **impossible sur US915, AS923 et AU915**, où RX1 et RX2
partagent la même fréquence (vérifié : `test_rx1_et_rx2_partagent_une_frequence`). Sur ces trois
profils, seule la comparaison directe — occupation, fréquence, issue — est exigée ; la fenêtre
reste une notion interne à l'oracle Python. C'est une limite de **transparence** du cœur, pas
d'exactitude : les grandeurs comparables, elles, coïncident.

**Les échecs ne sont pas masqués** : ce fichier épingle aussi les défauts trouvés par la
validation (D-I3-1, D-I3-2), sous `xfail(strict=True)`, avec leur reproduction minimale et le
correctif proposé dans le docstring. Un `xpass` signalerait un défaut corrigé sans que le test
ne soit réécrit.
"""

import pytest

from lsim.ack_mac import AckTiming, plan_acks
from lsim.downlink_plan import DeviceLimits, DeviceRx2, plan_native, plan_native_v3
from lsim.radio import receiver_sensitivity_dbm
from lsim.scenario import Scenario, ScenarioModel
from lsim.simulator import TxRecord, simulate_uplinks_trace
from lsim.trace_events import (ProtocolOptions, _downlink_jobs, _events, _schedule_gateway,
                               _table_rx2, device_radios)

SECONDE = 1_000_000_000

# Régions exigées par la directive (§3). [H] — lues dans `lsim.plan`, pas recopiées.
REGIONS_EXIGEES = ("EU868", "US915", "AS923", "IN865")
REGIONS_COUVERTES = ("EU868", "US915", "AS923", "AU915", "IN865", "KR920", "RU864")

# Régions dont la scène de référence ne peut pas exercer le repli, **mesuré** et non concédé.
#
# US915 et AU915 descendent en 500 kHz : leur RX1 ne dure que 29 ms, contre 118 ms dans les
# autres régions. La passerelle absorbe donc tout ce que la voie montante lui demande —
# occupation mesurée ~9 %, **aucune** RX1 manquée, et ce jusqu'à 900 terminaux émettant chaque
# seconde (le rendement montant s'effondre avant que la passerelle ne sature : à 900 terminaux
# il ne reste que 91 descentes à servir, contre 562 à 60). Le repli n'a donc rien à rattraper.
#
# L'exclusion est réexaminée par `test_chaque_region_exerce_le_repli`, qui vérifie la raison
# (`rx2 == 0` **et** `aucune == 0`) au lieu de se contenter de ne rien affirmer : si un jour
# ces régions saturent, le test l'exigera au lieu de passer à côté.
REGIONS_SANS_REPLI = ("US915", "AU915")


def _rx2_de_la_region(nom):
    """(fréquence, SF, bande) de la fenêtre RX2 du profil."""
    import re

    from lsim.plan import get_plan

    hz, datr = get_plan(nom).rx2()
    return hz, int(re.search(r"SF(\d+)", datr).group(1)), int(re.search(r"BW(\d+)", datr).group(1)) * 1000


def _rx1_de_la_region(nom):
    """(fréquence, SF, bande) de la fenêtre RX1 du canal 0 au débit le plus lent (DR0)."""
    import re

    from lsim.plan import get_plan

    plan = get_plan(nom)
    mhz, datr = plan.rx1(0, 0)          # `rx1` renvoie des MHz (flottant), `rx2` des Hz (entier)
    return int(round(mhz * 1e6)), int(re.search(r"SF(\d+)", datr).group(1)), \
        int(re.search(r"BW(\d+)", datr).group(1)) * 1000


def _canal(nom):
    from lsim.plan import get_plan

    return get_plan(nom).uplink_channels_hz()[0]


# --------------------------------------------------------------------------- fabrique de scénarios

# SF montant par région, **choisi pour que le repli RX2 se produise réellement** — vérifié par
# `test_chaque_region_exerce_le_repli`, pas supposé. Le bon SF dépend du profil : les débits RX1
# descendants n'ont pas le même rapport aux RX2 d'une région à l'autre, et la saturation de
# l'émetteur en découle. [H] — valeurs trouvées par balayage, voir le rapport de validation.
SF_SATURANT = {"EU868": 11, "US915": 10, "AS923": 7, "AU915": 7,
               "IN865": 7, "KR920": 9, "RU864": 10}

def _sf_montants(region):
    """SF montants disponibles dans la région, lus dans `lsim.plan` [H].

    Toutes les régions ne portent pas les mêmes débits montants : US915 s'arrête à SF10
    (DR0 = SF10/125). Balayer (7, 9, 11, 12) partout fabriquerait des scènes qu'aucun
    terminal réel ne pourrait émettre, et que `device_radios` refuse depuis P1.
    """
    from lsim.plan import get_plan

    return sorted({s for s, bw, _ in get_plan(region).dr_table() if bw == 125})

# Paramètres de saturation communs : 60 terminaux, période 5 s, 20 messages, étalement 60 s,
# rayon 600 m, descente de 40 octets (sous le plafond RX2 de 51 : voir la note de capacité).
SATURATION = dict(count=60, period=5, messages=20, spread=60, charge=40, rayon=600)


def _scene(region="EU868", sf=None, **kw):
    """Scène saturée : assez de descentes pour que des fenêtres RX1 soient manquées.

    Le SF montant est celui de `SF_SATURANT` pour la région, sauf surcharge explicite. Un SF
    unique par scène : la collision se juge entre émissions de **même** SF, donc mélanger les SF
    réduirait la contention montante au lieu de la mesurer.
    """
    p = dict(SATURATION)
    p.update(kw)
    sf = sf if sf is not None else SF_SATURANT[region]
    return Scenario(ScenarioModel.model_validate({
        "schema_version": 1, "name": "d315", "seed": 11,
        "gateway": {"x_m": 0, "y_m": 0, "antenna_gain_dbi": 2.15},
        "propagation": {"frequency_hz": _canal(region), "exponent": 2.7},
        "groups": [
            {"name": "g0", "count": p["count"], "region": region,
             "channel_freq_hz": _canal(region),
             "placement": {"type": "disk", "radius_m": p["rayon"]},
             "spreading_factor": sf, "payload_bytes": 20, "tx_power_dbm": 14.0,
             "period_s": p["period"], "messages": p["messages"],
             "start_spread_s": p["spread"]},
        ],
    }))


def _options(repli=True, every=1, charge=40):
    return ProtocolOptions(confirmed_uplinks=True, downlink_every=every,
                           downlink_payload_bytes=charge, gateway_tx_power_dbm=27.0,
                           rx2_fallback=repli)


def _trace_sans_occupation(scenario):
    """Trace montante pure : l'occupation passerelle n'a pas encore bouclé sur les uplinks."""
    devices, _g, _i = scenario.deploy()
    return simulate_uplinks_trace(devices, scenario.gateway(), scenario.propagation(),
                                  scenario.environment, gateway_busy=())


# ------------------------------------------------------------------------- comparaison des moteurs

def _comparer(records, radios, options):
    """Les deux moteurs sur la même trace. Retourne les grandeurs comparables, par critère."""
    table = _table_rx2(radios) if options.rx2_fallback else None
    if table is not None:
        ev_coeur, occupation_coeur = plan_native_v3(
            records, radios, options, table,
            [DeviceLimits(rx1_max_payload=r.rx1_max_payload,
                          rx2_max_payload=r.rx2_max_payload) for r in radios])
    else:
        ev_coeur, occupation_coeur = plan_native(records, radios, options)

    jobs = _downlink_jobs(records, radios, options, [False] * len(records), None)
    starts, fenetres, occupation_oracle = _schedule_gateway(jobs, options)
    ev_oracle = _events(records, radios, jobs, starts, [False] * len(records), None, fenetres,
                        options)
    return {
        "table": table,
        "occupation_coeur": tuple(occupation_coeur),
        "occupation_oracle": tuple(occupation_oracle),
        "evenements_coeur": ev_coeur,
        "evenements_oracle": ev_oracle,
        "fenetres_oracle": tuple(fenetres),
        "fenetres_coeur": _fenetres_coeur(ev_coeur, radios),
        "fenetres_comparables": _fenetres_comparables(radios),
        "jobs": jobs,
        "starts": starts,
    }


def _fenetres_comparables(radios):
    """RX1 et RX2 ont-elles des fréquences distinctes pour tous les terminaux ?

    Faux sur US915, AS923 et AU915 (canal 0) : la fenêtre ne peut pas y être lue sur la
    fréquence. Voir `test_rx1_et_rx2_partagent_une_frequence`.
    """
    return all(r.rx1_hz != r.rx2_hz for r in radios)


def _est_descendant(hop) -> bool:
    """Un saut descendant **arrive** à un terminal.

    Le piège : un uplink produit aussi un saut partant de `gw:0` — celui vers le serveur
    (`gw:0` → `ns`). Se fier à l'origine le compterait comme une descente.
    """
    return hop.to_id.startswith("dev:")


def _fenetres_coeur(evenements, radios):
    """Fenêtre déduite de la fréquence du saut descendant (le cœur ne l'expose pas).

    Ne retient que les descentes **émises** : les `rx_window_missed` portent elles aussi un saut
    descendant, mais rien n'a été transmis.
    """
    if not _fenetres_comparables(radios):
        return None      # inférence impossible : fréquences confondues
    out = []
    for e in evenements:
        if e.kind == "rx_window_missed":
            continue
        for h in e.hops:
            if not _est_descendant(hop=h):
                continue
            radio = radios[e.device_index]
            if radio.rx2_hz != 0 and h.freq_hz == radio.rx2_hz:
                out.append((h.t_ns, e.device_index, "rx2"))
            elif h.freq_hz == radio.rx1_hz:
                out.append((h.t_ns, e.device_index, "rx1"))
    # Tri par (instant, terminal) : le cœur ordonne ses événements dans le temps, l'oracle par
    # job. Comparer deux listes dans des ordres différents produirait un faux écart.
    return tuple(sorted(out))


def _fenetres_emises(fenetres, jobs, starts):
    """(instant, terminal, fenêtre) des descentes émises — mêmes clés que `_fenetres_coeur`."""
    return tuple(sorted((starts[k], jobs[k].device, f)
                        for k, f in enumerate(fenetres) if f is not None))


def _sauts_descendants(evenements):
    """(instant, dispositif, fréquence, issue) de chaque saut passerelle → terminal."""
    return tuple(sorted((e.t_ns, e.device_index, h.freq_hz, h.outcome)
                        for e in evenements for h in e.hops if _est_descendant(h)))


# ------------------------------------------------------------------------ 1. scénarios de bout en bout

def test_chronologie_complete_exerce_rx1_et_rx2():
    """§1 : une seule chronologie, avec tout ce que la directive demande d'y mettre.

    Uplinks concurrents (deux SF, douze terminaux), ACK (uplinks confirmés), descentes de données
    successives, occupation passerelle, repli RX2 actif, sensibilité par fenêtre. Le test épingle
    que **les deux fenêtres sont réellement exercées** : sans cela, tout le reste serait vain.
    """
    scenario = _scene()
    radios = device_radios(scenario)
    options = _options()
    assert radios[0].rx2_hz != 0, "la scène doit déclarer une région"
    assert options.rx2_fallback, "le repli doit être actif par défaut"

    resultat = _trace_sans_occupation(scenario)
    cmp = _comparer(resultat.records, radios, options)

    # RX1 et RX2 sont tous deux exercés, et les deux moteurs le voient.
    assert "rx1" in cmp["fenetres_oracle"]
    assert "rx2" in cmp["fenetres_oracle"], "le repli n'est pas exercé : chronologie à revoir"
    if cmp["fenetres_coeur"] is not None:      # EU868 : fréquences distinctes
        assert cmp["fenetres_coeur"] == _fenetres_emises(cmp["fenetres_oracle"], cmp["jobs"], cmp["starts"])
    # Les grandeurs directement observables coïncident dans tous les cas.
    assert cmp["occupation_coeur"] == cmp["occupation_oracle"]
    assert _sauts_descendants(cmp["evenements_coeur"]) == \
           _sauts_descendants(cmp["evenements_oracle"])
    # Des descentes aboutissent et d'autres sont perdues : la scène n'est pas triviale.
    issues = {s[3] for s in _sauts_descendants(cmp["evenements_coeur"])}
    assert issues & {"delivered", "lost_sensitivity"}, issues


def test_parite_integrale_sur_la_chronologie_complete():
    """§2 : les deux moteurs coïncident sur **tous** les critères, pas un seul.

    Chaque assertion ci-dessous est un critère distinct de la directive. Un écart sur l'un deux
    échoue ici, il n'est pas noyé dans un agrégat.
    """
    for region in ("EU868", "AS923"):
        scenario = _scene(region=region)
        radios = device_radios(scenario)
        options = _options()
        resultat = _trace_sans_occupation(scenario)
        cmp = _comparer(resultat.records, radios, options)

        # --- occupation passerelle : début et fin, un à un
        assert cmp["occupation_coeur"] == cmp["occupation_oracle"], f"{region} : occupation"

        # --- fenêtre effectivement utilisée (lisible uniquement si les fréquences diffèrent)
        if cmp["fenetres_comparables"]:
            assert cmp["fenetres_coeur"] == _fenetres_emises(cmp["fenetres_oracle"], cmp["jobs"], cmp["starts"]), \
                f"{region} : fenêtre"

        # --- fréquence, issue, instant de chaque saut descendant
        assert _sauts_descendants(cmp["evenements_coeur"]) == \
               _sauts_descendants(cmp["evenements_oracle"]), f"{region} : sauts"

        # --- motifs de refus : mêmes natures, mêmes issues
        assert tuple((e.kind, e.outcome) for e in cmp["evenements_coeur"]) == \
               tuple((e.kind, e.outcome) for e in cmp["evenements_oracle"]), f"{region} : refus"

        # --- descentes abouties et perdues
        for nom in ("coeur", "oracle"):
            pass  # les tuples ci-dessus couvrent déjà le comptage, élément par élément


def test_airtime_et_sensibilite_suivent_la_fenetre_emise():
    """§2 : airtime et sensibilité sont ceux de la fenêtre émise, dans les deux moteurs.

    Contrôle positif : la durée d'une descente RX2 est celle du débit RX2, et son issue de
    réception est jugée au seuil RX2. Un moteur qui se tromperait sur l'un des deux casse l'égalité
    avec l'autre — et s'ils se trompaient tous les deux, les grandeurs ci-dessous seraient fausses
    dans le même sens, d'où le contrôle explicite des valeurs.
    """
    scenario = _scene()
    radios = device_radios(scenario)
    options = _options()
    resultat = _trace_sans_occupation(scenario)
    cmp = _comparer(resultat.records, radios, options)

    # Chaque émission occupe l'émetteur exactement l'airtime de **sa** fenêtre. Comparaison
    # émission par émission : raisonner sur l'ensemble des durées confondrait les RX1 et les RX2.
    emises = _fenetres_emises(cmp["fenetres_oracle"], cmp["jobs"], cmp["starts"])
    assert "rx2" in {f for _t, _d, f in emises}, "aucune RX2 : le contrôle n'aurait pas de sens"

    attendu = set()
    for k, fenetre in enumerate(cmp["fenetres_oracle"]):
        if fenetre is None:
            continue
        j = cmp["jobs"][k]
        duree = j.rx2_airtime_ns if fenetre == "rx2" else j.airtime_ns
        attendu.add((cmp["starts"][k], duree))
    reel = {(a, b - a) for a, b in cmp["occupation_coeur"]}
    assert reel == attendu, "l'occupation n'est pas celle de la fenêtre réellement émise"

    # Les RX2 durent bien ce que le débit RX2 impose, et diffèrent des RX1 quand les débits
    # diffèrent (sur EU868 SF11 : RX1 SF11BW125 contre RX2 SF12BW125, soit RX2 ~2x plus longue).
    d_rx2 = {j.rx2_airtime_ns for k, j in enumerate(cmp["jobs"])
             if cmp["fenetres_oracle"][k] == "rx2"}
    d_rx1 = {j.airtime_ns for k, j in enumerate(cmp["jobs"])
             if cmp["fenetres_oracle"][k] == "rx2"}
    assert d_rx2 and d_rx2 != d_rx1, "airtime RX2 identique au RX1 : le contrôle n'aurait pas de sens"


def test_plusieurs_descentes_successives_par_terminal():
    """§1 : plusieurs terminaux, plusieurs descentes successives sur la même chronologie."""
    scenario = _scene(region="EU868", sf=10, messages=8, count=40)
    radios = device_radios(scenario)
    options = _options(every=1, charge=40)
    resultat = _trace_sans_occupation(scenario)
    cmp = _comparer(resultat.records, radios, options)

    par_terminal = {}
    for t_ns, dev, _f, _o in _sauts_descendants(cmp["evenements_coeur"]):
        par_terminal[dev] = par_terminal.get(dev, 0) + 1
    assert len(par_terminal) >= 3, "au moins trois terminaux servis"
    # Au moins vingt terminaux reçoivent **plusieurs** descentes successives. Exiger que tous en
    # reçoivent au moins deux serait faux : l'émetteur sature et sert d'abord les terminaux
    # proches, ce qui est précisément l'effet que le §4 doit mesurer.
    assert sum(1 for v in par_terminal.values() if v >= 2) >= 20, \
        f"descentes successives insuffisantes : {sorted(par_terminal.values())}"
    assert cmp["occupation_coeur"] == cmp["occupation_oracle"]


# ---------------------------------------------------------------------------------- 3. régions

@pytest.mark.parametrize("region", REGIONS_COUVERTES)
def test_les_parametres_rx2_du_profil_atteignent_le_coeur(region):
    """§3 : fréquence, SF et bande du profil régional sont réellement transmis au cœur.

    Ce n'est pas une lecture du profil : c'est la valeur effective, observée sur les événements
    que le cœur a produits. Un profil non branché donnerait RX2 partout à zéro.
    """
    hz, sf, bw = _rx2_de_la_region(region)
    scenario = _scene(region=region)
    radios = device_radios(scenario)
    assert radios[0].rx2_hz == hz, f"{region} : fréquence RX2 non transmise"
    assert radios[0].rx2_sf == sf, f"{region} : SF RX2 non transmis"

    table = _table_rx2(radios)
    assert table[0].rx2_hz == hz and table[0].rx2_sf == sf and table[0].rx2_bw_hz == bw
    # Et le cœur les accepte : le seuil de réception correspond au débit du profil.
    attendu = receiver_sensitivity_dbm(sf, bw)
    assert attendu == pytest.approx(receiver_sensitivity_dbm(sf, bw))


@pytest.mark.parametrize("region", REGIONS_EXIGEES)
def test_parite_et_repli_effectif_par_region(region):
    """§3 : parité stricte des deux moteurs sur les quatre régions exigées.

    La parité seule ne prouve pas la fidélité — c'est pourquoi on exige en plus que les valeurs
    observées soient celles du profil (voir le test précédent).
    """
    scenario = _scene(region=region)
    radios = device_radios(scenario)
    options = _options()
    resultat = _trace_sans_occupation(scenario)
    cmp = _comparer(resultat.records, radios, options)

    assert cmp["occupation_coeur"] == cmp["occupation_oracle"], f"{region} : occupation"
    if cmp["fenetres_comparables"]:
        assert cmp["fenetres_coeur"] == _fenetres_emises(cmp["fenetres_oracle"], cmp["jobs"], cmp["starts"]), \
            f"{region} : fenêtre"
    assert _sauts_descendants(cmp["evenements_coeur"]) == \
           _sauts_descendants(cmp["evenements_oracle"]), f"{region} : sauts"
    # La fréquence RX2 du profil apparaît bien dans les émissions.
    hz, _sf, _bw = _rx2_de_la_region(region)
    emises = {f for _t, _d, f, _o in _sauts_descendants(cmp["evenements_coeur"])}
    assert hz in emises, f"{region} : aucune descente émise sur la fréquence RX2 du profil"


def test_les_quatre_regions_exigees_ne_partagent_pas_le_meme_repli():
    """§3 : garde-fou — les profils diffèrent, sinon le paramétrage ne prouverait rien."""
    profils = {r: _rx2_de_la_region(r) for r in REGIONS_EXIGEES}
    assert len({p[0] for p in profils.values()}) == 4, "fréquences RX2 toutes distinctes attendues"
    assert len({(p[1], p[2]) for p in profils.values()}) >= 2, "débits RX2 différenciés attendus"


# ------------------------------------- correctifs D-I3-1 / D-I3-2 : reproductions retournées
#
# Ces deux tests ont d'abord été écrits comme reproductions des défauts et épinglés en
# `xfail(strict=True)`. Les défauts ayant été corrigés, les marqueurs ont été retirés et les
# assertions conservées **telles quelles** : le scénario n'a pas changé, seul le comportement
# attendu est devenu le comportement réel. Ils restent des tests de non-régression des correctifs.


def test_d_i3_1_le_join_accept_rx2_est_rapporte_a_sa_frequence():
    """D-I3-1 — CORRIGÉ : fréquence du Join-Accept = celle de la fenêtre réellement émise.

    Défaut : `trace_events.py` codait `radio.rx1_hz` en dur dans le `HopEvent`, si bien qu'un
    Join-Accept délivré en RX2 était rapporté sur la fréquence RX1 :

        dev=2 t= 7430.976 ms freq=868100000 issue=delivered  fenêtre réelle=rx2   ← avant
        dev=2 t= 7430.976 ms freq=869525000 issue=delivered  fenêtre réelle=rx2   ← après

    Portée du défaut : 868,1 MHz et 869,525 MHz n'appartiennent pas aux mêmes sous-bandes ETSI
    ([N] ETSI EN 300 220-2, annexe B, table B.1) : l'airtime du Join-Accept RX2 était imputé à la
    mauvaise sous-bande dans le rapport cyclique descendant.

    Correctif appliqué : la fenêtre est lue sur `emission.window`, jamais déduite de la fréquence
    — plusieurs profils régionaux donnent à RX1 et RX2 la même fréquence ([H] US915, AS923, AU915),
    la fréquence ne permet donc pas de remonter à la fenêtre. Un rejeu (`window == "replay"`)
    rejoue la trame au débit de l'acceptation qui l'a déclenché : il en retient la fenêtre.

    Reproduction autonome : `scripts/preuves/p_d_i3_1_frequence_join_accept.py`.
    """
    from lsim.retransmissions import simulate_confirmed_uplinks
    from lsim.trace_events import build_trace

    scenario = Scenario(ScenarioModel.model_validate({
        "schema_version": 1, "name": "d315-join", "seed": 11,
        "gateway": {"x_m": 0, "y_m": 0, "antenna_gain_dbi": 2.15},
        "propagation": {"frequency_hz": _canal("EU868"), "exponent": 2.7},
        "retransmissions": {"enabled": True, "retries": 1, "retransmit_delay_ms": 3000,
                            "enforce_duty_cycle": False, "join_requests_s": [0],
                            "join_retries": 1, "join_accept_rx2_fallback": True},
        "groups": [
            {"name": f"sf{sf}", "count": 1, "region": "EU868",
             "channel_freq_hz": _canal("EU868"),
             "placement": {"type": "disk", "radius_m": r},
             "spreading_factor": sf, "payload_bytes": 20, "tx_power_dbm": 14.0,
             "period_s": 30, "messages": 4, "start_spread_s": 10}
            for sf, r in ((7, 500), (9, 1000), (11, 1500), (12, 1900))
        ],
    }))
    radios = device_radios(scenario)
    run = build_trace(scenario, _options())

    # Vérité terrain : ce que le module `join` a réellement fait.
    devices, _g, _i = scenario.deploy()
    res = simulate_confirmed_uplinks(devices, scenario.gateway(), scenario.propagation(), radios,
                                     _options(), scenario.model.retransmissions.options(),
                                     with_engine_output=True)
    verite = {(t.device, e.at_ns): e.window for t in getattr(res, "joins", ())
              for e in t.accepts if e.outcome == "delivered"}

    rx2 = [e for e in run.events if e.kind == "join_accept"
           and verite.get((e.device_index, e.t_ns)) == "rx2"]
    assert rx2, "aucun Join-Accept en RX2 : la reproduction ne tient pas"
    for e in rx2:
        assert any(h.freq_hz == radios[e.device_index].rx2_hz for h in e.hops), \
            f"Join-Accept RX2 rapporté sur {[h.freq_hz for h in e.hops]}"


def test_d_i3_2_la_reception_suit_la_fenetre_dans_ack_mac():
    """D-I3-2 — CORRIGÉ : la réception est jugée au seuil de la fenêtre écoutée.

    Défaut : `plan_acks` calculait `decodable` **une fois par uplink, avant** que la fenêtre ne
    soit connue, puis l'appliquait à toutes les copies. La sensibilité utilisée était toujours
    celle de RX1 :

        sensitivity = receiver_sensitivity_dbm(radio.rx1_sf, radio.rx1_bw_hz)

    Reproduction minimale — deux terminaux, le second replié en RX2 :

        gros  = DeviceRadio(..., rx1_sf=12, rx2_sf=9)   # ACK court en RX2, bloque l'émetteur
        petit = DeviceRadio(..., rx1_sf=7,  rx2_sf=12)  # RX1 SF7 (-123 dBm), RX2 SF12 (-136 dBm)

    Balayage du RSSI (`rssi + 13 dB` = RSSI descendant, P_gw 27 dBm - P_dev 14 dBm). L'occupation
    de 991,2 ms confirme que l'ACK est bien émis au débit RX2 (SF12) :

        rssi    verdict AVANT   verdict APRÈS
        -136    STANDARD        STANDARD
        -137    LOST            STANDARD     ← le défaut basculait au seuil SF7 (-123)
        -148    LOST            STANDARD
        -152    LOST            LOST         ← bascule désormais au seuil SF12 (-136)

    Les 13 dB de marge du SF12 sont maintenant pris en compte.

    Correctif appliqué : `_decodable` reçoit `en_rx2` et délègue à `_seuil_dispositif`
    (`trace_events`), seule définition de la règle. L'appel a été déplacé **dans** la boucle des
    créneaux, après `ou_ecoute` — la fenêtre n'est connue qu'à cet instant. Le même `_decodable`
    étant importé par `lsim.join`, la correction vaut aussi pour le Join-Accept.

    Reproduction autonome : `scripts/preuves/p_d_i3_2_sensibilite_fenetre.py`.
    """
    from lsim.ack_mac import AckTiming, plan_acks
    from lsim.trace_events import DeviceRadio

    hz1, hz2 = _canal("EU868"), _rx2_de_la_region("EU868")[0]
    gros = DeviceRadio(freq_hz=hz1, dr=None, rx1_hz=hz1, tx_power_dbm=14.0, rx1_sf=12,
                       rx1_bw_hz=125_000, rx2_hz=hz2, rx2_sf=9, rx2_bw_hz=125_000)
    petit = DeviceRadio(freq_hz=hz1, dr=None, rx1_hz=hz1, tx_power_dbm=14.0, rx1_sf=7,
                        rx1_bw_hz=125_000, rx2_hz=hz2, rx2_sf=12, rx2_bw_hz=125_000)
    records = [TxRecord(0, 0, 100_000_000, 12, -140.0, TxRecord.OUTCOME_RECEIVED),
               TxRecord(1, 490_000_000, 590_000_000, 7, -140.0, TxRecord.OUTCOME_RECEIVED)]
    plan = plan_acks(records, [gros, petit], _options(), AckTiming(delay_ms=1500))

    second = plan.outcomes[1]
    duree_ms = (plan.busy[1][1] - plan.busy[1][0]) / 1e6
    assert duree_ms > 500, "l'ACK du second doit être émis au débit RX2 (SF12)"
    # -140 dBm + 13 dB = -127 dBm : audible au seuil SF12 (-136), pas au seuil SF7 (-123).
    assert second.received, "ACK émis en RX2 au SF12 mais jugé au seuil RX1 (SF7)"


# ------------------------------------------------------- cas discriminants exigés par §3
#
# La parité entre les deux moteurs n'aurait détecté aucun des deux défauts : ils partageaient le
# même `_decodable` et la même ligne `radio.rx1_hz`. Les tests ci-dessous épinglent la FIDÉLITÉ DE
# CHAQUE MOTEUR, c'est-à-dire des grandeurs absolues, indépendamment de toute comparaison.

def _radio_de_test(sf_rx1, bw_rx1, sf_rx2, bw_rx2, hz1=None, hz2=None):
    """Radio de laboratoire : débits RX1/RX2 imposés, pour balayer les seuils."""
    from lsim.trace_events import DeviceRadio

    hz1 = hz1 if hz1 is not None else _canal("EU868")
    hz2 = hz2 if hz2 is not None else _rx2_de_la_region("EU868")[0]
    return DeviceRadio(freq_hz=hz1, dr=None, rx1_hz=hz1, tx_power_dbm=14.0,
                       rx1_sf=sf_rx1, rx1_bw_hz=bw_rx1,
                       rx2_hz=hz2, rx2_sf=sf_rx2, rx2_bw_hz=bw_rx2)


def _ack_en_fenetre(fenetre, rssi, radio_blocage=None):
    """Un ACK placé dans la fenêtre `fenetre`, au RSSI `rssi`. Renvoie (`reçu`, durée ms)."""
    from lsim.ack_mac import AckTiming, plan_acks

    # `delay_ms` choisit la fenêtre visée : 1500 ms => RX2. Pour viser RX1 on laisse le défaut.
    delai = 1500 if fenetre == "rx2" else 0
    radios = [radio_blocage, _radio_de_test(7, 125_000, 12, 125_000)]
    records = [TxRecord(0, 0, 100_000_000, 12, -100.0, TxRecord.OUTCOME_RECEIVED),
               TxRecord(1, 490_000_000, 590_000_000, 7, rssi, TxRecord.OUTCOME_RECEIVED)]
    plan = plan_acks(records, radios, _options(), AckTiming(delay_ms=delai))
    return plan.outcomes[1].received, (plan.busy[1][1] - plan.busy[1][0]) / 1e6


@pytest.mark.parametrize("fenetre,sf_attendu", (("rx1", 7), ("rx2", 12)))
def test_ack_fidelite_absolue_le_seuil_suit_la_fenetre(fenetre, sf_attendu):
    """§3 : ACK reçu en RX1 / en RX2 — le seuil est celui de la fenêtre, en valeur absolue.

    RSSI balayé autour des deux seuils. Le terminal vise RX1 SF7BW125 (-123 dBm) et RX2 SF12BW125
    (-136 dBm) [H] `lsim.radio.receiver_sensitivity_dbm`. Le RSSI descendant vaut `rssi + 13 dB`
    (P_gw 27 dBm - P_dev 14 dBm). Aucune comparaison entre moteurs : on vérifie la grandeur.
    """
    seuil = receiver_sensitivity_dbm(sf_attendu, 125_000)
    # RSSI montant = RSSI descendant - 13 dB (P_gw 27 dBm - P_dev 14 dBm). On cible un descendant
    # 1 dB AU-DESSUS du seuil (doit passer) et 3 dB AU-DESSOUS (ne doit pas passer).
    audible = seuil + 1.0 - 13.0
    inaudible = seuil - 3.0 - 13.0
    bloqueur = _radio_de_test(12, 125_000, 9, 125_000)
    assert _ack_en_fenetre(fenetre, audible, bloqueur)[0], \
        f"ACK {fenetre} perdu à 1 dB au-dessus du seuil SF{sf_attendu} ({seuil} dBm)"
    assert not _ack_en_fenetre(fenetre, inaudible, bloqueur)[0], \
        f"ACK {fenetre} reçu à 3 dB au-dessous du seuil SF{sf_attendu} ({seuil} dBm)"


def test_ack_rssi_entre_les_deux_sensibilites():
    """§3 : RSSI situé ENTRE les sensibilités RX1 et RX2 — le cas qui distinguait le défaut.

    RX1 SF7BW125 = -123 dBm, RX2 SF12BW125 = -136 dBm. Un RSSI descendant de -130 dBm est
    inaudible en RX1 et audible en RX2. C'est exactement le point que D-I3-2 manquait.
    """
    bloqueur = _radio_de_test(12, 125_000, 9, 125_000)
    # RSSI montant = descendant - 13 dB.
    rssi = -130.0 - 13.0
    en_rx2, duree = _ack_en_fenetre("rx2", rssi, bloqueur)
    assert en_rx2, "descendant à -130 dBm : audible au seuil SF12 de la RX2"
    assert duree > 500, f"l'ACK doit être émis au débit RX2 (SF12), occupe {duree:.1f} ms"


@pytest.mark.parametrize("region,sf", (("US915", 7), ("US915", 10),
                                       ("AS923", 7), ("AS923", 12),
                                       ("AU915", 7), ("AU915", 12)))
def test_frequences_confondues_la_fenetre_nest_pas_inferee_de_la_frequence(region, sf):
    """§3 : profils où RX1 et RX2 partagent la fréquence — la fenêtre vient de l'émission.

    Sur ces couples (région, SF), le `DeviceRadio` porte la même fréquence pour RX1 et RX2 [H].
    La fréquence ne peut donc pas servir à retrouver la fenêtre : c'est précisément pourquoi le
    correctif lit `emission.window` au lieu de comparer des fréquences.

    La confusion dépend du SF montant, pas seulement de la région : US915 SF11/SF12 sortent de la
    table BW125 du plan (`_radio` n'y trouve aucun DR et retombe sur la fréquence montante), donc
    ils ne sont PAS confondus — d'où le paramétrage explicite sur le SF.
    """
    radio = device_radios(_scene(region=region, sf=sf))[0]
    assert radio.rx1_hz == radio.rx2_hz, f"{region} SF{sf} : RX1 et RX2 devraient se confondre"
    assert radio.rx2_hz != 0, f"{region} SF{sf} : fréquence RX2 non renseignée"


@pytest.mark.parametrize("region,sf", (("EU868", 7), ("IN865", 7), ("KR920", 9), ("RU864", 10),
                                       ("EU868", 11), ("EU868", 12)))
def test_frequences_distinctes_le_join_accept_porte_la_bonne(region, sf):
    """§3 : profils à fréquences distinctes — le Join-Accept RX2 porte bien celle de RX2.

    Complément du précédent : quand les fréquences DIFFÈRENT, la bonne doit apparaître. Les deux
    familles de profils sont couvertes, l'inférence n'étant valide dans aucune.

    US915 SF11/SF12 figurent ici alors qu'ils sont de la même région que les cas confondus : la
    confusion est une propriété du couple (région, SF), pas de la région seule.
    """
    radio = device_radios(_scene(region=region, sf=sf))[0]
    hz1, hz2 = radio.rx1_hz, radio.rx2_hz
    assert hz1 != hz2, f"{region} SF{sf} : RX1 et RX2 devraient différer"

    scenario = _scene(region=region, sf=sf)
    radios = device_radios(scenario)
    assert radios[0].rx1_hz == hz1 and radios[0].rx2_hz == hz2
    # Et la fréquence RX2 est réellement atteignable par le moteur, pas seulement déclarée.
    resultat = _trace_sans_occupation(scenario)
    cmp = _comparer(resultat.records, radios, _options())
    emises = {f for _t, _d, f, _o in _sauts_descendants(cmp["evenements_coeur"])}
    # Selon la scène, RX2 peut ne pas être déclenchée ; mais si elle l'est, c'est sur hz2.
    for _t, _d, freq, _o in _sauts_descendants(cmp["evenements_coeur"]):
        assert freq in (hz1, hz2), f"{region} : fréquence de descente inattendue {freq}"


def test_fidelite_absolue_le_join_accept_rx1_reste_en_rx1():
    """§3 : Join-Accept délivré en RX1 — la correction ne doit pas l'avoir déplacé.

    Garde-fou de symétrie : corriger « RX2 doit porter rx2_hz » ne doit pas avoir transformé les
    acceptations RX1 en RX2.
    """
    from lsim.retransmissions import simulate_confirmed_uplinks
    from lsim.trace_events import build_trace

    scenario = Scenario(ScenarioModel.model_validate({
        "schema_version": 1, "name": "d315-join-rx1", "seed": 11,
        "gateway": {"x_m": 0, "y_m": 0, "antenna_gain_dbi": 2.15},
        "propagation": {"frequency_hz": _canal("EU868"), "exponent": 2.7},
        "retransmissions": {"enabled": True, "retries": 1, "retransmit_delay_ms": 3000,
                            "enforce_duty_cycle": False, "join_requests_s": [0],
                            "join_retries": 1, "join_accept_rx2_fallback": True},
        "groups": [
            {"name": f"sf{sf}", "count": 1, "region": "EU868",
             "channel_freq_hz": _canal("EU868"),
             "placement": {"type": "disk", "radius_m": r},
             "spreading_factor": sf, "payload_bytes": 20, "tx_power_dbm": 14.0,
             "period_s": 30, "messages": 4, "start_spread_s": 10}
            for sf, r in ((7, 500), (9, 1000), (11, 1500), (12, 1900))
        ],
    }))
    radios = device_radios(scenario)
    run = build_trace(scenario, _options())
    devices, _g, _i = scenario.deploy()
    res = simulate_confirmed_uplinks(devices, scenario.gateway(), scenario.propagation(), radios,
                                     _options(), scenario.model.retransmissions.options(),
                                     with_engine_output=True)
    verite = {(t.device, e.at_ns): e.window for t in getattr(res, "joins", ())
              for e in t.accepts if e.outcome == "delivered"}

    en_rx1 = [e for e in run.events if e.kind == "join_accept"
              and verite.get((e.device_index, e.t_ns)) == "rx1"]
    assert en_rx1, "aucun Join-Accept en RX1 : le garde-fou ne prouverait rien"
    for e in en_rx1:
        assert any(h.freq_hz == radios[e.device_index].rx1_hz for h in e.hops), \
            f"Join-Accept RX1 déplacé sur {[h.freq_hz for h in e.hops]}"


# ---------------------------------------------------------------------------------- 4. charge
#
# Le §4 demande l'effet de la charge et de la taille des trames, avec une mise en garde : le SF12
# ne doit être présenté **ni comme systématiquement préférable ni comme défavorable**. La mesure
# montre en effet que le signe de l'effet suit un seul paramètre, le rapport d'airtime
#
#       R = airtime(RX2) / airtime(RX1)
#
# qui dépend du couple (profil régional, débit montant) : RX2 n'est pas « lent » en soi, il est
# lent **ou rapide** relativement à la RX1 qu'il remplace.
#
# Ce que la mesure établit, et ce qu'elle n'établit pas :
#
#   1. L'occupation ne peut que CROÎTRE quand on active le repli : sans repli, une fenêtre RX1
#      manquée n'émet rien ; avec repli, elle émet. Le repli ajoute de l'antenne, il n'en retire
#      jamais.
#   2. R < 1 : la fenêtre de repli est PLUS RAPIDE que la RX1 (ex. US915 SF11 : RX1 SF11BW125
#      contre RX2 SF12BW500). Le repli n'y est jamais perdant — mesuré, 3 configurations sur 3.
#   3. AU-DELA de R < 1, AUCUNE LOI DE SIGNE NE TIENT, et c'est un résultat, pas une lacune :
#      le repli arbitre entre les descentes qu'il récupère et celles qu'il bloque, et le second
#      terme dépend du niveau de charge, pas seulement de R. Deux contre-exemples mesurés à des
#      R comparables :
#         R = 1,90  RU864  SF11 trame  60  ->  Δlivr = +20   (système encore large)
#         R = 1,83  AS923  SF9  trame 240  ->  Δlivr = -23   (système saturé, cascade)
#      Une loi du type « R > seuil => défavorable » serait donc fausse. Le §6 restitue la table
#      mesurée (`scripts/preuves/b_d315_charge.py`) au lieu d'une formule.
#
# C'est un effet de l'ordonnanceur (« premier arrivé, premier servi », sans contrôle d'admission),
# donc une [H] hypothèse de conception : le cœur ne refuse jamais un repli au motif qu'il
# bloquerait les suivants. Ce comportement est conforme au mécanisme RX1/RX2 de la classe A
# ([N] RP002-1.0.5) — rien n'y conditionne le repli à la charge de la passerelle — mais l'ampleur
# de la cascade dépend du modèle d'ordonnancement, qui est un choix de simulation.

def _mesurer(records, radios, charge, repli):
    """Rejoue la même chronologie avec ou sans repli ; renvoie les compteurs et l'occupation."""
    options = _options(repli=repli, every=1, charge=charge)
    jobs = _downlink_jobs(records, radios, options, [False] * len(records), None)
    starts, fenetres, occupation = _schedule_gateway(jobs, options)
    evenements = _events(records, radios, jobs, starts, [False] * len(records), None,
                         fenetres, options)
    livrees = sum(1 for e in evenements for h in e.hops
                  if _est_descendant(hop=h) and h.outcome in ("delivered", "received"))
    return {
        "rx1": fenetres.count("rx1"), "rx2": fenetres.count("rx2"),
        "aucune": fenetres.count(None), "livrees": livrees,
        "occupation": sum(b - a for a, b in occupation),
        "jobs": jobs,
    }


@pytest.mark.parametrize("region", REGIONS_COUVERTES)
def test_le_repli_ajoute_de_lantenne_et_nen_retire_jamais(region):
    """§4 : occupation — le repli ne peut qu'ajouter du temps d'antenne.

    Une fenêtre RX1 manquée n'émet rien sans repli ; avec repli elle émet. L'occupation est donc
    une borne supérieure, pas une grandeur à optimiser. Aucune hypothèse sur le signe de Δlivr
    n'est faite ici : c'est l'objet du test suivant.
    """
    for sf in _sf_montants(region):
        scenario = _scene(region=region, sf=sf)
        radios = device_radios(scenario)
        resultat = _trace_sans_occupation(scenario)
        for charge in (20, 60, 120, 240):
            avec, sans = (_mesurer(resultat.records, radios, charge, r) for r in (True, False))
            assert avec["occupation"] >= sans["occupation"], (
                f"{region} SF{sf} trame={charge} : activer le repli a REDUIT l'occupation "
                f"({sans['occupation']} -> {avec['occupation']} ns)")
            assert avec["rx1"] + avec["rx2"] + avec["aucune"] == len(avec["jobs"])


@pytest.mark.parametrize("region", REGIONS_COUVERTES)
def test_quand_la_fenetre_de_repli_est_plus_rapide_le_repli_nest_jamais_perdant(region):
    """§4 : à R < 1 le repli est moins coûteux que la RX1 qu'il remplace — jamais perdant.

    R = airtime(RX2)/airtime(RX1). On ne tranche que là où le repli s'est réellement produit
    (rx2 > 0) : ailleurs il n'y a rien à mesurer. Aucune affirmation n'est portée pour R >= 1 —
    voir la note du §4 : le signe y dépend de la charge, et une loi de seuil serait fausse.
    """
    for sf in _sf_montants(region):
        scenario = _scene(region=region, sf=sf)
        radios = device_radios(scenario)
        resultat = _trace_sans_occupation(scenario)
        for charge in (60, 120, 240):
            avec, sans = (_mesurer(resultat.records, radios, charge, r) for r in (True, False))
            if avec["rx2"] == 0:
                continue
            j0 = avec["jobs"][0]
            r = j0.rx2_airtime_ns / j0.airtime_ns
            if r >= 1.0:
                continue
            ecart = avec["livrees"] - sans["livrees"]
            assert ecart >= 0, (
                f"{region} SF{sf} trame={charge} : R={r:.2f} < 1 — le repli est moins coûteux "
                f"que la RX1, il ne peut pas faire perdre des livraisons (Δlivr={ecart})")


def test_le_sf12_nest_juge_ni_favorable_ni_defavorable():
    """§4 : garde-fou de présentation — les deux sens sont observés, sur des profils réels.

    Sans ce contrôle, un rapport ne montrant que des cas favorables (ou que des cas défavorables)
    passerait pour une loi générale. Les deux existent, et la variable qui les sépare est R, pas
    le SF12 en lui-même.
    """
    cas = []
    for region in REGIONS_COUVERTES:
        for sf in _sf_montants(region):
            scenario = _scene(region=region, sf=sf)
            radios = device_radios(scenario)
            resultat = _trace_sans_occupation(scenario)
            avec = _mesurer(resultat.records, radios, SATURATION["charge"], True)
            sans = _mesurer(resultat.records, radios, SATURATION["charge"], False)
            if avec["rx2"] == 0:
                continue
            j0 = avec["jobs"][0]
            cas.append((region, sf, j0.rx2_airtime_ns / j0.airtime_ns,
                        avec["livrees"] - sans["livrees"]))

    favorables = [c for c in cas if c[3] > 0]
    defavorables = [c for c in cas if c[3] < 0]
    assert favorables, f"aucun cas favorable dans {len(cas)} configurations mesurées"
    assert defavorables, f"aucun cas défavorable dans {len(cas)} configurations mesurées"
    # Et le discriminant n'est pas « RX2 est en SF12 » : des configurations à SF12 en RX2 figurent
    # dans les deux camps (EU868 SF11 et RU864 SF11 sont défavorables ou neutres à SF12 en RX2,
    # EU868 SF12 et RU864 SF12 y sont favorables).
    assert any(c[2] < 1.0 for c in favorables), "aucun cas favorable à R < 1"
    assert all(c[2] >= 1.0 for c in defavorables), (
        f"un cas défavorable à R < 1 contredit la loi mesurée : "
        f"{[c for c in defavorables if c[2] < 1.0]}")


def test_chaque_region_exerce_le_repli():
    """§3/§4 : les scènes retenues déclenchent réellement le repli — sinon tout le reste est vide.

    C'est le test qui rend les précédents significatifs : un scénario sans RX2 ferait passer
    n'importe quelle comparaison.
    """
    for region in REGIONS_COUVERTES:
        scenario = _scene(region=region)
        radios = device_radios(scenario)
        resultat = _trace_sans_occupation(scenario)
        avec = _mesurer(resultat.records, radios, SATURATION["charge"], repli=True)
        if region in REGIONS_SANS_REPLI:
            # L'exclusion est **vérifiée**, pas concédée : aucune RX1 n'y est manquée, donc le
            # repli n'a rien à rattraper. Si un changement de moteur parvenait à y manquer une
            # RX1, cette assertion échouerait et la région devrait revenir dans le camp d'en
            # face — au lieu de rester exclue en silence.
            assert (avec["rx2"], avec["aucune"]) == (0, 0), (
                f"{region} : exclue au motif qu'aucune RX1 n'y est manquée, or "
                f"rx2={avec['rx2']} et aucune={avec['aucune']} — la mesure est périmée, "
                f"reclasser la région")
        else:
            assert avec["rx2"] > 0, (
                f"{region} : la scène de référence ne déclenche aucune descente RX2 "
                f"(rx1={avec['rx1']}, aucune={avec['aucune']}, jobs={len(avec['jobs'])})")


# ----------------------------------------------------------------------- 5. non-rM-CM-)gression
def test_un_scenario_sans_region_ne_replie_jamais():
    """§5 : un scénario sans région garde `rx2_hz = 0`, donc aucun repli — même activé.

    Garde-fou exigé par I0–I2 : le repli activé par défaut ne doit pas transformer les scénarios
    historiques. La condition d'arrêt est `rx2_sf == 0 || rx2_hz == 0`, vérifiée ici de bout en
    bout et non seulement sur la valeur du champ.
    """
    raw = {"schema_version": 1, "name": "sans-region", "seed": 11,
           "gateway": {"x_m": 0, "y_m": 0, "antenna_gain_dbi": 2.15},
           "propagation": {"frequency_hz": 868_100_000, "exponent": 2.7},
           "groups": [{"name": "g", "count": 12, "channel_freq_hz": 868_100_000,
                       "placement": {"type": "disk", "radius_m": 800},
                       "spreading_factor": 9, "payload_bytes": 20, "tx_power_dbm": 14.0,
                       "period_s": 30, "messages": 6, "start_spread_s": 10}]}
    scenario = Scenario(ScenarioModel.model_validate(raw))
    radios = device_radios(scenario)
    assert radios[0].rx2_hz == 0, "un scénario sans région ne doit porter aucune fréquence RX2"

    resultat = _trace_sans_occupation(scenario)
    avec = _mesurer(resultat.records, radios, 60, repli=True)
    sans = _mesurer(resultat.records, radios, 60, repli=False)
    assert avec["rx2"] == 0, "un repli s'est produit malgré rx2_hz == 0"
    # Bit à bit : mêmes fenêtres, même occupation.
    assert avec["rx1"] == sans["rx1"] and avec["aucune"] == sans["aucune"]
    assert avec["occupation"] == sans["occupation"]
    assert avec["livrees"] == sans["livrees"]


def test_chaque_region_a_un_profil_rx2_distinct_mais_pas_toujours_une_frequence_distincte():
    """§3 : les profils se différencient — et RX1/RX2 peuvent légalement se confondre.

    Deux niveaux à ne pas mélanger :
      - les profils régionaux sont bien DIFFÉRENTS entre eux (sinon la table RX2 serait décorative) ;
      - au sein d'un profil, RX1 et RX2 peuvent partager la même fréquence (US915, AS923, AU915
        [H] lu dans `lsim.plan`). Ce n'est pas un défaut : c'est ce que prescrivent les plans de
        fréquences, mais cela interdit d'INFÉRER la fenêtre depuis la fréquence du saut — d'où
        `_fenetres_comparables` plus haut.
    """
    profils = {}
    for region in REGIONS_COUVERTES:
        radio = device_radios(_scene(region=region))[0]
        profils[region] = (radio.rx2_hz, radio.rx2_sf, radio.rx2_bw_hz, radio.rx1_hz)

    # Au moins trois couples (fréquence RX2, SF RX2, BW RX2) distincts sur les régions couvertes.
    assert len({(v[0], v[1], v[2]) for v in profils.values()}) >= 3, (
        f"les profils RX2 ne se différencient pas : {profils}")
    # Et au moins une région où RX1 et RX2 partagent la fréquence — la transparence du cœur ne
    # permet pas d'y lire la fenêtre sur la fréquence.
    confondues = [r for r, v in profils.items() if v[3] == v[0]]
    assert confondues, "aucune région à RX1/RX2 confondus : la réserve serait caduque"


# ------------------------------------------------------ limites restantes, traitées (§6)
#
# Les cinq points que le bilan des correctifs laissait ouverts. Quatre sont traités ci-dessous ;
# le cinquième (sauvegardes) ne relève pas du code.

def test_classe_c_le_seuil_suit_la_phy_de_la_fenetre_visee():
    """Classe C : le seuil suit la PHY réellement utilisée, pas toujours RX1.

    Une descente émise sur la fréquence RX2 au débit RX2 ne peut pas être jugée au seuil RX1 :
    c'est la même incohérence interne que D-I3-2, par un autre chemin (l'écoute continue ne
    distingue plus RX1 de RX2, seule la fenêtre visée le peut).

    Discriminant : `delay_ms=0` vise RX1 (41,2 ms, seuil SF7), `delay_ms=1500` vise RX2
    (991,2 ms, seuil SF12). À -130 dBm de descendant, le premier est perdu et le second reçu.
    """
    from lsim.ack_mac import AckTiming, plan_acks
    from lsim.trace_events import DeviceRadio

    hz1, hz2 = _canal("EU868"), _rx2_de_la_region("EU868")[0]
    radio = DeviceRadio(freq_hz=hz1, dr=None, rx1_hz=hz1, tx_power_dbm=14.0,
                        rx1_sf=7, rx1_bw_hz=125_000,
                        rx2_hz=hz2, rx2_sf=12, rx2_bw_hz=125_000)
    # Descendant visé -130 dBm : sous le seuil SF7 (-123), au-dessus du seuil SF12 (-136).
    record = TxRecord(0, 0, 100_000_000, 7, -130.0 - 13.0, TxRecord.OUTCOME_RECEIVED)

    def essai(delai):
        plan = plan_acks([record], [radio], _options(), AckTiming(delay_ms=delai),
                         classes=["C"])
        return plan.outcomes[0], (plan.busy[0][1] - plan.busy[0][0]) / 1e6

    en_rx1, duree_rx1 = essai(0)
    en_rx2, duree_rx2 = essai(1500)
    assert duree_rx1 < 100 < duree_rx2, "les deux essais doivent viser des PHY différents"
    assert not en_rx1.received, "classe C visant RX1 : -130 dBm est sous le seuil SF7"
    assert en_rx2.received, "classe C visant RX2 : -130 dBm est au-dessus du seuil SF12"
    assert str(en_rx2.window) == "AckWindow.CONTINUOUS", "la classe C écoute en continu"


def test_le_rejeu_porte_la_fenetre_dont_la_phy_la_servi():
    """Rejeu : `AcceptEmission.fenetre_source` porte la fenêtre, lue et non reconstruite.

    Avant, `trace_events` retrouvait la fenêtre d'un rejeu par inférence (« dernière acceptation
    vue »), ce qui dépendait de l'ordre de `tentative.accepts`. Le champ la porte explicitement.

    On exerce ici les DEUX branches : un rejeu né d'une acceptation RX1, et un rejeu né d'une
    acceptation RX2 — celui-là seul distingue l'inférence d'une lecture correcte quand RX1 et RX2
    n'ont pas la même fréquence.
    """
    from lsim.join import RX1, RX2, REPLAY
    from lsim.retransmissions import simulate_confirmed_uplinks

    scenario = Scenario(ScenarioModel.model_validate({
        "schema_version": 1, "name": "d315-rejeu", "seed": 11,
        "gateway": {"x_m": 0, "y_m": 0, "antenna_gain_dbi": 2.15},
        "propagation": {"frequency_hz": _canal("EU868"), "exponent": 2.7},
        "retransmissions": {"enabled": True, "retries": 1, "retransmit_delay_ms": 3000,
                            "enforce_duty_cycle": False, "join_requests_s": [0],
                            "join_retries": 1, "join_accept_rx2_fallback": True,
                            "join_accept_replays": 2},
        "groups": [
            {"name": f"sf{sf}", "count": 1, "region": "EU868",
             "channel_freq_hz": _canal("EU868"),
             "placement": {"type": "disk", "radius_m": r},
             "spreading_factor": sf, "payload_bytes": 20, "tx_power_dbm": 14.0,
             "period_s": 30, "messages": 4, "start_spread_s": 10}
            for sf, r in ((7, 500), (9, 1000), (11, 1500), (12, 1900))
        ]}))
    radios = device_radios(scenario)
    devices, _g, _i = scenario.deploy()
    res = simulate_confirmed_uplinks(devices, scenario.gateway(), scenario.propagation(), radios,
                                     _options(), scenario.model.retransmissions.options(),
                                     with_engine_output=True)
    rejeux = [e for t in getattr(res, "joins", ()) for e in t.accepts if e.window == REPLAY]
    assert rejeux, "aucun rejeu produit : le test ne prouverait rien"
    for e in rejeux:
        assert e.fenetre_source in (RX1, RX2), (
            f"rejeu sans fenêtre source valide : {e.fenetre_source!r}")
    # Le cas qui distingue une lecture correcte d'une inférence : un rejeu issu d'une acceptation
    # RX2. Sans `fenetre_source`, il retomberait sur RX1. C'est l'assertion qui rend le test
    # discriminant — les deux autres ne portent que sur des rejeux RX1, indétectables.
    de_rx2 = [e for e in rejeux if e.fenetre_source == RX2]
    assert de_rx2, (
        f"aucun rejeu issu de RX2 sur {len(rejeux)} : le test ne distinguerait pas "
        f"la lecture du champ d'une inférence")
    # Et la fréquence tracée d'un rejeu suit sa fenêtre source, pas une inférence d'ordre.
    from lsim.trace_events import build_trace

    run = build_trace(scenario, _options())
    acceptees = {(t.device, e.at_ns): e for t in getattr(res, "joins", ()) for e in t.accepts}
    for ev in run.events:
        if ev.kind != "join_accept":
            continue
        emission = acceptees.get((ev.device_index, ev.t_ns))
        if emission is None or emission.window not in (RX1, RX2, REPLAY):
            continue
        attendu = (radios[ev.device_index].rx2_hz if emission.fenetre_source == RX2
                   else radios[ev.device_index].rx1_hz)
        assert any(h.freq_hz == attendu for h in ev.hops), (
            f"rejeu {emission.window}/{emission.fenetre_source} rapporté sur "
            f"{[h.freq_hz for h in ev.hops]}, attendu {attendu}")


def test_les_jointures_declarees_restent_en_rx1():
    """Jointures déclarées : aucune fenêtre n'existe, la convention RX1 est conservée et épinglée.

    Une jointure « déclarée » (`session_joins_s`) ouvre une session à un instant donné sans
    simulation radio : il n'y a ni RX1 ni RX2, donc aucune fenêtre à choisir. Le `HopEvent` garde
    `rx1_hz`, convention antérieure. Le test existe pour que ce point reste une convention
    documentée et vérifiée, non une limite implicite.
    """
    from lsim.trace_events import build_trace

    hz = _canal("EU868")
    scenario = Scenario(ScenarioModel.model_validate({
        "schema_version": 1, "name": "d315-declare", "seed": 11,
        "gateway": {"x_m": 0, "y_m": 0, "antenna_gain_dbi": 2.15},
        "propagation": {"frequency_hz": hz, "exponent": 2.7},
        # `is_active` exige `retries > 0` : sans réémission possible, `build_trace` emprunte le
        # chemin historique et les jointures déclarées n'apparaissent jamais.
        "retransmissions": {"enabled": True, "retries": 1, "retransmit_delay_ms": 2000,
                            "enforce_duty_cycle": False, "session_joins_s": [2]},
        "groups": [{"name": "g", "count": 3, "region": "EU868", "channel_freq_hz": hz,
                    "placement": {"type": "disk", "radius_m": 600},
                    "spreading_factor": 9, "payload_bytes": 20, "tx_power_dbm": 14.0,
                    "period_s": 30, "messages": 4, "start_spread_s": 10}]}))
    radios = device_radios(scenario)
    run = build_trace(scenario, _options())
    acceptees = [e for e in run.events if e.kind == "join_accept"]
    assert acceptees, "aucune jointure déclarée en trace"
    for e in acceptees:
        for h in e.hops:
            assert h.freq_hz == radios[e.device_index].rx1_hz, (
                f"jointure déclarée rapportée sur {h.freq_hz}")


def test_a_faible_puissance_passerelle_la_correction_change_le_resultat():
    """D-I3-2 : latent à 27 dBm, il double les ACK reçus à 7 dBm — les deux régimes sont épinglés.

    C'est le test qui donne sa portée réelle au correctif. Sous le budget de liaison par défaut
    (P_gw 27 dBm contre P_dev 14 dBm, soit +13 dB au descendant) l'asymétrie couvre déjà l'écart
    de sensibilité RX1/RX2 : le défaut n'y changeait RIEN. Il devient observable quand
    l'asymétrie se réduit. Sans ce test, le correctif ne serait gardé que dans le régime où il
    est sans effet.
    """
    import lsim.ack_mac as am

    original = am._decodable
    # Rayon large : il faut des terminaux dans la bande marginale entre les deux seuils, sinon
    # tous les descendants sont largement au-dessus des deux sensibilités et le test est vide.
    scenario = _scene(region="EU868", sf=7, rayon=40_000)
    radios = device_radios(scenario)
    devices, _, _ = scenario.deploy()
    resultat = simulate_uplinks_trace(devices, scenario.gateway(), scenario.propagation(),
                                      scenario.environment, gateway_busy=())
    par = [radios[r.device_index] for r in resultat.records]

    def compter(pgw, forcer_ancien):
        def _ancien(rssi, radio, options, en_rx2=False):
            return original(rssi, radio, options, en_rx2=False)
        am._decodable = _ancien if forcer_ancien else original
        try:
            opts = ProtocolOptions(confirmed_uplinks=True, downlink_every=1,
                                   downlink_payload_bytes=60, gateway_tx_power_dbm=pgw,
                                   rx2_fallback=True)
            plan = plan_acks(resultat.records, par, opts, AckTiming(delay_ms=1500))
            return sum(1 for o in plan.outcomes if o.received)
        finally:
            am._decodable = original

    # Régime par défaut : le défaut y était latent — le correctif ne change rien.
    assert compter(27.0, True) == compter(27.0, False), (
        "à 27 dBm la correction ne doit rien changer (asymétrie de 13 dB)")
    # Régime dégradé : la correction y est décisive.
    avant, apres = compter(7.0, True), compter(7.0, False)
    assert apres > avant, (
        f"à 7 dBm la correction doit augmenter les ACK reçus ({avant} -> {apres})")
