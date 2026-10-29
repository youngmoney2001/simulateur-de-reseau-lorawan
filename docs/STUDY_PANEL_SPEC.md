# Panneau d'étude étudiant : spécification (brouillon, non implémentée)

Statut : **proposition validée sur le périmètre** (réponses de l'auteur consignées en §10),
détails d'implémentation encore ouverts. Périmètre : `web/` et le contrat d'API
(`docs/API_CONTRACT.md`). Le moteur (`core/`, `python/lsim/`) n'est modifié que là où ce document
le signale. Aucun code d'interface n'est écrit à ce stade.

## 1. Objectif et public

Un panneau pédagogique : on construit une topologie, on configure chaque équipement en ligne de
commande, on lance la simulation et on observe les trames. Un exercice est **noté** par vérification
automatique côté serveur.

Public : étudiants en réseaux LoRaWAN, puis ingénieurs qui se forment sur un plan de réseau. Le
panneau reproduit une **interface de configuration** et un **comportement modélisé**, pas un
firmware réel.

## 2. Architecture visée

> Réseau LoRaWAN avec backhaul maillé interpasserelles, permettant le relais des données vers une
> passerelle frontière connectée au serveur réseau.

- Les capteurs émettent en LoRaWAN standard, directement vers une passerelle. Ils ne relaient jamais
  les messages des autres capteurs (pas de mesh entre capteurs, pas de répéteur de capteur).
- Les **passerelles relais** (sans accès Internet) retransmettent les trames des capteurs ou d'autres
  relais vers une **passerelle frontière**, qui est connectée au serveur réseau LoRaWAN.
- Le backhaul maillé est un **lien radio LoRa entre passerelles**, sur une seconde radio ou une
  bande dédiée, comme le fait ChirpStack Gateway Mesh : la passerelle frontière déballe la trame
  relayée et la transmet au serveur comme si elle l'avait reçue directement. Le protocole exact
  (encapsulation, nombre de sauts, bande) est un paramètre du modèle, pas une copie d'un produit.
- Bande : **dédiée**, distincte de celle des capteurs (choix de l'auteur). Le lien mesh n'entre
  donc pas en collision avec le trafic des capteurs, mais il a son propre duty cycle et son propre
  temps d'antenne.
- Limite de sauts : 8 par défaut (valeur de ChirpStack Gateway Mesh), configurable.

Source de référence du mécanisme : documentation ChirpStack Gateway Mesh
(chirpstack.io/docs/chirpstack-gateway-mesh).

Un backhaul **IP** entre passerelles (Ethernet, Wi-Fi, cellulaire) est une variante du même
modèle : une passerelle frontière reste obligatoire. Il est hors du premier jalon.

## 3. Équipements

| Équipement | Rôle | Configuration (CLI) |
|---|---|---|
| Capteur (end device) | Émet en classe A (classe B hors périmètre initial) | Plan régional, débit, puissance, période, clés (masquées) |
| Passerelle relais | Reçoit en radio, relaie par le backhaul maillé, sans Internet | Plan régional, radio mesh (fréquence, SF, BW, CR), nombre de sauts max |
| Passerelle frontière | Reçoit en radio et depuis le maillage, connectée au serveur | Idem + serveur (GWMP ou Basic Station), net-id |
| Serveur de jointure et réseau | Jointure, déduplication, acquittements | NetID, plan, clés (masquées), adresse |
| Application | Reçoit les données | Hors CLI |

Les modèles sont un mélange de **génériques** (paramètres libres) et de **références commerciales**
(profils par défaut inspirés de produits réels, par exemple des passerelles RAK). Les profils
commerciaux ne reprennent que les paramètres publiés dans leur documentation ; les commandes propres
à un fabricant ne sont pas reproduites sans source.

## 4. Interface de configuration (inspirée d'IOS)

L'interface **s'inspire** d'IOS : elle n'est pas une copie fidèle de la syntaxe ou des messages
Cisco. Les modes et conventions sont conservés pour l'apprentissage.

### 4.1 Modes

| Invite | Mode | Accès |
|---|---|---|
| `gw1>` | Utilisateur | Par défaut ; `show` limité |
| `gw1#` | Privilégié | `enable` |
| `gw1(config)#` | Configuration globale | `configure terminal` |
| `gw1(config-if)#` | Interface (radio, mesh, backhaul) | `interface lora 0`, `interface mesh 0`, `interface eth 0` |

Chaque équipement a son propre état. `exit`, `end`, `?` (aide contextuelle) et l'auto-complétion
suivent les conventions IOS. Les erreurs de syntaxe indiquent la position fautive par un marqueur
`^`, sans reproduire exactement les messages Cisco.

### 4.2 Commandes (noyau proposé)

Radio d'accès (`interface lora 0`) :

- `region EU868|US915|AU915|AS923|KR920|IN865|RU864` ;
- `sub-band N` (US915/AU915) ; `tx-power DBM` ; `antenna gain DBI` ; `frequency MHZ`.

Radio mesh (`interface mesh 0`, passerelles relais et frontière) :

- `mode relay|border` ; `frequency MHZ` ; `spreading-factor N` ; `bandwidth KHZ` ;
- `max-hops N` (1 à 8) ; `tx-power DBM`.

Passerelle (config globale) :

- `lorawan net-id HEX6` ; `lorawan server ADDR up-port N down-port N` (GWMP ; syntaxe retenue : les ports sont nommés, la forme du gabarit « port up-PORT » était ambiguë) ;
- `lorawan transport udp|basicstation` ; `lorawan location X Y`.

Vérification (`show`) :

- `show version`, `show running-config`, `show interfaces`, `show mesh neighbors`,
  `show mesh routes`, `show lorawan devices`, `show lorawan sessions`,
  `show lorawan counters` (pertes par cause : sensibilité, collision, hors-fenêtre,
  saut maximal dépassé, passerelle occupée).

Gestion :

- `copy running-config startup-config` ; `reload` (efface l'état non sauvegardé) ;
  `write erase` (réinitialise un équipement d'exercice).

Les clés et secrets ne sont **jamais** affichés : `show running-config` masque les clés (`******`),
conformément au contrat d'API.

### 4.3 Règles de cohérence (contrôlées par le moteur)

- Une passerelle et ses capteurs doivent partager le même plan régional ; sinon les trames sont
  perdues avec une issue explicite (pas silencieuse).
- Une passerelle relais dont aucune route mesh ne mène à une frontière ne relaie rien.
- Un relais ne transmet qu'à `max-hops` au plus ; au-delà, la trame est perdue (issue explicite).
- Une passerelle frontière ignore les uplinks radio directs si la configuration le demande (cas
  présent dans la documentation RAK, à reproduire comme option).
- Un `shutdown` sur l'interface mesh coupe le relais ; les trames en transit sont comptées comme
  perdues.

## 5. Ce que le moteur doit gagner

1. **Plusieurs passerelles** : le moteur ne calcule qu'une passerelle (`Gateway` dans
   `python/lsim/simulator.py`). Il faut calculer la réception par passerelle, puis dédupliquer au
   serveur (une copie retenue).
2. **Backhaul maillé radio** : chaque saut relais est une transmission LoRa avec son temps
   d'antenne, ses collisions et son duty cycle. C'est le point le plus coûteux : il consomme la
   même ressource radio que les capteurs (ou une bande dédiée, selon la configuration).
3. **Routage** : table de routes vers la frontière, construite par la configuration (routage
   statique au départ). Aucun protocole de routage dynamique n'est inventé.
4. **Sensibilité** : référence SX1276 tant que la fiche SX1262 n'est pas intégrée
   (`device_rx_offset_db` en attendant).

## 6. Exercices notés avec vérification automatique

Un exercice contient :

- une topologie de départ (capteurs, passerelles relais et frontière, serveur) ;
- un énoncé (par exemple « 95 % des messages du capteur C atteignent le serveur ») ;
- des **critères** vérifiés côté serveur : configuration attendue (`show running-config`),
  connectivité (route mesh présente), résultat de simulation (PDR, latence, nombre de sauts,
  passerelle utilisée) ;
- un **barème** : chaque critère a un poids, et la note est la somme des critères réussis ;
- des indices, révélés à la demande et comptés dans la note.

La vérification se fait côté serveur, sur l'état réel de la simulation. Le navigateur n'envoie
jamais de résultat à valider. La solution de référence n'est jamais envoyée au client.

Exemples (indicatifs) :

1. Configurer une passerelle sur EU868 et vérifier qu'un capteur est joint.
2. Ajouter un relais pour couvrir un capteur masqué, puis le relier à la frontière (au plus 2 sauts).
3. Corriger un plan régional incohérent entre capteur et passerelle.
4. Choisir une sous-bande US915 pour éviter une collision avec un autre groupe.

## 7. Contrat d'API du panneau d'étude (servi sous `/api/v1`)

Formes des données : `python/lsim/study_contract.py`. Schémas publiés dans `schemas/api/v1`
(`study_*.schema.json`), avec le reste du contrat : le dossier `study-draft` n'existe plus, le panneau
est public.

| Méthode | Chemin | Rôle |
|---|---|---|
| POST | `/api/v1/sessions` | Crée une session : `nodes` (topologie) ou `exercise_id` (topologie de l'exercice) |
| GET | `/api/v1/sessions/{id}/topology` | Équipements et états (hostname, région, configuré ; jamais de clé) |
| POST | `/api/v1/sessions/{id}/cli` | Exécute une ligne CLI sur un équipement ; réponse : sortie, mode, erreur |
| POST | `/api/v1/sessions/{id}/nodes` | Ajoute un équipement à la topologie (`Node`, `sensor` optionnel) |
| DELETE | `/api/v1/sessions/{id}/nodes/{node_id}` | Retire un équipement (et son état CLI) |
| POST | `/api/v1/sessions/{id}/nodes/{node_id}/sensor` | Remplace les réglages d'un capteur (`SensorSettings`) |
| POST | `/api/v1/sessions/{id}/simulate` | Compile la session et crée le run (`seed`) ; réponse : `run_id`, `links`, `notes` |
| POST | `/api/v1/sessions/{id}/simulation` | Lie un run terminé : `run_id`, et `links` ou, pour un run de `simulate`, rien |
| POST | `/api/v1/sessions/{id}/hints` | Révèle le prochain indice de l'exercice (`exercise_id`) |
| GET | `/api/v1/sessions/{id}/attempts` | Journal des soumissions de la session (résultats seulement) |
| GET | `/api/v1/exercises` | Catalogue : énoncé, total de points, nombre d'indices |
| POST | `/api/v1/exercises/{id}/submit` | Note la session (`session_id` seul) ; réponse : score et critères |

Décisions (implémentées) :

- **Persistance** : sessions, configurations CLI et journal sont écrits dans le fichier SQLite des runs
  (`--runs-db`) à chaque modification, et relus au démarrage (`study_store.py`). Un redémarrage ne les
  perd pas. Une lecture n'est écrite qu'une fois par minute au plus, pour que l'expiration parte de
  la dernière activité. Expiration après 4 h **d'inactivité**. 8 sessions par compte, 256 au total ;
  ces limites sont appliquées sous le verrou de la création (test de concurrence). 429
  `limit_exceeded` au-delà.
- **Simulation** (`study_compile.py`) : `simulate` transforme la topologie et les configurations CLI en
  scénario, puis crée le run par le même chemin que `POST /runs` (mêmes validations, même file). Règles :
  - chaque capteur est un groupe de simulation nommé comme lui ; ses réglages `sensor` (SF, charge,
    puissance, période, messages, région, canal) sont les paramètres du groupe, défauts du scénario ;
  - `border` et `relay` sont des passerelles ; une passerelle dont l'interface `lora` est arrêtée n'entre
    pas dans le run ; un relais dont l'interface `mesh` est arrêtée reste une passerelle d'accès ;
  - avec des relais actifs : exactement une frontière active, à interface mesh active ; les réglages
    mesh (SF, bande, sauts) viennent de la frontière et des relais. Deux SF ou deux bandes réglées et
    différentes : 422. Les sauts prennent la plus petite valeur réglée ;
  - `mode` réglé qui ne correspond pas au rôle : 422 ;
  - plan régional et sous-bande : ceux des passerelles, identiques pour toutes ; un capteur qui déclare
    un autre plan : 422. Non réglé : EU868 (et sous-bande 1 sur US915 / AU915), signalé dans `notes` ;
  - `notes` liste aussi ce que le moteur ne modélise pas : puissance des passerelles, fréquence réglée,
    Ethernet, serveur réseau (le LNS est implicite derrière la frontière) ;
  - la liaison est automatique : `links` (une par passerelle active) sont mémorisés et appliqués à la
    fin du run, sans nom à saisir.
- **Limites** : au plus 64 équipements par session. Le serveur n'accepte pas `PUT` (405) : les
  réglages capteur passent par `POST .../sensor`.
- **Propriété** : toute session, et tout équipement qu'elle contient, appartient à un seul compte. Un
  autre compte reçoit 404 (« inconnue »), jamais 403.
- **Identifiant d'équipement** : motif `^[a-z][a-z0-9-]{0,31}$`, chaîne stable (aussi nom d'hôte CLI,
  d'où l'absence de `_`). `nodes` vide autorisé ; doublons refusés (422), pas dédupliqués en silence.
  Avec un `exercise_id`, la topologie vient de l'exercice et `nodes` doit être vide.
- **Liaison explicite** : le run ne porte que des noms de passerelle (uniques), sans identifiant stable ;
  ajouter un identifiant au scénario modifierait le schéma `v1`, ce qui n'est pas fait. Un nom ne lie
  donc rien par lui-même. Chaque association est validée avant toute modification : une erreur ne lie
  rien partiellement. Un équipement et une passerelle ne sont associés qu'une fois.
- **CLI** : une seule ligne (422 sinon). `exit` au niveau utilisateur redémarre la console en mode
  utilisateur (message dans la sortie). `show lorawan counters` et `show mesh counters` lisent la
  passerelle associée ; les `show` non alimentés par le moteur ne sont pas dans la grammaire.
- **Exercices** : quatre exercices (EU868 ; relais à deux sauts avec lien mesh observé ; US915 sous-bande
  2 avec réception ; latence p95 de la frontière, seuil 300 ms, **validé par l'auteur**). Chaque
  topologie de départ contient un capteur. Dans les exercices à relais, il émet à -10 dBm à 1500 m :
  la frontière ne l'entend pas, le relais si. La latence de l'exercice tombe sous 300 ms avec une bande
  mesh de 812 kHz (p95 228 ms ; 790 ms à 203 kHz, valeur par défaut). Le public ne voit que l'énoncé, le total de points et
  le nombre d'indices. Critères : configuration (région, sous-bande, serveur, mode mesh, sauts) et
  simulation liée (trames reçues, lien mesh observé, latence p95). Le client n'envoie que `session_id` ;
  un champ `score` ou `criteria` est refusé (422). Une session ne se note que pour son exercice.
- **Indices** : deux par exercice, révélés un à un. Chaque indice révélé retire `HINT_PENALTY` = 2 points
  à la note, plancher 0. Plus d'indice : 409.
- **Journal** : chaque soumission ajoute une tentative (50 au plus par session) : numéro, instant,
  exercice, score, nombre d'indices, critères réussis. Aucune commande CLI, aucun secret.

Indicateurs de latence et de lien mesh (`lsim/trace_metrics.py`, publiés dans le résumé du run par
passerelle) :

- `latency_p50_ms`, `latency_p95_ms`, `latency_samples` : uplinks de donnée remis au LNS par la
  passerelle, de l'émission à la remise (saut mesh inclus). Rang le plus proche ; absents sans mesure.
- `mesh_inbound` : sauts mesh livrés depuis chaque émetteur (les copies supprimées ne comptent pas).

Décisions validées par l'auteur :

- seuil de latence de l'exercice : **300 ms** (p95 remise au LNS par la frontière).

Restent ouverts :

- compte et partage : les sessions appartiennent à un jeton, sans comptes multiples ni partage ;
- sauvegarde : les sessions sont dans le fichier des runs ; leur sauvegarde suit celle de ce fichier ;
- interface graphique (`web/`, phases 5 à 7 de la §8). L'API est complète pour construire, configurer
  et simuler ; le navigateur ne fait pas encore que la piloter.

## 8. Phasage proposé

1. Spécification validée et ajout au contrat.
2. Moteur multi-passerelles avec déduplication, tests C++ et Python. **Faits** : réception par passerelle et déduplication (`simulate_uplinks_multi`), downlinks par la meilleure passerelle et demi-duplex par passerelle (`simulate_uplinks_multi_downlinks`, calcul exact dans l'ordre de fin). Restent : intégration dans `run` et dans le contrat, puis le relais mesh (phase 3).
3. Backhaul maillé radio (saut, collisions, duty cycle) et routage statique.
4. CLI d'un équipement (une passerelle), tests de la grammaire et des erreurs.
5. Topologie multi-équipements et simulation pas à pas.
6. Exercices notés et vérification côté serveur.
7. Interface graphique (éditeur de topologie, animation des trames, journal par saut).

## 9. Hors périmètre initial

- Relais ou répéteur radio entre capteurs (non standard LoRaWAN) ;
- backhaul IP entre passerelles (variante ultérieure) ;
- classes B et C ;
- firmware réel et émulation binaire d'un équipement physique ;
- protocoles de routage dynamiques ;
- multi-utilisateurs et paquets macOS/Windows (voir la feuille de route).

## 10. Décisions

| Sujet | Décision de l'auteur |
|---|---|
| Sens de « mesh » | Backhaul maillé entre passerelles (relais vers une passerelle frontière), pas de mesh entre capteurs |
| Fidélité CLI | Inspirée d'IOS, pas fidèle (syntaxe et messages) |
| Exercices | Notés (barème, somme des critères) |
| Équipements | Mélange de modèles génériques et de références commerciales |

| Bande du lien mesh | **Bande dédiée**, distincte de la bande des capteurs (choix de l'auteur) |

Décidé : 8 sauts par défaut, comme ChirpStack (auteur). Reste ouvert : le choix précis de la bande
dédiée (sous-GHz second canal ou 2,4 GHz). Le moteur la prend en paramètre, sans valeur codée en dur.
