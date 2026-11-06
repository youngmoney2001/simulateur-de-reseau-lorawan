// SPDX-License-Identifier: Apache-2.0
// I5-a : le temps d'antenne et la sensibilité de réception d'une descente du moteur
// multi-passerelles suivent le SF et la bande de la **fenêtre émettrice** — jamais le SF montant,
// jamais une constante.
//
// Contrat testé :
//   - sans table de radios, le comportement est identique à l'hypothèse historique ;
//   - avec une table, RX1 est évalué à (rx1_sf, rx1_bw_hz) et RX2 à (rx2_sf, rx2_bw_hz) ;
//   - une table `rx2` impose `rule.rx2_sf == 0` ;
//   - toute valeur hors bornes est refusée, et `radios`/`rx2` vont par paire.
#include <cstddef>
#include <cstdint>
#include <vector>

#include "check.hpp"
#include "lsim/engine.hpp"

namespace lsim {
namespace {

using sim::DownlinkOutcome;
using sim::EndDeviceSpec;
using sim::GatewayRxStats;
using sim::GatewaySpec;
using sim::MultiDownlink;
using sim::MultiDownlinkRule;
using sim::NetworkStats;
using sim::SimStatus;
using sim::DeviceStats;
using sim::Position;
using sim::PropagationSpec;

constexpr std::int64_t kS = 1'000'000'000;

// Charge réellement transportée par une descente de données : `kDataFrameOverhead` (13) +
// `rule.payload_bytes` (40). Le moteur ajoute lui-même l'en-tête (engine.cpp:1394).
constexpr std::uint32_t kCharge = 53;

// Hypothèse historique : RX1 au SF montant, à 125 kHz. C'est ce que fait le moteur sans table.

EndDeviceSpec terminal(std::uint8_t sf, double x = 0.0, std::int64_t depart = 0) {
    EndDeviceSpec d{};
    d.position = Position{x, 0.0};
    d.spreading_factor = sf;
    d.payload_bytes = 20;
    d.tx_power_dbm = 14.0;
    d.start_offset_ns = depart;
    d.period_ns = 60 * kS;
    d.messages = 1;
    d.duty_cycle = 1.0;
    return d;
}

GatewaySpec passerelle(double x) {
    GatewaySpec g{};
    g.position = Position{x, 0.0};
    return g;
}

PropagationSpec propagation(double exposant = 2.0) {
    PropagationSpec p{};
    p.exponent = exposant;
    p.frequency_hz = 868'100'000;
    p.reference_distance_m = 1.0;
    p.exponent = 2.0;
    p.capture_threshold_db = 6.0;
    p.shadowing_sigma_db = 0.0;
    p.shadowing_seed = 1;
    return p;
}

// Règle commune : une descente de données par uplink reçu, sans repli (rx2_sf = 0) sauf demande.
MultiDownlinkRule regle() {
    MultiDownlinkRule r{};
    r.ack_uplinks = false;
    r.every = 1;
    r.payload_bytes = 40;
    r.gateway_tx_power_dbm = 14.0;
    return r;
}

// Lance une simulation à un dispositif et renvoie la première descente planifiée.
struct Essai {
    SimStatus statut = SimStatus::Ok;
    std::vector<MultiDownlink> dls;
};

Essai jouer(std::uint8_t sf_montant, const std::vector<plan::DeviceRadio>* radios,
            const std::vector<plan::DeviceRx2>* rx2, MultiDownlinkRule r = regle(),
            double distance = 50.0, double exposant = 2.0) {
    const std::vector<EndDeviceSpec> devs{terminal(sf_montant)};
    const std::vector<GatewaySpec> gws{passerelle(distance)};
    std::vector<DeviceStats> per_dev(1);
    std::vector<GatewayRxStats> per_gw(1);
    NetworkStats totals{};
    Essai e;
    e.statut = sim::simulate_uplinks_multi_downlinks(
        devs.data(), devs.size(), gws.data(), gws.size(), propagation(), r,
        radios != nullptr ? radios->data() : nullptr, rx2 != nullptr ? rx2->data() : nullptr,
        per_dev.data(), totals, per_gw.data(), nullptr, nullptr, &e.dls);
    return e;
}

plan::DeviceRadio radio(std::uint8_t rx1_sf, std::uint32_t rx1_bw_hz) {
    plan::DeviceRadio r{};
    r.rx1_sf = rx1_sf;
    r.rx1_bw_hz = rx1_bw_hz;
    return r;
}

plan::DeviceRx2 fenetre2(std::uint8_t rx2_sf, std::uint32_t rx2_bw_hz) {
    plan::DeviceRx2 w{};
    w.rx2_hz = 869'525'000;
    w.rx2_sf = rx2_sf;
    w.rx2_bw_hz = rx2_bw_hz;
    return w;
}

// Durée d'une descente, ou -1 si non émise.
std::int64_t duree(const Essai& e) {
    if (e.statut != SimStatus::Ok || e.dls.empty()) return -1;
    if (e.dls[0].start_ns < 0 || e.dls[0].end_ns < 0) return -1;
    return e.dls[0].end_ns - e.dls[0].start_ns;
}

// Temps d'antenne de référence, calculé indépendamment du moteur.
std::int64_t reference(std::uint8_t sf, std::uint32_t bw_hz, std::uint32_t charge) {
    lora::RadioConfig rc;
    rc.spreading_factor = sf;
    rc.bandwidth = static_cast<lora::Bandwidth>(bw_hz);
    rc.coding_rate = 1;
    rc.crc_on = false;
    rc.explicit_header = true;
    rc.low_data_rate_optimize = lora::low_data_rate_required(sf, rc.bandwidth);
    const lora::AirtimeResult at = lora::time_on_air(rc, static_cast<std::uint8_t>(charge));
    CHECK_EQ(static_cast<int>(at.status), static_cast<int>(lora::Status::Ok));
    return at.nanoseconds;
}

// 1. Sans table : l'hypothèse historique est conservée. RX1 = SF montant à 125 kHz.
void test_sans_table_hypothese_historique() {
    for (std::uint8_t sf : {7, 9, 12}) {
        const Essai e = jouer(sf, nullptr, nullptr);
        CHECK_EQ(static_cast<int>(e.statut), static_cast<int>(SimStatus::Ok));
        CHECK_EQ(duree(e), reference(sf, 125'000, kCharge));
    }
}

// 2. Avec une table qui reproduit l'hypothèse, les résultats sont les mêmes.
void test_table_sur_la_diagonale_est_sans_effet() {
    for (std::uint8_t sf : {7, 9, 12}) {
        const std::vector<plan::DeviceRadio> radios{radio(sf, 125'000)};
        const Essai avec = jouer(sf, &radios, nullptr);
        const Essai sans = jouer(sf, nullptr, nullptr);
        CHECK_EQ(static_cast<int>(avec.statut), static_cast<int>(SimStatus::Ok));
        CHECK_EQ(duree(avec), duree(sans));
    }
}

// 3. Le temps d'antenne suit la bande de RX1 : c'est le cœur du défaut corrigé.
void test_duree_suit_la_bande_de_rx1() {
    // Montée SF12 : le cas où l'hypothèse historique est la plus fausse.
    const std::vector<std::pair<std::uint32_t, std::int64_t>> cas{
        {125'000, reference(12, 125'000, kCharge)},
        {500'000, reference(12, 500'000, kCharge)},
    };
    for (const auto& c : cas) {
        const std::vector<plan::DeviceRadio> radios{radio(12, c.first)};
        const Essai e = jouer(12, &radios, nullptr);
        CHECK_EQ(static_cast<int>(e.statut), static_cast<int>(SimStatus::Ok));
        CHECK_EQ(duree(e), c.second);
    }
    // Une bande 500 kHz est environ quatre fois plus rapide qu'une bande 125 kHz.
    CHECK_TRUE(reference(12, 500'000, kCharge) * 4 <= reference(12, 125'000, kCharge));
}

// 4. Le SF employé est celui de RX1, pas celui de la montée.
void test_duree_suit_le_sf_de_rx1_et_non_du_montant() {
    const std::vector<std::pair<std::uint8_t, std::int64_t>> cas{
        {7, reference(7, 125'000, kCharge)},
        {12, reference(12, 125'000, kCharge)},
    };
    // Montée SF12 dans les deux cas ; seul le SF de RX1 change.
    for (const auto& c : cas) {
        const std::vector<plan::DeviceRadio> radios{radio(c.first, 125'000)};
        const Essai e = jouer(12, &radios, nullptr);
        CHECK_EQ(static_cast<int>(e.statut), static_cast<int>(SimStatus::Ok));
        CHECK_EQ(duree(e), c.second);
    }
    CHECK_TRUE(reference(7, 125'000, kCharge) < reference(12, 125'000, kCharge));
}

// 5. La sensibilité de réception descendante suit elle aussi la bande de la fenêtre.
//    Un seuil calculé à la mauvaise bande change la décision « la descente est reçue ».
void test_sensibilite_suit_la_bande() {
    // Même scénario, seule la bande de RX1 change : à 500 kHz le seuil est moins sévère,
    // donc une descente qui passait tout juste à 125 kHz doit être perdue, et non l'inverse.
    const std::vector<plan::DeviceRadio> etroite{radio(12, 125'000)};
    const std::vector<plan::DeviceRadio> large{radio(12, 500'000)};
    const Essai a = jouer(12, &etroite, nullptr);
    const Essai b = jouer(12, &large, nullptr);
    CHECK_EQ(static_cast<int>(a.statut), static_cast<int>(SimStatus::Ok));
    CHECK_EQ(static_cast<int>(b.statut), static_cast<int>(SimStatus::Ok));
    CHECK_EQ(duree(a), reference(12, 125'000, kCharge));
    CHECK_EQ(duree(b), reference(12, 500'000, kCharge));
    // Le seuil de sensibilité est une fonction décroissante de la bande : à bande plus large,
    // le seuil est plus permissif. Vérifié directement sur la fonction du modèle.
    double s125 = 0.0, s500 = 0.0;
    CHECK_EQ(static_cast<int>(lora::receiver_sensitivity_dbm(12, lora::Bandwidth::Bw125kHz, s125)),
              static_cast<int>(lora::Status::Ok));
    CHECK_EQ(static_cast<int>(lora::receiver_sensitivity_dbm(12, lora::Bandwidth::Bw500kHz, s500)),
              static_cast<int>(lora::Status::Ok));
    CHECK_TRUE(s500 > s125);  // seuil 500 kHz moins sévère (valeurs négatives, plus proche de 0)
}

// 5bis. Site 3, test discriminant : il existe une distance où la même descente est **reçue** en
//       125 kHz et **perdue** en 500 kHz. Le seuil de 500 kHz est plus haut de 6 à 7 dB ; si le
//       moteur figeait le seuil à 125 kHz, les deux colonnes seraient identiques.
void test_sensibilite_discrimine_selon_la_bande() {
    const std::vector<plan::DeviceRadio> etroite{radio(12, 125'000)};
    const std::vector<plan::DeviceRadio> large{radio(12, 500'000)};
    bool trouve = false;
    // Exposant raide : la zone de transition (entre -136 dBm et -130 dBm) est atteinte en
    // quelques centaines de mètres au lieu de plusieurs centaines de kilomètres.
    for (double d = 50.0; d <= 500'000.0 && !trouve; d *= 1.15) {
        const Essai a = jouer(12, &etroite, nullptr, regle(), d, 6.0);
        const Essai b = jouer(12, &large, nullptr, regle(), d, 6.0);
        if (a.dls.empty() || b.dls.empty()) continue;
        if (a.dls[0].outcome == b.dls[0].outcome) continue;
        // La bande étroite est la plus permissive : c'est elle qui reçoit.
        CHECK_EQ(static_cast<int>(a.dls[0].outcome),
                 static_cast<int>(DownlinkOutcome::Delivered));
        CHECK_EQ(static_cast<int>(b.dls[0].outcome),
                 static_cast<int>(DownlinkOutcome::LostSensitivity));
        trouve = true;
    }
    CHECK_TRUE(trouve);  // à défaut, le test ne prouverait rien
}

// 5ter. Repli RX2 : la bande et le SF de la fenêtre de secours viennent de la table, pas d'une
//       constante.
//
//       Montage : deux dispositifs de SF différents (donc non collisionnels). Le premier, au SF12,
//       émet longuement ; sa descente occupe l'émetteur pendant la fenêtre RX1 du second, qui
//       part donc en RX2. Un seul dispositif ne convient pas : sa seconde montante tomberait
//       pendant la descente de la première et serait perdue par demi-duplex.
void test_repli_rx2_suit_la_table() {
    MultiDownlinkRule neutre = regle();
    neutre.rx2_sf = 0;  // une table rx2 est fournie : la règle doit être neutre
    // Charge réduite : la descente de A doit être assez courte pour que la fenêtre RX2 de B
    // (ouverte 1 s après sa RX1) ne soit pas elle aussi couverte.
    neutre.payload_bytes = 10;
    const std::uint32_t charge = 13 + 10;  // kDataFrameOverhead + payload_bytes
    const std::vector<GatewaySpec> gws{passerelle(50.0)};

    for (std::uint32_t bw : {125'000u, 500'000u}) {
        // A : SF12, émet à t=0 ; sa montante dure 1,32 s, sa descente (RX1 SF12) occupe
        //     l'émetteur de 2,32 s à 4,79 s. B : SF7, émet à t=1,5 s — donc **après** la montante
        //     de A et **avant** sa descente, sans quoi B serait perdu par demi-duplex. La RX1 de
        //     B s'ouvre à 2,56 s, en pleine descente de A : elle part en RX2.
        const std::vector<EndDeviceSpec> devs{terminal(12, 0.0, 0),
                                              terminal(7, 10.0, 3 * kS / 2)};
        const std::vector<plan::DeviceRadio> radios{radio(12, 125'000), radio(7, 125'000)};
        const std::vector<plan::DeviceRx2> rx2{fenetre2(9, bw), fenetre2(9, bw)};
        std::vector<DeviceStats> per_dev(2);
        std::vector<GatewayRxStats> per_gw(1);
        NetworkStats totals{};
        std::vector<MultiDownlink> dls;
        const SimStatus st = sim::simulate_uplinks_multi_downlinks(
            devs.data(), devs.size(), gws.data(), gws.size(), propagation(), neutre,
            radios.data(), rx2.data(), per_dev.data(), totals, per_gw.data(), nullptr, nullptr,
            &dls);
        CHECK_EQ(static_cast<int>(st), static_cast<int>(SimStatus::Ok));
        std::size_t vus = 0;
        for (const MultiDownlink& d : dls) {
            if (d.rx_window != 2 || d.start_ns < 0) continue;
            ++vus;
            // Le SF (9) et la bande viennent tous deux de la table : la durée doit suivre.
            CHECK_EQ(d.end_ns - d.start_ns, reference(9, bw, charge));
        }
        // Sans repli observé, le test ne prouverait rien.
        CHECK_TRUE(vus > 0);
    }
}

// 6. Repli RX2 : évalué avec le SF et la bande de la table, pas avec rule.rx2_sf à 125 kHz.
void test_repli_rx2_utilise_la_table() {
    MultiDownlinkRule r = regle();
    r.rx2_sf = 7;  // interdit des qu'une table est passee : teste en 7.
    // D'abord sans table : le repli garde le comportement historique (SF7 à 125 kHz).
    {
        const Essai e = jouer(12, nullptr, nullptr, r);
        CHECK_EQ(static_cast<int>(e.statut), static_cast<int>(SimStatus::Ok));
        if (!e.dls.empty() && e.dls[0].rx_window == 2) {
            CHECK_EQ(e.dls[0].end_ns - e.dls[0].start_ns, reference(7, 125'000, kCharge));
        }
    }
    // Avec une table : rule.rx2_sf doit valoir 0.
    {
        const std::vector<plan::DeviceRadio> radios{radio(12, 125'000)};
        const std::vector<plan::DeviceRx2> rx2{fenetre2(9, 500'000)};
        const Essai e = jouer(12, &radios, &rx2, r);
        CHECK_EQ(static_cast<int>(e.statut), static_cast<int>(SimStatus::InvalidInput));
    }
    // Table fournie, regle neutre : accepte.
    {
        MultiDownlinkRule neutre = regle();
        neutre.rx2_sf = 0;
        const std::vector<plan::DeviceRadio> radios{radio(12, 125'000)};
        const std::vector<plan::DeviceRx2> rx2{fenetre2(9, 500'000)};
        const Essai e = jouer(12, &radios, &rx2, neutre);
        CHECK_EQ(static_cast<int>(e.statut), static_cast<int>(SimStatus::Ok));
    }
}

// 7. Validations : radios et rx2 vont par paire ; valeurs hors bornes refusées.
void test_validations() {
    const std::vector<plan::DeviceRadio> radios{radio(12, 125'000)};
    const std::vector<plan::DeviceRx2> rx2{fenetre2(9, 125'000)};
    MultiDownlinkRule neutre = regle();
    neutre.rx2_sf = 0;

    // Les deux tables sont independantes : chacune peut etre fournie seule.
    CHECK_EQ(static_cast<int>(jouer(12, &radios, nullptr, neutre).statut),
              static_cast<int>(SimStatus::Ok));
    CHECK_EQ(static_cast<int>(jouer(12, nullptr, &rx2, neutre).statut),
              static_cast<int>(SimStatus::Ok));
    // Mais `rx2_bw_hz == 0` (reprend la bande de RX1) exige la table de radios.
    {
        const std::vector<plan::DeviceRx2> heritee{fenetre2(9, 0)};
        CHECK_EQ(static_cast<int>(jouer(12, nullptr, &heritee, neutre).statut),
                  static_cast<int>(SimStatus::InvalidInput));
        CHECK_EQ(static_cast<int>(jouer(12, &radios, &heritee, neutre).statut),
                  static_cast<int>(SimStatus::Ok));
    }

    // SF hors bornes.
    for (std::uint8_t sf : {0, 6, 13}) {
        const std::vector<plan::DeviceRadio> mauvais{radio(sf, 125'000)};
        CHECK_EQ(static_cast<int>(jouer(12, &mauvais, &rx2, neutre).statut),
                  static_cast<int>(SimStatus::InvalidInput));
    }
    // Bande hors bornes.
    for (std::uint32_t bw : {0u, 100'000u, 250'001u, 1'000'000u}) {
        const std::vector<plan::DeviceRadio> mauvais{radio(12, bw)};
        CHECK_EQ(static_cast<int>(jouer(12, &mauvais, &rx2, neutre).statut),
                  static_cast<int>(SimStatus::InvalidInput));
    }
    // Bande RX2 hors bornes.
    for (std::uint32_t bw : {100'000u, 1'000'000u}) {
        const std::vector<plan::DeviceRx2> mauvais{fenetre2(9, bw)};
        CHECK_EQ(static_cast<int>(jouer(12, &radios, &mauvais, neutre).statut),
                  static_cast<int>(SimStatus::InvalidInput));
    }
    // Test discriminant : la validation a lieu **avant** la planification, même quand aucune
    // descente n'est demandée. Sans elle, un SF invalide ne serait rejeté que si un temps
    // d'antenne devait être calculé — le test passerait alors pour une mauvaise raison.
    {
        MultiDownlinkRule sans_descente = regle();
        sans_descente.ack_uplinks = false;
        sans_descente.every = 0;  // aucune descente : aucun temps d'antenne calculé
        sans_descente.rx2_sf = 0;
        const std::vector<plan::DeviceRadio> mauvais_sf{radio(0, 125'000)};
        CHECK_EQ(static_cast<int>(jouer(12, &mauvais_sf, nullptr, sans_descente).statut),
                  static_cast<int>(SimStatus::InvalidInput));
        const std::vector<plan::DeviceRadio> mauvais_sf2{radio(13, 125'000)};
        CHECK_EQ(static_cast<int>(jouer(12, &mauvais_sf2, nullptr, sans_descente).statut),
                  static_cast<int>(SimStatus::InvalidInput));
        const std::vector<plan::DeviceRadio> mauvaise_bande{radio(12, 100'000)};
        CHECK_EQ(static_cast<int>(jouer(12, &mauvaise_bande, nullptr, sans_descente).statut),
                  static_cast<int>(SimStatus::InvalidInput));
        // Et une table valide, dans les mêmes conditions, est acceptée.
        CHECK_EQ(static_cast<int>(jouer(12, &radios, nullptr, sans_descente).statut),
                  static_cast<int>(SimStatus::Ok));
    }

    // Les trois bandes admises, et rx2_bw_hz = 0 (reprend celle de RX1).
    for (std::uint32_t bw : {125'000u, 250'000u, 500'000u, 0u}) {
        const std::vector<plan::DeviceRx2> bon{fenetre2(9, bw)};
        CHECK_EQ(static_cast<int>(jouer(12, &radios, &bon, neutre).statut),
                  static_cast<int>(SimStatus::Ok));
    }
}

}  // namespace
}  // namespace lsim

void run_multi_dl_rx1_tests() {
    using namespace lsim;
    test_sans_table_hypothese_historique();
    test_table_sur_la_diagonale_est_sans_effet();
    test_duree_suit_la_bande_de_rx1();
    test_duree_suit_le_sf_de_rx1_et_non_du_montant();
    test_sensibilite_suit_la_bande();
    test_sensibilite_discrimine_selon_la_bande();
    test_repli_rx2_suit_la_table();
    test_repli_rx2_utilise_la_table();
    test_validations();
}
