"""Modèle de sensibilité absolue de passerelle `sensibilite-par-sf-v2` (ABI v2).

Seuils publiés en dBm, indexés par bande et SF. Le calcul n'utilise ni la référence SX1276 ni
un décalage relatif : une paire SF/bande absente est refusée, jamais déduite. Le modèle est
passerelle unique seulement. Il ne s'applique qu'à la configuration qui le sélectionne
explicitement ; sans lui, le chemin ABI v1 reste utilisé.
"""

from __future__ import annotations

from dataclasses import dataclass

from lsim._native import _CGatewayV2

MODEL_ID = "sensibilite-par-sf-v2"
MODEL_CODE = 1  # valeur de `sensitivity_model` dans lsim_gateway_v2
BANDWIDTHS_HZ = (125_000, 250_000, 500_000)  # indices 0, 1, 2 dans la table C
SF_MIN, SF_MAX = 5, 12
DBM_MIN, DBM_MAX = -160.0, -60.0
# SF5 (DR13) : seule région où l'usage est documenté (RP002-1.0.5, EU868).
SF5_REGION = "EU868"


class SensitivityError(ValueError):
    """Entrée absente, invalide ou incompatible avec le modèle de sensibilité."""


@dataclass(frozen=True)
class AbsoluteSensitivity:
    """Points publiés : tuples (bande en Hz, SF, dBm). Aucune valeur par défaut."""

    points: tuple[tuple[int, int, float], ...]
    source: str = ""
    conditions: str = ""

    def __post_init__(self) -> None:
        seen: set[tuple[int, int]] = set()
        for bw, sf, dbm in self.points:
            if bw not in BANDWIDTHS_HZ:
                raise SensitivityError(f"{MODEL_ID} : bande {bw} Hz non supportée")
            if sf == 6:
                raise SensitivityError(f"{MODEL_ID} : SF6 non modélisé (en-tête implicite seulement)")
            if not SF_MIN <= sf <= SF_MAX:
                raise SensitivityError(f"{MODEL_ID} : SF{sf} hors de {SF_MIN}..{SF_MAX}")
            if not DBM_MIN <= dbm <= DBM_MAX:
                raise SensitivityError(f"{MODEL_ID} : {dbm} dBm hors de [{DBM_MIN}, {DBM_MAX}]")
            if (bw, sf) in seen:
                raise SensitivityError(f"{MODEL_ID} : point SF{sf}/{bw} Hz en double")
            seen.add((bw, sf))

    def lookup(self, sf: int, bandwidth_hz: int) -> float:
        """Seuil publié pour cette paire ; SensitivityError si elle est absente."""
        for bw, s, dbm in self.points:
            if bw == bandwidth_hz and s == sf:
                return dbm
        raise SensitivityError(
            f"sensibilité absente pour SF{sf}/{bandwidth_hz // 1000} kHz dans le modèle {MODEL_ID}")

    def to_c(self, gateway) -> _CGatewayV2:
        """Structure `lsim_gateway_v2`. Refuse un décalage non nul : pas de conversion implicite."""
        if gateway.rx_sensitivity_offset_db != 0.0:
            raise SensitivityError(f"{MODEL_ID} : décalage non nul refusé (pas de conversion implicite)")
        c = _CGatewayV2()
        c.base.x_m = gateway.x_m
        c.base.y_m = gateway.y_m
        c.base.antenna_gain_dbi = gateway.antenna_gain_dbi
        c.base.rx_sensitivity_offset_db = 0.0
        c.sensitivity_model = MODEL_CODE
        present = 0
        for bw, sf, dbm in self.points:
            b = BANDWIDTHS_HZ.index(bw)
            present |= 1 << (b * 8 + (sf - SF_MIN))
            c.sensitivity_dbm[b][sf - SF_MIN] = dbm
        c.present = present
        return c


# Catalogue de profils de sensibilité absolue (valeurs publiées, indicatives).
# SF6 volontairement absent : DR12 utilise la référence SX1276 (non absolue).
SX1303_DATASHEET = AbsoluteSensitivity(
    points=((125_000, 5, -121.0), (125_000, 7, -127.0), (125_000, 8, -129.0),
            (125_000, 9, -132.5), (125_000, 10, -135.5), (125_000, 11, -138.0),
            (125_000, 12, -141.0)),
    source="Semtech SX1303 datasheet (SX1303_W_APP, V1.2), p. 14-15 : sensibilités à 125 kHz",
    conditions=("PER 10 %, paquets de 12 octets, front-end SX1250, LNA 18 dB, NF 1,5 dB, "
                "conditions nominales ; valeurs indicatives, non normatives LoRaWAN"),
)
CATALOG: dict[str, AbsoluteSensitivity] = {"sx1303-datasheet": SX1303_DATASHEET}


def refuse_absolute(gateway, path: str) -> None:
    """Refus explicite : le chemin `path` n'utilise pas la sensibilité absolue."""
    if getattr(gateway, "absolute_sensitivity", None) is not None:
        raise SensitivityError(
            f"{MODEL_ID} : non supporté par {path} (trace v2 et boucle fermée seulement)")
