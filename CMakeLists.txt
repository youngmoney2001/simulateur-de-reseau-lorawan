cmake_minimum_required(VERSION 3.20)
project(lsim VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

option(LSIM_WARNINGS_AS_ERRORS "Traiter les avertissements comme des erreurs" ON)
option(LSIM_BUILD_TESTS "Construire les tests C++" ON)

add_library(lsim_core SHARED
    core/src/lora_phy.cpp
    core/src/c_api.cpp
    core/src/lora_sensitivity.cpp
    core/src/link_budget.cpp
    core/src/lorawan_frame.cpp
)
target_include_directories(lsim_core PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/core/include)
target_compile_options(lsim_core PRIVATE -Wall -Wextra -Wpedantic -Wconversion -fvisibility=hidden)
if(LSIM_WARNINGS_AS_ERRORS)
    target_compile_options(lsim_core PRIVATE -Werror)
endif()
set_target_properties(lsim_core PROPERTIES POSITION_INDEPENDENT_CODE ON)

if(LSIM_BUILD_TESTS)
    enable_testing()
    add_executable(lsim_tests
        core/tests/main.cpp
        core/tests/test_lora_phy.cpp
        core/tests/test_link_budget.cpp
        core/tests/test_lorawan_frame.cpp
    )
    target_link_libraries(lsim_tests PRIVATE lsim_core)
    target_compile_options(lsim_tests PRIVATE -Wall -Wextra -Wpedantic)
    add_test(NAME core_unit_tests COMMAND lsim_tests)
endif()
