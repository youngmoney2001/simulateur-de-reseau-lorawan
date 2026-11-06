# D3_HANDOFF — reconstruction D3.2 (état au 2026-11-02)

**Fichier de reprise.** À lire en premier après toute perte de session. Il ne dépend d'aucune
conversation : il pointe vers le dépôt, les preuves et les journaux conservés.

> **Ce fichier est lui-même une reconstruction.** Le `D3_HANDOFF.md` original (D3.1, 198 lignes)
> a été détruit avec `/home/user/d3_work` et n'a pas été retrouvé. Celui-ci ne prétend pas le
> remplacer : il documente l'état **après reconstruction**.

---

## 1. Référence

| Élément | Valeur |
|---|---|
| Dépôt | `youngmoney2001/simulateur-de-reseau-lorawan` |
| Branche de travail | `arena/fdc94521-simulateur-de-reseau-lorawan` |
| Base | `8d296e20e395ae8aacd70d5692f518f4a28d6226` |
| **Commit A — reconstruction** | **`d85b50c6f1f81c30600ead1d4f45f335a6c44ae6`** |
| **Commit B — reconstruction** | **`dff67ba6f751d1966a89e6ebf07fc1cd13d32c61`** |
| Commits originaux **perdus** | `7d9caef36b1f4b07f3d3057ecada7da6dc540b34` · `004b69dd46fd21d84e3d722a164ce2e4a3601bc1` |
| `main` à préserver | `1f4337039c9ea10e2689600a67b63ca07bfe5318` (locale et distante) |
| Clone de reconstruction | `/home/user/recon` (HEAD `dff67ba`, arbre propre) |
| Clone de référence (échec attendu) | `/home/user/ref_f1` (`8d296e2` + tests, **sans** correction) |
| Clone de contrôle documentaire | `/home/user/docs_work` (`8d296e2` + docs seules) |
| Interpréteur / outillage | `/home/user/.venv-recon/bin/python` (cmake 4.4.4, pytest 9.2.0) |
| Dépôt principal (interdit) | `/home/user/simulateur-de-reseau-lorawan` (88 entrées préexistantes) |
| Preuves | `/home/user/d3_recon_preuves/` |

**Aucun push, merge ou déploiement. `main` intacte. Dépôt principal non touché.**

---

## 2. Ce qui a été perdu, et comment

Le 2026-11-02, l'environnement de travail a été réinitialisé entre deux tours. Ont disparu
ensemble : `/home/user/recovery` (portant les commits `7d9caef`, `004b69d` et la base `8d296e2`),
`/home/user/d3_work` (rapports, 50 journaux, 18 sondes, 2 patchs), `/home/user/sauvegardes`
(10 archives + 30 fichiers annexes), `/home/user/.venv-lsim`, et les clones `/tmp/d3_clone`,
`/tmp/d3_fixa`, `/tmp/d3_docs`, `/tmp/d3_instr`, `/tmp/d3_verify`, `/tmp/d3_before`.

Les commits n'avaient **jamais été poussés** : `origin/arena/fdc94521-…` est resté à `8d296e2`.
Recherche forensique complète (magasins Git, reflogs, objets *dangling*, bundles, tout le système de
fichiers, API GitHub) : **rien retrouvé**. L'API GitHub répond `422 « No commit found »` pour les
deux SHA.

---

## 3. Anomalies examinées et statuts

| ID | Statut | Résumé |
|---|---|---|
| **F1** | **CORRIGÉE** (commit `d85b50c`) | Borne `MAX_ITERATIONS` 12 → 64 + détection de cycle. Cause **reproduite** : 69/120 configurations échouaient, toutes à la limite ; elles convergent en 13 à 21 itérations. Les 51 configurations déjà convergentes sont **identiques au bit près**. |
| **F1-b** | **REJETÉE** (rapporté) | Amortissements `inter` et `union` : aucune convergence en 128 itérations. Mesure non rejouée le 2026-11-02 (sonde perdue). |
| **F6** | **PARTIELLEMENT RÉSOLUE** (rapporté) | `+2`, `+5`, `+7` dB et `24,633450` dB expliqués et documentés ; `12 dB` et `−91,892118 dBm` non reconstruits. |
| **M2** | **REQUALIFIÉE** (rapporté) | `d0` n'est pas « sans effet » : `ΔPL = (20 − 10n)·log10(d0₂/d0₁)` = −7 dB à n = 2,7. |
| **RF-YAML** | **DOCUMENTÉE + TESTÉE** (commit `dff67ba`) | `rf:` refusé racine et groupe ; deux tests le figent. |
| **MULTI-V4** | **DOCUMENTÉE + TESTÉE** | Tableau des 9 chemins ; aucun `multi_v4`, mesh sans RF. |
| **M3** | **DOCUMENTÉE** | Tables partielles refusées (statut 301) ; mesh sans capacité RF. |
| **GEO-RF** | **DOCUMENTÉE + TESTÉE** | 7 clés GeoJSON, aucune clé de gain/EIRP/câble. |
| **M1** | **EN ATTENTE DE PREUVE** | Document source perdu. |
| **M4** | **EN ATTENTE DE PREUVE** | Dépend de M1–M3. |

---

## 4. Commandes de reprise (toutes reproductibles)

```bash
# environnement
python3 -m venv /home/user/.venv-recon
/home/user/.venv-recon/bin/python -m pip install cmake pytest pydantic pyyaml pyarrow \
    cryptography websockets openpyxl reportlab rasterio

# clone + build
git clone --branch arena/fdc94521-simulateur-de-reseau-lorawan \
  https://github.com/youngmoney2001/simulateur-de-reseau-lorawan.git /home/user/recon
cd /home/user/recon
/home/user/.venv-recon/bin/cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
/home/user/.venv-recon/bin/cmake --build build --parallel "$(nproc)"
./build/lsim_tests                      # attendu : 685249/685249
LSIM_LIBRARY=$PWD/build/liblsim_core.so PYTHONPATH=python \
  /home/user/.venv-recon/bin/python -m pytest python/tests -q

# rejeu des 120 configurations F1
LSIM_LIBRARY=$PWD/build/liblsim_core.so PYTHONPATH=$PWD/python \
  /home/user/.venv-recon/bin/python /home/user/d3_recon_preuves/probes/p_f1_120.py \
  /home/user/recon /tmp/f1_120.json
```

---

## 5. Résultats de référence à retrouver

| Mesure | Valeur attendue |
|---|---|
| `lsim_tests` | 685 249 / 685 249 |
| `pytest` (base) | 1 847 réussis, 0 ignoré, 16 sous-tests |
| `pytest` (après A) | 1 849 réussis |
| `pytest` (après B) | 1 852 réussis |
| 120 configs, code d'origine | **69 échecs / 120** (join 3/40, dl2 33/40, dl1 33/40) |
| 120 configs, code corrigé | **0 échec / 120**, itérations 9 à 21 |
| Configurations de référence | 51/51 empreinte **et** itérations identiques |
| Distribution des ex-échecs | 13→23, 14→23, 15→11, 16→7, 17→3, 21→2 |

---

## 6. Décisions

- **D1, D2** : exécutées (Phase A, commit `8d296e2`, poussé).
- **D3.1** : clôturée ; sa poursuite était autorisée.
- **D3.2** : autorisée. Les deux commits originaux ont été créés puis **perdus**.
- **Reconstruction** : autorisée le 2026-11-02 (option A), avec trois arbitrages : poursuivre en
  documentant les écarts, rejouer les 120 configurations, identifier explicitement les commits
  comme reconstruits.
- **Push** : **non autorisé** à ce jour.
- **Interdits permanents** : toucher au dépôt principal ou à `main`, déployer, supprimer les
  archives, présenter un artefact reconstruit comme un original.

---

## 7. Prochaine action exacte

1. **Attendre une décision distincte pour le push** de `dff67ba`.
2. Ne rien modifier avant cette décision.
3. Si la session est perdue : tout ce qui est dans `/home/user/d3_recon_preuves` disparaîtra ;
   seule la copie hors de l'environnement (ou le push) le préserve.

---

## 8. Reprise après perte de session (procédure)

1. Lire ce fichier et `RAPPORT_D3_2_RECONSTRUIT.md`.
2. Vérifier `git -C /home/user/recon log --oneline -3` :
   attendu `dff67ba`, `d85b50c`, `8d296e2`.
3. Vérifier `git -C /home/user/recon status --porcelain` : vide.
4. Vérifier que le distant est toujours à `8d296e2` (aucun push effectué).
5. Si `/home/user/recon` a disparu : recommencer à la section 4, puis reconstruire les deux
   changements et **vérifier les empreintes de patchs** (`7ab7bc5a…` et `64bceb4d…`) avant tout
   commit.
