# Conception de l'interface du studio (brouillon, aucune ligne de code écrite)

Statut : **proposition** — aucune ligne de code n'a été écrite. Les trois questions laissées
ouvertes dans une première version sont tranchées au §7, preuves à l'appui.

Ce document ne modifie rien : il décrit l'interface à construire. Il complète
`docs/STUDY_PANEL_SPEC.md`, qui définit le **quoi** (modèle réseau, CLI, exercices notés, contrat
d'API) ; celui-ci définit le **comment visuel**. En cas de conflit, la spécification prime.

Décisions de l'auteur déjà arrêtées et auxquelles cette conception se conforme (§10 de la spec) :
backhaul mesh entre passerelles, CLI inspirée d'IOS sans fidélité, exercices notés par barème,
bande mesh dédiée.

---

## 1. État des lieux, mesuré

Deux applications distinctes, sans lien de navigation entre elles :

| Entrée | Rôle | Module |
|---|---|---|
| `index.html` | Carte des résultats (globe Cesium, chargement GeoJSON/MNT) | `src/main.js` |
| `studio.html` | Studio d'étude (topologie, CLI, simulation, exercices) | `src/studio/main.js` |

Le studio est découpé en modules purs (logique sans DOM) et un contrôleur :
`topology.js` (validation, conversion mètres ↔ pixels), `console.js` (historique, invite),
`results.js` (formatage), `animation.js` + `player.js` (animation des trames), `api.js` (HTTP),
`main.js` (câblage DOM, 583 lignes). Cette séparation est saine et **ne doit pas être remise en
cause** : c'est elle qui permet les 29 tests Node sans navigateur.

### Défauts constatés

**D1 — La grille du bas déclare deux colonnes pour trois panneaux.**
`.bottom { grid-template-columns: 1fr 1fr }` avec trois enfants directs (`.sim`, `.player`,
`.exercise`), et aucun `grid-column` nulle part. Le panneau *Exercice* passe donc en deuxième
rangée, colonne 1, laissant la colonne 2 vide.

Le défaut est **sournois** : le panneau *Animation* porte `hidden` tant qu'aucune simulation n'a
tourné. À l'ouverture, deux panneaux visibles remplissent proprement les deux colonnes. Le trou
n'apparaît qu'**après** la première simulation.

**D2 — La console est confinée dans une colonne de 320 px.**
La CLI signale ses erreurs par un caret aligné sur la colonne fautive :
`" ".repeat(res.error.column) + "^ " + message`. Dès que la ligne passe à la ligne, le caret ne
désigne plus rien. Or la console est rendue **dans** le panneau d'équipement (`renderConsole`
appelle `$("device-body")`), donc dans 320 px.

**D3 — L'exercice, objet pédagogique central, occupe la position la plus faible.**
Il est le dernier enfant du DOM et tombe en deuxième rangée (D1). La spec §1 fait pourtant de
l'exercice noté la finalité du panneau.

**D4 — La barre du haut mélange trois préoccupations sans rapport.**
Authentification (jeton, *Se connecter*), cycle de vie de la session (*Nouvelle*, *Supprimer*) et
choix de la tâche (*Exercice*, *Démarrer*) sont alignés dans le même bandeau, avec le même poids
visuel.

**D5 — L'inspecteur de trames est enterré.**
Construit au jalon D1, il est un `<details>` replié à l'intérieur du panneau *Animation*, lui-même
masqué par défaut. Trois niveaux d'accès pour la fonctionnalité la plus récente.

**D6 — Aucune navigation entre les deux applications.**
Rien ne relie le studio à la carte des résultats, ni l'inverse.

---

## 2. Principes

**P1 — L'interface suit la boucle d'apprentissage, pas l'ordre des widgets.**
La spec §1 la décrit : on construit une topologie, on configure en ligne de commande, on simule, on
observe. Quatre temps, séquentiels. L'interface actuelle présente six panneaux frères, d'où
l'absence de hiérarchie. La disposition doit rendre le temps courant évident.

**P2 — Un rôle par zone, un zone par rôle.**
Construire / configurer / observer ne doivent pas se disputer la même place.

**P3 — La console doit être large.**
Ce n'est pas un confort : c'est une condition de justesse du retour d'erreur (D2). D'où un
ancrage en bas, pleine largeur, repliable — le modèle du terminal, familier du public visé.

**P4 — Le serveur reste l'autorité ; l'interface ne fait pas d'oracle.**
Déjà vrai côté validation (`topology.js` reprend les règles de `study_contract.py` « pour un retour
immédiat », le serveur tranchant). Ce principe gouverne aussi l'affichage des critères (P5).

**P5 — Une évaluation n'est pas un état affiché en direct.** Décision **Q1** du §7 : interdit,
et pas seulement déconseillé — la spec §6 veut que la solution de référence ne quitte jamais le
serveur.
Les critères d'un exercice **ne doivent pas** se cocher au fil de la configuration : ce serait
donner la réponse avant la soumission, et l'exercice perdrait sa fonction d'évaluation. L'état des
critères n'apparaît qu'après *Noter*. Le coût d'un indice, en revanche, doit être visible **avant**
de le demander — c'est une information, pas une réponse.

**P6 — Rester en JavaScript natif.**
Aucune migration vers un framework. Les modules purs et les tests Node sans navigateur sont un
acquis (29 tests) ; un framework les remettrait en question pour un gain nul à cette échelle.

---

## 3. Architecture d'information

### Disposition retenue (≥ 1280 px)

```
┌─ CONTEXTE ───────────────────────────────────────────────────────────────────┐
│ Studio LoRaWAN   │ Exercice : <titre ou « aucun »>   │ Session ▾ │ Jeton ●   │
└──────────────────────────────────────────────────────────────────────────────┘
┌─ TÂCHE (300) ────┬─ RÉSEAU (1fr) ────────────────────┬─ ÉQUIPEMENT (340) ────┐
│                  │                                   │                       │
│ Énoncé           │        plan SVG                   │  Frontière · gw-nord  │
│                  │        + animation                │  ─────────────────    │
│ [ Indice (−2) ]  │                                   │  Type, position       │
│ [ Noter ]        │                                   │  État : configuré     │
│                  │                                   │  Réglages capteur     │
│ Tentatives       │                                   │  [ Retirer ]          │
│  · 12/30         │                                   │                       │
│                  │                                   │                       │
│ ───────────────  │                                   │                       │
│ PALETTE          │                                   │                       │
│ + Passerelle     │                                   │                       │
│ + Capteur        │                                   │                       │
│ Graine [1]       │                                   │                       │
│ [ Simuler ]      │                                   │                       │
├──────────────────┴───────────────────────────────────┴───────────────────────┤
│ OBSERVATION   [ Journal ] [ Trame ] [ Résultats ]                            │
│ ───────────────────────────────────────────────────────────────────────────  │
│  (contenu de l'onglet actif)                                                 │
├──────────────────────────────────────────────────────────────────────────────┤
│ ▾ CONSOLE                                          gw-nord> region EU868     │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Pourquoi ces trois colonnes

| Zone | Rôle (P1) | Contenu | Largeur |
|---|---|---|---|
| **Tâche** | Ce qu'on me demande | Énoncé, indices, Notation, tentatives, puis palette et simulation | 300 px |
| **Réseau** | Ce que j'ai construit | Plan SVG, animation, puis observation en onglets | 1fr |
| **Équipement** | Ce que je configure | Propriétés de la sélection, réglages capteur | 340 px |

La palette rejoint la colonne *Tâche* : ajouter un équipement est un acte de construction, au même
titre que lire l'énoncé. La simulation (graine, *Simuler*) s'y place aussi : c'est le passage de la
construction à l'observation.

L'observation (journal, trame, résultats) se place **sous le plan**, dans la même colonne, et non
dans une bande horizontale : on regarde les trames circuler, puis on les inspecte. Les séparer
obligerait l'œil à quitter la zone qu'il vient de suivre.

### La console en bas, pleine largeur

Répond à D2 et à la décision **Q2** : le dock est **permanent**, il ne disparaît jamais de
lui-même. Deux états, commandés par l'utilisateur seul — replié (barre de titre) ou ouvert (hauteur
fixe) — et ce choix persiste d'une session à l'autre.

Quand l'équipement sélectionné n'a pas de CLI (capteur, serveur), le dock **reste en place** et
affiche un état vide explicatif plutôt que de se masquer. La hauteur du plan ne dépend donc jamais
de la sélection : un redimensionnement subi désoriente plus qu'un espace occupé.

Le contenu reste mémorisé par équipement, comme aujourd'hui (`state.consoles`, clé par `node_id`) —
l'historique et la sortie ne sont pas perdus en changeant de sélection.

### Barre de contexte

Répond à D4 et D6. Trois groupes, séparés visuellement :

- **Identité** : nom de l'application, et lien vers la carte des résultats (D6).
- **Tâche courante** : l'exercice en cours, visible en permanence — on ne perd pas de vue ce qui est
  demandé en allant configurer un équipement.
- **État** : session active, indicateur de jeton (connecté / non connecté).

Le jeton reste un champ de saisie (la question de l'injection automatique au démarrage est une
décision produit, non traitée ici).

### Onglets d'observation

| Onglet | Contenu | Origine |
|---|---|---|
| **Journal** | Journal par saut, cliquable | existe (`player.js`) |
| **Trame** | Inspecteur de trames LoRaWAN, couche par couche | existe (jalon D1), à promouvoir — D5 |
| **Résultats** | Tableau par passerelle : reçues, pertes, latence p95, relais mesh | existe (`results.js`) |

Le premier onglet actif après une simulation est **Journal** ; l'onglet *Trame* se signale quand
l'événement courant porte une trame (pastille ou libellé), sans basculer tout seul — un changement
d'onglet non demandé désoriente.

---

## 4. Corrections immédiates (à faire avant toute restructuration)

Ces quatre points sont des défauts, pas des choix de conception. Ils se corrigent sans toucher à
l'architecture :

1. **D1** : donner trois colonnes à `.bottom`, ou faire passer l'exercice sur toute la largeur avec
   `grid-column: 1 / -1`. La seconde option est préférable : l'énoncé gagne en lisibilité.
2. **D2** : sortir la console du panneau d'équipement et l'élargir. À défaut du dock complet,
   élargir la colonne de droite à 480 px est un premier pas.
3. **D6** : ajouter un lien `Carte des résultats` dans la barre du haut, et réciproquement un lien
   `Studio` sur `index.html`.
4. **D5** : sortir l'inspecteur de trames du `<details>`.

---

## 5. Phasage

| Phase | Contenu | Risque |
|---|---|---|
| **0** | Les quatre corrections immédiates (§4) | Faible : CSS et déplacement de nœuds DOM |
| **1** | Console en bas, pleine largeur, repliable | Moyen : touche `renderConsole` et le focus |
| **2** | Réorganisation en trois colonnes + barre de contexte | Moyen : réécrit `studio.html`, peu de JS |
| **3** | Onglets d'observation, promotion de l'inspecteur de trames | Faible : réagencement de modules existants |
| **4** | Adaptatif (seuils de largeur), accessibilité au clavier, vérification en navigateur réel | Faible |

Chaque phase est indépendamment publiable et testable. La phase 0 est faisable sans attendre.

**La vérification en navigateur réel est une dette connue** : la spec §8.7 la cite explicitement
(« la vérification visuelle en navigateur réel au-delà du test e2e »). Aucune de ces phases ne doit
être considérée comme acquise sans un passage dans un vrai navigateur, y compris pour la phase 0.

---

## 6. Hors périmètre

Ce que cette conception **ne** propose pas :

- **Migrer vers un framework.** Le JavaScript natif et les modules purs sont un acquis (P6).
- **Intégrer Cesium au studio.** La carte des résultats reste une application séparée ; seul un lien
  les relie.
- **Refaire le modèle de données ou l'API.** Hors sujet : c'est `STUDY_PANEL_SPEC.md`.
- **Le multi-utilisateur**, l'internationalisation, le thème sombre. Non demandés.
- **L'injection automatique du jeton.** Décision de sécurité qui revient à l'auteur.

---

## 7. Décisions sur les trois questions soulevées

Ces trois points étaient restés ouverts. Ils sont tranchés ci-dessous. Pour chacun, la
recommandation initiale est reprise, puis **corrigée** là où elle était insuffisante, avec la
preuve qui fonde la décision.

### Q1 — Les critères d'un exercice doivent-ils se cocher en direct pendant la configuration ?

**Recommandation initiale :** non.
**Correction :** la réponse était juste, mais le raisonnement était insuffisant. Ce n'est pas une
préférence pédagogique, c'est une **contrainte d'architecture**.

La spec §6 pose : *« La solution de référence n'est jamais envoyée au client. »* Or une vérification
en direct ne peut se faire que de deux manières, et les deux violent cette règle :

1. **Évaluer côté client** : il faut alors envoyer au navigateur soit la logique du critère, soit la
   valeur attendue. C'est précisément la solution de référence.
2. **Interroger le serveur à chaque frappe** : le booléen renvoyé ne livre pas la solution
   littéralement, mais il est *sondable*. En configurant puis en observant le voyant, on obtient la
   réponse par essais — sans payer le prix d'un indice.

Le second point est le plus important : les indices sont *« révélés à la demande et comptés dans la
note »* (spec §6). Une vérification continue contournerait cette économie et rendrait les indices
inutiles.

**Décision : les critères ne sont jamais affichés avant la soumission.** L'état de chaque critère
n'apparaît qu'après *Noter*. Le coût d'un indice, lui, reste affiché **avant** la demande : c'est une
information tarifaire, pas une réponse.

**Conséquence :** le panneau *Tâche* n'a aucun état visuel par critère. Il affiche l'énoncé, les
boutons d'action, et l'historique des tentatives *après* notation.

**Piste écartée, notée pour mémoire :** un bouton *Vérifier* explicite, compté comme un indice
(coût en points), redonnerait du feedback sans fuite continue — l'élève paie l'information au lieu
de l'obtenir gratuitement. C'est cohérent avec le modèle, mais cela demande un endpoint serveur
supplémentaire et sort du périmètre de cette conception.

### Q2 — La console doit-elle être toujours visible ?

**Recommandation initiale :** ouverte seulement si l'équipement sélectionné dispose d'une CLI.
**Correction :** cette recommandation est **erronée**. Elle fait apparaître et disparaître le dock
selon qu'on sélectionne une passerelle ou un capteur : la zone de plan change de hauteur à chaque
clic, de façon imprévisible pour l'utilisateur. Un redimensionnement subi est pire qu'un espace
occupé.

**Décision : le dock est permanent.** Il ne disparaît jamais de lui-même. Deux états, et deux
seulement :

- **Replié** (une barre de titre) ou **ouvert** (hauteur fixe) — à la main de l'utilisateur, et ce
  choix **persiste** d'une session à l'autre.
- Quand l'équipement sélectionné n'a pas de CLI (capteur, serveur), le dock reste en place et
  affiche un **état vide explicatif** (« Les capteurs ne se configurent pas en ligne de commande :
  utilisez le formulaire de réglages. »), au lieu de se masquer.

La hauteur du plan ne dépend donc plus que d'une action explicite de l'utilisateur, jamais de sa
sélection.

**Conséquence :** le dock est un élément structurel de `studio.html`, pas un enfant du panneau
*Équipement*. Son état ouvert/replié se conserve (stockage local), comme l'historique de la console
déjà conservé par équipement.

### Q3 — Faut-il fusionner le studio et la carte des résultats en une seule application ?

**Recommandation initiale :** non, les relier suffit.
**Correction :** la conclusion tient, mais la question était **mal posée** — et la réponse initiale
s'appuyait sur une intuition non vérifiée. Mesure faite sur le build :

| Entrée | Bundle chargé | Taille |
|---|---|---|
| `studio.html` | `studio-*.js` | **22,3 ko** |
| `index.html` | `main-*.js` | **4 080 ko** (Cesium) |

Vite produit déjà deux bundles séparés : le studio **ne charge pas Cesium**, et la carte ne charge
pas le studio. Fusionner ferait payer au studio 4 Mo, ou imposerait un chargement différé qui
n'existe pas aujourd'hui.

Le vrai défaut n'est donc pas l'absence de fusion : c'est **l'absence totale de lien** (D6). La
question utile n'était pas « fusionner ? » mais « dans quel sens, et avec quoi ? ».

**Décision : ne pas fusionner ; poser une navigation bidirectionnelle et contextualisée.**

- Dans le studio, la barre de contexte porte un lien *Carte des résultats*.
- Sur la carte, un lien *Studio* en miroir.
- Les deux applications répondent à des moments distincts de la boucle : on construit et on observe
  en 2D dans le studio, on examine un déploiement sur terrain réel en 3D dans la carte.

**Conséquence :** deux entrées Vite conservées (`vite.config.js` a déjà les deux), deux bundles
distincts, un lien dans chaque barre de titre. Aucun travail de fusion.

---

### Tableau récapitulatif

| # | Question | Décision | Fondement |
|---|---|---|---|
| **Q1** | Critères cochés en direct ? | **Jamais** — affichés après soumission | Spec §6 : la solution de référence ne quitte pas le serveur ; une sonde continue contournerait le coût des indices |
| **Q2** | Console toujours visible ? | **Oui**, dock permanent et repliable, état vide si l'équipement n'a pas de CLI | Stabilité de la mise en page : un redimensionnement subi est pire qu'un espace occupé |
| **Q3** | Fusionner studio et carte ? | **Non** — navigation bidirectionnelle | Mesuré : 22,3 ko contre 4 080 ko ; Vite sépare déjà les bundles |
