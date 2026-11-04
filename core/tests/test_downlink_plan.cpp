// SPDX-License-Identifier: Apache-2.0
// Planification des descentes (S0) : cas élémentaires, RX1 manquée, capacité et options invalides.
// Planificateur incrémental (S1) : occupation égale à `plan_downlinks` quand les fins sont traitées dans l'ordre.
#include <algorithm>
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

// Jeu d'essai partagé par les tests de l'enveloppe v2 (jalon I0) : 8 montantes, 3 dispositifs,
// ACK et descentes de données. Mêmes durées que le cas 7, pour couvrir des ordres de fin variés.
struct PlanCase {
    std::vector<lsim_plan_uplink> ups;
    std::vector<lsim_plan_device> devs;
    lsim_plan_options opts;
};

PlanCase make_plan_case() {
    PlanCase c;
    const std::int64_t airs[] = {300'000'000, 20'000'000, 150'000'000, 20'000'000,
                                 400'000'000, 40'000'000, 20'000'000, 90'000'000};
    std::int64_t t = 0;
    for (std::uint32_t k = 0; k < 8; ++k) {
        lsim_plan_uplink u{};
        u.device_index = k % 3;
        u.start_ns = t;
        u.end_ns = t + airs[k];
        u.spreading_factor = 7;
        u.outcome = (k % 4 == 3) ? static_cast<std::uint8_t>(1) : static_cast<std::uint8_t>(2);
        u.rssi_dbm = -60.0;
        c.ups.push_back(u);
        t += 120'000'000;
    }
    for (int k = 0; k < 3; ++k) {
        lsim_plan_device d{};
        d.freq_hz = 868'100'000;
        d.dr = -1;
        d.rx1_hz = 868'100'000;
        d.tx_power_dbm = 14.0;
        d.rx1_sf = 7;
        d.rx1_bw_hz = 125'000;
        c.devs.push_back(d);
    }
    c.opts = lsim_plan_options{};
    c.opts.confirmed_uplinks = 1;
    c.opts.downlink_every = 2;
    c.opts.downlink_payload_bytes = 40;
    c.opts.gateway_tx_power_dbm = 14.0;
    c.opts.device_antenna_gain_dbi = 0.0;
    c.opts.device_rx_offset_db = 0.0;
    return c;
}

// Comparaison champ par champ de deux sorties de planification (parité v1 / v2).
void check_events_equal(const lsim_plan_event& a, const lsim_plan_event& b) {
    CHECK_EQ(a.t_ns, b.t_ns);
    CHECK_EQ(a.device_index, b.device_index);
    CHECK_EQ(static_cast<int>(a.kind), static_cast<int>(b.kind));
    CHECK_EQ(static_cast<int>(a.outcome), static_cast<int>(b.outcome));
    CHECK_EQ(static_cast<int>(a.hop_count), static_cast<int>(b.hop_count));
    for (int h = 0; h < 2 && h < static_cast<int>(a.hop_count); ++h) {
        CHECK_EQ(static_cast<int>(a.hops[h].dir), static_cast<int>(b.hops[h].dir));
        CHECK_EQ(static_cast<int>(a.hops[h].outcome), static_cast<int>(b.hops[h].outcome));
        CHECK_EQ(static_cast<int>(a.hops[h].has_rssi), static_cast<int>(b.hops[h].has_rssi));
        CHECK_EQ(a.hops[h].t_ns, b.hops[h].t_ns);
        CHECK_EQ(a.hops[h].freq_hz, b.hops[h].freq_hz);
        CHECK_EQ(a.hops[h].dr, b.hops[h].dr);
        CHECK_NEAR(a.hops[h].rssi_dbm, b.hops[h].rssi_dbm, 0.0);
    }
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
    // 7. Planificateur incrémental (S1) : mêmes intervalles que `plan_downlinks`, fins traitées
    //    dans l'ordre. Les débuts et les fins ne suivent pas le même ordre (trames de durées variées).
    {
        PlanOptions o;
        o.confirmed_uplinks = true;
        o.downlink_every = 2;
        o.downlink_payload_bytes = 40;
        std::vector<UplinkRecord> ups;
        const std::int64_t airs[] = {300'000'000, 20'000'000, 150'000'000, 20'000'000, 400'000'000,
                                     40'000'000, 20'000'000, 90'000'000};
        std::int64_t t = 0;
        for (std::uint32_t k = 0; k < 8; ++k) {
            const std::uint32_t dev = k % 3;
            ups.push_back(up(dev, t, airs[k], k % 4 == 3 ? UplinkOutcome::LostCollision : UplinkOutcome::Received));
            t += 120'000'000;
        }
        const std::vector<DeviceRadio> radios{radio_sf7(), radio_sf7(), radio_sf7()};
        std::vector<Event> ev;
        std::vector<Interval> ref;
        CHECK_EQ(plan_downlinks(ups, radios, o, ev, ref), PlanStatus::Ok);

        DownlinkScheduler sched(radios, o);
        CHECK_EQ(sched.status(), PlanStatus::Ok);
        std::vector<std::size_t> by_end(ups.size());
        for (std::size_t k = 0; k < by_end.size(); ++k) by_end[k] = k;
        std::stable_sort(by_end.begin(), by_end.end(), [&ups](std::size_t a, std::size_t b) {
            return ups[a].end_ns < ups[b].end_ns;
        });
        std::vector<Interval> got;
        for (std::size_t k : by_end) {
            if (ups[k].outcome != UplinkOutcome::Received) continue;
            for (const Interval& iv : sched.on_received(ups[k].device, ups[k].end_ns)) {
                got.push_back(iv);
            }
        }
        for (const Interval& iv : sched.drain()) got.push_back(iv);
        CHECK_EQ(got.size(), ref.size());
        std::sort(ref.begin(), ref.end(), [](const Interval& a, const Interval& b) {
            return a.start_ns < b.start_ns;
        });
        for (std::size_t k = 0; k < std::min(got.size(), ref.size()); ++k) {
            CHECK_EQ(got[k].start_ns, ref[k].start_ns);
            CHECK_EQ(got[k].end_ns, ref[k].end_ns);
        }
        // Bande RX1 invalide : code InvalidRadio précis, dès la construction (sans trame reçue).
        DeviceRadio bad_bw = radio_sf7();
        bad_bw.rx1_bw_hz = 100'000;
        CHECK_EQ(DownlinkScheduler({bad_bw}, o).status(), PlanStatus::InvalidRadio);
        CHECK_EQ(plan_downlinks({}, {bad_bw}, o, ev, ref), PlanStatus::InvalidRadio);
        const lsim_plan_device cbad{868'100'000, -1, 868'100'000, 14.0, 7, 100'000};
        lsim_plan_options copt{};
        lsim_plan_event cev[1];
        lsim_interval cbusy[1];
        size_t cn_ev = 0;
        size_t cn_busy = 0;
        CHECK_EQ(lsim_plan_downlinks_v1(nullptr, 0, &cbad, 1, &copt, cev, 1, &cn_ev, cbusy, 1, &cn_busy),
                 LSIM_STATUS_PLAN_BASE + 2);
        // Options invalides : signalées dès la construction.
        PlanOptions bad;
        bad.downlink_payload_bytes = 243;
        CHECK_EQ(DownlinkScheduler(radios, bad).status(), PlanStatus::InvalidOptions);
    }

    // ------------------------------------------- I0 : enveloppe versionnée de la planification (v2)
    // 8. Parité stricte v1 / v2. `rx2` nul reproduit la v1 au bit près. `rx2` renseigné aussi :
    //    le repli RX2 est opt-in, il n'est pas implémenté en I0, donc aucun repli n'apparaît.
    {
        const PlanCase c = make_plan_case();
        const std::size_t cap = 32;
        std::vector<lsim_plan_event> ev1(cap), ev2(cap), ev3(cap);
        std::vector<lsim_interval> b1(cap), b2(cap), b3(cap);
        size_t n1 = 0, nb1 = 0, n2 = 0, nb2 = 0, n3 = 0, nb3 = 0;

        const int32_t r1 = lsim_plan_downlinks_v1(c.ups.data(), c.ups.size(), c.devs.data(),
                                                  c.devs.size(), &c.opts, ev1.data(), cap, &n1,
                                                  b1.data(), cap, &nb1);
        CHECK_EQ(r1, 0);
        CHECK_TRUE(n1 > 0);
        CHECK_TRUE(nb1 > 0);  // le scénario produit bien des événements et de l'occupation

        const auto run_v2 = [&](const lsim_plan_device_rx2* rx2, lsim_plan_event* ev, size_t* n,
                                lsim_interval* bu, size_t* nb) {
            lsim_plan_downlinks_v2_args a{};
            a.struct_size = sizeof(a);
            a.abi_version = LSIM_PLAN_DOWNLINKS_V2_ABI_VERSION;
            a.uplinks = c.ups.data();
            a.uplink_count = c.ups.size();
            a.devices = c.devs.data();
            a.device_count = c.devs.size();
            a.options = &c.opts;
            a.rx2 = rx2;
            a.events = ev;
            a.event_capacity = cap;
            a.event_count = n;
            a.busy = bu;
            a.busy_capacity = cap;
            a.busy_count = nb;
            a.rx2_count = (rx2 == nullptr) ? 0u : c.devs.size();
            return lsim_plan_downlinks_v2(&a);
        };

        // 8a. rx2 nul : identique à la v1.
        const int32_t r2 = run_v2(nullptr, ev2.data(), &n2, b2.data(), &nb2);
        CHECK_EQ(r2, r1);
        CHECK_EQ(n2, n1);
        CHECK_EQ(nb2, nb1);
        for (size_t k = 0; k < n1; ++k) check_events_equal(ev2[k], ev1[k]);
        for (size_t k = 0; k < nb1; ++k) {
            CHECK_EQ(b2[k].start_ns, b1[k].start_ns);
            CHECK_EQ(b2[k].end_ns, b1[k].end_ns);
        }

        // 8b. rx2 renseigné (SF 12, fréquence et largeur valides) : toujours aucun repli RX2.
        std::vector<lsim_plan_device_rx2> rx2(c.devs.size());
        for (auto& r : rx2) {
            r.rx2_hz = 869'525'000;
            r.rx2_sf = 12;
            r.rx2_bw_hz = 125'000;
        }
        const int32_t r3 = run_v2(rx2.data(), ev3.data(), &n3, b3.data(), &nb3);
        CHECK_EQ(r3, r1);
        CHECK_EQ(n3, n1);
        CHECK_EQ(nb3, nb1);
        for (size_t k = 0; k < n1; ++k) check_events_equal(ev3[k], ev1[k]);
        for (size_t k = 0; k < nb1; ++k) {
            CHECK_EQ(b3[k].start_ns, b1[k].start_ns);
            CHECK_EQ(b3[k].end_ns, b1[k].end_ns);
        }
    }

    // 9. Enveloppe : pointeur nul, taille et version inconnue. Refus explicite, pas d'accès mémoire.
    {
        const PlanCase c = make_plan_case();
        lsim_plan_event ev[4];
        lsim_interval bu[4];
        size_t n = 0, nb = 0;

        const auto base = [&]() {
            lsim_plan_downlinks_v2_args a{};
            a.struct_size = sizeof(a);
            a.abi_version = LSIM_PLAN_DOWNLINKS_V2_ABI_VERSION;
            a.uplinks = c.ups.data();
            a.uplink_count = c.ups.size();
            a.devices = c.devs.data();
            a.device_count = c.devs.size();
            a.options = &c.opts;
            a.events = ev;
            a.event_capacity = 4;
            a.event_count = &n;
            a.busy = bu;
            a.busy_capacity = 4;
            a.busy_count = &nb;
            return a;
        };

        CHECK_EQ(lsim_plan_downlinks_v2(nullptr), LSIM_STATUS_PLAN_BASE + 1);
        {
            lsim_plan_downlinks_v2_args a = base();
            a.struct_size = sizeof(a) - 8u;
            CHECK_EQ(lsim_plan_downlinks_v2(&a), LSIM_STATUS_PLAN_BASE + 1);
        }
        {
            lsim_plan_downlinks_v2_args a = base();
            a.abi_version = LSIM_PLAN_DOWNLINKS_V2_ABI_VERSION + 1u;
            CHECK_EQ(lsim_plan_downlinks_v2(&a), LSIM_STATUS_PLAN_BASE + 1);
        }
        {
            lsim_plan_downlinks_v2_args a = base();
            a.options = nullptr;
            CHECK_EQ(lsim_plan_downlinks_v2(&a), LSIM_STATUS_PLAN_BASE + 1);
        }
        {
            lsim_plan_downlinks_v2_args a = base();
            a.event_count = nullptr;
            CHECK_EQ(lsim_plan_downlinks_v2(&a), LSIM_STATUS_PLAN_BASE + 1);
        }
        {
            lsim_plan_downlinks_v2_args a = base();
            a.busy_count = nullptr;
            CHECK_EQ(lsim_plan_downlinks_v2(&a), LSIM_STATUS_PLAN_BASE + 1);
        }
        {
            lsim_plan_downlinks_v2_args a = base();
            a.uplinks = nullptr;  // uplink_count > 0
            CHECK_EQ(lsim_plan_downlinks_v2(&a), LSIM_STATUS_PLAN_BASE + 1);
        }
        {
            lsim_plan_downlinks_v2_args a = base();
            a.devices = nullptr;  // device_count > 0
            CHECK_EQ(lsim_plan_downlinks_v2(&a), LSIM_STATUS_PLAN_BASE + 1);
        }
        // `rx2` non nul : sa longueur doit être annoncée et cohérente, sinon refus — jamais de
        // lecture au-delà du tableau fourni.
        {
            lsim_plan_device_rx2 un{};
            lsim_plan_downlinks_v2_args a = base();
            a.rx2 = &un;
            a.rx2_count = 0;  // annoncé vide alors que device_count vaut 3
            CHECK_EQ(lsim_plan_downlinks_v2(&a), LSIM_STATUS_PLAN_BASE + 1);
        }
        {
            lsim_plan_device_rx2 un{};
            lsim_plan_downlinks_v2_args a = base();
            a.rx2 = &un;
            a.rx2_count = 99;  // annoncé plus long que device_count
            CHECK_EQ(lsim_plan_downlinks_v2(&a), LSIM_STATUS_PLAN_BASE + 1);
        }
        // Capacité insuffisante : comptes requis renvoyés, statut dédié (comme la v1).
        {
            lsim_plan_downlinks_v2_args a = base();
            const int32_t r = lsim_plan_downlinks_v2(&a);
            CHECK_EQ(r, LSIM_STATUS_PLAN_BASE + 4);
            CHECK_TRUE(n > 4 || nb > 4);
        }
    }

    // 10. Paramètres RX2 : invalides refusés (InvalidRadio), valeurs « absentes » admises.
    {
        const PlanCase c = make_plan_case();
        const std::size_t cap = 32;
        std::vector<lsim_plan_event> ev(cap);
        std::vector<lsim_interval> bu(cap);
        size_t n = 0, nb = 0;

        const auto run = [&](const std::vector<lsim_plan_device_rx2>& rx2) {
            lsim_plan_downlinks_v2_args a{};
            a.struct_size = sizeof(a);
            a.abi_version = LSIM_PLAN_DOWNLINKS_V2_ABI_VERSION;
            a.uplinks = c.ups.data();
            a.uplink_count = c.ups.size();
            a.devices = c.devs.data();
            a.device_count = c.devs.size();
            a.options = &c.opts;
            a.rx2 = rx2.data();
            a.events = ev.data();
            a.event_capacity = cap;
            a.event_count = &n;
            a.busy = bu.data();
            a.busy_capacity = cap;
            a.busy_count = &nb;
            a.rx2_count = rx2.size();
            return lsim_plan_downlinks_v2(&a);
        };

        std::vector<lsim_plan_device_rx2> ok(c.devs.size());
        for (auto& r : ok) {
            r.rx2_hz = 869'525'000;
            r.rx2_sf = 12;
            r.rx2_bw_hz = 125'000;
        }
        CHECK_EQ(run(ok), 0);

        const auto variant = [&](void (*f)(lsim_plan_device_rx2&)) {
            std::vector<lsim_plan_device_rx2> v = ok;
            f(v[1]);
            return run(v);
        };
        CHECK_EQ(variant([](lsim_plan_device_rx2& r) { r.rx2_sf = 6; }), LSIM_STATUS_PLAN_BASE + 2);
        CHECK_EQ(variant([](lsim_plan_device_rx2& r) { r.rx2_sf = 13; }), LSIM_STATUS_PLAN_BASE + 2);
        CHECK_EQ(variant([](lsim_plan_device_rx2& r) { r.rx2_bw_hz = 100'000; }),
                 LSIM_STATUS_PLAN_BASE + 2);
        CHECK_EQ(variant([](lsim_plan_device_rx2& r) { r.rx2_hz = -1; }), LSIM_STATUS_PLAN_BASE + 2);
        // Valeurs admises : SF nul (aucun repli), fréquence nulle (non renseignée), largeur nulle
        // (reprend rx1_bw_hz) et les trois largeurs valides.
        CHECK_EQ(variant([](lsim_plan_device_rx2& r) { r.rx2_sf = 0; }), 0);
        CHECK_EQ(variant([](lsim_plan_device_rx2& r) { r.rx2_hz = 0; }), 0);
        CHECK_EQ(variant([](lsim_plan_device_rx2& r) { r.rx2_bw_hz = 0; }), 0);
        CHECK_EQ(variant([](lsim_plan_device_rx2& r) { r.rx2_bw_hz = 500'000; }), 0);
    }

    // 11. Surcharges C++ (I0, C2) : `nullptr` et valeurs par défaut reproduisent les signatures
    //     d'origine ; des RX2 renseignés ne changent rien au placement.
    {
        PlanOptions o;
        o.confirmed_uplinks = true;
        o.downlink_every = 2;
        o.downlink_payload_bytes = 40;
        const std::int64_t airs[] = {300'000'000, 20'000'000, 150'000'000, 20'000'000,
                                     400'000'000, 40'000'000, 20'000'000, 90'000'000};
        std::vector<UplinkRecord> ups;
        std::int64_t t = 0;
        for (std::uint32_t k = 0; k < 8; ++k) {
            ups.push_back(up(k % 3, t, airs[k],
                             k % 4 == 3 ? UplinkOutcome::LostCollision : UplinkOutcome::Received));
            t += 120'000'000;
        }
        const std::vector<DeviceRadio> radios{radio_sf7(), radio_sf7(), radio_sf7()};

        std::vector<Event> ev_a, ev_b;
        std::vector<Interval> bu_a, bu_b;
        CHECK_EQ(plan_downlinks(ups, radios, o, ev_a, bu_a), PlanStatus::Ok);
        CHECK_EQ(plan_downlinks(ups, radios, o, nullptr, ev_b, bu_b), PlanStatus::Ok);
        CHECK_EQ(ev_b.size(), ev_a.size());
        CHECK_EQ(bu_b.size(), bu_a.size());
        for (std::size_t k = 0; k < ev_a.size(); ++k) {
            CHECK_EQ(ev_b[k].t_ns, ev_a[k].t_ns);
            CHECK_EQ(static_cast<int>(ev_b[k].kind), static_cast<int>(ev_a[k].kind));
            CHECK_EQ(static_cast<int>(ev_b[k].outcome), static_cast<int>(ev_a[k].outcome));
            CHECK_EQ(ev_b[k].hops.size(), ev_a[k].hops.size());
        }
        for (std::size_t k = 0; k < bu_a.size(); ++k) {
            CHECK_EQ(bu_b[k].start_ns, bu_a[k].start_ns);
            CHECK_EQ(bu_b[k].end_ns, bu_a[k].end_ns);
        }
        // Comptage incohérent : InvalidInput.
        {
            std::vector<Event> ev_x;
            std::vector<Interval> bu_x;
            const std::vector<DeviceRx2> court(2);
            CHECK_EQ(plan_downlinks(ups, radios, o, &court, ev_x, bu_x), PlanStatus::InvalidInput);
        }

        // Planificateur incrémental : les deux formes du constructeur et les deux formes de
        // `on_received` donnent les mêmes intervalles, avec ou sans RX2.
        std::vector<std::size_t> by_end(ups.size());
        for (std::size_t k = 0; k < by_end.size(); ++k) by_end[k] = k;
        std::stable_sort(by_end.begin(), by_end.end(), [&ups](std::size_t a, std::size_t b) {
            return ups[a].end_ns < ups[b].end_ns;
        });

        const auto parcours = [&](const std::vector<DeviceRx2>* rx2, bool trois_args) {
            DownlinkScheduler s(radios, o, rx2);
            if (s.status() != PlanStatus::Ok) return std::vector<Interval>{};
            std::vector<Interval> got;
            for (std::size_t k : by_end) {
                if (ups[k].outcome != UplinkOutcome::Received) continue;
                const std::vector<Interval> iv =
                    trois_args
                        ? s.on_received(ups[k].device, ups[k].end_ns,
                                        rx2 ? (*rx2)[ups[k].device] : DeviceRx2{})
                        : s.on_received(ups[k].device, ups[k].end_ns);
                for (const Interval& i : iv) got.push_back(i);
            }
            for (const Interval& i : s.drain()) got.push_back(i);
            return got;
        };

        std::vector<DeviceRx2> plein(3);
        for (auto& r : plein) {
            r.rx2_hz = 869'525'000;
            r.rx2_sf = 12;
            r.rx2_bw_hz = 125'000;
        }
        const std::vector<Interval> ref2 = parcours(nullptr, false);
        const std::vector<Interval> ref3 = parcours(nullptr, true);
        const std::vector<Interval> avec_rx2 = parcours(&plein, false);
        const std::vector<Interval> avec_rx2_3 = parcours(&plein, true);

        CHECK_TRUE(!ref2.empty());  // le scénario planifie bien des descentes
        CHECK_EQ(ref3.size(), ref2.size());
        CHECK_EQ(avec_rx2.size(), ref2.size());
        CHECK_EQ(avec_rx2_3.size(), ref2.size());
        for (std::size_t k = 0; k < ref2.size(); ++k) {
            CHECK_EQ(ref3[k].start_ns, ref2[k].start_ns);
            CHECK_EQ(ref3[k].end_ns, ref2[k].end_ns);
            CHECK_EQ(avec_rx2[k].start_ns, ref2[k].start_ns);
            CHECK_EQ(avec_rx2[k].end_ns, ref2[k].end_ns);
            CHECK_EQ(avec_rx2_3[k].start_ns, ref2[k].start_ns);
            CHECK_EQ(avec_rx2_3[k].end_ns, ref2[k].end_ns);
        }

        // RX2 invalide : refusé à la construction, et par la surcharge `on_received` à trois
        // arguments, qui fait passer le planificateur en InvalidRadio.
        std::vector<DeviceRx2> mauvais(3);
        mauvais[1].rx2_sf = 6;
        CHECK_EQ(DownlinkScheduler(radios, o, &mauvais).status(), PlanStatus::InvalidRadio);
        {
            DownlinkScheduler s(radios, o);
            CHECK_EQ(s.status(), PlanStatus::Ok);
            DeviceRx2 bad;
            bad.rx2_sf = 13;
            CHECK_TRUE(s.on_received(0, 1'000'000'000, bad).empty());
            CHECK_EQ(s.status(), PlanStatus::InvalidRadio);
        }
        // Comptage incohérent à la construction.
        {
            const std::vector<DeviceRx2> court(2);
            CHECK_EQ(DownlinkScheduler(radios, o, &court).status(), PlanStatus::InvalidInput);
        }
    }

    // ----------------------------------------------------------------- I1 : repli RX2 dans le cœur
    // 12. Jeu d'essai : deux ACK, le premier au SF12 (descente longue) qui occupe l'émetteur au-delà
    //     de la fenêtre RX1 du second. C'est le cas « RX1 refusée puis RX2 acceptée ».
    //     Sans repli, la seconde descente est perdue.
    {
        DeviceRadio gros = radio_sf7();
        gros.rx1_sf = 12;  // ACK long : l'émetteur est pris bien au-delà de la fenêtre du second
        const DeviceRadio petit = radio_sf7();
        const std::vector<DeviceRadio> radios{gros, petit};

        // Descente de données : 13 octets d'en-tête + 27 de charge = 40 octets. Au SF12 cela dure
        // environ 1,97 s — assez pour masquer la fenêtre RX1 du second dispositif, pas sa RX2.
        constexpr std::uint32_t kCharge = 27;
        constexpr std::uint32_t kTrame = 13 + kCharge;
        PlanOptions o;
        o.confirmed_uplinks = true;
        o.downlink_every = 1;   // une descente de données par uplink reçu
        o.downlink_payload_bytes = kCharge;
        o.gateway_tx_power_dbm = 27.0;

        // Le second uplink finit 0,49 s après le premier : sa RX1 ferme à 2,5 s, sa RX2 à 3,5 s.
        // La descente du premier (SF12) occupe l'émetteur de 1,01 s à 2,98 s : RX1 perdue, RX2
        // encore ouverte. C'est exactement le cas que le jalon doit traiter.
        const std::vector<UplinkRecord> ups{up(0, 0, 10'000'000, UplinkOutcome::Received),
                                            up(1, 490'000'000, 10'000'000, UplinkOutcome::Received)};
        // Temps d'antenne de référence, au débit de chaque fenêtre.
        std::int64_t air_rx1 = 0;
        std::int64_t air_rx2 = 0;
        CHECK_EQ(downlink_airtime_ns(petit, kTrame, air_rx1), lsim::lora::Status::Ok);
        DeviceRadio en_rx2 = petit;
        en_rx2.rx1_sf = 12;
        CHECK_EQ(downlink_airtime_ns(en_rx2, kTrame, air_rx2), lsim::lora::Status::Ok);
        CHECK_TRUE(air_rx2 > air_rx1);  // le repli coûte l'émetteur : c'est le point du jalon

        std::vector<DeviceRx2> rx2(2);
        rx2[0] = DeviceRx2{869'525'000, 12, 125'000};
        rx2[1] = DeviceRx2{869'525'000, 12, 125'000};

        // 12a. Sans repli (opt-in désactivé) : la seconde descente est perdue, une seule occupation.
        {
            std::vector<Event> ev;
            std::vector<Interval> bu;
            CHECK_EQ(plan_downlinks(ups, radios, o, &rx2, ev, bu), PlanStatus::Ok);
            CHECK_EQ(bu.size(), 1u);
            // Le second dispositif n'a rien reçu : fenêtre manquée.
            std::size_t manquees = 0;
            for (const Event& e : ev) {
                if (e.kind == EventKind::RxWindowMissed) ++manquees;
            }
            CHECK_EQ(manquees, 1u);
        }

        // 12b. Repli activé : la seconde descente part en RX2, après la fin de la première.
        {
            PlanOptions avec = o;
            avec.rx2_fallback = true;
            std::vector<Event> ev;
            std::vector<Interval> bu;
            CHECK_EQ(plan_downlinks(ups, radios, avec, &rx2, ev, bu), PlanStatus::Ok);
            CHECK_EQ(bu.size(), 2u);  // une seule émission par descente : aucun doublon RX1/RX2
            // Le repli s'ouvre une seconde après RX1 et démarre dès que l'émetteur est libre.
            CHECK_EQ(bu[1].start_ns, bu[0].end_ns);
            CHECK_TRUE(bu[1].start_ns >= 2 * kS);  // RECEIVE_DELAY2 = 2 s après la fin de la montante
            // L'occupation porte la durée **réelle** : celle de RX2, pas celle de RX1.
            CHECK_EQ(bu[1].end_ns - bu[1].start_ns, air_rx2);
            // Et l'événement porte la fréquence de la fenêtre réellement émise.
            std::size_t sur_rx2 = 0;
            for (const Event& e : ev) {
                if (e.kind == EventKind::Downlink && e.device == 1) {
                    CHECK_EQ(e.hops.size(), 1u);
                    CHECK_EQ(e.hops[0].freq_hz, 869'525'000);
                    ++sur_rx2;
                }
            }
            CHECK_EQ(sur_rx2, 1u);
            // Le premier dispositif, lui, est resté en RX1 : une seule fenêtre par descente.
            for (const Event& e : ev) {
                if (e.kind == EventKind::Downlink && e.device == 0) {
                    CHECK_EQ(e.hops[0].freq_hz, 868'100'000);
                }
            }
        }

        // 12c. Sans table RX2, le repli est impossible même activé : rien ne change.
        {
            PlanOptions avec = o;
            avec.rx2_fallback = true;
            std::vector<Event> ev;
            std::vector<Interval> bu;
            CHECK_EQ(plan_downlinks(ups, radios, avec, nullptr, ev, bu), PlanStatus::Ok);
            CHECK_EQ(bu.size(), 1u);
        }

        // 12d. Fenêtre RX2 non renseignée : `rx2_sf = 0` ou `rx2_hz = 0` ⇒ aucun repli.
        for (const DeviceRx2& partiel : {DeviceRx2{869'525'000, 0, 125'000},
                                         DeviceRx2{0, 12, 125'000}}) {
            PlanOptions avec = o;
            avec.rx2_fallback = true;
            std::vector<DeviceRx2> r2(2, partiel);
            std::vector<Event> ev;
            std::vector<Interval> bu;
            CHECK_EQ(plan_downlinks(ups, radios, avec, &r2, ev, bu), PlanStatus::Ok);
            CHECK_EQ(bu.size(), 1u);
        }

        // 12e. Même règle au planificateur incrémental : sans l'opt-in, rien ne change ; avec lui,
        //      la descente part en RX2 avec la durée RX2.
        {
            DownlinkScheduler s_sans(radios, o);
            CHECK_EQ(s_sans.status(), PlanStatus::Ok);
            const auto a0 = s_sans.on_received(0, 10'000'000, rx2[0]);
            CHECK_EQ(a0.size(), 1u);
            const auto a1 = s_sans.on_received(1, 500'000'000, rx2[1]);
            CHECK_TRUE(a1.empty());  // RX1 masquée, et aucun repli demandé
            CHECK_TRUE(s_sans.drain().empty());

            PlanOptions repli = o;
            repli.rx2_fallback = true;
            DownlinkScheduler s_avec(radios, repli);
            CHECK_EQ(s_avec.status(), PlanStatus::Ok);
            const auto b0 = s_avec.on_received(0, 10'000'000, rx2[0]);
            CHECK_EQ(b0.size(), 1u);
            CHECK_EQ(b0[0].start_ns, a0[0].start_ns);
            CHECK_EQ(b0[0].end_ns, a0[0].end_ns);
            // La RX2 n'est pas placée à cet appel : son ouverture (2,5 s) est postérieure à la
            // frontière de l'appel courant (1,5 s), et une montante ultérieure pourrait ouvrir
            // sa RX1 avant elle.
            const auto b1 = s_avec.on_received(1, 500'000'000, rx2[1]);
            CHECK_TRUE(b1.empty());  // la RX1 est manquée, la seconde fenêtre est en attente
            const auto b2 = s_avec.drain();
            CHECK_EQ(b2.size(), 1u);  // rattrapée en RX2, à la purge
            CHECK_EQ(b2[0].start_ns, a0[0].end_ns);
            CHECK_EQ(b2[0].end_ns - b2[0].start_ns, air_rx2);  // durée réelle, pas celle de RX1
            CHECK_TRUE(b2[0].start_ns >= 2 * kS);
        }

        // 12f. La purge ne place rien de plus qu'une seconde descente : une RX2 déjà émise
        //      n'est pas réémise, et une seconde purge est vide.
        {
            PlanOptions repli = o;
            repli.rx2_fallback = true;
            DownlinkScheduler s(radios, repli);
            CHECK_EQ(s.status(), PlanStatus::Ok);
            std::vector<Interval> tout;
            for (const Interval& i : s.on_received(0, 10'000'000, rx2[0])) tout.push_back(i);
            for (const Interval& i : s.on_received(1, 500'000'000, rx2[1])) tout.push_back(i);
            for (const Interval& i : s.drain()) tout.push_back(i);
            CHECK_TRUE(s.drain().empty());
            CHECK_EQ(tout.size(), 2u);
            // Même résultat, dans le même ordre, que la planification par lot.
            std::vector<Event> ev;
            std::vector<Interval> bu;
            CHECK_EQ(plan_downlinks(ups, radios, repli, &rx2, ev, bu), PlanStatus::Ok);
            CHECK_EQ(bu.size(), tout.size());
            for (std::size_t k = 0; k < std::min(bu.size(), tout.size()); ++k) {
                CHECK_EQ(bu[k].start_ns, tout[k].start_ns);
                CHECK_EQ(bu[k].end_ns, tout[k].end_ns);
            }
        }
    }
}
