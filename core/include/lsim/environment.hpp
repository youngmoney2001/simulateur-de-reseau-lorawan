// SPDX-License-Identifier: Apache-2.0
// Environnement radio : relief (grille d'altitudes) et obstacles (pavés).
//
// Modèle (simplifié, à calibrer par campagne de mesures) :
//   PL = PL_log-distance(d_horizontal)
//        + diffraction (Deygout à 3 arêtes : approximation de Lee de l'intégrale de
//          Fresnel-Kirchhoff sur l'arête principale puis sur deux arêtes secondaires)
//        + pénétration (somme des atténuations des pavés traversés sous leur sommet)
//
// Règles :
//   * sans environnement, le résultat est identique au modèle log-distance ;
//   * le relief hors grille est pris au bord le plus proche (clamp), explicite ;
//   * tous les tableaux sont dimensionnés à partir de limites explicites ;
//   * aucune exception : les statuts sont renvoyés.
#pragma once

#include <cstddef>
#include <cstdint>
#include <vector>

#include "lsim/link_budget.hpp"

namespace lsim::env {

inline constexpr std::size_t kMaxGridCells = 4'000'000;
inline constexpr std::size_t kMaxObstacles = 10'000;
// Produit dispositifs x obstacles : borne du travail de calcul du simulateur.
inline constexpr std::uint64_t kMaxObstacleChecks = 50'000'000ULL;  // ex. 10 000 x 5 000
inline constexpr std::size_t kMaxProfileSamples = 2048;

enum class EnvStatus : std::int32_t {
    Ok = 0,
    InvalidGrid = 1,
    GridTooLarge = 2,
    InvalidObstacle = 3,
    TooManyObstacles = 4,
    InvalidInput = 5,
    WorkLimit = 6,
};

// Grille régulière d'altitudes (m), ligne par ligne (z[iy * nx + ix]).
// Le sommet (ix, iy) est en (origin_x + ix * cell, origin_y + iy * cell).
struct ElevationGrid {
    double origin_x_m = 0.0;
    double origin_y_m = 0.0;
    double cell_m = 30.0;
    std::uint32_t nx = 0;
    std::uint32_t ny = 0;
    std::vector<float> z;
};

// Pavé vertical : emprise rectangulaire, sommet à `height_m` au-dessus du sol local.
struct Obstacle {
    double x_min_m = 0.0;
    double y_min_m = 0.0;
    double x_max_m = 0.0;
    double y_max_m = 0.0;
    double height_m = 0.0;
    double attenuation_db = 0.0;  // perte par traversée sous le sommet
};

// Environnement non possédé : l'appelant garde les données vivantes pendant l'appel.
struct Environment {
    const ElevationGrid* grid = nullptr;     // nullable : terrain plat
    const Obstacle* obstacles = nullptr;     // nullable si count == 0
    std::size_t obstacle_count = 0;
    double gateway_height_m = 15.0;
    double device_height_m = 1.5;
};

struct PathLoss {
    double total_db = 0.0;
    double log_distance_db = 0.0;
    double diffraction_db = 0.0;
    double penetration_db = 0.0;
};

// Construit une grille (copie les valeurs). Valide dimensions, pas et valeurs finies.
LSIM_API EnvStatus make_elevation_grid(double origin_x_m, double origin_y_m, double cell_m,
                                       std::uint32_t nx, std::uint32_t ny, const float* values,
                                       std::size_t count, ElevationGrid& out);

// Vérifie un environnement complet (obstacles finis, boîtes non vides, bornes).
LSIM_API EnvStatus validate_environment(const Environment& e);

// Altitude du sol (m) au point (x, y) : interpolation bilinéaire, clamp au bord.
LSIM_API double ground_elevation_m(const ElevationGrid& grid, double x_m, double y_m);

// Perte de propagation totale entre émetteur et récepteur.
// Retourne un statut ; `out` n'est renseigné qu'en cas de succès.
LSIM_API EnvStatus path_loss_db(const radio::LogDistanceModel& model, double tx_x_m, double tx_y_m,
                                double rx_x_m, double rx_y_m, const Environment& env,
                                PathLoss& out);

// Portée réelle par azimut (m) : distance maximale où la perte totale (relief et
// obstacles inclus) reste sous `max_path_loss_db`. Le dispositif tourne autour de la
// passerelle (position de référence) ; `radii_out` reçoit `azimuths` valeurs.
// Recherche par pas puis dichotomie entre le dernier succès et le premier échec
// (le premier échec est retenu : pas de portée « trouée » surestimée).
// Borne haute : la portée log-distance (les termes ajoutés ne font qu'augmenter la perte).
LSIM_API EnvStatus coverage_radii_m(const radio::LogDistanceModel& model, double gateway_x_m,
                                    double gateway_y_m, const Environment& e,
                                    double max_path_loss_db, double step_m,
                                    std::size_t azimuths, double* radii_out);

}  // namespace lsim::env
