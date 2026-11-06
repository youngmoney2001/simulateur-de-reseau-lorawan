// SPDX-License-Identifier: Apache-2.0
// Ordonnanceur radio : propriétaire de l'occupation de l'émetteur d'une passerelle.
//
// Rôle
// ----
// Ce composant détient la chronologie d'émission d'une passerelle et applique la règle **A6**
// (TS001-1.0.4 §3.3.5) : une descente commence **exactement** à l'ouverture d'une fenêtre de
// réception. Il n'y a **aucun décalage à l'intérieur d'une fenêtre** :
//
//   1. la fenêtre RX1 est examinée à son ouverture ;
//   2. si elle est indisponible, la fenêtre RX2 est examinée à **sa propre** ouverture ;
//   3. si RX2 est indisponible (ou non demandée), **rien n'est émis** : verdict `NotPlaced`,
//      et **aucune occupation** n'est enregistrée.
//
// Une fenêtre est indisponible si et seulement si une émission déjà planifiée **chevauche
// réellement** l'intervalle `[ouverture, ouverture + durée)`. Ce n'est pas une borne de fin :
// une fenêtre située après la fin d'une émission antérieure et avant le début d'une émission
// postérieure est libre.
//
// Périmètre
// ---------
// L'ordonnanceur n'absorbe ni la logique MAC, ni l'ADR, ni les collisions, ni la sensibilité, ni
// les réémissions. Il reçoit des fenêtres candidates déjà constituées (ouverture et durée
// d'émission) et rend un placement ainsi que l'occupation effective.
//
// État actuel (jalon U0.1)
// ------------------------
// Un seul émetteur : l'occupation est une liste unique, à l'image de la boucle fermée dont ce
// composant est extrait. Le passage au multi-passerelles (une occupation par passerelle) est
// prévu à l'étape U0.5 ; il étendra cette classe sans en changer le contrat de placement.
#pragma once

#include <cstdint>
#include <vector>

// Composant volontairement **sans dépendance** : il n'inclut aucun en-tête du projet, de sorte que
// `engine.hpp` et `downlink_plan.hpp` puissent l'un et l'autre s'en servir — `engine.hpp` incluant
// déjà `downlink_plan.hpp`, une dépendance de ce fichier vers le moteur rendrait la réciproque
// impossible.
namespace lsim::radio {

using SimTime = std::int64_t;  // nanosecondes

// Intervalle **semi-ouvert** `[start, end)`.
struct Interval {
    SimTime start = 0;
    SimTime end = 0;
};

// Verdict d'un placement.
enum class PlacementVerdict : std::uint8_t {
    NotPlaced = 0,  // aucune fenêtre disponible : rien d'émis, aucune occupation
    PlacedRx1 = 1,  // émise à l'ouverture de RX1
    PlacedRx2 = 2,  // émise à l'ouverture de RX2 (repli)
};

// Résultat d'un placement.
//
// `t_open_ns` et `air_ns` sont ceux de la **dernière fenêtre examinée**, y compris lorsqu'aucune
// n'a abouti : l'appelant s'en sert pour situer la fenêtre perdue. C'est le comportement dont
// dépend la boucle fermée pour calculer la fermeture de fenêtre et reconnaître un repli RX2.
//
// `start_ns` vaut -1 si et seulement si le verdict est `NotPlaced`.
struct Placement {
    PlacementVerdict verdict = PlacementVerdict::NotPlaced;
    SimTime t_open_ns = 0;
    SimTime air_ns = 0;
    SimTime start_ns = -1;
};

// Occupation de l'émetteur d'une passerelle et placement A6 des descentes.
class RadioScheduler {
public:
    // Occupation initiale : émissions déjà décidées avant le début de la simulation.
    void seed(const std::vector<Interval>& intervals);

    // Vrai si une émission planifiée chevauche `[start, end)`.
    bool transmitting(SimTime start, SimTime end) const;

    // Place une descente selon A6.
    //
    // `rx2_allowed` faux : la fenêtre RX2 n'est jamais examinée (comportement opt-in des
    // paramètres régionaux — un dispositif sans RX2 renseignée ne tente pas de repli).
    Placement place(SimTime rx1_open_ns, SimTime rx1_air_ns,
                    SimTime rx2_open_ns, SimTime rx2_air_ns, bool rx2_allowed);

    // Place une émission à une **fenêtre unique**, sans repli : émise exactement à `open_ns`, ou
    // refusée. Refusée n'occupe pas l'émetteur.
    //
    // Le planificateur (jalon U0.3) l'emploie pour les deux phases : il garde la responsabilité de
    // l'ordonnancement — une fenêtre RX2 entre dans la file à sa propre ouverture, après les
    // fenêtres plus précoces déjà déposées, ce que `place()` ne sait pas exprimer puisqu'il
    // enchaîne RX1 puis RX2 dans le même appel. La **règle** de placement reste entièrement ici :
    // départ exact à l'ouverture, chevauchement réel, et occupation seulement si acceptée.
    bool place_at(SimTime open_ns, SimTime air_ns);

    // Émissions réellement planifiées, croissantes et disjointes, dans l'ordre de placement.
    const std::vector<Interval>& occupancy() const noexcept { return busy_; }

    void clear() noexcept { busy_.clear(); }

private:
    // Insère en gardant la liste croissante et disjointe (prérequis de `transmitting`).
    void insert(SimTime start, SimTime end);

    std::vector<Interval> busy_;
};

}  // namespace lsim::radio
