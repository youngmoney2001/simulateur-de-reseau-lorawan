// SPDX-License-Identifier: Apache-2.0
#include "lsim/crypto.hpp"

#include <cstring>

#include <mbedtls/aes.h>
#include <mbedtls/cipher.h>
#include <mbedtls/cmac.h>
#include <mbedtls/platform_util.h>

namespace lsim::crypto {
namespace {

constexpr std::size_t kMaxMessage = 255;

void put_le32(std::uint8_t* dst, std::uint32_t v) {
    dst[0] = static_cast<std::uint8_t>(v & 0xFFu);
    dst[1] = static_cast<std::uint8_t>((v >> 8) & 0xFFu);
    dst[2] = static_cast<std::uint8_t>((v >> 16) & 0xFFu);
    dst[3] = static_cast<std::uint8_t>((v >> 24) & 0xFFu);
}

// Bloc Ai (chiffrement FRMPayload) :
//   0x01 | FrameType(4) | Dir | DevAddr(4, LE) | FCnt(4, LE) | 0x00 | i
void build_a_block(const FrameTypeConstant& ftc, Direction dir, std::uint32_t dev_addr,
                   std::uint32_t fcnt32, std::uint8_t i, Block16& a) {
    a.fill(0);
    a[0] = 0x01;
    std::memcpy(a.data() + 1, ftc.data(), ftc.size());
    a[5] = static_cast<std::uint8_t>(dir);
    put_le32(a.data() + 6, dev_addr);
    put_le32(a.data() + 10, fcnt32);
    a[15] = i;
}

// Bloc de MIC (B0, B1 ou B0 downlink) :
//   tag | ConfFCnt(2, LE) | TxDr | TxCh | Dir | DevAddr(4) | FCnt(4) | 0x00 | len
// tag = 0x49 pour tous les blocs de MIC de la spécification.
void build_mic_block(std::uint16_t conf_fcnt, std::uint8_t tx_dr, std::uint8_t tx_ch, Direction dir,
                     std::uint32_t dev_addr, std::uint32_t fcnt32, std::uint8_t msg_len,
                     Block16& b) {
    b.fill(0);
    b[0] = 0x49;
    b[1] = static_cast<std::uint8_t>(conf_fcnt & 0xFFu);
    b[2] = static_cast<std::uint8_t>((conf_fcnt >> 8) & 0xFFu);
    b[3] = tx_dr;
    b[4] = tx_ch;
    b[5] = static_cast<std::uint8_t>(dir);
    put_le32(b.data() + 6, dev_addr);
    put_le32(b.data() + 10, fcnt32);
    b[15] = msg_len;
}

// CMAC sur (bloc B | message), résultat 16 octets. Le buffer est sur la pile,
// de taille bornée à 16 + 255 octets.
CryptoStatus cmac_block_and_message(const Key128& key, const Block16& block,
                                    const std::uint8_t* msg, std::size_t msg_len, Block16& out) {
    if (msg_len > kMaxMessage || (msg_len > 0 && msg == nullptr)) {
        return CryptoStatus::InvalidLength;
    }
    std::array<std::uint8_t, 16 + kMaxMessage> buf{};
    std::memcpy(buf.data(), block.data(), block.size());
    if (msg_len > 0) {
        std::memcpy(buf.data() + 16, msg, msg_len);
    }
    const CryptoStatus st = aes_cmac(key, buf.data(), 16 + msg_len, out);
    mbedtls_platform_zeroize(buf.data(), buf.size());
    return st;
}

}  // namespace

CryptoStatus aes128_encrypt_block(const Key128& key, const Block16& in, Block16& out) {
    mbedtls_aes_context ctx;
    mbedtls_aes_init(&ctx);
    CryptoStatus status = CryptoStatus::InternalError;
    if (mbedtls_aes_setkey_enc(&ctx, key.data(), 128) == 0 &&
        mbedtls_aes_crypt_ecb(&ctx, MBEDTLS_AES_ENCRYPT, in.data(), out.data()) == 0) {
        status = CryptoStatus::Ok;
    }
    mbedtls_aes_free(&ctx);
    return status;
}

CryptoStatus aes_cmac(const Key128& key, const std::uint8_t* data, std::size_t len, Block16& out) {
    if (len > 0 && data == nullptr) {
        return CryptoStatus::InvalidLength;
    }
    const mbedtls_cipher_info_t* info = mbedtls_cipher_info_from_type(MBEDTLS_CIPHER_AES_128_ECB);
    if (info == nullptr) {
        return CryptoStatus::InternalError;
    }
    // Message vide : mbedTLS exige un pointeur valide, même de longueur nulle.
    static const std::uint8_t kEmpty[1] = {0};
    const std::uint8_t* input = (len == 0) ? kEmpty : data;
    const int rc = mbedtls_cipher_cmac(info, key.data(), 128, input, len, out.data());
    return rc == 0 ? CryptoStatus::Ok : CryptoStatus::InternalError;
}

CryptoStatus crypt_frm_payload(const Key128& key, Direction dir, std::uint32_t dev_addr,
                               std::uint32_t fcnt32, std::uint8_t* payload, std::size_t len,
                               const FrameTypeConstant& frame_type) {
    if (len > kMaxMessage) {
        return CryptoStatus::InvalidLength;
    }
    if (len == 0) {
        return CryptoStatus::Ok;
    }
    if (payload == nullptr) {
        return CryptoStatus::InvalidLength;
    }

    mbedtls_aes_context ctx;
    mbedtls_aes_init(&ctx);
    CryptoStatus status = CryptoStatus::Ok;
    if (mbedtls_aes_setkey_enc(&ctx, key.data(), 128) != 0) {
        status = CryptoStatus::InternalError;
    }

    Block16 a{};
    Block16 s{};
    const std::size_t blocks = (len + 15) / 16;
    for (std::size_t i = 1; status == CryptoStatus::Ok && i <= blocks; ++i) {
        build_a_block(frame_type, dir, dev_addr, fcnt32, static_cast<std::uint8_t>(i), a);
        if (mbedtls_aes_crypt_ecb(&ctx, MBEDTLS_AES_ENCRYPT, a.data(), s.data()) != 0) {
            status = CryptoStatus::InternalError;
            break;
        }
        const std::size_t base = (i - 1) * 16;
        const std::size_t n = (len - base < 16) ? len - base : 16;
        for (std::size_t j = 0; j < n; ++j) {
            payload[base + j] = static_cast<std::uint8_t>(payload[base + j] ^ s[j]);
        }
    }

    mbedtls_aes_free(&ctx);
    mbedtls_platform_zeroize(a.data(), a.size());
    mbedtls_platform_zeroize(s.data(), s.size());
    return status;
}

CryptoStatus compute_data_mic(const Key128& key, Direction dir, std::uint32_t dev_addr,
                              std::uint32_t fcnt32, const std::uint8_t* msg, std::size_t msg_len,
                              std::array<std::uint8_t, 4>& mic_out) {
    if (msg_len > kMaxMessage) {
        return CryptoStatus::InvalidLength;
    }
    Block16 b0{};
    build_mic_block(0, 0, 0, dir, dev_addr, fcnt32, static_cast<std::uint8_t>(msg_len), b0);
    Block16 cmac{};
    const CryptoStatus st = cmac_block_and_message(key, b0, msg, msg_len, cmac);
    if (st == CryptoStatus::Ok) {
        std::memcpy(mic_out.data(), cmac.data(), 4);
    }
    mbedtls_platform_zeroize(b0.data(), b0.size());
    mbedtls_platform_zeroize(cmac.data(), cmac.size());
    return st;
}

CryptoStatus compute_uplink_mic_11(const Key128& s_nwk_s_int_key, const Key128& f_nwk_s_int_key,
                                   std::uint16_t conf_fcnt, std::uint8_t tx_dr, std::uint8_t tx_ch,
                                   std::uint32_t dev_addr, std::uint32_t fcnt32,
                                   const std::uint8_t* msg, std::size_t msg_len,
                                   std::array<std::uint8_t, 4>& mic_out) {
    if (msg_len > kMaxMessage) {
        return CryptoStatus::InvalidLength;
    }
    // Partie F : CMAC(FNwkSIntKey, B0 | msg) avec ConfFCnt = 0, dir = uplink.
    Block16 b0{};
    build_mic_block(0, 0, 0, Direction::Uplink, dev_addr, fcnt32, static_cast<std::uint8_t>(msg_len), b0);
    Block16 cmac_f{};
    CryptoStatus st = cmac_block_and_message(f_nwk_s_int_key, b0, msg, msg_len, cmac_f);

    // Partie S : CMAC(SNwkSIntKey, B1 | msg) avec ConfFCnt, TxDr, TxCh.
    Block16 b1{};
    Block16 cmac_s{};
    if (st == CryptoStatus::Ok) {
        build_mic_block(conf_fcnt, tx_dr, tx_ch, Direction::Uplink, dev_addr, fcnt32,
                        static_cast<std::uint8_t>(msg_len), b1);
        st = cmac_block_and_message(s_nwk_s_int_key, b1, msg, msg_len, cmac_s);
    }

    if (st == CryptoStatus::Ok) {
        // MIC = CMAC_S[0..1] || CMAC_F[0..1].
        mic_out[0] = cmac_s[0];
        mic_out[1] = cmac_s[1];
        mic_out[2] = cmac_f[0];
        mic_out[3] = cmac_f[1];
    }
    mbedtls_platform_zeroize(b0.data(), b0.size());
    mbedtls_platform_zeroize(b1.data(), b1.size());
    mbedtls_platform_zeroize(cmac_f.data(), cmac_f.size());
    mbedtls_platform_zeroize(cmac_s.data(), cmac_s.size());
    return st;
}

CryptoStatus compute_downlink_mic_11(const Key128& s_nwk_s_int_key, std::uint16_t conf_fcnt,
                                     std::uint32_t dev_addr, std::uint32_t fcnt32,
                                     const std::uint8_t* msg, std::size_t msg_len,
                                     std::array<std::uint8_t, 4>& mic_out) {
    if (msg_len > kMaxMessage) {
        return CryptoStatus::InvalidLength;
    }
    Block16 b0{};
    build_mic_block(conf_fcnt, 0, 0, Direction::Downlink, dev_addr, fcnt32,
                    static_cast<std::uint8_t>(msg_len), b0);
    Block16 cmac{};
    const CryptoStatus st = cmac_block_and_message(s_nwk_s_int_key, b0, msg, msg_len, cmac);
    if (st == CryptoStatus::Ok) {
        std::memcpy(mic_out.data(), cmac.data(), 4);
    }
    mbedtls_platform_zeroize(b0.data(), b0.size());
    mbedtls_platform_zeroize(cmac.data(), cmac.size());
    return st;
}

}  // namespace lsim::crypto
