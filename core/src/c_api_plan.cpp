// SPDX-License-Identifier: Apache-2.0
// Frontière C de la planification des descentes (lsim_plan_downlinks_v1).
#include <cstddef>
#include <cstdint>
#include <vector>

#include "lsim/c_api.h"
#include "lsim/downlink_plan.hpp"

namespace {

using lsim::plan::DeviceRadio;
using lsim::plan::Event;
using lsim::plan::Interval;
using lsim::plan::PlanOptions;
using lsim::plan::PlanStatus;
using lsim::plan::UplinkRecord;

int32_t map_status(PlanStatus s) {
    switch (s) {
        case PlanStatus::Ok: return 0;
        case PlanStatus::InvalidInput: return LSIM_STATUS_PLAN_BASE + 1;
        case PlanStatus::InvalidRadio: return LSIM_STATUS_PLAN_BASE + 2;
        case PlanStatus::InvalidOptions: return LSIM_STATUS_PLAN_BASE + 3;
    }
    return LSIM_STATUS_INTERNAL;
}

}  // namespace

int32_t lsim_plan_downlinks_v1(const lsim_plan_uplink* uplinks, size_t uplink_count,
                               const lsim_plan_device* devices, size_t device_count,
                               const lsim_plan_options* options,
                               lsim_plan_event* events, size_t event_capacity,
                               size_t* event_count,
                               lsim_interval* busy, size_t busy_capacity,
                               size_t* busy_count) {
    if (event_count == nullptr || busy_count == nullptr || options == nullptr) {
        return LSIM_STATUS_PLAN_BASE + 1;
    }
    if ((uplink_count > 0 && uplinks == nullptr) || (device_count > 0 && devices == nullptr)) {
        return LSIM_STATUS_PLAN_BASE + 1;
    }
    try {
        std::vector<UplinkRecord> ups(uplink_count);
        for (size_t i = 0; i < uplink_count; ++i) {
            const lsim_plan_uplink& u = uplinks[i];
            if (u.outcome > 3) return LSIM_STATUS_PLAN_BASE + 1;
            ups[i].device = u.device_index;
            ups[i].start_ns = u.start_ns;
            ups[i].end_ns = u.end_ns;
            ups[i].spreading_factor = u.spreading_factor;
            ups[i].outcome = static_cast<lsim::plan::UplinkOutcome>(u.outcome);
            ups[i].rssi_dbm = u.rssi_dbm;
        }
        std::vector<DeviceRadio> radios(device_count);
        for (size_t i = 0; i < device_count; ++i) {
            const lsim_plan_device& d = devices[i];
            radios[i].freq_hz = d.freq_hz;
            radios[i].dr = d.dr;
            radios[i].rx1_hz = d.rx1_hz;
            radios[i].tx_power_dbm = d.tx_power_dbm;
            radios[i].rx1_sf = d.rx1_sf;
            radios[i].rx1_bw_hz = d.rx1_bw_hz;
        }
        PlanOptions po;
        po.confirmed_uplinks = options->confirmed_uplinks != 0;
        po.downlink_every = options->downlink_every;
        po.downlink_payload_bytes = options->downlink_payload_bytes;
        po.gateway_tx_power_dbm = options->gateway_tx_power_dbm;
        po.device_antenna_gain_dbi = options->device_antenna_gain_dbi;
        po.device_rx_offset_db = options->device_rx_offset_db;

        std::vector<Event> evs;
        std::vector<Interval> bus;
        const PlanStatus st = lsim::plan::plan_downlinks(ups, radios, po, evs, bus);
        if (st != PlanStatus::Ok) return map_status(st);

        *event_count = evs.size();
        *busy_count = bus.size();
        if (evs.size() > event_capacity || bus.size() > busy_capacity) {
            return LSIM_STATUS_PLAN_BASE + 4;
        }
        for (size_t k = 0; k < evs.size(); ++k) {
            const Event& e = evs[k];
            lsim_plan_event& out = events[k];
            out.t_ns = e.t_ns;
            out.device_index = e.device;
            out.kind = static_cast<uint8_t>(e.kind);
            out.outcome = static_cast<uint8_t>(e.outcome);
            out.hop_count = static_cast<uint8_t>(e.hops.size());
            for (size_t h = 0; h < e.hops.size() && h < 2; ++h) {
                out.hops[h].dir = static_cast<uint8_t>(e.hops[h].dir);
                out.hops[h].outcome = static_cast<uint8_t>(e.hops[h].outcome);
                out.hops[h].has_rssi = e.hops[h].has_rssi ? 1 : 0;
                out.hops[h].t_ns = e.hops[h].t_ns;
                out.hops[h].freq_hz = e.hops[h].freq_hz;
                out.hops[h].dr = e.hops[h].dr;
                out.hops[h].rssi_dbm = e.hops[h].rssi_dbm;
            }
        }
        for (size_t k = 0; k < bus.size(); ++k) {
            busy[k].start_ns = bus[k].start_ns;
            busy[k].end_ns = bus[k].end_ns;
        }
        return 0;
    } catch (...) {
        return LSIM_STATUS_INTERNAL;
    }
}
