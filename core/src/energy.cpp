// SPDX-License-Identifier: Apache-2.0
#include "lsim/energy.hpp"

#include <cmath>

namespace lsim::energy {

namespace {

struct TxPoint {
    double rfo_dbm;
    double current_ma;
};

// SX1276 Table 6, IDDT typ. (PA_BOOST pour +20 et +17 dBm ; RFO pour +13 et +7 dBm).
constexpr TxPoint kTxPoints[] = {
    {7.0, 20.0},
    {13.0, 29.0},
    {17.0, 87.0},
    {20.0, 120.0},
};

}  // namespace

lora::Status tx_current_ma(double tx_power_dbm, double& out_ma) {
    if (!std::isfinite(tx_power_dbm) || tx_power_dbm > 20.0) {
        return lora::Status::InvalidParameter;
    }
    // Point du datasheet dont la puissance est >= la puissance demandée (conservateur).
    for (const TxPoint& p : kTxPoints) {
        if (p.rfo_dbm >= tx_power_dbm) {
            out_ma = p.current_ma;
            return lora::Status::Ok;
        }
    }
    return lora::Status::InvalidParameter;  // inatteignable pour tx_power_dbm <= 20
}

lora::Status rx_current_ma(lora::Bandwidth bw, const Profile& p, double& out_ma) {
    switch (bw) {
        case lora::Bandwidth::Bw125kHz:
            out_ma = p.rx_current_ma_125khz;
            return lora::Status::Ok;
        case lora::Bandwidth::Bw250kHz:
            out_ma = p.rx_current_ma_250khz;
            return lora::Status::Ok;
        case lora::Bandwidth::Bw500kHz:
            out_ma = p.rx_current_ma_500khz;
            return lora::Status::Ok;
    }
    return lora::Status::InvalidBandwidth;
}

lora::Status device_energy(const Profile& p, double tx_power_dbm, lora::Bandwidth bw,
                           std::uint64_t tx_ns, std::uint64_t rx_ns,
                           std::uint64_t mcu_active_ns, std::uint64_t total_ns, Result& out) {
    out = Result{};
    if (!std::isfinite(p.supply_v) || p.supply_v <= 0.0) {
        return lora::Status::InvalidParameter;
    }
    if (total_ns == 0) {
        return lora::Status::InvalidParameter;
    }
    // Somme des états actifs : débordement et dépassement de la durée totale refusés.
    if (tx_ns > total_ns || rx_ns > total_ns || mcu_active_ns > total_ns) {
        return lora::Status::InvalidParameter;
    }
    const std::uint64_t active = tx_ns + rx_ns + mcu_active_ns;
    if (active < tx_ns || active < rx_ns || active > total_ns) {
        return lora::Status::InvalidParameter;
    }
    const std::uint64_t sleep_ns = total_ns - active;

    double tx_ma = 0.0;
    double rx_ma = 0.0;
    const lora::Status st_tx = tx_current_ma(tx_power_dbm, tx_ma);
    if (st_tx != lora::Status::Ok) {
        return st_tx;
    }
    const lora::Status st_rx = rx_current_ma(bw, p, rx_ma);
    if (st_rx != lora::Status::Ok) {
        return st_rx;
    }

    // Charge (C) = Σ courant (A) × durée (s). Durées en ns entiers, converties une seule fois.
    constexpr double kNsToS = 1e-9;
    const double charge_c =
        (tx_ma * 1e-3) * (static_cast<double>(tx_ns) * kNsToS) +
        (rx_ma * 1e-3) * (static_cast<double>(rx_ns) * kNsToS) +
        (p.mcu_run_current_ma * 1e-3) * (static_cast<double>(mcu_active_ns) * kNsToS) +
        (p.sleep_current_ua * 1e-6) * (static_cast<double>(sleep_ns) * kNsToS);

    out.charge_c = charge_c;
    out.energy_j = p.supply_v * charge_c;
    out.average_current_ua = charge_c / (static_cast<double>(total_ns) * kNsToS) * 1e6;
    return lora::Status::Ok;
}

}  // namespace lsim::energy
