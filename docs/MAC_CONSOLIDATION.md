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
| `FCntDown` | un terminal | `AckEmission.f_cnt_down`, `AckFrame.frame_counter_down` | série **par terminal** ; un ACK émis consomme un numéro, ses copies gardent le même |
| contrôle de rejeu | un terminal | `plan_acks` (`dernier_accepte`) | un ACK n'est retenu que si son `FCntDown` est **strictement supérieur** au dernier accepté |

Conséquences vérifiées par `python/tests/test_mac_consolidation.py` :

- `fcnt_up_start: 1000` sur un scénario à deux messages donne les trames `1000` et `1001`, et les
  ACK portent `(1000, 0)` puis `(1001, 1)` — l'identité ne dépend plus d'un rang de tableau ;
- deux terminaux ont chacun leur série descendante : `[0, 1]` pour l'un, `[0, 1]` pour l'autre ;
- `AckFrame.is_explicit` devient vrai : l'appariement dispose de `FCntUp`, il n'a plus besoin de la
  seule fenêtre.

**Sémantique de référence** : celle de `lsim.session.DeviceSession` (`begin_uplink` → `fcnt32`,
`receive_downlink` → contrôle de rejeu). Ces compteurs ne sont pas un second modèle : le module les
transporte dans la trace, avec les mêmes règles.

**Ce qui n'est pas modélisé** : la fenêtre `MAX_FCNT_GAP`, la reconstruction 16 → 32 bits des trames
réelles, et la distinction `NFCntDown` / `AFCntDown` de LoRaWAN 1.1 (une seule série ici).

## 2. Taxonomie de l'ACK

Chaque **émission** reçoit exactement une classe (`AckSort`) ; les compteurs agrègent ces classes
sans recouvrement.

| Classe | Définition | Effet sur la trame |
|---|---|---|
| `STANDARD` | émise dans une fenêtre écoutée (RX1, RX2, ou écoute continue en classe C), décodable, `FCntDown` inédit | acquittée |
| `LATE` | émise après la fermeture des fenêtres | non acquittée ; l'airtime est consommée et la passerelle occupée |
| `LOST` | émise dans une fenêtre écoutée mais non décodable, ou terminal en train d'émettre | non acquittée |
| `DUPLICATE` | même `FCntDown` qu'un ACK déjà accepté par ce terminal | ignorée : le rejeu est rejeté par le compteur, pas par une règle propre à l'ACK |
| `NOT_SENT` | aucun ACK : l'uplink n'a pas été reçu | aucune |

`AckPlan.counts` donne les cinq totaux ; `RetransmissionResult` les expose en `ack_standard`,
`ack_late`, `ack_lost`, `ack_duplicate`, `ack_not_sent`. Un test vérifie que
`standard + late + lost + duplicate == acks_planned` pour les trois configurations de référence.

Le détail de réception reste disponible séparément (`AckWindow` : `RX1`, `RX2`, `CONTINUOUS`,
`LATE`, `NOT_DECODABLE`, `WINDOW_MISSED`, `NOT_SENT`). Une seule conversion est lossy et elle est
documentée : `LATE` est rangé avec les pertes de sensibilité dans `DownlinkDelivery`, qui n'a pas de
verdict « hors fenêtre ».

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
| Compteurs de trace | `ack_standard` / `late` / `lost` / `duplicate` proviennent du même plan que les émissions |
| Événements de trace | **limite** : les ACK de la couche MAC apparaissent dans l'occupation (`gateway_tx`), pas encore comme `ProtocolEvent` de type `ack` ; les événements restent ceux du planificateur du cœur |
| Appariement | inchangé sur le chemin du cœur (`_match_ack` par fenêtre RX1) ; la couche MAC utilise `FCntUp` |

Un test vérifie que six ACK tardifs donnent six intervalles d'occupation (`gateway_tx`), donc que la
trace ne cache pas l'airtime consommée.

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

## 6. Ce qui reste à faire

1. Faire apparaître les ACK de la couche MAC comme `ProtocolEvent` de la trace (aujourd'hui :
   `gateway_tx` et compteurs seulement).
2. `fcnt_down_start` et la distinction `NFCntDown` / `AFCntDown` si un scénario 1.1 l'exige.
3. Brancher la classe C sur le moteur d'opportunités existant (`lsim.simulator.DownlinkRequests`)
   au lieu de la règle locale d'écoute continue.
4. Appliquer les commandes aujourd'hui « codec seul » une par une, avec leurs tests de
   comportement, en commençant par `RxParamSetupReq` (elle change RX2, donc la réception de l'ACK).
