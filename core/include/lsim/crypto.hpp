// SPDX-License-Identifier: Apache-2.0
// Primitives cryptographiques LoRaWAN : AES-128, AES-CMAC (RFC 4493),
// chiffrement de FRMPayload et MIC des trames de données.
//
// Les primitives AES et CMAC proviennent de mbedTLS (Apache-2.0, version
// figée par SHA dans CMakeLists.txt). Ce fichier n'implémente AUCUN algorithme
// cryptographique : il assemble les blocs définis par la spécification LoRaWAN.
//
// Sécurité :
//   * les clés sont des tableaux de taille fixe ; leur effacement est confié
//     à mbedtls_platform_zeroize dans les chemins sensibles ;
//   * aucune allocation dynamique, aucune exception ;
//   * les longueurs sont vérifiées avant toute écriture.
#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

#include "lsim/lora_phy.hpp"

namespace lsim::crypto {

using Key128 = std::array<std::uint8_t, 16>;
using Block16 = std::array<std::uint8_t, 16>;
// Identifiant de type de trame (positions 1..4 du bloc Ai). Zéro par défaut ;
// utilisé en LoRaWAN 1.1 pour distinguer le chiffrement des FOpts.
using FrameTypeConstant = std::array<std::uint8_t, 4>;

enum class CryptoStatus : std::int32_t {
    Ok = 0,
    InvalidLength = 1,   // message au-delà de la borne (255 octets)
    InternalError = 2,   // échec inattendu de la bibliothèque sous-jacente
};

// Direction de la trame : Uplink = 0, Downlink = 1 (valeur du bloc Ai / B0).
enum class Direction : std::uint8_t { Uplink = 0, Downlink = 1 };

// AES-128 : chiffrement d'un bloc de 16 octets (ECB, usage interne uniquement).
LSIM_API CryptoStatus aes128_encrypt_block(const Key128& key, const Block16& in, Block16& out);

// AES-128 : déchiffrement d'un bloc de 16 octets (ECB, usage interne uniquement).
// Utilisé par le serveur pour chiffrer un join-accept (le device le déchiffre
// en appliquant le chiffrement AES).
LSIM_API CryptoStatus aes128_decrypt_block(const Key128& key, const Block16& in, Block16& out);

// AES-CMAC (RFC 4493) sur un message de longueur quelconque.
LSIM_API CryptoStatus aes_cmac(const Key128& key, const std::uint8_t* data, std::size_t len,
                               Block16& out);

// Chiffrement / déchiffrement de FRMPayload, en place (opération symétrique).
// fcnt32 : compteur de trame étendu sur 32 bits (FCntUp ou FCntDown).
LSIM_API CryptoStatus crypt_frm_payload(const Key128& key, Direction dir,
                                        std::uint32_t dev_addr, std::uint32_t fcnt32,
                                        std::uint8_t* payload, std::size_t len,
                                        const FrameTypeConstant& frame_type = FrameTypeConstant{});

// MIC d'une trame de données LoRaWAN 1.0.x (clé NwkSKey). `msg` = MHDR | FHDR |
// FPort | FRMPayload, sans le MIC. Pour 1.1, voir compute_uplink_mic_11 et
// compute_downlink_mic_11.
LSIM_API CryptoStatus compute_data_mic(const Key128& key, Direction dir,
                                       std::uint32_t dev_addr, std::uint32_t fcnt32,
                                       const std::uint8_t* msg, std::size_t msg_len,
                                       std::array<std::uint8_t, 4>& mic_out);

// MIC uplink LoRaWAN 1.1 : MIC = CMAC_S[0..1] || CMAC_F[0..1], où
//   CMAC_S = CMAC(SNwkSIntKey, B1 | msg) avec ConfFCnt, TxDr, TxCh,
//   CMAC_F = CMAC(FNwkSIntKey, B0 | msg) avec ConfFCnt = 0.
LSIM_API CryptoStatus compute_uplink_mic_11(const Key128& s_nwk_s_int_key,
                                            const Key128& f_nwk_s_int_key,
                                            std::uint16_t conf_fcnt, std::uint8_t tx_dr,
                                            std::uint8_t tx_ch, std::uint32_t dev_addr,
                                            std::uint32_t fcnt32, const std::uint8_t* msg,
                                            std::size_t msg_len,
                                            std::array<std::uint8_t, 4>& mic_out);

// MIC downlink LoRaWAN 1.1 : CMAC(SNwkSIntKey, B0 | msg) avec ConfFCnt, dir = 1.
LSIM_API CryptoStatus compute_downlink_mic_11(const Key128& s_nwk_s_int_key,
                                              std::uint16_t conf_fcnt, std::uint32_t dev_addr,
                                              std::uint32_t fcnt32, const std::uint8_t* msg,
                                              std::size_t msg_len,
                                              std::array<std::uint8_t, 4>& mic_out);

}  // namespace lsim::crypto
