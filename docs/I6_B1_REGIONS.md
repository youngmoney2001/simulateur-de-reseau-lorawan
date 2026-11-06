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

> **Recommandation initiale : voie D**, par symétrie avec la décision Q1.
>
> **Recommandation révisée après audit : voie B** — voir les sections **§12** (audit),
> **§13** (options) et **§14** (recommandation argumentée). L'audit a en effet révélé que
> les valeurs DR8 = 33 et DR9 = 109 d'AU915 constituent un **second défaut, démontrable par
> contradiction interne** avec US915 pour une modulation identique. Le corriger porte la
> borne à **53** octets — voisine des 51 déjà en vigueur dans cinq régions — au lieu des 33
> que produirait la seule correction du mappage.
>
> **Ce point requiert votre arbitrage explicite avant implémentation.**

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

## 12. Audit ciblé de `queue_payload_max`

*Section ajoutée à la demande expresse : « je ne souhaite pas que la borne passe
automatiquement de 222 à 33 octets sans analyse complémentaire ».*

### 12.1 Définition et portée exacte

**Calculé en un seul endroit** — `plan.py:57` :

```python
# Une charge en file doit tenir dans toutes les fenêtres RX1 atteignables.
self.queue_payload_max = min(self._max_payload[dr] for dr in set(self._rx1_dr.values()))
```

Nature : **limite d'admission en file, statique, calculée une fois par plan**. C'est le
*minimum* de la charge utile maximale sur l'**union** des DR RX1 atteignables depuis
n'importe quel DR montant du plan. C'est une borne **du pire cas**, volontairement
conservatrice : elle garantit qu'une charge admise tiendra quelle que soit la fenêtre
finalement utilisée.

Ce n'est : ni une capacité maximale théorique de la région, ni une limite par terminal,
ni une limite par DR, ni une négociation à l'émission.

### 12.2 Les trois points d'application (recherche exhaustive)

| # | Emplacement | Rôle | Nature |
|---|---|---|---|
| 1 | `plan.py:57` | **calcul** | dérivé de `rx1_dr` et de `max_frm_payload` |
| 2 | `join_store.py:451-453` | **admission en file** — rejet si `len(payload) > limite` | contrôle effectif, le seul |
| 3 | `uplink.py:204, 234` → `_build_downlink` (assertion l. 261) | contrôle défensif | **inatteignable par construction** — la file a déjà refusé |
| 4 | 7 tests | `test_au915.py:52`, `test_plan.py:51`, `test_as923.py:58`, `test_eu868.py:33`, `test_in865.py:57`, `test_kr920.py:57`, `test_ru864.py:57` | garde-fous |

La recherche a porté sur tous les types de fichiers du dépôt (`.py`, `.hpp`, `.cpp`, `.h`,
`.md`, JSON, JS), à l'exclusion des répertoires `build/`, `node_modules/` et `.git/`.

### 12.3 Ce que `queue_payload_max` n'est **pas**

| Propriété | État |
|---|---|
| Exposé dans `RegionInfo` (contrat d'API) | **Non** — interne |
| Consulté par le chemin trace / scénario | **Non** |
| Limite physique de transmission | **Non** — borne d'admission |

### 12.4 Les deux chemins de descente sont indépendants

Découverte structurante : le dépôt comporte **deux mécanismes de limitation disjoints**.

```
Chemin A — file / serveur lié à une session
    join_store.enqueue_downlink()  ──►  rejet si > plan.queue_payload_max  (par région)
    uplink._build_downlink()       ──►  assertion défensive (inatteignable)

Chemin B — trace / scénario / simulation
    ProtocolOptions.downlink_payload_bytes
    trace_events.py:501-502        ──►  rejet si > 242  (borne CODÉE EN DUR)
    api_contract.py:82             ──►  Field(10, ge=0, le=242)
```

Le chemin B **n'utilise jamais la file** (aucune occurrence de `enqueue_downlink`,
`queue_head` ou `queue_payload` dans `trace_events.py`) et **ne consulte aucune table
régionale** : sa borne de 242 est invariante par région.

**Conséquence directe.** Une modification de `queue_payload_max` n'affecte **que** le
chemin A. Les scénarios de simulation, les preuves et l'étude panel (chemin B) sont
**inchangés**. Notamment `scripts/preuves/b_d315_charge.py`, qui balaie les sept régions
avec des trames de 20, 60, 120 et 240 octets, relève du chemin B : il est **insensible** à
la borne de file.

*Corollaire — lacune préexistante.* Le chemin B n'applique aucune validation par DR : il
peut émettre une trame de 240 octets sur une fenêtre SF12/500 qui n'en supporte que 53.
Cette lacune est **antérieure à I6-b1** et lui est **étrangère** ; elle est signalée ici sans
être traitée.

### 12.5 Conséquences d'une limite globale à 33 octets

| Conséquence | Gravité |
|---|---|
| Cinq des sept régions sont déjà à **51** (EU868, AS923, IN865, KR920, RU864). Une borne à 33 ferait d'AU915 la région la plus contrainte du simulateur | **majeure** |
| Le commentaire de `au915.py:17-18` devient faux | à reprendre |
| `test_au915.py:52` (222), `:64` (datr), `:67-69` (file de 222 octets) deviennent faux | à reprendre |

> **Correction d'une erreur de la première version de ce document.**
> Une version antérieure avançait qu'une borne à 33 octets « ne laisserait aucune place à la
> charge applicative, parce que Join-Accept fait 33 octets ». **Cet argument est faux et a
> été retiré.** Il comparait deux grandeurs hétérogènes : la taille d'un **PHYPayload complet**
> (Join-Accept) et une limite de **charge applicative** (N). Join-Accept n'emprunte d'ailleurs
> pas la file et n'est donc pas soumis à `queue_payload_max`. Voir **§12.9**.

### 12.9 Le chemin Join-Accept est distinct — vérification

| Question | Réponse | Preuve |
|---|---|---|
| Join-Accept emprunte-t-il `enqueue_downlink()` ? | **Non** | aucune occurrence de `enqueue_downlink`, `queue_payload_max`, `queue_head` ou `store.` dans `join.py` |
| Est-il soumis à `queue_payload_max` ? | **Non** | idem |
| Quelle est sa taille ? | **PHYPayload complet** : 17 octets, ou **33 avec CFList** | `join.py:78` ; `security.py:371` « 17 octets, ou 33 avec CFList » ; `trace_events.py:86` (`JOIN_ACCEPT_BYTES = 17`) |
| Quelles sont ses contraintes ? | les siennes propres : trame de taille fixe, fenêtres RX1 (5 s) puis RX2 (6 s), repli par `lsim.arbitre` | `join.py:79-82` |
| Par quel canal I6-b1 l'atteint-il ? | **le temps d'antenne, pas la file** | `accept_airtime_ns()` (`join.py:299-313`) résout la fenêtre par `downlink_phy(radio, window)` → `radio.rx1_sf` / `rx1_bw_hz` |

**Trois grandeurs à ne pas confondre** :

| Grandeur | Désignation | Taille (AU915 DR8) | Chemin |
|---|---|---|---|
| **M** | MACPayload maximal | **61** | référence normative |
| **N** | charge applicative maximale **sans FOpts** | **53** = M − 8 | `max_frm_payload`, `queue_payload_max` |
| Join-Accept | **PHYPayload complet** | **33** (17 sans CFList) | chemin propre, hors file |

**Impact réel d'I6-b1 sur Join-Accept** — par le temps d'antenne, trame de 33 octets :

| DR montant | RX1 actuel | durée | RX1 corrigé | durée | rapport |
|---|---|---|---|---|---|
| DR0 | SF10/500 | 113,2 ms | **SF12/500** | 411,6 ms | **3,64×** |
| DR1 | SF9/500 | 61,7 ms | SF11/500 | 205,8 ms | 3,34× |
| DR2 | SF8/500 | 33,4 ms | SF10/500 | 113,2 ms | 3,39× |
| DR3 | SF7/500 | 18,0 ms | SF9/500 | 61,7 ms | 3,43× |
| DR4 | SF7/500 | 18,0 ms | SF8/500 | 33,4 ms | 1,86× |
| DR5 | SF10/500 | 113,2 ms | **SF7/500** | 18,0 ms | **0,16×** |
| DR6 | SF9/500 | 61,7 ms | **SF7/500** | 18,0 ms | **0,29×** |

C'est un **changement physique**, à documenter comme tel (§10 R8), jamais comme une
non-régression. Il concerne la durée d'occupation des fenêtres, pas l'admission en file.

### 12.6 Faisabilité d'une limite par DR

Les briques existent déjà :

| Brique | Emplacement | Disponibilité |
|---|---|---|
| `Plan.max_frm_payload(dr)` | `plan.py:125-129` | **publique**, déjà exposée |
| `Plan.dr_of_downlink_datr(datr)` | `plan.py` | publique |
| Le DR de la fenêtre | connu dans `_build_downlink` via `rx1` | oui |

**L'obstacle est conceptuel, pas technique.** La file est admise **à la mise en file**,
moment où le DR de la fenêtre future est **inconnu** : le terminal peut changer de DR
(ADR, rebonds) entre la mise en file et l'émission. Une limite par DR impose donc l'un de :

1. valider à l'émission — mais la charge est déjà en file : la refuser rompt le contrat de file ;
2. connaître le DR du terminal à la mise en file — couplage nouveau entre `join_store` et l'état ADR ;
3. borner par le DR **courant** et réadmettre — refonte de la file.

Aucune de ces voies n'est une correction de table : ce sont des **changements de conception**.

### 12.7 Découverte — un défaut indépendant dans la table des charges AU915

La comparaison interne de deux régions du simulateur révèle une **contradiction** :

| DR | Modulation | US915 · N | AU915 · N | Référence [H] |
|---|---|---|---|---|
| DR8 | **SF12 / 500 kHz** | 53 | **33** | 53 |
| DR9 | **SF11 / 500 kHz** | 129 | **109** | 129 |
| DR10-DR13 | SF10…SF7 / 500 kHz | 222 | 222 | 242 |

DR8 désigne **la même modulation** (SF12/500) dans les deux régions. Deux limites de charge
différentes pour une modulation identique sont **impossibles** : l'une des deux est fausse.
`MaxPayloadOfDatarateDwell0AU915` (LoRaMac-node v4.7.1) donne 53 et 129 — les valeurs
d'US915 **[H]**.

**Cette preuve est interne au dépôt et ne requiert aucun document externe.** Elle établit
que `au915.py:47-48` porte un **second défaut, distinct** du mappage RX1 : ses valeurs DR8
et DR9 sont trop basses de 20 octets.

Deux faits aggravants :

- **AU915 n'a aucun test sur sa table de charges.** `test_eu868.py:32`, `test_kr920.py:56` et
  `test_as923.py:57` vérifient la leur ; `test_au915.py` ne le fait pas. Le défaut est resté
  invisible.
- L'écart systématique de 20 octets sur DR10-DR13 (222 contre 242) est **partagé par US915** :
  le corriger toucherait une autre région, ce que le présent lot **exclut**.

---

### 12.10 Sémantique M / N et valeurs de référence

#### 12.10.1 `max_payload_by_dr` représente bien **N**, pas M

| Vérification | Emplacement | Conclusion |
|---|---|---|
| Docstring de l'accesseur | `plan.py:126` — « **N** : charge applicative maximale **sans FOpts** pour le débit DR » | **N** |
| Relation documentée | `au915.py:15` — « Charges **N** […], **M − 8 sans FOpts** » | **N = M − 8** |
| Comparaison à la mise en file | `join_store.py:451` — `len(payload) > plan.queue_payload_max`, `payload` = charge applicative | **N** |
| Comparaison à l'émission | `uplink.py:260` — `len(payload) > max_payload`, `payload = send.payload` | **N** |
| Contrat d'API | `api_contract.py:265` — `max_payload_by_dr = plan.max_frm_payload(dr)` | **N** |

Les deux grandeurs ne sont **jamais** mélangées dans le code : la table stocke N, et N seul
est comparé à des charges applicatives. La relation **M − 8 = N** est vérifiée sur les valeurs
de référence retenues :

```
DR8 : M =  61  →  N =  61 − 8 =  53   ✓
DR9 : M = 137  →  N = 137 − 8 = 129   ✓
```

#### 12.10.2 Valeurs de référence retenues — RP002-1.0.5, table 44

Table « AU915-928 maximum payload size », colonnes **compatibles avec les répéteurs** :

| DR | Modulation | **M** | **N** |
|---|---|---|---|
| DR8 | SF12 / 500 kHz | **61** | **53** |
| DR9 | SF11 / 500 kHz | **137** | **129** |

**Corroborations documentaires [N]** — valeurs identiques dans toutes les publications
consultées :

| Source | Table | DR8 | DR9 |
|---|---|---|---|
| *LoRaWAN Regional Parameters* v1.0 (2016) | Table 31 | 61 / 53 | 137 / 129 |
| *LoRaWAN Regional Parameters* v1.0.2 (2017) | Table 37 | 61 / 53 | 137 / 129 |
| *LoRaWAN Regional Parameters* v1.1rB (2017) | Tables 38-39 | 61 / 53 | 137 / 129 |
| RP002-1.0.3 (2021), sommaire | Table 45 « repeater compatible » | *(table présente)* | |
| The Things Network, paramètres régionaux | — | 61 / 53 | 137 / 129 |
| Actility, bande US902-928 | — | 61 / 53 | 137 / 129 |
| ST, brochure citant RP002-1.0.3 | Tableaux 1-2 | 61 / 53 | 137 / 129 |

> **L1 s'applique aussi ici.** La **table 44 de RP002-1.0.5** n'a **pas** été lue directement :
> elle relève de la même plage de pages que §3.8.7 (§5.2). Les valeurs sont retenues sur la
> foi (i) de la décision de référence, (ii) de leur **stabilité sur neuf ans** de publications,
> (iii) de la concordance avec LoRaMac-node **[H]** et avec la table d'US915 **[interne]**.

#### 12.10.3 Origine probable du défaut — une variante d'implémentation tierce

Un indice concordant : le paquet Go `github.com/edwindvinas/ttn/core/band/au915_928`
(The Things Network) déclare, pour les **six DR descendants** :

```go
{M:  41, N:  33},   // DR8
{M: 117, N: 109},   // DR9
{M: 230, N: 222},   // DR10
{M: 230, N: 222},   // DR11
{M: 230, N: 222},   // DR12
{M: 230, N: 222},   // DR13
```

Soit **exactement** les valeurs présentes dans `au915.py:47-48`, et un écart **constant de
20 octets** sur M comme sur N vis-à-vis de la spécification :

| DR | Spécification M / N | Dépôt M / N | Écart |
|---|---|---|---|
| DR8 | 61 / 53 | 41 / 33 | −20 |
| DR9 | 137 / 129 | 117 / 109 | −20 |
| DR10-DR13 | 250 / 242 | 230 / 222 | −20 |

La concordance porte sur les six DR descendants, ce qui en fait un indice solide — mais la
**filiation causale reste une hypothèse [D]** : elle n'est pas démontrée.

---

## 13. Options A, B, C et D

| | **A** — accepter 33 | **B** — corriger la table des charges | **C** — limite par DR | **D** — 33 + lot distinct |
|---|---|---|---|---|
| **Contenu** | corriger `rx1_dr`, borne → 33 | corriger `rx1_dr` **et** `max_frm_payload` DR8/DR9 (33→53, 109→129), borne → 53 | remplacer la borne globale par une validation au DR réel | corriger `rx1_dr`, documenter 33, ouvrir un lot |
| **Borne résultante** | **33** | **53** | 33 à 222 selon le DR | **33** |
| **Fichiers touchés** | `au915.py`, 3 tests | `au915.py`, 3 tests, +1 test à créer | `plan.py`, `join_store.py`, `uplink.py`, `trace_events.py`, schémas, tests | `au915.py`, 3 tests, doc |
| **Avantages** | cohérent avec l'invariant de `plan.py:56` ; coût minimal | corrige un défaut **démontré** ; borne comparable à celle d'EU868 (51) ; aligne AU915 sur US915 et la référence | fidélité physique maximale ; supprime la borne artificielle | séparation stricte des sujets |
| **Risques** | **enchâsse une valeur probablement fausse** comme borne globale ; borne la plus stricte du simulateur ; zéro place après un Join-Accept | modifie `max_payload_by_dr`, **champ du contrat d'API public** ; sort du périmètre strict d'I6-b1 | **changement de conception** du contrat de file ; trois variantes non tranchées ; aucun effet sur le chemin trace sans implémentation distincte | **livre une régression fonctionnelle** (222→33) contraire à la demande expresse |
| **Coût technique** | très faible | faible | **élevé** | très faible |
| **Vérification normative requise** | non | oui, sur la table des charges (distincte de L1) | non | non |

**Sur le contrat d'API (option B).** `RegionInfo.max_payload_by_dr` est exposé par
`region_info()`. Le schéma `schemas/api/v1/region_list.schema.json` n'impose que
`"type": "integer"` : **aucune valeur n'est figée**. `test_api_contract.py:73` n'assert que
la non-vacuité du champ. L'option B ne rompt donc ni le schéma ni ce test.

---

## 14. Recommandation

### 14.1 La distinction demandée

| | Correction normative du mappage | Politique de limitation des charges |
|---|---|---|
| **Objet** | `au915.py:45` — quel DR pour RX1 | `queue_payload_max` — quelle taille admettre en file |
| **Nature** | conformité à RP002 | choix de modélisation |
| **Preuve** | [N] RP002-1.0.5 Table 4, corroboré | aucun texte normatif ne la régit |
| **Négociable** | **non** | oui |
| **Lot** | **I6-b1** | hors I6-b1 |

Ces deux sujets sont **indépendants**. Le second n'est apparu que parce que la formule de
`plan.py:57` **dérive la politique du mappage** : c'est ce couplage, et non la correction,
qui crée la difficulté.

### 14.2 Recommandation : option **B** — **VALIDÉE PAR DÉCISION**

> **Décision du 2026-11-05.** « Je valide l'option B pour le traitement de
> `queue_payload_max`. La correction du mapping AU915 et celle des limites de charge utile
> doivent être traitées **ensemble** dans I6-b1, car le mapping RX1 corrigé rend atteignables
> les DR8 à DR13 et révèle une incohérence indépendante dans les limites de charge utile
> AU915. » Valeurs de référence retenues : RP002-1.0.5 table 44.

1. **Temps 1 — I6-b1.** Corriger `au915.py:45` (mappage). Corriger **aussi** `au915.py:47-48`
   (DR8 33→53, DR9 109→129). Justification : ce n'est pas une politique, c'est la correction
   d'un **second défaut démontré par contradiction interne** (§12.7), qui porte les valeurs
   d'AU915 à celles qu'US915 utilise déjà pour la même modulation. La borne devient **53**,
   voisine des 51 déjà en vigueur dans cinq régions.
2. **Temps 2 — lot distinct.** Traiter la politique de limitation (option C) et l'écart
   résiduel de 20 octets sur DR10-DR13, qui touche **aussi US915** et sort donc du périmètre.

### 14.3 Options écartées

| Option | Verdict | Motif |
|---|---|---|
| **A** | **rejetée** | enchâsse 33, valeur démontrée fausse, comme borne globale |
| **C** | **différée** | changement de conception du contrat de file, sans lien avec une correction de table ; à instruire dans un lot dédié avec les trois variantes du §12.6 |
| **D** | **rejetée** | livre une régression de 222 à 33, contrairement à la demande explicite |

### 14.4 Tests requis par solution

| Solution | Tests à reprendre | Tests à créer |
|---|---|---|
| **A / D** | `test_au915.py:52` (222→33), `:64` (datr), `:67-69` (file 222→33) | aucun |
| **B** | `test_au915.py:52` (222→53), `:64` (datr), `:67-69` (222→53) | **1.** table des charges AU915 complète, sur le modèle de `test_eu868.py:32` ; **2.** cohérence inter-régions : même modulation ⇒ même N, pour les DR descendants partagés ; **3.** non-régression de `max_payload_by_dr` pour les six autres régions |
| **C** | tous les tests de file | validation par DR sur le chemin A **et** le chemin B ; refus à l'émission ; interaction avec l'ADR |
| **Toutes** | — | non-régression des six autres régions (bornes 51/51/51/51/51/222 **inchangées**) |

**Garde-fou.** Les bornes des six autres régions doivent rester **strictement identiques**.
Toute solution qui les modifie est écartée.

---

## 15. Annexe — reproduction de l'audit `d1_i6b1_compare.py`

*Ce script n'est **pas** versionné dans le dépôt, conformément à la demande. Sa méthode est
consignée ici pour que l'audit soit reproductible ; son intégration fera l'objet d'une
décision séparée.*

### 15.1 Objet

Comparer, pour chaque région et chaque DR montant, le DR de la fenêtre RX1 produit par le
simulateur avec la table de référence LoRaMac-node (tag `v4.7.1`), **à offset 0**.

### 15.2 Méthode

1. Charger chaque plan via `lsim.plan.get_plan(nom)`.
2. Pour chaque DR montant du plan, appeler `plan.rx1(dr, 0)` → `(fréquence, datr)`, puis
   `plan.dr_of_downlink_datr(datr)` → DR simulé.
3. Lire la référence :
   - `RegionAU915.h` / `RegionUS915.h` : extraction de
     `DatarateOffsets<Region>[N][M]`, **colonne 0** (offset 0) ;
   - autres régions : **règle algorithmique** — pas de table, l'identité est la règle
     documentée dans `RegionXXX.c` (`DR descendant = DR montant` à offset 0).
4. Comparer, et pour chaque divergence calculer le rapport des durées d'émission.

### 15.3 Paramètres de mesure

| Paramètre | Valeur |
|---|---|
| Durée d'émission | **`lsim.lora.time_on_air_ns`** — la fonction du projet, pas une formule externe |
| Configuration radio | `RadioConfig(sf, bandwidth_hz, coding_rate=1, crc_on=False, explicit_header=True)` |
| Longueur de trame | **13 octets** (`13 + charge utile` nulle) |
| Justification | ni CRC ni en-tête implicite n'interviennent dans une fenêtre RX1 |

### 15.4 Conditions de reproduction

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DLSIM_WARNINGS_AS_ERRORS=ON
cmake --build build --parallel
pip install "./python[test]"

PYTHONPATH=python LSIM_LIBRARY=<chemin>/liblsim_core.so \
    python d1_i6b1_compare.py
```

`LSIM_LIBRARY` est **obligatoire** : sans lui, `lsim._native` lève `OSError` et la suite
échoue en collecte. Références : archive `LoRaMac-node` au tag `v4.7.1`, fichiers
`src/mac/region/Region*.h` et `Region*.c` (CRLF).

### 15.5 Résultat de référence

| Indicateur | Valeur |
|---|---|
| Cases comparées | **45** (AU915 7, US915 5, EU868 7, AS923 7, IN865 6, KR920 6, RU864 7) |
| Divergences | **7** |
| Régions concernées | **AU915 uniquement** |
| Rapports d'occupation | 0,29× · 0,29× · 0,29× · 0,29× · 0,50× · **7,01×** · **3,50×** |
| Conclusion | écart **non monotone** ⇒ aucun facteur correctif global |

---

## 16. Résumé des décisions en attente

| # | Objet | Statut |
|---|---|---|
| **A1** | Arbitrage de la borne de file AU915 (audit §12, options §13, recommandation §14) | **OPTION B VALIDÉE** — mapping et limites traités ensemble dans I6-b1 |
| **A2** | Autorisation d'implémenter I6-b1 (plan §18) | **en attente — NON DONNÉE** |
| **A3** | Lot distinct pour la normalisation des versions RP002 (§5.4) | à programmer |
| **A4** | Lot distinct pour la politique de limitation par DR (option C, §12.6) | à programmer |
| **A5** | Lot distinct pour l'écart de 20 octets sur DR10-DR13 — **touche aussi US915** (§12.7) | à programmer |
| **A6** | Levée de L1 — accès direct au PDF RP002-1.0.5 | bloqué sur l'accès réseau |
| **A7** | Décision d'intégrer ou non `d1_i6b1_compare.py` au dépôt (§15) | à décider séparément |
| **A8** | Lacune préexistante : le chemin trace ne valide pas la charge par DR (§12.4) | signalée, non traitée |

---

## 17. État des lieux de l'environnement

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

---

## 19. Constat d'implémentation — échec D3.15 documenté

*I6-b1 a été implémenté dans les deux fichiers autorisés. La suite n'est **pas** entièrement
verte, et cette section documente l'échec au lieu de le masquer.*

### 19.1 Résultat

| Suite | Résultat |
|---|---|
| Tests AU915 | **43 passés** (27 initiaux + 16 nouveaux) |
| Témoins US915 + LR-FHSS | **15 passés** — US915 strictement inchangé |
| Bornes régionales | **7/7 conformes** (AU915 = 53, six autres inchangées) |
| Audit `d1_i6b1_compare.py` | **45 cas, 0 divergence** |
| Suite Python complète | **2302 passés, 1 échoué, 1 ignoré** |
| Suite C++ | **1/1 passé** |

### 19.2 Le test en défaut

`test_d315_global.py::test_chaque_region_exerce_le_repli`

```
AssertionError: AU915 : la scène de référence ne déclenche aucune descente RX2
                (rx1=562, aucune=0, jobs=562)
```

Ce test est un **gardien** : il garantit que les scènes de référence déclenchent réellement
le repli, « sinon tout le reste est vide ». **Il n'est ni supprimé ni affaibli.**

### 19.3 Cause racine — le défaut créait un goulet artificiel

La scène AU915 utilise `SF_SATURANT["AU915"] = 7`. Le mapping défectueux dirigeait ce montant
rapide vers un descendant **lent** ; le mapping corrigé le dirige vers **DR13 (SF7/500)**, le
descendant le plus rapide.

| Mapping | Débit RX1 (montant SF7) | rx1 | rx2 | **aucune** |
|---|---|---|---|---|
| Avant (défaut) | SF10/500 | 122 | 85 | **355** |
| Après (corrigé) | **SF7/500** | **562** | 0 | **0** |

**Le défaut perdait 355 descentes sur 562** et provoquait 85 replis. Une fois corrigé,
**toutes les descentes aboutissent en RX1**. Il ne s'agit donc pas d'une régression
introduite par I6-b1, mais de la **disparition d'un artefact** : les mesures D3.15 d'AU915
quantifiaient un phénomène largement créé par le défaut.

### 19.4 Ce qui reste démontré, ce qui doit être réévalué

| Test D3.15 | Portée | Effet d'I6-b1 sur AU915 |
|---|---|---|
| `test_les_parametres_rx2_du_profil_atteignent_le_coeur` | `REGIONS_COUVERTES` | **non affecté** — RX2 (DR8) est inchangé |
| `test_parite_et_repli_effectif_par_region` | `REGIONS_EXIGEES` | **hors de portée** — AU915 n'y figure pas |
| `test_le_repli_ajoute_de_lantenne_et_nen_retire_jamais` | `REGIONS_COUVERTES` | **vacant par égalité** — `occupation(avec) == occupation(sans)` quand `rx2 = 0` |
| `test_quand_la_fenetre_de_repli_est_plus_rapide...` | `REGIONS_COUVERTES` | **auto-sauté** — `if rx2 == 0: continue`, mesure seulement à 240 o |
| `test_le_sf12_nest_juge_ni_favorable_ni_defavorable` | `REGIONS_COUVERTES`, 240 o | **contribue encore**, mais sur des trames invalides (§19.5) |
| `test_chaque_region_exerce_le_repli` | gardien | **ÉCHOUE** — détecte la vacuité |

**Reste démontré pour AU915** : le repli n'ajoute jamais d'antenne sans la retirer
(vérifié par égalité, non par excédent) ; les paramètres RX2 atteignent le cœur.

**Doit être réévalué pour AU915** : le coût et le bénéfice du repli, la loi de seuil sur
R = airtime(RX2)/airtime(RX1), et toute conclusion tirée des scènes de saturation.

### 19.5 Lacune préexistante — la charge de 240 octets est physiquement impossible

Matrice AU915 après correction :

| SF montant | 60 o | 120 o | **240 o** |
|---|---|---|---|
| 7 | rx2 = 0 | rx2 = 0 | rx2 = 56 |
| 9 | rx2 = 0 | rx2 = 0 | rx2 = 50 |
| 11 | rx2 = 0 | rx2 = 0 | rx2 = 2 |
| 12 | rx2 = 0 | rx2 = 0 | rx2 = 11 |

Les **119** replis restants proviennent **tous** de la charge 240. Or :

| Région | N maximal | charge 240 valide ? |
|---|---|---|
| **les sept régions** | **222** | **NON** |

La borne de 242 du chemin trace (`trace_events.py:501`) est **codée en dur et invariante par
région** ; elle ne valide pas la charge contre le DR réellement utilisé. Une trame de 240
octets y est donc acceptée alors qu'aucune région ne la supporte.

**Conséquence.** Après correction, **il ne reste aucune base probante valide pour AU915 dans
D3.15** : les seuls cas produisant un repli reposent sur des trames physiquement impossibles.
Cette lacune est **antérieure à I6-b1** et **commune aux sept régions** — elle n'est donc pas
imputable à la correction, qui se contente de la rendre visible pour AU915.

C'est ce qui fonde la décision de ne **pas** forcer la charge à 240 pour obtenir une suite
verte : on validerait une mesure au moyen de trames qu'aucune région ne peut émettre.

---

## 20. Proposition — lot distinct D3.15-AU915

*Proposition soumise. **Ce lot n'est pas commencé** et ne le sera pas sans autorisation
explicite. Il ne relève pas d'I6-b1.*

### 20.1 Scène radio conforme aux limites de charge par DR

Contrainte structurante : le DR montant détermine le DR de RX1, donc **N**. Pour AU915 après
correction :

| Montant | RX1 | **N** | Charge admissible |
|---|---|---|---|
| DR0 (SF12/125) | DR8 · SF12/500 | **53** | ≤ 53 |
| DR1 (SF11/125) | DR9 · SF11/500 | **129** | ≤ 129 |
| DR2-DR6 | DR10-DR13 | **222** | ≤ 222 |

La scène proposée : **un SF unique par scène, une charge ≤ N du DR de RX1 correspondant.**
Trois scènes, une par palier (53, 129, 222 octets), plutôt qu'une charge unique appliquée
uniformément. Toute trame dépassant N doit être **refusée par la scène**, pas émise.

Prérequis : combler la lacune de validation par DR sur le chemin trace (§12.4), sans quoi
la contrainte ci-dessus ne peut pas être appliquée.

### 20.2 Justification du mécanisme de saturation

La passerelle est **un émetteur unique**. Sous la règle `EXACTE` (U0.3 / A6), une descente
part **exactement** à l'ouverture de sa fenêtre : si l'émetteur est occupé à cet instant, le
placement échoue. La saturation n'est donc pas une question de collision radio mais de
**capacité série de l'émetteur** :

```
saturation  ⟺  Σ durées d'émission demandées  >  temps disponible
```

Le mapping corrigé **accélère** les descentes AU915 (SF7/500 au lieu de SF10/500, soit ~3,4×
moins de temps d'antenne). La scène historique, calibrée sur le défaut, ne sature plus : il
faut **augmenter le nombre de terminaux ou le débit d'émission**, et non ralentir les trames.

Deux leviers, à chiffrer lors du lot :

| Levier | Effet | À mesurer |
|---|---|---|
| Nombre de terminaux / messages | augmente la demande sérielle | seuil de saturation |
| Taille de trame (dans la limite de N) | allonge chaque descente | sensibilité du seuil |

### 20.3 Critères de déclenchement

| Issue | Condition | Compteur |
|---|---|---|
| **RX1** | placement exact à l'ouverture de RX1 réussi | `fenetres.count("rx1")` |
| **RX2** | placement RX1 échoué **et** `rx2_disponible` **et** placement RX2 réussi | `fenetres.count("rx2")` |
| **aucune** | RX1 échoué et (pas de RX2 disponible ou placement RX2 échoué) | `fenetres.count(None)` |

À relever pour chaque configuration : `rx1`, `rx2`, `aucune`, `livrees`, `occupation`,
et R = `rx2_airtime_ns / airtime_ns`.

### 20.4 Réévaluation à conduire

| Mesure | Statut | Action |
|---|---|---|
| Coût du repli (Δ occupation) | mesuré sur trames invalides à 240 o | **à refaire** |
| Bénéfice du repli (Δ livrées) | idem | **à refaire** |
| Loi de seuil sur R | établie sur l'ancien mapping | **à refaire** |
| Classement favorable / défavorable | contributions AU915 non valides | **à refaire** |
| `SF_SATURANT["AU915"]` | calibré sur le défaut | **à recalibrer** |

**Ce lot touche `test_d315_global.py` et, pour la validation par DR, `trace_events.py`.** Aucun
de ces deux fichiers n'entre dans le périmètre autorisé d'I6-b1 : le lot est donc distinct et
soumis à autorisation séparée.

---

---

## 21. Analyse du chemin `downlink_payload_bytes`

*Analyse demandée, **en lecture seule**. Aucun code n'a été modifié pour la produire. Elle ne
relève pas d'I6-b1 : la lacune qu'elle décrit est **transversale** et **antérieure** à la
correction AU915.*

### 21.1 Comment le DR descendant réellement utilisé est déterminé

```
device_radios(scenario)
      ↓
_radio(plan, freq_hz, sf, tx_power)                    trace_events.py:254
      ↓  dr = DR dont (SF, BW=125) correspond au SF du dispositif
      ↓  rx1_mhz, rx1_datr = plan.rx1(dr, ch)          trace_events.py:263
      ↓  rx1_sf, rx1_bw_hz = extrait de rx1_datr       trace_events.py:267
      ↓  rx2_* = plan.rx2()                            trace_events.py:275-280
DeviceRadio(rx1_sf, rx1_bw_hz, rx2_sf, rx2_bw_hz, dr)  trace_events.py:283
      ↓
downlink_phy(radio, window)                            trace_events.py:335
      ↓  window == "rx2"  → (rx2_hz, rx2_sf, rx2_bw_hz or rx1_bw_hz)
      ↓  sinon            → (rx1_hz, rx1_sf,  rx1_bw_hz)
```

**Le DR est donc connu à deux endroits** : à la création du `DeviceRadio` (via le plan), et au
moment du choix de la fenêtre (RX1 ou RX2), **lequel n'est arrêté qu'à la planification**.

### 21.2 Comment la limite N régionale est accessible

| Besoin | Accès | Visibilité |
|---|---|---|
| N pour un DR | `Plan.max_frm_payload(dr)` — `plan.py:125` | **publique** |
| DR de RX1 depuis le DR montant | `plan._rx1_dr[dr_up]` | privée |
| DR depuis (SF, bande) | `plan.dr_of_downlink_datr(f"SF{sf}BW{bw//1000}")` | **publique** — marche aussi pour RX2 |
| DR de RX2 | `plan.dl_settings & 0x0F` | publique |

**Aucun obstacle d'accès** : les briques existent toutes. La limite est simplement **non
consultée** par le chemin trace.

### 21.3 Faut-il valider à la création, à la planification, ou aux deux ?

**Aux deux — et c'est la conclusion structurante.** Motif : le repli **change le DR**, donc
**change N**.

| Fenêtre | N pour une même descente (AU915) |
|---|---|
| RX1 (montant DR5 → DR13) | **222** |
| RX2 (DR8 par défaut) | **53** |

Mesure sur les sept régions :

| Région | RX2 | N(RX2) | N(RX1) min | N(RX1) max | dégradation par le repli |
|---|---|---|---|---|---|
| EU868 | DR0 | 51 | 51 | 222 | **OUI** |
| US915 | DR8 | 53 | 222 | 222 | **OUI** |
| AS923 | DR2 | 51 | 51 | 222 | **OUI** |
| AU915 | DR8 | 53 | 53 | 222 | **OUI** |
| IN865 | DR2 | 51 | 51 | 222 | **OUI** |
| KR920 | DR0 | 51 | 51 | 222 | **OUI** |
| RU864 | DR0 | 51 | 51 | 222 | **OUI** |

Une trame de **200 octets** est valide en RX1 (N = 222) et **invalide en RX2** (N = 51 ou 53),
**dans les sept régions**. Le repli peut donc rendre une trame physiquement inémettable *après*
qu'elle a été admise.

Conséquence : une validation **uniquement à la création** laisserait passer des trames
inémettables en RX2 ; une validation **uniquement à la planification** produirait des
chronologies incohérentes (jobs sans fenêtre). **Les deux points sont nécessaires.**

### 21.4 Trames MAC et trames applicatives — ne pas confondre les tailles

Tailles calculées dans `_downlink_jobs` (`base`), puis `airtime = base + len(fopts)` :

| Type | `base` | Nature | Soumis à N ? |
|---|---|---|---|
| `join_accept` | `JOIN_ACCEPT_BYTES` = **17** (33 avec CFList) | **PHYPayload complet** | **non** — chemin propre |
| `downlink` (données) | `DATA_FRAME_OVERHEAD_BYTES + downlink_payload_bytes` = **13 + charge** | MACPayload + en-tête | **oui**, sur la charge |
| `ack` | `ACK_FRAME_BYTES` = **12** | trame MAC | **non** |
| `mac_answer` | `ACK_FRAME_BYTES` = **12** | trame MAC | **non** |
| `downlink` (MAC seul) | `ACK_FRAME_BYTES` = **12** | trame MAC | **non** |

Relation exacte : `fil = 13 + N + |FOpts|`, car
`13 = MHDR(1) + FHDR(7) + FPort(1) + MIC(4)`.

**La contrainte à appliquer est donc `charge + |FOpts| ≤ N`**, et non `charge ≤ N` — les FOpts
consomment la même enveloppe. Elle ne s'applique **qu'aux trames applicatives**, jamais aux
trames MAC ni au Join-Accept.

### 21.5 Chemins pouvant contourner la validation

| # | Chemin | Limite appliquée | Région-aware ? |
|---|---|---|---|
| 1 | File : `join_store.enqueue_downlink` | `queue_payload_max` (min sur RX1) | **oui** (statique, pire cas) |
| 2 | Trace : `trace_events._downlink_jobs` | **242**, codé en dur (`trace_events.py:501`) | **non** |
| 3 | Cœur C++ : `downlink_plan.cpp` | **`kMaxDownlinkPayloadBytes` = 242** (l. 26, validé l. 150 et 435) | **non** |
| 4 | Join-Accept : `join.py` | aucune (taille fixe) | sans objet |
| 5 | Mesh : `trace_events.py:1264` | `MAX_MESH_DOWNLINK_PAYLOAD_BYTES` = **227** | **non** |
| 6 | `engine.cpp:58` | `payload_bytes > 255` | **non** |

Consommateurs de `options.downlink_payload_bytes` : `trace_events.py`, `downlink_plan.py`
(l. 292, 418), `closed_loop.py:325`, `closed_loop_v3.py:374`, `mac_loop.py:82`,
`multi_trace.py:65`. **Tous partagent la même borne 242.**

> **Parité à préserver.** `test_downlink_plan_parity.py` vérifie la parité entre le chemin
> Python et le cœur. Toute modification de la borne doit être appliquée **des deux côtés**,
> sous peine de rompre cette parité.

### 21.6 Conséquences d'une validation stricte sur les scénarios existants

La validité dépend du **DR réellement utilisé**, donc du SF de la scène. Exemple, charge
200 octets :

| Région | SF7 | SF9 | SF10 | SF11 | SF12 |
|---|---|---|---|---|---|
| EU868 | **valide** (222) | invalide (115) | invalide (51) | invalide (51) | invalide (51) |
| AU915 | **valide** (222) | **valide** (222) | **valide** (222) | invalide (129) | invalide (53) |

Inventaire des usages :

| Usage | Charge | Région / SF | Validité | Effet d'une validation stricte |
|---|---|---|---|---|
| `test_d315_causal_envelope.py:287, 351` | 200 | EU868 **SF7** | **valide** (N = 222) | **aucun** |
| `test_d315_global.py` (plusieurs) | **240** | 7 régions | **invalide partout** | cas concernés deviennent inémettables |
| `test_mesh_trace.py:223` | 227 | mesh | **invalide** si N < 227 | à instruire |
| `test_downlink_plan_parity.py:92` | 243 | test négatif | attendu refus | **aucun** (refus toujours levé) |
| `test_trace_events.py:333, 337` | 243, 300 | tests négatifs | attendu refus | **aucun** |
| `test_study_simulate.py:251` | 240 | **uplink**, test négatif | hors périmètre | **aucun** |
| Valeur par défaut | **10** | toutes | **valide partout** (N min = 51) | **aucun** |

**N minimal sur l'ensemble des régions et des DR descendants : 51.** La valeur par défaut
(10 octets) reste donc valide partout, et la borne actuelle de 242 ne l'est nulle part.

### 21.7 Matrice des sept régions — DR descendants et limites N

| Région | DR descendants | N par DR | RX2 | N(RX2) |
|---|---|---|---|---|
| **EU868** | 0-6 (identité) | 51, 51, 51, 115, 222, 222, 222 | DR0 | 51 |
| **US915** | 8-13 | 53, 129, 222, 222, 222, 222 | DR8 | 53 |
| **AS923** | 0-6 (identité) | 51, 51, 51, 115, 222, 222, 222 | DR2 | 51 |
| **AU915** | 8-13 | 53, 129, 222, 222, 222, 222 | DR8 | 53 |
| **IN865** | 0-5 (identité) | 51, 51, 51, 115, 222, 222 | DR2 | 51 |
| **KR920** | 0-5 (identité) | 51, 51, 51, 115, 222, 222 | DR0 | 51 |
| **RU864** | 0-6 (identité) | 51, 51, 51, 115, 222, 222, 222 | DR0 | 51 |

Rappel de grandeur : **N = M − 8**, charge applicative maximale **sans FOpts** ; le fil vaut
`13 + N + |FOpts|`.

### 21.8 Tests de conformité proposés

*À valider avant toute implémentation. Proposition, non réalisée.*

| # | Test | Objet |
|---|---|---|
| **T-P1** | `test_n_disponible_pour_chaque_dr` | pour les 7 régions et chaque DR descendant, `max_frm_payload(dr)` est défini et > 0 |
| **T-P2** | `test_relation_m_moins_8_egale_n` | la relation est documentée et vérifiée sur les valeurs de référence |
| **T-P3** | `test_meme_modulation_meme_n` | deux régions partageant une modulation descendante ont le même N (généralise T-B1-12) |
| **T-P4** | `test_charge_superieure_a_n_est_refusee_a_la_creation` | `charge + |FOpts| > N(dr)` ⇒ refus à la création du job, pour chaque région |
| **T-P5** | `test_le_repli_ne_peut_pas_emettre_une_trame_trop_grande` | une trame valide en RX1 mais trop grande pour RX2 **n'est pas émise** en RX2 |
| **T-P6** | `test_trames_mac_non_soumises_a_n` | `ack`, `mac_answer` et `join_accept` ne sont **pas** rejetés par la contrainte applicative |
| **T-P7** | `test_fopts_consomment_l_enveloppe` | une charge à N − 1 avec 2 octets de FOpts est refusée |
| **T-P8** | `test_parite_python_cpp_de_la_nouvelle_borne` | même comportement des deux côtés (`test_downlink_plan_parity.py`) |
| **T-P9** | `test_scenarios_historiques_inchangés` | la valeur par défaut (10 o) et les scènes valides ne changent pas |
| **T-P10** | `test_inventaire_des_scenarios_invalides` | recense les scènes existantes dont la charge excède N, sans les modifier |

---

---

## 22. Proposition finale — validation transverse des charges descendantes

*Proposition soumise à décision. **Aucun code, test, fixture ou scénario n'a été modifié** pour
la produire.*

### 22.1 Question 1 — trame valide en RX1, trop grande pour RX2

**Principe retenu : échec explicite et traçable — sans troncature, sans décalage temporel,
sans émission hors fenêtre.**

Séquence, dans `apres(k, rx2=False)` de `_schedule_gateway` :

```
1. le placement RX1 échoue                     (émetteur occupé)
2. le repli est candidat : repli_actif ET rx2_disponible
3. NOUVEAU : contrôle de taille sur la fenêtre RX2
       taille_trame ≤ N(dr_rx2) ?
   ├─ oui → dépôt de la demande RX2 (comportement actuel, inchangé)
   └─ non → AUCUN dépôt
4. fenetres[k] = None, avec motif RX2_CAPACITY
```

Propriétés garanties :

| Propriété | Comment |
|---|---|
| Pas de troncature | la trame n'est jamais raccourcie ; elle n'est pas émise |
| Pas de décalage temporel | aucun dépôt ⇒ aucune réservation d'émetteur ; `occupation` inchangée |
| Pas d'émission hors fenêtre | la règle `EXACTE` (U0.3/A6) est intacte |
| Traçable | `fenetres[k] = None` **avec motif**, distinct du simple échec de placement |

**Le compteur `aucune` est conservé** : ce cas en est un **raffinement**, pas une substitution.
Le contrat de sortie existant reste donc compatible.

### 22.2 Question 2 — distinguer les trois familles d'erreurs

Taxonomie proposée, fondée sur le **type de trame** puis sur la **comparaison** :

| Motif | Condition | Trames concernées |
|---|---|---|
| `PAYLOAD_TOO_LARGE` | `charge > N` | descentes applicatives |
| `FOPTS_OVERFLOW` | `charge ≤ N` mais `charge + \|FOpts\| > N` | descentes applicatives avec FOpts |
| `RX2_CAPACITY` | valide en RX1, `taille > N(dr_rx2)` | descentes applicatives, au repli |
| *(aucun)* | — | `ack`, `mac_answer`, `join_accept` — **jamais soumises à N** |

Algorithme de classement :

```
si kind ∈ {ack, mac_answer, join_accept}  → aucun contrôle N
sinon (descente applicative) :
    si charge > N                    → PAYLOAD_TOO_LARGE
    sinon si charge + |FOpts| > N    → FOPTS_OVERFLOW
    sinon                            → conforme
    au repli, si taille > N(rx2)     → RX2_CAPACITY
```

La distinction « la charge seule passe mais les FOpts débordent » est **observable** et donc
testable : une charge à `N` avec un octet de FOpts doit lever `FOPTS_OVERFLOW`.

Rappel de la relation : `fil = 13 + N + |FOpts|`, car
`13 = MHDR(1) + FHDR(7) + FPort(1) + MIC(4)`.

### 22.3 Question 3 — ne pas rendre impossible une décision du planificateur

**Règle : valider à la création sur la fenêtre la moins contraignante (RX1), et différer le
contrôle RX2 à la planification.**

| Point | Contôle | Justification |
|---|---|---|
| Création | `taille ≤ N(dr_rx1)` uniquement | valider contre RX2 à la création rejetterait des trames qui auraient abouti en RX1 — **faux rejet** |
| Planification | `taille ≤ N(dr_rx2)` **au moment du repli** | c'est le seul instant où le repli est effectivement décidé |

**L'espace de décision du planificateur n'est jamais réduit** : tout job émettable en RX1 le
reste. Seul le **repli** devient conditionnel, ce qui est conforme à sa nature de secours.

Deux garanties complémentaires :

1. **Le contrôle de création est pur** — il ne modifie aucun état, ne consomme aucune
   occupation, n'altère aucune chronologie. Il ne peut donc pas influencer la planification.
2. **La taille est connue aux deux instants** : le job porte déjà `airtime_ns` et
   `rx2_airtime_ns`, calculés depuis `base + len(fopts)`. Aucun champ nouveau n'est strictement
   nécessaire au contrôle ; seule l'exposition d'un **motif** l'est.

### 22.4 Question 4 — événements, compteurs et motifs exposés

| Ajout | Nature | Compatibilité |
|---|---|---|
| `fenetres[k] = None` + motif | **existant**, raffiné | compatible : `count(None)` inchangé |
| Liste parallèle des motifs | **nouvelle**, optionnelle | additive |
| Compteur `refusees_taille` | **nouveau** | additive |
| Compteur `non_emis_rx2_taille` | **nouveau** | additive |
| Motif dans l'événement de descente | **nouveau** | additive |

**Aucun compteur existant n'est supprimé ni redéfini.** Un consommateur qui ignore les
nouveaux champs observe exactement le comportement antérieur, à ceci près que certaines
trames auparavant émises en RX2 ne le sont plus — ce qui est **l'objet** de la correction.

### 22.5 Question 5 — préserver les contrats Python et C ABI

| Contrat | État actuel | Proposition |
|---|---|---|
| `ProtocolOptions.downlink_payload_bytes` | `Field(10, ge=0, le=242)` | **inchangé** — la borne 242 reste le plafond absolu |
| Validation régionale | absente | **ajoutée**, erreur **distincte** et plus spécifique |
| `kMaxDownlinkPayloadBytes` (C) | 242 (`downlink_plan.cpp:26`) | **inchangé** |
| Statut de refus (C) | — | **nouveau code de statut**, ajouté en **fin d'énumération** |
| ABI | versionnée additive | **aucun champ existant modifié** |
| `lsim_plan_device*` | inchangé | inchangé |

Trois précautions :

1. **Ajout, jamais modification** — tout nouveau statut ou champ est ajouté en fin
   d'énumération, jamais inséré.
2. **Erreur distincte** — une `ValueError` régionale ne doit pas être confondue avec le dépassement
   de la borne 242 ; les messages et, idéalement, les types d'exception diffèrent.
3. **Parité** — les deux côtés appliquent les **mêmes** règles ; `test_downlink_plan_parity.py`
   est étendu, non contourné.

**Compatibilité amont** : la valeur par défaut (10 octets) est valide dans les sept régions et
à tous les DR descendants (N minimal = 51). Les scénarios valides ne changent donc pas.

### 22.6 Question 6 — tests de parité, dont RX1 valide / RX2 invalide

**Cas canonique** : AU915, terminal à **SF7** → montant DR5 → RX1 **DR13** (N = 222) ;
RX2 **DR8** (N = 53). Une charge de **120 octets** est valide en RX1, invalide en RX2.

| # | Test | Attendu |
|---|---|---|
| **T-PA1** | scénario saturé, charge 120, repli actif | aucune émission RX2 ; `motif = RX2_CAPACITY` |
| **T-PA2** | occupation avec repli vs sans repli | **égalité** stricte (aucun dépôt ⇒ aucune réservation) |
| **T-PA3** | même scénario, charge 40 (≤ 53) | le repli **fonctionne** — garde-fou contre un refus excessif |
| **T-PA4** | exécution sur le chemin Python **et** le chemin C++ | **résultats identiques au bit près** |
| **T-PA5** | les sept régions × charge à la limite | frontière exacte : `N` accepté, `N+1` refusé |
| **T-PA6** | trames MAC (`ack`, `mac_answer`) | jamais refusées — motifs N non applicables |
| **T-PA7** | Join-Accept | jamais refusé ; temps d'antenne inchangé |

**T-PA3 est le garde-fou essentiel** : il empêche que la nouvelle règle ne supprime le repli
là où il est légitime.

### 22.7 Inventaire des six chemins et points de contrôle

| # | Chemin | Emplacement | Contrôle actuel | **Point de contrôle proposé** |
|---|---|---|---|---|
| **1** | File | `join_store.py:451` | `queue_payload_max` (pire cas, par région) | **conservé tel quel** — politique distincte, non modifiée |
| **2** | Création des jobs | `trace_events.py:540` | borne 242 | **ajouter** `taille ≤ N(dr_rx1)` ; motifs `PAYLOAD_TOO_LARGE` / `FOPTS_OVERFLOW` |
| **3** | Planification | `trace_events.py:656-659` | aucune | **ajouter** `taille ≤ N(dr_rx2)` avant dépôt ; motif `RX2_CAPACITY` |
| **4** | Join-Accept | `join.py:299-313` | aucune | **aucun contrôle N** — chemin propre, taille fixe ; documenter comme tel |
| **5** | Mesh | `trace_events.py:1264` | `MAX_MESH_DOWNLINK_PAYLOAD_BYTES` = 227 | **ajouter** le contrôle N en aval de la borne mesh, sur le DR réel |
| **6** | Cœur C++ | `downlink_plan.cpp:26, 150, 435` | borne 242 | **miroiter** les contrôles 2 et 3 ; parité obligatoire |

Chemins **sans région** (`plan = None`) : aucun contrôle N n'est applicable — il n'existe pas
de N. Ces scénarios sont **hors du périmètre** de la validation régionale ; ils conservent la
borne 242. Sept des neuf fichiers de test utilisant `downlink_payload_bytes` sont dans ce cas.

### 22.8 Matrice de migration des scénarios existants

Charges effectivement employées, avec le DR et le N de la **scène de référence** de chaque
région (`SF_SATURANT`).

**Résolution de la scène de référence :**

| Région | SF | DR | RX1 | **N** | via le plan ? |
|---|---|---|---|---|---|
| EU868 | 11 | 1 | DR1 · SF11/125 | **51** | oui |
| US915 | 11 | — | SF11/125 | **indéterminé** | **non** — aucun DR montant à SF11 |
| AS923 | 7 | 5 | DR5 · SF7/125 | **222** | oui |
| AU915 | 7 | 5 | DR13 · SF7/500 | **222** | oui |
| IN865 | 7 | 5 | DR5 · SF7/125 | **222** | oui |
| KR920 | 9 | 3 | DR3 · SF9/125 | **115** | oui |
| RU864 | 10 | 2 | DR2 · SF10/125 | **51** | oui |

**Matrice charge × région :**

| Charge | EU868 | US915 | AS923 | AU915 | IN865 | KR920 | RU864 |
|---|---|---|---|---|---|---|---|
| **10** | ok | ? | ok | ok | ok | ok | ok |
| **200** | **NON** | ? | ok | ok | ok | **NON** | **NON** |
| **227** | **NON** | ? | **NON** | **NON** | **NON** | **NON** | **NON** |
| **240** | **NON** | ? | **NON** | **NON** | **NON** | **NON** | **NON** |
| **243** | **NON** | ? | **NON** | **NON** | **NON** | **NON** | **NON** |
| **300** | **NON** | ? | **NON** | **NON** | **NON** | **NON** | **NON** |

**Traitement attendu par usage :**

| Usage | Charge | Région | N | Validité | Traitement attendu |
|---|---|---|---|---|---|
| `test_d315_causal_envelope.py:287, 351` | 200 | EU868 **SF7** | 222 | **valide** | **aucun changement** |
| `test_d315_causal_envelope.py:326` | 60 | EU868 **SF7** | 222 | **valide** | **aucun changement** |
| `test_d315_global.py:721, 741` | 20 / 60 / **120** / **240** | 7 régions | 51-222 | **240 invalide partout** ; **120 invalide en EU868, KR920, RU864** | réévaluation D3.15 requise |
| `test_d315_global.py:768-769` | **240** | 7 régions | ≤ 222 | **invalide** | réévaluation D3.15 requise |
| `test_d315_global.py:799` | 120 | 7 régions | 51-222 | invalide en 3 régions | réévaluation D3.15 requise |
| `test_d315_global.py:825-826, 1020` | 60 | EU868 | 51 (SF11) / 222 (SF7) | dépend du SF | à instruire |
| `test_downlink_plan_parity.py:92` | 243 | aucune | — | test **négatif** | **inchangé** (refus déjà levé) |
| `test_downlink_plan_parity.py:100` | 10 | aucune | — | valide | **inchangé** |
| `test_trace_events.py:333` | 243 | aucune | — | test **négatif** | **inchangé** |
| `test_trace_events.py:337` | 300 | aucune | — | test **négatif** pydantic | **inchangé** |
| `test_mesh_trace.py:223` | 227 | aucune | — | borne mesh | **inchangé** (pas de région) |
| `test_mesh_trace.py:226` | 228 | aucune | — | test **négatif** mesh | **inchangé** |
| `test_downlink_plan_v2.py:40` | 40 | aucune | — | hors périmètre | **inchangé** |
| `test_u03:73`, `test_u04:89` | 0 | aucune | — | hors périmètre | **inchangé** |
| `test_u03:255` | 40 | aucune | — | hors périmètre | **inchangé** |
| `test_u04b:44`, `test_u05:75` | 20 | aucune | — | hors périmètre | **inchangé** |
| `b_d315_effet_correctifs.py:67, 113, 118` | 60 | **EU868** | dépend du SF | à vérifier | à instruire |
| `b_d315_charge.py` | 20/60/120/240 | **7 régions** | 51-222 | 240 invalide | à instruire |
| `p_d_i3_1:45` | 40 | **EU868** | dépend du SF | à vérifier | à instruire |
| `p_d_i3_2:41` | 27 | aucune | — | hors périmètre | **inchangé** |

**Lecture.** Sur les **vingt-deux usages** recensés, la majorité est **sans région** (donc hors
périmètre) ou **déjà négative** (donc inchangée). L'exposition réelle se concentre sur
`test_d315_global.py`, `b_d315_charge.py` et trois scripts de preuve.

### 22.9 Deux points à trancher

| # | Point | Options |
|---|---|---|
| **P1** | **US915 à SF11** : aucun DR montant ne correspond ; `_radio` retombe sur SF11/125 kHz en ignorant le mappage régional, et N est **indéterminé** | (a) refuser la scène ; (b) appliquer le DR le plus proche ; (c) laisser sans contrôle N — **à décider** |
| **P2** | **Trois scènes de référence D3.15 déjà invalides** (EU868 SF11 N=51, KR920 SF9 N=115, RU864 SF10 N=51) pour une charge de 120 | la réévaluation D3.15 doit couvrir **les sept régions**, pas seulement AU915 — **confirmation attendue** |

> **P2 confirme rétrospectivement la décision de traiter cette lacune comme transversale** : le
> problème n'était pas propre à AU915, qui n'en était que le révélateur.

---

---

## 23. Plan consolidé — validation transverse des charges descendantes

*Version consolidée intégrant les six décisions validées, la **correction de Q3**, la décision
**P1** et la décision **P2**. Étape **documentaire et analytique** : aucun code, test, fixture ou
scénario n'a été modifié.*

### 23.1 Statut et périmètre

| Décision | Contenu | Intégration |
|---|---|---|
| 1 | RX1 valide / RX2 trop grande ⇒ échec `RX2_CAPACITY`, sans troncature ni émission | §23.3, §23.5 |
| 2 | Séparation applicatif / FOpts / trames MAC | §23.4.2 |
| 3 | Exposition additive des motifs et compteurs | §23.4.4, §23.6.1 |
| 4 | Préservation des contrats Python et ABI C | §23.6 |
| 5 | Parité Python/C++ obligatoire | §23.6.2, §23.7.2 |
| 6 | Réévaluation D3.15 étendue aux sept régions | §23.8 |
| **Q3 corr.** | Validation **par fenêtre candidate**, aucune fenêtre privilégiée | §23.2 |
| **P1** | SF sans DR ⇒ refus de **configuration**, `UNSUPPORTED_UPLINK_DATARATE` | §23.4.1 |
| **P2** | D3.15 couvre les sept régions, chacune avec ses paramètres | §23.8 |

### 23.2 Correction de Q3 — validation par fenêtre candidate

**Le §22.3 est caduc sur un point** : il postulait que RX1 est la fenêtre la moins contraignante
et validait donc contre RX1 en différant le contrôle RX2. Cette présomption est **fausse en
droit** — rien dans RP002 ne garantit `N(RX1) ≥ N(RX2)`, et elle ne tiendrait pas pour un RX2
configuré plus rapide, pour LRFHSS, ou pour une région future. Elle est remplacée par quatre
règles.

> **R-N1 — Validation par fenêtre.** Chaque fenêtre candidate est validée **indépendamment**,
> contre le N de **son propre** DR descendant, au moment où elle devient candidate. Aucune
> fenêtre n'est privilégiée par construction.

> **R-N2 — Aucune réservation d'une fenêtre inéligible.** Une fenêtre qui ne peut porter la trame
> ne fait l'objet d'**aucune demande** auprès de l'arbitre : aucune occupation inscrite, aucun
> temps d'antenne consommé, aucun verdict.

> **R-N3 — Parcours non clôturé.** L'inéligibilité d'une fenêtre **ne termine pas** le parcours.
> Les autres fenêtres restent examinables, **dans l'ordre protocolaire**. C'est la condition pour
> qu'un repli réglementairement autorisé ne soit jamais supprimé par une validation.

> **R-N4 — Aucun effet sur la chronologie.** La validation ne décale aucune ouverture
> (`ready_ns`, `t_open`, `t_open_rx2`), ne consomme aucune occupation et ne modifie aucun
> `starts[k]`. Elle est **pure** et **idempotente**.

**Conséquence — symétrie.** Le cas « RX1 inéligible mais RX2 éligible » doit être traité, même
s'il ne se présente dans aucune des sept régions actuelles : si RX1 ne peut porter la trame, le
réseau n'émet pas en RX1, le terminal ouvre RX2 comme le protocole le prévoit, et RX2 est
examinée. Le miroir du cas de la décision 1.

### 23.3 Machine à états du placement RX1 / RX2

#### 23.3.1 Machine actuelle (mesurée)

Relevée dans `trace_events._schedule_gateway` et `lsim.arbitre` :

```
pour k dans jobs :
    arbitre.demand(fenetre(k, job, rx2=Faux), ensuite=apres(k, Faux))
arbitre.resolve()

apres(k, rx2) → reagir(émission, déposer) :
    émission.emitted      → starts[k], fenetres[k] = « rx2 » si rx2 sinon « rx1 »   [terminal]
    sinon si rx2
         ou non repli_actif
         ou non rx2_disponible                                    → return          [terminal]
    sinon → déposer(fenetre(k, job, rx2=Vrai), ensuite=apres(k, Vrai))              [transition]
```

États : `ATTENTE_RX1` → {`EMIS_RX1`, `ATTENTE_RX2`, `AUCUNE`} · `ATTENTE_RX2` → {`EMIS_RX2`,
`AUCUNE`}.

L'arbitre produit cinq verdicts (`EMITTED`, `LATE`, `WINDOW_MISSED`, `NOT_NEEDED`, `DUTY_CYCLE`) ;
sous la règle `EXACTE` (A6), seuls `EMITTED` et `WINDOW_MISSED` surviennent. **Un
`WINDOW_MISSED` n'inscrit aucune occupation** (`arbitre.py:84` — « inscrite seulement si émise »).

#### 23.3.2 Contrainte découverte — `condition` supprime la réaction

`EmissionRequest.condition` est évaluée **au moment du placement** ; si elle est fausse, le
verdict est `NOT_NEEDED` et **`ensuite` n'est pas appelée** (`arbitre.py:193`).

> **Conséquence de conception :** `condition` **ne doit pas** servir à exprimer l'inéligibilité
> d'une fenêtre. Elle supprimerait la réaction et, avec elle, le repli RX2 — violation directe de
> **R-N3** et de la décision 1.

Le filtrage doit donc intervenir **avant** `arbitre.demand`, dans la construction de la demande.

#### 23.3.3 Machine cible

```
ÉLIGIBILITÉ (calculée une fois, à la construction du job, à partir du plan)
    rx1_eligible = taille_trame ≤ N(dr_rx1)
    rx2_eligible = rx2_disponible et taille_trame ≤ N(dr_rx2)

INITIAL — première fenêtre candidate
    rx1_eligible                                  → ATTENTE_RX1
    sinon, rx2_eligible et repli_actif            → ATTENTE_RX2      (RX1 ni réservée ni émise)
    sinon                                         → AUCUNE(NO_WINDOW_CAPACITY)

ATTENTE_RX1
    EMITTED                                       → EMIS_RX1
    non émise :
        non (repli_actif et rx2_disponible)       → AUCUNE(WINDOW_MISSED)
        non rx2_eligible                          → AUCUNE(RX2_CAPACITY)
        sinon                                     → ATTENTE_RX2

ATTENTE_RX2
    EMITTED                                       → EMIS_RX2
    non émise                                     → AUCUNE(WINDOW_MISSED)
```

#### 23.3.4 Table des transitions

| État | Événement | Suivant | Occupation | Motif |
|---|---|---|---|---|
| initial | `rx1_eligible` | `ATTENTE_RX1` | — | — |
| initial | ¬`rx1_eligible` ∧ `rx2_eligible` ∧ repli | `ATTENTE_RX2` | **aucune** | — |
| initial | aucune fenêtre éligible | `AUCUNE` | **aucune** | `NO_WINDOW_CAPACITY` |
| `ATTENTE_RX1` | `EMITTED` | `EMIS_RX1` | inscrite | — |
| `ATTENTE_RX1` | ¬émis, repli indisponible | `AUCUNE` | **aucune** | `WINDOW_MISSED` |
| `ATTENTE_RX1` | ¬émis, repli dispo, ¬`rx2_eligible` | `AUCUNE` | **aucune** | `RX2_CAPACITY` |
| `ATTENTE_RX1` | ¬émis, repli dispo, `rx2_eligible` | `ATTENTE_RX2` | **aucune** | — |
| `ATTENTE_RX2` | `EMITTED` | `EMIS_RX2` | inscrite | — |
| `ATTENTE_RX2` | ¬émis | `AUCUNE` | **aucune** | `WINDOW_MISSED` |

#### 23.3.5 Propriétés garanties

| # | Propriété | Fondement |
|---|---|---|
| **P-a** | Une fenêtre inéligible n'est jamais réservée | R-N2 — filtrage avant `demand` |
| **P-b** | Aucune troncature | la trame n'est jamais modifiée |
| **P-c** | Aucun décalage temporel | aucune occupation inscrite (R-N4) |
| **P-d** | Aucune émission hors fenêtre | la règle `EXACTE` n'est pas touchée (A6) |
| **P-e** | `rx1 + rx2 + aucune == len(jobs)` | conservation du contrat de sortie |
| **P-f** | `fenetres[k] ∈ {None, "rx1", "rx2"}` | contrat de sortie inchangé |
| **P-g** | Idempotence | la validation est pure (R-N4) |

### 23.4 Les trois refus, distincts

#### 23.4.1 Refus de configuration

Porte sur le **triplet (région, SF, bande)**, avant toute planification. Il est **fatal pour la
scène** : il n'y a pas de radio à construire, donc pas de job, donc pas de chronologie.

```
si (région renseignée) et (aucun DR montant ne correspond à (SF, BW)) :
    lever RadioConfigurationError(UNSUPPORTED_UPLINK_DATARATE)
```

Décision **P1** : **aucun DR de substitution n'est inventé**, et **aucun repli silencieux** vers
une modulation générique ne subsiste. Le comportement actuel — qui retombe sur
`rx1_sf = sf, rx1_bw_hz = 125 000` en ignorant le mappage régional — est précisément le défaut à
supprimer.

Ce refus est **localisé** : il se produit dans la construction de la radio, côté Python. Le cœur
C++ ne reçoit jamais une telle radio, et n'a donc **pas besoin** d'être modifié pour P1.

#### 23.4.2 Refus de charge

Porte sur une **fenêtre**, pas sur la scène. Non fatal : les autres fenêtres restent examinables.

| Motif | Condition | Portée |
|---|---|---|
| `PAYLOAD_TOO_LARGE` | `charge > N` de la fenêtre | descentes applicatives |
| `FOPTS_OVERFLOW` | `charge ≤ N` mais `charge + \|FOpts\| > N` | descentes applicatives |
| `RX2_CAPACITY` | RX1 échouée, RX2 ne peut porter la trame | décision 1 |
| `NO_WINDOW_CAPACITY` | aucune fenêtre candidate ne peut porter la trame | R-N3 |

Rappel de la relation : `fil = 13 + N + |FOpts|`, avec
`13 = MHDR(1) + FHDR(7) + FPort(1) + MIC(4)`.

**Trames MAC — jamais soumises à N** : `ack` et `mac_answer` (12 o), `join_accept` (17 o, 33 avec
CFList) suivent leurs propres règles et ne sont **pas** concernées par ces motifs.

#### 23.4.3 Échec de placement

La fenêtre **peut** porter la trame, mais l'émetteur est occupé à l'ouverture. Verdict
`WINDOW_MISSED` : **aucune occupation**, aucune émission. Motif `WINDOW_MISSED`. C'est le
comportement existant, inchangé.

#### 23.4.4 Tableau comparatif

| | Refus de configuration | Refus de charge | Échec de placement |
|---|---|---|---|
| **Objet** | la radio (région, SF, BW) | une fenêtre | une fenêtre |
| **Quand** | construction de la radio | à la candidature de la fenêtre | au placement |
| **Grandeur** | existence d'un DR | `N` du DR descendant | occupation de l'émetteur |
| **Fatal pour la scène** | **oui** | non | non |
| **Autres fenêtres** | sans objet | **restent examinables** | restent examinables |
| **Occupation** | aucune | **aucune** | **aucune** |
| **Diagnostic** | `UNSUPPORTED_UPLINK_DATARATE` | `PAYLOAD_TOO_LARGE` · `FOPTS_OVERFLOW` · `RX2_CAPACITY` · `NO_WINDOW_CAPACITY` | `WINDOW_MISSED` |
| **Côté** | Python seul | Python **et** C++ (parité) | inchangé |

### 23.5 Comportement exact du planificateur sur fenêtre inéligible

#### 23.5.1 Algorithme

```
taille = base + len(fopts)                     # base : 13 + charge pour une trame applicative

# 1. Construction du job : éligibilité par fenêtre, à partir du plan
job.rx1_eligible = (kind est MAC) ou (taille ≤ N(dr_rx1))
job.rx2_eligible = job.rx2_disponible et ((kind est MAC) ou (taille ≤ N(dr_rx2)))

# 2. Première fenêtre candidate (jamais de demande pour une fenêtre inéligible)
si job.rx1_eligible :
    demander(RX1, ensuite=après(k, rx2=Faux))
sinon si job.rx2_eligible et repli_actif :
    demander(RX2, ensuite=après(k, rx2=Vrai))       # R-N3 : RX2 reste examinable
sinon :
    motif[k] = NO_WINDOW_CAPACITY                   # aucune occupation

# 3. Réaction
après(k, rx2) :
    si émis : starts[k], fenetres[k]                # terminal
    sinon si rx2 ou non repli_actif ou non rx2_disponible :
        motif[k] = WINDOW_MISSED                    # terminal
    sinon si non job.rx2_eligible :
        motif[k] = RX2_CAPACITY                     # terminal — aucune réservation
    sinon :
        déposer(RX2, ensuite=après(k, rx2=Vrai))    # transition
```

#### 23.5.2 Invariants à vérifier

| # | Invariant |
|---|---|
| **I-1** | `occupation` est **identique** à celle d'une exécution où les fenêtres inéligibles n'auraient jamais existé |
| **I-2** | Pour tout job en `AUCUNE(RX2_CAPACITY)`, `starts[k] is None` et **aucun intervalle** ne lui correspond dans `occupation` |
| **I-3** | `sum(len(o) for o in occupation)` avec repli ≥ sans repli, et **égal** si toutes les RX2 sont inéligibles |
| **I-4** | Aucun `t_open`, `t_open_rx2` ni `ready_ns` modifié |
| **I-5** | Le motif est renseigné pour **tout** job en `AUCUNE` |

### 23.6 Compatibilité des API Python et de l'ABI C

#### 23.6.1 Python

| Élément | État actuel | Proposition |
|---|---|---|
| `ProtocolOptions.downlink_payload_bytes` | `Field(10, ge=0, le=242)` | **inchangé** — 242 reste le plafond absolu |
| Validation régionale | absente | **ajoutée**, sans nouvelle option |
| N | non exposé | dérivé du plan ; **aucun paramètre utilisateur requis** |
| Nouvelle exception | — | `RadioConfigurationError` (P1) |
| Motifs et compteurs | — | **additifs**, jamais substitués |
| `fenetres`, `starts`, `occupation` | contrat de sortie | **inchangés** |

La valeur par défaut (10 o) est valide dans les sept régions et à tous les DR descendants (N
minimal = 51) : **les scénarios valides ne changent pas**.

#### 23.6.2 Contrainte majeure — le cœur C++ ne connaît pas les régions

Vérifié : `core/include/lsim/downlink_plan.hpp` ne contient **ni région ni `max_frm_payload`**.
`DeviceRadio` porte `dr`, `rx1_sf`, `rx1_bw_hz` ; `DeviceRx2` porte `rx2_sf`, `rx2_bw_hz`. Les
régions n'existent que sur le chemin de boucle fermée (`lsim_loop_region`), pas sur celui de
`downlink_plan`.

> **Le cœur C++ est donc incapable de calculer N.** La parité (décision 5) exige que N lui soit
> **fourni** par l'appelant. C'est la seule nécessité d'extension ABI du présent plan — elle est
> démontrée, non supposée.

#### 23.6.3 Options d'extension — toutes additives

**Les deux structures concernées disposent d'emplacements réservés**, ce qui rend l'extension
possible **sans changer la taille** d'aucune structure :

| Structure | Champ | Décalage x86-64 | Emplacement |
|---|---|---|---|
| `lsim_plan_device_rx2` | `uint64_t reserved[2]` | 16 | disponible |
| `lsim_plan_downlinks_v2_args` | `uint64_t reserved[2]` | 112 | disponible |
| `lsim_plan_device` | — | — | **aucun** (non extensible) |

**Option A — emplacements réservés (recommandée).**

```
lsim_plan_device_rx2.reserved[0]  ← rx2_max_payload_bytes  (0 = aucune contrainte)
v2_args.reserved[0]               ← const uint32_t* rx1_max_payload_bytes, par dispositif
                                    (NULL = aucune contrainte)
```

La taille des structures est **inchangée** (128 o en x86-64 pour `v2_args`). Un appelant
existant, qui met ses champs réservés à zéro, obtient **exactement** le comportement actuel :
`0` et `NULL` signifient « aucune contrainte ». Aucun `abi_version` à incrémenter, aucune
recompilation obligatoire.

*Réserve* : le contrat documenté dit « réservé, laisser à zéro ». Affecter ces emplacements est
donc un changement **sémantique**, quoique layout-compatible. Le précédent
`LSIM_STATUS_CHANNEL_RESERVED_NONZERO` (chemin `closed_loop_v3`) montre que ce projet sait
déjà refuser des emplacements réservés non nuls — la validation devra être **assouplie**
sélectivement sur ce seul point d'entrée.

**Option B — nouveau point d'entrée `lsim_plan_downlinks_v3`.** Plus propre sur le plan
contractuel, mais duplique la surface et la maintenance. À réserver au cas où l'option A
s'avérerait incompatible avec la politique de validation des champs réservés.

**Option C — validation côté Python seul, cœur inchangé.** Écartée : Python filtrerait et le
cœur placerait quand même, donc `test_downlink_plan_parity.py` **divergerait**. La parité est
une exigence (décision 5), pas une option.

#### 23.6.4 Statuts

`PlanStatus` est un `enum class : std::int32_t` (`Ok=0`, `InvalidInput=1`, `InvalidRadio=2`,
`InvalidOptions=3`). Toute valeur nouvelle est **ajoutée en fin** : le type sous-jacent est
fixé, l'ajout est donc sûr.

```
PlanStatus::UnsupportedUplinkDatarate = 4   // défensif : le cœur ne devrait jamais le voir
PlanStatus::PayloadTooLarge          = 5
PlanStatus::FoptsOverflow            = 6
```

### 23.7 Tests de non-régression et de parité

#### 23.7.1 Non-régression

| # | Test | Attendu |
|---|---|---|
| **T-NR1** | Les 22 usages recensés au §22.8 hors `test_d315_global.py` | résultats **identiques** |
| **T-NR2** | Trames MAC (`ack`, `mac_answer`, `join_accept`) | jamais refusées ; temps d'antenne inchangé |
| **T-NR3** | Charge 10 (défaut), sept régions | aucun changement |
| **T-NR4** | `test_d315_causal_envelope.py` (200 o et 60 o, EU868 SF7, N=222) | **identique** — scènes déjà valides |
| **T-NR5** | Bornes 243 et 300 | refus inchangé, **avant** tout contrôle régional |
| **T-NR6** | Compteurs `rx1 + rx2 + aucune == len(jobs)` | conservé sur toutes les scènes |

#### 23.7.2 Parité

| # | Test | Attendu |
|---|---|---|
| **T-PA1** | AU915 SF7 (RX1 DR13, N=222 ; RX2 DR8, N=53), charge 120, repli actif | aucune émission RX2, motif `RX2_CAPACITY` |
| **T-PA2** | Occupation avec repli vs sans repli, même scène | **égalité stricte** (aucun dépôt ⇒ aucune réservation) |
| **T-PA3** | Même scène, charge 40 (≤ 53) | le repli **fonctionne** — garde-fou contre un refus excessif |
| **T-PA4** | T-PA1 à T-PA3 sur le chemin Python **et** le chemin C++ | **identiques au bit près** |
| **T-PA5** | Sept régions × charge à la frontière | `N` accepté, `N+1` refusé |
| **T-PA6** | `condition` non utilisée pour l'éligibilité | le repli n'est jamais supprimé (R-N3) |
| **T-PA7** | Fenêtre RX1 inéligible, RX2 éligible | RX2 examinée et placée — symétrie (R-N1) |

**T-PA3 et T-PA6 sont les garde-fous essentiels** : ils empêchent que la règle ne supprime un
repli légitime.

### 23.8 Plan de migration D3.15 — sept régions (décision P2)

#### 23.8.1 Diagnostic

Contrôle de chaque scène de référence avec **ses propres** paramètres.

| Région | SF réf. | DR montant | RX1 | N(RX1) | RX2 | N(RX2) | Verdict P1 |
|---|---|---|---|---|---|---|---|
| EU868 | 11 | DR1 | DR1 | **51** | DR0 | **51** | conforme |
| US915 | 11 | **aucun** | — | — | DR8 | 53 | **REFUS `UNSUPPORTED_UPLINK_DATARATE`** |
| AS923 | 7 | DR5 | DR5 | 222 | DR2 | **51** | conforme |
| AU915 | 7 | DR5 | DR13 | 222 | DR8 | **53** | conforme |
| IN865 | 7 | DR5 | DR5 | 222 | DR2 | **51** | conforme |
| KR920 | 9 | DR3 | DR3 | **115** | DR0 | **51** | conforme |
| RU864 | 10 | DR2 | DR2 | **51** | DR0 | **51** | conforme |

**Deux constats majeurs :**

1. **US915 à SF11 est une erreur de configuration**, pas une scène lente. Ses DR montants sont
   SF10, SF9, SF8, SF7 — **SF11 n'existe qu'en descendant** (DR9). Le repli silencieux actuel
   masquait l'erreur. Sous P1, cette scène est refusée jusqu'à correction du SF.

2. **Trois régions ont une scène de référence déjà invalide** — EU868 (N=51), KR920 (N=115) et
   RU864 (N=51) — pour une charge de 120. La lacune est bien transversale ; **AU915 n'en était
   que le révélateur**.

#### 23.8.2 Corrections par région

| Région | Correction | N(RX1) | N(RX2) | Charge maximale permettant un repli |
|---|---|---|---|---|
| EU868 | aucune (SF11 conforme) | 51 | 51 | **51** |
| US915 | **SF 11 → 10** (P1) | 222 | 53 | **53** |
| AS923 | aucune (SF7 conforme) | 222 | 51 | **51** |
| AU915 | aucune (SF7 conforme) | 222 | 53 | **53** |
| IN865 | aucune (SF7 conforme) | 222 | 51 | **51** |
| KR920 | aucune (SF9 conforme) | 115 | 51 | **51** |
| RU864 | aucune (SF10 conforme) | 51 | 51 | **51** |

**Plafond commun aux sept régions : 51 octets.**

#### 23.8.3 Validité des charges D3.15 après correction

| Région | N(RX1) | N(RX2) | 20 | 60 | 120 | 240 |
|---|---|---|---|---|---|---|
| EU868 | 51 | 51 | **ok** | invalide | invalide | invalide |
| US915 | 222 | 53 | **ok** | RX1 seul | RX1 seul | invalide |
| AS923 | 222 | 51 | **ok** | RX1 seul | RX1 seul | invalide |
| AU915 | 222 | 53 | **ok** | RX1 seul | RX1 seul | invalide |
| IN865 | 222 | 51 | **ok** | RX1 seul | RX1 seul | invalide |
| KR920 | 115 | 51 | **ok** | RX1 seul | invalide | invalide |
| RU864 | 51 | 51 | **ok** | invalide | invalide | invalide |

`ok` = valide en RX1 **et** RX2 (le repli reste possible) · `RX1 seul` = motif `RX2_CAPACITY` au
repli · `invalide` = dépasse N(RX1), aucune fenêtre.

**Seule la charge de 20 octets est universellement valide.** La charge de 240, pilier des scènes
de saturation, est **invalide dans les sept régions sans exception**.

#### 23.8.4 Risque de vacuité — à neutraliser explicitement

Le gardien `test_chaque_region_exerce_le_repli` exige **au moins un repli par région**. Or
abaisser la charge de 240 à 20 ou 51 octets **réduit le temps d'antenne**, donc la saturation —
et avec elle le nombre de RX1 manquées. Le repli pourrait disparaître **non par invalidation
mais par absence de contention**, ce qui viderait le test de son sens sans le faire échouer.

**Parade** : la saturation est la **capacité série de l'émetteur**
(`Σ durées > temps disponible`, §20). Il faut l'obtenir en **augmentant le nombre de terminaux**,
non en ralentissant les trames. Chaque scène devra être **recalibrée** jusqu'à produire des RX1
manquées avec une charge ≤ N(RX2), puis **vérifiée** :

```
critère de validité d'une scène D3.15 :
    rx1 > 0  et  rx2 > 0  et  aucune ≥ 0   avec une charge ≤ N(RX2)
```

Une scène où `rx2 == 0` **par absence de contention** est une scène **vide**, pas une scène
conforme.

#### 23.8.5 Phasage proposé

| Étape | Contenu | Dépendance |
|---|---|---|
| **M1** | Appliquer P1 : refus `UNSUPPORTED_UPLINK_DATARATE` | — |
| **M2** | Corriger le SF de la scène US915 (11 → 10) | M1 |
| **M3** | Implémenter la validation transverse (Python) | — |
| **M4** | Implémenter la parité C++ (option A) | M3, décision sur §23.6.3 |
| **M5** | Inventaire des scènes D3.15 invalides (T-P10 du §21.8) | M3 |
| **M6** | Recalibrage des sept scènes : charge ≤ 51, nombre de terminaux ajusté | M5 |
| **M7** | Vérification du critère de non-vacuité, région par région | M6 |

M1 et M2 sont **indépendantes** du reste et peuvent précéder l'implémentation transverse.

### 23.9 Points ouverts

| # | Point | Options |
|---|---|---|
| **O1** | Option A (emplacements réservés) ou B (`v3`) pour l'ABI | A recommandée ; la politique de validation des champs réservés tranche |
| **O2** | `RadioConfigurationError` : exception nouvelle ou réutilisation d'un type existant | à décider |
| **O3** | Faut-il exposer N dans l'API publique, ou le garder dérivé du plan | non nécessaire au plan ; à décider |
| **O4** | Sort des scènes D3.15 historiques : recalibrées ou **archivées** comme témoins d'une hypothèse invalide | à décider — affecte M6 |

---

---

## 24. Plan consolidé — version définitive (arbitrages O1–O4 intégrés)

*Le §24 est la **version consolidée** du §23. Il reprend tout ce que le §23 établit et y intègre
les arbitrages O1, O2, O3, O4 ainsi que les cinq exigences complémentaires. Les §21, §22 et §23
sont conservés pour la traçabilité ; le §24 les complète et, sur les seuls points listés au
§24.0, s'y substitue.*

### 24.0 Ce que le §24 substitue au §23

| Point du §23 | Statut | Remplacé par |
|---|---|---|
| §23.6.3 — options A / A2 / B | **tranché** | §24.1 (option B retenue, démonstration à l'appui) |
| §23.6.4 — statuts | complété | §24.1.5 |
| §23.9 — point ouvert O1 | **clos** | §24.1 |
| §23.9 — point ouvert O2 | **clos** | §24.2 |
| §23.9 — point ouvert O3 | **clos** | §24.3 |
| §23.9 — point ouvert O4 | **clos** | §24.5 |
| §23.3.3 — machine à états | précisée | §24.4 (distinction capacité / temporel) |

Le reste du §23 — règles R-N1 à R-N4, machine à états, invariants, tests — demeure valide.

---

### 24.1 O1 — Choix de l'extension ABI, justifié

#### 24.1.1 Faits mesurés sur le code existant

| # | Fait | Emplacement |
|---|---|---|
| **F1** | `reserved` n'est **jamais validé** sur le chemin `downlink_plan` | `c_api_plan.cpp` ne vérifie que `struct_size` (l. 155) et `abi_version` (l. 158) |
| **F2** | `reserved` est **ignoré** à la conversion | `c_api_ext.cpp:1114-1118` ne recopie que `rx2_hz`, `rx2_sf`, `rx2_bw_hz` |
| **F3** | `abi_version` est validé par **égalité stricte** | `c_api_plan.cpp:158` — `args->abi_version != LSIM_PLAN_DOWNLINKS_V2_ABI_VERSION` |
| **F4** | Cette égalité stricte est **verrouillée par un test** | `core/tests/test_downlink_plan.cpp:462-465` — `abi_version = …+1u` ⇒ rejet attendu |
| **F5** | La convention du projet est l'**inverse** de la réutilisation : `reserved` **doit** être nul, et le non-respect est **refusé** | `LSIM_STATUS_CHANNEL_RESERVED_NONZERO` ; `closed_loop_v3_validate.cpp:76, 117` ; testé `test_abi_v3_prep.cpp:552` (`c.reserved[0] = 1`) |
| **F6** | Le projet **possède déjà** son idiome d'extension additive | `_CClosedLoopV4Args` : `struct_size`, `abi_version = 4`, `v4.v3` = pointeur vers l'args précédent (`closed_loop_v3.py:462-465`) |

> **F5 mérite l'attention.** La validation « champs réservés non nuls ⇒ refus » **existe** dans ce
> dépôt — mais sur le chemin `closed_loop_v3`, pas sur `downlink_plan`. Réutiliser les
> emplacements réservés sur `downlink_plan` consisterait à introduire, sur un seul chemin, une
> sémantique que le projet refuse explicitement partout ailleurs.

#### 24.1.2 Les quatre démonstrations demandées

| Condition exigée | **A1** — `reserved`, sans version | **A2** — `reserved` + version 2 dans v2 | **B** — nouveau point d'entrée v3 |
|---|---|---|---|
| **1. Zéro contractuellement garanti pour les anciens appelants** | ✗ **non démontré** | ✗ **non démontré** | ✓ sans objet |
| **2. Zéro conserve exactement le comportement historique** | ✓ si `0` = sans contrainte | ✓ idem | ✓ si `NULL` = sans contrainte |
| **3. Anciennes bibliothèques + nouveaux appelants** | ✗ **divergence silencieuse** | ✗ **casse un test verrouillé** | ✓ détectable |
| **4. Valeurs inconnues rejetées proprement** | ✗ aucun signal | ✓ mais casse le test | ✓ |

**Détail de la condition 1.** Le contrat « réservé, laisser à zéro » est **documenté**
(`DOWNLINK_PLAN_ABI_V2.md:36, 57`) mais **jamais vérifié** (F1, F2). Un appelant historique qui
laisserait ces octets non initialisés n'est **pas rejeté aujourd'hui** — les octets sont ignorés.
Après réutilisation, ces mêmes octets deviennent **porteurs de sens** : une mémoire non
initialisée produirait un N aléatoire, **sans aucune erreur**. La garantie est conventionnelle,
non démontrée. ✔ condition non remplie par A1 et A2.

**Détail de la condition 3 — le mode de défaillance rédhibitoire de A1.** Un nouvel appelant
écrit `reserved[0] = 53` et conserve `abi_version = 1`. Une ancienne bibliothèque accepte
(`abi_version == 1`), **ignore** `reserved`, et planifie **sans appliquer la validation**. Aucune
erreur n'est renvoyée : la divergence est **silencieuse**, précisément le défaut que toute cette
analyse cherche à éliminer.

**Détail de la condition 3 pour A2.** Faire accepter la version 2 impose de modifier
`core/tests/test_downlink_plan.cpp:462-465`, qui **assert que `ABI_VERSION + 1` est rejeté**.
Une extension qui exige de lever un verrou existant n'est pas une extension additive.

#### 24.1.3 Décision

> **Option B retenue** : nouveau point d'entrée versionné, **explicitement activé**, suivant
> l'idiome déjà établi par `_CClosedLoopV4Args` (F6). Aucun champ réservé n'est réaffecté, aucun
> test existant n'est modifié.

#### 24.1.4 Forme proposée

```c
#define LSIM_PLAN_DOWNLINKS_V3_ABI_VERSION 3

/* Limites de charge par fenêtre, par dispositif. */
typedef struct lsim_plan_window_limits {
    uint64_t struct_size;                 /* sizeof(lsim_plan_window_limits), obligatoire */
    uint32_t rx1_max_payload_bytes;       /* 0 = aucune contrainte (= comportement historique) */
    uint32_t rx2_max_payload_bytes;       /* 0 = aucune contrainte */
    uint64_t reserved[2];                 /* réservé, laisser à zéro — et VALIDÉ non nul */
} lsim_plan_window_limits;

typedef struct lsim_plan_downlinks_v3_args {
    uint32_t struct_size;                 /* obligatoire */
    uint32_t abi_version;                 /* LSIM_PLAN_DOWNLINKS_V3_ABI_VERSION, obligatoire */
    const lsim_plan_downlinks_v2_args* v2;/* entrées de la v2, par pointeur — idiome V4      */
    const lsim_plan_window_limits* limits;/* NULL = aucune contrainte = comportement v2      */
    size_t limits_count;                  /* entrées de `limits` ; 0 si NULL                 */
    uint64_t reserved[2];                 /* réservé, laisser à zéro — et VALIDÉ non nul     */
} lsim_plan_downlinks_v3_args;

LSIM_API int32_t lsim_plan_downlinks_v3(const lsim_plan_downlinks_v3_args* args);
```

Propriétés :

| Propriété | Garantie |
|---|---|
| Ancien appelant + nouvelle bibliothèque | utilise v1/v2, **inchangé** |
| Nouvel appelant + ancienne bibliothèque | symbole `lsim_plan_downlinks_v3` **absent** ⇒ échec de résolution, **détectable au chargement** |
| `limits == NULL` | comportement v2 **à l'identique** |
| `rx*_max_payload_bytes == 0` | aucune contrainte sur cette fenêtre |
| Champs réservés | validés non nuls, conformément à **F5** |
| `abi_version` inconnu | rejeté |
| Tests existants | **aucun modifié** |

#### 24.1.5 Statuts

```
PlanStatus::UnsupportedUplinkDatarate = 4   /* défensif — le cœur ne devrait jamais le voir */
PlanStatus::PayloadTooLarge           = 5
PlanStatus::FoptsOverflow             = 6
PlanStatus::InvalidWindowLimits       = 7   /* limits_count incohérent, ou N > 242        */
```

Ajoutés **en fin** d'un `enum class : std::int32_t` : le type sous-jacent est fixé, l'ajout est sûr.

---

### 24.2 O2 — Contrat d'erreur pour P1

```python
class UnsupportedUplinkDataRateError(ValueError):
    """Aucun DR montant du plan régional ne correspond au (SF, bande) demandé.

    Levée **avant la simulation**, à la construction de la radio. Aucun DR de substitution
    n'est inventé et aucun repli silencieux vers une modulation générique n'a lieu.
    """

    region: str                 # région du plan, telle que fournie
    spreading_factor: int       # SF demandé
    bandwidth_hz: int           # bande demandée
    available: tuple[int, ...]  # SF montants effectivement disponibles dans la région
```

| Exigence | Réalisation |
|---|---|
| Hérite de `ValueError` | oui — les appelants qui interceptent `ValueError` restent corrects |
| Expose la région | `e.region` |
| Expose le SF demandé | `e.spreading_factor` |
| Expose le contexte montant | `e.bandwidth_hz`, `e.available` |
| Avant la simulation | levée dans la construction de la radio, **jamais** pendant la planification |
| Sans repli silencieux | le comportement actuel (`rx1_sf = sf`, `rx1_bw_hz = 125 000`) est **supprimé** |

Message attendu, actionnable :

```
US915 : aucun DR montant pour SF11 @125000 Hz.
SF montants disponibles dans cette région : SF10, SF9, SF8, SF7.
```

**Portée.** Ce refus est **localisé côté Python** : le cœur C++ reçoit des radios déjà
construites et n'en verra jamais une invalide. Le statut `UnsupportedUplinkDatarate` du §24.1.5
est donc **purement défensif**.

---

### 24.3 O3 — Schéma des diagnostics et des résultats

#### 24.3.1 Contrainte découverte sur `RunSummary`

`RunSummary` (`api_contract.py:191`) dérive de `_Strict`, dont la configuration est
**`extra="forbid", frozen=True`** (`api_contract.py:48-49`), et son invariant
« exactement un de `gateway` / `gateways` » est **testé**
(`test_api_contract.py::test_run_summary_accepts_exactly_one_load_shape`).

> **Conséquence :** les diagnostics **ne peuvent pas** être ajoutés comme clés libres — elles
> seraient rejetées. Ils doivent être des **champs déclarés**, **optionnels**, **avec valeur par
> défaut**.

#### 24.3.2 Schéma proposé

```python
class DownlinkWindowDiagnostic(_Strict):
    """Diagnostic d'une fenêtre descendante candidate, pour une trame donnée."""

    window: str                          # "rx1" | "rx2"
    data_rate: Optional[int]             # DR descendant retenu pour cette fenêtre
    max_payload_bytes: Optional[int]     # N applicable à ce DR
    payload_bytes: int                   # charge applicative
    fopts_bytes: int                     # |FOpts|
    frame_bytes: int                     # fil = 13 + charge + |FOpts|
    eligible: bool                       # la fenêtre peut-elle porter la trame ?
    famille: Optional[str]               # None | "capacite" | "temporel"
    motif: Optional[str]                 # None | PAYLOAD_TOO_LARGE | FOPTS_OVERFLOW |
                                         #        RX2_CAPACITY | NO_WINDOW_CAPACITY |
                                         #        WINDOW_MISSED


class DownlinkCompliance(_Strict):
    """Conformité des charges descendantes — exposée **en sus**, jamais à la place."""

    emitted_ok: int                      # trames émises conformes à N de la fenêtre utilisée
    refused_payload_too_large: int
    refused_fopts_overflow: int
    refused_rx2_capacity: int
    refused_no_window_capacity: int
    diagnostics: list[DownlinkWindowDiagnostic]
```

#### 24.3.3 Intégration dans `RunSummary` — strictement additive

```python
class RunSummary(_Strict):
    …                                    # champs existants, aucun modifié, aucun renommé
    downlink_compliance: Optional[DownlinkCompliance] = None   # NOUVEAU, défaut None
```

| Exigence | Réalisation |
|---|---|
| DR sélectionné | `DownlinkWindowDiagnostic.data_rate` |
| N applicable | `max_payload_bytes` |
| Taille applicative | `payload_bytes` |
| FOpts | `fopts_bytes` |
| Fenêtre concernée | `window` |
| Motif de refus | `motif` + `famille` |
| Aucune casse de `run_summary` | champ **déclaré**, **optionnel**, **défaut `None`** : toute charge utile historique reste valide |

**Aucun champ existant n'est supprimé, renommé ni rendu obligatoire.**

---

### 24.4 Machine à états définitive

#### 24.4.1 Exigence 1 — distinction stricte capacité / indisponibilité temporelle

Deux familles **disjointes**, jamais confondues :

| Famille | Signification | Motifs | Occupation |
|---|---|---|---|
| **`capacite`** | la fenêtre **ne peut pas** porter la trame : `fil > N(dr)` | `PAYLOAD_TOO_LARGE` · `FOPTS_OVERFLOW` · `RX2_CAPACITY` · `NO_WINDOW_CAPACITY` | **aucune** — aucune demande déposée |
| **`temporel`** | la fenêtre **peut** porter la trame, mais l'émetteur est occupé à l'ouverture | `WINDOW_MISSED` | **aucune** — verdict de l'arbitre |
| **`configuration`** | la radio elle-même est invalide | `UNSUPPORTED_UPLINK_DATARATE` | sans objet — avant simulation |

Le motif `WINDOW_MISSED` reprend le verdict de l'arbitre ; il est **réservé** à l'indisponibilité
temporelle. Aucun motif de capacité ne porte ce nom.

#### 24.4.2 États et transitions

```
États : INITIAL | ATTENTE_RX1 | ATTENTE_RX2 | EMIS_RX1 | EMIS_RX2 | AUCUNE(motif)

ÉLIGIBILITÉ (une fois, à la construction du job, depuis le plan)
    rx1_eligible = (trame MAC) ou (fil ≤ N(dr_rx1))
    rx2_eligible = rx2_disponible et ((trame MAC) ou (fil ≤ N(dr_rx2)))

INITIAL
    rx1_eligible                              → ATTENTE_RX1
    ¬rx1_eligible ∧ rx2_eligible ∧ repli      → ATTENTE_RX2        ← exigence 2
    sinon                                     → AUCUNE(NO_WINDOW_CAPACITY)   [capacite]

ATTENTE_RX1
    EMITTED                                   → EMIS_RX1
    ¬émis :
        ¬(repli ∧ rx2_disponible)             → AUCUNE(WINDOW_MISSED)        [temporel]
        ¬rx2_eligible                         → AUCUNE(RX2_CAPACITY)         [capacite]
        sinon                                 → ATTENTE_RX2                  ← exigence 2

ATTENTE_RX2
    EMITTED                                   → EMIS_RX2
    ¬émis                                     → AUCUNE(WINDOW_MISSED)        [temporel]
```

#### 24.4.3 Exigence 2 — poursuite de l'examen après ineligibilité

Deux mécanismes distincts rendent la poursuite effective :

1. **Le filtrage précède la demande**, il ne la remplace pas. Une fenêtre inéligible n'est pas
   déposée (R-N2), mais la **réaction** est déclenchée comme si elle avait échoué — le parcours
   continue vers la fenêtre suivante (R-N3).
2. **`condition` n'est pas utilisé** pour l'éligibilité. Rappel du §23.3.2 : `condition` faux
   ⇒ `NOT_NEEDED` ⇒ **`ensuite` non appelé** ⇒ le repli serait supprimé. C'est la raison pour
   laquelle le filtrage est fait en amont de `arbitre.demand`.

**Traces commentées :**

| Cas | Région / fenêtres | Déroulé | Issue |
|---|---|---|---|
| **C1 — repli refusé par capacité** | AU915 SF7 · RX1 DR13 (N=222) · RX2 DR8 (N=53) · charge 120 | `rx1_eligible` ✓ → `ATTENTE_RX1` → émetteur occupé → repli dispo, `rx2_eligible` ✗ (120 > 53) | **`AUCUNE(RX2_CAPACITY)`** · aucune occupation RX2 |
| **C2 — repli autorisé** | idem, charge 40 | `rx1_eligible` ✓ → RX1 manquée → `rx2_eligible` ✓ (40 ≤ 53) → `ATTENTE_RX2` → émise | **`EMIS_RX2`** |
| **C3 — symétrie, RX1 inéligible** | hypothétique : RX1 N=51, RX2 N=222, charge 120 | `rx1_eligible` ✗ → **RX2 examinée directement** (RX1 ni réservée ni émise) | **`EMIS_RX2`** |
| **C4 — aucune fenêtre** | EU868 SF11 · N=51 partout · charge 120 | `rx1_eligible` ✗ ∧ `rx2_eligible` ✗ | **`AUCUNE(NO_WINDOW_CAPACITY)`** |

C3 illustre l'exigence : **l'inéligibilité de RX1 ne clôt pas le parcours**.

#### 24.4.4 Invariants

| # | Invariant |
|---|---|
| **I-1** | `occupation` identique à une exécution où les fenêtres inéligibles n'auraient jamais existé |
| **I-2** | Tout job en `AUCUNE(famille=capacite)` a `starts[k] is None` et **aucun intervalle** |
| **I-3** | Aucun `t_open`, `t_open_rx2` ni `ready_ns` modifié (R-N4) |
| **I-4** | `rx1 + rx2 + aucune == len(jobs)` |
| **I-5** | Tout motif appartient à **une seule** famille, sans ambiguïté |
| **I-6** | `fenetres[k] ∈ {None, "rx1", "rx2"}` — contrat de sortie inchangé |

---

### 24.5 O4 — Protocole d'archivage et de recalibrage D3.15

#### 24.5.1 Exigence 5 — préservation : trois phases, aucune écrasement

**Phase A — Archivage (destructif interdit)**

1. Copie **intégrale** des artéfacts D3.15 actuels vers
   `docs/archives/d315-avant-recalibrage/<date>/`, accompagnée d'un manifeste
   (liste des fichiers, sommes SHA-256, commit de référence `51e7de0`).
2. **Aucun fichier historique n'est supprimé, déplacé ni modifié.** L'archive est en lecture
   seule ; les fichiers d'origine restent en place jusqu'à la création effective du nouveau jeu.
3. Chaque artéfact archivé reçoit une bannière :

   > *Jeu historique — archivé le \<date\>. Certaines conclusions reposent sur des charges non
   > conformes à N. Voir `d315-STATUT.md`.*

**Phase B — Marquage des conclusions**

Création de `docs/archives/d315-STATUT.md`, conclusion par conclusion :

| Conclusion historique | Fondement | Verdict |
|---|---|---|
| Paramètres RX2 conformes au cœur | indépendant de la charge | **démontrée** — conservée |
| Parité Python/C++ du repli | AU915 absent du périmètre | **non démontrée** — hors portée |
| Le repli n'enlève jamais d'antenne | passe **par égalité** quand `rx2 == 0` | **non démontrée** — test vacant |
| Chaque région exerce le repli | repose sur des charges > N | **invalidée** — à reconstruire |
| Le SF12 n'est jamais jugé plus rapide | contribue sur **trames invalides** | **invalidée** — à reconstruire |

Trois verdicts seulement : **démontrée** · **invalidée** (repose sur une charge non conforme) ·
**non démontrée** (test vacant ou hors portée). Aucun résultat historique n'est effacé.

**Phase C — Nouveau jeu de référence D3.15-R**

| Paramètre | Valeur |
|---|---|
| Régions | les **sept**, chacune avec ses paramètres (décision P2) |
| SF US915 | **10** (SF11 impossible en montant — décision P1) |
| Charge | **≤ 51 octets** (plafond commun = min N(RX2)) |
| Saturation | obtenue par le **nombre de terminaux**, non par le ralentissement des trames |
| Critère d'acceptation | `rx1 > 0` **et** `rx2 > 0` par région |

#### 24.5.2 Exigence 3 — démontrer que les replis viennent de la contention

Le risque identifié au §23.8.4 est qu'un repli disparaisse **par absence de contention**, ce qui
donnerait un test vert mais vide. La parade est un **triple contrôle** :

| # | Exécution | Attendu | Ce que cela prouve |
|---|---|---|---|
| **D1** | Scène saturée, `rx2_fallback=True` | `rx2 > 0` | le repli se produit |
| **D2** | **Même graine, même scène**, `rx2_fallback=False` | ces mêmes jobs tombent en `aucune` | ils avaient **réellement manqué** RX1 |
| **D3** | Même scène, **nombre de terminaux réduit** (sans contention) | `rx2 == 0` **et** `aucune == 0` | le repli de D1 est **causé par la contention**, non par la capacité |

D2 est la pièce maîtresse : sans lui, `rx2 > 0` pourrait masquer un placement RX1 qui n'a jamais
été tenté. D3 garantit que le dispositif de mesure est sensible.

#### 24.5.3 Exigence 4 — vérifier N pour le DR réellement utilisé, y compris après repli

| # | Vérification | Attendu |
|---|---|---|
| **V1** | Pour chaque job émis, `diagnostic.data_rate` = DR de la fenêtre **réellement** utilisée | concordance avec `fenetres[k]` |
| **V2** | Pour chaque job émis, `frame_bytes ≤ max_payload_bytes` du diagnostic | aucune trame émise au-delà de N |
| **V3** | Pour chaque job passé en RX2, `N(dr_rx2)` a été évalué **au moment du repli** | le DR de RX2, jamais celui de RX1 |
| **V4** | Pour chaque motif `RX2_CAPACITY`, `frame_bytes > N(dr_rx2)` et `frame_bytes ≤ N(dr_rx1)` | le motif est exact, ni excessif ni insuffisant |

---

### 24.6 Critères d'acceptation

| # | Critère | Vérifié par |
|---|---|---|
| **A1** | Aucune trame émise au-delà de N de sa fenêtre | V2 |
| **A2** | Aucune fenêtre inéligible réservée | I-1, I-2 |
| **A3** | Le repli légitime n'est jamais supprimé | C2, T-PA3 |
| **A4** | Capacité et temporel ne sont jamais confondus | I-5 |
| **A5** | Aucune chronologie modifiée | I-3 |
| **A6** | Contrats `RunSummary` intacts | §24.3.3 |
| **A7** | Aucun test existant modifié | §24.1.4 |
| **A8** | Parité Python/C++ au bit près | T-PA4 |
| **A9** | Les sept régions exercent le repli **par contention** | D1, D2, D3 |
| **A10** | Résultats historiques préservés | Phase A + `d315-STATUT.md` |

### 24.7 Tests de parité

| # | Test | Attendu |
|---|---|---|
| **T-PA1** | C1 (AU915 SF7, 120 o, repli actif) | `AUCUNE(RX2_CAPACITY)`, aucune occupation RX2 |
| **T-PA2** | Occupation avec repli vs sans repli, C1 | **égalité stricte** |
| **T-PA3** | C2 (40 o) | repli **réussi** — garde-fou anti-refus-excessif |
| **T-PA4** | C1, C2, C3 sur Python **et** C++ | **identiques au bit près** |
| **T-PA5** | Sept régions × charge à la frontière | `N` accepté, `N+1` refusé |
| **T-PA6** | `condition` non utilisé | repli jamais supprimé |
| **T-PA7** | C3 (RX1 inéligible, RX2 éligible) | RX2 examinée et placée |
| **T-PA8** | `reserved` non nul sur les nouvelles structures | refus propre (conformément à F5) |
| **T-PA9** | Ancien appelant (`abi_version = 1`, `limits = NULL`) | comportement historique **à l'identique** |
| **T-PA10** | Nouvel appelant sur bibliothèque sans `v3` | échec de résolution **détectable** |
| **T-PA11** | `UnsupportedUplinkDataRateError` : US915 SF11 | levée **avant** simulation, attributs complets |
| **T-PA12** | `RunSummary` sans `downlink_compliance` | validation **inchangée** |

---

---

## 25. Revue contradictoire du §24

*Recherche systématique des cas où **un test passerait alors que le comportement réel resterait
incorrect**. Étape documentaire et analytique : aucun code, test, fixture ou scénario n'a été
modifié.*

### 25.1 Méthode

Chaque élément du §24 est soumis à trois questions :

1. **Opérabilité** — l'invariant ou le critère est-il **mesurable**, et la référence à laquelle on
   le compare existe-t-elle ?
2. **Non-vacuité** — le test échouerait-il réellement si le comportement était faux, ou passe-t-il
   « par construction » ?
3. **Non-circularité** — la vérification utilise-t-elle une grandeur **indépendante** du code
   sous test, ou se contente-t-elle de constater que le code est d'accord avec lui-même ?

Neuf anomalies sont relevées, dont **deux graves**.

### 25.2 Anomalies

#### 25.2.1 **[GRAVE]** Erreur normative de 13 octets dans la règle d'éligibilité

Le §24.4.2 énonce `rx1_eligible = fil ≤ N(dr_rx1)`. **C'est faux.**

| Grandeur | Définition |
|---|---|
| `N` | charge utile maximale (**FRMPayload**) |
| `M` | MACPayload maximale — **vérifié : `M = N + 8`** (AU915 : DR8 61/53, DR9 137/129) |
| `fil` | PHYPayload `= 13 + charge + \|FOpts\|` |

MACPayload `= 7 + |FOpts| + 1 + charge ≤ M = N + 8` se réduit à :

> **Règle correcte : `charge + |FOpts| ≤ N`** — équivalente à `fil ≤ N + 13`.

La règle écrite (`fil ≤ N`) **sous-utilise la capacité de 13 octets** et **rejette des trames
légales** : une charge de 53 octets en AU915 RX2 (N = 53) est parfaitement légale, mais
`fil = 66 > 53` la ferait refuser à tort.

#### 25.2.2 **[GRAVE]** Les traces C1–C4 ne distinguent pas la règle fausse de la vraie

Conséquence directe : **aucune des quatre traces ne détecte l'anomalie 25.2.1**.

| Trace | N | charge | `fil` | règle écrite | règle correcte | distingue ? |
|---|---|---|---|---|---|---|
| C1 RX1 | 222 | 120 | 133 | ✓ | ✓ | **non** |
| C1 RX2 | 53 | 120 | 133 | ✗ | ✗ | **non** |
| C2 RX2 | 53 | 40 | 53 | ✓ | ✓ | **non** *(coïncidence)* |
| C3 RX1 | 51 | 120 | 133 | ✗ | ✗ | **non** |
| C4 RX1/RX2 | 51 | 120 | 133 | ✗ | ✗ | **non** |
| **bord RX2** | 53 | **53** | 66 | ✗ | **✓** | **oui** |
| **bord RX1** | 222 | **222** | 235 | ✗ | **✓** | **oui** |

La trace C2 est la plus insidieuse : `13 + 40 = 53 = N` — elle passe **par coïncidence
arithmétique**, au point exact où les deux règles se confondent.

> **Leçons :** (i) aucune trace ne se situe à la **frontière** de N ; (ii) C2, censée être le
> garde-fou anti-refus-excessif, est calibrée sur une coïncidence.

#### 25.2.3 T-PA2 est vacant pris isolément

T-PA2 vérifie « occupation avec repli = occupation sans repli » sur C1. Or si le **mécanisme de
repli était entièrement cassé** (aucune demande RX2 jamais déposée), l'occupation serait
**aussi** identique : le test passerait. T-PA2 ne devient probant **qu'accolé à T-PA3** (C2, où le
repli doit aboutir).

#### 25.2.4 I-1 n'est pas opérationnel

I-1 compare l'occupation à « une exécution où les fenêtres inéligibles n'auraient jamais
existé ». Cette exécution de référence n'est **pas constructible** — il n'existe aucun moyen de
faire « comme si » une fenêtre n'existait pas. I-1 doit être remplacé par sa forme opérationnelle,
**I-2** (aucun intervalle d'occupation attributable à un job en `AUCUNE(capacite)`).

#### 25.2.5 A1 est circulaire

A1 (« aucune trame émise au-delà de N ») est vérifié par V2, qui compare `frame_bytes` au
`max_payload_bytes` **fourni par le diagnostic lui-même**. Si le calcul de N est faux, le
scheduler et le diagnostic s'accordent : **le test passe et le comportement est faux**. C'est
exactement le mode de défaillance de 25.2.1.

**Parade obligatoire** : N doit être confronté à une **table régionale codée en dur dans le
test**, indépendante du code sous test.

#### 25.2.6 A4 est vacant par construction

A4 (« capacité et temporel jamais confondus ») est vérifié par I-5 (« tout motif appartient à une
seule famille ») — vrai **par construction** d'une énumération. Ce n'est pas une propriété du
système. La vraie question est : *le code attribue-t-il la bonne famille au bon moment ?*

#### 25.2.7 A5 est ambigu sur entrées / sorties

A5 (« aucune chronologie modifiée ») renvoie à I-3, qui énonce qu'aucun `t_open`, `t_open_rx2` ni
`ready_ns` n'est modifié. Mais la validation **doit** changer `starts` et `fenetres` — c'est son
objet. Lu littéralement, A5 interdirait l'effet recherché. Il faut distinguer
**entrées inchangées** et **sorties pouvant changer**.

#### 25.2.8 D3 est vacant pris isolément

D3 (« sans contention : `rx2 == 0` et `aucune == 0` ») passerait **aussi** si le repli était
entièrement cassé. D3 ne prouve l'absence de contention que s'il **assère en outre**
`rx1 == total`. Et D1/D2/D3 doivent partager la **même graine**, ce que le §24 n'impose que pour
D2.

#### 25.2.9 A9 a une dépendance d'ordre non énoncée

A9 exige que les sept régions exercent le repli. Or **US915 à SF11 est refusé par P1**. A9 est
donc inatteignable tant que la scène US915 n'est pas passée à **SF10**. Cette dépendance
(M2 avant M6) n'est pas écrite dans le critère.

### 25.3 Anomalies de contrat ABI

#### 25.3.1 Le piège du zéro se répète

Le §24.1.4 définit `rx*_max_payload_bytes == 0` comme « aucune contrainte ». C'est **le même
piège que les champs `reserved`** : un appelant qui oublie de remplir le champ obtient
**silencieusement l'absence de validation**. La taille de structure n'y change rien.

**Parade.** Le zéro n'est accepté que dans le cas **explicite** `limits == NULL` (pas de tableau
du tout). Si `limits != NULL`, alors **chaque** entrée doit satisfaire `0 < N ≤ 242`, sous peine
de `InvalidWindowLimits`.

#### 25.3.2 Cohérence des comptes non énoncée

`limits_count` doit être **exactement égal** au `device_count` de la structure v2 embarquée. Un
tableau plus court laisserait certains dispositifs **sans contrainte, sans erreur** — validation
partielle silencieuse.

#### 25.3.3 La structure v2 embarquée doit être re-validée

Le §24.1.4 passe la v2 **par pointeur**. Il faut énoncer que l'entrée v3 **re-valide**
`v2->struct_size` et `v2->abi_version` (qui doit rester **1**), faute de quoi une v2 incohérente
serait acceptée.

#### 25.3.4 Découverte de l'API — mécanisme vérifié, à sanctuariser

Mesuré : les symboles sont déclarés par **attribution directe** au chargement
(`_native.py:527` — `lib.lsim_version.restype = …`). Un symbole absent lève donc **`AttributeError`
à l'import**, avant tout appel : c'est un échec **explicite et précoce**, conforme à l'exigence.

> **Mais cela tient à une habitude d'écriture, pas à un contrat.** La revue doit l'ériger en
> **règle** : *interdiction d'écrire un `hasattr` de repli vers `lsim_plan_downlinks_v2`.*
> Sans cette interdiction, un `getattr(lib, "…_v3", None)` réintroduirait exactement le repli
> silencieux que l'option B a pour objet d'éliminer.

L'échec doit en outre être **typé et actionnable**, pas un `AttributeError` brut.

### 25.4 Les trois notions de version — désambiguïsation

Vérifié : **il n'existe pas de version ABI globale** dans ce projet. Les versions sont **par point
d'entrée** (`LSIM_PLAN_DOWNLINKS_V2_ABI_VERSION`, `LSIM_CAUSAL_ABI_VERSION`,
`LSIM_CLOSED_LOOP_V4_ABI_VERSION`). `lsim_version()` renvoie une version **de bibliothèque**,
distincte.

Trois notions coexistent dans un même appel v3, et elles **peuvent diverger** :

| # | Notion | Valeur | Rôle | Négociable ? |
|---|---|---|---|---|
| 1 | **Nom de point d'entrée** | `lsim_plan_downlinks_v3` | identifie la **forme** de l'interface — **un nom, pas une version** | non |
| 2 | **Version de l'enveloppe** | `v3_args.abi_version = 3` | la **seule** valeur négociée | **oui** |
| 3 | **Version de la charge v2** | `v2_args.abi_version = 1` | figée : la v2 n'évolue plus | non |

> **Règle V-1.** Le suffixe du nom n'est **jamais** une version. Le jour où l'enveloppe v3
> acceptera l'`abi_version` 4, le symbole s'appellera **toujours** `…_v3` : le nom et la valeur
> auront divergé, et c'est attendu.

> **Règle V-2.** Seul `abi_version` fait foi. Toute documentation citant « la version 3 » doit
> préciser **de quelle structure** elle parle.

> **Règle V-3.** Le tableau des correspondances
> (nom ↔ version d'enveloppe ↔ version de charge embarquée) est **publié et testé** : un test
> assert que `v3` accepte 3, refuse 2 et 4, et que la v2 embarquée exige 1.

### 25.5 Corrections — machine à états

```
# §24.4.2 CORRIGE
charge_utile = charge + |FOpts|          # ce qui est comparé à N
fil          = 13 + charge_utile         # PHYPayload, pour l'occupation et l'airtime

rx1_eligible = (trame MAC) ou (charge_utile ≤ N(dr_rx1))
rx2_eligible = rx2_disponible et ((trame MAC) ou (charge_utile ≤ N(dr_rx2)))
```

**Motifs, bornes de décision inchangées** — mais la grandeur comparée change :

| Motif | Condition corrigée |
|---|---|
| `PAYLOAD_TOO_LARGE` | `charge > N` |
| `FOPTS_OVERFLOW` | `charge ≤ N` mais `charge + \|FOpts\| > N` |
| `RX2_CAPACITY` | RX1 échouée et `charge + \|FOpts\| > N(dr_rx2)` |

### 25.6 Traces révisées — C1 à C8

Les traces C1–C4 sont conservées ; quatre sont ajoutées, dont **deux à la frontière** — seules
capables de détecter l'anomalie 25.2.1.

| Trace | Scénario | Attendu | Détecte |
|---|---|---|---|
| **C1** | AU915 SF7, 120 o, repli | `AUCUNE(RX2_CAPACITY)` | repli refusé par capacité |
| **C2** | idem, **20 o** *(était 40 — coïncidence)* | `EMIS_RX2` | repli autorisé |
| **C3** | RX1 N=51, RX2 N=222, 120 o *(limites injectées)* | `EMIS_RX2` — symétrie | R-N1 |
| **C4** | EU868 SF11, 120 o | `AUCUNE(NO_WINDOW_CAPACITY)` | aucune fenêtre |
| **C5** | **frontière** : AU915 RX2, charge **53** = N | `EMIS_RX2` | **anomalie 25.2.1** |
| **C6** | **frontière** : AU915 RX1, charge **222** = N | `EMIS_RX1` | **anomalie 25.2.1** |
| **C7** | charge 220, `\|FOpts\|` = 5 → 225 > 222 | `FOPTS_OVERFLOW` | FOpts consomment l'enveloppe |
| **C8** | trame MAC (`ack`), charge 120, RX2 N=53 | **jamais refusée** | trames MAC hors N |

**C2 passe de 40 à 20 octets** : `13 + 20 = 33 < 53`, sans coïncidence. **C5 et C6 sont les
seules traces qui échoueraient si la règle des 13 octets était fausse.**

C3, non réalisable dans les sept régions, devient testable **par injection de limites** via
`lsim_plan_downlinks_v3` — ce qui est précisément ce que permet le nouveau point d'entrée.

### 25.7 Contrôles révisés — D1 à D5

| # | Exécution | Assertion | Rôle |
|---|---|---|---|
| **D1** | scène saturée, repli actif | `rx2 > 0` **et** `aucune ≥ 0`, **par région** | le repli se produit |
| **D2** | **même graine, même scène**, repli inactif | `aucune(D2) == aucune(D1) + rx2(D1)` | ils avaient **réellement** manqué RX1 |
| **D3** | même graine, terminaux réduits | `rx1 == total`, `rx2 == 0`, `aucune == 0` | absence de contention **prouvée** |
| **D4** | D1 + contrôle de conformité | pour tout `EMIS_RX2` : `charge_utile ≤ N(dr_rx2)` | les replis ne violent pas N |
| **D5** | D1, `repli` actif, `limits` retirés | `rx2 > 0` **et** des émissions au-delà de N | le contrôle démontre sa **sensibilité** |

**D2 acquiert une égalité exacte** — sans elle, `rx2 > 0` pourrait masquer des RX1 jamais tentées.
**D3** reçoit `rx1 == total`, sans quoi il est vacant (25.2.8). **D5 est un méta-contrôle** : il
vérifie que le dispositif détecte bien une violation, faute de quoi D4 ne prouve rien.

### 25.8 Critères révisés — A1 à A12

| # | Critère | Vérifié par | Changement |
|---|---|---|---|
| **A1** | Aucune trame émise au-delà de N | **table régionale codée en dur** | corrige la circularité (25.2.5) |
| **A2** | Aucune fenêtre inéligible réservée | I-2 (I-1 supprimé) | opérationnel (25.2.4) |
| **A3** | Repli légitime jamais supprimé | C2, C5 | C2 recalibrée (25.2.2) |
| **A4** | Bonne famille au bon moment | `WINDOW_MISSED` n'apparaît jamais pour `charge_utile > N` ; `*_CAPACITY` n'apparaît jamais émetteur libre | substitue I-5 (25.2.6) |
| **A5** | **Entrées** inchangées | `t_open`, `t_open_rx2`, `ready_ns` strictement identiques | distingue entrées/sorties (25.2.7) |
| **A6** | Contrats `RunSummary` intacts | `RunSummary` sans `downlink_compliance` valide | inchangé |
| **A7** | Aucun test existant modifié | diff vide sur les tests | inchangé |
| **A8** | Parité Python/C++ | limites passées au C++ **égales** à celles dérivées en Python | ajoute la comparaison des limites |
| **A9** | Sept régions, repli par contention | D1-D3 **après** M2 (US915 → SF10) | dépendance d'ordre explicite (25.2.9) |
| **A10** | Résultats historiques préservés | manifeste + `d315-STATUT.md` | inchangé |
| **A11** | **NOUVEAU** — `0` n'est jamais une validation manquée | `limits != NULL` ⇒ `0 < N ≤ 242` | corrige 25.3.1 |
| **A12** | **NOUVEAU** — absence de repli silencieux | aucun `hasattr` de repli vers v2 ; échec `AttributeError` typé | corrige 25.3.4 |

### 25.9 Méta-tests — la réponse structurée à la vacuité

Chaque test de comportement est doublé d'un **test de sa propre sensibilité** : on introduit la
faute que le test est censé détecter, et on vérifie qu'il **échoue bien**.

| Méta-test | Faute injectée | Le test doit |
|---|---|---|
| **M-A1** | N majoré de 13 (règle fausse) | C5 et C6 **échouent** |
| **M-A2** | `rx2_eligible` forcé à `True` | C1 **échoue** |
| **M-A3** | `rx2_eligible` forcé à `False` | C2 et C5 **échouent** |
| **M-A4** | repli jamais déposé | D2 **échoue** |
| **M-A5** | `condition` utilisé pour l'éligibilité | T-PA6 **échoue** |
| **M-A6** | limites non transmises au C++ | A8 **échoue** |
| **M-A7** | `hasattr` de repli vers v2 | A12 **échoue** |

> **Principe.** Un test qui ne peut pas échouer ne démontre rien. C'est la formalisation du
> garde-fou déjà appliqué au §19 : *ne jamais confondre « vert » et « démontré ».*

### 25.10 Synthèse des corrections à porter au §24

| § | Correction |
|---|---|
| §24.1.4 | `0 < N ≤ 242` si `limits != NULL` ; `limits_count == device_count` ; re-validation de la v2 embarquée |
| §24.4.2 | **`charge + \|FOpts\| ≤ N`**, non `fil ≤ N` |
| §24.4.3 | C2 : 40 → **20 o** ; ajout C5–C8 |
| §24.4.4 | I-1 supprimé au profit de I-2 |
| §24.5.2 | D2 : égalité exacte ; D3 : `rx1 == total` ; ajout D4, D5 ; graine commune |
| §24.6 | A1 dé-circularisé, A4 opérationnalisé, A5 précisé, A11 et A12 ajoutés |
| §24.7 | T-PA2 et T-PA3 inséparables ; T-PA9 comparé à v2 ; T-PA10 mécanisme spécifié |
| nouveau | §25.4 — règles V-1 à V-3 sur les trois notions de version |
| nouveau | §25.9 — méta-tests M-A1 à M-A7 |

### 25.11 Contrat de `limits` — v3 exige ses limites

#### 25.11.1 Le défaut à éliminer

La règle initiale du §24.1.4 (`NULL = aucune contrainte`) **reproduit exactement le défaut que
l'option B devait supprimer** : un nouvel appelant qui oublie de renseigner `limits` obtient une
validation **silencieusement absente**, sans erreur. La taille de structure, la version et le nom
du point d'entrée n'y changent rien — le contournement est dans la **valeur**, pas dans la forme.

#### 25.11.2 Règles

> **L-1 — `limits != NULL` est obligatoire dans v3.** `NULL` entraîne un rejet explicite
> (`MissingWindowLimits`). Il n'existe **aucun** moyen d'appeler v3 sans limites.

> **L-2 — Aucune valeur sentinelle.** Chaque entrée doit satisfaire `0 < N ≤ 242`. Les valeurs
> `0`, `UINT32_MAX` et toute valeur hors plage sont rejetées (`InvalidWindowLimits`). En
> particulier, **zéro n'est pas** « sans contrainte » : c'est une limite invalide.

> **L-3 — `limits_count == device_count`,** à l'identique du dispositif déjà en vigueur pour
> `rx2_count`. Un tableau plus court laisserait des dispositifs sans contrainte, sans erreur.

> **L-4 — L'absence de contrainte est le régime exclusif de v2.** v3 ne la propose jamais. Un
> appelant qui veut le comportement historique **appelle v2**, explicitement.

> **L-5 — Cohérence avec P1.** P1 garantit que le DR montant est résolu (sinon
> `UnsupportedUplinkDataRateError`). Or N dérive du DR. **DR résolu ⇒ N calculable.** Aucune
> situation légitime ne justifie un `limits` absent : la règle n'est donc pas contraignante en
> pratique, elle ne fait que supprimer le mode de défaillance silencieux.

#### 25.11.3 Conséquence assumée

Les scénarios **sans région** — pas de plan, donc pas de N — **ne peuvent pas appeler v3** ; ils
restent en v2. C'est cohérent avec le §22.7, qui les déclare hors du périmètre de la validation
régionale. Sept des neuf fichiers de test employant `downlink_payload_bytes` sont dans ce cas.

| Régime | Point d'entrée | `limits` | Contrainte appliquée |
|---|---|---|---|
| Avec région (N connu) | **v3** | **obligatoire** | **N par fenêtre** |
| Sans région (N inconnu) | v2 | sans objet | borne historique 242 |

#### 25.11.4 Objection traitée — les trames MAC

Les trames `ack`, `mac_answer` et `join_accept` ne sont pas soumises à N. Cela **ne dispense pas**
de fournir `limits` : celui-ci décrit la **capacité de la fenêtre**, toujours connue dès qu'une
région existe. C'est le **planificateur** qui décide, **par type de trame**, si la contrainte
s'applique. La dispense porte sur l'**application** de la limite, jamais sur sa **fourniture**.

#### 25.11.5 Statuts révisés

```
PlanStatus::UnsupportedUplinkDatarate = 4   /* défensif — le cœur ne devrait jamais le voir */
PlanStatus::PayloadTooLarge           = 5
PlanStatus::FoptsOverflow             = 6
PlanStatus::MissingWindowLimits       = 7   /* limits == NULL                              */
PlanStatus::InvalidWindowLimits       = 8   /* limits_count ou valeurs hors plage          */
```

#### 25.11.6 Tests

| # | Cas | Attendu |
|---|---|---|
| **T-L1** | v3, limites valides (`0 < N ≤ 242`, compte exact) | accepté, validation **appliquée** |
| **T-L2** | v3, `limits = NULL` | **rejet `MissingWindowLimits`** |
| **T-L3** | v3, `limits_count ≠ device_count` | rejet `InvalidWindowLimits` |
| **T-L4** | v3, une entrée à `N = 0` | **rejet** — aucune sentinelle |
| **T-L5** | v3, une entrée à `N > 242` | rejet |
| **T-L6** | v2, sans limites | comportement historique, **aucune erreur** |
| **T-L7** | même scène, v2 puis v3, trame > N | résultats **différents** : v2 émet, v3 refuse ⇒ v3 applique bien |
| **T-L8** | limites dérivées en Python vs passées au C++ | **égales** — parité |
| **T-L9** | v3 sur une bibliothèque sans le symbole | échec **explicite au chargement** |

**T-L7 est le test pivot** : sans lui, rien ne distinguerait « v3 applique la contrainte » de
« v3 accepte tout ». **T-L6 garantit** que le régime historique reste accessible — par v2, jamais
par un v3 permissif.

### 25.12 Critères et méta-tests du contrat `limits`

#### 25.12.1 Critères d'acceptation

| # | Critère | Vérifié par |
|---|---|---|
| **A13** | v3 sans `limits` est **toujours** rejeté | T-L2 |
| **A14** | Aucune sentinelle ne peut désactiver la validation dans v3 | T-L4, T-L5 |
| **A15** | L'absence de contrainte n'existe **qu'en v2** | T-L6, T-L7 |
| **A16** | Le **choix du point d'entrée** n'est pas un contournement | §25.12.2, M-A10 |

#### 25.12.2 A16 — la brèche résiduelle

Rendre `limits` obligatoire dans v3 **ne suffit pas** : un appelant disposant d'une région peut
toujours appeler **v2**, qui n'a pas de limites, et perdre la validation **sans erreur**. La
brèche se déplace du *paramètre* vers le *point d'entrée*.

**Fermeture proposée — invariant de la couche de liaison :**

```
si un plan régional existe  -> le pont DOIT appeler v3 avec les limites dérivées
sinon                       -> le pont DOIT appeler v2
```

Cet invariant est **asserté** : pour un scène régional, le pont doit avoir sélectionné v3 ; pour
une scène sans région, v2. Il est vérifiable sans instrumentation invasive, par observation du
point d'entrée effectivement appelé.

#### 25.12.3 Méta-tests

| Méta-test | Faute injectée | Le test doit |
|---|---|---|
| **M-A8** | accepter `limits = NULL` comme « sans contrainte » | **T-L2 échoue** |
| **M-A9** | accepter `N = 0` comme sentinelle | **T-L4 échoue** |
| **M-A10** | le pont appelle v2 même avec une région | **T-L7 et A8 échouent** |
| **M-A11** | ne pas valider `limits_count` | **T-L3 échoue** |
| **M-A12** | v3 tolérant (applique la borne 242 seulement) | **T-L7 échoue** |

### 25.13 Synthèse des corrections à porter au §24

| § | Correction |
|---|---|
| §24.1.4 | `limits` **obligatoire** ; `NULL` rejeté ; `0` rejeté ; `limits_count == device_count` ; re-validation de la v2 embarquée |
| §24.1.5 | statuts : 4, 5, 6 **puis 7 = `MissingWindowLimits`, 8 = `InvalidWindowLimits`** |
| §24.4.2 | **`charge + \|FOpts\| ≤ N`**, non `fil ≤ N` (§25.5) |
| §24.4.3 | C2 : 40 → **20 o** ; ajout C5–C8 |
| §24.4.4 | I-1 supprimé ; **renumérotation** (§26.3) |
| §24.5.2 | D2 : égalité exacte ; D3 : `rx1 == total` ; ajout D4, D5 ; graine commune |
| §24.6 | A1 dé-circularisé, A4 opérationnalisé, A5 précisé, A11–A16 ajoutés |
| §24.7 | T-PA2 et T-PA3 inséparables ; T-PA9 comparé à v2 ; T-PA10 mécanisme spécifié |
| nouveau | §25.4 (V-1 à V-3) · §25.9 (M-A1 à M-A7) · §25.11 (L-1 à L-5) · §25.12 (A13–A16, M-A8 à M-A12) |

---

## 26. Vérification documentaire de cohérence — §23, §24, §25

*Contrôle final : aucune règle contradictoire ne doit subsister, et toute décision remplacée doit
être explicitement identifiée. Vérification fondée sur le texte des sections, non sur la mémoire.*

### 26.1 Méthode

Chaque règle normative est extraite des trois sections et confrontée aux deux autres. Une
divergence est relevée dès lors que **deux énoncés donnent une réponse différente à la même
question**, quand bien même l'un des deux serait ultérieurement corrigé : la traçabilité exige que
la substitution soit **explicite**, pas implicite.

### 26.2 Registre des divergences

| # | Question | §23 | §24 | §25 | Statut |
|---|---|---|---|---|---|
| **1** | Quelle extension ABI ? | **A** recommandée (§23.6.3) | **B** retenue (§24.1.3) | confirmée (§25.3) | ✅ substituée, §24.0 l'identifie |
| **2** | `limits = NULL` en v3 ? | — | aucune contrainte (§24.1.4, l. 2021) | **rejeté** (§25.11, L-1) | ⚠️ **substitution non signalée dans §24.0** |
| **3** | `N = 0` ? | — | aucune contrainte (§24.1.4, l. 2036) | **rejeté** (§25.11, L-2) | ⚠️ **substitution non signalée dans §24.0** |
| **4** | Règle d'éligibilité | `fil ≤ N` (§23.4.2 implicite) | `fil ≤ N` (§24.4.2) | **`charge+\|FOpts\| ≤ N`** (§25.5) | ⚠️ **§23.4.2 non couvert par §24.0** |
| **5** | Que vaut **I-3** ? | somme d'occupation (l. 1717) | `t_open` inchangé (l. 2226) | — | 🔴 **collision de numérotation** |
| **6** | Que vaut **I-4** ? | `t_open` inchangé (l. 1718) | somme d'occupation (l. 2227) | — | 🔴 **collision de numérotation** |
| **7** | I-1 existe-t-il ? | défini (l. 1715) | défini (l. 2224) | **supprimé** (§25.2.4) | 🔴 **suppression non répercutée au §23** |
| **8** | A2 est vérifié par ? | — | « I-1, I-2 » (l. 2304) | « I-2 seul » (l. 2567) | 🔴 **énoncés incompatibles** |
| **9** | Charge maximale D3.15 ? | ≤ 51 (§23.8.2) | ≤ 51 (§24.5.1) | — | ⚠️ **§20 dit 53/129/222** |
| **10** | Statuts C++ | 4, 5, 6 (§23.6.4) | 4, 5, 6, 7 (§24.1.5) | 4…**8** (§25.11.5) | ⚠️ **trois énoncés successifs** |
| **11** | `reserved` réutilisé ? | — | **non** (§24.1.3) | confirmé (§25.3.1) | ✅ cohérent |

**Bilan : 3 divergences bloquantes (🔴), 5 substitutions à signaler (⚠️), 2 points cohérents (✅).**

### 26.3 Résolutions

#### 26.3.1 🔴 Collision I-3 / I-4 — renumérotation

Les invariants des §23.5.2 et §24.4.4 partagent les étiquettes `I-1` à `I-5` avec des **contenus
différents**, et I-3/I-4 sont **permuttés** :

| Étiquette | §23.5.2 | §24.4.4 |
|---|---|---|
| I-1 | occupation identique | occupation identique |
| I-2 | `AUCUNE(RX2_CAPACITY)` sans intervalle | `AUCUNE(famille=capacite)` sans intervalle |
| **I-3** | **somme d'occupation** | **`t_open` inchangé** |
| **I-4** | **`t_open` inchangé`** | **somme d'occupation** |
| I-5 | motif renseigné | famille unique |

**Résolution.** Un **espace de noms unique**, préfixé par la section d'origine :

| Nouveau | Ancien | Énoncé |
|---|---|---|
| **INV-A** | §24 I-2 / §23 I-2 | tout job en `AUCUNE(capacite)` n'a aucun intervalle d'occupation |
| **INV-B** | §24 I-3 / §23 I-4 | aucun `t_open`, `t_open_rx2`, `ready_ns` modifié |
| **INV-C** | §24 I-4 / §23 I-3 | somme des occupations : avec repli ≥ sans repli |
| **INV-D** | §24 I-6 | `fenetres[k] ∈ {None, "rx1", "rx2"}` |
| **INV-E** | §23 I-5 | le motif est renseigné pour tout job en `AUCUNE` |
| ~~I-1~~ | §23 I-1, §24 I-1 | **supprimé** — non opérationnel (§25.2.4) |

#### 26.3.2 🔴 I-1 supprimé, non répercuté

§25.2.4 supprime I-1, mais le §23.5.2 le porte toujours. **Résolution** : I-1 est supprimé dans
les **deux** sections ; les références à « I-1 » dans §23.5.2 et §24.6 sont caduques.

#### 26.3.3 🔴 A2 vérifié par « I-1, I-2 » ou « I-2 »

§24.6 (l. 2304) et §25.8 (l. 2567) donnent des réponses incompatibles. **Résolution** :
**A2 est vérifié par INV-A seul** (ex-I-2), I-1 étant supprimé.

#### 26.3.4 ⚠️ §20 (53/129/222) contre §24.5.1 (≤ 51)

Les deux énoncés sont **compatibles mais non disjoints** dans le texte : le §20 fixe
« une charge ≤ N du DR de **RX1** », le §24.5.1 « une charge ≤ N de **RX2** ». Un lecteur ne peut
pas trancher. **Résolution** — deux familles de scènes, nommées et bornées :

| Famille | Objet | Borne | Source |
|---|---|---|---|
| **S-RX1** | saturation de la fenêtre RX1 | charge ≤ **N(DR de RX1)** — jusqu'à 222 | §20 |
| **S-RX2** | exercice du repli | charge ≤ **N(DR de RX2)** — au plus 53 | §23.8.2, §24.5.1 |

Les deux familles coexistent ; **le repli n'est exigé que dans S-RX2**. Le palier de 51 octets
ne s'applique **qu'à** S-RX2, jamais à l'étude de saturation RX1.

#### 26.3.5 ⚠️ Substitutions à signaler explicitement

Le §24.0 liste ce que le §24 remplace, mais **ne couvre pas** les points 2, 3 et 4 du registre,
introduits ultérieurement par le §25. Le tableau de substitution est complété ci-dessous (§26.4).

### 26.4 Registre consolidé des décisions remplacées

| Décision remplacée | Section d'origine | Remplacée par | Signalée |
|---|---|---|---|
| Option A (champs `reserved`) | §23.6.3 | Option B, §24.1.3 | ✅ §24.0 |
| `abi_version` strict, v2 seule | §23 (implicite) | v3 versionné, §24.1.4 | ✅ §24.0 |
| Exposition de N libre | §23.9 O3 | champ déclaré optionnel, §24.3.3 | ✅ §24.0 |
| Archivage **ou** recalibrage | §23.9 O4 | archivage **et** recalibrage, §24.5 | ✅ §24.0 |
| **`limits = NULL` = sans contrainte** | **§24.1.4** | **rejeté — L-1, §25.11** | ⚠️ **→ §26.4** |
| **`N = 0` = sans contrainte** | **§24.1.4** | **rejeté — L-2, §25.11** | ⚠️ **→ §26.4** |
| **Éligibilité `fil ≤ N`** | **§24.4.2** | **`charge+\|FOpts\| ≤ N` — §25.5** | ⚠️ **→ §26.4** |
| **Invariants I-1 à I-5** | **§23.5.2, §24.4.4** | **INV-A à INV-E — §26.3.1** | ⚠️ **→ §26.4** |
| **Statuts 4, 5, 6, 7** | **§24.1.5** | **4 à 8 — §25.11.5** | ⚠️ **→ §26.4** |
| **A2 vérifié par « I-1, I-2 »** | **§24.6** | **INV-A seul — §26.3.3** | ⚠️ **→ §26.4** |

### 26.5 État de cohérence final

| Contrôle | Résultat |
|---|---|
| Règles normatives en conflit **non résolu** | **0** — les 10 divergences ont une résolution |
| Décisions remplacées **non identifiées** | **0** — registre §26.4 complet |
| Espaces de noms en collision | **0** — I-* → INV-* (§26.3.1) |
| Règles orphelines (énoncées, jamais reprises) | **0** |
| Sections historiques altérées | **0** — §1 à §25 conservés verbatim |

> **Lecture recommandée.** Le §26 ne modifie aucune section antérieure : il les **indexe**. Une
> section historique qui contredit une section plus récente n'est pas une erreur dès lors que la
> substitution est enregistrée ici — c'est la contrepartie assumée du choix de la consolidation
> additive validé au tour précédent.

---

**Aucun code, test, fixture ou scénario n'a été modifié** pour produire les sections §21 à §26,
qui sont des analyses en lecture seule. Seuls les deux fichiers d'I6-b1
(`python/lsim/au915.py`, `python/tests/test_au915.py`) et le présent document diffèrent du
commit `51e7de0`. **Aucun commit, push, rebase, fusion ni déploiement.**

---

## 18. Plan final d'I6-b1

*Établi à la demande : « Présente le plan final des modifications et des tests. » Ce plan
est **soumis à autorisation** ; aucune ligne n'a été écrite à ce jour.*

### 18.1 Confirmation des six critères de validation

| # | Critère | Résultat | Preuve |
|---|---|---|---|
| 1 | La limite résultante de `queue_payload_max` est bien **53** | **CONFIRMÉ** | `min(53, 129, 222, 222, 222, 222) = 53` — mesuré |
| 2 | Le calcul ne modifie pas les limites des autres régions | **CONFIRMÉ** | leurs `rx1_dr` sont inchangés : EU868 51, US915 222, AS923 51, IN865 51, KR920 51, RU864 51 — mesuré |
| 3 | Le contrat public `region_info()` reste compatible | **CONFIRMÉ** | le schéma n'impose que `"type": "integer"` ; `test_api_contract.py:73` n'assert que la non-vacuité |
| 4 | Join-Accept conserve son chemin et ses contraintes propres | **CONFIRMÉ** | aucun appel à `enqueue_downlink` dans `join.py` ; impact d'I6-b1 par le **temps d'antenne** seul (§12.9) |
| 5 | Les tests distinguent M et N | **À FAIRE** | les tests assertent **N** ; la relation M − 8 = N est énoncée une fois, en référence (§18.3, T-B1-10) |
| 6 | Le chemin de trace et le chemin de file restent distingués | **CONFIRMÉ** | deux bornes disjointes : `queue_payload_max` (chemin A) et `242` codé en dur (chemin B) — §12.4 |

### 18.2 Modifications prévues

**Un seul fichier de code : `python/lsim/au915.py`.**

| Ligne | État actuel | État cible | Nature |
|---|---|---|---|
| **45** | `rx1_dr={0: 10, 1: 11, 2: 12, 3: 13, 4: 13, 5: 10, 6: 11}` | `rx1_dr={0: 8, 1: 9, 2: 10, 3: 11, 4: 12, 5: 13, 6: 13}` | **correction normative** |
| **47-48** | `max_frm_payload={… 8: 33, 9: 109, …}` | `max_frm_payload={… 8: 53, 9: 129, …}` | **correction normative** (N = M − 8) |
| **11-13** | docstring citant RP002-1.0.3 avec les valeurs US915 | réécrite : RP002-1.0.5, DR0→DR8 … DR6→DR13 | traçabilité |
| **15-18** | docstring citant RP002-1.0.2, valeurs N erronées, mention « non compatible répéteurs » | réécrite : RP002-1.0.5 table 44, colonnes **compatibles répéteurs**, N = M − 8 | traçabilité |
| **1-22** | en-tête sans traçabilité | en-tête de traçabilité complet (§7) | traçabilité |

**Aucun autre fichier de code n'est modifié.** En particulier : pas de `plan.py`, pas de
`join_store.py`, pas de `uplink.py`, pas de `trace_events.py`, pas de fichier régional autre
qu'AU915, pas de schéma, pas d'ABI.

### 18.3 Tests prévus

**Modifiés** — `python/tests/test_au915.py` :

| # | Test | Assertion actuelle | Assertion cible |
|---|---|---|---|
| **T-B1-1** | `test_au_rx1_data_rate_offset_zero` (7 cas, l. 38-43) | DR0→SF10BW500 … DR6→SF9BW500 | DR0→**SF12BW500**, DR1→**SF11BW500**, DR2→**SF10BW500**, DR3→**SF9BW500**, DR4→**SF8BW500**, DR5→**SF7BW500**, DR6→**SF7BW500** |
| **T-B1-5** | `test_au915_end_to_end_join_ack_and_queue` (l. 64) | `txpk.datr == "SF10BW500"` | `"SF12BW500"` (uplink DR0 → RX1 DR8) |
| **T-B1-6** | `test_au_queue_limit_and_rx2` (l. 52) | `queue_payload_max == 222` | `== 53` |
| **T-B1-11** | fin du test (l. 67-69) | 222 octets acceptés, 223 refusés | **53** octets acceptés, **54** refusés |

**Créés** :

| # | Test | Objet |
|---|---|---|
| **T-B1-2** | `test_au_rx1_preserves_spreading_factor` | à offset 0, SF(RX1) = SF(montant), DR0-DR5 |
| **T-B1-3** | `test_au_rx1_dr_in_downlink_range` | tout DR RX1 ∈ [8, 13] |
| **T-B1-8** | `test_au915_traceability_header` | `au915.py` porte l'en-tête (§7) |
| **T-B1-10** | `test_au_max_payload_table` | **table N complète** AU915, sur le modèle de `test_eu868.py:32` — avec la relation **M − 8 = N** énoncée en commentaire de référence |
| **T-B1-12** | `test_downlink_payload_matches_shared_modulation` | **même modulation ⇒ même N** entre AU915 et US915 pour DR8-DR13 — garde-fou contre la récidive |
| **T-B1-13** | `test_au915_join_accept_airtime_follows_rx1` | le Join-Accept est émis au DR de RX1 du plan (chemin propre, hors file) |

**Préservés intacts** :

| Catégorie | Tests |
|---|---|
| Témoins US915 (5) | `test_plan.py:31`, `test_plan.py:43`, `test_uplink.py:404`, `test_uplink.py:414`, `test_lrfhss_unsupported.py:30` |
| Non-régression des régions (6) | bornes 51/51/51/51/51/222 **inchangées** — `test_eu868.py:33`, `test_as923.py:58`, `test_in865.py:57`, `test_kr920.py:57`, `test_ru864.py:57`, `test_plan.py:51` |
| Fréquence RX1 | `test_au_rx1_channel_is_tx_channel_modulo_8` (l. 46-48) — inchangé |
| Contrat d'API | `test_api_contract.py` |

**Verdict C++** — `T-B1-9` : triple verdict (A) résolveur Python conforme, (B) moteur C++
constaté divergent, (C) parité après I6-c en `xfail` (§9.2).

### 18.4 Ordre d'exécution

1. Modifier `au915.py:45` et `:47-48` (deux corrections indissociables).
2. Réécrire la docstring et l'en-tête de traçabilité.
3. Reprendre les quatre assertions de `test_au915.py`.
4. Créer les six tests nouveaux.
5. Vérifier l'absence de régression : suite C++ (1/1) et Python (2287 réussis, 1 ignoré).
6. Rejouer `d1_i6b1_compare.py` : **45 cas, 0 divergence attendue**.
7. Consigner le changement physique d'occupation RX1 (§10 R8, §12.9).

### 18.5 Commandes de vérification

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DLSIM_WARNINGS_AS_ERRORS=ON
cmake --build build --parallel
ctest --test-dir build --output-on-failure          # attendu : 1/1

pip install "./python[test]"
PYTHONPATH=python LSIM_LIBRARY=<chemin>/liblsim_core.so \
    pytest -q python/tests                          # attendu : 2287 réussis, 1 ignoré
```

### 18.6 Ce qui demeure exclu

| Exclu | Renvoi |
|---|---|
| Offsets 1 à 5 | I6-b2 |
| IN865 DR6 | lot séparé (Q1) |
| Dwell time AS923 | I6-b2 |
| Refonte du contrat de file (option C) | lot distinct (§12.6) |
| Écart de 20 octets sur DR10-DR13 (touche aussi US915) | lot distinct (§12.10.3) |
| Validation DR dans le chemin trace | lacune préexistante, non traitée (§12.4) |
| Divergence Python ↔ moteur C++ | I6-c, après I1 |
