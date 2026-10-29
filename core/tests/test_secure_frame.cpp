// SPDX-License-Identifier: Apache-2.0
// Intégration codec + crypto + clés : scellement et ouverture de trames.
#include <array>
#include <cstdint>
#include <cstring>
#include <optional>
#include <vector>

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

void test_fopts_roundtrip_and_encryption_on_wire() {
    const SessionKeys11 k = reference_keys();
    DataFrame in = make_frame(1, "data");
    in.fopts_len = 3;
    in.fopts[0] = 0x02;  // LinkCheckReq
    in.fopts[1] = 0x03;
    in.fopts[2] = 0x04;
    std::uint8_t wire[255];
    std::size_t n = 0;
    CHECK_EQ(static_cast<int>(seal_uplink(in, k, ctx_for(5), wire, sizeof wire, n)),
             static_cast<int>(SecureStatus::Ok));
    // FOpts commencent à l'octet 8 (MHDR, DevAddr, FCtrl, FCnt) : chiffrés sur le fil.
    CHECK_TRUE(wire[8] != 0x02 || wire[9] != 0x03 || wire[10] != 0x04);
    // Concordance avec la primitive directe (même compteur, constante 1).
    std::uint8_t expect[3] = {0x02, 0x03, 0x04};
    CHECK_EQ(static_cast<int>(lsim::crypto::crypt_fopts(
                 k.nwk_s_enc_key, lsim::crypto::Direction::Uplink, 0x01020304u, 5u,
                 lsim::crypto::FOptsCounter::FCntUpOrNFCntDwn, expect, 3)),
             static_cast<int>(lsim::crypto::CryptoStatus::Ok));
    CHECK_TRUE(std::memcmp(wire + 8, expect, 3) == 0);

    DataFrame out;
    CHECK_EQ(static_cast<int>(open_uplink(wire, n, k, ctx_for(5), out)),
             static_cast<int>(SecureStatus::Ok));
    CHECK_EQ(static_cast<int>(out.fopts_len), 3);
    CHECK_TRUE(out.fopts[0] == 0x02 && out.fopts[1] == 0x03 && out.fopts[2] == 0x04);
}

void test_fopts_tampering_rejected_before_exposure() {
    const SessionKeys11 k = reference_keys();
    DataFrame in = make_frame(1, "data");
    in.fopts_len = 2;
    in.fopts[0] = 0x02;
    in.fopts[1] = 0x03;
    std::uint8_t wire[255];
    std::size_t n = 0;
    CHECK_EQ(static_cast<int>(seal_uplink(in, k, ctx_for(5), wire, sizeof wire, n)),
             static_cast<int>(SecureStatus::Ok));
    wire[8] ^= 0x01;  // altération d'un octet de FOpts
    DataFrame out;
    CHECK_EQ(static_cast<int>(open_uplink(wire, n, k, ctx_for(5), out)),
             static_cast<int>(SecureStatus::MicMismatch));
    CHECK_EQ(static_cast<int>(out.fopts_len), 0);
}

DataFrame make_down(std::optional<std::uint8_t> fport, std::uint16_t fcnt, const char* text) {
    DataFrame f;
    f.mtype = MType::UnconfirmedDataDown;
    f.dev_addr = 0x01020304u;
    f.fcnt = fcnt;
    f.has_fport = fport.has_value();
    f.fport = fport.value_or(0);
    const std::size_t n = std::strlen(text);
    f.frm_payload_len = static_cast<std::uint8_t>(n);
    std::memcpy(f.frm_payload.data(), text, n);
    return f;
}

void test_downlink_fport_uses_afcntdwn_and_roundtrips() {
    const SessionKeys11 k = reference_keys();
    DataFrame in = make_down(std::uint8_t{2}, 40, "down");
    in.fopts_len = 2;
    in.fopts[0] = 0x02;
    in.fopts[1] = 0x03;
    DownlinkContext ctx;
    ctx.conf_fcnt = 0;
    ctx.afcnt32 = 40;
    ctx.nfcnt32 = 9;  // ignoré : FPort > 0
    std::uint8_t wire[255];
    std::size_t n = 0;
    CHECK_EQ(static_cast<int>(seal_downlink(in, k, ctx, wire, sizeof wire, n)),
             static_cast<int>(SecureStatus::Ok));
    CHECK_TRUE(std::memcmp(wire + 9, "down", 4) != 0);
    // Les FOpts utilisent la constante 0x00000002 (AFCntDwn) : concordance avec la primitive.
    std::uint8_t expect[2] = {0x02, 0x03};
    CHECK_EQ(static_cast<int>(lsim::crypto::crypt_fopts(
                 k.nwk_s_enc_key, lsim::crypto::Direction::Downlink, 0x01020304u, 40u,
                 lsim::crypto::FOptsCounter::AFCntDwn, expect, 2)),
             static_cast<int>(lsim::crypto::CryptoStatus::Ok));
    CHECK_TRUE(std::memcmp(wire + 8, expect, 2) == 0);

    DataFrame out;
    CHECK_EQ(static_cast<int>(open_downlink(wire, n, k, ctx, out)),
             static_cast<int>(SecureStatus::Ok));
    CHECK_EQ(static_cast<int>(out.fopts_len), 2);
    CHECK_TRUE(out.fopts[0] == 0x02 && out.fopts[1] == 0x03);
    CHECK_TRUE(std::memcmp(out.frm_payload.data(), "down", 4) == 0);
}

void test_downlink_without_fport_uses_nfcntdwn() {
    const SessionKeys11 k = reference_keys();
    DataFrame in = make_down(std::nullopt, 9, "");
    in.fopts_len = 1;
    in.fopts[0] = 0x05;
    DownlinkContext ctx;
    ctx.nfcnt32 = 9;
    ctx.afcnt32 = 77;  // ignoré : pas de FPort
    std::uint8_t wire[255];
    std::size_t n = 0;
    CHECK_EQ(static_cast<int>(seal_downlink(in, k, ctx, wire, sizeof wire, n)),
             static_cast<int>(SecureStatus::Ok));
    std::uint8_t expect[1] = {0x05};
    CHECK_EQ(static_cast<int>(lsim::crypto::crypt_fopts(
                 k.nwk_s_enc_key, lsim::crypto::Direction::Downlink, 0x01020304u, 9u,
                 lsim::crypto::FOptsCounter::FCntUpOrNFCntDwn, expect, 1)),
             static_cast<int>(lsim::crypto::CryptoStatus::Ok));
    CHECK_TRUE(wire[8] == expect[0]);
    DataFrame out;
    CHECK_EQ(static_cast<int>(open_downlink(wire, n, k, ctx, out)),
             static_cast<int>(SecureStatus::Ok));
    CHECK_TRUE(out.fopts[0] == 0x05);
}

void test_downlink_tamper_and_counter_checks() {
    const SessionKeys11 k = reference_keys();
    DataFrame in = make_down(std::uint8_t{1}, 40, "x");
    DownlinkContext ctx;
    ctx.afcnt32 = 40;
    std::uint8_t wire[255];
    std::size_t n = 0;
    CHECK_EQ(static_cast<int>(seal_downlink(in, k, ctx, wire, sizeof wire, n)),
             static_cast<int>(SecureStatus::Ok));
    wire[n - 1] ^= 0x80;  // altération du MIC
    DataFrame out;
    CHECK_EQ(static_cast<int>(open_downlink(wire, n, k, ctx, out)),
             static_cast<int>(SecureStatus::MicMismatch));
    CHECK_EQ(static_cast<int>(out.frm_payload_len), 0);

    // Compteur de contexte incohérent avec le FCnt transmis : rejet avant MIC.
    std::uint8_t good[255];
    std::size_t m = 0;
    seal_downlink(in, k, ctx, good, sizeof good, m);
    DownlinkContext other = ctx;
    other.afcnt32 = 41;
    CHECK_EQ(static_cast<int>(open_downlink(good, m, k, other, out)),
             static_cast<int>(SecureStatus::FCntMismatch));
}

}  // namespace

// ---------------------------------------------------------------------------
// Profil 1.0.x. Vecteurs recalculés indépendamment avec la bibliothèque cryptography
// (AES-ECB et CMAC, script hors dépôt) : ils ne proviennent pas du code C++.
// ---------------------------------------------------------------------------

std::vector<std::uint8_t> from_hex(const char* hex) {
    std::vector<std::uint8_t> out;
    for (std::size_t i = 0; hex[i] != '\0' && hex[i + 1] != '\0'; i += 2) {
        const auto nib = [](char c) -> std::uint8_t {
            return static_cast<std::uint8_t>(c <= '9' ? c - '0' : (c | 0x20) - 'a' + 10);
        };
        out.push_back(static_cast<std::uint8_t>((nib(hex[i]) << 4) | nib(hex[i + 1])));
    }
    return out;
}

bool bytes_equal_hex(const std::uint8_t* data, std::size_t len, const char* hex) {
    const std::vector<std::uint8_t> exp = from_hex(hex);
    return exp.size() == len && std::memcmp(exp.data(), data, len) == 0;
}

SessionKeys10 keys_10() {
    SessionKeys10 k{};
    for (std::size_t i = 0; i < 16; ++i) {
        k.nwk_s_key[i] = static_cast<std::uint8_t>(i);          // 00..0f
        k.app_s_key[i] = static_cast<std::uint8_t>(0xf0 + i);   // f0..ff
    }
    return k;
}

void test_v104_key_derivation_vector() {
    Key128 app_key{};
    for (std::size_t i = 0; i < 16; ++i) app_key[i] = static_cast<std::uint8_t>(0x10 + i);
    const std::array<std::uint8_t, 3> an = {0x01, 0x02, 0x03};
    const std::array<std::uint8_t, 3> ni = {0x00, 0x00, 0x13};
    const std::array<std::uint8_t, 2> dn = {0xaa, 0x55};
    SessionKeys10 k{};
    CHECK_EQ(static_cast<int>(derive_session_keys_10(app_key, an, ni, dn, k)),
             static_cast<int>(lsim::crypto::CryptoStatus::Ok));
    CHECK_TRUE(bytes_equal_hex(k.nwk_s_key.data(), 16, "1be2e9a6e593fa22099353a50240aff0"));
    CHECK_TRUE(bytes_equal_hex(k.app_s_key.data(), 16, "32b9f4258cbf3ad0e1d2acafb90720fd"));
}

void test_v104_uplink_vector_fopts_in_clear() {
    // FOpts (LinkCheckReq) en clair sur le fil ; FRMPayload chiffré avec AppSKey (FPort 1).
    const SessionKeys10 k = keys_10();
    DataFrame f;
    f.mtype = MType::UnconfirmedDataUp;
    f.dev_addr = 0x01020304u;
    f.fcnt = 5;
    f.fopts[0] = 0x02;
    f.fopts_len = 1;
    f.has_fport = true;
    f.fport = 1;
    const char* text = "hello";
    f.frm_payload_len = 5;
    std::memcpy(f.frm_payload.data(), text, 5);
    std::uint8_t wire[64];
    std::size_t n = 0;
    CHECK_EQ(static_cast<int>(seal_uplink_10(f, k, Context10{5}, wire, sizeof wire, n)),
             static_cast<int>(SecureStatus::Ok));
    CHECK_TRUE(bytes_equal_hex(wire, n, "40040302010105000201c5cb1fc5a69b451609"));
    CHECK_EQ(wire[8], std::uint8_t{0x02});  // FOpts en clair

    DataFrame out;
    CHECK_EQ(static_cast<int>(open_uplink_10(wire, n, k, Context10{5}, out)),
             static_cast<int>(SecureStatus::Ok));
    CHECK_TRUE(std::memcmp(out.frm_payload.data(), "hello", 5) == 0);
    CHECK_EQ(out.fopts_len, std::uint8_t{1});
    CHECK_EQ(out.fopts[0], std::uint8_t{0x02});
}

void test_v104_port0_uses_nwk_skey() {
    // FPort 0 : FRMPayload chiffré avec NwkSKey (et non AppSKey), FOpts absentes.
    const SessionKeys10 k = keys_10();
    DataFrame f;
    f.mtype = MType::UnconfirmedDataUp;
    f.dev_addr = 0x01020304u;
    f.fcnt = 5;
    f.has_fport = true;
    f.fport = 0;
    f.frm_payload_len = 2;
    f.frm_payload[0] = 0x02;
    f.frm_payload[1] = 0x03;
    std::uint8_t wire[64];
    std::size_t n = 0;
    CHECK_EQ(static_cast<int>(seal_uplink_10(f, k, Context10{5}, wire, sizeof wire, n)),
             static_cast<int>(SecureStatus::Ok));
    CHECK_TRUE(bytes_equal_hex(wire, n, "4004030201000500003d985663af94"));
    // Ouverture avec la mauvaise clé (AppSKey pour le port 0) : MIC rejeté.
    SessionKeys10 wrong = k;
    wrong.nwk_s_key = k.app_s_key;
    DataFrame out;
    CHECK_EQ(static_cast<int>(open_uplink_10(wire, n, wrong, Context10{5}, out)),
             static_cast<int>(SecureStatus::MicMismatch));
}

void test_v104_downlink_vector_and_tamper() {
    const SessionKeys10 k = keys_10();
    DataFrame f;
    f.mtype = MType::UnconfirmedDataDown;
    f.dev_addr = 0x01020304u;
    f.fcnt = 5;
    f.has_fport = true;
    f.fport = 1;
    f.frm_payload_len = 2;
    f.frm_payload[0] = 'o';
    f.frm_payload[1] = 'k';
    std::uint8_t wire[64];
    std::size_t n = 0;
    CHECK_EQ(static_cast<int>(seal_downlink_10(f, k, Context10{5}, wire, sizeof wire, n)),
             static_cast<int>(SecureStatus::Ok));
    CHECK_TRUE(bytes_equal_hex(wire, n, "600403020100050001a42c99fbfef5"));
    DataFrame out;
    CHECK_EQ(static_cast<int>(open_downlink_10(wire, n, k, Context10{5}, out)),
             static_cast<int>(SecureStatus::Ok));
    CHECK_TRUE(std::memcmp(out.frm_payload.data(), "ok", 2) == 0);
    // Trame modifiée : MIC rejeté avant tout déchiffrement, rien n'est exposé.
    std::uint8_t bad[64];
    std::memcpy(bad, wire, n);
    bad[9] ^= 0x01;
    DataFrame out2;
    CHECK_EQ(static_cast<int>(open_downlink_10(bad, n, k, Context10{5}, out2)),
             static_cast<int>(SecureStatus::MicMismatch));
    CHECK_EQ(out2.frm_payload_len, std::uint8_t{0});
    // Compteur différent : rejet.
    DataFrame out3;
    CHECK_EQ(static_cast<int>(open_downlink_10(wire, n, k, Context10{6}, out3)),
             static_cast<int>(SecureStatus::FCntMismatch));
}

void test_v104_profile_is_separate_from_v11() {
    // Le même message n'a pas le même MIC en 1.0.x et en 1.1 : les deux profils sont distincts.
    const SessionKeys10 k10 = keys_10();
    SessionKeys11 k11 = reference_keys();
    DataFrame f = make_frame(1, "hello");
    std::uint8_t w10[64];
    std::uint8_t w11[64];
    std::size_t n10 = 0;
    std::size_t n11 = 0;
    CHECK_EQ(static_cast<int>(seal_uplink_10(f, k10, Context10{5}, w10, sizeof w10, n10)),
             static_cast<int>(SecureStatus::Ok));
    CHECK_EQ(static_cast<int>(seal_uplink(f, k11, ctx_for(5), w11, sizeof w11, n11)),
             static_cast<int>(SecureStatus::Ok));
    CHECK_TRUE(n10 == n11);
    CHECK_TRUE(std::memcmp(w10 + n10 - 4, w11 + n11 - 4, 4) != 0);
}

void run_secure_frame_tests() {
    test_downlink_fport_uses_afcntdwn_and_roundtrips();
    test_downlink_without_fport_uses_nfcntdwn();
    test_downlink_tamper_and_counter_checks();
    test_fopts_roundtrip_and_encryption_on_wire();
    test_fopts_tampering_rejected_before_exposure();
    test_roundtrip_app_payload();
    test_roundtrip_mac_port0_and_no_payload();
    test_seal_does_not_modify_plaintext();
    test_tampering_is_rejected_without_decryption();
    test_counter_is_bound_to_mic();
    test_wrong_keys_rejected();
    test_buffer_too_small();
    test_fuzz_open_rejects_random_frames();
    test_v104_key_derivation_vector();
    test_v104_uplink_vector_fopts_in_clear();
    test_v104_port0_uses_nwk_skey();
    test_v104_downlink_vector_and_tamper();
    test_v104_profile_is_separate_from_v11();
}
