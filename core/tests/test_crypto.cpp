// SPDX-License-Identifier: Apache-2.0
// Tests crypto : vecteurs officiels (FIPS-197, RFC 4493) et trame LoRaWAN réelle
// (vecteur 1.0.x vérifié indépendamment : MIC 2B11FF0D, texte déchiffré "test").
#include <cstdint>
#include <cstring>

#include "check.hpp"
#include "lsim/crypto.hpp"
#include "lsim/lorawan_frame.hpp"
#include "lsim/lorawan_keys.hpp"

namespace {

using namespace lsim::crypto;
using lsim::lorawan::DataFrame;
using lsim::lorawan::decode;
using lsim::lorawan::FrameStatus;

template <std::size_t N>
std::array<std::uint8_t, N> from_hex(const char* hex) {
    std::array<std::uint8_t, N> out{};
    for (std::size_t i = 0; i < N; ++i) {
        auto nib = [](char c) -> std::uint8_t {
            if (c >= '0' && c <= '9') return static_cast<std::uint8_t>(c - '0');
            if (c >= 'a' && c <= 'f') return static_cast<std::uint8_t>(c - 'a' + 10);
            return static_cast<std::uint8_t>(c - 'A' + 10);
        };
        out[i] = static_cast<std::uint8_t>((nib(hex[2 * i]) << 4) | nib(hex[2 * i + 1]));
    }
    return out;
}

bool eq(const void* a, const void* b, std::size_t n) {
    return std::memcmp(a, b, n) == 0;
}

void test_aes_fips197_vector() {
    const Key128 key = from_hex<16>("000102030405060708090a0b0c0d0e0f");
    const Block16 pt = from_hex<16>("00112233445566778899aabbccddeeff");
    const Block16 expected = from_hex<16>("69c4e0d86a7b0430d8cdb78070b4c55a");
    Block16 ct{};
    CHECK_EQ(static_cast<int>(aes128_encrypt_block(key, pt, ct)), static_cast<int>(CryptoStatus::Ok));
    CHECK_TRUE(eq(ct.data(), expected.data(), 16));
}

void test_cmac_rfc4493_vectors() {
    const Key128 key = from_hex<16>("2b7e151628aed2a6abf7158809cf4f3c");
    const auto msg = from_hex<64>(
        "6bc1bee22e409f96e93d7e117393172aae2d8a571e03ac9c9eb76fac45af8e51"
        "30c81c46a35ce411e5fbc1191a0a52eff69f2445df4f9b17ad2b417be66c3710");
    Block16 out{};

    CHECK_EQ(static_cast<int>(aes_cmac(key, nullptr, 0, out)), static_cast<int>(CryptoStatus::Ok));
    CHECK_TRUE(eq(out.data(), from_hex<16>("bb1d6929e95937287fa37d129b756746").data(), 16));

    CHECK_EQ(static_cast<int>(aes_cmac(key, msg.data(), 16, out)), static_cast<int>(CryptoStatus::Ok));
    CHECK_TRUE(eq(out.data(), from_hex<16>("070a16b46b4d4144f79bdd9dd04a287c").data(), 16));

    CHECK_EQ(static_cast<int>(aes_cmac(key, msg.data(), 40, out)), static_cast<int>(CryptoStatus::Ok));
    CHECK_TRUE(eq(out.data(), from_hex<16>("dfa66747de9ae63030ca32611497c827").data(), 16));

    CHECK_EQ(static_cast<int>(aes_cmac(key, msg.data(), 64, out)), static_cast<int>(CryptoStatus::Ok));
    CHECK_TRUE(eq(out.data(), from_hex<16>("51f0bebf7e3b9d92fc49741779363cfe").data(), 16));
}

// Trame réelle 1.0.x : 40 F1 7D BE 49 00 02 00 01 95 43 78 76 2B 11 FF 0D
const std::uint8_t kFrame[] = {0x40, 0xF1, 0x7D, 0xBE, 0x49, 0x00, 0x02, 0x00, 0x01,
                               0x95, 0x43, 0x78, 0x76, 0x2B, 0x11, 0xFF, 0x0D};

void test_real_frame_mic_and_decryption() {
    const Key128 nwk_s_key = from_hex<16>("44024241ed4ce9a68c6a8bc055233fd3");
    const Key128 app_s_key = from_hex<16>("ec925802ae430ca77fd3dd73cb2cc588");

    DataFrame f;
    CHECK_EQ(static_cast<int>(decode(kFrame, sizeof kFrame, f)), static_cast<int>(FrameStatus::Ok));
    const std::size_t msg_len = sizeof kFrame - 4;  // MHDR | FHDR | FPort | FRMPayload

    std::array<std::uint8_t, 4> mic{};
    CHECK_EQ(static_cast<int>(compute_data_mic(nwk_s_key, Direction::Uplink, f.dev_addr,
                                               f.fcnt, kFrame, msg_len, mic)),
             static_cast<int>(CryptoStatus::Ok));
    CHECK_TRUE(eq(mic.data(), f.mic.data(), 4));  // 2B 11 FF 0D

    std::uint8_t payload[4];
    std::memcpy(payload, f.frm_payload.data(), 4);
    CHECK_EQ(static_cast<int>(crypt_frm_payload(app_s_key, Direction::Uplink, f.dev_addr, f.fcnt,
                                                payload, 4)),
             static_cast<int>(CryptoStatus::Ok));
    CHECK_TRUE(eq(payload, "test", 4));
}

void test_frm_payload_roundtrip_all_lengths() {
    const Key128 key = from_hex<16>("0102030405060708090a0b0c0d0e0f10");
    std::uint8_t original[255];
    std::uint8_t work[255];
    for (std::size_t len = 0; len <= 255; ++len) {
        for (std::size_t i = 0; i < len; ++i) original[i] = static_cast<std::uint8_t>(i * 7 + len);
        std::memcpy(work, original, len);
        CHECK_EQ(static_cast<int>(crypt_frm_payload(key, Direction::Downlink, 0x26011BDAu, 42u, work, len)),
                 static_cast<int>(CryptoStatus::Ok));
        if (len > 0) CHECK_TRUE(!eq(work, original, len));
        CHECK_EQ(static_cast<int>(crypt_frm_payload(key, Direction::Downlink, 0x26011BDAu, 42u, work, len)),
                 static_cast<int>(CryptoStatus::Ok));
        CHECK_TRUE(eq(work, original, len));
    }
}

void test_frm_payload_depends_on_direction_and_counter() {
    const Key128 key = from_hex<16>("0102030405060708090a0b0c0d0e0f10");
    std::uint8_t a[16] = {0};
    std::uint8_t b[16] = {0};
    std::uint8_t c[16] = {0};
    crypt_frm_payload(key, Direction::Uplink, 1, 1, a, 16);
    crypt_frm_payload(key, Direction::Downlink, 1, 1, b, 16);
    crypt_frm_payload(key, Direction::Uplink, 1, 2, c, 16);
    CHECK_TRUE(!eq(a, b, 16));
    CHECK_TRUE(!eq(a, c, 16));
}

void test_rejects_oversized_inputs() {
    const Key128 key{};
    std::uint8_t buf[256] = {0};
    CHECK_EQ(static_cast<int>(crypt_frm_payload(key, Direction::Uplink, 0, 0, buf, 256)),
             static_cast<int>(CryptoStatus::InvalidLength));
    std::array<std::uint8_t, 4> mic{};
    CHECK_EQ(static_cast<int>(compute_data_mic(key, Direction::Uplink, 0, 0, buf, 256, mic)),
             static_cast<int>(CryptoStatus::InvalidLength));
    CHECK_EQ(static_cast<int>(compute_data_mic(key, Direction::Uplink, 0, 0, nullptr, 5, mic)),
             static_cast<int>(CryptoStatus::InvalidLength));
}

// Les clés 1.1 ne disposent pas encore de vecteurs officiels dans ce dépôt.
// Ces tests vérifient la structure : déterminisme, séparation des clés,
// sensibilité à chaque entrée. Ils ne valident pas la conformité.
void test_session_keys_11_structure() {
    const Key128 nwk = from_hex<16>("00112233445566778899aabbccddeeff");
    const Key128 app = from_hex<16>("ffeeddccbbaa99887766554433221100");
    const auto jn = from_hex<3>("000001");
    const auto jeui = from_hex<8>("0102030405060708");
    const auto dn = from_hex<2>("0a0b");

    lsim::lorawan::SessionKeys11 k1{};
    lsim::lorawan::SessionKeys11 k2{};
    CHECK_EQ(static_cast<int>(lsim::lorawan::derive_session_keys_11(nwk, app, jn, jeui, dn, k1)),
             static_cast<int>(CryptoStatus::Ok));
    CHECK_EQ(static_cast<int>(lsim::lorawan::derive_session_keys_11(nwk, app, jn, jeui, dn, k2)),
             static_cast<int>(CryptoStatus::Ok));
    CHECK_TRUE(eq(k1.f_nwk_s_int_key.data(), k2.f_nwk_s_int_key.data(), 16));
    CHECK_TRUE(eq(k1.app_s_key.data(), k2.app_s_key.data(), 16));

    // Séparation : aucune clé de session identique à une autre.
    const Key128* keys[] = {&k1.f_nwk_s_int_key, &k1.s_nwk_s_int_key, &k1.nwk_s_enc_key, &k1.app_s_key};
    for (int i = 0; i < 4; ++i) {
        for (int j = i + 1; j < 4; ++j) {
            CHECK_TRUE(!eq(keys[i]->data(), keys[j]->data(), 16));
        }
    }

    // Sensibilité : un seul octet de DevNonce change la dérivation.
    const auto dn2 = from_hex<2>("0a0c");
    lsim::lorawan::SessionKeys11 k3{};
    lsim::lorawan::derive_session_keys_11(nwk, app, jn, jeui, dn2, k3);
    CHECK_TRUE(!eq(k1.f_nwk_s_int_key.data(), k3.f_nwk_s_int_key.data(), 16));
    CHECK_TRUE(!eq(k1.app_s_key.data(), k3.app_s_key.data(), 16));

    lsim::lorawan::JoinKeys jk{};
    CHECK_EQ(static_cast<int>(lsim::lorawan::derive_join_keys(nwk, jeui, jk)),
             static_cast<int>(CryptoStatus::Ok));
    CHECK_TRUE(!eq(jk.js_enc_key.data(), jk.js_int_key.data(), 16));
}

}  // namespace

void run_crypto_tests() {
    test_aes_fips197_vector();
    test_cmac_rfc4493_vectors();
    test_real_frame_mic_and_decryption();
    test_frm_payload_roundtrip_all_lengths();
    test_frm_payload_depends_on_direction_and_counter();
    test_rejects_oversized_inputs();
    test_session_keys_11_structure();
}
