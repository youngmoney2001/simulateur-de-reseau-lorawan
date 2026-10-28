// SPDX-License-Identifier: Apache-2.0
// Tests unitaires : bilan de liaison et propagation.
#include <limits>

#include "check.hpp"
#include "lsim/link_budget.hpp"

namespace {

using namespace lsim::radio;
using lsim::lora::Status;

void test_free_space_reference_values() {
    // FSPL(1 km, 868 MHz) = 91,2 dB ; FSPL(1 km, 2,4 GHz) = 100,05 dB.
    const BudgetResult a = free_space_path_loss_db(1000.0, 868e6);
    CHECK_EQ(static_cast<int>(a.status), static_cast<int>(Status::Ok));
    CHECK_NEAR(a.value, 91.2, 0.05);
    const BudgetResult b = free_space_path_loss_db(1000.0, 2.4e9);
    CHECK_NEAR(b.value, 100.05, 0.05);
}

void test_free_space_doubling_distance_adds_6db() {
    const double d1 = free_space_path_loss_db(500.0, 868e6).value;
    const double d2 = free_space_path_loss_db(1000.0, 868e6).value;
    CHECK_NEAR(d2 - d1, 6.02, 0.01);
}

void test_log_distance_exponent_slope() {
    LogDistanceModel m;
    m.exponent = 3.5;
    const double p1 = log_distance_path_loss_db(m, 100.0).value;
    const double p10 = log_distance_path_loss_db(m, 1000.0).value;
    // Une décade de distance ajoute 10 * n dB.
    CHECK_NEAR(p10 - p1, 35.0, 1e-9);
}

void test_log_distance_matches_free_space_when_n_is_2() {
    LogDistanceModel m;
    m.exponent = 2.0;
    const double ld = log_distance_path_loss_db(m, 1000.0).value;
    const double fs = free_space_path_loss_db(1000.0, m.frequency_hz).value;
    CHECK_NEAR(ld, fs, 1e-9);
}

void test_mapl_and_range_roundtrip() {
    // Budget : +14 dBm, antennes 0 dBi, sensibilité SF12 -137 dBm, marge 0.
    LinkBudget b;
    const BudgetResult mapl = maximum_allowable_path_loss_db(b, -137.0);
    CHECK_NEAR(mapl.value, 151.0, 1e-9);

    LogDistanceModel m;
    m.exponent = 2.7;
    const BudgetResult range = max_range_m(m, mapl.value);
    CHECK_EQ(static_cast<int>(range.status), static_cast<int>(Status::Ok));
    // Aller-retour : la perte à la portée calculée doit redonner la MAPL.
    const double pl_back = log_distance_path_loss_db(m, range.value).value;
    CHECK_NEAR(pl_back, mapl.value, 1e-6);
}

void test_fade_margin_reduces_range() {
    LogDistanceModel m;
    LinkBudget no_margin;
    LinkBudget with_margin;
    with_margin.fade_margin_db = 10.0;
    const double r0 = max_range_m(m, maximum_allowable_path_loss_db(no_margin, -137.0).value).value;
    const double r1 = max_range_m(m, maximum_allowable_path_loss_db(with_margin, -137.0).value).value;
    CHECK_TRUE(r1 < r0);
}

void test_rejects_invalid_parameters() {
    LogDistanceModel m;
    CHECK_EQ(static_cast<int>(free_space_path_loss_db(0.0, 868e6).status),
             static_cast<int>(Status::InvalidParameter));
    CHECK_EQ(static_cast<int>(free_space_path_loss_db(-5.0, 868e6).status),
             static_cast<int>(Status::InvalidParameter));
    m.exponent = 0.5;
    CHECK_EQ(static_cast<int>(log_distance_path_loss_db(m, 100.0).status),
             static_cast<int>(Status::InvalidParameter));
    m.exponent = 2.0;
    CHECK_EQ(static_cast<int>(max_range_m(m, std::numeric_limits<double>::infinity()).status),
             static_cast<int>(Status::InvalidParameter));
    // Perte inférieure à PL(d0) : hors modèle, refusé.
    CHECK_EQ(static_cast<int>(max_range_m(m, 0.0).status),
             static_cast<int>(Status::InvalidParameter));
}

}  // namespace

void run_link_budget_tests() {
    test_free_space_reference_values();
    test_free_space_doubling_distance_adds_6db();
    test_log_distance_exponent_slope();
    test_log_distance_matches_free_space_when_n_is_2();
    test_mapl_and_range_roundtrip();
    test_fade_margin_reduces_range();
    test_rejects_invalid_parameters();
}
