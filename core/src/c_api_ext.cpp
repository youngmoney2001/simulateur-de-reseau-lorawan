// SPDX-License-Identifier: Apache-2.0
// Fonctions C de la crypto 1.1, de la trame sécurisée et du simulateur.
// Chaque fonction intercepte les exceptions : aucune ne traverse la frontière C.
#include <array>
#include <cstring>
#include <vector>

#include "lsim/c_api.h"
#include "lsim/engine.hpp"
#include "lsim/environment.hpp"
#include "lsim/join.hpp"
#include "lsim/lorawan_keys.hpp"
#include "lsim/secure_frame.hpp"

namespace {

using lsim::crypto::Key128;
using lsim::lorawan::DataFrame;
using lsim::lorawan::MType;
using lsim::lorawan::SessionKeys11;

void copy_key(const std::uint8_t* src, std::uint8_t* dst) {
    std::memcpy(dst, src, 16);
}

void load_keys(const lsim_session_keys_11& in, SessionKeys11& out) {
    std::memcpy(out.f_nwk_s_int_key.data(), in.f_nwk_s_int_key, 16);
    std::memcpy(out.s_nwk_s_int_key.data(), in.s_nwk_s_int_key, 16);
    std::memcpy(out.nwk_s_enc_key.data(), in.nwk_s_enc_key, 16);
    std::memcpy(out.app_s_key.data(), in.app_s_key, 16);
}

void store_keys(const SessionKeys11& in, lsim_session_keys_11& out) {
    std::memcpy(out.f_nwk_s_int_key, in.f_nwk_s_int_key.data(), 16);
    std::memcpy(out.s_nwk_s_int_key, in.s_nwk_s_int_key.data(), 16);
    std::memcpy(out.nwk_s_enc_key, in.nwk_s_enc_key.data(), 16);
    std::memcpy(out.app_s_key, in.app_s_key.data(), 16);
}

// 0 = succès, dans tous les domaines ; les plages ne servent qu'aux erreurs.
std::int32_t map_secure(lsim::lorawan::SecureStatus s) {
    if (s == lsim::lorawan::SecureStatus::Ok) {
        return 0;
    }
    return LSIM_STATUS_SECURE_BASE + static_cast<std::int32_t>(s);
}

lsim::lorawan::UplinkContext to_ctx(const lsim_uplink_context& c) {
    lsim::lorawan::UplinkContext u;
    u.conf_fcnt = c.conf_fcnt;
    u.tx_dr = c.tx_dr;
    u.tx_ch = c.tx_ch;
    u.fcnt32 = c.fcnt32;
    return u;
}

void to_frame(const lsim_uplink_frame& in, DataFrame& out) {
    out = DataFrame{};
    out.mtype = static_cast<MType>(in.mtype);
    out.dev_addr = in.dev_addr;
    out.adr = in.adr != 0;
    out.adr_ack_req = in.adr_ack_req != 0;
    out.ack = in.ack != 0;
    out.class_b = in.class_b != 0;
    out.fcnt = in.fcnt;
    out.has_fport = in.has_fport != 0;
    out.fport = in.fport;
    out.frm_payload_len = in.payload_len;
    std::memcpy(out.frm_payload.data(), in.payload, in.payload_len);
    // FOpts : bornés par l'appelant (voir lsim_seal_uplink).
    out.fopts_len = in.fopts_len;
    std::memcpy(out.fopts.data(), in.fopts, in.fopts_len);
}

void from_frame(const DataFrame& in, lsim_uplink_frame& out) {
    std::memset(&out, 0, sizeof out);
    out.dev_addr = in.dev_addr;
    out.mtype = static_cast<std::uint8_t>(in.mtype);
    out.adr = in.adr ? 1 : 0;
    out.adr_ack_req = in.adr_ack_req ? 1 : 0;
    out.ack = in.ack ? 1 : 0;
    out.class_b = in.class_b ? 1 : 0;
    out.fcnt = in.fcnt;
    out.has_fport = in.has_fport ? 1 : 0;
    out.fport = in.fport;
    out.payload_len = in.frm_payload_len;
    std::memcpy(out.payload, in.frm_payload.data(), in.frm_payload_len);
    out.fopts_len = in.fopts_len;
    std::memcpy(out.fopts, in.fopts.data(), in.fopts_len);
    std::memcpy(out.mic, in.mic.data(), 4);
}

std::int32_t map_join(lsim::lorawan::JoinStatus s) {
    if (s == lsim::lorawan::JoinStatus::Ok) {
        return 0;
    }
    return LSIM_STATUS_JOIN_BASE + static_cast<std::int32_t>(s);
}

std::array<std::uint8_t, 8> arr8(const std::uint8_t* p) {
    std::array<std::uint8_t, 8> a;
    std::memcpy(a.data(), p, 8);
    return a;
}

std::array<std::uint8_t, 2> arr2(const std::uint8_t* p) {
    std::array<std::uint8_t, 2> a;
    std::memcpy(a.data(), p, 2);
    return a;
}

lsim::lorawan::JoinAcceptFields to_accept(const lsim_join_accept& in) {
    lsim::lorawan::JoinAcceptFields f;
    std::memcpy(f.join_nonce.data(), in.join_nonce, 3);
    std::memcpy(f.net_id.data(), in.net_id, 3);
    f.dev_addr = in.dev_addr;
    f.dl_settings = in.dl_settings;
    f.rx_delay = in.rx_delay;
    f.has_cflist = in.has_cflist != 0;
    std::memcpy(f.cflist.data(), in.cflist, 16);
    return f;
}

void from_accept(const lsim::lorawan::JoinAcceptFields& f, lsim_join_accept& out) {
    std::memset(&out, 0, sizeof out);
    std::memcpy(out.join_nonce, f.join_nonce.data(), 3);
    std::memcpy(out.net_id, f.net_id.data(), 3);
    out.dev_addr = f.dev_addr;
    out.dl_settings = f.dl_settings;
    out.rx_delay = f.rx_delay;
    out.has_cflist = f.has_cflist ? 1 : 0;
    std::memcpy(out.cflist, f.cflist.data(), 16);
}

}  // namespace

extern "C" {

int32_t lsim_derive_join_keys(const uint8_t nwk_key[16], const uint8_t dev_eui[8],
                              lsim_join_keys* out) {
    if (nwk_key == nullptr || dev_eui == nullptr || out == nullptr) {
        return static_cast<int32_t>(lsim::lora::Status::NullOutput);
    }
    try {
        Key128 nk;
        std::memcpy(nk.data(), nwk_key, 16);
        std::array<std::uint8_t, 8> eui;
        std::memcpy(eui.data(), dev_eui, 8);
        lsim::lorawan::JoinKeys jk;
        const auto st = lsim::lorawan::derive_join_keys(nk, eui, jk);
        if (st != lsim::crypto::CryptoStatus::Ok) {
            return LSIM_STATUS_CRYPTO_BASE + static_cast<int32_t>(st);
        }
        copy_key(jk.js_enc_key.data(), out->js_enc_key);
        copy_key(jk.js_int_key.data(), out->js_int_key);
        return 0;
    } catch (...) {
        return LSIM_STATUS_INTERNAL;
    }
}

int32_t lsim_derive_session_keys_11(const uint8_t nwk_key[16], const uint8_t app_key[16],
                                    const uint8_t join_nonce[3], const uint8_t join_eui[8],
                                    const uint8_t dev_nonce[2], lsim_session_keys_11* out) {
    if (nwk_key == nullptr || app_key == nullptr || join_nonce == nullptr ||
        join_eui == nullptr || dev_nonce == nullptr || out == nullptr) {
        return static_cast<int32_t>(lsim::lora::Status::NullOutput);
    }
    try {
        Key128 nk, ak;
        std::memcpy(nk.data(), nwk_key, 16);
        std::memcpy(ak.data(), app_key, 16);
        std::array<std::uint8_t, 3> jn;
        std::memcpy(jn.data(), join_nonce, 3);
        std::array<std::uint8_t, 8> je;
        std::memcpy(je.data(), join_eui, 8);
        std::array<std::uint8_t, 2> dn;
        std::memcpy(dn.data(), dev_nonce, 2);
        SessionKeys11 k;
        const auto st = lsim::lorawan::derive_session_keys_11(nk, ak, jn, je, dn, k);
        if (st != lsim::crypto::CryptoStatus::Ok) {
            return LSIM_STATUS_CRYPTO_BASE + static_cast<int32_t>(st);
        }
        store_keys(k, *out);
        return 0;
    } catch (...) {
        return LSIM_STATUS_INTERNAL;
    }
}

int32_t lsim_seal_uplink(const lsim_uplink_frame* frame, const lsim_session_keys_11* keys,
                         const lsim_uplink_context* ctx, uint8_t* out, size_t cap,
                         size_t* out_written) {
    if (frame == nullptr || keys == nullptr || ctx == nullptr || out == nullptr ||
        out_written == nullptr) {
        return static_cast<int32_t>(lsim::lora::Status::NullOutput);
    }
    *out_written = 0;
    if (frame->payload_len > lsim::lorawan::kMaxFrmPayload || frame->fopts_len > 15) {
        return map_secure(lsim::lorawan::SecureStatus::InvalidPayload);
    }
    try {
        DataFrame f;
        to_frame(*frame, f);
        SessionKeys11 k;
        load_keys(*keys, k);
        const auto st = lsim::lorawan::seal_uplink(f, k, to_ctx(*ctx), out, cap, *out_written);
        if (st != lsim::lorawan::SecureStatus::Ok) {
            *out_written = 0;
        }
        return map_secure(st);
    } catch (...) {
        *out_written = 0;
        return LSIM_STATUS_INTERNAL;
    }
}

int32_t lsim_open_uplink(const uint8_t* in, size_t len, const lsim_session_keys_11* keys,
                         const lsim_uplink_context* ctx, lsim_uplink_frame* out) {
    if (in == nullptr || keys == nullptr || ctx == nullptr || out == nullptr) {
        return static_cast<int32_t>(lsim::lora::Status::NullOutput);
    }
    std::memset(out, 0, sizeof *out);
    try {
        SessionKeys11 k;
        load_keys(*keys, k);
        DataFrame f;
        const auto st = lsim::lorawan::open_uplink(in, len, k, to_ctx(*ctx), f);
        from_frame(f, *out);
        if (st != lsim::lorawan::SecureStatus::Ok) {
            // Aucune donnée claire ne sort d'une trame rejetée.
            std::memset(out->payload, 0, sizeof out->payload);
            out->payload_len = 0;
            std::memset(out->fopts, 0, sizeof out->fopts);
            out->fopts_len = 0;
        }
        return map_secure(st);
    } catch (...) {
        std::memset(out, 0, sizeof *out);
        return LSIM_STATUS_INTERNAL;
    }
}

lsim::lorawan::DownlinkContext to_down_ctx(const lsim_downlink_context& c) {
    lsim::lorawan::DownlinkContext d;
    d.conf_fcnt = c.conf_fcnt;
    d.nfcnt32 = c.nfcnt32;
    d.afcnt32 = c.afcnt32;
    return d;
}

int32_t lsim_seal_downlink(const lsim_uplink_frame* frame, const lsim_session_keys_11* keys,
                           const lsim_downlink_context* ctx, uint8_t* out, size_t cap,
                           size_t* out_written) {
    if (frame == nullptr || keys == nullptr || ctx == nullptr || out == nullptr ||
        out_written == nullptr) {
        return static_cast<int32_t>(lsim::lora::Status::NullOutput);
    }
    *out_written = 0;
    if (frame->payload_len > lsim::lorawan::kMaxFrmPayload || frame->fopts_len > 15) {
        return map_secure(lsim::lorawan::SecureStatus::InvalidPayload);
    }
    try {
        DataFrame f;
        to_frame(*frame, f);
        SessionKeys11 k;
        load_keys(*keys, k);
        const auto st = lsim::lorawan::seal_downlink(f, k, to_down_ctx(*ctx), out, cap, *out_written);
        if (st != lsim::lorawan::SecureStatus::Ok) {
            *out_written = 0;
        }
        return map_secure(st);
    } catch (...) {
        *out_written = 0;
        return LSIM_STATUS_INTERNAL;
    }
}

int32_t lsim_open_downlink(const uint8_t* in, size_t len, const lsim_session_keys_11* keys,
                           const lsim_downlink_context* ctx, lsim_uplink_frame* out) {
    if (in == nullptr || keys == nullptr || ctx == nullptr || out == nullptr) {
        return static_cast<int32_t>(lsim::lora::Status::NullOutput);
    }
    std::memset(out, 0, sizeof *out);
    try {
        SessionKeys11 k;
        load_keys(*keys, k);
        DataFrame f;
        const auto st = lsim::lorawan::open_downlink(in, len, k, to_down_ctx(*ctx), f);
        from_frame(f, *out);
        if (st != lsim::lorawan::SecureStatus::Ok) {
            std::memset(out->payload, 0, sizeof out->payload);
            out->payload_len = 0;
            std::memset(out->fopts, 0, sizeof out->fopts);
            out->fopts_len = 0;
        }
        return map_secure(st);
    } catch (...) {
        std::memset(out, 0, sizeof *out);
        return LSIM_STATUS_INTERNAL;
    }
}

int32_t lsim_simulate_uplinks(const lsim_end_device* devices, size_t device_count,
                              const lsim_gateway* gateway, const lsim_propagation* prop,
                              lsim_device_stats* per_device, lsim_sim_stats* totals) {
    if (gateway == nullptr || prop == nullptr || totals == nullptr ||
        (device_count > 0 && (devices == nullptr || per_device == nullptr))) {
        return static_cast<int32_t>(lsim::lora::Status::NullOutput);
    }
    if (device_count > lsim::sim::kMaxEndDevices) {
        return LSIM_STATUS_SIM_BASE + static_cast<int32_t>(lsim::sim::SimStatus::TooManyDevices);
    }
    try {
        std::vector<lsim::sim::EndDeviceSpec> specs(device_count);
        for (size_t i = 0; i < device_count; ++i) {
            const lsim_end_device& d = devices[i];
            lsim::sim::EndDeviceSpec& s = specs[i];
            s.position.x_m = d.x_m;
            s.position.y_m = d.y_m;
            s.spreading_factor = d.spreading_factor;
            s.payload_bytes = d.payload_bytes;
            s.tx_power_dbm = d.tx_power_dbm;
            s.start_offset_ns = d.start_offset_ns;
            s.period_ns = d.period_ns;
            s.messages = d.messages;
            s.duty_cycle = d.duty_cycle;
        }
        lsim::sim::GatewaySpec g;
        g.position.x_m = gateway->x_m;
        g.position.y_m = gateway->y_m;
        g.antenna_gain_dbi = gateway->antenna_gain_dbi;
        g.rx_sensitivity_offset_db = gateway->rx_sensitivity_offset_db;

        lsim::sim::PropagationSpec p;
        p.frequency_hz = prop->frequency_hz;
        p.reference_distance_m = prop->reference_distance_m;
        p.exponent = prop->exponent;
        p.capture_threshold_db = prop->capture_threshold_db;
        p.shadowing_sigma_db = prop->shadowing_sigma_db;
        p.shadowing_seed = prop->shadowing_seed;

        std::vector<lsim::sim::DeviceStats> stats(device_count);
        lsim::sim::SimulationStats tot;
        const auto st = lsim::sim::simulate_uplinks(specs.data(), device_count, g, p,
                                                    stats.data(), tot);
        totals->sent = tot.sent;
        totals->received = tot.received;
        totals->lost_sensitivity = tot.lost_sensitivity;
        totals->lost_collision = tot.lost_collision;
        totals->lost_gateway_busy = tot.lost_gateway_busy;
        totals->airtime_ns = tot.airtime_ns;
        totals->gateway_busy_ns = tot.gateway_busy_ns;
        totals->gateway_peak_concurrent = tot.gateway_peak_concurrent;
        totals->observation_ns = tot.observation_ns;
        totals->gateway_utilization = tot.gateway_utilization;
        for (size_t i = 0; i < device_count; ++i) {
            per_device[i].sent = stats[i].sent;
            per_device[i].received = stats[i].received;
            per_device[i].lost_sensitivity = stats[i].lost_sensitivity;
            per_device[i].lost_collision = stats[i].lost_collision;
            per_device[i].lost_gateway_busy = stats[i].lost_gateway_busy;
            per_device[i].airtime_ns = stats[i].airtime_ns;
        }
        if (st == lsim::sim::SimStatus::Ok) {
            return 0;
        }
        return LSIM_STATUS_SIM_BASE + static_cast<int32_t>(st);
    } catch (...) {
        return LSIM_STATUS_INTERNAL;
    }
}

namespace {

// Copie les données C de l'environnement vers des objets C++ validés.
// Retourne 0 ou un code de statut LSIM_STATUS_ENV_BASE + EnvStatus.
int32_t build_environment(const lsim_environment* in, lsim::env::ElevationGrid& grid,
                          std::vector<lsim::env::Obstacle>& obstacles,
                          lsim::env::Environment& out) {
    out = lsim::env::Environment{};
    out.gateway_height_m = in->gateway_height_m;
    out.device_height_m = in->device_height_m;
    if (in->obstacle_count > 0 && in->obstacles == nullptr) {
        return LSIM_STATUS_ENV_BASE + static_cast<int32_t>(lsim::env::EnvStatus::InvalidInput);
    }
    if (in->obstacle_count > lsim::env::kMaxObstacles) {
        return LSIM_STATUS_ENV_BASE + static_cast<int32_t>(lsim::env::EnvStatus::TooManyObstacles);
    }
    obstacles.resize(in->obstacle_count);
    for (size_t i = 0; i < in->obstacle_count; ++i) {
        const lsim_obstacle& o = in->obstacles[i];
        obstacles[i].x_min_m = o.x_min_m;
        obstacles[i].y_min_m = o.y_min_m;
        obstacles[i].x_max_m = o.x_max_m;
        obstacles[i].y_max_m = o.y_max_m;
        obstacles[i].height_m = o.height_m;
        obstacles[i].attenuation_db = o.attenuation_db;
    }
    out.obstacles = obstacles.data();
    out.obstacle_count = obstacles.size();
    if (in->grid_z != nullptr) {
        const std::size_t count = static_cast<std::size_t>(in->grid_nx) * in->grid_ny;
        const auto st = lsim::env::make_elevation_grid(
            in->grid_origin_x_m, in->grid_origin_y_m, in->grid_cell_m,
            in->grid_nx, in->grid_ny, in->grid_z, count, grid);
        if (st != lsim::env::EnvStatus::Ok) {
            return LSIM_STATUS_ENV_BASE + static_cast<int32_t>(st);
        }
        out.grid = &grid;
    }
    return 0;
}

}  // namespace

namespace {

// Conversion des entrées C, appel du moteur et recopie des compteurs. `trace` optionnel.
int32_t run_uplinks_env(const lsim_end_device* devices, size_t device_count,
                        const lsim_gateway* gateway, const lsim_propagation* prop,
                        const lsim_environment* env, lsim_device_stats* per_device,
                        lsim_sim_stats* totals, std::vector<lsim::sim::TxRecord>* trace,
                        const std::vector<lsim::sim::Interval>* busy = nullptr,
                        const std::vector<lsim::sim::MacReservation>* reservations = nullptr,
                        const lsim::sim::CausalDownlinks* causal = nullptr) {
    try {
        std::vector<lsim::sim::EndDeviceSpec> specs(device_count);
        for (size_t i = 0; i < device_count; ++i) {
            const lsim_end_device& d = devices[i];
            lsim::sim::EndDeviceSpec& s = specs[i];
            s.position.x_m = d.x_m;
            s.position.y_m = d.y_m;
            s.spreading_factor = d.spreading_factor;
            s.payload_bytes = d.payload_bytes;
            s.tx_power_dbm = d.tx_power_dbm;
            s.start_offset_ns = d.start_offset_ns;
            s.period_ns = d.period_ns;
            s.messages = d.messages;
            s.duty_cycle = d.duty_cycle;
        }
        lsim::sim::GatewaySpec g;
        g.position.x_m = gateway->x_m;
        g.position.y_m = gateway->y_m;
        g.antenna_gain_dbi = gateway->antenna_gain_dbi;
        g.rx_sensitivity_offset_db = gateway->rx_sensitivity_offset_db;

        lsim::sim::PropagationSpec p;
        p.frequency_hz = prop->frequency_hz;
        p.reference_distance_m = prop->reference_distance_m;
        p.exponent = prop->exponent;
        p.capture_threshold_db = prop->capture_threshold_db;
        p.shadowing_sigma_db = prop->shadowing_sigma_db;
        p.shadowing_seed = prop->shadowing_seed;

        lsim::env::ElevationGrid grid;
        std::vector<lsim::env::Obstacle> obstacles;
        lsim::env::Environment e;
        if (env != nullptr) {
            const int32_t built = build_environment(env, grid, obstacles, e);
            if (built != 0) {
                return built;
            }
        }

        std::vector<lsim::sim::DeviceStats> stats(device_count);
        lsim::sim::SimulationStats tot;
        const auto st = lsim::sim::simulate_uplinks(specs.data(), device_count, g, p,
                                                    stats.data(), tot,
                                                    env != nullptr ? &e : nullptr, trace, busy,
                                                    reservations, causal);
        if (st != lsim::sim::SimStatus::Ok) {
            return LSIM_STATUS_SIM_BASE + static_cast<int32_t>(st);
        }
        totals->sent = tot.sent;
        totals->received = tot.received;
        totals->lost_sensitivity = tot.lost_sensitivity;
        totals->lost_collision = tot.lost_collision;
        totals->lost_gateway_busy = tot.lost_gateway_busy;
        totals->airtime_ns = tot.airtime_ns;
        totals->gateway_busy_ns = tot.gateway_busy_ns;
        totals->gateway_peak_concurrent = tot.gateway_peak_concurrent;
        totals->observation_ns = tot.observation_ns;
        totals->gateway_utilization = tot.gateway_utilization;
        for (size_t i = 0; i < device_count; ++i) {
            per_device[i].sent = stats[i].sent;
            per_device[i].received = stats[i].received;
            per_device[i].lost_sensitivity = stats[i].lost_sensitivity;
            per_device[i].lost_collision = stats[i].lost_collision;
            per_device[i].lost_gateway_busy = stats[i].lost_gateway_busy;
            per_device[i].airtime_ns = stats[i].airtime_ns;
        }
        return 0;
    } catch (...) {
        return LSIM_STATUS_INTERNAL;
    }
}

}  // namespace

int32_t lsim_simulate_uplinks_env(const lsim_end_device* devices, size_t device_count,
                                  const lsim_gateway* gateway, const lsim_propagation* prop,
                                  const lsim_environment* env,
                                  lsim_device_stats* per_device, lsim_sim_stats* totals) {
    if (env == nullptr) {
        return lsim_simulate_uplinks(devices, device_count, gateway, prop, per_device, totals);
    }
    if (gateway == nullptr || prop == nullptr || totals == nullptr ||
        (device_count > 0 && (devices == nullptr || per_device == nullptr))) {
        return static_cast<int32_t>(lsim::lora::Status::NullOutput);
    }
    if (device_count > lsim::sim::kMaxEndDevices) {
        return LSIM_STATUS_SIM_BASE + static_cast<int32_t>(lsim::sim::SimStatus::TooManyDevices);
    }
    return run_uplinks_env(devices, device_count, gateway, prop, env, per_device, totals, nullptr);
}

// Trace par transmission : borne de sortie (le contrat d'API limite les événements par run).
constexpr std::uint64_t kMaxTraceRecords = 200'000;
// Périodes d'émission passerelle : une par downlink au plus (bornées comme les transmissions).
constexpr size_t kMaxGatewayBusyIntervals = 5'000'000;

int32_t lsim_simulate_uplinks_trace(const lsim_end_device* devices, size_t device_count,
                                    const lsim_gateway* gateway, const lsim_propagation* prop,
                                    const lsim_environment* env, lsim_device_stats* per_device,
                                    lsim_sim_stats* totals, lsim_tx_record* records,
                                    size_t record_capacity, size_t* record_count,
                                    const lsim_interval* gateway_busy,
                                    size_t gateway_busy_count) {
    return lsim_simulate_uplinks_trace_v2(devices, device_count, gateway, prop, env, per_device,
                                          totals, records, record_capacity, record_count,
                                          gateway_busy, gateway_busy_count, nullptr, 0);
}

int32_t lsim_simulate_uplinks_trace_v2(const lsim_end_device* devices, size_t device_count,
                                       const lsim_gateway* gateway, const lsim_propagation* prop,
                                       const lsim_environment* env, lsim_device_stats* per_device,
                                       lsim_sim_stats* totals, lsim_tx_record* records,
                                       size_t record_capacity, size_t* record_count,
                                       const lsim_interval* gateway_busy,
                                       size_t gateway_busy_count,
                                       const lsim_mac_reservation* reservations,
                                       size_t reservation_count) {
    if (gateway == nullptr || prop == nullptr || totals == nullptr || record_count == nullptr ||
        (device_count > 0 && (devices == nullptr || per_device == nullptr)) ||
        (gateway_busy_count > 0 && gateway_busy == nullptr) ||
        (reservation_count > 0 && reservations == nullptr)) {
        return static_cast<int32_t>(lsim::lora::Status::NullOutput);
    }
    *record_count = 0;
    if (gateway_busy_count > kMaxGatewayBusyIntervals) {
        return LSIM_STATUS_SIM_BASE + static_cast<int32_t>(lsim::sim::SimStatus::InvalidGatewayBusy);
    }
    std::vector<lsim::sim::Interval> busy(gateway_busy_count);
    for (size_t k = 0; k < gateway_busy_count; ++k) {
        busy[k].start = gateway_busy[k].start_ns;
        busy[k].end = gateway_busy[k].end_ns;
    }
    if (device_count > lsim::sim::kMaxEndDevices) {
        return LSIM_STATUS_SIM_BASE + static_cast<int32_t>(lsim::sim::SimStatus::TooManyDevices);
    }
    std::uint64_t planned = 0;
    for (size_t i = 0; i < device_count; ++i) {
        planned += devices[i].messages;
    }
    if (planned > kMaxTraceRecords) {
        return LSIM_STATUS_SIM_BASE + static_cast<int32_t>(lsim::sim::SimStatus::TraceTooLarge);
    }
    try {
        std::vector<lsim::sim::MacReservation> res(reservation_count);
        for (size_t k = 0; k < reservation_count; ++k) {
            res[k].device = reservations[k].device_index;
            res[k].rank = reservations[k].rank;
            res[k].extra_bytes = reservations[k].extra_bytes;
        }
        std::vector<lsim::sim::TxRecord> trace;
        const int32_t st = run_uplinks_env(devices, device_count, gateway, prop, env, per_device,
                                           totals, &trace, &busy, &res);
        if (st != 0) {
            return st;
        }
        *record_count = trace.size();
        if (trace.size() > record_capacity) {
            return LSIM_STATUS_SIM_BASE + static_cast<int32_t>(lsim::sim::SimStatus::TraceBufferTooSmall);
        }
        for (size_t k = 0; k < trace.size(); ++k) {
            const lsim::sim::TxRecord& t = trace[k];
            records[k].device_index = t.device;
            records[k].start_ns = t.start_ns;
            records[k].end_ns = t.end_ns;
            records[k].spreading_factor = t.spreading_factor;
            records[k].rssi_dbm = t.rssi_dbm;
            records[k].outcome = static_cast<uint8_t>(t.outcome);
        }
        return 0;
    } catch (...) {
        return LSIM_STATUS_INTERNAL;
    }
}

int32_t lsim_simulate_uplinks_causal_v1(const lsim_end_device* devices, size_t device_count,
                                        const lsim_gateway* gateway, const lsim_propagation* prop,
                                        const lsim_environment* env, lsim_device_stats* per_device,
                                        lsim_sim_stats* totals, lsim_tx_record* records,
                                        size_t record_capacity, size_t* record_count,
                                        const lsim_plan_device* radios,
                                        const lsim_plan_options* options,
                                        lsim_interval* busy_out, size_t busy_capacity,
                                        size_t* busy_count) {
    if (gateway == nullptr || prop == nullptr || totals == nullptr || record_count == nullptr ||
        busy_count == nullptr || options == nullptr ||
        (device_count > 0 && (devices == nullptr || per_device == nullptr || radios == nullptr))) {
        return static_cast<int32_t>(lsim::lora::Status::NullOutput);
    }
    *record_count = 0;
    *busy_count = 0;
    if (device_count > lsim::sim::kMaxEndDevices) {
        return LSIM_STATUS_SIM_BASE + static_cast<int32_t>(lsim::sim::SimStatus::TooManyDevices);
    }
    std::uint64_t planned = 0;
    for (size_t i = 0; i < device_count; ++i) {
        planned += devices[i].messages;
    }
    if (planned > kMaxTraceRecords) {
        return LSIM_STATUS_SIM_BASE + static_cast<int32_t>(lsim::sim::SimStatus::TraceTooLarge);
    }
    try {
        lsim::sim::CausalDownlinks causal;
        causal.radios.resize(device_count);
        for (size_t i = 0; i < device_count; ++i) {
            const lsim_plan_device& d = radios[i];
            lsim::plan::DeviceRadio& r = causal.radios[i];
            r.freq_hz = d.freq_hz;
            r.dr = d.dr;
            r.rx1_hz = d.rx1_hz;
            r.tx_power_dbm = d.tx_power_dbm;
            r.rx1_sf = d.rx1_sf;
            r.rx1_bw_hz = d.rx1_bw_hz;
        }
        causal.options.confirmed_uplinks = options->confirmed_uplinks != 0;
        causal.options.downlink_every = options->downlink_every;
        causal.options.downlink_payload_bytes = options->downlink_payload_bytes;
        causal.options.gateway_tx_power_dbm = options->gateway_tx_power_dbm;
        causal.options.device_antenna_gain_dbi = options->device_antenna_gain_dbi;
        causal.options.device_rx_offset_db = options->device_rx_offset_db;
        // Options et radios validées avant la simulation (mêmes codes que lsim_plan_downlinks_v1).
        const lsim::plan::DownlinkScheduler probe(causal.radios, causal.options);
        if (probe.status() != lsim::plan::PlanStatus::Ok) {
            return LSIM_STATUS_PLAN_BASE + static_cast<int32_t>(probe.status());
        }
        std::vector<lsim::plan::Interval> planned_busy;
        causal.busy_out = &planned_busy;

        std::vector<lsim::sim::TxRecord> trace;
        const int32_t st = run_uplinks_env(devices, device_count, gateway, prop, env, per_device,
                                           totals, &trace, nullptr, nullptr, &causal);
        if (st != 0) {
            return st;
        }
        *record_count = trace.size();
        *busy_count = planned_busy.size();
        if (trace.size() > record_capacity) {
            return LSIM_STATUS_SIM_BASE + static_cast<int32_t>(lsim::sim::SimStatus::TraceBufferTooSmall);
        }
        if (planned_busy.size() > busy_capacity) {
            return LSIM_STATUS_PLAN_BASE + 4;
        }
        for (size_t k = 0; k < trace.size(); ++k) {
            const lsim::sim::TxRecord& t = trace[k];
            records[k].device_index = t.device;
            records[k].start_ns = t.start_ns;
            records[k].end_ns = t.end_ns;
            records[k].spreading_factor = t.spreading_factor;
            records[k].rssi_dbm = t.rssi_dbm;
            records[k].outcome = static_cast<uint8_t>(t.outcome);
        }
        for (size_t k = 0; k < planned_busy.size(); ++k) {
            busy_out[k].start_ns = planned_busy[k].start_ns;
            busy_out[k].end_ns = planned_busy[k].end_ns;
        }
        return 0;
    } catch (...) {
        return LSIM_STATUS_INTERNAL;
    }
}

int32_t lsim_simulate_downlinks_env(const lsim_end_device* devices, const lsim_downlink_plan* plans,
                                    size_t device_count, const lsim_gateway* gateway,
                                    const lsim_propagation* prop, const lsim_environment* env,
                                    lsim_device_stats* per_device, lsim_sim_stats* totals,
                                    lsim_downlink_stats* per_device_dl, lsim_downlink_stats* dl_total) {
    if (gateway == nullptr || prop == nullptr || totals == nullptr || dl_total == nullptr ||
        (device_count > 0 && (devices == nullptr || per_device == nullptr ||
                              per_device_dl == nullptr))) {
        return static_cast<int32_t>(lsim::lora::Status::NullOutput);
    }
    if (device_count > lsim::sim::kMaxEndDevices) {
        return LSIM_STATUS_SIM_BASE + static_cast<int32_t>(lsim::sim::SimStatus::TooManyDevices);
    }
    try {
        std::vector<lsim::sim::EndDeviceSpec> specs(device_count);
        for (size_t i = 0; i < device_count; ++i) {
            const lsim_end_device& d = devices[i];
            lsim::sim::EndDeviceSpec& s = specs[i];
            s.position.x_m = d.x_m;
            s.position.y_m = d.y_m;
            s.spreading_factor = d.spreading_factor;
            s.payload_bytes = d.payload_bytes;
            s.tx_power_dbm = d.tx_power_dbm;
            s.start_offset_ns = d.start_offset_ns;
            s.period_ns = d.period_ns;
            s.messages = d.messages;
            s.duty_cycle = d.duty_cycle;
            if (plans != nullptr) {
                const lsim_downlink_plan& p = plans[i];
                if (p.device_class > 2) {
                    return LSIM_STATUS_SIM_BASE + static_cast<int32_t>(lsim::sim::SimStatus::InvalidInput);
                }
                s.downlink.device_class = static_cast<lsim::lorawan::downlink::DeviceClass>(p.device_class);
                s.downlink.count = p.count;
                s.downlink.first_request_ns = p.first_request_ns;
                s.downlink.request_period_ns = p.request_period_ns;
                s.downlink.rx_window_ns = p.rx_window_ns;
                s.downlink.dev_addr = p.dev_addr;
                s.downlink.periodicity = p.periodicity;
                s.downlink.clock_drift_ppm = p.clock_drift_ppm;
            }
        }
        lsim::sim::GatewaySpec g;
        g.position.x_m = gateway->x_m;
        g.position.y_m = gateway->y_m;
        g.antenna_gain_dbi = gateway->antenna_gain_dbi;
        g.rx_sensitivity_offset_db = gateway->rx_sensitivity_offset_db;

        lsim::sim::PropagationSpec p;
        p.frequency_hz = prop->frequency_hz;
        p.reference_distance_m = prop->reference_distance_m;
        p.exponent = prop->exponent;
        p.capture_threshold_db = prop->capture_threshold_db;
        p.shadowing_sigma_db = prop->shadowing_sigma_db;
        p.shadowing_seed = prop->shadowing_seed;

        lsim::env::ElevationGrid grid;
        std::vector<lsim::env::Obstacle> obstacles;
        lsim::env::Environment e;
        const lsim::env::Environment* envp = nullptr;
        if (env != nullptr) {
            const int32_t built = build_environment(env, grid, obstacles, e);
            if (built != 0) return built;
            envp = &e;
        }

        std::vector<lsim::sim::DeviceStats> stats(device_count);
        lsim::sim::SimulationStats tot;
        const auto st = lsim::sim::simulate_uplinks(specs.data(), device_count, g, p, stats.data(),
                                                    tot, envp);
        if (st != lsim::sim::SimStatus::Ok) {
            return LSIM_STATUS_SIM_BASE + static_cast<int32_t>(st);
        }
        totals->sent = tot.sent;
        totals->received = tot.received;
        totals->lost_sensitivity = tot.lost_sensitivity;
        totals->lost_collision = tot.lost_collision;
        totals->lost_gateway_busy = tot.lost_gateway_busy;
        totals->airtime_ns = tot.airtime_ns;
        totals->gateway_busy_ns = tot.gateway_busy_ns;
        totals->gateway_peak_concurrent = tot.gateway_peak_concurrent;
        totals->observation_ns = tot.observation_ns;
        totals->gateway_utilization = tot.gateway_utilization;
        dl_total->requested = tot.downlink.requested;
        dl_total->delivered = tot.downlink.delivered;
        dl_total->latency_sum_ns = tot.downlink.latency_sum_ns;
        dl_total->latency_max_ns = tot.downlink.latency_max_ns;
        for (size_t i = 0; i < device_count; ++i) {
            per_device[i].sent = stats[i].sent;
            per_device[i].received = stats[i].received;
            per_device[i].lost_sensitivity = stats[i].lost_sensitivity;
            per_device[i].lost_collision = stats[i].lost_collision;
            per_device[i].lost_gateway_busy = stats[i].lost_gateway_busy;
            per_device[i].airtime_ns = stats[i].airtime_ns;
            per_device_dl[i].requested = stats[i].downlink.requested;
            per_device_dl[i].delivered = stats[i].downlink.delivered;
            per_device_dl[i].latency_sum_ns = stats[i].downlink.latency_sum_ns;
            per_device_dl[i].latency_max_ns = stats[i].downlink.latency_max_ns;
        }
        return 0;
    } catch (...) {
        return LSIM_STATUS_INTERNAL;
    }
}

int32_t lsim_env_path_loss_matrix(const lsim_propagation* prop, const lsim_environment* env,
                                  size_t n, const double* x_m, const double* y_m,
                                  double* out_db) {
    if (prop == nullptr || env == nullptr || x_m == nullptr || y_m == nullptr || out_db == nullptr) {
        return static_cast<int32_t>(lsim::lora::Status::NullOutput);
    }
    if (n == 0 || n > 64) {
        return LSIM_STATUS_ENV_BASE + static_cast<int32_t>(lsim::env::EnvStatus::InvalidInput);
    }
    try {
        lsim::radio::LogDistanceModel model;
        model.frequency_hz = prop->frequency_hz;
        model.reference_distance_m = prop->reference_distance_m;
        model.exponent = prop->exponent;
        lsim::env::ElevationGrid grid;
        std::vector<lsim::env::Obstacle> obstacles;
        lsim::env::Environment e;
        const int32_t built = build_environment(env, grid, obstacles, e);
        if (built != 0) {
            return built;
        }
        const std::uint64_t checks = static_cast<std::uint64_t>(n) * n * e.obstacle_count;
        if (checks > lsim::env::kMaxObstacleChecks) {
            return LSIM_STATUS_ENV_BASE + static_cast<int32_t>(lsim::env::EnvStatus::WorkLimit);
        }
        for (size_t i = 0; i < n; ++i) {
            out_db[i * n + i] = 0.0;
            for (size_t j = 0; j < n; ++j) {
                if (i == j) continue;
                lsim::env::PathLoss pl;
                const auto st = lsim::env::path_loss_db(model, x_m[i], y_m[i], x_m[j], y_m[j], e, pl);
                if (st != lsim::env::EnvStatus::Ok) {
                    return LSIM_STATUS_ENV_BASE + static_cast<int32_t>(st);
                }
                out_db[i * n + j] = pl.total_db;
            }
        }
        return 0;
    } catch (...) {
        return LSIM_STATUS_INTERNAL;
    }
}

int32_t lsim_coverage_radii(const lsim_gateway* gateway, const lsim_propagation* prop,
                            double max_path_loss_db, const lsim_environment* env,
                            double step_m, size_t azimuths, double* radii_out) {
    if (gateway == nullptr || prop == nullptr || radii_out == nullptr) {
        return static_cast<int32_t>(lsim::lora::Status::NullOutput);
    }
    try {
        lsim::radio::LogDistanceModel model;
        model.frequency_hz = prop->frequency_hz;
        model.reference_distance_m = prop->reference_distance_m;
        model.exponent = prop->exponent;
        lsim::env::ElevationGrid grid;
        std::vector<lsim::env::Obstacle> obstacles;
        lsim::env::Environment e;
        if (env != nullptr) {
            const int32_t built = build_environment(env, grid, obstacles, e);
            if (built != 0) {
                return built;
            }
        }
        const auto st = lsim::env::coverage_radii_m(model, gateway->x_m, gateway->y_m, e,
                                                    max_path_loss_db, step_m, azimuths, radii_out);
        if (st != lsim::env::EnvStatus::Ok) {
            return LSIM_STATUS_ENV_BASE + static_cast<int32_t>(st);
        }
        return 0;
    } catch (...) {
        return LSIM_STATUS_INTERNAL;
    }
}

int32_t lsim_encode_join_request(const lsim_join_request* req, const uint8_t nwk_key[16],
                                 uint8_t out[23]) {
    if (req == nullptr || nwk_key == nullptr || out == nullptr) {
        return static_cast<int32_t>(lsim::lora::Status::NullOutput);
    }
    try {
        lsim::lorawan::JoinRequestFields f;
        std::memcpy(f.join_eui.data(), req->join_eui, 8);
        std::memcpy(f.dev_eui.data(), req->dev_eui, 8);
        std::memcpy(f.dev_nonce.data(), req->dev_nonce, 2);
        Key128 k;
        std::memcpy(k.data(), nwk_key, 16);
        std::size_t n = 0;
        const auto st = lsim::lorawan::encode_join_request(f, k, out, 23, n);
        if (st != lsim::lorawan::JoinStatus::Ok) {
            std::memset(out, 0, 23);
        }
        return map_join(st);
    } catch (...) {
        return LSIM_STATUS_INTERNAL;
    }
}

int32_t lsim_decode_join_request(const uint8_t* in, size_t len, const uint8_t nwk_key[16],
                                 lsim_join_request* out) {
    if (in == nullptr || nwk_key == nullptr || out == nullptr) {
        return static_cast<int32_t>(lsim::lora::Status::NullOutput);
    }
    std::memset(out, 0, sizeof *out);
    try {
        Key128 k;
        std::memcpy(k.data(), nwk_key, 16);
        lsim::lorawan::JoinRequestFields f;
        const auto st = lsim::lorawan::decode_join_request(in, len, k, f);
        if (st == lsim::lorawan::JoinStatus::Ok) {
            std::memcpy(out->join_eui, f.join_eui.data(), 8);
            std::memcpy(out->dev_eui, f.dev_eui.data(), 8);
            std::memcpy(out->dev_nonce, f.dev_nonce.data(), 2);
        }
        return map_join(st);
    } catch (...) {
        std::memset(out, 0, sizeof *out);
        return LSIM_STATUS_INTERNAL;
    }
}

int32_t lsim_encode_join_accept(const lsim_join_accept* accept, const uint8_t nwk_key[16],
                                const uint8_t dev_eui[8], const uint8_t join_eui[8],
                                const uint8_t dev_nonce[2], uint8_t* out, size_t cap,
                                size_t* out_len) {
    if (accept == nullptr || nwk_key == nullptr || dev_eui == nullptr || join_eui == nullptr ||
        dev_nonce == nullptr || out == nullptr || out_len == nullptr) {
        return static_cast<int32_t>(lsim::lora::Status::NullOutput);
    }
    *out_len = 0;
    try {
        Key128 k;
        std::memcpy(k.data(), nwk_key, 16);
        std::size_t n = 0;
        const auto st = lsim::lorawan::encode_join_accept(to_accept(*accept), k, arr8(dev_eui),
                                                          arr8(join_eui), arr2(dev_nonce), out,
                                                          cap, n);
        if (st == lsim::lorawan::JoinStatus::Ok) {
            *out_len = n;
        }
        return map_join(st);
    } catch (...) {
        return LSIM_STATUS_INTERNAL;
    }
}

int32_t lsim_decode_join_accept(const uint8_t* in, size_t len, const uint8_t nwk_key[16],
                                const uint8_t dev_eui[8], const uint8_t join_eui[8],
                                const uint8_t dev_nonce[2], lsim_join_accept* out) {
    if (in == nullptr || nwk_key == nullptr || dev_eui == nullptr || join_eui == nullptr ||
        dev_nonce == nullptr || out == nullptr) {
        return static_cast<int32_t>(lsim::lora::Status::NullOutput);
    }
    std::memset(out, 0, sizeof *out);
    try {
        Key128 k;
        std::memcpy(k.data(), nwk_key, 16);
        lsim::lorawan::JoinAcceptFields f;
        const auto st = lsim::lorawan::decode_join_accept(in, len, k, arr8(dev_eui), arr8(join_eui),
                                                          arr2(dev_nonce), f);
        if (st == lsim::lorawan::JoinStatus::Ok) {
            from_accept(f, *out);
        }
        return map_join(st);
    } catch (...) {
        std::memset(out, 0, sizeof *out);
        return LSIM_STATUS_INTERNAL;
    }
}

int32_t lsim_encode_rejoin_join_accept(const lsim_join_accept* accept, const uint8_t nwk_key[16],
                                       const uint8_t dev_eui[8], const uint8_t join_eui[8],
                                       uint8_t rejoin_type, uint16_t rjcount, uint8_t* out,
                                       size_t cap, size_t* out_len) {
    if (accept == nullptr || nwk_key == nullptr || dev_eui == nullptr || join_eui == nullptr ||
        out == nullptr || out_len == nullptr) {
        return static_cast<int32_t>(lsim::lora::Status::NullOutput);
    }
    *out_len = 0;
    try {
        Key128 k;
        std::memcpy(k.data(), nwk_key, 16);
        std::size_t n = 0;
        const auto st = lsim::lorawan::encode_rejoin_join_accept(
            to_accept(*accept), k, arr8(dev_eui), arr8(join_eui), rejoin_type, rjcount, out, cap,
            n);
        if (st == lsim::lorawan::JoinStatus::Ok) {
            *out_len = n;
        }
        return map_join(st);
    } catch (...) {
        return LSIM_STATUS_INTERNAL;
    }
}

int32_t lsim_decode_rejoin_join_accept(const uint8_t* in, size_t len, const uint8_t nwk_key[16],
                                       const uint8_t dev_eui[8], const uint8_t join_eui[8],
                                       uint8_t rejoin_type, uint16_t rjcount,
                                       lsim_join_accept* out) {
    if (in == nullptr || nwk_key == nullptr || dev_eui == nullptr || join_eui == nullptr ||
        out == nullptr) {
        return static_cast<int32_t>(lsim::lora::Status::NullOutput);
    }
    std::memset(out, 0, sizeof *out);
    try {
        Key128 k;
        std::memcpy(k.data(), nwk_key, 16);
        lsim::lorawan::JoinAcceptFields f;
        const auto st = lsim::lorawan::decode_rejoin_join_accept(
            in, len, k, arr8(dev_eui), arr8(join_eui), rejoin_type, rjcount, f);
        if (st == lsim::lorawan::JoinStatus::Ok) {
            from_accept(f, *out);
        }
        return map_join(st);
    } catch (...) {
        std::memset(out, 0, sizeof *out);
        return LSIM_STATUS_INTERNAL;
    }
}

}  // extern "C"

// ------------------------------------------- Plusieurs passerelles (uplinks)

int32_t lsim_simulate_uplinks_multi(const lsim_end_device* devices, size_t device_count,
                                    const lsim_gateway* gateways, size_t gateway_count,
                                    const lsim_propagation* prop, const lsim_environment* env,
                                    lsim_device_stats* per_device, lsim_network_stats* totals,
                                    lsim_gateway_rx_stats* per_gateway, const lsim_interval* busy,
                                    const size_t* busy_counts, lsim_multi_tx_record* records,
                                    size_t record_capacity, size_t* record_count) {
    if (gateways == nullptr || prop == nullptr || totals == nullptr || per_gateway == nullptr ||
        (device_count > 0 && (devices == nullptr || per_device == nullptr)) ||
        (busy != nullptr && busy_counts == nullptr) ||
        (record_count != nullptr && records == nullptr && record_capacity > 0)) {
        return static_cast<int32_t>(lsim::lora::Status::NullOutput);
    }
    if (device_count > lsim::sim::kMaxEndDevices) {
        return LSIM_STATUS_SIM_BASE + static_cast<int32_t>(lsim::sim::SimStatus::TooManyDevices);
    }
    if (gateway_count == 0 || gateway_count > lsim::sim::kMaxGateways) {
        return LSIM_STATUS_SIM_BASE + static_cast<int32_t>(lsim::sim::SimStatus::InvalidInput);
    }
    try {
        std::vector<lsim::sim::EndDeviceSpec> specs(device_count);
        for (size_t i = 0; i < device_count; ++i) {
            const lsim_end_device& d = devices[i];
            lsim::sim::EndDeviceSpec& s = specs[i];
            s.position.x_m = d.x_m;
            s.position.y_m = d.y_m;
            s.spreading_factor = d.spreading_factor;
            s.payload_bytes = d.payload_bytes;
            s.tx_power_dbm = d.tx_power_dbm;
            s.start_offset_ns = d.start_offset_ns;
            s.period_ns = d.period_ns;
            s.messages = d.messages;
            s.duty_cycle = d.duty_cycle;
        }
        std::vector<lsim::sim::GatewaySpec> gws(gateway_count);
        for (size_t g = 0; g < gateway_count; ++g) {
            gws[g].position.x_m = gateways[g].x_m;
            gws[g].position.y_m = gateways[g].y_m;
            gws[g].antenna_gain_dbi = gateways[g].antenna_gain_dbi;
            gws[g].rx_sensitivity_offset_db = gateways[g].rx_sensitivity_offset_db;
        }
        std::vector<std::vector<lsim::sim::Interval>> busy_lists;
        if (busy != nullptr) {
            busy_lists.resize(gateway_count);
            size_t k = 0;
            for (size_t g = 0; g < gateway_count; ++g) {
                for (size_t c = 0; c < busy_counts[g]; ++c, ++k) {
                    busy_lists[g].push_back(lsim::sim::Interval{busy[k].start_ns, busy[k].end_ns});
                }
            }
        }
        lsim::sim::PropagationSpec p;
        p.frequency_hz = prop->frequency_hz;
        p.reference_distance_m = prop->reference_distance_m;
        p.exponent = prop->exponent;
        p.capture_threshold_db = prop->capture_threshold_db;
        p.shadowing_sigma_db = prop->shadowing_sigma_db;
        p.shadowing_seed = prop->shadowing_seed;

        lsim::env::ElevationGrid grid;
        std::vector<lsim::env::Obstacle> obstacles;
        lsim::env::Environment e;
        if (env != nullptr) {
            const int32_t built = build_environment(env, grid, obstacles, e);
            if (built != 0) {
                return built;
            }
        }

        std::vector<lsim::sim::DeviceStats> stats(device_count);
        std::vector<lsim::sim::GatewayRxStats> gstats(gateway_count);
        lsim::sim::NetworkStats tot;
        std::vector<lsim::sim::MultiTx> trace;
        const auto st = lsim::sim::simulate_uplinks_multi(
            specs.data(), device_count, gws.data(), gateway_count, p, stats.data(), tot,
            gstats.data(), env != nullptr ? &e : nullptr,
            record_count != nullptr ? &trace : nullptr,
            busy != nullptr ? &busy_lists : nullptr);
        if (st != lsim::sim::SimStatus::Ok) {
            return LSIM_STATUS_SIM_BASE + static_cast<int32_t>(st);
        }
        if (record_count != nullptr) {
            *record_count = trace.size();
            if (trace.size() > record_capacity) {
                return LSIM_STATUS_SIM_BASE + static_cast<int32_t>(lsim::sim::SimStatus::TraceBufferTooSmall);
            }
            for (size_t k = 0; k < trace.size(); ++k) {
                const lsim::sim::MultiTx& m = trace[k];
                records[k].device_index = m.device;
                records[k].start_ns = m.start_ns;
                records[k].end_ns = m.end_ns;
                records[k].spreading_factor = m.spreading_factor;
                records[k].receivers = m.receivers;
                records[k].best_gateway = m.best_gateway;
                records[k].best_rssi_dbm = m.best_rssi_dbm;
                records[k].outcome = static_cast<uint8_t>(m.outcome);
                records[k].decoded_mask = m.decoded_mask;
            }
        }
        totals->sent = tot.sent;
        totals->received = tot.received;
        totals->duplicates = tot.duplicates;
        totals->lost_sensitivity = tot.lost_sensitivity;
        totals->lost_collision = tot.lost_collision;
        totals->lost_gateway_busy = tot.lost_gateway_busy;
        totals->airtime_ns = tot.airtime_ns;
        for (size_t g = 0; g < gateway_count; ++g) {
            per_gateway[g].received = gstats[g].received;
            per_gateway[g].lost_sensitivity = gstats[g].lost_sensitivity;
            per_gateway[g].lost_collision = gstats[g].lost_collision;
            per_gateway[g].lost_gateway_busy = gstats[g].lost_gateway_busy;
            per_gateway[g].audible_frames = gstats[g].audible_frames;
            per_gateway[g].busy_ns = gstats[g].busy_ns;
            per_gateway[g].peak_concurrent = gstats[g].peak_concurrent;
            per_gateway[g].observation_ns = gstats[g].observation_ns;
        }
        for (size_t i = 0; i < device_count; ++i) {
            per_device[i].sent = stats[i].sent;
            per_device[i].received = stats[i].received;
            per_device[i].lost_sensitivity = stats[i].lost_sensitivity;
            per_device[i].lost_collision = stats[i].lost_collision;
            per_device[i].lost_gateway_busy = stats[i].lost_gateway_busy;
            per_device[i].airtime_ns = stats[i].airtime_ns;
        }
        return 0;
    } catch (...) {
        return LSIM_STATUS_INTERNAL;
    }
}

// ------------------------------------------- Passerelles multiples avec downlinks

int32_t lsim_simulate_uplinks_multi_dl(const lsim_end_device* devices, size_t device_count,
                                       const lsim_gateway* gateways, size_t gateway_count,
                                       const lsim_propagation* prop,
                                       const lsim_downlink_rule* rule, const lsim_environment* env,
                                       lsim_device_stats* per_device, lsim_network_stats* totals,
                                       lsim_gateway_rx_stats* per_gateway,
                                       lsim_multi_tx_record* records, size_t record_capacity,
                                       size_t* record_count, lsim_downlink_record* downlinks,
                                       size_t downlink_capacity, size_t* downlink_count,
                                       const int64_t* dl_ready_ns, size_t ready_count) {
    if (gateways == nullptr || prop == nullptr || rule == nullptr || totals == nullptr ||
        per_gateway == nullptr || record_count == nullptr || downlink_count == nullptr ||
        (device_count > 0 && (devices == nullptr || per_device == nullptr)) ||
        (record_capacity > 0 && records == nullptr) ||
        (downlink_capacity > 0 && downlinks == nullptr)) {
        return static_cast<int32_t>(lsim::lora::Status::NullOutput);
    }
    if (device_count > lsim::sim::kMaxEndDevices) {
        return LSIM_STATUS_SIM_BASE + static_cast<int32_t>(lsim::sim::SimStatus::TooManyDevices);
    }
    if (gateway_count == 0 || gateway_count > lsim::sim::kMaxGateways) {
        return LSIM_STATUS_SIM_BASE + static_cast<int32_t>(lsim::sim::SimStatus::InvalidInput);
    }
    try {
        std::vector<lsim::sim::EndDeviceSpec> specs(device_count);
        for (size_t i = 0; i < device_count; ++i) {
            const lsim_end_device& d = devices[i];
            lsim::sim::EndDeviceSpec& s = specs[i];
            s.position.x_m = d.x_m;
            s.position.y_m = d.y_m;
            s.spreading_factor = d.spreading_factor;
            s.payload_bytes = d.payload_bytes;
            s.tx_power_dbm = d.tx_power_dbm;
            s.start_offset_ns = d.start_offset_ns;
            s.period_ns = d.period_ns;
            s.messages = d.messages;
            s.duty_cycle = d.duty_cycle;
        }
        std::vector<lsim::sim::GatewaySpec> gws(gateway_count);
        for (size_t g = 0; g < gateway_count; ++g) {
            gws[g].position.x_m = gateways[g].x_m;
            gws[g].position.y_m = gateways[g].y_m;
            gws[g].antenna_gain_dbi = gateways[g].antenna_gain_dbi;
            gws[g].rx_sensitivity_offset_db = gateways[g].rx_sensitivity_offset_db;
        }
        lsim::sim::PropagationSpec p;
        p.frequency_hz = prop->frequency_hz;
        p.reference_distance_m = prop->reference_distance_m;
        p.exponent = prop->exponent;
        p.capture_threshold_db = prop->capture_threshold_db;
        p.shadowing_sigma_db = prop->shadowing_sigma_db;
        p.shadowing_seed = prop->shadowing_seed;

        lsim::sim::MultiDownlinkRule r;
        r.ack_uplinks = rule->ack_uplinks != 0;
        r.every = rule->every;
        r.payload_bytes = rule->payload_bytes;
        r.gateway_tx_power_dbm = rule->gateway_tx_power_dbm;
        r.device_antenna_gain_dbi = rule->device_antenna_gain_dbi;
        r.device_rx_offset_db = rule->device_rx_offset_db;
        r.join = rule->join != 0;
        if (rule->rx2_sf != 0 && (rule->rx2_sf < 7 || rule->rx2_sf > 12)) {
            return LSIM_STATUS_SIM_BASE + static_cast<int32_t>(lsim::sim::SimStatus::InvalidInput);
        }
        r.rx2_sf = rule->rx2_sf;

        lsim::env::ElevationGrid grid;
        std::vector<lsim::env::Obstacle> obstacles;
        lsim::env::Environment e;
        if (env != nullptr) {
            const int32_t built = build_environment(env, grid, obstacles, e);
            if (built != 0) {
                return built;
            }
        }

        std::vector<lsim::sim::DeviceStats> stats(device_count);
        std::vector<lsim::sim::GatewayRxStats> gstats(gateway_count);
        lsim::sim::NetworkStats tot;
        std::vector<lsim::sim::MultiTx> trace;
        std::vector<lsim::sim::MultiDownlink> dls;
        size_t total_messages = 0;
        for (const auto& s : specs) total_messages += s.messages;
        if (dl_ready_ns != nullptr && ready_count != total_messages) {
            return LSIM_STATUS_SIM_BASE + static_cast<int32_t>(lsim::sim::SimStatus::InvalidInput);
        }
        const auto st = lsim::sim::simulate_uplinks_multi_downlinks(
            specs.data(), device_count, gws.data(), gateway_count, p, r, stats.data(), tot,
            gstats.data(), env != nullptr ? &e : nullptr, &trace, &dls, dl_ready_ns);
        if (st != lsim::sim::SimStatus::Ok) {
            return LSIM_STATUS_SIM_BASE + static_cast<int32_t>(st);
        }
        *record_count = trace.size();
        *downlink_count = dls.size();
        if (trace.size() > record_capacity || dls.size() > downlink_capacity) {
            return LSIM_STATUS_SIM_BASE + static_cast<int32_t>(lsim::sim::SimStatus::TraceBufferTooSmall);
        }
        for (size_t k = 0; k < trace.size(); ++k) {
            const lsim::sim::MultiTx& m = trace[k];
            records[k].device_index = m.device;
            records[k].start_ns = m.start_ns;
            records[k].end_ns = m.end_ns;
            records[k].spreading_factor = m.spreading_factor;
            records[k].receivers = m.receivers;
            records[k].best_gateway = m.best_gateway;
            records[k].best_rssi_dbm = m.best_rssi_dbm;
            records[k].outcome = static_cast<uint8_t>(m.outcome);
            records[k].decoded_mask = m.decoded_mask;
            records[k].join_request = m.join_request ? 1 : 0;
        }
        for (size_t k = 0; k < dls.size(); ++k) {
            const lsim::sim::MultiDownlink& d = dls[k];
            downlinks[k].device_index = d.device;
            downlinks[k].gateway_index = d.gateway;
            downlinks[k].data = d.data ? 1 : 0;
            downlinks[k].t_open_ns = d.t_open_ns;
            downlinks[k].start_ns = d.start_ns;
            downlinks[k].end_ns = d.end_ns;
            downlinks[k].outcome = static_cast<uint8_t>(d.outcome);
            downlinks[k].join = d.join ? 1 : 0;
            downlinks[k].rx_window = d.rx_window;
        }
        totals->sent = tot.sent;
        totals->received = tot.received;
        totals->duplicates = tot.duplicates;
        totals->lost_sensitivity = tot.lost_sensitivity;
        totals->lost_collision = tot.lost_collision;
        totals->lost_gateway_busy = tot.lost_gateway_busy;
        totals->airtime_ns = tot.airtime_ns;
        for (size_t g = 0; g < gateway_count; ++g) {
            per_gateway[g].received = gstats[g].received;
            per_gateway[g].lost_sensitivity = gstats[g].lost_sensitivity;
            per_gateway[g].lost_collision = gstats[g].lost_collision;
            per_gateway[g].lost_gateway_busy = gstats[g].lost_gateway_busy;
            per_gateway[g].audible_frames = gstats[g].audible_frames;
            per_gateway[g].busy_ns = gstats[g].busy_ns;
            per_gateway[g].peak_concurrent = gstats[g].peak_concurrent;
            per_gateway[g].observation_ns = gstats[g].observation_ns;
        }
        for (size_t i = 0; i < device_count; ++i) {
            per_device[i].sent = stats[i].sent;
            per_device[i].received = stats[i].received;
            per_device[i].lost_sensitivity = stats[i].lost_sensitivity;
            per_device[i].lost_collision = stats[i].lost_collision;
            per_device[i].lost_gateway_busy = stats[i].lost_gateway_busy;
            per_device[i].airtime_ns = stats[i].airtime_ns;
        }
        return 0;
    } catch (...) {
        return LSIM_STATUS_INTERNAL;
    }
}
