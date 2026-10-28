# simulateur-de-reseau-lorawan

Simulateur de réseaux LoRaWAN pour bureaux d'études et opérateurs.
Cœur de calcul en C++17, données et analyse en Python.

## Architecture

```
core/            Cœur natif C++17 (calculs radio et protocole)
  include/lsim/  API publique (C++ et C stable)
  src/           Implémentation
  tests/         Tests unitaires C++
python/          API Python (ctypes) et tests
docs/            Feuille de route
```

Principes :
- **Sécurité** : entrées validées à chaque frontière, statuts d'erreur explicites,
  aucune exception ni UB traversant l'API C, surface exportée minimale (`LSIM_API`).
- **Performance** : arithmétique entière ; allocations dimensionnées à partir de limites
  explicites (10 000 dispositifs, 5 000 000 transmissions), jamais en croissance non bornée.
- **Déterminisme** : temps en nanosecondes entières, résultats reproductibles.

## Dépendances

- Compilateur C++17, CMake ≥ 3.20, Python ≥ 3.10.
- mbedTLS 3.6.4 (Apache-2.0) est récupéré automatiquement depuis GitHub à la configuration (accès réseau requis la première fois). Voir [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Compilation et tests

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --parallel
ctest --test-dir build --output-on-failure      # tests C++
PYTHONPATH=python pytest -q python/tests        # tests Python
```

Exemple :

```python
from lsim import RadioConfig, time_on_air_ns
time_on_air_ns(RadioConfig(spreading_factor=7), 10)   # 41216000 ns

from lsim.simulator import EndDevice, Gateway, Propagation, simulate_uplinks
simulate_uplinks([EndDevice(x_m=10.0)], Gateway(), Propagation()).totals.received   # 1
```

Les clés et trames 1.1 sont dans `lsim.security` (`derive_session_keys_11`,
`seal_uplink`, `open_uplink`). Convention : identifiants et nonces en ordre de transmission (LSB first).

Tests C++ sous AddressSanitizer et UBSan (inclut le fuzzing du codec de trame) :

```bash
cmake -S . -B build-asan -DCMAKE_BUILD_TYPE=Debug \
  -DCMAKE_CXX_FLAGS="-fsanitize=address,undefined -fno-sanitize-recover=all" \
  -DCMAKE_EXE_LINKER_FLAGS="-fsanitize=address,undefined" \
  -DCMAKE_SHARED_LINKER_FLAGS="-fsanitize=address,undefined"
cmake --build build-asan && ./build-asan/lsim_tests
```

## Statut

Jalons 0 et 1 en grande partie faits. Jalon 2 (LoRaWAN 1.1) en cours : codec, crypto,
dérivation de clés et trame sécurisée (MIC vérifié avant déchiffrement) sont prêts ;
la jointure OTAA et le chiffrement FOpts suivent. Un moteur d'événements et une
simulation des liaisons montantes sont disponibles (modèle de base).
Voir [docs/ROADMAP.md](docs/ROADMAP.md).

## Licence

Apache License 2.0, voir [LICENSE](LICENSE).
