"""Plan KR920-923 (Corée du Sud), LoRaWAN Regional Parameters RP002-1.0.2 §2.8.

Canaux par défaut (indices TxCh du MIC 1.1) : 0 = 922,1 MHz, 1 = 922,3 MHz, 2 = 922,5 MHz,
LoRa 125 kHz, DR0 à DR5. Ces trois canaux ne peuvent pas être modifiés par NewChannelReq.
Pas de CFList émise : seuls ces trois canaux sont utilisés, comme en EU868.

Débits montants et descendants : DR0 à DR5 = SF12 à SF7 / 125 kHz (RP002-1.0.2 §2.8.3). Pas de DR6.

RX1 : même canal que l'émission ; débit = max(0, DR montant − RX1DROffset), table RP002-1.0.2
§2.8.7. Ce serveur fixe RX1DROffset à 0 : débit RX1 = débit montant.
RX2 par défaut : 921,9 MHz / DR0 (RP002-1.0.2 §2.8.7 ; DLSettings 0x80).

Charge applicative sans FOpts (N) : valeurs prudentes 51, 51, 51, 115, 222, 222 pour DR0 à DR5.
Les valeurs DR0 à DR3 (51 / 115) correspondent aux tableaux publics ; pour DR4 et DR5, les
tableaux publics donnent 222 ou 242 selon la variante « repeater compatible » ou non. Le tableau
62 de RP002-1.0.2 n'a pas pu être lu dans cet environnement : on retient 222, la plus petite
valeur, pour ne jamais dépasser la charge autorisée.

Non modélisé : les 16 canaux de la liste étendue (CFList), la limite de dwell time, la puissance
(PIRE) et les règles locales (voir `lsim.regions`).
"""

from lsim.plan import Plan, register

_CHANNELS_HZ = (922_100_000, 922_300_000, 922_500_000)

KR920 = register(Plan(
    name="KR920",
    uplink_datr={
        "SF12BW125": 0, "SF11BW125": 1, "SF10BW125": 2,
        "SF9BW125": 3, "SF8BW125": 4, "SF7BW125": 5,
    },
    uplink_channels_hz=_CHANNELS_HZ,
    downlink_datr={
        0: "SF12BW125", 1: "SF11BW125", 2: "SF10BW125",
        3: "SF9BW125", 4: "SF8BW125", 5: "SF7BW125",
    },
    rx1_dr={dr: dr for dr in range(6)},                  # RX1DROffset 0 : même débit
    rx1_channel_hz=lambda tx_ch: _CHANNELS_HZ[tx_ch],    # RX1 : même canal
    max_frm_payload={0: 51, 1: 51, 2: 51, 3: 115, 4: 222, 5: 222},
    dl_settings=0x80,                                    # OptNeg, RX2 DR0
    rx2_hz=921_900_000,                                  # RX2 par défaut (RP002-1.0.2 §2.8.7)
))
