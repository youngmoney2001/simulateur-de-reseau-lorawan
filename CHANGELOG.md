# Journal des changements

## 0.1.0 (non publiée)


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
