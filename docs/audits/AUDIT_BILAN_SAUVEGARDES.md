# Bilan des preuves de sauvegarde et de restauration

**Référence auditée** `68176d6` · **Répertoire** `/home/user/sauvegardes/` (hors dépôt, comme exigé).

> **Rectification (Phase A, 2026-10-31).** §4 classait les mutations R2b parmi les éléments « non
> reproductibles ». Elles sont en réalité **rapportées, non rejouées** : les essais ont bien été
> exécutés et détectés lors de R2b, seuls leurs scripts ont disparu. §4 distingue désormais les
> deux cas ; **§1** reçoit une note de périmètre qui explicite les **dix** archives présentes. Ce
> document porte donc une empreinte SHA-256 différente de celle du livrable de session
> (`57d7079c…`) ; aucun autre passage n'a changé.

---

## 1. Inventaire vérifié le 2026-10-31

`sha256sum -c` a été exécuté sur **les neuf fichiers `.sha256`** : **18 artefacts sur 18 OK**.

| Archive | Couvre | tar.gz (octets / SHA-256 tronqué) | bundle (octets / SHA-256 tronqué) |
|---|---|---|---|
| `m64-base_20261031T173025Z_e3b0c44298fc` | base de travail `m64` (pré-R1) | 2 560 370 / `2a5029a1…` | 1 653 822 / `82e1eb30…` |
| `r1_20261031T173707Z` | R1 (pré-commit) | 3 849 879 / `8e830fd5…` | 1 655 849 / `97d5b265…` |
| `r1-final_20261031T173917Z` | **`c46d531`** (R1 commité) | 3 850 000 / `4137283a…` | 1 655 849 / `b09a9a90…` |
| `r2b_20261031T175618Z` | R2b (pré-commit) | 4 068 240 / `368f8f23…` | 1 637 371 / `994ca4da…` |
| `r2b-f7pre_20261031T180423Z` | **`2202782`** (R2b commité) | 4 068 240 / `5854462a…` | 1 637 371 / `d1b1d1d0…` |
| `f7_20261031T180738Z` | F7 (pré-commit) | 4 083 087 / `54de6a3d…` | 1 637 371 / `d1b1d1d0…` |
| `f7-final_20261031T181131Z` | **`c77f8eb`** (F7 commité) | 4 113 683 / `61546b36…` | 1 653 855 / `4e000c2d…` |
| `f7-pre-f2g1_20261031T181820Z` | `c77f8eb` (copie de sûreté avant F2/G1) | 4 113 678 / `e96de9f2…` | 1 653 855 / `4e000c2d…` |
| **`f2g1_20261031T182441Z`** | **`68176d6`** (état courant) | **2 879 415** / `37e2ed62…` | **1 657 837** / `2bb2b9a3…` |

SHA-256 complets des deux artefacts de référence :

- `f2g1_20261031T182441Z.tar.gz` : `37e2ed626217af25f94b1c3d5dd055af060aec40f5ea56b7693ca8ce85212f12`
- `f2g1_20261031T182441Z.bundle` : `2bb2b9a3d7a38d83eb016fbad00897e4d80d1a5c47c7ee044bbda4cf1bde408f`

Remarque : le `bundle` est **volontairement** identique entre `f7-pre-f2g1` et `f7-final` — un bundle
ne contient que des commits, et F7 était déjà commité. C'est le **tar** qui porte l'état de travail.

> **Note de périmètre — dix archives présentes.** Le répertoire contient **dix archives** : les
> **neuf** de l'inventaire historique initial ci-dessus, **plus l'archive supplémentaire de
> pré-Phase A** `phaseA-pre_20261031T184643Z`, créée à **18:46:43Z**, soit **22 minutes après** la
> dernière archive inventoriée, `f2g1_20261031T182441Z` (18:24:41Z) ; elle ne faisait donc pas
> partie de l'inventaire initial, et n'est donc pas comptée dans les **18 artefacts sur 18 OK**
> ci-dessus. Son contenu a néanmoins été contrôlé séparément : `tar tzf` sur son listing ne retourne
> **aucune** occurrence de « anomalie » ni de « AUDIT », et son empreinte a été vérifiée en clôture
> de Phase A (`sha256sum -c` ⇒ **OK**, `8fdd5515…` pour le `tar.gz`, `2bb2b9a3…` pour le `bundle`).

---

## 2. Restaurabilité de la sauvegarde courante (rejouée pendant l'audit)

| Étape | Commande | Résultat |
|---|---|---|
| Intégrité | `sha256sum -c f2g1_…sha256` | **OK** (2/2) |
| Extraction | `tar xzf` dans `/tmp/audit_restore` | **OK**, 332 fichiers suivis |
| Comparaison | `diff -r --exclude=__pycache__` avec `/home/user/recovery` | **2 écarts, tous dans `.git/refs/remotes/origin/…`** (voir §3) |
| Clone du bundle | `git clone f2g1_….bundle /tmp/audit_clone` | HEAD **`68176d6`**, **0** fichier sale, **332** fichiers suivis |
| Complétude | `git bundle verify` | « records a complete history » |
| Re-test à la création | suite complète depuis le clone restauré | **1846 passed / 1 skipped / 16 subtests**, empreintes `d2cb0fac…` / `ed126d7f…` |

La recompilation depuis l'archive **n'a pas été refaite** dans cet audit (elle l'a été à la clôture
de F2 + G1 : suite complète verte + empreintes). Ce qui a été rejoué ici : intégrité, extraction,
clone, vérification de complétude.

---

## 3. Écart constaté : référence distante en retard d'un push

Le `diff -r` n'est **pas** strictement vide :

```
.git/refs/remotes/origin/arena/fdc94521-…      < c77f8eb7…   > 68176d64…
.git/logs/refs/remotes/origin/arena/…          ligne « update by push » absente de l'archive
```

**Cause** : l'archive a été prise **après le commit mais avant le push**. Le contenu (arbres,
commits, `HEAD`) est identique ; seule la **mémoire locale du distant** diffère. Aucune
conséquence sur la restaurabilité — un clone du bundle repart de `68176d6`.

**Recommandation** : prendre les prochaines archives **après** le push, ou exclure explicitement
`refs/remotes` des comparaisons.

---

## 4. Ce que les archives ne contiennent pas

Les neuf archives ne sauvegardent que **le dépôt** (`recovery/`). Les rapports et sondes vivaient
dans `/home/user` et **n'ont jamais été archivés** :

| Élément perdu | Empreinte connue |
|---|---|
| `R2B_CLOTURE_AUDIT_ANOMALIES.md` (704 l.) | `1d2f5ad06e0f042630796325426643704cf670b5810ef125a0af907c272cc03e` |
| `F7_CORRECTION_RAPPORT.md` (367 l.) | `9125ce2d9612feead5b0d6a9f009100e0f4ff990dc839eda68ad04ca84979e29` |
| `F7_ABI_I386_DIAGNOSTIC.md` (501 l.) | `4d2ac56150dfbd8784319773f24bd309e4606ee12df55fc0a7d60481c2ce7dbf` |
| Sondes `f1_balayage_40_graines.py`, `gain_global_L0*.py`, `mesh_rf_probe.py`, `geo_regroupement.py` | perdues |
| `symbols_before_9686c25.txt` (91 l.), `symbols_after_r2b_final.txt` (95 l.) | perdues |

Vérification : `tar tzf` sur les neuf archives ⇒ **aucune** occurrence de « anomalie » ou « AUDIT ».

**Conséquence** : les contrôles qui en dépendent ne sont **pas rejouables** dans cet audit. La
qualification diffère selon la nature de la preuve perdue, et les deux cas ne doivent pas être
confondus (voir `AUDIT_REGISTRE_ANOMALIES.md`) :

- **non reproductibles** — preuve perdue sans essai antérieur exploitable : F1 (sonde d'origine),
  les écarts F6 en dB, le kit i386 de F7, M1 et M4 ;
- **rapportés, non rejoués** — essais **réellement exécutés** lors de R2b et **détectés**, mais dont
  les scripts ne sont pas conservés : les **quatre mutations** du frontal RF v4. L'absence de rejeu
  n'est **pas** un échec de reproduction.

**Recommandation** : à partir de la prochaine phase, tout rapport ou sonde qui sert de preuve doit
vivre **dans le dépôt** (par exemple `docs/audits/` et `scripts/preuves/`), ou être inclus dans le
tar de sauvegarde. Un dépôt est le seul stockage qui survit à la session.

---

## 5. Verdict

| Question | Réponse |
|---|---|
| La sauvegarde de l'état courant existe-t-elle ? | **Oui** (`f2g1_20261031T182441Z`, tar + bundle + sha256) |
| Est-elle intègre ? | **Oui**, 2/2 `OK` |
| Est-elle restaurable ? | **Oui** : extraction complète, clone à `68176d6`, 0 sale, 332 fichiers, historique complet |
| Est-elle strictement identique ? | **Au contenu oui** ; `.git/refs/remotes` en retard d'un push (sans effet) |
| A-t-elle été re-testée ? | **Oui à sa création** (1846/1/16 + empreintes) ; non recompilée dans cet audit |
| Couvre-t-elle les preuves d'audit ? | **Non** — aucun rapport ni sonde n'est archivé (voir §4) |
