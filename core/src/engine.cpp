// SPDX-License-Identifier: Apache-2.0
#include "lsim/engine.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <map>
#include <numeric>
#include <optional>

#include "lsim/class_b.hpp"
#include "lsim/downlink_plan.hpp"
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
    std::uint32_t msg = 0;  // indice de l'émission : dispositifs dans l'ordre, puis k (multi)
};

bool overlap(const Tx& a, const Tx& b) {
    return a.start < b.end && b.start < a.end;
}

// Temps d'antenne réservés : table par émission (dispositif, rang) construite à partir du
// calendrier. Vide si aucune réservation : le temps d'antenne est alors constant par dispositif.
struct ReservedAirtime {
    std::vector<std::size_t> offset;    // premier indice de chaque dispositif dans `air`
    std::vector<SimTime> air;           // temps d'antenne par émission (dispositif, rang)
};

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
    if (!finite(g.rx_sensitivity_offset_db) || std::fabs(g.rx_sensitivity_offset_db) > 20.0) {
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
                           const std::vector<Interval>* gateway_busy,
                           const std::vector<MacReservation>* reservations,
                           const CausalDownlinks* causal) {
    totals = SimulationStats{};
    if (trace != nullptr) trace->clear();
    if (causal != nullptr && gateway_busy != nullptr) return SimStatus::InvalidInput;
    if (causal != nullptr && causal->radios.size() != device_count) return SimStatus::InvalidInput;
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
    auto transmitting_in = [](const std::vector<Interval>& v, SimTime start, SimTime end) {
        auto it = std::lower_bound(v.begin(), v.end(), start,
                                   [](const Interval& b, SimTime s) { return b.end <= s; });
        return it != v.end() && it->start < end;
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

    // Calendrier MAC : temps d'antenne par émission (dispositif, rang), octets réservés compris.
    ReservedAirtime reserved;
    const bool has_reservations = reservations != nullptr && !reservations->empty();
    if (has_reservations) {
        reserved.offset.assign(device_count + 1, 0);
        for (std::size_t i = 0; i < device_count; ++i) {
            reserved.offset[i + 1] = reserved.offset[i] + devices[i].messages;
        }
        std::vector<std::uint8_t> extra(reserved.offset[device_count], 0);
        for (const MacReservation& r : *reservations) {
            if (r.device >= device_count || r.rank < 1 || r.rank > devices[r.device].messages ||
                r.extra_bytes < 1 || r.extra_bytes > 15) {
                return SimStatus::InvalidInput;
            }
            std::uint8_t& slot = extra[reserved.offset[r.device] + r.rank - 1];
            if (slot != 0) {
                return SimStatus::InvalidInput;  // deux réservations pour une même émission
            }
            slot = static_cast<std::uint8_t>(r.extra_bytes);
        }
        reserved.air.assign(extra.size(), 0);
        for (std::size_t i = 0; i < device_count; ++i) {
            const EndDeviceSpec& d = devices[i];
            lora::RadioConfig rc;
            rc.spreading_factor = d.spreading_factor;
            rc.bandwidth = lora::Bandwidth::Bw125kHz;
            rc.coding_rate = 1;
            rc.low_data_rate_optimize = lora::low_data_rate_required(d.spreading_factor, rc.bandwidth);
            for (std::uint32_t k = 0; k < d.messages; ++k) {
                const std::size_t idx = reserved.offset[i] + k;
                if (extra[idx] == 0) {
                    reserved.air[idx] = airtime[i];
                    continue;
                }
                const std::uint32_t bytes = d.payload_bytes + extra[idx];
                if (bytes > 255) {
                    return SimStatus::InvalidInput;
                }
                const lora::AirtimeResult at = lora::time_on_air(rc, bytes);
                if (at.status != lora::Status::Ok) {
                    return SimStatus::InvalidInput;
                }
                reserved.air[idx] = at.nanoseconds;
            }
        }
    }
    const auto air_of = [&](std::size_t i, std::uint32_t k) -> SimTime {
        return has_reservations ? reserved.air[reserved.offset[i] + k] : airtime[i];
    };

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
            const SimTime air_k = air_of(i, k);
            SimTime t = static_cast<SimTime>(nominal_d);
            if (k > 0 && off_factor > 0.0) {
                const double earliest_d = static_cast<double>(prev_end) +
                                          std::round(static_cast<double>(air_k) * off_factor);
                if (earliest_d > kMaxHorizonNs) {
                    return SimStatus::InvalidInput;
                }
                t = std::max(t, static_cast<SimTime>(earliest_d));
            }
            if (!queue.push(t, kKindTxStart, static_cast<std::uint32_t>(i))) {
                return SimStatus::QueueFull;
            }
            prev_end = t + air_k;
            ++per_device[i].sent;
        }
    }

    // Extraction dans l'ordre temporel : les émissions sont triées par début.
    std::vector<Tx> txs;
    txs.reserve(static_cast<std::size_t>(total_tx));
    SimTime max_airtime = 0;
    // Les débuts d'un dispositif sont strictement croissants : le compteur par dispositif donne le
    // rang (k) de l'émission extraite.
    std::vector<std::uint32_t> popped(device_count, 0);
    Event ev;
    while (queue.pop(ev)) {
        if (ev.kind != kKindTxStart || ev.target >= device_count) {
            continue;
        }
        const std::uint32_t i = ev.target;
        const SimTime air = air_of(i, popped[i]++);
        Tx t;
        t.start = ev.time;
        t.end = ev.time + air;
        t.device = i;
        t.sf = devices[i].spreading_factor;
        t.rssi_dbm = rssi[i];
        max_airtime = std::max(max_airtime, air);
        per_device[i].airtime_ns += static_cast<std::uint64_t>(air);
        totals.airtime_ns += static_cast<std::uint64_t>(air);
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
    // Chemin causal (S1) : les trames sont évaluées par fin croissante. Une trame ne dépend que des
    // descentes planifiées pour des trames déjà terminées (une descente chevauchant [start, end)
    // commence au plus tôt à end' + RX1 avec end' < end), donc l'occupation passerelle est connue.
    std::vector<std::size_t> order(txs.size());
    std::iota(order.begin(), order.end(), std::size_t{0});
    std::optional<plan::DownlinkScheduler> scheduler;
    std::vector<Interval> planned;  // descentes planifiées (chemin causal), triées et disjointes
    if (causal != nullptr) {
        std::stable_sort(order.begin(), order.end(),
                         [&txs](std::size_t a, std::size_t b) { return txs[a].end < txs[b].end; });
        scheduler.emplace(causal->radios, causal->options);
        if (scheduler->status() != plan::PlanStatus::Ok) return SimStatus::InvalidInput;
    }
    std::vector<TxOutcome> outcomes(txs.size(), TxOutcome::LostSensitivity);
    for (std::size_t k = 0; k < order.size(); ++k) {
        const std::size_t a = order[k];
        const Tx& ta = txs[a];
        DeviceStats& st = per_device[ta.device];
        TxOutcome outcome = TxOutcome::LostSensitivity;

        const bool on_air_gw = causal != nullptr ? transmitting_in(planned, ta.start, ta.end)
                                                 : transmitting_in(busy, ta.start, ta.end);
        if (ta.rssi_dbm < sensitivity[ta.device]) {
            ++st.lost_sensitivity;
            ++totals.lost_sensitivity;
        } else if (on_air_gw) {
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
        outcomes[a] = outcome;
        if (scheduler && outcome == TxOutcome::Received) {
            if (const std::optional<plan::Interval> iv = scheduler->on_received(ta.device, ta.end)) {
                planned.push_back(Interval{iv->start_ns, iv->end_ns});
            }
        }
    }
    if (scheduler && scheduler->status() != plan::PlanStatus::Ok) return SimStatus::InvalidInput;
    if (causal != nullptr && causal->busy_out != nullptr) {
        causal->busy_out->clear();
        for (const Interval& iv : planned) causal->busy_out->push_back(plan::Interval{iv.start, iv.end});
    }
    if (trace != nullptr) {
        trace->reserve(txs.size());
        for (std::size_t a = 0; a < txs.size(); ++a) {
            const Tx& ta = txs[a];
            trace->push_back(TxRecord{ta.device, ta.start, ta.end, ta.sf, ta.rssi_dbm, outcomes[a]});
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
                              const std::vector<double>& thresholds, std::size_t G,
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
            if (rssi[t.device * G + g] < thresholds[t.device * G + g]) continue;
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
                        std::vector<double>& thresholds, std::uint64_t& total_tx) {
    const env::Environment no_environment{};
    const env::Environment& envr = environment != nullptr ? *environment : no_environment;
    airtime.assign(device_count, 0);
    sensitivity.assign(device_count, 0.0);
    rssi.assign(device_count * G, 0.0);
    thresholds.assign(device_count * G, 0.0);
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

    // Seuil montant par couple (dispositif, passerelle) : sensibilité du dispositif + décalage.
    for (std::size_t i = 0; i < device_count; ++i) {
        for (std::size_t g = 0; g < G; ++g) {
            thresholds[i * G + g] = sensitivity[i] + gateways[g].rx_sensitivity_offset_db;
        }
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
    std::vector<double> thresholds;  // seuil montant par (dispositif, passerelle)
    std::uint64_t total_tx = 0;
    const SimStatus ls = prepare_links(devices, device_count, gateways, G, prop, environment,
                                       airtime, sensitivity, rssi, thresholds, total_tx);
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
    fill_gateway_load(txs, rssi, thresholds, G, per_gateway);

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
            if (r < thresholds[ta.device * G + g]) {
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

// Périodes d'émission d'une passerelle : début -> fin, disjointes. Un join-accept est placé plus
// tard dans le temps qu'un downlink de données créé après lui : une liste ordonnée par début
// permet d'insérer et de chercher un créneau libre sans supposer que les débuts croissent.
using BusyMap = std::map<SimTime, SimTime>;

// Vrai si [start, end) chevauche une période.
bool map_intersects(const BusyMap& m, SimTime start, SimTime end) {
    auto it = m.lower_bound(start);
    if (it != m.begin()) {
        auto prev = std::prev(it);
        if (prev->second > start) return true;
    }
    return it != m.end() && it->first < end;
}

// Premier instant >= t où [s, s + air) ne chevauche aucune période.
SimTime first_free(const BusyMap& m, SimTime t, SimTime air) {
    SimTime s = t;
    auto it = m.upper_bound(s);
    if (it != m.begin()) {
        auto prev = std::prev(it);
        if (prev->second > s) s = prev->second;
    }
    while (it != m.end() && it->first < s + air) {
        s = it->second;
        ++it;
    }
    return s;
}

constexpr std::uint32_t kAckFrameBytes = 12;      // MHDR, DevAddr, FCtrl, FCnt, MIC
constexpr std::uint32_t kDataFrameOverhead = 13;  // ACK + FPort
constexpr SimTime kRx1DelayNs = 1'000'000'000;
constexpr SimTime kJoinAcceptDelayNs = 5'000'000'000;  // JOIN_ACCEPT_DELAY1 (RP002 §2.3)
constexpr std::uint32_t kJoinAcceptBytes = 17;         // join-accept sans CFList
constexpr SimTime kRx1WindowNs = 1'000'000'000;

}  // namespace

SimStatus simulate_uplinks_multi_downlinks(
    const EndDeviceSpec* devices, std::size_t device_count, const GatewaySpec* gateways,
    std::size_t gateway_count, const PropagationSpec& prop, const MultiDownlinkRule& rule,
    DeviceStats* per_device, NetworkStats& totals, GatewayRxStats* per_gateway,
    const env::Environment* environment, std::vector<MultiTx>* trace,
    std::vector<MultiDownlink>* downlinks, const SimTime* dl_ready_ns) {
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
    std::vector<double> thresholds;  // seuil montant par (dispositif, passerelle)
    std::uint64_t total_tx = 0;
    const SimStatus ls = prepare_links(devices, device_count, gateways, G, prop, environment,
                                       airtime, sensitivity, rssi, thresholds, total_tx);
    if (ls != SimStatus::Ok) return ls;
    for (std::size_t i = 0; i < device_count; ++i) per_device[i] = DeviceStats{};

    // Émissions, triées par début (puis dispositif). Prochain début du même dispositif (-1 : aucun).
    std::vector<Tx> txs;
    txs.reserve(static_cast<std::size_t>(total_tx));
    SimTime max_airtime = 0;
    std::size_t msg_base = 0;
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
            tx.msg = static_cast<std::uint32_t>(msg_base + k);
            txs.push_back(tx);
            prev_end = tx.end;
            ++per_device[i].sent;
            ++totals.sent;
            per_device[i].airtime_ns += static_cast<std::uint64_t>(airtime[i]);
            totals.airtime_ns += static_cast<std::uint64_t>(airtime[i]);
            max_airtime = std::max(max_airtime, airtime[i]);
        }
        msg_base += d.messages;
    }
    std::stable_sort(txs.begin(), txs.end(), [](const Tx& a, const Tx& b) {
        if (a.start != b.start) return a.start < b.start;
        return a.device < b.device;
    });
    fill_gateway_load(txs, rssi, thresholds, G, per_gateway);
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
            if (r < thresholds[ta.device * G + g]) {
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
    std::vector<BusyMap> busy(G);
    std::vector<std::uint32_t> accepted(device_count, 0);
    // Instant de réception du join-accept (fin de sa transmission) ; kNever tant que non reçu.
    constexpr SimTime kNever = std::numeric_limits<SimTime>::max();
    std::vector<SimTime> joined_at(device_count, kNever);
    std::vector<MultiTx> out(T);
    std::vector<MultiDownlink> dls;

    // Place un downlink de `a` (RX1 à dl.t_open_ns) sur sa passerelle, ou le marque perdu.
    // Première place libre à partir de t_open : un join-accept (ouverture tardive) ne retarde
    // pas un downlink de données dont l'ouverture est plus tôt.
    // Repli RX2 : si la passerelle ne peut émettre dans la fenêtre RX1, la descente tente RX2
    // (ouverte 1 s après RX1, fenêtre de 1 s, SF `rule.rx2_sf`, même passerelle). Une émission
    // du dispositif pendant RX2 est une perte finale. Fréquence RX2 non modélisée.
    auto place = [&](MultiDownlink& dl, std::size_t a, std::uint32_t payload,
                     double rssi_up) -> SimStatus {
        const Tx& ta = txs[a];
        SimTime air = 0;
        if (downlink_airtime(ta.sf, payload, air) != SimStatus::Ok) return SimStatus::InvalidInput;
        std::uint8_t sf_used = ta.sf;
        // Départ au plus tôt : arrivée de la descente à la passerelle (retour mesh). Absent : t_open.
        const SimTime ready = dl_ready_ns != nullptr ? dl_ready_ns[ta.msg] : -1;
        if (ready == kDownlinkNever) {
            dl.outcome = DownlinkOutcome::GatewayBusy;  // jamais acheminée (perdue sur le mesh)
            return SimStatus::Ok;
        }
        if (next_start[a] >= 0 && next_start[a] < dl.t_open_ns + kRx1WindowNs) {
            dl.outcome = DownlinkOutcome::DeviceTransmitting;  // le dispositif émet pendant RX1
            return SimStatus::Ok;
        }
        const std::size_t g = dl.gateway;
        SimTime start = first_free(busy[g], std::max(dl.t_open_ns, ready), air);
        if (start - dl.t_open_ns >= kRx1WindowNs) {
            // La passerelle ne peut émettre dans RX1 : repli sur RX2, sinon perte.
            const SimTime open2 = dl.t_open_ns + kRx1WindowNs;
            if (rule.rx2_sf == 0) {
                dl.outcome = DownlinkOutcome::GatewayBusy;
                return SimStatus::Ok;
            }
            SimTime air2 = 0;
            if (downlink_airtime(rule.rx2_sf, payload, air2) != SimStatus::Ok) {
                return SimStatus::InvalidInput;
            }
            if (next_start[a] >= 0 && next_start[a] < open2 + kRx1WindowNs) {
                dl.outcome = DownlinkOutcome::DeviceTransmitting;  // le dispositif émet pendant RX2
                return SimStatus::Ok;
            }
            start = first_free(busy[g], std::max(open2, ready), air2);
            if (start - open2 >= kRx1WindowNs) {
                dl.outcome = DownlinkOutcome::GatewayBusy;  // ni RX1 ni RX2 : perte
                return SimStatus::Ok;
            }
            air = air2;
            sf_used = rule.rx2_sf;
            dl.rx_window = 2;
        }
        dl.start_ns = start;
        dl.end_ns = start + air;
        busy[g][start] = start + air;
        // Réciprocité : RSSI descendant = RSSI montant - P_dev + P_gw + G_dev.
        double s = 0.0;
        if (lora::receiver_sensitivity_dbm(sf_used, lora::Bandwidth::Bw125kHz, s) != lora::Status::Ok) {
            return SimStatus::InvalidInput;
        }
        const double rssi_dl = rssi_up - devices[ta.device].tx_power_dbm +
                               rule.gateway_tx_power_dbm + rule.device_antenna_gain_dbi;
        dl.outcome = rssi_dl >= s + rule.device_rx_offset_db ? DownlinkOutcome::Delivered
                                                             : DownlinkOutcome::LostSensitivity;
        return SimStatus::Ok;
    };

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
            if (map_intersects(busy[g], ta.start, ta.end)) {
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
        // Une trame démarrée avant la réception du join-accept est une join-request.
        m.join_request = rule.join && !(joined_at[d] != kNever && ta.start >= joined_at[d]);
        out[a] = m;

        if (receivers == 0) continue;
        const std::uint32_t gw = static_cast<std::uint32_t>(m.best_gateway);

        if (m.join_request) {
            // Join-request décodée : join-accept à fin + 5 s par la meilleure passerelle.
            // Le dispositif est jointé seulement si le join-accept lui parvient.
            MultiDownlink dl;
            dl.device = d;
            dl.gateway = gw;
            dl.join = true;
            dl.t_open_ns = ta.end + kJoinAcceptDelayNs;
            if (place(dl, a, kJoinAcceptBytes, m.best_rssi_dbm) != SimStatus::Ok) {
                return SimStatus::InvalidInput;
            }
            if (dl.outcome == DownlinkOutcome::Delivered &&
                (joined_at[d] == kNever || dl.end_ns < joined_at[d])) {
                joined_at[d] = dl.end_ns;  // premier join-accept reçu
            }
            dls.push_back(dl);
            continue;
        }

        ++accepted[d];
        const bool queued = rule.every > 0 && accepted[d] % rule.every == 0;
        if (!queued && !rule.ack_uplinks) continue;

        MultiDownlink dl;
        dl.device = d;
        dl.gateway = gw;
        dl.data = queued;
        dl.t_open_ns = ta.end + kRx1DelayNs;
        const std::uint32_t payload = queued ? kDataFrameOverhead + rule.payload_bytes : kAckFrameBytes;
        if (place(dl, a, payload, m.best_rssi_dbm) != SimStatus::Ok) return SimStatus::InvalidInput;
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
