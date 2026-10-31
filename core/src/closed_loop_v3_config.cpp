// SPDX-License-Identifier: Apache-2.0
// Liaison interne entre la configuration canal v3 et le moteur (étape 6.2.3).
#include "lsim/closed_loop_v3_config.hpp"

#include <cstddef>
#include <cstdint>

#include "lsim/loop_adr.hpp"

namespace lsim::sim::abi_v3 {
namespace {

// Bit c d'un tableau d'octets LSB d'abord : octet c / 8, bit c % 8 (convention de l'ABI v3).
bool bit_at(const std::uint8_t* bytes, std::size_t channel) {
    return ((bytes[channel / 8U] >> (channel % 8U)) & 1U) != 0;
}

// Les valeurs numériques de la trace v3 sont gelées (contrat 6.1) : chaque énumération interne
// doit coïncider avec la constante publique. Toute divergence fait échouer la compilation.
static_assert(static_cast<std::uint8_t>(LoopTraceKind::Uplink) == LSIM_TRACE_KIND_UPLINK);
static_assert(static_cast<std::uint8_t>(LoopTraceKind::LinkAdrAns) == LSIM_TRACE_KIND_LINK_ADR_ANS);
static_assert(static_cast<std::uint8_t>(LoopTraceKind::Exclusion) == LSIM_TRACE_KIND_EXCLUSION);
static_assert(static_cast<std::uint8_t>(LoopTraceKind::AdrDecision) == LSIM_TRACE_KIND_ADR_DECISION);
static_assert(static_cast<std::uint8_t>(LoopTraceKind::LinkAdrReq) == LSIM_TRACE_KIND_LINK_ADR_REQ);
static_assert(static_cast<std::uint8_t>(LoopTraceKind::Downlink) == LSIM_TRACE_KIND_DOWNLINK);
static_assert(static_cast<std::uint8_t>(LoopTraceKind::Apply) == LSIM_TRACE_KIND_APPLY);
static_assert(static_cast<std::uint8_t>(LoopTraceOrigin::Normative) == LSIM_TRACE_ORIGIN_NORMATIVE);
static_assert(static_cast<std::uint8_t>(LoopTraceOrigin::SimulatorPolicy) == LSIM_TRACE_ORIGIN_SIMULATOR_POLICY);
static_assert(static_cast<std::uint8_t>(LoopTraceOrigin::Radio) == LSIM_TRACE_ORIGIN_RADIO);
static_assert(static_cast<std::uint8_t>(LoopTraceAction::Created) == LSIM_TRACE_ACTION_CREATED);
static_assert(static_cast<std::uint8_t>(LoopTraceAction::Renewed) == LSIM_TRACE_ACTION_RENEWED);
static_assert(static_cast<std::uint8_t>(LoopTraceAction::Expired) == LSIM_TRACE_ACTION_EXPIRED);
static_assert(static_cast<std::uint8_t>(LoopExclusionTarget::DataRate) == LSIM_TRACE_TARGET_DATA_RATE);
static_assert(static_cast<std::uint8_t>(LoopExclusionTarget::Power) == LSIM_TRACE_TARGET_POWER);
static_assert(static_cast<std::uint8_t>(LoopExclusionTarget::Channel) == LSIM_TRACE_TARGET_CHANNEL);
static_assert(static_cast<std::uint8_t>(LoopExclusionTarget::Mask) == LSIM_TRACE_TARGET_MASK);
static_assert(static_cast<std::uint8_t>(LoopDownlinkLoss::None) == LSIM_TRACE_LOSS_NONE);
static_assert(static_cast<std::uint8_t>(LoopDownlinkLoss::DeviceTransmitting) == LSIM_TRACE_LOSS_DEVICE_TRANSMITTING);
static_assert(static_cast<std::uint8_t>(LoopDownlinkLoss::NoGatewaySlot) == LSIM_TRACE_LOSS_NO_GATEWAY_SLOT);
static_assert(static_cast<std::uint8_t>(LoopDownlinkLoss::BelowSensitivity) == LSIM_TRACE_LOSS_BELOW_SENSITIVITY);
static_assert(static_cast<std::uint8_t>(LoopChannelReason::Ok) == LSIM_TRACE_CHANNEL_REASON_OK);
static_assert(static_cast<std::uint8_t>(LoopChannelReason::RfuCntl) == LSIM_TRACE_CHANNEL_REASON_RFU_CNTL);
static_assert(static_cast<std::uint8_t>(LoopChannelReason::UndefinedChannel) == LSIM_TRACE_CHANNEL_REASON_UNDEFINED_CHANNEL);
static_assert(static_cast<std::uint8_t>(LoopChannelReason::AllDisabled) == LSIM_TRACE_CHANNEL_REASON_ALL_DISABLED);
static_assert(static_cast<std::uint8_t>(LoopChannelReason::IncompatibleWithDataRate) ==
              LSIM_TRACE_CHANNEL_REASON_INCOMPATIBLE_WITH_DATA_RATE);
static_assert(static_cast<std::uint8_t>(LoopChannelReason::RfuBits) == LSIM_TRACE_CHANNEL_REASON_RFU_BITS);
static_assert(static_cast<std::uint8_t>(LoopDataRateReason::Ok) == LSIM_TRACE_DR_REASON_OK);
static_assert(static_cast<std::uint8_t>(LoopDataRateReason::Ignored) == LSIM_TRACE_DR_REASON_IGNORED);
static_assert(static_cast<std::uint8_t>(LoopDataRateReason::UnknownDr) == LSIM_TRACE_DR_REASON_UNKNOWN_DR);
static_assert(static_cast<std::uint8_t>(LoopDataRateReason::NotSupportedByChannels) ==
              LSIM_TRACE_DR_REASON_NOT_SUPPORTED_BY_CHANNELS);
static_assert(static_cast<std::uint8_t>(LoopPowerReason::Ok) == LSIM_TRACE_POWER_REASON_OK);
static_assert(static_cast<std::uint8_t>(LoopPowerReason::Ignored) == LSIM_TRACE_POWER_REASON_IGNORED);
static_assert(static_cast<std::uint8_t>(LoopPowerReason::Reserved) == LSIM_TRACE_POWER_REASON_RESERVED);
static_assert(kLoopNoIndex == LSIM_TRACE_NO_INDEX);
static_assert(kLoopFieldIgnore == LSIM_TRACE_FIELD_IGNORE);

// `status` : bits ACK pour LinkAdrAns et Apply, sentinelle sinon (contrat 6.1).
std::uint8_t status_field(const LoopTraceEvent& e) {
    const bool applies = e.kind == LoopTraceKind::LinkAdrAns || e.kind == LoopTraceKind::Apply;
    return applies ? e.status : static_cast<std::uint8_t>(LSIM_TRACE_STATUS_NONE);
}

// `downlink` : indice de descente pour LinkAdrReq, Downlink et Apply, sentinelle sinon.
std::uint32_t downlink_field(const LoopTraceEvent& e) {
    const bool indexed = e.kind == LoopTraceKind::LinkAdrReq || e.kind == LoopTraceKind::Downlink ||
                         e.kind == LoopTraceKind::Apply;
    return indexed ? e.downlink : static_cast<std::uint32_t>(LSIM_TRACE_NO_INDEX);
}

// `loss` : cause de perte pour Downlink uniquement ; LSIM_TRACE_LOSS_NONE sinon.
std::uint8_t loss_field(const LoopTraceEvent& e) {
    return e.kind == LoopTraceKind::Downlink ? e.loss : static_cast<std::uint8_t>(LSIM_TRACE_LOSS_NONE);
}

}  // namespace

bool is_historical_channel_mode(const lsim_closed_loop_v3_args& args) {
    return args.channels == nullptr && args.channel_count == 0 && args.channel_plan == LSIM_CHANNEL_PLAN_NONE;
}

std::vector<LoopChannelConfig> build_channel_configs(const lsim_closed_loop_v3_args& args) {
    std::vector<LoopChannelConfig> out(args.device_count);
    const LoopChannelState default_device = loop_eu868_default_channels();
    const LoopChannelSet default_view = loop_eu868_plan().defaults;
    for (LoopChannelConfig& cfg : out) {
        cfg.device = default_device;
        cfg.server_view = default_view;
    }
    if (args.channels == nullptr) return out;
    for (std::size_t i = 0; i < args.channel_count; ++i) {
        const lsim_channel_device_v3& element = args.channels[i];
        if (element.device_index >= args.device_count) continue;  // refusé par la validation
        if (element.present != LSIM_CHANNEL_PRESENT_YES) continue;  // valeurs par défaut du moteur
        LoopChannelState device;
        LoopChannelSet view;
        for (std::size_t ch = 0; ch < kLoopMaxChannels; ++ch) {
            device.dr_mask[ch] = element.dr_mask[ch];
            if (bit_at(element.enabled, ch)) device.enabled.set(ch);
            if (bit_at(element.server_defined, ch)) view.set(ch);
        }
        out[element.device_index].device = device;
        out[element.device_index].server_view = view;
    }
    return out;
}

std::vector<lsim_loop_trace_v3> convert_trace_v3(const std::vector<LoopTraceEvent>& events) {
    std::vector<lsim_loop_trace_v3> out;
    out.reserve(events.size());
    for (const LoopTraceEvent& e : events) {
        lsim_loop_trace_v3 o{};  // reserved = 0
        o.t_ns = e.t_ns;
        o.device = e.device;
        o.uplink = e.uplink;
        o.downlink = downlink_field(e);
        o.kind = static_cast<std::uint8_t>(e.kind);
        o.origin = static_cast<std::uint8_t>(e.origin);
        o.action = static_cast<std::uint8_t>(e.action);
        o.target = static_cast<std::uint8_t>(e.target);
        o.loss = loss_field(e);
        o.status = status_field(e);
        o.dr = e.dr;
        o.power_index = e.power_index;
        o.channel_mask = e.channel_mask;
        o.value = e.value;
        o.flag = e.flag ? 1 : 0;
        o.reason_channel = e.reason_channel;
        o.reason_dr = e.reason_dr;
        o.reason_power = e.reason_power;
        out.push_back(o);
    }
    return out;
}

}  // namespace lsim::sim::abi_v3
