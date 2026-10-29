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
    CHECK_EQ(forward(radio_sf12(), n, rssi.data(), next, 0, &f, 1, &d), Status::Ok);
    CHECK_EQ(d.frame_id, std::uint64_t{42});
    CHECK_EQ(d.delivered, std::uint8_t{1});
    CHECK_EQ(d.hops, std::uint8_t{2});
    CHECK_EQ(d.latency_ns, 2 * std::int64_t{1'114'798'030});
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
    CHECK_EQ(forward(radio_sf12(), n, rssi.data(), next, 0, &f, 1, &d), Status::Ok);
    CHECK_EQ(d.delivered, std::uint8_t{0});
    CHECK_EQ(d.loss, static_cast<std::uint8_t>(Loss::NoRoute));
    CHECK_EQ(d.latency_ns, std::int64_t{-1});
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
}
