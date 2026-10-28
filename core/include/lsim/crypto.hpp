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

enum class CryptoStatus : std::int32_t {
    Ok = 0,
    InvalidLength = 1,   // message au-delà de la borne (255 octets)
    InternalError = 2,   // échec inattendu de la bibliothèque sous-jacente
};

// Direction de la trame : Uplink = 0, Downlink = 1 (valeur du bloc Ai / B0).
enum class Direction : std::uint8_t { Uplink = 0, Downlink = 1 };

// AES-128 : chiffrement d'un bloc de 16 octets (ECB, usage interne uniquement).
LSIM_API CryptoStatus aes128_encrypt_block(const Key128& key, const Block16& in, Block16& out);

// AES-CMAC (RFC 4493) sur un message de longueur quelconque.
LSIM_API CryptoStatus aes_cmac(const Key128& key, const std::uint8_t* data, std::size_t len,
                               Block16& out);

// Chiffrement / déchiffrement de FRMPayload, en place (opération symétrique).
// fcnt32 : compteur de trame étendu sur 32 bits (FCntUp ou FCntDown).
LSIM_API CryptoStatus crypt_frm_payload(const Key128& key, Direction dir,
                                        std::uint32_t dev_addr, std::uint32_t fcnt32,
                                        std::uint8_t* payload, std::size_t len);

// MIC d'une trame de données (1.0.x et 1.1 pour la clé NwkSKey / SNwkSIntKey
// en mode 1.0 compatible). `msg` = MHDR | FHDR | FPort | FRMPayload (sans MIC).
LSIM_API CryptoStatus compute_data_mic(const Key128& key, Direction dir,
                                       std::uint32_t dev_addr, std::uint32_t fcnt32,
                                       const std::uint8_t* msg, std::size_t msg_len,
                                       std::array<std::uint8_t, 4>& mic_out);

}  // namespace lsim::crypto
