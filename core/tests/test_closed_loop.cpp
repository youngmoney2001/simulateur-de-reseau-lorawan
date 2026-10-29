// SPDX-License-Identifier: Apache-2.0
// Boucle fermée (S2) : parité sans commande avec le chemin causal, convergence ADR,
// espacement du rapport cyclique, nouvel essai après perte pendant RX1.
#include <cmath>
#include <cstdint>
#include <vector>

#include "check.hpp"
#include "lsim/engine.hpp"

namespace {

using namespace lsim::sim;

constexpr SimTime kS = 1'000'000'000;

EndDeviceSpec dev(double x_m, std::uint8_t sf, SimTime offset_ns, SimTime period_ns,
                  std::uint32_t messages) {
    EndDeviceSpec d;
    d.position.x_m = x_m;
    d.spreading_factor = sf;
    d.payload_bytes = 10;
    d.tx_power_dbm = 14.0;
    d.start_offset_ns = offset_ns;
    d.period_ns = period_ns;
    d.messages = messages;
    d.duty_cycle = 1.0;
    return d;
}

lsim::plan::DeviceRadio radio() {
    lsim::plan::DeviceRadio r;
    r.freq_hz = 868'100'000;
    r.rx1_hz = 868'100'000;
    r.tx_power_dbm = 14.0;
    r.rx1_bw_hz = 125'000;
    return r;
}

// Table régionale à débits décroissants SF12..SF7 ; index de puissance 0..7 valides (pas 2 dB),
// PIRE du plan non définie (+inf) ; limite réglementaire 1 (aucune) par défaut.
LoopRegion region() {
    LoopRegion r;
    for (std::size_t i = 0; i < 6; ++i) {
        r.dr_sf[i] = static_cast<std::uint8_t>(12 - i);
    }
    r.max_dr = 5;
    r.max_tx_power_index = 7;
    r.power_step_tenth_db = 20;
    for (std::size_t i = 0; i <= 7; ++i) r.duty_limit[i] = 1.0;
    return r;
}

void test_plan_max_eirp_caps_index_zero() {
    // PIRE du plan 12 dBm, puissance configurée 14 dBm : l'index 0 vaut 12 dBm (-2 dB de RSSI).
    const EndDeviceSpec d[] = {dev(500.0, 7, 0, 60 * kS, 1)};
    lsim::plan::DeviceRadio rv[1] = {radio()};
    DeviceStats st[1];
    SimulationStats tot;
    LoopResult free_res;
    LoopResult capped_res;
    LoopRegion free_r[1] = {region()};
    LoopRegion capped_r[1] = {region()};
    capped_r[0].max_eirp_dbm = 12.0;
    LoopOptions opt;
    CHECK_EQ(static_cast<int>(simulate_closed_loop(d, 1, rv, free_r, GatewaySpec{}, PropagationSpec{},
                                                   nullptr, opt, st, tot, free_res)),
             0);
    CHECK_EQ(static_cast<int>(simulate_closed_loop(d, 1, rv, capped_r, GatewaySpec{}, PropagationSpec{},
                                                   nullptr, opt, st, tot, capped_res)),
             0);
    CHECK_EQ(free_res.uplinks.size(), std::size_t{1});
    CHECK_EQ(capped_res.uplinks.size(), std::size_t{1});
    if (free_res.uplinks.size() == 1 && capped_res.uplinks.size() == 1) {
        const double delta = free_res.uplinks[0].rssi_dbm - capped_res.uplinks[0].rssi_dbm;
        CHECK_TRUE(std::abs(delta - 2.0) < 1e-9);
    }
}

void test_regulatory_limit_applies_without_command() {
    // Limite réglementaire 1 % à l'index 0, aucune commande : repos de 99 airtimes après chaque émission.
    const EndDeviceSpec d[] = {dev(10.0, 12, 0, 4 * kS, 10)};
    lsim::plan::DeviceRadio rv[1] = {radio()};
    LoopRegion regions[1] = {region()};
    regions[0].duty_limit[0] = 0.01;
    DeviceStats st[1];
    SimulationStats tot;
    LoopResult res;
    LoopOptions opt;
    CHECK_EQ(static_cast<int>(simulate_closed_loop(d, 1, rv, regions, GatewaySpec{}, PropagationSpec{},
                                                   nullptr, opt, st, tot, res)),
             0);
    int checked = 0;
    for (std::size_t k = 0; k + 1 < res.uplinks.size(); ++k) {
        const LoopUplink& next = res.uplinks[k + 1];
        const SimTime air = res.uplinks[k].end_ns - res.uplinks[k].start_ns;
        CHECK_TRUE(next.start_ns - res.uplinks[k].end_ns >= 99 * air);
        ++checked;
    }
    CHECK_TRUE(checked > 3);
}

void test_no_command_parity_with_causal() {
    const EndDeviceSpec d[] = {dev(100.0, 7, 0, 30 * kS, 20), dev(2500.0, 9, 3 * kS, 30 * kS, 20),
                               dev(900.0, 7, 7 * kS, 30 * kS, 20)};
    lsim::plan::DeviceRadio rv[3] = {radio(), radio(), radio()};
    DeviceStats causal_stats[3];
    DeviceStats loop_stats[3];
    SimulationStats causal_tot;
    SimulationStats loop_tot;

    CausalDownlinks cd;
    cd.radios.assign(rv, rv + 3);
    std::vector<lsim::plan::Interval> busy;
    cd.busy_out = &busy;
    CHECK_EQ(static_cast<int>(simulate_uplinks(d, 3, GatewaySpec{}, PropagationSpec{}, causal_stats,
                                               causal_tot, nullptr, nullptr, nullptr, nullptr, &cd)),
             0);

    LoopRegion regions[3] = {region(), region(), region()};
    LoopResult res;
    LoopOptions opt;
    CHECK_EQ(static_cast<int>(simulate_closed_loop(d, 3, rv, regions, GatewaySpec{}, PropagationSpec{},
                                                   nullptr, opt, loop_stats, loop_tot, res)),
             0);
    CHECK_EQ(res.downlinks.size(), std::size_t{0});
    CHECK_EQ(res.uplinks.size(), std::size_t{60});
    CHECK_EQ(loop_tot.sent, causal_tot.sent);
    CHECK_EQ(loop_tot.received, causal_tot.received);
    CHECK_EQ(loop_tot.lost_sensitivity, causal_tot.lost_sensitivity);
    CHECK_EQ(loop_tot.lost_collision, causal_tot.lost_collision);
    CHECK_EQ(loop_tot.lost_gateway_busy, causal_tot.lost_gateway_busy);
    for (int i = 0; i < 3; ++i) {
        CHECK_EQ(loop_stats[i].sent, causal_stats[i].sent);
        CHECK_EQ(loop_stats[i].received, causal_stats[i].received);
        CHECK_EQ(loop_stats[i].lost_collision, causal_stats[i].lost_collision);
    }
}

void test_adr_converges_to_sf7() {
    // Dispositif proche de la passerelle, débit initial SF12 : l'ADR doit descendre à SF7.
    const EndDeviceSpec d[] = {dev(10.0, 12, 0, 60 * kS, 300)};
    lsim::plan::DeviceRadio rv[1] = {radio()};
    LoopRegion regions[1] = {region()};
    DeviceStats st[1];
    SimulationStats tot;
    LoopResult res;
    LoopOptions opt;
    opt.adr = true;
    CHECK_EQ(static_cast<int>(simulate_closed_loop(d, 1, rv, regions, GatewaySpec{}, PropagationSpec{},
                                                   nullptr, opt, st, tot, res)),
             0);
    CHECK_EQ(res.uplinks.size(), std::size_t{300});
    CHECK_EQ(res.uplinks.back().spreading_factor, std::uint8_t{7});
    bool adr_delivered = false;
    for (const LoopDownlink& dl : res.downlinks) {
        if ((dl.commands & kLoopCmdLinkAdr) != 0 && dl.delivered) adr_delivered = true;
    }
    CHECK_TRUE(adr_delivered);
}

void test_duty_cycle_spacing_after_apply() {
    // 1/16 : après l'application, deux débuts consécutifs sont séparés d'au moins 16 fois l'airtime.
    // SF12 et période de 4 s : la RX1 reste libre (aucune émission pendant [fin+1 s, fin+2 s]) et
    // le rapport cyclique, plus contraignant que la période, décale les émissions suivantes.
    const EndDeviceSpec d[] = {dev(10.0, 12, 0, 4 * kS, 40)};
    lsim::plan::DeviceRadio rv[1] = {radio()};
    LoopRegion regions[1] = {region()};
    DeviceStats st[1];
    SimulationStats tot;
    LoopResult res;
    LoopOptions opt;
    opt.duty_cycle = true;
    opt.duty_cycle_exponent = 4;
    CHECK_EQ(static_cast<int>(simulate_closed_loop(d, 1, rv, regions, GatewaySpec{}, PropagationSpec{},
                                                   nullptr, opt, st, tot, res)),
             0);
    SimTime apply = -1;
    for (const LoopDownlink& dl : res.downlinks) {
        if ((dl.commands & kLoopCmdDutyCycle) != 0 && dl.delivered) {
            const SimTime end = dl.start_ns >= 0 ? dl.start_ns + dl.air_ns : dl.t_open;
            const SimTime a = std::max(dl.t_open + kS, end);
            if (apply < 0 || a < apply) apply = a;
        }
    }
    CHECK_TRUE(apply > 0);
    int checked = 0;
    // Repos après l'émission terminée : le début suivant est au plus tôt à
    // fin_précédente + airtime_précédent * (1/rapport - 1), soit 15 airtimes pour 1/16.
    for (std::size_t k = 0; k + 1 < res.uplinks.size(); ++k) {
        const LoopUplink& prev = res.uplinks[k];
        const LoopUplink& next = res.uplinks[k + 1];
        if (next.start_ns < apply) continue;
        const SimTime air_prev = prev.end_ns - prev.start_ns;
        CHECK_TRUE(next.start_ns - prev.end_ns >= 15 * air_prev);
        ++checked;
    }
    CHECK_TRUE(checked > 10);
    CHECK_EQ(res.uplinks.size(), std::size_t{40});
}

void test_duty_convention_differs_from_start_airtime() {
    // Même scénario que le test d'espacement : après DutyCycleAns, l'uplink 1 est plus long
    // (octets MAC). Convention cible (airtime terminé) : le repos suit l'émission terminée. La
    // convention historique (airtime de l'émission qui démarre) donnerait un autre repos ; ce test
    // exige que les deux diffèrent sur ce cas, pour que la migration reste visible.
    const EndDeviceSpec d[] = {dev(10.0, 12, 0, 4 * kS, 40)};
    lsim::plan::DeviceRadio rv[1] = {radio()};
    LoopRegion regions[1] = {region()};
    DeviceStats st[1];
    SimulationStats tot;
    LoopResult res;
    LoopOptions opt;
    opt.duty_cycle = true;
    opt.duty_cycle_exponent = 4;
    CHECK_EQ(static_cast<int>(simulate_closed_loop(d, 1, rv, regions, GatewaySpec{}, PropagationSpec{},
                                                   nullptr, opt, st, tot, res)),
             0);
    int differs = 0;
    for (std::size_t k = 0; k + 1 < res.uplinks.size(); ++k) {
        const LoopUplink& prev = res.uplinks[k];
        const LoopUplink& next = res.uplinks[k + 1];
        const SimTime air_prev = prev.end_ns - prev.start_ns;
        const SimTime air_next = next.end_ns - next.start_ns;
        const SimTime gap = next.start_ns - prev.end_ns;
        const bool cible = gap >= 15 * air_prev;
        const bool historique = gap >= 15 * air_next;
        CHECK_TRUE(cible);  // la cible est respectée partout
        if (cible && !historique) ++differs;
    }
    CHECK_TRUE(differs >= 1);  // au moins un repos où la convention historique serait violée
}

void test_next_uplink_waits_for_rx2_end() {
    // TS001 §3.3.6 (décision C1) : le dispositif n'émet pas avant la fin de RX2 de l'uplink
    // précédent (fin + 3 s). Avec une période de 1,5 s, chaque uplink suivant est donc décalé
    // jusqu'à fin + 3 s. La descente, reçue en RX1 car le dispositif ne transmet pas pendant
    // RX1, livre la commande DutyCycleReq, et les émissions ne se chevauchent jamais.
    const EndDeviceSpec d[] = {dev(10.0, 7, 0, 3 * kS / 2, 5)};
    lsim::plan::DeviceRadio rv[1] = {radio()};
    LoopRegion regions[1] = {region()};
    DeviceStats st[1];
    SimulationStats tot;
    LoopResult res;
    LoopOptions opt;
    opt.duty_cycle = true;
    opt.duty_cycle_exponent = 2;
    CHECK_EQ(static_cast<int>(simulate_closed_loop(d, 1, rv, regions, GatewaySpec{}, PropagationSpec{},
                                                   nullptr, opt, st, tot, res)),
             0);
    CHECK_EQ(res.uplinks.size(), std::size_t{5});
    if (res.uplinks.size() != 5) return;
    CHECK_EQ(res.uplinks[0].start_ns, SimTime{0});
    for (std::size_t k = 1; k < res.uplinks.size(); ++k) {
        CHECK_TRUE(res.uplinks[k].start_ns >= res.uplinks[k - 1].end_ns + 2 * kS + kS);
        CHECK_EQ(res.uplinks[k].start_ns, res.uplinks[k - 1].end_ns + 3 * kS);
    }
    // Une seule descente : la commande DutyCycleReq est livrée à la première RX1 (le dispositif
    // n'émet pas pendant RX1), puis la file est vide et aucune descente n'est plus nécessaire.
    CHECK_EQ(res.downlinks.size(), std::size_t{1});
    if (res.downlinks.size() != 1) return;
    const LoopDownlink& dl = res.downlinks[0];
    CHECK_EQ(dl.uplink, std::uint32_t{0});
    CHECK_TRUE(!dl.device_missed);
    CHECK_EQ(dl.t_open, res.uplinks[0].end_ns + kS);  // ouverture de RX1
    CHECK_TRUE(dl.delivered);                          // reçue en RX1, sans repli
    CHECK_TRUE((dl.commands & kLoopCmdDutyCycle) != 0);
}

void test_rx2_fallback_when_gateway_busy() {
    // TS001 §3.3.1 et §3.3.3 (décision C3) : si la passerelle ne peut pas émettre dans RX1, la
    // descente part dans RX2 (fin + 2 s, SF12 par défaut EU868).
    // Dispositif 0 : SF12, uplink long, descente RX1 de ~1,5 s qui occupe la passerelle.
    // Dispositif 1 : SF7, émis pendant cette occupation ; sa RX1 déborde, donc RX2 est utilisée.
    const EndDeviceSpec d[] = {
        dev(10.0, 12, 0, 60 * kS, 1),
        dev(10.0, 7, 12 * kS / 10, 60 * kS, 1),  // RX1 occupée, RX2 libre (descente du dispositif 0 jusqu'à 3,15 s)
    };
    lsim::plan::DeviceRadio rv[2] = {radio(), radio()};
    LoopRegion regions[2] = {region(), region()};
    DeviceStats st[2];
    SimulationStats tot;
    LoopResult res;
    LoopOptions opt;
    const LoopMacSlot slots[] = {
        {0, 1, 0, kLoopMacLinkCheck},
        {1, 1, 0, kLoopMacLinkCheck},
    };
    opt.mac = slots;
    opt.mac_count = 2;
    CHECK_EQ(static_cast<int>(simulate_closed_loop(d, 2, rv, regions, GatewaySpec{}, PropagationSpec{},
                                                   nullptr, opt, st, tot, res)),
             0);
    CHECK_EQ(res.uplinks.size(), std::size_t{2});
    CHECK_EQ(res.downlinks.size(), std::size_t{2});
    if (res.uplinks.size() != 2 || res.downlinks.size() != 2) return;
    // Trouver la descente de chaque dispositif.
    const LoopDownlink* d0 = nullptr;
    const LoopDownlink* d1 = nullptr;
    for (const LoopDownlink& dl : res.downlinks) {
        if (dl.device == 0) d0 = &dl;
        if (dl.device == 1) d1 = &dl;
    }
    if (d0 == nullptr || d1 == nullptr) {
        CHECK_TRUE(false);
        return;
    }
    // Dispositif 0 : RX1 normale.
    CHECK_EQ(d0->t_open, res.uplinks[d0->uplink].end_ns + kS);
    CHECK_TRUE(d0->start_ns >= 0);
    // Dispositif 1 : RX1 refusée (passerelle occupée au-delà de la fenêtre), RX2 utilisée.
    CHECK_EQ(d1->t_open, res.uplinks[d1->uplink].end_ns + 2 * kS);
    CHECK_EQ(d1->start_ns, d1->t_open);  // départ exact à l'ouverture de RX2 (TS001 §3.3.5)
    CHECK_TRUE(d1->delivered);
}

void test_no_shift_inside_busy_windows() {
    // TS001 §3.3.5 (A6) : la passerelle ne décale pas une descente dans la fenêtre. Ici la RX1 du
    // dispositif 1 (ouverte à 2,04 s) et sa RX2 (3,04 s) tombent toutes deux pendant la descente du
    // dispositif 0 (jusqu'à 3,15 s) : la descente est perdue, sans créneau décalé.
    const EndDeviceSpec d[] = {
        dev(10.0, 12, 0, 60 * kS, 1),
        dev(10.0, 7, 1 * kS, 60 * kS, 1),
    };
    lsim::plan::DeviceRadio rv[2] = {radio(), radio()};
    LoopRegion regions[2] = {region(), region()};
    DeviceStats st[2];
    SimulationStats tot;
    LoopResult res;
    LoopOptions opt;
    const LoopMacSlot slots[] = {
        {0, 1, 0, kLoopMacLinkCheck},
        {1, 1, 0, kLoopMacLinkCheck},
    };
    opt.mac = slots;
    opt.mac_count = 2;
    CHECK_EQ(static_cast<int>(simulate_closed_loop(d, 2, rv, regions, GatewaySpec{}, PropagationSpec{},
                                                   nullptr, opt, st, tot, res)),
             0);
    CHECK_EQ(res.downlinks.size(), std::size_t{2});
    if (res.downlinks.size() != 2) return;
    for (const LoopDownlink& dl : res.downlinks) {
        if (dl.device != 1) continue;
        CHECK_EQ(dl.start_ns, SimTime{-1});  // aucun créneau : pas de décalage
        CHECK_TRUE(!dl.delivered);
    }
}

void test_mac_reservations_and_answers() {
    // Trois émissions à 60 s, passerelle proche. Calendrier : LinkCheckReq au rang 1 (1 octet
    // réservé), DevStatusReq au rang 2, DeviceTimeReq au rang 3 avec 3 octets réservés
    // (DevStatusAns, réservée au rang suivant la demande). La descente de l'uplink de rang 1
    // porte LinkCheckAns, celle du rang 2 DevStatusReq ; DevStatusAns est portée par le rang 3.
    const EndDeviceSpec d[] = {dev(10.0, 7, 0, 60 * kS, 3)};
    lsim::plan::DeviceRadio rv[1] = {radio()};
    LoopRegion regions[1] = {region()};
    const LoopMacSlot slots[] = {
        {0, 1, 1, kLoopMacLinkCheck},
        {0, 2, 0, kLoopMacDevStatus},
        {0, 3, 3, kLoopMacDeviceTime},
    };
    DeviceStats st[1];
    SimulationStats tot;
    LoopResult res;
    LoopOptions opt;
    opt.mac = slots;
    opt.mac_count = 3;
    CHECK_EQ(static_cast<int>(simulate_closed_loop(d, 1, rv, regions, GatewaySpec{}, PropagationSpec{},
                                                   nullptr, opt, st, tot, res)),
             0);
    CHECK_EQ(res.uplinks.size(), std::size_t{3});
    CHECK_EQ(res.downlinks.size(), std::size_t{3});
    if (res.uplinks.size() != 3 || res.downlinks.size() != 3) return;
    // Octets réservés dans l'airtime : l'uplink 3 (13 octets) dure plus que l'uplink 1 (11).
    CHECK_TRUE(res.uplinks[2].end_ns - res.uplinks[2].start_ns >
               res.uplinks[0].end_ns - res.uplinks[0].start_ns);
    CHECK_TRUE(res.uplinks[0].end_ns - res.uplinks[0].start_ns ==
               res.uplinks[1].end_ns - res.uplinks[1].start_ns);
    // Commandes par descente (une descente par uplink, dans l'ordre).
    for (std::size_t k = 0; k < 3; ++k) {
        CHECK_EQ(static_cast<std::size_t>(res.downlinks[k].uplink), k);
        CHECK_TRUE(res.downlinks[k].delivered);
        CHECK_EQ(static_cast<int>(res.downlinks[k].kind), 3);
    }
    CHECK_TRUE((res.downlinks[0].commands & kLoopCmdLinkCheck) != 0);
    CHECK_TRUE((res.downlinks[0].commands & kLoopCmdDevStatus) == 0);
    CHECK_TRUE((res.downlinks[1].commands & kLoopCmdDevStatus) != 0);
    CHECK_TRUE((res.downlinks[2].commands & kLoopCmdDeviceTime) != 0);
    // DevStatusReq dans la descente de l'uplink de rang 2 (indice 1), livrée : DevStatusAns est
    // portée par l'uplink de rang 3 (indice 2), et seulement par lui.
    CHECK_TRUE((res.uplinks[0].answer_mask & 4) == 0);
    CHECK_TRUE((res.uplinks[1].answer_mask & 4) == 0);
    CHECK_TRUE((res.uplinks[2].answer_mask & 4) != 0);
    // Calendrier invalide : doublon, rang hors plage, octets au-delà de 15.
    const LoopMacSlot dup[] = {{0, 1, 1, 0}, {0, 1, 0, kLoopMacLinkCheck}};
    LoopOptions bad = opt;
    bad.mac = dup;
    bad.mac_count = 2;
    CHECK_EQ(static_cast<int>(simulate_closed_loop(d, 1, rv, regions, GatewaySpec{}, PropagationSpec{},
                                                   nullptr, bad, st, tot, res)),
             static_cast<int>(SimStatus::InvalidInput));
    const LoopMacSlot range[] = {{0, 4, 1, 0}};
    bad.mac = range;
    bad.mac_count = 1;
    CHECK_EQ(static_cast<int>(simulate_closed_loop(d, 1, rv, regions, GatewaySpec{}, PropagationSpec{},
                                                   nullptr, bad, st, tot, res)),
             static_cast<int>(SimStatus::InvalidInput));
    const LoopMacSlot big[] = {{0, 1, 16, 0}};
    bad.mac = big;
    bad.mac_count = 1;
    CHECK_EQ(static_cast<int>(simulate_closed_loop(d, 1, rv, regions, GatewaySpec{}, PropagationSpec{},
                                                   nullptr, bad, st, tot, res)),
             static_cast<int>(SimStatus::InvalidInput));
}

// File MAC : les commandes à état (LinkADR 5, DutyCycle 2) restent en attente quand aucune
// descente n'est reçue ; avec LinkCheck (3), DeviceTime (6) et DevStatus (1) à chaque uplink, le
// total dépasse 15 octets. Les commandes en trop sont reportées puis expirent ; rien ne se tronque.
void test_mac_queue_defers_expires_and_conserves() {
    const std::uint32_t messages = 60;
    const EndDeviceSpec d[] = {dev(10.0, 12, 0, 60 * kS, messages)};
    lsim::plan::DeviceRadio rv[1] = {radio()};
    LoopRegion regions[1] = {region()};
    std::vector<LoopMacSlot> slots;
    for (std::uint32_t r = 1; r <= messages; ++r) {
        slots.push_back(LoopMacSlot{0, r, 0, static_cast<std::uint8_t>(kLoopMacLinkCheck |
                                                                       kLoopMacDeviceTime |
                                                                       kLoopMacDevStatus)});
    }
    DeviceStats st[1];
    SimulationStats tot;
    LoopResult res;
    LoopOptions opt;
    opt.adr = true;
    opt.duty_cycle = true;
    opt.duty_cycle_exponent = 2;
    opt.protocol.device_rx_offset_db = 200.0;  // aucune descente reçue : ADR et DutyCycle restent en attente
    opt.mac = slots.data();
    opt.mac_count = slots.size();
    CHECK_EQ(static_cast<int>(simulate_closed_loop(d, 1, rv, regions, GatewaySpec{}, PropagationSpec{},
                                                   nullptr, opt, st, tot, res)),
             0);
    const LoopMacQueueStats& q = res.mac;
    CHECK_TRUE(q.deferred > 0);            // la file a dû reporter (17 octets à offrir)
    CHECK_TRUE(q.expired > 0);             // au-delà de 3 reports, une commande expire
    CHECK_EQ(q.enqueued, q.dispatched + q.expired + q.pending_at_end);
    CHECK_TRUE(q.dispatch_lost > 0);       // descentes non reçues portant des commandes de la file
    CHECK_TRUE(q.dispatch_lost <= q.dispatched);
    for (const LoopDownlink& dl : res.downlinks) {
        CHECK_TRUE(!dl.delivered);         // le décalage de RX1 rend chaque descente non reçue
    }
}

// Expiration immédiate : sans report autorisé, toute commande qui ne tient pas expire au premier
// report. Les reports et les expirations coïncident.
void test_mac_queue_zero_deferrals_expires_at_once() {
    const EndDeviceSpec d[] = {dev(10.0, 12, 0, 60 * kS, 60)};
    lsim::plan::DeviceRadio rv[1] = {radio()};
    LoopRegion regions[1] = {region()};
    std::vector<LoopMacSlot> slots;
    for (std::uint32_t r = 1; r <= 60; ++r) {
        slots.push_back(LoopMacSlot{0, r, 0, static_cast<std::uint8_t>(kLoopMacLinkCheck |
                                                                       kLoopMacDeviceTime |
                                                                       kLoopMacDevStatus)});
    }
    DeviceStats st[1];
    SimulationStats tot;
    LoopResult res;
    LoopOptions opt;
    opt.adr = true;
    opt.duty_cycle = true;
    opt.duty_cycle_exponent = 2;
    opt.protocol.device_rx_offset_db = 200.0;
    opt.mac_max_deferrals = 0;
    opt.mac = slots.data();
    opt.mac_count = slots.size();
    CHECK_EQ(static_cast<int>(simulate_closed_loop(d, 1, rv, regions, GatewaySpec{}, PropagationSpec{},
                                                   nullptr, opt, st, tot, res)),
             0);
    CHECK_TRUE(res.mac.deferred > 0);
    CHECK_EQ(res.mac.expired, res.mac.deferred);
    CHECK_EQ(res.mac.enqueued, res.mac.dispatched + res.mac.expired + res.mac.pending_at_end);
}


// Validation de la file : vérifie le cycle de vie de chaque commande (journal mac_items) et les
// invariants des compteurs, sur une charge réaliste (plusieurs dispositifs, descentes perdues,
// uplinks porteurs perdus, expirations).
void check_mac_lifecycle(const LoopResult& res, std::uint32_t max_deferrals) {
    const LoopMacQueueStats& q = res.mac;
    // Invariants de comptage.
    CHECK_EQ(q.enqueued, q.dispatched + q.expired + q.pending_at_end);
    CHECK_EQ(q.dispatched, q.delivered + q.dispatch_lost);
    CHECK_TRUE(q.deferred >= q.expired);
    CHECK_EQ(static_cast<std::uint64_t>(res.mac_items.size()), q.enqueued);
    std::uint64_t sum_def = 0;
    std::uint64_t n_delivered = 0, n_lost = 0, n_expired = 0, n_queued = 0, n_dispatched = 0;
    for (const LoopMacItem& it : res.mac_items) {
        sum_def += it.deferrals;
        const bool answer = it.cmd == kLoopCmdLinkCheck || it.cmd == kLoopCmdDeviceTime;
        // Une commande est portée par une descente de même type, et une seule.
        switch (it.state) {
            case LoopMacState::Queued:
                ++n_queued;
                CHECK_TRUE(!answer);  // une réponse ne reste jamais en file
                CHECK_EQ(it.downlink, std::int64_t{-1});
                CHECK_TRUE(it.deferrals <= max_deferrals);  // jamais au-delà de la borne
                break;
            case LoopMacState::Expired:
                ++n_expired;
                CHECK_EQ(it.downlink, std::int64_t{-1});
                // Réponse : expire au premier report (fenêtres RX passées). Requête : après la borne.
                CHECK_EQ(static_cast<int>(it.deferrals),
                         answer ? 1 : static_cast<int>(max_deferrals) + 1);
                break;
            case LoopMacState::Delivered:
            case LoopMacState::Lost: {
                ++n_dispatched;
                if (it.state == LoopMacState::Delivered) ++n_delivered;
                else ++n_lost;
                CHECK_TRUE(it.downlink >= 0);
                if (it.downlink < 0) break;
                const LoopDownlink& dl = res.downlinks[static_cast<std::size_t>(it.downlink)];
                CHECK_EQ(dl.delivered, it.state == LoopMacState::Delivered);
                CHECK_TRUE((dl.commands & it.cmd) != 0);
                CHECK_TRUE(it.deferrals <= max_deferrals);
                // Réponse : servie dans la descente de son propre uplink, jamais une autre.
                if (answer) {
                    CHECK_EQ(static_cast<std::size_t>(dl.uplink), static_cast<std::size_t>(it.uplink));
                    CHECK_EQ(it.deferrals, std::uint8_t{0});
                }
                break;
            }
            case LoopMacState::Dispatched:
                CHECK_TRUE(false);  // état transitoire : aucun en fin de simulation
                break;
        }
        // Une commande n'est créée que par un uplink reçu : un uplink perdu ne porte rien.
        CHECK_TRUE(res.uplinks[it.uplink].outcome == TxOutcome::Received);
    }
    CHECK_EQ(sum_def, q.deferred);
    CHECK_EQ(n_dispatched, q.dispatched);
    CHECK_EQ(n_delivered, q.delivered);
    CHECK_EQ(n_lost, q.dispatch_lost);
    CHECK_EQ(n_expired, q.expired);
    CHECK_EQ(n_queued, q.pending_at_end);
}

// Charge réaliste : 8 dispositifs, SF mixtes, uplinks toutes les 3 s, RX1 décalée (pertes de
// descentes) et commandes au-delà de 15 octets ensemble (LinkADR, DutyCycle, LC, DT, DS).
void run_mixed_load(double rx_offset_db, LoopResult& res) {
    constexpr std::size_t kDevices = 8;
    const std::uint32_t messages = 40;
    std::vector<EndDeviceSpec> d;
    lsim::plan::DeviceRadio rv[kDevices];
    LoopRegion regions[kDevices];
    for (std::size_t k = 0; k < kDevices; ++k) {
        d.push_back(dev(1000.0 + 1500.0 * static_cast<double>(k), static_cast<std::uint8_t>(7 + k % 3),
                        static_cast<SimTime>(k) * 700'000'000, 3 * kS, messages));
        rv[k] = radio();
        regions[k] = region();
    }
    std::vector<LoopMacSlot> slots;
    for (std::uint32_t k = 0; k < kDevices; ++k) {
        for (std::uint32_t r = 1; r <= messages; ++r) {
            slots.push_back(LoopMacSlot{k, r, 0, static_cast<std::uint8_t>(
                                                     kLoopMacLinkCheck | kLoopMacDeviceTime | kLoopMacDevStatus)});
        }
    }
    DeviceStats st[kDevices];
    SimulationStats tot;
    LoopOptions opt;
    opt.adr = true;
    opt.duty_cycle = true;
    opt.duty_cycle_exponent = 2;
    opt.protocol.device_rx_offset_db = rx_offset_db;
    opt.mac = slots.data();
    opt.mac_count = slots.size();
    CHECK_EQ(static_cast<int>(simulate_closed_loop(d.data(), kDevices, rv, regions, GatewaySpec{},
                                                   PropagationSpec{}, nullptr, opt, st, tot, res)),
             0);
}

void test_mac_queue_lifecycle_under_mixed_load() {
    LoopResult res;
    run_mixed_load(5.0, res);
    CHECK_TRUE(res.mac.enqueued > 0);
    CHECK_TRUE(res.mac.delivered > 0);      // descentes reçues
    CHECK_TRUE(res.mac.dispatch_lost > 0);  // descentes non reçues
    // Expirations : aucune observée sous cette charge depuis le départ strict (A6) : ADR et DutyCycle ne
    // sont plus en attente en même temps lors des uplinks reçus. L'expiration est vérifiée par
    // `test_mac_queue_fairness_bounded_wait` et les tests déterministes de la file.
    // Réponses : expirent au premier report, donc deferred = expired ici ; seules les requêtes du
    // réseau (DevStatusReq, 1 octet) peuvent rester en file.
    CHECK_TRUE(res.mac.deferred >= res.mac.expired);
    std::size_t lost_carriers = 0;
    for (const LoopUplink& u : res.uplinks) lost_carriers += u.outcome != TxOutcome::Received;
    CHECK_TRUE(lost_carriers > 0);          // uplinks porteurs perdus : aucune commande créée
    check_mac_lifecycle(res, 3);
}

// Charge soutenue sans aucune descente reçue, un seul dispositif : LinkADR et DutyCycle restent
// en attente, LinkCheck, DeviceTime et DevStatus arrivent à chaque uplink. Équité : chaque type
// est dispatché au moins une fois, et aucune commande n'attend au-delà de `mac_max_deferrals`.
void test_mac_queue_fairness_bounded_wait() {
    const std::uint32_t messages = 80;
    const EndDeviceSpec d[] = {dev(10.0, 12, 0, 60 * kS, messages)};
    lsim::plan::DeviceRadio rv[1] = {radio()};
    LoopRegion regions[1] = {region()};
    std::vector<LoopMacSlot> slots;
    for (std::uint32_t r = 1; r <= messages; ++r) {
        slots.push_back(LoopMacSlot{0, r, 0, static_cast<std::uint8_t>(kLoopMacLinkCheck |
                                                                       kLoopMacDeviceTime |
                                                                       kLoopMacDevStatus)});
    }
    DeviceStats st[1];
    SimulationStats tot;
    LoopResult res;
    LoopOptions opt;
    opt.adr = true;
    opt.duty_cycle = true;
    opt.duty_cycle_exponent = 2;
    opt.protocol.device_rx_offset_db = 200.0;
    opt.mac = slots.data();
    opt.mac_count = slots.size();
    CHECK_EQ(static_cast<int>(simulate_closed_loop(d, 1, rv, regions, GatewaySpec{}, PropagationSpec{},
                                                   nullptr, opt, st, tot, res)),
             0);
    check_mac_lifecycle(res, opt.mac_max_deferrals);
    // Les requêtes du réseau (DevStatusReq) sont servies malgré les commandes à état.
    bool ds = false;
    for (const LoopMacItem& it : res.mac_items) {
        if (it.downlink >= 0 && it.cmd == kLoopCmdDevStatus) ds = true;
    }
    CHECK_TRUE(ds);
    // Une réponse ne peut pas attendre : elle est servie dans sa descente ou expire au premier report.
    // Sous charge avec LinkADR et DutyCycle en attente (8 octets), LinkCheckAns et DeviceTimeAns
    // se disputent la descente : l'une des deux expire, aucune n'est reportée.
    CHECK_TRUE(res.mac.expired > 0);
    CHECK_TRUE(res.mac.dispatched > 0);
    CHECK_EQ(res.mac.deferred >= res.mac.expired, true);
}

// Pas de retransmission : une commande perdue n'est jamais replacée dans une autre descente.
// Chaque commande dispatchée porte un seul indice de descente, et les descentes perdues
// ne portent que des commandes en état Lost.
void test_mac_no_retransmission_of_lost_answers() {
    LoopResult res;
    run_mixed_load(15.0, res);
    check_mac_lifecycle(res, 3);
    CHECK_TRUE(res.mac.dispatch_lost > 0);
    std::uint64_t in_lost_downlinks = 0;
    for (const LoopMacItem& it : res.mac_items) {
        if (it.downlink >= 0 && !res.downlinks[static_cast<std::size_t>(it.downlink)].delivered) {
            CHECK_TRUE(it.state == LoopMacState::Lost);
            ++in_lost_downlinks;
        }
    }
    CHECK_EQ(in_lost_downlinks, res.mac.dispatch_lost);
}

}  // namespace

void test_adr_ack_backoff_without_downlink() {
    // F14 (TS001 §4.3.1.1, RP002-1.0.5 §3.3) : aucune descente ne parvient au dispositif (sensibilité
    // réelle dégradée de 200 dB). ADRACKCnt atteint 64 : ADRACKReq. Sans descente pendant
    // LIMIT + DELAY = 96 uplinks, le débit baisse d'un cran au 97e uplink (puissance par défaut), puis
    // tous les DELAY = 32 uplinks : SF8 au rang 96, SF9 au rang 128, SF10 au rang 160.
    const EndDeviceSpec d[] = {dev(10.0, 7, 0, 60 * kS, 170)};
    lsim::plan::DeviceRadio rv[1] = {radio()};
    LoopRegion regions[1] = {region()};
    DeviceStats st[1];
    SimulationStats tot;
    LoopResult res;
    LoopOptions opt;
    opt.adr = true;
    opt.protocol.device_rx_offset_db = 200.0;
    CHECK_EQ(static_cast<int>(simulate_closed_loop(d, 1, rv, regions, GatewaySpec{}, PropagationSpec{},
                                                   nullptr, opt, st, tot, res)),
             0);
    CHECK_EQ(res.uplinks.size(), std::size_t{170});
    if (res.uplinks.size() != 170) return;
    CHECK_EQ(res.uplinks[95].spreading_factor, std::uint8_t{7});
    CHECK_EQ(res.uplinks[96].spreading_factor, std::uint8_t{8});
    CHECK_EQ(res.uplinks[127].spreading_factor, std::uint8_t{8});
    CHECK_EQ(res.uplinks[128].spreading_factor, std::uint8_t{9});
    CHECK_EQ(res.uplinks[160].spreading_factor, std::uint8_t{10});
    // ADRACKReq à partir du 64e uplink : une descente forcée est émise, perdue ici.
    CHECK_TRUE(res.downlinks.size() > 0);
    for (const LoopDownlink& dl : res.downlinks) CHECK_TRUE(!dl.delivered);
}

void test_adr_ack_counter_reset_by_downlink() {
    // F14 : des descentes reçues (ADRACKReq honoré à chaque 64 uplinks) remettent ADRACKCnt à 0 :
    // aucun backoff, donc le débit ne remonte jamais au cours des 170 uplinks, dispositif proche
    // partant de SF12 (l'ADR seul fait descendre le débit).
    const EndDeviceSpec d[] = {dev(10.0, 12, 0, 60 * kS, 170)};
    lsim::plan::DeviceRadio rv[1] = {radio()};
    LoopRegion regions[1] = {region()};
    DeviceStats st[1];
    SimulationStats tot;
    LoopResult res;
    LoopOptions opt;
    opt.adr = true;
    CHECK_EQ(static_cast<int>(simulate_closed_loop(d, 1, rv, regions, GatewaySpec{}, PropagationSpec{},
                                                   nullptr, opt, st, tot, res)),
             0);
    CHECK_EQ(res.uplinks.size(), std::size_t{170});
    if (res.uplinks.size() != 170) return;
    for (std::size_t k = 1; k < res.uplinks.size(); ++k) {
        CHECK_TRUE(res.uplinks[k].spreading_factor <= res.uplinks[k - 1].spreading_factor);
    }
    bool delivered_without_commands = false;
    for (const LoopDownlink& dl : res.downlinks) {
        if (dl.delivered && dl.commands == 0) delivered_without_commands = true;
    }
    CHECK_TRUE(delivered_without_commands);  // descente forcée par ADRACKReq, reçue
}

void run_closed_loop_tests() {
    test_mac_queue_lifecycle_under_mixed_load();
    test_mac_queue_fairness_bounded_wait();
    test_mac_no_retransmission_of_lost_answers();
    test_no_command_parity_with_causal();
    test_plan_max_eirp_caps_index_zero();
    test_regulatory_limit_applies_without_command();
    test_duty_convention_differs_from_start_airtime();
    test_adr_converges_to_sf7();
    test_duty_cycle_spacing_after_apply();
    test_next_uplink_waits_for_rx2_end();
    test_rx2_fallback_when_gateway_busy();
    test_no_shift_inside_busy_windows();
    test_adr_ack_backoff_without_downlink();
    test_adr_ack_counter_reset_by_downlink();
    test_mac_reservations_and_answers();
    test_mac_queue_defers_expires_and_conserves();
    test_mac_queue_zero_deferrals_expires_at_once();
}
