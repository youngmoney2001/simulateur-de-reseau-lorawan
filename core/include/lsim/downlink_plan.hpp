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
#include "lsim/radio_scheduler.hpp"

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

// Seconde fenêtre de réception (RX2), repli régional : fréquence et débit **propres**, distincts
// de RX1. Miroir de `lsim_plan_device_rx2` (frontière C).
//
// Jalon I0 : transportée et validée, puis **écartée** — aucun repli n'est produit. Le repli est
// **opt-in** : `rx2_sf = 0` signifie « aucune descente RX2 ».
struct DeviceRx2 {
    std::int64_t rx2_hz = 0;      // 0 : non renseignée ; sinon > 0
    std::uint8_t rx2_sf = 0;      // 0 : aucun repli ; sinon 7..12
    std::uint32_t rx2_bw_hz = 0;  // 0 : reprend `rx1_bw_hz` ; sinon 125k, 250k ou 500k
};

struct PlanOptions {
    bool confirmed_uplinks = false;
    std::uint32_t downlink_every = 0;
    std::uint32_t downlink_payload_bytes = 10;
    double gateway_tx_power_dbm = 14.0;
    double device_antenna_gain_dbi = 0.0;
    double device_rx_offset_db = 0.0;
    // Repli RX2 des descentes (I1). **Opt-in** : `false` reproduit exactement le comportement
    // d'avant I1. Ce n'est pas un champ de `lsim_plan_options` (frontière C) : la structure ABI
    // reste inchangée. Fournir une table RX2 à `lsim_plan_downlinks_v2` active le repli ; la v1
    // et la v2 sans table ne le font jamais.
    //
    // Même à `true`, le repli n'opère que pour les dispositifs dont la fenêtre RX2 est
    // réellement renseignée (`rx2_sf != 0` **et** `rx2_hz != 0`).
    bool rx2_fallback = false;
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

// Surcharge avec les paramètres RX2 (jalon I0). `rx2` nul : comportement de la forme ci-dessus.
// Non nul, il doit compter exactement `radios.size()` entrées, sinon InvalidInput.
//
// Au jalon I0 les valeurs RX2 sont **validées puis écartées** : le résultat est identique à celui
// de la forme sans RX2, quel que soit leur contenu.
PlanStatus plan_downlinks(const std::vector<UplinkRecord>& uplinks,
                          const std::vector<DeviceRadio>& radios, const PlanOptions& options,
                          const std::vector<DeviceRx2>* rx2, std::vector<Event>& events,
                          std::vector<Interval>& busy);

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

    // Surcharge avec les paramètres RX2 (jalon I0). `rx2` nul : comportement du constructeur
    // ci-dessus. Non nul, il doit compter exactement `radios.size()` entrées, sinon InvalidInput.
    DownlinkScheduler(const std::vector<DeviceRadio>& radios, const PlanOptions& options,
                      const std::vector<DeviceRx2>* rx2);

    PlanStatus status() const { return status_; }

    // Trame montante reçue par la passerelle, à `end_ns`. Retourne les émissions passerelle
    // planifiées à cet appel (voir la surcharge à trois arguments).
    // Les appels doivent se succéder par fins croissantes (ordre de la trace).
    std::vector<Interval> on_received(std::uint32_t device, std::int64_t end_ns);

    // Surcharge avec les paramètres RX2 du dispositif. Un RX2 invalide fait passer le
    // planificateur en InvalidRadio.
    //
    // Renvoie les intervalles **placés à cet appel**, dans l'ordre de placement : celui de la
    // montante courante, mais aussi d'éventuelles fenêtres RX2 différées d'une montante
    // antérieure et dont l'ouverture vient d'arriver.
    //
    // Avertissement : la RX2 n'est **pas** placée immédiatement. Elle entre dans la file à son
    // propre instant d'ouverture (fin + 2 s), donc après les descentes déjà déposées qui sont
    // plus tardives qu'elle. Placer la RX2 sur-le-champ placerait la descente trop tôt et
    // ferait diverger l'occupation de celle de `plan_downlinks` (tas), ce que le chemin causal
    // vérifie à l'égalité (`trace_events` : « occupation passerelle incohérente »).
    //
    // U0.3 renforce cette contrainte : A6 interdisant tout décalage, une RX2 placée sur-le-champ
    // serait émise avant son ouverture, ce qui n'a pas de sens. Le report n'est donc plus une
    // simple précaution de parité, il est exigé par la règle de placement elle-même.
    std::vector<Interval> on_received(std::uint32_t device, std::int64_t end_ns,
                                      const DeviceRx2& rx2);

    // Place ce qui reste en attente, sans attendre de nouvelle montante : à appeler une fois la
    // trace épuisée, sinon la dernière fenêtre RX2 différée ne serait jamais émise.
    std::vector<Interval> drain();

private:
    std::vector<Interval> placer(std::int64_t frontiere);
    // Une tentative de descente en attente de placement.
    struct Essai {
        std::int64_t pret = 0;      // ouverture de la fenêtre
        std::int64_t pret_rx2 = 0;  // ouverture de la fenêtre de secours (RX1 seulement)
        int phase = 0;              // 0 = RX1, 1 = RX2
        std::uint32_t device = 0;
        std::uint32_t base = 0;     // octets de la trame
        bool queued = false;        // descente de données (sinon ACK) : sélection du temps d'antenne
        std::int64_t ordre = 0;     // rang de dépôt, pour départager à ouverture égale
        DeviceRx2 rx2{};
    };
    // (ouverture, phase, rang) : même clé que le tas de `plan_downlinks` — la phase départage à
    // ouverture égale en faveur de la RX1, qui naît avant la RX2 qu'elle pourrait engendrer.
    static bool plus_tot(const Essai& a, const Essai& b) {
        if (a.pret != b.pret) return a.pret < b.pret;
        if (a.phase != b.phase) return a.phase < b.phase;
        return a.ordre < b.ordre;
    }

    PlanOptions options_;
    std::vector<DeviceRadio> radios_;
    std::vector<DeviceRx2> rx2_;
    std::vector<std::uint32_t> accepted_;
    std::vector<std::int64_t> ack_air_;  // 0 = non calculée
    std::vector<std::int64_t> data_air_;
    std::vector<Essai> pendantes_;  // tentatives dont l'ouverture n'est pas encore atteinte
    std::int64_t ordre_ = 0;
    PlanStatus status_ = PlanStatus::Ok;

    // Occupation de l'émetteur et règle de placement (jalon U0.3) : déléguées au composant
    // radio, qui applique A6 — départ exact à l'ouverture, chevauchement réel, occupation
    // seulement pour les émissions acceptées. Le planificateur garde l'**ordonnancement** :
    // l'ordre d'examen des fenêtres et le report de la RX2 à sa propre ouverture.
    lsim::radio::RadioScheduler sched_;
};

}  // namespace lsim::plan
