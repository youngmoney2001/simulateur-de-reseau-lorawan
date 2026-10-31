// SPDX-License-Identifier: Apache-2.0
// Tests des sorties v3 (étape 6.2.5) : capacités exactes, insuffisantes et nulles, ordre des erreurs,
// absence d'écriture en cas d'erreur de validation ou moteur, convention du buffer terminals.
// Aucune fonction v3 n'est exportée : les tests appellent emit_closed_loop_v3 directement.
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <vector>

#include "check.hpp"
#include "lsim/c_api.h"
#include "lsim/closed_loop_v3_output.hpp"
#include "lsim/engine.hpp"
#include "lsim/loop_adr.hpp"

namespace {

using namespace lsim::sim;
using lsim::sim::abi_v3::EngineOutputs;
using lsim::sim::abi_v3::emit_closed_loop_v3;

constexpr SimTime kS = 1'000'000'000;
constexpr std::uint8_t kPattern = 0xA5;
constexpr std::size_t kCountSentinel = 0x5A5A5A5A5A5A5A5AULL;

EndDeviceSpec dev(double x_m, std::uint8_t sf, SimTime offset_ns, SimTime period_ns, std::uint32_t messages) {
    EndDeviceSpec d;
    d.position.x_m = x_m;
    d.spreading_factor = sf;
    d.payload_bytes = 10;
    d.tx_power_dbm = 14.0;
    d.start_offset_ns = offset_ns;
    d.period_ns = period_ns;
    d.messages = messages;
    d.duty_cycle = 1.0;
    return d;
}

lsim::plan::DeviceRadio radio() {
    lsim::plan::DeviceRadio r;
    r.freq_hz = 868'100'000;
    r.rx1_hz = 868'100'000;
    r.tx_power_dbm = 14.0;
    r.rx1_bw_hz = 125'000;
    return r;
}

LoopRegion region() {
    LoopRegion r;
    for (std::size_t i = 0; i < 6; ++i) r.dr_sf[i] = static_cast<std::uint8_t>(12 - i);
    r.max_dr = 5;
    r.max_tx_power_index = 7;
    r.power_step_tenth_db = 20;
    for (std::size_t i = 0; i <= 7; ++i) r.duty_limit[i] = 1.0;
    return r;
}

// Scénario à deux dispositifs : passerelle occupée, NoGatewaySlot, descentes, busy, trace.
SimStatus run_two_devices(EngineOutputs& out, bool trace, double duty_exponent_override = -1.0) {
    const std::vector<EndDeviceSpec> devs = {dev(10.0, 12, 0, 60 * kS, 1), dev(10.0, 7, kS, 60 * kS, 1)};
    const std::vector<lsim::plan::DeviceRadio> rv = {radio(), radio()};
    const std::vector<LoopRegion> regions = {region(), region()};
    const std::vector<LoopMacSlot> slots = {{0, 1, 0, kLoopMacLinkCheck}, {1, 1, 0, kLoopMacLinkCheck}};
    LoopOptions opt;
    opt.mac = slots.data();
    opt.mac_count = slots.size();
    if (duty_exponent_override >= 0.0) {
        opt.duty_cycle = true;
        opt.duty_cycle_exponent = 16;   // invalide : InvalidInput
    }
    out = EngineOutputs{};
    out.per_device.assign(devs.size(), DeviceStats{});
    out.io.trace_v3 = trace;
    return simulate_closed_loop_channels(devs.data(), devs.size(), rv.data(), regions.data(), GatewaySpec{},
                                         PropagationSpec{}, nullptr, opt, out.per_device.data(), out.totals,
                                         out.result, out.io);
}

// Sorties utilisateur remplies d'un motif : toute écriture non prévue est détectée.
template <class T>
std::vector<T> pattern_buffer(std::size_t capacity) {
    std::vector<T> v(capacity > 0 ? capacity : 1);
    std::memset(v.data(), kPattern, sizeof(T) * v.size());
    return v;
}

bool bytes_are(const void* p, std::size_t bytes, std::uint8_t value) {
    const auto* b = static_cast<const std::uint8_t*>(p);
    for (std::size_t i = 0; i < bytes; ++i) {
        if (b[i] != value) return false;
    }
    return true;
}

struct Caps {
    std::size_t devices = 2;
    std::size_t uplinks = 0;
    std::size_t downlinks = 0;
    std::size_t busy = 0;
    std::size_t trace = 0;
    std::size_t terminals = 0;
    bool trace_on = true;
    bool with_mac = true;
    bool null_terminals = false;
};

// Arguments v3 complets (historique : pas de configuration explicite), buffers remplis d'un motif.
struct Harness {
    lsim_end_device devices[2]{};
    lsim_plan_device radios[2]{};
    lsim_loop_region regions[2]{};
    lsim_gateway_v2 gateway{};
    lsim_propagation prop{};
    lsim_loop_options options{};
    std::vector<lsim_device_stats> per_device;
    lsim_sim_stats totals{};
    lsim_loop_mac_counters mac{};
    std::vector<lsim_loop_uplink> uplinks;
    std::vector<lsim_loop_downlink> downlinks;
    std::vector<lsim_interval> busy;
    std::vector<lsim_loop_trace_v3> trace;
    std::vector<lsim_channel_terminal_v3> terminals;
    std::size_t uplink_count = kCountSentinel;
    std::size_t downlink_count = kCountSentinel;
    std::size_t busy_count = kCountSentinel;
    std::size_t trace_count = kCountSentinel;
    std::size_t terminal_count = kCountSentinel;
    lsim_closed_loop_v3_args args{};

    explicit Harness(const Caps& c) {
        per_device = std::vector<lsim_device_stats>(c.devices > 0 ? c.devices : 1);
        std::memset(per_device.data(), kPattern, sizeof(lsim_device_stats) * per_device.size());
        std::memset(&totals, kPattern, sizeof(totals));
        std::memset(&mac, kPattern, sizeof(mac));
        uplinks = pattern_buffer<lsim_loop_uplink>(c.uplinks);
        downlinks = pattern_buffer<lsim_loop_downlink>(c.downlinks);
        busy = pattern_buffer<lsim_interval>(c.busy);
        trace = pattern_buffer<lsim_loop_trace_v3>(c.trace);
        terminals = pattern_buffer<lsim_channel_terminal_v3>(c.terminals);
        args.struct_size = sizeof(lsim_closed_loop_v3_args);
        args.abi_version = 3;
        args.channel_plan = LSIM_CHANNEL_PLAN_NONE;
        args.trace_enabled = c.trace_on ? 1U : 0U;
        args.trace_element_size = sizeof(lsim_loop_trace_v3);
        args.terminal_element_size = sizeof(lsim_channel_terminal_v3);
        args.devices = devices;
        args.device_count = c.devices;
        args.radios = radios;
        args.regions = regions;
        args.gateway = &gateway;
        args.prop = &prop;
        args.options = &options;
        args.channels = nullptr;
        args.channel_count = 0;
        args.per_device = per_device.data();
        args.totals = &totals;
        args.mac_counters = c.with_mac ? &mac : nullptr;
        args.uplinks = uplinks.data();
        args.uplink_capacity = c.uplinks;
        args.uplink_count = &uplink_count;
        args.downlinks = downlinks.data();
        args.downlink_capacity = c.downlinks;
        args.downlink_count = &downlink_count;
        args.busy = busy.data();
        args.busy_capacity = c.busy;
        args.busy_count = &busy_count;
        args.trace = c.trace_on ? trace.data() : nullptr;
        args.trace_capacity = c.trace_on ? c.trace : 0;
        args.trace_count = &trace_count;
        args.terminals = c.null_terminals ? nullptr : terminals.data();
        args.terminal_capacity = c.null_terminals ? 0 : c.terminals;
        args.terminal_count = &terminal_count;
    }

    // Vrai si aucune sortie utilisateur n'a été touchée (buffers, totaux, compteurs).
    bool untouched() const {
        if (!bytes_are(per_device.data(), sizeof(lsim_device_stats) * per_device.size(), kPattern)) return false;
        if (!bytes_are(&totals, sizeof(totals), kPattern)) return false;
        if (!bytes_are(&mac, sizeof(mac), kPattern)) return false;
        if (!bytes_are(uplinks.data(), sizeof(lsim_loop_uplink) * uplinks.size(), kPattern)) return false;
        if (!bytes_are(downlinks.data(), sizeof(lsim_loop_downlink) * downlinks.size(), kPattern)) return false;
        if (!bytes_are(busy.data(), sizeof(lsim_interval) * busy.size(), kPattern)) return false;
        if (!bytes_are(trace.data(), sizeof(lsim_loop_trace_v3) * trace.size(), kPattern)) return false;
        if (!bytes_are(terminals.data(), sizeof(lsim_channel_terminal_v3) * terminals.size(), kPattern)) return false;
        return uplink_count == kCountSentinel && downlink_count == kCountSentinel && busy_count == kCountSentinel &&
               trace_count == kCountSentinel && terminal_count == kCountSentinel;
    }

    // Compteurs requis écrits, buffers et sorties non touchés (cas de capacité insuffisante).
    bool counters_only(std::size_t up, std::size_t dl, std::size_t busy_n, std::size_t trace_n,
                       std::size_t term_n) const {
        if (uplink_count != up || downlink_count != dl || busy_count != busy_n || trace_count != trace_n ||
            terminal_count != term_n) {
            return false;
        }
        if (!bytes_are(per_device.data(), sizeof(lsim_device_stats) * per_device.size(), kPattern)) return false;
        if (!bytes_are(&totals, sizeof(totals), kPattern)) return false;
        if (!bytes_are(&mac, sizeof(mac), kPattern)) return false;
        if (!bytes_are(uplinks.data(), sizeof(lsim_loop_uplink) * uplinks.size(), kPattern)) return false;
        if (!bytes_are(downlinks.data(), sizeof(lsim_loop_downlink) * downlinks.size(), kPattern)) return false;
        if (!bytes_are(busy.data(), sizeof(lsim_interval) * busy.size(), kPattern)) return false;
        if (!bytes_are(trace.data(), sizeof(lsim_loop_trace_v3) * trace.size(), kPattern)) return false;
        return bytes_are(terminals.data(), sizeof(lsim_channel_terminal_v3) * terminals.size(), kPattern);
    }
};

Caps exact_caps(const EngineOutputs& out, bool trace_on) {
    Caps c;
    c.devices = out.per_device.size();
    c.uplinks = out.result.uplinks.size();
    c.downlinks = out.result.downlinks.size();
    c.busy = out.result.gateway_busy.size();
    c.trace = trace_on ? out.io.trace.size() : 0;
    c.terminals = out.io.terminals.size();
    c.trace_on = trace_on;
    return c;
}

int32_t mapped_sim(SimStatus s) { return LSIM_STATUS_SIM_BASE + static_cast<std::int32_t>(s); }

// Une capacité exacte produit exactement les résultats ; les conversions sont fidèles.
void test_exact_capacities_success_copies_everything() {
    EngineOutputs out;
    CHECK_EQ(static_cast<int>(run_two_devices(out, true)), 0);
    CHECK_EQ(out.result.uplinks.size(), std::size_t{2});
    CHECK_EQ(out.result.downlinks.size(), std::size_t{2});
    CHECK_TRUE(out.result.gateway_busy.size() >= 1);
    CHECK_EQ(out.io.terminals.size(), std::size_t{2});
    const Caps c = exact_caps(out, true);
    Harness h(c);
    CHECK_EQ(static_cast<int>(emit_closed_loop_v3(&h.args, 0, out)), 0);
    CHECK_EQ(h.uplink_count, out.result.uplinks.size());
    CHECK_EQ(h.downlink_count, out.result.downlinks.size());
    CHECK_EQ(h.busy_count, out.result.gateway_busy.size());
    CHECK_EQ(h.trace_count, out.io.trace.size());
    CHECK_EQ(h.terminal_count, std::size_t{2});
    for (std::size_t k = 0; k < out.result.uplinks.size(); ++k) {
        CHECK_EQ(static_cast<int>(h.uplinks[k].device_index), static_cast<int>(out.result.uplinks[k].device));
        CHECK_TRUE(h.uplinks[k].start_ns == out.result.uplinks[k].start_ns);
        CHECK_TRUE(h.uplinks[k].end_ns == out.result.uplinks[k].end_ns);
    }
    for (std::size_t k = 0; k < out.result.downlinks.size(); ++k) {
        CHECK_EQ(static_cast<int>(h.downlinks[k].device_index), static_cast<int>(out.result.downlinks[k].device));
        CHECK_TRUE(h.downlinks[k].t_open_ns == out.result.downlinks[k].t_open);
        CHECK_EQ(static_cast<int>(h.downlinks[k].delivered), out.result.downlinks[k].delivered ? 1 : 0);
    }
    for (std::size_t k = 0; k < out.result.gateway_busy.size(); ++k) {
        CHECK_TRUE(h.busy[k].start_ns == out.result.gateway_busy[k].start);
        CHECK_TRUE(h.busy[k].end_ns == out.result.gateway_busy[k].end);
    }
    for (std::size_t k = 0; k < out.io.trace.size(); ++k) {
        CHECK_TRUE(h.trace[k].t_ns == out.io.trace[k].t_ns);
        CHECK_EQ(static_cast<int>(h.trace[k].kind), static_cast<int>(out.io.trace[k].kind));
        CHECK_EQ(static_cast<int>(h.trace[k].reserved), 0);
    }
    // Terminaux : bits 0..2 actifs dans la configuration par défaut, DR0..DR5 définis.
    for (std::size_t i = 0; i < 2; ++i) {
        CHECK_EQ(static_cast<int>(h.terminals[i].device_index), static_cast<int>(i));
        CHECK_EQ(static_cast<int>(h.terminals[i].enabled[0]), 0x07);
        CHECK_EQ(static_cast<int>(h.terminals[i].dr_mask[0]), 0x3F);
        CHECK_EQ(static_cast<int>(h.terminals[i].dr), static_cast<int>(out.io.terminals[i].dr));
        CHECK_EQ(static_cast<int>(h.terminals[i].reserved0), 0);
    }
    for (std::size_t i = 0; i < 2; ++i) {
        CHECK_TRUE(h.per_device[i].sent == out.per_device[i].sent);
        CHECK_TRUE(h.per_device[i].airtime_ns == out.per_device[i].airtime_ns);
    }
    CHECK_TRUE(h.totals.airtime_ns == out.totals.airtime_ns);
    CHECK_TRUE(h.mac.enqueued == out.result.mac.enqueued);
    CHECK_TRUE(h.mac.pending_at_end == out.result.mac.pending_at_end);
}

// Capacités supérieures : seuls les éléments résultats sont écrits, le reste du buffer n'est pas touché.
void test_larger_capacities_write_only_results() {
    EngineOutputs out;
    CHECK_EQ(static_cast<int>(run_two_devices(out, true)), 0);
    Caps c = exact_caps(out, true);
    c.uplinks += 3;
    c.downlinks += 3;
    c.busy += 3;
    c.trace += 3;
    Harness h(c);
    CHECK_EQ(static_cast<int>(emit_closed_loop_v3(&h.args, 0, out)), 0);
    CHECK_EQ(h.uplink_count, out.result.uplinks.size());
    CHECK_TRUE(bytes_are(&h.uplinks[out.result.uplinks.size()], sizeof(lsim_loop_uplink) * 3, kPattern));
    CHECK_TRUE(bytes_are(&h.downlinks[out.result.downlinks.size()], sizeof(lsim_loop_downlink) * 3, kPattern));
    CHECK_TRUE(bytes_are(&h.busy[out.result.gateway_busy.size()], sizeof(lsim_interval) * 3, kPattern));
    CHECK_TRUE(bytes_are(&h.trace[out.io.trace.size()], sizeof(lsim_loop_trace_v3) * 3, kPattern));
}

// Capacités nulles avec résultats : erreur de capacité, aucune écriture de buffer ni de sortie.
void test_zero_capacities_with_results_write_nothing_but_counts() {
    EngineOutputs out;
    CHECK_EQ(static_cast<int>(run_two_devices(out, true)), 0);
    Caps c;
    c.devices = 2;
    c.trace_on = true;
    c.null_terminals = true;
    Harness h(c);
    const std::size_t up = out.result.uplinks.size();
    const std::size_t dl = out.result.downlinks.size();
    const std::size_t busy = out.result.gateway_busy.size();
    const std::size_t tr = out.io.trace.size();
    CHECK_EQ(static_cast<int>(emit_closed_loop_v3(&h.args, 0, out)),
             static_cast<int>(mapped_sim(SimStatus::TraceBufferTooSmall)));
    CHECK_TRUE(h.counters_only(up, dl, busy, tr, 2));
}

// Priorité gelée : uplinks, puis downlinks/busy, puis trace, puis terminaux. Pour chaque combinaison,
// seule l'erreur de rang le plus haut est publiée, et seuls les compteurs sont écrits.
void test_capacity_error_priority_and_counters_only() {
    EngineOutputs out;
    CHECK_EQ(static_cast<int>(run_two_devices(out, true)), 0);
    const std::size_t up = out.result.uplinks.size();
    const std::size_t dl = out.result.downlinks.size();
    const std::size_t busy = out.result.gateway_busy.size();
    const std::size_t tr = out.io.trace.size();
    struct Case {
        const char* name;
        int32_t expected;
        Caps caps;
    };
    const Caps exact = exact_caps(out, true);
    std::vector<Case> cases;
    {
        Caps c = exact; c.uplinks = up - 1; c.downlinks = 0; c.busy = 0; c.trace = 0; c.terminals = 0;
        cases.push_back({"uplinks insuffisants, tout le reste nul", mapped_sim(SimStatus::TraceBufferTooSmall), c});
    }
    {
        Caps c = exact; c.downlinks = dl - 1; c.trace = 0; c.terminals = 0;
        cases.push_back({"downlinks insuffisantes, trace et terminaux nuls", LSIM_STATUS_PLAN_BASE + 4, c});
    }
    {
        Caps c = exact; c.busy = busy - 1; c.trace = 0; c.terminals = 0;
        cases.push_back({"busy insuffisant", LSIM_STATUS_PLAN_BASE + 4, c});
    }
    {
        Caps c = exact; c.trace = tr - 1; c.terminals = 0;
        cases.push_back({"trace insuffisante et terminaux nuls", LSIM_STATUS_CHANNEL_TRACE_BUFFER_TOO_SMALL, c});
    }
    {
        Caps c = exact; c.terminals = 1;
        cases.push_back({"terminaux insuffisants seuls", LSIM_STATUS_CHANNEL_TERMINAL_BUFFER_TOO_SMALL, c});
    }
    {
        Caps c = exact; c.terminals = 0; c.null_terminals = true;
        cases.push_back({"terminaux NULL (capacité nulle)", LSIM_STATUS_CHANNEL_TERMINAL_BUFFER_TOO_SMALL, c});
    }
    for (const Case& k : cases) {
        Harness h(k.caps);
        const int32_t got = static_cast<int32_t>(emit_closed_loop_v3(&h.args, 0, out));
        CHECK_EQ(static_cast<int>(got), static_cast<int>(k.expected));
        CHECK_TRUE(h.counters_only(up, dl, busy, tr, 2));
        (void)k.name;
    }
}

// Erreur moteur : aucune écriture, même des compteurs.
void test_engine_error_writes_nothing() {
    EngineOutputs out;
    const SimStatus st = run_two_devices(out, true, 0.0);
    CHECK_TRUE(st != SimStatus::Ok);
    Caps c = exact_caps(out, true);
    c.uplinks = 10;
    c.downlinks = 10;
    c.busy = 10;
    c.trace = 10;
    c.terminals = 2;
    Harness h(c);
    CHECK_EQ(static_cast<int>(emit_closed_loop_v3(&h.args, mapped_sim(st), out)), static_cast<int>(mapped_sim(st)));
    CHECK_TRUE(h.untouched());
}

// Erreur de validation : aucune écriture, même si les résultats sont présents.
void test_validation_error_writes_nothing() {
    EngineOutputs out;
    CHECK_EQ(static_cast<int>(run_two_devices(out, true)), 0);
    Harness h(exact_caps(out, true));
    h.args.struct_size = 1;
    CHECK_EQ(static_cast<int>(emit_closed_loop_v3(&h.args, 0, out)), static_cast<int>(LSIM_STATUS_CHANNEL_ARGS_SIZE));
    CHECK_TRUE(h.untouched());
}

// Trace désactivée : rien n'est écrit dans le buffer ni dans trace_count, même si le moteur a tracé.
void test_trace_disabled_writes_no_trace() {
    EngineOutputs out;
    CHECK_EQ(static_cast<int>(run_two_devices(out, true)), 0);
    Caps c = exact_caps(out, false);
    c.trace = 0;
    c.trace_on = false;
    Harness h(c);
    CHECK_EQ(static_cast<int>(emit_closed_loop_v3(&h.args, 0, out)), 0);
    CHECK_EQ(h.trace_count, std::size_t{0});
    CHECK_TRUE(bytes_are(h.trace.data(), sizeof(lsim_loop_trace_v3) * h.trace.size(), kPattern));
    CHECK_EQ(h.uplink_count, out.result.uplinks.size());
}

// Convention terminals : NULL vaut capacité nulle. Avec device_count = 0, le succès est possible
// sans buffer terminal ; avec device_count > 0, c'est TERMINAL_BUFFER_TOO_SMALL.
void test_terminals_null_convention() {
    EngineOutputs empty;
    empty.io.trace_v3 = false;
    Caps none;
    none.devices = 0;
    none.trace_on = false;
    none.null_terminals = true;
    none.with_mac = false;
    Harness ok(none);
    CHECK_EQ(static_cast<int>(emit_closed_loop_v3(&ok.args, 0, empty)), 0);
    CHECK_EQ(ok.terminal_count, std::size_t{0});
    CHECK_EQ(ok.uplink_count, std::size_t{0});
    CHECK_EQ(ok.downlink_count, std::size_t{0});
    CHECK_EQ(ok.busy_count, std::size_t{0});
    CHECK_EQ(ok.trace_count, std::size_t{0});
    CHECK_TRUE(bytes_are(&ok.mac, sizeof(ok.mac), kPattern));

    EngineOutputs out;
    CHECK_EQ(static_cast<int>(run_two_devices(out, true)), 0);
    Caps two = exact_caps(out, true);
    two.terminals = 0;
    two.null_terminals = true;
    Harness h(two);
    CHECK_EQ(static_cast<int>(emit_closed_loop_v3(&h.args, 0, out)),
             static_cast<int>(LSIM_STATUS_CHANNEL_TERMINAL_BUFFER_TOO_SMALL));
    CHECK_EQ(h.terminal_count, std::size_t{2});
}

// mac_counters est facultatif : NULL n'est pas une erreur, et rien n'est écrit dans ce cas.
void test_mac_counters_optional_on_success() {
    EngineOutputs out;
    CHECK_EQ(static_cast<int>(run_two_devices(out, true)), 0);
    Caps c = exact_caps(out, true);
    c.with_mac = false;
    Harness h(c);
    CHECK_EQ(static_cast<int>(emit_closed_loop_v3(&h.args, 0, out)), 0);
    CHECK_EQ(h.uplink_count, out.result.uplinks.size());
    CHECK_TRUE(bytes_are(&h.mac, sizeof(h.mac), kPattern));
}

// Incohérence interne (tailles par dispositif) : erreur interne, aucune écriture.
void test_internal_inconsistency_writes_nothing() {
    EngineOutputs out;
    CHECK_EQ(static_cast<int>(run_two_devices(out, true)), 0);
    out.per_device.pop_back();
    Harness h(exact_caps(out, true));
    CHECK_EQ(static_cast<int>(emit_closed_loop_v3(&h.args, 0, out)), static_cast<int>(LSIM_STATUS_INTERNAL));
    CHECK_TRUE(h.untouched());
}

}  // namespace

void run_closed_loop_v3_buffers_tests() {
    test_exact_capacities_success_copies_everything();
    test_larger_capacities_write_only_results();
    test_zero_capacities_with_results_write_nothing_but_counts();
    test_capacity_error_priority_and_counters_only();
    test_engine_error_writes_nothing();
    test_validation_error_writes_nothing();
    test_trace_disabled_writes_no_trace();
    test_terminals_null_convention();
    test_mac_counters_optional_on_success();
    test_internal_inconsistency_writes_nothing();
}
