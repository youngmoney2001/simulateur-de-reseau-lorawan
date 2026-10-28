// SPDX-License-Identifier: Apache-2.0
#include "lsim/downlink.hpp"

#include <algorithm>

namespace lsim::lorawan::downlink {

namespace {

// Premier indice dont le membre `value(k)` est >= `bound`, pour une suite croissante.
template <typename F>
std::size_t lower_index(std::size_t n, std::int64_t bound, F value) {
    std::size_t lo = 0;
    std::size_t hi = n;
    while (lo < hi) {
        const std::size_t mid = lo + (hi - lo) / 2;
        if (value(mid) < bound) {
            lo = mid + 1;
        } else {
            hi = mid;
        }
    }
    return lo;
}

}  // namespace

std::vector<Window> merge_windows(std::vector<Window> w) {
    std::sort(w.begin(), w.end(), [](const Window& a, const Window& b) {
        return a.start_ns != b.start_ns ? a.start_ns < b.start_ns : a.end_ns < b.end_ns;
    });
    std::vector<Window> out;
    out.reserve(w.size());
    for (const Window& x : w) {
        if (x.end_ns <= x.start_ns) continue;
        if (!out.empty() && x.start_ns <= out.back().end_ns) {
            out.back().end_ns = std::max(out.back().end_ns, x.end_ns);
        } else {
            out.push_back(x);
        }
    }
    return out;
}

DownlinkStatus class_c_blocked(const std::vector<Window>& uplinks, const Timing& t,
                               std::vector<Window>& out) {
    if (t.rx1_delay_ns < 0 || t.rx_window_ns < 0) return DownlinkStatus::InvalidParameter;
    std::vector<Window> raw;
    raw.reserve(uplinks.size() * 2);
    for (const Window& u : uplinks) {
        if (u.end_ns < u.start_ns) return DownlinkStatus::InvalidParameter;
        raw.push_back(Window{u.start_ns, u.end_ns});
        const std::int64_t rx1 = u.end_ns + t.rx1_delay_ns;
        raw.push_back(Window{rx1, rx1 + t.rx_window_ns});
    }
    out = merge_windows(std::move(raw));
    return DownlinkStatus::Ok;
}

DownlinkStatus next_class_a(const std::vector<Window>& uplinks, std::int64_t request_ns,
                            const Timing& t, std::int64_t& opportunity_ns) {
    if (t.rx1_delay_ns < 0 || t.rx2_delay_ns < t.rx1_delay_ns || request_ns < 0) {
        return DownlinkStatus::InvalidParameter;
    }
    // Les fins d'uplink sont croissantes : RX1 et RX2 le sont donc aussi. Premier
    // candidat >= request pour chacune des deux suites, puis le plus petit.
    const std::size_t n = uplinks.size();
    const std::size_t i1 = lower_index(n, request_ns, [&](std::size_t k) {
        return uplinks[k].end_ns + t.rx1_delay_ns;
    });
    const std::size_t i2 = lower_index(n, request_ns, [&](std::size_t k) {
        return uplinks[k].end_ns + t.rx2_delay_ns;
    });
    bool found = false;
    std::int64_t best = 0;
    if (i1 < n) {
        best = uplinks[i1].end_ns + t.rx1_delay_ns;
        found = true;
    }
    if (i2 < n) {
        const std::int64_t c = uplinks[i2].end_ns + t.rx2_delay_ns;
        if (!found || c < best) best = c;
        found = true;
    }
    if (!found) return DownlinkStatus::NoOpportunity;
    opportunity_ns = best;
    return DownlinkStatus::Ok;
}

DownlinkStatus next_class_c(const std::vector<Window>& blocked, std::int64_t request_ns,
                            std::int64_t& opportunity_ns) {
    if (request_ns < 0) return DownlinkStatus::InvalidParameter;
    // `blocked` est fusionné et trié : au plus un intervalle contient request_ns.
    const std::size_t idx = lower_index(blocked.size(), request_ns + 1, [&](std::size_t k) {
        return blocked[k].start_ns;
    });
    if (idx > 0 && blocked[idx - 1].end_ns > request_ns) {
        opportunity_ns = blocked[idx - 1].end_ns;
    } else {
        opportunity_ns = request_ns;
    }
    return DownlinkStatus::Ok;
}

DownlinkStatus next_class_b(const ClassBProfile& profile, const std::vector<Window>& blocked,
                            std::int64_t request_ns, std::int64_t& opportunity_ns) {
    if (request_ns < 0 || profile.periodicity > classb::kMaxPeriodicity ||
        profile.clock_drift_ppm > classb::kMaxDriftPpm) {
        return DownlinkStatus::InvalidParameter;
    }
    std::int64_t t = request_ns;
    for (std::size_t iter = 0; iter < kMaxSlotSearch; ++iter) {
        // Balise la plus récente à l'instant t (une balise par période de 128 s).
        const std::uint64_t period_start =
            (static_cast<std::uint64_t>(t) / classb::kBeaconPeriodNs) * classb::kBeaconPeriodNs;
        classb::DeviceClassB dev;
        dev.synchronized = true;
        dev.last_beacon_rx_ns = period_start;
        dev.last_beacon_time_s = static_cast<std::uint32_t>(period_start / 1'000'000'000ull);
        dev.dev_addr = profile.dev_addr;
        dev.periodicity = profile.periodicity;
        dev.clock_drift_ppm = profile.clock_drift_ppm;

        classb::PingSlot slot{};
        if (classb::next_ping_slot(dev, static_cast<std::uint64_t>(t), slot) !=
            classb::ClassBStatus::Ok) {
            return DownlinkStatus::NoOpportunity;
        }
        const std::int64_t margin = static_cast<std::int64_t>(slot.window_half_ns);
        const std::int64_t win_start = static_cast<std::int64_t>(slot.start_ns) - margin;
        const std::int64_t win_end =
            static_cast<std::int64_t>(slot.start_ns + classb::kSlotNs) + margin;
        // Premier bloc finissant après win_start.
        const std::size_t idx = lower_index(blocked.size(), win_start + 1, [&](std::size_t k) {
            return blocked[k].end_ns;
        });
        if (idx < blocked.size() && blocked[idx].start_ns < win_end) {
            // Chevauchement : prochain candidat après la fin du bloc (marge incluse).
            t = std::max(static_cast<std::int64_t>(slot.start_ns) + 1, blocked[idx].end_ns + margin);
            continue;
        }
        opportunity_ns = static_cast<std::int64_t>(slot.start_ns);
        return DownlinkStatus::Ok;
    }
    return DownlinkStatus::NoOpportunity;
}

}  // namespace lsim::lorawan::downlink
