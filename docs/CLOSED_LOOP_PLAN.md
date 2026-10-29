# Boucle fermée dans le moteur : plan de refonte (MAC phase 2 : LinkADR, DutyCycle)

Statut : **décisions prises, implémentation non commencée.**

## Décisions du propriétaire
1. **Unification** : les descentes sont gérées dans le moteur natif, en une seule exécution.
   Le point fixe actuel de `build_trace` (`MAX_ITERATIONS`, occupation passerelle par les
   descentes Python) est à supprimer. Correction : l'état précédent du dépôt n'était pas
   « une seule exécution » pour les descentes, seulement pour les réservations MAC.
2. **Classe A et RX1** : une commande est perdue si le dispositif émet pendant RX1 ; elle est
   retentée à l'uplink suivant. La prochaine émission n'est pas retardée.
3. **Décision ADR** : `python/lsim/adr.py` (et `core/include/lsim/adr.hpp`) fournit la décision
   côté serveur.

## Contrainte d'invariance (non négociable)
Les scénarios **sans bloc `mac:`** doivent garder leurs résultats octet pour octet. Référence :
`scripts/mac_baseline_dump.py`, empreintes SHA-256 dans `docs/MAC_PLAN.md`. Un changement de
modèle de descente qui les modifie doit être explicitement validé avant le merge.

## Étapes
- **S0 : référence C++ des descentes : fait pour le périmètre « passerelle unique, sans jointure ni MAC »**.
  Code : `core/src/downlink_plan.cpp` (`lsim::plan`), API `lsim_plan_downlinks_v1` (`c_api_plan.cpp`, statuts
  950+), pont `python/lsim/downlink_plan.py`. `build_trace` l'utilise pour ce périmètre (point fixe conservé).
  Preuves : tests C++ (`test_downlink_plan.cpp`) ; parité avec l'oracle Python sur 60 scénarios aléatoires,
  scénarios denses (RX1 manquées), traces converged (occupation passerelle, uplinks perdus) et descentes perdues
  (`test_downlink_plan_parity.py`) ; empreintes sans MAC identiques à la base.
  Non porté (reste Python) : jointure, commandes MAC, mesh, multi-passerelles.
  Constat : 2 scénarios denses sur 40 (seeds 11 et 38) n'atteignaient pas le point fixe de `build_trace`.
  Résolu par S1 (voir ci-dessous).
  Décision de modèle conservée de Python : la passerelle réserve son émission même si le dispositif émet pendant
  RX1 (`device_missed` n'affecte que les événements).
- (Détail initial, à titre de référence) porter `_downlink_jobs`, `_schedule_gateway` et
  `_events` (`python/lsim/trace_events.py`) vers le moteur, sans commande MAC. Critère : sorties
  identiques à Python sur `examples/` et sur les scénarios de test (avec et sans descentes,
  classes A/B/C, mesh exclu au départ).
- **S1 : moteur à événements causal** : chaque dispositif a une machine d'état (prochaine
  émission connue dès le début de la précédente). Issue d'un uplink décidée à sa fin ; RX1 à
  fin+1 s ; occupation passerelle = descentes du moteur. Critère : identique à S0 sans commande.
  **Fait pour le périmètre « passerelle unique, sans jointure ni MAC »**.
  - Moteur : `simulate_uplinks(..., causal)` (paramètre `CausalDownlinks`, exclusif avec `gateway_busy`).
    Les trames sont décidées par fin croissante ; chaque trame reçue planifie sa descente à sa fin via
    `plan::DownlinkScheduler` (`downlink_plan.hpp`), qui ne lit que des descentes déjà planifiées. Une
    descente chevauchant une trame commence au plus tôt à fin' + RX1 avec fin' < fin : l'occupation est
    connue à temps. Sans `causal`, le chemin historique est inchangé.
  - API C : `lsim_simulate_uplinks_causal_v1` (options et radios validées avant simulation).
  - Python : `lsim.downlink_plan.simulate_causal` ; `build_trace` l'utilise pour ce périmètre, en une
    seule exécution, sans point fixe. Contrôle : l'occupation du moteur doit égaler celle du planificateur.
    Le point fixe Python reste dans `_build_trace_python` (jointure, MAC, oracle de test).
  - Preuves : sur 281 scénarios denses dont le point fixe converge, trace, occupation, événements et
    compteurs sont identiques à l'ancien point fixe ; les seeds 11 et 38 (sans point fixe avant) sont
    résolus. Empreintes d'invariance inchangées : run `d2cb0fac…`, trace `ed126d7f…`.
    Tests : `test_downlink_plan.cpp` (planificateur incrémental), `test_downlink_plan_parity.py`
    (sans `skip`).
  - Non porté : jointure, MAC (S2), mesh et multi-passerelles.
- **S2 : commandes en boucle fermée** : LinkADRReq et DutyCycleReq émises par le serveur,
  appliquées (SF, puissance, duty cycle) à partir de l'émission suivant leur réception.
  LinkADRAns/DutyCycleAns : réservation conservatrice dans l'uplink suivant la commande ; l'octet
  n'est compté comme émis qu'après confirmation. Critère : déterminisme, trace distinguant
  planifié et effectif.
- **S3 : contrat** : ABI versionnée (v3 des fonctions de trace), schémas régénérés, journal web.
- **S4 : mesh et multi-passerelles** : hors périmètre initial ; refusés avec commandes actives
  tant qu'ils ne sont pas portés.

## Risques
- Performance : la file d'événements doit rester O(n log n) ; garder la limite 200 000 émissions.
- Divergence Python/C++ en S0 : tests d'équivalence obligatoires avant toute suppression du code Python.
