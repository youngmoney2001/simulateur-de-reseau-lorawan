// SPDX-License-Identifier: Apache-2.0
// Codec des commandes MAC LoRaWAN 1.1 : octets attendus, bornes et bits RFU.
#include <array>
#include <cstdint>

#include "check.hpp"
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
        const std::uint8_t unknown[2] = {0x05, 0x00};
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
}
