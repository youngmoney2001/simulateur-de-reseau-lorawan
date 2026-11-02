# D3 — Reconstitution des preuves de l'audit D3.1

> **Ce dossier ne contient aucun document original.** Le rapport D3.1 a été détruit le 2026-11-02
> avec l'environnement de travail `/home/user/d3_work` ; aucune empreinte SHA-256 n'en avait été
> conservée. Les documents ici présents sont des **reconstitutions**, étiquetées comme telles, et
> n'ont aucune prétention d'identité avec les fichiers perdus.

## 1. Contenu

| Fichier | Nature |
|---|---|
| `RAPPORT_D3_1_RECONSTITUE.md` | Reconstitution des conclusions de D3.1 (15 sections + 2 annexes) |
| `logs/10_sonde_d0_rejeu.log` | Rejeu de `scripts/preuves/sonde_d0.py` — F6 / M2 |
| `logs/11_f1b_amortissement.log` | Rejeu du rejet des amortissements — F1-b |
| `logs/f1b_amortissement.json` | Sortie structurée de la même sonde (6 configurations × 3 variantes) |
| `logs/12_d0_marge.log` | Modèle `d0` et marges réelles de l'exemple — M2 |
| `EMPREINTES.sha256` | Empreintes des 6 fichiers de ce dossier + 2 sondes, relatives à la racine du dépôt |

Les sondes associées sont versionnées avec les autres preuves :

| Fichier | Objet |
|---|---|
| `scripts/preuves/p_f1b_amortissement.py` | Boucle à point fixe réimplémentée à l'identique, variantes `none` / `inter` / `union` |
| `scripts/preuves/p_d0_marge.py` | Écart de `PL` selon `d0`, et marge des trames avant la sensibilité |

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
