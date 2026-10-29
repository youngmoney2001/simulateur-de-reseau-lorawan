// SPDX-License-Identifier: Apache-2.0
// Backhaul mesh par relais LoRa (style ChirpStack Gateway Mesh) : routes vers la
// passerelle frontière et relais saut par saut, avec demi-duplex et collisions.
// Seules les passerelles relaient ; les capteurs ne sont pas concernés.
//
// Suppression des doublons : chaque trame porte un identifiant (`frame_id`). Un relais
// ne transmet une trame qu'une fois. Il renonce à sa copie s'il entend, avant son
// propre départ, un autre relais transmettre la même trame (réception réussie).
#pragma once

#include <cstddef>
#include <cstdint>
#include <vector>

namespace lsim::mesh {

inline constexpr std::uint32_t kMaxHops = 8;        // valeur ChirpStack
inline constexpr std::size_t kMaxNodes = 64;        // kMaxGateways
inline constexpr std::size_t kMaxFrames = 5'000'000;
inline constexpr std::size_t kMaxReceptions = 50'000'000;  // mémoire : réceptions suivies

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
    TooManyReceptions = 9,   // trop de réceptions suivies : réduire la simulation
    BufferTooSmall = 10,     // journal des sauts plus grand que le tampon fourni (count renseigné)
};

// Issue d'une trame au terme du relais.
enum class Loss : std::uint8_t {
    Delivered = 0,
    NoRoute = 1,
    HalfDuplex = 2,
    Collision = 3,
    Suppressed = 4,          // aucune copie utile : un autre relais avait déjà transmis
};

// Sort d'une copie (une entrée par trame reçue à l'accès).
enum class CopyState : std::uint8_t {
    Forwarded = 0,           // le relais a transmis la copie
    Suppressed = 1,          // le relais a renoncé : un autre l'avait déjà transmise
    Border = 2,              // la passerelle a elle-même la frontière : remise directe
    NoRoute = 3,             // pas de route vers la frontière
};

// Issue d'un saut (une entrée par émission mesh et par intention, et par copie supprimée).
enum class HopOutcome : std::uint8_t {
    Received = 0,            // le saut prévu a reçu la copie
    LostCollision = 1,       // le saut prévu a été brouillé
    LostHalfDuplex = 2,      // le saut prévu émettait
    Suppressed = 3,          // copie abandonnée : un doublon avait déjà été relayé (pas d'émission)
};

// Journal d'un saut. Pour une émission : t_start/t_end de l'émission ; pour une copie
// supprimée : t_start = t_end = instant de la décision.
struct HopEvent {
    std::uint64_t frame_id = 0;
    std::uint32_t sender = 0;
    std::uint32_t receiver = 0;     // saut prévu (next[sender])
    std::int64_t t_start = 0;
    std::int64_t t_end = 0;
    std::uint8_t outcome = 0;       // HopOutcome
    std::uint8_t hop_index = 0;     // numéro du saut de la copie, 0 = premier
};

// Paramètres de la liaison mesh (toutes les passerelles identiques).
struct Radio {
    std::uint8_t spreading_factor = 12;   // 5..12
    std::uint8_t coding_rate = 1;         // 1 = 4/5 … 4 = 4/8
    std::uint32_t bandwidth_hz = 203'000; // doit valoir 203, 406, 812 ou 1625 kHz pour la sensibilité
    std::uint32_t payload_bytes = 32;     // 0..255 : taille par défaut (les trames portent la leur)
    std::uint32_t preamble_symbols = 8;   // 6..65535
    double capture_db = 6.0;              // >= 0
};

struct Frame {
    std::uint64_t frame_id = 0;  // identifiant de trame (un par émission de dispositif)
    std::uint32_t rx_node = 0;   // passerelle qui a reçu la trame sur la bande d'accès
    std::int64_t t_ns = 0;       // fin de réception sur l'accès
    // Taille relayée sur le mesh : trame LoRaWAN complète + enveloppe mesh (14 o en montant,
    // ChirpStack Gateway Mesh). Donne le temps d'antenne de chacune de ses émissions.
    std::uint32_t payload_bytes = 32;  // 0..255
};

struct Delivery {
    std::uint64_t frame_id = 0;
    std::uint8_t delivered = 0;   // la trame (toutes copies) a atteint la frontière
    std::uint8_t loss = 0;        // Loss ; 0 si livrée
    std::uint8_t hops = 0;        // sauts de la copie qui a atteint la frontière en premier
    std::uint8_t copy_state = 0;  // CopyState de cette copie
    std::int64_t latency_ns = -1; // depuis la première réception à l'accès ; -1 si non livrée
};

// Bilan agrégé d'un calcul.
struct Summary {
    std::uint64_t transmissions = 0;     // émissions mesh effectivement faites
    std::uint64_t suppressed = 0;        // copies abandonnées (doublon entendu)
    std::uint64_t lost_collision = 0;    // sauts perdus par collision
    std::uint64_t lost_half_duplex = 0;  // sauts perdus : récepteur en émission
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

// Relais des trames saut par saut.
// `suppress` : suppression des doublons par identifiant de trame. Sans suppression,
// chaque copie est relayée. `backoff_window_ns` : chaque relais attend, avant de
// transmettre une copie, un délai déterministe dans [0, fenêtre) propre à (relais,
// trame). Sans attente, deux relais qui reçoivent la même trame au même instant
// partent ensemble et ne peuvent pas s'entendre ; l'attente laisse au premier le temps
// d'être entendu par les autres. Les passerelles non capables n'entendent rien.
Status forward(const Radio& radio, std::size_t n, const std::uint8_t* capable,
               const double* rssi, const std::int32_t* next, std::uint32_t border,
               bool suppress, std::int64_t backoff_window_ns, const Frame* frames,
               std::size_t frame_count, Delivery* out, Summary* summary,
               std::vector<HopEvent>* log = nullptr);

}  // namespace lsim::mesh
