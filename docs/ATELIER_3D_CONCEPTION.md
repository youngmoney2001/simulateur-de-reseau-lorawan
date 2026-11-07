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
| 5a | Indicateurs calculés | **fait (K)** | — |
| 5b | Visualisation unifiée sur la carte | **fait (L)** | — |

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

### La conversion a changé de signature sans ses appelants

En créant `geo.js` j'ai pris l'origine en un objet `{lat, lon}`, là où l'ancienne forme la
prenait en deux nombres. Les huit appelants passaient encore **quatre** arguments : le
troisième, un nombre, servait d'origine, `origine.lat` valait `undefined`, et la conversion
rendait `NaN` **sans rien dire**. Le `NaN` remontait ensuite par deux chemins : `setNodes` le
donnait à Cesium, qui levait « normalized result is not a number » et interrompait le
rafraîchissement de toute l'interface ; et la fenêtre d'équipement affichait « NaN, NaN ».

Trois remèdes, pas un seul : appelants corrigés ; `geo.js` refuse une origine inexploitable
par une `TypeError` qui la nomme ; `setNodes` ignore un équipement fautif au lieu de priver la
carte du reste du réseau.

**Leçon** : une fonction qui rend `NaN` quand on la nourrit mal est un défaut. Une fonction
qui échoue en nommant la faute est un garde-fou. Choisir la seconde a transformé deux
exécutions de CI perdues en un message lisible.

### Identifier l'équipement visé

`nodeAt()` projette chaque équipement à l'écran et garde le plus proche dans un rayon de 22 px,
plutôt que d'appeler `scene.pick`. C'est déterministe, ça marche quand le point est dessiné sans
profondeur (`disableDepthTestDistance`), et ça ne casse pas si Cesium change la forme de ses
objets de sélection d'une version à l'autre.

## 4bis. Phase K — indicateurs calculés

Module pur `web/src/studio/metrics.js` (ni DOM, ni Cesium, ni réseau), affiché sous la table
des passerelles dans l'onglet Simulation.

### Ce qui est affiché

Onze indicateurs, tous dérivés des seuls compteurs du run (`summary.totals`, `summary.gateway`
ou `summary.gateways[]`, lignes `devices`). Chaque bloc affiche **la formule qui le produit** :
un nombre sans sa formule n'est pas vérifiable.

| Indicateur | Formule | Ce qu'il apprend |
|---|---|---|
| Taux de livraison | reçues ÷ émises | part des trames arrivées au serveur |
| Répartition des pertes | 4 causes, en parts de 100 % | *pourquoi* les trames sont perdues |
| Collisions parmi les audibles | collisions ÷ trames audibles | une trame hors portée ne peut pas entrer en collision |
| Charge offerte | Σ temps d'antenne ÷ fenêtre | charge ALOHA **G**, dépasse librement 1 |
| Occupation du canal | union des intervalles ÷ fenêtre | temps d'antenne réellement pris, borné à 100 % |
| Temps d'antenne moyen | Σ temps d'antenne ÷ émises | durée d'une trame sur les ondes |
| Débit utile | reçues ÷ durée d'observation | trames livrées par seconde |
| Simultanéité maximale | maximum sur la fenêtre | pics de concurrence |
| Énergie par message | moyenne des dispositifs | coût d'un message, écoute comprise |
| Énergie du run | Σ (énergie par message × émis) | coût total du scénario |
| Courant moyen | moyenne des dispositifs | µA sur la période, veille comprise |

Les trois derniers n'apparaissent qu'avec un profil énergie. Sans lui, ils sont **absents**,
jamais affichés à zéro : un `0 J` fabriqué est indiscernable d'une mesure nulle.

### Deux pièges que la mesure a écartés

**Charge offerte ≠ occupation du canal.** `totals.airtime_ns` **cumule** les trames, y compris
celles qui se recouvrent. Rapporté à la fenêtre d'observation, il donne la charge offerte d'un
canal ALOHA — mesurée à **4,60** sur un run saturé de 40 dispositifs SF12 dont le PDR
s'effondre à 5 %. Le publier comme « occupation » ferait lire « 460 % ». `busy_ns`, lui, est
l'**union** des intervalles : son rapport est dans [0, 1]. Les deux sont affichés, séparément,
et un test verrouille qu'ils ne sont pas le même champ.

**Fenêtre et occupation : le maximum, jamais la somme.** Avec trois passerelles, sommer les
`observation_ns` compterait trois fois la même horloge de run et diviserait le débit par trois.

### Aucun verdict réglementaire

La phase K **mesure**, elle ne prononce pas de conformité. Raisons, vérifiées :

- `RunSummary` ne porte **pas** la région ; elle est portée par chaque groupe du scénario
  (`GroupModel.region`, optionnelle), et les lignes de dispositifs du run ne la répètent pas.
  Un verdict serait donc attribué à une région devinée.
- `RegionProfile.duty_cycle_limit` renvoie `None` pour **cinq des huit régions** (US915, AU915,
  AS923, KR920, IN865) : zéro sous-bande déclarée, aucune limite. EU868 renvoie 0,01 à 868,1 et
  868,3 MHz ; RU864 et AS923JP ont deux sous-bandes.
- `docs/REGULATORY_SOURCES.md` ne cite **aucune limite de duty cycle vérifiée pour EU868** : la
  valeur 1 % vient du code, pas d'une source.

Un test interdit l'apparition des mots « conforme », « non conforme », « limite légale » et
« dépasse la limite » dans un libellé ou une formule d'indicateur.

### Invariant qui fonde la répartition des pertes

`émises = reçues + sensibilité + collision + passerelle occupée`, vérifié sur le moteur avant
écriture du module : cinq configurations (chargée, saturée, hors portée, dispositif unique,
deux SF) × une et trois passerelles = **dix mesures, dix concordances**. `repartitionPertes`
signale une rupture (`coherent: false`) au lieu de la masquer.

### Test

`web/tests/metrics.test.mjs`, 22 tests, dont une **parité** sur une sortie réelle du serveur :
`web/tests/fixtures/run-metrics.json` est la réponse brute de `GET /runs/{id}/summary` et
`GET /runs/{id}/devices` sur un run à trois passerelles, deux groupes et profil énergie,
régénérable par `web/scripts/capture-metrics-fixture.py`. Les valeurs attendues sont
recalculées à la main — les reprendre du module en ferait une reformulation.

## 4ter. Phase L — le résultat se lit sur la carte

Avant : la carte colorait chaque équipement selon son **type** (`COULEURS[n.kind]`). Après un
run, elle colore selon son **résultat**. C'est là que se lit le comportement du réseau — dans
la géographie, pas dans un tableau.

### Répartition

La décision de couleur vit dans `metrics.js` (module pur, testé sans Cesium) ; la carte ne
fait que l'appliquer. Un dégradé continu a été écarté : il suggère une précision que la mesure
n'a pas, et rend deux équipements voisins indiscernables. Quatre paliers francs, qu'on peut
nommer dans une légende.

| Taux de livraison | Couleur |
|---|---|
| 95 % et plus | vert `#2ea043` |
| de 80 à 95 % | ambre `#9a6700` |
| de 50 à 80 % | orange `#bc4c00` |
| moins de 50 % | rouge `#b42318` |

Sans résultat pour un équipement, il garde sa **couleur de type**. Un équipement non mesuré
n'est pas un équipement en échec — le peindre en rouge serait un mensonge.

### Jointure, et pourquoi elle refuse de deviner

Une session studio compile **un groupe par équipement**, nommé d'après l'identifiant du
capteur (`study_compile.py`) : la jointure est donc directe. Un run issu d'un scénario YAML a
de vrais groupes (12 dispositifs, par exemple) sans équivalent dans la topologie.
`resultatsParNoeud` n'y colore **rien** plutôt que d'affecter à un équipement la moyenne d'un
groupe : ce serait un chiffre inventé. Le test le verrouille.

### Légende

Affichée seulement quand un run colore effectivement des équipements : une légende sans
résultat décrirait des couleurs absentes. Les libellés viennent de `metrics.js`, seule source
de l'échelle — les recopier ici les laisserait dériver de la couleur réellement peinte.

### Les deux vues

La carte 3D **et** le plan 2D portent la même lecture. Le plan pose un attribut `fill` quand un
résultat existe, et laisse la classe CSS du type décider sinon.

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
- **À fort grossissement, le fond local est flou.** La texture Natural Earth II fournie avec
  Cesium est faite pour une vue planétaire : à 960 m d'altitude, elle n'a plus de détail et la
  carte devient un aplat (mesuré : 73 % de pixels identiques dans la zone carte). Le fond
  routier, précis à l'échelle d'une ville, est distant et **injoignable depuis la CI** — donc
  invisible sur les captures. Chez l'utilisateur, qui a accès au réseau, la surcouche doit
  charger et le rendu devrait être net ; cela reste à vérifier avec lui. En attendant, la
  géométrie est bonne : les marqueurs d'équipement passent de 19 à 125 pixels visibles
  après le cadrage sur la zone.
- **Les journaux du runner sont hors de portée du réseau** (`results-receiver.actions.githubusercontent.com`). Le seul moyen de lire un échec est de le faire publier sur la PR par
  le workflow lui-même. Sur un événement `pull_request`, `context.ref` vaut `refs/pull/N/merge`
  : chercher la PR par branche ne trouvait rien, et le journal partait dans le vide. Le numéro
  est pris dans la charge utile quand il y est.

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
