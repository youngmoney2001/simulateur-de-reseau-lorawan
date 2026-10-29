# Panneau d'étude étudiant : spécification (brouillon, non implémentée)

Statut : **proposition**, à valider avant tout code d'interface. Périmètre : `web/` et le contrat
d'API (`docs/API_CONTRACT.md`). Le moteur (`core/`, `python/lsim/`) n'est modifié que là où ce
document le signale.

## 1. Objectif et public

Un panneau pédagogique, sur le modèle des simulateurs de réseau pour la formation CCNA : on
construit une topologie, on configure chaque équipement en ligne de commande, on lance la
simulation et on observe les trames, puis un exercice vérifie le résultat automatiquement.

Public : étudiants en réseaux LoRaWAN, puis ingénieurs qui se forment sur un plan de réseau
donné. Le panneau n'a pas vocation à reproduire un firmware réel : il reproduit une **interface
de configuration** et un **comportement modélisé**.

## 2. Précision sur « mesh »

LoRaWAN n'a pas de routage mesh entre capteurs. Les capteurs émettent directement vers les
passerelles (étoile d'étoiles). Le « mesh » retenu ici est donc le **backhaul maillé entre
passerelles** : chaque passerelle reçoit en radio, et les passerelles se relient entre elles en
IP (filaire ou sans fil) jusqu'à un serveur. Les capteurs ne relaient jamais les messages des
autres. Un relais de type répéteur radio est hors périmètre (voir §9).

Hypothèse à confirmer par l'auteur (§10, question 1).

## 3. Équipements

| Équipement | Rôle | Configuration (CLI) |
|---|---|---|
| Capteur (end device) | Émet en classe A (classe B hors périmètre initial) | Plan régional, débit, puissance, période, clés (masquées) |
| Passerelle (gateway) | Reçoit en radio, relaie vers le serveur | Plan régional, sous-bande, antenne, puissance TX, serveur, interface backhaul |
| Nœud de backhaul (routeur IP) | Relie les passerelles entre elles | Interfaces, adresses, routes, coût de lien |
| Serveur de jointure et réseau | Jointure, déduplication, acquittements | NetID, plan, clés (masquées), adresse |
| Application | Reçoit les données | Hors CLI |

## 4. Interface de configuration (style IOS)

### 4.1 Modes

| Invite | Mode | Accès |
|---|---|---|
| `gw1>` | Utilisateur | Par défaut ; `show` limité |
| `gw1#` | Privilégié | `enable` |
| `gw1(config)#` | Configuration globale | `configure terminal` |
| `gw1(config-if)#` | Interface (radio ou backhaul) | `interface lora 0`, `interface eth 0` |
| `gw1(config-router)#` | Routage backhaul | `router ...` |

Chaque équipement a son propre état. `exit`, `end`, `?` (aide contextuelle) et l'auto-complétion
suivent les conventions IOS. Les erreurs de syntaxe affichent la position du caractère fautif, comme
IOS (`% Invalid input detected at '^' marker.`).

### 4.2 Commandes (noyau proposé)

Radio (interface `lora 0`) :

- `region EU868|US915|AU915|AS923|KR920|IN865|RU864` : plan régional (lecture seule sur capteur) ;
- `sub-band N` (US915/AU915) ;
- `tx-power DBM` ; `antenna gain DBI` ;
- `frequency MHZ` (dans le plan).

Passerelle (config globale) :

- `lorawan net-id HEX6` ; `lorawan server ADDR port up-PORT down-PORT` (GWMP) ;
- `lorawan transport udp|basicstation` ;
- `lorawan location X Y` (coordonnées en mètres ou lat/lon).

Backhaul (interface `eth 0` ou `wifi-mesh 0`) :

- `ip address ADDR/MASK` ; `link-cost N` ; `no shutdown` / `shutdown` ;
- `ip route PREFIX via NEXT-HOP` (routage statique) ; `router ospf`/`router rip` hors périmètre initial.

Vérification (`show`) :

- `show version`, `show running-config`, `show interfaces`, `show lorawan devices`,
  `show lorawan sessions`, `show ip route`, `show lorawan counters` (pertes par cause).

Gestion :

- `copy running-config startup-config` ; `reload` (efface l'état non sauvegardé) ;
- `write erase` pour réinitialiser un équipement d'exercice.

Les mots de passe, clés et `LSIM_*` ne sont jamais affichés : `show running-config` masque les
clés en `******`, conformément au contrat d'API (aucune clé dans une réponse).

### 4.3 Règles de cohérence (contrôlées par le moteur, pas par l'interface)

- Une passerelle et ses capteurs doivent partager le même plan régional : sinon les trames sont
  perdues (issue explicite, pas silencieuse).
- Une passerelle sans `lorawan server` ou sans liaison backhaul vers un serveur ne relaie rien.
- Un `shutdown` sur l'interface backhaul coupe le relais ; les trames déjà reçues sont
  comptées comme `lost_backhaul`.

## 5. Ce que le moteur doit gagner

Les commandes ci-dessus correspondent à des paramètres qui existent, sauf les points suivants :

1. **Plusieurs passerelles** : le moteur ne gère qu'une passerelle (`Gateway` dans
   `python/lsim/simulator.py`). Il faut calculer la réception par passerelle, puis dédupliquer
   au serveur (une copie retenue : la meilleure ou la première). C'est le cœur du protocole
   LoRaWAN en réseau dense et la condition du backhaul.
2. **Backhaul** : modèle de lien IP (délai, perte, débit, coût) entre passerelles et serveur.
   Aujourd'hui le backhaul est sans perte et sans délai (`ROADMAP`). Il faut un modèle
   explicite, avec des valeurs sourcées ou marquées hypothétiques.
3. **Routage** : pour un réseau simple, routage statique. Un protocole de routage dynamique
   (OSPF, RPL, etc.) n'est pas inventé : il sera ajouté seulement sur une spécification publiée.
4. **Sensibilité** : la référence reste SX1276 tant que la fiche SX1262 n'est pas intégrée
   (`device_rx_offset_db` en attendant).

## 6. Exercices avec vérification automatique

Un exercice est un fichier qui contient :

- une topologie de départ (capteurs, passerelles, backhaul, serveur) ;
- un énoncé (par exemple « faire parvenir 95 % des messages du capteur C au serveur ») ;
- une liste de contraintes vérifiées : configuration (`show running-config` attendu),
  connectivité (`ping` modélisé entre deux nœuds), résultat de simulation (PDR, latence,
  passerelle utilisée) ;
- un barème et des indices (non donnés d'emblée).

La vérification se fait côté serveur, sur un état de simulation, jamais sur une réponse
envoyée par le navigateur. L'étudiant ne voit pas la solution de référence.

Exemples d'exercices (indicatifs) :

1. Configurer une passerelle sur le plan EU868 et vérifier qu'un capteur est joint.
2. Ajouter une seconde passerelle pour couvrir un capteur masqué, puis relier les deux
   passerelles au serveur par backhaul.
3. Corriger un plan régional incohérent entre capteur et passerelle.
4. Choisir une sous-bande US915 pour éviter une collision avec un autre groupe.

## 7. Contrat d'API à ajouter (proposition, non implémentée)

| Méthode | Chemin | Rôle |
|---|---|---|
| POST | `/api/v1/sessions/{id}/cli` | Exécute une commande dans un mode donné ; réponse : sortie et nouveau mode |
| GET | `/api/v1/sessions/{id}/topology` | État de la topologie et des configurations (secrets masqués) |
| POST | `/api/v1/exercises/{id}/check` | Vérifie la solution de l'étudiant (côté serveur) |
| GET | `/api/v1/exercises` | Catalogue des exercices (sans solution) |

Chaque session est liée à un identifiant d'utilisateur et protégée par le jeton prévu dans le
contrat (authentification à implémenter, voir `docs/API_CONTRACT.md`). Les tentatives de
configuration sont journalisées sans secrets.

## 8. Phasage proposé

1. Spécification validée (ce document) et ajout au contrat.
2. Moteur multi-passerelles avec déduplication, tests C++ et Python.
3. Modèle de backhaul et routage statique.
4. CLI d'un équipement (une passerelle), tests de la grammaire et des erreurs.
5. Topologie multi-équipements et simulation pas à pas.
6. Exercices et vérification côté serveur.
7. Interface graphique (éditeur de topologie, animation des trames, journal par saut).

## 9. Hors périmètre initial

- Relais ou répéteur radio entre capteurs (non standard LoRaWAN) ;
- classe B et classe C (classe A seulement au départ) ;
- firmware réel, émulation binaire d'un équipement physique ;
- protocoles de routage dynamiques non publiés ;
- multi-utilisateurs et paquets macOS/Windows (voir la feuille de route).

## 10. Questions ouvertes

1. Le « mesh » visé est-il bien le backhaul maillé entre passerelles (§2) ? Sinon, préciser.
2. La CLI doit-elle être **fidèle à IOS** (syntaxe et messages), ou seulement inspirée de celle-ci ?
3. Les exercices sont-ils notés (score) ou seulement validés (réussi/échoué) ?
4. Les équipements sont-ils des modèles génériques, ou des références commerciales (RAK, Dragino,
   Kerlink) avec leurs commandes propres ?
