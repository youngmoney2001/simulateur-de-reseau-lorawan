// SPDX-License-Identifier: Apache-2.0
// Harnais de test minimal, sans dépendance externe.
#pragma once

#include <cmath>
#include <cstdio>

namespace lsim::test {

inline int& failures() { static int f = 0; return f; }
inline int& checks() { static int c = 0; return c; }

inline void report(const char* file, int line, const char* expr, long long got, long long want) {
    ++failures();
    std::fprintf(stderr, "FAIL %s:%d: %s (obtenu %lld, attendu %lld)\n", file, line, expr, got, want);
}

inline void report_bool(const char* file, int line, const char* expr) {
    ++failures();
    std::fprintf(stderr, "FAIL %s:%d: %s\n", file, line, expr);
}

}  // namespace lsim::test

#define CHECK_EQ(actual, expected)                                                    \
    do {                                                                              \
        ++::lsim::test::checks();                                                     \
        const auto a_ = (actual);                                                     \
        const auto e_ = (expected);                                                   \
        if (!(a_ == e_)) {                                                            \
            ::lsim::test::report(__FILE__, __LINE__, #actual " == " #expected,        \
                                 static_cast<long long>(a_), static_cast<long long>(e_)); \
        }                                                                             \
    } while (0)

#define CHECK_TRUE(cond)                                                              \
    do {                                                                              \
        ++::lsim::test::checks();                                                     \
        if (!(cond)) {                                                                \
            ::lsim::test::report_bool(__FILE__, __LINE__, #cond);                     \
        }                                                                             \
    } while (0)

#define CHECK_NEAR(actual, expected, tol)                                             \
    do {                                                                              \
        ++::lsim::test::checks();                                                     \
        const double a_ = (actual);                                                   \
        const double e_ = (expected);                                                 \
        if (!(std::fabs(a_ - e_) <= (tol))) {                                         \
            ::lsim::test::report_bool(__FILE__, __LINE__, #actual " ~= " #expected);  \
        }                                                                             \
    } while (0)
