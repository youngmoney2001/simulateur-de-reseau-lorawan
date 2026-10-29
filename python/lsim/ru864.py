"""Plan RU864-870 (Russie), LoRaWAN Regional Parameters RP002-1.0.x §2.11 (RU864).

Canaux par défaut (indices TxCh du MIC 1.1) : 0 = 868,9 MHz, 1 = 869,1 MHz, LoRa 125 kHz,
DR0 à DR5. Ces deux canaux servent à la jointure ; pas de CFList émise, comme en EU868.

Débits montants et descendants : DR0 à DR5 = SF12 à SF7 / 125 kHz. DR6 (SF7 / 250 kHz) n'est
pas retenu : certains documents le listent, d'autres non ; le serveur reste sur le sous-ensemble
sûr. Ce choix est à revoir si la table RP002 applicable est relue.

RX1 : même canal que l'émission ; débit = max(0, DR montant − RX1DROffset). Ce serveur fixe
RX1DROffset à 0 : débit RX1 = débit montant.
RX2 par défaut : 869,1 MHz / DR0 (SF12 / 125 kHz).

Charge applicative sans FOpts (N) : 51, 51, 51, 115, 222, 222 pour DR0 à DR5 (valeurs EU868,
« repeater compatible » ; le tableau RU864 n'a pas été relu en entier dans cet environnement).

Non modélisé : la PIRE (16 dBm, voir `lsim.regions`), la règle LBT et le duty cycle de la
sous-bande, et les canaux supplémentaires (CFList).
"""

from lsim.plan import Plan, register

_CHANNELS_HZ = (868_900_000, 869_100_000)

RU864 = register(Plan(
    name="RU864",
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
    rx2_hz=869_100_000,                                  # RX2 par défaut
))
