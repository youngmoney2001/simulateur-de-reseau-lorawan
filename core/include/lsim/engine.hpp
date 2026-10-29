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

#include <array>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <vector>

#include "lsim/downlink.hpp"
#include "lsim/downlink_plan.hpp"
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

// Octets MAC réservés dans une émission : calendrier de rangs (passerelle unique). L'émission de
// rang `rank` (1-based) du dispositif `device` est calculée avec payload_bytes + extra_bytes.
// Réservation conservatrice : une émission réservée ne porte pas forcément ces octets (ex.
// DevStatusAns, qui n'existe que si la requête est reçue).
struct MacReservation {
    std::uint32_t device = 0;
    std::uint32_t rank = 1;
    std::uint32_t extra_bytes = 0;  // 1..15 (FOpts)
};

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

// Descentes planifiées pendant la simulation (S1, boucle fermée causale) : passerelle unique.
// Chaque trame montante reçue est planifiée à sa fin (`plan::DownlinkScheduler`), de sorte que
// l'occupation passerelle utilisée pour décider des pertes est connue au moment de la décision.
// Exclusif avec `gateway_busy`. `radios` : un paramètre radio par dispositif (même ordre).
struct CausalDownlinks {
    std::vector<plan::DeviceRadio> radios;
    plan::PlanOptions options;
    std::vector<plan::Interval>* busy_out = nullptr;  // reçoit les émissions passerelle planifiées
};

// ------------------------------------------------------- Boucle fermée (S2)
//
// Passerelle unique, sans jointure, sans mesh ni autre commande MAC. Le serveur envoie
// LinkADRReq (débit et puissance, décision ADR sur les 20 dernières trames reçues) et
// DutyCycleReq (rapport cyclique 1/2^k). Une seule exécution, émissions en ordre temporel :
//   * une commande reçue (fin de RX1 + réception de la descente) s'applique aux émissions qui
//     commencent après cet instant ; le dispositif répond dans son uplink suivant ;
//   * la réponse n'est confirmée côté serveur que si cet uplink est reçu ;
//   * une commande est perdue si le dispositif émet pendant RX1 (classe A), ou si la passerelle
//     n'a pas de créneau dans la RX1 ; elle est retentée au prochain uplink reçu.
// Sans commande active, les résultats sont ceux de `simulate_uplinks` avec `causal`.

// Paramètres régionaux d'un dispositif. Lus dans tous les cas (puissance et limite réglementaire).
//  * dr_sf[i] : SF du débit i, 0 = indisponible ; max_dr : dernier débit utilisable ;
//  * max_tx_power_index : dernier index de puissance valide (les index 0..max sont contigus, les
//    suivants sont réservés par le plan et refusés par LinkADR) ;
//  * max_eirp_dbm : PIRE de l'index 0 du plan (plafond) ; +inf si le plan ne le définit pas ;
//  * power_step_tenth_db : pas entre index (dixièmes de dB) ; la puissance de l'index i est
//    min(tx_power_dbm, max_eirp_dbm) - i * pas ;
//  * duty_limit[i] : limite réglementaire du duty cycle à l'index i, dans ]0, 1] (sous-bande la plus
//    restrictive à la PIRE de cet index, et duty cycle du dispositif). DutyCycleReq ne fait que la
//    réduire.
struct LoopRegion {
    std::array<std::uint8_t, 16> dr_sf{};
    std::uint8_t max_dr = 0;
    std::uint8_t max_tx_power_index = 0;
    std::int32_t power_step_tenth_db = 20;
    double max_eirp_dbm = std::numeric_limits<double>::infinity();
    std::array<double, 16> duty_limit{};
};

// Calendrier MAC d'une émission (dispositif, rang 1-based), issu du calendrier réservé.
// `extra_bytes` : octets MAC réservés dans l'uplink (LinkCheckReq, DeviceTimeReq, DevStatusAns),
// ajoutés à la charge utile pour l'airtime. `flags` : kLoopMac* ci-dessous.
inline constexpr std::uint8_t kLoopMacLinkCheck = 1;   // LinkCheckAns dans la descente de cet uplink
inline constexpr std::uint8_t kLoopMacDeviceTime = 2;  // DeviceTimeAns dans la descente de cet uplink
inline constexpr std::uint8_t kLoopMacDevStatus = 4;   // DevStatusReq dans la descente de cet uplink
inline constexpr std::uint8_t kLoopMacAll = 7;
inline constexpr std::uint8_t kLoopMacMaxDeferrals = 3;  // défaut de LoopOptions::mac_max_deferrals
inline constexpr std::uint32_t kLoopFoptsMax = 15;       // taille maximale des FOpts

struct LoopMacSlot {
    std::uint32_t device = 0;
    std::uint32_t rank = 1;                   // 1-based
    std::uint8_t extra_bytes = 0;             // 0..15
    std::uint8_t flags = 0;                   // kLoopMac*
};

struct LoopOptions {
    plan::PlanOptions protocol;               // acquittements, descentes de données, puissances
    bool adr = false;                         // LinkADRReq
    std::int32_t installation_margin_tenth_db = 0;  // marge d'installation de l'ADR (dixièmes de dB)
    bool duty_cycle = false;                  // DutyCycleReq, une fois, au premier uplink reçu
    std::uint8_t duty_cycle_exponent = 0;     // 0..15 : rapport cyclique 1 / 2^k
    // Réservations MAC (LinkCheck, DeviceTime, DevStatus) : au plus une entrée par émission.
    const LoopMacSlot* mac = nullptr;
    std::size_t mac_count = 0;
    // File MAC : nombre de reports (uplinks reçus où la commande ne tient pas dans les FOpts)
    // au-delà duquel la commande expire.
    std::uint8_t mac_max_deferrals = kLoopMacMaxDeferrals;
};

// Compteurs de la file MAC. Invariant : enqueued = dispatched + expired + pending_at_end.
// `dispatched` : commandes placées dans une descente (livrée ou non) ; `dispatch_lost` : parmi
// elles, celles dont la descente n'a pas été reçue (pas de nouvel essai pour ces réponses).
struct LoopMacQueueStats {
    std::uint64_t enqueued = 0;
    std::uint64_t dispatched = 0;
    std::uint64_t dispatch_lost = 0;
    std::uint64_t deferred = 0;      // reports (une commande reportée à chaque uplink où elle ne tient pas)
    std::uint64_t expired = 0;
    std::uint64_t pending_at_end = 0;
};

// Uplink : une entrée par émission, dans l'ordre temporel des débuts.
struct LoopUplink {
    std::uint32_t device = 0;
    SimTime start_ns = 0;
    SimTime end_ns = 0;
    std::uint8_t spreading_factor = 7;
    std::int8_t dr = -1;                      // -1 : pas de table régionale
    std::uint8_t power_index = 0;
    double rssi_dbm = 0.0;
    TxOutcome outcome = TxOutcome::LostSensitivity;
    std::uint8_t answer_mask = 0;             // bit 0 : LinkADRAns, bit 1 : DutyCycleAns, bit 2 : DevStatusAns (portées)
    std::uint8_t answer_ok = 0;               // bit 0 : débit acquitté, bit 1 : puissance acquittée
};

inline constexpr std::uint8_t kLoopCmdLinkAdr = 1;   // bit de `LoopDownlink::commands`
inline constexpr std::uint8_t kLoopCmdDutyCycle = 2;
inline constexpr std::uint8_t kLoopCmdLinkCheck = 4;   // LinkCheckAns (FOpts, 3 octets)
inline constexpr std::uint8_t kLoopCmdDeviceTime = 8;  // DeviceTimeAns (FOpts, 6 octets)
inline constexpr std::uint8_t kLoopCmdDevStatus = 16;  // DevStatusReq (FOpts, 1 octet)

// Descente créée (ACK, donnée ou MAC seul) pour un uplink reçu.
struct LoopDownlink {
    std::uint32_t uplink = 0;                 // indice dans LoopResult::uplinks
    std::uint32_t device = 0;
    std::uint8_t kind = 3;                    // 1 ACK, 2 donnée, 3 MAC seul
    std::uint8_t commands = 0;                // kLoopCmd* (FOpts et réponses MAC)
    std::uint8_t queued = 0;                  // commandes de la file portées (pour `dispatch_lost`)
    SimTime t_open = 0;
    SimTime start_ns = -1;                    // -1 : pas de créneau passerelle dans la RX1
    SimTime air_ns = 0;
    bool device_missed = false;               // le dispositif émet pendant la RX1
    bool delivered = false;                   // reçue par le dispositif (commandes appliquées)
    std::uint8_t req_dr = 0;                  // LinkADRReq : débit demandé
    std::uint8_t req_power_index = 0;         // LinkADRReq : index de puissance demandé
};

struct LoopResult {
    std::vector<LoopUplink> uplinks;
    std::vector<LoopDownlink> downlinks;
    std::vector<Interval> gateway_busy;       // émissions passerelle planifiées (ordre croissant)
    LoopMacQueueStats mac;                    // file MAC (commandes ponctuelles)
};

// `radios` : un paramètre radio par dispositif (le SF RX1 suit le SF montant courant).
// `regions` : un jeu de paramètres par dispositif (toujours lu). Le repos du duty cycle se calcule
// à partir de l'airtime de l'émission terminée (convention S2, voir le plan de boucle fermée).
SimStatus simulate_closed_loop(const EndDeviceSpec* devices, std::size_t device_count,
                               const plan::DeviceRadio* radios, const LoopRegion* regions,
                               const GatewaySpec& gateway, const PropagationSpec& prop,
                               const env::Environment* environment, const LoopOptions& options,
                               DeviceStats* per_device, SimulationStats& totals, LoopResult& out);

// Simule les liaisons montantes vers une passerelle. `per_device` doit contenir
// `device_count` entrées ; les compteurs y sont remis à zéro puis remplis.
// `environment` optionnel : relief et obstacles (nullptr = terrain plat sans obstacle).
// `trace` optionnel : reçoit une entrée par transmission, dans l'ordre temporel (vidé puis rempli).
// `gateway_busy` optionnel : périodes d'émission de la passerelle (intervalles [start, end)).
// Une trame reçue qui chevauche une de ces périodes est perdue (LostGatewayBusy).
// `causal` optionnel : descentes planifiées au fil de l'eau (S1), à la place de `gateway_busy`.
LSIM_API SimStatus simulate_uplinks(const EndDeviceSpec* devices, std::size_t device_count,
                                    const GatewaySpec& gateway, const PropagationSpec& prop,
                                    DeviceStats* per_device, SimulationStats& totals,
                                    const env::Environment* environment = nullptr,
                                    std::vector<TxRecord>* trace = nullptr,
                                    const std::vector<Interval>* gateway_busy = nullptr,
                                    const std::vector<MacReservation>* reservations = nullptr,
                                    const CausalDownlinks* causal = nullptr);

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
