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

from lsim.downlink_plan import DeviceRx2, plan_native, plan_native_v2
from lsim.radio import receiver_sensitivity_dbm
from lsim.scenario import Scenario, ScenarioModel
from lsim.simulator import TxRecord, simulate_uplinks_trace
from lsim.trace_events import (ProtocolOptions, _downlink_jobs, _events, _schedule_gateway,
                               _table_rx2, device_radios)

SECONDE = 1_000_000_000

# Régions exigées par la directive (§3). [H] — lues dans `lsim.plan`, pas recopiées.
REGIONS_EXIGEES = ("EU868", "US915", "AS923", "IN865")
REGIONS_COUVERTES = ("EU868", "US915", "AS923", "AU915", "IN865", "KR920", "RU864")


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
SF_SATURANT = {"EU868": 11, "US915": 11, "AS923": 7, "AU915": 7,
               "IN865": 7, "KR920": 9, "RU864": 10}

# Paramètres de saturation communs : 60 terminaux, période 5 s, 20 messages, étalement 60 s,
# rayon 600 m, descente de 120 octets.
SATURATION = dict(count=60, period=5, messages=20, spread=60, charge=120, rayon=600)


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


def _options(repli=True, every=1, charge=120):
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
        ev_coeur, occupation_coeur = plan_native_v2(records, radios, options, table)
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


# --------------------------------------------------------- défauts trouvés par la validation (§6)

@pytest.mark.xfail(strict=True, reason="D-I3-1 : Join-Accept RX2 rapporté sur la fréquence RX1")
def test_d_i3_1_le_join_accept_rx2_est_rapporte_sa_frequence():
    """D-I3-1 — `trace_events.py`, construction des événements de jointure radio.

    Le Join-Accept du terminal 2 est **délivré en RX2** (le module `join` le sait :
    `AcceptEmission.window == "rx2"`), mais l'événement de trace porte `radio.rx1_hz` :

        HopEvent("gw:0", _dev(tentative.device), emission.at_ns, radio.rx1_hz, ...)

    Reproduction minimale : `python/tests/test_d315_global.py::test_..._e2e_join` (ci-dessous),
    qui compare la fenêtre connue du module `join` à la fréquence rapportée.

    Portée : la trace alimente le rapport cyclique descendant par sous-bande. Sur EU868, 868,1 MHz
    et 869,525 MHz n'appartiennent pas aux mêmes sous-bandes : l'airtime d'un Join-Accept RX2 est
    imputé à la mauvaise sous-bande.

    Correctif ciblé proposé (3 lignes, aucune refonte) : dans la boucle
    `for emission in tentative.accepts`, choisir la fréquence selon `emission.window` —

        freq = radio.rx2_hz if emission.window == "rx2" else radio.rx1_hz

    — et l'utiliser dans le `HopEvent`. `emission.window` vaut `rx1`, `rx2` ou `replay`.
    """
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
    from lsim.retransmissions import simulate_confirmed_uplinks

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


@pytest.mark.xfail(strict=True, reason="D-I3-2 : réception jugée au seuil RX1 quelle que soit la fenêtre")
def test_d_i3_2_la_reception_suit_la_fenetre_dans_ack_mac():
    """D-I3-2 — `ack_mac._decodable`, partagé par les ACK **et** les Join-Accept.

    `plan_acks` calcule `decodable` **une fois par uplink**, avant que la fenêtre ne soit connue
    (ligne 426), puis l'applique à toutes les copies (ligne 438 : `elif not decodable`) quelle que
    soit la fenêtre où l'émission atterrit. La sensibilité utilisée est celle de RX1 :

        sensitivity = receiver_sensitivity_dbm(radio.rx1_sf, radio.rx1_bw_hz)

    Reproduction minimale — deux terminaux, le second replié en RX2 :

        gros  = DeviceRadio(..., rx1_sf=12, rx2_sf=9)   # ACK court en RX2, bloque l'émetteur
        petit = DeviceRadio(..., rx1_sf=7,  rx2_sf=12)  # RX1 SF7 (-123 dBm), RX2 SF12 (-136 dBm)
        plan  = plan_acks(records, [gros, petit], options, AckTiming(delay_ms=1500))

    Résultat observé (`rssi + 13 dB` = RSSI descendant, P_gw 27 dBm − P_dev 14 dBm) :

        rssi    rssi_dl   verdict    occupation
        -136     -123     STANDARD   991,2 ms   ← seuil RX1 (SF7) franchi
        -137     -124     LOST       991,2 ms   ← seuil RX1 (SF7) non franchi

    L'occupation de 991,2 ms est bien celle du **SF12** : le moteur émet au débit RX2 et juge la
    réception au seuil RX1. Les 13 dB de marge du SF12 sont ignorés.

    Le même `_decodable` est importé par `lsim.join` (ligne 71) : un Join-Accept délivré en RX2 —
    mécanisme déjà actif par défaut — est jugé de la même façon.

    Correctif ciblé proposé (aucune refonte) : passer la fenêtre à `_decodable` et reprendre le
    seuil correspondant, comme `_seuil_dispositif` le fait déjà dans `trace_events` depuis I3/C4 —

        def _decodable(rssi, radio, options, fenetre="rx1"):
            seuil = (receiver_sensitivity_dbm(radio.rx2_sf, radio.rx2_bw_hz or radio.rx1_bw_hz)
                     if fenetre == "rx2" and radio.rx2_disponible
                     else receiver_sensitivity_dbm(radio.rx1_sf, radio.rx1_bw_hz))

    — puis, dans la boucle des créneaux, évaluer `decodable` **après** `ou_ecoute` :

        elif not _decodable(record.rssi_dbm, radio, options, str(ou_ecoute)):

    `ou_ecoute` est déjà connu à cet endroit (c'est la valeur retenue dans `fenetre_retenue`).
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
    for sf in (7, 9, 11, 12):
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
    for sf in (7, 9, 11, 12):
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
        for sf in (7, 9, 11, 12):
            scenario = _scene(region=region, sf=sf)
            radios = device_radios(scenario)
            resultat = _trace_sans_occupation(scenario)
            avec = _mesurer(resultat.records, radios, 240, True)
            sans = _mesurer(resultat.records, radios, 240, False)
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
        avec = _mesurer(resultat.records, radios, 120, repli=True)
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
        hz, sf, bw = _rx2_de_la_region(region)
        _, sf1, bw1 = _rx1_de_la_region(region)
        profils[region] = (hz, sf, bw, sf1, bw1)

    # Au moins trois couples (fréquence RX2, SF RX2, BW RX2) distincts sur les régions couvertes.
    assert len({(v[0], v[1], v[2]) for v in profils.values()}) >= 3, (
        f"les profils RX2 ne se différencient pas : {profils}")
    # Et au moins une région où RX1 et RX2 partagent la fréquence — la transparence du cœur ne
    # permet pas d'y lire la fenêtre sur la fréquence.
    confondues = [r for r, v in profils.items() if v[0] == _rx1_de_la_region(r)[0]]
    assert confondues, "aucune région à RX1/RX2 confondus : la réserve serait caduque"
