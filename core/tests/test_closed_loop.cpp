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

void test_retry_after_device_missed_rx1() {
    // Classe A : le dispositif émet toutes les 1,5 s, donc chaque uplink tombe dans la RX1 de
    // l'uplink précédent (fin + 1 s à fin + 2 s). Les descentes sont perdues, la commande
    // DutyCycleReq est retentée à chaque uplink reçu, et aucune émission n'est retardée.
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
    for (std::size_t k = 0; k < res.uplinks.size() && k < 5; ++k) {
        CHECK_EQ(res.uplinks[k].start_ns, SimTime(k) * 3 * kS / 2);
    }
    CHECK_EQ(res.downlinks.size(), std::size_t{5});
    if (res.downlinks.size() != 5) return;
    // Les quatre premières descentes sont perdues (émission du dispositif pendant la RX1)...
    for (std::size_t k = 0; k < 4; ++k) {
        CHECK_TRUE(res.downlinks[k].device_missed);
        CHECK_TRUE(!res.downlinks[k].delivered);
        CHECK_TRUE((res.downlinks[k].commands & kLoopCmdDutyCycle) != 0);  // retentée
    }
    // ...la dernière, sans émission pendant la RX1, livre la commande.
    CHECK_TRUE(!res.downlinks[4].device_missed);
    CHECK_TRUE(res.downlinks[4].delivered);
    CHECK_TRUE((res.downlinks[4].commands & kLoopCmdDutyCycle) != 0);
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

}  // namespace

void run_closed_loop_tests() {
    test_no_command_parity_with_causal();
    test_plan_max_eirp_caps_index_zero();
    test_regulatory_limit_applies_without_command();
    test_duty_convention_differs_from_start_airtime();
    test_adr_converges_to_sf7();
    test_duty_cycle_spacing_after_apply();
    test_retry_after_device_missed_rx1();
    test_mac_reservations_and_answers();
}
