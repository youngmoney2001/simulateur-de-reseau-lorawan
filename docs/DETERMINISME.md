# Déterminisme et identité de trame (jalon U0.2)

Ce document énonce les garanties d'ordonnancement de la boucle fermée, la clé qui les fonde, et
l'identifiant de trame `frame_id`. Il est normatif pour le code : les tests de
`core/tests/test_determinisme.cpp` le vérifient, et chacun est discriminant (démontré par
mutation).

Portée : **la boucle fermée** (`simulate_closed_loop`, `simulate_closed_loop_channels`). Les
autres chemins (planificateur causal, réémissions, arbitre Python) ont leurs propres clés, non
harmonisées à ce jour ; c'est l'objet des étapes U0.3 et suivantes.

---

## 1. Clé de déterminisme

### 1.1 File d'événements

La boucle fermée est menée par une file à priorité. Deux événements y sont comparés par la clé

```
(t, rank, seq)
```

définie par `LoopLater` (`core/src/engine.cpp`) :

| Composante | Rôle | Valeurs |
|:---|:---|:---|
| `t` | instant de l'événement | nanosecondes |
| `rank` | **classe** d'événement, départage les instants égaux | `0` Check/Apply, `1` Start, `2` End |
| `seq` | compteur d'insertion, monotone et unique | entier croissant |

La clé est **totale** : `seq` étant unique, deux événements distincts ne sont jamais égaux. Aucun
événement n'est donc « laissé à l'ordre d'arrivée » de façon implicite.

### 1.2 Justification de l'ordre des rangs

L'ordre `Check/Apply` → `Start` → `End` à instant égal n'est pas arbitraire ; il garantit que
toute lecture faite par un traitement porte sur un état déjà complet.

**`Check` (rang 0) avant `Start` (rang 1).** `Check` résout l'issue radio d'une descente : il lit
`txs[nxt]`, la montante suivante du dispositif, pour décider si celui-ci émettait pendant RX1. Un
`Start` au même instant créerait une montante. Faire passer `Check` d'abord signifie que la
montante démarrant à cet instant **n'est pas encore** dans `txs`, donc n'est **pas** comptée comme
émission du dispositif pendant la fenêtre. C'est la convention des intervalles semi-ouverts
appliquée aux fenêtres : `[ouverture, fermeture)` n'inclut pas la fermeture. Le §3.2 montre que
cette branche est de toute façon inatteignable, donc ce choix est sans effet observé — mais il
est cohérent, et il le reste si les temporisations changent.

**`Start` (rang 1) avant `End` (rang 2).** À un instant donné, toute montante qui *commence* est
enregistrée avant que soit évaluée celle qui *finit*. `End` déclenche `on_received`, donc le
placement de la descente : la montante concurrente doit déjà exister pour que le demi-duplex
soit correct. Sans cet ordre, une descente pourrait être placée en ignorant une montante
démarrant au même instant.

**Pourquoi `seq` en dernier, et non en premier.** C'est le point sur lequel portait la réserve
explicite de l'utilisateur : une clé qui traiterait l'ordre d'insertion avant le temps
provoquerait un traitement prématuré d'un événement futur ; une clé qui l'ignorerait bloquerait
le traitement causal des événements créés pendant une émission. Ici :

- **pas de traitement prématuré** : `t` domine. Un événement créé pendant le traitement d'un
  autre, même s'il porte un `seq` plus petit, ne sera tiré qu'à son propre instant. Le `Check`
  d'une descente est *poussé* pendant `on_received` (à `ta.end`), mais il porte `t = t_open + 1 s`
  et n'est donc tiré qu'à cet instant-là.
- **pas de blocage du traitement causal** : `seq` croît strictement, donc deux événements de même
  `t` et même `rank` sont départagés sans ambiguïté, dans l'ordre de création. Un événement créé
  pendant un traitement et portant le **même** instant et le **même** rang que son créateur est
  traité après lui — ordre causal — sans jamais être différé au-delà de son instant.

### 1.3 Sources de hasard

Le seul tirage aléatoire est le bruit de propagation, `splitmix64(seed ^ …)` indexé par
l'indice de dispositif et le numéro de message. Il est fonction de la graine et d'entiers
déterministes : deux exécutions de mêmes entrées produisent la même suite. Aucun conteneur non
ordonné n'est utilisé dans le moteur ; les tris utilisent `std::stable_sort` ou portent sur des
clés totales.

---

## 2. Ordre des événements de trace à instant égal

### 2.1 Le problème

La trace v3 était ordonnée par `t_ns` seul, avec `std::stable_sort`. L'ordre à instant égal était
donc **l'ordre d'insertion** — une propriété émergente de la place des appels d'émission dans
`on_received`. Déplacer une ligne de code changeait silencieusement l'ordre de la trace.

### 2.2 La solution

La trace est désormais ordonnée par `(t_ns, rang)`, le tri restant **stable** pour départager deux
événements de même rang au même instant par leur ordre de création. Le rang est une fonction
explicite, `loop_trace_rank`, et non une position dans le code.

### 2.3 Table des rangs

| Rang | Événement | Émis par | Justification |
|:---|:---|:---|:---|
| 0 | `downlink` | `Check` | issue radio d'une trame antérieure ; `Check` est traité en premier |
| 1 | `apply` | `Check` | application par le terminal, dans le même traitement |
| 2 | `exclusion` / action `expired` | `on_received` | nettoyage d'état, constaté en entrée de réception |
| 3 | `uplink` | `on_received` | la montante est reçue |
| 4 | `link_adr_ans` | `on_received` | réponse **portée par** cette montante |
| 5 | `exclusion` / `created` ou `renewed` | `on_received` | conséquence d'une réponse négative |
| 6 | `adr_decision` | `on_received` | décision du serveur, postérieure à la réception |
| 7 | `link_adr_req` | `on_received` | requête planifiée dans la descente qui suit |

**La table suit l'ordre de traitement du moteur**, et non un ordre d'affichage commode. Elle est
donc cohérente avec les rangs de la file (`kLoopRankCheck` 0 < `kLoopRankStart` 1 <
`kLoopRankEnd` 2) : un `Check` et un `End` de même instant sont traités dans cet ordre, et la
trace le rapporte.

Cet ordre a été **dérivé** de l'observation de la trace réelle, et non repris de l'ordre
initialement proposé pour le contrat d'événements U0 (`uplink_received`, `downlink_requested`, …),
qui ne correspondait à aucune classe existante dans le code. Vérifié sur une scène produisant les
sept classes : `uplink → link_adr_ans → exclusion → adr_decision`.

**Un piège a été évité, et il vaut d'être consigné.** Une première version de cette table plaçait
`downlink` et `apply` en fin de table, au motif qu'ils se rapportent à une trame antérieure. C'est
séduisant du point de vue de la lisibilité, mais **faux** : `Check` étant traité avant `End`, la
trace se serait mise à contredire l'ordre de traitement. Le point de rencontre a été construit
(`close` d'une trame == `fin` d'une montante d'un autre dispositif) et a effectivement montré une
inversion de la trace par rapport à l'avant-U0.2. La table corrigée rétablit l'ordre d'origine.

### 2.4 Stabilité et portée actuelle du rang

La table épouse l'ordre de traitement, et l'insertion se fait dans cet ordre : **rang et ordre
d'insertion coïncident donc aujourd'hui**. La trace produite est inchangée (vérifié : les 14
scènes de référence de U0.1 sont identiques au bit près, et le point de rencontre `Check`/`End`
donne le même ordre qu'avant le jalon).

Deux conséquences, à ne pas surinterpréter :

- **Aucun test ne peut aujourd'hui distinguer** un tri par `(t_ns, rang)` d'un tri stable par
  `t_ns` seul : ils produisent le même résultat par construction. Le comparateur
  `loop_trace_before` est donc testé **isolément**
  (`test_s9_2_le_comparateur_fait_primer_le_rang`), faute de scène discriminante.
- Le rang devient **porteur** dès que des classes d'événements seront émises dans un ordre
  différent de leur ordre de traitement — c'est precisément l'objet du contrat d'événements
  prévu à l'étape U0.3 (`downlink_requested`, `downlink_scheduled`, `downlink_emitted`,
  `downlink_missed`). La présente table devra alors être complétée, et l'ordre retenu pour ces
  nouvelles classes **démontré**, pas supposé.

---

## 3. Intervalles semi-ouverts

Toutes les fenêtres et toutes les occupations sont des intervalles **semi-ouverts** `[début, fin)`.
Deux intervalles se chevauchent si et seulement si `a.start < b.end && b.start < a.end`. En
particulier, `a.end == b.start` **n'est pas** un chevauchement.

### 3.1 Libération d'une occupation à l'ouverture exacte d'une fenêtre

C'est le cas signalé explicitement comme à vérifier. Soit une émission de descente occupant
`[T, T + air)`, et une fenêtre RX1 s'ouvrant à `T + air` : **la fenêtre est libre**. À
`T + air - 1`, elle est occupée.

Cette propriété est vérifiée à trois niveaux :

1. **Composant** (`test_radio_scheduler.cpp`) : `transmitting` sur les contacts exacts, de part
   et d'autre.
2. **Moteur** (`test_s9_3_bascule_exactement_a_la_libereration_de_l_occupation`) : deux
   dispositifs dont les montantes sont décalées de `air` (respectivement `air - 1`) ; la seconde
   descente part en RX1 (respectivement bascule en RX2).
3. **Balayage de la frontière** (`test_s9_3_balayage_de_la_frontiere`) : l'écart est balayé de
   `air - 4` à `air + 4` nanosecondes ; la bascule RX1 → RX2 doit survenir **exactement** à
   `air`. Une erreur d'une unité dans la convention (borne incluse au lieu d'excluse) déplace la
   bascule d'une nanoseconde et fait échouer le test.

### 3.2 Le dispositif émet-il pendant RX1 ? — branche inatteignable

`device_missed` est vrai si le dispositif émet avant la fermeture de RX1, soit
`txs[nxt].start < close` avec `close = fin + 1 s (RX1) + 1 s (fenêtre) = fin + 2 s`.

Or TS001 §3.3.6 interdit toute émission avant la réception en RX1/RX2 ou l'expiration de RX2, et
le moteur l'applique : le départ suivant est repoussé à `fin + 2 s (RX2) + 1 s (fenêtre) =
fin + 3 s`. Ce plancher est **strictement postérieur** à `close`.

**Conséquence : la branche est structurellement inatteignable.** Mesuré : 48 descentes produites
sur des périodes de 50 ms à 3 s, zéro `device_missed`. Les tests existants n'assertent d'ailleurs
jamais que `device_missed` est vrai (`test_closed_loop.cpp` l.264, l.1393, l.1438).

Caractérisation, **pas** preuve de conformité : c'est un comportement de code. Il devra être
réexaminé à l'étape U0.4, où RX2 devient paramétrable — si la durée de RX2 devient inférieure à
`close - (fin + 2 s)`, la branche redevient atteignable.

---

## 4. Identifiant de trame `frame_id`

### 4.1 Définition

`frame_id` est un `std::uint32_t` attribué à une trame descendante **au moment de sa demande**
(c'est-à-dire dans `on_received`, quand le serveur décide de répondre à une montante).

Propriétés garanties :

| Propriété | Énoncé |
|:---|:---|
| Attribution unique | un `frame_id` par trame, aucun doublon |
| Monotonie | croissant dans l'ordre des demandes |
| Stabilité | jamais réattribué, jamais renuméroté, indépendant de tout tri |
| Valeur d'absence | `kLoopNoIndex` (0xFFFFFFFF) pour un événement sans trame |
| Reproductibilité | deux exécutions identiques produisent les mêmes `frame_id` |

### 4.2 Ce que `frame_id` n'est pas

Il ne remplace aucun identifiant existant :

- `LoopDownlink::uplink` reste l'indice de la montante **déclencheur** ;
- l'indice dans `LoopResult::downlinks` reste une **position** ;
- `LoopTraceEvent::seq` (côté Python) reste un numéro d'ordre **positionnel**, réattribué après
  tri — c'est précisément pourquoi un identifiant stable était nécessaire.

`frame_id` identifie la **trame**, c'est-à-dire ce qui est émis, indépendamment de ce qui l'a
déclenchée et de la place qu'elle occupe.

### 4.3 Dispositions mémoire

`frame_id` est placé dans le **bourrage** des deux structures internes. Les tailles et tous les
décalages existants sont **inchangés** :

| Structure | Taille avant | Taille après | Emplacement de `frame_id` |
|:---|:---|:---|:---|
| `LoopDownlink` | 48 | 48 | décalage 12 (bourrage 11-15) |
| `LoopTraceEvent` | 40 | 40 | décalage 36 (bourrage 36-39) |

Vérifié par les `static_assert` du harnais de dispositions et par une sonde de décalages
(`offsetof`) exécutée avant et après le jalon.

### 4.4 Frontière C : non exposé, et pourquoi

`frame_id` **n'est pas** exposé dans l'ABI C (`lsim_loop_downlink`, `lsim_loop_trace_v3`).

Motif : ces deux structures ont été mesurées, et l'ajout du champ n'est pas neutre partout.

- Sur **x86-64**, `lsim_loop_downlink` passerait de 48 à 48 octets : le champ tiendrait dans le
  bourrage aux décalages 12-15, tous les décalages existants conservés.
- Sur **i386**, en revanche, `int64_t` n'y est aligné que sur 4 octets. Insérer un `uint32_t`
  après `commands` pousse `t_open_ns` du décalage 12 au décalage 16, et la taille de **40 à 44
  octets**. Vérifié par `static_assert` compilé en `-m32`.

C'est une rupture d'ABI 32 bits, incompatible avec la consigne de préserver les ABI existantes.
L'exposition de `frame_id` est donc reportée à une **extension d'enveloppe** (du type de
`lsim_causal_args` v2), qui permettra d'ajouter le champ sans toucher aux structures publiées.

Conséquence assumée : `frame_id` est aujourd'hui **interne au moteur**. Il est utilisable et
testé en C++, et il est prêt pour le contrat d'événements de l'étape U0.3, mais il n'est pas
encore visible depuis Python.

### 4.5 Égalité des événements

`LoopTraceEvent::operator==` **ne compare pas** `frame_id`. C'est un choix délibéré :
l'opérateur compare le **contenu protocolaire** observable, et `frame_id` est un handle de
corrélation. Deux événements de même contenu pour la même trame sont égaux — ce qui est le
comportement attendu par les tests existants, préservés sans modification.

---

## 5. Garanties et limites

### Garanties apportées

| Garantie | Vérification |
|:---|:---|
| Mêmes entrées + même graine ⇒ même trace, au bit près | `test_s9_1_reproductibilite_meme_entrees_meme_graine` |
| Ordre à instant égal défini par une table, non par le code | `test_s9_2_table_des_rangs`, `test_s9_2_ordre_de_la_trace_respecte_le_rang` |
| Intervalles semi-ouverts, bascule à la nanoseconde | `test_s9_3_*` (balayage de frontière) |
| Événements simultanés arbitrairement et reproductiblement | `test_s9_4_deux_montantes_terminant_au_meme_instant` |
| Causalité réception → décision → émission → issue | `test_s9_5_la_descente_est_resolue_apres_la_reception` |
| Événements créés pendant un traitement, ordonnés causalement | `test_s9_6_ordre_causal_des_evenements_d_une_meme_trame` |
| `frame_id` unique, monotone, stable, reproduit | `test_frame_id_*` |
| Tailles et décalages ABI inchangés | harnais `abi_layout.cpp`, 101 symboles exportés |

### Limites — à ne pas lire comme des garanties

1. **Portée.** Ce document ne couvre que la boucle fermée. Le chemin causal, les réémissions et
   l'arbitre Python ont d'autres clés, non harmonisées (U0.3).
2. **Rangs 6 et 7.** Convention, non exigence normative (§2.3).
3. **`device_missed`.** Branche inatteignable, caractérisée et non prouvée conforme (§3.2).
4. **`frame_id` non exposé.** Invisible depuis Python (§4.4).
5. **Reproductibilité ≠ validité.** Deux exécutions identiques prouvent le déterminisme, **pas** la
   fidélité du modèle au comportement réel.
6. **Un seul émetteur.** L'occupation est unique ; le multi-passerelles (U0.5) introduira une
   occupation par passerelle, et ce document devra être étendu.
7. **La stabilité du tri n'est pas démontrée par un test.** C'est la seule mutation du jalon que
   la suite ne détecte pas : remplacer `std::stable_sort` par `std::sort` laisse les 689 874
   vérifications passer. La raison est connue et mesurée — le plus grand groupe d'égalités
   `(t_ns, rang)` atteignable est de **6** événements (six montantes simultanées de SF distincts ;
   deux montantes de même SF se terminant au même instant se chevaucheraient et seraient en
   collision). En dessous du seuil de 16 éléments, l'introsort de la bibliothèque standard se
   réduit à un tri par insertion, qui est stable : la mutation est donc inoffensive **dans les
   faits**, mais rien ne la détecterait si elle cessait de l'être. La fermeture de cette lacune
   suppose un champ d'ordre de création dans `LoopTraceEvent`, ce qui demande une extension
   d'enveloppe (même motif que §4.4).

### Mutations du jalon

Chaque propriété a été révoquée une à une, la suite reconstruite et rejouée :

| Mutation révoquant… | Échecs détectés |
|:---|:---|
| **M1** — deux rangs de la table (`Downlink` ⇄ `Uplink`) | **6** |
| **M2** — le rang dans le comparateur (tri par temps seul) | **2** |
| **M3** — `std::stable_sort` remplacé par `std::sort` | **0 — non détecté** (limite 7) |
| **M4** — la monotonie de `frame_id` (identifiants réattribués) | **269** |
| **M5** — la propagation de `frame_id` aux événements de trace | **122** |
| **M6** — la convention semi-ouverte (borne de fin inclusive) | **4** |

Restauration vérifiée par SHA-256 sur les trois fichiers mutés, et rejeu à 689 874/689 874.
