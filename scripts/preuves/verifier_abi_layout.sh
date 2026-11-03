#!/usr/bin/env bash
# Harnais de dispositions ABI : exécution x86-64, compilation i386.
#
#   bash scripts/preuves/verifier_abi_layout.sh
#
# Attendu en x86-64 : « structures vérifiées : 55, grandeurs : 477 ».
# (jalon I0 : +2 structures — lsim_plan_device_rx2, lsim_plan_downlinks_v2_args — et +23 grandeurs)
# En i386, seule la COMPILATION est possible ici (pas de CRT ni de libc 32 bits) :
# le script le signale explicitement au lieu de prétendre à une exécution.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
CXX=${CXX:-g++}
OUT=$(mktemp -d)
trap 'rm -rf "$OUT"' EXIT

echo "== x86-64 : compilation et exécution du harnais =="
"$CXX" -std=c++17 -Wall -Wextra -I "$ROOT/core/include" \
       -DABI_LAYOUT_STANDALONE "$ROOT/core/tests/abi_layout.cpp" -o "$OUT/abi64"
"$OUT/abi64"

echo "== i386 : compilation seule =="
if "$CXX" -m32 -ffreestanding -std=c++17 -Wall -Wextra -I "$ROOT/core/include" \
          -c "$ROOT/core/tests/abi_layout.cpp" -o "$OUT/abi32.o" 2>"$OUT/i386.err"; then
    echo "i386 : objet produit ($(wc -c < "$OUT/abi32.o") octets) — dispositions seules, aucune exécution"
else
    echo "i386 : compilation impossible dans cet environnement"
    sed 's/^/    /' "$OUT/i386.err" | head -5
    echo "Rappel : l'absence de multilib ne prouve rien sur le moteur 32 bits."
fi
