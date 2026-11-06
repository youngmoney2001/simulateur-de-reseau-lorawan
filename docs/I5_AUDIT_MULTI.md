# Audit d'état — moteur multi-passerelles (jalon I5)

**Objet.** Établir, par mesure et par citation de code, ce que le moteur multi-passerelles fait
réellement aujourd'hui, et où sont les écarts. Ce document **ne spécifie rien** : il précède toute
conception d'I5.

**Méthode.** Chaque affirmation renvoie à un fichier et une ligne, ou à une mesure exécutée. Les
endroits où la connaissance manque sont marqués **réserve** et ne sont pas comblés par inférence.

---

## 1. Premier constat : le périmètre d'I5 n'est écrit nulle part

L'expression « trajectoire T2 » apparaît à exactement **deux** endroits du dépôt, et n'est
**jamais définie** :

| Emplacement | Texte |
|---|---|
| `docs/DOWNLINK_PLAN_ABI_V2.md:183` | `Multi-passerelles (trajectoire T2) \| jalon I5` |
| `docs/I6_C_PARITE_N.md:235` | `I5 — multi-passerelles (trajectoire T2) \| lot distinct` |

Il n'existe aucun `docs/I5_*.md`. **Réserve n°1** : le périmètre d'I5 n'est pas documenté ; le
présent audit ne prétend pas le retrouver, seulement inventorier l'état du code.

---

## 2. Deuxième constat, contre-intuitif : le multi-passerelles est déjà en C++

Le chemin multi-passerelles n'est **pas** un chemin Python en attente de portage. Il s'exécute
déjà dans le cœur :

| Symbole exporté | Adresse | Rôle |
|---|---|---|
| `lsim_simulate_uplinks_multi` | `2f6e0` | uplinks seuls |
| `lsim_simulate_uplinks_multi_dl` | `e400` | uplinks + descentes |
| `lsim_simulate_uplinks_multi_dl_v2` | `e470` | idem, avec frontaux RF |

Déclarations dans `core/include/lsim/engine.hpp:667` et `:728`. Implémentation dans
`core/src/engine.cpp:758` et `:1021`. Pont Python : `python/lsim/_native.py:638-646`,
sélection de l'entrée par `multi_dl_native_function` (`python/lsim/simulator.py:363`).

La docstring de `simulate_multi_downlinks` (`python/lsim/simulator.py:705`) annonce :
« Passerelles multiples avec downlinks et **demi-duplex par passerelle (calcul exact, C++)** ».

**Conséquence** : I5 ne peut pas consister à « porter le multi-passerelles en C++ ».

### 2.1 L'occupation par passerelle existe déjà

C'est le point le plus mal documenté du dépôt. Le chemin multi tient une occupation **par
passerelle** :

- `core/src/engine.cpp:1145` — `std::vector<BusyMap> busy(G);` (un créneau d'émission par
  passerelle, `BusyMap = std::map<SimTime, SimTime>`, défini `:985`) ;
- `core/src/engine.cpp:1203` — `busy[g][start] = start + air;` (réservation sur la passerelle `g`
  seulement) ;
- `core/src/engine.cpp:771` — `std::vector<std::vector<Interval>> busy(gateway_count);` pour
  `simulate_uplinks_multi`, qui **accepte en entrée** une occupation par passerelle
  (`engine.hpp:664`) : « une trame qui chevauche l'émission de **SA** passerelle n'y est pas
  décodée (`LostGatewayBusy` à cette passerelle seulement) » ;
- `core/src/engine.cpp:1241` — `map_intersects(busy[g], ta.start, ta.end)` : le demi-duplex est
  évalué passerelle par passerelle.

Borne : `kMaxGateways = 64` (`core/include/lsim/engine.hpp:624`), cohérent avec
`MAX_GATEWAYS = 64` côté Python (`python/lsim/simulator.py:578`, `python/lsim/scenario.py:42`).

> **Note** : `python/lsim/gwmp_server.py:42` définit `MAX_GATEWAYS = 4096`. Ce n'est pas une
> incohérence évidente — c'est la table du serveur GWMP, distincte du moteur de simulation — mais
> la coexistence de deux bornes de même nom est un piège de lecture. **Réserve n°2** : la
> relation entre les deux n'a pas été vérifiée.

---

## 3. Écart n°1 — le temps d'antenne RX1 utilise le SF montant et une bande codée en dur

C'est le verdict **(B)** de `docs/I6_B1_REGIONS.md:458` (« Divergent — constaté, non corrigé »).
Il est ici **localisé au numéro de ligne**.

### 3.1 Le code

```cpp
// core/src/engine.cpp:966
// Airtime d'un downlink au débit RX1 (= SF de l'uplink, BW 125 kHz), CR 4/5, en-tête explicite,
// sans CRC (LoRaWAN).
SimStatus downlink_airtime(std::uint8_t sf, std::uint32_t payload_bytes, SimTime& out) {
    ...
    rc.bandwidth = lora::Bandwidth::Bw125kHz;
    ...
}
```

```cpp
// core/src/engine.cpp:1163
if (downlink_airtime(ta.sf, payload, air) != SimStatus::Ok) return SimStatus::InvalidInput;
std::uint8_t sf_used = ta.sf;
```

`ta.sf` est le SF **montant** (`core/src/engine.cpp:1082` : `tx.sf = d.spreading_factor;`).
La bande RX1 est **littéralement codée en dur** à 125 kHz.

Le repli RX2 a le même défaut sur la bande (`engine.cpp:1185` :
`downlink_airtime(rule.rx2_sf, payload, air2)`), mais son SF vient bien de `rule.rx2_sf`.

### 3.2 Mesure de l'écart

Table de **sensibilité** — facteur d'erreur du temps d'antenne réservé par le moteur, en fonction
du DR RX1 réellement imposé. Charge de 40 octets + 13 de surcharge = 53. Aucune affirmation
régionale n'est faite ici : on balaie tout le couple (SF, bande) possible.

Lignes : le DR RX1 réel. Colonnes : le SF montant. Cellule = ce que le moteur réserve ÷ ce qu'il
faudrait réserver.

| RX1 réel | SF7 | SF8 | SF9 | SF10 | SF11 | SF12 |
|---|---:|---:|---:|---:|---:|---:|
| SF7/125k | **1.00x** | 1.80x | 3.20x | 6.00x | 12.81x | 24.02x |
| SF7/500k | 4.00x | 7.20x | 12.81x | 24.02x | 51.23x | 96.08x |
| SF8/125k | 0.56x | **1.00x** | 1.78x | 3.34x | 7.11x | 13.34x |
| SF8/500k | 2.22x | 4.00x | 7.11x | 13.34x | 28.45x | 53.36x |
| SF9/125k | 0.31x | 0.56x | **1.00x** | 1.88x | 4.00x | 7.50x |
| SF9/500k | 1.25x | 2.25x | 4.00x | 7.50x | 16.00x | 30.01x |
| SF10/125k | 0.17x | 0.30x | 0.53x | **1.00x** | 2.13x | 4.00x |
| SF10/500k | 0.67x | 1.20x | 2.13x | 4.00x | 8.53x | 16.00x |
| SF11/125k | 0.08x | 0.14x | 0.25x | 0.47x | **1.00x** | 1.88x |
| SF11/500k | 0.36x | 0.64x | 1.14x | 2.14x | 4.57x | 8.57x |
| SF12/125k | 0.04x | 0.07x | 0.13x | 0.25x | 0.53x | **1.00x** |
| SF12/500k | 0.19x | 0.35x | 0.61x | 1.15x | 2.46x | 4.61x |

**Lecture.** Le moteur est exact **uniquement** sur la diagonale `SF_n/125k`, c'est-à-dire quand
le DR RX1 égale le SF montant à 125 kHz — l'hypothèse inscrite dans le commentaire de la fonction.
Partout ailleurs il se trompe, jusqu'à **96x** (RX1 à SF7/500 kHz pour un uplink SF12) et, dans
l'autre sens, jusqu'à **0.04x** — une sous-réservation d'un facteur 25, qui laisse passer des
descentes qui devraient être refusées pour occupation.

**Portée du défaut.** Il affecte la durée réservée sur l'émetteur (`busy[g]`), donc l'admission
des descentes suivantes et le demi-duplex de la passerelle. Il n'affecte pas le temps d'antenne
**montant**, qui est calculé séparément.

### 3.3 Ce que dit l'oracle Python

`python/lsim/trace_events.py`, `downlink_airtime_by_device` (vers `:1644`) consomme le SF **et** la
bande de RX1. `docs/I6_B1_REGIONS.md:466` : « `build_multi_trace` n'exploite que `rx1_hz`,
`freq_hz` et `dr` ; seul `downlink_airtime_by_device` consomme le SF et la bande de RX1 ».

Le chemin **mono / boucle fermée** a le même défaut sur le SF mais pas sur la bande :
`core/src/engine.cpp:1943-1946` fait `rad.rx1_sf = ta.sf;` puis
`plan::downlink_airtime_ns(rad, base + fopts, air_rx1)`, où `rad.rx1_bw_hz` provient de la table
radio et peut valoir 250 ou 500 kHz.

**Conclusion mesurée** : les deux chemins C++ partagent l'hypothèse « RX1 = SF montant ». Ils
diffèrent sur la bande : codée en dur à 125 kHz dans le multi, lue dans la table radio dans la
boucle fermée.

---

## 4. Écart n°2 — la boucle fermée est mono-passerelle, et le refuse

`simulate_closed_loop` (`core/include/lsim/engine.hpp:434`) prend
`const GatewaySpec& gateway` (`:436`) — **une** passerelle. `LoopResult::gateway_busy`
(`engine.hpp:426`) est un seul `std::vector<Interval>`.

Côté Python, le multi-passerelles est **refusé** dès que des commandes MAC sont actives :

- `python/tests/test_mac_loop.py:119` — `test_closed_loop_refuses_join_and_gateways_and_accepts_reservations`
- `python/tests/test_mac_trace.py:95` — `test_mac_with_several_gateways_is_refused`

`docs/CLOSED_LOOP_PLAN.md` le dit explicitement : « Non porté (reste Python) : jointure, commandes
MAC, mesh, **multi-passerelles** » (`:28` et `:55`) ; « **S4 : mesh et multi-passerelles** : hors
périmètre initial ; refusés avec commandes actives tant qu'ils ne sont pas portés » (`:136`) ;
« Refusé explicitement (erreur) : jointure, passerelles multiples, mesh » (`:103`) ; « le chemin
Python de `build_trace` (`_build_trace_python`) reste pour les jointures, les **passerelles
multiples** et le mesh » (`:133-134`).

---

## 5. Écart n°3 — le chemin `plan` n'a pas de notion de passerelle

`lsim_plan_downlinks_v1` / `_v2` / `_v3` et `lsim::plan::plan_downlinks` ne prennent **aucune**
passerelle en paramètre. Le mot « gateway » n'apparaît dans `core/include/lsim/downlink_plan.hpp`
que deux fois, pour `gateway_tx_power_dbm` — un scalaire. L'émetteur y est unique **par
construction**, ce qui est cohérent : `plan_downlinks` modélise l'ordonnancement des descentes
d'**une** passerelle.

---

## 6. Le point `DETERMINISME.md` §6 est à moitié périmé

`docs/DETERMINISME.md:282` : « **Un seul émetteur.** L'occupation est unique ; le
multi-passerelles introduira une **occupation par passerelle**, et ce document devra être étendu. »

Or la portée de ce document est « **la boucle fermée** (`simulate_closed_loop`,
`simulate_closed_loop_channels`) » (`DETERMINISME.md:8`).

| Chemin | Occupation par passerelle ? |
|---|---|
| `simulate_uplinks_multi` | **oui** (`engine.cpp:771`) |
| `simulate_uplinks_multi_downlinks` | **oui** (`engine.cpp:1145`) |
| `simulate_closed_loop` | **non** — un seul `gateway_busy` (`engine.hpp:426`, `:436`) |

L'extension annoncée par §6 a donc eu lieu **pour le chemin multi**, mais pas pour la boucle
fermée, qui est la portée du document. La phrase n'a jamais été mise à jour. **Réserve n°3** :
rien n'indique que §6 visait la boucle fermée plutôt que l'ensemble du moteur ; la portée
déclarée du document penche pour la première lecture.

---

## 7. Synthèse — trois écarts, de nature différente

| # | Écart | Nature | Localisation | Gravité mesurée |
|---|---|---|---|---|
| 1 | Temps d'antenne RX1 = SF montant, bande 125 kHz en dur | **fidélité radio** | `engine.cpp:966-971`, `:1163` | facteur 0.04x à 96x selon le DR RX1 |
| 2 | Boucle fermée mono-passerelle | **périmètre fonctionnel** | `engine.hpp:426`, `:433` | refus explicite, pas un défaut |
| 3 | Chemin `plan` sans passerelle | **modélisation assumée** | `downlink_plan.hpp` | aucune — hors périmètre par construction |

Les trois ne doivent pas être confondus : le n°2 est un choix de périmètre explicite et assumé,
le n°3 est une propriété de conception, seul le **n°1 est un défaut**.

---

## 8. Réserves et limites de cet audit

1. **Le périmètre d'I5 n'est pas documenté** (§1). Cet audit ne le reconstitue pas.
2. **Deux bornes `MAX_GATEWAYS` coexistent** (64 et 4096) ; leur relation n'est pas vérifiée.
3. **La portée exacte de `DETERMINISME.md` §6** reste ambiguë.
4. **Aucune affirmation régionale** n'est faite ici. Les valeurs de la table du §3.2 balaient
   tout le couple (SF, bande) ; elles ne disent pas quel DR RX1 impose quelle région. Établir
   cette correspondance exige la lecture directe des tables RP002, qui n'a pas été refaite dans
   le cadre de cet audit. En particulier, la session porte une lacune connue : **la table 44 de
   RP002-1.0.5 n'a jamais été lue directement**.
5. **L'écart n°1 est mesuré sur le modèle de temps d'antenne, pas sur une simulation complète.**
   Son effet de bout en bout (nombre de descentes admises, occupation totale, taux de livraison)
   n'a pas été quantifié.

---

## 9. Questions ouvertes à trancher avant toute spécification

1. I5 doit-il traiter l'écart n°1 (fidélité radio du multi), l'écart n°2 (boucle fermée
   multi-passerelles), ou les deux ?
2. L'écart n°1 touche aussi le chemin **mono / boucle fermée** sur le SF (§3.3). Le corriger
   changerait des résultats existants dans les deux moteurs — le même arbitrage que celui déjà
   rendu pour la sensibilité RX1 en I3/C4. Faut-il le traiter dans I5 ou dans un lot distinct ?
3. Que recouvre exactement « trajectoire T2 » ?
