// SPDX-License-Identifier: Apache-2.0
// Tests de la configuration canal v3 (étape 6.2.3) : liaison contrat 6.1 -> moteur.
// Aucune fonction v3 n'est exportée ; les tests appellent le moteur interne directement.
#include <cstdint>
#include <cstring>
#include <vector>

#include "check.hpp"
#include "lsim/c_api.h"
#include "lsim/closed_loop_v3_config.hpp"
#include "lsim/engine.hpp"
#include "lsim/loop_adr.hpp"

namespace {

using namespace lsim::sim;
using lsim::sim::abi_v3::build_channel_configs;
using lsim::sim::abi_v3::convert_trace_v3;
using lsim::sim::abi_v3::is_historical_channel_mode;

constexpr SimTime kS = 1'000'000'000;

EndDeviceSpec device_spec(double x_m, std::uint8_t sf, std::uint32_t messages) {
    EndDeviceSpec d;
    d.position.x_m = x_m;
    d.spreading_factor = sf;
    d.payload_bytes = 10;
    d.tx_power_dbm = 14.0;
    d.start_offset_ns = 0;
    d.period_ns = 60 * kS;
    d.messages = messages;
    d.duty_cycle = 1.0;
    return d;
}

lsim::plan::DeviceRadio radio_spec() {
    lsim::plan::DeviceRadio r;
    r.freq_hz = 868'100'000;
    r.rx1_hz = 868'100'000;
    r.tx_power_dbm = 14.0;
    r.rx1_bw_hz = 125'000;
    return r;
}

LoopRegion region_spec() {
    LoopRegion r;
    for (std::size_t i = 0; i < 6; ++i) r.dr_sf[i] = static_cast<std::uint8_t>(12 - i);
    r.max_dr = 5;
    r.max_tx_power_index = 7;
    r.power_step_tenth_db = 20;
    for (std::size_t i = 0; i <= 7; ++i) r.duty_limit[i] = 1.0;
    return r;
}

// Entrée canal v3 vide : présente ou absente selon `present`.
lsim_channel_device_v3 element(std::uint32_t device_index, std::uint32_t present) {
    lsim_channel_device_v3 e;
    std::memset(&e, 0, sizeof(e));
    e.struct_size = sizeof(lsim_channel_device_v3);
    e.abi_version = 3;
    e.device_index = device_index;
    e.present = present;
    return e;
}

void set_channel(std::uint8_t* bytes, std::size_t channel) { bytes[channel / 8U] |= static_cast<std::uint8_t>(1U << (channel % 8U)); }

// Arguments minimaux pour le mapping (seuls les champs canal sont lus).
lsim_closed_loop_v3_args args_with(lsim_channel_device_v3* channels, std::size_t count, std::size_t devices) {
    lsim_closed_loop_v3_args a;
    std::memset(&a, 0, sizeof(a));
    a.channels = channels;
    a.channel_count = count;
    a.device_count = devices;
    a.channel_plan = channels != nullptr ? LSIM_CHANNEL_PLAN_EU868_RP002_1_0_5 : LSIM_CHANNEL_PLAN_NONE;
    return a;
}

// Vrai si le jeu de canaux contient exactement les canaux de `expected` (liste d'indices).
bool same_channels(const LoopChannelSet& set, const std::vector<std::size_t>& expected) {
    if (set.count() != expected.size()) return false;
    for (std::size_t c : expected) {
        if (!set.test(c)) return false;
    }
    return true;
}

// Un dispositif SF12 à 10 m ; `cfg` nullptr = pas de configuration (chemin historique).
SimStatus run_one(const LoopChannelConfig* cfg, bool adr, LoopChannelIo& io, LoopResult& res,
                  SimulationStats& tot, DeviceStats* st, std::uint32_t messages, double rx_offset_db = 0.0) {
    const EndDeviceSpec d[] = {device_spec(10.0, 12, messages)};
    lsim::plan::DeviceRadio rv[1] = {radio_spec()};
    LoopRegion regions[1] = {region_spec()};
    LoopOptions opt;
    opt.adr = adr;
    opt.protocol.device_rx_offset_db = rx_offset_db;
    io.config = cfg;
    io.config_count = cfg != nullptr ? 1 : 0;
    return simulate_closed_loop_channels(d, 1, rv, regions, GatewaySpec{}, PropagationSpec{}, nullptr, opt, st,
                                         tot, res, io);
}

// Champs canal en bits à 0, 7, 8 et 15 (frontières d'octets et de vecteur de 16 bits).
void test_explicit_fields_map_bit_by_bit() {
    lsim_channel_device_v3 ch[2];
    ch[0] = element(0, LSIM_CHANNEL_PRESENT_YES);
    ch[1] = element(1, LSIM_CHANNEL_PRESENT_YES);
    for (std::size_t c : {0u, 7u, 8u, 15u}) {
        set_channel(ch[0].enabled, c);
        set_channel(ch[0].server_defined, c);
        ch[0].dr_mask[c] = 0x3F;
    }
    ch[0].dr_mask[15] = 0x20;   // DR5 seul sur le canal 15
    ch[0].dr_mask[8] = 0x03;    // DR0 et DR1 sur le canal 8
    set_channel(ch[1].enabled, 0);
    set_channel(ch[1].server_defined, 0);
    ch[1].dr_mask[0] = 0x3F;
    const auto cfg = build_channel_configs(args_with(ch, 2, 2));
    CHECK_EQ(cfg.size(), static_cast<std::size_t>(2));
    CHECK_TRUE(same_channels(cfg[0].device.enabled, {0, 7, 8, 15}));
    CHECK_TRUE(same_channels(cfg[0].server_view, {0, 7, 8, 15}));
    CHECK_EQ(static_cast<int>(cfg[0].device.dr_mask[0]), 0x3F);
    CHECK_EQ(static_cast<int>(cfg[0].device.dr_mask[7]), 0x3F);
    CHECK_EQ(static_cast<int>(cfg[0].device.dr_mask[8]), 0x03);
    CHECK_EQ(static_cast<int>(cfg[0].device.dr_mask[15]), 0x20);
    CHECK_TRUE(cfg[1].device.enabled.test(0) && cfg[1].device.enabled.count() == 1);
    CHECK_TRUE(same_channels(cfg[1].server_view, {0}));
    // Le dispositif 1 n'hérite pas des canaux du dispositif 0.
    CHECK_TRUE(!cfg[1].device.enabled.test(7) && !cfg[1].device.enabled.test(15));
}

// present = 0 : valeurs par défaut du moteur, pour le terminal comme pour la vue serveur.
void test_present_zero_uses_engine_defaults() {
    lsim_channel_device_v3 ch[2];
    ch[0] = element(0, LSIM_CHANNEL_PRESENT_NO);
    ch[1] = element(1, LSIM_CHANNEL_PRESENT_YES);
    set_channel(ch[1].enabled, 4);
    set_channel(ch[1].server_defined, 4);
    ch[1].dr_mask[4] = 0x3F;
    const auto cfg = build_channel_configs(args_with(ch, 2, 2));
    CHECK_TRUE(cfg[0].device == loop_eu868_default_channels());
    CHECK_TRUE(cfg[0].server_view == loop_eu868_plan().defaults);
    CHECK_TRUE(same_channels(cfg[1].device.enabled, {4}));
}

// Un dispositif absent de la liste reçoit aussi les valeurs par défaut (ne doit pas arriver après validation).
void test_missing_device_entry_defaults() {
    lsim_channel_device_v3 ch[1];
    ch[0] = element(1, LSIM_CHANNEL_PRESENT_YES);
    set_channel(ch[0].enabled, 3);
    set_channel(ch[0].server_defined, 3);
    ch[0].dr_mask[3] = 0x01;
    const auto cfg = build_channel_configs(args_with(ch, 1, 2));
    CHECK_TRUE(cfg[0].device == loop_eu868_default_channels());
    CHECK_TRUE(same_channels(cfg[1].device.enabled, {3}));
}

// Mode historique : channels NULL, channel_count 0 et plan NONE, et uniquement cela.
void test_historical_mode_detection() {
    lsim_closed_loop_v3_args hist = args_with(nullptr, 0, 1);
    CHECK_TRUE(is_historical_channel_mode(hist));
    lsim_channel_device_v3 ch[1] = {element(0, LSIM_CHANNEL_PRESENT_NO)};
    lsim_closed_loop_v3_args explicit_mode = args_with(ch, 1, 1);
    CHECK_TRUE(!is_historical_channel_mode(explicit_mode));
    lsim_closed_loop_v3_args plan_only = args_with(nullptr, 0, 1);
    plan_only.channel_plan = LSIM_CHANNEL_PLAN_EU868_RP002_1_0_5;
    CHECK_TRUE(!is_historical_channel_mode(plan_only));
    lsim_closed_loop_v3_args count_only = args_with(nullptr, 0, 1);
    count_only.channel_count = 1;
    CHECK_TRUE(!is_historical_channel_mode(count_only));
}

// Une configuration explicite dont tous les éléments sont à present = 0 donne exactement le résultat
// du chemin historique (config nullptr) : terminal, uplinks, statistiques et statuts d'accusé.
void test_explicit_defaults_identical_to_historical_path() {
    lsim_channel_device_v3 ch[1] = {element(0, LSIM_CHANNEL_PRESENT_NO)};
    const auto cfg = build_channel_configs(args_with(ch, 1, 1));

    LoopChannelIo io_hist;
    LoopResult res_hist;
    SimulationStats tot_hist;
    DeviceStats st_hist[1];
    CHECK_EQ(static_cast<int>(run_one(nullptr, true, io_hist, res_hist, tot_hist, st_hist, 120)), 0);

    LoopChannelIo io_expl;
    LoopResult res_expl;
    SimulationStats tot_expl;
    DeviceStats st_expl[1];
    CHECK_EQ(static_cast<int>(run_one(cfg.data(), true, io_expl, res_expl, tot_expl, st_expl, 120)), 0);

    CHECK_EQ(res_expl.uplinks.size(), res_hist.uplinks.size());
    CHECK_EQ(res_expl.downlinks.size(), res_hist.downlinks.size());
    CHECK_TRUE(tot_expl.airtime_ns == tot_hist.airtime_ns);
    CHECK_TRUE(st_expl[0].received == st_hist[0].received);
    CHECK_TRUE(st_expl[0].lost_sensitivity == st_hist[0].lost_sensitivity);
    CHECK_EQ(io_expl.uplink_status.size(), io_hist.uplink_status.size());
    for (std::size_t i = 0; i < io_expl.uplink_status.size() && i < io_hist.uplink_status.size(); ++i) {
        CHECK_EQ(static_cast<int>(io_expl.uplink_status[i]), static_cast<int>(io_hist.uplink_status[i]));
    }
    CHECK_EQ(io_expl.terminals.size(), io_hist.terminals.size());
    if (!io_expl.terminals.empty() && !io_hist.terminals.empty()) {
        CHECK_TRUE(io_expl.terminals[0] == io_hist.terminals[0]);
    }
}

// Configuration explicite restreinte : sans ADR, aucune commande ; l'état final du terminal doit
// reprendre exactement la configuration construite (bits 0, 7, 8, 15 et DR par canal).
void test_explicit_configuration_reaches_terminal_state() {
    lsim_channel_device_v3 ch[1] = {element(0, LSIM_CHANNEL_PRESENT_YES)};
    for (std::size_t c : {0u, 7u, 8u, 15u}) {
        set_channel(ch[0].enabled, c);
        set_channel(ch[0].server_defined, c);
        ch[0].dr_mask[c] = 0x3F;
    }
    ch[0].dr_mask[15] = 0x20;
    ch[0].dr_mask[8] = 0x03;
    const auto cfg = build_channel_configs(args_with(ch, 1, 1));

    LoopChannelIo io;
    LoopResult res;
    SimulationStats tot;
    DeviceStats st[1];
    CHECK_EQ(static_cast<int>(run_one(cfg.data(), false, io, res, tot, st, 20)), 0);
    CHECK_EQ(io.terminals.size(), static_cast<std::size_t>(1));
    if (!io.terminals.empty()) {
        CHECK_TRUE(io.terminals[0].channels.enabled == cfg[0].device.enabled);
        CHECK_TRUE(io.terminals[0].channels == cfg[0].device);
    }
    CHECK_TRUE(io.trace.empty());   // trace v3 non convertie à ce stade
}

// ---------------------------------------------------------------------------------------------
// Conversion de la trace (étape 6.2.4)
// ---------------------------------------------------------------------------------------------

LoopTraceEvent event(LoopTraceKind kind, LoopTraceOrigin origin, std::int64_t t_ns) {
    LoopTraceEvent e;
    e.t_ns = t_ns;
    e.device = 2;
    e.uplink = 7;
    e.kind = kind;
    e.origin = origin;
    return e;
}

// Un événement par type, valeurs non triviales : chaque champ publié est vérifié.
void test_convert_hand_built_each_kind() {
    LoopTraceEvent up = event(LoopTraceKind::Uplink, LoopTraceOrigin::Radio, 10);
    up.flag = true;
    LoopTraceEvent ans = event(LoopTraceKind::LinkAdrAns, LoopTraceOrigin::Normative, 20);
    ans.status = 0x05;                       // ChannelMaskACK = 1, DataRateACK = 0, PowerACK = 1
    ans.dr = 3;
    ans.power_index = 2;
    ans.channel_mask = 0x0107;
    ans.flag = false;
    LoopTraceEvent ex = event(LoopTraceKind::Exclusion, LoopTraceOrigin::SimulatorPolicy, 30);
    ex.action = LoopTraceAction::Renewed;
    ex.target = LoopExclusionTarget::Channel;
    ex.value = 5;
    LoopTraceEvent adr = event(LoopTraceKind::AdrDecision, LoopTraceOrigin::SimulatorPolicy, 40);
    adr.dr = 4;
    adr.power_index = 1;
    adr.flag = true;
    LoopTraceEvent req = event(LoopTraceKind::LinkAdrReq, LoopTraceOrigin::SimulatorPolicy, 50);
    req.downlink = 3;
    req.dr = kLoopFieldIgnore;               // DR ignoré dans la commande
    req.power_index = 6;
    req.channel_mask = 0x0003;
    LoopTraceEvent dl_lost = event(LoopTraceKind::Downlink, LoopTraceOrigin::Radio, 60);
    dl_lost.downlink = 3;
    dl_lost.value = 1;                        // commande LinkADR
    dl_lost.flag = false;
    dl_lost.loss = static_cast<std::uint8_t>(LoopDownlinkLoss::NoGatewaySlot);
    LoopTraceEvent dl_ok = event(LoopTraceKind::Downlink, LoopTraceOrigin::Radio, 61);
    dl_ok.downlink = 4;
    dl_ok.value = 0;
    dl_ok.flag = true;
    LoopTraceEvent apply = event(LoopTraceKind::Apply, LoopTraceOrigin::Normative, 70);
    apply.downlink = 4;
    apply.status = 0x06;
    apply.dr = 2;
    apply.power_index = 0;
    apply.channel_mask = 0x0001;
    apply.flag = false;
    apply.reason_channel = static_cast<std::uint8_t>(LoopChannelReason::UndefinedChannel);
    apply.reason_dr = static_cast<std::uint8_t>(LoopDataRateReason::NotSupportedByChannels);
    apply.reason_power = static_cast<std::uint8_t>(LoopPowerReason::Reserved);

    const std::vector<LoopTraceEvent> in = {up, ans, ex, adr, req, dl_lost, dl_ok, apply};
    const auto out = convert_trace_v3(in);
    CHECK_EQ(out.size(), in.size());
    if (out.size() != in.size()) return;

    // Uplink : pas de LinkADRAns, pas de descente, flag = reçu.
    CHECK_EQ(static_cast<int>(out[0].kind), static_cast<int>(LSIM_TRACE_KIND_UPLINK));
    CHECK_EQ(static_cast<int>(out[0].origin), static_cast<int>(LSIM_TRACE_ORIGIN_RADIO));
    CHECK_EQ(static_cast<int>(out[0].status), static_cast<int>(LSIM_TRACE_STATUS_NONE));
    CHECK_EQ(static_cast<int>(out[0].downlink), static_cast<int>(LSIM_TRACE_NO_INDEX));
    CHECK_EQ(static_cast<int>(out[0].flag), 1);
    CHECK_EQ(static_cast<int>(out[0].loss), 0);
    CHECK_EQ(static_cast<int>(out[0].device), 2);
    CHECK_EQ(static_cast<int>(out[0].uplink), 7);

    // LinkAdrAns : bits ACK et contenu acquitté ; descente absente.
    CHECK_EQ(static_cast<int>(out[1].kind), static_cast<int>(LSIM_TRACE_KIND_LINK_ADR_ANS));
    CHECK_EQ(static_cast<int>(out[1].origin), static_cast<int>(LSIM_TRACE_ORIGIN_NORMATIVE));
    CHECK_EQ(static_cast<int>(out[1].status), 0x05);
    CHECK_EQ(static_cast<int>(out[1].downlink), static_cast<int>(LSIM_TRACE_NO_INDEX));
    CHECK_EQ(static_cast<int>(out[1].dr), 3);
    CHECK_EQ(static_cast<int>(out[1].power_index), 2);
    CHECK_EQ(static_cast<int>(out[1].channel_mask), 0x0107);
    CHECK_EQ(static_cast<int>(out[1].flag), 0);

    // Exclusion : action, cible, valeur ; pas de statut ni de descente.
    CHECK_EQ(static_cast<int>(out[2].kind), static_cast<int>(LSIM_TRACE_KIND_EXCLUSION));
    CHECK_EQ(static_cast<int>(out[2].origin), static_cast<int>(LSIM_TRACE_ORIGIN_SIMULATOR_POLICY));
    CHECK_EQ(static_cast<int>(out[2].action), static_cast<int>(LSIM_TRACE_ACTION_RENEWED));
    CHECK_EQ(static_cast<int>(out[2].target), static_cast<int>(LSIM_TRACE_TARGET_CHANNEL));
    CHECK_EQ(static_cast<int>(out[2].value), 5);
    CHECK_EQ(static_cast<int>(out[2].status), static_cast<int>(LSIM_TRACE_STATUS_NONE));
    CHECK_EQ(static_cast<int>(out[2].downlink), static_cast<int>(LSIM_TRACE_NO_INDEX));

    // AdrDecision : débit et puissance demandés, flag = demande en attente.
    CHECK_EQ(static_cast<int>(out[3].kind), static_cast<int>(LSIM_TRACE_KIND_ADR_DECISION));
    CHECK_EQ(static_cast<int>(out[3].dr), 4);
    CHECK_EQ(static_cast<int>(out[3].power_index), 1);
    CHECK_EQ(static_cast<int>(out[3].flag), 1);
    CHECK_EQ(static_cast<int>(out[3].downlink), static_cast<int>(LSIM_TRACE_NO_INDEX));

    // LinkAdrReq : descente planifiée, FIELD_IGNORE conservé, pas de statut ACK.
    CHECK_EQ(static_cast<int>(out[4].kind), static_cast<int>(LSIM_TRACE_KIND_LINK_ADR_REQ));
    CHECK_EQ(static_cast<int>(out[4].downlink), 3);
    CHECK_EQ(static_cast<int>(out[4].dr), static_cast<int>(LSIM_TRACE_FIELD_IGNORE));
    CHECK_EQ(static_cast<int>(out[4].power_index), 6);
    CHECK_EQ(static_cast<int>(out[4].channel_mask), 0x0003);
    CHECK_EQ(static_cast<int>(out[4].status), static_cast<int>(LSIM_TRACE_STATUS_NONE));
    CHECK_EQ(static_cast<int>(out[4].loss), 0);

    // Downlink perdue : cause NO_GATEWAY_SLOT, flag = 0, valeur = commandes.
    CHECK_EQ(static_cast<int>(out[5].kind), static_cast<int>(LSIM_TRACE_KIND_DOWNLINK));
    CHECK_EQ(static_cast<int>(out[5].origin), static_cast<int>(LSIM_TRACE_ORIGIN_RADIO));
    CHECK_EQ(static_cast<int>(out[5].loss), static_cast<int>(LSIM_TRACE_LOSS_NO_GATEWAY_SLOT));
    CHECK_EQ(static_cast<int>(out[5].flag), 0);
    CHECK_EQ(static_cast<int>(out[5].value), 1);
    CHECK_EQ(static_cast<int>(out[5].downlink), 3);
    CHECK_EQ(static_cast<int>(out[5].status), static_cast<int>(LSIM_TRACE_STATUS_NONE));

    // Downlink reçue : pas de cause, flag = 1.
    CHECK_EQ(static_cast<int>(out[6].loss), static_cast<int>(LSIM_TRACE_LOSS_NONE));
    CHECK_EQ(static_cast<int>(out[6].flag), 1);
    CHECK_EQ(static_cast<int>(out[6].downlink), 4);

    // Apply : bits ACK, motifs D5 par partie, descente conservée.
    CHECK_EQ(static_cast<int>(out[7].kind), static_cast<int>(LSIM_TRACE_KIND_APPLY));
    CHECK_EQ(static_cast<int>(out[7].origin), static_cast<int>(LSIM_TRACE_ORIGIN_NORMATIVE));
    CHECK_EQ(static_cast<int>(out[7].status), 0x06);
    CHECK_EQ(static_cast<int>(out[7].downlink), 4);
    CHECK_EQ(static_cast<int>(out[7].flag), 0);
    CHECK_EQ(static_cast<int>(out[7].reason_channel), static_cast<int>(LSIM_TRACE_CHANNEL_REASON_UNDEFINED_CHANNEL));
    CHECK_EQ(static_cast<int>(out[7].reason_dr), static_cast<int>(LSIM_TRACE_DR_REASON_NOT_SUPPORTED_BY_CHANNELS));
    CHECK_EQ(static_cast<int>(out[7].reason_power), static_cast<int>(LSIM_TRACE_POWER_REASON_RESERVED));

    for (const auto& o : out) CHECK_EQ(static_cast<int>(o.reserved), 0);
}

// Ordre d'entrée conservé à l'identique, égalités de t_ns comprises (pas de tri supplémentaire).
void test_convert_preserves_input_order() {
    const std::vector<LoopTraceEvent> in = {
        event(LoopTraceKind::Uplink, LoopTraceOrigin::Radio, 5),
        event(LoopTraceKind::LinkAdrAns, LoopTraceOrigin::Normative, 5),
        event(LoopTraceKind::Exclusion, LoopTraceOrigin::SimulatorPolicy, 5),
        event(LoopTraceKind::Apply, LoopTraceOrigin::Normative, 9),
    };
    const auto out = convert_trace_v3(in);
    CHECK_EQ(out.size(), in.size());
    if (out.size() != in.size()) return;
    for (std::size_t i = 0; i < in.size(); ++i) {
        CHECK_EQ(static_cast<int>(out[i].kind), static_cast<int>(in[i].kind));
        CHECK_TRUE(out[i].t_ns == in[i].t_ns);
    }
    CHECK_TRUE(convert_trace_v3({}).empty());
}

// Scénario moteur : une LinkADRReq forcée au débit 6 (non supporté) doit produire les sept types.
// Pour chaque événement, les sentinelles publiées doivent être celles de la règle, et la valeur
// interne doit déjà les respecter (aucune valeur masquée par la conversion).
void test_engine_trace_covers_seven_kinds_and_sentinels() {
    LoopChannelConfig cfg;
    cfg.device = loop_eu868_default_channels();
    cfg.server_view = loop_eu868_plan().defaults;
    LoopLinkAdrRequest bad;
    bad.ch_mask_cntl = 0;
    bad.ch_mask = 0x0007;
    bad.dr = 6;
    bad.power_index = 0;
    cfg.forced_sequence = {bad};
    LoopChannelIo io;
    io.trace_v3 = true;
    LoopResult res;
    SimulationStats tot;
    DeviceStats st[1];
    CHECK_EQ(static_cast<int>(run_one(&cfg, true, io, res, tot, st, 60)), 0);
    const auto out = convert_trace_v3(io.trace);
    CHECK_EQ(out.size(), io.trace.size());
    if (out.size() != io.trace.size()) return;

    std::size_t kinds[7] = {0, 0, 0, 0, 0, 0, 0};
    for (std::size_t i = 0; i < out.size(); ++i) {
        const LoopTraceEvent& e = io.trace[i];
        const lsim_loop_trace_v3& o = out[i];
        CHECK_TRUE(o.t_ns == e.t_ns);
        if (i > 0) CHECK_TRUE(out[i - 1].t_ns <= o.t_ns);
        CHECK_TRUE(o.kind < 7);
        if (o.kind < 7) ++kinds[o.kind];
        const bool status_applies = e.kind == LoopTraceKind::LinkAdrAns || e.kind == LoopTraceKind::Apply;
        const bool indexed = e.kind == LoopTraceKind::LinkAdrReq || e.kind == LoopTraceKind::Downlink ||
                             e.kind == LoopTraceKind::Apply;
        // Sentinelles : la valeur interne doit déjà être la sentinelle, sinon la conversion masquerait un défaut.
        if (!status_applies) CHECK_EQ(static_cast<int>(e.status), 0xFF);
        if (!indexed) CHECK_TRUE(e.downlink == kLoopNoIndex);
        if (e.kind != LoopTraceKind::Downlink) CHECK_EQ(static_cast<int>(e.loss), 0);
        CHECK_EQ(static_cast<int>(o.status), status_applies ? static_cast<int>(e.status) : 0xFF);
        CHECK_TRUE(o.downlink == (indexed ? e.downlink : LSIM_TRACE_NO_INDEX));
        CHECK_EQ(static_cast<int>(o.reserved), 0);
    }
    // Les sept types d'événements apparaissent (couverture par ce scénario).
    for (std::size_t k = 0; k < 7; ++k) CHECK_TRUE(kinds[k] > 0);
    // Exclusion de débit 6 (refus) présente.
    bool dr6 = false;
    for (const auto& o : out) {
        if (o.kind == LSIM_TRACE_KIND_EXCLUSION && o.target == LSIM_TRACE_TARGET_DATA_RATE && o.value == 6) dr6 = true;
    }
    CHECK_TRUE(dr6);
}


// ---------------------------------------------------------------------------------------------
// Causes de perte (étape 6.2.5) : chaque cause est publiée pour Downlink et seulement pour Downlink.
// ---------------------------------------------------------------------------------------------

constexpr LoopDownlinkLoss kCauses[] = {LoopDownlinkLoss::NoGatewaySlot, LoopDownlinkLoss::DeviceTransmitting,
                                        LoopDownlinkLoss::BelowSensitivity};

void test_convert_loss_causes_downlink_only() {
    for (LoopDownlinkLoss cause : kCauses) {
        LoopTraceEvent lost = event(LoopTraceKind::Downlink, LoopTraceOrigin::Radio, 3);
        lost.downlink = 1;
        lost.flag = false;
        lost.loss = static_cast<std::uint8_t>(cause);
        const auto out = convert_trace_v3({lost});
        CHECK_EQ(out.size(), std::size_t{1});
        if (out.size() != 1) continue;
        CHECK_EQ(static_cast<int>(out[0].loss), static_cast<int>(cause));
        CHECK_EQ(static_cast<int>(out[0].flag), 0);
        CHECK_EQ(static_cast<int>(out[0].downlink), 1);
    }
    // Même valeur de loss sur les autres types : publiée à 0.
    const LoopTraceKind others[] = {LoopTraceKind::Uplink, LoopTraceKind::LinkAdrAns, LoopTraceKind::Exclusion,
                                    LoopTraceKind::AdrDecision, LoopTraceKind::LinkAdrReq, LoopTraceKind::Apply};
    for (LoopDownlinkLoss cause : kCauses) {
        for (LoopTraceKind kind : others) {
            LoopTraceEvent e = event(kind, LoopTraceOrigin::Normative, 4);
            e.loss = static_cast<std::uint8_t>(cause);
            const auto out = convert_trace_v3({e});
            CHECK_EQ(out.size(), std::size_t{1});
            if (out.size() != 1) continue;
            CHECK_EQ(static_cast<int>(out[0].loss), 0);
        }
    }
}

// Scénario moteur : passerelle occupée dans RX1 et RX2 (même scénario que test_closed_loop) : NoGatewaySlot.
void test_engine_no_gateway_slot_loss_is_converted() {
    const std::vector<EndDeviceSpec> devs = {device_spec(10.0, 12, 1), device_spec(10.0, 7, 1)};
    std::vector<EndDeviceSpec> d = devs;
    d[1].start_offset_ns = kS;
    const std::vector<lsim::plan::DeviceRadio> rv = {radio_spec(), radio_spec()};
    const std::vector<LoopRegion> regions = {region_spec(), region_spec()};
    const std::vector<LoopMacSlot> slots = {{0, 1, 0, kLoopMacLinkCheck}, {1, 1, 0, kLoopMacLinkCheck}};
    LoopOptions opt;
    opt.mac = slots.data();
    opt.mac_count = slots.size();
    LoopChannelIo io;
    io.trace_v3 = true;
    LoopResult res;
    SimulationStats tot;
    std::vector<DeviceStats> st(d.size(), DeviceStats{});
    CHECK_EQ(static_cast<int>(simulate_closed_loop_channels(d.data(), d.size(), rv.data(), regions.data(),
                                                            GatewaySpec{}, PropagationSpec{}, nullptr, opt,
                                                            st.data(), tot, res, io)),
             0);
    const auto out = convert_trace_v3(io.trace);
    int seen = 0;
    for (const auto& o : out) {
        if (o.kind == LSIM_TRACE_KIND_DOWNLINK && o.loss == LSIM_TRACE_LOSS_NO_GATEWAY_SLOT) {
            ++seen;
            CHECK_EQ(static_cast<int>(o.flag), 0);
        }
    }
    CHECK_EQ(seen, 1);
}

// Scénario moteur : décalage de réception du terminal de 200 dB : descentes perdues sous la sensibilité.
void test_engine_below_sensitivity_loss_is_converted() {
    LoopChannelIo io;
    io.trace_v3 = true;
    LoopResult res;
    SimulationStats tot;
    DeviceStats st[1];
    CHECK_EQ(static_cast<int>(run_one(nullptr, true, io, res, tot, st, 60, 200.0)), 0);
    const auto out = convert_trace_v3(io.trace);
    int below = 0;
    int other_loss = 0;
    for (const auto& o : out) {
        if (o.kind != LSIM_TRACE_KIND_DOWNLINK) continue;
        if (o.loss == LSIM_TRACE_LOSS_BELOW_SENSITIVITY) ++below;
        if (o.loss != LSIM_TRACE_LOSS_NONE && o.loss != LSIM_TRACE_LOSS_BELOW_SENSITIVITY) ++other_loss;
    }
    CHECK_TRUE(below >= 1);
    CHECK_EQ(other_loss, 0);
}

// DeviceTransmitting : inatteignable dans la boucle fermée sous C1 (test_closed_loop, option a).
// La conversion est vérifiée ici sur un événement construit, sans prétendre à une couverture moteur.
void test_convert_device_transmitting_from_constructed_event() {
    LoopTraceEvent e = event(LoopTraceKind::Downlink, LoopTraceOrigin::Radio, 5);
    e.downlink = 0;
    e.flag = false;
    e.loss = static_cast<std::uint8_t>(LoopDownlinkLoss::DeviceTransmitting);
    const auto out = convert_trace_v3({e});
    CHECK_EQ(out.size(), std::size_t{1});
    if (out.size() == 1) CHECK_EQ(static_cast<int>(out[0].loss), LSIM_TRACE_LOSS_DEVICE_TRANSMITTING);
}

}  // namespace

void run_channel_config_v3_tests() {
    test_explicit_fields_map_bit_by_bit();
    test_present_zero_uses_engine_defaults();
    test_missing_device_entry_defaults();
    test_historical_mode_detection();
    test_explicit_defaults_identical_to_historical_path();
    test_explicit_configuration_reaches_terminal_state();
    test_convert_hand_built_each_kind();
    test_convert_preserves_input_order();
    test_engine_trace_covers_seven_kinds_and_sentinels();
    test_convert_loss_causes_downlink_only();
    test_engine_no_gateway_slot_loss_is_converted();
    test_engine_below_sensitivity_loss_is_converted();
    test_convert_device_transmitting_from_constructed_event();
}
