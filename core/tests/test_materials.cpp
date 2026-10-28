// SPDX-License-Identifier: Apache-2.0
// Tests unitaires : atténuation des pavés (UIT-R P.2040-4, Tableau 3 et éq. 27a).
#include <cmath>

#include "check.hpp"
#include "lsim/materials.hpp"

namespace {

using namespace lsim::materials;
using lsim::lora::Status;

void test_concrete_1ghz_matches_equation_27a() {
    // σ = 0,0462 · 1^0,7822 = 0,0462 S/m ; ε′ = 5,24 ;
    // A = 1636 · 0,0462 / √5,24 ≈ 33,0 dB/m.
    AttenuationResult r;
    CHECK_EQ(static_cast<int>(attenuation_db_per_m(Material::Concrete, 1e9, r)),
             static_cast<int>(Status::Ok));
    CHECK_TRUE(std::fabs(r.db_per_m - 33.0) < 0.05);
    CHECK_TRUE(std::fabs(r.relative_permittivity - 5.24) < 1e-9);
    CHECK_TRUE(!r.extrapolated);
}

void test_brick_wall_thickness() {
    // Brique, 1 GHz : σ = 0,0238 · 1^0,16 = 0,0238 ; ε′ = 3,91 ; A ≈ 19,7 dB/m.
    // Mur de 0,10 m : ≈ 1,97 dB.
    double loss = 0.0;
    CHECK_EQ(static_cast<int>(traversal_loss_db(Material::Brick, 1e9, 0.10, loss)),
             static_cast<int>(Status::Ok));
    CHECK_TRUE(std::fabs(loss - 1.97) < 0.02);
}

void test_out_of_range_is_flagged() {
    // Béton documenté 1–100 GHz ; 868 MHz est hors plage : valeur extrapolée signalée.
    AttenuationResult r;
    CHECK_EQ(static_cast<int>(attenuation_db_per_m(Material::Concrete, 868e6, r)),
             static_cast<int>(Status::Ok));
    CHECK_TRUE(r.extrapolated);
    CHECK_TRUE(r.db_per_m > 0.0);
}

void test_wood_and_glass_are_attenuating_and_monotonic_in_thickness() {
    AttenuationResult wood;
    AttenuationResult glass;
    CHECK_EQ(static_cast<int>(attenuation_db_per_m(Material::Wood, 2.4e9, wood)),
             static_cast<int>(Status::Ok));
    CHECK_EQ(static_cast<int>(attenuation_db_per_m(Material::Glass, 2.4e9, glass)),
             static_cast<int>(Status::Ok));
    CHECK_TRUE(wood.db_per_m > 0.0);
    CHECK_TRUE(glass.db_per_m > 0.0);
    double a = 0.0;
    double b = 0.0;
    CHECK_EQ(static_cast<int>(traversal_loss_db(Material::Glass, 2.4e9, 0.005, a)),
             static_cast<int>(Status::Ok));
    CHECK_EQ(static_cast<int>(traversal_loss_db(Material::Glass, 2.4e9, 0.010, b)),
             static_cast<int>(Status::Ok));
    CHECK_TRUE(b > a);
}

void test_air_is_lossless() {
    AttenuationResult r;
    CHECK_EQ(static_cast<int>(attenuation_db_per_m(Material::Air, 1e9, r)),
             static_cast<int>(Status::Ok));
    CHECK_TRUE(r.db_per_m == 0.0);
}

void test_rejects_invalid_inputs() {
    AttenuationResult r;
    CHECK_EQ(static_cast<int>(attenuation_db_per_m(Material::Concrete, 0.0, r)),
             static_cast<int>(Status::InvalidParameter));
    CHECK_EQ(static_cast<int>(attenuation_db_per_m(Material::Concrete, -1e9, r)),
             static_cast<int>(Status::InvalidParameter));
    CHECK_EQ(static_cast<int>(attenuation_db_per_m(Material::Concrete, NAN, r)),
             static_cast<int>(Status::InvalidParameter));
    double loss = 0.0;
    CHECK_EQ(static_cast<int>(traversal_loss_db(Material::Concrete, 1e9, -0.1, loss)),
             static_cast<int>(Status::InvalidParameter));
}

}  // namespace

void run_materials_tests() {
    test_concrete_1ghz_matches_equation_27a();
    test_brick_wall_thickness();
    test_out_of_range_is_flagged();
    test_wood_and_glass_are_attenuating_and_monotonic_in_thickness();
    test_air_is_lossless();
    test_rejects_invalid_inputs();
}
