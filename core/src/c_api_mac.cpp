// SPDX-License-Identifier: Apache-2.0
// Surface C des commandes MAC LoRaWAN 1.1 (voir lsim/c_api.h).
// Chaque fonction intercepte les exceptions : aucune ne traverse la frontière C.
#include <array>
#include <cstring>

#include "lsim/c_api.h"
#include "lsim/lora_phy.hpp"
#include "lsim/mac_commands.hpp"

namespace {

using lsim::lorawan::kMaxFOpts;
using namespace lsim::lorawan::mac;
using Buf = std::array<std::uint8_t, kMaxCommandBytes>;

std::int32_t map_mac(MacStatus s) {
    if (s == MacStatus::Ok) {
        return 0;
    }
    return LSIM_STATUS_MAC_BASE + static_cast<std::int32_t>(s);
}

// Champs de charge utile lus d'un lsim_mac_command selon son kind.
bool to_cpp_and_encode(const lsim_mac_command& c, Buf& out, std::size_t& len, MacStatus& st) {
    switch (c.kind) {
        case LSIM_MAC_LINK_CHECK_REQ:
            st = encode_empty(Cid::LinkCheck, Direction::Uplink, out, len);
            return true;
        case LSIM_MAC_LINK_CHECK_ANS: {
            LinkCheckAns v;
            v.margin = c.margin;
            v.gw_cnt = c.gw_cnt;
            st = encode(v, out, len);
            return true;
        }
        case LSIM_MAC_LINK_ADR_REQ: {
            LinkAdrReq v;
            v.data_rate = c.data_rate;
            v.tx_power = c.tx_power;
            v.ch_mask = c.ch_mask;
            v.ch_mask_cntl = c.ch_mask_cntl;
            v.nb_trans = c.nb_trans;
            st = encode(v, out, len);
            return true;
        }
        case LSIM_MAC_LINK_ADR_ANS: {
            LinkAdrAns v;
            v.channel_mask_ack = c.ack_channel_mask != 0;
            v.data_rate_ack = c.ack_data_rate != 0;
            v.power_ack = c.ack_power != 0;
            st = encode(v, out, len);
            return true;
        }
        case LSIM_MAC_DUTY_CYCLE_REQ: {
            DutyCycleReq v;
            v.max_dcycle = c.max_dcycle;
            st = encode(v, out, len);
            return true;
        }
        case LSIM_MAC_DUTY_CYCLE_ANS:
            st = encode_empty(Cid::DutyCycle, Direction::Uplink, out, len);
            return true;
        case LSIM_MAC_DEV_STATUS_REQ:
            st = encode_empty(Cid::DevStatus, Direction::Downlink, out, len);
            return true;
        case LSIM_MAC_DEV_STATUS_ANS: {
            DevStatusAns v;
            v.battery = c.battery;
            v.margin = c.dev_margin;
            st = encode(v, out, len);
            return true;
        }
        case LSIM_MAC_RX_PARAM_SETUP_REQ: {
            RxParamSetupReq v;
            v.rx2_data_rate = c.rx2_data_rate;
            v.rx1_dr_offset = c.rx1_dr_offset;
            v.freq_100hz = c.freq_100hz;
            st = encode(v, out, len);
            return true;
        }
        case LSIM_MAC_RX_PARAM_SETUP_ANS: {
            RxParamSetupAns v;
            v.channel_ack = c.ack_rx_channel != 0;
            v.rx2_data_rate_ack = c.ack_rx2_data_rate != 0;
            v.rx1_dr_offset_ack = c.ack_rx1_dr_offset != 0;
            st = encode(v, out, len);
            return true;
        }
        case LSIM_MAC_NEW_CHANNEL_REQ: {
            NewChannelReq v;
            v.ch_index = c.ch_index;
            v.freq_100hz = c.freq_100hz;
            v.min_dr = c.min_dr;
            v.max_dr = c.max_dr;
            st = encode(v, out, len);
            return true;
        }
        case LSIM_MAC_NEW_CHANNEL_ANS: {
            NewChannelAns v;
            v.dr_range_ack = c.ack_dr_range != 0;
            v.channel_freq_ack = c.ack_channel_freq != 0;
            st = encode(v, out, len);
            return true;
        }
        case LSIM_MAC_RX_TIMING_SETUP_REQ: {
            RxTimingSetupReq v;
            v.delay = c.rx_delay;
            st = encode(v, out, len);
            return true;
        }
        case LSIM_MAC_RX_TIMING_SETUP_ANS:
            st = encode_empty(Cid::RxTimingSetup, Direction::Uplink, out, len);
            return true;
        case LSIM_MAC_DEVICE_TIME_REQ:
            st = encode_empty(Cid::DeviceTime, Direction::Uplink, out, len);
            return true;
        case LSIM_MAC_DEVICE_TIME_ANS: {
            DeviceTimeAns v;
            v.seconds = c.device_time_s;
            v.fraction = c.device_time_frac;
            st = encode(v, out, len);
            return true;
        }
        case LSIM_MAC_FORCE_REJOIN_REQ: {
            ForceRejoinReq v;
            v.period = c.rejoin_period;
            v.max_retries = c.rejoin_max_retries;
            v.rejoin_type = c.rejoin_type;
            v.dr = c.data_rate;
            st = encode(v, out, len);
            return true;
        }
        case LSIM_MAC_REJOIN_PARAM_SETUP_REQ: {
            RejoinParamSetupReq v;
            v.max_time_n = c.max_time_n;
            v.max_count_n = c.max_count_n;
            st = encode(v, out, len);
            return true;
        }
        case LSIM_MAC_REJOIN_PARAM_SETUP_ANS: {
            RejoinParamSetupAns v;
            v.time_ok = c.ack_time_ok != 0;
            st = encode(v, out, len);
            return true;
        }
        case LSIM_MAC_DL_CHANNEL_REQ: {
            DlChannelReq v;
            v.ch_index = c.ch_index;
            v.freq_100hz = c.freq_100hz;
            st = encode(v, out, len);
            return true;
        }
        case LSIM_MAC_DL_CHANNEL_ANS: {
            DlChannelAns v;
            v.channel_freq_ok = c.ack_channel_freq != 0;
            v.uplink_freq_exists = c.ack_uplink_freq_exists != 0;
            st = encode(v, out, len);
            return true;
        }
        case LSIM_MAC_REKEY_IND:
        case LSIM_MAC_REKEY_CONF: {
            Rekey v;
            v.minor = c.lorawan_minor;
            st = encode(v, c.kind == LSIM_MAC_REKEY_IND ? Direction::Uplink : Direction::Downlink, out, len);
            return true;
        }
        default:
            st = MacStatus::UnknownCommand;
            return false;
    }
}

}  // namespace

int32_t lsim_mac_encode(const lsim_mac_command* cmd, uint8_t out[LSIM_MAC_MAX_COMMAND_BYTES], size_t* out_len) {
    if (cmd == nullptr || out == nullptr || out_len == nullptr) {
        return static_cast<int32_t>(lsim::lora::Status::NullOutput);
    }
    *out_len = 0;
    std::memset(out, 0, LSIM_MAC_MAX_COMMAND_BYTES);
    try {
        Buf buf{};
        std::size_t len = 0;
        MacStatus st = MacStatus::UnknownCommand;
        to_cpp_and_encode(*cmd, buf, len, st);
        if (st != MacStatus::Ok) {
            return map_mac(st);
        }
        std::memcpy(out, buf.data(), len);
        *out_len = len;
        return 0;
    } catch (...) {
        return LSIM_STATUS_INTERNAL;
    }
}

int32_t lsim_mac_decode(const uint8_t* in, size_t len, uint8_t direction, lsim_mac_command* out,
                        size_t* consumed) {
    if (in == nullptr || out == nullptr || consumed == nullptr) {
        return static_cast<int32_t>(lsim::lora::Status::NullOutput);
    }
    std::memset(out, 0, sizeof *out);
    *consumed = 0;
    try {
        const Direction dir = direction == LSIM_MAC_DOWNLINK ? Direction::Downlink : Direction::Uplink;
        std::size_t size = 0;
        MacStatus st = command_size(dir, in, len, size);
        if (st != MacStatus::Ok) {
            return map_mac(st);
        }
        const std::uint8_t cid = in[0];
        const std::uint8_t* p = in;
        const std::size_t n = size;
        if (dir == Direction::Uplink) {
            switch (cid) {
                case 0x02: out->kind = LSIM_MAC_LINK_CHECK_REQ; break;
                case 0x03: {
                    LinkAdrAns v;
                    st = decode(p, n, v);
                    out->ack_channel_mask = v.channel_mask_ack;
                    out->ack_data_rate = v.data_rate_ack;
                    out->ack_power = v.power_ack;
                    out->kind = LSIM_MAC_LINK_ADR_ANS;
                    break;
                }
                case 0x04: out->kind = LSIM_MAC_DUTY_CYCLE_ANS; break;
                case 0x08: out->kind = LSIM_MAC_RX_TIMING_SETUP_ANS; break;
                case 0x0A: {
                    DlChannelAns v;
                    st = decode(p, n, v);
                    out->ack_channel_freq = v.channel_freq_ok;
                    out->ack_uplink_freq_exists = v.uplink_freq_exists;
                    out->kind = LSIM_MAC_DL_CHANNEL_ANS;
                    break;
                }
                case 0x0D: out->kind = LSIM_MAC_DEVICE_TIME_REQ; break;
                case 0x0F: {
                    RejoinParamSetupAns v;
                    st = decode(p, n, v);
                    out->ack_time_ok = v.time_ok;
                    out->kind = LSIM_MAC_REJOIN_PARAM_SETUP_ANS;
                    break;
                }
                case 0x05: {
                    RxParamSetupAns v;
                    st = decode(p, n, v);
                    out->ack_rx_channel = v.channel_ack;
                    out->ack_rx2_data_rate = v.rx2_data_rate_ack;
                    out->ack_rx1_dr_offset = v.rx1_dr_offset_ack;
                    out->kind = LSIM_MAC_RX_PARAM_SETUP_ANS;
                    break;
                }
                case 0x06: {
                    DevStatusAns v;
                    st = decode(p, n, v);
                    out->battery = v.battery;
                    out->dev_margin = v.margin;
                    out->kind = LSIM_MAC_DEV_STATUS_ANS;
                    break;
                }
                case 0x07: {
                    NewChannelAns v;
                    st = decode(p, n, v);
                    out->ack_dr_range = v.dr_range_ack;
                    out->ack_channel_freq = v.channel_freq_ack;
                    out->kind = LSIM_MAC_NEW_CHANNEL_ANS;
                    break;
                }
                case 0x0B: {
                    Rekey v;
                    st = decode(p, n, v, Direction::Uplink);
                    out->lorawan_minor = v.minor;
                    out->kind = LSIM_MAC_REKEY_IND;
                    break;
                }
                default: st = MacStatus::UnknownCommand; break;
            }
        } else {
            switch (cid) {
                case 0x02: {
                    LinkCheckAns v;
                    st = decode(p, n, v);
                    out->margin = v.margin;
                    out->gw_cnt = v.gw_cnt;
                    out->kind = LSIM_MAC_LINK_CHECK_ANS;
                    break;
                }
                case 0x03: {
                    LinkAdrReq v;
                    st = decode(p, n, v);
                    out->data_rate = v.data_rate;
                    out->tx_power = v.tx_power;
                    out->ch_mask = v.ch_mask;
                    out->ch_mask_cntl = v.ch_mask_cntl;
                    out->nb_trans = v.nb_trans;
                    out->kind = LSIM_MAC_LINK_ADR_REQ;
                    break;
                }
                case 0x04: {
                    DutyCycleReq v;
                    st = decode(p, n, v);
                    out->max_dcycle = v.max_dcycle;
                    out->kind = LSIM_MAC_DUTY_CYCLE_REQ;
                    break;
                }
                case 0x05: {
                    RxParamSetupReq v;
                    st = decode(p, n, v);
                    out->rx2_data_rate = v.rx2_data_rate;
                    out->rx1_dr_offset = v.rx1_dr_offset;
                    out->freq_100hz = v.freq_100hz;
                    out->kind = LSIM_MAC_RX_PARAM_SETUP_REQ;
                    break;
                }
                case 0x06: out->kind = LSIM_MAC_DEV_STATUS_REQ; break;
                case 0x08: {
                    RxTimingSetupReq v;
                    st = decode(p, n, v);
                    out->rx_delay = v.delay;
                    out->kind = LSIM_MAC_RX_TIMING_SETUP_REQ;
                    break;
                }
                case 0x0A: {
                    DlChannelReq v;
                    st = decode(p, n, v);
                    out->ch_index = v.ch_index;
                    out->freq_100hz = v.freq_100hz;
                    out->kind = LSIM_MAC_DL_CHANNEL_REQ;
                    break;
                }
                case 0x0D: {
                    DeviceTimeAns v;
                    st = decode(p, n, v);
                    out->device_time_s = v.seconds;
                    out->device_time_frac = v.fraction;
                    out->kind = LSIM_MAC_DEVICE_TIME_ANS;
                    break;
                }
                case 0x0E: {
                    ForceRejoinReq v;
                    st = decode(p, n, v);
                    out->rejoin_period = v.period;
                    out->rejoin_max_retries = v.max_retries;
                    out->rejoin_type = v.rejoin_type;
                    out->data_rate = v.dr;
                    out->kind = LSIM_MAC_FORCE_REJOIN_REQ;
                    break;
                }
                case 0x0F: {
                    RejoinParamSetupReq v;
                    st = decode(p, n, v);
                    out->max_time_n = v.max_time_n;
                    out->max_count_n = v.max_count_n;
                    out->kind = LSIM_MAC_REJOIN_PARAM_SETUP_REQ;
                    break;
                }
                case 0x07: {
                    NewChannelReq v;
                    st = decode(p, n, v);
                    out->ch_index = v.ch_index;
                    out->freq_100hz = v.freq_100hz;
                    out->min_dr = v.min_dr;
                    out->max_dr = v.max_dr;
                    out->kind = LSIM_MAC_NEW_CHANNEL_REQ;
                    break;
                }
                case 0x0B: {
                    Rekey v;
                    st = decode(p, n, v, Direction::Downlink);
                    out->lorawan_minor = v.minor;
                    out->kind = LSIM_MAC_REKEY_CONF;
                    break;
                }
                default: st = MacStatus::UnknownCommand; break;
            }
        }
        if (st != MacStatus::Ok) {
            std::memset(out, 0, sizeof *out);
            return map_mac(st);
        }
        *consumed = size;
        return 0;
    } catch (...) {
        std::memset(out, 0, sizeof *out);
        return LSIM_STATUS_INTERNAL;
    }
}

int32_t lsim_mac_append_fopts(uint8_t fopts[15], uint8_t* fopts_len, const uint8_t* cmd, size_t cmd_len) {
    if (fopts == nullptr || fopts_len == nullptr || cmd == nullptr) {
        return static_cast<int32_t>(lsim::lora::Status::NullOutput);
    }
    if (cmd_len == 0 || cmd_len > kMaxCommandBytes || *fopts_len > kMaxFOpts) {
        return map_mac(MacStatus::MalformedPayload);
    }
    try {
        std::array<std::uint8_t, kMaxFOpts> buf{};
        std::memcpy(buf.data(), fopts, kMaxFOpts);
        std::uint8_t len = *fopts_len;
        Buf c{};
        std::memcpy(c.data(), cmd, cmd_len);
        const MacStatus st = append_to_fopts(buf, len, c, cmd_len);
        if (st != MacStatus::Ok) {
            return map_mac(st);
        }
        std::memcpy(fopts, buf.data(), kMaxFOpts);
        *fopts_len = len;
        return 0;
    } catch (...) {
        return LSIM_STATUS_INTERNAL;
    }
}
