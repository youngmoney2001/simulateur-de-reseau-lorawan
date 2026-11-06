// SPDX-License-Identifier: Apache-2.0
// Couche physique LoRa : temps d'antenne (time-on-air) et paramètres radio.
//
// Principes de conception :
//   * Arithmétique entière en nanosecondes : résultats déterministes et
//     reproductibles d'une plateforme à l'autre (pas d'erreurs d'arrondi flottant).
//   * Aucune exception, aucune allocation dynamique : chaque entrée est validée
//     et le statut d'erreur est explicite (sécurité et prévisibilité).
//   * Aucune donnée non vérifiée n'atteint les calculs.
#pragma once

#include <cstdint>

// Surface exportée explicite (le reste des symboles reste masqué).
#if defined(_WIN32)
#  define LSIM_API __declspec(dllexport)
#else
#  define LSIM_API __attribute__((visibility("default")))
#endif

namespace lsim::lora {

// Statut de retour explicite. Aucune exception n'est levée dans le cœur.
enum class Status : std::int32_t {
    Ok = 0,
    InvalidSpreadingFactor = 1,  // SF hors de 7..12
    InvalidBandwidth = 2,        // BW hors de {125, 250, 500} kHz
    InvalidCodingRate = 3,       // CR hors de 1..4 (4/5 à 4/8)
    InvalidPayloadSize = 4,      // charge utile hors de 0..255 octets
    InvalidPreamble = 5,         // préambule hors de 6..65535 symboles
    NullOutput = 6,              // pointeur de sortie nul (API C)
    UncalibratedSensitivity = 7, // sensibilité non vérifiée pour cette BW
    InvalidParameter = 8,        // paramètre physique non fini ou hors domaine
};

// Largeur de bande supportée par la modulation LoRa.
enum class Bandwidth : std::uint32_t {
    Bw125kHz = 125'000,
    Bw250kHz = 250'000,
    Bw500kHz = 500'000,
};

// Configuration radio d'une trame. Les valeurs par défaut correspondent
// à la configuration LoRaWAN la plus courante (SF7, 125 kHz, CR 4/5).
struct RadioConfig {
    std::uint8_t spreading_factor = 7;          // 7..12
    Bandwidth bandwidth = Bandwidth::Bw125kHz;  // 125/250/500 kHz
    std::uint8_t coding_rate = 1;               // 1..4  => 4/5 .. 4/8
    std::uint16_t preamble_symbols = 8;         // LoRaWAN : 8 symboles
    bool crc_on = true;                         // CRC de charge utile
    bool explicit_header = true;                // en-tête explicite (LoRaWAN)
    bool low_data_rate_optimize = false;        // obligatoire si Tsym > 16 ms
};

// Résultat : statut + valeur en nanosecondes (valide uniquement si Ok).
struct AirtimeResult {
    Status status;
    std::int64_t nanoseconds;
};

// Durée d'un symbole en nanosecondes : 2^SF / BW.
// Entier exact pour toutes les BW standard (voir lora_phy.cpp).
LSIM_API std::int64_t symbol_duration_ns(std::uint8_t spreading_factor, Bandwidth bw);

// Sensibilité récepteur (dBm) à PER 1 %, SX1276 mode LoRa, 125 kHz, CR 4/5.
// Valeurs issues du datasheet Semtech SX1276/77/78/79 (SF7 à SF12).
// Blocs RFS_L125/250/500_HF (LnaBoost, bande 1, chemin Rx/Tx séparé) ;
// SF7..SF12. Les autres largeurs renvoient UncalibratedSensitivity.
LSIM_API Status receiver_sensitivity_dbm(std::uint8_t spreading_factor,
                                         Bandwidth bw, double& out_dbm);

// Profil de récepteur. Chaque profil est une référence distincte : ne pas les mélanger.
enum class ReceiverProfile : std::uint32_t {
    Sx1276Reference = 0,  // table ci-dessus (défaut, historique) : SF7..SF12
    Sx1303Gateway = 1,    // SX1303 datasheet, 125 kHz, SF5..SF12 (PER 10 %, 12 octets, SX1250)
};

// Sensibilité selon le profil. Sx1303Gateway : 125 kHz seulement (SF5 à SF12) ; les autres
// largeurs renvoient UncalibratedSensitivity. Sx1276Reference est identique à la version
// sans profil. Le profil Sx1303Gateway n'est pas utilisable pour un dispositif (pas de valeur).
LSIM_API Status receiver_sensitivity_dbm(std::uint8_t spreading_factor, Bandwidth bw,
                                         ReceiverProfile profile, double& out_dbm);

// Vérifie la cohérence d'une configuration radio.
LSIM_API Status validate(const RadioConfig& cfg, std::uint32_t payload_bytes);

// Temps d'antenne d'une trame, selon la formule de la note Semtech AN1200.13.
// Calcul entier exact, sans erreur d'arrondi.
LSIM_API AirtimeResult time_on_air(const RadioConfig& cfg, std::uint32_t payload_bytes);

// Conseil standard : l'optimisation bas débit est requise quand Tsym > 16 ms.
LSIM_API bool low_data_rate_required(std::uint8_t spreading_factor, Bandwidth bw);

}  // namespace lsim::lora
