# Commandes MAC dans la simulation : plan par phases

Statut : phase 1, étape 1 faite (configuration). Le codec des 19 commandes existe déjà
(`python/lsim/mac.py`, `core/src/mac_commands.cpp`) ; son usage dans la simulation ne l'est pas.

## Décisions retenues
- Configuration : bloc `mac:` du scénario YAML, inclus dans l'empreinte SHA-256 (absent = hash inchangé).
- Journal : événements dédiés `mac_request` et `mac_answer`.
- Coût radio : octets MAC comptés dans le temps d'antenne, la charge et la consommation.
- Serveur : répond d'abord aux demandes des dispositifs ; les commandes initiées par le serveur viennent ensuite.
- Compatibilité : les scénarios sans commandes MAC gardent leurs résultats.

## Phases
1. **Socle** (en cours) : étape 1 faite, bloc `mac:` validé (`link_check_every` : LinkCheckReq émise par le dispositif en uplink ; `device_status_every` : DevStatusReq émise par le serveur en descente, réponse DevStatusAns en uplink). Étape 2 faite : calendrier et encodage dans `python/lsim/mac_plan.py`, testés. Étape 3 faite (couche protocole, `python/lsim/trace_events.py`) : LinkCheckReq reçue → LinkCheckAns dans un downlink (dédié s'il n'y en a pas) ; DevStatusReq dans les FOpts d'un downlink émis sur deux (période N) ; événements `mac_request` et `mac_answer` ; FOpts des downlinks comptés dans leur temps d'antenne. Uplinks : le moteur natif (`engine.cpp`, champ `link_check_every` de `EndDeviceSpec` / `lsim_end_device`) compte le LinkCheckReq de rang multiple de N comme 1 octet de plus dans la trame ; le temps d'antenne est donc calculé par émission. Physique LoRa : l'octet n'allonge l'émission que s'il franchit un bloc de symboles (SF7 : 12 → 13 octets passe de 20 à 25 symboles, 10 → 11 ne change rien). Multi-passerelles : refusé par le moteur. Marge de LinkCheckAns : `M = clamp(floor(RSSI_UL − S_ref(SF, 125 kHz) − marge_installation), 0, 254)` ; S_ref est la sensibilité SX1276 qui sert au simulateur pour décider de la perte, donc M est la marge au-dessus du seuil de réception (en dB). Elle égale la marge de démodulation SNR − SNR_requis seulement si S_ref correspond à ce seuil, ce que la fiche SX1276 suppose ; la marge normative LoRaWAN n'est pas modélisée séparément. `link_margin_installation_db` (0 par défaut, 0..60) est configurable dans le bloc `mac:`. Une seule passerelle. Reste : DevStatusAns côté dispositif, affichage dans l'interface, vecteurs de référence.
DevStatusAns : la réponse n'existe que si la requête est reçue, donc son octet d'uplink n'est connu qu'après la trace. Le moteur fixe aujourd'hui le temps d'antenne des uplinks avant la simulation (`link_check_every`, rang connu d'avance) : il faut soit un calendrier de rangs à octets supplémentaires passé au moteur (ABI à étendre), soit une itération à point fixe dans `build_trace`. Choix à arrêter avant implémentation.
Annotations : `mac_request` et les `mac_answer` ajoutés à un downlink n'ont pas de saut propre (pas de trame redessinée) ; seul un downlink dédié à une réponse en porte un.
2. **ADR et temps** : LinkADRReq/Ans (via la décision ADR existante), DeviceTimeReq/Ans, DutyCycleReq/Ans.
3. **Configuration radio et classes** : RXParamSetup, NewChannel, RXTimingSetup, DlChannel, ADRParamSetup, PingSlot (info, channel), BeaconFreq, RejoinParamSetup, ForceRejoin, avec leurs effets sur le modèle.
4. **Orchestration** : commandes initiées par le serveur, files de descentes, réponses différées, refus, expiration, interaction avec les classes A, B et C.
5. **Validation et interface** : vecteurs de référence, conformité TS001-1.1.0, journal détaillé, métriques, limites documentées.

## Règles à respecter
- FOpts limité à 15 octets : pas de troncature ; les commandes excédentaires passent dans une trame suivante selon les règles de transport.
- Direction explicite : commandes du dispositif (uplink) et du réseau (downlink).
- Réponse positive : applique l'état. Réponse négative : n'applique pas la configuration refusée.
- Fenêtres de réception et disponibilité des descentes respectées.
- Reproductibilité : même scénario, mêmes décisions MAC.
- Séparer ce qui est issu de la spécification de ce qui est une hypothèse du moteur.
