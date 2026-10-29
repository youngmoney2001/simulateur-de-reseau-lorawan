# Journal des changements

## 0.1.0 (non publiée)

### Boucle fermée : LinkADRReq et DutyCycleReq (passerelle unique)
- Bloc `mac:` : `link_adr` (LinkADRReq, décision ADR côté serveur) et `duty_cycle_exponent` (DutyCycleReq, 1/2^k). Actifs seulement si demandés ; sans ces champs, scénarios, résultats et empreintes inchangés. Schémas régénérés.
- `build_trace` et `run_scenario` passent par la boucle fermée (une seule exécution native, descentes créées par le moteur) dès que l'un de ces champs est actif. Événements `mac_request` (LinkADRReq, DutyCycleReq) et `mac_answer` (LinkADRAns, DutyCycleAns).
- **Puissance** : index 0 = puissance configurée plafonnée par la PIRE du plan ; pas du plan par index ; index réservés refusés. Table TXPower : EU868 uniquement (RP002-1.0.3, PIRE +16 dBm, pas 2 dB, index 0 à 7). Un plan sans table refuse LinkADR.
- **Duty cycle** : limite réglementaire par index (sous-bande à la PIRE de l'index, combinée au duty cycle du groupe) ; DutyCycleReq ne fait que la réduire. Repos après une émission = airtime de l'émission terminée × (1/D − 1).
- **Refusé explicitement** : jointure, passerelles multiples, mesh.
- **Réservations MAC dans la boucle fermée** : LinkCheckReq, DeviceTimeReq et DevStatusAns réservent leurs octets dans le temps d'antenne ; LinkCheckAns, DeviceTimeAns et DevStatusReq sont portés par la descente de l'uplink concerné. DevStatusAns est confirmée à la réception de l'uplink suivant. Nouvelle API `lsim_simulate_closed_loop_v2` (la v1 est conservée). Sans ADR ni DutyCycle, la boucle fermée reproduit le chemin historique (test de parité).
- **File MAC** : les FOpts ne dépassent jamais 15 octets. LinkADR et DutyCycle passent en premier ; LinkCheckAns, DeviceTimeAns et DevStatusReq attendent dans une file FIFO et sont reportées (puis expirent après 3 reports) si elles ne tiennent pas. Compteurs `enqueued`, `dispatched`, `dispatch_lost`, `deferred`, `expired`, `pending_at_end` (API C v2 et `TraceRun.mac_queue`).
- **Octets MAC** : `TraceRun.mac_bytes` sépare octets réservés, octets émis et réponses DevStatus confirmées. Les résultats de simulation ne changent pas.
- Tests : `core/tests/test_closed_loop.cpp`, `python/tests/test_mac_loop.py`. Documentation : `docs/CLOSED_LOOP_PLAN.md`.

### Commandes MAC : phase 1, étape 1
- Bloc `mac:` du scénario (`link_check_every`, `device_status_every`, bornes 0 à 1000 ; 0 = désactivé). Inclus dans l'empreinte SHA-256 ; absent = empreinte inchangée. Schémas `scenario_input`, `run_create` et `validate_request` régénérés.
- **Sans effet sur le calcul pour l'instant** : le moteur n'émet pas encore les commandes. Plan complet : `docs/MAC_PLAN.md`.
- Tests : `python/tests/test_scenario_mac.py`.

### Animation des trames (studio)
- **Lecteur** sous le panneau de simulation : lecture et pause, vitesses ×1 à ×300, curseur de temps, instant courant en secondes simulées.
- **Plan animé** : chaque saut apparaît comme une trame qui se déplace de sa source vers sa destination pendant 1 s simulée, puis reste visible 4 s. Couleur : vert (livré), rouge (perdu), gris (autre). Une remise au réseau est un anneau autour de la passerelle.
- **Journal par saut** : une ligne par événement (temps, source, type, résultat), dépliable sur ses sauts ; un clic place l'horloge sur l'événement.
- **Source des données** : `GET /api/v1/runs/{id}/events` et `GET /api/v1/runs/{id}/devices` (pages de 500). Le mapping `dev:<index>` vers le capteur vient de la page des dispositifs (groupe = identifiant du capteur) ; `gw:<nom>` désigne directement la passerelle.
- **Limite** : au-delà de 20 000 événements, l'animation n'est pas chargée (message dans l'état de simulation). Les résultats restent affichés.
- **Tests** : `web/tests/animation.test.mjs` (logique pure) et l'étape « animation » du test e2e (horloge qui avance, au moins une trame dessinée).


### Studio web (`web/studio.html`) et verrou de base
- **Interface** : page `web/studio.html` (Vite, à côté de la carte de résultats `index.html`, inchangée). Plan éditable (ajout, glisser-déposer, retrait), console CLI par équipement (historique aux flèches, erreur au caret), réglages capteur avec validation côté studio et serveur, simulation avec résultats par passerelle (compteurs, latence p95, relais mesh), exercices (énoncé, indices avec pénalité, notation, journal), sessions multiples (liste, nouvelle session, suppression).
- **API ajoutée** : `GET /api/v1/sessions` (sessions du compte), `DELETE /api/v1/sessions/{id}` (204), `POST /api/v1/sessions/{id}/nodes/{node_id}/position` (`Position`). Schémas `study_session_list` et `study_position` régénérés.
- **Verrou de base** : `make_server` prend un verrou exclusif `<runs-db>.lock` (flock) ; un second serveur sur le même fichier est refusé avec `RuntimeError`. Libéré à `server_close`.
- **Profil de relais composite** `rak5146-rak5148` (`gateway_profiles.py`) : RAK5146 pour l'accès sous-GHz (EU433, EU868, RU864, CN470, US915, AS923, AU915, KR920, IN865 ; 27 dBm ; -139 dBm à SF12 / 125 kHz ; 8 canaux) et RAK5148 pour le lien mesh 2,4 GHz. Sources : fiche RAK5146, fiche RAK5148, page produit RAK « Outdoor Gateway Mesh with 2.4G Backhaul » ; compatibilité logicielle à confirmer par le constructeur. Le compilateur l'utilise pour tous les relais (`MESH_PROFILE`).
- **Réserves du profil `rak5146-rak5148`, distinctes** (décision de l'auteur) : (1) *compatibilité logicielle* : statut « à valider » (`software_validated=False`, `software_status`), levé par un essai réel sur ChirpStack Gateway OS (détection des deux concentrateurs, accès EU868 et backhaul mesh 2,4 GHz, relais entre les radios, redémarrage, perte du lien mesh) ou une confirmation RAK ; le compilateur le signale dans `notes`. (2) *fidélité radio* : voir l'entrée « Sensibilité dans le budget de liaison » ci-dessous.
- **Sensibilité dans le budget de liaison** (modèle `decalage-uniforme-v1`, `SENSITIVITY_MODEL`) : la sensibilité publiée d'un profil entre dans la réception montante des passerelles d'accès, sous forme d'un décalage uniforme du seuil de référence du moteur. Décalage = sensibilité publiée − sensibilité de référence à **un point publié** du profil (`rx_sensitivity_point`). Résultat : RAK5146 (-139 dBm à SF12 / 125 kHz, référence moteur -136 dBm) → **-3 dB**, appliqué à toutes les combinaisons SF/BW ; RAK5148 (point SF12 / 203 kHz hors des bandes du moteur) et RAK7249 (aucun point publié) → 0 dB. Champ `rx_sensitivity_offset_db` sur `GatewaySpec` (C++), `lsim_gateway` (C) et `Gateway` (Python), borné à ±20 dB. Passerelle sans profil : 0 dB, résultats inchangés.
  - **Hypothèses non calibrées** : décalage uniforme sur SF et BW (la fiche ne publie qu'un point) ; descente (seuil du dispositif) et lien mesh 2,4 GHz (table SX1280) inchangés .
  - **Avant/après** : sur `examples/mesh_relais_quartier.yaml` (capteurs SF9, rayon 3,5 km) aucune perte par sensibilité, donc résultats identiques (2840 reçues sur 3000) ; cet exemple ne teste pas le seuil. Cas de comparaison (même topologie, capteurs SF12 jusqu'à 40 km) : sans décalage, 1100 reçues, 1140 pertes par sensibilité, 760 collisions (PDR 36,7 %) ; avec décalage, 1550 reçues, 110 pertes par sensibilité, 1340 collisions (PDR 51,7 %). Le décalage fait donc entendre plus de trames, et les collisions augmentent d'autant.
  - **Carte de couverture** (`geo.py`) : même seuil que la simulation (référence + décalage), donc le rayon d'une passerelle composite grandit de 3 dB dans la carte comme dans le calcul.
  - **Tests** : `python/tests/test_gateway_sensitivity.py` (effet au seuil dans les deux sens, valeur neutre par défaut, bornes ; décalages du catalogue).
- **RAK7249 vérifié** : la fiche RAK7249 (WisGate Edge Max) donne -139 dBm (min) pour la réception LoRa, sans spreading factor ni largeur de bande : pas de point, donc 0 dB (confirmé par l'auteur).
- **Prochaine évolution** : mesurer la sensibilité réelle du RAK5146 et de la descente, et remplacer le décalage uniforme par un modèle par SF/BW dès qu'un point mesuré existe (nouvelle version de modèle).
- **Règle de validation** : un relais dont le profil a des bandes d'accès ne peut pas servir un groupe déclaré dans une région absente de ces bandes (`rak5148` seul, EU868 : refusé). Les groupes sans région ne sont pas contraints.
- **Limite connue** : les indices révélés ne sont pas relus au rechargement de la page (le serveur applique la pénalité, l'interface ne la réaffiche que dans l'onglet courant).
- Tests : `web/tests/studio-modules.test.mjs` (8, `npm test`), `web/tests/e2e/studio.e2e.mjs` (navigateur Chromium réel contre l'API, `npm run test:e2e`), `test_study_persistence.py` (+1, verrou), `test_study_simulate.py` (+2, déplacement et liste/suppression).

### Panneau d'étude : simulation d'une session, topologie éditable, persistance (servis)
- **Simulation depuis la session** : `POST /api/v1/sessions/{id}/simulate` compile la topologie et les configurations CLI en scénario (`lsim/study_compile.py`) et crée le run par le chemin de `POST /runs` (mêmes validations). La réponse donne `run_id`, `links` et `notes`. La liaison au résultat est automatique à la fin du run : `POST /sessions/{id}/simulation` sans `links` lie les passerelles du run compilé.
- **Réglages capteur** : `Node.sensor` (SF, charge, puissance, période, messages, départ, plan, canal). Ils sont les paramètres d'un groupe de simulation nommé comme le capteur.
- **Topologie éditable** : `POST /sessions/{id}/nodes` (ajout, 64 au plus, identifiant unique), `DELETE /sessions/{id}/nodes/{node_id}`, `POST /sessions/{id}/nodes/{node_id}/sensor`. Le serveur n'accepte pas `PUT` : c'est `POST` qui remplace les réglages.
- **Règles de compilation** : passerelle à interface lora arrêtée exclue du run ; avec relais, exactement une frontière active ; réglages mesh (SF, bande) identiques entre frontière et relais (422 sinon) ; sauts : plus petite valeur réglée ; mode mesh incohérent avec le rôle (422) ; plan régional et sous-bande identiques pour toutes les passerelles. Défauts appliqués (EU868, sous-bande 1) et réglages non modélisés listés dans `notes`.
- **Persistance** : sessions, configurations CLI, liaisons et journal sont écrits dans le fichier SQLite des runs (`--runs-db`, `lsim/study_store.py`) et relus au démarrage. Expiration de 4 h d'inactivité appliquée après redémarrage. Une lecture est écrite au plus une fois par minute.
- **Seuil de latence validé** : 300 ms (p95 remise au LNS par la frontière), décision de l'auteur.
- **Exercices** : chaque topologie de départ contient un capteur. Dans les exercices à relais, le capteur émet à -10 dBm à 1500 m, la frontière ne l'entend pas. L'exercice de latence envoie 20 messages. Son indice mentionne la bande mesh : à 203 kHz, p95 ≈ 790 ms (échec) ; à 812 kHz, ≈ 228 ms (réussite).
- **Changement de comportement** : `unlinked` (réponse de liaison) liste aussi les capteurs, qui ne sont jamais liés à une passerelle.
- Tests : `test_study_compile.py` (18), `test_study_simulate.py` (17), `test_study_persistence.py` (6, dont un redémarrage du serveur HTTP). Schémas `v1` régénérés (`study_sensor`, `study_simulate`, `study_simulate_request`). Suite Python : 1489 passés, 1 ignoré.

### Panneau d'étude : critères de connectivité et de latence, indices, journal (servis)
- **Critères** : `_mesh_inbound(node, from_node)` (lien mesh observé entre deux passerelles liées, via `mesh_inbound` du résumé) et `_latency_p95_at_most(node, 300 ms)` (latence p95 remise au LNS).
- **Indices** : `POST /api/v1/sessions/{id}/hints`. Deux par exercice ; chaque indice révélé retire `HINT_PENALTY` = 2 points, plancher 0. Plus d'indice : 409 ; exercice différent : 422 ; exercice ou session d'un autre compte : 404.
- **Journal** : `GET /api/v1/sessions/{id}/attempts` (50 au plus par session ; numéro, instant, exercice, score, indices, réussite). Aucune commande CLI, aucun secret.
- **Publication** : les schémas du panneau sont dans `schemas/api/v1` (généré par `api_contract`). Le dossier `schemas/api/study-draft/` est supprimé et `study_contract` n'écrit plus de fichiers.
- Tests : `test_study_exercises.py` (23), `test_study_contract.py` (6), `test_study_api.py`, `test_study_cli.py`.

### Métriques par passerelle dans le résumé de run (`trace_metrics.py`)
- Par passerelle : `latency_samples`, `latency_p50_ms`, `latency_p95_ms` (uplinks de donnée remis au LNS, de l'émission à la remise), et `mesh_inbound` (sauts mesh livrés par émetteur). Champs optionnels dans `GatewayReportOut`.
- Tests : `test_trace_metrics.py` (9), plus un test de publication dans `test_study_exercises.py`.

### Correction de la trace des uplinks relayés (`trace_events.py`)
- **Changement de comportement** : pour un uplink livré par le mesh, le saut NS part de la passerelle frontière à `fin + border_delay` et non plus de la fin de réception du premier relais. L'attribution va à l'émetteur réel (`_direct_deliverer`). Un relais ne livre jamais en direct. Les latences issues de la trace changent donc pour ces uplinks.

### Panneau d'étude : exercices notés et liaison explicite (servis)
- `GET /api/v1/exercises` (catalogue sans critères ni solution) et `POST /api/v1/exercises/{id}/submit` (le client n'envoie que `session_id`; le serveur note l'état qu'il détient).
- Trois exercices : EU868, relais à deux sauts, US915 sous-bande 2 avec réception. Aucun indice servi (`hints_available: 0`).
- `POST /sessions` : `exercise_id` acceptée (topologie de l'exercice, `nodes` vide). `nodes` vide autorisé.
- **Changement** : la liaison à un run ne se fait plus par nom. `POST /sessions/{id}/simulation` reçoit `links: [{node_id, gateway}]` ; toute association invalide annule la requête entière.
- Limites de sessions appliquées sous verrou, testées en concurrence.
- Schémas `study-draft` régénérés (`study_simulation_bind`, `study_session_create`). Schémas `v1` inchangés.
- Tests : `test_study_exercises.py` (14), `test_study_api.py` (27). Suite Python : 1431 passés, 1 ignoré.

### Panneau d'étude : sessions, CLI et liaison aux résultats (servis)
- Routes : `POST /api/v1/sessions`, `GET /api/v1/sessions/{id}/topology`, `POST /api/v1/sessions/{id}/cli`, `POST /api/v1/sessions/{id}/simulation`. Propriétaire filtré (404 pour un autre compte), bornes et expiration en mémoire.
- `show lorawan counters` et `show mesh counters` affichent les compteurs réels de la passerelle associée dans le run lié (association explicite, voir ci-dessous). Les `show` non alimentés par le moteur (voisins, routes, appareils) sont retirés de la grammaire.
- Exercices : servis depuis (voir l'entrée « exercices notés » ci-dessus).
- Tests : `python/tests/test_study_api.py` (20). Suite Python : 1412 passés, 1 ignoré.

### CLI d'équipement du panneau d'étude (phase 4, brouillon)
- `python/lsim/study_cli.py` : grammaire IOS côté serveur (modes utilisateur, privilégié, configuration, interface), abréviations par préfixe, marqueur `^` à la colonne fautive, `?` et Tabulation, `show running-config` n'affichant que les paramètres positionnés (aucun secret n'existe encore ; masquage par construction, `******`).
- Commandes de vérification (`show mesh neighbors`, `show lorawan counters`, etc.) répondent « aucune simulation » tant qu'aucun résultat n'existe.
- Syntaxe `lorawan server ADDR up-port N down-port N` retenue (spec §4.2). Tests : `python/tests/test_study_cli.py` (19). Aucune route servie.

### Restes de la liste mesh : validate, export, tests de service
- `POST /api/v1/scenarios/validate` accepte un `protocol` optionnel (additif) : la règle de trame mesh y est appliquée comme à la création (problème `validation_error` avec le champ). Schéma `validate_request` régénéré.
- Export mesh : `MeshSummary.lost_mesh` (trames décodées à l'accès puis perdues sur le mesh). Avant, le total exporté ne s'équilibrait pas (sur `lossy`, 9 trames manquantes) ; désormais sent = received + pertes accès + lost_mesh, égal à la trace. Ajouté au rapport et à la CLI.
- TLS : le test vérifie qu'un client sans confiance dans le certificat échoue et qu'un client en clair n'obtient jamais de 200. Redémarrage : déjà testé (runs terminés relus, runs en file marqués `failed`).
- Étape 3 (`web/`) : non commencée. Choix de l'auteur : commencer par le contrat d'API du panneau d'étude.
- Contrat du panneau d'étude (brouillon, `docs/STUDY_PANEL_SPEC.md` §7) : `python/lsim/study_contract.py`, schémas `schemas/api/study-draft/` (8 fichiers, séparés de `v1`). Règles portées par les types : clés uniquement « ****** », dépôt d'exercice sans résultat, catalogue sans critères ni solution, tailles bornées. Aucune route servie. Tests : `python/tests/test_study_contract.py`.

### Limites mesh et RX2 corrigées
- RX2 modélisée (repli) : une descente qui ne peut partir en RX1 (passerelle occupée au-delà de la fenêtre RX1) tente RX2, ouverte 1 s après RX1 (fin + 2 s ; join : +6 s), fenêtre de 1 s, même passerelle, SF `rx2_sf` du plan régional (12 en EU868). `rx2_sf = 0` désactive le repli. Une émission du dispositif pendant RX2 la rend perdue, et la sensibilité reste finale. Fréquence RX2 non modélisée (le repli garde la fréquence RX1).
- **Changement de résultats par défaut** : des descentes autrefois `GatewayBusy` sont désormais servies en RX2 (`DownlinkRecord.rx_window = 2`, départ entre t_open + 1 s et t_open + 2 s). Champs ajoutés en fin de struct : `lsim_downlink_rule.rx2_sf`, `lsim_downlink_record.rx_window`. La trace API v1 ne porte pas `rx_window` : l'instant de départ le révèle.
- Un scénario dont les régions ont des RX2 de SF différents est refusé (un seul débit de repli par scénario).
- Passe jointe : montant et descente partagent une seule passe mesh (`lsim.mesh_pass.mesh_pass`, `forward_frames` avec destination par trame). Ils partagent donc le temps d'antenne, la suppression des doublons et l'attente. Les descentes vers des relais différents se disputent désormais le mesh. La charge par relais est comptée une fois, sur le journal complet.
- Point fixe : sur (départs au plus tôt des descentes, délai frontière de chaque uplink), par message. Cap inchangé à 64.
- Natif : `lsim_mesh_forward_routed_log` (destination par trame) ; `lsim_mesh_forward[_log]` reste un wrapper aux résultats identiques.
- Enveloppe mesh : 14 o (montant) et 15 o (descente) confirmés par la documentation ChirpStack (MHDR, métadonnées, relay ID, MIC). Non vérifiés sur un relais physique. La taille de trame relayée par défaut (32 o) reste une hypothèse.
- Limite trouvée : une trame mesh est bornée à 255 o. Une descente de plus de 227 o (PHY 13 + charge + enveloppe 15) ou une charge montante relayée de plus de 228 o (13 + charge + enveloppe 14) est refusée : 422 `validation_error` à la création d'un run (champ `protocol.downlink_payload_bytes` ou `scenario`), et `ValueError` dans `build_multi_trace` pour les appelants hors API. Montant contrôlé seulement si un relais achemine et si `frame_size` vaut `device`.
- Tests : `python/tests/test_rx2_fallback.py` (repli avec `dl_ready_ns`, désactivation, validation du SF, SF issu du plan), `test_mesh_trace.py` (passe jointe, descente perdue sans airtime, départ non avant le premier saut). Suite : 1359 passés, 1 ignoré.

### Descentes et charge par relais sur mesh
- Moteur natif (`simulate_uplinks_multi_downlinks`) : paramètre optionnel `dl_ready_ns` (départ au plus tôt de chaque descente, par émission ; `kDownlinkNever` pour une descente jamais acheminée). API C : `lsim_simulate_uplinks_multi_dl` prend `dl_ready_ns` et `ready_count` en fin de signature (NULL pour l'ancien comportement). `simulator.simulate_multi_downlinks(..., dl_ready_ns=...)`, `DL_READY_NEVER`.
- Descentes sur mesh (`lsim.mesh_pass.mesh_pass`, passe partagée avec le montant depuis la section ci-dessus) : chaque descente part de la frontière à l'arrivée de son uplink et est routée jusqu'au relais cible (graphe rooted au relais, une copie, 15 o d'enveloppe). Le relais la sert en RX1 après son arrivée. `join`, `confirmed_uplinks` et `downlink_every` acceptés en mesh (API et trace).
- Point fixe : la trace (passe moteur) et les arrivées mesh des descentes dépendent l'une de l'autre ; itération bornée (`MAX_MESH_RETURN_ITERATIONS` = 64, levée explicite au-delà). Hors mesh, une seule passe.
- Trace : événements `mesh_downlink_hop` (sauts descendants) ; issue `lost_mesh` d'une descente perdue sur le mesh (un saut `ns` → relais) ; issue `mesh_late` d'une `rx_window_missed` quand l'arrivée mesh dépasse la fenêtre RX1. Une descente d'un uplink non remis au LNS n'est pas émise. Airtime de réception : seules les descentes reçues (`_DELIVERED_DOWNLINK_OUTCOMES`) comptent.
- Charge mesh par relais : `gateways[].mesh_transmissions`, `mesh_busy_ns`, `mesh_lost_collision`, `mesh_lost_half_duplex`, `mesh_suppressed` (uplink et descente additionnés, comptés sur l'émetteur). Absents pour les passerelles sans mesh.
- Les deux limites documentées ici (RX2 et passe jointe) sont corrigées dans la section « Limites mesh et RX2 corrigées » ci-dessus.
- Contrat : `EventKind` += `mesh_downlink_hop` ; `HopOutcome` += `lost_mesh` ; `GatewayReportOut` += 5 champs optionnels. Schémas régénérés. Tests : `python/tests/test_mesh_trace.py` (descentes par saut, concordance de charge avec le journal, point fixe déterministe, descente perdue), `test_api_server.py` (descentes acceptées, champs par relais).

### Mesh par saut dans la trace API

- `lsim.mesh_pass.mesh_pass` : passe mesh extraite de `run_scenario` et partagée avec la trace (`build_multi_trace`). Sur `examples/mesh_relais_quartier.yaml`, totaux, résumé mesh et compteurs par dispositif sont identiques à la version précédente.
- Natif : `lsim_mesh_forward_log` (et `mesh::forward` avec journal optionnel) renvoie chaque émission mesh avec son saut prévu, son issue et ses instants ; tampon borné, taille requise renvoyée si trop petit (statut 810, réessai côté Python).
- Trace : événements `mesh_hop` ; issue `lost_mesh` pour les trames décodées non remises ; champs optionnels `lost_mesh` (totaux, par dispositif). Absents hors mesh.
- API v1 : `mesh` accepté ; les refus `join`, `confirmed_uplinks` et `downlink_every` en mesh ont été levés (voir « Descentes et charge par relais sur mesh »). Schémas régénérés (`trace_event`, `trace_page`, `run_summary`, `device_page`).
- Tests : `python/tests/test_mesh_trace.py` (concordance avec `run_scenario`, journal natif, variante avec pertes mesh), `test_mesh.py` (journal, invariants, réessai du tampon), `test_api_server.py` (run mesh réel, descentes acceptées).

### Join en multi-passerelles

- Moteur natif multi (`core/src/engine.cpp`, `simulate_uplinks_multi_downlinks`) : règle `join` (`MultiDownlinkRule`), join-request décodée -> join-accept à fin + 5 s par la meilleure passerelle, 17 octets. API C : `lsim_downlink_rule.join`, `lsim_downlink_record.join`, `lsim_multi_tx_record.join_request` (champs ajoutés en fin de structure).
- Placement des descendantes : première place libre à partir de l'ouverture RX1 (au lieu d'un `busy_until`), nécessaire car un join-accept s'ouvre plus tard qu'un downlink de données créé après lui. Sans join, le placement natif est identique à la version précédente (comparaison bit à bit des descentes). Les empreintes de trace changent pour les runs à charge confirmée, à cause du libellé `data_ack` ci-dessous, et non à cause du placement.
- `lsim.trace_events.build_multi_trace` : événements `join_request` et `join_accept` ; libellé `data_ack` des charges sur uplink confirmé (comme le mono) ; `decoded_mask` transmis au wrapper des descendantes.
- L'API accepte `protocol.join` en multi ; seul le mesh reste refusé.
- Tests : `python/tests/test_multi_join.py` (mono = multi sans contention, invariants du join, aucun chevauchement de descendantes).
- Mono aligné sur le multi : une join-request est répétée tant que le join-accept n'est pas reçu (avant, seule la première émission était une join-request). Le point fixe des jointures est itéré avec les émissions passerelle (`_plan` dans `trace_events`). Changement de comportement mono : les traces avec `join` changent quand une join-request est perdue.

### Serveur d'API v1, sensibilité du shadowing mesh
- Serveur de l'API v1 (`python/lsim/api_server.py`, bibliothèque standard) : santé, régions, validation, runs (file bornée, un calcul à la fois), état, résumé, dispositifs et événements paginés, annulation et suppression. Jetons d'accès : seul le SHA-256 est stocké, comparaison en temps constant, révocation et expiration ; `python -m lsim.api_server issue-token` affiche le jeton une fois. Runs persistés (SQLite, WAL) ; limite de débit par jeton (429 `rate_limited`) ; TLS optionnel, refus de démarrer en clair hors boucle locale. Passerelles multiples, environnement à obstacles et relief (catalogue serveur `--terrain-catalog`, identifiant `terrain_id`, jamais de chemin client) pris en charge ; énergie avec protocole ou multi-passerelles calculée depuis la trace (airtime des descendantes reçues) ; mesh : descentes acheminées depuis la version suivante (voir « Descentes et charge par relais sur mesh ») ; join en multi-passerelles calculé (join-request répétée tant que le join-accept n'est pas reçu ; même règle que le mono). Schémas : `run_summary` accepte `gateways` (multi) à la place de `gateway` (rupture d'additivité, documentée), `terrain_list` ajouté, `rate_limited` ajouté à `problem`. Génération des schémas testée (reproductible). Tests : `python/tests/test_api_server.py`, `test_api_contract.py`, `test_energy_protocol.py`.
- Trace multi-passerelles (`lsim.trace_events.build_multi_trace`) : mêmes totaux et même calcul natif (`simulate_multi_downlinks`) que les événements. Correction d'un défaut de cohérence : avec downlinks actifs, les totaux de `run_scenario` ne concordaient pas avec la trace (730 reçus contre 560 sur 3000 émissions) ; le serveur utilise désormais la trace et vérifie la somme par dispositif.
- Shadowing mesh, explication et test de sensibilité : sur `examples/mesh_relais_quartier.yaml`, la frontière entend toutes les trames en direct (`direct == frames`, `via_mesh == 0`), donc le mesh ne transporte que des copies redondantes et le shadowing ne change pas la livraison. Test de sensibilité : frontière seule à portée (tx −14 dBm), 150 dispositifs, σ = 8 dB et graine 7 font passer la livraison de 570 à 504 trames sur 570. Tests : `python/tests/test_run_mesh.py`.

### Shadowing mesh, join-accept après rejoin, RAK5148 et RAK7391
- Shadowing sur le mesh : `mesh.shadowing_sigma_db` (0 à 30 dB, 0 par défaut). Un tirage log-normal par paire de passerelles, réciproque (les deux sens reçoivent la même valeur), graine `propagation.shadowing_seed`, tirage natif `lsim_shadowing_sample_db` (même fonction que le cœur de simulation). Tests : réciprocité, déterminisme, σ = 0 identique, bornes (`python/tests/test_mesh.py`, `test_run_mesh.py`). Le shadowing de l'accès reste séparé : le mesh n'hérite pas de `propagation.shadowing_sigma_db`.
- Join-accept après rejoin (LoRaWAN 1.1 §6.2.4.4, tableaux 13 et 14) : `JoinServer.accept_rejoin` produit le join-accept dans la même transaction que la vérification du rejoin. Chiffrement JSEncKey, MIC JSIntKey avec JoinReqType 0x00, 0x01 ou 0x02, RJcount à la place de DevNonce pour la dérivation des clés de session. Le blocage précédent (« DevNonce non défini ») est levé par §6.2.4.4 : RJcount remplace DevNonce. Cœur C++ : `encode_rejoin_join_accept` / `decode_rejoin_join_accept` (API C `lsim_*_rejoin_join_accept`), liaisons `lsim.security`. Pour les rejoins type 0 et 2, le message ne porte pas le JoinEUI : il doit être fourni par le provisionnement (`DeviceKeys.join_eui`), sinon le join-accept est refusé. Ancien contexte conservé (§6.2.4) : le nouveau est mis en attente (table `pending_sessions`) et devient la session au premier uplink valide qui l'utilise, dans la même transaction ; l'ancien disparaît alors. Pendant l'attente, l'uplink sur l'ancien contexte ne reçoit ni la file de downlinks ni de commande MAC (ACK seul si confirmé) ; la file part au premier uplink valide du nouveau contexte. Les commandes MAC en attente sont effacées à l'émission du join-accept pour les rejoins types 0 et 1 (avant `on_join`, car `on_join` peut en enfiler de nouvelles) ; elles sont conservées pour le type 2, qui garde les paramètres radio. Un rejet après la promotion, dans la même transaction, annule la promotion : l'ancien contexte, la file et le contexte en attente restent intacts. Écart par rapport au plan initial : l'effacement se fait à l'émission du join-accept et non à la promotion. Un MIC faux n'y change rien ; un second rejoin remplace le contexte en attente ; une join-request complète supprime tout. L'état survit au redémarrage. Tests : `python/tests/test_uplink.py`. Tests : aller-retour device/serveur pour les types 0, 1, 2 ; JoinReqType et RJcount liés au MIC ; rejeu sans changement d'état ; MIC faux sans sortie ; JoinEUI absent refusé ; RJcount0 remis à zéro (`python/tests/test_join_server.py`, `core/tests/test_join.cpp`).
- Catalogue, RAK5148 : fiche technique fournie (9 pages) et one-pager. Tx max 27 dBm ; sensibilité typique −132 dBm (SF12 / 203 kHz) et −110 dBm (SF7 / 1625 kHz) ; 3,3 V (3,0 à 3,6 V) ; 810 mA en émission, 179 mA en réception ; −40 à +85 °C ; modèles RAK5148-211 (USB, reset MCU) et RAK5148-221 (USB, GPS ZOE-M8Q, reset MCU). Le nombre de canaux d'accès n'est pas publié : `max_channels` reste vide. La table basse consommation Semtech donne −106 dBm à SF7 / 1625 kHz au lieu de −110 dBm : le mesh garde la table, plus conservatrice. L'ancienne source (page RAK en 404) est remplacée par la fiche fournie.
- Catalogue, RAK7391 (WisGate Connect) : hôte Raspberry Pi CM4 avec 3 emplacements mini-PCIe, 1 M.2 B-key, 2 WisBlock IO, 10 à 28 V DC. La brochure ne publie aucun paramètre radio : le profil n'en porte aucun. Un hôte (`is_host`) est refusé comme passerelle radio (« hôte sans radio publiée »), tant qu'un module n'est pas déclaré.
- Documentation : `docs/USAGE.md` (5sexies), `docs/ROADMAP.md`. Schémas `schemas/api/v1/` régénérés depuis la racine.

### Relais mesh et passerelles multiples
- Relais mesh 2,4 GHz (style ChirpStack Gateway Mesh) : moteur C++ `core/src/mesh.cpp`, API C `lsim_mesh_*` (statuts 800..849). Routes vers la frontière, au plus 8 sauts ; liens réciproques ; demi-duplex et collisions avec capture ; sensibilité SX1280 (tableau basse consommation, CR 4/5, DS Rev 3.0 table 6-1) ; airtime AN1200.13 (vérifié contre le cœur natif à 125 kHz). `lsim.mesh` reste l'interface Python.
- Catalogue : RAK5148 (module 2,4 GHz, mesh) ajouté ; RAK7249 reste sans mesh (radio mesh non documentée).
- Scénario : `gateways` (liste nommée, profil du catalogue, `mesh: true` pour les relais) et `mesh` (frontière, SF, BW, CR, capture, sauts, suppression, attente, taille de trame). `lsim run` exécute le multi-passerelles ; avec mesh, une trame est remise au LNS si une copie atteint la frontière. Bilan `MeshSummary` et lignes dans le rapport.
- Suppression des doublons par identifiant de trame (`suppress_duplicates`, vrai par défaut) : un relais ne transmet une trame qu'une fois et renonce s'il entend un autre relais la transmettre avant son départ. Test de chevauchement : une émission au lieu de deux (`core/tests/test_mesh.cpp`, `python/tests/test_mesh.py`).
- Attente de relais déterministe (`relay_backoff_airtimes`, 4 temps d'antenne par défaut) : sans elle, deux relais qui reçoivent la même trame au même instant partent ensemble et la suppression ne se déclenche jamais (0 copie supprimée sur l'exemple). Sur `examples/mesh_relais_quartier.yaml` (SF12/203 kHz, taille réelle), sans attente : 0 copie supprimée, 5520 émissions, 2740 collisions ; avec attente de 4 T : 543 copies supprimées, 4977 émissions, 2159 collisions. La livraison ne change pas (2830 à 2831 trames) : la frontière décode déjà la plupart des trames.
- Taille de trame corrigée : l'hypothèse de 32 o fixes est remplacée par la trame LoRaWAN réelle du dispositif plus l'enveloppe mesh de 14 o en montant (documentation RAK et ChirpStack ; 15 o en descendant). `frame_size: fixed` garde l'ancien comportement. Le temps d'antenne se calcule par trame (`lsim_mesh_frame.payload_bytes`).
- Descente sur le mesh : pour chaque trame remise, fenêtre atteignable (RX1, RX2, hors fenêtres), par le chemin inverse et un temps d'antenne mesh par saut (borne optimiste : pas de collision au retour). Constat sur l'exemple : à SF12/203 kHz, un saut d'acquittement dure 1,01 s, donc aucune descente relayée n'atteint RX1 (1 s) ni RX2 (2 s) : 21 trames sur 21 hors fenêtres. À SF9/203 kHz (139 ms par saut), aucune. Le choix de bande et de SF mesh conditionne donc les acquittements.
- Obstacles et relief sur le mesh : perte de propagation entre passerelles calculée par le natif (`lsim_env_path_loss_matrix`), antennes à hauteur passerelle. Un mur de 60 dB entre frontière et relais supprime la route (test d'intégration).
- GeoJSON multi-passerelles : une passerelle par entrée, une couverture par passerelle et par groupe (`gateway` dans les propriétés). Le refus est supprimé.
- Charge par passerelle en multi : trames audibles (RSSI ≥ sensibilité), union des intervalles, simultanéité maximale (`lsim_gateway_rx_stats` : quatre champs ajoutés en fin de structure). Une passerelle a `busy_ns`, `peak_concurrent`, `utilization`. Sur l'exemple, toutes les passerelles entendent les 3000 trames (portée de 3,5 km) : la charge est donc identique entre elles.
- Défaut mesh : SF9 / 203 kHz (décision). À SF12 / 203 kHz, un saut d'acquittement dure 1,01 s : aucune descente relayée ne tient dans RX1 ni RX2. Le bloc `mesh` (SF, bande, CR) reste réglable par scénario ; le choix automatique par profil d'équipement n'est pas implémenté. Le bloc `mesh` n'existait pas sur `main` : ce changement de défaut n'affecte aucun contrat publié.
- Limites restantes : le shadowing n'est pas appliqué au mesh ; le retour de descente n'a pas de collision ni de file d'attente.
- Constat sur la saturation : la frontière décode 2810 trames sur 2840 directement ; le mesh n'en apporte que 21. Les 4977 émissions mesh et les 1840 collisions de relais servent donc surtout à des copies redondantes.
- Moteur multi-passerelles : `decoded_mask` par émission (bit g : passerelle g a décodé), ajouté en fin de `lsim_multi_tx_record`.

### Correctif : optimisation bas débit
- `RadioConfig.low_data_rate_optimize` vaut `None` par défaut : la règle LoRaWAN s'applique (Tsym > 16 ms, donc SF11 et SF12 à 125 kHz). Avant, la valeur `False` sous-estimait la durée d'émission de ces configurations dans l'API directe `time_on_air_ns`. Le moteur de simulation calculait déjà l'optimisation à partir du SF et de la bande : aucun résultat publié de simulation n'est modifié.

### Contrat d'API et traces
- Trace par transmission exportée par le cœur natif (`lsim_simulate_uplinks_trace`) : début, fin, SF, RSSI, issue. Mêmes compteurs que l'appel sans trace ; borne 200 000 émissions (statut 309).
- Événements du protocole dérivés de la trace (`lsim.trace_events`) : join-request / join-accept (fin + 5 s), ACK et downlink (fin + 1 s, un par uplink accepté), `rx_window_missed` en demi-duplex. Même `t_ns` que le moteur ; options `join`, `confirmed_uplinks`, `downlink_every`.
- Réception du downlink par le dispositif (réciprocité, puissance passerelle 14 dBm par défaut, sensibilité RX1 du plan) : une perte donne l'issue `lost_sensitivity`.
- Moteur multi-passerelles (phase 2, premier incrément) : `simulate_uplinks_multi` (C++, `lsim_simulate_uplinks_multi`, `simulate_uplinks_multi` en Python). Chaque passerelle reçoit indépendamment (sensibilité et collision à son RSSI) ; le serveur déduplique (une livraison par trame, copies comptées). Downlinks multi-passerelles (`simulate_uplinks_multi_downlinks`, `lsim_simulate_uplinks_multi_dl`, `simulate_multi_downlinks`) : chaque uplink décodé reçoit son ACK ou sa charge de la meilleure passerelle décodeuse ; chaque passerelle sérialise ses downlinks et ne décode pas pendant les siens. Calcul exact dans l'ordre de fin des émissions (sans itération : une itération en point fixe oscillait sur certains scénarios). Pas encore d'usage dans `run` ni dans le contrat d'API, ni de relais mesh.
- Passerelle demi-duplex : un downlink à la fois (sérialisation, perte si hors fenêtre RX1) ; uplinks reçus pendant une émission passerelle perdus (`lost_gateway_busy`, nouveau compteur C et Python). Calcul en point fixe avec le moteur.
- MNT libre : `scripts/fetch_copernicus_dem.py` (Copernicus DEM GLO-30, licence Copernicus) produit un CSV UTM à 30 m pour `terrain` ; cache `data/cache/` exclu du dépôt.
- Contrat v1 : `docs/API_CONTRACT.md`, schémas `schemas/api/v1/`. Authentification par jeton décrite (SHA-256 au repos, 401 `unauthorized`).

### Radio et régions
- Sensibilités SX1276 Rev. 4 pour 125, 250 et 500 kHz (SF7 à SF12), alignées sur le datasheet.
- Atténuation par matériau (UIT-R P.2040-4) : pertes de traversée, avec avertissement hors plage.
- Régions : EU868 (ETSI EN 300 220-2, RP002), AS923 (Japon, partiel), RU864, KR920 (partiel).
- US915 et AU915 : sous-bandes 1 à 8 (`sub_band` dans les groupes ; `lsim serve --sub-band`), règle LinkADRReq ChMaskCntl 0 à 7 (`lsim.channel_mask`). Le serveur envoie un LinkADRReq de sous-bande à chaque jointure, renvoyé jusqu'à acquittement (8 essais) ; la passerelle Basic Station annonce la sous-bande (canal 500 kHz sur radio_1).

- LR-FHSS non géré (décision) : uplinks US915 DR5/DR6 et modulation `LRFHSS` refusés, aucun débit LR-FHSS dans AU915 (`docs/USAGE.md` 5quater, `python/tests/test_lrfhss_unsupported.py`).

### LoRaWAN 1.1
- Codec de trame, crypto (mbedTLS), dérivation de clés 1.1, trame sécurisée (MIC avant déchiffrement).
- Jointure, rejoin types 0/1/2, garde anti-rejeu, rekey, commandes MAC (codec et API).
- Classe B (ping slots, limites documentées) et classe C (blocage RX2).

### Simulation et sorties
- Moteur d'événements déterministe, collisions et capture, temps d'antenne, charge passerelle.
- Scénarios YAML validés strictement, relief et obstacles, carte GeoJSON et MNT.
- Rapports PDF et Excel, export Parquet, notebook d'analyse.

### Énergie
- Deux profils au choix : `rak4631` et `sx1262-stm32l072` (`--energy-profile`).
- Classe A : fenêtres RX1/RX2 au préambule (durée configurable).
- Profil choisi dans le scénario YAML (`energy.profile`) ; l'option CLI le remplace. Absent du hash si non renseigné.

### Serveur de jointure
- Registre de jointure durable, partageable entre processus (SQLite WAL, transactions `BEGIN IMMEDIATE`, état protégé par MIC).
- Serveur de jointure : join-request acceptée et join-accept produit en une transaction ; rejoin vérifié sans join-accept généré (la spec 1.1 ne définit pas DevNonce ni JoinEUI pour ce join-accept).
- Périmètre : fichier SQLite local, un seul hôte (pas de NFS ni SMB).

### Passerelles
- Codec Semtech UDP (GWMP v2) et serveur UDP : join-accept livré à la passerelle en PULL_RESP (fenêtre JOIN_ACCEPT_DELAY1 = 5 s), routes et traitements bornés.
- Commande `lsim serve` (`--transport udp` par défaut) ; Basic Station : `--transport basicstation`, WebSocket (RFC 6455, sans dépendance), TLS 1.2+ optionnel.
- Trames de données : compteur 32 bits, rejeu refusé, MIC avec TxDr/TxCh, ACK downlink en RX1 à +1 s, retransmission confirmée ré-acquittée, file de downlinks (`lsim downlink`), session créée avec la jointure.
- Plan RU864 (`--region RU864`, `python/lsim/ru864.py`) : canaux 868,9 / 869,1 MHz, DR0-DR6, RX1 même canal et même débit, RX2 869,1 MHz DR0, charges N EU868.
- Plan IN865 (`--region IN865`, `python/lsim/in865.py`) : canaux 865,0625 / 865,4025 / 865,985 MHz, DR0-DR5, RX1 même canal et même débit, RX2 866,550 MHz DR2. Charges N prudentes.
- Plan KR920 (`--region KR920`, `python/lsim/kr920.py`) : canaux 922,1 / 922,3 / 922,5 MHz, DR0-DR5, RX1 même canal et même débit, RX2 921,9 MHz DR0. Charges N prudentes (tableau 62 de RP002-1.0.2 non lu).
- Plan AS923 (`--region AS923`, `python/lsim/as923.py`) : canaux 923,2 et 923,4 MHz, DR0-DR6, RX1 même canal et même débit, RX2 923,2 MHz DR2, charges N 51/115/222. DR7 (FSK) et DownLinkDwellTime non gérés.
- Plans régionaux EU868, US915 et AU915 (`--region`) : canaux, débits, RX1 (modulo 8 pour US915 et AU915), charges maximales, DLSettings.
- Chiffrement au repos des sessions, compteurs et charges en file (AES-256-GCM, clé `LSIM_DATA_KEY`, extra `serve` = `cryptography`).
- Base SQLite créée en mode 0600 ; refus si elle est accessible à d'autres utilisateurs.
- DevEUI dans `keys.json` et `lsim downlink --dev-eui` : ordre d'affichage TTN (conversion interne).
- Basic Station : `hwspec` `sx1301/N` (seul préfixe accepté par Station), `JoinEui` à `null`
  (pas de filtre), conformité vérifiée sur les vecteurs officiels `selftest_lora.c`.

### Données
- Paramètres de propagation indoor (Université de Siegen, CC BY 4.0) déposés dans
  `python/lsim/reference/`, sans les données brutes.

### Limites connues
- Pas de calibrage terrain ; pas de validation de pénétration sur mesures.
- Rx énergie 250/500 kHz non publié : estimation signalée.
- Pas de multi-utilisateurs, ni de fournisseur de tuiles sous contrat.
