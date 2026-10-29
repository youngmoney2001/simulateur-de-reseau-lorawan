// SPDX-License-Identifier: Apache-2.0
// Opportunités de downlink par classe (A, B, C), intégration moteur et API C.
#include <cstdint>
#include <vector>

#include "check.hpp"
#include "lsim/c_api.h"
#include "lsim/class_b.hpp"
#include "lsim/downlink.hpp"
#include "lsim/engine.hpp"

using namespace lsim::lorawan;
using downlink::DownlinkStatus;
using downlink::Timing;
using downlink::Window;

namespace {

constexpr std::int64_t kS = 1'000'000'000;  // 1 s en ns

}  // namespace

void run_downlink_tests() {
    // --- Fusion d'intervalles : recouvrements, contacts, vides ignorés.
    {
        const auto m = downlink::merge_windows({{5, 9}, {0, 3}, {3, 4}, {7, 7}, {20, 25}, {22, 24}});
        CHECK_EQ(m.size(), static_cast<std::size_t>(3));
        CHECK_TRUE(m[0].start_ns == 0);
        CHECK_TRUE(m[0].end_ns == 4);
        CHECK_TRUE(m[1].start_ns == 5);
        CHECK_TRUE(m[1].end_ns == 9);
        CHECK_TRUE(m[2].end_ns == 25);
    }

    // --- Classe C : blocage = émission + RX1 ; ailleurs, réception immédiate.
    {
        const std::vector<Window> ups = {{1 * kS, 1 * kS + 100'000'000}};  // émission 1,0 → 1,1 s
        std::vector<Window> blocked;
        CHECK_EQ(static_cast<int>(downlink::class_c_blocked(ups, Timing{}, blocked)), 0);
        // Blocs : [1,0 ; 1,1) émission et [2,1 ; 3,1) RX1.
        CHECK_EQ(blocked.size(), static_cast<std::size_t>(2));
        std::int64_t opp = -1;
        CHECK_EQ(static_cast<int>(downlink::next_class_c(blocked, 500'000'000, opp)), 0);
        CHECK_TRUE(opp == 500'000'000);  // hors blocs : immédiat
        CHECK_EQ(static_cast<int>(downlink::next_class_c(blocked, 1'050'000'000, opp)), 0);
        CHECK_TRUE(opp == 1'100'000'000);  // fin de l'émission
        CHECK_EQ(static_cast<int>(downlink::next_class_c(blocked, 2'500'000'000, opp)), 0);
        CHECK_TRUE(opp == 3'100'000'000);  // fin de RX1
        // Fenêtre RX2 courte entre fin d'émission et RX1 : pas de blocage.
        CHECK_EQ(static_cast<int>(downlink::next_class_c(blocked, 1'500'000'000, opp)), 0);
        CHECK_TRUE(opp == 1'500'000'000);
    }

    // --- Classe A : RX1 (fin + 1 s) puis RX2 (fin + 2 s) ; rien si aucun uplink ultérieur.
    {
        const std::vector<Window> ups = {{0, 100'000'000}};
        std::int64_t opp = -1;
        CHECK_EQ(static_cast<int>(downlink::next_class_a(ups, 500'000'000, Timing{}, opp)), 0);
        CHECK_TRUE(opp == 1'100'000'000);  // RX1
        CHECK_EQ(static_cast<int>(downlink::next_class_a(ups, 1'200'000'000, Timing{}, opp)), 0);
        CHECK_TRUE(opp == 2'100'000'000);  // RX2
        CHECK_EQ(static_cast<int>(downlink::next_class_a(ups, 2'200'000'000, Timing{}, opp)),
                 static_cast<int>(DownlinkStatus::NoOpportunity));
        CHECK_EQ(static_cast<int>(downlink::next_class_a({}, 0, Timing{}, opp)),
                 static_cast<int>(DownlinkStatus::NoOpportunity));
    }

    // --- Classe B : ping slot sans blocage, puis décalé à la période suivante si bloqué.
    {
        downlink::ClassBProfile p;
        p.dev_addr = 0;
        p.periodicity = 7;  // pingNb = 1, pingPeriod = 4096 : un slot par période
        std::int64_t opp = -1;
        // Beacon 0, pingOffset(0, 0, 7) = 2406 : slot à 2,12 s + 2406 × 30 ms = 74,30 s.
        CHECK_EQ(static_cast<int>(downlink::next_class_b(p, {}, 0, opp)), 0);
        const std::int64_t slot0 = 2'120'000'000 + 2406LL * 30'000'000;
        CHECK_TRUE(opp == slot0);

        // Émission bloquant ce slot : le prochain slot est celui de la période de 128 s suivante.
        const std::vector<Window> blocked = {{slot0 - 10'000'000, slot0 + 10'000'000}};
        CHECK_EQ(static_cast<int>(downlink::next_class_b(p, blocked, 0, opp)), 0);
        const std::uint32_t off1 = [] {
            std::uint32_t o = 0;
            classb::ping_offset(128, 0, 7, o);
            return o;
        }();
        const std::int64_t slot1 = 128LL * kS + 2'120'000'000 + static_cast<std::int64_t>(off1) * 30'000'000;
        CHECK_TRUE(opp == slot1);

        // Périodicité invalide : refusée.
        downlink::ClassBProfile bad = p;
        bad.periodicity = 8;
        CHECK_EQ(static_cast<int>(downlink::next_class_b(bad, {}, 0, opp)),
                 static_cast<int>(DownlinkStatus::InvalidParameter));
    }

    // --- Moteur : classes A, B, C sur le même scénario (uplinks à 0, 60 et 120 s).
    {
        using namespace lsim::sim;
        const auto make = [](downlink::DeviceClass cls, std::uint32_t count, std::int64_t first) {
            EndDeviceSpec d;
            d.position = Position{100.0, 0.0};
            d.spreading_factor = 7;
            d.payload_bytes = 10;
            d.period_ns = 60 * kS;
            d.messages = 3;
            d.downlink.device_class = cls;
            d.downlink.count = count;
            d.downlink.first_request_ns = first;
            d.downlink.request_period_ns = 0;
            return d;
        };
        GatewaySpec gw{};
        PropagationSpec prop{};

        // Classe C : requête à 10 s, hors émission et RX1 → latence nulle.
        {
            EndDeviceSpec devs[1] = {make(downlink::DeviceClass::C, 1, 10 * kS)};
            DeviceStats per[1]{};
            SimulationStats tot{};
            CHECK_EQ(static_cast<int>(simulate_uplinks(devs, 1, gw, prop, per, tot)), 0);
            CHECK_EQ(static_cast<int>(per[0].downlink.requested), 1);
            CHECK_EQ(static_cast<int>(per[0].downlink.delivered), 1);
            CHECK_EQ(static_cast<int>(per[0].downlink.latency_sum_ns), 0);
            CHECK_EQ(static_cast<int>(tot.downlink.requested), 1);
        }
        // Classe A : requête à 10 s, prochain uplink à 60 s → RX1 à 61 s + airtime.
        {
            EndDeviceSpec devs[1] = {make(downlink::DeviceClass::A, 1, 10 * kS)};
            DeviceStats per[1]{};
            SimulationStats tot{};
            CHECK_EQ(static_cast<int>(simulate_uplinks(devs, 1, gw, prop, per, tot)), 0);
            CHECK_EQ(static_cast<int>(per[0].downlink.delivered), 1);
            const auto lat = static_cast<std::int64_t>(per[0].downlink.latency_sum_ns);
            CHECK_TRUE(lat >= 51 * kS && lat < 52 * kS);
        }
        // Classe B : latence exacte jusqu'au slot de la période 0 (74,30 s).
        {
            EndDeviceSpec d = make(downlink::DeviceClass::B, 1, 10 * kS);
            d.downlink.periodicity = 7;
            d.downlink.dev_addr = 0;
            EndDeviceSpec devs[1] = {d};
            DeviceStats per[1]{};
            SimulationStats tot{};
            CHECK_EQ(static_cast<int>(simulate_uplinks(devs, 1, gw, prop, per, tot)), 0);
            CHECK_EQ(static_cast<int>(per[0].downlink.delivered), 1);
            const std::int64_t slot0 = 2'120'000'000 + 2406LL * 30'000'000;
            CHECK_TRUE(static_cast<std::int64_t>(per[0].downlink.latency_sum_ns) == slot0 - 10 * kS);
        }
        // Requêtes après la fin de l'observation : demandées, non livrées.
        {
            EndDeviceSpec devs[1] = {make(downlink::DeviceClass::A, 2, 500 * kS)};
            devs[0].downlink.request_period_ns = kS;
            DeviceStats per[1]{};
            SimulationStats tot{};
            CHECK_EQ(static_cast<int>(simulate_uplinks(devs, 1, gw, prop, per, tot)), 0);
            CHECK_EQ(static_cast<int>(per[0].downlink.requested), 2);
            CHECK_EQ(static_cast<int>(per[0].downlink.delivered), 0);
        }
        // Borne globale : 60 dispositifs × 100 000 requêtes = 6 000 000 > 5 000 000.
        {
            std::vector<EndDeviceSpec> many(60, make(downlink::DeviceClass::A, kMaxDownlinksPerDevice, 0));
            for (auto& d : many) d.downlink.request_period_ns = 1;
            std::vector<DeviceStats> per(many.size());
            SimulationStats tot{};
            CHECK_EQ(static_cast<int>(simulate_uplinks(many.data(), many.size(), gw, prop, per.data(), tot)),
                     static_cast<int>(SimStatus::TooManyDownlinks));
        }
        // Validation : compte excessif, dérive hors plage, classe inconnue.
        {
            EndDeviceSpec devs[1] = {make(downlink::DeviceClass::A, kMaxDownlinksPerDevice + 1, 0)};
            DeviceStats per[1]{};
            SimulationStats tot{};
            CHECK_EQ(static_cast<int>(simulate_uplinks(devs, 1, gw, prop, per, tot)),
                     static_cast<int>(SimStatus::InvalidInput));
            EndDeviceSpec b = make(downlink::DeviceClass::B, 1, 0);
            b.downlink.clock_drift_ppm = 1001;
            EndDeviceSpec devs2[1] = {b};
            CHECK_EQ(static_cast<int>(simulate_uplinks(devs2, 1, gw, prop, per, tot)),
                     static_cast<int>(SimStatus::InvalidInput));
            EndDeviceSpec c = make(downlink::DeviceClass::A, 2, 0);  // period 0 : refusé
            c.downlink.request_period_ns = 0;
            EndDeviceSpec devs3[1] = {c};
            CHECK_EQ(static_cast<int>(simulate_uplinks(devs3, 1, gw, prop, per, tot)),
                     static_cast<int>(SimStatus::InvalidInput));
        }
    }

    // --- API C : même scénario de classe C, plans alignés sur les dispositifs.
    {
        lsim_end_device d{};
        d.x_m = 100.0;
        d.spreading_factor = 7;
        d.payload_bytes = 10;
        d.tx_power_dbm = 14.0;
        d.period_ns = 60 * kS;
        d.messages = 3;
        d.duty_cycle = 1.0;
        lsim_downlink_plan p{};
        p.device_class = 2;
        p.count = 1;
        p.first_request_ns = 10 * kS;
        p.rx_window_ns = kS;
        lsim_gateway g{0.0, 0.0, 0.0, 0.0};
        lsim_propagation pr{868.1e6, 1.0, 2.7, 6.0, 0.0, 0};
        lsim_device_stats per[1]{};
        lsim_sim_stats tot{};
        lsim_downlink_stats dpd[1]{};
        lsim_downlink_stats dtot{};
        CHECK_EQ(lsim_simulate_downlinks_env(&d, &p, 1, &g, &pr, nullptr, per, &tot, dpd, &dtot), 0);
        CHECK_EQ(static_cast<int>(dtot.requested), 1);
        CHECK_EQ(static_cast<int>(dtot.delivered), 1);
        CHECK_EQ(static_cast<int>(dtot.latency_sum_ns), 0);
        // Plans NULL : aucune requête, compteurs de downlink à zéro.
        CHECK_EQ(lsim_simulate_downlinks_env(&d, nullptr, 1, &g, &pr, nullptr, per, &tot, dpd, &dtot), 0);
        CHECK_EQ(static_cast<int>(dtot.requested), 0);
        // Classe inconnue : statut d'entrée invalide.
        p.device_class = 7;
        CHECK_EQ(lsim_simulate_downlinks_env(&d, &p, 1, &g, &pr, nullptr, per, &tot, dpd, &dtot),
                 LSIM_STATUS_SIM_BASE + static_cast<int>(lsim::sim::SimStatus::InvalidInput));
        CHECK_EQ(lsim_simulate_downlinks_env(&d, &p, 1, &g, &pr, nullptr, per, &tot, dpd, nullptr),
                 static_cast<int>(lsim::lora::Status::NullOutput));
    }
}
