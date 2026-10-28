# Notices des composants tiers

## mbedTLS 3.6.4

- Usage : primitives AES-128 (ECB) et AES-CMAC (RFC 4493) du module `core/src/crypto.cpp`.
- Source : https://github.com/Mbed-TLS/mbedtls, commit `c765c831e5c2a0971410692f92f7a81d6ec65ec2` (tag v3.6.4).
- Licence retenue : Apache-2.0 (mbedTLS est aussi distribué sous GPL-2.0-or-later ; nous utilisons l'option Apache-2.0).
- Récupéré automatiquement par CMake (`FetchContent`) à la configuration ; non copié dans ce dépôt.
- Seule la bibliothèque `mbedcrypto` est construite (programmes et tests désactivés).
- Le script de version `core/exports.map` empêche l'exposition des symboles mbedTLS dans la bibliothèque partagée `liblsim_core.so`.
