# Feuille de route

Légende : ✅ fait · 🔧 en cours · ⬜ planifié

## Jalon 0 — Fondations (en cours)
- ✅ Dépôt, licence Apache-2.0, CI (C++ et Python)
- ✅ Cœur C++17 : temps d'antenne LoRa exact (entier nanosecondes, AN1200.13)
- ✅ Validation des entrées, statuts explicites, aucune exception traversant la frontière C
- ✅ API C stable + binding Python `ctypes` (aucun code de calcul en Python)
- ✅ Tests : valeurs de référence + différence avec une implémentation indépendante (1 008 cas)
- ✅ Tests sous ASan + UBSan, fuzzing déterministe du codec de trame

## Jalon 1 — Couche radio et propagation
- ✅ Sensibilité SX1276 125 kHz (SF7–SF12) ; 250/500 kHz refusées tant que non vérifiées
- ✅ Perte espace libre, log-distance, perte maximale admissible (MAPL), portée inverse
- ⬜ Vérifier les sensibilités 250/500 kHz sur le datasheet officiel
- ⬜ Obstacles, masques de terrain, shadowing

- ✅ Collisions même SF avec capture effect (seuil 6 dB), orthogonalité inter-SF (modèle de base, voir Limites)
- ⬜ Profils régionaux data-driven : EU868, US915, AS923, AU915, KR920, IN865, RU864
- ⬜ Duty cycle et temps d'attente réglementaires

## Jalon 2 — MAC LoRaWAN 1.1
- ✅ Codec de trame (MHDR, FHDR, FPort, FRMPayload, MIC) : encodage canonique, bornes vérifiées
- ✅ Primitives AES-128 et AES-CMAC via mbedTLS 3.6.4 (vecteurs FIPS-197 et RFC 4493)
- ✅ Chiffrement FRMPayload et MIC de données, validés sur une trame réelle 1.0.x (MIC 2B11FF0D, « test »)
- ✅ Dérivation des clés de session 1.1 et JSIntKey/JSEncKey : vecteurs TTN (Apache-2.0), recalculés indépendamment
- ✅ MIC 1.1 uplink (split SNwkSIntKey / FNwkSIntKey) et downlink : vecteurs TTN
- ✅ Chiffrement avec identifiant de type de trame (base du chiffrement FOpts) : vecteurs TTN
- ✅ Trame sécurisée 1.1 : scellement et ouverture, MIC vérifié avant déchiffrement, compteur 32 bits contrôlé
- ✅ Crypto et trame sécurisée exposées via l'API C et Python (`lsim.security`)
- ⬜ Confirmer les vecteurs contre le document officiel TS001 de la LoRa Alliance (non accessible ici)
- ⬜ Chiffrement FOpts 1.1 avec NwkSEncKey (câblage dans le codec de trame)
- ⬜ Classes A, B, C
- ⬜ Join OTAA 1.1 (join-request/accept, JoinNonce, DevNonce)
- ⬜ ADR, ACK, commandes MAC, rekey
- ✅ Moteur d'événements discrets : file bornée déterministe, simulation des uplinks (`lsim.simulator`)

## Limites connues (à traiter avant commercialisation)
- Le modèle de collision est un modèle de base : pas de réception multi-passerelle, pas de dérive d'horloge, pas de duty cycle ni de downlink.
- Les FOpts ne sont pas exposés par l'API C ; le chiffrement FOpts 1.1 (NwkSEncKey) n'est pas câblé.
- Vecteurs issus de TTN (Apache-2.0), pas du document TS001.

## Jalon 3 — Scénarios, résultats et analyse
- ⬜ Scénarios YAML validés (Pydantic)
- ⬜ Export Parquet, métriques (PDR, énergie, charge gateway)
- ⬜ Notebooks pour les bureaux d'études

## Jalon 4 — Visualisation 3D et produit
- ⬜ Carte 3D CesiumJS (Apache-2.0) : nœuds, gateways, zones de couverture
- ⬜ Rapports PDF/Excel, gestion multi-utilisateurs
- ⬜ Empaquetage, documentation, cycle de release
