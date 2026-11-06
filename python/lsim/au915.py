"""Plan AU915-928 (Australie, Nouvelle-Zélande et pays ITU-R 2 à bande 915-928 MHz), RP002.

Canaux montants (indices utilisés comme TxCh du MIC 1.1) :
- 0 à 63 : LoRa 125 kHz, 915,2 + 0,2 × i MHz, DR0 à DR5 ;
- 64 à 71 : LoRa 500 kHz, 915,9 + 1,6 × (i − 64) MHz, DR6 (SF8 / 500 kHz).
Canaux descendants : 923,3 + 0,6 × k MHz (k = 0 à 7), LoRa 500 kHz, DR8 à DR13.

Débits montants : DR0 SF12/125, DR1 SF11/125, DR2 SF10/125, DR3 SF9/125, DR4 SF8/125,
DR5 SF7/125, DR6 SF8/500. Débits descendants : DR8 SF12/500 … DR13 SF7/500.

RX1 (RP002-1.0.5, §3.8.7 « AU915-928 Receive Windows », RX1DROffset 0) : DR0→DR8, DR1→DR9,
DR2→DR10, DR3→DR11, DR4→DR12, DR5→DR13, DR6→DR13 ; fréquence 923,3 + 0,6 × (canal mod 8) MHz.
À offset 0 la descente conserve le facteur d'étalement de la montante en le transportant sur
500 kHz. RX2 par défaut : 923,3 MHz / DR8 (DLSettings).

Charges N (RP002-1.0.5, table 44 « AU915-928 maximum payload size », colonnes **compatibles
avec les répéteurs** ; N = M − 8, sans FOpts) : DR0 à DR2 51, DR3 115, DR4 à DR6 222,
DR8 53 (M = 61), DR9 129 (M = 137), DR10 à DR13 222. La file est bornée par la plus petite N
des fenêtres RX1 atteignables — soit DR8, depuis que DR8 est atteignable : 53 octets.

Sous-bandes et règle LinkADRReq : `lsim.channel_mask` (comme US915), émission par `lsim.serve`. Aucun débit LR-FHSS dans ce plan (voir docs/USAGE.md 5quater).
Le dispositif rejoint sur les 72 canaux par défaut, sans CFList.

Conformité régionale
--------------------
Référence normative ...... RP002-1.0.5 (LoRa Alliance, octobre 2025)
Table du mappage RX1 ..... §3.8.7 « AU915-928 Receive Windows » (page 62)
                           — NON LUE DIRECTEMENT : voir L1
Source de la table RX1 ... v1.0.3revA Table 40 (DR0–DR4) + v1.1rA Table 39 (DR5–DR6)
Plage d'offsets .......... [0:5] — RP002-1.0.5 Table 4 (lue)
Table des charges N ...... RP002-1.0.5 table 44 — NON LUE DIRECTEMENT : voir L1
Corroborations charges ... v1.0 (2016) T.31, v1.0.2 (2017) T.37, v1.1rB (2017) T.38-39
Date de vérification ..... 2026-11-05
Vérificateur ............. agent Arena, lot I6-b1

Statut de vérification
----------------------
Colonne offset 0 ......... NORMATIF CONFIRMÉ
Offsets 1 à 5 ............ NORMATIF CONFIRMÉ (corroborations antérieures à 1.0.5 ; L1)
Plage [0:5] .............. NORMATIF CONFIRMÉ (RP002-1.0.5 Table 4, lue)
Charges N, DR8 et DR9 .... NORMATIF CONFIRMÉ (corroborations interversions ; L1 sur 1.0.5)
Charges N, DR10 à DR13 ... HYPOTHÈSE NON VÉRIFIÉE — écart de 20 octets, hors lot I6-b1
DR7, DR14, SF5, SF6 ...... NON REPRÉSENTÉ

L1 — réserve normative
----------------------
Ni la table 7 × 6 du §3.8.7 ni la table 44 de RP002-1.0.5 n'ont pu être lues directement
(l'extraction du PDF plafonne vers la page 31 sur 115). Les valeurs retenues le sont sur la
foi de publications LoRa Alliance antérieures, de leur stabilité interversions et de leur
concordance avec LoRaMac-node v4.7.1, qui n'est pas une source normative. Voir
`docs/I6_B1_REGIONS.md` §5.2 et §12.10.2.
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
    rx1_dr={0: 8, 1: 9, 2: 10, 3: 11, 4: 12, 5: 13, 6: 13},
    rx1_channel_hz=_rx1_hz,
    max_frm_payload={0: 51, 1: 51, 2: 51, 3: 115, 4: 222, 5: 222, 6: 222,
                     8: 53, 9: 129, 10: 222, 11: 222, 12: 222, 13: 222},
    dl_settings=0x80 | 8,                               # OptNeg, RX2 DR8
    rx2_hz=923_300_000,
))
