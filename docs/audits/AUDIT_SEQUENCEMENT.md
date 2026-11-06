# Séquencement proposé des prochaines phases

**Base** `68176d6` · **Aucune phase n'est autorisée par ce document** : il propose un ordre, des
dépendances et des critères d'acceptation. Chaque phase reste soumise à validation explicite.

---

## 0. Principes de séquencement

1. **Consolider avant d'étendre** : corriger d'abord ce qui rend les preuves fragiles (documentation
   fausse, preuves perdues, dette de test) — c'est sans effet sur le comportement.
2. **Aucune phase fonctionnelle sans preuve reproductible préalable** : F1 et F6 restent ouverts
   tant que leurs sondes ne sont pas rétablies.
3. **Une phase = un périmètre de fichiers annoncé** ; toute extension est une nouvelle phase.
4. **Invariants de chaque phase** : 95 symboles (ou 96 avec `multi_v2`), empreintes
   `d2cb0fac6c2d9950` / `ed126d7ff5aac3b0` inchangées **sauf mention explicite contraire**, suite
   C++ complète, suite Python complète, `main` intact, aucun push forcé.

---

## 1. Vue d'ensemble

| Phase | Objet | Type | Dépend de | Risque | Priorité |
|---|---|---|---|---|---|
| **A** | Consolidation documentaire et des preuves | docs + scripts | — | **nul** | 1 |
| **B** | Dette LP64 : 14 littéraux → constantes `abi_layout` | tests | A | faible | 2 |
| **C** | RF dans les scénarios YAML | production | A | moyen | 3 |
| **D** | `simulate_uplinks_multi` v4 et RF mesh | production | C, design mesh | moyen | 4 |
| **E** | Diagnostic F1 / F6 (sans correction) | sondes | A | nul | 5 |
| **F** | Unification F6 / `d0` | production | E + décision de modèle | **très élevé** | 6 |
| **G** | GeoJSON avec configuration RF résolue | production | C, D | moyen | 7 |
| **H** | Faisabilité d'un moteur i386 complet | outillage | — | nul | 8 (ou clôture) |

---

## 2. Phase A — Consolidation documentaire et des preuves

**Objectif** : rendre l'état **auto-descriptif** et les preuves **rejouables**.

**Périmètre** : `CHANGELOG.md`, `docs/audits/` (nouveau), `scripts/preuves/` (nouveau),
rapports de phase importés. **Aucun fichier de code.**

**Travaux**
1. Corriger les chiffres du CHANGELOG (D1) : 1802 → 1839 tests Python, 685165 → 685249 C++,
   et préciser la base de chaque comparaison (79 / 91 / 95 symboles).
2. Consigner « 14 assertions LP64 » et non « 8 » (LP64-14), y compris dans la doc RF.
3. Verser dans `docs/audits/` : R1, R2b, F7, F2 + G1, audit global, registre, matrice, bilan,
   séquencement — avec leurs SHA-256.
4. Verser dans `scripts/preuves/` les sondes qui servent de preuve (balayage de graines, `d0`,
   vérification des symboles, harnais ABI) pour qu'elles cessent d'être perdues.
5. Mentionner explicitement l'écart D2 (archive prise avant push).

**Critères d'acceptation**
- `git diff` limité à `docs/`, `CHANGELOG.md`, `scripts/` ; **aucun** fichier `core/` ou `python/lsim/`.
- Suites inchangées : 685249 C++, 1846 Python, empreintes identiques.
- `sha256sum -c` de la nouvelle archive **après** push, `diff -r` **strictement** vide.

---

## 3. Phase B — Dette LP64 (tests seulement)

**Dépend de** A. **Périmètre** : `core/tests/test_rf_frontend.cpp` uniquement.

**Travaux** : remplacer les 14 littéraux (lignes 86–101) par
`abi_layout::expected::size_lsim_device_rf`, `off_lsim_device_rf__present`, etc.

**Critères d'acceptation**
- `grep -c "sizeof(lsim_.*), [0-9]"` ⇒ **0** dans le fichier.
- Suites C++ **685249** vérifications (aucune perte), `ctest` 1/1, Python 1846.
- Structures publiques **inchangées** (`git diff -- core/include` vide) ; `abi_layout.cpp` inchangé.
- Recompilation i386 du **harnais** toujours verte (les 14 assertions deviennent compilables).

**Risque** : faible (test). **Réserve** : la compilation i386 complète du fichier de test reste
impossible sans CRT 32 bits — la phase ne prouve que la **disposition**.

---

## 4. Phase C — RF dans les scénarios YAML

**Dépend de** A. **Périmètre annoncé** : `python/lsim/scenario.py`, `python/lsim/simulator.py`,
`python/lsim/rf.py`, `schemas/`, `python/tests/test_scenario*.py`, `python/tests/test_rf_frontend.py`,
`docs/RF_FRONTEND_V4.md`.

**Conception à valider avant code** : bloc `rf:` par groupe (`antenna_gain_dbi`, `cable_loss_db`)
et par passerelle ; champs optionnels indépendants ; **absent ⇒ hash inchangé** ; propagation vers
`DeviceRf`/`GatewayRf` ; refus explicite des configurations partielles.

**Critères d'acceptation**
- Scénarios **sans** `rf:` : empreintes `d2cb0fac…` / `ed126d7f…` **identiques**, 1846 tests.
- Scénarios **avec** `rf:` : routage vers v4 prouvé par espion ; un scénario de référence produit
  un RSSI montant/descendant conforme aux formules du contrat (à 1e-9).
- Schémas régénérés et testés (`test_channel_schema.py` et équivalents).
- Aucune modification de `geo.py` dans cette phase.

**Risque** : moyen. Précédent à éviter : écrire un bloc vide qui change le hash (incident R2b).

---

## 5. Phase D — `simulate_uplinks_multi` v4 et RF mesh

**Dépend de** C, et d'un **design mesh** (gains des deux extrémités, pertes émetteur/récepteur,
pas de réutilisation implicite du sous-GHz).

**Travaux** : nouveau symbole `lsim_simulate_uplinks_multi_v2` (surface **96** symboles), paramètres
Python, refus explicite si `mesh_rf` est partiel (règle 0 ou complet).

**Critères d'acceptation**
- `comm -13` sur les symboles ⇒ **exactement 1** ajout ; aucun retrait.
- Chemin sans `mesh_rf` : résultats mesh **identiques au bit près** à `68176d6`.
- Chemin avec `mesh_rf` complet : effet mesuré sur RSSI des deux extrémités, testé.
- `mesh_rf` partiel ⇒ statut 301 (refus), testé.

**Risque** : moyen (surface ABI additive, mais empreintes mesh propres).

---

## 6. Phase E — Diagnostic F1 / F6 (aucune correction)

**Dépend de** A (sondes versionnées). **Périmètre** : `scripts/preuves/`, aucun code de production.

**Travaux**
1. Rétablir un balayage **défini explicitement** (scénarios, options, graines) et publier le script.
2. Rejouer les sept mesures F6 (causal, trace neutre, `link_adr` +2, multi +5, mesh −24,633450,
   `mesh_rf` partiel 12, `d0` −91,892118) et produire un tableau chiffré.
3. Conclure pour chaque point : **reproduit** / **non reproduit** / **clos avec preuve négative**.

**Critères d'acceptation**
- Chaque point F1/F6 a une preuve reproductible ou une déclaration explicite de non-reproduction.
- Aucune modification de `core/` ni `python/lsim/`.
- Les scripts sont dans le dépôt et rejouables en une commande documentée.

**Ce que cette phase ne fait pas** : elle ne corrige **rien**. C'est la condition d'entrée de F.

---

## 7. Phase F — Unification F6 / `d0`

**Dépend de** E **et** d'une décision explicite de modèle (honorer `d0` ou documenter son invariance).
**Risque : très élevé** — c'est la seule phase susceptible de changer **les deux empreintes**.

**Prérequis d'entrée**
1. Tableau F6 complet et reproductible (phase E).
2. Décision écrite : modèle cible pour `d0`, cohérence causal/trace/multi/mesh.
3. Accord explicite sur le changement d'empreintes.

**Critères d'acceptation**
- Nouvelles empreintes publiées **et** justifiées écart par écart.
- Suite C++ et Python complètes vertes ; tests R1 relus et, si nécessaire, requalifiés
  (ils figent l'ancien comportement : un changement de modèle les invalide **par construction**).
- Aucune modification de l'algorithme ADR.

---

## 8. Phase G — GeoJSON avec configuration RF résolue

**Dépend de** C (source des paramètres) et D (si mesh visible sur la carte).

**Travaux** : regroupement par configuration résolue, champs optionnels (`eirp_dbm`,
`device_indices_in_group`) **seulement** si hétérogène, conservation du format à 7 clés sinon.

**Critères d'acceptation**
- Les **6 tests G1 existants restent verts sans modification** (format homogène préservé).
- Nouveaux tests : groupe hétérogène ⇒ champs optionnels présents et ordonnés ; groupe homogène ⇒
  **exactement** 7 clés.
- `web/` continue de lire le GeoJSON (test de contrat).

**Risque** : moyen (contrat consommé par l'interface web).

---

## 9. Phase H — Moteur i386 complet

**Dépend de** la disponibilité d'une chaîne 32 bits (multilib ou conteneur). Hors ligne, la réponse
est **non** : `gcc -m32` ne lie pas (`cannot find -lgcc`).

**Décision attendue** : soit clôturer définitivement (limite assumée, répétée dans chaque rapport),
soit ouvrir une phase d'outillage. **Aucune correction de code n'est en jeu.**

---

## 10. Ce qui reste explicitement hors séquence

| Sujet | Raison |
|---|---|
| Nettoyage du dépôt principal sale (E1) | hors périmètre d'écriture ; nécessite un accord et une archive préalable |
| Re-identification M1 / M4 | dépend de la restitution du document d'audit perdu |
| Fusion de branches, merge, déploiement | interdits par les restrictions en vigueur |
| Modification de l'algorithme ADR | décision verrouillée : jamais |
| Modification des 8 (14) assertions sans phase B | F7 l'interdisait ; B est la phase dédiée |

---

## 11. Ordre recommandé, en une phrase

**A** (rendre les preuves durables) → **B** (solder la dette de test) → **C** (RF utilisable dans un
scénario) → **E** (diagnostiquer F1/F6) → **F** (unifier, avec accord sur les empreintes) →
**D** puis **G** (mesh et carte), **H** restant une décision d'outillage séparée.
