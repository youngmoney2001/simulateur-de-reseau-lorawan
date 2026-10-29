# Matrice de conformité LoRaWAN

Cible : **LoRaWAN L2 1.0.4 (TS001-1.0.4)**, avec les paramètres régionaux **RP002-1.0.5** et les errata applicables.
Ce document est la base de travail avant toute modification du moteur. Il ne déclare conforme que ce qui a été vérifié.

## 1. Sources et état de vérification

| Source | Statut dans cette itération |
|---|---|
| TS001-1.0.4, PDF officiel (`lora-alliance.org/wp-content/uploads/2021/11/LoRaWAN-Link-Layer-Specification-v1.0.4.pdf`) | **Lu** : §1, §2 (classes), §3 (fenêtres de réception), §4 (format de trame, FCnt, FOpts, ADR, ACK, retransmissions, chiffrement, MIC), §5 (commandes MAC, tableau 14 et 15, LinkCheck, LinkADR jusqu'à Redundancy). **Non lu** : §5.2 (fin), §5.3 à §5.9, §6 (activation), §7 (backoff), §8 à §15 (classes B et C), §16 à §18. L'outil de lecture plafonne à 30 pages ; le PDF en fait 90. Les clauses non lues sont marquées **NV** (non vérifié). |
| Errata TS001-1.0.4 | `ERRATA_L2_1_0_4_D2D` : suppression de l'interdiction d'émettre des downlinks depuis un dispositif (D2D). **Sans effet** : le simulateur n'a pas de D2D. Errata US915/AU915 ChMaskCtrl (contradiction RP002-1.0.4) : **sans effet** tant que les plans à canaux fixes ne sont pas modélisés. |
| RP002-1.0.5 (paramètres régionaux) | **Non vérifié.** Le document existe (publié le 8 octobre 2025), mais son texte n'est pas accessible avec les outils de cette session. Les tables du simulateur proviennent de RP002-1.0.3 (recherches antérieures). **La compatibilité 1.0.5 n'est donc pas établie.** |
| Code du dépôt | Inspection directe des modules : `core/src/engine.cpp` (boucle fermée S2 et chemin historique), `lorawan_frame.cpp`, `session.cpp`, `secure_frame.cpp`, `crypto.cpp`, `join.cpp`, `mac_commands.cpp`, `adr.cpp`, `class_b.cpp`, `mesh.cpp`. |

**Constat de cadrage.** Le moteur de simulation (boucle fermée, chemin historique) et les modules de protocole (`core/src/*.cpp`) ne sont pas la même chose. Un codec correct ne prouve pas le comportement de bout en bout. Les statuts ci-dessous indiquent donc, pour chaque règle, ce qui est vérifié **dans le moteur** (E2E) et ce qui n'est vérifié que **dans un module isolé** (codec ou état).

## 2. Légende

- **Type** : `Obl.` = exigence obligatoire du protocole (SHALL / SHALL NOT) ; `Fac.` = fonctionnalité facultative (MAY, ou classe non obligatoire) ; `Appr.` = approximation physique ou modèle du simulateur, hors norme.
- **Statut** : `C` conforme (vérifié dans le moteur E2E) ; `Mod` conforme au niveau du module seul, pas du moteur ; `P` partiel ; `E` écart ; `NV` non vérifié ; `HP` hors périmètre de cette itération.

## 3. Matrice

### 3.1 Classe A, fenêtres RX1/RX2, planification des descentes

| ID | Réf. | Type | Comportement attendu | Implémentation actuelle | Statut | Écart | Test |
|---|---|---|---|---|---|---|---|
| A1 | TS001 §3.3 | Obl. | Après chaque uplink, ouvrir RX1 ; ouvrir RX2 si aucune trame destinée au dispositif n'est reçue en RX1. | Boucle fermée : RX1, puis repli RX2 (fin + 2 s) si la passerelle ne peut pas émettre en RX1 (`engine.cpp`, `on_received`). Le repli ne traite que l'occupation de la passerelle : une descente émise en RX1 mais non reçue (sensibilité) n'est pas réémise en RX2, car le serveur de réseau ne retransmet pas dans le modèle. | P | Réémission côté serveur de réseau non modélisée. Historique : repli RX2 déjà présent (inchangé). | `test_closed_loop.cpp` `test_rx2_fallback_when_gateway_busy` ; `python/tests/test_mac_loop.py` |
| A2 | TS001 §3.3.1 | Obl. | Pas d'ouverture de RX2 si une trame valide est reçue en RX1. | Historique : repli seulement après `GatewayBusy` en RX1. S2 : sans objet (pas de RX2). | P | Dépend de A1. | à écrire avec A1 |
| A3 | TS001 §3.3.2 | Obl. | RX1 ouverte à RECEIVE_DELAY1 = 1 s après la fin de l'uplink, durée ≥ détection du préambule. | S2 : `kLoopRxDelayNs = 1 s`, `kLoopRx1WindowNs = 1 s`. | C (valeurs par défaut) | RXTimingSetupReq (§5.7, NV) non modélisé : délai réglable 1 à 15 s. | `test_closed_loop.cpp` (délai RX1 implicite) |
| A4 | TS001 §3.3.3 | Obl. | RX2 à RECEIVE_DELAY2 = RECEIVE_DELAY1 + 1 s. | Boucle fermée : `kLoopRx2DelayNs = 2 s` (fin + 2 s), durée 1 s. Historique : +1 s après RX1 (inchangé). | C (boucle fermée) | Historique : valeur conforme, mais non vérifiée de bout en bout par un test dédié. | `test_closed_loop.cpp` `test_rx2_fallback_when_gateway_busy` |
| A5 | TS001 §3.3.3, RP002-1.0.3 | Obl. (valeur régionale) | Fréquence et débit RX2 par défaut de la région (EU868 : 869,525 MHz, DR0 = SF12/125 kHz). | Boucle fermée : SF RX2 = 12 (`kLoopRx2Sf`, valeur RP002-1.0.3) ; fréquence RX2 non modélisée. | P | RP002-1.0.5 non vérifiée (décision RP002). Fréquence RX2 et duty cycle de la passerelle sur RX2 non modélisés. | `test_rx2_fallback_when_gateway_busy` |
| A6 | TS001 §3.3.5 | Obl. | La passerelle commence la descente **précisément** au début de la fenêtre. | Boucle fermée : départ exactement à t_open ; si la passerelle est encore occupée à cet instant, la fenêtre n'est pas utilisable (repli RX2, puis perte). Aucun décalage intra-fenêtre. | C (boucle fermée) | Migré dans la boucle fermée (validé : C++ Release et ASan, Python, empreintes inchangées). Le chemin historique (`off_factor`, causal) garde le décalage `max(t_open, busy_until)` : conflit documenté, migration à proposer séparément. | `test_closed_loop.cpp` `test_no_shift_inside_busy_windows`, `test_rx2_fallback_when_gateway_busy` |
| A7 | TS001 §3.3.6 | Obl. (contrainte dispositif) | Un dispositif **n'émet pas** un nouvel uplink avant d'avoir reçu une descente en RX1/RX2 de l'uplink précédent, ou avant la fin de RX2. | Boucle fermée (décision C1, option b) : l'uplink suivant part au plus tôt à fin + 3 s (fin de RX2). Attendre la fin de RX2 satisfait la règle dans tous les cas. | C (boucle fermée) | Historique : non modifié (`device_missed` historique conservé pour les scénarios sans MAC). | `test_closed_loop.cpp` `test_next_uplink_waits_for_rx2_end` ; `python/tests/test_mac_loop.py` `test_next_uplink_waits_for_rx2_end_end_to_end` |
| A8 | TS001 §4.1 | Obl. | MACPayload ≤ M (taille maximale par débit, RP002). Trame plus longue : rejetée silencieusement. | Présent dans `plan.py` / `uplink.py` ; couverture de test non vérifiée dans cette session. | NV | — | à vérifier |
| A9 | TS001 §3.3.4, §5.7 | Obl. ? | RXTimingSetupReq / Ans : délai RX1 réglable. | Non modélisé (S2). | NV / E | Statut obligatoire à confirmer dans §5.7 (NV). | — |

### 3.2 Format de trame, FCnt, FOpts, ACK, retransmissions, chiffrement

| ID | Réf. | Type | Comportement attendu | Implémentation actuelle | Statut | Écart | Test |
|---|---|---|---|---|---|---|---|
| F1 | TS001 §4.2 | Obl. | MHDR : FType (3 bits), RFU, Major = 00. | `lorawan_frame.cpp` (codec). | Mod | — | `test_lorawan_frame.cpp` |
| F2 | TS001 §4.3.1 | Obl. | FOptsLen ≤ 15 ; FOpts ≤ 15 octets. | `lorawan_frame.cpp` (`kMaxFOpts`) ; S2 : budget 15 octets. | C (S2) | — | `test_closed_loop.cpp` (budget FOpts) |
| F3 | TS001 §4.3.2 | Obl. | FPort 0 interdit avec FOpts ; FPort absent si pas de FRMPayload. | `lorawan_frame.cpp` l.32–39. | Mod | — | `test_lorawan_frame.cpp` |
| F4 | TS001 §4.3.2 | Obl. | FPort 1..223 applicatif ; **224 = test MAC** (TS008/TS009, chiffré avec AppSKey) ; 225..255 réservés. | Codec : `kMaxFPort = 224`, 225 et au-delà refusés. FPort 224 chiffré avec AppSKey (`payload_key`, comme les ports applicatifs). | C | Codec conforme (224 accepté, 225 refusé). Le test MAC de l'application n'est pas exécuté par le moteur (hors périmètre). | `test_lorawan_frame.cpp` (224 accepté, 225 refusé) |
| F5 | TS001 §4.3.1.5 | Obl. | FCnt = 16 bits de poids faible ; le serveur reconstruit les 16 bits de poids fort. | `uplink.py` reconstruit (côté réseau) ; `secure_frame.cpp` exige `fcnt16 == fcnt32 & 0xFFFF` (l'appelant fournit le compteur complet). | P | Pas d'inférence du MSB dans le module de trame sécurisée. | `test_secure_frame.cpp` (à compléter) |
| F6 | TS001 §4.3.1.5 | Obl. | Le dispositif ignore une retransmission de descente (même FCnt). | `session.cpp` : `Replay` si `fcnt < expected`. | Mod | — | `test_session.cpp` |
| F7 | TS001 §4.3.1.5 | Obl. | ABP : compteurs jamais remis à zéro pendant la vie du dispositif. OTAA : remise à zéro après Join-Accept. | `session.cpp` : `fcnt_up_ = 0` à l'initialisation. Remise OTAA : NV (§6). | P | — | à vérifier |
| F8 | TS001 §5 (intro) | Obl. | **Commandes MAC en FOpts : jamais chiffrées.** Commandes en FRMPayload (FPort 0) : chiffrées avec NwkSKey. | Profil 1.0.x (défaut, décision C2) : FOpts en clair (`seal_uplink_10`, `open_uplink_10`). Profil 1.1 conservé séparément (chiffrement NwkSEncKey). | Mod | Moteur et API C/Python encore sur le profil 1.1 : sélection de profil à faire (voir S1). | `test_secure_frame.cpp` `test_v104_uplink_vector_fopts_in_clear` |
| F9 | TS001 §4.4 | Obl. | MIC = CMAC(NwkSKey, B0 \| msg)[0..3] (1.0.x). | Profil 1.0.x : `seal_uplink_10` / `open_uplink_10` / downlink, avec `compute_data_mic` (NwkSKey). Profil 1.1 : MIC à deux clés. | Mod | Moteur et API non migrés. | `test_v104_uplink_vector_fopts_in_clear`, `test_v104_downlink_vector_and_tamper` |
| F10 | TS001 §4.3.3 | Obl. | Chiffrement FRMPayload : AppSKey (FPort ≥ 1), NwkSKey (FPort 0). | Profil 1.0.x : `payload_key_10` (NwkSKey pour FPort 0). Profil 1.1 : NwkSEncKey pour FPort 0. | Mod | Moteur non migré. | `test_v104_port0_uses_nwk_skey` |
| F11 | TS001 §4.3.1.2 | Obl. | Confirmé reçu en RX → ACK avec le prochain uplink ; le réseau n'envoie l'ACK que dans les RX de l'uplink confirmé. | S2 : descente ACK en RX1 (`kind = 1`) ; bit ACK du prochain uplink non modélisé (sans effet sur l'airtime). | P | Bit ACK non porté. | à écrire |
| F12 | TS001 §4.3.1.3 | Obl. (dispositif) | Uplink confirmé : retransmis jusqu'à ACK, avec RETRANSMIT_TIMEOUT après RX2 ; uplink non confirmé : répété NbTrans fois tant qu'aucune descente Class A n'est reçue. | **Non modélisé** (S2 et historique : « sans retransmission », `trace_events.py`). | **E** | Confirmés et NbTrans absents du trafic simulé. Changerait airtime et collisions. | à écrire après décision C4 |
| F13 | TS001 §4.3.1.4 | Fac. (Class A : MAY) | FPending : le dispositif peut émettre tôt. | Non modélisé. | HP | — | — |
| F14 | TS001 §4.3.1.1, RP002-1.0.5 §3.3 | Obl. (ADRACKReq, backoff) | ADRACKCnt ; ADRACKReq à ADR_ACK_LIMIT = 64 ; sans descente pendant LIMIT + DELAY = 96 uplinks, puissance par défaut puis débit plus bas tous les ADR_ACK_DELAY = 32 uplinks ; une descente reçue remet ADRACKCnt à 0. | Boucle fermée (`engine.cpp`) : compteur côté dispositif ; ADRACKReq porté par l'uplink et suivi d'une descente de classe A (serveur). Le cran de débit est −1 (identique à Table 12 pour DR1–DR6 en EU868 ; DR8–DR11 sont LR-FHSS, non modélisés). Retour aux canaux par défaut et NbTrans = 1 : sans objet (pas de masque de canaux ni de NbTrans modélisés). Table 9 est un exemple, non suivi tel quel. | C (boucle fermée) | Historique : pas de backoff dans S2 ; scénarios sans ADR inchangés. | `test_closed_loop.cpp` `test_adr_ack_backoff_without_downlink` (SF8 à 96, SF9 à 128, SF10 à 160), `test_adr_ack_counter_reset_by_downlink` |

### 3.3 Commandes MAC

| ID | Réf. | Type | Comportement attendu | Implémentation actuelle | Statut | Écart | Test |
|---|---|---|---|---|---|---|---|
| M1 | TS001 §5 | Obl. | Réponses dans l'**ordre** de réception ; toutes les commandes d'une trame sont répondues dans **une** trame ; troncature autorisée à la fin de la dernière commande qui tient ; toutes exécutées. | S2 : réponses dans la descente de leur uplink. Ordre : commandes à état (LinkADR, DutyCycle) avant la file, donc pas strictement l'ordre de réception. | P | Ordre des réponses. | à écrire |
| M2 | TS001 §5 | Obl. | **Une réponse à une requête du dispositif n'est envoyée que dans les fenêtres RX qui suivent la requête** ; elle expire après ces fenêtres. | **Corrigé dans cette itération** : S2 reportait LinkCheckAns et DeviceTimeAns jusqu'à 3 uplinks (non conforme). Désormais, une réponse qui ne tient pas expire au premier report. | **C** (S2, après correction) | — | `test_closed_loop.cpp` : `check_mac_lifecycle` (réponse servie dans **sa** descente, jamais reportée) ; `test_mac_queue_fairness_bounded_wait` ; `test_answers_are_never_deferred_end_to_end` (Python) |
| M3 | TS001 §5, Tab. 15 | Obl. | Priorité : réponses MAC et nouvelles commandes avant la charge applicative. | S2 : budget FOpts uniquement (pas de concurrence avec une charge applicative). | P | Concurrence payload / MAC non modélisée. | à écrire |
| M4 | TS001 §5 (note) | Obl. | Commande MAC inconnue : arrêt du traitement de la séquence. | `mac_commands.cpp` renvoie `UnknownCommand` ; arrêt de la séquence : NV. | NV | — | à vérifier |
| M5 | TS001 §5.1 | Obl. | LinkCheckReq → LinkCheckAns (Margin, GwCnt). | S2 : réponse émise ; marge indicative (`MAC_PLAN.md`). | P | Marge : **approximation** du simulateur, pas la marge SNR normative. GwCnt = 1 (une passerelle). | `test_mac_loop.py` |
| M6 | TS001 §5.2 | Obl. | LinkADRReq avec ADR = 1 : tout ou rien. Avec ADR = 0 : acceptation **par élément** (débit, puissance, canaux). | S2 : accepté ou refusé en bloc (bits d'acquittement). Pas de réponse partielle, pas de ChMask (canaux EU868 fixes non modélisés). | P | Réponse par élément absente. | à écrire |
| M7 | TS001 §5.2 (Table 18) | Obl. | TXPower plus haute que le maximum : ACK et puissance maximale. Plus basse que possible : NACK. | S2 : index hors table refusé ; cas « trop haut » : à vérifier. | P | — | à écrire |
| M8 | TS001 §5.2 | Obl. | Valeur 0xF pour DataRate ou TXPower : ignorer le champ. | Codec : NV. S2 : NV. | NV | — | — |
| M9 | TS001 §5.2 (Table 20) | Obl. | NbTrans (1..15) appliqué à la répétition des uplinks ; ChMaskCntl. | NbTrans **non appliqué** (lié à F12). | E | — | — |
| M10 | TS001 §5.3 à §5.9 | Obl./Fac. selon commande | DutyCycle, DevStatus, RXParamSetup, NewChannel, DlChannel, RXTimingSetup, TXParamSetup, DeviceTime. | S2 : DutyCycle (oui, voir ADR/duty), DevStatus (oui), DeviceTime (oui, valeur approximative). RXParamSetup, NewChannel, DlChannel, RXTimingSetup, TXParamSetup : non modélisés. `mac_commands.cpp` : codec. | NV pour les clauses ; E si obligatoires | Statut obligatoire à confirmer (texte NV). | — |
| M11 | TS001 §5.1, §5.2 | Obl. | LinkCheckReq et DeviceTimeReq reçus : le réseau **doit** répondre. | S2 : réponses émises (voir M2). | C (S2) | — | — |

### 3.4 ADR, puissance, débits, duty cycle, régional

| ID | Réf. | Type | Comportement attendu | Implémentation actuelle | Statut | Écart | Test |
|---|---|---|---|---|---|---|---|
| R1 | TS001 §4.3.1.1 | Obl. (dispositif) | Puissance et débit par défaut : maximum et minimum autorisés. Un dispositif OTAA suit le débit de jointure. | Boucle fermée : `plan`/`region` ; défauts à vérifier. | NV | — | à vérifier |
| R2 | RP002-1.0.5 | Obl. (valeur régionale) | Tables de débits, puissance (index 0 = maximum EIRP, pas de 2 dB selon plan), limites réglementaires de duty cycle. | Tables EU868 de RP002-1.0.3 (puissance : 16 dBm, pas 2 dB, index 0..7). RP002-1.0.5 **NV**. | NV | Compatibilité 1.0.5 non établie. | — |
| R3 | Réglementaire | Obl. (hors LoRaWAN) | Duty cycle réglementaire par bande et sous-bande ; `DutyCycleReq` le réduit sans jamais l'élargir. | Implémenté (`T_rest = T_air × (1/D − 1)`, limite séparée de `DutyCycleReq`). | C (S2) | — | `test_closed_loop.cpp` (divergence de convention) |
| R4 | Appr. | — | Airtime, sensibilité, collisions, occupation passerelle. | Modèle SX1276 et `lora_phy.cpp`. | Appr. | — | — |

### 3.5 Compteurs, sécurité, jointure

| ID | Réf. | Type | Comportement attendu | Implémentation actuelle | Statut | Écart | Test |
|---|---|---|---|---|---|---|---|
| J1 | TS001 §6 | Obl. | Join-Request/Join-Accept, MIC, DevNonce non réutilisé, délais JOIN_ACCEPT (5 s et 6 s en 1.0.x : **NV**). | `join.cpp` : chemin 1.0.x (`compute_join_accept_mic_legacy`) **et** 1.1 (`JSIntKey`). Jointure refusée par la boucle fermée. | Mod (1.0.x et 1.1) / HP en E2E | Pas de test E2E ; délais NV. | `test_join.cpp` (existant) |
| J2 | TS001 §6.2.4, §6.1 | Obl. | Dérivation de NwkSKey et AppSKey depuis AppKey (1.0.x : AppNonce, NetID, DevNonce). | `crypto.cpp` / `join.cpp` : dérivation 1.1 et 1.0.x présentes ; **NV** pour la conformité 1.0.x. | P | À vérifier avec §6 (NV). | — |
| S1 | TS001 §4.3.3, §4.4 | Obl. | Profil 1.0.4 : MIC et chiffrement avec NwkSKey / AppSKey ; FOpts en clair. | Module de trame : profil 1.0.x (`seal_*_10`, `open_*_10`), dérivation `derive_session_keys_10`, API C `lsim_*_10` et `lsim_derive_session_keys_10`. Profil 1.1 séparé, API 1.1 inchangée. | Mod | Moteur et API Python non migrés : le moteur n'utilise pas encore le profil 1.0.x. Vecteurs calculés hors C++ (cryptography), non issus d'une suite officielle. | `test_secure_frame.cpp` `test_v104_*`, `test_c_api.cpp` `test_v104_c_api_vectors` |
| S2 | TS001 §4.3.1.5 | Obl. | OTAA : FCntUp et FCntDown remis à zéro après Join-Accept. | `session.cpp` (initialisation) ; reprise après jointure : NV. | P | — | — |

### 3.6 Classes B et C, mesh

| ID | Réf. | Type | Comportement attendu | Implémentation actuelle | Statut | Écart | Test |
|---|---|---|---|---|---|---|---|
| B1 | TS001 §8 à §14 | Fac. | Classe B : beacons, ping slots, MAC de classe B (0x10–0x1F). | `class_b.cpp`, `c_api_class_b.cpp` (modules). Non intégré à la boucle fermée. Texte §8–14 **NV**. | HP / NV | — | — |
| C1 | TS001 §15 | Fac. | Classe C : écoute continue, RX2 après chaque émission. | **Absente.** | HP | — | — |
| X1 | — | Hors standard | Mesh : **pas une fonctionnalité LoRaWAN standard**. `mesh.cpp` existe ; aucune spécification de périmètre. | Non démarré. | HP | Architecture et périmètre à définir séparément. | — |

## 4. Approximations du simulateur (hors norme, à documenter)

- Propagation, sensibilité (décalage `device_rx_offset_db`), collisions, occupation de la passerelle (une passerelle unique).
- Marge de LinkCheckAns indicative, DevStatusAns (batterie et marge) approximatifs, DeviceTimeAns sans horloge GPS réelle.
- Ordre et durée des uplinks : période, jitter de démarrage, pas de concurrence avec charge applicative.
- Airtime : modèle SX1276 (`lora_phy.cpp`) ; l'airtime de la boucle fermée réserve les octets MAC (option A).

## 5. Conflits entre résultats historiques ou choix utilisateur et la norme

**C1 — Émission pendant les fenêtres RX (A7). Décidé : option (b).** La règle antérieure (« une émission pendant RX1 fait perdre la descente ; la prochaine émission n'est pas retardée ») contredisait TS001 §3.3.6. Décision utilisateur : la prochaine émission est retardée jusqu'à la fin de RX2 (fin + 3 s) dans la boucle fermée. Appliqué. Le chemin historique reste inchangé jusqu'à validation explicite (empreintes `d2cb0fac…` et `ed126d7f…` inchangées : aucun scénario sans bloc `mac:` ne change).

**C2 — Profil de protocole (F8, F9, F10, S1).** Le module de trame sécurisée implémente LoRaWAN 1.1 (MIC et chiffrement de FOpts avec des clés 1.1). La cible est 1.0.4. Options :
- (a) profil de version explicite : 1.0.4 pour les trames et le MIC (`compute_data_mic` existant), 1.1 conservé comme profil séparé ;
- (b) supprimer le profil 1.1 du module de trame (non recommandé sans décision).
Recommandation : (a), avec tests de vecteurs 1.0.4.

**C3 — RX2 en boucle fermée (A1, A4, A5, A6). Décidé : valeurs RP002-1.0.3.** Repli RX2 implémenté en S2 (fin + 2 s, SF12, 1 s). Fréquence RX2 (869,525 MHz) non modélisée ; RP002-1.0.5 reste non vérifiée et sa compatibilité n'est pas établie.

**C4 — Retransmissions confirmées et NbTrans (F12, M9).** Modifie l'airtime et les collisions ; à faire avec validation explicite des traces.

## 6. Ordre de correction et état

| Ordre demandé | Élément | État |
|---|---|---|
| 1. Classe A, RX1/RX2, planification | Repli RX2 en S2 (A1, A4, A5) ; délai après RX2 (A7, C1) | **Fait (partiel)** : C1 et repli RX2 appliqués, tests E2E C++ et Python. Reste : fréquence RX2 (A5), réémission serveur (A1), RP002-1.0.5 (NV). |
| 2. Commandes MAC, réponses, FOpts | Réponses MAC : pas de report (M2) | **Fait** : tests C++ et Python ; empreintes historiques inchangées. Reste : M1, M3, M6, M7, M8, M9. |
| 3. ADR, puissance, débits, duty cycle, régional | RP002-1.0.5 (R2), backoff ADR (F14) | **Partiel** : F14 fait en boucle fermée (`test_adr_ack_*`) ; RP002-1.0.5 lu pour EU868 (§3.3, §3.4). DR13 (SF5) : modèle `sensibilite-par-sf-v2` dans le moteur C++ et l'ABI v2 (trace et boucle fermée), 125 kHz, valeurs SX1303 indicatives ; branché au pont Python, au schéma de scénario (`gateway.sensitivity`) et au catalogue (`sx1303-datasheet`) ; un groupe SF5 exige EU868 et une paire documentée, et refuse le bloc `mac:` ; une descente SF5 vers un dispositif est refusée (sensibilité dispositif NV). Écart résiduel : `energy.py` refuse SF5 (profil énergie non étendu) ; `build_trace` refuse une descente SF5 (explicite). DR12 (SF6) reste à faire. |
| 4. Compteurs, sécurité, jointure | Profil 1.0.4 (F8, F9, F10, S1) ; FPort 224 (F4) | **Non fait** : décision C2 requise. |
| 5. Classes B et C | Hors périmètre ; texte §8–15 NV | **Non fait**. |

## 7. Tests de validation exécutés pour ce tour

- `lsim_tests` (C++, dont `check_mac_lifecycle`, `test_mac_queue_fairness_bounded_wait`, `test_mac_no_retransmission_of_lost_answers`) : 654 568 vérifications, sans échec. Même résultat sous ASan/UBSan.
- `python/tests` : 1674 réussis, 1 ignoré.
- `scripts/mac_baseline_dump.py` : empreintes historiques `d2cb0fac…` (sorties) et `ed126d7f…` (traces) **inchangées**.
- Vérification du pont : la bibliothèque doit être reconstruite entière (`cmake --build build`) avant les tests Python ; une cible partielle laisse l'ancien `.so` en place.
