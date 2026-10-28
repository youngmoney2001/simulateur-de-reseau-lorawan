// SPDX-License-Identifier: Apache-2.0
#include "lsim/lora_phy.hpp"

namespace lsim::lora {

namespace {

// Source : Semtech SX1276/77/78/79 datasheet, Rev. 4 (mars 2015), Table 10
// (LoRa Receiver Specification), blocs RFS_L125_HF, RFS_L250_HF, RFS_L500_HF.
// Conditions communes : « highest LNA gain, LnaBoost for Band 1, using split
// Rx/Tx path », valeurs typiques, SF6..SF12 dans l'ordre du tableau (SF6 non
// exposé ici). Bloc RFS_L125_HF : SF11 = −133, SF12 = −136 dBm.
constexpr double kSensitivity125[] = {
    -123.0,  // SF7
    -126.0,  // SF8
    -129.0,  // SF9
    -132.0,  // SF10
    -133.0,  // SF11
    -136.0,  // SF12
};
constexpr double kSensitivity250[] = {
    -120.0,  // SF7
    -123.0,  // SF8
    -125.0,  // SF9
    -128.0,  // SF10
    -130.0,  // SF11
    -133.0,  // SF12
};
constexpr double kSensitivity500[] = {
    -116.0,  // SF7
    -119.0,  // SF8
    -122.0,  // SF9
    -125.0,  // SF10
    -128.0,  // SF11
    -130.0,  // SF12
};

}  // namespace

Status receiver_sensitivity_dbm(std::uint8_t spreading_factor, Bandwidth bw, double& out_dbm) {
    if (spreading_factor < 7 || spreading_factor > 12) {
        return Status::InvalidSpreadingFactor;
    }
    const std::size_t idx = static_cast<std::size_t>(spreading_factor - 7);
    switch (bw) {
        case Bandwidth::Bw125kHz:
            out_dbm = kSensitivity125[idx];
            return Status::Ok;
        case Bandwidth::Bw250kHz:
            out_dbm = kSensitivity250[idx];
            return Status::Ok;
        case Bandwidth::Bw500kHz:
            out_dbm = kSensitivity500[idx];
            return Status::Ok;
    }
    return Status::UncalibratedSensitivity;
}

}  // namespace lsim::lora
