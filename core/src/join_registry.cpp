// SPDX-License-Identifier: Apache-2.0
#include "lsim/join_registry.hpp"

#include <cstring>

namespace lsim::lorawan {
namespace {

RegistryStatus from_join(JoinStatus s) {
    switch (s) {
        case JoinStatus::Ok: return RegistryStatus::Ok;
        case JoinStatus::MicMismatch: return RegistryStatus::MicMismatch;
        case JoinStatus::CryptoFailure: return RegistryStatus::CryptoFailure;
        default: return RegistryStatus::Malformed;
    }
}

RegistryStatus from_rejoin(RejoinStatus s) {
    switch (s) {
        case RejoinStatus::Ok: return RegistryStatus::Ok;
        case RejoinStatus::MicMismatch: return RegistryStatus::MicMismatch;
        case RejoinStatus::CryptoFailure: return RegistryStatus::CryptoFailure;
        default: return RegistryStatus::Malformed;
    }
}

}  // namespace

JoinRegistry::JoinKey JoinRegistry::make_key(const Eui& join_eui, const Eui& dev_eui) {
    JoinKey k{};
    std::memcpy(k.data(), join_eui.data(), 8);
    std::memcpy(k.data() + 8, dev_eui.data(), 8);
    return k;
}

// Toute écriture d'état a lieu ici, après un MIC valide et un compteur croissant.
RegistryStatus JoinRegistry::accept_join_request(const std::uint8_t* in, std::size_t len,
                                                 const crypto::Key128& nwk_key, JoinRequestFields& out) {
    const JoinStatus st = decode_join_request(in, len, nwk_key, out);  // MIC d'abord
    if (st != JoinStatus::Ok) {
        return from_join(st);
    }
    const auto nonce = static_cast<std::uint16_t>(out.dev_nonce[0] | (out.dev_nonce[1] << 8));
    const JoinKey key = make_key(out.join_eui, out.dev_eui);
    auto it = joins_.find(key);
    if (it == joins_.end()) {
        if (!has_room()) {
            return RegistryStatus::CapacityExceeded;
        }
        it = joins_.emplace(key, JoinState{}).first;
    }
    if (!it->second.dev_nonce.is_fresh(nonce)) {
        return RegistryStatus::Replayed;
    }
    it->second.dev_nonce.record(nonce);
    return RegistryStatus::Ok;
}

RegistryStatus JoinRegistry::accept_rejoin_02(const std::uint8_t* in, std::size_t len,
                                              const crypto::Key128& s_nwk_s_int_key, Rejoin02Fields& out) {
    const RejoinStatus st = decode_rejoin_02(in, len, s_nwk_s_int_key, out);  // MIC d'abord
    if (st != RejoinStatus::Ok) {
        return from_rejoin(st);
    }
    auto it = rjcount0_.find(out.dev_eui);
    if (it == rjcount0_.end()) {
        if (!has_room()) {
            return RegistryStatus::CapacityExceeded;
        }
        it = rjcount0_.emplace(out.dev_eui, Counter16Guard{}).first;
    }
    if (!it->second.is_fresh(out.rjcount0)) {
        return RegistryStatus::Replayed;
    }
    it->second.record(out.rjcount0);
    return RegistryStatus::Ok;
}

RegistryStatus JoinRegistry::accept_rejoin_1(const std::uint8_t* in, std::size_t len,
                                             const crypto::Key128& js_int_key, Rejoin1Fields& out) {
    const RejoinStatus st = decode_rejoin_1(in, len, js_int_key, out);  // MIC d'abord
    if (st != RejoinStatus::Ok) {
        return from_rejoin(st);
    }
    const JoinKey key = make_key(out.join_eui, out.dev_eui);
    auto it = joins_.find(key);
    if (it == joins_.end()) {
        if (!has_room()) {
            return RegistryStatus::CapacityExceeded;
        }
        it = joins_.emplace(key, JoinState{}).first;
    }
    if (!it->second.rjcount1.is_fresh(out.rjcount1)) {
        return RegistryStatus::Replayed;
    }
    it->second.rjcount1.record(out.rjcount1);
    return RegistryStatus::Ok;
}

void JoinRegistry::on_join_accepted(const Eui& dev_eui) {
    const auto it = rjcount0_.find(dev_eui);
    if (it != rjcount0_.end()) {
        it->second.reset();
    }
}

}  // namespace lsim::lorawan
