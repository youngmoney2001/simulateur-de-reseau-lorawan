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
#include <vector>

#include "lsim/environment.hpp"
#include "lsim/lora_phy.hpp"

namespace lsim::sim {

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

// Dispositif terminal émettant périodiquement des trames confirmées-non.
struct EndDeviceSpec {
    Position position;
    std::uint8_t spreading_factor = 7;   // 7..12
    std::uint32_t payload_bytes = 10;    // 0..255
    double tx_power_dbm = 14.0;
    SimTime start_offset_ns = 0;
    SimTime period_ns = 60'000'000'000;  // 60 s
    std::uint32_t messages = 1;          // nombre de trames émises
};

struct GatewaySpec {
    Position position;
    double antenna_gain_dbi = 0.0;
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

struct DeviceStats {
    std::uint64_t sent = 0;
    std::uint64_t received = 0;
    std::uint64_t lost_sensitivity = 0;  // sous le seuil de sensibilité
    std::uint64_t lost_collision = 0;    // détruite par une collision non capturée
};

struct SimulationStats {
    std::uint64_t sent = 0;
    std::uint64_t received = 0;
    std::uint64_t lost_sensitivity = 0;
    std::uint64_t lost_collision = 0;
};

// Limites de sécurité / scalabilité.
inline constexpr std::size_t kMaxEndDevices = 10'000;
inline constexpr std::uint64_t kMaxTransmissions = 5'000'000;
inline constexpr double kMaxShadowingSigmaDb = 30.0;

enum class SimStatus : std::int32_t {
    Ok = 0,
    InvalidInput = 1,
    TooManyDevices = 2,
    TooManyTransmissions = 3,
    QueueFull = 4,
    InvalidEnvironment = 5,
    EnvironmentWorkLimit = 6,
};

// Simule les liaisons montantes vers une passerelle. `per_device` doit contenir
// `device_count` entrées ; les compteurs y sont remis à zéro puis remplis.
// `environment` optionnel : relief et obstacles (nullptr = terrain plat sans obstacle).
LSIM_API SimStatus simulate_uplinks(const EndDeviceSpec* devices, std::size_t device_count,
                                    const GatewaySpec& gateway, const PropagationSpec& prop,
                                    DeviceStats* per_device, SimulationStats& totals,
                                    const env::Environment* environment = nullptr);

}  // namespace lsim::sim
