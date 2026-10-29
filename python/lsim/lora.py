"""Calculs physiques LoRa, déléguées au cœur natif (C++) via l'API C.

Le cœur n'est jamais réimplémenté en Python : Python gère les données,
le natif gère les calculs. Les entrées sont validées avant l'appel natif.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
from typing import Optional

from lsim.status import describe

_VALID_BW_HZ = (125_000, 250_000, 500_000)


class StatusError(ValueError):
    """Erreur renvoyée par le cœur natif, avec le code de statut."""

    def __init__(self, code: int) -> None:
        self.code = code
        super().__init__(f"lsim: {describe(code)} (code {code})")


@dataclass(frozen=True)
class RadioConfig:
    """Configuration radio d'une trame (valeurs par défaut : LoRaWAN SF7/125 kHz/4 5)."""

    spreading_factor: int = 7
    bandwidth_hz: int = 125_000
    coding_rate: int = 1
    preamble_symbols: int = 8
    crc_on: bool = True
    explicit_header: bool = True
    # None : règle LoRaWAN, activée si la durée d'un symbole dépasse 16 ms.
    low_data_rate_optimize: Optional[bool] = None

    def __post_init__(self) -> None:
        # Validation défensive côté Python : rejet précoce, message clair.
        if not 7 <= self.spreading_factor <= 12:
            raise ValueError("spreading_factor doit être compris entre 7 et 12")
        if self.bandwidth_hz not in _VALID_BW_HZ:
            raise ValueError("bandwidth_hz doit valoir 125000, 250000 ou 500000")
        if not 1 <= self.coding_rate <= 4:
            raise ValueError("coding_rate doit être compris entre 1 et 4 (4/5 à 4/8)")
        if not 6 <= self.preamble_symbols <= 65_535:
            raise ValueError("preamble_symbols doit être compris entre 6 et 65535")

    @property
    def ldro_effective(self) -> bool:
        """Optimisation bas débit réellement appliquée (Tsym > 16 ms => obligatoire)."""
        if self.low_data_rate_optimize is not None:
            return bool(self.low_data_rate_optimize)
        return (2 ** self.spreading_factor) / self.bandwidth_hz > 0.016

    def _to_c(self) -> _CRadioConfig:
        return _CRadioConfig(
            spreading_factor=self.spreading_factor,
            bandwidth_hz=self.bandwidth_hz,
            coding_rate=self.coding_rate,
            preamble_symbols=self.preamble_symbols,
            crc_on=int(self.crc_on),
            explicit_header=int(self.explicit_header),
            low_data_rate_optimize=int(self.ldro_effective),
        )


from lsim._native import LIB as _LIB, _CRadioConfig  # noqa: E402


def native_version() -> str:
    """Version du cœur natif, au format MAJEUR.MINEUR.CORRECTIF."""
    v = _LIB.lsim_version()
    return f"{(v >> 16) & 0xFF}.{(v >> 8) & 0xFF}.{v & 0xFF}"


def time_on_air_ns(config: RadioConfig, payload_bytes: int) -> int:
    """Temps d'antenne en nanosecondes (entier exact, formule AN1200.13)."""
    if not 0 <= payload_bytes <= 255:
        raise ValueError("payload_bytes doit être compris entre 0 et 255")
    out = ctypes.c_int64(0)
    status = _LIB.lsim_time_on_air_ns(
        ctypes.byref(config._to_c()), payload_bytes, ctypes.byref(out)
    )
    if status != 0:
        raise StatusError(status)
    return out.value
