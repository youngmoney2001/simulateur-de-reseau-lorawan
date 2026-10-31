# Frontal RF v4 : contrat, sémantique et limites

**Phase** R2b · **base** `c46d531` · **ABI** additive et versionnée (option C)

---

## 1. Pourquoi

Jusqu'à la base, un terminal n'avait **aucun** gain d'antenne ni perte de câble : seul
`tx_power_dbm` existait, et il déplaçait le RSSI de 1 dB par dBm. Le gain de réception du terminal
n'existait que sous forme d'un scalaire global dans la règle de descente
(`device_antenna_gain_dbi`). R2b ajoute un frontal **par terminal** et **par passerelle**, sans
toucher aux 91 symboles existants.

## 2. Sémantique

Un frontal porte deux grandeurs **indépendamment présentes** :

| Champ | Unité | Contrainte si présent |
|---|---|---|
| `antenna_gain_dbi` | dBi | `|G| <= 40` |
| `cable_loss_db` | dB | `0 <= L <= 40` |

- `present()` faux ⇒ frontal neutre (chaîne 0 dB) ; c'est le comportement de la base.
- Un champ **absent n'est pas lu** : il ne vaut pas 0 par convention, il n'existe pas.
- L'antenne est **réciproque** : la chaîne `G - L` s'applique à l'émission et à la réception.

### Bilans

```
RSSI_ul = (P_tx + G_d − L_d) + (G_g − L_g) − PL − shadowing
RSSI_dl = P_gw + (G_g − L_g) − PL + (G_d − L_d) + device_rx_offset_db
```

Par réciprocité, `RSSI_dl = RSSI_ul − (P_tx + G_d − L_d) + P_gw + (G_d − L_d)` : les termes de la
chaîne terminale **s'annulent**. Le gain est donc compté **une seule fois**, jamais deux.

### Règle de non-cumul

Quand une table terminale est fournie, `rule.device_antenna_gain_dbi` **n'est pas ajouté**. La
chaîne du frontal fait foi. Aucun repli implicite, aucun cumul. Un test dédié construit une marge
où un double comptage ferait basculer l'issue de descente de « sous la sensibilité » à « reçue ».

### Passerelle

Quand une entrée `lsim_gateway_rf` est fournie, son gain **présent remplace**
`lsim_gateway.antenna_gain_dbi` ; la perte de câble s'ajoute à la chaîne. Un gain absent laisse le
scalaire en vigueur.

## 3. ABI

```c
#define LSIM_RF_HAS_ANTENNA_GAIN 1u
#define LSIM_RF_HAS_CABLE_LOSS   2u

typedef struct lsim_device_rf  { uint32_t present; double antenna_gain_dbi; double cable_loss_db; } lsim_device_rf;
typedef struct lsim_gateway_rf { uint32_t present; double antenna_gain_dbi; double cable_loss_db; } lsim_gateway_rf;
```

| Symbole | Base | Ajout |
|---|---|---|
| `lsim_simulate_uplinks_trace_v3` | `_trace_v2` | `device_rf`, `device_rf_count`, `gateway_rf` |
| `lsim_simulate_uplinks_trace_gw2_v2` | `_trace_gw2` | idem, sensibilité absolue conservée |
| `lsim_simulate_uplinks_multi_dl_v2` | `_multi_dl` | idem + `gateway_rf_count` |
| `lsim_simulate_closed_loop_v4` | `_closed_loop_v3` | `lsim_closed_loop_v4_args` : `v3` + les deux tables |

`lsim_closed_loop_v4_args` **enveloppe** les arguments v3 : la validation et l'écriture restent
celles du contrat v3, v4 n'ajoute que le RF.

### Règle de table

Un compteur RF vaut **0** (aucune table) ou **exactement** `device_count` / `gateway_count`.
Toute valeur intermédiaire est refusée (statut `301`, entrée invalide) : aucun élément ne reçoit
silencieusement un frontal vide.

### Statuts

| Situation | Statut |
|---|---|
| bit `present` inconnu | 301 |
| gain ou perte hors bornes, valeur non finie | 301 |
| table partielle | 301 |
| `lsim_closed_loop_v4_args` nul / taille / version / `v3` nul | 301 (null : code du statut « pointeur nul ») |

## 4. Pont Python

`python/lsim/rf.py` : `DeviceRf(antenna_gain_dbi=None, cable_loss_db=None)` et `GatewayRf(...)`.
`None` = champ absent ; `0.0` = valeur fournie. La distinction est testée.

Routage (un seul endroit, `simulator.trace_native_function` / `simulator.multi_dl_native_function`) :

| Entrée | Symbole appelé |
|---|---|
| aucun frontal | `_trace_v2` ou `_trace_gw2` |
| frontal + modèle relatif | `trace_v3` |
| frontal + sensibilité absolue | `trace_gw2_v2` |
| downlinks sans frontal | `multi_dl` |
| downlinks avec frontal | `multi_dl_v2` |

Les tests remplacent les symboles par des espions et vérifient **nommément** lequel est atteint :
dès qu'un frontal est fourni, l'ancien point d'entrée ne doit plus être appelé.

## 5. Portée et limites assumées

1. **Mesh** : aucune table RF n'est réutilisée. Les fonctions `lsim_mesh_*` sont inchangées ; un
   test vérifie qu'aucun symbole mesh n'est appelé par le chemin RF LoRaWAN.
2. **`simulate_uplinks_multi`** (multi-passerelles sans downlinks) n'a pas de variante v4 : elle
   n'accepte pas de frontal. Un frontal passé à `simulate_multi_downlinks` via `device_rf` y est
   traité ; le chemin multi-passerelles simple reste sans RF.
3. **`downlink_plan` / causal** : non couverts par R2b (pas de frontal par terminal dans ce
   chemin).
4. **`geo.py`** : inchangé ; la géométrie de couverture garde ses propres paramètres.
5. **ADR** : algorithme non modifié. Le frontal agit sur le bilan radio, pas sur les décisions.

## 6. Compatibilité

Sans table RF, les formules se réduisent **bit à bit** à celles de la base : empreintes gelées
`d2cb0fac6c2d9950` / `ed126d7ff5aac3b0` inchangées, 91 anciens symboles identiques, 95 au total.
