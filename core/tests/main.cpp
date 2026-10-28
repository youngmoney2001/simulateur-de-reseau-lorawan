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
void run_c_api_tests();
void run_join_tests();
void run_environment_tests();
void run_mac_commands_tests();

int main() {
    run_lora_phy_tests();
    run_link_budget_tests();
    run_lorawan_frame_tests();
    run_crypto_tests();
    run_secure_frame_tests();
    run_engine_tests();
    run_c_api_tests();
    run_join_tests();
    run_environment_tests();
    run_mac_commands_tests();
    std::printf("%d/%d vérifications réussies\n", lsim::test::checks() - lsim::test::failures(),
                lsim::test::checks());
    return lsim::test::failures() == 0 ? 0 : 1;
}
