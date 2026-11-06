// SPDX-License-Identifier: Apache-2.0
// Canaux, LinkADRReq et LinkADRAns (voir loop_adr.hpp pour les sources et les règles).
#include "lsim/loop_adr.hpp"

namespace lsim::sim {

namespace {

constexpr std::size_t kWordBits = 64;

std::uint64_t bit_of(std::size_t channel) {
    return std::uint64_t{1} << (channel % kWordBits);
}

// Évaluation commune à la validation et à l'application : un seul chemin de calcul.
LoopLinkAdrDiagnosis evaluate(const LoopRegionalPlan& plan, const LoopTerminalRadio& current,
                              const LoopLinkAdrRequest& req, LoopChannelSet& resulting) {
    LoopLinkAdrDiagnosis d;
    resulting = current.channels.enabled;

    // 1. Masque : portée (affected) et activation (enable) selon ChMaskCntl.
    LoopChannelSet affected;
    LoopChannelSet enable;
    bool mask_valid = true;
    const std::size_t max_ch = plan.max_channels < kLoopMaxChannels ? plan.max_channels
                                                                   : kLoopMaxChannels;
    if (req.ch_mask_cntl == 7) {
        d.channel_reason = LoopChannelReason::RfuCntl;
        mask_valid = false;
    } else if (req.ch_mask_cntl == 5 && (req.ch_mask & 0xFC00U) != 0) {
        // Bits 10 à 15 RFU non nuls : refus (jamais d'application silencieuse d'un masque douteux).
        d.channel_reason = LoopChannelReason::RfuBits;
        mask_valid = false;
    } else if (req.ch_mask_cntl == 6) {
        // Tous les canaux définis ON ; le champ ChMask est ignoré (RP002 Table 14).
        for (std::size_t c = 0; c < max_ch; ++c) {
            if (current.channels.defined(c)) {
                affected.set(c);
                enable.set(c);
            }
        }
    } else if (req.ch_mask_cntl <= 4) {
        // Blocs de 16 canaux ; chaque bit du masque active un canal du bloc. Les canaux du
        // bloc non activés sont désactivés.
        const std::size_t base = static_cast<std::size_t>(req.ch_mask_cntl) * 16U;
        for (std::size_t i = 0; i < 16U; ++i) {
            const std::size_t c = base + i;
            if (c >= max_ch) break;
            affected.set(c);
            if ((req.ch_mask >> i) & 1U) enable.set(c);
        }
    } else {
        // ChMaskCntl 5 : 10 bits, banques de 8 canaux (RP002 Table 14). Les bits 10 à 15 sont
        // RFU : leur présence a été refusée ci-dessus.
        for (std::size_t b = 0; b < 10U; ++b) {
            for (std::size_t i = 0; i < 8U; ++i) {
                const std::size_t c = b * 8U + i;
                if (c >= max_ch) break;
                affected.set(c);
                if ((req.ch_mask >> b) & 1U) enable.set(c);
            }
        }
    }

    if (mask_valid) {
        // 2. Activation d'un canal non défini : refus, les canaux concernés sont attribués.
        for (std::size_t c = 0; c < kLoopMaxChannels; ++c) {
            if (enable.test(c) && !current.channels.defined(c)) d.refused_channels.set(c);
        }
        if (d.refused_channels.any()) {
            d.channel_reason = LoopChannelReason::UndefinedChannel;
            mask_valid = false;
        }
    }

    if (mask_valid) {
        // État résultant : canaux hors portée inchangés, portée = activations définies.
        LoopChannelSet next;
        for (std::size_t w = 0; w < next.words.size(); ++w) {
            next.words[w] = (current.channels.enabled.words[w] & ~affected.words[w]) |
                            enable.words[w];
        }
        resulting = next;
        if (!resulting.any()) {
            d.channel_reason = LoopChannelReason::AllDisabled;
            mask_valid = false;
        }
    }

    // Ensemble utilisé pour évaluer le débit : résultant si le masque est valide, courant sinon.
    const LoopChannelSet& dr_set = mask_valid ? resulting : current.channels.enabled;

    // 3. Débit. `dr_known` : le débit est connu du plan (ou ignoré, donc le débit courant).
    std::uint8_t effective_dr = current.dr;
    bool dr_known = true;
    if (req.dr == kLoopFieldIgnore) {
        d.dr_reason = LoopDataRateReason::Ignored;
    } else if (req.dr > plan.max_dr || ((plan.dr_available >> req.dr) & 1U) == 0) {
        d.dr_reason = LoopDataRateReason::UnknownDr;
        d.refuse_dr = true;
        dr_known = false;
    } else {
        effective_dr = req.dr;
        if (!current.channels.supports_dr(dr_set, req.dr)) {
            d.dr_reason = LoopDataRateReason::NotSupportedByChannels;
            d.refuse_dr = true;
        } else {
            d.dr_reason = LoopDataRateReason::Ok;
        }
    }

    // 4. Compatibilité du masque avec le débit résultant (TS001 Table 23). Attribution D5 :
    // le débit demandé est déjà marqué ci-dessus ; si le débit est ignoré, le masque est en
    // cause et le débit courant n'est pas exclu. Un débit inconnu n'est pas comparé.
    if (mask_valid && dr_known && !current.channels.supports_dr(resulting, effective_dr)) {
        d.channel_reason = LoopChannelReason::IncompatibleWithDataRate;
        mask_valid = false;
    }

    // 5. Puissance : 0xF ignoré ; index réservés au-delà du plan (RP002 Table 13).
    if (req.power_index == kLoopFieldIgnore) {
        d.power_reason = LoopPowerReason::Ignored;
    } else if (req.power_index > plan.max_power_index) {
        d.power_reason = LoopPowerReason::Reserved;
        d.refuse_power = true;
    } else {
        d.power_reason = LoopPowerReason::Ok;
    }

    d.status.channel_mask_ack = mask_valid;
    d.status.data_rate_ack = d.dr_reason == LoopDataRateReason::Ok ||
                             d.dr_reason == LoopDataRateReason::Ignored;
    d.status.power_ack = d.power_reason == LoopPowerReason::Ok ||
                         d.power_reason == LoopPowerReason::Ignored;
    return d;
}

}  // namespace

bool LoopChannelSet::operator==(const LoopChannelSet& other) const {
    return words == other.words;
}

bool LoopChannelState::operator==(const LoopChannelState& other) const {
    return dr_mask == other.dr_mask && enabled == other.enabled;
}

bool LoopTerminalRadio::operator==(const LoopTerminalRadio& other) const {
    return channels == other.channels && dr == other.dr && power_index == other.power_index;
}

bool LoopAdrStatus::operator==(const LoopAdrStatus& other) const {
    return channel_mask_ack == other.channel_mask_ack && data_rate_ack == other.data_rate_ack &&
           power_ack == other.power_ack;
}

bool LoopChannelSet::test(std::size_t channel) const {
    if (channel >= kLoopMaxChannels) return false;
    return (words[channel / kWordBits] & bit_of(channel)) != 0;
}

void LoopChannelSet::set(std::size_t channel) {
    if (channel >= kLoopMaxChannels) return;
    words[channel / kWordBits] |= bit_of(channel);
}

void LoopChannelSet::reset(std::size_t channel) {
    if (channel >= kLoopMaxChannels) return;
    words[channel / kWordBits] &= ~bit_of(channel);
}

bool LoopChannelSet::any() const {
    return words[0] != 0 || words[1] != 0;
}

std::size_t LoopChannelSet::count() const {
    std::size_t n = 0;
    for (std::size_t c = 0; c < kLoopMaxChannels; ++c) {
        if (test(c)) ++n;
    }
    return n;
}

bool LoopChannelState::defined(std::size_t channel) const {
    return channel < kLoopMaxChannels && dr_mask[channel] != 0;
}

LoopChannelSet LoopChannelState::defined_set() const {
    LoopChannelSet out;
    for (std::size_t c = 0; c < kLoopMaxChannels; ++c) {
        if (defined(c)) out.set(c);
    }
    return out;
}

bool LoopChannelState::supports_dr(const LoopChannelSet& set, std::uint8_t dr) const {
    if (dr > kLoopEuMaxDr) return false;
    const auto bit = static_cast<std::uint8_t>(std::uint8_t{1} << dr);
    for (std::size_t c = 0; c < kLoopMaxChannels; ++c) {
        if (set.test(c) && defined(c) && (dr_mask[c] & bit) != 0) return true;
    }
    return false;
}

LoopRegionalPlan loop_eu868_plan() {
    LoopRegionalPlan plan;
    plan.defaults.set(0);  // 868.1 MHz
    plan.defaults.set(1);  // 868.3 MHz
    plan.defaults.set(2);  // 868.5 MHz
    plan.default_dr_mask = 0x3F;  // DR0..DR5
    plan.max_dr = kLoopEuMaxDr;
    plan.max_power_index = kLoopEuMaxPowerIndex;
    plan.max_channels = kLoopMaxChannels;
    return plan;
}

bool LoopExclusions::exclude_dr(std::uint8_t value) {
    if (value >= dr.size()) return false;
    const bool renewed = dr[value] > 0;
    dr[value] = kLoopExclusionUplinks;
    return renewed;
}

bool LoopExclusions::exclude_power(std::uint8_t value) {
    if (value >= power.size()) return false;
    const bool renewed = power[value] > 0;
    power[value] = kLoopExclusionUplinks;
    return renewed;
}

bool LoopExclusions::exclude_mask(std::uint16_t block0) {
    const bool renewed = mask > 0 && mask_value == block0;
    mask_value = block0;
    mask = kLoopExclusionUplinks;
    return renewed;
}

bool LoopExclusions::mask_excluded(std::uint16_t block0) const {
    return mask > 0 && mask_value == block0;
}

std::uint16_t loop_request_block0(const LoopChannelSet& view, const LoopExclusions& excl,
                                  const LoopChannelSet& confirmed) {
    LoopChannelSet cand;
    for (std::size_t c = 0; c < 16U; ++c) {
        if (view.test(c) && !excl.channel_excluded(c)) cand.set(c);
    }
    const auto block0 = [](const LoopChannelSet& s) {
        return static_cast<std::uint16_t>(s.words[0] & 0xFFFFU);
    };
    const std::uint16_t bits = block0(cand);
    if (bits == 0 || excl.mask_excluded(bits)) return block0(confirmed);
    return bits;
}

bool LoopExclusions::exclude_channel(std::size_t channel_index) {
    if (channel_index >= channel.size()) return false;
    const bool renewed = channel[channel_index] > 0;
    channel[channel_index] = kLoopExclusionUplinks;
    return renewed;
}

void LoopExclusions::tick(std::vector<LoopExpiry>* expired) {
    const auto step = [expired](std::uint16_t& c, LoopExclusionTarget target, std::size_t index) {
        if (c == 0) return;
        --c;
        if (c == 0 && expired != nullptr) {
            expired->push_back(LoopExpiry{target, static_cast<std::uint16_t>(index)});
        }
    };
    for (std::size_t i = 0; i < dr.size(); ++i) step(dr[i], LoopExclusionTarget::DataRate, i);
    for (std::size_t i = 0; i < power.size(); ++i) step(power[i], LoopExclusionTarget::Power, i);
    for (std::size_t i = 0; i < channel.size(); ++i) step(channel[i], LoopExclusionTarget::Channel, i);
    if (mask > 0) {
        --mask;
        if (mask == 0 && expired != nullptr) {
            expired->push_back(LoopExpiry{LoopExclusionTarget::Mask, mask_value});
        }
    }
}

bool LoopExclusions::dr_excluded(std::uint8_t value) const { return value < dr.size() && dr[value] > 0; }

bool LoopExclusions::power_excluded(std::uint8_t value) const { return value < power.size() && power[value] > 0; }

bool LoopExclusions::channel_excluded(std::size_t channel_index) const {
    return channel_index < channel.size() && channel[channel_index] > 0;
}

LoopChannelState loop_eu868_default_channels() {
    LoopChannelState st;
    const LoopRegionalPlan plan = loop_eu868_plan();
    for (std::size_t c = 0; c < kLoopMaxChannels; ++c) {
        if (plan.defaults.test(c)) {
            st.dr_mask[c] = plan.default_dr_mask;
            st.enabled.set(c);
        }
    }
    return st;
}

std::uint8_t LoopAdrStatus::to_wire() const {
    std::uint8_t out = 0;
    if (channel_mask_ack) out = static_cast<std::uint8_t>(out | 0x01U);  // bit 0
    if (data_rate_ack) out = static_cast<std::uint8_t>(out | 0x02U);     // bit 1
    if (power_ack) out = static_cast<std::uint8_t>(out | 0x04U);         // bit 2
    return out;
}

LoopAdrStatus LoopAdrStatus::from_wire(std::uint8_t status) {
    LoopAdrStatus s;
    s.channel_mask_ack = (status & 0x01U) != 0;
    s.data_rate_ack = (status & 0x02U) != 0;
    s.power_ack = (status & 0x04U) != 0;
    return s;
}

LoopLinkAdrDiagnosis loop_validate_link_adr(const LoopRegionalPlan& plan,
                                            const LoopTerminalRadio& current,
                                            const LoopLinkAdrRequest& request) {
    LoopChannelSet resulting;
    return evaluate(plan, current, request, resulting);
}

LoopLinkAdrDiagnosis loop_apply_link_adr(const LoopRegionalPlan& plan, LoopTerminalRadio& terminal,
                                         const LoopLinkAdrRequest& request) {
    LoopChannelSet resulting;
    const LoopLinkAdrDiagnosis d = evaluate(plan, terminal, request, resulting);
    if (!d.status.all()) return d;  // atomicité : aucun paramètre n'est appliqué
    terminal.channels.enabled = resulting;
    if (request.dr != kLoopFieldIgnore) terminal.dr = request.dr;
    if (request.power_index != kLoopFieldIgnore) terminal.power_index = request.power_index;
    return d;
}

}  // namespace lsim::sim
