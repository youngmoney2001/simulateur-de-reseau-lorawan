// SPDX-License-Identifier: Apache-2.0
// Écriture atomique des sorties de lsim_simulate_closed_loop_v3 (étape 6.2.5).
// En-tête C++ interne, hors API publique (les symboles publics sont dans c_api.h). Aucune simulation ici : les résultats moteur sont fournis.
#pragma once

#include <cstdint>
#include <vector>

#include "lsim/c_api.h"
#include "lsim/engine.hpp"

namespace lsim::sim::abi_v3 {

// Résultats moteur, en mémoire interne. Rien n'est écrit dans les sorties utilisateur avant
// la décision de `emit_closed_loop_v3`.
struct EngineOutputs {
    std::vector<DeviceStats> per_device;   // device_count entrées
    SimulationStats totals;
    LoopResult result;                     // uplinks, downlinks, gateway_busy, file MAC
    LoopChannelIo io;                      // io.trace (si trace v3 activée), io.terminals (device_count)
};

// Écrit les sorties v3 de façon atomique. Ordre des contrôles :
//  1. validation des arguments (validate_closed_loop_v3_args) : aucune écriture si invalide ;
//  2. `engine_status` non nul (erreur moteur, code déjà publié) : aucune écriture ;
//  3. capacités, dans l'ordre gelé en 6.1 : uplinks (SIM + TraceBufferTooSmall), downlinks et busy
//     (PLAN + 4), trace (CHANNEL + 16), terminaux (CHANNEL + 17). Une capacité insuffisante n'écrit
//     que les compteurs requis (uplink_count, downlink_count, busy_count, trace_count, terminal_count) ;
//  4. succès : toutes les conversions sont préparées, puis copiées ; per_device, totals,
//     mac_counters (si non NULL), buffers et compteurs sont écrits.
// Convention `terminals` : un buffer NULL vaut capacité 0. Avec device_count > 0, cela donne
// TERMINAL_BUFFER_TOO_SMALL. `trace` n'est écrite que si trace_enabled == 1.
// Retourne 0 ou le code d'erreur.
std::int32_t emit_closed_loop_v3(const lsim_closed_loop_v3_args* args, std::int32_t engine_status,
                                 const EngineOutputs& out);

}  // namespace lsim::sim::abi_v3
