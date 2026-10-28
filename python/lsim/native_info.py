"""Version du cœur natif (sans dépendance au reste du paquet)."""

from lsim._native import LIB


def native_version() -> str:
    v = LIB.lsim_version()
    return f"{(v >> 16) & 0xFF}.{(v >> 8) & 0xFF}.{v & 0xFF}"
