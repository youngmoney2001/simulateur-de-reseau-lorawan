# D3_HANDOFF — version 2 (état au 2026-11-02, base `fd5cdb5`)

**Fichier de reprise.** À lire en premier après toute perte de session.

> **Version 2.** Elle met à jour la version 1 (`dff67ba`, 139 lignes), dont l'empreinte est
> `186d346fb46e7737f7b6905130b5205b4ddb7f5cad75da06f20d3039f5ef1648`. Cette version 1 est
> conservée **à l'octet près** dans `D3_HANDOFF_v1.md` (même empreinte, vérifiable) et dans
> `sauvegardes_d32/d3_recon_preuves_20261102T112641Z.tar.gz`.
>
> **Le handoff D3.1 original (198 lignes) n'a pas été retrouvé.** Il n'est pas reconstitué ici :
> la version 1 se déclarait déjà remplaçante, la version 2 précise l'état réel des faits. Aucune
> des deux ne représente le document D3.1, dont ni le contenu, ni la structure, ni l'empreinte ne
> sont connus.

| Élément | Valeur |
|---|---|
| Rédigé le | 2026-11-02 |
| Base | `fd5cdb5739ad4347b71221a4f8a867f9db7be451` |
| Branche | `arena/fdc94521-simulateur-de-reseau-lorawan` |
| Nature | document de reprise, **non publié** à ce stade |
| Convention | **[M]** mesuré le 2026-11-02 · **[R]** rapporté, non rejoué · **[NV]** non vérifiable |

---

## 1. Référence

| Élément | Valeur | Qualité |
|---|---|---|
| Dépôt | `youngmoney2001/simulateur-de-reseau-lorawan` | [M] |
| Branche de travail | `arena/fdc94521-simulateur-de-reseau-lorawan` | [M] |
| Base de l'audit | `8d296e20e395ae8aacd70d5692f518f4a28d6226` (Phase A) | [M] |
| **Commit A** — reconstruction | `d85b50c6f1f81c30600ead1d4f45f335a6c44ae6` (4 fichiers) | [M] |
| **Commit B** — reconstruction | `dff67ba6f751d1966a89e6ebf07fc1cd13d32c61` (5 fichiers) | [M] |
| **Commit D3.3** — reconstitution des preuves | `fd5cdb5739ad4347b71221a4f8a867f9db7be451` (11 fichiers) | [M] |
| Commits originaux **perdus** | `7d9caef3…` · `004b69dd…` | [NV] — jamais poussés, `422` côté GitHub |
| `main` à préserver | `1f4337039c9ea10e2689600a67b63ca07bfe5318` (locale **et** distante) | [M] |
| Clone de travail | `/home/user/recon` | [M] |
| Commit publié sur la branche | **`dff67ba`** — `origin/arena/…` s'arrête là | [M] |
| Commit **non publié** | **`fd5cdb5`** — présent en local seulement | [M] |
| Fichiers suivis | **359** (350 avant D3.3) | [M] |
| Historique | **172 commits** au total, **52** d'avance sur `main` | [M] |
| Clone de référence (échec attendu) | `/home/user/ref_f1` (`8d296e2`, sans correction) | [M] |
| Clone de contrôle documentaire | `/home/user/docs_work` | [M] |
| Clone de restauration testé | `/home/user/restauration_d32` (`dff67ba`, 350 fichiers) | [M] |
| Dépôt principal (**interdit**) | `/home/user/simulateur-de-reseau-lorawan` — `1f43370`, **88 entrées** | [M] |
| Export en lecture seule | `http://127.0.0.1:8010` — 5 fichiers, `HTTP 200` | [M] |
| Interpréteur / outillage | `/home/user/.venv-recon/bin/python` (cmake, pytest, pydantic, pyyaml, pyarrow, cryptography, websockets, openpyxl, reportlab, rasterio) | [M] |

**État des publications, à la date de rédaction :**

| Événement | État |
|---|---|
| Push de `dff67ba` | **effectué** le 2026-11-02 — `8d296e2..dff67ba`, fast-forward, 2 commits, aucun force |
| Push de `fd5cdb5` | **non autorisé**, non effectué |
| Merge / déploiement | **aucun** |
| `main` | intacte, `1f43370` en local et à distance |

> La version 1 de ce fichier indiquait « push non autorisé à ce jour » : c'était exact au
> 2026-11-02 au matin, périmé depuis.

---

## 2. Ce qui a été perdu, et comment

Le 2026-11-02, l'environnement de travail a été réinitialisé entre deux tours. Ont disparu
ensemble : `/home/user/recovery` (portant les commits `7d9caef`, `004b69d` et la base `8d296e2`),
`/home/user/d3_work` (rapports, ≈ 45 journaux, 18 sondes, 2 patchs), `/home/user/sauvegardes`
(10 archives + fichiers annexes), `/home/user/.venv-lsim`, et les clones `/tmp/d3_clone`,
`/tmp/d3_fixa`, `/tmp/d3_docs`, `/tmp/d3_instr`, `/tmp/d3_verify`, `/tmp/d3_before`.

Les commits n'avaient **jamais été poussés** à ce moment : `origin/arena/…` était resté à
`8d296e2`. Recherche forensique complète (magasins Git, reflogs, objets *dangling*, bundles, tout le
système de fichiers, API GitHub) : **rien retrouvé**. L'API GitHub répond `422 « No commit found »`
pour les deux SHA perdus. **[R]** pour la recherche, **[M]** pour l'absence actuelle des objets.

---

## 3. Anomalies — statut au 2026-11-02

Les 15 anomalies du registre Phase A, plus le sous-item F1-b. Le registre
`docs/audits/AUDIT_REGISTRE_ANOMALIES.md` **n'est pas modifié** : il conserve ses statuts d'origine
(empreinte `e61be133…`, 243 lignes). Le détail est dans
`docs/audits/D3_RECONSTITUTION/SUIVI_ANOMALIES_POST_D3.md`.

| ID | Statut actuel | Résumé | Qualité |
|---|---|---|---|
| **F1** | **CORRIGÉE** pour la non-convergence · **NON REPRODUITE** pour causal/trace | Borne 12 → 64 + détection de cycle (`d85b50c`). 69/120 configurations échouaient à la limite ; 120/120 convergent en 9–21 itérations ; 51/51 identiques | [M] |
| **F1-b** | **REJETÉE — mesurée** | `none` : 13, 13, 15, 16, 14, 21 itérations ; `inter` et `union` : **échec aux 6 configurations** à 128 itérations | [M] |
| **F6** | **PARTIELLEMENT RÉSOLUE** | `+2` / `+5` / `+7` / `−24,633450` / `0` dB = arithmétique de modèle ; **`12` dB** et **`−91,892118` dBm** non reconstruits | [M] pour les 5 premiers, [R] pour les 2 autres |
| **M2** | **REQUALIFIÉE** | `d0` n'est pas neutre : `ΔPL = (20 − 10n)·log10(d0₂/d0₁)` = **−7,000000 dB** à `n = 2,7`, **0** à `n = 2` | [M] |
| **M3** | **PARTIELLEMENT ÉTABLIE** | Refus RF partielle : statut **301** en v4 ; **mesh non conclusif** (aucune capacité RF sur ce chemin) | [R] v4, [M] mesh |
| **RF-YAML** | **DOCUMENTÉE + TESTÉE** | `rf:` refusé à la racine et dans un groupe ; 2 tests (`dff67ba`) | [M] |
| **MULTI-V4** | **DOCUMENTÉE + TESTÉE** | Tableau des 9 chemins ; aucun `multi_v4` ; uplinks multi sans frontal | [M] |
| **GEO-RF** | **DOCUMENTÉE + TESTÉE** | 7 clés GeoJSON, aucun champ de gain/EIRP/câble | [M] |
| **LP64-14** | **OUVERTE** | 14 assertions ABI en littéraux ; 11/14 échouent en i386 | [R] |
| **I386** | **OUVERTE** | Aucun binaire 32 bits ; `-m32` impossible dans cet environnement | [R] |
| **M1** | **OUVERTE — en attente des éléments sources nécessaires à leur instruction** | Document source perdu | [NV] |
| **M4** | **OUVERTE — en attente des éléments sources nécessaires à leur instruction** | Dépend de M1–M3 | [NV] |
| **D1** | **CLOSE pour la correction** | `1832`/`685235` corrigés en `1839`/`685249` (Phase A) ; valeurs d'origine introuvables | [M] / [R] |
| **D2** | **OUVERTE, non instruisable** | Archive concernée perdue | [NV] |
| **E1** | **OUVERTE** | Dépôt principal : 47 modifications + 41 non suivis = **88 entrées** | [M] |
| **E2** | **PARTIELLEMENT REMÉDIÉE** | Preuves perdues circonscrites ; reconstitution + sauvegardes | [M] |

---

## 4. Commandes de reprise

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

# rejeux du 2026-11-02 (≈ 150 s pour le premier)
LSIM_LIBRARY=$PWD/build/liblsim_core.so PYTHONPATH=$PWD/python \
  /home/user/.venv-recon/bin/python scripts/preuves/p_f1b_amortissement.py "$PWD" /tmp/f1b.json 128
LSIM_LIBRARY=$PWD/build/liblsim_core.so PYTHONPATH=$PWD/python \
  /home/user/.venv-recon/bin/python scripts/preuves/p_d0_marge.py "$PWD"
```

> **Note de reprise :** après un `git clone` du distant, le HEAD sera `dff67ba` — `fd5cdb5` n'est
> **pas publié**. Il faut le récupérer depuis une sauvegarde (`sauvegardes_d34/`) ou le reconstruire.

---

## 5. Résultats de référence

| Mesure | Valeur attendue | Qualité |
|---|---|---|
| `lsim_tests` | **685 249 / 685 249** | [M] sur `fd5cdb5`, 2026-11-02 |
| `pytest` sur `fd5cdb5` | **1 854 réussis, 16 sous-tests** (96,65 s) | [M] |
| `pytest` base / après A / après B | 1 847 / 1 849 / 1 852 | [R] — compteurs de D3.2, non remesurés ; la mesure actuelle diffère car toutes les dépendances sont installées (`test_fetch_dem.py` n'est plus ignoré) |
| 120 configs, code d'origine | **69 échecs / 120** (join 3/40 · dl2 33/40 · dl1 33/40) | [M] |
| 120 configs, code corrigé | **0 échec / 120**, 9 à 21 itérations | [M] |
| Configurations déjà convergentes | **51/51** identiques (itérations et empreinte) | [M] |
| Distribution des ex-échecs | 13→23 · 14→23 · 15→11 · 16→7 · 17→3 · 21→2 | [M] |
| F1-b `none` | 13 · 13 · 15 · 16 · 14 · 21 itérations | [M] |
| F1-b `inter` / `union` | échec aux 6 configurations à 128 itérations | [M] |
| `d0` 1→10 | **−7,000000 dB** à `n = 2,7` · **0,000000 dB** à `n = 2` | [M] |
| Marge avant sensibilité | **+20,047 dB** min. sans relief (0 trame < 7 dB) · **−35,712 dB** avec relief (490 trames < 7 dB) | [M] |
| Empreintes de patchs | `7ab7bc5a…` (F1-a) · `64bceb4d…` (doc RF) | [M] |
| Empreintes gelées historiques | `d2cb0fac…` (JSON) · `ed126d7f…` (trace) | [R] — code inchangé, non rejouées |

---

## 6. Décisions

- **D1, D2** : exécutées (Phase A, `8d296e2`, poussées).
- **D3.1** : clôturée.
- **D3.2** : autorisée ; deux commits reconstruits puis poussés sous votre ordre explicite.
- **D3.3** : commit `fd5cdb5` créé localement ; **non poussé**.
- **D3.4** : préparation autorisée — documents et sauvegarde, **sans commit** à ce stade.
- **Texte (A)** : vous renoncez à l'inscrire dans le dépôt, son libellé exact n'ayant pas été
  retrouvé. **Aucune formulation de remplacement n'est inventée.** Voir §10.
- **Interdits permanents** : toucher au dépôt principal ou à `main`, déployer, écraser une
  sauvegarde existante, présenter un artefact reconstruit comme un original.

---

## 7. Prochaine action exacte

1. **Aucune publication** : ni commit, ni push, ni merge, ni déploiement avant autorisation.
2. Lire la revue D3.4 (fichiers, empreintes, différences, restauration).
3. Attendre une décision explicite pour committer les documents, puis pour pousser.

---

## 8. Reprise après perte de session

1. Lire ce fichier, puis `SUIVI_ANOMALIES_POST_D3.md` et `RAPPORT_D3_1_RECONSTITUE.md`.
2. `git -C /home/user/recon log --oneline -5` : attendu `fd5cdb5`, `dff67ba`, `d85b50c`,
   `8d296e2`, `68176d6`.
3. `git -C /home/user/recon status --porcelain` : vide **si** le commit documentaire a été fait ;
   sinon, les documents D3.4 apparaissent en non suivis.
4. `git -C /home/user/recon ls-remote origin refs/heads/arena/fdc94521-simulateur-de-reseau-lorawan` :
   attendu `dff67ba` tant que `fd5cdb5` n'est pas poussé.
5. Vérifier les preuves : `sha256sum -c` sur `d3_recon_preuves/EMPREINTES.sha256` (**13/13**) et sur
   `sauvegardes_d32/SHA256SUMS.txt`.
6. Si `/home/user/recon` a disparu : restaurer depuis `sauvegardes_d34/` (bundle + documents), puis
   vérifier les empreintes de patchs avant toute reconstruction.

---

## 9. Statut des affirmations — ce qui ne doit jamais être aplati

| Catégorie | Contenu |
|---|---|
| **Faits vérifiés [M]** | SHA des commits, arbres, empreintes de patchs, compteurs de tests, 120 configurations, F1-b, écarts `d0`, présence/absence dans les bundles |
| **Résultats rapportés [R]** | compteurs `pytest` 1 847 / 1 849 / 1 852 ; statut 301 en v4 ; 14 assertions et 11 échecs i386 ; `−91,892118` dBm ; empreintes gelées `d2cb0fac…` / `ed126d7f…` ; recherche forensique |
| **Non vérifiable [NV]** | contenu du handoff D3.1 (198 l.) ; 18 sondes et ≈ 45 journaux de D3.1 ; les 14 rapports jamais commités ; les commits perdus `7d9caef` / `004b69d` ; la complétude de la liste des pertes |

---

## 10. Limites documentaires persistantes

| Limite | Portée |
|---|---|
| **Texte (A) introuvable** | le libellé exact exigé pour remplacer « 0 échec : 112 … puis 240 … » n'a été retrouvé nulle part (5 motifs recherchés, 0 occurrence, tar de sauvegarde inclus). Vous renoncez à l'inscrire. **Aucune reformulation n'est produite ici.** Le registre conserve donc sa formulation d'origine. |
| **Handoff D3.1** | 198 lignes, perdu, aucune empreinte. Non reconstitué, non simulé. |
| **Rapports jamais commités** | 14 documents perdus définitivement (contrôle sur les 169 commits que comptait l'historique lors de la recherche). |
| **Sondes et journaux D3.1** | 18 sondes, ≈ 45 journaux : perdus ; deux sondes neuves les remplacent **partiellement**. |
| **Sauvegarde et export** | vivaient dans le même environnement que ce qu'ils protègent ; la mention « sécurisée hors environnement » reste interdite jusqu'à confirmation par vous de la réception des fichiers. |
| **Borne 64** | non démontrée universellement (max observé : 21 itérations sur 120 configurations). |
| **Unicité du point fixe** | non prouvée : deux points fixes distincts resteraient indétectables. |
