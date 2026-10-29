// SPDX-License-Identifier: Apache-2.0
#include "lsim/engine.hpp"

#include <algorithm>
#include <cmath>

#include "lsim/class_b.hpp"
#include "lsim/environment.hpp"
#include "lsim/link_budget.hpp"

namespace lsim::sim {
namespace classb = lorawan::classb;
namespace {

constexpr std::uint32_t kKindTxStart = 1;

bool finite(double x) {
    return std::isfinite(x);
}

// Transmission observée à la passerelle.
struct Tx {
    SimTime start = 0;
    SimTime end = 0;
    std::uint32_t device = 0;
    std::uint8_t sf = 7;
    double rssi_dbm = 0.0;
};

bool overlap(const Tx& a, const Tx& b) {
    return a.start < b.end && b.start < a.end;
}

SimStatus validate_device(const EndDeviceSpec& d) {
    if (!finite(d.position.x_m) || !finite(d.position.y_m) || !finite(d.tx_power_dbm)) {
        return SimStatus::InvalidInput;
    }
    if (d.spreading_factor < 7 || d.spreading_factor > 12) {
        return SimStatus::InvalidInput;
    }
    if (d.payload_bytes > 255) {
        return SimStatus::InvalidInput;
    }
    if (d.period_ns <= 0 || d.start_offset_ns < 0 || d.messages == 0) {
        return SimStatus::InvalidInput;
    }
    if (!finite(d.duty_cycle) || d.duty_cycle <= 0.0 || d.duty_cycle > 1.0) {
        return SimStatus::InvalidInput;
    }
    const DownlinkPlan& dl = d.downlink;
    if (dl.count > kMaxDownlinksPerDevice) return SimStatus::InvalidInput;
    if (dl.count > 0) {
        if (dl.first_request_ns < 0 || dl.rx_window_ns < 0 || dl.rx_window_ns > kMaxRxWindowNs) {
            return SimStatus::InvalidInput;
        }
        if (dl.count > 1 && dl.request_period_ns <= 0) return SimStatus::InvalidInput;
        const double last_d = static_cast<double>(dl.first_request_ns) +
                              static_cast<double>(dl.count - 1) * static_cast<double>(dl.request_period_ns);
        if (last_d > kMaxHorizonNs) return SimStatus::InvalidInput;
        if (dl.periodicity > classb::kMaxPeriodicity ||
            dl.clock_drift_ppm > classb::kMaxDriftPpm) {
            return SimStatus::InvalidInput;
        }
        if (static_cast<int>(dl.device_class) > static_cast<int>(downlink::DeviceClass::C)) {
            return SimStatus::InvalidInput;
        }
    }
    return SimStatus::Ok;
}

SimStatus validate_inputs(const GatewaySpec& g, const PropagationSpec& p) {
    if (!finite(g.position.x_m) || !finite(g.position.y_m) || !finite(g.antenna_gain_dbi)) {
        return SimStatus::InvalidInput;
    }
    if (!finite(p.frequency_hz) || p.frequency_hz <= 0.0) return SimStatus::InvalidInput;
    if (!finite(p.reference_distance_m) || p.reference_distance_m <= 0.0) return SimStatus::InvalidInput;
    if (!finite(p.exponent) || p.exponent < 1.0 || p.exponent > 6.0) return SimStatus::InvalidInput;
    if (!finite(p.capture_threshold_db) || p.capture_threshold_db < 0.0) return SimStatus::InvalidInput;
    if (!finite(p.shadowing_sigma_db) || p.shadowing_sigma_db < 0.0 ||
        p.shadowing_sigma_db > kMaxShadowingSigmaDb) {
        return SimStatus::InvalidInput;
    }
    return SimStatus::Ok;
}

// SplitMix64 : mélange déterministe et sans état, indépendant de la plateforme.
std::uint64_t splitmix64(std::uint64_t x) {
    x += 0x9E3779B97F4A7C15ULL;
    x = (x ^ (x >> 30)) * 0xBF58476D1CE4E5B9ULL;
    x = (x ^ (x >> 27)) * 0x94D049BB133111EBULL;
    return x ^ (x >> 31);
}

}  // namespace

double shadowing_sample_db(std::uint64_t seed, std::uint32_t device_index, double sigma_db) {
    if (!(sigma_db > 0.0) || !std::isfinite(sigma_db)) return 0.0;
    const std::uint64_t h1 = splitmix64(seed ^ splitmix64(static_cast<std::uint64_t>(device_index) * 2U));
    const std::uint64_t h2 = splitmix64(seed ^ splitmix64(static_cast<std::uint64_t>(device_index) * 2U + 1U));
    // Uniformes dans ]0, 1] et [0, 1[ à partir de 53 bits.
    const double u1 = (static_cast<double>(h1 >> 11) + 1.0) * 0x1.0p-53;
    const double u2 = static_cast<double>(h2 >> 11) * 0x1.0p-53;
    // Transformée de Box-Muller : gaussienne standard.
    const double z = std::sqrt(-2.0 * std::log(u1)) * std::cos(2.0 * 3.14159265358979323846 * u2);
    return sigma_db * z;
}

// ---------------------------------------------------------------- EventQueue

EventQueue::EventQueue(std::size_t capacity) : capacity_(capacity) {
    heap_.reserve(capacity);
}

bool EventQueue::before(const Event& a, const Event& b) {
    if (a.time != b.time) {
        return a.time < b.time;
    }
    return a.seq < b.seq;
}

bool EventQueue::push(SimTime time, std::uint32_t kind, std::uint32_t target) {
    if (heap_.size() >= capacity_) {
        return false;
    }
    heap_.push_back(Event{time, next_seq_++, kind, target});
    std::push_heap(heap_.begin(), heap_.end(),
                   [](const Event& a, const Event& b) { return before(b, a); });
    return true;
}

bool EventQueue::pop(Event& out) {
    if (heap_.empty()) {
        return false;
    }
    std::pop_heap(heap_.begin(), heap_.end(),
                  [](const Event& a, const Event& b) { return before(b, a); });
    out = heap_.back();
    heap_.pop_back();
    return true;
}

// ----------------------------------------------------------- simulate_uplinks

SimStatus simulate_uplinks(const EndDeviceSpec* devices, std::size_t device_count,
                           const GatewaySpec& gateway, const PropagationSpec& prop,
                           DeviceStats* per_device, SimulationStats& totals,
                           const env::Environment* environment, std::vector<TxRecord>* trace) {
    totals = SimulationStats{};
    if (trace != nullptr) trace->clear();
    if (device_count > kMaxEndDevices) {
        return SimStatus::TooManyDevices;
    }
    if (device_count > 0 && (devices == nullptr || per_device == nullptr)) {
        return SimStatus::InvalidInput;
    }
    const SimStatus gs = validate_inputs(gateway, prop);
    if (gs != SimStatus::Ok) {
        return gs;
    }
    const env::Environment no_environment{};
    const env::Environment& envr = environment != nullptr ? *environment : no_environment;
    if (environment != nullptr) {
        if (env::validate_environment(envr) != env::EnvStatus::Ok) {
            return SimStatus::InvalidEnvironment;
        }
        const std::uint64_t checks = static_cast<std::uint64_t>(device_count) * envr.obstacle_count;
        if (checks > env::kMaxObstacleChecks) {
            return SimStatus::EnvironmentWorkLimit;
        }
    }

    // Précalcul par dispositif : airtime, RSSI à la passerelle, sensibilité.
    std::vector<SimTime> airtime(device_count);
    std::vector<double> rssi(device_count);
    std::vector<double> sensitivity(device_count);
    std::uint64_t total_tx = 0;

    radio::LogDistanceModel model;
    model.frequency_hz = prop.frequency_hz;
    model.reference_distance_m = prop.reference_distance_m;
    model.exponent = prop.exponent;

    for (std::size_t i = 0; i < device_count; ++i) {
        const EndDeviceSpec& d = devices[i];
        const SimStatus ds = validate_device(d);
        if (ds != SimStatus::Ok) {
            return ds;
        }
        per_device[i] = DeviceStats{};

        lora::RadioConfig rc;
        rc.spreading_factor = d.spreading_factor;
        rc.bandwidth = lora::Bandwidth::Bw125kHz;
        rc.coding_rate = 1;
        rc.low_data_rate_optimize = lora::low_data_rate_required(d.spreading_factor, rc.bandwidth);
        const lora::AirtimeResult at = lora::time_on_air(rc, d.payload_bytes);
        if (at.status != lora::Status::Ok) {
            return SimStatus::InvalidInput;
        }
        airtime[i] = at.nanoseconds;

        // Distance minimale : d0 (évite les pertes négatives à très courte portée).
        const double dx = d.position.x_m - gateway.position.x_m;
        const double dy = d.position.y_m - gateway.position.y_m;
        const double dist = std::max(std::hypot(dx, dy), prop.reference_distance_m);
        double path_loss = 0.0;
        if (environment != nullptr) {
            env::PathLoss pl{};
            if (env::path_loss_db(model, d.position.x_m, d.position.y_m, gateway.position.x_m,
                                  gateway.position.y_m, envr, pl) != env::EnvStatus::Ok) {
                return SimStatus::InvalidEnvironment;
            }
            path_loss = pl.total_db;
        } else {
            const radio::BudgetResult pl = radio::log_distance_path_loss_db(model, dist);
            if (pl.status != lora::Status::Ok) {
                return SimStatus::InvalidInput;
            }
            path_loss = pl.value;
        }
        const double shadow = shadowing_sample_db(prop.shadowing_seed, static_cast<std::uint32_t>(i),
                                                  prop.shadowing_sigma_db);
        rssi[i] = d.tx_power_dbm + gateway.antenna_gain_dbi - path_loss - shadow;

        double s = 0.0;
        if (lora::receiver_sensitivity_dbm(d.spreading_factor, rc.bandwidth, s) != lora::Status::Ok) {
            return SimStatus::InvalidInput;
        }
        sensitivity[i] = s;

        total_tx += d.messages;
        if (total_tx > kMaxTransmissions) {
            return SimStatus::TooManyTransmissions;
        }
    }

    // Borne globale des requêtes de downlink (coût de calcul des opportunités).
    std::uint64_t total_dl = 0;
    for (std::size_t i = 0; i < device_count; ++i) {
        total_dl += devices[i].downlink.count;
    }
    if (total_dl > kMaxDownlinkRequests) return SimStatus::TooManyDownlinks;

    // Ordonnancement des émissions dans la file bornée.
    EventQueue queue(static_cast<std::size_t>(total_tx));
    for (std::size_t i = 0; i < device_count; ++i) {
        const EndDeviceSpec& d = devices[i];
        // Le rapport cyclique est propre à chaque dispositif : le décalage se
        // calcule ici, dans l'ordre de ses propres émissions.
        const double off_factor = (1.0 - d.duty_cycle) / d.duty_cycle;
        SimTime prev_end = 0;
        for (std::uint32_t k = 0; k < d.messages; ++k) {
            const double nominal_d = static_cast<double>(d.start_offset_ns) +
                                     static_cast<double>(k) * static_cast<double>(d.period_ns);
            if (nominal_d > kMaxHorizonNs) {
                return SimStatus::InvalidInput;
            }
            SimTime t = static_cast<SimTime>(nominal_d);
            if (k > 0 && off_factor > 0.0) {
                const double earliest_d = static_cast<double>(prev_end) +
                                          std::round(static_cast<double>(airtime[i]) * off_factor);
                if (earliest_d > kMaxHorizonNs) {
                    return SimStatus::InvalidInput;
                }
                t = std::max(t, static_cast<SimTime>(earliest_d));
            }
            if (!queue.push(t, kKindTxStart, static_cast<std::uint32_t>(i))) {
                return SimStatus::QueueFull;
            }
            prev_end = t + airtime[i];
            ++per_device[i].sent;
        }
    }

    // Extraction dans l'ordre temporel : les émissions sont triées par début.
    std::vector<Tx> txs;
    txs.reserve(static_cast<std::size_t>(total_tx));
    SimTime max_airtime = 0;
    Event ev;
    while (queue.pop(ev)) {
        if (ev.kind != kKindTxStart || ev.target >= device_count) {
            continue;
        }
        const std::uint32_t i = ev.target;
        Tx t;
        t.start = ev.time;
        t.end = ev.time + airtime[i];
        t.device = i;
        t.sf = devices[i].spreading_factor;
        t.rssi_dbm = rssi[i];
        max_airtime = std::max(max_airtime, airtime[i]);
        per_device[i].airtime_ns += static_cast<std::uint64_t>(airtime[i]);
        totals.airtime_ns += static_cast<std::uint64_t>(airtime[i]);
        txs.push_back(t);
    }

    // Métriques passerelle : union des intervalles, pic de simultanéité, charge.
    // `txs` est trié par début ; les fins sont triées à part (deux pointeurs).
    if (!txs.empty()) {
        SimTime busy = 0;
        SimTime cur_s = txs[0].start;
        SimTime cur_e = txs[0].end;
        SimTime last_end = txs[0].end;
        for (std::size_t k = 1; k < txs.size(); ++k) {
            last_end = std::max(last_end, txs[k].end);
            if (txs[k].start > cur_e) {
                busy += cur_e - cur_s;
                cur_s = txs[k].start;
                cur_e = txs[k].end;
            } else {
                cur_e = std::max(cur_e, txs[k].end);
            }
        }
        busy += cur_e - cur_s;

        std::vector<SimTime> ends;
        ends.reserve(txs.size());
        for (const Tx& t : txs) ends.push_back(t.end);
        std::sort(ends.begin(), ends.end());

        std::uint64_t peak = 0;
        std::size_t ended = 0;
        for (std::size_t k = 0; k < txs.size(); ++k) {
            while (ended < ends.size() && ends[ended] <= txs[k].start) ++ended;
            const std::uint64_t active = static_cast<std::uint64_t>(k + 1 - ended);
            peak = std::max(peak, active);
        }

        const SimTime observation = last_end - txs[0].start;
        totals.gateway_busy_ns = static_cast<std::uint64_t>(busy);
        totals.gateway_peak_concurrent = peak;
        totals.observation_ns = observation;
        totals.gateway_utilization =
            observation > 0 ? static_cast<double>(busy) / static_cast<double>(observation) : 0.0;
    }

    // Évaluation : sensibilité, puis collision avec capture.
    if (trace != nullptr) trace->reserve(txs.size());
    for (std::size_t a = 0; a < txs.size(); ++a) {
        const Tx& ta = txs[a];
        DeviceStats& st = per_device[ta.device];
        TxOutcome outcome = TxOutcome::LostSensitivity;

        if (ta.rssi_dbm < sensitivity[ta.device]) {
            ++st.lost_sensitivity;
            ++totals.lost_sensitivity;
        } else {
            // Interférence maximale parmi les émissions simultanées de même SF.
            bool interfered = false;
            double max_interf = -1e300;
            auto consider = [&](const Tx& tb) {
                if (tb.sf == ta.sf && overlap(ta, tb)) {
                    interfered = true;
                    max_interf = std::max(max_interf, tb.rssi_dbm);
                }
            };
            for (std::size_t b = a + 1; b < txs.size() && txs[b].start < ta.end; ++b) {
                consider(txs[b]);
            }
            for (std::size_t b = a; b-- > 0;) {
                if (txs[b].start + max_airtime <= ta.start) {
                    break;  // plus aucune émission antérieure ne peut chevaucher
                }
                consider(txs[b]);
            }

            const bool captured = !interfered || (ta.rssi_dbm - max_interf >= prop.capture_threshold_db);
            if (captured) {
                ++st.received;
                ++totals.received;
                outcome = TxOutcome::Received;
            } else {
                ++st.lost_collision;
                ++totals.lost_collision;
                outcome = TxOutcome::LostCollision;
            }
        }
        if (trace != nullptr) {
            trace->push_back(TxRecord{ta.device, ta.start, ta.end, ta.sf, ta.rssi_dbm, outcome});
        }
    }

    // Downlinks : pour chaque dispositif demandé, latence jusqu'à la première fenêtre de
    // réception utilisable. Observation : jusqu'à la fin de la dernière émission.
    SimTime horizon = 0;
    for (const Tx& t : txs) horizon = std::max(horizon, t.end);
    std::vector<std::vector<downlink::Window>> uplinks(device_count);
    for (const Tx& t : txs) {
        if (devices[t.device].downlink.count > 0) {
            uplinks[t.device].push_back(downlink::Window{t.start, t.end});
        }
    }
    for (std::size_t i = 0; i < device_count; ++i) {
        const DownlinkPlan& dl = devices[i].downlink;
        if (dl.count == 0) continue;
        DownlinkStats& st = per_device[i].downlink;
        const downlink::Timing timing{1'000'000'000, 2'000'000'000, dl.rx_window_ns};
        std::vector<downlink::Window> blocked;
        if (dl.device_class != downlink::DeviceClass::A) {
            if (downlink::class_c_blocked(uplinks[i], timing, blocked) !=
                downlink::DownlinkStatus::Ok) {
                return SimStatus::InvalidInput;
            }
        }
        const downlink::ClassBProfile profile{dl.dev_addr, dl.periodicity, dl.clock_drift_ppm};
        for (std::uint32_t k = 0; k < dl.count; ++k) {
            const SimTime request = dl.first_request_ns + static_cast<SimTime>(k) * dl.request_period_ns;
            ++st.requested;
            SimTime opp = 0;
            downlink::DownlinkStatus ds = downlink::DownlinkStatus::NoOpportunity;
            if (dl.device_class == downlink::DeviceClass::A) {
                ds = downlink::next_class_a(uplinks[i], request, timing, opp);
            } else if (dl.device_class == downlink::DeviceClass::C) {
                ds = downlink::next_class_c(blocked, request, opp);
            } else {
                ds = downlink::next_class_b(profile, blocked, request, opp);
            }
            if (ds != downlink::DownlinkStatus::Ok || opp > horizon) continue;
            const std::uint64_t latency = static_cast<std::uint64_t>(opp - request);
            ++st.delivered;
            st.latency_sum_ns += latency;
            st.latency_max_ns = std::max(st.latency_max_ns, latency);
        }
        totals.downlink.requested += st.requested;
        totals.downlink.delivered += st.delivered;
        totals.downlink.latency_sum_ns += st.latency_sum_ns;
        totals.downlink.latency_max_ns = std::max(totals.downlink.latency_max_ns, st.latency_max_ns);
    }

    for (std::size_t i = 0; i < device_count; ++i) {
        totals.sent += per_device[i].sent;
    }
    return SimStatus::Ok;
}

}  // namespace lsim::sim
