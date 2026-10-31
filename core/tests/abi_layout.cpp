// SPDX-License-Identifier: Apache-2.0
// Disposition ABI des structures publiques, vérifiée pour x86-64 **et** i386.
//
// Rôle (phase F7) : figer les tailles et décalages de toutes les structures `lsim_*` de
// `lsim/c_api.h`, avec **deux tables de constantes explicites** — une par ABI — au lieu des
// littéraux LP64 d'origine, qui ne compilaient pas en 32 bits.
//
// Les valeurs ne sont pas devinées : elles ont été **mesurées par le compilateur** sur les deux
// cibles (`g++ -m64` et `g++ -m32 -ffreestanding`), grandeur par grandeur, par des `static_assert`
// volontairement faux dont le message réduit donne la valeur. Le mode opératoire figure dans le
// rapport de phase F7.
//
// Ce fichier est compilable **seul** (harnais ABI 32/64 bits) :
//     g++ -std=c++17 -I core/include -DABI_LAYOUT_STANDALONE core/tests/abi_layout.cpp -o abi_layout
//     g++ -m32 -ffreestanding -I core/include -c core/tests/abi_layout.cpp -o abi_layout32.o
// Il est aussi **inclus** par `core/tests/test_abi_v3_prep.cpp`, pour que les deux fichiers
// partagent une seule table de constantes : la phase F7 n'autorise que ces deux fichiers, donc
// pas d'en-tête séparé (choix explicite, pas un oubli).
//
// Les structures publiques et les signatures ABI ne sont pas modifiées : ce fichier n'observe.
#ifndef LSIM_ABI_LAYOUT_CPP
#define LSIM_ABI_LAYOUT_CPP

#include <stddef.h>
#include <stdint.h>

#include "lsim/c_api.h"

namespace abi_layout {

enum class Abi { X86_64, I386 };

#if defined(__i386__)
inline constexpr Abi kAbi = Abi::I386;
inline constexpr const char* kAbiName = "i386";
inline constexpr size_t kPointerSize = 4;
inline constexpr size_t kMaxAlign = 4;   // alignof(max_align_t) i386 System V
#elif defined(__x86_64__)
inline constexpr Abi kAbi = Abi::X86_64;
inline constexpr const char* kAbiName = "x86-64";
inline constexpr size_t kPointerSize = 8;
inline constexpr size_t kMaxAlign = 16;
#else
#error "F7 ne couvre que x86-64 et i386 : ajouter une table explicite pour toute autre ABI"
#endif

namespace expected {

#if defined(__i386__)
// ---------------------------------------------------------------- i386 (ILP32)
// pointeurs et size_t : 4 octets ; double et uint64_t alignés sur 4.
    // lsim_radio_config
    inline constexpr size_t size_lsim_radio_config = 16;
    inline constexpr size_t off_lsim_radio_config__spreading_factor = 0;
    inline constexpr size_t off_lsim_radio_config__bandwidth_hz = 4;
    inline constexpr size_t off_lsim_radio_config__coding_rate = 8;
    inline constexpr size_t off_lsim_radio_config__preamble_symbols = 10;
    inline constexpr size_t off_lsim_radio_config__crc_on = 12;
    inline constexpr size_t off_lsim_radio_config__explicit_header = 13;
    inline constexpr size_t off_lsim_radio_config__low_data_rate_optimize = 14;
    // lsim_join_keys
    inline constexpr size_t size_lsim_join_keys = 32;
    inline constexpr size_t off_lsim_join_keys__js_enc_key = 0;
    inline constexpr size_t off_lsim_join_keys__js_int_key = 16;
    // lsim_session_keys_11
    inline constexpr size_t size_lsim_session_keys_11 = 64;
    inline constexpr size_t off_lsim_session_keys_11__f_nwk_s_int_key = 0;
    inline constexpr size_t off_lsim_session_keys_11__s_nwk_s_int_key = 16;
    inline constexpr size_t off_lsim_session_keys_11__nwk_s_enc_key = 32;
    inline constexpr size_t off_lsim_session_keys_11__app_s_key = 48;
    // lsim_session_keys_10
    inline constexpr size_t size_lsim_session_keys_10 = 32;
    inline constexpr size_t off_lsim_session_keys_10__nwk_s_key = 0;
    inline constexpr size_t off_lsim_session_keys_10__app_s_key = 16;
    // lsim_uplink_frame
    inline constexpr size_t size_lsim_uplink_frame = 280;
    inline constexpr size_t off_lsim_uplink_frame__dev_addr = 0;
    inline constexpr size_t off_lsim_uplink_frame__mtype = 4;
    inline constexpr size_t off_lsim_uplink_frame__adr = 5;
    inline constexpr size_t off_lsim_uplink_frame__adr_ack_req = 6;
    inline constexpr size_t off_lsim_uplink_frame__ack = 7;
    inline constexpr size_t off_lsim_uplink_frame__class_b = 8;
    inline constexpr size_t off_lsim_uplink_frame__fcnt = 10;
    inline constexpr size_t off_lsim_uplink_frame__has_fport = 12;
    inline constexpr size_t off_lsim_uplink_frame__fport = 13;
    inline constexpr size_t off_lsim_uplink_frame__payload_len = 14;
    inline constexpr size_t off_lsim_uplink_frame__payload = 15;
    inline constexpr size_t off_lsim_uplink_frame__mic = 257;
    inline constexpr size_t off_lsim_uplink_frame__fopts_len = 261;
    inline constexpr size_t off_lsim_uplink_frame__fopts = 262;
    // lsim_uplink_context
    inline constexpr size_t size_lsim_uplink_context = 8;
    inline constexpr size_t off_lsim_uplink_context__conf_fcnt = 0;
    inline constexpr size_t off_lsim_uplink_context__tx_dr = 2;
    inline constexpr size_t off_lsim_uplink_context__tx_ch = 3;
    inline constexpr size_t off_lsim_uplink_context__fcnt32 = 4;
    // lsim_downlink_context
    inline constexpr size_t size_lsim_downlink_context = 12;
    inline constexpr size_t off_lsim_downlink_context__conf_fcnt = 0;
    inline constexpr size_t off_lsim_downlink_context__nfcnt32 = 4;
    inline constexpr size_t off_lsim_downlink_context__afcnt32 = 8;
    // lsim_join_request
    inline constexpr size_t size_lsim_join_request = 18;
    inline constexpr size_t off_lsim_join_request__join_eui = 0;
    inline constexpr size_t off_lsim_join_request__dev_eui = 8;
    inline constexpr size_t off_lsim_join_request__dev_nonce = 16;
    // lsim_join_accept
    inline constexpr size_t size_lsim_join_accept = 32;
    inline constexpr size_t off_lsim_join_accept__join_nonce = 0;
    inline constexpr size_t off_lsim_join_accept__net_id = 3;
    inline constexpr size_t off_lsim_join_accept__dev_addr = 8;
    inline constexpr size_t off_lsim_join_accept__dl_settings = 12;
    inline constexpr size_t off_lsim_join_accept__rx_delay = 13;
    inline constexpr size_t off_lsim_join_accept__has_cflist = 14;
    inline constexpr size_t off_lsim_join_accept__cflist = 15;
    // lsim_end_device
    inline constexpr size_t size_lsim_end_device = 60;
    inline constexpr size_t off_lsim_end_device__x_m = 0;
    inline constexpr size_t off_lsim_end_device__y_m = 8;
    inline constexpr size_t off_lsim_end_device__spreading_factor = 16;
    inline constexpr size_t off_lsim_end_device__payload_bytes = 20;
    inline constexpr size_t off_lsim_end_device__tx_power_dbm = 24;
    inline constexpr size_t off_lsim_end_device__start_offset_ns = 32;
    inline constexpr size_t off_lsim_end_device__period_ns = 40;
    inline constexpr size_t off_lsim_end_device__messages = 48;
    inline constexpr size_t off_lsim_end_device__duty_cycle = 52;
    // lsim_gateway
    inline constexpr size_t size_lsim_gateway = 32;
    inline constexpr size_t off_lsim_gateway__x_m = 0;
    inline constexpr size_t off_lsim_gateway__y_m = 8;
    inline constexpr size_t off_lsim_gateway__antenna_gain_dbi = 16;
    inline constexpr size_t off_lsim_gateway__rx_sensitivity_offset_db = 24;
    // lsim_gateway_v2
    inline constexpr size_t size_lsim_gateway_v2 = 232;
    inline constexpr size_t off_lsim_gateway_v2__base = 0;
    inline constexpr size_t off_lsim_gateway_v2__sensitivity_model = 32;
    inline constexpr size_t off_lsim_gateway_v2__present = 36;
    inline constexpr size_t off_lsim_gateway_v2__sensitivity_dbm = 40;
    // lsim_propagation
    inline constexpr size_t size_lsim_propagation = 48;
    inline constexpr size_t off_lsim_propagation__frequency_hz = 0;
    inline constexpr size_t off_lsim_propagation__reference_distance_m = 8;
    inline constexpr size_t off_lsim_propagation__exponent = 16;
    inline constexpr size_t off_lsim_propagation__capture_threshold_db = 24;
    inline constexpr size_t off_lsim_propagation__shadowing_sigma_db = 32;
    inline constexpr size_t off_lsim_propagation__shadowing_seed = 40;
    // lsim_device_stats
    inline constexpr size_t size_lsim_device_stats = 48;
    inline constexpr size_t off_lsim_device_stats__sent = 0;
    inline constexpr size_t off_lsim_device_stats__received = 8;
    inline constexpr size_t off_lsim_device_stats__lost_sensitivity = 16;
    inline constexpr size_t off_lsim_device_stats__lost_collision = 24;
    inline constexpr size_t off_lsim_device_stats__airtime_ns = 32;
    inline constexpr size_t off_lsim_device_stats__lost_gateway_busy = 40;
    // lsim_sim_stats
    inline constexpr size_t size_lsim_sim_stats = 80;
    inline constexpr size_t off_lsim_sim_stats__sent = 0;
    inline constexpr size_t off_lsim_sim_stats__received = 8;
    inline constexpr size_t off_lsim_sim_stats__lost_sensitivity = 16;
    inline constexpr size_t off_lsim_sim_stats__lost_collision = 24;
    inline constexpr size_t off_lsim_sim_stats__airtime_ns = 32;
    inline constexpr size_t off_lsim_sim_stats__gateway_busy_ns = 40;
    inline constexpr size_t off_lsim_sim_stats__gateway_peak_concurrent = 48;
    inline constexpr size_t off_lsim_sim_stats__observation_ns = 56;
    inline constexpr size_t off_lsim_sim_stats__gateway_utilization = 64;
    inline constexpr size_t off_lsim_sim_stats__lost_gateway_busy = 72;
    // lsim_interval
    inline constexpr size_t size_lsim_interval = 16;
    inline constexpr size_t off_lsim_interval__start_ns = 0;
    inline constexpr size_t off_lsim_interval__end_ns = 8;
    // lsim_obstacle
    inline constexpr size_t size_lsim_obstacle = 48;
    inline constexpr size_t off_lsim_obstacle__x_min_m = 0;
    inline constexpr size_t off_lsim_obstacle__y_min_m = 8;
    inline constexpr size_t off_lsim_obstacle__x_max_m = 16;
    inline constexpr size_t off_lsim_obstacle__y_max_m = 24;
    inline constexpr size_t off_lsim_obstacle__height_m = 32;
    inline constexpr size_t off_lsim_obstacle__attenuation_db = 40;
    // lsim_environment
    inline constexpr size_t size_lsim_environment = 60;
    inline constexpr size_t off_lsim_environment__grid_z = 0;
    inline constexpr size_t off_lsim_environment__grid_nx = 4;
    inline constexpr size_t off_lsim_environment__grid_ny = 8;
    inline constexpr size_t off_lsim_environment__grid_origin_x_m = 12;
    inline constexpr size_t off_lsim_environment__grid_origin_y_m = 20;
    inline constexpr size_t off_lsim_environment__grid_cell_m = 28;
    inline constexpr size_t off_lsim_environment__obstacles = 36;
    inline constexpr size_t off_lsim_environment__obstacle_count = 40;
    inline constexpr size_t off_lsim_environment__gateway_height_m = 44;
    inline constexpr size_t off_lsim_environment__device_height_m = 52;
    // lsim_tx_record
    inline constexpr size_t size_lsim_tx_record = 36;
    inline constexpr size_t off_lsim_tx_record__device_index = 0;
    inline constexpr size_t off_lsim_tx_record__start_ns = 4;
    inline constexpr size_t off_lsim_tx_record__end_ns = 12;
    inline constexpr size_t off_lsim_tx_record__spreading_factor = 20;
    inline constexpr size_t off_lsim_tx_record__rssi_dbm = 24;
    inline constexpr size_t off_lsim_tx_record__outcome = 32;
    // lsim_mac_reservation
    inline constexpr size_t size_lsim_mac_reservation = 12;
    inline constexpr size_t off_lsim_mac_reservation__device_index = 0;
    inline constexpr size_t off_lsim_mac_reservation__rank = 4;
    inline constexpr size_t off_lsim_mac_reservation__extra_bytes = 8;
    // lsim_network_stats
    inline constexpr size_t size_lsim_network_stats = 56;
    inline constexpr size_t off_lsim_network_stats__sent = 0;
    inline constexpr size_t off_lsim_network_stats__received = 8;
    inline constexpr size_t off_lsim_network_stats__duplicates = 16;
    inline constexpr size_t off_lsim_network_stats__lost_sensitivity = 24;
    inline constexpr size_t off_lsim_network_stats__lost_collision = 32;
    inline constexpr size_t off_lsim_network_stats__airtime_ns = 40;
    inline constexpr size_t off_lsim_network_stats__lost_gateway_busy = 48;
    // lsim_gateway_rx_stats
    inline constexpr size_t size_lsim_gateway_rx_stats = 64;
    inline constexpr size_t off_lsim_gateway_rx_stats__received = 0;
    inline constexpr size_t off_lsim_gateway_rx_stats__lost_sensitivity = 8;
    inline constexpr size_t off_lsim_gateway_rx_stats__lost_collision = 16;
    inline constexpr size_t off_lsim_gateway_rx_stats__lost_gateway_busy = 24;
    inline constexpr size_t off_lsim_gateway_rx_stats__audible_frames = 32;
    inline constexpr size_t off_lsim_gateway_rx_stats__busy_ns = 40;
    inline constexpr size_t off_lsim_gateway_rx_stats__peak_concurrent = 48;
    inline constexpr size_t off_lsim_gateway_rx_stats__observation_ns = 56;
    // lsim_multi_tx_record
    inline constexpr size_t size_lsim_multi_tx_record = 56;
    inline constexpr size_t off_lsim_multi_tx_record__device_index = 0;
    inline constexpr size_t off_lsim_multi_tx_record__start_ns = 4;
    inline constexpr size_t off_lsim_multi_tx_record__end_ns = 12;
    inline constexpr size_t off_lsim_multi_tx_record__spreading_factor = 20;
    inline constexpr size_t off_lsim_multi_tx_record__receivers = 24;
    inline constexpr size_t off_lsim_multi_tx_record__best_gateway = 28;
    inline constexpr size_t off_lsim_multi_tx_record__best_rssi_dbm = 32;
    inline constexpr size_t off_lsim_multi_tx_record__outcome = 40;
    inline constexpr size_t off_lsim_multi_tx_record__decoded_mask = 44;
    inline constexpr size_t off_lsim_multi_tx_record__join_request = 52;
    // lsim_downlink_rule
    inline constexpr size_t size_lsim_downlink_rule = 40;
    inline constexpr size_t off_lsim_downlink_rule__ack_uplinks = 0;
    inline constexpr size_t off_lsim_downlink_rule__every = 4;
    inline constexpr size_t off_lsim_downlink_rule__payload_bytes = 8;
    inline constexpr size_t off_lsim_downlink_rule__gateway_tx_power_dbm = 12;
    inline constexpr size_t off_lsim_downlink_rule__device_antenna_gain_dbi = 20;
    inline constexpr size_t off_lsim_downlink_rule__device_rx_offset_db = 28;
    inline constexpr size_t off_lsim_downlink_rule__join = 36;
    inline constexpr size_t off_lsim_downlink_rule__rx2_sf = 37;
    // lsim_downlink_record
    inline constexpr size_t size_lsim_downlink_record = 40;
    inline constexpr size_t off_lsim_downlink_record__device_index = 0;
    inline constexpr size_t off_lsim_downlink_record__gateway_index = 4;
    inline constexpr size_t off_lsim_downlink_record__data = 8;
    inline constexpr size_t off_lsim_downlink_record__t_open_ns = 12;
    inline constexpr size_t off_lsim_downlink_record__start_ns = 20;
    inline constexpr size_t off_lsim_downlink_record__end_ns = 28;
    inline constexpr size_t off_lsim_downlink_record__outcome = 36;
    inline constexpr size_t off_lsim_downlink_record__join = 37;
    inline constexpr size_t off_lsim_downlink_record__rx_window = 38;
    // lsim_downlink_plan
    inline constexpr size_t size_lsim_downlink_plan = 44;
    inline constexpr size_t off_lsim_downlink_plan__device_class = 0;
    inline constexpr size_t off_lsim_downlink_plan__count = 4;
    inline constexpr size_t off_lsim_downlink_plan__first_request_ns = 8;
    inline constexpr size_t off_lsim_downlink_plan__request_period_ns = 16;
    inline constexpr size_t off_lsim_downlink_plan__rx_window_ns = 24;
    inline constexpr size_t off_lsim_downlink_plan__dev_addr = 32;
    inline constexpr size_t off_lsim_downlink_plan__periodicity = 36;
    inline constexpr size_t off_lsim_downlink_plan__clock_drift_ppm = 40;
    // lsim_downlink_stats
    inline constexpr size_t size_lsim_downlink_stats = 32;
    inline constexpr size_t off_lsim_downlink_stats__requested = 0;
    inline constexpr size_t off_lsim_downlink_stats__delivered = 8;
    inline constexpr size_t off_lsim_downlink_stats__latency_sum_ns = 16;
    inline constexpr size_t off_lsim_downlink_stats__latency_max_ns = 24;
    // lsim_mac_command
    inline constexpr size_t size_lsim_mac_command = 52;
    inline constexpr size_t off_lsim_mac_command__kind = 0;
    inline constexpr size_t off_lsim_mac_command__margin = 1;
    inline constexpr size_t off_lsim_mac_command__gw_cnt = 2;
    inline constexpr size_t off_lsim_mac_command__data_rate = 3;
    inline constexpr size_t off_lsim_mac_command__tx_power = 4;
    inline constexpr size_t off_lsim_mac_command__ch_mask = 6;
    inline constexpr size_t off_lsim_mac_command__ch_mask_cntl = 8;
    inline constexpr size_t off_lsim_mac_command__nb_trans = 9;
    inline constexpr size_t off_lsim_mac_command__ack_channel_mask = 10;
    inline constexpr size_t off_lsim_mac_command__ack_data_rate = 11;
    inline constexpr size_t off_lsim_mac_command__ack_power = 12;
    inline constexpr size_t off_lsim_mac_command__max_dcycle = 13;
    inline constexpr size_t off_lsim_mac_command__battery = 14;
    inline constexpr size_t off_lsim_mac_command__dev_margin = 15;
    inline constexpr size_t off_lsim_mac_command__lorawan_minor = 16;
    inline constexpr size_t off_lsim_mac_command__rx2_data_rate = 17;
    inline constexpr size_t off_lsim_mac_command__rx1_dr_offset = 18;
    inline constexpr size_t off_lsim_mac_command__freq_100hz = 20;
    inline constexpr size_t off_lsim_mac_command__ch_index = 24;
    inline constexpr size_t off_lsim_mac_command__min_dr = 25;
    inline constexpr size_t off_lsim_mac_command__max_dr = 26;
    inline constexpr size_t off_lsim_mac_command__ack_rx_channel = 27;
    inline constexpr size_t off_lsim_mac_command__ack_rx2_data_rate = 28;
    inline constexpr size_t off_lsim_mac_command__ack_rx1_dr_offset = 29;
    inline constexpr size_t off_lsim_mac_command__ack_dr_range = 30;
    inline constexpr size_t off_lsim_mac_command__ack_channel_freq = 31;
    inline constexpr size_t off_lsim_mac_command__rx_delay = 32;
    inline constexpr size_t off_lsim_mac_command__device_time_s = 36;
    inline constexpr size_t off_lsim_mac_command__device_time_frac = 40;
    inline constexpr size_t off_lsim_mac_command__rejoin_period = 41;
    inline constexpr size_t off_lsim_mac_command__rejoin_max_retries = 42;
    inline constexpr size_t off_lsim_mac_command__rejoin_type = 43;
    inline constexpr size_t off_lsim_mac_command__max_time_n = 44;
    inline constexpr size_t off_lsim_mac_command__max_count_n = 45;
    inline constexpr size_t off_lsim_mac_command__ack_time_ok = 46;
    inline constexpr size_t off_lsim_mac_command__ack_uplink_freq_exists = 47;
    inline constexpr size_t off_lsim_mac_command__adr_limit_exp = 48;
    inline constexpr size_t off_lsim_mac_command__adr_delay_exp = 49;
    inline constexpr size_t off_lsim_mac_command__ping_periodicity = 50;
    inline constexpr size_t off_lsim_mac_command__ack_beacon_freq = 51;
    // lsim_rejoin02
    inline constexpr size_t size_lsim_rejoin02 = 14;
    inline constexpr size_t off_lsim_rejoin02__rejoin_type = 0;
    inline constexpr size_t off_lsim_rejoin02__net_id = 1;
    inline constexpr size_t off_lsim_rejoin02__dev_eui = 4;
    inline constexpr size_t off_lsim_rejoin02__rjcount0 = 12;
    // lsim_rejoin1
    inline constexpr size_t size_lsim_rejoin1 = 18;
    inline constexpr size_t off_lsim_rejoin1__join_eui = 0;
    inline constexpr size_t off_lsim_rejoin1__dev_eui = 8;
    inline constexpr size_t off_lsim_rejoin1__rjcount1 = 16;
    // lsim_mesh_radio
    inline constexpr size_t size_lsim_mesh_radio = 24;
    inline constexpr size_t off_lsim_mesh_radio__spreading_factor = 0;
    inline constexpr size_t off_lsim_mesh_radio__coding_rate = 1;
    inline constexpr size_t off_lsim_mesh_radio__bandwidth_hz = 4;
    inline constexpr size_t off_lsim_mesh_radio__payload_bytes = 8;
    inline constexpr size_t off_lsim_mesh_radio__preamble_symbols = 12;
    inline constexpr size_t off_lsim_mesh_radio__capture_db = 16;
    // lsim_mesh_frame
    inline constexpr size_t size_lsim_mesh_frame = 24;
    inline constexpr size_t off_lsim_mesh_frame__frame_id = 0;
    inline constexpr size_t off_lsim_mesh_frame__rx_node = 8;
    inline constexpr size_t off_lsim_mesh_frame__t_ns = 12;
    inline constexpr size_t off_lsim_mesh_frame__payload_bytes = 20;
    // lsim_mesh_delivery
    inline constexpr size_t size_lsim_mesh_delivery = 20;
    inline constexpr size_t off_lsim_mesh_delivery__frame_id = 0;
    inline constexpr size_t off_lsim_mesh_delivery__delivered = 8;
    inline constexpr size_t off_lsim_mesh_delivery__loss = 9;
    inline constexpr size_t off_lsim_mesh_delivery__hops = 10;
    inline constexpr size_t off_lsim_mesh_delivery__copy_state = 11;
    inline constexpr size_t off_lsim_mesh_delivery__latency_ns = 12;
    // lsim_mesh_summary
    inline constexpr size_t size_lsim_mesh_summary = 32;
    inline constexpr size_t off_lsim_mesh_summary__transmissions = 0;
    inline constexpr size_t off_lsim_mesh_summary__suppressed = 8;
    inline constexpr size_t off_lsim_mesh_summary__lost_collision = 16;
    inline constexpr size_t off_lsim_mesh_summary__lost_half_duplex = 24;
    // lsim_mesh_hop
    inline constexpr size_t size_lsim_mesh_hop = 36;
    inline constexpr size_t off_lsim_mesh_hop__frame_id = 0;
    inline constexpr size_t off_lsim_mesh_hop__sender = 8;
    inline constexpr size_t off_lsim_mesh_hop__receiver = 12;
    inline constexpr size_t off_lsim_mesh_hop__t_start_ns = 16;
    inline constexpr size_t off_lsim_mesh_hop__t_end_ns = 24;
    inline constexpr size_t off_lsim_mesh_hop__outcome = 32;
    inline constexpr size_t off_lsim_mesh_hop__hop_index = 33;
    // lsim_plan_uplink
    inline constexpr size_t size_lsim_plan_uplink = 32;
    inline constexpr size_t off_lsim_plan_uplink__device_index = 0;
    inline constexpr size_t off_lsim_plan_uplink__start_ns = 4;
    inline constexpr size_t off_lsim_plan_uplink__end_ns = 12;
    inline constexpr size_t off_lsim_plan_uplink__spreading_factor = 20;
    inline constexpr size_t off_lsim_plan_uplink__outcome = 21;
    inline constexpr size_t off_lsim_plan_uplink__rssi_dbm = 24;
    // lsim_plan_device
    inline constexpr size_t size_lsim_plan_device = 36;
    inline constexpr size_t off_lsim_plan_device__freq_hz = 0;
    inline constexpr size_t off_lsim_plan_device__dr = 8;
    inline constexpr size_t off_lsim_plan_device__rx1_hz = 12;
    inline constexpr size_t off_lsim_plan_device__tx_power_dbm = 20;
    inline constexpr size_t off_lsim_plan_device__rx1_sf = 28;
    inline constexpr size_t off_lsim_plan_device__rx1_bw_hz = 32;
    // lsim_plan_options
    inline constexpr size_t size_lsim_plan_options = 36;
    inline constexpr size_t off_lsim_plan_options__confirmed_uplinks = 0;
    inline constexpr size_t off_lsim_plan_options__downlink_every = 4;
    inline constexpr size_t off_lsim_plan_options__downlink_payload_bytes = 8;
    inline constexpr size_t off_lsim_plan_options__gateway_tx_power_dbm = 12;
    inline constexpr size_t off_lsim_plan_options__device_antenna_gain_dbi = 20;
    inline constexpr size_t off_lsim_plan_options__device_rx_offset_db = 28;
    // lsim_plan_hop
    inline constexpr size_t size_lsim_plan_hop = 32;
    inline constexpr size_t off_lsim_plan_hop__dir = 0;
    inline constexpr size_t off_lsim_plan_hop__outcome = 1;
    inline constexpr size_t off_lsim_plan_hop__has_rssi = 2;
    inline constexpr size_t off_lsim_plan_hop__t_ns = 4;
    inline constexpr size_t off_lsim_plan_hop__freq_hz = 12;
    inline constexpr size_t off_lsim_plan_hop__dr = 20;
    inline constexpr size_t off_lsim_plan_hop__rssi_dbm = 24;
    // lsim_plan_event
    inline constexpr size_t size_lsim_plan_event = 80;
    inline constexpr size_t off_lsim_plan_event__t_ns = 0;
    inline constexpr size_t off_lsim_plan_event__device_index = 8;
    inline constexpr size_t off_lsim_plan_event__kind = 12;
    inline constexpr size_t off_lsim_plan_event__outcome = 13;
    inline constexpr size_t off_lsim_plan_event__hop_count = 14;
    inline constexpr size_t off_lsim_plan_event__hops = 16;
    // lsim_loop_region
    inline constexpr size_t size_lsim_loop_region = 160;
    inline constexpr size_t off_lsim_loop_region__dr_sf = 0;
    inline constexpr size_t off_lsim_loop_region__max_dr = 16;
    inline constexpr size_t off_lsim_loop_region__max_tx_power_index = 17;
    inline constexpr size_t off_lsim_loop_region__power_step_tenth_db = 20;
    inline constexpr size_t off_lsim_loop_region__max_eirp_dbm = 24;
    inline constexpr size_t off_lsim_loop_region__duty_limit = 32;
    // lsim_loop_options
    inline constexpr size_t size_lsim_loop_options = 48;
    inline constexpr size_t off_lsim_loop_options__protocol = 0;
    inline constexpr size_t off_lsim_loop_options__adr = 36;
    inline constexpr size_t off_lsim_loop_options__installation_margin_tenth_db = 40;
    inline constexpr size_t off_lsim_loop_options__duty_cycle = 44;
    inline constexpr size_t off_lsim_loop_options__duty_cycle_exponent = 45;
    // lsim_loop_mac
    inline constexpr size_t size_lsim_loop_mac = 12;
    inline constexpr size_t off_lsim_loop_mac__device_index = 0;
    inline constexpr size_t off_lsim_loop_mac__rank = 4;
    inline constexpr size_t off_lsim_loop_mac__extra_bytes = 8;
    inline constexpr size_t off_lsim_loop_mac__flags = 9;
    // lsim_loop_mac_counters
    inline constexpr size_t size_lsim_loop_mac_counters = 56;
    inline constexpr size_t off_lsim_loop_mac_counters__enqueued = 0;
    inline constexpr size_t off_lsim_loop_mac_counters__dispatched = 8;
    inline constexpr size_t off_lsim_loop_mac_counters__delivered = 16;
    inline constexpr size_t off_lsim_loop_mac_counters__dispatch_lost = 24;
    inline constexpr size_t off_lsim_loop_mac_counters__deferred = 32;
    inline constexpr size_t off_lsim_loop_mac_counters__expired = 40;
    inline constexpr size_t off_lsim_loop_mac_counters__pending_at_end = 48;
    // lsim_loop_uplink
    inline constexpr size_t size_lsim_loop_uplink = 36;
    inline constexpr size_t off_lsim_loop_uplink__device_index = 0;
    inline constexpr size_t off_lsim_loop_uplink__start_ns = 4;
    inline constexpr size_t off_lsim_loop_uplink__end_ns = 12;
    inline constexpr size_t off_lsim_loop_uplink__spreading_factor = 20;
    inline constexpr size_t off_lsim_loop_uplink__dr = 21;
    inline constexpr size_t off_lsim_loop_uplink__power_index = 22;
    inline constexpr size_t off_lsim_loop_uplink__rssi_dbm = 24;
    inline constexpr size_t off_lsim_loop_uplink__outcome = 32;
    inline constexpr size_t off_lsim_loop_uplink__answer_mask = 33;
    inline constexpr size_t off_lsim_loop_uplink__answer_ok = 34;
    // lsim_loop_downlink
    inline constexpr size_t size_lsim_loop_downlink = 40;
    inline constexpr size_t off_lsim_loop_downlink__uplink_index = 0;
    inline constexpr size_t off_lsim_loop_downlink__device_index = 4;
    inline constexpr size_t off_lsim_loop_downlink__kind = 8;
    inline constexpr size_t off_lsim_loop_downlink__commands = 9;
    inline constexpr size_t off_lsim_loop_downlink__t_open_ns = 12;
    inline constexpr size_t off_lsim_loop_downlink__start_ns = 20;
    inline constexpr size_t off_lsim_loop_downlink__air_ns = 28;
    inline constexpr size_t off_lsim_loop_downlink__device_missed = 36;
    inline constexpr size_t off_lsim_loop_downlink__delivered = 37;
    inline constexpr size_t off_lsim_loop_downlink__req_dr = 38;
    inline constexpr size_t off_lsim_loop_downlink__req_power_index = 39;
    // lsim_channel_device_v3
    inline constexpr size_t size_lsim_channel_device_v3 = 128;
    inline constexpr size_t off_lsim_channel_device_v3__struct_size = 0;
    inline constexpr size_t off_lsim_channel_device_v3__abi_version = 4;
    inline constexpr size_t off_lsim_channel_device_v3__device_index = 8;
    inline constexpr size_t off_lsim_channel_device_v3__present = 12;
    inline constexpr size_t off_lsim_channel_device_v3__dr_mask = 16;
    inline constexpr size_t off_lsim_channel_device_v3__enabled = 96;
    inline constexpr size_t off_lsim_channel_device_v3__server_defined = 106;
    inline constexpr size_t off_lsim_channel_device_v3__reserved = 116;
    // lsim_channel_terminal_v3
    inline constexpr size_t size_lsim_channel_terminal_v3 = 112;
    inline constexpr size_t off_lsim_channel_terminal_v3__struct_size = 0;
    inline constexpr size_t off_lsim_channel_terminal_v3__abi_version = 4;
    inline constexpr size_t off_lsim_channel_terminal_v3__device_index = 8;
    inline constexpr size_t off_lsim_channel_terminal_v3__dr = 12;
    inline constexpr size_t off_lsim_channel_terminal_v3__power_index = 13;
    inline constexpr size_t off_lsim_channel_terminal_v3__reserved0 = 14;
    inline constexpr size_t off_lsim_channel_terminal_v3__dr_mask = 16;
    inline constexpr size_t off_lsim_channel_terminal_v3__enabled = 96;
    inline constexpr size_t off_lsim_channel_terminal_v3__reserved1 = 106;
    // lsim_loop_trace_v3
    inline constexpr size_t size_lsim_loop_trace_v3 = 40;
    inline constexpr size_t off_lsim_loop_trace_v3__t_ns = 0;
    inline constexpr size_t off_lsim_loop_trace_v3__device = 8;
    inline constexpr size_t off_lsim_loop_trace_v3__uplink = 12;
    inline constexpr size_t off_lsim_loop_trace_v3__downlink = 16;
    inline constexpr size_t off_lsim_loop_trace_v3__kind = 20;
    inline constexpr size_t off_lsim_loop_trace_v3__origin = 21;
    inline constexpr size_t off_lsim_loop_trace_v3__action = 22;
    inline constexpr size_t off_lsim_loop_trace_v3__target = 23;
    inline constexpr size_t off_lsim_loop_trace_v3__loss = 24;
    inline constexpr size_t off_lsim_loop_trace_v3__status = 25;
    inline constexpr size_t off_lsim_loop_trace_v3__dr = 26;
    inline constexpr size_t off_lsim_loop_trace_v3__power_index = 27;
    inline constexpr size_t off_lsim_loop_trace_v3__channel_mask = 28;
    inline constexpr size_t off_lsim_loop_trace_v3__value = 30;
    inline constexpr size_t off_lsim_loop_trace_v3__flag = 32;
    inline constexpr size_t off_lsim_loop_trace_v3__reason_channel = 33;
    inline constexpr size_t off_lsim_loop_trace_v3__reason_dr = 34;
    inline constexpr size_t off_lsim_loop_trace_v3__reason_power = 35;
    inline constexpr size_t off_lsim_loop_trace_v3__reserved = 36;
    // lsim_closed_loop_v3_args
    inline constexpr size_t size_lsim_closed_loop_v3_args = 152;
    inline constexpr size_t off_lsim_closed_loop_v3_args__struct_size = 0;
    inline constexpr size_t off_lsim_closed_loop_v3_args__abi_version = 4;
    inline constexpr size_t off_lsim_closed_loop_v3_args__channel_plan = 8;
    inline constexpr size_t off_lsim_closed_loop_v3_args__trace_enabled = 12;
    inline constexpr size_t off_lsim_closed_loop_v3_args__trace_element_size = 16;
    inline constexpr size_t off_lsim_closed_loop_v3_args__terminal_element_size = 20;
    inline constexpr size_t off_lsim_closed_loop_v3_args__reserved0 = 24;
    inline constexpr size_t off_lsim_closed_loop_v3_args__reserved1 = 28;
    inline constexpr size_t off_lsim_closed_loop_v3_args__devices = 32;
    inline constexpr size_t off_lsim_closed_loop_v3_args__device_count = 36;
    inline constexpr size_t off_lsim_closed_loop_v3_args__radios = 40;
    inline constexpr size_t off_lsim_closed_loop_v3_args__regions = 44;
    inline constexpr size_t off_lsim_closed_loop_v3_args__gateway = 48;
    inline constexpr size_t off_lsim_closed_loop_v3_args__prop = 52;
    inline constexpr size_t off_lsim_closed_loop_v3_args__env = 56;
    inline constexpr size_t off_lsim_closed_loop_v3_args__options = 60;
    inline constexpr size_t off_lsim_closed_loop_v3_args__mac = 64;
    inline constexpr size_t off_lsim_closed_loop_v3_args__mac_count = 68;
    inline constexpr size_t off_lsim_closed_loop_v3_args__channels = 72;
    inline constexpr size_t off_lsim_closed_loop_v3_args__channel_count = 76;
    inline constexpr size_t off_lsim_closed_loop_v3_args__per_device = 80;
    inline constexpr size_t off_lsim_closed_loop_v3_args__totals = 84;
    inline constexpr size_t off_lsim_closed_loop_v3_args__uplinks = 88;
    inline constexpr size_t off_lsim_closed_loop_v3_args__uplink_capacity = 92;
    inline constexpr size_t off_lsim_closed_loop_v3_args__uplink_count = 96;
    inline constexpr size_t off_lsim_closed_loop_v3_args__downlinks = 100;
    inline constexpr size_t off_lsim_closed_loop_v3_args__downlink_capacity = 104;
    inline constexpr size_t off_lsim_closed_loop_v3_args__downlink_count = 108;
    inline constexpr size_t off_lsim_closed_loop_v3_args__busy = 112;
    inline constexpr size_t off_lsim_closed_loop_v3_args__busy_capacity = 116;
    inline constexpr size_t off_lsim_closed_loop_v3_args__busy_count = 120;
    inline constexpr size_t off_lsim_closed_loop_v3_args__mac_counters = 124;
    inline constexpr size_t off_lsim_closed_loop_v3_args__trace = 128;
    inline constexpr size_t off_lsim_closed_loop_v3_args__trace_capacity = 132;
    inline constexpr size_t off_lsim_closed_loop_v3_args__trace_count = 136;
    inline constexpr size_t off_lsim_closed_loop_v3_args__terminals = 140;
    inline constexpr size_t off_lsim_closed_loop_v3_args__terminal_capacity = 144;
    inline constexpr size_t off_lsim_closed_loop_v3_args__terminal_count = 148;
    // lsim_device_rf
    inline constexpr size_t size_lsim_device_rf = 20;
    inline constexpr size_t off_lsim_device_rf__present = 0;
    inline constexpr size_t off_lsim_device_rf__antenna_gain_dbi = 4;
    inline constexpr size_t off_lsim_device_rf__cable_loss_db = 12;
    // lsim_gateway_rf
    inline constexpr size_t size_lsim_gateway_rf = 20;
    inline constexpr size_t off_lsim_gateway_rf__present = 0;
    inline constexpr size_t off_lsim_gateway_rf__antenna_gain_dbi = 4;
    inline constexpr size_t off_lsim_gateway_rf__cable_loss_db = 12;
    // lsim_closed_loop_v4_args
    inline constexpr size_t size_lsim_closed_loop_v4_args = 40;
    inline constexpr size_t off_lsim_closed_loop_v4_args__struct_size = 0;
    inline constexpr size_t off_lsim_closed_loop_v4_args__abi_version = 4;
    inline constexpr size_t off_lsim_closed_loop_v4_args__v3 = 8;
    inline constexpr size_t off_lsim_closed_loop_v4_args__device_rf = 12;
    inline constexpr size_t off_lsim_closed_loop_v4_args__device_rf_count = 16;
    inline constexpr size_t off_lsim_closed_loop_v4_args__gateway_rf = 20;
    inline constexpr size_t off_lsim_closed_loop_v4_args__reserved = 24;

#elif defined(__x86_64__)
// ---------------------------------------------------------------- x86-64 (LP64)
// pointeurs et size_t : 8 octets ; double et uint64_t alignés sur 8.
    // lsim_radio_config
    inline constexpr size_t size_lsim_radio_config = 16;
    inline constexpr size_t off_lsim_radio_config__spreading_factor = 0;
    inline constexpr size_t off_lsim_radio_config__bandwidth_hz = 4;
    inline constexpr size_t off_lsim_radio_config__coding_rate = 8;
    inline constexpr size_t off_lsim_radio_config__preamble_symbols = 10;
    inline constexpr size_t off_lsim_radio_config__crc_on = 12;
    inline constexpr size_t off_lsim_radio_config__explicit_header = 13;
    inline constexpr size_t off_lsim_radio_config__low_data_rate_optimize = 14;
    // lsim_join_keys
    inline constexpr size_t size_lsim_join_keys = 32;
    inline constexpr size_t off_lsim_join_keys__js_enc_key = 0;
    inline constexpr size_t off_lsim_join_keys__js_int_key = 16;
    // lsim_session_keys_11
    inline constexpr size_t size_lsim_session_keys_11 = 64;
    inline constexpr size_t off_lsim_session_keys_11__f_nwk_s_int_key = 0;
    inline constexpr size_t off_lsim_session_keys_11__s_nwk_s_int_key = 16;
    inline constexpr size_t off_lsim_session_keys_11__nwk_s_enc_key = 32;
    inline constexpr size_t off_lsim_session_keys_11__app_s_key = 48;
    // lsim_session_keys_10
    inline constexpr size_t size_lsim_session_keys_10 = 32;
    inline constexpr size_t off_lsim_session_keys_10__nwk_s_key = 0;
    inline constexpr size_t off_lsim_session_keys_10__app_s_key = 16;
    // lsim_uplink_frame
    inline constexpr size_t size_lsim_uplink_frame = 280;
    inline constexpr size_t off_lsim_uplink_frame__dev_addr = 0;
    inline constexpr size_t off_lsim_uplink_frame__mtype = 4;
    inline constexpr size_t off_lsim_uplink_frame__adr = 5;
    inline constexpr size_t off_lsim_uplink_frame__adr_ack_req = 6;
    inline constexpr size_t off_lsim_uplink_frame__ack = 7;
    inline constexpr size_t off_lsim_uplink_frame__class_b = 8;
    inline constexpr size_t off_lsim_uplink_frame__fcnt = 10;
    inline constexpr size_t off_lsim_uplink_frame__has_fport = 12;
    inline constexpr size_t off_lsim_uplink_frame__fport = 13;
    inline constexpr size_t off_lsim_uplink_frame__payload_len = 14;
    inline constexpr size_t off_lsim_uplink_frame__payload = 15;
    inline constexpr size_t off_lsim_uplink_frame__mic = 257;
    inline constexpr size_t off_lsim_uplink_frame__fopts_len = 261;
    inline constexpr size_t off_lsim_uplink_frame__fopts = 262;
    // lsim_uplink_context
    inline constexpr size_t size_lsim_uplink_context = 8;
    inline constexpr size_t off_lsim_uplink_context__conf_fcnt = 0;
    inline constexpr size_t off_lsim_uplink_context__tx_dr = 2;
    inline constexpr size_t off_lsim_uplink_context__tx_ch = 3;
    inline constexpr size_t off_lsim_uplink_context__fcnt32 = 4;
    // lsim_downlink_context
    inline constexpr size_t size_lsim_downlink_context = 12;
    inline constexpr size_t off_lsim_downlink_context__conf_fcnt = 0;
    inline constexpr size_t off_lsim_downlink_context__nfcnt32 = 4;
    inline constexpr size_t off_lsim_downlink_context__afcnt32 = 8;
    // lsim_join_request
    inline constexpr size_t size_lsim_join_request = 18;
    inline constexpr size_t off_lsim_join_request__join_eui = 0;
    inline constexpr size_t off_lsim_join_request__dev_eui = 8;
    inline constexpr size_t off_lsim_join_request__dev_nonce = 16;
    // lsim_join_accept
    inline constexpr size_t size_lsim_join_accept = 32;
    inline constexpr size_t off_lsim_join_accept__join_nonce = 0;
    inline constexpr size_t off_lsim_join_accept__net_id = 3;
    inline constexpr size_t off_lsim_join_accept__dev_addr = 8;
    inline constexpr size_t off_lsim_join_accept__dl_settings = 12;
    inline constexpr size_t off_lsim_join_accept__rx_delay = 13;
    inline constexpr size_t off_lsim_join_accept__has_cflist = 14;
    inline constexpr size_t off_lsim_join_accept__cflist = 15;
    // lsim_end_device
    inline constexpr size_t size_lsim_end_device = 64;
    inline constexpr size_t off_lsim_end_device__x_m = 0;
    inline constexpr size_t off_lsim_end_device__y_m = 8;
    inline constexpr size_t off_lsim_end_device__spreading_factor = 16;
    inline constexpr size_t off_lsim_end_device__payload_bytes = 20;
    inline constexpr size_t off_lsim_end_device__tx_power_dbm = 24;
    inline constexpr size_t off_lsim_end_device__start_offset_ns = 32;
    inline constexpr size_t off_lsim_end_device__period_ns = 40;
    inline constexpr size_t off_lsim_end_device__messages = 48;
    inline constexpr size_t off_lsim_end_device__duty_cycle = 56;
    // lsim_gateway
    inline constexpr size_t size_lsim_gateway = 32;
    inline constexpr size_t off_lsim_gateway__x_m = 0;
    inline constexpr size_t off_lsim_gateway__y_m = 8;
    inline constexpr size_t off_lsim_gateway__antenna_gain_dbi = 16;
    inline constexpr size_t off_lsim_gateway__rx_sensitivity_offset_db = 24;
    // lsim_gateway_v2
    inline constexpr size_t size_lsim_gateway_v2 = 232;
    inline constexpr size_t off_lsim_gateway_v2__base = 0;
    inline constexpr size_t off_lsim_gateway_v2__sensitivity_model = 32;
    inline constexpr size_t off_lsim_gateway_v2__present = 36;
    inline constexpr size_t off_lsim_gateway_v2__sensitivity_dbm = 40;
    // lsim_propagation
    inline constexpr size_t size_lsim_propagation = 48;
    inline constexpr size_t off_lsim_propagation__frequency_hz = 0;
    inline constexpr size_t off_lsim_propagation__reference_distance_m = 8;
    inline constexpr size_t off_lsim_propagation__exponent = 16;
    inline constexpr size_t off_lsim_propagation__capture_threshold_db = 24;
    inline constexpr size_t off_lsim_propagation__shadowing_sigma_db = 32;
    inline constexpr size_t off_lsim_propagation__shadowing_seed = 40;
    // lsim_device_stats
    inline constexpr size_t size_lsim_device_stats = 48;
    inline constexpr size_t off_lsim_device_stats__sent = 0;
    inline constexpr size_t off_lsim_device_stats__received = 8;
    inline constexpr size_t off_lsim_device_stats__lost_sensitivity = 16;
    inline constexpr size_t off_lsim_device_stats__lost_collision = 24;
    inline constexpr size_t off_lsim_device_stats__airtime_ns = 32;
    inline constexpr size_t off_lsim_device_stats__lost_gateway_busy = 40;
    // lsim_sim_stats
    inline constexpr size_t size_lsim_sim_stats = 80;
    inline constexpr size_t off_lsim_sim_stats__sent = 0;
    inline constexpr size_t off_lsim_sim_stats__received = 8;
    inline constexpr size_t off_lsim_sim_stats__lost_sensitivity = 16;
    inline constexpr size_t off_lsim_sim_stats__lost_collision = 24;
    inline constexpr size_t off_lsim_sim_stats__airtime_ns = 32;
    inline constexpr size_t off_lsim_sim_stats__gateway_busy_ns = 40;
    inline constexpr size_t off_lsim_sim_stats__gateway_peak_concurrent = 48;
    inline constexpr size_t off_lsim_sim_stats__observation_ns = 56;
    inline constexpr size_t off_lsim_sim_stats__gateway_utilization = 64;
    inline constexpr size_t off_lsim_sim_stats__lost_gateway_busy = 72;
    // lsim_interval
    inline constexpr size_t size_lsim_interval = 16;
    inline constexpr size_t off_lsim_interval__start_ns = 0;
    inline constexpr size_t off_lsim_interval__end_ns = 8;
    // lsim_obstacle
    inline constexpr size_t size_lsim_obstacle = 48;
    inline constexpr size_t off_lsim_obstacle__x_min_m = 0;
    inline constexpr size_t off_lsim_obstacle__y_min_m = 8;
    inline constexpr size_t off_lsim_obstacle__x_max_m = 16;
    inline constexpr size_t off_lsim_obstacle__y_max_m = 24;
    inline constexpr size_t off_lsim_obstacle__height_m = 32;
    inline constexpr size_t off_lsim_obstacle__attenuation_db = 40;
    // lsim_environment
    inline constexpr size_t size_lsim_environment = 72;
    inline constexpr size_t off_lsim_environment__grid_z = 0;
    inline constexpr size_t off_lsim_environment__grid_nx = 8;
    inline constexpr size_t off_lsim_environment__grid_ny = 12;
    inline constexpr size_t off_lsim_environment__grid_origin_x_m = 16;
    inline constexpr size_t off_lsim_environment__grid_origin_y_m = 24;
    inline constexpr size_t off_lsim_environment__grid_cell_m = 32;
    inline constexpr size_t off_lsim_environment__obstacles = 40;
    inline constexpr size_t off_lsim_environment__obstacle_count = 48;
    inline constexpr size_t off_lsim_environment__gateway_height_m = 56;
    inline constexpr size_t off_lsim_environment__device_height_m = 64;
    // lsim_tx_record
    inline constexpr size_t size_lsim_tx_record = 48;
    inline constexpr size_t off_lsim_tx_record__device_index = 0;
    inline constexpr size_t off_lsim_tx_record__start_ns = 8;
    inline constexpr size_t off_lsim_tx_record__end_ns = 16;
    inline constexpr size_t off_lsim_tx_record__spreading_factor = 24;
    inline constexpr size_t off_lsim_tx_record__rssi_dbm = 32;
    inline constexpr size_t off_lsim_tx_record__outcome = 40;
    // lsim_mac_reservation
    inline constexpr size_t size_lsim_mac_reservation = 12;
    inline constexpr size_t off_lsim_mac_reservation__device_index = 0;
    inline constexpr size_t off_lsim_mac_reservation__rank = 4;
    inline constexpr size_t off_lsim_mac_reservation__extra_bytes = 8;
    // lsim_network_stats
    inline constexpr size_t size_lsim_network_stats = 56;
    inline constexpr size_t off_lsim_network_stats__sent = 0;
    inline constexpr size_t off_lsim_network_stats__received = 8;
    inline constexpr size_t off_lsim_network_stats__duplicates = 16;
    inline constexpr size_t off_lsim_network_stats__lost_sensitivity = 24;
    inline constexpr size_t off_lsim_network_stats__lost_collision = 32;
    inline constexpr size_t off_lsim_network_stats__airtime_ns = 40;
    inline constexpr size_t off_lsim_network_stats__lost_gateway_busy = 48;
    // lsim_gateway_rx_stats
    inline constexpr size_t size_lsim_gateway_rx_stats = 64;
    inline constexpr size_t off_lsim_gateway_rx_stats__received = 0;
    inline constexpr size_t off_lsim_gateway_rx_stats__lost_sensitivity = 8;
    inline constexpr size_t off_lsim_gateway_rx_stats__lost_collision = 16;
    inline constexpr size_t off_lsim_gateway_rx_stats__lost_gateway_busy = 24;
    inline constexpr size_t off_lsim_gateway_rx_stats__audible_frames = 32;
    inline constexpr size_t off_lsim_gateway_rx_stats__busy_ns = 40;
    inline constexpr size_t off_lsim_gateway_rx_stats__peak_concurrent = 48;
    inline constexpr size_t off_lsim_gateway_rx_stats__observation_ns = 56;
    // lsim_multi_tx_record
    inline constexpr size_t size_lsim_multi_tx_record = 72;
    inline constexpr size_t off_lsim_multi_tx_record__device_index = 0;
    inline constexpr size_t off_lsim_multi_tx_record__start_ns = 8;
    inline constexpr size_t off_lsim_multi_tx_record__end_ns = 16;
    inline constexpr size_t off_lsim_multi_tx_record__spreading_factor = 24;
    inline constexpr size_t off_lsim_multi_tx_record__receivers = 28;
    inline constexpr size_t off_lsim_multi_tx_record__best_gateway = 32;
    inline constexpr size_t off_lsim_multi_tx_record__best_rssi_dbm = 40;
    inline constexpr size_t off_lsim_multi_tx_record__outcome = 48;
    inline constexpr size_t off_lsim_multi_tx_record__decoded_mask = 56;
    inline constexpr size_t off_lsim_multi_tx_record__join_request = 64;
    // lsim_downlink_rule
    inline constexpr size_t size_lsim_downlink_rule = 48;
    inline constexpr size_t off_lsim_downlink_rule__ack_uplinks = 0;
    inline constexpr size_t off_lsim_downlink_rule__every = 4;
    inline constexpr size_t off_lsim_downlink_rule__payload_bytes = 8;
    inline constexpr size_t off_lsim_downlink_rule__gateway_tx_power_dbm = 16;
    inline constexpr size_t off_lsim_downlink_rule__device_antenna_gain_dbi = 24;
    inline constexpr size_t off_lsim_downlink_rule__device_rx_offset_db = 32;
    inline constexpr size_t off_lsim_downlink_rule__join = 40;
    inline constexpr size_t off_lsim_downlink_rule__rx2_sf = 41;
    // lsim_downlink_record
    inline constexpr size_t size_lsim_downlink_record = 48;
    inline constexpr size_t off_lsim_downlink_record__device_index = 0;
    inline constexpr size_t off_lsim_downlink_record__gateway_index = 4;
    inline constexpr size_t off_lsim_downlink_record__data = 8;
    inline constexpr size_t off_lsim_downlink_record__t_open_ns = 16;
    inline constexpr size_t off_lsim_downlink_record__start_ns = 24;
    inline constexpr size_t off_lsim_downlink_record__end_ns = 32;
    inline constexpr size_t off_lsim_downlink_record__outcome = 40;
    inline constexpr size_t off_lsim_downlink_record__join = 41;
    inline constexpr size_t off_lsim_downlink_record__rx_window = 42;
    // lsim_downlink_plan
    inline constexpr size_t size_lsim_downlink_plan = 48;
    inline constexpr size_t off_lsim_downlink_plan__device_class = 0;
    inline constexpr size_t off_lsim_downlink_plan__count = 4;
    inline constexpr size_t off_lsim_downlink_plan__first_request_ns = 8;
    inline constexpr size_t off_lsim_downlink_plan__request_period_ns = 16;
    inline constexpr size_t off_lsim_downlink_plan__rx_window_ns = 24;
    inline constexpr size_t off_lsim_downlink_plan__dev_addr = 32;
    inline constexpr size_t off_lsim_downlink_plan__periodicity = 36;
    inline constexpr size_t off_lsim_downlink_plan__clock_drift_ppm = 40;
    // lsim_downlink_stats
    inline constexpr size_t size_lsim_downlink_stats = 32;
    inline constexpr size_t off_lsim_downlink_stats__requested = 0;
    inline constexpr size_t off_lsim_downlink_stats__delivered = 8;
    inline constexpr size_t off_lsim_downlink_stats__latency_sum_ns = 16;
    inline constexpr size_t off_lsim_downlink_stats__latency_max_ns = 24;
    // lsim_mac_command
    inline constexpr size_t size_lsim_mac_command = 52;
    inline constexpr size_t off_lsim_mac_command__kind = 0;
    inline constexpr size_t off_lsim_mac_command__margin = 1;
    inline constexpr size_t off_lsim_mac_command__gw_cnt = 2;
    inline constexpr size_t off_lsim_mac_command__data_rate = 3;
    inline constexpr size_t off_lsim_mac_command__tx_power = 4;
    inline constexpr size_t off_lsim_mac_command__ch_mask = 6;
    inline constexpr size_t off_lsim_mac_command__ch_mask_cntl = 8;
    inline constexpr size_t off_lsim_mac_command__nb_trans = 9;
    inline constexpr size_t off_lsim_mac_command__ack_channel_mask = 10;
    inline constexpr size_t off_lsim_mac_command__ack_data_rate = 11;
    inline constexpr size_t off_lsim_mac_command__ack_power = 12;
    inline constexpr size_t off_lsim_mac_command__max_dcycle = 13;
    inline constexpr size_t off_lsim_mac_command__battery = 14;
    inline constexpr size_t off_lsim_mac_command__dev_margin = 15;
    inline constexpr size_t off_lsim_mac_command__lorawan_minor = 16;
    inline constexpr size_t off_lsim_mac_command__rx2_data_rate = 17;
    inline constexpr size_t off_lsim_mac_command__rx1_dr_offset = 18;
    inline constexpr size_t off_lsim_mac_command__freq_100hz = 20;
    inline constexpr size_t off_lsim_mac_command__ch_index = 24;
    inline constexpr size_t off_lsim_mac_command__min_dr = 25;
    inline constexpr size_t off_lsim_mac_command__max_dr = 26;
    inline constexpr size_t off_lsim_mac_command__ack_rx_channel = 27;
    inline constexpr size_t off_lsim_mac_command__ack_rx2_data_rate = 28;
    inline constexpr size_t off_lsim_mac_command__ack_rx1_dr_offset = 29;
    inline constexpr size_t off_lsim_mac_command__ack_dr_range = 30;
    inline constexpr size_t off_lsim_mac_command__ack_channel_freq = 31;
    inline constexpr size_t off_lsim_mac_command__rx_delay = 32;
    inline constexpr size_t off_lsim_mac_command__device_time_s = 36;
    inline constexpr size_t off_lsim_mac_command__device_time_frac = 40;
    inline constexpr size_t off_lsim_mac_command__rejoin_period = 41;
    inline constexpr size_t off_lsim_mac_command__rejoin_max_retries = 42;
    inline constexpr size_t off_lsim_mac_command__rejoin_type = 43;
    inline constexpr size_t off_lsim_mac_command__max_time_n = 44;
    inline constexpr size_t off_lsim_mac_command__max_count_n = 45;
    inline constexpr size_t off_lsim_mac_command__ack_time_ok = 46;
    inline constexpr size_t off_lsim_mac_command__ack_uplink_freq_exists = 47;
    inline constexpr size_t off_lsim_mac_command__adr_limit_exp = 48;
    inline constexpr size_t off_lsim_mac_command__adr_delay_exp = 49;
    inline constexpr size_t off_lsim_mac_command__ping_periodicity = 50;
    inline constexpr size_t off_lsim_mac_command__ack_beacon_freq = 51;
    // lsim_rejoin02
    inline constexpr size_t size_lsim_rejoin02 = 14;
    inline constexpr size_t off_lsim_rejoin02__rejoin_type = 0;
    inline constexpr size_t off_lsim_rejoin02__net_id = 1;
    inline constexpr size_t off_lsim_rejoin02__dev_eui = 4;
    inline constexpr size_t off_lsim_rejoin02__rjcount0 = 12;
    // lsim_rejoin1
    inline constexpr size_t size_lsim_rejoin1 = 18;
    inline constexpr size_t off_lsim_rejoin1__join_eui = 0;
    inline constexpr size_t off_lsim_rejoin1__dev_eui = 8;
    inline constexpr size_t off_lsim_rejoin1__rjcount1 = 16;
    // lsim_mesh_radio
    inline constexpr size_t size_lsim_mesh_radio = 24;
    inline constexpr size_t off_lsim_mesh_radio__spreading_factor = 0;
    inline constexpr size_t off_lsim_mesh_radio__coding_rate = 1;
    inline constexpr size_t off_lsim_mesh_radio__bandwidth_hz = 4;
    inline constexpr size_t off_lsim_mesh_radio__payload_bytes = 8;
    inline constexpr size_t off_lsim_mesh_radio__preamble_symbols = 12;
    inline constexpr size_t off_lsim_mesh_radio__capture_db = 16;
    // lsim_mesh_frame
    inline constexpr size_t size_lsim_mesh_frame = 32;
    inline constexpr size_t off_lsim_mesh_frame__frame_id = 0;
    inline constexpr size_t off_lsim_mesh_frame__rx_node = 8;
    inline constexpr size_t off_lsim_mesh_frame__t_ns = 16;
    inline constexpr size_t off_lsim_mesh_frame__payload_bytes = 24;
    // lsim_mesh_delivery
    inline constexpr size_t size_lsim_mesh_delivery = 24;
    inline constexpr size_t off_lsim_mesh_delivery__frame_id = 0;
    inline constexpr size_t off_lsim_mesh_delivery__delivered = 8;
    inline constexpr size_t off_lsim_mesh_delivery__loss = 9;
    inline constexpr size_t off_lsim_mesh_delivery__hops = 10;
    inline constexpr size_t off_lsim_mesh_delivery__copy_state = 11;
    inline constexpr size_t off_lsim_mesh_delivery__latency_ns = 16;
    // lsim_mesh_summary
    inline constexpr size_t size_lsim_mesh_summary = 32;
    inline constexpr size_t off_lsim_mesh_summary__transmissions = 0;
    inline constexpr size_t off_lsim_mesh_summary__suppressed = 8;
    inline constexpr size_t off_lsim_mesh_summary__lost_collision = 16;
    inline constexpr size_t off_lsim_mesh_summary__lost_half_duplex = 24;
    // lsim_mesh_hop
    inline constexpr size_t size_lsim_mesh_hop = 40;
    inline constexpr size_t off_lsim_mesh_hop__frame_id = 0;
    inline constexpr size_t off_lsim_mesh_hop__sender = 8;
    inline constexpr size_t off_lsim_mesh_hop__receiver = 12;
    inline constexpr size_t off_lsim_mesh_hop__t_start_ns = 16;
    inline constexpr size_t off_lsim_mesh_hop__t_end_ns = 24;
    inline constexpr size_t off_lsim_mesh_hop__outcome = 32;
    inline constexpr size_t off_lsim_mesh_hop__hop_index = 33;
    // lsim_plan_uplink
    inline constexpr size_t size_lsim_plan_uplink = 40;
    inline constexpr size_t off_lsim_plan_uplink__device_index = 0;
    inline constexpr size_t off_lsim_plan_uplink__start_ns = 8;
    inline constexpr size_t off_lsim_plan_uplink__end_ns = 16;
    inline constexpr size_t off_lsim_plan_uplink__spreading_factor = 24;
    inline constexpr size_t off_lsim_plan_uplink__outcome = 25;
    inline constexpr size_t off_lsim_plan_uplink__rssi_dbm = 32;
    // lsim_plan_device
    inline constexpr size_t size_lsim_plan_device = 40;
    inline constexpr size_t off_lsim_plan_device__freq_hz = 0;
    inline constexpr size_t off_lsim_plan_device__dr = 8;
    inline constexpr size_t off_lsim_plan_device__rx1_hz = 16;
    inline constexpr size_t off_lsim_plan_device__tx_power_dbm = 24;
    inline constexpr size_t off_lsim_plan_device__rx1_sf = 32;
    inline constexpr size_t off_lsim_plan_device__rx1_bw_hz = 36;
    // lsim_plan_options
    inline constexpr size_t size_lsim_plan_options = 40;
    inline constexpr size_t off_lsim_plan_options__confirmed_uplinks = 0;
    inline constexpr size_t off_lsim_plan_options__downlink_every = 4;
    inline constexpr size_t off_lsim_plan_options__downlink_payload_bytes = 8;
    inline constexpr size_t off_lsim_plan_options__gateway_tx_power_dbm = 16;
    inline constexpr size_t off_lsim_plan_options__device_antenna_gain_dbi = 24;
    inline constexpr size_t off_lsim_plan_options__device_rx_offset_db = 32;
    // lsim_plan_hop
    inline constexpr size_t size_lsim_plan_hop = 40;
    inline constexpr size_t off_lsim_plan_hop__dir = 0;
    inline constexpr size_t off_lsim_plan_hop__outcome = 1;
    inline constexpr size_t off_lsim_plan_hop__has_rssi = 2;
    inline constexpr size_t off_lsim_plan_hop__t_ns = 8;
    inline constexpr size_t off_lsim_plan_hop__freq_hz = 16;
    inline constexpr size_t off_lsim_plan_hop__dr = 24;
    inline constexpr size_t off_lsim_plan_hop__rssi_dbm = 32;
    // lsim_plan_event
    inline constexpr size_t size_lsim_plan_event = 96;
    inline constexpr size_t off_lsim_plan_event__t_ns = 0;
    inline constexpr size_t off_lsim_plan_event__device_index = 8;
    inline constexpr size_t off_lsim_plan_event__kind = 12;
    inline constexpr size_t off_lsim_plan_event__outcome = 13;
    inline constexpr size_t off_lsim_plan_event__hop_count = 14;
    inline constexpr size_t off_lsim_plan_event__hops = 16;
    // lsim_loop_region
    inline constexpr size_t size_lsim_loop_region = 160;
    inline constexpr size_t off_lsim_loop_region__dr_sf = 0;
    inline constexpr size_t off_lsim_loop_region__max_dr = 16;
    inline constexpr size_t off_lsim_loop_region__max_tx_power_index = 17;
    inline constexpr size_t off_lsim_loop_region__power_step_tenth_db = 20;
    inline constexpr size_t off_lsim_loop_region__max_eirp_dbm = 24;
    inline constexpr size_t off_lsim_loop_region__duty_limit = 32;
    // lsim_loop_options
    inline constexpr size_t size_lsim_loop_options = 56;
    inline constexpr size_t off_lsim_loop_options__protocol = 0;
    inline constexpr size_t off_lsim_loop_options__adr = 40;
    inline constexpr size_t off_lsim_loop_options__installation_margin_tenth_db = 44;
    inline constexpr size_t off_lsim_loop_options__duty_cycle = 48;
    inline constexpr size_t off_lsim_loop_options__duty_cycle_exponent = 49;
    // lsim_loop_mac
    inline constexpr size_t size_lsim_loop_mac = 12;
    inline constexpr size_t off_lsim_loop_mac__device_index = 0;
    inline constexpr size_t off_lsim_loop_mac__rank = 4;
    inline constexpr size_t off_lsim_loop_mac__extra_bytes = 8;
    inline constexpr size_t off_lsim_loop_mac__flags = 9;
    // lsim_loop_mac_counters
    inline constexpr size_t size_lsim_loop_mac_counters = 56;
    inline constexpr size_t off_lsim_loop_mac_counters__enqueued = 0;
    inline constexpr size_t off_lsim_loop_mac_counters__dispatched = 8;
    inline constexpr size_t off_lsim_loop_mac_counters__delivered = 16;
    inline constexpr size_t off_lsim_loop_mac_counters__dispatch_lost = 24;
    inline constexpr size_t off_lsim_loop_mac_counters__deferred = 32;
    inline constexpr size_t off_lsim_loop_mac_counters__expired = 40;
    inline constexpr size_t off_lsim_loop_mac_counters__pending_at_end = 48;
    // lsim_loop_uplink
    inline constexpr size_t size_lsim_loop_uplink = 48;
    inline constexpr size_t off_lsim_loop_uplink__device_index = 0;
    inline constexpr size_t off_lsim_loop_uplink__start_ns = 8;
    inline constexpr size_t off_lsim_loop_uplink__end_ns = 16;
    inline constexpr size_t off_lsim_loop_uplink__spreading_factor = 24;
    inline constexpr size_t off_lsim_loop_uplink__dr = 25;
    inline constexpr size_t off_lsim_loop_uplink__power_index = 26;
    inline constexpr size_t off_lsim_loop_uplink__rssi_dbm = 32;
    inline constexpr size_t off_lsim_loop_uplink__outcome = 40;
    inline constexpr size_t off_lsim_loop_uplink__answer_mask = 41;
    inline constexpr size_t off_lsim_loop_uplink__answer_ok = 42;
    // lsim_loop_downlink
    inline constexpr size_t size_lsim_loop_downlink = 48;
    inline constexpr size_t off_lsim_loop_downlink__uplink_index = 0;
    inline constexpr size_t off_lsim_loop_downlink__device_index = 4;
    inline constexpr size_t off_lsim_loop_downlink__kind = 8;
    inline constexpr size_t off_lsim_loop_downlink__commands = 9;
    inline constexpr size_t off_lsim_loop_downlink__t_open_ns = 16;
    inline constexpr size_t off_lsim_loop_downlink__start_ns = 24;
    inline constexpr size_t off_lsim_loop_downlink__air_ns = 32;
    inline constexpr size_t off_lsim_loop_downlink__device_missed = 40;
    inline constexpr size_t off_lsim_loop_downlink__delivered = 41;
    inline constexpr size_t off_lsim_loop_downlink__req_dr = 42;
    inline constexpr size_t off_lsim_loop_downlink__req_power_index = 43;
    // lsim_channel_device_v3
    inline constexpr size_t size_lsim_channel_device_v3 = 128;
    inline constexpr size_t off_lsim_channel_device_v3__struct_size = 0;
    inline constexpr size_t off_lsim_channel_device_v3__abi_version = 4;
    inline constexpr size_t off_lsim_channel_device_v3__device_index = 8;
    inline constexpr size_t off_lsim_channel_device_v3__present = 12;
    inline constexpr size_t off_lsim_channel_device_v3__dr_mask = 16;
    inline constexpr size_t off_lsim_channel_device_v3__enabled = 96;
    inline constexpr size_t off_lsim_channel_device_v3__server_defined = 106;
    inline constexpr size_t off_lsim_channel_device_v3__reserved = 116;
    // lsim_channel_terminal_v3
    inline constexpr size_t size_lsim_channel_terminal_v3 = 112;
    inline constexpr size_t off_lsim_channel_terminal_v3__struct_size = 0;
    inline constexpr size_t off_lsim_channel_terminal_v3__abi_version = 4;
    inline constexpr size_t off_lsim_channel_terminal_v3__device_index = 8;
    inline constexpr size_t off_lsim_channel_terminal_v3__dr = 12;
    inline constexpr size_t off_lsim_channel_terminal_v3__power_index = 13;
    inline constexpr size_t off_lsim_channel_terminal_v3__reserved0 = 14;
    inline constexpr size_t off_lsim_channel_terminal_v3__dr_mask = 16;
    inline constexpr size_t off_lsim_channel_terminal_v3__enabled = 96;
    inline constexpr size_t off_lsim_channel_terminal_v3__reserved1 = 106;
    // lsim_loop_trace_v3
    inline constexpr size_t size_lsim_loop_trace_v3 = 40;
    inline constexpr size_t off_lsim_loop_trace_v3__t_ns = 0;
    inline constexpr size_t off_lsim_loop_trace_v3__device = 8;
    inline constexpr size_t off_lsim_loop_trace_v3__uplink = 12;
    inline constexpr size_t off_lsim_loop_trace_v3__downlink = 16;
    inline constexpr size_t off_lsim_loop_trace_v3__kind = 20;
    inline constexpr size_t off_lsim_loop_trace_v3__origin = 21;
    inline constexpr size_t off_lsim_loop_trace_v3__action = 22;
    inline constexpr size_t off_lsim_loop_trace_v3__target = 23;
    inline constexpr size_t off_lsim_loop_trace_v3__loss = 24;
    inline constexpr size_t off_lsim_loop_trace_v3__status = 25;
    inline constexpr size_t off_lsim_loop_trace_v3__dr = 26;
    inline constexpr size_t off_lsim_loop_trace_v3__power_index = 27;
    inline constexpr size_t off_lsim_loop_trace_v3__channel_mask = 28;
    inline constexpr size_t off_lsim_loop_trace_v3__value = 30;
    inline constexpr size_t off_lsim_loop_trace_v3__flag = 32;
    inline constexpr size_t off_lsim_loop_trace_v3__reason_channel = 33;
    inline constexpr size_t off_lsim_loop_trace_v3__reason_dr = 34;
    inline constexpr size_t off_lsim_loop_trace_v3__reason_power = 35;
    inline constexpr size_t off_lsim_loop_trace_v3__reserved = 36;
    // lsim_closed_loop_v3_args
    inline constexpr size_t size_lsim_closed_loop_v3_args = 272;
    inline constexpr size_t off_lsim_closed_loop_v3_args__struct_size = 0;
    inline constexpr size_t off_lsim_closed_loop_v3_args__abi_version = 4;
    inline constexpr size_t off_lsim_closed_loop_v3_args__channel_plan = 8;
    inline constexpr size_t off_lsim_closed_loop_v3_args__trace_enabled = 12;
    inline constexpr size_t off_lsim_closed_loop_v3_args__trace_element_size = 16;
    inline constexpr size_t off_lsim_closed_loop_v3_args__terminal_element_size = 20;
    inline constexpr size_t off_lsim_closed_loop_v3_args__reserved0 = 24;
    inline constexpr size_t off_lsim_closed_loop_v3_args__reserved1 = 28;
    inline constexpr size_t off_lsim_closed_loop_v3_args__devices = 32;
    inline constexpr size_t off_lsim_closed_loop_v3_args__device_count = 40;
    inline constexpr size_t off_lsim_closed_loop_v3_args__radios = 48;
    inline constexpr size_t off_lsim_closed_loop_v3_args__regions = 56;
    inline constexpr size_t off_lsim_closed_loop_v3_args__gateway = 64;
    inline constexpr size_t off_lsim_closed_loop_v3_args__prop = 72;
    inline constexpr size_t off_lsim_closed_loop_v3_args__env = 80;
    inline constexpr size_t off_lsim_closed_loop_v3_args__options = 88;
    inline constexpr size_t off_lsim_closed_loop_v3_args__mac = 96;
    inline constexpr size_t off_lsim_closed_loop_v3_args__mac_count = 104;
    inline constexpr size_t off_lsim_closed_loop_v3_args__channels = 112;
    inline constexpr size_t off_lsim_closed_loop_v3_args__channel_count = 120;
    inline constexpr size_t off_lsim_closed_loop_v3_args__per_device = 128;
    inline constexpr size_t off_lsim_closed_loop_v3_args__totals = 136;
    inline constexpr size_t off_lsim_closed_loop_v3_args__uplinks = 144;
    inline constexpr size_t off_lsim_closed_loop_v3_args__uplink_capacity = 152;
    inline constexpr size_t off_lsim_closed_loop_v3_args__uplink_count = 160;
    inline constexpr size_t off_lsim_closed_loop_v3_args__downlinks = 168;
    inline constexpr size_t off_lsim_closed_loop_v3_args__downlink_capacity = 176;
    inline constexpr size_t off_lsim_closed_loop_v3_args__downlink_count = 184;
    inline constexpr size_t off_lsim_closed_loop_v3_args__busy = 192;
    inline constexpr size_t off_lsim_closed_loop_v3_args__busy_capacity = 200;
    inline constexpr size_t off_lsim_closed_loop_v3_args__busy_count = 208;
    inline constexpr size_t off_lsim_closed_loop_v3_args__mac_counters = 216;
    inline constexpr size_t off_lsim_closed_loop_v3_args__trace = 224;
    inline constexpr size_t off_lsim_closed_loop_v3_args__trace_capacity = 232;
    inline constexpr size_t off_lsim_closed_loop_v3_args__trace_count = 240;
    inline constexpr size_t off_lsim_closed_loop_v3_args__terminals = 248;
    inline constexpr size_t off_lsim_closed_loop_v3_args__terminal_capacity = 256;
    inline constexpr size_t off_lsim_closed_loop_v3_args__terminal_count = 264;
    // lsim_device_rf
    inline constexpr size_t size_lsim_device_rf = 24;
    inline constexpr size_t off_lsim_device_rf__present = 0;
    inline constexpr size_t off_lsim_device_rf__antenna_gain_dbi = 8;
    inline constexpr size_t off_lsim_device_rf__cable_loss_db = 16;
    // lsim_gateway_rf
    inline constexpr size_t size_lsim_gateway_rf = 24;
    inline constexpr size_t off_lsim_gateway_rf__present = 0;
    inline constexpr size_t off_lsim_gateway_rf__antenna_gain_dbi = 8;
    inline constexpr size_t off_lsim_gateway_rf__cable_loss_db = 16;
    // lsim_closed_loop_v4_args
    inline constexpr size_t size_lsim_closed_loop_v4_args = 56;
    inline constexpr size_t off_lsim_closed_loop_v4_args__struct_size = 0;
    inline constexpr size_t off_lsim_closed_loop_v4_args__abi_version = 4;
    inline constexpr size_t off_lsim_closed_loop_v4_args__v3 = 8;
    inline constexpr size_t off_lsim_closed_loop_v4_args__device_rf = 16;
    inline constexpr size_t off_lsim_closed_loop_v4_args__device_rf_count = 24;
    inline constexpr size_t off_lsim_closed_loop_v4_args__gateway_rf = 32;
    inline constexpr size_t off_lsim_closed_loop_v4_args__reserved = 40;

#endif

}  // namespace expected

// Une table n'est valable que pour son ABI : le garde-fou est explicite.
static_assert(sizeof(void*) == kPointerSize, "taille de pointeur incohérente avec la table choisie");
static_assert(sizeof(size_t) == kPointerSize, "size_t incohérent avec la table choisie");

// ---------------------------------------------------------------- Toutes les structures

static_assert(sizeof(lsim_radio_config) == expected::size_lsim_radio_config, "lsim_radio_config : taille");
static_assert(offsetof(lsim_radio_config, spreading_factor) == expected::off_lsim_radio_config__spreading_factor, "lsim_radio_config::spreading_factor");
static_assert(offsetof(lsim_radio_config, bandwidth_hz) == expected::off_lsim_radio_config__bandwidth_hz, "lsim_radio_config::bandwidth_hz");
static_assert(offsetof(lsim_radio_config, coding_rate) == expected::off_lsim_radio_config__coding_rate, "lsim_radio_config::coding_rate");
static_assert(offsetof(lsim_radio_config, preamble_symbols) == expected::off_lsim_radio_config__preamble_symbols, "lsim_radio_config::preamble_symbols");
static_assert(offsetof(lsim_radio_config, crc_on) == expected::off_lsim_radio_config__crc_on, "lsim_radio_config::crc_on");
static_assert(offsetof(lsim_radio_config, explicit_header) == expected::off_lsim_radio_config__explicit_header, "lsim_radio_config::explicit_header");
static_assert(offsetof(lsim_radio_config, low_data_rate_optimize) == expected::off_lsim_radio_config__low_data_rate_optimize, "lsim_radio_config::low_data_rate_optimize");
static_assert(sizeof(lsim_join_keys) == expected::size_lsim_join_keys, "lsim_join_keys : taille");
static_assert(offsetof(lsim_join_keys, js_enc_key) == expected::off_lsim_join_keys__js_enc_key, "lsim_join_keys::js_enc_key");
static_assert(offsetof(lsim_join_keys, js_int_key) == expected::off_lsim_join_keys__js_int_key, "lsim_join_keys::js_int_key");
static_assert(sizeof(lsim_session_keys_11) == expected::size_lsim_session_keys_11, "lsim_session_keys_11 : taille");
static_assert(offsetof(lsim_session_keys_11, f_nwk_s_int_key) == expected::off_lsim_session_keys_11__f_nwk_s_int_key, "lsim_session_keys_11::f_nwk_s_int_key");
static_assert(offsetof(lsim_session_keys_11, s_nwk_s_int_key) == expected::off_lsim_session_keys_11__s_nwk_s_int_key, "lsim_session_keys_11::s_nwk_s_int_key");
static_assert(offsetof(lsim_session_keys_11, nwk_s_enc_key) == expected::off_lsim_session_keys_11__nwk_s_enc_key, "lsim_session_keys_11::nwk_s_enc_key");
static_assert(offsetof(lsim_session_keys_11, app_s_key) == expected::off_lsim_session_keys_11__app_s_key, "lsim_session_keys_11::app_s_key");
static_assert(sizeof(lsim_session_keys_10) == expected::size_lsim_session_keys_10, "lsim_session_keys_10 : taille");
static_assert(offsetof(lsim_session_keys_10, nwk_s_key) == expected::off_lsim_session_keys_10__nwk_s_key, "lsim_session_keys_10::nwk_s_key");
static_assert(offsetof(lsim_session_keys_10, app_s_key) == expected::off_lsim_session_keys_10__app_s_key, "lsim_session_keys_10::app_s_key");
static_assert(sizeof(lsim_uplink_frame) == expected::size_lsim_uplink_frame, "lsim_uplink_frame : taille");
static_assert(offsetof(lsim_uplink_frame, dev_addr) == expected::off_lsim_uplink_frame__dev_addr, "lsim_uplink_frame::dev_addr");
static_assert(offsetof(lsim_uplink_frame, mtype) == expected::off_lsim_uplink_frame__mtype, "lsim_uplink_frame::mtype");
static_assert(offsetof(lsim_uplink_frame, adr) == expected::off_lsim_uplink_frame__adr, "lsim_uplink_frame::adr");
static_assert(offsetof(lsim_uplink_frame, adr_ack_req) == expected::off_lsim_uplink_frame__adr_ack_req, "lsim_uplink_frame::adr_ack_req");
static_assert(offsetof(lsim_uplink_frame, ack) == expected::off_lsim_uplink_frame__ack, "lsim_uplink_frame::ack");
static_assert(offsetof(lsim_uplink_frame, class_b) == expected::off_lsim_uplink_frame__class_b, "lsim_uplink_frame::class_b");
static_assert(offsetof(lsim_uplink_frame, fcnt) == expected::off_lsim_uplink_frame__fcnt, "lsim_uplink_frame::fcnt");
static_assert(offsetof(lsim_uplink_frame, has_fport) == expected::off_lsim_uplink_frame__has_fport, "lsim_uplink_frame::has_fport");
static_assert(offsetof(lsim_uplink_frame, fport) == expected::off_lsim_uplink_frame__fport, "lsim_uplink_frame::fport");
static_assert(offsetof(lsim_uplink_frame, payload_len) == expected::off_lsim_uplink_frame__payload_len, "lsim_uplink_frame::payload_len");
static_assert(offsetof(lsim_uplink_frame, payload) == expected::off_lsim_uplink_frame__payload, "lsim_uplink_frame::payload");
static_assert(offsetof(lsim_uplink_frame, mic) == expected::off_lsim_uplink_frame__mic, "lsim_uplink_frame::mic");
static_assert(offsetof(lsim_uplink_frame, fopts_len) == expected::off_lsim_uplink_frame__fopts_len, "lsim_uplink_frame::fopts_len");
static_assert(offsetof(lsim_uplink_frame, fopts) == expected::off_lsim_uplink_frame__fopts, "lsim_uplink_frame::fopts");
static_assert(sizeof(lsim_uplink_context) == expected::size_lsim_uplink_context, "lsim_uplink_context : taille");
static_assert(offsetof(lsim_uplink_context, conf_fcnt) == expected::off_lsim_uplink_context__conf_fcnt, "lsim_uplink_context::conf_fcnt");
static_assert(offsetof(lsim_uplink_context, tx_dr) == expected::off_lsim_uplink_context__tx_dr, "lsim_uplink_context::tx_dr");
static_assert(offsetof(lsim_uplink_context, tx_ch) == expected::off_lsim_uplink_context__tx_ch, "lsim_uplink_context::tx_ch");
static_assert(offsetof(lsim_uplink_context, fcnt32) == expected::off_lsim_uplink_context__fcnt32, "lsim_uplink_context::fcnt32");
static_assert(sizeof(lsim_downlink_context) == expected::size_lsim_downlink_context, "lsim_downlink_context : taille");
static_assert(offsetof(lsim_downlink_context, conf_fcnt) == expected::off_lsim_downlink_context__conf_fcnt, "lsim_downlink_context::conf_fcnt");
static_assert(offsetof(lsim_downlink_context, nfcnt32) == expected::off_lsim_downlink_context__nfcnt32, "lsim_downlink_context::nfcnt32");
static_assert(offsetof(lsim_downlink_context, afcnt32) == expected::off_lsim_downlink_context__afcnt32, "lsim_downlink_context::afcnt32");
static_assert(sizeof(lsim_join_request) == expected::size_lsim_join_request, "lsim_join_request : taille");
static_assert(offsetof(lsim_join_request, join_eui) == expected::off_lsim_join_request__join_eui, "lsim_join_request::join_eui");
static_assert(offsetof(lsim_join_request, dev_eui) == expected::off_lsim_join_request__dev_eui, "lsim_join_request::dev_eui");
static_assert(offsetof(lsim_join_request, dev_nonce) == expected::off_lsim_join_request__dev_nonce, "lsim_join_request::dev_nonce");
static_assert(sizeof(lsim_join_accept) == expected::size_lsim_join_accept, "lsim_join_accept : taille");
static_assert(offsetof(lsim_join_accept, join_nonce) == expected::off_lsim_join_accept__join_nonce, "lsim_join_accept::join_nonce");
static_assert(offsetof(lsim_join_accept, net_id) == expected::off_lsim_join_accept__net_id, "lsim_join_accept::net_id");
static_assert(offsetof(lsim_join_accept, dev_addr) == expected::off_lsim_join_accept__dev_addr, "lsim_join_accept::dev_addr");
static_assert(offsetof(lsim_join_accept, dl_settings) == expected::off_lsim_join_accept__dl_settings, "lsim_join_accept::dl_settings");
static_assert(offsetof(lsim_join_accept, rx_delay) == expected::off_lsim_join_accept__rx_delay, "lsim_join_accept::rx_delay");
static_assert(offsetof(lsim_join_accept, has_cflist) == expected::off_lsim_join_accept__has_cflist, "lsim_join_accept::has_cflist");
static_assert(offsetof(lsim_join_accept, cflist) == expected::off_lsim_join_accept__cflist, "lsim_join_accept::cflist");
static_assert(sizeof(lsim_end_device) == expected::size_lsim_end_device, "lsim_end_device : taille");
static_assert(offsetof(lsim_end_device, x_m) == expected::off_lsim_end_device__x_m, "lsim_end_device::x_m");
static_assert(offsetof(lsim_end_device, y_m) == expected::off_lsim_end_device__y_m, "lsim_end_device::y_m");
static_assert(offsetof(lsim_end_device, spreading_factor) == expected::off_lsim_end_device__spreading_factor, "lsim_end_device::spreading_factor");
static_assert(offsetof(lsim_end_device, payload_bytes) == expected::off_lsim_end_device__payload_bytes, "lsim_end_device::payload_bytes");
static_assert(offsetof(lsim_end_device, tx_power_dbm) == expected::off_lsim_end_device__tx_power_dbm, "lsim_end_device::tx_power_dbm");
static_assert(offsetof(lsim_end_device, start_offset_ns) == expected::off_lsim_end_device__start_offset_ns, "lsim_end_device::start_offset_ns");
static_assert(offsetof(lsim_end_device, period_ns) == expected::off_lsim_end_device__period_ns, "lsim_end_device::period_ns");
static_assert(offsetof(lsim_end_device, messages) == expected::off_lsim_end_device__messages, "lsim_end_device::messages");
static_assert(offsetof(lsim_end_device, duty_cycle) == expected::off_lsim_end_device__duty_cycle, "lsim_end_device::duty_cycle");
static_assert(sizeof(lsim_gateway) == expected::size_lsim_gateway, "lsim_gateway : taille");
static_assert(offsetof(lsim_gateway, x_m) == expected::off_lsim_gateway__x_m, "lsim_gateway::x_m");
static_assert(offsetof(lsim_gateway, y_m) == expected::off_lsim_gateway__y_m, "lsim_gateway::y_m");
static_assert(offsetof(lsim_gateway, antenna_gain_dbi) == expected::off_lsim_gateway__antenna_gain_dbi, "lsim_gateway::antenna_gain_dbi");
static_assert(offsetof(lsim_gateway, rx_sensitivity_offset_db) == expected::off_lsim_gateway__rx_sensitivity_offset_db, "lsim_gateway::rx_sensitivity_offset_db");
static_assert(sizeof(lsim_gateway_v2) == expected::size_lsim_gateway_v2, "lsim_gateway_v2 : taille");
static_assert(offsetof(lsim_gateway_v2, base) == expected::off_lsim_gateway_v2__base, "lsim_gateway_v2::base");
static_assert(offsetof(lsim_gateway_v2, sensitivity_model) == expected::off_lsim_gateway_v2__sensitivity_model, "lsim_gateway_v2::sensitivity_model");
static_assert(offsetof(lsim_gateway_v2, present) == expected::off_lsim_gateway_v2__present, "lsim_gateway_v2::present");
static_assert(offsetof(lsim_gateway_v2, sensitivity_dbm) == expected::off_lsim_gateway_v2__sensitivity_dbm, "lsim_gateway_v2::sensitivity_dbm");
static_assert(sizeof(lsim_propagation) == expected::size_lsim_propagation, "lsim_propagation : taille");
static_assert(offsetof(lsim_propagation, frequency_hz) == expected::off_lsim_propagation__frequency_hz, "lsim_propagation::frequency_hz");
static_assert(offsetof(lsim_propagation, reference_distance_m) == expected::off_lsim_propagation__reference_distance_m, "lsim_propagation::reference_distance_m");
static_assert(offsetof(lsim_propagation, exponent) == expected::off_lsim_propagation__exponent, "lsim_propagation::exponent");
static_assert(offsetof(lsim_propagation, capture_threshold_db) == expected::off_lsim_propagation__capture_threshold_db, "lsim_propagation::capture_threshold_db");
static_assert(offsetof(lsim_propagation, shadowing_sigma_db) == expected::off_lsim_propagation__shadowing_sigma_db, "lsim_propagation::shadowing_sigma_db");
static_assert(offsetof(lsim_propagation, shadowing_seed) == expected::off_lsim_propagation__shadowing_seed, "lsim_propagation::shadowing_seed");
static_assert(sizeof(lsim_device_stats) == expected::size_lsim_device_stats, "lsim_device_stats : taille");
static_assert(offsetof(lsim_device_stats, sent) == expected::off_lsim_device_stats__sent, "lsim_device_stats::sent");
static_assert(offsetof(lsim_device_stats, received) == expected::off_lsim_device_stats__received, "lsim_device_stats::received");
static_assert(offsetof(lsim_device_stats, lost_sensitivity) == expected::off_lsim_device_stats__lost_sensitivity, "lsim_device_stats::lost_sensitivity");
static_assert(offsetof(lsim_device_stats, lost_collision) == expected::off_lsim_device_stats__lost_collision, "lsim_device_stats::lost_collision");
static_assert(offsetof(lsim_device_stats, airtime_ns) == expected::off_lsim_device_stats__airtime_ns, "lsim_device_stats::airtime_ns");
static_assert(offsetof(lsim_device_stats, lost_gateway_busy) == expected::off_lsim_device_stats__lost_gateway_busy, "lsim_device_stats::lost_gateway_busy");
static_assert(sizeof(lsim_sim_stats) == expected::size_lsim_sim_stats, "lsim_sim_stats : taille");
static_assert(offsetof(lsim_sim_stats, sent) == expected::off_lsim_sim_stats__sent, "lsim_sim_stats::sent");
static_assert(offsetof(lsim_sim_stats, received) == expected::off_lsim_sim_stats__received, "lsim_sim_stats::received");
static_assert(offsetof(lsim_sim_stats, lost_sensitivity) == expected::off_lsim_sim_stats__lost_sensitivity, "lsim_sim_stats::lost_sensitivity");
static_assert(offsetof(lsim_sim_stats, lost_collision) == expected::off_lsim_sim_stats__lost_collision, "lsim_sim_stats::lost_collision");
static_assert(offsetof(lsim_sim_stats, airtime_ns) == expected::off_lsim_sim_stats__airtime_ns, "lsim_sim_stats::airtime_ns");
static_assert(offsetof(lsim_sim_stats, gateway_busy_ns) == expected::off_lsim_sim_stats__gateway_busy_ns, "lsim_sim_stats::gateway_busy_ns");
static_assert(offsetof(lsim_sim_stats, gateway_peak_concurrent) == expected::off_lsim_sim_stats__gateway_peak_concurrent, "lsim_sim_stats::gateway_peak_concurrent");
static_assert(offsetof(lsim_sim_stats, observation_ns) == expected::off_lsim_sim_stats__observation_ns, "lsim_sim_stats::observation_ns");
static_assert(offsetof(lsim_sim_stats, gateway_utilization) == expected::off_lsim_sim_stats__gateway_utilization, "lsim_sim_stats::gateway_utilization");
static_assert(offsetof(lsim_sim_stats, lost_gateway_busy) == expected::off_lsim_sim_stats__lost_gateway_busy, "lsim_sim_stats::lost_gateway_busy");
static_assert(sizeof(lsim_interval) == expected::size_lsim_interval, "lsim_interval : taille");
static_assert(offsetof(lsim_interval, start_ns) == expected::off_lsim_interval__start_ns, "lsim_interval::start_ns");
static_assert(offsetof(lsim_interval, end_ns) == expected::off_lsim_interval__end_ns, "lsim_interval::end_ns");
static_assert(sizeof(lsim_obstacle) == expected::size_lsim_obstacle, "lsim_obstacle : taille");
static_assert(offsetof(lsim_obstacle, x_min_m) == expected::off_lsim_obstacle__x_min_m, "lsim_obstacle::x_min_m");
static_assert(offsetof(lsim_obstacle, y_min_m) == expected::off_lsim_obstacle__y_min_m, "lsim_obstacle::y_min_m");
static_assert(offsetof(lsim_obstacle, x_max_m) == expected::off_lsim_obstacle__x_max_m, "lsim_obstacle::x_max_m");
static_assert(offsetof(lsim_obstacle, y_max_m) == expected::off_lsim_obstacle__y_max_m, "lsim_obstacle::y_max_m");
static_assert(offsetof(lsim_obstacle, height_m) == expected::off_lsim_obstacle__height_m, "lsim_obstacle::height_m");
static_assert(offsetof(lsim_obstacle, attenuation_db) == expected::off_lsim_obstacle__attenuation_db, "lsim_obstacle::attenuation_db");
static_assert(sizeof(lsim_environment) == expected::size_lsim_environment, "lsim_environment : taille");
static_assert(offsetof(lsim_environment, grid_z) == expected::off_lsim_environment__grid_z, "lsim_environment::grid_z");
static_assert(offsetof(lsim_environment, grid_nx) == expected::off_lsim_environment__grid_nx, "lsim_environment::grid_nx");
static_assert(offsetof(lsim_environment, grid_ny) == expected::off_lsim_environment__grid_ny, "lsim_environment::grid_ny");
static_assert(offsetof(lsim_environment, grid_origin_x_m) == expected::off_lsim_environment__grid_origin_x_m, "lsim_environment::grid_origin_x_m");
static_assert(offsetof(lsim_environment, grid_origin_y_m) == expected::off_lsim_environment__grid_origin_y_m, "lsim_environment::grid_origin_y_m");
static_assert(offsetof(lsim_environment, grid_cell_m) == expected::off_lsim_environment__grid_cell_m, "lsim_environment::grid_cell_m");
static_assert(offsetof(lsim_environment, obstacles) == expected::off_lsim_environment__obstacles, "lsim_environment::obstacles");
static_assert(offsetof(lsim_environment, obstacle_count) == expected::off_lsim_environment__obstacle_count, "lsim_environment::obstacle_count");
static_assert(offsetof(lsim_environment, gateway_height_m) == expected::off_lsim_environment__gateway_height_m, "lsim_environment::gateway_height_m");
static_assert(offsetof(lsim_environment, device_height_m) == expected::off_lsim_environment__device_height_m, "lsim_environment::device_height_m");
static_assert(sizeof(lsim_tx_record) == expected::size_lsim_tx_record, "lsim_tx_record : taille");
static_assert(offsetof(lsim_tx_record, device_index) == expected::off_lsim_tx_record__device_index, "lsim_tx_record::device_index");
static_assert(offsetof(lsim_tx_record, start_ns) == expected::off_lsim_tx_record__start_ns, "lsim_tx_record::start_ns");
static_assert(offsetof(lsim_tx_record, end_ns) == expected::off_lsim_tx_record__end_ns, "lsim_tx_record::end_ns");
static_assert(offsetof(lsim_tx_record, spreading_factor) == expected::off_lsim_tx_record__spreading_factor, "lsim_tx_record::spreading_factor");
static_assert(offsetof(lsim_tx_record, rssi_dbm) == expected::off_lsim_tx_record__rssi_dbm, "lsim_tx_record::rssi_dbm");
static_assert(offsetof(lsim_tx_record, outcome) == expected::off_lsim_tx_record__outcome, "lsim_tx_record::outcome");
static_assert(sizeof(lsim_mac_reservation) == expected::size_lsim_mac_reservation, "lsim_mac_reservation : taille");
static_assert(offsetof(lsim_mac_reservation, device_index) == expected::off_lsim_mac_reservation__device_index, "lsim_mac_reservation::device_index");
static_assert(offsetof(lsim_mac_reservation, rank) == expected::off_lsim_mac_reservation__rank, "lsim_mac_reservation::rank");
static_assert(offsetof(lsim_mac_reservation, extra_bytes) == expected::off_lsim_mac_reservation__extra_bytes, "lsim_mac_reservation::extra_bytes");
static_assert(sizeof(lsim_network_stats) == expected::size_lsim_network_stats, "lsim_network_stats : taille");
static_assert(offsetof(lsim_network_stats, sent) == expected::off_lsim_network_stats__sent, "lsim_network_stats::sent");
static_assert(offsetof(lsim_network_stats, received) == expected::off_lsim_network_stats__received, "lsim_network_stats::received");
static_assert(offsetof(lsim_network_stats, duplicates) == expected::off_lsim_network_stats__duplicates, "lsim_network_stats::duplicates");
static_assert(offsetof(lsim_network_stats, lost_sensitivity) == expected::off_lsim_network_stats__lost_sensitivity, "lsim_network_stats::lost_sensitivity");
static_assert(offsetof(lsim_network_stats, lost_collision) == expected::off_lsim_network_stats__lost_collision, "lsim_network_stats::lost_collision");
static_assert(offsetof(lsim_network_stats, airtime_ns) == expected::off_lsim_network_stats__airtime_ns, "lsim_network_stats::airtime_ns");
static_assert(offsetof(lsim_network_stats, lost_gateway_busy) == expected::off_lsim_network_stats__lost_gateway_busy, "lsim_network_stats::lost_gateway_busy");
static_assert(sizeof(lsim_gateway_rx_stats) == expected::size_lsim_gateway_rx_stats, "lsim_gateway_rx_stats : taille");
static_assert(offsetof(lsim_gateway_rx_stats, received) == expected::off_lsim_gateway_rx_stats__received, "lsim_gateway_rx_stats::received");
static_assert(offsetof(lsim_gateway_rx_stats, lost_sensitivity) == expected::off_lsim_gateway_rx_stats__lost_sensitivity, "lsim_gateway_rx_stats::lost_sensitivity");
static_assert(offsetof(lsim_gateway_rx_stats, lost_collision) == expected::off_lsim_gateway_rx_stats__lost_collision, "lsim_gateway_rx_stats::lost_collision");
static_assert(offsetof(lsim_gateway_rx_stats, lost_gateway_busy) == expected::off_lsim_gateway_rx_stats__lost_gateway_busy, "lsim_gateway_rx_stats::lost_gateway_busy");
static_assert(offsetof(lsim_gateway_rx_stats, audible_frames) == expected::off_lsim_gateway_rx_stats__audible_frames, "lsim_gateway_rx_stats::audible_frames");
static_assert(offsetof(lsim_gateway_rx_stats, busy_ns) == expected::off_lsim_gateway_rx_stats__busy_ns, "lsim_gateway_rx_stats::busy_ns");
static_assert(offsetof(lsim_gateway_rx_stats, peak_concurrent) == expected::off_lsim_gateway_rx_stats__peak_concurrent, "lsim_gateway_rx_stats::peak_concurrent");
static_assert(offsetof(lsim_gateway_rx_stats, observation_ns) == expected::off_lsim_gateway_rx_stats__observation_ns, "lsim_gateway_rx_stats::observation_ns");
static_assert(sizeof(lsim_multi_tx_record) == expected::size_lsim_multi_tx_record, "lsim_multi_tx_record : taille");
static_assert(offsetof(lsim_multi_tx_record, device_index) == expected::off_lsim_multi_tx_record__device_index, "lsim_multi_tx_record::device_index");
static_assert(offsetof(lsim_multi_tx_record, start_ns) == expected::off_lsim_multi_tx_record__start_ns, "lsim_multi_tx_record::start_ns");
static_assert(offsetof(lsim_multi_tx_record, end_ns) == expected::off_lsim_multi_tx_record__end_ns, "lsim_multi_tx_record::end_ns");
static_assert(offsetof(lsim_multi_tx_record, spreading_factor) == expected::off_lsim_multi_tx_record__spreading_factor, "lsim_multi_tx_record::spreading_factor");
static_assert(offsetof(lsim_multi_tx_record, receivers) == expected::off_lsim_multi_tx_record__receivers, "lsim_multi_tx_record::receivers");
static_assert(offsetof(lsim_multi_tx_record, best_gateway) == expected::off_lsim_multi_tx_record__best_gateway, "lsim_multi_tx_record::best_gateway");
static_assert(offsetof(lsim_multi_tx_record, best_rssi_dbm) == expected::off_lsim_multi_tx_record__best_rssi_dbm, "lsim_multi_tx_record::best_rssi_dbm");
static_assert(offsetof(lsim_multi_tx_record, outcome) == expected::off_lsim_multi_tx_record__outcome, "lsim_multi_tx_record::outcome");
static_assert(offsetof(lsim_multi_tx_record, decoded_mask) == expected::off_lsim_multi_tx_record__decoded_mask, "lsim_multi_tx_record::decoded_mask");
static_assert(offsetof(lsim_multi_tx_record, join_request) == expected::off_lsim_multi_tx_record__join_request, "lsim_multi_tx_record::join_request");
static_assert(sizeof(lsim_downlink_rule) == expected::size_lsim_downlink_rule, "lsim_downlink_rule : taille");
static_assert(offsetof(lsim_downlink_rule, ack_uplinks) == expected::off_lsim_downlink_rule__ack_uplinks, "lsim_downlink_rule::ack_uplinks");
static_assert(offsetof(lsim_downlink_rule, every) == expected::off_lsim_downlink_rule__every, "lsim_downlink_rule::every");
static_assert(offsetof(lsim_downlink_rule, payload_bytes) == expected::off_lsim_downlink_rule__payload_bytes, "lsim_downlink_rule::payload_bytes");
static_assert(offsetof(lsim_downlink_rule, gateway_tx_power_dbm) == expected::off_lsim_downlink_rule__gateway_tx_power_dbm, "lsim_downlink_rule::gateway_tx_power_dbm");
static_assert(offsetof(lsim_downlink_rule, device_antenna_gain_dbi) == expected::off_lsim_downlink_rule__device_antenna_gain_dbi, "lsim_downlink_rule::device_antenna_gain_dbi");
static_assert(offsetof(lsim_downlink_rule, device_rx_offset_db) == expected::off_lsim_downlink_rule__device_rx_offset_db, "lsim_downlink_rule::device_rx_offset_db");
static_assert(offsetof(lsim_downlink_rule, join) == expected::off_lsim_downlink_rule__join, "lsim_downlink_rule::join");
static_assert(offsetof(lsim_downlink_rule, rx2_sf) == expected::off_lsim_downlink_rule__rx2_sf, "lsim_downlink_rule::rx2_sf");
static_assert(sizeof(lsim_downlink_record) == expected::size_lsim_downlink_record, "lsim_downlink_record : taille");
static_assert(offsetof(lsim_downlink_record, device_index) == expected::off_lsim_downlink_record__device_index, "lsim_downlink_record::device_index");
static_assert(offsetof(lsim_downlink_record, gateway_index) == expected::off_lsim_downlink_record__gateway_index, "lsim_downlink_record::gateway_index");
static_assert(offsetof(lsim_downlink_record, data) == expected::off_lsim_downlink_record__data, "lsim_downlink_record::data");
static_assert(offsetof(lsim_downlink_record, t_open_ns) == expected::off_lsim_downlink_record__t_open_ns, "lsim_downlink_record::t_open_ns");
static_assert(offsetof(lsim_downlink_record, start_ns) == expected::off_lsim_downlink_record__start_ns, "lsim_downlink_record::start_ns");
static_assert(offsetof(lsim_downlink_record, end_ns) == expected::off_lsim_downlink_record__end_ns, "lsim_downlink_record::end_ns");
static_assert(offsetof(lsim_downlink_record, outcome) == expected::off_lsim_downlink_record__outcome, "lsim_downlink_record::outcome");
static_assert(offsetof(lsim_downlink_record, join) == expected::off_lsim_downlink_record__join, "lsim_downlink_record::join");
static_assert(offsetof(lsim_downlink_record, rx_window) == expected::off_lsim_downlink_record__rx_window, "lsim_downlink_record::rx_window");
static_assert(sizeof(lsim_downlink_plan) == expected::size_lsim_downlink_plan, "lsim_downlink_plan : taille");
static_assert(offsetof(lsim_downlink_plan, device_class) == expected::off_lsim_downlink_plan__device_class, "lsim_downlink_plan::device_class");
static_assert(offsetof(lsim_downlink_plan, count) == expected::off_lsim_downlink_plan__count, "lsim_downlink_plan::count");
static_assert(offsetof(lsim_downlink_plan, first_request_ns) == expected::off_lsim_downlink_plan__first_request_ns, "lsim_downlink_plan::first_request_ns");
static_assert(offsetof(lsim_downlink_plan, request_period_ns) == expected::off_lsim_downlink_plan__request_period_ns, "lsim_downlink_plan::request_period_ns");
static_assert(offsetof(lsim_downlink_plan, rx_window_ns) == expected::off_lsim_downlink_plan__rx_window_ns, "lsim_downlink_plan::rx_window_ns");
static_assert(offsetof(lsim_downlink_plan, dev_addr) == expected::off_lsim_downlink_plan__dev_addr, "lsim_downlink_plan::dev_addr");
static_assert(offsetof(lsim_downlink_plan, periodicity) == expected::off_lsim_downlink_plan__periodicity, "lsim_downlink_plan::periodicity");
static_assert(offsetof(lsim_downlink_plan, clock_drift_ppm) == expected::off_lsim_downlink_plan__clock_drift_ppm, "lsim_downlink_plan::clock_drift_ppm");
static_assert(sizeof(lsim_downlink_stats) == expected::size_lsim_downlink_stats, "lsim_downlink_stats : taille");
static_assert(offsetof(lsim_downlink_stats, requested) == expected::off_lsim_downlink_stats__requested, "lsim_downlink_stats::requested");
static_assert(offsetof(lsim_downlink_stats, delivered) == expected::off_lsim_downlink_stats__delivered, "lsim_downlink_stats::delivered");
static_assert(offsetof(lsim_downlink_stats, latency_sum_ns) == expected::off_lsim_downlink_stats__latency_sum_ns, "lsim_downlink_stats::latency_sum_ns");
static_assert(offsetof(lsim_downlink_stats, latency_max_ns) == expected::off_lsim_downlink_stats__latency_max_ns, "lsim_downlink_stats::latency_max_ns");
static_assert(sizeof(lsim_mac_command) == expected::size_lsim_mac_command, "lsim_mac_command : taille");
static_assert(offsetof(lsim_mac_command, kind) == expected::off_lsim_mac_command__kind, "lsim_mac_command::kind");
static_assert(offsetof(lsim_mac_command, margin) == expected::off_lsim_mac_command__margin, "lsim_mac_command::margin");
static_assert(offsetof(lsim_mac_command, gw_cnt) == expected::off_lsim_mac_command__gw_cnt, "lsim_mac_command::gw_cnt");
static_assert(offsetof(lsim_mac_command, data_rate) == expected::off_lsim_mac_command__data_rate, "lsim_mac_command::data_rate");
static_assert(offsetof(lsim_mac_command, tx_power) == expected::off_lsim_mac_command__tx_power, "lsim_mac_command::tx_power");
static_assert(offsetof(lsim_mac_command, ch_mask) == expected::off_lsim_mac_command__ch_mask, "lsim_mac_command::ch_mask");
static_assert(offsetof(lsim_mac_command, ch_mask_cntl) == expected::off_lsim_mac_command__ch_mask_cntl, "lsim_mac_command::ch_mask_cntl");
static_assert(offsetof(lsim_mac_command, nb_trans) == expected::off_lsim_mac_command__nb_trans, "lsim_mac_command::nb_trans");
static_assert(offsetof(lsim_mac_command, ack_channel_mask) == expected::off_lsim_mac_command__ack_channel_mask, "lsim_mac_command::ack_channel_mask");
static_assert(offsetof(lsim_mac_command, ack_data_rate) == expected::off_lsim_mac_command__ack_data_rate, "lsim_mac_command::ack_data_rate");
static_assert(offsetof(lsim_mac_command, ack_power) == expected::off_lsim_mac_command__ack_power, "lsim_mac_command::ack_power");
static_assert(offsetof(lsim_mac_command, max_dcycle) == expected::off_lsim_mac_command__max_dcycle, "lsim_mac_command::max_dcycle");
static_assert(offsetof(lsim_mac_command, battery) == expected::off_lsim_mac_command__battery, "lsim_mac_command::battery");
static_assert(offsetof(lsim_mac_command, dev_margin) == expected::off_lsim_mac_command__dev_margin, "lsim_mac_command::dev_margin");
static_assert(offsetof(lsim_mac_command, lorawan_minor) == expected::off_lsim_mac_command__lorawan_minor, "lsim_mac_command::lorawan_minor");
static_assert(offsetof(lsim_mac_command, rx2_data_rate) == expected::off_lsim_mac_command__rx2_data_rate, "lsim_mac_command::rx2_data_rate");
static_assert(offsetof(lsim_mac_command, rx1_dr_offset) == expected::off_lsim_mac_command__rx1_dr_offset, "lsim_mac_command::rx1_dr_offset");
static_assert(offsetof(lsim_mac_command, freq_100hz) == expected::off_lsim_mac_command__freq_100hz, "lsim_mac_command::freq_100hz");
static_assert(offsetof(lsim_mac_command, ch_index) == expected::off_lsim_mac_command__ch_index, "lsim_mac_command::ch_index");
static_assert(offsetof(lsim_mac_command, min_dr) == expected::off_lsim_mac_command__min_dr, "lsim_mac_command::min_dr");
static_assert(offsetof(lsim_mac_command, max_dr) == expected::off_lsim_mac_command__max_dr, "lsim_mac_command::max_dr");
static_assert(offsetof(lsim_mac_command, ack_rx_channel) == expected::off_lsim_mac_command__ack_rx_channel, "lsim_mac_command::ack_rx_channel");
static_assert(offsetof(lsim_mac_command, ack_rx2_data_rate) == expected::off_lsim_mac_command__ack_rx2_data_rate, "lsim_mac_command::ack_rx2_data_rate");
static_assert(offsetof(lsim_mac_command, ack_rx1_dr_offset) == expected::off_lsim_mac_command__ack_rx1_dr_offset, "lsim_mac_command::ack_rx1_dr_offset");
static_assert(offsetof(lsim_mac_command, ack_dr_range) == expected::off_lsim_mac_command__ack_dr_range, "lsim_mac_command::ack_dr_range");
static_assert(offsetof(lsim_mac_command, ack_channel_freq) == expected::off_lsim_mac_command__ack_channel_freq, "lsim_mac_command::ack_channel_freq");
static_assert(offsetof(lsim_mac_command, rx_delay) == expected::off_lsim_mac_command__rx_delay, "lsim_mac_command::rx_delay");
static_assert(offsetof(lsim_mac_command, device_time_s) == expected::off_lsim_mac_command__device_time_s, "lsim_mac_command::device_time_s");
static_assert(offsetof(lsim_mac_command, device_time_frac) == expected::off_lsim_mac_command__device_time_frac, "lsim_mac_command::device_time_frac");
static_assert(offsetof(lsim_mac_command, rejoin_period) == expected::off_lsim_mac_command__rejoin_period, "lsim_mac_command::rejoin_period");
static_assert(offsetof(lsim_mac_command, rejoin_max_retries) == expected::off_lsim_mac_command__rejoin_max_retries, "lsim_mac_command::rejoin_max_retries");
static_assert(offsetof(lsim_mac_command, rejoin_type) == expected::off_lsim_mac_command__rejoin_type, "lsim_mac_command::rejoin_type");
static_assert(offsetof(lsim_mac_command, max_time_n) == expected::off_lsim_mac_command__max_time_n, "lsim_mac_command::max_time_n");
static_assert(offsetof(lsim_mac_command, max_count_n) == expected::off_lsim_mac_command__max_count_n, "lsim_mac_command::max_count_n");
static_assert(offsetof(lsim_mac_command, ack_time_ok) == expected::off_lsim_mac_command__ack_time_ok, "lsim_mac_command::ack_time_ok");
static_assert(offsetof(lsim_mac_command, ack_uplink_freq_exists) == expected::off_lsim_mac_command__ack_uplink_freq_exists, "lsim_mac_command::ack_uplink_freq_exists");
static_assert(offsetof(lsim_mac_command, adr_limit_exp) == expected::off_lsim_mac_command__adr_limit_exp, "lsim_mac_command::adr_limit_exp");
static_assert(offsetof(lsim_mac_command, adr_delay_exp) == expected::off_lsim_mac_command__adr_delay_exp, "lsim_mac_command::adr_delay_exp");
static_assert(offsetof(lsim_mac_command, ping_periodicity) == expected::off_lsim_mac_command__ping_periodicity, "lsim_mac_command::ping_periodicity");
static_assert(offsetof(lsim_mac_command, ack_beacon_freq) == expected::off_lsim_mac_command__ack_beacon_freq, "lsim_mac_command::ack_beacon_freq");
static_assert(sizeof(lsim_rejoin02) == expected::size_lsim_rejoin02, "lsim_rejoin02 : taille");
static_assert(offsetof(lsim_rejoin02, rejoin_type) == expected::off_lsim_rejoin02__rejoin_type, "lsim_rejoin02::rejoin_type");
static_assert(offsetof(lsim_rejoin02, net_id) == expected::off_lsim_rejoin02__net_id, "lsim_rejoin02::net_id");
static_assert(offsetof(lsim_rejoin02, dev_eui) == expected::off_lsim_rejoin02__dev_eui, "lsim_rejoin02::dev_eui");
static_assert(offsetof(lsim_rejoin02, rjcount0) == expected::off_lsim_rejoin02__rjcount0, "lsim_rejoin02::rjcount0");
static_assert(sizeof(lsim_rejoin1) == expected::size_lsim_rejoin1, "lsim_rejoin1 : taille");
static_assert(offsetof(lsim_rejoin1, join_eui) == expected::off_lsim_rejoin1__join_eui, "lsim_rejoin1::join_eui");
static_assert(offsetof(lsim_rejoin1, dev_eui) == expected::off_lsim_rejoin1__dev_eui, "lsim_rejoin1::dev_eui");
static_assert(offsetof(lsim_rejoin1, rjcount1) == expected::off_lsim_rejoin1__rjcount1, "lsim_rejoin1::rjcount1");
static_assert(sizeof(lsim_mesh_radio) == expected::size_lsim_mesh_radio, "lsim_mesh_radio : taille");
static_assert(offsetof(lsim_mesh_radio, spreading_factor) == expected::off_lsim_mesh_radio__spreading_factor, "lsim_mesh_radio::spreading_factor");
static_assert(offsetof(lsim_mesh_radio, coding_rate) == expected::off_lsim_mesh_radio__coding_rate, "lsim_mesh_radio::coding_rate");
static_assert(offsetof(lsim_mesh_radio, bandwidth_hz) == expected::off_lsim_mesh_radio__bandwidth_hz, "lsim_mesh_radio::bandwidth_hz");
static_assert(offsetof(lsim_mesh_radio, payload_bytes) == expected::off_lsim_mesh_radio__payload_bytes, "lsim_mesh_radio::payload_bytes");
static_assert(offsetof(lsim_mesh_radio, preamble_symbols) == expected::off_lsim_mesh_radio__preamble_symbols, "lsim_mesh_radio::preamble_symbols");
static_assert(offsetof(lsim_mesh_radio, capture_db) == expected::off_lsim_mesh_radio__capture_db, "lsim_mesh_radio::capture_db");
static_assert(sizeof(lsim_mesh_frame) == expected::size_lsim_mesh_frame, "lsim_mesh_frame : taille");
static_assert(offsetof(lsim_mesh_frame, frame_id) == expected::off_lsim_mesh_frame__frame_id, "lsim_mesh_frame::frame_id");
static_assert(offsetof(lsim_mesh_frame, rx_node) == expected::off_lsim_mesh_frame__rx_node, "lsim_mesh_frame::rx_node");
static_assert(offsetof(lsim_mesh_frame, t_ns) == expected::off_lsim_mesh_frame__t_ns, "lsim_mesh_frame::t_ns");
static_assert(offsetof(lsim_mesh_frame, payload_bytes) == expected::off_lsim_mesh_frame__payload_bytes, "lsim_mesh_frame::payload_bytes");
static_assert(sizeof(lsim_mesh_delivery) == expected::size_lsim_mesh_delivery, "lsim_mesh_delivery : taille");
static_assert(offsetof(lsim_mesh_delivery, frame_id) == expected::off_lsim_mesh_delivery__frame_id, "lsim_mesh_delivery::frame_id");
static_assert(offsetof(lsim_mesh_delivery, delivered) == expected::off_lsim_mesh_delivery__delivered, "lsim_mesh_delivery::delivered");
static_assert(offsetof(lsim_mesh_delivery, loss) == expected::off_lsim_mesh_delivery__loss, "lsim_mesh_delivery::loss");
static_assert(offsetof(lsim_mesh_delivery, hops) == expected::off_lsim_mesh_delivery__hops, "lsim_mesh_delivery::hops");
static_assert(offsetof(lsim_mesh_delivery, copy_state) == expected::off_lsim_mesh_delivery__copy_state, "lsim_mesh_delivery::copy_state");
static_assert(offsetof(lsim_mesh_delivery, latency_ns) == expected::off_lsim_mesh_delivery__latency_ns, "lsim_mesh_delivery::latency_ns");
static_assert(sizeof(lsim_mesh_summary) == expected::size_lsim_mesh_summary, "lsim_mesh_summary : taille");
static_assert(offsetof(lsim_mesh_summary, transmissions) == expected::off_lsim_mesh_summary__transmissions, "lsim_mesh_summary::transmissions");
static_assert(offsetof(lsim_mesh_summary, suppressed) == expected::off_lsim_mesh_summary__suppressed, "lsim_mesh_summary::suppressed");
static_assert(offsetof(lsim_mesh_summary, lost_collision) == expected::off_lsim_mesh_summary__lost_collision, "lsim_mesh_summary::lost_collision");
static_assert(offsetof(lsim_mesh_summary, lost_half_duplex) == expected::off_lsim_mesh_summary__lost_half_duplex, "lsim_mesh_summary::lost_half_duplex");
static_assert(sizeof(lsim_mesh_hop) == expected::size_lsim_mesh_hop, "lsim_mesh_hop : taille");
static_assert(offsetof(lsim_mesh_hop, frame_id) == expected::off_lsim_mesh_hop__frame_id, "lsim_mesh_hop::frame_id");
static_assert(offsetof(lsim_mesh_hop, sender) == expected::off_lsim_mesh_hop__sender, "lsim_mesh_hop::sender");
static_assert(offsetof(lsim_mesh_hop, receiver) == expected::off_lsim_mesh_hop__receiver, "lsim_mesh_hop::receiver");
static_assert(offsetof(lsim_mesh_hop, t_start_ns) == expected::off_lsim_mesh_hop__t_start_ns, "lsim_mesh_hop::t_start_ns");
static_assert(offsetof(lsim_mesh_hop, t_end_ns) == expected::off_lsim_mesh_hop__t_end_ns, "lsim_mesh_hop::t_end_ns");
static_assert(offsetof(lsim_mesh_hop, outcome) == expected::off_lsim_mesh_hop__outcome, "lsim_mesh_hop::outcome");
static_assert(offsetof(lsim_mesh_hop, hop_index) == expected::off_lsim_mesh_hop__hop_index, "lsim_mesh_hop::hop_index");
static_assert(sizeof(lsim_plan_uplink) == expected::size_lsim_plan_uplink, "lsim_plan_uplink : taille");
static_assert(offsetof(lsim_plan_uplink, device_index) == expected::off_lsim_plan_uplink__device_index, "lsim_plan_uplink::device_index");
static_assert(offsetof(lsim_plan_uplink, start_ns) == expected::off_lsim_plan_uplink__start_ns, "lsim_plan_uplink::start_ns");
static_assert(offsetof(lsim_plan_uplink, end_ns) == expected::off_lsim_plan_uplink__end_ns, "lsim_plan_uplink::end_ns");
static_assert(offsetof(lsim_plan_uplink, spreading_factor) == expected::off_lsim_plan_uplink__spreading_factor, "lsim_plan_uplink::spreading_factor");
static_assert(offsetof(lsim_plan_uplink, outcome) == expected::off_lsim_plan_uplink__outcome, "lsim_plan_uplink::outcome");
static_assert(offsetof(lsim_plan_uplink, rssi_dbm) == expected::off_lsim_plan_uplink__rssi_dbm, "lsim_plan_uplink::rssi_dbm");
static_assert(sizeof(lsim_plan_device) == expected::size_lsim_plan_device, "lsim_plan_device : taille");
static_assert(offsetof(lsim_plan_device, freq_hz) == expected::off_lsim_plan_device__freq_hz, "lsim_plan_device::freq_hz");
static_assert(offsetof(lsim_plan_device, dr) == expected::off_lsim_plan_device__dr, "lsim_plan_device::dr");
static_assert(offsetof(lsim_plan_device, rx1_hz) == expected::off_lsim_plan_device__rx1_hz, "lsim_plan_device::rx1_hz");
static_assert(offsetof(lsim_plan_device, tx_power_dbm) == expected::off_lsim_plan_device__tx_power_dbm, "lsim_plan_device::tx_power_dbm");
static_assert(offsetof(lsim_plan_device, rx1_sf) == expected::off_lsim_plan_device__rx1_sf, "lsim_plan_device::rx1_sf");
static_assert(offsetof(lsim_plan_device, rx1_bw_hz) == expected::off_lsim_plan_device__rx1_bw_hz, "lsim_plan_device::rx1_bw_hz");
static_assert(sizeof(lsim_plan_options) == expected::size_lsim_plan_options, "lsim_plan_options : taille");
static_assert(offsetof(lsim_plan_options, confirmed_uplinks) == expected::off_lsim_plan_options__confirmed_uplinks, "lsim_plan_options::confirmed_uplinks");
static_assert(offsetof(lsim_plan_options, downlink_every) == expected::off_lsim_plan_options__downlink_every, "lsim_plan_options::downlink_every");
static_assert(offsetof(lsim_plan_options, downlink_payload_bytes) == expected::off_lsim_plan_options__downlink_payload_bytes, "lsim_plan_options::downlink_payload_bytes");
static_assert(offsetof(lsim_plan_options, gateway_tx_power_dbm) == expected::off_lsim_plan_options__gateway_tx_power_dbm, "lsim_plan_options::gateway_tx_power_dbm");
static_assert(offsetof(lsim_plan_options, device_antenna_gain_dbi) == expected::off_lsim_plan_options__device_antenna_gain_dbi, "lsim_plan_options::device_antenna_gain_dbi");
static_assert(offsetof(lsim_plan_options, device_rx_offset_db) == expected::off_lsim_plan_options__device_rx_offset_db, "lsim_plan_options::device_rx_offset_db");
static_assert(sizeof(lsim_plan_hop) == expected::size_lsim_plan_hop, "lsim_plan_hop : taille");
static_assert(offsetof(lsim_plan_hop, dir) == expected::off_lsim_plan_hop__dir, "lsim_plan_hop::dir");
static_assert(offsetof(lsim_plan_hop, outcome) == expected::off_lsim_plan_hop__outcome, "lsim_plan_hop::outcome");
static_assert(offsetof(lsim_plan_hop, has_rssi) == expected::off_lsim_plan_hop__has_rssi, "lsim_plan_hop::has_rssi");
static_assert(offsetof(lsim_plan_hop, t_ns) == expected::off_lsim_plan_hop__t_ns, "lsim_plan_hop::t_ns");
static_assert(offsetof(lsim_plan_hop, freq_hz) == expected::off_lsim_plan_hop__freq_hz, "lsim_plan_hop::freq_hz");
static_assert(offsetof(lsim_plan_hop, dr) == expected::off_lsim_plan_hop__dr, "lsim_plan_hop::dr");
static_assert(offsetof(lsim_plan_hop, rssi_dbm) == expected::off_lsim_plan_hop__rssi_dbm, "lsim_plan_hop::rssi_dbm");
static_assert(sizeof(lsim_plan_event) == expected::size_lsim_plan_event, "lsim_plan_event : taille");
static_assert(offsetof(lsim_plan_event, t_ns) == expected::off_lsim_plan_event__t_ns, "lsim_plan_event::t_ns");
static_assert(offsetof(lsim_plan_event, device_index) == expected::off_lsim_plan_event__device_index, "lsim_plan_event::device_index");
static_assert(offsetof(lsim_plan_event, kind) == expected::off_lsim_plan_event__kind, "lsim_plan_event::kind");
static_assert(offsetof(lsim_plan_event, outcome) == expected::off_lsim_plan_event__outcome, "lsim_plan_event::outcome");
static_assert(offsetof(lsim_plan_event, hop_count) == expected::off_lsim_plan_event__hop_count, "lsim_plan_event::hop_count");
static_assert(offsetof(lsim_plan_event, hops) == expected::off_lsim_plan_event__hops, "lsim_plan_event::hops");
static_assert(sizeof(lsim_loop_region) == expected::size_lsim_loop_region, "lsim_loop_region : taille");
static_assert(offsetof(lsim_loop_region, dr_sf) == expected::off_lsim_loop_region__dr_sf, "lsim_loop_region::dr_sf");
static_assert(offsetof(lsim_loop_region, max_dr) == expected::off_lsim_loop_region__max_dr, "lsim_loop_region::max_dr");
static_assert(offsetof(lsim_loop_region, max_tx_power_index) == expected::off_lsim_loop_region__max_tx_power_index, "lsim_loop_region::max_tx_power_index");
static_assert(offsetof(lsim_loop_region, power_step_tenth_db) == expected::off_lsim_loop_region__power_step_tenth_db, "lsim_loop_region::power_step_tenth_db");
static_assert(offsetof(lsim_loop_region, max_eirp_dbm) == expected::off_lsim_loop_region__max_eirp_dbm, "lsim_loop_region::max_eirp_dbm");
static_assert(offsetof(lsim_loop_region, duty_limit) == expected::off_lsim_loop_region__duty_limit, "lsim_loop_region::duty_limit");
static_assert(sizeof(lsim_loop_options) == expected::size_lsim_loop_options, "lsim_loop_options : taille");
static_assert(offsetof(lsim_loop_options, protocol) == expected::off_lsim_loop_options__protocol, "lsim_loop_options::protocol");
static_assert(offsetof(lsim_loop_options, adr) == expected::off_lsim_loop_options__adr, "lsim_loop_options::adr");
static_assert(offsetof(lsim_loop_options, installation_margin_tenth_db) == expected::off_lsim_loop_options__installation_margin_tenth_db, "lsim_loop_options::installation_margin_tenth_db");
static_assert(offsetof(lsim_loop_options, duty_cycle) == expected::off_lsim_loop_options__duty_cycle, "lsim_loop_options::duty_cycle");
static_assert(offsetof(lsim_loop_options, duty_cycle_exponent) == expected::off_lsim_loop_options__duty_cycle_exponent, "lsim_loop_options::duty_cycle_exponent");
static_assert(sizeof(lsim_loop_mac) == expected::size_lsim_loop_mac, "lsim_loop_mac : taille");
static_assert(offsetof(lsim_loop_mac, device_index) == expected::off_lsim_loop_mac__device_index, "lsim_loop_mac::device_index");
static_assert(offsetof(lsim_loop_mac, rank) == expected::off_lsim_loop_mac__rank, "lsim_loop_mac::rank");
static_assert(offsetof(lsim_loop_mac, extra_bytes) == expected::off_lsim_loop_mac__extra_bytes, "lsim_loop_mac::extra_bytes");
static_assert(offsetof(lsim_loop_mac, flags) == expected::off_lsim_loop_mac__flags, "lsim_loop_mac::flags");
static_assert(sizeof(lsim_loop_mac_counters) == expected::size_lsim_loop_mac_counters, "lsim_loop_mac_counters : taille");
static_assert(offsetof(lsim_loop_mac_counters, enqueued) == expected::off_lsim_loop_mac_counters__enqueued, "lsim_loop_mac_counters::enqueued");
static_assert(offsetof(lsim_loop_mac_counters, dispatched) == expected::off_lsim_loop_mac_counters__dispatched, "lsim_loop_mac_counters::dispatched");
static_assert(offsetof(lsim_loop_mac_counters, delivered) == expected::off_lsim_loop_mac_counters__delivered, "lsim_loop_mac_counters::delivered");
static_assert(offsetof(lsim_loop_mac_counters, dispatch_lost) == expected::off_lsim_loop_mac_counters__dispatch_lost, "lsim_loop_mac_counters::dispatch_lost");
static_assert(offsetof(lsim_loop_mac_counters, deferred) == expected::off_lsim_loop_mac_counters__deferred, "lsim_loop_mac_counters::deferred");
static_assert(offsetof(lsim_loop_mac_counters, expired) == expected::off_lsim_loop_mac_counters__expired, "lsim_loop_mac_counters::expired");
static_assert(offsetof(lsim_loop_mac_counters, pending_at_end) == expected::off_lsim_loop_mac_counters__pending_at_end, "lsim_loop_mac_counters::pending_at_end");
static_assert(sizeof(lsim_loop_uplink) == expected::size_lsim_loop_uplink, "lsim_loop_uplink : taille");
static_assert(offsetof(lsim_loop_uplink, device_index) == expected::off_lsim_loop_uplink__device_index, "lsim_loop_uplink::device_index");
static_assert(offsetof(lsim_loop_uplink, start_ns) == expected::off_lsim_loop_uplink__start_ns, "lsim_loop_uplink::start_ns");
static_assert(offsetof(lsim_loop_uplink, end_ns) == expected::off_lsim_loop_uplink__end_ns, "lsim_loop_uplink::end_ns");
static_assert(offsetof(lsim_loop_uplink, spreading_factor) == expected::off_lsim_loop_uplink__spreading_factor, "lsim_loop_uplink::spreading_factor");
static_assert(offsetof(lsim_loop_uplink, dr) == expected::off_lsim_loop_uplink__dr, "lsim_loop_uplink::dr");
static_assert(offsetof(lsim_loop_uplink, power_index) == expected::off_lsim_loop_uplink__power_index, "lsim_loop_uplink::power_index");
static_assert(offsetof(lsim_loop_uplink, rssi_dbm) == expected::off_lsim_loop_uplink__rssi_dbm, "lsim_loop_uplink::rssi_dbm");
static_assert(offsetof(lsim_loop_uplink, outcome) == expected::off_lsim_loop_uplink__outcome, "lsim_loop_uplink::outcome");
static_assert(offsetof(lsim_loop_uplink, answer_mask) == expected::off_lsim_loop_uplink__answer_mask, "lsim_loop_uplink::answer_mask");
static_assert(offsetof(lsim_loop_uplink, answer_ok) == expected::off_lsim_loop_uplink__answer_ok, "lsim_loop_uplink::answer_ok");
static_assert(sizeof(lsim_loop_downlink) == expected::size_lsim_loop_downlink, "lsim_loop_downlink : taille");
static_assert(offsetof(lsim_loop_downlink, uplink_index) == expected::off_lsim_loop_downlink__uplink_index, "lsim_loop_downlink::uplink_index");
static_assert(offsetof(lsim_loop_downlink, device_index) == expected::off_lsim_loop_downlink__device_index, "lsim_loop_downlink::device_index");
static_assert(offsetof(lsim_loop_downlink, kind) == expected::off_lsim_loop_downlink__kind, "lsim_loop_downlink::kind");
static_assert(offsetof(lsim_loop_downlink, commands) == expected::off_lsim_loop_downlink__commands, "lsim_loop_downlink::commands");
static_assert(offsetof(lsim_loop_downlink, t_open_ns) == expected::off_lsim_loop_downlink__t_open_ns, "lsim_loop_downlink::t_open_ns");
static_assert(offsetof(lsim_loop_downlink, start_ns) == expected::off_lsim_loop_downlink__start_ns, "lsim_loop_downlink::start_ns");
static_assert(offsetof(lsim_loop_downlink, air_ns) == expected::off_lsim_loop_downlink__air_ns, "lsim_loop_downlink::air_ns");
static_assert(offsetof(lsim_loop_downlink, device_missed) == expected::off_lsim_loop_downlink__device_missed, "lsim_loop_downlink::device_missed");
static_assert(offsetof(lsim_loop_downlink, delivered) == expected::off_lsim_loop_downlink__delivered, "lsim_loop_downlink::delivered");
static_assert(offsetof(lsim_loop_downlink, req_dr) == expected::off_lsim_loop_downlink__req_dr, "lsim_loop_downlink::req_dr");
static_assert(offsetof(lsim_loop_downlink, req_power_index) == expected::off_lsim_loop_downlink__req_power_index, "lsim_loop_downlink::req_power_index");
static_assert(sizeof(lsim_channel_device_v3) == expected::size_lsim_channel_device_v3, "lsim_channel_device_v3 : taille");
static_assert(offsetof(lsim_channel_device_v3, struct_size) == expected::off_lsim_channel_device_v3__struct_size, "lsim_channel_device_v3::struct_size");
static_assert(offsetof(lsim_channel_device_v3, abi_version) == expected::off_lsim_channel_device_v3__abi_version, "lsim_channel_device_v3::abi_version");
static_assert(offsetof(lsim_channel_device_v3, device_index) == expected::off_lsim_channel_device_v3__device_index, "lsim_channel_device_v3::device_index");
static_assert(offsetof(lsim_channel_device_v3, present) == expected::off_lsim_channel_device_v3__present, "lsim_channel_device_v3::present");
static_assert(offsetof(lsim_channel_device_v3, dr_mask) == expected::off_lsim_channel_device_v3__dr_mask, "lsim_channel_device_v3::dr_mask");
static_assert(offsetof(lsim_channel_device_v3, enabled) == expected::off_lsim_channel_device_v3__enabled, "lsim_channel_device_v3::enabled");
static_assert(offsetof(lsim_channel_device_v3, server_defined) == expected::off_lsim_channel_device_v3__server_defined, "lsim_channel_device_v3::server_defined");
static_assert(offsetof(lsim_channel_device_v3, reserved) == expected::off_lsim_channel_device_v3__reserved, "lsim_channel_device_v3::reserved");
static_assert(sizeof(lsim_channel_terminal_v3) == expected::size_lsim_channel_terminal_v3, "lsim_channel_terminal_v3 : taille");
static_assert(offsetof(lsim_channel_terminal_v3, struct_size) == expected::off_lsim_channel_terminal_v3__struct_size, "lsim_channel_terminal_v3::struct_size");
static_assert(offsetof(lsim_channel_terminal_v3, abi_version) == expected::off_lsim_channel_terminal_v3__abi_version, "lsim_channel_terminal_v3::abi_version");
static_assert(offsetof(lsim_channel_terminal_v3, device_index) == expected::off_lsim_channel_terminal_v3__device_index, "lsim_channel_terminal_v3::device_index");
static_assert(offsetof(lsim_channel_terminal_v3, dr) == expected::off_lsim_channel_terminal_v3__dr, "lsim_channel_terminal_v3::dr");
static_assert(offsetof(lsim_channel_terminal_v3, power_index) == expected::off_lsim_channel_terminal_v3__power_index, "lsim_channel_terminal_v3::power_index");
static_assert(offsetof(lsim_channel_terminal_v3, reserved0) == expected::off_lsim_channel_terminal_v3__reserved0, "lsim_channel_terminal_v3::reserved0");
static_assert(offsetof(lsim_channel_terminal_v3, dr_mask) == expected::off_lsim_channel_terminal_v3__dr_mask, "lsim_channel_terminal_v3::dr_mask");
static_assert(offsetof(lsim_channel_terminal_v3, enabled) == expected::off_lsim_channel_terminal_v3__enabled, "lsim_channel_terminal_v3::enabled");
static_assert(offsetof(lsim_channel_terminal_v3, reserved1) == expected::off_lsim_channel_terminal_v3__reserved1, "lsim_channel_terminal_v3::reserved1");
static_assert(sizeof(lsim_loop_trace_v3) == expected::size_lsim_loop_trace_v3, "lsim_loop_trace_v3 : taille");
static_assert(offsetof(lsim_loop_trace_v3, t_ns) == expected::off_lsim_loop_trace_v3__t_ns, "lsim_loop_trace_v3::t_ns");
static_assert(offsetof(lsim_loop_trace_v3, device) == expected::off_lsim_loop_trace_v3__device, "lsim_loop_trace_v3::device");
static_assert(offsetof(lsim_loop_trace_v3, uplink) == expected::off_lsim_loop_trace_v3__uplink, "lsim_loop_trace_v3::uplink");
static_assert(offsetof(lsim_loop_trace_v3, downlink) == expected::off_lsim_loop_trace_v3__downlink, "lsim_loop_trace_v3::downlink");
static_assert(offsetof(lsim_loop_trace_v3, kind) == expected::off_lsim_loop_trace_v3__kind, "lsim_loop_trace_v3::kind");
static_assert(offsetof(lsim_loop_trace_v3, origin) == expected::off_lsim_loop_trace_v3__origin, "lsim_loop_trace_v3::origin");
static_assert(offsetof(lsim_loop_trace_v3, action) == expected::off_lsim_loop_trace_v3__action, "lsim_loop_trace_v3::action");
static_assert(offsetof(lsim_loop_trace_v3, target) == expected::off_lsim_loop_trace_v3__target, "lsim_loop_trace_v3::target");
static_assert(offsetof(lsim_loop_trace_v3, loss) == expected::off_lsim_loop_trace_v3__loss, "lsim_loop_trace_v3::loss");
static_assert(offsetof(lsim_loop_trace_v3, status) == expected::off_lsim_loop_trace_v3__status, "lsim_loop_trace_v3::status");
static_assert(offsetof(lsim_loop_trace_v3, dr) == expected::off_lsim_loop_trace_v3__dr, "lsim_loop_trace_v3::dr");
static_assert(offsetof(lsim_loop_trace_v3, power_index) == expected::off_lsim_loop_trace_v3__power_index, "lsim_loop_trace_v3::power_index");
static_assert(offsetof(lsim_loop_trace_v3, channel_mask) == expected::off_lsim_loop_trace_v3__channel_mask, "lsim_loop_trace_v3::channel_mask");
static_assert(offsetof(lsim_loop_trace_v3, value) == expected::off_lsim_loop_trace_v3__value, "lsim_loop_trace_v3::value");
static_assert(offsetof(lsim_loop_trace_v3, flag) == expected::off_lsim_loop_trace_v3__flag, "lsim_loop_trace_v3::flag");
static_assert(offsetof(lsim_loop_trace_v3, reason_channel) == expected::off_lsim_loop_trace_v3__reason_channel, "lsim_loop_trace_v3::reason_channel");
static_assert(offsetof(lsim_loop_trace_v3, reason_dr) == expected::off_lsim_loop_trace_v3__reason_dr, "lsim_loop_trace_v3::reason_dr");
static_assert(offsetof(lsim_loop_trace_v3, reason_power) == expected::off_lsim_loop_trace_v3__reason_power, "lsim_loop_trace_v3::reason_power");
static_assert(offsetof(lsim_loop_trace_v3, reserved) == expected::off_lsim_loop_trace_v3__reserved, "lsim_loop_trace_v3::reserved");
static_assert(sizeof(lsim_closed_loop_v3_args) == expected::size_lsim_closed_loop_v3_args, "lsim_closed_loop_v3_args : taille");
static_assert(offsetof(lsim_closed_loop_v3_args, struct_size) == expected::off_lsim_closed_loop_v3_args__struct_size, "lsim_closed_loop_v3_args::struct_size");
static_assert(offsetof(lsim_closed_loop_v3_args, abi_version) == expected::off_lsim_closed_loop_v3_args__abi_version, "lsim_closed_loop_v3_args::abi_version");
static_assert(offsetof(lsim_closed_loop_v3_args, channel_plan) == expected::off_lsim_closed_loop_v3_args__channel_plan, "lsim_closed_loop_v3_args::channel_plan");
static_assert(offsetof(lsim_closed_loop_v3_args, trace_enabled) == expected::off_lsim_closed_loop_v3_args__trace_enabled, "lsim_closed_loop_v3_args::trace_enabled");
static_assert(offsetof(lsim_closed_loop_v3_args, trace_element_size) == expected::off_lsim_closed_loop_v3_args__trace_element_size, "lsim_closed_loop_v3_args::trace_element_size");
static_assert(offsetof(lsim_closed_loop_v3_args, terminal_element_size) == expected::off_lsim_closed_loop_v3_args__terminal_element_size, "lsim_closed_loop_v3_args::terminal_element_size");
static_assert(offsetof(lsim_closed_loop_v3_args, reserved0) == expected::off_lsim_closed_loop_v3_args__reserved0, "lsim_closed_loop_v3_args::reserved0");
static_assert(offsetof(lsim_closed_loop_v3_args, reserved1) == expected::off_lsim_closed_loop_v3_args__reserved1, "lsim_closed_loop_v3_args::reserved1");
static_assert(offsetof(lsim_closed_loop_v3_args, devices) == expected::off_lsim_closed_loop_v3_args__devices, "lsim_closed_loop_v3_args::devices");
static_assert(offsetof(lsim_closed_loop_v3_args, device_count) == expected::off_lsim_closed_loop_v3_args__device_count, "lsim_closed_loop_v3_args::device_count");
static_assert(offsetof(lsim_closed_loop_v3_args, radios) == expected::off_lsim_closed_loop_v3_args__radios, "lsim_closed_loop_v3_args::radios");
static_assert(offsetof(lsim_closed_loop_v3_args, regions) == expected::off_lsim_closed_loop_v3_args__regions, "lsim_closed_loop_v3_args::regions");
static_assert(offsetof(lsim_closed_loop_v3_args, gateway) == expected::off_lsim_closed_loop_v3_args__gateway, "lsim_closed_loop_v3_args::gateway");
static_assert(offsetof(lsim_closed_loop_v3_args, prop) == expected::off_lsim_closed_loop_v3_args__prop, "lsim_closed_loop_v3_args::prop");
static_assert(offsetof(lsim_closed_loop_v3_args, env) == expected::off_lsim_closed_loop_v3_args__env, "lsim_closed_loop_v3_args::env");
static_assert(offsetof(lsim_closed_loop_v3_args, options) == expected::off_lsim_closed_loop_v3_args__options, "lsim_closed_loop_v3_args::options");
static_assert(offsetof(lsim_closed_loop_v3_args, mac) == expected::off_lsim_closed_loop_v3_args__mac, "lsim_closed_loop_v3_args::mac");
static_assert(offsetof(lsim_closed_loop_v3_args, mac_count) == expected::off_lsim_closed_loop_v3_args__mac_count, "lsim_closed_loop_v3_args::mac_count");
static_assert(offsetof(lsim_closed_loop_v3_args, channels) == expected::off_lsim_closed_loop_v3_args__channels, "lsim_closed_loop_v3_args::channels");
static_assert(offsetof(lsim_closed_loop_v3_args, channel_count) == expected::off_lsim_closed_loop_v3_args__channel_count, "lsim_closed_loop_v3_args::channel_count");
static_assert(offsetof(lsim_closed_loop_v3_args, per_device) == expected::off_lsim_closed_loop_v3_args__per_device, "lsim_closed_loop_v3_args::per_device");
static_assert(offsetof(lsim_closed_loop_v3_args, totals) == expected::off_lsim_closed_loop_v3_args__totals, "lsim_closed_loop_v3_args::totals");
static_assert(offsetof(lsim_closed_loop_v3_args, uplinks) == expected::off_lsim_closed_loop_v3_args__uplinks, "lsim_closed_loop_v3_args::uplinks");
static_assert(offsetof(lsim_closed_loop_v3_args, uplink_capacity) == expected::off_lsim_closed_loop_v3_args__uplink_capacity, "lsim_closed_loop_v3_args::uplink_capacity");
static_assert(offsetof(lsim_closed_loop_v3_args, uplink_count) == expected::off_lsim_closed_loop_v3_args__uplink_count, "lsim_closed_loop_v3_args::uplink_count");
static_assert(offsetof(lsim_closed_loop_v3_args, downlinks) == expected::off_lsim_closed_loop_v3_args__downlinks, "lsim_closed_loop_v3_args::downlinks");
static_assert(offsetof(lsim_closed_loop_v3_args, downlink_capacity) == expected::off_lsim_closed_loop_v3_args__downlink_capacity, "lsim_closed_loop_v3_args::downlink_capacity");
static_assert(offsetof(lsim_closed_loop_v3_args, downlink_count) == expected::off_lsim_closed_loop_v3_args__downlink_count, "lsim_closed_loop_v3_args::downlink_count");
static_assert(offsetof(lsim_closed_loop_v3_args, busy) == expected::off_lsim_closed_loop_v3_args__busy, "lsim_closed_loop_v3_args::busy");
static_assert(offsetof(lsim_closed_loop_v3_args, busy_capacity) == expected::off_lsim_closed_loop_v3_args__busy_capacity, "lsim_closed_loop_v3_args::busy_capacity");
static_assert(offsetof(lsim_closed_loop_v3_args, busy_count) == expected::off_lsim_closed_loop_v3_args__busy_count, "lsim_closed_loop_v3_args::busy_count");
static_assert(offsetof(lsim_closed_loop_v3_args, mac_counters) == expected::off_lsim_closed_loop_v3_args__mac_counters, "lsim_closed_loop_v3_args::mac_counters");
static_assert(offsetof(lsim_closed_loop_v3_args, trace) == expected::off_lsim_closed_loop_v3_args__trace, "lsim_closed_loop_v3_args::trace");
static_assert(offsetof(lsim_closed_loop_v3_args, trace_capacity) == expected::off_lsim_closed_loop_v3_args__trace_capacity, "lsim_closed_loop_v3_args::trace_capacity");
static_assert(offsetof(lsim_closed_loop_v3_args, trace_count) == expected::off_lsim_closed_loop_v3_args__trace_count, "lsim_closed_loop_v3_args::trace_count");
static_assert(offsetof(lsim_closed_loop_v3_args, terminals) == expected::off_lsim_closed_loop_v3_args__terminals, "lsim_closed_loop_v3_args::terminals");
static_assert(offsetof(lsim_closed_loop_v3_args, terminal_capacity) == expected::off_lsim_closed_loop_v3_args__terminal_capacity, "lsim_closed_loop_v3_args::terminal_capacity");
static_assert(offsetof(lsim_closed_loop_v3_args, terminal_count) == expected::off_lsim_closed_loop_v3_args__terminal_count, "lsim_closed_loop_v3_args::terminal_count");
static_assert(sizeof(lsim_device_rf) == expected::size_lsim_device_rf, "lsim_device_rf : taille");
static_assert(offsetof(lsim_device_rf, present) == expected::off_lsim_device_rf__present, "lsim_device_rf::present");
static_assert(offsetof(lsim_device_rf, antenna_gain_dbi) == expected::off_lsim_device_rf__antenna_gain_dbi, "lsim_device_rf::antenna_gain_dbi");
static_assert(offsetof(lsim_device_rf, cable_loss_db) == expected::off_lsim_device_rf__cable_loss_db, "lsim_device_rf::cable_loss_db");
static_assert(sizeof(lsim_gateway_rf) == expected::size_lsim_gateway_rf, "lsim_gateway_rf : taille");
static_assert(offsetof(lsim_gateway_rf, present) == expected::off_lsim_gateway_rf__present, "lsim_gateway_rf::present");
static_assert(offsetof(lsim_gateway_rf, antenna_gain_dbi) == expected::off_lsim_gateway_rf__antenna_gain_dbi, "lsim_gateway_rf::antenna_gain_dbi");
static_assert(offsetof(lsim_gateway_rf, cable_loss_db) == expected::off_lsim_gateway_rf__cable_loss_db, "lsim_gateway_rf::cable_loss_db");
static_assert(sizeof(lsim_closed_loop_v4_args) == expected::size_lsim_closed_loop_v4_args, "lsim_closed_loop_v4_args : taille");
static_assert(offsetof(lsim_closed_loop_v4_args, struct_size) == expected::off_lsim_closed_loop_v4_args__struct_size, "lsim_closed_loop_v4_args::struct_size");
static_assert(offsetof(lsim_closed_loop_v4_args, abi_version) == expected::off_lsim_closed_loop_v4_args__abi_version, "lsim_closed_loop_v4_args::abi_version");
static_assert(offsetof(lsim_closed_loop_v4_args, v3) == expected::off_lsim_closed_loop_v4_args__v3, "lsim_closed_loop_v4_args::v3");
static_assert(offsetof(lsim_closed_loop_v4_args, device_rf) == expected::off_lsim_closed_loop_v4_args__device_rf, "lsim_closed_loop_v4_args::device_rf");
static_assert(offsetof(lsim_closed_loop_v4_args, device_rf_count) == expected::off_lsim_closed_loop_v4_args__device_rf_count, "lsim_closed_loop_v4_args::device_rf_count");
static_assert(offsetof(lsim_closed_loop_v4_args, gateway_rf) == expected::off_lsim_closed_loop_v4_args__gateway_rf, "lsim_closed_loop_v4_args::gateway_rf");
static_assert(offsetof(lsim_closed_loop_v4_args, reserved) == expected::off_lsim_closed_loop_v4_args__reserved, "lsim_closed_loop_v4_args::reserved");

// Vérification à l'exécution (possible seulement si un binaire de cette ABI peut être lié).
inline int run() {
#if defined(ABI_LAYOUT_STANDALONE)
    // Les static_assert ci-dessus ont déjà tout vérifié à la compilation ; ici on ne fait
    // qu'exposer le résultat pour le harnais 64 bits, qui est le seul liable dans la sandbox.
#endif
    return 0;
}

}  // namespace abi_layout

#if defined(ABI_LAYOUT_STANDALONE)
#include <stdio.h>
int main() {
    printf("ABI %s : pointeur %zu octets, alignement max %zu\n", abi_layout::kAbiName,
                abi_layout::kPointerSize, abi_layout::kMaxAlign);
    printf("structures vérifiées : 53, grandeurs : 454\n");
    return abi_layout::run();
}
#endif

#endif  // LSIM_ABI_LAYOUT_CPP
