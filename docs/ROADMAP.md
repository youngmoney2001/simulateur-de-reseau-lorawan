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
- ✅ Relief (grille d'altitudes bilinéaire, MNT CSV) et obstacles (pavés) : perte log-distance + diffraction de couteau unique (Lee, seulement si l'obstruction dépasse la ligne de visée) + pénétration ; API C `lsim_simulate_uplinks_env`, scénario YAML `environment:`
- ✅ Diffraction multi-arêtes (Deygout, 3 arêtes) à la place du couteau unique
- ✅ Couverture réelle par azimut (relief et obstacles, dichotomie, borne de travail) ; `model: environment` dans le GeoJSON
- ✅ Outil de calibrage `python -m lsim calibrate mesures.csv` (exposant, PL0, sigma, R2, avertissements)
- ⬜ Calibrage effectif sur mesures terrain (données réelles requises, aucune valeur inventée) ; attenuation des pavés par matériau
- ✅ Shadowing log-normal dans la simulation : terme par dispositif (constant sur la simulation), tirage déterministe par graine (SplitMix64 + Box-Muller), `shadowing_sigma_db` 0–30 dB ; non appliqué à la couverture

- ✅ Collisions même SF avec capture effect (seuil 6 dB), orthogonalité inter-SF (modèle de base, voir Limites)
- 🔧 Profils régionaux data-driven : ✅ cadre (`python/lsim/regions.py`, source obligatoire, règle du plus restrictif pour les sous-bandes qui se recouvrent) ; ✅ EU868 (ETSI EN 300 220-2 V3.2.1, tableau K à QP ; RP002-1.0.0 §2.4) ; ✅ liaison duty cycle du scénario vers le profil ; 🔧 canaux RP002-1.0.0 encodés pour US915, AU915, AS923, KR920, IN865, RU864 (PIRE et sous-bandes locales à compléter, voir `regions.py`) ; 🔧 textes locaux : ✅ FCC (US915), ✅ ACMA (AU915), ✅ GSR 564(E) (IN865, extrait) ; 🔧 Japon (ARIB v1.3 : 360 s/h sur 922,4–923,4 MHz confirmé par extrait officiel ; LBT et règle des 400 ms à modéliser), Russie (annexe 11 : 868,7–869,2 MHz « 10 % ou LBT » en version consolidée 2023, condition « stations de base » ; 0,1 % conservé par prudence), Corée (MSIT) — voir `docs/REGULATORY_SOURCES.md`
- 🔧 Duty cycle : ✅ mécanisme (rapport cyclique par dispositif, attente airtime·(1−d)/d, scénario `duty_cycle` par groupe) ; ✅ liaison scénario → profil (`region: EU868`, `channel_freq_hz`, duty cycle effectif = le plus restrictif ; canal hors plan refusé au chargement)

## Jalon 2 — MAC LoRaWAN 1.1
- ✅ Codec de trame (MHDR, FHDR, FPort, FRMPayload, MIC) : encodage canonique, bornes vérifiées
- ✅ Primitives AES-128 et AES-CMAC via mbedTLS 3.6.4 (vecteurs FIPS-197 et RFC 4493)
- ✅ Chiffrement FRMPayload et MIC de données, validés sur une trame réelle 1.0.x (MIC 2B11FF0D, « test »)
- ✅ Dérivation des clés de session 1.1 et JSIntKey/JSEncKey : vecteurs TTN (Apache-2.0), recalculés indépendamment
- ✅ MIC 1.1 uplink (split SNwkSIntKey / FNwkSIntKey) et downlink : vecteurs TTN
- ✅ Chiffrement avec identifiant de type de trame (base du chiffrement FOpts) : vecteurs TTN
- ✅ Trame sécurisée 1.1 : scellement et ouverture, MIC vérifié avant déchiffrement, compteur 32 bits contrôlé
- ✅ Crypto et trame sécurisée exposées via l'API C et Python (`lsim.security`)
- 🔧 Confirmer les vecteurs contre le document officiel TS001-1.1.0 : ✅ document lu (pas de vecteur numérique dans le PDF, seulement le format des blocs) ; ✅ errata « FOpts Encryption, Usage of FCntDwn » (CR de janvier 2018) lu et appliqué
- 🔧 Chiffrement FOpts 1.1 avec NwkSEncKey : ✅ primitive `crypt_fopts` (bloc A1 de l'errata : constante 0x00000001 ou 0x00000002 pour AFCntDwn, compteur de bloc 1) ; vecteurs TTN et calcul openssl concordants ; ✅ câblage uplink dans la trame sécurisée (chiffrement avant MIC, déchiffrement après MIC, API C et Python) ; ✅ downlink (compteur NFCntDwn sans FPort, AFCntDwn avec FPort > 0 ; API C et Python)
- ⬜ Classes A, B, C
- ✅ Join OTAA 1.1 : join-request (MIC NwkKey), join-accept (chiffrement NwkKey, MIC JSIntKey si OptNeg, repli 1.0.x) : vecteurs TTN, API C et Python
- 🔧 Rejoin et DevNonce : ✅ rejoin-request types 0, 1, 2 (`core/src/rejoin.cpp`) : MIC par SNwkSIntKey (types 0/2) ou JSIntKey (type 1), comparaison en temps constant, champs non exposés si MIC faux ; vecteurs calculés hors code (RFC 4493) ; ✅ API C et Python (`lsim.rejoin`) ; ✅ garde anti-rejeu `Counter16Guard` (RJcount et DevNonce strictement croissants, enregistrement après MIC seulement) ; ✅ registre serveur `JoinRegistry` (`core/src/join_registry.cpp`) : DevNonce par (JoinEUI, DevEUI), RJcount1 idem, RJcount0 par DevEUI ; MIC vérifié avant toute écriture, capacité bornée (`kMaxRegistryDevices` = 10 000), reset RJcount0 au join-accept ; API C par handles entiers (`lsim_registry_*`, statuts 700+) et binding `lsim.registry.JoinRegistry` ; ✅ persistance du registre (`export_state` / `import_state`, format v1 `LSRG`, MIC AES-CMAC 16 octets vérifié avant tout parsing, chargement atomique, API C `lsim_registry_export` / `lsim_registry_import`, binding `JoinRegistry.save` / `load` avec écriture tmp + fsync + `os.replace`) ; ⬜ base de données durable multi-processus ; ⬜ branchement dans un serveur de jointure réseau complet (hors bibliothèque)
- 🔧 Commandes MAC : ✅ codec C++ LinkCheck, LinkADR, DutyCycle, DevStatus, Rekey (`core/src/mac_commands.cpp`, RFU vérifiés, FOpts borné à 15 octets) ; ✅ RXParamSetup, NewChannel (codec, bornes de fréquence 100 MHz et RFU) ; ✅ API C (`lsim_mac_encode`, `lsim_mac_decode`, `lsim_mac_append_fopts`, statuts 600+) et binding Python (`python/lsim/mac.py`, bornes vérifiées avant l'appel natif) ; ✅ RXTimingSetup (0x08), DeviceTime (0x0D), ForceRejoin (0x0E), RejoinParamSetup (0x0F), DlChannel (0x0A) : codec, API C, Python ; ✅ ADRParamSetup (0x0C) : codec (Limit_exp 7:4, Delay_exp 3:0, 0..15), API C (kinds 24/25), Python ; ✅ PingSlotInfoReq (0x10), PingSlotChannelReq/Ans (0x11), BeaconFreqReq/Ans (0x13) : codec, API C (kinds 26 à 31), Python ; ⬜ BeaconTiming (0x12) déprécié, non implémenté ; ⬜ moteur de classe B (fenêtres de balise et de ping), hors codec ; ✅ ADR côté serveur (décision pure `core/src/adr.cpp`, `lsim_adr_decide`, `lsim.adr.decide`) : SNR max de l'historique, marge exacte par SF (table SX1276, datasheet « LoRa Demodulator SNR »), montée de débit tant que la marge reste ≥ 0, reliquat converti en index de puissance ; limites : pas de modification du masque de canaux, pas de baisse de débit, plan régional à fournir (`dr_sf` monotone) ; ✅ ADR_ACK côté dispositif (`device_on_uplink` / `device_on_downlink`, API C `lsim_adr_device_*`, `lsim.adr.device_uplink`) : ADR_ACK_CNT, ADRACKReq, repli puissance puis débit, réactivation des canaux au débit minimal ; écart signalé avec la figure 14 (texte normatif suivi) ; ✅ rekey effectif (`core/src/rekey.cpp`, API C `lsim_rekey_*`, `lsim.rekey`) : dispositif Pending → Confirmed (RekeyConf de version 1) ou NeedsJoin après ADR_ACK_LIMIT uplinks ; serveur : rejet des trames du nouveau contexte avant le premier RekeyInd, RekeyConf au premier RekeyInd ; ✅ moteur de session dispositif (`core/src/session.cpp`, API C `lsim_session_*` par handles, statuts 780+, `lsim.session.DeviceSession`) : clés et DevAddr de session fixés au join-accept, FCntUp / NFCntDown / AFCntDown remis à zéro (LoRaWAN 1.1 §4.3.1.5), cycle begin_uplink → receive_downlink → end_uplink, ADRACKReq décidé à la construction de la trame, anti-rejeu des compteurs descendants, NeedsJoin bloque les uplinks jusqu'à un nouveau join-accept ; limite : l'envoi de la join-request et la fenêtre de reprise restent à la charge de l'appelant, aucune classe B/C
- ✅ Moteur d'événements discrets : file bornée déterministe, simulation des uplinks (`lsim.simulator`)

## Limites connues (à traiter avant commercialisation)
- Le relief et les obstacles utilisent un modèle simplifié (Deygout à 3 arêtes, pénétration fixe par pavé) : à calibrer par mesures avant usage contractuel.
- Le modèle de collision est un modèle de base : pas de réception multi-passerelle, pas de dérive d'horloge, pas de duty cycle ni de downlink.
- Les FOpts sont câblés en uplink et en downlink (compteurs selon l'errata FCntDwn) ; le codec des commandes MAC existe (`mac_commands.hpp`, API C, `lsim.mac`) mais la simulation n'en génère pas encore.
- Le registre des compteurs de jointure se sauvegarde et se recharge (format v1 protégé par MIC). La clé d'intégrité est fournie par l'appelant et doit être stockée séparément de la sauvegarde. Un registre absent ou non rechargé remet les DevNonce à zéro, ce qui rouvrirait une fenêtre de rejeu tant que les dispositifs n'ont pas rejoint : le serveur doit donc recharger la sauvegarde avant de servir des jointures.
- Vecteurs issus de TTN (Apache-2.0), pas du document TS001.

## Jalon 3 — Scénarios, résultats et analyse
- ✅ Scénarios YAML validés (Pydantic, champs inconnus refusés, bornes 10 000 dispositifs / 5 000 000 transmissions), déploiement déterministe par graine, hash SHA-256 du scénario
- ✅ Export Parquet par dispositif avec métadonnées de traçabilité ; CLI `python -m lsim run`
- 🔧 Métriques avancées : ✅ temps d'antenne par dispositif (cœur, API C, Parquet) ; ✅ charge passerelle (temps occupé en union, pic de trames simultanées, taux d'occupation) ; ✅ latence = temps d'antenne (aucune file ni backhaul modélisés) ; ⬜ énergie (exige les courants réels de l'émetteur, non inventés)
- ⬜ Notebooks pour les bureaux d'études

## Jalon 4 — Visualisation 3D et produit
- ✅ Carte 3D CesiumJS (Apache-2.0) : passerelle, zones de couverture natives, dispositifs colorés par PDR (PointPrimitiveCollection), détail au clic, chargement GeoJSON validé
- ✅ Obstacles extrudés dans la carte (export GeoJSON `kind: obstacle`, hauteur en mètres)
- ✅ Relief dans la carte : terrain CesiumJS local (CustomHeightmapTerrainProvider) à partir du MNT `lsim-dem-v1` ; appareils, passerelle et obstacles posés au sol
- ⬜ Vérification du rendu en gros plan (obstacles et terrain) ; altitudes : le MNT doit être dans le même référentiel que l'ellipsoïde (géoïde à corriger pour les MNT réels)
- ⬜ Fournisseur de tuiles sous contrat pour l'usage commercial
- ⬜ Rapports PDF/Excel, gestion multi-utilisateurs
- ⬜ Empaquetage, documentation, cycle de release
