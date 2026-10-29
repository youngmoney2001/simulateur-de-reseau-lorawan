// SPDX-License-Identifier: Apache-2.0
// Backhaul mesh par relais LoRa (style ChirpStack Gateway Mesh) : routes vers la
// passerelle frontière et relais saut par saut, avec demi-duplex et collisions.
// Seules les passerelles relaient ; les capteurs ne sont pas concernés.
#pragma once

#include <cstddef>
#include <cstdint>
#include <vector>

namespace lsim::mesh {

inline constexpr std::uint32_t kMaxHops = 8;        // valeur ChirpStack
inline constexpr std::size_t kMaxNodes = 64;        // kMaxGateways
inline constexpr std::size_t kMaxFrames = 5'000'000;

enum class Status : std::int32_t {
    Ok = 0,
    InvalidRadio = 1,        // SF, BW, CR, charge utile, préambule ou capture hors domaine
    InvalidInput = 2,        // pointeur nul ou dimension incohérente
    TooManyNodes = 3,
    TooManyFrames = 4,
    UnknownBorder = 5,
    BorderNotCapable = 6,    // la frontière doit avoir une radio mesh
    InvalidHops = 7,         // max_hops hors de 1..8
    UnknownNode = 8,         // trame reçue par un indice de passerelle inexistant
};

// Issue d'une trame au terme du relais.
enum class Loss : std::uint8_t {
    Delivered = 0,
    NoRoute = 1,
    HalfDuplex = 2,
    Collision = 3,
};

// Paramètres de la liaison mesh (toutes les passerelles identiques).
struct Radio {
    std::uint8_t spreading_factor = 12;   // 5..12
    std::uint8_t coding_rate = 1;         // 1 = 4/5 … 4 = 4/8
    std::uint32_t bandwidth_hz = 203'000; // doit valoir 203, 406, 812 ou 1625 kHz pour la sensibilité
    std::uint32_t payload_bytes = 32;     // 0..255
    std::uint32_t preamble_symbols = 8;   // 6..65535
    double capture_db = 6.0;              // >= 0
};

struct Frame {
    std::uint64_t frame_id = 0;
    std::uint32_t rx_node = 0;   // passerelle qui a reçu la trame sur la bande d'accès
    std::int64_t t_ns = 0;       // fin de réception sur l'accès
};

struct Delivery {
    std::uint64_t frame_id = 0;
    std::uint8_t delivered = 0;
    std::uint8_t loss = 0;       // Loss
    std::uint8_t hops = 0;       // sauts tentés (0 pour frontière directe ou sans route)
    std::int64_t latency_ns = -1;
};

// Temps d'antenne (ns) : AN1200.13, CRC activé, en-tête explicite, optimisation
// bas débit appliquée si Tsym > 16 ms. Arrondi au plus proche, moitié vers le pair.
Status airtime_ns(const Radio& radio, std::int64_t& out);

// Sensibilité SX1280 (dBm), mode basse consommation, CR 4/5, PER 1 % (DS Rev 3.0,
// table 6-1). Erreur si la bande n'est pas 203, 406, 812 ou 1625 kHz.
Status sensitivity_dbm(const Radio& radio, std::int32_t& out);

// Routes vers la frontière. rssi[i*n+j] : puissance reçue en j émise par i (dBm).
// Un lien i-j existe si les deux sens atteignent la sensibilité et si les deux
// nœuds sont « capable ». next[i] = indice du saut suivant ; next[border] = border ;
// -1 si aucune route dans max_hops.
Status routes(const Radio& radio, std::size_t n, const std::uint8_t* capable,
              const double* rssi, std::uint32_t border, std::uint32_t max_hops,
              std::int32_t* next);

// Relais des trames saut par saut (événements datés, file FIFO par émetteur).
Status forward(const Radio& radio, std::size_t n, const double* rssi,
               const std::int32_t* next, std::uint32_t border,
               const Frame* frames, std::size_t frame_count, Delivery* out);

}  // namespace lsim::mesh
