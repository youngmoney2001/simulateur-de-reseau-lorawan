// SPDX-License-Identifier: Apache-2.0
// Surface C de la décision ADR serveur (fonction pure, sans état).
#include "lsim/adr.hpp"
#include "lsim/c_api.h"
#include "lsim/lora_phy.hpp"

int32_t lsim_adr_decide(const lsim_adr_input* in, lsim_adr_output* out) {
    if (in == nullptr || out == nullptr) {
        return static_cast<int32_t>(lsim::lora::Status::NullOutput);
    }
    try {
        lsim::lorawan::adr::Input v;
        for (std::size_t i = 0; i < lsim::lorawan::adr::kMaxSamples; ++i) {
            v.snr_tenth_db[i] = in->snr_tenth_db[i];
        }
        v.n_samples = in->n_samples;
        v.dr = in->dr;
        for (std::size_t i = 0; i < lsim::lorawan::adr::kDrCount; ++i) {
            v.dr_sf[i] = in->dr_sf[i];
        }
        v.min_dr = in->min_dr;
        v.max_dr = in->max_dr;
        v.tx_power_index = in->tx_power_index;
        v.max_tx_power_index = in->max_tx_power_index;
        v.power_step_tenth_db = in->power_step_tenth_db;
        v.installation_margin_tenth_db = in->installation_margin_tenth_db;

        lsim::lorawan::adr::Output o;
        const auto st = lsim::lorawan::adr::decide(v, o);
        out->dr = o.dr;
        out->tx_power_index = o.tx_power_index;
        if (st != lsim::lorawan::adr::AdrStatus::Ok) {
            return LSIM_STATUS_ADR_BASE + 1;
        }
        return 0;
    } catch (...) {
        return LSIM_STATUS_INTERNAL;
    }
}
