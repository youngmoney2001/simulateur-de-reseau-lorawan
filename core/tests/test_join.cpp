// SPDX-License-Identifier: Apache-2.0
// Jointure OTAA 1.1 : vecteurs TTN, aller-retour, altérations, bout en bout.
#include <array>
#include <cstdint>
#include <cstring>

#include "check.hpp"
#include "lsim/join.hpp"
#include "lsim/lorawan_keys.hpp"
#include "lsim/secure_frame.hpp"

namespace {

using namespace lsim::lorawan;
using lsim::crypto::Key128;
using Bytes = std::array<std::uint8_t, 8>;
using Nonce2 = std::array<std::uint8_t, 2>;

Key128 key01() {
    Key128 k;
    k.fill(0x01);
    return k;
}

bool same(const void* a, const void* b, std::size_t n) {
    return std::memcmp(a, b, n) == 0;
}

// Entrées du vecteur TTN « Join-request accept/no CFList » (ordre de transmission).
const Bytes kDevEuiRejoin = {0xAA, 0xBB, 0xCC, 0xDD, 0x01, 0x02, 0x03, 0x04};
const Bytes kJoinEui = {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08};
const Nonce2 kDevNonce = {0x01, 0x02};
const std::uint8_t kLegacyPayload[13] = {0x20, 0x03, 0x02, 0x01, 0x03, 0x02, 0x01,
                                         0x04, 0x03, 0x02, 0x01, 0x00, 0x01};

JoinAcceptFields sample_accept(bool optneg, bool cfl) {
    JoinAcceptFields f;
    f.join_nonce = {0x03, 0x02, 0x01};
    f.net_id = {0x03, 0x02, 0x01};
    f.dev_addr = 0x01020304u;
    f.dl_settings = optneg ? 0x80 : 0x00;
    f.rx_delay = 0x01;
    f.has_cflist = cfl;
    for (std::size_t i = 0; i < 16; ++i) f.cflist[i] = static_cast<std::uint8_t>(0xC0 + i);
    return f;
}

bool fields_equal(const JoinAcceptFields& a, const JoinAcceptFields& b) {
    return a.join_nonce == b.join_nonce && a.net_id == b.net_id && a.dev_addr == b.dev_addr &&
           a.dl_settings == b.dl_settings && a.rx_delay == b.rx_delay &&
           a.has_cflist == b.has_cflist && (!a.has_cflist || a.cflist == b.cflist);
}

void test_join_request_mic_ttn_vector() {
    // MHDR | JoinEUI | DevEUI | DevNonce, octets fournis tels quels à la fonction MIC.
    const std::uint8_t msg[19] = {0x00, 0x08, 0x07, 0x06, 0x05, 0x04, 0x03, 0x02, 0x01,
                                  0x08, 0x07, 0x06, 0x05, 0x04, 0x03, 0x02, 0x01, 0x02, 0x01};
    std::array<std::uint8_t, 4> mic{};
    CHECK_EQ(static_cast<int>(compute_join_request_mic(key01(), msg, 19, mic)),
             static_cast<int>(JoinStatus::Ok));
    CHECK_TRUE(same(mic.data(), "\xe6\xe1\x0c\x55", 4));
    CHECK_EQ(static_cast<int>(compute_join_request_mic(key01(), msg, 18, mic)),
             static_cast<int>(JoinStatus::InvalidLength));
}

void test_join_request_roundtrip_and_tamper() {
    JoinRequestFields f;
    f.join_eui = {0x08, 0x07, 0x06, 0x05, 0x04, 0x03, 0x02, 0x01};
    f.dev_eui = f.join_eui;
    f.dev_nonce = {0x02, 0x01};
    std::uint8_t wire[32];
    std::size_t n = 0;
    CHECK_EQ(static_cast<int>(encode_join_request(f, key01(), wire, sizeof wire, n)),
             static_cast<int>(JoinStatus::Ok));
    CHECK_EQ(n, kJoinRequestSize);
    CHECK_TRUE(same(wire + 19, "\xe6\xe1\x0c\x55", 4));  // MIC de référence

    JoinRequestFields g;
    CHECK_EQ(static_cast<int>(decode_join_request(wire, n, key01(), g)),
             static_cast<int>(JoinStatus::Ok));
    CHECK_TRUE(g.join_eui == f.join_eui && g.dev_eui == f.dev_eui && g.dev_nonce == f.dev_nonce);

    wire[10] ^= 0x01;
    CHECK_EQ(static_cast<int>(decode_join_request(wire, n, key01(), g)),
             static_cast<int>(JoinStatus::MicMismatch));
    CHECK_TRUE((g.dev_nonce == Nonce2{0, 0}));  // rien n'est exposé
    wire[10] ^= 0x01;
    wire[0] = 0x40;
    CHECK_EQ(static_cast<int>(decode_join_request(wire, n, key01(), g)),
             static_cast<int>(JoinStatus::InvalidMHDR));
    CHECK_EQ(static_cast<int>(encode_join_request(f, key01(), wire, 22, n)),
             static_cast<int>(JoinStatus::BufferTooSmall));
    CHECK_EQ(n, std::size_t{0});
}

void test_join_accept_cipher_ttn_vector() {
    // Clair (JoinNonce..MIC legacy) et chiffré de référence, clé 0x01.
    const std::uint8_t clear[16] = {0x03, 0x02, 0x01, 0x03, 0x02, 0x01, 0x04, 0x03,
                                    0x02, 0x01, 0x00, 0x01, 0x32, 0xf5, 0x4a, 0xb3};
    const std::uint8_t enc_ref[16] = {0xc9, 0xfb, 0xb2, 0x59, 0xe1, 0x16, 0x49, 0x09,
                                      0x6a, 0x56, 0x8a, 0x9e, 0x3b, 0x71, 0x17, 0xc3};
    std::uint8_t buf[16];
    std::memcpy(buf, clear, 16);
    CHECK_EQ(static_cast<int>(join_accept_encrypt(key01(), buf, 16)),
             static_cast<int>(JoinStatus::Ok));
    CHECK_TRUE(same(buf, enc_ref, 16));
    CHECK_EQ(static_cast<int>(join_accept_decrypt(key01(), buf, 16)),
             static_cast<int>(JoinStatus::Ok));
    CHECK_TRUE(same(buf, clear, 16));

    std::uint8_t bad[15] = {0};
    CHECK_EQ(static_cast<int>(join_accept_encrypt(key01(), bad, 15)),
             static_cast<int>(JoinStatus::InvalidLength));
}

void test_join_accept_mic_ttn_vectors() {
    std::array<std::uint8_t, 4> mic{};
    CHECK_EQ(static_cast<int>(compute_join_accept_mic_legacy(key01(), kLegacyPayload, 13, mic)),
             static_cast<int>(JoinStatus::Ok));
    CHECK_TRUE(same(mic.data(), "\x32\xf5\x4a\xb3", 4));

    // MIC 1.1 : JoinReqType 0xFF | JoinEUI | DevNonce | message, clé JSIntKey = 0x01.
    CHECK_EQ(static_cast<int>(compute_join_accept_mic_11(key01(), kJoinReqTypeJoin, kJoinEui,
                                                         kDevNonce, kLegacyPayload, 13, mic)),
             static_cast<int>(JoinStatus::Ok));
    CHECK_TRUE(same(mic.data(), "\x48\xe9\xbe\x5f", 4));
    CHECK_EQ(static_cast<int>(compute_join_accept_mic_11(key01(), kJoinReqTypeJoin, kJoinEui,
                                                         kDevNonce, kLegacyPayload, 14, mic)),
             static_cast<int>(JoinStatus::InvalidLength));
}

void test_encode_legacy_matches_vector() {
    // OptNeg = 0 : chiffrement et MIC de référence, sortie = MHDR | blocs chiffrés.
    JoinAcceptFields f = sample_accept(false, false);
    std::uint8_t wire[64];
    std::size_t n = 0;
    CHECK_EQ(static_cast<int>(encode_join_accept(f, key01(), Bytes{}, kJoinEui, kDevNonce, wire,
                                                 sizeof wire, n)),
             static_cast<int>(JoinStatus::Ok));
    CHECK_EQ(n, kJoinAcceptSizeNoCfl);
    const std::uint8_t enc_ref[16] = {0xc9, 0xfb, 0xb2, 0x59, 0xe1, 0x16, 0x49, 0x09,
                                      0x6a, 0x56, 0x8a, 0x9e, 0x3b, 0x71, 0x17, 0xc3};
    CHECK_EQ(wire[0], 0x20);
    CHECK_TRUE(same(wire + 1, enc_ref, 16));

    JoinAcceptFields g;
    CHECK_EQ(static_cast<int>(decode_join_accept(wire, n, key01(), Bytes{}, kJoinEui, kDevNonce, g)),
             static_cast<int>(JoinStatus::Ok));
    CHECK_TRUE(fields_equal(f, g));
}

void test_roundtrip_optneg_and_cflist() {
    const Key128 nwk = key01();
    const Bytes dev_eui = {0x42, 0x00, 0x42, 0x13, 0x42, 0x42, 0x00, 0x42};
    for (int variant = 0; variant < 4; ++variant) {
        const bool optneg = (variant & 1) != 0;
        const bool cfl = (variant & 2) != 0;
        const JoinAcceptFields f = sample_accept(optneg, cfl);
        std::uint8_t wire[64];
        std::size_t n = 0;
        CHECK_EQ(static_cast<int>(encode_join_accept(f, nwk, dev_eui, kJoinEui, kDevNonce, wire,
                                                     sizeof wire, n)),
                 static_cast<int>(JoinStatus::Ok));
        CHECK_EQ(n, cfl ? kJoinAcceptSizeCfl : kJoinAcceptSizeNoCfl);

        JoinAcceptFields g;
        CHECK_EQ(static_cast<int>(decode_join_accept(wire, n, nwk, dev_eui, kJoinEui, kDevNonce, g)),
                 static_cast<int>(JoinStatus::Ok));
        CHECK_TRUE(fields_equal(f, g));

        // Altération d'un bit : rejet, champs remis à zéro.
        wire[5] ^= 0x10;
        CHECK_EQ(static_cast<int>(decode_join_accept(wire, n, nwk, dev_eui, kJoinEui, kDevNonce, g)),
                 static_cast<int>(JoinStatus::MicMismatch));
        CHECK_EQ(g.dev_addr, std::uint32_t{0});
        wire[5] ^= 0x10;

        // Mauvais contexte. En 1.1 (OptNeg=1), le MIC couvre DevNonce, JoinEUI et
        // DevEUI (via JSIntKey) : toute différence doit être rejetée. En 1.0
        // (OptNeg=0), le MIC ne couvre que le message : seul le contenu compte.
        if (optneg) {
            CHECK_EQ(static_cast<int>(decode_join_accept(wire, n, nwk, dev_eui, kJoinEui,
                                                         Nonce2{0x02, 0x02}, g)),
                     static_cast<int>(JoinStatus::MicMismatch));
            Bytes other_eui = dev_eui;
            other_eui[0] ^= 0x01;
            CHECK_EQ(static_cast<int>(decode_join_accept(wire, n, nwk, other_eui, kJoinEui,
                                                         kDevNonce, g)),
                     static_cast<int>(JoinStatus::MicMismatch));
        }
    }
}

void test_optneg_changes_mic_key() {
    // Même message, OptNeg différent : le MIC (et donc le chiffré) doit différer.
    const Bytes dev_eui = {1, 2, 3, 4, 5, 6, 7, 8};
    std::uint8_t a[64], b[64];
    std::size_t na = 0, nb = 0;
    encode_join_accept(sample_accept(false, false), key01(), dev_eui, kJoinEui, kDevNonce, a,
                       sizeof a, na);
    encode_join_accept(sample_accept(true, false), key01(), dev_eui, kJoinEui, kDevNonce, b,
                       sizeof b, nb);
    CHECK_TRUE(!same(a + 1, b + 1, 16));
}

void test_encode_buffer_too_small() {
    std::uint8_t wire[16];
    std::size_t n = 9;
    CHECK_EQ(static_cast<int>(encode_join_accept(sample_accept(false, false), key01(), Bytes{},
                                                 kJoinEui, kDevNonce, wire, sizeof wire, n)),
             static_cast<int>(JoinStatus::BufferTooSmall));
    CHECK_EQ(n, std::size_t{0});
}

// Bout en bout : join-accept 1.1 -> clés de session -> trame uplink scellée -> ouverte.
void test_end_to_end_join_then_uplink() {
    const Key128 nwk = key01();
    Key128 app;
    app.fill(0x02);
    const Bytes dev_eui = {0x42, 0x00, 0x42, 0x13, 0x42, 0x42, 0x00, 0x42};
    const JoinAcceptFields accept = sample_accept(true, false);

    // Serveur : join-accept chiffré.
    std::uint8_t wire[64];
    std::size_t n = 0;
    CHECK_EQ(static_cast<int>(encode_join_accept(accept, nwk, dev_eui, kJoinEui, kDevNonce, wire,
                                                 sizeof wire, n)),
             static_cast<int>(JoinStatus::Ok));

    // Device : ouverture, puis dérivation des clés de session 1.1.
    JoinAcceptFields got;
    CHECK_EQ(static_cast<int>(decode_join_accept(wire, n, nwk, dev_eui, kJoinEui, kDevNonce, got)),
             static_cast<int>(JoinStatus::Ok));
    SessionKeys11 keys{};
    CHECK_EQ(static_cast<int>(derive_session_keys_11(nwk, app, got.join_nonce, kJoinEui,
                                                     kDevNonce, keys)),
             static_cast<int>(lsim::crypto::CryptoStatus::Ok));

    // Le device émet une trame ; le serveur la vérifie avec les mêmes clés.
    DataFrame f;
    f.mtype = MType::ConfirmedDataUp;
    f.dev_addr = got.dev_addr;
    f.fcnt = 1;
    f.has_fport = true;
    f.fport = 10;
    const char* text = "join ok";
    f.frm_payload_len = 7;
    std::memcpy(f.frm_payload.data(), text, 7);
    UplinkContext ctx;
    ctx.fcnt32 = 1;
    std::uint8_t phy[255];
    std::size_t pn = 0;
    CHECK_EQ(static_cast<int>(seal_uplink(f, keys, ctx, phy, sizeof phy, pn)),
             static_cast<int>(SecureStatus::Ok));
    DataFrame back;
    CHECK_EQ(static_cast<int>(open_uplink(phy, pn, keys, ctx, back)),
             static_cast<int>(SecureStatus::Ok));
    CHECK_TRUE(back.frm_payload_len == 7 && same(back.frm_payload.data(), text, 7));
}

// Entrées aléatoires : jamais acceptées, jamais de lecture hors bornes.
void test_fuzz_join_decoders() {
    const Key128 nwk = key01();
    const Bytes dev_eui = {1, 2, 3, 4, 5, 6, 7, 8};
    std::uint32_t seed = 0xBADC0DEu;
    std::uint8_t buf[40];
    int accepted = 0;
    for (int iter = 0; iter < 20000; ++iter) {
        seed = seed * 1664525u + 1013904223u;
        const std::size_t len = seed % 40u;
        for (std::size_t i = 0; i < len; ++i) {
            seed = seed * 1664525u + 1013904223u;
            buf[i] = static_cast<std::uint8_t>(seed >> 24);
        }
        if (len > 0) buf[0] = (iter & 1) ? 0x20 : 0x00;
        JoinAcceptFields a;
        JoinRequestFields r;
        if (decode_join_accept(buf, len, nwk, dev_eui, kJoinEui, kDevNonce, a) == JoinStatus::Ok) {
            ++accepted;
        }
        if (decode_join_request(buf, len, nwk, r) == JoinStatus::Ok) {
            ++accepted;
        }
    }
    CHECK_EQ(accepted, 0);
}

}  // namespace

// Join-accept après rejoin (1.1 §6.2.4.4) : aller-retour, JoinReqType et RJcount liés au MIC.
void test_rejoin_join_accept_roundtrip_and_binding() {
    JoinAcceptFields f;
    f.join_nonce = {0x01, 0x02, 0x03};
    f.net_id = {0x13, 0x00, 0x00};
    f.dev_addr = 0x26011234;
    f.dl_settings = 0x80;
    f.rx_delay = 1;
    std::uint8_t wire[33] = {};
    std::size_t n = 0;
    CHECK_EQ(static_cast<int>(encode_rejoin_join_accept(f, key01(), kDevEuiRejoin, kJoinEui, 1,
                                                        0x0102, wire, sizeof wire, n)),
             static_cast<int>(JoinStatus::Ok));
    CHECK_EQ(n, kJoinAcceptSizeNoCfl);
    CHECK_EQ(static_cast<int>(wire[0]), static_cast<int>(kMhdrJoinAccept));

    JoinAcceptFields g;
    CHECK_EQ(static_cast<int>(decode_rejoin_join_accept(wire, n, key01(), kDevEuiRejoin, kJoinEui,
                                                        1, 0x0102, g)),
             static_cast<int>(JoinStatus::Ok));
    CHECK_TRUE(g.join_nonce == f.join_nonce && g.net_id == f.net_id && g.dev_addr == f.dev_addr);
    CHECK_EQ(static_cast<int>(g.dl_settings), 0x80);

    // Mauvais JoinReqType, mauvais RJcount, ou join-accept de join-request : MIC faux.
    CHECK_EQ(static_cast<int>(decode_rejoin_join_accept(wire, n, key01(), kDevEuiRejoin, kJoinEui,
                                                        0, 0x0102, g)),
             static_cast<int>(JoinStatus::MicMismatch));
    CHECK_EQ(static_cast<int>(decode_rejoin_join_accept(wire, n, key01(), kDevEuiRejoin, kJoinEui,
                                                        1, 0x0103, g)),
             static_cast<int>(JoinStatus::MicMismatch));
    CHECK_TRUE(g.dev_addr == 0);  // rien n'est exposé
    CHECK_EQ(static_cast<int>(decode_join_accept(wire, n, key01(), kDevEuiRejoin, kJoinEui,
                                                 Nonce2{0x02, 0x01}, g)),
             static_cast<int>(JoinStatus::MicMismatch));

    // OptNeg obligatoire pour un rejoin.
    f.dl_settings = 0x00;
    CHECK_EQ(static_cast<int>(encode_rejoin_join_accept(f, key01(), kDevEuiRejoin, kJoinEui, 0,
                                                        1, wire, sizeof wire, n)),
             static_cast<int>(JoinStatus::FieldOutOfRange));
    f.dl_settings = 0x80;
    CHECK_EQ(static_cast<int>(encode_rejoin_join_accept(f, key01(), kDevEuiRejoin, kJoinEui, 3,
                                                        1, wire, sizeof wire, n)),
             static_cast<int>(JoinStatus::FieldOutOfRange));
}

void run_join_tests() {
    test_join_request_mic_ttn_vector();
    test_join_request_roundtrip_and_tamper();
    test_join_accept_cipher_ttn_vector();
    test_join_accept_mic_ttn_vectors();
    test_encode_legacy_matches_vector();
    test_roundtrip_optneg_and_cflist();
    test_optneg_changes_mic_key();
    test_encode_buffer_too_small();
    test_end_to_end_join_then_uplink();
    test_fuzz_join_decoders();
    test_rejoin_join_accept_roundtrip_and_binding();
}
