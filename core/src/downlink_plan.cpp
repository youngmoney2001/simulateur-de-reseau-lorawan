// SPDX-License-Identifier: Apache-2.0
#include "lsim/downlink_plan.hpp"

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <limits>
#include <queue>

#include "lsim/lora_phy.hpp"

namespace lsim::plan {
namespace {

// Constantes alignées sur `lsim.plan.RECEIVE_DELAY1_US` et `trace_events.RX1_WINDOW_NS`.
constexpr std::int64_t kReceiveDelay1Ns = 1'000'000'000;
constexpr std::int64_t kRx1WindowNs = 1'000'000'000;
// RX2 s'ouvre une seconde après RX1 : RP002 §2.3, RECEIVE_DELAY2 = RECEIVE_DELAY1 + 1 s.
constexpr std::int64_t kReceiveDelay2Ns = 2'000'000'000;
constexpr std::int64_t kRx2WindowNs = 1'000'000'000;
// Frontière de purge : toute ouverture réelle lui est strictement antérieure.
constexpr std::int64_t kInf = std::numeric_limits<std::int64_t>::max();
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

// Paramètres RX2 valides (jalon I0). `rx2_sf = 0` et `rx2_bw_hz = 0` sont des valeurs
// **admissibles** — aucun repli ; largeur reprise de RX1 — et non des erreurs : c'est l'absence
// de valeur, documentée dans le contrat d'ABI.
bool valid_rx2(const DeviceRx2& r) {
    if (r.rx2_hz < 0) return false;
    if (r.rx2_sf != 0 && (r.rx2_sf < 7 || r.rx2_sf > 12)) return false;
    if (r.rx2_bw_hz != 0 && r.rx2_bw_hz != 125'000 && r.rx2_bw_hz != 250'000 &&
        r.rx2_bw_hz != 500'000) {
        return false;
    }
    return true;
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
    bool received = false;      // seuil RX1 (réévalué si la descente part en RX2, voir plus bas)
    double rssi_dl = 0.0;       // réciprocité, indépendant de la fenêtre
    bool device_missed = false;
    // Fenêtre de secours (I1). RX2 n'est ni RX1 ni une répétition : fréquence et débit régionaux
    // propres, donc temps d'antenne distinct — d'où `rx2_airtime_ns` calculé à part.
    std::int64_t rx2_hz = 0;
    std::uint8_t rx2_sf = 0;
    std::uint32_t rx2_bw_hz = 0;
    std::int64_t rx2_airtime_ns = 0;
    bool device_missed_rx2 = false;

    // Le repli RX2 est-il matériellement possible ? `rx2_sf == 0` : pas de fenêtre de secours.
    // `rx2_hz == 0` : aucune fréquence régionale — on ne peut pas émettre sans fréquence, et la
    // deviner serait inventer une valeur réglementaire.
    bool rx2_disponible() const { return rx2_sf != 0 && rx2_hz != 0; }
    std::int64_t t_open_rx2() const { return t_open + (kReceiveDelay2Ns - kReceiveDelay1Ns); }
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

namespace {

// Temps d'antenne d'un downlink au débit de la fenêtre RX2. Largeur non renseignée (0) : RX2
// reprend celle de RX1, comme le valideur `valid_rx2`.
lora::Status rx2_airtime_ns(const DeviceRadio& radio, const DeviceRx2& rx2,
                            std::uint32_t payload_bytes, std::int64_t& out_ns) {
    DeviceRadio r = radio;
    r.rx1_sf = rx2.rx2_sf;
    r.rx1_bw_hz = rx2.rx2_bw_hz != 0 ? rx2.rx2_bw_hz : radio.rx1_bw_hz;
    return downlink_airtime_ns(r, payload_bytes, out_ns);
}

}  // namespace

PlanStatus plan_downlinks(const std::vector<UplinkRecord>& uplinks,
                          const std::vector<DeviceRadio>& radios, const PlanOptions& options,
                          std::vector<Event>& events, std::vector<Interval>& busy) {
    // Jalon I0 : aucune fenêtre RX2, comportement inchangé.
    return plan_downlinks(uplinks, radios, options, nullptr, events, busy);
}

PlanStatus plan_downlinks(const std::vector<UplinkRecord>& uplinks,
                          const std::vector<DeviceRadio>& radios, const PlanOptions& options,
                          const std::vector<DeviceRx2>* rx2, std::vector<Event>& events,
                          std::vector<Interval>& busy) {
    events.clear();
    busy.clear();
    if (rx2 != nullptr && rx2->size() != radios.size()) return PlanStatus::InvalidInput;
    if (rx2 != nullptr) {
        for (const DeviceRx2& r : *rx2) {
            if (!valid_rx2(r)) return PlanStatus::InvalidRadio;
        }
    }
    // Jalon I0 : RX2 est transporté et validé, puis **écarté** — aucun repli n'est produit.
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
        job.rssi_dl = rssi_dl;
        const std::int64_t nxt = next_start[i];
        job.device_missed = nxt != kNone && nxt < job.t_open + kRx1WindowNs;
        // Fenêtre de secours. Le repli est **opt-in** : il n'existe que si l'appelant a fourni une
        // table RX2 (enveloppe v2). Sans elle, rien n'est calculé et le comportement est celui
        // d'avant I1. Le temps d'antenne RX2 n'est calculé que si le repli est matériellement
        // possible, pour ne pas payer un calcul inutile quand il n'y a rien à émettre.
        if (rx2 != nullptr) {
            const DeviceRx2& r2 = (*rx2)[r.device];
            job.rx2_hz = r2.rx2_hz;
            job.rx2_sf = r2.rx2_sf;
            job.rx2_bw_hz = r2.rx2_bw_hz;
            if (job.rx2_disponible() &&
                rx2_airtime_ns(radio, r2, base, job.rx2_airtime_ns) != lora::Status::Ok) {
                return PlanStatus::InvalidRadio;
            }
            job.device_missed_rx2 = nxt != kNone && nxt < job.t_open_rx2() + kRx2WindowNs;
        }
        job_of[i] = static_cast<std::int64_t>(jobs.size());
        jobs.push_back(job);
    }

    // Planification passerelle (`_schedule_gateway`) : un émetteur, file chronologique.
    //
    // Sans table RX2, l'algorithme est celui d'avant I1 : les jobs sont triés par `t_open` (ordre
    // stable, donc ordre de la trace à `t_open` égal) et placés à `max(t_open, occupé_jusqu'à)`.
    //
    // Avec table RX2, la file devient un **tas** : la fenêtre de secours naît de l'échec de la
    // RX1 et porte sa propre ouverture (`t_open + 1 s`), qui peut être postérieure à celle
    // d'autres jobs. La traiter au même endroit que la RX1 placerait la descente trop tôt. C'est
    // ce que fait l'arbitre Python (`GatewayArbiter`, tas sur `ready_ns`) et l'on s'y aligne.
    std::vector<std::int64_t> starts(jobs.size(), kNone);
    std::vector<std::uint8_t> en_rx2(jobs.size(), 0);
    bool any_busy = false;
    std::int64_t busy_until = 0;

    if (rx2 == nullptr) {
        std::vector<std::size_t> order(jobs.size());
        for (std::size_t k = 0; k < order.size(); ++k) order[k] = k;
        std::stable_sort(order.begin(), order.end(), [&jobs](std::size_t a, std::size_t b) {
            return jobs[a].t_open < jobs[b].t_open;
        });
        for (std::size_t k : order) {
            const Job& job = jobs[k];
            const std::int64_t start = any_busy ? std::max(job.t_open, busy_until) : job.t_open;
            if (start - job.t_open >= kRx1WindowNs) continue;  // indisponible dans la RX1
            starts[k] = start;
            busy_until = start + job.airtime_ns;
            any_busy = true;
            busy.push_back(Interval{start, busy_until});
        }
    } else {
        // (ouverture, phase, indice) : la phase départage à ouverture égale — une RX2 naît après
        // toutes les RX1 déjà déposées, donc elle passe après elles. Même ordre que le tas Python,
        // dont la clé est (ready_ns, -priorité, ticket) avec des tickets croissants.
        struct Essai {
            std::int64_t pret;
            int phase;
            std::size_t index;
        };
        struct PlusTot {
            bool operator()(const Essai& a, const Essai& b) const {
                if (a.pret != b.pret) return a.pret > b.pret;
                if (a.phase != b.phase) return a.phase > b.phase;
                return a.index > b.index;
            }
        };
        std::priority_queue<Essai, std::vector<Essai>, PlusTot> file;
        for (std::size_t k = 0; k < jobs.size(); ++k) {
            file.push(Essai{jobs[k].t_open, 0, k});
        }
        while (!file.empty()) {
            const Essai e = file.top();
            file.pop();
            Job& job = jobs[e.index];
            if (e.phase == 0) {
                const std::int64_t start = any_busy ? std::max(job.t_open, busy_until) : job.t_open;
                if (start - job.t_open >= kRx1WindowNs) {
                    // RX1 perdue : seconde fenêtre, une seule fois, avec ses propres paramètres.
                    // Le repli est opt-in et n'opère que si la fenêtre RX2 est renseignée.
                    if (options.rx2_fallback && job.rx2_disponible()) {
                        file.push(Essai{job.t_open_rx2(), 1, e.index});
                    }
                    continue;
                }
                starts[e.index] = start;
                busy_until = start + job.airtime_ns;
                any_busy = true;
                busy.push_back(Interval{start, busy_until});
            } else {
                // Repli RX2. Le temps d'antenne est celui de RX2, pas celui de RX1 : au SF12, la
                // même trame occupe l'émetteur une vingtaine de fois plus longtemps.
                const std::int64_t ouverture = job.t_open_rx2();
                const std::int64_t start = any_busy ? std::max(ouverture, busy_until) : ouverture;
                if (start - ouverture >= kRx2WindowNs) continue;  // indisponible dans la RX2 aussi
                starts[e.index] = start;
                en_rx2[e.index] = 1;
                busy_until = start + job.rx2_airtime_ns;
                any_busy = true;
                busy.push_back(Interval{start, busy_until});
            }
        }
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
        // Fenêtre réellement émise : la fréquence du saut descendant est celle de cette fenêtre.
        // Une descente repliée en RX2 n'est pas sur la même fréquence — la rapporter en RX1
        // serait faux, et trompeur pour le rapport cyclique.
        const bool rx2_emise = en_rx2[static_cast<std::size_t>(k)] != 0;
        const std::int64_t freq_dl = rx2_emise ? job.rx2_hz : job.rx1_hz;
        const bool manquee = rx2_emise ? job.device_missed_rx2 : job.device_missed;
        // Sensibilité de la fenêtre **réellement émise**. Le seuil dépend du débit de cette
        // fenêtre, et RX2 n'a pas celui de RX1 : au SF12BW125 il est meilleur d'une quinzaine de
        // dB qu'au SF7BW125. Seuiller une descente RX2 avec RX1 la déclarerait perdue alors que
        // le dispositif l'entend. Les deux moteurs commettaient la même erreur : la parité ne la
        // voyait pas.
        bool recu = job.received;
        if (rx2_emise && job.rx2_disponible()) {
            double sens_rx2 = 0.0;
            const std::uint32_t bw = job.rx2_bw_hz != 0 ? job.rx2_bw_hz
                                                        : radios[job.device].rx1_bw_hz;
            if (lora::receiver_sensitivity_dbm(job.rx2_sf, static_cast<lora::Bandwidth>(bw),
                                               sens_rx2) != lora::Status::Ok) {
                return PlanStatus::InvalidRadio;
            }
            recu = job.rssi_dl >= sens_rx2 + options.device_rx_offset_db;
        }
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
            hop.freq_hz = freq_dl;
            ev.ev.hops.push_back(hop);
        } else if (manquee) {
            ev.ev.t_ns = job.t_open;
            ev.ev.kind = EventKind::RxWindowMissed;
            ev.ev.outcome = Outcome::DeviceTransmitting;
            Hop hop;
            hop.dir = HopDir::GwToDev;
            hop.outcome = Outcome::NotListened;
            hop.t_ns = start;
            hop.freq_hz = freq_dl;
            ev.ev.hops.push_back(hop);
        } else {
            ev.ev.t_ns = start;
            ev.ev.kind = job.kind;
            ev.ev.outcome = recu ? job.content : Outcome::LostSensitivity;
            Hop hop;
            hop.dir = HopDir::GwToDev;
            hop.outcome = recu ? Outcome::Delivered : Outcome::LostSensitivity;
            hop.t_ns = start;
            hop.freq_hz = freq_dl;
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
    : DownlinkScheduler(radios, options, nullptr) {}

DownlinkScheduler::DownlinkScheduler(const std::vector<DeviceRadio>& radios, const PlanOptions& options,
                                     const std::vector<DeviceRx2>* rx2)
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
    if (rx2 != nullptr) {
        // Le comptage doit être annoncé par l'appelant : `rx2_count` côté C. Un tableau de
        // longueur différente est une erreur d'appel, pas une entrée à tronquer.
        if (rx2->size() != radios.size()) {
            status_ = PlanStatus::InvalidInput;
            return;
        }
        for (const DeviceRx2& r : *rx2) {
            if (!valid_rx2(r)) {
                status_ = PlanStatus::InvalidRadio;
                return;
            }
        }
        rx2_ = *rx2;
    }
    // Durées de trame : calculées à la première utilisation (comme `plan_downlinks`, une erreur
    // n'est signalée que si une descente est réellement planifiée).
    radios_ = radios;
}

std::vector<Interval> DownlinkScheduler::on_received(std::uint32_t device, std::int64_t end_ns) {
    // Sans RX2 explicite, on reprend celui fourni à la construction (ou « aucun »).
    return on_received(device, end_ns, rx2_.empty() ? DeviceRx2{} : rx2_[device]);
}

std::vector<Interval> DownlinkScheduler::on_received(std::uint32_t device, std::int64_t end_ns,
                                                     const DeviceRx2& rx2) {
    std::vector<Interval> poses;
    if (status_ != PlanStatus::Ok) return poses;
    if (!valid_rx2(rx2)) {
        status_ = PlanStatus::InvalidRadio;
        return poses;
    }
    ++accepted_[device];
    const bool queued = options_.downlink_every > 0 && accepted_[device] % options_.downlink_every == 0;
    std::uint32_t base = 0;
    if (queued) {
        base = kDataFrameOverheadBytes + options_.downlink_payload_bytes;
    } else if (options_.confirmed_uplinks) {
        base = kAckFrameBytes;
    } else {
        return poses;   // aucune réponse attendue
    }

    // Dépôt de la tentative RX1 de cette montante.
    Essai nu;
    nu.pret = end_ns + kReceiveDelay1Ns;
    nu.pret_rx2 = end_ns + kReceiveDelay2Ns;
    nu.phase = 0;
    nu.device = device;
    nu.base = base;
    nu.queued = queued;
    nu.ordre = ordre_++;
    nu.rx2 = rx2;
    pendantes_.push_back(nu);

    // Frontier : une montante ultérieure finit au plus tôt à `end_ns`, donc sa RX1 ouvrira au
    // plus tôt à `nu.pret` et sa RX2 une seconde plus tard. Tout ce qui est en attente à une
    // ouverture strictement antérieure — ou égale, en RX1, car la phase départage — peut donc
    // être placé maintenant : plus rien ne peut s'intercaler avant.
    return placer(nu.pret);
}

std::vector<Interval> DownlinkScheduler::drain() { return placer(kInf); }

std::vector<Interval> DownlinkScheduler::placer(std::int64_t frontiere) {
    std::vector<Interval> poses;
    while (!pendantes_.empty()) {
        auto it = std::min_element(pendantes_.begin(), pendantes_.end(), plus_tot);
        const bool avant = (it->pret != frontiere) ? (it->pret < frontiere) : (it->phase == 0);
        if (!avant) break;  // cette tentative attend une montante ultérieure

        const Essai e = *it;
        pendantes_.erase(it);

        std::int64_t& air_e = e.queued ? data_air_[e.device] : ack_air_[e.device];
        std::int64_t air_utile = 0;
        if (e.phase == 0) {
            if (air_e == 0 &&
                downlink_airtime_ns(radios_[e.device], e.base, air_e) != lora::Status::Ok) {
                status_ = PlanStatus::InvalidRadio;
                return poses;
            }
            air_utile = air_e;
        } else if (rx2_airtime_ns(radios_[e.device], e.rx2, e.base, air_utile) !=
                   lora::Status::Ok) {
            status_ = PlanStatus::InvalidRadio;
            return poses;
        }

        const std::int64_t start = any_busy_ ? std::max(e.pret, busy_until_) : e.pret;
        const std::int64_t fenetre = (e.phase == 0) ? kRx1WindowNs : kRx2WindowNs;
        if (start - e.pret >= fenetre) {
            // Fenêtre manquée. En RX1, la seconde fenêtre entre dans la file à son propre
            // instant d'ouverture — pas maintenant : des descentes encore en attente peuvent
            // être plus précoces qu'elle.
            if (e.phase == 0 && options_.rx2_fallback && e.rx2.rx2_sf != 0 && e.rx2.rx2_hz != 0) {
                Essai secours = e;
                secours.pret = e.pret_rx2;
                secours.phase = 1;
                secours.ordre = ordre_++;
                pendantes_.push_back(secours);
            }
            continue;
        }
        any_busy_ = true;
        busy_until_ = start + air_utile;
        poses.push_back(Interval{start, busy_until_});
    }
    return poses;
}

}  // namespace lsim::plan
