// SPDX-License-Identifier: Apache-2.0
// Tests unitaires : bilan énergétique (SX1276 Table 6 et 10, STM32L072 fiche).
#include <cmath>
#include <cstdint>

#include "check.hpp"
#include "lsim/energy.hpp"

namespace {

using namespace lsim::energy;
using lsim::lora::Bandwidth;
using lsim::lora::Status;

constexpr std::uint64_t kSecond = 1'000'000'000ULL;

void test_tx_current_points() {
    double ma = 0.0;
    CHECK_EQ(static_cast<int>(tx_current_ma(20.0, ma)), static_cast<int>(Status::Ok));
    CHECK_NEAR(ma, 120.0, 1e-9);
    CHECK_EQ(static_cast<int>(tx_current_ma(13.0, ma)), static_cast<int>(Status::Ok));
    CHECK_NEAR(ma, 29.0, 1e-9);
    // 14 dBm : point supérieur (17 dBm, 87 mA), estimation conservatrice.
    CHECK_EQ(static_cast<int>(tx_current_ma(14.0, ma)), static_cast<int>(Status::Ok));
    CHECK_NEAR(ma, 87.0, 1e-9);
    CHECK_EQ(static_cast<int>(tx_current_ma(21.0, ma)), static_cast<int>(Status::InvalidParameter));
}

void test_device_energy_hand_computed() {
    // 1 s d'émission à 14 dBm (87 mA), 3599 s de veille (0,63 µA), alimentation 3,3 V.
    // Q = 0,087 + 0,63e-6 × 3599 = 0,0892674 C ; E = 3,3 × Q = 0,29458 J.
    const Profile p;
    Result r;
    CHECK_EQ(static_cast<int>(device_energy(p, 14.0, Bandwidth::Bw125kHz, kSecond, 0, 0,
                                            3600 * kSecond, r)),
             static_cast<int>(Status::Ok));
    CHECK_NEAR(r.charge_c, 0.0892674, 1e-7);
    CHECK_NEAR(r.energy_j, 0.29458242, 1e-6);
    CHECK_NEAR(r.average_current_ua, 0.0892674 / 3600.0 * 1e6, 1e-3);
}

void test_rx_bandwidth_and_mcu_contribution() {
    const Profile p;
    Result r;
    // 2 s de réception 500 kHz (12,6 mA) + 0,5 s de MCU actif (2,976 mA), reste en veille.
    CHECK_EQ(static_cast<int>(device_energy(p, 14.0, Bandwidth::Bw500kHz, 0, 2 * kSecond,
                                            kSecond / 2, 10 * kSecond, r)),
             static_cast<int>(Status::Ok));
    const double expected = 0.0126 * 2.0 + 0.002976 * 0.5 + 0.63e-6 * 7.5;
    CHECK_NEAR(r.charge_c, expected, 1e-9);
}

void test_rejects_inconsistent_inputs() {
    const Profile p;
    Result r;
    // Somme des états actifs supérieure à la durée totale.
    CHECK_EQ(static_cast<int>(device_energy(p, 14.0, Bandwidth::Bw125kHz, 2 * kSecond, 2 * kSecond,
                                            0, 3 * kSecond, r)),
             static_cast<int>(Status::InvalidParameter));
    // Durée totale nulle.
    CHECK_EQ(static_cast<int>(device_energy(p, 14.0, Bandwidth::Bw125kHz, 0, 0, 0, 0, r)),
             static_cast<int>(Status::InvalidParameter));
    // Puissance au-dessus de +20 dBm.
    CHECK_EQ(static_cast<int>(device_energy(p, 22.0, Bandwidth::Bw125kHz, 0, 0, 0, kSecond, r)),
             static_cast<int>(Status::InvalidParameter));
}

void test_zero_activity_is_sleep_only() {
    const Profile p;
    Result r;
    CHECK_EQ(static_cast<int>(device_energy(p, 14.0, Bandwidth::Bw125kHz, 0, 0, 0,
                                            1000 * kSecond, r)),
             static_cast<int>(Status::Ok));
    CHECK_NEAR(r.average_current_ua, 0.63, 1e-9);
}

}  // namespace

void run_energy_tests() {
    test_tx_current_points();
    test_device_energy_hand_computed();
    test_rx_bandwidth_and_mcu_contribution();
    test_rejects_inconsistent_inputs();
    test_zero_activity_is_sleep_only();
}
