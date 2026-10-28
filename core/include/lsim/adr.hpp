// SPDX-License-Identifier: Apache-2.0
// ADR côté serveur (LoRaWAN 1.1, §7 « Adaptive Data Rate » ; algorithme de décision).
//
// Fonction pure et déterministe : entrée = SNR des dernières trames montantes, sortie =
// débit et index de puissance recommandés. Aucune allocation, aucun état caché.
//
// Modèle (documenté pour les bureaux d'études) :
//   * SNR requis par SF : table du démodulateur LoRa du SX1276 (Semtech, datasheet, §
//     « LoRa Demodulator SNR ») : SF7 -7,5 dB ... SF12 -20 dB, pas de 2,5 dB ;
//   * marge au débit d (SF s) : M(d) = SNR_max - SNR_requis(s) - marge d'installation ;
//   * le débit monte tant que M(d) >= 0 (saut exact, pas de pas fixe de 3 dB) ;
//   * le reliquat M(d) sert à réduire la puissance, un index à la fois (pas de
//     `power_step`, en dixièmes de dB, fourni par la région) ; si M < 0 au débit courant,
//     la puissance monte (index décroît) jusqu'à M >= 0 ou puissance maximale.
// Les débits sont parcourus par index croissant, avec SF décroissant : la table `dr_sf`
// doit donc être monotone (SF plus faible à index plus élevé) pour chaque plan régional.
// Le serveur n'abaisse jamais le débit ici ; la marge négative se traduit par la puissance.
#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

namespace lsim::lorawan::adr {

inline constexpr std::size_t kMaxSamples = 20;  // historique ADR (Semtech : 20 trames)
inline constexpr std::size_t kDrCount = 16;     // index DR 0..15

enum class AdrStatus : std::int32_t {
    Ok = 0,
    InvalidParameter = 1,
};

struct Input {
    std::array<std::int32_t, kMaxSamples> snr_tenth_db{};  // SNR en dixièmes de dB, -500..500
    std::size_t n_samples = 0;                              // 1..kMaxSamples
    std::uint8_t dr = 0;                                    // débit courant
    std::array<std::uint8_t, kDrCount> dr_sf{};             // SF par index DR (7..12) ; 0 = indisponible
    std::uint8_t min_dr = 0;
    std::uint8_t max_dr = 0;
    std::uint8_t tx_power_index = 0;                        // 0 = puissance maximale
    std::uint8_t max_tx_power_index = 0;
    std::int32_t power_step_tenth_db = 20;                  // 1..100 (0,1 à 10 dB)
    std::int32_t installation_margin_tenth_db = 100;        // -300..300 (10 dB par défaut)
};

struct Output {
    std::uint8_t dr = 0;
    std::uint8_t tx_power_index = 0;
};

// SNR requis du démodulateur pour un SF 7..12 (dixièmes de dB). false si SF hors plage.
bool required_snr_tenth_db(std::uint8_t sf, std::int32_t& out);

// Décision ADR. En cas d'erreur, `out` vaut l'état courant et le statut est InvalidParameter.
AdrStatus decide(const Input& in, Output& out);

// ------------------------------------------------------------ ADR_ACK côté dispositif
//
// LoRaWAN 1.1 §4.3.1.1 (back-off ADR) : ADR_ACK_CNT compte les uplinks depuis la dernière
// réception descendante. À ADR_ACK_LIMIT (= 2^limit_exp) : ADRACKReq = 1 si le débit n'est
// pas le minimum, ou la puissance est inférieure au défaut, ou le masque est restreint.
// À LIMIT + k·DELAY (= 2^delay_exp, k >= 1), une étape de repli : puissance au défaut si
// elle ne l'est pas, sinon débit d'un cran plus bas ; au débit minimal, les canaux par
// défaut sont réactivés.
// Écart signalé : le tableau d'exemple (fig. 14) place la première remontée de puissance
// à 96 et non à 64 ; ce module suit le texte normatif (étape à LIMIT + DELAY).

struct DeviceAdrState {
    std::uint64_t ack_cnt = 0;             // ADR_ACK_CNT (uplinks depuis la dernière réception)
    std::uint8_t dr = 0;
    std::uint8_t min_dr = 0;               // débit minimal défini par le dispositif
    std::uint8_t tx_power_index = 0;
    std::uint8_t default_tx_power_index = 0;
    bool channels_subset = false;          // masque restreint aux canaux par défaut
};

struct UplinkOutcome {
    bool ack_req = false;                  // ADRACKReq à émettre dans cet uplink
    bool default_channels_reenabled = false;
};

// Un uplink (nouveau FCnt). limit_exp et delay_exp : 0..15 (ADRParamSetup).
// Invalide : rien n'est modifié.
AdrStatus device_on_uplink(DeviceAdrState& st, std::uint8_t limit_exp, std::uint8_t delay_exp,
                           UplinkOutcome& out);

// Réception d'une trame descendante : réinitialise ADR_ACK_CNT.
void device_on_downlink(DeviceAdrState& st);

}  // namespace lsim::lorawan::adr
