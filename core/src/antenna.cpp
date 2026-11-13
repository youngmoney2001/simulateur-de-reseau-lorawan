// SPDX-License-Identifier: Apache-2.0
// Implémentation du diagramme de rayonnement horizontal (voir antenna.hpp).

#include "lsim/antenna.hpp"

#include <cmath>

namespace lsim::antenna {
namespace {

constexpr double kFullTurnDeg = 360.0;
constexpr double kHalfTurnDeg = 180.0;

// Forme du lobe (3GPP TR 36.814 §A.2.1.1.2) : atténuation positive, à soustraire.
// La pente de 12 est fixée par la convention du point à −3 dB à mi-ouverture.
double lobe_attenuation_db(double excess_deg, double beamwidth_deg, double front_to_back_db) {
    const double x = excess_deg / beamwidth_deg;
    return std::min(12.0 * x * x, front_to_back_db);
}

// Écart compté depuis l'axe pour la décroissance du lobe. Un secteur est à sommet
// plat : son gain maximal tient sur toute la largeur annoncée, et ce n'est qu'au-delà
// du bord que la courbe retombe. Les autres types décroissent dès l'axe.
double excess_from_boresight_deg(Kind kind, double offset_deg, double beamwidth_deg) {
    if (kind == Kind::Sector) {
        return std::max(0.0, offset_deg - 0.5 * beamwidth_deg);
    }
    return offset_deg;
}

// Écart angulaire minimal (degrés, dans [0, 180]) entre une direction et un axe.
double angular_offset_deg(double azimuth_deg, double pointing_deg) {
    double d = std::fmod(azimuth_deg - pointing_deg, kFullTurnDeg);
    if (d < 0.0) {
        d += kFullTurnDeg;
    }
    // Au-delà d'un demi-tour, passer par l'autre côté est plus court.
    if (d > kHalfTurnDeg) {
        d = kFullTurnDeg - d;
    }
    return d;
}

}  // namespace

AntennaStatus validate_pattern(const Pattern& p) {
    const auto kind_index = static_cast<int>(p.kind);
    if (kind_index < 0 || kind_index > static_cast<int>(Kind::Sector)) {
        return AntennaStatus::InvalidInput;
    }
    if (!std::isfinite(p.peak_gain_dbi) || !std::isfinite(p.pointing_deg)) {
        return AntennaStatus::InvalidInput;
    }
    if (p.peak_gain_dbi < kMinGainDbi || p.peak_gain_dbi > kMaxGainDbi) {
        return AntennaStatus::InvalidInput;
    }
    // L'omnidirectionnelle ignore l'ouverture et l'affaiblissement arrière : son
    // diagramme est un cercle, quels que soient ces réglages.
    if (p.kind == Kind::Omnidirectional) {
        return AntennaStatus::Ok;
    }
    if (!std::isfinite(p.beamwidth_deg) || !std::isfinite(p.front_to_back_db)) {
        return AntennaStatus::InvalidInput;
    }
    if (p.beamwidth_deg < kMinBeamwidthDeg || p.beamwidth_deg > kMaxBeamwidthDeg) {
        return AntennaStatus::InvalidInput;
    }
    if (p.front_to_back_db < kMinFrontToBackDb || p.front_to_back_db > kMaxFrontToBackDb) {
        return AntennaStatus::InvalidInput;
    }
    return AntennaStatus::Ok;
}

double gain_offset_db(const Pattern& p, double azimuth_deg) {
    // Un diagramme non valide dégénère en omnidirectionnel (offset nul) plutôt que de
    // propager un angle absurde dans un bilan de liaison.
    if (validate_pattern(p) != AntennaStatus::Ok) {
        return 0.0;
    }
    if (p.kind == Kind::Omnidirectional || !std::isfinite(azimuth_deg)) {
        return 0.0;
    }
    double best = lobe_attenuation_db(
        excess_from_boresight_deg(p.kind, angular_offset_deg(azimuth_deg, p.pointing_deg),
                                  p.beamwidth_deg),
        p.beamwidth_deg, p.front_to_back_db);
    if (p.kind == Kind::Bidirectional) {
        // Second lobe dans l'autre sens : on retient le meilleur des deux.
        best = std::min(best,
                        lobe_attenuation_db(
                            excess_from_boresight_deg(
                                p.kind, angular_offset_deg(azimuth_deg, p.pointing_deg + kHalfTurnDeg),
                                p.beamwidth_deg),
                            p.beamwidth_deg, p.front_to_back_db));
    }
    return -best;
}

double gain_dbi(const Pattern& p, double azimuth_deg) {
    return p.peak_gain_dbi + gain_offset_db(p, azimuth_deg);
}

}  // namespace lsim::antenna
