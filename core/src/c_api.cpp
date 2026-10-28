// SPDX-License-Identifier: Apache-2.0
#include "lsim/c_api.h"

#include "lsim/lora_phy.hpp"

namespace {

// Conversion sûre : seule la valeur 125/250/500 kHz est acceptée.
// Toute autre valeur est rejetée par validate() via un Bandwidth invalide.
lsim::lora::Bandwidth to_bandwidth(std::uint32_t hz) {
    return static_cast<lsim::lora::Bandwidth>(hz);
}

}  // namespace

extern "C" {

uint32_t lsim_version(void) {
    return 0x000100u;  // 0.1.0
}

int32_t lsim_time_on_air_ns(const lsim_radio_config* cfg,
                            uint32_t payload_bytes,
                            int64_t* out_ns) {
    if (cfg == nullptr || out_ns == nullptr) {
        return static_cast<int32_t>(lsim::lora::Status::NullOutput);
    }

    lsim::lora::RadioConfig rc;
    rc.spreading_factor = cfg->spreading_factor;
    rc.bandwidth = to_bandwidth(cfg->bandwidth_hz);
    rc.coding_rate = cfg->coding_rate;
    rc.preamble_symbols = cfg->preamble_symbols;
    rc.crc_on = cfg->crc_on != 0;
    rc.explicit_header = cfg->explicit_header != 0;
    rc.low_data_rate_optimize = cfg->low_data_rate_optimize != 0;

    const lsim::lora::AirtimeResult res = lsim::lora::time_on_air(rc, payload_bytes);
    if (res.status == lsim::lora::Status::Ok) {
        *out_ns = res.nanoseconds;
    } else {
        *out_ns = 0;
    }
    return static_cast<int32_t>(res.status);
}

}  // extern "C"
