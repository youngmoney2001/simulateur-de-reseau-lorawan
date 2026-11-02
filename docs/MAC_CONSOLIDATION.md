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

Ces trois mécanismes sont détaillés en §7. Ce qui reste hors périmètre : la reconstruction depuis un
**journal de paquets réels** (le simulateur tient les 32 bits en mémoire), la remise à zéro par une
nouvelle jointure dans la couche ACK (le scénario fixe les départs), et le compteur `AFCntDown` de
bout en bout — un ACK ne portant pas de charge utile, la couche n'exerce que `NFCntDown`.

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
3. Appliquer les commandes aujourd'hui « codec seul » une par une, avec leurs tests de
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
de la session 1 n'est pas un rejeu de celui de la session 0 (`sessions=` dans `plan_acks`). **Ce qui
n'est pas fait** : aucun `Join-Accept` de scénario ne crée cette nouvelle session ; elle est fournie
par l'appelant.

**Limite de mesure, à ne pas masquer** : `GAP` n'est produit par **aucun scénario livré**. La copie
d'un ACK porte le même champ 16 bits : c'est un `DUPLICATE`, jamais un saut de 65 536. La
désynchronisation n'est vérifiée qu'au niveau des primitives (`CounterSeries`) et du plan, jamais de
bout en bout dans une trace.
