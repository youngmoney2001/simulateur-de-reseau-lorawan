# RP002-1.0.5 — relevé direct et correction d'une erreur de référence

Objet : clore, autant que possible, la lacune notée à plusieurs reprises dans cette session —
« la table 44 de RP002-1.0.5 n'a jamais été lue directement ».

## 1. Ce qui bloquait, et pourquoi c'est levé

Cinq méthodes avaient échoué et la consigne « ne pas retenter » était en vigueur. La cause est
trouvée : **l'URL utilisée n'était plus la bonne**.

    ancienne : lora-alliance.org/wp-content/uploads/2025/10/RP002-1.0.5.pdf   -> 404
    actuelle : resources.lora-alliance.org/technical-specifications/
                 rp002-1-0-5-lorawan-regional-parameters

La page courante expose un lien de téléchargement direct (`content.cdntwrk.com/...`), qui
fournit **le document complet** : 127 pages, 11 chunks, contre une version tronquée qui
plafonnait vers la page 31. Le blocage n'était donc pas un défaut du parseur mais une
mauvaise adresse.

## 2. Correction : la table 44 n'était pas celle que je croyais

C'est le résultat le plus utile de ce relevé, et il invalide des heures de recherche.

D'après la **liste des tables** du document (lue directement) :

| Numéro | Titre | Page |
|---|---|---|
| Table 44 | AU915-928 **maximum payload size** (repeater compatible) | 61 |
| Tableau recherché | AU915-928 **downlink RX1 data rate mapping** | **62** |

La cartographie RX1 de l'AU915 est la **table 46**, pas la 44. Je poursuivais un mauvais
numéro depuis le début de la mission.

Les cartographies RX1, par région :

| Région | Table | Page |
|---|---|---|
| EU863-870 | 17 | 38 |
| US902-928 | 26 | 46 |
| EU433 | 38 | 54 |
| AU915-928 | 46 | 62 |
| CN470-510 | 56 | 71 |
| AS923 (DownlinkDwellTime = 0 / = 1) | 74 / 75 | 81 |
| KR920-923 | 87 | 87 |
| IN865-868 | 98 | 93 |
| RU864-870 | 109 | 100 |

## 3. Ce qui a pu être lu directement

Le parseur s'arrête à **30 pages** (limite de l'outil, vérifiée : le dernier chunk se termine
au §3.3.1). Sont donc accessibles les pages 1 à 30, qui couvrent les tables de synthèse
1 à 7 et les réglages par défaut. Les cartographies RX1 (pages 38 à 100) restent **hors
d'atteinte**.

### 3.1 Table 5 — Global data rate summary (p. 27) — **la pièce utile**

C'est elle qui donne la correspondance DR ↔ (SF, bande), et c'est elle dont I5-a avait besoin.
Extraits, lus directement :

| GDR | Modulation | Paramètres | EU868 | US915-UL | US915-DL | AU915-UL | AU915-DL |
|---|---|---|---|---|---|---|---|
| 0x12 | LoRa | SF10, 125 kHz | DR2 | DR0 | | DR2 | |
| 0x13 | LoRa | SF9, 125 kHz | DR3 | DR1 | | DR3 | |
| 0x14 | LoRa | SF8, 125 kHz | DR4 | DR2 | | DR4 | |
| 0x15 | LoRa | SF7, 125 kHz | DR5 | DR3 | | DR5 | |
| 0x30 | LoRa | SF12, 500 kHz | | | **DR8** | | **DR8** |
| 0x31 | LoRa | SF11, 500 kHz | | | **DR9** | | **DR9** |
| 0x32 | LoRa | SF10, 500 kHz | | | **DR10** | | **DR10** |
| 0x33 | LoRa | SF9, 500 kHz | | | **DR11** | | **DR11** |
| 0x34 | LoRa | SF8, 500 kHz | | DR4 | **DR12** | DR6 | **DR12** |
| 0x35 | LoRa | SF7, 500 kHz | | | **DR13** | | **DR13** |

**Ce que cela confirme, et qui fonde I5-a** : les DR descendants DR8 à DR13 de l'US915 et de
l'AU915 sont **SF12 à SF7 à 500 kHz**. Les descentes de ces deux régions se font donc bien à
500 kHz, jamais à 125 kHz. C'est la cause du facteur 4,00x mesuré dans I5-a.

### 3.2 Table 4 — Fixed channel plan summary (p. 26)

| Paramètre | US915 | AU915 |
|---|---|---|
| Canaux descendants | 8 × 500 kHz (923,3 → 927,5 MHz) | idem |
| DR obligatoires | montant [0:4], **descendant [8:13]** | montant [0:6], **descendant [8:13]** |
| RX1DRoffset par défaut | 0 | 0 |
| RX1DRoffset autorisé | **[0:3]** | **[0:5]** |
| RX2DataRate par défaut | **DR8** | **DR8** |
| Fréquence RX2 par défaut | 923,3 MHz | 923,3 MHz |

### 3.3 Table 3 — Dynamic channel plan summary (p. 25)

| Plan | EU868 | AS923-1 | KR920 | IN865 | RU864 |
|---|---|---|---|---|---|
| RX2 par défaut | 869,525 MHz | 923,2 MHz | 921,90 MHz | 866,550 MHz | 869,1 MHz |
| RX2DataRate par défaut | (DR0) | DR2 | DR0 | DR2 | DR0 |
| RX1DRoffset autorisé | [0:5] ou [0:7] | [0:7] | [0:5] | [0:5] | [0:5] |

**Réserve sur cette extraction** : l'alignement des colonnes du tableau Markdown est
incertain pour la ligne « RX1DRoffset autorisé ». Les valeurs ci-dessus sont donc
**indicatives**, contrairement à celles des §3.1 et §3.2 dont la structure était non ambiguë.

### 3.4 §3.3 — Default Settings (p. 29)

`RECEIVE_DELAY1 = 1 s` · `RECEIVE_DELAY2 = 2 s` · **`RX1DROffset = 0`** ·
`JOIN_ACCEPT_DELAY1 = 5 s` · `DownlinkDwellTime = 0`.

## 4. Ce qui reste non lu, et ce que cela interdit

Les **cartographies RX1 (tables 17, 26, 46, 74, 75, 87, 98, 109)** n'ont pas pu être lues :
elles sont au-delà de la limite de 30 pages.

Conséquence, à retenir pour la suite :

- Une divergence a été observée entre la table RX1 de l'AU915 **telle qu'extraite de
  RP002-1.0.2** (DR0 → DR10, c'est-à-dire SF12 → SF10) et le profil Python du simulateur
  (`plan.rx1(0, …)` → `SF12BW500`, c'est-à-dire DR8). Les deux ne peuvent pas avoir raison.
- **Il n'est pas tranché ici.** L'extrait 1.0.2 provient d'une extraction bruitée, la table 46
  de la 1.0.5 n'a pas pu être lue, et une divergence de ce type relève d'un lot distinct
  (audit des profils régionaux), pas d'une correction de moteur.
- Aucune conclusion n'est donc tirée sur la **valeur** que doit prendre un `rx1_sf` régional.
  En revanche, la question « le moteur doit-il utiliser la valeur qu'on lui donne ? » est
  indépendante de ce débat, et c'est elle que traite `docs/I5_B_RX1_SF_BOUCLE_FERMEE.md`.

## 5. Bilan de la lacune

| Point | Avant | Après |
|---|---|---|
| Accès au document | impossible (5 échecs) | **ouvert** — URL corrigée, 127 pages |
| Table 44 | jamais lue | **lue** : c'est une table de charge utile, pas une cartographie RX1 |
| DR descendant ↔ (SF, bande) | déduit | **lu directement** (table 5, p. 27) |
| Descentes US915/AU915 à 500 kHz | inféré de sources tierces | **confirmé par le document normatif** |
| Cartographies RX1 par région | non lues | **toujours non lues** (au-delà de 30 pages) |
