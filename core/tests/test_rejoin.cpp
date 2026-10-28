// SPDX-License-Identifier: Apache-2.0
// Rejoin-request 1.1 : vecteurs CMAC calculés hors du code (bibliothèque cryptography,
// AES-CMAC RFC 4493), rejets (MIC, clé, type, MHDR) et garde anti-rejeu.
#include <array>
#include <cstdint>
#include <cstring>

#include "check.hpp"
#include "lsim/rejoin.hpp"

namespace {

using namespace lsim::lorawan;
using lsim::crypto::Key128;

// Clé RFC 4493 : sert ici de SNwkSIntKey / JSIntKey de test.
Key128 test_key() {
    return Key128{0x2b, 0x7e, 0x15, 0x16, 0x28, 0xae, 0xd2, 0xa6,
                  0xab, 0xf7, 0x15, 0x88, 0x09, 0xcf, 0x4f, 0x3c};
}

}  // namespace

void run_rejoin_tests() {
    const Key128 key = test_key();

    // --- Type 0 : vecteur de référence (MIC a6d032e8).
    {
        Rejoin02Fields f;
        f.rejoin_type = 0;
        f.net_id = {0x13, 0x00, 0x00};
        f.dev_eui = {0x08, 0x07, 0x06, 0x05, 0x04, 0x03, 0x02, 0x01};
        f.rjcount0 = 5;
        std::uint8_t out[kRejoin02Size] = {};
        std::size_t n = 0;
        CHECK_EQ(static_cast<int>(encode_rejoin_02(f, key, out, sizeof out, n)), static_cast<int>(RejoinStatus::Ok));
        CHECK_EQ(n, kRejoin02Size);
        const std::uint8_t expected[kRejoin02Size] = {0xC0, 0x00, 0x13, 0x00, 0x00, 0x08, 0x07, 0x06, 0x05, 0x04,
                                                      0x03, 0x02, 0x01, 0x05, 0x00, 0xA6, 0xD0, 0x32, 0xE8};
        for (std::size_t i = 0; i < kRejoin02Size; ++i) CHECK_EQ(out[i], expected[i]);

        Rejoin02Fields back;
        CHECK_EQ(static_cast<int>(decode_rejoin_02(out, n, key, back)), static_cast<int>(RejoinStatus::Ok));
        CHECK_EQ(back.rjcount0, std::uint16_t{5});
        CHECK_EQ(back.rejoin_type, std::uint8_t{0});
        CHECK_TRUE(back.dev_eui == f.dev_eui);

        // MIC altéré d'un bit : rejeté, champs non exposés.
        std::uint8_t bad[kRejoin02Size];
        std::memcpy(bad, out, sizeof bad);
        bad[18] ^= 0x01;
        Rejoin02Fields none;
        CHECK_EQ(static_cast<int>(decode_rejoin_02(bad, n, key, none)), static_cast<int>(RejoinStatus::MicMismatch));
        CHECK_EQ(none.rjcount0, std::uint16_t{0});
        // RJcount0 altéré : le MIC le couvre aussi.
        bad[18] ^= 0x01;
        bad[13] ^= 0x01;
        CHECK_EQ(static_cast<int>(decode_rejoin_02(bad, n, key, none)), static_cast<int>(RejoinStatus::MicMismatch));
        // Mauvaise clé.
        Key128 other = key;
        other[0] ^= 0xFF;
        CHECK_EQ(static_cast<int>(decode_rejoin_02(out, n, other, none)), static_cast<int>(RejoinStatus::MicMismatch));
    }
    // --- Type 2 : même format, type différent couvert par le MIC.
    {
        Rejoin02Fields f;
        f.rejoin_type = 2;
        f.net_id = {0x13, 0x00, 0x00};
        f.dev_eui = {0x08, 0x07, 0x06, 0x05, 0x04, 0x03, 0x02, 0x01};
        f.rjcount0 = 5;
        std::uint8_t out[kRejoin02Size];
        std::size_t n = 0;
        CHECK_EQ(static_cast<int>(encode_rejoin_02(f, key, out, sizeof out, n)), static_cast<int>(RejoinStatus::Ok));
        CHECK_TRUE(out[18] != 0xE8 || out[15] != 0xA6);  // le type 2 change le MIC
        // Un message type 2 falsifié en type 0 : MIC rejeté.
        out[1] = 0x00;
        Rejoin02Fields back;
        CHECK_EQ(static_cast<int>(decode_rejoin_02(out, n, key, back)), static_cast<int>(RejoinStatus::MicMismatch));
    }
    // --- Type 1 : vecteur de référence (MIC 62acc0c3), clé JSIntKey.
    {
        Rejoin1Fields f;
        f.join_eui = {0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88};
        f.dev_eui = {0x08, 0x07, 0x06, 0x05, 0x04, 0x03, 0x02, 0x01};
        f.rjcount1 = 0x0102;
        std::uint8_t out[kRejoin1Size];
        std::size_t n = 0;
        CHECK_EQ(static_cast<int>(encode_rejoin_1(f, key, out, sizeof out, n)), static_cast<int>(RejoinStatus::Ok));
        CHECK_EQ(n, kRejoin1Size);
        const std::uint8_t expected_tail[4] = {0x62, 0xAC, 0xC0, 0xC3};
        for (std::size_t i = 0; i < 4; ++i) CHECK_EQ(out[20 + i], expected_tail[i]);
        CHECK_EQ(out[18], std::uint8_t{0x02});
        CHECK_EQ(out[19], std::uint8_t{0x01});

        Rejoin1Fields back;
        CHECK_EQ(static_cast<int>(decode_rejoin_1(out, n, key, back)), static_cast<int>(RejoinStatus::Ok));
        CHECK_EQ(back.rjcount1, std::uint16_t{0x0102});
        // Type 1 vérifié avec la mauvaise clé (SNwkSIntKey au lieu de JSIntKey) : rejeté.
        Key128 other = key;
        other[15] ^= 0x01;
        CHECK_EQ(static_cast<int>(decode_rejoin_1(out, n, other, back)), static_cast<int>(RejoinStatus::MicMismatch));
        // Tampon trop petit.
        CHECK_EQ(static_cast<int>(encode_rejoin_1(f, key, out, 23, n)), static_cast<int>(RejoinStatus::BufferTooSmall));
    }
    // --- Rejets structurels avant tout calcul.
    {
        std::uint8_t buf[kRejoin1Size] = {};
        std::uint8_t t = 0;
        CHECK_EQ(static_cast<int>(peek_rejoin_type(buf, kRejoin1Size, t)), static_cast<int>(RejoinStatus::InvalidMHDR));
        buf[0] = kMhdrRejoinRequest;
        buf[1] = 3;
        CHECK_EQ(static_cast<int>(peek_rejoin_type(buf, kRejoin1Size, t)), static_cast<int>(RejoinStatus::InvalidType));
        buf[1] = 1;
        CHECK_EQ(static_cast<int>(peek_rejoin_type(buf, kRejoin1Size, t)), static_cast<int>(RejoinStatus::Ok));
        CHECK_EQ(t, std::uint8_t{1});
        Rejoin02Fields f;
        CHECK_EQ(static_cast<int>(decode_rejoin_02(buf, kRejoin02Size, test_key(), f)),
                 static_cast<int>(RejoinStatus::InvalidType));  // type 1 passé au décodeur 0/2
        CHECK_EQ(static_cast<int>(decode_rejoin_02(buf, 18, test_key(), f)), static_cast<int>(RejoinStatus::InvalidLength));
        Rejoin1Fields g;
        CHECK_EQ(static_cast<int>(decode_rejoin_1(buf, 23, test_key(), g)), static_cast<int>(RejoinStatus::InvalidLength));
    }
    // --- Garde anti-rejeu : strictement croissant, enregistrement après MIC seulement.
    {
        Counter16Guard g;
        CHECK_TRUE(g.is_fresh(0));  // premier message après jointure : tout est frais
        g.record(0);
        CHECK_TRUE(!g.is_fresh(0));  // rejeu
        CHECK_TRUE(g.is_fresh(1));
        g.record(7);
        CHECK_TRUE(!g.is_fresh(5));
        CHECK_TRUE(!g.is_fresh(7));
        CHECK_TRUE(g.is_fresh(8));
        CHECK_TRUE(g.is_fresh(0xFFFF));
        g.reset();  // nouvelle session
        CHECK_TRUE(g.is_fresh(0));
    }
}
