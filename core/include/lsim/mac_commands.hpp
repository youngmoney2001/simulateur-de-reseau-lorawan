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
//   * les CID non implémentés (BeaconTiming 0x12, déprécié) sont refusés
//     (`UnknownCommand`), car leur longueur ne peut pas être devinée.
//     classe B : PingSlot (0x10, 0x11) et Beacon (0x13) implémentés.
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
    DlChannel = 0x0A,     // DlChannelAns (up) / DlChannelReq (down)
    RxTimingSetup = 0x08, // RXTimingSetupAns (up) / RXTimingSetupReq (down)
    DeviceTime = 0x0D,    // DeviceTimeReq (up) / DeviceTimeAns (down)
    ForceRejoin = 0x0E,   // ForceRejoinReq (down, sans réponse)
    RejoinParamSetup = 0x0F,  // RejoinParamSetupAns (up) / RejoinParamSetupReq (down)
    Rekey = 0x0B,         // RekeyInd (up) / RekeyConf (down)
    AdrParamSetup = 0x0C, // ADRParamSetupAns (up) / ADRParamSetupReq (down)
    PingSlotInfo = 0x10,    // PingSlotInfoReq (up) / PingSlotInfoAns (down)
    PingSlotChannel = 0x11, // PingSlotChannelAns (up) / PingSlotChannelReq (down)
    BeaconFreq = 0x13,      // BeaconFreqAns (up) / BeaconFreqReq (down)
};

enum class MacStatus : std::int32_t {
    Ok = 0,
    BufferTooSmall = 1,
    MalformedPayload = 2,
    FieldOutOfRange = 3,
    UnknownCommand = 4,
};

inline constexpr std::size_t kMaxCommandBytes = 6;  // plus grande commande gérée (DeviceTimeAns)
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

// RXTimingSetupReq (down) : délai TX -> RX1 en secondes, Del 3:0 (0 -> 1 s), bits 7:4 RFU.
// Taille totale : 2 octets. Réponse RXTimingSetupAns : sans charge utile.
struct RxTimingSetupReq {
    std::uint8_t delay = 1;  // 0..15
};

// DeviceTimeAns (down) : secondes depuis l'époque GPS (32 bits LE) et fraction 1/256 s.
// Taille totale : 6 octets. Requête DeviceTimeReq : sans charge utile.
struct DeviceTimeAns {
    std::uint32_t seconds = 0;
    std::uint8_t fraction = 0;  // unités de 1/256 s
};

// ForceRejoinReq (down) : 16 bits LE. bits 15:14 RFU, 13:11 Period, 10:8 Max_Retries,
// bit 7 RFU, 6:4 RejoinType (0, 1 -> type 0 ; 2 -> type 2 ; 3..7 RFU), 3:0 DR.
// Taille totale : 3 octets. Aucune réponse.
struct ForceRejoinReq {
    std::uint8_t period = 0;       // 0..7
    std::uint8_t max_retries = 0;  // 0..7
    std::uint8_t rejoin_type = 0;  // 0..2
    std::uint8_t dr = 0;           // 0..15
};

// RejoinParamSetupReq (down) : MaxCountN 3:0 (C : rejoin au plus tous les 2^C+4 uplinks),
// MaxTimeN 7:4 (T : au plus tous les 2^T+10 s). Taille totale : 2 octets.
struct RejoinParamSetupReq {
    std::uint8_t max_count_n = 0;  // 0..15
    std::uint8_t max_time_n = 0;   // 0..15
};

// ADRParamSetupReq (down) : Limit_exp 7:4 (ADR_ACK_LIMIT = 2^Limit_exp), Delay_exp 3:0
// (ADR_ACK_DELAY = 2^Delay_exp), chacun dans 0..15. Taille totale : 2 octets.
struct AdrParamSetupReq {
    std::uint8_t limit_exp = 0;  // 0..15
    std::uint8_t delay_exp = 0;  // 0..15
};

// PingSlotInfoReq (up) : Periodicity 2:0 (période effective 0,96 x 2^P s, P = 7 : 128 s ;
// spec 14.1), bits 7:3 RFU. Taille totale : 2 octets.
struct PingSlotInfoReq {
    std::uint8_t periodicity = 0;  // 0..7
};

// PingSlotChannelReq (down) : fréquence en pas de 100 Hz (0 = plan par défaut), DR 3:0.
// Taille totale : 5 octets.
struct PingSlotChannelReq {
    std::uint32_t freq_100hz = 0;
    std::uint8_t dr = 0;  // 0..15
};

// PingSlotChannelAns (up) : bit 0 fréquence utilisable, bit 1 débit compatible ; bits 7:2 RFU.
struct PingSlotChannelAns {
    bool channel_freq_ok = false;
    bool data_rate_ok = false;
};

// BeaconFreqReq (down) : fréquence en pas de 100 Hz (0 = plan par défaut). Taille totale : 4 octets.
struct BeaconFreqReq {
    std::uint32_t freq_100hz = 0;
};

// BeaconFreqAns (up) : bit 0 fréquence de balise acceptée ; bits 7:1 RFU. Taille totale : 2 octets.
struct BeaconFreqAns {
    bool beacon_freq_ok = false;
};

// RejoinParamSetupAns (up) : bit 0 TimeOK, bits 7:1 RFU. Taille totale : 2 octets.
struct RejoinParamSetupAns {
    bool time_ok = false;
};

// DlChannelReq (down) : ChIndex 0..15 et fréquence RX1 en pas de 100 Hz (>= 100 MHz).
// Taille totale : 5 octets.
struct DlChannelReq {
    std::uint8_t ch_index = 0;
    std::uint32_t freq_100hz = 0;
};

// DlChannelAns (up) : bit 0 fréquence utilisable, bit 1 fréquence montante existante ;
// bits 7:2 RFU. Taille totale : 2 octets.
struct DlChannelAns {
    bool channel_freq_ok = false;
    bool uplink_freq_exists = false;
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
MacStatus encode(const RxTimingSetupReq& c, std::array<std::uint8_t, kMaxCommandBytes>& out, std::size_t& len);
MacStatus encode(const DeviceTimeAns& c, std::array<std::uint8_t, kMaxCommandBytes>& out, std::size_t& len);
MacStatus encode(const ForceRejoinReq& c, std::array<std::uint8_t, kMaxCommandBytes>& out, std::size_t& len);
MacStatus encode(const RejoinParamSetupReq& c, std::array<std::uint8_t, kMaxCommandBytes>& out, std::size_t& len);
MacStatus encode(const RejoinParamSetupAns& c, std::array<std::uint8_t, kMaxCommandBytes>& out, std::size_t& len);
MacStatus encode(const AdrParamSetupReq& c, std::array<std::uint8_t, kMaxCommandBytes>& out, std::size_t& len);
MacStatus encode(const PingSlotInfoReq& c, std::array<std::uint8_t, kMaxCommandBytes>& out, std::size_t& len);
MacStatus encode(const PingSlotChannelReq& c, std::array<std::uint8_t, kMaxCommandBytes>& out, std::size_t& len);
MacStatus encode(const PingSlotChannelAns& c, std::array<std::uint8_t, kMaxCommandBytes>& out, std::size_t& len);
MacStatus encode(const BeaconFreqReq& c, std::array<std::uint8_t, kMaxCommandBytes>& out, std::size_t& len);
MacStatus encode(const BeaconFreqAns& c, std::array<std::uint8_t, kMaxCommandBytes>& out, std::size_t& len);
MacStatus encode(const DlChannelReq& c, std::array<std::uint8_t, kMaxCommandBytes>& out, std::size_t& len);
MacStatus encode(const DlChannelAns& c, std::array<std::uint8_t, kMaxCommandBytes>& out, std::size_t& len);
MacStatus encode(const Rekey& c, Direction dir, std::array<std::uint8_t, kMaxCommandBytes>& out, std::size_t& len);

// Commandes sans charge utile : LinkCheckReq, DutyCycleAns, DevStatusReq, PingSlotInfoAns.
// (PingSlotInfoAns : le PDF 1.1 ne décrit pas de charge ; traité comme vide.)
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
MacStatus decode(const std::uint8_t* data, std::size_t len, RxTimingSetupReq& out);     // down
MacStatus decode(const std::uint8_t* data, std::size_t len, DeviceTimeAns& out);         // down
MacStatus decode(const std::uint8_t* data, std::size_t len, ForceRejoinReq& out);        // down
MacStatus decode(const std::uint8_t* data, std::size_t len, RejoinParamSetupReq& out);   // down
MacStatus decode(const std::uint8_t* data, std::size_t len, RejoinParamSetupAns& out);   // up
MacStatus decode(const std::uint8_t* data, std::size_t len, AdrParamSetupReq& out);     // down
MacStatus decode(const std::uint8_t* data, std::size_t len, PingSlotInfoReq& out);     // up
MacStatus decode(const std::uint8_t* data, std::size_t len, PingSlotChannelReq& out);   // down
MacStatus decode(const std::uint8_t* data, std::size_t len, PingSlotChannelAns& out);   // up
MacStatus decode(const std::uint8_t* data, std::size_t len, BeaconFreqReq& out);        // down
MacStatus decode(const std::uint8_t* data, std::size_t len, BeaconFreqAns& out);        // up
MacStatus decode(const std::uint8_t* data, std::size_t len, DlChannelReq& out);          // down
MacStatus decode(const std::uint8_t* data, std::size_t len, DlChannelAns& out);          // up
MacStatus decode(const std::uint8_t* data, std::size_t len, Rekey& out, Direction dir);

// ------------------------------------------------------------ FOpts

// Ajoute une commande encodée au champ FOpts (capacité 15 octets, §4.3.1.6).
// Refuse tout dépassement : `BufferTooSmall` si la commande ne tient pas.
MacStatus append_to_fopts(std::array<std::uint8_t, kMaxFOpts>& fopts, std::uint8_t& fopts_len,
                          const std::array<std::uint8_t, kMaxCommandBytes>& cmd, std::size_t cmd_len);

}  // namespace lsim::lorawan::mac
