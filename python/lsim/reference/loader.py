"""Chargement des paramètres de référence (lecture seule, validation stricte)."""

from __future__ import annotations

import json
import math
from importlib import resources
from typing import Any

_SIEGEN = "siegen_indoor_lorawan.json"


def _check_numbers(obj: Any, path: str) -> None:
    if isinstance(obj, dict):
        for key, value in obj.items():
            _check_numbers(value, f"{path}.{key}")
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            _check_numbers(value, f"{path}[{i}]")
    elif isinstance(obj, float) and not math.isfinite(obj):
        raise ValueError(f"valeur non finie dans {path}")


def load_siegen_indoor() -> dict[str, Any]:
    """Retourne les paramètres du jeu Siegen (CC BY 4.0) : provenance, modèles, avertissements."""
    text = resources.files(__package__).joinpath(_SIEGEN).read_text(encoding="utf-8")
    doc = json.loads(text)
    if doc.get("dataset", {}).get("licence") != "CC BY 4.0":
        raise ValueError("licence inattendue pour le jeu Siegen")
    _check_numbers(doc, "siegen")
    return doc
