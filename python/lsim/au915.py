"""Plan AU915-928 (Australie, Nouvelle-Zélande et pays ITU-R 2 à bande 915-928 MHz), RP002.

Canaux montants (indices utilisés comme TxCh du MIC 1.1) :
- 0 à 63 : LoRa 125 kHz, 915,2 + 0,2 × i MHz, DR0 à DR5 ;
- 64 à 71 : LoRa 500 kHz, 915,9 + 1,6 × (i − 64) MHz, DR6 (SF8 / 500 kHz).
Canaux descendants : 923,3 + 0,6 × k MHz (k = 0 à 7), LoRa 500 kHz, DR8 à DR13.

Débits montants : DR0 SF12/125, DR1 SF11/125, DR2 SF10/125, DR3 SF9/125, DR4 SF8/125,
DR5 SF7/125, DR6 SF8/500. Débits descendants : DR8 SF12/500 … DR13 SF7/500.

RX1 (RP002-1.0.3, tableau AU915 : RX1DROffset 0) : débit DR0→DR10, DR1→DR11, DR2→DR12, DR3→DR13,
DR4→DR13, DR5→DR10, DR6→DR11 ; fréquence 923,3 + 0,6 × (canal mod 8) MHz. RX2 par défaut :
923,3 MHz / DR8 (DLSettings).

Charges N (RP002-1.0.2, tableau AU915 « maximum payload size », M − 8 sans FOpts) : DR0 à DR2 51,
DR3 115, DR4 à DR6 222, DR8 33, DR9 109, DR10 à DR13 222. Ces valeurs sont celles de la table
« not repeater compatible » du tableau AU ; la file est bornée par la plus petite N des
fenêtres RX1 atteignables (DR10 à DR13) : 222 octets.

Non implémenté : sous-bandes choisies par le masque de canaux (LinkADRReq), comme pour US915.
Le dispositif rejoint sur les 72 canaux par défaut, sans CFList.
"""

from lsim.plan import Plan, register

_UP_125_HZ = tuple(915_200_000 + 200_000 * i for i in range(64))
_UP_500_HZ = tuple(915_900_000 + 1_600_000 * i for i in range(8))


def _rx1_hz(tx_ch: int) -> int:
    return 923_300_000 + 600_000 * (tx_ch % 8)


AU915 = register(Plan(
    name="AU915",
    uplink_datr={
        "SF12BW125": 0, "SF11BW125": 1, "SF10BW125": 2, "SF9BW125": 3,
        "SF8BW125": 4, "SF7BW125": 5, "SF8BW500": 6,
    },
    uplink_channels_hz=_UP_125_HZ + _UP_500_HZ,
    downlink_datr={
        8: "SF12BW500", 9: "SF11BW500", 10: "SF10BW500",
        11: "SF9BW500", 12: "SF8BW500", 13: "SF7BW500",
    },
    rx1_dr={0: 10, 1: 11, 2: 12, 3: 13, 4: 13, 5: 10, 6: 11},
    rx1_channel_hz=_rx1_hz,
    max_frm_payload={0: 51, 1: 51, 2: 51, 3: 115, 4: 222, 5: 222, 6: 222,
                     8: 33, 9: 109, 10: 222, 11: 222, 12: 222, 13: 222},
    dl_settings=0x80 | 8,                               # OptNeg, RX2 DR8
))
