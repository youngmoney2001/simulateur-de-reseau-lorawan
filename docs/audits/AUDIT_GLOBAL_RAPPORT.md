# Audit global de consolidation — rapport principal

**Point de référence** `68176d64869298932f32b7458ddc1beb51449f3e` (`arena/fdc94521-simulateur-de-reseau-lorawan`)
**Date** 2026-10-31 · **Nature** audit en lecture seule : **aucun fichier du dépôt modifié, aucun
commit, aucun push, aucun merge**.
**Livrables associés** : `AUDIT_MATRICE_FONCTIONNALITES.md`, `AUDIT_REGISTRE_ANOMALIES.md`,
`AUDIT_BILAN_SAUVEGARDES.md`, `AUDIT_SEQUENCEMENT.md`.

---

## 0. Résumé exécutif

L'état technique est **sain et reproductible** : depuis `68176d6`, un build **neuf** (répertoire
vide) reconstruit le cœur, passe **685249/685249** vérifications C++, `ctest` 1/1, **1846 tests
Python** (1 skip, 16 subtests) et redonne les **empreintes gelées**. Les **95 symboles** sont
exactement les 91 de `c46d531` **plus 4** ajouts, sans aucune disparition.

Quatre constats **nouveaux** sortent de cet audit et ne figuraient pas dans les rapports précédents :

1. **Les « 8 assertions LP64 » sont 14.** `core/tests/test_rf_frontend.cpp` lignes 86–101 contient
   14 assertions `sizeof`/`offsetof` en littéraux (4 + 4 pour `lsim_device_rf` et `lsim_gateway_rf`,
   6 pour `lsim_closed_loop_v4_args`). **11 des 14** échouent en i386 d'après la table `abi_layout` elle-même ; 3 sont
   indépendantes de l'ABI (décalage 0 de `present` dans les deux structures, décalage 8 de `v3`).
   Le chiffre « 8 » sous-estime la dette de 6 assertions. *(Corrigé le 2026-10-31 : la première
   rédaction affirmait à tort que les 14 échouaient ; détail dans `AUDIT_COMPLEMENT.md` §1.)*
2. **La sauvegarde F2 + G1 est complète mais son `.git` est décalé d'un push.** L'extraction est
   identique **sauf** `.git/refs/remotes/origin/…` (qui pointe `c77f8eb` dans l'archive, `68176d6`
   en direct) : l'archive a été prise avant le push. Le contenu (HEAD `68176d6`, 332 fichiers) est
   identique. Toute formule « `diff -r` identique » doit désormais exclure cette référence.
3. **F1 n'est pas reproduit** par la sonde reconstruite : 40 graines sur `quartier_sf9` puis 72 runs
   (3 exemples × 12 graines × 2 jeux d'options de trace) donnent **0 échec**, alors que la
   description d'origine annonce des échecs aux graines 11 et 38. La sonde d'origine est perdue.
4. **Le dépôt principal `/home/user/simulateur-de-reseau-lorawan` n'est pas propre** : HEAD
   `1f43370` intact et reflog sans commit/reset (`clone` + `checkout` seulement), mais l'arbre porte
   **47 fichiers modifiés + 41 non suivis** — un instantané R2b antérieur à `9686c25`, jamais
   commité, supplanté par la branche. Ce n'est pas une régression de nos phases, mais c'est un
   risque de source de vérité.

---

## 1. Sécurisation de l'état

| Contrôle | Résultat |
|---|---|
| `git rev-parse HEAD` | `68176d64869298932f32b7458ddc1beb51449f3e` |
| `git status --porcelain` | **0** entrée (arbre propre) |
| `git ls-remote origin refs/heads/arena/…` | `68176d6…` — **identique au local** |
| `git ls-remote origin refs/heads/main` | `1f4337039c9ea10e2689600a67b63ca07bfe5318` — **intact** |
| Dépôt principal — HEAD | `1f43370` — **intact** |
| Dépôt principal — reflog | 2 entrées : `clone` puis `checkout main → arena/…`, **aucun commit/reset/merge** |
| Dépôt principal — arbre | **47 ` M` + 41 `??`** = instantané pré-`9686c25`, non commité (voir §6) |
| Commits de la branche depuis `main` | **48** |
| Fichiers suivis | **332** |
| Sauvegarde F2 + G1 | `sha256sum -c` **OK**, extraction identique hors référence distante, clone `68176d6`, 0 sale, 332 fichiers, bundle complet |

Détail des sauvegardes et de leur restauration : `AUDIT_BILAN_SAUVEGARDES.md`.

---

## 2. Méthode

Chaque contrôle a été **rejoué depuis `68176d6`**, pas relu dans un rapport :

1. `git` : état, historique, périmètre de chaque commit de phase.
2. **Build neuf** dans `/tmp/audit_build` (`cmake` configure + build complets, aucun cache réutilisé).
3. **Build de comparaison** au commit `c46d531` (pré-R2b) dans `/tmp/pre_r2b` pour la liste des
   symboles, et au commit `1f43370` (main) dans `/tmp/base_audit` pour situer la base publique.
4. Harnais ABI compilé seul en x86-64 et en i386 (`-m32 -ffreestanding -c`).
5. Suites complètes : `lsim_tests`, `ctest`, `pytest python/tests`.
6. Sondes indépendantes pour F1 (`build_trace`, 40 graines puis 72 runs) et F6 (`d0` avec/sans relief).
7. Empreintes gelées par `scripts/mac_baseline_dump.py` sur le build neuf.

Les commandes exactes et leurs sorties figurent dans les sections suivantes ; elles sont
rejouables telles quelles.

---

## 3. Audit de la chaîne R1 → R2b → F7 → F2 + G1

### 3.1 Périmètre des commits (reproductible)

| Commit | Objet | Périmètre | Lignes |
|---|---|---|---|
| `c46d531` | R1 — caractérisation RF | 2 fichiers de test | +330 / −0 |
| `2202782` | R2b — frontal RF v4 | 16 fichiers | +1634 / −37 |
| `c77f8eb` | F7 — dispositions ABI 32/64 | 2 fichiers de test | +1641 / −54 |
| `68176d6` | F2 + G1 — imports et GeoJSON | 2 fichiers de test | +216 / −0 |

Cohérence : R1 et R2b ne se recouvrent pas (R1 = mesure gelée, R2b = code) ; F7 ne touche que des
tests ; F2 + G1 ne touche que des tests. **Aucune phase ne modifie une phase antérieure** :
`git log --oneline c46d531..HEAD -- core/tests/test_rf_frontend.cpp` renvoie un seul commit
(`2202782`), donc F7 et F2 + G1 n'ont pas retouché le fichier RF.

### 3.2 Contrat RF par terminal et par passerelle

**Contrat** (`core/include/lsim/c_api.h`, section « Frontal RF v4 ») :
`lsim_device_rf` et `lsim_gateway_rf` portent `present` à bits indépendants
(`LSIM_RF_HAS_ANTENNA_GAIN = 1`, `LSIM_RF_HAS_CABLE_LOSS = 2`), bornes `|G| ≤ 40 dBi`,
`0 ≤ L ≤ 40 dB`, valeurs non finies refusées, table « 0 ou complète ». Antenne réciproque :
`RSSI_ul = (P_tx + G_d − L_d) + (G_g − L_g) − PL − shadowing`,
`RSSI_dl = P_gw + (G_g − L_g) − PL + (G_d − L_d) + offset`, donc les termes terminaux s'annulent
et le gain est compté **une fois**. Quand une entrée passerelle est fournie, son gain **remplace**
`lsim_gateway.antenna_gain_dbi` (pas de cumul).

**Vérifications** :
- 11 tests C++ (`core/tests/test_rf_frontend.cpp`) : chaîne, bornes, indépendance des champs,
  gain montant « une fois », perte de câble, remplacement du scalaire passerelle, table 0/complète,
  bits inconnus et valeurs hors bornes, gain compté une fois en descente, validation v4.
- 30 tests Python (`python/tests/test_rf_frontend.py`) : `None` ≠ 0, bits, chaîne, bornes,
  sélecteurs de routage, espions sur les symboles, absence d'appel `lsim_mesh_*`, égalité **bit à
  bit** d'une table neutre avec l'absence de table, refus des tables partielles.
- 24 tests R1 (`python/tests/test_rf_characterization_r1.py`) figent le comportement **antérieur**
  (gain passerelle +3 dBi = +3 dB, absence de gain terminal dans l'ancien modèle, réciprocité de
  descente, sensibilité RAK7249, collisions et frontière de capture à 6 dB).

Exécution ciblée : **129 tests passés** (`test_rf_frontend.py`, `test_rf_characterization_r1.py`,
`test_abi_v3_contract.py`, `test_geo.py`, 16 subtests).

**Réserve de preuve** : les mutations de R2b (routage forcé, frontaux ignorés, double comptage,
gardes partielles) sont **rapportées** mais **non rejouées** ici ; leurs scripts n'existent plus
(§6). Elles ne sont donc pas comptées comme validées par cet audit.

### 3.3 Compatibilité binaire : 91 anciens + 4 nouveaux

| Build | Commit | Symboles `lsim_*` |
|---|---|---|
| `main` | `1f43370` | **79** |
| pré-R2b | `c46d531` | **91** |
| courant | `68176d6` | **95** |

`comm -23` (anciens absents du courant) : **0**. `comm -13` (ajouts) : exactement
`lsim_simulate_uplinks_trace_v3`, `lsim_simulate_uplinks_trace_gw2_v2`,
`lsim_simulate_uplinks_multi_dl_v2`, `lsim_simulate_closed_loop_v4`.
Liste triée du build neuf : SHA-256 `e8b97058ca45d79bb902c69aeac666e6eaa3a4d25e3bfa1a9ff99e115494e234`,
**identique** à celle du build de travail.

Écart documentaire à noter : la comparaison « 91 → 95 » est celle de `c46d531` → `68176d6`, **pas**
celle de `main` (79). Les deux chiffres sont exacts, mais ils ne parlent pas du même point de départ.

### 3.4 Pont Python v4

- Décision de routage **centralisée** : `trace_native_function()` et `multi_dl_native_function()`
  (`python/lsim/simulator.py`) — dès qu'un frontal est fourni, l'ancien symbole n'est plus appelé.
- `python/lsim/rf.py` : `DeviceRf` / `GatewayRf`, `None` = champ absent (jamais 0 implicite),
  conversion en structures C avec `present` calculé.
- `python/lsim/closed_loop_v3.py` : bascule v3 → v4.
- `simulate_uplinks_multi` **n'a pas** de paramètre RF (vérifié dans la signature) : c'est la
  limitation documentée, pas un oubli silencieux.

### 3.5 Assertions ABI x86-64 et i386

| Contrôle | Mesure |
|---|---|
| `static_assert` dans `core/tests/abi_layout.cpp` | **458** |
| Harnais x86-64 (`-DABI_LAYOUT_STANDALONE`), exécuté | **53 structures, 454 grandeurs** |
| Harnais i386 (`-m32 -ffreestanding -std=c++17 -c`) | **objet produit**, assertions évaluées à la compilation |
| `test_abi_v3_prep.cpp` | aucune valeur numérique en dur ; alias `exp = abi_layout::expected` |
| Littéraux LP64 restants | **14** dans `test_rf_frontend.cpp` (lignes 86–101) |
| Édition de liens 32 bits | **impossible** : `gcc -m32` échoue (`cannot find -lgcc`), pas de CRT ni libc 32 bits |

**Portée de la preuve** : les dispositions sont vérifiées sur les deux ABI ; le **moteur 32 bits**
n'est ni compilé ni exécuté. Aucune affirmation de fonctionnement i386 n'est faite dans cet audit.

### 3.6 Isolation des imports

- 4 tests dans `PathIsolationTests` : 3 scans textuels historiques **inchangés** + 1 test
  d'exécution (F2) à cinq marqueurs (import direct, chemin sans v3, handle unique, rechargement
  dynamique, refus d'une surcharge invalide).
- Exécuté dans cet audit : **55 tests** du fichier `test_abi_v3_contract.py`, dont le test F2,
  tous passés.

### 3.7 Contrat GeoJSON effectivement couvert

`to_geojson` émet une Feature `coverage` par **(passerelle × groupe)** avec exactement 7 clés :
`kind, group, gateway, spreading_factor, tx_power_dbm, range_m, model`. Les 13 tests de
`test_geo.py` (7 historiques + 6 G1) couvrent : format homogène à 7 clés, partition des indices
`0..n−1`, effectifs, portée sous pertes seules (rapport `10^(−6/(10n))` à 1e-4), G × groupes,
non-fusion de deux groupes de configuration identique, cohérence portée / `coverage_radius_m` /
rayon de l'anneau projeté.

**Ce que ces tests ne couvrent pas** : aucune configuration RF résolue (pas d'EIRP, pas de pertes
de câble, pas d'indices par groupe dans la Feature) — `geo.py` (211 lignes) n'a jamais eu ces
objets. Le contrat testé est le contrat réel, pas une cible fonctionnelle.

### 3.8 Empreintes historiques

`scripts/mac_baseline_dump.py` sur le **build neuf** :
`d2cb0fac6c2d99504d888e497f5e07c56ba0f7b81deaf560584c78ee19b4e1ea` (JSON) et
`ed126d7ff5aac3b006f31067d73fb6a5f5b5bf9b597021589910c24db8dc865b` (trace).
**Identiques** aux valeurs gelées, sur les 6 entrées de run et les 6 traces.

---

## 4. Résultats des contrôles d'exécution

| Contrôle | Commande | Résultat |
|---|---|---|
| Build neuf | `cmake -S recovery -B /tmp/audit_build` + `--build` | **OK** |
| Tests C++ | `/tmp/audit_build/lsim_tests` | **685249/685249** |
| `ctest` | `ctest --test-dir /tmp/audit_build` | **1/1** |
| Tests Python | `pytest python/tests` (build neuf) | **1846 passed, 1 skipped, 16 subtests** |
| Empreintes | `mac_baseline_dump.py` (build neuf) | **`d2cb0fac…` / `ed126d7f…`** |
| Symboles | `nm -D` | **95**, identiques au build de travail |
| Ciblé RF/ABI/GeoJSON | 4 fichiers | **129 passed**, 16 subtests |

---

## 5. Coherence : ce qui est prouvé, ce qui ne l'est pas

**Prouvé dans cet audit** : état git, sauvegarde et restauration, build neuf, suites complètes,
empreintes, compatibilité des 95 symboles, layout x86-64, compilation i386 du harnais de
dispositions, routage Python v4 (par lecture + tests), contrat GeoJSON réel, isolation des imports,
`d0` sans relief (invariance reproduite).

**Rapporté mais non rejoué** (et donc **non validé** par cet audit) : mutations R2b ; kit i386 de
F7 (harnais de mutation, `readelf`) ; mutations F2/G1 (rejouées à la phase précédente, scripts
perdus) ; les écarts F6 en dB ; les graines 11/38 de F1.

**Perdu** (incident d'espace de travail antérieur) : `R2B_CLOTURE_AUDIT_ANOMALIES.md` (704 l.,
SHA-256 `1d2f5ad0…`), `F7_ABI_I386_DIAGNOSTIC.md`, `F7_CORRECTION_RAPPORT.md`,
`AUDIT_BRANCHEMENT_V4.md`, les sondes `f1_balayage_40_graines.py`, `gain_global_L0*.py`,
`mesh_rf_probe.py`, `geo_regroupement.py`, et les listes `symbols_before/after`. Les conclusions qui
en dépendent sont reclassées « non reproductibles » dans le registre.

---

## 6. Risques d'état (indépendants du code)

1. **Dépôt principal sale** : 47 ` M` + 41 `??` correspondant à l'instantané de travail antérieur à
   `9686c25`. Risque : confusion de source de vérité, `diff` trompeur, builds involontaires.
   Remède proposé : **ne pas y toucher** (hors périmètre), ou l'archiver puis le nettoyer dans une
   phase autorisée. Aucune écriture n'y a été faite pendant les phases R1 → F2 + G1 (reflog).
2. **Référence distante dans l'archive** : l'archive F2 + G1 précède le push ; `.git/refs/remotes/…`
   y est en retard d'un commit. Le contenu et l'historique sont complets.
3. **Documentation chiffrée incohérente** : `CHANGELOG.md` (entrée RF v4) annonce « 1778 → 1832
   tests Python, 685165 → 685235 vérifications » alors que les mesures du dépôt sont
   **1802 → 1839** et **685165 → 685249** ; l'entrée R1 annonce « 685165/685165, 91 symboles », ce
   qui est exact à `c46d531` mais ne mentionne pas les 1802 tests Python de R1. Aucun impact
   fonctionnel, impact documentaire réel (voir registre, D1).

---

## 7. Conclusion

La branche est **cohérente, constructible à neuf et vérifiable** : un tiers peut, depuis `68176d6`,
reconstruire le cœur, rejouer 685 249 vérifications C++, 1846 tests Python et retrouver les
empreintes gelées. Les quatre phases s'empilent sans se contredire et la surface binaire est
strictement additive (91 + 4).

Les points fragiles sont **documentaires et méthodologiques**, pas fonctionnels : compteur « 8 »
au lieu de 14 pour la dette LP64, preuves antérieures perdues (donc non rejouables), F1 non
reproduit, dépôt principal sale, chiffres du CHANGELOG faux. Ils sont consignés dans
`AUDIT_REGISTRE_ANOMALIES.md` avec preuve, impact, dépendances, correction et risque.

Aucune correction n'a été appliquée : l'audit n'a écrit **que** des fichiers hors dépôt
(`/home/user/AUDIT_*.md`). Le dépôt reste à `68176d6`, arbre propre, distant identique.
