// SPDX-License-Identifier: Apache-2.0
#include "lsim/rekey.hpp"

namespace lsim::lorawan::rekey {

void device_join_accepted(DeviceRekey& d) {
    d.state = DeviceState::Pending;
    d.uplinks = 0;
}

bool device_must_send_rekey_ind(const DeviceRekey& d) { return d.state == DeviceState::Pending; }

void device_uplink_completed(DeviceRekey& d, std::uint64_t admin_limit, bool conf_received,
                             std::uint8_t server_version) {
    if (d.state != DeviceState::Pending) return;
    if (conf_received && server_version >= 1 && server_version <= kDeviceMinor) {
        d.state = DeviceState::Confirmed;
        return;
    }
    ++d.uplinks;
    if (d.uplinks >= admin_limit) d.state = DeviceState::NeedsJoin;
}

void server_join_accepted(ServerRekey& s) { s.awaiting = true; }

ServerAction server_on_uplink(ServerRekey& s, bool new_context, bool has_rekey_ind) {
    if (!new_context) return ServerAction::Accept;  // ancien contexte : hors du périmètre de ce rekey
    if (s.awaiting) {
        if (!has_rekey_ind) return ServerAction::Discard;
        s.awaiting = false;
        return ServerAction::AcceptAndConfirm;
    }
    return ServerAction::Accept;  // RekeyInd ultérieurs : ignorés, trame acceptée
}

}  // namespace lsim::lorawan::rekey
