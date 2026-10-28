// SPDX-License-Identifier: Apache-2.0
// Opportunités de réception descendante par classe (LoRaWAN 1.1 §10 classe A, §12-13
// classe B, §17 classe C). Fonctions pures, temps en nanosecondes entières sur l'horloge
// du dispositif. Le dispositif émet ses uplinks ; ces fonctions disent à partir de quand
// une requête de downlink peut être reçue.
//
// Hypothèses de modélisation (explicites) :
//  - une fenêtre de réception RX1 dure `rx_window_ns` (la spec ne fixe pas cette durée ici) ;
//  - en classe C, le dispositif n'écoute pas pendant son émission ni pendant RX1 ;
//  - en classe B, un ping slot est utilisable s'il ne chevauche aucune émission ni RX1 ;
//  - une fenêtre de ping slot est élargie de classb::PingSlot::window_half_ns de chaque côté.
#pragma once

#include <cstdint>
#include <vector>

#include "lsim/class_b.hpp"

namespace lsim::lorawan::downlink {

enum class DeviceClass : std::uint8_t { A = 0, B = 1, C = 2 };

// Intervalle demi-ouvert [start_ns, end_ns).
struct Window {
    std::int64_t start_ns = 0;
    std::int64_t end_ns = 0;
};

struct Timing {
    std::int64_t rx1_delay_ns = 1'000'000'000;  // RECEIVE_DELAY1 = 1 s
    std::int64_t rx2_delay_ns = 2'000'000'000;  // RECEIVE_DELAY2 = 2 s
    std::int64_t rx_window_ns = 1'000'000'000;  // durée de RX1 (hypothèse, voir en-tête)
};

enum class DownlinkStatus : std::int32_t {
    Ok = 0,
    InvalidParameter = 1,
    NoOpportunity = 2,  // aucune fenêtre trouvée (pas d'uplink, balise perdue, limite atteinte)
};

inline constexpr std::size_t kMaxSlotSearch = 1'000'000;  // borne de recherche classe B

// Trie et fusionne les intervalles (recouvrements et contacts). Résultat trié, disjoint.
std::vector<Window> merge_windows(std::vector<Window> w);

// Intervalles pendant lesquels un dispositif de classe C ne peut pas recevoir sur RX2 :
// son émission et sa fenêtre RX1. `uplinks` : émissions triées par début.
// La fenêtre courte RX2 entre fin d'émission et RX1 reste ouverte (pas de blocage).
DownlinkStatus class_c_blocked(const std::vector<Window>& uplinks, const Timing& t,
                               std::vector<Window>& out);

// Classe A : première fenêtre RX1 ou RX2 ouverte à `request_ns` ou après, issue d'un uplink.
// `uplinks` triées par début (fins croissantes : airtime constant par dispositif).
DownlinkStatus next_class_a(const std::vector<Window>& uplinks, std::int64_t request_ns,
                            const Timing& t, std::int64_t& opportunity_ns);

// Classe C : premier instant >= request_ns hors émission et hors RX1 (`blocked` fusionné).
DownlinkStatus next_class_c(const std::vector<Window>& blocked, std::int64_t request_ns,
                            std::int64_t& opportunity_ns);

// Paramètres de classe B d'un dispositif (la balise n'est pas un état : voir next_class_b).
struct ClassBProfile {
    std::uint32_t dev_addr = 0;
    std::uint8_t periodicity = 0;       // 0..7
    std::uint32_t clock_drift_ppm = 0;  // 0..1000
};

// Classe B : premier ping slot >= request_ns, élargi selon la dérive, qui ne chevauche
// aucune émission ni RX1 (`blocked` fusionné, voir class_c_blocked).
// Hypothèse : la passerelle émet une balise à chaque période de 128 s (temps 0 = début
// de simulation) et le dispositif la reçoit. Chaque candidat s'appuie donc sur la balise
// la plus récente. Le mode beacon-less (perte de balise) n'est pas déclenché ici.
DownlinkStatus next_class_b(const ClassBProfile& profile, const std::vector<Window>& blocked,
                            std::int64_t request_ns, std::int64_t& opportunity_ns);

}  // namespace lsim::lorawan::downlink
