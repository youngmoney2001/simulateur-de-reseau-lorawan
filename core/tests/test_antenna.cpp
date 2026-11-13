// SPDX-License-Identifier: Apache-2.0
// Antennes : diagramme de rayonnement horizontal et couverture qui en découle.
#include <cmath>
#include <vector>

#include "check.hpp"
#include "lsim/antenna.hpp"
#include "lsim/environment.hpp"

namespace {

using lsim::antenna::gain_dbi;
using lsim::antenna::gain_offset_db;
using lsim::antenna::Kind;
using lsim::antenna::Pattern;
using lsim::antenna::validate_pattern;
using lsim::radio::LogDistanceModel;

// Borne de comparaison : les formules sont exactes, la tolérance ne sert qu'à absorber
// l'arrondi des degrés en radians en cascade.
constexpr double kTol = 1e-9;

LogDistanceModel model() {
    LogDistanceModel m;
    m.frequency_hz = 868.1e6;
    m.reference_distance_m = 1.0;
    m.exponent = 2.7;
    return m;
}

// Sommet du lobe : offset nul sur l'axe, quel que soit le type.
void test_boresight_is_at_peak_gain() {
    const Pattern types[] = {
        Pattern{Kind::Omnidirectional, 3.0, 90.0, 0.0, 20.0},
        Pattern{Kind::Unidirectional, 3.0, 90.0, 0.0, 20.0},
        Pattern{Kind::Bidirectional, 3.0, 90.0, 0.0, 20.0},
        Pattern{Kind::Sector, 3.0, 90.0, 0.0, 20.0},
    };
    for (const Pattern& p : types) {
        CHECK_NEAR(gain_offset_db(p, 0.0), 0.0, kTol);
        CHECK_NEAR(gain_dbi(p, 0.0), 3.0, kTol);
    }
    // Un lobe pointé ailleurs déplace le sommet, il ne l'aplatit pas.
    const Pattern east{Kind::Unidirectional, 6.0, 60.0, 90.0, 25.0};
    CHECK_NEAR(gain_offset_db(east, 90.0), 0.0, kTol);
    CHECK_NEAR(gain_dbi(east, 90.0), 6.0, kTol);
}

// −3 dB à mi-ouverture : la convention qui fixe la pente de 12 (12 × 0,25 = 3).
void test_minus_3db_at_half_beamwidth() {
    const double widths[] = {30.0, 60.0, 90.0, 120.0};
    for (const double w : widths) {
        const Pattern p{Kind::Unidirectional, 0.0, w, 0.0, 40.0};
        CHECK_NEAR(gain_offset_db(p, 0.5 * w), -3.0, kTol);
        CHECK_NEAR(gain_offset_db(p, -0.5 * w), -3.0, kTol);
    }
    // Ouverture entière : 12 dB, soit quatre fois le point à −3 dB (pente quadratique).
    const Pattern p{Kind::Unidirectional, 0.0, 90.0, 0.0, 40.0};
    CHECK_NEAR(gain_offset_db(p, 90.0), -12.0, kTol);
    CHECK_NEAR(gain_offset_db(p, 45.0), -3.0, kTol);
}

// Le plancher arrière borne la décroissance : au-delà, le diagramme ne descend plus.
void test_front_to_back_is_a_floor() {
    // Ouverture 60° : 60° d'écart vaut 12 dB, 90° en vaudrait 27 et 180° en vaudrait
    // 108. Le plancher à 20 dB écrête les deux derniers.
    const Pattern p{Kind::Unidirectional, 0.0, 60.0, 0.0, 20.0};
    CHECK_NEAR(gain_offset_db(p, 60.0), -12.0, kTol);   // sous le plancher : inchangé
    CHECK_NEAR(gain_offset_db(p, 90.0), -20.0, kTol);   // 27 dB calculés, ramenés à 20
    CHECK_NEAR(gain_offset_db(p, 180.0), -20.0, kTol);  // 108 dB calculés, ramenés à 20
    // Avec un plancher plus bas, les 27 dB de 90° se voient à nouveau.
    const Pattern s{Kind::Unidirectional, 0.0, 60.0, 0.0, 45.0};
    CHECK_NEAR(gain_offset_db(s, 90.0), -27.0, kTol);
    CHECK_NEAR(gain_offset_db(s, 180.0), -45.0, kTol);  // 108 dB calculés, ramenés à 45
}

// Bidirectionnelle : deux lobes opposés, et le gain décroît entre les deux.
void test_bidirectional_has_two_opposite_lobes() {
    const Pattern p{Kind::Bidirectional, 0.0, 60.0, 0.0, 30.0};
    CHECK_NEAR(gain_offset_db(p, 0.0), 0.0, kTol);
    CHECK_NEAR(gain_offset_db(p, 180.0), 0.0, kTol);  // le dos est un axe, pas un plancher
    // Le creux est à 90° : c'est le point le plus éloigné des deux axes (90° de chacun).
    CHECK_NEAR(gain_offset_db(p, 90.0), -27.0, kTol);
    CHECK_NEAR(gain_offset_db(p, 270.0), -27.0, kTol);
    // Le point à −3 dB est à une demi-ouverture de l'axe le plus proche, soit 30°.
    CHECK_NEAR(gain_offset_db(p, 30.0), -3.0, kTol);
    CHECK_NEAR(gain_offset_db(p, 150.0), -3.0, kTol);  // 30° de l'axe opposé
    // Symétrie parfaite entre les deux lobes.
    for (double a = 0.0; a < 180.0; a += 7.5) {
        CHECK_NEAR(gain_offset_db(p, a), gain_offset_db(p, a + 180.0), kTol);
    }
    // Un creux à 90° n'est pas un plancher : le diagramme remonte ensuite vers 180°.
    CHECK_TRUE(gain_offset_db(p, 180.0) > gain_offset_db(p, 90.0));
}

// Sectorielle : sommet plat sur toute la largeur annoncée, décroissance au-delà.
void test_sector_has_a_flat_top() {
    const Pattern p{Kind::Sector, 0.0, 120.0, 0.0, 30.0};
    // Tout le secteur est au gain de crête, du bord ouest au bord est.
    for (double a = -60.0; a <= 60.0; a += 5.0) {
        CHECK_NEAR(gain_offset_db(p, a), 0.0, kTol);
    }
    // Au-delà du bord, la courbe retombe et atteint −3 dB un demi-secteur plus loin.
    CHECK_NEAR(gain_offset_db(p, 120.0), -3.0, kTol);
    // Un degré après le bord, la décroissance ne fait que commencer : 12·(1/120)².
    CHECK_NEAR(gain_offset_db(p, 61.0), -12.0 * (1.0 / 120.0) * (1.0 / 120.0), 1e-12);

    // Une directive de même ouverture n'est PAS plate : c'est là toute la différence.
    const Pattern u{Kind::Unidirectional, 0.0, 120.0, 0.0, 30.0};
    CHECK_TRUE(gain_offset_db(p, 60.0) > gain_offset_db(u, 60.0) + 2.9);
    CHECK_NEAR(gain_offset_db(u, 60.0), -3.0, kTol);

    // Les trois ouvertures de secteur usuelles.
    for (const double w : {60.0, 90.0, 120.0}) {
        const Pattern s{Kind::Sector, 0.0, w, 0.0, 30.0};
        CHECK_NEAR(gain_offset_db(s, 0.5 * w), 0.0, kTol);  // bord : encore au sommet
        CHECK_NEAR(gain_offset_db(s, w), -3.0, kTol);       // un demi-secteur plus loin
    }
}

// Omnidirectionnelle : insensible à tous les réglages, cercle parfait.
void test_omnidirectional_ignores_everything() {
    const Pattern a{Kind::Omnidirectional, 2.0, 90.0, 0.0, 20.0};
    const Pattern b{Kind::Omnidirectional, 2.0, 5.0, 200.0, 0.0};
    for (double az = 0.0; az < 360.0; az += 11.25) {
        CHECK_NEAR(gain_offset_db(a, az), 0.0, kTol);
        CHECK_NEAR(gain_offset_db(b, az), 0.0, kTol);
        CHECK_NEAR(gain_dbi(a, az), 2.0, kTol);
    }
}

// Angles hors d'un tour : ramenés par modulo, dans les deux sens.
void test_azimuth_wraps_around() {
    const Pattern p{Kind::Unidirectional, 0.0, 90.0, 30.0, 25.0};
    for (double az = 0.0; az < 360.0; az += 13.0) {
        CHECK_NEAR(gain_offset_db(p, az), gain_offset_db(p, az + 360.0), kTol);
        CHECK_NEAR(gain_offset_db(p, az), gain_offset_db(p, az - 720.0), kTol);
        CHECK_NEAR(gain_offset_db(p, az), gain_offset_db(p, az + 1080.0), kTol);
    }
    // Pointage lui aussi ramené : 370° vaut 10°.
    const Pattern q{Kind::Unidirectional, 0.0, 90.0, 370.0, 25.0};
    const Pattern r{Kind::Unidirectional, 0.0, 90.0, 10.0, 25.0};
    for (double az = 0.0; az < 360.0; az += 17.0) {
        CHECK_NEAR(gain_offset_db(q, az), gain_offset_db(r, az), kTol);
    }
}

// Décroissance monotone depuis l'axe : aucun lobe secondaire ne dépasse le principal.
void test_gain_never_exceeds_peak() {
    const Pattern types[] = {
        Pattern{Kind::Unidirectional, 0.0, 45.0, 0.0, 20.0},
        Pattern{Kind::Bidirectional, 0.0, 45.0, 0.0, 20.0},
        Pattern{Kind::Sector, 0.0, 45.0, 0.0, 20.0},
        Pattern{Kind::Omnidirectional, 0.0, 45.0, 0.0, 20.0},
    };
    for (const Pattern& p : types) {
        for (double az = 0.0; az < 360.0; az += 3.0) {
            CHECK_TRUE(gain_offset_db(p, az) <= 1e-12);
            CHECK_TRUE(gain_offset_db(p, az) >= -20.0 - 1e-12);
        }
    }
}

// Validation : ce qui est refusé, et ce qui ne doit pas l'être.
void test_validation() {
    CHECK_EQ(static_cast<int>(validate_pattern(Pattern{})), 0);

    // Types inconnus (au-delà de Sector, et valeur négative).
    CHECK_EQ(static_cast<int>(validate_pattern(Pattern{static_cast<Kind>(4), 0, 90, 0, 20})), 1);
    CHECK_EQ(static_cast<int>(validate_pattern(Pattern{static_cast<Kind>(-1), 0, 90, 0, 20})), 1);

    // Ouverture hors bornes : 5°..360°.
    CHECK_EQ(static_cast<int>(validate_pattern(Pattern{Kind::Sector, 0, 4.999, 0, 20})), 1);
    CHECK_EQ(static_cast<int>(validate_pattern(Pattern{Kind::Sector, 0, 360.001, 0, 20})), 1);
    CHECK_EQ(static_cast<int>(validate_pattern(Pattern{Kind::Sector, 0, 5.0, 0, 20})), 0);
    CHECK_EQ(static_cast<int>(validate_pattern(Pattern{Kind::Sector, 0, 360.0, 0, 20})), 0);

    // Gain hors bornes : −40..40 dBi.
    CHECK_EQ(static_cast<int>(validate_pattern(Pattern{Kind::Sector, -40.001, 90, 0, 20})), 1);
    CHECK_EQ(static_cast<int>(validate_pattern(Pattern{Kind::Sector, 40.001, 90, 0, 20})), 1);

    // Affaiblissement arrière : 0..60 dB.
    CHECK_EQ(static_cast<int>(validate_pattern(Pattern{Kind::Sector, 0, 90, 0, -0.001})), 1);
    CHECK_EQ(static_cast<int>(validate_pattern(Pattern{Kind::Sector, 0, 90, 0, 60.001})), 1);

    // Non fini.
    CHECK_EQ(static_cast<int>(validate_pattern(Pattern{Kind::Sector, 0, NAN, 0, 20})), 1);
    CHECK_EQ(static_cast<int>(validate_pattern(Pattern{Kind::Sector, NAN, 90, 0, 20})), 1);
    CHECK_EQ(static_cast<int>(validate_pattern(Pattern{Kind::Sector, 0, 90, NAN, 20})), 1);
    CHECK_EQ(static_cast<int>(validate_pattern(Pattern{Kind::Sector, 0, 90, 0, NAN})), 1);

    // Une omnidirectionnelle n'a pas à renseigner des champs sans effet : la refuser
    // sous prétexte qu'un réglage inutile est hors bornes serait un piège.
    CHECK_EQ(static_cast<int>(validate_pattern(Pattern{Kind::Omnidirectional, 0, 1.0, 0, 999.0})),
             0);
}

// Un diagramme invalide dégénère en omnidirectionnel plutôt que de propager un
// angle absurde dans un bilan de liaison.
void test_invalid_pattern_degenerates_to_omnidirectional() {
    const Pattern bad{static_cast<Kind>(9), 0.0, 90.0, 0.0, 20.0};
    for (double az = 0.0; az < 360.0; az += 23.0) {
        CHECK_NEAR(gain_offset_db(bad, az), 0.0, kTol);
    }
    // Azimut non fini : pareil, pas de NaN en sortie.
    const Pattern good{Kind::Unidirectional, 0.0, 90.0, 0.0, 20.0};
    CHECK_NEAR(gain_offset_db(good, NAN), 0.0, kTol);
    CHECK_NEAR(gain_offset_db(good, INFINITY), 0.0, kTol);
}

// Couverture : le lobe creuse la zone hors de son axe.
void test_coverage_follows_the_lobe() {
    const LogDistanceModel m = model();
    const lsim::env::Environment flat{};  // terrain plat : la portée ne dépend que du budget
    constexpr std::size_t kAz = 72;       // pas de 5°
    std::vector<double> omni(kAz, 0.0);
    std::vector<double> beam(kAz, 0.0);

    const double budget = 130.0;
    CHECK_EQ(static_cast<int>(lsim::env::coverage_radii_m(m, 0.0, 0.0, flat, budget, 50.0, kAz,
                                                          omni.data(), nullptr)),
             static_cast<int>(lsim::env::EnvStatus::Ok));
    const Pattern p{Kind::Unidirectional, 0.0, 60.0, 0.0, 30.0};
    CHECK_EQ(static_cast<int>(lsim::env::coverage_radii_m(m, 0.0, 0.0, flat, budget, 50.0, kAz,
                                                          beam.data(), &p)),
             static_cast<int>(lsim::env::EnvStatus::Ok));

    // k = 0 → azimut 0° = l'axe du lobe : portée identique à l'omnidirectionnelle.
    CHECK_NEAR(beam[0], omni[0], 1.0);
    // k = 36 → 180°, dans le dos : le budget perd 30 dB, la portée s'effondre.
    CHECK_TRUE(beam[36] < omni[36] * 0.2);
    CHECK_TRUE(beam[36] > 0.0);  // mais reste non nulle : le plancher n'est pas un mur
    // Aucune direction ne dépasse l'omnidirectionnelle : le lobe ne crée pas de portée.
    for (std::size_t k = 0; k < kAz; ++k) {
        CHECK_TRUE(beam[k] <= omni[k] + 1.0);
    }
}

// Couverture : un secteur pointé à l'est éclaire l'est, pas le nord.
void test_coverage_respects_pointing() {
    const LogDistanceModel m = model();
    const lsim::env::Environment flat{};
    constexpr std::size_t kAz = 360;  // pas de 1°
    std::vector<double> r(kAz, 0.0);
    const Pattern p{Kind::Sector, 0.0, 90.0, 0.0, 40.0};  // secteur de 90° vers l'est
    CHECK_EQ(static_cast<int>(lsim::env::coverage_radii_m(m, 0.0, 0.0, flat, 130.0, 50.0, kAz,
                                                          r.data(), &p)),
             static_cast<int>(lsim::env::EnvStatus::Ok));
    // Est (0°), et tout le secteur ±45°, sont à pleine portée.
    const double east = r[0];
    CHECK_TRUE(east > 0.0);
    CHECK_NEAR(r[45], east, 1.0);
    CHECK_NEAR(r[315], east, 1.0);  // −45°
    // L'ouest est nettement plus court.
    CHECK_TRUE(r[180] < east * 0.5);
    // Décroissance monotone du bord du secteur (45°) vers l'arrière (180°).
    for (int k = 45; k < 180; ++k) {
        CHECK_TRUE(r[k + 1] <= r[k] + 1.0);
    }
}

// Un diagramme invalide est refusé par la couverture : pas de zone silencieusement fausse.
void test_coverage_rejects_invalid_pattern() {
    const LogDistanceModel m = model();
    const lsim::env::Environment flat{};
    std::vector<double> r(8, 0.0);
    const Pattern bad{static_cast<Kind>(7), 0.0, 90.0, 0.0, 20.0};
    CHECK_EQ(static_cast<int>(lsim::env::coverage_radii_m(m, 0.0, 0.0, flat, 130.0, 50.0, 8,
                                                          r.data(), &bad)),
             static_cast<int>(lsim::env::EnvStatus::InvalidInput));
    const Pattern too_narrow{Kind::Sector, 0.0, 1.0, 0.0, 20.0};
    CHECK_EQ(static_cast<int>(lsim::env::coverage_radii_m(m, 0.0, 0.0, flat, 130.0, 50.0, 8,
                                                          r.data(), &too_narrow)),
             static_cast<int>(lsim::env::EnvStatus::InvalidInput));
}

// Une omnidirectionnelle explicite reproduit exactement l'absence de diagramme :
// c'est la garantie que le nouveau chemin de calcul ne change rien au comportement
// d'avant pour les scénarios existants.
void test_omni_equals_no_pattern() {
    const LogDistanceModel m = model();
    const lsim::env::Environment flat{};
    constexpr std::size_t kAz = 36;
    std::vector<double> a(kAz, 0.0);
    std::vector<double> b(kAz, 0.0);
    const Pattern omni{Kind::Omnidirectional, 0.0, 90.0, 45.0, 20.0};
    CHECK_EQ(static_cast<int>(lsim::env::coverage_radii_m(m, 100.0, -50.0, flat, 135.0, 40.0, kAz,
                                                          a.data(), nullptr)),
             static_cast<int>(lsim::env::EnvStatus::Ok));
    CHECK_EQ(static_cast<int>(lsim::env::coverage_radii_m(m, 100.0, -50.0, flat, 135.0, 40.0, kAz,
                                                          b.data(), &omni)),
             static_cast<int>(lsim::env::EnvStatus::Ok));
    for (std::size_t k = 0; k < kAz; ++k) {
        CHECK_NEAR(a[k], b[k], kTol);
    }
}

}  // namespace

void run_antenna_tests() {
    test_boresight_is_at_peak_gain();
    test_minus_3db_at_half_beamwidth();
    test_front_to_back_is_a_floor();
    test_bidirectional_has_two_opposite_lobes();
    test_sector_has_a_flat_top();
    test_omnidirectional_ignores_everything();
    test_azimuth_wraps_around();
    test_gain_never_exceeds_peak();
    test_validation();
    test_invalid_pattern_degenerates_to_omnidirectional();
    test_coverage_follows_the_lobe();
    test_coverage_respects_pointing();
    test_coverage_rejects_invalid_pattern();
    test_omni_equals_no_pattern();
}
