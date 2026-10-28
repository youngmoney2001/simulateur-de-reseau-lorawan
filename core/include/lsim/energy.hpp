// SPDX-License-Identifier: Apache-2.0
// Bilan énergétique d'un dispositif (charge et énergie par état).
//
// Profils (identifiants stables, exposés par l'API C) :
//
// 0 — RAK4631 (module RAKwireless : nRF52840 + Semtech SX1262), fiche RAK :
//   - tension nominale 3,3 V ;
//   - émission LoRa, PA_BOOST : +17 dBm 92 mA ; +20 dBm 125 mA ;
//   - réception LoRa (37,5 kbit/s) : 17 mA, appliquée aux trois largeurs de bande ;
//   - veille LoRa et BLE : 2,0 µA.
//   Les courants module incluent le microcontrôleur : terme MCU séparé à 0.
//
// 1 — SX1262 (Semtech, datasheet) + STM32L072 (ST, fiche) :
//   - émission (réglage PA par défaut, datasheet v2.1) : +14 dBm 90 mA ; +17 dBm 95 mA ;
//     +20 dBm 102 mA ; +22 dBm 118 mA ;
//   - réception LoRa 125 kHz : 4,6 mA (datasheet) ; appliquée aussi à 250 et 500 kHz
//     (non publié par Semtech dans les extraits consultés : estimation) ;
//   - veille : SX1262 « OFF, cold start » 0,16 µA + STM32L072 Stop 0,43 µA (typ., −40 à 25 °C) ;
//     le démarrage à froid suppose la reconfiguration du SX1262 au réveil ;
//   - MCU actif : 93 µA/MHz × 32 MHz = 2,976 mA. C'est la valeur « jusqu'à » de la fiche ST :
//     une valeur basse, pas typique.
//
// Alimentation des deux profils : 3,3 V (hypothèse commune aux deux fiches).
//
// Règle d'émission : pour une puissance demandée P, on prend le point du profil dont la
// puissance est supérieure ou égale à P (conservateur). Au-delà du dernier point : refusé.
#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

#include "lsim/lora_phy.hpp"

namespace lsim::energy {

inline constexpr std::uint32_t kProfileRak4631 = 0;
inline constexpr std::uint32_t kProfileSx1262Stm32l072 = 1;
inline constexpr std::uint32_t kProfileCount = 2;

constexpr std::size_t kMaxTxPoints = 4;

struct TxPoint {
    double dbm;
    double ma;
};

struct Profile {
    const char* name;
    double supply_v;
    double rx_current_ma_125khz;
    double rx_current_ma_250khz;
    double rx_current_ma_500khz;
    double sleep_current_ua;
    double mcu_run_current_ma;
    std::array<TxPoint, kMaxTxPoints> tx_points;  // triés par puissance croissante
    std::size_t tx_point_count;
};

struct Result {
    double charge_c = 0.0;          // charge consommée (C)
    double energy_j = 0.0;          // énergie (J)
    double average_current_ua = 0.0;
};

// Profil par identifiant ; InvalidParameter si l'identifiant est inconnu.
lora::Status profile_from_id(std::uint32_t profile_id, const Profile*& out);

// Courant d'émission (mA) : point du profil de puissance >= demandée.
// InvalidParameter si la puissance dépasse le dernier point publié ou n'est pas finie.
lora::Status tx_current_ma(const Profile& p, double tx_power_dbm, double& out_ma);

// Courant de réception LoRa (mA) pour une largeur de bande.
lora::Status rx_current_ma(lora::Bandwidth bw, const Profile& p, double& out_ma);

// Énergie d'un dispositif sur `total_ns` : tx_ns, rx_ns et mcu_active_ns sont des durées
// en nanosecondes entières ; le reste est en veille. Refuse une somme supérieure à total_ns.
lora::Status device_energy(const Profile& p, double tx_power_dbm, lora::Bandwidth bw,
                           std::uint64_t tx_ns, std::uint64_t rx_ns,
                           std::uint64_t mcu_active_ns, std::uint64_t total_ns, Result& out);

// Durée d'écoute du préambule (ns entiers) : (n_préambule + 4,25) × Tsym.
// C'est la durée minimale utile pour détecter une trame de downlink.
lora::Status preamble_listen_ns(std::uint8_t spreading_factor, lora::Bandwidth bw,
                                std::uint16_t preamble_symbols, std::uint64_t& out_ns);

// Classe A : par uplink, deux fenêtres RX1 (RECEIVE_DELAY1 = 1 s) et RX2 (2 s), chacune
// ouverte pendant `rx_window_ns` (0 : durée du préambule calculée).
// `downlink_ns_total` : airtime total des downlinks reçus, ajouté en majorant.
// `mcu_ns_per_uplink` : traitement MCU par uplink (0 si non modélisé).
lora::Status device_energy_class_a(const Profile& p, double tx_power_dbm, lora::Bandwidth bw,
                                   std::uint8_t spreading_factor, std::uint16_t preamble_symbols,
                                   std::uint64_t uplinks, std::uint64_t airtime_ns,
                                   std::uint64_t rx_window_ns, std::uint64_t downlink_ns_total,
                                   std::uint64_t mcu_ns_per_uplink, std::uint64_t total_ns,
                                   Result& out);

}  // namespace lsim::energy
