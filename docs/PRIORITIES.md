# Priorités et carte d'intégration

Ordre de priorité fondé sur les dépendances : chaque niveau consomme les interfaces du niveau précédent.

| Rang | Compartiment | Rôle | Dépend de | Statut |
|------|--------------|------|-----------|--------|
| P0 | Codec de trame (`lorawan_frame`) | Structure filaire, bornes, encodage canonique | — | fait |
| P0 | Crypto (`crypto`, mbedTLS) | AES, CMAC, chiffrement, MIC 1.0/1.1 | mbedTLS | fait |
| P0 | Clés 1.1 (`lorawan_keys`) | Dérivation des clés de session | crypto | fait |
| P1 | **Trame sécurisée (`secure_frame`)** | Scellement et ouverture d'une trame : chiffrement + MIC + contrôle de compteur | codec, crypto, clés | **ce cycle** |
| P1 | Radio (`lora_phy`, `link_budget`) | Temps d'antenne, sensibilité, propagation | — | fait |
| P1 | **Moteur d'événements (`engine`)** | File d'événements déterministe, collisions et capture | radio, trame | **ce cycle** (minimal) |
| P2 | MAC complète | Join OTAA 1.1, commandes MAC, FOpts chiffrés, ADR, classes A/B/C | P1 | à faire |
| P3 | API Python (`ctypes`) | Exposition scénarios, résultats, clés | P1, P2 | à faire |
| P4 | Scénarios YAML + export Parquet | Configuration reproductible, analyse | P3 | à faire |
| P5 | Carte 3D (CesiumJS) | Visualisation des couvertures et du trafic | P4 | à faire |
| P6 | Régions (EU868, US915, AS923…) | Profils data-driven | P1, P2 | à faire |

## Règles d'intégration

1. **Un seul chemin de vérification du MIC** : toute trame reçue passe par `open_uplink`, qui compare le MIC en temps constant et ne déchiffre qu'après succès.
2. **Pas de compteur implicite** : le compteur 32 bits est fourni par l'appelant (serveur de réseau) ; un FCnt 16 bits incohérent est rejeté.
3. **Déterminisme** : temps en nanosecondes entières ; ordre des événements `(temps, numéro de séquence)`.
4. **Frontière unique** : Python ne voit que l'API C (`c_api.h`) ; aucun pointeur interne n'est exposé.
5. **Surface exportée minimale** : `exports.map` n'expose que `lsim_*`.
