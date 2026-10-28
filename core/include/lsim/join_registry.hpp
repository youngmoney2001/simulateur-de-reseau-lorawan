// SPDX-License-Identifier: Apache-2.0
// Registre serveur des compteurs de jointure par dispositif :
//   * DevNonce (join-request) : strictement croissant par (JoinEUI, DevEUI) ;
//   * RJcount0 (rejoin type 0 et 2) : par DevEUI, remis à zéro à chaque join-accept ;
//   * RJcount1 (rejoin type 1) : par (JoinEUI, DevEUI).
//
// Règles de sécurité :
//   * le MIC est vérifié AVANT toute création d'entrée ou tout enregistrement : un
//     message forgé ne peut ni faire avancer un compteur, ni consommer de mémoire ;
//   * capacité bornée : au-delà, un nouveau dispositif est refusé (échec fermé) ;
//   * déterminisme : table ordonnée (std::map), aucune dépendance à l'ordre de hachage.
#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <map>

#include "lsim/join.hpp"
#include "lsim/rejoin.hpp"

namespace lsim::lorawan {

enum class RegistryStatus : std::int32_t {
    Ok = 0,
    Malformed = 1,        // longueur, MHDR ou type invalide
    MicMismatch = 2,      // MIC faux : rien n'a été enregistré
    CryptoFailure = 3,
    Replayed = 4,         // compteur non croissant
    CapacityExceeded = 5, // trop de dispositifs
};

inline constexpr std::size_t kMaxRegistryDevices = 10'000;

class JoinRegistry {
public:
    explicit JoinRegistry(std::size_t max_devices = kMaxRegistryDevices) : max_devices_(max_devices) {}

    // Join-request : MIC par NwkKey, puis DevNonce strictement croissant.
    RegistryStatus accept_join_request(const std::uint8_t* in, std::size_t len,
                                       const crypto::Key128& nwk_key, JoinRequestFields& out);

    // Rejoin type 0 ou 2 : MIC par SNwkSIntKey, puis RJcount0 croissant.
    RegistryStatus accept_rejoin_02(const std::uint8_t* in, std::size_t len,
                                    const crypto::Key128& s_nwk_s_int_key, Rejoin02Fields& out);

    // Rejoin type 1 : MIC par JSIntKey, puis RJcount1 croissant.
    RegistryStatus accept_rejoin_1(const std::uint8_t* in, std::size_t len,
                                   const crypto::Key128& js_int_key, Rejoin1Fields& out);

    // Join-accept traité : RJcount0 repart de zéro (le DevNonce reste acquis).
    void on_join_accepted(const std::array<std::uint8_t, 8>& dev_eui);

    std::size_t device_count() const { return joins_.size() + rjcount0_.size(); }

private:
    using JoinKey = std::array<std::uint8_t, 16>;  // JoinEUI | DevEUI
    using Eui = std::array<std::uint8_t, 8>;

    struct JoinState {
        Counter16Guard dev_nonce;  // join-request
        Counter16Guard rjcount1;   // rejoin type 1
    };

    static JoinKey make_key(const Eui& join_eui, const Eui& dev_eui);
    // Capacité globale : dispositifs (JoinEUI, DevEUI) et DevEUI (type 0/2) confondus.
    bool has_room() const { return joins_.size() + rjcount0_.size() < max_devices_; }

    std::size_t max_devices_;
    std::map<JoinKey, JoinState> joins_;
    std::map<Eui, Counter16Guard> rjcount0_;  // indexé par DevEUI seul (type 0/2)
};

}  // namespace lsim::lorawan
