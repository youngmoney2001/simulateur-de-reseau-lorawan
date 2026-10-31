// SPDX-License-Identifier: Apache-2.0
// Validation fonctionnelle croisée EU868 (étape 6.2.6) : configurations explicites, vue serveur
// distincte de l'état terminal, ADR actif, plusieurs dispositifs, configuration mixte (present = 0),
// parité du mode historique. Aucune règle ADR, D5, D6, D7, C1 ni retransmission n'est modifiée.
// Les tests passent par le chemin v3 (build_channel_configs) quand la configuration est explicite.
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <initializer_list>
#include <vector>

#include "check.hpp"
#include "lsim/c_api.h"
#include "lsim/closed_loop_v3_config.hpp"
#include "lsim/engine.hpp"
#include "lsim/loop_adr.hpp"

namespace {

using namespace lsim::sim;
using lsim::sim::abi_v3::build_channel_configs;

constexpr SimTime kS = 1'000'000'000;
constexpr std::uint8_t kAccepted = 0x07;
using Bits = std::vector<unsigned>;

EndDeviceSpec dev(double x_m, std::uint8_t sf, SimTime offset_ns, std::uint32_t messages) {
    EndDeviceSpec d;
    d.position.x_m = x_m;
    d.spreading_factor = sf;
    d.payload_bytes = 10;
    d.tx_power_dbm = 14.0;
    d.start_offset_ns = offset_ns;
    d.period_ns = 60 * kS;
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

// Configuration explicite : canaux définis (DR0..DR5), actifs et vue serveur.
LoopChannelConfig make_cfg(const Bits& defined, const Bits& enabled, const Bits& server) {
    LoopChannelConfig c;
    for (unsigned ch : defined) c.device.dr_mask[ch] = 0x3F;
    for (unsigned ch : enabled) c.device.enabled.set(ch);
    for (unsigned ch : server) c.server_view.set(ch);
    return c;
}

lsim_channel_device_v3 element(std::uint32_t index, std::uint32_t present, const Bits& defined, const Bits& enabled,
                               const Bits& server) {
    lsim_channel_device_v3 e;
    std::memset(&e, 0, sizeof(e));
    e.struct_size = sizeof(lsim_channel_device_v3);
    e.abi_version = 3;
    e.device_index = index;
    e.present = present;
    for (unsigned ch : defined) e.dr_mask[ch] = 0x3F;
    for (unsigned ch : enabled) e.enabled[ch / 8] = static_cast<std::uint8_t>(e.enabled[ch / 8] | (1U << (ch % 8)));
    for (unsigned ch : server) {
        e.server_defined[ch / 8] = static_cast<std::uint8_t>(e.server_defined[ch / 8] | (1U << (ch % 8)));
    }
    return e;
}

struct Outcome {
    SimStatus st = SimStatus::Ok;
    LoopChannelIo io;
    LoopResult res;
    SimulationStats tot;
    std::vector<DeviceStats> stats;
};

// Simulation multi-dispositifs, SF12, décalages de 20 s (pas de collision), ADR optionnel.
// `cfg` nullptr : chemin historique de la boucle fermée avec canaux.
void run(const std::vector<LoopChannelConfig>* cfg, bool adr, std::uint32_t messages, Outcome& out,
         std::size_t devices = 1) {
    std::vector<EndDeviceSpec> devs;
    std::vector<lsim::plan::DeviceRadio> rv;
    std::vector<LoopRegion> regions;
    for (std::size_t i = 0; i < devices; ++i) {
        devs.push_back(dev(10.0 + 5.0 * static_cast<double>(i), 12, static_cast<SimTime>(20 * i) * kS, messages));
        rv.push_back(radio());
        regions.push_back(region());
    }
    LoopOptions opt;
    opt.adr = adr;
    out = Outcome{};
    out.stats.assign(devs.size(), DeviceStats{});
    out.io.trace_v3 = true;
    out.io.config = cfg != nullptr ? cfg->data() : nullptr;
    out.io.config_count = cfg != nullptr ? cfg->size() : 0;
    out.st = simulate_closed_loop_channels(devs.data(), devs.size(), rv.data(), regions.data(), GatewaySpec{},
                                           PropagationSpec{}, nullptr, opt, out.stats.data(), out.tot, out.res,
                                           out.io);
}

// Descentes portant une LinkADRReq, pour un dispositif donné : indices dans res.downlinks.
std::vector<std::size_t> linkadr_downlinks(const Outcome& o, std::uint32_t device) {
    std::vector<std::size_t> idx;
    for (std::size_t i = 0; i < o.res.downlinks.size(); ++i) {
        if (o.res.downlinks[i].device != device) continue;
        if ((o.res.downlinks[i].commands & kLoopCmdLinkAdr) != 0) idx.push_back(i);
    }
    return idx;
}

// Nombre d'événements Apply avec application complète pour un dispositif.
int applied_count(const Outcome& o, std::uint32_t device) {
    int n = 0;
    for (const LoopTraceEvent& e : o.io.trace) {
        if (e.kind == LoopTraceKind::Apply && e.device == device && e.flag) ++n;
    }
    return n;
}

bool same_set(const LoopChannelSet& s, const Bits& expected) {
    if (s.count() != expected.size()) return false;
    for (unsigned c : expected) {
        if (!s.test(c)) return false;
    }
    return true;
}

bool all_requests_mask(const Outcome& o, std::uint32_t device, std::uint16_t mask) {
    const auto idx = linkadr_downlinks(o, device);
    if (idx.empty()) return false;
    for (std::size_t i : idx) {
        if (o.io.downlink_requests[i].ch_mask != mask) return false;
    }
    return true;
}

// ---------------------------------------------------------------------------------------------
// 1. Vue serveur différente de l'état terminal, ADR actif.
// Terminal : canaux 0, 1, 2 définis et actifs. Serveur : 0 et 1 seulement.
// Attendu : toutes les requêtes portent le masque serveur 0x03 ; après application, le terminal
// n'active que 0 et 1 ; le canal 2 reste défini (capacité) et n'est plus actif.
// ---------------------------------------------------------------------------------------------
void test_server_view_differs_from_terminal_with_adr() {
    const std::vector<LoopChannelConfig> cfg = {make_cfg({0, 1, 2}, {0, 1, 2}, {0, 1})};
    Outcome o;
    run(&cfg, true, 120, o);
    CHECK_EQ(static_cast<int>(o.st), static_cast<int>(SimStatus::Ok));
    if (o.st != SimStatus::Ok) return;
    CHECK_TRUE(!linkadr_downlinks(o, 0).empty());
    CHECK_TRUE(all_requests_mask(o, 0, 0x03));
    CHECK_TRUE(applied_count(o, 0) >= 1);
    CHECK_EQ(o.io.terminals.size(), std::size_t{1});
    if (o.io.terminals.size() != 1) return;
    const LoopTerminalRadio& t = o.io.terminals[0];
    CHECK_TRUE(same_set(t.channels.enabled, {0, 1}));          // état terminal = requête appliquée
    CHECK_TRUE(t.channels.defined(2));                         // capacité conservée
    CHECK_TRUE(t.channels.dr_mask[2] == cfg[0].device.dr_mask[2]);
    CHECK_TRUE(same_set(cfg[0].server_view, {0, 1}));          // la vue serveur n'a pas été modifiée
    // La vue serveur ne devient pas l'état terminal : la configuration d'entrée est intacte.
    CHECK_TRUE(cfg[0].device.enabled.test(2));
    // Trace : chaque LinkADRReq porte le masque serveur ; chaque application porte le même masque.
    for (const LoopTraceEvent& e : o.io.trace) {
        if (e.kind == LoopTraceKind::LinkAdrReq) CHECK_EQ(static_cast<int>(e.channel_mask), 0x03);
        if (e.kind == LoopTraceKind::Apply && e.flag) CHECK_EQ(static_cast<int>(e.channel_mask), 0x03);
    }
    // LinkADRAns reçues : au moins une réponse acceptée.
    bool ans_ok = false;
    for (std::uint8_t s : o.io.uplink_status) {
        if (s == kAccepted) ans_ok = true;
    }
    CHECK_TRUE(ans_ok);
}

// ---------------------------------------------------------------------------------------------
// 2. Refus éventuels : la vue serveur contient le canal 5, que le terminal ne définit pas.
// Attendu : refus CM (UndefinedChannel, canal 5 suspect), rien n'est appliqué au terminal
// (atomicité), et le canal 5 est exclu des requêtes suivantes (renégociation).
// ---------------------------------------------------------------------------------------------
void test_server_channel_undefined_on_terminal_refused_then_renegotiated() {
    const std::vector<LoopChannelConfig> cfg = {make_cfg({0, 1, 2}, {0, 1, 2}, {0, 1, 5})};
    Outcome o;
    run(&cfg, true, 120, o);
    CHECK_EQ(static_cast<int>(o.st), static_cast<int>(SimStatus::Ok));
    if (o.st != SimStatus::Ok) return;
    const auto idx = linkadr_downlinks(o, 0);
    CHECK_TRUE(!idx.empty());
    // Première requête : masque serveur complet, refusée pour le canal 5.
    bool refused = false;
    std::size_t first_refusal = idx.size();
    for (std::size_t k = 0; k < idx.size(); ++k) {
        const std::size_t i = idx[k];
        if (!o.res.downlinks[i].delivered) continue;
        if (o.io.downlink_diagnoses[i].channel_reason == LoopChannelReason::UndefinedChannel) {
            refused = true;
            if (first_refusal == idx.size()) first_refusal = k;
            CHECK_TRUE(o.io.downlink_diagnoses[i].refused_channels.test(5));
            CHECK_TRUE(!o.io.downlink_diagnoses[i].status.channel_mask_ack);
        }
    }
    CHECK_TRUE(refused);
    CHECK_TRUE(first_refusal < idx.size());
    // Les requêtes après le premier refus n'incluent plus le canal 5 (renégociation).
    for (std::size_t k = first_refusal + 1; k < idx.size(); ++k) {
        CHECK_TRUE((o.io.downlink_requests[idx[k]].ch_mask & 0x0020) == 0);
    }
    // Le terminal n'active jamais le canal 5 et ne dépasse pas sa définition.
    CHECK_EQ(o.io.terminals.size(), std::size_t{1});
    if (o.io.terminals.size() == 1) {
        CHECK_TRUE(!o.io.terminals[0].channels.enabled.test(5));
        CHECK_TRUE(!o.io.terminals[0].channels.defined(5));
    }
    // Une LinkADRAns négative est publiée (bit 0 à 0) pour l'uplink qui porte la réponse.
    bool negative = false;
    for (std::uint8_t s : o.io.uplink_status) {
        if (s != 0xFF && (s & 1U) == 0) negative = true;
    }
    CHECK_TRUE(negative);
}

// ---------------------------------------------------------------------------------------------
// 3. Plusieurs dispositifs, configurations explicites différentes, ADR actif.
//   dev0 : vue = terminal (0,1,2) ;
//   dev1 : terminal actif 0..3, vue serveur 0,1 (divergence) ;
//   dev2 : terminal actif 1,2 seulement, vue serveur 0,1,2 (requête complète, activation de 0).
// Attendu : chaque requête suit la vue du dispositif concerné, l'état terminal est isolé.
// ---------------------------------------------------------------------------------------------
void test_multi_device_distinct_explicit_configurations() {
    const std::vector<LoopChannelConfig> cfg = {
        make_cfg({0, 1, 2}, {0, 1, 2}, {0, 1, 2}),
        make_cfg({0, 1, 2, 3}, {0, 1, 2, 3}, {0, 1}),
        make_cfg({0, 1, 2}, {1, 2}, {0, 1, 2}),
    };
    Outcome o;
    run(&cfg, true, 120, o, 3);
    CHECK_EQ(static_cast<int>(o.st), static_cast<int>(SimStatus::Ok));
    if (o.st != SimStatus::Ok) return;
    CHECK_TRUE(all_requests_mask(o, 0, 0x07));
    CHECK_TRUE(all_requests_mask(o, 1, 0x03));
    CHECK_TRUE(all_requests_mask(o, 2, 0x07));
    CHECK_EQ(o.io.terminals.size(), std::size_t{3});
    if (o.io.terminals.size() != 3) return;
    CHECK_TRUE(same_set(o.io.terminals[0].channels.enabled, {0, 1, 2}));
    CHECK_TRUE(same_set(o.io.terminals[1].channels.enabled, {0, 1}));     // appliqué : vue serveur
    CHECK_TRUE(o.io.terminals[1].channels.defined(3));                    // 3 reste défini
    CHECK_TRUE(same_set(o.io.terminals[2].channels.enabled, {0, 1, 2}));  // 0 réactivé par la vue serveur
    // Isolation : aucun dispositif ne porte les canaux d'un autre (canal 3 absent des dispositifs 0 et 2).
    CHECK_TRUE(!o.io.terminals[0].channels.defined(3));
    CHECK_TRUE(!o.io.terminals[2].channels.defined(3));
}

// ---------------------------------------------------------------------------------------------
// 4. Configuration mixte par le chemin v3 : dev0 explicite, dev1 present = 0 (défauts), dev2 explicite.
// Attendu : dev1 reçoit exactement les défauts EU868 (canaux 0..2, DR0..DR5, vue 0..2) et ses requêtes
// suivent la vue par défaut ; dev0 et dev2 ne sont pas affectés par dev1.
// ---------------------------------------------------------------------------------------------
void test_mixed_configuration_present_zero_uses_defaults() {
    lsim_channel_device_v3 ch[3] = {
        element(0, LSIM_CHANNEL_PRESENT_YES, {0, 1, 2, 3}, {0, 1, 2, 3}, {0, 1}),
        element(1, LSIM_CHANNEL_PRESENT_NO, {}, {}, {}),
        element(2, LSIM_CHANNEL_PRESENT_YES, {0, 1, 2}, {1, 2}, {0, 1, 2}),
    };
    lsim_closed_loop_v3_args a;
    std::memset(&a, 0, sizeof(a));
    a.channels = ch;
    a.channel_count = 3;
    a.device_count = 3;
    const std::vector<LoopChannelConfig> cfg = build_channel_configs(a);
    CHECK_EQ(cfg.size(), std::size_t{3});
    if (cfg.size() != 3) return;
    CHECK_TRUE(cfg[1].device == loop_eu868_default_channels());
    CHECK_TRUE(cfg[1].server_view == loop_eu868_plan().defaults);
    Outcome o;
    run(&cfg, true, 120, o, 3);
    CHECK_EQ(static_cast<int>(o.st), static_cast<int>(SimStatus::Ok));
    if (o.st != SimStatus::Ok) return;
    CHECK_TRUE(all_requests_mask(o, 1, 0x07));                     // vue par défaut 0..2
    CHECK_TRUE(all_requests_mask(o, 0, 0x03));                     // vue explicite 0,1
    CHECK_TRUE(all_requests_mask(o, 2, 0x07));                     // vue explicite 0,1,2
    CHECK_EQ(o.io.terminals.size(), std::size_t{3});
    if (o.io.terminals.size() != 3) return;
    CHECK_TRUE(same_set(o.io.terminals[1].channels.enabled, {0, 1, 2}));   // défauts inchangés
    CHECK_TRUE(o.io.terminals[1].channels.defined(0) && o.io.terminals[1].channels.defined(1) && o.io.terminals[1].channels.defined(2));
    CHECK_TRUE(!o.io.terminals[1].channels.defined(3));
    CHECK_TRUE(same_set(o.io.terminals[0].channels.enabled, {0, 1}));
    CHECK_TRUE(o.io.terminals[0].channels.defined(3));
}

// ---------------------------------------------------------------------------------------------
// 5. Parité du mode historique : chemin historique (simulate_closed_loop), chemin canaux sans
// configuration, et configuration explicite entièrement en present = 0 (via le chemin v3) donnent
// le même résultat : statistiques, uplinks, descentes, statuts d'accusé et états terminaux.
// ---------------------------------------------------------------------------------------------
void test_historical_parity_three_paths() {
    constexpr std::size_t n = 3;
    std::vector<EndDeviceSpec> devs;
    std::vector<lsim::plan::DeviceRadio> rv;
    std::vector<LoopRegion> regions;
    for (std::size_t i = 0; i < n; ++i) {
        devs.push_back(dev(10.0 + 5.0 * static_cast<double>(i), 12, static_cast<SimTime>(20 * i) * kS, 120));
        rv.push_back(radio());
        regions.push_back(region());
    }
    LoopOptions opt;
    opt.adr = true;
    std::vector<DeviceStats> st_legacy(n), st_null(n), st_def(n);
    SimulationStats tot_legacy, tot_null, tot_def;
    LoopResult legacy, with_null, with_def;
    CHECK_EQ(static_cast<int>(simulate_closed_loop(devs.data(), n, rv.data(), regions.data(), GatewaySpec{},
                                                   PropagationSpec{}, nullptr, opt, st_legacy.data(), tot_legacy,
                                                   legacy)),
             0);
    LoopChannelIo io_null;
    CHECK_EQ(static_cast<int>(simulate_closed_loop_channels(devs.data(), n, rv.data(), regions.data(), GatewaySpec{},
                                                            PropagationSpec{}, nullptr, opt, st_null.data(), tot_null,
                                                            with_null, io_null)),
             0);
    lsim_channel_device_v3 ch[3];
    for (std::uint32_t i = 0; i < n; ++i) ch[i] = element(i, LSIM_CHANNEL_PRESENT_NO, {}, {}, {});
    lsim_closed_loop_v3_args a;
    std::memset(&a, 0, sizeof(a));
    a.channels = ch;
    a.channel_count = n;
    a.device_count = n;
    const std::vector<LoopChannelConfig> cfg = build_channel_configs(a);
    LoopChannelIo io_def;
    io_def.config = cfg.data();
    io_def.config_count = cfg.size();
    CHECK_EQ(static_cast<int>(simulate_closed_loop_channels(devs.data(), n, rv.data(), regions.data(), GatewaySpec{},
                                                            PropagationSpec{}, nullptr, opt, st_def.data(), tot_def,
                                                            with_def, io_def)),
             0);
    // Statistiques.
    CHECK_TRUE(tot_null.airtime_ns == tot_legacy.airtime_ns && tot_def.airtime_ns == tot_legacy.airtime_ns);
    CHECK_TRUE(tot_null.received == tot_legacy.received && tot_def.received == tot_legacy.received);
    for (std::size_t i = 0; i < n; ++i) {
        CHECK_TRUE(st_null[i].received == st_legacy[i].received && st_def[i].received == st_legacy[i].received);
        CHECK_TRUE(st_null[i].lost_sensitivity == st_legacy[i].lost_sensitivity);
    }
    // Uplinks et descentes.
    CHECK_EQ(legacy.uplinks.size(), with_null.uplinks.size());
    CHECK_EQ(legacy.uplinks.size(), with_def.uplinks.size());
    CHECK_EQ(legacy.downlinks.size(), with_null.downlinks.size());
    CHECK_EQ(legacy.downlinks.size(), with_def.downlinks.size());
    const std::size_t nu = legacy.uplinks.size() < with_def.uplinks.size() ? legacy.uplinks.size() : with_def.uplinks.size();
    for (std::size_t i = 0; i < nu; ++i) {
        CHECK_TRUE(legacy.uplinks[i].start_ns == with_def.uplinks[i].start_ns);
        CHECK_TRUE(legacy.uplinks[i].dr == with_def.uplinks[i].dr);
        CHECK_TRUE(legacy.uplinks[i].power_index == with_def.uplinks[i].power_index);
        CHECK_TRUE(legacy.uplinks[i].answer_ok == with_def.uplinks[i].answer_ok);
        CHECK_TRUE(legacy.uplinks[i].outcome == with_def.uplinks[i].outcome);
    }
    const std::size_t nd = legacy.downlinks.size() < with_def.downlinks.size() ? legacy.downlinks.size() : with_def.downlinks.size();
    for (std::size_t i = 0; i < nd; ++i) {
        CHECK_TRUE(legacy.downlinks[i].commands == with_def.downlinks[i].commands);
        CHECK_TRUE(legacy.downlinks[i].delivered == with_def.downlinks[i].delivered);
        CHECK_TRUE(legacy.downlinks[i].start_ns == with_def.downlinks[i].start_ns);
    }
    // Statuts d'accusé et états terminaux : identiques entre le chemin sans configuration et le chemin explicite.
    CHECK_EQ(io_null.uplink_status.size(), io_def.uplink_status.size());
    for (std::size_t i = 0; i < io_null.uplink_status.size() && i < io_def.uplink_status.size(); ++i) {
        CHECK_EQ(static_cast<int>(io_null.uplink_status[i]), static_cast<int>(io_def.uplink_status[i]));
    }
    CHECK_EQ(io_null.terminals.size(), io_def.terminals.size());
    for (std::size_t i = 0; i < io_null.terminals.size() && i < io_def.terminals.size(); ++i) {
        CHECK_TRUE(io_null.terminals[i] == io_def.terminals[i]);
    }
}


// Sans ADR, aucune commande : l'état initial du terminal doit être exactement la configuration
// d'entrée, même quand la vue serveur diffère. La vue serveur ne doit pas être copiée dans le terminal.
void test_divergent_view_does_not_alter_initial_terminal_state() {
    const LoopChannelConfig c = make_cfg({0, 1, 2}, {0, 1, 2}, {0, 1});
    const std::vector<LoopChannelConfig> cfg = {c};
    Outcome o;
    run(&cfg, false, 30, o);
    CHECK_EQ(static_cast<int>(o.st), static_cast<int>(SimStatus::Ok));
    if (o.st != SimStatus::Ok) return;
    CHECK_TRUE(linkadr_downlinks(o, 0).empty());
    CHECK_EQ(o.io.terminals.size(), std::size_t{1});
    if (o.io.terminals.size() != 1) return;
    CHECK_TRUE(o.io.terminals[0].channels.enabled == c.device.enabled);   // {0,1,2}, pas {0,1}
    CHECK_TRUE(o.io.terminals[0].channels.defined(2));
    CHECK_TRUE(o.io.terminals[0].channels == c.device);
}

// Mapping du chemin v3 : `enabled` (terminal) et `server_defined` (vue serveur) sont deux champs
// distincts. Deux combinaisons non symétriques : la confusion de l'un avec l'autre est détectée.
void test_v3_mapping_enabled_and_server_view_are_distinct() {
    lsim_channel_device_v3 ch[2] = {
        element(0, LSIM_CHANNEL_PRESENT_YES, {0, 7, 8, 15}, {0, 7, 8, 15}, {0, 7}),
        element(1, LSIM_CHANNEL_PRESENT_YES, {0, 7, 8, 15}, {0}, {0, 7, 8, 15}),
    };
    lsim_closed_loop_v3_args a;
    std::memset(&a, 0, sizeof(a));
    a.channels = ch;
    a.channel_count = 2;
    a.device_count = 2;
    const std::vector<LoopChannelConfig> cfg = build_channel_configs(a);
    CHECK_EQ(cfg.size(), std::size_t{2});
    if (cfg.size() != 2) return;
    CHECK_TRUE(same_set(cfg[0].device.enabled, {0, 7, 8, 15}));
    CHECK_TRUE(same_set(cfg[0].server_view, {0, 7}));
    CHECK_TRUE(same_set(cfg[1].device.enabled, {0}));
    CHECK_TRUE(same_set(cfg[1].server_view, {0, 7, 8, 15}));
    CHECK_TRUE(cfg[0].device.defined(15) && cfg[1].device.defined(15));
}

}  // namespace

void run_closed_loop_v3_crossval_tests() {
    test_server_view_differs_from_terminal_with_adr();
    test_server_channel_undefined_on_terminal_refused_then_renegotiated();
    test_multi_device_distinct_explicit_configurations();
    test_mixed_configuration_present_zero_uses_defaults();
    test_historical_parity_three_paths();
    test_divergent_view_does_not_alter_initial_terminal_state();
    test_v3_mapping_enabled_and_server_view_are_distinct();
}
