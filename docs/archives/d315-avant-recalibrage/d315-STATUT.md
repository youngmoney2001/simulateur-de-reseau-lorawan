# D3.15 — Statut des conclusions historiques

*Phase B du protocole d'archivage (§24.5.1). Verdict porté **conclusion par conclusion**, pour
que rien de ce qui a été établi ne soit effacé, et que rien de ce qui est caduc ne continue à
passer pour démontré.*

- **Jeu archivé** : `docs/archives/d315-avant-recalibrage/2026-11-06/` (copie intégrale)
- **Commit de référence** : `72fc6cb`
- **Date du statut** : 2026-11-06

## Les trois verdicts

| Verdict | Signification |
|---|---|
| **démontrée** | Ne dépend d'aucune charge non conforme. Conservée telle quelle. |
| **invalidée** | Repose sur une charge que les fenêtres ne peuvent pas porter, ou sur une configuration refusée par P1. |
| **non démontrée** | Le test passe mais ne démontre rien : scène muette, ou hors de portée. |

> Un quatrième état, transitoire : **en attente du miroir C++** — la conclusion est
> vraisemblablement correcte, mais la parité ne peut pas être établie tant que le cœur
> n'applique pas la validation.

## Le fait qui commande tout le reste

Mesuré sur la scène de référence, **à la charge historique de 120 octets** :

| Région | N(RX1) | N(RX2) | émises | rx2 | aucune |
|---|---|---|---|---|---|
| EU868 (SF11) | 51 | 51 | **0** | 0 | 440 |
| US915 (SF11) | — | — | **refusée** | — | — |
| AS923 (SF7) | 222 | 51 | 371 | **0** | 191 |
| AU915 (SF7) | 222 | 53 | 562 | **0** | 0 |
| IN865 (SF7) | 222 | 51 | 371 | **0** | 191 |
| KR920 (SF9) | 115 | 51 | **0** | 0 | 210 |
| RU864 (SF10) | 51 | 51 | **0** | 0 | 800 |

**Aucune région ne produit le moindre repli RX2 à 120 octets**, et trois d'entre elles
n'émettent **aucune** descente. La scène de référence de D3.15 est donc, à sa charge
historique, **partiellement ou totalement muette**.

La même scène à **40 octets** s'anime immédiatement (EU868 : 260 RX1, **120 replis**, 60
pertes). Le défaut n'est donc pas la scène, mais la charge — exactement le diagnostic du
§23.8.

## Conclusions invalidées

| # | Conclusion historique | Cause |
|---|---|---|
| 1 | `test_chronologie_complete_exerce_rx1_et_rx2` | scène muette : 0 émission sur 440 jobs |
| 2 | `test_airtime_et_sensibilite_suivent_la_fenetre_emise` | aucune fenêtre émise à comparer |
| 3 | `test_le_sf12_nest_juge_ni_favorable_ni_defavorable` | contribue sur des trames jamais émises |
| 4 | `test_chaque_region_exerce_le_repli` (le gardien) | `rx2 = 0` dans les sept régions |
| 5 | `test_les_parametres_rx2_du_profil_atteignent_le_coeur[US915]` | **P1** : SF11 sans DR montant |
| 6 | `test_frequences_distinctes_le_join_accept_porte_la_bonne[US915-11]` | **P1** |
| 7 | `test_frequences_distinctes_le_join_accept_porte_la_bonne[US915-12]` | **P1** |
| 8 | `test_le_repli_ajoute_de_lantenne_et_nen_retire_jamais[US915]` | **P1** |
| 9 | `test_quand_la_fenetre_de_repli_est_plus_rapide_le_repli_nest_jamais_perdant[US915]` | **P1** |
| 10 | `test_chaque_region_a_un_profil_rx2_distinct_mais_pas_toujours_une_frequence_distincte` | **P1** |

## En attente du miroir C++

| # | Conclusion | Situation |
|---|---|---|
| 11 | `test_parite_integrale_sur_la_chronologie_complete` | l'oracle filtre, le cœur pas encore |
| 12 | `test_parite_et_repli_effectif_par_region[*]` | idem ; de plus EU868/KR920/RU864 sont muettes à 120 |

Ces divergences sont **attendues et non accidentelles** : elles disparaîtront avec
`lsim_plan_downlinks_v3` (§24.1), puis avec le recalibrage des scènes.

## Conclusions préservées (démontrées)

Indépendantes de la taille des charges : elles portent sur le Join-Accept, la couche MAC, la
sensibilité par fenêtre, l'absence de région ou le rejeu.

`test_d_i3_1_le_join_accept_rx2_est_rapporte_a_sa_frequence` ·
`test_d_i3_2_la_reception_suit_la_fenetre_dans_ack_mac` ·
`test_ack_fidelite_absolue_le_seuil_suit_la_fenetre` ·
`test_ack_rssi_entre_les_deux_sensibilites` ·
`test_frequences_confondues_la_fenetre_nest_pas_inferee_de_la_frequence` ·
`test_fidelite_absolue_le_join_accept_rx1_reste_en_rx1` ·
`test_un_scenario_sans_region_ne_replie_jamais` ·
`test_classe_c_le_seuil_suit_la_phy_de_la_fenetre_visee` ·
`test_le_rejeu_porte_la_fenetre_dont_la_phy_la_servi` ·
`test_les_jointures_declarees_restent_en_rx1` ·
`test_a_faible_puissance_passerelle_la_correction_change_le_resultat` ·
`test_plusieurs_descentes_successives_par_terminal` ·
`test_les_quatre_regions_exigees_ne_partagent_pas_le_meme_repli`

## Réserve de vacuité — à lever au recalibrage

**41 des 56 cas passent encore.** Ce succès n'est pas une preuve : une assertion portant sur un
ensemble vide est vraie. En particulier :

- `test_le_repli_ajoute_de_lantenne_et_nen_retire_jamais` compare deux occupations ; quand
  les deux sont nulles, l'inégalité est satisfaite **sans rien démontrer**.
- `test_quand_la_fenetre_de_repli_est_plus_rapide_le_repli_nest_jamais_perdant` et
  `test_le_sf12_…` s'auto-sautent honnêtement quand aucune fenêtre n'est émise.

Le recalibrage (phase C) devra donc vérifier, pour **chaque** scène retenue, le critère de
non-vacuité du §25.7 :

```
rx1 > 0  et  rx2 > 0     (et non pas seulement « le test passe »)
```

## Point ouvert — US915 et AU915 résistent au recalibrage

À 40 octets, cinq régions sur sept produisent des replis (EU868 120, AS923 84, IN865 84,
KR920 33, RU864 120). **US915 et AU915 n'en produisent aucun**, non par excès de taille mais
par **absence de contention** : leurs descentes descendantes sont rapides (SF10/500 et SF7/500)
et l'espacement moyen entre ouvertures de fenêtres (≈ 1 s) est environ trente fois supérieur au
temps d'antenne (≈ 30 ms).

Trois leviers essayés, sans succès à ce stade :

| Levier | Effet observé |
|---|---|
| Augmenter le nombre de terminaux (60 → 260) | les uplinks se perdent en collision : le nombre de jobs **décroît** |
| Regrouper les départs (`spread` 60 → 2 s) | idem, jobs 562 → 180 |
| Ralentir le SF (AU915 SF7 → SF12) | temps d'antenne ×40, mais jobs 562 → 40 : toujours aucune contention |

Le levier restant est la **densité temporelle des ouvertures** — réduire `period` et augmenter
`messages` pour concentrer les descentes sans concentrer les montantes. Ce point est laissé
ouvert ; il conditionne la phase C pour ces deux régions.

---

*Ce document **n'efface** aucun résultat historique. Il enregistre ce qui demeure établi, ce
qui est caduc, et ce qui n'a jamais été démontré.*
