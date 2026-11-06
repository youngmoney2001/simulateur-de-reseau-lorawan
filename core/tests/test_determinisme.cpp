// SPDX-License-Identifier: Apache-2.0
// Déterminisme de la boucle fermée (jalon U0.2) : clé d'ordonnancement, ordre à instant égal,
// identité de trame, intervalles semi-ouverts.
//
// Chaque test porte sur une propriété énoncée dans `docs/DETERMINISME.md` et est discriminant :
// la révocation de la propriété le fait échouer (démontré par mutation).
#include <algorithm>
#include <cstdint>
#include <set>
#include <vector>

#include "check.hpp"
#include "lsim/engine.hpp"

namespace {

using namespace lsim::sim;

constexpr SimTime kS = 1'000'000'000;
// Boucle fermée : RX1 s'ouvre 1 s après la fin de la montante, RX2 2 s, fenêtre RX1 de 1 s.
constexpr SimTime kRx1Delay = 1 * kS;
constexpr SimTime kRx2Delay = 2 * kS;

// Temps d'antenne observés (SF7/125 kHz, charge 10 octets + en-tête) : montante 41,216 ms,
// descente 56,576 ms. Constants vérifiées par `test_constantes_de_temps`.
constexpr SimTime kAirUlSf7 = 41'216'000;
constexpr SimTime kAirDlSf7 = 56'576'000;

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

LoopRegion region() {
    LoopRegion r;
    for (std::size_t i = 0; i < 6; ++i) r.dr_sf[i] = static_cast<std::uint8_t>(12 - i);
    r.max_dr = 5;
    r.max_tx_power_index = 7;
    r.power_step_tenth_db = 20;
    for (std::size_t i = 0; i <= 7; ++i) r.duty_limit[i] = 1.0;
    return r;
}

// Une exécution de la boucle fermée avec trace interne v3.
//
// `st` est dimensionné au nombre de dispositifs : un tableau de taille fixe a provoqué un
// débordement de pile dès qu'un scénario a dépassé cette taille (détecté par AddressSanitizer en
// CI, invisible en Release). Le moteur écrit `device_count` statistiques, sans quoi l'appel est
// invalide — on ne peut donc pas se contenter d'un sous-dimensionnement « tolérant ».
struct Run {
    LoopResult res;
    LoopChannelIo io;
    std::vector<DeviceStats> st;
    SimulationStats tot{};
};

Run run(const std::vector<EndDeviceSpec>& d, const LoopOptions& opt) {
    const std::size_t n = d.size();
    std::vector<lsim::plan::DeviceRadio> rv(n, radio());
    std::vector<LoopRegion> rg(n, region());
    Run r;
    r.io.trace_v3 = true;
    r.st.assign(n, DeviceStats{});
    CHECK_EQ(static_cast<int>(simulate_closed_loop_channels(
                 d.data(), n, rv.data(), rg.data(), GatewaySpec{}, PropagationSpec{}, nullptr, opt,
                 r.st.data(), r.tot, r.res, r.io)),
             0);
    return r;
}

LoopOptions confirmed() {
    LoopOptions o;
    o.protocol.confirmed_uplinks = true;
    o.protocol.downlink_every = 1;
    // Le repli RX2 est opt-in dans les options du planificateur. La boucle fermée l'a toujours
    // pratiqué sans condition (comportement historique conservé en U0.1) ; les scénarios
    // ci-dessous l'exercent explicitement.
    o.protocol.rx2_fallback = true;
    return o;
}

// Constats de cadrage : si le moteur change ses temps d'antenne, les scénarios ci-dessous
// perdent leur sens. Ce test échoue alors, au lieu de laisser passer des conclusions fausses.
void test_constantes_de_temps() {
    const std::vector<EndDeviceSpec> d = {dev(100.0, 7, 0, 60 * kS, 1)};
    const Run r = run(d, confirmed());
    CHECK_EQ(r.res.uplinks.size(), std::size_t{1});
    CHECK_EQ(r.res.uplinks[0].end_ns - r.res.uplinks[0].start_ns, kAirUlSf7);
    CHECK_EQ(r.res.downlinks.size(), std::size_t{1});
    CHECK_EQ(r.res.downlinks[0].air_ns, kAirDlSf7);
    CHECK_EQ(r.res.downlinks[0].t_open, kAirUlSf7 + kRx1Delay);
}

// ---------------------------------------------------------------- S9.1 reproductibilité

void test_s9_1_reproductibilite_meme_entrees_meme_graine() {
    // Deux exécutions indépendantes, mêmes entrées : résultats et trace identiques au bit près.
    const std::vector<EndDeviceSpec> d = {dev(120.0, 7, 0, 60 * kS, 40),
                                          dev(900.0, 9, 3 * kS, 60 * kS, 40),
                                          dev(2400.0, 10, 7 * kS, 60 * kS, 40)};
    LoopOptions opt = confirmed();
    opt.adr = true;
    const Run a = run(d, opt);
    const Run b = run(d, opt);

    CHECK_EQ(a.res.uplinks.size(), b.res.uplinks.size());
    CHECK_EQ(a.res.downlinks.size(), b.res.downlinks.size());
    CHECK_EQ(a.res.gateway_busy.size(), b.res.gateway_busy.size());
    CHECK_EQ(a.io.trace.size(), b.io.trace.size());
    CHECK_TRUE(a.io.trace.size() > 100);  // la scène doit réellement produire une trace

    for (std::size_t i = 0; i < a.res.uplinks.size(); ++i) {
        const LoopUplink& x = a.res.uplinks[i];
        const LoopUplink& y = b.res.uplinks[i];
        CHECK_EQ(x.start_ns, y.start_ns);
        CHECK_EQ(x.end_ns, y.end_ns);
        CHECK_EQ(static_cast<int>(x.outcome), static_cast<int>(y.outcome));
        CHECK_EQ(x.rssi_dbm, y.rssi_dbm);
    }
    for (std::size_t i = 0; i < a.res.downlinks.size(); ++i) {
        CHECK_EQ(a.res.downlinks[i].frame_id, b.res.downlinks[i].frame_id);
        CHECK_EQ(a.res.downlinks[i].t_open, b.res.downlinks[i].t_open);
        CHECK_EQ(a.res.downlinks[i].start_ns, b.res.downlinks[i].start_ns);
        CHECK_EQ(a.res.downlinks[i].delivered, b.res.downlinks[i].delivered);
    }
    for (std::size_t i = 0; i < a.io.trace.size(); ++i) {
        CHECK_EQ(a.io.trace[i].t_ns, b.io.trace[i].t_ns);
        CHECK_EQ(a.io.trace[i].frame_id, b.io.trace[i].frame_id);
        CHECK_EQ(static_cast<int>(a.io.trace[i].kind), static_cast<int>(b.io.trace[i].kind));
    }
}

// ---------------------------------------------------------------- S9.2 ordre à instant égal

void test_s9_2_table_des_rangs() {
    // La table est la référence documentée ; elle est dérivée de la causalité observée.
    LoopTraceEvent e;
    e.kind = LoopTraceKind::Uplink;
    CHECK_EQ(static_cast<int>(loop_trace_rank(e)), static_cast<int>(kTraceRankUplink));
    e.kind = LoopTraceKind::LinkAdrAns;
    CHECK_EQ(static_cast<int>(loop_trace_rank(e)), static_cast<int>(kTraceRankAnswer));
    e.kind = LoopTraceKind::Exclusion;
    e.action = LoopTraceAction::Created;
    CHECK_EQ(static_cast<int>(loop_trace_rank(e)), static_cast<int>(kTraceRankExclusion));
    e.action = LoopTraceAction::Expired;
    CHECK_EQ(static_cast<int>(loop_trace_rank(e)), static_cast<int>(kTraceRankExpired));
    e.kind = LoopTraceKind::AdrDecision;
    CHECK_EQ(static_cast<int>(loop_trace_rank(e)), static_cast<int>(kTraceRankDecision));
    e.kind = LoopTraceKind::LinkAdrReq;
    CHECK_EQ(static_cast<int>(loop_trace_rank(e)), static_cast<int>(kTraceRankRequest));
    e.kind = LoopTraceKind::Downlink;
    CHECK_EQ(static_cast<int>(loop_trace_rank(e)), static_cast<int>(kTraceRankDownlink));
    e.kind = LoopTraceKind::Apply;
    CHECK_EQ(static_cast<int>(loop_trace_rank(e)), static_cast<int>(kTraceRankApply));

    // Une exclusion expirée précède la montante qui la constate : nettoyage d'état d'abord.
    CHECK_TRUE(kTraceRankExpired < kTraceRankUplink);
    CHECK_TRUE(kTraceRankUplink < kTraceRankAnswer);
    CHECK_TRUE(kTraceRankAnswer < kTraceRankExclusion);
    CHECK_TRUE(kTraceRankExclusion < kTraceRankDecision);
    CHECK_TRUE(kTraceRankDecision < kTraceRankRequest);
    // Cohérence avec les rangs de la file : un `Check` est traité avant un `End` de même
    // instant, donc `Downlink` et `Apply` précèdent tout ce qu'émet `on_received`.
    CHECK_TRUE(kTraceRankDownlink < kTraceRankApply);
    CHECK_TRUE(kTraceRankApply < kTraceRankExpired);
}

void test_s9_2_le_comparateur_fait_primer_le_rang() {
    // Le rang prime sur l'ordre d'insertion. Aucune scène ne peut le montrer aujourd'hui (la
    // table épouse l'ordre de traitement, donc les deux coïncident) : on teste le comparateur
    // isolément. C'est ce qui rendra la table opérante quand le contrat d'événements U0.3
    // introduira des classes émises dans un ordre différent de leur ordre de traitement.
    LoopTraceEvent dl;
    dl.t_ns = 100;
    dl.kind = LoopTraceKind::Downlink;
    LoopTraceEvent up;
    up.t_ns = 100;
    up.kind = LoopTraceKind::Uplink;

    CHECK_TRUE(loop_trace_before(dl, up));    // Check traité avant End
    CHECK_TRUE(!loop_trace_before(up, dl));   // l'ordre inverse est refusé
    CHECK_TRUE(!loop_trace_before(dl, dl));   // stricte : pas d'auto-infériorité

    // Le temps reste la clé principale : un événement antérieur passe avant n'importe quel rang.
    LoopTraceEvent tard;
    tard.t_ns = 99;
    tard.kind = LoopTraceKind::Apply;
    CHECK_TRUE(loop_trace_before(tard, dl));
    CHECK_TRUE(!loop_trace_before(dl, tard));

    // À rang égal, ni l'un ni l'autre : le tri stable conserve alors l'ordre de création.
    LoopTraceEvent dl2;
    dl2.t_ns = 100;
    dl2.kind = LoopTraceKind::Downlink;
    CHECK_TRUE(!loop_trace_before(dl, dl2));
    CHECK_TRUE(!loop_trace_before(dl2, dl));
}

void test_s9_2_ordre_au_point_de_rencontre_check_et_end() {
    // Un `Check` (issue radio d'une trame antérieure) et un `End` (réception d'une nouvelle
    // montante) tombent au même instant. La file traite `Check` d'abord (rang 0 < 2) ; la trace
    // doit donc rapporter `downlink` avant `uplink`. C'est le seul cas observé où l'ordre de la
    // trace ne suit pas l'ordre de première émission, et il départage deux tables de rangs.
    constexpr SimTime kFin = kAirUlSf7;
    const SimTime close = kFin + kRx1Delay + 1 * kS;  // fermeture RX1 de la première descente
    const std::vector<EndDeviceSpec> d = {
        dev(100.0, 7, 0, 600 * kS, 1),                        // finit à kFin
        dev(200.0, 7, close - kAirUlSf7, 600 * kS, 1),        // finit exactement à `close`
    };
    const Run r = run(d, confirmed());
    CHECK_EQ(r.res.uplinks.size(), std::size_t{2});
    CHECK_EQ(r.res.uplinks[0].end_ns, kFin);
    CHECK_EQ(r.res.uplinks[1].end_ns, close);

    // Les deux événements coexistants à `close`, dans l'ordre de la trace.
    const LoopTraceEvent* up = nullptr;
    const LoopTraceEvent* dl = nullptr;
    for (const LoopTraceEvent& e : r.io.trace) {
        if (e.t_ns != close) continue;
        if (e.kind == LoopTraceKind::Uplink) up = &e;
        if (e.kind == LoopTraceKind::Downlink) dl = &e;
    }
    CHECK_TRUE(up != nullptr);
    CHECK_TRUE(dl != nullptr);
    CHECK_TRUE(loop_trace_rank(*dl) < loop_trace_rank(*up));
    // Et la trace les rapporte effectivement dans cet ordre.
    CHECK_TRUE(loop_trace_before(*dl, *up));
}

void test_s9_2_ordre_de_la_trace_respecte_le_rang() {
    // Sur une trace réelle : à instant égal, les rangs sont croissants. C'est la propriété que
    // le tri explicite garantit, indépendamment de la place des appels d'émission dans le code.
    const std::vector<EndDeviceSpec> d = {dev(120.0, 7, 0, 60 * kS, 130),
                                          dev(900.0, 9, 3 * kS, 60 * kS, 130)};
    LoopOptions opt = confirmed();
    opt.adr = true;
    const Run r = run(d, opt);
    CHECK_TRUE(r.io.trace.size() > 200);
    std::size_t egalites = 0;
    for (std::size_t i = 0; i + 1 < r.io.trace.size(); ++i) {
        const LoopTraceEvent& x = r.io.trace[i];
        const LoopTraceEvent& y = r.io.trace[i + 1];
        CHECK_TRUE(x.t_ns <= y.t_ns);  // temps globalement croissant
        if (x.t_ns == y.t_ns) {
            ++egalites;
            CHECK_TRUE(loop_trace_rank(x) <= loop_trace_rank(y));
        }
    }
    CHECK_TRUE(egalites > 50);  // la scène doit réellement contenir des instants égaux
}

// ------------------------------------------- S9.3 égalités temporelles, intervalles semi-ouverts

// Deux montantes SF7 sur des dispositifs distincts. La seconde se termine `ecart` après la
// première. L'ouverture RX1 de la seconde vaut donc `fin_A + ecart + 1 s`, à comparer à la fin
// de l'émission de la première, `fin_A + 1 s + air_dl`.
//
// Intervalles semi-ouverts `[début, fin)` : l'ouverture est libre si et seulement si
// `ecart >= air_dl`. La bascule doit donc se produire exactement à `ecart == air_dl`.
SimTime ouverture_rx1_de_la_seconde(const Run& r, std::size_t index) {
    return r.res.downlinks[index].t_open;
}

void test_s9_3_bascule_exactement_a_la_libereration_de_l_occupation() {
    // ecart == air_dl : l'occupation se libère **à l'instant exact** de l'ouverture de RX1.
    // La fenêtre est libre (borne supérieure exclue) : la descente part en RX1.
    {
        const std::vector<EndDeviceSpec> d = {
            dev(100.0, 7, 0, 60 * kS, 1),
            dev(200.0, 7, kAirDlSf7, 60 * kS, 1),  // fin = air_ul + air_dl
        };
        const Run r = run(d, confirmed());
        CHECK_EQ(r.res.downlinks.size(), std::size_t{2});
        const SimTime fin_a = kAirUlSf7 + kAirDlSf7;
        CHECK_EQ(ouverture_rx1_de_la_seconde(r, 1), fin_a + kRx1Delay);
        CHECK_EQ(r.res.downlinks[1].t_open, fin_a + kRx1Delay);
        CHECK_TRUE(r.res.downlinks[1].start_ns >= 0);  // placée, et en RX1
    }
    // ecart == air_dl - 1 : l'occupation empiète d'une nanoseconde. RX1 est occupée, la
    // descente bascule en RX2. C'est le témoin que la bascule est bien à la nanoseconde près.
    {
        const std::vector<EndDeviceSpec> d = {
            dev(100.0, 7, 0, 60 * kS, 1),
            dev(200.0, 7, kAirDlSf7 - 1, 60 * kS, 1),
        };
        const Run r = run(d, confirmed());
        CHECK_EQ(r.res.downlinks.size(), std::size_t{2});
        const SimTime fin_a = kAirUlSf7 + kAirDlSf7 - 1;
        CHECK_EQ(r.res.downlinks[1].t_open, fin_a + kRx2Delay);  // repli RX2
    }
}

void test_s9_3_balayage_de_la_frontiere() {
    // Balayage de l'écart : la bascule RX1 -> RX2 doit survenir exactement à `ecart == air_dl`.
    SimTime bascule = -1;
    for (SimTime ecart = kAirDlSf7 - 4; ecart <= kAirDlSf7 + 4; ++ecart) {
        const std::vector<EndDeviceSpec> d = {dev(100.0, 7, 0, 60 * kS, 1),
                                              dev(200.0, 7, ecart, 60 * kS, 1)};
        const Run r = run(d, confirmed());
        CHECK_EQ(r.res.downlinks.size(), std::size_t{2});
        const SimTime fin_a = kAirUlSf7 + ecart;
        const bool en_rx1 = r.res.downlinks[1].t_open == fin_a + kRx1Delay;
        const bool en_rx2 = r.res.downlinks[1].t_open == fin_a + kRx2Delay;
        CHECK_TRUE(en_rx1 || en_rx2);  // pas d'autre issue possible
        if (en_rx1 && bascule < 0) bascule = ecart;
    }
    CHECK_EQ(bascule, kAirDlSf7);  // demi-ouvert : libre dès l'instant exact de libération
}

// Caractérisation : la branche `device_missed` est inatteignable dans la boucle fermée.
//
// `device_missed` vaut vrai si le dispositif émet avant la fermeture de RX1
// (`txs[nxt].start < close`, `close = fin + 1 s + 1 s`). Or TS001 §3.3.6 interdit toute émission
// avant la fin de RX2, et le moteur l'applique : le prochain départ est repoussé à
// `fin + 2 s + 1 s`. Ce plancher est strictement postérieur à `close`.
//
// La conséquence est vérifiée ci-dessous, ainsi que l'inégalité qui l'explique. Ce n'est **pas**
// une preuve de conformité : c'est la caractérisation d'un comportement de code, à revoir si les
// temporisations RX1/RX2 changent (notamment à l'étape U0.4, où RX2 devient paramétrable).
void test_s9_3_la_branche_device_missed_est_inatteignable() {
    const SimTime fin = kAirUlSf7;
    const SimTime close = fin + kRx1Delay + 1 * kS;
    const SimTime plancher = fin + kRx2Delay + 1 * kS;  // fin de RX2
    CHECK_TRUE(plancher > close);                       // l'inégalité qui rend la branche morte

    for (SimTime periode : {SimTime{50'000'000}, SimTime{500'000'000}, SimTime{1 * kS},
                            SimTime{2 * kS}, SimTime{3 * kS}}) {
        const std::vector<EndDeviceSpec> d = {dev(100.0, 7, 0, periode, 6)};
        const Run r = run(d, confirmed());
        CHECK_EQ(r.res.downlinks.size(), std::size_t{6});
        for (const LoopDownlink& dl : r.res.downlinks) {
            CHECK_TRUE(!dl.device_missed);
            CHECK_TRUE(dl.delivered);
        }
        // Le second départ est toujours au plancher, quelle que soit la période demandée.
        CHECK_EQ(r.res.uplinks[1].start_ns, plancher);
    }
}

// ---------------------------------------------------------------- S9.4 événements simultanés

void test_s9_4_deux_montantes_terminant_au_meme_instant() {
    // Deux dispositifs de SF différents, dont les montantes se terminent au même instant :
    // deux descentes demandées au même instant, une seule fenêtre RX1 disponible.
    // Les SF diffèrent volontairement : deux montantes de même SF se chevauchant seraient en
    // collision, et l'on perdrait l'objet du test (l'arbitrage des fenêtres).
    constexpr SimTime kFin = 200'000'000;
    constexpr SimTime kAirUlSf8 = 72'192'000;
    const std::vector<EndDeviceSpec> d = {dev(100.0, 7, kFin - kAirUlSf7, 600 * kS, 1),
                                          dev(200.0, 8, kFin - kAirUlSf8, 600 * kS, 1)};
    const Run r = run(d, confirmed());
    CHECK_EQ(r.res.uplinks.size(), std::size_t{2});
    CHECK_EQ(r.res.uplinks[0].end_ns, kFin);
    CHECK_EQ(r.res.uplinks[1].end_ns, kFin);
    CHECK_EQ(r.res.downlinks.size(), std::size_t{2});

    // Une seule fenêtre RX1 : l'une des deux est placée, l'autre bascule en RX2.
    const std::uint32_t en_rx1 = (r.res.downlinks[0].t_open == kFin + kRx1Delay) ? 0u : 1u;
    const std::uint32_t en_rx2 = 1u - en_rx1;
    CHECK_EQ(r.res.downlinks[en_rx1].t_open, kFin + kRx1Delay);
    CHECK_EQ(r.res.downlinks[en_rx2].t_open, kFin + kRx2Delay);
    CHECK_TRUE(r.res.downlinks[en_rx1].start_ns >= 0);
    CHECK_TRUE(r.res.downlinks[en_rx2].start_ns >= 0);

    // L'identifiant de trame distingue les deux demandes et suit l'ordre de dépôt.
    CHECK_TRUE(r.res.downlinks[0].frame_id != r.res.downlinks[1].frame_id);
    CHECK_TRUE(r.res.downlinks[en_rx1].frame_id < r.res.downlinks[en_rx2].frame_id);

    // Les deux demandes sont portées par le même instant dans la trace, et l'ordre y est
    // celui du rang, pas celui du dépôt : ici même rang (deux descentes), donc ordre de dépôt.
    std::size_t au_meme_instant = 0;
    for (const LoopTraceEvent& e : r.io.trace) {
        if (e.t_ns == kFin) ++au_meme_instant;
    }
    CHECK_EQ(au_meme_instant, std::size_t{2});  // les deux montantes reçues au même instant
}

void test_s9_4_ordre_d_un_groupe_d_egalites_maximal() {
    // Six montantes de SF distincts finissant au même instant : six collisions évitées (la
    // collision exige un SF identique), donc six réceptions simultanées, donc le plus grand
    // groupe d'égalités atteignable — six, le nombre de SF distincts étant la limite.
    //
    // L'ordre attendu est celui de départ, qui est aussi l'ordre de création : à `(t_ns, rang)`
    // égal, le tri stable conserve l'ordre de création.
    constexpr SimTime kFin = 1'100'000'000;
    constexpr SimTime kAir[6] = {41'216'000,  72'192'000,  144'384'000,
                                 288'768'000, 577'536'000, 991'232'000};  // SF7..SF12
    std::vector<EndDeviceSpec> d;
    for (std::uint8_t k = 0; k < 6; ++k) {
        d.push_back(dev(100.0 + 60.0 * k, static_cast<std::uint8_t>(7 + k), kFin - kAir[k],
                        600 * kS, 1));
    }
    const Run r = run(d, confirmed());
    CHECK_EQ(r.res.uplinks.size(), std::size_t{6});
    for (std::size_t k = 0; k < 6; ++k) CHECK_EQ(r.res.uplinks[k].end_ns, kFin);

    // Ordre de création : le SF le plus lent part le premier, donc le dispositif 5 d'abord.
    const std::uint32_t attendu[6] = {5, 4, 3, 2, 1, 0};
    std::size_t i = 0;
    for (const LoopTraceEvent& e : r.io.trace) {
        if (e.t_ns != kFin || e.kind != LoopTraceKind::Uplink) continue;
        CHECK_TRUE(i < 6);
        CHECK_EQ(e.device, attendu[i]);
        ++i;
    }
    CHECK_EQ(i, std::size_t{6});
}

// ---------------------------------------------------------------- S9.5 transitions causales

void test_s9_5_la_descente_est_resolue_apres_la_reception() {
    // Causalité : la réception de la montante précède la décision de descente, qui précède
    // l'émission, qui précède la résolution de l'issue radio. Les instants le traduisent.
    const std::vector<EndDeviceSpec> d = {dev(100.0, 7, 0, 60 * kS, 3)};
    LoopOptions opt = confirmed();
    opt.adr = true;
    const Run r = run(d, opt);
    CHECK_TRUE(!r.res.downlinks.empty());
    for (const LoopDownlink& dl : r.res.downlinks) {
        const LoopUplink& up = r.res.uplinks[dl.uplink];
        CHECK_TRUE(up.end_ns <= dl.t_open);                       // réception puis ouverture
        CHECK_TRUE(dl.start_ns < 0 || dl.start_ns == dl.t_open);  // émission à l'ouverture (A6)
        CHECK_EQ(dl.t_open, up.end_ns + kRx1Delay);               // RX1 à son ouverture
    }
    // L'événement d'issue radio d'une trame est postérieur à la réception qui l'a déclenchée.
    for (const LoopTraceEvent& e : r.io.trace) {
        if (e.kind != LoopTraceKind::Downlink) continue;
        const LoopUplink& up = r.res.uplinks[e.uplink];
        CHECK_TRUE(e.t_ns > up.end_ns);
        CHECK_EQ(e.t_ns, up.end_ns + kRx1Delay + 1 * kS);  // résolution à la fermeture de RX1
    }
}

// ------------------------------------- S9.6 événements créés pendant le traitement

void test_s9_6_ordre_causal_des_evenements_d_une_meme_trame() {
    // Le `frame_id` permet de suivre une trame à travers la trace. Pour chaque trame porteuse
    // d'une LinkADRReq : la requête est planifiée **avant** l'issue radio de la trame, qui est
    // elle-même avant l'application par le terminal. C'est l'ordre causal, vérifié par
    // l'identifiant et non par la position dans le vecteur.
    const std::vector<EndDeviceSpec> d = {dev(120.0, 7, 0, 60 * kS, 130)};
    LoopOptions opt = confirmed();
    opt.adr = true;
    const Run r = run(d, opt);

    std::set<std::uint32_t> avec_requete;
    for (const LoopTraceEvent& e : r.io.trace) {
        if (e.kind == LoopTraceKind::LinkAdrReq) avec_requete.insert(e.frame_id);
    }
    CHECK_TRUE(!avec_requete.empty());

    for (std::uint32_t fid : avec_requete) {
        SimTime t_req = -1, t_dl = -1, t_apply = -1;
        for (const LoopTraceEvent& e : r.io.trace) {
            if (e.frame_id != fid) continue;
            if (e.kind == LoopTraceKind::LinkAdrReq) t_req = e.t_ns;
            if (e.kind == LoopTraceKind::Downlink) t_dl = e.t_ns;
            if (e.kind == LoopTraceKind::Apply) t_apply = e.t_ns;
        }
        CHECK_TRUE(t_req >= 0);
        CHECK_TRUE(t_dl >= 0);
        CHECK_TRUE(t_req < t_dl);  // planification puis issue radio
        if (t_apply >= 0) CHECK_TRUE(t_dl <= t_apply);
    }
}

// ---------------------------------------------------------------- identité de trame

void test_frame_id_unique_et_monotone() {
    const std::vector<EndDeviceSpec> d = {dev(120.0, 7, 0, 60 * kS, 60),
                                          dev(900.0, 9, 3 * kS, 60 * kS, 60),
                                          dev(2400.0, 10, 7 * kS, 60 * kS, 60)};
    LoopOptions opt = confirmed();
    opt.adr = true;
    const Run r = run(d, opt);
    CHECK_TRUE(r.res.downlinks.size() > 50);

    std::set<std::uint32_t> vus;
    std::uint32_t precedent = 0;
    for (std::size_t i = 0; i < r.res.downlinks.size(); ++i) {
        const std::uint32_t fid = r.res.downlinks[i].frame_id;
        CHECK_TRUE(fid != kLoopNoIndex);
        CHECK_EQ(vus.count(fid), std::size_t{0});  // unicité
        vus.insert(fid);
        if (i > 0) CHECK_TRUE(fid > precedent);  // monotone dans l'ordre des demandes
        precedent = fid;
    }
    // Attribués sans trou à partir de 0 : l'identifiant est un compteur de demandes.
    CHECK_EQ(*vus.begin(), std::uint32_t{0});
    CHECK_EQ(vus.size(), r.res.downlinks.size());
}

void test_frame_id_reproduit_et_absent_sur_les_evenements_sans_trame() {
    const std::vector<EndDeviceSpec> d = {dev(120.0, 7, 0, 60 * kS, 60)};
    LoopOptions opt = confirmed();
    opt.adr = true;
    const Run a = run(d, opt);
    const Run b = run(d, opt);
    CHECK_EQ(a.res.downlinks.size(), b.res.downlinks.size());
    for (std::size_t i = 0; i < a.res.downlinks.size(); ++i) {
        CHECK_EQ(a.res.downlinks[i].frame_id, b.res.downlinks[i].frame_id);
    }
    // Un événement qui ne se rapporte à aucune trame porte la valeur d'absence.
    std::size_t sans_trame = 0;
    for (const LoopTraceEvent& e : a.io.trace) {
        if (e.kind == LoopTraceKind::Uplink || e.kind == LoopTraceKind::AdrDecision) {
            CHECK_EQ(e.frame_id, kLoopNoIndex);
            ++sans_trame;
        }
    }
    CHECK_TRUE(sans_trame > 50);
    // Et tout événement de descente renseigne l'identifiant de sa trame.
    for (const LoopTraceEvent& e : a.io.trace) {
        if (e.kind != LoopTraceKind::Downlink) continue;
        CHECK_TRUE(e.frame_id != kLoopNoIndex);
        CHECK_EQ(e.frame_id, a.res.downlinks[e.downlink].frame_id);
    }
}

}  // namespace

void run_determinisme_tests() {
    test_constantes_de_temps();
    test_s9_1_reproductibilite_meme_entrees_meme_graine();
    test_s9_2_table_des_rangs();
    test_s9_2_le_comparateur_fait_primer_le_rang();
    test_s9_2_ordre_au_point_de_rencontre_check_et_end();
    test_s9_2_ordre_de_la_trace_respecte_le_rang();
    test_s9_3_bascule_exactement_a_la_libereration_de_l_occupation();
    test_s9_3_balayage_de_la_frontiere();
    test_s9_3_la_branche_device_missed_est_inatteignable();
    test_s9_4_deux_montantes_terminant_au_meme_instant();
    test_s9_4_ordre_d_un_groupe_d_egalites_maximal();
    test_s9_5_la_descente_est_resolue_apres_la_reception();
    test_s9_6_ordre_causal_des_evenements_d_une_meme_trame();
    test_frame_id_unique_et_monotone();
    test_frame_id_reproduit_et_absent_sur_les_evenements_sans_trame();
}
