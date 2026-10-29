# Contrat d'API moteur ↔ navigateur (v1)

Statut : **proposé**, non implémenté. Les formes de données sont dans
`python/lsim/api_contract.py` ; les schémas JSON publiés sont dans `schemas/api/v1/`. Les tests
(`python/tests/test_api_contract.py`) vérifient que les schémas restent synchronisés avec le code.

Régénérer les schémas après une modification :

```bash
cd python && python -m lsim.api_contract ../schemas/api/v1
```

## 1. Principes

| Sujet | Règle |
|---|---|
| Transport | HTTP/1.1 JSON, préfixe `/api/v1`. Le navigateur n'appelle que des chemins relatifs ; en développement, Vite fait le relais vers le serveur Python. Aucun `localhost` dans le code du navigateur. |
| Calcul | Tout calcul radio, réseau et crypto est fait côté Python / cœur C++. Le navigateur affiche et rejoue. |
| Fichiers | Le navigateur ne fournit jamais de chemin de fichier. Le relief (`terrain`) est refusé dans le scénario d'API ; il sera désigné par un identifiant de catalogue serveur (à définir). |
| Secrets | Aucune clé (NwkSKey, AppSKey, clés de jointure, `LSIM_DATA_KEY`) dans une réponse, un journal ou un événement. |
| Erreurs | Format `Problem` (code stable + message), HTTP 4xx pour l'entrée, 5xx pour le serveur. Pas de trace Python dans la réponse. |
| Bornes | Corps de requête et réponses non paginées : 256 KiB. Événements par run : 200 000 au plus. Page : 500 éléments au plus. Dispositifs et transmissions : bornes de `ScenarioModel`. |
| Version | Le préfixe `/v1` ne change qu'en cas de rupture. Ajout de champ optionnel = compatible. Les réponses refusent les champs inconnus côté client. |

## 2. Points d'accès

| Méthode | Chemin | Rôle | Réponse |
|---|---|---|---|
| GET | `/api/v1/regions` | Plans régionaux (lecture seule) : canaux, débits, RX2, charges N | `RegionList` |
| POST | `/api/v1/scenarios/validate` | Valide un scénario sans lancer de calcul | `ValidateResponse` (`valid`, `scenario_sha256`, `problems`) |
| POST | `/api/v1/runs` | Crée un run (file d'attente), options `protocol` incluses | 202 + `RunStatus` (`state: queued`) |
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
- Limites assumées : le backhaul passerelle → serveur et le join-accept transmis par le serveur
  sont sans perte (`delivered`) ; sensibilité du récepteur de référence (SX1276) plus
  `device_rx_offset_db` ; une seule passerelle.
- Options applicatives dans `RunCreate.protocol` : `join`, `confirmed_uplinks`, `downlink_every`,
  `downlink_payload_bytes`, `gateway_tx_power_dbm`, `device_antenna_gain_dbi`, `device_rx_offset_db`
  (par défaut : aucune charge ; seuls uplinks, pertes et ACK/join-accept sont produits quand les
  options correspondantes sont activées).

Tant que la route `events` n'existe pas, l'animation n'est pas disponible côté navigateur ; les
totaux (`summary`, `devices`) le sont.

## 5. Erreurs

Corps `Problem` :

```json
{"code": "validation_error", "message": "groups.0.count : …", "field": "groups.0.count"}
```

| `code` | HTTP | Cas |
|---|---|---|
| `validation_error` | 422 | scénario ou requête invalide |
| `terrain_not_allowed` | 422 | `terrain` présent dans le scénario d'API |
| `unsupported_region` | 422 | région absente des plans |
| `limit_exceeded` | 413 / 422 | corps, page, événements, dispositifs, transmissions |
| `not_found` | 404 | `run_id` inconnu ou supprimé |
| `conflict` | 409 | résumé demandé avant la fin, annulation d'un run terminé |
| `run_failed` | 500 (dans `RunStatus.problem`) | échec pendant le calcul |
| `unauthorized` | 401 | jeton absent, invalide ou révoqué |

## 6. Sécurité (exigences de mise en œuvre)

- Validation côté serveur de toute entrée, y compris les champs déjà validés côté navigateur.
- YAML : `yaml.safe_load` uniquement (déjà le cas dans `lsim.scenario`).
- Pas de chemin de fichier venant du client ; le catalogue de reliefs est un répertoire serveur fixe.
- Limite de débit et file bornée par jeton.
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
  Tant que le serveur n'existe pas, l'API n'écoute que sur une machine de confiance.
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

1. Catalogue de reliefs (décision utilisateur ; données MNT à vérifier avant intégration).
2. Exposer `events` à partir de `lsim.trace_events` (pagination par `seq`).
3. Implémenter le serveur (`python/lsim/api_server.py`) selon ce contrat, avec tests de
   contrat (chaque réponse validée par son schéma).
4. Construire `web/` contre le contrat, sans appel à une route qui n'existe pas dans `docs/`.

## Relais mesh et passerelles multiples (scénario)

Ajouts additifs au schéma `scenario_input` (aucune clé existante retirée ou modifiée) :

- `gateways` : liste de passerelles nommées (`name`, `profile`, `mesh`), alternative à `gateway`.
- `mesh` : bloc de backhaul (`border`, `spreading_factor`, `bandwidth_khz`, `coding_rate`,
  `max_hops`, `capture_db`, `suppress_duplicates`, `relay_backoff_airtimes`, `frame_size`,
  `payload_bytes`).

Les schémas `run_create`, `validate_request` et `scenario_input` sont régénérés depuis la racine
du dépôt (`PYTHONPATH=python python -m lsim.api_contract`). Détail du comportement : `docs/USAGE.md`
section 5sexies.
