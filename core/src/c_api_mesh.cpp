// SPDX-License-Identifier: Apache-2.0
// Fonctions C du relais mesh. Aucune exception ne traverse la frontière.
#include <cstddef>
#include <cstdint>
#include <vector>

#include "lsim/c_api.h"
#include "lsim/mesh.hpp"

namespace {

lsim::mesh::Radio to_radio(const lsim_mesh_radio* r) {
    lsim::mesh::Radio out;
    out.spreading_factor = r->spreading_factor;
    out.coding_rate = r->coding_rate;
    out.bandwidth_hz = r->bandwidth_hz;
    out.payload_bytes = r->payload_bytes;
    out.preamble_symbols = r->preamble_symbols;
    out.capture_db = r->capture_db;
    return out;
}

int32_t status_code(lsim::mesh::Status st) {
    return st == lsim::mesh::Status::Ok
               ? 0
               : LSIM_STATUS_MESH_BASE + static_cast<int32_t>(st);
}

}  // namespace

extern "C" {

int32_t lsim_mesh_airtime_ns(const lsim_mesh_radio* radio, int64_t* out) {
    if (radio == nullptr || out == nullptr) return status_code(lsim::mesh::Status::InvalidInput);
    try {
        return status_code(lsim::mesh::airtime_ns(to_radio(radio), *out));
    } catch (...) {
        return LSIM_STATUS_INTERNAL;
    }
}

int32_t lsim_mesh_sensitivity_dbm(const lsim_mesh_radio* radio, int32_t* out) {
    if (radio == nullptr || out == nullptr) return status_code(lsim::mesh::Status::InvalidInput);
    try {
        return status_code(lsim::mesh::sensitivity_dbm(to_radio(radio), *out));
    } catch (...) {
        return LSIM_STATUS_INTERNAL;
    }
}

int32_t lsim_mesh_routes(const lsim_mesh_radio* radio, size_t node_count,
                         const uint8_t* capable, const double* rssi_dbm,
                         uint32_t border, uint32_t max_hops, int32_t* next) {
    if (radio == nullptr) return status_code(lsim::mesh::Status::InvalidInput);
    try {
        return status_code(lsim::mesh::routes(to_radio(radio), node_count, capable, rssi_dbm,
                                              border, max_hops, next));
    } catch (...) {
        return LSIM_STATUS_INTERNAL;
    }
}

int32_t lsim_mesh_forward(const lsim_mesh_radio* radio, size_t node_count,
                          const double* rssi_dbm, const int32_t* next, uint32_t border,
                          const lsim_mesh_frame* frames, size_t frame_count,
                          lsim_mesh_delivery* out) {
    if (radio == nullptr) return status_code(lsim::mesh::Status::InvalidInput);
    try {
        std::vector<lsim::mesh::Frame> in(frame_count);
        for (size_t k = 0; k < frame_count; ++k) {
            in[k].frame_id = frames[k].frame_id;
            in[k].rx_node = frames[k].rx_node;
            in[k].t_ns = frames[k].t_ns;
        }
        std::vector<lsim::mesh::Delivery> res(frame_count);
        const auto st = lsim::mesh::forward(to_radio(radio), node_count, rssi_dbm, next, border,
                                            in.data(), frame_count, res.data());
        if (st != lsim::mesh::Status::Ok) return status_code(st);
        for (size_t k = 0; k < frame_count; ++k) {
            out[k].frame_id = res[k].frame_id;
            out[k].delivered = res[k].delivered;
            out[k].loss = res[k].loss;
            out[k].hops = res[k].hops;
            out[k].latency_ns = res[k].latency_ns;
        }
        return 0;
    } catch (...) {
        return LSIM_STATUS_INTERNAL;
    }
}

}  // extern "C"
