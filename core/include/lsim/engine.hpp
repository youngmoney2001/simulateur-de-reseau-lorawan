// SPDX-License-Identifier: Apache-2.0
// Moteur à événements discrets minimal et simulation de liaisons montantes.
//
// Principes :
//   * temps en nanosecondes entières (SimTime) ;
//   * ordre total des événements : (temps, numéro de séquence). Deux exécutions
//     avec les mêmes entrées produisent exactement les mêmes résultats ;
//   * file bornée : la capacité est fixée à la création, aucun dépassement
//     silencieux de mémoire (push refuse au lieu de croître) ;
//   * toutes les entrées sont validées avant calcul.
#pragma once

#include <cstddef>
#include <cstdint>
#include <limits>
#include <vector>

#include "lsim/downlink.hpp"
#include "lsim/environment.hpp"
#include "lsim/lora_phy.hpp"

namespace lsim::sim {

namespace downlink = lorawan::downlink;

using SimTime = std::int64_t;  // nanosecondes

struct Event {
    SimTime time = 0;
    std::uint64_t seq = 0;      // départage des événements simultanés
    std::uint32_t kind = 0;     // type défini par l'appelant
    std::uint32_t target = 0;   // index du dispositif concerné
};

// File de priorité (min-heap) bornée et déterministe.
class EventQueue {
public:
    explicit EventQueue(std::size_t capacity);

    // Refuse (retourne false) si la capacité est atteinte.
    bool push(SimTime time, std::uint32_t kind, std::uint32_t target);
    bool pop(Event& out);

    std::size_t size() const { return heap_.size(); }
    bool empty() const { return heap_.empty(); }
    std::size_t capacity() const { return capacity_; }

private:
    static bool before(const Event& a, const Event& b);
    std::vector<Event> heap_;
    std::size_t capacity_;
    std::uint64_t next_seq_ = 0;
};

// Position planaire en mètres.
struct Position {
    double x_m = 0.0;
    double y_m = 0.0;
};

// Requêtes de downlink adressées à un dispositif (count = 0 : aucune). La requête k part à
// first_request_ns + k * request_period_ns ; la latence est mesurée jusqu'à la première
// fenêtre de réception utilisable selon la classe (voir lsim/downlink.hpp).
struct DownlinkPlan {
    downlink::DeviceClass device_class = downlink::DeviceClass::A;
    std::uint32_t count = 0;                // 0..kMaxDownlinksPerDevice
    SimTime first_request_ns = 0;           // >= 0
    SimTime request_period_ns = 0;          // > 0 si count > 1
    SimTime rx_window_ns = 1'000'000'000;   // durée de RX1 (hypothèse, 0..10 s)
    std::uint32_t dev_addr = 0;             // classe B : entrée du ping slot
    std::uint8_t periodicity = 0;           // classe B : 0..7
    std::uint32_t clock_drift_ppm = 0;      // classe B : 0..1000
};

// Dispositif terminal émettant périodiquement des trames confirmées-non.
struct EndDeviceSpec {
    Position position;
    std::uint8_t spreading_factor = 7;   // 7..12
    std::uint32_t payload_bytes = 10;    // 0..255
    double tx_power_dbm = 14.0;
    SimTime start_offset_ns = 0;
    SimTime period_ns = 60'000'000'000;  // 60 s
    std::uint32_t messages = 1;          // nombre de trames émises
    // Rapport cyclique maximal (0 < d <= 1, 1 = sans limite). Après chaque
    // trame, le dispositif attend airtime * (1 - d) / d avant la suivante.
    double duty_cycle = 1.0;
    DownlinkPlan downlink;
};

// Borne de l'horizon de simulation : au-delà, les dates ne sont plus fiables.
inline constexpr double kMaxHorizonNs = 4.0e18;

struct GatewaySpec {
    Position position;
    double antenna_gain_dbi = 0.0;
    // Décalage du seuil de réception montant de cette passerelle (dB) : seuil = sensibilité de
    // l'équipement + décalage. Négatif = passerelle plus sensible. 0 = modèle sans profil.
    double rx_sensitivity_offset_db = 0.0;
};

struct PropagationSpec {
    double frequency_hz = 868.1e6;
    double reference_distance_m = 1.0;
    double exponent = 2.7;
    // Seuil de capture : un signal survit à une interférence de même SF s'il
    // est supérieur d'au moins ce seuil (dB).
    double capture_threshold_db = 6.0;
    // Shadowing log-normal par dispositif (écart-type en dB, 0 = désactivé).
    // Tirage déterministe : même graine et même index de dispositif donnent la
    // même valeur. Modèle « évanouissement lent » : constant pour un dispositif.
    double shadowing_sigma_db = 0.0;
    std::uint64_t shadowing_seed = 0;
};

// Valeur de shadowing (dB) du dispositif `device_index`, gaussienne de moyenne
// nulle et d'écart-type `sigma_db`. Fonction pure, reproductible.
LSIM_API double shadowing_sample_db(std::uint64_t seed, std::uint32_t device_index,
                                    double sigma_db);

// Statistiques de downlink. Une requête est livrée si une fenêtre de réception
// utilisable ouvre au plus tard à la fin de l'observation (fin de la dernière émission).
struct DownlinkStats {
    std::uint64_t requested = 0;
    std::uint64_t delivered = 0;
    std::uint64_t latency_sum_ns = 0;   // somme des latences des requêtes livrées
    std::uint64_t latency_max_ns = 0;
};

struct DeviceStats {
    std::uint64_t sent = 0;
    std::uint64_t received = 0;
    std::uint64_t lost_sensitivity = 0;  // sous le seuil de sensibilité
    std::uint64_t lost_collision = 0;    // détruite par une collision non capturée
    std::uint64_t airtime_ns = 0;        // temps d'antenne cumulé des trames émises
    std::uint64_t lost_gateway_busy = 0; // reçue mais passerelle en émission
    DownlinkStats downlink;
};

struct SimulationStats {
    std::uint64_t sent = 0;
    std::uint64_t received = 0;
    std::uint64_t lost_sensitivity = 0;
    std::uint64_t lost_collision = 0;
    std::uint64_t lost_gateway_busy = 0;      // trames perdues pendant une émission passerelle
    std::uint64_t airtime_ns = 0;             // somme des temps d'antenne
    std::uint64_t gateway_busy_ns = 0;        // durée où la passerelle reçoit au moins une trame (union)
    std::uint64_t gateway_peak_concurrent = 0;  // nombre maximal de trames simultanées
    std::int64_t observation_ns = 0;          // fin de la dernière trame - début de la première
    double gateway_utilization = 0.0;         // gateway_busy_ns / observation_ns, dans [0, 1]
    DownlinkStats downlink;                   // somme des dispositifs
};

// Limites de sécurité / scalabilité.
inline constexpr std::size_t kMaxEndDevices = 10'000;
inline constexpr std::uint64_t kMaxTransmissions = 5'000'000;
inline constexpr std::uint32_t kMaxDownlinksPerDevice = 100'000;
inline constexpr std::uint64_t kMaxDownlinkRequests = 5'000'000;  // total de la simulation
inline constexpr SimTime kMaxRxWindowNs = 10'000'000'000;  // 10 s
inline constexpr double kMaxShadowingSigmaDb = 30.0;

enum class SimStatus : std::int32_t {
    Ok = 0,
    InvalidInput = 1,
    TooManyDevices = 2,
    TooManyTransmissions = 3,
    QueueFull = 4,
    InvalidEnvironment = 5,
    EnvironmentWorkLimit = 6,
    TooManyDownlinks = 7,
    TraceBufferTooSmall = 8,
    TraceTooLarge = 9,
    InvalidGatewayBusy = 10,
};

// Issue d'une transmission, telle que calculée par le moteur.
enum class TxOutcome : std::uint8_t {
    LostSensitivity = 0,  // RSSI sous la sensibilité du SF
    LostCollision = 1,    // détruite par une collision non capturée
    Received = 2,         // reçue par la passerelle
    LostGatewayBusy = 3,  // passerelle en émission (downlink) pendant la trame
};

// Intervalle [start, end) pendant lequel la passerelle émet (demi-duplex : elle ne reçoit pas).
struct Interval {
    SimTime start = 0;
    SimTime end = 0;
};

// Une transmission de la trace, dans l'ordre temporel (début, puis ordre de file).
// Les temps sont ceux du moteur : même horloge pour toute la trace et les événements.
struct TxRecord {
    std::uint32_t device = 0;
    SimTime start_ns = 0;
    SimTime end_ns = 0;
    std::uint8_t spreading_factor = 7;
    double rssi_dbm = 0.0;
    TxOutcome outcome = TxOutcome::LostSensitivity;
};

// Simule les liaisons montantes vers une passerelle. `per_device` doit contenir
// `device_count` entrées ; les compteurs y sont remis à zéro puis remplis.
// `environment` optionnel : relief et obstacles (nullptr = terrain plat sans obstacle).
// `trace` optionnel : reçoit une entrée par transmission, dans l'ordre temporel (vidé puis rempli).
// `gateway_busy` optionnel : périodes d'émission de la passerelle (intervalles [start, end)).
// Une trame reçue qui chevauche une de ces périodes est perdue (LostGatewayBusy).
LSIM_API SimStatus simulate_uplinks(const EndDeviceSpec* devices, std::size_t device_count,
                                    const GatewaySpec& gateway, const PropagationSpec& prop,
                                    DeviceStats* per_device, SimulationStats& totals,
                                    const env::Environment* environment = nullptr,
                                    std::vector<TxRecord>* trace = nullptr,
                                    const std::vector<Interval>* gateway_busy = nullptr);

// ------------------------------------------------------------- Plusieurs passerelles
//
// Chaque passerelle reçoit indépendamment les mêmes émissions (sensibilité et collision calculées
// à son propre RSSI). Le serveur déduplique : une trame est livrée une fois si au moins une
// passerelle la décode. Les copies supplémentaires sont comptées (`duplicates`).
//
// Hors périmètre de cette fonction : downlinks et demi-duplex par passerelle (passerelles
// émettant pendant une trame). Le chemin mono-passerelle (`simulate_uplinks`) reste inchangé.

inline constexpr std::size_t kMaxGateways = 64;

// Statistiques réseau, après déduplication serveur.
struct NetworkStats {
    std::uint64_t sent = 0;
    std::uint64_t received = 0;         // trames livrées au serveur (une fois par trame)
    std::uint64_t duplicates = 0;       // copies décodées en plus de la première
    std::uint64_t lost_sensitivity = 0;  // aucune passerelle au-dessus de la sensibilité
    std::uint64_t lost_collision = 0;    // au-dessus de la sensibilité quelque part, mais collisionnée partout
    std::uint64_t lost_gateway_busy = 0; // seule(s) passerelle(s) audibles en émission (downlink)
    std::uint64_t airtime_ns = 0;
};

// Statistiques par passerelle : trames décodées ou perdues à cette seule passerelle.
struct GatewayRxStats {
    std::uint64_t received = 0;
    std::uint64_t lost_sensitivity = 0;
    std::uint64_t lost_collision = 0;
    std::uint64_t lost_gateway_busy = 0;  // passerelle en émission pendant la trame
    // Charge de réception : trames audibles (RSSI >= sensibilité) à cette passerelle.
    std::uint64_t audible_frames = 0;
    std::uint64_t busy_ns = 0;            // union des intervalles de ces trames
    std::uint64_t peak_concurrent = 0;    // trames audibles simultanées au maximum
    std::int64_t observation_ns = 0;      // fin de la dernière émission - début de la première
};

// Issue réseau d'une émission. `receivers` = nombre de passerelles qui l'ont décodée.
struct MultiTx {
    std::uint32_t device = 0;
    SimTime start_ns = 0;
    SimTime end_ns = 0;
    std::uint8_t spreading_factor = 7;
    std::uint32_t receivers = 0;
    std::uint64_t decoded_mask = 0;     // bit g : passerelle g a décodé la trame (g < 64)
    std::int32_t best_gateway = -1;     // meilleure passerelle parmi les décodeurs (-1 : aucune)
    double best_rssi_dbm = 0.0;         // RSSI à cette passerelle (ou RSSI max si aucune)
    TxOutcome outcome = TxOutcome::LostSensitivity;  // Received si receivers > 0
    bool join_request = false;          // première trame non jointe : join-request (rule.join)
};

// `per_gateway` doit contenir `gateway_count` entrées. `trace` optionnel (trié par début). `gateway_busy` optionnel : une liste d'émissions passerelle par passerelle
// (intervalles [start, end)) ; une trame qui chevauche l'émission de SA passerelle n'y est pas
// décodée (LostGatewayBusy à cette passerelle seulement).
LSIM_API SimStatus simulate_uplinks_multi(const EndDeviceSpec* devices, std::size_t device_count,
                                          const GatewaySpec* gateways, std::size_t gateway_count,
                                          const PropagationSpec& prop, DeviceStats* per_device,
                                          NetworkStats& totals, GatewayRxStats* per_gateway,
                                          const env::Environment* environment = nullptr,
                                          std::vector<MultiTx>* trace = nullptr,
                                          const std::vector<std::vector<Interval>>* gateway_busy = nullptr);

// ------------------------------------------------- Downlinks multi-passerelles
//
// Règle : chaque uplink décodé par au moins une passerelle est acquitté (ACK seul) ou reçoit une
// charge (une par `every` uplinks décodés), par la MEILLEURE passerelle décodeuse (plus fort RSSI),
// en fenêtre RX1 (+1 s). Chaque passerelle sérialise ses propres downlinks ; un downlink qui ne
// peut pas partir dans la fenêtre RX1 est perdu (GatewayBusy). Pendant son downlink, une passerelle
// ne décode pas les trames (demi-duplex par passerelle). Le dispositif ne reçoit que s'il n'émet
// pas pendant sa fenêtre RX1 (DeviceTransmitting), puis par réciprocité sur le RSSI de la passerelle
// répondante.
//
// Calcul exact sans itération : les émissions sont traitées dans l'ordre de leur FIN. Un downlink
// qui chevauche une émission X est déclenché par une émission finie avant X - 1 s, donc déjà connu.

struct MultiDownlinkRule {
    bool ack_uplinks = false;               // ACK seul pour chaque uplink décodé (confirmé)
    std::uint32_t every = 0;                // charge en file : une par `every` uplinks décodés (0 : aucune)
    std::uint32_t payload_bytes = 10;       // charge des downlinks de données, 0..242
    double gateway_tx_power_dbm = 14.0;     // puissance d'émission passerelle (downlink)
    double device_antenna_gain_dbi = 0.0;   // gain d'antenne du dispositif (réception)
    double device_rx_offset_db = 0.0;       // écart de sensibilité du récepteur réel (dB)
    bool join = false;                      // join : une join-request décodée reçoit un join-accept
                                            // (à fin + 5 s, 17 octets) ; les uplinks sont des données
                                            // tant que le join-accept n'est pas délivré
    std::uint8_t rx2_sf = 12;               // SF de la fenêtre RX2 de repli (7..12, BW 125 kHz) ;
                                            // 0 : pas de repli (GatewayBusy en RX1 reste final)
};

enum class DownlinkOutcome : std::uint8_t {
    Delivered = 0,
    LostSensitivity = 1,
    GatewayBusy = 2,         // hors de la fenêtre RX1 : la passerelle ne peut plus émettre à temps
    DeviceTransmitting = 3,  // le dispositif émet pendant sa fenêtre RX1
};

// Downlink planifié. start_ns = -1 si non émis (GatewayBusy ou DeviceTransmitting).
struct MultiDownlink {
    std::uint32_t device = 0;
    std::uint32_t gateway = 0;
    bool data = false;          // false : ACK seul ; true : charge
    bool join = false;          // true : join-accept (charge de 17 octets)
    SimTime t_open_ns = 0;      // ouverture de RX1 chez le dispositif (RX2 : +1 s)
    SimTime start_ns = -1;
    SimTime end_ns = -1;
    DownlinkOutcome outcome = DownlinkOutcome::GatewayBusy;
    std::uint8_t rx_window = 1; // 1 : RX1 ; 2 : RX2 (repli après GatewayBusy en RX1)
};

// `dl_ready_ns` (optionnel) : départ au plus tôt de la descente de chaque émission, indexé comme
// les émissions (dispositifs dans l'ordre, puis k) ; -1 : aucune contrainte (ouverture RX1) ;
// kDownlinkNever : jamais acheminée (retour mesh perdu). Une descente qui ne peut partir dans
// sa fenêtre RX1 après ce départ est perdue (GatewayBusy). Taille : somme des `messages`.
inline constexpr SimTime kDownlinkNever = std::numeric_limits<SimTime>::max();

LSIM_API SimStatus simulate_uplinks_multi_downlinks(
    const EndDeviceSpec* devices, std::size_t device_count, const GatewaySpec* gateways,
    std::size_t gateway_count, const PropagationSpec& prop, const MultiDownlinkRule& rule,
    DeviceStats* per_device, NetworkStats& totals, GatewayRxStats* per_gateway,
    const env::Environment* environment = nullptr, std::vector<MultiTx>* trace = nullptr,
    std::vector<MultiDownlink>* downlinks = nullptr,
    const SimTime* dl_ready_ns = nullptr);

}  // namespace lsim::sim
