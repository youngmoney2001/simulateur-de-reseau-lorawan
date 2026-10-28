// SPDX-License-Identifier: Apache-2.0
// Relief et obstacles : grille, interpolation, diffraction, pénétration, intégration moteur.
#include <cmath>
#include <vector>

#include "check.hpp"
#include "lsim/engine.hpp"
#include "lsim/environment.hpp"

namespace {

using namespace lsim::env;
using lsim::radio::LogDistanceModel;

LogDistanceModel model() {
    LogDistanceModel m;
    m.frequency_hz = 868.1e6;
    m.reference_distance_m = 1.0;
    m.exponent = 2.7;
    return m;
}

// Relief : crête de hauteur `peak` sur la colonne ix = 20 (x = 2000 m) d'une grille 41 x 2.
ElevationGrid ridge(float peak) {
    std::vector<float> z(41 * 2, 0.0f);
    for (std::uint32_t iy = 0; iy < 2; ++iy) {
        z[iy * 41 + 20] = peak;
    }
    ElevationGrid g;
    CHECK_EQ(static_cast<int>(make_elevation_grid(0.0, 0.0, 100.0, 41, 2, z.data(), z.size(), g)),
             static_cast<int>(EnvStatus::Ok));
    return g;
}

void test_grid_validation() {
    ElevationGrid g;
    const float v[4] = {0, 1, 2, 3};
    CHECK_EQ(static_cast<int>(make_elevation_grid(0, 0, 10, 1, 2, v, 2, g)),
             static_cast<int>(EnvStatus::InvalidGrid));
    CHECK_EQ(static_cast<int>(make_elevation_grid(0, 0, 0, 2, 2, v, 4, g)),
             static_cast<int>(EnvStatus::InvalidGrid));
    CHECK_EQ(static_cast<int>(make_elevation_grid(0, 0, 10, 2, 2, v, 3, g)),
             static_cast<int>(EnvStatus::InvalidGrid));
    const float nan_v[4] = {0, NAN, 2, 3};
    CHECK_EQ(static_cast<int>(make_elevation_grid(0, 0, 10, 2, 2, nan_v, 4, g)),
             static_cast<int>(EnvStatus::InvalidGrid));
    CHECK_EQ(static_cast<int>(make_elevation_grid(0, 0, 10, 2000, 2001, v, 4, g)),
             static_cast<int>(EnvStatus::GridTooLarge));
}

void test_bilinear_and_clamp() {
    const float v[4] = {0, 10, 20, 30};  // (0,0)=0 (1,0)=10 (0,1)=20 (1,1)=30
    ElevationGrid g;
    CHECK_EQ(static_cast<int>(make_elevation_grid(0, 0, 100, 2, 2, v, 4, g)),
             static_cast<int>(EnvStatus::Ok));
    CHECK_NEAR(ground_elevation_m(g, 50, 50), 15.0, 1e-9);
    CHECK_NEAR(ground_elevation_m(g, 100, 100), 30.0, 1e-9);
    CHECK_NEAR(ground_elevation_m(g, -500, -500), 0.0, 1e-9);   // clamp
    CHECK_NEAR(ground_elevation_m(g, 1000, 1000), 30.0, 1e-9);  // clamp
}

void test_no_environment_equals_log_distance() {
    PathLoss pl;
    CHECK_EQ(static_cast<int>(path_loss_db(model(), 0, 0, 3000, 400, Environment{}, pl)),
             static_cast<int>(EnvStatus::Ok));
    const auto base = lsim::radio::log_distance_path_loss_db(model(), std::hypot(3000.0, 400.0));
    CHECK_NEAR(pl.total_db, base.value, 1e-12);
    CHECK_NEAR(pl.diffraction_db, 0.0, 1e-12);
}

void test_flat_terrain_has_no_extra_loss() {
    const ElevationGrid flat = ridge(0.0f);
    Environment e;
    e.grid = &flat;
    PathLoss pl;
    CHECK_EQ(static_cast<int>(path_loss_db(model(), 0, 50, 4000, 50, e, pl)),
             static_cast<int>(EnvStatus::Ok));
    CHECK_NEAR(pl.diffraction_db, 0.0, 1e-9);
    CHECK_NEAR(pl.total_db, pl.log_distance_db, 1e-9);
}

void test_ridge_creates_diffraction_loss() {
    const ElevationGrid g = ridge(200.0f);
    Environment e;
    e.grid = &g;
    PathLoss pl;
    CHECK_EQ(static_cast<int>(path_loss_db(model(), 0, 50, 4000, 50, e, pl)),
             static_cast<int>(EnvStatus::Ok));
    CHECK_TRUE(pl.diffraction_db > 30.0);
    CHECK_NEAR(pl.total_db, pl.log_distance_db + pl.diffraction_db, 1e-9);

    // Une crête plus haute bloque davantage.
    const ElevationGrid higher = ridge(400.0f);
    e.grid = &higher;
    PathLoss pl2;
    path_loss_db(model(), 0, 50, 4000, 50, e, pl2);
    CHECK_TRUE(pl2.diffraction_db > pl.diffraction_db);
}

void test_obstacle_penetration_and_diffraction() {
    // Pavé x in [1000, 1100] ; sommet à 20 m au-dessus du sol (plat) : rayon sous le sommet.
    const Obstacle wall{1000, -50, 1100, 50, 20.0, 12.0};
    Environment e;
    e.obstacles = &wall;
    e.obstacle_count = 1;
    PathLoss pl;
    CHECK_EQ(static_cast<int>(path_loss_db(model(), 0, 0, 2000, 0, e, pl)),
             static_cast<int>(EnvStatus::Ok));
    CHECK_NEAR(pl.penetration_db, 12.0, 1e-9);
    CHECK_TRUE(pl.diffraction_db > 0.0);

    // Pavé bas, sous le rayon : aucune pénétration ni diffraction.
    const Obstacle low{1000, -50, 1100, 50, 1.0, 12.0};
    e.obstacles = &low;
    PathLoss pl2;
    path_loss_db(model(), 0, 0, 2000, 0, e, pl2);
    CHECK_NEAR(pl2.penetration_db, 0.0, 1e-9);
    CHECK_NEAR(pl2.diffraction_db, 0.0, 1e-9);
}

void test_invalid_obstacle_refused() {
    const Obstacle bad{10, 0, 5, 10, 3.0, 0.0};  // x_min >= x_max
    Environment e;
    e.obstacles = &bad;
    e.obstacle_count = 1;
    CHECK_EQ(static_cast<int>(validate_environment(e)), static_cast<int>(EnvStatus::InvalidObstacle));
    const Obstacle neg{0, 0, 5, 5, -1.0, 0.0};
    e.obstacles = &neg;
    CHECK_EQ(static_cast<int>(validate_environment(e)), static_cast<int>(EnvStatus::InvalidObstacle));
    e.obstacles = nullptr;
    CHECK_EQ(static_cast<int>(validate_environment(e)), static_cast<int>(EnvStatus::InvalidInput));
}

// Intégration moteur : un dispositif derrière la crête est perdu, un autre non.
void test_engine_uses_environment() {
    using namespace lsim::sim;
    const EndDeviceSpec devs[] = {
        {Position{4000.0, 50.0}, 7, 10, 14.0, 0, 600000000000LL, 1},  // derrière la crête
    };
    GatewaySpec gw{};
    gw.position = Position{0.0, 50.0};
    PropagationSpec prop;
    prop.exponent = 2.7;

    DeviceStats st[1];
    SimulationStats tot;
    simulate_uplinks(devs, 1, gw, prop, st, tot);
    CHECK_EQ(tot.received, std::uint64_t{1});

    const ElevationGrid g = ridge(200.0f);
    Environment e;
    e.grid = &g;
    CHECK_EQ(static_cast<int>(simulate_uplinks(devs, 1, gw, prop, st, tot, &e)),
             static_cast<int>(SimStatus::Ok));
    CHECK_EQ(tot.received, std::uint64_t{0});
    CHECK_EQ(tot.lost_sensitivity, std::uint64_t{1});
}

void test_engine_rejects_invalid_environment_and_work_limit() {
    using namespace lsim::sim;
    const EndDeviceSpec devs[] = {{Position{100.0, 0.0}, 7, 10, 14.0, 0, 600000000000LL, 1}};
    GatewaySpec gw{};
    PropagationSpec prop;
    DeviceStats st[1];
    SimulationStats tot;

    const Obstacle bad{10, 0, 5, 10, 3.0, 0.0};
    Environment e;
    e.obstacles = &bad;
    e.obstacle_count = 1;
    CHECK_EQ(static_cast<int>(simulate_uplinks(devs, 1, gw, prop, st, tot, &e)),
             static_cast<int>(SimStatus::InvalidEnvironment));

    // 10 000 dispositifs x 6 000 obstacles > 5e7 contrôles : refusé avant calcul.
    std::vector<EndDeviceSpec> many(10000, devs[0]);
    std::vector<DeviceStats> stats(many.size());
    std::vector<Obstacle> walls(6000, Obstacle{1e6, 1e6, 1e6 + 1, 1e6 + 1, 1.0, 0.0});
    Environment big;
    big.obstacles = walls.data();
    big.obstacle_count = walls.size();
    CHECK_EQ(static_cast<int>(simulate_uplinks(many.data(), many.size(), gw, prop, stats.data(),
                                               tot, &big)),
             static_cast<int>(SimStatus::EnvironmentWorkLimit));
}

}  // namespace

void run_environment_tests() {
    test_grid_validation();
    test_bilinear_and_clamp();
    test_no_environment_equals_log_distance();
    test_flat_terrain_has_no_extra_loss();
    test_ridge_creates_diffraction_loss();
    test_obstacle_penetration_and_diffraction();
    test_invalid_obstacle_refused();
    test_engine_uses_environment();
    test_engine_rejects_invalid_environment_and_work_limit();
}
