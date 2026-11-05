// SPDX-License-Identifier: Apache-2.0
// Ordonnanceur radio (`lsim::radio::RadioScheduler`) : règle A6 (TS001-1.0.4 §3.3.5).
//
// Ces tests portent sur la règle elle-même, isolée de tout moteur : mêmes entrées, même occupation
// initiale, mêmes fenêtres ⇒ mêmes intervalles et mêmes verdicts. Ils sont volontairement
// discriminants : chacun échoue si l'on réintroduit un décalage intra-fenêtre, ou si l'on
// remplace le chevauchement réel par une borne de fin.
#include <cstdint>
#include <vector>

#include "check.hpp"
#include "lsim/radio_scheduler.hpp"

namespace {

using lsim::radio::PlacementVerdict;
using lsim::radio::RadioScheduler;
using lsim::radio::Interval;
using lsim::radio::SimTime;

constexpr SimTime kS = 1'000'000'000;

// Temps d'antenne réalistes : 20 octets en SF7/125 kHz et en SF12/125 kHz.
constexpr SimTime kAirSf7 = 56'576'000;
constexpr SimTime kAirSf12 = 1'319'000'000;  // dépasse la fenêtre RX1 d'une seconde

// ---------------------------------------------------------------- cas nominal

void test_rx1_libre_est_placee_exactement_a_l_ouverture() {
    RadioScheduler sch;
    const auto p = sch.place(10 * kS, kAirSf7, 11 * kS, kAirSf12, true);
    CHECK_EQ(static_cast<int>(p.verdict), static_cast<int>(PlacementVerdict::PlacedRx1));
    CHECK_EQ(p.start_ns, 10 * kS);
    CHECK_EQ(p.t_open_ns, 10 * kS);
    CHECK_EQ(sch.occupancy().size(), std::size_t{1});
    CHECK_EQ(sch.occupancy()[0].start, 10 * kS);
    CHECK_EQ(sch.occupancy()[0].end, 10 * kS + kAirSf7);
}

// ---------------------------------------------------------------- repli RX2

void test_repli_rx2_exactement_a_son_ouverture() {
    RadioScheduler sch;
    // Une émission occupe l'ouverture de RX1 : elle se termine après.
    sch.seed({Interval{10 * kS, 10 * kS + kAirSf7}});
    const auto p = sch.place(10 * kS, kAirSf7, 11 * kS, kAirSf12, true);
    CHECK_EQ(static_cast<int>(p.verdict), static_cast<int>(PlacementVerdict::PlacedRx2));
    CHECK_EQ(p.start_ns, 11 * kS);  // ouverture de RX2, pas un instant décalé depuis RX1
    CHECK_EQ(p.t_open_ns, 11 * kS);
}

void test_repli_rx2_refuse_si_non_demande() {
    RadioScheduler sch;
    sch.seed({Interval{10 * kS, 10 * kS + kAirSf7}});
    // RX2 est libre, mais le dispositif n'en a pas : aucun repli.
    const auto p = sch.place(10 * kS, kAirSf7, 11 * kS, kAirSf12, false);
    CHECK_EQ(static_cast<int>(p.verdict), static_cast<int>(PlacementVerdict::NotPlaced));
    CHECK_EQ(p.start_ns, SimTime{-1});
    CHECK_EQ(sch.occupancy().size(), std::size_t{1});  // aucune occupation ajoutée
}

// ------------------------------------------------- A6 : aucun décalage (le test central)

void test_aucun_decalage_intra_fenetre() {
    // Une émission se termine peu après l'ouverture de RX1. Une règle à décalage placerait la
    // descente à la fin de cette émission. A6 l'interdit : la descente part à l'ouverture de RX2,
    // à un instant strictement postérieur à cette fin.
    RadioScheduler sch;
    const SimTime fin_occupation = 10 * kS + 10'000'000;  // 10 ms après l'ouverture de RX1
    sch.seed({Interval{10 * kS, fin_occupation}});
    const auto p = sch.place(10 * kS, kAirSf7, 11 * kS, kAirSf12, true);
    CHECK_EQ(static_cast<int>(p.verdict), static_cast<int>(PlacementVerdict::PlacedRx2));
    CHECK_EQ(p.start_ns, 11 * kS);
    CHECK_TRUE(p.start_ns > fin_occupation);  // aucun rattrapage juste après l'occupation
}

void test_aucune_fenetre_disponible_rien_nest_emis() {
    RadioScheduler sch;
    // RX1 et RX2 toutes deux couvertes par une émission assez longue.
    sch.seed({Interval{9 * kS, 12 * kS}});
    const auto p = sch.place(10 * kS, kAirSf7, 11 * kS, kAirSf12, true);
    CHECK_EQ(static_cast<int>(p.verdict), static_cast<int>(PlacementVerdict::NotPlaced));
    CHECK_EQ(p.start_ns, SimTime{-1});
    CHECK_EQ(sch.occupancy().size(), std::size_t{1});  // toujours l'occupation initiale
    // t_open_ns situe la dernière fenêtre examinée : c'est dont dépend la boucle fermée.
    CHECK_EQ(p.t_open_ns, 11 * kS);
}

// ------------------------------------------- chevauchement réel, et non borne de fin

void test_fenetre_libre_entre_deux_emissions_est_acceptee() {
    // Deux émissions encadrent une fenêtre libre. Une règle « fin maximale des émissions
    // planifiées » refuserait cette fenêtre ; A6 l'accepte à l'instant exact.
    RadioScheduler sch;
    sch.seed({Interval{1 * kS, 2 * kS}, Interval{20 * kS, 21 * kS}});
    const SimTime ouverture = 10 * kS;
    const auto p = sch.place(ouverture, kAirSf7, ouverture + kS, kAirSf12, true);
    CHECK_EQ(static_cast<int>(p.verdict), static_cast<int>(PlacementVerdict::PlacedRx1));
    CHECK_EQ(p.start_ns, ouverture);
}

void test_chevauchement_partiel_en_fin_de_fenetre_est_refuse() {
    // L'émission en place finit juste après l'ouverture mais avant la fin de la descente :
    // il y a chevauchement réel, la fenêtre est refusée.
    RadioScheduler sch;
    const SimTime ouverture = 10 * kS;
    sch.seed({Interval{ouverture - kS, ouverture + kAirSf7 - 1}});
    const auto p = sch.place(ouverture, kAirSf7, ouverture + kS, kAirSf12, true);
    CHECK_EQ(static_cast<int>(p.verdict), static_cast<int>(PlacementVerdict::PlacedRx2));
    CHECK_EQ(p.start_ns, ouverture + kS);
}

// ---------------------------------------------------------------- occupation

void test_occupation_croissante_et_disjointe() {
    RadioScheduler sch;
    // Descentes dont les ouvertures ne sont pas dans l'ordre croissant des instants de dépôt.
    sch.place(30 * kS, kAirSf7, 31 * kS, kAirSf12, true);
    sch.place(10 * kS, kAirSf7, 11 * kS, kAirSf12, true);
    sch.place(20 * kS, kAirSf7, 21 * kS, kAirSf12, true);
    const std::vector<Interval>& oc = sch.occupancy();
    CHECK_EQ(oc.size(), std::size_t{3});
    for (std::size_t i = 0; i + 1 < oc.size(); ++i) {
        CHECK_TRUE(oc[i].end <= oc[i + 1].start);  // croissante et disjointe
    }
    CHECK_EQ(oc[0].start, 10 * kS);
    CHECK_EQ(oc[1].start, 20 * kS);
    CHECK_EQ(oc[2].start, 30 * kS);
}

void test_emission_debordant_la_fenetre_est_placee() {
    // A6 contraint le **départ**, pas la fin : une descente SF12 plus longue que la fenêtre est
    // émise en entier et occupe l'émetteur au-delà de la fermeture.
    RadioScheduler sch;
    const SimTime ouverture = 10 * kS;
    const auto p = sch.place(ouverture, kAirSf12, ouverture + kS, kAirSf12, true);
    CHECK_EQ(static_cast<int>(p.verdict), static_cast<int>(PlacementVerdict::PlacedRx1));
    CHECK_EQ(p.start_ns, ouverture);
    CHECK_EQ(sch.occupancy()[0].end, ouverture + kAirSf12);
    CHECK_TRUE(sch.occupancy()[0].end > ouverture + 1 * kS);  // dépasse la fenêtre
}

void test_place_at_fenetre_libre_entre_deux_emissions() {
    // Même scène que ci-dessus, mais par `place_at` — l'entrée employée par le planificateur
    // (jalon U0.3), qui examine une fenêtre à la fois et garde l'ordonnancement pour lui.
    //
    // Deux émissions encadrent une fenêtre libre : [1 s, 2 s) et [20 s, 21 s). Une borne de fin
    // — « occupé jusqu'à » la fin de la dernière émission inscrite — refuserait l'ouverture à
    // 10 s, puisque 21 s la dépasse. Le chevauchement réel l'accepte : rien n'émet à 10 s.
    //
    // Ce test est la raison d'être de l'occupation sous forme de liste d'intervalles, et non d'un
    // scalaire : c'est lui qui échoue si l'on remplace le chevauchement par une borne.
    RadioScheduler sch;
    sch.seed({Interval{1 * kS, 2 * kS}, Interval{20 * kS, 21 * kS}});
    CHECK_TRUE(sch.place_at(10 * kS, kAirSf7));
    CHECK_EQ(sch.occupancy().size(), std::size_t{3});
    CHECK_EQ(sch.occupancy()[1].start, 10 * kS);  // insérée à sa place, liste croissante

    // Et la fenêtre réellement masquée, elle, reste refusée : la règle n'est pas assouplie.
    CHECK_TRUE(!sch.place_at(21 * kS - 1, kAirSf7));
    CHECK_EQ(sch.occupancy().size(), std::size_t{3});  // refus : aucune occupation
}

void test_place_at_ouvertures_dans_le_desordre() {
    // `place_at` est publique : rien ne garantit que les ouvertures arrivent dans l'ordre. Une
    // borne de fin ne s'en sortirait pas ; le chevauchement réel, si.
    RadioScheduler sch;
    sch.seed({Interval{10 * kS, 11 * kS}});
    // Placée **avant** l'émission déjà inscrite : aucun chevauchement, donc acceptée.
    CHECK_TRUE(sch.place_at(5 * kS, kAirSf7));
    CHECK_EQ(sch.occupancy().size(), std::size_t{2});
    CHECK_EQ(sch.occupancy()[0].start, 5 * kS);   // insérée avant : liste maintenue croissante
    CHECK_EQ(sch.occupancy()[1].start, 10 * kS);
    // Une fenêtre entre les deux reste libre.
    CHECK_TRUE(sch.place_at(7 * kS, kAirSf7));
    CHECK_EQ(sch.occupancy().size(), std::size_t{3});
    CHECK_EQ(sch.occupancy()[1].start, 7 * kS);
}

void test_transmitting_chevauchement_reel() {
    RadioScheduler sch;
    sch.seed({Interval{10 * kS, 11 * kS}});
    CHECK_TRUE(sch.transmitting(10 * kS + 1, 10 * kS + 2));   // strictement à l'intérieur
    CHECK_TRUE(sch.transmitting(9 * kS, 10 * kS + 1));        // chevauchement par la gauche
    CHECK_TRUE(sch.transmitting(10 * kS + 1, 12 * kS));       // chevauchement par la droite
    CHECK_TRUE(!sch.transmitting(9 * kS, 10 * kS));           // contact exact : pas de chevauchement
    CHECK_TRUE(!sch.transmitting(11 * kS, 12 * kS));          // contact exact : pas de chevauchement
    CHECK_TRUE(!sch.transmitting(12 * kS, 13 * kS));          // entièrement après
}

}  // namespace

void run_radio_scheduler_tests() {
    test_rx1_libre_est_placee_exactement_a_l_ouverture();
    test_repli_rx2_exactement_a_son_ouverture();
    test_repli_rx2_refuse_si_non_demande();
    test_aucun_decalage_intra_fenetre();
    test_aucune_fenetre_disponible_rien_nest_emis();
    test_fenetre_libre_entre_deux_emissions_est_acceptee();
    test_chevauchement_partiel_en_fin_de_fenetre_est_refuse();
    test_occupation_croissante_et_disjointe();
    test_emission_debordant_la_fenetre_est_placee();
    test_transmitting_chevauchement_reel();
    test_place_at_fenetre_libre_entre_deux_emissions();
    test_place_at_ouvertures_dans_le_desordre();
}
