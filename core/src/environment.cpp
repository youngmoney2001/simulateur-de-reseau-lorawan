// SPDX-License-Identifier: Apache-2.0
#include "lsim/environment.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <vector>

#include "lsim/lora_phy.hpp"

namespace lsim::env {
namespace {

constexpr double kSpeedOfLight = 299'792'458.0;
constexpr double kMinDistanceM = 1.0;         // en dessous : pas de diffraction
constexpr double kProfileStepM = 10.0;        // pas de profil sans grille
constexpr double kKnifeEdgeMinV = -0.78;      // domaine de validité de J(v)
constexpr std::size_t kMaxAzimuths = 720;
constexpr double kMinCoverageStepM = 1.0;
constexpr int kCoverageBisections = 14;
constexpr double kMaxCoverageWork = 2.0e9;

bool finite(double x) { return std::isfinite(x); }

// Liang-Barsky : intervalle [t0, t1] de la portion du segment à l'intérieur du pavé.
bool clip_segment(const Obstacle& o, double x0, double y0, double x1, double y1,
                  double& t0, double& t1) {
    const double dx = x1 - x0;
    const double dy = y1 - y0;
    const double p[4] = {-dx, dx, -dy, dy};
    const double q[4] = {x0 - o.x_min_m, o.x_max_m - x0, y0 - o.y_min_m, o.y_max_m - y0};
    t0 = 0.0;
    t1 = 1.0;
    for (int k = 0; k < 4; ++k) {
        if (p[k] == 0.0) {
            if (q[k] < 0.0) return false;  // parallèle et à l'extérieur
            continue;
        }
        const double r = q[k] / p[k];
        if (p[k] < 0.0) {
            if (r > t1) return false;
            t0 = std::max(t0, r);
        } else {
            if (r < t0) return false;
            t1 = std::min(t1, r);
        }
    }
    return t0 <= t1;
}

// Perte de diffraction de Lee (couteau unique) pour le paramètre de Fresnel v.
double knife_edge_loss_db(double v) {
    if (v <= kKnifeEdgeMinV) return 0.0;
    const double a = v - 0.1;
    const double j = 6.9 + 20.0 * std::log10(std::sqrt(a * a + 1.0) + a);
    return std::max(0.0, j);
}

struct Candidate {
    std::size_t index;
    double t0;
    double t1;
    double ground_m;  // sol local sous le centre du pavé
};

// Profil discrétisé : d[i] distance depuis l'émetteur (croissante), z[i] hauteur
// absolue de l'obstruction (sol ou sommet de pavé). z[0] et z[n] : antennes.
struct Profile {
    const double* d;
    const double* z;
    double wavelength_m;
};

// Diffraction de Deygout à 3 arêtes (principale + deux secondaires, niveau 2).
// Chaque arête est évaluée par rapport à la droite joignant ses extrémités
// (sommets d'obstacles inclus), comme dans la méthode de Deygout / UIT-R P.526.
double deygout_loss_db(const Profile& p, std::size_t a, std::size_t b, int level) {
    if (level <= 0 || b < a + 2) {
        return 0.0;
    }
    const double da = p.d[a];
    const double db = p.d[b];
    const double span = db - da;
    const double za = p.z[a];
    const double zb = p.z[b];
    double vmax = -std::numeric_limits<double>::infinity();
    std::size_t m = a;
    for (std::size_t i = a + 1; i < b; ++i) {
        const double t = (p.d[i] - da) / span;
        const double h = p.z[i] - (za + t * (zb - za));
        const double d1 = p.d[i] - da;
        const double d2 = db - p.d[i];
        const double v = h * std::sqrt(2.0 * span / (p.wavelength_m * d1 * d2));
        if (v > vmax) {
            vmax = v;
            m = i;
        }
    }
    if (vmax <= kKnifeEdgeMinV) {
        return 0.0;
    }
    return knife_edge_loss_db(vmax) + deygout_loss_db(p, a, m, level - 1) +
           deygout_loss_db(p, m, b, level - 1);
}

}  // namespace

EnvStatus make_elevation_grid(double origin_x_m, double origin_y_m, double cell_m,
                              std::uint32_t nx, std::uint32_t ny, const float* values,
                              std::size_t count, ElevationGrid& out) {
    out = ElevationGrid{};
    if (!finite(origin_x_m) || !finite(origin_y_m) || !finite(cell_m) || cell_m <= 0.0) {
        return EnvStatus::InvalidGrid;
    }
    if (nx < 2 || ny < 2) {
        return EnvStatus::InvalidGrid;
    }
    const std::uint64_t cells = static_cast<std::uint64_t>(nx) * static_cast<std::uint64_t>(ny);
    if (cells > kMaxGridCells) {
        return EnvStatus::GridTooLarge;
    }
    if (values == nullptr || count != cells) {
        return EnvStatus::InvalidGrid;
    }
    for (std::size_t i = 0; i < count; ++i) {
        if (!std::isfinite(values[i])) {
            return EnvStatus::InvalidGrid;
        }
    }
    out.origin_x_m = origin_x_m;
    out.origin_y_m = origin_y_m;
    out.cell_m = cell_m;
    out.nx = nx;
    out.ny = ny;
    out.z.assign(values, values + count);
    return EnvStatus::Ok;
}

EnvStatus validate_environment(const Environment& e) {
    if (!finite(e.gateway_height_m) || !finite(e.device_height_m) ||
        e.gateway_height_m < 0.0 || e.device_height_m < 0.0) {
        return EnvStatus::InvalidInput;
    }
    if (e.obstacle_count > kMaxObstacles) {
        return EnvStatus::TooManyObstacles;
    }
    if (e.obstacle_count > 0 && e.obstacles == nullptr) {
        return EnvStatus::InvalidInput;
    }
    for (std::size_t i = 0; i < e.obstacle_count; ++i) {
        const Obstacle& o = e.obstacles[i];
        if (!finite(o.x_min_m) || !finite(o.y_min_m) || !finite(o.x_max_m) || !finite(o.y_max_m) ||
            !finite(o.height_m) || !finite(o.attenuation_db)) {
            return EnvStatus::InvalidObstacle;
        }
        if (o.x_min_m >= o.x_max_m || o.y_min_m >= o.y_max_m) {
            return EnvStatus::InvalidObstacle;
        }
        if (o.height_m < 0.0 || o.attenuation_db < 0.0) {
            return EnvStatus::InvalidObstacle;
        }
    }
    return EnvStatus::Ok;
}

double ground_elevation_m(const ElevationGrid& g, double x_m, double y_m) {
    if (g.z.empty()) {
        return 0.0;
    }
    const double fx = std::clamp((x_m - g.origin_x_m) / g.cell_m, 0.0, static_cast<double>(g.nx - 1));
    const double fy = std::clamp((y_m - g.origin_y_m) / g.cell_m, 0.0, static_cast<double>(g.ny - 1));
    const std::uint32_t ix = std::min<std::uint32_t>(static_cast<std::uint32_t>(fx), g.nx - 2);
    const std::uint32_t iy = std::min<std::uint32_t>(static_cast<std::uint32_t>(fy), g.ny - 2);
    const double tx = fx - ix;
    const double ty = fy - iy;
    const auto at = [&](std::uint32_t x, std::uint32_t y) {
        return static_cast<double>(g.z[static_cast<std::size_t>(y) * g.nx + x]);
    };
    const double top = at(ix, iy) * (1.0 - tx) + at(ix + 1, iy) * tx;
    const double bottom = at(ix, iy + 1) * (1.0 - tx) + at(ix + 1, iy + 1) * tx;
    return top * (1.0 - ty) + bottom * ty;
}

EnvStatus path_loss_db(const radio::LogDistanceModel& model, double tx_x_m, double tx_y_m,
                       double rx_x_m, double rx_y_m, const Environment& e, PathLoss& out) {
    out = PathLoss{};
    if (!finite(tx_x_m) || !finite(tx_y_m) || !finite(rx_x_m) || !finite(rx_y_m)) {
        return EnvStatus::InvalidInput;
    }
    const EnvStatus vs = validate_environment(e);
    if (vs != EnvStatus::Ok) {
        return vs;
    }

    const double dx = rx_x_m - tx_x_m;
    const double dy = rx_y_m - tx_y_m;
    const double d = std::max(std::hypot(dx, dy), model.reference_distance_m);
    const radio::BudgetResult base = radio::log_distance_path_loss_db(model, d);
    if (base.status != lora::Status::Ok) {
        return EnvStatus::InvalidInput;
    }
    out.log_distance_db = base.value;
    out.total_db = base.value;

    const bool has_terrain = e.grid != nullptr;
    if (!has_terrain && e.obstacle_count == 0) {
        return EnvStatus::Ok;
    }
    if (std::hypot(dx, dy) < kMinDistanceM) {
        return EnvStatus::Ok;  // rayons de Fresnel indéfinis à très courte distance
    }

    // Altitudes des extrémités : émetteur = dispositif, récepteur = passerelle.
    const double ground_tx = has_terrain ? ground_elevation_m(*e.grid, tx_x_m, tx_y_m) : 0.0;
    const double ground_rx = has_terrain ? ground_elevation_m(*e.grid, rx_x_m, rx_y_m) : 0.0;
    const double z_tx = ground_tx + e.device_height_m;
    const double z_rx = ground_rx + e.gateway_height_m;
    const auto los = [&](double t) { return z_tx + t * (z_rx - z_tx); };

    // Pavés coupés par le segment, avec leur intervalle de paramètre.
    std::vector<Candidate> cands;
    for (std::size_t i = 0; i < e.obstacle_count; ++i) {
        const Obstacle& o = e.obstacles[i];
        double t0 = 0.0, t1 = 0.0;
        if (!clip_segment(o, tx_x_m, tx_y_m, rx_x_m, rx_y_m, t0, t1)) {
            continue;
        }
        const double cx = 0.5 * (o.x_min_m + o.x_max_m);
        const double cy = 0.5 * (o.y_min_m + o.y_max_m);
        cands.push_back(Candidate{i, t0, t1, has_terrain ? ground_elevation_m(*e.grid, cx, cy) : 0.0});
    }

    // Pénétration : le rayon est sous le sommet à l'entrée ou à la sortie du pavé.
    for (const Candidate& c : cands) {
        const Obstacle& o = e.obstacles[c.index];
        const double top = c.ground_m + o.height_m;
        const double lowest = std::min(los(c.t0), los(c.t1));
        if (lowest < top) {
            out.penetration_db += o.attenuation_db;
        }
    }

    // Diffraction : profil discrétisé (sol ou sommet de pavé), puis Deygout à 3 arêtes.
    const double step = has_terrain ? e.grid->cell_m : kProfileStepM;
    const double total_m = std::hypot(dx, dy);
    const std::size_t n = std::clamp<std::size_t>(
        static_cast<std::size_t>(std::ceil(total_m / step)), 2, kMaxProfileSamples);
    std::vector<double> dist(n + 1);
    std::vector<double> obstruction(n + 1);
    double max_h = -std::numeric_limits<double>::infinity();
    for (std::size_t s = 0; s <= n; ++s) {
        const double t = static_cast<double>(s) / static_cast<double>(n);
        dist[s] = t * total_m;
        if (s == 0) {
            obstruction[s] = z_tx;
            continue;
        }
        if (s == n) {
            obstruction[s] = z_rx;
            continue;
        }
        const double x = tx_x_m + t * dx;
        const double y = tx_y_m + t * dy;
        double top = has_terrain ? ground_elevation_m(*e.grid, x, y) : 0.0;
        for (const Candidate& c : cands) {
            if (t < c.t0 || t > c.t1) continue;
            const Obstacle& o = e.obstacles[c.index];
            if (x < o.x_min_m || x > o.x_max_m || y < o.y_min_m || y > o.y_max_m) continue;
            top = std::max(top, c.ground_m + o.height_m);
        }
        obstruction[s] = top;
        max_h = std::max(max_h, top - los(t));
    }
    // Diffraction seulement si une obstruction dépasse réellement la ligne de visée :
    // un sol sous le rayon est déjà couvert par le modèle log-distance calibré.
    if (max_h > 0.0) {
        const Profile profile{dist.data(), obstruction.data(),
                              kSpeedOfLight / model.frequency_hz};
        out.diffraction_db = deygout_loss_db(profile, 0, n, 2);
    }
    out.total_db = out.log_distance_db + out.diffraction_db + out.penetration_db;
    return EnvStatus::Ok;
}

EnvStatus coverage_radii_m(const radio::LogDistanceModel& model, double gateway_x_m,
                           double gateway_y_m, const Environment& e, double max_path_loss_db,
                           double step_m, std::size_t azimuths, double* radii_out) {
    if (radii_out == nullptr || azimuths == 0 || azimuths > kMaxAzimuths ||
        !finite(gateway_x_m) || !finite(gateway_y_m) || !finite(max_path_loss_db) ||
        !finite(step_m) || step_m < kMinCoverageStepM) {
        return EnvStatus::InvalidInput;
    }
    const EnvStatus vs = validate_environment(e);
    if (vs != EnvStatus::Ok) {
        return vs;
    }
    // Sans relief ni obstacle, la portée log-distance est une borne haute exacte :
    // les termes ajoutés (diffraction, pénétration) ne font qu'augmenter la perte.
    const radio::BudgetResult bound = radio::max_range_m(model, max_path_loss_db);
    if (bound.status != lora::Status::Ok) {
        return EnvStatus::InvalidInput;
    }
    const double range = bound.value;
    const double steps = std::ceil(range / step_m) + 1.0;
    // Borne de travail réaliste : azimuts x pas de recherche x échantillons du profil
    // (portée / pas du profil, plafonné) x (1 + obstacles). Refus avant tout calcul.
    const double profile_step = e.grid != nullptr ? e.grid->cell_m : kProfileStepM;
    const double samples = std::min(std::max(2.0, range / profile_step),
                                    static_cast<double>(kMaxProfileSamples));
    const double work = static_cast<double>(azimuths) * steps * samples *
                        (1.0 + static_cast<double>(e.obstacle_count));
    if (work > kMaxCoverageWork) {
        return EnvStatus::WorkLimit;
    }

    const auto ok_at = [&](double theta, double r) {
        PathLoss pl;
        const double px = gateway_x_m + r * std::cos(theta);
        const double py = gateway_y_m + r * std::sin(theta);
        if (path_loss_db(model, px, py, gateway_x_m, gateway_y_m, e, pl) != EnvStatus::Ok) {
            return false;
        }
        return pl.total_db <= max_path_loss_db;
    };

    constexpr double kTwoPi = 6.283185307179586;
    for (std::size_t k = 0; k < azimuths; ++k) {
        const double theta = kTwoPi * static_cast<double>(k) / static_cast<double>(azimuths);
        double last_ok = 0.0;
        double first_fail = -1.0;
        for (double r = step_m; ; r += step_m) {
            const double rr = std::min(r, range);
            if (ok_at(theta, rr)) {
                last_ok = rr;
            } else {
                first_fail = rr;
                break;
            }
            if (rr >= range) {
                break;
            }
        }
        if (first_fail > 0.0) {
            // Raffinement dichotomique entre le dernier succès et le premier échec.
            double lo = last_ok;
            double hi = first_fail;
            for (int it = 0; it < kCoverageBisections; ++it) {
                const double mid = 0.5 * (lo + hi);
                if (ok_at(theta, mid)) {
                    lo = mid;
                } else {
                    hi = mid;
                }
            }
            last_ok = lo;
        }
        radii_out[k] = last_ok;
    }
    return EnvStatus::Ok;
}

}  // namespace lsim::env
