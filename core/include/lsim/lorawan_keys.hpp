// SPDX-License-Identifier: Apache-2.0
// Dérivation des clés de session LoRaWAN 1.1 (à partir de NwkKey et AppKey).
//
// Formules : chaque clé = AES-128(clé_racine, tag | données | pad16), tags :
//   0x01 FNwkSIntKey, 0x02 AppSKey, 0x03 SNwkSIntKey, 0x04 NwkSEncKey,
//   0x05 JSEncKey, 0x06 JSIntKey.
//
// Convention d'ordre des octets : les identifiants et nonces sont passés dans
// l'ordre de transmission sur les ondes (little-endian), tel que défini par la
// spécification. Ce module n'a PAS encore été validé contre les vecteurs de
// test officiels LoRa Alliance : c'est une étape ouverte (voir ROADMAP.md).
#pragma once

#include <array>
#include <cstdint>

#include "lsim/crypto.hpp"

namespace lsim::lorawan {

using crypto::Key128;

struct JoinKeys {
    Key128 js_enc_key;  // JSEncKey (chiffrement du join-accept en rejoin)
    Key128 js_int_key;  // JSIntKey (intégrité des rejoin type 1 et join-accept)
};

struct SessionKeys11 {
    Key128 f_nwk_s_int_key;  // FNwkSIntKey : MIC uplink (partie 2 octets)
    Key128 s_nwk_s_int_key;  // SNwkSIntKey : MIC uplink (partie 2 octets) et downlink
    Key128 nwk_s_enc_key;    // NwkSEncKey : chiffrement des commandes MAC (port 0, FOpts)
    Key128 app_s_key;        // AppSKey : chiffrement de la charge applicative
};

// Clés de vie des serveurs de jointure, dérivées de NwkKey et DevEUI (8 octets).
LSIM_API crypto::CryptoStatus derive_join_keys(const Key128& nwk_key,
                                      const std::array<std::uint8_t, 8>& dev_eui,
                                      JoinKeys& out);

// Clés de session 1.1 après un join-accept réussi.
//   join_nonce : 3 octets, join_eui : 8 octets, dev_nonce : 2 octets.
LSIM_API crypto::CryptoStatus derive_session_keys_11(const Key128& nwk_key, const Key128& app_key,
                                            const std::array<std::uint8_t, 3>& join_nonce,
                                            const std::array<std::uint8_t, 8>& join_eui,
                                            const std::array<std::uint8_t, 2>& dev_nonce,
                                            SessionKeys11& out);

}  // namespace lsim::lorawan
