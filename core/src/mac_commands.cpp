// SPDX-License-Identifier: Apache-2.0
#include "lsim/mac_commands.hpp"

namespace lsim::lorawan::mac {
namespace {

using Buf = std::array<std::uint8_t, kMaxCommandBytes>;

// Taille de charge utile (sans CID) pour un CID et un sens ; -1 si non implémenté.
int payload_len(Direction dir, std::uint8_t cid) {
    if (dir == Direction::Uplink) {
        switch (cid) {
            case 0x02: return 0;  // LinkCheckReq
            case 0x03: return 1;  // LinkADRAns
            case 0x04: return 0;  // DutyCycleAns
            case 0x06: return 2;  // DevStatusAns
            case 0x0B: return 1;  // RekeyInd
            default: return -1;
        }
    }
    switch (cid) {
        case 0x02: return 2;  // LinkCheckAns
        case 0x03: return 4;  // LinkADRReq
        case 0x04: return 1;  // DutyCycleReq
        case 0x06: return 0;  // DevStatusReq
        case 0x0B: return 1;  // RekeyConf
        default: return -1;
    }
}

bool rfu_zero(std::uint8_t value, std::uint8_t rfu_mask) { return (value & rfu_mask) == 0; }

}  // namespace

// ------------------------------------------------------------ encodage

MacStatus encode(const LinkCheckAns& c, Buf& out, std::size_t& len) {
    if (c.margin == 255) return MacStatus::FieldOutOfRange;  // 255 réservé
    out = {};
    out[0] = static_cast<std::uint8_t>(Cid::LinkCheck);
    out[1] = c.margin;
    out[2] = c.gw_cnt;
    len = 3;
    return MacStatus::Ok;
}

MacStatus encode(const LinkAdrReq& c, Buf& out, std::size_t& len) {
    if (c.data_rate > 15 || c.tx_power > 15 || c.ch_mask_cntl > 7 || c.nb_trans > 15) {
        return MacStatus::FieldOutOfRange;
    }
    out = {};
    out[0] = static_cast<std::uint8_t>(Cid::LinkAdr);
    out[1] = static_cast<std::uint8_t>((c.data_rate << 4) | c.tx_power);
    out[2] = static_cast<std::uint8_t>(c.ch_mask & 0xFFu);
    out[3] = static_cast<std::uint8_t>(c.ch_mask >> 8);
    out[4] = static_cast<std::uint8_t>((c.ch_mask_cntl << 4) | c.nb_trans);
    len = 5;
    return MacStatus::Ok;
}

MacStatus encode(const LinkAdrAns& c, Buf& out, std::size_t& len) {
    out = {};
    out[0] = static_cast<std::uint8_t>(Cid::LinkAdr);
    out[1] = static_cast<std::uint8_t>((c.channel_mask_ack ? 0x01 : 0) | (c.data_rate_ack ? 0x02 : 0) |
                                       (c.power_ack ? 0x04 : 0));
    len = 2;
    return MacStatus::Ok;
}

MacStatus encode(const DutyCycleReq& c, Buf& out, std::size_t& len) {
    if (c.max_dcycle > 15) return MacStatus::FieldOutOfRange;
    out = {};
    out[0] = static_cast<std::uint8_t>(Cid::DutyCycle);
    out[1] = c.max_dcycle;
    len = 2;
    return MacStatus::Ok;
}

MacStatus encode(const DevStatusAns& c, Buf& out, std::size_t& len) {
    if (c.margin < -32 || c.margin > 31) return MacStatus::FieldOutOfRange;
    out = {};
    out[0] = static_cast<std::uint8_t>(Cid::DevStatus);
    out[1] = c.battery;
    out[2] = static_cast<std::uint8_t>(static_cast<std::uint8_t>(c.margin) & 0x3Fu);
    len = 3;
    return MacStatus::Ok;
}

MacStatus encode(const Rekey& c, Direction dir, Buf& out, std::size_t& len) {
    if (c.minor != kLoRaWan11Minor) return MacStatus::FieldOutOfRange;
    out = {};
    out[0] = static_cast<std::uint8_t>(Cid::Rekey);
    out[1] = c.minor;
    len = 2;
    (void)dir;  // RekeyInd (up) et RekeyConf (down) ont la même charge utile
    return MacStatus::Ok;
}

MacStatus encode_empty(Cid cid, Direction dir, Buf& out, std::size_t& len) {
    if (payload_len(dir, static_cast<std::uint8_t>(cid)) != 0) return MacStatus::UnknownCommand;
    out = {};
    out[0] = static_cast<std::uint8_t>(cid);
    len = 1;
    return MacStatus::Ok;
}

// ------------------------------------------------------------ décodage

MacStatus command_size(Direction dir, const std::uint8_t* data, std::size_t len, std::size_t& size) {
    size = 0;
    if (len == 0 || data == nullptr) return MacStatus::MalformedPayload;
    const int p = payload_len(dir, data[0]);
    if (p < 0) return MacStatus::UnknownCommand;
    const auto total = static_cast<std::size_t>(p) + 1;
    if (len < total) return MacStatus::MalformedPayload;
    size = total;
    return MacStatus::Ok;
}

MacStatus decode(const std::uint8_t* data, std::size_t len, LinkCheckAns& out) {
    if (len != 3 || data[0] != static_cast<std::uint8_t>(Cid::LinkCheck)) return MacStatus::MalformedPayload;
    if (data[1] == 255) return MacStatus::FieldOutOfRange;
    out.margin = data[1];
    out.gw_cnt = data[2];
    return MacStatus::Ok;
}

MacStatus decode(const std::uint8_t* data, std::size_t len, LinkAdrReq& out) {
    if (len != 5 || data[0] != static_cast<std::uint8_t>(Cid::LinkAdr)) return MacStatus::MalformedPayload;
    if (!rfu_zero(data[4], 0x80)) return MacStatus::MalformedPayload;  // bit 7 RFU
    out.data_rate = static_cast<std::uint8_t>(data[1] >> 4);
    out.tx_power = static_cast<std::uint8_t>(data[1] & 0x0F);
    out.ch_mask = static_cast<std::uint16_t>(data[2] | (data[3] << 8));
    out.ch_mask_cntl = static_cast<std::uint8_t>((data[4] >> 4) & 0x07);
    out.nb_trans = static_cast<std::uint8_t>(data[4] & 0x0F);
    return MacStatus::Ok;
}

MacStatus decode(const std::uint8_t* data, std::size_t len, LinkAdrAns& out) {
    if (len != 2 || data[0] != static_cast<std::uint8_t>(Cid::LinkAdr)) return MacStatus::MalformedPayload;
    if (!rfu_zero(data[1], 0xF8)) return MacStatus::MalformedPayload;  // bits 7:3 RFU
    out.channel_mask_ack = (data[1] & 0x01) != 0;
    out.data_rate_ack = (data[1] & 0x02) != 0;
    out.power_ack = (data[1] & 0x04) != 0;
    return MacStatus::Ok;
}

MacStatus decode(const std::uint8_t* data, std::size_t len, DutyCycleReq& out) {
    if (len != 2 || data[0] != static_cast<std::uint8_t>(Cid::DutyCycle)) return MacStatus::MalformedPayload;
    if (!rfu_zero(data[1], 0xF0)) return MacStatus::MalformedPayload;  // bits 7:4 RFU
    out.max_dcycle = static_cast<std::uint8_t>(data[1] & 0x0F);
    return MacStatus::Ok;
}

MacStatus decode(const std::uint8_t* data, std::size_t len, DevStatusAns& out) {
    if (len != 3 || data[0] != static_cast<std::uint8_t>(Cid::DevStatus)) return MacStatus::MalformedPayload;
    if (!rfu_zero(data[2], 0xC0)) return MacStatus::MalformedPayload;  // bits 7:6 RFU
    out.battery = data[1];
    // Margin signé sur 6 bits (complément à deux).
    const auto raw = static_cast<std::uint8_t>(data[2] & 0x3F);
    out.margin = static_cast<std::int8_t>((raw & 0x20) ? (raw | 0xC0) : raw);
    return MacStatus::Ok;
}

MacStatus decode(const std::uint8_t* data, std::size_t len, Rekey& out, Direction dir) {
    (void)dir;
    if (len != 2 || data[0] != static_cast<std::uint8_t>(Cid::Rekey)) return MacStatus::MalformedPayload;
    if (!rfu_zero(data[1], 0xF0)) return MacStatus::MalformedPayload;  // bits 7:4 RFU
    if ((data[1] & 0x0F) != kLoRaWan11Minor) return MacStatus::FieldOutOfRange;
    out.minor = kLoRaWan11Minor;
    return MacStatus::Ok;
}

// ------------------------------------------------------------ FOpts

MacStatus append_to_fopts(std::array<std::uint8_t, kMaxFOpts>& fopts, std::uint8_t& fopts_len,
                          const Buf& cmd, std::size_t cmd_len) {
    if (cmd_len == 0 || cmd_len > kMaxCommandBytes) return MacStatus::MalformedPayload;
    if (static_cast<std::size_t>(fopts_len) + cmd_len > kMaxFOpts) return MacStatus::BufferTooSmall;
    for (std::size_t i = 0; i < cmd_len; ++i) {
        fopts[fopts_len + i] = cmd[i];
    }
    fopts_len = static_cast<std::uint8_t>(fopts_len + cmd_len);
    return MacStatus::Ok;
}

}  // namespace lsim::lorawan::mac
