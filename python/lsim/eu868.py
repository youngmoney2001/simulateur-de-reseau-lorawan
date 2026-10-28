"""Plan EU863-870 (EU868), RP002-1.0.2 (§2.4).

- Canaux par défaut (§2.4.2, tableau 6) : 868,10 / 868,30 / 868,50 MHz, indices 0, 1, 2.
  Pas de CFList dans les join-accept émis : seuls ces trois canaux sont utilisés.
- Débits (§2.4.3, tableau 8) : DR0 à DR5 = SF12 à SF7 / 125 kHz, DR6 = SF7 / 250 kHz.
- Charge applicative sans FOpts (§2.4.6, tableau 12, valeurs « repeater compatible ») : N = 51,
  51, 51, 115, 222, 222, 222 pour DR0 à DR6.
- RX1 (§2.4.7) : même canal que l'émission, débit = débit montant (RX1DROffset 0).
- DLSettings : RX2 par défaut DR0 (§2.4.7).
"""

from lsim.plan import Plan, register

_CHANNELS_HZ = (868_100_000, 868_300_000, 868_500_000)

EU868 = register(Plan(
    name="EU868",
    uplink_datr={
        "SF12BW125": 0, "SF11BW125": 1, "SF10BW125": 2, "SF9BW125": 3,
        "SF8BW125": 4, "SF7BW125": 5, "SF7BW250": 6,
    },
    uplink_channels_hz=_CHANNELS_HZ,
    downlink_datr={
        0: "SF12BW125", 1: "SF11BW125", 2: "SF10BW125", 3: "SF9BW125",
        4: "SF8BW125", 5: "SF7BW125", 6: "SF7BW250",
    },
    rx1_dr={dr: dr for dr in range(7)},                  # RX1DROffset 0 : même débit
    rx1_channel_hz=lambda tx_ch: _CHANNELS_HZ[tx_ch],    # RX1 : même canal
    max_frm_payload={0: 51, 1: 51, 2: 51, 3: 115, 4: 222, 5: 222, 6: 222},
    dl_settings=0x80,                                    # OptNeg, RX2 DR0
))
