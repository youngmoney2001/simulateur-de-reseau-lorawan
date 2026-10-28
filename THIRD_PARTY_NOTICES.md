# Notices des composants tiers

## mbedTLS 3.6.4

- Usage : primitives AES-128 (ECB) et AES-CMAC (RFC 4493) du module `core/src/crypto.cpp`.
- Source : https://github.com/Mbed-TLS/mbedtls, commit `c765c831e5c2a0971410692f92f7a81d6ec65ec2` (tag v3.6.4).
- Licence retenue : Apache-2.0 (mbedTLS est aussi distribué sous GPL-2.0-or-later ; nous utilisons l'option Apache-2.0).
- Récupéré automatiquement par CMake (`FetchContent`) à la configuration ; non copié dans ce dépôt.
- Seule la bibliothèque `mbedcrypto` est construite (programmes et tests désactivés).
- Le script de version `core/exports.map` empêche l'exposition des symboles mbedTLS dans la bibliothèque partagée `liblsim_core.so`.

## Vecteurs de test LoRaWAN 1.1 (TheThingsNetwork/lorawan-stack)

- Usage : valeurs attendues des tests `core/tests/test_crypto.cpp` (dérivations de clés 1.1, MIC 1.1, chiffrement avec identifiant de trame). Seules les valeurs numériques sont reprises ; aucun code n'est copié.
- Source : https://github.com/TheThingsNetwork/lorawan-stack (`pkg/crypto/key_derivation_test.go`, `data_messages_test.go`), licence Apache-2.0.
- Ces valeurs ont été recalculées indépendamment avec la bibliothèque `cryptography` avant intégration.

## CesiumJS 1.146.0 (carte 3D, `web/`)

- Usage : rendu 3D de la carte des résultats. Les ressources statiques (Workers, Assets, Widgets) sont copiées localement dans `web/public/cesium` ; aucun jeton Cesium ion n'est utilisé.
- Licence : Apache-2.0. Le crédit « Cesium ion » affiché par défaut doit être conservé tant qu'il est requis par la licence ou le contrat.
- Source : https://github.com/CesiumGS/cesium (paquet npm `cesium`).

## Vite (outil de build de `web/`)

- Usage : serveur de développement et build de l'interface. Non distribué dans le produit final hormis le bundle.
- Licence : MIT.

## OpenStreetMap (fond de carte, `web/src/main.js`)

- Usage : tuiles du fond de carte, appelées depuis le navigateur de l'utilisateur.
- Données : © contributeurs OpenStreetMap, licence ODbL. La politique d'usage des tuiles limite l'usage intensif ; un usage commercial doit utiliser un fournisseur de tuiles sous contrat.

## Vecteurs de jointure LoRaWAN 1.1 (TheThingsNetwork/lorawan-stack)

- Usage : valeurs attendues des tests `core/tests/test_join.cpp` et `python/tests/test_join.py` (join-request, join-accept, MIC 1.0.x et 1.1, chiffrement du join-accept). Seules les valeurs numériques sont reprises.
- Source : `pkg/crypto/join_messages_test.go`, licence Apache-2.0.

## Jeu de données LoRaWAN en intérieur, Université de Siegen (paramètres de propagation)

- Usage : paramètres ajustés des modèles de perte de parcours (LDPLM-MW, COST231-MWM, LDPLM-MW-EP) dans `python/lsim/reference/siegen_indoor_lorawan.json`. Le jeu brut n'est pas copié dans ce dépôt.
- Auteurs : Nahshon Mokua Obiri, Kristof Van Laerhoven. Article : https://doi.org/10.1109/ACCESS.2025.3569164 (IEEE Access, vol. 13, 2025).
- Jeu de données : https://doi.org/10.5281/zenodo.15349730 ; code : https://github.com/nahshonmokua/LoRaWAN-Indoor-PathLoss-Dataset-IEEEACCESS (commit `7fa0327c8ed65a5823f4923f6d62301fff69d935`).
- Licence : CC BY 4.0 (section « License » du README du dépôt ; aucun fichier LICENSE séparé). Attribution requise dans tout produit qui reprend ces paramètres.

## Données de consommation (valeurs numériques, aucun code copié)

- Semtech SX1262 : datasheet (Rev. 1.2 et v2.1, copies publiques) : courants d'émission, réception LoRa 125 kHz 4,6 mA, veille « SLEEP warm start » 600 nA (configuration conservée ; source secondaire : copie de la datasheet Rev. 2.2). Utilisé dans `core/src/energy.cpp` (profil 1).
- STM32L072xx : fiche technique ST (DocID027100), Stop 0,43 µA typ., « jusqu'à » 93 µA/MHz en Run. Utilisé dans `core/src/energy.cpp` (profil 1).
- RAKwireless RAK4631 : documentation RAKwireless (tension 3,3 V nominale, courants Tx/Rx/veille module). Utilisé dans `core/src/energy.cpp` (profil 0).

## Protocole passerelle Semtech UDP (GWMP v2)

- Usage : format des messages PUSH_DATA, PULL_DATA, PULL_RESP, TX_ACK et de leurs champs JSON (`python/lsim/gwmp.py`). Seul le format des messages est repris ; aucun code source n'est copié.
- Source : `PROTOCOL.TXT`, dépôt https://github.com/Lora-net/packet_forwarder (© 2013 Semtech, révision v1.4).
- Licence du dépôt : BSD (conditions de redistribution du fichier LICENSE du dépôt).

## cryptography (chiffrement au repos du serveur, extra `serve`)

- Bibliothèque Python `cryptography` (PyCA), licence Apache-2.0 ou BSD-3-Clause, dépendance
  optionnelle : utilisée pour AES-256-GCM (`python/lsim/sealed.py`). Aucun code copié.

## Plans régionaux US902-928 (valeurs seulement)

- Tableaux DR, charges maximales et règle RX1 extraits des Regional Parameters RP002 (LoRa
  Alliance) et de la page The Things Network « US902-928 MHz Band ». Valeurs numériques
  reprises, aucun texte copié. Source de référence : `python/lsim/us915.py`.
