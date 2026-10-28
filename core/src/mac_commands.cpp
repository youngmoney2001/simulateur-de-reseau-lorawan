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
            case 0x05: return 1;  // RXParamSetupAns
            case 0x07: return 1;  // NewChannelAns
            case 0x08: return 0;  // RXTimingSetupAns
            case 0x0A: return 1;  // DlChannelAns
            case 0x0D: return 0;  // DeviceTimeReq
            case 0x0F: return 1;  // RejoinParamSetupAns
            case 0x0C: return 0;  // ADRParamSetupAns
            case 0x10: return 1;  // PingSlotInfoReq
            case 0x11: return 1;  // PingSlotChannelAns
            case 0x13: return 1;  // BeaconFreqAns
            case 0x0B: return 1;  // RekeyInd
            default: return -1;
        }
    }
    switch (cid) {
        case 0x02: return 2;  // LinkCheckAns
        case 0x03: return 4;  // LinkADRReq
        case 0x04: return 1;  // DutyCycleReq
        case 0x06: return 0;  // DevStatusReq
        case 0x05: return 4;  // RXParamSetupReq
        case 0x07: return 5;  // NewChannelReq
        case 0x08: return 1;  // RXTimingSetupReq
        case 0x0A: return 4;  // DlChannelReq
        case 0x0D: return 5;  // DeviceTimeAns
        case 0x0E: return 2;  // ForceRejoinReq
        case 0x0F: return 1;  // RejoinParamSetupReq
        case 0x0C: return 1;  // ADRParamSetupReq
        case 0x10: return 0;  // PingSlotInfoAns
        case 0x11: return 4;  // PingSlotChannelReq
        case 0x13: return 3;  // BeaconFreqReq
        case 0x0B: return 1;  // RekeyConf
        default: return -1;
    }
}

bool rfu_zero(std::uint8_t value, std::uint8_t rfu_mask) { return (value & rfu_mask) == 0; }

// Fréquence codée sur 24 bits LE, en pas de 100 Hz : 0 (canal désactivé) ou >= 100 MHz.
bool freq_valid(std::uint32_t f) { return f <= 0xFFFFFFu && (f == 0 || f >= 1'000'000u); }

std::uint32_t read_u24(const std::uint8_t* p) {
    return static_cast<std::uint32_t>(p[0]) | (static_cast<std::uint32_t>(p[1]) << 8) |
           (static_cast<std::uint32_t>(p[2]) << 16);
}

void write_u24(std::uint8_t* p, std::uint32_t v) {
    p[0] = static_cast<std::uint8_t>(v & 0xFFu);
    p[1] = static_cast<std::uint8_t>((v >> 8) & 0xFFu);
    p[2] = static_cast<std::uint8_t>((v >> 16) & 0xFFu);
}

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

MacStatus encode(const RxParamSetupReq& c, Buf& out, std::size_t& len) {
    if (c.rx2_data_rate > 15 || c.rx1_dr_offset > 7 || c.freq_100hz > 0xFFFFFFu || !freq_valid(c.freq_100hz)) {
        return MacStatus::FieldOutOfRange;
    }
    out = {};
    out[0] = static_cast<std::uint8_t>(Cid::RxParamSetup);
    out[1] = static_cast<std::uint8_t>((c.rx1_dr_offset << 4) | c.rx2_data_rate);
    write_u24(&out[2], c.freq_100hz);
    len = 5;
    return MacStatus::Ok;
}

MacStatus encode(const RxParamSetupAns& c, Buf& out, std::size_t& len) {
    out = {};
    out[0] = static_cast<std::uint8_t>(Cid::RxParamSetup);
    out[1] = static_cast<std::uint8_t>((c.channel_ack ? 0x01 : 0) | (c.rx2_data_rate_ack ? 0x02 : 0) |
                                       (c.rx1_dr_offset_ack ? 0x04 : 0));
    len = 2;
    return MacStatus::Ok;
}

MacStatus encode(const NewChannelReq& c, Buf& out, std::size_t& len) {
    if (c.ch_index > 15 || c.min_dr > 15 || c.max_dr > 15 || !freq_valid(c.freq_100hz)) {
        return MacStatus::FieldOutOfRange;
    }
    out = {};
    out[0] = static_cast<std::uint8_t>(Cid::NewChannel);
    out[1] = c.ch_index;
    write_u24(&out[2], c.freq_100hz);
    out[5] = static_cast<std::uint8_t>((c.max_dr << 4) | c.min_dr);
    len = 6;
    return MacStatus::Ok;
}

MacStatus encode(const NewChannelAns& c, Buf& out, std::size_t& len) {
    out = {};
    out[0] = static_cast<std::uint8_t>(Cid::NewChannel);
    out[1] = static_cast<std::uint8_t>((c.dr_range_ack ? 0x01 : 0) | (c.channel_freq_ack ? 0x02 : 0));
    len = 2;
    return MacStatus::Ok;
}

MacStatus encode(const RxTimingSetupReq& c, Buf& out, std::size_t& len) {
    if (c.delay > 15) return MacStatus::FieldOutOfRange;
    out = {};
    out[0] = static_cast<std::uint8_t>(Cid::RxTimingSetup);
    out[1] = c.delay;
    len = 2;
    return MacStatus::Ok;
}

MacStatus encode(const DeviceTimeAns& c, Buf& out, std::size_t& len) {
    out = {};
    out[0] = static_cast<std::uint8_t>(Cid::DeviceTime);
    out[1] = static_cast<std::uint8_t>(c.seconds & 0xFFu);
    out[2] = static_cast<std::uint8_t>((c.seconds >> 8) & 0xFFu);
    out[3] = static_cast<std::uint8_t>((c.seconds >> 16) & 0xFFu);
    out[4] = static_cast<std::uint8_t>((c.seconds >> 24) & 0xFFu);
    out[5] = c.fraction;
    len = 6;
    return MacStatus::Ok;
}

MacStatus encode(const ForceRejoinReq& c, Buf& out, std::size_t& len) {
    if (c.period > 7 || c.max_retries > 7 || c.rejoin_type > 2 || c.dr > 15) return MacStatus::FieldOutOfRange;
    const std::uint16_t word = static_cast<std::uint16_t>((c.period << 11) | (c.max_retries << 8) |
                                                          (c.rejoin_type << 4) | c.dr);
    out = {};
    out[0] = static_cast<std::uint8_t>(Cid::ForceRejoin);
    out[1] = static_cast<std::uint8_t>(word & 0xFFu);
    out[2] = static_cast<std::uint8_t>(word >> 8);
    len = 3;
    return MacStatus::Ok;
}

MacStatus encode(const RejoinParamSetupReq& c, Buf& out, std::size_t& len) {
    if (c.max_count_n > 15 || c.max_time_n > 15) return MacStatus::FieldOutOfRange;
    out = {};
    out[0] = static_cast<std::uint8_t>(Cid::RejoinParamSetup);
    out[1] = static_cast<std::uint8_t>((c.max_time_n << 4) | c.max_count_n);
    len = 2;
    return MacStatus::Ok;
}

MacStatus encode(const AdrParamSetupReq& c, Buf& out, std::size_t& len) {
    if (c.limit_exp > 15 || c.delay_exp > 15) return MacStatus::FieldOutOfRange;
    out = {};
    out[0] = static_cast<std::uint8_t>(Cid::AdrParamSetup);
    out[1] = static_cast<std::uint8_t>((c.limit_exp << 4) | c.delay_exp);
    len = 2;
    return MacStatus::Ok;
}

MacStatus encode(const PingSlotInfoReq& c, Buf& out, std::size_t& len) {
    if (c.periodicity > 7) return MacStatus::FieldOutOfRange;
    out = {};
    out[0] = static_cast<std::uint8_t>(Cid::PingSlotInfo);
    out[1] = c.periodicity;
    len = 2;
    return MacStatus::Ok;
}

MacStatus encode(const PingSlotChannelReq& c, Buf& out, std::size_t& len) {
    if (c.dr > 15 || !freq_valid(c.freq_100hz)) return MacStatus::FieldOutOfRange;
    out = {};
    out[0] = static_cast<std::uint8_t>(Cid::PingSlotChannel);
    write_u24(&out[1], c.freq_100hz);
    out[4] = c.dr;
    len = 5;
    return MacStatus::Ok;
}

MacStatus encode(const PingSlotChannelAns& c, Buf& out, std::size_t& len) {
    out = {};
    out[0] = static_cast<std::uint8_t>(Cid::PingSlotChannel);
    out[1] = static_cast<std::uint8_t>((c.data_rate_ok ? 0x02 : 0x00) | (c.channel_freq_ok ? 0x01 : 0x00));
    len = 2;
    return MacStatus::Ok;
}

MacStatus encode(const BeaconFreqReq& c, Buf& out, std::size_t& len) {
    if (!freq_valid(c.freq_100hz)) return MacStatus::FieldOutOfRange;
    out = {};
    out[0] = static_cast<std::uint8_t>(Cid::BeaconFreq);
    write_u24(&out[1], c.freq_100hz);
    len = 4;
    return MacStatus::Ok;
}

MacStatus encode(const BeaconFreqAns& c, Buf& out, std::size_t& len) {
    out = {};
    out[0] = static_cast<std::uint8_t>(Cid::BeaconFreq);
    out[1] = c.beacon_freq_ok ? 0x01 : 0x00;
    len = 2;
    return MacStatus::Ok;
}

MacStatus encode(const RejoinParamSetupAns& c, Buf& out, std::size_t& len) {
    out = {};
    out[0] = static_cast<std::uint8_t>(Cid::RejoinParamSetup);
    out[1] = c.time_ok ? 0x01 : 0x00;
    len = 2;
    return MacStatus::Ok;
}

MacStatus encode(const DlChannelReq& c, Buf& out, std::size_t& len) {
    if (c.ch_index > 15 || c.freq_100hz > 0xFFFFFFu || c.freq_100hz < 1'000'000u) {
        return MacStatus::FieldOutOfRange;
    }
    out = {};
    out[0] = static_cast<std::uint8_t>(Cid::DlChannel);
    out[1] = c.ch_index;
    write_u24(&out[2], c.freq_100hz);
    len = 5;
    return MacStatus::Ok;
}

MacStatus encode(const DlChannelAns& c, Buf& out, std::size_t& len) {
    out = {};
    out[0] = static_cast<std::uint8_t>(Cid::DlChannel);
    out[1] = static_cast<std::uint8_t>((c.channel_freq_ok ? 0x01 : 0) | (c.uplink_freq_exists ? 0x02 : 0));
    len = 2;
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

MacStatus decode(const std::uint8_t* data, std::size_t len, RxParamSetupReq& out) {
    if (len != 5 || data[0] != static_cast<std::uint8_t>(Cid::RxParamSetup)) return MacStatus::MalformedPayload;
    if (!rfu_zero(data[1], 0x80)) return MacStatus::MalformedPayload;  // bit 7 RFU
    const std::uint32_t f = read_u24(&data[2]);
    if (!freq_valid(f)) return MacStatus::FieldOutOfRange;
    out.rx2_data_rate = static_cast<std::uint8_t>(data[1] & 0x0F);
    out.rx1_dr_offset = static_cast<std::uint8_t>((data[1] >> 4) & 0x07);
    out.freq_100hz = f;
    return MacStatus::Ok;
}

MacStatus decode(const std::uint8_t* data, std::size_t len, RxParamSetupAns& out) {
    if (len != 2 || data[0] != static_cast<std::uint8_t>(Cid::RxParamSetup)) return MacStatus::MalformedPayload;
    if (!rfu_zero(data[1], 0xF8)) return MacStatus::MalformedPayload;  // bits 7:3 RFU
    out.channel_ack = (data[1] & 0x01) != 0;
    out.rx2_data_rate_ack = (data[1] & 0x02) != 0;
    out.rx1_dr_offset_ack = (data[1] & 0x04) != 0;
    return MacStatus::Ok;
}

MacStatus decode(const std::uint8_t* data, std::size_t len, NewChannelReq& out) {
    if (len != 6 || data[0] != static_cast<std::uint8_t>(Cid::NewChannel)) return MacStatus::MalformedPayload;
    if (data[1] > 15) return MacStatus::FieldOutOfRange;
    const std::uint32_t f = read_u24(&data[2]);
    if (!freq_valid(f)) return MacStatus::FieldOutOfRange;
    out.ch_index = data[1];
    out.freq_100hz = f;
    out.min_dr = static_cast<std::uint8_t>(data[5] & 0x0F);
    out.max_dr = static_cast<std::uint8_t>((data[5] >> 4) & 0x0F);
    return MacStatus::Ok;
}

MacStatus decode(const std::uint8_t* data, std::size_t len, NewChannelAns& out) {
    if (len != 2 || data[0] != static_cast<std::uint8_t>(Cid::NewChannel)) return MacStatus::MalformedPayload;
    if (!rfu_zero(data[1], 0xFC)) return MacStatus::MalformedPayload;  // bits 7:2 RFU
    out.dr_range_ack = (data[1] & 0x01) != 0;
    out.channel_freq_ack = (data[1] & 0x02) != 0;
    return MacStatus::Ok;
}

MacStatus decode(const std::uint8_t* data, std::size_t len, RxTimingSetupReq& out) {
    if (len != 2 || data[0] != static_cast<std::uint8_t>(Cid::RxTimingSetup)) return MacStatus::MalformedPayload;
    if (!rfu_zero(data[1], 0xF0)) return MacStatus::MalformedPayload;  // bits 7:4 RFU
    out.delay = static_cast<std::uint8_t>(data[1] & 0x0F);
    return MacStatus::Ok;
}

MacStatus decode(const std::uint8_t* data, std::size_t len, DeviceTimeAns& out) {
    if (len != 6 || data[0] != static_cast<std::uint8_t>(Cid::DeviceTime)) return MacStatus::MalformedPayload;
    out.seconds = static_cast<std::uint32_t>(data[1]) | (static_cast<std::uint32_t>(data[2]) << 8) |
                  (static_cast<std::uint32_t>(data[3]) << 16) | (static_cast<std::uint32_t>(data[4]) << 24);
    out.fraction = data[5];
    return MacStatus::Ok;
}

MacStatus decode(const std::uint8_t* data, std::size_t len, ForceRejoinReq& out) {
    if (len != 3 || data[0] != static_cast<std::uint8_t>(Cid::ForceRejoin)) return MacStatus::MalformedPayload;
    const auto word = static_cast<std::uint16_t>(data[1] | (data[2] << 8));
    if ((word & 0xC080u) != 0) return MacStatus::MalformedPayload;  // bits 15:14 et 7 RFU
    const std::uint8_t rtype = static_cast<std::uint8_t>((word >> 4) & 0x07);
    if (rtype > 2) return MacStatus::FieldOutOfRange;
    out.period = static_cast<std::uint8_t>((word >> 11) & 0x07);
    out.max_retries = static_cast<std::uint8_t>((word >> 8) & 0x07);
    out.rejoin_type = rtype;
    out.dr = static_cast<std::uint8_t>(word & 0x0F);
    return MacStatus::Ok;
}

MacStatus decode(const std::uint8_t* data, std::size_t len, RejoinParamSetupReq& out) {
    if (len != 2 || data[0] != static_cast<std::uint8_t>(Cid::RejoinParamSetup)) return MacStatus::MalformedPayload;
    out.max_count_n = static_cast<std::uint8_t>(data[1] & 0x0F);
    out.max_time_n = static_cast<std::uint8_t>((data[1] >> 4) & 0x0F);
    return MacStatus::Ok;
}

MacStatus decode(const std::uint8_t* data, std::size_t len, AdrParamSetupReq& out) {
    if (len != 2 || data[0] != static_cast<std::uint8_t>(Cid::AdrParamSetup)) return MacStatus::MalformedPayload;
    out.delay_exp = static_cast<std::uint8_t>(data[1] & 0x0F);
    out.limit_exp = static_cast<std::uint8_t>((data[1] >> 4) & 0x0F);
    return MacStatus::Ok;
}

MacStatus decode(const std::uint8_t* data, std::size_t len, PingSlotInfoReq& out) {
    if (len != 2 || data[0] != static_cast<std::uint8_t>(Cid::PingSlotInfo)) return MacStatus::MalformedPayload;
    if (!rfu_zero(data[1], 0xF8)) return MacStatus::MalformedPayload;  // bits 7:3 RFU
    out.periodicity = static_cast<std::uint8_t>(data[1] & 0x07);
    return MacStatus::Ok;
}

MacStatus decode(const std::uint8_t* data, std::size_t len, PingSlotChannelReq& out) {
    if (len != 5 || data[0] != static_cast<std::uint8_t>(Cid::PingSlotChannel)) return MacStatus::MalformedPayload;
    if (!rfu_zero(data[4], 0xF0)) return MacStatus::MalformedPayload;  // bits 7:4 RFU du DR
    const std::uint32_t f = read_u24(&data[1]);
    if (!freq_valid(f)) return MacStatus::FieldOutOfRange;
    out.freq_100hz = f;
    out.dr = static_cast<std::uint8_t>(data[4] & 0x0F);
    return MacStatus::Ok;
}

MacStatus decode(const std::uint8_t* data, std::size_t len, PingSlotChannelAns& out) {
    if (len != 2 || data[0] != static_cast<std::uint8_t>(Cid::PingSlotChannel)) return MacStatus::MalformedPayload;
    if (!rfu_zero(data[1], 0xFC)) return MacStatus::MalformedPayload;  // bits 7:2 RFU
    out.channel_freq_ok = (data[1] & 0x01) != 0;
    out.data_rate_ok = (data[1] & 0x02) != 0;
    return MacStatus::Ok;
}

MacStatus decode(const std::uint8_t* data, std::size_t len, BeaconFreqReq& out) {
    if (len != 4 || data[0] != static_cast<std::uint8_t>(Cid::BeaconFreq)) return MacStatus::MalformedPayload;
    const std::uint32_t f = read_u24(&data[1]);
    if (!freq_valid(f)) return MacStatus::FieldOutOfRange;
    out.freq_100hz = f;
    return MacStatus::Ok;
}

MacStatus decode(const std::uint8_t* data, std::size_t len, BeaconFreqAns& out) {
    if (len != 2 || data[0] != static_cast<std::uint8_t>(Cid::BeaconFreq)) return MacStatus::MalformedPayload;
    if (!rfu_zero(data[1], 0xFE)) return MacStatus::MalformedPayload;  // bits 7:1 RFU
    out.beacon_freq_ok = (data[1] & 0x01) != 0;
    return MacStatus::Ok;
}

MacStatus decode(const std::uint8_t* data, std::size_t len, RejoinParamSetupAns& out) {
    if (len != 2 || data[0] != static_cast<std::uint8_t>(Cid::RejoinParamSetup)) return MacStatus::MalformedPayload;
    if (!rfu_zero(data[1], 0xFE)) return MacStatus::MalformedPayload;  // bits 7:1 RFU
    out.time_ok = (data[1] & 0x01) != 0;
    return MacStatus::Ok;
}

MacStatus decode(const std::uint8_t* data, std::size_t len, DlChannelReq& out) {
    if (len != 5 || data[0] != static_cast<std::uint8_t>(Cid::DlChannel)) return MacStatus::MalformedPayload;
    if (data[1] > 15) return MacStatus::FieldOutOfRange;
    const std::uint32_t f = read_u24(&data[2]);
    if (f < 1'000'000u) return MacStatus::FieldOutOfRange;  // < 100 MHz réservé
    out.ch_index = data[1];
    out.freq_100hz = f;
    return MacStatus::Ok;
}

MacStatus decode(const std::uint8_t* data, std::size_t len, DlChannelAns& out) {
    if (len != 2 || data[0] != static_cast<std::uint8_t>(Cid::DlChannel)) return MacStatus::MalformedPayload;
    if (!rfu_zero(data[1], 0xFC)) return MacStatus::MalformedPayload;  // bits 7:2 RFU
    out.channel_freq_ok = (data[1] & 0x01) != 0;
    out.uplink_freq_exists = (data[1] & 0x02) != 0;
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
