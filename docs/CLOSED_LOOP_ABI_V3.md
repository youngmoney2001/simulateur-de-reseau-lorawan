# ABI v3 de la boucle fermée (contrat 6.1, étape 6.2.7)

Statut : **contrat figé en révision 3 (6.1)**. Structures, validations, sorties et trace sont implémentées en
C++ (6.2.1 à 6.2.6) et les schémas Python sont publiés (6.2.7). La fonction publique
`lsim_simulate_closed_loop_v3` est **définie** dans `core/src/c_api_closed_loop_v3.cpp`, **exportée** par
`core/exports.map` (symbole `lsim_*`, visible dans `liblsim_core.so`), et **liée** en Python par
`python/lsim/closed_loop_v3.py` (étape 6.3, voir la section 9). Cette étape ne modifie ni le moteur, ni les
règles ADR, ni l'ABI v1/v2/gw2, ni le chemin Python `scenario`.

## 1. Périmètre et compatibilité

- ABI v3 additive. Les fonctions v1, v2 et gw2 et leurs structures sont **inchangées**.
- Les empreintes historiques sont **inchangées** : JSON `d2cb0fac6c2d9950`, trace `ed126d7ff5aac3b0`.
- Les scénarios sans bloc `mac:` restent octet pour octet identiques.
- `mac.device_channels` et `mac.server_channel_plan` restent **refusés** par `python/lsim/scenario.py`
  (message « étape 3 »). Ils n'entrent dans aucun chemin Python non v3 et ne figurent pas dans les schémas
  `schemas/api/v1`.
- Profils radio et régionaux inchangés : SX1276 par défaut, DR13 (SF5) réservé au profil SX1303 ; le plan
  de canaux v3 ne couvre que EU868 RP002-1.0.5 (US915 et AU915 relèvent de l'étape 7, non autorisée).
- Le mesh est hors LoRaWAN standard et hors de cette ABI.

## 2. Structures

Tailles LP64 vérifiées par `static_assert` (`core/tests/test_abi_v3_prep.cpp`).

### 2.1 `lsim_channel_device_v3` (128 octets)

| Champ | Type | Obligatoire | Sens |
|---|---|---|---|
| `struct_size` | `uint32_t` | oui | taille de la structure |
| `abi_version` | `uint32_t` | oui | 3 |
| `device_index` | `uint32_t` | oui | index du dispositif, < `device_count` |
| `present` | `uint32_t` | oui | 0 = défauts moteur, 1 = configuration explicite |
| `dr_mask[80]` | `uint8_t[80]` | si `present = 1` | débits supportés par canal (bit n = DRn) ; 0 = canal non défini |
| `enabled[10]` | `uint8_t[10]` | si `present = 1` | bitmap des canaux actifs (80 bits) |
| `server_defined[10]` | `uint8_t[10]` | si `present = 1` | bitmap de la vue serveur (80 bits) |
| `reserved[12]` | `uint8_t[12]` | doit être nul | réservé |

Convention des bits : `words[c/64]`, bit `c%64` ; octet k = canaux 8k à 8k+7, LSB d'abord.

### 2.2 `lsim_channel_terminal_v3` (112 octets)

Sortie : état final du terminal (`device_index`, `dr`, `power_index`, `dr_mask[80]`, `enabled[10]`,
`reserved0`, `reserved1`). Les champs `reserved*` sont écrits à zéro.

### 2.3 `lsim_loop_trace_v3` (40 octets)

`t_ns` (int64), `device`, `uplink`, `downlink` (uint32) ; `kind`, `origin`, `action`, `target`, `loss`,
`status`, `dr`, `power_index` (uint8) ; `channel_mask`, `value` (uint16) ; `flag`, `reason_channel`,
`reason_dr`, `reason_power` (uint8) ; `reserved` (uint32). Détails en section 6.

### 2.4 `lsim_closed_loop_v3_args` (272 octets)

Mêmes entrées que la v2 (`devices`, `radios`, `regions`, `gateway`, `prop`, `env`, `options`, `mac`), plus :
`channel_plan` (0 = NONE, 1 = EU868_RP002_1_0_5), `trace_enabled`, `trace_element_size`,
`terminal_element_size`, `channels`/`channel_count`, et les capacités de sortie : `uplinks`, `downlinks`,
`busy`, `mac_counters`, `trace`, `terminals` (avec leurs capacités, pointeurs de compteurs et
`terminal_count` à l'offset 264). Seul `mac_counters` est facultatif ; `uplinks`, `downlinks` et `busy`
sont obligatoires même à capacité 0.

## 3. Modes de configuration canal

| Mode | Condition | Effet |
|---|---|---|
| **Historique** | `channels = NULL`, `channel_count = 0`, `channel_plan = NONE` | chemin historique inchangé (défauts moteur, aucun canal explicite) |
| **Explicite EU868** | `channels` non NULL, `channel_count == device_count > 0`, `channel_plan = EU868_RP002_1_0_5` | configuration fournie par dispositif |

Les défauts (`present = 0`) ne sont pas dupliqués ici : ils viennent uniquement de
`loop_eu868_default_channels()` et `loop_eu868_plan()` (canaux 0, 1, 2 actifs, `dr_mask` 0x3F). Un mélange
d'éléments `present = 0` et `present = 1` est valide ; il est testé en 6.2.6.

## 4. Validations et codes d'erreur

Les codes sont `LSIM_STATUS_CHANNEL_<NOM>` = 1000 + n. Les codes historiques (dont la collision 800 entre
MESH et CLASSB, conservée selon A7 et A8) ne sont pas modifiés. La validation est complète avant toute
écriture ; une erreur ne produit aucune sortie partielle (A3).

| Nom | Valeur | Cas déclencheur |
|---|---|---|
| `LSIM_STATUS_CHANNEL_ARGS_SIZE` | 1001 | `struct_size` inattendu |
| `LSIM_STATUS_CHANNEL_ABI_VERSION` | 1002 | `abi_version != 3` |
| `LSIM_STATUS_CHANNEL_ELEMENT_SIZE` | 1003 | taille d'élément inattendue |
| `LSIM_STATUS_CHANNEL_PLAN` | 1004 | `channel_plan` inconnu |
| `LSIM_STATUS_CHANNEL_MODE` | 1005 | mode incohérent (plan sans élément, élément sans plan, `channel_count != device_count`) |
| `LSIM_STATUS_CHANNEL_DEVICE_INDEX` | 1006 | index hors plage ou en double |
| `LSIM_STATUS_CHANNEL_PRESENT_FLAG` | 1007 | `present` autre que 0 ou 1 |
| `LSIM_STATUS_CHANNEL_FIELDS_WITHOUT_PRESENT` | 1008 | champs non vides avec `present = 0` |
| `LSIM_STATUS_CHANNEL_RESERVED_NONZERO` | 1009 | champ réservé non nul |
| `LSIM_STATUS_CHANNEL_INDEX_UNSUPPORTED` | 1010 | canal 16 à 79 dans `dr_mask`, `enabled` ou `server_defined` (A1 : 80 emplacements, 16 à 79 refusés) |
| `LSIM_STATUS_CHANNEL_DR_MASK_INVALID` | 1011 | `dr_mask` nul sur un canal défini (ou invalide) |
| `LSIM_STATUS_CHANNEL_ENABLED_UNDEFINED` | 1012 | canal actif non défini |
| `LSIM_STATUS_CHANNEL_ENABLED_EMPTY` | 1013 | aucun canal actif (A4 : refus de l'ensemble vide) |
| `LSIM_STATUS_CHANNEL_SERVER_VIEW_EMPTY` | 1014 | vue serveur vide |
| `LSIM_STATUS_CHANNEL_TRACE_MODE` | 1015 | `trace_enabled` hors de {0, 1}, ou `trace_enabled = 0` avec `trace` non NULL ou `trace_capacity` non nulle (A10) |
| `LSIM_STATUS_CHANNEL_TRACE_BUFFER_TOO_SMALL` | 1016 | capacité trace insuffisante |
| `LSIM_STATUS_CHANNEL_TERMINAL_BUFFER_TOO_SMALL` | 1017 | capacité terminaux insuffisante |
| `LSIM_STATUS_CHANNEL_BUFFERS_ALIASED` | 1018 | sorties qui se chevauchent |
| `LSIM_STATUS_CHANNEL_NULL_POINTER` | 1019 | pointeur obligatoire NULL : `uplinks`, `downlinks`, `busy` (même à capacité 0) ; `trace` si `trace_enabled = 1` (même à capacité 0) ; `terminals` si capacité positive ; compteurs requis |
| `LSIM_STATUS_CHANNEL_RANGE_OVERFLOW` | 1020 | dépassement d'intervalle (cible 64 bits, A11) |
| `LSIM_STATUS_CHANNEL_MISALIGNED` | 1021 | pointeur mal aligné |

Priorité des erreurs de capacité (gelée en 6.2.5) : uplinks, puis downlinks et busy, puis trace, puis
terminaux. Convention des pointeurs de buffers :
- `uplinks`, `downlinks`, `busy` : NULL refusé, même à capacité 0 ;
- `trace` : NULL refusé si `trace_enabled = 1`, même à capacité 0 ; si `trace_enabled = 0`, `trace` doit
  être NULL et `trace_capacity` doit valoir 0 (A10) ;
- `terminals` : NULL avec capacité 0 signifie « buffer non demandé ». Cette convention ne s'étend à aucun
  autre buffer.

`mac_counters` facultatif : s'il est fourni, il doit être aligné, sans chevauchement et
valide en mémoire. `dr_mask` ne rejette pas un bit sans entrée `dr_sf` (le moteur n'est pas durci).

Limite documentée : `DeviceTransmitting` n'est pas atteignable en boucle fermée sous la règle C1 (uplink
suivant après RX2, TS001 §3.3.6). Le code de perte existe et son convertisseur est testé sur des
événements construits, pas sur une simulation (6.2.5, décision option a).

## 5. Sorties

- `uplinks`, `downlinks`, `busy` : écrits seulement après validation complète.
- `per_device`, `totals`, `mac_counters` : écrits seulement si la validation réussit.
- Erreur de capacité (`*_CAPACITY_TOO_SMALL`) : les cinq compteurs requis (`uplink_count`,
  `downlink_count`, `busy_count`, `trace_count`, `terminal_count`) reçoivent le nombre réel d'éléments
  produits. Ce sont des compteurs, pas des buffers : aucun buffer de données ni statistique
  (`per_device`, `totals`, `mac_counters`) n'est écrit.
- Erreur de validation ou d'engine : aucune sortie n'est écrite, compteurs compris.
- Trace : format v3, ordre d'émission du moteur conservé (6.2.4).
- Terminaux : `dr_mask` et `enabled` issus de l'état final ; la vue serveur n'est pas une sortie terminale.

## 6. Trace v3

### 6.1 Énumérations

| Champ | Valeurs |
|---|---|
| `kind` | `uplink` 0, `link_adr_ans` 1, `exclusion` 2, `adr_decision` 3, `link_adr_req` 4, `downlink` 5, `apply` 6 |
| `origin` | `normative` 0 (TS001), `simulator_policy` 1 (politique du simulateur, non TS001), `radio` 2 |
| `action` | `created` 0, `renewed` 1, `expired` 2 |
| `target` | `data_rate` 0, `power` 1, `channel` 2, `mask` 3 |
| `loss` | `none` 0, `device_transmitting` 1, `no_gateway_slot` 2, `below_sensitivity` 3 |
| `reason_channel` | `ok` 0, `rfu_cntl` 1, `undefined_channel` 2, `all_disabled` 3, `incompatible_with_data_rate` 4, `rfu_bits` 5 |
| `reason_dr` | `ok` 0, `ignored` 1, `unknown_dr` 2, `not_supported_by_channels` 3 |
| `reason_power` | `ok` 0, `ignored` 1, `reserved` 2 |

### 6.2 Sentinelles

- `downlink` = 0xFFFFFFFF (`LSIM_TRACE_NO_INDEX`) sauf pour `link_adr_req`, `downlink` et `apply`.
- `status` = 0xFF (`LSIM_TRACE_STATUS_NONE`) sauf pour `link_adr_ans` et `apply`.
- `loss` est non nulle seulement pour `downlink`.
- `reason_*` ne sont renseignés que pour `apply`.
- `value` est défini par type (décision contractuelle, validée) :
  - `uplink`, `link_adr_ans`, `adr_decision`, `link_adr_req`, `apply` : `value = 0` ;
  - `downlink` : `value = commands`, masque limité aux cinq bits connus `0x01` (LinkADR), `0x02`
    (DutyCycle), `0x04` (LinkCheck), `0x08` (DeviceTime), `0x10` (DevStatus), soit `value ≤ 0x1F` ;
  - `exclusion` : valeur de la cible, avec bornes par cible :

    | `target` | `value` | Borne |
    |---|---|---|
    | `data_rate` | débit exclu | 0 à 15 |
    | `power` | index de puissance exclu | 0 à 14 |
    | `channel` | index de canal exclu | 0 à 15 |
    | `mask` | masque complet de 16 bits (`block0`) | 0 à 65535 |

    Pour `power` : les valeurs **8 à 14 sont des index réservés** (RP002 Table 13). Ils sont refusables
    par le terminal puis inscrits dans une exclusion (cas des requêtes forcées, testé par
    `test_forced_110_power_refused_valid_mask_and_dr_not_applied` et `test_forced_000_everything_refused`).
    L'index **15** est la valeur ignorée : il n'est jamais refusé, donc jamais exclu.
- `flag` est défini par type : `link_adr_ans` = `(status == 0x07)` (indicateur d'acceptation complète) ;
  `link_adr_req` = `false` (sans objet) ; `downlink` = reçue ; `uplink` = reçu ; `apply` = tous les bits ACK ;
  `exclusion` et `adr_decision` : non définis par ce contrat (voir section 9.3).
- `dr` ou `power_index` = 15 (`LSIM_TRACE_FIELD_IGNORE`) signifie « ignoré » dans une `link_adr_req`.

Dans le modèle Python, la sentinelle est exprimée par `null` ; `trace_raw_downlink` et `trace_raw_status`
rendent les valeurs brutes.

### 6.3 Invariants

- `downlink` reçue ⇔ `flag = 1` et `loss = none`.
- `link_adr_ans` : `status` = bits ACK (bit 0 ChannelMaskACK, bit 1 DataRateACK, bit 2 PowerACK) ; `flag` = `(status == 0x07)`.
- `apply` : `status` = `to_wire()`, `flag` = tous les bits ACK à 1.

## 7. Schémas Python

Généré par `python/lsim/abi_v3_contract.py` (`write_schemas`) dans `schemas/abi/v3/` :

- `closed_loop_v3_channel_set.schema.json` : mode, éléments canal, validations de présence et de plage ;
- `closed_loop_v3_terminal_state.schema.json` : état terminal ;
- `closed_loop_v3_trace_event.schema.json` : événement de trace, avec conditionnels.

Les schémas ne sont **pas** ajoutés à `schemas/api/v1` (qui conserve son test d'ensemble exact). Le test
`python/tests/test_abi_v3_contract.py` vérifie la parité des constantes avec `c_api.h` et `engine.hpp`, la
synchronisation des schémas, les validations, les conditionnels de trace, l'unicité de la liaison Python
(seul `closed_loop_v3.py` référence la fonction native) et la présence de cette documentation.

## 8. Décisions contractuelles et points restants

### 8.1 Décisions appliquées (étape 6.2.7, correctif contractuel Python)

1. **`flag` de `link_adr_ans`** : conservé, égal à `(status == 0x07)`, documenté comme indicateur
   d'acceptation complète. Imposé par `TraceEventV3` et par le schéma.
2. **`value`** : `0` pour `uplink`, `link_adr_ans`, `adr_decision`, `link_adr_req`, `apply` ; `commands`
   (≤ 0x1F) pour `downlink` ; valeur de la cible pour `exclusion`, bornée par cible (§6.2).
3. **`flag` de `link_adr_req`** : toujours `false` (sans objet). Imposé.

Ces décisions sont compatibles avec le moteur C++ tel qu'il est (vérifié par lecture de
`engine.cpp` : écritures de `flag` et `value` aux emplacements indiqués dans le rapport de
clarification), et avec les tests C++ existants, qui ne sont pas modifiés.

### 8.2 Points restants (non tranchés, non appliqués)

1. **Commentaire de `LoopTraceEvent.flag`** (`engine.hpp`, l. 449) : faux pour `adr_decision`, incomplet
   pour `downlink`, `link_adr_ans` et `exclusion` ; ne décrit pas la valeur `value` du masque. Correction
   documentaire prévue en étape 8 (A9), non appliquée ici (moteur C++ hors périmètre).
2. **`docs/CHANNEL_MASK_MODEL.md`, section 6** : la table ne définit pas `value` pour `Exclusion` (bornes
   par cible et masque 16 bits), ni `flag` pour `LinkAdrAns` et `LinkAdrReq`. Ce n'est pas une
   contradiction, mais une absence ; la mise à jour est à faire hors de cette étape.
3. **Collision 800** entre codes historiques MESH et CLASSB : conservée (A7).
4. **`DeviceTransmitting`** : inatteignable en boucle fermée (voir §4).

## 9. Étape 6.3 : fonction publique, liaison Python et preuves

### 9.1 Ce qui est en place

| Élément | Emplacement | Statut |
|---|---|---|
| Prototype | `core/include/lsim/c_api.h` | déclaré, `LSIM_API int32_t lsim_simulate_closed_loop_v3(const lsim_closed_loop_v3_args*)` |
| Définition | `core/src/c_api_closed_loop_v3.cpp` | définie ; compilée avec `c_api.h`, donc le prototype correspond à la définition (une divergence est une erreur de compilation) |
| Export | `core/exports.map` (`lsim_*`) | exporté ; `nm -D --defined-only build/liblsim_core.so` affiche `T lsim_simulate_closed_loop_v3` |
| Liaison Python | `python/lsim/closed_loop_v3.py` | seul module qui référence le symbole ; charge `LIB` de `lsim._native` |
| Tests C++ | `core/tests/test_closed_loop_v3_api.cpp` | appel réel de la fonction exportée, dans la suite permanente |
| Tests Python natifs | `python/tests/test_closed_loop_v3_native.py` | 18 tests avec la bibliothèque compilée |

La fonction n'est pas supprimée pour satisfaire un ancien garde-fou. Le garde-fou
`test_v3_python_binding_is_the_single_native_module` remplace l'ancienne interdiction par une vérification
positive : un seul module référence le symbole, la liaison appelle `LIB.lsim_simulate_closed_loop_v3(ctypes.pointer(args))`
et aucun autre module de `python/lsim` n'importe la liaison v3.

### 9.2 Preuves exécutées (suites de tests nommées)

- Tailles et décalages : `static_assert` C (`core/tests/test_abi_v3_prep.cpp`) et
  `test_structure_sizes_match_c_static_asserts`, `test_structure_offsets_match_c_static_asserts` (Python).
- Appel réel : `test_native_symbol_is_exported_and_callable`, `test_library_loaded_is_the_compiled_core_and_exports_the_symbol`,
  `test_python_call_reaches_the_native_symbol_with_v3_header`.
- Erreurs natives remontées en `StatusError` sans résultat : `test_invalid_channel_configuration_is_refused_by_core_with_status`,
  `test_dr_mask_above_region_maximum_is_refused`, `test_uplink_capacity_error_raises_status_and_returns_nothing`,
  `test_trace_capacity_error_raises_channel_status` (code 1016 pour la trace).
- Parité historique : `test_historical_parity_with_v2_and_gw2`, `test_historical_parity_with_trace_enabled` (C++) ;
  `test_historical_mode_matches_v2_outcome`, `test_explicit_defaults_match_historical_with_trace`,
  `test_trace_does_not_change_results` (Python).
- Trace : `test_trace_events_and_sentinels` (sentinelles, `flag` et `value` par type), `test_trace_cross_checks_across_scenarios`
  (cohérence trace ↔ sorties sur plusieurs scénarios), `test_trace_order_stable_at_equal_timestamps`
  (ordre reproductible à `t_ns` identique ; la condition est non vide).
- ADR et terminal : `test_adr_success_applies_to_terminal`, `test_adr_refusal_creates_exclusion`,
  `test_refused_apply_does_not_change_terminal_dr`, `test_adr_success_updates_terminal_state_and_trace`,
  `test_adr_refusal_creates_exclusion_and_keeps_low_data_rates` (Python).
- Validation et capacité : `test_validation_error_writes_nothing`, `test_capacity_errors_write_counts_only`,
  `test_null_and_optional_buffers`, `test_alias_and_alignment`, `test_common_errors_match_v2`.
- Compteurs : `test_mac_counter_invariants` (C++), `test_mac_counters_invariants_on_native_outcome` (Python).
- Mutations (étape 2, relevées pendant l'étape) : inversion du `flag` d'`apply` : 8 échecs ; descente forcée à `none` :
  44 échecs ; fichiers restaurés à l'identique.

### 9.3 Limites documentées (non tranchées, non corrigées)

1. **Exclusion de puissance 8 à 14 : non atteignable par l'API.** Les requêtes LinkADRReq sont produites par le
   moteur à partir de la région (`max_tx_power_index`). Les scénarios EU868 restent à Power ≤ 7. Les exclusions de
   puissance 8 à 14 ne sont couvertes que par les requêtes forcées au niveau moteur
   (`test_forced_110_power_refused_valid_mask_and_dr_not_applied`, `test_forced_000_everything_refused`). La
   borne ABI 0 à 14 reste vérifiée pour toute valeur produite.
2. **Incohérence à arbitrer (moteur, non modifiée, non exercée par un test).** `engine.cpp` l.2212 règle
   `plan.max_power_index = rg.max_tx_power_index` (région), alors que `loop_adr.cpp` l.123 refuse un index
   au-delà de `plan.max_power_index`, et que le planificateur EU868 plafonne à `kLoopEuMaxPowerIndex = 7`
   (`loop_adr.cpp` l.212). Lecture du code : avec une région à `max_tx_power_index = 14`, un terminal accepterait
   donc les index réservés 8 à 14 (RP002 Table 13). Le contrat dit « refusables par le terminal » ; le comportement
   dépendrait donc de la région. Ce point n'a pas été exécuté ; décision requise avant toute correction.
3. **Origine de `link_adr_req`.** Le moteur écrit `simulator_policy` ; le message est TS001. Ce n'est pas tranché
   par le contrat, donc non vérifié par les tests.
4. **`flag` de `adr_decision`.** Le contrat dit « en attente » ; le moteur écrit `want != current`. Non vérifié
   par les tests. À trancher avec le point 3 (documentation de `LoopTraceEvent.flag`, A9).
5. **`DeviceTransmitting` inatteignable** en boucle fermée sous C1 (section 4). Le convertisseur est testé sur
   des événements construits.
6. **Cible 64 bits uniquement** (A11).

### 9.4 Ajouts hors suivi de l'étape 6.3

`test_null_zero_capacity_rules` (`core/tests/test_abi_v3_prep.cpp`) vérifie la convention de la section 4 :
NULL avec capacité 0 est refusé pour `uplinks`, `downlinks`, `busy` et `trace` (si `trace_enabled = 1`), accepté
pour `terminals`. Ces 5 vérifications expliquent l'écart de 678940 à 678945 relevé dans les mesures de l'audit.
Ce test a été ajouté après l'audit, sans être consigné : il est conservé et signalé.

