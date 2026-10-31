# Matrice des fonctionnalités — état au 2026-10-31 (`68176d6`)

Légende : **IT** = implémentée et testée · **IP** = implémentée, partiellement couverte ·
**AD** = absente / non démontrée.
La colonne « Preuve » renvoie à un artefact **présent dans le dépôt** ou à une mesure **rejouée
pendant l'audit**. Les domaines marqués « non audité en profondeur » n'ont pas été inspectés
ligne à ligne ici : leur existence est certaine, leur qualité est réputée acquise des phases
antérieures, non re-vérifiée dans cet audit.

| # | Domaine | État | Preuve | Limites / réserves |
|---|---|---|---|---|
| 1 | **Moteur LoRaWAN classe A** (déploiement, airtime, collisions, sensibilité, capture) | **IT** | `core/src/engine.cpp`, `core/tests/test_engine.cpp`, 685249 vérifications C++ | Moteur non audité chemins par chemins ici |
| 2 | **MAC** : LinkADR, DutyCycle, LinkCheck, DeviceTime, DevStatus | **IT** | `core/src/mac_commands.cpp`, `core/src/loop_adr.cpp`, `python/lsim/mac.py`, `test_mac.py`, `test_loop_adr.cpp` | 3 exigences TS001 §5 restent partielles/non vérifiées dans `docs/CONFORMANCE_MATRIX.md` (M1, M3, M4 de **ce** tableau, sans rapport avec les M1–M4 de l'audit R2b) |
| 3 | **ADR** (algorithme) | **IT** | `core/src/*adr*`, `test_adr.cpp`, `test_linkadr_wiring.py` | Algorithme **non modifié** depuis la base ; toute évolution est interdite par décision verrouillée |
| 4 | **Régions et duty cycle** (EU868, US915, AU915, AS923, IN865, KR920, RU864) | **IT** | `python/lsim/{eu868,au915,as923,in865,kr920,ru864}.py`, `test_*`, `docs/REGULATORY_SOURCES.md` | Non audité en profondeur |
| 5 | **Sensibilité passerelle v2** (absolue, par SF, SX1303 / RAK7249) | **IT** | `core/src/*sensitivity*`, `lsim_simulate_uplinks_trace_gw2*`, `test_gateway_sensitivity.py`, `test_geo_sensitivity.py` | SF5 : valeur **indicative** (documentée) |
| 6 | **Boucle fermée** v1 → v4 | **IT** | `lsim_simulate_closed_loop_v1..v4`, `python/lsim/closed_loop_v3.py`, `test_closed_loop_v3_api.cpp`, `test_closed_loop_v3_native.py` | v4 = enveloppe v3 + frontal ; pas d'extension fonctionnelle |
| 7 | **Frontal RF v4** — ABI et API Python | **IT** | 95 symboles (91 + 4), `lsim_device_rf`/`lsim_gateway_rf`, `python/lsim/rf.py`, 11 tests C++ + 30 Python | **Pas de RF dans les scénarios YAML** (voir #13) |
| 8 | **Traces** : v1, v2, v3, gw2, gw2 v2, multi-downlinks v1/v2 | **IT** | `lsim_simulate_uplinks_trace*`, `lsim_simulate_uplinks_multi_dl*`, `test_downlink.py`, `test_downlink_plan_parity.py` | `simulate_uplinks_multi` **sans v4** |
| 9 | **Mesh** (relais, déduplication, enveloppe) | **IP** | `core/src/mesh.cpp`, `python/lsim/mesh.py`, `test_mesh.cpp`, `examples/mesh_relais_quartier.yaml` | **Aucune RF mesh** : pas de `mesh_rf`, pas de gain/perte par extrémité |
| 10 | **GeoJSON / couverture** | **IP** | `python/lsim/geo.py` (211 l.), `test_geo.py` **13 tests** (7 + 6 G1) | Couverture par (passerelle × groupe), **sans RF résolue** ; format à 7 clés |
| 11 | **Caractérisation RF R1** (comportement réel mesuré) | **IT** | `python/tests/test_rf_characterization_r1.py`, **24 tests**, verts | Figent l'état **antérieur** à R2b ; à relire si le modèle RF change |
| 12 | **Dispositions ABI x86-64 / i386** | **IP** | `core/tests/abi_layout.cpp`, **458 `static_assert`**, harnais x86-64 exécuté (53 structures / 454 grandeurs), i386 compilé | **14 littéraux LP64** subsistent dans `test_rf_frontend.cpp` ; **aucun moteur 32 bits** |
| 13 | **Scénarios YAML** (schémas, hash, refus stricts) | **IP** | `python/lsim/scenario.py`, `schemas/`, 4 exemples | **Aucune clé RF** ; le hash ignore les blocs absents |
| 14 | **Énergie** (profils RAK4631, SX1262+STM32L072, rapports) | **IT** | `core/src/energy.cpp`, `python/lsim/energy*.py`, `test_energy*.py` | Non audité en profondeur |
| 15 | **API HTTP / GWMP / web** | **IT** | `python/lsim/api_server.py`, `gwmp_server.py`, `web/`, `test_api_server.py`, `test_gwmp_server.py` | Non audité en profondeur ; hors périmètre RF |
| 16 | **Isolation des imports** | **IT** | `PathIsolationTests` : 3 scans + 1 test d'exécution (5 marqueurs) | Test d'exécution dépend d'un sous-processus (coût ~0,5 s) |
| 17 | **Moteur i386 complet** | **AD** | `gcc -m32` échoue au lien (`cannot find -lgcc`) | Ni compilation, ni exécution, ni tests 32 bits |
| 18 | **RF dans le chemin causal / plan** | **AD** | `downlink_plan.*`, `c_api_plan.cpp` non modifiés par R2b (décision documentée) | Aucun frontal par terminal dans ce chemin |
| 19 | **RF mesh** | **AD** | aucun symbole `lsim_mesh_*` modifié ; test « aucun symbole mesh appelé par le chemin RF » | Dépend de #9 et #8 |
| 20 | **`simulate_uplinks_multi` v4** | **AD** | signature sans paramètre RF ; aucun symbole `_v2` | Voir #8, #9 |

---

## 1. Couverture par nature de test

| Nature | Volume | Fichiers |
|---|---|---|
| Tests C++ | **31 fichiers**, **685249** vérifications | `core/tests/*.cpp` |
| Tests Python | **78 fichiers**, **1846 tests réussis**, **1 ignoré** (1847 collectés ; 16 sous-tests signalés séparément) | `python/tests/test_*.py` |
| Harnais ABI autonome | 458 `static_assert` | `core/tests/abi_layout.cpp` |
| Empreintes gelées | 6 runs + 6 traces | `scripts/mac_baseline_dump.py` |

---

## 2. Couverture spécifique des sujets F2 / G1 / F7 / R2b

| Sujet | Tests dédiés | Ce qui est réellement prouvé | Ce qui ne l'est pas |
|---|---|---|---|
| F2 — isolation des imports | 1 test d'exécution + 3 scans | `lsim.simulator`/`closed_loop_v3` non chargés à l'import, handle unique, refus d'une surcharge invalide | Contraste « avec RF » (RF absente du YAML) |
| G1 — regroupement GeoJSON | 6 tests | 7 clés, indices, effectifs, G × groupes, non-fusion, cohérence portée/anneau | RF résolue, `eirp_dbm`, indices par groupe |
| F7 — dispositions ABI | 458 `static_assert` | Tailles/décalages sur 2 ABI | Exécution 32 bits, édition de liens, moteur |
| R2b — frontal RF | 11 C++ + 30 Python + 24 R1 | Chaîne `G − L`, bits indépendants, non-cumul, remplacement du scalaire, routage, neutralité bit à bit | Scénario YAML, mesh, causal, multi sans downlinks |
