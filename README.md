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
- **Performance** : arithmétique entière, aucune allocation dynamique dans le cœur.
- **Déterminisme** : temps en nanosecondes entières, résultats reproductibles.

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
```

## Statut

Jalon 0 en cours. Voir [docs/ROADMAP.md](docs/ROADMAP.md).

## Licence

Apache License 2.0, voir [LICENSE](LICENSE).
