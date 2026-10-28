// SPDX-License-Identifier: Apache-2.0
#include "lsim/join.hpp"

#include <mbedtls/platform_util.h>

#include <cstring>

#include "lsim/constant_time.hpp"
#include "lsim/lorawan_keys.hpp"

namespace lsim::lorawan {
namespace {

constexpr std::size_t kMicLen = 4;
constexpr std::size_t kJoinRequestMsgLen = 19;   // MHDR | JoinEUI | DevEUI | DevNonce
constexpr std::size_t kBodyNoCfl = 12;           // JoinNonce | NetID | DevAddr | DLSettings | RxDelay
constexpr std::size_t kBodyCfl = 28;             // + CFList (16)
constexpr std::uint8_t kOptNegMask = 0x80;

bool valid_accept_len(std::size_t len) {
    return len == 13 || len == 29;
}

void wipe(void* p, std::size_t n) {
    mbedtls_platform_zeroize(p, n);
}

void store_le32(std::uint32_t v, std::uint8_t* out) {
    out[0] = static_cast<std::uint8_t>(v);
    out[1] = static_cast<std::uint8_t>(v >> 8);
    out[2] = static_cast<std::uint8_t>(v >> 16);
    out[3] = static_cast<std::uint8_t>(v >> 24);
}

std::uint32_t load_le32(const std::uint8_t* in) {
    return static_cast<std::uint32_t>(in[0]) | (static_cast<std::uint32_t>(in[1]) << 8) |
           (static_cast<std::uint32_t>(in[2]) << 16) | (static_cast<std::uint32_t>(in[3]) << 24);
}

JoinStatus from_crypto(crypto::CryptoStatus s) {
    return s == crypto::CryptoStatus::Ok ? JoinStatus::Ok : JoinStatus::CryptoFailure;
}

}  // namespace

// ----------------------------------------------------------- Join-request

JoinStatus compute_join_request_mic(const crypto::Key128& nwk_key, const std::uint8_t* msg,
                                    std::size_t len, std::array<std::uint8_t, 4>& mic) {
    if (len != kJoinRequestMsgLen || msg == nullptr) {
        return JoinStatus::InvalidLength;
    }
    crypto::Block16 tag{};
    const JoinStatus st = from_crypto(crypto::aes_cmac(nwk_key, msg, len, tag));
    if (st != JoinStatus::Ok) {
        return st;
    }
    std::memcpy(mic.data(), tag.data(), kMicLen);
    return JoinStatus::Ok;
}

JoinStatus encode_join_request(const JoinRequestFields& f, const crypto::Key128& nwk_key,
                               std::uint8_t* out, std::size_t cap, std::size_t& out_written) {
    out_written = 0;
    if (out == nullptr) {
        return JoinStatus::InvalidLength;
    }
    if (cap < kJoinRequestSize) {
        return JoinStatus::BufferTooSmall;
    }
    out[0] = kMhdrJoinRequest;
    std::memcpy(out + 1, f.join_eui.data(), 8);
    std::memcpy(out + 9, f.dev_eui.data(), 8);
    std::memcpy(out + 17, f.dev_nonce.data(), 2);
    std::array<std::uint8_t, 4> mic{};
    const JoinStatus st = compute_join_request_mic(nwk_key, out, kJoinRequestMsgLen, mic);
    if (st != JoinStatus::Ok) {
        return st;
    }
    std::memcpy(out + 19, mic.data(), kMicLen);
    out_written = kJoinRequestSize;
    return JoinStatus::Ok;
}

JoinStatus decode_join_request(const std::uint8_t* in, std::size_t len,
                               const crypto::Key128& nwk_key, JoinRequestFields& out) {
    out = JoinRequestFields{};
    if (in == nullptr || len != kJoinRequestSize) {
        return JoinStatus::InvalidLength;
    }
    if (in[0] != kMhdrJoinRequest) {
        return JoinStatus::InvalidMHDR;
    }
    std::array<std::uint8_t, 4> expected{};
    const JoinStatus st = compute_join_request_mic(nwk_key, in, kJoinRequestMsgLen, expected);
    if (st != JoinStatus::Ok) {
        return st;
    }
    if (!lsim::constant_time_equal(expected.data(), in + 19, kMicLen)) {
        return JoinStatus::MicMismatch;
    }
    std::memcpy(out.join_eui.data(), in + 1, 8);
    std::memcpy(out.dev_eui.data(), in + 9, 8);
    std::memcpy(out.dev_nonce.data(), in + 17, 2);
    return JoinStatus::Ok;
}

// ----------------------------------------------------------- Join-accept

JoinStatus join_accept_encrypt(const crypto::Key128& key, std::uint8_t* data, std::size_t len) {
    if (data == nullptr || (len != 16 && len != 32)) {
        return JoinStatus::InvalidLength;
    }
    for (std::size_t i = 0; i < len; i += 16) {
        crypto::Block16 in{}, out{};
        std::memcpy(in.data(), data + i, 16);
        const JoinStatus st = from_crypto(crypto::aes128_decrypt_block(key, in, out));
        if (st != JoinStatus::Ok) {
            wipe(data, len);
            return st;
        }
        std::memcpy(data + i, out.data(), 16);
    }
    return JoinStatus::Ok;
}

JoinStatus join_accept_decrypt(const crypto::Key128& key, std::uint8_t* data, std::size_t len) {
    if (data == nullptr || (len != 16 && len != 32)) {
        return JoinStatus::InvalidLength;
    }
    for (std::size_t i = 0; i < len; i += 16) {
        crypto::Block16 in{}, out{};
        std::memcpy(in.data(), data + i, 16);
        const JoinStatus st = from_crypto(crypto::aes128_encrypt_block(key, in, out));
        if (st != JoinStatus::Ok) {
            wipe(data, len);
            return st;
        }
        std::memcpy(data + i, out.data(), 16);
    }
    return JoinStatus::Ok;
}

JoinStatus compute_join_accept_mic_11(const crypto::Key128& js_int_key, std::uint8_t join_req_type,
                                      const std::array<std::uint8_t, 8>& join_eui,
                                      const std::array<std::uint8_t, 2>& dev_nonce,
                                      const std::uint8_t* msg, std::size_t len,
                                      std::array<std::uint8_t, 4>& mic) {
    if (msg == nullptr || !valid_accept_len(len)) {
        return JoinStatus::InvalidLength;
    }
    // JoinReqType | JoinEUI | DevNonce | MHDR | ... (ordre de transmission)
    std::array<std::uint8_t, 1 + 8 + 2 + 29> buf{};
    buf[0] = join_req_type;
    std::memcpy(buf.data() + 1, join_eui.data(), 8);
    std::memcpy(buf.data() + 9, dev_nonce.data(), 2);
    std::memcpy(buf.data() + 11, msg, len);
    crypto::Block16 tag{};
    const JoinStatus st = from_crypto(crypto::aes_cmac(js_int_key, buf.data(), 11 + len, tag));
    if (st != JoinStatus::Ok) {
        return st;
    }
    std::memcpy(mic.data(), tag.data(), kMicLen);
    return JoinStatus::Ok;
}

JoinStatus compute_join_accept_mic_legacy(const crypto::Key128& key, const std::uint8_t* msg,
                                          std::size_t len, std::array<std::uint8_t, 4>& mic) {
    if (msg == nullptr || !valid_accept_len(len)) {
        return JoinStatus::InvalidLength;
    }
    crypto::Block16 tag{};
    const JoinStatus st = from_crypto(crypto::aes_cmac(key, msg, len, tag));
    if (st != JoinStatus::Ok) {
        return st;
    }
    std::memcpy(mic.data(), tag.data(), kMicLen);
    return JoinStatus::Ok;
}

JoinStatus encode_join_accept(const JoinAcceptFields& f, const crypto::Key128& nwk_key,
                              const std::array<std::uint8_t, 8>& dev_eui,
                              const std::array<std::uint8_t, 8>& join_eui,
                              const std::array<std::uint8_t, 2>& dev_nonce, std::uint8_t* out,
                              std::size_t cap, std::size_t& out_written) {
    out_written = 0;
    if (out == nullptr) {
        return JoinStatus::InvalidLength;
    }
    const std::size_t body_len = f.has_cflist ? kBodyCfl : kBodyNoCfl;
    const std::size_t wire_len = 1 + body_len + kMicLen;
    if (cap < wire_len) {
        return JoinStatus::BufferTooSmall;
    }

    // Message clair : MHDR | corps (MIC non inclus).
    std::array<std::uint8_t, 1 + kBodyCfl> msg{};
    msg[0] = kMhdrJoinAccept;
    std::memcpy(msg.data() + 1, f.join_nonce.data(), 3);
    std::memcpy(msg.data() + 4, f.net_id.data(), 3);
    store_le32(f.dev_addr, msg.data() + 7);
    msg[11] = f.dl_settings;
    msg[12] = f.rx_delay;
    if (f.has_cflist) {
        std::memcpy(msg.data() + 13, f.cflist.data(), 16);
    }
    const std::size_t msg_len = 1 + body_len;

    // OptNeg = 1 (1.1) : MIC avec JSIntKey ; sinon MIC 1.0.x avec NwkKey.
    std::array<std::uint8_t, 4> mic{};
    JoinStatus st = JoinStatus::Ok;
    if ((f.dl_settings & kOptNegMask) != 0) {
        JoinKeys jk{};
        if (derive_join_keys(nwk_key, dev_eui, jk) != crypto::CryptoStatus::Ok) {
            return JoinStatus::CryptoFailure;
        }
        st = compute_join_accept_mic_11(jk.js_int_key, kJoinReqTypeJoin, join_eui, dev_nonce,
                                        msg.data(), msg_len, mic);
        wipe(&jk, sizeof jk);
    } else {
        st = compute_join_accept_mic_legacy(nwk_key, msg.data(), msg_len, mic);
    }
    if (st != JoinStatus::Ok) {
        return st;
    }

    // Chiffrement : corps | MIC, chiffré avec NwkKey (AES déchiffrement).
    std::array<std::uint8_t, kBodyCfl + kMicLen> enc{};
    std::memcpy(enc.data(), msg.data() + 1, body_len);
    std::memcpy(enc.data() + body_len, mic.data(), kMicLen);
    const std::size_t enc_len = body_len + kMicLen;  // 16 ou 32
    st = join_accept_encrypt(nwk_key, enc.data(), enc_len);
    if (st == JoinStatus::Ok) {
        out[0] = kMhdrJoinAccept;
        std::memcpy(out + 1, enc.data(), enc_len);
        out_written = wire_len;
    }
    wipe(enc.data(), enc.size());
    wipe(msg.data(), msg.size());
    return st;
}

JoinStatus decode_join_accept(const std::uint8_t* in, std::size_t len,
                              const crypto::Key128& nwk_key,
                              const std::array<std::uint8_t, 8>& dev_eui,
                              const std::array<std::uint8_t, 8>& join_eui,
                              const std::array<std::uint8_t, 2>& dev_nonce, JoinAcceptFields& out) {
    out = JoinAcceptFields{};
    if (in == nullptr || (len != kJoinAcceptSizeNoCfl && len != kJoinAcceptSizeCfl)) {
        return JoinStatus::InvalidLength;
    }
    if (in[0] != kMhdrJoinAccept) {
        return JoinStatus::InvalidMHDR;
    }
    const std::size_t enc_len = len - 1;  // 16 ou 32
    const std::size_t body_len = enc_len - kMicLen;

    std::array<std::uint8_t, kBodyCfl + kMicLen> dec{};
    std::memcpy(dec.data(), in + 1, enc_len);
    JoinStatus st = join_accept_decrypt(nwk_key, dec.data(), enc_len);
    if (st != JoinStatus::Ok) {
        wipe(dec.data(), dec.size());
        return st;
    }

    // Message reconstitué pour le MIC : MHDR | corps.
    std::array<std::uint8_t, 1 + kBodyCfl> msg{};
    msg[0] = kMhdrJoinAccept;
    std::memcpy(msg.data() + 1, dec.data(), body_len);
    const std::size_t msg_len = 1 + body_len;
    const std::uint8_t dl = dec[10];

    std::array<std::uint8_t, 4> expected{};
    if ((dl & kOptNegMask) != 0) {
        JoinKeys jk{};
        if (derive_join_keys(nwk_key, dev_eui, jk) != crypto::CryptoStatus::Ok) {
            wipe(dec.data(), dec.size());
            return JoinStatus::CryptoFailure;
        }
        st = compute_join_accept_mic_11(jk.js_int_key, kJoinReqTypeJoin, join_eui, dev_nonce,
                                        msg.data(), msg_len, expected);
        wipe(&jk, sizeof jk);
    } else {
        st = compute_join_accept_mic_legacy(nwk_key, msg.data(), msg_len, expected);
    }
    if (st != JoinStatus::Ok) {
        wipe(dec.data(), dec.size());
        return st;
    }
    if (!lsim::constant_time_equal(expected.data(), dec.data() + body_len, kMicLen)) {
        wipe(dec.data(), dec.size());
        return JoinStatus::MicMismatch;
    }

    JoinAcceptFields f;
    std::memcpy(f.join_nonce.data(), dec.data(), 3);
    std::memcpy(f.net_id.data(), dec.data() + 3, 3);
    f.dev_addr = load_le32(dec.data() + 6);
    f.dl_settings = dl;
    f.rx_delay = dec[11];
    f.has_cflist = body_len == kBodyCfl;
    if (f.has_cflist) {
        std::memcpy(f.cflist.data(), dec.data() + 12, 16);
    }
    out = f;
    wipe(dec.data(), dec.size());
    return JoinStatus::Ok;
}

}  // namespace lsim::lorawan
