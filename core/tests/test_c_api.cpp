// SPDX-License-Identifier: Apache-2.0
// Tests de la frontière C (c_api.h) : même comportement que le C++ interne,
// codes de statut dans leurs plages, pointeurs nuls refusés.
#include <cstdint>
#include <cstring>

#include "check.hpp"
#include "lsim/c_api.h"

namespace {

const uint8_t kKey[16] = {0xbe, 0xc4, 0x99, 0xc6, 0x9e, 0x9c, 0x93, 0x9e,
                          0x41, 0x3b, 0x66, 0x39, 0x61, 0x63, 0x6c, 0x61};
const uint8_t kJn[3] = {0x1c, 0x3b, 0xae};          // ordre de transmission
const uint8_t kJeui[8] = {0x42, 0x42, 0x22, 0x23, 0x12, 0x00, 0x00, 0x00};
const uint8_t kDn[2] = {0x69, 0x73};

lsim_session_keys_11 derive() {
    lsim_session_keys_11 k{};
    CHECK_EQ(lsim_derive_session_keys_11(kKey, kKey, kJn, kJeui, kDn, &k), 0);
    return k;
}

void test_derive_matches_cpp_vectors() {
    // Mêmes valeurs que test_crypto.cpp (vecteurs TTN 1.1).
    const lsim_session_keys_11 k = derive();
    CHECK_EQ(k.f_nwk_s_int_key[0], 0x37);
    CHECK_EQ(k.f_nwk_s_int_key[15], 0xa3);
    CHECK_EQ(k.s_nwk_s_int_key[0], 0x63);
    CHECK_EQ(k.nwk_s_enc_key[0], 0xce);
}

void test_null_pointers_refused() {
    lsim_session_keys_11 k{};
    CHECK_EQ(lsim_derive_session_keys_11(nullptr, kKey, kJn, kJeui, kDn, &k), 6);
    CHECK_EQ(lsim_derive_join_keys(kKey, kJeui, nullptr), 6);
    lsim_uplink_frame f{};
    lsim_uplink_context c{};
    uint8_t buf[255];
    size_t n = 7;
    CHECK_EQ(lsim_seal_uplink(&f, &k, &c, buf, sizeof buf, nullptr), 6);
    CHECK_EQ(lsim_seal_uplink(nullptr, &k, &c, buf, sizeof buf, &n), 6);
    CHECK_EQ(n, size_t{7});
}

void test_seal_open_roundtrip_and_tamper() {
    const lsim_session_keys_11 k = derive();
    lsim_uplink_frame f{};
    f.dev_addr = 0x01020304u;
    f.mtype = 2;
    f.fcnt = 5;
    f.has_fport = 1;
    f.fport = 1;
    f.payload_len = 5;
    std::memcpy(f.payload, "hello", 5);
    lsim_uplink_context c{};
    c.fcnt32 = 5;

    uint8_t wire[255];
    size_t n = 0;
    CHECK_EQ(lsim_seal_uplink(&f, &k, &c, wire, sizeof wire, &n), 0);
    CHECK_EQ(n, size_t{9 + 5 + 4});
    CHECK_TRUE(std::memcmp(wire + 9, "hello", 5) != 0);  // chiffré

    lsim_uplink_frame out{};
    CHECK_EQ(lsim_open_uplink(wire, n, &k, &c, &out), 0);
    CHECK_EQ(out.payload_len, 5);
    CHECK_TRUE(std::memcmp(out.payload, "hello", 5) == 0);

    wire[10] ^= 0x01;
    CHECK_EQ(lsim_open_uplink(wire, n, &k, &c, &out), 200 + 2);  // MicMismatch
    CHECK_EQ(out.payload_len, 0);
    for (uint8_t b : out.payload) {
        CHECK_EQ(b, 0);
    }

    // Charge trop grande : refus avant tout calcul.
    lsim_uplink_frame big{};
    big.payload_len = 243;
    CHECK_EQ(lsim_seal_uplink(&big, &k, &c, wire, sizeof wire, &n), 200 + 6);
    CHECK_EQ(n, size_t{0});
}

void test_status_ranges_are_disjoint() {
    // Un statut de crypto (100+) ne doit jamais se confondre avec un PHY (0..99).
    lsim_session_keys_11 k{};
    CHECK_TRUE(lsim_derive_session_keys_11(kKey, kKey, kJn, kJeui, kDn, &k) < 100);
}

void test_simulate_totals() {
    const lsim_gateway g{0.0, 0.0, 0.0};
    const lsim_propagation p{868.1e6, 1.0, 2.7, 6.0};
    lsim_end_device d[2] = {
        {10.0, 0.0, 7, 10, 14.0, 0, 600000000000LL, 1},
        {1000000.0, 0.0, 7, 10, 14.0, 0, 600000000000LL, 1},
    };
    lsim_device_stats per[2]{};
    lsim_sim_stats tot{};
    CHECK_EQ(lsim_simulate_uplinks(d, 2, &g, &p, per, &tot), 0);
    CHECK_EQ(tot.sent, uint64_t{2});
    CHECK_EQ(tot.received, uint64_t{1});
    CHECK_EQ(tot.lost_sensitivity, uint64_t{1});
    CHECK_EQ(per[0].received, uint64_t{1});
    CHECK_EQ(per[1].lost_sensitivity, uint64_t{1});

    // Entrée invalide (SF 13) : statut simulateur, totaux remis à zéro.
    d[0].spreading_factor = 13;
    CHECK_EQ(lsim_simulate_uplinks(d, 2, &g, &p, per, &tot), 301);
    CHECK_EQ(tot.sent, uint64_t{0});
}


void test_join_roundtrip_and_vectors() {
    const uint8_t key[16] = {1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1};
    const uint8_t eui[8] = {0x08, 0x07, 0x06, 0x05, 0x04, 0x03, 0x02, 0x01};
    lsim_join_request req{};
    std::memcpy(req.join_eui, eui, 8);
    std::memcpy(req.dev_eui, eui, 8);
    req.dev_nonce[0] = 0x02;
    req.dev_nonce[1] = 0x01;
    uint8_t wire[23];
    CHECK_EQ(lsim_encode_join_request(&req, key, wire), 0);
    CHECK_TRUE(std::memcmp(wire + 19, "\xe6\xe1\x0c\x55", 4) == 0);  // MIC TTN
    lsim_join_request back{};
    CHECK_EQ(lsim_decode_join_request(wire, 23, key, &back), 0);
    CHECK_TRUE(std::memcmp(back.dev_eui, eui, 8) == 0);
    wire[3] ^= 0x01;
    CHECK_EQ(lsim_decode_join_request(wire, 23, key, &back), 400 + 4);  // MicMismatch
    CHECK_EQ(back.dev_nonce[0], 0);

    lsim_join_accept acc{};
    acc.join_nonce[0] = 0x03; acc.join_nonce[1] = 0x02; acc.join_nonce[2] = 0x01;
    acc.net_id[0] = 0x03; acc.net_id[1] = 0x02; acc.net_id[2] = 0x01;
    acc.dev_addr = 0x01020304u;
    acc.rx_delay = 1;
    const uint8_t jnonce[2] = {0x01, 0x02};
    const uint8_t join_eui_wire[8] = {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08};
    uint8_t ja[33];
    size_t n = 0;
    CHECK_EQ(lsim_encode_join_accept(&acc, key, eui, join_eui_wire, jnonce, ja, sizeof ja, &n), 0);
    CHECK_EQ(n, size_t{17});
    CHECK_TRUE(std::memcmp(ja + 1, "\xc9\xfb\xb2\x59", 4) == 0);  // chiffré TTN
    lsim_join_accept got{};
    CHECK_EQ(lsim_decode_join_accept(ja, n, key, eui, join_eui_wire, jnonce, &got), 0);
    CHECK_EQ(got.dev_addr, 0x01020304u);
    CHECK_EQ(lsim_encode_join_accept(&acc, key, eui, join_eui_wire, jnonce, ja, 16, &n), 400 + 1);
    CHECK_EQ(n, size_t{0});
    ja[7] ^= 0x40;
    CHECK_EQ(lsim_decode_join_accept(ja, 17, key, eui, join_eui_wire, jnonce, &got), 400 + 4);
    CHECK_EQ(got.dev_addr, 0u);
}

}  // namespace

void run_c_api_tests() {
    test_derive_matches_cpp_vectors();
    test_null_pointers_refused();
    test_seal_open_roundtrip_and_tamper();
    test_status_ranges_are_disjoint();
    test_simulate_totals();
    test_join_roundtrip_and_vectors();
}
