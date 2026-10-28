// SPDX-License-Identifier: Apache-2.0
#include "lsim/c_api.h"
#include "lsim/energy.hpp"
#include "lsim/materials.hpp"

#include "lsim/link_budget.hpp"
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

int32_t lsim_receiver_sensitivity_dbm(uint8_t spreading_factor,
                                      uint32_t bandwidth_hz,
                                      double* out_dbm) {
    if (out_dbm == nullptr) {
        return static_cast<int32_t>(lsim::lora::Status::NullOutput);
    }
    if (bandwidth_hz != 125000u && bandwidth_hz != 250000u && bandwidth_hz != 500000u) {
        *out_dbm = 0.0;
        return static_cast<int32_t>(lsim::lora::Status::InvalidBandwidth);
    }
    const lsim::lora::Status st = lsim::lora::receiver_sensitivity_dbm(
        spreading_factor, to_bandwidth(bandwidth_hz), *out_dbm);
    return static_cast<int32_t>(st);
}

uint32_t lsim_material_count(void) {
    return lsim::materials::kMaterialCount;
}

int32_t lsim_material_traversal_loss_db(uint32_t material_id, double frequency_hz,
                                        double thickness_m, double* out_db,
                                        int32_t* out_extrapolated) {
    if (out_db == nullptr || out_extrapolated == nullptr) {
        return static_cast<int32_t>(lsim::lora::Status::NullOutput);
    }
    *out_db = 0.0;
    *out_extrapolated = 0;
    if (material_id >= lsim::materials::kMaterialCount) {
        return static_cast<int32_t>(lsim::lora::Status::InvalidParameter);
    }
    const auto material = static_cast<lsim::materials::Material>(material_id);
    lsim::materials::AttenuationResult r;
    const lsim::lora::Status st = lsim::materials::attenuation_db_per_m(material, frequency_hz, r);
    if (st != lsim::lora::Status::Ok) {
        return static_cast<int32_t>(st);
    }
    double loss = 0.0;
    const lsim::lora::Status st2 = lsim::materials::traversal_loss_db(material, frequency_hz, thickness_m, loss);
    if (st2 != lsim::lora::Status::Ok) {
        return static_cast<int32_t>(st2);
    }
    *out_db = loss;
    *out_extrapolated = r.extrapolated ? 1 : 0;
    return static_cast<int32_t>(lsim::lora::Status::Ok);
}

int32_t lsim_energy_device(double tx_power_dbm, uint32_t bandwidth_hz, uint64_t tx_ns,
                           uint64_t rx_ns, uint64_t mcu_active_ns, uint64_t total_ns,
                           double* out_energy_j, double* out_avg_current_ua) {
    if (out_energy_j == nullptr || out_avg_current_ua == nullptr) {
        return static_cast<int32_t>(lsim::lora::Status::NullOutput);
    }
    *out_energy_j = 0.0;
    *out_avg_current_ua = 0.0;
    if (bandwidth_hz != 125000u && bandwidth_hz != 250000u && bandwidth_hz != 500000u) {
        return static_cast<int32_t>(lsim::lora::Status::InvalidBandwidth);
    }
    const lsim::energy::Profile profile;
    lsim::energy::Result r;
    const lsim::lora::Status st = lsim::energy::device_energy(
        profile, tx_power_dbm, to_bandwidth(bandwidth_hz), tx_ns, rx_ns, mcu_active_ns, total_ns, r);
    if (st != lsim::lora::Status::Ok) {
        return static_cast<int32_t>(st);
    }
    *out_energy_j = r.energy_j;
    *out_avg_current_ua = r.average_current_ua;
    return static_cast<int32_t>(lsim::lora::Status::Ok);
}

int32_t lsim_energy_profile(double* supply_v, double* rx_ma_125khz, double* rx_ma_250khz,
                            double* rx_ma_500khz, double* sleep_ua, double* mcu_run_ma) {
    if (supply_v == nullptr || rx_ma_125khz == nullptr || rx_ma_250khz == nullptr ||
        rx_ma_500khz == nullptr || sleep_ua == nullptr || mcu_run_ma == nullptr) {
        return static_cast<int32_t>(lsim::lora::Status::NullOutput);
    }
    const lsim::energy::Profile p;
    *supply_v = p.supply_v;
    *rx_ma_125khz = p.rx_current_ma_125khz;
    *rx_ma_250khz = p.rx_current_ma_250khz;
    *rx_ma_500khz = p.rx_current_ma_500khz;
    *sleep_ua = p.sleep_current_ua;
    *mcu_run_ma = p.mcu_run_current_ma;
    return static_cast<int32_t>(lsim::lora::Status::Ok);
}

int32_t lsim_free_space_path_loss_db(double distance_m, double frequency_hz, double* out_db) {
    if (out_db == nullptr) {
        return static_cast<int32_t>(lsim::lora::Status::NullOutput);
    }
    const lsim::radio::BudgetResult r = lsim::radio::free_space_path_loss_db(distance_m, frequency_hz);
    *out_db = r.value;
    return static_cast<int32_t>(r.status);
}

int32_t lsim_log_distance_path_loss_db(double distance_m, double frequency_hz,
                                       double reference_distance_m, double exponent,
                                       double* out_db) {
    if (out_db == nullptr) {
        return static_cast<int32_t>(lsim::lora::Status::NullOutput);
    }
    lsim::radio::LogDistanceModel m;
    m.frequency_hz = frequency_hz;
    m.reference_distance_m = reference_distance_m;
    m.exponent = exponent;
    const lsim::radio::BudgetResult r = lsim::radio::log_distance_path_loss_db(m, distance_m);
    *out_db = r.value;
    return static_cast<int32_t>(r.status);
}

int32_t lsim_max_allowable_path_loss_db(double tx_power_dbm, double tx_antenna_gain_dbi,
                                        double rx_antenna_gain_dbi, double cable_losses_db,
                                        double fade_margin_db, double rx_sensitivity_dbm,
                                        double* out_db) {
    if (out_db == nullptr) {
        return static_cast<int32_t>(lsim::lora::Status::NullOutput);
    }
    lsim::radio::LinkBudget b;
    b.tx_power_dbm = tx_power_dbm;
    b.tx_antenna_gain_dbi = tx_antenna_gain_dbi;
    b.rx_antenna_gain_dbi = rx_antenna_gain_dbi;
    b.cable_losses_db = cable_losses_db;
    b.fade_margin_db = fade_margin_db;
    const lsim::radio::BudgetResult r =
        lsim::radio::maximum_allowable_path_loss_db(b, rx_sensitivity_dbm);
    *out_db = r.value;
    return static_cast<int32_t>(r.status);
}

int32_t lsim_max_range_m(double max_path_loss_db, double frequency_hz,
                         double reference_distance_m, double exponent, double* out_m) {
    if (out_m == nullptr) {
        return static_cast<int32_t>(lsim::lora::Status::NullOutput);
    }
    lsim::radio::LogDistanceModel m;
    m.frequency_hz = frequency_hz;
    m.reference_distance_m = reference_distance_m;
    m.exponent = exponent;
    const lsim::radio::BudgetResult r = lsim::radio::max_range_m(m, max_path_loss_db);
    *out_m = r.value;
    return static_cast<int32_t>(r.status);
}

}  // extern "C"
