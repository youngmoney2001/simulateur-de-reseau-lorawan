// SPDX-License-Identifier: Apache-2.0
// Primitives en temps constant. Utilisées pour toute comparaison de secret ou de MIC.
#pragma once

#include <cstddef>
#include <cstdint>

namespace lsim {

// Comparaison sans arrêt anticipé : le temps ne dépend pas du contenu.
inline bool constant_time_equal(const std::uint8_t* a, const std::uint8_t* b, std::size_t n) {
    std::uint8_t diff = 0;
    for (std::size_t i = 0; i < n; ++i) {
        diff = static_cast<std::uint8_t>(diff | (a[i] ^ b[i]));
    }
    return diff == 0;
}

}  // namespace lsim
