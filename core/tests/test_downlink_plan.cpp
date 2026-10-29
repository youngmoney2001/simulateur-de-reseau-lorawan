// SPDX-License-Identifier: Apache-2.0
// Planification des descentes (S0) : cas élémentaires, RX1 manquée, capacité et options invalides.
#include <cstdint>
#include <vector>

#include "check.hpp"
#include "lsim/c_api.h"
#include "lsim/downlink_plan.hpp"

using namespace lsim::plan;

namespace {

constexpr std::int64_t kS = 1'000'000'000;

DeviceRadio radio_sf7() {
    DeviceRadio r;
    r.freq_hz = 868'100'000;
    r.rx1_hz = 868'100'000;
    r.rx1_sf = 7;
    r.rx1_bw_hz = 125'000;
    r.tx_power_dbm = 14.0;
    return r;
}

UplinkRecord up(std::uint32_t dev, std::int64_t start, std::int64_t air, UplinkOutcome o,
                double rssi = -60.0) {
    UplinkRecord u;
    u.device = dev;
    u.start_ns = start;
    u.end_ns = start + air;
    u.spreading_factor = 7;
    u.outcome = o;
    u.rssi_dbm = rssi;
    return u;
}

}  // namespace

void run_downlink_plan_tests() {
    // 1. Uplink reçu, confirmé : un ACK à fin + 1 s, sur la passerelle, livré au dispositif.
    {
        PlanOptions o;
        o.confirmed_uplinks = true;
        std::int64_t air_dl = 0;
        CHECK_EQ(downlink_airtime_ns(radio_sf7(), 12, air_dl), lsim::lora::Status::Ok);
        std::vector<Event> ev;
        std::vector<Interval> busy;
        const std::vector<UplinkRecord> ups{up(0, 0, 50'000'000, UplinkOutcome::Received)};
        CHECK_EQ(plan_downlinks(ups, {radio_sf7()}, o, ev, busy), PlanStatus::Ok);
        CHECK_EQ(ev.size(), 2u);
        CHECK_EQ(ev[0].kind, EventKind::Uplink);
        CHECK_EQ(ev[1].kind, EventKind::Ack);
        CHECK_EQ(ev[1].t_ns, 50'000'000 + kS);
        CHECK_EQ(ev[1].outcome, Outcome::AckOnly);
        CHECK_EQ(ev[1].hops.size(), 1u);
        CHECK_EQ(ev[1].hops[0].dir, HopDir::GwToDev);
        CHECK_EQ(ev[1].hops[0].outcome, Outcome::Delivered);
        CHECK_EQ(busy.size(), 1u);
        CHECK_EQ(busy[0].start_ns, 50'000'000 + kS);
        CHECK_EQ(busy[0].end_ns - busy[0].start_ns, air_dl);
    }
    // 2. Uplink perdu : aucun événement de réponse ni occupation.
    {
        PlanOptions o;
        o.confirmed_uplinks = true;
        std::vector<Event> ev;
        std::vector<Interval> busy;
        const std::vector<UplinkRecord> ups{up(0, 0, 50'000'000, UplinkOutcome::LostCollision)};
        CHECK_EQ(plan_downlinks(ups, {radio_sf7()}, o, ev, busy), PlanStatus::Ok);
        CHECK_EQ(ev.size(), 1u);
        CHECK_EQ(ev[0].outcome, Outcome::LostCollision);
        CHECK_EQ(ev[0].hops[0].outcome, Outcome::LostCollision);
        CHECK_EQ(busy.size(), 0u);
    }
    // 3. Le dispositif émet à nouveau pendant RX1 : fenêtre manquée, pas de descente.
    {
        PlanOptions o;
        o.confirmed_uplinks = true;
        std::vector<Event> ev;
        std::vector<Interval> busy;
        const std::vector<UplinkRecord> ups{
            up(0, 0, 50'000'000, UplinkOutcome::Received),
            up(0, 50'000'000 + kS / 2, 50'000'000, UplinkOutcome::LostSensitivity),
        };
        CHECK_EQ(plan_downlinks(ups, {radio_sf7()}, o, ev, busy), PlanStatus::Ok);
        bool missed = false;
        for (const Event& e : ev) {
            if (e.kind == EventKind::RxWindowMissed) {
                missed = e.outcome == Outcome::DeviceTransmitting && e.t_ns == 50'000'000 + kS;
            }
        }
        CHECK_TRUE(missed);
        // Comme `_schedule_gateway` côté Python : la passerelle réserve son émission même si le
        // dispositif ne l'écoute pas (occupation non libérée par device_missed).
        CHECK_EQ(busy.size(), 1u);
    }
    // 4. Descente de données toutes les 2 réceptions, confirmée : Downlink / DataAck.
    {
        PlanOptions o;
        o.confirmed_uplinks = true;
        o.downlink_every = 2;
        o.downlink_payload_bytes = 10;
        std::vector<Event> ev;
        std::vector<Interval> busy;
        const std::vector<UplinkRecord> ups{
            up(0, 0, 50'000'000, UplinkOutcome::Received),
            up(0, 600 * kS, 50'000'000, UplinkOutcome::Received),
        };
        CHECK_EQ(plan_downlinks(ups, {radio_sf7()}, o, ev, busy), PlanStatus::Ok);
        CHECK_EQ(busy.size(), 2u);
        bool data = false;
        for (const Event& e : ev) {
            if (e.kind == EventKind::Downlink) data = e.outcome == Outcome::DataAck;
        }
        CHECK_TRUE(data);
    }
    // 5. Options et entrées invalides.
    {
        PlanOptions o;
        o.downlink_payload_bytes = 243;
        std::vector<Event> ev;
        std::vector<Interval> busy;
        CHECK_EQ(plan_downlinks({}, {radio_sf7()}, o, ev, busy), PlanStatus::InvalidOptions);
        PlanOptions ok;
        const std::vector<UplinkRecord> bad{up(3, 0, 1, UplinkOutcome::Received)};
        CHECK_EQ(plan_downlinks(bad, {radio_sf7()}, ok, ev, busy), PlanStatus::InvalidInput);
        DeviceRadio r = radio_sf7();
        r.rx1_sf = 13;
        CHECK_EQ(plan_downlinks({}, {r}, ok, ev, busy), PlanStatus::InvalidRadio);
    }
    // 6. Frontière C : capacité insuffisante, puis taille requise dans *event_count.
    {
        const lsim_plan_uplink u{0, 0, 50'000'000, 7, 2, -60.0};
        const lsim_plan_device d{868'100'000, -1, 868'100'000, 14.0, 7, 125'000};
        lsim_plan_options o{};
        o.confirmed_uplinks = 1;
        lsim_plan_event events[1];
        lsim_interval busy[1];
        size_t n_ev = 0;
        size_t n_busy = 0;
        const int32_t st = lsim_plan_downlinks_v1(&u, 1, &d, 1, &o, events, 1, &n_ev, busy, 1, &n_busy);
        CHECK_EQ(st, LSIM_STATUS_PLAN_BASE + 4);
        CHECK_EQ(n_ev, 2u);
        CHECK_EQ(n_busy, 1u);
        lsim_plan_event big[4];
        lsim_interval bbig[4];
        CHECK_EQ(lsim_plan_downlinks_v1(&u, 1, &d, 1, &o, big, 4, &n_ev, bbig, 4, &n_busy), 0);
        CHECK_EQ(big[1].kind, 1);  // ACK
        CHECK_EQ(big[1].hop_count, 1);
    }
}
