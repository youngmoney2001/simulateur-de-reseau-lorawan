// SPDX-License-Identifier: Apache-2.0
// Tests du frontal RF v4 (R2b) : sémantique de la chaîne, indépendance des champs présents,
// comptage unique du gain, tables 0 ou complètes, et compatibilité stricte avec la base.
#include <cmath>
#include <cstddef>
#include <cstring>
#include <vector>

#include "check.hpp"
#include "lsim/c_api.h"
#include "lsim/engine.hpp"

namespace {

using lsim::sim::RadioFrontend;

constexpr int32_t kInvalid =
    LSIM_STATUS_SIM_BASE + static_cast<int32_t>(lsim::sim::SimStatus::InvalidInput);

// Propagation de référence des tests : EU868, 1 m, exposant 2,7.
lsim_propagation propagation() {
    lsim_propagation p{};
    p.frequency_hz = 868.1e6;
    p.reference_distance_m = 1.0;
    p.exponent = 2.7;
    p.capture_threshold_db = 6.0;
    return p;
}

lsim_end_device device(double x_m, double tx_power_dbm, uint8_t sf = 9) {
    lsim_end_device d{};
    d.x_m = x_m;
    d.spreading_factor = sf;
    d.payload_bytes = 10;
    d.tx_power_dbm = tx_power_dbm;
    d.period_ns = 60'000'000'000LL;
    d.messages = 1;
    d.duty_cycle = 1.0;
    return d;
}

lsim_gateway gateway(double gain_dbi) {
    lsim_gateway g{};
    g.antenna_gain_dbi = gain_dbi;
    return g;
}

// RSSI de la première émission d'un dispositif isolé, avec frontaux optionnels.
double rssi_of(const lsim_end_device& d, const lsim_gateway& g, const lsim_device_rf* drf,
               const lsim_gateway_rf* grf) {
    lsim_propagation p = propagation();
    lsim_device_stats stats{};
    lsim_sim_stats totals{};
    lsim_tx_record rec{};
    size_t count = 0;
    const int32_t st = lsim_simulate_uplinks_trace_v3(&d, 1, &g, &p, nullptr, &stats, &totals,
                                                      &rec, 1, &count, nullptr, 0, nullptr, 0,
                                                      drf, drf == nullptr ? 0 : 1, grf);
    CHECK_EQ(static_cast<int>(st), 0);
    CHECK_EQ(static_cast<int>(count), 1);
    return rec.rssi_dbm;
}


// Statut d'un appel de trace avec un frontal terminal, sans assertion sur le succès.
int32_t rssi_status(const lsim_end_device& d, const lsim_gateway& g, const lsim_device_rf* drf) {
    lsim_propagation p = propagation();
    lsim_gateway gw = g;
    lsim_device_stats stats{};
    lsim_sim_stats totals{};
    lsim_tx_record rec{};
    size_t count = 0;
    return lsim_simulate_uplinks_trace_v3(&d, 1, &gw, &p, nullptr, &stats, &totals, &rec, 1,
                                          &count, nullptr, 0, nullptr, 0, drf, 1, nullptr);
}

// Issues de descente (encodage de lsim_downlink_record : 0 reçu, 1 sous la sensibilité).
constexpr int kDlReceived = 0;
constexpr int kDlLostSensitivity = 1;


// ---------------------------------------------------------------- 0. Disposition ABI

void test_rf_structs_have_a_fixed_layout() {
    // Taille et décalages publics : une extension future doit passer par une nouvelle version.
    CHECK_EQ(static_cast<int>(sizeof(lsim_device_rf)), 24);
    CHECK_EQ(static_cast<int>(offsetof(lsim_device_rf, present)), 0);
    CHECK_EQ(static_cast<int>(offsetof(lsim_device_rf, antenna_gain_dbi)), 8);
    CHECK_EQ(static_cast<int>(offsetof(lsim_device_rf, cable_loss_db)), 16);

    CHECK_EQ(static_cast<int>(sizeof(lsim_gateway_rf)), 24);
    CHECK_EQ(static_cast<int>(offsetof(lsim_gateway_rf, present)), 0);
    CHECK_EQ(static_cast<int>(offsetof(lsim_gateway_rf, antenna_gain_dbi)), 8);
    CHECK_EQ(static_cast<int>(offsetof(lsim_gateway_rf, cable_loss_db)), 16);

    CHECK_EQ(static_cast<int>(sizeof(lsim_closed_loop_v4_args)), 56);
    CHECK_EQ(static_cast<int>(offsetof(lsim_closed_loop_v4_args, v3)), 8);
    CHECK_EQ(static_cast<int>(offsetof(lsim_closed_loop_v4_args, device_rf)), 16);
    CHECK_EQ(static_cast<int>(offsetof(lsim_closed_loop_v4_args, device_rf_count)), 24);
    CHECK_EQ(static_cast<int>(offsetof(lsim_closed_loop_v4_args, gateway_rf)), 32);
    CHECK_EQ(static_cast<int>(offsetof(lsim_closed_loop_v4_args, reserved)), 40);
}

// ---------------------------------------------------------------- 1. Chaîne et validation

void test_frontend_chain_is_gain_minus_loss() {
    RadioFrontend rf;
    CHECK_TRUE(!rf.present());
    CHECK_NEAR(rf.chain_db(), 0.0, 1e-12);

    rf.has_antenna_gain = true;
    rf.antenna_gain_dbi = 3.0;
    CHECK_TRUE(rf.present());
    CHECK_NEAR(rf.chain_db(), 3.0, 1e-12);

    rf.has_cable_loss = true;
    rf.cable_loss_db = 1.5;
    CHECK_NEAR(rf.chain_db(), 1.5, 1e-12);
}

void test_frontend_validity_bounds() {
    RadioFrontend rf;
    CHECK_TRUE(lsim::sim::radio_frontend_valid(rf));

    rf.has_antenna_gain = true;
    rf.antenna_gain_dbi = lsim::sim::kMaxAntennaGainDbi;
    CHECK_TRUE(lsim::sim::radio_frontend_valid(rf));
    rf.antenna_gain_dbi = lsim::sim::kMaxAntennaGainDbi + 1.0;
    CHECK_TRUE(!lsim::sim::radio_frontend_valid(rf));
    rf.antenna_gain_dbi = -lsim::sim::kMaxAntennaGainDbi - 1.0;
    CHECK_TRUE(!lsim::sim::radio_frontend_valid(rf));
    rf.antenna_gain_dbi = std::nan("");
    CHECK_TRUE(!lsim::sim::radio_frontend_valid(rf));

    // Perte de câble : négative ou hors borne refusée ; le champ absent n'est pas lu.
    rf = RadioFrontend{};
    rf.has_cable_loss = true;
    rf.cable_loss_db = -0.5;
    CHECK_TRUE(!lsim::sim::radio_frontend_valid(rf));
    rf.cable_loss_db = lsim::sim::kMaxCableLossDb + 0.1;
    CHECK_TRUE(!lsim::sim::radio_frontend_valid(rf));
    rf.cable_loss_db = lsim::sim::kMaxCableLossDb;
    CHECK_TRUE(lsim::sim::radio_frontend_valid(rf));

    // Un champ absent n'est jamais lu : valeur aberrante ignorée.
    RadioFrontend absent;
    absent.antenna_gain_dbi = 1e9;  // has_antenna_gain reste faux
    CHECK_TRUE(lsim::sim::radio_frontend_valid(absent));
    CHECK_NEAR(absent.chain_db(), 0.0, 1e-12);
}

// ---------------------------------------------------------------- 2. Montée

void test_device_gain_raises_the_uplink_rssi_once() {
    const lsim_end_device d = device(1000.0, 14.0);
    const lsim_gateway g = gateway(0.0);
    const double neutral = rssi_of(d, g, nullptr, nullptr);

    lsim_device_rf rf{};
    rf.present = LSIM_RF_HAS_ANTENNA_GAIN;
    rf.antenna_gain_dbi = 3.0;
    CHECK_NEAR(rssi_of(d, g, &rf, nullptr) - neutral, 3.0, 1e-9);

    rf.antenna_gain_dbi = 6.0;
    CHECK_NEAR(rssi_of(d, g, &rf, nullptr) - neutral, 6.0, 1e-9);
}

void test_cable_loss_lowers_the_uplink_rssi_once() {
    const lsim_end_device d = device(1000.0, 14.0);
    const lsim_gateway g = gateway(0.0);
    const double neutral = rssi_of(d, g, nullptr, nullptr);

    lsim_device_rf rf{};
    rf.present = LSIM_RF_HAS_CABLE_LOSS;
    rf.cable_loss_db = 2.0;
    CHECK_NEAR(rssi_of(d, g, &rf, nullptr) - neutral, -2.0, 1e-9);
}

void test_antenna_gain_and_cable_loss_are_independent() {
    const lsim_end_device d = device(1000.0, 14.0);
    const lsim_gateway g = gateway(0.0);
    const double neutral = rssi_of(d, g, nullptr, nullptr);

    lsim_device_rf gain{};
    gain.present = LSIM_RF_HAS_ANTENNA_GAIN;
    gain.antenna_gain_dbi = 3.0;
    // Perte non présente : la valeur aberrante ne doit pas être lue.
    gain.cable_loss_db = 1e9;
    CHECK_NEAR(rssi_of(d, g, &gain, nullptr) - neutral, 3.0, 1e-9);

    lsim_device_rf loss{};
    loss.present = LSIM_RF_HAS_CABLE_LOSS;
    loss.cable_loss_db = 1.0;
    loss.antenna_gain_dbi = -1e9;  // gain non présent, ignoré
    CHECK_NEAR(rssi_of(d, g, &loss, nullptr) - neutral, -1.0, 1e-9);

    lsim_device_rf both{};
    both.present = LSIM_RF_HAS_ANTENNA_GAIN | LSIM_RF_HAS_CABLE_LOSS;
    both.antenna_gain_dbi = 3.0;
    both.cable_loss_db = 1.0;
    CHECK_NEAR(rssi_of(d, g, &both, nullptr) - neutral, 2.0, 1e-9);
}

void test_gateway_frontend_gain_replaces_the_scalar_and_loss_subtracts() {
    const lsim_end_device d = device(1000.0, 14.0);
    const double neutral = rssi_of(d, gateway(0.0), nullptr, nullptr);

    lsim_gateway_rf gain{};
    gain.present = LSIM_RF_HAS_ANTENNA_GAIN;
    gain.antenna_gain_dbi = 6.0;
    // Remplacement : le scalaire (0 dBi) n'est pas ajouté en plus.
    CHECK_NEAR(rssi_of(d, gateway(0.0), nullptr, &gain) - neutral, 6.0, 1e-9);
    // Et il remplace aussi une valeur scalaire non nulle.
    CHECK_NEAR(rssi_of(d, gateway(3.0), nullptr, &gain) - neutral, 6.0, 1e-9);

    lsim_gateway_rf loss{};
    loss.present = LSIM_RF_HAS_CABLE_LOSS;
    loss.cable_loss_db = 2.0;
    CHECK_NEAR(rssi_of(d, gateway(3.0), nullptr, &loss) - neutral, 1.0, 1e-9);
}

// ---------------------------------------------------------------- 3. Validation des tables

void test_rf_table_count_must_be_zero_or_complete() {
    std::vector<lsim_end_device> devices{device(100.0, 14.0), device(200.0, 14.0)};
    lsim_gateway g = gateway(0.0);
    lsim_propagation p = propagation();
    std::vector<lsim_device_stats> stats(2);
    lsim_sim_stats totals{};
    lsim_tx_record rec[2]{};
    size_t count = 0;
    lsim_device_rf rf[2]{};

    // 0 entrée : accepté (comportement historique).
    CHECK_EQ(static_cast<int>(lsim_simulate_uplinks_trace_v3(
                 devices.data(), 2, &g, &p, nullptr, stats.data(), &totals, rec, 2, &count,
                 nullptr, 0, nullptr, 0, nullptr, 0, nullptr)),
             0);

    // 1 entrée pour 2 dispositifs : refusé, aucune table partielle.
    CHECK_EQ(static_cast<int>(lsim_simulate_uplinks_trace_v3(
                 devices.data(), 2, &g, &p, nullptr, stats.data(), &totals, rec, 2, &count,
                 nullptr, 0, nullptr, 0, rf, 1, nullptr)),
             static_cast<int>(kInvalid));

    // 3 entrées pour 2 dispositifs : refusé aussi.
    lsim_device_rf three[3]{};
    CHECK_EQ(static_cast<int>(lsim_simulate_uplinks_trace_v3(
                 devices.data(), 2, &g, &p, nullptr, stats.data(), &totals, rec, 2, &count,
                 nullptr, 0, nullptr, 0, three, 3, nullptr)),
             static_cast<int>(kInvalid));

    // 2 entrées : accepté.
    CHECK_EQ(static_cast<int>(lsim_simulate_uplinks_trace_v3(
                 devices.data(), 2, &g, &p, nullptr, stats.data(), &totals, rec, 2, &count,
                 nullptr, 0, nullptr, 0, rf, 2, nullptr)),
             0);
}

void test_unknown_bits_and_out_of_range_values_are_rejected() {
    const lsim_end_device d = device(1000.0, 14.0);
    const lsim_gateway g = gateway(0.0);
    lsim_device_rf rf{};

    rf.present = 0x4u;  // bit inconnu
    CHECK_EQ(static_cast<int>(rssi_status(d, g, &rf)), static_cast<int>(kInvalid));

    rf.present = LSIM_RF_HAS_ANTENNA_GAIN;
    rf.antenna_gain_dbi = lsim::sim::kMaxAntennaGainDbi + 0.5;
    CHECK_EQ(static_cast<int>(rssi_status(d, g, &rf)), static_cast<int>(kInvalid));

    rf = lsim_device_rf{};
    rf.present = LSIM_RF_HAS_CABLE_LOSS;
    rf.cable_loss_db = -1.0;
    CHECK_EQ(static_cast<int>(rssi_status(d, g, &rf)), static_cast<int>(kInvalid));
}

// ---------------------------------------------------------------- 4. Downlinks : un seul comptage

// Résultat d'une descente pour un dispositif à 12 km, SF12, P_gw = 0 dBm.
uint8_t downlink_outcome(const lsim_downlink_rule& rule, const lsim_device_rf* rf) {
    lsim_end_device d = device(12000.0, 14.0, 12);
    d.messages = 3;
    lsim_gateway g = gateway(0.0);
    lsim_propagation p = propagation();
    lsim_device_stats stats{};
    lsim_network_stats totals{};
    lsim_gateway_rx_stats gstats{};
    lsim_multi_tx_record rec[3]{};
    size_t count = 0;
    lsim_downlink_record dls[3]{};
    size_t dl_count = 0;
    const int32_t st = lsim_simulate_uplinks_multi_dl_v2(
        &d, 1, &g, 1, &p, &rule, nullptr, &stats, &totals, &gstats, rec, 3, &count, dls, 3,
        &dl_count, nullptr, 0, rf, rf == nullptr ? 0 : 1, nullptr, 0);
    CHECK_EQ(static_cast<int>(st), 0);
    if (dl_count == 0) {
        CHECK_TRUE(false);
        return 0xFF;
    }
    return dls[0].outcome;
}

void test_device_gain_is_counted_once_in_the_downlink() {
    // RSSI montant sans frontal, mesuré (12 km, SF12, 14 dBm, passerelle 0 dBi).
    const double rssi_up = rssi_of(device(12000.0, 14.0, 12), gateway(0.0), nullptr, nullptr);
    const double sens_sf12 = -136.0;
    const double chain = 10.0;
    // Descente correcte : rssi_up - P_tx + P_gw + chaîne.
    const double correct = rssi_up - 14.0 + 0.0 + chain;
    // Marge de -5 dB : perdue si le gain est compté une fois, reçue si compté deux fois (+10 dB).
    const double offset = correct - sens_sf12 + 5.0;

    lsim_downlink_rule rule{};
    rule.ack_uplinks = 1;
    rule.gateway_tx_power_dbm = 0.0;
    rule.device_rx_offset_db = offset;
    // Le scalaire de la règle est volontairement différent : il doit être ignoré quand une
    // table terminale est fournie (aucun cumul, aucun repli implicite).
    rule.device_antenna_gain_dbi = 30.0;

    lsim_device_rf rf{};
    rf.present = LSIM_RF_HAS_ANTENNA_GAIN;
    rf.antenna_gain_dbi = chain;
    // Perdue => la chaîne n'est comptée qu'une fois (une version doublée recevrait).
    CHECK_EQ(static_cast<int>(downlink_outcome(rule, &rf)), kDlLostSensitivity);

    // Le même cas sans offset de marge : reçue, et 10 dB de plus ne change pas l'issue.
    rule.device_rx_offset_db = 0.0;
    CHECK_EQ(static_cast<int>(downlink_outcome(rule, &rf)), kDlReceived);

    // Ancien contrat, sans table : le gain scalaire de la règle produit le même résultat.
    lsim_downlink_rule legacy = rule;
    legacy.device_rx_offset_db = offset;
    legacy.device_antenna_gain_dbi = chain;
    CHECK_EQ(static_cast<int>(downlink_outcome(legacy, nullptr)), kDlLostSensitivity);
}

// ---------------------------------------------------------------- 5. Boucle fermée v4

void test_closed_loop_v4_validates_its_arguments() {
    CHECK_EQ(static_cast<int>(lsim_simulate_closed_loop_v4(nullptr)),
             static_cast<int>(lsim::lora::Status::NullOutput));

    lsim_closed_loop_v4_args args{};
    args.struct_size = sizeof(lsim_closed_loop_v4_args);
    args.abi_version = LSIM_CLOSED_LOOP_V4_ABI_VERSION;
    args.v3 = nullptr;  // requis
    CHECK_EQ(static_cast<int>(lsim_simulate_closed_loop_v4(&args)), static_cast<int>(kInvalid));

    args.struct_size = sizeof(lsim_closed_loop_v4_args) - 8;
    CHECK_EQ(static_cast<int>(lsim_simulate_closed_loop_v4(&args)), static_cast<int>(kInvalid));

    args.struct_size = sizeof(lsim_closed_loop_v4_args);
    args.abi_version = 3;
    CHECK_EQ(static_cast<int>(lsim_simulate_closed_loop_v4(&args)), static_cast<int>(kInvalid));

    // Table annoncée sans pointeur : refusée même avant la validation v3.
    args.abi_version = LSIM_CLOSED_LOOP_V4_ABI_VERSION;
    args.device_rf_count = 1;
    args.device_rf = nullptr;
    CHECK_EQ(static_cast<int>(lsim_simulate_closed_loop_v4(&args)), static_cast<int>(kInvalid));
}

}  // namespace

void run_rf_frontend_tests() {
    test_rf_structs_have_a_fixed_layout();
    test_frontend_chain_is_gain_minus_loss();
    test_frontend_validity_bounds();
    test_device_gain_raises_the_uplink_rssi_once();
    test_cable_loss_lowers_the_uplink_rssi_once();
    test_antenna_gain_and_cable_loss_are_independent();
    test_gateway_frontend_gain_replaces_the_scalar_and_loss_subtracts();
    test_rf_table_count_must_be_zero_or_complete();
    test_unknown_bits_and_out_of_range_values_are_rejected();
    test_device_gain_is_counted_once_in_the_downlink();
    test_closed_loop_v4_validates_its_arguments();
}
