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

#ifdef __cplusplus
}
#endif

#endif /* LSIM_C_API_H */
