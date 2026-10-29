"""Catalogue des passerelles : capacités radio publiées par les constructeurs.

Règles :
- une valeur n'entre dans le catalogue que si elle est publiée dans une fiche citée (`source`) ;
- ce qui n'est pas publié reste à `None` ou vide, avec une note ; jamais de valeur devinée ;
- un profil sans radio mesh documentée ne peut pas relayer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class GatewayProfile:
    key: str                       # identifiant stable (minuscules, sans espace)
    vendor: str
    model: str
    source: str                    # fiche constructeur citée
    access_bands: tuple[str, ...]  # régions LoRaWAN de l'accès capteurs
    max_channels: int              # canaux de réception (accès capteurs)
    rx_sensitivity_min_dbm: Optional[float]  # valeur « min » publiée
    tx_power_max_dbm: Optional[float]
    mesh_bands: tuple[str, ...] = ()         # bandes du lien mesh documentées (vide : aucune)
    notes: tuple[str, ...] = field(default=())


CATALOG: tuple[GatewayProfile, ...] = (
    GatewayProfile(
        key="rak7249",
        vendor="RAKwireless",
        model="RAK7249 WisGate Edge Max",
        source="https://docs.rakwireless.com/product-categories/wisgate/rak7249/datasheet/",
        access_bands=("EU433", "CN470", "EU868", "US915", "AS923", "AU915", "KR920", "IN865"),
        max_channels=16,  # fiche : jusqu'à 16 canaux (2 concentrateurs SX1301)
        rx_sensitivity_min_dbm=-139.0,  # fiche officielle ; le manuel V1.3 indique -142 dBm
        tx_power_max_dbm=27.0,
        mesh_bands=(),
        notes=(
            "Radio LoRa sous-GHz uniquement (le 2,4 GHz de la fiche est du Wi-Fi).",
            "Radio mesh non documentée : bandes et usage du second concentrateur non précisés. "
            "Pas de relais tant que le constructeur ne le confirme pas.",
            "Sensibilité : -139 dBm (fiche officielle) contre -142 dBm (manuel V1.3). Valeur "
            "retenue : la fiche officielle, la plus récente.",
        ),
    ),
)


def get_profile(key: str) -> GatewayProfile:
    for p in CATALOG:
        if p.key == key:
            return p
    raise KeyError(f"passerelle inconnue : {key!r}")


def can_relay(profile: GatewayProfile) -> bool:
    """Vrai si le profil documente une radio mesh : condition nécessaire pour relayer."""
    return len(profile.mesh_bands) > 0
