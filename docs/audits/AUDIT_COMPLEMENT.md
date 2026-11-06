# Complément d'audit — LP64, divergences Git, recherche documentaire, dépendances

**Référence** `68176d64869298932f32b7458ddc1beb51449f3e` · **Date** 2026-10-31
**Restrictions respectées** : aucun fichier du dépôt modifié, aucun commit, aucun push, aucun merge,
aucune correction fonctionnelle, dépôt principal et `main` non touchés.

> **Rectification assumée.** Le rapport d'audit initial affirmait que « les 14 assertions LP64
> échouent en i386 ». C'est **faux** : **11** échouent, **3** sont indépendantes de l'ABI (§1).
> `AUDIT_GLOBAL_RAPPORT.md` et `AUDIT_REGISTRE_ANOMALIES.md` ont été corrigés en conséquence
> (nouvelles empreintes SHA-256 : `119e4cbc…` et `081fd38d…`). Rien d'autre n'a changé dans ces
> deux documents.

> **Rectification C6 (Phase A, 2026-10-31).** La conclusion de §3.3 présentait M2 et M3 comme
> « corroborés » par F6. F6 n'étant **pas reproduit**, cette formulation allait au-delà des
> observations disponibles ; elle a été requalifiée (§3.3). Ce document porte donc une empreinte
> SHA-256 différente de celle du livrable de session (`b4fcdd5a…`) ; `AUDIT_GLOBAL_RAPPORT.md` et
> `AUDIT_REGISTRE_ANOMALIES.md` restent inchangés. Aucun fichier de code n'est concerné.

---

## 1. Les 14 assertions LP64 : liste exacte, emplacements, effet i386

### 1.1 Emplacement

**Fichier** : `core/tests/test_rf_frontend.cpp`, fonction
`test_rf_structs_have_a_fixed_layout()` (ligne 84), assertions **lignes 86 à 101**
(14 assertions, séparées par deux lignes vides aux lignes 90 et 95).

### 1.2 Liste exhaustive

Valeurs i386 extraites de `core/tests/abi_layout.cpp` (table `expected`, branche `__i386__`,
lignes 49–559), **mesurées par le compilateur** en F7 **et re-mesurées pendant ce complément**
(§1.3).

| # | Ligne | Assertion | x86-64 | i386 | i386 ? | Constante de remplacement |
|---|---|---|---|---|---|---|
| 1 | 86 | `sizeof(lsim_device_rf) == 24` | 24 | **20** | **ÉCHEC** | `expected::size_lsim_device_rf` |
| 2 | 87 | `offsetof(lsim_device_rf, present) == 0` | 0 | 0 | OK | `expected::off_lsim_device_rf__present` |
| 3 | 88 | `offsetof(lsim_device_rf, antenna_gain_dbi) == 8` | 8 | **4** | **ÉCHEC** | `expected::off_lsim_device_rf__antenna_gain_dbi` |
| 4 | 89 | `offsetof(lsim_device_rf, cable_loss_db) == 16` | 16 | **12** | **ÉCHEC** | `expected::off_lsim_device_rf__cable_loss_db` |
| 5 | 91 | `sizeof(lsim_gateway_rf) == 24` | 24 | **20** | **ÉCHEC** | `expected::size_lsim_gateway_rf` |
| 6 | 92 | `offsetof(lsim_gateway_rf, present) == 0` | 0 | 0 | OK | `expected::off_lsim_gateway_rf__present` |
| 7 | 93 | `offsetof(lsim_gateway_rf, antenna_gain_dbi) == 8` | 8 | **4** | **ÉCHEC** | `expected::off_lsim_gateway_rf__antenna_gain_dbi` |
| 8 | 94 | `offsetof(lsim_gateway_rf, cable_loss_db) == 16` | 16 | **12** | **ÉCHEC** | `expected::off_lsim_gateway_rf__cable_loss_db` |
| 9 | 96 | `sizeof(lsim_closed_loop_v4_args) == 56` | 56 | **40** | **ÉCHEC** | `expected::size_lsim_closed_loop_v4_args` |
| 10 | 97 | `offsetof(lsim_closed_loop_v4_args, v3) == 8` | 8 | 8 | OK | `expected::off_lsim_closed_loop_v4_args__v3` |
| 11 | 98 | `offsetof(lsim_closed_loop_v4_args, device_rf) == 16` | 16 | **12** | **ÉCHEC** | `expected::off_lsim_closed_loop_v4_args__device_rf` |
| 12 | 99 | `offsetof(lsim_closed_loop_v4_args, device_rf_count) == 24` | 24 | **16** | **ÉCHEC** | `expected::off_lsim_closed_loop_v4_args__device_rf_count` |
| 13 | 100 | `offsetof(lsim_closed_loop_v4_args, gateway_rf) == 32` | 32 | **20** | **ÉCHEC** | `expected::off_lsim_closed_loop_v4_args__gateway_rf` |
| 14 | 101 | `offsetof(lsim_closed_loop_v4_args, reserved) == 40` | 40 | **24** | **ÉCHEC** | `expected::off_lsim_closed_loop_v4_args__reserved` |

**Bilan** : 14 assertions · **0 échec en x86-64** · **11 échecs en i386** · 3 assertions
indépendantes de l'ABI (`offsetof(present) = 0` pour les deux structures RF, `offsetof(v3) = 8`).

### 1.3 Reproductibilité

```bash
# extraction des 14 littéraux
grep -nE "CHECK_EQ\(static_cast<int>\((sizeof|offsetof)\(lsim_" core/tests/test_rf_frontend.cpp
# valeurs i386 et x86-64 (tables mesurées en F7)
grep -n "size_lsim_device_rf\|off_lsim_device_rf__\|size_lsim_gateway_rf\|off_lsim_gateway_rf__\|size_lsim_closed_loop_v4_args\|off_lsim_closed_loop_v4_args__" core/tests/abi_layout.cpp
```

Le script de comparaison (lecture des deux tables, appariement avec les 14 assertions) a produit
exactement le tableau ci-dessus ; il est rejouable sans dépendance.

**Vérification indépendante des valeurs i386, faite pendant ce complément** (et non seulement
reprise de la table F7) : un fichier de 14 `static_assert` écrivant les valeurs i386 du tableau
est compilé pour les deux ABI, contre le `c_api.h` réel.

```bash
g++ -std=c++17 -I core/include -c /tmp/check_layout.cpp -o /tmp/check64.o   # → OK (14 valeurs LP64)
g++ -m32 -ffreestanding -std=c++17 -I core/include -c /tmp/check_layout.cpp -o /tmp/check32.o
# → OK : les 14 valeurs i386 du tableau sont confirmées par le compilateur
```

**Test de sensibilité** : en remplaçant la première valeur i386 par le littéral x86-64 (`24`), la
compilation i386 échoue immédiatement :

```
/tmp/check_bad.cpp:6:38: error: static assertion failed: x
    6 | static_assert(sizeof(lsim_device_rf) == 24, "x");
```

C'est la démonstration que le tableau n'est pas recopié : il est **mesuré**, et la mesure est
**discriminante**.

### 1.4 Conséquences techniques

1. **Rien n'arrête ces 11 assertions à la compilation** : `CHECK_EQ`
   (`core/tests/check.hpp`, ligne 25) est une vérification **d'exécution** (compteur
   `++checks()` puis `report`), pas un `static_assert`. Sur une chaîne 32 bits complète, le
   binaire se compilerait et ces vérifications échoueraient **au lancement**. C'est plus grave
   qu'une erreur de compilation : la compilation ne signale rien. (Réserve : cette chaîne 32 bits
   n'existe pas ici — §H — donc le comportement i386 n'est pas observable, seulement calculable
   depuis la table `abi_layout`.)
2. **Le décompte « 8 »** correspond aux 8 assertions des deux structures RF (`lsim_device_rf` 4 +
   `lsim_gateway_rf` 4 = lignes 86–94) ; il **omet les 6 assertions** de `lsim_closed_loop_v4_args`.
3. **La correction est mécanique** : chaque littéral a une constante mesurée équivalente
   (colonne de droite). Aucune structure ne change.

---

## 2. Les deux divergences Git de la sauvegarde : preuve détaillée

### 2.1 Écart mesuré

```
$ diff -r --exclude=__pycache__ /tmp/audit_restore/recovery /home/user/recovery
diff -r .../.git/logs/refs/remotes/origin/arena/fdc94521-simulateur-de-reseau-lorawan ...
3a4
> c77f8eb7d46a2403a181f480f7c2a8c220531ee6 68176d64869298932f32b7458ddc1beb51449f3e Arena Agent <agent@arena.ai> 1793471088 +0000	update by push
diff -r .../.git/refs/remotes/origin/arena/fdc94521-simulateur-de-reseau-lorawan ...
1c1
< c77f8eb7d46a2403a181f480f7c2a8c220531ee6
---
> 68176d64869298932f32b7458ddc1beb51449f3e
```

**Divergence 1** — `.git/refs/remotes/origin/arena/fdc94521-simulateur-de-reseau-lorawan`
(contenu du fichier) : archive `c77f8eb…`, direct `68176d6…`.
**Divergence 2** — `.git/logs/refs/remotes/origin/…` (journal de la référence) : la ligne de push
`c77f8eb… → 68176d6…` (horodatage `1793471088`) existe en direct, **pas** dans l'archive.

Aucune autre divergence : **2 fichiers, tous deux dans `.git/refs/remotes`**.

### 2.2 Preuve que le contenu est identique

| Contrôle | Archive | Direct |
|---|---|---|
| `HEAD` | `68176d64869298932f32b7458ddc1beb51449f3e` | `68176d64869298932f32b7458ddc1beb51449f3e` |
| `HEAD^{tree}` | `d3095c077b7c0ca0321ec16e120b219952ca320f` | `d3095c077b7c0ca0321ec16e120b219952ca320f` |
| `git diff --stat <archive> <direct>` | — | **vide** |
| Fichiers suivis | 332 | 332 |
| Fichiers modifiés/sales | 0 | 0 |

### 2.3 Chronologie mesurée

| Événement | Horodatage | Source |
|---|---|---|
| Commit `68176d6` | **18:24:39Z** (`1793471079`) | `git log --format=%ct` |
| Création du tar et du bundle | **18:24:41Z** | `mtime` des trois fichiers de sauvegarde |
| Mise à jour de la référence distante (push) | **18:24:48Z** (`1793471088`) | `.git/logs/refs/remotes/…` |

L'archive est donc postérieure au commit de **2 s** et antérieure au push de **7 s** : il est
**impossible** qu'elle contienne la référence mise à jour. Ce n'est ni une erreur de sauvegarde ni
une perte de données.

### 2.4 Portée

- **Non affecté** : commits, arbres, fichiers, historique, restaurabilité (clone du bundle ⇒
  `68176d6`, 0 sale, 332 fichiers, « complete history »).
- **Affecté** : la seule mémoire locale du distant, c'est-à-dire un `git status` d'avance/retard
  sur `origin/arena/…` dans l'arbre restauré.
- **Consequence pratique** : dans l'arbre restauré, `git fetch` réalignerait la référence ; aucune
  action de réparation n'est nécessaire.

---

## 3. Recherche de `R2B_CLOTURE_AUDIT_ANOMALIES.md`

### 3.1 Objet recherché

Fichier `R2B_CLOTURE_AUDIT_ANOMALIES.md`, **704 lignes**, SHA-256 attendu
`1d2f5ad06e0f042630796325426643704cf670b5810ef125a0af907c272cc03e` (source : tableau §2.2 de
`R2B_PHASE1_INCIDENT_ESPACE_TRAVAIL.md`, ligne 166).

### 3.2 Méthodes et résultats

| # | Emplacement / méthode | Volume examiné | Résultat |
|---|---|---|---|
| 1 | `recovery` — `git rev-list --objects --all \| grep -i "cloture\|audit"` | toutes les refs (locales, distantes, `refs/remotes/origin/arena/d67ca5ff`, `e2b61318`) | **0 objet** |
| 2 | `recovery` — contenu des blobs (objets 10–200 Ko) recherché par titre `CLOTURE_AUDIT` / `R2B_CLOTURE` | **694 blobs** | **0 occurrence** |
| 3 | Dépôt principal — mêmes deux recherches | toutes les refs, tous les blobs de la plage | **0** |
| 4 | 9 bundles — `git bundle list-heads` | 9 bundles | uniquement des commits connus (`68176d6`, `c77f8eb`, `2202782`, `9686c25`, `c46d531`, `1f43370` + deux refs distantes anciennes) — **aucun commit inconnu** |
| 5 | 9 archives `tar.gz` — extraction complète puis hachage de **tous** les fichiers (hors `.git`) | **4 035 fichiers** | **aucune empreinte `1d2f5ad0…`** |
| 6 | 9 archives — recherche par nom (`*cloture*`, `*anomal*`, `*audit*`) | 9 archives | **0** |
| 7 | 9 archives + `/home/user` — fichiers Markdown de 650 à 760 lignes | tous les `.md` | un seul : `recovery-build/_deps/mbedtls-src/docs/architecture/psa-shared-memory.md` (685 l.) — sans rapport |
| 8 | `/home/user` — hachage de **tous** les fichiers, toutes extensions | **3 293 fichiers** | **aucune correspondance** |
| 9 | `/home/user` — hachage des `.md`/`.txt` | **184 fichiers** | **aucune correspondance** |
| 10 | Répertoires cachés (`/home/user/.cache`, `.local`, `.venv-lsim` ; `.arena` inexistant) | tout le contenu texte | **0** |
| 11 | `/tmp` — tous les répertoires de travail (`audit_b`, `audit_build`, `audit_clone`, `audit_restore`, `audit_t`, `base_audit`, `build_f7`, `build_f7f`, `build_restore`, `clone_f2g1`, `drift`, `drift2`, `f7`, `f7f_b`, `f7f_t`, `fp`, `g1`, `mut`, `mutrepo`, `pipprobe`, `pre_b`, `pre_r2b`, `pre_t`, `pref2_b`, `pref2_t`, `probe`, `pytest-of-user`, `r1probe`, `restore_bundle`, `restore_r1`, `search_tars`, `arena-workspace`, `arena-coding-uploads`) | tous les `.md` + tous les fichiers hors builds | **aucune correspondance** |
| 12 | `/tmp/arena-workspace/coding.patch`, `coding.diff`, `coding-numstat.txt` (artefacts de session) | 1 013 602 o chacun | **0** occurrence du titre ou de l'empreinte ; le patch ne touche que des chemins `a/…` du dépôt |
| 13 | `/tmp/arena-coding-uploads` | 28 pièces jointes (PDF de spécifications, PNG) | **aucun rapport** |
| 14 | Tout le système de fichiers — `find / -xdev -iname '*cloture*'` | hors `/usr`, `/var/lib`, `recovery-build` | **aucun fichier** |
| 15 | Toutes références textuelles à `1d2f5ad0` dans `/home`, `/tmp`, `/opt`, `/srv` | — | **4 fichiers** : `R2B_PHASE1_INCIDENT_ESPACE_TRAVAIL.md` (la ligne d'inventaire) et **mes trois rapports d'audit** |

### 3.3 Conclusion

**Le document est introuvable.** Aucune copie, aucun extrait, aucune variante de nom ou d'empreinte
n'existe dans les espaces accessibles. Il **n'a pas été reconstruit** : la consigne est respectée,
et une reconstruction non vérifiable ne serait pas une preuve.

**Ce qui reste connu de façon certaine** : le nom, la longueur (704 lignes) et l'empreinte
SHA-256. **Ce qui n'est plus connu** : son contenu, donc la définition exacte de **M1** et **M4**
(et la portée exacte de M3).

**Éléments de contexte retrouvés ailleurs** (non vérifiables contre l'original, donc présentés
comme tels — aucun n'est une corroboration établie de l'anomalie complète) :
- **M2** : l'invariance `d0` sans relief a été **observée** dans le périmètre de la sonde rejouée ;
  cette observation ne suffit pas à établir l'anomalie globale. Les éléments F6 associés restent
  **non reproduits**.
- **M3** : le refus d'une configuration RF partielle est **observé dans le chemin v4**. Cette
  observation ne démontre pas le comportement correspondant dans le chemin mesh. L'écart F6 relatif
  à `mesh_rf` partiel (12 dB) reste **non reproductible**.
- **M1** et **M4** n'ont **aucun** contenu résiduel exploitable.

**Pistes de récupération** (hors de ma portée, à votre main) :
1. Le fichier a probablement existé dans une session antérieure ; un export de cette conversation ou
   du répertoire de travail de cette session permettrait de le retrouver.
2. Si vous le fournissez, **je vérifierai d'abord** `sha256sum` contre `1d2f5ad0…` ; en cas
   d'écart, je le signalerai sans l'utiliser.

---

## 4. Dépendances techniques entre les phases A à H

### 4.1 Graphe

```
                    ┌──────────────┐
                    │      A       │  consolidation (docs, preuves versionnées)
                    └──────┬───────┘
          ┌────────────────┼─────────────────┐
          ▼                ▼                 ▼
     ┌─────────┐      ┌─────────┐       ┌─────────┐
     │    B    │      │    C    │       │    E    │  diagnostic F1/F6
     │  LP64   │      │ RF YAML │       └────┬────┘
     └─────────┘      └───┬─────┘            ▼
                     ┌────┴────┐         ┌─────────┐
                     ▼         ▼         │    F    │  unification F6 / d0
                 ┌───────┐ ┌───────┐     └─────────┘
                 │   D   │ │   G   │
                 │ multi │ │GeoJSON│
                 │ mesh  │ └───────┘
                 └───────┘

     ┌─────────┐
     │    H    │  i386 complet — indépendant (outillage), informe B
     └─────────┘
```

### 4.2 Table des dépendances

| Phase | Dépend de | Bloque | Nature de la dépendance | Type de porte |
|---|---|---|---|---|
| **A** | — | B, C, E | Les preuves et les chiffres doivent être justes avant de s'appuyer dessus | **Porte dure** |
| **B** | A | — (informe H) | Aucune dépendance technique ; A évite de corriger un fichier mal documenté | Porte souple |
| **C** | A | D, G | D et G ont besoin d'une source de configuration RF | **Porte dure** |
| **D** | C | G (si mesh affiché) | Le mesh a besoin d'un frontal configurable | Porte dure |
| **E** | A | F | On ne corrige que ce qui est reproduit | **Porte dure** |
| **F** | E + décision de modèle | G (recommandé) | Un changement de modèle de propagation invalide les cartes | Porte dure |
| **G** | C, D, F (recommandé) | — | Format GeoJSON dépendant des configurations et de `d0` | Porte souple |
| **H** | — | — | Outillage indépendant ; conditionne la **preuve** i386 de B | Porte indépendante |

### 4.3 Chemin critique

`A → C → D → G` (fonctionnalités) et `A → E → F` (fiabilité). **F et D sont parallélisables** si
les périmètres de fichiers sont disjoints (`core/src/engine.cpp` et `python/lsim/geo.py` vs
`core/src/mesh.cpp` et `c_api_ext.cpp`) — mais **F doit précéder G** pour ne pas cartographier
deux fois.

---

## 5. Critères d'acceptation proposés, phase par phase

Chaque critère est **mesurable et rejouable** ; une phase n'est acceptée que si **tous** ses
critères sont satisfaits, empreintes et suites comprises.

### Phase A — Consolidation documentaire et des preuves

| ID | Critère | Commande / mesure |
|---|---|---|
| A-1 | Aucun fichier de code touché | `git diff --stat` limité à `docs/`, `CHANGELOG.md`, `scripts/` |
| A-2 | Chiffres du CHANGELOG exacts | contient `1802 → 1839` et `685165 → 685249` ; plus aucune occurrence de `1832` ou `685235` |
| A-3 | Décompte LP64 rectifié partout | « 14 assertions » présent ; « 8 assertions » absent sauf mention historique explicite |
| A-4 | Rapports versés dans `docs/audits/` avec leurs SHA-256 | tous les rapports de phase et d'audit présents, `sha256sum` conforme à l'index |
| A-5 | Sondes versionnées et exécutables | `scripts/preuves/` : chaque script se lance en **une** commande, code retour 0 |
| A-6 | Suites inchangées | C++ **685249**, `ctest` **1/1**, Python **1846/1/16**, empreintes `d2cb0fac…` / `ed126d7f…` |
| A-7 | Archive post-push | `diff -r --exclude=.git` vide **et** `.git/refs/remotes` identiques |

### Phase B — Dette LP64

| ID | Critère | Commande / mesure |
|---|---|---|
| B-1 | Plus aucun littéral ABI dans le fichier | `grep -cE "CHECK_EQ\(static_cast<int>\((sizeof\|offsetof)\(lsim_[^)]*\), [0-9]+\)" core/tests/test_rf_frontend.cpp` ⇒ **0** |
| B-2 | 14 assertions remplacées par les constantes | diff : **14** lignes modifiées, aucune autre |
| B-3 | Structures et tables inchangées | `git diff -- core/include core/tests/abi_layout.cpp` **vide** |
| B-4 | Suites x86-64 inchangées | C++ **685249**, `ctest` 1/1, Python **1846** |
| B-5 | Harnais ABI toujours vert | x86-64 : 53 structures / 454 grandeurs ; i386 : compilation OK |
| B-6 | Portée annoncée honnêtement | le rapport de phase précise « dispositions, pas exécution 32 bits » |

### Phase C — RF dans les scénarios YAML

| ID | Critère | Commande / mesure |
|---|---|---|
| C-1 | Neutralité stricte | sans clé `rf:` : empreintes `d2cb0fac…` / `ed126d7f…` **identiques**, 1846 tests |
| C-2 | Hash non pollué | un scénario sans `rf:` garde le **même** `scenario_sha256` qu'à `68176d6` |
| C-3 | Routage prouvé | espions : avec `rf` ⇒ `trace_v3`/`gw2_v2`/`multi_dl_v2`/`closed_loop_v4` appelés, anciens **jamais** |
| C-4 | Refus explicite | `rf` partiel ⇒ `ValueError` Python **et** statut **301** côté ABI |
| C-5 | Bornes | `|G| > 40`, `L < 0`, `L > 40`, `NaN` refusés (Python + C) |
| C-6 | Schémas | schémas régénérés, tests de schéma verts, `schema_version` inchangée |
| C-7 | Périmètre | `git diff -- python/lsim/geo.py` **vide** ; `test_geo.py` 13 tests verts |
| C-8 | ABI | **95** symboles (aucun ajout en C dans cette phase) |

### Phase D — `simulate_uplinks_multi` v4 et RF mesh

| ID | Critère | Commande / mesure |
|---|---|---|
| D-1 | Surface binaire | **96** symboles, `comm -23` = **0**, exactement **1** ajout (`lsim_simulate_uplinks_multi_v2`) |
| D-2 | Neutralité mesh | sans `mesh_rf` : sorties mesh **identiques au bit près** à `68176d6` |
| D-3 | Effet mesuré | avec `mesh_rf` complet : RSSI des deux extrémités modifiés conformément au contrat documenté |
| D-4 | Refus partiel | `mesh_rf` incomplet ⇒ statut **301**, aucun calcul |
| D-5 | Isolation | `test_rf_path_never_calls_a_mesh_symbol` toujours vert ; aucun symbole `lsim_mesh_*` appelé par le chemin LoRaWAN RF |
| D-6 | Suites | C++ et Python complets verts, compteurs publiés |

### Phase E — Diagnostic F1 / F6 (aucune correction)

| ID | Critère | Commande / mesure |
|---|---|---|
| E-1 | Sondes versionnées | chaque point F1/F6 a un script dans `scripts/preuves/`, exécutable en une commande |
| E-2 | Tableau de verdicts | pour chacun des 7 points F6 et de F1 : **reproduit** / **non reproduit** / **clos avec preuve négative** |
| E-3 | Aucun code de production touché | `git diff -- core python/lsim` **vide** |
| E-4 | F1 tranché | soit une graine en échec **reproductible** est identifiée, soit une preuve négative argumentée (nombre de runs, paramétrage exact) est publiée |
| E-5 | Suites | 685249 / 1846 / empreintes inchangées |

### Phase F — Unification F6 / `d0`

| ID | Critère | Commande / mesure |
|---|---|---|
| F-1 | Décision écrite | document de conception signé **avant** code : `d0` honorée ou invariance documentée ; modèle cible par chemin |
| F-2 | Changement d'empreintes assumé | nouvelles valeurs publiées **et** justifiées écart par écart (aucune dérive silencieuse) |
| F-3 | R1 requalifié | les 24 tests de caractérisation sont mis à jour **ou** explicitement déclarés obsolètes, avec justification |
| F-4 | ADR intact | `git diff -- core/src/*adr*` **vide** |
| F-5 | Suites | C++ et Python complets verts ; `ctest` 1/1 |
| F-6 | Périmètre | un seul modèle de propagation, une seule convention `d0`, cohérence causal/trace/multi/mesh démontrée par test |

### Phase G — GeoJSON avec configuration RF résolue

| ID | Critère | Commande / mesure |
|---|---|---|
| G-1 | Contrat historique préservé | les **6 tests G1 existants passent sans modification** |
| G-2 | Groupe homogène | **exactement 7 clés** (comparaison d'ensembles de clés) |
| G-3 | Groupe hétérogène | seules les clés optionnelles documentées apparaissent, dans l'ordre documenté |
| G-4 | Cohérence | `range_m` = `coverage_radius_m` recalculé ; anneau fermé ; rayon projeté cohérent |
| G-5 | Interface web | test de contrat `web/` vert (lecture du GeoJSON) |
| G-6 | ABI | 96 symboles (aucun changement) |

### Phase H — Moteur i386 complet

| ID | Critère | Commande / mesure |
|---|---|---|
| H-1 | Décision explicite | soit « outillage disponible et phase ouverte », soit « limite définitive documentée » |
| H-2 | Si outillage | `cmake -DCMAKE_C_FLAGS=-m32` configure, compile, **lie**, et `lsim_tests` s'exécute : résultat publié |
| H-3 | Si clôture | la phrase exacte de l'échec (`ld: cannot find -lgcc`) et l'absence de CRT/libc 32 bits sont consignées dans `docs/` |
| H-4 | Aucun impact x86-64 | suites et empreintes inchangées |

---

## 6. État final de ce complément

| Question | Réponse |
|---|---|
| Les 14 assertions sont-elles listées ? | **Oui** (§1.2), avec ligne, expression, valeur x86-64, valeur i386 et constante de remplacement |
| Combien échouent en i386 ? | **11 sur 14** ; 3 sont indépendantes de l'ABI |
| Les deux divergences Git sont-elles prouvées ? | **Oui** (§2) : 2 fichiers, ref + log, chronologie à la seconde, contenu identique par arbre |
| Le document perdu a-t-il été retrouvé ? | **Non** (§3), après 15 méthodes couvrant 3 293 fichiers de `/home/user`, 4 035 fichiers d'archives, 694 blobs Git, 9 bundles et tout `/tmp` |
| A-t-il été reconstruit ? | **Non** — aucune reconstruction, conformément à la consigne |
| Les dépendances A–H sont-elles établies ? | **Oui** (§4), graphe + table + chemin critique |
| Des critères d'acceptation existent-ils ? | **Oui** (§5), **48** critères mesurables répartis sur 8 phases (7 + 6 + 8 + 6 + 5 + 6 + 6 + 4) |

**Aucun fichier du dépôt n'a été modifié. Aucun commit, aucun push.** Le dépôt reste à
`68176d6`, arbre propre.
