// SPDX-License-Identifier: Apache-2.0
// ADR serveur : seuils SX1276, montée de débit, réduction/augmentation de puissance, entrées invalides.
#include <cstdint>

#include "check.hpp"
#include "lsim/adr.hpp"
#include "lsim/c_api.h"
#include "lsim/lora_phy.hpp"

namespace {

using namespace lsim::lorawan::adr;

// Plan type EU868 : DR0..DR5 = SF12..SF7 ; DR6..15 indisponibles ici.
Input base_input(std::int32_t snr_tenth) {
    Input in;
    for (std::size_t i = 0; i < kMaxSamples; ++i) in.snr_tenth_db[i] = snr_tenth;
    in.n_samples = kMaxSamples;
    in.dr = 0;
    in.dr_sf = {12, 11, 10, 9, 8, 7, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0};
    in.min_dr = 0;
    in.max_dr = 5;
    in.tx_power_index = 0;
    in.max_tx_power_index = 7;
    in.power_step_tenth_db = 20;
    in.installation_margin_tenth_db = 100;
    return in;
}

}  // namespace

void run_adr_tests() {
    // --- Seuils SX1276 (dixièmes de dB) : SF7 -7,5 ... SF12 -20.
    {
        std::int32_t v = 0;
        CHECK_TRUE(required_snr_tenth_db(7, v));
        CHECK_EQ(v, -75);
        CHECK_TRUE(required_snr_tenth_db(12, v));
        CHECK_EQ(v, -200);
        CHECK_TRUE(!required_snr_tenth_db(13, v));
        CHECK_TRUE(!required_snr_tenth_db(6, v));
    }
    // --- Forte liaison : SNR max 10 dB. Débit 0 -> 5 (marge 75 à SF7), puis puissance 0 -> 3
    // (reliquat 75 : 3 pas de 20 ; le quatrième ramènerait la marge à -5).
    {
        Input in = base_input(100);
        Output o;
        CHECK_EQ(static_cast<int>(decide(in, o)), static_cast<int>(AdrStatus::Ok));
        CHECK_EQ(o.dr, std::uint8_t{5});
        CHECK_EQ(o.tx_power_index, std::uint8_t{3});
    }
    // --- Le SNR max de l'historique est utilisé (pas la moyenne ni le dernier).
    {
        Input in = base_input(-200);
        in.snr_tenth_db[7] = 100;
        Output o;
        CHECK_EQ(static_cast<int>(decide(in, o)), static_cast<int>(AdrStatus::Ok));
        CHECK_EQ(o.dr, std::uint8_t{5});
        CHECK_EQ(o.tx_power_index, std::uint8_t{3});
    }
    // --- Marge négative au débit courant (-10 dB ... -1 dB après marge) : puissance augmentée.
    // SNR -11 dB, SF12 : M = -110 + 200 - 100 = -10 ; index 3 -> 2 (M = 10).
    {
        Input in = base_input(-110);
        in.tx_power_index = 3;
        Output o;
        CHECK_EQ(static_cast<int>(decide(in, o)), static_cast<int>(AdrStatus::Ok));
        CHECK_EQ(o.dr, std::uint8_t{0});
        CHECK_EQ(o.tx_power_index, std::uint8_t{2});
    }
    // --- Liaison désespérée : marge -100 et puissance déjà maximale -> inchangé.
    {
        Input in = base_input(-200);
        Output o;
        CHECK_EQ(static_cast<int>(decide(in, o)), static_cast<int>(AdrStatus::Ok));
        CHECK_EQ(o.dr, std::uint8_t{0});
        CHECK_EQ(o.tx_power_index, std::uint8_t{0});
    }
    // --- Puissance déjà au plafond de la région : pas de dépassement.
    {
        Input in = base_input(100);
        in.tx_power_index = 7;
        in.max_tx_power_index = 7;
        Output o;
        CHECK_EQ(static_cast<int>(decide(in, o)), static_cast<int>(AdrStatus::Ok));
        CHECK_EQ(o.dr, std::uint8_t{5});
        CHECK_EQ(o.tx_power_index, std::uint8_t{7});
    }
    // --- Débit plafonné par max_dr : pas de montée au-delà.
    {
        Input in = base_input(100);
        in.max_dr = 2;
        Output o;
        CHECK_EQ(static_cast<int>(decide(in, o)), static_cast<int>(AdrStatus::Ok));
        CHECK_EQ(o.dr, std::uint8_t{2});
    }
    // --- Entrées invalides : rien n'est modifié en sortie (retour à l'état courant).
    {
        Output o{9, 9};
        Input in = base_input(100);
        in.n_samples = 0;
        CHECK_EQ(static_cast<int>(decide(in, o)), static_cast<int>(AdrStatus::InvalidParameter));
        CHECK_EQ(o.dr, std::uint8_t{0});
        CHECK_EQ(o.tx_power_index, std::uint8_t{0});
        in = base_input(100);
        in.n_samples = 21;
        CHECK_EQ(static_cast<int>(decide(in, o)), static_cast<int>(AdrStatus::InvalidParameter));
        in = base_input(100);
        in.dr = 6;  // hors plage min..max ou SF absent
        CHECK_EQ(static_cast<int>(decide(in, o)), static_cast<int>(AdrStatus::InvalidParameter));
        in = base_input(100);
        in.dr_sf[2] = 13;  // SF hors plage
        CHECK_EQ(static_cast<int>(decide(in, o)), static_cast<int>(AdrStatus::InvalidParameter));
        in = base_input(100);
        in.power_step_tenth_db = 0;
        CHECK_EQ(static_cast<int>(decide(in, o)), static_cast<int>(AdrStatus::InvalidParameter));
        in = base_input(100);
        in.snr_tenth_db[3] = 501;
        CHECK_EQ(static_cast<int>(decide(in, o)), static_cast<int>(AdrStatus::InvalidParameter));
        in = base_input(100);
        in.tx_power_index = 8;  // > max_tx_power_index
        CHECK_EQ(static_cast<int>(decide(in, o)), static_cast<int>(AdrStatus::InvalidParameter));
        CHECK_EQ(o.dr, std::uint8_t{0});
    }
    // --- ADR_ACK dispositif. LIMIT = DELAY = 32 (exp 5). Départ : DR2, puissance 2 (< défaut 0),
    // masque restreint, débit minimal 0.
    {
        DeviceAdrState st;
        st.dr = 2;
        st.min_dr = 0;
        st.tx_power_index = 2;
        st.default_tx_power_index = 0;
        st.channels_subset = true;
        UplinkOutcome o;
        for (int i = 1; i <= 31; ++i) {
            CHECK_EQ(static_cast<int>(device_on_uplink(st, 5, 5, o)), static_cast<int>(AdrStatus::Ok));
            CHECK_TRUE(!o.ack_req);
        }
        // cnt 32 : ADRACKReq (débit, puissance et masque non nominaux), pas encore de repli.
        CHECK_EQ(static_cast<int>(device_on_uplink(st, 5, 5, o)), static_cast<int>(AdrStatus::Ok));
        CHECK_TRUE(o.ack_req);
        CHECK_EQ(st.tx_power_index, std::uint8_t{2});
        // cnt 63 : pas de repli (pas un multiple de DELAY après LIMIT + DELAY).
        for (int i = 33; i <= 63; ++i) device_on_uplink(st, 5, 5, o);
        CHECK_EQ(st.tx_power_index, std::uint8_t{2});
        // cnt 64 = LIMIT + DELAY : puissance remontée au défaut.
        device_on_uplink(st, 5, 5, o);
        CHECK_EQ(st.tx_power_index, std::uint8_t{0});
        CHECK_EQ(st.dr, std::uint8_t{2});
        CHECK_TRUE(o.ack_req);
        // cnt 96 : débit d'un cran plus bas.
        for (int i = 65; i <= 96; ++i) device_on_uplink(st, 5, 5, o);
        CHECK_EQ(st.dr, std::uint8_t{1});
        // cnt 128 : débit minimal atteint ; canaux par défaut réactivés ; ADRACKReq à 0.
        for (int i = 97; i <= 128; ++i) device_on_uplink(st, 5, 5, o);
        CHECK_EQ(st.dr, std::uint8_t{0});
        CHECK_TRUE(o.default_channels_reenabled);
        CHECK_TRUE(!st.channels_subset);
        CHECK_TRUE(!o.ack_req);
        // Une trame descendante remet ADR_ACK_CNT à zéro.
        device_on_downlink(st);
        CHECK_EQ(static_cast<int>(st.ack_cnt), 0);
        device_on_uplink(st, 5, 5, o);
        CHECK_TRUE(!o.ack_req);
        // Entrées invalides : état intact.
        const auto before = st;
        CHECK_EQ(static_cast<int>(device_on_uplink(st, 16, 5, o)), static_cast<int>(AdrStatus::InvalidParameter));
        CHECK_EQ(st.ack_cnt, before.ack_cnt);
        DeviceAdrState bad;
        bad.dr = 0;
        bad.min_dr = 1;
        CHECK_EQ(static_cast<int>(device_on_uplink(bad, 5, 5, o)), static_cast<int>(AdrStatus::InvalidParameter));
    }
    // --- ADR_ACK via l'API C.
    {
        lsim_adr_device_state cs{};
        cs.dr = 2;
        cs.tx_power_index = 2;
        cs.channels_subset = 1;
        lsim_adr_uplink_outcome co{};
        for (int i = 0; i < 32; ++i) CHECK_EQ(lsim_adr_device_uplink(&cs, 5, 5, &co), 0);
        CHECK_EQ(static_cast<int>(co.ack_req), 1);
        CHECK_EQ(lsim_adr_device_uplink(&cs, 16, 5, &co), LSIM_STATUS_ADR_BASE + 1);
        CHECK_EQ(lsim_adr_device_downlink(&cs), 0);
        CHECK_EQ(static_cast<int>(cs.ack_cnt), 0);
        CHECK_EQ(lsim_adr_device_downlink(nullptr), static_cast<int>(lsim::lora::Status::NullOutput));
    }
    // --- Frontière C : NULL et code 761.
    {
        lsim_adr_input cin{};
        for (int i = 0; i < 20; ++i) cin.snr_tenth_db[i] = 100;
        cin.n_samples = 20;
        cin.dr_sf[0] = 12;
        cin.dr_sf[1] = 11;
        cin.dr_sf[2] = 10;
        cin.dr_sf[3] = 9;
        cin.dr_sf[4] = 8;
        cin.dr_sf[5] = 7;
        cin.max_dr = 5;
        cin.max_tx_power_index = 7;
        cin.power_step_tenth_db = 20;
        cin.installation_margin_tenth_db = 100;
        lsim_adr_output cout{};
        CHECK_EQ(lsim_adr_decide(&cin, &cout), 0);
        CHECK_EQ(static_cast<int>(cout.dr), 5);
        CHECK_EQ(static_cast<int>(cout.tx_power_index), 3);
        CHECK_EQ(lsim_adr_decide(nullptr, &cout), static_cast<int>(lsim::lora::Status::NullOutput));
        cin.n_samples = 0;
        CHECK_EQ(lsim_adr_decide(&cin, &cout), LSIM_STATUS_ADR_BASE + 1);
    }
}
