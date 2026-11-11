# Consolidation du modèle MAC — incrément 1

Ce document décrit ce que le simulateur modélise réellement de la MAC LoRaWAN, comment les
notions voisines sont séparées, et ce qui reste hors périmètre. Il ne remplace pas la
`CONFORMANCE_MATRIX.md` : il précise les décisions prises pour l'ACK, les compteurs de trame et
les classes d'écoute, avec les tests qui les tiennent.

Périmètre de cet incrément : `lsim.ack_mac`, `lsim.retransmissions`, le bloc `retransmissions:` du
scénario et la trace produite par `build_trace`. **Le cœur C++ et l'ABI ne sont pas modifiés.**

## 1. Identité de trame et compteurs

| Notion | Portée | Où elle vit | Sémantique |
|---|---|---|---|
| `FCntUp` | une trame de terminal | `Attempt.f_cnt_up`, `AckFrame.frame_counter_up` | incrémenté par **nouvelle** trame ; toutes les réémissions d'une trame partagent la valeur |
| `FCntDown` | un terminal, **deux séries** (1.1) | `AckEmission.f_cnt_down`, `AckFrame.frame_counter_down`, `AckOutcome.series` | `NFCntDown` pour une trame sans charge utile (ACK seul), `AFCntDown` sinon ; un ACK émis consomme un numéro de sa série, ses copies gardent le même |
| contrôle de rejeu | un terminal, par série | `lsim.fcnt.CounterSeries` | le champ **16 bits** est replacé dans la série 32 bits ; un ACK n'est retenu que si le compteur reconstruit est **strictement supérieur** au dernier accepté, et à moins de `MAX_FCNT_GAP` de lui |

Conséquences vérifiées par `python/tests/test_mac_consolidation.py` :

- `fcnt_up_start: 1000` sur un scénario à deux messages donne les trames `1000` et `1001`, et les
  ACK portent `(1000, 0)` puis `(1001, 1)` — l'identité ne dépend plus d'un rang de tableau ;
- deux terminaux ont chacun leur série descendante : `[0, 1]` pour l'un, `[0, 1]` pour l'autre ;
- `AckFrame.is_explicit` devient vrai : l'appariement dispose de `FCntUp`, il n'a plus besoin de la
  seule fenêtre.

**Sémantique de référence** : celle de `lsim.session.DeviceSession` (`begin_uplink` → `fcnt32`,
`receive_downlink` → contrôle de rejeu). Ces compteurs ne sont pas un second modèle : le module les
transporte dans la trace, avec les mêmes règles.

Ces trois mécanismes sont détaillés en §7, les jointures en §8. Ce qui reste hors périmètre : la
reconstruction depuis un **journal de paquets réels** (le simulateur tient les 32 bits en mémoire) et
la cryptographie des jointures — le simulateur ordonne les sessions, il ne déchiffre pas un
`Join-Accept`.

## 2. Taxonomie de l'ACK

Chaque **émission** reçoit exactement une classe (`AckSort`) ; les compteurs agrègent ces classes
sans recouvrement.

| Classe | Définition | Effet sur la trame |
|---|---|---|
| `STANDARD` | émise dans une fenêtre écoutée (RX1, RX2, ou écoute continue en classe C), décodable, `FCntDown` inédit | acquittée |
| `LATE` | émise après la fermeture des fenêtres | non acquittée ; l'airtime est consommée et la passerelle occupée |
| `LOST` | émise dans une fenêtre écoutée mais non décodable, ou terminal en train d'émettre | non acquittée |
| `DUPLICATE` | champ 16 bits identique à celui d'un ACK déjà accepté par ce terminal | ignorée : le rejeu est rejeté par le compteur, pas par une règle propre à l'ACK |
| `GAP` | reçue et décodable, mais à plus de `MAX_FCNT_GAP` du dernier accepté | rejetée : désynchronisation, la série n'avance pas |
| `NOT_SENT` | aucun ACK : l'uplink n'a pas été reçu, ou la série descendante est épuisée (2^32) | aucune |

`AckPlan.counts` donne les six totaux ; `RetransmissionResult` les expose en `ack_standard`,
`ack_late`, `ack_lost`, `ack_duplicate`, `ack_gap`, `ack_not_sent`. Un test vérifie que
`standard + late + lost + duplicate + gap == acks_planned` pour les trois configurations de
référence. `GAP` n'apparaît dans aucun scénario livré : sur les exemples, la copie d'un ACK est un
`DUPLICATE` (champ identique), jamais un saut de 65 536 — un test construit le vérifie.

Le détail de réception reste disponible séparément (`AckWindow` : `RX1`, `RX2`, `CONTINUOUS`,
`LATE`, `NOT_DECODABLE`, `WINDOW_MISSED`, `NOT_SENT`). Une seule conversion est lossy et elle est
documentée : `LATE` et `GAP` sont rangés avec les pertes de sensibilité dans `DownlinkDelivery`, qui
n'a pas de verdict « hors fenêtre » ni « rejeté par le compteur ».

## 3. Classes d'écoute A, B, C

| Classe | Règle d'écoute appliquée à l'ACK | Ce qui n'est pas modélisé |
|---|---|---|
| A | RX1 (`fin + 1 s`, 1 s) puis RX2 (`fin + 2 s`, 1 s) | — |
| B | identique à A : l'ACK est une descente de classe A | les *ping slots* (balise, périodicité, dérive) — autre mécanisme, `core/include/lsim/class_b.hpp` |
| C | écoute continue après l'uplink, sauf pendant ses propres transmissions | `CLASS_C_RESP_TIMEOUT` côté réseau, bascule A → C |

Mesure sur `docs/exemples/retransmissions_ack_tardif.yaml` (`ack_delay_ms: 2500`), mêmes graines :

| Classe | Transmissions | ACK émis | `standard` | `late` | Reçus | Livrées |
|---|---|---|---|---|---|---|
| A | 6 | 6 | 0 | 6 | 0 | 0/2 |
| B | 6 | 6 | 0 | 6 | 0 | 0/2 |
| C | 2 | 2 | 2 | 0 | 2 | 2/2 |

La classe ne déplace aucune émission initiale : les couples `(instant de début, instant de fin)`
des premières tentatives sont identiques dans les trois cas, et seules les réémissions (donc la
réception de l'ACK) diffèrent. C'est la boucle de bout en bout, pas une fuite de la règle d'écoute
dans la radio.

## 3 bis. Pourquoi la classe B se comporte comme A

Ce n'est pas une approximation : c'est une conséquence du modèle de descente, et il vaut mieux
l'énoncer que laisser croire à un chantier inachevé.

**Toutes les descentes du moteur sont déclenchées par un uplink.** L'ACK d'une trame confirmée, la
charge utile de `downlink_every`, le `LinkCheckAns`, le `DevStatusAns` : chacune est la réponse à
une trame montante, planifiée dans RX1 ou RX2. Or **une descente déclenchée par un uplink tombe
toujours dans RX1 ou RX2** par construction — il n'y a rien à rattraper. Un ping slot ne sert donc
à rien ici : il ne peut que recevoir par hasard une descente que le réseau n'a pas mise à son
heure, ce qui arrive environ une fois sur trente en périodicité 0 (un slot de 30 ms toutes les
0,96 s) et une fois sur quatre mille en périodicité 7.

**Le ping slot est un mécanisme d'ordonnancement, pas une écoute opportuniste.** Le réseau *garde*
la descente et l'émet au prochain ping slot du terminal ; il n'émet pas au hasard en espérant
qu'une fenêtre soit ouverte. C'est ce que calcule `core/src/downlink.cpp`
(`lsim::lorawan::downlink::next_class_b`) et ce qu'expose `lsim.simulator.DownlinkRequests`.

Faire différer la classe B demande donc **des descentes à l'initiative du réseau** : une demande
née à un instant que le terminal n'a pas choisi. La latence devient alors la grandeur qui
distingue les trois classes — A attend le prochain uplink du terminal (jusqu'à une période), B
attend le prochain ping slot (0,96 s en périodicité 0, 128 s en périodicité 7), C émet presque
aussitôt. C'est la mesure que le simulateur ne sait pas encore produire, et c'est elle qui rendrait
le choix d'une classe dans l'atelier autre chose qu'un libellé.

Le moteur, lui, est prêt des deux côtés :

| Question | Fonction | Disponible |
|---|---|---|
| quand le réseau peut-il émettre ? | `next_ping_slot` (`core/src/class_b.cpp`, `ClassBDevice.next_ping_slot`) | oui |
| le terminal écoute-t-il à cet instant ? | `ping_slot_at` (idem, `ClassBDevice.ping_slot_at`), fenêtre = 30 ms élargie de la dérive | oui, ajouté pour cela |
| combien de temps jusqu'à la prochaine fenêtre ? | `next_class_a` / `next_class_b` / `next_class_c` (`core/src/downlink.cpp`) | oui |

Hypothèse commune aux trois, inchangée : la passerelle émet une balise à chaque période de 128 s
depuis l'origine du run et le terminal la reçoit. Le mode *beacon-less* n'est pas déclenché.

## 4. Cohérence planificateur / moteur causal / réémissions / traces

| Élément | État |
|---|---|
| Occupation passerelle | les intervalles d'ACK **émis par la couche MAC** sont imposés au moteur : les pertes montantes qu'ils provoquent sont réelles, et la trace les contient (`gateway_tx`) |
| Résultat de réémission | `acks_planned` = nombre d'émissions réelles (copies incluses), pas le nombre de réponses logiques |
| Compteurs de trace | `ack_standard` / `late` / `lost` / `duplicate` / `gap` proviennent du même plan que les émissions |
| Événements de trace | un `ProtocolEvent` de type `ack` par émission réelle de la couche MAC, aux mêmes instants que `gateway_tx`, avec les issues du contrat d'API (voir 4.1) |
| Appariement | inchangé sur le chemin du cœur (`_match_ack` par fenêtre RX1) ; la couche MAC utilise `FCntUp` |

Un test vérifie que six ACK tardifs donnent six intervalles d'occupation (`gateway_tx`), donc que la
trace ne cache pas l'airtime consommée ; un second vérifie qu'ils donnent aussi six événements
`ack` (`python/tests/test_mac_trace_events.py`).

### 4.1 Les ACK de la couche MAC dans la trace

`_mac_ack_events` (`python/lsim/retransmissions.py`) convertit chaque émission réelle du plan MAC en
`ProtocolEvent` de type `ack`. Le point de départ n'est pas le planificateur du cœur mais
`AckEmission` : instants, nombre de copies et verdict appartiennent donc au **même** plan que
`gateway_tx` et que les compteurs `ack_standard` / `ack_late` / `ack_lost` / `ack_duplicate`.

| Classe du plan (`AckSort`) | Situation | `ProtocolEvent.outcome` | `Hop.outcome` (passerelle → terminal) |
|---|---|---|---|
| `STANDARD` | reçue dans une fenêtre écoutée, `FCntDown` inédit | `ack_only` | `delivered` |
| `LATE` | émise après la fermeture des fenêtres | `not_listened` | `not_listened` |
| `LOST` (fenêtre manquée) | terminal en émission au moment de l'ouverture | `device_transmitting` | `not_listened` |
| `LOST` (non décodable) | dans une fenêtre, sous la sensibilité du récepteur | `lost_sensitivity` | `lost_sensitivity` |
| `DUPLICATE` | copie reçue puis rejetée par le contrôle de rejeu | `suppressed` | `delivered` |
| `NOT_SENT` | uplink non reçu : rien n'est émis | aucun événement | — |

`suppressed` est déjà employé par les doublons de maillage ; `not_listened` et
`device_transmitting` par l'appariement du cœur. **Aucune valeur nouvelle n'entre dans `EventKind`
ni dans `HopOutcome`** (contrat `lsim.api_contract`, schémas `schemas/api/v1` inchangés) : un
`ack_only` reste la seule issue d'un ACK effectivement reçu.

Propriétés tenues par les tests (`python/tests/test_mac_trace_events.py`, 7 tests) :

- une émission ↔ un événement : `len([e for e in events if e.kind == "ack"]) == acks_planned`, et
  chaque `t_ns` est un début d'intervalle de `gateway_tx` ;
- ordre stable `(t_ns, device_index, copie)` puis `seq` renumérotée comme sur tout le chemin, avec
  les indices virtuels ramenés aux terminaux du scénario par `_build_trace_retransmissions` ;
- la trace reste triée par `t_ns` et toutes les issues appartiennent au contrat ;
- sans couche MAC (`ack_delay_ms: 0`), les événements restent ceux de `plan_native` : deux ACK
  `ack_only` pour deux trames, aucun doublon d'événement.

## 5. Commandes MAC déjà disponibles

Inventaire **vérifié** par `python/tests/test_mac_commands_inventory.py` : les 31 commandes du
codec (`python/lsim/mac.py`, cœur `core/src/mac_commands.cpp`) sont codées, décodées dans le bon
sens et retombent sur leurs champs. Le test échoue si une commande est ajoutée sans ligne dans son
tableau.

| Famille | Commandes | Application dans le projet |
|---|---|---|
| ADR | `LinkAdrReq/Ans`, `AdrParamSetupReq/Ans` | LinkADRReq appliqué par `lsim.mac_loop` (boucle fermée) ; ADRParamSetup : codec seul |
| Duty cycle | `DutyCycleReq/Ans` | appliqué par `lsim.mac_loop` (réduction uniquement) |
| Diagnostic | `LinkCheckReq/Ans`, `DevStatusReq/Ans` | `LinkCheckReq` réservé par `lsim.mac_plan` ; `DevStatusReq` placé dans la descente ; `DevStatusAns` réservé |
| Temps | `DeviceTimeReq/Ans` | `DeviceTimeReq` réservé par `mac_loop` |
| Fenêtres | `RxParamSetupReq/Ans`, `RxTimingSetupReq/Ans`, `DlChannelReq/Ans` | codec seul |
| Canaux | `NewChannelReq/Ans` | codec seul (les canaux viennent du plan régional) |
| Rejoignure | `ForceRejoinReq`, `RejoinParamSetupReq/Ans` | codec seul |
| Classe B | `PingSlotInfoReq/Ans`, `PingSlotChannelReq/Ans`, `BeaconFreqReq/Ans` | codec seul ; moteur de classe B séparé (`core/src/class_b.cpp`) |
| Clés | `RekeyInd/Conf` | codec + `lsim.rekey` (machine Pending → Confirmed) |

« Codec seul » signifie : encodage/décodage validés, **aucun effet simulé**. C'est une limite
explicite, pas un oubli.

Ce qui est réellement vérifié : `python/tests/test_mac.py` (20 tests) couvre les octets sur l'air, les
bornes, les bits RFU et le décodage d'un flux mixte ; `python/tests/test_mac_commands_inventory.py`
(4 tests) vérifie l'inventaire complet dans les deux sens ; `python/tests/test_mac_loop.py` couvre
LinkADR et DutyCycle dans la boucle fermée. Les autres commandes n'ont **pas** de test d'effet,
puisqu'elles n'en ont pas.

## 6. Ce qui reste à faire

1. **Compteurs d'une session réelle** : reconstruction depuis un journal de paquets réels (le
   simulateur tient les 32 bits en mémoire) et jointure effectivement simulée — `plan_acks` sait
   déjà recevoir un numéro de session et `DeviceCounters.renew_session()` remet les trois séries à
   zéro, mais aucun scénario ne déclenche de `Join-Accept` dans cette couche.
2. Brancher la classe C sur le moteur d'opportunités existant (`lsim.simulator.DownlinkRequests`)
   au lieu de la règle locale d'écoute continue.
3. **Pourquoi la classe B se comporte comme A, et ce qui la ferait différer** : voir §3 bis.
   Ce n'est pas un oubli : c'est une conséquence du modèle de descente.
4. Appliquer les commandes aujourd'hui « codec seul » une par une, avec leurs tests de
   comportement, en commençant par `RxParamSetupReq` (elle change RX2, donc la réception de l'ACK).

## 7. Compteurs complets : rejeu, désynchronisation, débordement

Les primitives vivent dans `python/lsim/fcnt.py` ; la couche ACK les applique, le cœur C++ garde sa
propre logique (`core/src/session.cpp`, inchangé). Chaque règle est marquée **standard** ou
**hypothèse** : c'est la distinction qui empêche de lire ce tableau comme une conformité.

| Mécanisme | Règle appliquée | Statut | Test |
|---|---|---|---|
| reconstruction 16 → 32 bits | plus petit candidat strictement supérieur au dernier accepté ; champ identique = doublon | standard (champ `FCnt` de 16 bits) | `test_the_sixteen_bit_field_wraps_once` |
| rejeu | compteur ≤ dernier accepté → `REPLAY`, série inchangée | standard | `test_a_consumed_counter_is_a_replay` |
| désynchronisation | écart > 16 384 → `GAP`, série inchangée | **hypothèse** : `MAX_FCNT_GAP` est la valeur ≤ 1.0.3, **retirée de 1.0.4 et suivants** (RP002) ; appliquée ici comme politique de rejeu explicite | `test_the_gap_boundary_is_the_specification_value` |
| débordement | série épuisée à 2^32 → `EXHAUSTED`, aucun ACK numéroté ; la nouvelle jointure n'est pas simulée | standard pour la limite, hors périmètre pour la jointure | `test_a_series_ends_at_two_to_the_thirty_two`, `test_an_exhausted_series_emits_no_ack` |
| séries descendantes | `NFCntDown` / `AFCntDown` indépendantes, même départ de session | 1.1 ; en 1.0.x une seule série, la couche n'utilise que `NFCntDown` | `test_the_two_downlink_series_do_not_move_together` |
| réémission | même `FCntUp` pour toutes les tentatives d'une trame ; chaque ACK émis consomme un nouveau `FCntDown` | standard | `test_a_retransmission_consumes_a_new_downlink_counter` |
| descente applicative | `downlink_payload: true` : la trame porte une charge utile (`data_ack`), elle consomme `AFCntDown` | standard (une trame à charge utile avance `AFCntDown`) | `test_a_downlink_with_payload_consumes_afcnt` |
| sessions | deux sessions d'un même terminal ont des séries indépendantes ; la session 1 n'hérite pas des compteurs de la session 0 | standard (les compteurs repartent de zéro au `Join-Accept`) | `test_a_new_session_restarts_both_counters`, `test_a_second_session_does_not_inherit_the_first` |

**Correction apportée par cet incrément.** Dans le chemin des réémissions, chaque tentative était
représentée par un terminal virtuel : les compteurs descendants étaient donc clés par *transmission*
et non par *terminal*, et deux trames d'un même terminal recevaient le même `FCntDown` — la seconde
étant acceptée parce que sa série était neuve. `plan_acks` reçoit désormais le terminal physique
(`devices=`), et les séries sont par terminal. Les mesures publiées ne changent pas (6 ACK tardifs ;
2 `STANDARD` + 2 `DUPLICATE` ; classe C : 2 `STANDARD`), mais le compteur lu sur le cas « deux
copies » passe de `[0, 0]` à `[0, 1]`.

**Séries et sessions, mesurées.** `NFCntDown` et `AFCntDown` sont exercées de bout en bout, sur le
même scénario de référence à deux trames (classe C) :

| Réglage | Événement de trace | Série | `FCntDown` lu |
|---|---|---|---|
| défaut (ACK seul) | `ack_only` | `NF` | `[0, 1]` |
| `downlink_payload: true` | `data_ack` | `AF` | `[0, 1]` |
| `fcnt_down_start: 100` | `ack_only` | `NF` | `[100, 101]` |

Les deux séries partent du même compteur de session mais avancent séparément
(`test_the_two_series_are_counted_separately`). Une nouvelle session repart de zéro : le compteur 0
de la session 1 n'est pas un rejeu de celui de la session 0 (`sessions=` dans `plan_acks`). **Ce
qui a changé depuis** : une jointure déclarée dans le scénario (`session_joins_s`) crée cette
nouvelle session — voir §8.

**Limite de mesure, à ne pas masquer** : `GAP` n'est produit par **aucun scénario livré**. La copie
d'un ACK porte le même champ 16 bits : c'est un `DUPLICATE`, jamais un saut de 65 536. La
désynchronisation n'est vérifiée qu'au niveau des primitives (`CounterSeries`) et du plan, jamais de
bout en bout dans une trace.

## 8. Sessions et jointures

Une **session** commence à un `Join-Accept` accepté et se termine au suivant. Elle porte trois
conséquences, toutes appliquées par le même objet (`lsim.sessions.SessionTimeline`) :

| Conséquence | Où elle se voit | Vérification |
|---|---|---|
| les compteurs repartent de zéro | `Attempt.f_cnt_up` et `Attempt.f_cnt_down` sont numérotés par `(terminal, session)` | `test_counters_restart_at_each_session` |
| une trame de l'ancienne session n'est plus reçue | réémission supprimée, `RetransmissionResult.rejected_stale_session` l'incrémente | `test_a_stale_frame_is_not_retransmitted` |
| un `Join-Accept` rejoué n'ouvre rien | `SessionTimeline.accept` lève `JoinRejected` | `test_a_replayed_join_is_rejected` |

### 8.1 Ce qu'un scénario déclare

`session_joins_s` liste les instants (en secondes) des `Join-Accept` **acceptés**. Les nonces sont
déduits de l'ordre (0, 1, 2, …) : c'est la seule grandeur que le simulateur utilise, puisque la
cryptographie n'est pas modélisée. Le champ est validé (entiers, strictement croissants) et **absent
du hash** quand il est vide : un scénario écrit avant lui garde son empreinte.

| Numéro de session | Signification |
|---|---|
| `0` | session ouverte avant le scénario (aucune jointure déclarée, ou trame antérieure à la première) |
| `1`, `2`, … | sessions ouvertes par les jointures déclarées, dans l'ordre |

```yaml
retransmissions:
  retries: 2
  ack_delay_ms: 2500
  session_joins_s: [5]      # un Join-Accept accepté à 5 s
```

### 8.2 Jointures dans la trace

Chaque jointure déclarée produit **deux événements par terminal**, avec le vocabulaire du contrat
existant (`EventKind.join_request`, `EventKind.join_accept`) :

| Événement | Instant | Sens du saut |
|---|---|---|
| `join_request` | `Join-Accept − JOIN_ACCEPT_DELAY1` (5 s), borné à 0 | terminal → `gw:0` |
| `join_accept` | l'instant déclaré | `gw:0` → terminal, sur `RX1` |

`JOIN_ACCEPT_DELAY1` est la constante de la spécification (`lsim.gwmp_server`), pas une invention du
simulateur. Aucune trame n'est modélisée dans l'intervalle : le `Join-Request` n'occupe pas la
passerelle, et le `Join-Accept` ne consomme aucun compteur. Pour un échange réellement transporté
(temps de vol, collisions, fenêtres), voir §9.

### 8.3 Mesures de bout en bout

Scénario `docs/exemples/retransmissions_ack_tardif.yaml`, `retries: 2`, `ack_delay_ms: 2500`,
deux messages (`(session, début en s, tentative)`) :

| Réglage | Transmissions | `rejected_stale_session` | ACK émis |
|---|---|---|---|
| témoin, sans jointure | `(0,1,0) (0,4,1) (0,7,2) (0,61,0) (0,64,1) (0,67,2)` | 0 | 6 |
| `session_joins_s: [5]` | `(0,1,0) (0,4,1) (1,61,0) (1,64,1) (1,67,2)` | **2** | 5 |

La jointure à 5 s rend périmées la tentative prévue à 7 s **et** la suivante : la trame de la
session 0 s'arrête à sa deuxième émission, et le réseau n'émet pas d'ACK pour une trame qu'il ne
sait plus déchiffrer. Le compteur de trames reste celui du scénario ; seule la réémission disparaît.

Redémarrage des compteurs, scénario à trois messages et `session_joins_s: [0, 40]` :

| Session | Trame | `FCntUp` | `FCntDown` |
|---|---|---|---|
| 1 | 0 | 0 | 0 |
| 2 | 0 | 0 | 0 |
| 2 | 1 | 1 | 1 |

La trame de rang 0 de la session 2 porte le compteur 0, comme celle de la session 1 : deux séries
distinctes, pas un rejeu.

### 8.4 Ce qui n'est pas modélisé

- **Ni cryptographie ni `JoinNonce` réel** : le nonce est un rang, pas un compteur réseau vérifié
  contre une clé. Un `Join-Accept` rejoué est refusé parce que son rang n'avance pas, pas parce que
  son `MIC` est faux.
- **Pas de `Join-Request` dans le moteur radio** dans ce modèle **déclaré** : l'échange n'occupe
  pas la passerelle et ne subit pas de collision. Le modèle **radio** correspondant est décrit en §9
  (`join_requests_s`) : c'est lui qu'il faut utiliser pour éprouver les pertes et les collisions.
- **Pas de rejoint (LoRaWAN 1.1)** : `rejoin_request` / `rejoin_accept` ne sont pas distingués des
  jointures ; une trame ne peut pas migrer d'une session à l'autre avec des compteurs conservés.

## 9. Jointure OTAA dans le moteur radio

`join_requests_s` remplace le modèle **déclaré** de §8 par un échange réellement transporté : le
Join-Request est une émission uplink, le Join-Accept une descente. Une session n'est ouverte que si
l'échange aboutit (`python/lsim/join.py`).

| Étape | Modélisé | Non modélisé |
|---|---|---|
| Join-Request | 23 octets (`lsim_encode_join_request`), temps de vol, collisions, sensibilité, couverture, placement causal | `DevNonce`, `DevEUI`, `MIC` : aucun octet n'est construit ni vérifié |
| Join-Accept | 33 octets, émis en **RX1** (`JOIN_ACCEPT_DELAY1`, 5 s) ; **RX2** (6 s) n'est émise que si RX1 n'a pas abouti | occupation de la passerelle par les ACK, temps de vol des autres descentes, CFList |
| Session | ouverte si un Join-Accept est **reçu** et si son `JoinNonce` dépasse le dernier accepté | dérivation de clés, chiffrement, rejoint 1.1 |

### 9.1 Ce que le moteur décide

| Situation | Fenêtres émises | Session |
|---|---|---|
| tout passe | RX1 seule, `delivered` | ouverte à la fin de RX1 |
| RX1 non écoutée (terminal en émission) | RX1 `not_listened` **puis** RX2 `delivered` | ouverte à la fin de RX2 |
| RX1 sous la sensibilité | RX1 `lost_sensitivity` **puis** RX2, même issue | ouverte seulement si RX2 passe |
| RX1 et RX2 perdues | RX1 puis RX2, toutes deux perdues | aucune |
| requête perdue | aucune émission | aucune |
| deux Join-Request simultanés | aucune émission | aucune |
| Join-Accept rejoué (`join_accept_replays`) | RX1 `delivered` **puis** réémission `replayed` | une seule, le rejeu est refusé |

**RX2 est une fenêtre de secours, pas une seconde copie.** Si RX1 est reçue, aucune émission RX2
n'a lieu (`join_accept_rx2_fallback: false` supprime même la possibilité de secours). Le rejeu est
un mécanisme distinct : c'est une réémission du **même** Join-Accept, que le terminal reçoit et
refuse parce que son `JoinNonce` n'avance pas (`SessionTimeline.accept`) ; elle est comptée dans
`JoinAttempt.accept_replays` et apparaît en trace comme `suppressed`.

`JoinNonce` est un **rang attribué par le simulateur**, pas une valeur dérivée d'une clé.

### 9.2 Mesures

Scénario `docs/exemples/retransmissions_ack_tardif.yaml`, `ack_delay_ms: 0`, un Join-Request à 10 s :

| Réglage | Fenêtres | Sessions des trames |
|---|---|---|
| terminal à 100 m | RX1 `delivered` (15,45 s), pas de RX2 | 0 puis 1, `FCntUp` 0 puis 0 |
| terminal à 20 km | aucune émission (requête perdue) | 0 seulement, `FCntUp` 0 et 1 |
| 9 km, récepteur dégradé de 10 dB | RX1 puis RX2, `lost_sensitivity` | 0 seulement |
| trame de 51 octets en SF12 couvrant RX1 (requête à 56 s) | RX1 `not_listened` (62,48 s), RX2 `delivered` (63,48 s) | 0 puis 1 |
| deux terminaux au même point | aucune émission (collision) | 0 seulement |
| deux terminaux à 100 m et 300 m, `join_retries: 2` | RX1 `delivered` ×2 | 0 puis 1 par terminal |
| `join_accept_replays: 1` | RX1 `delivered` puis 1 rejeu refusé | une seule session |

### 9.3 Trace

Chaque tentative produit un événement `join_request` à son instant réel, avec l'issue du moteur
(`received`, `lost_collision`, `lost_sensitivity`). Le `join_accept` apparaît **une fois par émission
réellement faite** : un seul événement si RX1 a abouti, deux si RX2 a servi de secours, plus un
événement `suppressed` par rejeu reçu. L'instant de l'événement identifie la fenêtre
(`fin de la requête + 5 s` pour RX1, `+ 6 s` pour RX2). Aucune valeur nouvelle au contrat : ces
issues existent déjà dans `HopOutcome`.

### 9.4 Limites explicites

- **Aucune cryptographie** : ni clé, ni `MIC`, ni chiffrement. « Reçu » veut dire « décodable au
  niveau radio », pas « authentifié ».
- **Une seule jointure par terminal** : `join_requests_s` ne modélise pas le rejoint 1.1 ni un
  changement de session pendant que des trames sont en vol.

Les deux limites suivantes, présentes jusqu'à D3.12, **ne sont plus d'actualité** : l'occupation de la
passerelle et le rapport cyclique sont désormais arbitrés, voir §10.

| Limite levée | Depuis D3.13 |
|---|---|
| « le Join-Accept n'occupe pas la passerelle » | il passe par l'arbitre partagé : une fenêtre couverte n'est pas émise (`gateway_busy`), une émission retarde les autres |
| « le Join-Request ne consomme pas le rapport cyclique » | il passe par `DutyCycleLedger` : une tentative qui dépasse le budget n'est pas émise du tout |

## 10. Arbitrage radio partagé (D3.13)

Avant D3.13, trois implémentations indépendantes décidaient de l'occupation de l'émetteur, et la
quatrième (le Join-Accept) n'en décidait rien du tout :

| Producteur | Où il vivait | Ressource utilisée |
|---|---|---|
| ACK et downlinks, chemin du cœur | `DownlinkScheduler` (C++, `lsim_plan_downlinks_v1`) | `busy` calculé en C++ |
| ACK et downlinks, oracle Python | `trace_events._schedule_gateway` | `busy_until` local |
| ACK retardé ou répété | `ack_mac.plan_acks` | `busy_until` local |
| Join-Accept RX1 / RX2 / rejeu | `join._evaluer` | **aucune** |

D3.13 les fait converger vers **un seul arbitre**, `lsim.arbitre.GatewayArbiter`, et ajoute la
contrainte réglementaire qui manquait, `lsim.arbitre.DutyCycleLedger`.

### 10.1 Règles d'arbitrage

| Règle | Énoncé | Statut |
|---|---|---|
| 1. Émetteur unique | la passerelle n'émet qu'une descente à la fois | modélisé |
| 2. File monotone | `début = max(instant_prêt, occupé_jusqu'à)` ; `occupé_jusqu'à` ne décroît jamais dans une passe | **hypothèse** (modèle « une file d'émission »), et la règle historique du cœur |
| 3. Ordre chronologique | file d'événements : une demande née du placement d'une autre (RX2 après RX1) entre à son propre instant | modélisé |
| 4. Aucune priorité inventée | `ArbitrationPolicy.priority` est **vide** : à instant égal, ordre de dépôt | décision |
| 5. Fenêtre | `début >= fin de fenêtre` ⇒ `window_missed`, **aucune occupation** | modélisé |
| 6. Émission tardive | `allow_late=True` (couche MAC) : émise hors fenêtre, elle occupe quand même | déjà le comportement de `ack_mac` |
| 7. Rapport cyclique | budget `airtime cumulé + airtime <= rapport × instant`, **avant** l'appel au moteur | **hypothèse**, la même que pour les réémissions |
| 8. Causalité des tentatives | une tentative n'est retirée du calendrier que si une jointure a été **observée**, jamais sur une prévision | modélisé |

La règle 8 est la correction apportée par la validation finale de D3.13. Le Join-Accept partage
l'émetteur avec les ACK : on ne sait donc **qu'après** l'avoir placé si une tentative aboutit. Une
sonde qui rejouait la jointure à part, avant le placement partagé, pouvait annoncer une réussite
qu'un ACK concurrent démentait ensuite — la tentative de secours était alors retirée du calendrier
alors qu'elle était nécessaire. Le jeu de tentatives se déduit désormais des succès observés au
tour précédent (`JoinResult.succes`), par itération jusqu'au point fixe ; au premier tour, rien
n'est encore observé, donc toutes les tentatives sont jouées et aucune n'est supprimée. Une
tentative postérieure à une jointure obtenue n'émet pas de Join-Accept (condition de
`EmissionRequest`) et disparaît du calendrier au tour suivant.

La règle 4 est une décision, pas une approximation : LoRaWAN ne définit pas d'ordre entre un
Join-Accept et l'ACK d'un autre terminal. Le simulateur n'en invente pas ; une politique explicite
reste configurable, à charge pour l'appelant de la justifier.

La règle 5 ne vérifie que le **début** de l'émission, comme le planificateur du cœur : une descente
qui commence dans la fenêtre et finit après sa fermeture est émise. C'est la règle historique,
conservée pour ne pas rompre la parité.

### 10.2 Ce que ça change, mesuré

Scénario `retransmissions_ack_tardif.yaml`, trames de 51 octets en SF12 (descentes longues),
`join_requests_s: [10]`, `retries: 2` :

| Réglage | RX1 | RX2 | Session |
|---|---|---|---|
| `ack_delay_ms: 0` | `delivered` | — | 1 |
| `ack_repetitions: 2`, `ack_delay_ms: 12000` | `gateway_busy` | `delivered` | 1 |
| `ack_repetitions: 3`, `ack_delay_ms: 12000` | `gateway_busy` | `gateway_busy` | **0** |

`ack_delay_ms: 12800` place un ACK à 15,288 s, pendant l'émission du Join-Accept (15,206 →
15,453 s) : l'ACK part à 15,453 s. **La ressource est unique, dans les deux sens.**

RX2 est désormais **retardée par l'émission de RX1** quand celle-ci dépasse l'ouverture de RX2 :
c'est le cas mesuré en SF12, où un Join-Accept de 33 octets occupe l'émetteur 1,81 s. La correction
RX1/RX2 de D3.12 est intacte — RX2 reste un **secours**, jamais une seconde copie — mais elle
s'ajoute à la file au lieu d'être posée à un instant fixe.

#### Le scénario de causalité, avant et après

Scénario de la directive de validation finale : un terminal tente à 10 s, avec une seconde tentative
programmée à 20 s (`join_retries: 2`) ; trois copies d'ACK couvrent RX1 **et** RX2 de la première
tentative (`ack_repetitions: 3`, `ack_delay_ms: 12000`, SF12).

| | Tentatives jouées | RX1 / RX2 de la 1re | Session | Join-Accept émis |
|---|---|---|---|---|
| **Avant** (sonde anticipée) | 1 (à 10 s) | `gateway_busy` / `gateway_busy` | **0** | 0 |
| **Après** (programmation causale) | **2** (10 s et 20 s) | `gateway_busy` / `gateway_busy`, puis `delivered` à 26,48 s | **1** | 1 |

Avant : la sonde prévoyait une réussite à 10 s, la tentative de secours à 20 s était retirée du
calendrier, et le terminal **ne joignait jamais** alors que rien ne l'en empêchait. Après : la
tentative de secours a lieu, le Join-Accept de 26,48 s est délivré, la session s'ouvre. Aucune
tentative n'est émise après une jointure réussie — cas sans concurrence mesuré à une seule
tentative, un seul Join-Accept émis, une seule session.

### 10.3 Rapport cyclique des Join-Request

`DutyCycleLedger` applique `airtime cumulé + airtime <= rapport × instant`, avec le
`duty_cycle` du groupe (et la limite de sous-bande régionale, déjà appliquée par
`GroupModel.effective_duty_cycle`). Le budget est **global** : les trames de données et les
réémissions du terminal le consomment comme les Join-Request, parce que la contrainte
réglementaire porte sur l'occupation de la sous-bande, pas sur la nature de la trame.

Une tentative refusée :

- n'entre **pas** dans le moteur : aucune collision provoquée, aucun temps d'antenne consommé ;
- porte l'issue `blocked_duty_cycle` sur `JoinAttempt.request_outcome` ;
- apparaît en trace avec l'issue `suppressed` du contrat — jamais comme une transmission ;
- **n'alimente pas** le budget : le cumul ne compte que les émissions réellement faites.

**Grandeurs et unités.** `rapport` : sans dimension, dans `]0, 1]` (1 % = 0,01). `airtime` et
`instant` : **nanosecondes entières** comptées depuis l'origine de la simulation. Le produit
`rapport × instant` est un temps d'antenne autorisé, en nanosecondes.

**Fenêtre temporelle — ce n'est pas une fenêtre glissante.** Le budget est **cumulatif depuis
l'origine** : `airtime_cumulé` est la somme de toutes les émissions du terminal depuis `t = 0`,
mise en regard d'un droit qui croît linéairement avec le temps. Une émission vieille de 190 s pèse
encore à `t = 200 s`. C'est la règle déjà appliquée aux réémissions, reprise à l'identique ; rien
de nouveau n'est inventé ici.

**Isolation.** Le budget est par terminal : celui de l'un ne limite pas l'autre. Mesuré avec deux
groupes (`duty_cycle: 0.001` et `1.0`), `join_retries: 2` : le terminal contraint voit ses deux
tentatives refusées, l'autre joint du premier coup, et le compteur de refus vaut 2.

Mesuré avec `duty_cycle: 0.001` et `join_retries: 2` : 2 tentatives refusées, 0 Join-Accept
émis, 0 session. Avec `join_retries: 3` : **3** tentatives refusées — le budget s'applique à
toutes les tentatives réelles, pas seulement à la première. `enforce_duty_cycle: false` rend le
budget inopérant (1 Join-Accept émis, session ouverte) — la même clef que pour les réémissions.

**Contrainte non modélisée, signalée et non inventée :** aucune limite réglementaire **descendante**
n'est introduite. La passerelle n'a pas de budget d'émission ; `DutyCycleLedger` ne connaît que des
terminaux et l'arbitre ne le consulte jamais pour une descente.

### 10.4 Conséquences sur le chemin d'exécution

Dès qu'une jointure radio est déclarée, les descentes passent par le planificateur **Python**
(`lsim.ack_mac`) au lieu de celui du cœur, avec le comportement nominal (`AckTiming()` : délai nul,
une copie). C'est le seul moyen de faire partager un émetteur unique sans modifier l'ABI : le cœur
ne peut pas arbitrer une demande qu'il ne connaît pas. Sans jointure radio, **rien ne change** : le
cœur garde la main, et la parité avec l'oracle Python reste exigée test par test
(`tests/test_downlink_plan_parity.py`).

L'occupation rendue par l'arbitre — ACK **et** Join-Accept — est réinjectée au moteur à
l'itération suivante du point fixe : une trame montante qui chevauche une descente est perdue
(`LOST_GATEWAY_BUSY`), dans les deux sens.

**Pourquoi exactement le chemin Python est activé.** La bascule est une seule fonction,
`_native_plan_applies` : `not options.join and mac is None`. La raison est structurelle, pas
incidente. `plan_native(records, radios, options)` reçoit les enregistrements d'**une** exécution du
moteur et produit un plan ; `_build_trace_native` vérifie ensuite que l'occupation produite égale
celle que le moteur a utilisé, et **lève** sinon. Il n'y a pas d'itération — mesuré : une seule
exécution du moteur sur le chemin natif, contre un point fixe sur le chemin Python. Or une demande
de Join-Accept n'est pas une fonction des seuls enregistrements :

1. elle dépend du **calendrier des tentatives de données**, qui ferme les fenêtres RX quand le
   terminal émet — calendrier connu seulement dans la boucle de point fixe des retransmissions ;
2. elle dépend de l'**issue de l'arbitrage**, puisque RX2 n'est déposée que si RX1 n'a pas abouti et
   qu'un rejeu naît d'une acceptation : une demande naît donc **pendant** la résolution.

Faire tenir cela dans `lsim_plan_downlinks_v1` exigerait de changer la structure d'entrée de la
fonction, donc l'ABI gelée — ce qui n'est autorisé que sur nécessité démontrée et autorisation
spécifique. **L'ABI est inchangée :** 97 symboles `lsim_*`, empreinte
`0e546fa6391866d9…`, 685 282 vérifications C++.

**Mêmes résultats quand le mécanisme partagé n'est pas nécessaire.** Condition exigée et vérifiée :
sans concurrence pour l'émetteur, l'arbitre partagé reproduit le chemin isolé **à la nanoseconde**.
Mesuré sur les 500 tentatives du scénario de référence : empreintes identiques, mêmes instants de
Join-Accept, mêmes sessions.

### 10.5 Limites explicites de D3.13

- **Le rapport cyclique descendant n'est pas modélisé.** La passerelle n'a pas de budget
  réglementaire : seul le terminal en a un. Une passerelle réelle est soumise à une limite, que le
  simulateur ne connaît pas.
- **La programmation causale du jeu de tentatives est itérative, et bornée.** Les tentatives qui
  suivent une jointure **observée** sont retirées au tour suivant, jamais sur une prévision. Le
  point fixe est recherché en au plus 8 tours ; un état qui se répète à l'identique lève une erreur
  explicite plutôt que de rendre un résultat approximatif. La limite résiduelle est le coût : un
  scénario qui joint est rejoué autant de fois qu'il faut pour stabiliser le calendrier des
  tentatives — en pratique deux à trois tours, soit une durée de simulation inchangée au regard des
  mesures (101 s pour la suite complète, contre 100 s avant la correction).
- **Un seul émetteur par passerelle** : ni cartes radio multiples, ni descentes simultanées sur
  plusieurs canaux. Un équipement réel à huit canaux descendants n'est pas représenté.
- **La durée d'ouverture des fenêtres (1 s) est une hypothèse du simulateur**, déjà celle du cœur.
  LoRaWAN fixe le délai d'ouverture, pas la durée d'écoute.
- **La jointure reste non authentifiée** : §10.1 ne change rien à §9.4 — aucune clé, aucun `MIC`.
- **Le cœur C++ et l'ABI ne sont pas modifiés.**
