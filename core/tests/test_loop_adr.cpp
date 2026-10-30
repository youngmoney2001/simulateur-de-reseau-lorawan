// SPDX-License-Identifier: Apache-2.0
// Étape 1 ChannelMask : canaux, LinkADRReq et LinkADRAns (fonctions pures).
// Les canaux hors défaut utilisés ici sont définis directement dans les fixtures : NewChannelReq
// n'est pas modélisé, donc ce sont des hypothèses de test, pas des règles du modèle.
#include <cstdint>
#include <initializer_list>
#include <utility>

#include "check.hpp"
#include "lsim/loop_adr.hpp"

namespace {

using lsim::sim::LoopAdrStatus;
using lsim::sim::LoopChannelSet;
using lsim::sim::LoopChannelState;
using lsim::sim::LoopLinkAdrDiagnosis;
using lsim::sim::LoopLinkAdrRequest;
using lsim::sim::LoopTerminalRadio;

LoopLinkAdrRequest req(std::uint8_t cntl, std::uint16_t mask, std::uint8_t dr, std::uint8_t pw) {
    LoopLinkAdrRequest r;
    r.ch_mask_cntl = cntl;
    r.ch_mask = mask;
    r.dr = dr;
    r.power_index = pw;
    return r;
}

// Terminal : canaux définis (index, débits supportés), canaux actifs, débit et puissance courants.
LoopTerminalRadio terminal(std::initializer_list<std::pair<std::size_t, std::uint8_t>> defined,
                           std::initializer_list<std::size_t> enabled, std::uint8_t dr,
                           std::uint8_t pw) {
    LoopTerminalRadio t;
    for (const auto& [c, mask] : defined) t.channels.dr_mask[c] = mask;
    for (const std::size_t c : enabled) t.channels.enabled.set(c);
    t.dr = dr;
    t.power_index = pw;
    return t;
}

// Défaut EU868 : canaux 0..2 (DR0..DR5), actifs ; DR5, puissance 0.
LoopTerminalRadio default_terminal() {
    return terminal({{0, 0x3F}, {1, 0x3F}, {2, 0x3F}}, {0, 1, 2}, 5, 0);
}

// Défaut + un canal hors défaut supportant DR0..DR7 (hypothèse de test).
LoopTerminalRadio extended_terminal() {
    return terminal({{0, 0x3F}, {1, 0x3F}, {2, 0x3F}, {8, 0xFF}}, {0, 1, 2}, 5, 0);
}

bool same_terminal(const LoopTerminalRadio& a, const LoopTerminalRadio& b) {
    return a == b;
}

void test_plan_eu868_defaults() {
    const auto plan = lsim::sim::loop_eu868_plan();
    CHECK_EQ(plan.defaults.count(), std::size_t{3});
    CHECK_TRUE(plan.defaults.test(0) && plan.defaults.test(1) && plan.defaults.test(2));
    CHECK_EQ(static_cast<int>(plan.default_dr_mask), 0x3F);  // DR0..DR5 (RP002 Table 8)
    CHECK_EQ(static_cast<int>(plan.max_dr), 7);
    CHECK_EQ(static_cast<int>(plan.max_power_index), 7);
}

void test_wire_order_is_protocolar() {
    // TS001 Table 22 : bit 0 ChannelMaskACK, bit 1 DataRateACK, bit 2 PowerACK.
    CHECK_EQ(static_cast<int>(LoopAdrStatus{true, true, true}.to_wire()), 0x07);
    CHECK_EQ(static_cast<int>(LoopAdrStatus{false, true, true}.to_wire()), 0x06);   // 011
    CHECK_EQ(static_cast<int>(LoopAdrStatus{true, false, true}.to_wire()), 0x05);   // 101
    CHECK_EQ(static_cast<int>(LoopAdrStatus{true, true, false}.to_wire()), 0x03);   // 110
    CHECK_EQ(static_cast<int>(LoopAdrStatus{false, false, false}.to_wire()), 0x00); // 000
    // Décodage : bits RFU 3..7 ignorés, aller-retour exact sur les 8 valeurs utiles.
    for (std::uint8_t v = 0; v < 8; ++v) {
        const LoopAdrStatus s = LoopAdrStatus::from_wire(v);
        CHECK_EQ(static_cast<int>(s.to_wire()), static_cast<int>(v));
    }
    CHECK_EQ(static_cast<int>(LoopAdrStatus::from_wire(0xF8).to_wire()), 0x00);
    CHECK_TRUE(LoopAdrStatus::from_wire(0x0F).all());
}

void test_combination_111_applies() {
    LoopTerminalRadio t = default_terminal();
    const LoopTerminalRadio before = t;
    const LoopLinkAdrDiagnosis d = lsim::sim::loop_apply_link_adr(
        lsim::sim::loop_eu868_plan(), t, req(0, 0x0007, 4, 1));
    CHECK_TRUE(d.status.all());
    CHECK_EQ(static_cast<int>(d.status.to_wire()), 0x07);
    CHECK_EQ(static_cast<int>(t.dr), 4);
    CHECK_EQ(static_cast<int>(t.power_index), 1);
    CHECK_TRUE(!same_terminal(t, before));
    CHECK_EQ(t.channels.enabled.count(), std::size_t{3});
}

void test_combination_011_channel_refused_atomic() {
    // Canal 3 activé et non défini : ChannelMaskACK = 0 ; DR4 et puissance 1 sont valides.
    LoopTerminalRadio t = default_terminal();
    const LoopTerminalRadio before = t;
    const LoopLinkAdrDiagnosis d = lsim::sim::loop_apply_link_adr(
        lsim::sim::loop_eu868_plan(), t, req(0, 0x0009, 4, 1));
    CHECK_EQ(static_cast<int>(d.status.to_wire()), 0x06);
    CHECK_EQ(static_cast<int>(d.channel_reason),
             static_cast<int>(lsim::sim::LoopChannelReason::UndefinedChannel));
    CHECK_TRUE(d.refused_channels.test(3) && d.refused_channels.count() == 1);
    CHECK_TRUE(!d.refuse_dr && !d.refuse_power);
    CHECK_TRUE(same_terminal(t, before));  // rien appliqué, pas même DR4 ni puissance 1
}

void test_combination_101_data_rate_refused_atomic() {
    // DR8 hors plan modélisé : DataRateACK = 0 ; masque et puissance valides.
    LoopTerminalRadio t = default_terminal();
    const LoopTerminalRadio before = t;
    const LoopLinkAdrDiagnosis d = lsim::sim::loop_apply_link_adr(
        lsim::sim::loop_eu868_plan(), t, req(0, 0x0007, 8, 1));
    CHECK_EQ(static_cast<int>(d.status.to_wire()), 0x05);
    CHECK_EQ(static_cast<int>(d.dr_reason),
             static_cast<int>(lsim::sim::LoopDataRateReason::UnknownDr));
    CHECK_TRUE(d.refuse_dr && !d.refuse_power);
    CHECK_TRUE(d.refused_channels.count() == 0);
    CHECK_TRUE(same_terminal(t, before));
}

void test_combination_110_power_refused_atomic() {
    // Puissance 8 réservée (RP002 Table 13) : PowerACK = 0 ; masque et DR4 valides.
    LoopTerminalRadio t = default_terminal();
    const LoopTerminalRadio before = t;
    const LoopLinkAdrDiagnosis d = lsim::sim::loop_apply_link_adr(
        lsim::sim::loop_eu868_plan(), t, req(0, 0x0007, 4, 8));
    CHECK_EQ(static_cast<int>(d.status.to_wire()), 0x03);
    CHECK_EQ(static_cast<int>(d.power_reason),
             static_cast<int>(lsim::sim::LoopPowerReason::Reserved));
    CHECK_TRUE(d.refuse_power && !d.refuse_dr);
    CHECK_TRUE(same_terminal(t, before));
}

void test_combination_000_everything_refused() {
    LoopTerminalRadio t = default_terminal();
    const LoopTerminalRadio before = t;
    const LoopLinkAdrDiagnosis d = lsim::sim::loop_apply_link_adr(
        lsim::sim::loop_eu868_plan(), t, req(0, 0x0009, 8, 8));
    CHECK_EQ(static_cast<int>(d.status.to_wire()), 0x00);
    CHECK_TRUE(d.refused_channels.test(3));
    CHECK_TRUE(d.refuse_dr && d.refuse_power);
    CHECK_TRUE(same_terminal(t, before));
}

void test_cross_rule_dr6_on_default_channels_is_attributed_to_dr() {
    // D5 : masque valide (canaux 0..2) mais DR6 non supporté par ces canaux (DR0..DR5).
    // ChannelMaskACK = 0 pour incompatibilité, débit exclu (attribution au débit).
    const auto plan = lsim::sim::loop_eu868_plan();
    LoopTerminalRadio t = extended_terminal();
    const LoopTerminalRadio before = t;
    const LoopLinkAdrDiagnosis d = lsim::sim::loop_apply_link_adr(plan, t, req(0, 0x0007, 6, 0xF));
    CHECK_EQ(static_cast<int>(d.status.to_wire()), 0x04);  // 100 : puissance ignorée seule
    CHECK_EQ(static_cast<int>(d.channel_reason),
             static_cast<int>(lsim::sim::LoopChannelReason::IncompatibleWithDataRate));
    CHECK_EQ(static_cast<int>(d.dr_reason),
             static_cast<int>(lsim::sim::LoopDataRateReason::NotSupportedByChannels));
    CHECK_TRUE(d.refuse_dr && !d.refuse_power);
    CHECK_TRUE(d.refused_channels.count() == 0);  // le motif exact est conservé, pas de canal exclu
    CHECK_TRUE(same_terminal(t, before));
}

void test_cross_rule_dr6_supported_when_channel_8_enabled() {
    // Même débit, mais le masque active le canal 8 (DR0..DR7 dans la fixture) : compatible.
    LoopTerminalRadio t = extended_terminal();
    const LoopLinkAdrDiagnosis d = lsim::sim::loop_apply_link_adr(
        lsim::sim::loop_eu868_plan(), t, req(0, 0x0107, 6, 0xF));
    CHECK_EQ(static_cast<int>(d.status.to_wire()), 0x07);
    CHECK_TRUE(t.channels.enabled.test(8));
    CHECK_EQ(static_cast<int>(t.dr), 6);
}

void test_ignored_dr_incompatibility_attributed_to_channels() {
    // Débit ignoré (courant DR5). Le seul canal actif supporte DR0 : le masque est en cause,
    // le débit courant n'est pas exclu.
    LoopTerminalRadio t = terminal({{0, 0x3F}, {8, 0x01}}, {0}, 5, 0);
    const LoopTerminalRadio before = t;
    const LoopLinkAdrDiagnosis d = lsim::sim::loop_apply_link_adr(
        lsim::sim::loop_eu868_plan(), t, req(0, 0x0100, 0xF, 0xF));  // ne garde que le canal 8
    CHECK_EQ(static_cast<int>(d.status.to_wire()), 0x06);
    CHECK_EQ(static_cast<int>(d.channel_reason),
             static_cast<int>(lsim::sim::LoopChannelReason::IncompatibleWithDataRate));
    CHECK_TRUE(!d.refuse_dr);
    CHECK_TRUE(same_terminal(t, before));
}

void test_all_channels_disabled_refused() {
    LoopTerminalRadio t = default_terminal();
    const LoopTerminalRadio before = t;
    // ChMaskCntl 0 avec ChMask nul : le bloc 0..15 est désactivé, aucun canal ne reste actif.
    const LoopLinkAdrDiagnosis d = lsim::sim::loop_apply_link_adr(
        lsim::sim::loop_eu868_plan(), t, req(0, 0x0000, 0xF, 0xF));
    CHECK_EQ(static_cast<int>(d.channel_reason),
             static_cast<int>(lsim::sim::LoopChannelReason::AllDisabled));
    CHECK_TRUE(!d.status.channel_mask_ack);
    CHECK_TRUE(d.refused_channels.count() == 0);
    CHECK_TRUE(same_terminal(t, before));
}

void test_cntl6_enables_all_defined_channels() {
    LoopTerminalRadio t = terminal({{0, 0x3F}, {1, 0x3F}, {2, 0x3F}}, {0}, 5, 0);
    const LoopLinkAdrDiagnosis d = lsim::sim::loop_apply_link_adr(
        lsim::sim::loop_eu868_plan(), t, req(6, 0x0000, 0xF, 0xF));
    CHECK_TRUE(d.status.all());
    CHECK_EQ(t.channels.enabled.count(), std::size_t{3});  // tous les canaux définis, ChMask ignoré
}

void test_cntl7_rfu_refused() {
    LoopTerminalRadio t = default_terminal();
    const LoopTerminalRadio before = t;
    const LoopLinkAdrDiagnosis d = lsim::sim::loop_apply_link_adr(
        lsim::sim::loop_eu868_plan(), t, req(7, 0x0001, 4, 1));
    CHECK_EQ(static_cast<int>(d.channel_reason),
             static_cast<int>(lsim::sim::LoopChannelReason::RfuCntl));
    CHECK_TRUE(!d.status.channel_mask_ack);
    CHECK_TRUE(same_terminal(t, before));
}

void test_cntl5_banks_of_eight() {
    // Canaux 0..7 définis : la banque 0 est entièrement définie, la banque 1 ne l'est pas.
    LoopTerminalRadio t = terminal({{0, 0x3F}, {1, 0x3F}, {2, 0x3F}, {3, 0x3F},
                                    {4, 0x3F}, {5, 0x3F}, {6, 0x3F}, {7, 0x3F}},
                                   {0}, 5, 0);
    LoopTerminalRadio ok = t;
    const LoopLinkAdrDiagnosis good = lsim::sim::loop_apply_link_adr(
        lsim::sim::loop_eu868_plan(), ok, req(5, 0x0001, 5, 0));  // banque 0 seule
    CHECK_TRUE(good.status.all());
    CHECK_EQ(ok.channels.enabled.count(), std::size_t{8});

    LoopTerminalRadio bad = t;
    const LoopTerminalRadio before = bad;
    const LoopLinkAdrDiagnosis d = lsim::sim::loop_apply_link_adr(
        lsim::sim::loop_eu868_plan(), bad, req(5, 0x0003, 5, 0));  // banques 0 et 1 : 8..15 non définis
    CHECK_EQ(static_cast<int>(d.channel_reason),
             static_cast<int>(lsim::sim::LoopChannelReason::UndefinedChannel));
    CHECK_EQ(d.refused_channels.count(), std::size_t{8});
    CHECK_TRUE(same_terminal(bad, before));
}

void test_ignore_fields_keep_values() {
    LoopTerminalRadio t = default_terminal();
    const LoopLinkAdrDiagnosis d = lsim::sim::loop_apply_link_adr(
        lsim::sim::loop_eu868_plan(), t, req(0, 0x0007, 0xF, 0xF));
    CHECK_TRUE(d.status.all());
    CHECK_EQ(static_cast<int>(t.dr), 5);
    CHECK_EQ(static_cast<int>(t.power_index), 0);
}

void test_power_boundaries() {
    const auto plan = lsim::sim::loop_eu868_plan();
    LoopTerminalRadio a = default_terminal();
    CHECK_TRUE(lsim::sim::loop_apply_link_adr(plan, a, req(0, 0x0007, 4, 7)).status.all());
    CHECK_EQ(static_cast<int>(a.power_index), 7);
    LoopTerminalRadio b = default_terminal();
    const LoopLinkAdrDiagnosis d = lsim::sim::loop_apply_link_adr(plan, b, req(0, 0x0007, 4, 14));
    CHECK_EQ(static_cast<int>(d.power_reason),
             static_cast<int>(lsim::sim::LoopPowerReason::Reserved));
}

void test_validation_is_pure() {
    // La validation seule ne modifie jamais le terminal, même quand elle refuse.
    const auto plan = lsim::sim::loop_eu868_plan();
    const LoopTerminalRadio t = default_terminal();
    const LoopTerminalRadio before = t;
    const LoopLinkAdrDiagnosis d1 = lsim::sim::loop_validate_link_adr(plan, t, req(0, 0x0009, 8, 8));
    const LoopLinkAdrDiagnosis d2 = lsim::sim::loop_validate_link_adr(plan, t, req(0, 0x0009, 8, 8));
    CHECK_TRUE(same_terminal(t, before));
    CHECK_TRUE(d1.status == d2.status);
    CHECK_TRUE(d1.refused_channels == d2.refused_channels);
}

// Convention du simulateur : ChMaskCntl 5 avec un bit RFU non nul (10..15) est refusé, jamais
// appliqué silencieusement. Le terminal reste strictement inchangé.
void test_cntl5_rfu_bits_refused_atomic() {
    const lsim::sim::LoopRegionalPlan plan = lsim::sim::loop_eu868_plan();
    LoopTerminalRadio t = terminal({{0, 0x3F}, {1, 0x3F}, {2, 0x3F}}, {0, 1, 2}, 0, 0);
    const lsim::sim::LoopTerminalRadio before = t;
    // Bit 10 (RFU) à 1 avec un canal valide : refus complet.
    const lsim::sim::LoopLinkAdrDiagnosis d = lsim::sim::loop_apply_link_adr(plan, t, req(5, 0x0401, 0, 0));
    CHECK_TRUE(d.channel_reason == lsim::sim::LoopChannelReason::RfuBits);
    CHECK_TRUE(!d.status.channel_mask_ack);
    CHECK_TRUE(d.status.data_rate_ack);
    CHECK_TRUE(d.status.power_ack);
    CHECK_TRUE(t == before);
    // Bit 15 seul : refus aussi.
    const lsim::sim::LoopLinkAdrDiagnosis d2 = lsim::sim::loop_apply_link_adr(plan, t, req(5, 0x8000, 0, 0));
    CHECK_TRUE(d2.channel_reason == lsim::sim::LoopChannelReason::RfuBits);
    CHECK_TRUE(t == before);
}

// Table des débits du plan : un débit absent de la table de la région est refusé (UnknownDr),
// même si le terminal le supporte sur ses canaux.
void test_plan_dr_availability_refuses_unknown_dr() {
    lsim::sim::LoopRegionalPlan plan = lsim::sim::loop_eu868_plan();
    plan.dr_available = 0x3F;  // DR0..DR5 seulement (table 125 kHz)
    LoopTerminalRadio t = terminal({{0, 0xFF}, {1, 0xFF}, {2, 0xFF}}, {0, 1, 2}, 0, 0);
    const lsim::sim::LoopTerminalRadio before = t;
    const lsim::sim::LoopLinkAdrDiagnosis d = lsim::sim::loop_apply_link_adr(plan, t, req(0, 0x0007, 6, 0));
    CHECK_TRUE(d.dr_reason == lsim::sim::LoopDataRateReason::UnknownDr);
    CHECK_TRUE(d.refuse_dr);
    CHECK_TRUE(t == before);
}

// Étape 4 : exclusions. 99 uplinks admissibles reçus : toujours exclu ; 100e : expiré.
void test_exclusion_boundary_99_and_100() {
    lsim::sim::LoopExclusions e;
    e.exclude_dr(5);
    for (int k = 0; k < 99; ++k) e.tick();
    CHECK_TRUE(e.dr_excluded(5));
    e.tick();  // 100e uplink admissible reçu
    CHECK_TRUE(!e.dr_excluded(5));
    CHECK_EQ(static_cast<int>(lsim::sim::kLoopExclusionUplinks), 100);
}

// Renouvellement : une nouvelle réponse négative remet le compteur à 100 (pas d'expiration par
// accumulation) ; l'expiration n'est pas une acceptation et ne touche à aucun autre compteur.
void test_exclusion_renewal_resets_counter() {
    lsim::sim::LoopExclusions e;
    e.exclude_dr(5);
    for (int k = 0; k < 60; ++k) e.tick();
    e.exclude_dr(5);
    for (int k = 0; k < 99; ++k) e.tick();
    CHECK_TRUE(e.dr_excluded(5));
    e.tick();
    CHECK_TRUE(!e.dr_excluded(5));
}

// Compteurs indépendants : un débit n'exclut ni un autre débit, ni une puissance, ni le masque.
void test_exclusion_counters_are_independent() {
    lsim::sim::LoopExclusions e;
    e.exclude_dr(5);
    CHECK_TRUE(!e.dr_excluded(4));
    CHECK_TRUE(!e.power_excluded(5));
    CHECK_TRUE(!e.mask_excluded());
    for (int k = 0; k < 50; ++k) e.tick();
    e.exclude_power(1);
    e.exclude_mask();
    for (int k = 0; k < 50; ++k) e.tick();  // DR5 expire (100) ; puissance et masque restent (50)
    CHECK_TRUE(!e.dr_excluded(5));
    CHECK_TRUE(e.power_excluded(1));
    CHECK_TRUE(e.mask_excluded());
    for (int k = 0; k < 50; ++k) e.tick();
    CHECK_TRUE(!e.power_excluded(1));
    CHECK_TRUE(!e.mask_excluded());
}

// Valeurs hors bornes (index RFU ou débit absent du tableau) : ignorées, jamais de dépassement.
void test_exclusion_out_of_range_ignored() {
    lsim::sim::LoopExclusions e;
    e.exclude_dr(16);
    e.exclude_power(200);
    CHECK_TRUE(!e.dr_excluded(16));
    CHECK_TRUE(!e.power_excluded(200));
    e.tick();
    CHECK_TRUE(!e.mask_excluded());
}

}  // namespace

void run_loop_adr_tests() {
    test_plan_eu868_defaults();
    test_wire_order_is_protocolar();
    test_combination_111_applies();
    test_combination_011_channel_refused_atomic();
    test_combination_101_data_rate_refused_atomic();
    test_combination_110_power_refused_atomic();
    test_combination_000_everything_refused();
    test_cross_rule_dr6_on_default_channels_is_attributed_to_dr();
    test_cross_rule_dr6_supported_when_channel_8_enabled();
    test_ignored_dr_incompatibility_attributed_to_channels();
    test_all_channels_disabled_refused();
    test_cntl6_enables_all_defined_channels();
    test_cntl7_rfu_refused();
    test_cntl5_banks_of_eight();
    test_ignore_fields_keep_values();
    test_power_boundaries();
    test_validation_is_pure();
    test_cntl5_rfu_bits_refused_atomic();
    test_plan_dr_availability_refuses_unknown_dr();
    test_exclusion_boundary_99_and_100();
    test_exclusion_renewal_resets_counter();
    test_exclusion_counters_are_independent();
    test_exclusion_out_of_range_ignored();
}
