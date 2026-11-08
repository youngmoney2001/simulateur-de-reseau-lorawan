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

## 1. ~~La fenêtre passerelle est presque vide~~ — **arbitrage tranché, en cours depuis cette tranche**

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
comble pas en une tranche : **c'est un chantier de fond, à mener après l'arbitrage du §1** (les
exercices s'écrivent contre l'interface qui les résout).

---

## 3. Liaisons mesh tracées sur le plan — **livré** ; les liaisons radio restent ouvertes

La phase L colore chaque équipement selon son taux de livraison et affiche ses chiffres au clic.
Elle ne **trace pas les liaisons**. Packet Tracer, lui, matérialise les câbles : on voit qui parle
à qui avant même de lancer quoi que ce soit.

Le relais rend ce manque plus sensible qu'ailleurs : la topologie relais → frontière → serveur est
invisible à l'écran, alors que le moteur la connaît. La matière est donc disponible ; c'est le
tracé qui manquait.

### Ce qui est tracé

Les **liaisons mesh observées** : un relais qui a livré des trames à la frontière. Un trait
tireté, avec son chiffre au milieu (« 8 trames relayées »). Tireté et non plein : la liaison est
observée, pas câblée — on ne la débranche pas.

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

### Liaisons radio : la donnée existe, elle n'est pas exposée — mesuré, pas supposé

`MultiTxRecord.decoded_mask` est un masque d'entier 64 bits : **bit _g_ = la passerelle _g_ a
décodé la trame**. C'est exactement la donnée qu'il faudrait pour tracer les liaisons radio
capteur → passerelle. Elle n'est **pas** exposée : `trace_events.py` ne s'en sert que pour
désigner celle qui remet la trame, et l'événement servi ne porte que `gateway_index`, c'est-à-dire
la meilleure passerelle. Tracer à partir de ce qu'on sert aujourd'hui dessinerait un trait par
trame là où plusieurs passerelles ont entendu : **faux, pas imprécis**.

Deux obstacles à lever, mesurés tous les deux :

`with_trace` n'est demandé que `si mesh_cfg is not None` — sans relais, la trace est vide et le
masque n'est jamais calculé. La demander partout coûte un tampon de `MAX_TRACE_RECORDS`
(200 000) et **fait échouer** les runs qui dépassent cette borne : la généraliser régresserait
les gros scénarios.

Il faut donc soit un compteur natif par couple (capteur, passerelle), soit une trace demandée
sous condition de taille. À décider avant d'écrire quoi que ce soit côté atelier.

### Ce qui ne l'est pas, et pourquoi : une mesure, pas une prudence

Les **liaisons radio** « capteur → passerelle » sont écartées, et la raison est chiffrée. Un
événement de trace porte `gateway_index = best_gateway` : la meilleure passerelle **de la trame**,
une seule. Or, mesuré sur un run à deux passerelles et six capteurs :

| Source | Ce qu'elle dit |
|---|---|
| Événements de trace | chaque trame attribuée à **une** passerelle |
| Compteurs par passerelle | **les deux** passerelles ont reçu les 24 trames |

Tracer d'après les événements affirmerait « ce capteur n'est entendu que par gw-nord », ce qui est
faux, et masquerait la **macro-diversité** — une propriété que LoRaWAN cultive précisément. La
matrice par couple (capteur, passerelle) n'existe pas dans l'API. On ne peut donc pas tracer
juste, et tracer faux serait pire que ne pas tracer.

La porte de sortie est connue : exposer l'ensemble des passerelles ayant décodé chaque trame
(`decoded_mask`, déjà calculé côté moteur). C'est un ajout de contrat, pas une supposition.

### Ce qui reste

- Les liaisons radio, donc, dès que la donnée par couple existe.
- Le tracé sur la **carte 3D** : aujourd'hui seule la vue Plan 2D les porte.
- L'audit de mise en page ne voit pas ces traits : sa session n'a pas de relais.

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
