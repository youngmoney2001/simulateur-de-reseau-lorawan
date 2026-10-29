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
- Sous-bande de la passerelle (`lsim serve --region US915|AU915 --sub-band N`, défaut 1) : la passerelle Basic Station annonce les 8 canaux 125 kHz et le canal 500 kHz de la sous-bande (radio_0, radio_1 pour le 500 kHz). À chaque jointure, le serveur envoie un LinkADRReq (ChMaskCntl 5, DataRate et TXPower ignorés) qui restreint le dispositif à cette sous-bande. Il part en FOpts du downlink et est renvoyé à chaque downlink tant que le dispositif ne répond pas par un LinkADRAns complet (débit, puissance, masque) : au plus 8 essais, persistés dans la table `mac_pending`. Limites : le dispositif ne reçoit la commande que s'il ouvre RX1 après un uplink ; une passerelle Semtech UDP se configure côté passerelle (GWMP ne permet pas au serveur de changer son plan de canaux) ; LR-FHSS non géré (voir section 5quater).
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

## 6. Limites connues

Voir `docs/ROADMAP.md`. Points notables pour l'usage :

- collisions : même SF, capture à 6 dB ; une seule passerelle ;
- latence = temps d'antenne (ni file ni backhaul) ;
- énergie : profils constructeur, pas de mesure terrain ;
- pénétration : pertes par matériau selon UIT-R P.2040-4 (diélectriques), non calibrées sur mesures.
