"""Plan RU864-870 (Russie), LoRaWAN Regional Parameters RP002-1.0.x §2.11 (RU864).

Canaux par défaut (indices TxCh du MIC 1.1) : 0 = 868,9 MHz, 1 = 869,1 MHz, LoRa 125 kHz,
DR0 à DR5. Ces deux canaux servent à la jointure ; pas de CFList émise, comme en EU868.

Débits montants et descendants : DR0 à DR5 = SF12 à SF7 / 125 kHz, DR6 = SF7 / 250 kHz (comme
EU868).

RX1 : même canal que l'émission ; débit = max(0, DR montant − RX1DROffset). Ce serveur fixe
RX1DROffset à 0 par défaut : débit RX1 = débit montant ; un offset non nul est
un réglage de déploiement (groupe).
RX2 par défaut : 869,1 MHz / DR0 (SF12 / 125 kHz).

Charge applicative sans FOpts (N) : 51, 51, 51, 115, 222, 222, 222 pour DR0 à DR6, valeurs
EU868 reprises (le tableau RU864 n'a pas été relu en entier dans cet environnement).

Non modélisé : la PIRE (16 dBm, voir `lsim.regions`), la règle LBT et le duty cycle de la
sous-bande, et les canaux supplémentaires (CFList).
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

_CHANNELS_HZ = (868_900_000, 869_100_000)

RU864 = register(Plan(
    name="RU864",
    uplink_datr={
        "SF12BW125": 0, "SF11BW125": 1, "SF10BW125": 2,
        "SF9BW125": 3, "SF8BW125": 4, "SF7BW125": 5, "SF7BW250": 6,
    },
    uplink_channels_hz=_CHANNELS_HZ,
    downlink_datr={
        0: "SF12BW125", 1: "SF11BW125", 2: "SF10BW125",
        3: "SF9BW125", 4: "SF8BW125", 5: "SF7BW125", 6: "SF7BW250",
    },
    rx1_dr_table=rx1_clamp_table(tuple(range(7)), dr_max=7, offsets=6),
    rx1_channel_hz=lambda tx_ch: _CHANNELS_HZ[tx_ch],    # RX1 : même canal
    max_frm_payload={0: 51, 1: 51, 2: 51, 3: 115, 4: 222, 5: 222, 6: 222},
    dl_settings=0x80,                                    # OptNeg, RX2 DR0
    rx2_hz=869_100_000,                                  # RX2 par défaut
))
