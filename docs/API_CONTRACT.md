# Contrat d'API moteur ↔ navigateur (v1)

Statut : **v1 implémentée** (`python/lsim/api_server.py`, bibliothèque standard, sans dépendance
nouvelle), limites ci-dessous. Les formes de données sont dans `python/lsim/api_contract.py` ; les
schémas JSON publiés sont dans `schemas/api/v1/`. Les tests `python/tests/test_api_contract.py`
vérifient que les schémas restent synchronisés avec le code ; `python/tests/test_api_server.py`
vérifie le serveur (jetons, routes, pagination, refus, file bornée, annulation).

Lancer : `python -m lsim.api_server issue-token --tokens FICHIER --owner NOM` (jeton affiché une
fois), puis `python -m lsim.api_server serve --tokens FICHIER --port 8765` (écoute sur 127.0.0.1).

Régénérer les schémas après une modification, depuis la racine du dépôt :

```bash
PYTHONPATH=python python -m lsim.api_contract schemas/api/v1
```

La génération est déterministe : `python/tests/test_api_contract.py` la relance en sous-processus
et compare les octets obtenus aux fichiers publiés.

## 1. Principes

| Sujet | Règle |
|---|---|
| Transport | HTTP/1.1 JSON, préfixe `/api/v1`. Le navigateur n'appelle que des chemins relatifs ; en développement, Vite fait le relais vers le serveur Python. Aucun `localhost` dans le code du navigateur. |
| Calcul | Tout calcul radio, réseau et crypto est fait côté Python / cœur C++. Le navigateur affiche et rejoue. |
| Fichiers | Le navigateur ne fournit jamais de chemin de fichier. Le relief est désigné par `terrain_id` (identifiant de catalogue, `[a-z0-9_-]{1,64}`) résolu sur le serveur (`--terrain-catalog`) ; un `terrain` avec chemin dans le scénario est refusé. |
| Secrets | Aucune clé (NwkSKey, AppSKey, clés de jointure, `LSIM_DATA_KEY`) dans une réponse, un journal ou un événement. |
| Erreurs | Format `Problem` (code stable + message), HTTP 4xx pour l'entrée, 5xx pour le serveur. Pas de trace Python dans la réponse. |
| Bornes | Corps de requête et réponses non paginées : 256 KiB. Événements par run : 200 000 au plus. Page : 500 éléments au plus. Dispositifs et transmissions : bornes de `ScenarioModel`. |
| Version | Le préfixe `/v1` ne change qu'en cas de rupture. Ajout de champ optionnel = compatible. Les réponses refusent les champs inconnus côté client. |

## 2. Points d'accès

| Méthode | Chemin | Rôle | Réponse |
|---|---|---|---|
| GET | `/api/v1/regions` | Plans régionaux (lecture seule) : canaux, débits, RX2, charges N | `RegionList` |
| GET | `/api/v1/terrains` | Reliefs du catalogue serveur : identifiant et empreinte SHA-256 | `TerrainList` |
| POST | `/api/v1/scenarios/validate` | Valide un scénario (et `terrain_id` optionnel) sans lancer de calcul | `ValidateResponse` (`valid`, `scenario_sha256`, `problems`) |
| POST | `/api/v1/runs` | Crée un run (file d'attente), options `protocol`, `energy_profile` et `terrain_id` incluses | 202 + `RunStatus` (`state: queued`) |
| GET | `/api/v1/runs/{run_id}` | État, avancement, erreur éventuelle | `RunStatus` |
| GET | `/api/v1/runs/{run_id}/summary` | Totaux, PDR, charge passerelle (run terminé) | `RunSummary`, 409 tant que non terminé |
| GET | `/api/v1/runs/{run_id}/devices?cursor=` | Lignes par dispositif, paginées | `DevicePage` |
| GET | `/api/v1/runs/{run_id}/events?cursor=&limit=` | Journal d'événements, paginé, ordonné par `seq` | `TracePage` |
| DELETE | `/api/v1/runs/{run_id}` | Annule (si `queued` ou `running`) ou supprime (si terminé) | 204 |

Cycle d'un run : `queued` → `running` → `done` | `failed` | `cancelled`. Un run `done` est
immuable ; le même scénario et la même graine redonnent les mêmes événements (`scenario_sha256`).

`run_id` : 8 à 64 caractères `[A-Za-z0-9_-]`, généré par le serveur.

## 3. Horloge de simulation

Le moteur calcule le run entier, puis le navigateur **rejoue** le journal :

- temps simulé `t_ns` (entier, nanosecondes) ;
- lecture, pause, pas à pas (passage à l'événement suivant), vitesse (facteur) : états purement
  côté navigateur ;
- la position dans le journal est un `seq` ; reprendre après une pause ne demande aucun calcul.

Conséquence : l'horloge ne pilote pas le moteur. Un run sans horloge temps réel est reproductible.

## 4. Journal d'événements (animation et journal par saut)

`TraceEvent` : `seq`, `t_ns`, `kind`, `device_index`, `gateway_index`, `outcome`, `hops`.

- `kind` : `join_request`, `join_accept`, `uplink`, `ack`, `downlink`, `lost_sensitivity`,
  `lost_collision`, `rx_window_missed`.
- `hops` (au plus 8) : une entrée par saut (`from_id`, `to_id`, `t_ns`, `freq_hz`, `dr`,
  `rssi_dbm`, `outcome`). Le journal affiche ces sauts dans l'ordre.
- Ordre : `seq` strictement croissant, `t_ns` non décroissant.

**Trace par transmission (implémentée côté Python, pas encore exposée par HTTP).**

- Le cœur natif renvoie une entrée par émission (`lsim_simulate_uplinks_trace`) : début, fin,
  SF, RSSI, issue (`lost_sensitivity`, `lost_collision`, `received`). Les compteurs sont ceux du
  même appel, donc trace et totaux concordent. Borne : 200 000 émissions par run (statut 309).
- `lsim.trace_events` dérive les événements à partir de cette trace, avec les temporisations du
  protocole et le même `t_ns` que le moteur :
  - join-request : issue de l'émission ; join-accept à fin + 5 s (`JOIN_ACCEPT_DELAY1`) ;
  - uplink accepté (passerelle) : fenêtre RX1 à fin + 1 s (`RECEIVE_DELAY1`) ;
  - downlink : un seul par uplink accepté (comme `lsim.uplink`) ; `downlink` si une charge est en
    file (`downlink_every`), sinon `ack` si l'uplink est confirmé ;
  - demi-duplex : si le dispositif émet encore pendant sa fenêtre RX1, l'événement est
    `rx_window_missed` (issue `not_listened`), sans retransmission.
- Réception des downlinks par le dispositif : hypothèse de réciprocité. RSSI descendant =
  RSSI montant − P_dispositif + P_passerelle + G_dispositif ; reçu si ≥ sensibilité du débit RX1
  du plan. Valeurs par défaut : P_passerelle 14 dBm, G_dispositif 0 dBi (`RunCreate.protocol`).
  Perte : événement dont l'issue est `lost_sensitivity`, saut `lost_sensitivity`.
- Passerelle demi-duplex : un seul downlink à la fois (un downlink qui tombe pendant un autre
  attend ; s'il ne peut partir dans la fenêtre RX1 du dispositif, il est perdu : `rx_window_missed`,
  issue `gateway_busy`). Pendant ses émissions, elle ne reçoit pas : un uplink qui les chevauche
  est perdu (`lost_gateway_busy`, comptée dans `Totals.lost_gateway_busy`). Uplinks et downlinks
  dépendent les uns des autres : le calcul itère jusqu'à un point fixe, sinon il échoue.
- Join en multi-passerelles : une trame est une join-request tant que son dispositif n'a pas reçu
  son join-accept. Une join-request décodée reçoit un join-accept à fin + 5 s, par la meilleure
  passerelle (17 octets, sans CFList), en RX1. Le dispositif est jointé à la réception du join-accept ;
  une join-request perdue (ou un join-accept perdu) est répétée à l'émission suivante. Les
  descendantes d'une passerelle ne se chevauchent jamais, quel que soit leur ordre de création.
  **Écart avec le mono** : en mono, seule la première émission est une join-request (une join-request
  perdue n'est jamais répétée). Le multi suit le comportement du dispositif réel ; le mono est à
  aligner plus tard. À débit égal, sans contention, les deux traces sont identiques (test).
- Limites assumées : le backhaul passerelle → serveur et le join-accept transmis par le serveur
  sont sans perte (`delivered`) ; sensibilité du récepteur de référence (SX1276) plus
  `device_rx_offset_db` ; une seule passerelle.
- Options applicatives dans `RunCreate.protocol` : `join`, `confirmed_uplinks`, `downlink_every`,
  `downlink_payload_bytes`, `gateway_tx_power_dbm`, `device_antenna_gain_dbi`, `device_rx_offset_db`
  (par défaut : aucune charge ; seuls uplinks, pertes et ACK/join-accept sont produits quand les
  options correspondantes sont activées).

La route `events` est exposée (v1). Sa trace provient de `lsim.trace_events.build_trace`, et le
serveur vérifie que ses totaux concordent avec `run_scenario` avant de publier le run.

**Périmètre de la v1 (implémentation)** :
- Scénarios **mono** et **multi-passerelles**, environnement **à obstacles** et **relief** (catalogue).
  Totaux, compteurs par dispositif, charges et événements viennent d'un seul calcul natif par run
  (`build_trace`, ou `build_multi_trace` en multi) ; le serveur vérifie que la somme des compteurs par
  dispositif égale les totaux avant de publier (sinon `run_failed`).
- **Énergie** (`energy_profile`) : calculée depuis la trace, en mono comme en multi. Chaque dispositif
  compte ses uplinks et l'airtime des descendantes qu'il reçoit (`downlink_airtime_by_device` : join-accept,
  données, ACK). Sans protocole, le résultat égale `run_scenario` (test de non-régression). Les fenêtres
  RX1/RX2 restent comptées par le modèle classe A.
- **Relief** : `terrain_id` désigne `<id>.csv` dans le dossier `--terrain-catalog`. Le client ne fournit
  jamais de chemin. Le relief est lu une fois puis gardé en mémoire. Son empreinte entre dans
  `scenario_sha256` (même scénario, autre relief : autre identifiant). `GET /terrains` liste le catalogue.
  Sans `--terrain-catalog`, le catalogue est vide. Un identifiant inconnu ou invalide : 422 sur `terrain_id`.
- Refusé explicitement (`validation_error`, jamais calculé à tort) : **mesh** (trace par saut non
  construite).
- **Résumé** : `gateway` (mono) **ou** `gateways` (multi), exactement un des deux. Historique du contrat :
  dans la v1 de départ (`bfde0e9`), `gateway` était **obligatoire**. Commit `2fd310c` l'a rendu optionnel
  et a ajouté `gateways` : c'est une rupture de la règle d'additivité, acceptée pour permettre le multi.
  Consommateurs vérifiés dans le dépôt (`web/`, `python/`) : aucun ne lit `run_summary` ; les autres
  occurrences de `gateway` sont des objets internes ou GeoJSON. Les clients mono ne voient aucun changement
  de valeur, seulement la possibilité d'une absence pour le multi.
- Runs **persistés** dans une base SQLite (`--runs-db`, mode WAL). Un run encore en file ou en cours
  au redémarrage passe à `failed` (« interrompu au redémarrage »). 20 runs par jeton, 200 au total.
  Une seule file de calcul (16 en attente, 4 actifs par jeton).
- **Écriture d'un run terminé** : les corps JSON sont sérialisés hors du verrou ; l'écriture SQL (dispositifs,
  événements, résumé) se fait sous le verrou. Mesure (base fichier, WAL, 500 dispositifs) : 5 ms pour
  1 000 événements, 30 ms pour 10 000, 147 ms pour 50 000, 540 ms pour 200 000 (borne). Pendant ce temps,
  les lectures attendent. Le déplacement de l'insertion hors verrou n'est pas fait : il exige de
  revalider l'annulation et la suppression après écriture ; le coût reste borné par run.
- **Débit** : seau à jetons par propriétaire, 120 requêtes par minute soutenues, rafale de 60. Au-delà :
  429 `rate_limited` avec `Retry-After`.
- **TLS** : `--tls-cert` et `--tls-key` (TLS 1.2 minimum). `serve` refuse de démarrer sur une adresse
  non locale sans TLS. Le certificat est fourni par l'exploitant.
- Erreur interne : code `run_failed`, message générique, sans trace.

## 5. Erreurs

Corps `Problem` :

```json
{"code": "validation_error", "message": "groups.0.count : …", "field": "groups.0.count"}
```

| `code` | HTTP | Cas |
|---|---|---|
| `validation_error` | 422 | scénario ou requête invalide |
| `terrain_not_allowed` | 422 | `terrain` avec chemin de fichier dans le scénario d'API |
| `unsupported_region` | 422 | région absente des plans |
| `limit_exceeded` | 413 / 422 | corps, page, événements, dispositifs, transmissions |
| `not_found` | 404 | `run_id` inconnu ou supprimé |
| `conflict` | 409 | résumé demandé avant la fin, annulation d'un run terminé |
| `run_failed` | 500 (dans `RunStatus.problem`) | échec pendant le calcul |
| `unauthorized` | 401 | jeton absent, invalide ou révoqué |
| `rate_limited` | 429 | trop de requêtes pour ce jeton (en-tête `Retry-After`) |

## 6. Sécurité (exigences de mise en œuvre)

- Validation côté serveur de toute entrée, y compris les champs déjà validés côté navigateur.
- YAML : `yaml.safe_load` uniquement (déjà le cas dans `lsim.scenario`).
- Pas de chemin de fichier venant du client ; le catalogue de reliefs est un répertoire serveur fixe.
- Limite de débit (120 par minute, rafale 60) et file bornée par jeton : implémentées en v1.
- Authentification par **jeton d'accès** (choix utilisateur) :
  - en-tête `Authorization: Bearer <jeton>` sur toutes les routes sauf la santé ;
  - jeton aléatoire d'au moins 256 bits (`secrets.token_urlsafe(32)`), émis hors de l'API
    (commande d'administration), affiché une seule fois ;
  - en base, seul le SHA-256 du jeton est stocké ; jamais le jeton en clair, ni dans les journaux ;
  - comparaison en temps constant (`hmac.compare_digest`) ;
  - jeton absent ou invalide : 401 `unauthorized`, sans indiquer lequel ;
  - révocation immédiate, et date d'expiration optionnelle ;
  - un jeton ne donne accès qu'aux runs qu'il a créés (contrôle par propriétaire) ;
  - HTTPS obligatoire hors machine de confiance (le jeton circule dans l'en-tête).
  Le serveur refuse une adresse non locale sans TLS (`--tls-cert`, `--tls-key`).
- En-têtes : CORS désactivé (même origine), `Content-Security-Policy` stricte côté `web/`.

## 7. Régions et configuration

`GET /regions` renvoie, pour chaque plan, les canaux par défaut, les débits (SF, BW, indice
DNONLY), la fréquence et le débit RX2 et les charges N par DR. Ce sont les valeurs des modules
régionaux (`python/lsim/*.py`), avec leurs limites documentées dans `docs/USAGE.md`. Le panneau de
configuration du navigateur n'invente aucune valeur : il lit cette réponse.

## 8. Ce qui n'est pas dans le contrat v1

- Mode exercices et vérification automatique (demande de l'utilisateur, à définir après la v1 de
  l'animation) ;
- rendu 3D en gros plan, tuiles cartographiques sous contrat (point C, hors protocole) ;
- multi-utilisateurs et comptes ;
- modification d'un run en cours.

## 9. Prochaines étapes

1. Données MNT réelles : à vérifier avant tout usage d'étude (les exemples sont synthétiques).
2. ~~Exposer `events`~~ : fait (pagination par `seq`).
3. ~~Implémenter le serveur~~ : fait (v1). ~~Relief (catalogue)~~ : fait. ~~Énergie avec protocole ou
   multi~~ : fait. ~~Join en multi-passerelles~~ : fait. Reste : mesh (trace par saut, à concevoir).
4. Construire `web/` contre le contrat, sans appel à une route qui n'existe pas dans `docs/`.

## Relais mesh et passerelles multiples (scénario)

Ajouts additifs au schéma `scenario_input` (aucune clé existante retirée ou modifiée) :

- `gateways` : liste de passerelles nommées (`name`, `profile`, `mesh`), alternative à `gateway`.
- `mesh` : bloc de backhaul (`border`, `spreading_factor`, `bandwidth_khz`, `coding_rate`,
  `max_hops`, `capture_db`, `suppress_duplicates`, `relay_backoff_airtimes`, `frame_size`,
  `payload_bytes`).

Les schémas `run_create`, `validate_request` et `scenario_input` sont régénérés depuis la racine
du dépôt (`PYTHONPATH=python python -m lsim.api_contract schemas/api/v1`) ; `terrain_list` est ajouté
(`terrain_id` dans `run_create` et `validate_request`). Détail du comportement : `docs/USAGE.md`
section 5sexies.
