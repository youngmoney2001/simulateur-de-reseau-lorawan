// SPDX-License-Identifier: Apache-2.0
// Planification des descentes d'une passerelle unique (S0 de la refonte boucle fermée).
//
// Porte en C++ la logique de `python/lsim/trace_events.py` (`_downlink_jobs`, `_schedule_gateway`,
// `_events`) pour le cas sans jointure et sans commande MAC. Entrée : les émissions montantes issues
// du moteur (`TxRecord`) et les paramètres radio des dispositifs. Sortie : occupation de la passerelle
// et événements de protocole, dans le même ordre que la version Python (même instant, même ordre
// d'insertion). La version Python reste l'oracle de test tant que la parité n'est pas totale.
#pragma once

#include <cstdint>
#include <optional>
#include <vector>

#include "lsim/lora_phy.hpp"

namespace lsim::plan {

// Issue d'une émission montante (mêmes valeurs que `lsim::sim::TxOutcome`).
enum class UplinkOutcome : std::uint8_t {
    LostSensitivity = 0,
    LostCollision = 1,
    Received = 2,
    LostGatewayBusy = 3,
};

// Codes des issues d'événements et de sauts (table de correspondance côté Python).
enum class Outcome : std::uint8_t {
    Received = 0,         // uplink reçu par la passerelle
    LostSensitivity = 1,  // sous la sensibilité
    LostCollision = 2,    // collision non capturée
    LostGatewayBusy = 3,  // passerelle en émission pendant la trame
    AckOnly = 4,          // ACK seul
    Data = 5,             // downlink de données
    DataAck = 6,          // downlink de données confirmé
    GatewayBusy = 7,      // RX1 manquée : passerelle occupée
    DeviceTransmitting = 8,  // RX1 manquée : le dispositif émet
    Delivered = 9,        // saut livré
    NotListened = 10,     // saut non écouté
};

enum class EventKind : std::uint8_t {
    Uplink = 0,
    Ack = 1,
    Downlink = 2,
    RxWindowMissed = 3,
};

enum class HopDir : std::uint8_t {
    DevToGw = 0,
    GwToNs = 1,
    GwToDev = 2,
};

struct UplinkRecord {
    std::uint32_t device = 0;
    std::int64_t start_ns = 0;
    std::int64_t end_ns = 0;
    std::uint8_t spreading_factor = 7;
    UplinkOutcome outcome = UplinkOutcome::LostSensitivity;
    double rssi_dbm = 0.0;
};

struct DeviceRadio {
    std::int64_t freq_hz = 868'100'000;
    std::int32_t dr = -1;            // -1 : aucun débit de plan
    std::int64_t rx1_hz = 868'100'000;
    double tx_power_dbm = 14.0;
    std::uint8_t rx1_sf = 7;
    std::uint32_t rx1_bw_hz = 125'000;
};

struct PlanOptions {
    bool confirmed_uplinks = false;
    std::uint32_t downlink_every = 0;
    std::uint32_t downlink_payload_bytes = 10;
    double gateway_tx_power_dbm = 14.0;
    double device_antenna_gain_dbi = 0.0;
    double device_rx_offset_db = 0.0;
};

struct Hop {
    HopDir dir = HopDir::DevToGw;
    Outcome outcome = Outcome::Delivered;
    bool has_rssi = false;
    double rssi_dbm = 0.0;
    std::int64_t t_ns = 0;
    std::int64_t freq_hz = 0;
    std::int32_t dr = -1;
};

struct Event {
    std::int64_t t_ns = 0;
    std::uint32_t device = 0;
    EventKind kind = EventKind::Uplink;
    Outcome outcome = Outcome::Received;
    std::vector<Hop> hops;  // au plus 2 sauts
};

struct Interval {
    std::int64_t start_ns = 0;
    std::int64_t end_ns = 0;
};

enum class PlanStatus : std::int32_t {
    Ok = 0,
    InvalidInput = 1,
    InvalidRadio = 2,
    InvalidOptions = 3,
};

// Planifie les descentes. `uplinks` doit être dans l'ordre de la trace (début croissant par
// dispositif). `events` et `busy` reçoivent le résultat (remplacés).
PlanStatus plan_downlinks(const std::vector<UplinkRecord>& uplinks,
                          const std::vector<DeviceRadio>& radios, const PlanOptions& options,
                          std::vector<Event>& events, std::vector<Interval>& busy);

// Durée d'un downlink de `payload_bytes` au débit RX1 du dispositif (CR 4/5, en-tête explicite,
// sans CRC, préambule 8, optimisation bas débit si Tsym > 16 ms), en ns.
lora::Status downlink_airtime_ns(const DeviceRadio& radio, std::uint32_t payload_bytes,
                                 std::int64_t& out_ns);

// Planificateur incrémental (S1) : mêmes règles que `plan_downlinks`, appelé à la fin de chaque trame
// montante reçue, dans l'ordre temporel des fins. Ne donne que l'occupation passerelle (ce qui décide
// des pertes montantes) ; les événements restent produits par `plan_downlinks`.
class DownlinkScheduler {
public:
    DownlinkScheduler(const std::vector<DeviceRadio>& radios, const PlanOptions& options);

    PlanStatus status() const { return status_; }

    // Trame montante reçue par la passerelle, à `end_ns`. Retourne l'émission passerelle planifiée,
    // ou nullopt (pas de réponse attendue, ou fenêtre RX1 perdue faute de passerelle libre).
    // Les appels doivent se succéder par fins croissantes (ordre de la trace).
    std::optional<Interval> on_received(std::uint32_t device, std::int64_t end_ns);

private:
    PlanOptions options_;
    std::vector<DeviceRadio> radios_;
    std::vector<std::uint32_t> accepted_;
    std::vector<std::int64_t> ack_air_;  // 0 = non calculée
    std::vector<std::int64_t> data_air_;
    PlanStatus status_ = PlanStatus::Ok;
    bool any_busy_ = false;
    std::int64_t busy_until_ = 0;
};

}  // namespace lsim::plan
