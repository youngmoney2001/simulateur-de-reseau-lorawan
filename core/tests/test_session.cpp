// SPDX-License-Identifier: Apache-2.0
// Moteur de session dispositif : cycle uplink, compteurs, anti-rejeu, ADR_ACK, rekey -> NeedsJoin.
#include <cstdint>

#include "check.hpp"
#include "lsim/session.hpp"

using namespace lsim::lorawan;
using namespace lsim::lorawan::session;

namespace {

SessionKeys11 sample_keys() {
    SessionKeys11 k;
    k.f_nwk_s_int_key.fill(0x11);
    k.s_nwk_s_int_key.fill(0x22);
    k.nwk_s_enc_key.fill(0x33);
    k.app_s_key.fill(0x44);
    return k;
}

InitParams sample_init() {
    InitParams p;
    p.dev_addr = 0x26011234;
    p.dr = 2;
    p.min_dr = 0;
    p.tx_power_index = 1;
    p.default_tx_power_index = 1;
    return p;
}

// Un cycle complet sans trame descendante.
SessionStatus uplink_cycle(Session& s, std::uint8_t limit_exp, std::uint8_t delay_exp,
                           UplinkPlan& plan, UplinkEnd& end) {
    const auto b = s.begin_uplink(limit_exp, delay_exp, plan);
    if (b != SessionStatus::Ok) return b;
    return s.end_uplink(end);
}

}  // namespace

void run_session_tests() {
    // --- Sans join : aucun uplink possible.
    {
        Session s;
        UplinkPlan plan;
        CHECK_EQ(static_cast<int>(s.begin_uplink(3, 3, plan)), static_cast<int>(SessionStatus::NoSession));
        CHECK_TRUE(s.state() == SessionState::NoSession);
        // Paramètres de join invalides : rien n'est modifié.
        InitParams bad = sample_init();
        bad.min_dr = 5;  // > dr
        CHECK_EQ(static_cast<int>(s.join_accepted(sample_keys(), bad)),
                 static_cast<int>(SessionStatus::InvalidParameter));
        CHECK_TRUE(s.state() == SessionState::NoSession);
    }
    // --- Join, premier cycle avec RekeyConf et trame descendante.
    {
        Session s;
        CHECK_EQ(static_cast<int>(s.join_accepted(sample_keys(), sample_init())),
                 static_cast<int>(SessionStatus::Ok));
        CHECK_TRUE(s.state() == SessionState::Active);
        const Snapshot s0 = s.snapshot();
        CHECK_EQ(static_cast<int>(s0.fcnt_up), 0);
        CHECK_EQ(static_cast<int>(s0.dev_addr), 0x26011234);

        UplinkPlan plan;
        UplinkEnd end;
        // Paramètre hors plage : rien n'est consommé, aucun cycle ouvert.
        CHECK_EQ(static_cast<int>(s.begin_uplink(16, 0, plan)), static_cast<int>(SessionStatus::InvalidParameter));
        CHECK_TRUE(!s.snapshot().cycle_open);
        CHECK_EQ(static_cast<int>(s.begin_uplink(3, 3, plan)), static_cast<int>(SessionStatus::Ok));
        CHECK_EQ(static_cast<int>(plan.fcnt32), 0);
        CHECK_TRUE(plan.rekey_ind);
        // Cycle déjà ouvert.
        CHECK_EQ(static_cast<int>(s.begin_uplink(3, 3, plan)), static_cast<int>(SessionStatus::CycleError));
        CHECK_TRUE(s.snapshot().cycle_open);
        CHECK_EQ(static_cast<int>(s.snapshot().fcnt_up), 0);

        DownlinkInfo conf;
        conf.uses_nf = true;
        conf.fcnt32 = 0;
        conf.conf_received = true;
        conf.server_version = 1;
        CHECK_EQ(static_cast<int>(s.receive_downlink(conf)), static_cast<int>(SessionStatus::Ok));
        CHECK_EQ(static_cast<int>(s.end_uplink(end)), static_cast<int>(SessionStatus::Ok));
        CHECK_EQ(static_cast<int>(s.snapshot().fcnt_up), 1);
        CHECK_EQ(static_cast<int>(s.snapshot().nf_cnt_dwn), 1);
        CHECK_TRUE(s.state() == SessionState::Active);
        CHECK_TRUE(!plan.ack_req);

        // Second cycle : plus de RekeyInd ; compteur descendant NF rejoué refusé.
        CHECK_EQ(static_cast<int>(s.begin_uplink(3, 3, plan)), static_cast<int>(SessionStatus::Ok));
        CHECK_EQ(static_cast<int>(plan.fcnt32), 1);
        CHECK_TRUE(!plan.rekey_ind);
        DownlinkInfo replay;
        replay.uses_nf = true;
        replay.fcnt32 = 0;
        CHECK_EQ(static_cast<int>(s.receive_downlink(replay)), static_cast<int>(SessionStatus::Replay));
        // AFCntDown est un compteur indépendant de NFCntDown.
        DownlinkInfo app;
        app.uses_nf = false;
        app.fcnt32 = 0;
        CHECK_EQ(static_cast<int>(s.receive_downlink(app)), static_cast<int>(SessionStatus::Ok));
        DownlinkInfo nf1;
        nf1.uses_nf = true;
        nf1.fcnt32 = 1;
        CHECK_EQ(static_cast<int>(s.receive_downlink(nf1)), static_cast<int>(SessionStatus::Ok));
        CHECK_EQ(static_cast<int>(s.end_uplink(end)), static_cast<int>(SessionStatus::Ok));
        CHECK_EQ(static_cast<int>(s.snapshot().nf_cnt_dwn), 2);
        CHECK_EQ(static_cast<int>(s.snapshot().af_cnt_dwn), 1);
        // Une trame descendante hors cycle n'est pas acceptée.
        CHECK_EQ(static_cast<int>(s.receive_downlink(nf1)), static_cast<int>(SessionStatus::CycleError));
    }
    // --- ADR_ACK : réception descendante réinitialise ADR_ACK_CNT.
    {
        Session s;
        s.join_accepted(sample_keys(), sample_init());
        DownlinkInfo conf;
        conf.fcnt32 = 0;
        conf.conf_received = true;
        conf.server_version = 1;
        UplinkPlan plan;
        UplinkEnd end;
        s.begin_uplink(3, 3, plan);
        s.receive_downlink(conf);
        s.end_uplink(end);
        CHECK_TRUE(s.state() == SessionState::Active);
        // ADRACKReq est décidé à la construction de la trame (begin_uplink).
        bool ack_seen = false;
        for (int i = 0; i < 20 && !ack_seen; ++i) {
            UplinkPlan pl;
            CHECK_EQ(static_cast<int>(uplink_cycle(s, 3, 3, pl, end)), static_cast<int>(SessionStatus::Ok));
            ack_seen = pl.ack_req;
        }
        CHECK_TRUE(ack_seen);
        // Trame portant ADRACKReq, puis trame descendante reçue dans ses fenêtres.
        UplinkPlan p2;
        s.begin_uplink(3, 3, p2);
        DownlinkInfo d;
        d.uses_nf = true;
        d.fcnt32 = 1;
        s.receive_downlink(d);
        s.end_uplink(end);
        CHECK_EQ(static_cast<int>(s.snapshot().ack_cnt), 0);
        // L'uplink suivant ne porte plus ADRACKReq.
        UplinkPlan p3;
        CHECK_EQ(static_cast<int>(uplink_cycle(s, 3, 3, p3, end)), static_cast<int>(SessionStatus::Ok));
        CHECK_TRUE(!p3.ack_req);
        CHECK_EQ(static_cast<int>(s.snapshot().ack_cnt), 1);
    }
    // --- Rekey : pas de RekeyConf dans la limite -> NeedsJoin, plus d'uplink ; rejoin rétablit.
    {
        Session s;
        s.join_accepted(sample_keys(), sample_init());
        UplinkEnd end;
        UplinkPlan pa, pb;
        CHECK_EQ(static_cast<int>(uplink_cycle(s, 1, 1, pa, end)), static_cast<int>(SessionStatus::Ok));
        CHECK_TRUE(s.state() == SessionState::Active);
        CHECK_EQ(static_cast<int>(uplink_cycle(s, 1, 1, pb, end)), static_cast<int>(SessionStatus::Ok));
        CHECK_TRUE(end.state == SessionState::NeedsJoin);
        CHECK_TRUE(s.state() == SessionState::NeedsJoin);
        UplinkPlan plan;
        CHECK_EQ(static_cast<int>(s.begin_uplink(3, 3, plan)), static_cast<int>(SessionStatus::NoSession));

        // Nouveau join : compteurs remis à zéro, session active.
        CHECK_EQ(static_cast<int>(s.join_accepted(sample_keys(), sample_init())),
                 static_cast<int>(SessionStatus::Ok));
        const Snapshot r = s.snapshot();
        CHECK_TRUE(r.state == SessionState::Active);
        CHECK_EQ(static_cast<int>(r.fcnt_up), 0);
        CHECK_EQ(static_cast<int>(r.nf_cnt_dwn), 0);
        CHECK_EQ(static_cast<int>(r.af_cnt_dwn), 0);
        CHECK_TRUE(!r.cycle_open);
    }
    // --- Limite de compteur : 2^32 uplinks atteints -> CounterExhausted (chemin hors bornes).
    // Non testé ici : le compteur 32 bits ne peut pas être amorcé sans passer 2^32 cycles.
}
