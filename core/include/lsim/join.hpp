// SPDX-License-Identifier: Apache-2.0
// Jointure OTAA LoRaWAN 1.1 : join-request et join-accept, côté device et côté
// serveur. Les vecteurs proviennent de TTN (Apache-2.0), pkg/crypto/join_messages_test.go.
//
// Convention d'octets : JoinEUI, DevEUI, DevNonce et JoinNonce sont en ordre de
// transmission (LSB first). Les fonctions de MIC prennent les octets exactement
// comme ils sont transmis.
//
// Règles :
//   * le MIC est vérifié en temps constant avant toute exposition des champs ;
//   * le join-accept est chiffré avec NwkKey (1.1) ; le MIC utilise JSIntKey si
//     OptNeg (bit 7 de DLSettings) vaut 1, sinon NwkKey (réseau 1.0.x) ;
//   * aucune allocation dynamique ; les tailles sont fixes et vérifiées.
//
// Hors périmètre de ce module : le suivi des DevNonce déjà utilisés (état du
// serveur de jointure) et le rejoin. Ils doivent être gérés par l'appelant.
#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

#include "lsim/crypto.hpp"
#include "lsim/lorawan_keys.hpp"

namespace lsim::lorawan {

enum class JoinStatus : std::int32_t {
    Ok = 0,
    BufferTooSmall = 1,
    InvalidLength = 2,
    InvalidMHDR = 3,
    MicMismatch = 4,
    CryptoFailure = 5,
    FieldOutOfRange = 6,
};

inline constexpr std::size_t kJoinRequestSize = 23;      // MHDR | JoinEUI | DevEUI | DevNonce | MIC
inline constexpr std::size_t kJoinAcceptSizeNoCfl = 17;  // MHDR | 16 octets chiffrés
inline constexpr std::size_t kJoinAcceptSizeCfl = 33;    // MHDR | 32 octets chiffrés
inline constexpr std::uint8_t kMhdrJoinRequest = 0x00;
inline constexpr std::uint8_t kMhdrJoinAccept = 0x20;
inline constexpr std::uint8_t kJoinReqTypeJoin = 0xFF;   // JoinReqType d'une réponse à une join-request

struct JoinRequestFields {
    std::array<std::uint8_t, 8> join_eui{};
    std::array<std::uint8_t, 8> dev_eui{};
    std::array<std::uint8_t, 2> dev_nonce{};
};

struct JoinAcceptFields {
    std::array<std::uint8_t, 3> join_nonce{};  // AppNonce (1.0) / JoinNonce (1.1)
    std::array<std::uint8_t, 3> net_id{};
    std::uint32_t dev_addr = 0;
    std::uint8_t dl_settings = 0;              // bit 7 = OptNeg, bits 6..4 RX2DR, 3..0 RX1DROffset
    std::uint8_t rx_delay = 0;
    bool has_cflist = false;
    std::array<std::uint8_t, 16> cflist{};
};

// ----------------------------------------------------------- Join-request

// MIC d'une join-request (AES-CMAC avec NwkKey, 4 premiers octets).
// msg = MHDR | JoinEUI | DevEUI | DevNonce, 19 octets.
LSIM_API JoinStatus compute_join_request_mic(const crypto::Key128& nwk_key,
                                             const std::uint8_t* msg, std::size_t len,
                                             std::array<std::uint8_t, 4>& mic);

// Encode une join-request complète (23 octets). Écrit dans out_written.
LSIM_API JoinStatus encode_join_request(const JoinRequestFields& f, const crypto::Key128& nwk_key,
                                        std::uint8_t* out, std::size_t cap,
                                        std::size_t& out_written);

// Décode et vérifie le MIC d'une join-request reçue par le serveur.
LSIM_API JoinStatus decode_join_request(const std::uint8_t* in, std::size_t len,
                                        const crypto::Key128& nwk_key, JoinRequestFields& out);

// ----------------------------------------------------------- Join-accept

// Chiffrement du join-accept côté serveur : AES déchiffrement bloc par bloc, en place.
// len doit valoir 16 ou 32. Le device applique join_accept_decrypt pour revenir au clair.
LSIM_API JoinStatus join_accept_encrypt(const crypto::Key128& key, std::uint8_t* data,
                                        std::size_t len);

// Déchiffrement du join-accept côté device : AES chiffrement bloc par bloc, en place.
LSIM_API JoinStatus join_accept_decrypt(const crypto::Key128& key, std::uint8_t* data,
                                        std::size_t len);

// MIC 1.1 d'un join-accept (CMAC avec JSIntKey).
// msg = MHDR | JoinNonce | NetID | DevAddr | DLSettings | RxDelay | [CFList], 13 ou 29 octets.
// join_req_type = 0xFF pour une réponse à une join-request.
LSIM_API JoinStatus compute_join_accept_mic_11(const crypto::Key128& js_int_key,
                                               std::uint8_t join_req_type,
                                               const std::array<std::uint8_t, 8>& join_eui,
                                               const std::array<std::uint8_t, 2>& dev_nonce,
                                               const std::uint8_t* msg, std::size_t len,
                                               std::array<std::uint8_t, 4>& mic);

// MIC 1.0.x d'un join-accept (CMAC avec AppKey ou NwkKey, OptNeg = 0).
LSIM_API JoinStatus compute_join_accept_mic_legacy(const crypto::Key128& key,
                                                   const std::uint8_t* msg, std::size_t len,
                                                   std::array<std::uint8_t, 4>& mic);

// Encode un join-accept complet (17 ou 33 octets) côté serveur.
// dev_eui sert à dériver JSIntKey lorsque OptNeg = 1 ; ignoré sinon.
LSIM_API JoinStatus encode_join_accept(const JoinAcceptFields& f, const crypto::Key128& nwk_key,
                                       const std::array<std::uint8_t, 8>& dev_eui,
                                       const std::array<std::uint8_t, 8>& join_eui,
                                       const std::array<std::uint8_t, 2>& dev_nonce,
                                       std::uint8_t* out, std::size_t cap,
                                       std::size_t& out_written);

// Ouvre un join-accept côté device : déchiffrement puis vérification du MIC
// (clé choisie selon OptNeg lu dans le message déchiffré). En cas d'échec,
// `out` est remis à zéro.
LSIM_API JoinStatus decode_join_accept(const std::uint8_t* in, std::size_t len,
                                       const crypto::Key128& nwk_key,
                                       const std::array<std::uint8_t, 8>& dev_eui,
                                       const std::array<std::uint8_t, 8>& join_eui,
                                       const std::array<std::uint8_t, 2>& dev_nonce,
                                       JoinAcceptFields& out);

}  // namespace lsim::lorawan
