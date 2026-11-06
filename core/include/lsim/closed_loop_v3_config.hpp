// SPDX-License-Identifier: Apache-2.0
// Liaison interne entre la configuration canal v3 (contrat 6.1) et le modèle du moteur (étape 6.2.3).
// En-tête C++ interne, hors API publique (les symboles publics sont dans c_api.h), sans simulation ni écriture dans les sorties v3.
#pragma once

#include <vector>

#include "lsim/c_api.h"
#include "lsim/engine.hpp"

namespace lsim::sim::abi_v3 {

// Vrai si les arguments demandent le mode historique : channels NULL, channel_count 0 et
// channel_plan NONE. Précondition : arguments validés par validate_closed_loop_v3_args.
bool is_historical_channel_mode(const lsim_closed_loop_v3_args& args);

// Traduit les éléments de configuration explicites en une entrée par dispositif (index = device_index).
// Un élément present = 0 reçoit les valeurs par défaut du moteur : loop_eu868_default_channels()
// pour le terminal et loop_eu868_plan().defaults pour la vue serveur (contrat 6.1).
// Précondition : mode explicite et arguments validés. Ne lit que les champs canal.
std::vector<LoopChannelConfig> build_channel_configs(const lsim_closed_loop_v3_args& args);

// Convertit la trace interne vers lsim_loop_trace_v3 (étape 6.2.4) : même ordre que l'entrée
// (déjà triée par temps, à égalité ordre d'insertion), valeurs et sentinelles du contrat 6.1.
// Ne touche à aucun buffer de sortie : la copie et les capacités relèvent de 6.2.5.
std::vector<lsim_loop_trace_v3> convert_trace_v3(const std::vector<LoopTraceEvent>& events);

}  // namespace lsim::sim::abi_v3
