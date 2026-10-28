// SPDX-License-Identifier: Apache-2.0
#include "lsim/rejoin.hpp"

#include <cstring>

#include "lsim/constant_time.hpp"

namespace lsim::lorawan {
namespace {

constexpr std::size_t kMicLen = 4;
constexpr std::size_t kMsg02Len = kRejoin02Size - kMicLen;  // 15
constexpr std::size_t kMsg1Len = kRejoin1Size - kMicLen;    // 20

RejoinStatus from_crypto(crypto::CryptoStatus s) {
    return s == crypto::CryptoStatus::Ok ? RejoinStatus::Ok : RejoinStatus::CryptoFailure;
}

// Point unique de calcul du MIC de rejoin : CMAC tronqué à 4 octets.
RejoinStatus compute_rejoin_mic(const crypto::Key128& key, const std::uint8_t* msg, std::size_t len,
                                std::uint8_t* mic) {
    crypto::Block16 tag{};
    const RejoinStatus st = from_crypto(crypto::aes_cmac(key, msg, len, tag));
    if (st != RejoinStatus::Ok) {
        return st;
    }
    std::memcpy(mic, tag.data(), kMicLen);
    return RejoinStatus::Ok;
}

// Écrit `msg` puis le MIC dans `out` (taille totale `total`).
RejoinStatus seal(const std::uint8_t* msg, std::size_t msg_len, const crypto::Key128& key,
                  std::uint8_t* out, std::size_t cap, std::size_t total, std::size_t& out_len) {
    out_len = 0;
    if (cap < total) {
        return RejoinStatus::BufferTooSmall;
    }
    std::uint8_t mic[kMicLen];
    const RejoinStatus st = compute_rejoin_mic(key, msg, msg_len, mic);
    if (st != RejoinStatus::Ok) {
        return st;
    }
    std::memcpy(out, msg, msg_len);
    std::memcpy(out + msg_len, mic, kMicLen);
    out_len = total;
    return RejoinStatus::Ok;
}

// Vérifie le MIC reçu contre le calcul sur `msg_len` premiers octets.
RejoinStatus check(const std::uint8_t* in, std::size_t msg_len, const crypto::Key128& key) {
    std::uint8_t expected[kMicLen];
    const RejoinStatus st = compute_rejoin_mic(key, in, msg_len, expected);
    if (st != RejoinStatus::Ok) {
        return st;
    }
    if (!lsim::constant_time_equal(expected, in + msg_len, kMicLen)) {
        return RejoinStatus::MicMismatch;
    }
    return RejoinStatus::Ok;
}

}  // namespace

RejoinStatus peek_rejoin_type(const std::uint8_t* in, std::size_t len, std::uint8_t& rejoin_type) {
    rejoin_type = 0xFF;
    if (in == nullptr || len < 2) {
        return RejoinStatus::InvalidLength;
    }
    if (in[0] != kMhdrRejoinRequest) {
        return RejoinStatus::InvalidMHDR;
    }
    if (in[1] > 2) {
        return RejoinStatus::InvalidType;
    }
    rejoin_type = in[1];
    return RejoinStatus::Ok;
}

RejoinStatus encode_rejoin_02(const Rejoin02Fields& f, const crypto::Key128& s_nwk_s_int_key,
                              std::uint8_t* out, std::size_t cap, std::size_t& out_len) {
    out_len = 0;
    if (f.rejoin_type != 0 && f.rejoin_type != 2) {
        return RejoinStatus::InvalidType;
    }
    if (out == nullptr) {
        return RejoinStatus::BufferTooSmall;
    }
    std::uint8_t msg[kMsg02Len];
    msg[0] = kMhdrRejoinRequest;
    msg[1] = f.rejoin_type;
    std::memcpy(&msg[2], f.net_id.data(), 3);
    std::memcpy(&msg[5], f.dev_eui.data(), 8);
    msg[13] = static_cast<std::uint8_t>(f.rjcount0 & 0xFFu);
    msg[14] = static_cast<std::uint8_t>(f.rjcount0 >> 8);
    return seal(msg, kMsg02Len, s_nwk_s_int_key, out, cap, kRejoin02Size, out_len);
}

RejoinStatus decode_rejoin_02(const std::uint8_t* in, std::size_t len,
                              const crypto::Key128& s_nwk_s_int_key, Rejoin02Fields& out) {
    if (in == nullptr || len != kRejoin02Size) {
        return RejoinStatus::InvalidLength;
    }
    if (in[0] != kMhdrRejoinRequest) {
        return RejoinStatus::InvalidMHDR;
    }
    if (in[1] != 0 && in[1] != 2) {
        return RejoinStatus::InvalidType;
    }
    const RejoinStatus st = check(in, kMsg02Len, s_nwk_s_int_key);
    if (st != RejoinStatus::Ok) {
        return st;
    }
    out.rejoin_type = in[1];
    std::memcpy(out.net_id.data(), &in[2], 3);
    std::memcpy(out.dev_eui.data(), &in[5], 8);
    out.rjcount0 = static_cast<std::uint16_t>(in[13] | (in[14] << 8));
    return RejoinStatus::Ok;
}

RejoinStatus encode_rejoin_1(const Rejoin1Fields& f, const crypto::Key128& js_int_key,
                             std::uint8_t* out, std::size_t cap, std::size_t& out_len) {
    out_len = 0;
    if (out == nullptr) {
        return RejoinStatus::BufferTooSmall;
    }
    std::uint8_t msg[kMsg1Len];
    msg[0] = kMhdrRejoinRequest;
    msg[1] = 1;
    std::memcpy(&msg[2], f.join_eui.data(), 8);
    std::memcpy(&msg[10], f.dev_eui.data(), 8);
    msg[18] = static_cast<std::uint8_t>(f.rjcount1 & 0xFFu);
    msg[19] = static_cast<std::uint8_t>(f.rjcount1 >> 8);
    return seal(msg, kMsg1Len, js_int_key, out, cap, kRejoin1Size, out_len);
}

RejoinStatus decode_rejoin_1(const std::uint8_t* in, std::size_t len,
                             const crypto::Key128& js_int_key, Rejoin1Fields& out) {
    if (in == nullptr || len != kRejoin1Size) {
        return RejoinStatus::InvalidLength;
    }
    if (in[0] != kMhdrRejoinRequest) {
        return RejoinStatus::InvalidMHDR;
    }
    if (in[1] != 1) {
        return RejoinStatus::InvalidType;
    }
    const RejoinStatus st = check(in, kMsg1Len, js_int_key);
    if (st != RejoinStatus::Ok) {
        return st;
    }
    std::memcpy(out.join_eui.data(), &in[2], 8);
    std::memcpy(out.dev_eui.data(), &in[10], 8);
    out.rjcount1 = static_cast<std::uint16_t>(in[18] | (in[19] << 8));
    return RejoinStatus::Ok;
}

}  // namespace lsim::lorawan
