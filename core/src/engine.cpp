// SPDX-License-Identifier: Apache-2.0
#include "lsim/engine.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <map>
#include <numeric>
#include <optional>
#include <queue>

#include "lsim/adr.hpp"
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
    std::uint32_t rank = 0; // rang 1-based de l'émission dans son dispositif (boucle fermée)
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
    if (d.spreading_factor < 5 || d.spreading_factor > 12 || d.spreading_factor == 6) {
        return SimStatus::InvalidInput;  // SF6 : en-tête implicite seulement, modèle non fourni
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

// Seuil absolu d'une paire SF/bande documentée dans le profil ; sinon InvalidInput.
SimStatus absolute_gateway_dbm(const GatewayAbsoluteSensitivity& a, std::uint8_t sf,
                               lora::Bandwidth bw, double& out) {
    std::size_t b = 0;
    switch (bw) {
        case lora::Bandwidth::Bw125kHz: b = 0; break;
        case lora::Bandwidth::Bw250kHz: b = 1; break;
        case lora::Bandwidth::Bw500kHz: b = 2; break;
        default: return SimStatus::InvalidInput;
    }
    if (sf < 5 || sf > 12) return SimStatus::InvalidInput;
    const std::uint32_t bit = static_cast<std::uint32_t>(b * 8 + (sf - 5));
    if (((a.present >> bit) & 1U) == 0U) return SimStatus::InvalidInput;
    out = a.dbm[b][sf - 5];
    return SimStatus::Ok;
}

SimStatus validate_inputs(const GatewaySpec& g, const PropagationSpec& p) {
    if (!finite(g.position.x_m) || !finite(g.position.y_m) || !finite(g.antenna_gain_dbi)) {
        return SimStatus::InvalidInput;
    }
    if (!finite(g.rx_sensitivity_offset_db) || std::fabs(g.rx_sensitivity_offset_db) > 20.0) {
        return SimStatus::InvalidInput;
    }
    if (g.absolute.enabled) {
        if (g.rx_sensitivity_offset_db != 0.0) return SimStatus::InvalidInput;  // pas de conversion
        if ((g.absolute.present >> 24U) != 0U) return SimStatus::InvalidInput;   // 3 x 8 bits
        for (std::size_t b = 0; b < 3; ++b) {
            for (std::size_t k = 0; k < 8; ++k) {
                if (((g.absolute.present >> (b * 8 + k)) & 1U) == 0U) continue;
                const double v = g.absolute.dbm[b][k];
                if (!finite(v) || v < -160.0 || v > -60.0) return SimStatus::InvalidInput;
            }
        }
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
        if (gateway.absolute.enabled) {
            if (absolute_gateway_dbm(gateway.absolute, d.spreading_factor, rc.bandwidth, s) !=
                SimStatus::Ok) {
                return SimStatus::InvalidInput;
            }
        } else if (lora::receiver_sensitivity_dbm(d.spreading_factor, rc.bandwidth, s) !=
                   lora::Status::Ok) {
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
    // Modèle absolu non supporté en multi-passerelle (refus explicite, pas de déduction).
    for (std::size_t g = 0; g < gateway_count; ++g) {
        if (gateways[g].absolute.enabled) return SimStatus::InvalidInput;
    }
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

// ---------------------------------------------------------------- Boucle fermée (S2)

namespace {

constexpr double kNoiseFloorDbmBw125 = -117.0;  // -174 + 10 log10(125 kHz) + NF 6 dB
constexpr double kMaxLoopSnrDb = 50.0;          // bornes du cœur ADR : -500..500 dixièmes de dB
constexpr std::size_t kLoopHistory = lorawan::adr::kMaxSamples;
constexpr SimTime kLoopRxDelayNs = 1'000'000'000;   // RECEIVE_DELAY1
constexpr SimTime kLoopRx1WindowNs = 1'000'000'000;
constexpr SimTime kLoopRx2DelayNs = 2'000'000'000;   // RECEIVE_DELAY2 (TS001 §3.3.3)
constexpr SimTime kLoopRx2WindowNs = 1'000'000'000;  // durée de RX2 (égale à RX1, §3.3.4)
// SF de RX2 par défaut en EU868 (RP002-1.0.3 : SF12, 125 kHz, DR0). RP002-1.0.5 non vérifié.
constexpr std::uint8_t kLoopRx2Sf = 12;
constexpr std::uint32_t kLoopAdrAckLimit = 64;   // ADR_ACK_LIMIT (RP002-1.0.5 §3.3)
constexpr std::uint32_t kLoopAdrAckDelay = 32;   // ADR_ACK_DELAY (RP002-1.0.5 §3.3)
// RP002-1.0.5 Table 12 (EU863-870, « data rate back-off ») : DRnext pendant le repli de débit ADR,
// indexé par DRcurrent. Table propre à EU868 : le moteur n'a pas d'identifiant de région.
constexpr std::array<std::uint8_t, 14> kLoopDrBackOffEu868 = {0, 0, 1, 2, 3, 4, 5, 6, 0, 8, 0, 10, 5, 12};
constexpr std::uint32_t kLoopAckBytes = 12;         // MHDR, DevAddr, FCtrl, FCnt, MIC
constexpr std::uint32_t kLoopDataOverheadBytes = 13;
constexpr std::uint8_t kLoopIgnoreField = 15;       // LinkADRReq : champ « ignorer »
constexpr int kLoopRankCheck = 0;                   // fermeture RX1 et application : avant les émissions
constexpr int kLoopRankStart = 1;
constexpr int kLoopRankEnd = 2;

enum class LoopKind : std::uint8_t { Check, Apply, Start, End };

struct LoopEvent {
    SimTime t = 0;
    int rank = kLoopRankStart;
    std::uint64_t seq = 0;
    LoopKind kind = LoopKind::Start;
    std::uint32_t device = 0;   // Start
    std::uint32_t index = 0;    // End : indice d'émission ; Check, Apply : indice de descente
    std::uint8_t cmd = 0;       // Apply : kLoopCmdLinkAdr ou kLoopCmdDutyCycle
};

struct LoopLater {
    bool operator()(const LoopEvent& a, const LoopEvent& b) const {
        if (a.t != b.t) return a.t > b.t;
        if (a.rank != b.rank) return a.rank > b.rank;
        return a.seq > b.seq;
    }
};

// État d'un dispositif (côté équipement).
struct LoopDevice {
    std::uint8_t sf = 7;
    std::int8_t dr = -1;
    std::uint8_t power_index = 0;
    double cap = 1.0;              // plafond appliqué par DutyCycleReq (1 : aucun)
    std::uint32_t next_k = 0;      // rang de la prochaine émission
    SimTime prev_end = 0;
    SimTime prev_air = 0;          // airtime de l'émission terminée (repos après elle)
    bool has_prev = false;
    std::int64_t last_tx = -1;     // indice de la dernière émission démarrée
    std::uint8_t answer_mask = 0;  // réponses MAC à porter dans la prochaine émission
    std::uint8_t answer_ok = 0;
    bool ds_pending = false;       // DevStatusReq reçue : DevStatusAns dans la prochaine émission
    std::uint32_t adr_cnt = 0;     // ADRACKCnt : uplinks depuis la dernière descente reçue (TS001 §4.3.1.1)
    LoopChannelState channels;     // capacités et canaux actifs du terminal (modèle canaux)
    std::uint8_t answer_status = 0xFF;  // LinkADRAns (bits CM, DR, PW) de la prochaine émission ; 0xFF : aucun
};

// État du serveur pour un dispositif : état confirmé et commandes en attente.
// Commande ponctuelle en file (LinkCheckAns, DeviceTimeAns, DevStatusReq) : une réponse ou une
// requête n'est pas retransmise, elle attend seulement une descente où elle tient (FIFO).
struct LoopQueued {
    std::uint8_t cmd = 0;        // kLoopCmdLinkCheck, kLoopCmdDeviceTime ou kLoopCmdDevStatus
    std::uint8_t bytes = 0;      // taille en FOpts
    std::uint8_t deferrals = 0;  // reports subis
    std::uint32_t id = 0;        // indice dans LoopResult::mac_items
};

struct LoopServer {
    std::vector<LoopQueued> queue;   // commandes ponctuelles en attente, dans l'ordre d'arrivée
    std::vector<std::int32_t> snr;   // dixièmes de dB, 20 au plus
    std::uint8_t dr = 0;
    std::uint8_t power_index = 0;
    bool adr_pending = false;
    std::uint8_t pend_dr = 0;
    std::uint8_t pend_power = 0;
    std::uint16_t refused_dr = 0;    // bit n : débit n refusé par le dispositif (réponse négative)
    std::uint16_t refused_pi = 0;    // bit n : index de puissance n refusé
    LoopChannelSet view;             // canaux que le serveur configure (sa vue, pas celle du terminal)
    std::uint8_t duty_state = 0;     // 0 : rien à faire ; 1 : DutyCycleReq en attente ; 2 : acquittée
    std::uint64_t accepted = 0;      // uplinks reçus
};

// Temps d'antenne d'un uplink à 125 kHz (CR 4/5, en-tête explicite), en ns.
bool uplink_airtime(std::uint8_t sf, std::uint32_t bytes, SimTime& out) {
    lora::RadioConfig rc;
    rc.spreading_factor = sf;
    rc.bandwidth = lora::Bandwidth::Bw125kHz;
    rc.coding_rate = 1;
    rc.low_data_rate_optimize = lora::low_data_rate_required(sf, rc.bandwidth);
    const lora::AirtimeResult at = lora::time_on_air(rc, bytes);
    if (at.status != lora::Status::Ok) return false;
    out = at.nanoseconds;
    return true;
}

// Octets MAC portés par un uplink : LinkADRAns (2), DutyCycleAns (1).
std::uint32_t answer_octets(std::uint8_t mask) {
    return static_cast<std::uint32_t>(((mask & 1U) != 0 ? 2U : 0U) + ((mask & 2U) != 0 ? 1U : 0U));
}

}  // namespace

SimStatus simulate_closed_loop(const EndDeviceSpec* devices, std::size_t device_count,
                               const plan::DeviceRadio* radios, const LoopRegion* regions,
                               const GatewaySpec& gateway, const PropagationSpec& prop,
                               const env::Environment* environment, const LoopOptions& options,
                               DeviceStats* per_device, SimulationStats& totals, LoopResult& out) {
    LoopChannelIo io;  // configuration par défaut, sorties ignorées
    return simulate_closed_loop_channels(devices, device_count, radios, regions, gateway, prop,
                                         environment, options, per_device, totals, out, io);
}

SimStatus simulate_closed_loop_channels(const EndDeviceSpec* devices, std::size_t device_count,
                                        const plan::DeviceRadio* radios, const LoopRegion* regions,
                                        const GatewaySpec& gateway, const PropagationSpec& prop,
                                        const env::Environment* environment, const LoopOptions& options,
                                        DeviceStats* per_device, SimulationStats& totals, LoopResult& out,
                                        LoopChannelIo& io) {
    totals = SimulationStats{};
    out = LoopResult{};
    {
        const LoopChannelConfig* cfg = io.config;  // entrées conservées, sorties remises à zéro
        const std::size_t cfg_count = io.config_count;
        io = LoopChannelIo{};
        io.config = cfg;
        io.config_count = cfg_count;
    }
    if (device_count > kMaxEndDevices) return SimStatus::TooManyDevices;
    if (device_count > 0 && (devices == nullptr || per_device == nullptr || radios == nullptr)) {
        return SimStatus::InvalidInput;
    }
    if (device_count > 0 && regions == nullptr) return SimStatus::InvalidInput;
    if (io.config != nullptr) {
        if (io.config_count != device_count) return SimStatus::InvalidInput;
        for (std::size_t i = 0; i < device_count; ++i) {
            const LoopChannelConfig& cfg = io.config[i];
            // Vue serveur : non vide, bloc 0 seulement (ChMaskCntl 0, canaux 0..15).
            if (!cfg.server_view.any() || cfg.server_view.words[1] != 0 || (cfg.server_view.words[0] >> 16) != 0) {
                return SimStatus::InvalidInput;
            }
            // Un canal actif doit être défini côté terminal.
            for (std::size_t c = 0; c < kLoopMaxChannels; ++c) {
                if (cfg.device.enabled.test(c) && !cfg.device.defined(c)) return SimStatus::InvalidInput;
            }
        }
    }
    const SimStatus gs = validate_inputs(gateway, prop);
    if (gs != SimStatus::Ok) return gs;
    const env::Environment no_environment{};
    const env::Environment& envr = environment != nullptr ? *environment : no_environment;
    if (environment != nullptr) {
        if (env::validate_environment(envr) != env::EnvStatus::Ok) return SimStatus::InvalidEnvironment;
        const std::uint64_t checks = static_cast<std::uint64_t>(device_count) * envr.obstacle_count;
        if (checks > env::kMaxObstacleChecks) return SimStatus::EnvironmentWorkLimit;
    }
    if (options.duty_cycle && options.duty_cycle_exponent > 15) return SimStatus::InvalidInput;
    if (options.installation_margin_tenth_db < -300 || options.installation_margin_tenth_db > 300) {
        return SimStatus::InvalidInput;
    }
    {
        const std::vector<plan::DeviceRadio> rv(radios, radios + device_count);
        if (plan::DownlinkScheduler(rv, options.protocol).status() != plan::PlanStatus::Ok) {
            return SimStatus::InvalidInput;
        }
    }

    const std::size_t n = device_count;
    std::vector<LoopDevice> dev(n);
    std::vector<LoopServer> srv(n);
    std::vector<double> path_loss(n), shadow(n), step_db(n, 0.0);
    std::uint64_t total_tx = 0;
    radio::LogDistanceModel model;
    model.frequency_hz = prop.frequency_hz;
    model.reference_distance_m = prop.reference_distance_m;
    model.exponent = prop.exponent;
    for (std::size_t i = 0; i < n; ++i) {
        const EndDeviceSpec& d = devices[i];
        if (validate_device(d) != SimStatus::Ok) return SimStatus::InvalidInput;
        if (d.downlink.count > 0) return SimStatus::InvalidInput;  // descentes de l'API v1 : hors boucle
        per_device[i] = DeviceStats{};
        per_device[i].sent = d.messages;
        dev[i].sf = d.spreading_factor;
        dev[i].channels = io.config != nullptr ? io.config[i].device : loop_eu868_default_channels();
        srv[i].view = io.config != nullptr ? io.config[i].server_view : loop_eu868_plan().defaults;
        {
            const LoopRegion& rg = regions[i];
            if (rg.max_dr > 15 || rg.max_tx_power_index > 15 || rg.power_step_tenth_db < 1 ||
                rg.power_step_tenth_db > 100 || !(rg.max_eirp_dbm > -200.0)) {
                return SimStatus::InvalidInput;
            }
            for (std::uint8_t k = 0; k <= rg.max_tx_power_index; ++k) {
                if (!(rg.duty_limit[k] > 0.0 && rg.duty_limit[k] <= 1.0)) return SimStatus::InvalidInput;
            }
            step_db[i] = rg.power_step_tenth_db / 10.0;
        }
        if (options.adr) {
            const LoopRegion& rg = regions[i];
            int found = -1;
            for (std::uint8_t j = 0; j <= rg.max_dr; ++j) {
                if (rg.dr_sf[j] == d.spreading_factor) {
                    found = j;
                    break;
                }
            }
            if (found < 0) return SimStatus::InvalidInput;  // SF du dispositif absent de la table
            dev[i].dr = static_cast<std::int8_t>(found);
            srv[i].dr = static_cast<std::uint8_t>(found);
        }
        // Gain de liaison : même calcul que `simulate_uplinks` (ordre des opérations conservé).
        const double dx = d.position.x_m - gateway.position.x_m;
        const double dy = d.position.y_m - gateway.position.y_m;
        const double dist = std::max(std::hypot(dx, dy), prop.reference_distance_m);
        if (environment != nullptr) {
            env::PathLoss pl{};
            if (env::path_loss_db(model, d.position.x_m, d.position.y_m, gateway.position.x_m,
                                  gateway.position.y_m, envr, pl) != env::EnvStatus::Ok) {
                return SimStatus::InvalidEnvironment;
            }
            path_loss[i] = pl.total_db;
        } else {
            const radio::BudgetResult pl = radio::log_distance_path_loss_db(model, dist);
            if (pl.status != lora::Status::Ok) return SimStatus::InvalidInput;
            path_loss[i] = pl.value;
        }
        shadow[i] = shadowing_sample_db(prop.shadowing_seed, static_cast<std::uint32_t>(i),
                                        prop.shadowing_sigma_db);
        total_tx += d.messages;
        if (total_tx > kMaxTransmissions) return SimStatus::TooManyTransmissions;
    }
    // Sensibilité par SF (125 kHz), et borne du temps d'antenne (recherche arrière).
    double sensitivity_by_sf[13] = {};
    bool sf_documented[13] = {};
    for (std::uint8_t sf = 5; sf <= 12; ++sf) {
        if (gateway.absolute.enabled) {
            sf_documented[sf] = absolute_gateway_dbm(gateway.absolute, sf, lora::Bandwidth::Bw125kHz,
                                                     sensitivity_by_sf[sf]) == SimStatus::Ok;
        } else if (sf >= 7) {
            if (lora::receiver_sensitivity_dbm(sf, lora::Bandwidth::Bw125kHz, sensitivity_by_sf[sf]) !=
                lora::Status::Ok) {
                return SimStatus::InvalidInput;
            }
            sf_documented[sf] = true;
        }
    }
    for (std::size_t k = 0; k < device_count; ++k) {
        if (!sf_documented[devices[k].spreading_factor]) return SimStatus::InvalidInput;
    }
    SimTime max_airtime = 0;
    if (!uplink_airtime(12, 255, max_airtime)) return SimStatus::InvalidInput;

    // Puissance de l'index : plafond du plan (index 0) moins le pas du plan pour chaque index.
    const auto tx_dbm = [&](std::size_t i, std::uint8_t power_index) {
        const double p0 = std::min(devices[i].tx_power_dbm, regions[i].max_eirp_dbm);
        return p0 - static_cast<double>(power_index) * step_db[i];
    };
    const auto rssi_of = [&](std::size_t i, std::uint8_t power_index) {
        return tx_dbm(i, power_index) + gateway.antenna_gain_dbi - path_loss[i] - shadow[i];
    };
    // Instant de début de la k-ième émission nominale ; false si hors horizon.
    const auto nominal = [&](std::size_t i, std::uint32_t k, SimTime& out_t) {
        const double d = static_cast<double>(devices[i].start_offset_ns) +
                         static_cast<double>(k) * static_cast<double>(devices[i].period_ns);
        if (d > kMaxHorizonNs) return false;
        out_t = static_cast<SimTime>(d);
        return true;
    };

    std::priority_queue<LoopEvent, std::vector<LoopEvent>, LoopLater> q;
    std::uint64_t seq = 0;
    SimStatus status = SimStatus::Ok;
    for (std::size_t i = 0; i < n; ++i) {
        if (devices[i].messages == 0) continue;
        SimTime t0 = 0;
        if (!nominal(i, 0, t0)) return SimStatus::InvalidInput;
        q.push(LoopEvent{t0, kLoopRankStart, seq++, LoopKind::Start, static_cast<std::uint32_t>(i), 0, 0});
    }

    // Calendrier MAC : octets réservés et commandes portées, par émission (dispositif, rang).
    std::vector<std::size_t> mac_off(n + 1, 0);
    for (std::size_t i = 0; i < n; ++i) mac_off[i + 1] = mac_off[i] + devices[i].messages;
    std::vector<std::uint8_t> mac_extra(mac_off[n], 0);
    std::vector<std::uint8_t> mac_flags(mac_off[n], 0);
    if (options.mac_count > 0 && options.mac == nullptr) return SimStatus::InvalidInput;
    {
        std::vector<std::uint8_t> seen(mac_off[n], 0);
        for (std::size_t m = 0; m < options.mac_count; ++m) {
            const LoopMacSlot& s = options.mac[m];
            if (s.device >= n || s.rank < 1 || s.rank > devices[s.device].messages ||
                s.extra_bytes > 15 || (s.flags & ~kLoopMacAll) != 0) {
                return SimStatus::InvalidInput;
            }
            const std::size_t idx = mac_off[s.device] + s.rank - 1;
            if (seen[idx] != 0) return SimStatus::InvalidInput;  // deux entrées pour une émission
            seen[idx] = 1;
            mac_extra[idx] = s.extra_bytes;
            mac_flags[idx] = s.flags;
        }
    }

    // Émissions (dans l'ordre des débuts), issues et réponses MAC portées.
    std::vector<Tx> txs;
    std::vector<TxOutcome> outcome;
    std::vector<std::uint8_t> powers, masks, oks, sts;
    std::vector<LoopLinkAdrRequest> dl_requests;  // parallèle à `dls`
    std::vector<LoopLinkAdrDiagnosis> dl_diag;    // diagnostic à l'application (descentes reçues)
    std::vector<std::uint8_t> adr_reqs;  // ADRACKReq porté par l'émission (F14)
    std::vector<std::int8_t> drs;
    std::vector<std::int64_t> next_tx;  // émission suivante du même dispositif, -1 si aucune
    std::vector<Interval> busy;         // émissions passerelle planifiées (croissantes, disjointes)
    std::vector<LoopDownlink>& dls = out.downlinks;
    const auto transmitting = [&busy](SimTime start, SimTime end) {
        auto it = std::lower_bound(busy.begin(), busy.end(), start,
                                   [](const Interval& b, SimTime s) { return b.end <= s; });
        return it != busy.end() && it->start < end;
    };

    // Traitement d'un uplink reçu : réponses MAC, décision ADR, descente.
    LoopMacQueueStats qs;
    std::vector<std::vector<std::uint32_t>> dl_items;  // commandes de la file par descente
    const auto on_received = [&](std::size_t a) -> void {
        const Tx& ta = txs[a];
        const std::uint32_t d = ta.device;
        LoopServer& sv = srv[d];
        const std::uint8_t mask = masks[a];
        const std::uint8_t st = sts[a];
        // Réponses : confirmées seulement parce que cet uplink est reçu.
        if ((mask & 1U) != 0 && sv.adr_pending) {
            if (st == 0x07) {
                sv.dr = sv.pend_dr;
                sv.power_index = sv.pend_power;
            } else {
                // Réponse négative (TS001 §5.2 : un bit à 0 = échec, état précédent conservé) :
                // l'élément refusé n'est pas renvoyé ; la décision suivante l'exclut.
                // Bit 1 (DataRateACK) à 0 : débit exclu. Bit 2 (PowerACK) à 0 : puissance exclue.
                // Bit 0 (ChannelMaskACK) à 0 : aucune exclusion avant l'étape 4 (réévaluation).
                if ((st & 2U) == 0) sv.refused_dr = static_cast<std::uint16_t>(sv.refused_dr | (1U << sv.pend_dr));
                if ((st & 4U) == 0) sv.refused_pi = static_cast<std::uint16_t>(sv.refused_pi | (1U << sv.pend_power));
            }
            sv.adr_pending = false;
        }
        if ((mask & 2U) != 0 && sv.duty_state == 1) sv.duty_state = 2;

        if (options.adr) {
            const LoopRegion& rg = regions[d];
            const double snr = std::clamp(ta.rssi_dbm - kNoiseFloorDbmBw125, -kMaxLoopSnrDb, kMaxLoopSnrDb);
            sv.snr.push_back(static_cast<std::int32_t>(std::lround(snr * 10.0)));
            if (sv.snr.size() > kLoopHistory) sv.snr.erase(sv.snr.begin());
            if (sv.snr.size() == kLoopHistory && !sv.adr_pending) {
                lorawan::adr::Input in{};
                for (std::size_t k = 0; k < sv.snr.size(); ++k) in.snr_tenth_db[k] = sv.snr[k];
                in.n_samples = sv.snr.size();
                in.dr = sv.dr;
                in.dr_sf = rg.dr_sf;
                in.min_dr = 0;
                in.max_dr = rg.max_dr;
                in.tx_power_index = sv.power_index;
                in.max_tx_power_index = rg.max_tx_power_index;
                in.power_step_tenth_db = rg.power_step_tenth_db;
                in.installation_margin_tenth_db = options.installation_margin_tenth_db;
                lorawan::adr::Output o{};
                if (lorawan::adr::decide(in, o) != lorawan::adr::AdrStatus::Ok) {
                    status = SimStatus::InvalidInput;
                    return;
                }
                // Valeurs refusées exclues : on garde l'état courant pour cet élément.
                std::uint8_t want_dr = o.dr;
                std::uint8_t want_pi = o.tx_power_index;
                if (((sv.refused_dr >> want_dr) & 1U) != 0) want_dr = sv.dr;
                if (((sv.refused_pi >> want_pi) & 1U) != 0) want_pi = sv.power_index;
                if (want_dr != sv.dr || want_pi != sv.power_index) {
                    sv.adr_pending = true;
                    sv.pend_dr = want_dr;
                    sv.pend_power = want_pi;
                }
            }
        }
        if (options.duty_cycle && sv.duty_state == 0) sv.duty_state = 1;

        ++sv.accepted;
        const bool queued = options.protocol.downlink_every > 0 &&
                            sv.accepted % options.protocol.downlink_every == 0;
        std::uint8_t kind = 0;  // 1 ACK, 2 donnée, 3 MAC seul
        if (queued) {
            kind = 2;
        } else if (options.protocol.confirmed_uplinks) {
            kind = 1;
        }
        // Commandes à état (LinkADR, DutyCycle) : toujours offertes tant qu'elles ne sont pas
        // acquittées. Elles passent en premier, dans le budget de 15 octets de FOpts.
        std::uint8_t cmds = 0;
        std::uint32_t budget = kLoopFoptsMax;
        if (sv.adr_pending) {
            cmds |= kLoopCmdLinkAdr;
            budget -= 5;
        }
        if (options.duty_cycle && sv.duty_state == 1) {
            cmds |= kLoopCmdDutyCycle;
            budget -= 2;
        }
        // Commandes ponctuelles du calendrier pour cet uplink (rang 1-based), mises en file.
        const std::uint8_t mf = mac_flags[mac_off[d] + ta.rank - 1];
        const auto enqueue = [&](std::uint8_t cmd, std::uint8_t bytes) {
            const auto id = static_cast<std::uint32_t>(out.mac_items.size());
            out.mac_items.push_back(LoopMacItem{d, cmd, static_cast<std::uint32_t>(a), 0,
                                                LoopMacState::Queued, -1});
            sv.queue.push_back(LoopQueued{cmd, bytes, 0, id});
            ++qs.enqueued;
        };
        if ((mf & kLoopMacLinkCheck) != 0) enqueue(kLoopCmdLinkCheck, 3);
        if ((mf & kLoopMacDeviceTime) != 0) enqueue(kLoopCmdDeviceTime, 6);
        if ((mf & kLoopMacDevStatus) != 0) enqueue(kLoopCmdDevStatus, 1);
        // Ordre de service : les commandes les plus reportées d'abord, puis ordre d'arrivée
        // (tri stable). Une commande qui tient part dans cette descente ; sinon elle est reportée,
        // et expire après `mac_max_deferrals` reports. Rien ne se tronque.
        std::stable_sort(sv.queue.begin(), sv.queue.end(),
                         [](const LoopQueued& x, const LoopQueued& y) { return x.deferrals > y.deferrals; });
        std::uint8_t carried = 0;
        std::vector<std::uint32_t> carried_ids;
        const auto is_answer = [](std::uint8_t cmd) {
            return cmd == kLoopCmdLinkCheck || cmd == kLoopCmdDeviceTime;
        };
        for (auto it = sv.queue.begin(); it != sv.queue.end();) {
            LoopMacItem& mi = out.mac_items[it->id];
            if (it->bytes <= budget) {
                budget -= it->bytes;
                cmds |= it->cmd;
                ++carried;
                carried_ids.push_back(it->id);
                ++qs.dispatched;
                mi.state = LoopMacState::Dispatched;
                mi.downlink = static_cast<std::int64_t>(dls.size());  // la descente est ajoutée plus bas
                it = sv.queue.erase(it);
            } else {
                ++qs.deferred;
                ++it->deferrals;
                mi.deferrals = it->deferrals;
                // TS001 §5 : une réponse à une requête du dispositif (LinkCheckAns, DeviceTimeAns)
                // n'est envoyée que dans les fenêtres RX qui suivent cette requête ; elle n'est
                // jamais reportée. Une réponse qui ne tient pas dans sa descente expire aussitôt.
                if (it->deferrals > options.mac_max_deferrals || is_answer(it->cmd)) {
                    ++qs.expired;
                    mi.state = LoopMacState::Expired;
                    it = sv.queue.erase(it);
                } else {
                    ++it;
                }
            }
        }
        if (adr_reqs[a] != 0 && kind == 0) kind = 3;  // F14 : ADRACKReq, descente obligatoire
        if (kind == 0 && cmds == 0) return;
        if (kind == 0) kind = 3;
        const std::uint32_t fopts = kLoopFoptsMax - budget;
        const std::uint32_t base = kind == 2 ? kLoopDataOverheadBytes + options.protocol.downlink_payload_bytes
                                             : kLoopAckBytes;
        plan::DeviceRadio rad = radios[d];
        // Fenêtre : RX1 (fin + 1 s, débit montant, RX1DROffset 0) ; si la passerelle ne peut pas
        // émettre dans RX1, repli sur RX2 (fin + 2 s, SF kLoopRx2Sf). TS001 §3.3.1 et §3.3.3.
        // TS001 §3.3.5 : la descente débute exactement à l'ouverture de la fenêtre, sans décalage. La
        // fenêtre est indisponible si une émission planifiée chevauche [départ, départ + airtime) ;
        // la descente bascule alors sur RX2, puis est perdue si RX2 est aussi occupée.
        SimTime t_open = ta.end + kLoopRxDelayNs;
        SimTime start = t_open;
        rad.rx1_sf = ta.sf;
        SimTime air = 0;
        if (plan::downlink_airtime_ns(rad, base + fopts, air) != lora::Status::Ok) {
            status = SimStatus::InvalidInput;
            return;
        }
        bool scheduled = !transmitting(start, start + air);
        if (!scheduled) {
            t_open = ta.end + kLoopRx2DelayNs;
            start = t_open;
            rad.rx1_sf = kLoopRx2Sf;
            if (plan::downlink_airtime_ns(rad, base + fopts, air) != lora::Status::Ok) {
                status = SimStatus::InvalidInput;
                return;
            }
            scheduled = !transmitting(start, start + air);
        }
        if (scheduled) {
            // Insertion ordonnée : la liste reste croissante et disjointe (requise par `transmitting`).
            const auto pos = std::upper_bound(busy.begin(), busy.end(), start,
                                              [](SimTime s, const Interval& b) { return s < b.start; });
            busy.insert(pos, Interval{start, start + air});
        }
        LoopDownlink dl;
        dl.uplink = static_cast<std::uint32_t>(a);
        dl.device = d;
        dl.kind = kind;
        dl.commands = cmds;
        dl.queued = carried;
        dl_items.push_back(std::move(carried_ids));
        dl.t_open = t_open;
        dl.start_ns = scheduled ? start : -1;
        dl.air_ns = air;
        dl.req_dr = sv.pend_dr;
        dl.req_power_index = sv.pend_power;
        dls.push_back(dl);
        // LinkADRReq : vue du serveur, ChMaskCntl 0 sur le bloc 0 (utilisée seulement si LinkADR est portée).
        LoopLinkAdrRequest rq;
        rq.ch_mask_cntl = 0;
        rq.ch_mask = static_cast<std::uint16_t>(sv.view.words[0] & 0xFFFFU);
        rq.dr = sv.pend_dr;
        rq.power_index = sv.pend_power;
        if (io.config != nullptr && io.config[d].forced_request) rq = *io.config[d].forced_request;
        dl_requests.push_back(rq);
        // Fermeture de RX1 : l'occupation de la passerelle est connue, la réception se décide là.
        q.push(LoopEvent{t_open + kLoopRx1WindowNs, kLoopRankCheck, seq++, LoopKind::Check, d,
                         static_cast<std::uint32_t>(dls.size() - 1), 0});
    };

    while (!q.empty() && status == SimStatus::Ok) {
        const LoopEvent ev = q.top();
        q.pop();
        switch (ev.kind) {
            case LoopKind::Start: {
                const std::size_t i = ev.device;
                const EndDeviceSpec& d = devices[i];
                LoopDevice& ds = dev[i];
                if (ds.next_k >= d.messages) break;
                // TS001 §3.3.6 : pas d'émission avant d'avoir reçu une descente en RX1/RX2 de
                // l'uplink précédent, ou avant la fin de RX2. Attendre la fin de RX2 (fin + 3 s)
                // satisfait la règle dans tous les cas, y compris après une descente reçue en RX1.
                if (ds.has_prev) {
                    const SimTime rx_free = ds.prev_end + kLoopRx2DelayNs + kLoopRx2WindowNs;
                    if (rx_free > ev.t) {
                        q.push(LoopEvent{rx_free, kLoopRankStart, seq++, LoopKind::Start, ev.device, 0, 0});
                        break;
                    }
                }
                const std::size_t mo = mac_off[i] + ds.next_k;
                const std::uint32_t bytes = d.payload_bytes + answer_octets(ds.answer_mask) + mac_extra[mo];
                if (bytes > 255) {
                    status = SimStatus::InvalidInput;
                    break;
                }
                SimTime air = 0;
                if (!uplink_airtime(ds.sf, bytes, air)) {
                    status = SimStatus::InvalidInput;
                    break;
                }
                // Limite du duty cycle au moment du départ : réglementaire à l'index de puissance
                // courant, plafonnée par DutyCycleReq. Le repos suit l'airtime de l'émission terminée.
                const double duty = std::min(regions[i].duty_limit[ds.power_index], ds.cap);
                if (ds.has_prev) {
                    const double off = (1.0 - duty) / duty;
                    if (off > 0.0) {
                        const double earliest_d = static_cast<double>(ds.prev_end) +
                                                  std::round(static_cast<double>(ds.prev_air) * off);
                        if (earliest_d > kMaxHorizonNs) {
                            status = SimStatus::InvalidInput;
                            break;
                        }
                        const SimTime earliest = static_cast<SimTime>(earliest_d);
                        if (earliest > ev.t) {
                            q.push(LoopEvent{earliest, kLoopRankStart, seq++, LoopKind::Start,
                                             ev.device, 0, 0});
                            break;
                        }
                    }
                }
                std::uint8_t adr_req = 0;
                if (options.adr) {
                    // F14 (TS001 §4.3.1.1) : ADRACKCnt compte les nouveaux uplinks ; ADRACKReq dès
                    // LIMIT ; sans descente pendant LIMIT + DELAY uplinks, puissance par défaut puis
                    // un débit plus bas tous les DELAY uplinks, jusqu'au débit par défaut.
                    ++ds.adr_cnt;
                    const std::uint32_t first = kLoopAdrAckLimit + kLoopAdrAckDelay + 1;
                    if (ds.adr_cnt >= first && (ds.adr_cnt - first) % kLoopAdrAckDelay == 0) {
                        ds.power_index = 0;
                        // Repli : DRnext de la Table 12. Un débit cible indisponible dans la région
                        // laisse le débit inchangé (cas non atteint : max_dr ≤ 7 pour les régions de la boucle).
                        if (ds.dr >= 0 && static_cast<std::size_t>(ds.dr) < kLoopDrBackOffEu868.size()) {
                            const std::uint8_t back = kLoopDrBackOffEu868[static_cast<std::size_t>(ds.dr)];
                            if (back != ds.dr && regions[i].dr_sf[back] != 0) {
                                ds.dr = static_cast<std::int8_t>(back);
                                ds.sf = regions[i].dr_sf[back];
                            }
                        }
                    }
                    if (ds.adr_cnt >= kLoopAdrAckLimit) adr_req = 1;
                }
                const std::uint32_t idx = static_cast<std::uint32_t>(txs.size());
                Tx t;
                t.start = ev.t;
                t.end = ev.t + air;
                t.device = static_cast<std::uint32_t>(i);
                t.sf = ds.sf;
                t.rssi_dbm = rssi_of(i, ds.power_index);
                t.rank = ds.next_k + 1;
                txs.push_back(t);
                outcome.push_back(TxOutcome::LostSensitivity);
                powers.push_back(ds.power_index);
                drs.push_back(ds.dr);
                masks.push_back(static_cast<std::uint8_t>(ds.answer_mask | (ds.ds_pending ? 4U : 0U)));
                oks.push_back(ds.answer_ok);
                sts.push_back((ds.answer_mask & 1U) != 0 ? ds.answer_status : std::uint8_t{0xFF});
                adr_reqs.push_back(adr_req);
                ds.ds_pending = false;
                next_tx.push_back(-1);
                if (ds.last_tx >= 0) next_tx[static_cast<std::size_t>(ds.last_tx)] = idx;
                ds.last_tx = idx;
                ds.answer_mask = 0;
                ds.answer_ok = 0;
                ds.answer_status = 0xFF;
                per_device[i].airtime_ns += static_cast<std::uint64_t>(air);
                totals.airtime_ns += static_cast<std::uint64_t>(air);
                ds.prev_end = t.end;
                ds.prev_air = air;
                ds.has_prev = true;
                ++ds.next_k;
                q.push(LoopEvent{t.end, kLoopRankEnd, seq++, LoopKind::End, 0, idx, 0});
                if (ds.next_k < d.messages) {
                    SimTime nom = 0;
                    if (!nominal(i, ds.next_k, nom)) {
                        status = SimStatus::InvalidInput;
                        break;
                    }
                    q.push(LoopEvent{nom, kLoopRankStart, seq++, LoopKind::Start, ev.device, 0, 0});
                }
                break;
            }
            case LoopKind::End: {
                const std::size_t a = ev.index;
                const Tx ta = txs[a];
                DeviceStats& st = per_device[ta.device];
                TxOutcome o = TxOutcome::LostSensitivity;
                if (ta.rssi_dbm < sensitivity_by_sf[ta.sf]) {
                    ++st.lost_sensitivity;
                    ++totals.lost_sensitivity;
                } else if (transmitting(ta.start, ta.end)) {
                    ++st.lost_gateway_busy;
                    ++totals.lost_gateway_busy;
                    o = TxOutcome::LostGatewayBusy;
                } else {
                    bool interfered = false;
                    double max_interf = -1e300;
                    const auto consider = [&](const Tx& tb) {
                        if (tb.sf == ta.sf && overlap(ta, tb)) {
                            interfered = true;
                            max_interf = std::max(max_interf, tb.rssi_dbm);
                        }
                    };
                    for (std::size_t b = a + 1; b < txs.size() && txs[b].start < ta.end; ++b) {
                        consider(txs[b]);
                    }
                    for (std::size_t b = a; b-- > 0;) {
                        if (txs[b].start + max_airtime <= ta.start) break;
                        consider(txs[b]);
                    }
                    const bool captured =
                        !interfered || (ta.rssi_dbm - max_interf >= prop.capture_threshold_db);
                    if (captured) {
                        ++st.received;
                        ++totals.received;
                        o = TxOutcome::Received;
                    } else {
                        ++st.lost_collision;
                        ++totals.lost_collision;
                        o = TxOutcome::LostCollision;
                    }
                }
                outcome[a] = o;
                if (o == TxOutcome::Received) on_received(a);
                break;
            }
            case LoopKind::Check: {
                // RX1 fermée : perdue si le dispositif a émis dans la fenêtre, ou si la réception
                // de la descente échoue. Les émissions débutant avant cet instant sont connues.
                LoopDownlink& dl = dls[ev.index];
                const SimTime close = dl.t_open + kLoopRx1WindowNs;
                const std::int64_t nxt = next_tx[dl.uplink];
                dl.device_missed = nxt >= 0 && txs[static_cast<std::size_t>(nxt)].start < close;
                bool ok = dl.start_ns >= 0 && !dl.device_missed;
                if (ok) {
                    const Tx& ta = txs[dl.uplink];
                    plan::DeviceRadio rad = radios[dl.device];
                    const bool rx2 = dl.t_open == ta.end + kLoopRx2DelayNs;
                    rad.rx1_sf = rx2 ? kLoopRx2Sf : ta.sf;
                    const double rssi_dl = ta.rssi_dbm - tx_dbm(dl.device, powers[dl.uplink]) +
                                           options.protocol.gateway_tx_power_dbm +
                                           options.protocol.device_antenna_gain_dbi;
                    double sens = 0.0;
                    if (lora::receiver_sensitivity_dbm(rad.rx1_sf, static_cast<lora::Bandwidth>(rad.rx1_bw_hz),
                                                       sens) != lora::Status::Ok) {
                        status = SimStatus::InvalidInput;
                        break;
                    }
                    ok = rssi_dl >= sens + options.protocol.device_rx_offset_db;
                }
                dl.delivered = ok;
                if (ok) dev[dl.device].adr_cnt = 0;  // F14 : toute descente de classe A reçue
                {
                    const std::vector<std::uint32_t>& ids = dl_items[ev.index];
                    for (const std::uint32_t id : ids) {
                        out.mac_items[id].state = ok ? LoopMacState::Delivered : LoopMacState::Lost;
                    }
                    if (ok) {
                        qs.delivered += ids.size();
                    } else {
                        qs.dispatch_lost += ids.size();
                    }
                }
                if (ok && (dl.commands & kLoopCmdDevStatus) != 0) {
                    dev[dl.device].ds_pending = true;  // DevStatusAns portée par l'uplink suivant
                }
                if (ok) {
                    const SimTime apply_at = std::max(close, dl.start_ns + dl.air_ns);
                    if ((dl.commands & kLoopCmdLinkAdr) != 0) {
                        q.push(LoopEvent{apply_at, kLoopRankCheck, seq++, LoopKind::Apply, dl.device,
                                         ev.index, kLoopCmdLinkAdr});
                    }
                    if ((dl.commands & kLoopCmdDutyCycle) != 0) {
                        q.push(LoopEvent{apply_at, kLoopRankCheck, seq++, LoopKind::Apply, dl.device,
                                         ev.index, kLoopCmdDutyCycle});
                    }
                }
                break;
            }
            case LoopKind::Apply: {
                const std::size_t i = ev.device;
                LoopDevice& ds = dev[i];
                if (ev.cmd == kLoopCmdLinkAdr) {
                    // Validation et application atomiques (TS001 §5.2) sur la vue du terminal : le
                    // plan porte les débits de la région (table 125 kHz), ses puissances et ses défauts.
                    const LoopRegion& rg = regions[i];
                    const LoopLinkAdrRequest& rq = dl_requests[ev.index];
                    LoopRegionalPlan plan = loop_eu868_plan();
                    plan.max_dr = rg.max_dr;
                    plan.max_power_index = rg.max_tx_power_index;
                    plan.dr_available = 0;
                    for (std::size_t k = 0; k < 8U; ++k) {
                        if (rg.dr_sf[k] != 0) plan.dr_available = static_cast<std::uint8_t>(plan.dr_available | (1U << k));
                    }
                    LoopTerminalRadio term;
                    term.channels = ds.channels;
                    term.dr = static_cast<std::uint8_t>(ds.dr < 0 ? 0 : ds.dr);
                    term.power_index = ds.power_index;
                    const LoopLinkAdrDiagnosis dg = loop_apply_link_adr(plan, term, rq);
                    if (dl_diag.size() <= ev.index) dl_diag.resize(ev.index + 1);
                    dl_diag[ev.index] = dg;
                    ds.answer_mask = static_cast<std::uint8_t>(ds.answer_mask | 1U);
                    ds.answer_status = dg.status.to_wire();
                    // Bits historiques de ABI v2 (`answer_ok`) : bit 0 débit, bit 1 puissance.
                    ds.answer_ok = static_cast<std::uint8_t>((ds.answer_ok & ~3U) |
                                                             (dg.status.data_rate_ack ? 1U : 0U) |
                                                             (dg.status.power_ack ? 2U : 0U));
                    if (dg.status.all()) {
                        ds.channels = term.channels;
                        if (rq.dr != kLoopIgnoreField) {
                            ds.dr = static_cast<std::int8_t>(term.dr);
                            ds.sf = rg.dr_sf[term.dr];
                        }
                        if (rq.power_index != kLoopIgnoreField) ds.power_index = term.power_index;
                    }
                } else {
                    ds.cap = std::ldexp(1.0, -static_cast<int>(options.duty_cycle_exponent));
                    ds.answer_mask = static_cast<std::uint8_t>(ds.answer_mask | 2U);
                }
                break;
            }
        }
    }
    if (status != SimStatus::Ok) return status;
    for (const LoopServer& sv : srv) qs.pending_at_end += sv.queue.size();
    out.mac = qs;

    // Sorties : émissions, occupation passerelle, métriques passerelle (comme `simulate_uplinks`).
    out.uplinks.reserve(txs.size());
    for (std::size_t a = 0; a < txs.size(); ++a) {
        const Tx& t = txs[a];
        LoopUplink u;
        u.device = t.device;
        u.start_ns = t.start;
        u.end_ns = t.end;
        u.spreading_factor = t.sf;
        u.dr = drs[a];
        u.power_index = powers[a];
        u.rssi_dbm = t.rssi_dbm;
        u.outcome = outcome[a];
        u.answer_mask = masks[a];
        u.answer_ok = oks[a];
        out.uplinks.push_back(u);
    }
    out.gateway_busy = busy;
    io.uplink_status = sts;
    io.downlink_requests = dl_requests;
    io.downlink_diagnoses = dl_diag;
    io.downlink_diagnoses.resize(dls.size());
    io.terminals.clear();
    for (std::size_t i = 0; i < n; ++i) {
        LoopTerminalRadio t;
        t.channels = dev[i].channels;
        t.dr = static_cast<std::uint8_t>(dev[i].dr < 0 ? 0 : dev[i].dr);
        t.power_index = dev[i].power_index;
        io.terminals.push_back(t);
    }
    if (!txs.empty()) {
        SimTime busy_sum = 0;
        SimTime cur_s = txs[0].start;
        SimTime cur_e = txs[0].end;
        SimTime last_end = txs[0].end;
        for (std::size_t k = 1; k < txs.size(); ++k) {
            last_end = std::max(last_end, txs[k].end);
            if (txs[k].start > cur_e) {
                busy_sum += cur_e - cur_s;
                cur_s = txs[k].start;
                cur_e = txs[k].end;
            } else {
                cur_e = std::max(cur_e, txs[k].end);
            }
        }
        busy_sum += cur_e - cur_s;
        std::vector<SimTime> ends;
        ends.reserve(txs.size());
        for (const Tx& t : txs) ends.push_back(t.end);
        std::sort(ends.begin(), ends.end());
        std::uint64_t peak = 0;
        std::size_t ended = 0;
        for (std::size_t k = 0; k < txs.size(); ++k) {
            while (ended < ends.size() && ends[ended] <= txs[k].start) ++ended;
            peak = std::max(peak, static_cast<std::uint64_t>(k + 1 - ended));
        }
        const SimTime observation = last_end - txs[0].start;
        totals.gateway_busy_ns = static_cast<std::uint64_t>(busy_sum);
        totals.gateway_peak_concurrent = peak;
        totals.observation_ns = observation;
        totals.gateway_utilization =
            observation > 0 ? static_cast<double>(busy_sum) / static_cast<double>(observation) : 0.0;
    }
    for (std::size_t i = 0; i < n; ++i) totals.sent += per_device[i].sent;
    return SimStatus::Ok;
}

}  // namespace lsim::sim
