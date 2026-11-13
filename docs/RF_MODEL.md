# Modèle radio : équations, paramètres et périmètre

**Statut** : document de référence (D3.2). Il fixe ce que le simulateur applique **réellement** et
ce qu'il **n'expose pas**, pour les anomalies F6, M2, RF-YAML, MULTI-V4, M3 et GEO-RF.

**Sources de vérité** : `core/src/link_budget.cpp` (perte de propagation), `python/lsim/radio.py`
(sensibilité, modèle log-distance), `python/lsim/trace_events.py` (descente par réciprocité),
`python/lsim/simulator.py` (routage des frontaux), `python/lsim/rf.py` (tables de frontal).
Chaque valeur de référence du §10 est reproductible par les tests cités.

---

## 1. Périmètre

Le modèle radio couvre trois choses, et trois seulement :

1. la **perte de propagation** entre un terminal et une passerelle ;
2. la **sensibilité** du récepteur, qui décide de la réception d'une trame ;
3. les **frontaux** (gain d'antenne, perte de câble) par terminal et par passerelle.

La **géographie** (projection, anneaux de couverture, export GeoJSON) est traitée séparément au §9.
Aucun paramètre radio n'est déduit d'une donnée géographique, et aucun champ de gain, d'EIRP ou de
perte de câble n'est écrit dans un export géographique.

## 2. Perte de propagation

Modèle log-distance, distance de référence `d0 = propagation.reference_distance_m` :

```
PL(d)  = PL(d0) + 10 · n · log10(d / d0)
PL(d0) = 20 · log10(d0) + 20 · log10(f) − 147,55        (espace libre, f en Hz)
```

- `PL(d0)` est toujours l'espace libre : `d0` ne décale pas le modèle, il **déplace le point
  d'ancrage** de la pente.
- `n` (`propagation.exponent`) est borné à `[1 ; 6]` ; `d0 > 0` ; `f > 0`.
- Changer `d0` de `d0₁` à `d0₂` décale **toutes** les pertes de :

```
ΔPL = (20 − 10 n) · log10(d0₂ / d0₁)
```

Cette expression explique l'observation M2 : sur un exemple où aucun terminal n'est plus proche
que 60 m de la passerelle, faire passer `d0` de 1 m à 10 m ne change **rien** à n = 2
(`20 − 10 × 2 = 0`), mais retire **7 dB** à n = 2,7. `d0` n'est donc pas « sans effet » : son effet
dépend de `n` et du domaine de distances réellement utilisé.

Le relief et les obstacles (`environment`) s'ajoutent à `PL(d)` ; sans environnement, le résultat
est celui du modèle log-distance seul. La façon dont ils s'ajoutent fait l'objet du §2.1.

### 2.1 Obstacles : deux chemins, le meilleur gagne

Un obstacle dont le sommet dépasse le rayon offre deux chemins, et le moteur retient le
**moins coûteux** des deux — jamais leur somme :

```
surplus        = min(pénétration, contournement)
pénétration    = Σ attenuation_db des obstacles traversés
contournement  = diffraction de Deygout (3 arêtes) sur le profil relief + sommets d'obstacles
```

Un mur dont on connaît la perte se **traverse** ; un mur opaque se **contourne**. Deux
conséquences valent d'être connues avant d'exploiter un chiffre :

- la perte d'un obstacle est **plafonnée** par le prix du contournement. Alourdir le
  matériau au-delà ne change plus rien : le matériau n'est pas un interrupteur, et il est
  impossible de couper une liaison à bout portant en durcissant un mur ;
- la pénétration ne se voit donc que là où elle coûte **moins** que le contournement —
  murs peu absorbants, ou vus de loin. De près, le bilan ferme largement et aucune perte
  de matériau ne suffit à couper : c'est pourquoi les tests de calibration portent leurs
  capteurs à 8–10 km, là où la marge est mince.

**Historique.** Les deux termes étaient additionnés. Un mur réglé à **0 dB** coupait alors
la liaison, l'onde payant à la fois la traversée et le contournement : un bloqueur parfait,
quel que soit son matériau, et insensible à toute mesure — la `material_calibration` du §5
bis de `USAGE.md` n'y pouvait rien changer. Corrigé : le rayon prend le meilleur chemin.

## 3. Sensibilité et décision de réception

La réception d'une trame est décidée par comparaison du RSSI à la sensibilité du débit utilisé
(`receiver_sensitivity_dbm(sf, bw)`, référence SX1276), éventuellement décalée par
`device_rx_offset_db`. Il n'y a ni marge de fading, ni probabilité de réception : la frontière est
déterministe.

Conséquence mesurée : à puissance et gains constants, la bascule de réception se produit à une
distance fixe par débit — 15 à 25 km en SF9 et 40 km en SF12 dans la configuration du §10.

## 4. Collisions et seuil de capture

Deux trames de même débit qui se chevauchent entrent en collision ; la plus forte n'est reçue que
si elle dépasse l'autre d'au moins `propagation.capture_threshold_db` (6 dB par défaut, frontière
**inclusive** : un écart exactement égal au seuil est capturé).

Des débits différents **ne collisionnent pas par défaut** : les spreading factors sont réputés
orthogonaux. C'est un choix, pas une propriété d'un vrai récepteur. `propagation.inter_sf:
sx1276` le lève.

### 4.1 Collisions entre SF différents (`propagation.inter_sf`)

`orthogonal` (défaut) : deux trames de SF différents qui se chevauchent ne se gênent jamais.
Un scénario qui ne mentionne pas la clé garde exactement ses chiffres **et** son empreinte.

`sx1276` : un interférent d'un SF différent est compté. La trame voulue, de SF `s`, survit si

    P_voulue − P_interférent ≥ SNR_s

où `SNR_s` est la valeur de la table « LoRa Demodulator SNR » du SX1276 (datasheet Rev. 4),
celle-là même qui sert à l'ADR et à la sensibilité : −7,5 dB en SF7, −10 en SF8, −12,5 en SF9,
−15 en SF10, −17,5 en SF11, −20 en SF12. Ces valeurs sont négatives : plus le SF voulu est
élevé, plus il tolère un interférent fort. Ainsi un SF12 supporte un SF7 reçu 20 dB au-dessus
de lui, alors qu'un SF7 cède dès 7,5 dB.

Deux réserves, qui valent d'être lues avant d'exploiter un résultat :

- **le seuil ne dépend que du SF voulu**, jamais de la paire (voulu, interférent). Une vraie
  isolation se mesure entre deux SF : c'est une matrice, pas une droite.
- **c'est l'approximation de la littérature, pas une mesure.** Les valeurs viennent d'une
  datasheet (seuil de démodulation face au bruit), et sont employées ici comme seuil
  d'interférence. Une matrice d'isolement crédible viendrait d'une campagne de mesures.

Quand plusieurs interférents se cumulent, la contrainte la plus sévère l'emporte : la trame
survit si elle respecte le seuil de **chacun**, les mêmes-SF face au seuil de capture et les
SF-différents face au seuil inter-SF.

## 5. Descente : réciprocité

Le canal descendant réutilise le bilan montant, sans second modèle :

```
RSSI_dl = RSSI_ul − P_tx_terminal + P_tx_passerelle + G_antenne_terminal
```

Les termes de la chaîne terminale s'annulent (voir `docs/RF_FRONTEND_V4.md` §2) : le gain est
compté **une seule fois**. Un downlink est reçu si `RSSI_dl` atteint la sensibilité du débit RX1 du
terminal.

## 6. Frontaux RF v4

Un frontal porte deux grandeurs **indépendamment présentes** : `antenna_gain_dbi` (`|G| ≤ 40`) et
`cable_loss_db` (`0 ≤ L ≤ 40`). Chaîne appliquée : `G − L`.

- Une table **absente** donne une chaîne de 0 dB, sans changer le résultat historique.
- Une table **partielle** (un seul des deux champs renseigné alors que l'autre est attendu) est
  refusée avant l'appel natif, avec le statut **301** côté cœur. Aucun repli implicite.
- Un gain de passerelle **présent** remplace `gateway.antenna_gain_dbi` ; un gain absent laisse le
  scalaire en vigueur.
- Le détail du contrat et les bornes sont dans `docs/RF_FRONTEND_V4.md`.

## 7. Capacités réellement exposées, par chemin

| Chemin | Frontaux RF | Remarque |
|---|---|---|
| `simulate_uplinks` | **non** | aucun paramètre de frontal |
| `simulate_uplinks_trace` | **oui** (`device_rf`, `gateway_rf`) | routage vers `lsim_simulate_uplinks_trace_v3` |
| `simulate_uplinks_multi` | **non** | multi-passerelles sans descente |
| `simulate_multi_downlinks` | **oui** (`device_rf`, `gateway_rf`) | routage vers `lsim_simulate_uplinks_multi_dl_v2` |
| `simulate_closed_loop_v3` | **oui** | bascule sur `lsim_simulate_closed_loop_v4` |
| `downlink_plan` / trace causale | **non** | pas de frontal par terminal |
| Mesh (`lsim_mesh_*`) | **non** | aucune table RF n'est réutilisée |
| Scénario YAML | **non** | `rf:` refusé à la racine et dans un groupe (§8) |
| Export GeoJSON | sans objet | géométrie seule (§9) |

Un chemin qui n'expose pas de frontal ne doit pas en recevoir : il n'existe **aucune** entrée
`multi_v4`, et le mesh n'a aucune notion de gain d'antenne. Ces absences sont des limites
assumées, pas des options désactivées par défaut.

## 8. Configuration : YAML et API

Le fichier de scénario est validé strictement : un champ inconnu est refusé. Il **ne porte aucune
donnée RF de frontal** :

- pas de clé `rf:` à la racine du scénario ;
- pas de clé `rf:` dans un groupe ;
- les seuls champs radio d'un groupe sont `spreading_factor`, `tx_power_dbm`, `payload_bytes`,
  `channel_freq_hz`, `sub_band`, `region` et `duty_cycle`.

Les frontaux se déclarent **uniquement dans l'API Python** (`DeviceRf`, `GatewayRf`), au niveau des
fonctions du §7. Un scénario chargé depuis YAML décrit donc une population **sans frontal** : pour
mesurer un gain d'antenne, il faut passer par l'API et fournir la table correspondante.

Le bloc `propagation` porte les réglages du canal, tous facultatifs : `frequency_hz`,
`reference_distance_m`, `exponent`, `capture_threshold_db`, `shadowing_sigma_db`,
`shadowing_seed` et `inter_sf`. Ce dernier vaut `orthogonal` ou `sx1276` (§4.1) ; à
`orthogonal`, sa valeur par défaut, la clé quitte le hachage du scénario — un scénario écrit
avant son introduction garde donc exactement la même empreinte.

## 9. Géographie et radio : séparation

L'export GeoJSON contient de la **géométrie et des compteurs**, jamais de radio fréquence :

- propriétés du document : `environment`, `origin`, `pdr`, `scenario_name`, `scenario_sha256`,
  `total_received`, `total_sent` (7 clés) ;
- une entité par passerelle (gaine de couverture), par groupe (anneau) et par terminal ;
- aucune clé `gain`, `eirp`, `cable`, `frontend` ou `rf`.

L'anneau de couverture est calculé à partir du bilan de liaison, mais le résultat exporté reste une
**distance** (`range_m`) : aucune donnée de frontal n'est transportée par l'export, et
`python/lsim/geo.py` n'est pas modifié par les frontaux v4.

## 10. Valeurs de référence mesurées

Configuration de référence : 868,1 MHz, `d0 = 1 m`, `n = 2,7`, seuil de capture 6 dB (valeurs des
exemples `quartier_*.yaml`).

| Grandeur | Valeur mesurée |
|---|---|
| `PL(3 000 m)` | **125,103669 dB** |
| `d0 : 1 m → 10 m` à n = 2,7 | **−7,000000 dB** (`20 − 10 n`) |
| `d0 : 1 m → 10 m` à n = 2 | **0,000000 dB** |
| `n : 2,7 → 3,5` à 1 000 m | **+24,000000 dB** |
| `n : 2,7 → 3,5` à 1 200 m | **+24,633450 dB** (et **−24,633450 dB** pour 3,5 → 2,7) |
| `DeviceRf(3 dBi, 1 dB)` | **+2,000000 dB** |
| `GatewayRf(6 dBi, 1 dB)` | **+5,000000 dB** |
| Cumul des deux frontaux | **+7,000000 dB** |
| Multi-passerelles sans frontal | **0,000000 dB** |
| Bascule de réception SF9 | 15 km / 25 km |
| Bascule de réception SF12 | 40 km |

Ces valeurs servent de garde aux tests de non-régression RF (`test_rf_characterization_r1.py`,
`test_rf_frontend.py`, `test_rf_scope.py`).

## 11. Ce que le modèle ne fait pas

1. Aucun modèle de canal distinct : la fréquence est portée par la propagation, pas par la trame.
2. Aucun fading aléatoire ; la réception est déterministe au dB près.
3. Aucun gain d'antenne pour le mesh ni pour le chemin causal.
4. Aucun EIRP, aucun diagramme d'antenne, aucune polarisation.
5. **Aucune grandeur énergétique** : le bilan d'un dispositif n'entre dans aucune équation de ce
   document. Ce n'est pas une absence de calcul — le moteur évalue l'énergie par message et le
   courant moyen (`core/src/energy.cpp`), à partir du temps d'antenne et, le cas échéant, d'un
   relevé mesuré (`energy.measured`) qui remplace la fiche constructeur. Ces grandeurs relèvent
   d'un autre modèle, décrit dans `USAGE.md` et dans les deux manuels ; les confondre avec le
   modèle radio ferait croire qu'une portée dépend d'une batterie.
5. Aucune table RF dans un scénario YAML ni dans un export géographique.
