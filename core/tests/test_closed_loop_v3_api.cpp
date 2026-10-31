// SPDX-License-Identifier: Apache-2.0
// Tests de la fonction publique lsim_simulate_closed_loop_v3 (étape 6.3). Chaque test appelle la
// fonction C exportée (core/src/c_api_closed_loop_v3.cpp) et non un helper interne. Couverts :
// erreurs d'arguments, de mode et de configuration, pointeurs NULL, alias et alignement, capacités,
// parité avec v2 et gw2 (mode historique et erreurs communes), configuration EU868 explicite,
// états terminaux, vue serveur, trace v3 (sept types), ADR réussi et ADR refusé, invariants MAC,
// absence d'écriture partielle.
#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <utility>
#include <vector>

#include "check.hpp"
#include "lsim/c_api.h"
#include "lsim/engine.hpp"

namespace {

constexpr std::int64_t kSec = 1'000'000'000;
constexpr std::int32_t kSimTooManyDevices =
    LSIM_STATUS_SIM_BASE + static_cast<std::int32_t>(lsim::sim::SimStatus::TooManyDevices);
constexpr std::int32_t kSimInvalidInput = LSIM_STATUS_SIM_BASE + static_cast<std::int32_t>(lsim::sim::SimStatus::InvalidInput);
// Uplinks insuffisants : même code que la v2 (SIM + TraceBufferTooSmall = 308).
constexpr std::int32_t kSimUplinkTooSmall =
    LSIM_STATUS_SIM_BASE + static_cast<std::int32_t>(lsim::sim::SimStatus::TraceBufferTooSmall);
// Descentes ou occupations insuffisantes : code historique PLAN + 4.
constexpr std::int32_t kPlanCapacity = LSIM_STATUS_PLAN_BASE + 4;
constexpr std::size_t kCountSentinel = 777;

// Scénario complet, en structures C publiques. Les sorties sont dans `Out`.
struct Scenario {
    std::vector<lsim_end_device> devices;
    std::vector<lsim_plan_device> radios;
    std::vector<lsim_loop_region> regions;
    lsim_gateway_v2 gateway{};
    lsim_propagation prop{};
    lsim_loop_options options{};
    std::vector<lsim_loop_mac> mac;
    std::vector<lsim_channel_device_v3> channels;  // vide : mode historique
};

// Tampons de sortie. Les vecteurs ne sont jamais redimensionnés après création.
struct Out {
    std::vector<lsim_device_stats> per_device;
    lsim_sim_stats totals{};
    std::vector<lsim_loop_uplink> ups;
    std::vector<lsim_loop_downlink> dls;
    std::vector<lsim_interval> busy;
    lsim_loop_mac_counters mac_counters{};
    std::vector<lsim_loop_trace_v3> trace;
    std::vector<lsim_channel_terminal_v3> terminals;
    std::size_t up_n = kCountSentinel;
    std::size_t dl_n = kCountSentinel;
    std::size_t busy_n = kCountSentinel;
    std::size_t trace_n = kCountSentinel;
    std::size_t term_n = kCountSentinel;
};

lsim_loop_region eu_region() {
    lsim_loop_region r{};
    for (std::size_t i = 0; i < 6; ++i) r.dr_sf[i] = static_cast<std::uint8_t>(12 - i);
    r.max_dr = 5;
    r.max_tx_power_index = 7;
    r.power_step_tenth_db = 20;
    r.max_eirp_dbm = 16.0;
    for (std::size_t i = 0; i < 16; ++i) r.duty_limit[i] = 1.0;
    return r;
}

// Dispositifs proches (SF12), décalés de 20 s, sans collision sur 60 s de période.
Scenario make_scenario(std::size_t n, std::uint32_t messages, bool adr, std::uint32_t downlink_every) {
    Scenario s;
    for (std::size_t i = 0; i < n; ++i) {
        lsim_end_device d{};
        d.x_m = 80.0 + 40.0 * static_cast<double>(i);
        d.y_m = 0.0;
        d.spreading_factor = 12;
        d.payload_bytes = 10;
        d.tx_power_dbm = 14.0;
        d.start_offset_ns = static_cast<std::int64_t>(i) * 20 * kSec;
        d.period_ns = 60 * kSec;
        d.messages = messages;
        d.duty_cycle = 1.0;
        s.devices.push_back(d);
        lsim_plan_device r{};
        r.freq_hz = 868'100'000;
        r.dr = 0;
        r.rx1_hz = 868'100'000;
        r.tx_power_dbm = 14.0;
        r.rx1_sf = 12;
        r.rx1_bw_hz = 125'000;
        s.radios.push_back(r);
        s.regions.push_back(eu_region());
    }
    s.gateway.base.x_m = 0.0;
    s.gateway.base.y_m = 0.0;
    s.gateway.base.antenna_gain_dbi = 0.0;
    s.gateway.base.rx_sensitivity_offset_db = 0.0;
    s.gateway.sensitivity_model = LSIM_SENSITIVITY_MODEL_NONE;
    s.prop.frequency_hz = 868'100'000;
    s.prop.reference_distance_m = 1.0;
    s.prop.exponent = 2.7;
    s.prop.capture_threshold_db = 6.0;
    s.prop.shadowing_sigma_db = 0.0;
    s.prop.shadowing_seed = 1;
    s.options.protocol.confirmed_uplinks = 0;
    s.options.protocol.downlink_every = downlink_every;
    s.options.protocol.downlink_payload_bytes = 10;
    s.options.protocol.gateway_tx_power_dbm = 14.0;
    s.options.protocol.device_antenna_gain_dbi = 0.0;
    s.options.protocol.device_rx_offset_db = 0.0;
    s.options.adr = adr ? 1 : 0;
    s.options.installation_margin_tenth_db = 0;
    s.options.duty_cycle = 0;
    s.options.duty_cycle_exponent = 0;
    return s;
}

// Capacités généreuses : tous les résultats tiennent.
Out make_out(const Scenario& s, bool trace) {
    std::uint64_t total = 0;
    for (const lsim_end_device& d : s.devices) total += d.messages;
    Out o;
    o.per_device.resize(std::max<std::size_t>(1, s.devices.size()));
    o.ups.resize(static_cast<std::size_t>(total) * 2 + 1);
    o.dls.resize(static_cast<std::size_t>(total) * 2 + 1);
    o.busy.resize(static_cast<std::size_t>(total) * 2 + 1);
    o.trace.resize(trace ? 100'000 : 1);
    o.terminals.resize(std::max<std::size_t>(1, s.devices.size()));
    return o;
}

// Arguments v3 pointant vers `o`. Mode historique si `s.channels` est vide.
lsim_closed_loop_v3_args args_of(Scenario& s, Out& o, bool trace) {
    lsim_closed_loop_v3_args a{};
    a.struct_size = sizeof(lsim_closed_loop_v3_args);
    a.abi_version = 3;
    a.channel_plan = s.channels.empty() ? LSIM_CHANNEL_PLAN_NONE : LSIM_CHANNEL_PLAN_EU868_RP002_1_0_5;
    a.trace_enabled = trace ? 1u : 0u;
    a.trace_element_size = sizeof(lsim_loop_trace_v3);
    a.terminal_element_size = sizeof(lsim_channel_terminal_v3);
    a.devices = s.devices.data();
    a.device_count = s.devices.size();
    a.radios = s.radios.data();
    a.regions = s.regions.data();
    a.gateway = &s.gateway;
    a.prop = &s.prop;
    a.env = nullptr;
    a.options = &s.options;
    a.mac = s.mac.empty() ? nullptr : s.mac.data();
    a.mac_count = s.mac.size();
    a.channels = s.channels.empty() ? nullptr : s.channels.data();
    a.channel_count = s.channels.size();
    a.per_device = o.per_device.data();
    a.totals = &o.totals;
    a.uplinks = o.ups.data();
    a.uplink_capacity = o.ups.size();
    a.uplink_count = &o.up_n;
    a.downlinks = o.dls.data();
    a.downlink_capacity = o.dls.size();
    a.downlink_count = &o.dl_n;
    a.busy = o.busy.data();
    a.busy_capacity = o.busy.size();
    a.busy_count = &o.busy_n;
    a.mac_counters = &o.mac_counters;
    a.trace = trace ? o.trace.data() : nullptr;
    a.trace_capacity = trace ? o.trace.size() : 0;
    a.trace_count = &o.trace_n;
    a.terminals = o.terminals.data();
    a.terminal_capacity = o.terminals.size();
    a.terminal_count = &o.term_n;
    return a;
}

std::int32_t run_v3(Scenario& s, Out& o, bool trace) {
    const lsim_closed_loop_v3_args a = args_of(s, o, trace);
    return lsim_simulate_closed_loop_v3(&a);
}

// Appels v2 (ou gw2 si `gw2`) avec les mêmes entrées, sorties dans `o`.
std::int32_t run_v2(Scenario& s, Out& o, bool gw2) {
    const std::size_t n = s.devices.size();
    const std::size_t cap = o.ups.size();
    if (gw2) {
        return lsim_simulate_closed_loop_gw2(s.devices.data(), n, s.radios.data(), s.regions.data(), &s.gateway,
                                             &s.prop, nullptr, &s.options, s.mac.empty() ? nullptr : s.mac.data(),
                                             s.mac.size(), o.per_device.data(), &o.totals, o.ups.data(), cap,
                                             &o.up_n, o.dls.data(), cap, &o.dl_n, o.busy.data(), cap, &o.busy_n,
                                             &o.mac_counters);
    }
    return lsim_simulate_closed_loop_v2(s.devices.data(), n, s.radios.data(), s.regions.data(), &s.gateway.base,
                                        &s.prop, nullptr, &s.options, s.mac.empty() ? nullptr : s.mac.data(),
                                        s.mac.size(), o.per_device.data(), &o.totals, o.ups.data(), cap, &o.up_n,
                                        o.dls.data(), cap, &o.dl_n, o.busy.data(), cap, &o.busy_n, &o.mac_counters);
}

// Égalité octet à octet des résultats (hors trace). Les champs non écrits restent à zéro.
bool same_results(const Out& a, const Out& b, std::size_t n) {
    return a.up_n == b.up_n && a.dl_n == b.dl_n && a.busy_n == b.busy_n &&
           std::memcmp(a.per_device.data(), b.per_device.data(), n * sizeof(lsim_device_stats)) == 0 &&
           std::memcmp(&a.totals, &b.totals, sizeof(lsim_sim_stats)) == 0 &&
           std::memcmp(a.ups.data(), b.ups.data(), a.up_n * sizeof(lsim_loop_uplink)) == 0 &&
           std::memcmp(a.dls.data(), b.dls.data(), a.dl_n * sizeof(lsim_loop_downlink)) == 0 &&
           std::memcmp(a.busy.data(), b.busy.data(), a.busy_n * sizeof(lsim_interval)) == 0 &&
           std::memcmp(&a.mac_counters, &b.mac_counters, sizeof(lsim_loop_mac_counters)) == 0;
}

bool same_trace(const Out& a, const Out& b) {
    return a.trace_n == b.trace_n &&
           std::memcmp(a.trace.data(), b.trace.data(), a.trace_n * sizeof(lsim_loop_trace_v3)) == 0;
}

bool all_zero(const void* p, std::size_t bytes) {
    const auto* b = static_cast<const unsigned char*>(p);
    for (std::size_t i = 0; i < bytes; ++i) {
        if (b[i] != 0) return false;
    }
    return true;
}

// Aucun octet de sortie n'a été écrit (tampons et statistiques à zéro, compteurs au sentinelle).
bool outputs_untouched(const Out& o) {
    return all_zero(o.per_device.data(), o.per_device.size() * sizeof(lsim_device_stats)) &&
           all_zero(&o.totals, sizeof(o.totals)) && all_zero(o.ups.data(), o.ups.size() * sizeof(lsim_loop_uplink)) &&
           all_zero(o.dls.data(), o.dls.size() * sizeof(lsim_loop_downlink)) &&
           all_zero(o.busy.data(), o.busy.size() * sizeof(lsim_interval)) &&
           all_zero(&o.mac_counters, sizeof(o.mac_counters)) &&
           all_zero(o.trace.data(), o.trace.size() * sizeof(lsim_loop_trace_v3)) &&
           all_zero(o.terminals.data(), o.terminals.size() * sizeof(lsim_channel_terminal_v3));
}

bool counts_untouched(const Out& o) {
    return o.up_n == kCountSentinel && o.dl_n == kCountSentinel && o.busy_n == kCountSentinel &&
           o.trace_n == kCountSentinel && o.term_n == kCountSentinel;
}

// Élément de configuration explicite : chaque canal défini reçoit `dr` (masque DR) donné.
lsim_channel_device_v3 element_masks(std::uint32_t index, const std::vector<std::pair<unsigned, std::uint8_t>>& defined,
                                     const std::vector<unsigned>& enabled, const std::vector<unsigned>& server) {
    lsim_channel_device_v3 e{};
    e.struct_size = sizeof(lsim_channel_device_v3);
    e.abi_version = 3;
    e.device_index = index;
    e.present = LSIM_CHANNEL_PRESENT_YES;
    for (const auto& [ch, mask] : defined) e.dr_mask[ch] = mask;
    for (unsigned ch : enabled) e.enabled[ch / 8] = static_cast<std::uint8_t>(e.enabled[ch / 8] | (1U << (ch % 8)));
    for (unsigned ch : server) {
        e.server_defined[ch / 8] = static_cast<std::uint8_t>(e.server_defined[ch / 8] | (1U << (ch % 8)));
    }
    return e;
}

// Canaux 0..2 définis avec DR0..5 (0x3F), actifs et vus du serveur : valeurs par défaut du moteur.
lsim_channel_device_v3 element_default_values(std::uint32_t index) {
    const std::vector<std::pair<unsigned, std::uint8_t>> defined = {{0, 0x3F}, {1, 0x3F}, {2, 0x3F}};
    return element_masks(index, defined, {0, 1, 2}, {0, 1, 2});
}

// Élément « present = 0 » : tous les champs à zéro, valeurs par défaut du moteur.
lsim_channel_device_v3 element_absent(std::uint32_t index) {
    lsim_channel_device_v3 e{};
    e.struct_size = sizeof(lsim_channel_device_v3);
    e.abi_version = 3;
    e.device_index = index;
    e.present = LSIM_CHANNEL_PRESENT_NO;
    return e;
}

bool enabled_bit(const lsim_channel_terminal_v3& t, unsigned ch) {
    return ((t.enabled[ch / 8] >> (ch % 8)) & 1U) != 0;
}

// ---------------------------------------------------------------------------------------------

void test_argument_errors() {
    Scenario s = make_scenario(2, 3, false, 0);
    Out o = make_out(s, false);
    const lsim_closed_loop_v3_args a = args_of(s, o, false);
    CHECK_EQ(static_cast<int>(lsim_simulate_closed_loop_v3(&a)), 0);
    CHECK_EQ(static_cast<int>(lsim_simulate_closed_loop_v3(nullptr)), LSIM_STATUS_CHANNEL_NULL_POINTER);

    // Pointeur d'arguments désaligné : copie décalée d'un octet.
    alignas(16) unsigned char raw[sizeof(lsim_closed_loop_v3_args) + 16];
    std::memcpy(raw + 1, &a, sizeof(a));
    CHECK_EQ(static_cast<int>(lsim_simulate_closed_loop_v3(reinterpret_cast<const lsim_closed_loop_v3_args*>(raw + 1))),
             LSIM_STATUS_CHANNEL_MISALIGNED);

    lsim_closed_loop_v3_args b = a;
    b.struct_size -= 1;
    CHECK_EQ(static_cast<int>(lsim_simulate_closed_loop_v3(&b)), LSIM_STATUS_CHANNEL_ARGS_SIZE);
    b = a;
    b.abi_version = 2;
    CHECK_EQ(static_cast<int>(lsim_simulate_closed_loop_v3(&b)), LSIM_STATUS_CHANNEL_ABI_VERSION);
    b = a;
    b.abi_version = 4;
    CHECK_EQ(static_cast<int>(lsim_simulate_closed_loop_v3(&b)), LSIM_STATUS_CHANNEL_ABI_VERSION);
    b = a;
    b.trace_element_size = 39;
    CHECK_EQ(static_cast<int>(lsim_simulate_closed_loop_v3(&b)), LSIM_STATUS_CHANNEL_ELEMENT_SIZE);
    b = a;
    b.terminal_element_size = 111;
    CHECK_EQ(static_cast<int>(lsim_simulate_closed_loop_v3(&b)), LSIM_STATUS_CHANNEL_ELEMENT_SIZE);
    b = a;
    b.reserved1 = 1;
    CHECK_EQ(static_cast<int>(lsim_simulate_closed_loop_v3(&b)), LSIM_STATUS_CHANNEL_RESERVED_NONZERO);
    b = a;
    b.channel_plan = 2;
    CHECK_EQ(static_cast<int>(lsim_simulate_closed_loop_v3(&b)), LSIM_STATUS_CHANNEL_PLAN);
    b = a;
    b.trace_enabled = 2;
    CHECK_EQ(static_cast<int>(lsim_simulate_closed_loop_v3(&b)), LSIM_STATUS_CHANNEL_TRACE_MODE);
    b = a;
    b.device_count = 10'001;
    CHECK_EQ(static_cast<int>(lsim_simulate_closed_loop_v3(&b)), kSimTooManyDevices);
    b = a;
    b.gateway = nullptr;
    CHECK_EQ(static_cast<int>(lsim_simulate_closed_loop_v3(&b)), LSIM_STATUS_CHANNEL_NULL_POINTER);
    // Erreurs d'argument : rien n'est écrit (la sortie de référence ci-dessus a été remplie, donc on
    // vérifie les compteurs sur un tampon neuf).
    Out fresh = make_out(s, false);
    lsim_closed_loop_v3_args c = args_of(s, fresh, false);
    c.trace_element_size = 39;
    CHECK_EQ(static_cast<int>(lsim_simulate_closed_loop_v3(&c)), LSIM_STATUS_CHANNEL_ELEMENT_SIZE);
    CHECK_TRUE(outputs_untouched(fresh));
    CHECK_TRUE(counts_untouched(fresh));
}

void test_mode_and_element_errors() {
    Scenario s = make_scenario(2, 2, false, 0);
    Out o = make_out(s, false);
    lsim_closed_loop_v3_args a = args_of(s, o, false);
    // Plan EU868 sans éléments : mode incohérent.
    a.channel_plan = LSIM_CHANNEL_PLAN_EU868_RP002_1_0_5;
    CHECK_EQ(static_cast<int>(lsim_simulate_closed_loop_v3(&a)), LSIM_STATUS_CHANNEL_MODE);

    // Éléments sans plan.
    s.channels = {element_absent(0), element_absent(1)};
    o = make_out(s, false);
    a = args_of(s, o, false);
    a.channel_plan = LSIM_CHANNEL_PLAN_NONE;
    CHECK_EQ(static_cast<int>(lsim_simulate_closed_loop_v3(&a)), LSIM_STATUS_CHANNEL_MODE);

    // Nombre d'éléments différent du nombre de dispositifs.
    a = args_of(s, o, false);
    a.channel_count = 1;
    CHECK_EQ(static_cast<int>(lsim_simulate_closed_loop_v3(&a)), LSIM_STATUS_CHANNEL_MODE);

    // Index hors plage, doublon.
    s.channels = {element_absent(0), element_absent(5)};
    a = args_of(s, o, false);
    CHECK_EQ(static_cast<int>(lsim_simulate_closed_loop_v3(&a)), LSIM_STATUS_CHANNEL_DEVICE_INDEX);
    s.channels = {element_absent(0), element_absent(0)};
    a = args_of(s, o, false);
    CHECK_EQ(static_cast<int>(lsim_simulate_closed_loop_v3(&a)), LSIM_STATUS_CHANNEL_DEVICE_INDEX);

    // present invalide ; champs non vides avec present = 0 ; réservé non nul.
    s.channels = {element_absent(0), element_absent(1)};
    s.channels[0].present = 2;
    a = args_of(s, o, false);
    CHECK_EQ(static_cast<int>(lsim_simulate_closed_loop_v3(&a)), LSIM_STATUS_CHANNEL_PRESENT_FLAG);
    s.channels[0] = element_absent(0);
    s.channels[0].enabled[0] = 1;
    a = args_of(s, o, false);
    CHECK_EQ(static_cast<int>(lsim_simulate_closed_loop_v3(&a)), LSIM_STATUS_CHANNEL_FIELDS_WITHOUT_PRESENT);
    s.channels[0] = element_absent(0);
    s.channels[0].reserved[3] = 1;
    a = args_of(s, o, false);
    CHECK_EQ(static_cast<int>(lsim_simulate_closed_loop_v3(&a)), LSIM_STATUS_CHANNEL_RESERVED_NONZERO);

    // Canal actif non défini ; canal 16 ; DR au-delà de max_dr (5) ; vue serveur vide ; aucun actif.
    s.channels = {element_masks(0, {{0, 0x03}, {1, 0x03}}, {0, 2}, {0}), element_absent(1)};
    a = args_of(s, o, false);
    CHECK_EQ(static_cast<int>(lsim_simulate_closed_loop_v3(&a)), LSIM_STATUS_CHANNEL_ENABLED_UNDEFINED);
    s.channels = {element_masks(0, {{0, 0x03}, {16, 0x03}}, {0}, {0}), element_absent(1)};
    a = args_of(s, o, false);
    CHECK_EQ(static_cast<int>(lsim_simulate_closed_loop_v3(&a)), LSIM_STATUS_CHANNEL_INDEX_UNSUPPORTED);
    s.channels = {element_masks(0, {{0, 0x40}}, {0}, {0}), element_absent(1)};  // DR6 avec max_dr = 5
    a = args_of(s, o, false);
    CHECK_EQ(static_cast<int>(lsim_simulate_closed_loop_v3(&a)), LSIM_STATUS_CHANNEL_DR_MASK_INVALID);
    s.channels = {element_masks(0, {{0, 0x03}}, {0}, {}), element_absent(1)};  // vue serveur vide
    a = args_of(s, o, false);
    CHECK_EQ(static_cast<int>(lsim_simulate_closed_loop_v3(&a)), LSIM_STATUS_CHANNEL_SERVER_VIEW_EMPTY);
    s.channels = {element_masks(0, {{0, 0x03}}, {}, {0}), element_absent(1)};  // aucun actif
    a = args_of(s, o, false);
    CHECK_EQ(static_cast<int>(lsim_simulate_closed_loop_v3(&a)), LSIM_STATUS_CHANNEL_ENABLED_EMPTY);
    CHECK_TRUE(outputs_untouched(o));
    CHECK_TRUE(counts_untouched(o));
}

void test_null_and_optional_buffers() {
    Scenario s = make_scenario(2, 2, false, 0);
    Out o = make_out(s, false);
    lsim_closed_loop_v3_args a = args_of(s, o, false);

    // uplinks, downlinks, busy : NULL refusé même à capacité 0.
    a.uplinks = nullptr;
    a.uplink_capacity = 0;
    CHECK_EQ(static_cast<int>(lsim_simulate_closed_loop_v3(&a)), LSIM_STATUS_CHANNEL_NULL_POINTER);
    a = args_of(s, o, false);
    a.downlinks = nullptr;
    a.downlink_capacity = 0;
    CHECK_EQ(static_cast<int>(lsim_simulate_closed_loop_v3(&a)), LSIM_STATUS_CHANNEL_NULL_POINTER);
    a = args_of(s, o, false);
    a.busy = nullptr;
    a.busy_capacity = 0;
    CHECK_EQ(static_cast<int>(lsim_simulate_closed_loop_v3(&a)), LSIM_STATUS_CHANNEL_NULL_POINTER);
    // Trace activée : NULL refusé même à capacité 0.
    a = args_of(s, o, true);
    a.trace = nullptr;
    a.trace_capacity = 0;
    CHECK_EQ(static_cast<int>(lsim_simulate_closed_loop_v3(&a)), LSIM_STATUS_CHANNEL_NULL_POINTER);
    // Terminaux : NULL avec capacité positive refusé.
    a = args_of(s, o, false);
    a.terminals = nullptr;
    CHECK_EQ(static_cast<int>(lsim_simulate_closed_loop_v3(&a)), LSIM_STATUS_CHANNEL_NULL_POINTER);
    // Calendrier MAC NULL avec mac_count > 0.
    s.mac = {lsim_loop_mac{0, 1, 0, 1}};
    o = make_out(s, false);
    a = args_of(s, o, false);
    a.mac = nullptr;
    CHECK_EQ(static_cast<int>(lsim_simulate_closed_loop_v3(&a)), LSIM_STATUS_CHANNEL_NULL_POINTER);
    s.mac.clear();
    CHECK_TRUE(outputs_untouched(o));
    CHECK_TRUE(counts_untouched(o));

    // Buffers optionnels : mac_counters NULL ; trace désactivée sans buffer.
    o = make_out(s, false);
    a = args_of(s, o, false);
    a.mac_counters = nullptr;
    a.trace = nullptr;
    a.trace_capacity = 0;
    CHECK_EQ(static_cast<int>(lsim_simulate_closed_loop_v3(&a)), 0);
    CHECK_TRUE(o.up_n <= 4);
    CHECK_TRUE(o.totals.sent > 0);

    // Terminaux NULL à capacité 0 avec dispositifs : buffer non demandé, donc erreur de capacité ;
    // seul le compteur terminal est écrit.
    o = make_out(s, false);
    a = args_of(s, o, false);
    a.terminals = nullptr;
    a.terminal_capacity = 0;
    CHECK_EQ(static_cast<int>(lsim_simulate_closed_loop_v3(&a)), LSIM_STATUS_CHANNEL_TERMINAL_BUFFER_TOO_SMALL);
    CHECK_EQ(o.term_n, s.devices.size());
    CHECK_TRUE(o.up_n <= 4);  // compteur réel écrit même sur erreur de capacité (2 dispositifs x 2 messages)
}

void test_alias_and_alignment() {
    Scenario s = make_scenario(2, 2, false, 0);
    Out o = make_out(s, false);
    lsim_closed_loop_v3_args a = args_of(s, o, false);
    // Sorties qui se chevauchent : uplinks et downlinks à la même adresse.
    a.downlinks = reinterpret_cast<lsim_loop_downlink*>(o.ups.data());
    a.downlink_capacity = 1;
    CHECK_EQ(static_cast<int>(lsim_simulate_closed_loop_v3(&a)), LSIM_STATUS_CHANNEL_BUFFERS_ALIASED);
    // Compteur désaligné (size_t à adresse impaire).
    a = args_of(s, o, false);
    a.uplink_count = reinterpret_cast<std::size_t*>(reinterpret_cast<unsigned char*>(&o.up_n) + 1);
    CHECK_EQ(static_cast<int>(lsim_simulate_closed_loop_v3(&a)), LSIM_STATUS_CHANNEL_MISALIGNED);
    CHECK_TRUE(outputs_untouched(o));
    CHECK_TRUE(counts_untouched(o));
}

// Capacités insuffisantes : seuls les compteurs requis sont écrits ; buffers et statistiques non.
void test_capacity_errors_write_counts_only() {
    Scenario s = make_scenario(2, 3, false, 1);
    Out base = make_out(s, true);
    CHECK_EQ(static_cast<int>(run_v3(s, base, true)), 0);
    const std::size_t up = base.up_n;
    const std::size_t dl = base.dl_n;
    const std::size_t busy = base.busy_n;
    const std::size_t tr = base.trace_n;
    CHECK_TRUE(up > 1 && dl > 0 && tr > 1);

    // Uplinks insuffisants.
    Out o = make_out(s, true);
    lsim_closed_loop_v3_args a = args_of(s, o, true);
    a.uplink_capacity = up - 1;
    CHECK_EQ(static_cast<int>(lsim_simulate_closed_loop_v3(&a)), kSimUplinkTooSmall);
    CHECK_EQ(o.up_n, up);
    CHECK_EQ(o.dl_n, dl);
    CHECK_EQ(o.busy_n, busy);
    CHECK_EQ(o.trace_n, tr);
    CHECK_EQ(o.term_n, s.devices.size());
    CHECK_TRUE(all_zero(o.per_device.data(), o.per_device.size() * sizeof(lsim_device_stats)));
    CHECK_TRUE(all_zero(&o.totals, sizeof(o.totals)));
    CHECK_TRUE(all_zero(&o.mac_counters, sizeof(o.mac_counters)));
    CHECK_TRUE(all_zero(o.ups.data(), o.ups.size() * sizeof(lsim_loop_uplink)));
    CHECK_TRUE(all_zero(o.terminals.data(), o.terminals.size() * sizeof(lsim_channel_terminal_v3)));
    CHECK_TRUE(all_zero(o.trace.data(), o.trace.size() * sizeof(lsim_loop_trace_v3)));

    // Descentes insuffisantes : PLAN + 4 (code historique).
    o = make_out(s, true);
    a = args_of(s, o, true);
    a.downlink_capacity = dl - 1;
    CHECK_EQ(static_cast<int>(lsim_simulate_closed_loop_v3(&a)), kPlanCapacity);
    CHECK_EQ(o.dl_n, dl);
    CHECK_EQ(o.up_n, up);
    CHECK_TRUE(o.totals.sent == 0);
    CHECK_TRUE(all_zero(o.dls.data(), o.dls.size() * sizeof(lsim_loop_downlink)));

    // Occupation passerelle insuffisante : même code.
    if (busy > 0) {
        o = make_out(s, true);
        a = args_of(s, o, true);
        a.busy_capacity = busy - 1;
        CHECK_EQ(static_cast<int>(lsim_simulate_closed_loop_v3(&a)), kPlanCapacity);
        CHECK_EQ(o.busy_n, busy);
    }

    // Trace insuffisante.
    o = make_out(s, true);
    a = args_of(s, o, true);
    a.trace_capacity = tr - 1;
    CHECK_EQ(static_cast<int>(lsim_simulate_closed_loop_v3(&a)), LSIM_STATUS_CHANNEL_TRACE_BUFFER_TOO_SMALL);
    CHECK_EQ(o.trace_n, tr);
    CHECK_EQ(o.up_n, up);
    CHECK_TRUE(all_zero(o.trace.data(), o.trace.size() * sizeof(lsim_loop_trace_v3)));

    // Terminaux insuffisants.
    o = make_out(s, true);
    a = args_of(s, o, true);
    a.terminal_capacity = s.devices.size() - 1;
    CHECK_EQ(static_cast<int>(lsim_simulate_closed_loop_v3(&a)), LSIM_STATUS_CHANNEL_TERMINAL_BUFFER_TOO_SMALL);
    CHECK_EQ(o.term_n, s.devices.size());
    CHECK_EQ(o.up_n, up);
    CHECK_TRUE(all_zero(o.terminals.data(), o.terminals.size() * sizeof(lsim_channel_terminal_v3)));
}

// Erreurs communes à v2 et v3 : mêmes codes (plan et moteur), sans écriture côté v3.
void test_common_errors_match_v2() {
    // Modèle de sensibilité inconnu : gw2 le refuse ; v3 doit donner le même code.
    {
        Scenario s = make_scenario(1, 1, false, 0);
        s.gateway.sensitivity_model = 7;
        Out v2 = make_out(s, false);
        const std::int32_t expected = run_v2(s, v2, true);
        CHECK_EQ(expected, kSimInvalidInput);
        Out o = make_out(s, false);
        CHECK_EQ(static_cast<int>(run_v3(s, o, false)), kSimInvalidInput);
        CHECK_TRUE(outputs_untouched(o));
        CHECK_TRUE(counts_untouched(o));
    }
    // Charge utile de descente hors plage : erreur de planification identique.
    {
        Scenario s = make_scenario(1, 1, false, 1);
        s.options.protocol.downlink_payload_bytes = 243;
        Out v2 = make_out(s, false);
        const std::int32_t expected = run_v2(s, v2, false);
        CHECK_TRUE(expected != 0);
        Out o = make_out(s, false);
        CHECK_EQ(static_cast<int>(run_v3(s, o, false)), static_cast<int>(expected));
        CHECK_TRUE(outputs_untouched(o));
        CHECK_TRUE(counts_untouched(o));
    }
    // Radio sans débit de plan : même code que v2 (planification des descentes).
    {
        Scenario s = make_scenario(1, 1, false, 1);
        s.radios[0].freq_hz = 0;
        Out v2 = make_out(s, false);
        const std::int32_t expected = run_v2(s, v2, false);
        Out o = make_out(s, false);
        CHECK_EQ(static_cast<int>(run_v3(s, o, false)), static_cast<int>(expected));
        if (expected != 0) CHECK_TRUE(outputs_untouched(o));
    }
}

// Mode historique v3 = v2 (sans configuration) et gw2 (sensibilité absolue).
void test_historical_parity_with_v2_and_gw2() {
    for (bool adr : {false, true}) {
        for (bool with_mac : {false, true}) {
            Scenario s = make_scenario(3, 4, adr, 1);
            if (with_mac) s.mac = {lsim_loop_mac{0, 1, 0, 1}, lsim_loop_mac{1, 2, 0, 2}};
            Out v2 = make_out(s, false);
            CHECK_EQ(static_cast<int>(run_v2(s, v2, false)), 0);
            Out v3 = make_out(s, false);
            CHECK_EQ(static_cast<int>(run_v3(s, v3, false)), 0);
            CHECK_TRUE(same_results(v2, v3, s.devices.size()));
            // La trace activée ne change pas les résultats.
            Out v3t = make_out(s, true);
            CHECK_EQ(static_cast<int>(run_v3(s, v3t, true)), 0);
            CHECK_TRUE(same_results(v3, v3t, s.devices.size()));
            CHECK_TRUE(v3t.trace_n > 0);
        }
    }
    // gw2 sans sensibilité absolue : égal à v2.
    {
        Scenario s = make_scenario(2, 3, true, 1);
        Out v2 = make_out(s, false);
        CHECK_EQ(static_cast<int>(run_v2(s, v2, false)), 0);
        Out v3 = make_out(s, false);
        CHECK_EQ(static_cast<int>(run_v3(s, v3, false)), 0);
        CHECK_TRUE(same_results(v2, v3, s.devices.size()));
    }
    // gw2 avec sensibilité absolue : égal à gw2.
    {
        Scenario s = make_scenario(2, 3, true, 1);
        s.gateway.sensitivity_model = LSIM_SENSITIVITY_MODEL_ABSOLUTE_PER_SF_V2;
        s.gateway.present = 1u << (0 * 8 + 12 - 5);  // SF12 / 125 kHz
        s.gateway.sensitivity_dbm[0][7] = -137.0;
        Out g2 = make_out(s, false);
        CHECK_EQ(static_cast<int>(run_v2(s, g2, true)), 0);
        Out v3 = make_out(s, false);
        CHECK_EQ(static_cast<int>(run_v3(s, v3, false)), 0);
        CHECK_TRUE(same_results(g2, v3, s.devices.size()));
    }
}

// Configuration EU868 explicite avec les valeurs par défaut : égale au mode historique.
void test_explicit_defaults_equal_historical() {
    for (bool adr : {false, true}) {
        Scenario hist = make_scenario(2, 4, adr, 1);
        hist.mac = {lsim_loop_mac{0, 1, 0, 1}};
        Out h = make_out(hist, true);
        CHECK_EQ(static_cast<int>(run_v3(hist, h, true)), 0);

        // present = 0 : valeurs par défaut du moteur.
        Scenario absent = hist;
        absent.channels = {element_absent(0), element_absent(1)};
        Out d = make_out(absent, true);
        CHECK_EQ(static_cast<int>(run_v3(absent, d, true)), 0);
        CHECK_TRUE(same_results(h, d, hist.devices.size()));
        CHECK_TRUE(same_trace(h, d));

        // present = 1 avec exactement les valeurs par défaut.
        Scenario explicit_default = hist;
        explicit_default.channels = {element_default_values(0), element_default_values(1)};
        Out e = make_out(explicit_default, true);
        CHECK_EQ(static_cast<int>(run_v3(explicit_default, e, true)), 0);
        CHECK_TRUE(same_results(h, e, hist.devices.size()));
        CHECK_TRUE(same_trace(h, e));
        // Terminal : états initiaux identiques aux valeurs par défaut.
        CHECK_EQ(static_cast<int>(e.terminals[0].dr_mask[0]), 0x3F);
        CHECK_TRUE(enabled_bit(e.terminals[0], 0) && enabled_bit(e.terminals[0], 2) &&
                   !enabled_bit(e.terminals[0], 3));
    }
}

// Trois terminaux aux configurations différentes ; état terminal distinct de la vue serveur.
void test_terminal_states_and_server_view() {
    Scenario s = make_scenario(3, 2, false, 0);
    // Dispositif 0 : canaux 0..3 définis, actifs 0..2 ; vue serveur 0..2 et 5 (5 non défini côté terminal).
    // Dispositif 1 : canaux 0..5 définis, actifs 3..5, vue serveur 3..5.
    // Dispositif 2 : valeurs par défaut (present = 0).
    s.channels = {element_masks(0, {{0, 0x3F}, {1, 0x3F}, {2, 0x3F}, {3, 0x3F}}, {0, 1, 2}, {0, 1, 2, 5}),
                  element_masks(1, {{0, 0x3F}, {1, 0x3F}, {2, 0x3F}, {3, 0x3F}, {4, 0x3F}, {5, 0x3F}}, {3, 4, 5},
                                {3, 4, 5}),
                  element_absent(2)};
    Out o = make_out(s, false);
    CHECK_EQ(static_cast<int>(run_v3(s, o, false)), 0);
    CHECK_EQ(o.term_n, static_cast<std::size_t>(3));
    const lsim_channel_terminal_v3& t0 = o.terminals[0];
    const lsim_channel_terminal_v3& t1 = o.terminals[1];
    const lsim_channel_terminal_v3& t2 = o.terminals[2];
    CHECK_EQ(static_cast<int>(t0.device_index), 0);
    CHECK_EQ(static_cast<int>(t1.device_index), 1);
    CHECK_EQ(static_cast<int>(t2.device_index), 2);
    CHECK_EQ(static_cast<int>(t0.dr_mask[3]), 0x3F);
    CHECK_EQ(static_cast<int>(t0.dr_mask[5]), 0);  // vue serveur seule : non défini côté terminal
    CHECK_TRUE(enabled_bit(t0, 0) && enabled_bit(t0, 2) && !enabled_bit(t0, 3));
    CHECK_TRUE(!enabled_bit(t0, 5));
    CHECK_TRUE(enabled_bit(t1, 3) && enabled_bit(t1, 5) && !enabled_bit(t1, 0));
    CHECK_EQ(static_cast<int>(t1.dr_mask[4]), 0x3F);
    CHECK_EQ(static_cast<int>(t2.dr_mask[0]), 0x3F);
    CHECK_TRUE(enabled_bit(t2, 0) && enabled_bit(t2, 1) && enabled_bit(t2, 2) && !enabled_bit(t2, 3));
    CHECK_EQ(static_cast<int>(t2.dr_mask[3]), 0);
    CHECK_EQ(static_cast<int>(t0.dr_mask[79]), 0);
    // Pas de bits de réservé écrits.
    CHECK_EQ(static_cast<int>(t0.reserved0), 0);
    for (std::uint8_t r : t0.reserved1) CHECK_EQ(static_cast<int>(r), 0);
}

// Trace : ordre temporel, sentinelles, valeurs par type, présence des sept types sur un scénario ADR.
void test_trace_events_and_sentinels() {
    // ADR : première LinkADRReq après 97 uplinks (ADR_ACK_LIMIT 64 + ADR_ACK_DELAY 32 + 1).
    Scenario s = make_scenario(2, 130, true, 1);
    s.mac = {lsim_loop_mac{0, 1, 0, 1}, lsim_loop_mac{1, 1, 0, 1}};
    Out o = make_out(s, true);
    CHECK_EQ(static_cast<int>(run_v3(s, o, true)), 0);
    CHECK_TRUE(o.trace_n > 0);
    std::size_t kinds[7] = {0, 0, 0, 0, 0, 0, 0};
    std::int64_t prev = 0;
    for (std::size_t i = 0; i < o.trace_n; ++i) {
        const lsim_loop_trace_v3& e = o.trace[i];
        CHECK_TRUE(e.t_ns >= prev);
        prev = e.t_ns;
        CHECK_TRUE(e.kind <= LSIM_TRACE_KIND_APPLY);
        CHECK_TRUE(e.origin <= LSIM_TRACE_ORIGIN_RADIO);
        ++kinds[e.kind];
        // Sentinelle de descente : indice pour LinkAdrReq, Downlink, Apply ; 0xFFFFFFFF sinon.
        const bool indexed = e.kind == LSIM_TRACE_KIND_LINK_ADR_REQ || e.kind == LSIM_TRACE_KIND_DOWNLINK ||
                             e.kind == LSIM_TRACE_KIND_APPLY;
        if (!indexed) CHECK_EQ(static_cast<std::uint32_t>(e.downlink), LSIM_TRACE_NO_INDEX);
        // Sentinelle de statut : bits pour LinkAdrAns et Apply ; 0xFF sinon.
        const bool status_kind = e.kind == LSIM_TRACE_KIND_LINK_ADR_ANS || e.kind == LSIM_TRACE_KIND_APPLY;
        if (!status_kind) CHECK_EQ(static_cast<int>(e.status), static_cast<int>(LSIM_TRACE_STATUS_NONE));
        // loss : non nulle seulement pour Downlink.
        if (e.kind != LSIM_TRACE_KIND_DOWNLINK) CHECK_EQ(static_cast<int>(e.loss), 0);
        if (e.kind == LSIM_TRACE_KIND_UPLINK) {
            CHECK_EQ(static_cast<int>(e.origin), static_cast<int>(LSIM_TRACE_ORIGIN_RADIO));
            CHECK_EQ(static_cast<int>(e.value), 0);
        }
        if (e.kind == LSIM_TRACE_KIND_LINK_ADR_ANS) {
            CHECK_TRUE(e.status <= 7);
            CHECK_EQ(static_cast<int>(e.flag), e.status == 0x07 ? 1 : 0);
            CHECK_EQ(static_cast<int>(e.value), 0);
        }
        if (e.kind == LSIM_TRACE_KIND_APPLY) {
            CHECK_EQ(static_cast<int>(e.flag), e.status == 0x07 ? 1 : 0);
            CHECK_EQ(static_cast<int>(e.value), 0);
        }
        if (e.kind == LSIM_TRACE_KIND_LINK_ADR_REQ) {
            CHECK_EQ(static_cast<int>(e.flag), 0);
            CHECK_EQ(static_cast<int>(e.value), 0);
        }
        if (e.kind == LSIM_TRACE_KIND_DOWNLINK) {
            CHECK_TRUE(e.value <= 0x1F);
            CHECK_EQ(static_cast<int>(e.flag), e.loss == 0 ? 1 : 0);
            CHECK_TRUE(e.loss <= LSIM_TRACE_LOSS_BELOW_SENSITIVITY);
        }
        if (e.kind == LSIM_TRACE_KIND_EXCLUSION) {
            if (e.target == LSIM_TRACE_TARGET_DATA_RATE) CHECK_TRUE(e.value <= 15);
            if (e.target == LSIM_TRACE_TARGET_POWER) CHECK_TRUE(e.value <= 14);
            if (e.target == LSIM_TRACE_TARGET_CHANNEL) CHECK_TRUE(e.value <= 15);
        }
        if (e.kind != LSIM_TRACE_KIND_EXCLUSION && e.kind != LSIM_TRACE_KIND_DOWNLINK) {
            CHECK_EQ(static_cast<int>(e.value), 0);
        }
    }
    CHECK_TRUE(kinds[LSIM_TRACE_KIND_UPLINK] > 0);
    CHECK_TRUE(kinds[LSIM_TRACE_KIND_DOWNLINK] > 0);
    CHECK_TRUE(kinds[LSIM_TRACE_KIND_ADR_DECISION] > 0);
    CHECK_TRUE(kinds[LSIM_TRACE_KIND_LINK_ADR_REQ] > 0);
    CHECK_TRUE(kinds[LSIM_TRACE_KIND_APPLY] > 0);
    CHECK_TRUE(kinds[LSIM_TRACE_KIND_LINK_ADR_ANS] > 0);
}

// ADR réussi : LinkADRReq planifiée, appliquée, acquittée ; le terminal change de débit.
void test_adr_success_applies_to_terminal() {
    Scenario s = make_scenario(1, 130, true, 1);
    Out o = make_out(s, true);
    CHECK_EQ(static_cast<int>(run_v3(s, o, true)), 0);
    bool applied = false;
    bool accepted = false;
    for (std::size_t i = 0; i < o.trace_n; ++i) {
        const lsim_loop_trace_v3& e = o.trace[i];
        if (e.kind == LSIM_TRACE_KIND_APPLY && e.flag != 0) applied = true;
        if (e.kind == LSIM_TRACE_KIND_LINK_ADR_ANS && e.status == 0x07) accepted = true;
    }
    CHECK_TRUE(applied);
    CHECK_TRUE(accepted);
    CHECK_TRUE(o.terminals[0].dr > 0);
    // Résultat de référence : le même scénario en mode historique donne le même nombre d'uplinks.
    Out h = make_out(s, false);
    CHECK_EQ(static_cast<int>(run_v3(s, h, false)), 0);
    CHECK_TRUE(same_results(h, o, s.devices.size()));
}

// ADR refusé : le terminal n'accepte que DR0 et DR1 ; la requête est refusée, une exclusion est créée
// et le débit du terminal ne dépasse pas DR1.
void test_adr_refusal_creates_exclusion() {
    Scenario s = make_scenario(1, 130, true, 1);
    s.channels = {element_masks(0, {{0, 0x03}, {1, 0x03}, {2, 0x03}}, {0, 1, 2}, {0, 1, 2})};
    Out o = make_out(s, true);
    CHECK_EQ(static_cast<int>(run_v3(s, o, true)), 0);
    std::size_t exclusions_dr = 0;
    std::size_t refused_answers = 0;
    for (std::size_t i = 0; i < o.trace_n; ++i) {
        const lsim_loop_trace_v3& e = o.trace[i];
        if (e.kind == LSIM_TRACE_KIND_EXCLUSION && e.target == LSIM_TRACE_TARGET_DATA_RATE) {
            ++exclusions_dr;
            CHECK_TRUE(e.value <= 15);
        }
        if (e.kind == LSIM_TRACE_KIND_LINK_ADR_ANS && (e.status & 0x02) == 0) ++refused_answers;
        // Un Apply acquitté ne porte que les débits admis par le terminal (DR0 ou DR1).
        if (e.kind == LSIM_TRACE_KIND_APPLY && e.flag != 0) CHECK_TRUE(e.dr <= 1);
    }
    CHECK_TRUE(exclusions_dr > 0);
    CHECK_TRUE(refused_answers > 0);
    CHECK_TRUE(o.terminals[0].dr <= 1);
    CHECK_EQ(static_cast<int>(o.terminals[0].dr_mask[0]), 0x03);
}

// Invariants de la file MAC : enqueued = dispatched + expired + pending_at_end ; dispatched = delivered +
// dispatch_lost.
void test_mac_counter_invariants() {
    Scenario s = make_scenario(2, 20, true, 1);
    s.mac = {lsim_loop_mac{0, 1, 0, 1}, lsim_loop_mac{0, 2, 0, 2}, lsim_loop_mac{1, 1, 4, 4}};
    Out o = make_out(s, false);
    CHECK_EQ(static_cast<int>(run_v3(s, o, false)), 0);
    const lsim_loop_mac_counters& m = o.mac_counters;
    CHECK_EQ(m.enqueued, m.dispatched + m.expired + m.pending_at_end);
    CHECK_EQ(m.dispatched, m.delivered + m.dispatch_lost);
}

// Erreur de validation d'élément de configuration : aucune écriture, même partielle.
void test_validation_error_writes_nothing() {
    Scenario s = make_scenario(2, 3, true, 1);
    s.channels = {element_default_values(0), element_masks(1, {{0, 0x01}}, {5}, {0})};  // canal actif 5 non défini
    Out o = make_out(s, true);
    lsim_closed_loop_v3_args a = args_of(s, o, true);
    CHECK_EQ(static_cast<int>(lsim_simulate_closed_loop_v3(&a)), LSIM_STATUS_CHANNEL_ENABLED_UNDEFINED);
    CHECK_TRUE(outputs_untouched(o));
    CHECK_TRUE(counts_untouched(o));
}

// ---------------------------------------------------------------------------------------------
// Vérifications croisées de la trace (étape 6.3). Chaque propriété est celle du contrat gelé
// (docs/CLOSED_LOOP_ABI_V3.md §6) et est comparée aux tableaux de sortie ; aucune valeur n'est
// déduite de la trace elle-même.

struct TraceCoverage {
    bool kind[7] = {false, false, false, false, false, false, false};
    bool target[4] = {false, false, false, false};
    bool loss[4] = {false, false, false, false};
    bool apply_accepted = false;
    bool apply_refused = false;
};

// Réponse LinkADRAns de cette émission pour ce dispositif (nullptr si absente).
const lsim_loop_trace_v3* find_ans(const Out& o, std::uint32_t device, std::uint32_t uplink) {
    for (std::size_t i = 0; i < o.trace_n; ++i) {
        const lsim_loop_trace_v3& e = o.trace[i];
        if (e.kind == LSIM_TRACE_KIND_LINK_ADR_ANS && e.device == device && e.uplink == uplink) return &e;
    }
    return nullptr;
}

// Contrôle de chaque événement : type, origine, sentinelles, flags, bornes et renvois vers les sorties.
void check_trace_events(const Out& o, TraceCoverage& c) {
    std::int64_t prev = 0;
    for (std::size_t i = 0; i < o.trace_n; ++i) {
        const lsim_loop_trace_v3& e = o.trace[i];
        CHECK_TRUE(e.t_ns >= prev);  // ordre temporel non décroissant
        prev = e.t_ns;
        CHECK_TRUE(e.kind <= LSIM_TRACE_KIND_APPLY);
        if (e.kind > LSIM_TRACE_KIND_APPLY) continue;
        c.kind[e.kind] = true;
        const bool has_downlink = e.kind == LSIM_TRACE_KIND_LINK_ADR_REQ || e.kind == LSIM_TRACE_KIND_DOWNLINK ||
                                  e.kind == LSIM_TRACE_KIND_APPLY;
        const bool has_status = e.kind == LSIM_TRACE_KIND_LINK_ADR_ANS || e.kind == LSIM_TRACE_KIND_APPLY;
        // Sentinelles : indice de descente et statut, 0xFFFFFFFF et 0xFF hors de leur type.
        if (!has_downlink) CHECK_EQ(static_cast<std::uint32_t>(e.downlink), LSIM_TRACE_NO_INDEX);
        if (!has_status) CHECK_EQ(static_cast<int>(e.status), static_cast<int>(LSIM_TRACE_STATUS_NONE));
        // loss : seulement pour Downlink.
        if (e.kind != LSIM_TRACE_KIND_DOWNLINK) CHECK_EQ(static_cast<int>(e.loss), static_cast<int>(LSIM_TRACE_LOSS_NONE));

        switch (e.kind) {
        case LSIM_TRACE_KIND_UPLINK:
            CHECK_TRUE(e.uplink < o.up_n);
            CHECK_EQ(static_cast<int>(e.origin), static_cast<int>(LSIM_TRACE_ORIGIN_RADIO));
            // flag = uplink reçu (contrat §6.2).
            CHECK_EQ(static_cast<int>(e.flag), o.ups[e.uplink].outcome == 2 ? 1 : 0);
            CHECK_EQ(static_cast<int>(e.value), 0);
            break;
        case LSIM_TRACE_KIND_LINK_ADR_ANS:
            CHECK_TRUE(e.uplink < o.up_n);
            CHECK_EQ(static_cast<int>(e.origin), static_cast<int>(LSIM_TRACE_ORIGIN_NORMATIVE));
            CHECK_TRUE(e.status <= 7);
            CHECK_EQ(static_cast<int>(e.flag), e.status == 0x07 ? 1 : 0);  // flag = acceptation complète
            CHECK_EQ(static_cast<int>(e.value), 0);
            break;
        case LSIM_TRACE_KIND_EXCLUSION: {
            CHECK_EQ(static_cast<int>(e.origin), static_cast<int>(LSIM_TRACE_ORIGIN_SIMULATOR_POLICY));
            CHECK_TRUE(e.target <= LSIM_TRACE_TARGET_MASK);
            c.target[e.target] = true;
            if (e.target == LSIM_TRACE_TARGET_DATA_RATE) CHECK_TRUE(e.value <= 15);
            if (e.target == LSIM_TRACE_TARGET_POWER) CHECK_TRUE(e.value <= 14);
            // Action : Created ou Renewed (posée par une réponse négative) ou Expired (échéance, sans réponse).
            CHECK_TRUE(e.action == LSIM_TRACE_ACTION_CREATED || e.action == LSIM_TRACE_ACTION_RENEWED ||
                       e.action == LSIM_TRACE_ACTION_EXPIRED);
            if (e.action == LSIM_TRACE_ACTION_EXPIRED) {
                // Une échéance suit une exclusion posée antérieurement pour la même cible et la même valeur.
                bool posed_before = false;
                for (std::size_t j = 0; j < i; ++j) {
                    const lsim_loop_trace_v3& p = o.trace[j];
                    if (p.kind == LSIM_TRACE_KIND_EXCLUSION && p.device == e.device && p.target == e.target &&
                        p.value == e.value && p.action != LSIM_TRACE_ACTION_EXPIRED) {
                        posed_before = true;
                    }
                }
                CHECK_TRUE(posed_before);
            }
            if (e.action != LSIM_TRACE_ACTION_EXPIRED &&
                (e.target == LSIM_TRACE_TARGET_CHANNEL || e.target == LSIM_TRACE_TARGET_MASK)) {
                // Canal ou masque exclu sur réponse négative : la requête est celle de la réponse de cette émission.
                const lsim_loop_trace_v3* ans = find_ans(o, e.device, e.uplink);
                CHECK_TRUE(ans != nullptr);
                if (ans != nullptr) {
                    if (e.target == LSIM_TRACE_TARGET_MASK) {
                        CHECK_TRUE(e.value != 0);
                        CHECK_EQ(static_cast<int>(e.value), static_cast<int>(ans->channel_mask));
                    } else {
                        CHECK_TRUE(e.value <= 15);
                        CHECK_TRUE(((ans->channel_mask >> e.value) & 1U) != 0);  // canal demandé
                    }
                }
            }
            break;
        }
        case LSIM_TRACE_KIND_ADR_DECISION:
            // Origine non fixée par le contrat pour ce type : non vérifiée ici.
            CHECK_EQ(static_cast<int>(e.value), 0);
            break;
        case LSIM_TRACE_KIND_LINK_ADR_REQ:
            CHECK_TRUE(e.downlink < o.dl_n);
            // Origine : non fixée par le contrat pour ce type (voir rapport) : non vérifiée ici.
            CHECK_EQ(static_cast<int>(e.flag), 0);  // sans objet : toujours faux
            CHECK_EQ(static_cast<int>(e.value), 0);
            if (e.downlink < o.dl_n) CHECK_TRUE((o.dls[e.downlink].commands & 0x01U) != 0);  // porte LinkADRReq
            break;
        case LSIM_TRACE_KIND_DOWNLINK: {
            CHECK_TRUE(e.downlink < o.dl_n);
            if (e.downlink >= o.dl_n) break;
            const lsim_loop_downlink& d = o.dls[e.downlink];
            CHECK_EQ(e.uplink, d.uplink_index);
            CHECK_EQ(e.device, d.device_index);
            CHECK_EQ(static_cast<int>(e.origin), static_cast<int>(LSIM_TRACE_ORIGIN_RADIO));
            CHECK_EQ(static_cast<int>(e.flag), d.delivered ? 1 : 0);  // flag = descente reçue
            CHECK_TRUE((e.loss == LSIM_TRACE_LOSS_NONE) == (d.delivered != 0));  // loss ⇔ non reçue
            CHECK_EQ(static_cast<int>(e.value), static_cast<int>(d.commands));  // value = masque de commandes
            CHECK_TRUE(e.value <= 0x1F);
            if (e.loss != LSIM_TRACE_LOSS_NONE) {
                CHECK_TRUE(e.loss <= LSIM_TRACE_LOSS_BELOW_SENSITIVITY);
                c.loss[e.loss] = true;
            }
            if (e.loss == LSIM_TRACE_LOSS_NO_GATEWAY_SLOT) CHECK_EQ(d.start_ns, static_cast<std::int64_t>(-1));
            break;
        }
        case LSIM_TRACE_KIND_APPLY: {
            CHECK_TRUE(e.downlink < o.dl_n);
            if (e.downlink >= o.dl_n) break;
            const lsim_loop_downlink& d = o.dls[e.downlink];
            CHECK_EQ(e.uplink, d.uplink_index);
            CHECK_EQ(static_cast<int>(e.origin), static_cast<int>(LSIM_TRACE_ORIGIN_NORMATIVE));
            CHECK_TRUE(e.status <= 7);
            CHECK_EQ(static_cast<int>(e.flag), e.status == 0x07 ? 1 : 0);  // flag = tous les bits ACK
            CHECK_EQ(static_cast<int>(e.value), 0);
            // Un Apply ne concerne qu'une descente reçue (la requête n'est lue que si elle est reçue).
            CHECK_EQ(static_cast<int>(d.delivered), 1);
            if (e.flag != 0) c.apply_accepted = true;
            else c.apply_refused = true;
            break;
        }
        default:
            break;
        }
    }
}

// Scénario à réponses négatives sur le masque : terminal défini et actif sur 0 et 1, serveur sur 0..2.
Scenario scenario_dr_refused() {
    Scenario s = make_scenario(1, 130, true, 1);
    s.channels = {element_masks(0, {{0, 0x03}, {1, 0x03}, {2, 0x03}}, {0, 1, 2}, {0, 1, 2})};
    return s;
}

// Canal suspect : le serveur croit défini le canal 5, que le terminal ne définit pas.
Scenario scenario_channel_refused() {
    Scenario s = make_scenario(1, 130, true, 1);
    s.channels = {element_masks(0, {{0, 0x3F}, {1, 0x3F}, {2, 0x3F}}, {0, 1, 2}, {0, 1, 2, 5})};
    return s;
}

// Aucun suspect : le serveur ne voit défini que 0 et 1, et demande 0..2 ; le masque complet est exclu.
Scenario scenario_mask_refused() {
    Scenario s = make_scenario(1, 130, true, 1);
    s.channels = {element_masks(0, {{0, 0x3F}, {1, 0x3F}}, {0, 1}, {0, 1, 2})};
    return s;
}

// Passerelle occupée dans RX1 et RX2 (même configuration que le test moteur NoGatewaySlot).
Scenario scenario_no_gateway_slot() {
    Scenario s = make_scenario(2, 1, false, 1);
    s.devices[0].x_m = 10.0;
    s.devices[0].spreading_factor = 12;
    s.devices[0].start_offset_ns = 0;
    s.devices[0].period_ns = 60 * kSec;
    s.devices[1].x_m = 10.0;
    s.devices[1].spreading_factor = 7;
    s.devices[1].start_offset_ns = kSec;
    s.devices[1].period_ns = 60 * kSec;
    s.mac = {lsim_loop_mac{0, 1, 0, 1}, lsim_loop_mac{1, 1, 0, 1}};
    return s;
}

// Descente sous la sensibilité : marge de réception du dispositif réduite de 40 dB.
Scenario scenario_below_sensitivity() {
    Scenario s = make_scenario(1, 130, true, 1);
    s.devices[0].x_m = 9000.0;
    s.devices[0].spreading_factor = 7;
    s.options.protocol.device_rx_offset_db = 40.0;
    return s;
}

// Les sept types, les trois cibles d'exclusion atteignables, les pertes atteignables, Apply accepté et
// refusé : parcourus sur six scénarios ; chaque événement est contrôlé. La cible Power et la perte
// DeviceTransmitting ne sont pas atteintes par ces scénarios (voir le rapport d'étape 6.3).
void test_trace_cross_checks_across_scenarios() {
    TraceCoverage c;
    const Scenario scenarios[] = {
        make_scenario(1, 130, true, 1),  // ADR réussi
        scenario_dr_refused(),           // débit refusé : exclusion DR, Apply refusé
        scenario_mask_refused(),         // masque sans suspect : exclusion Mask
        scenario_channel_refused(),      // canal suspect : exclusion Channel
        scenario_no_gateway_slot(),      // perte NoGatewaySlot
        scenario_below_sensitivity(),    // perte BelowSensitivity
    };
    for (const Scenario& base : scenarios) {
        Scenario s = base;
        Out o = make_out(s, true);
        CHECK_EQ(static_cast<int>(run_v3(s, o, true)), 0);
        check_trace_events(o, c);
    }
    for (std::size_t k = 0; k < 7; ++k) CHECK_TRUE(c.kind[k]);
    CHECK_TRUE(c.target[LSIM_TRACE_TARGET_DATA_RATE]);
    CHECK_TRUE(c.target[LSIM_TRACE_TARGET_CHANNEL]);
    CHECK_TRUE(c.target[LSIM_TRACE_TARGET_MASK]);
    CHECK_TRUE(c.loss[LSIM_TRACE_LOSS_NO_GATEWAY_SLOT]);
    CHECK_TRUE(c.loss[LSIM_TRACE_LOSS_BELOW_SENSITIVITY]);
    CHECK_TRUE(c.apply_accepted);
    CHECK_TRUE(c.apply_refused);
}

// Ordre à timestamp identique : deux exécutions identiques produisent la même trace, octet pour octet,
// y compris pour les événements partageant un même t_ns. La condition est non vacueuse.
void test_trace_order_stable_at_equal_timestamps() {
    Scenario s = make_scenario(2, 130, true, 1);
    s.mac = {lsim_loop_mac{0, 1, 0, 1}, lsim_loop_mac{1, 1, 0, 1}};
    Out a = make_out(s, true);
    CHECK_EQ(static_cast<int>(run_v3(s, a, true)), 0);
    Out b = make_out(s, true);
    CHECK_EQ(static_cast<int>(run_v3(s, b, true)), 0);
    CHECK_EQ(a.trace_n, b.trace_n);
    CHECK_TRUE(same_trace(a, b));
    std::size_t ties = 0;
    for (std::size_t i = 0; i + 1 < a.trace_n; ++i) {
        if (a.trace[i].t_ns == a.trace[i + 1].t_ns) ++ties;
    }
    CHECK_TRUE(ties > 0);
}

// Parité historique : les résultats v3 (sans trace) égalent ceux de v2 sur un scénario
// avec ADR et descentes, et la trace v3 ne modifie pas les résultats.
void test_historical_parity_with_trace_enabled() {
    Scenario s = make_scenario(2, 130, true, 1);
    s.mac = {lsim_loop_mac{0, 1, 0, 1}, lsim_loop_mac{1, 1, 0, 1}};
    Out v2 = make_out(s, false);
    CHECK_EQ(static_cast<int>(run_v2(s, v2, false)), 0);
    Out v3 = make_out(s, true);
    CHECK_EQ(static_cast<int>(run_v3(s, v3, true)), 0);
    CHECK_TRUE(same_results(v2, v3, s.devices.size()));
}

// ADR refusé : la trace ne contient pas de Apply accepté pour le débit refusé.
void test_refused_apply_does_not_change_terminal_dr() {
    Scenario s = scenario_dr_refused();
    Out o = make_out(s, true);
    CHECK_EQ(static_cast<int>(run_v3(s, o, true)), 0);
    for (std::size_t i = 0; i < o.trace_n; ++i) {
        const lsim_loop_trace_v3& e = o.trace[i];
        if (e.kind == LSIM_TRACE_KIND_APPLY && e.flag == 0) {
            CHECK_TRUE(e.dr > 1);  // débit refusé : requête au-delà de DR1
        }
    }
    CHECK_TRUE(o.terminals[0].dr <= 1);
}

}  // namespace

void run_closed_loop_v3_api_tests() {
    test_argument_errors();
    test_mode_and_element_errors();
    test_null_and_optional_buffers();
    test_alias_and_alignment();
    test_capacity_errors_write_counts_only();
    test_common_errors_match_v2();
    test_historical_parity_with_v2_and_gw2();
    test_explicit_defaults_equal_historical();
    test_terminal_states_and_server_view();
    test_trace_events_and_sentinels();
    test_adr_success_applies_to_terminal();
    test_adr_refusal_creates_exclusion();
    test_mac_counter_invariants();
    test_validation_error_writes_nothing();
    test_trace_cross_checks_across_scenarios();
    test_trace_order_stable_at_equal_timestamps();
    test_historical_parity_with_trace_enabled();
    test_refused_apply_does_not_change_terminal_dr();
}
