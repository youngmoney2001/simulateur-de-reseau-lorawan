// SPDX-License-Identifier: Apache-2.0
// Tests unitaires : bilan énergétique (profils RAK4631 et SX1262 + STM32L072, classe A).
#include <cstdint>
#include <limits>

#include "check.hpp"
#include "lsim/energy.hpp"

namespace {

using namespace lsim::energy;
using lsim::lora::Bandwidth;
using lsim::lora::Status;

constexpr std::uint64_t kSecond = 1'000'000'000ULL;

const Profile& rak() {
    const Profile* p = nullptr;
    profile_from_id(kProfileRak4631, p);
    return *p;
}

const Profile& sx() {
    const Profile* p = nullptr;
    profile_from_id(kProfileSx1262Stm32l072, p);
    return *p;
}

void test_profile_ids() {
    const Profile* p = nullptr;
    CHECK_EQ(static_cast<int>(profile_from_id(kProfileRak4631, p)), static_cast<int>(Status::Ok));
    CHECK_TRUE(p != nullptr);
    CHECK_EQ(static_cast<int>(profile_from_id(kProfileSx1262Stm32l072, p)),
             static_cast<int>(Status::Ok));
    CHECK_EQ(static_cast<int>(profile_from_id(kProfileCount, p)),
             static_cast<int>(Status::InvalidParameter));
    CHECK_TRUE(p == nullptr);
}

void test_rak_tx_points() {
    double ma = 0.0;
    CHECK_EQ(static_cast<int>(tx_current_ma(rak(), 20.0, ma)), static_cast<int>(Status::Ok));
    CHECK_NEAR(ma, 125.0, 1e-9);
    // 14 dBm : point module supérieur (17 dBm, 92 mA).
    CHECK_EQ(static_cast<int>(tx_current_ma(rak(), 14.0, ma)), static_cast<int>(Status::Ok));
    CHECK_NEAR(ma, 92.0, 1e-9);
    CHECK_EQ(static_cast<int>(tx_current_ma(rak(), 21.0, ma)),
             static_cast<int>(Status::InvalidParameter));
}

void test_sx_tx_points() {
    double ma = 0.0;
    // 14 dBm : point 14 dBm (90 mA) ; 15 dBm : point supérieur 17 dBm (95 mA).
    CHECK_EQ(static_cast<int>(tx_current_ma(sx(), 14.0, ma)), static_cast<int>(Status::Ok));
    CHECK_NEAR(ma, 90.0, 1e-9);
    CHECK_EQ(static_cast<int>(tx_current_ma(sx(), 15.0, ma)), static_cast<int>(Status::Ok));
    CHECK_NEAR(ma, 95.0, 1e-9);
    CHECK_EQ(static_cast<int>(tx_current_ma(sx(), 22.0, ma)), static_cast<int>(Status::Ok));
    CHECK_NEAR(ma, 118.0, 1e-9);
    CHECK_EQ(static_cast<int>(tx_current_ma(sx(), 22.5, ma)),
             static_cast<int>(Status::InvalidParameter));
    CHECK_EQ(static_cast<int>(tx_current_ma(sx(), std::numeric_limits<double>::quiet_NaN(), ma)),
             static_cast<int>(Status::InvalidParameter));
}

void test_rak_hand_computed() {
    // 1 s à 14 dBm (92 mA), 3599 s de veille (2,0 µA), 3,3 V.
    // Q = 0,092 + 2,0e-6 × 3599 = 0,099198 C ; E = 3,3 × Q = 0,3273534 J.
    Result r;
    CHECK_EQ(static_cast<int>(device_energy(rak(), 14.0, Bandwidth::Bw125kHz, kSecond, 0, 0,
                                            3600 * kSecond, r)),
             static_cast<int>(Status::Ok));
    CHECK_NEAR(r.charge_c, 0.099198, 1e-9);
    CHECK_NEAR(r.energy_j, 0.3273534, 1e-7);
    CHECK_NEAR(r.average_current_ua, 0.099198 / 3600.0 * 1e6, 1e-6);
}

void test_sx_hand_computed() {
    // 1 s à 14 dBm (90 mA), 3599 s de veille (0,59 µA), 3,3 V.
    // Q = 0,090 + 0,59e-6 × 3599 = 0,09212341 C ; E = 0,304007253 J.
    Result r;
    CHECK_EQ(static_cast<int>(device_energy(sx(), 14.0, Bandwidth::Bw125kHz, kSecond, 0, 0,
                                            3600 * kSecond, r)),
             static_cast<int>(Status::Ok));
    CHECK_NEAR(r.charge_c, 0.09212341, 1e-9);
    CHECK_NEAR(r.energy_j, 0.304007253, 1e-7);
}

void test_mcu_active_term_sx() {
    // 2 s de MCU actif (2,976 mA), reste en veille (0,59 µA), sur 10 s, sans radio.
    // Q = 2,976e-3 × 2 + 0,59e-6 × 8 = 0,005952 + 0,00000472 = 0,00595672 C.
    Result r;
    CHECK_EQ(static_cast<int>(device_energy(sx(), 14.0, Bandwidth::Bw125kHz, 0, 0, 2 * kSecond,
                                            10 * kSecond, r)),
             static_cast<int>(Status::Ok));
    CHECK_NEAR(r.charge_c, 0.00595672, 1e-9);
}

void test_device_energy_rejects_overflow_and_bad_input() {
    Result r;
    // Somme des états actifs > total.
    CHECK_EQ(static_cast<int>(device_energy(rak(), 14.0, Bandwidth::Bw125kHz, 2 * kSecond, 0, 0,
                                            kSecond, r)),
             static_cast<int>(Status::InvalidParameter));
    // Débordement d'addition tx + rx.
    const std::uint64_t big = std::numeric_limits<std::uint64_t>::max() - 1;
    CHECK_EQ(static_cast<int>(device_energy(rak(), 14.0, Bandwidth::Bw125kHz, big, 5, 0, big, r)),
             static_cast<int>(Status::InvalidParameter));
    CHECK_EQ(static_cast<int>(device_energy(rak(), 14.0, Bandwidth::Bw125kHz, 0, 0, 0, 0, r)),
             static_cast<int>(Status::InvalidParameter));
}

void test_preamble_duration() {
    std::uint64_t ns = 0;
    // SF7, 125 kHz, 8 symboles : Tsym = 1,024 ms ; (8 + 4,25) × 1,024 ms = 12,544 ms.
    CHECK_EQ(static_cast<int>(preamble_listen_ns(7, Bandwidth::Bw125kHz, 8, ns)),
             static_cast<int>(Status::Ok));
    CHECK_EQ(static_cast<std::uint64_t>(ns), 12'544'000ULL);
    // SF12, 250 kHz, 8 symboles : Tsym = 16,384 ms ; × 12,25 = 200,704 ms.
    CHECK_EQ(static_cast<int>(preamble_listen_ns(12, Bandwidth::Bw250kHz, 8, ns)),
             static_cast<int>(Status::Ok));
    CHECK_EQ(static_cast<std::uint64_t>(ns), 200'704'000ULL);
    CHECK_EQ(static_cast<int>(preamble_listen_ns(6, Bandwidth::Bw125kHz, 8, ns)),
             static_cast<int>(Status::InvalidSpreadingFactor));
}

void test_class_a_preamble_window() {
    // 10 uplinks de 100 ms à SF7/125 kHz, RX1 et RX2 au préambule (12,544 ms), 3600 s.
    // tx = 1 s ; rx = 10 × 2 × 12,544 ms = 0,25088 s ; veille = 3598,74912 s.
    // Q = 0,092 + 0,017 × 0,25088 + 2,0e-6 × 3598,74912 = 0,10346245824 C.
    Result r;
    CHECK_EQ(static_cast<int>(device_energy_class_a(rak(), 14.0, Bandwidth::Bw125kHz, 7, 8, 10,
                                                    100'000'000ULL, 0, 0, 0, 3600 * kSecond, r)),
             static_cast<int>(Status::Ok));
    CHECK_NEAR(r.charge_c, 0.10346245824, 1e-9);
}

void test_class_a_explicit_window_and_downlink() {
    // 1 uplink, fenêtres de 1 s chacune, plus 0,5 s de downlink reçu, sur 10 s, profil SX.
    // rx = 2 + 0,5 = 2,5 s à 4,6 mA ; veille = 7,5 s à 0,59 µA.
    // Q = 0,0046 × 2,5 + 0,59e-6 × 7,5 = 0,0115 + 0,00000443 = 0,01150443 C.
    Result r;
    CHECK_EQ(static_cast<int>(device_energy_class_a(sx(), 14.0, Bandwidth::Bw125kHz, 7, 8, 1, 0,
                                                    kSecond, kSecond / 2, 0, 10 * kSecond, r)),
             static_cast<int>(Status::Ok));
    CHECK_NEAR(r.charge_c, 0.011504425, 1e-9);
}

void test_class_a_overflow_rejected() {
    Result r;
    CHECK_EQ(static_cast<int>(device_energy_class_a(rak(), 14.0, Bandwidth::Bw125kHz, 7, 8,
                                                    std::numeric_limits<std::uint64_t>::max(), 2,
                                                    0, 0, 0, 10 * kSecond, r)),
             static_cast<int>(Status::InvalidParameter));
}

}  // namespace

void run_energy_tests() {
    test_profile_ids();
    test_rak_tx_points();
    test_sx_tx_points();
    test_rak_hand_computed();
    test_sx_hand_computed();
    test_mcu_active_term_sx();
    test_device_energy_rejects_overflow_and_bad_input();
    test_preamble_duration();
    test_class_a_preamble_window();
    test_class_a_explicit_window_and_downlink();
    test_class_a_overflow_rejected();
}
