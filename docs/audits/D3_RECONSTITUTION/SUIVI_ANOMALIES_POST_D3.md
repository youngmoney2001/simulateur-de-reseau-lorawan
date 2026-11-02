# Suivi des anomalies après D3 — **PROPOSITION**

> **Statut du document : proposition, non commitée, non publiée.**
> Il ne remplace pas `docs/audits/AUDIT_REGISTRE_ANOMALIES.md`, qui reste **inchangé** : le registre
> de la Phase A est conservé comme archive de phase, avec ses statuts d'alors. Ce document est un
> **suivi annexe** : il met côte à côte ce que le registre affirme, ce que D3.1 et D3.2 ont mesuré,
> et ce qu'il est proposé de retenir — sous réserve d'arbitrage.

| Élément | Valeur |
|---|---|
| Rédigé le | 2026-11-02 |
| Base de référence | `fd5cdb5739ad4347b71221a4f8a867f9db7be451` (branche `arena/fdc94521-…`, **non poussé**) |
| Parent | `dff67ba6f751d1966a89e6ebf07fc1cd13d32c61` |
| Registre historique | `docs/audits/AUDIT_REGISTRE_ANOMALIES.md`, 243 lignes, SHA-256 `e61be13340039f92878d21dd1ea8522939c6eeddf5e3f6cc5b0d4d5a4bb62681` |
| Portée | **15 anomalies** du registre ; 4 entrées déjà closes (`F2`, `G1`, `F7`, `R2b`) ne sont pas reprises |
| Effet sur le dépôt | **aucun** — aucun fichier du dépôt n'a été modifié pour produire ce document |

## 0. Convention

| Marque | Sens |
|---|---|
| **[M]** | mesuré, journal conservé dans cet environnement |
| **[R]** | rapporté lors d'une phase antérieure, journal perdu, **non rejoué** |
| **[P]** | **proposé** par ce document — n'a aucune valeur tant qu'il n'est pas arbitré |

Une ligne de statut **[P]** n'énonce pas une décision : elle formule une option d'arbitrage.

---

## 1. Synthèse

| ID | Statut Phase A (registre) | Après D3.1 / D3.2 | Statut actuel **proposé** |
|---|---|---|---|
| **F1** | non reproduit (0 échec : 112 puis 240) | non-convergence **reproduite** (69/120) puis **corrigée** (`d85b50c`) | **CORRIGÉE** pour la non-convergence ; **NON REPRODUITE** pour la divergence causal/trace |
| **F6** | partiel : `d0` reproduit, écarts dB non reproduits | 5 écarts sur 7 expliqués par arithmétique de modèle ; 2 non reconstruits | **PARTIELLEMENT RÉSOLUE** |
| **M2** | reproduit (`d0 1↔10` : sorties identiques) | invariance exacte **seulement si `n = 2`** ; −7,000000 dB à `n = 2,7` | **REQUALIFIÉE — résolue par explication** |
| **M3** | plausible, non prouvé | v4 : refus reproduit (301) ; mesh : non conclusif | **PARTIELLEMENT ÉTABLIE** |
| **RF-YAML** | reproduit (aucune clé `rf`) | 2 tests ajoutés, documentation publiée | **CLOSE par documentation et test** |
| **MULTI-V4** | reproduit (signature sans RF) | tableau des 9 chemins publié, test ajouté | **CLOSE par documentation** |
| **GEO-RF** | reproduit (7 clés, 211 l.) | 7 clés confirmées, 1 test ajouté | **CLOSE par documentation et test** |
| **LP64-14** | reproduit (14 lignes 86–101) | non instruite en D3 | **OUVERTE** — correction identifiée, non appliquée |
| **I386** | reproduit (lien `-m32` impossible) | non instruite en D3 | **OUVERTE** — dépend de l'environnement |
| **M1** | non reproductible | aucun élément nouveau | **OUVERTE — en attente des éléments sources nécessaires à leur instruction** |
| **M4** | non reproductible | aucun élément nouveau | **OUVERTE — en attente des éléments sources nécessaires à leur instruction** |
| **D1** | reproduit (1832/685235 vs 1839/685249) | corrigé en Phase A ; les valeurs d'origine restent introuvables | **CLOSE pour la correction**, réserve documentée |
| **D2** | reproduit (`diff -r` sur `.git/refs/remotes`) | archive concernée perdue | **OUVERTE, non instruisable** |
| **E1** | reproduit | dépôt principal toujours à 88 entrées | **OUVERTE** — préexistante, hors périmètre D3 |
| **E2** | reproduit (absentes des 9 archives) | partiellement remédiée (`d3_recon_preuves`, `fd5cdb5`) | **PARTIELLEMENT REMÉDIÉE** |

---

## 2. Fiches

### F1 — Divergence du chemin causal / point fixe

| Champ | Contenu |
|---|---|
| **Statut Phase A** | **non reproduit** — « 0 échec : 112 exécutions de la sonde reconstruite, puis 240 du balayage Phase A, qui la contient ». Priorité P1. |
| **Résultats D3.1 / D3.2** | Le balayage de la Phase A n'exerçait pas la boucle à point fixe : `_native_plan_applies()` renvoie vrai quand `join=False` et `mac=None` [M]. En forçant `join=True`, 120 configurations (40 graines × 3 jeux, `quartier_sf9.yaml` à 2 000 dispositifs) donnent **69 échecs**, tous `RuntimeError` à la limite de **12** itérations (join 3/40 · dl2 33/40 · dl1 33/40) [M]. Le code corrigé donne **120/120** en **9 à 21** itérations, et les **51** configurations déjà convergentes sont **identiques** (itérations et empreinte) [M]. Instrumentation de `_plan()` : les états **ne se répètent jamais à l'identique** — glissement progressif, pas oscillation [M]. |
| **F1-b (sous-item)** | Phase A/registre : non traité. **D3.2** : rejet des amortissements, **rapporté** [R]. **Rejeu du 2026-11-02** : `none` converge en 13, 13, 15, 16, 14, 21 ; `inter` et `union` **échouent aux 6 configurations** à 128 itérations [M]. |
| **Preuves disponibles** | `d3_recon_preuves/logs/01_echec_sur_origine.log`, `02_f1_120_reference.log`, `03_f1_120_reconstruit.log`, `04_f1_120_synthese.txt`, `f1_120_reference.json`, `f1_120_reconstruit.json`, `probes/p_f1_120.py` ; commit `d85b50c` ; `docs/audits/D3_RECONSTITUTION/logs/11_f1b_amortissement.log` + JSON ; `scripts/preuves/p_f1b_amortissement.py`. |
| **Incertitudes restantes** | (a) la sonde d'origine `f1_balayage_40_graines.py` reste **perdue** ; (b) la divergence **causal vs trace** (38/40 identiques, graines 11 et 38 en échec) n'a **jamais** été reproduite dans sa paramétrisation d'origine ; (c) la borne 64 n'est **pas démontrée universellement** (max observé : 21 sur 120 configurations) ; (d) l'**unicité du point fixe n'est pas prouvée**. |
| **Statut proposé [P]** | **CORRIGÉE** pour la non-convergence à 12 itérations ; **NON REPRODUITE** pour la divergence causal/trace. Les deux moitiés doivent rester distinctes. |
| **Réserve de libellé** | Le **libellé exact** du texte de remplacement exigé pour la formulation « 0 échec : 112 … puis 240 … » **n'a pas été retrouvé** (voir §3.2). Aucune reformulation n'est proposée ici. |

### F6 — Cohérence de `d0` et du chemin RF

| Champ | Contenu |
|---|---|
| **Statut Phase A** | **partiel** : `d0` reproduit ; écarts en dB non reproduits. P1. |
| **Résultats D3.1 / D3.2** | Cinq des sept écarts sont de l'**arithmétique de modèle** : `+2,000000` = `DeviceRf(3 dBi, 1 dB)` [M] ; `+5,000000` = `GatewayRf(6 dBi, 1 dB)` [M] ; `+7,000000` = cumul [M] ; `−24,633450` = terme `10·n·log10(d/d₀)` à 1 200 m pour 3,5 → 2,7 [M] ; `0` = `simulate_uplinks_multi` n'accepte aucun frontal [M]. Trace neutre de référence : `−98,221395` dBm [R]. |
| **Preuves disponibles** | `docs/RF_MODEL.md` §10 ; `docs/audits/D3_RECONSTITUTION/RAPPORT_D3_1_RECONSTITUE.md` §5 ; `docs/RF_FRONTEND_V4.md`. |
| **Incertitudes restantes** | **`12` dB** : non reconstruit — le chemin mesh n'accepte aucun frontal, une mesure « mesh + gain » n'est pas exprimable dans le code actuel [M]. **`−91,892118` dBm** : non reconstruit après **1 077 570** combinaisons testées, 18 valeurs à ±5 × 10⁻⁴ dB, **aucune correspondance exacte** [R]. Les sondes `gain_global_L0*.py` et `mesh_rf_probe.py` sont perdues. |
| **Statut proposé [P]** | **PARTIELLEMENT RÉSOLUE** — cinq écarts sur sept expliqués et documentés ; deux restent sans origine établie. |

### M2 — `reference_distance_m` (d0) non honorée sans relief

| Champ | Contenu |
|---|---|
| **Statut Phase A** | **reproduit** (« d0 1↔10 : sorties identiques »). P2. |
| **Résultats D3.1 / D3.2** | `PL(d) = PL(d0) + 10·n·log10(d/d0)`, donc `ΔPL = (20 − 10n)·log10(d0₂/d0₁)` : **−7,000000 dB** à `n = 2,7` (à 1 000 m **et** à 3 000 m), **0,000000 dB** à `n = 2` [M]. L'invariance observée est donc une **coïncidence numérique** à `n = 2`, pas une propriété du modèle [M]. Explication du désaccord avec `sonde_d0.py` : marge minimale **+20,047 dB** sans relief (**0** trame à moins de 7 dB du seuil) contre **−35,712 dB** avec relief (**490** trames sur 5 000) [M] — un décalage de 7 dB ne peut changer aucune issue dans le premier cas, il le peut dans le second. |
| **Preuves disponibles** | `docs/audits/D3_RECONSTITUTION/logs/12_d0_marge.log` ; `docs/audits/D3_RECONSTITUTION/logs/10_sonde_d0_rejeu.log` ; `scripts/preuves/p_d0_marge.py` ; `docs/RF_MODEL.md` §2. |
| **Incertitudes restantes** | La docstring de `scripts/preuves/sonde_d0.py` affirme « d0 s'annule dans le modèle » **sans condition** : c'est exact à `n = 2` seulement. Le script n'a pas été modifié (hors périmètre). Le registre conserve la formulation d'origine. |
| **Statut proposé [P]** | **REQUALIFIÉE — résolue par explication** : l'invariance est réelle mais conditionnelle ; l'énoncé « `d0` sans effet » est réfuté. |

### M3 — Refus explicite d'une configuration RF partielle

| Champ | Contenu |
|---|---|
| **Statut Phase A** | **plausible, non prouvé**. P2. |
| **Résultats D3.1 / D3.2** | Chemin v4 : la table RF partielle est **refusée avant l'appel natif**, statut **301** côté cœur, aucun repli implicite [R]. Volet **mesh** : **non conclusif** — le mesh n'accepte aucun frontal, donc « acceptation silencieuse d'un `mesh_rf` partiel » n'est pas exprimable dans le code actuel [M]. |
| **Preuves disponibles** | `docs/RF_MODEL.md` §8 ; `python/tests/test_rf_scope.py::test_uplink_paths_without_frontend_stay_without_one` ; fiche M3 du registre. |
| **Incertitudes restantes** | Le comportement d'origine (celui que décrivait l'anomalie) n'a pas été observé sur le chemin mesh, faute de capacité RF sur ce chemin. La preuve v4 est **rapportée**, non rejouée dans cet environnement. |
| **Statut proposé [P]** | **PARTIELLEMENT ÉTABLIE** — v4 établi, mesh hors d'atteinte du code actuel. |

### RF-YAML — Aucune configuration RF dans les scénarios

| Champ | Contenu |
|---|---|
| **Statut Phase A** | **reproduit** (aucune clé `rf`). P1. |
| **Résultats D3.1 / D3.2** | `rf:` à la racine **et** dans un groupe : refusé par le modèle strict [M]. Aucune clé RF de scénario ; les seuls champs radio d'un groupe sont `spreading_factor`, `tx_power_dbm`, `payload_bytes`, `channel_freq_hz`, `sub_band`, `region`, `duty_cycle` [M]. Frontaux déclarables **uniquement** via l'API Python (`DeviceRf`, `GatewayRf`) [M]. |
| **Preuves disponibles** | `python/tests/test_rf_scope.py::test_scenario_refuses_an_rf_key_at_root`, `::test_scenario_refuses_an_rf_key_inside_a_group` ; `docs/RF_MODEL.md` §8 ; commit `dff67ba`. |
| **Incertitudes restantes** | La **capacité** n'existe toujours pas : documenter n'est pas implémenter. Ajouter `rf:` au YAML reste une décision produit non prise. |
| **Statut proposé [P]** | **CLOSE par documentation et test** — le comportement est figé et borné ; l'absence de capacité est un choix explicite, pas un défaut latent. |

### MULTI-V4 — `simulate_uplinks_multi` sans v4 et RF mesh absente

| Champ | Contenu |
|---|---|
| **Statut Phase A** | **reproduit** (signature sans RF). P2. |
| **Résultats D3.1 / D3.2** | `simulate_uplinks_multi` n'accepte **ni** `device_rf` **ni** `gateway_rf` [M] ; `simulate_multi_downlinks` **accepte** les deux [M]. Aucun symbole `multi_v4` parmi les exportations ; la capacité est **absente**, pas désactivée [R]. |
| **Preuves disponibles** | `python/tests/test_rf_scope.py::test_uplink_paths_without_frontend_stay_without_one`, `::test_trace_and_multi_downlink_paths_accept_both_frontends` ; `docs/RF_MODEL.md` §7 ; `docs/RF_FRONTEND_V4.md`. |
| **Incertitudes restantes** | Le tableau des 9 chemins est une **description de l'existant**, pas une spécification cible. Arbitrer l'ajout d'un `multi_v4` demande une décision d'architecture et d'ABI. |
| **Statut proposé [P]** | **CLOSE par documentation** — l'absence est désormais explicite et testée. |

### GEO-RF — Limites RF de `geo.py`

| Champ | Contenu |
|---|---|
| **Statut Phase A** | **reproduit** (7 clés, 211 l.). P2. |
| **Résultats D3.1 / D3.2** | Propriétés du document GeoJSON : **7 clés** (`environment`, `origin`, `pdr`, `scenario_name`, `scenario_sha256`, `total_received`, `total_sent`) [M] ; **aucun** champ de gain, EIRP, câble ou frontal [M] ; `python/lsim/geo.py` **inchangé** par les frontaux v4 [M]. |
| **Preuves disponibles** | `python/tests/test_rf_scope.py::test_geojson_carries_no_radio_frontend_field` ; `docs/RF_MODEL.md` §9. |
| **Incertitudes restantes** | L'export transporte une **distance** (`range_m`), pas un bilan radio : c'est une séparation assumée, non une lacune accidentelle. La rendre explicite dans un contrat de données reste à faire si un consommateur l'exige. |
| **Statut proposé [P]** | **CLOSE par documentation et test**. |

### LP64-14 — 14 assertions ABI en littéraux dans `test_rf_frontend.cpp`

| Champ | Contenu |
|---|---|
| **Statut Phase A** | **reproduit** (14 lignes 86–101). P2. |
| **Résultats D3.1 / D3.2** | Non instruite pendant D3. Mesure de l'audit : `grep` ⇒ 14 assertions ; la table i386 d'`abi_layout.cpp` donne 20/20/40 octets, **11 des 14 échouent en i386**, 3 concordent [R]. |
| **Preuves disponibles** | `scripts/preuves/verifier_assertions_lp64.py` ; `core/tests/abi_layout.cpp` ; `core/tests/test_rf_frontend.cpp` l. 86–101 ; `docs/audits/AUDIT_COMPLEMENT.md`. |
| **Incertitudes restantes** | Aucune sur le constat ; la correction (remplacer les littéraux par `abi_layout::expected::*`) n'est **pas appliquée**. |
| **Statut proposé [P]** | **OUVERTE** — correction mécanique identifiée, sans effet sur x86-64, à planifier. |

### I386 — Aucune compilation complète du moteur en 32 bits

| Champ | Contenu |
|---|---|
| **Statut Phase A** | **reproduit** (lien `-m32` impossible). P3. |
| **Résultats D3.1 / D3.2** | Non instruite pendant D3. `gcc -m32` échoue sur `cannot find -lgcc` [R] : l'environnement n'a ni CRT, ni libc, ni libstdc++ 32 bits. |
| **Preuves disponibles** | `scripts/preuves/verifier_abi_layout.sh` ; `docs/audits/AUDIT_COMPLEMENT.md`. |
| **Incertitudes restantes** | Dépend de l'environnement, pas du dépôt : aucune correction de code ne fermerait l'anomalie à elle seule. |
| **Statut proposé [P]** | **OUVERTE** — contrainte d'environnement documentée. |

### M1 — Point d'audit R2b, définition perdue

| Champ | Contenu |
|---|---|
| **Statut Phase A** | **non reproductible**. P2. |
| **Résultats D3.1 / D3.2** | Aucun. Le document source est déclaré introuvable ; `AUDIT_RECHERCHE_TRACES.md` documente 15 méthodes de recherche restées vaines. |
| **Preuves disponibles** | `docs/audits/AUDIT_RECHERCHE_TRACES.md` (journal de recherche, 116 l.). |
| **Incertitudes restantes** | Ni l'énoncé, ni le périmètre, ni le composant concerné ne sont connus. Aucune instruction n'est possible sans source. |
| **Statut proposé [P]** | **OUVERTE — en attente des éléments sources nécessaires à leur instruction.** Aucune clôture administrative. |

### M4 — Documentation après M1–M3

| Champ | Contenu |
|---|---|
| **Statut Phase A** | **non reproductible**. P3. |
| **Résultats D3.1 / D3.2** | Aucun. M4 dépend de M1–M3 ; M1 étant sans énoncé, M4 n'a pas de contenu déterminable. |
| **Preuves disponibles** | Aucune pièce propre. |
| **Incertitudes restantes** | Le périmètre de M4 pourrait recouvrir partiellement ce que `docs/RF_MODEL.md` traite aujourd'hui — hypothèse **non vérifiée**, à ne pas présenter comme un début de résolution. |
| **Statut proposé [P]** | **OUVERTE — en attente des éléments sources nécessaires à leur instruction.** Aucune clôture administrative. |

### D1 — Chiffres faux dans `CHANGELOG.md`

| Champ | Contenu |
|---|---|
| **Statut Phase A** | **reproduit** (1832/685235 vs 1839/685249). P3. |
| **Résultats D3.1 / D3.2** | Corrigé pendant la Phase A (commit `8d296e2`). Les valeurs d'origine `1832` et `685235` ne correspondent à **aucun commit** [R]. |
| **Preuves disponibles** | `docs/audits/README.md` §4 (table par commit : `9686c25`, `c46d531`, `2202782`, `c77f8eb`, `68176d6`). |
| **Incertitudes restantes** | L'origine exacte des deux valeurs initiales n'est pas établie — d'où leur remplacement par des mesures. |
| **Statut proposé [P]** | **CLOSE pour la correction**, avec réserve documentée sur l'origine des valeurs retirées. |

### D2 — Archive F2 + G1 : référence distante en retard d'un push

| Champ | Contenu |
|---|---|
| **Statut Phase A** | **reproduit** (`diff -r` sur `.git/refs/remotes`). P3. |
| **Résultats D3.1 / D3.2** | Non instruite. L'anomalie portait sur une archive nommée ; les 10 archives de `sauvegardes/` ont été **perdues** avec l'environnement. |
| **Preuves disponibles** | `docs/audits/AUDIT_BILAN_SAUVEGARDES.md` ; `docs/audits/AUDIT_REGISTRE_ANOMALIES.md` fiche D2. |
| **Incertitudes restantes** | L'objet même de l'anomalie n'existe plus : elle ne peut être ni confirmée ni infirmée par une nouvelle mesure. |
| **Statut proposé [P]** | **OUVERTE, non instruisable** — conserver le constat historique sans le rouvrir. |

### E1 — Dépôt principal sale

| Champ | Contenu |
|---|---|
| **Statut Phase A** | **reproduit**. P2. |
| **Résultats D3.1 / D3.2** | Toujours **88 entrées** (47 modifications + 41 non suivis) au 2026-11-02, `HEAD = 1f43370` [M]. Le dépôt principal n'a jamais servi d'environnement d'expérience. |
| **Preuves disponibles** | `git -C /home/user/simulateur-de-reseau-lorawan status --porcelain` (88 lignes). |
| **Incertitudes restantes** | L'intention derrière ces 88 entrées n'est pas connue : ni à committer, ni à supprimer sans décision explicite. |
| **Statut proposé [P]** | **OUVERTE** — préexistante, hors du périmètre D3 ; à arbitrer séparément. |

### E2 — Preuves antérieures perdues

| Champ | Contenu |
|---|---|
| **Statut Phase A** | **reproduit** (absentes des 9 archives). P1. |
| **Résultats D3.1 / D3.2** | 14 rapports jamais commités sont **définitivement perdus** — contrôle effectué sur les **169 commits** que comptait l'historique au moment de la recherche (le dépôt en compte **172** depuis `d85b50c`, `dff67ba` et `fd5cdb5`). Remédiation partielle : `d3_recon_preuves/` (14 fichiers, 13/13 empreintes), bundle + tar (5 fichiers vérifiés), et le commit `fd5cdb5` (11 fichiers). |
| **Preuves disponibles** | `d3_recon_preuves/` ; `sauvegardes_d32/` ; `docs/audits/D3_RECONSTITUTION/` ; `EMPREINTES.sha256`. |
| **Incertitudes restantes** | Les 18 sondes et 45 journaux de D3.1 restent perdus ; la reconstitution ne les remplace pas, elle les **documente**. La sauvegarde et son export vivent dans le **même environnement** que ce qu'ils protègent, jusqu'à confirmation de réception sur le poste utilisateur. |
| **Statut proposé [P]** | **PARTIELLEMENT REMÉDIÉE** — la perte est circonscrite et tracée, pas effacée. |

---

## 3. Points de méthode

### 3.1 Ce que ce document ne fait pas

- Il **ne réécrit pas** le registre de la Phase A ; celui-ci conserve ses statuts et son empreinte.
- Il **ne corrige aucun code** et ne rouvre aucune mesure.
- Il **ne clôt aucune anomalie** : les statuts proposés attendent un arbitrage nommé.

### 3.2 Texte imposé pour F1 — **libellé introuvable**

Une formulation de remplacement avait été exigée pour la phrase du registre « 0 échec : 112 … puis
240 … ». **Sa formulation exacte n'a pas été retrouvée.**

Recherche effectuée le 2026-11-02, sur tout l'espace de travail (hors `build/`, `.git/`,
`node_modules/`, `.venv-recon/`), y compris le contenu extrait du `tar.gz` de sauvegarde :

| Motif recherché | Occurrences |
|---|---|
| `352 exécutions` | 0 |
| `0 échec de convergence` | 0 |
| `absence de défaut` | 0 |
| `demeure non reproduite` | 0 |
| `0/352` | 0 |

Aucun artefact conservé ne porte ce libellé. Le résumé de session en contient une **reformulation**,
mais un résumé n'est pas une capture verbatim : il ne peut pas servir de référence.

**Conséquence** : ce document ne propose **aucune** restitution de ce texte, et le registre n'est
pas modifié. Si le libellé doit être inscrit dans le dépôt, il doit être **fourni à nouveau** par
l'auteur de la consigne, puis cité tel quel.

### 3.3 Écarts entre le registre et l'état mesuré

| Ligne du registre | Ce qu'elle affirme | Ce qui est mesuré |
|---|---|---|
| F1, §1 | « non reproduit (0 échec : 112 … puis 240 …) » | 69/120 échecs dès que la boucle est exercée [M] |
| F1, §2 | « aucune graine en échec observée sur les chemins testés » | vrai **pour les chemins testés**, qui n'exerçaient pas la boucle [M] |
| M2 | « `d0` 1↔10 : sorties identiques » | vrai **à `n = 2` seulement** [M] |
| F6 | « écarts en dB non reproduits » | 5 écarts sur 7 expliqués [M] |

Ces écarts sont **documentés**, non corrigés : c'est l'objet même de ce suivi annexe.

---

## 4. Ce que ce document ne prouve pas

- Il ne transforme pas un résultat **[R]** en résultat **[M]** : les emplacements marqués [R] n'ont
  pas été rejoués.
- Il ne démontre pas que la liste des 15 anomalies est complète.
- Il ne préjuge pas de l'issue de l'arbitrage : chaque « statut proposé » est une **option**, pas une
  décision.
