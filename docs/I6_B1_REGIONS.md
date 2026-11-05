# I6-b1 — Cadrage définitif : conformité régionale des fenêtres RX1

| | |
|---|---|
| **Lot** | I6-b1 — vérification normative des tables régionales, volet « corrections déjà représentables » |
| **Référence normative cible** | RP002-1.0.5 (LoRa Alliance, octobre 2025) |
| **Statut du document** | Cadrage finalisé — **en attente d'autorisation d'implémentation** |
| **Date de rédaction** | 2026-11-05 |
| **Branche** | `arena/fdc94521-simulateur-de-reseau-lorawan` |
| **Racine vérifiée** | `4f8dc5a` (209 commits, 0 modification) |
| **Ligne de base C++** | 1/1 test passé — `core_unit_tests` |
| **Ligne de base Python** | 2287 réussis, 1 ignoré, 16 sous-tests, 125 s |
| **Empreinte binaire** | `liblsim_core.so` = 596 696 octets |

> **Avertissement de lecture.** Ce document distingue trois régimes de preuve, et cette
> distinction est structurante :
> **[N]** normatif — lu dans un document LoRa Alliance ;
> **[H]** matériel — implémentation de référence (LoRaMac-node v4.7.1), jamais normative seule ;
> **[D]** hypothèse — non vérifiée, explicitement signalée comme telle.
> Aucune valeur issue de LoRaMac-node n'est présentée comme certifiée sans corroboration [N].

---

## 1. Périmètre définitif

I6-b1 corrige **un seul défaut**, sur **une seule région**, dans **un seul fichier** :

| Objet | Valeur |
|---|---|
| Fichier | `python/lsim/au915.py` |
| Ligne | **45** |
| Champ | `rx1_dr` |
| Défaut | les 7 valeurs sont erronées |
| Origine | table **US915** transplantée dans le plan AU915 |

**Exclusions explicites** (décidées, non négociables dans ce lot) :

| Exclu | Motif | Renvoi |
|---|---|---|
| IN865 DR6 | fonctionnalité distincte ; ne doit pas modifier indirectement l'ADR | **Q1**, lot séparé |
| Offsets 1 à 5 | non représentables dans le modèle actuel | **I6-b2** |
| Dwell time AS923 | évolution du résolveur | **I6-b2** |
| DR7 FSK, DR14, SF5/SF6, LR-FHSS | extensions introduites ou révisées par RP002-1.0.5 | lot séparé |
| Table des charges utiles AU915 (écart de 20 octets) | défaut distinct, non normatif au sens d'I6-b1 | §8, lot séparé |
| Divergence Python ↔ moteur C++ multi-passerelles | relève de la fidélité radio du moteur | **I6-c**, après I1 |

---

## 2. Délimitation stricte d'I6-b1

Les quatre confirmations demandées sont apportées ci-dessous.

### 2.1 La table 7 × 6 est la référence normative complète — OUI, sous réserve L1

La table AU915 complète couvre **7 débits montants (DR0–DR6) × 6 offsets (0–5) = 42 cellules**.
Elle est la référence complète du comportement RX1 de la région. Sa **structure** est confirmée
par RP002-1.0.5 lu directement ; ses **42 cellules** sont corroborées par deux publications
LoRa Alliance antérieures, mais **pas lues dans RP002-1.0.5** (voir §6 et la limite **L1**).

### 2.2 I6-b1 ne corrige que la colonne offset 0 — OUI

Seule la colonne 0 est actuellement représentable : le modèle `Plan` stocke un dictionnaire
`rx1_dr: dict[int, int]` indexé par DR montant, sans dimension d'offset. Les colonnes 1 à 5
n'ont nulle part où être stockées. Leur ajout exige un changement de structure du résolveur,
ce qui est précisément l'objet d'I6-b2.

### 2.3 Les offsets non nuls restent exclus — OUI

Ils appartiennent à **I6-b2**. Aucune assertion, aucun test et aucune valeur d'offset non nul
n'est introduit dans I6-b1.

### 2.4 Aucun changement de schéma ni d'ABI — OUI, démontré

Démonstration par la chaîne causale, vérifiée dans le dépôt :

```
au915.py:45  rx1_dr
      ↓
plan.py:72   Plan.rx1(tx_dr, tx_ch) → (fréquence, datr)
      ↓
trace_events.py:263   rx1_mhz, rx1_datr = plan.rx1(dr, ch)
trace_events.py:267   rx1_sf, rx1_bw_hz = int(m.group(1)), int(m.group(2)) * 1000
      ↓
trace_events.py:283   DeviceRadio(rx1_sf=…, rx1_bw_hz=…)
      ↓
downlink_plan.py:289-290   c_radios[i].rx1_sf = d.rx1_sf ; c_radios[i].rx1_bw_hz = …
      ↓
cœur C++ (champs rx1_sf / rx1_bw_hz de lsim_plan_device)
```

Le cœur C++ **ne contient aucune table régionale**. Une recherche exhaustive dans `core/`
sur `rx1_dr`, `DatarateOffsets` et `rx1_dr_offset` ne remonte que :

- `lsim_mac_command.rx1_dr_offset` — champ de **transport** d'une commande MAC
  (`RxParamSetupReq`), codé sur 3 bits, plage 0..7, sans sémantique régionale ;
- aucune table de résolution RX1.

Le moteur reçoit donc des valeurs **déjà résolues** (SF et bande). Corriger `au915.py:45`
modifie les valeurs transmises, **pas la forme des données**. Conséquences :

- aucun champ de structure C modifié ;
- aucune recompilation nécessaire ;
- `.so` inchangée (596 696 octets) ;
- `_multi_dl_v3` et l'ABI versionnée additive restent du ressort d'**I6-d**.

---

## 3. Fichiers et fonctions concernés

### 3.1 Fichier modifié

| Fichier | Ligne | Nature |
|---|---|---|
| `python/lsim/au915.py` | **45** | correction des 7 valeurs de `rx1_dr` |
| `python/lsim/au915.py` | 11–13, 15–18, 20 | docstring : références normatives erronées, à refondre (§7) |

### 3.2 Fonctions en lecture (non modifiées)

| Fonction | Fichier | Rôle |
|---|---|---|
| `Plan.rx1(tx_dr, tx_ch)` | `plan.py:72-79` | résout (fréquence, datr) de RX1 ; **indépendante de `rx1_dr` pour la fréquence** |
| `Plan.__init__` (l. 57) | `plan.py:57` | dérive `queue_payload_max` — **point d'arbitrage, §8** |
| `_radio(plan, …)` | `trace_events.py:254-285` | consomme `plan.rx1()` et en extrait SF/bande |
| `device_radios(scenario)` | `trace_events.py:304` | construit les radios par dispositif |
| `downlink_airtime_by_device` | `trace_events.py:1644` | consomme SF/bande RX1 pour l'occupation |

### 3.3 Fichiers **non** concernés

`us915.py`, `eu868.py`, `as923.py`, `in865.py`, `kr920.py`, `ru864.py` sont **100 % conformes**
à la référence (38 cas sur 38, voir §5.2). Conformément à **Q4**, ils ne sont **pas modifiés** :
aucun en-tête de traçabilité ne leur est ajouté.

---

## 4. Valeurs corrigées

### 4.1 Correction d'I6-b1 (colonne offset 0)

```python
# python/lsim/au915.py:45
# AVANT (erroné — 7 valeurs sur 7)
rx1_dr={0: 10, 1: 11, 2: 12, 3: 13, 4: 13, 5: 10, 6: 11},

# APRÈS (conforme)
rx1_dr={0: 8, 1: 9, 2: 10, 3: 11, 4: 12, 5: 13, 6: 13},
```

| DR montant | Débit montant | RX1 simulé (erroné) | RX1 attendu | Rapport de durée d'émission |
|---|---|---|---|---|
| DR0 | SF12/125 | DR10 · SF10BW500 | **DR8 · SF12BW500** | 0,29× |
| DR1 | SF11/125 | DR11 · SF9BW500 | **DR9 · SF11BW500** | 0,29× |
| DR2 | SF10/125 | DR12 · SF8BW500 | **DR10 · SF10BW500** | 0,29× |
| DR3 | SF9/125 | DR13 · SF7BW500 | **DR11 · SF9BW500** | 0,29× |
| DR4 | SF8/125 | DR13 · SF7BW500 | **DR12 · SF8BW500** | 0,50× |
| DR5 | SF7/125 | DR10 · SF10BW500 | **DR13 · SF7BW500** | 7,01× |
| DR6 | SF8/500 | DR11 · SF9BW500 | **DR13 · SF7BW500** | 3,50× |

Rapports mesurés avec la fonction du projet (`lsim.lora.time_on_air_ns`), trame de 13 octets,
en-tête explicite, CR 4/5, sans CRC, sans DE.

**L'écart est non monotone** (de 0,29× à 7,01×, dans les deux sens) : aucun facteur correctif
global n'est applicable. Chaque valeur doit être corrigée individuellement.

### 4.2 Table complète 7 × 6 — référence (hors périmètre de correction d'I6-b1)

Colonnes = `RX1DROffset` 0 → 5.

| DR ↑ \ off → | 0 | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|---|
| **DR0** | DR8 | DR8 | DR8 | DR8 | DR8 | DR8 |
| **DR1** | DR9 | DR8 | DR8 | DR8 | DR8 | DR8 |
| **DR2** | DR10 | DR9 | DR8 | DR8 | DR8 | DR8 |
| **DR3** | DR11 | DR10 | DR9 | DR8 | DR8 | DR8 |
| **DR4** | DR12 | DR11 | DR10 | DR9 | DR8 | DR8 |
| **DR5** | DR13 | DR12 | DR11 | DR10 | DR9 | DR8 |
| **DR6** | DR13 | DR13 | DR12 | DR11 | DR10 | DR9 |

**Sources.** DR0–DR4 : *LoRaWAN Regional Parameters v1.0.3revA*, **Table 40**
« AU915-928 downlink RX1 data rate mapping », **[N]**.
DR5–DR6 : *LoRaWAN Regional Parameters v1.1rA*, **Table 39**, même intitulé, **[N]**.
Les deux publications portent la phrase : « *The allowed values for RX1DROffset are in the
[0:5] range.* » — **[N]**.

**Corroboration [H].** `DatarateOffsetsAU915[7][6]` dans
`RegionAU915.h` (LoRaMac-node, tag `v4.7.1`) concorde sur **42 cellules sur 42**.

### 4.3 Invariant physique de contrôle

À offset 0, la descente conserve le **facteur d'étalement** de la montante, en le transportant
sur 500 kHz :

```
DR0 SF12/125 → DR8 SF12/500      DR3 SF9/125 → DR11 SF9/500
DR1 SF11/125 → DR9 SF11/500      DR4 SF8/125 → DR12 SF8/500
DR2 SF10/125 → DR10 SF10/500     DR5 SF7/125 → DR13 SF7/500
```

La référence respecte cet invariant sur DR0–DR5. Le simulateur le contredit sur **6 DR sur 7**.
Cet invariant est un **test**, pas une preuve : il ne remplace pas la lecture normative.

---

## 5. Preuves normatives et leurs limites

### 5.1 Ce qui est lu **directement** dans RP002-1.0.5

Extraction du PDF officiel (115 pages), sommaire et tables de synthèse :

| Élément | Contenu | Statut |
|---|---|---|
| **Table 4** — synthèse régionale | AU915 `Allowed RX1DRoffset` = **[0:5]** ; US915 = **[0:3]** ; `Default RX1DRoffset` = 0 ; `Default RX2DataRate` = DR8 ; `Default RX2 Frequency` = 923,3 MHz | **[N]** lu |
| **Table 5** — Global data rates | AU915 descendant DR8→SF12/500 … DR13→SF7/500 ; montant DR0→SF12/125 … DR5→SF7/125, DR6→SF8/500 | **[N]** lu |
| **§3.3** — Default Settings | `DownlinkDwellTime` = 0 ; `RECEIVE_DELAY1` = 1 s | **[N]** lu |
| **Table 7** | RP002-1.0.5 ⇒ identifiant de révision `RP2-1.0.5` | **[N]** lu |
| **Sommaire** | §3.8 « AU915-928 » p.**56** ; §3.8.7 « Receive Windows » p.**62** | **[N]** lu |

**Argument interne décisif.** RP002-1.0.5 publie, pour AU915, une plage d'offsets autorisés
de **[0:5]**, soit **six** valeurs. La table de correspondance RX1 de cette région comporte donc
**six colonnes**. Une table à quatre colonnes (offsets 0–3) serait en contradiction avec la
plage publiée par le **même document**. Cet argument est interne à RP002-1.0.5 et ne dépend
d'aucune publication antérieure.

### 5.2 Ce qui **n'est pas** lu : la page 62 (limite L1)

La table 7 × 6 elle-même, au §3.8.7 p.62, **n'a pas pu être lue**. Quatre routes ont été
tentées et ont échoué :

| # | Route | Résultat |
|---|---|---|
| 1 | Découpage séquentiel du PDF | 11 segments ; plafonne vers **p. 31 / 115** — huit à neuf segments sont consommés par la table ISO 3166-1 des pays. Fin de flux au segment 10. |
| 2 | Fragment `#page=62` sur l'URL du PDF | le fragment est ignoré : le document est renvoyé depuis la page 1 |
| 3 | Page du flipbook avec `?page=62` | renvoie uniquement la coquille du visualiseur (« 0 of 115 », « Loading… »), **aucun texte** |
| 4 | Téléchargement direct puis extraction locale | hôte `content.cdntwrk.com` hors des accès réseau autorisés ; aucune copie miroir trouvée sur GitHub (recherche par contenu et par dépôt) ; `pypdf` installé et disponible, sans fichier à traiter |

> **L1 — RÉSERVE MAINTENUE.** Les 42 cellules du §4.2 sont **corroborées par des publications
> antérieures et par l'implémentation de référence**, elles ne sont **pas directement vérifiées
> dans RP002-1.0.5**. Cette distinction est conservée explicitement, conformément à la demande.
> Elle n'affecte pas la colonne offset 0 de deux manières : la structure à six colonnes est
> attestée par la Table 4 de RP002-1.0.5, et les colonnes de la référence sont stables entre
> les versions 1.0.2, 1.0.3 et 1.0.5 (voir §5.3).

### 5.3 Comparaison interversions

Aucune différence affectant la **colonne offset 0** d'AU915 n'a été identifiée entre
RP002-1.0.2, RP002-1.0.3 et RP002-1.0.5. La correction est donc **insensible au choix de
version** — ce qui ne dispense pas de lever L1 pour les offsets 1 à 5.

Nouveautés de 1.0.5 **hors périmètre** d'I6-b1 : SF5/SF6, DR7 LR-FHSS 1 523 kHz, DR9 SF6/125,
DR10 SF5/125, DR14 SF6/500, dépréciation de CN779-787 (depuis 1.0.4).

### 5.4 Coexistence des versions dans le dépôt (Q2-e)

Hors `python/build/` (artefact git-ignoré qui duplique les sources), **six** versions
coexistent :

| Version | Citations | Fichiers principaux |
|---|---|---|
| 1.0.2 | 29 | `kr920.py` (6), `as923.py` (4), `eu868.py`/`gwmp_server.py`/`in865.py` (2 chacun), **`au915.py` (1)** |
| 1.0.5 | 22 | `CONFORMANCE_MATRIX.md` (9), `CHANNEL_MASK_MODEL.md` (3), `closed_loop_v3.py`, `gateway_sensitivity.py`, 6 tests |
| 1.0.0 | 13 | `regions.py` (6) |
| 1.0.3 | 4 | **`au915.py` (1)** |
| 1.0.4 | 2 | — |
| 1.0.1 | 1 | `plan.py` |

`plan.py` cite à lui seul 1.0.1, 1.0.2 **et** 1.0.4. Cette hétérogénéité est un défaut de
traçabilité général, **distinct** du défaut de valeurs traité par I6-b1. Sa normalisation
constitue un lot séparé ; elle n'est pas entreprise ici.

---

## 6. Diagnostic de l'origine du défaut (révisé)

### 6.1 Preuve interne : deux versions dans un même fichier

`au915.py:11` déclare :

> « RX1 (**RP002-1.0.3, tableau AU915** : RX1DROffset 0) : débit DR0→DR10, DR1→DR11… »

La version citée est la bonne (1.0.3), la région est la bonne (**AU915**), l'offset est le bon
(0) — et les valeurs encodées sont celles d'**US915**. La ligne 15 du même fichier cite
**RP002-1.0.2**. L'auteur a identifié la section à remplir, puis a recopié la table voisine.

### 6.2 Nature exacte de la table transplantée

Comparaison des tables de référence (LoRaMac-node v4.7.1) :

```
DatarateOffsetsUS915[5][4]  colonne 0 :  DR_10, DR_11, DR_12, DR_13, DR_13     ← DR0..DR4
DatarateOffsetsAU915[7][6]  colonne 0 :  DR_8, DR_9, DR_10, DR_11, DR_12, DR_13, DR_13
au915.py:45                           :  10,   11,   12,   13,   13,   10,   11
```

Les cinq **premières** valeurs du simulateur reproduisent exactement la colonne 0 d'US915.
Les deux **dernières** (DR5→10, DR6→11) n'existent pas dans la table US915 à cinq lignes,
mais correspondent aux lignes **LR-FHSS** de la table US915 à sept lignes, où
**DR5 → SF10/500 (DR10)** et **DR6 → SF9/500 (DR11)** **[H]** — corroboré par le projet
`LoRaWAN-SIM`, qui documente ces deux mappages d'après RP002-1.0.5 §3.5.

**Le point décisif** : en **AU915**, DR5 et DR6 sont des débits **LoRa** (SF7/125 et SF8/500),
alors qu'en **US915** ce sont des débits **LR-FHSS**. La table transplantée applique donc à
AU915 des lignes issues d'une classe de modulation que cette région n'utilise pas à ces
indices. Le défaut est double : valeurs fausses **et** classe de modulation sous-jacente
étrangère à la région.

### 6.3 Piste non résolue — signalée, non tranchée

Des extraits d'index de recherche portant sur RP002-1.0.2 et RP002-1.0.3 présentent une table
AU915 à **quatre colonnes** et sept lignes, avec DR0→DR10, DR5→DR10, DR6→DR11. Si elle était
avérée, elle expliquerait directement les sept valeurs du simulateur.

**Ces extraits n'ont pas pu être vérifiés dans les PDF correspondants** (même plafond
d'extraction qu'au §5.2). Ils peuvent être le fruit d'une fusion de tables voisines par
l'index de recherche. Ils sont donc consignés comme **piste [D]**, et **ne sont pas** retenus
comme preuve. Ils ne modifient en rien la correction proposée, laquelle s'appuie sur la
structure à six colonnes attestée par RP002-1.0.5 Table 4.

---

## 7. Traçabilité (Q4)

Un **en-tête de traçabilité** est ajouté **au seul fichier `au915.py`** — seul fichier régional
modifié, conformément à la consigne « ne modifie pas les fichiers régionaux qui ne sont pas
concernés ».

Modèle d'en-tête, avec le vocabulaire de statuts imposé :

```python
"""Plan AU915-928 (…), RP002.

Conformité régionale
--------------------
Référence normative ...... RP002-1.0.5 (LoRa Alliance, octobre 2025)
Table applicable ......... §3.8.7 « AU915-928 Receive Windows »
                           (page 62 — NON LUE DIRECTEMENT, voir L1)
Source de la table RX1 ... v1.0.3revA Table 40 (DR0–DR4) + v1.1rA Table 39 (DR5–DR6)
Plage d'offsets .......... [0:5] — RP002-1.0.5 Table 4
Date de vérification ..... 2026-11-05
Vérificateur ............. agent Arena, lot I6-b1

Statut de vérification
----------------------
Colonne offset 0 ......... NORMATIF CONFIRMÉ
Offsets 1 à 5 ............ NORMATIF CONFIRMÉ (corroboration antérieure à 1.0.5, L1)
Plage [0:5] .............. NORMATIF CONFIRMÉ (RP002-1.0.5 Table 4, lu)
Charges utiles N ......... HYPOTHÈSE NON VÉRIFIÉE (écart de 20 octets, hors lot)
DR7 / DR14 / SF5 / SF6 ... NON REPRÉSENTÉ
"""
```

| Statut | Signification |
|---|---|
| **NORMATIF CONFIRMÉ** | valeur lue dans un document LoRa Alliance |
| **CORROBORÉ PAR IMPLÉMENTATION** | concordance LoRaMac-node, **sans** lecture normative |
| **HYPOTHÈSE NON VÉRIFIÉE** | valeur non vérifiée, à ne pas présenter comme conforme |

---

## 8. Point d'arbitrage — la borne de file (découverte en cours de cadrage)

### 8.1 Le couplage

`plan.py:57` dérive la borne de file des DR RX1 atteignables :

```python
self.queue_payload_max = min(self._max_payload[dr] for dr in set(self._rx1_dr.values()))
```

Corriger `rx1_dr` rend **DR8** atteignable — dont la charge utile maximale est la plus faible.
La borne de file d'AU915 **changerait donc mécaniquement**, sans que la table des charges
utiles ne soit touchée.

| Situation | DR RX1 atteignables | `queue_payload_max` |
|---|---|---|
| Actuel (défaut) | {10, 11, 12, 13} | **222** octets |
| Après correction, table de charges actuelle | {8, 9, 10, 11, 12, 13} | **33** octets |
| Après correction, table de référence | idem | **53** octets |

Mesures relevées dans le dépôt (`AU915._max_payload`) ; la « table de référence » est
`MaxPayloadOfDatarateDwell0AU915` (LoRaMac-node v4.7.1) **[H]**.

### 8.2 L'écart de charge utile est systématique

| DR | Référence [H] | Simulateur | Écart |
|---|---|---|---|
| DR8 | 53 | 33 | +20 |
| DR9 | 129 | 109 | +20 |
| DR10 | 242 | 222 | +20 |
| DR11 | 242 | 222 | +20 |
| DR12 | 242 | 222 | +20 |
| DR13 | 242 | 222 | +20 |

L'écart est **uniformément de 20 octets** sur les six DR descendants. Ce défaut est
**distinct** de celui des valeurs RX1 : il n'est pas corrigé par I6-b1.

### 8.3 Pourquoi c'est un arbitrage, pas une décision technique

Les trois tests qui portent sur la borne de file deviendraient faux :

| Test | Assertion | Après correction |
|---|---|---|
| `test_au915.py:52` | `queue_payload_max == 222` | deviendrait 33 |
| `test_au915.py:67` | enfile 222 octets avec succès | échouerait |
| `test_au915.py:68-69` | 223 octets refusés | échouerait |

Réduire la file descendante d'AU915 de 222 à 33 octets est une **modification fonctionnelle
majeure**, obtenue **indirectement** par une correction de table. C'est exactement le type
d'effet que l'arbitrage **Q1** a exclu pour IN865 DR6. Quatre voies :

| Voie | Contenu | Conséquence |
|---|---|---|
| **A** | Corriger `rx1_dr`, accepter la borne à 33 | cohérent avec l'invariant de `plan.py:56`, mais sévèrement restrictif |
| **B** | Corriger `rx1_dr` **et** la table des charges (33→53, 109→129, 222→242) | nécessite sa propre vérification normative ; sort du périmètre I6-b1 |
| **C** | Revoir l'invariant de la borne (la borner par RX2, ou par dispositif) | changement de conception ; sort clairement d'I6-b1 |
| **D** | Ne corriger que `rx1_dr` et ouvrir un lot distinct pour la borne | cohérent avec le traitement réservé à IN865 DR6 (Q1) |

**Recommandation : voie D**, par symétrie avec la décision Q1 — la borne de file est traitée
comme une fonctionnalité distincte, sans masquer que la correction de `rx1_dr` la modifie
dans l'intervalle. **Ce point requiert votre arbitrage explicite avant implémentation.**

---

## 9. Tests d'acceptation

### 9.1 Résolveur Python — remplacement des huit assertions

Les huit assertions AU915 actuelles encodent le défaut. Elles sont **remplacées** (jamais
supprimées) par des assertions conformes.

| # | Test | Remplace | Assertion |
|---|---|---|---|
| **T-B1-1** | `test_au_rx1_data_rate_offset_zero` (7 cas paramétrés) | `test_au915.py:38-43` | DR0→`SF12BW500`, DR1→`SF11BW500`, DR2→`SF10BW500`, DR3→`SF9BW500`, DR4→`SF8BW500`, DR5→`SF7BW500`, DR6→`SF7BW500` |
| **T-B1-2** | `test_au_rx1_preserves_spreading_factor` (6 cas) | — | à offset 0, SF(RX1) = SF(montant) sur DR0–DR5 |
| **T-B1-3** | `test_au_rx1_dr_in_downlink_range` | — | tout DR RX1 ∈ [8, 13] |
| **T-B1-4** | `test_au_rx1_channel_is_tx_channel_modulo_8` | conservé **à l'identique** | la fréquence ne dépend pas de `rx1_dr` |
| **T-B1-5** | `test_au915_end_to_end_join_ack_and_queue` | `test_au915.py:64` | `outcome.txpk.datr == "SF12BW500"` (DR0 → DR8) |
| **T-B1-6** | `test_au_queue_limit_and_rx2` | `test_au915.py:52` | **suspendu** — dépend de l'arbitrage §8 |
| **T-B1-7** | non-régression des 6 autres régions (38 cas) | — | EU868, US915, AS923, IN865, KR920, RU864 inchangés |
| **T-B1-8** | `test_au915_traceability_header` | — | `au915.py` porte l'en-tête de traçabilité (§7) |

**Témoins US915 — intouchés** (5 cas, garants de l'absence de contagion) :
`test_plan.py:31`, `test_plan.py:43`, `test_uplink.py:404`, `test_uplink.py:414`,
`test_lrfhss_unsupported.py:30`.

### 9.2 Moteur C++ multi-passerelles — triple verdict (Q3)

**T-B1-9** est scindé en **trois verdicts indépendants**, qui ne doivent jamais être confondus :

| Verdict | Objet | Attendu en I6-b1 | État |
|---|---|---|---|
| **(A)** | **Résolveur Python régional** : `Plan.rx1()` produit-il le bon (fréquence, DR) ? | **Conforme** après correction | testé par T-B1-1 à T-B1-5 |
| **(B)** | **Moteur C++ multi-passerelles** : son comportement actuel | **Divergent** — constaté, **non corrigé** | test de **caractérisation** |
| **(C)** | **Parité Python ↔ C++ après I6-c** | **Différée** — hors I6-b1 | test **marqué `xfail`**, non désactivé |

Règle inscrite : **une validation du résolveur Python ne vaut jamais validation du moteur C++.**
Le verdict (A) ne doit pas être présenté comme une validation du moteur.

Contenu de (B) : `build_multi_trace` n'exploite que `rx1_hz`, `freq_hz` et `dr` ; seul
`downlink_airtime_by_device` (`trace_events.py:1644`) consomme le SF et la bande de RX1. La
divergence porte sur la fidélité radio du moteur multi-passerelles, objet d'I6-c.

### 9.3 Garde-fou — suite verte n'est pas conformité (G8)

Les huit assertions actuelles sont **vertes avant correction**. La suite Python complète
(2287 réussis, 1 ignoré) l'est également. Une suite verte ne démontre donc pas la conformité :
les tests encodaient le défaut. Ce point est rappelé pour qu'aucun résultat vert ultérieur ne
soit interprété comme une preuve de conformité.

---

## 10. Risques résiduels

| # | Risque | Nature | Mitigation |
|---|---|---|---|
| **R1** | **L1** — 42 cellules non lues dans RP002-1.0.5 | preuve | la correction ne porte que sur la colonne 0, dont la structure à 6 colonnes est attestée par RP002-1.0.5 Table 4 ; L1 doit être levée avant I6-b2 |
| **R2** | La correction modifie **indirectement** la borne de file (222 → 33) | fonctionnel | arbitrage §8 requis avant implémentation |
| **R3** | La piste [D] du §6.3, si elle était avérée, modifierait le récit du défaut | diagnostic | sans effet sur la correction, fondée sur la Table 4 |
| **R4** | Six versions de RP002 coexistent ; `plan.py` en cite trois | traçabilité | lot de normalisation distinct |
| **R5** | L'écart systématique de 20 octets sur les charges utiles reste non vérifié | conformité | hors I6-b1, lot distinct |
| **R6** | Confondre verdict (A) et verdict (C) dans T-B1-9 | méthode | triple verdict séparé, (C) en `xfail` |
| **R7** | Présenter la suite verte comme preuve de conformité | méthode | garde-fou G9.3 |
| **R8** | Les valeurs corrigées changent l'occupation RX1 (0,29× à 7,01×) : les scénarios AU915 enregistrés changeront | physique | changement **physique** attendu, à documenter comme tel — jamais comme une non-régression |

> **R8 est le plus important.** Les durées d'occupation RX1 d'AU915 changent dans un rapport
> allant de 0,29× à 7,01×. Tout scénario AU915 enregistré verra ses résultats évoluer. C'est
> la **conséquence physique de la correction**, et non un effet de bord : elle doit être
> documentée comme un changement de comportement physique, conformément à l'exigence
> transversale de ne jamais masquer un changement physique en non-régression.

---

## 11. Critères de sortie d'I6-b1

I6-b1 est terminé lorsque **toutes** les conditions suivantes sont réunies :

| # | Critère | Vérification |
|---|---|---|
| **S1** | `au915.py:45` porte les 7 valeurs conformes | relecture + T-B1-1 |
| **S2** | En-tête de traçabilité présent dans `au915.py`, avec les statuts de §7 | T-B1-8 |
| **S3** | Les 6 autres régions sont **strictement inchangées** | `git diff --stat` + T-B1-7 |
| **S4** | Aucun fichier hors `au915.py` et ses tests n'est modifié | `git diff --stat` |
| **S5** | Aucune ABI, aucun schéma C modifié ; `.so` non recompilée | empreinte 596 696 octets |
| **S6** | Témoins US915 intouchés et verts | 5 cas de §9.1 |
| **S7** | Suite C++ : 1/1 ; suite Python : 2287 réussis, 1 ignoré | `ctest`, `pytest` |
| **S8** | T-B1-9 produit trois verdicts **distincts** et documentés | A conforme, B constaté, C `xfail` |
| **S9** | L1 est mentionnée dans le code et dans ce document | §5.2, §7 |
| **S10** | L'arbitrage §8 est tranché **avant** implémentation | décision explicite |
| **S11** | Le changement d'occupation RX1 est documenté comme changement physique | §10 R8 |

**S10 est un préalable, pas un critère de sortie** : il doit être levé avant la première
modification de code.

---

## 12. Résumé des décisions en attente

| # | Objet | Statut |
|---|---|---|
| **A1** | Arbitrage de la borne de file AU915 (§8, voies A/B/C/D) | **en attente** |
| **A2** | Autorisation d'implémenter I6-b1 | **en attente** |
| **A3** | Lot distinct pour la normalisation des versions RP002 (§5.4) | à programmer |
| **A4** | Lot distinct pour l'écart de 20 octets sur les charges utiles (§8.2) | à programmer |
| **A5** | Levée de L1 — accès direct au PDF RP002-1.0.5 | bloqué sur l'accès réseau |

---

## 13. État des lieux de l'environnement

Vérifié après reconstruction, le 2026-11-05 :

| Emplacement | État |
|---|---|
| Clone de travail | `4f8dc5a`, 209 commits, **0 modification** |
| Dépôt principal `/home/user/simulateur-de-reseau-lorawan` | `1f43370`, **88 modifications intactes** |
| `main` distante | `1f43370` — inchangée |
| PR #3 | `OPEN`, `MERGEABLE` — non fusionnée |
| Tests C++ | 1/1 passé |
| Tests Python | 2287 réussis, 1 ignoré, 16 sous-tests, 125 s |
| `liblsim_core.so` | 596 696 octets |
| Références LoRaMac-node | 15 fichiers au tag `v4.7.1` |
| Script d'audit | `d1_i6b1_compare.py` — 45 cas, 7 divergences |

**Aucune modification de code, aucun commit de code, aucun push de code.** Le présent
document est le seul contenu ajouté.
