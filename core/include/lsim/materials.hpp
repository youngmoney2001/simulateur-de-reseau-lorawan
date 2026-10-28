// SPDX-License-Identifier: Apache-2.0
// Atténuation des matériaux de construction (pavés), modèle de la
// Recommandation UIT-R P.2040-4 (09/2025) :
//   ε′(f) = a · f^b          (éq. 57, f en GHz)
//   σ(f)  = c · f^d  [S/m]   (éq. 58)
//   A     = 1636 · σ / √ε′   [dB/m]  (éq. 27a, diélectrique à faible pertes)
// Coefficients : Tableau 3 de la Recommandation (lignes diélectriques uniquement ;
// le métal et les sols sont exclus). Les plages de fréquences du tableau ne sont
// pas strictes : une fréquence hors plage utilise la ligne la plus proche et
// est signalée (`extrapolated`).
#pragma once

#include <cstdint>

#include "lsim/lora_phy.hpp"

namespace lsim::materials {

enum class Material : std::uint8_t {
    Air = 0,
    Concrete,
    Brick,
    Plasterboard,
    Wood,
    Glass,
    AcrylicGlass,
    CeilingPanel,
    ChipboardPanel,
    Plywood,
    Marble,
    FloorPanel,
    VinylTile,
    CarpetTile,
    BituminousAsphalt,
};

// Nombre de matériaux (identifiants 0 .. kMaterialCount-1, ordre de l'enum).
inline constexpr std::uint32_t kMaterialCount = 15;

struct AttenuationResult {
    double relative_permittivity = 0.0;  // ε′ à la fréquence demandée
    double conductivity_s_per_m = 0.0;   // σ à la fréquence demandée
    double db_per_m = 0.0;               // A, dB par mètre de matériau
    bool extrapolated = false;           // f hors de la plage documentée de la ligne
};

// Atténuation par mètre de matériau à `frequency_hz`. Renvoie Ok, ou
// lora::Status::InvalidParameter si la fréquence est non finie ou non positive.
lora::Status attenuation_db_per_m(Material material, double frequency_hz,
                                     AttenuationResult& out);

// Perte totale d'une traversée de dalle monocouche en incidence normale, air → dalle → air
// (UIT-R P.2040-4, éq. 43b avec θ = 0, ε_rc = ε′ − jσ/(ωε₀), éq. 10-11 et 44) : pertes aux
// deux interfaces (éq. 37a) et réflexions multiples inclus. Vaut 0 pour une épaisseur nulle.
lora::Status traversal_loss_db(Material material, double frequency_hz,
                               double thickness_m, double& out_db);

// Terme « matériau seul » : A × épaisseur (éq. 27a), sans pertes aux interfaces.
lora::Status material_only_loss_db(Material material, double frequency_hz,
                                   double thickness_m, double& out_db);

}  // namespace lsim::materials
