#!/usr/bin/env bash
# Compile le studio web et le depose dans le paquet Python, sous lsim/web_dist.
#
# Une fois depose la, le serveur le sert tout seul (lsim.studio_static.find_dist) :
# l utilisateur n a plus besoin de Node ni de Vite pour ouvrir le studio.
#
# Usage : scripts/package_studio.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WEB="${ROOT}/web"
CIBLE="${ROOT}/python/lsim/web_dist"

if [[ ! -d "${WEB}" ]]; then
    echo "dossier web/ introuvable : ${WEB}" >&2
    exit 1
fi

echo "==> installation des dependances du studio"
(cd "${WEB}" && npm ci --no-audit --no-fund)

echo "==> compilation du studio"
(cd "${WEB}" && npm run build)

if [[ ! -f "${WEB}/dist/studio.html" ]]; then
    echo "compilation terminee mais dist/studio.html absent" >&2
    exit 1
fi

echo "==> depot dans ${CIBLE}"
rm -rf "${CIBLE}"
mkdir -p "${CIBLE}"
cp -R "${WEB}"/dist/. "${CIBLE}"/

echo "==> contenu servi"
find "${CIBLE}" -type f | sed "s|${CIBLE}/||" | sort
