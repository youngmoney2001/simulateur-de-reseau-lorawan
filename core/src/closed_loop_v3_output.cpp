// SPDX-License-Identifier: Apache-2.0
// Écriture atomique des sorties de lsim_simulate_closed_loop_v3 (étape 6.2.5).
#include "lsim/closed_loop_v3_output.hpp"

#include <cstddef>
#include <cstdint>
#include <vector>

#include "lsim/closed_loop_v3_config.hpp"
#include "lsim/closed_loop_v3_validate.hpp"
#include "lsim/loop_adr.hpp"

namespace lsim::sim::abi_v3 {
namespace {

struct Converted {
    std::vector<lsim_loop_uplink> uplinks;
    std::vector<lsim_loop_downlink> downlinks;
    std::vector<lsim_interval> busy;
    std::vector<lsim_loop_trace_v3> trace;
    std::vector<lsim_channel_terminal_v3> terminals;
    std::vector<lsim_device_stats> per_device;
    lsim_sim_stats totals{};
    lsim_loop_mac_counters mac{};
};

// Conversions pures, sans écriture utilisateur. Tout ce qui peut échouer (allocations) a lieu ici.
Converted convert_all(const lsim_closed_loop_v3_args& a, const EngineOutputs& out) {
    Converted c;
    const LoopResult& res = out.result;

    c.uplinks.resize(res.uplinks.size());
    for (std::size_t k = 0; k < res.uplinks.size(); ++k) {
        const LoopUplink& u = res.uplinks[k];
        lsim_loop_uplink& o = c.uplinks[k];
        o.device_index = u.device;
        o.start_ns = u.start_ns;
        o.end_ns = u.end_ns;
        o.spreading_factor = u.spreading_factor;
        o.dr = u.dr;
        o.power_index = u.power_index;
        o.rssi_dbm = u.rssi_dbm;
        o.outcome = static_cast<std::uint8_t>(u.outcome);
        o.answer_mask = u.answer_mask;
        o.answer_ok = u.answer_ok;
    }

    c.downlinks.resize(res.downlinks.size());
    for (std::size_t k = 0; k < res.downlinks.size(); ++k) {
        const LoopDownlink& d = res.downlinks[k];
        lsim_loop_downlink& o = c.downlinks[k];
        o.uplink_index = d.uplink;
        o.device_index = d.device;
        o.kind = d.kind;
        o.commands = d.commands;
        o.t_open_ns = d.t_open;
        o.start_ns = d.start_ns;
        o.air_ns = d.air_ns;
        o.device_missed = d.device_missed ? 1 : 0;
        o.delivered = d.delivered ? 1 : 0;
        o.req_dr = d.req_dr;
        o.req_power_index = d.req_power_index;
    }

    c.busy.resize(res.gateway_busy.size());
    for (std::size_t k = 0; k < res.gateway_busy.size(); ++k) {
        c.busy[k].start_ns = res.gateway_busy[k].start;
        c.busy[k].end_ns = res.gateway_busy[k].end;
    }

    // La trace n'est produite que si trace_enabled == 1 (l'appelant active io.trace_v3 dans ce cas).
    if (a.trace_enabled == 1) c.trace = convert_trace_v3(out.io.trace);

    c.terminals.resize(out.io.terminals.size());
    for (std::size_t i = 0; i < out.io.terminals.size(); ++i) {
        const LoopTerminalRadio& t = out.io.terminals[i];
        lsim_channel_terminal_v3& o = c.terminals[i];
        o.struct_size = sizeof(lsim_channel_terminal_v3);
        o.abi_version = 3;
        o.device_index = static_cast<std::uint32_t>(i);
        o.dr = t.dr;
        o.power_index = t.power_index;
        o.reserved0 = 0;
        for (std::size_t ch = 0; ch < kLoopMaxChannels; ++ch) {
            o.dr_mask[ch] = t.channels.dr_mask[ch];
            if (t.channels.enabled.test(ch)) {
                o.enabled[ch / 8U] = static_cast<std::uint8_t>(o.enabled[ch / 8U] | (1U << (ch % 8U)));
            }
        }
        for (std::uint8_t& r : o.reserved1) r = 0;
    }

    c.per_device.resize(out.per_device.size());
    for (std::size_t i = 0; i < out.per_device.size(); ++i) {
        const DeviceStats& s = out.per_device[i];
        lsim_device_stats& o = c.per_device[i];
        o.sent = s.sent;
        o.received = s.received;
        o.lost_sensitivity = s.lost_sensitivity;
        o.lost_collision = s.lost_collision;
        o.airtime_ns = s.airtime_ns;
        o.lost_gateway_busy = s.lost_gateway_busy;
    }

    const SimulationStats& tot = out.totals;
    c.totals.sent = tot.sent;
    c.totals.received = tot.received;
    c.totals.lost_sensitivity = tot.lost_sensitivity;
    c.totals.lost_collision = tot.lost_collision;
    c.totals.airtime_ns = tot.airtime_ns;
    c.totals.lost_gateway_busy = tot.lost_gateway_busy;
    c.totals.gateway_busy_ns = tot.gateway_busy_ns;
    c.totals.gateway_peak_concurrent = tot.gateway_peak_concurrent;
    c.totals.observation_ns = tot.observation_ns;
    c.totals.gateway_utilization = tot.gateway_utilization;

    c.mac.enqueued = res.mac.enqueued;
    c.mac.dispatched = res.mac.dispatched;
    c.mac.delivered = res.mac.delivered;
    c.mac.dispatch_lost = res.mac.dispatch_lost;
    c.mac.deferred = res.mac.deferred;
    c.mac.expired = res.mac.expired;
    c.mac.pending_at_end = res.mac.pending_at_end;
    return c;
}

// Compteurs requis : écrits dans tous les cas où la sortie est décidée (succès ou capacité).
void write_counts(const lsim_closed_loop_v3_args& a, std::size_t up, std::size_t dl, std::size_t busy,
                  std::size_t trace, std::size_t terminals) {
    *a.uplink_count = up;
    *a.downlink_count = dl;
    *a.busy_count = busy;
    *a.trace_count = trace;
    *a.terminal_count = terminals;
}

}  // namespace

std::int32_t emit_closed_loop_v3(const lsim_closed_loop_v3_args* args, std::int32_t engine_status,
                                 const EngineOutputs& out) {
    const std::int32_t valid = validate_closed_loop_v3_args(args);
    if (valid != 0) return valid;
    if (engine_status != 0) return engine_status;
    const lsim_closed_loop_v3_args& a = *args;
    try {
        const std::size_t n = a.device_count;
        if (out.per_device.size() != n || out.io.terminals.size() != n) {
            return LSIM_STATUS_INTERNAL;
        }
        const std::size_t trace_n = a.trace_enabled == 1 ? out.io.trace.size() : 0;
        const std::size_t up_n = out.result.uplinks.size();
        const std::size_t dl_n = out.result.downlinks.size();
        const std::size_t busy_n = out.result.gateway_busy.size();

        // Capacités, dans l'ordre gelé en 6.1. Seuls les compteurs requis sont écrits.
        if (up_n > a.uplink_capacity) {
            write_counts(a, up_n, dl_n, busy_n, trace_n, n);
            return LSIM_STATUS_SIM_BASE + static_cast<std::int32_t>(SimStatus::TraceBufferTooSmall);
        }
        if (dl_n > a.downlink_capacity || busy_n > a.busy_capacity) {
            write_counts(a, up_n, dl_n, busy_n, trace_n, n);
            return LSIM_STATUS_PLAN_BASE + 4;
        }
        if (trace_n > a.trace_capacity) {
            write_counts(a, up_n, dl_n, busy_n, trace_n, n);
            return LSIM_STATUS_CHANNEL_TRACE_BUFFER_TOO_SMALL;
        }
        if (n > a.terminal_capacity) {
            write_counts(a, up_n, dl_n, busy_n, trace_n, n);
            return LSIM_STATUS_CHANNEL_TERMINAL_BUFFER_TOO_SMALL;
        }

        // Succès : préparer toutes les sorties, puis copier sans échec possible.
        const Converted c = convert_all(a, out);
        for (std::size_t k = 0; k < up_n; ++k) a.uplinks[k] = c.uplinks[k];
        for (std::size_t k = 0; k < dl_n; ++k) a.downlinks[k] = c.downlinks[k];
        for (std::size_t k = 0; k < busy_n; ++k) a.busy[k] = c.busy[k];
        for (std::size_t k = 0; k < trace_n; ++k) a.trace[k] = c.trace[k];
        for (std::size_t k = 0; k < n; ++k) a.terminals[k] = c.terminals[k];
        for (std::size_t i = 0; i < n; ++i) a.per_device[i] = c.per_device[i];
        *a.totals = c.totals;
        if (a.mac_counters != nullptr) *a.mac_counters = c.mac;
        write_counts(a, up_n, dl_n, busy_n, trace_n, n);
        return 0;
    } catch (...) {
        return LSIM_STATUS_INTERNAL;
    }
}

}  // namespace lsim::sim::abi_v3
