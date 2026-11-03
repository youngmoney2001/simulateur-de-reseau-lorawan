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

## 4. Sémantique RX2 au jalon I0

**Les paramètres RX2 sont transportés, validés, puis écartés.** Ils ne modifient ni le placement ni
le temps d'antenne : **aucun repli RX2 n'est produit**, quelles que soient les valeurs fournies.

Trois conséquences, toutes voulues :

1. Le repli reste **opt-in** : `rx2_sf = 0` signifie « aucune descente RX2 ». Comme aucun repli
   n'est implémenté, la condition est satisfaite de façon triviale.
2. `lsim_plan_downlinks_v2` renvoie **exactement** le résultat de `lsim_plan_downlinks_v1` pour les
   mêmes entrées — avec `rx2 = NULL` **et** avec `rx2` renseigné. C'est le cœur des tests de parité.
3. Le champ est aujourd'hui **inutilisé en pratique** : l'exposition de la fréquence RX2 par module
   régional est reportée (arbitrage S1), donc aucun appelant ne peut renseigner `rx2_hz`
   correctement. C'est une dette assumée, pas un oubli.

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

## 6. Côté Python

`python/lsim/downlink_plan.py` :

- `DeviceRx2` (dataclasse immuable), `_CPlanDeviceRx2`, `_CPlanDownlinksV2Args`.
- `plan_native_v2(records, radios, options, rx2=None)` — même contrat que `plan_native`.
- `plan_native` est désormais un appel de `plan_native_v2` sans RX2.

`argtypes` et `restype` sont déclarés explicitement : une erreur de typage ctypes provoquerait
sinon un segfault silencieux. Le test `test_disposition_ctypes_conforme_au_harnais_abi`
(`python/tests/test_downlink_plan_v2.py`) épingle côté Python les tailles et décalages, que le
harnais C++ ne couvrait pas.

## 7. Reporté

| Point | Raison |
|---|---|
| Le repli RX2 (placement) | jalon suivant. Il **changera le placement**, ce que le critère I0 interdit. |
| Exposition de `rx2_hz` par module régional | arbitrage S1 |
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
