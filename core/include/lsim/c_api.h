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
 *   900      erreur interne (exception interceptée à la frontière)
 */
#define LSIM_STATUS_CRYPTO_BASE 100
#define LSIM_STATUS_SECURE_BASE 200
#define LSIM_STATUS_FRAME_BASE  250
#define LSIM_STATUS_SIM_BASE    300
#define LSIM_STATUS_ENV_BASE    500
#define LSIM_STATUS_JOIN_BASE   400
#define LSIM_STATUS_MAC_BASE    600
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
} lsim_classb_device;

typedef struct {
    uint64_t start_ns;
    uint32_t slot_index;       /* N, 0..4095 */
    uint32_t beacon_time_s;
    uint64_t beacon_period_start_ns;
} lsim_classb_ping_slot;

/* rfu_len : 2 (EU868) ou 3 (US915). CRC-16 vérifié avant d'écrire time_s. */
LSIM_API int32_t lsim_classb_decode_beacon(const uint8_t* in, size_t len, uint8_t rfu_len,
                                           uint32_t* time_s);
LSIM_API int32_t lsim_classb_ping_offset(uint32_t beacon_time_s, uint32_t dev_addr,
                                         uint8_t periodicity, uint32_t* offset);
LSIM_API int32_t lsim_classb_on_beacon(lsim_classb_device* d, uint64_t rx_ns,
                                       uint32_t beacon_time_s);
/* state : 0 NotSynchronized, 1 Synchronized, 2 BeaconLess, 3 Lost. */
LSIM_API int32_t lsim_classb_beacon_state(const lsim_classb_device* d, uint64_t now_ns,
                                          uint8_t* state);
LSIM_API int32_t lsim_classb_next_ping_slot(const lsim_classb_device* d, uint64_t now_ns,
                                            lsim_classb_ping_slot* out);

#ifdef __cplusplus
}
#endif

#endif /* LSIM_C_API_H */
