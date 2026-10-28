// SPDX-License-Identifier: Apache-2.0
// Trame sécurisée LoRaWAN 1.1 : scellement (chiffrement + MIC) et ouverture
// (vérification du MIC + déchiffrement). Compartiment d'intégration entre le
// codec de trame, la crypto et les clés de session.
//
// Règles :
//   * le MIC est vérifié en temps constant AVANT tout déchiffrement ;
//   * le compteur 32 bits est fourni par l'appelant (serveur de réseau) et
//     doit correspondre aux 16 bits transmis, sinon rejet ;
//   * aucune allocation dynamique.
#pragma once

#include <cstddef>
#include <cstdint>

#include "lsim/crypto.hpp"
#include "lsim/lorawan_frame.hpp"
#include "lsim/lorawan_keys.hpp"

namespace lsim::lorawan {

// Statuts propres à la trame sécurisée (en complément de FrameStatus).
enum class SecureStatus : std::int32_t {
    Ok = 0,
    Frame = 1,          // erreur de codec (voir FrameStatus, valeur convertie)
    MicMismatch = 2,    // MIC invalide : trame non déchiffrée
    FCntMismatch = 3,   // compteur 32 bits incompatible avec les 16 bits reçus
    CryptoFailure = 4,  // échec de la bibliothèque crypto
    BufferTooSmall = 5,
    InvalidPayload = 6, // FRMPayload hors bornes ou port réservé
};

// Paramètres de contexte d'une trame uplink (fournis par la couche radio et le
// serveur de réseau).
struct UplinkContext {
    std::uint16_t conf_fcnt = 0;  // ConfFCnt : 0 sans ACK, sinon FCnt de la dernière downlink
    std::uint8_t tx_dr = 0;       // TxDr : index du débit d'émission
    std::uint8_t tx_ch = 0;       // TxCh : index du canal d'émission
    std::uint32_t fcnt32 = 0;     // compteur d'uplink complet (32 bits)
};

// Scelle une trame uplink. `frame.frm_payload` contient le texte clair ;
// il est chiffré (AppSKey si FPort > 0, NwkSEncKey si FPort == 0) puis le MIC
// est calculé. Écrit la trame PHY dans `out`.
LSIM_API SecureStatus seal_uplink(const DataFrame& frame, const SessionKeys11& keys,
                                  const UplinkContext& ctx, std::uint8_t* out, std::size_t cap,
                                  std::size_t& out_written);

// Ouvre une trame uplink : décode, vérifie le MIC puis déchiffre FRMPayload.
// En cas d'échec, `out` n'est pas exploitable.
LSIM_API SecureStatus open_uplink(const std::uint8_t* in, std::size_t len,
                                  const SessionKeys11& keys, const UplinkContext& ctx,
                                  DataFrame& out);

}  // namespace lsim::lorawan
