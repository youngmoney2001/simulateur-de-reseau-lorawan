# I6-c — Parité C++ : validation de N par fenêtre dans le cœur

**Date** : 2026-11-06 · **Branche** : `arena/fdc94521-simulateur-de-reseau-lorawan`
**Base** : `5456193` · **Statut** : **plan soumis à autorisation, aucune ligne écrite**

## 1. Objet

Porter dans le cœur C++ la règle d'éligibilité par fenêtre (**R-N1…R-N4**) déjà implémentée et
vérifiée côté Python (`72fc6cb`), afin que les deux moteurs coïncident.

### 1.1 La divergence, mesurée

Occupation passerelle, cœur C++ (`plan_native_v2`) contre oracle Python
(`_schedule_gateway_with_motifs`), sur les sept scènes recalibrées de D3.15-R :

| Région | Charge | N(RX2) | Occupation C++ | Occupation Python | |
|---|---:|---:|---:|---:|---|
| EU868 | 40 | 51 | 380 | 380 | identique |
| EU868 | **120** | 51 | **260** | **0** | le cœur émet ce qui est intransportable |
| US915 | 40 | 53 | 260 | 260 | identique |
| US915 | **120** | 53 | **220** | 200 | divergent |
| AS923 | 40 | 51 | 407 | 407 | identique |
| AS923 | **120** | 51 | **211** | 371 | divergent |
| AU915 | 40 | 53 | 220 | 220 | identique |
| AU915 | **120** | 53 | **240** | 220 | divergent |
| IN865 | 40 | 51 | 407 | 407 | identique |
| IN865 | **120** | 51 | **211** | 371 | divergent |
| KR920 | 40 | 51 | 113 | 113 | identique |
| KR920 | **120** | 51 | **54** | **0** | le cœur émet ce qui est intransportable |
| RU864 | 40 | 51 | 620 | 620 | identique |
| RU864 | **120** | 51 | **320** | **0** | le cœur émet ce qui est intransportable |

**7/7 identique à charge conforme, 7/7 divergent au-delà de N.** Le cœur applique une partie de
la règle (il refuse le repli quand RX2 ne peut pas porter) mais pas la règle entière : il ne
refuse pas la RX1, et il ne classe pas l'échec.

Le nombre de sauts descendants, lui, ne diverge jamais (440/440, 280/280…) : l'écart porte sur
**l'occupation**, donc sur ce que la passerelle émet réellement.

### 1.2 Ce que la parité exige

Reproduire à l'identique le comportement de `_schedule_gateway_with_motifs` (`trace_events.py`,
l. 691-780) :

- **R-N1** — chaque fenêtre est validée contre le N **de son propre DR**, jamais contre celui de
  l'uplink ni contre celui de l'autre fenêtre.
- **R-N2** — une fenêtre inéligible n'est **jamais demandée** : elle ne réserve rien et n'occupe
  pas l'émetteur. C'est la différence entre « refusé » et « demandé puis manqué ».
- **R-N3** — l'inéligibilité d'une fenêtre ne clôt pas l'examen : RX1 inéligible, RX2 reste
  examinable, et réciproquement.
- **R-N4** — aucune validation anticipée ne modifie la chronologie.

## 2. Deux faits qui bornent la conception

### 2.1 Le chemin plan n'a pas de FOpts

`core/src/downlink_plan.cpp` ne connaît pas les FOpts (vérifié : aucune occurrence). La grandeur
comparée à N y est donc `options.downlink_payload_bytes`, sans le terme `|FOpts|` que l'oracle
Python ajoute quand un MAC est planifié.

La parité est néanmoins **bien définie** : `plan_native_v2` et les tests D3.15-R passent
`mac=None`, donc `fopts = b""` et `charge_contrainte = downlink_payload_bytes`. Toute
comparaison de parité doit rester dans ce régime — sinon elle comparerait deux grandeurs
différentes.

### 2.2 Seules les descentes applicatives sont soumises à N

`trace_events.py:641` : `soumis_a_n = kind == "downlink" and content in ("data", "data_ack")`.
Les ACK et les Join-Accept **ne sont pas** soumis à N (garde-fou 14 : ne pas confondre les
contraintes du Join-Accept et celles des charges applicatives).

Côté C++ (`downlink_plan.cpp:181-190`), le pendant est :
`queued = downlink_every > 0 && accepted[device] % downlink_every == 0`, puis
`content = confirmed_uplinks ? DataAck : Data` si `queued`, sinon `AckOnly`.

**La règle ne s'applique donc qu'à `content ∈ {Data, DataAck}`**, jamais à `AckOnly`.

## 3. Conception — arbitrages déjà rendus, aucune question nouvelle

| Arbitrage | Disposition retenue |
|---|---|
| **O1** — option B | extension **versionnée explicitement activée** ; aucun `reserved` réaffecté |
| **bbb3** — découverte d'API | échec **explicite**, jamais de repli silencieux |
| **bbb5** — contrat `limits` | `NULL` **rejeté** ; aucune sentinelle ; absence de contrainte réservée à v2 |
| précédent I3 | « une entrée de plus plutôt qu'un champ » |

Le pendant exact de ce qui a été fait pour RX2 en `lsim_plan_downlinks_v2` : une **table
parallèle** portée par un **nouveau point d'entrée**. Passer la table = demander la validation
N ; appeler v2 = comportement inchangé à l'octet près.

### 3.1 Nouvelle structure de limites

```c
#define LSIM_PLAN_DOWNLINKS_V3_ABI_VERSION 1

typedef struct lsim_plan_device_limits {
    int32_t rx1_max_payload;  /* N du DR de RX1 ; 0..242                              */
    int32_t rx2_max_payload;  /* N du DR de RX2 ; 0..242                              */
    uint64_t reserved[2];
} lsim_plan_device_limits;
```

Aucune sentinelle : les deux champs sont des N **effectifs**, validés dans `[0, 242]` à la
frontière C. « Pas de contrainte » ne s'exprime pas par une valeur magique mais en **appelant
v2**.

### 3.2 Nouvelle enveloppe

```c
typedef struct lsim_plan_downlinks_v3_args {
    uint32_t struct_size;   /* sizeof(lsim_plan_downlinks_v3_args), obligatoire       */
    uint32_t abi_version;   /* LSIM_PLAN_DOWNLINKS_V3_ABI_VERSION, obligatoire        */
    const lsim_plan_uplink*   uplinks;         size_t uplink_count;
    const lsim_plan_device*   devices;         size_t device_count;
    const lsim_plan_options*  options;         /* obligatoire                          */
    const lsim_plan_device_rx2*    rx2;        size_t rx2_count;
    const lsim_plan_device_limits* limits;     /* obligatoire, non NULL                */
    size_t limits_count;
    lsim_plan_event*  events;  size_t event_capacity;  size_t* event_count;
    lsim_interval*    busy;    size_t busy_capacity;   size_t* busy_count;
    uint64_t reserved[2];
} lsim_plan_downlinks_v3_args;

LSIM_API int32_t lsim_plan_downlinks_v3(const lsim_plan_downlinks_v3_args* args);
```

### 3.3 Refus explicites (bbb3)

Tous renvoient `LSIM_STATUS_PLAN_BASE + 1` (InvalidInput), jamais de repli silencieux vers v2 :

| Condition | Refus |
|---|---|
| `args == NULL` | oui |
| `struct_size != sizeof(v3_args)` | oui |
| `abi_version != 1` | oui |
| **`limits == NULL`** | **oui** — l'absence de contrainte s'exprime en appelant v2 |
| `limits_count != device_count` | oui |
| `rx1_max_payload` ou `rx2_max_payload` hors `[0, 242]` | oui |

## 4. Modifications prévues

### 4.1 C++ cœur

**`core/include/lsim/downlink_plan.hpp`**

| Ajout | Nature |
|---|---|
| `struct DeviceLimits { std::int32_t rx1_max_payload; std::int32_t rx2_max_payload; }` | miroir de `lsim_plan_device_limits` |
| surcharge `plan_downlinks(uplinks, radios, options, rx2, limits, events, busy)` | nouvelle forme |
| surcharge `DownlinkScheduler(radios, options, rx2, limits)` | chemin causal incrémental |

Les formes existantes sont **conservées et délèguent** avec `limits = nullptr` — comportement
inchangé à l'octet près.

**`core/src/downlink_plan.cpp`** — application des règles R-N1…R-N4 :

1. au moment de construire la demande, si `content ∈ {Data, DataAck}` et
   `downlink_payload_bytes > limits[device].rx1_max_payload` ⇒ **aucune demande RX1** (R-N2) ;
2. si RX2 est demandée et `downlink_payload_bytes > limits[device].rx2_max_payload` ⇒
   **aucune demande RX2** (R-N2, R-N3) ;
3. si RX1 est inéligible mais RX2 éligible ⇒ RX2 est demandée directement (R-N3), sans que RX1
   n'ait rien réservé ;
4. aucune validation n'a lieu avant l'instant de la demande (R-N4).

**Aucun changement** à `PlanStatus` : les valeurs 0-3 suffisent, et les geler évite une
cassure ABI.

### 4.2 Frontière C

**`core/include/lsim/c_api.h`** : les deux structures et le point d'entrée (§3).

**`core/src/c_api_plan.cpp`** : `lsim_plan_downlinks_v3`, validations du §3.3, puis appel de
`run_plan` étendu.

**`core/tests/abi_layout.cpp`** : ajout des deux structures aux **deux** tables (x86-64 et
i386) — c'est la source de vérité partagée par `test_abi_v3_prep.cpp`.

### 4.3 Python

**`python/lsim/downlink_plan.py`**

| Ajout | Objet |
|---|---|
| `DeviceLimits` (dataclasse immuable) | miroir Python |
| `_CPlanDeviceLimits`, `_CPlanDownlinksV3Args` | structures ctypes, `argtypes`/`restype` explicites |
| `plan_native_v3(records, radios, options, rx2=None, limits=None)` | même contrat que `plan_native_v2` |

`plan_native` et `plan_native_v2` ne changent pas.

## 5. Tests prévus

| # | Test | Objet |
|---|---|---|
| **T-C-1** | `test_disposition_ctypes_conforme_au_harnais_abi` (étendu) | tailles et décalages des deux structures, côté Python |
| **T-C-2** | refus : `limits == NULL` rejeté | bbb3, bbb5 |
| **T-C-3** | refus : `limits_count != device_count` | lecture bornée |
| **T-C-4** | refus : N hors `[0, 242]`, `struct_size` et `abi_version` faux | validation de frontière |
| **T-C-5** | **parité sur les 7 scènes D3.15-R à charge conforme** | occupation et sauts identiques |
| **T-C-6** | **parité sur les 7 scènes à charge 120** | les 7 divergences du §1.1 disparaissent |
| **T-C-7** | non-régression v1 / v2 | résultat identique à l'octet près |
| **T-C-8** | `AckOnly` jamais refusé pour capacité | garde-fou 14 |
| **T-C-9** | R-N2 : une fenêtre inéligible ne réserve rien | l'occupation ne la compte pas |
| **T-C-10** | R-N3 : RX1 inéligible, RX2 éligible ⇒ RX2 émise | poursuite de l'examen |

## 6. Ordre d'exécution

1. `downlink_plan.hpp` + `downlink_plan.cpp` (cœur, avec les règles).
2. `c_api.h` + `c_api_plan.cpp` (frontière C et validations).
3. `abi_layout.cpp` (deux tables) + `test_abi_v3_prep.cpp`.
4. `downlink_plan.py` (binding).
5. Tests T-C-1 à T-C-10.
6. Vérification d'absence de régression.
7. Rejouer les 91 tests D3.15-R.

## 7. Commandes de vérification

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DLSIM_WARNINGS_AS_ERRORS=ON
cmake --build build --parallel
ctest --test-dir build --output-on-failure          # attendu : 1/1

PYTHONPATH=python LSIM_LIBRARY=<chemin>/liblsim_core.so \
    pytest -q python/tests                          # attendu : aucun test cassé
```

Contrôles ABI : **+1 symbole** (`lsim_plan_downlinks_v3`), **0 retiré** ; les structures
existantes gardent tailles et décalages.

## 8. Hors périmètre d'I6-c

| Exclu | Renvoi |
|---|---|
| I6-b2 — offsets RX1 1 à 5, dwell time AS923 | lot distinct |
| I4 — enveloppe causale (variante C) | lot distinct |
| I5 — multi-passerelles (trajectoire T2) | lot distinct |
| FOpts dans le chemin plan | la parité n'est définie qu'à `fopts = b""` (§2.1) |
| Validation du DR montant dans le chemin trace | lacune préexistante, non traitée |
| Écart de 20 octets sur DR10-DR13 (touche aussi US915) | lot distinct (§12.10.3) |
