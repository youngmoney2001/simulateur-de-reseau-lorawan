// SPDX-License-Identifier: Apache-2.0
// Validation interne des arguments de lsim_simulate_closed_loop_v3 (étape 6.2.2).
// En-tête C++ interne, hors API publique (les symboles publics sont dans c_api.h), sans simulation ni écriture dans les sorties.
#pragma once

#include <cstdint>

#include "lsim/c_api.h"

namespace lsim::sim::abi_v3 {

// Version d'ABI attendue dans `lsim_closed_loop_v3_args::abi_version` et dans chaque élément de
// configuration canal. Valeur 3 : version de l'ABI v3.
inline constexpr std::uint32_t kClosedLoopV3AbiVersion = 3;

// Valide l'ensemble des arguments sans rien écrire. Retourne 0 si valide, sinon un code
// LSIM_STATUS_CHANNEL_* (base 1000) ou un code historique (dont SIM + TooManyDevices).
// Ordre de contrôle : pointeur d'arguments, alignement, en-tête, plan et mode canal, trace,
// pointeurs obligatoires, tailles et débordements, alignements, chevauchements,
// puis éléments de configuration canal (dispositif par dispositif, champ par champ).
// Les capacités de sortie ne sont pas contrôlées ici : elles le sont après simulation (6.2.5).
std::int32_t validate_closed_loop_v3_args(const lsim_closed_loop_v3_args* args);

}  // namespace lsim::sim::abi_v3
