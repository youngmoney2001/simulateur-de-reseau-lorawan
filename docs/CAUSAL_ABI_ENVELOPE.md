# Enveloppe causale — jalon I4 (D3.15)

Spécification et résultats. Variante retenue : **C**, pointeurs typés exclusifs.

## 1. Constat : la multiplication des entrées

Le chemin causal s'était fragmenté en **six** entrées C, produits du cartésien
{passerelle v1, passerelle v2} × {sans frontal, avec frontaux} × {sans RX2, avec RX2} :

| Passerelle | Frontaux | RX2 | Entrée |
|---|---|---|---|
| v1 | non | non | `lsim_simulate_uplinks_causal_v1` |
| v1 | oui | non | `lsim_simulate_uplinks_causal_v2` |
| v1 | non | oui | `lsim_simulate_uplinks_causal_v3` |
| v1 | oui | oui | `lsim_simulate_uplinks_causal_v3` |
| v2 | non | non | `lsim_simulate_uplinks_causal_gw2` |
| v2 | oui | non | `lsim_simulate_uplinks_causal_gw2_v2` |
| v2 | non | oui | `lsim_simulate_uplinks_causal_gw2_v3` |
| v2 | oui | oui | `lsim_simulate_uplinks_causal_gw2_v3` |

Chaque appelant devait choisir la bonne combinaison. Chaque extension ajoutée en aurait créé
deux nouvelles. Le choix se faisait par **nom de symbole**, donc hors du système de types.

## 2. Les trois variantes

### Variante A — entrées plates multiples

On garde les six. **Rejetée** : le constat est le problème, pas sa gestion.

### Variante B — enveloppe à pointeurs faiblement typés

Une structure avec des `void*` et des compteurs. **Rejetée** : une confusion de table
(passer `device_rf` là où l'on attend `rx2`) compile, se lie, et corrompt silencieusement la
mémoire — le compte serait lu sur le mauvais type. C'est exactement la classe de défaut que
`DOWNLINK_PLAN_ABI_V2.md` §2.3 cherche à exclure.

### Variante C — enveloppe à pointeurs typés exclusifs — **retenue**

Une structure où chaque table optionnelle porte son **propre type de pointeur** :
`lsim_plan_device_rx2*`, `lsim_device_rf*`, `lsim_gateway_rf*`. Une confusion devient une erreur
de compilation (C) ou de typage (ctypes), jamais une corruption.

## 3. Contrat

### 3.1 Entrée

```c
#define LSIM_CAUSAL_ABI_VERSION 1u
int32_t lsim_simulate_uplinks_causal(const lsim_causal_args* args);
```

### 3.2 Structure et dispositions

24 champs + `reserved[2]`. Dispositions **mesurées** puis épinglées par `static_assert` sur les
deux cibles dans `core/tests/abi_layout.cpp`.

| Champ | x86-64 | i386 | | Champ | x86-64 | i386 |
|---|---|---|---|---|---|---|
| `struct_size` | 0 | 0 | | `record_capacity` | 96 | 52 |
| `abi_version` | 4 | 4 | | `record_count` | 104 | 56 |
| `devices` | 8 | 8 | | `busy_out` | 112 | 60 |
| `device_count` | 16 | 12 | | `busy_capacity` | 120 | 64 |
| `gateway` | 24 | 16 | | `busy_count` | 128 | 68 |
| `gateway_v2` | 32 | 20 | | `rx2` | 136 | 72 |
| `prop` | 40 | 24 | | `rx2_count` | 144 | 76 |
| `env` | 48 | 28 | | `device_rf` | 152 | 80 |
| `radios` | 56 | 32 | | `device_rf_count` | 160 | 84 |
| `options` | 64 | 36 | | `gateway_rf` | 168 | 88 |
| `per_device` | 72 | 40 | | `reserved` | 176 | 92 |
| `totals` | 80 | 44 | | `sizeof` | **192** | **108** |
| `records` | 88 | 48 | | | | |

### 3.3 Validation

Refus de validation de l'enveloppe : **951** (`LSIM_STATUS_PLAN_BASE + 1`).

L'ensemble des champs obligatoires est **exactement** celui de `causal_v1_impl`, ni plus ni
moins — sinon l'enveloppe refuserait un appel que l'entrée plate accepte :

- requis : `prop`, `options`, `totals`, `record_count`, `busy_count` ;
- requis si `device_count > 0` : `devices`, `per_device`, `radios` ;
- requis si `record_capacity > 0` : `records` ; si `busy_capacity > 0` : `busy_out`.

Trois règles propres à l'enveloppe :

1. **Passerelle exclusive** : exactement un de `gateway` / `gateway_v2`.
2. **Pointeur et compte solidaires** pour `rx2` et `device_rf` : la table est fournie entièrement
   ou pas du tout. Un compte orphelin ferait lire une longueur qui n'est pas celle du tableau.
3. **Longueur annoncée** égale à `device_count`, jamais une autre.

Un refus est décidé **avant tout déréférencement** : aucune table n'est lue si l'appel est refusé.

Un `gateway_v2` dont `sensitivity_model > LSIM_SENSITIVITY_MODEL_ABSOLUTE_PER_SF_V2` est refusé
par le moteur (**301**), comme dans `gw2_v3` — l'enveloppe ne masque pas ce refus.

### 3.4 Équivalence

L'enveloppe délègue à `causal_v1_impl`. Elle doit produire, pour une configuration donnée,
exactement le résultat de l'entrée plate correspondante.

## 4. Périmètre — fichiers

| Fichier | Rôle |
|---|---|
| `core/include/lsim/c_api.h` | `lsim_causal_args`, `LSIM_CAUSAL_ABI_VERSION`, déclaration |
| `core/src/c_api_ext.cpp` | l'enveloppe, insérée après la déclaration anticipée de `causal_v1_impl` |
| `core/tests/abi_layout.cpp` | dispositions épinglées sur les deux cibles, compteurs 55→56 / 477→502 |
| `python/lsim/downlink_plan.py` | `_CCausalArgs`, `argtypes` explicites, `simulate_causal` réécrit |
| `python/tests/test_d315_causal_envelope.py` | 26 tests : équivalence, validation, discrimination |
| `docs/CAUSAL_ABI_ENVELOPE.md` | ce document |

Les six entrées plates demeurent **exportées et inchangées** : c'est un contrat envers les
appelants externes, pas une tolérance.

## 5. Critères d'acceptation

1. Les six entrées plates sont inchangées et produisent les mêmes résultats.
2. L'enveloppe produit des résultats **identiques** à l'entrée plate correspondante, sur une
   chronologie commune (8 configurations), pas sur des cas isolés.
3. Chaque règle de validation est testée, et aucun refus ne déréférence.
4. Typage : pointeurs typés uniquement ; la liaison Python déclare `argtypes` explicitement.
5. ABI x86-64 : **56** structures, compteurs mis à jour ; i386 : compilation OK.
6. Symboles `lsim_*` : **101** (+1, **0** retiré).
7. Empreintes gelées inchangées.
8. Scénarios historiques sans région inchangés.
9. Tests discriminants : retirer l'enveloppe ou affaiblir une validation fait échouer les tests.

---

## 6. Résultats mesurés (2026-11-04)

Toutes les valeurs proviennent de commandes exécutées, sur la bibliothèque reconstruite après la
dernière modification du code.

| # | Critère | Mesure | Verdict |
|---|---------|--------|---------|
| 1 | Six entrées plates inchangées | sorties comparées champ par champ entre la base `8e9fcbd` et I4 : **identiques** ; 0 symbole retiré | **tenu** |
| 2 | Équivalence sur chronologie commune | 8 configurations + scène sans région, comparées enregistrement / occupation / compteurs / totaux | **tenu** |
| 3 | Validation testée, aucun déréférencement | adresse `0x1` avec compte cohérent ⇒ refus 951 sans accès | **tenu** |
| 4 | Pointeurs typés | 3 types distincts, aucun `void*`, `TypeError` sur confusion | **tenu** |
| 5 | ABI | 56 structures / 502 grandeurs en x86-64, objet i386 produit | **tenu** |
| 6 | Symboles | **101** `lsim_*`, **+1 / 0 retiré** | **tenu** |
| 7 | Empreintes | `d2cb0fac…` (JSON) et `ed126d7f…` (trace) : **inchangées** | **tenu** |
| 8 | Scénarios sans région | `-k sans_region` : 4 passed | **tenu** |
| 9 | Tests discriminants | 6 révocations, chacune détectée | **tenu** |

### 6.1 Révocations — preuve que les tests sont discriminants

Chaque révocation est appliquée au code, la bibliothèque reconstruite, les tests rejoués, puis le
code restauré et reconstruit. La restauration est vérifiée par empreinte SHA-256.

| Révocation | Échecs |
|---|---|
| R1 — la production repasse par les entrées plates | 1 |
| R2 — règle « pointeur et compte solidaires » retirée (rx2) | 1 |
| R3 — `rx2` non transmis à `causal_v1_impl` | 4 |
| R4 — frontaux RF non transmis | 4 |
| R5 — exclusivité des passerelles neutralisée | 1 |
| R6 — vérification de `abi_version` neutralisée | 2 |

### 6.2 Limite : le repli RX2 n'est observable qu'en saturation

Sur une scène calme (12 terminaux, SF10, descentes de 60 octets), **aucune fenêtre RX1 n'est
manquée** : la table RX2 est transmise mais inerte. La révocation R3 n'y était **pas détectée**.

La scène d'équivalence est donc une scène saturée (40 terminaux, SF7, descentes de 200 octets),
trouvée empiriquement, où la table RX2 change effectivement le résultat : 194 intervalles
d'occupation et 223 trames reçues sans RX2, contre 104 et 112 avec — le repli coûte l'émetteur
(SF12), ce qui est un fait radio et non un défaut. Un garde-fou d'utilité épingle cette
propriété : le test échoue si la scène redevient inerte.

**Portée** : le test prouve que l'enveloppe transmet RX2 **là où RX2 a un effet**, pas dans
l'absolu. Le repli lui-même reste démontré par
`test_downlink_plan_rx2.py::test_scenario_sature_demontre_le_repli` (7 descentes en RX2 sur 40
RX1 manquées).

### 6.3 Garde-fou sur le paramètre passerelle

Avec les seuils publiés SX1303, la scène saturée donne **exactement le même résultat** en
passerelle v1 et v2 (aucune trame n'y est perdue en sensibilité). Une enveloppe qui ignorerait
`gateway_v2` passerait donc inaperçue. Le garde-fou utilise des seuils volontairement sourds
(−70 dBm) pour que les deux modèles diffèrent réellement.

### 6.4 Constat annexe — 11 échecs i386 préexistants

`scripts/preuves/verifier_assertions_lp64.py` rapporte 11 échecs i386. Mesurés à l'identique sur
`8e9fcbd` **hors I4** (worktree temporaire). Ils concernent d'autres structures, jamais
`lsim_causal_args`, que ce script ne couvre pas (14 assertions). État antérieur à I4, non traité.

### 6.5 Note sur la reconstruction du 2026-11-04

Ce jalon a été produit une première fois, puis **perdu** : le répertoire de travail a été effacé
sans que le commit ait été poussé. Il a été reconstruit depuis cette spécification et les relevés
de disposition. Les mesures du §6 sont celles de la version reconstruite, et toutes ont été
rejouées sur le code reconstruit — aucune n'est reprise de la version perdue.
