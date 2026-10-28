// SPDX-License-Identifier: Apache-2.0
// Surface C du rekey : états passés par l'appelant (aucun état caché).
#include "lsim/c_api.h"
#include "lsim/lora_phy.hpp"
#include "lsim/rekey.hpp"

namespace {
int32_t null_out() { return static_cast<int32_t>(lsim::lora::Status::NullOutput); }
}  // namespace

int32_t lsim_rekey_device_join_accepted(lsim_rekey_device* d) {
    if (d == nullptr) return null_out();
    lsim::lorawan::rekey::DeviceRekey v;
    v.state = static_cast<lsim::lorawan::rekey::DeviceState>(d->state);
    v.uplinks = d->uplinks;
    lsim::lorawan::rekey::device_join_accepted(v);
    d->state = static_cast<uint8_t>(v.state);
    d->uplinks = v.uplinks;
    return 0;
}

int32_t lsim_rekey_device_uplink_completed(lsim_rekey_device* d, uint64_t admin_limit, uint8_t conf_received,
                                           uint8_t server_version) {
    if (d == nullptr) return null_out();
    lsim::lorawan::rekey::DeviceRekey v;
    v.state = static_cast<lsim::lorawan::rekey::DeviceState>(d->state);
    v.uplinks = d->uplinks;
    lsim::lorawan::rekey::device_uplink_completed(v, admin_limit, conf_received != 0, server_version);
    d->state = static_cast<uint8_t>(v.state);
    d->uplinks = v.uplinks;
    return 0;
}

int32_t lsim_rekey_device_must_send_rekey_ind(const lsim_rekey_device* d, uint8_t* out) {
    if (d == nullptr || out == nullptr) return null_out();
    lsim::lorawan::rekey::DeviceRekey v;
    v.state = static_cast<lsim::lorawan::rekey::DeviceState>(d->state);
    *out = lsim::lorawan::rekey::device_must_send_rekey_ind(v) ? 1 : 0;
    return 0;
}

int32_t lsim_rekey_server_join_accepted(lsim_rekey_server* s) {
    if (s == nullptr) return null_out();
    s->awaiting = 1;
    return 0;
}

int32_t lsim_rekey_server_on_uplink(lsim_rekey_server* s, uint8_t new_context, uint8_t has_rekey_ind,
                                    uint8_t* action) {
    if (s == nullptr || action == nullptr) return null_out();
    lsim::lorawan::rekey::ServerRekey v;
    v.awaiting = s->awaiting != 0;
    const auto a = lsim::lorawan::rekey::server_on_uplink(v, new_context != 0, has_rekey_ind != 0);
    s->awaiting = v.awaiting ? 1 : 0;
    *action = static_cast<uint8_t>(a);
    return 0;
}
