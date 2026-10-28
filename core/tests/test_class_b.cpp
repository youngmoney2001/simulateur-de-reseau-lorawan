// SPDX-License-Identifier: Apache-2.0
// Classe B : CRC et décodage du beacon (exemple de la spec), pingOffset (vecteurs OpenSSL
// indépendants), timing des ping slots, suivi beacon / beacon-less, passage par l'API C.
#include <cstdint>
#include <vector>

#include "check.hpp"
#include "lsim/c_api.h"
#include "lsim/class_b.hpp"
#include "lsim/lora_phy.hpp"

using namespace lsim::lorawan::classb;

namespace {

constexpr std::uint64_t kSec = 1'000'000'000ull;

// Beacon EU868 de la spec (figure 61) : RFU 0000 | Time CC020000 (LE) | CRC A27E | GwSpecific | CRC.
const std::vector<std::uint8_t> kEuBeacon = {0x00, 0x00, 0x00, 0x00, 0x02, 0xCC, 0xA2, 0x7E, 0x00,
                                             0x01, 0x20, 0x00, 0x00, 0x81, 0x03, 0xDE, 0x55};

}  // namespace

void run_class_b_tests() {
    // --- CRC-16 : exemple de la spec (valeur 0x7EA2, transmise A2 7E).
    {
        const std::uint8_t body[6] = {0x00, 0x00, 0x00, 0x00, 0x02, 0xCC};
        CHECK_EQ(static_cast<int>(beacon_crc16(body, 6)), 0x7EA2);
        const std::uint8_t body2[6] = {0x00, 0x00, 0x00, 0x00, 0x02, 0xCD};
        CHECK_TRUE(beacon_crc16(body2, 6) != 0x7EA2);
    }
    // --- Décodage du beacon.
    {
        BeaconCommon b;
        CHECK_EQ(static_cast<int>(decode_beacon(kEuBeacon.data(), kEuBeacon.size(), 2, b)),
                 static_cast<int>(ClassBStatus::Ok));
        CHECK_EQ(static_cast<int>(b.time_s), static_cast<int>(0xCC020000u));
        auto bad = kEuBeacon;
        bad[4] ^= 0x01;  // un bit du champ Time
        CHECK_EQ(static_cast<int>(decode_beacon(bad.data(), bad.size(), 2, b)),
                 static_cast<int>(ClassBStatus::CrcError));
        CHECK_EQ(static_cast<int>(decode_beacon(kEuBeacon.data(), 7, 2, b)),
                 static_cast<int>(ClassBStatus::InvalidParameter));  // trop court
        CHECK_EQ(static_cast<int>(decode_beacon(kEuBeacon.data(), kEuBeacon.size(), 4, b)),
                 static_cast<int>(ClassBStatus::InvalidParameter));  // RFU hors 2/3
    }
    // --- pingOffset : vecteurs calculés avec openssl (aes-128-ecb, clé nulle, bloc
    //     beaconTime LE | DevAddr LE | 8 zéros) : offset = (Rand0 + 256·Rand1) mod pingPeriod.
    {
        std::uint32_t off = 0;
        CHECK_EQ(static_cast<int>(ping_offset(0xCC020000u, 0x26011234u, 0, off)),
                 static_cast<int>(ClassBStatus::Ok));
        CHECK_EQ(static_cast<int>(off), 6);  // Rand = 06af4566…, pingPeriod 32
        CHECK_EQ(static_cast<int>(ping_offset(0u, 0u, 7, off)), static_cast<int>(ClassBStatus::Ok));
        CHECK_EQ(static_cast<int>(off), 2406);  // Rand = 66e94bd4…, pingPeriod 4096
        CHECK_EQ(static_cast<int>(ping_offset(1234567u, 0xFFFFFFFFu, 2, off)),
                 static_cast<int>(ClassBStatus::Ok));
        CHECK_EQ(static_cast<int>(off), 94);  // Rand = de8b8275…, pingPeriod 128
        CHECK_EQ(static_cast<int>(ping_offset(0u, 0u, 8, off)),
                 static_cast<int>(ClassBStatus::InvalidParameter));
    }
    // --- Nombre de ping slots : pingNb = 2^(7-P), pingPeriod = 2^(5+P).
    {
        std::uint32_t nb = 0, per = 0;
        CHECK_EQ(static_cast<int>(ping_slot_count(0, nb, per)), static_cast<int>(ClassBStatus::Ok));
        CHECK_EQ(static_cast<int>(nb), 128);
        CHECK_EQ(static_cast<int>(per), 32);
        CHECK_EQ(static_cast<int>(ping_slot_count(7, nb, per)), static_cast<int>(ClassBStatus::Ok));
        CHECK_EQ(static_cast<int>(nb), 1);
        CHECK_EQ(static_cast<int>(per), 4096);
    }
    // --- États de synchronisation.
    {
        DeviceClassB d;
        d.dev_addr = 0x26011234;
        d.periodicity = 7;
        BeaconState st = BeaconState::Lost;
        CHECK_EQ(static_cast<int>(beacon_state(d, 0, st)), static_cast<int>(ClassBStatus::Ok));
        CHECK_TRUE(st == BeaconState::NotSynchronized);
        PingSlot ps;
        CHECK_EQ(static_cast<int>(next_ping_slot(d, 0, ps)), static_cast<int>(ClassBStatus::NotSynchronized));

        const std::uint64_t t0 = 1000 * kSec;
        CHECK_EQ(static_cast<int>(on_beacon(d, t0, 500)), static_cast<int>(ClassBStatus::Ok));
        beacon_state(d, t0 + 60 * kSec, st);
        CHECK_TRUE(st == BeaconState::Synchronized);
        beacon_state(d, t0 + 200 * kSec, st);
        CHECK_TRUE(st == BeaconState::BeaconLess);
        beacon_state(d, t0 + 120 * 60 * kSec, st);
        CHECK_TRUE(st == BeaconState::Lost);
        CHECK_EQ(static_cast<int>(next_ping_slot(d, t0 + 120 * 60 * kSec, ps)),
                 static_cast<int>(ClassBStatus::BeaconLost));
        // Nouveau beacon après 3 h : resynchronisation.
        CHECK_EQ(static_cast<int>(on_beacon(d, t0 + 3 * 3600 * kSec, 9999)), static_cast<int>(ClassBStatus::Ok));
        beacon_state(d, t0 + 3 * 3600 * kSec, st);
        CHECK_TRUE(st == BeaconState::Synchronized);
        // Horloge qui recule : refusé.
        CHECK_EQ(static_cast<int>(on_beacon(d, t0, 1)), static_cast<int>(ClassBStatus::InvalidParameter));
    }
    // --- Ping slot, périodicité 7 : un slot par beacon, à l'index pingOffset.
    {
        DeviceClassB d;
        d.dev_addr = 0;
        d.periodicity = 7;
        const std::uint64_t t0 = 50 * kSec;
        on_beacon(d, t0, 0);  // beaconTime 0 : pingOffset = 2406 (vecteur ci-dessus)
        PingSlot ps;
        CHECK_EQ(static_cast<int>(next_ping_slot(d, t0, ps)), static_cast<int>(ClassBStatus::Ok));
        CHECK_EQ(static_cast<int>(ps.slot_index), 2406);
        // Ton = beacon_reserved + N·30 ms = 2,120 s + 72,18 s = 74,30 s après le beacon.
        CHECK_EQ(static_cast<int>(ps.start_ns), static_cast<int>(t0 + 74'300'000'000ull));
        CHECK_EQ(static_cast<int>(ps.beacon_time_s), 0);
        // Juste après ce slot : slot de la période suivante, beaconTime + 128 s.
        CHECK_EQ(static_cast<int>(next_ping_slot(d, ps.start_ns + 1, ps)), static_cast<int>(ClassBStatus::Ok));
        std::uint32_t off1 = 0;
        CHECK_EQ(static_cast<int>(ping_offset(128u, 0u, 7, off1)), static_cast<int>(ClassBStatus::Ok));
        CHECK_EQ(static_cast<int>(ps.slot_index), static_cast<int>(off1));
        CHECK_EQ(static_cast<int>(ps.beacon_time_s), 128);
        CHECK_EQ(static_cast<int>(ps.beacon_period_start_ns), static_cast<int>(t0 + 128 * kSec));
    }
    // --- Enroulement du beaconTime modulo 2^32 au passage de période.
    {
        DeviceClassB d;
        d.periodicity = 7;
        on_beacon(d, 0, 0xFFFFFFFFu - 10u);
        PingSlot ps;
        CHECK_EQ(static_cast<int>(next_ping_slot(d, 127 * kSec, ps)), static_cast<int>(ClassBStatus::Ok));
        CHECK_EQ(static_cast<int>(ps.beacon_time_s), 117);  // 0xFFFFFFFF - 10 + 128 mod 2^32
    }
    // --- Balayage déterministe (périodicité 0, 128 slots par période) : bornes et cohérence.
    {
        DeviceClassB d;
        d.dev_addr = 0x01020304;
        d.periodicity = 0;
        const std::uint64_t t0 = 7 * kSec;
        on_beacon(d, t0, 123456);
        std::uint64_t now = t0;
        std::uint64_t prev = 0;
        for (int i = 0; i < 400; ++i) {
            PingSlot ps;
            CHECK_EQ(static_cast<int>(next_ping_slot(d, now, ps)), static_cast<int>(ClassBStatus::Ok));
            CHECK_TRUE(ps.start_ns >= now);
            CHECK_TRUE(ps.slot_index < kSlotsPerWindow);
            const std::uint64_t rel = ps.start_ns - ps.beacon_period_start_ns;
            CHECK_TRUE(rel >= kBeaconReservedNs);
            // Le slot (30 ms) finit avant le début de la garde (125 s après le beacon).
            CHECK_TRUE(rel + kSlotNs <= kBeaconPeriodNs - kBeaconGuardNs);
            CHECK_TRUE(ps.start_ns >= prev);  // ordre croissant des appels successifs
            prev = ps.start_ns;
            now = ps.start_ns + 1;
        }
    }
    // --- API C : même comportement, statuts en 800+.
    {
        uint32_t t = 0;
        CHECK_EQ(lsim_classb_decode_beacon(kEuBeacon.data(), kEuBeacon.size(), 2, &t), 0);
        CHECK_EQ(static_cast<int>(t), static_cast<int>(0xCC020000u));
        auto bad = kEuBeacon;
        bad[6] ^= 0xFF;
        CHECK_EQ(lsim_classb_decode_beacon(bad.data(), bad.size(), 2, &t), LSIM_STATUS_CLASSB_BASE + 2);
        uint32_t off = 0;
        CHECK_EQ(lsim_classb_ping_offset(0u, 0u, 7, &off), 0);
        CHECK_EQ(static_cast<int>(off), 2406);
        CHECK_EQ(lsim_classb_ping_offset(0u, 0u, 9, &off), LSIM_STATUS_CLASSB_BASE + 1);
        lsim_classb_device cd2{};
        cd2.periodicity = 7;
        lsim_classb_ping_slot slot{};
        CHECK_EQ(lsim_classb_next_ping_slot(&cd2, 0, &slot), LSIM_STATUS_CLASSB_BASE + 3);
        CHECK_EQ(lsim_classb_on_beacon(&cd2, 0, 0), 0);
        CHECK_EQ(lsim_classb_next_ping_slot(&cd2, 0, &slot), 0);
        CHECK_EQ(static_cast<int>(slot.slot_index), 2406);
        uint8_t state = 9;
        CHECK_EQ(lsim_classb_beacon_state(&cd2, 0, &state), 0);
        CHECK_EQ(static_cast<int>(state), 1);
        CHECK_EQ(lsim_classb_next_ping_slot(nullptr, 0, &slot), static_cast<int>(lsim::lora::Status::NullOutput));
    }
}
