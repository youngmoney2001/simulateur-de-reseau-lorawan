// SPDX-License-Identifier: Apache-2.0
#include "lsim/secure_frame.hpp"

#include "lsim/constant_time.hpp"

#include <array>

#include <mbedtls/platform_util.h>

namespace lsim::lorawan {
namespace {

SecureStatus from_frame(FrameStatus s) {
    switch (s) {
        case FrameStatus::Ok:
            return SecureStatus::Ok;
        case FrameStatus::BufferTooSmall:
            return SecureStatus::BufferTooSmall;
        default:
            return SecureStatus::Frame;
    }
}

// Clé de chiffrement selon le port : NwkSEncKey pour le port 0, AppSKey sinon.
const crypto::Key128& payload_key(const SessionKeys11& keys, std::uint8_t fport) {
    return fport == 0 ? keys.nwk_s_enc_key : keys.app_s_key;
}

}  // namespace

SecureStatus seal_uplink(const DataFrame& frame, const SessionKeys11& keys,
                         const UplinkContext& ctx, std::uint8_t* out, std::size_t cap,
                         std::size_t& out_written) {
    out_written = 0;
    // Travail sur une copie : le texte clair de l'appelant n'est pas modifié.
    DataFrame work = frame;
    work.mic = {0, 0, 0, 0};

    if (work.has_fport && work.frm_payload_len > 0) {
        const crypto::CryptoStatus st = crypto::crypt_frm_payload(
            payload_key(keys, work.fport), crypto::Direction::Uplink, work.dev_addr, ctx.fcnt32,
            work.frm_payload.data(), work.frm_payload_len);
        if (st != crypto::CryptoStatus::Ok) {
            mbedtls_platform_zeroize(work.frm_payload.data(), work.frm_payload.size());
            return SecureStatus::CryptoFailure;
        }
    }

    // FOpts (LoRaWAN 1.1) : chiffrés avec NwkSEncKey, compteur FCntUp (constante 1).
    if (work.fopts_len > 0) {
        const crypto::CryptoStatus fst = crypto::crypt_fopts(
            keys.nwk_s_enc_key, crypto::Direction::Uplink, work.dev_addr, ctx.fcnt32,
            crypto::FOptsCounter::FCntUpOrNFCntDwn, work.fopts.data(), work.fopts_len);
        if (fst != crypto::CryptoStatus::Ok) {
            mbedtls_platform_zeroize(work.frm_payload.data(), work.frm_payload.size());
            return SecureStatus::CryptoFailure;
        }
    }

    std::size_t n = 0;
    const FrameStatus enc = encode(work, out, cap, n);
    if (enc != FrameStatus::Ok) {
        mbedtls_platform_zeroize(work.frm_payload.data(), work.frm_payload.size());
        return from_frame(enc);
    }

    // MIC 1.1 sur tout le message (MHDR | FHDR | FPort | FRMPayload).
    const std::size_t msg_len = n - kMicSize;
    std::array<std::uint8_t, 4> mic{};
    const crypto::CryptoStatus st = crypto::compute_uplink_mic_11(
        keys.s_nwk_s_int_key, keys.f_nwk_s_int_key, ctx.conf_fcnt, ctx.tx_dr, ctx.tx_ch,
        work.dev_addr, ctx.fcnt32, out, msg_len, mic);
    mbedtls_platform_zeroize(work.frm_payload.data(), work.frm_payload.size());
    if (st != crypto::CryptoStatus::Ok) {
        return SecureStatus::CryptoFailure;
    }
    for (std::size_t i = 0; i < 4; ++i) {
        out[msg_len + i] = mic[i];
    }
    out_written = n;
    return SecureStatus::Ok;
}

SecureStatus open_uplink(const std::uint8_t* in, std::size_t len, const SessionKeys11& keys,
                         const UplinkContext& ctx, DataFrame& out) {
    const FrameStatus dec = decode(in, len, out);
    if (dec != FrameStatus::Ok) {
        return from_frame(dec);
    }
    // Le compteur 32 bits doit être cohérent avec les 16 bits transmis.
    if (out.fcnt != static_cast<std::uint16_t>(ctx.fcnt32 & 0xFFFFu)) {
        return SecureStatus::FCntMismatch;
    }

    // 1) Vérification du MIC AVANT tout déchiffrement.
    if (len < kMinDataFrame) {
        return SecureStatus::Frame;
    }
    const std::size_t msg_len = len - kMicSize;
    std::array<std::uint8_t, 4> expected{};
    const crypto::CryptoStatus st = crypto::compute_uplink_mic_11(
        keys.s_nwk_s_int_key, keys.f_nwk_s_int_key, ctx.conf_fcnt, ctx.tx_dr, ctx.tx_ch,
        out.dev_addr, ctx.fcnt32, in, msg_len, expected);
    if (st != crypto::CryptoStatus::Ok) {
        return SecureStatus::CryptoFailure;
    }
    if (!lsim::constant_time_equal(expected.data(), out.mic.data(), 4)) {
        // Ne rien exposer d'une trame non authentifiée.
        mbedtls_platform_zeroize(out.frm_payload.data(), out.frm_payload.size());
        out.frm_payload_len = 0;
        mbedtls_platform_zeroize(out.fopts.data(), out.fopts.size());
        out.fopts_len = 0;
        return SecureStatus::MicMismatch;
    }

    // 2) Déchiffrement seulement si le MIC est authentique.
    if (out.fopts_len > 0) {
        const crypto::CryptoStatus fst = crypto::crypt_fopts(
            keys.nwk_s_enc_key, crypto::Direction::Uplink, out.dev_addr, ctx.fcnt32,
            crypto::FOptsCounter::FCntUpOrNFCntDwn, out.fopts.data(), out.fopts_len);
        if (fst != crypto::CryptoStatus::Ok) {
            mbedtls_platform_zeroize(out.fopts.data(), out.fopts.size());
            return SecureStatus::CryptoFailure;
        }
    }
    if (out.has_fport && out.frm_payload_len > 0) {
        const crypto::CryptoStatus dst = crypto::crypt_frm_payload(
            payload_key(keys, out.fport), crypto::Direction::Uplink, out.dev_addr, ctx.fcnt32,
            out.frm_payload.data(), out.frm_payload_len);
        if (dst != crypto::CryptoStatus::Ok) {
            mbedtls_platform_zeroize(out.frm_payload.data(), out.frm_payload.size());
            return SecureStatus::CryptoFailure;
        }
    }
    return SecureStatus::Ok;
}

namespace {

// Compteur downlink retenu : AFCntDwn pour FPort > 0, NFCntDwn sinon.
std::uint32_t downlink_counter(const DataFrame& f, const DownlinkContext& ctx) {
    return (f.has_fport && f.fport > 0) ? ctx.afcnt32 : ctx.nfcnt32;
}

crypto::FOptsCounter downlink_fopts_kind(const DataFrame& f) {
    return (f.has_fport && f.fport > 0) ? crypto::FOptsCounter::AFCntDwn
                                        : crypto::FOptsCounter::FCntUpOrNFCntDwn;
}

}  // namespace

SecureStatus seal_downlink(const DataFrame& frame, const SessionKeys11& keys,
                           const DownlinkContext& ctx, std::uint8_t* out, std::size_t cap,
                           std::size_t& out_written) {
    out_written = 0;
    DataFrame work = frame;
    work.mic = {0, 0, 0, 0};
    // La direction est imposée par la fonction : MHDR downlink quel que soit l'entrée.
    if (work.mtype == MType::UnconfirmedDataUp) work.mtype = MType::UnconfirmedDataDown;
    if (work.mtype == MType::ConfirmedDataUp) work.mtype = MType::ConfirmedDataDown;
    if (work.mtype != MType::UnconfirmedDataDown && work.mtype != MType::ConfirmedDataDown) {
        return SecureStatus::Frame;
    }
    const std::uint32_t counter = downlink_counter(work, ctx);

    if (work.fopts_len > 0) {
        if (crypto::crypt_fopts(keys.nwk_s_enc_key, crypto::Direction::Downlink, work.dev_addr,
                                counter, downlink_fopts_kind(work), work.fopts.data(),
                                work.fopts_len) != crypto::CryptoStatus::Ok) {
            mbedtls_platform_zeroize(work.fopts.data(), work.fopts.size());
            return SecureStatus::CryptoFailure;
        }
    }
    if (work.has_fport && work.frm_payload_len > 0) {
        if (crypto::crypt_frm_payload(payload_key(keys, work.fport), crypto::Direction::Downlink,
                                      work.dev_addr, counter, work.frm_payload.data(),
                                      work.frm_payload_len) != crypto::CryptoStatus::Ok) {
            mbedtls_platform_zeroize(work.frm_payload.data(), work.frm_payload.size());
            mbedtls_platform_zeroize(work.fopts.data(), work.fopts.size());
            return SecureStatus::CryptoFailure;
        }
    }

    std::size_t n = 0;
    const FrameStatus enc = encode(work, out, cap, n);
    mbedtls_platform_zeroize(work.frm_payload.data(), work.frm_payload.size());
    mbedtls_platform_zeroize(work.fopts.data(), work.fopts.size());
    if (enc != FrameStatus::Ok) {
        return from_frame(enc);
    }
    const std::size_t msg_len = n - kMicSize;
    std::array<std::uint8_t, 4> mic{};
    if (crypto::compute_downlink_mic_11(keys.s_nwk_s_int_key, ctx.conf_fcnt, work.dev_addr,
                                        counter, out, msg_len, mic) != crypto::CryptoStatus::Ok) {
        return SecureStatus::CryptoFailure;
    }
    for (std::size_t i = 0; i < 4; ++i) {
        out[msg_len + i] = mic[i];
    }
    out_written = n;
    return SecureStatus::Ok;
}

SecureStatus open_downlink(const std::uint8_t* in, std::size_t len, const SessionKeys11& keys,
                           const DownlinkContext& ctx, DataFrame& out) {
    const FrameStatus dec = decode(in, len, out);
    if (dec != FrameStatus::Ok) {
        return from_frame(dec);
    }
    if (out.mtype != MType::UnconfirmedDataDown && out.mtype != MType::ConfirmedDataDown) {
        return SecureStatus::Frame;  // pas une trame downlink
    }
    const std::uint32_t counter = downlink_counter(out, ctx);
    if (out.fcnt != static_cast<std::uint16_t>(counter & 0xFFFFu)) {
        return SecureStatus::FCntMismatch;
    }
    if (len < kMinDataFrame) {
        return SecureStatus::Frame;
    }

    // 1) MIC vérifié avant tout déchiffrement.
    const std::size_t msg_len = len - kMicSize;
    std::array<std::uint8_t, 4> expected{};
    if (crypto::compute_downlink_mic_11(keys.s_nwk_s_int_key, ctx.conf_fcnt, out.dev_addr,
                                        counter, in, msg_len, expected) != crypto::CryptoStatus::Ok) {
        return SecureStatus::CryptoFailure;
    }
    if (!lsim::constant_time_equal(expected.data(), out.mic.data(), 4)) {
        mbedtls_platform_zeroize(out.frm_payload.data(), out.frm_payload.size());
        out.frm_payload_len = 0;
        mbedtls_platform_zeroize(out.fopts.data(), out.fopts.size());
        out.fopts_len = 0;
        return SecureStatus::MicMismatch;
    }

    // 2) Déchiffrement seulement si le MIC est authentique.
    if (out.fopts_len > 0 &&
        crypto::crypt_fopts(keys.nwk_s_enc_key, crypto::Direction::Downlink, out.dev_addr, counter,
                            downlink_fopts_kind(out), out.fopts.data(),
                            out.fopts_len) != crypto::CryptoStatus::Ok) {
        mbedtls_platform_zeroize(out.fopts.data(), out.fopts.size());
        return SecureStatus::CryptoFailure;
    }
    if (out.has_fport && out.frm_payload_len > 0 &&
        crypto::crypt_frm_payload(payload_key(keys, out.fport), crypto::Direction::Downlink,
                                  out.dev_addr, counter, out.frm_payload.data(),
                                  out.frm_payload_len) != crypto::CryptoStatus::Ok) {
        mbedtls_platform_zeroize(out.frm_payload.data(), out.frm_payload.size());
        return SecureStatus::CryptoFailure;
    }
    return SecureStatus::Ok;
}

// ---------------------------------------------------------------------------
// Profil 1.0.x
// ---------------------------------------------------------------------------
namespace {

const crypto::Key128& payload_key_10(const SessionKeys10& keys, std::uint8_t fport) {
    return fport == 0 ? keys.nwk_s_key : keys.app_s_key;
}

// Scellement commun uplink/downlink 1.0.x.
SecureStatus seal_10(const DataFrame& frame, const SessionKeys10& keys, crypto::Direction dir,
                     std::uint32_t fcnt32, std::uint8_t* out, std::size_t cap,
                     std::size_t& out_written) {
    out_written = 0;
    DataFrame work = frame;
    work.mic = {0, 0, 0, 0};

    if (work.has_fport && work.frm_payload_len > 0) {
        const crypto::CryptoStatus st = crypto::crypt_frm_payload(
            payload_key_10(keys, work.fport), dir, work.dev_addr, fcnt32, work.frm_payload.data(),
            work.frm_payload_len);
        if (st != crypto::CryptoStatus::Ok) {
            mbedtls_platform_zeroize(work.frm_payload.data(), work.frm_payload.size());
            return SecureStatus::CryptoFailure;
        }
    }

    std::size_t n = 0;
    const FrameStatus enc = encode(work, out, cap, n);
    if (enc != FrameStatus::Ok) {
        mbedtls_platform_zeroize(work.frm_payload.data(), work.frm_payload.size());
        return from_frame(enc);
    }

    // MIC 1.0.x sur MHDR | FHDR | FPort | FRMPayload (FOpts inclus, en clair).
    const std::size_t msg_len = n - kMicSize;
    std::array<std::uint8_t, 4> mic{};
    const crypto::CryptoStatus st =
        crypto::compute_data_mic(keys.nwk_s_key, dir, work.dev_addr, fcnt32, out, msg_len, mic);
    mbedtls_platform_zeroize(work.frm_payload.data(), work.frm_payload.size());
    if (st != crypto::CryptoStatus::Ok) {
        return SecureStatus::CryptoFailure;
    }
    for (std::size_t i = 0; i < 4; ++i) {
        out[msg_len + i] = mic[i];
    }
    out_written = n;
    return SecureStatus::Ok;
}

// Ouverture commune 1.0.x : décodage, cohérence FCnt, MIC, puis déchiffrement.
SecureStatus open_10(const std::uint8_t* in, std::size_t len, const SessionKeys10& keys,
                     crypto::Direction dir, std::uint32_t fcnt32, DataFrame& out) {
    const FrameStatus dec = decode(in, len, out);
    if (dec != FrameStatus::Ok) {
        return from_frame(dec);
    }
    if (out.fcnt != static_cast<std::uint16_t>(fcnt32 & 0xFFFFu)) {
        return SecureStatus::FCntMismatch;
    }
    if (len < kMinDataFrame) {
        return SecureStatus::Frame;
    }

    // 1) MIC vérifié AVANT tout déchiffrement.
    const std::size_t msg_len = len - kMicSize;
    std::array<std::uint8_t, 4> expected{};
    const crypto::CryptoStatus st =
        crypto::compute_data_mic(keys.nwk_s_key, dir, out.dev_addr, fcnt32, in, msg_len, expected);
    if (st != crypto::CryptoStatus::Ok) {
        return SecureStatus::CryptoFailure;
    }
    if (!lsim::constant_time_equal(expected.data(), out.mic.data(), 4)) {
        mbedtls_platform_zeroize(out.frm_payload.data(), out.frm_payload.size());
        out.frm_payload_len = 0;
        return SecureStatus::MicMismatch;
    }

    // 2) Déchiffrement seulement si le MIC est authentique. FOpts déjà en clair.
    if (out.has_fport && out.frm_payload_len > 0) {
        const crypto::CryptoStatus dst = crypto::crypt_frm_payload(
            payload_key_10(keys, out.fport), dir, out.dev_addr, fcnt32, out.frm_payload.data(),
            out.frm_payload_len);
        if (dst != crypto::CryptoStatus::Ok) {
            return SecureStatus::CryptoFailure;
        }
    }
    return SecureStatus::Ok;
}

}  // namespace

SecureStatus seal_uplink_10(const DataFrame& frame, const SessionKeys10& keys, const Context10& ctx,
                            std::uint8_t* out, std::size_t cap, std::size_t& out_written) {
    return seal_10(frame, keys, crypto::Direction::Uplink, ctx.fcnt32, out, cap, out_written);
}

SecureStatus open_uplink_10(const std::uint8_t* in, std::size_t len, const SessionKeys10& keys,
                            const Context10& ctx, DataFrame& out) {
    return open_10(in, len, keys, crypto::Direction::Uplink, ctx.fcnt32, out);
}

SecureStatus seal_downlink_10(const DataFrame& frame, const SessionKeys10& keys,
                              const Context10& ctx, std::uint8_t* out, std::size_t cap,
                              std::size_t& out_written) {
    return seal_10(frame, keys, crypto::Direction::Downlink, ctx.fcnt32, out, cap, out_written);
}

SecureStatus open_downlink_10(const std::uint8_t* in, std::size_t len, const SessionKeys10& keys,
                              const Context10& ctx, DataFrame& out) {
    return open_10(in, len, keys, crypto::Direction::Downlink, ctx.fcnt32, out);
}

}  // namespace lsim::lorawan
