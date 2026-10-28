"""Plan EU863-870 (EU868) pour la couche données du serveur, source RP002-1.0.2.

- Canaux par défaut (§2.4.2, tableau 6) : 868,10 / 868,30 / 868,50 MHz, indices 0, 1, 2.
  Pas de CFList dans les join-accept émis : seuls ces trois canaux sont utilisés.
- Débits (§2.4.3, tableau 8) : DR0 à DR5 = SF12 à SF7 / 125 kHz, DR6 = SF7 / 250 kHz.
  DR7 (FSK) et DR8 à DR15 ne sont pas supportés ici.
- Charge utile applicative sans FOpts (§2.4.6, tableau 12, valeurs « repeater compatible »,
  les plus restrictives) : N = 51, 51, 51, 115, 222, 222, 222 pour DR0 à DR6.
- RX1 (§2.4.7) : même canal que l'émission, débit = débit montant (RX1DROffset 0).
- RECEIVE_DELAY1 = 1 s (§2.3).
"""

from __future__ import annotations

RECEIVE_DELAY1_US = 1_000_000

_DR_BY_DATR = {
    "SF12BW125": 0, "SF11BW125": 1, "SF10BW125": 2, "SF9BW125": 3,
    "SF8BW125": 4, "SF7BW125": 5, "SF7BW250": 6,
}
_MAX_FRM_PAYLOAD_N = (51, 51, 51, 115, 222, 222, 222)
_DEFAULT_CHANNELS_HZ = (868_100_000, 868_300_000, 868_500_000)
DEFAULT_CHANNEL_TOLERANCE_HZ = 1_000   # la fréquence rapportée par la passerelle est en Hz précis


def data_rate_index(datr: str) -> int:
    """Indice DR d'une chaîne « SF7BW125 ». Lève ValueError si hors plan."""
    try:
        return _DR_BY_DATR[datr]
    except KeyError:
        raise ValueError(f"débit non supporté par le plan EU868 : {datr!r}") from None


def channel_index(freq_mhz: float) -> int:
    """Indice du canal par défaut correspondant à la fréquence (MHz) ; ValueError sinon."""
    hz = round(freq_mhz * 1_000_000)
    for index, centre in enumerate(_DEFAULT_CHANNELS_HZ):
        if abs(hz - centre) <= DEFAULT_CHANNEL_TOLERANCE_HZ:
            return index
    raise ValueError(f"canal hors plan EU868 par défaut : {freq_mhz} MHz")


def max_frm_payload(dr: int) -> int:
    """Taille maximale de FRMPayload sans FOpts pour le débit DR (0 à 6)."""
    if not 0 <= dr < len(_MAX_FRM_PAYLOAD_N):
        raise ValueError(f"DR hors plan EU868 : {dr}")
    return _MAX_FRM_PAYLOAD_N[dr]


# Taille de file applicative : la plus restrictive des DR 0 à 6 (charge limitée à DR0).
MAX_QUEUED_PAYLOAD = min(_MAX_FRM_PAYLOAD_N)
