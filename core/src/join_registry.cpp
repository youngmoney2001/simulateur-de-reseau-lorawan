// SPDX-License-Identifier: Apache-2.0
#include "lsim/join_registry.hpp"

#include <cstring>

#include "lsim/constant_time.hpp"
#include "lsim/crypto.hpp"

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

// ------------------------------------------------------------ persistance
//
// Format (little-endian), version 1 :
//   magic "LSRG" (4) | version u8 = 1 | réservé 3 x 0 | max_devices u32 |
//   join_count u32 | rj0_count u32
//   join_count x [ JoinEUI 8 | DevEUI 8 | nonce_has u8 | DevNonce u16 |
//                  rj1_has u8 | RJcount1 u16 ]                       (22 octets)
//   rj0_count x  [ DevEUI 8 | rj0_has u8 | RJcount0 u16 ]              (11 octets)
//   tag : AES-CMAC(integrity_key, tout ce qui précède), 16 octets.
// Les entrées sont dans l'ordre des clés (std::map) : sortie déterministe.

namespace {

constexpr std::uint8_t kMagic[4] = {'L', 'S', 'R', 'G'};
constexpr std::uint8_t kFormatVersion = 1;
constexpr std::size_t kHeaderLen = 20;
constexpr std::size_t kJoinEntryLen = 22;
constexpr std::size_t kRj0EntryLen = 11;
constexpr std::size_t kTagLen = 16;

void put_u16(std::vector<std::uint8_t>& v, std::uint16_t x) {
    v.push_back(static_cast<std::uint8_t>(x & 0xFFu));
    v.push_back(static_cast<std::uint8_t>(x >> 8));
}

void put_u32(std::vector<std::uint8_t>& v, std::uint32_t x) {
    for (int i = 0; i < 4; ++i) {
        v.push_back(static_cast<std::uint8_t>((x >> (8 * i)) & 0xFFu));
    }
}

std::uint16_t get_u16(const std::uint8_t* p) {
    return static_cast<std::uint16_t>(p[0] | (p[1] << 8));
}

std::uint32_t get_u32(const std::uint8_t* p) {
    return static_cast<std::uint32_t>(p[0]) | (static_cast<std::uint32_t>(p[1]) << 8) |
           (static_cast<std::uint32_t>(p[2]) << 16) | (static_cast<std::uint32_t>(p[3]) << 24);
}

void put_guard(std::vector<std::uint8_t>& v, const Counter16Guard& g) {
    v.push_back(g.has_last() ? 1 : 0);
    put_u16(v, g.has_last() ? g.last() : 0);
}

// Flag canonique (0 ou 1) ; une valeur absente doit valoir 0.
bool read_guard(const std::uint8_t* p, Counter16Guard& out) {
    if (p[0] > 1) {
        return false;
    }
    const std::uint16_t value = get_u16(p + 1);
    if (p[0] == 0 && value != 0) {
        return false;
    }
    out = Counter16Guard::restore(p[0] == 1, value);
    return true;
}

}  // namespace

RegistryStatus JoinRegistry::export_state(const crypto::Key128& integrity_key,
                                          std::vector<std::uint8_t>& out) const {
    out.clear();
    out.reserve(kHeaderLen + kJoinEntryLen * joins_.size() + kRj0EntryLen * rjcount0_.size() + kTagLen);
    out.insert(out.end(), kMagic, kMagic + 4);
    out.push_back(kFormatVersion);
    out.push_back(0);
    out.push_back(0);
    out.push_back(0);
    put_u32(out, static_cast<std::uint32_t>(max_devices_));
    put_u32(out, static_cast<std::uint32_t>(joins_.size()));
    put_u32(out, static_cast<std::uint32_t>(rjcount0_.size()));
    for (const auto& [key, st] : joins_) {
        out.insert(out.end(), key.begin(), key.begin() + 8);      // JoinEUI
        out.insert(out.end(), key.begin() + 8, key.end());        // DevEUI
        put_guard(out, st.dev_nonce);
        put_guard(out, st.rjcount1);
    }
    for (const auto& [eui, g] : rjcount0_) {
        out.insert(out.end(), eui.begin(), eui.end());
        put_guard(out, g);
    }
    crypto::Block16 tag{};
    if (crypto::aes_cmac(integrity_key, out.data(), out.size(), tag) != crypto::CryptoStatus::Ok) {
        out.clear();
        return RegistryStatus::CryptoFailure;
    }
    out.insert(out.end(), tag.begin(), tag.end());
    return RegistryStatus::Ok;
}

RegistryStatus JoinRegistry::import_state(const std::uint8_t* in, std::size_t len,
                                          const crypto::Key128& integrity_key, JoinRegistry& out) {
    if (in == nullptr || len < kHeaderLen + kTagLen) {
        return RegistryStatus::Malformed;
    }
    if (std::memcmp(in, kMagic, 4) != 0 || in[4] != kFormatVersion) {
        return RegistryStatus::UnsupportedFormat;
    }
    // Intégrité d'abord : aucun champ n'est lu avant la vérification du MIC.
    const std::size_t body_len = len - kTagLen;
    crypto::Block16 expected{};
    if (crypto::aes_cmac(integrity_key, in, body_len, expected) != crypto::CryptoStatus::Ok) {
        return RegistryStatus::CryptoFailure;
    }
    if (!lsim::constant_time_equal(expected.data(), in + body_len, kTagLen)) {
        return RegistryStatus::IntegrityFailure;
    }
    const std::uint32_t max = get_u32(in + 8);
    const std::uint32_t nj = get_u32(in + 12);
    const std::uint32_t nr = get_u32(in + 16);
    if (max == 0 || max > kMaxRegistryDevices) {
        return RegistryStatus::CorruptState;
    }
    if (static_cast<std::uint64_t>(nj) + nr > max) {
        return RegistryStatus::CorruptState;
    }
    const std::uint64_t expected_body = kHeaderLen + static_cast<std::uint64_t>(nj) * kJoinEntryLen +
                                        static_cast<std::uint64_t>(nr) * kRj0EntryLen;
    if (expected_body != body_len) {
        return RegistryStatus::CorruptState;
    }
    JoinRegistry fresh(max);
    const std::uint8_t* p = in + kHeaderLen;
    for (std::uint32_t i = 0; i < nj; ++i, p += kJoinEntryLen) {
        JoinKey key{};
        std::memcpy(key.data(), p, 16);
        JoinState st;
        if (!read_guard(p + 16, st.dev_nonce) || !read_guard(p + 19, st.rjcount1)) {
            return RegistryStatus::CorruptState;
        }
        if (!fresh.joins_.emplace(key, st).second) {
            return RegistryStatus::CorruptState;  // doublon
        }
    }
    for (std::uint32_t i = 0; i < nr; ++i, p += kRj0EntryLen) {
        Eui eui{};
        std::memcpy(eui.data(), p, 8);
        Counter16Guard g;
        if (!read_guard(p + 8, g)) {
            return RegistryStatus::CorruptState;
        }
        if (!fresh.rjcount0_.emplace(eui, g).second) {
            return RegistryStatus::CorruptState;
        }
    }
    out = std::move(fresh);  // remplacement seulement après un import complet
    return RegistryStatus::Ok;
}

}  // namespace lsim::lorawan
