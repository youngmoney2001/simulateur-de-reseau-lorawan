// SPDX-License-Identifier: Apache-2.0
// Moteur à événements discrets et simulation de liaisons montantes.
#include <cmath>
#include <cstdint>
#include <limits>
#include <vector>

#include "check.hpp"
#include "lsim/engine.hpp"

namespace {

using namespace lsim::sim;

EndDeviceSpec device_at(double x_m, std::uint8_t sf, SimTime start_ns) {
    EndDeviceSpec d;
    d.position.x_m = x_m;
    d.spreading_factor = sf;
    d.payload_bytes = 10;
    d.tx_power_dbm = 14.0;
    d.start_offset_ns = start_ns;
    d.period_ns = 600'000'000'000;  // une seule trame dans la fenêtre
    d.messages = 1;
    return d;
}

GatewaySpec gateway() { return GatewaySpec{}; }

void test_queue_order_and_capacity() {
    EventQueue q(4);
    CHECK_TRUE(q.push(5, 0, 0));
    CHECK_TRUE(q.push(1, 1, 1));
    CHECK_TRUE(q.push(1, 2, 2));  // même temps : l'ordre d'insertion départage
    CHECK_TRUE(q.push(3, 3, 3));
    CHECK_TRUE(!q.push(0, 9, 9));  // capacité atteinte : refus, pas de croissance
    CHECK_EQ(q.size(), std::size_t{4});

    Event e;
    CHECK_TRUE(q.pop(e)); CHECK_EQ(e.time, SimTime{1}); CHECK_EQ(e.kind, std::uint32_t{1});
    CHECK_TRUE(q.pop(e)); CHECK_EQ(e.time, SimTime{1}); CHECK_EQ(e.kind, std::uint32_t{2});
    CHECK_TRUE(q.pop(e)); CHECK_EQ(e.time, SimTime{3});
    CHECK_TRUE(q.pop(e)); CHECK_EQ(e.time, SimTime{5});
    CHECK_TRUE(q.empty());
    CHECK_TRUE(!q.pop(e));
}

void test_single_close_device_received() {
    const EndDeviceSpec d[] = {device_at(10.0, 7, 0)};
    DeviceStats st[1];
    SimulationStats tot;
    CHECK_EQ(static_cast<int>(simulate_uplinks(d, 1, gateway(), PropagationSpec{}, st, tot)),
             static_cast<int>(SimStatus::Ok));
    CHECK_EQ(st[0].sent, std::uint64_t{1});
    CHECK_EQ(st[0].received, std::uint64_t{1});
    CHECK_EQ(tot.sent, std::uint64_t{1});
    CHECK_EQ(tot.received, std::uint64_t{1});
    CHECK_EQ(tot.lost_collision, std::uint64_t{0});
}

void test_far_device_below_sensitivity() {
    const EndDeviceSpec d[] = {device_at(1'000'000.0, 7, 0)};
    DeviceStats st[1];
    SimulationStats tot;
    CHECK_EQ(static_cast<int>(simulate_uplinks(d, 1, gateway(), PropagationSpec{}, st, tot)),
             static_cast<int>(SimStatus::Ok));
    CHECK_EQ(st[0].received, std::uint64_t{0});
    CHECK_EQ(st[0].lost_sensitivity, std::uint64_t{1});
}

void test_non_overlapping_no_collision() {
    // Deux trames séparées de 10 s : bien plus long que l'airtime SF7 (~50 ms).
    const EndDeviceSpec d[] = {device_at(100.0, 7, 0), device_at(100.0, 7, 10'000'000'000)};
    DeviceStats st[2];
    SimulationStats tot;
    simulate_uplinks(d, 2, gateway(), PropagationSpec{}, st, tot);
    CHECK_EQ(tot.received, std::uint64_t{2});
    CHECK_EQ(tot.lost_collision, std::uint64_t{0});
}

void test_equal_power_collision_destroys_both() {
    // Même distance, même SF, même instant : aucun écart pour la capture.
    const EndDeviceSpec d[] = {device_at(100.0, 7, 0), device_at(100.0, 7, 0)};
    DeviceStats st[2];
    SimulationStats tot;
    simulate_uplinks(d, 2, gateway(), PropagationSpec{}, st, tot);
    CHECK_EQ(tot.received, std::uint64_t{0});
    CHECK_EQ(tot.lost_collision, std::uint64_t{2});
}

void test_capture_effect() {
    // Émetteur proche (~ -44 dBm) contre émetteur lointain (~ -98 dBm) : écart > 6 dB.
    const EndDeviceSpec d[] = {device_at(10.0, 7, 0), device_at(1000.0, 7, 0)};
    DeviceStats st[2];
    SimulationStats tot;
    simulate_uplinks(d, 2, gateway(), PropagationSpec{}, st, tot);
    CHECK_EQ(st[0].received, std::uint64_t{1});  // capturé
    CHECK_EQ(st[1].lost_collision, std::uint64_t{1});
    CHECK_EQ(st[1].received, std::uint64_t{0});
}

void test_different_sf_are_orthogonal() {
    // Même instant, SF différents : pas de collision (quasi-orthogonalité).
    const EndDeviceSpec d[] = {device_at(100.0, 7, 0), device_at(100.0, 9, 0)};
    DeviceStats st[2];
    SimulationStats tot;
    simulate_uplinks(d, 2, gateway(), PropagationSpec{}, st, tot);
    CHECK_EQ(tot.received, std::uint64_t{2});
    CHECK_EQ(tot.lost_collision, std::uint64_t{0});
}

void test_totals_match_per_device_sums() {
    std::vector<EndDeviceSpec> d;
    for (int i = 0; i < 50; ++i) {
        d.push_back(device_at(10.0 + 37.0 * i, static_cast<std::uint8_t>(7 + i % 3), 1'000'000LL * i));
        d.back().messages = 3;
        d.back().period_ns = 2'000'000'000;
    }
    std::vector<DeviceStats> st(d.size());
    SimulationStats tot;
    CHECK_EQ(static_cast<int>(simulate_uplinks(d.data(), d.size(), gateway(), PropagationSpec{},
                                               st.data(), tot)),
             static_cast<int>(SimStatus::Ok));
    std::uint64_t sent = 0, rec = 0, ls = 0, lc = 0;
    for (const auto& s : st) {
        sent += s.sent; rec += s.received; ls += s.lost_sensitivity; lc += s.lost_collision;
        CHECK_EQ(s.sent, s.received + s.lost_sensitivity + s.lost_collision);
    }
    CHECK_EQ(tot.sent, sent);
    CHECK_EQ(tot.received, rec);
    CHECK_EQ(tot.lost_sensitivity, ls);
    CHECK_EQ(tot.lost_collision, lc);
    CHECK_EQ(tot.sent, std::uint64_t{150});
}

void test_deterministic() {
    std::vector<EndDeviceSpec> d;
    for (int i = 0; i < 30; ++i) {
        d.push_back(device_at(5.0 * i, 7, 0));
        d.back().messages = 2;
        d.back().period_ns = 1'000'000'000;
    }
    std::vector<DeviceStats> a(d.size()), b(d.size());
    SimulationStats ta, tb;
    simulate_uplinks(d.data(), d.size(), gateway(), PropagationSpec{}, a.data(), ta);
    simulate_uplinks(d.data(), d.size(), gateway(), PropagationSpec{}, b.data(), tb);
    CHECK_EQ(ta.received, tb.received);
    CHECK_EQ(ta.lost_collision, tb.lost_collision);
    for (std::size_t i = 0; i < d.size(); ++i) {
        CHECK_EQ(a[i].received, b[i].received);
        CHECK_EQ(a[i].lost_collision, b[i].lost_collision);
    }
}

void test_invalid_inputs_rejected() {
    DeviceStats st[1];
    SimulationStats tot;
    const EndDeviceSpec bad_sf[] = {device_at(10.0, 6, 0)};
    CHECK_EQ(static_cast<int>(simulate_uplinks(bad_sf, 1, gateway(), PropagationSpec{}, st, tot)),
             static_cast<int>(SimStatus::InvalidInput));
    const EndDeviceSpec bad_sf13[] = {device_at(10.0, 13, 0)};
    CHECK_EQ(static_cast<int>(simulate_uplinks(bad_sf13, 1, gateway(), PropagationSpec{}, st, tot)),
             static_cast<int>(SimStatus::InvalidInput));

    EndDeviceSpec zero = device_at(10.0, 7, 0);
    zero.messages = 0;
    const EndDeviceSpec zero_msg[] = {zero};
    CHECK_EQ(static_cast<int>(simulate_uplinks(zero_msg, 1, gateway(), PropagationSpec{}, st, tot)),
             static_cast<int>(SimStatus::InvalidInput));

    PropagationSpec p;
    p.exponent = -1.0;
    const EndDeviceSpec ok[] = {device_at(10.0, 7, 0)};
    CHECK_EQ(static_cast<int>(simulate_uplinks(ok, 1, gateway(), p, st, tot)),
             static_cast<int>(SimStatus::InvalidInput));

    CHECK_EQ(static_cast<int>(simulate_uplinks(nullptr, 1, gateway(), PropagationSpec{}, st, tot)),
             static_cast<int>(SimStatus::InvalidInput));
}

void test_device_count_limit() {
    std::vector<EndDeviceSpec> d(kMaxEndDevices + 1, device_at(10.0, 7, 0));
    SimulationStats tot;
    CHECK_EQ(static_cast<int>(simulate_uplinks(d.data(), d.size(), gateway(), PropagationSpec{},
                                               nullptr, tot)),
             static_cast<int>(SimStatus::TooManyDevices));
}

void test_shadowing_sample_properties() {
    // Désactivé : valeur nulle.
    CHECK_EQ(shadowing_sample_db(42, 7, 0.0), 0.0);
    // Reproductible : même graine, même index.
    CHECK_EQ(shadowing_sample_db(42, 7, 6.0), shadowing_sample_db(42, 7, 6.0));
    // Indépendant selon l'index et la graine.
    CHECK_TRUE(shadowing_sample_db(42, 7, 6.0) != shadowing_sample_db(42, 8, 6.0));
    CHECK_TRUE(shadowing_sample_db(42, 7, 6.0) != shadowing_sample_db(43, 7, 6.0));
    // Distribution : moyenne ~ 0, écart-type ~ sigma sur un grand échantillon.
    const double sigma = 6.0;
    const std::uint32_t n = 20000;
    double sum = 0.0;
    double sum2 = 0.0;
    for (std::uint32_t i = 0; i < n; ++i) {
        const double v = shadowing_sample_db(2026, i, sigma);
        sum += v;
        sum2 += v * v;
    }
    const double mean = sum / n;
    const double sd = std::sqrt(sum2 / n - mean * mean);
    CHECK_NEAR(mean, 0.0, 0.15);
    CHECK_NEAR(sd, sigma, 0.15);
}

void test_shadowing_input_limits() {
    SimulationStats tot;
    DeviceStats st[1];
    const EndDeviceSpec ok[] = {device_at(10.0, 7, 0)};
    const double bad[] = {-1.0, 31.0, std::numeric_limits<double>::quiet_NaN()};
    for (double sigma : bad) {
        PropagationSpec p;
        p.shadowing_sigma_db = sigma;
        CHECK_EQ(static_cast<int>(simulate_uplinks(ok, 1, gateway(), p, st, tot)),
                 static_cast<int>(SimStatus::InvalidInput));
    }
    PropagationSpec max_ok;
    max_ok.shadowing_sigma_db = 30.0;
    CHECK_EQ(static_cast<int>(simulate_uplinks(ok, 1, gateway(), max_ok, st, tot)),
             static_cast<int>(SimStatus::Ok));
}

void test_gateway_load_metrics() {
    // Deux trames simultanées (t = 0) et une trame isolée (t = 1 s), même SF et charge.
    const EndDeviceSpec d[] = {device_at(10.0, 7, 0), device_at(10.0, 7, 0),
                               device_at(10.0, 7, 1'000'000'000)};
    DeviceStats st[3];
    SimulationStats tot;
    CHECK_EQ(static_cast<int>(simulate_uplinks(d, 3, gateway(), PropagationSpec{}, st, tot)),
             static_cast<int>(SimStatus::Ok));
    const auto airtime = static_cast<SimTime>(st[0].airtime_ns);
    CHECK_TRUE(airtime > 0);
    CHECK_EQ(st[1].airtime_ns, st[0].airtime_ns);
    CHECK_EQ(st[2].airtime_ns, st[0].airtime_ns);
    CHECK_EQ(tot.airtime_ns, 3 * st[0].airtime_ns);
    // Union : [0, A) couvre les deux trames simultanées, puis [1 s, 1 s + A).
    CHECK_EQ(static_cast<SimTime>(tot.gateway_busy_ns), 2 * airtime);
    CHECK_EQ(tot.observation_ns, 1'000'000'000 + airtime);
    CHECK_EQ(tot.gateway_peak_concurrent, std::uint64_t{2});
    CHECK_NEAR(tot.gateway_utilization,
               static_cast<double>(2 * airtime) / static_cast<double>(1'000'000'000 + airtime), 1e-12);
}

void test_gateway_load_without_traffic() {
    SimulationStats tot;
    DeviceStats st[1];
    const EndDeviceSpec none[] = {device_at(10.0, 7, 0)};
    simulate_uplinks(none, 1, gateway(), PropagationSpec{}, st, tot);
    CHECK_TRUE(tot.gateway_utilization >= 0.0 && tot.gateway_utilization <= 1.0);
    SimulationStats empty;
    simulate_uplinks(nullptr, 0, gateway(), PropagationSpec{}, nullptr, empty);
    CHECK_EQ(empty.gateway_busy_ns, std::uint64_t{0});
    CHECK_EQ(empty.gateway_peak_concurrent, std::uint64_t{0});
    CHECK_NEAR(empty.gateway_utilization, 0.0, 0.0);
}

}  // namespace

void run_engine_tests() {
    test_gateway_load_metrics();
    test_gateway_load_without_traffic();
    test_shadowing_sample_properties();
    test_shadowing_input_limits();
    test_queue_order_and_capacity();
    test_single_close_device_received();
    test_far_device_below_sensitivity();
    test_non_overlapping_no_collision();
    test_equal_power_collision_destroys_both();
    test_capture_effect();
    test_different_sf_are_orthogonal();
    test_totals_match_per_device_sums();
    test_deterministic();
    test_invalid_inputs_rejected();
    test_device_count_limit();
}
