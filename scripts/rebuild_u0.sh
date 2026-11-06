#!/usr/bin/env bash
# Reconstruction de l'environnement de travail après réinitialisation du bac à sable.
#
# Le bac à sable est régulièrement remis à blanc : /home/user/work, /home/user/pyenv et
# /home/user/build_u0_1 disparaissent, seul le dépôt principal survit. Ce script rétablit
# l'environnement complet à partir de la branche distante.
#
# Usage :  bash scripts/rebuild_u0.sh [--sans-tests]
#
# Il est **idempotent** : relançable après un échec partiel. Il ne touche jamais au dépôt
# principal (/home/user/simulateur-de-reseau-lorawan).
#
# Empreintes attestées au 2026-11-06 (après reconstruction complète) :
#   liblsim_core.so   596 696 octets
#   ctest             1 / 1
#   pytest            2318 passed / 15 failed / 1 skipped / 16 subtests

set -euo pipefail

BRANCHE="arena/fdc94521-simulateur-de-reseau-lorawan"
RACINE="/home/user"
DEPOT="$RACINE/work"
PYENV="$RACINE/pyenv"
BUILD="$RACINE/build_u0_1"
SO_ATTENDU=596696

cd "$RACINE"

# ------------------------------------------------------------------- 1. le dépôt de travail
if [ -d "$DEPOT/.git" ]; then
    echo "== 1/4 dépôt déjà présent, mise à jour"
    git -C "$DEPOT" fetch origin
    git -C "$DEPOT" checkout "$BRANCHE"
    git -C "$DEPOT" reset --hard "origin/$BRANCHE"
else
    echo "== 1/4 clonage de $BRANCHE"
    git clone --branch "$BRANCHE" \
        https://github.com/youngmoney2001/simulateur-de-reseau-lorawan.git "$DEPOT"
fi
git -C "$DEPOT" config user.name  "Agent Arena"
git -C "$DEPOT" config user.email "agent@arena.ai"

# --------------------------------------------------------- 2. environnement Python
if [ ! -x "$PYENV/bin/python" ]; then
    echo "== 2/4 création du venv"
    python3 -m venv "$PYENV"
fi
echo "== 2/4 installation du paquet [test] et de cmake"
"$PYENV/bin/pip" install -q --upgrade pip
"$PYENV/bin/pip" install -q "$DEPOT/python[test]"
# cmake n'est pas dans le PATH système : il provient d'un paquet pip (4.4.4).
"$PYENV/bin/pip" install -q cmake

# ------------------------------------------------------------------ 3. cœur C++
echo "== 3/4 compilation du cœur natif"
"$PYENV/bin/cmake" -S "$DEPOT" -B "$BUILD" \
    -DCMAKE_BUILD_TYPE=Release -DLSIM_WARNINGS_AS_ERRORS=ON
"$PYENV/bin/cmake" --build "$BUILD" -j"$(nproc)"

TAILLE=$(stat -c %s "$BUILD/liblsim_core.so")
echo "    liblsim_core.so : $TAILLE octets (attendu $SO_ATTENDU)"
[ "$TAILLE" -eq "$SO_ATTENDU" ] || echo "    ATTENTION : empreinte différente"

echo "== 3/4 ctest"
"$PYENV/bin/ctest" --test-dir "$BUILD" --output-on-failure

# ------------------------------------------------------------------ 4. vérification
if [ "${1:-}" = "--sans-tests" ]; then
    echo "== 4/4 ignorée (--sans-tests)"
    exit 0
fi
echo "== 4/4 suite Python (long : ~2 min)"
cd "$DEPOT"
PYTHONPATH=python LSIM_LIBRARY="$BUILD/liblsim_core.so" \
    "$PYENV/bin/python" -m pytest -q python/tests
