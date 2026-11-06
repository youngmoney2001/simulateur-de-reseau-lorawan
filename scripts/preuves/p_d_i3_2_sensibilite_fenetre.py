#!/usr/bin/env python3
"""Preuve D3.15 — D-I3-2 : la réception d'un ACK suit le seuil de RX1, quelle que soit la fenêtre.

Deux terminaux, deux jeux de débits :
  - terminal 0 (« gros »)   RX1 SF12/125 kHz, RX2 SF9/125 kHz ;
  - terminal 1 (« petit »)  RX1 SF7/125 kHz,  RX2 **SF12**/125 kHz.

Le terminal 0 occupe l'émetteur pendant toute la fenêtre RX1 du terminal 1 : l'ACK de ce dernier
ne peut donc partir qu'en RX2, au SF12 — ce que confirme la durée d'occupation constante mesurée
ci-dessous (991,2 ms, l'airtime d'un SF12/125 kHz). Son seuil de réception devrait donc être celui
du SF12 (**-136 dBm**, [H] `lsim.radio.receiver_sensitivity_dbm`), et non celui du SF7 de sa RX1
(-123 dBm).

Constat : la bascule « reçu » -> « perdu » a lieu exactement au seuil **SF7**. Les 13 dB de marge
que le SF12 apporte en RX2 sont ignorés. Cause lue dans `lsim/ack_mac.py` : `_decodable` est
évalué sur `rx1_sf`/`rx1_bw_hz` avant que la fenêtre ne soit connue, et le verdict est appliqué à
toutes les copies. `lsim/join.py` importe le même `_decodable` : le défaut atteint donc aussi le
Join-Accept, dont le repli RX2 est actif par défaut.

Usage (depuis la racine du dépôt) :
    LSIM_LIBRARY=build_i1/liblsim_core.so PYTHONPATH=python python3 scripts/preuves/p_d_i3_2_sensibilite_fenetre.py

Épinglé sous `xfail(strict=True)` dans
`python/tests/test_d315_global.py::test_d_i3_2_la_reception_suit_la_fenetre_dans_ack_mac`.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "python"))

from lsim.ack_mac import AckTiming, plan_acks
from lsim.trace_events import DeviceRadio, ProtocolOptions
from lsim.radio import receiver_sensitivity_dbm
from lsim.simulator import TxRecord

RX1_HZ, RX2_HZ = 868_100_000, 869_525_000
gros = DeviceRadio(freq_hz=RX1_HZ, dr=None, rx1_hz=RX1_HZ, tx_power_dbm=14.0,
                   rx1_sf=12, rx1_bw_hz=125_000, rx2_hz=RX2_HZ, rx2_sf=9, rx2_bw_hz=125_000)
petit = DeviceRadio(freq_hz=RX1_HZ, dr=None, rx1_hz=RX1_HZ, tx_power_dbm=14.0,
                    rx1_sf=7, rx1_bw_hz=125_000, rx2_hz=RX2_HZ, rx2_sf=12, rx2_bw_hz=125_000)
opts = ProtocolOptions(confirmed_uplinks=True, downlink_every=1, downlink_payload_bytes=27,
                       gateway_tx_power_dbm=27.0)
seuil_rx1 = receiver_sensitivity_dbm(7, 125_000)   # -123
seuil_rx2 = receiver_sensitivity_dbm(12, 125_000)  # -136
print(f"seuil RX1 (SF7) = {seuil_rx1} dBm | seuil RX2 (SF12) = {seuil_rx2} dBm")
print("rssi  rssi_dl  verdict  fenêtre   durée d'occupation (ms)")
for rssi in (-125.0, -130.0, -135.0, -136.0, -137.0, -140.0, -145.0, -148.0, -152.0):
    records = [TxRecord(0, 0, 100_000_000, 12, rssi, TxRecord.OUTCOME_RECEIVED),
               TxRecord(1, 490_000_000, 590_000_000, 7, rssi, TxRecord.OUTCOME_RECEIVED)]
    plan = plan_acks(records, [gros, petit], opts, AckTiming(delay_ms=1500))
    o = plan.outcomes[1]
    duree = (plan.busy[1][1] - plan.busy[1][0]) / 1e6
    print(f"{rssi:6.0f} {rssi+13:7.0f}  {str(o.sort):28s} {str(o.window):22s} {duree:8.1f}")
