// SPDX-License-Identifier: Apache-2.0
// Point d'entrée public lsim_simulate_closed_loop_v3 (étape 6.3).
//
// Chaîne d'appel : validation (closed_loop_v3_validate) ; adaptation des entrées C vers le moteur ;
// moteur canal (simulate_closed_loop_channels) ; sorties atomiques (emit_closed_loop_v3).
// Aucune écriture utilisateur n'a lieu avant `emit_closed_loop_v3`, donc aucune sur erreur de
// validation, d'environnement ou de moteur.
//
// Les adaptateurs C vers C++ (sensibilité absolue, environnement, entrées du moteur) sont des copies
// de ceux de c_api_ext.cpp, placées ici dans un espace anonyme. v1, v2 et gw2 ne sont pas modifiées.
#include <cstddef>
#include <cstdint>
#include <vector>

#include "lsim/c_api.h"
#include "lsim/closed_loop_v3_config.hpp"
#include "lsim/closed_loop_v3_output.hpp"
#include "lsim/closed_loop_v3_validate.hpp"
#include "lsim/engine.hpp"
#include "lsim/environment.hpp"
#include "lsim/loop_adr.hpp"

namespace {

// Borne de sortie par run : identique à c_api_ext.cpp (kMaxTraceRecords).
constexpr std::uint64_t kMaxTraceRecords = 200'000;

// Sensibilité absolue : copie de c_api_ext.cpp (to_absolute).
lsim::sim::GatewayAbsoluteSensitivity to_absolute(const lsim_gateway_v2* gw2) {
    lsim::sim::GatewayAbsoluteSensitivity a;
    if (gw2 == nullptr || gw2->sensitivity_model == LSIM_SENSITIVITY_MODEL_NONE) return a;
    a.enabled = true;
    a.present = gw2->present;
    for (std::size_t b = 0; b < 3; ++b) {
        for (std::size_t k = 0; k < 8; ++k) a.dbm[b][k] = gw2->sensitivity_dbm[b][k];
    }
    return a;
}

// Environnement : copie de c_api_ext.cpp (build_environment).
int32_t build_environment(const lsim_environment* in, lsim::env::ElevationGrid& grid,
                          std::vector<lsim::env::Obstacle>& obstacles, lsim::env::Environment& out) {
    out = lsim::env::Environment{};
    out.gateway_height_m = in->gateway_height_m;
    out.device_height_m = in->device_height_m;
    if (in->obstacle_count > 0 && in->obstacles == nullptr) {
        return LSIM_STATUS_ENV_BASE + static_cast<int32_t>(lsim::env::EnvStatus::InvalidInput);
    }
    if (in->obstacle_count > lsim::env::kMaxObstacles) {
        return LSIM_STATUS_ENV_BASE + static_cast<int32_t>(lsim::env::EnvStatus::TooManyObstacles);
    }
    obstacles.resize(in->obstacle_count);
    for (std::size_t i = 0; i < in->obstacle_count; ++i) {
        const lsim_obstacle& o = in->obstacles[i];
        obstacles[i].x_min_m = o.x_min_m;
        obstacles[i].y_min_m = o.y_min_m;
        obstacles[i].x_max_m = o.x_max_m;
        obstacles[i].y_max_m = o.y_max_m;
        obstacles[i].height_m = o.height_m;
        obstacles[i].attenuation_db = o.attenuation_db;
    }
    out.obstacles = obstacles.data();
    out.obstacle_count = obstacles.size();
    if (in->grid_z != nullptr) {
        const std::size_t count = static_cast<std::size_t>(in->grid_nx) * in->grid_ny;
        const auto st = lsim::env::make_elevation_grid(in->grid_origin_x_m, in->grid_origin_y_m,
                                                       in->grid_cell_m, in->grid_nx, in->grid_ny,
                                                       in->grid_z, count, grid);
        if (st != lsim::env::EnvStatus::Ok) {
            return LSIM_STATUS_ENV_BASE + static_cast<int32_t>(st);
        }
        out.grid = &grid;
    }
    return 0;
}

// Exécution après validation. Ne touche aux sorties utilisateur qu'à travers emit_closed_loop_v3.
int32_t run_closed_loop_v3(const lsim_closed_loop_v3_args& a) {
    const std::size_t n = a.device_count;

    std::uint64_t planned = 0;
    for (std::size_t i = 0; i < n; ++i) planned += a.devices[i].messages;
    if (planned > kMaxTraceRecords) {
        return LSIM_STATUS_SIM_BASE + static_cast<int32_t>(lsim::sim::SimStatus::TraceTooLarge);
    }

    // Dispositifs, radios et régions.
    std::vector<lsim::sim::EndDeviceSpec> specs(n);
    for (std::size_t i = 0; i < n; ++i) {
        const lsim_end_device& d = a.devices[i];
        lsim::sim::EndDeviceSpec& s = specs[i];
        s.position.x_m = d.x_m;
        s.position.y_m = d.y_m;
        s.spreading_factor = d.spreading_factor;
        s.payload_bytes = d.payload_bytes;
        s.tx_power_dbm = d.tx_power_dbm;
        s.start_offset_ns = d.start_offset_ns;
        s.period_ns = d.period_ns;
        s.messages = d.messages;
        s.duty_cycle = d.duty_cycle;
    }
    std::vector<lsim::plan::DeviceRadio> rv(n);
    for (std::size_t i = 0; i < n; ++i) {
        const lsim_plan_device& d = a.radios[i];
        lsim::plan::DeviceRadio& r = rv[i];
        r.freq_hz = d.freq_hz;
        r.dr = d.dr;
        r.rx1_hz = d.rx1_hz;
        r.tx_power_dbm = d.tx_power_dbm;
        r.rx1_sf = d.rx1_sf;
        r.rx1_bw_hz = d.rx1_bw_hz;
    }
    std::vector<lsim::sim::LoopRegion> rg(n);
    for (std::size_t i = 0; i < n; ++i) {
        for (std::size_t k = 0; k < 16; ++k) {
            rg[i].dr_sf[k] = a.regions[i].dr_sf[k];
            rg[i].duty_limit[k] = a.regions[i].duty_limit[k];
        }
        rg[i].max_dr = a.regions[i].max_dr;
        rg[i].max_tx_power_index = a.regions[i].max_tx_power_index;
        rg[i].power_step_tenth_db = a.regions[i].power_step_tenth_db;
        rg[i].max_eirp_dbm = a.regions[i].max_eirp_dbm;
    }

    // Options du protocole et MAC (mêmes conversions que closed_loop_impl de c_api_ext.cpp).
    lsim::sim::LoopOptions lo;
    const lsim_plan_options& po = a.options->protocol;
    lo.protocol.confirmed_uplinks = po.confirmed_uplinks != 0;
    lo.protocol.downlink_every = po.downlink_every;
    lo.protocol.downlink_payload_bytes = po.downlink_payload_bytes;
    lo.protocol.gateway_tx_power_dbm = po.gateway_tx_power_dbm;
    lo.protocol.device_antenna_gain_dbi = po.device_antenna_gain_dbi;
    lo.protocol.device_rx_offset_db = po.device_rx_offset_db;
    lo.adr = a.options->adr != 0;
    lo.installation_margin_tenth_db = a.options->installation_margin_tenth_db;
    lo.duty_cycle = a.options->duty_cycle != 0;
    lo.duty_cycle_exponent = a.options->duty_cycle_exponent;
    std::vector<lsim::sim::LoopMacSlot> slots;
    slots.reserve(a.mac_count);
    for (std::size_t m = 0; m < a.mac_count; ++m) {
        lsim::sim::LoopMacSlot s;
        s.device = a.mac[m].device_index;
        s.rank = a.mac[m].rank;
        s.extra_bytes = a.mac[m].extra_bytes;
        s.flags = a.mac[m].flags;
        slots.push_back(s);
    }
    lo.mac = slots.data();
    lo.mac_count = slots.size();

    // Options et radios validées avant simulation (mêmes codes que lsim_plan_downlinks_v1).
    const lsim::plan::DownlinkScheduler probe(rv, lo.protocol);
    if (probe.status() != lsim::plan::PlanStatus::Ok) {
        return LSIM_STATUS_PLAN_BASE + static_cast<int32_t>(probe.status());
    }

    // Passerelle (gw2) : refus des modèles de sensibilité inconnus, comme gw2.
    if (a.gateway->sensitivity_model > LSIM_SENSITIVITY_MODEL_ABSOLUTE_PER_SF_V2) {
        return LSIM_STATUS_SIM_BASE + static_cast<int32_t>(lsim::sim::SimStatus::InvalidInput);
    }
    const lsim::sim::GatewayAbsoluteSensitivity absolute = to_absolute(a.gateway);
    lsim::sim::GatewaySpec g;
    g.position.x_m = a.gateway->base.x_m;
    g.position.y_m = a.gateway->base.y_m;
    g.antenna_gain_dbi = a.gateway->base.antenna_gain_dbi;
    g.rx_sensitivity_offset_db = a.gateway->base.rx_sensitivity_offset_db;
    g.absolute = absolute;

    lsim::sim::PropagationSpec p;
    p.frequency_hz = a.prop->frequency_hz;
    p.reference_distance_m = a.prop->reference_distance_m;
    p.exponent = a.prop->exponent;
    p.capture_threshold_db = a.prop->capture_threshold_db;
    p.shadowing_sigma_db = a.prop->shadowing_sigma_db;
    p.shadowing_seed = a.prop->shadowing_seed;

    lsim::env::ElevationGrid grid;
    std::vector<lsim::env::Obstacle> obstacles;
    lsim::env::Environment e;
    if (a.env != nullptr) {
        const int32_t built = build_environment(a.env, grid, obstacles, e);
        if (built != 0) return built;
    }

    // Configuration canal : absente en mode historique (chemin moteur par défaut), explicite sinon.
    std::vector<lsim::sim::LoopChannelConfig> configs;
    lsim::sim::LoopChannelIo io;
    io.trace_v3 = a.trace_enabled == 1;
    if (!lsim::sim::abi_v3::is_historical_channel_mode(a)) {
        configs = lsim::sim::abi_v3::build_channel_configs(a);
        io.config = configs.data();
        io.config_count = configs.size();
    }

    // Moteur canal.
    std::vector<lsim::sim::DeviceStats> stats(n);
    lsim::sim::SimulationStats tot;
    lsim::sim::LoopResult res;
    const lsim::sim::SimStatus st = lsim::sim::simulate_closed_loop_channels(
        specs.data(), n, rv.data(), rg.data(), g, p, a.env != nullptr ? &e : nullptr, lo, stats.data(),
        tot, res, io);
    if (st != lsim::sim::SimStatus::Ok) {
        return LSIM_STATUS_SIM_BASE + static_cast<int32_t>(st);
    }

    // Sorties : écriture atomique, uniquement après succès du moteur.
    lsim::sim::abi_v3::EngineOutputs out;
    out.per_device = std::move(stats);
    out.totals = tot;
    out.result = std::move(res);
    out.io = std::move(io);
    return lsim::sim::abi_v3::emit_closed_loop_v3(&a, 0, out);
}

}  // namespace

extern "C" {

int32_t lsim_simulate_closed_loop_v3(const lsim_closed_loop_v3_args* args) {
    const int32_t valid = lsim::sim::abi_v3::validate_closed_loop_v3_args(args);
    if (valid != 0) return valid;
    try {
        return run_closed_loop_v3(*args);
    } catch (...) {
        return LSIM_STATUS_INTERNAL;
    }
}

}  // extern "C"
