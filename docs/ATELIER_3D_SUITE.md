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

### Ce qui reste

- Donner une seconde passerelle à la session de l'audit de mise en page, pour que les liaisons
  radio y soient mesurées autrement que par l'étape e2e. Cela déplace sa ligne de base : à faire
  sciemment, pas en passant.

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

## 7. Le verdict réglementaire — **fenêtre de mesure affichée** ; la comparaison reste à deux fenêtres

Le verdict livré cette tranche compare l'occupation **mesurée sur la fenêtre du run** à une limite
définie sur une **fenêtre de moyennage réglementaire** (une heure chez ETSI). La réserve est
affichée, mais la comparaison reste celle de deux fenêtres différentes.

Deux voies pour la rendre exacte :

- **Allonger le run** jusqu'à la fenêtre réglementaire — coûteux, mais la simulation est déjà
  hors ligne ;
- **Afficher la fenêtre de mesure à côté du verdict** — **retenue et livrée**. L'utilisateur
  juge de l'écart, ce qui suppose d'exposer la durée du run en clair là où le verdict
  s'affiche.

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
