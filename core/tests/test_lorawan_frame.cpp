// SPDX-License-Identifier: Apache-2.0
// Tests unitaires : codec de trame LoRaWAN (vecteurs construits à la main,
// aller-retour, rejets défensifs, fuzzing déterministe).
#include <cstdint>
#include <cstring>

#include "check.hpp"
#include "lsim/lorawan_frame.hpp"

namespace {

using namespace lsim::lorawan;

// Trame uplink non confirmée :
// MHDR 0x40 | DevAddr 0x01020304 (LE) | FCtrl 0x00 | FCnt 1 | FPort 1 | "AB" | MIC 11 22 33 44
const std::uint8_t kUplinkVector[] = {0x40, 0x04, 0x03, 0x02, 0x01, 0x00, 0x01, 0x00,
                                      0x01, 0x41, 0x42, 0x11, 0x22, 0x33, 0x44};

void test_decode_known_uplink_vector() {
    DataFrame f;
    const FrameStatus st = decode(kUplinkVector, sizeof kUplinkVector, f);
    CHECK_EQ(static_cast<int>(st), static_cast<int>(FrameStatus::Ok));
    CHECK_EQ(static_cast<int>(f.mtype), static_cast<int>(MType::UnconfirmedDataUp));
    CHECK_EQ(f.dev_addr, std::uint32_t{0x01020304});
    CHECK_EQ(f.fcnt, std::uint16_t{1});
    CHECK_TRUE(f.has_fport);
    CHECK_EQ(f.fport, std::uint8_t{1});
    CHECK_EQ(f.frm_payload_len, std::uint8_t{2});
    CHECK_EQ(f.frm_payload[0], std::uint8_t{0x41});
    CHECK_EQ(f.frm_payload[1], std::uint8_t{0x42});
    CHECK_EQ(f.mic[0], std::uint8_t{0x11});
}

void test_encode_reproduces_known_vector() {
    DataFrame f;
    f.mtype = MType::UnconfirmedDataUp;
    f.dev_addr = 0x01020304u;
    f.fcnt = 1;
    f.has_fport = true;
    f.fport = 1;
    f.frm_payload[0] = 0x41;
    f.frm_payload[1] = 0x42;
    f.frm_payload_len = 2;
    f.mic = {0x11, 0x22, 0x33, 0x44};

    std::uint8_t buf[255];
    std::size_t n = 0;
    const FrameStatus st = encode(f, buf, sizeof buf, n);
    CHECK_EQ(static_cast<int>(st), static_cast<int>(FrameStatus::Ok));
    CHECK_EQ(n, sizeof kUplinkVector);
    CHECK_TRUE(std::memcmp(buf, kUplinkVector, n) == 0);
}

void test_roundtrip_with_all_flags_and_fopts() {
    DataFrame in;
    in.mtype = MType::ConfirmedDataDown;
    in.dev_addr = 0xDEADBEEFu;
    in.adr = true;
    in.ack = true;
    in.f_pending = true;
    in.fcnt = 0xFFFE;
    in.fopts[0] = 0x02;  // LinkCheckAns (exemple)
    in.fopts[1] = 0x03;
    in.fopts_len = 2;
    in.has_fport = true;
    in.fport = 10;
    in.frm_payload_len = 3;
    in.frm_payload[0] = 1;
    in.frm_payload[1] = 2;
    in.frm_payload[2] = 3;
    in.mic = {9, 8, 7, 6};

    std::uint8_t buf[255];
    std::size_t n = 0;
    CHECK_EQ(static_cast<int>(encode(in, buf, sizeof buf, n)), static_cast<int>(FrameStatus::Ok));

    DataFrame out;
    CHECK_EQ(static_cast<int>(decode(buf, n, out)), static_cast<int>(FrameStatus::Ok));
    CHECK_EQ(static_cast<int>(out.mtype), static_cast<int>(MType::ConfirmedDataDown));
    CHECK_EQ(out.dev_addr, in.dev_addr);
    CHECK_TRUE(out.adr && out.ack && out.f_pending);
    CHECK_EQ(out.fcnt, in.fcnt);
    CHECK_EQ(out.fopts_len, std::uint8_t{2});
    CHECK_EQ(out.fopts[1], std::uint8_t{0x03});
    CHECK_EQ(out.fport, std::uint8_t{10});
    CHECK_EQ(out.frm_payload_len, std::uint8_t{3});
    CHECK_EQ(out.mic[3], std::uint8_t{6});
}

void test_max_size_frame_is_255_bytes() {
    DataFrame f;
    f.mtype = MType::UnconfirmedDataDown;
    f.has_fport = true;
    f.fport = 1;
    f.frm_payload_len = static_cast<std::uint8_t>(lsim::lorawan::kMaxFrmPayload);  // 242
    CHECK_EQ(encoded_size(f), std::size_t{255});
    std::uint8_t buf[255];
    std::size_t n = 0;
    CHECK_EQ(static_cast<int>(encode(f, buf, sizeof buf, n)), static_cast<int>(FrameStatus::Ok));
    CHECK_EQ(n, std::size_t{255});
}

void test_encode_rejects_inconsistent_frames() {
    std::uint8_t buf[255];
    std::size_t n = 0;

    DataFrame no_port;
    no_port.mtype = MType::UnconfirmedDataUp;
    no_port.frm_payload_len = 1;  // payload sans FPort
    CHECK_EQ(static_cast<int>(encode(no_port, buf, sizeof buf, n)),
             static_cast<int>(FrameStatus::FieldOutOfRange));

    DataFrame reserved_port;
    reserved_port.mtype = MType::UnconfirmedDataUp;
    reserved_port.has_fport = true;
    reserved_port.fport = 225;  // réservé
    CHECK_EQ(static_cast<int>(encode(reserved_port, buf, sizeof buf, n)),
             static_cast<int>(FrameStatus::FieldOutOfRange));

    // FPort 224 (test MAC, TS001 §4.3.2) est valide ; 225 est le premier port réservé.
    DataFrame test_port;
    test_port.mtype = MType::UnconfirmedDataUp;
    test_port.has_fport = true;
    test_port.fport = 224;
    CHECK_EQ(static_cast<int>(encode(test_port, buf, sizeof buf, n)), static_cast<int>(FrameStatus::Ok));
    DataFrame back;
    CHECK_EQ(static_cast<int>(decode(buf, n, back)), static_cast<int>(FrameStatus::Ok));
    CHECK_EQ(back.fport, std::uint8_t{224});

    DataFrame fopts_on_port0;
    fopts_on_port0.mtype = MType::UnconfirmedDataUp;
    fopts_on_port0.has_fport = true;
    fopts_on_port0.fport = 0;
    fopts_on_port0.fopts_len = 1;
    CHECK_EQ(static_cast<int>(encode(fopts_on_port0, buf, sizeof buf, n)),
             static_cast<int>(FrameStatus::FieldOutOfRange));

    DataFrame wrong_flag;
    wrong_flag.mtype = MType::UnconfirmedDataUp;
    wrong_flag.f_pending = true;  // réservé aux downlinks
    CHECK_EQ(static_cast<int>(encode(wrong_flag, buf, sizeof buf, n)),
             static_cast<int>(FrameStatus::FieldOutOfRange));

    DataFrame not_data;
    not_data.mtype = MType::JoinRequest;
    CHECK_EQ(static_cast<int>(encode(not_data, buf, sizeof buf, n)),
             static_cast<int>(FrameStatus::NotADataFrame));
}

void test_encode_buffer_too_small() {
    DataFrame f;
    f.mtype = MType::UnconfirmedDataUp;
    std::uint8_t buf[11];  // taille minimale = 12
    std::size_t n = 99;
    CHECK_EQ(static_cast<int>(encode(f, buf, sizeof buf, n)), static_cast<int>(FrameStatus::BufferTooSmall));
    CHECK_EQ(n, std::size_t{0});
}

void test_decode_rejects_malformed_inputs() {
    DataFrame f;
    // Trop courte.
    CHECK_EQ(static_cast<int>(decode(kUplinkVector, 11, f)), static_cast<int>(FrameStatus::MalformedFrame));
    // Version majeure inconnue.
    std::uint8_t bad_major[15];
    std::memcpy(bad_major, kUplinkVector, sizeof bad_major);
    bad_major[0] = 0x41;
    CHECK_EQ(static_cast<int>(decode(bad_major, 15, f)), static_cast<int>(FrameStatus::UnsupportedMajorVersion));
    // JoinRequest : pas une trame de données ici.
    std::uint8_t join[15];
    std::memcpy(join, kUplinkVector, sizeof join);
    join[0] = 0x00;
    CHECK_EQ(static_cast<int>(decode(join, 15, f)), static_cast<int>(FrameStatus::NotADataFrame));
    // FOptsLen = 15 incohérent avec une trame de 15 octets.
    std::uint8_t big_fopts[15];
    std::memcpy(big_fopts, kUplinkVector, sizeof big_fopts);
    big_fopts[5] = 0x0F;
    CHECK_EQ(static_cast<int>(decode(big_fopts, 15, f)), static_cast<int>(FrameStatus::MalformedFrame));
    // Pointeur nul.
    CHECK_EQ(static_cast<int>(decode(nullptr, 15, f)), static_cast<int>(FrameStatus::MalformedFrame));
}

// Fuzzing déterministe : aucune entrée aléatoire ne doit provoquer de lecture
// hors bornes (vérifié avec -fsanitize=address dans la CI sanitizer).
void test_fuzz_decode_never_crashes() {
    std::uint32_t seed = 0x12345678u;
    std::uint8_t buf[255];
    DataFrame f;
    for (int iter = 0; iter < 20000; ++iter) {
        seed = seed * 1664525u + 1013904223u;
        const std::size_t len = seed % 256u;
        for (std::size_t i = 0; i < len; ++i) {
            seed = seed * 1664525u + 1013904223u;
            buf[i] = static_cast<std::uint8_t>(seed >> 24);
        }
        const FrameStatus st = decode(buf, len, f);
        if (st == FrameStatus::Ok) {
            // Toute trame décodée doit se ré-encoder à l'identique (hors MIC inclus).
            std::uint8_t out[255];
            std::size_t n = 0;
            CHECK_EQ(static_cast<int>(encode(f, out, sizeof out, n)), static_cast<int>(FrameStatus::Ok));
            CHECK_EQ(n, len);
            CHECK_TRUE(std::memcmp(out, buf, len) == 0);
        }
    }
}

}  // namespace

void run_lorawan_frame_tests() {
    test_decode_known_uplink_vector();
    test_encode_reproduces_known_vector();
    test_roundtrip_with_all_flags_and_fopts();
    test_max_size_frame_is_255_bytes();
    test_encode_rejects_inconsistent_frames();
    test_encode_buffer_too_small();
    test_decode_rejects_malformed_inputs();
    test_fuzz_decode_never_crashes();
}
