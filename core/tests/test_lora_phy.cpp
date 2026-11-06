// SPDX-License-Identifier: Apache-2.0
// Tests unitaires : couche physique LoRa (temps d'antenne, sensibilité).
#include <cstdint>
#include <cstdio>

#include "check.hpp"
#include "lsim/lora_phy.hpp"

namespace {

using namespace lsim::lora;

RadioConfig make(std::uint8_t sf, Bandwidth bw, std::uint8_t cr = 1) {
    RadioConfig c;
    c.spreading_factor = sf;
    c.bandwidth = bw;
    c.coding_rate = cr;
    return c;
}

void test_symbol_duration_exact() {
    CHECK_EQ(symbol_duration_ns(7, Bandwidth::Bw125kHz), std::int64_t{1'024'000});
    CHECK_EQ(symbol_duration_ns(12, Bandwidth::Bw125kHz), std::int64_t{32'768'000});
    CHECK_EQ(symbol_duration_ns(7, Bandwidth::Bw500kHz), std::int64_t{256'000});
}

void test_known_airtime_sf7_10_bytes() {
    // SF7, 125 kHz, CR 4/5, 10 octets : 12,544 ms préambule + 28,672 ms charge utile.
    const AirtimeResult r = time_on_air(make(7, Bandwidth::Bw125kHz), 10);
    CHECK_EQ(static_cast<int>(r.status), 0);
    CHECK_EQ(r.nanoseconds, std::int64_t{41'216'000});
}

void test_airtime_sf12_low_dr() {
    RadioConfig c = make(12, Bandwidth::Bw125kHz);
    CHECK_TRUE(low_data_rate_required(12, Bandwidth::Bw125kHz));
    c.low_data_rate_optimize = true;
    const AirtimeResult r = time_on_air(c, 10);
    CHECK_EQ(static_cast<int>(r.status), 0);
    // 401,408 ms préambule + 18 symboles * 32,768 ms = 991,232 ms.
    CHECK_EQ(r.nanoseconds, std::int64_t{991'232'000});
}

void test_airtime_monotonic() {
    const RadioConfig c = make(9, Bandwidth::Bw125kHz);
    std::int64_t prev = 0;
    for (std::uint32_t n = 0; n <= 255; ++n) {
        const AirtimeResult r = time_on_air(c, n);
        CHECK_EQ(static_cast<int>(r.status), 0);
        CHECK_TRUE(r.nanoseconds >= prev);
        prev = r.nanoseconds;
    }
    prev = 0;
    for (std::uint8_t sf = 7; sf <= 12; ++sf) {
        const AirtimeResult r = time_on_air(make(sf, Bandwidth::Bw125kHz), 20);
        CHECK_TRUE(r.nanoseconds > prev);
        prev = r.nanoseconds;
    }
}

void test_sensitivity_125khz_table() {
    double s = 0.0;
    CHECK_EQ(static_cast<int>(receiver_sensitivity_dbm(7, Bandwidth::Bw125kHz, s)), 0);
    CHECK_NEAR(s, -123.0, 1e-9);
    CHECK_EQ(static_cast<int>(receiver_sensitivity_dbm(12, Bandwidth::Bw125kHz, s)), 0);
    CHECK_NEAR(s, -136.0, 1e-9);
    // Sensibilité décroissante (plus négative) quand SF augmente.
    double prev = 0.0;
    receiver_sensitivity_dbm(7, Bandwidth::Bw125kHz, prev);
    for (std::uint8_t sf = 8; sf <= 12; ++sf) {
        double cur = 0.0;
        receiver_sensitivity_dbm(sf, Bandwidth::Bw125kHz, cur);
        CHECK_TRUE(cur < prev);
        prev = cur;
    }
}

void test_sensitivity_250_500_datasheet_values() {
    double s = 0.0;
    CHECK_EQ(static_cast<int>(receiver_sensitivity_dbm(7, Bandwidth::Bw250kHz, s)),
             static_cast<int>(Status::Ok));
    CHECK_EQ(static_cast<int>(s), -120);
    CHECK_EQ(static_cast<int>(receiver_sensitivity_dbm(12, Bandwidth::Bw250kHz, s)),
             static_cast<int>(Status::Ok));
    CHECK_EQ(static_cast<int>(s), -133);
    CHECK_EQ(static_cast<int>(receiver_sensitivity_dbm(7, Bandwidth::Bw500kHz, s)),
             static_cast<int>(Status::Ok));
    CHECK_EQ(static_cast<int>(s), -116);
    CHECK_EQ(static_cast<int>(receiver_sensitivity_dbm(12, Bandwidth::Bw500kHz, s)),
             static_cast<int>(Status::Ok));
    CHECK_EQ(static_cast<int>(s), -130);
    CHECK_EQ(static_cast<int>(receiver_sensitivity_dbm(13, Bandwidth::Bw125kHz, s)),
             static_cast<int>(Status::InvalidSpreadingFactor));
}

void test_sx1303_profile_sf5_and_default_unchanged() {
    // DR13 (SF5/125 kHz) : valeur indicative du SX1303 ; le profil SX1276 n'a pas de SF5.
    double s = 0.0;
    CHECK_EQ(static_cast<int>(receiver_sensitivity_dbm(5, Bandwidth::Bw125kHz,
                                                       ReceiverProfile::Sx1303Gateway, s)),
             static_cast<int>(Status::Ok));
    CHECK_NEAR(s, -121.0, 1e-9);
    CHECK_EQ(static_cast<int>(receiver_sensitivity_dbm(12, Bandwidth::Bw125kHz,
                                                       ReceiverProfile::Sx1303Gateway, s)),
             static_cast<int>(Status::Ok));
    CHECK_NEAR(s, -141.0, 1e-9);
    CHECK_EQ(static_cast<int>(receiver_sensitivity_dbm(5, Bandwidth::Bw125kHz,
                                                       ReceiverProfile::Sx1276Reference, s)),
             static_cast<int>(Status::InvalidSpreadingFactor));
    CHECK_EQ(static_cast<int>(receiver_sensitivity_dbm(7, Bandwidth::Bw250kHz,
                                                       ReceiverProfile::Sx1303Gateway, s)),
             static_cast<int>(Status::UncalibratedSensitivity));
    // Profil par défaut : SX1276 inchangé (SF7 = −123 dBm).
    CHECK_EQ(static_cast<int>(receiver_sensitivity_dbm(7, Bandwidth::Bw125kHz,
                                                       ReceiverProfile::Sx1276Reference, s)),
             static_cast<int>(Status::Ok));
    CHECK_NEAR(s, -123.0, 1e-9);
    // Sensibilité SX1303 décroissante avec SF (plus négative), comme la table SX1276.
    double prev = 0.0;
    receiver_sensitivity_dbm(5, Bandwidth::Bw125kHz, ReceiverProfile::Sx1303Gateway, prev);
    for (std::uint8_t sf = 6; sf <= 12; ++sf) {
        double cur = 0.0;
        receiver_sensitivity_dbm(sf, Bandwidth::Bw125kHz, ReceiverProfile::Sx1303Gateway, cur);
        CHECK_TRUE(cur < prev);
        prev = cur;
    }
    // Airtime SF5 : Tsym = 0,256 ms ; 12 octets, CR 4/5, CRC, en-tête explicite, préambule 8.
    // Symboles de charge utile : 8 + ceil((96 - 20 + 28 + 16) / 20) × 5 = 8 + 6 × 5 = 38.
    // Total : (8 + 4,25 + 38) × 0,256 ms = 12,864 ms.
    RadioConfig c5 = make(5, Bandwidth::Bw125kHz);
    const AirtimeResult r5 = time_on_air(c5, 12);
    CHECK_EQ(static_cast<int>(r5.status), static_cast<int>(Status::Ok));
    CHECK_EQ(r5.nanoseconds, std::int64_t{12'864'000});
    // SF6 reste refusé (en-tête implicite seulement) ; SF5 en en-tête implicite aussi refusé.
    RadioConfig c5i = make(5, Bandwidth::Bw125kHz);
    c5i.explicit_header = false;
    CHECK_EQ(static_cast<int>(time_on_air(c5i, 12).status),
             static_cast<int>(Status::InvalidSpreadingFactor));
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

// Point d'entrée unique : chaque suite est appelée depuis lsim_tests (main.cpp).
void run_lora_phy_tests() {
    test_symbol_duration_exact();
    test_known_airtime_sf7_10_bytes();
    test_airtime_sf12_low_dr();
    test_airtime_monotonic();
    test_sensitivity_125khz_table();
    test_sensitivity_250_500_datasheet_values();
    test_rejects_invalid_inputs();
    test_sx1303_profile_sf5_and_default_unchanged();
}
