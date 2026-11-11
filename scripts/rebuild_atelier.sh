#!/usr/bin/env bash
# Reconstruction de l'environnement de travail apres reinitialisation du bac a sable.
#
# Le bac a sable est regulierement remis a blanc : `build/` et `web/node_modules/`
# disparaissent, seul le depot survit. Ce script retablit l'environnement depuis la branche.
#
# Usage :  bash scripts/rebuild_atelier.sh
#
# Il est **idempotent** : relancable apres un echec partiel. Il ne touche jamais au depot
# principal et ne fait aucun `reset --hard` : un arbre sale est un travail en cours, pas
# un incident.
#
# Empreinte attestee au 2026-11-09 (apres reconstruction complete) :
#   liblsim_core.so   608 984 octets
#   ctest             1 / 1
#
# Ce script complete `rebuild_u0.sh`, qui vise une autre disposition (depot dans
# /home/user/work, build separe). Celui-ci travaille **dans** le depot : `pyenv/` et `build/`
# y sont ignores par `.gitignore`.
set -euo pipefail

cd "$(dirname "$0")/.."
RACINE="$PWD"

echo "=== 1/4 venv ==="
[ -x pyenv/bin/python ] || python3 -m venv pyenv
pyenv/bin/pip install -q --upgrade pip
pyenv/bin/pip install -q "./python[test]"
# cmake n'est pas dans le PATH systeme : il provient d'un paquet pip.
pyenv/bin/pip install -q cmake

echo "=== 2/4 coeur natif ==="
pyenv/bin/cmake -S "$RACINE" -B "$RACINE/build" \
    -DCMAKE_BUILD_TYPE=Release -DLSIM_WARNINGS_AS_ERRORS=ON
pyenv/bin/cmake --build "$RACINE/build" -j"$(nproc)"
stat -c "    liblsim_core.so : %s octets" build/liblsim_core.so

echo "=== 3/4 ctest ==="
pyenv/bin/ctest --test-dir build --output-on-failure

echo "=== 4/4 dependances web ==="
( cd web && npm ci )

echo "=== ENVIRONNEMENT PRET ==="
