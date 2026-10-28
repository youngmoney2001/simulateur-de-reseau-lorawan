// SPDX-License-Identifier: Apache-2.0
// Rejoin-request LoRaWAN 1.1 (types 0, 1, 2) et garde anti-rejeu des compteurs
// (RJcount0, RJcount1, DevNonce). Spécification 1.1, §6.2.4 et §6.2.5.
//
// Règles de sécurité :
//   * MIC vérifié avant tout enregistrement de compteur (un message forgé ne doit
//     jamais faire avancer l'état du serveur) ;
//   * clé imposée par type : SNwkSIntKey pour les types 0 et 2, JSIntKey pour le type 1 ;
//   * comparaison du MIC en temps constant ;
//   * compteur strictement croissant, jamais réutilisé (pas d'enroulement).
#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

#include "lsim/crypto.hpp"

namespace lsim::lorawan {

enum class RejoinStatus : std::int32_t {
    Ok = 0,
    BufferTooSmall = 1,
    InvalidLength = 2,
    InvalidMHDR = 3,
    InvalidType = 4,
    MicMismatch = 5,
    CryptoFailure = 6,
    FieldOutOfRange = 7,
    Replayed = 8,
};

inline constexpr std::uint8_t kMhdrRejoinRequest = 0xC0;  // MType 110, Major 0
inline constexpr std::size_t kRejoin02Size = 19;          // MHDR | Type | NetID | DevEUI | RJcount0 | MIC
inline constexpr std::size_t kRejoin1Size = 24;           // MHDR | Type | JoinEUI | DevEUI | RJcount1 | MIC

// Type 0 ou 2 : NetID (3 octets) + DevEUI + RJcount0 (16 bits).
struct Rejoin02Fields {
    std::uint8_t rejoin_type = 0;  // 0 ou 2
    std::array<std::uint8_t, 3> net_id{};
    std::array<std::uint8_t, 8> dev_eui{};
    std::uint16_t rjcount0 = 0;
};

// Type 1 : JoinEUI + DevEUI + RJcount1 (16 bits).
struct Rejoin1Fields {
    std::array<std::uint8_t, 8> join_eui{};
    std::array<std::uint8_t, 8> dev_eui{};
    std::uint16_t rjcount1 = 0;
};

// Garde anti-rejeu : une valeur n'est acceptée que si elle dépasse la dernière
// enregistrée. Deux temps (is_fresh puis record) : l'appelant enregistre seulement
// après une vérification de MIC réussie.
class Counter16Guard {
public:
    bool is_fresh(std::uint16_t value) const { return !has_last_ || value > last_; }
    void record(std::uint16_t value) {
        last_ = value;
        has_last_ = true;
    }
    // Nouvelle session (Join-accept traité) : repartir sans historique.
    void reset() {
        has_last_ = false;
        last_ = 0;
    }
    bool has_last() const { return has_last_; }
    std::uint16_t last() const { return last_; }

private:
    bool has_last_ = false;
    std::uint16_t last_ = 0;
};

// Type de rejoin lu dans un message reçu (vérifie MHDR et taille minimale).
RejoinStatus peek_rejoin_type(const std::uint8_t* in, std::size_t len, std::uint8_t& rejoin_type);

RejoinStatus encode_rejoin_02(const Rejoin02Fields& f, const crypto::Key128& s_nwk_s_int_key,
                              std::uint8_t* out, std::size_t cap, std::size_t& out_len);
RejoinStatus decode_rejoin_02(const std::uint8_t* in, std::size_t len,
                              const crypto::Key128& s_nwk_s_int_key, Rejoin02Fields& out);

RejoinStatus encode_rejoin_1(const Rejoin1Fields& f, const crypto::Key128& js_int_key,
                             std::uint8_t* out, std::size_t cap, std::size_t& out_len);
RejoinStatus decode_rejoin_1(const std::uint8_t* in, std::size_t len,
                             const crypto::Key128& js_int_key, Rejoin1Fields& out);

}  // namespace lsim::lorawan
