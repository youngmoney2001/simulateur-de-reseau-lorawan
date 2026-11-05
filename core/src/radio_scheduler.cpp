// SPDX-License-Identifier: Apache-2.0
// Ordonnanceur radio (voir `lsim/radio_scheduler.hpp` pour le contrat et la règle A6).
//
// Ce fichier est l'extraction fidèle du placement qui se trouvait dans
// `lsim::sim::simulate_closed_loop` (jalon U0.1) : les formes et l'ordre des opérations sont
// conservés à l'identique, afin que la migration ne change aucun résultat.
#include "lsim/radio_scheduler.hpp"

#include <algorithm>

namespace lsim::radio {

void RadioScheduler::seed(const std::vector<Interval>& intervals) {
    for (const Interval& iv : intervals) {
        insert(iv.start, iv.end);
    }
}

bool RadioScheduler::transmitting(SimTime start, SimTime end) const {
    // `busy_` est croissante et disjointe : la première émission qui finit après `start` est la
    // seule qui puisse encore chevaucher.
    auto it = std::lower_bound(busy_.begin(), busy_.end(), start,
                               [](const Interval& b, SimTime s) { return b.end <= s; });
    return it != busy_.end() && it->start < end;
}

Placement RadioScheduler::place(SimTime rx1_open_ns, SimTime rx1_air_ns,
                                SimTime rx2_open_ns, SimTime rx2_air_ns, bool rx2_allowed) {
    Placement p;
    p.t_open_ns = rx1_open_ns;
    p.air_ns = rx1_air_ns;

    if (!transmitting(rx1_open_ns, rx1_open_ns + rx1_air_ns)) {
        p.verdict = PlacementVerdict::PlacedRx1;
        p.start_ns = rx1_open_ns;
        insert(rx1_open_ns, rx1_open_ns + rx1_air_ns);
        return p;
    }

    if (rx2_allowed) {
        // Repli : RX2 est examinée à **sa** ouverture, pas à un instant décalé depuis RX1.
        p.t_open_ns = rx2_open_ns;
        p.air_ns = rx2_air_ns;
        if (!transmitting(rx2_open_ns, rx2_open_ns + rx2_air_ns)) {
            p.verdict = PlacementVerdict::PlacedRx2;
            p.start_ns = rx2_open_ns;
            insert(rx2_open_ns, rx2_open_ns + rx2_air_ns);
            return p;
        }
    }

    // A6 : aucune fenêtre disponible. Rien n'est émis, l'émetteur n'est pas occupé, et la
    // descente n'est **pas** reportée à un instant ultérieur.
    p.verdict = PlacementVerdict::NotPlaced;
    p.start_ns = -1;
    return p;
}

void RadioScheduler::insert(SimTime start, SimTime end) {
    const auto pos = std::upper_bound(busy_.begin(), busy_.end(), start,
                                      [](SimTime s, const Interval& b) { return s < b.start; });
    busy_.insert(pos, Interval{start, end});
}

}  // namespace lsim::radio
