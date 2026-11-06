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
    // Table RX2 valide (SF12) fournie par défaut : le repli est actif dès qu'elle est passée à
    // l'enveloppe v2. `received` ne garde que les montantes reçues, pour retrouver les ouvertures.
    std::vector<lsim_plan_device_rx2> rx2;
    std::vector<lsim_plan_uplink> received;
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
        if (u.outcome == 2) c.received.push_back(u);
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
    c.rx2.resize(3);
    for (auto& r : c.rx2) {
        r.rx2_hz = 869'525'000;
        r.rx2_sf = 12;
        r.rx2_bw_hz = 125'000;
    }
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

        // 8b. rx2 renseigné : le repli devient actif et, sous A6, il se déclenche réellement.
        //
        // L'enveloppe C active le repli par la seule présence de la table
        // (`po.rx2_fallback = (rx2 != nullptr)`) : fournir la table **est** l'opt-in. Ce
        // comportement existait avant U0.3 mais ne produisait jamais d'émission, la règle à
        // décalage faisant toujours tenir la descente dans la seconde de la fenêtre. A6 supprime
        // ce décalage : une RX1 chevauchée à son ouverture est perdue, et le repli part.
        //
        // La v2 produit donc **davantage** d'occupation que la v1, qui n'a pas de table. C'est une
        // conséquence voulue de l'arbitrage A6, pas une divergence d'implémentation — le cas 8d
        // vérifie que, sans contention, les deux enveloppes restent identiques.
        std::vector<lsim_plan_device_rx2> rx2(c.devs.size());
        for (auto& r : rx2) {
            r.rx2_hz = 869'525'000;
            r.rx2_sf = 12;
            r.rx2_bw_hz = 125'000;
        }
        const int32_t r3 = run_v2(rx2.data(), ev3.data(), &n3, b3.data(), &nb3);
        CHECK_EQ(r3, r1);
        CHECK_TRUE(nb3 > nb1);  // au moins une descente rattrapée en RX2
        // Les émissions que la v1 plaçait sont retrouvées **telles quelles** : la v2 ne décale
        // rien de ce qui existait déjà, elle ajoute les fenêtres de secours.
        for (size_t k = 0; k < nb1; ++k) {
            CHECK_EQ(b3[k].start_ns, b1[k].start_ns);
            CHECK_EQ(b3[k].end_ns, b1[k].end_ns);
        }
        // Chaque émission supplémentaire est une RX2 : elle part exactement 1 s après une
        // ouverture de RX1 (`t_open_rx2 = t_open + 1 s`) et porte la fréquence de la RX2.
        for (size_t k = nb1; k < nb3; ++k) {
            const std::int64_t ouverture_rx1 = b3[k].start_ns - 1'000'000'000;
            bool rx1_correspondante = false;
            for (const lsim_plan_uplink& u : c.received) {
                if (u.end_ns + 1'000'000'000 == ouverture_rx1) rx1_correspondante = true;
            }
            CHECK_TRUE(rx1_correspondante);  // ouverture exacte de la RX2, aucun décalage
        }
    }

    // 8d. Sans contention, la table RX2 ne change rien : parité stricte v1 / v2 avec repli actif.
    //
    // Les montantes sont espacées de 600 ms, très au-delà du temps d'antenne d'une descente
    // (au plus ~0,10 s au SF7) : aucune fenêtre n'est masquée, donc aucun repli ne se déclenche.
    // La parité observée en 8a ne dépend donc pas de l'absence de table, mais du repli — ce qui
    // isole la cause de l'écart constaté en 8b.
    {
        PlanCase c = make_plan_case();
        c.ups.clear();
        std::int64_t t = 0;
        for (std::uint32_t k = 0; k < 6; ++k) {
            lsim_plan_uplink u{};
            u.device_index = k % 3;
            u.start_ns = t;
            u.end_ns = t + 20'000'000;
            u.spreading_factor = 7;
            u.outcome = 2;
            u.rssi_dbm = -60.0;
            c.ups.push_back(u);
            t += 600'000'000;
        }
        const std::size_t cap = 32;
        std::vector<lsim_plan_event> ev1(cap), ev3(cap);
        std::vector<lsim_interval> b1(cap), b3(cap);
        size_t n1 = 0, nb1 = 0, n3 = 0, nb3 = 0;
        CHECK_EQ(lsim_plan_downlinks_v1(c.ups.data(), c.ups.size(), c.devs.data(), c.devs.size(),
                                       &c.opts, ev1.data(), cap, &n1, b1.data(), cap, &nb1), 0);
        lsim_plan_downlinks_v2_args a{};
        a.struct_size = sizeof(a);
        a.abi_version = LSIM_PLAN_DOWNLINKS_V2_ABI_VERSION;
        a.uplinks = c.ups.data();
        a.uplink_count = c.ups.size();
        a.devices = c.devs.data();
        a.device_count = c.devs.size();
        a.options = &c.opts;
        a.rx2 = c.rx2.data();
        a.rx2_count = c.devs.size();
        a.events = ev3.data();
        a.event_capacity = cap;
        a.event_count = &n3;
        a.busy = b3.data();
        a.busy_capacity = cap;
        a.busy_count = &nb3;
        CHECK_EQ(lsim_plan_downlinks_v2(&a), 0);
        CHECK_EQ(n3, n1);
        CHECK_EQ(nb3, nb1);
        CHECK_TRUE(nb1 > 0);
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

    // 9bis. Enveloppe v3 (I6-c) : mêmes refus que la v2, plus le contrat `limits`. Passer la
    //    table, c'est **demander** la validation N ; l'absence de contrainte reste l'affaire de
    //    la v2 (bbb5). Cas conforme d'abord, puis chaque refus, un par un.
    {
        const PlanCase c = make_plan_case();
        const std::size_t cap = 32;
        std::vector<lsim_plan_event> ev(cap);
        std::vector<lsim_interval> bu(cap);
        size_t n = 0, nb = 0;

        const auto base = [&]() {
            lsim_plan_downlinks_v3_args a{};
            a.struct_size = sizeof(a);
            a.abi_version = LSIM_PLAN_DOWNLINKS_V3_ABI_VERSION;
            a.uplinks = c.ups.data();
            a.uplink_count = c.ups.size();
            a.devices = c.devs.data();
            a.device_count = c.devs.size();
            a.options = &c.opts;
            a.rx2 = c.rx2.data();
            a.rx2_count = c.rx2.size();
            a.limits = nullptr;      // remplacé par les cas qui suivent
            a.limits_count = 0;
            a.events = ev.data();
            a.event_capacity = cap;
            a.event_count = &n;
            a.busy = bu.data();
            a.busy_capacity = cap;
            a.busy_count = &nb;
            return a;
        };

        // 9bis-0. Cas conforme : une table de trois entrées, tous N à 51 ⇒ la charge de 40 passe.
        {
            std::vector<lsim_plan_device_limits> lim(3, lsim_plan_device_limits{51, 51});
            lsim_plan_downlinks_v3_args a = base();
            a.limits = lim.data();
            a.limits_count = lim.size();
            CHECK_EQ(lsim_plan_downlinks_v3(&a), 0);
            const size_t nb_conforme = nb;

            // Même scénario, fenêtres toutes inéligibles ⇒ plus aucune occupation émise.
            std::vector<lsim_plan_device_limits> nuls(3, lsim_plan_device_limits{0, 0});
            lsim_plan_downlinks_v3_args b = base();
            b.limits = nuls.data();
            b.limits_count = nuls.size();
            n = 0;
            nb = 0;
            CHECK_EQ(lsim_plan_downlinks_v3(&b), 0);
            CHECK_TRUE(nb < nb_conforme);
        }

        const std::vector<lsim_plan_device_limits> lim(3, lsim_plan_device_limits{51, 51});
        const auto avec = [&](auto&& muter) {
            lsim_plan_downlinks_v3_args a = base();
            a.limits = lim.data();
            a.limits_count = lim.size();
            muter(a);
            return lsim_plan_downlinks_v3(&a);
        };
        const std::int32_t refus = LSIM_STATUS_PLAN_BASE + 1;

        // Refus hérités de la v2 : aucun n'est silencieusement accepté.
        CHECK_EQ(lsim_plan_downlinks_v3(nullptr), refus);
        CHECK_EQ(avec([](lsim_plan_downlinks_v3_args& a) { a.struct_size = sizeof(a) - 8u; }),
                 refus);
        CHECK_EQ(avec([](lsim_plan_downlinks_v3_args& a) {
                     a.abi_version = LSIM_PLAN_DOWNLINKS_V3_ABI_VERSION + 1u;
                 }),
                 refus);
        CHECK_EQ(avec([](lsim_plan_downlinks_v3_args& a) { a.reserved[1] = 1; }), refus);
        CHECK_EQ(avec([](lsim_plan_downlinks_v3_args& a) { a.options = nullptr; }), refus);
        CHECK_EQ(avec([](lsim_plan_downlinks_v3_args& a) { a.event_count = nullptr; }), refus);
        CHECK_EQ(avec([](lsim_plan_downlinks_v3_args& a) { a.busy_count = nullptr; }), refus);
        CHECK_EQ(avec([](lsim_plan_downlinks_v3_args& a) { a.uplinks = nullptr; }), refus);
        CHECK_EQ(avec([](lsim_plan_downlinks_v3_args& a) { a.devices = nullptr; }), refus);

        // Refus propres au contrat `limits` (bbb5, bbb3) : jamais de repli silencieux.
        CHECK_EQ(avec([](lsim_plan_downlinks_v3_args& a) { a.limits = nullptr; }), refus);
        CHECK_EQ(avec([](lsim_plan_downlinks_v3_args& a) { a.limits_count = 2; }), refus);
        CHECK_EQ(avec([](lsim_plan_downlinks_v3_args& a) { a.limits_count = 99; }), refus);
        CHECK_EQ(avec([](lsim_plan_downlinks_v3_args& a) { a.limits_count = 0; }), refus);
        // N hors bornes : 243 et −1, sur RX1 comme sur RX2. Aucune lecture n'a lieu.
        {
            std::vector<lsim_plan_device_limits> hors(3, lsim_plan_device_limits{243, 51});
            lsim_plan_downlinks_v3_args a = base();
            a.limits = hors.data();
            a.limits_count = hors.size();
            CHECK_EQ(lsim_plan_downlinks_v3(&a), refus);
            for (auto& l : hors) l = lsim_plan_device_limits{-1, 51};
            CHECK_EQ(lsim_plan_downlinks_v3(&a), refus);
            for (auto& l : hors) l = lsim_plan_device_limits{51, 243};
            CHECK_EQ(lsim_plan_downlinks_v3(&a), refus);
            for (auto& l : hors) l = lsim_plan_device_limits{51, -1};
            CHECK_EQ(lsim_plan_downlinks_v3(&a), refus);
        }
        // `reserved` de l'élément doit être nul : un octet non nul est un appelant d'une ABI
        // future, pas un appelant toléré.
        {
            std::vector<lsim_plan_device_limits> res(3, lsim_plan_device_limits{51, 51});
            res[0].reserved[0] = 1;
            lsim_plan_downlinks_v3_args a = base();
            a.limits = res.data();
            a.limits_count = res.size();
            CHECK_EQ(lsim_plan_downlinks_v3(&a), refus);
        }
        // Non-régression : sans table, la v3 se comporte comme la v2 (mêmes occupations).
        {
            std::vector<lsim_plan_event> ev2(cap), ev3(cap);
            std::vector<lsim_interval> bu2(cap), bu3(cap);
            size_t n2 = 0, nb2 = 0, n3 = 0, nb3 = 0;
            lsim_plan_downlinks_v2_args v2{};
            v2.struct_size = sizeof(v2);
            v2.abi_version = LSIM_PLAN_DOWNLINKS_V2_ABI_VERSION;
            v2.uplinks = c.ups.data();
            v2.uplink_count = c.ups.size();
            v2.devices = c.devs.data();
            v2.device_count = c.devs.size();
            v2.options = &c.opts;
            v2.rx2 = c.rx2.data();
            v2.rx2_count = c.rx2.size();
            v2.events = ev2.data();
            v2.event_capacity = cap;
            v2.event_count = &n2;
            v2.busy = bu2.data();
            v2.busy_capacity = cap;
            v2.busy_count = &nb2;
            CHECK_EQ(lsim_plan_downlinks_v2(&v2), 0);

            std::vector<lsim_plan_device_limits> large(3, lsim_plan_device_limits{242, 242});
            lsim_plan_downlinks_v3_args v3 = base();
            v3.limits = large.data();
            v3.limits_count = large.size();
            v3.events = ev3.data();
            v3.event_count = &n3;
            v3.busy = bu3.data();
            v3.busy_count = &nb3;
            CHECK_EQ(lsim_plan_downlinks_v3(&v3), 0);
            CHECK_EQ(n3, n2);
            CHECK_EQ(nb3, nb2);
            for (size_t k = 0; k < std::min(nb2, nb3); ++k) {
                CHECK_EQ(bu3[k].start_ns, bu2[k].start_ns);
                CHECK_EQ(bu3[k].end_ns, bu2[k].end_ns);
            }
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
        // U0.3 : SF11, et non SF12. La descente du premier doit masquer la RX1 du second mais
        // **libérer l'émetteur avant l'ouverture de sa RX2** (2,5 s). Avec A6 il n'y a plus de
        // décalage : une fenêtre chevauchée à son ouverture est refusée, elle n'attend pas. Au
        // SF12 l'émetteur restait pris jusqu'à 2,98 s et la RX2 était perdue — cas désormais
        // couvert par 12g ci-dessous.
        gros.rx1_sf = 11;
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
            // A6 : la RX2 est émise **exactement à son ouverture** (fin de la montante + 2 s),
            // et non « dès que l'émetteur est libre ». Ici l'émetteur est libre dès 1,75 s, soit
            // 0,75 s avant l'ouverture : l'ancienne règle aurait émis à 1,75 s.
            CHECK_EQ(bu[1].start_ns, 2 * kS + 500'000'000);
            CHECK_TRUE(bu[1].start_ns > bu[0].end_ns);  // l'émetteur s'est vraiment libéré avant
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
            CHECK_EQ(b2[0].start_ns, 2 * kS + 500'000'000);  // A6 : ouverture exacte de la RX2
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

    // -------------------------------------------------------------------------------
    // Cas 12g. U0.3 / A6 : une fenêtre chevauchée à son ouverture est **refusée**, et ne crée
    // aucune occupation fictive.
    //
    // Mêmes instants que le cas 12, mais la première descente est au SF12 : elle occupe
    // l'émetteur de 1,01 s à 2,98 s. La RX1 du second dispositif (1,5 s) est masquée — comme en
    // 12 — **et sa RX2 (2,5 s) l'est aussi**.
    //
    // Avant U0.3 la RX2 était émise à 2,98 s, soit 0,48 s après son ouverture : l'émetteur
    // attendait sa libération. A6 l'interdit (TS001-1.0.4 §3.3.5 : émission « précisément au
    // début » de la fenêtre). La descente est donc perdue, et surtout **l'émetteur ne porte
    // aucune trace de cette tentative** : une seule occupation, celle de la première descente.
    //
    // Ce cas est la contrepartie négative de 12b : sans lui, « repli RX2 réussi » et « occupation
    // uniquement pour les émissions acceptées » ne seraient pas départagés.
    {
        DeviceRadio gros = radio_sf7();
        gros.rx1_sf = 12;  // descente longue : masque la RX1 **et** la RX2 du second
        const DeviceRadio petit = radio_sf7();
        const std::vector<DeviceRadio> radios{gros, petit};

        PlanOptions o;
        o.confirmed_uplinks = true;
        o.downlink_every = 1;
        o.downlink_payload_bytes = 27;
        o.gateway_tx_power_dbm = 27.0;
        o.rx2_fallback = true;  // le repli est demandé, mais la fenêtre n'est pas disponible

        const std::vector<UplinkRecord> ups{up(0, 0, 10'000'000, UplinkOutcome::Received),
                                            up(1, 490'000'000, 10'000'000, UplinkOutcome::Received)};
        std::vector<DeviceRx2> rx2(2, DeviceRx2{869'525'000, 12, 125'000});

        // Planification par lot : une seule émission, aucune occupation au-delà de la première.
        {
            std::vector<Event> ev;
            std::vector<Interval> bu;
            CHECK_EQ(plan_downlinks(ups, radios, o, &rx2, ev, bu), PlanStatus::Ok);
            CHECK_EQ(bu.size(), 1u);
            CHECK_EQ(bu[0].start_ns, kS + 10'000'000);  // ouverture exacte de la RX1 du premier
            // Le second dispositif n'a rien reçu, et aucune fenêtre ne lui a été imputée.
            std::size_t manquees = 0;
            for (const Event& e : ev) {
                if (e.kind == EventKind::RxWindowMissed) ++manquees;
            }
            CHECK_EQ(manquees, 1u);
        }

        // Même chose au planificateur incrémental : le repli est tenté puis abandonné, sans
        // laisser d'occupation.
        {
            DownlinkScheduler s(radios, o);
            CHECK_EQ(s.status(), PlanStatus::Ok);
            std::vector<Interval> tout;
            for (const Interval& i : s.on_received(0, 10'000'000, rx2[0])) tout.push_back(i);
            for (const Interval& i : s.on_received(1, 500'000'000, rx2[1])) tout.push_back(i);
            for (const Interval& i : s.drain()) tout.push_back(i);
            CHECK_EQ(tout.size(), 1u);
            CHECK_EQ(tout[0].start_ns, kS + 10'000'000);
        }
    }

    // -------------------------------------------------------------------------------
    // Cas 13. Sensibilité de la fenêtre **réellement émise** (I3/C4).
    //
    // Le seuil de réception dépend du débit de la fenêtre, et RX2 n'a pas celui de RX1 : au
    // SF12BW125 il est meilleur de 13 dB qu'au SF7BW125. Seuiller une descente émise en RX2 avec
    // le seuil de RX1 la déclarait perdue alors que le dispositif l'entendait.
    //
    // **La parité ne voyait pas cette erreur : l'oracle Python la commettait à l'identique.** Ce
    // cas épingle donc le cœur seul, indépendamment de tout oracle.
    //
    // Réglage : `rssi_dl = rssi + (27 dBm - 14 dBm)` = `rssi + 13 dB`. À -145 dBm, le lien tombe
    // à -132 dBm — sourd au seuil SF7 (-123), audible au seuil SF12 (-136).
    {
        DeviceRadio gros = radio_sf7();
        // U0.3 : SF11 et non SF12 (voir cas 12). La RX1 du second doit être masquée, mais sa RX2
        // doit rester disponible à son ouverture — sans quoi il n'y a plus de descente à seuiller.
        gros.rx1_sf = 11;
        const DeviceRadio petit = radio_sf7();
        const std::vector<DeviceRadio> radios{gros, petit};

        constexpr std::uint32_t kCharge = 27;
        constexpr std::uint32_t kTrame = 13 + kCharge;
        PlanOptions o;
        o.confirmed_uplinks = true;
        o.downlink_every = 1;
        o.downlink_payload_bytes = kCharge;
        o.gateway_tx_power_dbm = 27.0;
        o.rx2_fallback = true;

        // Même instants, même fenêtre émise (RX2) : seul le SF de la fenêtre de secours change.
        const std::vector<UplinkRecord> ups{
            up(0, 0, 10'000'000, UplinkOutcome::Received, -145.0),
            up(1, 490'000'000, 10'000'000, UplinkOutcome::Received, -145.0)};

        // Verdict du saut passerelle → dispositif pour la descente du second.
        const auto verdict = [&](std::uint8_t rx2_sf) {
            std::vector<DeviceRx2> r2(2);
            r2[0] = DeviceRx2{869'525'000, rx2_sf, 125'000};
            r2[1] = DeviceRx2{869'525'000, rx2_sf, 125'000};
            std::vector<Event> ev;
            std::vector<Interval> bu;
            if (plan_downlinks(ups, radios, o, &r2, ev, bu) != PlanStatus::Ok) {
                return static_cast<int>(-1);
            }
            for (const Event& e : ev) {
                if (e.kind != EventKind::Downlink || e.device != 1) continue;
                if (e.hops.empty()) continue;
                return static_cast<int>(e.hops.back().outcome);
            }
            return static_cast<int>(-2);  // aucune descente pour le second dispositif
        };

        const int rx2_sf12 = verdict(12);
        const int rx2_sf7 = verdict(7);
        CHECK_EQ(rx2_sf12, static_cast<int>(Outcome::Delivered));
        CHECK_EQ(rx2_sf7, static_cast<int>(Outcome::LostSensitivity));

        // Contrôle négatif : franchement sous le seuil SF12, la descente reste perdue. La
        // correction n'est pas un passe-droit — elle déplace le seuil, elle ne l'abaisse pas.
        {
            const std::vector<UplinkRecord> sourds{
                up(0, 0, 10'000'000, UplinkOutcome::Received, -155.0),
                up(1, 490'000'000, 10'000'000, UplinkOutcome::Received, -155.0)};
            std::vector<DeviceRx2> r2(2, DeviceRx2{869'525'000, 12, 125'000});
            std::vector<Event> ev;
            std::vector<Interval> bu;
            CHECK_EQ(plan_downlinks(sourds, radios, o, &r2, ev, bu), PlanStatus::Ok);
            int vu = -2;
            for (const Event& e : ev) {
                if (e.kind != EventKind::Downlink || e.device != 1 || e.hops.empty()) continue;
                vu = static_cast<int>(e.hops.back().outcome);
            }
            CHECK_EQ(vu, static_cast<int>(Outcome::LostSensitivity));
        }

        // Et la fenêtre retenue est bien RX2 : c'est la condition du cas, pas une supposition.
        {
            std::vector<DeviceRx2> r2(2, DeviceRx2{869'525'000, 12, 125'000});
            std::vector<Event> ev;
            std::vector<Interval> bu;
            CHECK_EQ(plan_downlinks(ups, radios, o, &r2, ev, bu), PlanStatus::Ok);
            CHECK_EQ(bu.size(), 2u);
            for (const Event& e : ev) {
                if (e.kind == EventKind::Downlink && e.device == 1 && !e.hops.empty()) {
                    CHECK_EQ(e.hops.back().freq_hz, 869'525'000);
                }
            }
        }
    }

    // -------------------------------------------------------------------------------
    // Cas 14. U0.3 / A6 — scènes discriminantes du placement.
    //
    // Chaque scène est jouée **deux fois** : sur le planificateur par lot (`plan_downlinks`) et
    // sur le planificateur incrémental du chemin causal (`DownlinkScheduler`). Les deux doivent
    // produire la même occupation, sinon `trace_events` lève « occupation passerelle incohérente
    // entre le moteur et le planificateur ».
    //
    // Les scènes D et E forment la paire décisive : elles ne diffèrent que d'une nanoseconde et
    // doivent aboutir à des verdicts opposés. C'est ce qui distingue un placement « à
    // l'ouverture exacte » d'un placement « dès que l'émetteur est libre », et c'est ce qui
    // empêche de remplacer le chevauchement réel par une borne de fin.
    //
    // Toutes les préconditions sont **vérifiées** : si un temps d'antenne changeait au point de
    // rendre une scène inopérante, le test échouerait bruyamment au lieu de passer à côté.
    //
    // Réglage commun : deux dispositifs, ACK à chaque uplink reçu (`downlink_every = 0`), au
    // SF7 sauf mention contraire. L'émission du premier dispositif sert d'occupation connue ;
    // celle du second est la fenêtre observée.
    {
        const DeviceRadio sf7 = radio_sf7();
        // Trame d'ACK : 12 octets, valeur déjà employée par les cas précédents.
        constexpr std::uint32_t kAckBytes = 12;
        // Trame de données : 13 octets d'en-tête + 10 de charge (même valeur que le cœur).
        constexpr std::uint32_t kTrameDonnees = 23;
        std::int64_t air = 0;
        CHECK_EQ(downlink_airtime_ns(sf7, kAckBytes, air), lsim::lora::Status::Ok);
        CHECK_TRUE(air > 0);

        // Temps d'antenne d'une descente SF12, pour les scènes qui ont besoin d'une émission
        // longue : c'est aussi celui de la fenêtre RX2, dont le SF propre est conservé.
        DeviceRadio radio_long = sf7;
        radio_long.rx1_sf = 12;
        std::int64_t air_long = 0;
        CHECK_EQ(downlink_airtime_ns(radio_long, kAckBytes, air_long), lsim::lora::Status::Ok);

        // Joue une scène sur les deux planificateurs et retourne l'occupation de chacun.
        // `rx2_hz` non nul ⇒ table RX2 fournie ⇒ repli actif (opt-in par la table).
        const auto jouer = [&](const std::vector<DeviceRadio>& radios,
                               const std::vector<UplinkRecord>& ups, PlanOptions o,
                               std::uint8_t rx2_sf) {
            std::vector<DeviceRx2> r2(radios.size(), DeviceRx2{869'525'000, rx2_sf, 125'000});
            std::vector<Event> ev;
            std::vector<Interval> par_lot;
            CHECK_EQ(plan_downlinks(ups, radios, o, &r2, ev, par_lot), PlanStatus::Ok);

            DownlinkScheduler incr(radios, o);
            CHECK_EQ(incr.status(), PlanStatus::Ok);
            std::vector<Interval> causal;
            for (const UplinkRecord& u : ups) {
                for (const Interval& i : incr.on_received(u.device, u.end_ns, r2[u.device])) {
                    causal.push_back(i);
                }
            }
            for (const Interval& i : incr.drain()) causal.push_back(i);

            // L'égalité des deux producteurs est exigée par le chemin causal (`trace_events`).
            CHECK_EQ(causal.size(), par_lot.size());
            for (std::size_t k = 0; k < std::min(causal.size(), par_lot.size()); ++k) {
                CHECK_EQ(causal[k].start_ns, par_lot[k].start_ns);
                CHECK_EQ(causal[k].end_ns, par_lot[k].end_ns);
            }
            return par_lot;
        };

        // --- A. RX1 libre : émission exactement à l'ouverture de RX1 -------------------------
        {
            PlanOptions o;
            o.confirmed_uplinks = true;
            o.downlink_every = 0;
            const std::vector<UplinkRecord> ups{up(0, 0, 10'000'000, UplinkOutcome::Received)};
            const auto bu = jouer({sf7}, ups, o, 12);
            CHECK_EQ(bu.size(), std::size_t{1});
            CHECK_EQ(bu[0].start_ns, kS + 10'000'000);  // ouverture exacte, aucun décalage
            CHECK_EQ(bu[0].end_ns, kS + 10'000'000 + air);
        }

        // --- B. RX1 occupée : repli en RX2, à l'ouverture de RX2 -----------------------------
        // L'émission du premier dispositif recouvre l'ouverture de la RX1 du second, mais se
        // termine bien avant l'ouverture de sa RX2 (une seconde plus tard).
        {
            PlanOptions o;
            o.confirmed_uplinks = true;
            o.downlink_every = 0;
            o.rx2_fallback = true;
            // L'émission du premier va de 1,01 s à 1,01 s + air. Le second uplink finit à 25 ms :
            // sa RX1 ouvre à 1,025 s, en pleine émission ; sa RX2 ouvre à 2,025 s, où
            // l'émetteur est libre depuis longtemps.
            constexpr std::int64_t kFinUtile = 25'000'000;
            const std::vector<UplinkRecord> ups{
                up(0, 0, 10'000'000, UplinkOutcome::Received),
                up(1, kFinUtile - 10'000'000, 10'000'000, UplinkOutcome::Received)};
            // Préconditions : la RX1 du second est bien masquée, et ses montantes ne se
            // chevauchent pas (sinon l'uplink serait perdu et la scène ne dirait plus rien).
            CHECK_TRUE(kS + 10'000'000 < kS + kFinUtile);
            CHECK_TRUE(kS + kFinUtile < kS + 10'000'000 + air);
            CHECK_TRUE(kFinUtile - 10'000'000 > 10'000'000);
            const std::vector<DeviceRadio> radios{sf7, sf7};
            std::int64_t air_rx2 = 0;
            DeviceRadio en_rx2 = sf7;
            en_rx2.rx1_sf = 12;
            CHECK_EQ(downlink_airtime_ns(en_rx2, kAckBytes, air_rx2), lsim::lora::Status::Ok);
            const auto bu = jouer(radios, ups, o, 12);
            CHECK_EQ(bu.size(), std::size_t{2});
            CHECK_EQ(bu[0].start_ns, kS + 10'000'000);
            // RX2 : ouverture exacte (RX1 + 1 s), et durée de RX2 — pas celle de RX1.
            CHECK_EQ(bu[1].start_ns, kS + kFinUtile + kS);
            CHECK_EQ(bu[1].end_ns, bu[1].start_ns + air_rx2);
            CHECK_TRUE(air_rx2 > air);  // le repli coûte l'émetteur : la scène est probante
        }

        // --- C. RX1 et RX2 occupées : aucune émission, aucune occupation fictive -------------
        {
            PlanOptions o;
            o.confirmed_uplinks = true;
            o.downlink_every = 0;
            o.rx2_fallback = true;
            // Le premier dispositif émet une descente de données au SF12 — un ACK (12 octets,
            // 0,99 s) ne suffirait pas : il faut masquer la RX1 **et** la RX2 du second, soit plus
            // d'une seconde d'occupation.
            o.downlink_every = 1;
            o.downlink_payload_bytes = 10;
            std::int64_t air_donnees = 0;
            CHECK_EQ(downlink_airtime_ns(radio_long, kTrameDonnees, air_donnees),
                     lsim::lora::Status::Ok);
            const std::vector<DeviceRadio> radios{radio_long, sf7};
            const std::int64_t ouverture_rx1 = kS + 25'000'000;
            const std::int64_t ouverture_rx2 = ouverture_rx1 + kS;
            // Précondition : les deux fenêtres du second sont réellement masquées. Sans elle, un
            // changement de temps d'antenne ferait passer le test à côté de ce qu'il épingle.
            CHECK_TRUE(kS + 10'000'000 + air_donnees > ouverture_rx2);
            const std::vector<UplinkRecord> ups{
                up(0, 0, 10'000'000, UplinkOutcome::Received),
                up(1, 25'000'000 - 10'000'000, 10'000'000, UplinkOutcome::Received)};
            const auto bu = jouer(radios, ups, o, 12);
            // Une seule occupation : celle de l'émission réellement acceptée. Les deux fenêtres
            // refusées du second dispositif n'en laissent aucune trace.
            CHECK_EQ(bu.size(), std::size_t{1});
            CHECK_EQ(bu[0].start_ns, kS + 10'000'000);
            CHECK_EQ(bu[0].end_ns, kS + 10'000'000 + air_donnees);
        }

        // --- D. Occupation se terminant **exactement** à l'ouverture : émission autorisée -----
        // Le second uplink finit à `air` : sa RX1 ouvre exactement à la libération de
        // l'émetteur. Intervalle semi-ouvert : le contact n'est pas un chevauchement.
        {
            PlanOptions o;
            o.confirmed_uplinks = true;
            o.downlink_every = 0;
            const std::vector<UplinkRecord> ups{
                up(0, 0, 10'000'000, UplinkOutcome::Received),
                up(1, air, 10'000'000, UplinkOutcome::Received)};
            CHECK_TRUE(air > 10'000'000);  // les deux montantes ne se chevauchent pas
            const auto bu = jouer({sf7, sf7}, ups, o, 12);
            CHECK_EQ(bu.size(), std::size_t{2});
            CHECK_EQ(bu[1].start_ns, kS + 10'000'000 + air);  // ouverture exacte, aucun repli
        }

        // --- E. Occupation chevauchant **réellement** la fenêtre : refus ----------------------
        // Strictement la même scène que D, à une nanoseconde près : l'émetteur est encore pris
        // une nanoseconde après l'ouverture. La fenêtre est manquée. Le repli est actif mais la
        // RX2, une seconde plus tard, est libre — la descente part donc en RX2.
        {
            PlanOptions o;
            o.confirmed_uplinks = true;
            o.downlink_every = 0;
            o.rx2_fallback = true;
            const std::vector<UplinkRecord> ups{
                up(0, 0, 10'000'000, UplinkOutcome::Received),
                up(1, air - 1, 10'000'000, UplinkOutcome::Received)};
            const auto bu = jouer({sf7, sf7}, ups, o, 12);
            CHECK_EQ(bu.size(), std::size_t{2});
            // RX1 refusée : une nanoseconde de trop. Rattrapée en RX2, à l'ouverture de celle-ci.
            CHECK_EQ(bu[1].start_ns, kS + 10'000'000 + air - 1 + kS);
            // La paire D/E prouve que le refus vient d'un chevauchement réel et non d'une borne :
            // une borne « occupé jusqu'à » n'aurait pas départagé deux instants si proches.
        }

        // --- F. Deux fenêtres séparées par un intervalle libre : les deux sont émises ---------
        // Le piège d'une borne monotone « occupé jusqu'à » : une fois l'émetteur occupé, une
        // telle borne ne décroît jamais et rejetterait la seconde fenêtre à tort. Le placement
        // porte donc sur un chevauchement réel, pas sur une borne.
        {
            PlanOptions o;
            o.confirmed_uplinks = true;
            o.downlink_every = 0;
            const std::vector<UplinkRecord> ups{
                up(0, 0, 10'000'000, UplinkOutcome::Received),
                up(1, 3 * kS, 10'000'000, UplinkOutcome::Received)};
            CHECK_TRUE(kS + 10'000'000 + air < 4 * kS + 10'000'000);  // intervalle libre réel
            const auto bu = jouer({sf7, sf7}, ups, o, 12);
            CHECK_EQ(bu.size(), std::size_t{2});
            CHECK_EQ(bu[0].start_ns, kS + 10'000'000);
            CHECK_EQ(bu[1].start_ns, 4 * kS + 10'000'000);  // à son ouverture, pas après
        }

        // --- G. Une émission acceptée occupe l'émetteur ; un refus n'en laisse aucune ---------
        // Reprise de C sans repli : le second dispositif n'a aucune fenêtre, et l'occupation est
        // exactement celle de la seule émission acceptée — ni plus, ni décalée.
        {
            PlanOptions o;
            o.confirmed_uplinks = true;
            o.downlink_every = 0;
            o.downlink_every = 1;
            o.downlink_payload_bytes = 10;
            std::int64_t air_donnees = 0;
            CHECK_EQ(downlink_airtime_ns(radio_long, kTrameDonnees, air_donnees),
                     lsim::lora::Status::Ok);
            const std::vector<DeviceRadio> radios{radio_long, sf7};
            const std::vector<UplinkRecord> ups{
                up(0, 0, 10'000'000, UplinkOutcome::Received),
                up(1, 25'000'000 - 10'000'000, 10'000'000, UplinkOutcome::Received)};
            const auto bu = jouer(radios, ups, o, 12);
            CHECK_EQ(bu.size(), std::size_t{1});
            CHECK_EQ(bu[0].start_ns, kS + 10'000'000);
            CHECK_EQ(bu[0].end_ns, kS + 10'000'000 + air_donnees);
        }

    // -------------------------------------------------------------------------------
    // 13. I6-c : limites de charge par fenêtre. R-N1 : chaque fenêtre est validée contre le N
    //     de son propre DR. R-N2 : une fenêtre inéligible n'est jamais demandée — elle ne
    //     réserve rien et n'occupe pas l'émetteur. R-N3 : l'inéligibilité de RX1 ne clôt pas
    //     l'examen, RX2 reste demandable.
    {
        const DeviceRadio sf7 = radio_sf7();
        const std::vector<DeviceRadio> radios{sf7, sf7};
        // Deux montantes reçues, assez espacées pour qu'aucune ne masque l'autre.
        const std::vector<UplinkRecord> ups{
            up(0, 0, 10'000'000, UplinkOutcome::Received),
            up(1, 5 * kS, 10'000'000, UplinkOutcome::Received)};

        PlanOptions o;
        o.confirmed_uplinks = true;
        o.downlink_every = 1;  // descente applicative : soumise à N
        o.downlink_payload_bytes = 40;
        o.rx2_fallback = true;
        const std::vector<DeviceRx2> rx2(2, DeviceRx2{869'525'000, 12, 125'000});

        const auto jouer_limites = [&](const std::vector<DeviceLimits>* lim) {
            std::vector<Event> ev;
            std::vector<Interval> bu;
            CHECK_EQ(plan_downlinks(ups, radios, o, &rx2, lim, ev, bu), PlanStatus::Ok);
            return bu;
        };

        // 13a. Aucune fenêtre éligible (N = 0 < 40) : rien n'est émis, rien n'est réservé.
        {
            const std::vector<DeviceLimits> nuls(2, DeviceLimits{0, 0});
            CHECK_TRUE(jouer_limites(&nuls).empty());
        }
        // 13b. RX1 seule éligible : émission en RX1, à l'ouverture exacte de RX1.
        {
            const std::vector<DeviceLimits> larges(2, DeviceLimits{51, 0});
            const auto bu = jouer_limites(&larges);
            CHECK_EQ(bu.size(), std::size_t{2});
            if (bu.size() >= 1) {
                CHECK_EQ(bu[0].start_ns, kS + 10'000'000);  // A6 : ouverture exacte
            }
        }
        // 13c. RX1 inéligible, RX2 éligible (R-N3) : la descente part en RX2, à l'ouverture de
        //      RX2 et avec la durée RX2 — jamais celle de RX1.
        {
            const std::vector<DeviceLimits> report(2, DeviceLimits{39, 51});
            const auto bu = jouer_limites(&report);
            CHECK_EQ(bu.size(), std::size_t{2});
            DeviceRadio r2 = sf7;
            r2.rx1_sf = 12;
            std::int64_t air_rx2 = 0;
            CHECK_EQ(downlink_airtime_ns(r2, 13 + 40, air_rx2), lsim::lora::Status::Ok);
            if (bu.size() >= 1) {
                CHECK_EQ(bu[0].start_ns, 2 * kS + 10'000'000);  // RECEIVE_DELAY2
                CHECK_EQ(bu[0].end_ns - bu[0].start_ns, air_rx2);
            }
        }
        // 13d. Sans table de limites, le comportement est exactement celui d'avant I6-c.
        {
            const auto bu = jouer_limites(nullptr);
            CHECK_EQ(bu.size(), std::size_t{2});
            if (bu.size() >= 1) {
                CHECK_EQ(bu[0].start_ns, kS + 10'000'000);
            }
        }
        // 13e. Un ACK n'est jamais refusé pour capacité : N nul partout, l'ACK passe.
        {
            PlanOptions ack = o;
            ack.downlink_every = 0;  // aucun downlink de données
            const std::vector<DeviceLimits> nuls(2, DeviceLimits{0, 0});
            std::vector<Event> ev;
            std::vector<Interval> bu;
            CHECK_EQ(plan_downlinks(ups, radios, ack, &rx2, &nuls, ev, bu), PlanStatus::Ok);
            CHECK_EQ(bu.size(), std::size_t{2});
        }
        // 13f. Validations : longueur inexacte et N hors bornes sont refusées, sans lecture.
        {
            std::vector<Event> ev;
            std::vector<Interval> bu;
            const std::vector<DeviceLimits> court(1, DeviceLimits{51, 51});
            CHECK_EQ(plan_downlinks(ups, radios, o, &rx2, &court, ev, bu),
                     PlanStatus::InvalidInput);
            const std::vector<DeviceLimits> hors{DeviceLimits{243, 51}, DeviceLimits{51, 51}};
            CHECK_EQ(plan_downlinks(ups, radios, o, &rx2, &hors, ev, bu),
                     PlanStatus::InvalidInput);
            const std::vector<DeviceLimits> neg{DeviceLimits{-1, 51}, DeviceLimits{51, 51}};
            CHECK_EQ(plan_downlinks(ups, radios, o, &rx2, &neg, ev, bu),
                     PlanStatus::InvalidInput);
        }
        // 13g. Parité : le planificateur incrémental applique la même règle, à l'identique.
        {
            const std::vector<DeviceLimits> report(2, DeviceLimits{39, 51});
            std::vector<Event> ev;
            std::vector<Interval> par_lot;
            CHECK_EQ(plan_downlinks(ups, radios, o, &rx2, &report, ev, par_lot),
                     PlanStatus::Ok);
            DownlinkScheduler incr(radios, o, &rx2, &report);
            CHECK_EQ(incr.status(), PlanStatus::Ok);
            std::vector<Interval> causal;
            for (const UplinkRecord& u : ups) {
                for (const Interval& i : incr.on_received(u.device, u.end_ns, rx2[u.device])) {
                    causal.push_back(i);
                }
            }
            for (const Interval& i : incr.drain()) causal.push_back(i);
            CHECK_EQ(causal.size(), par_lot.size());
            for (std::size_t k = 0; k < std::min(causal.size(), par_lot.size()); ++k) {
                CHECK_EQ(causal[k].start_ns, par_lot[k].start_ns);
                CHECK_EQ(causal[k].end_ns, par_lot[k].end_ns);
            }
        }
        // 13h. Le constructeur du planificateur valide la table : longueur et bornes.
        {
            const std::vector<DeviceLimits> court(1, DeviceLimits{51, 51});
            CHECK_EQ(DownlinkScheduler(radios, o, &rx2, &court).status(),
                     PlanStatus::InvalidInput);
            const std::vector<DeviceLimits> hors{DeviceLimits{243, 51}, DeviceLimits{51, 51}};
            CHECK_EQ(DownlinkScheduler(radios, o, &rx2, &hors).status(),
                     PlanStatus::InvalidInput);
        }
    }
    }
}
