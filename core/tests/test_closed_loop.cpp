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

void test_exact_overlap_accepts_window_before_later_emission() {
    // TS001 §3.3.5 (A6), vérification exacte : une fenêtre n'est indisponible que si une émission
    // planifiée la chevauche réellement. Y (SF10) occupe la passerelle à sa RX1 ; la RX1 de X tombe
    // dans cette émission, donc X bascule sur RX2 (+2 s), qui démarre plus tard. La RX1 de B est
    // postérieure à la fin de Y et antérieure au début de la RX2 de X : elle est libre et doit être
    // planifiée à l'instant exact. L'ancienne règle (fin maximale des émissions planifiées) la refusait.
    const EndDeviceSpec d[] = {
        dev(10.0, 10, 1 * kS, 3600 * kS, 1),        // Y
        dev(10.0, 8, 1'400'000'000, 3600 * kS, 1),  // X
        dev(10.0, 7, 1'850'000'000, 3600 * kS, 1),  // B
    };
    lsim::plan::DeviceRadio rv[3] = {radio(), radio(), radio()};
    LoopRegion regions[3] = {region(), region(), region()};
    const LoopMacSlot slots[] = {
        {0, 1, 0, kLoopMacLinkCheck},
        {1, 1, 0, kLoopMacLinkCheck},
        {2, 1, 0, kLoopMacLinkCheck},
    };
    DeviceStats st[3];
    SimulationStats tot;
    LoopResult res;
    LoopOptions opt;
    opt.mac = slots;
    opt.mac_count = 3;
    CHECK_EQ(static_cast<int>(simulate_closed_loop(d, 3, rv, regions, GatewaySpec{}, PropagationSpec{},
                                                   nullptr, opt, st, tot, res)),
             0);
    if (res.uplinks.size() != 3 || res.downlinks.size() != 3) {
        CHECK_TRUE(false);
        return;
    }
    const LoopUplink* up[3] = {nullptr, nullptr, nullptr};
    const LoopDownlink* dn[3] = {nullptr, nullptr, nullptr};
    for (const LoopUplink& u : res.uplinks) up[u.device] = &u;
    for (const LoopDownlink& l : res.downlinks) dn[l.device] = &l;
    for (int k = 0; k < 3; ++k) {
        CHECK_TRUE(up[k] != nullptr && dn[k] != nullptr);
        if (up[k] == nullptr || dn[k] == nullptr) return;
        CHECK_TRUE(up[k]->outcome == TxOutcome::Received);
    }
    // Préconditions : RX1 de X dans l'émission de Y (RX2 choisie), RX1 de B après la fin de Y.
    const SimTime y_end = dn[0]->start_ns + dn[0]->air_ns;
    CHECK_EQ(dn[0]->start_ns, dn[0]->t_open);
    CHECK_TRUE(up[1]->end_ns + kS >= dn[0]->start_ns && up[1]->end_ns + kS < y_end);
    CHECK_EQ(dn[1]->t_open, up[1]->end_ns + 2 * kS);  // X : RX1 bloquée, RX2
    CHECK_TRUE(up[2]->end_ns + kS >= y_end);
    // Résultat attendu : B est planifiée exactement à l'ouverture de sa RX1.
    CHECK_EQ(dn[2]->t_open, up[2]->end_ns + kS);
    CHECK_EQ(dn[2]->start_ns, dn[2]->t_open);
    CHECK_EQ(dn[1]->start_ns, dn[1]->t_open);
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

// TS001 §5 : LinkADRAns est obligatoire, et l'émetteur décide de réémettre à la réception d'une
// trame sans la réponse attendue. Aucun plafond normatif ni temporisation : tant que la réponse
// manque, chaque uplink reçu porte une descente avec LinkADRReq (ici jamais reçue, 200 dB).
void test_linkadr_reissued_on_each_uplink_without_answer() {
    const EndDeviceSpec d[] = {dev(10.0, 12, 0, 60 * kS, 120)};
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
    CHECK_EQ(res.uplinks.size(), std::size_t{120});
    if (res.uplinks.size() != 120) return;
    std::vector<bool> has_link_adr(res.uplinks.size(), false);
    for (const LoopDownlink& dl : res.downlinks) {
        CHECK_TRUE(!dl.delivered);
        if ((dl.commands & kLoopCmdLinkAdr) != 0) has_link_adr[static_cast<std::size_t>(dl.uplink)] = true;
    }
    // Première décision (SF12 vers SF7) : ADR a besoin de 20 trames, puis la commande reste en attente.
    std::size_t first = res.uplinks.size();
    for (std::size_t u = 0; u < has_link_adr.size(); ++u) {
        if (has_link_adr[u]) { first = u; break; }
    }
    CHECK_TRUE(first < res.uplinks.size());
    if (first >= res.uplinks.size()) return;
    // Au-delà de 8 essais (ancien plafond d'implémentation) : une descente LinkADR par uplink, jusqu'au dernier.
    CHECK_TRUE(res.uplinks.size() - first > 8);
    for (std::size_t u = first; u < res.uplinks.size(); ++u) CHECK_TRUE(has_link_adr[u]);
    // Jamais acquittée : le débit reste SF12 (pas de changement implicite).
    CHECK_EQ(res.uplinks.back().spreading_factor, std::uint8_t{12});
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

// Sensibilité absolue de passerelle (sensibilite-par-sf-v2). Un seul dispositif SF5 proche,
// sans commande ni confirmation : seule la sensibilité de la passerelle décide.
SimStatus run_absolute_sf5(double threshold_dbm, bool with_table, std::uint32_t present,
                           double offset_db, LoopResult& res, DeviceStats* st_out = nullptr) {
    // 3 km : RSSI vers −110 dBm, dans la plage des seuils validés.
    const EndDeviceSpec d[] = {dev(3000.0, 5, 0, 60 * kS, 3)};
    lsim::plan::DeviceRadio rv[1] = {radio()};
    LoopRegion regions[1] = {region()};
    DeviceStats st[1];
    SimulationStats tot;
    LoopOptions opt;
    GatewaySpec gw;
    gw.rx_sensitivity_offset_db = offset_db;
    if (with_table) {
        gw.absolute.enabled = true;
        gw.absolute.present = present;
        gw.absolute.dbm[0][0] = threshold_dbm;  // 125 kHz, SF5
    }
    const SimStatus status = simulate_closed_loop(d, 1, rv, regions, gw, PropagationSpec{}, nullptr,
                                                  opt, st, tot, res);
    if (st_out != nullptr) *st_out = st[0];
    return status;
}

void test_absolute_gateway_sf5_threshold() {
    // Seuil absolu −150 dBm : le signal proche passe ; seuil −20 dBm : tout est perdu.
    LoopResult ok;
    DeviceStats st_ok;
    CHECK_EQ(static_cast<int>(run_absolute_sf5(-150.0, true, 1U, 0.0, ok, &st_ok)), 0);
    CHECK_EQ(ok.uplinks.size(), std::size_t{3});
    CHECK_EQ(st_ok.lost_sensitivity, std::uint64_t{0});
    // Seuil juste au-dessus du RSSI mesuré (dans la plage validée −160..−60 dBm) : perte.
    if (ok.uplinks.empty()) return;
    const double rssi = ok.uplinks[0].rssi_dbm;
    const double above = rssi + 5.0;
    CHECK_TRUE(above <= -60.0);
    LoopResult ko;
    DeviceStats st_ko;
    CHECK_EQ(static_cast<int>(run_absolute_sf5(above, true, 1U, 0.0, ko, &st_ko)), 0);
    CHECK_EQ(st_ko.lost_sensitivity, std::uint64_t{3});
}

void test_absolute_gateway_refusals() {
    LoopResult res;
    // Paire SF5/125 kHz absente du profil : refus, pas de repli sur la table SX1276.
    CHECK_EQ(static_cast<int>(run_absolute_sf5(-150.0, true, 0U, 0.0, res)),
             static_cast<int>(SimStatus::InvalidInput));
    // Décalage non nul avec un modèle absolu : refus (pas de conversion implicite).
    CHECK_EQ(static_cast<int>(run_absolute_sf5(-150.0, true, 1U, 3.0, res)),
             static_cast<int>(SimStatus::InvalidInput));
    // ABI v1 (sans table) : SF5 reste refusé par la référence SX1276.
    CHECK_EQ(static_cast<int>(run_absolute_sf5(0.0, false, 0U, 0.0, res)),
             static_cast<int>(SimStatus::InvalidInput));
    // Valeur hors plage : refus.
    CHECK_EQ(static_cast<int>(run_absolute_sf5(-200.0, true, 1U, 0.0, res)),
             static_cast<int>(SimStatus::InvalidInput));
}

void test_absolute_gateway_no_sf5_downlink() {
    // Descente SF5 vers le dispositif : sensibilité du terminal NV, refus explicite.
    const EndDeviceSpec d[] = {dev(10.0, 5, 0, 60 * kS, 2)};
    lsim::plan::DeviceRadio rv[1] = {radio()};
    LoopRegion regions[1] = {region()};
    DeviceStats st[1];
    SimulationStats tot;
    LoopResult res;
    LoopOptions opt;
    opt.protocol.confirmed_uplinks = true;  // chaque uplink appelle une descente
    GatewaySpec gw;
    gw.absolute.enabled = true;
    gw.absolute.present = 1U;
    gw.absolute.dbm[0][0] = -150.0;
    CHECK_EQ(static_cast<int>(simulate_closed_loop(d, 1, rv, regions, gw, PropagationSpec{}, nullptr,
                                                   opt, st, tot, res)),
             static_cast<int>(SimStatus::InvalidInput));
}

// ---- Modèle canaux (étape 2) : LinkADR validé de bout en bout, état terminal observé ----
namespace {

constexpr std::uint8_t kAccepted = 0x07;

lsim::sim::LoopChannelConfig cfg_default() {
    LoopChannelConfig c;
    c.device = lsim::sim::loop_eu868_default_channels();
    c.server_view = lsim::sim::loop_eu868_plan().defaults;
    return c;
}

// Un dispositif SF12 à 10 m, 120 messages, ADR actif ; `cfg` nullptr = configuration par défaut.
// Même scénario que run_channels, distance du dispositif réglable (pertes de liaison).
SimStatus run_channels_at(const LoopChannelConfig* cfg, LoopChannelIo& io, LoopResult& res,
                          SimulationStats& tot, DeviceStats* st, std::uint32_t messages, double x_m,
                          double rx_offset_db = 0.0) {
    const EndDeviceSpec d[] = {dev(x_m, 12, 0, 60 * kS, messages)};
    lsim::plan::DeviceRadio rv[1] = {radio()};
    LoopRegion regions[1] = {region()};
    LoopOptions opt;
    opt.adr = true;
    opt.protocol.device_rx_offset_db = rx_offset_db;
    io.config = cfg;
    io.config_count = 1;
    return simulate_closed_loop_channels(d, 1, rv, regions, GatewaySpec{}, PropagationSpec{}, nullptr,
                                         opt, st, tot, res, io);
}

SimStatus run_channels(const LoopChannelConfig* cfg, std::size_t cfg_count, LoopChannelIo& io,
                       LoopResult& res, SimulationStats& tot, DeviceStats* st, std::uint32_t messages = 120) {
    const EndDeviceSpec d[] = {dev(10.0, 12, 0, 60 * kS, messages)};
    lsim::plan::DeviceRadio rv[1] = {radio()};
    LoopRegion regions[1] = {region()};
    LoopOptions opt;
    opt.adr = true;
    io.config = cfg;
    io.config_count = cfg_count;
    return simulate_closed_loop_channels(d, 1, rv, regions, GatewaySpec{}, PropagationSpec{}, nullptr,
                                         opt, st, tot, res, io);
}

// Vue 011 : le serveur croit le canal 5 défini, le terminal ne le connaît pas.
void test_channel_accepted_changes_terminal_state() {
    LoopChannelConfig cfg = cfg_default();
    LoopChannelIo io;
    LoopResult res;
    SimulationStats tot;
    DeviceStats st[1];
    CHECK_EQ(static_cast<int>(run_channels(&cfg, 1, io, res, tot, st)), 0);
    if (io.terminals.size() != 1 || res.uplinks.empty()) return;
    // Le terminal a appliqué le débit SF7 (DR5) : l'état final diffère de l'état initial (DR0).
    CHECK_EQ(static_cast<int>(io.terminals[0].dr), 5);
    CHECK_TRUE(io.terminals[0].channels == cfg.device);
    bool any_accepted = false;
    for (std::uint8_t s : io.uplink_status) any_accepted = any_accepted || s == kAccepted;
    CHECK_TRUE(any_accepted);
    CHECK_EQ(static_cast<int>(res.uplinks.back().spreading_factor), 7);
}

// Vue 011 : le serveur croit le canal 5 défini, le terminal ne le connaît pas (ChannelMaskACK = 0,
// débit et puissance acceptables). Étape 4 : le masque de la vue est exclu ; la requête suivante reprend
// le dernier masque acquitté (canaux 0..2) et le débit est alors appliqué. Aucune commande n'est
// déclenchée à l'expiration de l'exclusion (ici l'ADR n'a plus rien à changer).
// Changement de comportement (étape 4) : le refus d'un canal (CM=0, DR et PW acceptés) n'exclut plus
// le masque entier ; le canal non acquitté est exclu, et le dernier masque acquitté est repris.
void test_channel_refused_mask_excluded_then_acknowledged_mask_used() {
    LoopChannelConfig cfg = cfg_default();
    cfg.server_view.set(5);
    LoopChannelIo io;
    LoopResult res;
    SimulationStats tot;
    DeviceStats st[1];
    CHECK_EQ(static_cast<int>(run_channels(&cfg, 1, io, res, tot, st, 240)), 0);
    if (io.terminals.size() != 1 || io.downlink_requests.size() != res.downlinks.size()) return;
    // Première requête : vue serveur complète (0x27), refusée pour le canal 5 indéfini.
    std::size_t first = res.downlinks.size();
    for (std::size_t i = 0; i < res.downlinks.size(); ++i) {
        if ((res.downlinks[i].commands & kLoopCmdLinkAdr) != 0) { first = i; break; }
    }
    CHECK_TRUE(first < res.downlinks.size());
    if (first >= res.downlinks.size()) return;
    CHECK_EQ(static_cast<int>(io.downlink_requests[first].ch_mask), 0x27);
    CHECK_TRUE(io.downlink_diagnoses[first].channel_reason == LoopChannelReason::UndefinedChannel);
    CHECK_TRUE(io.downlink_diagnoses[first].refused_channels.test(5));
    // Requêtes suivantes : dernier masque acquitté (0x07), jamais le masque exclu.
    for (std::size_t i = first + 1; i < res.downlinks.size(); ++i) {
        if ((res.downlinks[i].commands & kLoopCmdLinkAdr) == 0) continue;
        CHECK_EQ(static_cast<int>(io.downlink_requests[i].ch_mask), 0x07);
    }
    // Uplink portant l'acceptation (statut 0b111) : après lui, aucune commande LinkADR, et ce jusqu'à
    // la fin de l'horizon (240 uplinks, expiration de l'exclusion à first+100 incluse).
    std::size_t accepted_at = res.uplinks.size();
    for (std::size_t u = 0; u < io.uplink_status.size(); ++u) {
        if (io.uplink_status[u] == kAccepted) { accepted_at = u; break; }
    }
    CHECK_TRUE(accepted_at < res.uplinks.size());
    std::size_t sent_after = 0;
    for (const LoopDownlink& dl : res.downlinks) {
        if ((dl.commands & kLoopCmdLinkAdr) != 0 && static_cast<std::size_t>(dl.uplink) > accepted_at) ++sent_after;
    }
    // Acceptation : débit SF7 (DR5) appliqué, canaux du terminal inchangés.
    CHECK_EQ(static_cast<int>(io.terminals[0].dr), 5);
    CHECK_TRUE(io.terminals[0].channels == cfg.device);
    bool refused = false;
    bool accepted = false;
    for (std::uint8_t s2 : io.uplink_status) {
        if (s2 == 0xFF) continue;
        refused = refused || s2 == 0x06;
        accepted = accepted || s2 == kAccepted;
        CHECK_TRUE(s2 == 0x06 || s2 == kAccepted);
    }
    CHECK_TRUE(refused);
    CHECK_TRUE(accepted);
    // Expiration (100 uplinks après le refus) : aucune commande n'est déclenchée automatiquement.
    CHECK_EQ(static_cast<int>(sent_after), 0);
}

// Refus partiel : le serveur demande les canaux 0..4 ; le terminal ne définit ni le canal 3 ni le
// canal 4 (dr_mask nul). Les deux sont donc indéfinis : l'attribution est exacte. Les requêtes
// suivantes reprennent les canaux acquittés (0..2). La sur-approximation (canal valide suspect) est
// testée à part, dans test_valid_suspect_channel_excluded_by_over_approximation.
void test_partial_channel_refusal_excludes_only_unacknowledged_requested_channels() {
    LoopChannelConfig cfg = cfg_default();
    cfg.server_view.set(3);
    cfg.server_view.set(4);
    cfg.device.dr_mask[3] = 0;
    cfg.device.enabled.reset(3);
    LoopChannelIo io;
    io.trace_v3 = true;  // exclusions observées directement
    LoopResult res;
    SimulationStats tot;
    DeviceStats st[1];
    CHECK_EQ(static_cast<int>(run_channels(&cfg, 1, io, res, tot, st, 240)), 0);
    if (io.terminals.size() != 1 || io.downlink_requests.size() != res.downlinks.size()) return;
    std::size_t first = res.downlinks.size();
    for (std::size_t i = 0; i < res.downlinks.size(); ++i) {
        if ((res.downlinks[i].commands & kLoopCmdLinkAdr) != 0) { first = i; break; }
    }
    CHECK_TRUE(first < res.downlinks.size());
    if (first >= res.downlinks.size()) return;
    CHECK_TRUE(!cfg.device.defined(3) && !cfg.device.defined(4));  // sanity : canaux indéfinis
    CHECK_EQ(static_cast<int>(io.downlink_requests[first].ch_mask), 0x1F);  // canaux 0..4 demandés
    CHECK_TRUE(io.downlink_diagnoses[first].refused_channels.test(3));
    // Le masque demandé garde les confirmés 0..2 : aucun d'eux ne doit être exclu, même au refus.
    // (Sans cette assertion, le repli sur le masque confirmé masquerait l'erreur.)
    // Premier refus de canal : uplink du premier LinkAdrAns avec ChannelMaskACK = 0.
    std::uint32_t refusal_uplink = 0;
    bool refusal_seen = false;
    for (const LoopTraceEvent& e : io.trace) {
        if (e.kind == LoopTraceKind::LinkAdrAns && (e.status & 1U) == 0 && !refusal_seen) {
            refusal_uplink = e.uplink;
            refusal_seen = true;
        }
    }
    CHECK_TRUE(refusal_seen);
    int ex34_at_refusal = 0, ex012 = 0;
    for (const LoopTraceEvent& e : io.trace) {
        if (e.kind != LoopTraceKind::Exclusion || e.target != LoopExclusionTarget::Channel) continue;
        if ((e.value == 3 || e.value == 4) && e.uplink == refusal_uplink) ++ex34_at_refusal;
        if (e.value <= 2) ++ex012;  // jamais, sur toute la trace
    }
    CHECK_EQ(ex34_at_refusal, 2);  // 3 et 4 (suspects), une fois chacun
    CHECK_EQ(ex012, 0);
    // Requêtes suivantes : seuls les canaux acquittés (0..2) ; 3 et 4 exclus (indéfinis : exact).
    bool accepted = false;
    for (std::size_t i = first + 1; i < res.downlinks.size(); ++i) {
        if ((res.downlinks[i].commands & kLoopCmdLinkAdr) == 0) continue;
        CHECK_EQ(static_cast<int>(io.downlink_requests[i].ch_mask), 0x07);
    }
    for (std::uint8_t s2 : io.uplink_status) accepted = accepted || s2 == kAccepted;
    CHECK_TRUE(accepted);
    CHECK_EQ(static_cast<int>(io.terminals[0].dr), 5);          // débit appliqué malgré le refus de canal
    CHECK_TRUE(io.terminals[0].channels == cfg.device);
}

// Canal valide nouvellement demandé (défini côté terminal) : accepté dès la première requête.
void test_valid_new_channel_accepted_first_time() {
    LoopChannelConfig cfg = cfg_default();
    cfg.server_view.set(5);
    cfg.device.dr_mask[5] = 0x3F;
    cfg.device.enabled.set(5);
    LoopChannelIo io;
    LoopResult res;
    SimulationStats tot;
    DeviceStats st[1];
    CHECK_EQ(static_cast<int>(run_channels(&cfg, 1, io, res, tot, st)), 0);
    if (io.terminals.size() != 1) return;
    bool any = false;
    for (std::size_t i = 0; i < res.downlinks.size(); ++i) {
        if ((res.downlinks[i].commands & kLoopCmdLinkAdr) == 0) continue;
        if (!any) CHECK_EQ(static_cast<int>(io.downlink_requests[i].ch_mask), 0x27);
        any = true;
    }
    CHECK_TRUE(any);
    CHECK_TRUE(io.terminals[0].channels.enabled.test(5));
    CHECK_EQ(static_cast<int>(io.terminals[0].dr), 5);
    for (std::uint8_t s2 : io.uplink_status) {
        if (s2 != 0xFF) CHECK_EQ(static_cast<int>(s2), static_cast<int>(kAccepted));
    }
}

// ---- Trace interne v3 (étape 5) -------------------------------------------------------------

// Désactivée par défaut : aucune sortie.
void test_trace_v3_off_by_default() {
    LoopChannelConfig cfg = cfg_default();
    for (std::size_t c = 0; c < 3; ++c) cfg.device.dr_mask[c] = 0x0F;
    LoopChannelIo io;
    LoopResult res;
    SimulationStats tot;
    DeviceStats st[1];
    CHECK_EQ(static_cast<int>(run_channels(&cfg, 1, io, res, tot, st)), 0);
    CHECK_TRUE(!io.trace_v3);
    CHECK_TRUE(io.trace.empty());
}

// Activer la trace ne change ni les radios, ni les réponses, ni les requêtes, ni les compteurs.
void test_trace_v3_does_not_change_radio_or_answers() {
    LoopChannelConfig cfg = cfg_default();
    cfg.server_view.set(3);
    cfg.server_view.set(4);
    cfg.device.dr_mask[3] = 0;
    cfg.device.enabled.reset(3);
    LoopChannelIo off, on;
    LoopResult ro, rn;
    SimulationStats to, tn;
    DeviceStats so[1], sn[1];
    on.trace_v3 = true;
    CHECK_EQ(static_cast<int>(run_channels(&cfg, 1, off, ro, to, so, 240)), 0);
    CHECK_EQ(static_cast<int>(run_channels(&cfg, 1, on, rn, tn, sn, 240)), 0);
    CHECK_TRUE(!on.trace.empty());
    // Résultats radio par uplink : issue, instants, débit, puissance, réponses portées.
    CHECK_EQ(static_cast<int>(ro.uplinks.size()), static_cast<int>(rn.uplinks.size()));
    for (std::size_t i = 0; i < ro.uplinks.size() && i < rn.uplinks.size(); ++i) {
        const LoopUplink& a = ro.uplinks[i];
        const LoopUplink& b = rn.uplinks[i];
        CHECK_TRUE(a.outcome == b.outcome);
        CHECK_TRUE(a.start_ns == b.start_ns && a.end_ns == b.end_ns);
        CHECK_EQ(static_cast<int>(a.spreading_factor), static_cast<int>(b.spreading_factor));
        CHECK_EQ(static_cast<int>(a.power_index), static_cast<int>(b.power_index));
        CHECK_EQ(static_cast<int>(a.answer_mask), static_cast<int>(b.answer_mask));
        CHECK_EQ(static_cast<int>(a.answer_ok), static_cast<int>(b.answer_ok));
    }
    // Descentes : même issue, mêmes créneaux, mêmes commandes.
    CHECK_EQ(static_cast<int>(ro.downlinks.size()), static_cast<int>(rn.downlinks.size()));
    for (std::size_t i = 0; i < ro.downlinks.size() && i < rn.downlinks.size(); ++i) {
        const LoopDownlink& a = ro.downlinks[i];
        const LoopDownlink& b = rn.downlinks[i];
        CHECK_TRUE(a.delivered == b.delivered && a.device_missed == b.device_missed);
        CHECK_TRUE(a.start_ns == b.start_ns && a.air_ns == b.air_ns);
        CHECK_EQ(static_cast<int>(a.commands), static_cast<int>(b.commands));
    }
    // Totaux radio et compteurs de passerelle.
    CHECK_EQ(static_cast<int>(to.sent), static_cast<int>(tn.sent));
    CHECK_EQ(static_cast<int>(to.received), static_cast<int>(tn.received));
    CHECK_EQ(static_cast<int>(to.lost_sensitivity), static_cast<int>(tn.lost_sensitivity));
    CHECK_EQ(static_cast<int>(to.lost_collision), static_cast<int>(tn.lost_collision));
    CHECK_EQ(static_cast<int>(to.lost_gateway_busy), static_cast<int>(tn.lost_gateway_busy));
    CHECK_TRUE(to.airtime_ns == tn.airtime_ns);
    // Réponses et état terminal.
    CHECK_TRUE(off.uplink_status == on.uplink_status);
    CHECK_EQ(static_cast<int>(off.downlink_requests.size()), static_cast<int>(on.downlink_requests.size()));
    for (std::size_t i = 0; i < off.downlink_requests.size() && i < on.downlink_requests.size(); ++i) {
        CHECK_EQ(static_cast<int>(off.downlink_requests[i].ch_mask), static_cast<int>(on.downlink_requests[i].ch_mask));
        CHECK_EQ(static_cast<int>(off.downlink_requests[i].dr), static_cast<int>(on.downlink_requests[i].dr));
        CHECK_EQ(static_cast<int>(off.downlink_requests[i].power_index), static_cast<int>(on.downlink_requests[i].power_index));
    }
    CHECK_EQ(static_cast<int>(off.terminals.size()), static_cast<int>(on.terminals.size()));
    if (off.terminals.size() == on.terminals.size() && !off.terminals.empty()) {
        CHECK_EQ(static_cast<int>(off.terminals[0].dr), static_cast<int>(on.terminals[0].dr));
        CHECK_TRUE(off.terminals[0].channels == on.terminals[0].channels);
    }
}

// Refus partiel : bits 0..2 visibles, motifs exacts, exclusions par canal, dans l'ordre causal.
void test_trace_v3_partial_refusal_shows_three_bits_and_exclusions() {
    LoopChannelConfig cfg = cfg_default();
    cfg.server_view.set(3);
    cfg.server_view.set(4);
    cfg.device.dr_mask[3] = 0;
    cfg.device.enabled.reset(3);
    LoopChannelIo io;
    io.trace_v3 = true;
    LoopResult res;
    SimulationStats tot;
    DeviceStats st[1];
    CHECK_EQ(static_cast<int>(run_channels(&cfg, 1, io, res, tot, st, 240)), 0);
    // Réponse partielle : CM=0 (bit 0), DR=1 et PW=1 : statut 0b110.
    const LoopTraceEvent* ans = nullptr;
    for (const LoopTraceEvent& e : io.trace) {
        if (e.kind == LoopTraceKind::LinkAdrAns && e.status == 0x06) { ans = &e; break; }
    }
    CHECK_TRUE(ans != nullptr);
    if (ans == nullptr) return;
    CHECK_TRUE(!ans->flag);
    CHECK_TRUE(ans->origin == LoopTraceOrigin::Normative);
    // Exclusions créées pour les canaux 3 et 4, et pas pour le débit ni la puissance.
    int ex3 = 0, ex4 = 0, ex_dr = 0, ex_pw = 0;
    for (const LoopTraceEvent& e : io.trace) {
        if (e.kind != LoopTraceKind::Exclusion || e.uplink != ans->uplink) continue;
        CHECK_TRUE(e.action == LoopTraceAction::Created);
        CHECK_TRUE(e.origin == LoopTraceOrigin::SimulatorPolicy);
        if (e.target == LoopExclusionTarget::Channel && e.value == 3) ++ex3;
        if (e.target == LoopExclusionTarget::Channel && e.value == 4) ++ex4;
        if (e.target == LoopExclusionTarget::DataRate) ++ex_dr;
        if (e.target == LoopExclusionTarget::Power) ++ex_pw;
    }
    CHECK_EQ(ex3, 1);
    CHECK_EQ(ex4, 1);
    CHECK_EQ(ex_dr, 0);
    CHECK_EQ(ex_pw, 0);
    // Motif du canal présent dans la trace d'application.
    bool reason_seen = false;
    for (const LoopTraceEvent& e : io.trace) {
        if (e.kind == LoopTraceKind::Apply && e.reason_channel != 0) reason_seen = true;
    }
    CHECK_TRUE(reason_seen);
}

// Ordre causal à l'intérieur d'un uplink : Uplink < LinkAdrAns < Exclusion < AdrDecision ; et trace
// triée par temps.
void test_trace_v3_causal_order_and_time_sorted() {
    LoopChannelConfig cfg = cfg_default();
    for (std::size_t c = 0; c < 3; ++c) cfg.device.dr_mask[c] = 0x0F;
    LoopChannelIo io;
    io.trace_v3 = true;
    LoopResult res;
    SimulationStats tot;
    DeviceStats st[1];
    CHECK_EQ(static_cast<int>(run_channels(&cfg, 1, io, res, tot, st)), 0);
    for (std::size_t i = 1; i < io.trace.size(); ++i) CHECK_TRUE(io.trace[i - 1].t_ns <= io.trace[i].t_ns);
    std::size_t iu = io.trace.size(), ia = io.trace.size(), ie = io.trace.size(), ad = io.trace.size();
    for (std::size_t i = 0; i < io.trace.size(); ++i) {
        const LoopTraceEvent& e = io.trace[i];
        if (e.kind == LoopTraceKind::LinkAdrAns && ia == io.trace.size()) {
            ia = i;
            const std::uint32_t u = e.uplink;
            for (std::size_t j = 0; j < io.trace.size(); ++j) {
                if (io.trace[j].kind == LoopTraceKind::Uplink && io.trace[j].uplink == u) iu = j;
                if (io.trace[j].kind == LoopTraceKind::Exclusion && io.trace[j].uplink == u && ie == io.trace.size()) ie = j;
                if (io.trace[j].kind == LoopTraceKind::AdrDecision && io.trace[j].uplink == u && ad == io.trace.size()) ad = j;
            }
        }
    }
    CHECK_TRUE(ia < io.trace.size());
    CHECK_TRUE(iu < ia);
    CHECK_TRUE(ia < ie);
    CHECK_TRUE(ie < ad);
}

// Cycle de vie 001 : créée au refus, expirée exactement 100 uplinks plus tard. Un refus renégocié
// après expiration rouvre une exclusion (création) à partir de R' ; le renouvellement strict (refus
// pendant une exclusion encore active) n'est pas atteignable par l'ADR et est couvert en unitaire.
// Aucune décision ADR portant DR5 strictement entre la création et l'expiration.
void test_trace_v3_exclusion_expired_then_recreated() {
    // Refus DR5 à R, expiration à R+100, puis nouveau refus à R+101 : une création, pas un
    // renouvellement (l'exclusion précédente était déjà expirée). Le renouvellement strict est testé
    // dans test_trace_v3_mask_exclusion_renewed_while_active.
    LoopChannelConfig cfg = cfg_default();
    for (std::size_t c = 0; c < 3; ++c) cfg.device.dr_mask[c] = 0x0F;
    LoopChannelIo io;
    io.trace_v3 = true;
    LoopResult res;
    SimulationStats tot;
    DeviceStats st[1];
    CHECK_EQ(static_cast<int>(run_channels(&cfg, 1, io, res, tot, st, 340)), 0);
    std::vector<LoopTraceEvent> dr5;
    for (const LoopTraceEvent& e : io.trace) {
        if (e.kind == LoopTraceKind::Exclusion && e.target == LoopExclusionTarget::DataRate && e.value == 5) {
            dr5.push_back(e);
        }
    }
    CHECK_TRUE(dr5.size() >= 3);
    if (dr5.size() < 3) return;
    CHECK_TRUE(dr5[0].action == LoopTraceAction::Created);
    CHECK_TRUE(dr5[1].action == LoopTraceAction::Expired);
    CHECK_TRUE(dr5[2].action == LoopTraceAction::Created);               // recréée, pas renouvelée
    CHECK_EQ(static_cast<int>(dr5[1].uplink - dr5[0].uplink), 100);      // expiration au 100e uplink
    CHECK_EQ(static_cast<int>(dr5[2].uplink - dr5[1].uplink), 1);        // réponse refusée à l'uplink suivant
    for (const LoopTraceEvent& e : io.trace) {
        if (e.kind == LoopTraceKind::AdrDecision && e.flag && e.dr == 5 && e.uplink > dr5[0].uplink &&
            e.uplink < dr5[1].uplink) {
            CHECK_TRUE(false);  // aucune demande DR5 pendant l'exclusion
        }
    }
}

// Déterminisme : deux exécutions identiques donnent une trace identique, événement par événement.
void test_trace_v3_deterministic() {
    LoopChannelConfig cfg = cfg_default();
    cfg.server_view.set(3);
    cfg.server_view.set(4);
    cfg.device.dr_mask[3] = 0;
    cfg.device.enabled.reset(3);
    LoopChannelIo a, b;
    a.trace_v3 = true;
    b.trace_v3 = true;
    LoopResult ra, rb;
    SimulationStats ta, tb;
    DeviceStats sa[1], sb[1];
    CHECK_EQ(static_cast<int>(run_channels(&cfg, 1, a, ra, ta, sa, 240)), 0);
    CHECK_EQ(static_cast<int>(run_channels(&cfg, 1, b, rb, tb, sb, 240)), 0);
    CHECK_EQ(static_cast<int>(a.trace.size()), static_cast<int>(b.trace.size()));
    CHECK_TRUE(a.trace == b.trace);                       // événement par événement
    CHECK_TRUE(a.uplink_status == b.uplink_status);
    CHECK_TRUE(ra.downlinks.size() == rb.downlinks.size());
    // Les événements sont classés par temps.
    for (std::size_t i = 1; i < a.trace.size(); ++i) CHECK_TRUE(a.trace[i - 1].t_ns <= a.trace[i].t_ns);
}

// Masque qui retire des canaux confirmés (0..2) au profit de canaux 3 (indéfini) et 4 (valide) : le
// refus n'attribue que les suspects (3 et 4). Les canaux confirmés 0..2 ne sont jamais exclus, et le
// terminal reste atomique (ses canaux activés ne changent pas).
void test_mask_removing_confirmed_channels_attributes_only_suspects() {
    LoopChannelConfig cfg = cfg_default();
    cfg.device.dr_mask[3] = 0;     // 3 indéfini
    cfg.device.dr_mask[4] = 0x3F;  // 4 défini, non activé
    LoopLinkAdrRequest rq;
    rq.ch_mask_cntl = 0;
    rq.ch_mask = 0x0018;           // canaux 3 et 4 seulement : retire 0..2 (confirmés)
    rq.dr = 5;
    rq.power_index = 7;
    cfg.forced_sequence = {rq};
    LoopChannelIo io;
    io.trace_v3 = true;
    LoopResult res;
    SimulationStats tot;
    DeviceStats st[1];
    CHECK_EQ(static_cast<int>(run_channels(&cfg, 1, io, res, tot, st, 120)), 0);
    const LoopTraceEvent* ans = nullptr;
    for (const LoopTraceEvent& e : io.trace) {
        if (e.kind == LoopTraceKind::LinkAdrAns && (e.status & 1U) == 0) { ans = &e; break; }
    }
    CHECK_TRUE(ans != nullptr);
    if (ans == nullptr) return;
    CHECK_EQ(static_cast<int>(ans->status & 2U), 2);  // débit accepté : attribution au masque seul
    int ex34 = 0, ex012 = 0;
    for (const LoopTraceEvent& e : io.trace) {
        if (e.kind != LoopTraceKind::Exclusion || e.target != LoopExclusionTarget::Channel) continue;
        if (e.value == 3 || e.value == 4) ++ex34;
        if (e.value <= 2) ++ex012;
    }
    CHECK_EQ(ex34, 2);    // suspects exclus
    CHECK_EQ(ex012, 0);   // confirmés jamais exclus, même retirés par le masque demandé
    CHECK_TRUE(io.terminals[0].channels.enabled.test(0));
    CHECK_TRUE(io.terminals[0].channels.enabled.test(1));
    CHECK_TRUE(io.terminals[0].channels.enabled.test(2));
    CHECK_TRUE(!io.terminals[0].channels.enabled.test(3));
    CHECK_TRUE(!io.terminals[0].channels.enabled.test(4));
}

// D5 : CM=0 et DR=0 simultanés. Le débit est exclu, les canaux ne le sont pas. Le canal indéfini
// n'est suspect que lorsque le débit est accepté (CM=0, DR=1) : il est alors seul exclu.
void test_d5_cm0_dr0_then_channel_refusal() {
    LoopChannelConfig cfg = cfg_default();
    for (std::size_t c = 0; c < 3; ++c) cfg.device.dr_mask[c] = 0x0F;  // DR0..DR3 seulement
    cfg.server_view.set(5);
    cfg.device.dr_mask[5] = 0;                                           // canal 5 indéfini
    LoopChannelIo io;
    io.trace_v3 = true;
    LoopResult res;
    SimulationStats tot;
    DeviceStats st[1];
    CHECK_EQ(static_cast<int>(run_channels(&cfg, 1, io, res, tot, st, 400)), 0);
    // Premier refus à débit refusé et masque refusé.
    const LoopTraceEvent* both = nullptr;
    const LoopTraceEvent* dr_ok = nullptr;
    for (const LoopTraceEvent& e : io.trace) {
        if (e.kind != LoopTraceKind::LinkAdrAns) continue;
        if (both == nullptr && (e.status & 3U) == 0) both = &e;
        if (both != nullptr && dr_ok == nullptr && e.uplink > both->uplink && (e.status & 1U) == 0 &&
            (e.status & 2U) != 0) {
            dr_ok = &e;
        }
    }
    CHECK_TRUE(both != nullptr);
    CHECK_TRUE(dr_ok != nullptr);
    if (both == nullptr || dr_ok == nullptr) return;
    int dr_excl = 0, ch_excl_at_both = 0;
    for (const LoopTraceEvent& e : io.trace) {
        if (e.kind != LoopTraceKind::Exclusion || e.uplink != both->uplink) continue;
        if (e.target == LoopExclusionTarget::DataRate && e.value == both->dr && e.action == LoopTraceAction::Created) {
            ++dr_excl;
        }
        if (e.target == LoopExclusionTarget::Channel) ++ch_excl_at_both;
    }
    CHECK_EQ(dr_excl, 1);          // le débit refusé est exclu
    CHECK_EQ(ch_excl_at_both, 0);  // aucun canal exclu sur un refus DR=0 (D5)
    // Le canal indéfini est exclu au premier refus à débit accepté, et lui seul.
    int ch5 = 0, ch_other = 0;
    for (const LoopTraceEvent& e : io.trace) {
        if (e.kind != LoopTraceKind::Exclusion || e.uplink != dr_ok->uplink) continue;
        if (e.target != LoopExclusionTarget::Channel) continue;
        if (e.value == 5) ++ch5;
        else ++ch_other;
    }
    CHECK_EQ(ch5, 1);
    CHECK_EQ(ch_other, 0);
}

// Sur-approximation réelle : le canal 4 est DÉFINI côté terminal (valide) et figure parmi les suspects
// avec le canal 3 (indéfini). Le serveur exclut les deux : c'est la limite de l'attribution sans motif
// par canal.
void test_valid_suspect_channel_excluded_by_over_approximation() {
    LoopChannelConfig cfg = cfg_default();
    cfg.server_view.set(3);
    cfg.server_view.set(4);
    cfg.device.dr_mask[3] = 0;     // 3 indéfini
    cfg.device.dr_mask[4] = 0x3F;  // 4 défini, valide, non activé
    CHECK_TRUE(!cfg.device.defined(3));
    CHECK_TRUE(cfg.device.defined(4));
    LoopChannelIo io;
    io.trace_v3 = true;
    LoopResult res;
    SimulationStats tot;
    DeviceStats st[1];
    CHECK_EQ(static_cast<int>(run_channels(&cfg, 1, io, res, tot, st, 240)), 0);
    const LoopTraceEvent* ans = nullptr;
    for (const LoopTraceEvent& e : io.trace) {
        if (e.kind == LoopTraceKind::LinkAdrAns && e.status == 0x06) { ans = &e; break; }
    }
    CHECK_TRUE(ans != nullptr);
    if (ans == nullptr) return;
    int ex3 = 0, ex4 = 0;
    for (const LoopTraceEvent& e : io.trace) {
        if (e.kind == LoopTraceKind::Exclusion && e.uplink == ans->uplink && e.target == LoopExclusionTarget::Channel) {
            if (e.value == 3) ++ex3;
            if (e.value == 4) ++ex4;
        }
    }
    CHECK_EQ(ex3, 1);
    CHECK_EQ(ex4, 1);  // exclusion du canal valide : sur-approximation
    // Les requêtes à partir de l'uplink de refus (incluse) n'incluent pas le canal 4 pendant la
    // fenêtre d'exclusion.
    int after = 0;
    for (const LoopTraceEvent& e : io.trace) {
        if (e.kind != LoopTraceKind::LinkAdrReq || e.uplink < ans->uplink) continue;
        ++after;
        CHECK_EQ(static_cast<int>(e.channel_mask & 0x10U), 0);
    }
    CHECK_TRUE(after > 0);
    CHECK_TRUE(!io.terminals[0].channels.enabled.test(4));  // jamais activé : pas de masque confirmé
}

// Refus à suspects vides (masque demandé entièrement confirmé, ou vide) : exclusion du masque demandé
// complet, sans répétition pendant 100 uplinks, expiration sans commande, repli sur le dernier masque
// confirmé. La requête est forcée une seule fois (test de robustesse), puis la politique reprend.
void test_empty_suspect_refusal_excludes_mask_without_repetition() {
    LoopChannelConfig cfg = cfg_default();
    LoopLinkAdrRequest bad;
    bad.ch_mask_cntl = 0;
    bad.ch_mask = 0x0000;  // tous les canaux désactivés : CM=0, aucun suspect
    bad.dr = 0;
    bad.power_index = 0;
    cfg.forced_sequence = {bad};
    LoopChannelIo io;
    io.trace_v3 = true;
    LoopResult res;
    SimulationStats tot;
    DeviceStats st[1];
    CHECK_EQ(static_cast<int>(run_channels(&cfg, 1, io, res, tot, st, 240)), 0);
    const LoopTraceEvent* ans = nullptr;
    for (const LoopTraceEvent& e : io.trace) {
        if (e.kind == LoopTraceKind::LinkAdrAns && e.status == 0x06) { ans = &e; break; }
    }
    CHECK_TRUE(ans != nullptr);
    if (ans == nullptr) return;
    const std::uint32_t r = ans->uplink;
    // Exclusion du masque demandé complet, créée au refus, et seulement elle.
    int mask_created = 0, channel_events = 0;
    for (const LoopTraceEvent& e : io.trace) {
        if (e.kind != LoopTraceKind::Exclusion || e.uplink != r) continue;
        if (e.target == LoopExclusionTarget::Mask && e.action == LoopTraceAction::Created && e.value == 0) ++mask_created;
        if (e.target == LoopExclusionTarget::Channel) ++channel_events;
    }
    CHECK_EQ(mask_created, 1);
    CHECK_EQ(channel_events, 0);
    // Pendant les 100 uplinks admissibles qui suivent, aucune LinkADRReq ne porte le masque exclu.
    // La seule requête à masque nul est la requête forcée initiale.
    int zero_requests = 0;
    for (const LoopTraceEvent& e : io.trace) {
        if (e.kind != LoopTraceKind::LinkAdrReq) continue;
        if (e.channel_mask == 0) ++zero_requests;
        if (e.uplink >= r && e.uplink < r + 100) CHECK_TRUE(e.channel_mask != 0);
    }
    CHECK_EQ(zero_requests, 1);
    // Repli : la requête suivante porte le dernier masque confirmé (défauts 0x07).
    for (const LoopTraceEvent& e : io.trace) {
        if (e.kind == LoopTraceKind::LinkAdrReq && e.uplink > r) {
            CHECK_EQ(static_cast<int>(e.channel_mask), 0x07);
            break;
        }
    }
    // Expiration exactement au 100e uplink, sans nouvelle requête de masque nul.
    int expired = 0;
    for (const LoopTraceEvent& e : io.trace) {
        if (e.kind == LoopTraceKind::Exclusion && e.target == LoopExclusionTarget::Mask &&
            e.action == LoopTraceAction::Expired) {
            ++expired;
            CHECK_EQ(static_cast<int>(e.uplink - r), 100);
            CHECK_EQ(static_cast<int>(e.value), 0);
        }
    }
    CHECK_EQ(expired, 1);
}

// Renouvellement strict : le même masque refusé de nouveau pendant son exclusion remet le compteur à
// 100 (Renewed), au lieu de créer une seconde exclusion.
void test_trace_v3_mask_exclusion_renewed_while_active() {
    LoopChannelConfig cfg = cfg_default();
    LoopLinkAdrRequest bad;
    bad.ch_mask_cntl = 0;
    bad.ch_mask = 0x0000;
    bad.dr = 0;
    bad.power_index = 0;
    cfg.forced_sequence = {bad, bad};  // la seconde LinkADRReq, envoyée après le refus, est refusée aussi
    LoopChannelIo io;
    io.trace_v3 = true;
    LoopResult res;
    SimulationStats tot;
    DeviceStats st[1];
    CHECK_EQ(static_cast<int>(run_channels(&cfg, 1, io, res, tot, st, 240)), 0);
    std::vector<LoopTraceEvent> mask;
    for (const LoopTraceEvent& e : io.trace) {
        if (e.kind == LoopTraceKind::Exclusion && e.target == LoopExclusionTarget::Mask) mask.push_back(e);
    }
    CHECK_TRUE(mask.size() >= 2);
    if (mask.size() < 2) return;
    CHECK_TRUE(mask[0].action == LoopTraceAction::Created);
    CHECK_TRUE(mask[1].action == LoopTraceAction::Renewed);
    CHECK_EQ(static_cast<int>(mask[1].uplink - mask[0].uplink), 1);
    for (std::size_t i = 2; i < mask.size(); ++i) {
        CHECK_TRUE(mask[i].action != LoopTraceAction::Created || mask[i].uplink - mask[i - 1].uplink >= 100);
    }
}

// Sémantique des événements : LinkAdrAns porte le contenu acquitté (pas la demande en attente),
// Apply référence la descente et son uplink déclencheur, Downlink donne l'issue radio.
void test_trace_v3_event_semantics_answer_content_and_downlink_link() {
    LoopChannelConfig cfg = cfg_default();
    LoopLinkAdrRequest ok;
    ok.ch_mask_cntl = 0;
    ok.ch_mask = 0x0007;
    ok.dr = 0;            // pend du serveur : DR5 ; le contenu forcé est DR0
    ok.power_index = 0;
    cfg.forced_sequence = {ok};
    LoopChannelIo io;
    io.trace_v3 = true;
    LoopResult res;
    SimulationStats tot;
    DeviceStats st[1];
    CHECK_EQ(static_cast<int>(run_channels(&cfg, 1, io, res, tot, st, 60)), 0);
    const LoopTraceEvent* req = nullptr;
    const LoopTraceEvent* ans = nullptr;
    for (const LoopTraceEvent& e : io.trace) {
        if (req == nullptr && e.kind == LoopTraceKind::LinkAdrReq) req = &e;
    }
    CHECK_TRUE(req != nullptr);
    if (req == nullptr) return;
    CHECK_EQ(static_cast<int>(req->dr), 0);
    CHECK_EQ(static_cast<int>(req->downlink), 0);
    CHECK_TRUE(req->origin == LoopTraceOrigin::SimulatorPolicy);
    for (const LoopTraceEvent& e : io.trace) {
        if (ans == nullptr && e.kind == LoopTraceKind::LinkAdrAns) ans = &e;
    }
    CHECK_TRUE(ans != nullptr);
    if (ans == nullptr) return;
    CHECK_EQ(static_cast<int>(ans->status), 0x07);
    CHECK_EQ(static_cast<int>(ans->dr), 0);            // contenu acquitté, pas DR5 en attente
    CHECK_EQ(static_cast<int>(ans->power_index), 0);
    CHECK_EQ(static_cast<int>(ans->channel_mask), 0x0007);
    CHECK_TRUE(ans->origin == LoopTraceOrigin::Normative);
    // Apply de la descente 0 : même descente, uplink déclencheur de la LinkADRReq.
    bool apply_seen = false;
    for (const LoopTraceEvent& e : io.trace) {
        if (e.kind != LoopTraceKind::Apply || e.downlink != 0) continue;
        apply_seen = true;
        CHECK_EQ(static_cast<int>(e.uplink), static_cast<int>(req->uplink));
        CHECK_TRUE(e.flag);
    }
    CHECK_TRUE(apply_seen);
    // Downlink : issue radio, origine Radio, causes de perte nulles quand reçue.
    bool dl_seen = false;
    for (const LoopTraceEvent& e : io.trace) {
        if (e.kind != LoopTraceKind::Downlink || e.downlink != 0) continue;
        dl_seen = true;
        CHECK_TRUE(e.origin == LoopTraceOrigin::Radio);
        CHECK_EQ(static_cast<int>(e.uplink), static_cast<int>(req->uplink));
        CHECK_TRUE(e.flag);
        CHECK_EQ(static_cast<int>(e.loss), 0);
    }
    CHECK_TRUE(dl_seen);
    // Uplinks : origine radio.
    for (const LoopTraceEvent& e : io.trace) {
        if (e.kind == LoopTraceKind::Uplink) CHECK_TRUE(e.origin == LoopTraceOrigin::Radio);
    }
}

// Requête forcée refusée sur le débit : l'exclusion vise le débit réellement refusé (DR6), non la
// demande en attente du serveur (DR5).
void test_forced_refused_dr_excluded_is_the_requested_value() {
    LoopChannelConfig cfg = cfg_default();
    LoopLinkAdrRequest bad;
    bad.ch_mask_cntl = 0;
    bad.ch_mask = 0x0007;
    bad.dr = 6;  // non supporté par le terminal
    bad.power_index = 0;
    cfg.forced_sequence = {bad};
    LoopChannelIo io;
    io.trace_v3 = true;
    LoopResult res;
    SimulationStats tot;
    DeviceStats st[1];
    CHECK_EQ(static_cast<int>(run_channels(&cfg, 1, io, res, tot, st, 60)), 0);
    int dr6 = 0, dr5 = 0;
    for (const LoopTraceEvent& e : io.trace) {
        if (e.kind != LoopTraceKind::Exclusion || e.target != LoopExclusionTarget::DataRate) continue;
        if (e.value == 6) ++dr6;
        if (e.value == 5) ++dr5;
    }
    CHECK_EQ(dr6, 1);
    CHECK_EQ(dr5, 0);
}

// Invariants des descentes : chaque LinkADRReq planifiée a une issue radio ; les Apply sont exactement
// les descentes reçues portant une LinkADRReq ; une descente perdue a une cause, une reçue n'en a pas.
void test_trace_v3_downlink_invariants() {
    // Deux régimes : liaison descendante normale, et marge de réception du terminal de 110 dB
    // (toutes les descentes perdues par sensibilité ; la LinkADRReq est réémise à chaque uplink).
    for (double offset_db : {0.0, 110.0}) {
        LoopChannelConfig cfg = cfg_default();
        for (std::size_t c = 0; c < 3; ++c) cfg.device.dr_mask[c] = 0x0F;
        LoopChannelIo io;
        io.trace_v3 = true;
        LoopResult res;
        SimulationStats tot;
        DeviceStats st[1];
        CHECK_EQ(static_cast<int>(run_channels_at(&cfg, io, res, tot, st, 240, 10.0, offset_db)), 0);
        std::size_t planned = 0, outcomes = 0, applies = 0, delivered_link = 0, lost_sens = 0;
        for (const LoopTraceEvent& e : io.trace) {
            if (e.kind == LoopTraceKind::LinkAdrReq) ++planned;
            if (e.kind == LoopTraceKind::Apply) ++applies;
            if (e.kind != LoopTraceKind::Downlink) continue;
            ++outcomes;
            if (e.flag) {
                CHECK_EQ(static_cast<int>(e.loss), 0);
                if ((e.value & 1U) != 0) ++delivered_link;
            } else {
                CHECK_TRUE(e.loss != 0);
                if (e.loss == static_cast<std::uint8_t>(LoopDownlinkLoss::BelowSensitivity)) ++lost_sens;
            }
        }
        CHECK_EQ(static_cast<int>(outcomes), static_cast<int>(res.downlinks.size()));
        CHECK_EQ(static_cast<int>(applies), static_cast<int>(delivered_link));
        CHECK_TRUE(planned > 0);
        CHECK_TRUE(planned <= outcomes);
        if (offset_db > 100.0) {
            CHECK_TRUE(lost_sens > 0);   // régime de perte : pertes par sensibilité observées
            CHECK_EQ(static_cast<int>(applies), 0);
        }
    }
}

// Limite documentée par le test d'unité : le repli vers le dernier masque confirmé peut renvoyer
// le masque exclu lorsque celui-ci est confirmé. Ce cas exige un terminal non conforme aux canaux
// par défaut (RP002 Table 8) et n'est pas produit par la configuration par défaut.

// Vue 001 : le terminal ne supporte que DR0..DR3. Le serveur demande DR5 : refus de débit
// (attribué au débit, D5), l'état terminal reste inchangé. Après exclusion, la réévaluation
// propose un autre débit (DR0, accepté) : le débit refusé n'est jamais renvoyé.
void test_data_rate_refused_then_reevaluated_without_repetition() {
    LoopChannelConfig cfg = cfg_default();
    for (std::size_t c = 0; c < 3; ++c) cfg.device.dr_mask[c] = 0x0F;  // DR0..DR3 seulement
    LoopChannelIo io;
    LoopResult res;
    SimulationStats tot;
    DeviceStats st[1];
    CHECK_EQ(static_cast<int>(run_channels(&cfg, 1, io, res, tot, st)), 0);
    if (io.terminals.size() != 1 || io.downlink_requests.size() != res.downlinks.size()) return;
    // État final = requête acceptée (DR0, état initial) ; DR5 refusé n'a rien modifié.
    CHECK_EQ(static_cast<int>(io.terminals[0].dr), 0);
    CHECK_TRUE(io.terminals[0].channels == cfg.device);
    // Requêtes LinkADR livrées dans l'ordre : débits strictement décroissants (aucune répétition).
    std::vector<int> drs;
    for (std::size_t i = 0; i < res.downlinks.size(); ++i) {
        if ((res.downlinks[i].commands & kLoopCmdLinkAdr) != 0) {
            drs.push_back(static_cast<int>(io.downlink_requests[i].dr));
        }
    }
    CHECK_TRUE(drs.size() >= 2);
    // Aucun débit demandé deux fois : le refus de DR5 n'est pas renvoyé.
    for (std::size_t i = 0; i < drs.size(); ++i) {
        for (std::size_t j = i + 1; j < drs.size(); ++j) CHECK_TRUE(drs[i] != drs[j]);
    }
    CHECK_EQ(drs.front(), 5);
    // Réponses : débit refusé (0x04 : DataRateACK = 0 ; ChannelMaskACK = 0 par compatibilité, D5
    // attribue le refus au débit), puis acceptation (0x07).
    bool refused_dr = false;
    bool accepted = false;
    for (std::uint8_t s : io.uplink_status) {
        if (s == 0x04) refused_dr = true;
        if (s == kAccepted) accepted = true;
    }
    CHECK_TRUE(refused_dr);
    CHECK_TRUE(accepted);
    // D5 : refus croisé attribué au débit (diagnostic exact, débit exclu côté serveur).
    bool cross = false;
    for (std::size_t i = 0; i < res.downlinks.size(); ++i) {
        if ((res.downlinks[i].commands & kLoopCmdLinkAdr) == 0 || !res.downlinks[i].delivered) continue;
        const auto& dg = io.downlink_diagnoses[i];
        if (io.downlink_requests[i].dr == 5 && dg.dr_reason == LoopDataRateReason::NotSupportedByChannels) {
            cross = true;
            CHECK_TRUE(dg.channel_reason == LoopChannelReason::IncompatibleWithDataRate);
            CHECK_TRUE(dg.refuse_dr);
            CHECK_TRUE(!dg.refuse_power);
            CHECK_TRUE(!dg.status.data_rate_ack);
            CHECK_TRUE(dg.status.power_ack);
        }
    }
    CHECK_TRUE(cross);
}

// ---- Étape 4 : exclusions après refus, frontières et renouvellement ----
// Refus de débit DR5 (terminal limité à DR0..DR3). Les compteurs sont exprimés en uplinks admissibles
// REÇUS (ordinaux) : R est l'uplink porteur de la réponse négative. Convention : l'exclusion vaut
// 100 uplinks reçus ; R+1 … R+99 restent exclus, R+100 est le premier uplink où le débit redevient
// éligible. Le refus renouvelé à R' = R+101 repousse la prochaine proposition à R'+100.
void test_dr_exclusion_boundary_99_100_and_renewal() {
    LoopChannelConfig cfg = cfg_default();
    for (std::size_t c = 0; c < 3; ++c) cfg.device.dr_mask[c] = 0x0F;  // DR0..DR3 seulement
    LoopChannelIo io;
    LoopResult res;
    SimulationStats tot;
    DeviceStats st[1];
    CHECK_EQ(static_cast<int>(run_channels(&cfg, 1, io, res, tot, st, 340)), 0);
    if (io.downlink_requests.size() != res.downlinks.size() || res.uplinks.empty()) return;
    // Ordinal (0-based) de chaque uplink reçu ; -1 pour les uplinks perdus.
    std::vector<long> ord(res.uplinks.size(), -1);
    std::vector<std::size_t> by_ord;  // ordinal -> index d'uplink
    for (std::size_t u = 0; u < res.uplinks.size(); ++u) {
        if (res.uplinks[u].outcome != TxOutcome::Received) continue;
        ord[u] = static_cast<long>(by_ord.size());
        by_ord.push_back(u);
    }
    // Ordinal de l'uplink portant la réponse LinkADR à la descente de l'uplink `u` (suivant immédiat).
    const auto answer_ordinal_after = [&](std::size_t u) -> long {
        for (std::size_t k = u + 1; k < res.uplinks.size(); ++k) {
            if (io.uplink_status[k] != 0xFF && ord[k] >= 0) return ord[k];
        }
        return -1;
    };
    // Ordinaux des uplinks porteurs d'une descente LinkADR demandant DR5.
    std::vector<long> dr5_at;
    for (std::size_t i = 0; i < res.downlinks.size(); ++i) {
        if ((res.downlinks[i].commands & kLoopCmdLinkAdr) == 0) continue;
        if (io.downlink_requests[i].dr != 5) continue;
        dr5_at.push_back(ord[static_cast<std::size_t>(res.downlinks[i].uplink)]);
    }
    CHECK_TRUE(dr5_at.size() >= 3);
    if (dr5_at.size() < 3) return;
    const long proposal1 = dr5_at[0];
    const long R = answer_ordinal_after(by_ord[static_cast<std::size_t>(proposal1)]);  // refus, ordinal R
    CHECK_TRUE(R >= 0);
    if (R < 0) return;
    // 99 uplinks admissibles après le refus : DR5 exclu, aucune proposition.
    for (long k = R + 1; k <= R + 99; ++k) {
        for (const long v : dr5_at) CHECK_TRUE(v != k);
    }
    // 100e uplink admissible après le refus : DR5 de nouveau éligible et proposé à cet uplink.
    CHECK_EQ(static_cast<int>(dr5_at[1] - R), 100);
    // Renouvellement : la proposition R+100 est refusée à nouveau (ordinal R2), et la suivante
    // n'arrive qu'après 100 uplinks admissibles reçus depuis R2.
    const long R2 = answer_ordinal_after(by_ord[static_cast<std::size_t>(dr5_at[1])]);
    CHECK_EQ(static_cast<int>(R2 - R), 101);
    CHECK_EQ(static_cast<int>(dr5_at[2] - R2), 100);
    // Chaque refus reçu a laissé le terminal sur DR0 (débit refusé jamais appliqué).
    CHECK_EQ(static_cast<int>(io.terminals[0].dr), 0);
}

// ---- Étape 3 : terminal et serveur ont des vues distinctes ; le terminal valide seul ----

// Le terminal connaît un canal 5 que le serveur ignore : la requête (bloc 0 de la vue serveur)
// l'inclut dans le bloc et le désactive. Acceptée, et la requête reprend la vue serveur (0x07),
// non l'état actif du terminal (0x27).
void test_terminal_extra_channel_unknown_to_server_follows_server_view() {
    LoopChannelConfig cfg = cfg_default();
    cfg.device.dr_mask[5] = 0x3F;
    cfg.device.enabled.set(5);
    LoopChannelIo io;
    LoopResult res;
    SimulationStats tot;
    DeviceStats st[1];
    CHECK_EQ(static_cast<int>(run_channels(&cfg, 1, io, res, tot, st)), 0);
    if (io.terminals.size() != 1) return;
    CHECK_TRUE(io.terminals[0].channels.defined(5));          // le terminal garde sa capacité
    CHECK_TRUE(!io.terminals[0].channels.enabled.test(5));    // canal 5 désactivé par le bloc serveur
    CHECK_EQ(static_cast<int>(io.terminals[0].dr), 5);
    bool seen = false;
    for (std::size_t i = 0; i < res.downlinks.size(); ++i) {
        if ((res.downlinks[i].commands & kLoopCmdLinkAdr) == 0) continue;
        seen = true;
        CHECK_EQ(static_cast<int>(io.downlink_requests[i].ch_mask), 0x07);
    }
    CHECK_TRUE(seen);
}

// Le serveur croit le canal 2 défini ; le terminal ne le définit pas : refus CM, rien appliqué,
// y compris le débit (valide) et la puissance (valide).
void test_server_channel_missing_on_terminal_refused_atomic() {
    LoopChannelConfig cfg = cfg_default();
    cfg.device.dr_mask[2] = 0;   // canal 2 non défini côté terminal
    cfg.device.enabled.reset(2);
    LoopChannelIo io;
    LoopResult res;
    SimulationStats tot;
    DeviceStats st[1];
    CHECK_EQ(static_cast<int>(run_channels(&cfg, 1, io, res, tot, st)), 0);
    if (io.terminals.size() != 1) return;
    CHECK_EQ(static_cast<int>(io.terminals[0].dr), 0);
    CHECK_TRUE(io.terminals[0].channels == cfg.device);
    bool refused = false;
    for (std::size_t i = 0; i < res.downlinks.size(); ++i) {
        if ((res.downlinks[i].commands & kLoopCmdLinkAdr) == 0 || !res.downlinks[i].delivered) continue;
        refused = true;
        CHECK_TRUE(io.downlink_diagnoses[i].channel_reason == LoopChannelReason::UndefinedChannel);
        CHECK_TRUE(io.downlink_diagnoses[i].refused_channels.test(2));
        CHECK_TRUE(!io.downlink_diagnoses[i].status.channel_mask_ack);
    }
    CHECK_TRUE(refused);
    for (std::uint8_t s : io.uplink_status) CHECK_TRUE(s != kAccepted);
}

// Combinaisons 101, 110 et 000 en boucle fermée : LinkADRReq imposée (test de robustesse),
// l'état du terminal ne doit changer dans aucun cas.
void test_forced_101_dr_refused_valid_mask_not_applied() {
    // Masque valide (canaux 0 et 1 seulement) + débit inconnu du plan (DR6) + puissance ignorée.
    LoopChannelConfig cfg = cfg_default();
    LoopLinkAdrRequest rq;
    rq.ch_mask_cntl = 0;
    rq.ch_mask = 0x0003;
    rq.dr = 6;
    rq.power_index = kLoopFieldIgnore;
    cfg.forced_request = rq;
    LoopChannelIo io;
    LoopResult res;
    SimulationStats tot;
    DeviceStats st[1];
    CHECK_EQ(static_cast<int>(run_channels(&cfg, 1, io, res, tot, st)), 0);
    if (io.terminals.size() != 1) return;
    CHECK_TRUE(io.terminals[0].channels == cfg.device);   // le masque valide n'a pas été appliqué
    CHECK_EQ(static_cast<int>(io.terminals[0].dr), 0);
    bool seen = false;
    for (std::size_t i = 0; i < res.downlinks.size(); ++i) {
        if ((res.downlinks[i].commands & kLoopCmdLinkAdr) == 0 || !res.downlinks[i].delivered) continue;
        seen = true;
        CHECK_TRUE(io.downlink_diagnoses[i].dr_reason == LoopDataRateReason::UnknownDr);
        CHECK_TRUE(io.downlink_diagnoses[i].channel_reason == LoopChannelReason::Ok);
    }
    CHECK_TRUE(seen);
    bool s101 = false;
    for (std::uint8_t s : io.uplink_status) {
        if (s == 0xFF) continue;
        CHECK_EQ(static_cast<int>(s), 0x05);  // CM=1, DR=0, PW=1
        s101 = true;
    }
    CHECK_TRUE(s101);
}

void test_forced_110_power_refused_valid_mask_and_dr_not_applied() {
    // Masque valide (canaux 0 et 1), débit DR0 supporté, puissance réservée (8).
    LoopChannelConfig cfg = cfg_default();
    LoopLinkAdrRequest rq;
    rq.ch_mask_cntl = 0;
    rq.ch_mask = 0x0003;
    rq.dr = 0;
    rq.power_index = 8;
    cfg.forced_request = rq;
    LoopChannelIo io;
    LoopResult res;
    SimulationStats tot;
    DeviceStats st[1];
    CHECK_EQ(static_cast<int>(run_channels(&cfg, 1, io, res, tot, st)), 0);
    if (io.terminals.size() != 1) return;
    CHECK_TRUE(io.terminals[0].channels == cfg.device);
    CHECK_EQ(static_cast<int>(io.terminals[0].dr), 0);
    CHECK_EQ(static_cast<int>(io.terminals[0].power_index), 0);
    bool seen = false;
    for (std::size_t i = 0; i < res.downlinks.size(); ++i) {
        if ((res.downlinks[i].commands & kLoopCmdLinkAdr) == 0 || !res.downlinks[i].delivered) continue;
        seen = true;
        CHECK_TRUE(io.downlink_diagnoses[i].power_reason == LoopPowerReason::Reserved);
    }
    CHECK_TRUE(seen);
    bool s110 = false;
    for (std::uint8_t s : io.uplink_status) {
        if (s == 0xFF) continue;
        CHECK_EQ(static_cast<int>(s), 0x03);  // CM=1, DR=1, PW=0
        s110 = true;
    }
    CHECK_TRUE(s110);
}

void test_forced_000_everything_refused() {
    // Masque vide (aucun canal actif), débit inconnu, puissance réservée.
    LoopChannelConfig cfg = cfg_default();
    LoopLinkAdrRequest rq;
    rq.ch_mask_cntl = 0;
    rq.ch_mask = 0x0000;
    rq.dr = 6;
    rq.power_index = 8;
    cfg.forced_request = rq;
    LoopChannelIo io;
    LoopResult res;
    SimulationStats tot;
    DeviceStats st[1];
    CHECK_EQ(static_cast<int>(run_channels(&cfg, 1, io, res, tot, st)), 0);
    if (io.terminals.size() != 1) return;
    CHECK_TRUE(io.terminals[0].channels == cfg.device);
    CHECK_EQ(static_cast<int>(io.terminals[0].dr), 0);
    CHECK_EQ(static_cast<int>(io.terminals[0].power_index), 0);
    bool s000 = false;
    for (std::uint8_t s : io.uplink_status) {
        if (s == 0xFF) continue;
        CHECK_EQ(static_cast<int>(s), 0x00);
        s000 = true;
    }
    CHECK_TRUE(s000);
}

// Vue serveur sans canal 2 (terminal le définit) : la requête suivante n'inclut pas le canal 2
// non demandé, et le terminal reste sur sa configuration initiale en cas d'acceptation.
void test_requests_follow_server_view_not_terminal_state() {
    LoopChannelConfig cfg = cfg_default();
    cfg.server_view = LoopChannelSet{};
    cfg.server_view.set(0);
    cfg.server_view.set(1);   // le serveur ne voit pas le canal 2 comme configuré
    LoopChannelIo io;
    LoopResult res;
    SimulationStats tot;
    DeviceStats st[1];
    CHECK_EQ(static_cast<int>(run_channels(&cfg, 1, io, res, tot, st)), 0);
    if (io.terminals.size() != 1) return;
    bool seen = false;
    for (std::size_t i = 0; i < res.downlinks.size(); ++i) {
        if ((res.downlinks[i].commands & kLoopCmdLinkAdr) == 0) continue;
        seen = true;
        CHECK_EQ(static_cast<int>(io.downlink_requests[i].ch_mask), 0x03);
    }
    CHECK_TRUE(seen);
    // Le canal 2 du terminal est désactivé par le bloc serveur (accepté, requête = vue serveur).
    CHECK_TRUE(!io.terminals[0].channels.enabled.test(2));
    CHECK_TRUE(io.terminals[0].channels.enabled.test(0));
}

void test_channel_view_outside_block0_refused() {
    LoopChannelConfig cfg = cfg_default();
    cfg.server_view.set(20);  // hors bloc 0 : ChMaskCntl 0 ne peut le représenter
    LoopChannelIo io;
    LoopResult res;
    SimulationStats tot;
    DeviceStats st[1];
    CHECK_EQ(static_cast<int>(run_channels(&cfg, 1, io, res, tot, st)), static_cast<int>(SimStatus::InvalidInput));
    cfg = cfg_default();
    cfg.server_view = LoopChannelSet{};  // vue vide
    CHECK_EQ(static_cast<int>(run_channels(&cfg, 1, io, res, tot, st)), static_cast<int>(SimStatus::InvalidInput));
    cfg = cfg_default();
    cfg.device.enabled.set(9);  // canal actif non défini côté terminal
    CHECK_EQ(static_cast<int>(run_channels(&cfg, 1, io, res, tot, st)), static_cast<int>(SimStatus::InvalidInput));
    cfg = cfg_default();
    CHECK_EQ(static_cast<int>(run_channels(&cfg, 0, io, res, tot, st)), static_cast<int>(SimStatus::InvalidInput));
}

// Configuration par défaut explicite = chemin historique (aucun écart de résultat).
void test_explicit_defaults_equal_legacy_path() {
    LoopResult legacy;
    SimulationStats tot_legacy;
    DeviceStats st_legacy[1];
    const EndDeviceSpec d[] = {dev(10.0, 12, 0, 60 * kS, 120)};
    lsim::plan::DeviceRadio rv[1] = {radio()};
    LoopRegion regions[1] = {region()};
    LoopOptions opt;
    opt.adr = true;
    CHECK_EQ(static_cast<int>(simulate_closed_loop(d, 1, rv, regions, GatewaySpec{}, PropagationSpec{}, nullptr,
                                                   opt, st_legacy, tot_legacy, legacy)),
             0);
    LoopChannelConfig cfg = cfg_default();
    LoopChannelIo io;
    LoopResult res;
    SimulationStats tot;
    DeviceStats st[1];
    CHECK_EQ(static_cast<int>(run_channels(&cfg, 1, io, res, tot, st)), 0);
    CHECK_EQ(res.uplinks.size(), legacy.uplinks.size());
    CHECK_EQ(res.downlinks.size(), legacy.downlinks.size());
    CHECK_TRUE(tot.airtime_ns == tot_legacy.airtime_ns);
    CHECK_TRUE(st[0].received == st_legacy[0].received);
    for (std::size_t i = 0; i < res.uplinks.size() && i < legacy.uplinks.size(); ++i) {
        CHECK_EQ(static_cast<int>(res.uplinks[i].spreading_factor), static_cast<int>(legacy.uplinks[i].spreading_factor));
        CHECK_EQ(static_cast<int>(res.uplinks[i].answer_ok), static_cast<int>(legacy.uplinks[i].answer_ok));
        CHECK_EQ(static_cast<int>(res.uplinks[i].outcome), static_cast<int>(legacy.uplinks[i].outcome));
    }
    // Sans configuration (nullptr), le résultat est identique à la configuration par défaut explicite.
    LoopChannelIo io_null;
    LoopResult res_null;
    SimulationStats tot_null;
    DeviceStats st_null[1];
    CHECK_EQ(static_cast<int>(run_channels(nullptr, 0, io_null, res_null, tot_null, st_null)), 0);
    CHECK_EQ(res_null.uplinks.size(), res.uplinks.size());
    CHECK_EQ(io_null.uplink_status.size(), io.uplink_status.size());
    for (std::size_t i = 0; i < io.uplink_status.size() && i < io_null.uplink_status.size(); ++i) {
        CHECK_EQ(static_cast<int>(io_null.uplink_status[i]), static_cast<int>(io.uplink_status[i]));
    }
}

}  // namespace

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
    test_exact_overlap_accepts_window_before_later_emission();
    test_adr_ack_backoff_without_downlink();
    test_linkadr_reissued_on_each_uplink_without_answer();
    test_channel_accepted_changes_terminal_state();
    test_channel_refused_mask_excluded_then_acknowledged_mask_used();
    test_partial_channel_refusal_excludes_only_unacknowledged_requested_channels();
    test_valid_new_channel_accepted_first_time();
    test_trace_v3_off_by_default();
    test_trace_v3_does_not_change_radio_or_answers();
    test_trace_v3_partial_refusal_shows_three_bits_and_exclusions();
    test_trace_v3_causal_order_and_time_sorted();
    test_trace_v3_exclusion_expired_then_recreated();
    test_mask_removing_confirmed_channels_attributes_only_suspects();
    test_d5_cm0_dr0_then_channel_refusal();
    test_valid_suspect_channel_excluded_by_over_approximation();
    test_empty_suspect_refusal_excludes_mask_without_repetition();
    test_trace_v3_mask_exclusion_renewed_while_active();
    test_trace_v3_event_semantics_answer_content_and_downlink_link();
    test_forced_refused_dr_excluded_is_the_requested_value();
    test_trace_v3_downlink_invariants();
    test_trace_v3_deterministic();
    test_data_rate_refused_then_reevaluated_without_repetition();
    test_channel_view_outside_block0_refused();
    test_explicit_defaults_equal_legacy_path();
    test_dr_exclusion_boundary_99_100_and_renewal();
    test_terminal_extra_channel_unknown_to_server_follows_server_view();
    test_server_channel_missing_on_terminal_refused_atomic();
    test_forced_101_dr_refused_valid_mask_not_applied();
    test_forced_110_power_refused_valid_mask_and_dr_not_applied();
    test_forced_000_everything_refused();
    test_requests_follow_server_view_not_terminal_state();
    test_adr_ack_counter_reset_by_downlink();
    test_absolute_gateway_sf5_threshold();
    test_absolute_gateway_refusals();
    test_absolute_gateway_no_sf5_downlink();
    test_mac_reservations_and_answers();
    test_mac_queue_defers_expires_and_conserves();
    test_mac_queue_zero_deferrals_expires_at_once();
}
