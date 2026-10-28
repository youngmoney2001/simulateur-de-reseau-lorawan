/* SPDX-License-Identifier: Apache-2.0
 * API C stable du cœur lsim. Frontière d'interopérabilité avec Python (ctypes)
 * et tout autre langage. Aucune exception ne traverse cette frontière.
 */
#ifndef LSIM_C_API_H
#define LSIM_C_API_H

#include <stdint.h>

#if defined(_WIN32)
#  define LSIM_API __declspec(dllexport)
#else
#  define LSIM_API __attribute__((visibility("default")))
#endif

#ifdef __cplusplus
extern "C" {
#endif

typedef struct lsim_radio_config {
    uint8_t  spreading_factor;     /* 7..12 */
    uint32_t bandwidth_hz;         /* 125000, 250000 ou 500000 */
    uint8_t  coding_rate;          /* 1..4 (4/5 à 4/8) */
    uint16_t preamble_symbols;     /* >= 6 */
    uint8_t  crc_on;               /* 0 ou 1 */
    uint8_t  explicit_header;      /* 0 ou 1 */
    uint8_t  low_data_rate_optimize; /* 0 ou 1 */
} lsim_radio_config;

/* Version du cœur, encodée en 0xMMmmpp (majeur, mineur, correctif). */
LSIM_API uint32_t lsim_version(void);

/* Calcule le temps d'antenne en nanosecondes.
 * Retourne un code de statut (0 = OK, voir lora_phy.hpp). */
LSIM_API int32_t lsim_time_on_air_ns(const lsim_radio_config* cfg,
                            uint32_t payload_bytes,
                            int64_t* out_ns);

/* Sensibilité récepteur (dBm), 125 kHz uniquement pour l'instant. */
LSIM_API int32_t lsim_receiver_sensitivity_dbm(uint8_t spreading_factor,
                                               uint32_t bandwidth_hz,
                                               double* out_dbm);

/* Perte en espace libre (dB) : distance en m, fréquence en Hz. */
LSIM_API int32_t lsim_free_space_path_loss_db(double distance_m,
                                              double frequency_hz,
                                              double* out_db);

/* Perte log-distance (dB) avec distance de référence d0 (m) et exposant n. */
LSIM_API int32_t lsim_log_distance_path_loss_db(double distance_m,
                                                double frequency_hz,
                                                double reference_distance_m,
                                                double exponent,
                                                double* out_db);

/* Perte maximale admissible (dB) à partir d'un bilan de liaison (dBm, dBi, dB). */
LSIM_API int32_t lsim_max_allowable_path_loss_db(double tx_power_dbm,
                                                 double tx_antenna_gain_dbi,
                                                 double rx_antenna_gain_dbi,
                                                 double cable_losses_db,
                                                 double fade_margin_db,
                                                 double rx_sensitivity_dbm,
                                                 double* out_db);

/* Portée maximale (m) pour une perte maximale donnée (modèle log-distance). */
LSIM_API int32_t lsim_max_range_m(double max_path_loss_db,
                                  double frequency_hz,
                                  double reference_distance_m,
                                  double exponent,
                                  double* out_m);

#ifdef __cplusplus
}
#endif

#endif /* LSIM_C_API_H */
