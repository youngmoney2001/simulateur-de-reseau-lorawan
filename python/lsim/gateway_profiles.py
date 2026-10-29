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
    source: str                    # fiche constructeur citée (URL ou document fourni)
    access_bands: tuple[str, ...]  # régions LoRaWAN de l'accès capteurs
    max_channels: Optional[int]    # canaux de réception ; None si non publié
    rx_sensitivity_min_dbm: Optional[float]  # sensibilité publiée (min ou typique : voir notes)
    tx_power_max_dbm: Optional[float]
    mesh_bands: tuple[str, ...] = ()         # bandes du lien mesh documentées (vide : aucune)
    # Hôte : porteur de modules, sans radio LoRa propre publiée. Un hôte ne peut pas être
    # utilisé comme passerelle radio : il faut un module dans ses emplacements.
    is_host: bool = False
    # Point de sensibilité publié (SF, bande en Hz) de `rx_sensitivity_min_dbm`. None : point non
    # publié, ou hors des bandes du moteur (125/250/500 kHz) : aucun décalage n'est appliqué.
    rx_sensitivity_point: Optional[tuple[int, int]] = None
    # Compatibilité logicielle validée (essai réel ou confirmation constructeur). False : provisoire.
    software_validated: bool = True
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
            "Point de sensibilité non publié : la fiche donne -139 dBm (min) sans spreading factor ni "
            "largeur de bande, donc aucun décalage n'est appliqué (0 dB, décision confirmée par l'auteur).",
        ),
    ),
    GatewayProfile(
        key="rak5148",
        vendor="RAKwireless",
        model="RAK5148 WisLink LPWAN 2.4 GHz Concentrator Module (RAK5148-211 / RAK5148-221)",
        source="Fiche technique RAK5148 (9 pages, fournie) ; one-pager RAK5148 (fourni)",
        access_bands=("ISM2400",),
        max_channels=None,              # la fiche ne publie pas de nombre de canaux d'accès
        rx_sensitivity_min_dbm=-132.0,  # typique, SF12 / 203 kHz (fiche)
        tx_power_max_dbm=27.0,          # 3+1 SX1280 : Tx max 27 dBm (fiche)
        mesh_bands=("ISM2400",),
        notes=(
            "Module mini-PCIe 2,4 GHz : 3 SX1280 en réception, 1 en émission (fiche).",
            "Alimentation 3,3 V (3,0 à 3,6 V) ; 810 mA max en émission, 179 mA en réception ; "
            "-40 à +85 °C ; ESD 1 kV ; interface USB.",
            "Modèles : RAK5148-211 (USB, reset MCU) et RAK5148-221 (USB, GPS ZOE-M8Q, reset MCU).",
            "Sensibilité fiche : -132 dBm (SF12 / 203 kHz) et -110 dBm (SF7 / 1625 kHz), valeurs "
            "typiques. La table basse consommation Semtech donne -106 dBm à SF7 / 1625 kHz : "
            "les simulations mesh gardent cette table, plus conservatrice (lsim.mesh).",
            "Nombre de canaux d'accès non publié : max_channels reste vide.",
            "Le guide mesh RAK utilise 2,4 GHz, BW 812 kHz, CR 4/8 : non modélisé ici, la "
            "configuration du moteur reste paramétrable.",
        ),
    ),
    GatewayProfile(
        key="rak5146-rak5148",
        vendor="RAKwireless",
        model="Passerelle relais RAK « Outdoor Gateway Mesh » : RAK5146 (accès sous-GHz) + RAK5148 (mesh 2,4 GHz)",
        source=(
            "Fiche RAK5146 (docs.rakwireless.com, wislink/rak5146/datasheet) ; fiche RAK5148 ; page "
            "produit « Outdoor Gateway Mesh with 2.4G Backhaul » (store.rakwireless.com)"
        ),
        access_bands=("EU433", "EU868", "RU864", "CN470", "US915", "AS923", "AU915", "KR920", "IN865"),
        max_channels=8,                 # page produit : « 8 channels subGHz LoRa concentrator (RAK5146) »
        rx_sensitivity_min_dbm=-139.0,  # RAK5146, accès : -139 dBm à SF12 / 125 kHz (fiche)
        rx_sensitivity_point=(12, 125_000),
        tx_power_max_dbm=27.0,          # RAK5146 : Tx jusqu'à 27 dBm (fiche)
        mesh_bands=("ISM2400",),        # RAK5148 : lien relais 2,4 GHz
        software_validated=False,       # provisoire : essai ChirpStack Gateway OS ou confirmation RAK requis
        notes=(
            "Hôte à deux concentrateurs : le RAK5146 reçoit les capteurs sous-GHz, le RAK5148 "
            "porte le lien mesh 2,4 GHz (page produit RAK, ChirpStack Gateway OS).",
            "Compatibilité logicielle À VALIDER : configuration matérielle documentée par RAK, "
            "mais pas le fonctionnement de chaque version logicielle. Essai requis : détection "
            "simultanée des deux concentrateurs, accès EU868 et backhaul mesh 2,4 GHz, relais de "
            "trames entre les deux radios, comportement après redémarrage et perte du lien mesh.",
            "Fidélité radio : la sensibilité publiée (RAK5146, -139 dBm, SF12 / 125 kHz) entre dans la "
            "réception montante des accès sous forme de décalage uniforme (modèle « decalage-uniforme-v1 », "
            "-3 dB). Hypothèse non calibrée sur le matériel : ni la descente ni le lien mesh n'en tiennent "
            "compte, et la puissance d'émission (27 dBm) ne sert qu'aux relais.",
            "Un relais RAK5148 seul ne reçoit pas les capteurs sous-GHz : la règle de scénario le refuse.",
        ),
    ),
    GatewayProfile(
        key="rak7391",
        vendor="RAKwireless",
        model="RAK7391 WisGate Connect (hôte Raspberry Pi CM4)",
        source="Brochure WisGate Connect (RAK7391), fichier fourni",
        access_bands=(),
        max_channels=None,
        rx_sensitivity_min_dbm=None,
        tx_power_max_dbm=None,
        mesh_bands=(),
        is_host=True,
        notes=(
            "Hôte : Raspberry Pi CM4 (BCM2711), 3 emplacements mini-PCIe, 1 M.2 B-key, "
            "2 WisBlock IO, alimentation 10 à 28 V DC, 170 × 170 mm (brochure).",
            "La brochure ne publie aucun paramètre radio du concentrateur : aucune sensibilité, "
            "aucune puissance, aucune bande. Le profil ne porte donc aucune valeur radio.",
            "Non simulable seul comme passerelle : déclarer le module installé (par exemple "
            "rak5148) dans un profil dédié dès que sa compatibilité est publiée.",
        ),
    ),
)


def get_profile(key: str) -> GatewayProfile:
    for p in CATALOG:
        if p.key == key:
            return p
    raise KeyError(f"passerelle inconnue : {key!r}")


# Hypothèse de modèle versionnée (voir CHANGELOG) : le décalage mesuré au seul point publié
# s'applique à tous les SF et bandes du moteur. Sans donnée par SF, c'est l'hypothèse la plus simple.
SENSITIVITY_MODEL = "decalage-uniforme-v1"


def rx_sensitivity_offset_db(profile: GatewayProfile) -> float:
    """Décalage (dB) du seuil montant de la passerelle : sensibilité publiée − sensibilité de référence
    du moteur au même point (SF, bande). 0.0 si le profil ne publie pas de point utilisable."""
    if profile.rx_sensitivity_min_dbm is None or profile.rx_sensitivity_point is None:
        return 0.0
    from lsim.radio import receiver_sensitivity_dbm
    sf, bw_hz = profile.rx_sensitivity_point
    return float(profile.rx_sensitivity_min_dbm) - receiver_sensitivity_dbm(sf, bw_hz)


def software_status(profile: GatewayProfile) -> str:
    """« validé » ou « à valider » : état de la compatibilité logicielle, distinct de la fidélité radio."""
    return "validé" if profile.software_validated else "à valider"


def can_relay(profile: GatewayProfile) -> bool:
    """Vrai si le profil documente une radio mesh : condition nécessaire pour relayer."""
    return len(profile.mesh_bands) > 0


def can_simulate_radio(profile: GatewayProfile) -> bool:
    """Vrai si le profil peut servir de passerelle radio (un hôte seul ne le peut pas)."""
    return not profile.is_host and len(profile.access_bands) > 0
