"""Confrontation : tables RX1 du simulateur vs relevé RP002-1.0.4.

Référence = RP002-1.0.4, transcrit indépendamment par deux implantations :
  - LoRaMac-node v4.7.1 (Lora-net) : DatarateOffsetsUS915[5][4], DatarateOffsetsAU915[7][6]
  - lorawan-stack v3.37.0 (TTI)    : us902928DownlinkDRTable, au915928DownlinkDRTable, ...
Les deux concordent exactement sur US915 et AU915 (seules régions tabulées).

Sortie : une ligne par région, CONFORME ou un écart explicite.
"""
from __future__ import annotations
import re, sys
sys.path.insert(0, "/home/user/work/python")
from lsim.plan import get_plan

# RP002-1.0.4 : DR -> (SF, BW kHz). None = modulation non LoRa (FSK / LR-FHSS), hors périmètre.
DR = {
    "EU868": {0:(12,125), 1:(11,125), 2:(10,125), 3:(9,125), 4:(8,125), 5:(7,125), 6:(7,250), 7:None},
    "US915": {0:(10,125), 1:(9,125), 2:(8,125), 3:(7,125), 4:(8,500), 5:None, 6:None,
              8:(12,500), 9:(11,500), 10:(10,500), 11:(9,500), 12:(8,500), 13:(7,500)},
    "AU915": {0:(12,125), 1:(11,125), 2:(10,125), 3:(9,125), 4:(8,125), 5:(7,125), 6:(8,500), 7:None,
              8:(12,500), 9:(11,500), 10:(10,500), 11:(9,500), 12:(8,500), 13:(7,500)},
    "AS923": {0:(12,125), 1:(11,125), 2:(10,125), 3:(9,125), 4:(8,125), 5:(7,125), 6:(7,250), 7:None},
    "IN865": {0:(12,125), 1:(11,125), 2:(10,125), 3:(9,125), 4:(8,125), 5:(7,125), 7:None},
    "KR920": {0:(12,125), 1:(11,125), 2:(10,125), 3:(9,125), 4:(8,125), 5:(7,125)},
    "RU864": {0:(12,125), 1:(11,125), 2:(10,125), 3:(9,125), 4:(8,125), 5:(7,125), 6:(7,250), 7:None},
}
# RP002-1.0.4 : RX1 DR pour RX1DROffset = 0. Table explicite, ou règle clamp(dr - offset, lo, hi).
RX1_OFF0 = {
    "EU868": lambda dr: max(0, min(dr, 7)),
    "US915": lambda dr: {0:10, 1:11, 2:12, 3:13, 4:13}[dr],
    "AU915": lambda dr: {0:8, 1:9, 2:10, 3:11, 4:12, 5:13, 6:13}[dr],
    "AS923": lambda dr: max(0, min(dr, 7)),
    "IN865": lambda dr: max(0, min(dr, 7)),
    "KR920": lambda dr: max(0, min(dr, 5)),
    "RU864": lambda dr: max(0, min(dr, 7)),
}

def parse(datr):
    m = re.fullmatch(r"SF(\d+)BW(\d+)", datr)
    return (int(m.group(1)), int(m.group(2))) if m else None

ecarts = 0
print(f"{'région':7} {'DR montants':38} {'RX1 (offset 0)':30} verdict")
print("-" * 118)
for name in ("EU868", "US915", "AU915", "AS923", "IN865", "KR920", "RU864"):
    p = get_plan(name)
    ref, bad = DR[name], []

    # 1. table DR -> (SF, BW)
    up_ok, dn_ok = [], []
    for datr, dr in sorted(p._uplink_datr.items(), key=lambda kv: kv[1]):
        got = parse(datr)
        if got != ref.get(dr):
            bad.append(f"uplink DR{dr} {datr} != {ref.get(dr)}")
        up_ok.append(f"DR{dr}=SF{got[0]}/{got[1]}")
    for dr, datr in sorted(p._downlink_datr.items()):
        got = parse(datr)
        if got != ref.get(dr):
            bad.append(f"downlink DR{dr} {datr} != {ref.get(dr)}")
        dn_ok.append(f"{dr}->{got[0]}/{got[1]}")

    # 2. mapping RX1
    rx1 = p._rx1_dr
    for dr in sorted(rx1):
        attendu = RX1_OFF0[name](dr)
        if rx1[dr] != attendu:
            bad.append(f"RX1 DR{dr} -> DR{rx1[dr]} != DR{attendu}")
    rx1_txt = " ".join(f"{dr}→{rx1[dr]}" for dr in sorted(rx1))

    verdict = "CONFORME" if not bad else "ÉCART"
    ecarts += len(bad)
    print(f"{name:7} {', '.join(up_ok):38} {rx1_txt:30} {verdict}")
    for b in bad:
        print(f"         ! {b}")

print("-" * 118)
print(f"{ecarts} écart(s)")
