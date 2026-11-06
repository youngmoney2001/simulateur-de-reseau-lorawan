#!/usr/bin/env bash
# Empreintes gelées : rejoue scripts/mac_baseline_dump.py et compare aux valeurs de référence.
#
#   LSIM_LIBRARY=build/liblsim_core.so bash scripts/preuves/verifier_empreintes.sh
#
# Valeurs attendues (identiques depuis la base 1f43370) :
#   JSON  d2cb0fac6c2d99504d888e497f5e07c56ba0f7b81deaf560584c78ee19b4e1ea
#   trace ed126d7ff5aac3b006f31067d73fb6a5f5b5bf9b597021589910c24db8dc865b
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
PYTHON=${PYTHON:-python3}
: "${LSIM_LIBRARY:?définir LSIM_LIBRARY (chemin de liblsim_core.so)}"
OUT=$(mktemp -d)
trap 'rm -rf "$OUT"' EXIT

"$PYTHON" -c "import yaml" 2>/dev/null || {
    echo "ÉCHEC : l'interpréteur « $PYTHON » n'a pas PyYAML." >&2
    echo "Définir PYTHON=/chemin/vers/python (interpréteur du projet)." >&2
    exit 2
}

PYTHONPATH="$ROOT/python" LSIM_LIBRARY="$LSIM_LIBRARY" \
    "$PYTHON" "$ROOT/scripts/mac_baseline_dump.py" "$OUT/dump.json" > /dev/null

json=$(sha256sum "$OUT/dump.json" | cut -d' ' -f1)
trace=$(sha256sum "$OUT/dump.json.trace.json" | cut -d' ' -f1)
att_json=d2cb0fac6c2d99504d888e497f5e07c56ba0f7b81deaf560584c78ee19b4e1ea
att_trace=ed126d7ff5aac3b006f31067d73fb6a5f5b5bf9b597021589910c24db8dc865b

echo "JSON  : $json"
echo "trace : $trace"
statut=0
[ "$json" = "$att_json" ]   || { echo "ÉCART JSON (attendu $att_json)";   statut=1; }
[ "$trace" = "$att_trace" ] || { echo "ÉCART trace (attendu $att_trace)"; statut=1; }
[ "$statut" -eq 0 ] && echo "OK : empreintes gelées inchangées"
exit "$statut"
