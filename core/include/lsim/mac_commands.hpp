// SPDX-License-Identifier: Apache-2.0
// Commandes MAC LoRaWAN 1.1 (codec) : LinkCheck, LinkADR, DutyCycle, DevStatus, Rekey.
//
// Structure (LoRaWAN 1.1, §5.2 à §5.10) : un octet CID puis une charge utile de
// longueur fixe selon le sens (uplink ou downlink). Ce module code et décode ces
// octets ; il ne décide ni de la politique ADR ni de l'état de l'appareil.
//
// Sécurité :
//   * chaque longueur est vérifiée avant toute lecture ;
//   * capacité fixe, aucune allocation dynamique ;
//   * encodage canonique : les bits RFU doivent valoir 0 à la lecture (rejet sinon) ;
//   * les CID non implémentés (RXTimingSetup, DeviceTime, …) sont refusés
//     (`UnknownCommand`), car leur longueur ne peut pas être devinée. Les CID 0x08
//     (RXTimingSetup), 0x0D (DeviceTime) et suivants restent à implémenter.
#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

#include "lsim/lorawan_frame.hpp"

namespace lsim::lorawan::mac {

enum class Direction : std::uint8_t { Uplink, Downlink };

// CID communs (LoRaWAN 1.1, tableau 4). Le même CID désigne une requête dans un
// sens et sa réponse dans l'autre.
enum class Cid : std::uint8_t {
    LinkCheck = 0x02,   // LinkCheckReq (up) / LinkCheckAns (down)
    LinkAdr = 0x03,     // LinkADRAns (up) / LinkADRReq (down)
    DutyCycle = 0x04,   // DutyCycleAns (up) / DutyCycleReq (down)
    DevStatus = 0x06,   // DevStatusAns (up) / DevStatusReq (down)
    RxParamSetup = 0x05,  // RXParamSetupAns (up) / RXParamSetupReq (down)
    NewChannel = 0x07,    // NewChannelAns (up) / NewChannelReq (down)
    Rekey = 0x0B,         // RekeyInd (up) / RekeyConf (down)
};

enum class MacStatus : std::int32_t {
    Ok = 0,
    BufferTooSmall = 1,
    MalformedPayload = 2,
    FieldOutOfRange = 3,
    UnknownCommand = 4,
};

inline constexpr std::size_t kMaxCommandBytes = 6;  // plus grande commande gérée (NewChannelReq)
inline constexpr std::uint8_t kLoRaWan11Minor = 1;   // « LoRaWAN x.1 » dans RekeyInd/Conf

// ------------------------------------------------------------ charges utiles

// LinkCheckAns (down) : Margin 0..254 (dB), GwCnt 0..255.  Taille totale : 3 octets.
struct LinkCheckAns {
    std::uint8_t margin = 0;
    std::uint8_t gw_cnt = 0;
};

// LinkADRReq (down) : DataRate et TXPower sur 4 bits (15 = ignorer le champ),
// ChMask 16 bits (LSB = canal 1), ChMaskCntl 0..7, NbTrans 0..15 (0 = inchangé).
// Taille totale : 5 octets.
struct LinkAdrReq {
    std::uint8_t data_rate = 0;
    std::uint8_t tx_power = 0;
    std::uint16_t ch_mask = 0;
    std::uint8_t ch_mask_cntl = 0;
    std::uint8_t nb_trans = 1;
};

// LinkADRAns (up) : trois acquittements. Taille totale : 2 octets.
struct LinkAdrAns {
    bool channel_mask_ack = false;
    bool data_rate_ack = false;
    bool power_ack = false;
};

// DutyCycleReq (down) : MaxDCycle 0..15, duty cycle agrégé = 1 / 2^MaxDCycle
// (0 = pas de limite, hors limite réglementaire). Taille totale : 2 octets.
struct DutyCycleReq {
    std::uint8_t max_dcycle = 0;
};

// DevStatusAns (up) : Battery (0 = externe, 255 = non mesurée) et Margin signé
// sur 6 bits, de -32 à 31 dB. Taille totale : 3 octets.
struct DevStatusAns {
    std::uint8_t battery = 0;
    std::int8_t margin = 0;
};

// RekeyInd (up) et RekeyConf (down) : version LoRaWAN de l'appareil ou du serveur.
// Seule la valeur 1 (LoRaWAN x.1) est acceptée. Taille totale : 2 octets.
struct Rekey {
    std::uint8_t minor = kLoRaWan11Minor;
};

// RXParamSetupReq (down) : DLsettings (RX2DataRate 3:0, RX1DRoffset 6:4, bit 7 RFU)
// et fréquence RX2 sur 24 bits en pas de 100 Hz (0 interdit ici, < 100 MHz réservé).
// Taille totale : 5 octets.
struct RxParamSetupReq {
    std::uint8_t rx2_data_rate = 0;   // 0..15
    std::uint8_t rx1_dr_offset = 0;   // 0..7
    std::uint32_t freq_100hz = 0;     // 0..0xFFFFFF, Hz = 100 x valeur
};

// RXParamSetupAns (up) : bit 0 canal, bit 1 débit RX2, bit 2 offset RX1 ; bits 7:3 RFU.
// Taille totale : 2 octets.
struct RxParamSetupAns {
    bool channel_ack = false;
    bool rx2_data_rate_ack = false;
    bool rx1_dr_offset_ack = false;
};

// NewChannelReq (down) : ChIndex, Freq (24 bits, pas de 100 Hz, 0 = désactive le canal),
// DrRange (MinDR 3:0, MaxDR 7:4). Taille totale : 6 octets.
struct NewChannelReq {
    std::uint8_t ch_index = 0;        // 0..15
    std::uint32_t freq_100hz = 0;     // 0 ou >= 1 000 000 (100 MHz)
    std::uint8_t min_dr = 0;          // 0..15
    std::uint8_t max_dr = 0;          // 0..15
};

// NewChannelAns (up) : bit 0 plage de débits, bit 1 fréquence ; bits 7:2 RFU.
// Taille totale : 2 octets.
struct NewChannelAns {
    bool dr_range_ack = false;
    bool channel_freq_ack = false;
};

// ------------------------------------------------------------ encodage

// Chaque encodeur écrit CID + charge utile dans `out` et renvoie la longueur.
MacStatus encode(const LinkCheckAns& c, std::array<std::uint8_t, kMaxCommandBytes>& out, std::size_t& len);
MacStatus encode(const LinkAdrReq& c, std::array<std::uint8_t, kMaxCommandBytes>& out, std::size_t& len);
MacStatus encode(const LinkAdrAns& c, std::array<std::uint8_t, kMaxCommandBytes>& out, std::size_t& len);
MacStatus encode(const DutyCycleReq& c, std::array<std::uint8_t, kMaxCommandBytes>& out, std::size_t& len);
MacStatus encode(const DevStatusAns& c, std::array<std::uint8_t, kMaxCommandBytes>& out, std::size_t& len);
MacStatus encode(const RxParamSetupReq& c, std::array<std::uint8_t, kMaxCommandBytes>& out, std::size_t& len);
MacStatus encode(const RxParamSetupAns& c, std::array<std::uint8_t, kMaxCommandBytes>& out, std::size_t& len);
MacStatus encode(const NewChannelReq& c, std::array<std::uint8_t, kMaxCommandBytes>& out, std::size_t& len);
MacStatus encode(const NewChannelAns& c, std::array<std::uint8_t, kMaxCommandBytes>& out, std::size_t& len);
MacStatus encode(const Rekey& c, Direction dir, std::array<std::uint8_t, kMaxCommandBytes>& out, std::size_t& len);

// Commandes sans charge utile : LinkCheckReq, DutyCycleAns, DevStatusReq.
MacStatus encode_empty(Cid cid, Direction dir, std::array<std::uint8_t, kMaxCommandBytes>& out, std::size_t& len);

// ------------------------------------------------------------ décodage

// Taille totale (CID compris) de la commande commençant à `data[0]`, dans le sens
// `dir`. Refuse un CID non implémenté (UnknownCommand) et une commande tronquée
// (MalformedPayload). Ne lit jamais au-delà de `len`.
MacStatus command_size(Direction dir, const std::uint8_t* data, std::size_t len, std::size_t& size);

// Les décodeurs attendent exactement la commande complète (CID compris).
MacStatus decode(const std::uint8_t* data, std::size_t len, LinkCheckAns& out);      // down
MacStatus decode(const std::uint8_t* data, std::size_t len, LinkAdrReq& out);        // down
MacStatus decode(const std::uint8_t* data, std::size_t len, LinkAdrAns& out);        // up
MacStatus decode(const std::uint8_t* data, std::size_t len, DutyCycleReq& out);      // down
MacStatus decode(const std::uint8_t* data, std::size_t len, DevStatusAns& out);      // up
MacStatus decode(const std::uint8_t* data, std::size_t len, RxParamSetupReq& out);     // down
MacStatus decode(const std::uint8_t* data, std::size_t len, RxParamSetupAns& out);     // up
MacStatus decode(const std::uint8_t* data, std::size_t len, NewChannelReq& out);       // down
MacStatus decode(const std::uint8_t* data, std::size_t len, NewChannelAns& out);       // up
MacStatus decode(const std::uint8_t* data, std::size_t len, Rekey& out, Direction dir);

// ------------------------------------------------------------ FOpts

// Ajoute une commande encodée au champ FOpts (capacité 15 octets, §4.3.1.6).
// Refuse tout dépassement : `BufferTooSmall` si la commande ne tient pas.
MacStatus append_to_fopts(std::array<std::uint8_t, kMaxFOpts>& fopts, std::uint8_t& fopts_len,
                          const std::array<std::uint8_t, kMaxCommandBytes>& cmd, std::size_t cmd_len);

}  // namespace lsim::lorawan::mac
