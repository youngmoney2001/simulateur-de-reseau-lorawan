// SPDX-License-Identifier: Apache-2.0
// Surface C du moteur de classe B : fonctions sans état, dispositif passé par l'appelant.
#include "lsim/c_api.h"
#include "lsim/class_b.hpp"
#include "lsim/lora_phy.hpp"

namespace {

using lsim::lorawan::classb::BeaconState;
using lsim::lorawan::classb::ClassBStatus;
using lsim::lorawan::classb::DeviceClassB;

int32_t map_status(ClassBStatus s) {
    return s == ClassBStatus::Ok ? 0 : LSIM_STATUS_CLASSB_BASE + static_cast<int32_t>(s);
}

int32_t null_out() { return static_cast<int32_t>(lsim::lora::Status::NullOutput); }

DeviceClassB to_native(const lsim_classb_device& d) {
    DeviceClassB n;
    n.synchronized = d.synchronized != 0;
    n.last_beacon_rx_ns = d.last_beacon_rx_ns;
    n.last_beacon_time_s = d.last_beacon_time_s;
    n.dev_addr = d.dev_addr;
    n.periodicity = d.periodicity;
    n.clock_drift_ppm = d.clock_drift_ppm;
    return n;
}

void from_native(const DeviceClassB& n, lsim_classb_device& d) {
    d.synchronized = n.synchronized ? 1 : 0;
    d.last_beacon_rx_ns = n.last_beacon_rx_ns;
    d.last_beacon_time_s = n.last_beacon_time_s;
    d.dev_addr = n.dev_addr;
    d.periodicity = n.periodicity;
    d.clock_drift_ppm = n.clock_drift_ppm;
}

}  // namespace

int32_t lsim_classb_decode_beacon(const uint8_t* in, size_t len, uint8_t rfu_len, uint32_t* time_s) {
    if (in == nullptr || time_s == nullptr) return null_out();
    lsim::lorawan::classb::BeaconCommon b;
    const auto st = lsim::lorawan::classb::decode_beacon(in, len, rfu_len, b);
    if (st != ClassBStatus::Ok) return map_status(st);
    *time_s = b.time_s;
    return 0;
}

int32_t lsim_classb_decode_beacon_full(const uint8_t* in, size_t len, uint8_t rfu_len,
                                       uint8_t gw_rfu_len, lsim_classb_gateway_info* out) {
    if (in == nullptr || out == nullptr) return null_out();
    lsim::lorawan::classb::BeaconCommon b;
    lsim::lorawan::classb::GatewayInfo g;
    const auto st = lsim::lorawan::classb::decode_beacon_full(in, len, rfu_len, gw_rfu_len, b, g);
    if (st != ClassBStatus::Ok) return map_status(st);
    out->time_s = b.time_s;
    out->present = g.present ? 1 : 0;
    out->info_desc = g.info_desc;
    out->has_coordinates = g.has_coordinates ? 1 : 0;
    out->latitude_deg = g.latitude_deg;
    out->longitude_deg = g.longitude_deg;
    return 0;
}

int32_t lsim_classb_us902_channel(uint32_t beacon_time_s, uint8_t* index, uint32_t* freq_hz) {
    if (index == nullptr || freq_hz == nullptr) return null_out();
    uint8_t idx = 0;
    const auto st = lsim::lorawan::classb::us902_channel_index(beacon_time_s, idx);
    if (st != ClassBStatus::Ok) return map_status(st);
    uint32_t f = 0;
    const auto st2 = lsim::lorawan::classb::us902_channel_frequency_hz(idx, f);
    if (st2 != ClassBStatus::Ok) return map_status(st2);
    *index = idx;
    *freq_hz = f;
    return 0;
}

int32_t lsim_classb_ping_offset(uint32_t beacon_time_s, uint32_t dev_addr, uint8_t periodicity,
                                uint32_t* offset) {
    if (offset == nullptr) return null_out();
    return map_status(lsim::lorawan::classb::ping_offset(beacon_time_s, dev_addr, periodicity, *offset));
}

int32_t lsim_classb_on_beacon(lsim_classb_device* d, uint64_t rx_ns, uint32_t beacon_time_s) {
    if (d == nullptr) return null_out();
    DeviceClassB n = to_native(*d);
    const auto st = lsim::lorawan::classb::on_beacon(n, rx_ns, beacon_time_s);
    if (st != ClassBStatus::Ok) return map_status(st);
    from_native(n, *d);
    return 0;
}

int32_t lsim_classb_beacon_state(const lsim_classb_device* d, uint64_t now_ns, uint8_t* state) {
    if (d == nullptr || state == nullptr) return null_out();
    BeaconState s = BeaconState::NotSynchronized;
    const auto st = lsim::lorawan::classb::beacon_state(to_native(*d), now_ns, s);
    if (st != ClassBStatus::Ok) return map_status(st);
    *state = static_cast<uint8_t>(s);
    return 0;
}

int32_t lsim_classb_next_ping_slot(const lsim_classb_device* d, uint64_t now_ns,
                                   lsim_classb_ping_slot* out) {
    if (d == nullptr || out == nullptr) return null_out();
    lsim::lorawan::classb::PingSlot p;
    const auto st = lsim::lorawan::classb::next_ping_slot(to_native(*d), now_ns, p);
    if (st != ClassBStatus::Ok) return map_status(st);
    out->start_ns = p.start_ns;
    out->slot_index = p.slot_index;
    out->beacon_time_s = p.beacon_time_s;
    out->beacon_period_start_ns = p.beacon_period_start_ns;
    out->window_half_ns = p.window_half_ns;
    return 0;
}
