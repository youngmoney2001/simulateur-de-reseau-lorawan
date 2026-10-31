// SPDX-License-Identifier: Apache-2.0
// Gel exécutable de l'ABI v1, v2, gw2 et v3 : static_assert de tailles et de décalages (contrat 6.1),
// signatures et codes de statut. Les tests de la fonction publique lsim_simulate_closed_loop_v3
// (appel réel, parité avec v2, erreurs, trace) sont dans core/tests/test_closed_loop_v3_api.cpp.
//
// Depuis F7, les tailles et décalages ne sont plus des littéraux LP64 : ils viennent de
// `abi_layout.cpp`, qui porte DEUX tables explicites (x86-64 et i386) et les vérifie pour les
// 53 structures de `lsim/c_api.h`. Ce fichier l'inclut pour partager une seule source de vérité
// (la phase F7 n'autorise que ces deux fichiers, d'où l'absence d'en-tête séparé).
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <limits>
#include <type_traits>

#include "abi_layout.cpp"  // deux tables ABI + 453 vérifications de disposition
#include "check.hpp"
#include "lsim/c_api.h"
#include "lsim/engine.hpp"
#include "lsim/closed_loop_v3_validate.hpp"
#include "lsim/loop_adr.hpp"

namespace {

// Signatures figées. Le type de pointeur est écrit à la main : si l'en-tête change, la compilation échoue.
using ClosedLoopV1 = int32_t (*)(const lsim_end_device*, size_t, const lsim_plan_device*,
                                 const lsim_loop_region*, const lsim_gateway*, const lsim_propagation*,
                                 const lsim_environment*, const lsim_loop_options*, lsim_device_stats*,
                                 lsim_sim_stats*, lsim_loop_uplink*, size_t, size_t*, lsim_loop_downlink*,
                                 size_t, size_t*, lsim_interval*, size_t, size_t*);

using ClosedLoopV2 = int32_t (*)(const lsim_end_device*, size_t, const lsim_plan_device*,
                                 const lsim_loop_region*, const lsim_gateway*, const lsim_propagation*,
                                 const lsim_environment*, const lsim_loop_options*, const lsim_loop_mac*,
                                 size_t, lsim_device_stats*, lsim_sim_stats*, lsim_loop_uplink*, size_t,
                                 size_t*, lsim_loop_downlink*, size_t, size_t*, lsim_interval*, size_t,
                                 size_t*, lsim_loop_mac_counters*);

using ClosedLoopGw2 = int32_t (*)(const lsim_end_device*, size_t, const lsim_plan_device*,
                                  const lsim_loop_region*, const lsim_gateway_v2*, const lsim_propagation*,
                                  const lsim_environment*, const lsim_loop_options*, const lsim_loop_mac*,
                                  size_t, lsim_device_stats*, lsim_sim_stats*, lsim_loop_uplink*, size_t,
                                  size_t*, lsim_loop_downlink*, size_t, size_t*, lsim_interval*, size_t,
                                  size_t*, lsim_loop_mac_counters*);

static_assert(std::is_same<decltype(&lsim_simulate_closed_loop_v1), ClosedLoopV1>::value,
              "signature de lsim_simulate_closed_loop_v1 modifiée");
static_assert(std::is_same<decltype(&lsim_simulate_closed_loop_v2), ClosedLoopV2>::value,
              "signature de lsim_simulate_closed_loop_v2 modifiée");
static_assert(std::is_same<decltype(&lsim_simulate_closed_loop_gw2), ClosedLoopGw2>::value,
              "signature de lsim_simulate_closed_loop_gw2 modifiée");
static_assert(std::is_same<decltype(&lsim_version), uint32_t (*)(void)>::value,
              "signature de lsim_version modifiée");

// Layouts (taille, décalages des champs publics) : constantes issues de la table de l'ABI
// courante (`abi_layout::expected`), plus aucune valeur LP64 codée en dur.
namespace exp = abi_layout::expected;
static_assert(sizeof(lsim_plan_device) == exp::size_lsim_plan_device &&
                  offsetof(lsim_plan_device, rx1_sf) == exp::off_lsim_plan_device__rx1_sf,
              "lsim_plan_device");
static_assert(sizeof(lsim_plan_options) == exp::size_lsim_plan_options &&
                  offsetof(lsim_plan_options, device_rx_offset_db) ==
                      exp::off_lsim_plan_options__device_rx_offset_db,
              "lsim_plan_options");
static_assert(sizeof(lsim_loop_region) == exp::size_lsim_loop_region &&
                  offsetof(lsim_loop_region, duty_limit) == exp::off_lsim_loop_region__duty_limit,
              "lsim_loop_region");
static_assert(offsetof(lsim_loop_region, max_dr) == exp::off_lsim_loop_region__max_dr &&
                  offsetof(lsim_loop_region, power_step_tenth_db) ==
                      exp::off_lsim_loop_region__power_step_tenth_db,
              "lsim_loop_region : décalages des entiers");
static_assert(sizeof(lsim_loop_options) == exp::size_lsim_loop_options &&
                  offsetof(lsim_loop_options, adr) == exp::off_lsim_loop_options__adr &&
                  offsetof(lsim_loop_options, duty_cycle_exponent) ==
                      exp::off_lsim_loop_options__duty_cycle_exponent,
              "lsim_loop_options");
static_assert(sizeof(lsim_loop_mac) == exp::size_lsim_loop_mac &&
                  offsetof(lsim_loop_mac, flags) == exp::off_lsim_loop_mac__flags,
              "lsim_loop_mac");
static_assert(sizeof(lsim_loop_mac_counters) == exp::size_lsim_loop_mac_counters &&
                  offsetof(lsim_loop_mac_counters, pending_at_end) ==
                      exp::off_lsim_loop_mac_counters__pending_at_end,
              "lsim_loop_mac_counters");
static_assert(sizeof(lsim_loop_uplink) == exp::size_lsim_loop_uplink &&
                  offsetof(lsim_loop_uplink, rssi_dbm) == exp::off_lsim_loop_uplink__rssi_dbm &&
                  offsetof(lsim_loop_uplink, answer_ok) == exp::off_lsim_loop_uplink__answer_ok,
              "lsim_loop_uplink");
static_assert(sizeof(lsim_loop_downlink) == exp::size_lsim_loop_downlink &&
                  offsetof(lsim_loop_downlink, t_open_ns) == exp::off_lsim_loop_downlink__t_open_ns &&
                  offsetof(lsim_loop_downlink, req_power_index) ==
                      exp::off_lsim_loop_downlink__req_power_index,
              "lsim_loop_downlink");
static_assert(sizeof(lsim_gateway) == exp::size_lsim_gateway &&
                  offsetof(lsim_gateway, antenna_gain_dbi) == exp::off_lsim_gateway__antenna_gain_dbi,
              "lsim_gateway");
static_assert(sizeof(lsim_gateway_v2) == exp::size_lsim_gateway_v2 &&
                  offsetof(lsim_gateway_v2, sensitivity_model) ==
                      exp::off_lsim_gateway_v2__sensitivity_model &&
                  offsetof(lsim_gateway_v2, present) == exp::off_lsim_gateway_v2__present &&
                  offsetof(lsim_gateway_v2, sensitivity_dbm) ==
                      exp::off_lsim_gateway_v2__sensitivity_dbm,
              "lsim_gateway_v2");
static_assert(sizeof(lsim_end_device) == exp::size_lsim_end_device, "lsim_end_device");
static_assert(sizeof(lsim_propagation) == exp::size_lsim_propagation, "lsim_propagation");
static_assert(sizeof(lsim_device_stats) == exp::size_lsim_device_stats, "lsim_device_stats");
static_assert(sizeof(lsim_sim_stats) == exp::size_lsim_sim_stats, "lsim_sim_stats");
static_assert(sizeof(lsim_interval) == exp::size_lsim_interval, "lsim_interval");
static_assert(sizeof(lsim_mac_reservation) == exp::size_lsim_mac_reservation &&
                  offsetof(lsim_mac_reservation, extra_bytes) ==
                      exp::off_lsim_mac_reservation__extra_bytes,
              "lsim_mac_reservation");

// Bases de statut historiques. MESH et CLASSB partagent 800 : chevauchement historique, conservé
// (arbitrage A7 : ne pas corriger avant migration explicite).
static_assert(LSIM_STATUS_CRYPTO_BASE == 100 && LSIM_STATUS_SECURE_BASE == 200 &&
                  LSIM_STATUS_FRAME_BASE == 250 && LSIM_STATUS_JOIN_BASE == 400 &&
                  LSIM_STATUS_ENV_BASE == 500 && LSIM_STATUS_REGISTRY_BASE == 700 &&
                  LSIM_STATUS_MAC_BASE == 600 && LSIM_STATUS_REJOIN_BASE == 650 &&
                  LSIM_STATUS_ADR_BASE == 760 && LSIM_STATUS_SESSION_BASE == 780 &&
                  LSIM_STATUS_SIM_BASE == 300 && LSIM_STATUS_PLAN_BASE == 950 &&
                  LSIM_STATUS_INTERNAL == 900,
              "bases de statut historiques modifiées");
static_assert(LSIM_STATUS_MESH_BASE == LSIM_STATUS_CLASSB_BASE,
              "chevauchement historique MESH / CLASSB (800) : à conserver jusqu'à migration");

// ---- ABI v3 (étape 6.2.1) : dispositions, sentinelles et valeurs reprises des énumérations moteur.
// Les tailles et décalages suivent la table de l'ABI compilée (x86-64 ou i386).
static_assert(sizeof(lsim_channel_device_v3) == exp::size_lsim_channel_device_v3, "lsim_channel_device_v3 : taille de la table ABI");
static_assert(offsetof(lsim_channel_device_v3, device_index) == exp::off_lsim_channel_device_v3__device_index && offsetof(lsim_channel_device_v3, present) == exp::off_lsim_channel_device_v3__present,
              "lsim_channel_device_v3 : décalages d'en-tête");
static_assert(offsetof(lsim_channel_device_v3, dr_mask) == exp::off_lsim_channel_device_v3__dr_mask && offsetof(lsim_channel_device_v3, enabled) == exp::off_lsim_channel_device_v3__enabled &&
                  offsetof(lsim_channel_device_v3, server_defined) == exp::off_lsim_channel_device_v3__server_defined &&
                  offsetof(lsim_channel_device_v3, reserved) == exp::off_lsim_channel_device_v3__reserved,
              "lsim_channel_device_v3 : décalages des champs de canaux");

static_assert(sizeof(lsim_channel_terminal_v3) == exp::size_lsim_channel_terminal_v3, "lsim_channel_terminal_v3 : taille de la table ABI");
static_assert(offsetof(lsim_channel_terminal_v3, dr) == exp::off_lsim_channel_terminal_v3__dr && offsetof(lsim_channel_terminal_v3, power_index) == exp::off_lsim_channel_terminal_v3__power_index &&
                  offsetof(lsim_channel_terminal_v3, reserved0) == exp::off_lsim_channel_terminal_v3__reserved0 && offsetof(lsim_channel_terminal_v3, dr_mask) == exp::off_lsim_channel_terminal_v3__dr_mask &&
                  offsetof(lsim_channel_terminal_v3, enabled) == exp::off_lsim_channel_terminal_v3__enabled && offsetof(lsim_channel_terminal_v3, reserved1) == exp::off_lsim_channel_terminal_v3__reserved1,
              "lsim_channel_terminal_v3 : décalages");

static_assert(sizeof(lsim_loop_trace_v3) == exp::size_lsim_loop_trace_v3, "lsim_loop_trace_v3 : taille de la table ABI");
static_assert(offsetof(lsim_loop_trace_v3, t_ns) == exp::off_lsim_loop_trace_v3__t_ns && offsetof(lsim_loop_trace_v3, device) == exp::off_lsim_loop_trace_v3__device &&
                  offsetof(lsim_loop_trace_v3, uplink) == exp::off_lsim_loop_trace_v3__uplink && offsetof(lsim_loop_trace_v3, downlink) == exp::off_lsim_loop_trace_v3__downlink &&
                  offsetof(lsim_loop_trace_v3, kind) == exp::off_lsim_loop_trace_v3__kind && offsetof(lsim_loop_trace_v3, origin) == exp::off_lsim_loop_trace_v3__origin &&
                  offsetof(lsim_loop_trace_v3, action) == exp::off_lsim_loop_trace_v3__action && offsetof(lsim_loop_trace_v3, target) == exp::off_lsim_loop_trace_v3__target &&
                  offsetof(lsim_loop_trace_v3, loss) == exp::off_lsim_loop_trace_v3__loss && offsetof(lsim_loop_trace_v3, status) == exp::off_lsim_loop_trace_v3__status &&
                  offsetof(lsim_loop_trace_v3, dr) == exp::off_lsim_loop_trace_v3__dr && offsetof(lsim_loop_trace_v3, power_index) == exp::off_lsim_loop_trace_v3__power_index &&
                  offsetof(lsim_loop_trace_v3, channel_mask) == exp::off_lsim_loop_trace_v3__channel_mask && offsetof(lsim_loop_trace_v3, value) == exp::off_lsim_loop_trace_v3__value &&
                  offsetof(lsim_loop_trace_v3, flag) == exp::off_lsim_loop_trace_v3__flag && offsetof(lsim_loop_trace_v3, reason_channel) == exp::off_lsim_loop_trace_v3__reason_channel &&
                  offsetof(lsim_loop_trace_v3, reason_dr) == exp::off_lsim_loop_trace_v3__reason_dr && offsetof(lsim_loop_trace_v3, reason_power) == exp::off_lsim_loop_trace_v3__reason_power &&
                  offsetof(lsim_loop_trace_v3, reserved) == exp::off_lsim_loop_trace_v3__reserved,
              "lsim_loop_trace_v3 : décalages");

static_assert(sizeof(lsim_closed_loop_v3_args) == exp::size_lsim_closed_loop_v3_args, "lsim_closed_loop_v3_args : taille de la table ABI");
static_assert(offsetof(lsim_closed_loop_v3_args, reserved1) == exp::off_lsim_closed_loop_v3_args__reserved1 && offsetof(lsim_closed_loop_v3_args, devices) == exp::off_lsim_closed_loop_v3_args__devices &&
                  offsetof(lsim_closed_loop_v3_args, mac) == exp::off_lsim_closed_loop_v3_args__mac && offsetof(lsim_closed_loop_v3_args, channels) == exp::off_lsim_closed_loop_v3_args__channels &&
                  offsetof(lsim_closed_loop_v3_args, channel_count) == exp::off_lsim_closed_loop_v3_args__channel_count &&
                  offsetof(lsim_closed_loop_v3_args, mac_counters) == exp::off_lsim_closed_loop_v3_args__mac_counters &&
                  offsetof(lsim_closed_loop_v3_args, trace) == exp::off_lsim_closed_loop_v3_args__trace &&
                  offsetof(lsim_closed_loop_v3_args, trace_count) == exp::off_lsim_closed_loop_v3_args__trace_count &&
                  offsetof(lsim_closed_loop_v3_args, terminals) == exp::off_lsim_closed_loop_v3_args__terminals &&
                  offsetof(lsim_closed_loop_v3_args, terminal_count) == exp::off_lsim_closed_loop_v3_args__terminal_count,
              "lsim_closed_loop_v3_args : décalages");

// Codes de statut : base 1000, offsets +1 à +21 consécutifs.
static_assert(LSIM_STATUS_CHANNEL_BASE == 1000, "base des codes canal");
static_assert(LSIM_STATUS_CHANNEL_ARGS_SIZE == 1001 && LSIM_STATUS_CHANNEL_MISALIGNED == 1021 &&
                  LSIM_STATUS_CHANNEL_RANGE_OVERFLOW == 1020 && LSIM_STATUS_CHANNEL_NULL_POINTER == 1019 &&
                  LSIM_STATUS_CHANNEL_BUFFERS_ALIASED == 1018 && LSIM_STATUS_CHANNEL_TERMINAL_BUFFER_TOO_SMALL == 1017 &&
                  LSIM_STATUS_CHANNEL_TRACE_BUFFER_TOO_SMALL == 1016 && LSIM_STATUS_CHANNEL_TRACE_MODE == 1015,
              "codes de statut canal");

// Modes et sentinelles.
static_assert(LSIM_CHANNEL_PLAN_NONE == 0 && LSIM_CHANNEL_PLAN_EU868_RP002_1_0_5 == 1, "plans de canaux");
static_assert(LSIM_CHANNEL_PRESENT_NO == 0 && LSIM_CHANNEL_PRESENT_YES == 1, "drapeau present");
static_assert(LSIM_CHANNEL_ENGINE_MAX == lsim::sim::kLoopMaxChannels, "80 emplacements = kLoopMaxChannels");
static_assert(LSIM_CHANNEL_SUPPORTED_MAX == 16, "16 canaux supportés par le moteur");
static_assert(LSIM_TRACE_NO_INDEX == lsim::sim::kLoopNoIndex, "sentinelle d'index");
static_assert(LSIM_TRACE_STATUS_NONE == 0xFF, "sentinelle de statut");
static_assert(LSIM_TRACE_FIELD_IGNORE == lsim::sim::kLoopFieldIgnore, "0xF = conserver");

// Valeurs numériques reprises des énumérations du moteur (aucune nouvelle valeur ABI).
static_assert(static_cast<unsigned>(lsim::sim::LoopTraceKind::Uplink) == LSIM_TRACE_KIND_UPLINK, "kind Uplink");
static_assert(static_cast<unsigned>(lsim::sim::LoopTraceKind::LinkAdrAns) == LSIM_TRACE_KIND_LINK_ADR_ANS, "kind LinkAdrAns");
static_assert(static_cast<unsigned>(lsim::sim::LoopTraceKind::Exclusion) == LSIM_TRACE_KIND_EXCLUSION, "kind Exclusion");
static_assert(static_cast<unsigned>(lsim::sim::LoopTraceKind::AdrDecision) == LSIM_TRACE_KIND_ADR_DECISION, "kind AdrDecision");
static_assert(static_cast<unsigned>(lsim::sim::LoopTraceKind::LinkAdrReq) == LSIM_TRACE_KIND_LINK_ADR_REQ, "kind LinkAdrReq");
static_assert(static_cast<unsigned>(lsim::sim::LoopTraceKind::Downlink) == LSIM_TRACE_KIND_DOWNLINK, "kind Downlink");
static_assert(static_cast<unsigned>(lsim::sim::LoopTraceKind::Apply) == LSIM_TRACE_KIND_APPLY, "kind Apply");

static_assert(static_cast<unsigned>(lsim::sim::LoopTraceOrigin::Normative) == LSIM_TRACE_ORIGIN_NORMATIVE, "origin");
static_assert(static_cast<unsigned>(lsim::sim::LoopTraceOrigin::SimulatorPolicy) == LSIM_TRACE_ORIGIN_SIMULATOR_POLICY, "origin");
static_assert(static_cast<unsigned>(lsim::sim::LoopTraceOrigin::Radio) == LSIM_TRACE_ORIGIN_RADIO, "origin");

static_assert(static_cast<unsigned>(lsim::sim::LoopTraceAction::Created) == LSIM_TRACE_ACTION_CREATED, "action");
static_assert(static_cast<unsigned>(lsim::sim::LoopTraceAction::Renewed) == LSIM_TRACE_ACTION_RENEWED, "action");
static_assert(static_cast<unsigned>(lsim::sim::LoopTraceAction::Expired) == LSIM_TRACE_ACTION_EXPIRED, "action");

static_assert(static_cast<unsigned>(lsim::sim::LoopExclusionTarget::DataRate) == LSIM_TRACE_TARGET_DATA_RATE, "target");
static_assert(static_cast<unsigned>(lsim::sim::LoopExclusionTarget::Power) == LSIM_TRACE_TARGET_POWER, "target");
static_assert(static_cast<unsigned>(lsim::sim::LoopExclusionTarget::Channel) == LSIM_TRACE_TARGET_CHANNEL, "target");
static_assert(static_cast<unsigned>(lsim::sim::LoopExclusionTarget::Mask) == LSIM_TRACE_TARGET_MASK, "target");

static_assert(static_cast<unsigned>(lsim::sim::LoopDownlinkLoss::None) == LSIM_TRACE_LOSS_NONE, "loss");
static_assert(static_cast<unsigned>(lsim::sim::LoopDownlinkLoss::DeviceTransmitting) == LSIM_TRACE_LOSS_DEVICE_TRANSMITTING, "loss");
static_assert(static_cast<unsigned>(lsim::sim::LoopDownlinkLoss::NoGatewaySlot) == LSIM_TRACE_LOSS_NO_GATEWAY_SLOT, "loss");
static_assert(static_cast<unsigned>(lsim::sim::LoopDownlinkLoss::BelowSensitivity) == LSIM_TRACE_LOSS_BELOW_SENSITIVITY, "loss");

static_assert(static_cast<unsigned>(lsim::sim::LoopChannelReason::Ok) == LSIM_TRACE_CHANNEL_REASON_OK, "reason canal");
static_assert(static_cast<unsigned>(lsim::sim::LoopChannelReason::RfuCntl) == LSIM_TRACE_CHANNEL_REASON_RFU_CNTL, "reason canal");
static_assert(static_cast<unsigned>(lsim::sim::LoopChannelReason::UndefinedChannel) == LSIM_TRACE_CHANNEL_REASON_UNDEFINED_CHANNEL, "reason canal");
static_assert(static_cast<unsigned>(lsim::sim::LoopChannelReason::AllDisabled) == LSIM_TRACE_CHANNEL_REASON_ALL_DISABLED, "reason canal");
static_assert(static_cast<unsigned>(lsim::sim::LoopChannelReason::IncompatibleWithDataRate) == LSIM_TRACE_CHANNEL_REASON_INCOMPATIBLE_WITH_DATA_RATE, "reason canal");
static_assert(static_cast<unsigned>(lsim::sim::LoopChannelReason::RfuBits) == LSIM_TRACE_CHANNEL_REASON_RFU_BITS, "reason canal");

static_assert(static_cast<unsigned>(lsim::sim::LoopDataRateReason::Ok) == LSIM_TRACE_DR_REASON_OK, "reason DR");
static_assert(static_cast<unsigned>(lsim::sim::LoopDataRateReason::Ignored) == LSIM_TRACE_DR_REASON_IGNORED, "reason DR");
static_assert(static_cast<unsigned>(lsim::sim::LoopDataRateReason::UnknownDr) == LSIM_TRACE_DR_REASON_UNKNOWN_DR, "reason DR");
static_assert(static_cast<unsigned>(lsim::sim::LoopDataRateReason::NotSupportedByChannels) == LSIM_TRACE_DR_REASON_NOT_SUPPORTED_BY_CHANNELS, "reason DR");

static_assert(static_cast<unsigned>(lsim::sim::LoopPowerReason::Ok) == LSIM_TRACE_POWER_REASON_OK, "reason puissance");
static_assert(static_cast<unsigned>(lsim::sim::LoopPowerReason::Ignored) == LSIM_TRACE_POWER_REASON_IGNORED, "reason puissance");
static_assert(static_cast<unsigned>(lsim::sim::LoopPowerReason::Reserved) == LSIM_TRACE_POWER_REASON_RESERVED, "reason puissance");

}  // namespace

namespace {

using lsim::sim::abi_v3::validate_closed_loop_v3_args;

// Jeu d'arguments valide (EU868 explicite, 2 dispositifs, trace activée). Tous les tableaux sont
// distincts : les cas de chevauchement modifient ensuite un pointeur seulement.
struct Fixture {
    lsim_end_device devices[2];
    lsim_plan_device radios[2];
    lsim_loop_region regions[2];
    lsim_gateway_v2 gateway;
    lsim_propagation prop;
    lsim_loop_options options;
    alignas(8) lsim_loop_mac mac[1];
    alignas(8) lsim_channel_device_v3 channels[2];
    lsim_device_stats per_device[2];
    lsim_sim_stats totals;
    lsim_loop_mac_counters mac_counters;
    lsim_loop_uplink uplinks[4];
    size_t uplink_count;
    lsim_loop_downlink downlinks[4];
    size_t downlink_count;
    lsim_interval busy[4];
    size_t busy_count;
    lsim_loop_trace_v3 trace[4];
    size_t trace_count;
    alignas(8) lsim_channel_terminal_v3 terminals[3];
    size_t terminal_count;
    alignas(8) lsim_closed_loop_v3_args args;

    Fixture() {
        std::memset(this, 0, sizeof(*this));
        for (size_t i = 0; i < 2; ++i) {
            channels[i].struct_size = sizeof(lsim_channel_device_v3);
            channels[i].abi_version = 3;
            channels[i].device_index = static_cast<std::uint32_t>(i);
            channels[i].present = 1;
            for (std::size_t c = 0; c < 3; ++c) channels[i].dr_mask[c] = 0x3F;   // DR0..DR5
            channels[i].enabled[0] = 0x07;                                      // canaux 0..2
            channels[i].server_defined[0] = 0x07;
            for (std::size_t k = 0; k < 6; ++k) regions[i].dr_sf[k] = static_cast<std::uint8_t>(12 - k);
            regions[i].max_dr = 5;
        }
        args.struct_size = sizeof(lsim_closed_loop_v3_args);
        args.abi_version = 3;
        args.channel_plan = LSIM_CHANNEL_PLAN_EU868_RP002_1_0_5;
        args.trace_enabled = 1;
        args.trace_element_size = sizeof(lsim_loop_trace_v3);
        args.terminal_element_size = sizeof(lsim_channel_terminal_v3);
        args.devices = devices;
        args.device_count = 2;
        args.radios = radios;
        args.regions = regions;
        args.gateway = &gateway;
        args.prop = &prop;
        args.options = &options;
        args.mac = nullptr;
        args.mac_count = 0;
        args.channels = channels;
        args.channel_count = 2;
        args.per_device = per_device;
        args.totals = &totals;
        args.uplinks = uplinks;
        args.uplink_capacity = 4;
        args.uplink_count = &uplink_count;
        args.downlinks = downlinks;
        args.downlink_capacity = 4;
        args.downlink_count = &downlink_count;
        args.busy = busy;
        args.busy_capacity = 4;
        args.busy_count = &busy_count;
        args.mac_counters = &mac_counters;
        args.trace = trace;
        args.trace_capacity = 4;
        args.trace_count = &trace_count;
        args.terminals = terminals;
        args.terminal_capacity = 2;
        args.terminal_count = &terminal_count;
    }
};

void expect(const Fixture& f, std::int32_t code) { CHECK_EQ(static_cast<int>(validate_closed_loop_v3_args(&f.args)), static_cast<int>(code)); }

void test_valid_arguments_accepted() {
    Fixture f;
    expect(f, 0);
    // Mode historique : plan NONE, pas de canaux ; trace désactivée sans buffer.
    Fixture h;
    h.args.channel_plan = LSIM_CHANNEL_PLAN_NONE;
    h.args.channels = nullptr;
    h.args.channel_count = 0;
    h.args.trace_enabled = 0;
    h.args.trace = nullptr;
    h.args.trace_capacity = 0;
    expect(h, 0);
    // Buffers terminaux « non demandés » : NULL + 0, ou non NULL + 0.
    Fixture t;
    t.args.terminals = nullptr;
    t.args.terminal_capacity = 0;
    expect(t, 0);
    t.args.terminals = t.terminals;
    t.args.terminal_capacity = 0;
    expect(t, 0);
    // Capacité terminal exactement égale à device_count ; capacité plus grande acceptée.
    Fixture big;
    big.args.terminal_capacity = 3;
    expect(big, 0);
    // Canaux sans trace : pas de buffer trace requis.
    Fixture nt;
    nt.args.trace_enabled = 0;
    nt.args.trace = nullptr;
    nt.args.trace_capacity = 0;
    expect(nt, 0);
    // Zéro dispositif : pas de tableaux par dispositif, configuration historique.
    Fixture z;
    z.args.device_count = 0;
    z.args.channel_plan = LSIM_CHANNEL_PLAN_NONE;
    z.args.channels = nullptr;
    z.args.channel_count = 0;
    z.args.devices = nullptr;
    z.args.radios = nullptr;
    z.args.regions = nullptr;
    z.args.per_device = nullptr;
    z.args.terminals = nullptr;
    z.args.terminal_capacity = 0;
    expect(z, 0);
}

void test_header_and_mode_errors() {
    Fixture a;
    a.args.struct_size = 271;
    expect(a, LSIM_STATUS_CHANNEL_ARGS_SIZE);
    Fixture b;
    b.args.abi_version = 2;
    expect(b, LSIM_STATUS_CHANNEL_ABI_VERSION);
    Fixture c;
    c.args.trace_element_size = 39;
    expect(c, LSIM_STATUS_CHANNEL_ELEMENT_SIZE);
    Fixture d;
    d.args.terminal_element_size = 0;
    expect(d, LSIM_STATUS_CHANNEL_ELEMENT_SIZE);
    Fixture e;
    e.args.reserved0 = 1;
    expect(e, LSIM_STATUS_CHANNEL_RESERVED_NONZERO);
    Fixture g;
    g.args.reserved1 = 7;
    expect(g, LSIM_STATUS_CHANNEL_RESERVED_NONZERO);
    Fixture p;
    p.args.channel_plan = 2;
    expect(p, LSIM_STATUS_CHANNEL_PLAN);
    // Mode : plan EU868 sans canaux, plan NONE avec canaux, nombre d'éléments différent, aucun dispositif.
    Fixture m1;
    m1.args.channels = nullptr;
    m1.args.channel_count = 0;
    expect(m1, LSIM_STATUS_CHANNEL_MODE);
    Fixture m2;
    m2.args.channel_plan = LSIM_CHANNEL_PLAN_NONE;
    expect(m2, LSIM_STATUS_CHANNEL_MODE);
    Fixture m3;
    m3.args.channel_count = 1;
    expect(m3, LSIM_STATUS_CHANNEL_MODE);
    Fixture m4;
    m4.args.device_count = 0;
    m4.args.channel_count = 0;
    expect(m4, LSIM_STATUS_CHANNEL_MODE);
    // Trace : mode invalide, buffer présent alors que désactivée (A10), capacité sans buffer.
    Fixture t1;
    t1.args.trace_enabled = 2;
    expect(t1, LSIM_STATUS_CHANNEL_TRACE_MODE);
    Fixture t2;
    t2.args.trace_enabled = 0;
    expect(t2, LSIM_STATUS_CHANNEL_TRACE_MODE);
    Fixture t3;
    t3.args.trace_enabled = 0;
    t3.args.trace = nullptr;
    t3.args.trace_capacity = 1;
    expect(t3, LSIM_STATUS_CHANNEL_TRACE_MODE);
    // Limite historique de dispositifs (SIM + TooManyDevices), atteinte avant les pointeurs.
    Fixture many;
    many.args.device_count = lsim::sim::kMaxEndDevices + 1;
    many.args.channel_plan = LSIM_CHANNEL_PLAN_NONE;
    many.args.channels = nullptr;
    many.args.channel_count = 0;
    expect(many, LSIM_STATUS_SIM_BASE + static_cast<std::int32_t>(lsim::sim::SimStatus::TooManyDevices));
    // Ordre : une taille d'en-tête fausse prime sur un pointeur nul.
    Fixture order;
    order.args.struct_size = 1;
    order.args.uplinks = nullptr;
    expect(order, LSIM_STATUS_CHANNEL_ARGS_SIZE);
}

void test_pointer_requirements() {
    struct Case {
        const char* name;
        void (*mutate)(Fixture&);
    };
    const Case cases[] = {
        {"gateway", [](Fixture& f) { f.args.gateway = nullptr; }},
        {"prop", [](Fixture& f) { f.args.prop = nullptr; }},
        {"totals", [](Fixture& f) { f.args.totals = nullptr; }},
        {"options", [](Fixture& f) { f.args.options = nullptr; }},
        {"uplinks", [](Fixture& f) { f.args.uplinks = nullptr; }},
        {"downlinks", [](Fixture& f) { f.args.downlinks = nullptr; }},
        {"busy", [](Fixture& f) { f.args.busy = nullptr; }},
        {"uplink_count", [](Fixture& f) { f.args.uplink_count = nullptr; }},
        {"downlink_count", [](Fixture& f) { f.args.downlink_count = nullptr; }},
        {"busy_count", [](Fixture& f) { f.args.busy_count = nullptr; }},
        {"trace_count", [](Fixture& f) { f.args.trace_count = nullptr; }},
        {"terminal_count", [](Fixture& f) { f.args.terminal_count = nullptr; }},
        {"devices", [](Fixture& f) { f.args.devices = nullptr; }},
        {"radios", [](Fixture& f) { f.args.radios = nullptr; }},
        {"regions", [](Fixture& f) { f.args.regions = nullptr; }},
        {"per_device", [](Fixture& f) { f.args.per_device = nullptr; }},
        {"mac absent avec mac_count", [](Fixture& f) { f.args.mac = nullptr; f.args.mac_count = 1; }},
        {"trace absent avec trace activée", [](Fixture& f) { f.args.trace = nullptr; }},
        {"terminaux absents avec capacité", [](Fixture& f) { f.args.terminals = nullptr; }},
    };
    for (const Case& c : cases) {
        Fixture f;
        c.mutate(f);
        // Le code attendu est NULL_POINTER pour tous ces cas.
        CHECK_EQ(static_cast<int>(validate_closed_loop_v3_args(&f.args)), static_cast<int>(LSIM_STATUS_CHANNEL_NULL_POINTER));
        (void)c.name;
    }
    // Pointeur d'arguments nul.
    CHECK_EQ(static_cast<int>(validate_closed_loop_v3_args(nullptr)), static_cast<int>(LSIM_STATUS_CHANNEL_NULL_POINTER));
    // Sans dispositif, devices/radios/regions/per_device peuvent être nuls.
    Fixture z;
    z.args.device_count = 0;
    z.args.channel_plan = LSIM_CHANNEL_PLAN_NONE;
    z.args.channels = nullptr;
    z.args.channel_count = 0;
    z.args.devices = nullptr;
    z.args.radios = nullptr;
    z.args.regions = nullptr;
    z.args.per_device = nullptr;
    expect(z, 0);
    // Environnement optionnel.
    Fixture env;
    env.args.channel_plan = LSIM_CHANNEL_PLAN_NONE;
    env.args.channels = nullptr;
    env.args.channel_count = 0;
    env.args.trace_enabled = 0;
    env.args.trace = nullptr;
    env.args.trace_capacity = 0;
    env.args.env = nullptr;
    expect(env, 0);
}

void test_terminal_buffer_rules() {
    // Capacité terminale insuffisante : contrôlée après simulation (6.2.5), pas par le validateur.
    Fixture small;
    small.args.terminal_capacity = 1;   // device_count = 2
    expect(small, 0);
    Fixture nullbuf;
    nullbuf.args.terminals = nullptr;
    nullbuf.args.terminal_capacity = 2;
    expect(nullbuf, LSIM_STATUS_CHANNEL_NULL_POINTER);
}

void test_element_size_and_range_errors() {
    // Débordement : capacité telle que capacité × taille dépasse l'espace d'adressage.
    Fixture of;
    of.args.uplink_capacity = std::numeric_limits<std::size_t>::max() / sizeof(lsim_loop_uplink) + 1;
    expect(of, LSIM_STATUS_CHANNEL_RANGE_OVERFLOW);
    // Débordement d'adresse : début près de la fin de l'espace d'adressage.
    Fixture wrap;
    wrap.args.uplinks = reinterpret_cast<lsim_loop_uplink*>(static_cast<std::uintptr_t>(0xFFFFFFFFFFFFFFF8ULL));
    wrap.args.uplink_capacity = 1;
    expect(wrap, LSIM_STATUS_CHANNEL_RANGE_OVERFLOW);
    // Alignement : tableau d'uplinks décalé d'un octet.
    Fixture mis;
    mis.args.uplinks = reinterpret_cast<lsim_loop_uplink*>(reinterpret_cast<char*>(mis.uplinks) + 1);
    mis.args.uplink_capacity = 1;
    expect(mis, LSIM_STATUS_CHANNEL_MISALIGNED);
    // Alignement des arguments eux-mêmes : vérifié avant toute lecture de champ.
    Fixture arg;
    const lsim_closed_loop_v3_args* shifted = reinterpret_cast<const lsim_closed_loop_v3_args*>(reinterpret_cast<const char*>(&arg.args) + 1);
    CHECK_EQ(static_cast<int>(validate_closed_loop_v3_args(shifted)), static_cast<int>(LSIM_STATUS_CHANNEL_MISALIGNED));
    // Plages vides : un pointeur non nul de capacité 0 ne chevauche rien.
    Fixture empty;
    empty.args.uplinks = reinterpret_cast<lsim_loop_uplink*>(empty.devices);
    empty.args.uplink_capacity = 0;
    expect(empty, 0);
}

void test_overlap_rules() {
    Fixture uo;
    uo.args.uplinks = reinterpret_cast<lsim_loop_uplink*>(uo.devices);
    uo.args.uplink_capacity = 1;
    expect(uo, LSIM_STATUS_CHANNEL_BUFFERS_ALIASED);
    Fixture co;
    co.args.uplink_count = reinterpret_cast<size_t*>(co.uplinks);
    expect(co, LSIM_STATUS_CHANNEL_BUFFERS_ALIASED);
    Fixture ao;
    ao.args.uplinks = reinterpret_cast<lsim_loop_uplink*>(&ao.args);
    ao.args.uplink_capacity = 1;
    expect(ao, LSIM_STATUS_CHANNEL_BUFFERS_ALIASED);
    Fixture io;
    io.args.channels = io.channels;
    io.args.channel_count = 2;
    io.args.busy = reinterpret_cast<lsim_interval*>(io.channels);
    io.args.busy_capacity = 1;
    expect(io, LSIM_STATUS_CHANNEL_BUFFERS_ALIASED);
}

void test_mac_counters_optional() {
    // mac_counters est facultatif en v3 (convention v1/v2) : NULL accepté, fourni validé.
    Fixture absent;
    absent.args.mac_counters = nullptr;
    expect(absent, 0);
    Fixture present;
    expect(present, 0);
}

void test_channel_element_rules() {
    struct Case {
        std::int32_t code;
        void (*mutate)(lsim_channel_device_v3&);
    };
    const Case cases[] = {
        {LSIM_STATUS_CHANNEL_ELEMENT_SIZE, [](lsim_channel_device_v3& c) { c.struct_size = 127; }},
        {LSIM_STATUS_CHANNEL_ABI_VERSION, [](lsim_channel_device_v3& c) { c.abi_version = 2; }},
        {LSIM_STATUS_CHANNEL_PRESENT_FLAG, [](lsim_channel_device_v3& c) { c.present = 2; }},
        {LSIM_STATUS_CHANNEL_RESERVED_NONZERO, [](lsim_channel_device_v3& c) { c.reserved[0] = 1; }},
        {LSIM_STATUS_CHANNEL_INDEX_UNSUPPORTED, [](lsim_channel_device_v3& c) { c.dr_mask[16] = 1; }},
        {LSIM_STATUS_CHANNEL_INDEX_UNSUPPORTED, [](lsim_channel_device_v3& c) { c.dr_mask[79] = 1; }},
        {LSIM_STATUS_CHANNEL_INDEX_UNSUPPORTED, [](lsim_channel_device_v3& c) { c.enabled[2] = 1; }},
        {LSIM_STATUS_CHANNEL_INDEX_UNSUPPORTED, [](lsim_channel_device_v3& c) { c.server_defined[9] = 0x80; }},
        {LSIM_STATUS_CHANNEL_DR_MASK_INVALID, [](lsim_channel_device_v3& c) { c.dr_mask[0] = 0x40; }},
        {LSIM_STATUS_CHANNEL_DR_MASK_INVALID, [](lsim_channel_device_v3& c) { c.dr_mask[1] = 0x80; }},
        {LSIM_STATUS_CHANNEL_ENABLED_UNDEFINED, [](lsim_channel_device_v3& c) { c.enabled[0] |= 0x08; }},
        {LSIM_STATUS_CHANNEL_ENABLED_EMPTY, [](lsim_channel_device_v3& c) { c.enabled[0] = 0; }},
        {LSIM_STATUS_CHANNEL_SERVER_VIEW_EMPTY, [](lsim_channel_device_v3& c) { c.server_defined[0] = 0; }},
    };
    for (const Case& c : cases) {
        Fixture f;
        c.mutate(f.channels[0]);
        expect(f, c.code);
    }
    // Index de dispositif : hors plage et doublon.
    Fixture oor;
    oor.channels[0].device_index = 2;
    expect(oor, LSIM_STATUS_CHANNEL_DEVICE_INDEX);
    Fixture dup;
    dup.channels[1].device_index = 0;
    expect(dup, LSIM_STATUS_CHANNEL_DEVICE_INDEX);
    // Ordre des éléments libre : le dispositif 1 avant le dispositif 0 est valide.
    Fixture swap;
    swap.channels[0].device_index = 1;
    swap.channels[1].device_index = 0;
    expect(swap, 0);
    // present = 0 : configuration libre de zéro, sinon FIELDS_WITHOUT_PRESENT.
    Fixture absent;
    absent.channels[0].present = 0;
    std::memset(absent.channels[0].dr_mask, 0, sizeof(absent.channels[0].dr_mask));
    std::memset(absent.channels[0].enabled, 0, sizeof(absent.channels[0].enabled));
    std::memset(absent.channels[0].server_defined, 0, sizeof(absent.channels[0].server_defined));
    expect(absent, 0);
    Fixture absent_bad;
    absent_bad.channels[0].present = 0;
    expect(absent_bad, LSIM_STATUS_CHANNEL_FIELDS_WITHOUT_PRESENT);
    // Masques valides : DR0 seul, DR0..DR5 ; canal activé minimal.
    Fixture ok;
    ok.channels[0].dr_mask[0] = 0x01;
    ok.channels[0].enabled[0] = 0x01;
    expect(ok, 0);
    // Non-régression : un bit DR sans entrée dr_sf est accepté (le moteur l'accepte aussi).
    // Région avec max_dr = 6 et dr_sf[6] absent (0) ; le bit DR6 du canal 0 doit passer.
    Fixture no_sf;
    no_sf.regions[0].max_dr = 6;
    no_sf.regions[0].dr_sf[6] = 0;
    no_sf.channels[0].dr_mask[0] = 0x40;
    expect(no_sf, 0);
    // Bit au-delà de max_dr : toujours refusé.
    Fixture above;
    above.channels[0].dr_mask[0] = 0x40;   // DR6 avec max_dr = 5
    expect(above, LSIM_STATUS_CHANNEL_DR_MASK_INVALID);
}

void test_first_error_wins() {
    // Un canal invalide et un terminal trop petit : la validation des éléments de configuration
    // précède ; la capacité terminale n'est plus contrôlée avant la simulation (6.2.5).
    Fixture f;
    f.args.terminal_capacity = 1;
    f.channels[0].enabled[0] = 0;
    expect(f, LSIM_STATUS_CHANNEL_ENABLED_EMPTY);
}

void test_validation_writes_nothing() {
    // Aucune écriture pendant la validation, succès comme échec.
    Fixture f;
    std::memset(f.uplinks, 0xA5, sizeof(f.uplinks));
    std::memset(f.trace, 0x5A, sizeof(f.trace));
    std::memset(f.terminals, 0x3C, sizeof(f.terminals));
    std::memset(f.per_device, 0x66, sizeof(f.per_device));
    Fixture snapshot = f;
    std::memcpy(&snapshot, &f, sizeof(Fixture));
    const std::int32_t ok = validate_closed_loop_v3_args(&f.args);
    CHECK_EQ(static_cast<int>(ok), 0);
    CHECK_TRUE(std::memcmp(&snapshot, &f, sizeof(Fixture)) == 0);
    f.channels[0].enabled[0] = 0;
    const std::int32_t bad = validate_closed_loop_v3_args(&f.args);
    CHECK_EQ(static_cast<int>(bad), static_cast<int>(LSIM_STATUS_CHANNEL_ENABLED_EMPTY));
    CHECK_TRUE(std::memcmp(&snapshot, &f, sizeof(Fixture)) != 0);   // seule l'entrée a changé
    Fixture before = f;
    (void)validate_closed_loop_v3_args(&f.args);
    CHECK_TRUE(std::memcmp(&before, &f, sizeof(Fixture)) == 0);
    CHECK_EQ(static_cast<int>(f.uplink_count), 0);
    CHECK_EQ(static_cast<int>(f.trace_count), 0);
}

}  // namespace

namespace {

// Octet k d'un ensemble de canaux, en arithmétique pure (indépendante de l'ordre des octets de la machine) :
// l'octet k contient les canaux 8k..8k+7, bit 0 = canal 8k (LSB d'abord).
std::uint8_t set_byte(const lsim::sim::LoopChannelSet& s, std::size_t k) {
    return static_cast<std::uint8_t>((s.words[k / 8U] >> (8U * (k % 8U))) & 0xFFU);
}

}  // namespace

// Convention des bits de `enabled` et `server_defined` : canal c dans l'octet c / 8, bit c % 8.
// Canaux discriminants : 0, 7, 8, 15 (bords d'octets), 63/64 (bord de mots internes), 79 (dernier).
void test_channel_bit_order_matches_abi_bytes() {
    lsim::sim::LoopChannelSet s;
    for (std::size_t c : {0U, 7U, 8U, 15U}) s.set(c);
    CHECK_EQ(static_cast<int>(set_byte(s, 0)), 0x81);
    CHECK_EQ(static_cast<int>(set_byte(s, 1)), 0x81);
    for (std::size_t k = 2; k < 10; ++k) CHECK_EQ(static_cast<int>(set_byte(s, k)), 0);
    for (std::size_t c : {0U, 7U, 8U, 15U}) CHECK_TRUE(s.test(c));
    CHECK_TRUE(!s.test(1));
    CHECK_TRUE(!s.test(16));

    lsim::sim::LoopChannelSet t;
    t.set(63);
    t.set(64);
    t.set(79);
    CHECK_EQ(static_cast<int>(set_byte(t, 7)), 0x80);   // canal 63 : octet 7, bit 7
    CHECK_EQ(static_cast<int>(set_byte(t, 8)), 0x01);   // canal 64 : octet 8, bit 0
    CHECK_EQ(static_cast<int>(set_byte(t, 9)), 0x80);   // canal 79 : octet 9, bit 7
    for (std::size_t k = 0; k < 7; ++k) CHECK_EQ(static_cast<int>(set_byte(t, k)), 0);
    // Au-delà de 79 : ignoré par set(), aucun octet touché.
    lsim::sim::LoopChannelSet u;
    u.set(80);
    for (std::size_t k = 0; k < 10; ++k) CHECK_EQ(static_cast<int>(set_byte(u, k)), 0);
    // Réinitialisation : bit retiré exactement.
    t.reset(64);
    CHECK_EQ(static_cast<int>(set_byte(t, 8)), 0);
    CHECK_TRUE(t.test(63) && t.test(79));
}

// Code historique 302 = LSIM_STATUS_SIM_BASE + SimStatus::TooManyDevices, renvoyé par v2 sans
// lecture des entrées (la limite est testée avant la lecture des dispositifs).
void test_too_many_devices_code_302_historical() {
    static_assert(LSIM_STATUS_SIM_BASE + static_cast<int>(lsim::sim::SimStatus::TooManyDevices) == 302,
                  "302 = SIM + TooManyDevices");
    lsim_end_device devices[1]{};
    lsim_plan_device radios[1]{};
    lsim_loop_region regions[1]{};
    lsim_gateway gateway{};
    lsim_propagation prop{};
    lsim_loop_options options{};
    lsim_device_stats per_device[1]{};
    lsim_sim_stats totals{};
    lsim_loop_uplink uplinks[1]{};
    lsim_loop_downlink downlinks[1]{};
    lsim_interval busy[1]{};
    size_t uplink_count = 99, downlink_count = 99, busy_count = 99;
    const int32_t code = lsim_simulate_closed_loop_v2(
        devices, lsim::sim::kMaxEndDevices + 1, radios, regions, &gateway, &prop, nullptr, &options, nullptr, 0,
        per_device, &totals, uplinks, 1, &uplink_count, downlinks, 1, &downlink_count, busy, 1, &busy_count, nullptr);
    CHECK_EQ(static_cast<int>(code), 302);
}

// Pointeurs NULL à capacité 0 : uplinks, downlinks, busy et trace (trace activée) sont obligatoires ;
// terminals suit sa convention propre (NULL + capacité 0 = buffer non demandé).
void test_null_zero_capacity_rules() {
    Fixture u;
    u.args.uplinks = nullptr;
    u.args.uplink_capacity = 0;
    expect(u, LSIM_STATUS_CHANNEL_NULL_POINTER);
    Fixture d;
    d.args.downlinks = nullptr;
    d.args.downlink_capacity = 0;
    expect(d, LSIM_STATUS_CHANNEL_NULL_POINTER);
    Fixture b;
    b.args.busy = nullptr;
    b.args.busy_capacity = 0;
    expect(b, LSIM_STATUS_CHANNEL_NULL_POINTER);
    Fixture t;
    t.args.trace_enabled = 1;
    t.args.trace = nullptr;
    t.args.trace_capacity = 0;
    expect(t, LSIM_STATUS_CHANNEL_NULL_POINTER);
    Fixture term;
    term.args.terminals = nullptr;
    term.args.terminal_capacity = 0;
    expect(term, 0);
}

void run_abi_v3_prep_tests() {
    // Le compteur de version est encodé 0xMMmmpp : 0.1.0 pour l'ABI actuelle.
    CHECK_EQ(static_cast<int>(lsim_version()), 0x000100);
    // Les symboles v1, v2 et gw2 restent exportés et non nuls.
    CHECK_TRUE(&lsim_simulate_closed_loop_v1 != nullptr);
    CHECK_TRUE(&lsim_simulate_closed_loop_v2 != nullptr);
    CHECK_TRUE(&lsim_simulate_closed_loop_gw2 != nullptr);
    test_valid_arguments_accepted();
    test_header_and_mode_errors();
    test_pointer_requirements();
    test_null_zero_capacity_rules();
    test_terminal_buffer_rules();
    test_element_size_and_range_errors();
    test_overlap_rules();
    test_mac_counters_optional();
    test_channel_element_rules();
    test_first_error_wins();
    test_validation_writes_nothing();
    test_channel_bit_order_matches_abi_bytes();
    test_too_many_devices_code_302_historical();
}
