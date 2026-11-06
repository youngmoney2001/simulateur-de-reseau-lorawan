# I5-b — le SF de RX1 dans la boucle fermée : un défaut latent, pas un défaut actif

Lot distinct d'I5-a, conformément à l'arbitrage rendu à l'audit
(`docs/I5_AUDIT_MULTI.md` §9, question 2). Rédigé avant toute modification, comme toujours.

## 1. Le défaut

`docs/I5_AUDIT_MULTI.md` §3.3 : « le chemin **mono / boucle fermée** a le même défaut sur le SF
mais pas sur la bande ».

La bande est en effet déjà correcte : `rad.rx1_bw_hz` provient de la table radio et n'est jamais
écrasé. Seul le SF l'est, à deux endroits :

```cpp
// core/src/engine.cpp:2013
plan::DeviceRadio rad = radios[d];
...
rad.rx1_sf = ta.sf;                              // :2029  <- écrase la valeur reçue
SimTime air_rx1 = 0;
if (plan::downlink_airtime_ns(rad, base + fopts, air_rx1) != lora::Status::Ok) { ... }
rad.rx1_sf = kLoopRx2Sf;                         // :2035  <- RX2, SF12 en dur

// core/src/engine.cpp:2272
rad.rx1_sf = rx2 ? kLoopRx2Sf : ta.sf;           // <- même écrasement, côté sensibilité
...
if (lora::receiver_sensitivity_dbm(rad.rx1_sf,
        static_cast<lora::Bandwidth>(rad.rx1_bw_hz), ...)   // :2280
```

Le point de droit : le moteur **reçoit** une table de radios où `rx1_sf` est renseigné, et la
**jette** pour lui substituer le SF montant. C'est un défaut de couche, indépendamment de la
valeur transportée — le moteur n'a pas à savoir quelle région produit `rx1_sf`.

## 2. Mesure décisive : le défaut est latent

Avant de corriger, j'ai cherché s'il se manifeste. Il ne se manifeste pas.

Test parcourant **toutes** les régions et **tous** les DR montants à 125 kHz :

    for region in (EU868, US915, AU915, AS923, IN865, KR920, RU864):
        for dr, (sf, bw, _) in enumerate(plan.dr_table()):
            if bw != 125: continue
            sf_rx1 = SF de plan.rx1(dr, canal)
            si sf_rx1 != sf: signaler

Résultat : **aucune région, aucun DR**. `plan.rx1()` conserve le SF ; seule la bande change
(125 kHz → 500 kHz pour US915 et AU915).

La cause est dans `_radio` (`python/lsim/trace_events.py:298`) : le `rx1_sf` du profil découle
du DR résolu par la table régionale, et à `RX1DROffset = 0` — la valeur par défaut imposée par
RP002 §3.3, confirmée par lecture directe — les profils rendent le même SF.

**Conséquence** : avec les profils livrés, `radio.rx1_sf == ta.sf` dans tous les cas. La ligne
fautive produit donc aujourd'hui **exactement le bon résultat**, pour une mauvaise raison.

## 3. Différence avec I5-a, à ne pas confondre

| | Chemin multi (I5-a) | Boucle fermée (I5-b) |
|---|---|---|
| SF | codé au SF montant | codé au SF montant |
| Bande | **codée en dur à 125 kHz** | lue dans la table (correcte) |
| Effet mesuré | **actif** : 4,00x sur US915/AU915 | **latent** : nul aujourd'hui |
| Nature | erreur numérique | erreur de couche |

I5-a corrigeait une erreur qui faussait les résultats. I5-b corrige une erreur qui ne les
fausse pas encore, mais qui deviendrait active dès qu'un profil produirait un `rx1_sf`
différent — par exemple un `RX1DROffset` non nul, ou un profil AU915 corrigé si la divergence
relevée dans `docs/RP002_1_0_5_RELEVE.md` §4 tournait contre le profil actuel.

## 4. Question ouverte, volontairement non tranchée ici

Une divergence a été observée entre la cartographie RX1 de l'AU915 **telle qu'extraite de
RP002-1.0.2** (DR0 → DR10, soit SF12 → SF10) et le profil Python (DR0 → `SF12BW500`, soit DR8).
Elle n'est **pas** tranchée : la table 46 de RP002-1.0.5 n'a pas pu être lue (au-delà de la
limite de 30 pages du parseur), et l'extrait 1.0.2 est bruité.

Cela ne bloque pas I5-b, et c'est le point important : **la correction du moteur ne dépend pas
de la réponse**. Quelle que soit la bonne valeur, le moteur doit utiliser celle qu'on lui
transmet. Vérifier les profils est un lot distinct (audit des profils régionaux).

## 5. Modifications proposées

### 5.1 Cœur C++ — deux sites

Remplacer, dans `core/src/engine.cpp` :

- `:2029` — `rad.rx1_sf = ta.sf;` par l'utilisation directe de `radios[d].rx1_sf` ;
- `:2272` — `rad.rx1_sf = rx2 ? kLoopRx2Sf : ta.sf;` par `radios[dl.device].rx1_sf` pour RX1,
  en laissant RX2 sur `kLoopRx2Sf`.

### 5.2 Validation à ajouter

La boucle fermée **ne valide pas** les radios : elle vérifie seulement `radios != nullptr`
(`engine.cpp:1557`). Dès lors qu'on utilise `rx1_sf`, il faut le contrôler, comme l'a fait I5-a
pour le chemin multi (`:1082-1083`) :

- `rx1_sf` dans `[7, 12]` ;
- `rx1_bw_hz` dans `{125 000, 250 000, 500 000}`.

Sans cela, une table invalide ne serait plus masquée par l'écrasement.

### 5.3 RX2 : hors périmètre

`kLoopRx2Sf = 12` (`:1435`) est un SF12 en dur, sans bande associée. Le corriger demanderait
une table RX2 dans la boucle fermée — qui n'en a pas. Lot distinct, comme I3/C4 et comme
l'écart n°2. Noté, pas traité.

## 6. Propriétés attendues

**P-B-1** — Sans plan régional, aucun changement : `_radio` rend `rx1_sf = sf` (le SF montant)
et `rx1_bw_hz = 125 000`, donc la valeur utilisée est identique à l'ancienne.

**P-B-2** — Avec un plan régional, aucun changement non plus, compte tenu de la mesure du §2 :
tous les profils livrés conservent le SF.

**P-B-3** — La correction devient porteuse dès qu'un profil écarte le SF : un test doit donc
vérifier le comportement **sur une table construite exprès**, pas sur les profils.

**P-B-4** — Une table invalide est refusée, jamais corrigée en silence (bbb3).

## 7. Tests

| Id | Propriété |
|---|---|
| T-B-1 | Parité bit à bit sur les scénarios existants (les 15 échecs connus inchangés) |
| T-B-2 | Tous les profils livrés : `rx1_sf` de la table == SF montant (documente la latence) |
| T-B-3 | Table exprès avec `rx1_sf` écarté : le temps d'antenne RX1 suit la table |
| T-B-4 | Table exprès : la sensibilité de réception descendante suit `rx1_sf` de la table |
| T-B-5 | `rx1_sf` hors `[7,12]` ⇒ refus ; `rx1_bw_hz` hors `{125k, 250k, 500k}` ⇒ refus |
| T-B-6 | Mutation : rétablir `ta.sf` doit faire échouer T-B-3 et T-B-4 |

T-B-3 et T-B-4 sont les seuls qui donnent un effet mesurable. Sans eux, le lot n'aurait aucun
test discriminant — le piège exact rencontré en I5-a, où deux tests ont d'abord été écrits
vacuous.

## 8. Ordre d'exécution

1. Cœur C++ : deux sites + validation (§5.1, §5.2)
2. Tests C++ (T-B-3 à T-B-6)
3. Non-régression : C++ 690 127 · ctest 1/1 · Python 2477 / 15
4. Mutations
5. Bilan

Aucune modification d'ABI : le chemin emprunté ne change pas, seules les valeurs lues
diffèrent. À vérifier (`nm -D` : 103 symboles, 0 retiré).
