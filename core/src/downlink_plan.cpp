// SPDX-License-Identifier: Apache-2.0
#include "lsim/downlink_plan.hpp"

#include <algorithm>
#include <cmath>
#include <cstddef>

#include "lsim/lora_phy.hpp"

namespace lsim::plan {
namespace {

// Constantes alignées sur `lsim.plan.RECEIVE_DELAY1_US` et `trace_events.RX1_WINDOW_NS`.
constexpr std::int64_t kReceiveDelay1Ns = 1'000'000'000;
constexpr std::int64_t kRx1WindowNs = 1'000'000'000;
// Trame downlink sans charge (MHDR, DevAddr, FCtrl, FCnt, MIC) et avec charge (+ FPort).
constexpr std::uint32_t kAckFrameBytes = 12;
constexpr std::uint32_t kDataFrameOverheadBytes = 13;
constexpr std::uint32_t kMaxDownlinkPayloadBytes = 242;

// Débit RX1 valide : SF 7..12 et largeur 125, 250 ou 500 kHz. Vérifié à la construction, pour que
// l'erreur porte sur le paramètre radio et non sur une descente planifiée plus tard.
bool valid_rx1(const DeviceRadio& r) {
    if (r.rx1_sf < 7 || r.rx1_sf > 12) return false;
    return r.rx1_bw_hz == 125'000 || r.rx1_bw_hz == 250'000 || r.rx1_bw_hz == 500'000;
}

Outcome from_uplink(UplinkOutcome o) {
    switch (o) {
        case UplinkOutcome::Received: return Outcome::Received;
        case UplinkOutcome::LostSensitivity: return Outcome::LostSensitivity;
        case UplinkOutcome::LostCollision: return Outcome::LostCollision;
        case UplinkOutcome::LostGatewayBusy: return Outcome::LostGatewayBusy;
    }
    return Outcome::LostSensitivity;
}

// Issue du saut montant (`_HOP_OUTCOME` côté Python).
Outcome hop_from_uplink(UplinkOutcome o) {
    switch (o) {
        case UplinkOutcome::Received: return Outcome::Delivered;
        case UplinkOutcome::LostSensitivity: return Outcome::LostSensitivity;
        case UplinkOutcome::LostCollision: return Outcome::LostCollision;
        case UplinkOutcome::LostGatewayBusy: return Outcome::NotListened;
    }
    return Outcome::NotListened;
}

struct Job {
    std::size_t record = 0;
    std::uint32_t device = 0;
    EventKind kind = EventKind::Downlink;  // Ack ou Downlink
    Outcome content = Outcome::Data;       // issue si reçue
    std::int64_t t_open = 0;
    std::int64_t airtime_ns = 0;
    std::int64_t rx1_hz = 0;
    bool received = false;
    bool device_missed = false;
};

}  // namespace

lora::Status downlink_airtime_ns(const DeviceRadio& radio, std::uint32_t payload_bytes,
                                 std::int64_t& out_ns) {
    lora::RadioConfig rc;
    rc.spreading_factor = radio.rx1_sf;
    rc.bandwidth = static_cast<lora::Bandwidth>(radio.rx1_bw_hz);
    if (radio.rx1_bw_hz != 125'000 && radio.rx1_bw_hz != 250'000 && radio.rx1_bw_hz != 500'000) {
        return lora::Status::InvalidBandwidth;
    }
    rc.coding_rate = 1;
    rc.crc_on = false;
    rc.explicit_header = true;
    const double symbol_s = static_cast<double>(1u << radio.rx1_sf) / static_cast<double>(radio.rx1_bw_hz);
    rc.low_data_rate_optimize = symbol_s > 0.016;
    const lora::AirtimeResult at = lora::time_on_air(rc, payload_bytes);
    if (at.status != lora::Status::Ok) return at.status;
    out_ns = at.nanoseconds;
    return lora::Status::Ok;
}

PlanStatus plan_downlinks(const std::vector<UplinkRecord>& uplinks,
                          const std::vector<DeviceRadio>& radios, const PlanOptions& options,
                          std::vector<Event>& events, std::vector<Interval>& busy) {
    events.clear();
    busy.clear();
    if (options.downlink_payload_bytes > kMaxDownlinkPayloadBytes) return PlanStatus::InvalidOptions;
    if (!std::isfinite(options.gateway_tx_power_dbm) || !std::isfinite(options.device_antenna_gain_dbi) ||
        !std::isfinite(options.device_rx_offset_db)) {
        return PlanStatus::InvalidOptions;
    }
    for (const UplinkRecord& r : uplinks) {
        if (r.device >= radios.size()) return PlanStatus::InvalidInput;
    }
    for (const DeviceRadio& rad : radios) {
        if (!valid_rx1(rad)) return PlanStatus::InvalidRadio;
    }

    // Début de l'émission suivante du même dispositif (requête de désoccupation de RX1).
    constexpr std::int64_t kNone = -1;
    std::vector<std::int64_t> next_start(uplinks.size(), kNone);
    std::vector<std::int64_t> last_of(radios.size(), kNone);  // indice du dernier enregistrement
    for (std::size_t i = 0; i < uplinks.size(); ++i) {
        const std::int64_t prev = last_of[uplinks[i].device];
        if (prev != kNone) next_start[static_cast<std::size_t>(prev)] = uplinks[i].start_ns;
        last_of[uplinks[i].device] = static_cast<std::int64_t>(i);
    }

    // Jobs : une réponse par uplink reçu, dans l'ordre de la trace (`_downlink_jobs`).
    std::vector<Job> jobs;
    std::vector<std::int64_t> job_of(uplinks.size(), kNone);
    std::vector<std::uint32_t> accepted(radios.size(), 0);
    for (std::size_t i = 0; i < uplinks.size(); ++i) {
        const UplinkRecord& r = uplinks[i];
        if (r.outcome != UplinkOutcome::Received) continue;
        const DeviceRadio& radio = radios[r.device];
        ++accepted[r.device];
        const bool queued = options.downlink_every > 0 && accepted[r.device] % options.downlink_every == 0;
        Job job;
        std::uint32_t base = 0;
        if (queued) {
            job.kind = EventKind::Downlink;
            job.content = options.confirmed_uplinks ? Outcome::DataAck : Outcome::Data;
            base = kDataFrameOverheadBytes + options.downlink_payload_bytes;
        } else if (options.confirmed_uplinks) {
            job.kind = EventKind::Ack;
            job.content = Outcome::AckOnly;
            base = kAckFrameBytes;
        } else {
            continue;
        }
        job.record = i;
        job.device = r.device;
        job.t_open = r.end_ns + kReceiveDelay1Ns;
        job.rx1_hz = radio.rx1_hz;
        if (downlink_airtime_ns(radio, base, job.airtime_ns) != lora::Status::Ok) {
            return PlanStatus::InvalidRadio;
        }
        // Réciprocité : RSSI descendant = RSSI montant - P_dev + P_gw + G_dev.
        const double rssi_dl = r.rssi_dbm - radio.tx_power_dbm + options.gateway_tx_power_dbm +
                               options.device_antenna_gain_dbi;
        double sens = 0.0;
        if (lora::receiver_sensitivity_dbm(radio.rx1_sf, static_cast<lora::Bandwidth>(radio.rx1_bw_hz),
                                           sens) != lora::Status::Ok) {
            return PlanStatus::InvalidRadio;
        }
        job.received = rssi_dl >= sens + options.device_rx_offset_db;
        const std::int64_t nxt = next_start[i];
        job.device_missed = nxt != kNone && nxt < job.t_open + kRx1WindowNs;
        job_of[i] = static_cast<std::int64_t>(jobs.size());
        jobs.push_back(job);
    }

    // Planification passerelle (`_schedule_gateway`) : ordre (t_open, indice de job).
    std::vector<std::size_t> order(jobs.size());
    for (std::size_t k = 0; k < order.size(); ++k) order[k] = k;
    std::stable_sort(order.begin(), order.end(), [&jobs](std::size_t a, std::size_t b) {
        return jobs[a].t_open < jobs[b].t_open;
    });
    std::vector<std::int64_t> starts(jobs.size(), kNone);
    bool any_busy = false;
    std::int64_t busy_until = 0;
    for (std::size_t k : order) {
        const Job& job = jobs[k];
        const std::int64_t start = any_busy ? std::max(job.t_open, busy_until) : job.t_open;
        if (start - job.t_open >= kRx1WindowNs) continue;  // passerelle indisponible dans la RX1
        starts[k] = start;
        busy_until = start + job.airtime_ns;
        any_busy = true;
        busy.push_back(Interval{start, busy_until});
    }

    // Événements (`_events`) : ordre d'insertion = enregistrement, puis job ; tri stable par temps.
    struct Pending {
        std::int64_t t;
        Event ev;
    };
    std::vector<Pending> pending;
    pending.reserve(uplinks.size() + jobs.size());
    for (std::size_t i = 0; i < uplinks.size(); ++i) {
        const UplinkRecord& r = uplinks[i];
        const DeviceRadio& radio = radios[r.device];
        Pending up;
        up.t = r.start_ns;
        up.ev.t_ns = r.start_ns;
        up.ev.device = r.device;
        up.ev.kind = EventKind::Uplink;
        up.ev.outcome = from_uplink(r.outcome);
        Hop h;
        h.dir = HopDir::DevToGw;
        h.outcome = hop_from_uplink(r.outcome);
        h.has_rssi = true;
        h.rssi_dbm = r.rssi_dbm;
        h.t_ns = r.start_ns;
        h.freq_hz = radio.freq_hz;
        h.dr = radio.dr;
        up.ev.hops.push_back(h);
        if (r.outcome == UplinkOutcome::Received) {
            Hop ns;
            ns.dir = HopDir::GwToNs;
            ns.outcome = Outcome::Delivered;
            ns.t_ns = r.end_ns;
            ns.freq_hz = radio.freq_hz;
            ns.dr = radio.dr;
            up.ev.hops.push_back(ns);
        }
        pending.push_back(std::move(up));

        const std::int64_t k = job_of[i];
        if (k == kNone) continue;
        const Job& job = jobs[static_cast<std::size_t>(k)];
        const std::int64_t start = starts[static_cast<std::size_t>(k)];
        Pending ev;
        ev.t = job.t_open;
        ev.ev.device = job.device;
        if (start == kNone) {
            ev.ev.t_ns = job.t_open;
            ev.ev.kind = EventKind::RxWindowMissed;
            ev.ev.outcome = Outcome::GatewayBusy;
            Hop hop;
            hop.dir = HopDir::GwToDev;
            hop.outcome = Outcome::NotListened;
            hop.t_ns = job.t_open;
            hop.freq_hz = job.rx1_hz;
            ev.ev.hops.push_back(hop);
        } else if (job.device_missed) {
            ev.ev.t_ns = job.t_open;
            ev.ev.kind = EventKind::RxWindowMissed;
            ev.ev.outcome = Outcome::DeviceTransmitting;
            Hop hop;
            hop.dir = HopDir::GwToDev;
            hop.outcome = Outcome::NotListened;
            hop.t_ns = start;
            hop.freq_hz = job.rx1_hz;
            ev.ev.hops.push_back(hop);
        } else {
            ev.ev.t_ns = start;
            ev.ev.kind = job.kind;
            ev.ev.outcome = job.received ? job.content : Outcome::LostSensitivity;
            Hop hop;
            hop.dir = HopDir::GwToDev;
            hop.outcome = job.received ? Outcome::Delivered : Outcome::LostSensitivity;
            hop.t_ns = start;
            hop.freq_hz = job.rx1_hz;
            ev.ev.hops.push_back(hop);
            ev.t = start;
        }
        pending.push_back(std::move(ev));
    }
    std::stable_sort(pending.begin(), pending.end(),
                     [](const Pending& a, const Pending& b) { return a.t < b.t; });
    events.reserve(pending.size());
    for (Pending& p : pending) events.push_back(std::move(p.ev));
    return PlanStatus::Ok;
}

}  // namespace lsim::plan

namespace lsim::plan {

DownlinkScheduler::DownlinkScheduler(const std::vector<DeviceRadio>& radios, const PlanOptions& options)
    : options_(options), accepted_(radios.size(), 0), ack_air_(radios.size(), 0),
      data_air_(radios.size(), 0) {
    if (options.downlink_payload_bytes > kMaxDownlinkPayloadBytes) {
        status_ = PlanStatus::InvalidOptions;
        return;
    }
    if (!std::isfinite(options.gateway_tx_power_dbm) || !std::isfinite(options.device_antenna_gain_dbi) ||
        !std::isfinite(options.device_rx_offset_db)) {
        status_ = PlanStatus::InvalidOptions;
        return;
    }
    for (const DeviceRadio& rad : radios) {
        if (!valid_rx1(rad)) {
            status_ = PlanStatus::InvalidRadio;
            return;
        }
    }
    // Durées de trame : calculées à la première utilisation (comme `plan_downlinks`, une erreur
    // n'est signalée que si une descente est réellement planifiée).
    radios_ = radios;
}

std::optional<Interval> DownlinkScheduler::on_received(std::uint32_t device, std::int64_t end_ns) {
    if (status_ != PlanStatus::Ok) return std::nullopt;
    ++accepted_[device];
    const bool queued = options_.downlink_every > 0 && accepted_[device] % options_.downlink_every == 0;
    std::uint32_t base = 0;
    if (queued) {
        base = kDataFrameOverheadBytes + options_.downlink_payload_bytes;
    } else if (options_.confirmed_uplinks) {
        base = kAckFrameBytes;
    } else {
        return std::nullopt;
    }
    std::int64_t& air = queued ? data_air_[device] : ack_air_[device];
    if (air == 0 && downlink_airtime_ns(radios_[device], base, air) != lora::Status::Ok) {
        status_ = PlanStatus::InvalidRadio;
        return std::nullopt;
    }
    const std::int64_t t_open = end_ns + kReceiveDelay1Ns;
    const std::int64_t start = any_busy_ ? std::max(t_open, busy_until_) : t_open;
    if (start - t_open >= kRx1WindowNs) return std::nullopt;  // passerelle indisponible dans la RX1
    any_busy_ = true;
    busy_until_ = start + air;
    return Interval{start, busy_until_};
}

}  // namespace lsim::plan
