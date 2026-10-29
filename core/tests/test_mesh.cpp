// SPDX-License-Identifier: Apache-2.0
// Tests unitaires : relais mesh 2,4 GHz (airtime, sensibilité, routes, relais, erreurs).
#include <cstdint>
#include <limits>
#include <vector>

#include "check.hpp"
#include "lsim/mesh.hpp"

namespace {

using namespace lsim::mesh;

Radio radio_sf12() {
    Radio r;
    r.spreading_factor = 12;
    r.bandwidth_hz = 203'000;
    r.payload_bytes = 32;
    return r;
}

void test_airtime_reference_value() {
    // Valeur de référence (même formule qu'AN1200.13, vérifiée côté Python).
    std::int64_t ns = 0;
    CHECK_EQ(airtime_ns(radio_sf12(), ns), Status::Ok);
    CHECK_EQ(ns, std::int64_t{1'114'798'030});
}

void test_airtime_matches_125_khz_reference() {
    // SF7/125 kHz, 10 octets, CR 4/5 : 41,216 ms (valeur du cœur LoRa).
    Radio r;
    r.spreading_factor = 7;
    r.bandwidth_hz = 125'000;
    r.payload_bytes = 10;
    std::int64_t ns = 0;
    CHECK_EQ(airtime_ns(r, ns), Status::Ok);
    CHECK_EQ(ns, std::int64_t{41'216'000});
}

void test_sensitivity_table() {
    std::int32_t s = 0;
    CHECK_EQ(sensitivity_dbm(radio_sf12(), s), Status::Ok);
    CHECK_EQ(s, -130);
    Radio r;
    r.spreading_factor = 7;
    r.bandwidth_hz = 1'625'000;
    CHECK_EQ(sensitivity_dbm(r, s), Status::Ok);
    CHECK_EQ(s, -106);
    r.bandwidth_hz = 125'000;  // hors tableau SX1280
    CHECK_EQ(sensitivity_dbm(r, s), Status::InvalidRadio);
}

void test_invalid_radio_is_refused() {
    Radio r = radio_sf12();
    r.spreading_factor = 4;
    std::int64_t ns = 0;
    CHECK_EQ(airtime_ns(r, ns), Status::InvalidRadio);
    r = radio_sf12();
    r.payload_bytes = 256;
    CHECK_EQ(airtime_ns(r, ns), Status::InvalidRadio);
    r = radio_sf12();
    r.capture_db = -1.0;
    CHECK_EQ(airtime_ns(r, ns), Status::InvalidRadio);
}

// Chaîne 0-1-…-(n-1) : seuls les voisins immédiats sont audibles.
std::vector<double> chain_rssi(std::size_t n, double strong) {
    std::vector<double> rssi(n * n, -300.0);
    for (std::size_t i = 0; i + 1 < n; ++i) {
        rssi[i * n + (i + 1)] = strong;
        rssi[(i + 1) * n + i] = strong;
    }
    return rssi;
}

void test_routes_follow_chain() {
    constexpr std::size_t n = 4;
    const auto rssi = chain_rssi(n, -100.0);
    const std::uint8_t capable[n] = {1, 1, 1, 1};
    std::int32_t next[n] = {-9, -9, -9, -9};
    CHECK_EQ(routes(radio_sf12(), n, capable, rssi.data(), 0, 8, next), Status::Ok);
    CHECK_EQ(next[0], 0);
    CHECK_EQ(next[1], 0);
    CHECK_EQ(next[2], 1);
    CHECK_EQ(next[3], 2);
}

void test_hop_limit_is_enforced() {
    constexpr std::size_t n = 10;  // nœud 9 est à 9 sauts : hors limite
    const auto rssi = chain_rssi(n, -100.0);
    std::uint8_t capable[n];
    for (auto& c : capable) c = 1;
    std::int32_t next[n];
    CHECK_EQ(routes(radio_sf12(), n, capable, rssi.data(), 0, kMaxHops, next), Status::Ok);
    CHECK_EQ(next[8], 7);
    CHECK_EQ(next[9], -1);
    CHECK_EQ(routes(radio_sf12(), n, capable, rssi.data(), 0, 9, next), Status::InvalidHops);
}

void test_border_must_be_capable() {
    constexpr std::size_t n = 2;
    const auto rssi = chain_rssi(n, -100.0);
    const std::uint8_t capable[n] = {0, 1};
    std::int32_t next[n];
    CHECK_EQ(routes(radio_sf12(), n, capable, rssi.data(), 0, 8, next), Status::BorderNotCapable);
}

void test_two_hop_frame_latency() {
    constexpr std::size_t n = 3;
    const auto rssi = chain_rssi(n, -100.0);
    const std::uint8_t capable[n] = {1, 1, 1};
    std::int32_t next[n];
    CHECK_EQ(routes(radio_sf12(), n, capable, rssi.data(), 0, 8, next), Status::Ok);
    Frame f;
    f.frame_id = 42;
    f.rx_node = 2;
    f.t_ns = 1000;
    Delivery d;
    Summary sum;
    CHECK_EQ(forward(radio_sf12(), n, capable, rssi.data(), next, 0, true, 0, &f, 1, &d, &sum),
             Status::Ok);
    CHECK_EQ(sum.transmissions, std::uint64_t{2});
    CHECK_EQ(sum.suppressed, std::uint64_t{0});
    CHECK_EQ(d.frame_id, std::uint64_t{42});
    CHECK_EQ(d.delivered, std::uint8_t{1});
    CHECK_EQ(d.hops, std::uint8_t{2});
    CHECK_EQ(d.latency_ns, 2 * std::int64_t{1'114'798'030});
}

// Trois nœuds : 0 frontière, 1 et 2 relais. Tous s'entendent. Le relais 1 transmet la
// trame à t = 0 ; le relais 2 l'entend finir (il n'en est pas le destinataire prévu) avant
// de recevoir sa propre copie à t = 1,5 T. Sans suppression, le relais 2 retransmet.
struct OverhearSetup {
    static constexpr std::size_t n = 3;
    std::vector<double> rssi = std::vector<double>(9, -100.0);
    std::uint8_t capable[3] = {1, 1, 1};
    std::int32_t next[3] = {0, 0, 0};
    OverhearSetup() {
        for (std::size_t i = 0; i < n; ++i) rssi[i * n + i] = -300.0;
    }
};

void test_overhearing_suppresses_duplicate() {
    OverhearSetup s;
    const std::int64_t T = 1'114'798'030;
    Frame frames[2];
    frames[0].frame_id = 7;
    frames[0].rx_node = 1;
    frames[0].t_ns = 0;
    frames[1].frame_id = 7;
    frames[1].rx_node = 2;
    frames[1].t_ns = T + T / 2;
    Delivery out[2];
    Summary sum;
    // Le relais 1 ayant transmis vers la frontière, la copie du relais 2 est supprimée.
    CHECK_EQ(forward(radio_sf12(), OverhearSetup::n, s.capable, s.rssi.data(), s.next, 0, true, 0,
                     frames, 2, out, &sum),
             Status::Ok);
    CHECK_EQ(sum.transmissions, std::uint64_t{1});
    CHECK_EQ(sum.suppressed, std::uint64_t{1});
    CHECK_EQ(sum.lost_collision, std::uint64_t{0});
    CHECK_EQ(out[0].delivered, std::uint8_t{1});
    CHECK_EQ(out[0].hops, std::uint8_t{1});
    CHECK_EQ(out[1].copy_state, static_cast<std::uint8_t>(CopyState::Suppressed));
}

void test_without_suppression_both_copies_are_relayed() {
    OverhearSetup s;
    const std::int64_t T = 1'114'798'030;
    Frame frames[2];
    frames[0].frame_id = 7;
    frames[0].rx_node = 1;
    frames[0].t_ns = 0;
    frames[1].frame_id = 7;
    frames[1].rx_node = 2;
    frames[1].t_ns = T + T / 2;
    Delivery out[2];
    Summary sum;
    CHECK_EQ(forward(radio_sf12(), OverhearSetup::n, s.capable, s.rssi.data(), s.next, 0, false, 0,
                     frames, 2, out, &sum),
             Status::Ok);
    CHECK_EQ(sum.transmissions, std::uint64_t{2});
    CHECK_EQ(sum.suppressed, std::uint64_t{0});
    CHECK_EQ(out[1].copy_state, static_cast<std::uint8_t>(CopyState::Forwarded));
}

void test_no_route_is_reported() {
    constexpr std::size_t n = 2;
    std::vector<double> rssi(n * n, -300.0);
    const std::uint8_t capable[n] = {1, 1};
    std::int32_t next[n];
    CHECK_EQ(routes(radio_sf12(), n, capable, rssi.data(), 0, 8, next), Status::Ok);
    CHECK_EQ(next[1], -1);
    Frame f;
    f.rx_node = 1;
    Delivery d;
    Summary sum;
    CHECK_EQ(forward(radio_sf12(), n, capable, rssi.data(), next, 0, true, 0, &f, 1, &d, &sum),
             Status::Ok);
    CHECK_EQ(d.copy_state, static_cast<std::uint8_t>(CopyState::NoRoute));
    CHECK_EQ(d.delivered, std::uint8_t{0});
    CHECK_EQ(d.loss, static_cast<std::uint8_t>(Loss::NoRoute));
    CHECK_EQ(d.latency_ns, std::int64_t{-1});
}

void test_frame_size_sets_its_own_airtime() {
    // Chaîne 0-1 : une trame de 10 o relayée d'un saut met son temps d'antenne 10 o.
    constexpr std::size_t n = 2;
    const auto rssi = chain_rssi(n, -100.0);
    const std::uint8_t capable[n] = {1, 1};
    std::int32_t next[n];
    CHECK_EQ(routes(radio_sf12(), n, capable, rssi.data(), 0, 8, next), Status::Ok);
    Frame f;
    f.frame_id = 5;
    f.rx_node = 1;
    f.t_ns = 0;
    f.payload_bytes = 10;
    Delivery d;
    Summary sum;
    CHECK_EQ(forward(radio_sf12(), n, capable, rssi.data(), next, 0, true, 0, &f, 1, &d, &sum),
             Status::Ok);
    Radio r = radio_sf12();
    r.payload_bytes = 10;
    std::int64_t expected = 0;
    CHECK_EQ(airtime_ns(r, expected), Status::Ok);
    CHECK_EQ(d.latency_ns, expected);
    f.payload_bytes = 256;
    CHECK_EQ(forward(radio_sf12(), n, capable, rssi.data(), next, 0, true, 0, &f, 1, &d, &sum),
             Status::InvalidRadio);
}

}  // namespace

void run_mesh_tests() {
    test_airtime_reference_value();
    test_airtime_matches_125_khz_reference();
    test_sensitivity_table();
    test_invalid_radio_is_refused();
    test_routes_follow_chain();
    test_hop_limit_is_enforced();
    test_border_must_be_capable();
    test_two_hop_frame_latency();
    test_no_route_is_reported();
    test_overhearing_suppresses_duplicate();
    test_without_suppression_both_copies_are_relayed();
    test_frame_size_sets_its_own_airtime();
}
