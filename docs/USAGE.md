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
export LSIM_INTEGRITY_KEY=<32 caractères hexadécimaux, stockés hors dépôt>
python -m lsim serve --host 0.0.0.0 --port 1700 --db joins.sqlite --keys keys.json --net-id 000013
```

- `keys.json` : `{"devices": {"<DevEUI hex>": {"nwk_key": "<32 hex>", "app_key": "<32 hex, optionnel>"}}}`, mode 600 exigé.
- Passerelle : pointer le packet forwarder vers ce serveur (`server_address`, ports up/down).
- Jointure : join-request valide → join-accept en PULL_RESP, à `tmst + 5 s` (RP002-1.0.2 §2.3), même fréquence et débit que l'émission. La session de données (clés de session 1.1, compteurs) est créée dans la même transaction.
- Données (plan EU868 uniquement, `lsim.eu868`) :
  - uplink confirmé ou non confirmé vérifié avec le compteur 32 bits reconstruit depuis le FCnt 16 bits, TxDr et TxCh (canaux par défaut 868,10 / 868,30 / 868,50 MHz) ;
  - rejeu, compteur ancien et MIC faux : rejetés, sans changement d'état ;
  - uplink confirmé : ACK en downlink RX1 à `tmst + 1 s`, même canal et débit ; retransmission identique ré-acquittée ;
  - downlink mis en file avec `lsim downlink`, émis en RX1 au prochain uplink (un seul par uplink). Charge limitée à 51 octets (DR0, RP002-1.0.2 tableau 12) ; FPort 1 à 223 ; FPort > 0 exige `app_key`.
- Fichier de base SQLite créé en mode 0600 ; une base accessible par d'autres utilisateurs est refusée. Les clés de session y sont stockées en clair (décision à valider).

```bash
python -m lsim downlink --db joins.sqlite --dev-eui 0102030405060708 --fport 1 --payload-hex 0102
python -m lsim downlink --db joins.sqlite --dev-eui 0102030405060708 --fport 2 --payload-hex 00 --confirmed
```

Limites des trames de données :

- Livraison au mieux : un downlink est retiré de la file à son émission ; pas de retransmission. Un downlink confirmé sans acquittement à l'uplink suivant est considéré perdu.
- Une seule copie est traitée : avec plusieurs passerelles, les copies suivantes sont rejetées comme rejeu.
- FPending, ADR et commandes MAC (FOpts, FPort 0) ne sont pas interprétés.
- Canal non par défaut ou débit hors DR0-DR6 : rejet (le MIC 1.1 exige TxCh).
- Pas de limite d'écart de compteur (MAX_FCNT_GAP supprimé en 1.0.4+) : l'intégrité repose sur le MIC.
- Basic Station : pas encore pris en charge ; autres plans régionaux : non pris en charge pour les données.

## 6. Limites connues

Voir `docs/ROADMAP.md`. Points notables pour l'usage :

- collisions : même SF, capture à 6 dB ; une seule passerelle ;
- latence = temps d'antenne (ni file ni backhaul) ;
- énergie : profils constructeur, pas de mesure terrain ;
- pénétration : pertes par matériau selon UIT-R P.2040-4 (diélectriques), non calibrées sur mesures.
