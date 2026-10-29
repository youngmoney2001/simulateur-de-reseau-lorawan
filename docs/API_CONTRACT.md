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
| POST | `/api/v1/runs` | Crée un run (file d'attente) | 202 + `RunStatus` (`state: queued`) |
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

**Point bloquant (à traiter avant l'étape 3)** : aujourd'hui, le moteur natif ne renvoie que des
compteurs par dispositif (`Counters`, `GatewayLoad`) ; il n'exporte pas une trace par trame. Les
join-accept, ACK et downlinks sont traités par la couche Python (`lsim.uplink`, `lsim.join_server`)
sur des paquets un par un. Il faut donc :
1. exporter une trace par transmission depuis le cœur (file d'événements, déjà interne) ;
2. produire les événements de jointure, ACK et downlink à partir de la couche protocole, avec le
   même `t_ns` que le moteur.

Tant que ces deux points ne sont pas faits, `events` renvoie 409 `run_failed` ou une liste vide
signalée dans `RunStatus`, et l'animation n'est pas disponible. Les totaux (`summary`, `devices`)
sont déjà disponibles.

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

## 6. Sécurité (exigences de mise en œuvre)

- Validation côté serveur de toute entrée, y compris les champs déjà validés côté navigateur.
- YAML : `yaml.safe_load` uniquement (déjà le cas dans `lsim.scenario`).
- Pas de chemin de fichier venant du client ; le catalogue de reliefs est un répertoire serveur fixe.
- Limite de débit et file bornée par utilisateur (à définir avec l'authentification).
- Authentification : **non définie**. Tant qu'elle ne l'est pas, l'API n'écoute que sur une
  machine de confiance. Un déploiement multi-utilisateurs exige un choix (jeton, session, SSO).
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

1. Trancher l'authentification et le catalogue de reliefs (décision utilisateur).
2. Exporter la trace par transmission du cœur natif et la couche protocole (voir §4).
3. Implémenter le serveur (`python/lsim/api_server.py`) selon ce contrat, avec tests de
   contrat (chaque réponse validée par son schéma).
4. Construire `web/` contre le contrat, sans appel à une route qui n'existe pas dans `docs/`.
