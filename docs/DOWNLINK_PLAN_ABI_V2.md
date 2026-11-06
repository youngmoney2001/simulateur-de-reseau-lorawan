# ABI v2 de la planification des descentes (D3.15, jalon I0)

Statut : **implémentée**. L'entrée `lsim_plan_downlinks_v2` est **définie** dans
`core/src/c_api_plan.cpp`, **exportée** par `core/exports.map` (symbole `lsim_*`, visible dans
`liblsim_core.so`), et **liée** en Python par `python/lsim/downlink_plan.py`
(`plan_native_v2`). Elle est **capacitaire** : elle transporte et valide les paramètres de la
seconde fenêtre de réception (RX2) sans modifier ni le placement ni le temps d'antenne.

Ce document est le contrat de l'enveloppe. Il ne décrit pas le repli RX2, qui n'existe pas encore
(section 7).

## 1. Périmètre et compatibilité

- ABI v2 **additive**. `lsim_plan_downlinks_v1` et ses structures sont **inchangées** ; sa
  déclaration publique est identique au caractère près à celle du commit `a9abf64`.
- `sizeof(lsim_plan_device)` est **inchangé** : 40 octets en x86-64, 36 en i386. La structure
  n'est pas étendue en place — elle n'a aucun octet libre.
- Les anciens appels conservent **exactement** leur comportement. Le corps de la v1 est déplacé
  tel quel dans une fonction commune (`run_plan`), appelée avec `rx2 = nullptr`.
- Les empreintes historiques sont **inchangées** : JSON `d2cb0fac6c2d9950`, trace
  `ed126d7ff5aac3b0`.
- Aucun module régional, aucun module de plan, aucun scénario n'est modifié.

## 2. Structures

Tailles et décalages **mesurés par le compilateur** sur les deux cibles, puis épinglés par
`static_assert` dans `core/tests/abi_layout.cpp` (même mode opératoire que la phase F7).

### 2.1 `lsim_plan_device_rx2` (32 octets, les deux ABI)

| Champ | Type | Décalage | Sens |
|---|---|---|---|
| `rx2_hz` | `int64_t` | 0 | fréquence de la seconde fenêtre ; 0 = non renseigné ; sinon > 0 |
| `rx2_sf` | `uint32_t` | 8 | 0 = **aucun repli** (opt-in) ; sinon 7..12 |
| `rx2_bw_hz` | `uint32_t` | 12 | 0 = reprend `rx1_bw_hz` ; sinon 125000, 250000 ou 500000 |
| `reserved[2]` | `uint64_t[2]` | 16 | réservé, laisser à zéro |

### 2.2 `lsim_plan_downlinks_v2_args`

| Champ | Type | x86-64 | i386 | Obligatoire |
|---|---|---|---|---|
| `struct_size` | `uint32_t` | 0 | 0 | oui, `sizeof(lsim_plan_downlinks_v2_args)` |
| `abi_version` | `uint32_t` | 4 | 4 | oui, `LSIM_PLAN_DOWNLINKS_V2_ABI_VERSION` (1) |
| `uplinks` | `const lsim_plan_uplink*` | 8 | 8 | si `uplink_count > 0` |
| `uplink_count` | `size_t` | 16 | 12 | — |
| `devices` | `const lsim_plan_device*` | 24 | 16 | si `device_count > 0` |
| `device_count` | `size_t` | 32 | 20 | — |
| `options` | `const lsim_plan_options*` | 40 | 24 | **oui** |
| `rx2` | `const lsim_plan_device_rx2*` | 48 | 28 | non ; `NULL` = comportement v1 |
| `events` | `lsim_plan_event*` | 56 | 32 | si `event_capacity > 0` |
| `event_capacity` | `size_t` | 64 | 36 | — |
| `event_count` | `size_t*` | 72 | 40 | **oui** |
| `busy` | `lsim_interval*` | 80 | 44 | si `busy_capacity > 0` |
| `busy_capacity` | `size_t` | 88 | 48 | — |
| `busy_count` | `size_t*` | 96 | 52 | **oui** |
| `rx2_count` | `size_t` | 104 | 56 | si `rx2 != NULL` |
| `reserved[2]` | `uint64_t[2]` | 112 | 60 | réservé, laisser à zéro |

**Taille totale : 128 octets en x86-64, 76 en i386.**

### 2.3 Pourquoi `rx2_count` existe

Un pointeur ne dit pas sa longueur. Sans ce champ, la conversion aurait lu `device_count` entrées
depuis `rx2` quelle que soit la taille réelle du tableau fourni par l'appelant — une **lecture hors
bornes silencieuse**. `rx2_count` est donc vérifié **avant toute lecture** : `rx2 != NULL` impose
`rx2_count == device_count`.

## 3. Validation et codes de retour

`LSIM_STATUS_PLAN_BASE` vaut 950. Les codes sont ceux de la v1.

| Condition | Statut |
|---|---|
| `args == NULL` | 951 |
| `struct_size != sizeof(lsim_plan_downlinks_v2_args)` | 951 |
| `abi_version != LSIM_PLAN_DOWNLINKS_V2_ABI_VERSION` | 951 |
| `options`, `event_count` ou `busy_count` nul | 951 |
| `uplinks` nul avec `uplink_count > 0`, ou `devices` nul avec `device_count > 0` | 951 |
| `rx2 != NULL` et `rx2_count != device_count` | 951 |
| `rx2 == NULL` et `rx2_count != 0` | 951 |
| `outcome` d'une montante > 3 | 951 |
| index de dispositif hors bornes | 951 |
| `rx2_sf` ni nul ni dans 7..12 | 952 |
| `rx2_bw_hz` ni nul ni dans {125000, 250000, 500000} | 952 |
| `rx2_hz` négatif | 952 |
| RX1 invalide, ou temps d'antenne incalculable | 952 |
| options invalides | 953 |
| capacité insuffisante (`*event_count` / `*busy_count` donnent la taille requise) | 954 |

Aucun de ces refus n'accède à la mémoire pointée.

## 4. Sémantique RX2

### Au jalon I0 (historique)

Les paramètres RX2 étaient **transportés, validés, puis écartés** : aucun repli n'était produit, et
`lsim_plan_downlinks_v2` renvoyait exactement le résultat de la v1, avec `rx2 = NULL` comme avec
`rx2` renseigné.

### Depuis le jalon I1 (état actuel)

**Fournir une table RX2 à l'enveloppe v2, c'est demander le repli.** Le cœur l'implémente, à
l'identique de l'oracle Python (`trace_events._schedule_gateway`) :

- RX1 reste **prioritaire** : RX2 n'est tentée que sur l'échec d'une RX1, jamais en double. Une
  seule émission par descente.
- Le repli n'opère que si la fenêtre est renseignée : `rx2_sf != 0` **et** `rx2_hz != 0`.
- Il porte la fréquence, le SF et la largeur de RX2, donc un **temps d'antenne distinct** — c'est
  cette durée qui est réservée à l'émetteur.
- Ouverture à `RECEIVE_DELAY2` (2 s après la fin de la montante), fenêtre de 1 s, placement
  `début = max(ouverture, occupé_jusqu'à)`, abandon si `début − ouverture >= 1 s`.
- La file de placement est un **tas** : la RX2 naît de l'échec de la RX1 avec sa propre ouverture,
  qui peut être postérieure à celle d'autres descentes. La traiter au même endroit que la RX1 la
  placerait trop tôt. C'est l'alignement sur `GatewayArbiter`.

**La v1 et la v2 sans table ne replient jamais** : le comportement est préservé à l'identique. Le
repli reste donc **opt-in**, par le seul canal disponible sans changer l'ABI : la présence de la
table. `lsim::plan::PlanOptions::rx2_fallback` porte ce choix côté C++ ; il ne figure pas dans
`lsim_plan_options`, dont la taille est figée.

**Limitation de fidélité connue** : la sensibilité du récepteur servant à décider si la descente est
reçue reste celle du débit **RX1**, même pour une descente émise en RX2. Une trame RX2 au SF12 est
en réalité reçue avec la sensibilité SF12, bien meilleure. Les deux moteurs partagent ce
comportement ; le corriger changerait les résultats des deux côtés (voir CHANGELOG, I1).

**Dette restante** : l'exposition de la fréquence RX2 par module régional est reportée (arbitrage
S1) — aucun appelant de production ne peut encore renseigner `rx2_hz` correctement.

## 5. Côté C++ (`lsim::plan`)

Ajouts dans `core/include/lsim/downlink_plan.hpp` et `core/src/downlink_plan.cpp` :

- `struct DeviceRx2` — miroir de `lsim_plan_device_rx2`.
- Surcharge `plan_downlinks(uplinks, radios, options, rx2, events, busy)`. La signature à cinq
  arguments est conservée et délègue avec `nullptr`.
- `DownlinkScheduler` : surcharge du constructeur avec `rx2`, et surcharge
  `on_received(device, end_ns, rx2)`. La classe n'expose pas de méthode `add` ; l'arbitrage C2
  (surcharge plutôt que tableau parallèle) s'applique donc à ces deux formes. Les signatures
  d'origine sont conservées et délèguent avec « aucun RX2 ».
- `valid_rx2()` — la seule nouvelle règle de validation.

### Chemin causal (jalon I3)

`lsim::sim::CausalDownlinks` porte `const std::vector<plan::DeviceRx2>* rx2` (défaut `nullptr`),
que le moteur transmet au `DownlinkScheduler`. Les entrées C correspondantes sont
`lsim_simulate_uplinks_causal_v3` et `lsim_simulate_uplinks_causal_gw2_v3` : elles réunissent la
table RX2 **et** les frontaux, de sorte qu'une seule entrée couvre les deux extensions. Sans
aucune des deux, l'appelant reste en v1 et le résultat est identique à l'octet près.

**Pourquoi une entrée de plus plutôt qu'un champ** : la frontière C n'a pas d'argument
facultatif. Ajouter `rx2` à `lsim_plan_options` aurait changé la taille d'une structure déjà
gelée par le harnais ABI ; modifier la signature de `causal_v1` aurait rompu tous les appelants
existants. Une nouvelle entrée est le seul choix qui ne casse rien.

### Placement différé de la RX2 (jalon I3)

`DownlinkScheduler::on_received` renvoie `std::vector<Interval>` : la fenêtre de secours **n'est
pas** placée à l'appel qui la provoque, mais à son propre instant d'ouverture, une fois certain
que plus aucune descente ne peut la précéder. `drain()` purge ce qui reste en attente à la fin
de la trace. Voir le §4 et le commentaire de `on_received` dans l'en-tête.

## 6. Côté Python

`python/lsim/downlink_plan.py` :

- `DeviceRx2` (dataclasse immuable), `_CPlanDeviceRx2`, `_CPlanDownlinksV2Args`.
- `plan_native_v2(records, radios, options, rx2=None)` — même contrat que `plan_native`.
- `plan_native` est désormais un appel de `plan_native_v2` sans RX2.
- `simulate_causal(..., rx2=None)` : passer la table, c'est demander le repli côté moteur. Sans
  table **ni** frontal, l'entrée v1 reste appelée : la base est inchangée à l'octet près.

`argtypes` et `restype` sont déclarés explicitement : une erreur de typage ctypes provoquerait
sinon un segfault silencieux. Le test `test_disposition_ctypes_conforme_au_harnais_abi`
(`python/tests/test_downlink_plan_v2.py`) épingle côté Python les tailles et décalages, que le
harnais C++ ne couvrait pas.

## 7. Reporté

| Point | Raison |
|---|---|
| Exposition de `rx2_hz` par module régional | **traité en I3** : `DeviceRadio.rx2_*` est rempli par `device_radios`, et `_table_rx2` en fait une table pour le cœur. |
| Enveloppe causale (variante C : pointeurs typés exclusifs) | jalon I4 |
| Multi-passerelles (trajectoire T2) | jalon I5 |

## 8. Vérifications

Exécutées sur la reconstruction du jalon (base `a9abf64`) :

| Contrôle | Résultat |
|---|---|
| Suite C++ | 685 874 / 685 874 (dont 592 nouvelles) |
| Suite Python | 2 103 passed, 1 skipped, 16 subtests (dont 31 nouveaux) |
| Parité `test_downlink_plan_parity.py` | 114 passed |
| Harnais ABI x86-64 | 55 structures / 477 grandeurs |
| Harnais ABI i386 | compilation OK |
| Symboles `lsim_*` | 98, soit **+1** (`lsim_plan_downlinks_v2`), **0** retiré |
| Empreintes | `d2cb0fac6c2d9950` et `ed126d7ff5aac3b0` inchangées |

État après les jalons I1 (repli), I3/C3 (placement différé), I3/C4 (sensibilité par fenêtre) et
I3/C1-C2 (table RX2 sur le chemin causal) :

| Contrôle | Résultat |
|---|---|
| Suite C++ | 685 924 / 685 924 |
| Suite Python | 2 167 passed, 1 skipped, 16 subtests |
| Harnais ABI x86-64 | 55 structures / 477 grandeurs — inchangé |
| Symboles `lsim_*` | 100, soit **+2** (`lsim_simulate_uplinks_causal_v3`, `..._gw2_v3`), **0** retiré |
| Empreintes | inchangées |
