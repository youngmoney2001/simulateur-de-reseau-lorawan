# Audit clavier du studio

Généré par `web/tests/e2e/audit-clavier.mjs`.

> **Audit interrompu :** TimeoutError : Waiting for selector `.device-win[data-node-id="capteur-a"]` failed
>
> Les états mesurés avant l'interruption sont rapportés ci-dessous. Les états manquants n'ont pas été mesurés : ils ne sont pas sains, ils sont inconnus.

**32 problème(s)** sur 4 états mesurés et 92 éléments atteints.

## observation · Simulation

30 problème(s) · 3 élément(s) dans l'ordre de tabulation

### non atteignable au clavier (30)

| élément | détail |
|---|---|
| select#mode-select | « Conception Étude » est affiché et interactif, mais absent de l'ordre |
| button.zone-btn#pick-origin | « Choisir la zone en cliquant sur la carte » est affiché et interactif, mais absent de l'ordre |
| input#origin-coords | « (sans nom) » est affiché et interactif, mais absent de l'ordre |
| button.zone-btn#recenter | « Recentrer la carte sur la zone » est affiché et interactif, mais absent de l'ordre |
| select#terrain-select | « (sans nom) » est affiché et interactif, mais absent de l'ordre |
| a.applink#map-link | « Situer ce réseau sur la carte 3D » est affiché et interactif, mais absent de l'ordre |
| button.view-tab | « Carte 3D » est affiché et interactif, mais absent de l'ordre |
| button.view-tab.active | « Plan » est affiché et interactif, mais absent de l'ordre |
| button.tool.active | « Sélection » est affiché et interactif, mais absent de l'ordre |
| button.tool | « Déplacer » est affiché et interactif, mais absent de l'ordre |
| button.tool | « Supprimer » est affiché et interactif, mais absent de l'ordre |
| button.tool | « Inspecter » est affiché et interactif, mais absent de l'ordre |
| button.tool | « Trame » est affiché et interactif, mais absent de l'ordre |
| button.tool#new-session | « Nouvelle session » est affiché et interactif, mais absent de l'ordre |
| button.tool.danger#delete-session | « Supprimer la session » est affiché et interactif, mais absent de l'ordre |
| button.tool#save-chantier | « Enregistrer le chantier (équipements, ré » est affiché et interactif, mais absent de l'ordre |
| button.tool#load-chantier | « Ouvrir un chantier depuis un fichier, da » est affiché et interactif, mais absent de l'ordre |
| button.tool.active | « Passerelles » est affiché et interactif, mais absent de l'ordre |
| button.tool | « LoRaCapteurs » est affiché et interactif, mais absent de l'ordre |
| button.tool | « Serveur » est affiché et interactif, mais absent de l'ordre |
| button.tool | « Passerelle frontière — glissez sur la ca » est affiché et interactif, mais absent de l'ordre |
| button.tool | « Passerelle relais — glissez sur la carte » est affiché et interactif, mais absent de l'ordre |
| select#session-select | « bgn2pbPs · 3 équip. » est affiché et interactif, mais absent de l'ordre |
| button.tab.active | « Simulation » est affiché et interactif, mais absent de l'ordre |
| button.tab | « Journal » est affiché et interactif, mais absent de l'ordre |
| button.tab | « Trame » est affiché et interactif, mais absent de l'ordre |
| button.tab | « Exercice » est affiché et interactif, mais absent de l'ordre |
| input#seed | « (sans nom) » est affiché et interactif, mais absent de l'ordre |
| button#simulate | « Simuler » est affiché et interactif, mais absent de l'ordre |
| input#adr-toggle | « (sans nom) » est affiché et interactif, mais absent de l'ordre |

<details><summary>ordre de tabulation</summary>

| rang | élément | rôle | nom accessible | indicateur |
|---|---|---|---|---|
| 1 | input#join-toggle | input | Jointure OTAA (join-request) | oui |
| 2 | input#confirmed-toggle | input | Trames confirmées (ACK) | oui |
| 3 | input#battery-mah | input | 2400 | oui |

</details>

## observation · Journal

0 problème(s) · 32 élément(s) dans l'ordre de tabulation

Aucun problème.

<details><summary>ordre de tabulation</summary>

| rang | élément | rôle | nom accessible | indicateur |
|---|---|---|---|---|
| 1 | select#mode-select | select | Mode Conception Étude | oui |
| 2 | button.zone-btn#pick-origin | button | Choisir la zone en cliquant sur la carte | oui |
| 3 | input#origin-coords | input | 4.051100, 9.767900 | oui |
| 4 | button.zone-btn#recenter | button | Recentrer la carte sur la zone | oui |
| 5 | select#terrain-select | select | Relief | oui |
| 6 | a.applink#map-link | a | Situer ce réseau sur la carte 3D | oui |
| 7 | button.view-tab | tab | Carte 3D | oui |
| 8 | button.view-tab.active | tab | Plan | oui |
| 9 | button.tool.active | button | Sélection | oui |
| 10 | button.tool | button | Déplacer | oui |
| 11 | button.tool | button | Supprimer | oui |
| 12 | button.tool | button | Inspecter | oui |
| 13 | button.tool | button | Trame | oui |
| 14 | button.tool#new-session | button | Nouvelle session | oui |
| 15 | button.tool.danger#delete-session | button | Supprimer la session | oui |
| 16 | button.tool#save-chantier | button | Enregistrer le chantier (équipements, réglages,  | oui |
| 17 | button.tool#load-chantier | button | Ouvrir un chantier depuis un fichier, dans une s | oui |
| 18 | button.tool.active | button | Passerelles | oui |
| 19 | button.tool | button | LoRaCapteurs | oui |
| 20 | button.tool | button | Serveur | oui |
| 21 | button.tool | button | Passerelle frontière — glissez sur la carte, ou  | oui |
| 22 | button.tool | button | Passerelle relais — glissez sur la carte, ou cli | oui |
| 23 | select#session-select | select | Session bgn2pbPs · 3 équip. | oui |
| 24 | button.tab | tab | Simulation | oui |
| 25 | button.tab.active | tab | Journal | oui |
| 26 | button.tab | tab | Trame | oui |
| 27 | button.tab | tab | Exercice | oui |
| 28 | button#play-toggle | button | Lecture | oui |
| 29 | select#play-speed | select | Vitesse ×1×10×60×300 | oui |
| 30 | input#play-clock | input | Instant de la simulation | oui |
| 31 | button.journal-head | button | 0.000 s · capteur-a · uplink · received | oui |
| 32 | button.journal-head | button | 0.000 s · capteur-b · uplink · lost_collision | oui |

</details>

## observation · Trame

0 problème(s) · 28 élément(s) dans l'ordre de tabulation

Aucun problème.

<details><summary>ordre de tabulation</summary>

| rang | élément | rôle | nom accessible | indicateur |
|---|---|---|---|---|
| 1 | select#mode-select | select | Mode Conception Étude | oui |
| 2 | button.zone-btn#pick-origin | button | Choisir la zone en cliquant sur la carte | oui |
| 3 | input#origin-coords | input | 4.051100, 9.767900 | oui |
| 4 | button.zone-btn#recenter | button | Recentrer la carte sur la zone | oui |
| 5 | select#terrain-select | select | Relief | oui |
| 6 | a.applink#map-link | a | Situer ce réseau sur la carte 3D | oui |
| 7 | button.view-tab | tab | Carte 3D | oui |
| 8 | button.view-tab.active | tab | Plan | oui |
| 9 | button.tool.active | button | Sélection | oui |
| 10 | button.tool | button | Déplacer | oui |
| 11 | button.tool | button | Supprimer | oui |
| 12 | button.tool | button | Inspecter | oui |
| 13 | button.tool | button | Trame | oui |
| 14 | button.tool#new-session | button | Nouvelle session | oui |
| 15 | button.tool.danger#delete-session | button | Supprimer la session | oui |
| 16 | button.tool#save-chantier | button | Enregistrer le chantier (équipements, réglages,  | oui |
| 17 | button.tool#load-chantier | button | Ouvrir un chantier depuis un fichier, dans une s | oui |
| 18 | button.tool.active | button | Passerelles | oui |
| 19 | button.tool | button | LoRaCapteurs | oui |
| 20 | button.tool | button | Serveur | oui |
| 21 | button.tool | button | Passerelle frontière — glissez sur la carte, ou  | oui |
| 22 | button.tool | button | Passerelle relais — glissez sur la carte, ou cli | oui |
| 23 | select#session-select | select | Session bgn2pbPs · 3 équip. | oui |
| 24 | button.tab | tab | Simulation | oui |
| 25 | button.tab | tab | Journal | oui |
| 26 | button.tab.active | tab | Trame | oui |
| 27 | button.tab | tab | Exercice | oui |
| 28 | div.tab-body | div | Trame LoRaWAN MHDR40unconfirmed_data_upDevAddr6D | oui |

</details>

## observation · Exercice

2 problème(s) · 29 élément(s) dans l'ordre de tabulation

### non atteignable au clavier (2)

| élément | détail |
|---|---|
| button#hint | « Indice » est affiché et interactif, mais absent de l'ordre |
| button#submit | « Noter » est affiché et interactif, mais absent de l'ordre |

<details><summary>ordre de tabulation</summary>

| rang | élément | rôle | nom accessible | indicateur |
|---|---|---|---|---|
| 1 | select#mode-select | select | Mode Conception Étude | oui |
| 2 | button.zone-btn#pick-origin | button | Choisir la zone en cliquant sur la carte | oui |
| 3 | input#origin-coords | input | 4.051100, 9.767900 | oui |
| 4 | button.zone-btn#recenter | button | Recentrer la carte sur la zone | oui |
| 5 | select#terrain-select | select | Relief | oui |
| 6 | a.applink#map-link | a | Situer ce réseau sur la carte 3D | oui |
| 7 | button.view-tab | tab | Carte 3D | oui |
| 8 | button.view-tab.active | tab | Plan | oui |
| 9 | button.tool.active | button | Sélection | oui |
| 10 | button.tool | button | Déplacer | oui |
| 11 | button.tool | button | Supprimer | oui |
| 12 | button.tool | button | Inspecter | oui |
| 13 | button.tool | button | Trame | oui |
| 14 | button.tool#new-session | button | Nouvelle session | oui |
| 15 | button.tool.danger#delete-session | button | Supprimer la session | oui |
| 16 | button.tool#save-chantier | button | Enregistrer le chantier (équipements, réglages,  | oui |
| 17 | button.tool#load-chantier | button | Ouvrir un chantier depuis un fichier, dans une s | oui |
| 18 | button.tool.active | button | Passerelles | oui |
| 19 | button.tool | button | LoRaCapteurs | oui |
| 20 | button.tool | button | Serveur | oui |
| 21 | button.tool | button | Passerelle frontière — glissez sur la carte, ou  | oui |
| 22 | button.tool | button | Passerelle relais — glissez sur la carte, ou cli | oui |
| 23 | select#session-select | select | Session bgn2pbPs · 3 équip. | oui |
| 24 | button.tab | tab | Simulation | oui |
| 25 | button.tab | tab | Journal | oui |
| 26 | button.tab | tab | Trame | oui |
| 27 | button.tab.active | tab | Exercice | oui |
| 28 | select#exercise-start | select | Exercice Configurer une passerelle frontière sur | oui |
| 29 | button#start-exercise | button | Démarrer | oui |

</details>

TOTAL : 32 problème(s)
