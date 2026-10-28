// SPDX-License-Identifier: Apache-2.0
#include "lsim/class_b.hpp"

#include "lsim/crypto.hpp"

namespace lsim::lorawan::classb {

namespace {

constexpr std::size_t kTimeLen = 4;
constexpr std::size_t kCrcLen = 2;
constexpr std::size_t kGwLen = 7;  // InfoDesc (1) + Info (6)
constexpr double kCoordScale = 8388608.0;  // 2^23

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

// Entier de 24 bits en complément à deux, little-endian.
std::int32_t get_s24le(const std::uint8_t* p) {
    std::uint32_t v = static_cast<std::uint32_t>(p[0]) | (static_cast<std::uint32_t>(p[1]) << 8) |
                      (static_cast<std::uint32_t>(p[2]) << 16);
    if ((v & 0x800000u) != 0) v |= 0xFF000000u;
    return static_cast<std::int32_t>(v);
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

ClassBStatus decode_beacon_full(const std::uint8_t* in, std::size_t len, std::uint8_t rfu_len,
                                std::uint8_t gw_rfu_len, BeaconCommon& common, GatewayInfo& gw) {
    if (gw_rfu_len > 1) return ClassBStatus::InvalidParameter;
    gw = GatewayInfo{};
    const ClassBStatus c = decode_beacon(in, len, rfu_len, common);
    if (c != ClassBStatus::Ok) return c;
    const std::size_t common_len = rfu_len + kTimeLen + kCrcLen;
    if (len == common_len) return ClassBStatus::Ok;  // pas de GwSpecific
    const std::size_t gw_total = kGwLen + gw_rfu_len + kCrcLen;
    if (len != common_len + gw_total) return ClassBStatus::InvalidParameter;

    const std::uint8_t* g = in + common_len;
    const std::size_t signed_len = kGwLen + gw_rfu_len;
    const std::uint16_t expected = beacon_crc16(g, signed_len);
    const std::uint16_t received =
        static_cast<std::uint16_t>(g[signed_len] | (static_cast<std::uint16_t>(g[signed_len + 1]) << 8));
    if (expected != received) return ClassBStatus::CrcError;

    gw.present = true;
    gw.info_desc = g[0];
    if (gw.info_desc <= 2) {
        const std::int32_t lat = get_s24le(g + 1);
        const std::int32_t lng = get_s24le(g + 4);
        gw.has_coordinates = true;
        gw.latitude_deg = static_cast<double>(lat) * 90.0 / kCoordScale;
        gw.longitude_deg = static_cast<double>(lng) * 180.0 / kCoordScale;
    }
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

ClassBStatus us902_channel_index(std::uint32_t beacon_time_s, std::uint8_t& index) {
    index = static_cast<std::uint8_t>((beacon_time_s / 128u) % kUs902Channels);
    return ClassBStatus::Ok;
}

ClassBStatus us902_channel_frequency_hz(std::uint8_t index, std::uint32_t& freq_hz) {
    if (index >= kUs902Channels) return ClassBStatus::InvalidParameter;
    freq_hz = 923'300'000u + 600'000u * index;
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
    if (d.clock_drift_ppm > kMaxDriftPpm) return ClassBStatus::InvalidParameter;

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
            // Dérive : fenêtre élargie proportionnellement au temps écoulé depuis le beacon.
            const std::uint64_t elapsed = best.start_ns - d.last_beacon_rx_ns;
            const std::uint64_t drift_num = elapsed * d.clock_drift_ppm;  // ≤ 7,2e15 : pas de débordement
            best.window_half_ns = (drift_num + 999'999ull) / 1'000'000ull;
            out = best;
            return ClassBStatus::Ok;
        }
    }
    return ClassBStatus::InvalidParameter;  // inatteignable
}

}  // namespace lsim::lorawan::classb
