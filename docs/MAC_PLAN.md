# Commandes MAC dans la simulation : plan par phases

Statut : phase 1 terminée (socle) ; phases 2 à 5 à faire. Étape 1 faite (configuration). Le codec des 19 commandes existe déjà
(`python/lsim/mac.py`, `core/src/mac_commands.cpp`) ; son usage dans la simulation ne l'est pas.

## Décisions retenues
- Configuration : bloc `mac:` du scénario YAML, inclus dans l'empreinte SHA-256 (absent = hash inchangé).
- Journal : événements dédiés `mac_request` et `mac_answer`.
- Coût radio : octets MAC comptés dans le temps d'antenne, la charge et la consommation.
- Serveur : répond d'abord aux demandes des dispositifs ; les commandes initiées par le serveur viennent ensuite.
- Compatibilité : les scénarios sans commandes MAC gardent leurs résultats.

## Phases
1. **Socle** (en cours) : étape 1 faite, bloc `mac:` validé (`link_check_every` : LinkCheckReq émise par le dispositif en uplink ; `device_status_every` : DevStatusReq émise par le serveur en descente, réponse DevStatusAns en uplink). Étape 2 faite : calendrier et encodage dans `python/lsim/mac_plan.py`, testés. Étape 3 faite (couche protocole, `python/lsim/trace_events.py`) : LinkCheckReq reçue → LinkCheckAns dans un downlink (dédié s'il n'y en a pas) ; DevStatusReq dans les FOpts d'un downlink émis sur deux (période N) ; événements `mac_request` et `mac_answer` ; FOpts des downlinks comptés dans leur temps d'antenne. Uplinks : le moteur natif (`engine.cpp`, champ `link_check_every` de `EndDeviceSpec` / `lsim_end_device`) compte le LinkCheckReq de rang multiple de N comme 1 octet de plus dans la trame ; le temps d'antenne est donc calculé par émission. Physique LoRa : l'octet n'allonge l'émission que s'il franchit un bloc de symboles (SF7 : 12 → 13 octets passe de 20 à 25 symboles, 10 → 11 ne change rien). Multi-passerelles : refusé par le moteur. Marge de LinkCheckAns : `M = clamp(floor(RSSI_UL − S_ref(SF, 125 kHz) − marge_installation), 0, 254)` ; S_ref est la sensibilité SX1276 qui sert au simulateur pour décider de la perte, donc M est la marge au-dessus du seuil de réception (en dB). Elle égale la marge de démodulation SNR − SNR_requis seulement si S_ref correspond à ce seuil, ce que la fiche SX1276 suppose ; la marge normative LoRaWAN n'est pas modélisée séparément. `link_margin_installation_db` (0 par défaut, 0..60) est configurable dans le bloc `mac:`. Une seule passerelle. Restent hors phase 1 : vecteurs de référence (TS001 non accessible depuis le bac à sable).
DevStatusAns (choix retenu : calendrier de rangs passé au moteur, une seule exécution) : la réponse n'existe que si la requête est reçue. Le calendrier réserve donc 3 octets dans l'uplink suivant chaque requête planifiée, sans supposer la réponse ; la réponse n'est confirmée (événement `mac_answer`) que si cet uplink est reçu. ABI : `lsim_simulate_uplinks_trace_v2` ; v1 inchangée. Réservations : `python/lsim/mac_plan.py`, `trace_events.mac_reservations`, partagées par la trace et l'export.
Interface : le journal affiche un libellé MAC dédié (`macLabel`, `isMacEvent` dans `web/src/studio/animation.js`) et une classe de ligne propre.
Annotations : `mac_request` et les `mac_answer` ajoutés à un downlink n'ont pas de saut propre (pas de trame redessinée) ; seul un downlink dédié à une réponse en porte un.
2. **ADR et temps** : LinkADRReq/Ans (via la décision ADR existante), DeviceTimeReq/Ans, DutyCycleReq/Ans.
3. **Configuration radio et classes** : RXParamSetup, NewChannel, RXTimingSetup, DlChannel, ADRParamSetup, PingSlot (info, channel), BeaconFreq, RejoinParamSetup, ForceRejoin, avec leurs effets sur le modèle.
4. **Orchestration** : commandes initiées par le serveur, files de descentes, réponses différées, refus, expiration, interaction avec les classes A, B et C.
5. **Validation et interface** : vecteurs de référence, conformité TS001-1.1.0, journal détaillé, métriques, limites documentées.

## Vérification de la phase 1
- Sans bloc `mac:`, `run_scenario` (avec et sans profil énergie) et `build_trace` (deux jeux d'options) donnent des sorties identiques à la base `1f43370`, sur les trois scénarios de `examples/` : 6 résultats de run, 6 traces de 3 000 à 8 575 événements. Empreintes SHA-256 des sorties : run `d2cb0fac6c2d99504d888e497f5e07c56ba0f7b81deaf560584c78ee19b4e1ea`, trace `ed126d7ff5aac3b006f31067d73fb6a5f5b5bf9b597021589910c24db8dc865b`.
- Script reproductible : `scripts/mac_baseline_dump.py` (le fichier de trace s'écrit à côté, suffixe `.trace.json`).
- Tests : `pytest python/tests` (1531 réussis) ; `lsim_tests` (644 644 vérifications) ; `npm test` dans `web/` (29 réussis).

## Règles à respecter
- FOpts limité à 15 octets : pas de troncature ; les commandes excédentaires passent dans une trame suivante selon les règles de transport.
- Direction explicite : commandes du dispositif (uplink) et du réseau (downlink).
- Réponse positive : applique l'état. Réponse négative : n'applique pas la configuration refusée.
- Fenêtres de réception et disponibilité des descentes respectées.
- Reproductibilité : même scénario, mêmes décisions MAC.
- Séparer ce qui est issu de la spécification de ce qui est une hypothèse du moteur.
