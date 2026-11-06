"""D3.15-R — conclusions historiques de D3.15, requalifiées sur des scènes recalibrées.

Pourquoi un fichier distinct
----------------------------

`test_d315_global.py` est préservé tel quel, de même que les quatre artefacts archivés en
`docs/archives/d315-avant-recalibrage/2026-11-06/` (arbitrage **O4** : archivage sans
écrasement, puis marquage, puis nouveau jeu). Ce fichier est le nouveau jeu.

Le jeu historique était **vacant** : à la charge de 120 octets qu'il emploie, aucune des sept
régions ne produit le moindre repli RX2, et trois d'entre elles n'émettent aucune descente
(`docs/D315_RECALIBRAGE.md`, §C.1). Une assertion portant sur un ensemble vide est vraie :
41 des 56 cas historiques passaient donc sans rien démontrer.

Le présent fichier reprend **les mêmes conclusions** sur des scènes où elles ont un objet, et
les assortit d'un critère de non-vacuité explicite (`rx1 > 0` **et** `rx2 > 0` **et** des
descentes perdues), au lieu du seul « le test passe ».

Ce que ce fichier n'établit pas
-------------------------------

Les scènes bi-SF d'US915 et d'AU915 exploitent que la collision montante n'est jugée qu'entre
émissions de **même** SF. Elles produisent une contention descendante **réelle**, mais elles ne
constituent en aucun cas une preuve de fidélité radio : `_CTxRecord` ne porte aucun champ de
fréquence, donc le cœur C++ place toutes les émissions montantes dans un domaine de collision
unique. Cette limitation est **épinglée** par `test_la_scene_bi_sf_nest_pas_une_preuve_de_
fidelite_radio` — non réparée ici. Elle relève du chantier radio.
"""

import pytest

from lsim.downlink_plan import plan_native_v2
from lsim.plan import get_plan
from lsim.scenario import Scenario, ScenarioModel
from lsim.simulator import _CTxRecord, simulate_uplinks_trace
from lsim.trace_events import (MOTIFS_CAPACITE, MOTIFS_TEMPOREL, MOTIF_NO_WINDOW_CAPACITY,
                               MOTIF_RX2_CAPACITY, MOTIF_WINDOW_MISSED, ProtocolOptions,
                               _downlink_jobs, _events, _schedule_gateway,
                               _schedule_gateway_with_motifs, _table_rx2, device_radios)

REGIONS_COUVERTES = ("EU868", "US915", "AS923", "AU915", "IN865", "KR920", "RU864")

# Charge historique du jeu D3.15, conservée pour la démonstration de vacuité.
CHARGE_HISTORIQUE = 120


# ------------------------------------------------------------------- fabrique de scènes
#
# Réglages retenus par le recalibrage (§C.1 du rapport). Deux points méritent attention :
#
#   - la charge descendante est ramenée à **40 octets**, sous N(RX2) de toutes les régions
#     (51 ou 53). Au-delà, RX2 ne peut pas porter la trame et le repli est refusé pour
#     capacité : c'est la cause première de la vacuité historique ;
#   - US915 et AU915 emploient **deux groupes de SF différents**. Leur descente est à 500 kHz,
#     si bien qu'une fenêtre RX1 y est plus courte que le montant qui l'a ouverte : deux
#     fenêtres RX1 ne peuvent s'y chevaucher que si les montants se sont déjà collisionnés.
#     Entre deux SF, la collision n'est pas jugée — un montant SF7 peut se terminer à
#     l'intérieur d'un montant SF10 sans qu'aucun ne soit perdu, et les deux fenêtres RX1
#     s'ouvrent alors à moins d'un temps d'antenne descendant l'une de l'autre (§C.2).
#
# Le SF11 historique d'US915 est **invalide** : SF11/125 kHz n'est un DR montant d'aucune
# région US915. SF10/125 = DR0 est le DR montant le plus lent de la région.
REGLAGES = {
    "EU868": dict(sfs=(11,), charge=40, count=60, spread=60),
    "US915": dict(sfs=(10, 7), charge=40, count=30, spread=2.0),
    "AS923": dict(sfs=(7,), charge=40, count=60, spread=60),
    "AU915": dict(sfs=(10, 8), charge=40, count=30, spread=3.0),
    "IN865": dict(sfs=(7,), charge=40, count=60, spread=60),
    "KR920": dict(sfs=(9,), charge=40, count=60, spread=60),
    "RU864": dict(sfs=(10,), charge=40, count=60, spread=60),
}


def _canal(region):
    return get_plan(region).uplink_channels_hz()[0]


def _scene_r(region, sfs=None, count=None, spread=None, period=5, messages=20, rayon=600):
    """Scène recalibrée. Un groupe par SF : plusieurs SF ⇒ plusieurs groupes."""
    p = REGLAGES[region]
    sfs = p["sfs"] if sfs is None else sfs
    count = p["count"] if count is None else count
    spread = p["spread"] if spread is None else spread
    f0 = _canal(region)
    groupes = [
        {"name": f"g{i}", "count": count, "region": region, "channel_freq_hz": f0,
         "placement": {"type": "disk", "radius_m": rayon}, "spreading_factor": sf,
         "payload_bytes": 20, "tx_power_dbm": 14.0, "period_s": period,
         "messages": messages, "start_spread_s": spread}
        for i, sf in enumerate(sfs)]
    return Scenario(ScenarioModel.model_validate({
        "schema_version": 1, "name": "d315r", "seed": 11,
        "gateway": {"x_m": 0, "y_m": 0, "antenna_gain_dbi": 2.15},
        "propagation": {"frequency_hz": f0, "exponent": 2.7}, "groups": groupes}))


def _options(charge, repli=True):
    return ProtocolOptions(confirmed_uplinks=True, downlink_every=1,
                           downlink_payload_bytes=charge, gateway_tx_power_dbm=27.0,
                           rx2_fallback=repli)


class _Course:
    """Résultat d'un rejeu : jobs, planification, motifs, événements."""

    def __init__(self, region, charge, repli=True, **kw):
        self.region, self.charge = region, charge
        self.scenario = _scene_r(region, **kw)
        self.radios = device_radios(self.scenario)
        devices, _, _ = self.scenario.deploy()
        trace = simulate_uplinks_trace(devices, self.scenario.gateway(),
                                       self.scenario.propagation(),
                                       self.scenario.environment, gateway_busy=())
        self.records = trace.records
        self.options = _options(charge, repli)
        self.jobs = _downlink_jobs(self.records, self.radios, self.options,
                                   [False] * len(self.records), None)
        (self.starts, self.fenetres, self.occupation,
         self.motifs) = _schedule_gateway_with_motifs(self.jobs, self.options)
        self.evenements = _events(self.records, self.radios, self.jobs, self.starts,
                                  [False] * len(self.records), None, self.fenetres,
                                  self.options)

    # --- compteurs -------------------------------------------------------------------
    @property
    def rx1(self):
        return self.fenetres.count("rx1")

    @property
    def rx2(self):
        return self.fenetres.count("rx2")

    @property
    def aucune(self):
        return self.fenetres.count(None)

    @property
    def occupation_ns(self):
        return sum(b - a for a, b in self.occupation)

    @property
    def livrees(self):
        return sum(1 for e in self.evenements for h in e.hops
                   if h.to_id.startswith("dev:")
                   and h.outcome in ("delivered", "received"))

    def fenetre_de(self, k):
        return self.fenetres[k]

    def emission_de(self, k):
        """Intervalle émis [début, fin) du job `k`, ou None s'il n'a rien émis."""
        if self.fenetres[k] is None:
            return None
        duree = (self.jobs[k].rx2_airtime_ns if self.fenetres[k] == "rx2"
                 else self.jobs[k].airtime_ns)
        return (self.starts[k], self.starts[k] + duree)

    def bloqueurs_de(self, k):
        """Jobs **distincts** déjà émis qui recouvrent la fenêtre RX1 du job `k`.

        Un bloqueur a forcément commencé avant l'ouverture de la fenêtre RX1 : l'arbitre est
        « premier arrivé, premier servi », une émission postérieure ne peut pas en bloquer une
        antérieure. Intervalles semi-ouverts : se toucher n'est pas se chevaucher.
        """
        debut, fin = self.jobs[k].t_open, self.jobs[k].t_open + self.jobs[k].airtime_ns
        return [j for j in range(len(self.jobs))
                if j != k and self.fenetres[j] is not None
                and self.starts[j] < debut
                and self.starts[j] < fin
                and debut < self.starts[j] + (self.jobs[j].rx2_airtime_ns
                                              if self.fenetres[j] == "rx2"
                                              else self.jobs[j].airtime_ns)]


def _courir(region, charge=None, repli=True, **kw):
    charge = REGLAGES[region]["charge"] if charge is None else charge
    return _Course(region, charge, repli, **kw)


def _sauts_descendants(evenements):
    """(instant, dispositif, fréquence, issue) de chaque saut passerelle → terminal."""
    return tuple(sorted((e.t_ns, e.device_index, h.freq_hz, h.outcome)
                        for e in evenements for h in e.hops
                        if h.to_id.startswith("dev:")))


def _n_de_la_fenetre(radios, k, fenetre):
    """N du DR **réellement utilisé** par la fenêtre, lu sur le job."""
    return (radios[0].rx2_max_payload if fenetre == "rx2"
            else radios[0].rx1_max_payload)


# ============================================================ A. non-vacuité des sept régions
#
# C'est l'exigence que le jeu historique ne satisfaisait pas. « Le test passe » n'y suffit
# pas : une assertion portant sur un ensemble vide est vraie. On exige donc les trois
# grandeurs à la fois.

@pytest.mark.parametrize("region", REGIONS_COUVERTES)
def test_les_sept_regions_sont_non_vacantes(region):
    """Les deux fenêtres sont réellement exercées — sinon tout le reste est vide de sens."""
    c = _courir(region)
    assert c.rx1 > 0, f"{region} : aucune descente RX1 (jobs={len(c.jobs)})"
    assert c.rx2 > 0, (f"{region} : aucun repli RX2 — scène vacante "
                       f"(rx1={c.rx1}, aucune={c.aucune}, jobs={len(c.jobs)})")
    assert c.rx1 + c.rx2 + c.aucune == len(c.jobs)


@pytest.mark.parametrize("region", REGIONS_COUVERTES)
def test_la_scene_nest_pas_triviale_des_descentes_sont_perdues(region):
    """La contrainte est réellement exercée : des fenêtres sont manquées.

    Une scène où tout aboutirait ne mesurerait rien : le repli n'aurait jamais lieu d'être.
    """
    c = _courir(region)
    assert c.aucune > 0, (f"{region} : aucune descente perdue — la passerelle ne sature "
                          f"pas, la scène est triviale (rx1={c.rx1}, rx2={c.rx2})")


def test_le_jeu_historique_etait_vacant_et_cela_est_desormais_mesure():
    """Contrôle de la correction : à la charge historique, les sept scènes sont vides.

    Ce test est la raison d'être du recalibrage. Il échouerait si quelqu'un « corrigeait »
    la vacuité en relâchant une contrainte au lieu de changer la charge.
    """
    for region in REGIONS_COUVERTES:
        c = _courir(region, charge=CHARGE_HISTORIQUE)
        assert c.rx2 == 0, (f"{region} : un repli s'est produit à {CHARGE_HISTORIQUE} octets — "
                            f"la démonstration de vacuité ne tient plus")
        assert c.motifs, f"{region} : aucun motif rapporté à {CHARGE_HISTORIQUE} octets"


# ============================================ B. limites N du DR effectivement utilisé
#
# R-N1 : chaque fenêtre est validée contre son propre DR, et non contre celui de l'uplink ni
# contre celui de l'autre fenêtre. La grandeur comparée à N est **charge + |FOpts|**, et non
# la trame entière (§25.2.1 : M = N + 8 borne le MACPayload, N borne la charge utile).

@pytest.mark.parametrize("region", REGIONS_COUVERTES)
def test_la_charge_respecte_n_de_la_fenetre_emise(region):
    """Aucune fenêtre émise ne porte une charge supérieure au N de son propre DR."""
    c = _courir(region)
    emises = [k for k, f in enumerate(c.fenetres) if f is not None]
    assert emises, f"{region} : aucune émission, le contrôle n'aurait pas de sens"
    for k in emises:
        f = c.fenetres[k]
        job = c.jobs[k]
        assert job.soumis_a_n, f"{region} job {k} : descente applicative non soumise à N"
        borne = job.rx2_max_payload if f == "rx2" else job.rx1_max_payload
        assert job.charge_contrainte <= borne, (
            f"{region} job {k} : {f} émise avec charge+FOpts={job.charge_contrainte} "
            f"> N={borne}")


@pytest.mark.parametrize("region", REGIONS_COUVERTES)
def test_n_de_rx2_est_celui_du_dr_de_rx2_et_non_de_luplink(region):
    """N(RX2) est celui du DR de la fenêtre de secours, vérifié contre le plan régional.

    Deux lectures indépendantes doivent coïncider : celle du DR issu de `dl_settings`, et
    celle du débit effectif de RX2. Elles diffèrent de N(RX1) dès que les DR diffèrent —
    sinon le contrôle serait vide.
    """
    plan = get_plan(region)
    dr_rx2 = plan.dl_settings & 0x0F
    attendu = plan.max_frm_payload(dr_rx2)
    assert attendu == plan.max_frm_payload(
        plan.dr_of_downlink_datr(plan.rx2()[1])), (
        f"{region} : les deux lectures de N(RX2) divergent")

    c = _courir(region)
    jobs_rx2 = [k for k, f in enumerate(c.fenetres) if f == "rx2"]
    assert jobs_rx2, f"{region} : aucun repli, le contrôle n'aurait pas de sens"
    for k in jobs_rx2:
        assert c.jobs[k].rx2_max_payload == attendu, (
            f"{region} job {k} : N(RX2)={c.jobs[k].rx2_max_payload}, attendu {attendu}")
    # Et ce n'est pas N(RX1) : la confusion des deux est précisément le défaut R-N1.
    n_rx1 = c.jobs[jobs_rx2[0]].rx1_max_payload
    assert (attendu != n_rx1) or region in ("EU868", "KR920", "RU864"), (
        f"{region} : N(RX1) = N(RX2) = {attendu} sans que le profil le justifie")


@pytest.mark.parametrize("region", REGIONS_COUVERTES)
def test_au_dela_de_n_rx2_le_repli_est_refuse_pour_capacite(region):
    """Au-delà de N(RX2), le repli est refusé **sans réserver l'émetteur** (R-N2).

    C'est la famille `capacite`, distincte de la famille `temporel` : la fenêtre ne peut pas
    porter la trame, elle ne fait l'objet d'aucune demande et n'occupe donc rien.
    """
    plan = get_plan(region)
    n_rx2 = plan.max_frm_payload(plan.dl_settings & 0x0F)
    n_rx1 = None
    charge = max(CHARGE_HISTORIQUE, n_rx2 + 1)
    c = _courir(region, charge=charge)
    assert c.rx2 == 0, (f"{region} : repli émis avec charge={charge} > N(RX2)={n_rx2}")
    refus = {m for m in c.motifs if m is not None}
    assert refus <= set(MOTIFS_CAPACITE), (
        f"{region} : motifs inattendus {refus - set(MOTIFS_CAPACITE)}")
    assert refus, f"{region} : aucun refus rapporté, la contrainte n'est pas appliquée"
    # Aucune fenêtre éligible ⇒ aucune émission du tout (cas où N(RX1) ≤ charge aussi).
    if refus == {MOTIF_NO_WINDOW_CAPACITY}:
        assert c.rx1 == 0 and c.occupation == [], (
            f"{region} : aucune fenêtre éligible, mais {c.rx1} RX1 émises")


def test_les_deux_familles_de_motifs_sont_disjointes():
    """Garde-fou (aaa5) : `capacite` et `temporel` ne se recouvrent jamais.

    Un motif classé dans les deux familles rendrait le diagnostic ambigu.
    """
    assert not set(MOTIFS_CAPACITE) & set(MOTIFS_TEMPOREL)
    assert MOTIF_WINDOW_MISSED in MOTIFS_TEMPOREL
    assert {MOTIF_RX2_CAPACITY, MOTIF_NO_WINDOW_CAPACITY} <= set(MOTIFS_CAPACITE)


# ===================================== C. les replis résultent réellement de la contention
#
# Un repli peut avoir deux causes légitimes mais distinctes : RX1 ne peut pas porter la trame
# (capacité), ou l'émetteur est occupé à son ouverture (contention). Seule la seconde est une
# démonstration de la règle I2. On exige donc que **chaque** repli soit imputable à une
# émission déjà en cours, et non à un défaut de planification.

@pytest.mark.parametrize("region", REGIONS_COUVERTES)
def test_chaque_repli_est_bloque_par_une_emission_distincte(region):
    """Chaque RX2 émise l'est parce qu'une **autre** émission occupait la fenêtre RX1.

    La preuve est constructive : on exhibe, pour chaque repli, l'intervalle émis qui recouvre
    la fenêtre RX1 du job et a débuté avant son ouverture. Aucun repli ne doit rester
    inexpliqué — un repli sans bloqueur signalerait un défaut de planification, pas une
    contention.
    """
    c = _courir(region)
    replis = [k for k, f in enumerate(c.fenetres) if f == "rx2"]
    assert replis, f"{region} : aucun repli, le contrôle n'aurait pas de sens"
    inexpliques = [k for k in replis if not c.bloqueurs_de(k)]
    assert not inexpliques, (
        f"{region} : {len(inexpliques)} repli(s) sans bloqueur — ce n'est pas de la "
        f"contention : {[(k, c.jobs[k].t_open) for k in inexpliques[:5]]}")


@pytest.mark.parametrize("region", REGIONS_COUVERTES)
def test_aucun_repli_nest_imputable_a_la_capacite(region):
    """Dans une scène conforme, le seul motif présent est `window_missed` (famille temporel).

    Si un motif de capacité apparaissait, les replis compteraient des cas où RX2 était
    intransportable — et le dénombrement de la contention serait faussé.
    """
    c = _courir(region)
    refus = {m for m in c.motifs if m is not None}
    assert refus <= set(MOTIFS_TEMPOREL), (
        f"{region} : motif de capacité dans une scène conforme : "
        f"{refus - set(MOTIFS_TEMPOREL)}")
    assert refus, f"{region} : aucun motif, la scène ne sature pas"


@pytest.mark.parametrize("region", REGIONS_COUVERTES)
def test_sans_contention_le_repli_disparait(region):
    """Témoin négatif : un seul terminal par groupe ⇒ aucune contention, donc aucun repli.

    La scène est par ailleurs inchangée : même région, même charge, même réglage de repli.
    Que les descentes aboutissent toutes (aucune = 0) confirme que c'est bien la charge de
    l'émetteur, et non une inéligibilité de RX1, qui provoquait les replis.
    """
    c = _courir(region, count=1)
    assert c.rx1 > 0, f"{region} : aucune descente émise, le témoin est vide"
    assert c.rx2 == 0, (f"{region} : repli sans contention — la cause n'est pas "
                        f"l'occupation de l'émetteur")
    assert c.aucune == 0, f"{region} : {c.aucune} descente(s) perdue(s) sans contention"


@pytest.mark.parametrize("region", REGIONS_COUVERTES)
def test_le_repli_ajoute_de_lantenne_et_nen_retire_jamais(region):
    """Reprise du §4 : activer le repli ne peut qu'ajouter du temps d'antenne.

    Conclusion historique **confirmée** sur scène non vacante : sans repli, une RX1 manquée
    n'émet rien ; avec repli, elle émet. La conclusion était vraie mais vide à 120 octets.
    """
    avec = _courir(region, repli=True)
    sans = _courir(region, repli=False)
    assert avec.rx2 > 0, f"{region} : aucun repli, le contrôle n'aurait pas de sens"
    assert avec.occupation_ns >= sans.occupation_ns, (
        f"{region} : activer le repli a réduit l'occupation "
        f"({sans.occupation_ns} → {avec.occupation_ns} ns)")
    # Et l'écart est au moins le temps d'antenne des replis émis.
    ajout = avec.occupation_ns - sans.occupation_ns
    assert ajout > 0, f"{region} : le repli n'ajoute rien, la scène est dégénérée"


# Configurations où R = airtime(RX2)/airtime(RX1) est **strictement inférieur à 1**, mesurées
# sur les six SF montants valides des sept régions. Deux seulement existent :
#
#   - EU868, KR920, RU864 : RX2 est en SF12/125 et RX1 suit le SF montant, qui vaut au plus
#     12 ⇒ R ≥ 1 partout (R = 1 au SF12).
#   - US915, AU915 : RX1 et RX2 sont tous deux à 500 kHz, et RX2 y est le DR le plus lent
#     (DR8 = SF12/500) ⇒ R > 1 partout. Le SF11 qui donnait R < 1 dans le jeu historique y
#     est **invalide** (P1) : SF11/125 n'est un DR montant d'aucune région US915.
#   - AS923, IN865 : RX2 est en SF10/125. Un montant en SF11 ou SF12 donne une RX1 plus lente
#     que RX2 ⇒ R < 1. Au SF12, R = 0,25 mais aucune scène n'y produit de repli ; seul le SF11
#     (R = 0,47) est exploitable.
#
# La conclusion historique « R < 1, mesuré sur 3 configurations sur 3 » est donc
# **requalifiée** : le régime existe, mais sur 1 configuration par région dans 2 régions, et
# non sur 3 dans les 7.
R_INFERIEUR_A_UN = (("AS923", 11), ("IN865", 11))


@pytest.mark.parametrize("region, sf", R_INFERIEUR_A_UN)
def test_a_r_infereur_a_un_le_repli_nest_jamais_perdant(region, sf):
    """Reprise du §4 : à R < 1, le repli est moins coûteux que la RX1 — jamais perdant.

    Aucune loi de signe n'est affirmée au-delà : deux contre-exemples à R comparables
    (RU864 SF11 → Δ = +20, AS923 SF9 → Δ = −23) interdisent toute loi de seuil, ce qui est
    un résultat et non une lacune.
    """
    c = _courir(region, sfs=(sf,), count=30, spread=3.0, period=15, messages=6)
    replis = [k for k, f in enumerate(c.fenetres) if f == "rx2"]
    assert replis, f"{region} SF{sf} : aucun repli, rien à mesurer"
    r = c.jobs[replis[0]].rx2_airtime_ns / c.jobs[replis[0]].airtime_ns
    assert r < 1.0, (
        f"{region} SF{sf} : R={r:.2f} ≥ 1 — la configuration ne relève plus du régime "
        f"étudié, revoir R_INFERIEUR_A_UN")
    sans = _courir(region, sfs=(sf,), count=30, spread=3.0, period=15, messages=6,
                   repli=False)
    assert c.livrees - sans.livrees >= 0, (
        f"{region} SF{sf} : R={r:.2f} < 1 — le repli est moins coûteux que la RX1 qu'il "
        f"remplace, il ne peut pas faire perdre des livraisons "
        f"(Δ={c.livrees - sans.livrees})")


@pytest.mark.parametrize("region", REGIONS_COUVERTES)
def test_le_regime_r_inferieur_a_un_nest_pas_atteignable_partout(region):
    """Garde-fou de portée : R < 1 n'est pas une propriété générale, il a un domaine.

    Sans ce contrôle, un rapport laisserait croire que la loi « R < 1 ⇒ jamais perdant »
    s'applique aux sept régions. Elle ne s'applique qu'à AS923 et IN865 au SF11 ; ailleurs
    RX2 est la fenêtre lente, et le repli coûte du temps d'antenne.
    """
    attendu = region in {r for r, _ in R_INFERIEUR_A_UN}
    atteint = False
    for sf in (7, 8, 9, 10, 11, 12):
        try:
            c = _courir(region, sfs=(sf,), count=30, spread=3.0, period=15, messages=6)
        except Exception:                      # SF non admis par la région (P1)
            continue
        if any(c.fenetres[k] == "rx2" and
               c.jobs[k].rx2_airtime_ns < c.jobs[k].airtime_ns
               for k in range(len(c.jobs))):
            atteint = True
            break
    assert atteint == attendu, (
        f"{region} : régime R < 1 {'attendu mais absent' if attendu else 'inattendu'} "
        f"— revoir R_INFERIEUR_A_UN et la portée du §4")


# ==================================================== D. reprise des conclusions (parité)

@pytest.mark.parametrize("region", REGIONS_COUVERTES)
def test_parite_des_deux_moteurs(region):
    """Reprise du §2 : cœur C++ et oracle Python coïncident sur tous les critères.

    Conclusion historique **confirmée et étendue** : la parité était vérifiée sur quatre
    régions, elle l'est ici sur les sept, et sur des scènes non vacantes. Elle ne tient qu'à
    charge conforme — au-delà de N, le cœur n'applique pas encore la règle R-N1 et diverge.
    """
    c = _courir(region)
    evenements_coeur, occupation_coeur = plan_native_v2(
        c.records, c.radios, c.options, _table_rx2(c.radios))
    assert tuple(occupation_coeur) == tuple(c.occupation), f"{region} : occupation"
    assert _sauts_descendants(evenements_coeur) == _sauts_descendants(c.evenements), (
        f"{region} : sauts descendants")
    assert (tuple((e.kind, e.outcome) for e in evenements_coeur)
            == tuple((e.kind, e.outcome) for e in c.evenements)), f"{region} : refus"


@pytest.mark.parametrize("region", REGIONS_COUVERTES)
def test_lairtime_est_celui_de_la_fenetre_emise(region):
    """Reprise du §2 : chaque émission occupe l'émetteur l'airtime de **sa** fenêtre.

    Une RX2 occupe `rx2_airtime_ns`, jamais l'airtime de l'uplink ni celui de RX1 (R-I6-b :
    le repli utilise `rx2_sf`, pas le SF montant).
    """
    c = _courir(region)
    replis = [k for k, f in enumerate(c.fenetres) if f == "rx2"]
    assert replis, f"{region} : aucun repli, le contrôle n'aurait pas de sens"
    attendu = {c.emission_de(k) for k in range(len(c.jobs))
               if c.fenetres[k] is not None}
    assert attendu == set(c.occupation), (
        f"{region} : l'occupation ne correspond pas aux fenêtres émises")
    durees_rx2 = {c.jobs[k].rx2_airtime_ns for k in replis}
    durees_rx1 = {c.jobs[k].airtime_ns for k in replis}
    assert durees_rx2 != durees_rx1, (
        f"{region} : airtime RX2 identique à RX1 — le contrôle n'aurait pas de sens")


def test_les_profils_rx2_des_sept_regions_ne_sont_pas_tous_identiques():
    """Garde-fou : les profils diffèrent, sinon le paramétrage ne prouverait rien."""
    profils = {r: get_plan(r).rx2() for r in REGIONS_COUVERTES}
    assert len({p[1] for p in profils.values()}) >= 2, "débits RX2 tous identiques"
    assert len({p[0] for p in profils.values()}) >= 2, "fréquences RX2 toutes identiques"


def test_un_scenario_sans_region_ne_replie_jamais():
    """Reprise du §5 : sans région, `rx2_hz = 0` et aucun repli, même repli activé."""
    hz = _canal("EU868")
    scenario = Scenario(ScenarioModel.model_validate({
        "schema_version": 1, "name": "sans-region", "seed": 11,
        "gateway": {"x_m": 0, "y_m": 0, "antenna_gain_dbi": 2.15},
        "propagation": {"frequency_hz": hz, "exponent": 2.7},
        "groups": [{"name": "g", "count": 12, "channel_freq_hz": hz,
                    "placement": {"type": "disk", "radius_m": 800},
                    "spreading_factor": 9, "payload_bytes": 20, "tx_power_dbm": 14.0,
                    "period_s": 30, "messages": 6, "start_spread_s": 10}]}))
    radios = device_radios(scenario)
    assert radios[0].rx2_hz == 0, "un scénario sans région ne porte aucune fréquence RX2"
    devices, _, _ = scenario.deploy()
    records = simulate_uplinks_trace(devices, scenario.gateway(), scenario.propagation(),
                                     scenario.environment, gateway_busy=()).records
    for repli in (True, False):
        options = _options(60, repli)
        jobs = _downlink_jobs(records, radios, options, [False] * len(records), None)
        _debuts, fenetres, occupation = _schedule_gateway(jobs, options)
        assert fenetres.count("rx2") == 0, f"repli produit malgré rx2_hz == 0 (repli={repli})"


# =========================================================== E. limite de modèle, épinglée

def test_la_scene_bi_sf_nest_pas_une_preuve_de_fidelite_radio():
    """La scène bi-SF est un moyen de **produire** une contention, pas une preuve de fidélité.

    Elle exploite une **limitation** du modèle : `_CTxRecord` ne porte aucun champ de
    fréquence, donc le cœur C++ met toutes les émissions montantes dans un domaine de
    collision unique, quel que soit le canal déclaré. Deux terminaux sur deux canaux
    distincts s'y collisionnent comme s'ils partageaient le même — ce qu'une passerelle
    LoRaWAN réelle ne fait pas (huit canaux reçus en parallèle).

    Ce test épingle la limitation au lieu de la décrire : si le chantier radio ajoute la
    fréquence à `_CTxRecord`, il échoue et impose de revoir à la fois la scène bi-SF et la
    portée attribuée aux conclusions d'US915 et d'AU915.
    """
    champs = [nom for nom, _ in _CTxRecord._fields_]
    assert champs, "_CTxRecord n'expose aucun champ"
    assert not any("freq" in c or "channel" in c or "hz" in c for c in champs), (
        f"_CTxRecord porte désormais une dimension de fréquence ({champs}) : la limitation "
        f"invoquée par les scènes bi-SF n'existe plus, revoir leur portée")
    # Conséquence directe, mesurée : séparer les terminaux sur deux canaux ne les empêche
    # pas de se collisionner — le nombre de jobs décroît au lieu de croître.
    hz = _canal("EU868")
    def compter(nb_canaux):
        groupes = [
            {"name": f"g{i}", "count": 10, "region": "EU868",
             "channel_freq_hz": hz + i * 400_000,
             "placement": {"type": "disk", "radius_m": 400}, "spreading_factor": 10,
             "payload_bytes": 20, "tx_power_dbm": 14.0, "period_s": 20, "messages": 5,
             "start_spread_s": 3.5} for i in range(nb_canaux)]
        s = Scenario(ScenarioModel.model_validate({
            "schema_version": 1, "name": "canaux", "seed": 11,
            "gateway": {"x_m": 0, "y_m": 0, "antenna_gain_dbi": 2.15},
            "propagation": {"frequency_hz": hz, "exponent": 2.7}, "groups": groupes}))
        radios = device_radios(s)
        devices, _, _ = s.deploy()
        records = simulate_uplinks_trace(devices, s.gateway(), s.propagation(),
                                         s.environment, gateway_busy=()).records
        options = _options(40)
        return len(_downlink_jobs(records, radios, options, [False] * len(records), None))

    un, deux = compter(1), compter(2)
    assert deux < un * 2, (
        f"les canaux semblent désormais séparés ({un} → {deux} jobs pour le double de "
        f"terminaux) : la limitation n'est plus démontrée, revoir le test")
