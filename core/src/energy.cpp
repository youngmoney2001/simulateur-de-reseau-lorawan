// SPDX-License-Identifier: Apache-2.0
#include "lsim/energy.hpp"

#include <cmath>
#include <limits>

namespace lsim::energy {

namespace {

constexpr Profile kRak4631 = {
    "RAK4631 (nRF52840 + SX1262, module)",
    3.3,      // tension nominale
    17.0, 17.0, 17.0,  // Rx LoRa (valeur unique de la fiche)
    2.0,      // veille LoRa et BLE
    0.0,      // MCU inclus dans les courants module
    {{{17.0, 92.0}, {20.0, 125.0}, {0.0, 0.0}, {0.0, 0.0}}},
    2};

constexpr Profile kSx1262Stm32l072 = {
    "SX1262 (datasheet) + STM32L072 (MCU)",
    3.3,
    4.6, 4.6, 4.6,           // Rx LoRa 125 kHz ; 250/500 kHz : estimation
    0.16 + 0.43,             // SX1262 OFF cold start + STM32L072 Stop (typ.)
    93e-3 * 32.0,            // 93 µA/MHz × 32 MHz (valeur « jusqu'à » de la fiche ST)
    {{{14.0, 90.0}, {17.0, 95.0}, {20.0, 102.0}, {22.0, 118.0}}},
    4};

bool is_valid_bw(lora::Bandwidth bw) {
    return bw == lora::Bandwidth::Bw125kHz || bw == lora::Bandwidth::Bw250kHz ||
           bw == lora::Bandwidth::Bw500kHz;
}

// a × b sans débordement ; false si débordement.
bool mul_u64(std::uint64_t a, std::uint64_t b, std::uint64_t& out) {
    if (b != 0 && a > std::numeric_limits<std::uint64_t>::max() / b) {
        return false;
    }
    out = a * b;
    return true;
}

bool add_u64(std::uint64_t a, std::uint64_t b, std::uint64_t& out) {
    if (a > std::numeric_limits<std::uint64_t>::max() - b) {
        return false;
    }
    out = a + b;
    return true;
}

}  // namespace

lora::Status profile_from_id(std::uint32_t profile_id, const Profile*& out) {
    switch (profile_id) {
        case kProfileRak4631:
            out = &kRak4631;
            return lora::Status::Ok;
        case kProfileSx1262Stm32l072:
            out = &kSx1262Stm32l072;
            return lora::Status::Ok;
        default:
            out = nullptr;
            return lora::Status::InvalidParameter;
    }
}

lora::Status tx_current_ma(const Profile& p, double tx_power_dbm, double& out_ma) {
    out_ma = 0.0;
    if (!std::isfinite(tx_power_dbm)) {
        return lora::Status::InvalidParameter;
    }
    for (std::size_t i = 0; i < p.tx_point_count; ++i) {
        if (p.tx_points[i].dbm >= tx_power_dbm) {
            out_ma = p.tx_points[i].ma;
            return lora::Status::Ok;
        }
    }
    return lora::Status::InvalidParameter;  // au-delà du dernier point publié
}

lora::Status rx_current_ma(lora::Bandwidth bw, const Profile& p, double& out_ma) {
    out_ma = 0.0;
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
    if (tx_ns > total_ns || rx_ns > total_ns || mcu_active_ns > total_ns) {
        return lora::Status::InvalidParameter;
    }
    std::uint64_t active = 0;
    std::uint64_t active_rx = 0;
    if (!add_u64(tx_ns, rx_ns, active_rx) || !add_u64(active_rx, mcu_active_ns, active) ||
        active > total_ns) {
        return lora::Status::InvalidParameter;
    }
    const std::uint64_t sleep_ns = total_ns - active;

    double tx_ma = 0.0;
    double rx_ma = 0.0;
    const lora::Status st_tx = tx_current_ma(p, tx_power_dbm, tx_ma);
    if (st_tx != lora::Status::Ok) {
        return st_tx;
    }
    const lora::Status st_rx = rx_current_ma(bw, p, rx_ma);
    if (st_rx != lora::Status::Ok) {
        return st_rx;
    }

    const double tx_s = static_cast<double>(tx_ns) * 1e-9;
    const double rx_s = static_cast<double>(rx_ns) * 1e-9;
    const double mcu_s = static_cast<double>(mcu_active_ns) * 1e-9;
    const double sleep_s = static_cast<double>(sleep_ns) * 1e-9;
    const double total_s = static_cast<double>(total_ns) * 1e-9;

    out.charge_c = tx_ma * 1e-3 * tx_s + rx_ma * 1e-3 * rx_s +
                   p.mcu_run_current_ma * 1e-3 * mcu_s + p.sleep_current_ua * 1e-6 * sleep_s;
    out.energy_j = p.supply_v * out.charge_c;
    out.average_current_ua = out.charge_c / total_s * 1e6;
    return lora::Status::Ok;
}

lora::Status preamble_listen_ns(std::uint8_t spreading_factor, lora::Bandwidth bw,
                                std::uint16_t preamble_symbols, std::uint64_t& out_ns) {
    out_ns = 0;
    if (spreading_factor < 7 || spreading_factor > 12) {
        return lora::Status::InvalidSpreadingFactor;
    }
    if (!is_valid_bw(bw)) {
        return lora::Status::InvalidBandwidth;
    }
    // (n + 4,25) × Tsym = Tsym × (4n + 17) / 4 : Tsym est un multiple de 2000 ns, division exacte.
    const auto tsym = static_cast<std::uint64_t>(lora::symbol_duration_ns(spreading_factor, bw));
    out_ns = tsym * (4ULL * preamble_symbols + 17ULL) / 4ULL;
    return lora::Status::Ok;
}

lora::Status device_energy_class_a(const Profile& p, double tx_power_dbm, lora::Bandwidth bw,
                                   std::uint8_t spreading_factor, std::uint16_t preamble_symbols,
                                   std::uint64_t uplinks, std::uint64_t airtime_ns,
                                   std::uint64_t rx_window_ns, std::uint64_t downlink_ns_total,
                                   std::uint64_t mcu_ns_per_uplink, std::uint64_t total_ns,
                                   Result& out) {
    out = Result{};
    std::uint64_t window = rx_window_ns;
    if (window == 0) {
        const lora::Status st = preamble_listen_ns(spreading_factor, bw, preamble_symbols, window);
        if (st != lora::Status::Ok) {
            return st;
        }
    }
    std::uint64_t tx_total = 0;
    std::uint64_t rx_per_uplink = 0;
    std::uint64_t rx_total = 0;
    std::uint64_t mcu_total = 0;
    // Deux fenêtres (RX1, RX2) par uplink, plus l'airtime des downlinks reçus.
    if (!mul_u64(uplinks, airtime_ns, tx_total) || !mul_u64(2, window, rx_per_uplink) ||
        !mul_u64(uplinks, rx_per_uplink, rx_total) ||
        !add_u64(rx_total, downlink_ns_total, rx_total) ||
        !mul_u64(uplinks, mcu_ns_per_uplink, mcu_total)) {
        return lora::Status::InvalidParameter;
    }
    return device_energy(p, tx_power_dbm, bw, tx_total, rx_total, mcu_total, total_ns, out);
}

}  // namespace lsim::energy
