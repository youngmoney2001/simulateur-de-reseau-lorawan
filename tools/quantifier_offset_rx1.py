"""Impact de RX1DROffset > 0 : ce que le simulateur produit, ce que RP002 exige.

Le serveur fixe RX1DROffset à 0. Un terminal configuré avec un offset non nul reçoit donc
une descente au mauvais débit. Mesure : le SF de RX1, et le rapport de temps d'émission
(airtime) entre la valeur exigée et la valeur produite.
"""
from __future__ import annotations
import sys, re
sys.path.insert(0, "/home/user/work/python")
from lsim.plan import get_plan

# (SF, BW kHz) par DR et par région — RP002-1.0.4 (cf. verifier_rx1_rp002.py)
DRL = {
 "EU868":{0:(12,125),1:(11,125),2:(10,125),3:(9,125),4:(8,125),5:(7,125),6:(7,250)},
 "US915":{0:(10,125),1:(9,125),2:(8,125),3:(7,125),4:(8,500),8:(12,500),9:(11,500),10:(10,500),11:(9,500),12:(8,500),13:(7,500)},
 "AU915":{0:(12,125),1:(11,125),2:(10,125),3:(9,125),4:(8,125),5:(7,125),6:(8,500),8:(12,500),9:(11,500),10:(10,500),11:(9,500),12:(8,500),13:(7,500)},
 "AS923":{0:(12,125),1:(11,125),2:(10,125),3:(9,125),4:(8,125),5:(7,125),6:(7,250)},
 "IN865":{0:(12,125),1:(11,125),2:(10,125),3:(9,125),4:(8,125),5:(7,125)},
 "KR920":{0:(12,125),1:(11,125),2:(10,125),3:(9,125),4:(8,125),5:(7,125)},
 "RU864":{0:(12,125),1:(11,125),2:(10,125),3:(9,125),4:(8,125),5:(7,125),6:(7,250)},
}
# mapping RX1 RP002-1.0.4 : (dr, offset) -> dr
OFF = {
 "EU868":lambda dr,o: max(0, min(dr-o, 7)),
 "US915":lambda dr,o: {0:[10,9,8,8],1:[11,10,9,8],2:[12,11,10,9],3:[13,12,11,10],4:[13,13,12,11]}[dr][o],
 "AU915":lambda dr,o: {0:[8,8,8,8,8,8],1:[9,8,8,8,8,8],2:[10,9,8,8,8,8],3:[11,10,9,8,8,8],
                       4:[12,11,10,9,8,8],5:[13,12,11,10,9,8],6:[13,13,12,11,10,9]}[dr][o],
 "AS923":lambda dr,o: max(0, min(dr-o, 7)),
 "IN865":lambda dr,o: max(0, min(dr-o, 7)),
 "KR920":lambda dr,o: max(0, min(dr-o, 5)),
 "RU864":lambda dr,o: max(0, min(dr-o, 7)),
}
MAXOFF = {"EU868":5,"US915":3,"AU915":5,"AS923":5,"IN865":5,"KR920":5,"RU864":5}
# airtime relatif ~ 2^SF / BW  (proportionnel, préambule et en-tête négligés)
def air(sf, bw): return (2 ** sf) / bw

print("RX1 : SF exigé par RP002 (offset o) vs SF produit par le serveur (offset 0)")
print("rapport = airtime exigé / airtime produit ; >1 = le serveur sous-estime la fenêtre\n")
pire = 0.0
for name in DRL:
    p, tbl, n = get_plan(name), DRL[name], MAXOFF[name]
    lignes = []
    for dr in sorted(p._uplink_datr.values()):
        if dr not in tbl: continue
        prod_dr = p._rx1_dr[dr]                       # ce que le serveur utilise (offset 0)
        m = re.fullmatch(r"SF(\d+)BW(\d+)", p._dr_table[prod_dr]); sf_p, bw_p = int(m.group(1)), int(m.group(2))
        for o in range(1, n + 1):
            ex_dr = OFF[name](dr, o)
            if ex_dr not in tbl: continue
            sf_e, bw_e = tbl[ex_dr]
            r = air(sf_e, bw_e) / air(sf_p, bw_p)
            pire = max(pire, r, 1.0 / r)
            if abs(r - 1.0) > 1e-9:
                lignes.append(f"    DR{dr} offset {o} : RP002 DR{ex_dr} (SF{sf_e}/{bw_e}) "
                              f"vs serveur DR{prod_dr} (SF{sf_p}/{bw_p})  rapport {r:.2f}x")
    print(f"{name}  (offsets 1..{n})")
    print("\n".join(lignes) if lignes else "    aucun écart : la table à offset 0 suffit")
    print()
print(f"Rapport maximal observé : {pire:.2f}x")
