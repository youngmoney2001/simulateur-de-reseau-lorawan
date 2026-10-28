// SPDX-License-Identifier: Apache-2.0
#include "lsim/materials.hpp"

#include <cmath>
#include <cstddef>

namespace lsim::materials {

namespace {

// Tableau 3 de la Recommandation UIT-R P.2040-4 (09/2025), lignes diélectriques.
// Chaque ligne : matériau, a (ε′ = a·f^b), b, c (σ = c·f^d), d, plage documentée (GHz).
struct Row {
    Material material;
    double a;
    double b;
    double c;
    double d;
    double f_min_ghz;
    double f_max_ghz;
};

constexpr Row kRows[] = {
    {Material::Air, 1.0, 0.0, 0.0, 0.0, 0.001, 100.0},
    {Material::Concrete, 5.24, 0.0, 0.0462, 0.7822, 1.0, 100.0},
    {Material::Concrete, 5.17, 0.0, 0.0145, 1.0900, 110.0, 330.0},
    {Material::Brick, 3.91, 0.0, 0.0238, 0.16, 1.0, 40.0},
    {Material::Brick, 4.15, 0.0, 0.0006, 1.5712, 110.0, 330.0},
    {Material::Plasterboard, 2.73, 0.0, 0.0085, 0.9395, 1.0, 100.0},
    {Material::Plasterboard, 2.56, 0.0, 0.0001, 1.7799, 110.0, 330.0},
    {Material::Plasterboard, 2.65, 0.0, 0.0002, 1.598, 100.0, 400.0},
    {Material::Wood, 1.99, 0.0, 0.0047, 1.0718, 0.001, 100.0},
    {Material::Wood, 1.82, 0.0, 0.0040, 1.0761, 110.0, 330.0},
    {Material::Wood, 2.1183, 0.0, 0.0055, 1.1113, 100.0, 400.0},
    {Material::Glass, 6.31, 0.0, 0.0036, 1.3394, 0.1, 100.0},
    {Material::Glass, 5.79, 0.0, 0.0004, 1.658, 220.0, 450.0},
    {Material::Glass, 6.5767, 0.0, 0.0012, 1.4697, 100.0, 400.0},
    {Material::AcrylicGlass, 2.58, 0.0, 0.0001, 1.6524, 110.0, 330.0},
    {Material::CeilingPanel, 1.48, 0.0, 0.0011, 1.0750, 1.0, 100.0},
    {Material::CeilingPanel, 1.52, 0.0, 0.0029, 1.029, 220.0, 450.0},
    {Material::CeilingPanel, 1.2567, 0.0, 0.00013, 1.454, 100.0, 400.0},
    {Material::ChipboardPanel, 2.58, 0.0, 0.0217, 0.7800, 1.0, 100.0},
    {Material::ChipboardPanel, 2.16, 0.0, 0.0023, 1.359, 100.0, 200.0},
    {Material::Plywood, 2.71, 0.0, 0.33, 0.0, 1.0, 40.0},
    {Material::Plywood, 1.94, 0.0, 0.0067, 0.9982, 110.0, 330.0},
    {Material::Plywood, 2.17, 0.0, 0.0063, 1.045, 100.0, 400.0},
    {Material::Marble, 7.074, 0.0, 0.0055, 0.9262, 1.0, 60.0},
    {Material::Marble, 7.94, 0.0, 0.0001, 1.7330, 110.0, 330.0},
    {Material::Marble, 8.62, 0.0, 0.0027, 1.15, 100.0, 400.0},
    {Material::FloorPanel, 3.66, 0.0, 0.0044, 1.3515, 50.0, 100.0},
    {Material::FloorPanel, 5.27, 0.0, 2.22e-17, 7.3413, 220.0, 300.0},
    {Material::FloorPanel, 5.27, 0.0, 0.0003, 2.0298, 300.0, 400.0},
    {Material::FloorPanel, 5.27, 0.0, 49.8726, 0.0, 400.0, 450.0},
    {Material::FloorPanel, 3.1575, 0.0, 0.001675, 1.32775, 100.0, 400.0},
    {Material::VinylTile, 3.62, 0.0, 0.0051, 0.8422, 1.0, 40.0},
    {Material::CarpetTile, 2.08, 0.0, 0.0009, 0.8200, 1.0, 40.0},
    {Material::BituminousAsphalt, 4.83, 0.0, 0.0108, 1.3969, 1.0, 40.0},
};

// Constante de l'éq. (27a) : A = 1636 · σ / √ε′ (dB/m).
constexpr double kAttenuationConstant = 1636.0;

}  // namespace

lora::Status attenuation_db_per_m(Material material, double frequency_hz,
                                  AttenuationResult& out) {
    if (!std::isfinite(frequency_hz) || frequency_hz <= 0.0) {
        return lora::Status::InvalidParameter;
    }
    const double f_ghz = frequency_hz / 1e9;

    // Choix de la ligne : celle dont la plage contient f ; sinon la plus proche.
    const Row* best = nullptr;
    double best_distance = 0.0;
    for (const Row& row : kRows) {
        if (row.material != material) {
            continue;
        }
        double distance = 0.0;
        if (f_ghz < row.f_min_ghz) {
            distance = row.f_min_ghz - f_ghz;
        } else if (f_ghz > row.f_max_ghz) {
            distance = f_ghz - row.f_max_ghz;
        }
        if (best == nullptr || distance < best_distance) {
            best = &row;
            best_distance = distance;
        }
        if (distance == 0.0) {
            break;  // première ligne dont la plage contient f
        }
    }
    if (best == nullptr) {
        return lora::Status::InvalidParameter;
    }

    const double eps = best->a * std::pow(f_ghz, best->b);
    const double sigma = best->c * std::pow(f_ghz, best->d);
    if (!(eps > 0.0) || !std::isfinite(eps) || !std::isfinite(sigma) || sigma < 0.0) {
        return lora::Status::InvalidParameter;
    }
    out.relative_permittivity = eps;
    out.conductivity_s_per_m = sigma;
    out.db_per_m = kAttenuationConstant * sigma / std::sqrt(eps);
    out.extrapolated = best_distance > 0.0;
    return lora::Status::Ok;
}

lora::Status traversal_loss_db(Material material, double frequency_hz,
                               double thickness_m, double& out_db) {
    if (!std::isfinite(thickness_m) || thickness_m < 0.0) {
        return lora::Status::InvalidParameter;
    }
    AttenuationResult r;
    const lora::Status st = attenuation_db_per_m(material, frequency_hz, r);
    if (st != lora::Status::Ok) {
        return st;
    }
    out_db = r.db_per_m * thickness_m;
    return lora::Status::Ok;
}

}  // namespace lsim::materials
