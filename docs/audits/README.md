# Audits — index et provenance

Ce répertoire conserve les rapports d'audit **tels qu'ils ont été livrés et validés**, avec leur
empreinte SHA-256. Il ne contient **aucun code** et **aucune preuve fabriquée** : les documents y
sont copiés à l'octet près depuis les livrables de session.

## 1. Documents

| Fichier | Objet | Lignes | SHA-256 |
|---|---|---|---|
| `AUDIT_GLOBAL_RAPPORT.md` | Audit global R1 → F2 + G1 : état, contrôles rejoués, cohérence, limites | 256 | `119e4cbcfb7421d51dbafcbf4b13d12e262f57b11f4d83219477b21bcf905187` |
| `AUDIT_COMPLEMENT.md` | Complément : 14 assertions LP64, divergences Git, recherche documentaire, dépendances A–H, 48 critères | 373 | `36f0522ec878a653641adfd1c8a04ea88c956f01bdde349b0b0e5cf24f62dd0b` |
| `AUDIT_REGISTRE_ANOMALIES.md` | Registre F1, F6, LP64-14, I386, RF-YAML, MULTI-V4, GEO-RF, M1–M4, D1, D2, E1, E2 | 243 | `e61be13340039f92878d21dd1ea8522939c6eeddf5e3f6cc5b0d4d5a4bb62681` |
| `AUDIT_MATRICE_FONCTIONNALITES.md` | Matrice « implémenté / partiel / absent » sur 20 domaines | 53 | `71f0d61070994d006c6358a7182507909e53dfe14707fbb67a90a615462f8823` |
| `AUDIT_BILAN_SAUVEGARDES.md` | Inventaire de 10 archives (9 historiques + archive de pré-Phase A), contrôles `sha256sum`, restaurabilité | 124 | `7284f1bcc7ac5aa294e6bd688a6d4e7d42cf44cfcb50f74874c2b1893797ef6e` |
| `AUDIT_SEQUENCEMENT.md` | Séquencement A → H, dépendances, risques | 197 | `0979509d1776dc90a56691ea35a8214ada06da5cab7b41975679705ea0b60ebd` |
| `AUDIT_RECHERCHE_TRACES.md` | Journal de recherche de `R2B_CLOTURE_AUDIT_ANOMALIES.md` (15 méthodes, introuvable) | 116 | `16122272698a5220d9a36436b0887e29b70a0d42f512ea9aa23a8fc540d1a2c8` |

## 2. Provenance

Les documents ont été rédigés dans `/home/user/` pendant les phases d'audit, puis copiés ici
**sans modification**. Les chemins `/home/user/AUDIT_*.md` cités dans leur texte désignent les
originaux de session ; dans le dépôt, ils correspondent aux fichiers du tableau ci-dessus.

Aucun rapport n'a été supprimé, réécrit ou « amélioré » lors du transfert. Les seules
modifications admises dans ces documents sont les **rectifications d'erreurs factuelles**,
signalées dans le document lui-même (`AUDIT_GLOBAL_RAPPORT.md` §0 et `AUDIT_REGISTRE_ANOMALIES.md`,
entrée LP64-14) ; elles sont antérieures au transfert et incluses dans les empreintes ci-dessus.

Des rectifications **postérieures au transfert** sont signalées dans les documents eux-mêmes :

- `AUDIT_COMPLEMENT.md` (en-tête et §3.3) — requalification de M2 et M3 ;
- `AUDIT_RECHERCHE_TRACES.md` (§6.3) — même requalification, pour retirer F6 comme base de
  corroboration ;
- `AUDIT_REGISTRE_ANOMALIES.md` (§1 et §2 F1, §3 R2b) — décompte exact des exécutions de F1 ;
  statut des mutations R2b : rapportées, non rejouées ;
- `AUDIT_MATRICE_FONCTIONNALITES.md` (§1) — distinction entre tests réussis, ignorés et collectés ;
- `AUDIT_BILAN_SAUVEGARDES.md` (§1 et §4) — note de périmètre sur la dixième archive ; les
  mutations R2b ne sont plus classées « non reproductibles » mais **rapportées, non rejouées**.

Ce sont les seules modifications apportées à des livrables d'audit à l'intérieur du dépôt ; elles
expliquent l'écart d'empreinte avec les livrables de session (`b4fcdd5a…` pour le complément,
`081fd38d…` pour le registre, `58ae843f…` pour la matrice, `2fb520bc…` pour le journal de
recherche, `57d7079c…` pour le bilan → empreintes du tableau ci-dessus).

## 3. Statut des affirmations

Les documents distinguent quatre statuts, et aucun ne doit être aplati :

- **preuve directe** : mesure rejouée pendant l'audit (ex. 11 des 14 assertions échouent en i386,
  mesuré par compilation) ;
- **résultat rapporté, non rejoué** : essai réellement exécuté lors d'une phase antérieure et
  consigné, mais non revalidé ici faute de script conservé ;
- **corroboration indirecte** : observation établie dans un périmètre donné, mais insuffisante pour
  démontrer l'hypothèse complète de l'anomalie. Pour **M2**, le comportement de `d0` sans relief est
  observé, sans établir à lui seul l'anomalie globale ; pour **M3**, le rejet d'une configuration RF
  partielle est observé **dans v4**, mais ne démontre pas à lui seul le comportement correspondant
  **dans le contexte mesh** ;
- **non reproductible** : preuve perdue, sans essai antérieur exploitable (F1, F6 en dB, M1, M4).

**Mutations R2b — statut par mutation.** Quatre essais ont été exécutés lors de la phase R2b et ont
tous été détectés ; leurs scripts ne sont plus conservés, ils ne sont donc **pas rejoués** ici.

| Mutation identifiée | Résultat rapporté lors de R2b | Statut dans cet audit |
|---|---|---|
| routage v4 désactivé | **6** échecs détectés | rapporté, non rejoué |
| frontal ignoré | **5** échecs détectés | rapporté, non rejoué |
| double comptage en descente | **1** échec détecté | rapporté, non rejoué |
| suppression des deux gardes de table | **2** échecs détectés | rapporté, non rejoué |

Ces quatre résultats sont **rapportés** : aucune trace des scripts de mutation ne subsiste dans le
dépôt ni dans les neuf archives de `sauvegardes/`. Les mutations ne sont donc **ni** des preuves
perdues au sens de F1, M1 ou M4, **ni** des résultats validés par le présent audit : elles ont été
détectées à l'époque, elles ne sont plus rejouables aujourd'hui.

`M1` et `M4` restent **non identifiables** : le document source est déclaré introuvable et
**aucune reconstruction n'a été produite**.

## 4. Vérification de l'origine des chiffres du CHANGELOG (Phase A)

La correction porte sur **une ligne** du `CHANGELOG.md` (entrée « Frontal RF v4 »). Les valeurs
d'origine (`1832`, `685235`) ne correspondent à **aucun commit** ; les valeurs retenues ont été
mesurées sur les commits réels :

| Commit | Étape | C++ (`lsim_tests`) | Tests Python collectés | Tests Python réussis | Tests Python ignorés |
|---|---|---|---|---|---|
| `9686c25` | avant R1 | 685165 | 1779 | 1778 | 1 |
| `c46d531` | R1 | 685165 | 1803 | **1802** | 1 |
| `2202782` | R2b | **685249** | 1840 | **1839** | 1 |
| `c77f8eb` | F7 | 685249 | 1840 | 1839 | 1 |
| `68176d6` | F2 + G1 | 685249 | 1847 | 1846 | 1 |

Deux mesures distinctes, exécutées sur chaque commit :

- **collecte** — `python -m pytest python/tests -q --collect-only` : nombre de tests découverts ;
- **exécution** — `python -m pytest python/tests -q` : nombre de tests **réussis**, plus les tests
  **ignorés** (toujours **1** : `python/tests/test_fetch_dem.py`, `rasterio` absent de
  l'environnement).

Le CHANGELOG annonce des tests **réussis** : c'est cette colonne, et non celle des tests collectés,
qui justifie la correction `1802 → 1839`. Les deux valeurs C++ (`685165 → 685249`) proviennent du
binaire `lsim_tests` exécuté par commit.

## 5. Éléments reproductibles

Les contrôles décrits dans ces rapports sont rejouables via `scripts/preuves/`
(voir `scripts/preuves/README.md`) : symboles exportés, empreintes gelées, harnais ABI, tableau des
14 assertions, sonde `d0`, balayage de graines, vérification d'une sauvegarde.

## 6. D3 — reconstitution des preuves

Le sous-répertoire `D3_RECONSTITUTION/` est **hors de l'index du §1** et n'est pas un livrable
d'audit validé : il contient une **reconstitution** du rapport D3.1 — dont l'original a été détruit
le 2026-11-02 sans qu'aucune empreinte n'en soit conservée — accompagnée des **journaux de rejeu**
du 2026-11-02. Il est conservé ici parce qu'il documente l'état des anomalies F1, F6, M2 et M3 après
les mesures de D3.1 et D3.2, et parce qu'il porte ses propres empreintes.

| Élément | Nature |
|---|---|
| `D3_RECONSTITUTION/RAPPORT_D3_1_RECONSTITUE.md` | Reconstitution (15 sections + 2 annexes) — **pas** le rapport original |
| `D3_RECONSTITUTION/logs/` | 4 journaux de rejeu, sortie brute des sondes |
| `D3_RECONSTITUTION/README.md` | Provenance, limites, mode de reproduction, convention [R]/[M]/[NR] |
| `D3_RECONSTITUTION/EMPREINTES.sha256` | 8 empreintes, vérifiables par `sha256sum -c` depuis la racine |

Les deux sondes de rejeu sont versionnées avec les autres preuves : `scripts/preuves/p_f1b_amortissement.py`
et `scripts/preuves/p_d0_marge.py`. Elles ne modifient aucun code de production.

Les statuts du §1 (tableau de synthèse de `AUDIT_REGISTRE_ANOMALIES.md`) sont ceux établis **au
moment de la Phase A** ; ils ne tiennent pas compte des mesures de D3.1 et D3.2. Ils n'ont pas été
réécrits ici : l'écart est explicité dans le rapport reconstitué, il n'est pas corrigé dans le
registre.
