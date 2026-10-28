// SPDX-License-Identifier: Apache-2.0
#include "lsim/lora_phy.hpp"

namespace lsim::lora {

Status receiver_sensitivity_dbm(std::uint8_t spreading_factor, Bandwidth bw, double& out_dbm) {
    // Table SX1276 (mode LoRa, 125 kHz, CR 4/5, PER 1 %), en dBm.
    static constexpr double kSensitivity125[] = {
        -123.0,  // SF7
        -126.0,  // SF8
        -129.0,  // SF9
        -132.0,  // SF10
        -134.5,  // SF11
        -137.0,  // SF12
    };
    if (spreading_factor < 7 || spreading_factor > 12) {
        return Status::InvalidSpreadingFactor;
    }
    if (bw != Bandwidth::Bw125kHz) {
        return Status::UncalibratedSensitivity;
    }
    out_dbm = kSensitivity125[spreading_factor - 7];
    return Status::Ok;
}

}  // namespace lsim::lora
