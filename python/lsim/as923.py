"""Plan AS923 (AS923-1, 920-925 MHz), LoRaWAN Regional Parameters RP002-1.0.4 §2.7.

Canaux par défaut (indices TxCh du MIC 1.1) : 0 = 923,2 MHz, 1 = 923,4 MHz (LoRa 125 kHz).
Pas de CFList émise : seuls ces deux canaux sont utilisés, comme en EU868.
Débits montants et descendants : DR0 à DR5 = SF12 à SF7 / 125 kHz, DR6 = SF7 / 250 kHz.
DR7 (FSK 50 kbit/s) n'est pas géré.

RX1 : même canal que l'émission ; débit = max(0, DR montant − RX1DROffset) (table « AS923
downlink RX1 data rate mapping », RP002-1.0.4). Le serveur règle RX1DROffset à 0 par défaut : débit RX1 = débit
montant. Un offset non nul est un réglage de déploiement (groupe). RX2 par défaut : 923,2 MHz / DR2 (DLSettings).

Charge applicative sans FOpts (N) : 51, 51, 51, 115, 222, 222, 222 pour DR0 à DR6 (valeurs
prudentes : N = M − 8 avec M = 59, 59, 59, 123, 230, 230, 230). Le tableau 53 de RP002-1.0.4
(§2.7.6) n'a pas pu être lu dans cet environnement ; pour DR4 à DR6, une variante non compatible
répéteur donne N = 242 : la valeur retenue reste donc inférieure ou égale à la limite réelle.

Non modélisé : DownLinkDwellTime = 1 (400 ms) qui relève le débit minimal à DR2 et réduit le
mapping RX1 ; les limites par pays (ARIB pour le Japon, voir `lsim.regions`) ; les canaux
supplémentaires par CFList.
Provenance
----------
Référence vérifiée ....... RP002-1.0.4 (débits, mapping RX1, bornes d'offset)
Source ................... deux transcriptions indépendantes et concordantes :
                           LoRaMac-node v4.7.1 (Lora-net) et lorawan-stack v3.37.0 (TTI)
Vérificateur ............. tools/verifier_rx1_rp002.py (0 écart sur les 7 régions)
Réserve .................. les tables régionales de RP002-1.0.5 n'ont PAS été lues
                           directement ; voir docs/I5_C_RX1_DROFFSET.md §1

"""

from lsim.plan import Plan, register, rx1_clamp_table

_CHANNELS_HZ = (923_200_000, 923_400_000)

AS923 = register(Plan(
    name="AS923",
    uplink_datr={
        "SF12BW125": 0, "SF11BW125": 1, "SF10BW125": 2, "SF9BW125": 3,
        "SF8BW125": 4, "SF7BW125": 5, "SF7BW250": 6,
    },
    uplink_channels_hz=_CHANNELS_HZ,
    downlink_datr={
        0: "SF12BW125", 1: "SF11BW125", 2: "SF10BW125", 3: "SF9BW125",
        4: "SF8BW125", 5: "SF7BW125", 6: "SF7BW250",
    },
    rx1_dr_table=rx1_clamp_table(tuple(range(7)), dr_max=7, offsets=6),
    rx1_channel_hz=lambda tx_ch: _CHANNELS_HZ[tx_ch],    # RX1 : même canal
    max_frm_payload={0: 51, 1: 51, 2: 51, 3: 115, 4: 222, 5: 222, 6: 222},
    dl_settings=0x80 | 2,                                # OptNeg, RX2 DR2
    rx2_hz=923_200_000,                                  # RX2 par défaut (RP002-1.0.4 §2.7)
))
