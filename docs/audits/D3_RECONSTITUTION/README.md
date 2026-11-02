# D3 — Reconstitution des preuves de l'audit D3.1

> **Ce dossier ne contient aucun document provenant du D3.1 original.** Le rapport D3.1 a été
> détruit le 2026-11-02 avec l'environnement de travail `/home/user/d3_work` ; aucune empreinte
> SHA-256 n'en avait été conservée. Les documents de reconstitution sont **étiquetés comme tels** et
> n'ont aucune prétention d'identité avec les fichiers perdus.
>
> **Seule exception, explicitement identifiée :** `D3_HANDOFF_v1.md` n'est pas une reconstitution.
> C'est la **copie à l'octet près** du handoff D3.2 réellement produit le 2026-11-02, d'empreinte
> `186d346fb46e7737f7b6905130b5205b4ddb7f5cad75da06f20d3039f5ef1648`, conservée ici comme
> référence historique après la mise à jour en version 2.

## 1. Contenu

| Fichier | Nature |
|---|---|
| `RAPPORT_D3_1_RECONSTITUE.md` | Reconstitution des conclusions de D3.1 (15 sections + 2 annexes) |
| `SUIVI_ANOMALIES_POST_D3.md` | Suivi des 15 anomalies : statut Phase A, résultats D3, preuves, incertitudes, statut proposé |
| `D3_HANDOFF.md` | Fichier de reprise, **version 2** (2026-11-02, base `fd5cdb5`) |
| `D3_HANDOFF_v1.md` | Version 1 **originale** (D3.2, 139 l.), conservée à l'octet près — `186d346f…` |
| `logs/10_sonde_d0_rejeu.log` | Rejeu de `scripts/preuves/sonde_d0.py` — F6 / M2 |
| `logs/11_f1b_amortissement.log` | Rejeu du rejet des amortissements — F1-b |
| `logs/f1b_amortissement.json` | Sortie structurée de la même sonde (6 configurations × 3 variantes) |
| `logs/12_d0_marge.log` | Modèle `d0` et marges réelles de l'exemple — M2 |
| `EMPREINTES.sha256` | Empreintes des 9 fichiers de ce dossier + 2 sondes, relatives à la racine du dépôt |

Les sondes associées sont versionnées avec les autres preuves :

| Fichier | Objet |
|---|---|
| `scripts/preuves/p_f1b_amortissement.py` | Boucle à point fixe réimplémentée à l'identique, variantes `none` / `inter` / `union` |
| `scripts/preuves/p_d0_marge.py` | Écart de `PL` selon `d0`, et marge des trames avant la sensibilité |

### 1.1 Les deux versions du handoff

| Fichier | Version | Base décrite | Empreinte | Statut |
|---|---|---|---|---|
| `D3_HANDOFF_v1.md` | D3.2 | `dff67ba` | `186d346f…` | **original**, conservé tel quel |
| `D3_HANDOFF.md` | v2 | `fd5cdb5` | voir `EMPREINTES.sha256` | mise à jour du 2026-11-02 |

La version 1 est **périmée** sur deux points qu'elle ne pouvait pas connaître : elle indique « push
non autorisé » alors que `dff67ba` a été poussé, et elle ignore `fd5cdb5`. La version 2 corrige ces
deux points et conserve la distinction entre faits vérifiés, résultats rapportés et éléments non
vérifiables. Aucune des deux ne représente le handoff D3.1 (198 l.), perdu et **non reconstitué**.

## 2. Distinction des qualités de preuve

Le rapport emploie trois marques, à lire avant toute citation :

| Marque | Signification |
|---|---|
| **[R]** | **Rapporté** — mesuré le 2026-10-31, journal perdu, non rejoué |
| **[M]** | **Mesuré** — exécuté le 2026-11-02, journal conservé dans `logs/` |
| **[NR]** | **Non rejoué** — non reproductible faute de sonde ou de données |

Aucune valeur **[R]** ne doit être citée comme si elle avait été revérifiée.

## 3. Ce qui manque, et pourquoi

| Élément perdu | État |
|---|---|
| `logs/00`–`logs/25` de D3.1 | perdus, non reconstituables |
| 18 sondes `probes/p_*.py` de D3.1 | perdues ; deux sondes neuves les remplacent partiellement (§1) |
| 10 archives de sauvegarde | perdues ; seules des archives reconstruites existent, avec d'autres empreintes |
| `D3_HANDOFF.md` | perdu |
| Rapport D3.1 original (359 lignes) | perdu ; ce dossier en propose une reconstitution, pas une copie |

## 4. Reproduction

Depuis la racine d'un clone compilé (`cmake` + `build/liblsim_core.so`) :

```bash
export LSIM_LIBRARY="$PWD/build/liblsim_core.so"
export PYTHONPATH="$PWD/python"

# F1-b : trois variantes d'amortissement, borne 128
python scripts/preuves/p_f1b_amortissement.py "$PWD" /tmp/f1b.json 128

# M2 : écart de PL selon d0, puis marge réelle des 5 000 trames de chaque exemple
python scripts/preuves/p_d0_marge.py "$PWD"

# intégrité des preuves de ce dossier
sha256sum -c docs/audits/D3_RECONSTITUTION/EMPREINTES.sha256
```

Durée observée : environ 150 s pour F1-b (6 configurations, dont 12 échecs à 128 itérations),
moins de 1 s pour `p_d0_marge.py`.

## 5. Résultats mesurés, en une ligne chacun

- **F1-b** : `none` converge en 13, 13, 15, 16, 14, 21 itérations ; `inter` et `union` **échouent aux
  6 configurations** à 128 itérations. Le rejet des amortissements n'est plus rapporté, il est mesuré.
- **F6/M2** : `d0 : 1 → 10` décale `PL` de **−7,000000 dB** à `n = 2,7` et de **0,000000 dB** à
  `n = 2`. L'exemple sans relief a une marge minimale de **+20,047 dB** (0 trame à moins de 7 dB du
  seuil) ; l'exemple avec relief descend à **−35,712 dB** et compte **490** trames dans cette zone.
  Les deux affirmations — « `d0` décale `PL` » et « `d0` ne change pas l'issue » — sont vraies, mais
  à deux niveaux différents.
