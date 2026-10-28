// SPDX-License-Identifier: Apache-2.0
// Tests crypto LoRaWAN. Sources des vecteurs :
//   * FIPS-197 (AES-128) et RFC 4493 (AES-CMAC) : standards publics ;
//   * trame réelle LoRaWAN 1.0.x (MIC 2B11FF0D, texte « test ») : vérifiée
//     indépendamment avec la bibliothèque Python `cryptography` ;
//   * dérivations de clés 1.1, MIC 1.1 et chiffrements avec identifiant de
//     trame : tests de TheThingsNetwork/lorawan-stack (Apache-2.0), dont les
//     entrées sont données en ordre d'affichage et inversées ici en ordre de
//     transmission (convention de l'API), et recalculées indépendamment.
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
    auto nib = [](char c) -> std::uint8_t {
        if (c >= '0' && c <= '9') return static_cast<std::uint8_t>(c - '0');
        if (c >= 'a' && c <= 'f') return static_cast<std::uint8_t>(c - 'a' + 10);
        return static_cast<std::uint8_t>(c - 'A' + 10);
    };
    for (std::size_t i = 0; i < N; ++i) {
        out[i] = static_cast<std::uint8_t>((nib(hex[2 * i]) << 4) | nib(hex[2 * i + 1]));
    }
    return out;
}

bool eq(const void* a, const void* b, std::size_t n) {
    return std::memcmp(a, b, n) == 0;
}

// Compare les n premiers octets de a (tableau) à une valeur hexadécimale.
template <std::size_t N>
bool equals_hex(const std::uint8_t* a, const char* hex) {
    const auto e = from_hex<N>(hex);
    return eq(a, e.data(), N);
}

void test_aes_fips197_vector() {
    const Key128 key = from_hex<16>("000102030405060708090a0b0c0d0e0f");
    const Block16 pt = from_hex<16>("00112233445566778899aabbccddeeff");
    Block16 ct{};
    CHECK_EQ(static_cast<int>(aes128_encrypt_block(key, pt, ct)), static_cast<int>(CryptoStatus::Ok));
    CHECK_TRUE(equals_hex<16>(ct.data(), "69c4e0d86a7b0430d8cdb78070b4c55a"));
}

void test_cmac_rfc4493_vectors() {
    const Key128 key = from_hex<16>("2b7e151628aed2a6abf7158809cf4f3c");
    const auto msg = from_hex<64>(
        "6bc1bee22e409f96e93d7e117393172aae2d8a571e03ac9c9eb76fac45af8e51"
        "30c81c46a35ce411e5fbc1191a0a52eff69f2445df4f9b17ad2b417be66c3710");
    Block16 out{};

    CHECK_EQ(static_cast<int>(aes_cmac(key, nullptr, 0, out)), static_cast<int>(CryptoStatus::Ok));
    CHECK_TRUE(equals_hex<16>(out.data(), "bb1d6929e95937287fa37d129b756746"));
    CHECK_EQ(static_cast<int>(aes_cmac(key, msg.data(), 16, out)), static_cast<int>(CryptoStatus::Ok));
    CHECK_TRUE(equals_hex<16>(out.data(), "070a16b46b4d4144f79bdd9dd04a287c"));
    CHECK_EQ(static_cast<int>(aes_cmac(key, msg.data(), 40, out)), static_cast<int>(CryptoStatus::Ok));
    CHECK_TRUE(equals_hex<16>(out.data(), "dfa66747de9ae63030ca32611497c827"));
    CHECK_EQ(static_cast<int>(aes_cmac(key, msg.data(), 64, out)), static_cast<int>(CryptoStatus::Ok));
    CHECK_TRUE(equals_hex<16>(out.data(), "51f0bebf7e3b9d92fc49741779363cfe"));
}

// Trame réelle 1.0.x : 40 F1 7D BE 49 00 02 00 01 95 43 78 76 2B 11 FF 0D
const std::uint8_t kFrame[] = {0x40, 0xF1, 0x7D, 0xBE, 0x49, 0x00, 0x02, 0x00, 0x01,
                               0x95, 0x43, 0x78, 0x76, 0x2B, 0x11, 0xFF, 0x0D};

void test_real_frame_mic_and_decryption() {
    const Key128 nwk_s_key = from_hex<16>("44024241ed4ce9a68c6a8bc055233fd3");
    const Key128 app_s_key = from_hex<16>("ec925802ae430ca77fd3dd73cb2cc588");

    DataFrame f;
    CHECK_EQ(static_cast<int>(decode(kFrame, sizeof kFrame, f)), static_cast<int>(FrameStatus::Ok));
    const std::size_t msg_len = sizeof kFrame - 4;

    std::array<std::uint8_t, 4> mic{};
    CHECK_EQ(static_cast<int>(compute_data_mic(nwk_s_key, Direction::Uplink, f.dev_addr, f.fcnt,
                                               kFrame, msg_len, mic)),
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

// FOpts LoRaWAN 1.1 (bloc A1 de l'errata FCntDwn). Les valeurs avec constante
// 0x00000001 coïncident avec les vecteurs TTN ; celles avec 0x00000002 ont été
// calculées avec openssl (AES-128-ECB), indépendamment de mbedTLS.
void test_fopts_encryption_vectors() {
    const Key128 key = from_hex<16>("01010101010101010101010101010101");
    const std::uint8_t plain[4] = {1, 2, 3, 4};
    std::uint8_t p[4];

    std::memcpy(p, plain, 4);
    CHECK_EQ(static_cast<int>(crypt_fopts(key, Direction::Uplink, 0x01020304u, 1,
                                          FOptsCounter::FCntUpOrNFCntDwn, p, 4)),
             static_cast<int>(CryptoStatus::Ok));
    CHECK_TRUE(equals_hex<4>(p, "23615f18"));
    // Symétrie : un second passage restitue le clair.
    CHECK_EQ(static_cast<int>(crypt_fopts(key, Direction::Uplink, 0x01020304u, 1,
                                          FOptsCounter::FCntUpOrNFCntDwn, p, 4)),
             static_cast<int>(CryptoStatus::Ok));
    CHECK_TRUE(equals_hex<4>(p, "01020304"));

    std::memcpy(p, plain, 4);
    crypt_fopts(key, Direction::Downlink, 0x01020304u, 1, FOptsCounter::FCntUpOrNFCntDwn, p, 4);
    CHECK_TRUE(equals_hex<4>(p, "b2dbe391"));

    // Constante 0x00000002 (AFCntDwn) : doit différer, pour isoler les domaines.
    std::memcpy(p, plain, 4);
    crypt_fopts(key, Direction::Downlink, 0x01020304u, 1, FOptsCounter::AFCntDwn, p, 4);
    CHECK_TRUE(equals_hex<4>(p, "f1b1baa0"));
    std::memcpy(p, plain, 4);
    crypt_fopts(key, Direction::Uplink, 0x01020304u, 1, FOptsCounter::AFCntDwn, p, 4);
    CHECK_TRUE(equals_hex<4>(p, "85eed646"));

    // Bornes : plus de 15 octets refusés ; pointeur nul refusé pour len > 0.
    std::uint8_t big[16] = {};
    CHECK_EQ(static_cast<int>(crypt_fopts(key, Direction::Uplink, 1u, 1u,
                                          FOptsCounter::FCntUpOrNFCntDwn, big, 16)),
             static_cast<int>(CryptoStatus::InvalidLength));
    CHECK_EQ(static_cast<int>(crypt_fopts(key, Direction::Uplink, 1u, 1u,
                                          FOptsCounter::FCntUpOrNFCntDwn, nullptr, 4)),
             static_cast<int>(CryptoStatus::InvalidLength));
}

// Vecteurs TTN (clé = 0x01 répété, DevAddr 01020304, FCnt 1, données 01 02 03 04).
void test_encryption_vectors_with_and_without_frame_type() {
    const Key128 key = from_hex<16>("01010101010101010101010101010101");
    const FrameTypeConstant fid = from_hex<4>("00000001");
    std::uint8_t p[4];

    const std::uint8_t plain[4] = {1, 2, 3, 4};
    std::memcpy(p, plain, 4);
    crypt_frm_payload(key, Direction::Uplink, 0x01020304u, 1, p, 4);
    CHECK_TRUE(equals_hex<4>(p, "cff30b4e"));

    std::memcpy(p, plain, 4);
    crypt_frm_payload(key, Direction::Downlink, 0x01020304u, 1, p, 4);
    CHECK_TRUE(equals_hex<4>(p, "4e75f440"));

    std::memcpy(p, plain, 4);
    crypt_frm_payload(key, Direction::Uplink, 0x01020304u, 1, p, 4, fid);
    CHECK_TRUE(equals_hex<4>(p, "23615f18"));

    std::memcpy(p, plain, 4);
    crypt_frm_payload(key, Direction::Downlink, 0x01020304u, 1, p, 4, fid);
    CHECK_TRUE(equals_hex<4>(p, "b2dbe391"));
}

void test_mic_vectors_legacy_and_11() {
    const Key128 key = from_hex<16>("01010101010101010101010101010101");
    // MHDR | DevAddr(LE) | FCtrl | FCnt | FPort | FRMPayload, sans MIC.
    const std::uint8_t msg[] = {0x40, 0x04, 0x03, 0x02, 0x01, 0x00, 0x01, 0x00,
                                0x01, 0x01, 0x02, 0x03, 0x04};
    const std::size_t n = sizeof msg;
    std::array<std::uint8_t, 4> mic{};

    CHECK_EQ(static_cast<int>(compute_data_mic(key, Direction::Uplink, 0x01020304u, 1, msg, n, mic)),
             static_cast<int>(CryptoStatus::Ok));
    CHECK_TRUE(equals_hex<4>(mic.data(), "3b073182"));

    CHECK_EQ(static_cast<int>(compute_uplink_mic_11(key, key, 0, 0, 0, 0x01020304u, 1, msg, n, mic)),
             static_cast<int>(CryptoStatus::Ok));
    CHECK_TRUE(equals_hex<4>(mic.data(), "3b073b07"));

    CHECK_EQ(static_cast<int>(compute_downlink_mic_11(key, 0, 0x01020304u, 1, msg, n, mic)),
             static_cast<int>(CryptoStatus::Ok));
    CHECK_TRUE(equals_hex<4>(mic.data(), "a5609fa9"));

    // Le ConfFCnt entre dans le calcul : une valeur différente change le MIC.
    std::array<std::uint8_t, 4> ul_conf7{};
    std::array<std::uint8_t, 4> ul_conf0{};
    compute_uplink_mic_11(key, key, 7, 0, 0, 0x01020304u, 1, msg, n, ul_conf7);
    compute_uplink_mic_11(key, key, 0, 0, 0, 0x01020304u, 1, msg, n, ul_conf0);
    CHECK_TRUE(!eq(ul_conf7.data(), ul_conf0.data(), 4));
}

// Dérivations de clés 1.1 : vecteurs TTN. Entrées fournies en ordre de
// transmission (little-endian), c'est-à-dire l'ordre inverse de l'affichage :
//   JoinNonce 0xAE3B1C -> 1c3bae ; JoinEUI 0000001223224242 -> 4242222312000000
//   DevNonce 0x7369 -> 6973     ; DevEUI 0042004213424341 -> 4143421342004200
void test_session_keys_11_ttn_vectors() {
    const Key128 key = from_hex<16>("bec499c69e9c939e413b663961636c61");
    const auto jn = from_hex<3>("1c3bae");
    const auto join_eui = from_hex<8>("4242222312000000");
    const auto dn = from_hex<2>("6973");
    const auto dev_eui = from_hex<8>("4143421342004200");

    lsim::lorawan::SessionKeys11 k{};
    CHECK_EQ(static_cast<int>(lsim::lorawan::derive_session_keys_11(key, key, jn, join_eui, dn, k)),
             static_cast<int>(CryptoStatus::Ok));
    CHECK_TRUE(equals_hex<16>(k.f_nwk_s_int_key.data(), "379084e7ce22ff191bff4b77536f2aa3"));
    CHECK_TRUE(equals_hex<16>(k.s_nwk_s_int_key.data(), "63c59309d53485bc5164dbf71627aeb9"));
    CHECK_TRUE(equals_hex<16>(k.nwk_s_enc_key.data(), "ce07a009a3970ac0519a099ed53e550b"));
    CHECK_TRUE(equals_hex<16>(k.app_s_key.data(), "b035cce24e4a040eb5cecbf21724412d"));

    lsim::lorawan::JoinKeys jk{};
    CHECK_EQ(static_cast<int>(lsim::lorawan::derive_join_keys(key, dev_eui, jk)),
             static_cast<int>(CryptoStatus::Ok));
    CHECK_TRUE(equals_hex<16>(jk.js_int_key.data(), "cb8e9ee114c3fb5ce472a5aa13ab1855"));
    CHECK_TRUE(equals_hex<16>(jk.js_enc_key.data(), "bb711eefb9829b4a75866f8616bacd6d"));
}

void test_session_keys_11_structure() {
    const Key128 nwk = from_hex<16>("00112233445566778899aabbccddeeff");
    const Key128 app = from_hex<16>("ffeeddccbbaa99887766554433221100");
    const auto jn = from_hex<3>("000001");
    const auto jeui = from_hex<8>("0102030405060708");
    const auto dn = from_hex<2>("0a0b");

    lsim::lorawan::SessionKeys11 k1{};
    CHECK_EQ(static_cast<int>(lsim::lorawan::derive_session_keys_11(nwk, app, jn, jeui, dn, k1)),
             static_cast<int>(CryptoStatus::Ok));

    const Key128* keys[] = {&k1.f_nwk_s_int_key, &k1.s_nwk_s_int_key, &k1.nwk_s_enc_key, &k1.app_s_key};
    for (int i = 0; i < 4; ++i) {
        for (int j = i + 1; j < 4; ++j) {
            CHECK_TRUE(!eq(keys[i]->data(), keys[j]->data(), 16));
        }
    }
    const auto dn2 = from_hex<2>("0a0c");
    lsim::lorawan::SessionKeys11 k3{};
    lsim::lorawan::derive_session_keys_11(nwk, app, jn, jeui, dn2, k3);
    CHECK_TRUE(!eq(k1.f_nwk_s_int_key.data(), k3.f_nwk_s_int_key.data(), 16));
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
    CHECK_EQ(static_cast<int>(compute_uplink_mic_11(key, key, 0, 0, 0, 0, 0, buf, 256, mic)),
             static_cast<int>(CryptoStatus::InvalidLength));
    CHECK_EQ(static_cast<int>(compute_downlink_mic_11(key, 0, 0, 0, buf, 256, mic)),
             static_cast<int>(CryptoStatus::InvalidLength));
}

}  // namespace

void run_crypto_tests() {
    test_aes_fips197_vector();
    test_cmac_rfc4493_vectors();
    test_real_frame_mic_and_decryption();
    test_frm_payload_roundtrip_all_lengths();
    test_encryption_vectors_with_and_without_frame_type();
    test_fopts_encryption_vectors();
    test_mic_vectors_legacy_and_11();
    test_session_keys_11_ttn_vectors();
    test_session_keys_11_structure();
    test_rejects_oversized_inputs();
}
