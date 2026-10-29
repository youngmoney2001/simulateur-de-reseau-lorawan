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
 *   600..649 commandes MAC (mac::MacStatus + 600)
 *   650..699 rejoin-request (RejoinStatus + 650)
 *   700..749 registre serveur (RegistryStatus + 700 ; 740 handle inconnu, 741 paramètre invalide)
 *   800..849 relais mesh (mesh::Status + 800)
 *   900      erreur interne (exception interceptée à la frontière)
 */
#define LSIM_STATUS_CRYPTO_BASE 100
#define LSIM_STATUS_SECURE_BASE 200
#define LSIM_STATUS_FRAME_BASE  250
#define LSIM_STATUS_SIM_BASE    300
#define LSIM_STATUS_ENV_BASE    500
#define LSIM_STATUS_JOIN_BASE   400
#define LSIM_STATUS_MAC_BASE    600
#define LSIM_STATUS_MESH_BASE   800
#define LSIM_STATUS_REJOIN_BASE 650
#define LSIM_STATUS_REGISTRY_BASE 700
#define LSIM_STATUS_ADR_BASE    760
#define LSIM_STATUS_SESSION_BASE 780
#define LSIM_STATUS_CLASSB_BASE 800
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

/* Sensibilité récepteur (dBm), 125/250/500 kHz, SF7..SF12. */
LSIM_API int32_t lsim_receiver_sensitivity_dbm(uint8_t spreading_factor,
                                               uint32_t bandwidth_hz,
                                               double* out_dbm);

/* Atténuation des matériaux (UIT-R P.2040-4). material_id dans [0, count) ;
 * perte totale d'une dalle monocouche en incidence normale (interfaces incluses) ;
 * out_extrapolated = 1 si la fréquence est hors de la plage documentée. */
LSIM_API uint32_t lsim_material_count(void);
LSIM_API int32_t lsim_material_traversal_loss_db(uint32_t material_id,
                                                 double frequency_hz,
                                                 double thickness_m,
                                                 double* out_db,
                                                 int32_t* out_extrapolated);

/* Bilan énergétique d'un dispositif. profile_id : 0 = RAK4631, 1 = SX1262 + STM32L072
 * (voir energy.hpp). Durées en ns entiers ; le reste de total_ns est en veille. */
LSIM_API uint32_t lsim_energy_profile_count(void);
LSIM_API int32_t lsim_energy_device(uint32_t profile_id, double tx_power_dbm,
                                    uint32_t bandwidth_hz, uint64_t tx_ns, uint64_t rx_ns,
                                    uint64_t mcu_active_ns, uint64_t total_ns,
                                    double* out_energy_j, double* out_avg_current_ua);

/* Classe A : uplinks identiques ; deux fenêtres RX1/RX2 par uplink de rx_window_ns
 * (0 : durée du préambule), plus downlink_ns_total ; traitement MCU par uplink. */
LSIM_API int32_t lsim_energy_device_class_a(uint32_t profile_id, double tx_power_dbm,
                                            uint32_t bandwidth_hz, uint8_t spreading_factor,
                                            uint16_t preamble_symbols, uint64_t uplinks,
                                            uint64_t airtime_ns, uint64_t rx_window_ns,
                                            uint64_t downlink_ns_total,
                                            uint64_t mcu_ns_per_uplink, uint64_t total_ns,
                                            double* out_energy_j, double* out_avg_current_ua);

/* Courant d'émission (mA) : point du profil de puissance >= demandée. */
LSIM_API int32_t lsim_energy_tx_current_ma(uint32_t profile_id, double tx_power_dbm,
                                           double* out_ma);

/* Paramètres d'un profil (transparence : sources dans energy.hpp). */
LSIM_API int32_t lsim_energy_profile(uint32_t profile_id, double* supply_v,
                                     double* rx_ma_125khz, double* rx_ma_250khz,
                                     double* rx_ma_500khz, double* sleep_ua,
                                     double* mcu_run_ma);

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

/* Trame uplink à plat. FOpts (LoRaWAN 1.1) : chiffrés/déchiffrés avec NwkSEncKey. */
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
    uint8_t  fopts_len;      /* 0..15 ; FOpts interdits avec FPort 0 */
    uint8_t  fopts[15];      /* entrée de seal : clair ; sortie de open : clair */
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

/* Contexte downlink : ConfFCnt, NFCntDwn (FPort absent ou 0) et AFCntDwn (FPort > 0). */
typedef struct lsim_downlink_context {
    uint16_t conf_fcnt;
    uint32_t nfcnt32;
    uint32_t afcnt32;
} lsim_downlink_context;

/* Scelle / ouvre une trame downlink. lsim_uplink_frame sert aux deux sens
 * (nom historique). Le compteur retenu dépend du FPort (errata FCntDwn). */
LSIM_API int32_t lsim_seal_downlink(const lsim_uplink_frame* frame,
                                    const lsim_session_keys_11* keys,
                                    const lsim_downlink_context* ctx,
                                    uint8_t* out, size_t cap, size_t* out_written);
LSIM_API int32_t lsim_open_downlink(const uint8_t* in, size_t len,
                                    const lsim_session_keys_11* keys,
                                    const lsim_downlink_context* ctx,
                                    lsim_uplink_frame* out);

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

// Join-accept déclenché par une rejoin-request (1.1 §6.2.4.4) : JSEncKey, JSIntKey,
// JoinReqType = rejoin_type (0, 1 ou 2), RJcount remplace DevNonce. OptNeg obligatoire.
LSIM_API int32_t lsim_encode_rejoin_join_accept(const lsim_join_accept* accept,
                                                const uint8_t nwk_key[16],
                                                const uint8_t dev_eui[8],
                                                const uint8_t join_eui[8], uint8_t rejoin_type,
                                                uint16_t rjcount, uint8_t* out, size_t cap,
                                                size_t* out_len);
LSIM_API int32_t lsim_decode_rejoin_join_accept(const uint8_t* in, size_t len,
                                                const uint8_t nwk_key[16],
                                                const uint8_t dev_eui[8],
                                                const uint8_t join_eui[8], uint8_t rejoin_type,
                                                uint16_t rjcount, lsim_join_accept* out);

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
    double   duty_cycle;         /* ]0, 1] ; 1 = sans limite */
} lsim_end_device;

typedef struct lsim_gateway {
    double x_m;
    double y_m;
    double antenna_gain_dbi;
    double rx_sensitivity_offset_db; /* décalage du seuil montant (dB), |.| <= 20 ; 0 = sans profil */
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
    uint64_t lost_gateway_busy; /* reçue pendant une émission passerelle (demi-duplex) */
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
    uint64_t lost_gateway_busy;          /* trames perdues pendant une émission passerelle */
} lsim_sim_stats;

/* Période d'émission de la passerelle : [start_ns, end_ns), end > start. */
typedef struct lsim_interval {
    int64_t start_ns;
    int64_t end_ns;
} lsim_interval;

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

/* Trace par transmission (même moteur, mêmes temps que les compteurs). Une entrée par
 * émission, dans l'ordre temporel. records : capacité record_capacity ; record_count reçoit
 * le nombre réel. Si la capacité est insuffisante : statut 308 (LSIM_STATUS_SIM_BASE + 8)
 * et record_count indique la taille requise. Borne : 200 000 émissions par appel (statut 309).
 * outcome : 0 sous la sensibilité, 1 collision, 2 reçue. env NULL = terrain plat. */
typedef struct lsim_tx_record {
    uint32_t device_index;
    int64_t  start_ns;
    int64_t  end_ns;
    uint8_t  spreading_factor;
    double   rssi_dbm;
    uint8_t  outcome;
} lsim_tx_record;

LSIM_API int32_t lsim_simulate_uplinks_trace(const lsim_end_device* devices, size_t device_count,
                                             const lsim_gateway* gateway,
                                             const lsim_propagation* prop,
                                             const lsim_environment* env,
                                             lsim_device_stats* per_device,
                                             lsim_sim_stats* totals, lsim_tx_record* records,
                                             size_t record_capacity, size_t* record_count,
                                             const lsim_interval* gateway_busy,
                                             size_t gateway_busy_count);

/* Calendrier MAC (version 2 de la trace) : octets MAC réservés dans des émissions, comptés dans
 * le temps d'antenne. Réservation conservatrice : une émission réservée ne porte pas forcément
 * ces octets. Un doublon (même dispositif, même rang), un rang hors de 1..messages, extra_bytes
 * hors de 1..15 ou une charge dépassant 255 octets sont refusés. Sans réservation, identique à
 * lsim_simulate_uplinks_trace. */
typedef struct lsim_mac_reservation {
    uint32_t device_index;       /* index dans devices */
    uint32_t rank;               /* rang 1-based de l'émission du dispositif */
    uint32_t extra_bytes;        /* 1..15 */
} lsim_mac_reservation;

LSIM_API int32_t lsim_simulate_uplinks_trace_v2(const lsim_end_device* devices,
                                                size_t device_count,
                                                const lsim_gateway* gateway,
                                                const lsim_propagation* prop,
                                                const lsim_environment* env,
                                                lsim_device_stats* per_device,
                                                lsim_sim_stats* totals, lsim_tx_record* records,
                                                size_t record_capacity, size_t* record_count,
                                                const lsim_interval* gateway_busy,
                                                size_t gateway_busy_count,
                                                const lsim_mac_reservation* reservations,
                                                size_t reservation_count);

/* ------------------------------------------- Plusieurs passerelles (uplinks)
 * Chaque passerelle reçoit les mêmes émissions ; le serveur déduplique (une livraison par
 * trame). Voir lsim/engine.hpp. Pas de downlink ni de demi-duplex par passerelle ici.
 * gateways : gateway_count entrées, 1..64. env NULL = terrain plat. per_gateway : gateway_count
 * entrées. Statut 0, ou LSIM_STATUS_SIM_BASE + code du moteur (InvalidInput si gateway_count
 * est hors bornes). */
typedef struct lsim_network_stats {
    uint64_t sent;
    uint64_t received;          /* trames livrées au serveur, une fois par trame */
    uint64_t duplicates;        /* copies décodées en plus de la première */
    uint64_t lost_sensitivity;  /* aucune passerelle au-dessus de la sensibilité */
    uint64_t lost_collision;    /* collisionnée à toutes les passerelles qui l'entendent */
    uint64_t airtime_ns;
    uint64_t lost_gateway_busy; /* passerelle(s) audibles en émission (downlink) */
} lsim_network_stats;

typedef struct lsim_gateway_rx_stats {
    uint64_t received;          /* trames décodées par cette passerelle */
    uint64_t lost_sensitivity;
    uint64_t lost_collision;
    uint64_t lost_gateway_busy; /* passerelle en émission pendant la trame */
    uint64_t audible_frames;    /* trames au-dessus de la sensibilité à cette passerelle */
    uint64_t busy_ns;           /* union de leurs intervalles */
    uint64_t peak_concurrent;   /* simultanéité maximale */
    int64_t  observation_ns;    /* fin de la dernière émission - début de la première */
} lsim_gateway_rx_stats;

/* Trace par émission, multi-passerelles. outcome : 0 sous la sensibilité partout, 1 collision,
 * 2 reçue (receivers > 0 ; best_gateway = meilleure passerelle décodeuse), 3 passerelle(s)
 * occupée(s) par un downlink. Sans décodeur, best_gateway = -1 et best_rssi = RSSI maximal. */
typedef struct lsim_multi_tx_record {
    uint32_t device_index;
    int64_t  start_ns;
    int64_t  end_ns;
    uint8_t  spreading_factor;
    uint32_t receivers;
    int32_t  best_gateway;
    double   best_rssi_dbm;
    uint8_t  outcome;
    uint64_t decoded_mask;   /* bit g : passerelle g a décodé (g < 64) */
    uint8_t  join_request;   /* 1 : join-request (rule.join, dispositif non jointé) */
} lsim_multi_tx_record;

/* busy : NULL = aucune émission passerelle. Sinon, périodes [start, end) de toutes les passerelles
 * mises bout à bout ; busy_counts[g] = nombre de périodes de la passerelle g (gateway_count
 * entrées). records : NULL si record_count est NULL (pas de trace) ; sinon capacité
 * record_capacity, et record_count reçoit le nombre réel ; statut 308 si trop petit. */
LSIM_API int32_t lsim_simulate_uplinks_multi(const lsim_end_device* devices, size_t device_count,
                                             const lsim_gateway* gateways, size_t gateway_count,
                                             const lsim_propagation* prop,
                                             const lsim_environment* env,
                                             lsim_device_stats* per_device,
                                             lsim_network_stats* totals,
                                             lsim_gateway_rx_stats* per_gateway,
                                             const lsim_interval* busy,
                                             const size_t* busy_counts,
                                             lsim_multi_tx_record* records,
                                             size_t record_capacity, size_t* record_count);

/* Passerelles multiples avec downlinks (ordre de fin, calcul exact sans itération) : chaque uplink
 * décodé est acquitté (ack_uplinks) ou reçoit une charge (une par `every` uplinks décodés) par la
 * meilleure passerelle décodeuse, en RX1 (repli en RX2 si la passerelle est occupée en RX1,
 * voir rx2_sf). Chaque passerelle sérialise ses downlinks et ne décode
 * pas pendant les siens (demi-duplex par passerelle). Voir lsim/engine.hpp. */
typedef struct lsim_downlink_rule {
    uint8_t  ack_uplinks;             /* 0 ou 1 */
    uint32_t every;                   /* 0 : aucune charge en file */
    uint32_t payload_bytes;           /* 0..242 */
    double   gateway_tx_power_dbm;
    double   device_antenna_gain_dbi;
    double   device_rx_offset_db;
    uint8_t  join;                    /* 0 ou 1 : join-accept après une join-request décodée */
    uint8_t  rx2_sf;                  /* SF de RX2 de repli (7..12, BW 125 kHz) ; 0 : pas de repli */
} lsim_downlink_rule;

/* outcome : 0 reçu, 1 sous la sensibilité, 2 passerelle hors RX1 et RX2, 3 dispositif en émission.
 * start_ns/end_ns = -1 si non émis. rx_window : 1 RX1, 2 RX2 (repli après RX1 occupée). */
typedef struct lsim_downlink_record {
    uint32_t device_index;
    uint32_t gateway_index;
    uint8_t  data;
    int64_t  t_open_ns;
    int64_t  start_ns;
    int64_t  end_ns;
    uint8_t  outcome;
    uint8_t  join;                    /* 1 : join-accept (17 octets) */
    uint8_t  rx_window;               /* 1 : RX1 ; 2 : RX2 (repli) */
} lsim_downlink_record;

LSIM_API int32_t lsim_simulate_uplinks_multi_dl(const lsim_end_device* devices, size_t device_count,
                                                const lsim_gateway* gateways, size_t gateway_count,
                                                const lsim_propagation* prop,
                                                const lsim_downlink_rule* rule,
                                                const lsim_environment* env,
                                                lsim_device_stats* per_device,
                                                lsim_network_stats* totals,
                                                lsim_gateway_rx_stats* per_gateway,
                                                lsim_multi_tx_record* records,
                                                size_t record_capacity, size_t* record_count,
                                                lsim_downlink_record* downlinks,
                                                size_t downlink_capacity, size_t* downlink_count,
                                                const int64_t* dl_ready_ns, size_t ready_count);
/* dl_ready_ns (NULL : aucun) : départ au plus tôt de la descente de chaque émission (ordre :
   dispositifs puis k), -1 aucune contrainte, INT64_MAX jamais ; ready_count = somme des messages. */

/* ------------------------------------------- Downlinks par classe (A, B, C)
 * Requêtes de downlink par dispositif. plans : device_count entrées (NULL = aucune).
 * device_class : 0 A, 1 B, 2 C. Latence = début de la première fenêtre utilisable moins
 * la date de requête ; livrée si la fenêtre ouvre avant la fin de l'observation.
 * Classe B : balise supposée reçue à chaque période de 128 s depuis le temps 0. */
typedef struct lsim_downlink_plan {
    uint8_t  device_class;       /* 0 A, 1 B, 2 C */
    uint32_t count;              /* 0..100000 */
    int64_t  first_request_ns;   /* >= 0 */
    int64_t  request_period_ns;  /* > 0 si count > 1 */
    int64_t  rx_window_ns;       /* 0..10 s : durée RX1 (hypothèse) */
    uint32_t dev_addr;           /* classe B */
    uint8_t  periodicity;        /* classe B : 0..7 */
    uint32_t clock_drift_ppm;    /* classe B : 0..1000 */
} lsim_downlink_plan;

typedef struct lsim_downlink_stats {
    uint64_t requested;
    uint64_t delivered;
    uint64_t latency_sum_ns;     /* somme des latences livrées */
    uint64_t latency_max_ns;
} lsim_downlink_stats;

LSIM_API int32_t lsim_simulate_downlinks_env(const lsim_end_device* devices,
                                             const lsim_downlink_plan* plans, size_t device_count,
                                             const lsim_gateway* gateway,
                                             const lsim_propagation* prop,
                                             const lsim_environment* env,
                                             lsim_device_stats* per_device,
                                             lsim_sim_stats* totals,
                                             lsim_downlink_stats* per_device_dl,
                                             lsim_downlink_stats* dl_total);

/* Portée réelle par azimut (relief et obstacles inclus) : radii_out reçoit
 * `azimuths` distances (m), autour de la passerelle. step_m >= 1 ;
 * azimuths in 1..720. Borne de travail refusée au-delà (statut 506). */
LSIM_API int32_t lsim_coverage_radii(const lsim_gateway* gateway, const lsim_propagation* prop,
                                     double max_path_loss_db, const lsim_environment* env,
                                     double step_m, size_t azimuths, double* radii_out);

/* Perte de propagation totale (dB) entre toutes les paires de points (relief et obstacles
 * inclus). out_db[i*n+j] : émetteur i, récepteur j ; diagonale 0. 1 <= n <= 64 et
 * n*n*obstacles <= borne de travail (statut 506). Hauteurs : celles de `env` (émetteur =
 * device_height_m, récepteur = gateway_height_m). */
LSIM_API int32_t lsim_env_path_loss_matrix(const lsim_propagation* prop,
                                           const lsim_environment* env, size_t n,
                                           const double* x_m, const double* y_m,
                                           double* out_db);


/* ------------------------------------------------- Commandes MAC 1.1 */

/* Sens d'une commande : uplink (appareil -> serveur) ou downlink. */
#define LSIM_MAC_UPLINK   0
#define LSIM_MAC_DOWNLINK 1

/* Type de commande. Le sens est implicite dans le type (LinkCheckReq et
 * LinkCheckAns partagent le CID 0x02). */
#define LSIM_MAC_LINK_CHECK_REQ    1  /* up, sans charge */
#define LSIM_MAC_LINK_CHECK_ANS    2  /* down : margin, gw_cnt */
#define LSIM_MAC_LINK_ADR_REQ      3  /* down : data_rate, tx_power, ch_mask, ch_mask_cntl, nb_trans */
#define LSIM_MAC_LINK_ADR_ANS      4  /* up : ack_channel_mask, ack_data_rate, ack_power */
#define LSIM_MAC_DUTY_CYCLE_REQ    5  /* down : max_dcycle */
#define LSIM_MAC_DUTY_CYCLE_ANS    6  /* up, sans charge */
#define LSIM_MAC_DEV_STATUS_REQ    7  /* down, sans charge */
#define LSIM_MAC_DEV_STATUS_ANS    8  /* up : battery, dev_margin */
#define LSIM_MAC_REKEY_IND         9  /* up : lorawan_minor (1) */
#define LSIM_MAC_REKEY_CONF       10  /* down : lorawan_minor (1) */
#define LSIM_MAC_RX_PARAM_SETUP_REQ 11  /* down : rx2_data_rate, rx1_dr_offset, freq_100hz */
#define LSIM_MAC_RX_PARAM_SETUP_ANS 12  /* up : ack_rx_channel, ack_rx2_data_rate, ack_rx1_dr_offset */
#define LSIM_MAC_NEW_CHANNEL_REQ    13  /* down : ch_index, freq_100hz (0 = désactivé), min_dr, max_dr */
#define LSIM_MAC_NEW_CHANNEL_ANS    14  /* up : ack_dr_range, ack_channel_freq */
#define LSIM_MAC_RX_TIMING_SETUP_REQ    15  /* down : rx_delay (0..15, 0 -> 1 s) */
#define LSIM_MAC_RX_TIMING_SETUP_ANS    16  /* up, sans charge */
#define LSIM_MAC_DEVICE_TIME_REQ        17  /* up, sans charge */
#define LSIM_MAC_DEVICE_TIME_ANS        18  /* down : device_time_s, device_time_frac */
#define LSIM_MAC_FORCE_REJOIN_REQ       19  /* down : rejoin_period, rejoin_max_retries, rejoin_type, data_rate */
#define LSIM_MAC_REJOIN_PARAM_SETUP_REQ 20  /* down : max_time_n, max_count_n */
#define LSIM_MAC_REJOIN_PARAM_SETUP_ANS 21  /* up : ack_time_ok */
#define LSIM_MAC_DL_CHANNEL_REQ         22  /* down : ch_index, freq_100hz (>= 100 MHz) */
#define LSIM_MAC_DL_CHANNEL_ANS         23  /* up : ack_channel_freq, ack_uplink_freq_exists */
#define LSIM_MAC_ADR_PARAM_SETUP_REQ    24  /* down : adr_limit_exp, adr_delay_exp (0..15) */
#define LSIM_MAC_ADR_PARAM_SETUP_ANS    25  /* up, sans charge */
#define LSIM_MAC_PING_SLOT_INFO_REQ     26  /* up : ping_periodicity (0..7) */
#define LSIM_MAC_PING_SLOT_INFO_ANS     27  /* down, sans charge */
#define LSIM_MAC_PING_SLOT_CHANNEL_REQ  28  /* down : freq_100hz (0 = défaut), data_rate (0..15) */
#define LSIM_MAC_PING_SLOT_CHANNEL_ANS  29  /* up : ack_channel_freq, ack_data_rate */
#define LSIM_MAC_BEACON_FREQ_REQ        30  /* down : freq_100hz (0 = défaut) */
#define LSIM_MAC_BEACON_FREQ_ANS        31  /* up : ack_beacon_freq */

/* Commande à plat : seuls les champs du type indiqué par `kind` sont lus. */
typedef struct lsim_mac_command {
    uint8_t  kind;              /* LSIM_MAC_* */
    uint8_t  margin;            /* LinkCheckAns : 0..254 dB */
    uint8_t  gw_cnt;            /* LinkCheckAns */
    uint8_t  data_rate;         /* LinkADRReq : 0..15 */
    uint8_t  tx_power;          /* LinkADRReq : 0..15 (15 = ignorer) */
    uint16_t ch_mask;           /* LinkADRReq : bit 0 = canal 1 */
    uint8_t  ch_mask_cntl;      /* LinkADRReq : 0..7 */
    uint8_t  nb_trans;          /* LinkADRReq : 0..15 (0 = inchangé) */
    uint8_t  ack_channel_mask;  /* LinkADRAns : 0 ou 1 */
    uint8_t  ack_data_rate;     /* LinkADRAns : 0 ou 1 */
    uint8_t  ack_power;         /* LinkADRAns : 0 ou 1 */
    uint8_t  max_dcycle;        /* DutyCycleReq : 0..15 (duty = 1/2^n) */
    uint8_t  battery;           /* DevStatusAns : 0 externe, 255 non mesuré */
    int8_t   dev_margin;        /* DevStatusAns : -32..31 dB */
    uint8_t  lorawan_minor;     /* Rekey : 1 (LoRaWAN 1.1) */
    uint8_t  rx2_data_rate;     /* RXParamSetupReq : 0..15 */
    uint8_t  rx1_dr_offset;     /* RXParamSetupReq : 0..7 */
    uint32_t freq_100hz;        /* RXParamSetupReq, NewChannelReq : 24 bits, Hz = 100 x valeur */
    uint8_t  ch_index;          /* NewChannelReq : 0..15 */
    uint8_t  min_dr;            /* NewChannelReq : 0..15 */
    uint8_t  max_dr;            /* NewChannelReq : 0..15 */
    uint8_t  ack_rx_channel;    /* RXParamSetupAns : 0 ou 1 */
    uint8_t  ack_rx2_data_rate; /* RXParamSetupAns : 0 ou 1 */
    uint8_t  ack_rx1_dr_offset; /* RXParamSetupAns : 0 ou 1 */
    uint8_t  ack_dr_range;      /* NewChannelAns : 0 ou 1 */
    uint8_t  ack_channel_freq;  /* NewChannelAns, DlChannelAns : 0 ou 1 */
    uint8_t  rx_delay;          /* RXTimingSetupReq : 0..15 */
    uint32_t device_time_s;     /* DeviceTimeAns : secondes depuis l'époque GPS */
    uint8_t  device_time_frac;  /* DeviceTimeAns : 1/256 s */
    uint8_t  rejoin_period;     /* ForceRejoinReq : 0..7 */
    uint8_t  rejoin_max_retries;/* ForceRejoinReq : 0..7 */
    uint8_t  rejoin_type;       /* ForceRejoinReq : 0..2 */
    uint8_t  max_time_n;        /* RejoinParamSetupReq : 0..15 */
    uint8_t  max_count_n;       /* RejoinParamSetupReq : 0..15 */
    uint8_t  ack_time_ok;       /* RejoinParamSetupAns : 0 ou 1 */
    uint8_t  ack_uplink_freq_exists; /* DlChannelAns : 0 ou 1 */
    uint8_t  adr_limit_exp;     /* ADRParamSetupReq : 0..15 (ADR_ACK_LIMIT = 2^x) */
    uint8_t  adr_delay_exp;     /* ADRParamSetupReq : 0..15 (ADR_ACK_DELAY = 2^x) */
    uint8_t  ping_periodicity;  /* PingSlotInfoReq : 0..7 */
    uint8_t  ack_beacon_freq;   /* BeaconFreqAns : 0 ou 1 */
} lsim_mac_command;

/* Plus grande commande MAC (CID compris) : 6 octets. */
#define LSIM_MAC_MAX_COMMAND_BYTES 6

/* Encode une commande (CID compris) dans out ; *out_len reçoit 1..6. */
LSIM_API int32_t lsim_mac_encode(const lsim_mac_command* cmd,
                                 uint8_t out[LSIM_MAC_MAX_COMMAND_BYTES], size_t* out_len);

/* Décode la première commande de `in` selon le sens ; *consumed reçoit sa taille.
 * Un CID non implémenté renvoie LSIM_STATUS_MAC_BASE + UnknownCommand. */
LSIM_API int32_t lsim_mac_decode(const uint8_t* in, size_t len, uint8_t direction,
                                 lsim_mac_command* out, size_t* consumed);

/* Ajoute une commande encodée au champ FOpts (fopts : 15 octets, *fopts_len
 * en entrée et sortie). Refuse tout dépassement sans modifier fopts. */
LSIM_API int32_t lsim_mac_append_fopts(uint8_t fopts[15], uint8_t* fopts_len,
                                       const uint8_t* cmd, size_t cmd_len);

/* ------------------------------------------------- Rejoin-request 1.1 */

/* Type 0 ou 2 : NetID (3 octets, ordre de transmission) + DevEUI + RJcount0. */
typedef struct lsim_rejoin02 {
    uint8_t  rejoin_type;   /* 0 ou 2 */
    uint8_t  net_id[3];
    uint8_t  dev_eui[8];
    uint16_t rjcount0;
} lsim_rejoin02;

/* Type 1 : JoinEUI + DevEUI + RJcount1. */
typedef struct lsim_rejoin1 {
    uint8_t  join_eui[8];
    uint8_t  dev_eui[8];
    uint16_t rjcount1;
} lsim_rejoin1;

/* Encode un rejoin type 0/2 (19 octets) ; MIC par SNwkSIntKey (key). */
LSIM_API int32_t lsim_rejoin_encode_02(const lsim_rejoin02* f, const uint8_t key[16],
                                       uint8_t out[19]);
/* Décode et vérifie le MIC (SNwkSIntKey) avant exposition des champs. */
LSIM_API int32_t lsim_rejoin_decode_02(const uint8_t* in, size_t len, const uint8_t key[16],
                                       lsim_rejoin02* out);
/* Encode un rejoin type 1 (24 octets) ; MIC par JSIntKey (key). */
LSIM_API int32_t lsim_rejoin_encode_1(const lsim_rejoin1* f, const uint8_t key[16],
                                      uint8_t out[24]);
/* Décode et vérifie le MIC (JSIntKey) avant exposition des champs. */
LSIM_API int32_t lsim_rejoin_decode_1(const uint8_t* in, size_t len, const uint8_t key[16],
                                      lsim_rejoin1* out);

/* ------------------------------------------------- Registre serveur de jointure */

/* Registre des DevNonce et RJcount par dispositif. Le registre est désigné par un
 * identifiant entier (handle) : aucun pointeur interne n'est exposé. Un handle
 * inconnu renvoie LSIM_STATUS_REGISTRY_BASE + 6. Thread-safe. */
#define LSIM_REGISTRY_MAX_INSTANCES 64

LSIM_API int32_t lsim_registry_create(uint64_t max_devices, uint64_t* handle);
LSIM_API int32_t lsim_registry_destroy(uint64_t handle);

/* Join-request : MIC (NwkKey) puis DevNonce strictement croissant. Rien n'est
 * enregistré si le MIC est faux. */
LSIM_API int32_t lsim_registry_accept_join_request(uint64_t handle, const uint8_t* in, size_t len,
                                                   const uint8_t nwk_key[16], lsim_join_request* out);
/* Rejoin type 0/2 : MIC (SNwkSIntKey) puis RJcount0 croissant. */
LSIM_API int32_t lsim_registry_accept_rejoin_02(uint64_t handle, const uint8_t* in, size_t len,
                                                const uint8_t s_nwk_s_int_key[16], lsim_rejoin02* out);
/* Rejoin type 1 : MIC (JSIntKey) puis RJcount1 croissant. */
LSIM_API int32_t lsim_registry_accept_rejoin_1(uint64_t handle, const uint8_t* in, size_t len,
                                               const uint8_t js_int_key[16], lsim_rejoin1* out);
/* Join-accept traité : RJcount0 du dispositif repart de zéro. */
LSIM_API int32_t lsim_registry_on_join_accepted(uint64_t handle, const uint8_t dev_eui[8]);
LSIM_API int32_t lsim_registry_device_count(uint64_t handle, uint64_t* count);

/* Sauvegarde : écrit l'état dans out (cap octets) ; *out_len reçoit la taille.
 * Si cap est insuffisant : statut BufferTooSmall (706 - 700 = 6) et *out_len = taille
 * requise. integrity_key protège la sauvegarde par AES-CMAC (16 octets). */
LSIM_API int32_t lsim_registry_export(uint64_t handle, const uint8_t integrity_key[16],
                                      uint8_t* out, size_t cap, size_t* out_len);
/* Chargement : crée un nouveau registre à partir d'une sauvegarde. Le MIC est vérifié
 * avant tout parsing ; en cas d'échec, aucun registre n'est créé. */
LSIM_API int32_t lsim_registry_import(const uint8_t integrity_key[16], const uint8_t* in,
                                      size_t len, uint64_t* handle);

/* ADR serveur (fonction pure) : SNR en dixièmes de dB (-500..500) pour les n_samples
 * dernières trames (1..20). dr_sf[i] = SF du débit i (7..12), 0 si indisponible.
 * Statut : 0 ; 761 = paramètre invalide (LSIM_STATUS_ADR_BASE + 1). */
typedef struct {
    int32_t snr_tenth_db[20];
    uint8_t n_samples;
    uint8_t dr;
    uint8_t dr_sf[16];
    uint8_t min_dr;
    uint8_t max_dr;
    uint8_t tx_power_index;
    uint8_t max_tx_power_index;
    int32_t power_step_tenth_db;          /* 1..100 */
    int32_t installation_margin_tenth_db; /* -300..300 */
} lsim_adr_input;

typedef struct {
    uint8_t dr;
    uint8_t tx_power_index;
} lsim_adr_output;

LSIM_API int32_t lsim_adr_decide(const lsim_adr_input* in, lsim_adr_output* out);

/* ADR_ACK côté dispositif : état passé et mis à jour par l'appelant (aucun état caché).
 * ack_cnt : uplinks depuis la dernière réception descendante. Un état invalide laisse
 * *st intact et renvoie 761. limit_exp / delay_exp : 0..15 (ADRParamSetup). */
typedef struct {
    uint64_t ack_cnt;
    uint8_t  dr;
    uint8_t  min_dr;
    uint8_t  tx_power_index;
    uint8_t  default_tx_power_index;
    uint8_t  channels_subset;   /* 0 ou 1 */
} lsim_adr_device_state;

typedef struct {
    uint8_t ack_req;                    /* ADRACKReq à émettre : 0 ou 1 */
    uint8_t default_channels_reenabled; /* 0 ou 1 */
} lsim_adr_uplink_outcome;

LSIM_API int32_t lsim_adr_device_uplink(lsim_adr_device_state* st, uint8_t limit_exp, uint8_t delay_exp,
                                        lsim_adr_uplink_outcome* out);
LSIM_API int32_t lsim_adr_device_downlink(lsim_adr_device_state* st);

/* Rekey (LoRaWAN 1.1 §5.10). Dispositif : state 0 Idle, 1 Pending, 2 Confirmed, 3 NeedsJoin. */
typedef struct {
    uint8_t  state;
    uint64_t uplinks;   /* uplinks depuis le join-accept */
} lsim_rekey_device;

typedef struct {
    uint8_t awaiting;   /* 0 ou 1 */
} lsim_rekey_server;

/* action serveur : 0 Accept, 1 AcceptAndConfirm (RekeyConf à émettre), 2 Discard. */
LSIM_API int32_t lsim_rekey_device_join_accepted(lsim_rekey_device* d);
LSIM_API int32_t lsim_rekey_device_uplink_completed(lsim_rekey_device* d, uint64_t admin_limit,
                                                    uint8_t conf_received, uint8_t server_version);
LSIM_API int32_t lsim_rekey_device_must_send_rekey_ind(const lsim_rekey_device* d, uint8_t* out);
LSIM_API int32_t lsim_rekey_server_join_accepted(lsim_rekey_server* s);
LSIM_API int32_t lsim_rekey_server_on_uplink(lsim_rekey_server* s, uint8_t new_context,
                                             uint8_t has_rekey_ind, uint8_t* action);

/* ------------------------------------------- Moteur de session dispositif (OTAA 1.1)
 * Session désignée par un handle (table protégée par verrou, aucune clé exposée en
 * retour). Statut : 780 + SessionStatus (0 Ok, 1 NoSession, 2 CycleError, 3 Replay,
 * 4 InvalidParameter, 5 CounterExhausted) ; handle inconnu : 786.
 * state : 0 NoSession, 1 Active, 2 NeedsJoin. Cycle d'uplink :
 * begin_uplink -> [receive_downlink]* -> end_uplink. */
typedef struct {
    uint8_t f_nwk_s_int_key[16];
    uint8_t s_nwk_s_int_key[16];
    uint8_t nwk_s_enc_key[16];
    uint8_t app_s_key[16];
} lsim_session_keys;

typedef struct {
    uint32_t fcnt32;   /* FCntUp à utiliser */
    uint8_t rekey_ind; /* 1 : inclure RekeyInd */
    uint8_t ack_req;   /* 1 : inclure ADRACKReq */
    uint8_t default_channels_reenabled;
} lsim_session_uplink_plan;

typedef struct {
    uint8_t state;     /* 0 NoSession, 1 Active, 2 NeedsJoin */
} lsim_session_uplink_end;

typedef struct {
    uint8_t state;
    uint32_t dev_addr;
    uint64_t fcnt_up;
    uint64_t nf_cnt_dwn;
    uint64_t af_cnt_dwn;
    uint8_t dr;
    uint8_t tx_power_index;
    uint64_t ack_cnt;
    uint8_t cycle_open;
} lsim_session_info;

LSIM_API int32_t lsim_session_create(uint64_t* handle);
LSIM_API int32_t lsim_session_destroy(uint64_t handle);
LSIM_API int32_t lsim_session_join_accepted(uint64_t handle, const lsim_session_keys* keys,
                                            uint32_t dev_addr, uint8_t dr, uint8_t min_dr,
                                            uint8_t tx_power_index, uint8_t default_tx_power_index);
/* limit_exp / delay_exp : ADR_ACK_LIMIT / ADR_ACK_DELAY en exposants (0..15). */
LSIM_API int32_t lsim_session_begin_uplink(uint64_t handle, uint8_t limit_exp, uint8_t delay_exp,
                                           lsim_session_uplink_plan* plan);
/* uses_nf : 1 si FPort absent ou 0 (NFCntDown), 0 sinon (AFCntDown). */
LSIM_API int32_t lsim_session_receive_downlink(uint64_t handle, uint8_t uses_nf, uint32_t fcnt32,
                                               uint8_t conf_received, uint8_t server_version);
LSIM_API int32_t lsim_session_end_uplink(uint64_t handle, lsim_session_uplink_end* out);
LSIM_API int32_t lsim_session_snapshot(uint64_t handle, lsim_session_info* out);

/* ------------------------------------------- Moteur de classe B (beacon, ping slot)
 * Fonctions sans état : le dispositif est passé et renvoyé par l'appelant. Statut :
 * 800 + ClassBStatus (0 Ok, 1 paramètre invalide, 2 CRC faux, 3 non synchronisé,
 * 4 balise perdue depuis 2 h). Temps en nanosecondes entières (horloge locale). */
typedef struct {
    uint8_t  synchronized;
    uint64_t last_beacon_rx_ns;
    uint32_t last_beacon_time_s;
    uint32_t dev_addr;
    uint8_t  periodicity;      /* 0..7 */
    uint32_t clock_drift_ppm;  /* dérive d'horloge, 0..1000 ppm */
} lsim_classb_device;

typedef struct {
    uint64_t start_ns;
    uint32_t slot_index;       /* N, 0..4095 */
    uint32_t beacon_time_s;
    uint64_t beacon_period_start_ns;
    uint64_t window_half_ns;   /* élargissement de la fenêtre (dérive × temps depuis beacon) */
} lsim_classb_ping_slot;

/* GwSpecific décodé. has_coordinates = 1 seulement si info_desc est 0, 1 ou 2. */
typedef struct {
    uint32_t time_s;
    uint8_t  present;
    uint8_t  info_desc;
    uint8_t  has_coordinates;
    double   latitude_deg;
    double   longitude_deg;
} lsim_classb_gateway_info;

/* rfu_len : 2 (EU868) ou 3 (US915). CRC-16 vérifié avant d'écrire time_s. */
LSIM_API int32_t lsim_classb_decode_beacon(const uint8_t* in, size_t len, uint8_t rfu_len,
                                           uint32_t* time_s);
/* gw_rfu_len : 0 (EU868) ou 1 (US915). Accepte une trame sans GwSpecific. */
LSIM_API int32_t lsim_classb_decode_beacon_full(const uint8_t* in, size_t len, uint8_t rfu_len,
                                                uint8_t gw_rfu_len,
                                                lsim_classb_gateway_info* out);
/* US902-928 : index = floor(beacon_time / 128) mod 8 ; freq_hz = 923,3 MHz + 0,6 MHz × index. */
LSIM_API int32_t lsim_classb_us902_channel(uint32_t beacon_time_s, uint8_t* index,
                                           uint32_t* freq_hz);
LSIM_API int32_t lsim_classb_ping_offset(uint32_t beacon_time_s, uint32_t dev_addr,
                                         uint8_t periodicity, uint32_t* offset);
LSIM_API int32_t lsim_classb_on_beacon(lsim_classb_device* d, uint64_t rx_ns,
                                       uint32_t beacon_time_s);
/* state : 0 NotSynchronized, 1 Synchronized, 2 BeaconLess, 3 Lost. */
LSIM_API int32_t lsim_classb_beacon_state(const lsim_classb_device* d, uint64_t now_ns,
                                          uint8_t* state);
LSIM_API int32_t lsim_classb_next_ping_slot(const lsim_classb_device* d, uint64_t now_ns,
                                            lsim_classb_ping_slot* out);

/* Relais mesh 2,4 GHz (core/src/mesh.cpp). Disposition identique aux structures ctypes. */
typedef struct lsim_mesh_radio {
    uint8_t  spreading_factor;   /* 5..12 */
    uint8_t  coding_rate;        /* 1..4 : 4/5 à 4/8 */
    uint32_t bandwidth_hz;
    uint32_t payload_bytes;      /* 0..255 */
    uint32_t preamble_symbols;   /* 6..65535 */
    double   capture_db;         /* >= 0 */
} lsim_mesh_radio;

typedef struct lsim_mesh_frame {
    uint64_t frame_id;
    uint32_t rx_node;            /* indice de la passerelle qui a reçu la trame */
    int64_t  t_ns;               /* fin de réception sur l'accès */
    uint32_t payload_bytes;      /* taille relayée (trame LoRaWAN + enveloppe), 0..255 */
} lsim_mesh_frame;

typedef struct lsim_mesh_delivery {
    uint64_t frame_id;
    uint8_t  delivered;          /* 0 ou 1 */
    uint8_t  loss;               /* 0 livré, 1 no_route, 2 half_duplex, 3 collision, 4 suppressed */
    uint8_t  hops;               /* sauts de la copie livrée en premier, 0 si non livré */
    uint8_t  copy_state;         /* 0 relayée, 1 supprimée, 2 frontière, 3 sans route */
    int64_t  latency_ns;         /* -1 si non livré */
} lsim_mesh_delivery;

typedef struct lsim_mesh_summary {
    uint64_t transmissions;      /* émissions mesh effectives */
    uint64_t suppressed;         /* copies abandonnées (doublon entendu avant départ) */
    uint64_t lost_collision;     /* sauts perdus par collision */
    uint64_t lost_half_duplex;   /* sauts perdus : récepteur en émission */
} lsim_mesh_summary;

/* Journal d'un saut mesh (mesh::HopEvent). outcome : 0 reçu, 1 collision, 2 demi-duplex,
   3 copie supprimée (t_start = t_end = décision). */
typedef struct lsim_mesh_hop {
    uint64_t frame_id;
    uint32_t sender;
    uint32_t receiver;
    int64_t  t_start_ns;
    int64_t  t_end_ns;
    uint8_t  outcome;
    uint8_t  hop_index;
} lsim_mesh_hop;

LSIM_API int32_t lsim_mesh_airtime_ns(const lsim_mesh_radio* radio, int64_t* out);
LSIM_API int32_t lsim_mesh_sensitivity_dbm(const lsim_mesh_radio* radio, int32_t* out);
// Tirage de shadowing (dB) d'un indice donné : même fonction que le cœur de simulation
// (`shadowing_sample_db`), gaussienne d'écart-type sigma_db. Utilisé par le mesh pour
// tirer une valeur par paire de passerelles.
LSIM_API int32_t lsim_shadowing_sample_db(uint64_t seed, uint32_t device_index, double sigma_db,
                                          double* out);
LSIM_API int32_t lsim_mesh_routes(const lsim_mesh_radio* radio, size_t node_count,
                                  const uint8_t* capable, const double* rssi_dbm,
                                  uint32_t border, uint32_t max_hops, int32_t* next);
LSIM_API int32_t lsim_mesh_forward(const lsim_mesh_radio* radio, size_t node_count,
                                   const uint8_t* capable, const double* rssi_dbm,
                                   const int32_t* next, uint32_t border, int suppress,
                                   int64_t backoff_window_ns,
                                   const lsim_mesh_frame* frames, size_t frame_count,
                                   lsim_mesh_delivery* out, lsim_mesh_summary* summary);
/* Comme lsim_mesh_forward, avec le journal des sauts. Si le journal dépasse hop_capacity,
   rien n'est écrit, *hop_count reçoit la taille requise et le statut est BufferTooSmall (810). */
LSIM_API int32_t lsim_mesh_forward_log(const lsim_mesh_radio* radio, size_t node_count,
                                       const uint8_t* capable, const double* rssi_dbm,
                                       const int32_t* next, uint32_t border, int suppress,
                                       int64_t backoff_window_ns,
                                       const lsim_mesh_frame* frames, size_t frame_count,
                                       lsim_mesh_delivery* out, lsim_mesh_summary* summary,
                                       lsim_mesh_hop* hops, size_t hop_capacity,
                                       size_t* hop_count);

/* Comme lsim_mesh_forward_log, avec une destination par trame. `next_by_dest` : node_count x
   node_count (ligne d = routes vers la passerelle d, -1 si aucune route) ; `dests[k]` : passerelle
   de destination de la trame k (capable). Une même trame ne peut viser deux destinations. */
LSIM_API int32_t lsim_mesh_forward_routed_log(const lsim_mesh_radio* radio, size_t node_count,
                                              const uint8_t* capable, const double* rssi_dbm,
                                              const int32_t* next_by_dest, const uint32_t* dests,
                                              int suppress, int64_t backoff_window_ns,
                                              const lsim_mesh_frame* frames, size_t frame_count,
                                              lsim_mesh_delivery* out, lsim_mesh_summary* summary,
                                              lsim_mesh_hop* hops, size_t hop_capacity,
                                              size_t* hop_count);

/* ------------------------------------------- Planification des descentes (v1, S0)
 * Passerelle unique, sans jointure ni commande MAC. Même logique que la trace Python
 * (`lsim.trace_events`) pour ce cas. Entrées : émissions montantes (ordre de trace) et paramètres
 * radio par dispositif. Sorties : événements (ordre temporel stable) et occupation passerelle.
 * Codes d'issue : voir lsim/downlink_plan.hpp (Outcome, EventKind, HopDir). */
#define LSIM_STATUS_PLAN_BASE 950

typedef struct lsim_plan_uplink {
    uint32_t device_index;
    int64_t start_ns;
    int64_t end_ns;
    uint8_t spreading_factor;
    uint8_t outcome;             /* 0 sensibilité, 1 collision, 2 reçue, 3 passerelle occupée */
    double rssi_dbm;
} lsim_plan_uplink;

typedef struct lsim_plan_device {
    int64_t freq_hz;
    int32_t dr;                  /* -1 : aucun débit de plan */
    int64_t rx1_hz;
    double tx_power_dbm;
    uint8_t rx1_sf;
    uint32_t rx1_bw_hz;          /* 125000, 250000 ou 500000 */
} lsim_plan_device;

typedef struct lsim_plan_options {
    uint8_t confirmed_uplinks;
    uint32_t downlink_every;
    uint32_t downlink_payload_bytes;   /* 0..242 */
    double gateway_tx_power_dbm;
    double device_antenna_gain_dbi;
    double device_rx_offset_db;
} lsim_plan_options;

typedef struct lsim_plan_hop {
    uint8_t dir;                 /* 0 dispositif->passerelle, 1 passerelle->réseau, 2 passerelle->dispositif */
    uint8_t outcome;             /* code Outcome */
    uint8_t has_rssi;
    int64_t t_ns;
    int64_t freq_hz;
    int32_t dr;
    double rssi_dbm;
} lsim_plan_hop;

typedef struct lsim_plan_event {
    int64_t t_ns;
    uint32_t device_index;
    uint8_t kind;                /* 0 uplink, 1 ack, 2 downlink, 3 rx_window_missed */
    uint8_t outcome;
    uint8_t hop_count;           /* 0..2 */
    lsim_plan_hop hops[2];
} lsim_plan_event;

/* Planifie les descentes. Les tableaux de sortie ont une capacité ; si elle est insuffisante,
 * *event_count / *busy_count donnent la taille requise et le statut est
 * LSIM_STATUS_PLAN_BASE + 4 (TraceBufferTooSmall). */
LSIM_API int32_t lsim_plan_downlinks_v1(const lsim_plan_uplink* uplinks, size_t uplink_count,
                                        const lsim_plan_device* devices, size_t device_count,
                                        const lsim_plan_options* options,
                                        lsim_plan_event* events, size_t event_capacity,
                                        size_t* event_count,
                                        lsim_interval* busy, size_t busy_capacity,
                                        size_t* busy_count);

/* ------------------------------------------- Boucle fermée causale (v1, S1)
 * Passerelle unique, sans commande MAC ni jointure. Les descentes sont planifiées au fil de
 * l'eau (fin de chaque trame reçue) : une seule exécution, sans point fixe. radios : device_count
 * entrées (même ordre que devices). Sorties : trace (ordre temporel) et occupation passerelle
 * planifiée. Statut 0, ou code d'erreur du moteur / du planificateur. */
LSIM_API int32_t lsim_simulate_uplinks_causal_v1(const lsim_end_device* devices,
                                                 size_t device_count,
                                                 const lsim_gateway* gateway,
                                                 const lsim_propagation* prop,
                                                 const lsim_environment* env,
                                                 lsim_device_stats* per_device,
                                                 lsim_sim_stats* totals, lsim_tx_record* records,
                                                 size_t record_capacity, size_t* record_count,
                                                 const lsim_plan_device* radios,
                                                 const lsim_plan_options* options,
                                                 lsim_interval* busy_out, size_t busy_capacity,
                                                 size_t* busy_count);

#ifdef __cplusplus
}
#endif

#endif /* LSIM_C_API_H */
