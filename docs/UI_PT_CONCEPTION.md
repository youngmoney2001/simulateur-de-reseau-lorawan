# Conception de l'interface — disposition Packet Tracer, contenu LoRaWAN

Statut : **proposition**. Ce document **remplace les §3, §4, §5 et la décision Q2** de
`docs/UI_STUDIO_CONCEPTION.md`, qui proposaient trois colonnes fixes et un dock de console en bas.
Cette orientation a été écartée : elle ne correspond pas à l'interface attendue. L'état des lieux
mesuré (§1, défauts D1–D6) et les principes (§2, P1–P6) du document initial restent valables.

Référence amont : `docs/STUDY_PANEL_SPEC.md` définit le **quoi** et prime en cas de conflit. Elle
précise déjà (§4) que l'interface de configuration est *« inspirée d'IOS »* avec les modes Cisco
`gw1>` → `gw1#` → `gw1(config)#` → `gw1(config-if)#`. Ces modes **existent déjà et fonctionnent**.
Ce document porte sur l'**enveloppe visuelle**, pas sur la CLI.

---

## 1. Ce qui est demandé

Deux choses, distinctes :

1. **Au lancement, un choix de mode.**
2. **Ensuite, une interface de type Cisco Packet Tracer** — avec nos équipements LoRaWAN et nos
   propres icônes, pas celles de Cisco.

---

## 2. Le choix du mode au lancement

### 2.1 Constat mesuré : le serveur n'a pas de rôles

Avant de dessiner un sélecteur, il faut savoir ce qu'il commande. Vérification faite dans le code :

| Élément | État réel |
|---|---|
| `TokenStore` | porte un `owner` : une chaîne d'identité (`[A-Za-z0-9_.-]{1,64}`). Sert à l'isolation et à la limitation de débit. **Aucun rôle.** |
| `study_session.py` | les sessions **sont** rattachées à un propriétaire : `_get_locked` rejette si `st.owner != owner`. L'isolation entre utilisateurs est donc réelle. |
| `runs` (base SQLite) | les runs sont également rattachés à un `owner` (`owner_runs`, `_owned`). |
| `GET /api/v1/exercises` | renvoie `study_exercises.listing()` : **liste globale en lecture seule**. Aucun jeton ne peut créer ou modifier un exercice. |
| `POST /api/v1/exercises/{id}/submit` | ouvert à tout jeton valide. |

**Conséquence :** un sélecteur *Élève / Enseignant* n'aurait aujourd'hui **rien à commander**. Le
mode « Enseignant » implique au minimum *créer un exercice* et *consulter les tentatives d'un
élève* ; aucun des deux n'existe côté serveur. Le construire côté client produirait un
interrupteur décoratif — exactement ce que le principe P2 du document initial interdit
(présenter une commande qui n'agit sur rien).

### 2.2 Recommandation : deux modes adossés à du réel

Le choix « Élève / Enseignant, ou conception / étude » recouvrait deux lectures. La seconde est
**réalisable immédiatement**, parce que les deux pans existent déjà :

| Mode | Ce qu'il ouvre | Existe déjà ? |
|---|---|---|
| **Conception** | Réseau libre : construire, configurer, simuler, observer. Aucun barème, aucune note. | Oui — c'est le studio actuel |
| **Étude** | Exercice guidé : énoncé, indices pénalisés, notation, tentatives. | Oui — 7 exercices, `study_exercises.py` |

L'écran de lancement présente ces deux modes en cartes, avec le jeton demandé une seule fois.
Le mode reste **changeable à chaud** depuis la barre du haut : imposer un choix définitif au
démarrage obligerait à relancer l'application pour passer de l'un à l'autre.

### 2.3 Ce que demanderait le mode Enseignant

À titre d'information, et **hors périmètre de cette conception** : il faudrait ajouter au serveur
un rôle dans le jeton, un endpoint d'écriture sur les exercices, et un endpoint de consultation des
tentatives par élève — avec le risque que cela introduise une notion d'établissement ou de classe
qui n'existe pas dans le modèle actuel. C'est une décision produit, pas une variante d'interface.

---

## 3. La disposition Packet Tracer, adaptée

### 3.1 Ce qui fait qu'une interface « ressemble à Packet Tracer »

Ce n'est pas une affaire de couleurs. Ce sont six traits structurels :

1. **Le plan domine.** L'espace de travail occupe l'essentiel de la fenêtre ; les panneaux ne
   l'encadrent pas.
2. **La palette est en bas à gauche**, en deux boîtes : les catégories, puis les modèles de la
   catégorie choisie.
3. **Une barre d'outils verticale à droite**, pour les outils (sélection, déplacement,
   suppression, inspection, annotation, trame).
4. **Des fenêtres d'équipement flottantes**, ouvrables plusieurs à la fois, avec des onglets.
5. **Une barre d'état en bas** : bascule temps réel / simulation, et onglets de scénario.
6. **Les équipements sont des icônes posées sur le plan**, déplaçables, nommées.

L'interface actuelle ne respecte **aucun** de ces six traits : la palette est une barre latérale de
240 px, le plan est une colonne parmi d'autres, le panneau d'équipement est fixe à droite, et les
trois panneaux du bas se partagent l'écran avec le plan. Ce n'est pas une variante à corriger :
c'est une autre logique d'organisation.

### 3.2 Disposition proposée

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ Fichier  Édition  Affichage  Outils  Aide        [ Conception ▾ ]   alice  ▾  │
├────────────────────────────────────────────────────────┬─────────────────────┤
│                                                        │ ▣ Sélection         │
│                                                        │ ✥ Déplacer          │
│                                                        │ ✕  Supprimer        │
│                     PLAN (dominant)                    │ ⚲  Inspecter        │
│                                                        │ ✎  Annoter          │
│      ◯ capt-1        ▭ gw-nord ──── ▣ serveur          │ ➤  Trame simple     │
│                          │                             │ ➤  Trame complexe   │
│                        ▭ gw-relais                     │                     │
│                                                        │                     │
│      (couche d'animation superposée)                   │                     │
│                                                        │                     │
├─────────────────────────┬──────────────────────────────┴─────────────────────┤
│ CATÉGORIES  │ MODÈLES   │ Journal │ Trame │ Résultats                        │
│ ▸ Passerelle│ ▭ frontière│                                                    │
│ ▸ Relais    │ ▭ relais   │                                                    │
│ ▸ Capteur   │ ◯ capteur  │  (panneau d'observation, repliable)                │
│ ▸ Serveur   │ ▣ serveur  │                                                    │
├─────────────┴───────────┴────────────────────────────────────────────────────┤
│ ◉ Simulation  ○ Temps réel     │ Scénario 0 │ 7 équipements · 0 erreur       │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 3.3 Correspondance avec le code existant

L'intérêt de cette disposition est qu'elle se greffe sur des modules qui existent déjà :

| Zone | Reprend | État |
|---|---|---|
| Plan central | `renderPlan()`, `startDrag`/`onMove`/`onUp`, couche `#anim-layer` | existe |
| Icônes d'équipement | styles `.node .border/.relay/.sensor/.server` | existe |
| Palette bas-gauche | les 4 valeurs de `KINDS` (border, relay, sensor, server) | existe, à déplacer |
| Barre d'outils droite | outil *Trame* → `player.js` | en partie |
| Onglets Journal / Trame / Résultats | `player.js`, inspecteur de trames, `results.js` | existe |
| Fenêtre d'équipement | voir §4 | à construire |
| Bascule temps réel / simulation | **n'existe pas** | voir §6 |

---

## 4. La fenêtre d'équipement : trois onglets

C'est le trait le plus reconnaissable de Packet Tracer, et celui qui apporte le plus ici. La
fenêtre est **flottante** : plusieurs équipements peuvent être ouverts en même temps, ce qui permet
de comparer deux configurations côte à côte — impossible avec un panneau fixe.

| Onglet | Contenu | Reprend |
|---|---|---|
| **Physique** | Rôle, position (x, y) en mètres, état (configuré / non), nom d'hôte | `renderDeviceInfo()` |
| **Config** | Réglages par formulaire : région, sous-bande, SF, BW, mode mesh | `renderSensorForm()` pour les capteurs ; **à créer** pour les passerelles |
| **CLI** | Console IOS : modes `>` `#` `(config)#` `(config-if)#` | `renderConsole()` |

Deux bénéfices directs :

- **Le défaut D2 se résout mieux ainsi qu'avec la colonne à 480 px.** Une fenêtre flottante est
  redimensionnable : la console peut occuper la largeur nécessaire, et le caret d'erreur
  (`" ".repeat(column) + "^"`) ne se décale plus jamais, quelle que soit la taille de l'écran.
- **Le défaut D5 disparaît naturellement** : l'inspecteur de trames rejoint l'onglet *Trame* du
  panneau d'observation, au lieu d'être un `<details>` replié dans un panneau masqué.

Le principe de la décision Q2 (pas de zone qui apparaît et disparaît sans action de
l'utilisateur) demeure, mais change de support : la fenêtre s'ouvre sur un double-clic explicite,
et un équipement sans CLI (capteur, serveur) affiche un **état explicatif dans l'onglet CLI** au
lieu de masquer l'onglet.

---

## 5. Ce qui survit de la phase 0 déjà réalisée

La phase 0 (`f0a7319`) corrigeait quatre défauts. Le changement d'orientation n'annule pas tout :

| Correction | Sort |
|---|---|
| **D5** — inspecteur sorti du `<details>` | **conservé**, et renforcé par l'onglet *Trame* |
| **D6** — liens studio ↔ carte | **conservé** sans réserve |
| **D1** — exercice sur toute la largeur | **devenu sans objet** : la rangée du bas disparaît au profit de la palette |
| **D2** — colonne élargie à 480 px | **devenue sans objet** : la console passe en fenêtre flottante, mieux encore |

Aucune de ces quatre corrections n'était inutile : D5 et D6 restent, et D1/D2 ont été remplacées
par de meilleures réponses aux mêmes défauts. Le commit reste donc justifié.

---

## 6. Deux points qui ne sont pas de l'interface

### 6.1 La bascule temps réel / simulation

Packet Tracer l'affiche en bas à droite. **Ici, elle ne peut pas être branchée** : le moteur
fonctionne par lots, avec une file bornée — une simulation est lancée, elle produit un run, puis
un jeu d'événements que l'on rejoue. Il n'y a pas d'état « réseau vivant » à observer en direct.

Afficher un bouton *Temps réel* qui ne fait rien violerait le principe P2. Proposition : **ne pas
reproduire cette bascule**, et garder à la place l'état du run dans la barre du bas
(`7 équipements · 0 erreur`). Si le temps réel devient souhaitable, c'est un chantier moteur, pas
un chantier d'interface.

### 6.2 Les liaisons

Packet Tracer tire des câbles explicites entre équipements. Ici, les liaisons LoRaWAN ne sont pas
des câbles : un capteur émet, toutes les passerelles à portée reçoivent. Forcer un tracé de câble
donnerait une image fausse du protocole. Le plan montre donc les **portées et les trames**
(anneaux, trajectoires animées), pas des liaisons fixes.

---

## 6 bis. La saisie automatique du jeton

Demandée explicitement : le jeton ne doit plus être collé à la main.

### Ce qui rendait la chose non triviale

Le serveur **ne stocke que l'empreinte** (`sha256`) des jetons : `TokenStore.issue` génère
`secrets.token_urlsafe(32)`, conserve le hash et renvoie le jeton en clair **une seule fois**. Il est
donc impossible de restituer un jeton déjà émis — il faut en **émettre un nouveau**.

### Ce qui a été fait

Option `--auto-token PROPRIETAIRE` sur `serve` :

1. Au démarrage, le serveur émet **un** jeton pour ce propriétaire et le garde en mémoire.
2. **Chemin production** (`--dist`) : le serveur inscrit le jeton dans `studio.html` avant `</head>`.
3. **Chemin développement** (Vite proxy `/api`) : le point d'accès `GET /api/v1/auto-token` le
   fournit. Sans l'option, la route **n'existe pas** (404).
4. Le studio essaie `window.LSIM_TOKEN`, puis l'appel réseau ; s'il obtient un jeton, il se connecte
   et **masque le champ**. Sinon, la saisie manuelle reste disponible.

### Gardes

| Garde | Effet |
|---|---|
| Option absente par défaut | Comportement inchangé : saisie manuelle |
| `--auto-token` hors boucle locale | Refusé : *« sur le réseau, émettez des jetons avec issue-token »* |
| Injection limitée à `studio.*.html` | La carte des résultats n'appelle pas l'API : elle ne reçoit rien |
| Motif strict avant insertion | Aucune chaîne non conforme insérée dans la page |
| Avertissement au démarrage | `WARNING jeton automatique actif ... authentification désactivée` |

**Ce que cela coûte, en clair :** tant que l'option est active, **toute personne qui peut joindre le
port dispose de l'accès**. C'est acceptable pour une instance locale mono-utilisateur, ce qui est
précisément le cas d'usage visé ; ce ne l'est pas pour un serveur partagé.

---

## 7. Phasage

| Phase | Contenu | Risque | État |
|---|---|---|---|
| **A** | Écran de lancement : saisie du jeton, choix Conception / Étude, mode changeable à chaud | Faible | **Fait** |
| **B** | Plan dominant + palette en bas à gauche + barre d'outils à droite + barre d'état | Faible | **Fait** |
| **C** | Fenêtre d'équipement flottante, trois onglets | **Moyen** : touche `renderConsole` et le focus | **Fait** (le flottant est livré en phase E) |
| **D** | Panneau d'observation à onglets (Simulation / Journal / Trame / Exercice) | Faible | **Fait** |
| **E** | Fenêtre réellement flottante et redimensionnable (détachement du panneau) | Moyen | **Fait** |
| **F** | Adaptatif, accessibilité clavier, **vérification en navigateur réel** | Faible | **Fait** |

### Ce que couvrent les phases A–D

- **A** — écran `#launch` : jeton, deux cartes *Conception* / *Étude*, erreur visible sur place. Le mode
  est mémorisé et se change depuis la barre du haut (`#mode-select`).
- **B** — `.workspace` : plan en zone dominante, barre d'outils verticale à droite, palette en bas à
  gauche (catégories puis modèles), barre d'état en bas. Cliquer un modèle remplit et soumet le
  formulaire d'ajout existant : aucune logique d'ajout dupliquée, `validateNewNode` reste seul juge.
- **C** — fenêtre d'équipement à trois onglets **Physique / Config / CLI**. Elle est pour l'instant un
  panneau ancré (`position:fixed`) et non une fenêtre déplaçable : le gain principal — la console
  large et les trois vues séparées — est acquis, le détachement reste à faire.
- **D** — quatre onglets d'observation. L'inspecteur de trames quitte le panneau d'animation et
  devient un onglet de plein droit, ce qui clôt le défaut D5.

### Phase E — fenêtres flottantes

Le panneau ancré de la phase C devient une **fenêtre par équipement** :

- **Plusieurs ouvertes à la fois**, ce qui permet de comparer deux configurations côte à côte —
  impossible avec un panneau unique.
- **Déplaçable** par sa barre de titre, en cascade à l'ouverture, sans jamais sortir de l'écran.
- **Redimensionnable** (`resize: both`), y compris en largeur.
- La fenêtre active est mise en avant (bordure d'accent, élévation).
- Une fenêtre dont l'équipement disparaît est fermée par `renderDevice`, qui rafraîchit toutes les
  fenêtres ouvertes.

Conséquence directe sur le défaut **D2** : la console n'a plus de hauteur plafonnée
(`max-height: none`) et la fenêtre s'élargit à volonté. **Le caret d'erreur ne peut plus se
décaler**, quelle que soit la taille de l'écran — ce que la colonne de 480 px ne garantissait pas.

### Vérification dans un navigateur : acquise

La dette du §8.7 de la spec est **levée**. Un job `web` a été ajouté à la CI : il compile le cœur,
installe Chromium et exécute le test de bout en bout contre le vrai serveur API. **Les phases A–E
sont donc désormais validées dans un navigateur réel**, plus seulement par le build.

Le test couvre l'ensemble de la boucle : connexion, ajout d'équipements, rejet d'un identifiant
invalide, configuration en ligne de commande avec erreur au caret, refus d'un SF hors bornes,
glisser-déposer persisté côté API, simulation, animation (horloge, trames, journal), exercice
(indice pénalisé, notation, tentatives) et suppression de session.

**Dès son premier passage, ce test a trouvé trois défauts que rien d'autre ne pouvait voir** :

| Défaut | Nature |
|---|---|
| `renderDeviceInfo(node)` appelé sans corps de fenêtre après chaque commande CLI | **Bug d'application** : cinq erreurs de page par série de cinq commandes |
| Dix-huit sélecteurs désignant `#device-body`, renommé en phase E | Refactorisation incomplète |
| Onglet cliqué sans préciser la fenêtre | Ambiguïté révélée par l'ouverture simultanée de deux fenêtres |

Deux remarques d'exploitation. Le journal d'un job est hébergé hors de portée de l'outillage de
développement : en cas d'échec, il est publié en commentaire de la pull request pour rester
lisible. Et le paquet déclarant `dependencies: []`, la CI doit installer l'extra `[test]` — sans
quoi le serveur API échoue à l'import avant même que le navigateur ne démarre.

### Phase F — accessibilité clavier : mesurée, pas supposée

L'adaptatif et la vérification en navigateur étaient acquis. Restait une question qu'aucune
lecture de code ne tranche — « peut-on se passer de la souris ? » — et à laquelle personne
ici ne peut répondre à la main, faute d'affichage. La méthode est donc celle de l'audit de
mise en page : **substituer des mesures à l'examen impossible**.

`web/tests/e2e/audit-clavier.mjs` ouvre le studio dans Chromium, construit la même session
que l'audit de mise en page (une passerelle, deux capteurs, graine 7), lance un run, puis
parcourt huit états à la tabulation réelle. Pour chaque élément atteint, il publie le rôle,
le nom accessible, la visibilité, et **ce que le focus change au style** — mesuré en
comparant le style calculé avant et après, plutôt qu'en cherchant un `outline` : un thème
peut signaler le focus par une bordure, un fond ou une ombre.

**État mesuré : 0 problème sur 8 états et 297 éléments atteints.** Le rapport est déposé
dans `docs/audits/clavier.md` et rapatrié par la CI, comme celui de la mise en page.

Trois défauts ont été trouvés et corrigés au passage, tous par la mesure :

| Défaut | Ce que la mesure a montré |
|---|---|
| La couche d'animation avalait les clics | `elementFromPoint` au centre d'un capteur renvoyait `circle.anim-ok.frame`, pas le nœud : après un run, cliquer un équipement sur le plan ne faisait plus rien. La couche est décorative ; elle ne capte plus le pointeur. |
| Les onglets `Carte 3D / Plan` étaient sourds aux flèches | Ils portent `role="tab"` et un `aria-selected` tenu à jour — le motif ARIA promet donc les flèches, mais `wireTabs` n'était câblé que sur deux des trois groupes. Il gagne aussi Début et Fin. |
| Les équipements du plan n'étaient atteignables qu'au pointeur | Un groupe SVG sans `tabindex` ni rôle n'est une cible de tabulation pour personne. Sans souris, **aucune fenêtre d'équipement ne pouvait être ouverte** — donc aucun réglage d'émission, de batterie ou de SF. Les nœuds sont désormais des boutons : `role`, nom accessible, indicateur de focus, et ouverture par Envoi ou Espace. |

Un quatrième point mérite d'être noté parce qu'il a coûté deux rapports : l'audit s'est d'abord
trompé lui-même. Un `blur()` ne remet pas à zéro le point de départ de la navigation
séquentielle (un état annonçait 3 éléments et 30 inatteignables qui n'étaient qu'en aval), et
un `focus()` programmatique ne tient pas dans ce navigateur (ordre vide dans les quatre états).
Seules de vraies pressions de touche déplacent le focus de façon fiable. Un contrôle désactivé
est par ailleurs **correctement** hors du parcours : les boutons « Indice » et « Noter »,
inactifs tant qu'aucun exercice n'est lancé, ont été exclus de la règle plutôt que comptés
comme des défauts.

### Captures d'écran : produites, mais illisibles par une machine

Une étape enregistre treize états du studio — écran d'accueil, topologie à quatre équipements, les
trois onglets d'une fenêtre, une console remplie, les quatre onglets d'observation, et deux
largeurs étroites — puis les dépose dans la branche, l'hébergeur d'artefacts étant inaccessible.

**Ces images n'ont jamais pu être examinées par l'outil lui-même** : la lecture d'un fichier image
renvoie une absence de capacité de vision. Elles servent donc uniquement au lecteur humain, qui
peut enfin juger du rendu sans rien installer. Aucune conclusion n'a été tirée d'une image.

### Audit de mise en page : l'œil remplacé par des mesures

Faute de pouvoir regarder, l'interface est **mesurée**. Le navigateur connaît la position et la
taille réelles de chaque boîte ; un audit interroge donc en nombres ce qu'on chercherait
visuellement, à quatre largeurs dont les deux paliers adaptatifs :

| Famille recherchée | Résultat |
|---|---|
| Débordement horizontal | aucun aux quatre largeurs |
| Texte tronqué par un débordement masqué | aucun |
| Région attendue absente, invisible ou écrasée | aucune |
| Contraste insuffisant (seuil 4,5) | **2 trouvés, puis 0 après correction** |

Les deux défauts relevés étaient réels, et identiques aux quatre largeurs : le gris des textes
secondaires ne donnait que **4,27** de contraste sur le fond des menus, et la poignée signalant
qu'une fenêtre se déplace — seul indice de cette fonction — tombait à **1,54**, c'est-à-dire
invisible. Corrigés en assombrissant le gris vers la teinte la plus claire qui passe sur les cinq
fonds clairs de l'interface, et en colorant la poignée comme un texte secondaire. L'audit est
ensuite redescendu à **0 problème**.

Cette méthode ne remplace pas un jugement esthétique : elle ne dit rien de l'élégance, de
l'équilibre ni de la ressemblance avec Packet Tracer. Elle garantit seulement l'absence de défauts
mesurables.

**Point de géométrie à connaître** : à 1180 px et en dessous, le panneau d'observation commence
sous la ligne de flottaison (il démarre à y=1000 pour une fenêtre de 1000 px de haut). Il reste
accessible en défilant, le corps de page acceptant le défilement depuis la phase F, mais il n'est
pas visible d'emblée. C'est un choix, pas un défaut — à documenter si l'on préfère l'autre option.

La phase C est la seule sensible : la console garde le focus et l'historique par équipement, et le
passage d'un panneau fixe à une fenêtre flottante touche `renderConsole`, `renderDeviceInfo` et
`renderSensorForm`.

**Dette connue, inchangée** : la spec §8.7 signale que la vérification visuelle en navigateur réel
n'a jamais été faite. Aucune phase ne doit être tenue pour acquise sans ce passage — et la CI
n'exécute aujourd'hui **aucun** test web, ni les 29 tests Node ni l'e2e.

---

## 8. Questions ouvertes

1. **Le mode Enseignant est-il souhaité ?** Il demande des rôles côté serveur, qui n'existent pas.
   Si oui, il faut arbitrer le modèle (établissement, classe, tentatives) avant toute interface.
2. **La bascule temps réel / simulation est-elle attendue ?** Elle est emblématique de Packet
   Tracer, mais le moteur actuel ne peut pas l'alimenter (§6.1).
3. **Faut-il conserver les deux applications ?** Le studio en disposition PT, et la carte Cesium
   en applicatif séparé, reliées comme décidé en Q3.

---

## 9. Tableau récapitulatif

| Sujet | Décision |
|---|---|
| Orientation | Disposition Packet Tracer, **contenu et icônes LoRaWAN** |
| Document initial | §3, §4, §5 et Q2 **remplacés** ; §1 (D1–D6) et §2 (P1–P6) conservés |
| Mode au lancement | **Conception / Étude**, changeable à chaud — les deux pans existent |
| Mode Élève / Enseignant | **Écarté** : aucun rôle côté serveur, rien à commander |
| Fenêtre d'équipement | Flottante, trois onglets : Physique / Config / CLI |
| Console | Dans l'onglet CLI, fenêtre redimensionnable → le caret ne se décale plus |
| Bascule temps réel | **Non reproduite** : le moteur travaille par lots |
| Liaisons | Non représentées en câbles : contraires au modèle LoRaWAN |
| Phase 0 (`f0a7319`) | D5 et D6 conservés ; D1 et D2 remplacés par de meilleures réponses |
