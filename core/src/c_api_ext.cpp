// SPDX-License-Identifier: Apache-2.0
// Fonctions C de la crypto 1.1, de la trame sécurisée et du simulateur.
// Chaque fonction intercepte les exceptions : aucune ne traverse la frontière C.
#include <array>
#include <cstring>
#include <vector>

#include "lsim/c_api.h"
#include "lsim/engine.hpp"
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
    // FOpts : non exposés par l'API C, toujours vides.
    out.fopts_len = 0;
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
    std::memcpy(out.mic, in.mic.data(), 4);
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
    if (frame->payload_len > lsim::lorawan::kMaxFrmPayload) {
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
        }
        lsim::sim::GatewaySpec g;
        g.position.x_m = gateway->x_m;
        g.position.y_m = gateway->y_m;
        g.antenna_gain_dbi = gateway->antenna_gain_dbi;

        lsim::sim::PropagationSpec p;
        p.frequency_hz = prop->frequency_hz;
        p.reference_distance_m = prop->reference_distance_m;
        p.exponent = prop->exponent;
        p.capture_threshold_db = prop->capture_threshold_db;

        std::vector<lsim::sim::DeviceStats> stats(device_count);
        lsim::sim::SimulationStats tot;
        const auto st = lsim::sim::simulate_uplinks(specs.data(), device_count, g, p,
                                                    stats.data(), tot);
        totals->sent = tot.sent;
        totals->received = tot.received;
        totals->lost_sensitivity = tot.lost_sensitivity;
        totals->lost_collision = tot.lost_collision;
        for (size_t i = 0; i < device_count; ++i) {
            per_device[i].sent = stats[i].sent;
            per_device[i].received = stats[i].received;
            per_device[i].lost_sensitivity = stats[i].lost_sensitivity;
            per_device[i].lost_collision = stats[i].lost_collision;
        }
        if (st == lsim::sim::SimStatus::Ok) {
            return 0;
        }
        return LSIM_STATUS_SIM_BASE + static_cast<int32_t>(st);
    } catch (...) {
        return LSIM_STATUS_INTERNAL;
    }
}

}  // extern "C"
