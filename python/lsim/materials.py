"""Atténuation des matériaux de construction (UIT-R P.2040-4), calculée par le cœur natif.

Les noms ci-dessous suivent l'ordre de l'énumération C++ `lsim::materials::Material` ;
l'ordre est vérifié contre le natif (`lsim_material_count`) à l'import.
"""

from __future__ import annotations

import ctypes
import math
from typing import Final

from lsim._native import LIB as _LIB
from lsim.lora import StatusError

MATERIAL_NAMES: Final[tuple[str, ...]] = (
    "air",
    "concrete",
    "brick",
    "plasterboard",
    "wood",
    "glass",
    "acrylic_glass",
    "ceiling_panel",
    "chipboard_panel",
    "plywood",
    "marble",
    "floor_panel",
    "vinyl_tile",
    "carpet_tile",
    "bituminous_asphalt",
)

if _LIB.lsim_material_count() != len(MATERIAL_NAMES):
    raise RuntimeError("table des matériaux désynchronisée avec le cœur natif")


def traversal_loss(material: str, frequency_hz: float, thickness_m: float) -> tuple[float, bool]:
    """Perte (dB) d'une traversée de `thickness_m` mètres ; second terme : extrapolé.

    `extrapolated` vaut True si la fréquence est hors de la plage documentée du matériau.
    Les pertes aux interfaces ne sont pas comptées.
    """
    try:
        material_id = MATERIAL_NAMES.index(material)
    except ValueError:
        raise ValueError(f"matériau inconnu : {material!r}") from None
    if not math.isfinite(frequency_hz) or frequency_hz <= 0:
        raise ValueError("frequency_hz doit être strictement positive et finie")
    if not math.isfinite(thickness_m) or thickness_m < 0:
        raise ValueError("thickness_m doit être positive et finie")
    out = ctypes.c_double(0.0)
    flag = ctypes.c_int32(0)
    status = _LIB.lsim_material_traversal_loss_db(
        material_id, frequency_hz, thickness_m, ctypes.byref(out), ctypes.byref(flag))
    if status != 0:
        raise StatusError(status)
    return out.value, bool(flag.value)
