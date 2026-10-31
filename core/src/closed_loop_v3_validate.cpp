// SPDX-License-Identifier: Apache-2.0
// Validation des arguments de lsim_simulate_closed_loop_v3 (étape 6.2.2). Aucune écriture dans les
// sorties ; aucune simulation. Les règles suivent le contrat 6.1 (codes base 1000, sentinelles,
// buffers) ; les choix d'interprétation sont signalés dans le compte rendu de 6.2.2.
#include "lsim/closed_loop_v3_validate.hpp"

#include <array>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <vector>

#include "lsim/engine.hpp"
#include "lsim/loop_adr.hpp"

namespace lsim::sim::abi_v3 {
namespace {

constexpr std::size_t kEnabledBytes = 10;     // 80 bits, LSB first : bit c dans enabled[c / 8]
constexpr std::size_t kDrMaskBytes = 80;      // un octet par canal
constexpr std::size_t kReservedBytes = 12;    // lsim_channel_device_v3::reserved
constexpr std::size_t kSupportedChannels = 16;
constexpr std::size_t kMaxDrBit = 7;          // bits de DR0..DR7 dans dr_mask

constexpr std::size_t kArgsSize = sizeof(lsim_closed_loop_v3_args);
constexpr std::size_t kTraceSize = sizeof(lsim_loop_trace_v3);
constexpr std::size_t kTerminalSize = sizeof(lsim_channel_terminal_v3);
constexpr std::size_t kChannelSize = sizeof(lsim_channel_device_v3);

// Une plage mémoire non vide : [begin, end).
struct Span {
    std::uintptr_t begin = 0;
    std::uintptr_t end = 0;
};

bool any_nonzero(const std::uint8_t* bytes, std::size_t count) {
    for (std::size_t i = 0; i < count; ++i) {
        if (bytes[i] != 0) return true;
    }
    return false;
}

bool bit_set(const std::uint8_t* bytes, std::size_t channel) {
    return ((bytes[channel / 8U] >> (channel % 8U)) & 1U) != 0;
}

// Ajoute une plage après contrôle de débordement et d'alignement. Une plage vide est ignorée.
// Le pointeur d'une plage non vide doit déjà être non nul (contrôlé par l'appelant).
std::int32_t add_span(std::array<Span, 32>& spans, std::size_t& count, const void* p, std::size_t elements,
                      std::size_t element_size, std::size_t alignment) {
    if (elements == 0) return 0;
    if (elements > std::numeric_limits<std::size_t>::max() / element_size) {
        return LSIM_STATUS_CHANNEL_RANGE_OVERFLOW;
    }
    const std::size_t bytes = elements * element_size;
    const auto begin = reinterpret_cast<std::uintptr_t>(p);
    if (begin > std::numeric_limits<std::uintptr_t>::max() - static_cast<std::uintptr_t>(bytes)) {
        return LSIM_STATUS_CHANNEL_RANGE_OVERFLOW;
    }
    if (begin % alignment != 0) return LSIM_STATUS_CHANNEL_MISALIGNED;
    spans[count++] = Span{begin, begin + static_cast<std::uintptr_t>(bytes)};
    return 0;
}

// Contrôle d'un élément de configuration canal, dans l'ordre : taille, version, index, drapeau
// present, réservés, champs sans present, indices 16..79, masques de DR, activation, vue serveur.
std::int32_t check_channel_device(const lsim_channel_device_v3& c, std::size_t device_count,
                                  std::vector<bool>& seen, const lsim_loop_region* regions) {
    if (c.struct_size != kChannelSize) return LSIM_STATUS_CHANNEL_ELEMENT_SIZE;
    if (c.abi_version != kClosedLoopV3AbiVersion) return LSIM_STATUS_CHANNEL_ABI_VERSION;
    if (c.device_index >= device_count || seen[c.device_index]) return LSIM_STATUS_CHANNEL_DEVICE_INDEX;
    seen[c.device_index] = true;
    if (c.present != LSIM_CHANNEL_PRESENT_NO && c.present != LSIM_CHANNEL_PRESENT_YES) {
        return LSIM_STATUS_CHANNEL_PRESENT_FLAG;
    }
    if (any_nonzero(c.reserved, kReservedBytes)) return LSIM_STATUS_CHANNEL_RESERVED_NONZERO;
    if (c.present == LSIM_CHANNEL_PRESENT_NO) {
        if (any_nonzero(c.dr_mask, kDrMaskBytes) || any_nonzero(c.enabled, kEnabledBytes) ||
            any_nonzero(c.server_defined, kEnabledBytes)) {
            return LSIM_STATUS_CHANNEL_FIELDS_WITHOUT_PRESENT;
        }
        return 0;
    }
    // Indices 16 à 79 : refusés dans les champs concernés (A1).
    for (std::size_t ch = kSupportedChannels; ch < kDrMaskBytes; ++ch) {
        if (c.dr_mask[ch] != 0) return LSIM_STATUS_CHANNEL_INDEX_UNSUPPORTED;
    }
    if (any_nonzero(c.enabled + 2, kEnabledBytes - 2) || any_nonzero(c.server_defined + 2, kEnabledBytes - 2)) {
        return LSIM_STATUS_CHANNEL_INDEX_UNSUPPORTED;
    }
    // Chaque bit de DR d'un canal défini doit être inférieur ou égal au max_dr de la région.
    // Pas de contrôle sur dr_sf : le moteur accepte un bit sans entrée dr_sf (état initial).
    const lsim_loop_region& region = regions[c.device_index];
    for (std::size_t ch = 0; ch < kSupportedChannels; ++ch) {
        const std::uint8_t mask = c.dr_mask[ch];
        for (std::size_t dr = 0; dr <= kMaxDrBit; ++dr) {
            if (((mask >> dr) & 1U) == 0) continue;
            if (dr > region.max_dr) return LSIM_STATUS_CHANNEL_DR_MASK_INVALID;
        }
    }
    // Un canal activé doit être défini (dr_mask non nul).
    for (std::size_t ch = 0; ch < kSupportedChannels; ++ch) {
        if (bit_set(c.enabled, ch) && c.dr_mask[ch] == 0) return LSIM_STATUS_CHANNEL_ENABLED_UNDEFINED;
    }
    if (!any_nonzero(c.enabled, kEnabledBytes)) return LSIM_STATUS_CHANNEL_ENABLED_EMPTY;
    if (!any_nonzero(c.server_defined, kEnabledBytes)) return LSIM_STATUS_CHANNEL_SERVER_VIEW_EMPTY;
    return 0;
}

std::int32_t validate_body(const lsim_closed_loop_v3_args& a) {
    // En-tête et tailles déclarées.
    if (a.struct_size != kArgsSize) return LSIM_STATUS_CHANNEL_ARGS_SIZE;
    if (a.abi_version != kClosedLoopV3AbiVersion) return LSIM_STATUS_CHANNEL_ABI_VERSION;
    if (a.trace_element_size != kTraceSize || a.terminal_element_size != kTerminalSize) {
        return LSIM_STATUS_CHANNEL_ELEMENT_SIZE;
    }
    if (a.reserved0 != 0 || a.reserved1 != 0) return LSIM_STATUS_CHANNEL_RESERVED_NONZERO;

    // Plan et mode de configuration des canaux.
    if (a.channel_plan != LSIM_CHANNEL_PLAN_NONE && a.channel_plan != LSIM_CHANNEL_PLAN_EU868_RP002_1_0_5) {
        return LSIM_STATUS_CHANNEL_PLAN;
    }
    const bool historical = a.channels == nullptr && a.channel_count == 0 && a.channel_plan == LSIM_CHANNEL_PLAN_NONE;
    const bool explicit_mode = a.channels != nullptr && a.device_count > 0 &&
                               a.channel_count == a.device_count &&
                               a.channel_plan == LSIM_CHANNEL_PLAN_EU868_RP002_1_0_5;
    if (!historical && !explicit_mode) return LSIM_STATUS_CHANNEL_MODE;

    // Trace : mode binaire, buffer interdit quand désactivée (A10), obligatoire quand activée.
    if (a.trace_enabled != 0 && a.trace_enabled != 1) return LSIM_STATUS_CHANNEL_TRACE_MODE;
    if (a.trace_enabled == 0 && (a.trace != nullptr || a.trace_capacity != 0)) return LSIM_STATUS_CHANNEL_TRACE_MODE;

    if (a.device_count > kMaxEndDevices) {
        return LSIM_STATUS_SIM_BASE + static_cast<std::int32_t>(SimStatus::TooManyDevices);
    }

    // Pointeurs obligatoires.
    const std::size_t n = a.device_count;
    if (a.gateway == nullptr || a.prop == nullptr || a.totals == nullptr || a.options == nullptr ||
        a.uplinks == nullptr || a.downlinks == nullptr || a.busy == nullptr || a.uplink_count == nullptr ||
        a.downlink_count == nullptr || a.busy_count == nullptr ||
        a.trace_count == nullptr || a.terminal_count == nullptr) {
        return LSIM_STATUS_CHANNEL_NULL_POINTER;
    }
    if (n > 0 && (a.devices == nullptr || a.radios == nullptr || a.regions == nullptr || a.per_device == nullptr)) {
        return LSIM_STATUS_CHANNEL_NULL_POINTER;
    }
    if (a.mac_count > 0 && a.mac == nullptr) return LSIM_STATUS_CHANNEL_NULL_POINTER;
    if (a.trace_enabled == 1 && a.trace == nullptr) return LSIM_STATUS_CHANNEL_NULL_POINTER;
    if (a.terminals == nullptr && a.terminal_capacity > 0) return LSIM_STATUS_CHANNEL_NULL_POINTER;
    // Capacités de sortie : contrôlées après simulation (closed_loop_v3_output.cpp), dans l'ordre gelé.

    // Plages mémoire : débordements, alignements, puis chevauchements (plages vides ignorées).
    std::array<Span, 32> spans{};
    std::size_t span_count = 0;
    std::int32_t err = 0;
    auto add = [&](const void* p, std::size_t elements, std::size_t size, std::size_t align) {
        if (err == 0) err = add_span(spans, span_count, p, elements, size, align);
    };
    add(&a, 1, kArgsSize, alignof(lsim_closed_loop_v3_args));
    add(a.devices, n, sizeof(lsim_end_device), alignof(lsim_end_device));
    add(a.radios, n, sizeof(lsim_plan_device), alignof(lsim_plan_device));
    add(a.regions, n, sizeof(lsim_loop_region), alignof(lsim_loop_region));
    add(a.gateway, 1, sizeof(lsim_gateway_v2), alignof(lsim_gateway_v2));
    add(a.prop, 1, sizeof(lsim_propagation), alignof(lsim_propagation));
    add(a.env, a.env != nullptr ? 1 : 0, sizeof(lsim_environment), alignof(lsim_environment));
    add(a.options, 1, sizeof(lsim_loop_options), alignof(lsim_loop_options));
    add(a.mac, a.mac_count, sizeof(lsim_loop_mac), alignof(lsim_loop_mac));
    add(a.channels, a.channel_count, kChannelSize, alignof(lsim_channel_device_v3));
    add(a.per_device, n, sizeof(lsim_device_stats), alignof(lsim_device_stats));
    add(a.totals, 1, sizeof(lsim_sim_stats), alignof(lsim_sim_stats));
    add(a.mac_counters, a.mac_counters != nullptr ? 1 : 0, sizeof(lsim_loop_mac_counters),
        alignof(lsim_loop_mac_counters));  // facultatif (convention v1/v2)
    add(a.uplinks, a.uplink_capacity, sizeof(lsim_loop_uplink), alignof(lsim_loop_uplink));
    add(a.uplink_count, 1, sizeof(std::size_t), alignof(std::size_t));
    add(a.downlinks, a.downlink_capacity, sizeof(lsim_loop_downlink), alignof(lsim_loop_downlink));
    add(a.downlink_count, 1, sizeof(std::size_t), alignof(std::size_t));
    add(a.busy, a.busy_capacity, sizeof(lsim_interval), alignof(lsim_interval));
    add(a.busy_count, 1, sizeof(std::size_t), alignof(std::size_t));
    add(a.trace, a.trace_enabled == 1 ? a.trace_capacity : 0, kTraceSize, alignof(lsim_loop_trace_v3));
    add(a.trace_count, 1, sizeof(std::size_t), alignof(std::size_t));
    add(a.terminals, a.terminal_capacity, kTerminalSize, alignof(lsim_channel_terminal_v3));
    add(a.terminal_count, 1, sizeof(std::size_t), alignof(std::size_t));
    if (err != 0) return err;
    for (std::size_t i = 0; i < span_count; ++i) {
        for (std::size_t j = i + 1; j < span_count; ++j) {
            if (spans[i].begin < spans[j].end && spans[j].begin < spans[i].end) {
                return LSIM_STATUS_CHANNEL_BUFFERS_ALIASED;
            }
        }
    }

    // Éléments de configuration canal : un par dispositif, chacun une seule fois.
    if (explicit_mode) {
        std::vector<bool> seen(n, false);
        for (std::size_t i = 0; i < n; ++i) {
            const std::int32_t code = check_channel_device(a.channels[i], n, seen, a.regions);
            if (code != 0) return code;
        }
    }
    return 0;
}

}  // namespace

std::int32_t validate_closed_loop_v3_args(const lsim_closed_loop_v3_args* args) {
    if (args == nullptr) return LSIM_STATUS_CHANNEL_NULL_POINTER;
    if (reinterpret_cast<std::uintptr_t>(args) % alignof(lsim_closed_loop_v3_args) != 0) {
        return LSIM_STATUS_CHANNEL_MISALIGNED;
    }
    try {
        return validate_body(*args);
    } catch (...) {
        return LSIM_STATUS_INTERNAL;
    }
}

}  // namespace lsim::sim::abi_v3
