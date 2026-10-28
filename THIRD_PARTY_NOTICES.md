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
