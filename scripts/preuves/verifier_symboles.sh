#!/usr/bin/env bash
# Symboles exportés par le cœur, et comparaison éventuelle à une bibliothèque de référence.
#
#   bash scripts/preuves/verifier_symboles.sh build/liblsim_core.so
#   bash scripts/preuves/verifier_symboles.sh build/liblsim_core.so /chemin/ref.so
#
# Attendu au commit 68176d6 : 95 symboles, SHA-256 de la liste triée
# e8b97058ca45d79bb902c69aeac666e6eaa3a4d25e3bfa1a9ff99e115494e234.
# Base avant R2b (c46d531) : 91 symboles.  main (1f43370) : 79 symboles.
set -euo pipefail

LIB=${1:?usage : verifier_symboles.sh LIB [LIB_REF]}
REF=${2:-}
OUT=$(mktemp -d)
trap 'rm -rf "$OUT"' EXIT

liste() { nm -D --defined-only "$1" | awk '{print $3}' | grep '^lsim_' | sort; }
liste "$LIB" > "$OUT/current.txt"
echo "bibliothèque : $LIB"
echo "symboles lsim_* : $(wc -l < "$OUT/current.txt")"
echo "SHA-256 (liste triée) : $(sha256sum "$OUT/current.txt" | cut -d' ' -f1)"

if [ -n "$REF" ]; then
    liste "$REF" > "$OUT/ref.txt"
    echo "référence : $REF ($(wc -l < "$OUT/ref.txt") symboles)"
    echo "ajoutés   : $(comm -13 "$OUT/ref.txt" "$OUT/current.txt" | wc -l)"
    echo "retirés   : $(comm -23 "$OUT/ref.txt" "$OUT/current.txt" | wc -l)"
    comm -13 "$OUT/ref.txt" "$OUT/current.txt" | sed 's/^/    + /'
    comm -23 "$OUT/ref.txt" "$OUT/current.txt" | sed 's/^/    - /'
fi
