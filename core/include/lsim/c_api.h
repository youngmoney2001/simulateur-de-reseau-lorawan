/* SPDX-License-Identifier: Apache-2.0
 * API C stable du cœur lsim. Frontière d'interopérabilité avec Python (ctypes)
 * et tout autre langage. Aucune exception ne traverse cette frontière.
 */
#ifndef LSIM_C_API_H
#define LSIM_C_API_H

#include <stddef.h>
#include <stdint.h>

#if defined(_WIN32)
#  define LSIM_API __declspec(dllexport)
#else
#  define LSIM_API __attribute__((visibility("default")))
#endif

#ifdef __cplusplus
extern "C" {
#endif

/* Codes de statut par domaine (plages disjointes) :
 *   0        succès
 *   1..99    PHY et lien radio (lora::Status, valeur directe)
 *   100..199 crypto (crypto::CryptoStatus + 100)
 *   200..249 trame sécurisée (SecureStatus + 200)
 *   250..299 codec de trame (FrameStatus + 250)
 *   300..399 simulateur (SimStatus + 300)
 *   400..449 jointure OTAA (JoinStatus + 400)
 *   900      erreur interne (exception interceptée à la frontière)
 */
#define LSIM_STATUS_CRYPTO_BASE 100
#define LSIM_STATUS_SECURE_BASE 200
#define LSIM_STATUS_FRAME_BASE  250
#define LSIM_STATUS_SIM_BASE    300
#define LSIM_STATUS_ENV_BASE    500
#define LSIM_STATUS_JOIN_BASE   400
#define LSIM_STATUS_INTERNAL    900

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

/* ---------------------------------------------------------------- Clés 1.1 */

/* Clés de jointure dérivées de NwkKey et DevEUI. */
typedef struct lsim_join_keys {
    uint8_t js_enc_key[16];
    uint8_t js_int_key[16];
} lsim_join_keys;

/* Clés de session LoRaWAN 1.1. */
typedef struct lsim_session_keys_11 {
    uint8_t f_nwk_s_int_key[16];
    uint8_t s_nwk_s_int_key[16];
    uint8_t nwk_s_enc_key[16];
    uint8_t app_s_key[16];
} lsim_session_keys_11;

/* Dérivation des clés de jointure. DevEUI en ordre de transmission (LSB first). */
LSIM_API int32_t lsim_derive_join_keys(const uint8_t nwk_key[16],
                                       const uint8_t dev_eui[8],
                                       lsim_join_keys* out);

/* Dérivation des clés de session 1.1. join_nonce 3 octets, join_eui 8,
 * dev_nonce 2 octets, tous en ordre de transmission (LSB first). */
LSIM_API int32_t lsim_derive_session_keys_11(const uint8_t nwk_key[16],
                                             const uint8_t app_key[16],
                                             const uint8_t join_nonce[3],
                                             const uint8_t join_eui[8],
                                             const uint8_t dev_nonce[2],
                                             lsim_session_keys_11* out);

/* ------------------------------------------------------- Trame sécurisée */

/* Trame uplink à plat. Les FOpts ne sont pas exposés par l'API C. */
typedef struct lsim_uplink_frame {
    uint32_t dev_addr;
    uint8_t  mtype;          /* 2 = unconfirmed up, 4 = confirmed up */
    uint8_t  adr;
    uint8_t  adr_ack_req;
    uint8_t  ack;
    uint8_t  class_b;
    uint16_t fcnt;           /* 16 bits de poids faible */
    uint8_t  has_fport;
    uint8_t  fport;
    uint8_t  payload_len;    /* <= 242 */
    uint8_t  payload[242];   /* entrée de seal : clair ; sortie de open : clair */
    uint8_t  mic[4];         /* sortie de seal ; ignoré à l'entrée (recalculé) */
} lsim_uplink_frame;

/* Contexte du MIC et du chiffrement uplink 1.1, fourni par le serveur de réseau. */
typedef struct lsim_uplink_context {
    uint16_t conf_fcnt;
    uint8_t  tx_dr;
    uint8_t  tx_ch;
    uint32_t fcnt32;         /* compteur complet 32 bits */
} lsim_uplink_context;

/* Scelle une trame uplink (chiffrement puis MIC 1.1). *out_written reçoit la
 * taille écrite, 0 en cas d'erreur. */
LSIM_API int32_t lsim_seal_uplink(const lsim_uplink_frame* frame,
                                  const lsim_session_keys_11* keys,
                                  const lsim_uplink_context* ctx,
                                  uint8_t* out, size_t cap, size_t* out_written);

/* Ouvre une trame uplink : MIC vérifié avant déchiffrement. En cas d'échec,
 * out->payload_len vaut 0 et aucune donnée claire n'est exposée. */
LSIM_API int32_t lsim_open_uplink(const uint8_t* in, size_t len,
                                  const lsim_session_keys_11* keys,
                                  const lsim_uplink_context* ctx,
                                  lsim_uplink_frame* out);

/* ------------------------------------------------------ Jointure OTAA 1.1 */

/* Join-request décodée : tous les champs en ordre de transmission (LSB first). */
typedef struct lsim_join_request {
    uint8_t join_eui[8];
    uint8_t dev_eui[8];
    uint8_t dev_nonce[2];
} lsim_join_request;

/* Join-accept en clair. dev_addr en valeur numérique ; l'encodage LE est interne. */
typedef struct lsim_join_accept {
    uint8_t  join_nonce[3];
    uint8_t  net_id[3];
    uint32_t dev_addr;
    uint8_t  dl_settings;      /* bit 7 = OptNeg */
    uint8_t  rx_delay;
    uint8_t  has_cflist;       /* 0 ou 1 */
    uint8_t  cflist[16];
} lsim_join_accept;

/* Encode une join-request (23 octets exactement). */
LSIM_API int32_t lsim_encode_join_request(const lsim_join_request* req,
                                          const uint8_t nwk_key[16],
                                          uint8_t out[23]);

/* Décode et vérifie le MIC d'une join-request (côté serveur). */
LSIM_API int32_t lsim_decode_join_request(const uint8_t* in, size_t len,
                                          const uint8_t nwk_key[16],
                                          lsim_join_request* out);

/* Encode un join-accept côté serveur : out doit contenir 33 octets ;
 * *out_len reçoit 17 ou 33. */
LSIM_API int32_t lsim_encode_join_accept(const lsim_join_accept* accept,
                                         const uint8_t nwk_key[16],
                                         const uint8_t dev_eui[8],
                                         const uint8_t join_eui[8],
                                         const uint8_t dev_nonce[2],
                                         uint8_t* out, size_t cap, size_t* out_len);

/* Ouvre un join-accept côté device : MIC vérifié avant exposition des champs. */
LSIM_API int32_t lsim_decode_join_accept(const uint8_t* in, size_t len,
                                         const uint8_t nwk_key[16],
                                         const uint8_t dev_eui[8],
                                         const uint8_t join_eui[8],
                                         const uint8_t dev_nonce[2],
                                         lsim_join_accept* out);

/* -------------------------------------------------------------- Simulateur */

typedef struct lsim_end_device {
    double   x_m;
    double   y_m;
    uint8_t  spreading_factor;   /* 7..12 */
    uint32_t payload_bytes;      /* 0..255 */
    double   tx_power_dbm;
    int64_t  start_offset_ns;    /* >= 0 */
    int64_t  period_ns;          /* > 0 */
    uint32_t messages;           /* >= 1 */
} lsim_end_device;

typedef struct lsim_gateway {
    double x_m;
    double y_m;
    double antenna_gain_dbi;
} lsim_gateway;

typedef struct lsim_propagation {
    double frequency_hz;
    double reference_distance_m;
    double exponent;             /* 1..6 */
    double capture_threshold_db; /* >= 0 */
    double shadowing_sigma_db;   /* 0..30 ; 0 = pas de shadowing */
    uint64_t shadowing_seed;     /* graine du tirage par dispositif */
} lsim_propagation;

typedef struct lsim_device_stats {
    uint64_t sent;
    uint64_t received;
    uint64_t lost_sensitivity;
    uint64_t lost_collision;
    uint64_t airtime_ns;        /* temps d'antenne cumulé (ns) */
} lsim_device_stats;

typedef struct lsim_sim_stats {
    uint64_t sent;
    uint64_t received;
    uint64_t lost_sensitivity;
    uint64_t lost_collision;
    uint64_t airtime_ns;                 /* somme des temps d'antenne (ns) */
    uint64_t gateway_busy_ns;            /* union des réceptions passerelle (ns) */
    uint64_t gateway_peak_concurrent;    /* trames simultanées maximales */
    int64_t  observation_ns;             /* fin dernière trame - début première */
    double   gateway_utilization;        /* busy / observation, dans [0, 1] */
} lsim_sim_stats;

/* Simule les liaisons montantes. per_device doit contenir device_count entrées ;
 * totals reçoit la somme. */
LSIM_API int32_t lsim_simulate_uplinks(const lsim_end_device* devices, size_t device_count,
                                       const lsim_gateway* gateway,
                                       const lsim_propagation* prop,
                                       lsim_device_stats* per_device,
                                       lsim_sim_stats* totals);

/* Environnement radio : relief et obstacles (voir lsim/environment.hpp). */
typedef struct lsim_obstacle {
    double x_min_m;
    double y_min_m;
    double x_max_m;
    double y_max_m;
    double height_m;
    double attenuation_db;       /* >= 0, par traversée sous le sommet */
} lsim_obstacle;

typedef struct lsim_environment {
    /* Relief : grid_z NULL = terrain plat. Sinon grid_z DOIT pointer vers au
     * moins grid_nx * grid_ny flottants (m), ligne par ligne. La taille ne peut
     * pas être vérifiée par le cœur : c'est un contrat de l'appelant. Les
     * dimensions sont bornées avant toute lecture. Les valeurs sont copiées. */
    const float* grid_z;
    uint32_t grid_nx;
    uint32_t grid_ny;
    double grid_origin_x_m;
    double grid_origin_y_m;
    double grid_cell_m;          /* > 0 */
    const lsim_obstacle* obstacles;   /* NULL si obstacle_count == 0 */
    size_t obstacle_count;
    double gateway_height_m;
    double device_height_m;
} lsim_environment;

/* Comme lsim_simulate_uplinks, avec relief et obstacles. env NULL = terrain plat. */
LSIM_API int32_t lsim_simulate_uplinks_env(const lsim_end_device* devices, size_t device_count,
                                           const lsim_gateway* gateway,
                                           const lsim_propagation* prop,
                                           const lsim_environment* env,
                                           lsim_device_stats* per_device,
                                           lsim_sim_stats* totals);

/* Portée réelle par azimut (relief et obstacles inclus) : radii_out reçoit
 * `azimuths` distances (m), autour de la passerelle. step_m >= 1 ;
 * azimuths in 1..720. Borne de travail refusée au-delà (statut 506). */
LSIM_API int32_t lsim_coverage_radii(const lsim_gateway* gateway, const lsim_propagation* prop,
                                     double max_path_loss_db, const lsim_environment* env,
                                     double step_m, size_t azimuths, double* radii_out);

#ifdef __cplusplus
}
#endif

#endif /* LSIM_C_API_H */
