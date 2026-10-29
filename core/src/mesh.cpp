// SPDX-License-Identifier: Apache-2.0
#include "lsim/mesh.hpp"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <functional>
#include <map>
#include <queue>
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

// Liste d'intervalles d'émission d'un nœud : non chevauchants, triés (un émetteur
// ne peut pas émettre deux fois à la fois, et sa file est FIFO).
struct TxSpan {
    std::int64_t start;
    std::int64_t end;
};

struct Hop {
    std::size_t frame_index;   // indice dans le tableau d'entrée
    std::uint8_t index;        // numéro du saut, 0 = premier
    std::uint32_t sender;
    std::uint32_t receiver;
    std::int64_t start;
    std::int64_t end;
    double rssi;
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

Status forward(const Radio& radio, std::size_t n, const double* rssi,
               const std::int32_t* next, std::uint32_t border,
               const Frame* frames, std::size_t frame_count, Delivery* out) {
    if (rssi == nullptr || next == nullptr || (frame_count > 0 && (frames == nullptr || out == nullptr))) {
        return Status::InvalidInput;
    }
    if (n == 0 || n > kMaxNodes) return Status::TooManyNodes;
    if (frame_count > kMaxFrames) return Status::TooManyFrames;
    if (border >= n) return Status::UnknownBorder;
    if (validate_radio(radio) != Status::Ok) return Status::InvalidRadio;
    std::int64_t airtime = 0;
    airtime_ns(radio, airtime);
    const double capture = radio.capture_db;

    std::vector<Delivery> results(frame_count);
    std::vector<Hop> hops;
    std::vector<std::vector<TxSpan>> tx(n);                       // émissions par nœud
    std::vector<std::multimap<std::int64_t, std::size_t>> rx(n);  // réceptions par début -> hop
    std::vector<std::int64_t> busy_until(n, 0);

    using Event = std::pair<std::int64_t, std::size_t>;           // (fin, indice du saut)
    std::priority_queue<Event, std::vector<Event>, std::greater<>> heap;

    auto transmit = [&](std::size_t frame_index, std::uint8_t index, std::uint32_t sender,
                        std::uint32_t receiver, std::int64_t ready) {
        const std::int64_t start = std::max(ready, busy_until[sender]);
        const std::int64_t end = start + airtime;
        busy_until[sender] = end;
        tx[sender].push_back(TxSpan{start, end});
        const std::size_t id = hops.size();
        hops.push_back(Hop{frame_index, index, sender, receiver, start, end,
                           rssi[static_cast<std::size_t>(sender) * n + receiver]});
        rx[receiver].emplace(start, id);
        heap.emplace(end, id);
    };

    // Trames traitées par ordre de date (puis identifiant), comme côté Python.
    std::vector<std::size_t> order(frame_count);
    for (std::size_t k = 0; k < frame_count; ++k) order[k] = k;
    std::sort(order.begin(), order.end(), [&](std::size_t a, std::size_t b) {
        if (frames[a].t_ns != frames[b].t_ns) return frames[a].t_ns < frames[b].t_ns;
        return frames[a].frame_id < frames[b].frame_id;
    });

    for (const std::size_t k : order) {
        const Frame& f = frames[k];
        Delivery& d = results[k];
        d.frame_id = f.frame_id;
        if (f.rx_node >= n) return Status::UnknownNode;
        if (f.rx_node == border) {
            d.delivered = 1;
            d.loss = static_cast<std::uint8_t>(Loss::Delivered);
            d.latency_ns = 0;
            continue;
        }
        if (next[f.rx_node] < 0) {
            d.loss = static_cast<std::uint8_t>(Loss::NoRoute);
            continue;
        }
        transmit(k, 0, f.rx_node, static_cast<std::uint32_t>(next[f.rx_node]), f.t_ns);
    }

    while (!heap.empty()) {
        const std::size_t id = heap.top().second;
        heap.pop();
        const Hop h = hops[id];
        const std::uint32_t r = h.receiver;
        Delivery& d = results[h.frame_index];
        d.hops = static_cast<std::uint8_t>(h.index + 1);

        // Demi-duplex : le récepteur émettait pendant une partie de la trame.
        // Les intervalles d'un nœud sont triés et disjoints : recherche dichotomique.
        const auto& spans = tx[r];
        auto it = std::lower_bound(spans.begin(), spans.end(), h.start,
                                   [](const TxSpan& s, std::int64_t t) { return s.end <= t; });
        const bool half_duplex = it != spans.end() && it->start < h.end;
        if (half_duplex) {
            d.loss = static_cast<std::uint8_t>(Loss::HalfDuplex);
            continue;
        }

        // Collision : un autre saut audible au récepteur chevauche ce saut et n'est
        // pas plus faible de `capture` dB. Seuls les débuts dans (start - airtime, end)
        // peuvent chevaucher, la durée d'émission étant uniforme.
        bool collided = false;
        const auto& recv = rx[r];
        for (auto jt = recv.upper_bound(h.start - airtime); jt != recv.end() && jt->first < h.end; ++jt) {
            if (jt->second == id) continue;
            const Hop& other = hops[jt->second];
            if (!(other.start < h.end && h.start < other.end)) continue;
            if (h.rssi < other.rssi + capture) {
                collided = true;
                break;
            }
        }
        if (collided) {
            d.loss = static_cast<std::uint8_t>(Loss::Collision);
            continue;
        }

        if (r == border) {
            d.delivered = 1;
            d.loss = static_cast<std::uint8_t>(Loss::Delivered);
            d.latency_ns = h.end - frames[h.frame_index].t_ns;
            continue;
        }
        const std::int32_t nxt = next[r];
        if (nxt < 0) {
            d.loss = static_cast<std::uint8_t>(Loss::NoRoute);
            continue;
        }
        transmit(h.frame_index, static_cast<std::uint8_t>(h.index + 1), r,
                 static_cast<std::uint32_t>(nxt), h.end);
    }

    for (std::size_t k = 0; k < frame_count; ++k) out[k] = results[k];
    return Status::Ok;
}

}  // namespace lsim::mesh
