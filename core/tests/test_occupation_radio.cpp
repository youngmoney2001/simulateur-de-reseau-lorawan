// SPDX-License-Identifier: Apache-2.0
// U0.4 — Propagation de l'occupation radio réelle et cohérence du demi-duplex.
//
// Objet du jalon : une émission **acceptée** par l'ordonnanceur radio doit être immédiatement
// visible de tous les mécanismes qui ont besoin de connaître l'état de l'émetteur, et une
// émission **refusée** ne doit réserver aucune ressource.
//
// Avant U0.4, le chemin causal du moteur entretenait sa propre liste `planned`, alimentée par les
// valeurs de retour de `on_received`. Le placement décidait sur l'ordonnanceur, le demi-duplex
// lisait la copie : deux états pour une même réalité, et aucune vérification de leur égalité.
// Le moteur interroge désormais l'ordonnanceur directement ; `busy_out` en est dérivé.
//
// Ces tests épinglent la conséquence **observable** de ce choix, pas son écriture : ils
// échoueraient si l'on réintroduisait une copie divergente, quelle que soit sa forme.
#include <algorithm>
#include <cstdint>
#include <vector>

#include "check.hpp"
#include "lsim/engine.hpp"
#include "lsim/radio_scheduler.hpp"

namespace {

using lsim::sim::CausalDownlinks;
using lsim::sim::DeviceStats;
using lsim::sim::EndDeviceSpec;
using lsim::sim::GatewaySpec;
using lsim::sim::Interval;
using lsim::sim::PropagationSpec;
using lsim::sim::SimulationStats;
using lsim::sim::SimTime;
using lsim::sim::TxOutcome;
using lsim::sim::TxRecord;

constexpr SimTime kS = 1'000'000'000;

// Un dispositif à un seul message, entièrement audible : aucune perte de sensibilité, aucune
// collision entre montantes tant que les intervalles ne se chevauchent pas.
EndDeviceSpec dev(double x_m, int sf, SimTime start_ns, std::uint32_t messages = 1) {
    EndDeviceSpec d{};
    d.position.x_m = x_m;
    d.position.y_m = 0.0;
    d.spreading_factor = static_cast<std::uint8_t>(sf);
    d.payload_bytes = 8;
    d.tx_power_dbm = 14.0;
    d.start_offset_ns = start_ns;
    d.period_ns = 3600 * kS;
    d.messages = messages;
    return d;
}

lsim::plan::DeviceRadio radio(int sf = 7) {
    lsim::plan::DeviceRadio r{};
    r.freq_hz = 868'100'000;
    r.dr = -1;
    r.rx1_hz = 868'100'000;
    r.tx_power_dbm = 14.0;
    r.rx1_sf = sf;
    r.rx1_bw_hz = 125'000;
    return r;
}

// Joue le chemin causal et renvoie l'occupation restituée, la trace et les compteurs.
struct Causal {
    std::vector<lsim::plan::Interval> busy;
    std::vector<TxRecord> trace;
    SimulationStats totals{};
    std::vector<DeviceStats> stats;
    int status = -1;

    Causal(const std::vector<EndDeviceSpec>& d, const std::vector<lsim::plan::DeviceRadio>& rv,
           const lsim::plan::PlanOptions& o, const std::vector<lsim::plan::DeviceRx2>* rx2 = nullptr) {
        CausalDownlinks cd;
        cd.radios = rv;
        cd.options = o;
        cd.rx2 = rx2;
        cd.busy_out = &busy;
        stats.resize(d.size());
        status = static_cast<int>(lsim::sim::simulate_uplinks(
            d.data(), d.size(), GatewaySpec{}, PropagationSpec{}, stats.data(), totals, nullptr,
            &trace, nullptr, nullptr, &cd));
    }
};

lsim::plan::PlanOptions options_dl(std::uint32_t every = 1, std::uint32_t payload = 200,
                                   bool repli = false) {
    lsim::plan::PlanOptions o;
    o.confirmed_uplinks = true;
    o.downlink_every = every;
    o.downlink_payload_bytes = payload;
    o.gateway_tx_power_dbm = 27.0;
    o.rx2_fallback = repli;
    return o;
}

// --------------------------------------------------------------------------- invariance de forme

void test_occupation_restituee_est_croissante_et_disjointe() {
    // `busy_out` est la source de vérité publiée : le point fixe Python s'en sert comme
    // occupation imposée, et `transmitting_in` exige une liste croissante et disjointe.
    // Le contrat est garanti par construction depuis U0.4 — il ne l'était que par accident avant.
    const std::vector<EndDeviceSpec> d = {
        dev(100.0, 7, 0), dev(200.0, 7, 50'000'000), dev(300.0, 7, 100'000'000),
        dev(400.0, 7, 150'000'000), dev(500.0, 7, 200'000'000), dev(600.0, 7, 250'000'000)};
    const std::vector<lsim::plan::DeviceRx2> rx2(6, lsim::plan::DeviceRx2{869'525'000, 12, 125'000});
    const Causal c(d, {radio(), radio(), radio(), radio(), radio(), radio()},
                   options_dl(1, 200, true), &rx2);
    CHECK_EQ(c.status, 0);
    CHECK_TRUE(!c.busy.empty());

    for (std::size_t k = 1; k < c.busy.size(); ++k) {
        // Croissante **et** disjointe : le début de l'une suit la fin de la précédente.
        CHECK_TRUE(c.busy[k - 1].end_ns <= c.busy[k].start_ns);
    }
    // Aucun intervalle vide ou inversé : une émission refusée n'en laisse pas de trace.
    for (const lsim::plan::Interval& iv : c.busy) {
        CHECK_TRUE(iv.end_ns > iv.start_ns);
    }
}

// --------------------------------------------------------------------------- demi-duplex

void test_descente_acceptee_bloque_une_montante_incompatible() {
    // Une descente acceptée occupe l'émetteur : une montante qui chevauche son intervalle est
    // perdue (`lost_gateway_busy`). Le demi-duplex doit lire **le même état** que le placement —
    // c'est la cohérence que U0.4 garantit structurellement.
    //
    // Montage : une montante très longue (SF12, 200 octets) couvre la fenêtre RX1 d'une montante
    // courte qui la précède dans l'ordre de traitement. La descente de la courte tombe donc
    // **pendant** la longue, qui doit être déclarée perdue.
    const std::vector<EndDeviceSpec> d = {dev(100.0, 7, 0), dev(150.0, 12, 200'000'000)};
    const Causal c(d, {radio(), radio(12)}, options_dl(1, 200));
    CHECK_EQ(c.status, 0);

    CHECK_TRUE(!c.busy.empty());  // la descente de la montante courte a bien été émise
    // La montante longue chevauche cette émission : elle n'est pas reçue.
    CHECK_EQ(c.totals.lost_gateway_busy, std::uint64_t{1});
    CHECK_EQ(c.totals.received, std::uint64_t{1});
}

void test_occupation_imposee_et_descendante_produisent_le_meme_demi_duplex() {
    // Même scène, deux chemins : l'occupation est soit imposée de l'extérieur (`gateway_busy`),
    // soit produite par le planificateur causal. Une montante qui chevauche l'intervalle doit
    // être perdue dans les deux cas — le demi-duplex ne dépend pas de l'origine de l'occupation.
    //
    // Montage : la seconde montante démarre pendant l'émission descendante que la première a
    // déclenchée. Elle est perdue dans le chemin causal ; l'occupation imposée doit produire
    // exactement la même perte.
    const std::vector<EndDeviceSpec> d = {dev(100.0, 7, 0), dev(150.0, 7, 1'100'000'000)};

    const Causal ref(d, {radio(), radio()}, options_dl(1, 200));
    CHECK_EQ(ref.status, 0);
    CHECK_EQ(ref.busy.size(), std::size_t{1});  // la seconde montante, perdue, n'en déclenche pas
    CHECK_EQ(ref.totals.lost_gateway_busy, std::uint64_t{1});

    // (a) Occupation imposée : exactement l'intervalle que le planificateur avait produit.
    std::vector<DeviceStats> s1(2);
    SimulationStats t1{};
    std::vector<Interval> imposee;
    for (const lsim::plan::Interval& iv : ref.busy) imposee.push_back(Interval{iv.start_ns, iv.end_ns});
    CHECK_EQ(static_cast<int>(lsim::sim::simulate_uplinks(d.data(), 2, GatewaySpec{},
                                                          PropagationSpec{}, s1.data(), t1,
                                                          nullptr, nullptr, &imposee)),
             0);

    // (b) Les deux chemins perdent la seconde montante de la même façon.
    CHECK_EQ(t1.lost_gateway_busy, ref.totals.lost_gateway_busy);
}

// --------------------------------------------------------------------------- frontières temporelles

void test_contact_exact_ne_provoque_pas_de_faux_conflit() {
    // Une occupation qui s'achève **exactement** à l'instant de disponibilité suivant ne doit pas
    // provoquer de conflit : l'intervalle est semi-ouvert `[début, fin)`.
    //
    // On impose une émission [1 s, 2 s), puis une montante démarrant à 2 s pile. Elle ne
    // chevauche rien et doit être reçue.
    const std::vector<EndDeviceSpec> d = {dev(100.0, 7, 2 * kS)};
    std::vector<DeviceStats> s(1);
    SimulationStats t{};
    const std::vector<Interval> imposee{Interval{1 * kS, 2 * kS}};
    CHECK_EQ(static_cast<int>(lsim::sim::simulate_uplinks(d.data(), 1, GatewaySpec{},
                                                          PropagationSpec{}, s.data(), t,
                                                          nullptr, nullptr, &imposee)),
             0);
    CHECK_EQ(t.lost_gateway_busy, std::uint64_t{0});
    CHECK_EQ(t.received, std::uint64_t{1});

    // Et une nanoseconde plus tôt, le chevauchement est réel : la trame est perdue.
    std::vector<DeviceStats> s2(1);
    SimulationStats t2{};
    const std::vector<EndDeviceSpec> d2 = {dev(100.0, 7, 2 * kS - 1)};
    CHECK_EQ(static_cast<int>(lsim::sim::simulate_uplinks(d2.data(), 1, GatewaySpec{},
                                                          PropagationSpec{}, s2.data(), t2,
                                                          nullptr, nullptr, &imposee)),
             0);
    // La trame dure bien plus d'une nanoseconde : elle chevauche [1 s, 2 s) par la gauche.
    CHECK_EQ(t2.lost_gateway_busy, std::uint64_t{1});
}

void test_emissions_sur_intervalles_disjointes_sont_toutes_possibles() {
    // Deux émissions séparées par un intervalle libre sont toutes deux possibles. Une borne
    // monotone « occupé jusqu'à » rejetterait la seconde : c'est le piège que le placement par
    // chevauchement réel évite, ici observé du côté du moteur.
    const std::vector<EndDeviceSpec> d = {dev(100.0, 7, 0), dev(200.0, 7, 5 * kS)};
    const Causal c(d, {radio(), radio()}, options_dl(1, 200));
    CHECK_EQ(c.status, 0);
    CHECK_EQ(c.busy.size(), std::size_t{2});
    // Chaque descente s'ouvre exactement 1 s après la **fin de sa montante** (A6) : l'attente
    // est dérivée de la trace, jamais d'une constante recopiée.
    CHECK_EQ(c.busy[0].start_ns, c.trace[0].end_ns + 1 * kS);
    CHECK_EQ(c.busy[1].start_ns, c.trace[1].end_ns + 1 * kS);
    // Intervalle disjoint : la seconde ne commence qu'après la fin de la première.
    CHECK_TRUE(c.busy[0].end_ns <= c.busy[1].start_ns);
    // Aucune montante perdue pour cause d'émission passerelle : les deux descentes sont
    // postérieures aux deux montantes, qui ne les chevauchent donc pas.
    CHECK_EQ(c.totals.lost_gateway_busy, std::uint64_t{0});
}

void test_descente_refusee_ne_reserve_aucune_ressource() {
    // U0.4, exigence 6 : une émission refusée ne réserve **aucune** ressource radio.
    //
    // Deux descentes dont la seconde tombe dans l'émission de la première, sans repli RX2 : la
    // seconde est refusée, et l'occupation restituée ne contient que la première. Surtout, la
    // seconde ne bloque aucune montante — un refus ne doit pas avoir d'effet physique.
    // Deux terminaux dont les fenêtres RX1 tombent dans la même émission : le second écart est
    // inférieur au temps d'antenne descendant, donc la seconde descente est refusée. Sans repli
    // RX2, aucune seconde chance.
    // La seconde montante démarre après la fin de la première (pas de collision), mais sa fenêtre
    // RX1 tombe **dans** l'émission déclenchée par la première : elle est refusée.
    const std::vector<EndDeviceSpec> d = {dev(100.0, 7, 0), dev(200.0, 7, 100'000'000)};
    const Causal c(d, {radio(), radio()}, options_dl(1, 200, /*repli=*/false));
    CHECK_EQ(c.status, 0);

    // Deux montantes reçues, mais **une seule** émission : la seconde fenêtre a été refusée.
    CHECK_EQ(c.totals.received, std::uint64_t{2});
    CHECK_EQ(c.busy.size(), std::size_t{1});
    // L'occupation publiée est exactement l'émission acceptée, à son ouverture.
    CHECK_EQ(c.busy[0].start_ns, c.trace[0].end_ns + 1 * kS);
}

void test_descente_acceptee_reserve_exactement_son_intervalle() {
    // U0.4, exigence 7 : une émission acceptée réserve **exactement** son intervalle réel —
    // `[ouverture, ouverture + temps d'antenne)`, sans garde, sans arrondi, sans prolongement.
    const std::vector<EndDeviceSpec> d = {dev(100.0, 7, 0)};
    const Causal c(d, {radio()}, options_dl(1, 200));
    CHECK_EQ(c.status, 0);
    CHECK_EQ(c.busy.size(), std::size_t{1});

    // `kDataFrameOverheadBytes` est interne à `downlink_plan.cpp` : on reprend sa valeur ici,
    // comme le font déjà les autres suites de tests. Une divergence de la constante cesserait
    // d'être invisible : ce test échouerait.
    constexpr std::uint32_t kTrameDonnees = 13;
    std::int64_t air = 0;
    CHECK_EQ(static_cast<int>(lsim::plan::downlink_airtime_ns(radio(), kTrameDonnees + 200, air)), 0);
    CHECK_EQ(c.busy[0].start_ns, c.trace[0].end_ns + 1 * kS);  // ouverture exacte de RX1
    CHECK_EQ(c.busy[0].end_ns, c.busy[0].start_ns + air);      // temps d'antenne seul
}

// --------------------------------------------------------------------------- absence de descente

void test_scenario_sans_descente_ne_cree_aucune_occupation() {
    // Exigence transverse : les scénarios sans descente doivent rester inchangés. Aucune
    // occupation, aucune perte pour cause d'émission passerelle.
    const std::vector<EndDeviceSpec> d = {dev(100.0, 7, 0), dev(200.0, 7, 500'000'000),
                                          dev(300.0, 7, 1 * kS)};
    lsim::plan::PlanOptions o;
    o.confirmed_uplinks = false;
    o.downlink_every = 0;
    o.gateway_tx_power_dbm = 27.0;
    const Causal c(d, {radio(), radio(), radio()}, o);
    CHECK_EQ(c.status, 0);
    CHECK_TRUE(c.busy.empty());
    CHECK_EQ(c.totals.lost_gateway_busy, std::uint64_t{0});
    CHECK_EQ(c.totals.received, std::uint64_t{3});
}

}  // namespace

void run_occupation_radio_tests() {
    test_occupation_restituee_est_croissante_et_disjointe();
    test_descente_acceptee_bloque_une_montante_incompatible();
    test_occupation_imposee_et_descendante_produisent_le_meme_demi_duplex();
    test_contact_exact_ne_provoque_pas_de_faux_conflit();
    test_emissions_sur_intervalles_disjointes_sont_toutes_possibles();
    test_descente_refusee_ne_reserve_aucune_ressource();
    test_descente_acceptee_reserve_exactement_son_intervalle();
    test_scenario_sans_descente_ne_cree_aucune_occupation();
}
