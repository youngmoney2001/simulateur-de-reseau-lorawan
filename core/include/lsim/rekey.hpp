// SPDX-License-Identifier: Apache-2.0
// Rekey effectif (LoRaWAN 1.1 §5.10 : RekeyInd / RekeyConf ; §6.2.3 : activation OTA).
//
// Dispositif : après un join-accept traité, RekeyInd est envoyé dans chaque uplink (confirmé
// ou non) jusqu'à réception d'un RekeyConf valide. Si aucun RekeyConf n'arrive pendant les
// ADR_ACK_LIMIT premiers uplinks, le dispositif revient à l'état Join (il doit rejoindre).
// Un RekeyConf est valide si sa version serveur vaut 1..kDeviceMinor (0 interdit).
//
// Serveur : après un join-accept, les trames protégées par le nouveau contexte reçues
// avant le premier RekeyInd sont rejetées ; le RekeyInd déclenche un RekeyConf. Les
// RekeyInd suivants sont ignorés (la trame reste acceptée).
//
// Les deux machines sont pures : l'état est passé par l'appelant.
#pragma once

#include <cstdint>

namespace lsim::lorawan::rekey {

inline constexpr std::uint8_t kDeviceMinor = 1;  // LoRaWAN 1.1

enum class DeviceState : std::uint8_t {
    Idle = 0,       // aucun join-accept traité
    Pending = 1,    // RekeyInd à envoyer dans chaque uplink
    Confirmed = 2,  // RekeyConf reçu : contexte confirmé
    NeedsJoin = 3,  // pas de RekeyConf dans les ADR_ACK_LIMIT premiers uplinks : rejoindre
};

struct DeviceRekey {
    DeviceState state = DeviceState::Idle;
    std::uint64_t uplinks = 0;  // uplinks émis depuis le join-accept (en état Pending)
};

enum class ServerAction : std::uint8_t {
    Accept = 0,            // trame traitée normalement
    AcceptAndConfirm = 1,  // trame traitée et RekeyConf à émettre
    Discard = 2,           // trame sous le nouveau contexte rejetée
};

struct ServerRekey {
    bool awaiting = false;  // join-accept traité, premier RekeyInd non reçu
};

void device_join_accepted(DeviceRekey& d);
bool device_must_send_rekey_ind(const DeviceRekey& d);
// À appeler après chaque uplink et ses fenêtres de réception. `conf_received` et
// `server_version` décrivent le RekeyConf reçu pendant ces fenêtres (ignoré sinon).
void device_uplink_completed(DeviceRekey& d, std::uint64_t admin_limit, bool conf_received,
                             std::uint8_t server_version);

void server_join_accepted(ServerRekey& s);
ServerAction server_on_uplink(ServerRekey& s, bool new_context, bool has_rekey_ind);

}  // namespace lsim::lorawan::rekey
