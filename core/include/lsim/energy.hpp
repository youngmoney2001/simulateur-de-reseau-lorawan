// SPDX-License-Identifier: Apache-2.0
// Bilan énergétique d'un dispositif (charge et énergie par état).
//
// Profil par défaut : module RAKwireless RAK4631 (nRF52840 + Semtech SX1262), fiche RAK :
//   - tension nominale VBAT_SX / VDD_NRF : 3,3 V (plage 2,0 à 3,7 V) ;
//   - émission LoRa, PA_BOOST : +17 dBm 92 mA ; +20 dBm 125 mA ;
//   - réception LoRa (37,5 kbit/s) : 17 mA, appliquée à toutes les largeurs de bande
//     (pas de valeur par largeur dans la fiche : estimation conservatrice) ;
//   - veille LoRa et BLE : 2,0 µA.
// Les courants module incluent le microcontrôleur pendant l'émission et la réception :
// aucun terme MCU séparé par défaut (mcu_run_current_ma = 0).
// Contrôle croisé : Semtech SX1262 (datasheet v2.1, réglage PA par défaut) : +14 dBm 90 mA,
// +17 dBm 95 mA, +20 dBm 102 mA, +22 dBm 118 mA (puce seule, sans nRF52840).
//
// Règle d'émission : pour une puissance demandée P, on prend le point de la fiche module
// dont la puissance est supérieure ou égale à P (conservateur). P = 14 dBm donne 92 mA.
#pragma once

#include <cstdint>

#include "lsim/lora_phy.hpp"

namespace lsim::energy {

struct Profile {
    double supply_v = 3.3;                 // RAK4631, tension nominale
    double rx_current_ma_125khz = 17.0;    // RAK4631, Rx LoRa (valeur unique)
    double rx_current_ma_250khz = 17.0;
    double rx_current_ma_500khz = 17.0;
    double sleep_current_ua = 2.0;         // RAK4631, veille LoRa et BLE
    double mcu_run_current_ma = 0.0;       // inclus dans les courants module
};

struct Result {
    double charge_c = 0.0;          // charge consommée (C)
    double energy_j = 0.0;          // énergie (J)
    double average_current_ua = 0.0;
};

// Courant d'émission (mA) : point de la fiche module, puissance >= demandée (conservateur).
// Puissance > 20 dBm refusée (point non publié dans la fiche).
lora::Status tx_current_ma(double tx_power_dbm, double& out_ma);

// Courant de réception LoRa (mA) pour une largeur de bande.
lora::Status rx_current_ma(lora::Bandwidth bw, const Profile& p, double& out_ma);

// Énergie d'un dispositif sur `total_ns` : tx_ns, rx_ns et mcu_active_ns sont des durées
// en nanosecondes entières ; le reste est en veille. Refuse une somme supérieure à total_ns.
lora::Status device_energy(const Profile& p, double tx_power_dbm, lora::Bandwidth bw,
                           std::uint64_t tx_ns, std::uint64_t rx_ns,
                           std::uint64_t mcu_active_ns, std::uint64_t total_ns, Result& out);

}  // namespace lsim::energy
