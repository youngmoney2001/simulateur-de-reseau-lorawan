// SPDX-License-Identifier: Apache-2.0
#include "lsim/lorawan_keys.hpp"

#include <mbedtls/platform_util.h>

namespace lsim::lorawan {
namespace {

using crypto::Block16;
using crypto::CryptoStatus;

// Dérive une clé : AES-128(root, tag | data | pad16). data_len <= 15.
CryptoStatus derive(const Key128& root, std::uint8_t tag, const std::uint8_t* data,
                    std::size_t data_len, Key128& out) {
    Block16 in{};
    in[0] = tag;
    for (std::size_t i = 0; i < data_len; ++i) {
        in[1 + i] = data[i];
    }
    Block16 res{};
    const CryptoStatus st = crypto::aes128_encrypt_block(root, in, res);
    if (st == CryptoStatus::Ok) {
        out = res;
    }
    mbedtls_platform_zeroize(in.data(), in.size());
    mbedtls_platform_zeroize(res.data(), res.size());
    return st;
}

}  // namespace

CryptoStatus derive_join_keys(const Key128& nwk_key, const std::array<std::uint8_t, 8>& dev_eui,
                              JoinKeys& out) {
    CryptoStatus st = derive(nwk_key, 0x05, dev_eui.data(), dev_eui.size(), out.js_enc_key);
    if (st == CryptoStatus::Ok) {
        st = derive(nwk_key, 0x06, dev_eui.data(), dev_eui.size(), out.js_int_key);
    }
    return st;
}

CryptoStatus derive_session_keys_11(const Key128& nwk_key, const Key128& app_key,
                                    const std::array<std::uint8_t, 3>& join_nonce,
                                    const std::array<std::uint8_t, 8>& join_eui,
                                    const std::array<std::uint8_t, 2>& dev_nonce,
                                    SessionKeys11& out) {
    // Données communes : JoinNonce | JoinEUI | DevNonce = 3 + 8 + 2 = 13 octets.
    std::array<std::uint8_t, 13> data{};
    for (std::size_t i = 0; i < 3; ++i) data[i] = join_nonce[i];
    for (std::size_t i = 0; i < 8; ++i) data[3 + i] = join_eui[i];
    for (std::size_t i = 0; i < 2; ++i) data[11 + i] = dev_nonce[i];

    CryptoStatus st = derive(nwk_key, 0x01, data.data(), data.size(), out.f_nwk_s_int_key);
    if (st == CryptoStatus::Ok) st = derive(nwk_key, 0x03, data.data(), data.size(), out.s_nwk_s_int_key);
    if (st == CryptoStatus::Ok) st = derive(nwk_key, 0x04, data.data(), data.size(), out.nwk_s_enc_key);
    if (st == CryptoStatus::Ok) st = derive(app_key, 0x02, data.data(), data.size(), out.app_s_key);

    mbedtls_platform_zeroize(data.data(), data.size());
    return st;
}

CryptoStatus derive_session_keys_10(const Key128& app_key,
                                    const std::array<std::uint8_t, 3>& app_nonce,
                                    const std::array<std::uint8_t, 3>& net_id,
                                    const std::array<std::uint8_t, 2>& dev_nonce,
                                    SessionKeys10& out) {
    // Données communes : AppNonce | NetID | DevNonce = 3 + 3 + 2 = 8 octets.
    std::array<std::uint8_t, 8> data{};
    for (std::size_t i = 0; i < 3; ++i) data[i] = app_nonce[i];
    for (std::size_t i = 0; i < 3; ++i) data[3 + i] = net_id[i];
    for (std::size_t i = 0; i < 2; ++i) data[6 + i] = dev_nonce[i];

    CryptoStatus st = derive(app_key, 0x01, data.data(), data.size(), out.nwk_s_key);
    if (st == CryptoStatus::Ok) st = derive(app_key, 0x02, data.data(), data.size(), out.app_s_key);

    mbedtls_platform_zeroize(data.data(), data.size());
    return st;
}

}  // namespace lsim::lorawan
