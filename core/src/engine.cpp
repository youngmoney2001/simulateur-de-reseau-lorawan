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
                           const env::Environment* environment, std::vector<TxRecord>* trace,
                           const std::vector<Interval>* gateway_busy) {
    totals = SimulationStats{};
    if (trace != nullptr) trace->clear();
    // Périodes d'émission passerelle : triées et fusionnées (intervalles disjoints, triés).
    std::vector<Interval> busy;
    if (gateway_busy != nullptr) {
        busy = *gateway_busy;
        for (const Interval& b : busy) {
            if (b.end <= b.start) return SimStatus::InvalidGatewayBusy;
        }
        std::sort(busy.begin(), busy.end(), [](const Interval& a, const Interval& b) {
            return a.start < b.start;
        });
        std::vector<Interval> merged;
        for (const Interval& b : busy) {
            if (!merged.empty() && b.start <= merged.back().end) {
                merged.back().end = std::max(merged.back().end, b.end);
            } else {
                merged.push_back(b);
            }
        }
        busy.swap(merged);
    }
    // Vrai si la trame [start, end) chevauche une période d'émission passerelle.
    auto gateway_transmitting = [&busy](SimTime start, SimTime end) {
        auto it = std::lower_bound(busy.begin(), busy.end(), start,
                                   [](const Interval& b, SimTime s) { return b.end <= s; });
        return it != busy.end() && it->start < end;
    };
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
        } else if (gateway_transmitting(ta.start, ta.end)) {
            // Demi-duplex : la passerelle émet un downlink, elle ne reçoit pas cette trame.
            ++st.lost_gateway_busy;
            ++totals.lost_gateway_busy;
            outcome = TxOutcome::LostGatewayBusy;
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

// ------------------------------------------------- simulate_uplinks_multi

// Charge de réception par passerelle, sur les trames audibles (RSSI >= sensibilité) :
// union des intervalles, pic de simultanéité. Balayage d'événements, fins avant débuts.
static void fill_gateway_load(const std::vector<Tx>& txs, const std::vector<double>& rssi,
                              const std::vector<double>& sensitivity, std::size_t G,
                              GatewayRxStats* per_gateway) {
    if (txs.empty()) return;
    SimTime first = txs.front().start;
    SimTime last_end = txs.front().end;
    for (const Tx& t : txs) {
        first = std::min(first, t.start);
        last_end = std::max(last_end, t.end);
    }
    std::vector<std::pair<SimTime, int>> events;
    for (std::size_t g = 0; g < G; ++g) {
        events.clear();
        std::uint64_t audible = 0;
        for (const Tx& t : txs) {
            if (rssi[t.device * G + g] < sensitivity[t.device]) continue;
            events.emplace_back(t.start, +1);
            events.emplace_back(t.end, -1);
            ++audible;
        }
        std::sort(events.begin(), events.end());  // à égalité de temps, la fin (-1) passe avant
        SimTime busy = 0;
        SimTime run_start = 0;
        std::int64_t depth = 0;
        std::int64_t peak = 0;
        for (const auto& ev : events) {
            if (ev.second > 0) {
                if (depth == 0) run_start = ev.first;
                ++depth;
                peak = std::max(peak, depth);
            } else {
                --depth;
                if (depth == 0) busy += ev.first - run_start;
            }
        }
        GatewayRxStats& gs = per_gateway[g];
        gs.audible_frames = audible;
        gs.busy_ns = static_cast<std::uint64_t>(busy);
        gs.peak_concurrent = static_cast<std::uint64_t>(peak);
        gs.observation_ns = last_end - first;
    }
}

// Préparation commune aux fonctions multi-passerelles : airtime, sensibilité et RSSI par
// dispositif et passerelle (rssi[i * G + g]). Le shadowing est tiré une fois par dispositif.
static SimStatus prepare_links(const EndDeviceSpec* devices, std::size_t device_count,
                        const GatewaySpec* gateways, std::size_t G, const PropagationSpec& prop,
                        const env::Environment* environment, std::vector<SimTime>& airtime,
                        std::vector<double>& sensitivity, std::vector<double>& rssi,
                        std::uint64_t& total_tx) {
    const env::Environment no_environment{};
    const env::Environment& envr = environment != nullptr ? *environment : no_environment;
    airtime.assign(device_count, 0);
    sensitivity.assign(device_count, 0.0);
    rssi.assign(device_count * G, 0.0);
    total_tx = 0;

    radio::LogDistanceModel model;
    model.frequency_hz = prop.frequency_hz;
    model.reference_distance_m = prop.reference_distance_m;
    model.exponent = prop.exponent;

    for (std::size_t i = 0; i < device_count; ++i) {
        const EndDeviceSpec& d = devices[i];
        const SimStatus ds = validate_device(d);
        if (ds != SimStatus::Ok) return ds;

        lora::RadioConfig rc;
        rc.spreading_factor = d.spreading_factor;
        rc.bandwidth = lora::Bandwidth::Bw125kHz;
        rc.coding_rate = 1;
        rc.low_data_rate_optimize = lora::low_data_rate_required(d.spreading_factor, rc.bandwidth);
        const lora::AirtimeResult at = lora::time_on_air(rc, d.payload_bytes);
        if (at.status != lora::Status::Ok) return SimStatus::InvalidInput;
        airtime[i] = at.nanoseconds;

        double s = 0.0;
        if (lora::receiver_sensitivity_dbm(d.spreading_factor, rc.bandwidth, s) != lora::Status::Ok) {
            return SimStatus::InvalidInput;
        }
        sensitivity[i] = s;

        // Shadowing : un tirage par dispositif, commun à toutes les passerelles (hypothèse :
        // évanouissement lent côté dispositif). Voir docs/STUDY_PANEL_SPEC.md.
        const double shadow = shadowing_sample_db(prop.shadowing_seed, static_cast<std::uint32_t>(i),
                                                  prop.shadowing_sigma_db);
        for (std::size_t g = 0; g < G; ++g) {
            const GatewaySpec& gw = gateways[g];
            const double dx = d.position.x_m - gw.position.x_m;
            const double dy = d.position.y_m - gw.position.y_m;
            const double dist = std::max(std::hypot(dx, dy), prop.reference_distance_m);
            double path_loss = 0.0;
            if (environment != nullptr) {
                env::PathLoss pl{};
                if (env::path_loss_db(model, d.position.x_m, d.position.y_m, gw.position.x_m,
                                      gw.position.y_m, envr, pl) != env::EnvStatus::Ok) {
                    return SimStatus::InvalidEnvironment;
                }
                path_loss = pl.total_db;
            } else {
                const radio::BudgetResult pl = radio::log_distance_path_loss_db(model, dist);
                if (pl.status != lora::Status::Ok) return SimStatus::InvalidInput;
                path_loss = pl.value;
            }
            rssi[i * G + g] = d.tx_power_dbm + gw.antenna_gain_dbi - path_loss - shadow;
        }

        total_tx += d.messages;
        if (total_tx > kMaxTransmissions) return SimStatus::TooManyTransmissions;
    }

    return SimStatus::Ok;
}

SimStatus simulate_uplinks_multi(const EndDeviceSpec* devices, std::size_t device_count,
                                 const GatewaySpec* gateways, std::size_t gateway_count,
                                 const PropagationSpec& prop, DeviceStats* per_device,
                                 NetworkStats& totals, GatewayRxStats* per_gateway,
                                 const env::Environment* environment, std::vector<MultiTx>* trace,
                                 const std::vector<std::vector<Interval>>* gateway_busy) {
    totals = NetworkStats{};
    if (trace != nullptr) trace->clear();
    // Émissions passerelle par passerelle : bornes, tri et fusion, comme en mono-passerelle.
    std::vector<std::vector<Interval>> busy(gateway_count);
    if (gateway_busy != nullptr) {
        if (gateway_busy->size() != gateway_count) return SimStatus::InvalidGatewayBusy;
        for (std::size_t g = 0; g < gateway_count; ++g) {
            std::vector<Interval> v = (*gateway_busy)[g];
            for (const Interval& b : v) {
                if (b.end <= b.start) return SimStatus::InvalidGatewayBusy;
            }
            std::sort(v.begin(), v.end(), [](const Interval& a, const Interval& b) {
                return a.start < b.start;
            });
            std::vector<Interval> merged;
            for (const Interval& b : v) {
                if (!merged.empty() && b.start <= merged.back().end) {
                    merged.back().end = std::max(merged.back().end, b.end);
                } else {
                    merged.push_back(b);
                }
            }
            busy[g].swap(merged);
        }
    }
    auto transmitting = [&busy](std::size_t g, SimTime start, SimTime end) {
        const std::vector<Interval>& v = busy[g];
        auto it = std::lower_bound(v.begin(), v.end(), start,
                                   [](const Interval& b, SimTime s) { return b.end <= s; });
        return it != v.end() && it->start < end;
    };
    if (device_count > kMaxEndDevices) return SimStatus::TooManyDevices;
    if (gateway_count == 0 || gateway_count > kMaxGateways || gateways == nullptr ||
        per_gateway == nullptr) {
        return SimStatus::InvalidInput;
    }
    if (gateway_busy != nullptr && gateway_busy->size() != gateway_count) {
        return SimStatus::InvalidGatewayBusy;
    }
    if (device_count > 0 && (devices == nullptr || per_device == nullptr)) {
        return SimStatus::InvalidInput;
    }
    for (std::size_t g = 0; g < gateway_count; ++g) {
        const SimStatus gs = validate_inputs(gateways[g], prop);
        if (gs != SimStatus::Ok) return gs;
        per_gateway[g] = GatewayRxStats{};
    }
    const env::Environment no_environment{};
    const env::Environment& envr = environment != nullptr ? *environment : no_environment;
    if (environment != nullptr) {
        if (env::validate_environment(envr) != env::EnvStatus::Ok) {
            return SimStatus::InvalidEnvironment;
        }
        const std::uint64_t checks = static_cast<std::uint64_t>(device_count) *
                                     envr.obstacle_count * gateway_count;
        if (checks > env::kMaxObstacleChecks) return SimStatus::EnvironmentWorkLimit;
    }

    const std::size_t G = gateway_count;
    std::vector<SimTime> airtime;
    std::vector<double> sensitivity;
    std::vector<double> rssi;  // rssi[i * G + g]
    std::uint64_t total_tx = 0;
    const SimStatus ls = prepare_links(devices, device_count, gateways, G, prop, environment,
                                       airtime, sensitivity, rssi, total_tx);
    if (ls != SimStatus::Ok) return ls;
    for (std::size_t i = 0; i < device_count; ++i) per_device[i] = DeviceStats{};

    // Émissions, triées par début puis par dispositif (ordre déterministe).
    std::vector<Tx> txs;
    txs.reserve(static_cast<std::size_t>(total_tx));
    SimTime max_airtime = 0;
    for (std::size_t i = 0; i < device_count; ++i) {
        const EndDeviceSpec& d = devices[i];
        const double off_factor = (1.0 - d.duty_cycle) / d.duty_cycle;
        SimTime prev_end = 0;
        for (std::uint32_t k = 0; k < d.messages; ++k) {
            const double nominal_d = static_cast<double>(d.start_offset_ns) +
                                     static_cast<double>(k) * static_cast<double>(d.period_ns);
            if (nominal_d > kMaxHorizonNs) return SimStatus::InvalidInput;
            SimTime t = static_cast<SimTime>(nominal_d);
            if (k > 0 && off_factor > 0.0) {
                const double earliest_d = static_cast<double>(prev_end) +
                                          std::round(static_cast<double>(airtime[i]) * off_factor);
                if (earliest_d > kMaxHorizonNs) return SimStatus::InvalidInput;
                t = std::max(t, static_cast<SimTime>(earliest_d));
            }
            Tx tx;
            tx.start = t;
            tx.end = t + airtime[i];
            tx.device = static_cast<std::uint32_t>(i);
            tx.sf = d.spreading_factor;
            tx.rssi_dbm = 0.0;  // RSSI par passerelle : voir rssi[]
            txs.push_back(tx);
            prev_end = tx.end;
            ++per_device[i].sent;
            ++totals.sent;
            per_device[i].airtime_ns += static_cast<std::uint64_t>(airtime[i]);
            totals.airtime_ns += static_cast<std::uint64_t>(airtime[i]);
            max_airtime = std::max(max_airtime, airtime[i]);
        }
    }
    std::stable_sort(txs.begin(), txs.end(), [](const Tx& a, const Tx& b) {
        if (a.start != b.start) return a.start < b.start;
        return a.device < b.device;
    });
    fill_gateway_load(txs, rssi, sensitivity, G, per_gateway);

    if (trace != nullptr) trace->reserve(txs.size());
    for (std::size_t a = 0; a < txs.size(); ++a) {
        const Tx& ta = txs[a];
        MultiTx out;
        out.device = ta.device;
        out.start_ns = ta.start;
        out.end_ns = ta.end;
        out.spreading_factor = ta.sf;
        out.best_rssi_dbm = -1e300;
        bool any_collision = false;

        bool any_busy = false;
        for (std::size_t g = 0; g < G; ++g) {
            const double r = rssi[ta.device * G + g];
            if (r < sensitivity[ta.device]) {
                ++per_gateway[g].lost_sensitivity;
                continue;
            }
            if (transmitting(g, ta.start, ta.end)) {
                // Demi-duplex : cette passerelle émet un downlink, elle ne reçoit pas la trame.
                ++per_gateway[g].lost_gateway_busy;
                any_busy = true;
                continue;
            }
            // Interférence maximale à cette passerelle parmi les émissions simultanées de même SF.
            bool interfered = false;
            double max_interf = -1e300;
            auto consider = [&](const Tx& tb) {
                if (tb.sf == ta.sf && overlap(ta, tb)) {
                    interfered = true;
                    max_interf = std::max(max_interf, rssi[tb.device * G + g]);
                }
            };
            for (std::size_t b = a + 1; b < txs.size() && txs[b].start < ta.end; ++b) {
                consider(txs[b]);
            }
            for (std::size_t b = a; b-- > 0;) {
                if (txs[b].start + max_airtime <= ta.start) break;
                consider(txs[b]);
            }
            const bool captured = !interfered || (r - max_interf >= prop.capture_threshold_db);
            if (captured) {
                ++per_gateway[g].received;
                ++out.receivers;
                out.decoded_mask |= std::uint64_t{1} << g;
                if (r > out.best_rssi_dbm) {
                    out.best_rssi_dbm = r;
                    out.best_gateway = static_cast<std::int32_t>(g);
                }
            } else {
                ++per_gateway[g].lost_collision;
                any_collision = true;
            }
        }
        // RSSI max si aucune passerelle ne décode : sert à la trace.
        if (out.best_gateway < 0) {
            double max_r = -1e300;
            for (std::size_t g = 0; g < G; ++g) max_r = std::max(max_r, rssi[ta.device * G + g]);
            out.best_rssi_dbm = max_r;
        }

        DeviceStats& st = per_device[ta.device];
        if (out.receivers > 0) {
            out.outcome = TxOutcome::Received;
            ++st.received;
            ++totals.received;
            totals.duplicates += out.receivers - 1;
        } else if (any_collision) {
            out.outcome = TxOutcome::LostCollision;
            ++st.lost_collision;
            ++totals.lost_collision;
        } else if (any_busy) {
            out.outcome = TxOutcome::LostGatewayBusy;
            ++st.lost_gateway_busy;
            ++totals.lost_gateway_busy;
        } else {
            out.outcome = TxOutcome::LostSensitivity;
            ++st.lost_sensitivity;
            ++totals.lost_sensitivity;
        }
        if (trace != nullptr) trace->push_back(out);
    }
    return SimStatus::Ok;
}

// ------------------------------------------ passerelles + downlinks (ordre de fin)

namespace {

// Airtime d'un downlink au débit RX1 (= SF de l'uplink, BW 125 kHz), CR 4/5, en-tête explicite,
// sans CRC (LoRaWAN).
SimStatus downlink_airtime(std::uint8_t sf, std::uint32_t payload_bytes, SimTime& out) {
    lora::RadioConfig rc;
    rc.spreading_factor = sf;
    rc.bandwidth = lora::Bandwidth::Bw125kHz;
    rc.coding_rate = 1;
    rc.crc_on = false;
    rc.explicit_header = true;
    rc.low_data_rate_optimize = lora::low_data_rate_required(sf, rc.bandwidth);
    const lora::AirtimeResult at = lora::time_on_air(rc, static_cast<std::uint8_t>(payload_bytes));
    if (at.status != lora::Status::Ok) return SimStatus::InvalidInput;
    out = at.nanoseconds;
    return SimStatus::Ok;
}

// Vrai si [start, end) chevauche une période de la liste triée et disjointe.
bool intersects(const std::vector<Interval>& v, SimTime start, SimTime end) {
    auto it = std::lower_bound(v.begin(), v.end(), start,
                               [](const Interval& b, SimTime s) { return b.end <= s; });
    return it != v.end() && it->start < end;
}

constexpr std::uint32_t kAckFrameBytes = 12;      // MHDR, DevAddr, FCtrl, FCnt, MIC
constexpr std::uint32_t kDataFrameOverhead = 13;  // ACK + FPort
constexpr SimTime kRx1DelayNs = 1'000'000'000;
constexpr SimTime kRx1WindowNs = 1'000'000'000;

}  // namespace

SimStatus simulate_uplinks_multi_downlinks(
    const EndDeviceSpec* devices, std::size_t device_count, const GatewaySpec* gateways,
    std::size_t gateway_count, const PropagationSpec& prop, const MultiDownlinkRule& rule,
    DeviceStats* per_device, NetworkStats& totals, GatewayRxStats* per_gateway,
    const env::Environment* environment, std::vector<MultiTx>* trace,
    std::vector<MultiDownlink>* downlinks) {
    totals = NetworkStats{};
    if (trace != nullptr) trace->clear();
    if (downlinks != nullptr) downlinks->clear();
    if (device_count > kMaxEndDevices) return SimStatus::TooManyDevices;
    if (gateway_count == 0 || gateway_count > kMaxGateways || gateways == nullptr ||
        per_gateway == nullptr) {
        return SimStatus::InvalidInput;
    }
    if (device_count > 0 && (devices == nullptr || per_device == nullptr)) {
        return SimStatus::InvalidInput;
    }
    if (rule.payload_bytes > 242 || !finite(rule.gateway_tx_power_dbm) ||
        !finite(rule.device_antenna_gain_dbi) || !finite(rule.device_rx_offset_db)) {
        return SimStatus::InvalidInput;
    }
    for (std::size_t g = 0; g < gateway_count; ++g) {
        const SimStatus gs = validate_inputs(gateways[g], prop);
        if (gs != SimStatus::Ok) return gs;
        per_gateway[g] = GatewayRxStats{};
    }
    const std::size_t G = gateway_count;
    std::vector<SimTime> airtime;
    std::vector<double> sensitivity;
    std::vector<double> rssi;
    std::uint64_t total_tx = 0;
    const SimStatus ls = prepare_links(devices, device_count, gateways, G, prop, environment,
                                       airtime, sensitivity, rssi, total_tx);
    if (ls != SimStatus::Ok) return ls;
    for (std::size_t i = 0; i < device_count; ++i) per_device[i] = DeviceStats{};

    // Émissions, triées par début (puis dispositif). Prochain début du même dispositif (-1 : aucun).
    std::vector<Tx> txs;
    txs.reserve(static_cast<std::size_t>(total_tx));
    SimTime max_airtime = 0;
    for (std::size_t i = 0; i < device_count; ++i) {
        const EndDeviceSpec& d = devices[i];
        const double off_factor = (1.0 - d.duty_cycle) / d.duty_cycle;
        SimTime prev_end = 0;
        for (std::uint32_t k = 0; k < d.messages; ++k) {
            const double nominal_d = static_cast<double>(d.start_offset_ns) +
                                     static_cast<double>(k) * static_cast<double>(d.period_ns);
            if (nominal_d > kMaxHorizonNs) return SimStatus::InvalidInput;
            SimTime t = static_cast<SimTime>(nominal_d);
            if (k > 0 && off_factor > 0.0) {
                const double earliest_d = static_cast<double>(prev_end) +
                                          std::round(static_cast<double>(airtime[i]) * off_factor);
                if (earliest_d > kMaxHorizonNs) return SimStatus::InvalidInput;
                t = std::max(t, static_cast<SimTime>(earliest_d));
            }
            Tx tx;
            tx.start = t;
            tx.end = t + airtime[i];
            tx.device = static_cast<std::uint32_t>(i);
            tx.sf = d.spreading_factor;
            txs.push_back(tx);
            prev_end = tx.end;
            ++per_device[i].sent;
            ++totals.sent;
            per_device[i].airtime_ns += static_cast<std::uint64_t>(airtime[i]);
            totals.airtime_ns += static_cast<std::uint64_t>(airtime[i]);
            max_airtime = std::max(max_airtime, airtime[i]);
        }
    }
    std::stable_sort(txs.begin(), txs.end(), [](const Tx& a, const Tx& b) {
        if (a.start != b.start) return a.start < b.start;
        return a.device < b.device;
    });
    fill_gateway_load(txs, rssi, sensitivity, G, per_gateway);
    const std::size_t T = txs.size();
    std::vector<std::int64_t> next_start(T, -1);
    {
        std::vector<std::int64_t> last(device_count, -1);
        for (std::size_t a = T; a-- > 0;) {
            const std::uint32_t d = txs[a].device;
            next_start[a] = last[d];
            last[d] = static_cast<std::int64_t>(txs[a].start);
        }
    }

    // Passe 1 (ordre de début) : échecs statiques par passerelle, indépendants des downlinks.
    // Bit g de sens_fail : sous la sensibilité ; bit g de coll_fail : collision non capturée.
    std::vector<std::uint64_t> sens_fail(T, 0), coll_fail(T, 0);
    for (std::size_t a = 0; a < T; ++a) {
        const Tx& ta = txs[a];
        for (std::size_t g = 0; g < G; ++g) {
            const double r = rssi[ta.device * G + g];
            if (r < sensitivity[ta.device]) {
                sens_fail[a] |= std::uint64_t{1} << g;
                continue;
            }
            bool interfered = false;
            double max_interf = -1e300;
            auto consider = [&](const Tx& tb) {
                if (tb.sf == ta.sf && overlap(ta, tb)) {
                    interfered = true;
                    max_interf = std::max(max_interf, rssi[tb.device * G + g]);
                }
            };
            for (std::size_t b = a + 1; b < T && txs[b].start < ta.end; ++b) consider(txs[b]);
            for (std::size_t b = a; b-- > 0;) {
                if (txs[b].start + max_airtime <= ta.start) break;
                consider(txs[b]);
            }
            const bool captured = !interfered || (r - max_interf >= prop.capture_threshold_db);
            if (!captured) coll_fail[a] |= std::uint64_t{1} << g;
        }
    }

    // Passe 2 (ordre de fin) : décodage avec demi-duplex, puis downlink de la meilleure passerelle.
    std::vector<std::size_t> by_end(T);
    for (std::size_t a = 0; a < T; ++a) by_end[a] = a;
    std::stable_sort(by_end.begin(), by_end.end(), [&txs](std::size_t x, std::size_t y) {
        return txs[x].end < txs[y].end;
    });
    std::vector<std::vector<Interval>> busy(G);
    std::vector<SimTime> busy_until(G, 0);
    std::vector<std::uint32_t> accepted(device_count, 0);
    std::vector<MultiTx> out(T);
    std::vector<MultiDownlink> dls;

    for (std::size_t a : by_end) {
        const Tx& ta = txs[a];
        const std::uint32_t d = ta.device;
        MultiTx m;
        m.device = d;
        m.start_ns = ta.start;
        m.end_ns = ta.end;
        m.spreading_factor = ta.sf;
        m.best_rssi_dbm = -1e300;
        bool any_collision = false;
        bool any_busy = false;
        std::uint32_t receivers = 0;
        for (std::size_t g = 0; g < G; ++g) {
            const std::uint64_t bit = std::uint64_t{1} << g;
            GatewayRxStats& gs = per_gateway[g];
            if (sens_fail[a] & bit) {
                ++gs.lost_sensitivity;
                continue;
            }
            if (intersects(busy[g], ta.start, ta.end)) {
                ++gs.lost_gateway_busy;
                any_busy = true;
                continue;
            }
            if (coll_fail[a] & bit) {
                ++gs.lost_collision;
                any_collision = true;
                continue;
            }
            ++gs.received;
            ++receivers;
            m.decoded_mask |= bit;
            const double r = rssi[d * G + g];
            if (r > m.best_rssi_dbm) {
                m.best_rssi_dbm = r;
                m.best_gateway = static_cast<std::int32_t>(g);
            }
        }
        m.receivers = receivers;
        if (m.best_gateway < 0) {
            double max_r = -1e300;
            for (std::size_t g = 0; g < G; ++g) max_r = std::max(max_r, rssi[d * G + g]);
            m.best_rssi_dbm = max_r;
        }

        DeviceStats& st = per_device[d];
        if (receivers > 0) {
            m.outcome = TxOutcome::Received;
            ++st.received;
            ++totals.received;
            totals.duplicates += receivers - 1;
        } else if (any_collision) {
            m.outcome = TxOutcome::LostCollision;
            ++st.lost_collision;
            ++totals.lost_collision;
        } else if (any_busy) {
            m.outcome = TxOutcome::LostGatewayBusy;
            ++st.lost_gateway_busy;
            ++totals.lost_gateway_busy;
        } else {
            m.outcome = TxOutcome::LostSensitivity;
            ++st.lost_sensitivity;
            ++totals.lost_sensitivity;
        }
        out[a] = m;

        if (receivers == 0) continue;
        ++accepted[d];
        const bool queued = rule.every > 0 && accepted[d] % rule.every == 0;
        if (!queued && !rule.ack_uplinks) continue;

        MultiDownlink dl;
        dl.device = d;
        dl.gateway = static_cast<std::uint32_t>(m.best_gateway);
        dl.data = queued;
        dl.t_open_ns = ta.end + kRx1DelayNs;
        SimTime air = 0;
        const std::uint32_t payload = queued ? kDataFrameOverhead + rule.payload_bytes : kAckFrameBytes;
        if (downlink_airtime(ta.sf, payload, air) != SimStatus::Ok) return SimStatus::InvalidInput;

        if (next_start[a] >= 0 && next_start[a] < dl.t_open_ns + kRx1WindowNs) {
            dl.outcome = DownlinkOutcome::DeviceTransmitting;  // le dispositif émet pendant RX1
        } else {
            const std::size_t g = dl.gateway;
            const SimTime start = std::max(dl.t_open_ns, busy_until[g]);
            if (start - dl.t_open_ns >= kRx1WindowNs) {
                dl.outcome = DownlinkOutcome::GatewayBusy;  // la passerelle ne peut plus émettre à temps
            } else {
                dl.start_ns = start;
                dl.end_ns = start + air;
                busy[g].push_back(Interval{start, start + air});
                busy_until[g] = start + air;
                // Réciprocité : RSSI descendant = RSSI montant - P_dev + P_gw + G_dev.
                double s = 0.0;
                if (lora::receiver_sensitivity_dbm(ta.sf, lora::Bandwidth::Bw125kHz, s) !=
                    lora::Status::Ok) {
                    return SimStatus::InvalidInput;
                }
                const double rssi_dl = m.best_rssi_dbm - devices[d].tx_power_dbm +
                                       rule.gateway_tx_power_dbm + rule.device_antenna_gain_dbi;
                dl.outcome = rssi_dl >= s + rule.device_rx_offset_db ? DownlinkOutcome::Delivered
                                                                     : DownlinkOutcome::LostSensitivity;
            }
        }
        dls.push_back(dl);
    }

    if (trace != nullptr) {
        trace->reserve(T);
        for (std::size_t a = 0; a < T; ++a) trace->push_back(out[a]);
    }
    if (downlinks != nullptr) {
        // Ordre d'ouverture RX1 (ordre de fin = ordre d'ouverture, car RX1 = fin + 1 s).
        *downlinks = std::move(dls);
    }
    return SimStatus::Ok;
}

}  // namespace lsim::sim
