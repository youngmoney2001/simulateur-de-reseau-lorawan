// SPDX-License-Identifier: Apache-2.0
// Modèle des canaux et de LinkADRReq / LinkADRAns pour la boucle fermée (étape 1 de la
// correction ChannelMask). API C++ interne : aucune fonction de l'ABI C n'utilise ces types.
//
// Sources normatives :
//   * TS001-1.0.4 Table 22 : LinkADRAns Status, bit 0 = ChannelMaskACK, bit 1 = DataRateACK,
//     bit 2 = PowerACK (ordre protocolaire, appliqué uniquement dans to_wire / from_wire) ;
//   * TS001-1.0.4 Table 23 : sens de chaque bit ; un bit à 0 = commande non réussie ;
//   * TS001-1.0.4 §5.2 : bloc de LinkADRReq contigus traité comme une commande atomique ;
//     un bit à 0 : le terminal conserve son état précédent ;
//   * RP002-1.0.5 §3.4.5 et Table 14 : ChMaskCntl EU863-870 (0..4 blocs de 16, 5 banques de 8,
//     6 = tous les canaux définis ON, 7 = RFU) ;
//   * RP002-1.0.5 Table 8 : canaux par défaut 868.1 / 868.3 / 868.5 MHz, DR0 à DR5.
//
// Convention interne du simulateur (non normative) : chaque bit indique la validité de son
// propre paramètre. L'application reste atomique : si un bit vaut 0, rien n'est appliqué.
//
// Règles de validation (évaluation dans cet ordre, déterministe) :
//   1. Masque : ChMaskCntl RFU -> refus, motif RfuCntl ; ChMaskCntl 5 avec un bit RFU non nul
//      (bits 10 à 15) -> refus, motif RfuBits (convention du simulateur : un masque invalide
//      n'est jamais accepté, même si la norme ne décrit pas ce cas).
//   2. Masque : canal activé non défini -> refus, motif UndefinedChannel ; canaux refusés
//      = ceux activés et non définis.
//   3. Masque : aucun canal actif après la commande -> refus, motif AllDisabled.
//   4. Débit : DR 0xF = ignoré ; DR hors plan (non modélisé) -> refus, motif UnknownDr ;
//      sinon le débit est évalué sur l'état résultant si le masque est valide, sinon sur
//      l'état courant. Aucun canal actif ne supporte ce débit -> refus, motif
//      NotSupportedByChannels.
//   5. Compatibilité (TS001 Table 23) : si le masque est valide et que le débit (demandé ou
//      courant, s'il est ignoré) n'est supporté par aucun canal actif résultant, le bit
//      ChannelMaskACK vaut 0 avec le motif IncompatibleWithDataRate. Attribution (D5) : au
//      débit si le débit est demandé, au masque sinon.
//   6. Puissance : 0xF = ignorée ; index 0..7 valides ; 8..14 réservés (RFU) -> refus,
//      motif Reserved.
#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <vector>

namespace lsim::sim {

// RP002-1.0.5 EU863-870 : 24 à 80 canaux ; le modèle en stocke 80 au plus.
inline constexpr std::size_t kLoopMaxChannels = 80;
inline constexpr std::uint8_t kLoopEuMaxDr = 7;         // DR0..DR7 (DR7 FSK non modélisé)
inline constexpr std::uint8_t kLoopEuMaxPowerIndex = 7; // RP002 Table 13 : 0..7 utilisables
inline constexpr std::uint8_t kLoopFieldIgnore = 15;    // TS001 : 0xF = conserver la valeur

// Ensemble de 80 canaux (deux mots de 64 bits).
struct LoopChannelSet {
    std::array<std::uint64_t, 2> words{};

    bool test(std::size_t channel) const;
    void set(std::size_t channel);
    void reset(std::size_t channel);
    bool any() const;
    std::size_t count() const;
    bool operator==(const LoopChannelSet& other) const;
};

// État canal d'un terminal : pour chaque canal, les débits qu'il supporte (bit n = DRn) ;
// 0 = canal non défini. `enabled` : canaux actifs pour l'émission.
struct LoopChannelState {
    std::array<std::uint8_t, kLoopMaxChannels> dr_mask{};
    LoopChannelSet enabled;

    bool defined(std::size_t channel) const;
    LoopChannelSet defined_set() const;
    // Vrai si au moins un canal de `set` supporte le débit `dr`.
    bool supports_dr(const LoopChannelSet& set, std::uint8_t dr) const;
    bool operator==(const LoopChannelState& other) const;
};

// Exclusions après refus (étape 4). Durée : 5 fenêtres ADR de 20 uplinks admissibles reçus, soit
// 100 uplinks (convention du simulateur, les fenêtres ADR ne sont pas normatives). Chaque valeur a
// son compteur : un débit exclu n'exclut ni un autre débit, ni une puissance, ni le masque.
// Un uplink admissible reçu décrémente tous les compteurs actifs ; à 0, l'exclusion expire.
// Le renouvellement remet le compteur à 100. L'expiration ne déclenche aucune commande.
inline constexpr std::uint16_t kLoopExclusionUplinks = 100;

// Cible d'une exclusion. `Mask` : le masque demandé complet (politique du simulateur, suspects vides).
enum class LoopExclusionTarget : std::uint8_t { DataRate, Power, Channel, Mask };

// Exclusion arrivée à échéance lors d'un `tick`.
struct LoopExpiry {
    LoopExclusionTarget target = LoopExclusionTarget::DataRate;
    std::uint16_t value = 0;
};

struct LoopExclusions {
    std::array<std::uint16_t, 16> dr{};     // uplinks admissibles restants par débit ; 0 = éligible
    std::array<std::uint16_t, 16> power{};  // idem par index de puissance
    std::array<std::uint16_t, kLoopMaxChannels> channel{};  // par canal ; 0 = éligible
    // Masque demandé complet (bloc 0) exclu : une seule case. Ne bloque que ce masque exact.
    std::uint16_t mask_value = 0;
    std::uint16_t mask = 0;                                  // uplinks restants ; 0 = aucun

    // Pose (ou renouvelle) l'exclusion. Retourne vrai si la même exclusion était déjà active
    // (renouvellement). Une exclusion de masque remplace une exclusion de masque différente.
    bool exclude_dr(std::uint8_t dr);
    bool exclude_power(std::uint8_t power_index);
    bool exclude_channel(std::size_t channel_index);
    bool exclude_mask(std::uint16_t block0);
    bool mask_excluded(std::uint16_t block0) const;
    // Un uplink admissible reçu : décrémente les compteurs actifs. `expired` (optionnel) reçoit les
    // exclusions qui arrivent à 0 à cet uplink.
    void tick(std::vector<LoopExpiry>* expired = nullptr);
    bool dr_excluded(std::uint8_t dr) const;
    bool power_excluded(std::uint8_t power_index) const;
    bool channel_excluded(std::size_t channel_index) const;
};

// Masque du bloc 0 à demander : vue serveur privée des canaux exclus. Repli sur le dernier masque
// confirmé si ce candidat est vide ou égal au masque exclu (politique du simulateur).
std::uint16_t loop_request_block0(const LoopChannelSet& view, const LoopExclusions& excl,
                                  const LoopChannelSet& confirmed);

// Terminal complet (partie radio pertinente pour LinkADR).
struct LoopTerminalRadio {
    LoopChannelState channels;
    std::uint8_t dr = 0;
    std::uint8_t power_index = 0;
    bool operator==(const LoopTerminalRadio& other) const;
};

// Plan régional connu du serveur : canaux par défaut, débits et puissances valides.
// Ce n'est pas l'état du terminal : le serveur et le terminal ont chacun leur vue.
struct LoopRegionalPlan {
    LoopChannelSet defaults;               // canaux par défaut (RP002 Table 8)
    std::uint8_t default_dr_mask = 0;      // débits supportés par les canaux par défaut
    std::uint8_t dr_available = 0xFF;      // bit n = DRn utilisable (table du plan / de la région)
    std::uint8_t max_dr = 0;
    std::uint8_t max_power_index = 0;
    std::size_t max_channels = kLoopMaxChannels;
};

// Plan EU863-870 (RP002-1.0.5) : défauts 0..2 avec DR0..DR5.
LoopRegionalPlan loop_eu868_plan();

// État canal par défaut d'un terminal EU863-870 : canaux 0..2 définis, actifs, DR0..DR5.
LoopChannelState loop_eu868_default_channels();

// LinkADRReq tel que reçu par le terminal.
struct LoopLinkAdrRequest {
    std::uint8_t ch_mask_cntl = 0;   // 0..7 (EU863-870)
    std::uint16_t ch_mask = 0;
    std::uint8_t dr = kLoopFieldIgnore;
    std::uint8_t power_index = kLoopFieldIgnore;
};

// Bits de LinkADRAns. L'ordre protocolaire n'existe que dans to_wire / from_wire.
struct LoopAdrStatus {
    bool channel_mask_ack = false;   // bit 0 (TS001 Table 22)
    bool data_rate_ack = false;      // bit 1
    bool power_ack = false;          // bit 2

    bool all() const { return channel_mask_ack && data_rate_ack && power_ack; }
    std::uint8_t to_wire() const;               // octet d'état de LinkADRAns
    static LoopAdrStatus from_wire(std::uint8_t status);  // bits RFU 3..7 ignorés
    bool operator==(const LoopAdrStatus& other) const;
};

enum class LoopChannelReason : std::uint8_t {
    Ok,
    RfuCntl,
    UndefinedChannel,
    AllDisabled,
    IncompatibleWithDataRate,
    RfuBits,
};

enum class LoopDataRateReason : std::uint8_t {
    Ok,
    Ignored,
    UnknownDr,
    NotSupportedByChannels,
};

enum class LoopPowerReason : std::uint8_t {
    Ok,
    Ignored,
    Reserved,
};

// Diagnostic d'une commande : bits individuels, motifs exacts et attribution pour les
// exclusions côté serveur (D5 : refus croisé attribué au débit).
struct LoopLinkAdrDiagnosis {
    LoopAdrStatus status;
    LoopChannelReason channel_reason = LoopChannelReason::Ok;
    LoopDataRateReason dr_reason = LoopDataRateReason::Ok;
    LoopPowerReason power_reason = LoopPowerReason::Ok;
    LoopChannelSet refused_channels;   // canaux activés demandés et non définis
    bool refuse_dr = false;            // débit à exclure côté serveur
    bool refuse_power = false;         // puissance à exclure côté serveur
};

// Validation pure : ne modifie ni le terminal ni le plan.
LoopLinkAdrDiagnosis loop_validate_link_adr(const LoopRegionalPlan& plan,
                                            const LoopTerminalRadio& current,
                                            const LoopLinkAdrRequest& request);

// Application atomique : si le diagnostic n'est pas entièrement positif, le terminal reste
// strictement inchangé. Retourne le diagnostic dans tous les cas.
LoopLinkAdrDiagnosis loop_apply_link_adr(const LoopRegionalPlan& plan, LoopTerminalRadio& terminal,
                                         const LoopLinkAdrRequest& request);

}  // namespace lsim::sim
