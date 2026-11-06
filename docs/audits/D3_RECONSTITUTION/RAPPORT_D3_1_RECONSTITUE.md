# Rapport technique consolidé — D3.1 — **RECONSTITUÉ**

> **Nature du document.** Le rapport D3.1 original (359 lignes, rédigé le 2026-10-31) a été détruit
> avec `/home/user/d3_work` lors de la réinitialisation de l'environnement du 2026-11-02. Aucune
> empreinte SHA-256 n'en avait été conservée : son identité au document d'origine n'est **ni
> vérifiable, ni revendiquée**. Ce document reconstitue ses **conclusions**, à partir de l'historique
> de la session et des mesures refaites le 2026-11-02. Il ne remplace pas l'original : il le résume
> honnêtement, en distinguant systématiquement trois qualités de preuve.

**Convention de lecture, valable pour tout le document :**

| Marque | Signification |
|---|---|
| **[R]** | **Rapporté** : mesuré le 2026-10-31, journal aujourd'hui perdu. Repris tel quel, sans rejeu. |
| **[M]** | **Mesuré** : exécuté et vérifié le 2026-11-02 dans cet environnement, journal conservé. |
| **[NR]** | **Non rejoué** : résultat non reproductible faute de sonde ou de données d'origine. |

| Élément | Valeur |
|---|---|
| Base de référence | `8d296e20e395ae8aacd70d5692f518f4a28d6226` |
| Branche | `arena/fdc94521-simulateur-de-reseau-lorawan` |
| `main` préservée | `1f4337039c9ea10e2689600a67b63ca07bfe5318` |
| Empreintes gelées | `d2cb0fac6c2d9950…` (JSON) / `ed126d7ff5aac3b0…` (trace) |
| Périmètre | F1, F6, RF-YAML, MULTI-V4, GEO-RF, M1, M2, M3, M4 |

---

## 1. Résumé exécutif

Neuf anomalies ont été examinées pendant D3.1. Le bilan, inchangé après D3.2 :

| Statut | Anomalies |
|---|---|
| **REPRODUITE** | RF-YAML, MULTI-V4, GEO-RF |
| **PARTIELLEMENT REPRODUITE** | F1, F6, M2, M3 |
| **EN ATTENTE DE PREUVE** | M1, M4 |

Quatre résultats ont changé la lecture des preuves antérieures :

1. **Le balayage de convergence de la Phase A n'exerçait pas le code suspecté.** `join=False` et
   l'absence de bloc `mac:` activent `_build_trace_native` : la boucle à point fixe
   (`_build_trace_python`, `MAX_ITERATIONS = 12`) n'était **jamais** exécutée — 0 itération sur les
   240 runs. Toute mesure de F1 doit forcer `join=True` ou un bloc `mac:` **[M]**.
2. **Forcer la boucle la fait réellement tourner — et échouer.** Sur une variante à 2 000
   dispositifs, 69 des 120 configurations échouent, toutes `RuntimeError` à la limite des 12
   itérations ; la cause, établie en D3.2, est une **borne trop basse** et non une oscillation **[M]**.
3. **Les « écarts » chiffrés de F6 sont majoritairement de l'arithmétique de modèle** : `+2,000`,
   `+5,000`, `+7,000` dB sont les chaînes RF par côté ; `−24,633450` dB est le terme log-distance à
   1 200 m pour 3,5 → 2,7 **[M]**.
4. **L'interprétation « `d0` sans effet » est réfutée** : `d0` décale `PL` de
   `(20 − 10n)·log10(d0₂/d0₁)`, soit **−7,000000 dB** à `n = 2,7` **[M]**. Le désaccord apparent avec
   le script `scripts/preuves/sonde_d0.py` est expliqué au §6.3 — les deux mesures sont justes, elles
   ne parlent pas de la même chose.

---

## 2. Objet, méthode, limites

**Objet** : reproduire et diagnostiquer, **sans corriger**, les anomalies ouvertes du registre
`docs/audits/AUDIT_REGISTRE_ANOMALIES.md`.

**Méthode** : clone isolé, build Release, sondes dédiées, journaux conservés, aucune modification du
code de production. Le dépôt principal (`/home/user/simulateur-de-reseau-lorawan`, 88 entrées
préexistantes) n'a jamais servi d'environnement d'expérience.

**Limites de cette reconstitution** :

1. Les 50 journaux `logs/00`–`logs/25`, les 18 sondes `probes/` et les 10 archives de sauvegarde sont
   **perdus**. Ce document en reprend les conclusions, avec la marque **[R]**.
2. Aucune empreinte n'a été conservée pour ces fichiers : leur contenu exact n'est pas vérifiable.
3. Les chiffres marqués **[R]** n'ont pas été rejoués ; ceux marqués **[M]** le sont, avec journal.
4. Le rapport original comptait 15 sections ; la présente version en compte 15 + 2 annexes, mais sa
   structure n'est pas nécessairement identique à l'originale.

---

## 3. Environnement vérifié

| Contrôle | Valeur | Qualité |
|---|---|---|
| `git rev-parse HEAD` | `8d296e2…` | **[M]** |
| Fichiers suivis | 348 | **[M]** |
| Compilation Release | OK | **[M]** |
| `lsim_tests` | **685 249 / 685 249** | **[M]**, reconfirmé le 2026-11-02 |
| `pytest python/tests` | **1 846 réussis, 1 ignoré, 16 sous-tests** | **[R]** ; remesuré **[M]** à 1 847 / 0 ignoré (même total, dépendances installées) |
| Empreintes gelées | `d2cb0fac…` / `ed126d7f…` non rejouées (code inchangé) | **[R]** |

---

## 4. F1 — convergence et reproductibilité — **PARTIELLEMENT REPRODUITE**

### 4.1 Le piège de la Phase A

`_native_plan_applies(options, mac)` est vrai quand `join=False` **et** `mac=None`. Le chemin natif
produit la trace **sans itération** : la boucle à point fixe n'est pas exercée. Le balayage de la
Phase A (240 exécutions, « 0 échec ») ne prouvait donc rien sur F1 **[M]**.

### 4.2 Balayage en forçant la boucle

| Série | Périmètre | Résultat |
|---|---|---|
| B | 3 exemples × 40 graines × 2 jeux × 3 = **720 runs** | **0 `RuntimeError`**, 80 `ValidationError` (croisement `mac` + scénario mesh, refusé par construction), jusqu'à **11 itérations sur 12** **[R]** |
| C | variante `count: 2000`, 3 graines | échecs systématiques avec `downlink_every` **[R]** |
| D | `count: 2000`, 20 graines, 2 jeux | `join` 2/20 · `dl1` 15/20 **[R]** |
| E | `count: 2000`, **40 graines × 3 jeux = 120 runs** | `join` **3/40** (7, 19, 36) · `dl2` **33/40** · `dl1` **33/40** ⇒ **69/120** **[R]**, **rejoué [M]** à l'identique |

**[M] 2026-11-02** — rejeu complet des 120 configurations sur le code d'origine :

| Jeu | Échecs | Itérations |
|---|---:|---|
| `join` | 3 / 40 | 9–12 |
| `join + confirmed + dl2` | 33 / 40 | 11–12 |
| `join + confirmed + dl1` | 33 / 40 | 11–12 |

Les **69 échecs sont tous à la limite des 12 itérations** ; aucune autre exception **[M]**.

### 4.3 Nature de l'échec

L'analyse D3.1 par distances `d1 = |sᵢ Δ sᵢ₊₁|` et `d2 = |sᵢ Δ sᵢ₊₂|` concluait à un
« quasi-cycle de période 2 » sans descentes, et à une « évolution progressive » avec descentes **[R]**.

**Cette lecture a été réfutée en D3.2** par instrumentation de `_plan()` : les états **ne se répètent
jamais à l'identique**. La graine 0 montre, à l'itération 4, une cardinalité **constante**
(7 607 → 7 607 descentes) avec **+1 203 / −1 203** fenêtres décalées, et un recouvrement croissant
0 → 649 → 4 591 → 6 404 → 7 607 **[M]**. Il s'agit d'un **glissement progressif**, pas d'un cycle.

### 4.4 Conclusion F1

Le mécanisme est **réel et reproductible** : 69 configurations sur 120 n'atteignent pas le point fixe
en 12 itérations. La cause est la **borne**, pas une instabilité : à borne élevée, **120/120
convergent en 9 à 21 itérations** **[M]**. Les conditions d'origine de l'anomalie F1 (le rapport
historique) ne sont pas reconstituées : statut **PARTIELLEMENT REPRODUITE**.

---

## 5. F6 — écarts avec et sans terrain — **PARTIELLEMENT REPRODUITE**

### 5.1 Écarts expliqués

| Écart constaté | Explication | Valeur mesurée |
|---|---|---|
| **+2** | chaîne du frontal dispositif `DeviceRf(3 dBi, 1 dB)` | **+2,000000 dB** **[M]** |
| **+5** | chaîne du frontal passerelle `GatewayRf(6 dBi, 1 dB)` | **+5,000000 dB** **[M]** |
| **+7** | cumul des deux chaînes | **+7,000000 dB** **[M]** |
| **−24,633450** | terme `10·n·log10(d/d₀)` à **1 200 m** pour un exposant 3,5 → 2,7 | **−24,633450 dB** **[M]** |
| **0** (multi-passerelles) | `simulate_uplinks_multi` n'accepte aucun frontal | **0,000000 dB** **[M]** |

Trace neutre de référence : **−98,221395 dBm** **[R]**, cohérente avec les chaînes ci-dessus.

### 5.2 Écarts non reconstruits

| Écart | Statut | Détail |
|---|---|---|
| **12 dB** | **NON RECONSTRUIT** | le chemin mesh n'accepte **aucun** frontal ; une mesure « mesh + gain » n'est pas exprimable dans le code actuel **[M]** |
| **−91,892118 dBm** | **NON RECONSTRUIT** | recherche paramétrique de **1 077 570** combinaisons (`d`, `d0`, `n`, `P_tx`, chaîne) : **18** valeurs à ±5 × 10⁻⁴ dB, **aucune correspondance exacte** **[R]** ; valeurs voisines à `d0 = 1, n = 2,7` : 582 m ⇒ −91,874316 dBm, 600 m ⇒ −92,231479 dBm |

---

## 6. M2 — invariance observée sur `d0` — **PARTIELLEMENT REPRODUITE**

### 6.1 Le modèle

```
PL(d)  = PL(d0) + 10·n·log10(d / d0)          PL(d0) = espace libre
ΔPL    = (20 − 10n)·log10(d0₂ / d0₁)
```

| Mesure | Valeur | Qualité |
|---|---|---|
| `PL(3 000 m, d0 = 1, n = 2,7)` | **125,103669 dB** | **[M]** |
| `d0 : 1 → 10` à `n = 2,7` | **−7,000000 dB** (à 1 000 m **et** à 3 000 m) | **[M]** |
| `d0 : 1 → 10` à `n = 2,0` | **0,000000 dB** | **[M]** |
| Bascule de réception SF9 | 15 km / 25 km | **[R]** |
| Bascule de réception SF12 | 40 km | **[R]** |
| Distance minimale dans les exemples | 60,444 m (quartier), 70,518 m (mesh) | **[R]** |

L'observation d'origine — « faire varier `d0` ne change rien sur l'exemple » — est donc une
**coïncidence numérique** : à `n = 2`, `20 − 10n = 0` et le modèle est exactement invariant. À
`n = 2,7`, il ne l'est plus.

### 6.2 Conclusion M2

L'invariance observée est reproduite ; l'interprétation « `d0` sans effet » est **réfutée**.

### 6.3 Pourquoi le script du dépôt dit pourtant « d0 n'agit qu'avec un relief »

`scripts/preuves/sonde_d0.py` compare des **résultats de bout en bout** (compteurs, PDR, lignes par
terminal), pas des pertes. Rejeu du 2026-11-02 **[M]** :

| Exemple | Marge minimale avant la sensibilité | Trames à moins de 7 dB du seuil | Conséquence d'un décalage de 7 dB |
|---|---:|---:|---|
| `quartier_sf9.yaml` (sans relief) | **+20,047 dB** | **0** | aucune issue ne peut basculer ⇒ sorties identiques |
| `quartier_relief_sf9.yaml` (avec relief) | **−35,712 dB** | **490** (sur 5 000 trames) | 490 trames peuvent basculer ⇒ sorties différentes |

**Les deux affirmations sont vraies, à des niveaux différents** : `d0` décale toujours `PL` de
`(20 − 10n)·log10(d0₂/d0₁)` ; il ne change les **issues** que si des trames se trouvent à moins de ce
décalage du seuil. Sur l'exemple sans relief, la marge minimale est de 20 dB : rien ne peut basculer.
La phrase du script (« n'agit qu'en présence d'un relief ») est donc **exacte pour ces deux exemples,
mais trop générale comme énoncé du modèle** — c'est une imprécision de documentation, pas un défaut
de calcul. Elle est corrigée dans `docs/RF_MODEL.md` §2 (publié, commit `dff67ba`).

---

## 7. RF-YAML — **REPRODUITE**

| Contrôle | Résultat | Qualité |
|---|---|---|
| Clé `rf:` à la racine du scénario | **refusée** (`ValidationError`, modèle strict) | **[M]**, test `test_scenario_refuses_an_rf_key_at_root` |
| Clé `rf:` dans un groupe | **refusée** | **[M]**, test `test_scenario_refuses_an_rf_key_inside_a_group` |
| Clés RF de scénario | **aucune** — les seuls champs radio d'un groupe sont `spreading_factor`, `tx_power_dbm`, `payload_bytes`, `channel_freq_hz`, `sub_band`, `region`, `duty_cycle` | **[M]** |
| Frontaux déclarables | **API Python seulement** (`DeviceRf`, `GatewayRf`) | **[M]** |

Documentation publiée : `docs/RF_MODEL.md` §8.

---

## 8. MULTI-V4 — **REPRODUITE**

| Contrôle | Résultat | Qualité |
|---|---|---|
| `simulate_uplinks_multi` | **aucun** paramètre `device_rf` / `gateway_rf` | **[M]**, test `test_uplink_paths_without_frontend_stay_without_one` |
| `simulate_multi_downlinks` | **accepte** les deux frontaux | **[M]** |
| Symboles natifs | `multi`, `multi_dl`, `multi_dl_v2`, `trace_v2/v3/gw2/gw2_v2`, 6 symboles mesh — **aucun `multi_v4`** | **[R]**, structure inchangée depuis |
| `lsim_simulate_closed_loop_v4` | présent (95 symboles exportés) | **[R]** |

Il n'existe donc **aucune entrée `multi_v4`** : la capacité est absente, pas désactivée.

---

## 9. M3 — tables partielles et chemin mesh — **PARTIELLEMENT REPRODUITE**

| Volet | Résultat | Statut |
|---|---|---|
| Table RF **partielle** sur le chemin v4 | **refusée avant l'appel natif**, statut **301** côté cœur ; aucun repli implicite **[R]** | reproduit |
| Volet **mesh** | **NON CONCLUSIF** : le mesh n'accepte aucun frontal, donc « acceptation silencieuse d'un `mesh_rf` partiel » n'est pas exprimable dans le code actuel | non conclusif |

---

## 10. GEO-RF — **REPRODUITE**

| Contrôle | Résultat | Qualité |
|---|---|---|
| Propriétés du document GeoJSON | **7 clés** : `environment`, `origin`, `pdr`, `scenario_name`, `scenario_sha256`, `total_received`, `total_sent` | **[M]** |
| Champs de gain / EIRP / câble / `frontend` | **aucun** | **[M]**, test `test_geojson_carries_no_radio_frontend_field` |
| Entités | une par passerelle (`coverage`), par groupe (anneau), par terminal | **[M]** |
| `python/lsim/geo.py` | **inchangé** par les frontaux v4 | **[M]** |

La géographie et la propagation sont séparées : l'export transporte une **distance** (`range_m`), pas
un bilan radio.

---

## 11. M1 et M4 — **EN ATTENTE DE PREUVE**

| ID | Situation |
|---|---|
| **M1** | document source perdu, aucune définition dans le dépôt, aucune reconstruction possible |
| **M4** | dépend de M1–M3 ; contenu d'origine perdu |

Ces deux anomalies ne peuvent pas être instruites : ni leur énoncé, ni leur périmètre ne sont
disponibles. Elles restent ouvertes, sans conclusion.

---

## 12. Corrections candidates (aucune n'a été appliquée pendant D3.1)

| # | Candidat | Effet attendu | État |
|---|---|---|---|
| 1 | **F1-a** : porter `MAX_ITERATIONS` à 64 et détecter les cycles exacts | 69/120 configurations corrigées, 51/51 inchangées | **appliqué en D3.2**, commit `d85b50c` |
| 2 | **F1-b** : accélérer le point fixe (amortissement d'état) | réduire le nombre d'itérations | **rejeté sur mesure** : `inter` et `union` ne convergent pas en 128 itérations (§ annexe A) |
| 3 | **F6/M2** : documenter les équations et le rôle de `d0` | supprimer l'interprétation erronée | **appliqué en D3.2**, `docs/RF_MODEL.md` |
| 4 | **RF-YAML** : documenter l'absence de `rf:` en YAML | lever la confusion | **appliqué en D3.2** |
| 5 | **MULTI-V4** : publier le tableau des capacités par chemin | clarifier l'absence de `multi_v4` | **appliqué en D3.2** |
| 6 | **M3** : documenter le statut 301 et le mesh sans RF | cadrer le périmètre | **appliqué en D3.2** |
| 7 | **GEO-RF** : documenter la séparation géo/radio | cadrer l'export | **appliqué en D3.2** |
| 8 | **M1/M4** | — | **bloqué** faute d'énoncé |

---

## 13. Contradictions documentaires constatées

| Document | Contradiction |
|---|---|
| `docs/audits/AUDIT_SEQUENCEMENT.md` | rédigé au futur : décrit un état à venir, pas l'état constaté |
| `docs/audits/AUDIT_BILAN_SAUVEGARDES.md` | les vérifications d'archives dépendent d'un stockage externe au dépôt |
| `scripts/preuves/README.md` | attendus calés sur le commit `68176d6`, antérieur à la Phase A (`8d296e2`) |
| `docs/PRIORITIES.md` | périmé au regard du registre d'anomalies |
| `CHANGELOG.md` | annonce « 1839 » tests Python là où la mesure donne 1 846 |
| `main` | ne contient pas la Phase A : `1f43370` est l'ancêtre de `68176d6` → `8d296e2` sur la branche seulement |

---

## 14. Priorisation proposée

| Rang | Sujet | Justification |
|---|---|---|
| **1** | F1-a / F1-b | anomalie la plus impactante : perte totale du résultat sur 57 % des configurations denses |
| **2** | Documentation `d0` / F6 | coût quasi nul, supprime une interprétation fausse |
| **3** | RF-YAML | confusion à l'usage, pas de défaut de calcul |
| **4** | MULTI-V4 + M3 | absence de capacité, pas défaut ; à documenter puis arbitrer |
| **5** | GEO-RF | clarification |
| **6** | M1 / M4 | bloqués faute de source |

**Registre** : P0 aucun · **P1** F1, F6, RF-YAML, E2 · **P2** LP64-14, MULTI-V4, GEO-RF, M1–M3,
E1 · **P3** I386, M4, D1, D2.

---

## 15. Conclusion

D3.1 n'a corrigé aucune anomalie et n'a modifié aucun code de production. Elle a produit trois
acquis durables :

1. **Un piège de mesure démasqué** : la boucle de convergence n'était pas exercée par les balayages
   antérieurs. Toutes les mesures F1 postérieures en tiennent compte.
2. **Une cause établie pour F1** : 69 configurations sur 120 échouaient à la borne de 12 itérations ;
   elles convergent toutes en 13 à 21. L'anomalie n'est pas une instabilité.
3. **Une requalification de F6 et M2** : les écarts chiffrés sont de l'arithmétique de modèle, et
   `d0` n'est neutre que pour `n = 2`.

Deux anomalies restent sans instruction possible (M1, M4), deux écarts F6 restent non reconstruits
(`12 dB`, `−91,892118 dBm`). Aucune anomalie n'a été déclarée corrigée pendant D3.1.

---

## Annexe A — F1-b rejouée le 2026-11-02 **[M]**

Boucle à point fixe réimplémentée à l'identique (mêmes appels, même critère d'arrêt), borne 128 :

| Configuration | `none` | `inter` | `union` |
|---|---|---|---|
| `join`, graine 7 | 13 itérations | **échec à 128** | **échec à 128** |
| `join`, graine 19 | 13 | **échec à 128** | **échec à 128** |
| `join`, graine 36 | 15 | **échec à 128** | **échec à 128** |
| `dl1`, graine 0 | 16 | **échec à 128** | **échec à 128** |
| `dl1`, graine 7 | 14 | **échec à 128** | **échec à 128** |
| `dl1`, graine 36 | 21 | **échec à 128** | **échec à 128** |

Les deux amortissements sont **contre-productifs** : ils modifient la suite d'états sans garantir
l'atteinte d'un point fixe. Le résultat rapporté en D3.2 est donc **confirmé par mesure**.
Journal : `logs/11_f1b_amortissement.log` · sonde : `probes/p_f1b_amortissement.py`.

## Annexe B — inventaire des preuves

| Élément | Statut |
|---|---|
| 120 configurations F1, code d'origine et code corrigé | **conservées** : `d3_recon_preuves/logs/02`, `03`, JSON + `04_f1_120_synthese.txt` |
| Échec des tests sur le code d'origine | **conservé** : `d3_recon_preuves/logs/01_echec_sur_origine.log` |
| `sonde_d0.py` rejouée | **conservé** : `d3_restauration/logs/10_sonde_d0_rejeu.log` |
| F1-b, trois variantes | **conservé** : `d3_restauration/logs/11_f1b_amortissement.log` + JSON |
| Marge avant sensibilité (M2) | **conservé** : `d3_restauration/logs/12_d0_marge.log` |
| Journaux `logs/00`–`logs/25` de D3.1 | **perdus** |
| Sondes `probes/p_*.py` de D3.1 (18) | **perdues** |
| 10 archives de sauvegarde | **perdues** |
