// SPDX-License-Identifier: Apache-2.0
// Moteur de classe B LoRaWAN 1.1 : décodage du beacon, randomisation du ping slot,
// calcul du prochain ping slot et suivi de la validité de la synchronisation.
//
// Sources : LoRaWAN 1.1 §12 (acquisition et beacon-less), §13 (timing des ping slots,
// randomisation), §15.2 (contenu du beacon). Temps en nanosecondes entières sur l'horloge
// locale du dispositif ; temps du beacon en secondes GPS modulo 2^32.
//
// Aucun état caché : le dispositif (DeviceClassB) est passé et renvoyé par l'appelant.
#pragma once

#include <cstddef>
#include <cstdint>

namespace lsim::lorawan::classb {

inline constexpr std::uint64_t kBeaconPeriodNs = 128'000'000'000ull;     // 128 s
inline constexpr std::uint64_t kBeaconReservedNs = 2'120'000'000ull;     // 2,120 s
inline constexpr std::uint64_t kBeaconGuardNs = 3'000'000'000ull;        // 3,000 s
inline constexpr std::uint64_t kSlotNs = 30'000'000ull;                  // 30 ms
inline constexpr std::uint32_t kSlotsPerWindow = 4096;                   // 2^12
inline constexpr std::uint64_t kBeaconlessNs = 120ull * 60ull * 1'000'000'000ull;  // 2 h
inline constexpr std::uint8_t kMaxPeriodicity = 7;

enum class ClassBStatus : std::int32_t {
    Ok = 0,
    InvalidParameter = 1,  // périodicité > 7, temps non monotone, trame trop courte
    CrcError = 2,          // CRC-16 de la partie commune du beacon fausse
    NotSynchronized = 3,   // aucun beacon reçu
    BeaconLost = 4,        // plus de beacon depuis 2 h : quitter la classe B
};

enum class BeaconState : std::uint8_t {
    NotSynchronized = 0,
    Synchronized = 1,  // beacon reçu depuis moins de 128 s
    BeaconLess = 2,    // au moins 128 s sans beacon, mais moins de 2 h : fonctionnement sans balise
    Lost = 3,          // 2 h ou plus sans beacon : quitter la classe B
};

struct BeaconCommon {
    std::uint32_t time_s = 0;  // BCNPayload.Time (secondes GPS modulo 2^32)
};

// Dispositif de classe B : dernier beacon reçu et paramètres de ping slot.
struct DeviceClassB {
    bool synchronized = false;
    std::uint64_t last_beacon_rx_ns = 0;   // horloge locale à la réception du beacon
    std::uint32_t last_beacon_time_s = 0;  // BCNPayload.Time de ce beacon
    std::uint32_t dev_addr = 0;
    std::uint8_t periodicity = 0;          // 0..7 (PingSlotInfoReq)
};

struct PingSlot {
    std::uint64_t start_ns = 0;             // début de la fenêtre (horloge locale)
    std::uint32_t slot_index = 0;           // N, dans 0..4095
    std::uint32_t beacon_time_s = 0;        // beaconTime de la période concernée
    std::uint64_t beacon_period_start_ns = 0;
};

// Décodage de la partie commune du beacon : RFU (rfu_len octets : 2 en EU868, 3 en US915),
// Time (4 octets, little-endian), CRC-16 sur RFU+Time (2 octets). Les octets suivants
// (GwSpecific) ne sont pas décodés ici.
ClassBStatus decode_beacon(const std::uint8_t* in, std::size_t len, std::uint8_t rfu_len,
                           BeaconCommon& out);

// CRC-16 du beacon : polynôme 0x1021, valeur initiale 0, sans réflexion ni XOR final.
// Reproduit l'exemple EU868 de la spec (0x7EA2 sur 00 00 00 00 02 CC).
std::uint16_t beacon_crc16(const std::uint8_t* data, std::size_t len);

// pingOffset = (Rand[0] + Rand[1]·256) mod pingPeriod,
// Rand = AES-128(0x00…00, beaconTime | DevAddr | pad16). Octets de beaconTime et DevAddr
// en little-endian. Le PDF ne fournit pas de vecteur numérique : formule seule (voir docs).
ClassBStatus ping_offset(std::uint32_t beacon_time_s, std::uint32_t dev_addr,
                         std::uint8_t periodicity, std::uint32_t& offset);

// Nombre de ping slots par période de beacon (pingNb = 2^(7-P)) et période en slots
// (pingPeriod = 2^(5+P)).
ClassBStatus ping_slot_count(std::uint8_t periodicity, std::uint32_t& ping_nb,
                             std::uint32_t& ping_period);

// Enregistre un beacon reçu à `rx_ns` (horloge locale). rx_ns ne doit pas être antérieur
// au beacon précédent.
ClassBStatus on_beacon(DeviceClassB& d, std::uint64_t rx_ns, std::uint32_t beacon_time_s);

// État de synchronisation à l'instant `now_ns`.
ClassBStatus beacon_state(const DeviceClassB& d, std::uint64_t now_ns, BeaconState& out);

// Prochain ping slot dont le début est >= now_ns. Renvoie BeaconLost au-delà de 2 h sans
// beacon. Le beaconTime d'une période sans beacon est celui du dernier beacon + 128 s par
// période écoulée (horloge du dispositif).
ClassBStatus next_ping_slot(const DeviceClassB& d, std::uint64_t now_ns, PingSlot& out);

}  // namespace lsim::lorawan::classb
