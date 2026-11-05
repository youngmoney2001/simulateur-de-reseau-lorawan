# Placement temporel des descentes — jalon U0.3 (arbitrage A6)

**Statut : implémenté, validé, sauvegardé.** Ce document est la référence du placement et
recense **toutes** les différences de résultats induites par A6.

| | |
|---|---|
| Arbitrage | **A6** — émission **exactement** à l'ouverture de RX1 ou de RX2, aucun décalage intra-fenêtre |
| Source normative | **[N]** TS001-1.0.4 §3.3.5 : « SHALL initiate the transmission of the downlink frame **precisely at the beginning** of one of those two receive windows » |
| Composant de référence | `lsim::radio::RadioScheduler` (`core/include/lsim/radio_scheduler.hpp`) |
| Périmètre | descentes de données et ACK, chemin causal **et** planificateur, passerelle unique |
| Hors périmètre | multi-passerelles (`engine.cpp` `first_free`), Join-Accept, ACK MAC, réémissions |

---

## 1. La règle

```
ouverture = fenêtre[0]                       # RX1 : fin de la montante + RECEIVE_DELAY1 (1 s)
                                             # RX2 : ouverture de RX1 + 1 s
début     = ouverture                        # jamais décalé, jamais anticipé

si [début, début + temps_d'antenne) chevauche une émission déjà planifiée :
    verdict = fenêtre manquée                # AUCUNE émission, AUCUNE occupation
sinon :
    verdict = émise                          # l'émetteur est occupé sur [début, début + air)
```

Deux propriétés structurent tout le reste :

1. **Le contact n'est pas un chevauchement.** L'intervalle d'occupation est semi-ouvert
   `[début, fin)` : une émission qui s'achève exactement à l'ouverture ne bloque pas la fenêtre.
   **[N]** Aucune source primaire ne fixe de garde ; c'est une **[D]** hypothèse de conception
   déjà retenue pour la durée d'occupation (temps d'antenne seul, sans temps de retournement).
2. **Le refus ne laisse aucune trace.** Une fenêtre manquée n'inscrit **rien** dans l'occupation
   — ni intervalle, ni intervalle de longueur nulle, ni report. L'occupation est exactement
   l'ensemble des émissions acceptées.

## 2. Ce qui a changé

L'ancienne règle était `début = max(ouverture, occupé_jusqu'à)`, avec refus si
`début − ouverture ≥ durée de la fenêtre`. La descente **attendait** la libération de
l'émetteur, dans la limite d'une seconde.

| Aspect | Avant U0.3 | Après U0.3 (A6) |
|---|---|---|
| Départ | `max(ouverture, occupé_jusqu'à)` | `ouverture` |
| Émetteur occupé à l'ouverture | attend, émet dès que libre | **fenêtre perdue** |
| Condition de refus | `début − ouverture ≥ 1 s` | chevauchement réel |
| Borne d'occupation | scalaire monotone `occupé_jusqu'à` | liste d'intervalles croissante et disjointe |
| Repli RX2 | implémenté, opt-in, **jamais déclenché** | effectif dès qu'une RX1 est perdue |
| Occupation d'un refus | aucune (déjà correct) | aucune (inchangé, désormais testé) |

## 3. Points d'entrée migrés

| Point d'entrée | Fichier | État |
|---|---|---|
| Planificateur causal incrémental | `core/src/downlink_plan.cpp` — `DownlinkScheduler::placer` | **migré** : délègue à `RadioScheduler::place_at` |
| Planificateur par lot (tas) | `core/src/downlink_plan.cpp` — `_schedule_gateway` | **migré** : deux branches RX1/RX2, même `place_at` |
| Oracle Python des descentes | `python/lsim/trace_events.py` — `_schedule_gateway` | **migré** : `GatewayArbiter(regle_placement=EXACTE)` |
| Règle de placement | `core/src/radio_scheduler.cpp` — `place_at` | **ajoutée** (U0.1 avait déjà `place` pour la boucle fermée) |

### 3.1 Points d'entrée **non** migrés, et pourquoi

| Point d'entrée | Fichier | Raison |
|---|---|---|
| Multi-passerelles | `core/src/engine.cpp` — `first_free`, `map_intersects` | explicitement **hors périmètre U0.3** |
| Join-Accept | `python/lsim/join.py` via `GatewayArbiter` | chemin distinct, migration hors jalon |
| ACK MAC | `python/lsim/ack_mac.py` via `GatewayArbiter` | chemin distinct, migration hors jalon |
| Réémissions | `python/lsim/retransmissions.py` via `GatewayArbiter` | chemin distinct, migration hors jalon |

Ces trois chemins Python restent sur la règle historique `DECALE`, qui demeure implémentée et
testée dans `lsim.arbitre.GatewayArbiter`. **Ce n'est pas une seconde logique concurrente pour
une même décision** : ce sont des décisions différentes (Join-Accept, ACK, réémission) prises par
le même composant. Leur migration est un jalon distinct. La coexistence est explicite, bornée et
documentée dans `arbitre.py` (`DECALE` / `EXACTE`).

## 4. Différences de résultats induites par A6

Mesurées sur 9 scènes de référence (sonde `/tmp/u0/ref_plan.py`), exécutées avant et après.
`occup` = durée totale d'occupation de l'émetteur.

| Scène | Descentes avant | Descentes après | Occupation avant | Occupation après | Verdict |
|---|---|---|---|---|---|
| P1 RX1 libre | 10 | 10 | 0,5658 s | 0,5658 s | **inchangé** |
| P2 contention 2 terminaux | 20 | 20 | 1,1315 s | 15,3933 s | changé (repli RX2) |
| P3 écart = temps d'antenne | 12 | 12 | 0,6789 s | 0,6789 s | **inchangé** |
| P4 écart = air − 1 ns | 12 | 12 | 0,6789 s | 9,2360 s | changé (voir §4.1) |
| P5 dense 12 terminaux | 96 | **56** | 5,4313 s | 14,5777 s | changé |
| P6 dense sans repli RX2 | 96 | **48** | 5,4313 s | 2,7156 s | changé |
| P7 **sans descente** | 0 | 0 | 0 s | 0 s | **inchangé** |
| P8 échelonné libre | 18 | 18 | 1,0184 s | 1,0184 s | **inchangé** |
| P9 période courte (1,5 s) | 10 | 10 | 0,5658 s | 0,5658 s | **inchangé** |

L'égalité moteur / planificateur (`plan_busy == busy`, contrôle bloquant de
`trace_events.py`) est vérifiée sur les 9 scènes, avant comme après.

### 4.1 P3 et P4 : la paire qui prouve le changement

**Avant U0.3, P3 et P4 produisaient des résultats identiques** (même empreinte
`1969e3d3669f0017`). La raison : dans P4 l'émetteur se libère 1 ns après l'ouverture, la règle à
décalage émettait donc à `ouverture + 1 ns` — si proche de P3 que les occupations coïncidaient
au nanoseconde près après arrondi des intervalles.

**Après U0.3 elles divergent** (`1969e3d3669f0017` contre une empreinte distincte, occupation
0,679 s contre 9,236 s) : en P4 la RX1 est refusée et la descente part en RX2, au SF12, sur une
durée bien plus longue.

Cette paire est la preuve la plus directe que la règle est bien devenue « à l'ouverture exacte »
et non « dès que libre ».

### 4.2 Pourquoi P5 perd 40 descentes sur 96

Avec 12 terminaux émettant toutes les 50 ms, la majorité des fenêtres RX1 s'ouvrent pendant une
émission en cours. Avant U0.3 la descente était décalée — et comme l'occupation ne cessait de
croître, la file finissait par se résorber en rejetant tout ce qui dépassait une seconde. Après
U0.3 chaque fenêtre masquée est perdue immédiatement, sauf rattrapage en RX2.

**C'est le comportement voulu par A6**, et non une régression : une émission 0,4 s après
l'ouverture de la fenêtre n'est pas une émission LoRaWAN valide, le terminal n'écoute plus.

### 4.3 Conséquence sur le demi-duplex

Les occupations RX2 étant longues (SF12), les montantes qui les chevauchent sont perdues
(`lost_gateway_busy`). C'est un effet **aval** correct du demi-duplex, pas un défaut de
placement : il apparaît dans les compteurs P5/P6 après U0.3 et il est attendu.

## 5. Invariants préservés (preuves)

| Invariant | Mesure |
|---|---|
| Empreintes gelées | `d2cb0fac…` (JSON) / `ed126d7f…` (trace) — **inchangées** |
| Vecteurs de déterminisme de la boucle fermée | `65ce329f7fbc5409…` — **bit à bit identiques** |
| Dispositions ABI | 56 structures, 502 grandeurs ; i386 compile |
| Scénario sans descente | occupation vide, empreinte `821bf06b…` identique avant/après |
| Scénario sans contention | strictement inchangé |
| Égalité moteur / planificateur | vérifiée sur les 9 scènes |
| Performance planificateur (2 000 terminaux) | **1,00 ×** la référence (budget 1,20) |
| Performance boucle fermée (2 000 terminaux) | **1,00 ×** la référence |
| Sanitizers (ASan + UBSan) | propres |
| CI (`core`, `sanitizers`, `python`) | 3/3 |

## 6. Tests discriminants

### 6.1 C++ — `core/tests/test_downlink_plan.cpp`, cas 14

Sept scènes, chacune jouée **deux fois** (planificateur par lot et planificateur incrémental du
chemin causal), avec vérification de l'égalité des deux :

| Scène | Attendu |
|---|---|
| A. RX1 libre | émission à l'ouverture exacte |
| B. RX1 occupée | repli en RX2, à l'ouverture de RX2, durée RX2 |
| C. RX1 **et** RX2 occupées | aucune émission, une seule occupation |
| D. Libération **exactement** à l'ouverture | émission autorisée, sans repli |
| E. Chevauchement d'une nanoseconde | refus en RX1, rattrapage en RX2 |
| F. Deux fenêtres séparées par un intervalle libre | les deux émises |
| G. Repli désactivé, deux fenêtres masquées | une seule occupation |

D et E ne diffèrent que d'une nanoseconde. Les préconditions sont **vérifiées par des
assertions** : si un temps d'antenne changeait au point de rendre une scène inopérante, le test
échouerait bruyamment au lieu de passer à côté.

### 6.2 C++ — `core/tests/test_radio_scheduler.cpp`

`test_place_at_fenetre_libre_entre_deux_emissions` et `test_place_at_ouvertures_dans_le_desordre`
couvrent l'entrée `place_at` elle-même, y compris hors ordre chronologique — cas où une borne de
fin ne fonctionnerait pas.

### 6.3 Python — `python/tests/test_u03_placement_a6.py`

Neuf tests : invariance des scénarios sans descente et sans contention, fenêtre masquée perdue
(non décalée), correspondance occupation/émissions acceptées, repli RX2 devenu effectif, paire
contact exact / une nanoseconde, intervalle libre, et parité cœur/oracle.

## 7. Mutations négatives

Chaque mutation réintroduit une ancienne règle ou une règle fausse ; le test doit échouer.

### C++ (9 mutations, toutes détectées)

| Id | Mutation | Résultat |
|---|---|---|
| N1 | décalage rétabli dans `DownlinkScheduler` | détectée (6 assertions) |
| N2 | décalage rétabli dans le tas (RX1) | détectée (28) |
| N3 | chevauchement réel → borne monotone | détectée (11) |
| N4 | contact compté comme chevauchement | détectée (6) |
| N5 | occupation inscrite même si refusée | détectée (15) |
| N6 | émission acceptée mais non inscrite | détectée (9) |
| N7 | durée RX2 ignorée (celle de RX1) | détectée (5) |
| N8 | repli RX2 jamais tenté | détectée (18) |
| N9 | RX1 et RX2 émises (doublon) | détectée (41) |

### Python (5 mutations, toutes détectées)

| Id | Mutation | Résultat |
|---|---|---|
| P1 | décalage rétabli (`occupé_jusqu'à`) | détectée (50 tests) |
| P2 | contact compté comme chevauchement | détectée (2) |
| P3 | occupation inscrite même si refusée | détectée (124) |
| P4 | émission acceptée mais non inscrite | détectée (120) |
| P5 | A6 désactivé (règle historique partout) | détectée (50) |

**N3 a d'abord été non détectée**, et c'était une vraie lacune : le test « intervalle libre entre
deux émissions » existait mais passait par `place()`, alors que le planificateur appelle
`place_at()`. Deux tests ont été ajoutés pour couvrir `place_at`, y compris hors ordre
chronologique. **P2 a d'abord été non détectée** côté Python : la scène du contact exact a été
ajoutée (`test_contact_exact_a_l_ouverture_n_est_pas_un_chevauchement` et sa paire).

## 8. Réserves

- **[D]** Le contact exact n'est pas un chevauchement : hypothèse de conception, aucune source
  primaire consultée ne fixe de garde inter-trames descendantes.
- **[C]** `device_missed` : atteignable dans le planificateur (observé : 9 descentes sur 10 en
  scène P9, période 1,5 s). L'affirmation « structurellement inatteignable », issue de la boucle
  fermée, **ne se généralise pas** : elle tenait au plancher d'émission `précédente_fin + 3 s`
  propre à ce chemin, pas au placement lui-même.
- **[C]** La mutation **M3 de U0.2** (`stable_sort` → `sort`, non détectée) reste signalée. Elle
  n'est pas traitée par U0.3, qui ne modifie pas l'ordre de la trace.
- **[H]** Aucune validation matérielle n'a été menée. La conformité à la norme n'est pas établie
  par ces tests : ils établissent la **fidélité** du code à la règle A6 retenue.
