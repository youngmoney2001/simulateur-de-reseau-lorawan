// SPDX-License-Identifier: Apache-2.0
#include "lsim/link_budget.hpp"

#include <cmath>

namespace lsim::radio {
namespace {

constexpr double kFsplConstantDb = 147.55;  // 20 log10(4 pi / c)

bool finite_positive(double x) {
    return std::isfinite(x) && x > 0.0;
}

BudgetResult fail(lora::Status s) {
    return {s, 0.0};
}

}  // namespace

BudgetResult free_space_path_loss_db(double distance_m, double frequency_hz) {
    if (!finite_positive(distance_m) || !finite_positive(frequency_hz)) {
        return fail(lora::Status::InvalidParameter);
    }
    const double db = 20.0 * std::log10(distance_m) + 20.0 * std::log10(frequency_hz) - kFsplConstantDb;
    return {lora::Status::Ok, db};
}

BudgetResult log_distance_path_loss_db(const LogDistanceModel& model, double distance_m) {
    if (!finite_positive(model.frequency_hz) || !finite_positive(model.reference_distance_m) ||
        !finite_positive(distance_m) || !std::isfinite(model.exponent) || model.exponent < 1.0 ||
        model.exponent > 6.0) {
        return fail(lora::Status::InvalidParameter);
    }
    const BudgetResult pl0 = free_space_path_loss_db(model.reference_distance_m, model.frequency_hz);
    if (pl0.status != lora::Status::Ok) {
        return pl0;
    }
    const double db = pl0.value + 10.0 * model.exponent * std::log10(distance_m / model.reference_distance_m);
    return {lora::Status::Ok, db};
}

BudgetResult maximum_allowable_path_loss_db(const LinkBudget& b, double rx_sensitivity_dbm) {
    if (!std::isfinite(rx_sensitivity_dbm) || !std::isfinite(b.tx_power_dbm) ||
        !std::isfinite(b.tx_antenna_gain_dbi) || !std::isfinite(b.rx_antenna_gain_dbi) ||
        !std::isfinite(b.fade_margin_db) || !std::isfinite(b.cable_losses_db)) {
        return fail(lora::Status::InvalidParameter);
    }
    const double mapl = b.tx_power_dbm + b.tx_antenna_gain_dbi + b.rx_antenna_gain_dbi -
                        b.cable_losses_db - b.fade_margin_db - rx_sensitivity_dbm;
    return {lora::Status::Ok, mapl};
}

BudgetResult max_range_m(const LogDistanceModel& model, double max_path_loss_db) {
    if (!std::isfinite(max_path_loss_db)) {
        return fail(lora::Status::InvalidParameter);
    }
    const BudgetResult pl0 = free_space_path_loss_db(model.reference_distance_m, model.frequency_hz);
    if (pl0.status != lora::Status::Ok || !std::isfinite(model.exponent) || model.exponent < 1.0 ||
        model.exponent > 6.0) {
        return fail(lora::Status::InvalidParameter);
    }
    if (max_path_loss_db < pl0.value) {
        // Perte inférieure à PL(d0) : portée inférieure à d0, hors modèle.
        return fail(lora::Status::InvalidParameter);
    }
    const double d = model.reference_distance_m *
                     std::pow(10.0, (max_path_loss_db - pl0.value) / (10.0 * model.exponent));
    return {lora::Status::Ok, d};
}

}  // namespace lsim::radio
