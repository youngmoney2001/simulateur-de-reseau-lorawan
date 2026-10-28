// SPDX-License-Identifier: Apache-2.0
// Surface C du moteur de session : handles entiers, un verrou par session.
#include <cstring>
#include <map>
#include <memory>
#include <mutex>

#include "lsim/c_api.h"
#include "lsim/lora_phy.hpp"
#include "lsim/session.hpp"

namespace {

using lsim::lorawan::session::Session;
using lsim::lorawan::session::SessionStatus;

struct Entry {
    std::mutex mu;
    Session s;
};

std::mutex g_mu;
uint64_t g_next = 1;
std::map<uint64_t, std::shared_ptr<Entry>> g_table;

constexpr int32_t kUnknownHandle = LSIM_STATUS_SESSION_BASE + 6;
constexpr int32_t kInvalidParam = LSIM_STATUS_SESSION_BASE + static_cast<int32_t>(SessionStatus::InvalidParameter);

int32_t map_status(SessionStatus s) {
    return s == SessionStatus::Ok ? 0 : LSIM_STATUS_SESSION_BASE + static_cast<int32_t>(s);
}

std::shared_ptr<Entry> lookup(uint64_t handle) {
    std::lock_guard<std::mutex> lock(g_mu);
    const auto it = g_table.find(handle);
    return it == g_table.end() ? nullptr : it->second;
}

}  // namespace

int32_t lsim_session_create(uint64_t* handle) {
    if (handle == nullptr) return static_cast<int32_t>(lsim::lora::Status::NullOutput);
    *handle = 0;
    try {
        std::lock_guard<std::mutex> lock(g_mu);
        const uint64_t id = g_next++;
        g_table.emplace(id, std::make_shared<Entry>());
        *handle = id;
        return 0;
    } catch (...) {
        return LSIM_STATUS_INTERNAL;
    }
}

int32_t lsim_session_destroy(uint64_t handle) {
    try {
        std::lock_guard<std::mutex> lock(g_mu);
        return g_table.erase(handle) == 1 ? 0 : kUnknownHandle;
    } catch (...) {
        return LSIM_STATUS_INTERNAL;
    }
}

int32_t lsim_session_join_accepted(uint64_t handle, const lsim_session_keys* keys, uint32_t dev_addr,
                                   uint8_t dr, uint8_t min_dr, uint8_t tx_power_index,
                                   uint8_t default_tx_power_index) {
    if (keys == nullptr) return static_cast<int32_t>(lsim::lora::Status::NullOutput);
    auto e = lookup(handle);
    if (!e) return kUnknownHandle;
    lsim::lorawan::SessionKeys11 k;
    std::memcpy(k.f_nwk_s_int_key.data(), keys->f_nwk_s_int_key, 16);
    std::memcpy(k.s_nwk_s_int_key.data(), keys->s_nwk_s_int_key, 16);
    std::memcpy(k.nwk_s_enc_key.data(), keys->nwk_s_enc_key, 16);
    std::memcpy(k.app_s_key.data(), keys->app_s_key, 16);
    lsim::lorawan::session::InitParams p;
    p.dev_addr = dev_addr;
    p.dr = dr;
    p.min_dr = min_dr;
    p.tx_power_index = tx_power_index;
    p.default_tx_power_index = default_tx_power_index;
    std::lock_guard<std::mutex> lock(e->mu);
    return map_status(e->s.join_accepted(k, p));
}

int32_t lsim_session_begin_uplink(uint64_t handle, uint8_t limit_exp, uint8_t delay_exp,
                                  lsim_session_uplink_plan* plan) {
    if (plan == nullptr) return static_cast<int32_t>(lsim::lora::Status::NullOutput);
    auto e = lookup(handle);
    if (!e) return kUnknownHandle;
    lsim::lorawan::session::UplinkPlan p;
    std::lock_guard<std::mutex> lock(e->mu);
    const auto st = e->s.begin_uplink(limit_exp, delay_exp, p);
    if (st != SessionStatus::Ok) return map_status(st);
    plan->fcnt32 = p.fcnt32;
    plan->rekey_ind = p.rekey_ind ? 1 : 0;
    plan->ack_req = p.ack_req ? 1 : 0;
    plan->default_channels_reenabled = p.default_channels_reenabled ? 1 : 0;
    return 0;
}

int32_t lsim_session_receive_downlink(uint64_t handle, uint8_t uses_nf, uint32_t fcnt32,
                                      uint8_t conf_received, uint8_t server_version) {
    auto e = lookup(handle);
    if (!e) return kUnknownHandle;
    lsim::lorawan::session::DownlinkInfo d;
    d.uses_nf = uses_nf != 0;
    d.fcnt32 = fcnt32;
    d.conf_received = conf_received != 0;
    d.server_version = server_version;
    std::lock_guard<std::mutex> lock(e->mu);
    return map_status(e->s.receive_downlink(d));
}

int32_t lsim_session_end_uplink(uint64_t handle, lsim_session_uplink_end* out) {
    if (out == nullptr) return static_cast<int32_t>(lsim::lora::Status::NullOutput);
    auto e = lookup(handle);
    if (!e) return kUnknownHandle;
    lsim::lorawan::session::UplinkEnd u;
    std::lock_guard<std::mutex> lock(e->mu);
    const auto st = e->s.end_uplink(u);
    if (st != SessionStatus::Ok) return map_status(st);
    out->state = static_cast<uint8_t>(u.state);
    return 0;
}

int32_t lsim_session_snapshot(uint64_t handle, lsim_session_info* out) {
    if (out == nullptr) return static_cast<int32_t>(lsim::lora::Status::NullOutput);
    auto e = lookup(handle);
    if (!e) return kUnknownHandle;
    std::lock_guard<std::mutex> lock(e->mu);
    const auto s = e->s.snapshot();
    out->state = static_cast<uint8_t>(s.state);
    out->dev_addr = s.dev_addr;
    out->fcnt_up = s.fcnt_up;
    out->nf_cnt_dwn = s.nf_cnt_dwn;
    out->af_cnt_dwn = s.af_cnt_dwn;
    out->dr = s.dr;
    out->tx_power_index = s.tx_power_index;
    out->ack_cnt = s.ack_cnt;
    out->cycle_open = s.cycle_open ? 1 : 0;
    return 0;
}
