// SPDX-License-Identifier: Apache-2.0
// Intégration codec + crypto + clés : scellement et ouverture de trames.
#include <array>
#include <cstdint>
#include <cstring>

#include "check.hpp"
#include "lsim/lorawan_keys.hpp"
#include "lsim/secure_frame.hpp"

namespace {

using namespace lsim::lorawan;
using lsim::crypto::Key128;

// Clés de session de référence (vecteurs TTN, voir test_crypto.cpp).
SessionKeys11 reference_keys() {
    const Key128 key = {0xbe, 0xc4, 0x99, 0xc6, 0x9e, 0x9c, 0x93, 0x9e,
                        0x41, 0x3b, 0x66, 0x39, 0x61, 0x63, 0x6c, 0x61};
    const std::array<std::uint8_t, 3> jn = {0x1c, 0x3b, 0xae};
    const std::array<std::uint8_t, 8> jeui = {0x42, 0x42, 0x22, 0x23, 0x12, 0x00, 0x00, 0x00};
    const std::array<std::uint8_t, 2> dn = {0x69, 0x73};
    SessionKeys11 k{};
    const bool ok = derive_session_keys_11(key, key, jn, jeui, dn, k) == lsim::crypto::CryptoStatus::Ok;
    CHECK_TRUE(ok);
    return k;
}

DataFrame make_frame(std::uint8_t fport, const char* text) {
    DataFrame f;
    f.mtype = MType::UnconfirmedDataUp;
    f.dev_addr = 0x01020304u;
    f.fcnt = 5;
    f.has_fport = true;
    f.fport = fport;
    const std::size_t n = std::strlen(text);
    f.frm_payload_len = static_cast<std::uint8_t>(n);
    std::memcpy(f.frm_payload.data(), text, n);
    return f;
}

UplinkContext ctx_for(std::uint32_t fcnt32) {
    UplinkContext c;
    c.fcnt32 = fcnt32;
    return c;
}

void test_roundtrip_app_payload() {
    const SessionKeys11 k = reference_keys();
    const DataFrame in = make_frame(1, "hello");
    std::uint8_t wire[255];
    std::size_t n = 0;
    CHECK_EQ(static_cast<int>(seal_uplink(in, k, ctx_for(5), wire, sizeof wire, n)),
             static_cast<int>(SecureStatus::Ok));
    // Le chiffrement a bien modifié le texte sur le fil.
    CHECK_TRUE(std::memcmp(wire + 9, "hello", 5) != 0);

    DataFrame out;
    CHECK_EQ(static_cast<int>(open_uplink(wire, n, k, ctx_for(5), out)),
             static_cast<int>(SecureStatus::Ok));
    CHECK_EQ(out.frm_payload_len, std::uint8_t{5});
    CHECK_TRUE(std::memcmp(out.frm_payload.data(), "hello", 5) == 0);
    CHECK_EQ(out.fcnt, std::uint16_t{5});
}

void test_roundtrip_mac_port0_and_no_payload() {
    const SessionKeys11 k = reference_keys();
    std::uint8_t wire[255];
    std::size_t n = 0;

    const DataFrame mac = make_frame(0, "\x02\x03");  // commandes MAC sur le port 0
    CHECK_EQ(static_cast<int>(seal_uplink(mac, k, ctx_for(5), wire, sizeof wire, n)),
             static_cast<int>(SecureStatus::Ok));
    DataFrame out;
    CHECK_EQ(static_cast<int>(open_uplink(wire, n, k, ctx_for(5), out)),
             static_cast<int>(SecureStatus::Ok));
    CHECK_TRUE(std::memcmp(out.frm_payload.data(), "\x02\x03", 2) == 0);

    DataFrame empty;
    empty.mtype = MType::UnconfirmedDataUp;
    empty.dev_addr = 0x01020304u;
    empty.fcnt = 5;
    CHECK_EQ(static_cast<int>(seal_uplink(empty, k, ctx_for(5), wire, sizeof wire, n)),
             static_cast<int>(SecureStatus::Ok));
    CHECK_EQ(n, std::size_t{12});
    CHECK_EQ(static_cast<int>(open_uplink(wire, n, k, ctx_for(5), out)),
             static_cast<int>(SecureStatus::Ok));
    CHECK_EQ(out.frm_payload_len, std::uint8_t{0});
}

void test_seal_does_not_modify_plaintext() {
    const SessionKeys11 k = reference_keys();
    const DataFrame in = make_frame(1, "hello");
    std::uint8_t wire[255];
    std::size_t n = 0;
    seal_uplink(in, k, ctx_for(5), wire, sizeof wire, n);
    CHECK_TRUE(std::memcmp(in.frm_payload.data(), "hello", 5) == 0);
}

void test_tampering_is_rejected_without_decryption() {
    const SessionKeys11 k = reference_keys();
    const DataFrame in = make_frame(1, "hello");
    std::uint8_t wire[255];
    std::size_t n = 0;
    seal_uplink(in, k, ctx_for(5), wire, sizeof wire, n);

    // Altération d'un octet de la charge chiffrée.
    std::uint8_t bad[255];
    std::memcpy(bad, wire, n);
    bad[10] ^= 0x01;
    DataFrame out;
    CHECK_EQ(static_cast<int>(open_uplink(bad, n, k, ctx_for(5), out)),
             static_cast<int>(SecureStatus::MicMismatch));
    CHECK_EQ(out.frm_payload_len, std::uint8_t{0});  // rien n'est exposé

    // Altération du MIC.
    std::memcpy(bad, wire, n);
    bad[n - 1] ^= 0x80;
    CHECK_EQ(static_cast<int>(open_uplink(bad, n, k, ctx_for(5), out)),
             static_cast<int>(SecureStatus::MicMismatch));

    // Altération de l'en-tête (DevAddr).
    std::memcpy(bad, wire, n);
    bad[2] ^= 0x01;
    CHECK_EQ(static_cast<int>(open_uplink(bad, n, k, ctx_for(5), out)),
             static_cast<int>(SecureStatus::MicMismatch));
}

void test_counter_is_bound_to_mic() {
    const SessionKeys11 k = reference_keys();
    const DataFrame in = make_frame(1, "hello");
    std::uint8_t wire[255];
    std::size_t n = 0;
    seal_uplink(in, k, ctx_for(5), wire, sizeof wire, n);

    DataFrame out;
    // Compteur 32 bits différent mais même 16 bits de poids faible : le MIC échoue.
    CHECK_EQ(static_cast<int>(open_uplink(wire, n, k, ctx_for(65541), out)),
             static_cast<int>(SecureStatus::MicMismatch));
    // Compteur incohérent avec les 16 bits transmis : rejet avant MIC.
    CHECK_EQ(static_cast<int>(open_uplink(wire, n, k, ctx_for(6), out)),
             static_cast<int>(SecureStatus::FCntMismatch));
}

void test_wrong_keys_rejected() {
    const SessionKeys11 k = reference_keys();
    SessionKeys11 other = k;
    other.s_nwk_s_int_key[0] ^= 0x01;
    const DataFrame in = make_frame(1, "hello");
    std::uint8_t wire[255];
    std::size_t n = 0;
    seal_uplink(in, k, ctx_for(5), wire, sizeof wire, n);
    DataFrame out;
    CHECK_EQ(static_cast<int>(open_uplink(wire, n, other, ctx_for(5), out)),
             static_cast<int>(SecureStatus::MicMismatch));
}

void test_buffer_too_small() {
    const SessionKeys11 k = reference_keys();
    const DataFrame in = make_frame(1, "hello");
    std::uint8_t wire[10];
    std::size_t n = 99;
    CHECK_EQ(static_cast<int>(seal_uplink(in, k, ctx_for(5), wire, sizeof wire, n)),
             static_cast<int>(SecureStatus::BufferTooSmall));
    CHECK_EQ(n, std::size_t{0});
}

// Entrées aléatoires : aucune ne doit être acceptée ni provoquer de lecture hors bornes.
void test_fuzz_open_rejects_random_frames() {
    const SessionKeys11 k = reference_keys();
    std::uint32_t seed = 0xC0FFEEu;
    std::uint8_t buf[255];
    int accepted = 0;
    for (int iter = 0; iter < 20000; ++iter) {
        seed = seed * 1664525u + 1013904223u;
        const std::size_t len = seed % 256u;
        for (std::size_t i = 0; i < len; ++i) {
            seed = seed * 1664525u + 1013904223u;
            buf[i] = static_cast<std::uint8_t>(seed >> 24);
        }
        DataFrame out;
        if (open_uplink(buf, len, k, ctx_for(0), out) == SecureStatus::Ok) {
            ++accepted;
        }
    }
    CHECK_EQ(accepted, 0);
}

}  // namespace

void run_secure_frame_tests() {
    test_roundtrip_app_payload();
    test_roundtrip_mac_port0_and_no_payload();
    test_seal_does_not_modify_plaintext();
    test_tampering_is_rejected_without_decryption();
    test_counter_is_bound_to_mic();
    test_wrong_keys_rejected();
    test_buffer_too_small();
    test_fuzz_open_rejects_random_frames();
}
