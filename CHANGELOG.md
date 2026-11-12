# Journal des changements

## 0.1.0 (non publiée)

### Descentes à l'initiative du réseau — la classe d'écoute décide de l'attente

Un scénario peut désormais dire « le serveur veut envoyer une commande à cet instant », et le
résultat dit **quand elle est arrivée**. Bloc `downlink:` optionnel par groupe, résumé
`RunResult.downlink` / `RunSummary.downlink`, colonnes par dispositif.

**Ce que ça n'est pas.** Un ACK, une réponse MAC ou une charge `downlink_every` sont déclenchés
par un uplink : ils tombent dans RX1 ou RX2, et la classe n'y change rien (§3 bis de
`docs/MAC_CONSOLIDATION.md`). Ici la demande naît au moment choisi par le réseau, et c'est la
classe qui décide de la fenêtre — donc de l'attente. C'est la seule grandeur du simulateur que
la classe détermine à elle seule.

**Aucune ligne de C++ n'a été écrite.** Le moteur savait déjà planifier ces descentes
(`lsim_simulate_downlinks_env`, `core/src/downlink.cpp`). Ce qui manquait était le chaînon
scénario → déploiement → export : `Scenario.deploy()` ne renseignait jamais `downlink=`, et
`RunResult` jetait les compteurs que le moteur renvoyait.

**Mesuré** (terminal unique à 100 m, 3 messages espacés de 60 s, une demande à t = 10 s) :

| classe | attente | pourquoi |
|---|---|---|
| C | 0,00 s | la fenêtre est ouverte en permanence |
| B, `periodicity: 0` | 0,94 s | slot de ping toutes les ~0,96 s |
| A | 51,04 s | prochain uplink (60 s) puis RX1 |
| B, `periodicity: 7` | 64,30 s | un slot par période de 128 s |

**L'idée reçue à ne pas propager : la classe B n'est pas « meilleure que A », elle est de part et
d'autre.** Avec un slot fréquent elle fait mieux que A (0,94 s contre 51 s) ; avec un slot rare
elle fait **moins bien** (64 s). C'est la périodicité qui décide, pas l'étiquette. Un test
(`test_class_b_is_not_published_as_faster_than_a`) garde cette relation dans les deux sens.

**Le résumé est absent, pas à zéro, quand aucune descente n'est demandée.** Un objet de zéros
dirait « aucune descente livrée », ce qui est faux d'un run qui n'en a jamais demandé. La
distinction porte sur `requested`, pas sur `delivered` : une descente demandée et jamais
acheminée est un résultat, pas une absence de résultat.

**Pourquoi un passage natif dédié côté API.** Le seul point d'entrée qui planifie ces descentes
recalcule les uplinks dont il a besoin ; il ne se greffe pas sur une trace déjà produite. On ne
lui emprunte donc que les compteurs de descente. Ce qu'il ne voit pas : la charge MAC et l'ADR.
Mesuré — les réservations MAC allongent les trames (41,2 → 56,6 ms pour 10 octets à SF7) **sans
décaler leur début**. Reste RX1, qui s'ouvre après la fin de l'émission : l'écart induit est donc
de l'ordre de 15 ms, soit 0,03 % des 51 s de la classe A. Gardé par
`test_mac_payload_does_not_move_transmission_starts`.

**Compatibilité.** Champ optionnel partout : un scénario écrit avant garde ses chiffres **et**
son empreinte (`downlink` quitte le hachage quand il est absent, comme `device_class` valant
`"A"`). Colonnes Parquet et lignes de rapport ajoutées seulement si le run en planifie.

**Exposé dans l'atelier.** Réglage par capteur (classe d'écoute + « le serveur envoie une
commande ») et animation de l'attente sur le plan : la flèche « serveur → passerelle » part à
l'instant voulu, la flèche « passerelle → capteur » à l'instant où la fenêtre s'est ouverte, et
l'écart visible **est** l'attente. Nouvel endpoint `GET /device-classes` : les libellés, la
phrase d'ouverture et les intervalles entre créneaux de ping viennent du moteur, jamais
recopiés.

Le bloc dit ce que la classe **ne** change pas (un ACK tombe dans RX1/RX2 quelle que soit la
classe), et avertit dès qu'une classe B peut attendre plus longtemps qu'une classe A. La
périodicité n'apparaît qu'en classe B : ailleurs elle n'a aucun effet. L'animation ne trace
rien pour plusieurs commandes, la latence publiée étant alors une moyenne — dater chaque
émission de cette moyenne inventerait un instant.

**Publié aussi en multi-passerelles.** Toute session de l'atelier compile en forme `gateways`,
fût-elle à une seule passerelle ; le réserver au mono l'y aurait rendu invisible. Mesuré : les
instants d'émission sont identiques dans les deux formes, or l'attente n'est faite que de ces
instants et de la classe.

### Le serveur ne se configure pas — il commande, et dit ce qu'il a vu

Sa fenêtre d'équipement disait « pas de configuration dans cette version ». C'était vrai, et
ce n'était pas le défaut : le serveur n'a rien à régler dans l'atelier, puisque c'est **lui**
qui commande le débit, les canaux et les descentes. Le défaut était de n'y rien mettre.

Elle montre désormais ce que le serveur a **vu** du run affiché, par équipement : trames
remises sur émises, pertes (hors portée, puis en collision), débit commandé, canaux laissés au
terminal — plus, quand le run en a planifié, les commandes envoyées et leur attente moyenne.
C'est le seul endroit de l'atelier qui montre le réseau du point de vue de celui qui décide.

**Rien n'y est recopié depuis les formulaires.** Un champ que le run n'a pas observé reste
vide plutôt que d'afficher une valeur que personne n'a mesurée : les canaux d'un run qui ne
les a pas relevés s'écrivent « — », pas « aucun ». Le débit ne porte une flèche
(`SF7 → SF9`) que si le serveur a commandé un changement **et** que le terminal l'a appliqué ;
sinon il recopierait le réglage de départ en laissant croire à une décision du réseau.

### « Celui du run » nomme enfin de quel matériel il s'agit

Un capteur peut porter son propre modèle de matériel, ou dire « celui du run ». La seconde
option ne valait que si le run **avait** un profil — et l'atelier le proposait sans jamais
dire lequel. Choisir entre deux matériels qui diffèrent de 10 % de courant moyen, sans savoir
lequel on aura, n'est pas choisir.

**Mesuré d'abord, plutôt que cru.** La dette était notée « `_simulate` ne transmet aucun
`energy_profile` au run créé depuis l'atelier ». Elle n'existe pas : `compile_session` écrit
le profil du run dans le corps, `scenario.py` porte le modèle propre du groupe jusqu'au
dispositif, et le modèle de l'équipement prime sur celui du run. Cinq tests le prouvent, et
chacun a été vérifié discriminant par mutation : retirer le profil du corps en fait échouer
deux, retirer celui du groupe en fait échouer deux autres.

Ce qui manquait vraiment : **le moteur n'exposait pas ce défaut**. `GET /energy-profiles`
publie désormais `default`, et l'atelier l'écrit sous le sélecteur — à l'ajout d'un capteur
comme dans sa fenêtre — au lieu de le recopier, ce qui l'aurait laissé dériver. Un test lie
les deux : le défaut annoncé par le catalogue est celui que le corps compilé écrit.

### Les runs d'un chantier — revoir une simulation au lieu de n'avoir que la dernière

Comparer deux réglages suppose de revoir le premier. Or l'atelier ne connaissait que le
dernier run : les autres n'étaient atteignables que par leur identifiant, et un run qu'on
n'avait pas noté était un run perdu.

Nouvel onglet **Runs** dans le panneau d'observation, servi par `GET /sessions/{id}/runs` :
graine, date, état, trames reçues, PDR et attente des descentes, du plus récent au plus
ancien. Un clic rouvre un run — ses chiffres, son plan et son journal remplacent ceux de
l'écran, et le chantier ne bouge pas : le run n'est **pas** relié à nouveau (`bind` sert à
noter un exercice sur l'état courant, pas à regarder un résultat passé).

**Un run non terminé ne publie aucun chiffre.** Pas de mesure ne veut pas dire mesure nulle :
ses colonnes restent vides plutôt qu'à zéro, et « 0 reçu » ne se lit pas comme un résultat.
Même règle pour l'attente des descentes, absente d'un run qui n'en a pas planifié.

**Comparer, pas seulement revoir.** Chaque ligne porte un bouton « Comparer » qui met le run
choisi face au run affiché : taux de réception, trames reçues, attente des descentes, avec
l'écart lu de l'un vers l'autre. Seules les grandeurs **mesurées par les deux** runs sont
comparées — un écart calculé contre une case vide inventerait une différence, l'attente des
descentes ne se comparant qu'entre deux runs qui en ont planifié.

**L'historique est celui du chantier, pas du stockage.** Le chantier rattache ses 16 derniers
runs (`MAX_COMPILED`) ; un run évincé est sauté sans faire échouer la liste, et un run plus
ancien n'est pas effacé — il cesse d'être rattaché, et reste consultable par son identifiant.
Chaque entrée porte les liaisons équipement ↔ passerelle du run, sans lesquelles le revoir
afficherait des équipements sans jamais dire qui a entendu qui.

### U0.5 — Convergence du point fixe : budget de réémissions cumulé

Septième jalon de la refonte U0. Il traite le défaut laissé ouvert par U0.4-bis : **quatre
configurations denses qui oscillaient au lieu de converger**. Périmètre : la convergence
seulement ; ni `DECALE`, ni A6, ni les règles MAC, ni l'ABI, ni le budget réglementaire
descendant ne sont touchés.

**Le défaut.** Le budget de réémissions portait sur le **rang courant** de l'essai
(`attempt.attempt >= budget`). Or `_prune_acknowledged` est appelée à l'intérieur de la
boucle de point fixe : elle supprime, à chaque itération, les réémissions qu'un ACK reçu
avant leur départ rend impossibles. Supprimer un essai postérieur fait **redescendre** le
dernier essai de la trame vers un rang antérieur, ce qui **rouvre le budget**. Comme
l'ensemble des ACK reçus oscille avec l'occupation — l'inconnue même du point fixe — le
budget était rouvert indéfiniment. Mesuré sur le cas étalon : **75 rembobinages sur
18 passes**, et aucune borne sur le nombre total d'émissions d'une trame.

Ce défaut est **antérieur à U0.4-bis** : il était masqué par la sortie prématurée que
U0.4-bis a supprimée. Deux des quatre configurations convergeaient en **une seule passe**,
sans jamais avoir rejoué la trace sous l'occupation qu'elles venaient de produire.

**La correction.** Le budget est désormais compté **cumulativement** (`emis`), et ne décroît
jamais : une trame est émise au plus `1 + retries` fois, comme le veut la politique de
réémission. L'élagage reste dans la boucle — le déplacer après la boucle, variante mesurée
et écartée, laisserait des réémissions fantômes occuper la radio et bloquer des
transmissions réelles.

**Corrections physiques — résultats qui changent, et pourquoi ils devaient changer.**
Trois des quatre configurations denses convergent désormais, au lieu de lever une erreur.
Sur les 400 configurations de l'audit, **8** voient leur résultat modifié
(86, 117, 125, 189, 240, 288, 319, 365), d'au plus 4 transmissions et 4 trames livrées.
Agrégats : 14 transmissions en moins, 2 montantes reçues en moins, 11 pertes d'occupation
passerelle en moins, 6 trames livrées en moins. Aucune violation du demi-duplex n'apparaît :
le test de balayage reste à zéro sur les 400.

**⚠ Diagnostic erroné, rectifié en U0.5-bis.** Ce jalon laissait une configuration
(11 terminaux, période 15 s, `retries=3`) lever une erreur, décrite ici comme « un cycle de
période 3 … qu'aucune correction numérique ne résout ». **Cette analyse était fausse**, et
l'est restée faute d'avoir cherché plus loin que la garde qui la produisait. L'observation
de départ était juste — seules 9 trames sur 62 atteignent le budget, trajectoire identique
avec ou sans budget cumulé — mais la conclusion ne l'était pas : la configuration **converge**
en 22 passes vers un point fixe cohérent (192 intervalles imposés = produits, aucune
violation). La « période 3 » était un artefact : la garde comparait le **calendrier seul**,
et le calendrier de 109 tentatives revient aux passes 3 et 7 **sous des occupations
différentes** (195 puis 228 intervalles). Aucun état complet ne se répétait. Voir U0.5-bis.
Taux d'oscillation sur 1 500 configurations denses : 0,33 % avant, **0,20 %** après.

**Homonymie levée.** Il existait deux constantes `MAX_ITERATIONS` indépendantes — 128 dans
`retransmissions` (point fixe des réémissions), 64 dans `trace_events` (deux boucles :
jointures, et montantes ↔ descentes). Aucun import croisé, points fixes non imbriqués.
Elles s'appellent désormais `MAX_ITERATIONS_REEMISSIONS` et `MAX_ITERATIONS_TRACE`.
*Rupture pour d'éventuels importateurs directs* : ni l'une ni l'autre ne figure dans
`lsim.__all__`.

**Comparaison canonique partagée.** `trace_events` comparait les occupations par égalité de
listes brutes, ce qui n'était correct que parce que `GatewayArbiter.occupation` se trouve
être triée chronologiquement — une propriété d'implémentation, qu'aucun test ne verrouillait.
La comparaison et la signature de détection de cycle passent par la forme canonique, comme
dans `retransmissions`. Un test fige désormais l'ordre de l'arbitre.

**Filet physique extrait et testé.** Le filet qui lève plutôt que de rendre une trace
impossible est **inatteignable depuis la boucle** : celle-ci ne sort que lorsque l'occupation
produite égale l'occupation imposée, et la trace a été jouée sous cette même occupation.
Mesuré : 0 déclenchement sur les 400 configurations. Il est donc extrait en
`_verifier_coherence_occupation` et testé directement — la mutation qui le neutralisait
n'était détectée par aucune suite boîte noire.

**Non traité ici** : le colmatage préventif des trois sites créant un arbitre isolé
(`ack_mac.py:356`, `join.py:557`, `join.py:566`) — aucun n'est atteint par
`simulate_confirmed_uplinks`, ses appelants de production passant toujours un arbitre ;
l'oscillation structurelle décrite plus haut, qui relève d'une décision de modèle.

### U0.5-bis — Détection d'état répété sur la paire (calendrier, occupation)

Huitième jalon de la refonte U0. Il corrige un **faux diagnostic** porté par U0.5 et la
garde qui l'avait produit. Périmètre strict : la détection des états répétés. Ni `DECALE`,
ni A6, ni les règles MAC, ni l'ABI, ni le budget réglementaire descendant ne sont touchés ;
le budget cumulé de réémissions et l'élagage dans la boucle sont **conservés**.

**Le défaut.** La garde de détection des états répétés comparait le **calendrier seul** :

```python
signature = tuple((a.device, a.session, a.frame, a.attempt, a.start_ns) for a in schedule)
```

Or l'état du système est la **paire** (calendrier, occupation imposée). Un même calendrier
peut revenir sous une occupation différente : ce n'est pas un cycle, seulement la répétition
d'une projection incomplète de l'état.

**Conséquence mesurée.** L'essai 334 — 11 terminaux, période 15 s, `retries=3` — était
déclaré oscillant de période 3 et rejeté. En réalité :

- le calendrier de 109 tentatives revient aux passes 3 et 7, sous des occupations imposées
  de **195** puis **228** intervalles ;
- **aucun état complet ne se répète** sur les 22 passes de la trajectoire ;
- l'occupation converge par oscillation amortie : 156 → 204 → 174 → 192 → 174 → 213 → 168 →
  195 → 180 → 189 → 180 → 198 → 186 → **192** ;
- le point fixe est atteint à la 22ᵉ passe : 192 intervalles imposés = produits, 64 montantes
  reçues, **0 violation** du demi-duplex, résultat identique sur trois exécutions.

La garde interrompait donc une convergence en cours, et U0.5 en avait fait une « limite
connue » au lieu d'y voir son propre défaut.

**Pourquoi le budget cumulé ne pouvait pas y suffire.** Au moment du faux positif, seules
**9 trames sur 62** atteignent le budget, et ce compte est **constant** d'un état à l'autre
(9/9/9). Les trames qui saturent le budget ne sont pas celles qui alternent : 16 trames
oscillent entre les rangs 0 et 1, en deux groupes en antiphase (terminaux 0, 2, 9, 10 contre
terminal 3 ; terminaux 4 et 8 sur une autre phase). Borner le cumul plafonne la taille du
calendrier, il ne stabilise pas l'alternance des ACK — ce qui explique que U0.5 ait résolu
les essais 11, 61 et 318, mais pas celui-ci.

**La correction.** La signature porte désormais sur l'état complet, occupation sous forme
canonique :

```python
signature = (tuple((a.device, a.session, a.frame, a.attempt, a.start_ns)
                   for a in schedule), _canonique(occupation_imposee))
```

**Corrections physiques — résultats qui changent, et pourquoi ils devaient changer.**
Une configuration passe de « erreur explicite » à « résultat rendu » : l'essai 334 fournit
désormais 111 transmissions, 64 montantes reçues, 59 trames livrées et 41 pertes
d'occupation passerelle. Ce n'est pas une non-régression : c'est une configuration que le
simulateur **refusait à tort**. Sur le balayage de référence à 400 configurations, **0
modification** — compteurs identiques au bit près, nombre total de passes identique (1698).
Sur 1 500 scénarios denses : **0 oscillation** (contre 3), soit 0,00 % contre 0,20 %.

**Limite empirique de la borne d'itérations — à ne pas lire comme une garantie.** Depuis que
la détection porte sur la paire (calendrier, occupation), la borne **théorique** d'atteinte
du plafond est beaucoup plus grande : l'espace d'états est fini — le budget cumulé borne le
calendrier, l'occupation en découle — mais vaste. Mesuré : **74 passes au plus** sur 1 500
scénarios denses, 23 sur les 400 de référence, **aucune configuration au plafond**. La marge
n'est que de **1,7 ×** et n'a **pas** été éprouvée au-delà de 16 terminaux. Le plafond de 128
reste un filet empirique, non une borne démontrée : il **lève** explicitement
(`pas de point fixe des réémissions après … itérations`) et ne rend jamais silencieusement
un résultat faux. Les gardes d'oscillation du calendrier et de l'occupation, ainsi que le
filet de cohérence physique, demeurent actifs.

**Non traité ici** : le colmatage préventif des trois sites créant un arbitre isolé
(`ack_mac.py:356`, `join.py:557`, `join.py:566`) — aucun n'est atteint par
`simulate_confirmed_uplinks` ; toute autre refonte de la convergence.

### U0.4-bis — Convergence de l'occupation radio sur le chemin MAC

Sixième jalon de la refonte U0. Il corrige un contournement du demi-duplex **révélé par
l'audit** des chemins ACK, Join-Accept et réémissions, et non par une erreur de placement.

**Le défaut.** Le point fixe des réémissions (`_simulate_confirmed`) sortait dès qu'aucune
réémission nouvelle n'était nécessaire, sans vérifier que l'occupation produite était celle
qui avait servi à calculer la trace. Le plan pouvait donc contenir une descente chevauchant
une montante comptée comme reçue : **un émetteur demi-duplex émettant pendant qu'il reçoit**.
Mesuré avant correction : 95 configurations sur 400, 708 intervalles fautifs.

**La correction.** La sortie exige désormais la stabilité du calendrier **et** de l'occupation.
S'y ajoutent une comparaison canonique (triée, dédupliquée), une garde d'oscillation de
l'occupation, un budget porté de 32 à 128 itérations (75 mesurées au plus sur 500 scénarios
denses), et un filet qui **lève** plutôt que de rendre une trace physiquement impossible.
L'arbitre n'est pas amorcé avec l'occupation précédente : il la redérive depuis un émetteur
libre, faute de quoi la même émission serait comptée deux fois.

**Corrections physiques — résultats qui changent, et pourquoi ils devaient changer.**
Sur les 400 configurations de l'audit, 103 voient leur résultat modifié, **toutes** sur le
chemin MAC ; le chemin causal est strictement inchangé. Agrégats sur les 365 configurations
MAC : 708 violations supprimées, 586 pertes d'occupation passerelle supplémentaires, 102
montantes reçues en moins, 488 réémissions en plus, 7 trames livrées en moins. Ces écarts ne
sont pas des régressions : les configurations concernées renvoyaient une trace que le matériel
ne pourrait pas produire. Les configurations déjà cohérentes — dont tous les scénarios
historiques à 5 terminaux testés — sont inchangées.

**Non-convergence assumée.** Sur 500 scénarios denses, 4 configurations oscillent
(occupation mesurée : 84, 50, 96, 64, 94, 72, 72, 76, 70, 84… sans jamais se stabiliser) et
lèvent désormais une erreur explicite. Ces 4 renvoyaient auparavant un résultat comptant
22, 148, 37 et 24 violations : le code refuse maintenant de les rendre.

**Non traité ici** : `DECALE` et A6 inchangés, aucune règle MAC modifiée, ABI intacte, budget
réglementaire descendant toujours désactivé, chemin multi-passerelles non migré.

### U0.4 — Occupation radio : source unique et cohérence du demi-duplex

Cinquième jalon de la refonte U0. Le moteur causal n'entretient plus de copie locale de
l'occupation : le demi-duplex interroge l'ordonnanceur radio **qui a décidé le placement**.

**Ce qui change.** Le chemin causal maintenait un `std::vector<Interval> planned`, alimenté par les
valeurs de retour de `DownlinkScheduler::on_received()`. Le placement décidait sur l'état de
l'ordonnanceur, le demi-duplex lisait la copie : deux états pour une même réalité, et aucun
contrôle de leur égalité. `DownlinkScheduler` expose désormais `occupancy()` — l'occupation de
l'ordonnanceur radio, sans liste parallèle — et `transmitting()`, le **même** test que le
placement. `busy_out` en est **dérivé**, et non reconstitué au fil des appels.

**Ce qui ne change pas.** Comportement bit à bit identique : empreintes gelées
`d2cb0fac…` / `ed126d7f…` invariantes, les neuf scènes de la sonde d'occupation gardent leurs
comptes, durées et empreintes, et l'égalité moteur/planificateur reste acquise sur les neuf.

**Garanties épinglées par les tests.** Une émission acceptée réserve exactement
`[ouverture, ouverture + temps d'antenne)` ; une émission refusée n'en réserve aucune ; deux
émissions disjointes sont toutes deux possibles ; une occupation s'achevant exactement à
l'instant de disponibilité suivant ne provoque pas de faux conflit ; ACK, Join-Accept et
réémission passent par un émetteur unique et ne peuvent pas émettre par-dessus une émission
déjà acceptée.

**Non traité ici** (limites du mandat) : migration du multi-passerelles, budget réglementaire
descendant, retrait de `GatewayArbiter` — ses responsabilités ne sont pas toutes identifiées.

### U0.3 — Placement temporel A6 : un ordonnanceur radio commun

Quatrième jalon de la refonte U0. Le `RadioScheduler` devient la référence commune de placement
des descentes, dans le **chemin causal** comme dans le **planificateur**.

**Règle (arbitrage A6, TS001-1.0.4 §3.3.5).** Une descente part **exactement** à l'ouverture de
RX1 ou de RX2, ou n'est pas émise. Aucun décalage intra-fenêtre : si l'émetteur émet encore à
l'ouverture, la fenêtre est manquée **sans occupation fictive**.

- `RadioScheduler::place_at` : nouvelle entrée pour le planificateur, qui examine une fenêtre à
  la fois et garde l'ordonnancement (l'ordre d'examen, le report de la RX2 à sa propre
  ouverture). La **règle** reste entièrement dans le composant radio.
- `DownlinkScheduler::placer` (chemin causal) et `_schedule_gateway` (planificateur par lot)
  délèguent tous deux à `place_at` : plus aucune logique concurrente, plus de
  `any_busy` / `busy_until` dupliqués. L'occupation publiée est reprise telle quelle de
  l'ordonnanceur.
- `lsim.arbitre.GatewayArbiter` : nouvelle règle `EXACTE` (A6), activée pour la descente de
  données. Les Join-Accept, ACK MAC et réémissions restent sur `DECALE` — chemins disjoints et
  documentés, migration hors jalon.
- `lsim::radio::Interval` et `SimTime` sont désormais définis par `radio_scheduler.hpp`, sans
  dépendance : `engine.hpp` et `downlink_plan.hpp` les réutilisent (dispositions identiques,
  aucune conversion).

**Conséquences assumées.** Le repli RX2, implémenté mais qui ne se déclenchait jamais, devient
effectif. Les scènes de contention perdent des descentes que l'ancienne règle émettait **après**
l'ouverture de la fenêtre. Les scènes sans descente et sans contention sont strictement
inchangées : empreintes gelées `d2cb0fac…` / `ed126d7f…` invariantes, vecteurs de déterminisme
`65ce329f…` bit à bit identiques, performance 1,00 × la référence.

Détail complet, tableau des différences et preuves : `docs/PLACEMENT_TEMPOREL_A6.md`.

### D3.15 / I3 — Repli RX2 : exposition, sensibilité de la fenêtre émise, cohérence des moteurs

Troisième jalon, découpé en quatre incréments. Il traite les deux défauts classés Haute et le
préalable que leur correction a révélé.

#### C3 — Placement différé de la RX2 (préalable)

`DownlinkScheduler::on_received` plaçait la fenêtre de secours **immédiatement**, alors que
`plan_downlinks` la met dans un tas à son propre instant d'ouverture. Dès que deux montantes
finissent à moins d'une seconde d'écart, les deux moteurs divergaient — et le contrôle
d'égalité de `trace_events` (`occupation passerelle incohérente`) est bloquant. Activer le repli
par défaut sans corriger cela aurait cassé les scénarios réels.

- `on_received` renvoie désormais `std::vector<Interval>` et ne place que ce qui est certain de
  ne plus pouvoir être devancé : frontière = ouverture de la RX1 de la montante courante.
- `drain()` purge ce qui reste en attente à la fin de la trace, faute de quoi la dernière RX2
  différée n'était jamais émise.

#### C4 — Sensibilité évaluée dans la fenêtre réellement émise

Une descente repliée en RX2 était seuillée avec la sensibilité de **RX1**. Au SF12BW125 le
récepteur entend 13 dB plus bas qu'au SF7BW125 : la descente était déclarée perdue alors que le
dispositif l'entendait. **Les deux moteurs commettaient l'erreur à l'identique, la parité ne la
voyait pas.** Corrigé dans `downlink_plan.cpp` et dans `trace_events.py`, et épinglé dans chacun
séparément.

#### C1/C2 — La table RX2 atteint enfin les appelants

Les profils régionaux exposent RX2 depuis toujours, et `device_radios` remplit déjà
`DeviceRadio.rx2_*`. Le chaînon manquant était dans l'appelant :

- aucune entrée causale n'acceptait la table ⇒ le moteur causal n'avait aucune fenêtre de
  secours, alors que le planificateur par lot en avait une. Nouvelles entrées
  `lsim_simulate_uplinks_causal_v3` / `..._gw2_v3`, qui réunissent la table RX2 **et** les
  frontaux (sans aucune des deux extensions, l'entrée v1 reste appelée : base inchangée) ;
- `trace_events` et `retransmissions` appelaient `plan_native` (v1). Ils appellent désormais
  `plan_native_v2` avec la table, et la passent aussi à `simulate_causal` ;
- `ProtocolOptions.rx2_fallback` passe à **`True`** par défaut, comme le repli du Join-Accept.

**Sans région déclarée, `rx2_hz == 0` et le repli reste inerte** : les scénarios historiques et
les empreintes gelées sont intacts (aucun scénario de référence ne déclare de région).

#### C6/C7 — Multi-régions et coût

Sept profils exercés (EU868, US915, AS923, AU915, IN865, KR920, RU864) ; un garde-fou exige
qu'au moins un soit en SF10, un en BW500 et un en SF12BW125. Le coût du repli est mesuré : au
SF12BW125, la même trame occupe l'émetteur environ 20× plus longtemps qu'au SF7BW125.

### D3.15 / I1 — Repli RX2 dans le planificateur natif

Le cœur C++ implémente le repli vers la seconde fenêtre de réception, ce qui **supprime la
divergence** documentée en I2 (écart D1 de l'audit). Python et C++ produisent désormais les mêmes
décisions sur un scénario qui exerce réellement le repli.

- **Opt-in.** `lsim::plan::PlanOptions::rx2_fallback`. Ce n'est **pas** un champ de
  `lsim_plan_options` : la structure ABI reste inchangée. Côté C, fournir une table RX2 à
  `lsim_plan_downlinks_v2` active le repli ; la v1 et la v2 sans table ne le font jamais.
- **Même condition qu'en Python** : le repli n'opère que si `rx2_sf != 0` **et** `rx2_hz != 0`.
- **File chronologique.** La boucle de placement devient un **tas** : la fenêtre de secours naît de
  l'échec de la RX1 et porte sa propre ouverture (`t_open + 1 s`), qui peut être postérieure à
  celle d'autres descentes. La traiter au même endroit que la RX1 placerait la descente trop tôt.
  C'est l'alignement sur le tas de `GatewayArbiter` (`ready_ns`, puis ticket croissant), qui
  départage à ouverture égale en faveur de la RX1. Sans table RX2, l'ancien tri stable est
  conservé : résultat identique à l'octet près.
- **Paramètres effectifs** : ouverture à `RECEIVE_DELAY2` (2 s après la fin de la montante),
  fenêtre de 1 s, fréquence `rx2_hz`, temps d'antenne calculé au SF et à la largeur de RX2
  (largeur nulle ⇒ reprise de `rx1_bw_hz`). L'occupation réservée est la durée réelle.
- **Une seule émission par descente** : la RX2 n'est enfichée que sur l'échec de la RX1, et la
  réaction ne redemande rien. Aucun doublon.
- **Événements** : le saut descendant porte la fréquence de la fenêtre réellement émise, et
  l'indicateur « dispositif en émission » est évalué sur cette fenêtre (RX2 s'ouvre une seconde
  plus tard : une montante courte ne la masque pas forcément).
- **Planificateur incrémental** : `DownlinkScheduler::on_received` applique la même règle.

**Limitation de fidélité, commune aux deux moteurs, non masquée** : la sensibilité du récepteur
utilisée pour décider si la descente est reçue reste celle du débit **RX1**, même pour une
descente émise en RX2. Une trame RX2 au SF12 est en réalité reçue avec la sensibilité SF12, bien
meilleure. Corriger cela change les résultats des deux côtés ; c'est un travail de fidélité radio,
pas de parité.

**Vérifications** : C++ 685 905/685 905 (dont 31 nouvelles) ; suite Python complète et parité
(114) rejouées ; ABI **inchangée** (55 / 477, i386) ; **98 symboles, +0 / −0** par rapport à I2 ;
empreintes `d2cb0fac…` et `ed126d7f…` inchangées. Le `xfail(strict=True)` d'I2 est devenu une
parité stricte, et un nouveau test vérifie que la v2 avec table **diffère** de la v1 (le repli
natif est réel, pas déclaratif).

### D3.15 / I0 — Enveloppe ABI versionnée du planificateur de descentes

Premier jalon de la refonte descendante. **Capacitaire :** l'extension transporte et valide les
paramètres de la seconde fenêtre de réception (RX2) **sans modifier ni le placement ni le temps
d'antenne**. Le repli RX2 reste **opt-in** et son implémentation est reportée à un jalon ultérieur.

- **`lsim_plan_downlinks_v2`** (nouveau symbole) : enveloppe `lsim_plan_downlinks_v2_args`
  versionnée (`struct_size`, `abi_version`), qui reprend les entrées de la v1 et ajoute
  `lsim_plan_device_rx2` — `rx2_hz`, `rx2_sf`, `rx2_bw_hz` — plus `rx2_count`. Les champs
  `reserved` permettent une extension ultérieure sans rupture.
- **`lsim_plan_downlinks_v1` inchangée.** Sa déclaration publique est identique au caractère près ;
  son corps est déplacé tel quel dans une fonction commune, appelée avec `rx2 = nullptr`. Les
  anciens appels conservent exactement leur comportement — vérifié par la parité bit à bit
  (C++ et Python), les 114 tests de `test_downlink_plan_parity.py` et les empreintes gelées.
- **`sizeof(lsim_plan_device)` inchangé** (40 o en x86-64, 36 o en i386). La structure n'est pas
  étendue en place : elle n'a aucun octet libre.
- **Sûreté de la frontière C.** `args` nul, `struct_size` erroné, `abi_version` inconnue, pointeurs
  obligatoires nuls et comptages incohérents sont refusés sans accéder à la mémoire. `rx2_count`
  existe précisément parce qu'un pointeur seul ne dit pas sa longueur : sans lui, le cœur aurait lu
  `device_count` entrées quelle que soit la taille réelle du tableau.
- **C++ (`lsim::plan`)** : `DeviceRx2` ; surcharge `plan_downlinks(..., rx2, ...)` ; surcharge du
  constructeur de `DownlinkScheduler` et surcharge `on_received(device, end_ns, rx2)` (arbitrage
  C2). Les signatures d'origine sont conservées et délèguent avec « aucun RX2 ».
- **Validation RX2** : `rx2_sf` nul = aucun repli ; sinon 7..12. `rx2_bw_hz` nul = reprend
  `rx1_bw_hz` ; sinon 125, 250 ou 500 kHz. `rx2_hz` nul = non renseigné ; valeur négative refusée.
- **Python** : `plan_native_v2` et `DeviceRx2` dans `lsim.downlink_plan`. `plan_native` est
  désormais un appel de `plan_native_v2` sans RX2.
- **`docs/DOWNLINK_PLAN_ABI_V2.md`** : contrat de l'enveloppe.

**Vérifications** : C++ 685 874/685 874 (dont 592 nouvelles), Python 2 103 tests (dont 31
nouveaux), harnais ABI 55 structures / 477 grandeurs en x86-64 et compilation i386, 98 symboles
`lsim_*` (**+1**, aucun retiré), empreintes `d2cb0fac…` et `ed126d7f…` inchangées.

**Non couvert, reporté** : le repli RX2 lui-même (changera le placement) ; l'exposition de la
fréquence RX2 par module régional (arbitrage S1) — aucun appelant ne peut donc aujourd'hui
renseigner `rx2_hz` correctement.

### D3.15 / I2 — Repli RX2 dans l'oracle Python

Le repli vers la seconde fenêtre de réception est implémenté dans la planification descendante
Python (`trace_events._schedule_gateway`). RX1 reste prioritaire : RX2 n'est demandée que par la
réaction d'une RX1 **non émise**, jamais à côté ni en double.

- **Opt-in.** `ProtocolOptions.rx2_fallback`, `False` par défaut : à `False`, la file de
  l'émetteur ne contient que des demandes RX1, exactement comme avant I2.
- **Conditionné à une fenêtre réellement renseignée.** Le repli n'opère que si `rx2_sf != 0`
  (il y a une fenêtre) **et** `rx2_hz != 0` (il y a une fréquence). Sans fréquence régionale —
  cas de tous les scénarios sans `region:` — le repli est **inerte par construction**, ce qui
  préserve les empreintes gelées.
- **Paramètres effectifs.** Une descente repliée porte la fréquence, le SF et la bande passante
  de RX2, donc un temps d'antenne **différent** : au SF12 BW125 (défaut EU868, RP002-1.0.5), la
  même trame occupe l'émetteur une vingtaine de fois plus longtemps qu'au SF7. C'est cette durée
  qui est réservée, pas celle de RX1.
- **Validation ajoutée**, bornes identiques à `valid_rx2()` du cœur : `rx2_sf` dans 7..12 (0 =
  aucun repli), `rx2_bw_hz` dans {125k, 250k, 500k} (0 = reprend `rx1_bw_hz`), `rx2_hz` non
  négatif. Hors opt-in, rien n'est validé ni lu.
- **Aucun doublon** : une seule émission acceptée par descente ; la réaction RX2 ne redemande
  rien.

**Divergence identifiée, non masquée.** Le planificateur natif n'implémente **aucun** repli RX2
(écart D1 de l'audit). La parité Python/natif est donc exigée et vérifiée sur RX1, sur le repli
désactivé et sur l'absence de fréquence régionale — où les deux moteurs se rejoignent — mais
**pas** sur un repli effectif, qui n'a pas d'équivalent natif. Ce cas est épinglé par un
`xfail(strict=True)` et par un test qui démontre positivement l'écart
(`test_le_coeur_ne_replie_pas_et_le_dit`). Tant que le cœur ne replie pas, toute comparaison
« parité avec repli » serait fausse.

**Conséquence mesurée, assumée** : en saturation, le repli **réduit** le nombre de descentes qui
aboutissent. Une RX2 au SF12 bloque l'émetteur plusieurs secondes, et empêche des RX1 suivantes
de se placer. Ce n'est pas un défaut de placement : c'est le coût radio réel du débit de repli
EU868. Le test `test_le_repli_coute_l_emetteur_et_peut_reduire_le_total` épingle cet effet.

**Vérifications** : 25 nouveaux tests (`python/tests/test_downlink_plan_rx2.py`) ; suite Python
complète rejouée ; C++, ABI (55 / 477, i386) et symboles (98, +1) inchangés ; empreintes
`d2cb0fac…` et `ed126d7f…` inchangées — le champ `rx2_fallback` est délibérément exclu du `repr`
de `ProtocolOptions`, dont la chaîne sert de clé au dépôt figé : l'y faire apparaître aurait
changé l'empreinte sans changer un seul événement.

### D3.13 — Arbitrage radio partagé : un émetteur, un budget, une seule source de vérité
- **`python/lsim/arbitre.py` (nouveau)** : `GatewayArbiter` et `DutyCycleLedger` remplacent trois
  occupations passerelle indépendantes — `busy_until` local de `trace_events._schedule_gateway`,
  `busy_until` local de `ack_mac.plan_acks`, et **aucune** pour `join._evaluer`. Une seule ressource,
  une seule règle, une seule trace d'occupation.
- **Règles d'arbitrage** : (1) un seul émetteur ; (2) file monotone `début = max(instant_prêt,
  occupé_jusqu'à)` — la règle historique du cœur, au bit près ; (3) ordre chronologique évalué en
  **file d'événements**, une demande née du placement d'une autre (RX2 après RX1) entrant à son propre
  instant ; (4) **aucune priorité inventée** : LoRaWAN ne définit pas d'ordre entre un Join-Accept et
  l'ACK d'un autre terminal, `ArbitrationPolicy.priority` est vide et l'ordre est celui du dépôt ;
  (5) une émission hors fenêtre **n'a pas lieu** (`window_missed`, aucune occupation), sauf
  `allow_late` explicite — c'est l'ACK tardif, qui occupe sans être écouté.
- **Le Join-Accept occupe l'émetteur et lui est opposé.** Mesuré, `retransmissions_ack_tardif`,
  trames de 51 octets en SF12, `join_requests_s: [10]`, `retries: 2`, `ack_delay_ms: 12000` :

  | copies d'ACK | avant D3.13 | après D3.13 |
  |---|---|---|
  | 1 | RX1 `delivered`, session 1 | RX1 `delivered`, session 1 |
  | 2 | RX1 `delivered`, session 1 | RX1 `gateway_busy`, **RX2 `delivered`**, session 1 |
  | 3 | RX1 `delivered`, session 1 | RX1 `gateway_busy`, RX2 `gateway_busy`, **session 0** |

  Dans l'autre sens, `ack_delay_ms: 12800` place un ACK à 15,288 s pendant l'émission du Join-Accept
  (15,206 → 15,453 s) : l'ACK part à 15,453 s, alors qu'il partait à 15,288 s avant. L'occupation
  passerelle contient désormais les Join-Accept, et elle est réinjectée au moteur au tour suivant :
  une trame montante qui chevauche une descente est perdue.
- **RX2 peut être retardée par l'émission de RX1.** Mesuré en SF12, où un Join-Accept de 33 octets
  occupe l'émetteur 1,81 s : RX2 passe de 63,483 s à 64,293 s (fin de l'émission de RX1), tout en
  restant dans sa fenêtre. La correction D3.12 est intacte — RX2 reste un **secours**, jamais une
  seconde copie — mais elle s'ajoute à la file au lieu d'être posée à un instant fixe.
- **Le Join-Request consomme le rapport cyclique du terminal** (`DutyCycleLedger`, budget
  `airtime cumulé + airtime <= rapport × instant`, la règle déjà utilisée pour les réémissions).
  Une tentative refusée n'entre **pas** dans le moteur : aucune collision provoquée, aucun temps
  d'antenne consommé, aucun compteur `sent`. Mesuré avec `duty_cycle: 0.001`, `join_retries: 2` :
  2 refus, 0 Join-Accept émis, 0 session, et une trace qui porte `join_request / suppressed` au lieu
  de `join_request / received`. `enforce_duty_cycle: false` rend le budget inopérant.
- **Nouveaux compteurs** : `RetransmissionResult.joins_blocked_by_duty_cycle`,
  `.join_accepts_emitted` ; `JoinResult.blocked_by_duty_cycle` ; `AcceptEmission.emitted` ;
  `JoinAttempt.emitted`. Issue `gateway_busy` sur une émission de Join-Accept dont la fenêtre est
  couverte — c'est un fait de réseau tracé, pas une transmission.
- **Chemin d'exécution** : dès qu'une jointure radio est déclarée, les descentes passent par le
  planificateur Python (`lsim.ack_mac`, `AckTiming()` nominal) au lieu de celui du cœur : c'est le
  seul moyen de faire partager un émetteur unique sans modifier l'ABI. **Sans jointure radio, rien ne
  change** : le cœur garde la main et la parité avec l'oracle Python reste exigée
  (`test_downlink_plan_parity.py`, 124 tests).
- **Tests** : `python/tests/test_arbitre_radio.py`, **25 tests** (portés à 34 par la validation
  finale) — concurrence reproductible
  (Join-Accept et ACK au même instant, ACK en émission quand RX1 s'ouvre, RX1 impossible puis RX2
  possible, RX1 réussie sans RX2, descentes concurrentes, deux jointures qui se chevauchent,
  émission bloquée non tracée comme réussie, session seulement après réception effective), plus un
  scénario de bout en bout combinant jointure, ACK et downlink de données sur une passerelle.
- **Mesures inchangées, vérifiées** : scénarios de référence des retransmissions **8/24 → 7/24 → 5/24**
  (24/43/83 transmises, 11/15/20 reçues, 8/7/5 livrées, 0/1/8 doublons, 6/16/31 collisions,
  occupation 0,296 / 0,440 / 0,543) ; chemin historique `join=True` avec `downlink_every` ; aucune
  clé de scénario nouvelle, donc **les 30 schémas `schemas/api/v1` sont identiques**.
- **Invariants** : cœur C++ et **ABI intacts** (97 symboles `lsim_*`, aucune source C++ touchée),
  empreintes gelées `d2cb0fac…` / `ed126d7f…` inchangées, **685 282 / 685 282** vérifications C++,
  suite Python **1 977 tests** (1 952 + 25) — portée à 1 997 par la validation finale.
- **Limites** : rapport cyclique **descendant** non modélisé ; un seul émetteur par passerelle (pas de
  cartes radio multiples) ; durée d'ouverture des fenêtres (1 s) = hypothèse du simulateur ; la
  programmation causale du jeu de tentatives est **itérative et bornée** (8 tours, erreur explicite
  sur état répété). `docs/MAC_CONSOLIDATION.md` §10.

#### D3.13 — Validation finale : causalité du jeu de tentatives, fenêtres, rapport cyclique, chemins

La sonde anticipée qui figeait le jeu de tentatives **avant** le placement partagé est remplacée par
une **programmation causale** : une tentative n'est retirée du calendrier que si une jointure a été
**observée**, jamais sur une prévision.

- **`python/lsim/join.py`** : nouveau paramètre `succes_connu` de `simulate_joins`. Sur le chemin de
  l'arbitre partagé, la boucle de sonde disparaît : les tentatives postérieures à une jointure
  observée sont retirées, et **celles-là seulement**. Au premier tour rien n'est observé, donc toutes
  les tentatives sont jouées. `JoinResult.succes` expose les succès observés. Le chemin **sans**
  arbitre partagé garde sa boucle, qui y est causale puisque l'évaluateur y est le placement définitif.
- **`python/lsim/retransmissions.py`** : `simulate_confirmed_uplinks` itère sur `succes` jusqu'au point
  fixe (8 tours au plus). Un état qui se répète à l'identique lève `RuntimeError` plutôt que de rendre
  un résultat approximatif. En pratique : deux à trois tours.
- **Scénario de causalité, avant / après.** `join_retries: 2`, tentative à 10 s, seconde à 20 s ;
  `ack_repetitions: 3`, `ack_delay_ms: 12000`, SF12 — les ACK couvrent RX1 **et** RX2 :

  | | Tentatives | RX1 / RX2 de la 1re | Session | Join-Accept émis |
  |---|---|---|---|---|
  | avant (sonde) | 1 (10 s) | `gateway_busy` / `gateway_busy` | **0** | 0 |
  | après (causal) | **2** (10 s, 20 s) | `gateway_busy` / `gateway_busy`, puis `delivered` à 26,48 s | **1** | 1 |

  Avant, le terminal **ne joignait jamais** alors que rien ne l'en empêchait. Sans concurrence, une
  seule tentative est jouée : aucune tentative n'est émise après une jointure réussie.
- **Fenêtres : les sept cas exigés sont couverts et testés** — ACK occupant RX1 puis RX2 ; Join-Accept
  occupant l'émetteur quand un ACK est demandé ; plusieurs demandes au même instant ; demande retardée
  dépassant sa fenêtre ; **émission commençant dans la fenêtre et la dépassant** ; demande supprimée ne
  réservant pas l'émetteur ; **rejeu non confondu avec un nouvel Join-Accept**. La règle de départ est
  documentée dans `lsim.arbitre` : `début = max(instant_prêt, ouverture, occupé_jusqu'à)`, occupation
  de `début` à `début + temps d'antenne`, **sans garde ni temps de retournement**. Le verdict porte sur
  le **début** : une descente commencée dans la fenêtre est émise entière et occupe au-delà.
- **Rapport cyclique : le budget Join-Request est conservé**, jamais étendu. Vérifié : il s'applique à
  **toutes** les tentatives réelles du terminal (`join_retries: 3` ⇒ 3 refus, pas 1) ; une tentative
  refusée n'est **pas** enregistrée comme une émission (ni occupation, ni temps d'antenne, ni compteur
  `sent`, événement `suppressed`) ; isolation entre terminaux mesurée sur deux groupes (`0.001` et
  `1.0`) ; unités et fenêtre documentées — nanosecondes, budget **cumulatif depuis l'origine**, et non
  une fenêtre glissante. **Aucune limite réglementaire descendante n'est inventée** : contrainte non
  modélisée, signalée.
- **Chemins C++ et Python.** La bascule est `_native_plan_applies` : `not options.join and mac is None`.
  La raison est structurelle : `plan_native(records, radios, options)` ne reçoit que des enregistrements
  et **n'itère pas** (une seule exécution du moteur, contrôle d'égalité), alors qu'une demande de
  Join-Accept dépend du calendrier des tentatives de données **et** naît pendant la résolution (RX2,
  rejeu). Faire tenir cela dans `lsim_plan_downlinks_v1` changerait l'ABI gelée. Vérifié sans équivoque :
  sans concurrence pour l'émetteur, l'arbitre partagé reproduit le chemin isolé **à la nanoseconde**,
  sur les **500 tentatives** du scénario de référence. **97 symboles `lsim_*`, empreinte
  `0e546fa6391866d9…` : ABI et symboles exportés inchangés.**
- **Mesures de référence inchangées, remesurées après la correction** : 8/24 → 7/24 → 5/24
  (24/43/83 transmises, 11/15/20 reçues, 8/7/5 livrées, 0/1/8 doublons, 6/16/31 collisions,
  occupation 0,296 / 0,440 / 0,543) ; RX2 retardée par RX1 (62,483 → 64,293 s) ; ACK repoussé par le
  Join-Accept (15,206 → 15,453 s) ; chemin historique `join=True` avec `downlink_every` (3 familles de
  descentes, aucun chevauchement).
- **Tests** : `test_join_causalite.py` (**6**, le scénario exigé et les quatre propriétés),
  `test_arbitre_radio.py` (**34**, dont les sept cas de fenêtres et cinq de rapport cyclique),
  `test_chemins_cpp_python.py` (**5**, branche empruntée, justification, concordance). Suite Python :
  **1 997 tests** (1 977 + 20), 1 ignoré, aucun échec. **685 282 / 685 282** vérifications C++.
  Empreintes gelées `d2cb0fac…` / `ed126d7f…` inchangées.


### Jointure OTAA dans le moteur radio : Join-Request uplink, Join-Accept en RX1/RX2
- **`python/lsim/join.py`** : le Join-Request passe par le moteur causal comme une transmission de
  23 octets (temps de vol, collisions, sensibilité, couverture) ; le Join-Accept est une descente de
  33 octets émise en **RX1** (`JOIN_ACCEPT_DELAY1`, 5 s).
- **RX2 est une fenêtre de secours, pas une copie.** RX2 (`JOIN_ACCEPT_DELAY2`, 6 s) n'est émise que
  si RX1 n'a pas abouti ; si RX1 est reçue, aucune émission RX2 n'a lieu
  (`join_accept_rx2_fallback: false` la supprime entièrement). Le rejeu d'un Join-Accept est un
  mécanisme distinct (`join_accept_replays`) : le même message est réémis après acceptation, reçu
  puis refusé, et ne rouvre aucune session.
- **Une session n'est ouverte que si l'échange aboutit** : Join-Accept reçu dans une fenêtre,
  terminal à l'écoute, `JoinNonce` supérieur au dernier accepté. Un Join-Request perdu, une
  collision, RX1 et RX2 perdues ne remettent **aucun** compteur à zéro.
- **Scénario** : `join_requests_s` (instants des Join-Request), `join_retries` (1 à 3, 10 s entre
  deux essais), `join_accept_rx2_fallback`, `join_accept_replays` (0 à 2). Absents du hash à leur
  valeur par défaut ; exclusifs avec le modèle déclaré `session_joins_s`.
- **Trace** : `join_request` à l'instant réel avec l'issue du moteur ; un `join_accept` **par
  émission réellement faite** — un seul si RX1 aboutit, deux si RX2 sert de secours, plus un
  événement `suppressed` par rejeu reçu.
- **Mesures** : à 100 m, RX1 reçue et session ouverte (`FCntUp` 0 → 0) ; à 20 km, requête perdue,
  aucune session (`FCntUp` 0 puis 1) ; à 9 km avec récepteur dégradé, RX1 et RX2 perdues ; trame de
  51 octets en SF12 couvrant RX1, RX2 reçue à 63,48 s ; deux terminaux au même point, collision ;
  deux tentatives sur deux terminaux, une session par terminal ; rejeu, une seule session.
- **Limites** : aucune cryptographie (ni clé, ni `MIC`, ni chiffrement), Join-Accept non opposé à
  l'occupation de la passerelle, Join-Request non compté dans le rapport cyclique, pas de rejoint 1.1.
  `docs/MAC_CONSOLIDATION.md` §9.

### Cycle de vie des sessions : jointures déclarées, compteurs remis à zéro, trames périmées
- **`python/lsim/sessions.py`** : `SessionTimeline` ordonne les `Join-Accept` acceptés. Un `Join-Accept`
  rejoué (nonce non croissant, instant non postérieur) lève `JoinRejected` **sans** rien remettre à
  zéro ; une session ouverte porte un rang (1, 2, …) et une date.
- **Le scénario déclare les jointures** : `retransmissions.session_joins_s` (instants en secondes,
  strictement croissants, 16 au plus). Vide, il est absent du hash : les scénarios existants gardent
  leur empreinte. Lorsqu'il est déclaré, il produit des événements `join_request` /
  `join_accept` dans la trace, au vocabulaire déjà défini par le contrat — aucune valeur nouvelle.
- **Les compteurs repartent de zéro** : `FCntUp` et les deux séries descendantes sont numérotés par
  `(terminal, session)`. Mesuré sur trois trames et `session_joins_s: [0, 40]` :
  `(session 1, trame 0, FCntUp 0, FCntDown 0)`, `(session 2, trame 0, 0, 0)`, `(session 2, trame 1, 1, 1)`.
- **Les trames de l'ancienne session ne sont plus réémises** : la tentative prévue après la jointure
  est supprimée et comptée dans `RetransmissionResult.rejected_stale_session`. Mesuré sur le cas
  « ACK tardif » à deux messages, `retries: 2` : 6 transmissions sans jointure, **5** avec
  `session_joins_s: [5]`, deux tentatives périmées, 5 ACK au lieu de 6.
- **Tests** : `python/tests/test_mac_sessions.py` (9 tests), dont un qui vérifie que le hash ne change
  pas quand `session_joins_s` est vide et qu'il change dès qu'une jointure est déclarée.
- **Limites** : ni cryptographie ni `JoinNonce` réel (le nonce est un rang) ; le `Join-Request` n'est
  pas modélisé dans le moteur radio ; pas de rejoint 1.1. `docs/MAC_CONSOLIDATION.md` §8.

### Validation opérationnelle des compteurs : `AFCntDown`, sessions, interactions
- **`NFCntDown` et `AFCntDown` exercées de bout en bout.** `downlink_payload: true` fait porter une
  charge utile à la descente : elle consomme `AFCntDown` et son événement de trace est `data_ack`,
  au lieu d'`ack_only` et `NFCntDown`. Mêmes transmissions, même livraison, seule la série change
  (mesuré sur le scénario à deux trames : `FCntDown` `[0, 1]` dans les deux modes).
- **Sessions.** `plan_acks(sessions=...)` et `DeviceCounters.renew_session()` : deux sessions d'un
  même terminal ont des séries indépendantes ; le compteur 0 de la session 1 n'est **pas** un rejeu
  de celui de la session 0. Le terminal (identité) et la session (compteurs) sont distincts.
- **Interactions vérifiées** : ACK tardif en mode applicatif (`6 LATE`, 0 reçu), copies
  (`2 data_ack` + 2 `suppressed`), réémissions inchangées (6 transmissions, 4 réémissions), série
  épuisée (un seul ACK numéroté, `ack_not_sent` compte les trames sans ACK), et cohérence
  trace ↔ compteurs ↔ `gateway_tx` dans les deux séries.
- **Limites maintenues** : aucun scénario ne déclenche de `Join-Accept` (la session est fournie par
  l'appelant), `GAP` reste couvert par un test construit, et les scénarios livrés gardent leur
  empreinte (`downlink_payload` absent du hash à sa valeur par défaut).
- **Tests** : `python/tests/test_mac_counters_operational.py` (12 tests).

### Compteurs de trame complets : rejeu, désynchronisation, débordement
- **`python/lsim/fcnt.py`** : primitives testées seules — `CounterSeries` (reconstruction du champ
  16 bits dans la série 32 bits, rejeu, borne d'écart, épuisement à 2^32) et `DownlinkCounters`
  (`NFCntDown` / `AFCntDown` indépendantes, même départ de session).
- **Le terminal lit un champ de 16 bits.** `plan_acks` ne compare plus deux compteurs 32 bits : il
  reconstruit (`CounterSeries.reconstruct`) puis contrôle. `DUPLICATE` (champ identique — rejeu,
  copie) et `GAP` (> 16 384 — désynchronisation) deviennent des **verdicts de compteur**, exposés par
  `AckOutcome.counter` ; la classe `GAP` s'ajoute à la taxonomie, `AckCounts.gap` et
  `RetransmissionResult.ack_gap` la comptent, et l'invariant devient
  `standard + late + lost + duplicate + gap == acks_planned`.
- **`fcnt_down_start`** (0 à 2^32-1) fixe le premier compteur descendant de chaque terminal ; absent
  du hash à sa valeur par défaut, comme `fcnt_up_start`.
- **Correction de clé.** Les compteurs étaient clés par *transmission* dans le chemin des
  réémissions : deux trames d'un même terminal recevaient le même `FCntDown`, la seconde étant
  acceptée parce que sa série était neuve. `plan_acks(devices=...)` reçoit désormais le terminal
  physique ; les séries et l'écoute continue sont par terminal. Mesures des scénarios livrés
  inchangées (6 `LATE` ; 2 `STANDARD` + 2 `DUPLICATE` ; classe C : 2 `STANDARD`), mais `FCntDown`
  passe de `[0, 0]` à `[0, 1]` sur le cas « deux copies ».
- **Schémas d'API** : `fcnt_down_start` est ajouté au modèle de scénario (`schemas/api/v1`, trois
  fichiers, sept lignes chacun). Changement **additif** : aucune valeur de `EventKind` ni de
  `HopOutcome` ne bouge.
- **Statut normatif, écrit dans le code et la doc** : la reconstruction 16 → 32 bits et le rejeu
  strictement croissant sont des règles de la spécification ; la borne de 16 384 est la valeur
  historique `MAX_FCNT_GAP` des versions ≤ 1.0.3, **retirée de LoRaWAN 1.0.4 et suivants** (RP002),
  appliquée ici comme politique de rejeu explicite. Limites : `GAP` n'est produit par **aucun**
  scénario livré (la copie d'un ACK est un `DUPLICATE`), `AFCntDown` n'est pas exercé de bout en
  bout (un ACK ne porte pas de charge utile), et la remise à zéro par une nouvelle jointure reste
  hors modèle.
- **Tests** : `python/tests/test_fcnt_counters.py` (11 tests) — rejeu, borne exacte 16 384/16 385,
  débordement, bascule du champ 16 bits, séries NF/AF, `fcnt_down_start`, série épuisée, copie
  reconnue comme rejeu et non comme saut, réémission, neutralité du hash. Validation : **1 914**
  tests Python, **685 282/685 282** C++, empreintes `d2cb0fac…` / `ed126d7f…` inchangées.

### ACK de la couche MAC dans la trace
- **Un `ProtocolEvent` par ACK réellement émis.** `_mac_ack_events`
  (`python/lsim/retransmissions.py`) convertit les `AckEmission` du plan MAC en événements `ack` :
  instants, nombre de copies et verdicts viennent du **même plan** que `gateway_tx` et que les
  compteurs, au lieu des événements du planificateur du cœur. Les ACK tardif, dupliqué et non
  décodable cessent d'être invisibles dans la trace.
- **Aucune valeur nouvelle dans le contrat d'API.** Correspondance :
  `STANDARD → ack_only`, `LATE → not_listened`, `LOST` (fenêtre manquée) `→ device_transmitting`,
  `LOST` (non décodable) `→ lost_sensitivity`, `DUPLICATE → suppressed` (`suppressed` est déjà le
  verdict des doublons de maillage). `EventKind`, `HopOutcome` et `schemas/api/v1` sont inchangés :
  régénérer les schémas ne produit **aucun** diff. Un test refuse toute issue hors contrat.
- **Chemins du cœur intacts.** Sans `ack_delay_ms` ni `ack_repetitions` actifs, les événements
  restent ceux de `plan_native` : témoin à `ack_delay_ms: 0` → 2 trames, 2 événements `ack_only`,
  aucun doublon. Mesures sur les scénarios de référence : tardif 2 500 ms → 6 émissions,
  **6 événements `not_listened`** ; deux copies → 4 émissions, **2 `ack_only` + 2 `suppressed`** ;
  classe C → 2 émissions, **2 `ack_only`**. Dans les trois cas, chaque `t_ns` d'événement est un
  début d'intervalle de `gateway_tx` et `len(ack events) == acks_planned`.
- **Tests** : `python/tests/test_mac_trace_events.py` (7 tests) — correspondance émission ↔
  événement, tri et `seq`, trois scénarios de référence, cas construit `device_transmitting`,
  vocabulaire du contrat, non-régression du chemin du cœur. Validation de l'incrément :
  1 903 tests Python, 685 282/685 282 tests C++, empreintes `d2cb0fac…` / `ed126d7f…` inchangées.

### Consolidation MAC : compteurs de trame, taxonomie de l'ACK, classes d'écoute
- **Identité de trame réelle.** `FCntUp` identifie la trame et non la tentative : toutes les
  réémissions la partagent. `fcnt_up_start` (0 à 2^32-1) fixe le premier compteur d'un terminal,
  pour qu'il ne soit pas un rang de tableau. `FCntDown` est une série **par terminal** ; un ACK émis
  consomme un numéro, ses copies le conservent. `AckFrame` porte désormais les deux
  (`is_explicit` vrai) : l'appariement dispose de l'identité, même si le chemin du cœur continue de
  s'apparier par fenêtre. Sémantique alignée sur `lsim.session` (`begin_uplink`, `receive_downlink`).
- **Contrôle de rejeu.** Un ACK n'est accepté que si son `FCntDown` dépasse le dernier accepté par
  ce terminal : la copie d'un ACK est un `DUPLICATE` rejeté par le compteur, plus par une règle
  propre à la couche.
- **Taxonomie explicite** (`AckSort`) : chaque émission reçoit exactement une classe —
  `STANDARD`, `LATE`, `LOST`, `DUPLICATE` — et `AckPlan.counts` /
  `RetransmissionResult.ack_standard|ack_late|ack_lost|ack_duplicate|ack_not_sent` les agrègent.
  Un test vérifie `standard + late + lost + duplicate == acks_planned` sur les trois configurations
  de référence (2 500 ms, témoin, deux copies).
- **Classes d'écoute sans mélange.** `device_class` du groupe (`A` par défaut, `B`, `C`). A et B
  ouvrent RX1/RX2 ; l'ACK étant une descente de classe A, B s'y comporte comme A et ses *ping slots*
  restent hors périmètre. C écoute en continu. Mesure, même scénario `ack_delay_ms: 2500` :

  | Classe | Transmissions | ACK émis | `standard` | `late` | Livrées |
  |---|---|---|---|---|---|
  | A | 6 | 6 | 0 | 6 | 0/2 |
  | B | 6 | 6 | 0 | 6 | 0/2 |
  | C | 2 | 2 | 2 | 0 | 2/2 |

  Les émissions initiales sont identiques dans les trois cas (mêmes instants) : seule la réception de
  l'ACK change, la radio montante n'est pas touchée.
- **Cohérence des traces** : les intervalles d'ACK émis par la couche MAC sont imposés au moteur
  (pertes montantes réelles) et présents dans `gateway_tx` — vérifié : six ACK tardifs ⇒ six
  intervalles. **Limite énoncée** : ces ACK ne sont pas encore des `ProtocolEvent` de type `ack`.
- **Inventaire des commandes MAC validé** : `python/tests/test_mac_commands_inventory.py` couvre les
  **31** commandes du codec (encodage, décodage dans le bon sens, CID attendu, égalité des champs) et
  échoue si une commande est ajoutée sans ligne. `docs/MAC_CONSOLIDATION.md` distingue celles qui
  sont appliquées (LinkADR, DutyCycle, LinkCheck, DevStatus, DeviceTime, Rekey) de celles qui restent
  des codecs sans effet simulé.
- **Hash stable** : `fcnt_up_start: 0` et `device_class: A` sont retirés du hachage à leur valeur par
  défaut. Vérifié : `retransmissions_ack_tardif` garde `cee60ffc…`, les autres exemples aussi.
- Empreintes gelées `d2cb0fac…` / `ed126d7f…` inchangées ; **1 896 tests** Python (dont 13 pour la
  consolidation MAC et 4 pour l'inventaire des commandes) et **685 282** vérifications C++.

### Couche MAC de l'ACK : tardif et dupliqué, produits de bout en bout
- `lsim.ack_mac` (Python) rend possibles les deux seules situations que le planificateur du cœur ne
  sait pas produire : `DownlinkScheduler::on_received` renvoie `nullopt` hors RX1 et n'émet qu'un
  ACK par trame reçue. La couche ne touche **ni au cœur C++ ni à l'ABI** : elle replanifie l'instant
  d'émission de l'ACK, réutilise `_downlink_airtime_ns` et `receiver_sensitivity_dbm` du cœur, et
  décide si l'émission tombe dans une fenêtre écoutée (RX1, RX2, sinon `LATE`).
- Deux réglages **facultatifs** du bloc `retransmissions:` : `ack_delay_ms` (0 à 60 000) et
  `ack_repetitions` (1 à 3). À leurs valeurs par défaut, **rien ne change** : le chemin causal du
  cœur est emprunté tel quel, et un test de parité vérifie que la couche MAC reproduit exactement le
  planificateur natif. Hors bornes : `ValidationError`.
- **Hash stable** : les deux champs à leur valeur par défaut sont retirés du hachage, comme les
  champs ajoutés du bloc `mac`. Vérifié fichier par fichier contre le commit précédent :
  `retransmissions_nominal` `312a19b1…`, `retransmissions_ack_perdu` `27ce1bd0…`,
  `retransmissions_collision` `83d531e5…`, `retransmissions_doublons` `e0521e93…` — identiques. Un
  test fige `312a19b1…` pour que la stabilité ne dépende pas d'une relecture.
- Mesures `build_trace`, mêmes graines :

  | scénario | réglage | transmissions | ACK émis | ACK reçus | livrées | doublons ignorés |
  |---|---|---|---|---|---|---|
  | `ack_tardif` | `ack_delay_ms: 2500` | 6 | 6 | **0** | 0/2 | 0 |
  | `ack_tardif` | témoin `ack_delay_ms: 0` | 2 | 2 | 2 | 2/2 | 0 |
  | `ack_duplique` | `ack_repetitions: 2` | 2 | **4** | 2 | 2/2 | **2** |

  L'émission commence à `fin + 1 s + delay_ms`. Frontières balayées de 0 à 2 500 ms (pas de 50) :
  `delay_ms` 0 à 999 tombent dans RX1, 1000 à 1999 dans RX2 (reçus), 2000 et au-delà après RX2 —
  ACK émis, airtime consommée, jamais entendu. Une passerelle occupée repousse l'émission
  (`max(ouverture + delay, fin d'occupation)`) et peut faire basculer un ACK de RX1 vers RX2 ou hors
  fenêtre.
- **Isolation de la dégradation du récepteur** (réserve d'évaluation) : trois tests. Le premier
  compare les empreintes `(device_index, start_ns, end_ns, rssi, outcome)` des uplinks à 0, 5, 10 et
  20 dB de marge — une seule empreinte distincte exigée : la liaison montante est **inchangée** au
  bit près ; le deuxième montre que la réception de l'ACK, elle, bascule ; le troisième vérifie que
  le premier passage (`retries: 0`) est identique, donc que le budget montant n'est pas touché.
- Documentation corrigée là où elle affirmait le contraire : `docs/USAGE.md` disait « aucun scénario
  ne les provoque » pour l'ACK tardif et l'ACK dupliqué ; le bloc `retransmissions:` y gagne les deux
  clés, les tableaux de fenêtres mesurées et les deux exemples exécutables.
- Limites énoncées, non masquées : `LATE` est rangé avec les pertes de sensibilité dans
  `DownlinkDelivery` (pas de verdict « hors fenêtre » dans l'énumération existante) ; `ack_repetitions`
  est une hypothèse de réseau, LoRaWAN 1.0.4 ne répète pas l'ACK en classe A ; aucun `FCntUp` /
  `FCntDown` réel n'est décrémenté ; la couche est Python, hors du cœur C++.
- Empreintes gelées `d2cb0fac…` / `ed126d7f…` inchangées ; suites complètes **1 879 tests** Python
  (dont 26 pour les scénarios de retransmission) et **685 282** vérifications C++.

### Retransmissions pilotées par le scénario, et modèle ACK explicite
- Nouveau bloc `retransmissions:` **facultatif** dans le YAML (`retries` 0 à 7,
  `retransmit_delay_ms` >= 2000, `enforce_duty_cycle`, `energy_profile`, `enabled`). Absent :
  comportement historique et hash inchangé. `retries: 0` n'ajoute aucune transmission.
  Paramètre hors bornes ou clé inconnue : `ValidationError`.
- `build_trace` et `run_scenario` empruntent ce chemin : une entrée de trace **par transmission**,
  indices des terminaux du scénario, et `trace.retransmissions` (essais, ACK, doublons, refus).
- Le modèle ACK est découpé en trois notions distinctes — livraison de la descente
  (`DownlinkDelivery`), réception de l'ACK (`AckReception`), acquittement logique — au lieu de
  confondre « descente planifiée » et « trame ACK reçue ». `AckFrame` prépare une représentation
  MAC complète sans toucher à l'ABI.
- Quatre scénarios exécutables sous `docs/exemples/retransmissions_*.yaml` couvrent : aucun échec,
  collision puis récupération, refus par rapport cyclique, et ACK perdus avec **doublons réseau
  réels** (8 pour 20 réceptions).
- Mesures comparatives, mêmes graines, scénario `ack_perdu` (récepteur +10 dB) :

  | réémissions | transmises | reçues | ACK reçus | livrées | doublons | collisions | occupation | énergie |
  |---|---|---|---|---|---|---|---|---|
  | 0 | 24 | 11 | 8 | 8/24 | 0 | 6 | 0,296 | 2,232 J |
  | 1 | 43 | 15 | 7 | 7/24 | 1 | 16 | 0,440 | 4,000 J |
  | 3 | 83 | 20 | 5 | 5/24 | 8 | 31 | 0,543 | 7,720 J |

  **Plus de réémissions ne veut pas dire plus de livraisons** : ici la livraison baisse (8 → 5)
  parce que le trafic ajouté provoque des collisions. Aucun nombre de tentatives n'est un optimum
  universel.
- Fait mesuré, à ne pas masquer : avec un récepteur nominal, le planificateur causal livre l'ACK
  de **toute** trame reçue (15 réceptions, 15 ACK, 0 doublon). La perte d'ACK exige une hypothèse de
  récepteur dégradé ; elle n'est pas représentable par le seul scénario.
- Empreintes gelées `d2cb0fac…` / `ed126d7f…` inchangées ; suites complètes **1 869 tests** Python
  et **685 282** vérifications C++.

### Point fixe uplinks ↔ descentes : borne portée à 64 itérations, cycles signalés (F1)
- `MAX_ITERATIONS` passe de **12 à 64**. Mesure sur les 120 configurations de référence de D3.2 (40 graines × 3 jeux, `quartier_sf9.yaml` à 2 000 dispositifs) : le point fixe est atteint en **9 à 21 itérations** ; les **69** configurations qui échouaient en `RuntimeError` en demandaient **13 à 21**. Les **51** configurations déjà convergentes ne changent pas d'un octet : même nombre d'itérations, empreinte du résultat complet (`records`, `gateway_tx`, totaux, compteurs par dispositif) identique.
- Un état qui se répète à l'identique est signalé immédiatement (`cycle de période N`) au lieu d'épuiser la borne : une répétition exacte ne peut pas converger. Le message d'échec indique le nombre d'itérations effectuées. `build_protocol_events` (jointures seules) suit le même critère.
- Aucun résultat approximatif : la trace n'est renvoyée que si l'égalité exacte de l'état est vérifiée ; la borne ne sert qu'à borner le travail.
- Effet de bord mesuré : les scénarios denses 11 et 38 de `test_downlink_plan_parity.py`, réputés sans point fixe, convergent désormais (la trace causale et le point fixe Python coïncident) ; la garde `except RuntimeError` du test reste en place.
- Tests : `test_fixed_point_converges_beyond_twelve_iterations` (1 300 dispositifs, graine 5, point fixe à la 16e itération — échouait avant la correction) et `test_fixed_point_cycle_is_reported_immediately` (cycle de période 2 détecté au 3e tour).

### Frontal RF v4 : gain et perte par terminal et par passerelle (ABI additive)
- Quatre points d'entrée ajoutés sans modifier les 91 existants : `lsim_simulate_uplinks_trace_v3`, `lsim_simulate_uplinks_trace_gw2_v2`, `lsim_simulate_uplinks_multi_dl_v2`, `lsim_simulate_closed_loop_v4` (95 symboles exportés).
- `lsim_device_rf` / `lsim_gateway_rf` : `present` à bits indépendants (`LSIM_RF_HAS_ANTENNA_GAIN`, `LSIM_RF_HAS_CABLE_LOSS`). Un champ absent n'est pas lu ; un bit inconnu, une valeur hors bornes (`|G| <= 40 dBi`, `0 <= L <= 40 dB`) ou une table partielle sont refusés (statut 301).
- Sémantique réciproque : `RSSI_ul = (P_tx + G_d − L_d) + (G_g − L_g) − PL − shadowing` ; la descente réutilise le montant, les termes de la chaîne terminale s'annulent, donc le gain est compté une seule fois. Quand une table terminale est fournie, `rule.device_antenna_gain_dbi` n'est plus ajouté (aucun cumul).
- `lsim_closed_loop_v4_args` enveloppe les arguments v3 : validation et écriture inchangées.
- Pont Python : `python/lsim/rf.py` (`DeviceRf`, `GatewayRf`, `None` = champ absent), routage unique et testé par espions ; dès qu'un frontal est fourni, l'ancien point d'entrée n'est plus appelé.
- **Sans frontal fourni, résultat identique au bit près** : empreintes `d2cb0fac6c2d9950` / `ed126d7ff5aac3b0` inchangées, 1802 → 1839 tests Python (dont 30 pour le frontal), C++ 685165 → 685249 vérifications.

### Caractérisation RF R1 (tests seulement, aucun changement de comportement)
- `python/tests/test_rf_characterization_r1.py` : 24 tests qui figent le comportement radio **réel** de la base, mesuré et non supposé. Six sujets : gain de la passerelle (+3 dBi = +3 dB, additif de 0 à 6 dBi, sans effet sur l'airtime ; RSSI = P_tx + G_passerelle − PL(d) à 1e-9) ; absence de gain d'antenne du terminal dans le modèle (seul `tx_power_dbm` agit) et non-contamination du gain de descente sur la liaison montante (RSSI montant identique au bit près pour 0 / 10 / 20 dBi, alors que l'issue de descente bascule) ; descente par réciprocité, avec bascule de réception à 12 km / SF12 quand le gain terminal passe de 0 à 10 dBi ; sensibilité RAK7249 (catalogue −139 dBm, aucun point publié, seuils relatifs SX1276 appliqués : écarts 16 / 13 / 10 / 7 / 6 / 3 dB du SF7 au SF12) ; collisions de même SF, frontière de capture exacte et inclusive à 6 dB, chevauchement partiel (140 ms chevauche, 150 ms non pour un airtime SF9 de 144 384 000 ns) ; contrôles (SF différents et transmissions disjointes ne collisionnent pas).
- Limites documentées dans les tests, non corrigées ici : la fréquence est portée par la propagation et non par la trame (aucun modèle de canaux distincts au niveau radio) ; l'issue de descente utilise un encodage inversé de celui de la montée (0 = reçu), figé par l'ABI.
- Empreintes gelées, résultats C++ et symboles exportés **inchangés** : `d2cb0fac6c2d9950` / `ed126d7ff5aac3b0`, 685165 / 685165, 91 symboles.

### Modèle de canaux LinkADR : exclusions par canal, trace interne v3 (boucle fermée, EU868)
- Refus de canal : exclusion par canal des seuls suspects (`demandés \ confirmés`), 100 uplinks admissibles (convention du simulateur, ni TS001 ni RP002). Le débit et la puissance acceptés restent appliqués.
- Refus à suspects vides (aucun suspect, masque demandé entièrement confirmé ou vide) : exclusion du masque exact (politique du simulateur, non TS001), sans répétition pendant 100 uplinks, renouvelée si le même masque est refusé, expirée sans commande. Repli sur le dernier masque confirmé.
- Refus de débit et de masque simultanés (D5) : seul le débit est exclu ; le canal indéfini n'est exclu qu'au refus suivant à débit accepté.
- **Changement de comportement** : dans le scénario 011 (masque refusé, débit et puissance acceptés), le masque entier n'est plus exclu. Voir `docs/CHANNEL_MASK_MODEL.md`.
- Compteurs indépendants par débit, puissance et canal ; renouvellement signalé ; expiration sans commande.
- Trace interne v3 (`LoopChannelIo::trace_v3`, opt-in, C++ seulement) : bits LinkADRAns et contenu acquitté, exclusions créées / renouvelées / expirées, décisions ADR, motifs D5, descentes avec issue radio et cause de perte, chaque événement avec son origine (`Normative`, `Radio` ou `SimulatorPolicy`). Sans effet sur les radios. Non exposée à Python : elle attend l'ABI v3.
- Empreintes historiques (dump, trace ADR) inchangées.

### Réémission des commandes LinkADR (TS001-1.0.4 §5, décision utilisateur)
- Réémission : une commande LinkADRReq sans LinkADRAns est renvoyée à chaque uplink reçu, sans plafond normatif ni temporisation. La norme ne fixe ni nombre maximal de réémissions ni backoff exponentiel pour cette règle (section 7 : seulement les uplinks confirmés qui attendent un acquittement, intervalle aléatoire).
- Chemin en direct (`lsim serve`) : le plafond de 8 essais devient facultatif (`MAC_MAX_ATTEMPTS = None` par défaut ; une valeur fixe est une politique d'implémentation). Un LinkADRAns négatif (au moins un bit à 0, TS001 §5.2) ferme la demande, journalisé avec ses trois bits, et la même configuration n'est pas renvoyée. Refus journalisé, non persisté.
- Boucle fermée : aucun plafond. Une réponse négative exclut la valeur refusée de la décision ADR suivante au lieu de bloquer définitivement l'ADR. Ce chemin n'est pas atteignable tel quel : le serveur et le dispositif partagent le même plan régional, donc aucun refus n'est produit ; non testé de bout en bout.
- Tests : `test_linkadr_wiring.py` (réémission au-delà de 8 essais, refus sur chaque bit) ; `test_closed_loop.cpp` `test_linkadr_reissued_on_each_uplink_without_answer` (mutation vers un plafond à 60 uplinks détectée).

### Boucle fermée : LinkADRReq et DutyCycleReq (passerelle unique)
- Bloc `mac:` : `link_adr` (LinkADRReq, décision ADR côté serveur) et `duty_cycle_exponent` (DutyCycleReq, 1/2^k). Actifs seulement si demandés ; sans ces champs, scénarios, résultats et empreintes inchangés. Schémas régénérés.
- `build_trace` et `run_scenario` passent par la boucle fermée (une seule exécution native, descentes créées par le moteur) dès que l'un de ces champs est actif. Événements `mac_request` (LinkADRReq, DutyCycleReq) et `mac_answer` (LinkADRAns, DutyCycleAns).
- **Puissance** : index 0 = puissance configurée plafonnée par la PIRE du plan ; pas du plan par index ; index réservés refusés. Table TXPower : EU868 uniquement (RP002-1.0.3, PIRE +16 dBm, pas 2 dB, index 0 à 7). Un plan sans table refuse LinkADR.
- **Duty cycle** : limite réglementaire par index (sous-bande à la PIRE de l'index, combinée au duty cycle du groupe) ; DutyCycleReq ne fait que la réduire. Repos après une émission = airtime de l'émission terminée × (1/D − 1).
- **Refusé explicitement** : jointure, passerelles multiples, mesh.
- **Réservations MAC dans la boucle fermée** : LinkCheckReq, DeviceTimeReq et DevStatusAns réservent leurs octets dans le temps d'antenne ; LinkCheckAns, DeviceTimeAns et DevStatusReq sont portés par la descente de l'uplink concerné. DevStatusAns est confirmée à la réception de l'uplink suivant. Nouvelle API `lsim_simulate_closed_loop_v2` (la v1 est conservée). Sans ADR ni DutyCycle, la boucle fermée reproduit le chemin historique (test de parité).
- **Fenêtres RX (TS001 §3.3)** : le dispositif n'émet plus avant la fin de RX2 de son uplink précédent (fin + 3 s), décision C1 ; la boucle fermée ouvre RX2 (fin + 2 s, SF12, 1 s) si la passerelle ne peut pas émettre en RX1 (RP002-1.0.3). Fréquence RX2 non modélisée ; RP002-1.0.5 non vérifiée. Sans bloc `mac:`, empreintes inchangées.
- **Départ de descente (A6)** : la passerelle démarre une descente exactement à l'ouverture de la fenêtre ; une fenêtre encore occupée n'est pas décalée (repli RX2, puis perte). Sous la charge mixte à 5 dB, plus aucune expiration de réponse n'est observée (ADR et DutyCycle ne sont plus en attente simultanément) ; l'expiration est couverte par les tests de file déterministes et `test_mac_queue_fairness_bounded_wait`. Effet mesuré (C++, mêmes paramètres que la charge mixte de référence, 8 dispositifs, 40 messages, 5 dB) : commandes mises en file 519 → 402, réponses reportées/expirées 30 → 0, réceptions d'uplinks 173 → 134, descentes en RX2 (SF12) 0 → 26 (même configuration). Sous 120 messages à 5 dB, réceptions 472 → 298 : la descente ne peut plus être décalée, donc RX1 bloquée devient perte ; c'est le comportement normatif, pas une régression. Règle d'occupation en boucle fermée : intervalles exacts (une descente n'est planifiée que si elle ne chevauche aucune descente déjà planifiée) au lieu du maximum des fins (`busy_until`), qui refusait à tort des fenêtres libres ; test `test_exact_overlap_accepts_window_before_later_emission` (vérifié par mutation : il échoue avec l'ancienne règle). Effet mesuré (sonde C++ hors dépôt, mêmes graines et paramètres, avant → après) : 40 messages, 5 dB : descentes RX1 108 → 111, RX2 26 → 23, non planifiées 11 → 8 ; réceptions, file et occupation de sensibilité inchangées ; 120 messages, 5 dB : tous compteurs identiques ; 120 messages, 15 dB : commandes mises en file 1155 → 1146, réceptions 385 → 382, pertes de sensibilité 303 → 319. Les descentes récupérées ne sont pas reçues par le dispositif (descentes reçues inchangées), d'où l'absence d'effet sur la file à 40 messages.
- **Backoff ADR côté dispositif (F14, TS001 §4.3.1.1)** : en boucle fermée avec ADR, ADRACKCnt compte les uplinks depuis la dernière descente reçue ; ADRACKReq dès 64 ; sans descente pendant 96 uplinks, puissance par défaut puis débit −1 cran tous les 32 uplinks. Un uplink avec ADRACKReq déclenche une descente de classe A (sans commande si besoin). Le cran de débit suit RP002-1.0.5 Table 12 (EU868) : DR1–DR7 → DR−1, DR8 → 0, DR9 → 8, DR10 → 0, DR11 → 10, DR12 → 5, DR13 → 12 ; si le débit cible n'est pas disponible, le débit reste inchangé. Pour DR1–DR7 la table est identique à DR−1, donc aucun résultat atteignable ne change ; DR8 et plus ne sont pas atteints en boucle fermée (`max_dr` ≤ 7), la ligne n'est donc pas testée de bout en bout. Sans ADR, aucun changement ; empreintes historiques vérifiées inchangées.
- **DR13 (SF5/125 kHz), profil passerelle SX1303 (C++)** : `receiver_sensitivity_dbm(sf, bw, ReceiverProfile::Sx1303Gateway, s)` renvoie −121 dBm pour SF5 (datasheet SX1303, p. 14 : PER 10 %, 12 octets, front-end SX1250 ; valeur indicative, non normative LoRaWAN). Le profil SX1276 par défaut est inchangé et n'a pas de SF5. Airtime SF5 accepté en en-tête explicite (hypothèse) ; SF6 toujours refusé. Le moteur refuse un uplink SF5 (profil par défaut) et une descente SF5 (sensibilité dispositif NV). Non branché aux scénarios Python ni à l'ABI.
- **Modèle de sensibilité absolue `sensibilite-par-sf-v2`** : seuils passerelle absolus en dBm, indexés par bande (125/250/500 kHz) et SF (5 à 12). Sans décalage relatif ni conversion, et sans repli sur la référence SX1276 pour une paire absente. Valeurs SF5 à SF12 à 125 kHz du datasheet SX1303 (p. 14-15 : PER 10 %, paquets de 12 octets, front-end SX1250, indicatives, non normatives). Multi-passerelle refusée. Descente SF5 vers un dispositif refusée (sensibilité terminal NV). SF5 accepté en uplink (en-tête explicite supposé), SF6 toujours refusé. ABI : `lsim_gateway_v2` (modèle 0 = v1 ; modèle 1 = absolu), points d'entrée `lsim_simulate_uplinks_trace_gw2` et `lsim_simulate_closed_loop_gw2`. ABI v1 inchangée. Branché au pont Python (`lsim/gateway_sensitivity.py`, `_CGatewayV2`), au schéma de scénario (`gateway.sensitivity` : `profile` du catalogue `sx1303-datasheet`, ou `points` explicites avec `source` et `conditions`) Chemins : `run_scenario` sans MAC et `simulate_uplinks_trace` passent par la trace ABI v2 ; `build_trace` (descentes causales) passe par `lsim_simulate_uplinks_causal_gw2`, mais refuse explicitement une descente vers SF5 (sensibilité du dispositif NV) ; la boucle fermée passe par `lsim_simulate_closed_loop_gw2`. Multi-passerelles et `coverage_radii` refusent le modèle ; `geo` suit le seuil absolu. Un groupe SF5 exige le modèle, la région EU868, une paire SF5 documentée, et refuse le bloc `mac:` (sensibilité terminal NV). Le catalogue ne contient pas de RAK5146 : aucune valeur n'a été ajoutée sans source de mesure. Empreinte : le bloc `sensitivity` entre dans le hash seulement s'il est présent. Schémas régénérés. Tests : `python/tests/test_gateway_sensitivity.py`.
- **File MAC** : les FOpts ne dépassent jamais 15 octets. LinkADR et DutyCycle passent en premier ; LinkCheckAns, DeviceTimeAns et DevStatusReq attendent dans une file FIFO et sont reportées (puis expirent après 3 reports) si elles ne tiennent pas. Compteurs `enqueued`, `dispatched`, `dispatch_lost`, `deferred`, `expired`, `pending_at_end` (API C v2 et `TraceRun.mac_queue`).
- **Conformité TS001 §5 (réponses MAC)** : LinkCheckAns et DeviceTimeAns ne sont plus reportées. Une réponse qui ne tient pas dans la descente de son uplink expire aussitôt (la norme les limite aux fenêtres RX qui suivent la requête). Changement de résultats pour les scénarios avec MAC qui saturent la descente. Matrice de conformité : `docs/CONFORMANCE_MATRIX.md`.
- **Validation de la file** : cycle de vie explicite (`LoopResult::mac_items` : en attente, placée, livrée, perdue, expirée), compteur `delivered` (API C v2 `lsim_loop_mac_counters`, `MacQueueCounters.delivered`), invariants testés (C++ et Python). Équité : hypothèse de famine testée et infirmée ; la garantie retenue est la borne d'attente (`mac_max_deferrals`). L'ABI v1 n'expose plus de compteurs de file (`mac_queue` vaut `None`).
- **Octets MAC** : `TraceRun.mac_bytes` sépare octets réservés, octets émis et réponses DevStatus confirmées. Les résultats de simulation ne changent pas.
- Tests : `core/tests/test_closed_loop.cpp`, `python/tests/test_mac_loop.py`. Documentation : `docs/CLOSED_LOOP_PLAN.md`.

### Commandes MAC : phase 1, étape 1
- Bloc `mac:` du scénario (`link_check_every`, `device_status_every`, bornes 0 à 1000 ; 0 = désactivé). Inclus dans l'empreinte SHA-256 ; absent = empreinte inchangée. Schémas `scenario_input`, `run_create` et `validate_request` régénérés.
- **Sans effet sur le calcul pour l'instant** : le moteur n'émet pas encore les commandes. Plan complet : `docs/MAC_PLAN.md`.
- Tests : `python/tests/test_scenario_mac.py`.

### Animation des trames (studio)
- **Lecteur** sous le panneau de simulation : lecture et pause, vitesses ×1 à ×300, curseur de temps, instant courant en secondes simulées.
- **Plan animé** : chaque saut apparaît comme une trame qui se déplace de sa source vers sa destination pendant 1 s simulée, puis reste visible 4 s. Couleur : vert (livré), rouge (perdu), gris (autre). Une remise au réseau est un anneau autour de la passerelle.
- **Journal par saut** : une ligne par événement (temps, source, type, résultat), dépliable sur ses sauts ; un clic place l'horloge sur l'événement.
- **Source des données** : `GET /api/v1/runs/{id}/events` et `GET /api/v1/runs/{id}/devices` (pages de 500). Le mapping `dev:<index>` vers le capteur vient de la page des dispositifs (groupe = identifiant du capteur) ; `gw:<nom>` désigne directement la passerelle.
- **Limite** : au-delà de 20 000 événements, l'animation n'est pas chargée (message dans l'état de simulation). Les résultats restent affichés.
- **Tests** : `web/tests/animation.test.mjs` (logique pure) et l'étape « animation » du test e2e (horloge qui avance, au moins une trame dessinée).


### Studio web (`web/studio.html`) et verrou de base
- **Interface** : page `web/studio.html` (Vite, à côté de la carte de résultats `index.html`, inchangée). Plan éditable (ajout, glisser-déposer, retrait), console CLI par équipement (historique aux flèches, erreur au caret), réglages capteur avec validation côté studio et serveur, simulation avec résultats par passerelle (compteurs, latence p95, relais mesh), exercices (énoncé, indices avec pénalité, notation, journal), sessions multiples (liste, nouvelle session, suppression).
- **API ajoutée** : `GET /api/v1/sessions` (sessions du compte), `DELETE /api/v1/sessions/{id}` (204), `POST /api/v1/sessions/{id}/nodes/{node_id}/position` (`Position`). Schémas `study_session_list` et `study_position` régénérés.
- **Verrou de base** : `make_server` prend un verrou exclusif `<runs-db>.lock` (flock) ; un second serveur sur le même fichier est refusé avec `RuntimeError`. Libéré à `server_close`.
- **Profil de relais composite** `rak5146-rak5148` (`gateway_profiles.py`) : RAK5146 pour l'accès sous-GHz (EU433, EU868, RU864, CN470, US915, AS923, AU915, KR920, IN865 ; 27 dBm ; -139 dBm à SF12 / 125 kHz ; 8 canaux) et RAK5148 pour le lien mesh 2,4 GHz. Sources : fiche RAK5146, fiche RAK5148, page produit RAK « Outdoor Gateway Mesh with 2.4G Backhaul » ; compatibilité logicielle à confirmer par le constructeur. Le compilateur l'utilise pour tous les relais (`MESH_PROFILE`).
- **Réserves du profil `rak5146-rak5148`, distinctes** (décision de l'auteur) : (1) *compatibilité logicielle* : statut « à valider » (`software_validated=False`, `software_status`), levé par un essai réel sur ChirpStack Gateway OS (détection des deux concentrateurs, accès EU868 et backhaul mesh 2,4 GHz, relais entre les radios, redémarrage, perte du lien mesh) ou une confirmation RAK ; le compilateur le signale dans `notes`. (2) *fidélité radio* : voir l'entrée « Sensibilité dans le budget de liaison » ci-dessous.
- **Sensibilité dans le budget de liaison** (modèle `decalage-uniforme-v1`, `SENSITIVITY_MODEL`) : la sensibilité publiée d'un profil entre dans la réception montante des passerelles d'accès, sous forme d'un décalage uniforme du seuil de référence du moteur. Décalage = sensibilité publiée − sensibilité de référence à **un point publié** du profil (`rx_sensitivity_point`). Résultat : RAK5146 (-139 dBm à SF12 / 125 kHz, référence moteur -136 dBm) → **-3 dB**, appliqué à toutes les combinaisons SF/BW ; RAK5148 (point SF12 / 203 kHz hors des bandes du moteur) et RAK7249 (aucun point publié) → 0 dB. Champ `rx_sensitivity_offset_db` sur `GatewaySpec` (C++), `lsim_gateway` (C) et `Gateway` (Python), borné à ±20 dB. Passerelle sans profil : 0 dB, résultats inchangés.
  - **Hypothèses non calibrées** : décalage uniforme sur SF et BW (la fiche ne publie qu'un point) ; descente (seuil du dispositif) et lien mesh 2,4 GHz (table SX1280) inchangés .
  - **Avant/après** : sur `examples/mesh_relais_quartier.yaml` (capteurs SF9, rayon 3,5 km) aucune perte par sensibilité, donc résultats identiques (2840 reçues sur 3000) ; cet exemple ne teste pas le seuil. Cas de comparaison (même topologie, capteurs SF12 jusqu'à 40 km) : sans décalage, 1100 reçues, 1140 pertes par sensibilité, 760 collisions (PDR 36,7 %) ; avec décalage, 1550 reçues, 110 pertes par sensibilité, 1340 collisions (PDR 51,7 %). Le décalage fait donc entendre plus de trames, et les collisions augmentent d'autant.
  - **Carte de couverture** (`geo.py`) : même seuil que la simulation (référence + décalage), donc le rayon d'une passerelle composite grandit de 3 dB dans la carte comme dans le calcul.
  - **Tests** : `python/tests/test_gateway_sensitivity.py` (effet au seuil dans les deux sens, valeur neutre par défaut, bornes ; décalages du catalogue).
- **RAK7249 vérifié** : la fiche RAK7249 (WisGate Edge Max) donne -139 dBm (min) pour la réception LoRa, sans spreading factor ni largeur de bande : pas de point, donc 0 dB (confirmé par l'auteur).
- **Prochaine évolution** : mesurer la sensibilité réelle du RAK5146 et de la descente, et remplacer le décalage uniforme par un modèle par SF/BW dès qu'un point mesuré existe (nouvelle version de modèle).
- **Règle de validation** : un relais dont le profil a des bandes d'accès ne peut pas servir un groupe déclaré dans une région absente de ces bandes (`rak5148` seul, EU868 : refusé). Les groupes sans région ne sont pas contraints.
- **Limite connue** : les indices révélés ne sont pas relus au rechargement de la page (le serveur applique la pénalité, l'interface ne la réaffiche que dans l'onglet courant).
- Tests : `web/tests/studio-modules.test.mjs` (8, `npm test`), `web/tests/e2e/studio.e2e.mjs` (navigateur Chromium réel contre l'API, `npm run test:e2e`), `test_study_persistence.py` (+1, verrou), `test_study_simulate.py` (+2, déplacement et liste/suppression).

### Panneau d'étude : simulation d'une session, topologie éditable, persistance (servis)
- **Simulation depuis la session** : `POST /api/v1/sessions/{id}/simulate` compile la topologie et les configurations CLI en scénario (`lsim/study_compile.py`) et crée le run par le chemin de `POST /runs` (mêmes validations). La réponse donne `run_id`, `links` et `notes`. La liaison au résultat est automatique à la fin du run : `POST /sessions/{id}/simulation` sans `links` lie les passerelles du run compilé.
- **Réglages capteur** : `Node.sensor` (SF, charge, puissance, période, messages, départ, plan, canal). Ils sont les paramètres d'un groupe de simulation nommé comme le capteur.
- **Topologie éditable** : `POST /sessions/{id}/nodes` (ajout, 64 au plus, identifiant unique), `DELETE /sessions/{id}/nodes/{node_id}`, `POST /sessions/{id}/nodes/{node_id}/sensor`. Le serveur n'accepte pas `PUT` : c'est `POST` qui remplace les réglages.
- **Règles de compilation** : passerelle à interface lora arrêtée exclue du run ; avec relais, exactement une frontière active ; réglages mesh (SF, bande) identiques entre frontière et relais (422 sinon) ; sauts : plus petite valeur réglée ; mode mesh incohérent avec le rôle (422) ; plan régional et sous-bande identiques pour toutes les passerelles. Défauts appliqués (EU868, sous-bande 1) et réglages non modélisés listés dans `notes`.
- **Persistance** : sessions, configurations CLI, liaisons et journal sont écrits dans le fichier SQLite des runs (`--runs-db`, `lsim/study_store.py`) et relus au démarrage. Expiration de 4 h d'inactivité appliquée après redémarrage. Une lecture est écrite au plus une fois par minute.
- **Seuil de latence validé** : 300 ms (p95 remise au LNS par la frontière), décision de l'auteur.
- **Exercices** : chaque topologie de départ contient un capteur. Dans les exercices à relais, le capteur émet à -10 dBm à 1500 m, la frontière ne l'entend pas. L'exercice de latence envoie 20 messages. Son indice mentionne la bande mesh : à 203 kHz, p95 ≈ 790 ms (échec) ; à 812 kHz, ≈ 228 ms (réussite).
- **Changement de comportement** : `unlinked` (réponse de liaison) liste aussi les capteurs, qui ne sont jamais liés à une passerelle.
- Tests : `test_study_compile.py` (18), `test_study_simulate.py` (17), `test_study_persistence.py` (6, dont un redémarrage du serveur HTTP). Schémas `v1` régénérés (`study_sensor`, `study_simulate`, `study_simulate_request`). Suite Python : 1489 passés, 1 ignoré.

### Panneau d'étude : critères de connectivité et de latence, indices, journal (servis)
- **Critères** : `_mesh_inbound(node, from_node)` (lien mesh observé entre deux passerelles liées, via `mesh_inbound` du résumé) et `_latency_p95_at_most(node, 300 ms)` (latence p95 remise au LNS).
- **Indices** : `POST /api/v1/sessions/{id}/hints`. Deux par exercice ; chaque indice révélé retire `HINT_PENALTY` = 2 points, plancher 0. Plus d'indice : 409 ; exercice différent : 422 ; exercice ou session d'un autre compte : 404.
- **Journal** : `GET /api/v1/sessions/{id}/attempts` (50 au plus par session ; numéro, instant, exercice, score, indices, réussite). Aucune commande CLI, aucun secret.
- **Publication** : les schémas du panneau sont dans `schemas/api/v1` (généré par `api_contract`). Le dossier `schemas/api/study-draft/` est supprimé et `study_contract` n'écrit plus de fichiers.
- Tests : `test_study_exercises.py` (23), `test_study_contract.py` (6), `test_study_api.py`, `test_study_cli.py`.

### Métriques par passerelle dans le résumé de run (`trace_metrics.py`)
- Par passerelle : `latency_samples`, `latency_p50_ms`, `latency_p95_ms` (uplinks de donnée remis au LNS, de l'émission à la remise), et `mesh_inbound` (sauts mesh livrés par émetteur). Champs optionnels dans `GatewayReportOut`.
- Tests : `test_trace_metrics.py` (9), plus un test de publication dans `test_study_exercises.py`.

### Correction de la trace des uplinks relayés (`trace_events.py`)
- **Changement de comportement** : pour un uplink livré par le mesh, le saut NS part de la passerelle frontière à `fin + border_delay` et non plus de la fin de réception du premier relais. L'attribution va à l'émetteur réel (`_direct_deliverer`). Un relais ne livre jamais en direct. Les latences issues de la trace changent donc pour ces uplinks.

### Panneau d'étude : exercices notés et liaison explicite (servis)
- `GET /api/v1/exercises` (catalogue sans critères ni solution) et `POST /api/v1/exercises/{id}/submit` (le client n'envoie que `session_id`; le serveur note l'état qu'il détient).
- Trois exercices : EU868, relais à deux sauts, US915 sous-bande 2 avec réception. Aucun indice servi (`hints_available: 0`).
- `POST /sessions` : `exercise_id` acceptée (topologie de l'exercice, `nodes` vide). `nodes` vide autorisé.
- **Changement** : la liaison à un run ne se fait plus par nom. `POST /sessions/{id}/simulation` reçoit `links: [{node_id, gateway}]` ; toute association invalide annule la requête entière.
- Limites de sessions appliquées sous verrou, testées en concurrence.
- Schémas `study-draft` régénérés (`study_simulation_bind`, `study_session_create`). Schémas `v1` inchangés.
- Tests : `test_study_exercises.py` (14), `test_study_api.py` (27). Suite Python : 1431 passés, 1 ignoré.

### Panneau d'étude : sessions, CLI et liaison aux résultats (servis)
- Routes : `POST /api/v1/sessions`, `GET /api/v1/sessions/{id}/topology`, `POST /api/v1/sessions/{id}/cli`, `POST /api/v1/sessions/{id}/simulation`. Propriétaire filtré (404 pour un autre compte), bornes et expiration en mémoire.
- `show lorawan counters` et `show mesh counters` affichent les compteurs réels de la passerelle associée dans le run lié (association explicite, voir ci-dessous). Les `show` non alimentés par le moteur (voisins, routes, appareils) sont retirés de la grammaire.
- Exercices : servis depuis (voir l'entrée « exercices notés » ci-dessus).
- Tests : `python/tests/test_study_api.py` (20). Suite Python : 1412 passés, 1 ignoré.

### CLI d'équipement du panneau d'étude (phase 4, brouillon)
- `python/lsim/study_cli.py` : grammaire IOS côté serveur (modes utilisateur, privilégié, configuration, interface), abréviations par préfixe, marqueur `^` à la colonne fautive, `?` et Tabulation, `show running-config` n'affichant que les paramètres positionnés (aucun secret n'existe encore ; masquage par construction, `******`).
- Commandes de vérification (`show mesh neighbors`, `show lorawan counters`, etc.) répondent « aucune simulation » tant qu'aucun résultat n'existe.
- Syntaxe `lorawan server ADDR up-port N down-port N` retenue (spec §4.2). Tests : `python/tests/test_study_cli.py` (19). Aucune route servie.

### Restes de la liste mesh : validate, export, tests de service
- `POST /api/v1/scenarios/validate` accepte un `protocol` optionnel (additif) : la règle de trame mesh y est appliquée comme à la création (problème `validation_error` avec le champ). Schéma `validate_request` régénéré.
- Export mesh : `MeshSummary.lost_mesh` (trames décodées à l'accès puis perdues sur le mesh). Avant, le total exporté ne s'équilibrait pas (sur `lossy`, 9 trames manquantes) ; désormais sent = received + pertes accès + lost_mesh, égal à la trace. Ajouté au rapport et à la CLI.
- TLS : le test vérifie qu'un client sans confiance dans le certificat échoue et qu'un client en clair n'obtient jamais de 200. Redémarrage : déjà testé (runs terminés relus, runs en file marqués `failed`).
- Étape 3 (`web/`) : non commencée. Choix de l'auteur : commencer par le contrat d'API du panneau d'étude.
- Contrat du panneau d'étude (brouillon, `docs/STUDY_PANEL_SPEC.md` §7) : `python/lsim/study_contract.py`, schémas `schemas/api/study-draft/` (8 fichiers, séparés de `v1`). Règles portées par les types : clés uniquement « ****** », dépôt d'exercice sans résultat, catalogue sans critères ni solution, tailles bornées. Aucune route servie. Tests : `python/tests/test_study_contract.py`.

### Limites mesh et RX2 corrigées
- RX2 modélisée (repli) : une descente qui ne peut partir en RX1 (passerelle occupée au-delà de la fenêtre RX1) tente RX2, ouverte 1 s après RX1 (fin + 2 s ; join : +6 s), fenêtre de 1 s, même passerelle, SF `rx2_sf` du plan régional (12 en EU868). `rx2_sf = 0` désactive le repli. Une émission du dispositif pendant RX2 la rend perdue, et la sensibilité reste finale. Fréquence RX2 non modélisée (le repli garde la fréquence RX1).
- **Changement de résultats par défaut** : des descentes autrefois `GatewayBusy` sont désormais servies en RX2 (`DownlinkRecord.rx_window = 2`, départ entre t_open + 1 s et t_open + 2 s). Champs ajoutés en fin de struct : `lsim_downlink_rule.rx2_sf`, `lsim_downlink_record.rx_window`. La trace API v1 ne porte pas `rx_window` : l'instant de départ le révèle.
- Un scénario dont les régions ont des RX2 de SF différents est refusé (un seul débit de repli par scénario).
- Passe jointe : montant et descente partagent une seule passe mesh (`lsim.mesh_pass.mesh_pass`, `forward_frames` avec destination par trame). Ils partagent donc le temps d'antenne, la suppression des doublons et l'attente. Les descentes vers des relais différents se disputent désormais le mesh. La charge par relais est comptée une fois, sur le journal complet.
- Point fixe : sur (départs au plus tôt des descentes, délai frontière de chaque uplink), par message. Cap inchangé à 64.
- Natif : `lsim_mesh_forward_routed_log` (destination par trame) ; `lsim_mesh_forward[_log]` reste un wrapper aux résultats identiques.
- Enveloppe mesh : 14 o (montant) et 15 o (descente) confirmés par la documentation ChirpStack (MHDR, métadonnées, relay ID, MIC). Non vérifiés sur un relais physique. La taille de trame relayée par défaut (32 o) reste une hypothèse.
- Limite trouvée : une trame mesh est bornée à 255 o. Une descente de plus de 227 o (PHY 13 + charge + enveloppe 15) ou une charge montante relayée de plus de 228 o (13 + charge + enveloppe 14) est refusée : 422 `validation_error` à la création d'un run (champ `protocol.downlink_payload_bytes` ou `scenario`), et `ValueError` dans `build_multi_trace` pour les appelants hors API. Montant contrôlé seulement si un relais achemine et si `frame_size` vaut `device`.
- Tests : `python/tests/test_rx2_fallback.py` (repli avec `dl_ready_ns`, désactivation, validation du SF, SF issu du plan), `test_mesh_trace.py` (passe jointe, descente perdue sans airtime, départ non avant le premier saut). Suite : 1359 passés, 1 ignoré.

### Descentes et charge par relais sur mesh
- Moteur natif (`simulate_uplinks_multi_downlinks`) : paramètre optionnel `dl_ready_ns` (départ au plus tôt de chaque descente, par émission ; `kDownlinkNever` pour une descente jamais acheminée). API C : `lsim_simulate_uplinks_multi_dl` prend `dl_ready_ns` et `ready_count` en fin de signature (NULL pour l'ancien comportement). `simulator.simulate_multi_downlinks(..., dl_ready_ns=...)`, `DL_READY_NEVER`.
- Descentes sur mesh (`lsim.mesh_pass.mesh_pass`, passe partagée avec le montant depuis la section ci-dessus) : chaque descente part de la frontière à l'arrivée de son uplink et est routée jusqu'au relais cible (graphe rooted au relais, une copie, 15 o d'enveloppe). Le relais la sert en RX1 après son arrivée. `join`, `confirmed_uplinks` et `downlink_every` acceptés en mesh (API et trace).
- Point fixe : la trace (passe moteur) et les arrivées mesh des descentes dépendent l'une de l'autre ; itération bornée (`MAX_MESH_RETURN_ITERATIONS` = 64, levée explicite au-delà). Hors mesh, une seule passe.
- Trace : événements `mesh_downlink_hop` (sauts descendants) ; issue `lost_mesh` d'une descente perdue sur le mesh (un saut `ns` → relais) ; issue `mesh_late` d'une `rx_window_missed` quand l'arrivée mesh dépasse la fenêtre RX1. Une descente d'un uplink non remis au LNS n'est pas émise. Airtime de réception : seules les descentes reçues (`_DELIVERED_DOWNLINK_OUTCOMES`) comptent.
- Charge mesh par relais : `gateways[].mesh_transmissions`, `mesh_busy_ns`, `mesh_lost_collision`, `mesh_lost_half_duplex`, `mesh_suppressed` (uplink et descente additionnés, comptés sur l'émetteur). Absents pour les passerelles sans mesh.
- Les deux limites documentées ici (RX2 et passe jointe) sont corrigées dans la section « Limites mesh et RX2 corrigées » ci-dessus.
- Contrat : `EventKind` += `mesh_downlink_hop` ; `HopOutcome` += `lost_mesh` ; `GatewayReportOut` += 5 champs optionnels. Schémas régénérés. Tests : `python/tests/test_mesh_trace.py` (descentes par saut, concordance de charge avec le journal, point fixe déterministe, descente perdue), `test_api_server.py` (descentes acceptées, champs par relais).

### Mesh par saut dans la trace API

- `lsim.mesh_pass.mesh_pass` : passe mesh extraite de `run_scenario` et partagée avec la trace (`build_multi_trace`). Sur `examples/mesh_relais_quartier.yaml`, totaux, résumé mesh et compteurs par dispositif sont identiques à la version précédente.
- Natif : `lsim_mesh_forward_log` (et `mesh::forward` avec journal optionnel) renvoie chaque émission mesh avec son saut prévu, son issue et ses instants ; tampon borné, taille requise renvoyée si trop petit (statut 810, réessai côté Python).
- Trace : événements `mesh_hop` ; issue `lost_mesh` pour les trames décodées non remises ; champs optionnels `lost_mesh` (totaux, par dispositif). Absents hors mesh.
- API v1 : `mesh` accepté ; les refus `join`, `confirmed_uplinks` et `downlink_every` en mesh ont été levés (voir « Descentes et charge par relais sur mesh »). Schémas régénérés (`trace_event`, `trace_page`, `run_summary`, `device_page`).
- Tests : `python/tests/test_mesh_trace.py` (concordance avec `run_scenario`, journal natif, variante avec pertes mesh), `test_mesh.py` (journal, invariants, réessai du tampon), `test_api_server.py` (run mesh réel, descentes acceptées).

### Join en multi-passerelles

- Moteur natif multi (`core/src/engine.cpp`, `simulate_uplinks_multi_downlinks`) : règle `join` (`MultiDownlinkRule`), join-request décodée -> join-accept à fin + 5 s par la meilleure passerelle, 17 octets. API C : `lsim_downlink_rule.join`, `lsim_downlink_record.join`, `lsim_multi_tx_record.join_request` (champs ajoutés en fin de structure).
- Placement des descendantes : première place libre à partir de l'ouverture RX1 (au lieu d'un `busy_until`), nécessaire car un join-accept s'ouvre plus tard qu'un downlink de données créé après lui. Sans join, le placement natif est identique à la version précédente (comparaison bit à bit des descentes). Les empreintes de trace changent pour les runs à charge confirmée, à cause du libellé `data_ack` ci-dessous, et non à cause du placement.
- `lsim.trace_events.build_multi_trace` : événements `join_request` et `join_accept` ; libellé `data_ack` des charges sur uplink confirmé (comme le mono) ; `decoded_mask` transmis au wrapper des descendantes.
- L'API accepte `protocol.join` en multi ; seul le mesh reste refusé.
- Tests : `python/tests/test_multi_join.py` (mono = multi sans contention, invariants du join, aucun chevauchement de descendantes).
- Mono aligné sur le multi : une join-request est répétée tant que le join-accept n'est pas reçu (avant, seule la première émission était une join-request). Le point fixe des jointures est itéré avec les émissions passerelle (`_plan` dans `trace_events`). Changement de comportement mono : les traces avec `join` changent quand une join-request est perdue.

### Serveur d'API v1, sensibilité du shadowing mesh
- Serveur de l'API v1 (`python/lsim/api_server.py`, bibliothèque standard) : santé, régions, validation, runs (file bornée, un calcul à la fois), état, résumé, dispositifs et événements paginés, annulation et suppression. Jetons d'accès : seul le SHA-256 est stocké, comparaison en temps constant, révocation et expiration ; `python -m lsim.api_server issue-token` affiche le jeton une fois. Runs persistés (SQLite, WAL) ; limite de débit par jeton (429 `rate_limited`) ; TLS optionnel, refus de démarrer en clair hors boucle locale. Passerelles multiples, environnement à obstacles et relief (catalogue serveur `--terrain-catalog`, identifiant `terrain_id`, jamais de chemin client) pris en charge ; énergie avec protocole ou multi-passerelles calculée depuis la trace (airtime des descendantes reçues) ; mesh : descentes acheminées depuis la version suivante (voir « Descentes et charge par relais sur mesh ») ; join en multi-passerelles calculé (join-request répétée tant que le join-accept n'est pas reçu ; même règle que le mono). Schémas : `run_summary` accepte `gateways` (multi) à la place de `gateway` (rupture d'additivité, documentée), `terrain_list` ajouté, `rate_limited` ajouté à `problem`. Génération des schémas testée (reproductible). Tests : `python/tests/test_api_server.py`, `test_api_contract.py`, `test_energy_protocol.py`.
- Trace multi-passerelles (`lsim.trace_events.build_multi_trace`) : mêmes totaux et même calcul natif (`simulate_multi_downlinks`) que les événements. Correction d'un défaut de cohérence : avec downlinks actifs, les totaux de `run_scenario` ne concordaient pas avec la trace (730 reçus contre 560 sur 3000 émissions) ; le serveur utilise désormais la trace et vérifie la somme par dispositif.
- Shadowing mesh, explication et test de sensibilité : sur `examples/mesh_relais_quartier.yaml`, la frontière entend toutes les trames en direct (`direct == frames`, `via_mesh == 0`), donc le mesh ne transporte que des copies redondantes et le shadowing ne change pas la livraison. Test de sensibilité : frontière seule à portée (tx −14 dBm), 150 dispositifs, σ = 8 dB et graine 7 font passer la livraison de 570 à 504 trames sur 570. Tests : `python/tests/test_run_mesh.py`.

### Shadowing mesh, join-accept après rejoin, RAK5148 et RAK7391
- Shadowing sur le mesh : `mesh.shadowing_sigma_db` (0 à 30 dB, 0 par défaut). Un tirage log-normal par paire de passerelles, réciproque (les deux sens reçoivent la même valeur), graine `propagation.shadowing_seed`, tirage natif `lsim_shadowing_sample_db` (même fonction que le cœur de simulation). Tests : réciprocité, déterminisme, σ = 0 identique, bornes (`python/tests/test_mesh.py`, `test_run_mesh.py`). Le shadowing de l'accès reste séparé : le mesh n'hérite pas de `propagation.shadowing_sigma_db`.
- Join-accept après rejoin (LoRaWAN 1.1 §6.2.4.4, tableaux 13 et 14) : `JoinServer.accept_rejoin` produit le join-accept dans la même transaction que la vérification du rejoin. Chiffrement JSEncKey, MIC JSIntKey avec JoinReqType 0x00, 0x01 ou 0x02, RJcount à la place de DevNonce pour la dérivation des clés de session. Le blocage précédent (« DevNonce non défini ») est levé par §6.2.4.4 : RJcount remplace DevNonce. Cœur C++ : `encode_rejoin_join_accept` / `decode_rejoin_join_accept` (API C `lsim_*_rejoin_join_accept`), liaisons `lsim.security`. Pour les rejoins type 0 et 2, le message ne porte pas le JoinEUI : il doit être fourni par le provisionnement (`DeviceKeys.join_eui`), sinon le join-accept est refusé. Ancien contexte conservé (§6.2.4) : le nouveau est mis en attente (table `pending_sessions`) et devient la session au premier uplink valide qui l'utilise, dans la même transaction ; l'ancien disparaît alors. Pendant l'attente, l'uplink sur l'ancien contexte ne reçoit ni la file de downlinks ni de commande MAC (ACK seul si confirmé) ; la file part au premier uplink valide du nouveau contexte. Les commandes MAC en attente sont effacées à l'émission du join-accept pour les rejoins types 0 et 1 (avant `on_join`, car `on_join` peut en enfiler de nouvelles) ; elles sont conservées pour le type 2, qui garde les paramètres radio. Un rejet après la promotion, dans la même transaction, annule la promotion : l'ancien contexte, la file et le contexte en attente restent intacts. Écart par rapport au plan initial : l'effacement se fait à l'émission du join-accept et non à la promotion. Un MIC faux n'y change rien ; un second rejoin remplace le contexte en attente ; une join-request complète supprime tout. L'état survit au redémarrage. Tests : `python/tests/test_uplink.py`. Tests : aller-retour device/serveur pour les types 0, 1, 2 ; JoinReqType et RJcount liés au MIC ; rejeu sans changement d'état ; MIC faux sans sortie ; JoinEUI absent refusé ; RJcount0 remis à zéro (`python/tests/test_join_server.py`, `core/tests/test_join.cpp`).
- Catalogue, RAK5148 : fiche technique fournie (9 pages) et one-pager. Tx max 27 dBm ; sensibilité typique −132 dBm (SF12 / 203 kHz) et −110 dBm (SF7 / 1625 kHz) ; 3,3 V (3,0 à 3,6 V) ; 810 mA en émission, 179 mA en réception ; −40 à +85 °C ; modèles RAK5148-211 (USB, reset MCU) et RAK5148-221 (USB, GPS ZOE-M8Q, reset MCU). Le nombre de canaux d'accès n'est pas publié : `max_channels` reste vide. La table basse consommation Semtech donne −106 dBm à SF7 / 1625 kHz au lieu de −110 dBm : le mesh garde la table, plus conservatrice. L'ancienne source (page RAK en 404) est remplacée par la fiche fournie.
- Catalogue, RAK7391 (WisGate Connect) : hôte Raspberry Pi CM4 avec 3 emplacements mini-PCIe, 1 M.2 B-key, 2 WisBlock IO, 10 à 28 V DC. La brochure ne publie aucun paramètre radio : le profil n'en porte aucun. Un hôte (`is_host`) est refusé comme passerelle radio (« hôte sans radio publiée »), tant qu'un module n'est pas déclaré.
- Documentation : `docs/USAGE.md` (5sexies), `docs/ROADMAP.md`. Schémas `schemas/api/v1/` régénérés depuis la racine.

### Relais mesh et passerelles multiples
- Relais mesh 2,4 GHz (style ChirpStack Gateway Mesh) : moteur C++ `core/src/mesh.cpp`, API C `lsim_mesh_*` (statuts 800..849). Routes vers la frontière, au plus 8 sauts ; liens réciproques ; demi-duplex et collisions avec capture ; sensibilité SX1280 (tableau basse consommation, CR 4/5, DS Rev 3.0 table 6-1) ; airtime AN1200.13 (vérifié contre le cœur natif à 125 kHz). `lsim.mesh` reste l'interface Python.
- Catalogue : RAK5148 (module 2,4 GHz, mesh) ajouté ; RAK7249 reste sans mesh (radio mesh non documentée).
- Scénario : `gateways` (liste nommée, profil du catalogue, `mesh: true` pour les relais) et `mesh` (frontière, SF, BW, CR, capture, sauts, suppression, attente, taille de trame). `lsim run` exécute le multi-passerelles ; avec mesh, une trame est remise au LNS si une copie atteint la frontière. Bilan `MeshSummary` et lignes dans le rapport.
- Suppression des doublons par identifiant de trame (`suppress_duplicates`, vrai par défaut) : un relais ne transmet une trame qu'une fois et renonce s'il entend un autre relais la transmettre avant son départ. Test de chevauchement : une émission au lieu de deux (`core/tests/test_mesh.cpp`, `python/tests/test_mesh.py`).
- Attente de relais déterministe (`relay_backoff_airtimes`, 4 temps d'antenne par défaut) : sans elle, deux relais qui reçoivent la même trame au même instant partent ensemble et la suppression ne se déclenche jamais (0 copie supprimée sur l'exemple). Sur `examples/mesh_relais_quartier.yaml` (SF12/203 kHz, taille réelle), sans attente : 0 copie supprimée, 5520 émissions, 2740 collisions ; avec attente de 4 T : 543 copies supprimées, 4977 émissions, 2159 collisions. La livraison ne change pas (2830 à 2831 trames) : la frontière décode déjà la plupart des trames.
- Taille de trame corrigée : l'hypothèse de 32 o fixes est remplacée par la trame LoRaWAN réelle du dispositif plus l'enveloppe mesh de 14 o en montant (documentation RAK et ChirpStack ; 15 o en descendant). `frame_size: fixed` garde l'ancien comportement. Le temps d'antenne se calcule par trame (`lsim_mesh_frame.payload_bytes`).
- Descente sur le mesh : pour chaque trame remise, fenêtre atteignable (RX1, RX2, hors fenêtres), par le chemin inverse et un temps d'antenne mesh par saut (borne optimiste : pas de collision au retour). Constat sur l'exemple : à SF12/203 kHz, un saut d'acquittement dure 1,01 s, donc aucune descente relayée n'atteint RX1 (1 s) ni RX2 (2 s) : 21 trames sur 21 hors fenêtres. À SF9/203 kHz (139 ms par saut), aucune. Le choix de bande et de SF mesh conditionne donc les acquittements.
- Obstacles et relief sur le mesh : perte de propagation entre passerelles calculée par le natif (`lsim_env_path_loss_matrix`), antennes à hauteur passerelle. Un mur de 60 dB entre frontière et relais supprime la route (test d'intégration).
- GeoJSON multi-passerelles : une passerelle par entrée, une couverture par passerelle et par groupe (`gateway` dans les propriétés). Le refus est supprimé.
- Charge par passerelle en multi : trames audibles (RSSI ≥ sensibilité), union des intervalles, simultanéité maximale (`lsim_gateway_rx_stats` : quatre champs ajoutés en fin de structure). Une passerelle a `busy_ns`, `peak_concurrent`, `utilization`. Sur l'exemple, toutes les passerelles entendent les 3000 trames (portée de 3,5 km) : la charge est donc identique entre elles.
- Défaut mesh : SF9 / 203 kHz (décision). À SF12 / 203 kHz, un saut d'acquittement dure 1,01 s : aucune descente relayée ne tient dans RX1 ni RX2. Le bloc `mesh` (SF, bande, CR) reste réglable par scénario ; le choix automatique par profil d'équipement n'est pas implémenté. Le bloc `mesh` n'existait pas sur `main` : ce changement de défaut n'affecte aucun contrat publié.
- Limites restantes : le shadowing n'est pas appliqué au mesh ; le retour de descente n'a pas de collision ni de file d'attente.
- Constat sur la saturation : la frontière décode 2810 trames sur 2840 directement ; le mesh n'en apporte que 21. Les 4977 émissions mesh et les 1840 collisions de relais servent donc surtout à des copies redondantes.
- Moteur multi-passerelles : `decoded_mask` par émission (bit g : passerelle g a décodé), ajouté en fin de `lsim_multi_tx_record`.

### Correctif : optimisation bas débit
- `RadioConfig.low_data_rate_optimize` vaut `None` par défaut : la règle LoRaWAN s'applique (Tsym > 16 ms, donc SF11 et SF12 à 125 kHz). Avant, la valeur `False` sous-estimait la durée d'émission de ces configurations dans l'API directe `time_on_air_ns`. Le moteur de simulation calculait déjà l'optimisation à partir du SF et de la bande : aucun résultat publié de simulation n'est modifié.

### Contrat d'API et traces
- Trace par transmission exportée par le cœur natif (`lsim_simulate_uplinks_trace`) : début, fin, SF, RSSI, issue. Mêmes compteurs que l'appel sans trace ; borne 200 000 émissions (statut 309).
- Événements du protocole dérivés de la trace (`lsim.trace_events`) : join-request / join-accept (fin + 5 s), ACK et downlink (fin + 1 s, un par uplink accepté), `rx_window_missed` en demi-duplex. Même `t_ns` que le moteur ; options `join`, `confirmed_uplinks`, `downlink_every`.
- Réception du downlink par le dispositif (réciprocité, puissance passerelle 14 dBm par défaut, sensibilité RX1 du plan) : une perte donne l'issue `lost_sensitivity`.
- Moteur multi-passerelles (phase 2, premier incrément) : `simulate_uplinks_multi` (C++, `lsim_simulate_uplinks_multi`, `simulate_uplinks_multi` en Python). Chaque passerelle reçoit indépendamment (sensibilité et collision à son RSSI) ; le serveur déduplique (une livraison par trame, copies comptées). Downlinks multi-passerelles (`simulate_uplinks_multi_downlinks`, `lsim_simulate_uplinks_multi_dl`, `simulate_multi_downlinks`) : chaque uplink décodé reçoit son ACK ou sa charge de la meilleure passerelle décodeuse ; chaque passerelle sérialise ses downlinks et ne décode pas pendant les siens. Calcul exact dans l'ordre de fin des émissions (sans itération : une itération en point fixe oscillait sur certains scénarios). Pas encore d'usage dans `run` ni dans le contrat d'API, ni de relais mesh.
- Passerelle demi-duplex : un downlink à la fois (sérialisation, perte si hors fenêtre RX1) ; uplinks reçus pendant une émission passerelle perdus (`lost_gateway_busy`, nouveau compteur C et Python). Calcul en point fixe avec le moteur.
- MNT libre : `scripts/fetch_copernicus_dem.py` (Copernicus DEM GLO-30, licence Copernicus) produit un CSV UTM à 30 m pour `terrain` ; cache `data/cache/` exclu du dépôt.
- Contrat v1 : `docs/API_CONTRACT.md`, schémas `schemas/api/v1/`. Authentification par jeton décrite (SHA-256 au repos, 401 `unauthorized`).

### Radio et régions
- Sensibilités SX1276 Rev. 4 pour 125, 250 et 500 kHz (SF7 à SF12), alignées sur le datasheet.
- Atténuation par matériau (UIT-R P.2040-4) : pertes de traversée, avec avertissement hors plage.
- Régions : EU868 (ETSI EN 300 220-2, RP002), AS923 (Japon, partiel), RU864, KR920 (partiel).
- US915 et AU915 : sous-bandes 1 à 8 (`sub_band` dans les groupes ; `lsim serve --sub-band`), règle LinkADRReq ChMaskCntl 0 à 7 (`lsim.channel_mask`). Le serveur envoie un LinkADRReq de sous-bande à chaque jointure, renvoyé jusqu'à acquittement (8 essais) ; la passerelle Basic Station annonce la sous-bande (canal 500 kHz sur radio_1).

- LR-FHSS non géré (décision) : uplinks US915 DR5/DR6 et modulation `LRFHSS` refusés, aucun débit LR-FHSS dans AU915 (`docs/USAGE.md` 5quater, `python/tests/test_lrfhss_unsupported.py`).

### LoRaWAN 1.1
- Codec de trame, crypto (mbedTLS), dérivation de clés 1.1, trame sécurisée (MIC avant déchiffrement).
- Jointure, rejoin types 0/1/2, garde anti-rejeu, rekey, commandes MAC (codec et API).
- Classe B (ping slots, limites documentées) et classe C (blocage RX2).

### Simulation et sorties
- Moteur d'événements déterministe, collisions et capture, temps d'antenne, charge passerelle.
- Scénarios YAML validés strictement, relief et obstacles, carte GeoJSON et MNT.
- Rapports PDF et Excel, export Parquet, notebook d'analyse.

### Énergie
- Deux profils au choix : `rak4631` et `sx1262-stm32l072` (`--energy-profile`).
- Classe A : fenêtres RX1/RX2 au préambule (durée configurable).
- Profil choisi dans le scénario YAML (`energy.profile`) ; l'option CLI le remplace. Absent du hash si non renseigné.

### Serveur de jointure
- Registre de jointure durable, partageable entre processus (SQLite WAL, transactions `BEGIN IMMEDIATE`, état protégé par MIC).
- Serveur de jointure : join-request acceptée et join-accept produit en une transaction ; rejoin vérifié sans join-accept généré (la spec 1.1 ne définit pas DevNonce ni JoinEUI pour ce join-accept).
- Périmètre : fichier SQLite local, un seul hôte (pas de NFS ni SMB).

### Passerelles
- Codec Semtech UDP (GWMP v2) et serveur UDP : join-accept livré à la passerelle en PULL_RESP (fenêtre JOIN_ACCEPT_DELAY1 = 5 s), routes et traitements bornés.
- Commande `lsim serve` (`--transport udp` par défaut) ; Basic Station : `--transport basicstation`, WebSocket (RFC 6455, sans dépendance), TLS 1.2+ optionnel.
- Trames de données : compteur 32 bits, rejeu refusé, MIC avec TxDr/TxCh, ACK downlink en RX1 à +1 s, retransmission confirmée ré-acquittée, file de downlinks (`lsim downlink`), session créée avec la jointure.
- Plan RU864 (`--region RU864`, `python/lsim/ru864.py`) : canaux 868,9 / 869,1 MHz, DR0-DR6, RX1 même canal et même débit, RX2 869,1 MHz DR0, charges N EU868.
- Plan IN865 (`--region IN865`, `python/lsim/in865.py`) : canaux 865,0625 / 865,4025 / 865,985 MHz, DR0-DR5, RX1 même canal et même débit, RX2 866,550 MHz DR2. Charges N prudentes.
- Plan KR920 (`--region KR920`, `python/lsim/kr920.py`) : canaux 922,1 / 922,3 / 922,5 MHz, DR0-DR5, RX1 même canal et même débit, RX2 921,9 MHz DR0. Charges N prudentes (tableau 62 de RP002-1.0.2 non lu).
- Plan AS923 (`--region AS923`, `python/lsim/as923.py`) : canaux 923,2 et 923,4 MHz, DR0-DR6, RX1 même canal et même débit, RX2 923,2 MHz DR2, charges N 51/115/222. DR7 (FSK) et DownLinkDwellTime non gérés.
- Plans régionaux EU868, US915 et AU915 (`--region`) : canaux, débits, RX1 (modulo 8 pour US915 et AU915), charges maximales, DLSettings.
- Chiffrement au repos des sessions, compteurs et charges en file (AES-256-GCM, clé `LSIM_DATA_KEY`, extra `serve` = `cryptography`).
- Base SQLite créée en mode 0600 ; refus si elle est accessible à d'autres utilisateurs.
- DevEUI dans `keys.json` et `lsim downlink --dev-eui` : ordre d'affichage TTN (conversion interne).
- Basic Station : `hwspec` `sx1301/N` (seul préfixe accepté par Station), `JoinEui` à `null`
  (pas de filtre), conformité vérifiée sur les vecteurs officiels `selftest_lora.c`.

### Données
- Paramètres de propagation indoor (Université de Siegen, CC BY 4.0) déposés dans
  `python/lsim/reference/`, sans les données brutes.

### Limites connues
- Pas de calibrage terrain ; pas de validation de pénétration sur mesures.
- Rx énergie 250/500 kHz non publié : estimation signalée.
- Pas de multi-utilisateurs, ni de fournisseur de tuiles sous contrat.
