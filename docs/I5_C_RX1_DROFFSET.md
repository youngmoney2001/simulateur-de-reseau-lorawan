# I5-c — Lacune RP002 : état des lieux et fermeture de l'écart RX1DROffset

**Objet.** Lever la réserve « aucune affirmation régionale » ouverte par l'audit I5, laquelle
tenait à l'impossibilité de lire les tables de mapping RX1 de RP002-1.0.5 (tables 17, 26, 46, …).

**Résultat, en deux phrases.** Le contenu RX1 du serveur est **conforme** à RP002 — 0 écart
sur 7 régions, vérifié par l'exécution. L'écart n'est pas dans les valeurs mais dans la
**dimension** de la table : elle est indicée par le seul DR montant, alors que RP002 exige
`(DR montant, RX1DROffset)`.

---

## 1. Méthode, et ce qui n'a pas pu être lu

Le PDF RP002-1.0.5 est hébergé hors de la liste d'accès réseau de cet environnement, et le
parseur de pages plafonne à 30 pages sur un document de 127 : les tables 17 (EU863-870, p. 38),
26 (US902-928, p. 46) et 46 (AU915-928, p. 62) restent **non lues directement**.

Ce qui a été obtenu à la place, par des accès autorisés (`github.com`, `codeload.github.com`) :

| Source | Nature | Apport |
|---|---|---|
| **RP002-1.0.5**, table 5 | lue **directement** (tranche 51) | DR → (SF, bande) EU868 / US915 / AU915 |
| **LoRaMac-node v4.7.1** (Lora-net) | transcription, implantable de référence | `DatarateOffsetsUS915[5][4]`, `DatarateOffsetsAU915[7][6]`, `DatarateOffsetsCN470[8][6]` |
| **lorawan-stack v3.37.0** (TTI) | transcription, **un fichier par version RP002** | `*_rp2_v1_0_4.go` : `DataRates` et `Rx1DataRate` des 10 régions |

**Les deux transcriptions concordent exactement** sur US915 et AU915, les seules régions à
mapping tabulaire — ce sont donc deux relevés indépendants, pas une copie. Elles concordent
aussi avec la table 5 lue directement.

> **Réserve conservée.** La chaîne de preuve est « deux transcriptions indépendantes + une
> lecture directe partielle », non « lecture directe des tables 17/26/46 ». La confiance est
> haute ; ce n'est pas une citation de la norme. Toute affirmation ci-dessous qui dépend de
> ces tables le rappelle.

---

## 2. Résultat : conformité à RX1DROffset = 0

`tools/verifier_rx1_rp002.py` confronte, pour chaque région, la table DR → (SF, bande) et le
mapping RX1 du serveur aux valeurs RP002-1.0.4 relevées ci-dessus.

```
région  DR montants                            RX1 (offset 0)                 verdict
EU868   DR0=SF12/125 … DR6=SF7/250             0→0 1→1 2→2 3→3 4→4 5→5 6→6    CONFORME
US915   DR0=SF10/125 … DR4=SF8/500             0→10 1→11 2→12 3→13 4→13       CONFORME
AU915   DR0=SF12/125 … DR6=SF8/500             0→8 1→9 2→10 3→11 4→12 5→13 6→13 CONFORME
AS923   DR0=SF12/125 … DR6=SF7/250             0→0 … 6→6                      CONFORME
IN865   DR0=SF12/125 … DR5=SF7/125             0→0 … 5→5                      CONFORME
KR920   DR0=SF12/125 … DR5=SF7/125             0→0 … 5→5                      CONFORME
RU864   DR0=SF12/125 … DR6=SF7/250             0→0 … 6→6                      CONFORME
0 écart(s)
```

**Corollaire important pour I5-b.** La propriété « `plan.rx1()` ne change jamais le SF »,
relevée comme suspecte en tranche 51, n'est **pas** une lacune : à offset 0, le mapping RP002
préserve réellement le SF dans les 7 régions. Pour US915, DR10..DR13 valent SF10..SF7 à 500 kHz,
et DR0..DR3 valent SF10..SF7 à 125 kHz — le bloc descendant est construit pour que le SF
suive. Le SF est conservé, seule la bande change. L'hypothèse d'I5-b était donc doublement
fausse, et le lot a été clos sur ce constat (`docs/I5_B_RX1_SF_BOUCLE_FERMEE.md` §12).

---

## 3. L'écart : la table RX1 est à une dimension

`Plan.rx1(tx_dr, tx_ch)` (`plan.py:101`) lit `self._rx1_dr[tx_dr]` — un `Mapping[int, int]`
**plat**, DR montant → DR RX1. RP002 définit une table à **deux** entrées :
`(DR montant, RX1DROffset) → DR RX1`.

Les sept modules régionaux le disent d'ailleurs explicitement, par exemple `as923.py:9` :
« Ce serveur fixe RX1DROffset à 0 ». Il s'agit donc d'une **limite assumée et documentée**,
non d'une erreur — mais d'une limite qui n'est pas anodine (§5).

Bornes d'offset par région (RP002-1.0.4) : US915 **0..3** ; AU915 **0..5** ; EU868, EU433,
KR920, RU864, IN865, AS923 **0..5**. Au-delà, la valeur est hors spécification.

Forme du mapping, telle qu'implantée par les deux sources :

- **Régions tabulaires (US915, AU915)** : `table[dr][offset]`, reproduite en §7.
- **Régions arithmétiques (EU868, EU433, KR920, RU864, IN865, AS923)** :
  `RX1_DR = clamp(DR_montant − offset, DR_min, DR_max)` avec `DR_max` = 7 partout sauf KR920
  (5), et `DR_min` = 0, sauf AS923 avec `DownLinkDwellTime = 1` où `DR_min` = 2.

---

## 4. Le serveur n'émet jamais `RXParamSetupReq` — rectification

> **Ce chapitre remplace une affirmation erronée.** Une version précédente décrivait
> `RXParamSetupReq` comme une commande qu'un terminal négocierait et que le serveur
> acquitterait sans l'appliquer. **C'est faux, et l'erreur est de direction.**

`RXParamSetupReq` (CID 0x05) est une commande **descendante** : c'est le serveur qui la
construit pour régler le terminal, et le terminal répond par `RXParamSetupAns` (montante).
Les sources du dépôt sont sans ambiguïté :

- `core/include/lsim/mac_commands.hpp:105` — « RXParamSetupReq **(down)** »
- `core/include/lsim/mac_commands.hpp:266-267` — `decode(...Req) // down`,
  `decode(...Ans) // up`
- `core/include/lsim/c_api.h:655-656` — `REQ /* down */`, `ANS /* up */`

Or **le serveur n'émet jamais cette commande**. Vérifié : aucune occurrence de
`RxParamSetupReq` hors du codec (`mac.py`, `_native.py`, `mac_commands.cpp`,
`c_api_mac.cpp`), et la seule commande MAC effectivement émise est `LinkADRReq`
(CID 0x03, `uplink.py:57`).

**Conséquence, corrigée.** Il n'existe aucun chemin par lequel un terminal pourrait se voir
appliquer un RX1DROffset non nul — non pas parce qu'un réglage serait ignoré, mais parce
que **rien ne le produit jamais**. Le codec est complet et validé (encodage
`mac_commands.cpp:130`, décodage `:371`, acquittement `:140`, validation `mac.py:190`) ; ce
qui manque n'est pas l'application d'une valeur reçue, c'est **l'émission de la commande**.

Ce n'est donc pas une réponse protocolaire inexacte au sens de **bbb3**. C'est une
fonctionnalité absente, et la distance à parcourir est plus grande qu'estimé : il ne suffit
pas de propager une valeur, il faut décider qui la fixe.

**Conséquence sur le périmètre.** L'option « complet » retenue en §9 reposait sur la
prémisse, désormais infirmée, qu'un offset négocié existait à propager. Voir §9.1.

---

## 5. Quantification

`tools/quantifier_offset_rx1.py` compare, pour chaque région, DR montant et offset non nul,
le (SF, bande) exigé par RP002 à celui produit par le serveur, avec le rapport de temps
d'émission correspondant (proportionnel à `2^SF / BW`).

| Région | Cas | Exigé | Produit | Rapport |
|---|---|---|---|---|
| EU868 | DR5, offset 5 | DR0 = SF12/125 | DR5 = SF7/125 | **32,00x** |
| US915 | DR3, offset 3 | DR10 = SF10/500 | DR13 = SF7/500 | **8,00x** |
| AU915 | DR5, offset 5 | DR8 = SF12/500 | DR13 = SF7/500 | **32,00x** |
| AS923 | DR6, offset 5 | DR1 = SF11/125 | DR6 = SF7/250 | **32,00x** |
| IN865 | DR5, offset 5 | DR0 = SF12/125 | DR5 = SF7/125 | **32,00x** |
| KR920 | DR5, offset 5 | DR0 = SF12/125 | DR5 = SF7/125 | **32,00x** |
| RU864 | DR6, offset 5 | DR2 = SF10/125 | DR6 = SF7/250 | **32,00x** |

**Rapport maximal : 32,00x.** Le serveur sous-estime la fenêtre RX1 d'un facteur pouvant
atteindre 32 — l'inverse d'I5-a, qui la sous-estimait d'un facteur 4, mais sur la même
grandeur physique. Un créneau RX1 réputé libre peut être occupé en réalité, et réciproquement.

---

## 6. Périmètre de la correction proposée

**Retenu**

1. Table RX1 à deux dimensions, par région : `rx1_dr` devient `(dr, offset) → dr`.
2. `Plan.rx1(tx_dr, tx_ch, rx1_dr_offset = 0)` — paramètre **optionnel**, valeur par défaut 0,
   pour ne casser aucun appelant existant (parité Python/C++, **zz4**).
3. Refus explicite d'un offset hors bornes pour la région (arbitrage **bbb3**) : `ValueError`
   nommant la région et la borne, jamais de saturation silencieuse.
4. Propagation de l'offset négocié : le `rx1_dr_offset` issu de `RXParamSetupReq` doit
   atteindre le calcul RX1, faute de quoi l'acquittement reste inexact (§4).
5. Harmonisation des références documentaires : `plan.py` cite RP002-1.0.2 avec « la table RX1
   RP002-1.0.1 », `au915.py` cite RP002-1.0.5, `us915.py` et `ru864.py` ne citent rien.

**Hors périmètre**, à documenter comme limites connues :

- **FSK (DR7)** — EU868, AS923, IN865, RU864. Non atteignable en RX1 depuis un DR montant
  (le DR montant maximal est DR6), donc sans effet mesurable aujourd'hui.
- **LR-FHSS** — DR8..DR11 (EU868), DR5/DR6 (US915), DR7 (AU915). Modulation ajoutée par
  RP002-1.0.4, distincte de LoRa ; le simulateur est LoRa-seul.
- **`DownLinkDwellTime = 1` (AS923)** — relève le débit minimal à DR2. Déjà documenté
  (`as923.py:17`) ; restera non modélisé sauf décision contraire.
- **CN470** — région non supportée par le serveur.

---

## 7. Conception

### 7.1 Forme de la table

Le constructeur de `Plan` prend aujourd'hui `rx1_dr: Mapping[int, int]`. Deux options :

- **(A) table imbriquée** : `rx1_dr: Mapping[int, Sequence[int]]`, `rx1_dr[dr][offset]`.
  Une valeur par (dr, offset), y compris quand la règle est arithmétique.
- **(B) table creuse + règle** : conserver `Mapping[int, int]` pour l'offset 0 et ajouter un
  appelable `rx1_dr_at(dr, offset)`, la région choisissant table ou `clamp`.

**(A) est retenue** : les valeurs sont alors toutes dans les modules régionaux, lisibles
d'un coup d'œil et vérifiables ligne à ligne contre la norme — c'est le critère qui compte
pour un document de conformité. Le coût est la répétition pour les régions arithmétiques
(6 offsets × 6 DR), acceptable à cette échelle.

### 7.2 Tables à transcrire

US915 (`DatarateOffsetsUS915[5][4]`, offsets 0..3) — identique dans LoRaMac-node et
lorawan-stack :

```
        off0  off1  off2  off3
DR0  ->  10    9     8     8
DR1  ->  11    10    9     8
DR2  ->  12    11    10    9
DR3  ->  13    12    11    10
DR4  ->  13    13    12    11
```

AU915 (`DatarateOffsetsAU915[7][6]`, offsets 0..5) — identique dans les deux sources ;
la colonne 0 (`8,9,10,11,12,13,13`) avait déjà été corroborée en tranche 48 :

```
        off0 off1 off2 off3 off4 off5
DR0  ->  8    8    8    8    8    8
DR1  ->  9    8    8    8    8    8
DR2  ->  10   9    8    8    8    8
DR3  ->  11   10   9    8    8    8
DR4  ->  12   11   10   9    8    8
DR5  ->  13   12   11   10   9    8
DR6  ->  13   13   12   11   10   9
```

EU868, RU864, EU433, AS923, IN865 : `clamp(dr − offset, 0, 7)`.
KR920 : `clamp(dr − offset, 0, 5)`.

### 7.3 Propagation de l'offset

Trois appelants de `plan.rx1()` : `uplink.py:163`, `gwmp_server.py:62`,
`trace_events.py:314`. Il faut déterminer, pour chacun, d'où vient l'offset du terminal :
état MAC par dispositif, ou valeur régionale par défaut. **Ce point n'est pas tranché** et
conditionne l'ampleur du changement (§9).

---

## 8. Tests

- **T-C-1** — non-régression : tous les appels existants (offset par défaut 0) produisent des
  résultats **bit à bit identiques**. C'est la propriété centrale : la correction ajoute une
  dimension, elle n'en modifie aucune.
- **T-C-2** — parité : les 7 régions × tous les (DR, offset) valides, comparés aux valeurs
  transcrites en §7.2. Doit rester vert ; c'est le test qui détecterait une transcription
  fautive.
- **T-C-3** — refus : offset hors bornes (US915 offset 4 ; KR920 offset 6 ; valeur 7) ⇒
  `ValueError` nommant la région et la borne. **Contrôle positif** exigé : le même offset
  dans les bornes doit réussir (leçon §11.5 d'I5-a).
- **T-C-4** — effet physique : pour un (région, DR, offset) choisi, l'airtime RX1 mesuré doit
  correspondre au SF et à la bande exigés — pas seulement au DR. Reprendre le piège d'I5-b :
  un test qui ne vérifie que le DR peut passer alors que le SF est faux.
- **T-C-5** — `RXParamSetupReq` : un terminal qui négocie un offset non nul doit voir ses
  descentes RX1 calculées avec cet offset. Test de bout en bout, pas de table seule.
- **T-C-6** — mutation : altérer une valeur de `rx1_dr` doit faire échouer T-C-2 **et** T-C-4.

---

## 9. Questions ouvertes

1. **Qui fixe l'offset ? (§4, rectifié)** — question rouverte, la prémisse initiale étant
   infirmée. Le serveur n'émettant jamais `RXParamSetupReq`, rien ne produit de valeur non
   nulle. Trois voies, d'ampleur très différente :
   - **(a) Réglage de déploiement** — l'offset devient un paramètre de scénario, par
     dispositif ou par groupe. Court, rend l'offset réellement simulable, mais le terminal
     n'est pas notifié par la voie MAC normale.
   - **(b) Émission de `RXParamSetupReq`** — le serveur origine la commande, suit
     `RxParamSetupAns` et applique l'offset une fois acquitté. Conforme à la norme, mais
     c'est une fonctionnalité MAC entière (origine, suivi d'acquittement, persistance).
   - **(c) Rien de plus** — la table à deux dimensions reste disponible (§6) sans qu'aucun
     chemin ne produise d'offset non nul, documenté comme tel.

   L'état de session pour porter l'offset est en place (`join_store.py` : colonne
   `rx1_dr_offset`, migration, `set_rx1_dr_offset`) ; il reste à choisir ce qui l'alimente.
2. **`DownLinkDwellTime` (AS923)** : le relever passe le `DR_min` de 0 à 2. Le modèle-t-on,
   ou documente-t-on seulement ?
3. **Référence de version** : les valeurs étant désormais vérifiées conformes à 1.0.4/1.0.5,
   faut-il harmoniser toutes les citations sur RP002-1.0.5, ou conserver la version
   effectivement consultée région par région ?
4. **LR-FHSS** : documenter comme limite, ou ouvrir un lot distinct ?
