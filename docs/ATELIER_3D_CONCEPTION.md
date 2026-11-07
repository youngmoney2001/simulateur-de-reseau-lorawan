# Atelier 3D — concevoir son réseau LoRaWAN comme dans Packet Tracer

Source de vérité de la mission en cours. Ce document a été perdu une fois avec une
réinitialisation du dépôt (il n'était pas suivi par git) : il est donc commité désormais.

## 1. Les six étapes du workflow demandé

L'utilisateur décrit son attente ainsi :

> je choisie la zone où je veux tester mon reseau, puis comme dans cisco j'ai une carte 3D
> centree sur ce lieu qui est devant moi et mes equipements disponible. je peux poster un
> equipement par drag and drop ou definir directement les coordonnees geometrique du lieux ou
> je veux le placer, je peux les parametrer comme de vrai equipements lorawan, avec des
> fenetres de cnfiguration propre, illustrees et conforme pour chaque equipement une fois la
> configuration finie je lance la simulation et je visualise le comportement du reseau avec
> toutes les infos possible.

| # | Étape | État | Écart restant |
|---|---|---|---|
| 1 | Choisir la zone | **à faire (I)** | aucun choix de lieu ; il faut taper des degrés |
| 2 | Carte 3D comme plan de travail | **fait (G)** | — |
| 3a | Pose par glisser-déposer | **fait (H)** | — |
| 3b | Pose par coordonnées | **fait (H)** | — |
| 4 | Fenêtres propres, illustrées, conformes | **fait (J)** | — |
| 5 | Simulation et visualisation | **à faire (K, L)** | existe, mais séparé de la carte |

## 2. Architecture

```
web/src/studio/
  geo.js          conversion mètres ↔ degrés — AUCUNE dépendance, donc testable
  device-art.js   DEVICE_SPECS (données) + dessin SVG — séparés pour tester les données
  topology.js     géométrie du plan, validation des formulaires — logique pure
  map3d.js        Cesium — délègue la conversion à geo.js
  main.js         contrôleur : câble les modules purs au DOM
```

La règle qui tient cet assemblage : **tout ce qui engage la conformité est pur et testé**. Le
DOM et Cesium ne portent que de la mécanique.

## 3. Décisions arrêtées

| | Décision | Conséquence |
|---|---|---|
| **D1** | La carte 3D est la surface de travail | le plan 2D devient la vue métrique de secours |
| **D2** | Degrés en façade, mètres au moteur | conversion exacte et réversible, testée par aller-retour et par parité avec `geo.py` |
| **D3** | Changer de zone repositionne les équipements | la géométrie du réseau est conservée, seule l'ancre géographique bouge |
| **D4** | Le plan 2D reste une vue secondaire | il sert à régler des distances au pixel |
| **D5** | Illustrations en SVG dessiné | aucune image externe, aucun service distant |
| **D6** | N'exposer que les huit paramètres simulés | le reste est affiché, jamais proposé à la saisie — barrière testée |

## 4. Phase H — poser un équipement

### Les deux gestes

1. **Glisser depuis la palette** : le `pointerdown` part du bouton, un repère suit le curseur,
   la carte montre le point d'arrivée, le relâchement crée l'équipement. `Échap` annule.
2. **Saisir les coordonnées** : en degrés, dans le formulaire d'ajout ou dans la fenêtre de
   l'équipement (qui les affiche et permet de les corriger).

### Pourquoi l'écoute est en capture

Le canevas de Cesium porte ses propres écouteurs, posés à la création du `Viewer` donc **avant**
les nôtres. Un `pointerdown` sur le canevas déclencherait une rotation du globe avant qu'on ait
pu dire « non, c'est un équipement ». On écoute donc sur le conteneur `#cesium` en phase de
capture : l'événement nous atteint avant le canevas, et `stopPropagation` l'empêche d'y arriver.

Écouter directement sur le canevas ne marche pas, quel que soit le mode de capture : nos
écouteurs y sont seconds dans l'ordre d'appel.

### Trois pièges rencontrés

- **Le relâchement est aussi un clic.** Un glisser se termine par un `pointerup` que Cesium lit
  comme un clic, lequel déplace l'origine de la zone. D'où `setIgnoreClick()`, une trappe
  temporelle posée à la fin de chaque geste.
- **Un bouton qui ne répond qu'au pointeur devient inutilisable au clavier.** La palette garde
  donc son `onclick`, neutralisé juste après un dépôt réussi pour éviter le double ajout.
- **La carte montrait la planète entière.** Sans cadrage initial, un dépôt au centre de l'écran
  tombait à des milliers de kilomètres de l'origine. `syncMap` recadre donc à la première
  apparition, pas seulement quand l'ancre change.

### Identifier l'équipement visé

`nodeAt()` projette chaque équipement à l'écran et garde le plus proche dans un rayon de 22 px,
plutôt que d'appeler `scene.pick`. C'est déterministe, ça marche quand le point est dessiné sans
profondeur (`disableDepthTestDistance`), et ça ne casse pas si Cesium change la forme de ses
objets de sélection d'une version à l'autre.

## 5. Difficultés connues

- **Imagerie de fond distante inaccessible** depuis l'environnement de développement comme
  depuis la CI. Le fond local Natural Earth II est donc le garant ; le fond routier reste une
  surcouche optionnelle. La carte est lisible sans lui.
- **Aucun navigateur installable dans le bac à sable** (`npx puppeteer browsers install chrome`
  échoue, réseau restreint). **La CI est le seul moyen d'observer un rendu**, et l'e2e le seul
  endroit où Cesium tourne.
- **Aucune vision sur les images** : `read_file` sur un PNG ne renvoie rien d'exploitable. Les
  captures sont donc jugées par des **mesures** (`web/tests/e2e/audit.mjs`, comptage de teintes
  en PIL), jamais à l'œil.
- **Le dépôt peut se réinitialiser entre les tours.** Voir §6.

## 6. Procédure si le dépôt se réinitialise

Elle a déjà servi deux fois, sans aucune perte.

```bash
git fetch origin <branche>:refs/remotes/origin/<branche>
git log -3 --oneline origin/<branche>                  # le travail est-il toujours là ?
git merge-base --is-ancestor HEAD origin/<branche>     # avance rapide = restauration sans perte
```

Puis, avant d'avancer :

1. déplacer les fichiers de sondage non suivis vers `/tmp/arena_scratch*` ;
2. `git stash push` des modifications suivies ;
3. pour chaque fichier non suivi qui **bloque** le merge, comparer
   `git show origin/<branche>:<f> | sha256sum` à `sha256sum <f>` — ne supprimer que si
   identique ;
4. `git merge --ff-only origin/<branche>`.

**Jamais de `git reset --hard` sans accord explicite.** L'environnement (`pyenv/`, `build/`,
`web/node_modules`, `web/public/cesium`) ne persiste pas non plus et doit être reconstruit.
