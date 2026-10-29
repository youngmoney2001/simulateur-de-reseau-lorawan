cmake_minimum_required(VERSION 3.20)
project(lsim VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

option(LSIM_WARNINGS_AS_ERRORS "Traiter les avertissements comme des erreurs" ON)
option(LSIM_BUILD_TESTS "Construire les tests C++" ON)

# Primitives cryptographiques : mbedTLS (Apache-2.0), version épinglée par SHA.
# Seule la bibliothèque mbedcrypto est construite (ni programmes, ni tests).
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
set(ENABLE_PROGRAMS OFF CACHE BOOL "" FORCE)
set(ENABLE_TESTING OFF CACHE BOOL "" FORCE)
set(MBEDTLS_FATAL_WARNINGS OFF CACHE BOOL "" FORCE)
include(FetchContent)
FetchContent_Declare(mbedtls
    GIT_REPOSITORY https://github.com/Mbed-TLS/mbedtls.git
    GIT_TAG c765c831e5c2a0971410692f92f7a81d6ec65ec2  # v3.6.4
    GIT_SHALLOW TRUE
    GIT_SUBMODULES framework
)
FetchContent_MakeAvailable(mbedtls)

# Sources du cœur, compilées une seule fois.
add_library(lsim_objects OBJECT
    core/src/lora_phy.cpp
    core/src/c_api.cpp
    core/src/lora_sensitivity.cpp
    core/src/materials.cpp
    core/src/energy.cpp
    core/src/link_budget.cpp
    core/src/lorawan_frame.cpp
    core/src/crypto.cpp
    core/src/lorawan_keys.cpp
    core/src/secure_frame.cpp
    core/src/engine.cpp
    core/src/c_api_ext.cpp
    core/src/join.cpp
    core/src/mac_commands.cpp
    core/src/c_api_mac.cpp
    core/src/rejoin.cpp
    core/src/c_api_rejoin.cpp
    core/src/join_registry.cpp
    core/src/c_api_registry.cpp
    core/src/adr.cpp
    core/src/c_api_adr.cpp
    core/src/rekey.cpp
    core/src/c_api_rekey.cpp
    core/src/session.cpp
    core/src/c_api_session.cpp
    core/src/class_b.cpp
    core/src/downlink.cpp
    core/src/downlink_plan.cpp
    core/src/c_api_plan.cpp
    core/src/c_api_class_b.cpp
    core/src/environment.cpp
    core/src/mesh.cpp
    core/src/c_api_mesh.cpp
)
target_include_directories(lsim_objects PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/core/include)
target_link_libraries(lsim_objects PRIVATE mbedcrypto)
target_compile_options(lsim_objects PRIVATE -Wall -Wextra -Wpedantic -Wconversion -fvisibility=hidden)
if(LSIM_WARNINGS_AS_ERRORS)
    target_compile_options(lsim_objects PRIVATE -Werror)
endif()
set_target_properties(lsim_objects PROPERTIES POSITION_INDEPENDENT_CODE ON)

# Bibliothèque publique : seuls les symboles lsim_* (API C) sont exportés.
add_library(lsim_core SHARED $<TARGET_OBJECTS:lsim_objects>)
target_link_libraries(lsim_core PRIVATE mbedcrypto)
if(CMAKE_SYSTEM_NAME STREQUAL "Linux")
    target_link_options(lsim_core PRIVATE "LINKER:--version-script=${CMAKE_CURRENT_SOURCE_DIR}/core/exports.map")
endif()

if(LSIM_BUILD_TESTS)
    enable_testing()
    # Les tests liaient les objets directement : ils accèdent à l'API C++ interne.
    add_executable(lsim_tests
        $<TARGET_OBJECTS:lsim_objects>
        core/tests/main.cpp
        core/tests/test_lora_phy.cpp
        core/tests/test_link_budget.cpp
        core/tests/test_lorawan_frame.cpp
        core/tests/test_crypto.cpp
        core/tests/test_secure_frame.cpp
        core/tests/test_engine.cpp
        core/tests/test_closed_loop.cpp
        core/tests/test_c_api.cpp
        core/tests/test_join.cpp
        core/tests/test_mac_commands.cpp
        core/tests/test_rejoin.cpp
        core/tests/test_join_registry.cpp
        core/tests/test_adr.cpp
        core/tests/test_rekey.cpp
        core/tests/test_session.cpp
        core/tests/test_class_b.cpp
        core/tests/test_downlink.cpp
        core/tests/test_downlink_plan.cpp
        core/tests/test_environment.cpp
        core/tests/test_materials.cpp
        core/tests/test_energy.cpp
        core/tests/test_mesh.cpp
    )
    target_link_libraries(lsim_tests PRIVATE mbedcrypto)
    target_compile_options(lsim_tests PRIVATE -Wall -Wextra -Wpedantic)
    target_include_directories(lsim_tests PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/core/include)
    add_test(NAME core_unit_tests COMMAND lsim_tests)
endif()
