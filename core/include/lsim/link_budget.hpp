// SPDX-License-Identifier: Apache-2.0
// Bilan de liaison et propagation (log-distance). Calculs en double :
// IEEE 754 sur une même plateforme est reproductible ; les entrées sont validées.
#pragma once

#include <cstdint>

#include "lsim/lora_phy.hpp"

namespace lsim::radio {

// Modèle log-distance : PL(d) = PL(d0) + 10 * n * log10(d / d0).
// PL(d0) est la perte en espace libre à la distance de référence d0.
struct LogDistanceModel {
    double frequency_hz = 868.1e6;   // fréquence porteuse
    double reference_distance_m = 1.0;  // d0
    double exponent = 2.0;           // n : 2 espace libre, 2.7-3.5 urbain, > 3 dense
};

// Paramètres du bilan de liaison (dBm, dBi, dB).
struct LinkBudget {
    double tx_power_dbm = 14.0;          // puissance émise
    double tx_antenna_gain_dbi = 0.0;
    double rx_antenna_gain_dbi = 0.0;
    double fade_margin_db = 0.0;         // marge de sécurité (masquage, bruit)
    double cable_losses_db = 0.0;        // pertes totales émission et réception
};

struct BudgetResult {
    lora::Status status;
    double value;  // valeur utile si status == Ok
};

// Perte en espace libre à la distance d (mètres) et fréquence f (Hz).
// Formule : FSPL = 20 log10(d) + 20 log10(f) - 147,55 (d en m, f en Hz).
LSIM_API BudgetResult free_space_path_loss_db(double distance_m, double frequency_hz);

// Perte log-distance à la distance d (mètres).
LSIM_API BudgetResult log_distance_path_loss_db(const LogDistanceModel& model,
                                                double distance_m);

// Perte maximale admissible (MAPL) : tout ce qui dépasse cette perte rend la
// trame non décodable, en tenant compte de la sensibilité et des marges.
LSIM_API BudgetResult maximum_allowable_path_loss_db(const LinkBudget& budget,
                                                     double rx_sensitivity_dbm);

// Portée maximale (mètres) pour une perte maximale donnée (inverse du modèle).
LSIM_API BudgetResult max_range_m(const LogDistanceModel& model,
                                  double max_path_loss_db);

}  // namespace lsim::radio
