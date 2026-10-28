// SPDX-License-Identifier: Apache-2.0
// Surface C du registre serveur : handles entiers, table protégée par verrou,
// un verrou par registre (les appels sur des registres distincts ne se bloquent pas).
#include <cstring>
#include <map>
#include <memory>
#include <mutex>
#include <vector>

#include "lsim/c_api.h"
#include "lsim/join_registry.hpp"
#include "lsim/lora_phy.hpp"

namespace {

using lsim::crypto::Key128;
using lsim::lorawan::RegistryStatus;

struct Entry {
    std::mutex mu;
    lsim::lorawan::JoinRegistry reg;
    explicit Entry(std::size_t max) : reg(max) {}
};

std::mutex g_mu;
std::uint64_t g_next = 1;
std::map<std::uint64_t, std::shared_ptr<Entry>> g_table;

constexpr std::int32_t kUnknownHandle = LSIM_STATUS_REGISTRY_BASE + 40;
constexpr std::int32_t kInvalidParam = LSIM_STATUS_REGISTRY_BASE + 41;

std::int32_t map_registry(RegistryStatus s) {
    if (s == RegistryStatus::Ok) {
        return 0;
    }
    return LSIM_STATUS_REGISTRY_BASE + static_cast<std::int32_t>(s);
}

std::shared_ptr<Entry> lookup(std::uint64_t handle) {
    std::lock_guard<std::mutex> lock(g_mu);
    const auto it = g_table.find(handle);
    return it == g_table.end() ? nullptr : it->second;
}

Key128 to_key(const uint8_t* k) {
    Key128 out;
    std::memcpy(out.data(), k, 16);
    return out;
}

}  // namespace

int32_t lsim_registry_create(uint64_t max_devices, uint64_t* handle) {
    if (handle == nullptr) {
        return static_cast<int32_t>(lsim::lora::Status::NullOutput);
    }
    *handle = 0;
    if (max_devices == 0 || max_devices > lsim::lorawan::kMaxRegistryDevices) {
        return kInvalidParam;
    }
    try {
        std::lock_guard<std::mutex> lock(g_mu);
        if (g_table.size() >= LSIM_REGISTRY_MAX_INSTANCES) {
            return LSIM_STATUS_REGISTRY_BASE + static_cast<std::int32_t>(RegistryStatus::CapacityExceeded);
        }
        const std::uint64_t id = g_next++;
        g_table.emplace(id, std::make_shared<Entry>(static_cast<std::size_t>(max_devices)));
        *handle = id;
        return 0;
    } catch (...) {
        return LSIM_STATUS_INTERNAL;
    }
}

int32_t lsim_registry_destroy(uint64_t handle) {
    try {
        std::lock_guard<std::mutex> lock(g_mu);
        return g_table.erase(handle) == 1 ? 0 : kUnknownHandle;
    } catch (...) {
        return LSIM_STATUS_INTERNAL;
    }
}

int32_t lsim_registry_accept_join_request(uint64_t handle, const uint8_t* in, size_t len,
                                          const uint8_t nwk_key[16], lsim_join_request* out) {
    if (in == nullptr || nwk_key == nullptr || out == nullptr) {
        return static_cast<int32_t>(lsim::lora::Status::NullOutput);
    }
    std::memset(out, 0, sizeof *out);
    const auto e = lookup(handle);
    if (!e) {
        return kUnknownHandle;
    }
    try {
        lsim::lorawan::JoinRequestFields f;
        std::lock_guard<std::mutex> lock(e->mu);
        const auto st = e->reg.accept_join_request(in, len, to_key(nwk_key), f);
        if (st == RegistryStatus::Ok) {
            std::memcpy(out->join_eui, f.join_eui.data(), 8);
            std::memcpy(out->dev_eui, f.dev_eui.data(), 8);
            std::memcpy(out->dev_nonce, f.dev_nonce.data(), 2);
        }
        return map_registry(st);
    } catch (...) {
        std::memset(out, 0, sizeof *out);
        return LSIM_STATUS_INTERNAL;
    }
}

int32_t lsim_registry_accept_rejoin_02(uint64_t handle, const uint8_t* in, size_t len,
                                       const uint8_t s_nwk_s_int_key[16], lsim_rejoin02* out) {
    if (in == nullptr || s_nwk_s_int_key == nullptr || out == nullptr) {
        return static_cast<int32_t>(lsim::lora::Status::NullOutput);
    }
    std::memset(out, 0, sizeof *out);
    const auto e = lookup(handle);
    if (!e) {
        return kUnknownHandle;
    }
    try {
        lsim::lorawan::Rejoin02Fields f;
        std::lock_guard<std::mutex> lock(e->mu);
        const auto st = e->reg.accept_rejoin_02(in, len, to_key(s_nwk_s_int_key), f);
        if (st == RegistryStatus::Ok) {
            out->rejoin_type = f.rejoin_type;
            std::memcpy(out->net_id, f.net_id.data(), 3);
            std::memcpy(out->dev_eui, f.dev_eui.data(), 8);
            out->rjcount0 = f.rjcount0;
        }
        return map_registry(st);
    } catch (...) {
        std::memset(out, 0, sizeof *out);
        return LSIM_STATUS_INTERNAL;
    }
}

int32_t lsim_registry_accept_rejoin_1(uint64_t handle, const uint8_t* in, size_t len,
                                      const uint8_t js_int_key[16], lsim_rejoin1* out) {
    if (in == nullptr || js_int_key == nullptr || out == nullptr) {
        return static_cast<int32_t>(lsim::lora::Status::NullOutput);
    }
    std::memset(out, 0, sizeof *out);
    const auto e = lookup(handle);
    if (!e) {
        return kUnknownHandle;
    }
    try {
        lsim::lorawan::Rejoin1Fields f;
        std::lock_guard<std::mutex> lock(e->mu);
        const auto st = e->reg.accept_rejoin_1(in, len, to_key(js_int_key), f);
        if (st == RegistryStatus::Ok) {
            std::memcpy(out->join_eui, f.join_eui.data(), 8);
            std::memcpy(out->dev_eui, f.dev_eui.data(), 8);
            out->rjcount1 = f.rjcount1;
        }
        return map_registry(st);
    } catch (...) {
        std::memset(out, 0, sizeof *out);
        return LSIM_STATUS_INTERNAL;
    }
}

int32_t lsim_registry_on_join_accepted(uint64_t handle, const uint8_t dev_eui[8]) {
    if (dev_eui == nullptr) {
        return static_cast<int32_t>(lsim::lora::Status::NullOutput);
    }
    const auto e = lookup(handle);
    if (!e) {
        return kUnknownHandle;
    }
    try {
        std::array<std::uint8_t, 8> eui;
        std::memcpy(eui.data(), dev_eui, 8);
        std::lock_guard<std::mutex> lock(e->mu);
        e->reg.on_join_accepted(eui);
        return 0;
    } catch (...) {
        return LSIM_STATUS_INTERNAL;
    }
}

int32_t lsim_registry_device_count(uint64_t handle, uint64_t* count) {
    if (count == nullptr) {
        return static_cast<int32_t>(lsim::lora::Status::NullOutput);
    }
    *count = 0;
    const auto e = lookup(handle);
    if (!e) {
        return kUnknownHandle;
    }
    std::lock_guard<std::mutex> lock(e->mu);
    *count = static_cast<std::uint64_t>(e->reg.device_count());
    return 0;
}

int32_t lsim_registry_export(uint64_t handle, const uint8_t integrity_key[16], uint8_t* out, size_t cap,
                             size_t* out_len) {
    if (integrity_key == nullptr || out_len == nullptr || (out == nullptr && cap > 0)) {
        return static_cast<int32_t>(lsim::lora::Status::NullOutput);
    }
    *out_len = 0;
    const auto e = lookup(handle);
    if (!e) {
        return kUnknownHandle;
    }
    try {
        std::vector<std::uint8_t> blob;
        std::lock_guard<std::mutex> lock(e->mu);
        const auto st = e->reg.export_state(to_key(integrity_key), blob);
        if (st != RegistryStatus::Ok) {
            return map_registry(st);
        }
        *out_len = blob.size();
        if (out == nullptr || cap < blob.size()) {
            return map_registry(RegistryStatus::BufferTooSmall);
        }
        std::memcpy(out, blob.data(), blob.size());
        return 0;
    } catch (...) {
        return LSIM_STATUS_INTERNAL;
    }
}

int32_t lsim_registry_import(const uint8_t integrity_key[16], const uint8_t* in, size_t len,
                             uint64_t* handle) {
    if (integrity_key == nullptr || in == nullptr || handle == nullptr) {
        return static_cast<int32_t>(lsim::lora::Status::NullOutput);
    }
    *handle = 0;
    try {
        lsim::lorawan::JoinRegistry reg;
        const auto st = lsim::lorawan::JoinRegistry::import_state(in, len, to_key(integrity_key), reg);
        if (st != RegistryStatus::Ok) {
            return map_registry(st);
        }
        std::lock_guard<std::mutex> lock(g_mu);
        if (g_table.size() >= LSIM_REGISTRY_MAX_INSTANCES) {
            return map_registry(RegistryStatus::CapacityExceeded);
        }
        const std::uint64_t id = g_next++;
        auto entry = std::make_shared<Entry>(reg.max_devices());
        entry->reg = std::move(reg);
        g_table.emplace(id, std::move(entry));
        *handle = id;
        return 0;
    } catch (...) {
        return LSIM_STATUS_INTERNAL;
    }
}
