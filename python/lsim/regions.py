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
class DiscreteChannel:
    """Canal discret (fréquence centrale, largeur, plage de DR, PIRE optionnelle)."""

    freq_hz: int
    bw_hz: int                       # 125000, 250000 ou 500000
    dr_min: int
    dr_max: int
    uplink: bool
    max_eirp_dbm: Optional[float] = None   # None = non documentée dans la source
    is_default: bool = False               # canal obligatoire (join / diffusion)

    def __post_init__(self) -> None:
        if not (isinstance(self.freq_hz, int) and self.freq_hz > 0):
            raise ValueError("fréquence de canal : entier positif en Hz requis")
        if self.bw_hz not in (125_000, 250_000, 500_000):
            raise ValueError(f"largeur de canal non LoRa : {self.bw_hz}")
        if not (isinstance(self.dr_min, int) and isinstance(self.dr_max, int)
                and 0 <= self.dr_min <= self.dr_max <= 15):
            raise ValueError(f"plage de DR invalide : {self.dr_min}..{self.dr_max}")
        if self.max_eirp_dbm is not None and not math.isfinite(self.max_eirp_dbm):
            raise ValueError("PIRE de canal non finie")


POWER_BASES = ("eirp", "conducted", None)


@dataclass(frozen=True)
class RegionProfile:
    """Profil régional. `source` est obligatoire : référence officielle vérifiée.

    `sub_bands` : règles de duty cycle par plage de fréquences (ETSI, etc.).
    `channels`  : plan de canaux discrets (LoRaWAN Regional Parameters).
    `power_basis` : base de la PIRE des canaux : "eirp", "conducted" ou None (inconnue).
    `dwell_time_ms` : temps d'émission maximal par trame (FCC 400 ms), sinon None.
    `recommended_interval_s` : intervalle recommandé entre émissions (AU915, UplinkDwellTime=1).
    """

    code: str
    source: str
    sub_bands: tuple[SubBand, ...] = field(default_factory=tuple)
    channels: tuple[DiscreteChannel, ...] = field(default_factory=tuple)
    power_basis: Optional[str] = None
    dwell_time_ms: Optional[int] = None
    recommended_interval_s: Optional[float] = None

    def __post_init__(self) -> None:
        if not self.code:
            raise ValueError("code de région vide")
        if not self.source.strip():
            raise ValueError(f"région {self.code} : source officielle requise")
        if not self.sub_bands and not self.channels:
            raise ValueError(f"région {self.code} : au moins une sous-bande ou un canal")
        if self.power_basis not in POWER_BASES:
            raise ValueError(f"région {self.code} : base de puissance inconnue")
        if self.dwell_time_ms is not None and not (isinstance(self.dwell_time_ms, int)
                                                   and self.dwell_time_ms > 0):
            raise ValueError(f"région {self.code} : dwell time invalide")

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

    def duty_cycle_limit(self, freq_hz: int, eirp_dbm: float) -> Optional[float]:
        """Duty cycle réglementaire, ou None si le profil n'en définit pas (sous-bandes absentes)."""
        if not self.sub_bands:
            return None
        return self.duty_cycle_for(freq_hz, eirp_dbm)

    def channel_at(self, freq_hz: int, uplink: bool = True) -> Optional[DiscreteChannel]:
        """Canal discret à cette fréquence exacte, ou None."""
        for ch in self.channels:
            if ch.freq_hz == freq_hz and ch.uplink == uplink:
                return ch
        return None


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

# ------------------------------------------- Plans de canaux (RP002-1.0.0)
# Toutes les valeurs ci-dessous viennent de LoRaWAN Regional Parameters RP002-1.0.0
# (LoRa Alliance, 1er novembre 2019). Quand la source ne donne pas une PIRE, elle
# reste None : aucune valeur n'est inventée.

RP002 = "LoRaWAN Regional Parameters RP002-1.0.0 (2019)"


def _ch(freq, bw, dr_min, dr_max, *, uplink=True, eirp=None, default=False):
    return DiscreteChannel(freq, bw, dr_min, dr_max, uplink, eirp, default)


# US902-928 (§2.5.2, §2.5.3) : 64 × 125 kHz (DR0–3), 8 × 500 kHz (DR4), 8 descendants (DR8–13).
# PIRE documentée en puissance conduite : 30 dBm en mode FHSS (125 kHz, ≥ 50 canaux),
# 26 dBm en mode DTS (500 kHz). Dwell time 400 ms (FCC).
US915_CHANNELS = (
    tuple(_ch(902_300_000 + 200_000 * k, 125_000, 0, 3, eirp=30.0) for k in range(64))
    + tuple(_ch(903_000_000 + 1_600_000 * k, 500_000, 4, 4, eirp=26.0) for k in range(8))
    + tuple(_ch(923_300_000 + 600_000 * k, 500_000, 8, 13, uplink=False) for k in range(8))
)
US915 = RegionProfile(
    code="US915", source=RP002 + " §2.5.2–2.5.3 ; FCC 47 CFR 15.247 (govinfo, édition 2013 : FHSS ≥ 50 canaux 1 W, numérique ≥ 500 kHz, dwell 0,4 s)", channels=US915_CHANNELS,
    power_basis="conducted", dwell_time_ms=400,
)

# AU915-928 (§2.8.2, §2.8.3) : 64 × 125 kHz (DR0–5), 8 × 500 kHz (DR6), 8 descendants.
# PIRE maximale documentée : 30 dBm EIRP. UplinkDwellTime = 1 : 20 s recommandées.
AU915_CHANNELS = (
    tuple(_ch(915_200_000 + 200_000 * k, 125_000, 0, 5, eirp=30.0) for k in range(64))
    + tuple(_ch(915_900_000 + 1_600_000 * k, 500_000, 6, 6, eirp=30.0) for k in range(8))
    + tuple(_ch(923_300_000 + 600_000 * k, 500_000, 8, 13, uplink=False) for k in range(8))
)
AU915 = RegionProfile(
    code="AU915",
    source=(RP002 + " §2.8.2–2.8.3 ; ACMA, Radiocommunications (LIPD) Class Licence 2015, compilation n° 10 "
            "(F2023C00524), item 58 : modulation numérique 915–928 MHz, 1 W EIRP, PSD ≤ 25 mW par 3 kHz ; "
            "item 54 : FH, ≥ 20 fréquences"),
    channels=AU915_CHANNELS, power_basis="eirp", recommended_interval_s=20.0,
)

# AS923 (§2.10.2, §2.10.3) : canaux par défaut 923,2 et 923,4 MHz (DR0–5, duty cycle < 1 %).
# PIRE par défaut 16 dBm EIRP ; limites par pays et LBT (Japon, ARIB STD-T108) hors RP002.
AS923 = RegionProfile(
    code="AS923",
    source=RP002 + " §2.10.2–2.10.3 (canaux par défaut ; limites par pays dans les textes locaux)",
    channels=(
        _ch(923_200_000, 125_000, 0, 5, eirp=None, default=True),
        _ch(923_400_000, 125_000, 0, 5, eirp=None, default=True),
    ),
    power_basis=None,
)

# KR920-923 (§2.11.2, §2.11.3) : 13 canaux 920,9 à 923,3 MHz (DR0–5).
# PIRE end-device : 10 dBm (920,9–921,9 MHz) et 14 dBm (922,1–923,3 MHz). LBT AFA imposé.
KR920_CHANNELS = tuple(
    _ch(920_900_000 + 200_000 * k, 125_000, 0, 5,
        eirp=(10.0 if 920_900_000 + 200_000 * k <= 921_900_000 else 14.0),
        default=(922_100_000 <= 920_900_000 + 200_000 * k <= 922_500_000))
    for k in range(13)
)
KR920 = RegionProfile(
    code="KR920",
    source=RP002 + " §2.11.2 (tableau 68 : PIRE end-device) et §2.11.3 (canaux par défaut 922,1/922,3/922,5 MHz)",
    channels=KR920_CHANNELS, power_basis="eirp",
)

# IN865-867 (§2.12.2, §2.12.3) : canaux par défaut, aucune limite de dwell time ni de duty cycle.
# PIRE : GSR 564(E) du 30 juillet 2008 (DoT) : 1 W émetteur, 4 W ERP, carrier 200 kHz.
# La limite ERP 4 W est convertie en EIRP (EIRP = ERP + 2,15 dB). La limite 1 W conduite
# ne peut pas être vérifiée sans gain d'antenne : elle reste à respecter côté matériel.
IN865_MAX_EIRP_DBM = mw_to_dbm(4000.0) + ANTENNA_GAIN_DBI_TO_DBD   # ≈ 38,17 dBm
IN865 = RegionProfile(
    code="IN865",
    source=(RP002 + " §2.12.2–2.12.3 (canaux par défaut) ; GSR 564(E) du 30/07/2008 du DoT Inde "
            "(extrait de la gazette officielle : 1 W émetteur, 4 W ERP, 200 kHz)"),
    channels=(
        _ch(865_062_500, 125_000, 0, 5, eirp=IN865_MAX_EIRP_DBM, default=True),
        _ch(865_402_500, 125_000, 0, 5, eirp=IN865_MAX_EIRP_DBM, default=True),
        _ch(865_985_000, 125_000, 0, 5, eirp=IN865_MAX_EIRP_DBM, default=True),
    ),
    power_basis="eirp",
)

# RU864-870 (§2.13.2, §2.13.3) : canaux par défaut 868,9 et 869,1 MHz (DR0–5, duty cycle < 1 %).
# Sous-bandes et PIRE par le texte russe : à compléter.
RU864 = RegionProfile(
    code="RU864",
    source=RP002 + " §2.13.2–2.13.3 (canaux par défaut ; sous-bandes et PIRE à compléter, texte russe)",
    channels=(
        _ch(868_900_000, 125_000, 0, 5, eirp=None, default=True),
        _ch(869_100_000, 125_000, 0, 5, eirp=None, default=True),
    ),
    power_basis=None,
)

# Profils livrés. Toute région ajoutée doit passer par load_profile ou RegionProfile avec sa source.
PROFILES: dict[str, RegionProfile] = {
    "EU868": EU868,
    "US915": US915,
    "AU915": AU915,
    "AS923": AS923,
    "KR920": KR920,
    "IN865": IN865,
    "RU864": RU864,
}
