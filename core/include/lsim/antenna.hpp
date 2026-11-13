// SPDX-License-Identifier: Apache-2.0
// Antennes : diagramme de rayonnement dans le plan horizontal.
//
// Le moteur ne connaissait qu'un gain scalaire (`antenna_gain_dbi`), appliqué
// indifféremment dans toutes les directions — ce qui revient à décrire toute antenne
// comme un fouet omnidirectionnel. Une antenne réelle ne rayonne pas ainsi : un panneau
// ou un secteur concentre l'énergie dans un lobe, et la zone couverte en porte la marque.
//
// Modèle retenu (horizontal), celui du 3GPP TR 36.814 §A.2.1.1.2, repris par l'UIT-R
// pour les études de réseau :
//
//     A(θ) = −min( 12 · (e / θ₃dB)² , Am )
//
// où Am est l'affaiblissement avant-arrière (plancher du diagramme). La forme est
// parabolique en dB, ce qui place bien le point à −3 dB là où e = θ₃dB / 2
// (12 × 0,25 = 3), et elle sature sur Am : au-delà, les lobes secondaires sont
// plafonnés au lieu de décroître sans fin.
//
// Ce qui distingue les types, c'est la définition de `e`, l'écart compté depuis l'axe :
//
//   * directive / bidirectionnelle : e = |Δθ|, la décroissance part de l'axe. Le lobe
//     est un pic : le gain maximal n'est atteint qu'au pointage ;
//   * sectorielle : e = max(0, |Δθ| − θ₃dB / 2), la décroissance part du bord du
//     secteur. Le lobe est à sommet plat : tout le secteur annoncé (60, 90 ou 120°)
//     est servi au gain maximal, puis la courbe retombe de la même façon et atteint
//     −3 dB un demi-secteur plus loin.
//
// La différence est celle qu'on observe sur une antenne réelle : un panneau de secteur
// est conçu pour arroser uniformément un quart de tour, une Yagi pour concentrer
// l'énergie sur une direction.
//
// Conséquence à connaître : sur un secteur large, le plancher Am n'est pas atteint.
// Un secteur de 120° présente −12 dB dans son dos (e = 120° à 180° du pointage, soit
// 12 × 1²), et il faudrait 233° d'écart pour descendre à −25 dB : hors de portée du
// demi-cercle. Un Am élevé n'a donc d'effet que sur les secteurs étroits (60°) et sur
// les types à décroissance immédiate. Ce n'est pas un défaut du modèle, c'est le fait
// qu'une antenne qui arrose un tiers du tour ne peut pas beaucoup discriminer l'arrière.
//
// Deux réserves, qui valent d'être lues avant d'exploiter un chiffre :
//   * le diagramme est **horizontal seul**. Aucune ouverture verticale, donc aucun
//     effet de l'élévation d'antenne sur la forme du lobe ;
//   * la transition entre lobe principal et plancher est franche (min), là où une
//     antenne réelle présente des lobes secondaires irréguliers. Le modèle donne la
//     enveloppe, pas le détail.
//
// Règles :
//   * aucune exception : la validation renvoie un statut ;
//   * tout angle est en degrés, 0 = est, sens trigonométrique — la convention déjà
//     employée par `coverage_radii_m`, pour qu'un lobe pointé à 0° éclaire bien l'est.
#pragma once

#include <cstdint>

#include "lsim/lora_phy.hpp"

namespace lsim::antenna {

enum class Kind : std::int32_t {
    Omnidirectional = 0,  // gain identique dans toutes les directions
    Unidirectional = 1,   // un lobe principal, un arrière atténué
    Bidirectional = 2,    // deux lobes opposés (ex. doublet, antenne de couloir)
    Sector = 3,           // un lobe à sommet plat : secteur de 60/90/120°
};

// Nombre de lobes du type : 0 pour l'omnidirectionnelle, qui n'en a pas.
inline constexpr int kLobeCount[] = {0, 1, 2, 1};

struct Pattern {
    Kind kind = Kind::Omnidirectional;
    double peak_gain_dbi = 0.0;      // gain au maximum du lobe (dBi)
    double beamwidth_deg = 90.0;     // ouverture à −3 dB (degrés)
    double pointing_deg = 0.0;       // azimut de l'axe du lobe (degrés, 0 = est)
    double front_to_back_db = 20.0;  // affaiblissement arrière : plancher du diagramme (dB)
};

enum class AntennaStatus : std::int32_t {
    Ok = 0,
    InvalidInput = 1,  // non fini, hors bornes, ou type inconnu
};

// Bornes admissibles. L'ouverture minimale à 5° évite un lobe si étroit que le pas
// d'azimut de la couverture (souvent 5 à 15°) le traverserait sans jamais le voir.
inline constexpr double kMinBeamwidthDeg = 5.0;
inline constexpr double kMaxBeamwidthDeg = 360.0;
inline constexpr double kMinGainDbi = -40.0;
inline constexpr double kMaxGainDbi = 40.0;
inline constexpr double kMinFrontToBackDb = 0.0;
inline constexpr double kMaxFrontToBackDb = 60.0;

// Vérifie un diagramme : valeurs finies, type connu, grandeurs dans les bornes.
// L'ouverture et l'affaiblissement arrière ne sont contrôlés que sur les types qui
// s'en servent — les exiger sur une omnidirectionnelle refuserait un réglage valide
// sous prétexte qu'un champ sans effet n'est pas renseigné.
LSIM_API AntennaStatus validate_pattern(const Pattern& p);

// Décalage du gain (dB, négatif ou nul) dans la direction `azimuth_deg`, **par rapport
// au gain maximal** : 0 sur l'axe du lobe, −Am dans le dos. Indépendant de
// `peak_gain_dbi`, donc composable avec lui.
//
// `azimuth_deg` est ramené à un tour avant calcul : pointer à 370° vaut pointer à 10°.
LSIM_API double gain_offset_db(const Pattern& p, double azimuth_deg);

// Gain absolu (dBi) dans la direction `azimuth_deg`.
LSIM_API double gain_dbi(const Pattern& p, double azimuth_deg);

}  // namespace lsim::antenna
