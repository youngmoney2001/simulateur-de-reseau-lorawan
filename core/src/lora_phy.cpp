// SPDX-License-Identifier: Apache-2.0
#include "lsim/lora_phy.hpp"

namespace lsim::lora {
namespace {

constexpr std::int64_t kNsPerSecond = 1'000'000'000;
constexpr std::int64_t kMaxPayloadBytes = 255;

bool is_valid_bw(Bandwidth bw) {
    switch (bw) {
        case Bandwidth::Bw125kHz:
        case Bandwidth::Bw250kHz:
        case Bandwidth::Bw500kHz:
            return true;
    }
    return false;
}

// Division entière arrondie vers le haut, pour numérateur positif uniquement.
std::int64_t ceil_div_positive(std::int64_t num, std::int64_t den) {
    return (num + den - 1) / den;
}

}  // namespace

std::int64_t symbol_duration_ns(std::uint8_t spreading_factor, Bandwidth bw) {
    // Tsym = 2^SF / BW (secondes) => 2^SF * 1e9 / BW (ns).
    // Pour BW = 125/250/500 kHz, 1e9 / BW est un entier (8000, 4000, 2000),
    // donc le résultat est exact. Les appelants doivent valider SF d'abord.
    const std::int64_t chips = std::int64_t{1} << spreading_factor;
    return chips * kNsPerSecond / static_cast<std::int64_t>(bw);
}

Status validate(const RadioConfig& cfg, std::uint32_t payload_bytes) {
    // SF5 (DR13) : en-tête explicite supposé (le datasheet SX1303 ne le précise pas). SF6 n'existe
    // qu'en en-tête implicite (datasheet SX1276, p. 15) : refusé tant que son modèle n'existe pas.
    const bool sf_ok = (cfg.spreading_factor >= 7 && cfg.spreading_factor <= 12) ||
                       (cfg.spreading_factor == 5 && cfg.explicit_header);
    if (!sf_ok) {
        return Status::InvalidSpreadingFactor;
    }
    if (!is_valid_bw(cfg.bandwidth)) {
        return Status::InvalidBandwidth;
    }
    if (cfg.coding_rate < 1 || cfg.coding_rate > 4) {
        return Status::InvalidCodingRate;
    }
    if (payload_bytes > static_cast<std::uint32_t>(kMaxPayloadBytes)) {
        return Status::InvalidPayloadSize;
    }
    if (cfg.preamble_symbols < 6) {
        return Status::InvalidPreamble;
    }
    return Status::Ok;
}

bool low_data_rate_required(std::uint8_t spreading_factor, Bandwidth bw) {
    // Seuil réglementaire : Tsym > 16 ms.
    return symbol_duration_ns(spreading_factor, bw) > 16'000'000;
}

AirtimeResult time_on_air(const RadioConfig& cfg, std::uint32_t payload_bytes) {
    const Status st = validate(cfg, payload_bytes);
    if (st != Status::Ok) {
        return {st, 0};
    }

    const std::int64_t sf = cfg.spreading_factor;
    const std::int64_t tsym = symbol_duration_ns(cfg.spreading_factor, cfg.bandwidth);

    // Préambule : (P + 4,25) symboles. tsym est divisible par 4 (SF >= 7),
    // donc le quart de symbole reste entier.
    const std::int64_t t_preamble =
        static_cast<std::int64_t>(cfg.preamble_symbols) * tsym + (tsym / 4) * 17;

    // Nombre de symboles de charge utile (note AN1200.13) :
    //   8 + max(ceil((8*PL - 4*SF + 28 + 16*CRC - 20*IH) / (4*(SF - 2*DE))) * (CR + 4), 0)
    const std::int64_t pl = static_cast<std::int64_t>(payload_bytes);
    const std::int64_t crc = cfg.crc_on ? 1 : 0;
    const std::int64_t ih = cfg.explicit_header ? 0 : 1;
    const std::int64_t de = cfg.low_data_rate_optimize ? 1 : 0;

    const std::int64_t numerator = 8 * pl - 4 * sf + 28 + 16 * crc - 20 * ih;
    const std::int64_t denominator = 4 * (sf - 2 * de);

    std::int64_t coded_blocks = 0;
    if (numerator > 0) {
        coded_blocks = ceil_div_positive(numerator, denominator);
    }
    const std::int64_t payload_symbols =
        8 + coded_blocks * (static_cast<std::int64_t>(cfg.coding_rate) + 4);

    const std::int64_t t_payload = payload_symbols * tsym;
    return {Status::Ok, t_preamble + t_payload};
}

}  // namespace lsim::lora
