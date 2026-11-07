# Conception — l'atelier 3D

Objet : rapprocher l'application du workflow décrit par l'utilisateur, qui est celui de Packet
Tracer appliqué à un réseau LoRaWAN réel.

> **Le workflow demandé, en ses propres termes :**
> 1. je choisis la zone où je veux tester mon réseau ;
> 2. comme dans Cisco, j'ai une carte 3D centrée sur ce lieu devant moi, et mes équipements
>    disponibles ;
> 3. je pose un équipement par glisser-déposer, **ou** je définis directement ses coordonnées
>    géographiques ;
> 4. je le paramètre comme un vrai équipement LoRaWAN, dans des fenêtres de configuration
>    propres, **illustrées** et **conformes** ;
> 5. la configuration finie, je lance la simulation et je visualise le comportement du réseau
>    avec toutes les informations possibles.

---

## 1. Écart entre le workflow demandé et l'existant

| # | Étape demandée | Existant aujourd'hui | Écart |
|---|---|---|---|
| 1 | Choisir la zone | Deux champs latitude/longitude dans l'en-tête | Aucun choix de lieu : il faut connaître les degrés |
| 2 | Carte 3D comme plan de travail | Carte 3D = page de résultats **distincte** ; le studio est un plan 2D en mètres | **Manquant** : la 3D n'est pas le lieu où l'on travaille |
| 3a | Poser par glisser-déposer | Sur le plan SVG 2D uniquement | Impossible sur la 3D |
| 3b | Définir les coordonnées géographiques | `x_m` / `y_m`, en mètres | **Manquant** : aucune saisie en latitude/longitude |
| 4 | Fenêtres illustrées et conformes | Formulaires numériques (7 champs + plan régional) | Ni illustration, ni vue physique, ni indicateurs |
| 5 | Simulation et visualisation complète | Onglets Simulation, Journal, Trame, Exercice | Existe, mais séparé de la carte |

**Le changement de fond** : la carte 3D cesse d'être une page de résultats pour devenir la
surface de travail. Tout le reste découle de là.

---

## 2. Architecture retenue

### 2.1 Une seule page

Le studio absorbe la carte. `studio.html` devient :

```
┌──────────────────────────────────────────────────────────────┐
│ en-tête : session · zone choisie · origine · lien résultats  │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│              CARTE 3D (Cesium), centrée sur la zone          │
│              ← on y pose les équipements                     │
│                                                              │
│  ┌────────────┐                          ┌───────────────┐   │
│  │  palette   │                          │ observation   │   │
│  │ équipements│                          │ Simulation    │   │
│  │ disponibles│                          │ Journal       │   │
│  └────────────┘                          │ Trame         │   │
│                                          └───────────────┘   │
├──────────────────────────────────────────────────────────────┤
│ barre d'état                                                  │
└──────────────────────────────────────────────────────────────┘
        + fenêtres flottantes d'équipement (déjà construites)
```

Le plan 2D ne disparaît pas : il devient une **vue logique** secondaire, utile pour régler
finement des distances, accessible par un onglet. La 3D est la vue géographique ; le plan est
la vue métrique. Les deux montrent les mêmes équipements.

### 2.2 Coordonnées : degrés en façade, mètres au moteur

Le moteur radio travaille en mètres autour d'une origine. L'utilisateur parle en degrés. Les
deux coexistent par une conversion exacte et réversible, celle-là même que le serveur utilise
dans `geo.py` :

```
lat = lat0 + (y / R) · 180/π
lon = lon0 + (x / (R · cos(lat0))) · 180/π        R = 6 371 000 m
```

**Règle** : l'interface affiche et accepte la latitude/longitude. La conversion en mètres a
lieu au moment de l'appel API. Rien n'est stocké deux fois, donc rien ne peut désynchroniser.

### 2.3 La zone est l'ancre

Choisir la zone fixe `lat0 / lon0`. Trois voies, volontairement redondantes :

1. **Cliquer sur la carte** : un clic pose l'origine, la caméra s'y place ;
2. **Chercher un lieu** : saisie libre, résolue sans service distant (voir §5) ;
3. **Saisir les degrés** : les champs déjà en place.

**Question ouverte** : que fait-on si la zone change alors que des équipements existent ?
Voir §4, décision D3.

---

## 3. Positionner un équipement

Deux voies, comme demandé, et elles doivent donner exactement le même résultat.

**Glisser-déposer.** Depuis la palette vers la carte. Le point lâché est converti en position
géographique, puis en mètres. Retour visuel pendant le glissement : un repère suit le curseur
et affiche la latitude/longitude visée.

**Saisie directe.** Dans la fenêtre de l'équipement, onglet *Position* : latitude, longitude,
et altitude. Les trois sont modifiables à tout moment, pas seulement à la création.

---

## 4. Décisions de conception

| # | Décision | Alternative écartée | Pourquoi |
|---|---|---|---|
| **D1** | La carte 3D devient la surface de travail | Deux pages qui se complètent | Le workflow demande la carte « devant soi » ; deux pages obligent à jongler |
| **D2** | Degrés en façade, mètres au moteur | Tout stocker en degrés | Le moteur exige des mètres ; doubler le stockage créerait deux vérités |
| **D3** | Changer de zone **repositionne** les équipements | Exiger une nouvelle session | Le réseau garde sa géométrie ; seule l'ancre bouge. Réversible |
| **D4** | Le plan 2D reste, en vue secondaire | Le supprimer | Il reste le meilleur outil pour régler des distances précises |
| **D5** | Illustrations en **SVG dessiné** | Images bitmap, photographies | Aucune dépendance externe, net à toute échelle, style homogène |
| **D6** | N'exposer que les paramètres **réellement simulés** | Ajouter ADR, classe, OTAA | Le moteur ne les simule pas : les montrer mentirait |

### D6 est la plus importante

Une fenêtre « conforme » ne peut exposer que ce que le moteur calcule. L'inventaire exact,
relevé dans le contrat d'API (`SensorSettings`) :

| Paramètre | Bornes |
|---|---|
| `spreading_factor` | 7 … 12 |
| `payload_bytes` | 0 … 255 |
| `tx_power_dbm` | −10 … 30 |
| `period_s` | > 0 … 86 400 |
| `messages` | 1 … 1 000 |
| `start_spread_s` | 0 … 86 400 |
| `region` | plan régional RP002, ou celui des passerelles |
| `channel_freq_hz` | 137 MHz … 3 GHz (facultatif) |

Huit paramètres, pas un de plus. **Le reste sera affiché, jamais proposé à la saisie** :
temps d'émission calculé depuis le SF et la charge utile, respect du rapport cyclique selon le
plan régional, sensibilité de réception. Ces grandeurs se déduisent des huit paramètres et de
RP002-1.0.5 — elles informent sans simuler ce qui ne l'est pas.

---

## 5. Difficultés connues

**Imagerie de fond.** La carte utilise des tuiles distantes. Elles sont inaccessibles depuis
l'environnement de développement, ce qui rend toute vérification visuelle impossible ici — la
CI, elle, y accède. Le fond doit donc rester optionnel et la carte rester lisible sans lui.

**Recherche de lieu.** Sans service de géocodage distant, la saisie libre ne peut pas être
résolue en degrés. Deux options : une liste de lieux prédéfinis (villes, zones d'étude), ou
accepter de dépendre d'un service externe. À trancher — voir §7.

**Performance.** Cesium et le plan 2D sur la même page : un seul contexte 3D, et le plan reste
en SVG. Le nombre d'équipements est borné par l'API, ce qui limite le risque.

---

## 6. Phasage

| Phase | Contenu | Dépend de |
|---|---|---|
| **G** | La carte 3D dans le studio, centrée sur la zone ; les équipements existants y apparaissent | — |
| **H** | Positionnement : glisser-déposer depuis la palette, et saisie latitude/longitude/altitude | G |
| **I** | Choix de la zone : clic sur carte, lieux prédéfinis, champs de degrés | G |
| **J** | Fenêtres illustrées : vue physique dessinée en SVG pour chaque type | — |
| **K** | Indicateurs calculés : temps d'émission, rapport cyclique, sensibilité | J |
| **L** | Unification de la visualisation : la simulation se lit sur la carte | G |

Les phases **G** et **J** sont indépendantes : J peut avancer pendant G.

---

## 7. Questions tranchées

1. **Recherche de lieu** — *« le clic sur la carte, ou entrer les coordonnées d'un point sur le
   lieu »*. Aucun service de géocodage : ni liste prédéfinie, ni résolution en ligne. La zone
   se choisit en cliquant sur la carte ou en saisissant les degrés. Le §2.3 est donc réduit à
   deux voies, la recherche étant abandonnée.
2. **Changement de zone** — repositionner les équipements. La décision **D3** est confirmée :
   le réseau conserve sa géométrie, seule l'ancre géographique bouge.
3. **Imagerie** — question reportée : elle ne conditionne pas la phase G. Le fond reste celui
   déjà en place, avec la réserve du §5.

**Ordre de travail** : la phase **G** d'abord (la carte 3D comme plan de travail). La phase J
reste indépendante et viendra ensuite.

---

## 8. Ce que ce document ne prétend pas

Il ne décrit pas encore l'apparence précise des fenêtres illustrées, ni le détail des
indicateurs calculés : ces points seront arrêtés phase J et K, en s'appuyant sur les tables
RP002-1.0.5 déjà relevées.

Il ne prétend pas non plus que l'application deviendra Packet Tracer. Le workflow sera
respecté ; la ressemblance visuelle reste un jugement qui appartient à l'utilisateur.
