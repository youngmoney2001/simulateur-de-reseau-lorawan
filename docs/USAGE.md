# Utilisation du simulateur lsim

Ce document décrit l'utilisation courante. Les hypothèses de modélisation sont dans
`docs/ROADMAP.md` (limites listées par fonctionnalité) et les sources réglementaires dans
`docs/REGULATORY_SOURCES.md`.

## 1. Installation

Prérequis : Python ≥ 3.10, CMake, un compilateur C++17. mbedTLS est récupéré automatiquement
par CMake (accès à GitHub requis).

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --parallel
pip install -e "python[data,report,test]"      # données, rapports, tests
```

La bibliothèque native est cherchée dans `build/` ; sinon, indiquer son chemin :

```bash
export LSIM_LIBRARY=/chemin/vers/liblsim_core.so
```

Un paquet binaire du cœur natif (Linux) s'obtient avec `scripts/package_native.sh`
(archive et empreinte SHA-256 dans `dist/`).

## 2. Scénario

Un scénario est un fichier YAML validé strictement (champs inconnus refusés).
Exemple complet : `examples/quartier_sf9.yaml` (500 compteurs autour d'une passerelle).

Champs principaux :

| Champ | Rôle |
|---|---|
| `schema_version` | toujours `1` |
| `name`, `seed` | nom et graine (déterminisme) |
| `gateway` | position `x_m`, `y_m` et gain d'antenne |
| `propagation` | fréquence, distance de référence, exposant, seuil de capture, shadowing |
| `environment` | obstacles (perte fixe ou matériau + épaisseur) et relief (optionnel) |
| `groups` | populations : placement, SF, charge utile, puissance, période, messages |

Un groupe peut porter une région (`region`, ex. `EU868`) : le duty cycle effectif est alors le
plus restrictif entre `duty_cycle` et la sous-bande de `channel_freq_hz`.

Le YAML ne porte **aucun frontal RF** : ni `rf:` à la racine, ni `rf:` dans un groupe (champ
refusé). Les gains d'antenne et pertes de câble se déclarent uniquement dans l'API Python, par
`DeviceRf` / `GatewayRf`. Périmètre complet : `docs/RF_MODEL.md` §7 et §8.

## 3. Ligne de commande

```bash
python -m lsim run examples/quartier_sf9.yaml -o resultats.parquet
python -m lsim run examples/quartier_sf9.yaml -o resultats.parquet --energy-profile rak4631
python -m lsim report examples/quartier_sf9.yaml -o rapport.pdf
python -m lsim report examples/quartier_sf9.yaml -o rapport.xlsx --energy-profile sx1262-stm32l072
python -m lsim geojson examples/quartier_sf9.yaml -o carte.geojson --origin 4.0511,9.7679
python -m lsim calibrate mesures.csv --d0 1.0 --json
```

- `run` : résultats par dispositif (Parquet, zstd). Les métadonnées portent l'empreinte
  SHA-256 du scénario, la version et la graine.
- `report` : synthèse et tableau par dispositif, en PDF ou Excel. Le format vient de l'extension.
- `geojson` : carte géoréférencée (`--dem` pour écrire le relief lorsque le scénario en a un).
- `calibrate` : ajuste la loi log-distance sur un CSV `distance_m,path_loss_db`.

## 4. Profil énergie (au choix)

L'énergie est calculée par le cœur natif, en classe A, pour un message par période du groupe
(deux fenêtres RX1/RX2 ouvertes pendant le préambule, veille sur le reste).

| Profil | Description | Option |
|---|---|---|
| `rak4631` (défaut dans `report`) | module RAKwireless (nRF52840 + SX1262), MCU inclus | `--energy-profile rak4631` |
| `sx1262-stm32l072` | puce SX1262 et MCU STM32L072 séparés | `--energy-profile sx1262-stm32l072` |

- `run` : sans option, pas de colonnes énergie. Avec option, le Parquet ajoute
  `energy_per_message_j` et `average_current_ua`.
- `report` : colonnes « Énergie par message (mJ) » et « Courant moyen (µA) », et une ligne
  « Profil énergie » dans la synthèse.
- En Python : `run_scenario(scenario, energy_profile="sx1262-stm32l072")`.

Sources et réserves des valeurs : `core/include/lsim/energy.hpp`. En bref : le STM32L072 Run
est une valeur « jusqu'à » (basse), le Rx du SX1262 n'est publié que pour 125 kHz.

## 5. Utilisation en Python

```python
from lsim.export import run_scenario
from lsim.scenario import load_scenario

scenario = load_scenario("examples/quartier_sf9.yaml")
result = run_scenario(scenario, energy_profile="rak4631")
print(result.pdr, result.totals.received)
print(result.rows[0].energy_per_message_j)
```

Le hash du scénario est stable : deux exécutions avec la même graine donnent les mêmes compteurs.

## 5bis. Serveur de jointure pour passerelles (Semtech UDP)

```bash
pip install -e 'python[serve]'          # installe cryptography (chiffrement au repos)
export LSIM_INTEGRITY_KEY=<32 caractères hexadécimaux, stockés hors dépôt>
export LSIM_DATA_KEY=<64 caractères hexadécimaux, AES-256, stockée hors dépôt et hors base>
python -m lsim serve --host 0.0.0.0 --port 1700 --db joins.sqlite --keys keys.json --net-id 000013 --region EU868
```

Le plan régional (`--region`) doit être celui de la passerelle : `EU868` (défaut), `US915` ou `AU915`.

- `keys.json` : `{"devices": {"<DevEUI hex>": {"nwk_key": "<32 hex>", "app_key": "<32 hex, optionnel>"}}}`, mode 600 exigé. Le DevEUI s'écrit en ordre d'affichage (comme dans TTN) ; le serveur fait la conversion.
- Passerelle : pointer le packet forwarder vers ce serveur (`server_address`, ports up/down).
- Jointure : join-request valide → join-accept en PULL_RESP, à `tmst + 5 s` (RP002 §2.3), sur la fenêtre RX1 du plan (`lsim.plan`). La session de données (clés de session 1.1, compteurs) est créée dans la même transaction.
- Données :
  - uplink confirmé ou non confirmé vérifié avec le compteur 32 bits reconstruit depuis le FCnt 16 bits, TxDr et TxCh du plan ;
  - rejeu, compteur ancien et MIC faux : rejetés, sans changement d'état ;
  - uplink confirmé : ACK en downlink RX1 à `tmst + 1 s` ; retransmission identique ré-acquittée ;
  - downlink mis en file avec `lsim downlink`, émis en RX1 au prochain uplink (un seul par uplink) ; FPort 1 à 223 ; FPort > 0 exige `app_key`.
- Chiffrement au repos : clés de session, compteurs et charges en file sont chiffrés (AES-256-GCM, `lsim/sealed.py`) avec `LSIM_DATA_KEY`. Chaque enregistrement est lié à son DevAddr ou DevEUI : un enregistrement déplacé ou modifié est refusé. Une base créée avant ce format est refusée (aucune base de production n'existait).
- Fichier de base SQLite créé en mode 0600 ; une base accessible par d'autres utilisateurs est refusée.

```bash
python -m lsim downlink --db joins.sqlite --dev-eui 0102030405060708 --fport 1 --payload-hex 0102 --region US915
python -m lsim downlink --db joins.sqlite --dev-eui 0102030405060708 --fport 1 --payload-hex 0102 --region AU915
python -m lsim downlink --db joins.sqlite --dev-eui 0102030405060708 --fport 2 --payload-hex 00 --confirmed
```

Charges maximales en file (fenêtres RX1 atteignables, plus petite valeur N du plan) : EU868 51 octets, US915 et AU915 222 octets.

Limites des trames de données :

- Livraison au mieux : un downlink est retiré de la file à son émission ; pas de retransmission. Un downlink confirmé sans acquittement à l'uplink suivant est considéré perdu.
- Une seule copie est traitée : avec plusieurs passerelles, les copies suivantes sont rejetées comme rejeu.
- FPending, ADR et commandes MAC (FOpts, FPort 0) ne sont pas interprétés.
- Canal ou débit hors du plan : rejet (le MIC 1.1 exige TxCh et TxDr).
- US915 et AU915 : le groupe de scénario peut porter `sub_band` (1 à 8) ; son canal doit alors appartenir à la sous-bande. Règle LinkADRReq (ChMaskCntl 0 à 7) dans `lsim.channel_mask`.
- Sous-bande de la passerelle (`lsim serve --region US915|AU915 --sub-band N`, défaut 1) : la passerelle Basic Station annonce les 8 canaux 125 kHz et le canal 500 kHz de la sous-bande (radio_0, radio_1 pour le 500 kHz). À chaque jointure, le serveur envoie un LinkADRReq (ChMaskCntl 5, DataRate et TXPower ignorés) qui restreint le dispositif à cette sous-bande. Il part en FOpts du downlink et est renvoyé à chaque downlink tant que le dispositif ne répond pas par un LinkADRAns complet (débit, puissance, masque). TS001 §5 ne fixe ni plafond ni backoff pour cette réémission : aucun plafond par défaut (`MAC_MAX_ATTEMPTS = None`, facultatif). La demande est persistée dans la table `mac_pending`. **Comportement actuel du chemin en direct :** un LinkADRAns négatif (au moins un bit à 0) ferme la demande, est journalisé, et la même configuration n'est pas renvoyée (refus non persisté). Un refus partiel n'est pas gardé ouvert sur ce chemin : ce traitement, prévu par le modèle de canaux, est reporté à l'étape 7. Le modèle d'exclusions par canal (refus attribué aux suspects, exclusions de 100 uplinks, trace interne) n'est implémenté que dans la boucle fermée C++ ; voir `docs/CHANNEL_MASK_MODEL.md`. La trace v3 n'est pas exposée par l'interface Python. Limite du chemin en direct : `answer_ok` (ABI v2) ne porte que les bits débit et puissance ; `ChannelMaskACK` n'est pas transmis. Limites : le dispositif ne reçoit la commande que s'il ouvre RX1 après un uplink ; une passerelle Semtech UDP se configure côté passerelle (GWMP ne permet pas au serveur de changer son plan de canaux) ; LR-FHSS non géré (voir section 5quater).
- AU915 : RX1 suit le canal montant modulo 8 et la table RX1DROffset 0 (DR0→DR10 … DR6→DR11, RP002-1.0.3) ; les charges maximales sont celles de la table « not repeater compatible » (RP002-1.0.2), à confirmer contre le PDF complet ; pas de fenêtre de répéteur.
- Pas de limite d'écart de compteur (MAX_FCNT_GAP supprimé en 1.0.4+) : l'intégrité repose sur le MIC.
- Pas de rotation de la clé de données ; une restauration complète d'une ancienne base rétablit ses compteurs (la protection relève de la sauvegarde).
- Basic Station : voir section 5ter. Plan AS923 (`--region AS923`) : canaux 923,2 et 923,4 MHz, DR0 à DR6, RX1 même canal et même débit (RX1DROffset 0), RX2 923,2 MHz DR2, charge N 51/115/222 selon le débit. DownLinkDwellTime (400 ms) non modélisé. Plan KR920 (`--region KR920`) : canaux 922,1 / 922,3 / 922,5 MHz, DR0 à DR5, RX1 même canal et même débit, RX2 921,9 MHz DR0, charges N 51/115/222 (prudentes, voir `python/lsim/kr920.py`). Plan IN865 (`--region IN865`) : canaux 865,0625 / 865,4025 / 865,985 MHz, DR0 à DR5, RX1 même canal et même débit, RX2 866,550 MHz DR2, charges N prudentes (voir `python/lsim/in865.py`). Plan RU864 (`--region RU864`) : canaux 868,9 / 869,1 MHz, DR0 à DR6, RX1 même canal et même débit, RX2 869,1 MHz DR0 (voir `python/lsim/ru864.py`).

## 5ter. Passerelles Basic Station (WebSocket)

Même cœur que le serveur UDP (jointure, trames de données, file de downlinks, chiffrement au
repos) ; seul le transport change. Les RAKwireless et autres passerelles Basic Station s'y
connectent en WebSocket (`ws://` ou `wss://`).

```bash
python -m lsim serve --transport basicstation --host 0.0.0.0 --port 8887 \
  --db joins.sqlite --keys keys.json --net-id 000013 --region AU915 \
  --uri wss://lns.example.org:8887/ws --tls-cert cert.pem --tls-key key.pem
```

- `--uri` : adresse publique annoncée aux passerelles lors de la découverte (`ws://` ou `wss://`).
  Obligatoire.
- TLS : `--tls-cert` et `--tls-key` vont ensemble (TLS 1.2 minimum). Sans TLS, le serveur n'écoute
  en clair qu'en boucle locale : hors boucle locale, il journalise un avertissement. En production,
  utiliser TLS ici ou un proxy TLS devant le serveur.
- `--hwspec` : matériel annoncé dans `router_config`, forme `sx1301/N` (défaut `sx1301/1`). Station
  n'accepte que ce préfixe (aucun `sx1302/` dans ses sources), y compris pour les concentrateurs
  SX1302. Une autre valeur est refusée au démarrage.
- Routes : `…/router-info` (découverte : `router` → `muxs`, `uri`) ; toute autre cible est une
  session de données, ouverte après un `version`.
- `router_config` : plan régional (`--region`), NetID, bornes de fréquence, tables DR (16 entrées),
  et `sx1301_conf` pour un concentrateur de 8 canaux (les 8 premiers canaux montants du plan).
- Jointure et données : même logique que le serveur UDP. Un join-accept est un `dnmsg` avec
  `RxDelay` 5 s ; un ACK ou un downlink de file, `RxDelay` 1 s ; RX2 du plan dans le message.
- Acquittement `dntxed`, `timesync` (avec `gpstime`) et messages inconnus : comptés, sans effet.
- Sécurité : taille de message bornée (16 Kio), trames masquées obligatoires, RSV refusés, UTF-8
  vérifié, délai de handshake 10 s, inactivité 300 s, nombre de connexions borné (503 au-delà).

**Ordre des identifiants** : `keys.json` et `lsim downlink --dev-eui` attendent le DevEUI en
**ordre d'affichage** (comme TTN et Basic Station). Le cœur travaille en ordre de transmission
(LSB first) ; la conversion est faite une seule fois, à la lecture de `keys.json` et à la mise en
file. Exemple : le DevEUI affiché `08-07-06-05-04-03-02-01` s'écrit `0807060504030201`.

**Limites** : authentification des passerelles seulement par TLS (pas de certificat client ni de
jeton) ; `router` en format ID6 non accepté (EUI ou entier seulement) ; un seul concentrateur et
seulement les 8 canaux 125 kHz de la sous-bande choisie (`--sub-band`, défaut 1 pour US915 et AU915 ; les 8 premiers canaux pour EU868). Le canal 500 kHz de la sous-bande est aussi annoncé. Pas de
LR-FHSS, refusé) ; pas de beacon, de Class B/C ni de `rmtsh` ; formats EUI et MIC (petit-boutiste) validés
conformes aux vecteurs de test officiels de Basic Station (`selftest_lora.c`) ; reste à confirmer
sur une passerelle réelle (non disponible pour ces essais).

## 5quater. LR-FHSS (non géré)

Le serveur ne gère pas LR-FHSS. Décision documentée, pas un oubli :

- US915 : les débits DR5 (LR-FHSS CR1/3) et DR6 (LR-FHSS CR2/3) sont hors du plan. Un uplink DR5 ou DR6 est refusé en Semtech UDP (`datr` ou `modu` non LoRa) comme en Basic Station (débit hors plan) ; une jointure sur ce débit reçoit l'issue `join_unsupported_channel`, sans join-accept.
- Le plan AU915 ne déclare aucun débit LR-FHSS : une trame `modu` `LRFHSS` est refusée, mais DR5 (SF7/125) et DR6 (SF8/500) restent des débits LoRa gérés.
- Le DR RX1 d'un uplink LR-FHSS n'est donc jamais calculé, faute de source vérifiée.

Test de référence : `python/tests/test_lrfhss_unsupported.py`. Une prise en charge future demandera une capture `rxpk` réelle et une source officielle pour la fenêtre RX1.

## 5quinquies. MNT libre (Copernicus DEM GLO-30)

Source retenue : Copernicus DEM GLO-30, version publique (seau AWS `copernicus-dem-30m`, sans
compte). Usage commercial autorisé avec attribution ; le fichier `*.ATTRIBUTION.txt` produit par
l'outil reprend la mention à vérifier. Le 5 m de JAXA (ALOS World 3D) est un produit commercial : il
n'est pas utilisé.

Acquisition, sur le poste de l'opérateur (le serveur de simulation ne télécharge rien) :

```bash
pip install rasterio numpy
python scripts/fetch_copernicus_dem.py --bbox 9.5 3.8 9.9 4.2 --out data/douala_dem.csv
```

Le script reprojette en UTM (zone 32N pour Douala) à 30 m et écrit `x_m,y_m,z_m`. Il s'utilise
ensuite comme `terrain` du scénario (`type: dem_csv`, chemin relatif au YAML). Précautions :

- une tuile absente (HTTP 404) arrête le script : elle peut être de l'océan (pas de tuile) ou une
  tuile non publiée. La liste des tuiles non publiées est sur spacedata.copernicus.eu ; le
  Cameroun n'a pas été vérifié dans cette liste. `--allow-missing` remplace l'absence par 0 m, après
  avertissement ;
- les coins de la grille UTM, hors de la boîte demandée, valent 0 m ;
- les tuiles sont mises en cache dans `data/cache/copernicus_dem`, exclu du dépôt par `.gitignore`.

## 5sexies. Passerelles multiples et relais mesh

Plusieurs passerelles se déclarent dans `gateways` (au lieu de `gateway`). Chaque passerelle a un
`name` unique ; un `profile` du catalogue (`python/lsim/gateway_profiles.py`) est requis pour
qu'elle relaie.
Un profil « hôte » (RAK7391 : Raspberry Pi CM4 avec emplacements pour modules) ne publie aucun
paramètre radio : il est refusé comme passerelle radio, le module installé doit être déclaré.

- `mesh: true` : la passerelle relaie sur la bande mesh 2,4 GHz. Profil de relais : `rak5146-rak5148`
  (RAK5146 pour les capteurs sous-GHz, RAK5148 pour le lien mesh ; solution publiée par RAK, compatibilité
  logicielle **à valider** : essai ChirpStack Gateway OS ou confirmation RAK ; la sensibilité publiée entre dans la réception montante des accès par un décalage de -3 dB, modèle `decalage-uniforme-v1`, non calibré sur matériel). Un relais `rak5148` seul ne reçoit pas les capteurs sous-GHz : une région de
  groupe absente de ses bandes d'accès est refusée à la validation. Sans `mesh`, la passerelle a un backhaul
  IP direct vers le LNS.
- `mesh` (bloc de scénario) : `border` (nom de la passerelle frontière, `mesh: true`),
  `spreading_factor` (5 à 12), `bandwidth_khz` (203, 406, 812 ou 1625), `coding_rate`,
  `max_hops` (1 à 8, 8 par défaut), `capture_db`, `suppress_duplicates` (vrai par défaut),
  `relay_backoff_airtimes` (0 à 64, 4 par défaut), `frame_size` (`device` par défaut).
  - `frame_size: device` : une trame relayée fait sa taille PHY LoRaWAN (13 o + charge du
    dispositif) plus l'enveloppe mesh de 14 o en montant (ChirpStack Gateway Mesh).
  - `frame_size: fixed` : toutes les trames font `payload_bytes` (défaut 32 o, hypothèse
    d'avant la correction ; à utiliser pour comparer).
  - `shadowing_sigma_db` (0 à 30, 0 par défaut) : shadowing log-normal des liaisons entre
    passerelles, un tirage par paire, identique dans les deux sens ; graine
    `propagation.shadowing_seed`. Le shadowing de l'accès n'est pas repris sur le mesh.

Suppression des doublons : un relais ne transmet une trame qu'une fois. Il renonce à sa copie
s'il entend un autre relais transmettre la même trame avant son propre départ. Chaque relais
attend, avant de transmettre, un délai déterministe dans `[0, relay_backoff_airtimes × T_air)` :
sans attente, deux relais qui reçoivent la même trame au même instant partent ensemble et ne
s'entendent pas.

Une trame décodée par un relais suit le mesh saut par saut jusqu'à la frontière. Une trame est
remise au LNS si au moins une copie y arrive. Obstacles et relief sont pris en compte sur les
liens entre passerelles (calcul natif, antennes à hauteur passerelle).

`lsim run` affiche le bilan : remises directes et après saut mesh, émissions mesh, copies
supprimées, sauts perdus (collisions, demi-duplex), copies sans route, et la descente. La
descente est une borne optimiste : la réponse part de la frontière dès réception, redescend le
chemin inverse (un temps d'antenne mesh par saut, partagé avec les uplinks) et le relais l'émet en
RX1 (+1 s) ou, si RX1 est occupée côté passerelle, en RX2 (+2 s, SF du plan). Les collisions et
l'attente sur le retour sont comptées.

Par passerelle, la charge de réception (trames audibles, occupation, simultanéité) est remontée
dans le rapport et dans les métadonnées Parquet (`lsim.gateways`).

GeoJSON multi-passerelles : une passerelle, un point et une couverture par groupe ; la couverture
tient compte du relief et des obstacles.

Défaut : SF9 / 203 kHz (décision). SF12 / 203 kHz reste possible mais un acquittement relayé y
dure plus d'une seconde par saut et n'atteint plus RX1 ni RX2. Le SF et la bande se règlent
dans le bloc `mesh` ; le choix automatique par profil d'équipement n'est pas implémenté.

Limites : le retour de descente n'a pas de collision ; le shadowing mesh est un tirage par
paire (pas de variation dans le temps).

Exemple : `examples/mesh_relais_quartier.yaml`.

## 5septies. Studio web (panneau d'étude)

Lancer l'API (un seul serveur par fichier de runs) puis le studio :

```bash
python -m lsim.api_server issue-token --tokens tokens.json --owner alice     # jeton affiché une fois
python -m lsim.api_server serve --tokens tokens.json --runs-db runs.sqlite --port 8765
cd web && npm ci && LSIM_API_URL=http://127.0.0.1:8765 npx vite --port 5173  # page /studio.html
```

Le studio appelle `/api` (proxy Vite vers `LSIM_API_URL`). Le jeton est saisi dans la page ; il reste
dans l'onglet et n'apparaît jamais dans une URL. Tests : `npm test` (modules) et `npm run test:e2e`
(Chromium réel ; variables `CHROME_PATH`, `LSIM_LIBRARY`, `PYTHON`).

Deux réglages de l'atelier n'existent qu'entre ses murs, et valent d'être connus avant de s'en
servir — ils ne sont pas cosmétiques, ils changent l'issue du run.

**Modèle de la passerelle** (`gateway-profiles`). Quatre fiches constructeur. Le modèle décale le
seuil de réception de la différence entre la sensibilité publiée et la référence du moteur au même
point d'étalement et sur la même bande — et **seulement si la fiche publie ce point**. Trois des
quatre modèles ne le publient pas : le run les calcule à l'identique. Mesuré à 20 km, SF10, 20
trames : 0 reçue sans modèle, 0 avec `rak7249`, 20 avec `rak5146-rak5148` (−3 dB). L'atelier
annonce le décalage de chaque modèle, modèle par modèle.

**Obstacles, shadowing et hauteurs** (onglet « Obstacles »). Un mur se trace au rectangle sur le
plan métrique ; chaque mur porte une atténuation saisie en dB, ou un matériau et une épaisseur dont
le moteur calcule la perte (UIT-R P.2040-4). Rien n'est émis tant que rien n'est réglé : un
scénario sans environnement reste celui d'avant, empreinte comprise.

| Réglage | Ordre de grandeur mesuré |
|---|---|
| Mur en travers, 6 dB | à 10 km SF10 : 20 reçues sur 20 → **0 sur 20** |
| Hauteur de passerelle | face à un mur de 12 m : 0 à 15 m, **20 sur 20 à 40 m** |
| Shadowing σ = 8 dB | à 10 km, 40 graines : **30** restent entendues |
| Matériau à 868 MHz | **12 des 15** hors plage documentée : perte extrapolée |

Le caractère extrapolé est affiché à côté du matériau, et l'atténuation saisie reste le chemin
par défaut : à 868 MHz, seuls `air`, `wood` et `glass` sont dans la plage du Tableau 3.

### 5 bis. Remplacer P.2040-4 par une mesure (`material_calibration`)

Une mesure vaut mieux qu'une extrapolation. Elle se déclare dans l'environnement, matériau par
matériau, en dB par mètre :

```yaml
environment:
  material_calibration:
    concrete:
      loss_db_per_m: 60.0                        # mesure, dB/m
      provenance: "campagne Douala, 2026-04, 14 murs"
  obstacles:
    - x_min_m: -1
      y_min_m: -400
      x_max_m: 1
      y_max_m: 400
      height_m: 20.0
      material: concrete
      thickness_m: 0.25                          # perte = 60,0 × 0,25 = 15,0 dB
```

Trois points, pour que le résultat reste interprétable :

- la perte vaut `loss_db_per_m × thickness_m` : l'épaisseur reste celle de l'obstacle, seul le
  coefficient change ;
- la mesure **n'est pas une extrapolation**, et l'avertissement P.2040-4 ne la concerne donc
  pas — le faire porter sur un relevé ferait douter d'une valeur solide ;
- `provenance` est obligatoire, comme sur un relevé d'énergie : un chiffre sans origine se
  présente comme une donnée du moteur.

Un obstacle qui déclare `attenuation_db` au lieu d'un matériau n'est pas concerné : la
calibration porte sur un matériau, pas sur une valeur déjà saisie.

**Annuler et rétablir** (barre d'outils, `Ctrl+Z` / `Ctrl+Maj+Z`). L'historique vit côté serveur,
parce que le CLI y vit aussi : annuler « region US915 » restaure la configuration de l'équipement,
pas seulement la case que l'interface affichait. Un geste par opération — ajout, retrait,
déplacement, ligne CLI qui change la configuration, réglages de capteur, modèle de passerelle,
relief, environnement, ADR, protocole — et la navigation (lecture, indices, compilation) n'en est
pas un, ni un geste sans effet : quatre lignes tapées pour régler une région s'annulent d'un
seul coup, et déplacer un équipement sur place n'empile rien. Les deux boutons
sont grisés **avec leur raison** (« Rien à annuler ») et nomment l'opération qu'ils vont annuler ;
l'interface n'écrit aucun de ces libellés, c'est le serveur qui les porte dans chaque réponse.
Profondeur 50 ; les piles ne sont pas écrites dans le fichier de runs, une session rechargée après
redémarrage repart donc sans historique.

## 5octies. Retransmissions des uplinks confirmés

Un bloc `retransmissions:` **facultatif** transforme les uplinks du scénario en uplinks confirmés :
une trame non acquittée est réémise après RX2, dans la limite des tentatives.

```yaml
retransmissions:
  retries: 3                 # 0 à 7 ; 0 = aucune réémission (moteur actuel)
  retransmit_delay_ms: 3000  # >= 2000 : une réémission ne peut pas partir avant RX2
  enforce_duty_cycle: true   # refuse une réémission qui dépasserait le rapport cyclique
  energy_profile: rak4631    # facultatif : ajoute le relevé d'énergie
  ack_delay_ms: 0            # 0 à 60000 : retard du réseau avant d'émettre l'ACK
  ack_repetitions: 1         # 1 à 3 : copies du même ACK (même FCntDown)
  fcnt_up_start: 0           # premier FCntUp de chaque terminal (0 à 2^32-1)
  fcnt_down_start: 0         # premier compteur descendant (NFCntDown et AFCntDown)
  downlink_payload: false    # la descente porte une charge utile : AFCntDown, événement data_ack
  session_joins_s: []        # instants (s) des Join-Accept acceptés ; [] = une seule session
  join_requests_s: []        # instants (s) des Join-Request : jointure jouée par le moteur radio
  join_retries: 1            # 1 à 3 tentatives par jointure (10 s entre deux essais)
  join_accept_rx2_fallback: true  # RX2 seulement si RX1 n'a pas abouti (fenêtre de secours)
  join_accept_replays: 0     # 0 à 2 Join-Accept rejoués après acceptation (reçus puis refusés)
```

La classe d'écoute est une propriété du groupe :

```yaml
groups:
  - name: terminaux
    device_class: A          # A (défaut), B ou C — voir docs/MAC_CONSOLIDATION.md
```

| Règle | Comportement |
|---|---|
| Bloc absent | aucune réémission, chemin historique, hash inchangé |
| `retries: 0` | aucune transmission ajoutée : le scénario emprunte le chemin historique |
| Paramètre hors bornes, clé inconnue, profil d'énergie inconnu | `ValidationError` explicite |
| Rapport cyclique dépassé | la réémission est **refusée et comptée**, jamais forcée |
| Bloc `enabled: false` | équivaut à `retries: 0` |
| `ack_delay_ms` / `ack_repetitions` / `fcnt_up_start` / `fcnt_down_start` / `downlink_payload` / `session_joins_s` / `join_requests_s` / `join_retries` / `join_accept_rx2_fallback` / `join_accept_replays` / `device_class` à leur valeur par défaut | absents du hash : le hash d'un scénario écrit avant eux ne change pas |
| `session_joins_s` et `join_requests_s` ensemble | refusé : le modèle déclaré et le modèle radio sont exclusifs |
| Émetteur de la passerelle | une seule descente à la fois : Join-Accept, ACK et downlinks passent par le même arbitre (`lsim.arbitre`) |
| Join-Request et rapport cyclique | le budget du terminal s'applique ; une tentative refusée n'est **pas** émise (`enforce_duty_cycle` pour le désactiver) |
| `FCntUp` | identifie la trame : toutes les réémissions d'une même trame le partagent |
| `FCntDown` | série **par terminal** et **par série** (`NFCntDown` pour un ACK seul, `AFCntDown` sinon) ; un ACK émis consomme un numéro, ses copies le conservent |

### Émetteur partagé : Join-Accept, ACK et downlinks (D3.13)

Les descentes ne sont pas indépendantes : la passerelle n'a **qu'un émetteur**. Join-Accept RX1 et
RX2, ACK des uplinks et downlinks de données passent par le même arbitre
(`lsim.arbitre.GatewayArbiter`), dans l'ordre chronologique :

- une émission en cours en retarde une autre ;
- une descente dont la fenêtre est couverte **n'est pas émise** (`gateway_busy`) et n'occupe rien ;
- une trame montante qui chevauche une descente est perdue (demi-duplex, par le point fixe).

Aucune priorité n'est inventée entre un Join-Accept et l'ACK d'un autre terminal : LoRaWAN n'en
définit pas. À instant égal, l'ordre est celui du dépôt.

**Règle de départ et durée d'occupation** : `début = max(instant_prêt, ouverture de fenêtre,
occupé_jusqu'à)` ; l'émetteur est occupé de `début` à `début + temps d'antenne`, sans garde ni temps
de retournement. Le verdict porte sur le **début** : une descente commencée dans la fenêtre est
émise entière, même si elle finit après la fermeture, et elle occupe l'émetteur au-delà.

**Causalité des tentatives.** L'issue d'un Join-Accept n'est connue qu'après le placement partagé.
Une tentative de secours n'est donc jamais retirée du calendrier sur une prévision : elle l'est
seulement quand la jointure a été **observée**. Un terminal dont la première tentative échoue parce
qu'un ACK occupait RX1 et RX2 effectue bien sa tentative suivante.

Le Join-Request consomme le rapport cyclique du groupe (`duty_cycle`, et la limite de sous-bande
régionale). Une tentative qui dépasse le budget n'est pas émise du tout : elle ne provoque aucune
collision et n'apparaît pas comme une transmission dans la trace.

```yaml
groups:
  - name: terminaux
    duty_cycle: 0.01       # 1 % ; la sous-bande régionale peut être plus restrictive
retransmissions:
  enforce_duty_cycle: true # false : le budget n'est pas appliqué (ni aux réémissions)
  join_requests_s: [10]
```

**Un budget cumulatif, pas une fenêtre glissante.** Le rapport cyclique est un budget montant par
terminal : `airtime cumulé + airtime <= rapport × instant`, en nanosecondes, le cumul étant pris
depuis l'origine de la simulation. Une émission ancienne pèse donc encore sur le droit courant. Il
s'applique à **toutes** les tentatives réelles du terminal, et une tentative refusée n'est pas
enregistrée comme une émission — elle ne consomme aucun budget.

Ce qui **n'est pas** modélisé : le rapport cyclique **descendant** de la passerelle, les cartes
radio multiples, et la durée d'ouverture des fenêtres (1 s, hypothèse du simulateur — LoRaWAN ne
fixe que le délai). Détails et mesures : `docs/MAC_CONSOLIDATION.md` §10.

### Compteurs : rejeu, désynchronisation, débordement

Le terminal ne reçoit que le champ `FCnt` de **16 bits** ; il le replace dans sa série 32 bits
(`lsim.fcnt.CounterSeries`). Quatre verdicts en sortent, visibles dans `AckOutcome.counter` :

| Verdict | Quand | Effet |
|---|---|---|
| `OK` | compteur reconstruit strictement supérieur au dernier accepté | ACK retenu (`STANDARD`) |
| `REPLAY` | champ identique à celui du dernier ACK accepté | copie ignorée (`DUPLICATE`), série inchangée |
| `GAP` | écart supérieur à 16 384 | ACK rejeté (`GAP`), série inchangée |
| `EXHAUSTED` | série arrivée à 2^32 | aucun ACK numéroté ; nouvelle jointure, hors modèle |

**Deux séries, deux événements.** Un ACK seul consomme `NFCntDown` et apparaît en `ack_only` ; avec
`downlink_payload: true`, la descente porte une charge utile, consomme `AFCntDown` et apparaît en
`data_ack`. Les deux séries partent du même `fcnt_down_start` mais avancent séparément. Une nouvelle
**session** repart de zéro : `plan_acks(sessions=...)` et `DeviceCounters.renew_session()` le
modélisent, et le compteur 0 de la nouvelle session n'est pas rejeté comme rejeu de l'ancienne. Une
jointure déclarée dans le scénario (`session_joins_s`) ouvre cette nouvelle session : `FCntUp` et
les deux séries descendantes repartent de zéro, et les trames de l'ancienne session cessent d'être
réémises (voir `docs/MAC_CONSOLIDATION.md` §8).

**Statut des règles** : la reconstruction 16 → 32 bits et le rejeu strictement croissant sont des
règles de la spécification. La borne de 16 384 est la valeur historique `MAX_FCNT_GAP` des versions
≤ 1.0.3, **retirée de LoRaWAN 1.0.4 et suivants** (RP002) : le simulateur l'applique comme
**politique de rejeu explicite**, parce qu'il rejoue des trames à champ 16 bits. Ce n'est pas une
exigence de 1.0.4, et c'est écrit ainsi dans le code (`lsim/fcnt.py`). Limite : aucun scénario livré
ne produit `GAP` — la copie d'un ACK est un `DUPLICATE`, jamais un saut de 65 536.

`build_trace` et `run_scenario` empruntent alors un chemin dédié qui renvoie une entrée de trace
**par transmission**, avec les indices des terminaux du scénario, ainsi qu'un objet
`trace.retransmissions` (essais, ACK, doublons, tentatives bloquées).

### Ce que le modèle distingue

| Notion | Où elle vit |
|---|---|
| Livraison de la descente | verdict du planificateur : livrée, sous la sensibilité, non planifiée |
| Réception de l'ACK | la descente tombe dans la fenêtre RX1 de **cette** trame |
| Acquittement logique | la réception ci-dessus concerne bien cette trame |

Le cœur ne modélise pas le contenu de la trame ACK : l'appariement se fait par fenêtre, ce qui est
exact tant qu'un seul ACK est attendu par fenêtre. `AckFrame` porte déjà les champs
(`frame_counter_up`, `frame_counter_down`) qu'une représentation MAC complète utilisera.

### Couche MAC de l'ACK (`lsim.ack_mac`) — tardif et dupliqué, de bout en bout

Le planificateur du cœur place la descente à `fin + RECEIVE_DELAY1` et **abandonne** celle qui ne
tient pas dans RX1 : il ne peut produire ni ACK tardif ni ACK dupliqué. Deux réglages du bloc
`retransmissions:` activent à la place une couche MAC Python, qui les rend possibles sans toucher
au cœur ni à l'ABI.

| Réglage | Effet mesuré (`build_trace`) |
|---|---|
| `ack_delay_ms: 2500` | 6 transmissions, 6 ACK émis, **0 reçu**, 0/2 livrée : l'ACK tombe après la fermeture de RX2 ; l'airtime est consommée et la passerelle occupée |
| `ack_delay_ms: 1500` | l'ACK tombe dans RX2 (`fin + 2 s`, durée 1 s) et **est reçu** |
| `ack_delay_ms: 0` (témoin) | 2 transmissions, 2 ACK reçus, 2/2 livrées — comportement du cœur |
| `ack_repetitions: 2` | 2 transmissions, **4 ACK émis**, 2 reçus, **2 doublons ignorés**, 2/2 livrées |

La réception n'est pas recalculée : la recette radio (réciprocité, sensibilité, marge du récepteur)
est celle du cœur, et un test de parité vérifie que la couche MAC reproduit le planificateur natif
quand elle est laissée à ses valeurs par défaut.

L'émission de l'ACK commence à `fin + 1 s + delay_ms`. Frontières **mesurées** (balayage de 0 à
2 500 ms, pas de 50 ms, sur `retransmissions_ack_tardif.yaml`) :

| Fenêtre | Ouverture | Durée | `delay_ms` qui y tombe | Réception |
|---|---|---|---|---|
| RX1 | `fin + 1 s` | 1 s | 0 à 999 | reçu |
| RX2 | `fin + 2 s` | 1 s | 1000 à 1999 | reçu |
| aucune (`LATE`) | après RX2 | — | 2000 et au-delà : l'ACK est émis, jamais entendu |

Une passerelle occupée peut repousser l'émission (`max(ouverture + delay, fin d'occupation)`) : un
ACK prévu dans RX1 peut donc basculer en RX2, ou hors fenêtre, selon le trafic.

### Taxonomie et classes d'écoute

Chaque émission d'ACK reçoit une classe, exposée par `trace.retransmissions` :

| Classe | Sens | Compteur |
|---|---|---|
| `STANDARD` | reçue dans une fenêtre écoutée, `FCntDown` inédit | `ack_standard` |
| `LATE` | émise après la fermeture des fenêtres | `ack_late` |
| `LOST` | dans une fenêtre mais non décodable, ou terminal en train d'émettre | `ack_lost` |
| `DUPLICATE` | même `FCntDown` déjà accepté, rejeté par le contrôle de rejeu | `ack_duplicate` |
| `NOT_SENT` | aucun ACK : uplink non reçu | `ack_not_sent` |

Même scénario à `ack_delay_ms: 2500` : un terminal de **classe A** ne reçoit aucun ACK (6 tardifs,
0/2 livrée) ; un terminal de **classe C**, qui écoute en continu, reçoit les deux (2/2 livrée).
La classe B se comporte comme A pour l'ACK — ses *ping slots* sont un autre mécanisme, non
modélisé ici. Détail et limites : `docs/MAC_CONSOLIDATION.md`.

### Les ACK dans la trace

Chaque émission d'ACK de la couche MAC devient un `ProtocolEvent` de type `ack`, à l'instant exact
où elle commence et avec le même verdict que les compteurs. Le vocabulaire est celui du contrat
(`lsim.api_contract`), sans valeur nouvelle :

| Classe | `event.outcome` | `hops[0].outcome` | Sens |
|---|---|---|---|
| `STANDARD` | `ack_only` | `delivered` | reçu dans une fenêtre écoutée |
| `LATE` | `not_listened` | `not_listened` | émis après RX2 : personne n'écoute |
| `LOST` (fenêtre manquée) | `device_transmitting` | `not_listened` | le terminal émet au moment de l'ouverture |
| `LOST` (non décodable) | `lost_sensitivity` | `lost_sensitivity` | sous la sensibilité du récepteur |
| `DUPLICATE` | `suppressed` | `delivered` | copie reçue, rejetée par le contrôle de rejeu |
| `NOT_SENT` | — | — | uplink non reçu : rien n'est émis |

Une émission = un événement : sur `retransmissions_ack_tardif.yaml`, six ACK tardifs donnent six
événements `not_listened` et six intervalles dans `gateway_tx`. Sans la couche MAC
(`ack_delay_ms: 0`), la trace garde les événements du planificateur du cœur. Détail :
`docs/MAC_CONSOLIDATION.md` §4.1.

### Ce qui n'est pas modélisé

- **Aucune perte d'ACK avec un récepteur nominal** : le planificateur causal livre l'ACK de toute
  trame qu'il reçoit. Observer une perte d'ACK exige une hypothèse de récepteur dégradé
  (`ProtocolOptions(device_rx_offset_db=...)`), pas un réglage du scénario.
- L'ACK tardif et l'ACK dupliqué ne peuvent pas être produits par le planificateur du cœur ; ils le
  sont par la couche MAC Python (`ack_delay_ms` / `ack_repetitions`), qui n'est **pas** dans le cœur
  C++ et n'est appelée que lorsque l'un de ces deux réglages sort de sa valeur par défaut.
- `ack_repetitions > 1` est une hypothèse de réseau (répétition du même ACK), pas un mécanisme
  LoRaWAN standard : LoRaWAN 1.0.4 ne répète pas la trame d'acquittement en classe A.
- Un ACK émis hors fenêtre (`LATE`) est rangé avec les pertes de sensibilité dans
  `DownlinkDelivery`, qui n'a pas de verdict « hors fenêtre » ; la fenêtre exacte reste lisible
  dans `AckOutcome.window`.
- Le compteur de doublons déduplique côté réseau ; il ne remplace pas une trace MAC complète.
- Aucun `FCntUp` / `FCntDown` n'est réellement décrémenté : l'identité de la trame est l'indice de
  trame du scénario, pas un compteur de trame.
- L'énergie n'est pas ventilée entre émission, écoute RX1/RX2 et veille.

### Exemples exécutables

| Fichier | Ce qu'il démontre |
|---|---|
| `docs/exemples/retransmissions_nominal.yaml` | uplink reçu, ACK reçu, aucune réémission |
| `docs/exemples/retransmissions_collision.yaml` | collision, réémission réussie, refus par rapport cyclique |
| `docs/exemples/retransmissions_doublons.yaml` | trafic dense : réémissions et borne de tentatives |
| `docs/exemples/retransmissions_ack_perdu.yaml` | ACK perdus et **doublons réseau** (avec récepteur à +10 dB) |
| `docs/exemples/retransmissions_ack_tardif.yaml` | `ack_delay_ms: 2500` : ACK émis après RX2, jamais reçu, 0/2 livrée |
| `docs/exemples/retransmissions_ack_duplique.yaml` | `ack_repetitions: 2` : 4 ACK émis, 2 reçus, 2 doublons ignorés |

## 6. Limites connues

Voir `docs/ROADMAP.md`. Points notables pour l'usage. Cette liste est vérifiée contre le
moteur : une limite qui n'existe plus en est retirée, une limite levable par un réglage le dit.

- **collisions, même SF** : seuil de capture à 6 dB, réglable (`propagation.capture_threshold_db`).
  Les SF différents sont **orthogonaux par défaut** : deux trames qui se chevauchent sur des SF
  différents ne se gênent pas. Ce n'est pas une propriété d'un vrai récepteur, c'est un choix.
- **collisions, SF différents** : `propagation.inter_sf: sx1276` lève l'hypothèse d'orthogonalité.
  Le seuil vient de la table « LoRa Demodulator SNR » du SX1276 (datasheet Rev. 4) — la même que
  l'ADR et la sensibilité : la trame voulue tolère un interférent d'autant plus fort que son SF
  est élevé (−7,5 dB en SF7, −20 dB en SF12). **Ce seuil ne dépend que du SF voulu** : c'est
  l'approximation de la littérature, pas une matrice d'isolement mesurée entre deux SF — celle-ci
  viendrait d'une campagne de mesures, pas d'une datasheet. Le défaut `orthogonal` laisse un
  scénario écrit avant l'introduction de l'option exactement ses chiffres **et** son empreinte.
- **plusieurs passerelles : ce n'est plus une limite.** Le moteur compte les réceptions
  passerelle par passerelle (charge, meilleure passerelle, masque de décodage) et le demi-duplex
  s'applique à chacune. L'ancienne mention « une seule passerelle » était périmée : elle
  détournait d'une fonctionnalité qui existe.
- **protocole** (`lsim.trace_events`) : passerelle **mono-émetteur** et demi-duplex — un seul
  downlink à la fois, et un uplink qui chevauche une de ses émissions est perdu. La réception
  descendante est calculée par réciprocité à partir du RSSI montant, avec `gateway_tx_power_dbm`
  (14 dBm par défaut) et le gain d'antenne du dispositif `device_antenna_gain_dbi` — 0 dBi par
  défaut, **réglable de −10 à +10 dBi**, ce n'est pas une constante. Le seuil est la sensibilité
  de référence SX1276 plus `device_rx_offset_db`, à renseigner depuis la fiche technique du
  récepteur réel.
- **latence** : ce qui est publié n'est **pas** le temps d'antenne. Côté montant, c'est
  l'émission → la remise au LNS, saut mesh inclus ; côté descendant, c'est la demande →
  l'émission effective, attente de la fenêtre RX comprise. Manquent le backhaul IP et les délais
  du réseau fixe : la latence publiée est un **plancher**, pas un temps de bout en bout.
- **énergie** : les deux profils (`rak4631`, `sx1262-stm32l072`) reprennent les courants des
  fiches constructeur. **Aucune mesure de terrain n'a été faite par ce projet** — les valeurs
  du moteur restent des fiches, et le dimensionnement d'une pile demande un relevé. Celui-ci
  s'entre désormais dans le scénario (`energy.measured`, §4.1) : la limite n'est plus
  l'absence de mesure possible, elle est que **le projet n'en fournit aucune**.
- **pénétration** : la perte d'un matériau suit UIT-R P.2040-4 (diélectriques), non calibrée sur
  mesures. À 868,1 MHz, **12 des 15 matériaux** sortent de la plage documentée : la valeur est
  alors extrapolée, et le serveur le signale (`extrapolated`). Deux issues, selon ce dont on
  dispose : un relevé d'atténuation se saisit directement (`attenuation_db` sur un obstacle),
  et une mesure de matériau se déclare dans `environment.material_calibration` (§5 bis), qui
  remplace P.2040-4 pour les obstacles concernés.
