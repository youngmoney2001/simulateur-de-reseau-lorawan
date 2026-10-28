// SPDX-License-Identifier: Apache-2.0
#include "lsim/class_b.hpp"

#include <array>

#include "lsim/crypto.hpp"

namespace lsim::lorawan::classb {

namespace {

constexpr std::size_t kTimeLen = 4;
constexpr std::size_t kCrcLen = 2;

void put_le32(std::uint8_t* p, std::uint32_t v) {
    p[0] = static_cast<std::uint8_t>(v);
    p[1] = static_cast<std::uint8_t>(v >> 8);
    p[2] = static_cast<std::uint8_t>(v >> 16);
    p[3] = static_cast<std::uint8_t>(v >> 24);
}

std::uint32_t get_le32(const std::uint8_t* p) {
    return static_cast<std::uint32_t>(p[0]) | (static_cast<std::uint32_t>(p[1]) << 8) |
           (static_cast<std::uint32_t>(p[2]) << 16) | (static_cast<std::uint32_t>(p[3]) << 24);
}

}  // namespace

std::uint16_t beacon_crc16(const std::uint8_t* data, std::size_t len) {
    std::uint16_t crc = 0;
    for (std::size_t i = 0; i < len; ++i) {
        crc = static_cast<std::uint16_t>(crc ^ (static_cast<std::uint16_t>(data[i]) << 8));
        for (int bit = 0; bit < 8; ++bit) {
            crc = (crc & 0x8000u) != 0 ? static_cast<std::uint16_t>((crc << 1) ^ 0x1021u)
                                       : static_cast<std::uint16_t>(crc << 1);
        }
    }
    return crc;
}

ClassBStatus decode_beacon(const std::uint8_t* in, std::size_t len, std::uint8_t rfu_len,
                           BeaconCommon& out) {
    if (in == nullptr || (rfu_len != 2 && rfu_len != 3)) return ClassBStatus::InvalidParameter;
    const std::size_t common = rfu_len + kTimeLen;
    if (len < common + kCrcLen) return ClassBStatus::InvalidParameter;
    const std::uint16_t expected = beacon_crc16(in, common);
    const std::uint16_t received = static_cast<std::uint16_t>(
        in[common] | (static_cast<std::uint16_t>(in[common + 1]) << 8));
    if (expected != received) return ClassBStatus::CrcError;
    out.time_s = get_le32(in + rfu_len);
    return ClassBStatus::Ok;
}

ClassBStatus ping_slot_count(std::uint8_t periodicity, std::uint32_t& ping_nb,
                             std::uint32_t& ping_period) {
    if (periodicity > kMaxPeriodicity) return ClassBStatus::InvalidParameter;
    ping_nb = 1u << (7u - periodicity);
    ping_period = 1u << (5u + periodicity);
    return ClassBStatus::Ok;
}

ClassBStatus ping_offset(std::uint32_t beacon_time_s, std::uint32_t dev_addr,
                         std::uint8_t periodicity, std::uint32_t& offset) {
    std::uint32_t ping_nb = 0;
    std::uint32_t ping_period = 0;
    if (ping_slot_count(periodicity, ping_nb, ping_period) != ClassBStatus::Ok) {
        return ClassBStatus::InvalidParameter;
    }
    crypto::Block16 block{};
    put_le32(block.data(), beacon_time_s);
    put_le32(block.data() + 4, dev_addr);  // octets 8..15 : pad16 (zéros)
    const crypto::Key128 zero_key{};
    crypto::Block16 rand{};
    if (crypto::aes128_encrypt_block(zero_key, block, rand) != crypto::CryptoStatus::Ok) {
        return ClassBStatus::InvalidParameter;
    }
    const std::uint32_t raw = static_cast<std::uint32_t>(rand[0]) +
                              static_cast<std::uint32_t>(rand[1]) * 256u;
    offset = raw % ping_period;
    return ClassBStatus::Ok;
}

ClassBStatus on_beacon(DeviceClassB& d, std::uint64_t rx_ns, std::uint32_t beacon_time_s) {
    if (d.synchronized && rx_ns < d.last_beacon_rx_ns) return ClassBStatus::InvalidParameter;
    d.synchronized = true;
    d.last_beacon_rx_ns = rx_ns;
    d.last_beacon_time_s = beacon_time_s;
    return ClassBStatus::Ok;
}

ClassBStatus beacon_state(const DeviceClassB& d, std::uint64_t now_ns, BeaconState& out) {
    if (!d.synchronized) {
        out = BeaconState::NotSynchronized;
        return ClassBStatus::Ok;
    }
    if (now_ns < d.last_beacon_rx_ns) return ClassBStatus::InvalidParameter;
    const std::uint64_t age = now_ns - d.last_beacon_rx_ns;
    if (age >= kBeaconlessNs) {
        out = BeaconState::Lost;
    } else if (age < kBeaconPeriodNs) {
        out = BeaconState::Synchronized;
    } else {
        out = BeaconState::BeaconLess;
    }
    return ClassBStatus::Ok;
}

ClassBStatus next_ping_slot(const DeviceClassB& d, std::uint64_t now_ns, PingSlot& out) {
    if (!d.synchronized) return ClassBStatus::NotSynchronized;
    if (now_ns < d.last_beacon_rx_ns) return ClassBStatus::InvalidParameter;
    if (now_ns - d.last_beacon_rx_ns >= kBeaconlessNs) return ClassBStatus::BeaconLost;

    std::uint32_t ping_nb = 0;
    std::uint32_t ping_period = 0;
    if (ping_slot_count(d.periodicity, ping_nb, ping_period) != ClassBStatus::Ok) {
        return ClassBStatus::InvalidParameter;
    }

    // Période courante k, puis k+1 : la période k+1 commence après now_ns, donc elle
    // contient toujours un candidat (pingNb >= 1). Deux itérations suffisent.
    const std::uint64_t k = (now_ns - d.last_beacon_rx_ns) / kBeaconPeriodNs;
    for (std::uint64_t j = k; j <= k + 1; ++j) {
        const std::uint64_t period_start = d.last_beacon_rx_ns + j * kBeaconPeriodNs;
        // beaconTime de la période : +128 s par période, modulo 2^32.
        const std::uint32_t beacon_time =
            d.last_beacon_time_s + static_cast<std::uint32_t>(j * (kBeaconPeriodNs / 1'000'000'000ull));
        std::uint32_t offset = 0;
        if (ping_offset(beacon_time, d.dev_addr, d.periodicity, offset) != ClassBStatus::Ok) {
            return ClassBStatus::InvalidParameter;
        }
        bool found = false;
        PingSlot best{};
        for (std::uint32_t m = 0; m < ping_nb; ++m) {
            const std::uint32_t n = offset + m * ping_period;  // < 4096 car offset < pingPeriod
            const std::uint64_t start =
                period_start + kBeaconReservedNs + static_cast<std::uint64_t>(n) * kSlotNs;
            if (start < now_ns) continue;
            if (!found || start < best.start_ns) {
                found = true;
                best.start_ns = start;
                best.slot_index = n;
                best.beacon_time_s = beacon_time;
                best.beacon_period_start_ns = period_start;
            }
        }
        if (found) {
            out = best;
            return ClassBStatus::Ok;
        }
    }
    return ClassBStatus::InvalidParameter;  // inatteignable
}

}  // namespace lsim::lorawan::classb
