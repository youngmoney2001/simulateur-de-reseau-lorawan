"""Plan US902-928 (US915), LoRaWAN Regional Parameters RP002.

Canaux montants (indices utilisés comme TxCh du MIC 1.1) :
- 0 à 63 : LoRa 125 kHz, 902,3 + 0,2 × i MHz, DR0 à DR3 ;
- 64 à 71 : LoRa 500 kHz, 903,0 + 1,6 × (i − 64) MHz, DR4.
Canaux descendants : 923,3 + 0,6 × k MHz (k = 0 à 7), LoRa 500 kHz, DR8 à DR13.

Débits montants (TTN US902-928, RP002) : DR0 SF10/125, DR1 SF9/125, DR2 SF8/125, DR3 SF7/125,
DR4 SF8/500. Débits descendants DR8 à DR13 = SF12 à SF7 / 500 kHz.

RX1 (RP002, tableau RX1DROffset et « RX1 Channel Number = Transmit Channel Number modulo 8 ») :
fréquence 923,3 + 0,6 × (canal mod 8) MHz ; débit RX1 avec RX1DROffset 0 : DR0→DR10, DR1→DR11,
DR2→DR12, DR3→DR13, DR4→DR13. RX2 par défaut : 923,3 MHz / DR8 (DLSettings).

Charges N (sans FOpts, compatibles répéteur, TTN US902-928) : DR0 11, DR1 53, DR2 125, DR3 222,
DR4 222, DR8 53, DR9 129, DR10 à DR13 222. La file est bornée par la plus petite N des fenêtres
RX1 atteignables (DR10 à DR13) : 222 octets.

Non implémenté : sous-bandes choisies par le masque de canaux (LinkADRReq), LR-FHSS (DR5, DR6).
Le dispositif rejoint sur les 72 canaux par défaut sans CFList : c'est la règle de ce serveur.
"""

from lsim.plan import Plan, register

_UP_125_HZ = tuple(902_300_000 + 200_000 * i for i in range(64))
_UP_500_HZ = tuple(903_000_000 + 1_600_000 * i for i in range(8))
_UPLINK_HZ = _UP_125_HZ + _UP_500_HZ


def _rx1_hz(tx_ch: int) -> int:
    return 923_300_000 + 600_000 * (tx_ch % 8)


US915 = register(Plan(
    name="US915",
    uplink_datr={
        "SF10BW125": 0, "SF9BW125": 1, "SF8BW125": 2, "SF7BW125": 3, "SF8BW500": 4,
    },
    uplink_channels_hz=_UPLINK_HZ,
    downlink_datr={
        8: "SF12BW500", 9: "SF11BW500", 10: "SF10BW500",
        11: "SF9BW500", 12: "SF8BW500", 13: "SF7BW500",
    },
    rx1_dr={0: 10, 1: 11, 2: 12, 3: 13, 4: 13},
    rx1_channel_hz=_rx1_hz,
    max_frm_payload={0: 11, 1: 53, 2: 125, 3: 222, 4: 222,
                     8: 53, 9: 129, 10: 222, 11: 222, 12: 222, 13: 222},
    dl_settings=0x80 | 8,                                # OptNeg, RX2 DR8
))
