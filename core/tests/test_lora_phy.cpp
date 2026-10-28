// SPDX-License-Identifier: Apache-2.0
// Tests unitaires du cœur (harnais minimal, sans dépendance externe).
#include <cstdint>
#include <cstdio>

#include "lsim/lora_phy.hpp"

namespace {

int g_failures = 0;
int g_checks = 0;

#define CHECK_EQ(actual, expected)                                              \
    do {                                                                        \
        ++g_checks;                                                             \
        const auto a_ = (actual);                                               \
        const auto e_ = (expected);                                             \
        if (!(a_ == e_)) {                                                      \
            ++g_failures;                                                       \
            std::fprintf(stderr, "FAIL %s:%d: %s == %s (obtenu %lld, attendu %lld)\n", \
                         __FILE__, __LINE__, #actual, #expected,                \
                         static_cast<long long>(a_), static_cast<long long>(e_)); \
        }                                                                       \
    } while (0)

using namespace lsim::lora;

RadioConfig make(std::uint8_t sf, Bandwidth bw, std::uint8_t cr = 1) {
    RadioConfig c;
    c.spreading_factor = sf;
    c.bandwidth = bw;
    c.coding_rate = cr;
    return c;
}

void test_symbol_duration_exact() {
    // 2^7 / 125 kHz = 1.024 ms
    CHECK_EQ(symbol_duration_ns(7, Bandwidth::Bw125kHz), std::int64_t{1'024'000});
    // 2^12 / 125 kHz = 32.768 ms
    CHECK_EQ(symbol_duration_ns(12, Bandwidth::Bw125kHz), std::int64_t{32'768'000});
    // 2^7 / 500 kHz = 256 us
    CHECK_EQ(symbol_duration_ns(7, Bandwidth::Bw500kHz), std::int64_t{256'000});
}

void test_known_airtime_sf7_10_bytes() {
    // SF7, 125 kHz, CR 4/5, 10 octets, CRC, en-tête explicite :
    // préambule 12,544 ms + charge utile 28,672 ms = 41,216 ms.
    const AirtimeResult r = time_on_air(make(7, Bandwidth::Bw125kHz), 10);
    CHECK_EQ(static_cast<int>(r.status), 0);
    CHECK_EQ(r.nanoseconds, std::int64_t{41'216'000});
}

void test_airtime_sf12_uses_low_dr_optimisation() {
    RadioConfig c = make(12, Bandwidth::Bw125kHz);
    CHECK_EQ(low_data_rate_required(12, Bandwidth::Bw125kHz), true);
    c.low_data_rate_optimize = true;
    const AirtimeResult r = time_on_air(c, 10);
    CHECK_EQ(static_cast<int>(r.status), 0);
    // Calcul détaillé : préambule 8 + 4,25 symboles = 401,408 ms ;
    // charge utile 8 + 2 * 5 = 18 symboles = 589,824 ms ; total 991,232 ms.
    CHECK_EQ(r.nanoseconds, std::int64_t{991'232'000});
}

void test_airtime_monotonic_in_payload() {
    const RadioConfig c = make(9, Bandwidth::Bw125kHz);
    std::int64_t prev = 0;
    for (std::uint32_t n = 0; n <= 255; ++n) {
        const AirtimeResult r = time_on_air(c, n);
        CHECK_EQ(static_cast<int>(r.status), 0);
        CHECK_EQ(r.nanoseconds >= prev, true);
        prev = r.nanoseconds;
    }
}

void test_airtime_monotonic_in_sf() {
    std::int64_t prev = 0;
    for (std::uint8_t sf = 7; sf <= 12; ++sf) {
        const AirtimeResult r = time_on_air(make(sf, Bandwidth::Bw125kHz), 20);
        CHECK_EQ(r.nanoseconds > prev, true);
        prev = r.nanoseconds;
    }
}

void test_rejects_invalid_inputs() {
    CHECK_EQ(static_cast<int>(time_on_air(make(6, Bandwidth::Bw125kHz), 1).status),
             static_cast<int>(Status::InvalidSpreadingFactor));
    CHECK_EQ(static_cast<int>(time_on_air(make(13, Bandwidth::Bw125kHz), 1).status),
             static_cast<int>(Status::InvalidSpreadingFactor));
    CHECK_EQ(static_cast<int>(time_on_air(make(7, static_cast<Bandwidth>(100'000)), 1).status),
             static_cast<int>(Status::InvalidBandwidth));
    CHECK_EQ(static_cast<int>(time_on_air(make(7, Bandwidth::Bw125kHz, 0), 1).status),
             static_cast<int>(Status::InvalidCodingRate));
    CHECK_EQ(static_cast<int>(time_on_air(make(7, Bandwidth::Bw125kHz, 5), 1).status),
             static_cast<int>(Status::InvalidCodingRate));
    CHECK_EQ(static_cast<int>(time_on_air(make(7, Bandwidth::Bw125kHz), 256).status),
             static_cast<int>(Status::InvalidPayloadSize));
    RadioConfig bad_preamble = make(7, Bandwidth::Bw125kHz);
    bad_preamble.preamble_symbols = 5;
    CHECK_EQ(static_cast<int>(time_on_air(bad_preamble, 1).status),
             static_cast<int>(Status::InvalidPreamble));
}

}  // namespace

int main() {
    test_symbol_duration_exact();
    test_known_airtime_sf7_10_bytes();
    test_airtime_sf12_uses_low_dr_optimisation();
    test_airtime_monotonic_in_payload();
    test_airtime_monotonic_in_sf();
    test_rejects_invalid_inputs();

    std::printf("%d/%d vérifications réussies\n", g_checks - g_failures, g_checks);
    return g_failures == 0 ? 0 : 1;
}
