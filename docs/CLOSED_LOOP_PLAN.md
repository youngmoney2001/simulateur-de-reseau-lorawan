# Boucle fermée dans le moteur : plan de refonte (MAC phase 2 : LinkADR, DutyCycle)

Statut : **S0, S1 et S2 faits pour la passerelle unique, sans jointure ni autre commande MAC (LinkADRReq et DutyCycleReq), y compris le câblage du bloc `mac:` et de `build_trace`.**

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
  - Erreur RX1 : une bande RX1 hors `{125, 250, 500}` kHz ou un SF RX1 hors 7..12 est signalée par
    `InvalidRadio` (planificateur, `plan_downlinks`, `lsim_plan_downlinks_v1`, chemin causal), et non plus
    par un code générique. Commit `d361f12`. Constat S1 résolu.
- **S2 : commandes en boucle fermée** : fait pour la passerelle unique, sans jointure ni autre commande MAC.
  - Moteur : `simulate_closed_loop` (`core/src/engine.cpp`, déclarations dans `engine.hpp`). Une seule
    exécution : une file d'événements (Check, Apply, Start, End) traite les émissions dans l'ordre temporel.
    À l'ordre des débuts et fins près, les règles sont celles du chemin causal.
  - Serveur : LinkADRReq décidé par `lorawan::adr::decide()` sur les 20 dernières trames reçues (SNR borné à
    ±50 dB, bruit −117 dBm à 125 kHz, NF 6 dB). Puissance : index de 0 à 7, pas de `power_step_tenth_db`.
    LinkADR est atomique : appliqué seulement si débit et puissance sont tous deux acquittés ; sinon refusé
    en bloc, sans nouvel essai. DutyCycleReq : `min(régional, 1/2^k)`, envoyé une fois au premier uplink
    reçu, puis répété jusqu'à DutyCycleAns.
  - Classe A : une descente est perdue si le dispositif émet pendant RX1 (`device_missed`, décidé par un
    événement Check à t_open + 1 s, avant les débuts simultanés). La commande est retentée au prochain
    uplink reçu ; l'émission suivante n'est pas retardée. Une descente est livrée seulement si elle a un
    créneau passerelle dans RX1, si le dispositif n'émet pas pendant RX1 et si son RSSI atteint la sensibilité
    RX1 (plus `device_rx_offset_db`).
  - Application : `max(t_open + 1 s, début + airtime)` pour une descente livrée. Réponse confirmée seulement si
    l'uplink qui la porte est reçu.
  - Puissance (corrigée) : index 0 = puissance configurée, plafonnée par la PIRE du plan ; chaque index
    retire le pas du plan. Les index réservés par le plan sont refusés par LinkADR. Table TXPower : EU868
    seulement (RP002-1.0.3 : PIRE +16 dBm, pas 2 dB, index 0 à 7 ; `lsim.regions.POWER_TABLES`). Un plan
    sans table refuse LinkADR : aucune puissance n'est inventée.
  - Duty cycle (corrigé) : limite réglementaire par index (sous-bande la plus restrictive à la PIRE de
    l'index, combinée au duty cycle du groupe), puis `min` avec DutyCycleReq. Repos après une émission =
    airtime de l'émission terminée × (1/D − 1). DutyCycleReq ne peut pas relever la limite réglementaire.
  - Divergence connue : le chemin sans commande (scénarios sans `link_adr` ni `duty_cycle_exponent`, dont
    les empreintes sont figées) garde l'ancienne convention, où le repos utilise l'airtime de l'émission
    qui démarre. Les deux conventions ne sont pas équivalentes quand D < 1. Migrer le chemin historique
    changerait ses résultats : à faire seulement après validation explicite.
  - API C : `lsim_simulate_closed_loop_v1` (statuts moteur 300+ et planification 950+). Pont Python :
    `python/lsim/closed_loop.py`.
  - Preuves : `core/tests/test_closed_loop.cpp` (parité sans commande avec le chemin causal, convergence
    ADR de SF12 à SF7, espacement du cycle de service après application, nouvel essai après RX1 manquée) ;
    `python/tests/test_closed_loop.py`. Invariants : empreintes `d2cb0fac…` (run) et `ed126d7f…` (trace)
    inchangées. Tests C++ et ASan/UBSan verts.
  - Branchement : `lsim.mac_loop` traduit le bloc `mac:` (`link_adr`, `duty_cycle_exponent`) en paramètres
    du moteur. `build_trace` et `run_scenario` l'utilisent dès qu'un de ces champs est actif (sinon, chemin
    historique inchangé). Événements : `mac_request` LinkADRReq / DutyCycleReq, `mac_answer` LinkADRAns /
    DutyCycleAns.
  - Refusé explicitement (erreur) : jointure, passerelles multiples, mesh, combinaison avec LinkCheck,
    DevStatus ou DeviceTime (leurs réservations ne sont pas encore portées dans la boucle fermée).
  - Non testé : une commande LinkADR à un index réservé, donc le refus NACK par le moteur (le code est en
    place, mais l'ADR ne demande jamais un tel index et aucune API n'injecte de commande).
  - Point fixe : le chemin Python de `build_trace` (`_build_trace_python`) reste pour les jointures, les
    passerelles multiples et le mesh ; la suppression du point fixe n'est donc pas encore complète.
- **S3 : contrat** : ABI versionnée (v3 des fonctions de trace), schémas régénérés, journal web.
- **S4 : mesh et multi-passerelles** : hors périmètre initial ; refusés avec commandes actives
  tant qu'ils ne sont pas portés.

## Risques
- Performance : la file d'événements doit rester O(n log n) ; garder la limite 200 000 émissions.
- Divergence Python/C++ en S0 : tests d'équivalence obligatoires avant toute suppression du code Python.
