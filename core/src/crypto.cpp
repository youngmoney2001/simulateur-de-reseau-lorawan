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

// Bloc Ai (FRMPayload) : 0x01 | 0x00*4 | Dir | DevAddr | FCnt | 0x00 | i
// Bloc B0 (MIC)        : 0x49 | 0x00*4 | Dir | DevAddr | FCnt | 0x00 | len
// Les deux ne diffèrent que par le premier octet et le dernier.
void build_block(std::uint8_t tag, Direction dir, std::uint32_t dev_addr, std::uint32_t fcnt32,
                 std::uint8_t last, Block16& block) {
    block.fill(0);
    block[0] = tag;
    block[5] = static_cast<std::uint8_t>(dir);
    put_le32(block.data() + 6, dev_addr);
    put_le32(block.data() + 10, fcnt32);
    block[15] = last;
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
                               std::uint32_t fcnt32, std::uint8_t* payload, std::size_t len) {
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
        build_block(0x01, dir, dev_addr, fcnt32, static_cast<std::uint8_t>(i), a);
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
    if (msg_len > kMaxMessage || (msg_len > 0 && msg == nullptr)) {
        return CryptoStatus::InvalidLength;
    }
    // Construction B0 | msg, puis CMAC ; le MIC est les 4 premiers octets.
    // Le buffer est alloué sur la pile : taille bornée à 16 + 255 octets.
    std::array<std::uint8_t, 16 + kMaxMessage> buf{};
    Block16 b0{};
    build_block(0x49, dir, dev_addr, fcnt32, static_cast<std::uint8_t>(msg_len), b0);
    std::memcpy(buf.data(), b0.data(), b0.size());
    if (msg_len > 0) {
        std::memcpy(buf.data() + 16, msg, msg_len);
    }
    mbedtls_platform_zeroize(b0.data(), b0.size());

    Block16 cmac{};
    const CryptoStatus st = aes_cmac(key, buf.data(), 16 + msg_len, cmac);
    if (st == CryptoStatus::Ok) {
        std::memcpy(mic_out.data(), cmac.data(), 4);
    }
    mbedtls_platform_zeroize(buf.data(), buf.size());
    mbedtls_platform_zeroize(cmac.data(), cmac.size());
    return st;
}

}  // namespace lsim::crypto
