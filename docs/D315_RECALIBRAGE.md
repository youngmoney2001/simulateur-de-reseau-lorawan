# D3.15 — Recalibrage du jeu de scènes

**Date** : 2026-11-06 · **Branche** : `arena/fdc94521-simulateur-de-reseau-lorawan`
**Commits de référence** : `72fc6cb` (éligibilité par fenêtre) → `755e1f7` (archivage + statut)

Ce document est la **phase C** du protocole de recalibrage (§24.5.1). Il suit
[`d315-STATUT.md`](archives/d315-avant-recalibrage/d315-STATUT.md) (phase B), qui
avait établi la vacuité du jeu historique et laissé un point ouvert : US915 et
AU915 ne produisaient aucun repli.

**Le point ouvert est résolu. Les sept régions produisent désormais des replis
réels.** La cause n'était pas un mauvais réglage mais une propriété structurelle
du modèle de collision, exposée ci-dessous (§C.2).

---

## C.1 — Résultat

Scènes recalibrées, charge descendante **40 octets** (au lieu de 120), scènes à
deux SF pour US915 et AU915. Critère de non-vacuité : `rx1 > 0` **et** `rx2 > 0`,
et non « le test passe ».

| Région | SF montants | Charge | N(RX2) | Jobs | RX1 | **RX2** | Sans fenêtre | Non vide |
|---|---|---:|---:|---:|---:|---:|---:|:---:|
| EU868 | 11 | 40 | 51 | 440 | 260 | **120** | 60 | ✅ |
| US915 | 10 + 7 | 40 | 53 | 280 | 220 | **40** | 20 | ✅ |
| AS923 | 7 | 40 | 51 | 562 | 323 | **84** | 155 | ✅ |
| AU915 | 10 + 8 | 40 | 53 | 280 | 180 | **40** | 60 | ✅ |
| IN865 | 7 | 40 | 51 | 562 | 323 | **84** | 155 | ✅ |
| KR920 | 9 | 40 | 51 | 210 | 80 | **33** | 97 | ✅ |
| RU864 | 10 | 40 | 51 | 800 | 500 | **120** | 180 | ✅ |

**7 / 7.** Aucune région n'est vacante. Les colonnes « sans fenêtre » non nulles
attestent que la contrainte est réellement exercée : des descentes sont perdues,
la scène n'est pas triviale.

### Correction collatérale

`SF_SATURANT["US915"] = 11` est **invalide** : SF11/125 kHz n'est un DR montant
d'aucune région US915 (DR0 = SF10/125). C'est précisément ce que **P1** détecte
et refuse. Le jeu recalibré emploie **SF10/125 = DR0**, le DR montant le plus
lent de la région — celui qui conserve la propriété recherchée par la scène
(contention), sans enfreindre le plan régional.

---

## C.2 — Pourquoi US915 et AU915 résistaient

Ce n'était pas un défaut de calibrage. Trois faits, tous mesurés.

### Fait 1 — le modèle de collision montant ignore la fréquence

`_CTxRecord` (pont Python↔C++, `simulator.py`) porte :
`device_index, start_ns, end_ns, spreading_factor, rssi_dbm, outcome`.
**Aucun champ de fréquence.** Le cœur C++ place donc toutes les émissions
montantes dans un **domaine de collision unique**, quel que soit le canal déclaré
par le groupe.

Conséquence : séparer les terminaux sur deux canaux ne les empêche pas de se
collisionner. Vérifié — à mesure qu'on ajoute des canaux, le nombre de jobs
*s'effondre* au lieu de croître :

```
1 canal  × 10 terminaux :  50 montants → 10 jobs
2 canaux × 10 terminaux : 100 montants →  5 jobs
3 canaux × 10 terminaux : 150 montants →  5 jobs
```

La parade « deux canaux pour des montants non collisionnés, une seule radio
descendante » — la voie évidente — est donc **fermée**.

### Fait 2 — en 500 kHz, une fenêtre RX1 est plus courte que son montant

Temps d'antenne mesurés (`time_on_air_ns`, montant 20 o + 13, descendant 40 o + 13) :

| Région | SF | Montant | RX1 | RX2 | RX1 / montant |
|---|---|---:|---:|---:|---:|
| EU868 | 11 | 905,2 ms | 1314,8 ms | 2465,8 ms | **1,45** |
| US915 | 10 | 452,6 ms | 154,1 ms | 534,5 ms | **0,34** |
| AS923 | 7 | 71,9 ms | 102,7 ms | 616,4 ms | **1,43** |
| AU915 | 7 | 71,9 ms | 25,7 ms | 534,5 ms | **0,36** |
| IN865 | 7 | 71,9 ms | 102,7 ms | 616,4 ms | **1,43** |
| KR920 | 9 | 246,8 ms | 328,7 ms | 2465,8 ms | **1,33** |
| RU864 | 10 | 452,6 ms | 616,4 ms | 2465,8 ms | **1,36** |

Deux fenêtres RX1 ne se chevauchent que si les deux montants correspondants se
terminent à moins d'un temps d'antenne *descendant* l'un de l'autre.

- Là où **RX1 > montant** (EU868, AS923, IN865, KR920, RU864), il existe un
  intervalle non vide : deux montants peuvent se terminer assez loin pour ne pas
  se collisionner, et assez près pour que leurs fenêtres RX1 se recouvrent.
  **La contention est atteignable** — et elle l'était déjà à 120 octets dans
  AS923, IN865, KR920.
- Là où **RX1 < montant** (US915, AU915 : descente à 500 kHz, soit 4× plus
  rapide à SF égal), cet intervalle est **vide**. Deux montants dont les
  extrémités sont à moins d'un temps d'antenne descendant se recouvrent
  nécessairement : ils se collisionnent, et les deux descentes disparaissent avec
  eux. **La contention est structurellement inatteignable dans un scène à SF
  unique.**

### Fait 3 — la capacité ne peut pas non plus amorcer

Reste la seconde cause d'inéligibilité de RX1, le **dépassement de capacité**.
Elle exigerait `N(RX1) < charge ≤ N(RX2)`, or `N(RX1) = 222 > N(RX2) = 53` en
US915/AU915 :

| Région | N(RX1) | N(RX2) |
|---|---:|---:|
| EU868 | 51 | 51 |
| RU864 | 51 | 51 |
| US915 | 222 | 53 |
| AS923 | 222 | 51 |
| AU915 | **222** | **53** |
| IN865 | 222 | 51 |
| KR920 | 115 | 51 |

Toute charge transportable en RX2 l'est *a fortiori* en RX1. Aucun dépassement
de capacité ne peut donc s'y produire, et le repli ne peut être déclenché que
par l'occupation de l'émetteur — laquelle est inatteignable en scène à SF
unique (fait 2).

> **Rectificatif (phase C, après mesure).** Une version antérieure de ce
> document attribuait les replis d'EU868 et de RU864 à leur limite de duty
> cycle. **C'est faux, et la mesure l'a démenti.** Les limites ci-dessus
> (`duty_cycle_limit`, 0,01 en EU868, 0,001 en RU864) contraignent les
> **émissions montantes**, pas la planification descendante : l'arbitre
> descendant (`GatewayArbiter`) ne reçoit ici aucune règle de duty cycle.
> Vérifié sur les sept régions : **100 % des replis** sont imputables à une
> émission antérieure d'un **autre** terminal recouvrant la fenêtre RX1, sans
> un seul auto-blocage ni un seul cas inexpliqué, et le seul motif rapporté est
> `window_missed` (famille `temporel`). Le mécanisme est donc **le même dans
> les sept régions** : de la contention, et rien d'autre. Seul le fait 2
> explique que deux d'entre elles n'y parviennent pas.

### La parade retenue

Le fait 2 ne vaut que pour des montants de **même SF**, seul cas où la collision
est jugée. Entre deux SF différents, la collision n'est pas évaluée : un montant
SF7 (71,9 ms) peut se terminer à l'intérieur d'un montant SF10 (452,6 ms) sans
que ni l'un ni l'autre soit perdu. Leurs fenêtres RX1 s'ouvrent alors à moins de
154 ms d'intervalle — largement dans la fenêtre d'occupation de la descente SF10.

**Une scène à deux groupes de SF différents lève l'impossibilité**, sans rien
assouplir : la contention descendante est réelle, et les montants survivent.

| Région | Paire de SF | Spread | Jobs | RX1 | RX2 | Sans fenêtre |
|---|---|---:|---:|---:|---:|---:|
| US915 | 10 + 7 | 2,0 s | 280 | 220 | **40** | 20 |
| AU915 | 10 + 8 | 3,0 s | 280 | 180 | **40** | 60 |

---

## C.3 — Ce que cela change pour les conclusions historiques

Le jeu historique reposait sur une hypothèse implicite : **que saturer une scène
suffit à faire apparaître des replis dans toutes les régions**. Cette hypothèse
est fausse pour US915 et AU915, et fausse pour une raison structurelle — pas pour
un défaut de réglage.

Deux conséquences :

1. **Les conclusions invalidées par la vacuité ne sont pas restaurées par un
   simple changement de charge.** Elles doivent être ré-énoncées sur les scènes
   recalibrées, région par région, avec le critère `rx1 > 0 et rx2 > 0`.
2. **La couverture des sept régions (zz5) n'est pas remise en cause, mais son
   mode de démonstration l'est** : pour US915 et AU915 elle exige une scène
   bi-SF. Un jeu qui prétendrait l'obtenir avec une scène à SF unique serait
   vacant, même s'il passait au vert.

## C.4 — Le jeu D3.15-R

`python/tests/test_d315_recalibre.py` — **91 tests, tous passants**. Conformément
à **O4**, c'est un **nouveau fichier** : `test_d315_global.py` et son jumeau
`test_d315_causal_envelope.py` demeurent intacts, dans l'état archivé en
`docs/archives/d315-avant-recalibrage/2026-11-06/`. Aucun n'a été modifié.

### Conclusions reprises, rangées par verdict

| Conclusion historique | Verdict |
|---|---|
| Les sept régions exercent le repli | **Confirmée** — elle était vacante, elle est maintenant mesurée |
| Chaque fenêtre respecte le N de son DR | **Confirmée** — `charge + \|FOpts\| ≤ N(fenêtre)`, aucune violation |
| Le repli ne peut qu'ajouter du temps d'antenne | **Confirmée** — vraie mais vide à 120 o, mesurée à 40 o |
| Parité cœur C++ / oracle Python | **Confirmée et étendue** — de 4 régions à 7, sur scènes non vacantes |
| Airtime et sensibilité suivent la fenêtre émise | **Confirmée** |
| Scénario sans région : aucun repli | **Confirmée** |
| Profils RX2 différenciés | **Confirmée** |
| **À R < 1 le repli n'est jamais perdant** | **Requalifiée — domaine restreint** |

### La conclusion requalifiée : R < 1

Le jeu historique énonçait « mesuré, 3 configurations sur 3 ». Le balayage des
six SF montants valides sur les sept régions montre que le régime `R < 1` est
**bien plus étroit** :

- **EU868, KR920, RU864** : RX2 est en SF12/125 et RX1 suit le SF montant, qui
  vaut au plus 12 ⇒ `R ≥ 1` partout (égalité au SF12).
- **US915, AU915** : RX1 et RX2 sont tous deux à 500 kHz, et RX2 y est le DR le
  plus lent (DR8 = SF12/500) ⇒ `R > 1` partout. Les trois configurations
  historiques à `R < 1` venaient **d'US915 au SF11 — un SF invalide**, précisément
  celui que P1 refuse.
- **AS923, IN865** : RX2 est en SF10/125. Un montant en SF11 donne `R = 0,47` —
  les deux seules configurations exploitables (une par région, au lieu de trois
  sur sept).

La conclusion reste donc **vraie**, mais sur **2 configurations dans 2 régions**
au lieu de 3 dans 7. Elle est assortie d'un garde-fou de portée qui échouerait
si une huitième configuration à `R < 1` apparaissait.

### Les replis sont bien de la contention

Mesure faite sur les sept régions, à charge conforme :

| Région | Replis | Bloqués par une émission **distincte** | Auto-blocage | Inexpliqués |
|---|---:|---:|---:|---:|
| EU868 | 120 | 120 | 0 | 0 |
| US915 | 40 | 40 | 0 | 0 |
| AS923 | 84 | 84 | 0 | 0 |
| AU915 | 40 | 40 | 0 | 0 |
| IN865 | 84 | 84 | 0 | 0 |
| KR920 | 33 | 33 | 0 | 0 |
| RU864 | 120 | 120 | 0 | 0 |

Le seul motif rapporté est `window_missed` (famille `temporel`) : aucun repli
n'est imputable à la capacité. Un témoin négatif complète la preuve — à un seul
terminal par groupe, la contention disparaît et **le repli disparaît avec elle**
(`rx2 = 0`, `aucune = 0`), à région et charge identiques.

### Limitation épinglée, non réparée

La scène bi-SF n'est **pas** une preuve de fidélité radio. Elle exploite que
`_CTxRecord` ne porte aucun champ de fréquence, donc que le cœur C++ place toutes
les émissions montantes dans un domaine de collision unique. Un test dédié
épingle cette limitation : il échouera si le chantier radio ajoute la dimension
de fréquence, ce qui imposera de revoir la portée attribuée aux conclusions
d'US915 et d'AU915.

### Vérification

- `test_d315_recalibre.py` : **91 passed**, 0 échec, 0 saut.
- Suite complète : **2409 passed / 15 failed / 1 skipped**, contre
  2318 / 15 / 1 avant l'ajout — soit exactement +91, **aucun test existant
  cassé**. Les 15 échecs sont les mêmes qu'avant, tous dans
  `test_d315_global.py`.
- `ctest` : **1/1**.
- Parité Python/C++ vérifiée région par région sur les sept scènes (occupation,
  sauts descendants, motifs de refus).
