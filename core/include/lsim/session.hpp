// SPDX-License-Identifier: Apache-2.0
// Moteur de session d'un dispositif OTAA LoRaWAN 1.1 : clés et DevAddr de la session,
// compteurs (FCntUp, NFCntDown, AFCntDown), ADR_ACK et rekey, enchaînés par cycle d'uplink.
//
// Cycle d'un uplink (ordre imposé, comme sur un dispositif de classe A) :
//   begin_uplink  -> plan : compteur FCntUp, RekeyInd, ADRACKReq et canaux (ADR_ACK_CNT
//                    est incrémenté ici, car ADRACKReq fait partie de la trame émise)
//   receive_downlink (0 ou 1 fois, pendant les fenêtres de réception de cet uplink)
//   end_uplink    -> commit : FCntUp + 1, rekey (RekeyConf), réinitialisation ADR_ACK_CNT
//                    si une trame descendante a été reçue
//
// Règles (LoRaWAN 1.1 §4.3.1.5 et §6.1.2.6) :
//   * au join-accept traité : FCntUp, NFCntDown et AFCntDown repartent de 0 ;
//   * une trame descendante est acceptée si son compteur est >= au compteur attendu, qui
//     passe alors à compteur + 1 (interprétation « prochain attendu ») ; sinon rejeu ;
//   * NeedsJoin (rekey sans RekeyConf) : plus aucun uplink tant qu'un nouveau join n'a pas
//     été traité.
// Le moteur ne vérifie pas les MIC : il reçoit le compteur déjà authentifié (voir
// secure_frame.hpp, seul chemin de vérification du MIC).
#pragma once

#include <cstdint>

#include "lsim/adr.hpp"
#include "lsim/lorawan_keys.hpp"
#include "lsim/rekey.hpp"

namespace lsim::lorawan::session {

enum class SessionState : std::uint8_t {
    NoSession = 0,  // aucun join-accept traité
    Active = 1,     // uplinks et downlinks autorisés
    NeedsJoin = 2,  // rekey échoué : rejoindre
};

enum class SessionStatus : std::int32_t {
    Ok = 0,
    NoSession = 1,         // pas de session active
    CycleError = 2,        // appel hors d'un cycle, ou cycle déjà ouvert
    Replay = 3,            // compteur descendant déjà consommé
    InvalidParameter = 4,  // paramètre hors plage
    CounterExhausted = 5,  // FCntUp à 2^32 : rejoindre avant tout nouvel uplink
};

struct InitParams {
    std::uint32_t dev_addr = 0;
    std::uint8_t dr = 0;
    std::uint8_t min_dr = 0;
    std::uint8_t tx_power_index = 0;
    std::uint8_t default_tx_power_index = 0;
};

struct UplinkPlan {
    std::uint32_t fcnt32 = 0;  // FCntUp à utiliser (le FCnt 16 bits en est la partie basse)
    bool rekey_ind = false;    // RekeyInd à inclure dans cette trame
    bool ack_req = false;      // ADRACKReq à inclure dans cette trame
    bool default_channels_reenabled = false;
};

struct DownlinkInfo {
    bool uses_nf = true;             // NFCntDown (FPort absent ou 0) ; sinon AFCntDown
    std::uint32_t fcnt32 = 0;        // compteur descendant authentifié
    bool conf_received = false;      // RekeyConf dans cette trame
    std::uint8_t server_version = 0; // version du RekeyConf
};

struct UplinkEnd {
    SessionState state = SessionState::NoSession;
};

struct Snapshot {
    SessionState state = SessionState::NoSession;
    std::uint32_t dev_addr = 0;
    std::uint64_t fcnt_up = 0;
    std::uint64_t nf_cnt_dwn = 0;
    std::uint64_t af_cnt_dwn = 0;
    std::uint8_t dr = 0;
    std::uint8_t tx_power_index = 0;
    std::uint64_t ack_cnt = 0;
    bool cycle_open = false;
};

class Session {
public:
    // Join-accept traité : nouvelles clés, DevAddr, compteurs à 0, rekey en attente.
    SessionStatus join_accepted(const SessionKeys11& keys, const InitParams& init);
    // limit_exp / delay_exp : ADR_ACK_LIMIT et ADR_ACK_DELAY en exposants (0..15).
    SessionStatus begin_uplink(std::uint8_t limit_exp, std::uint8_t delay_exp, UplinkPlan& plan);
    SessionStatus receive_downlink(const DownlinkInfo& d);
    SessionStatus end_uplink(UplinkEnd& out);

    SessionState state() const;
    Snapshot snapshot() const;
    // Clés de session : lecture pour la couche de scellement uniquement.
    const SessionKeys11& keys() const { return keys_; }

private:
    bool joined_ = false;
    bool cycle_open_ = false;
    bool rx_seen_ = false;
    bool conf_seen_ = false;
    std::uint64_t admin_limit_ = 0;  // ADR_ACK_LIMIT = 2^limit_exp, fixé à begin_uplink
    std::uint8_t conf_version_ = 0;
    SessionKeys11 keys_{};
    std::uint32_t dev_addr_ = 0;
    std::uint64_t fcnt_up_ = 0;
    std::uint64_t nf_cnt_dwn_ = 0;
    std::uint64_t af_cnt_dwn_ = 0;
    rekey::DeviceRekey rekey_{};
    adr::DeviceAdrState adr_{};
};

}  // namespace lsim::lorawan::session
