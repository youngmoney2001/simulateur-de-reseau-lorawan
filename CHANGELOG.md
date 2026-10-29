# Journal des changements

## 0.1.0 (non publiée)

### Radio et régions
- Sensibilités SX1276 Rev. 4 pour 125, 250 et 500 kHz (SF7 à SF12), alignées sur le datasheet.
- Atténuation par matériau (UIT-R P.2040-4) : pertes de traversée, avec avertissement hors plage.
- Régions : EU868 (ETSI EN 300 220-2, RP002), AS923 (Japon, partiel), RU864, KR920 (partiel).
- US915 et AU915 : sous-bandes 1 à 8 (`sub_band` dans les groupes ; `lsim serve --sub-band`), règle LinkADRReq ChMaskCntl 0 à 7 (`lsim.channel_mask`). Le serveur envoie un LinkADRReq de sous-bande à chaque jointure, renvoyé jusqu'à acquittement (8 essais) ; la passerelle Basic Station annonce la sous-bande (canal 500 kHz sur radio_1).

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
