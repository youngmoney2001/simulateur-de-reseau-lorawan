# Atelier 3D — points à peaufiner ou à créer

Objet de ce document : répondre à « selon l'objectif du projet, liste les points à peaufiner
ou à créer ». Il ne s'agit pas d'une liste de souhaits mais d'un **recensement d'écarts mesurés**
entre l'objectif énoncé et l'état du dépôt. Chaque point porte la mesure qui le fonde ; quand une
mesure manque, le point est marqué « à vérifier » et n'est pas présenté comme acquis.

## L'objectif, rappelé comme référence

> « je choisie la zone où je veux tester mon reseau, puis comme dans cisco j'ai une carte 3D
> centree sur ce lieu qui est devant moi et mes equipements disponible. je peux poster un
> equipement par drag and drop ou definir directement les coordonnees geometrique du lieux ou je
> veux le placer, je peux les parametrer comme de vrai equipements lorawan, **avec des fenetres
> de cnfiguration propre, illustrees et conforme pour chaque equipement** une fois la
> configuration finie je lance la simulation et je visualise le comportement du reseau avec
> toutes les infos possible. »

Les six étapes de ce workflow sont fermées (voir `docs/ATELIER_3D_CONCEPTION.md` §1). Ce qui suit
concerne la **profondeur** de chaque étape, pas leur existence.

---

## 1. ~~La fenêtre passerelle est presque vide~~ — **arbitrage tranché, livré**

**C'est l'écart le plus grave, et il est chiffrable.**

Ce que la fenêtre passerelle affiche réellement (`renderGatewayConfig`, `web/src/studio/main.js`) :

```
Rôle : Passerelle frontière
Nom d'hôte : <hostname>
Région : <region>
État : configuré / non configuré
« La configuration des passerelles se fait en ligne de commande, comme sur un
  équipement réel. Ouvrez l'onglet CLI. »
```

Ce que le CLI d'étude sait régler (`COMMANDS`, `python/lsim/study_cli.py`) — et que rien
d'autre ne sait régler :

`region` · `sub-band` · `tx-power` · `antenna` · `frequency` · `shutdown` ·
`mode relay` · `bandwidth` · `max-hops` · `spreading-factor` · `hostname`

Vérifié par absence : `grep -rn "sub_band\|bandwidth\|max-hops" web/src/` ne renvoie **rien**. Ces
réglages n'ont donc **aucun** chemin d'accès hors du CLI.

### Conséquence directe : 4 exercices sur 7 ne se terminent pas dans l'atelier

| Exercice | Critère | Réglage requis | Accessible hors CLI ? |
|---|---|---|---|
| `us915-sous-bande` | sous-bande 2 | `sub-band` | **non** |
| `au915-sous-bande` | sous-bande 5 | `sub-band` | **non** |
| `relais-deux-sauts` | mode relay + sauts | `mode relay`, `max-hops` | **non** |
| `relais-bande-large` | bande 1625 kHz | `mode relay`, `bandwidth` | **non** |

Autrement dit : **la majorité du contenu pédagogique envoie l'apprenant au clavier** pour des
réglages que l'objectif place explicitement « dans des fenêtres de configuration propres,
illustrées et conformes pour chaque équipement ».

### Ce point est un arbitrage, pas un défaut

Le choix « consoles = CLI, capteurs = formulaire » est défendable et assume une filiation CCNA :
un vrai équipement réseau se configure en console, un capteur LoRaWAN ne se configure pas du
tout en ligne de commande. Le problème n'est pas ce choix, c'est qu'il n'a **jamais été confronté
au contenu** : les exercices ont été écrits du côté CLI, l'atelier 3D du côté fenêtres, et les
deux ne se rencontrent pas.

Trois issues, à trancher :

1. **Ouvrir la fenêtre passerelle** — lui donner les onze réglages, avec les mêmes illustrations
   SVG que les capteurs. Le plus fidèle à l'objectif ; le plus de travail.
2. **Assumer le CLI** et le dire dans l'interface : l'exercice annonce « ouvrez l'onglet CLI »,
   la fenêtre passerelle cesse de faire croire qu'elle configure.
3. **Réduire le contenu** aux exercices qui se terminent dans l'atelier (3 sur 7 aujourd'hui).

### Décision : ouvrir la fenêtre, progressivement

Arbitrage rendu : **ouvrir la fenêtre**, exposer d'abord ce que les exercices réclament, garder
le reste au CLI **avec un renvoi visible**, et **ne pas réduire les exercices** — adapter
l'interface aux quatre qui doivent se terminer dans l'atelier.

Ce que la fenêtre expose désormais, en deux sections :

| Section | Réglages |
|---|---|
| **Radio LoRa** | plan régional, sous-bande, puissance TX |
| **Relais (mesh)** | mode, sauts max, bande passante |

Ce qui reste au CLI, et que le bloc « Réglages avancés » **nomme** : gain d'antenne, fréquence,
facteur d'étalement du mesh, arrêt d'interface.

**La fenêtre et le CLI écrivent la même configuration.** Ce n'est pas un état parallèle : ce que
la fenêtre pose apparaît dans `show running-config`, et réciproquement. Les deux sens sont
testés. Sans cette propriété, un même équipement aurait deux vérités selon le chemin emprunté.

Deux détails qui comptent plus que leur taille :

- **La sous-bande est désactivée hors US915 et AU915, avec la raison écrite à côté.** Un champ
  muet ou grisé sans explication est le genre de silence qui fait perdre une heure.
- **Un champ vide emporte « ne pas toucher ».** La fenêtre n'affiche pas l'antenne ; elle ne doit
  donc pas pouvoir l'effacer.

La région a été exposée en plus de la demande, parce que deux des quatre exercices l'exigent :
une sous-bande sans plan régional n'a pas de sens, et le CLI refuse déjà cette combinaison.

### Vérifié, et comment

Le test décisif n'est pas que la fenêtre enregistre, c'est que **les quatre exercices passent
leurs critères de configuration sans ouvrir la console** — et que `us915-sous-bande` atteigne
30/30 une fois le run lié. C'était l'écart à fermer ; il est fermé et prouvé par l'évaluation
elle-même, pas par une assertion sur un formulaire.

Trois échecs de CI en route, tous instructifs :

1. L'étape e2e visait un équipement disparu : je l'avais placée avant la suppression de la
   session, sans voir que l'étape « exercice » démarre une **session neuve**. Après elle,
   `gw-nord` n'existe plus. Le sélecteur était juste, l'emplacement ne l'était pas.
2. `setValue` pose `.value` en JS sans déclencher `change` : la sous-bande restait désactivée.
   Ce n'est pas un défaut d'interface — un vrai geste sur une liste déroulante déclenche
   l'événement — mais le test doit employer `page.select`.
3. Le message « Réglages enregistrés. » était frère du formulaire au lieu d'en être le dernier
   enfant. J'avais réinventé une disposition au lieu de recopier celle du capteur.

Un quatrième défaut, trouvé en examinant le deuxième, que la CI n'avait pas encore rencontré :
quitter un plan à sous-bandes l'efface côté serveur, mais la fenêtre continuait d'afficher « 2 ».
Afficher un réglage qui n'est plus fait croire à un enregistrement qui n'a pas eu lieu.

**Mesure de la fenêtre** : l'audit balaie les onglets d'une fenêtre d'équipement, mais n'ouvrait
que celle d'un capteur — le formulaire passerelle n'était donc jamais passé au gabarit, et « la
CI est verte » n'aurait voulu dire que « aucune assertion n'a échoué ». Un état
« passerelle · Config » a été ajouté. Résultat : **430 × 517 px, 0 problème, aucun défilement
horizontal**, à 1400 px comme à 900 px. 517 px est la hauteur naturelle du contenu, sous la
borne CSS de 760 px : le formulaire tient sans être rogné.

Ces trois chiffres sont désormais **relus dans le dépôt**, pas répétés de mémoire. L'audit est
`continue-on-error` et son rapport ne vivait que dans le journal du runner, hébergé hors de
portée de l'outillage : illisible par une machine et perdu à chaque exécution. Il est écrit
dans `docs/audits/mise-en-page.md` et rapatrié dans la branche. Vérifié à la lecture :
**0 problème sur 21 états**, et `device-win.active` à `430×517` aux deux largeurs.

Un champ que la fenêtre n'affiche pas ne doit pas être effacé pour autant qu'elle poste. Le test
client vérifiait que `validateGateway` n'émet pas la clé d'un champ vide ; il manquait la moitié
serveur, qui est la seule qui compte : régler la région depuis la fenêtre détruirait sinon
l'antenne posée au clavier, sans que rien ne le montre puisque l'antenne n'est pas affichée.
Vérifié par `show running-config` — et non par `/topology`, dont l'état n'expose que les six
champs de la fenêtre et ne dirait donc rien d'un réglage qu'elle ne montre pas.

---

## 2. Le contenu : 7 exercices, et un moteur qui en simule bien plus

Mesuré : **7 exercices**, couvrant **9 notions** (`region`, `serveur`, `mode`, `sauts`, `lien`,
`sous-bande`, `réception`, `latence`, `bande`) et **3 scénarios d'exemple**
(`quartier_sf9`, `quartier_relief_sf9`, `mesh_relais_quartier`).

Le moteur compte **75 modules Python**, dont plusieurs simulent des mécanismes qu'**aucun**
exercice n'aborde :

| Module | Mécanisme | Couvert par un exercice ? |
|---|---|---|
| `adr.py` | Adaptation du débit (ADR) | **non** |
| `join.py`, `rejoin.py` | Activation OTAA / réactivation | **non** |
| `retransmissions.py` | Trames confirmées et retransmissions | **non** |
| `class_b.py` | Classe B (fenêtres de réception) | **non** |
| `channel_mask.py` | Masque de canaux | **non** |
| `energy.py`, `energy_report.py` | Profils d'énergie | **non** |
| `rekey.py` | Renouvellement de clés | **non** |
| `gateway_sensitivity.py`, `rf.py` | Chaîne RF, sensibilité | **non** |

ADR, join et retransmissions sont les trois qu'un apprentissage de LoRaWAN ne peut pas ignorer —
ce sont aussi les trois qui expliquent le mieux un PDR dégradé dans la visualisation. Un
exercice « pourquoi ce capteur est-il passé de SF7 à SF10 ? » relierait directement le mécanisme
au chiffre affiché.

À comparer aux centaines d'activités livrées avec Packet Tracer. L'écart est structurel, il ne se
comble pas en une tranche : **c'est un chantier de fond**. L'arbitrage du §1 est rendu, donc il
peut commencer — et la première mesure à prendre n'était pas « combien d'exercices manquent »,
mais « lesquels pourraient être résolus dans l'atelier ».

### Les trois qui comptent ne sont pas également atteignables — mesuré

§2 désignait ADR, join et retransmissions comme les trois mécanismes qu'un apprentissage de
LoRaWAN ne peut pas ignorer. Ils n'existent pas au même endroit, et surtout **ils ne sont pas
aussi accessibles les uns que les autres**. Trois scénarios réels, compilés depuis l'atelier,
soumis au validateur du schéma :

| Mécanisme | Bloc du scénario | Accepté sur un scénario d'atelier ? |
|---|---|---|
| Jointure OTAA | `retransmissions.join_requests_s` | **oui** |
| Trames confirmées et réémissions | `retransmissions.enabled` / `retries` | **oui** |
| ADR (LinkADRReq) | `mac.link_adr` | **non** — refusé |

**Pourquoi l'ADR est refusé, et c'est le fait à retenir** : `mac.link_adr` n'est admis qu'à
passerelle unique et sans mesh. Or `study_compile` émet **toujours** la liste `gateways`, y
compris quand la session n'a qu'une seule passerelle — vérifié : un scénario d'une passerelle et
d'un capteur porte `gateways: ['gw-seule']`. L'ADR est donc hors de portée de l'atelier **non
pas parce que le moteur ne le simule pas** (la boucle MAC complète existe : `adr_decision`,
`link_adr_req`, `link_adr_ans`, `apply`), mais parce que la forme du scénario que l'atelier
produit lui est interdite.

Le bloc `retransmissions`, lui, n'a pas cette contrainte : les deux mécanismes atteignables le
sont sur un scénario multi-passerelles.

### Ce que ça implique pour la suite

Un exercice s'écrit contre l'interface qui le résout — c'était la leçon du §1, et elle s'applique
ici deux fois plutôt qu'une. Ces réglages sont **au niveau du scénario**, pas de l'équipement : il
n'existe aujourd'hui aucune surface pour les poser. Le formulaire de simulation de l'atelier ne
porte qu'une graine et un bouton (`studio.html`, `#sim-form`), et `study_compile` n'émet ni
`mac` ni `retransmissions`.

Deux chantiers, d'ampleur très différente :

1. **Jointure et trames confirmées** : ouvrir une surface de réglage de scénario, la brancher sur
   `study_compile`, écrire les exercices. Mécanismes déjà simulés et déjà acceptés par le schéma.
2. **ADR** : exige un choix d'architecture. Ce n'est pas un complément du chantier 1, c'en est
   un autre.

### Décision : réutiliser la boucle validée, pas en inventer une

Deux voies, et la mesure tranche entre elles.

**Étendre l'ADR au multi-passerelles.** `simulate_multi_downlinks` — le chemin de calcul de
l'atelier — n'a **aucun** paramètre `mac` : la boucle MAC n'y existe pas. L'y ajouter ne serait
pas un branchement, ce serait écrire de la physique : l'ADR décide sur l'historique de SNR des
vingt dernières trames, et avec trois passerelles qui décodent la même trame, il faudrait décider
quel SNR compte — le meilleur ? la médiane ? par passerelle ? Aucune de ces réponses n'est dans
le moteur, et les inventer ferait passer une invention pour une simulation.

**Produire un scénario à passerelle unique.** La boucle fermée existe, elle est testée, et elle
n'accepte qu'**une** passerelle : `args.gateway = ctypes.pointer(c_gw)`, un seul `GatewayLoad` —
la contrainte est dans l'ABI, pas dans un validateur prudent. Vérifié à l'exécution : un
scénario mono avec `mac.link_adr` et un plan régional produit des `mac_request` portant
`outcome: 'LinkADRReq'`, et aucun sans. Le mécanisme tourne ; il manquait le chemin.

La décision suit : **on réutilise la boucle validée**. Une session peut donc produire deux
formes de scénario, et le choix est porté par la session, comme le relief :

| Session | Scénario | Ce qui marche |
|---|---|---|
| plusieurs passerelles, ou un relais | `gateways` | relais, latence, matrice des réceptions (§3) |
| une seule passerelle **et** ADR demandé | `gateway` + `mac` | boucle ADR, `LinkADRReq` |

**Le coût est réel et il est dit**, pas compensé : sur un run ADR, les liaisons radio du §3
disparaissent (`rx_matrix` n'est publié que sur `gateways`) et le relais ne peut pas être
simulé. C'est acceptable parce qu'à passerelle unique une matrice à une colonne ne dirait rien
de plus que le PDR — raison déjà écrite dans le contrat — et parce que l'ADR exige de toute
façon l'absence de mesh.

Deux conditions d'usage, chacune avec sa raison affichée, comme la sous-bande du §1 :
- **une seule passerelle** — sinon l'ADR est refusé par le schéma ;
- **un plan régional** — sans lui, `mac_loop.py` lève « LinkADR exige un plan régional ».
  Vérifié : un scénario ADR sans `region` échoue le run, il ne le dégrade pas silencieusement.

Ce que l'atelier doit montrer, et c'est le but de l'exercice : **le débit a changé, et pourquoi**.
La trace porte `mac_request` / `LinkADRReq` ; c'est cette trace que l'exercice interrogera, pas
une affirmation sur un formulaire.

### Ce qui est livré, et vérifié sur un serveur réel

Le chemin existe d'un bout à l'autre, et il a été exercé en HTTP, pas seulement en test :

| Étape | Mesuré |
|---|---|
| `POST /sessions/{sid}/adr` | le souhait est enregistré ; la topologie revient avec `adr_possible` et `adr_raison` |
| compilation | `gateway` + `mac` au lieu de `gateways`, avec la note de coût |
| run | ADR désactivé : 40 uplinks, rien d'autre. **ADR activé : 40 uplinks, 2 `downlink`, 2 `mac_request` `LinkADRReq`** — un par capteur |

La case vit dans le panneau de simulation, pas dans la fenêtre d'un équipement : l'ADR est une
décision du serveur de réseau, et elle change la forme du run entier. Elle est **grisée avec sa
 raison** quand la topologie ne le permet pas — la leçon du §1, appliquée une deuxième fois.

Le souhait est gardé même quand il n'est pas réalisable, et le statut annonce ce qui sera
**réellement** simulé plutôt que ce qui a été demandé : le serveur accepte de garder une
intention qu'il ne peut pas exécuter, et la répéter telle quelle laisserait croire à un run
qu'on n'aura pas.

Sept tests serveur, six tests web. Les libellés sont des fonctions pures (`adrMessage`,
`adrStatut`) : un réglage qui explique son refus mérite d'être vérifié, et cela se fait sans
navigateur.

### Montrer le débit que le serveur a laissé

La trace disait *que* le serveur a commandé ; elle ne disait pas *de SF12 à SF7*. Rien ne
montrait le changement, et la mesure a d'abord semblé dire qu'il n'existait pas : les sauts d'un
événement uplink portent `radios[dev].dr`, le DR **de départ**, figé pour tout le run, et un
`mac_request` ne porte que le nom de la commande. Le seul endroit où le changement se lit est le
SF du **dernier uplink**.

`DeviceRowOut` porte donc `final_spreading_factor`. Il est **absent** quand le run n'observe pas
la fin (voie multi-passerelles, sans enregistrements d'émission) plutôt que de recopier le SF de
départ : un champ absent vaut mieux qu'une valeur qui laisserait croire à une mesure.

L'atelier en fait un encadré, « Débit commandé par le serveur », qui ne s'ouvre que si le run a
observé une différence, et qui dit combien de dispositifs n'ont **pas** bougé — sans quoi trois
changements sur trente passeraient pour une décision générale.

#### Le bloc restait masqué : quatre causes, une seule visible à la fois

L'étape e2e qui vérifie ce bloc a échoué plusieurs fois, et **la cause a changé à chaque
mesure** — c'est la leçon à retenir, plus que la succession des correctifs :

1. l'ADR n'était pas simulable (passerelle inactive) ⇒ `refreshTopologie()` ;
2. le plan régional manquait (étape placée avant celle qui le règle) ⇒ étape déplacée ;
3. **le run lu n'était pas le nouveau.** Le statut affichait déjà « …terminé (graine 7) » du
   run précédent : attendre ce mot passait avant que le run parte, et on lisait les lignes de
   l'ancien, qui n'avaient ni les 60 messages ni le SF12. Un texte laissé par une étape
   antérieure ne prouve rien sur l'étape courante — le même piège que le message
   « enregistrés » d'un formulaire, rencontré juste avant ;
4. **la session était incompilable.** `POST /simulate` renvoyait 422 : « mode mesh « relay »
   ne correspond pas au rôle border ». L'étape précédente posait `relay` sur une frontière, ce
   que l'enregistrement acceptait sans broncher et que le compilateur refusait au lancement —
   trois gestes plus loin, par un message nommant un réglage que l'utilisateur a oublié.

Le point 4 était un vrai défaut, et il est corrigé au **réglage**, pas au lancement : le mode
qui contredit le rôle reste visible et nommé, mais grisé, avec la raison écrite à côté. Le
retirer de la liste ferait croire qu'il n'existe pas ; le laisser actif ferait enregistrer une
configuration qu'aucun run ne peut compiler.

Ce n'est qu'en **lisant le corps des réponses HTTP** que la cause 4 est apparue : la console du
navigateur n'affiche que « 422 ».

### L'exercice : prouver le changement, pas le demander

`adr-debit-observe` (40 points) part d'un capteur à 150 m en SF12 qui n'émet que 20 messages.
Les vingt premiers points tombent avec le plan régional et la case ADR. Les vingt autres
**n'existent que si le run a vu le débit changer** :

| Messages | Ce que la trace porte | Note |
|---|---|---|
| 20 | `LinkADRReq` émis, terminal non encore appliqué : SF12 → SF12 | **20 / 40** |
| 40 | SF12 → **SF7** | **40 / 40** |

Mesuré sur serveur HTTP réel, trois graines, reproductible. La case cochée ne suffit donc pas :
c'est bien le run qui est noté. Les deux indices le disent sans donner la réponse.

**Défaut trouvé en chemin, et corrigé.** Un run ADR compile en forme `gateway` (singulier) : il
ne nomme **aucune** passerelle. Or `bind_run` exigeait un nom — l'atelier aurait donc échoué sur
**chaque** run ADR, y compris celui qu'il vient de lancer. La liaison implicite accepte
désormais un run sans passerelle nommée ; la liaison explicite reste stricte, parce qu'un nom
demandé qui n'existe pas est une faute de l'utilisateur et que le refus la lui dit.

### Jointure OTAA et trames confirmées — **livrés**

Le moteur les modélisait déjà (`ProtocolOptions.join` et `confirmed_uplinks`) ; `compile_session`
figeait `"protocol": {}`, et rien ne les exposait. Deux cases dans le panneau de simulation,
donc — à côté de l'ADR, parce qu'elles en ont la nature : ce sont des décisions qui changent la
forme du run entier, pas le comportement d'un équipement.

**Les deux s'excluent de l'ADR, et c'est dit avant le run.** `mac_loop` lève « jointure non
supportée par la boucle fermée ». Sans l'annonce, l'atelier aurait présenté une case valide
dont le run échoue sur une exception que rien n'explique.

Le cas d'école, mesuré sur serveur HTTP réel (5 capteurs, 6 messages, graine 7) :

| dispersion | join-request | join-accept | uplinks de données |
|---|---|---|---|
| 0 s  | 25 | **1** | **5**  |
| 20 s | 6  | 5     | **24** |

Une flotte qui joint au même instant se collisionne et n'émet presque rien. C'est ce que
l'encadré « Échanges avec le serveur » rend visible, plutôt que « 0 jointure réussie ».

Deux comptages qui ne se confondent pas, et la nuance est dans le code aussi bien que dans le
texte : un `join_accept` n'existe que si la demande a été reçue (une **tentative** n'est pas une
acceptation), et un `ack` n'existe que pour un uplink reçu — l'écart compte donc des trames
jamais arrivées au serveur, **pas** des acquittements perdus en vol.

**Le coût des trames confirmées est mesuré, pas supposé :** 16,1 → 18,4 µA de courant moyen
(+14,6 %), 15,9 → 18,2 mJ par message. Le capteur ouvre une fenêtre d'écoute pour l'ACK.

**Exercice `join-flotte-etalee`** (40 points) : quatre capteurs démarrent ensemble.

| état | run | note |
|---|---|---|
| départs simultanés | 24 join-request, **0 acceptation, 0 donnée** | **10 / 40** |
| dispersion 10 s | 4 acceptations, 19 uplinks | **40 / 40** |

### Ce qui reste

Rien. Les masques de canaux, dernier point ouvert du §2, sont livrés.

### Les masques de canaux — **livrés, par la v3 devenue voie de production**

`simulate_closed_loop_v3` expose `ClosedLoopV3Outcome.terminals`, dont `dr_masks` et
`enabled` — les canaux que le serveur a laissés au terminal. Ils n'étaient câblés dans
aucune voie de production, et l'ABI v2 ne les porte pas.

**L'invariant D1 disait plus que son intention.** Son commentaire énonce : « v1, v2 et gw2
n'importent rien de v3 » — la dépendance va dans un seul sens, la v3 réutilisant les
structures de la v2. L'assertion, elle, interdisait à **quiconque** d'appeler la v3, ce qui
n'avait de sens que tant que la v2 restait la voie de production. La v3 l'est devenue, et
l'assertion est resserrée sur l'intention : aucun retour de v1, v2 ou gw2 vers la v3, et une
seule voie d'appel nommée, pour qu'un second appelant soit vu plutôt que toléré.

**La bascule a été mesurée avant d'être faite.** Six scénarios — sans ADR, ADR proche, ADR
lointain, trames confirmées, cycle de service, créneaux MAC — ont été soumis aux deux ABI :
comptages, uplinks, descendantes, occupations et file MAC **identiques**. Sans cette mesure,
la bascule aurait été une régression silencieuse de toutes les mesures existantes plutôt
qu'une migration. Le test de parité v1/v2 est devenu un test v1/v3, et sert désormais de
garde-fou permanent.

Le plan est publié par l'API (`enabled_channels`, `channel_dr_masks`) et affiché dans le bloc
ADR, dont la commande — LinkADRReq — porte justement le débit **et** le masque. Deux
confusions écartées par les tests : un canal défini n'est pas forcément actif, et un masque
n'est pas forcément une plage contiguë (`0b10000001` admet DR0 et DR7, rien entre les deux).

### La puissance d'émission — **livrée par l'ABI v2, sans toucher à D1**

La même question que pour le débit, posée à la puissance : le serveur a-t-il commandé une
baisse, et a-t-elle été **appliquée** ?

Elle l'est, et la mesure le prouve : sur un capteur à 300 m réglé sur 14 dBm, quarante messages
avec ADR font passer l'index de puissance de 0 à 7, et le RSSI suit exactement — **−84,10 dBm
puis −98,10 dBm, soit 14 dB** pour un pas de 2 dB. La commande n'est donc pas un état calculé
pour la forme : elle change la physique du run.

Reste à ne pas la chiffrer de travers. Deux pièges, tous deux mesurés :

- **Ce n'est pas une puissance absolue.** L'index 0 n'est pas la PIRE du plan (16 dBm en
  EU868) : la base est la **puissance configurée du dispositif**. Un capteur réglé sur 14 dBm
  émet, à l'index 0, le RSSI de 14 dBm — trois configurations à 5, 10 et 16 dBm donnent
  −93,10, −88,10 et −82,10 dBm, l'index restant à 0 dans les trois cas. Afficher
  « 16 dBm → 2 dBm » serait faux de 2 dB au départ.
- **Le bas de l'échelle descend sous le minimum régional.** L'index 7 sur un capteur à 14 dBm
  donne 0 dBm, alors que le plan EU868 s'arrête à 2 dBm. Le moteur ne borne pas : c'est un
  écart de fidélité à garder en vue, pas une conformité à revendiquer.

L'encadré annonce donc une **réduction** — « puissance réduite de 14 dB » — et jamais des dBm
absolus qu'aucun terminal n'a émis. `DeviceRowOut` porte `power_index`, `final_power_index` et
`power_step_db`, absents hors boucle fermée comme l'est `final_spreading_factor` ; le bilan
retient un dispositif dont le débit **ou** la puissance a changé, pour ne pas taire l'un quand
l'autre bouge.

---

## 3. Liaisons observées sur les deux vues — **mesh et radio, livrés**

La phase L colore chaque équipement selon son taux de livraison et affiche ses chiffres au clic.
Elle ne **traçait pas les liaisons**. Packet Tracer, lui, matérialise les câbles : on voit qui
parle à qui avant même de lancer quoi que ce soit.

Le relais rendait ce manque plus sensible qu'ailleurs : la topologie relais → frontière → serveur
était invisible à l'écran, alors que le moteur la connaît. La matière était disponible ; c'est le
tracé qui manquait. Il est livré, pour les **deux** natures de liaisons.

### Ce qui est tracé

Les **liaisons mesh observées** : un relais qui a livré des trames à la frontière. Un trait
tireté, avec son chiffre au milieu (« 8 trames relayées »).

Les **liaisons radio observées** : une passerelle qui a **décodé** des trames d'un capteur. Même
trait tireté, même chiffre (« 5 trames décodées »), une teinte distincte.

Tireté et non plein, dans les deux cas : la liaison est observée, pas câblée — on ne la débranche
pas.

Rien n'est tracé avant un run : la topologie d'un réseau radio se mesure, elle ne se déclare pas.

### Où elles sont tracées

Sur **les deux vues**, à partir d'une seule source. `state.liaisonsObservees` est calculée une
seule fois après le run ; le plan 2D (`renderLiaisons`) et la carte 3D (`carte.setLiaisons`) la
consomment telle quelle. Si chacun recalculait de son côté, les deux vues pourraient diverger sans
que rien ne le signale — et deux vues qui ne disent pas la même chose sont pires qu'une seule.

Sur la carte 3D, le trait est porté à **40 m d'altitude**. À zéro, le relief et le fond de carte
l'avalent dès qu'on zoome : le trait disparaît au moment précis où on se rapproche pour le lire.

Une primitive Cesium n'existe pas dans le DOM. `window.__liaisonsCarte` compte les traits
effectivement tracés ; il est remis à zéro à chaque tracé, et lu par le test e2e. Sans ce
compteur, un trait jamais tracé ne se distinguerait pas d'un trait que personne ne regarde.

### Liaisons radio : livrées, et la leçon de la section est une correction

La section s'ouvrait sur « la donnée existe, elle n'est pas exposée », et désignait `with_trace`
comme l'obstacle. **Les deux affirmations étaient fausses, et une exécution les a défaites** —
c'est le fait que cette section doit porter, plus que le tracé lui-même.

Ce qui était faux, précisément :

| Affirmation de la version précédente | Ce que l'exécution a montré |
|---|---|
| `with_trace` n'est demandé qu'avec un relais ; sans mesh, la trace est vide | `build_multi_trace` appelle `simulate_multi_downlinks` **sans** `with_trace`, et obtient pourtant une trace de 5 enregistrements. La borne `MAX_TRACE_RECORDS` (200 000) ne concerne pas cette voie. |
| Le masque n'est jamais calculé | `decoded_mask == 0b111` sur **chacune** des 5 trames, trois passerelles : les trois ont décodé. |
| La matrice n'existe pas dans l'API | Elle n'était pas **exposée**. Elle était calculée, et disponible sans surcoût. |

La leçon, et elle vaut pour le reste du chantier : une conclusion tirée d'une lecture de code,
même soigneuse, n'est pas une mesure. Celle-ci a tenu plusieurs tranches sur la seule foi d'un
`grep`, alors qu'une sonde de six lignes la défaisait.

### Ce qui est livré

`MultiTxRecord.decoded_mask` est un masque 64 bits : **bit _g_ = la passerelle _g_ a décodé la
trame**. `trace_events.py` le réduisait à une seule passerelle pour désigner qui remet la trame ;
il produit désormais, en une passe, la matrice des réceptions par couple (dispositif, passerelle) :

| Étage | Ce qu'il fait |
|---|---|
| `trace_events._rx_matrix` | Une passe sur la trace, pas une double boucle dispositifs × passerelles. |
| `MultiTraceRun.rx_matrix` | Matrice portée par le résultat, sur **les deux voies** (avec et sans mesh). |
| `RunSummary.rx_matrix` | Publiée par l'API, avec `gateways` comme ordre des colonnes. |

Pourquoi c'était nécessaire, chiffré : trois passerelles en triangle autour d'un capteur, mesuré.

| Source | Ce qu'elle dit |
|---|---|
| Événements de trace (`gateway_index`) | chaque trame attribuée à **une** passerelle, toujours `gw-ouest` |
| `decoded_mask` | **les trois** passerelles ont décodé les 5 trames |

Tracer d'après les événements aurait affirmé « ce capteur n'est entendu que par gw-ouest », ce qui
est faux, et aurait masqué la **macro-diversité** — une propriété que LoRaWAN cultive précisément.
La carte aurait été fausse d'un **facteur trois**, pas imprécise.

### Ce que le trait veut dire

Une trame décodée par trois passerelles compte **trois liaisons**. Le masque dit « a décodé », pas
« a entendu » : c'est la granularité à laquelle une liaison radio est significative, et c'est
celle que l'étiquette annonce — « 5 trames décodées », pas « 5 trames relayées ». Confondre les
deux ferait lire un relais là où il n'y a qu'une portée.

Deux natures, deux teintes, sur les deux vues : **violet** pour un acheminement mesh (relais →
frontière), **sarcelle** pour une portée radio (capteur → passerelle), plus fine. Les peindre
pareil ferait lire « ce capteur est raccordé » là où il est seulement entendu. Et le trait reste
**tireté** dans les deux cas : une liaison observée n'est pas un câble.

Un couple à zéro n'est pas tracé : il n'a pas été observé. Un bout inconnu n'est pas tracé : pas
de trait dans le vide. Ce sont les mêmes règles que le mesh, et elles sont testées.

### Vérifié par quoi

La matrice est confrontée à un compteur **indépendant** : chaque colonne sommée doit retrouver
`audible_frames` de cette passerelle, tenu par le cœur. Mesuré sur deux passerelles et deux
capteurs à 6 trames : 12 = 12, 12 = 12. Une matrice qui dériverait se verrait.

Côté Python, 4 tests ; côté web, 12. La forme est garantie par le contrat, pas par une convention :
une colonne par passerelle, ou pas de matrice (`rx_matrix` sans `gateways` est refusé, et une ligne
de travers lève). Sans ce validateur, des traits décalés d'un cran seraient invisibles sur la
carte — et donc impossibles à corriger.

La composition des deux natures (`liaisonsObservees`) est une fonction pure, sans accès à `state` :
elle se vérifie donc **sans navigateur**. La vue n'a plus qu'à lui passer cinq entrées. C'est ce
qui ferme le trou entre « la matrice est servie » et « le trait est dessiné » — le seul chaînon
que les tests d'atelier ne pouvaient pas atteindre autrement.

Un test a d'ailleurs été corrigé par l'exécution : j'avais écrit trois passerelles pour deux
colonnes, et la fonction a attribué les colonnes dans l'ordre déclaré. Le code avait raison et
l'attente avait tort — c'est précisément la propriété que le tracé doit garantir.

L'étape e2e « liaisons mesh » les voit, et pour une raison qui n'allait pas de soi : sa session a
une frontière **et** un relais, donc deux passerelles, donc `rx_matrix` est publiée. Vérifié avant
d'écrire l'assertion : la session compile bien deux passerelles, et la matrice vaut `((4, 4),)` —
les 4 trames du capteur décodées par les deux.

Cette étape exigeait que chaque étiquette dise « trames relayées », ce qui était juste quand seul
le mesh se traçait. Elle est passée **au rouge** sur les liaisons radio, et elle avait raison.
L'assertion est désormais par nature : chaque étiquette porte le verbe du lien qu'elle chiffre, et
les deux natures doivent être présentes. Elle échoue si la matrice n'atteint pas le plan — c'est la
mesure en navigateur réel qui manquait.

Ce que l'audit de mise en page, lui, ne voit toujours pas : sa session n'a **qu'une** passerelle,
donc aucun trait radio. Le lui ajouter changerait la topologie qu'il mesure, donc sa ligne de base.
À faire sciemment, pas en passant.

Un écueil rencontré, et il mérite d'être noté : la matrice restait `None` alors que la fonction
directe renvoyait la bonne valeur. La cause était un **retour anticipé** — la voie sans mesh
sortait avant le `return` que j'avais modifié. Le symptôme ressemblait à une panne de moteur ;
c'était une ligne plus haut dans le fichier.

### Seconde passerelle de l'audit — **livrée**

La session de l'audit a désormais **deux** frontières : `gw-nord` à l'origine, `gw-sud` à 400 m à
l'est et 350 m au sud. Les liaisons radio y sont donc mesurées autrement que par l'étape e2e, et
la vue Plan est entrée dans les états passées au gabarit.

Ligne de base déplacée sciemment, et mesurée : **4 liaisons** tracées (2 capteurs × 2
passerelles), chacune portant 4 trames décodées, **0 problème** sur 23 états.

Deux écueils, et ils valent d'être notés parce qu'ils ne ressemblaient pas à des défauts de
l'application :

- **Un plan qu'on vient de cacher.** La première version revenait à la vue Carte après le
  comptage des liaisons ; l'audit signalait alors 35 problèmes — « `.plan-area` présente mais
  masquée », « `svg#plan` 0x0 » — qui n'étaient que le plan qu'on venait de masquer. La boucle
  de largeurs mesure le plan ; il faut y rester.
- **Deux capteurs qui émettent à la même seconde se collisionnent.** Il n'en restait qu'une
  trame décodée, donc **une** liaison : de quoi mesurer la géométrie d'un trait, pas celle d'un
  réseau. Une dispersion des départs (`start_spread_s`) et quatre trames chacun donnent les
  quatre liaisons attendues.

### Ce qui reste

Rien d'ouvert à cet endroit.

---

## 4. Sauvegarde et chargement d'un chantier — **livré**

Vérifié : `grep -rn "download\|save\|export" web/src/studio/main.js` ne renvoie que la
restauration du **jeton** en `sessionStorage`. Les sessions vivent côté serveur, indexées par
jeton.

Conséquence : pas d'équivalent du `.pkt`. On ne peut ni enregistrer une topologie pour la
reprendre, ni l'échanger, ni en rendre une variante. C'est l'affordance la plus élémentaire de
Packet Tracer et le meilleur support pédagogique qui soit (« voici le fichier, corrigez-le »).

`export.py` n'y répond pas : il exporte les **résultats** d'un run en Parquet, pas le chantier.

### Ce que contient le fichier

Tout est déjà dans `GET /sessions/{sid}/topology`, sans toucher au serveur : `nodes[]` porte
l'identifiant, le type, le nom, la position en mètres **et** les réglages capteur ; `states[]`
porte les réglages passerelle. S'y ajoute l'origine géographique, qui vit dans le studio.

### Quatre décisions

**Les positions sont en mètres, avec l'origine à côté.** C'est l'invariant D3 : changer de zone
déplace les équipements. Des latitudes absolues figeraient le chantier au lieu où il a été
construit et casseraient cette règle. C'est aussi D2 : les degrés à l'affichage, les mètres dans
le fichier et au moteur.

**Aucune clé dans le fichier.** `NodeState.keys` ne vaut jamais que `« ****** »`. Un chantier
s'échange par courriel ; il ne doit rien contenir qu'on ne puisse montrer.

**Charger crée une session neuve**, elle n'écrase pas la session courante. On ouvre un fichier
dans un nouvel atelier, comme Packet Tracer. C'est réversible : rien n'est perdu si le fichier
est mauvais.

**La validation est stricte et précède tout.** Un format inconnu est refusé avant la création de
quoi que ce soit. Un chantier à moitié chargé est pire qu'un chantier refusé : il a l'air
correct et ne l'est pas.

### Ce que le test vérifie

Le refus est la partie la plus testée du module, et c'est voulu : un chantier accepté à tort
produit une session à moitié construite, qui a l'air correcte et ne l'est pas. La charge de la
preuve est du côté de l'acceptation.

Le test de bout en bout **recharge un chantier écrit pour l'occasion**, et non le fichier qu'il
vient de recevoir. Recharger ce qu'on a produit soi-même prouverait l'aller-retour, pas l'import.

### Deux pièges rencontrés

Une lecture unique après une action asynchrone est une supposition. L'étape lisait le plan juste
après l'import : elle obtenait les équipements de la session précédente, et son propre message
d'erreur affichait déjà le bon chiffre — évalué une seconde fois, une fois le rendu fini. On
attend désormais le plan, puis la zone.

La zone était écrite après la sélection de la session, donc après le rendu : la carte s'affichait
à l'ancre du chantier précédent puis sautait. Invisible sur un plan en mètres, pas sur la carte
3D — et un saut qu'on voit ressemble à une hésitation.

### Le nom d'hôte

`new_session(id)` pose `hostname = id`. Le cas courant — personne ne renomme — est donc restauré
gratuitement. Renommer passe par le CLI (`configure terminal`, puis `hostname`), trois allers-
retours par équipement ; on ne les fait **que** si le nom diffère de l'identifiant, et un échec
est signalé, pas avalé.

---

## 5. Autonomie — **livrée** : le courant est simulé, la capacité est énoncée

Mesuré antérieurement : les profils d'énergie (`energy.py`, `energy_report.py`) n'ont **ni
capacité de batterie ni `mAh`**. L'autonomie en années, qui est la question numéro un d'un
déploiement LoRaWAN, ne se déduit pas des grandeurs simulées.

**Le diagnostic était inexact, et la cause était ailleurs.** Vérifié de nouveau : les profils
n'ont effectivement ni `mAh` ni capacité — mais ils n'en ont pas besoin. `energy.py` calcule un
**courant moyen** (`average_current_ua`, en µA), et c'est le seul terme que la simulation peut
mesurer. L'autre terme est la pile que l'utilisateur a choisie, que lui seul connaît.

Le vrai défaut : la compilation ne demandait **aucun profil d'énergie**. `RunCreate` accepte
bien `energy_profile`, mais `compile_session` ne le renseignait jamais. La mesure existait dans
le moteur et restait à `None` — l'indicateur « Courant moyen » de l'atelier était donc
structurellement vide, sans que rien ne le signale.

### Ce qui est en place

`compile_session` pose `energy_profile = "rak4631"` et le **déclare** dans les notes de
compilation : « énergie des capteurs : profil rak4631 (RAK4631 nRF52840 + SX1262) — le courant
moyen est celui de ce matériel ». Appliquer la consommation d'un module réel à « un capteur »
est un choix de modélisation ; il se dit, il ne se tait pas.

L'atelier affiche alors le courant moyen, et un champ « Capacité de la pile » laisse
l'utilisateur énoncer la sienne. Sur un run réel (SF9, période 300 s) : **51,96 µA**, soit
**5,3 ans** sur 2400 mAh.

### Pourquoi ce n'est pas une estimation

Le simulateur fournit le courant, l'utilisateur fournit la capacité, la division est de
l'arithmétique : aucun des deux côtés n'invente une grandeur. C'est ce qui distingue ce calcul
d'une estimation — et c'est pourquoi le champ reste **vide** plutôt que prérempli. Une pile
devinée produirait un chiffre d'autonomie qui a l'air mesuré et ne l'est pas.

Trois états, et ils ne se confondent pas : sans capacité saisie, rien n'est affiché (un « — »
à côté d'un champ vide dirait « autonomie nulle » à qui lit vite) ; capacité illisible, on le
nomme au lieu de convertir de force ; les deux présents, les deux termes sont rappelés et la
limite est dite — une pile ne rend pas ce que le calcul promet.

---

## 6. Relief — **livré** : choisissable depuis l'atelier, et sa voie réparée

Le serveur résout un `terrain_id` dans un catalogue (`--terrain-catalog`, fichiers `<id>.csv`),
l'API le valide (« relief inconnu du catalogue »), `environment.py` le simule. Mais :

- aucun catalogue n'est livré (pas de dossier `terrains/` dans le dépôt) ;
- `grep -rn "terrain\|relief\|elevation" web/src/studio/` ne renvoie **rien** d'exploitable.

Le relief était donc une capacité **entièrement invisible** : elle change la propagation, et
l'apprenant ne pouvait ni la voir ni la choisir. C'est d'autant plus dommage que l'atelier permet
justement de choisir une zone géographique réelle — le relief en est la suite naturelle.

### Ce qui est en place

Le relief appartient à la session (`POST /sessions/{sid}/terrain`), descend dans le corps compilé,
et voyage avec le chantier. L'atelier propose ceux que le serveur déclare, et **masque le champ
quand le catalogue est vide** : aucun relief n'est livré avec le dépôt, et c'est un fait à dire —
un sélecteur vide serait une promesse non tenue. Un serveur sans catalogue ne dit pas « le
simulateur ne sait pas faire », il dit « je n'ai rien à charger ». La nuance compte : sinon
l'utilisateur conclut à une limite du moteur quand c'est le serveur qui est vide.

### Deux défauts trouvés en rendant la voie praticable

Ils n'étaient pas latents par chance : **personne n'avait jamais pu emprunter cette voie.**
C'est la leçon de cette tranche — une capacité que rien ne permet d'exercer n'est pas une
capacité à moitié finie, c'est une capacité non testée.

`_build_scenario` reconstruisait le modèle par `model_validate({**model.model_dump(), ...})`.
Or `model_dump` transforme les valeurs par défaut en champs **explicitement fournis**, et
`gateway` en a une ; la règle « `gateway` ou `gateways`, pas les deux » se lit sur les champs
fournis. Le relief disqualifiait donc tout scénario multi-passerelles — précisément le cas où
il a le plus d'intérêt. Corrigé par `model_copy`, qui préserve ce qui a été fourni.

`simulate_multi_downlinks` rangeait un `ctypes.byref()` dans un champ de structure. `byref` ne
vaut que comme argument direct d'un appel et produit là un `CArgObject` que ctypes refuse ;
`prop` et `rule`, dans la même structure, ont toujours utilisé `ctypes.pointer`. Le run échouait
avec un relief, en signalant « échec du calcul » sans plus de précision.

### Preuve qu'il agit, et pas seulement qu'il est accepté

Avec une crête de 400 m entre le capteur et la passerelle : **0/1** reçue, perdue en sensibilité.
Sans elle : **1/1**. Accepter un paramètre ne prouve pas qu'il fait quelque chose.

---

## 7. Le verdict réglementaire — **livré** : la fenêtre est couverte, la comparaison est directe

Le verdict livré cette tranche compare l'occupation **mesurée sur la fenêtre du run** à une limite
définie sur une **fenêtre de moyennage réglementaire** (une heure chez ETSI). La réserve est
affichée, mais la comparaison reste celle de deux fenêtres différentes.

Deux voies pour la rendre exacte :

- **Allonger le run** jusqu'à la fenêtre réglementaire — **livrée** ; la réserve « coûteuse »
  qui l'accompagnait était fausse, voir ci-dessous ;
- **Afficher la fenêtre de mesure à côté du verdict** — **retenue et livrée**. L'utilisateur
  juge de l'écart, ce qui suppose d'exposer la durée du run en clair là où le verdict
  s'affiche.

#### Couvrir la fenêtre : la règle, et deux idées reçues que la mesure a défaites

Le verdict nommait l'écart entre les deux fenêtres sans dire comment le combler. Il nomme
désormais le réglage et le nombre, et propose le geste qui les applique.

La fenêtre observée vaut **`(messages − 1) × période`**, parce qu'elle court de la première
émission à la dernière et non de zéro à la dernière. D'où `messages = ceil(cible / période) + 1`.

Le piège, mesuré sur un capteur à 60 s :

| messages | fenêtre | occupation | verdict |
|---|---|---|---|
| 10 | 540 s | 0,267 % | réserve (7 fois plus long) |
| **60** | **3 540 s** | 0,245 % | **réserve (1 fois plus long)** |
| **61** | **3 600 s** | 0,245 % | **directe** |

`3600 / 60 = 60` paraît la réponse ; elle tombe **60 s sous l'heure**, et le verdict
retombe dans sa réserve en annonçant « 1 fois plus long » — ce qui sonne comme « presque
bon » sans rien dire de plus. Vérifié sur 18 configurations (périodes de 7 à 300 s, 1 à 3
capteurs, dispersion jusqu'à 100 s) : toutes couvrent l'heure, et dans 13 cas sur 18 un
message de moins n'aurait pas suffi.

À noter : l'occupation ne bouge pas (0,245 % contre 0,267 %). **Prolonger le run ne change
pas la valeur du verdict, il change sa validité** — c'est tout l'intérêt de la manœuvre, et
c'est pourquoi elle ne fausse rien.

Deux idées reçues que la mesure a défaites :

- **« Coûteux »** — non : 1,3 ms pour trois capteurs sur une heure, contre 0,5 ms pour dix
  messages. C'est ce coût supposé qui avait fait écarter la voie, et il n'avait jamais été
  mesuré.
- **La dispersion des départs n'est pas déductible.** Un capteur décalé émet plus tard,
  jamais plus tôt : elle s'ajoute à la fenêtre, on ne la compte pas. Mesuré : deux capteurs
  et 100 s de dispersion allongent la fenêtre de 17 s, pas de 100. La retirer du calcul
  ferait tomber sous l'heure dès qu'elle est nulle.

Le geste n'est proposé que s'il y a quelque chose à faire : rien sous un verdict annoncé
comme direct, et rien quand le besoin dépasse la borne du champ (1 000 messages).

### Ce qui est affiché

La fenêtre réelle du run, mesurée (`observation_ns`, la plus longue des passerelles), remplace
la réserve générale. Sur un run de trois équipements à `period_s=60, messages=10`, la note est
devenue :

> Mesuré sur 9 min 4 s, quand le texte réglementaire moyenne sur 1 h (ETSI) — soit environ
> 7 fois plus long. Le verdict porte sur la fenêtre du run : sur une heure, l'occupation
> moyenne peut être plus basse comme plus haute.

Le rapport est chiffré (« 7 fois ») et non suggéré (« plus court ») : un rapport donne la
sentence de la fenêtre, un adjectif ne permet pas de juger.

Quand le run couvre l'heure réglementaire, la phrase le dit et la comparaison devient directe.
Afficher la réserve dans ce cas décrédibiliserait un verdict valide — c'est le défaut symétrique
de celui qu'on corrige.

À noter : le verdict est rendu **par groupe**, ce qui est correct (la limite s'applique par
émetteur, et c'est le maximum du groupe qui est affiché, jamais la moyenne).

---

## 8. Temps réel — recommandation maintenue : ne pas le faire

Point D5, inchangé. Le simulateur est un moteur hors ligne qui produit une trace, rejouée ensuite.
Le temps réel supposerait un autre moteur, ou un découpage de la trace en temps réel qui
trahirait la physique simulée (une trame d'une seconde en SF12 ne se « joue » pas).

Packet Tracer a les deux modes ; il a aussi vingt ans et une équipe. La recommandation reste de
creuser le mode différé, qui est déjà riche (lecteur, instantané, inspecteur) et qui correspond à
la réalité d'un réseau LPWAN : on ne regarde pas un capteur émettre, on lit son historique.

---

## Ordre proposé

Le §1 commande tout le reste : la forme des fenêtres décide de celle des exercices.

```
1. Arbitrage fenêtre passerelle / CLI          ← décision à prendre
       │
       ├─→ 2. Contenu (exercices)              ← écrit contre la décision 1
       ├─→ 3. Liaisons tracées                 ← indépendant, peut venir avant
       └─→ 4. Sauvegarde du chantier           ← indépendant
   5. Autonomie      (dépend d'un champ batterie dans energy.py)
   6. Relief         (dépend d'un catalogue de terrains)
   7. Verdict : fenêtre de mesure affichée     ← petit, peut se faire à tout moment
   8. Temps réel     ← recommandé de ne pas faire
```

Les points 3, 4 et 7 sont indépendants de l'arbitrage et peuvent être menés sans attendre.
