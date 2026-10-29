"""Plan IN865-867 (Inde), LoRaWAN Regional Parameters RP002-1.0.2 §2.9.

Canaux par défaut (indices TxCh du MIC 1.1) : 0 = 865,0625 MHz, 1 = 865,4025 MHz, 2 = 865,985 MHz,
LoRa 125 kHz, DR0 à DR5 (§2.12.2 dans les tableaux de la version de référence de `lsim.regions`).
Pas de CFList émise : seuls ces trois canaux sont utilisés, comme en EU868.

Débits montants et descendants : DR0 à DR5 = SF12 à SF7 / 125 kHz. Pas de DR6.

RX1 : même canal que l'émission ; débit = max(0, DR montant − RX1DROffset). Ce serveur fixe
RX1DROffset à 0 : débit RX1 = débit montant.
RX2 par défaut : 866,550 MHz / DR2 (SF10 / 125 kHz). Valeur donnée par des guides de passerelles
et des documents de constructeurs, non relue dans le texte RP002 pendant cette session.

Charge applicative sans FOpts (N) : valeurs prudentes 51, 51, 51, 115, 222, 222 pour DR0 à DR5.
Le tableau de charges de RP002-1.0.2 pour IN865 n'a pas été lu (limite de lecture de l'outil) ;
les valeurs retenues sont inférieures ou égales à celles des plans à structure identique.

Non modélisé : la PIRE et la limite légale (GSR 564(E), voir `lsim.regions`) ; les canaux
supplémentaires de la liste étendue (CFList).
"""

from lsim.plan import Plan, register

_CHANNELS_HZ = (865_062_500, 865_402_500, 865_985_000)

IN865 = register(Plan(
    name="IN865",
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
    dl_settings=0x82,                                    # OptNeg, RX2 DR2
    rx2_hz=866_550_000,                                  # RX2 par défaut
))
