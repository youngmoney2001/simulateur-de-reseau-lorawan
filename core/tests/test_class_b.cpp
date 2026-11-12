// SPDX-License-Identifier: Apache-2.0
// Classe B : CRC et décodage du beacon (exemple de la spec), pingOffset (vecteurs OpenSSL
// indépendants), timing des ping slots, suivi beacon / beacon-less, passage par l'API C.
#include <cmath>
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

    // --- GwSpecific : exemple EU868 (CRC GwSpecific DE55) puis exemple US915 (CRC D450).
    {
        BeaconCommon common;
        GatewayInfo gw;
        CHECK_EQ(static_cast<int>(decode_beacon_full(kEuBeacon.data(), kEuBeacon.size(), 2, 0, common, gw)),
                 0);
        CHECK_EQ(static_cast<int>(common.time_s), static_cast<int>(0xCC020000u));
        CHECK_TRUE(gw.present);
        CHECK_EQ(static_cast<int>(gw.info_desc), 0);
        CHECK_TRUE(gw.has_coordinates);
        // Lat 0x002001 = 8193 ; Lng 0x038100 = 229632 (complément à deux, 24 bits).
        CHECK_NEAR(gw.latitude_deg - 8193.0 * 90.0 / 8388608.0, 0.0, 1e-12);
        CHECK_NEAR(gw.longitude_deg - 229632.0 * 180.0 / 8388608.0, 0.0, 1e-12);

        const std::vector<std::uint8_t> us = {0x00, 0x00, 0x00, 0x00, 0x00, 0x02, 0xCC, 0xA2, 0x7E,
                                              0x00, 0x01, 0x20, 0x00, 0x00, 0x81, 0x03, 0x00, 0x50, 0xD4};
        CHECK_EQ(static_cast<int>(decode_beacon_full(us.data(), us.size(), 3, 1, common, gw)), 0);
        CHECK_EQ(static_cast<int>(common.time_s), static_cast<int>(0xCC020000u));
        CHECK_TRUE(gw.present);
        CHECK_NEAR(gw.latitude_deg - 8193.0 * 90.0 / 8388608.0, 0.0, 1e-12);

        // Sans GwSpecific : accepté, gw.present = false.
        CHECK_EQ(static_cast<int>(decode_beacon_full(kEuBeacon.data(), 8, 2, 0, common, gw)), 0);
        CHECK_TRUE(!gw.present);

        // Longueur incohérente et CRC GwSpecific faux.
        CHECK_EQ(static_cast<int>(decode_beacon_full(kEuBeacon.data(), 12, 2, 0, common, gw)),
                 static_cast<int>(ClassBStatus::InvalidParameter));
        auto bad_gw = kEuBeacon;
        bad_gw[9] ^= 0x01;  // altère Lat : CRC GwSpecific doit échouer
        CHECK_EQ(static_cast<int>(decode_beacon_full(bad_gw.data(), bad_gw.size(), 2, 0, common, gw)),
                 static_cast<int>(ClassBStatus::CrcError));

        // Latitude -90° (raw -2^23 = 0x800000) et InfoDesc 3 (pas de coordonnées décodées).
        std::vector<std::uint8_t> south = {0x00, 0x00, 0x00, 0x00, 0x02, 0xCC, 0xA2, 0x7E,
                                           0x00, 0x00, 0x00, 0x80, 0x00, 0x00, 0x00};
        const std::uint16_t crc_s = beacon_crc16(south.data() + 8, 7);
        south.push_back(static_cast<std::uint8_t>(crc_s & 0xFF));
        south.push_back(static_cast<std::uint8_t>(crc_s >> 8));
        CHECK_EQ(static_cast<int>(decode_beacon_full(south.data(), south.size(), 2, 0, common, gw)), 0);
        CHECK_NEAR(gw.latitude_deg + 90.0, 0.0, 1e-12);
        auto info3 = south;
        info3[8] = 3;
        const std::uint16_t crc_3 = beacon_crc16(info3.data() + 8, 7);
        info3[15] = static_cast<std::uint8_t>(crc_3 & 0xFF);
        info3[16] = static_cast<std::uint8_t>(crc_3 >> 8);
        CHECK_EQ(static_cast<int>(decode_beacon_full(info3.data(), info3.size(), 2, 0, common, gw)), 0);
        CHECK_TRUE(gw.present);
        CHECK_TRUE(!gw.has_coordinates);
    }

    // --- US902-928 : canal = floor(T/128) mod 8, fréquence 923,3 MHz + 0,6 MHz × indice.
    {
        std::uint8_t idx = 99;
        CHECK_EQ(static_cast<int>(us902_channel_index(0, idx)), 0);
        CHECK_EQ(static_cast<int>(idx), 0);
        CHECK_EQ(static_cast<int>(us902_channel_index(127, idx)), 0);
        CHECK_EQ(static_cast<int>(idx), 0);
        CHECK_EQ(static_cast<int>(us902_channel_index(128, idx)), 0);
        CHECK_EQ(static_cast<int>(idx), 1);
        CHECK_EQ(static_cast<int>(us902_channel_index(8 * 128, idx)), 0);
        CHECK_EQ(static_cast<int>(idx), 0);
        std::uint32_t f = 0;
        CHECK_EQ(static_cast<int>(us902_channel_frequency_hz(0, f)), 0);
        CHECK_EQ(static_cast<int>(f), 923300000);
        CHECK_EQ(static_cast<int>(us902_channel_frequency_hz(7, f)), 0);
        CHECK_EQ(static_cast<int>(f), 927500000);
        CHECK_EQ(static_cast<int>(us902_channel_frequency_hz(8, f)), static_cast<int>(ClassBStatus::InvalidParameter));
        uint32_t cf = 0;
        uint8_t ci = 0;
        CHECK_EQ(lsim_classb_us902_channel(128, &ci, &cf), 0);
        CHECK_EQ(static_cast<int>(ci), 1);
        CHECK_EQ(static_cast<int>(cf), 923900000);
    }

    // --- Dérive d'horloge : fenêtre élargie = dérive × temps depuis le beacon (arrondi sup.).
    {
        DeviceClassB d;
        d.dev_addr = 0;
        d.periodicity = 7;
        CHECK_EQ(static_cast<int>(on_beacon(d, 0, 0)), 0);
        PingSlot s{};
        CHECK_EQ(static_cast<int>(next_ping_slot(d, 0, s)), 0);
        CHECK_EQ(static_cast<int>(s.window_half_ns), 0);  // dérive nulle : pas d'élargissement

        d.clock_drift_ppm = 10;  // spec : ±10 ppm ≈ ±1,3 ms après une période de 128 s
        CHECK_EQ(static_cast<int>(next_ping_slot(d, 0, s)), 0);
        const std::uint64_t expected = (s.start_ns * 10ull + 999'999ull) / 1'000'000ull;
        CHECK_EQ(static_cast<int>(s.window_half_ns), static_cast<int>(expected));
        CHECK_TRUE(s.window_half_ns <= 1'280'000ull * 2);  // slot avant 2 × 128 s : ≤ 2,56 ms

        // Beacon-less : 2 h après le beacon, la fenêtre atteint plusieurs dizaines de ms.
        DeviceClassB far = d;
        PingSlot late{};
        CHECK_EQ(static_cast<int>(next_ping_slot(far, 7000ull * kSec, late)), 0);
        CHECK_TRUE(late.window_half_ns >= 60'000'000ull);

        d.clock_drift_ppm = 1001;
        CHECK_EQ(static_cast<int>(next_ping_slot(d, 0, s)), static_cast<int>(ClassBStatus::InvalidParameter));

        lsim_classb_device cd{};
        cd.periodicity = 7;
        cd.clock_drift_ppm = 10;
        CHECK_EQ(lsim_classb_on_beacon(&cd, 0, 0), 0);
        lsim_classb_ping_slot cs{};
        CHECK_EQ(lsim_classb_next_ping_slot(&cd, 0, &cs), 0);
        CHECK_EQ(static_cast<int>(cs.window_half_ns), static_cast<int>(expected));
    }

    // --- ping_slot_at : la question inverse. Un terminal ne choisit pas quand le réseau
    //     émet, il décide s'il écoute à cet instant. La fonction est O(1) (trois
    //     candidats) ; elle est donc confrontée au balayage exhaustif des slots, qui est
    //     la définition même de la fenêtre.
    {
        for (std::uint8_t periodicite : {std::uint8_t{0}, std::uint8_t{3}, std::uint8_t{7}}) {
            for (std::uint32_t derive : {std::uint32_t{0}, std::uint32_t{10}}) {
                DeviceClassB d{};
                d.dev_addr = 0x11223344u;
                d.periodicity = periodicite;
                d.clock_drift_ppm = derive;
                CHECK_EQ(static_cast<int>(on_beacon(d, 0, 0)), 0);

                std::uint32_t ping_nb = 0;
                std::uint32_t ping_period = 0;
                CHECK_EQ(static_cast<int>(ping_slot_count(periodicite, ping_nb, ping_period)), 0);

                // Balayage : un instant toutes les 10 ms sur trois périodes de balise.
                std::size_t trouves = 0;
                std::size_t ecarts = 0;
                for (std::uint64_t t = 0; t < 3 * kBeaconPeriodNs; t += 10'000'000ull) {
                    // Référence : les trois mêmes périodes, tous les slots, dans l'ordre.
                    const std::uint64_t k = t / kBeaconPeriodNs;
                    bool attendu = false;
                    std::uint64_t debut_attendu = 0;
                    for (std::int64_t delta = -1; delta <= 1 && !attendu; ++delta) {
                        const std::int64_t j = static_cast<std::int64_t>(k) + delta;
                        if (j < 0) continue;
                        const std::uint64_t debut_periode =
                            d.last_beacon_rx_ns + static_cast<std::uint64_t>(j) * kBeaconPeriodNs;
                        const std::uint32_t temps_balise =
                            d.last_beacon_time_s + static_cast<std::uint32_t>(
                                static_cast<std::uint64_t>(j) * (kBeaconPeriodNs / kSec));
                        std::uint32_t offset = 0;
                        CHECK_EQ(static_cast<int>(ping_offset(temps_balise, d.dev_addr,
                                                              periodicite, offset)), 0);
                        for (std::uint32_t m = 0; m < ping_nb; ++m) {
                            const std::uint32_t n = offset + m * ping_period;
                            const std::uint64_t debut = debut_periode + kBeaconReservedNs
                                + static_cast<std::uint64_t>(n) * kSlotNs;
                            const std::uint64_t marge =
                                ((debut - d.last_beacon_rx_ns) * derive + 999'999ull) / 1'000'000ull;
                            if (t + marge >= debut && t < debut + kSlotNs + marge) {
                                attendu = true;
                                debut_attendu = debut;
                                break;
                            }
                        }
                    }
                    PingSlot s{};
                    const bool obtenu = ping_slot_at(d, t, s) == ClassBStatus::Ok;
                    CHECK_EQ(static_cast<int>(obtenu), static_cast<int>(attendu));
                    if (attendu) {
                        ++trouves;
                        if (s.start_ns != debut_attendu) ++ecarts;
                    }
                }
                CHECK_EQ(static_cast<int>(ecarts), 0);
                CHECK_TRUE(trouves > 0);   // au moins un ping slot couvert, sinon le test est vide
            }
        }
    }
    // --- ping_slot_at : bords de fenêtre, dérive, et états du dispositif.
    {
        DeviceClassB d{};
        d.dev_addr = 0x0000ABCDu;
        d.periodicity = 0;
        CHECK_EQ(static_cast<int>(on_beacon(d, 0, 0)), 0);
        PingSlot s{};
        CHECK_EQ(static_cast<int>(next_ping_slot(d, 0, s)), 0);
        const std::uint64_t debut = s.start_ns;

        // Sans dérive : fenêtre exactement [start, start + 30 ms).
        PingSlot a{};
        CHECK_EQ(static_cast<int>(ping_slot_at(d, debut, a)), 0);
        CHECK_EQ(static_cast<int>(a.slot_index), static_cast<int>(s.slot_index));
        CHECK_EQ(static_cast<int>(ping_slot_at(d, debut - 1, a)),
                 static_cast<int>(ClassBStatus::NoSlot));
        CHECK_EQ(static_cast<int>(ping_slot_at(d, debut + kSlotNs - 1, a)), 0);
        CHECK_EQ(static_cast<int>(ping_slot_at(d, debut + kSlotNs, a)),
                 static_cast<int>(ClassBStatus::NoSlot));

        // Avec dérive : la fenêtre s'élargit de `window_half_ns` de chaque côté.
        d.clock_drift_ppm = 10;
        PingSlot w{};
        CHECK_EQ(static_cast<int>(ping_slot_at(d, debut, w)), 0);
        const std::uint64_t marge = w.window_half_ns;
        CHECK_TRUE(marge > 0);
        CHECK_EQ(static_cast<int>(ping_slot_at(d, debut - marge, w)), 0);
        CHECK_EQ(static_cast<int>(ping_slot_at(d, debut - marge - 1, w)),
                 static_cast<int>(ClassBStatus::NoSlot));
        CHECK_EQ(static_cast<int>(ping_slot_at(d, debut + kSlotNs + marge - 1, w)), 0);
        CHECK_EQ(static_cast<int>(ping_slot_at(d, debut + kSlotNs + marge, w)),
                 static_cast<int>(ClassBStatus::NoSlot));

        // Un dispositif qui n'a jamais reçu de beacon n'ouvre aucun slot.
        DeviceClassB vierge{};
        vierge.periodicity = 0;
        CHECK_EQ(static_cast<int>(ping_slot_at(vierge, debut, w)),
                 static_cast<int>(ClassBStatus::NotSynchronized));
        // Au-delà de 2 h sans beacon : la classe B est quittée.
        CHECK_EQ(static_cast<int>(ping_slot_at(d, kBeaconlessNs, w)),
                 static_cast<int>(ClassBStatus::BeaconLost));
        // Paramètres hors bornes.
        DeviceClassB mauvais = d;
        mauvais.clock_drift_ppm = kMaxDriftPpm + 1;
        CHECK_EQ(static_cast<int>(ping_slot_at(mauvais, debut, w)),
                 static_cast<int>(ClassBStatus::InvalidParameter));

        // Passage par l'API C.
        lsim_classb_device cd{};
        cd.dev_addr = 0x0000ABCDu;
        cd.periodicity = 0;
        CHECK_EQ(lsim_classb_on_beacon(&cd, 0, 0), 0);
        lsim_classb_ping_slot cs{};
        CHECK_EQ(lsim_classb_ping_slot_at(&cd, debut, &cs), 0);
        CHECK_EQ(static_cast<int>(cs.slot_index), static_cast<int>(s.slot_index));
        CHECK_EQ(static_cast<int>(lsim_classb_ping_slot_at(&cd, debut - 1, &cs)),
                 LSIM_STATUS_CLASSB_BASE + static_cast<int>(ClassBStatus::NoSlot));
        CHECK_TRUE(lsim_classb_ping_slot_at(nullptr, 0, &cs) != 0);
        CHECK_TRUE(lsim_classb_ping_slot_at(&cd, 0, nullptr) != 0);
    }
}

