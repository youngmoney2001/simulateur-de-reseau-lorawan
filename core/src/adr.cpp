// SPDX-License-Identifier: Apache-2.0
#include "lsim/adr.hpp"

namespace lsim::lorawan::adr {
namespace {

constexpr std::int32_t kMinSnr = -500;
constexpr std::int32_t kMaxSnr = 500;
constexpr std::int32_t kMaxPowerStep = 100;
constexpr std::int32_t kMaxMargin = 300;
constexpr std::uint8_t kMaxPowerIndex = 15;

// Marge M = SNR_max - SNR_requis(sf) - marge d'installation, en dixièmes de dB.
bool margin_for_sf(std::uint8_t sf, std::int32_t snr_max, std::int32_t installation, std::int32_t& margin) {
    std::int32_t req = 0;
    if (!required_snr_tenth_db(sf, req)) return false;
    margin = snr_max - req - installation;
    return true;
}

}  // namespace

bool required_snr_tenth_db(std::uint8_t sf, std::int32_t& out) {
    // Datasheet SX1276, table « LoRa Demodulator SNR » (dB) : 7 -7,5 ; 8 -10 ; 9 -12,5 ;
    // 10 -15 ; 11 -17,5 ; 12 -20.
    switch (sf) {
        case 7: out = -75; return true;
        case 8: out = -100; return true;
        case 9: out = -125; return true;
        case 10: out = -150; return true;
        case 11: out = -175; return true;
        case 12: out = -200; return true;
        default: return false;
    }
}

AdrStatus decide(const Input& in, Output& out) {
    out.dr = in.dr;
    out.tx_power_index = in.tx_power_index;

    // Validation complète avant tout calcul.
    if (in.n_samples < 1 || in.n_samples > kMaxSamples) return AdrStatus::InvalidParameter;
    if (in.min_dr > in.max_dr || in.max_dr >= kDrCount) return AdrStatus::InvalidParameter;
    if (in.dr < in.min_dr || in.dr > in.max_dr) return AdrStatus::InvalidParameter;
    if (in.tx_power_index > in.max_tx_power_index || in.max_tx_power_index > kMaxPowerIndex) {
        return AdrStatus::InvalidParameter;
    }
    if (in.power_step_tenth_db < 1 || in.power_step_tenth_db > kMaxPowerStep) return AdrStatus::InvalidParameter;
    if (in.installation_margin_tenth_db < -kMaxMargin || in.installation_margin_tenth_db > kMaxMargin) {
        return AdrStatus::InvalidParameter;
    }
    for (std::size_t i = 0; i < kDrCount; ++i) {
        if (in.dr_sf[i] != 0) {
            std::int32_t unused = 0;
            if (!required_snr_tenth_db(in.dr_sf[i], unused)) return AdrStatus::InvalidParameter;
        }
    }
    if (in.dr_sf[in.dr] == 0) return AdrStatus::InvalidParameter;

    std::int32_t snr_max = in.snr_tenth_db[0];
    for (std::size_t i = 0; i < in.n_samples; ++i) {
        const std::int32_t s = in.snr_tenth_db[i];
        if (s < kMinSnr || s > kMaxSnr) return AdrStatus::InvalidParameter;
        if (s > snr_max) snr_max = s;
    }

    std::int32_t margin = 0;
    if (!margin_for_sf(in.dr_sf[in.dr], snr_max, in.installation_margin_tenth_db, margin)) {
        return AdrStatus::InvalidParameter;
    }

    std::uint8_t dr = in.dr;
    if (margin >= 0) {
        // Montée du débit tant que la marge reste positive (SF décroissant).
        for (std::size_t c = static_cast<std::size_t>(in.dr) + 1; c <= in.max_dr; ++c) {
            if (in.dr_sf[c] == 0) continue;
            std::int32_t m = 0;
            margin_for_sf(in.dr_sf[c], snr_max, in.installation_margin_tenth_db, m);
            if (m < 0) break;
            dr = static_cast<std::uint8_t>(c);
            margin = m;
        }
    }

    // Puissance : reliquat positif -> réduction (index croissant) ; négatif -> augmentation.
    std::uint8_t idx = in.tx_power_index;
    if (margin >= 0) {
        while (margin >= in.power_step_tenth_db && idx < in.max_tx_power_index) {
            ++idx;
            margin -= in.power_step_tenth_db;
        }
    } else {
        while (margin < 0 && idx > 0) {
            --idx;
            margin += in.power_step_tenth_db;
        }
    }

    out.dr = dr;
    out.tx_power_index = idx;
    return AdrStatus::Ok;
}

AdrStatus device_on_uplink(DeviceAdrState& st, std::uint8_t limit_exp, std::uint8_t delay_exp,
                           UplinkOutcome& out) {
    out = UplinkOutcome{};
    if (limit_exp > 15 || delay_exp > 15) return AdrStatus::InvalidParameter;
    if (st.dr < st.min_dr || st.tx_power_index > kMaxPowerIndex ||
        st.default_tx_power_index > kMaxPowerIndex) {
        return AdrStatus::InvalidParameter;
    }
    DeviceAdrState next = st;
    ++next.ack_cnt;
    const std::uint64_t limit = std::uint64_t{1} << limit_exp;
    const std::uint64_t delay = std::uint64_t{1} << delay_exp;
    if (next.ack_cnt >= limit + delay && (next.ack_cnt - limit) % delay == 0) {
        // Étape de repli : puissance au défaut, sinon débit d'un cran plus bas.
        if (next.tx_power_index > next.default_tx_power_index) {
            next.tx_power_index = next.default_tx_power_index;
        } else if (next.dr > next.min_dr) {
            --next.dr;
        }
        // Débit minimal atteint : canaux par défaut réactivés sans attendre une étape de plus.
        if (next.dr == next.min_dr && next.channels_subset) {
            next.channels_subset = false;
            out.default_channels_reenabled = true;
        }
    }
    out.ack_req = next.ack_cnt >= limit &&
                  (next.dr > next.min_dr || next.tx_power_index > next.default_tx_power_index ||
                   next.channels_subset);
    st = next;
    return AdrStatus::Ok;
}

void device_on_downlink(DeviceAdrState& st) { st.ack_cnt = 0; }

}  // namespace lsim::lorawan::adr
