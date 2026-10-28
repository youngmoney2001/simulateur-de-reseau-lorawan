// SPDX-License-Identifier: Apache-2.0
// Codec de trame LoRaWAN (structure filaire identique en 1.0.x et 1.1).
//
// Ce module ne fait AUCUN chiffrement ni vérification de MIC : il code et
// décode la structure. Le MIC est transporté tel quel et marqué comme non
// vérifié. La vérification et le chiffrement (AppSKey / NwkSKey, LoRaWAN 1.1)
// relèvent d'un module crypto séparé, à implémenter avec des vecteurs de test.
//
// Sécurité :
//   * capacité fixe, aucune allocation dynamique ;
//   * chaque longueur est vérifiée avant toute lecture ;
//   * entrées non fiables (réseau) : décodage défensif, statut explicite.
#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

#include "lsim/lora_phy.hpp"

namespace lsim::lorawan {

// Types de message (MType, bits 7..5 du MHDR).
enum class MType : std::uint8_t {
    JoinRequest = 0,
    JoinAccept = 1,
    UnconfirmedDataUp = 2,
    UnconfirmedDataDown = 3,
    ConfirmedDataUp = 4,
    ConfirmedDataDown = 5,
    RejoinRequest = 6,
    Proprietary = 7,
};

// Limites de la spécification.
inline constexpr std::size_t kMaxPhyPayload = 255;
inline constexpr std::size_t kMaxFOpts = 15;
inline constexpr std::size_t kMicSize = 4;
inline constexpr std::size_t kMaxFrmPayload = kMaxPhyPayload - 1 - 7 - 1 - kMicSize;  // 242
inline constexpr std::size_t kMinDataFrame = 1 + 7 + kMicSize;                         // 12

// Trame de données décodée. Tous les tableaux sont à capacité fixe.
struct DataFrame {
    MType mtype = MType::UnconfirmedDataUp;
    std::uint32_t dev_addr = 0;
    // FCtrl : sens uplink ou downlink (les bits ne sont pas les mêmes).
    bool adr = false;
    bool adr_ack_req = false;  // uplink uniquement
    bool ack = false;
    bool class_b = false;      // uplink uniquement
    bool f_pending = false;    // downlink uniquement
    std::uint16_t fcnt = 0;    // compteur de trames, 16 bits de poids faible
    std::array<std::uint8_t, kMaxFOpts> fopts{};
    std::uint8_t fopts_len = 0;
    bool has_fport = false;
    std::uint8_t fport = 0;
    std::array<std::uint8_t, kMaxFrmPayload> frm_payload{};
    std::uint8_t frm_payload_len = 0;
    std::array<std::uint8_t, kMicSize> mic{};  // non vérifié à ce stade
};

// Statuts propres au codec (étendent lora::Status via des codes dédiés).
enum class FrameStatus : std::int32_t {
    Ok = 0,
    BufferTooSmall = 1,
    MalformedFrame = 2,
    UnsupportedMajorVersion = 3,
    NotADataFrame = 4,
    FieldOutOfRange = 5,
};

struct DecodeResult {
    FrameStatus status;
    std::size_t consumed;  // octets lus (= taille de la trame)
};

// Taille de la trame encodée (0 si la trame est invalide).
LSIM_API std::size_t encoded_size(const DataFrame& f);

// Encode la trame dans `out` (capacité `cap`). Retourne le nombre d'octets écrits
// dans `out_written`, ou un statut d'erreur.
LSIM_API FrameStatus encode(const DataFrame& f, std::uint8_t* out, std::size_t cap,
                            std::size_t& out_written);

// Décode une trame PHY depuis `in` (longueur `len`). Lecture strictement bornée.
LSIM_API FrameStatus decode(const std::uint8_t* in, std::size_t len, DataFrame& out);

}  // namespace lsim::lorawan
