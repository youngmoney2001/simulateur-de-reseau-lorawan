// SPDX-License-Identifier: Apache-2.0
// Moteur de classe B LoRaWAN 1.1 : décodage du beacon (partie commune et GwSpecific),
// randomisation du ping slot, prochain ping slot avec fenêtre élargie par dérive
// d'horloge, suivi de la validité de la synchronisation, saut de fréquence US902-928.
//
// Sources : LoRaWAN 1.1 §12 (acquisition, beacon-less, dérive ±10 ppm ≈ ±1,3 ms par
// période), §13 (timing et randomisation des ping slots), §15.2 et §15.3 (contenu du
// beacon, GwSpecific), RP002-1.0.2 §2.5 (US902-928 : beacon et ping slot sur 8 canaux,
// ping slot « follows beacon channel »). Temps en nanosecondes entières sur l'horloge
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
inline constexpr std::uint32_t kMaxDriftPpm = 1000;                      // garde-fou (0,1 %)
inline constexpr std::uint8_t kUs902Channels = 8;

enum class ClassBStatus : std::int32_t {
    Ok = 0,
    InvalidParameter = 1,  // périodicité, dérive, temps non monotone, trame trop courte, RFU
    CrcError = 2,          // CRC-16 du beacon (partie commune ou GwSpecific) fausse
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

// GwSpecific (§15.3) : InfoDesc 0, 1 ou 2 => coordonnées de l'antenne (Lat, Lng sur 24 bits
// en complément à deux : -2^23 = -90°/-180°, 2^23-1 ≈ +90°/+180°). Autres InfoDesc : pas de
// coordonnées décodées (has_coordinates = false).
struct GatewayInfo {
    bool present = false;            // partie GwSpecific présente dans la trame
    std::uint8_t info_desc = 0;
    bool has_coordinates = false;
    double latitude_deg = 0.0;
    double longitude_deg = 0.0;
};

// Dispositif de classe B : dernier beacon reçu et paramètres de ping slot.
struct DeviceClassB {
    bool synchronized = false;
    std::uint64_t last_beacon_rx_ns = 0;   // horloge locale à la réception du beacon
    std::uint32_t last_beacon_time_s = 0;  // BCNPayload.Time de ce beacon
    std::uint32_t dev_addr = 0;
    std::uint8_t periodicity = 0;          // 0..7 (PingSlotInfoReq)
    std::uint32_t clock_drift_ppm = 0;     // dérive de l'horloge locale, 0..1000 ppm
};

struct PingSlot {
    std::uint64_t start_ns = 0;             // début nominal du slot (horloge locale)
    std::uint32_t slot_index = 0;           // N, dans 0..4095
    std::uint32_t beacon_time_s = 0;        // beaconTime de la période concernée
    std::uint64_t beacon_period_start_ns = 0;
    // Élargissement de la fenêtre d'écoute de chaque côté : dérive × temps écoulé depuis le
    // dernier beacon (arrondi supérieur). Hypothèse de modélisation, voir docs/ROADMAP.md.
    std::uint64_t window_half_ns = 0;
};

// Décodage de la partie commune : RFU (rfu_len : 2 en EU868, 3 en US915), Time (4 octets
// little-endian), CRC-16 sur RFU+Time (2 octets).
ClassBStatus decode_beacon(const std::uint8_t* in, std::size_t len, std::uint8_t rfu_len,
                           BeaconCommon& out);

// Décodage complet : partie commune puis GwSpecific (7 octets, CRC-16 sur GwSpecific+RFU).
// gw_rfu_len : 0 en EU868, 1 en US915. Trame acceptée si elle s'arrête après la partie
// commune (pas de GwSpecific) ou si elle a exactement la taille attendue.
ClassBStatus decode_beacon_full(const std::uint8_t* in, std::size_t len, std::uint8_t rfu_len,
                                std::uint8_t gw_rfu_len, BeaconCommon& common, GatewayInfo& gw);

// CRC-16 du beacon : polynôme 0x1021, valeur initiale 0, sans réflexion ni XOR final.
// Reproduit l'exemple EU868 de la spec (0x7EA2 sur 00 00 00 00 02 CC).
std::uint16_t beacon_crc16(const std::uint8_t* data, std::size_t len);

// pingOffset = (Rand[0] + Rand[1]·256) mod pingPeriod, Rand = AES-128(0x00…00,
// beaconTime | DevAddr | pad16). Octets de beaconTime et DevAddr en little-endian.
// Le PDF ne fournit pas de vecteur numérique : formule seule (voir docs/ROADMAP.md).
ClassBStatus ping_offset(std::uint32_t beacon_time_s, std::uint32_t dev_addr,
                         std::uint8_t periodicity, std::uint32_t& offset);

// pingNb = 2^(7-P) slots par période ; pingPeriod = 2^(5+P) slots.
ClassBStatus ping_slot_count(std::uint8_t periodicity, std::uint32_t& ping_nb,
                             std::uint32_t& ping_period);

// US902-928 : indice de canal du beacon et du ping slot de la période dont le beacon porte
// `beacon_time_s` : floor(beacon_time / 128) mod 8. Sources : RP002-1.0.2 (« hops across all
// 8 downlink channels » ; ping slot « follows beacon channel » ; définitions de beacon_time,
// beacon_period = 128 s et floor ; table des canaux 0 à 6 = 923,3 à 926,9 MHz). L'équation
// seule n'apparaît pas dans l'extrait lu : à relire dans le texte complet.
ClassBStatus us902_channel_index(std::uint32_t beacon_time_s, std::uint8_t& index);
// Fréquence du canal descendant d'indice 0..7 : 923,3 MHz + 0,6 MHz × index.
ClassBStatus us902_channel_frequency_hz(std::uint8_t index, std::uint32_t& freq_hz);

// Enregistre un beacon reçu à `rx_ns` (horloge locale). rx_ns ne doit pas être antérieur
// au beacon précédent.
ClassBStatus on_beacon(DeviceClassB& d, std::uint64_t rx_ns, std::uint32_t beacon_time_s);

// État de synchronisation à l'instant `now_ns`.
ClassBStatus beacon_state(const DeviceClassB& d, std::uint64_t now_ns, BeaconState& out);

// Prochain ping slot dont le début nominal est >= now_ns. Renvoie BeaconLost au-delà de 2 h
// sans beacon. Le beaconTime d'une période sans beacon est celui du dernier beacon + 128 s
// par période écoulée (horloge du dispositif).
ClassBStatus next_ping_slot(const DeviceClassB& d, std::uint64_t now_ns, PingSlot& out);

}  // namespace lsim::lorawan::classb
