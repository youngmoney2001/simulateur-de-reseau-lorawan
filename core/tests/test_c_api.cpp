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

void test_simulate_with_environment() {
    const lsim_gateway g{0.0, 0.0, 0.0, 0.0};
    const lsim_propagation p{868.1e6, 1.0, 2.7, 6.0, 0.0, 0};
    lsim_end_device d[1] = {{1000.0, 0.0, 7, 10, 14.0, 0, 600000000000LL, 1, 1.0}};
    lsim_device_stats per[1]{};
    lsim_sim_stats tot{};

    // env NULL : identique à l'API sans environnement.
    CHECK_EQ(lsim_simulate_uplinks_env(d, 1, &g, &p, nullptr, per, &tot), 0);
    const uint64_t base_received = tot.received;

    // Obstacle épais et haut, traversé : perte supplémentaire -> perte de réception.
    lsim_obstacle wall{500.0, -50.0, 600.0, 50.0, 30.0, 200.0};
    lsim_environment e{};
    e.obstacles = &wall;
    e.obstacle_count = 1;
    e.gateway_height_m = 15.0;
    e.device_height_m = 1.5;
    CHECK_EQ(lsim_simulate_uplinks_env(d, 1, &g, &p, &e, per, &tot), 0);
    CHECK_EQ(tot.received, uint64_t{0});
    CHECK_TRUE(base_received >= tot.received);

    // Grille hors bornes (4 002 000 cellules > 4 000 000) : refusée avant toute lecture.
    const float z[1] = {0.0f};
    lsim_environment bad{};
    bad.grid_z = z;
    bad.grid_nx = 2000;
    bad.grid_ny = 2001;
    bad.grid_cell_m = 10.0;
    CHECK_EQ(lsim_simulate_uplinks_env(d, 1, &g, &p, &bad, per, &tot), 500 + 2);  // GridTooLarge

    // Pas de grille nul : refusé.
    lsim_environment zero{};
    zero.grid_z = z;
    zero.grid_nx = 1;
    zero.grid_ny = 1;
    zero.grid_cell_m = 0.0;
    CHECK_EQ(lsim_simulate_uplinks_env(d, 1, &g, &p, &zero, per, &tot), 500 + 1);  // InvalidGrid

    // Obstacle non fini : refusé.
    lsim_obstacle nan_wall{0.0, 0.0, 1.0, 1.0, 1.0, 0.0};
    nan_wall.height_m = 0.0 / 0.0;
    lsim_environment nan_env{};
    nan_env.obstacles = &nan_wall;
    nan_env.obstacle_count = 1;
    CHECK_EQ(lsim_simulate_uplinks_env(d, 1, &g, &p, &nan_env, per, &tot) == 0, false);

    // Pointeur d'obstacles nul avec un nombre non nul : refus.
    lsim_environment null_env{};
    null_env.obstacle_count = 1;
    CHECK_EQ(lsim_simulate_uplinks_env(d, 1, &g, &p, &null_env, per, &tot),
             500 + 5);
}

void test_v104_c_api_vectors() {
    // Mêmes vecteurs que test_secure_frame.cpp (recalculés hors C++ avec cryptography).
    uint8_t app_key[16];
    for (int i = 0; i < 16; ++i) app_key[i] = static_cast<uint8_t>(0x10 + i);
    const uint8_t an[3] = {0x01, 0x02, 0x03};
    const uint8_t ni[3] = {0x00, 0x00, 0x13};
    const uint8_t dn[2] = {0xaa, 0x55};
    lsim_session_keys_10 k{};
    CHECK_EQ(lsim_derive_session_keys_10(app_key, an, ni, dn, &k), 0);
    CHECK_EQ(k.nwk_s_key[0], uint8_t{0x1b});
    CHECK_EQ(k.app_s_key[15], uint8_t{0xfd});

    lsim_session_keys_10 keys{};
    for (int i = 0; i < 16; ++i) {
        keys.nwk_s_key[i] = static_cast<uint8_t>(i);
        keys.app_s_key[i] = static_cast<uint8_t>(0xf0 + i);
    }
    lsim_uplink_frame f{};
    f.dev_addr = 0x01020304u;
    f.mtype = 2;
    f.fcnt = 5;
    f.fopts[0] = 0x02;
    f.fopts_len = 1;
    f.has_fport = 1;
    f.fport = 1;
    f.payload_len = 5;
    std::memcpy(f.payload, "hello", 5);
    lsim_uplink_context c{};
    c.fcnt32 = 5;
    uint8_t wire[64];
    size_t n = 0;
    CHECK_EQ(lsim_seal_uplink_10(&f, &keys, &c, wire, sizeof wire, &n), 0);
    const uint8_t expected[19] = {0x40, 0x04, 0x03, 0x02, 0x01, 0x01, 0x05, 0x00, 0x02, 0x01,
                                  0xc5, 0xcb, 0x1f, 0xc5, 0xa6, 0x9b, 0x45, 0x16, 0x09};
    CHECK_EQ(n, size_t{19});
    CHECK_TRUE(std::memcmp(wire, expected, 19) == 0);

    lsim_uplink_frame out{};
    CHECK_EQ(lsim_open_uplink_10(wire, n, &keys, &c, &out), 0);
    CHECK_EQ(out.payload_len, 5);
    CHECK_TRUE(std::memcmp(out.payload, "hello", 5) == 0);
    // Le profil 1.1 ne doit pas accepter une trame 1.0.x.
    lsim_session_keys_11 k11 = derive();
    CHECK_TRUE(lsim_open_uplink(wire, n, &k11, &c, &out) != 0);
}

void test_status_ranges_are_disjoint() {
    // Un statut de crypto (100+) ne doit jamais se confondre avec un PHY (0..99).
    lsim_session_keys_11 k{};
    CHECK_TRUE(lsim_derive_session_keys_11(kKey, kKey, kJn, kJeui, kDn, &k) < 100);
}

void test_simulate_totals() {
    const lsim_gateway g{0.0, 0.0, 0.0, 0.0};
    const lsim_propagation p{868.1e6, 1.0, 2.7, 6.0, 0.0, 0};
    lsim_end_device d[2] = {
        {10.0, 0.0, 7, 10, 14.0, 0, 600000000000LL, 1, 1.0},
        {1000000.0, 0.0, 7, 10, 14.0, 0, 600000000000LL, 1, 1.0},
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

void test_multi_gateway_c_api() {
    lsim_end_device d{};
    d.x_m = 20000.0;
    d.spreading_factor = 7;
    d.payload_bytes = 10;
    d.tx_power_dbm = 14.0;
    d.period_ns = 600000000000LL;
    d.messages = 1;
    d.duty_cycle = 1.0;
    lsim_gateway g[2] = {{0.0, 0.0, 0.0, 0.0}, {20000.0, 100.0, 0.0, 0.0}};
    lsim_propagation prop{};
    prop.frequency_hz = 868.1e6;
    prop.reference_distance_m = 1.0;
    prop.exponent = 2.7;
    prop.capture_threshold_db = 6.0;
    lsim_device_stats per_device[1];
    lsim_network_stats tot{};
    lsim_gateway_rx_stats per_gw[2]{};

    // Une passerelle : hors de portée.
    CHECK_EQ(lsim_simulate_uplinks_multi(&d, 1, g, 1, &prop, nullptr, per_device, &tot, per_gw, nullptr, nullptr, nullptr, 0, nullptr),
             0);
    CHECK_EQ(tot.received, uint64_t{0});
    CHECK_EQ(tot.lost_sensitivity, uint64_t{1});

    // Deux passerelles : la seconde reçoit.
    CHECK_EQ(lsim_simulate_uplinks_multi(&d, 1, g, 2, &prop, nullptr, per_device, &tot, per_gw, nullptr, nullptr, nullptr, 0, nullptr),
             0);
    CHECK_EQ(tot.received, uint64_t{1});
    CHECK_EQ(per_gw[1].received, uint64_t{1});
    CHECK_EQ(per_gw[0].lost_sensitivity, uint64_t{1});

    // Bornes : 0 passerelle et 65 passerelles refusées par statut, sans appel au moteur.
    CHECK_TRUE(lsim_simulate_uplinks_multi(&d, 1, g, 0, &prop, nullptr, per_device, &tot, per_gw, nullptr, nullptr, nullptr, 0, nullptr) !=
               0);
    CHECK_TRUE(lsim_simulate_uplinks_multi(&d, 1, g, 65, &prop, nullptr, per_device, &tot,
                                           per_gw, nullptr, nullptr, nullptr, 0, nullptr) != 0);
}

void test_gateway_v2_absolute_abi() {
    // ABI v1 et v2 modèle 0 : mêmes sorties. Modèle 1 : seuil absolu SF5 documenté, refus sinon.
    const lsim_propagation p{868.1e6, 1.0, 2.7, 6.0, 0.0, 0};
    lsim_end_device d7[1] = {{10.0, 0.0, 7, 10, 14.0, 0, 600000000000LL, 1, 1.0}};
    lsim_end_device d5[1] = {{10.0, 0.0, 5, 10, 14.0, 0, 600000000000LL, 1, 1.0}};
    lsim_device_stats per[1]{};
    lsim_sim_stats tot{};
    lsim_tx_record rec1[4]{};
    lsim_tx_record rec2[4]{};
    size_t n1 = 0;
    size_t n2 = 0;
    const lsim_gateway g1{0.0, 0.0, 0.0, 0.0};
    lsim_gateway_v2 g2{};
    g2.base = g1;
    g2.sensitivity_model = LSIM_SENSITIVITY_MODEL_NONE;

    // Modèle 0 et SF7 : identique à la v1 (statut, nombre d'enregistrements, RSSI).
    const int32_t s1 = lsim_simulate_uplinks_trace_v2(d7, 1, &g1, &p, nullptr, per, &tot, rec1, 4, &n1,
                                                      nullptr, 0, nullptr, 0);
    const int32_t s2 = lsim_simulate_uplinks_trace_gw2(d7, 1, &g2, &p, nullptr, per, &tot, rec2, 4, &n2,
                                                       nullptr, 0, nullptr, 0);
    CHECK_EQ(s1, 0);
    CHECK_EQ(s2, 0);
    CHECK_EQ(n1, n2);
    CHECK_TRUE(n1 == 1 && rec1[0].rssi_dbm == rec2[0].rssi_dbm && rec1[0].outcome == rec2[0].outcome);

    // Modèle 0 et SF5 : refusé, comme en v1 (référence SX1276 sans SF5).
    CHECK_TRUE(lsim_simulate_uplinks_trace_v2(d5, 1, &g1, &p, nullptr, per, &tot, rec1, 4, &n1,
                                              nullptr, 0, nullptr, 0) != 0);
    CHECK_TRUE(lsim_simulate_uplinks_trace_gw2(d5, 1, &g2, &p, nullptr, per, &tot, rec2, 4, &n2,
                                               nullptr, 0, nullptr, 0) != 0);

    // Modèle 1 : SF5/125 kHz documenté à −150 dBm : accepté.
    g2.sensitivity_model = LSIM_SENSITIVITY_MODEL_ABSOLUTE_PER_SF_V2;
    g2.present = 1U;
    g2.sensitivity_dbm[0][0] = -150.0;
    CHECK_EQ(lsim_simulate_uplinks_trace_gw2(d5, 1, &g2, &p, nullptr, per, &tot, rec2, 4, &n2,
                                             nullptr, 0, nullptr, 0), 0);
    CHECK_EQ(n2, size_t{1});
    CHECK_EQ(tot.received, uint64_t{1});

    // Modèle 1 : paire absente (SF7 non documenté) : refus, pas de repli.
    CHECK_TRUE(lsim_simulate_uplinks_trace_gw2(d7, 1, &g2, &p, nullptr, per, &tot, rec2, 4, &n2,
                                               nullptr, 0, nullptr, 0) != 0);
    // Modèle 1 avec décalage non nul : refus.
    g2.base.rx_sensitivity_offset_db = 2.0;
    CHECK_TRUE(lsim_simulate_uplinks_trace_gw2(d5, 1, &g2, &p, nullptr, per, &tot, rec2, 4, &n2,
                                               nullptr, 0, nullptr, 0) != 0);
    g2.base.rx_sensitivity_offset_db = 0.0;
    // Modèle inconnu : refus.
    g2.sensitivity_model = 7U;
    CHECK_TRUE(lsim_simulate_uplinks_trace_gw2(d5, 1, &g2, &p, nullptr, per, &tot, rec2, 4, &n2,
                                               nullptr, 0, nullptr, 0) != 0);
}

void run_c_api_tests() {
    test_multi_gateway_c_api();
    test_derive_matches_cpp_vectors();
    test_null_pointers_refused();
    test_seal_open_roundtrip_and_tamper();
    test_v104_c_api_vectors();
    test_status_ranges_are_disjoint();
    test_simulate_totals();
    test_simulate_with_environment();
    test_join_roundtrip_and_vectors();
    test_gateway_v2_absolute_abi();
}
