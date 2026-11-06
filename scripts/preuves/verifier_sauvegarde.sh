#!/usr/bin/env bash
# Vérifie une sauvegarde : empreinte, extraction, comparaison au dépôt, clone du bundle.
#
#   bash scripts/preuves/verifier_sauvegarde.sh /home/user/sauvegardes/xxx.tar.gz [xxx.bundle]
#
# La comparaison ignore `__pycache__` et, séparément, `.git/refs/remotes` + son journal :
# une archive prise avant un push conserve légitimement l'ancienne référence distante.
set -euo pipefail

TAR=${1:?usage : verifier_sauvegarde.sh ARCHIVE.tar.gz [ARCHIVE.bundle]}
BUNDLE=${2:-}
ROOT=${PREUVES_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}  # PREUVES_ROOT : comparaison
                                                          # avec un autre arbre
OUT=$(mktemp -d)
trap 'rm -rf "$OUT"' EXIT

SHAFILE="${TAR%.tar.gz}.sha256"
if [ -f "$SHAFILE" ]; then
    echo "== empreinte =="
    (cd "$(dirname "$TAR")" && sha256sum -c "$(basename "$SHAFILE")")
else
    echo "== empreinte : aucun fichier .sha256 voisin, étape ignorée =="
fi

echo "== extraction =="
mkdir -p "$OUT/extract"
tar xzf "$TAR" -C "$OUT/extract"
BASE="$OUT/extract/recovery"
[ -d "$BASE" ] || { echo "ÉCHEC : racine « recovery/ » absente de l'archive"; exit 1; }

echo "== arbre de travail (hors .git et __pycache__) =="
if diff -r --exclude=.git --exclude=__pycache__ --exclude=.pytest_cache --exclude=build \
        "$BASE" "$ROOT" > "$OUT/diff.txt" 2>&1; then
    echo "identique"
else
    echo "ÉCARTS :"; sed 's/^/    /' "$OUT/diff.txt" | head -20
    echo "ÉCHEC : le contenu du projet diverge"
    exit 1
fi

echo "== commit =="
HEAD_ARCHIVE=$(git -C "$BASE" rev-parse HEAD)
HEAD_REPO=$(git -C "$ROOT" rev-parse HEAD)
echo "archive : $HEAD_ARCHIVE"
echo "dépôt   : $HEAD_REPO"
[ "$HEAD_ARCHIVE" = "$HEAD_REPO" ] || { echo "ÉCHEC : commits différents"; exit 1; }

echo "== références distantes (information) =="
if diff -r "$BASE/.git/refs/remotes" "$ROOT/.git/refs/remotes" > "$OUT/refs.txt" 2>&1; then
    echo "identiques"
else
    echo "références différentes (informatif : clone frais ou archive antérieure à un push) :"
    # `|| true` : une différence de références est informative, jamais une erreur.
    # Si `diff` ne produit que des lignes « Only in … », le grep ne trouve rien et
    # retournerait 1 : sans ce garde-fou, `pipefail` ferait échouer tout le script
    # alors que l'arbre et le commit sont conformes.
    grep -E "^[<>]" "$OUT/refs.txt" | sed 's/^/    /' | head -6 || true
fi

if [ -n "$BUNDLE" ]; then
    echo "== clone du bundle =="
    git clone -q "$BUNDLE" "$OUT/clone" 2>/dev/null
    echo "HEAD     : $(git -C "$OUT/clone" rev-parse HEAD)"
    echo "fichiers : $(git -C "$OUT/clone" ls-files | wc -l)"
    echo "modifiés : $(git -C "$OUT/clone" status --porcelain | wc -l)"
fi
