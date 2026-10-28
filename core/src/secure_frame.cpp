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
        return SecureStatus::MicMismatch;
    }

    // 2) Déchiffrement seulement si le MIC est authentique.
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

}  // namespace lsim::lorawan
