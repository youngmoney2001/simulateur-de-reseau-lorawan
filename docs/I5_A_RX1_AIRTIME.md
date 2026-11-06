# I5-a — Temps d'antenne et sensibilité des descentes du moteur multi-passerelles

Conception, avant toute ligne de code. Fait suite à `docs/I5_AUDIT_MULTI.md` (écart n°1) et à la
décision de traiter **d'abord** cet écart, en lot borné.

---

## 1. Objet

Corriger le calcul du temps d'antenne **descendant** et de la **sensibilité de réception
descendante** dans `simulate_uplinks_multi_downlinks`, qui reposent aujourd'hui sur deux
hypothèses fausses : le débit RX1 égale le SF montant, et la bande vaut 125 kHz.

Ne pas toucher au temps d'antenne montant, ni au périmètre fonctionnel (boucle fermée
mono-passerelle), ni au chemin `plan`.

---

## 2. Les trois sites du défaut

Tous dans `core/src/engine.cpp`, tous dans `simulate_uplinks_multi_downlinks`.

### 2.1 Site 1 — bande du temps d'antenne descendant, codée en dur

```cpp
// core/src/engine.cpp:966-971
// Airtime d'un downlink au débit RX1 (= SF de l'uplink, BW 125 kHz), ...
SimStatus downlink_airtime(std::uint8_t sf, std::uint32_t payload_bytes, SimTime& out) {
    rc.spreading_factor = sf;
    rc.bandwidth = lora::Bandwidth::Bw125kHz;   // <- littéral
```

### 2.2 Site 2 — le SF employé est le SF montant

```cpp
// core/src/engine.cpp:1163
if (downlink_airtime(ta.sf, payload, air) != SimStatus::Ok) return SimStatus::InvalidInput;
std::uint8_t sf_used = ta.sf;
```

`ta.sf` est posé en `:1082` (`tx.sf = d.spreading_factor;`), donc le SF **montant**. Le repli RX2
(`:1185`) prend bien son SF de `rule.rx2_sf`, mais retombe sur le site 1 pour la bande.

### 2.3 Site 3 — la sensibilité de réception descendante, elle aussi en 125 kHz

```cpp
// core/src/engine.cpp:1209
if (lora::receiver_sensitivity_dbm(sf_used, lora::Bandwidth::Bw125kHz, s) != lora::Status::Ok) {
```

Ce site est **indépendant** des deux autres et n'avait pas été relevé par l'audit : la décision
« la descente est-elle reçue ? » est prise avec un seuil de sensibilité calculé à la mauvaise
bande. Le corriger change le taux de livraison, pas seulement l'occupation.

### 2.4 Gravité (mesurée — voir `I5_AUDIT_MULTI.md` §3.2)

Facteur d'erreur du temps d'antenne réservé : **0,04x à 96x** selon le DR RX1 réellement imposé.
Exact **uniquement** sur la diagonale « RX1 = SF montant à 125 kHz ». La sensibilité (site 3) suit
la même loi : un seuil calculé à 125 kHz est trop pessimiste en 500 kHz d'environ 6 dB.

---

## 3. Ce qui manque : le chemin multi ne reçoit aucune table radio

C'est le fait structurant. `simulate_uplinks_multi_downlinks` (`engine.hpp:728`) reçoit
`const EndDeviceSpec* devices` ; `EndDeviceSpec` (`engine.hpp:116-131`) ne porte que
`spreading_factor` (montant) et `payload_bytes`. **Aucun** `rx1_sf`, **aucun** `rx1_bw_hz`.

Aux deux entrées C (`c_api.h:571` et `:1820`), aucune table radio non plus — contrairement à
`lsim_simulate_uplinks_causal_v3` (`c_api.h:1687`) qui prend `const lsim_plan_device* radios`.

Côté Python, les données **existent déjà** et sont calculées pour rien :
`build_multi_trace` fait `radios = device_radios(scenario)` (`trace_events.py:1586`) puis appelle
`simulate_multi_downlinks(...)` (`simulator.py:705`) dont la signature n'accepte que `device_rf`
et `gateway_rf` — les **frontaux**, qui sont une autre grandeur.

**La correction est donc d'abord un problème de transport, pas un problème de formule.**

### 3.1 Les types existent déjà

| Donnée | Type C existant | Champ | Source Python |
|---|---|---|---|
| SF et bande de RX1 | `lsim_plan_device` | `rx1_sf`, `rx1_bw_hz` | `DeviceRadio.rx1_sf`, `.rx1_bw_hz` |
| SF et bande de RX2 | `lsim_plan_device_rx2` | `rx2_sf`, `rx2_bw_hz` | `DeviceRadio.rx2_sf`, `.rx2_bw_hz` |

`lsim_plan_device_rx2` vient d'I3 ; Python remplit `rx2_bw_hz` en le **lisant du profil
régional** (`trace_events.py:330`). Aucune nouvelle structure n'est à inventer.

---

## 4. Conception

### 4.1 Règle de comportement

Passer une table de radios à l'entrée multi, c'est **demander** la fidélité RX1/RX2. Ne pas la
passer conserve le comportement actuel **à l'identique**. Exactement la convention déjà établie
pour la table `rx2` d'I3 : « compter des entrées, c'est demander le repli ».

Aucune modification silencieuse des entrées existantes : `lsim_simulate_uplinks_multi_dl` et
`_v2` gardent leurs résultats **au bit près**.

### 4.2 Trois options pour la forme de l'entrée

| | Option | Coût | Avantage | Inconvénient |
|---|---|---|---|---|
| **A** | Nouvelle entrée plate `_multi_dl_v3` avec `radios` + `rx2` ajoutés | faible | précédent `causal_v3` | 4 entrées à terme : {sans, avec radios} × {sans, avec frontal} |
| **B** | Enveloppe `lsim_multi_dl_args` à pointeurs typés | moyen | une seule entrée, extensible ; variante retenue en I4 | nouvelle structure, harnais ABI à étendre |
| **C** | Ajouter `rx1_sf`/`rx1_bw_hz` à `lsim_end_device` | nul | rien à transporter | **refusé** : change la taille d'une structure utilisée par des dizaines d'entrées — rupture d'ABI déguisée en extension |

**Recommandation : option B.** C'est la variante déjà retenue en I4 pour une raison qui s'applique
ici mot pour mot : le cartésien des tables optionnelles. Le multi en a deux aujourd'hui
(frontaux) et en aurait quatre avec les radios. I4 a tranché ce exact problème.

**À arbitrer avant d'écrire du code** : A est proportionné si l'on juge que le multi n'aura
jamais d'autre table optionnelle. B est proportionné si l'on anticipe (fréquence RX2 par
dispositif, contraintes de charge N par fenêtre comme en I6-c, …). **La question est ouverte.**

### 4.3 Contrat de l'enveloppe (option B)

```c
typedef struct lsim_multi_dl_args {
    uint32_t struct_size;
    uint32_t abi_version;                 /* LSIM_MULTI_DL_ABI_VERSION = 1 */
    const lsim_end_device*   devices;     /* obligatoire                */
    size_t                   device_count;
    const lsim_gateway*      gateways;    /* obligatoire, 1..64         */
    size_t                   gateway_count;
    const lsim_propagation*  prop;        /* obligatoire                */
    const lsim_downlink_rule* rule;       /* obligatoire                */
    const lsim_environment*  env;         /* NULL admis                 */
    const lsim_plan_device*  radios;      /* NULL : comportement actuel */
    size_t                   radio_count; /* device_count si non NULL   */
    const lsim_plan_device_rx2* rx2;      /* NULL : repli inactif       */
    size_t                   rx2_count;
    const lsim_device_rf*    device_rf;   /* NULL admis (frontal)       */
    size_t                   device_rf_count;
    const lsim_gateway_rf*   gateway_rf;  /* NULL admis (frontal)       */
    size_t                   gateway_rf_count;
    const int64_t*           dl_ready_ns; /* NULL admis                 */
    /* sorties … */
    uint64_t reserved[2];                 /* doit être nul (O1, bbb3)   */
} lsim_multi_dl_args;
```

Règles, calquées sur I6-c et I4 :

- chaque table non nulle annonce son compte, vérifié **avant toute lecture** ;
- `struct_size`, `abi_version` et `reserved` nul validés d'abord (O1, bbb3) ;
- `radios` non nul ⇒ `radio_count == device_count`, sinon refus ;
- une table non nulle dont le SF est hors 7..12 ou la bande hors {125k, 250k, 500k} ⇒ refus
  (`InvalidRadio`), jamais de repli sur une valeur par défaut ;
- `rx2` non nul ⇒ le repli est demandé et évalué avec `rx2_sf`/`rx2_bw_hz` **de la table**, et non
  plus avec `rule.rx2_sf` à 125 kHz. Conflit entre `rule.rx2_sf` et la table ⇒ refus explicite,
  pas de précédence implicite. **Point à trancher** : ou bien la table prime, ou bien l'on refuse.

### 4.4 Le calcul corrigé

```
air_rx1 = airtime(radios[d].rx1_sf, radios[d].rx1_bw_hz, payload)
air_rx2 = airtime(rx2[d].rx2_sf,    rx2[d].rx2_bw_hz,    payload)
sens    = receiver_sensitivity_dbm(sf_utilisé, bande_utilisée)
```

Le SF et la bande employés sont **ceux de la fenêtre réellement utilisée** — jamais ceux de
l'uplink, jamais une constante. C'est la règle R-N1 d'I6-c, appliquée au chemin multi.

---

## 5. Modifications prévues

| Fichier | nature |
|---|---|
| `core/src/engine.cpp` | `downlink_airtime` prend une bande ; `simulate_uplinks_multi_downlinks` surcharge avec radios + rx2 ; trois sites corrigés |
| `core/include/lsim/engine.hpp` | surcharge de `simulate_uplinks_multi_downlinks` ; `MultiDownlinkRule` inchangé |
| `core/include/lsim/c_api.h` | `lsim_multi_dl_args`, `LSIM_MULTI_DL_ABI_VERSION`, `lsim_simulate_uplinks_multi_dl_env` |
| `core/src/c_api_ext.cpp` | entrée à enveloppe + validations |
| `core/tests/abi_layout.cpp` | tables i386 / x86-64 de la nouvelle structure |
| `python/lsim/_native.py`, `simulator.py` | pont, nouvelle fonction `simulate_multi_downlinks_env` |
| `python/lsim/trace_events.py` | `build_multi_trace` passe enfin les `radios` qu'il calcule déjà |
| `python/tests/test_multi_dl_rx1.py` | tests du lot |

---

## 6. Tests prévus

| Id | Propriété |
|---|---|
| T-A-1 | Sans table de radios, les résultats sont **identiques** à l'entrée `_multi_dl` actuelle (empreintes) |
| T-A-2 | Avec `radios` où RX1 = (SF montant, 125 kHz), résultats identiques — la diagonale de la table de sensibilité |
| T-A-3 | Avec `radios` où RX1 = (SF_x, 500 kHz), le temps d'antenne réservé est celui de la table de sensibilité, mesuré |
| T-A-4 | La sensibilité de réception descendante suit la bande de la fenêtre (site 3), pas 125 kHz |
| T-A-5 | `struct_size`, `abi_version`, `reserved` non nul ⇒ refus |
| T-A-6 | Comptes incohérents (`radio_count` ≠ `device_count`) ⇒ refus, sans lecture |
| T-A-7 | SF hors 7..12 ou bande hors {125k, 250k, 500k} ⇒ `InvalidRadio`, aucun repli |
| T-A-8 | Conflit `rule.rx2_sf` / table `rx2` ⇒ refus (ou précédence, selon l'arbitrage §4.3) |
| T-A-9 | Parité : `build_multi_trace` avec et sans table produit les même événements quand RX1 = (SF montant, 125 kHz) |
| T-A-10 | Mutation : forcer la bande à 125 kHz doit faire échouer T-A-3 et T-A-4 |

---

## 7. Ordre d'exécution

1. Cœur C++ (surcharge, trois sites).
2. Frontière C (enveloppe, validations).
3. Harnais ABI.
4. Pont Python + `build_multi_trace`.
5. Tests T-A-1…T-A-10.
6. Non-régression : suite C++ et suite Python, comparées à `6615536`.
7. Mutations.

---

## 8. Commandes

```
cmake --build build --parallel
ctest --test-dir build --output-on-failure
PYTHONPATH=python LSIM_LIBRARY=<chemin>/liblsim_core.so pytest -q python/tests
```

Contrôles ABI : **+1 symbole**, **0 retiré** ; structures existantes à taille constante.

---

## 9. Hors périmètre

| Exclu | Pourquoi |
|---|---|
| Écart n°2 — boucle fermée multi-passerelles | lot distinct, décision reportée |
| Le défaut équivalent sur le SF dans le chemin mono (`engine.cpp:1943`) | touche les deux moteurs ; changerait des résultats existants — lot distinct, comme I3/C4 |
| Fréquence RX2 dans le multi (non modélisée aujourd'hui) | lot distinct |
| Contraintes de charge N dans le chemin multi | I6-c a traité le chemin `plan` seulement |

---

## 10. Réserves

1. **Aucune affirmation régionale.** Ce lot transporte le DR des fenêtres ; il ne décide pas
   lequel impose chaque région. Produire les bonnes tables reste à la charge de l'appelant
   (Python les a déjà via `device_radios`, qui les lit du profil régional — `trace_events.py:330`).
2. **Le site 3 change le taux de livraison**, pas seulement l'occupation. Toute comparaison
   avant/après devra séparer les deux effets.
3. **L'option A ou B n'est pas tranchée** (§4.2). La recommandation va à B par cohérence avec I4,
   mais A reste défendable si l'on borne le nombre de tables optionnelles.
4. **Le conflit `rule.rx2_sf` / table `rx2` n'est pas tranché** (§4.3).
