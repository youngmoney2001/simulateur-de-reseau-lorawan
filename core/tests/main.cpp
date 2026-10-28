// SPDX-License-Identifier: Apache-2.0
// Point d'entrée des tests C++ : exécute chaque suite et renvoie un code de sortie.
#include <cstdio>

#include "check.hpp"

void run_lora_phy_tests();
void run_link_budget_tests();
void run_lorawan_frame_tests();
void run_crypto_tests();

int main() {
    run_lora_phy_tests();
    run_link_budget_tests();
    run_lorawan_frame_tests();
    run_crypto_tests();
    std::printf("%d/%d vérifications réussies\n", lsim::test::checks() - lsim::test::failures(),
                lsim::test::checks());
    return lsim::test::failures() == 0 ? 0 : 1;
}
