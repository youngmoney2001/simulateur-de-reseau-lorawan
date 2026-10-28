// SPDX-License-Identifier: Apache-2.0
// Codec des commandes MAC LoRaWAN 1.1 : octets attendus, bornes et bits RFU.
#include <array>
#include <cstdint>

#include "check.hpp"
#include "lsim/c_api.h"
#include "lsim/mac_commands.hpp"

namespace {

using namespace lsim::lorawan;
using namespace lsim::lorawan::mac;
using Buf = std::array<std::uint8_t, kMaxCommandBytes>;

}  // namespace

void run_mac_commands_tests() {
    // --- LinkADRReq (down) : DR=5, TXPower=2, ChMask=0x00FF, ChMaskCntl=0, NbTrans=1.
    {
        Buf out{};
        std::size_t len = 0;
        LinkAdrReq req;
        req.data_rate = 5;
        req.tx_power = 2;
        req.ch_mask = 0x00FF;
        req.ch_mask_cntl = 0;
        req.nb_trans = 1;
        CHECK_EQ(static_cast<int>(encode(req, out, len)), static_cast<int>(MacStatus::Ok));
        CHECK_EQ(len, std::size_t{5});
        const std::uint8_t expected[5] = {0x03, 0x52, 0xFF, 0x00, 0x01};
        for (std::size_t i = 0; i < 5; ++i) CHECK_EQ(out[i], expected[i]);

        LinkAdrReq back;
        CHECK_EQ(static_cast<int>(decode(out.data(), len, back)), static_cast<int>(MacStatus::Ok));
        CHECK_EQ(back.data_rate, std::uint8_t{5});
        CHECK_EQ(back.tx_power, std::uint8_t{2});
        CHECK_EQ(back.ch_mask, std::uint16_t{0x00FF});
        CHECK_EQ(back.ch_mask_cntl, std::uint8_t{0});
        CHECK_EQ(back.nb_trans, std::uint8_t{1});
    }
    // Bits RFU de Redundancy (bit 7) et bornes de champs.
    {
        const std::uint8_t rfu[5] = {0x03, 0x52, 0xFF, 0x00, 0x81};
        LinkAdrReq r;
        CHECK_EQ(static_cast<int>(decode(rfu, 5, r)), static_cast<int>(MacStatus::MalformedPayload));
        Buf out{};
        std::size_t len = 0;
        LinkAdrReq bad;
        bad.data_rate = 16;
        CHECK_EQ(static_cast<int>(encode(bad, out, len)), static_cast<int>(MacStatus::FieldOutOfRange));
        bad = LinkAdrReq{};
        bad.ch_mask_cntl = 8;
        CHECK_EQ(static_cast<int>(encode(bad, out, len)), static_cast<int>(MacStatus::FieldOutOfRange));
        bad = LinkAdrReq{};
        bad.nb_trans = 16;
        CHECK_EQ(static_cast<int>(encode(bad, out, len)), static_cast<int>(MacStatus::FieldOutOfRange));
    }
    // --- LinkADRAns (up) : bits 0..2 et RFU bits 7:3.
    {
        Buf out{};
        std::size_t len = 0;
        LinkAdrAns ans;
        ans.data_rate_ack = true;
        ans.power_ack = true;
        CHECK_EQ(static_cast<int>(encode(ans, out, len)), static_cast<int>(MacStatus::Ok));
        CHECK_EQ(len, std::size_t{2});
        CHECK_EQ(out[1], std::uint8_t{0x06});
        LinkAdrAns back;
        const std::uint8_t bad[2] = {0x03, 0x08};
        CHECK_EQ(static_cast<int>(decode(bad, 2, back)), static_cast<int>(MacStatus::MalformedPayload));
        const std::uint8_t good[2] = {0x03, 0x07};
        CHECK_EQ(static_cast<int>(decode(good, 2, back)), static_cast<int>(MacStatus::Ok));
        CHECK_TRUE(back.channel_mask_ack && back.data_rate_ack && back.power_ack);
    }
    // --- DutyCycleReq (down) : MaxDCycle sur 4 bits ; RFU bits 7:4.
    {
        const std::uint8_t ok[2] = {0x04, 0x03};
        DutyCycleReq d;
        CHECK_EQ(static_cast<int>(decode(ok, 2, d)), static_cast<int>(MacStatus::Ok));
        CHECK_EQ(d.max_dcycle, std::uint8_t{3});
        const std::uint8_t rfu[2] = {0x04, 0x13};
        CHECK_EQ(static_cast<int>(decode(rfu, 2, d)), static_cast<int>(MacStatus::MalformedPayload));
        Buf out{};
        std::size_t len = 0;
        DutyCycleReq big;
        big.max_dcycle = 16;
        CHECK_EQ(static_cast<int>(encode(big, out, len)), static_cast<int>(MacStatus::FieldOutOfRange));
    }
    // --- DevStatusAns (up) : marge signée sur 6 bits, aller-retour sur les bornes.
    {
        Buf out{};
        std::size_t len = 0;
        DevStatusAns s;
        s.battery = 254;
        s.margin = -32;
        CHECK_EQ(static_cast<int>(encode(s, out, len)), static_cast<int>(MacStatus::Ok));
        CHECK_EQ(out[2], std::uint8_t{0x20});
        DevStatusAns back;
        CHECK_EQ(static_cast<int>(decode(out.data(), len, back)), static_cast<int>(MacStatus::Ok));
        CHECK_EQ(back.margin, std::int8_t{-32});
        CHECK_EQ(back.battery, std::uint8_t{254});

        s.margin = 31;
        CHECK_EQ(static_cast<int>(encode(s, out, len)), static_cast<int>(MacStatus::Ok));
        CHECK_EQ(out[2], std::uint8_t{0x1F});
        CHECK_EQ(static_cast<int>(decode(out.data(), len, back)), static_cast<int>(MacStatus::Ok));
        CHECK_EQ(back.margin, std::int8_t{31});

        s.margin = 32;
        CHECK_EQ(static_cast<int>(encode(s, out, len)), static_cast<int>(MacStatus::FieldOutOfRange));
        const std::uint8_t rfu[3] = {0x06, 0x00, 0x40};
        CHECK_EQ(static_cast<int>(decode(rfu, 3, back)), static_cast<int>(MacStatus::MalformedPayload));
    }
    // --- LinkCheckAns (down) : 255 réservé.
    {
        const std::uint8_t ok[3] = {0x02, 0x7F, 0x02};
        LinkCheckAns c;
        CHECK_EQ(static_cast<int>(decode(ok, 3, c)), static_cast<int>(MacStatus::Ok));
        CHECK_EQ(c.margin, std::uint8_t{127});
        CHECK_EQ(c.gw_cnt, std::uint8_t{2});
        const std::uint8_t reserved[3] = {0x02, 0xFF, 0x01};
        CHECK_EQ(static_cast<int>(decode(reserved, 3, c)), static_cast<int>(MacStatus::FieldOutOfRange));
    }
    // --- Rekey (RekeyInd up / RekeyConf down) : seule la version 1.1 est acceptée.
    {
        Buf out{};
        std::size_t len = 0;
        Rekey r;
        CHECK_EQ(static_cast<int>(encode(r, Direction::Uplink, out, len)), static_cast<int>(MacStatus::Ok));
        CHECK_EQ(out[0], std::uint8_t{0x0B});
        CHECK_EQ(out[1], std::uint8_t{0x01});
        const std::uint8_t v10[2] = {0x0B, 0x00};
        CHECK_EQ(static_cast<int>(decode(v10, 2, r, Direction::Downlink)),
                 static_cast<int>(MacStatus::FieldOutOfRange));
        const std::uint8_t rfu[2] = {0x0B, 0x11};
        CHECK_EQ(static_cast<int>(decode(rfu, 2, r, Direction::Downlink)),
                 static_cast<int>(MacStatus::MalformedPayload));
    }
    // --- Commandes sans charge utile : LinkCheckReq, DutyCycleAns, DevStatusReq.
    {
        Buf out{};
        std::size_t len = 0;
        CHECK_EQ(static_cast<int>(encode_empty(Cid::LinkCheck, Direction::Uplink, out, len)),
                 static_cast<int>(MacStatus::Ok));
        CHECK_EQ(len, std::size_t{1});
        CHECK_EQ(out[0], std::uint8_t{0x02});
        // LinkCheck en downlink a une charge utile : pas une commande vide.
        CHECK_EQ(static_cast<int>(encode_empty(Cid::LinkCheck, Direction::Downlink, out, len)),
                 static_cast<int>(MacStatus::UnknownCommand));
    }
    // --- Tailles lues dans un flux de commandes (FOpts concaténés).
    {
        // Uplink : LinkCheckReq (1) + DevStatusAns (3).
        const std::uint8_t up[4] = {0x02, 0x06, 0x80, 0x10};
        std::size_t size = 0;
        CHECK_EQ(static_cast<int>(command_size(Direction::Uplink, up, 4, size)), static_cast<int>(MacStatus::Ok));
        CHECK_EQ(size, std::size_t{1});
        CHECK_EQ(static_cast<int>(command_size(Direction::Uplink, up + 1, 3, size)),
                 static_cast<int>(MacStatus::Ok));
        CHECK_EQ(size, std::size_t{3});
        // Tronquée : LinkADRReq (downlink) n'a que 3 octets sur 5.
        const std::uint8_t trunc[3] = {0x03, 0x52, 0xFF};
        CHECK_EQ(static_cast<int>(command_size(Direction::Downlink, trunc, 3, size)),
                 static_cast<int>(MacStatus::MalformedPayload));
        // CID non implémenté (RXParamSetup 0x05) : refusé.
        const std::uint8_t unknown[2] = {0x10, 0x00};  // PingSlotInfoReq : non implémenté
        CHECK_EQ(static_cast<int>(command_size(Direction::Downlink, unknown, 2, size)),
                 static_cast<int>(MacStatus::UnknownCommand));
        CHECK_EQ(static_cast<int>(command_size(Direction::Uplink, up, 0, size)),
                 static_cast<int>(MacStatus::MalformedPayload));
    }
    // --- Ajout dans FOpts : capacité 15 octets, aucun dépassement.
    {
        std::array<std::uint8_t, kMaxFOpts> fopts{};
        std::uint8_t fopts_len = 0;
        Buf cmd{};
        std::size_t len = 0;
        // 3 × DevStatusAns = 9 octets, puis 2 × LinkADRAns = 4 octets : 13 au total.
        DevStatusAns s;
        for (int i = 0; i < 3; ++i) {
            CHECK_EQ(static_cast<int>(encode(s, cmd, len)), static_cast<int>(MacStatus::Ok));
            CHECK_EQ(static_cast<int>(append_to_fopts(fopts, fopts_len, cmd, len)), static_cast<int>(MacStatus::Ok));
        }
        LinkAdrAns a;
        for (int i = 0; i < 2; ++i) {
            CHECK_EQ(static_cast<int>(encode(a, cmd, len)), static_cast<int>(MacStatus::Ok));
            CHECK_EQ(static_cast<int>(append_to_fopts(fopts, fopts_len, cmd, len)), static_cast<int>(MacStatus::Ok));
        }
        CHECK_EQ(fopts_len, std::uint8_t{13});
        // +3 octets : 16 > 15, refusé et longueur inchangée.
        CHECK_EQ(static_cast<int>(encode(s, cmd, len)), static_cast<int>(MacStatus::Ok));
        CHECK_EQ(static_cast<int>(append_to_fopts(fopts, fopts_len, cmd, len)),
                 static_cast<int>(MacStatus::BufferTooSmall));
        CHECK_EQ(fopts_len, std::uint8_t{13});
    }

    // --- Surface C : mêmes octets, statuts 600+, FOpts borné.
    {
        lsim_mac_command c{};
        c.kind = LSIM_MAC_LINK_ADR_REQ;
        c.data_rate = 5;
        c.tx_power = 2;
        c.ch_mask = 0x00FF;
        c.nb_trans = 1;
        std::uint8_t out[LSIM_MAC_MAX_COMMAND_BYTES] = {};
        std::size_t n = 0;
        CHECK_EQ(lsim_mac_encode(&c, out, &n), 0);
        CHECK_EQ(n, std::size_t{5});
        CHECK_EQ(out[1], std::uint8_t{0x52});

        lsim_mac_command back{};
        std::size_t used = 0;
        CHECK_EQ(lsim_mac_decode(out, n, LSIM_MAC_DOWNLINK, &back, &used), 0);
        CHECK_EQ(back.kind, std::uint8_t{LSIM_MAC_LINK_ADR_REQ});
        CHECK_EQ(back.ch_mask, std::uint16_t{0x00FF});
        CHECK_EQ(used, std::size_t{5});

        // Même octet 0x02 : sens différent, charge différente.
        const std::uint8_t lc_down[3] = {0x02, 0x10, 0x01};
        CHECK_EQ(lsim_mac_decode(lc_down, 3, LSIM_MAC_DOWNLINK, &back, &used), 0);
        CHECK_EQ(back.kind, std::uint8_t{LSIM_MAC_LINK_CHECK_ANS});
        CHECK_EQ(back.margin, std::uint8_t{0x10});
        CHECK_EQ(lsim_mac_decode(lc_down, 1, LSIM_MAC_DOWNLINK, &back, &used),
                 LSIM_STATUS_MAC_BASE + static_cast<int>(MacStatus::MalformedPayload));
        CHECK_EQ(back.kind, std::uint8_t{0});

        // CID non implémenté (PingSlotInfoReq 0x10).
        const std::uint8_t rx[6] = {0x10, 0, 0, 0, 0, 0};  // PingSlotInfoReq : non implémenté
        CHECK_EQ(lsim_mac_decode(rx, 6, LSIM_MAC_DOWNLINK, &back, &used),
                 LSIM_STATUS_MAC_BASE + static_cast<int>(MacStatus::UnknownCommand));

        // Type inconnu à l'encodage.
        lsim_mac_command bogus{};
        bogus.kind = 99;
        CHECK_EQ(lsim_mac_encode(&bogus, out, &n),
                 LSIM_STATUS_MAC_BASE + static_cast<int>(MacStatus::UnknownCommand));
        CHECK_EQ(n, std::size_t{0});

        // Pointeurs nuls : statut NullOutput, pas de plantage.
        CHECK_EQ(lsim_mac_encode(nullptr, out, &n), static_cast<int>(lsim::lora::Status::NullOutput));

        // FOpts : 14 octets + une commande de 2 : refus sans modification.
        std::uint8_t fopts[kMaxFOpts] = {};
        std::uint8_t flen = 14;
        const std::uint8_t ack[2] = {0x03, 0x07};
        CHECK_EQ(lsim_mac_append_fopts(fopts, &flen, ack, 2),
                 LSIM_STATUS_MAC_BASE + static_cast<int>(MacStatus::BufferTooSmall));
        CHECK_EQ(flen, std::uint8_t{14});
        CHECK_EQ(lsim_mac_append_fopts(fopts, &flen, ack, 1) , 0);
        CHECK_EQ(flen, std::uint8_t{15});
        CHECK_EQ(fopts[14], std::uint8_t{0x03});
    }

    // --- RXParamSetupReq (down) : DLsettings + fréquence 24 bits LE (869,525 MHz = 8 695 250).
    {
        Buf out{};
        std::size_t len = 0;
        RxParamSetupReq r;
        r.rx2_data_rate = 3;
        r.rx1_dr_offset = 2;
        r.freq_100hz = 8'695'250;
        CHECK_EQ(static_cast<int>(encode(r, out, len)), static_cast<int>(MacStatus::Ok));
        CHECK_EQ(len, std::size_t{5});
        // DLsettings = 0x23 ; 8695250 = 0x84ADD2 -> LE D2 AD 84
        CHECK_EQ(out[1], std::uint8_t{0x23});
        CHECK_EQ(out[2], std::uint8_t{0xD2});
        CHECK_EQ(out[3], std::uint8_t{0xAD});
        CHECK_EQ(out[4], std::uint8_t{0x84});
        RxParamSetupReq back;
        CHECK_EQ(static_cast<int>(decode(out.data(), len, back)), static_cast<int>(MacStatus::Ok));
        CHECK_EQ(back.rx2_data_rate, std::uint8_t{3});
        CHECK_EQ(back.rx1_dr_offset, std::uint8_t{2});
        CHECK_EQ(back.freq_100hz, std::uint32_t{8'695'250});
        // Bit 7 de DLsettings RFU.
        const std::uint8_t rfu[5] = {0x05, 0x80, 0xD2, 0xAD, 0x84};
        CHECK_EQ(static_cast<int>(decode(rfu, 5, back)), static_cast<int>(MacStatus::MalformedPayload));
        // Offset RX1 sur 3 bits : 8 interdit.
        r.rx1_dr_offset = 8;
        CHECK_EQ(static_cast<int>(encode(r, out, len)), static_cast<int>(MacStatus::FieldOutOfRange));
        // Fréquence sous 100 MHz réservée.
        r.rx1_dr_offset = 0;
        r.freq_100hz = 500'000;
        CHECK_EQ(static_cast<int>(encode(r, out, len)), static_cast<int>(MacStatus::FieldOutOfRange));
    }
    // --- RXParamSetupAns (up) : bits 0..2 et RFU 7:3.
    {
        Buf out{};
        std::size_t len = 0;
        RxParamSetupAns a;
        a.channel_ack = true;
        a.rx1_dr_offset_ack = true;
        CHECK_EQ(static_cast<int>(encode(a, out, len)), static_cast<int>(MacStatus::Ok));
        CHECK_EQ(out[1], std::uint8_t{0x05});
        RxParamSetupAns back;
        const std::uint8_t rfu[2] = {0x05, 0x08};
        CHECK_EQ(static_cast<int>(decode(rfu, 2, back)), static_cast<int>(MacStatus::MalformedPayload));
    }
    // --- NewChannelReq (down) : ChIndex, Freq, DrRange = MaxDR 7:4 | MinDR 3:0.
    {
        Buf out{};
        std::size_t len = 0;
        NewChannelReq n;
        n.ch_index = 3;
        n.freq_100hz = 8'686'000;  // 868,6 MHz
        n.min_dr = 0;
        n.max_dr = 5;              // DrRange = 0x50 : DR0 à DR5
        CHECK_EQ(static_cast<int>(encode(n, out, len)), static_cast<int>(MacStatus::Ok));
        CHECK_EQ(len, std::size_t{6});
        CHECK_EQ(out[5], std::uint8_t{0x50});
        NewChannelReq back;
        CHECK_EQ(static_cast<int>(decode(out.data(), len, back)), static_cast<int>(MacStatus::Ok));
        CHECK_EQ(back.ch_index, std::uint8_t{3});
        CHECK_EQ(back.freq_100hz, std::uint32_t{8'686'000});
        CHECK_EQ(back.max_dr, std::uint8_t{5});
        // Canal 0 désactivé : fréquence 0 acceptée.
        n.freq_100hz = 0;
        CHECK_EQ(static_cast<int>(encode(n, out, len)), static_cast<int>(MacStatus::Ok));
        // ChIndex 16 refusé.
        n.ch_index = 16;
        CHECK_EQ(static_cast<int>(encode(n, out, len)), static_cast<int>(MacStatus::FieldOutOfRange));
        // ChIndex 16 refusé aussi au décodage.
        const std::uint8_t bad_idx[6] = {0x07, 0x10, 0x00, 0x00, 0x00, 0x50};
        CHECK_EQ(static_cast<int>(decode(bad_idx, 6, back)), static_cast<int>(MacStatus::FieldOutOfRange));
    }
    // --- NewChannelAns (up) : bits 0..1 et RFU 7:2.
    {
        Buf out{};
        std::size_t len = 0;
        NewChannelAns a;
        a.channel_freq_ack = true;
        CHECK_EQ(static_cast<int>(encode(a, out, len)), static_cast<int>(MacStatus::Ok));
        CHECK_EQ(out[1], std::uint8_t{0x02});
        NewChannelAns back;
        const std::uint8_t rfu[2] = {0x07, 0x04};
        CHECK_EQ(static_cast<int>(decode(rfu, 2, back)), static_cast<int>(MacStatus::MalformedPayload));
    }
    // --- Tailles dans un flux : RXParamSetupReq (5) et NewChannelReq (6) ; CID 0x0D reste inconnu.
    {
        const std::uint8_t dn[11] = {0x05, 0x00, 0x00, 0x00, 0x00, 0x07, 0x00, 0x00, 0x00, 0x00, 0x00};
        std::size_t size = 0;
        CHECK_EQ(static_cast<int>(command_size(Direction::Downlink, dn, 11, size)), static_cast<int>(MacStatus::Ok));
        CHECK_EQ(size, std::size_t{5});
        CHECK_EQ(static_cast<int>(command_size(Direction::Downlink, dn + 5, 6, size)), static_cast<int>(MacStatus::Ok));
        CHECK_EQ(size, std::size_t{6});
        const std::uint8_t unk[2] = {0x10, 0x00};
        CHECK_EQ(static_cast<int>(command_size(Direction::Downlink, unk, 2, size)),
                 static_cast<int>(MacStatus::UnknownCommand));
    }
    // --- Surface C : nouveaux types.
    {
        lsim_mac_command c{};
        c.kind = LSIM_MAC_NEW_CHANNEL_REQ;
        c.ch_index = 4;
        c.freq_100hz = 8'670'000;
        c.min_dr = 0;
        c.max_dr = 5;
        std::uint8_t out[LSIM_MAC_MAX_COMMAND_BYTES] = {};
        std::size_t n = 0;
        CHECK_EQ(lsim_mac_encode(&c, out, &n), 0);
        CHECK_EQ(n, std::size_t{6});
        lsim_mac_command back{};
        std::size_t used = 0;
        CHECK_EQ(lsim_mac_decode(out, n, LSIM_MAC_DOWNLINK, &back, &used), 0);
        CHECK_EQ(back.kind, std::uint8_t{LSIM_MAC_NEW_CHANNEL_REQ});
        CHECK_EQ(back.freq_100hz, std::uint32_t{8'670'000});
        const std::uint8_t ans[2] = {0x05, 0x03};
        CHECK_EQ(lsim_mac_decode(ans, 2, LSIM_MAC_UPLINK, &back, &used), 0);
        CHECK_EQ(back.kind, std::uint8_t{LSIM_MAC_RX_PARAM_SETUP_ANS});
        CHECK_EQ(back.ack_rx_channel, std::uint8_t{1});
        CHECK_EQ(back.ack_rx2_data_rate, std::uint8_t{1});
        CHECK_EQ(back.ack_rx1_dr_offset, std::uint8_t{0});
    }

    // --- RXTimingSetupReq (down) : Del 3:0, bits 7:4 RFU.
    {
        Buf out{};
        std::size_t len = 0;
        RxTimingSetupReq r;
        r.delay = 5;
        CHECK_EQ(static_cast<int>(encode(r, out, len)), static_cast<int>(MacStatus::Ok));
        CHECK_EQ(len, std::size_t{2});
        CHECK_EQ(out[1], std::uint8_t{0x05});
        RxTimingSetupReq back;
        const std::uint8_t rfu[2] = {0x08, 0x10};
        CHECK_EQ(static_cast<int>(decode(rfu, 2, back)), static_cast<int>(MacStatus::MalformedPayload));
        r.delay = 16;
        CHECK_EQ(static_cast<int>(encode(r, out, len)), static_cast<int>(MacStatus::FieldOutOfRange));
    }
    // --- DeviceTimeAns (down) : 32 bits LE + fraction. Exemple : 1139322288 s (spec §5.12).
    {
        Buf out{};
        std::size_t len = 0;
        DeviceTimeAns d;
        d.seconds = 1'139'322'288u;
        d.fraction = 0x80;
        CHECK_EQ(static_cast<int>(encode(d, out, len)), static_cast<int>(MacStatus::Ok));
        CHECK_EQ(len, std::size_t{6});
        DeviceTimeAns back;
        CHECK_EQ(static_cast<int>(decode(out.data(), len, back)), static_cast<int>(MacStatus::Ok));
        CHECK_EQ(back.seconds, std::uint32_t{1'139'322'288u});
        CHECK_EQ(back.fraction, std::uint8_t{0x80});
    }
    // --- ForceRejoinReq (down) : 16 bits LE ; RejoinType 3..7 RFU refusé ; bits 15:14 et 7 RFU.
    {
        Buf out{};
        std::size_t len = 0;
        ForceRejoinReq f;
        f.period = 2;
        f.max_retries = 3;
        f.rejoin_type = 2;
        f.dr = 5;
        CHECK_EQ(static_cast<int>(encode(f, out, len)), static_cast<int>(MacStatus::Ok));
        CHECK_EQ(len, std::size_t{3});
        // word = 2<<11 | 3<<8 | 2<<4 | 5 = 0x1000 | 0x0300 | 0x0020 | 0x0005 = 0x1325
        CHECK_EQ(out[1], std::uint8_t{0x25});
        CHECK_EQ(out[2], std::uint8_t{0x13});
        ForceRejoinReq back;
        CHECK_EQ(static_cast<int>(decode(out.data(), len, back)), static_cast<int>(MacStatus::Ok));
        CHECK_EQ(back.period, std::uint8_t{2});
        CHECK_EQ(back.max_retries, std::uint8_t{3});
        CHECK_EQ(back.rejoin_type, std::uint8_t{2});
        CHECK_EQ(back.dr, std::uint8_t{5});
        const std::uint8_t rtype_rfu[3] = {0x0E, 0x35, 0x00};  // type 3 (0x30 dans 6:4)
        CHECK_EQ(static_cast<int>(decode(rtype_rfu, 3, back)), static_cast<int>(MacStatus::FieldOutOfRange));
        const std::uint8_t bit7[3] = {0x0E, 0x80, 0x00};
        CHECK_EQ(static_cast<int>(decode(bit7, 3, back)), static_cast<int>(MacStatus::MalformedPayload));
        const std::uint8_t bit15[3] = {0x0E, 0x00, 0x80};
        CHECK_EQ(static_cast<int>(decode(bit15, 3, back)), static_cast<int>(MacStatus::MalformedPayload));
        f.period = 8;
        CHECK_EQ(static_cast<int>(encode(f, out, len)), static_cast<int>(MacStatus::FieldOutOfRange));
    }
    // --- RejoinParamSetup : Req (MaxTimeN 7:4, MaxCountN 3:0), Ans (bit 0 TimeOK).
    {
        Buf out{};
        std::size_t len = 0;
        RejoinParamSetupReq r;
        r.max_time_n = 4;
        r.max_count_n = 7;
        CHECK_EQ(static_cast<int>(encode(r, out, len)), static_cast<int>(MacStatus::Ok));
        CHECK_EQ(out[1], std::uint8_t{0x47});
        RejoinParamSetupAns a;
        a.time_ok = true;
        CHECK_EQ(static_cast<int>(encode(a, out, len)), static_cast<int>(MacStatus::Ok));
        CHECK_EQ(out[1], std::uint8_t{0x01});
        RejoinParamSetupAns back;
        const std::uint8_t rfu[2] = {0x0F, 0x02};
        CHECK_EQ(static_cast<int>(decode(rfu, 2, back)), static_cast<int>(MacStatus::MalformedPayload));
    }
    // --- ADRParamSetupReq (down) : Limit_exp 7:4, Delay_exp 3:0 ; ADRParamSetupAns (up, vide).
    {
        Buf out{};
        std::size_t len = 0;
        AdrParamSetupReq r;
        r.limit_exp = 4;
        r.delay_exp = 13;
        CHECK_EQ(static_cast<int>(encode(r, out, len)), static_cast<int>(MacStatus::Ok));
        CHECK_EQ(len, std::size_t{2});
        CHECK_EQ(out[0], std::uint8_t{0x0C});
        CHECK_EQ(out[1], std::uint8_t{0x4D});
        AdrParamSetupReq back;
        CHECK_EQ(static_cast<int>(decode(out.data(), len, back)), static_cast<int>(MacStatus::Ok));
        CHECK_EQ(back.limit_exp, std::uint8_t{4});
        CHECK_EQ(back.delay_exp, std::uint8_t{13});
        AdrParamSetupReq bad;
        bad.limit_exp = 16;
        CHECK_EQ(static_cast<int>(encode(bad, out, len)), static_cast<int>(MacStatus::FieldOutOfRange));
        bad.limit_exp = 0;
        bad.delay_exp = 16;
        CHECK_EQ(static_cast<int>(encode(bad, out, len)), static_cast<int>(MacStatus::FieldOutOfRange));
        const std::uint8_t trunc[1] = {0x0C};
        CHECK_EQ(static_cast<int>(decode(trunc, 1, back)), static_cast<int>(MacStatus::MalformedPayload));
        std::size_t size = 0;
        const std::uint8_t dn[2] = {0x0C, 0x00};
        CHECK_EQ(static_cast<int>(command_size(Direction::Downlink, dn, 2, size)), static_cast<int>(MacStatus::Ok));
        CHECK_EQ(size, std::size_t{2});
        const std::uint8_t up[1] = {0x0C};
        CHECK_EQ(static_cast<int>(command_size(Direction::Uplink, up, 1, size)), static_cast<int>(MacStatus::Ok));
        CHECK_EQ(size, std::size_t{1});
    }
    // --- DlChannelReq (down) : ChIndex, Freq >= 100 MHz ; DlChannelAns (up) : bits 0..1, RFU 7:2.
    {
        Buf out{};
        std::size_t len = 0;
        DlChannelReq d;
        d.ch_index = 2;
        d.freq_100hz = 9'235'000;  // 923,5 MHz
        CHECK_EQ(static_cast<int>(encode(d, out, len)), static_cast<int>(MacStatus::Ok));
        CHECK_EQ(len, std::size_t{5});
        DlChannelReq back;
        CHECK_EQ(static_cast<int>(decode(out.data(), len, back)), static_cast<int>(MacStatus::Ok));
        CHECK_EQ(back.freq_100hz, std::uint32_t{9'235'000});
        d.freq_100hz = 500'000;
        CHECK_EQ(static_cast<int>(encode(d, out, len)), static_cast<int>(MacStatus::FieldOutOfRange));
        DlChannelAns a;
        a.uplink_freq_exists = true;
        CHECK_EQ(static_cast<int>(encode(a, out, len)), static_cast<int>(MacStatus::Ok));
        CHECK_EQ(out[1], std::uint8_t{0x02});
        DlChannelAns ab;
        const std::uint8_t rfu[2] = {0x0A, 0x04};
        CHECK_EQ(static_cast<int>(decode(rfu, 2, ab)), static_cast<int>(MacStatus::MalformedPayload));
    }
    // --- Tailles et CID : DeviceTimeReq (up, 1), DeviceTimeAns (down, 6) ; 0x10 reste inconnu.
    {
        std::size_t size = 0;
        const std::uint8_t dt_req[1] = {0x0D};
        CHECK_EQ(static_cast<int>(command_size(Direction::Uplink, dt_req, 1, size)), static_cast<int>(MacStatus::Ok));
        CHECK_EQ(size, std::size_t{1});
        const std::uint8_t dt_ans[6] = {0x0D, 0, 0, 0, 0, 0};
        CHECK_EQ(static_cast<int>(command_size(Direction::Downlink, dt_ans, 6, size)), static_cast<int>(MacStatus::Ok));
        CHECK_EQ(size, std::size_t{6});
        const std::uint8_t ping[2] = {0x10, 0x00};
        CHECK_EQ(static_cast<int>(command_size(Direction::Downlink, ping, 2, size)),
                 static_cast<int>(MacStatus::UnknownCommand));
    }
    // --- Surface C : ForceRejoin et DeviceTimeAns.
    {
        lsim_mac_command c{};
        c.kind = LSIM_MAC_FORCE_REJOIN_REQ;
        c.rejoin_period = 2;
        c.rejoin_max_retries = 3;
        c.rejoin_type = 2;
        c.data_rate = 5;
        std::uint8_t out[LSIM_MAC_MAX_COMMAND_BYTES] = {};
        std::size_t n = 0;
        CHECK_EQ(lsim_mac_encode(&c, out, &n), 0);
        CHECK_EQ(n, std::size_t{3});
        lsim_mac_command back{};
        std::size_t used = 0;
        CHECK_EQ(lsim_mac_decode(out, n, LSIM_MAC_DOWNLINK, &back, &used), 0);
        CHECK_EQ(back.kind, std::uint8_t{LSIM_MAC_FORCE_REJOIN_REQ});
        CHECK_EQ(back.data_rate, std::uint8_t{5});
        lsim_mac_command dt{};
        dt.kind = LSIM_MAC_DEVICE_TIME_ANS;
        dt.device_time_s = 1'139'322'288u;
        dt.device_time_frac = 0x40;
        CHECK_EQ(lsim_mac_encode(&dt, out, &n), 0);
        CHECK_EQ(n, std::size_t{6});
        CHECK_EQ(lsim_mac_decode(out, n, LSIM_MAC_DOWNLINK, &back, &used), 0);
        CHECK_EQ(back.device_time_s, std::uint32_t{1'139'322'288u});
    }
}
