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
1. **Socle** (en cours) : étape 1 faite, bloc `mac:` validé (`link_check_every`, `device_status_every`), sans effet moteur. Reste : LinkCheckReq/Ans, DevStatusReq/Ans en FOpts, événements de trace, temps d'antenne avec FOpts.
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
