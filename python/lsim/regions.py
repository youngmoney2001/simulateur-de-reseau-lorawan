"""Profils régionaux (data-driven) : sous-bandes, duty cycle, PIRE.

Chaque profil cite sa source officielle. Un profil sans source est refusé.

Règle de sélection (conservatrice) :
  une sous-bande S s'applique à une émission si
    * la fréquence est dans [f_min, f_max] de S, et
    * la PIRE (ERP) de l'émission est inférieure ou égale à max_erp_dbm de S.
  Si plusieurs sous-bandes s'appliquent, c'est la plus restrictive
  (duty cycle minimal) qui fait foi. Les sous-bandes peuvent donc se recouvrir,
  comme dans ETSI EN 300 220-2 (O/P, RQ/QP).

Pour LoRaWAN, la PIRE (ERP) se déduit de la PIRE (EIRP) : ERP = EIRP - 2,15 dB
(RP002-1.0.0, §2.4.3, note 2).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Optional

ANTENNA_GAIN_DBI_TO_DBD = 2.15  # ERP = EIRP - 2,15 dB (demi-onde)


def mw_to_dbm(mw: float) -> float:
    return 10.0 * math.log10(mw)


def erp_from_eirp(eirp_dbm: float) -> float:
    return eirp_dbm - ANTENNA_GAIN_DBI_TO_DBD


@dataclass(frozen=True)
class SubBand:
    name: str
    f_min_hz: int
    f_max_hz: int
    duty_cycle: float          # fraction de temps d'émission autorisée, ]0, 1]
    max_erp_dbm: float         # PIRE maximale de la sous-bande (dBm)

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
            raise ValueError(f"sous-bande {self.name} : PIRE non finie")

    def applies(self, freq_hz: int, erp_dbm: float) -> bool:
        return self.f_min_hz <= freq_hz <= self.f_max_hz and erp_dbm <= self.max_erp_dbm + 1e-9


@dataclass(frozen=True)
class RegionProfile:
    """Profil régional. `source` est obligatoire : référence officielle vérifiée."""

    code: str
    source: str
    sub_bands: tuple[SubBand, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.code:
            raise ValueError("code de région vide")
        if not self.source.strip():
            raise ValueError(f"région {self.code} : source officielle requise")
        if not self.sub_bands:
            raise ValueError(f"région {self.code} : au moins une sous-bande")

    def applicable(self, freq_hz: int, erp_dbm: float) -> tuple[SubBand, ...]:
        return tuple(b for b in self.sub_bands if b.applies(freq_hz, erp_dbm))

    def band_for(self, freq_hz: int, erp_dbm: float) -> Optional[SubBand]:
        """Sous-bande la plus restrictive applicable, ou None si l'émission est hors plan."""
        bands = self.applicable(freq_hz, erp_dbm)
        if not bands:
            return None
        return min(bands, key=lambda b: b.duty_cycle)

    def duty_cycle_for(self, freq_hz: int, eirp_dbm: float) -> float:
        """Duty cycle maximal pour une émission de PIRE EIRP donnée. Lève si hors plan."""
        band = self.band_for(freq_hz, erp_from_eirp(eirp_dbm))
        if band is None:
            raise ValueError(f"{self.code} : {freq_hz} Hz à {eirp_dbm} dBm EIRP hors plan")
        return band.duty_cycle


def load_profile(code: str, source: Optional[str], bands: Iterable[SubBand]) -> RegionProfile:
    """Construit un profil. Refuse explicitement un profil sans source."""
    if not source or not source.strip():
        raise ValueError(f"région {code} : aucune source officielle, profil refusé")
    return RegionProfile(code=code, source=source, sub_bands=tuple(bands))


# ----------------------------------------------------------------- EU863-870

EU868_SOURCE = (
    "ETSI EN 300 220-2 V3.2.1 (2018-06), tableau des sous-bandes K à Q ; "
    "LoRaWAN Regional Parameters RP002-1.0.0 (2019), §2.4.2 (canaux par défaut), "
    "§2.4.3 (PIRE, ERP = EIRP - 2,15 dB) et §2.4.8 (RX2 869,525 MHz)"
)

# Valeurs transcrites du tableau ETSI EN 300 220-2 V3.2.1 (2018-06).
EU868 = load_profile("EU868", EU868_SOURCE, (
    SubBand("K", 863_000_000, 865_000_000, 0.001, mw_to_dbm(25.0)),
    SubBand("L", 865_000_000, 868_000_000, 0.01, mw_to_dbm(25.0)),
    SubBand("M", 868_000_000, 868_600_000, 0.01, mw_to_dbm(25.0)),
    SubBand("N", 868_700_000, 869_200_000, 0.001, mw_to_dbm(25.0)),
    SubBand("O", 869_400_000, 869_650_000, 0.001, mw_to_dbm(25.0)),
    SubBand("P", 869_400_000, 869_650_000, 0.10, mw_to_dbm(500.0)),
    SubBand("Q", 869_700_000, 870_000_000, 0.01, mw_to_dbm(25.0)),
    SubBand("QP", 869_700_000, 870_000_000, 1.0, mw_to_dbm(5.0)),
))

# Profils livrés. Toute région ajoutée doit passer par load_profile avec sa source.
PROFILES: dict[str, RegionProfile] = {"EU868": EU868}
