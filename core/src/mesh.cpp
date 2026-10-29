// SPDX-License-Identifier: Apache-2.0
#include "lsim/mesh.hpp"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <functional>
#include <map>
#include <queue>
#include <unordered_map>
#include <utility>

namespace lsim::mesh {
namespace {

// Sensibilité SX1280 : lignes BW 203/406/812/1625 kHz, colonnes SF5..SF12.
constexpr std::int32_t kSensitivity[4][8] = {
    {-109, -111, -115, -118, -121, -124, -127, -130},
    {-107, -110, -113, -116, -119, -122, -125, -128},
    {-105, -108, -112, -115, -117, -120, -123, -126},
    {-99, -103, -106, -109, -111, -114, -117, -120},
};

int bandwidth_row(std::uint32_t bandwidth_hz) {
    switch (bandwidth_hz) {
        case 203'000: return 0;
        case 406'000: return 1;
        case 812'000: return 2;
        case 1'625'000: return 3;
        default: return -1;
    }
}

Status validate_radio(const Radio& r) {
    if (r.spreading_factor < 5 || r.spreading_factor > 12) return Status::InvalidRadio;
    if (r.coding_rate < 1 || r.coding_rate > 4) return Status::InvalidRadio;
    if (r.bandwidth_hz == 0) return Status::InvalidRadio;
    if (r.payload_bytes > 255) return Status::InvalidRadio;
    if (r.preamble_symbols < 6 || r.preamble_symbols > 65535) return Status::InvalidRadio;
    if (!std::isfinite(r.capture_db) || r.capture_db < 0.0) return Status::InvalidRadio;
    return Status::Ok;
}

// Vrai si le temps d'un symbole dépasse 16 ms : 2^SF / BW > 0,016 ⇔ 1000·2^SF > 16·BW.
bool low_data_rate(std::uint8_t sf, std::uint32_t bw) {
    const std::int64_t lhs = 1000 * (std::int64_t{1} << sf);
    return lhs > 16 * static_cast<std::int64_t>(bw);
}

// Arrondi au plus proche, moitié vers le pair (comme `round` de Python sur Fraction).
std::int64_t round_half_even(std::int64_t num, std::int64_t den) {
    std::int64_t q = num / den;
    const std::int64_t r = num % den;
    if (2 * r > den || (2 * r == den && (q % 2) != 0)) {
        ++q;
    }
    return q;
}

struct TxSpan {
    std::int64_t start;
    std::int64_t end;
};

enum class RelayState : std::uint8_t { Pending = 1, Forwarded = 2, Suppressed = 3 };

// Une émission mesh (une copie qui saute d'un relais vers le suivant).
struct Tx {
    std::uint32_t sender = 0;
    std::uint32_t dest = 0;         // destination de la trame (frontière de la passe)
    std::uint64_t frame_id = 0;
    std::size_t copy = 0;           // copie d'origine (indice dans le tableau d'entrée)
    std::uint8_t index = 0;         // numéro du saut, 0 = premier
    std::int64_t ready = 0;         // instant où la copie est disponible au relais
    std::int64_t start = 0;
    std::int64_t end = 0;
    std::vector<std::size_t> rx;    // réceptions créées par cette émission
};

// Une réception : `receiver` entend `tx`. `intended` : c'est le saut prévu.
struct Rx {
    std::size_t tx = 0;
    std::uint32_t receiver = 0;
    std::int64_t start = 0;
    std::int64_t end = 0;
    double rssi = 0.0;
    bool intended = false;
};

struct FrameInfo {
    std::uint32_t dest = 0;         // destination (frontière) de la trame
    std::int64_t t_first = 0;       // première réception à l'accès
    bool delivered = false;
    std::int64_t best_end = 0;      // fin de la première copie livrée
    std::uint8_t best_hops = 0;
    std::uint8_t loss = 0;          // pire perte de copie (priorité : collision > demi-duplex > route)
};

enum class Kind : std::uint8_t { Access = 0, Start = 1, End = 2 };

struct Event {
    std::int64_t t;
    std::uint64_t seq;
    Kind kind;
    std::size_t id;                 // copie (Access) ou émission (Start, End)
    bool operator>(const Event& o) const {
        return t != o.t ? t > o.t : seq > o.seq;
    }
};

}  // namespace

Status airtime_ns(const Radio& radio, std::int64_t& out) {
    if (validate_radio(radio) != Status::Ok) return Status::InvalidRadio;
    const std::int64_t sf = radio.spreading_factor;
    const std::int64_t bw = radio.bandwidth_hz;
    const std::int64_t de = low_data_rate(radio.spreading_factor, radio.bandwidth_hz) ? 1 : 0;
    // Charge utile : CRC activé, en-tête explicite (IH = 0).
    const std::int64_t num = 8 * static_cast<std::int64_t>(radio.payload_bytes) - 4 * sf + 28 + 16;
    const std::int64_t den = 4 * (sf - 2 * de);
    const std::int64_t blocks = num > 0 ? (num + den - 1) / den : 0;
    const std::int64_t payload_symbols = 8 + blocks * (radio.coding_rate + 4);
    // Durée = (préambule + 4,25 + charge) · 2^SF / BW ; on exprime tout en quarts de symbole.
    const std::int64_t quarter_symbols =
        4 * static_cast<std::int64_t>(radio.preamble_symbols) + 17 + 4 * payload_symbols;
    const std::int64_t numerator = quarter_symbols * (std::int64_t{1} << sf) * 1'000'000'000;
    out = round_half_even(numerator, 4 * bw);
    return Status::Ok;
}

Status sensitivity_dbm(const Radio& radio, std::int32_t& out) {
    if (validate_radio(radio) != Status::Ok) return Status::InvalidRadio;
    const int row = bandwidth_row(radio.bandwidth_hz);
    if (row < 0) return Status::InvalidRadio;
    out = kSensitivity[row][radio.spreading_factor - 5];
    return Status::Ok;
}

Status routes(const Radio& radio, std::size_t n, const std::uint8_t* capable,
              const double* rssi, std::uint32_t border, std::uint32_t max_hops,
              std::int32_t* next) {
    if (capable == nullptr || rssi == nullptr || next == nullptr) return Status::InvalidInput;
    if (n == 0 || n > kMaxNodes) return Status::TooManyNodes;
    if (border >= n) return Status::UnknownBorder;
    if (max_hops < 1 || max_hops > kMaxHops) return Status::InvalidHops;
    std::int32_t sens = 0;
    if (sensitivity_dbm(radio, sens) != Status::Ok) return Status::InvalidRadio;
    if (capable[border] == 0) return Status::BorderNotCapable;

    auto link = [&](std::size_t i, std::size_t j) {
        return capable[i] != 0 && capable[j] != 0 &&
               rssi[i * n + j] >= static_cast<double>(sens) &&
               rssi[j * n + i] >= static_cast<double>(sens);
    };

    for (std::size_t v = 0; v < n; ++v) next[v] = -1;
    next[border] = static_cast<std::int32_t>(border);
    std::vector<std::size_t> frontier{border};
    for (std::uint32_t depth = 0; depth < max_hops && !frontier.empty(); ++depth) {
        std::vector<std::size_t> nxt;
        for (const std::size_t u : frontier) {
            for (std::size_t v = 0; v < n; ++v) {
                if (next[v] == -1 && v != u && link(u, v)) {
                    next[v] = static_cast<std::int32_t>(u);
                    nxt.push_back(v);
                }
            }
        }
        frontier = std::move(nxt);
    }
    return Status::Ok;
}

// Délai d'attente déterministe dans [0, window) pour (relais, trame) : SplitMix64.
std::int64_t backoff_ns(std::uint32_t relay, std::uint64_t frame_id, std::int64_t window) {
    if (window <= 0) return 0;
    std::uint64_t z = frame_id * 0x9E3779B97F4A7C15ULL + (static_cast<std::uint64_t>(relay) + 1) * 0xBF58476D1CE4E5B9ULL;
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
    z ^= z >> 31;
    return static_cast<std::int64_t>(z % static_cast<std::uint64_t>(window));
}

Status forward_routed(const Radio& radio, std::size_t n, const std::uint8_t* capable,
                      const double* rssi, const std::int32_t* next_by_dest,
                      const std::uint32_t* dests, bool suppress, std::int64_t backoff_window_ns,
                      const Frame* frames, std::size_t frame_count, Delivery* out, Summary* summary,
                      std::vector<HopEvent>* log) {
    if (capable == nullptr || rssi == nullptr || next_by_dest == nullptr || summary == nullptr ||
        (frame_count > 0 && (frames == nullptr || dests == nullptr || out == nullptr))) {
        return Status::InvalidInput;
    }
    if (backoff_window_ns < 0) return Status::InvalidInput;
    if (n == 0 || n > kMaxNodes) return Status::TooManyNodes;
    if (frame_count > kMaxFrames) return Status::TooManyFrames;
    if (validate_radio(radio) != Status::Ok) return Status::InvalidRadio;
    for (std::size_t k = 0; k < frame_count; ++k) {
        if (dests[k] >= n) return Status::UnknownBorder;
        if (capable[dests[k]] == 0) return Status::BorderNotCapable;
    }
    std::int32_t sens_i = 0;
    if (sensitivity_dbm(radio, sens_i) != Status::Ok) return Status::InvalidRadio;
    const double sens = static_cast<double>(sens_i);
    // Temps d'antenne par taille de trame (chaque Frame porte la sienne).
    std::vector<std::int64_t> air_by_size(256, -1);
    std::vector<std::int64_t> frame_air(frame_count, 0);
    std::int64_t max_air = 0;
    for (std::size_t k = 0; k < frame_count; ++k) {
        const std::uint32_t size = frames[k].payload_bytes;
        if (size > 255) return Status::InvalidRadio;
        if (air_by_size[size] < 0) {
            Radio r = radio;
            r.payload_bytes = size;
            std::int64_t a = 0;
            if (airtime_ns(r, a) != Status::Ok) return Status::InvalidRadio;
            air_by_size[size] = a;
        }
        frame_air[k] = air_by_size[size];
        max_air = std::max(max_air, frame_air[k]);
    }
    const double capture = radio.capture_db;
    // Route vers la destination `d` : prochain saut du nœud `i` (-1 si aucune route).
    auto nxt = [&](std::uint32_t d, std::uint32_t i) -> std::int32_t {
        return next_by_dest[static_cast<std::size_t>(d) * n + i];
    };

    *summary = Summary{};
    std::vector<Tx> txs;
    std::vector<Rx> rxs;
    std::vector<std::vector<TxSpan>> spans(n);                          // émissions committées par nœud
    std::vector<std::multimap<std::int64_t, std::size_t>> rx_at(n);     // réceptions par début
    std::vector<std::int64_t> busy_until(n, 0);
    std::unordered_map<std::uint64_t, FrameInfo> frame_info;
    // État par (relais, trame). Clé : identifiant de trame et relais.
    std::map<std::pair<std::uint32_t, std::uint64_t>, RelayState> relay_state;

    std::priority_queue<Event, std::vector<Event>, std::greater<>> heap;
    std::uint64_t seq = 0;
    auto push = [&](std::int64_t t, Kind kind, std::size_t id) {
        heap.push(Event{t, seq++, kind, id});
    };

    // Premier passage : première réception à l'accès de chaque trame, destination de la trame.
    for (std::size_t k = 0; k < frame_count; ++k) {
        if (frames[k].rx_node >= n) return Status::UnknownNode;
        auto [it, inserted] = frame_info.try_emplace(frames[k].frame_id);
        if (inserted) {
            it->second.dest = dests[k];
        } else if (it->second.dest != dests[k]) {
            return Status::InvalidInput;  // une même trame ne peut viser deux destinations
        }
        if (inserted || frames[k].t_ns < it->second.t_first) {
            it->second.t_first = frames[k].t_ns;
        }
        push(frames[k].t_ns, Kind::Access, k);
    }

    auto note_loss = [&](std::uint64_t frame_id, std::uint8_t reason) {
        FrameInfo& fi = frame_info[frame_id];
        if (reason > fi.loss) fi.loss = reason;
    };
    auto deliver = [&](std::uint64_t frame_id, std::int64_t t_end, std::uint8_t hops) {
        FrameInfo& fi = frame_info[frame_id];
        if (!fi.delivered || t_end < fi.best_end) {
            fi.delivered = true;
            fi.best_end = t_end;
            fi.best_hops = hops;
        }
    };

    // Relais d'une copie : elle devient disponible au nœud `r` à l'instant `t`.
    auto obtain = [&](std::uint32_t r, std::uint64_t frame_id, std::size_t copy,
                      std::uint8_t index, std::int64_t t) {
        const std::uint32_t dest = frame_info[frame_id].dest;
        if (nxt(dest, r) < 0) {
            note_loss(frame_id, static_cast<std::uint8_t>(Loss::NoRoute));
            return;
        }
        if (suppress) {
            const auto key = std::make_pair(r, frame_id);
            if (relay_state.count(key) != 0) {        // déjà pris en charge : copie superflue
                ++summary->suppressed;
                if (log != nullptr) {
                    log->push_back(HopEvent{frame_id, r, static_cast<std::uint32_t>(nxt(dest, r)), t, t,
                                            static_cast<std::uint8_t>(HopOutcome::Suppressed), index});
                }
                return;
            }
            relay_state[key] = RelayState::Pending;
        }
        Tx tx;
        tx.sender = r;
        tx.dest = dest;
        tx.frame_id = frame_id;
        tx.copy = copy;
        tx.index = index;
        tx.ready = t;
        txs.push_back(std::move(tx));
        push(t + backoff_ns(r, frame_id, backoff_window_ns), Kind::Start, txs.size() - 1);
    };

    std::size_t rx_total = 0;
    while (!heap.empty()) {
        const Event ev = heap.top();
        heap.pop();

        if (ev.kind == Kind::Access) {
            const Frame& f = frames[ev.id];
            const std::uint32_t dest = frame_info[f.frame_id].dest;
            if (f.rx_node == dest) {
                deliver(f.frame_id, f.t_ns, 0);
            } else {
                obtain(f.rx_node, f.frame_id, ev.id, 0, f.t_ns);
            }
            continue;
        }

        if (ev.kind == Kind::Start) {
            Tx& tx = txs[ev.id];
            const std::uint32_t s = tx.sender;
            if (suppress) {
                const auto st = relay_state[{s, tx.frame_id}];
                if (st != RelayState::Pending) {
                    ++summary->suppressed;  // copie en file, supprimée par un doublon entendu
                    if (log != nullptr) {
                        log->push_back(HopEvent{tx.frame_id, s, static_cast<std::uint32_t>(nxt(tx.dest, s)),
                                                ev.t, ev.t,
                                                static_cast<std::uint8_t>(HopOutcome::Suppressed), tx.index});
                    }
                    continue;
                }
            }
            if (busy_until[s] > ev.t) {
                push(busy_until[s], Kind::Start, ev.id);  // FIFO : attendre la fin de l'émission
                continue;
            }
            tx.start = ev.t;
            tx.end = ev.t + frame_air[tx.copy];
            busy_until[s] = tx.end;
            spans[s].push_back(TxSpan{tx.start, tx.end});
            if (suppress) relay_state[{s, tx.frame_id}] = RelayState::Forwarded;
            ++summary->transmissions;

            const std::uint32_t intended = static_cast<std::uint32_t>(nxt(tx.dest, s));
            for (std::uint32_t r = 0; r < n; ++r) {
                if (r == s || capable[r] == 0) continue;
                if (rssi[static_cast<std::size_t>(s) * n + r] < sens) continue;
                if (++rx_total > kMaxReceptions) return Status::TooManyReceptions;
                Rx q;
                q.tx = ev.id;
                q.receiver = r;
                q.start = tx.start;
                q.end = tx.end;
                q.rssi = rssi[static_cast<std::size_t>(s) * n + r];
                q.intended = (r == intended);
                rxs.push_back(q);
                const std::size_t rid = rxs.size() - 1;
                rx_at[r].emplace(q.start, rid);
                tx.rx.push_back(rid);
            }
            push(tx.end, Kind::End, ev.id);
            continue;
        }

        // Kind::End : évaluation de chaque réception de l'émission. Les champs sont copiés :
        // `obtain` ajoute des émissions et peut réallouer `txs`.
        const std::vector<std::size_t> tx_rx = txs[ev.id].rx;
        const std::uint64_t tx_frame = txs[ev.id].frame_id;
        const std::size_t tx_copy = txs[ev.id].copy;
        const std::uint8_t tx_index = txs[ev.id].index;
        const std::uint32_t tx_sender = txs[ev.id].sender;
        const std::uint32_t tx_dest = txs[ev.id].dest;
        const std::int64_t tx_start = txs[ev.id].start;
        const std::int64_t tx_end = txs[ev.id].end;
        for (const std::size_t rid : tx_rx) {
            const Rx q = rxs[rid];
            const std::uint32_t r = q.receiver;
            bool half_duplex = false;
            const auto& sp = spans[r];
            auto it = std::lower_bound(sp.begin(), sp.end(), q.start,
                                       [](const TxSpan& x, std::int64_t t) { return x.end <= t; });
            if (it != sp.end() && it->start < q.end) half_duplex = true;

            bool collided = false;
            if (!half_duplex) {
                const auto& at = rx_at[r];
                for (auto jt = at.upper_bound(q.start - max_air); jt != at.end() && jt->first < q.end; ++jt) {
                    if (jt->second == rid) continue;
                    const Rx& other = rxs[jt->second];
                    if (!(other.start < q.end && q.start < other.end)) continue;
                    if (q.rssi < other.rssi + capture) {
                        collided = true;
                        break;
                    }
                }
            }

            if (q.intended && log != nullptr) {
                const auto outcome = half_duplex ? HopOutcome::LostHalfDuplex
                                     : collided  ? HopOutcome::LostCollision
                                                 : HopOutcome::Received;
                log->push_back(HopEvent{tx_frame, tx_sender, r, tx_start, tx_end,
                                        static_cast<std::uint8_t>(outcome), tx_index});
            }
            if (half_duplex || collided) {
                if (q.intended) {
                    if (half_duplex) {
                        ++summary->lost_half_duplex;
                        note_loss(tx_frame, static_cast<std::uint8_t>(Loss::HalfDuplex));
                    } else {
                        ++summary->lost_collision;
                        note_loss(tx_frame, static_cast<std::uint8_t>(Loss::Collision));
                    }
                }
                continue;
            }

            if (q.intended) {
                if (r == tx_dest) {
                    deliver(tx_frame, q.end, static_cast<std::uint8_t>(tx_index + 1));
                } else {
                    obtain(r, tx_frame, tx_copy, static_cast<std::uint8_t>(tx_index + 1), q.end);
                }
            } else if (suppress) {
                // Un relais entend une transmission qui n'est pas la sienne : si sa propre
                // copie n'est pas encore partie, elle est superflue.
                const auto key = std::make_pair(r, tx_frame);
                auto st = relay_state.find(key);
                if (st == relay_state.end()) {
                    relay_state[key] = RelayState::Suppressed;
                } else if (st->second == RelayState::Pending) {
                    st->second = RelayState::Suppressed;
                }
            }
        }
    }

    // Sorties : une entrée par copie, avec l'issue de la trame.
    for (std::size_t k = 0; k < frame_count; ++k) {
        const Frame& f = frames[k];
        const FrameInfo& fi = frame_info[f.frame_id];
        Delivery& d = out[k];
        d.frame_id = f.frame_id;
        d.delivered = fi.delivered ? 1 : 0;
        if (fi.delivered) {
            d.loss = static_cast<std::uint8_t>(Loss::Delivered);
            d.hops = fi.best_hops;
            d.latency_ns = fi.best_end - fi.t_first;
        } else {
            d.loss = fi.loss != 0 ? fi.loss : static_cast<std::uint8_t>(Loss::Suppressed);
            d.hops = 0;
            d.latency_ns = -1;
        }
        CopyState cs;
        if (f.rx_node == fi.dest) {
            cs = CopyState::Border;
        } else if (nxt(fi.dest, f.rx_node) < 0) {
            cs = CopyState::NoRoute;
        } else if (suppress) {
            const auto it = relay_state.find({f.rx_node, f.frame_id});
            cs = (it != relay_state.end() && it->second == RelayState::Suppressed)
                     ? CopyState::Suppressed
                     : CopyState::Forwarded;
        } else {
            cs = CopyState::Forwarded;
        }
        d.copy_state = static_cast<std::uint8_t>(cs);
    }
    return Status::Ok;
}

Status forward(const Radio& radio, std::size_t n, const std::uint8_t* capable,
               const double* rssi, const std::int32_t* next, std::uint32_t border,
               bool suppress, std::int64_t backoff_window_ns, const Frame* frames,
               std::size_t frame_count, Delivery* out, Summary* summary,
               std::vector<HopEvent>* log) {
    if (next == nullptr) return Status::InvalidInput;
    if (n == 0 || n > kMaxNodes) return Status::TooManyNodes;
    if (border >= n) return Status::UnknownBorder;
    // Une seule destination : la ligne de la frontière porte les routes, les autres sont absentes.
    std::vector<std::int32_t> by_dest(n * n, -1);
    for (std::size_t i = 0; i < n; ++i) by_dest[static_cast<std::size_t>(border) * n + i] = next[i];
    std::vector<std::uint32_t> dests(frame_count, border);
    return forward_routed(radio, n, capable, rssi, by_dest.data(),
                          frame_count > 0 ? dests.data() : nullptr, suppress, backoff_window_ns,
                          frames, frame_count, out, summary, log);
}

}  // namespace lsim::mesh
