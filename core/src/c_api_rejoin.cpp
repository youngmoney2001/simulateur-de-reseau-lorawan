// SPDX-License-Identifier: Apache-2.0
// Surface C du rejoin-request 1.1 (voir lsim/c_api.h). Sans état : le garde anti-rejeu
// reste côté serveur (Counter16Guard). Exceptions interceptées à la frontière.
#include <cstring>

#include "lsim/c_api.h"
#include "lsim/lora_phy.hpp"
#include "lsim/rejoin.hpp"

namespace {

using lsim::crypto::Key128;
using lsim::lorawan::RejoinStatus;

std::int32_t map_rejoin(RejoinStatus s) {
    if (s == RejoinStatus::Ok) {
        return 0;
    }
    return LSIM_STATUS_REJOIN_BASE + static_cast<std::int32_t>(s);
}

Key128 to_key(const uint8_t key[16]) {
    Key128 k;
    std::memcpy(k.data(), key, 16);
    return k;
}

}  // namespace

int32_t lsim_rejoin_encode_02(const lsim_rejoin02* f, const uint8_t key[16], uint8_t out[19]) {
    if (f == nullptr || key == nullptr || out == nullptr) {
        return static_cast<int32_t>(lsim::lora::Status::NullOutput);
    }
    try {
        lsim::lorawan::Rejoin02Fields v;
        v.rejoin_type = f->rejoin_type;
        std::memcpy(v.net_id.data(), f->net_id, 3);
        std::memcpy(v.dev_eui.data(), f->dev_eui, 8);
        v.rjcount0 = f->rjcount0;
        std::size_t n = 0;
        const auto st = lsim::lorawan::encode_rejoin_02(v, to_key(key), out, 19, n);
        if (st != RejoinStatus::Ok) {
            std::memset(out, 0, 19);
        }
        return map_rejoin(st);
    } catch (...) {
        return LSIM_STATUS_INTERNAL;
    }
}

int32_t lsim_rejoin_decode_02(const uint8_t* in, size_t len, const uint8_t key[16], lsim_rejoin02* out) {
    if (in == nullptr || key == nullptr || out == nullptr) {
        return static_cast<int32_t>(lsim::lora::Status::NullOutput);
    }
    std::memset(out, 0, sizeof *out);
    try {
        lsim::lorawan::Rejoin02Fields v;
        const auto st = lsim::lorawan::decode_rejoin_02(in, len, to_key(key), v);
        if (st == RejoinStatus::Ok) {
            out->rejoin_type = v.rejoin_type;
            std::memcpy(out->net_id, v.net_id.data(), 3);
            std::memcpy(out->dev_eui, v.dev_eui.data(), 8);
            out->rjcount0 = v.rjcount0;
        }
        return map_rejoin(st);
    } catch (...) {
        std::memset(out, 0, sizeof *out);
        return LSIM_STATUS_INTERNAL;
    }
}

int32_t lsim_rejoin_encode_1(const lsim_rejoin1* f, const uint8_t key[16], uint8_t out[24]) {
    if (f == nullptr || key == nullptr || out == nullptr) {
        return static_cast<int32_t>(lsim::lora::Status::NullOutput);
    }
    try {
        lsim::lorawan::Rejoin1Fields v;
        std::memcpy(v.join_eui.data(), f->join_eui, 8);
        std::memcpy(v.dev_eui.data(), f->dev_eui, 8);
        v.rjcount1 = f->rjcount1;
        std::size_t n = 0;
        const auto st = lsim::lorawan::encode_rejoin_1(v, to_key(key), out, 24, n);
        if (st != RejoinStatus::Ok) {
            std::memset(out, 0, 24);
        }
        return map_rejoin(st);
    } catch (...) {
        return LSIM_STATUS_INTERNAL;
    }
}

int32_t lsim_rejoin_decode_1(const uint8_t* in, size_t len, const uint8_t key[16], lsim_rejoin1* out) {
    if (in == nullptr || key == nullptr || out == nullptr) {
        return static_cast<int32_t>(lsim::lora::Status::NullOutput);
    }
    std::memset(out, 0, sizeof *out);
    try {
        lsim::lorawan::Rejoin1Fields v;
        const auto st = lsim::lorawan::decode_rejoin_1(in, len, to_key(key), v);
        if (st == RejoinStatus::Ok) {
            std::memcpy(out->join_eui, v.join_eui.data(), 8);
            std::memcpy(out->dev_eui, v.dev_eui.data(), 8);
            out->rjcount1 = v.rjcount1;
        }
        return map_rejoin(st);
    } catch (...) {
        std::memset(out, 0, sizeof *out);
        return LSIM_STATUS_INTERNAL;
    }
}
