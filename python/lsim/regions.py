"""Cadre des profils régionaux (data-driven) : sous-bandes, duty cycle, PIRE.

Ce module ne contient AUCUNE valeur réglementaire. Chaque profil doit citer
sa source officielle (document, version, clause) et ne peut être chargé que
si cette source est renseignée. Les valeurs seront ajoutées une fois la
source vérifiée (voir docs/ROADMAP.md, Jalon 1 : profils régionaux).

Règles :
  * sous-bandes disjointes, triées, fréquences en Hz entiers ;
  * duty cycle dans ]0, 1] ; PIRE maximal en dBm, fini ;
  * une bande de fréquence n'appartient qu'à une sous-bande.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Optional


@dataclass(frozen=True)
class SubBand:
    name: str
    f_min_hz: int
    f_max_hz: int
    duty_cycle: float          # fraction de temps d'émission autorisée, ]0, 1]
    max_erp_dbm: float         # puissance rayonnée maximale (dBm)

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("nom de sous-bande vide")
        if not (isinstance(self.f_min_hz, int) and isinstance(self.f_max_hz, int)):
            raise ValueError("les fréquences doivent être des entiers en Hz")
        if not 0 < self.f_min_hz < self.f_max_hz:
            raise ValueError(f"sous-bande {self.name} : bornes invalides")
        if not 0.0 < self.duty_cycle <= 1.0:
            raise ValueError(f"sous-bande {self.name} : duty_cycle hors ]0, 1]")
        if not math.isfinite(self.max_erp_dbm):
            raise ValueError(f"sous-bande {self.name} : PIRE non fini")

    def contains(self, freq_hz: int) -> bool:
        return self.f_min_hz <= freq_hz <= self.f_max_hz


@dataclass(frozen=True)
class RegionProfile:
    """Profil régional. `source` est obligatoire : référence officielle vérifiée."""

    code: str
    source: str                      # ex. « LoRaWAN Regional Parameters RP002-1.0.x, §… »
    sub_bands: tuple[SubBand, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.code:
            raise ValueError("code de région vide")
        if not self.source.strip():
            raise ValueError(f"région {self.code} : source officielle requise")
        if not self.sub_bands:
            raise ValueError(f"région {self.code} : au moins une sous-bande")
        ordered = sorted(self.sub_bands, key=lambda b: b.f_min_hz)
        for a, b in zip(ordered, ordered[1:]):
            if b.f_min_hz <= a.f_max_hz:
                raise ValueError(f"région {self.code} : sous-bandes {a.name} et {b.name} se chevauchent")

    def band_for(self, freq_hz: int) -> Optional[SubBand]:
        """Sous-bande contenant la fréquence, ou None hors plan."""
        for band in self.sub_bands:
            if band.contains(freq_hz):
                return band
        return None


def load_profile(code: str, source: Optional[str], bands: Iterable[SubBand]) -> RegionProfile:
    """Construit un profil. Refuse explicitement un profil sans source."""
    if not source or not source.strip():
        raise ValueError(f"région {code} : aucune source officielle, profil refusé")
    return RegionProfile(code=code, source=source, sub_bands=tuple(bands))
