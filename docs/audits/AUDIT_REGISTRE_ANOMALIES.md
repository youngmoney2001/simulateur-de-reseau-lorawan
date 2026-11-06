# Registre des anomalies ouvertes — audit du 2026-10-31

**Référence** `68176d6` · **Aucune anomalie n'a été corrigée pendant l'audit.**
Chaque entrée porte : identifiant, description, composant, preuve reproductible, impact,
dépendances, correction envisageable, risque de régression, priorité technique.
La colonne **Preuve** distingue explicitement ce qui a été **reproduit** dans cet audit de ce qui
reste **non reproductible** (document ou sonde perdu).

---

## 1. Tableau de synthèse

| ID | Sujet | Composant | Preuve | Priorité |
|---|---|---|---|---|
| **F1** | Divergence du chemin causal / point fixe, RF neutre | `trace_events.py`, `simulator.py` | **non reproduit** (0 échec : 112 exécutions de la sonde reconstruite, puis 240 du balayage Phase A, qui la contient) | P1 |
| **F6** | Cohérence de `d0` et du chemin RF | `engine.cpp`, `mesh.py`, `downlink_plan.py` | **partiel** : `d0` reproduit ; écarts en dB non reproduits | P1 |
| **LP64-14** | 14 assertions ABI en littéraux (annoncées « 8 ») | `core/tests/test_rf_frontend.cpp` | **reproduit** (14 lignes 86–101) | P2 |
| **I386** | Moteur 32 bits jamais compilé/exécuté | chaîne de build | **reproduit** (lien `-m32` impossible) | P3 |
| **RF-YAML** | Aucune configuration RF dans les scénarios | `python/lsim/scenario.py`, schémas | **reproduit** (aucune clé `rf`) | P1 |
| **MULTI-V4** | `simulate_uplinks_multi` sans variante v4 ; RF mesh absente | `simulator.py`, `mesh.py`, ABI | **reproduit** (signature sans RF) | P2 |
| **GEO-RF** | `geo.py` sans configuration RF résolue | `python/lsim/geo.py` | **reproduit** (7 clés, 211 l.) | P2 |
| **M1** | Point d'audit R2b — définition perdue | — | **non reproductible** | P2 |
| **M2** | `reference_distance_m` (d0) non honorée sans relief | `core/src/engine.cpp` | **reproduit** (d0 1↔10 : sorties identiques) | P2 |
| **M3** | Refus explicite d'une configuration RF partielle | ABI v4 / mesh | **plausible, non prouvé** | P2 |
| **M4** | Documentation après M1–M3 | docs | **non reproductible** | P3 |
| **D1** | Chiffres faux dans `CHANGELOG.md` | `CHANGELOG.md` | **reproduit** (1832/685235 vs 1839/685249) | P3 |
| **D2** | Archive F2 + G1 : référence distante en retard d'un push | `sauvegardes/` | **reproduit** (`diff -r` sur `.git/refs/remotes`) | P3 |
| **E1** | Dépôt principal sale (47 M + 41 ??) | `/home/user/simulateur-de-reseau-lorawan` | **reproduit** | P2 |
| **E2** | Preuves antérieures perdues (sondes, rapports) | hors dépôt | **reproduit** (absentes des 9 archives) | P1 |

Légende priorité : **P0** = bloquant (aucun) · **P1** = à traiter avant toute nouvelle
fonctionnalité · **P2** = à planifier · **P3** = documentation / dette acceptée.

---

## 2. Fiches détaillées

### F1 — Divergence du chemin causal / point fixe avec RF neutre

| Champ | Contenu |
|---|---|
| **Description** | Comparaison du chemin causal (`simulate_uplinks_causal*`, `build_trace`) avec le chemin de trace en configuration RF neutre : 38/40 scénarios identiques, graines **11** et **38** en échec (`RuntimeError` de point fixe). |
| **Composant** | `python/lsim/trace_events.py` (boucle de point fixe), `python/lsim/simulator.py` (routage), `core/src/engine.cpp` (chemins causaux). |
| **Preuve reproductible** | **Non reproduit.** Sonde reconstruite le 2026-10-31 : (a) **40 exécutions** = 1 exemple (`examples/quartier_sf9.yaml`) × 40 graines (0–39) × 1 jeu d'options (`ProtocolOptions()` par défaut) ⇒ **0 échec** ; (b) **72 exécutions** = 3 exemples (`quartier_sf9.yaml`, `quartier_relief_sf9.yaml`, `mesh_relais_quartier.yaml`) × 12 graines (0–11) × 2 jeux d'options (`ProtocolOptions()`, `confirmed_uplinks=True, downlink_every=2`) ⇒ **0 échec**. Total **112 exécutions** : les 12 configurations `quartier_sf9` / graines 0–11 / options par défaut sont communes aux deux séries, soit **100 configurations distinctes** exécutées une ou deux fois. **Balayage de Phase A** (script `scripts/preuves/balayage_graines.py`) : **240 exécutions distinctes** = 3 exemples × 40 graines (0–39) × 2 jeux d'options ⇒ **0 échec** ; ce balayage est un **sur-ensemble** des 112 exécutions précédentes. La sonde d'origine (`f1_balayage_40_graines.py`) est **perdue** ; on ignore la paramétrisation exacte (quels 40 scénarios, quelles options, quel chemin). |
| **Impact** | Inconnu. Si le défaut existe, il se manifeste par une **non-convergence** (exception), pas par un résultat faux silencieux. Aucune graine en échec n'a été observée sur les chemins testés. |
| **Dépendances** | Aucune dépendance de code ; dépend de la **restitution** de la sonde ou d'un accord sur une nouvelle définition du balayage. |
| **Correction envisageable** | 1) Rejouer un balayage **défini explicitement** (scénarios, options, nombre de graines) et publier le script dans `scripts/`. 2) Si un échec apparaît, instrumenter la boucle de point fixe (itérations, écart) avant toute modification. |
| **Risque de régression** | **Élevé** : toute modification de `build_trace` ou de l'ordre des émissions change les empreintes de trace `ed126d7f…`. |
| **Priorité** | **P1** (fiabilité), à traiter en diagnostic **avant** toute correction. |

### F6 — Cohérence de `d0` et du chemin RF

| Champ | Contenu |
|---|---|
| **Description** | Sept écarts mesurés lors de l'audit de réception : causal 0 dB ; trace RF neutre 0 dB ; `link_adr` v4 **+2,000 dB** ; multi **+5,000 dB** ; mesh exposant 2,7→3,5 = **−24,633450 dB** ; `mesh_rf` partiel **12 dB** ; `d0` ignorée sans relief (**−91,892118 dBm**). |
| **Composant** | `core/src/engine.cpp` (3 sites `std::max(hypot, reference_distance_m)`), `python/lsim/mesh.py`, `python/lsim/downlink_plan.py`, `python/lsim/geo.py` (indirect). |
| **Preuve reproductible** | **Partielle.** Reproduit : `d0 = 1` et `d0 = 10` donnent des sorties **identiques** sans relief (comparaison ligne à ligne + totaux + passerelle) et **différentes** avec `examples/quartier_relief_sf9.yaml`. Non reproduit : les écarts en dB (`+2,000`, `+5,000`, `−24,633450`, `12`, `−91,892118`), faute des sondes `gain_global_L0*.py` et `mesh_rf_probe.py`. |
| **Impact** | Incohérence de modèle entre chemins (causal, trace, multi, mesh) sur la manière dont `d0` et la chaîne RF entrent dans le bilan. Aucun impact sur les scénarios sans RF ni relief (empreintes identiques). |
| **Dépendances** | Dépend de F1 (même boucle) et de RF-YAML (pour tester un scénario « avec RF » de bout en bout). |
| **Correction envisageable** | Unifier explicitement `d0` (documenter qu'elle s'annule dans le modèle log-distance, ou la faire entrer dans le calcul) **puis** aligner les quatre chemins. Toute unification doit être précédée d'un état des lieux chiffré reproductible. |
| **Risque de régression** | **Très élevé** : toucher au calcul de perte change `d2cb0fac…` **et** `ed126d7f…`. |
| **Priorité** | **P1**, mais **après** restauration des sondes et validation utilisateur du modèle cible. |

### LP64-14 — Assertions ABI en littéraux dans `test_rf_frontend.cpp`

| Champ | Contenu |
|---|---|
| **Description** | 14 assertions `sizeof`/`offsetof` codées en valeurs LP64 : `lsim_device_rf` (4), `lsim_gateway_rf` (4), `lsim_closed_loop_v4_args` (6). Les rapports antérieurs annoncent « 8 assertions », ce qui **sous-estime la dette de 6**. |
| **Composant** | `core/tests/test_rf_frontend.cpp`, lignes **86–101**. |
| **Preuve reproductible** | `grep -n "sizeof(lsim_\|offsetof(lsim_"` ⇒ lignes 86–101 (14 assertions). La table i386 de `core/tests/abi_layout.cpp` donne pour les mêmes structures `20 / 20 / 40` octets et des décalages différents (`4 / 12`, `12 / 16 / 20 / 24`) : **11 des 14 échouent en i386**, les 3 autres
(`offsetof(present) = 0` dans les deux structures, `offsetof(v3) = 8`) sont indépendantes de l'ABI. |
| **Impact** | Le fichier de test RF ne peut pas être compilé pour i386 ; la couverture RF n'existe que sur une ABI. |
| **Dépendances** | `abi_layout.cpp` fournit déjà les constantes (`abi_layout::expected::*`). |
| **Correction envisageable** | Remplacer les 14 littéraux par les constantes `abi_layout::expected::size_lsim_device_rf`, `off_lsim_device_rf__present`, etc. Correction mécanique, sans effet sur x86-64. |
| **Risque de régression** | **Faible** (test seulement), à condition de ne pas modifier les structures. |
| **Priorité** | **P2**. |

### I386 — Aucune compilation complète du moteur en 32 bits

| Champ | Contenu |
|---|---|
| **Description** | Seules les **dispositions** ABI sont vérifiées en i386 (`-m32 -ffreestanding -c`). Aucun binaire 32 bits n'est produit ni exécuté. |
| **Composant** | Chaîne de build, `core/tests/abi_layout.cpp`. |
| **Preuve reproductible** | `gcc -m32` sur un `int main(void){return 0;}` ⇒ `ld: cannot find -lgcc` (pas de CRT, pas de libc, pas de libstdc++ 32 bits). Le harnais i386 **compile** (objet produit) ; il ne se **lie** ni ne s'exécute. |
| **Impact** | Toute affirmation « compatible 32 bits » doit rester limitée aux dispositions. Tests RF, exécution, performances : non démontrés. |
| **Dépendances** | Paquets multilib (`gcc-multilib`, `libc6-dev-i386`) indisponibles hors ligne. |
| **Correction envisageable** | Soit installer une chaîne 32 bits complète, soit produire une image de conteneur dédiée ; sans cela, la limite est définitive. |
| **Risque de régression** | Nul (aucun code touché). |
| **Priorité** | **P3** (limite assumée, à répéter dans chaque rapport). |

### RF-YAML — Aucune configuration RF dans les scénarios

| Champ | Contenu |
|---|---|
| **Description** | Le frontal RF n'existe qu'au niveau **ABI** et **API Python** (`DeviceRf`/`GatewayRf`). Aucune clé `rf` n'est acceptée dans un scénario YAML ; `GroupModel` ne porte ni gain d'antenne ni perte de câble. |
| **Composant** | `python/lsim/scenario.py` (modèles stricts), `schemas/`, `python/lsim/simulator.py`. |
| **Preuve reproductible** | `grep -n "rf" python/lsim/scenario.py` ⇒ aucune clé de scénario ; un YAML portant `rf:` serait refusé (`_Strict`). `simulate_uplinks_trace(..., device_rf=…)` est la seule voie. |
| **Impact** | La promesse « configuration indépendante par capteur » n'est pas atteignable par un utilisateur de scénario : il faut passer par l'API. Bloque aussi F2 (@6.2) et G1 (@6.3) dans leur version « avec RF ». |
| **Dépendances** | Contrat R2b (stable), régénération des schémas, empreintes (doivent rester inchangées **sans** clé `rf`). |
| **Correction envisageable** | Ajouter un bloc optionnel `rf: {antenna_gain_dbi, cable_loss_db}` par groupe et par passerelle, absent du hash quand non fourni, propagé jusqu'aux tables v4. |
| **Risque de régression** | **Moyen** : schémas et hash de scénario ; risque d'empreinte si le bloc est écrit même vide (précédent R2b documenté). |
| **Priorité** | **P1** (écart produit le plus visible). |

### MULTI-V4 — `simulate_uplinks_multi` sans v4 et RF mesh absente

| Champ | Contenu |
|---|---|
| **Description** | `simulate_uplinks_multi` (multi-passerelles sans downlinks) n'accepte pas de frontal ; la variante v4 existe pour la trace, la trace gw2, les downlinks multi et la boucle fermée, pas pour ce chemin. Le mesh s'appuyant sur ce chemin, aucune RF mesh n'est modélisée. |
| **Composant** | `python/lsim/simulator.py`, `core/src/c_api_ext.cpp`, `python/lsim/mesh.py`. |
| **Preuve reproductible** | Signature `simulate_uplinks_multi(devices, gateways, propagation, environment=None, gateway_busy=None, with_trace=False)` — **aucun** paramètre RF. `nm -D` : aucun symbole `lsim_simulate_uplinks_multi_v*`. Test `test_rf_path_never_calls_a_mesh_symbol` : le chemin RF LoRaWAN n'appelle aucun `lsim_mesh_*`. |
| **Impact** | Un utilisateur du mesh ne peut pas configurer d'antenne ni de câble ; toute étude mesh + RF est impossible. |
| **Dépendances** | Design mesh (G×N, pertes émetteur/récepteur, sous-GHz) déjà arbitré mais **non implémenté**. |
| **Correction envisageable** | Nouveau point d'entrée `lsim_simulate_uplinks_multi_v2` + paramètres Python, avec refus explicite si `mesh_rf` est partiel. |
| **Risque de régression** | Moyen (surface ABI additive, mais le mesh a ses propres empreintes). |
| **Priorité** | **P2**. |

### GEO-RF — Limites RF de `geo.py`

| Champ | Contenu |
|---|---|
| **Description** | `geo.py` calcule une couverture par (passerelle × groupe) à partir du SF et de `tx_power_dbm` du groupe ; aucune PIRE résolue, aucune perte de câble, aucun indice par groupe, aucun champ `eirp_dbm`/`device_indices_in_group`. |
| **Composant** | `python/lsim/geo.py` (211 lignes), `python/tests/test_geo.py`. |
| **Preuve reproductible** | 7 clés exactement par Feature `coverage` (`kind, group, gateway, spreading_factor, tx_power_dbm, range_m, model`), vérifié par `test_g1_homogeneous_group_keeps_the_historical_format`. |
| **Impact** | La carte ne reflète pas un frontal RF ; deux terminaux d'un même groupe ne peuvent pas différer en portée. |
| **Dépendances** | RF-YAML (source des paramètres), décision sur le format GeoJSON hétérogène. |
| **Correction envisageable** | Regrouper par configuration **résolue** (EIRP, pertes), ajouter les champs optionnels seulement si hétérogène, conserver le format historique sinon. |
| **Risque de régression** | Moyen (contrat GeoJSON consommé par `web/`). |
| **Priorité** | **P2**. |

### M1 — Point d'audit R2b (définition perdue)

| Champ | Contenu |
|---|---|
| **Description** | Point identifié lors de l'audit de clôture R2b, avec l'arbitrage **M1-B** consigné en session. Le document source (`R2B_CLOTURE_AUDIT_ANOMALIES.md`, 704 l., SHA-256 `1d2f5ad06e0f042630796325426643704cf670b5810ef125a0af907c272cc03e`) est **perdu** et absent des 9 archives. |
| **Composant** | Inconnu. |
| **Preuve reproductible** | **Aucune.** Ni le dépôt ni `/home/user` ne contiennent la définition ; `docs/CONFORMANCE_MATRIX.md` utilise `M1`–`M4` pour des exigences TS001 §5 **sans rapport**. |
| **Impact** | Non évaluable tant que la définition n'est pas rétablie. |
| **Dépendances** | Restitution du document (utilisateur) ou re-identification par un audit ciblé. |
| **Correction envisageable** | **Ne rien corriger à l'aveugle.** Re-identification : reprendre les points de l'audit R2b un par un et produire une fiche par point. |
| **Risque de régression** | Non évaluable. |
| **Priorité** | **P2** (traçabilité), bloquant pour toute action sur ce point. |

### M2 — `d0` (`reference_distance_m`) non honorée sans relief

| Champ | Contenu |
|---|---|
| **Description** | `reference_distance_m` n'a **aucun effet** en l'absence de relief ; elle n'agit qu'avec un environnement. Arbitrage retenu en session : **M2-A « honorer d0 »**. |
| **Composant** | `core/src/engine.cpp` (3 sites `std::max(hypot, reference_distance_m)`), `python/lsim/radio.py`. |
| **Preuve reproductible** | Deux variantes de `examples/quartier_sf9.yaml` (`d0 = 1` et `d0 = 10`) ⇒ sorties **identiques** (lignes, totaux, passerelle) ; mêmes variantes sur `quartier_relief_sf9.yaml` ⇒ sorties **différentes**. |
| **Impact** | Paramètre décoratif sans relief ; un utilisateur qui règle `d0` n'obtient aucun changement. La limite est mathématiquement cohérente pour un modèle log-distance où `PL(d0)` est l'espace libre à `d0`, mais elle n'est **pas documentée** comme telle. |
| **Dépendances** | F6 (même sujet), empreintes gelées. |
| **Correction envisageable** | Soit documenter explicitement l'invariance (option la moins risquée), soit faire entrer `d0` dans le calcul (change les empreintes). |
| **Risque de régression** | **Élevé** si le calcul change ; nul si la documentation est corrigée. |
| **Priorité** | **P2**. |

### M3 — Refus explicite d'une configuration RF partielle

| Champ | Contenu |
|---|---|
| **Description** | Décision **M3-A « refus explicite »** : une configuration RF partielle doit être refusée, jamais complétée silencieusement. Le périmètre exact visé (table ABI, `mesh_rf`, ou les deux) n'est pas attesté par un document conservé. |
| **Composant** | ABI v4 (`apply_device_rf`, `trace_v2_impl`), chemin mesh. |
| **Preuve reproductible** | **Partielle.** Sur le chemin ABI v4, le refus existe et est testé (`test_partial_tables_are_refused_before_the_native_call`, `test_rf_table_count_must_be_zero_or_complete`, `test_multi_dl_refuses_a_partial_gateway_table`). Sur le mesh, l'écart F6 « `mesh_rf` partiel 12 dB » suggère une acceptation silencieuse, **non reproduite** (sonde perdue). |
| **Impact** | Si le mesh accepte un frontal partiel, un utilisateur croit avoir configuré un gain qui n'est appliqué qu'en partie. |
| **Dépendances** | MULTI-V4 (le mesh n'a pas de v4), F6. |
| **Correction envisageable** | Aligner la règle mesh sur la règle v4 : 0 ou complet, sinon statut 301. |
| **Risque de régression** | Faible sur LoRaWAN, moyen sur les scénarios mesh existants. |
| **Priorité** | **P2**. |

### M4 — Documentation après M1–M3

| Champ | Contenu |
|---|---|
| **Description** | Arbitrage **M4-A** : documenter après résolution de M1–M3. Contenu exact perdu. |
| **Composant** | `docs/`, `CHANGELOG.md`. |
| **Preuve reproductible** | **Aucune** ; dépend de M1–M3. |
| **Impact** | Documentaire. |
| **Dépendances** | M1, M2, M3. |
| **Correction envisageable** | Une fois M1–M3 tranchés, écrire une section « modèle RF et `d0` » dans `docs/RF_FRONTEND_V4.md` et un encart dans le CHANGELOG. |
| **Risque de régression** | Nul. |
| **Priorité** | **P3**. |

### D1 — Chiffres faux dans `CHANGELOG.md`

| Champ | Contenu |
|---|---|
| **Description** | L'entrée « Frontal RF v4 » annonce « 1778 → 1832 tests Python (dont 30 pour le frontal), C++ 685165 → 685235 vérifications ». Mesures réelles de la branche : **1802 → 1839** tests Python et **685165 → 685249** vérifications C++. L'entrée R1 annonce « 685165/685165, 91 symboles » sans mentionner les 1802 tests Python de R1. |
| **Composant** | `CHANGELOG.md` (lignes 5–16). |
| **Preuve reproductible** | `pytest python/tests` à `c46d531` = 1802 ; à `68176d6` = 1846 (1839 à `c77f8eb` + 7 F2/G1) ; `lsim_tests` = 685249. |
| **Impact** | Un lecteur du CHANGELOG croit à 14 tests et 14 vérifications de moins que la réalité, et à un point de départ faux. |
| **Dépendances** | Aucune. |
| **Correction envisageable** | Corriger les quatre nombres (documentation seule, aucun test affecté). |
| **Risque de régression** | Nul. |
| **Priorité** | **P3**. |

### D2 — Archive F2 + G1 : référence distante en retard d'un push

| Champ | Contenu |
|---|---|
| **Description** | L'archive `f2g1_20261031T182441Z` a été prise **avant** le push : son `.git/refs/remotes/origin/arena/…` pointe `c77f8eb` alors que le direct pointe `68176d6`. Le `diff -r` « identique » n'est donc vrai qu'en excluant cette référence. |
| **Composant** | `sauvegardes/f2g1_20261031T182441Z.tar.gz`. |
| **Preuve reproductible** | `diff -r` ⇒ 2 écarts, tous deux dans `.git/refs/remotes/origin/…` (ref + log) ; `HEAD` identique `68176d6`, 332 fichiers identiques, clone du bundle à `68176d6`, 0 sale. |
| **Impact** | Aucun sur le contenu ; risque de conclusion erronée si l'on affirme « identique » sans nuance. |
| **Dépendances** | Aucune. |
| **Correction envisageable** | Prendre les prochaines archives **après** push, ou exclure explicitement `refs/remotes` des comparaisons. |
| **Risque de régression** | Nul. |
| **Priorité** | **P3**. |

### E1 — Dépôt principal sale

| Champ | Contenu |
|---|---|
| **Description** | `/home/user/simulateur-de-reseau-lorawan` : HEAD `1f43370`, branche `arena/…`, reflog limité à `clone` + `checkout`, mais **47 fichiers modifiés** et **41 non suivis** correspondant à l'instantané de travail antérieur à `9686c25`. |
| **Composant** | Dépôt principal (hors périmètre d'écriture). |
| **Preuve reproductible** | `git -C … status --porcelain` ⇒ 47 ` M` + 41 `??` ; `git reflog` ⇒ 2 entrées ; `diff` de `core/include/lsim/c_api.h` avec la branche ⇒ fichiers différents (78 069 vs 86 017 octets). |
| **Impact** | Risque de confusion de source de vérité, de build involontaire ou de `diff` trompeur. Aucun impact sur la branche poussée. |
| **Dépendances** | Autorisation utilisateur (hors périmètre actuel). |
| **Correction envisageable** | Archiver l'arbre sale puis `git checkout -- .` / `git clean -fd`, ou le laisser tel quel en le documentant. |
| **Risque de régression** | Nul sur la branche ; **perte de données** si nettoyage sans archive. |
| **Priorité** | **P2** (hygiène), **mais aucune action sans accord explicite**. |

### E2 — Preuves antérieures perdues

| Champ | Contenu |
|---|---|
| **Description** | Documents et sondes d'audit antérieurs absents : `R2B_CLOTURE_AUDIT_ANOMALIES.md`, `F7_ABI_I386_DIAGNOSTIC.md`, `F7_CORRECTION_RAPPORT.md`, `AUDIT_BRANCHEMENT_V4.md`, `R2B_PREUVES.md`, `preuves/f7/`, `preuves/audit_reception/`, `symbols_before/after_*.txt`. |
| **Composant** | Hors dépôt (`/home/user/r1_r2`, perdu). |
| **Preuve reproductible** | Aucun des 9 tar.gz de `sauvegardes/` ne contient ces fichiers (`tar tzf | grep -ci "anomalie\|AUDIT"` ⇒ 0 pour chacun). |
| **Impact** | Les conclusions qui en dépendent (mutations R2b, kit i386 F7, F1, F6 en dB, M1–M4) ne sont **pas rejouables** ; elles sont reclassées « non validées par cet audit ». |
| **Dépendances** | Aucune. |
| **Correction envisageable** | Reconstruire les sondes critiques et les versionner dans `scripts/preuves/` (le dépôt est le seul stockage durable). |
| **Risque de régression** | Nul. |
| **Priorité** | **P1** (condition de toute confiance future). |

---

## 3. Ce qui est **fermé**

| ID | Objet | Preuve de fermeture |
|---|---|---|
| **F2** | Décision « test runtime de l'isolation des imports » | 1 test d'exécution à 5 marqueurs, 55 tests verts, 4 mutations détectées (phase F2 + G1) |
| **G1** | Contract GeoJSON couvert | 6 tests, 6 mutations détectées, écart de spec documenté |
| **F7** | Dispositions ABI 32/64 | 458 `static_assert`, harnais x86-64 exécuté, i386 compilé |
| **R2b** | Frontal RF v4 | 95 symboles, 11 tests C++, 30 tests Python, empreintes inchangées ; résultats de mutations **rapportés lors de R2b**, scripts non conservés et mutations **non rejouées dans cet audit** |
