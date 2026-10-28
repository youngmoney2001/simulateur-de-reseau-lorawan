// SPDX-License-Identifier: Apache-2.0
// Bilan énergétique d'un dispositif (charge et énergie par état).
//
// Sources des courants par défaut :
//   - Émetteur (IDDT, typ., Table 6) et récepteur LoRa (IDDR_L, bande 1, LnaBoost off,
//     Table 10), veille (IDDSL, Table 6) : Semtech SX1276 datasheet Rev. 4.
//       Tx : +20 dBm PA_BOOST 120 mA ; +17 dBm PA_BOOST 87 mA ; +13 dBm RFO 29 mA ;
//            +7 dBm RFO 20 mA.
//       Rx : 9,9 / 10,3 / 11,1 / 12,6 mA pour 7,8-62,5 / 125 / 250 / 500 kHz (bande 1).
//       Veille : 0,2 µA (typ.).
//   - Microcontrôleur de référence STM32L072 (fiche ST, « Down to 93 µA/MHz in Run mode »,
//     « 0.43 µA Stop mode ») : valeurs « à partir de » (cas optimal), à remplacer par la
//     table de consommation du modèle retenu.
// Alimentation 3,3 V : hypothèse de référence, à remplacer.
#pragma once

#include <cstdint>

#include "lsim/lora_phy.hpp"

namespace lsim::energy {

struct Profile {
    double supply_v = 3.3;                 // hypothèse de référence
    double rx_current_ma_125khz = 10.3;    // SX1276, bande 1, LnaBoost off (typ.)
    double rx_current_ma_250khz = 11.1;
    double rx_current_ma_500khz = 12.6;
    double sleep_current_ua = 0.2 + 0.43;  // radio (0,2 µA) + MCU en Stop (0,43 µA)
    double mcu_run_current_ma = 93e-3 * 32.0;  // 93 µA/MHz × 32 MHz (valeur optimale)
};

struct Result {
    double charge_c = 0.0;          // charge consommée (C)
    double energy_j = 0.0;          // énergie (J)
    double average_current_ua = 0.0;
};

// Courant d'émission (mA) pour une puissance demandée : point du datasheet le plus proche
// par valeur supérieure ou égale (estimation conservatrice). Puissance > 20 dBm refusée.
lora::Status tx_current_ma(double tx_power_dbm, double& out_ma);

// Courant de réception LoRa (mA) pour une largeur de bande.
lora::Status rx_current_ma(lora::Bandwidth bw, const Profile& p, double& out_ma);

// Énergie d'un dispositif sur `total_ns` : tx_ns, rx_ns et mcu_active_ns sont des durées
// en nanosecondes entières ; le reste est en veille. Refuse une somme supérieure à total_ns.
lora::Status device_energy(const Profile& p, double tx_power_dbm, lora::Bandwidth bw,
                           std::uint64_t tx_ns, std::uint64_t rx_ns,
                           std::uint64_t mcu_active_ns, std::uint64_t total_ns, Result& out);

}  // namespace lsim::energy
