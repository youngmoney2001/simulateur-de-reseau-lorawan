#!/usr/bin/env bash
# Produit une archive du cœur natif lsim (bibliothèque partagée, en-tête C, licences)
# dans dist/ : lsim-native-<version>-<os>-<arch>.tar.gz + empreinte SHA-256.
# Usage : scripts/package_native.sh  (exige cmake, un compilateur C++17 et l'accès à GitHub
# pour récupérer mbedTLS à la configuration).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD="${ROOT}/build-release"
DIST="${ROOT}/dist"

cmake -S "${ROOT}" -B "${BUILD}" -DCMAKE_BUILD_TYPE=Release
cmake --build "${BUILD}" --parallel

VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' "${ROOT}/python/pyproject.toml" | head -1)"
OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
ARCH="$(uname -m)"
NAME="lsim-native-${VERSION}-${OS}-${ARCH}"
STAGE="${DIST}/${NAME}"

LIB=""
for candidate in liblsim_core.so liblsim_core.dylib lsim_core.dll; do
    if [[ -f "${BUILD}/${candidate}" ]]; then LIB="${BUILD}/${candidate}"; break; fi
done
if [[ -z "${LIB}" ]]; then
    echo "bibliothèque native introuvable dans ${BUILD}" >&2
    exit 1
fi

rm -rf "${STAGE}"
mkdir -p "${STAGE}/lib" "${STAGE}/include/lsim"
cp "${LIB}" "${STAGE}/lib/"
cp "${ROOT}/core/include/lsim/c_api.h" "${STAGE}/include/lsim/"
cp "${ROOT}/LICENSE" "${ROOT}/THIRD_PARTY_NOTICES.md" "${STAGE}/"

(
    cd "${DIST}"
    tar -czf "${NAME}.tar.gz" "${NAME}"
    sha256sum "${NAME}.tar.gz" > "${NAME}.tar.gz.sha256"
)
echo "archive : ${DIST}/${NAME}.tar.gz"
