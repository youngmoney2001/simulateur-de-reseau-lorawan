// SPDX-License-Identifier: Apache-2.0
// Point d'entrée des tests C++ : exécute chaque suite et renvoie un code de sortie.
#include <cstdio>

#include "check.hpp"

void run_lora_phy_tests();
void run_link_budget_tests();
void run_lorawan_frame_tests();
void run_crypto_tests();
void run_secure_frame_tests();
void run_engine_tests();
void run_closed_loop_tests();
void run_loop_adr_tests();
void run_c_api_tests();
void run_join_tests();
void run_environment_tests();
void run_mac_commands_tests();
void run_rejoin_tests();
void run_join_registry_tests();
void run_adr_tests();
void run_rekey_tests();
void run_session_tests();
void run_class_b_tests();
void run_downlink_tests();
void run_downlink_plan_tests();
void run_materials_tests();
void run_energy_tests();
void run_mesh_tests();
void run_abi_v3_prep_tests();
void run_channel_config_v3_tests();
void run_closed_loop_v3_buffers_tests();
void run_closed_loop_v3_crossval_tests();
void run_closed_loop_v3_api_tests();
void run_rf_frontend_tests();

int main() {
    run_lora_phy_tests();
    run_materials_tests();
    run_energy_tests();
    run_mesh_tests();
    run_abi_v3_prep_tests();
    run_channel_config_v3_tests();
    run_closed_loop_v3_buffers_tests();
    run_closed_loop_v3_crossval_tests();
    run_closed_loop_v3_api_tests();
    run_rf_frontend_tests();
    run_link_budget_tests();
    run_lorawan_frame_tests();
    run_crypto_tests();
    run_secure_frame_tests();
    run_engine_tests();
    run_closed_loop_tests();
    run_loop_adr_tests();
    run_c_api_tests();
    run_join_tests();
    run_environment_tests();
    run_mac_commands_tests();
    run_rejoin_tests();
    run_join_registry_tests();
    run_adr_tests();
    run_rekey_tests();
    run_session_tests();
    run_class_b_tests();
    run_downlink_tests();
    run_downlink_plan_tests();
    std::printf("%d/%d vérifications réussies\n", lsim::test::checks() - lsim::test::failures(),
                lsim::test::checks());
    return lsim::test::failures() == 0 ? 0 : 1;
}
