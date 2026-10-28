"""Chargement de la bibliothèque native lsim et déclaration des prototypes C.

Chaque prototype est déclaré explicitement (types et arguments) : aucun appel
implicite avec des types par défaut, ce qui évite les troncatures silencieuses.
"""

from __future__ import annotations

import ctypes
import os
from pathlib import Path


class _CRadioConfig(ctypes.Structure):
    _fields_ = [
        ("spreading_factor", ctypes.c_uint8),
        ("bandwidth_hz", ctypes.c_uint32),
        ("coding_rate", ctypes.c_uint8),
        ("preamble_symbols", ctypes.c_uint16),
        ("crc_on", ctypes.c_uint8),
        ("explicit_header", ctypes.c_uint8),
        ("low_data_rate_optimize", ctypes.c_uint8),
    ]



def _load_library() -> ctypes.CDLL:
    """Charge la bibliothèque native. Chemin surchargeable via LSIM_LIBRARY."""
    override = os.environ.get("LSIM_LIBRARY")
    candidates = [Path(override)] if override else []
    root = Path(__file__).resolve().parents[2]
    candidates += [
        root / "build" / "liblsim_core.so",
        root / "build" / "liblsim_core.dylib",
        root / "build" / "Release" / "lsim_core.dll",
    ]
    for path in candidates:
        if path.is_file():
            lib = ctypes.CDLL(str(path))
            break
    else:
        raise OSError(
            "bibliothèque native lsim introuvable : compilez le cœur "
            "(cmake -S . -B build && cmake --build build) ou définissez LSIM_LIBRARY"
        )

    lib.lsim_version.restype = ctypes.c_uint32
    lib.lsim_version.argtypes = []
    lib.lsim_time_on_air_ns.restype = ctypes.c_int32
    lib.lsim_time_on_air_ns.argtypes = [
        ctypes.POINTER(_CRadioConfig),
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_int64),
    ]
    return lib



_DBL = ctypes.POINTER(ctypes.c_double)

LIB = _load_library()

LIB.lsim_receiver_sensitivity_dbm.restype = ctypes.c_int32
LIB.lsim_receiver_sensitivity_dbm.argtypes = [ctypes.c_uint8, ctypes.c_uint32, _DBL]
LIB.lsim_free_space_path_loss_db.restype = ctypes.c_int32
LIB.lsim_free_space_path_loss_db.argtypes = [ctypes.c_double, ctypes.c_double, _DBL]
LIB.lsim_log_distance_path_loss_db.restype = ctypes.c_int32
LIB.lsim_log_distance_path_loss_db.argtypes = [
    ctypes.c_double, ctypes.c_double, ctypes.c_double, ctypes.c_double, _DBL]
LIB.lsim_max_allowable_path_loss_db.restype = ctypes.c_int32
LIB.lsim_max_allowable_path_loss_db.argtypes = [ctypes.c_double] * 6 + [_DBL]
LIB.lsim_max_range_m.restype = ctypes.c_int32
LIB.lsim_max_range_m.argtypes = [ctypes.c_double, ctypes.c_double, ctypes.c_double, ctypes.c_double, _DBL]
