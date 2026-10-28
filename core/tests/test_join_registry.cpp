// SPDX-License-Identifier: Apache-2.0
// Registre serveur : rejeu de join-request et de rejoin, MIC forgé sans effet d'état,
// reset de RJcount0 au join-accept, capacité bornée.
#include <array>
#include <cstdint>
#include <cstring>

#include "check.hpp"
#include "lsim/join.hpp"
#include "lsim/join_registry.hpp"
#include "lsim/rejoin.hpp"

namespace {

using namespace lsim::lorawan;
using lsim::crypto::Key128;
using Eui = std::array<std::uint8_t, 8>;

Key128 key_of(std::uint8_t b) {
    Key128 k{};
    k.fill(b);
    return k;
}

// Join-request signée avec `nwk` ; DevNonce en ordre de transmission.
std::array<std::uint8_t, kJoinRequestSize> join_request(const Key128& nwk, std::uint16_t nonce,
                                                        std::uint8_t dev_byte) {
    JoinRequestFields f;
    f.join_eui = {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08};
    f.dev_eui = Eui{dev_byte, 0, 0, 0, 0, 0, 0, 0};
    f.dev_nonce = {static_cast<std::uint8_t>(nonce & 0xFF), static_cast<std::uint8_t>(nonce >> 8)};
    std::array<std::uint8_t, kJoinRequestSize> out{};
    std::size_t n = 0;
    const JoinStatus st = encode_join_request(f, nwk, out.data(), out.size(), n);
    CHECK_TRUE(st == JoinStatus::Ok);
    return out;
}

Rejoin02Fields rejoin02(std::uint8_t dev_byte, std::uint16_t count) {
    Rejoin02Fields f;
    f.rejoin_type = 0;
    f.net_id = {0x13, 0x00, 0x00};
    f.dev_eui = Eui{dev_byte, 0, 0, 0, 0, 0, 0, 0};
    f.rjcount0 = count;
    return f;
}

}  // namespace

void run_join_registry_tests() {
    const Key128 nwk = key_of(0x01);

    // --- Join-request : DevNonce strictement croissant.
    {
        JoinRegistry reg;
        JoinRequestFields out;
        auto m1 = join_request(nwk, 1, 0xA1);
        CHECK_EQ(static_cast<int>(reg.accept_join_request(m1.data(), m1.size(), nwk, out)),
                 static_cast<int>(RegistryStatus::Ok));
        CHECK_EQ(static_cast<int>(reg.accept_join_request(m1.data(), m1.size(), nwk, out)),
                 static_cast<int>(RegistryStatus::Replayed));
        auto m0 = join_request(nwk, 0, 0xA1);
        CHECK_EQ(static_cast<int>(reg.accept_join_request(m0.data(), m0.size(), nwk, out)),
                 static_cast<int>(RegistryStatus::Replayed));
        auto m2 = join_request(nwk, 2, 0xA1);
        CHECK_EQ(static_cast<int>(reg.accept_join_request(m2.data(), m2.size(), nwk, out)),
                 static_cast<int>(RegistryStatus::Ok));
        CHECK_EQ(reg.device_count(), std::size_t{1});
    }
    // --- MIC forgé : rejeté, et aucune entrée créée (pas de consommation mémoire).
    {
        JoinRegistry reg;
        JoinRequestFields out;
        auto m = join_request(nwk, 7, 0xB2);
        m[m.size() - 1] ^= 0x01;
        CHECK_EQ(static_cast<int>(reg.accept_join_request(m.data(), m.size(), nwk, out)),
                 static_cast<int>(RegistryStatus::MicMismatch));
        CHECK_EQ(reg.device_count(), std::size_t{0});
        // Le vrai message ensuite : toujours accepté (le forgé n'a rien consommé).
        auto good = join_request(nwk, 7, 0xB2);
        CHECK_EQ(static_cast<int>(reg.accept_join_request(good.data(), good.size(), nwk, out)),
                 static_cast<int>(RegistryStatus::Ok));
    }
    // --- Rejoin type 0/2 : RJcount0 croissant, MIC forgé sans effet.
    {
        JoinRegistry reg;
        Rejoin02Fields out;
        std::uint8_t wire[kRejoin02Size];
        std::size_t n = 0;
        const Key128 s = key_of(0x02);
        CHECK_EQ(static_cast<int>(encode_rejoin_02(rejoin02(0xC3, 5), s, wire, sizeof wire, n)),
                 static_cast<int>(RejoinStatus::Ok));
        CHECK_EQ(static_cast<int>(reg.accept_rejoin_02(wire, n, s, out)), static_cast<int>(RegistryStatus::Ok));
        CHECK_EQ(static_cast<int>(reg.accept_rejoin_02(wire, n, s, out)), static_cast<int>(RegistryStatus::Replayed));

        std::uint8_t forged[kRejoin02Size];
        std::memcpy(forged, wire, sizeof forged);
        forged[13] = 9;  // RJcount0 altéré : MIC faux
        CHECK_EQ(static_cast<int>(reg.accept_rejoin_02(forged, n, s, out)),
                 static_cast<int>(RegistryStatus::MicMismatch));
        // RJcount0 = 9 authentique : toujours accepté (le forgé n'a pas avancé le compteur).
        std::uint8_t ok9[kRejoin02Size];
        CHECK_EQ(static_cast<int>(encode_rejoin_02(rejoin02(0xC3, 9), s, ok9, sizeof ok9, n)),
                 static_cast<int>(RejoinStatus::Ok));
        CHECK_EQ(static_cast<int>(reg.accept_rejoin_02(ok9, n, s, out)), static_cast<int>(RegistryStatus::Ok));
        // Join-accept traité : RJcount0 repart à zéro.
        reg.on_join_accepted(Eui{0xC3, 0, 0, 0, 0, 0, 0, 0});
        std::uint8_t zero[kRejoin02Size];
        CHECK_EQ(static_cast<int>(encode_rejoin_02(rejoin02(0xC3, 0), s, zero, sizeof zero, n)),
                 static_cast<int>(RejoinStatus::Ok));
        CHECK_EQ(static_cast<int>(reg.accept_rejoin_02(zero, n, s, out)), static_cast<int>(RegistryStatus::Ok));
    }
    // --- Rejoin type 1 : clé JSIntKey, compteur RJcount1 par (JoinEUI, DevEUI).
    {
        JoinRegistry reg;
        Rejoin1Fields out;
        const Key128 js = key_of(0x03);
        Rejoin1Fields f;
        f.join_eui = {0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88};
        f.dev_eui = Eui{0xD4, 0, 0, 0, 0, 0, 0, 0};
        f.rjcount1 = 3;
        std::uint8_t wire[kRejoin1Size];
        std::size_t n = 0;
        CHECK_EQ(static_cast<int>(encode_rejoin_1(f, js, wire, sizeof wire, n)), static_cast<int>(RejoinStatus::Ok));
        CHECK_EQ(static_cast<int>(reg.accept_rejoin_1(wire, n, js, out)), static_cast<int>(RegistryStatus::Ok));
        CHECK_EQ(static_cast<int>(reg.accept_rejoin_1(wire, n, js, out)), static_cast<int>(RegistryStatus::Replayed));
        CHECK_EQ(static_cast<int>(reg.accept_rejoin_1(wire, n, key_of(0x04), out)),
                 static_cast<int>(RegistryStatus::MicMismatch));
    }
    // --- Capacité bornée : nouveau dispositif refusé, existant toujours servi.
    {
        JoinRegistry reg(1);
        JoinRequestFields out;
        auto a = join_request(nwk, 1, 0xE1);
        auto b = join_request(nwk, 1, 0xE2);
        CHECK_EQ(static_cast<int>(reg.accept_join_request(a.data(), a.size(), nwk, out)),
                 static_cast<int>(RegistryStatus::Ok));
        CHECK_EQ(static_cast<int>(reg.accept_join_request(b.data(), b.size(), nwk, out)),
                 static_cast<int>(RegistryStatus::CapacityExceeded));
        CHECK_EQ(reg.device_count(), std::size_t{1});
        auto a2 = join_request(nwk, 2, 0xE1);
        CHECK_EQ(static_cast<int>(reg.accept_join_request(a2.data(), a2.size(), nwk, out)),
                 static_cast<int>(RegistryStatus::Ok));
    }
}
