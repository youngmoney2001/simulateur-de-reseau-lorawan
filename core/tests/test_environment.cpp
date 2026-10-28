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
        {Position{4000.0, 50.0}, 7, 10, 14.0, 0, 600000000000LL, 1, 1.0, {}},  // derrière la crête
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
    const EndDeviceSpec devs[] = {{Position{100.0, 0.0}, 7, 10, 14.0, 0, 600000000000LL, 1, 1.0, {}}};
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

// Deux crêtes identiques à 1/3 et 2/3 du trajet : Deygout doit ajouter la perte
// des deux arêtes secondaires à celle de l'arête principale.
void test_deygout_two_ridges_add_loss() {
    const double cell = 100.0;
    const std::uint32_t nx = 31;  // 3 000 m, pas 100 m
    std::vector<float> z_two(nx * 2, 0.0f);
    std::vector<float> z_one(nx * 2, 0.0f);
    for (std::uint32_t iy = 0; iy < 2; ++iy) {
        z_two[iy * nx + 10] = 60.0f;  // x = 1000 m
        z_two[iy * nx + 20] = 60.0f;  // x = 2000 m
        z_one[iy * nx + 10] = 60.0f;
    }
    ElevationGrid g2, g1;
    CHECK_EQ(static_cast<int>(make_elevation_grid(0, 0, cell, nx, 2, z_two.data(), z_two.size(), g2)),
             static_cast<int>(EnvStatus::Ok));
    CHECK_EQ(static_cast<int>(make_elevation_grid(0, 0, cell, nx, 2, z_one.data(), z_one.size(), g1)),
             static_cast<int>(EnvStatus::Ok));
    Environment e2;
    e2.grid = &g2;
    Environment e1;
    e1.grid = &g1;
    PathLoss p2, p1;
    CHECK_EQ(static_cast<int>(path_loss_db(model(), 0, 50, 3000, 50, e2, p2)),
             static_cast<int>(EnvStatus::Ok));
    CHECK_EQ(static_cast<int>(path_loss_db(model(), 0, 50, 3000, 50, e1, p1)),
             static_cast<int>(EnvStatus::Ok));
    CHECK_TRUE(p2.diffraction_db > p1.diffraction_db + 1.0);
    CHECK_TRUE(p1.diffraction_db > 0.0);
}

// Portée par azimut : un mur côté est réduit la portée dans cette direction seulement.
void test_coverage_radii_follow_obstacles() {
    const LogDistanceModel m = model();
    const double mapl = 120.0;
    const auto bound = lsim::radio::max_range_m(m, mapl);
    CHECK_EQ(static_cast<int>(bound.status), 0);

    constexpr std::size_t kAz = 8;
    double flat[kAz] = {};
    CHECK_EQ(static_cast<int>(coverage_radii_m(m, 0, 0, Environment{}, mapl, 10.0, kAz, flat)),
             static_cast<int>(EnvStatus::Ok));
    for (double r : flat) {
        CHECK_NEAR(r, bound.value, 10.0 + 1e-6);
    }

    // Mur haut de 40 m entre 300 et 320 m, au-dessus de l'azimut 0 (est).
    Obstacle wall{300.0, -200.0, 320.0, 200.0, 40.0, 60.0};
    Environment walled;
    walled.obstacles = &wall;
    walled.obstacle_count = 1;
    double with_wall[kAz] = {};
    CHECK_EQ(static_cast<int>(coverage_radii_m(m, 0, 0, walled, mapl, 10.0, kAz, with_wall)),
             static_cast<int>(EnvStatus::Ok));
    // Azimut 0 (est) : la portée est coupée par le mur ; azimut opposé (ouest) : inchangé.
    CHECK_TRUE(with_wall[0] < 300.0 + 1.0);
    CHECK_NEAR(with_wall[kAz / 2], flat[kAz / 2], 10.0 + 1e-6);
    for (std::size_t k = 0; k < kAz; ++k) {
        CHECK_TRUE(with_wall[k] <= flat[k] + 1e-6);  // jamais plus que le log-distance
    }
}

void test_coverage_input_and_work_limits() {
    const LogDistanceModel m = model();
    double out[4] = {};
    CHECK_EQ(static_cast<int>(coverage_radii_m(m, 0, 0, Environment{}, 120.0, 10.0, 0, out)),
             static_cast<int>(EnvStatus::InvalidInput));
    CHECK_EQ(static_cast<int>(coverage_radii_m(m, 0, 0, Environment{}, 120.0, 0.1, 4, out)),
             static_cast<int>(EnvStatus::InvalidInput));
    CHECK_EQ(static_cast<int>(coverage_radii_m(m, 0, 0, Environment{}, 120.0, 10.0, 4, nullptr)),
             static_cast<int>(EnvStatus::InvalidInput));
    CHECK_EQ(static_cast<int>(coverage_radii_m(m, 0, 0, Environment{}, std::nan(""), 10.0, 4, out)),
             static_cast<int>(EnvStatus::InvalidInput));
    // 720 azimuts, pas de 1 m, 6 000 obstacles : borne de travail dépassée.
    std::vector<double> big(720);
    std::vector<Obstacle> walls(6000, Obstacle{1e6, 1e6, 1e6 + 1, 1e6 + 1, 1.0, 0.0});
    Environment e;
    e.obstacles = walls.data();
    e.obstacle_count = walls.size();
    CHECK_EQ(static_cast<int>(coverage_radii_m(m, 0, 0, e, 120.0, 1.0, 720, big.data())),
             static_cast<int>(EnvStatus::WorkLimit));
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
    test_deygout_two_ridges_add_loss();
    test_coverage_radii_follow_obstacles();
    test_coverage_input_and_work_limits();
}
