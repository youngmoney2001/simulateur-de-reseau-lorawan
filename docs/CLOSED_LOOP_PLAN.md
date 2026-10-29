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
  - Décision de convention (validée par le propriétaire) : la convention cible du simulateur est le repos
    calculé sur l'airtime de l'émission terminée. Étapes : (1) test de divergence
    (`test_duty_convention_differs_from_start_airtime`, cas où un uplink plus long porte une réponse MAC) ;
    (2) empreintes historiques conservées tant que la migration n'est pas validée ; (3) contrat ABI versionné
    et schémas de configuration ; (4) commandes MAC restantes ; (5) migration explicite du chemin historique,
    avec validation des changements de trace et régénération des empreintes. Ne pas garder deux conventions
    sans les documenter.
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
  - Refusé explicitement (erreur) : jointure, passerelles multiples, mesh.
  - Réservations MAC (étape 4 de la priorité, faite) : LinkCheckReq, DeviceTimeReq et DevStatusAns
    passent dans la boucle fermée, avec LinkADR et DutyCycle. Le calendrier (`mac_plan`, `mac_loop.mac_slots`)
    donne, par émission (dispositif, rang) : les octets réservés (`extra_bytes`), et les drapeaux
    `kLoopMacLinkCheck`, `kLoopMacDeviceTime` (réponse portée par la descente de cet uplink) et
    `kLoopMacDevStatus` (DevStatusReq due dans cette descente). Le moteur (`lsim_simulate_closed_loop_v2`,
    `LoopOptions::mac`) : ajoute les octets réservés à la charge utile pour l'airtime ; ajoute les FOpts
    (LinkCheckAns 3 octets, DeviceTimeAns 6, DevStatusReq 1) ; et, pour DevStatusAns, retient la
    demande livrée (`dev.ds_pending`) pour la porter dans l'uplink suivant (bit 2 de `answer_mask`),
    confirmée seulement si cet uplink est reçu. Règles de conservation : l'octet DevStatusAns est réservé
    dans l'airtime dès que la requête est planifiée, même si elle est perdue (réservation conservatrice,
    comme `mac_plan`) ; seule la confirmation dépend de la réception. Les FOpts ne se tronquent jamais : voir « File MAC » ci-dessous.
  - File MAC (faite) : les commandes à état (LinkADR, DutyCycle) passent en premier, dans un budget de 15 octets de FOpts ; elles restent offertes tant qu'elles ne sont pas acquittées. Les commandes ponctuelles (LinkCheckAns 3 octets, DeviceTimeAns 6, DevStatusReq 1) entrent en file FIFO à leur uplink ; une commande qui tient part dans la descente, une autre est reportée (`deferred`) et expire après `mac_max_deferrals` reports (défaut 3, `expired`). Une réponse ou requête ponctuelle n'est pas retransmise : si sa descente n'est pas reçue, elle est perdue (`dispatch_lost`). Pas de priorité entre commandes ponctuelles au-delà de l'ordre d'arrivée ; le regroupement est implicite (plusieurs commandes compatibles tiennent dans une même descente).
  - États d'une commande ponctuelle : en attente (dans la file) ; transmise (placée dans une descente : `dispatched`), livraison confirmée ou non (`dispatch_lost` si la descente n'est pas reçue) ; terminée (réponse portée ou requête livrée) ; expirée (`expired`). Invariant testé : `enqueued = dispatched + expired + pending_at_end`.
  - Comptabilité des octets (option A, décision du propriétaire) : `MacByteAccounting` distingue les octets réservés par le calendrier (airtime), les octets présents dans les uplinks émis (`sent_bytes`, y compris les DevStatusAns émises), et les réponses confirmées (`confirmed_ds_answers`, DevStatusAns dans un uplink reçu). La réservation DevStatusAns n'est jamais comptée comme une émission ; la réservation non utilisée est `unused_reserved_ds_bytes`. Les résultats (airtime, collisions, descentes) ne changent pas : les compteurs sont additifs. Exposition : `TraceRun.mac_queue` et `TraceRun.mac_bytes` (Python) ; `lsim_loop_mac_counters` (API C v2). Non exposé dans les réponses de l'API HTTP : cela demande un changement de schéma, à faire après validation.
  - Validation de la file (avant toute extension des commandes MAC). Cycle de vie explicite par commande, journal `LoopResult::mac_items` (un élément par commande mise en file) : `Queued` (en attente) -> `Dispatched` (placée dans une descente planifiée) -> `Delivered` (descente reçue par le dispositif) ou `Lost` (descente non reçue) ; `Queued` -> `Expired` (plus de `mac_max_deferrals` reports). Une commande n'est placée dans une descente qu'une fois : une perte n'entraîne aucune retransmission.
    - Définitions exactes (code et compteurs) : `dispatched` = commandes incluses dans une descente planifiée (émise ou non, reçue ou non) ; `delivered` = parmi elles, celles dont la descente est reçue par le dispositif ; `dispatch_lost` = parmi elles, celles dont la descente n'est pas reçue ; `confirmed_ds_answers` (octets) = DevStatusAns présentes dans des uplinks reçus ; `pending_at_end` = commandes encore en file à la fin de la simulation ; `deferred` = reports cumulés, une par uplink reçu où la commande ne tient pas.
    - Invariants testés (C++ `check_mac_lifecycle`, et Python) : `enqueued = dispatched + expired + pending_at_end` ; `dispatched = delivered + dispatch_lost` ; `deferred = Σ reports par commande` ; `deferred ≥ expired` ; chaque commande `Dispatched`/`Delivered`/`Lost` a une descente qui porte son type, et la descente est reçue si et seulement si la commande est `Delivered` ; une commande n'est créée que par un uplink reçu (un uplink perdu ne porte rien) ; aucune commande en attente au-delà de `mac_max_deferrals`.
    - Charge réaliste testée : 8 dispositifs à 1,5 km d'intervalle, SF7 à SF9, uplinks toutes les 3 s en C++, LinkCheck, DeviceTime et DevStatus à chaque uplink, LinkADR et DutyCycle en attente. Avec décalage RX1 de 5 dB (C++) : 600 enqueued = 576 dispatched + 14 expired + 10 pending ; 576 = 360 delivered + 216 lost ; 210 reports ; 120 uplinks porteurs perdus. Avec 8 dispositifs à 9 km et 10 dB (Python, scénario `mac:` complet) : 780 = 731 + 28 + 21 ; 731 = 240 + 491.
    - Équité (hypothèse testée et infirmée). Hypothèse de départ : sous charge soutenue, DeviceTime (6 octets) occupe le budget restant et LinkCheck (3 octets) n'y tient jamais, donc expire systématiquement. Mesure : avec LinkADR et DutyCycle en attente (budget 8 octets), une seule DeviceTime tient par descente, et LinkCheck est servie en alternance (0 expiration). Ce sont les DeviceTimeReq qui expirent (27 sur 80, pas de descente reçue). Le tri stable par nombre de reports ne protège pas la plus grosse commande. La garantie d'équité qui tient est la borne d'attente : aucune commande ponctuelle n'attend au-delà de `mac_max_deferrals` reports, et chaque type est dispatché au moins une fois (test `test_mac_queue_fairness_bounded_wait`). Une politique qui protège les grosses commandes (réserver le budget, ou servir le plus petit d'abord) reste une décision à prendre ; elle change les résultats et n'est pas faite ici.
    - Pas de retransmission : test `test_mac_no_retransmission_of_lost_answers` (les descentes perdues ne portent que des commandes `Lost`, et leur nombre égale `dispatch_lost`).
    - API : `lsim_loop_mac_counters` ajoute `delivered` (ABI v2, non publiée). Le pont Python ne fournit `mac_queue` qu'en v2 ; la v1 renvoie `None`. Parité v1/v2 sans commande MAC testée en Python (`test_abi_v1_and_v2_agree_without_mac_commands`). Déterminisme testé (`test_queue_counters_are_deterministic`). Empreintes historiques inchangées (`scripts/mac_baseline_dump.py` : `d2cb0fac…` et `ed126d7f…`).
  - Option B (réservation DevStatusAns seulement si la requête est livrée) : à faire après la file, avec validation explicite des traces et des empreintes concernées.
  - Preuves : `core/tests/test_closed_loop.cpp` (`test_mac_reservations_and_answers`, `test_mac_queue_*`) ; `python/tests/test_mac_loop.py` (`test_byte_accounting_*`, `test_queue_defers_*`)
    (`test_reservations_closed_loop_matches_legacy_path` : sans ADR ni DutyCycle, la boucle fermée reproduit
    le chemin historique, en airtime, descentes et événements). Le chemin historique reste la référence de
    ce périmètre ; ses empreintes sont inchangées.
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
