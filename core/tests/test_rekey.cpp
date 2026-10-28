// SPDX-License-Identifier: Apache-2.0
// Rekey : machine d'état dispositif (RekeyInd / RekeyConf, retour à Join) et serveur (rejet).
#include <cstdint>

#include "check.hpp"
#include "lsim/c_api.h"
#include "lsim/lora_phy.hpp"
#include "lsim/rekey.hpp"

using namespace lsim::lorawan::rekey;

void run_rekey_tests() {
    // --- Dispositif : pas de RekeyConf -> NeedsJoin après LIMIT uplinks.
    {
        DeviceRekey d;
        CHECK_TRUE(!device_must_send_rekey_ind(d));
        device_join_accepted(d);
        CHECK_TRUE(device_must_send_rekey_ind(d));
        for (int i = 0; i < 3; ++i) device_uplink_completed(d, 3, false, 0);
        CHECK_TRUE(d.state == DeviceState::NeedsJoin);
        CHECK_TRUE(!device_must_send_rekey_ind(d));
        // État terminal : un RekeyConf tardif n'y change rien.
        device_uplink_completed(d, 3, true, 1);
        CHECK_TRUE(d.state == DeviceState::NeedsJoin);
    }
    // --- Dispositif : RekeyConf version invalide (0 ou 2) ignoré, version 1 confirme.
    {
        DeviceRekey d;
        device_join_accepted(d);
        device_uplink_completed(d, 64, true, 0);
        CHECK_TRUE(d.state == DeviceState::Pending);
        device_uplink_completed(d, 64, true, 2);
        CHECK_TRUE(d.state == DeviceState::Pending);
        device_uplink_completed(d, 64, true, 1);
        CHECK_TRUE(d.state == DeviceState::Confirmed);
        CHECK_TRUE(!device_must_send_rekey_ind(d));
        CHECK_EQ(static_cast<int>(d.uplinks), 2);
    }
    // --- Serveur : trames du nouveau contexte rejetées avant le premier RekeyInd.
    {
        ServerRekey s;
        CHECK_TRUE(server_on_uplink(s, true, false) == ServerAction::Accept);  // pas de join-accept : hors cas
        server_join_accepted(s);
        CHECK_TRUE(server_on_uplink(s, true, false) == ServerAction::Discard);
        CHECK_TRUE(server_on_uplink(s, true, true) == ServerAction::AcceptAndConfirm);
        // RekeyInd ultérieur : trame acceptée, pas de nouvelle confirmation.
        CHECK_TRUE(server_on_uplink(s, true, true) == ServerAction::Accept);
        // Ancien contexte : jamais rejeté par cette règle.
        ServerRekey t;
        server_join_accepted(t);
        CHECK_TRUE(server_on_uplink(t, false, false) == ServerAction::Accept);
        CHECK_TRUE(t.awaiting);
    }
    // --- API C : même machine d'état, états passés par l'appelant.
    {
        lsim_rekey_device cd{};
        CHECK_EQ(lsim_rekey_device_join_accepted(&cd), 0);
        CHECK_EQ(static_cast<int>(cd.state), 1);
        uint8_t need = 0;
        CHECK_EQ(lsim_rekey_device_must_send_rekey_ind(&cd, &need), 0);
        CHECK_EQ(static_cast<int>(need), 1);
        CHECK_EQ(lsim_rekey_device_uplink_completed(&cd, 64, 1, 1), 0);
        CHECK_EQ(static_cast<int>(cd.state), 2);
        lsim_rekey_server cs{};
        CHECK_EQ(lsim_rekey_server_join_accepted(&cs), 0);
        uint8_t action = 0xFF;
        CHECK_EQ(lsim_rekey_server_on_uplink(&cs, 1, 0, &action), 0);
        CHECK_EQ(static_cast<int>(action), 2);
        CHECK_EQ(lsim_rekey_server_on_uplink(&cs, 1, 1, &action), 0);
        CHECK_EQ(static_cast<int>(action), 1);
        CHECK_EQ(lsim_rekey_server_on_uplink(nullptr, 1, 1, &action), static_cast<int>(lsim::lora::Status::NullOutput));
    }
}
