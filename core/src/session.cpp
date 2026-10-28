// SPDX-License-Identifier: Apache-2.0
#include "lsim/session.hpp"

namespace lsim::lorawan::session {

namespace {
bool valid_init(const InitParams& p) {
    return p.min_dr <= p.dr && p.dr <= 15 && p.min_dr <= 15 && p.tx_power_index <= 15 &&
           p.default_tx_power_index <= 15;
}
}  // namespace

SessionStatus Session::join_accepted(const SessionKeys11& keys, const InitParams& init) {
    if (!valid_init(init)) return SessionStatus::InvalidParameter;
    keys_ = keys;
    dev_addr_ = init.dev_addr;
    fcnt_up_ = 0;
    nf_cnt_dwn_ = 0;
    af_cnt_dwn_ = 0;
    adr_ = adr::DeviceAdrState{};
    adr_.dr = init.dr;
    adr_.min_dr = init.min_dr;
    adr_.tx_power_index = init.tx_power_index;
    adr_.default_tx_power_index = init.default_tx_power_index;
    rekey::device_join_accepted(rekey_);
    joined_ = true;
    cycle_open_ = false;
    rx_seen_ = false;
    conf_seen_ = false;
    conf_version_ = 0;
    return SessionStatus::Ok;
}

SessionStatus Session::begin_uplink(std::uint8_t limit_exp, std::uint8_t delay_exp, UplinkPlan& plan) {
    if (state() != SessionState::Active) return SessionStatus::NoSession;
    if (cycle_open_) return SessionStatus::CycleError;
    if (fcnt_up_ > 0xFFFFFFFFull) return SessionStatus::CounterExhausted;
    if (limit_exp > 15 || delay_exp > 15) return SessionStatus::InvalidParameter;
    adr::UplinkOutcome uo;
    if (adr::device_on_uplink(adr_, limit_exp, delay_exp, uo) != adr::AdrStatus::Ok) {
        return SessionStatus::InvalidParameter;  // inatteignable après validation ci-dessus
    }
    admin_limit_ = std::uint64_t{1} << limit_exp;
    plan.fcnt32 = static_cast<std::uint32_t>(fcnt_up_);
    plan.rekey_ind = rekey::device_must_send_rekey_ind(rekey_);
    plan.ack_req = uo.ack_req;
    plan.default_channels_reenabled = uo.default_channels_reenabled;
    cycle_open_ = true;
    rx_seen_ = false;
    conf_seen_ = false;
    conf_version_ = 0;
    return SessionStatus::Ok;
}

SessionStatus Session::receive_downlink(const DownlinkInfo& d) {
    if (!cycle_open_) return SessionStatus::CycleError;
    std::uint64_t& expected = d.uses_nf ? nf_cnt_dwn_ : af_cnt_dwn_;
    if (d.fcnt32 < expected) return SessionStatus::Replay;
    expected = static_cast<std::uint64_t>(d.fcnt32) + 1;
    rx_seen_ = true;
    if (d.conf_received) {
        conf_seen_ = true;
        conf_version_ = d.server_version;
    }
    return SessionStatus::Ok;
}

SessionStatus Session::end_uplink(UplinkEnd& out) {
    if (!cycle_open_) return SessionStatus::CycleError;
    ++fcnt_up_;
    rekey::device_uplink_completed(rekey_, admin_limit_, conf_seen_, conf_version_);
    if (rx_seen_) adr::device_on_downlink(adr_);
    cycle_open_ = false;
    rx_seen_ = false;
    conf_seen_ = false;
    out.state = state();
    return SessionStatus::Ok;
}

SessionState Session::state() const {
    if (!joined_) return SessionState::NoSession;
    if (rekey_.state == rekey::DeviceState::NeedsJoin) return SessionState::NeedsJoin;
    return SessionState::Active;
}

Snapshot Session::snapshot() const {
    Snapshot s;
    s.state = state();
    s.dev_addr = dev_addr_;
    s.fcnt_up = fcnt_up_;
    s.nf_cnt_dwn = nf_cnt_dwn_;
    s.af_cnt_dwn = af_cnt_dwn_;
    s.dr = adr_.dr;
    s.tx_power_index = adr_.tx_power_index;
    s.ack_cnt = adr_.ack_cnt;
    s.cycle_open = cycle_open_;
    return s;
}

}  // namespace lsim::lorawan::session
