# Modèle de masque de canaux (LinkADR ChannelMask), boucle fermée

Ce document décrit le modèle de canaux de la boucle fermée (passerelle unique, EU868) : refus,
attribution, exclusions, trace interne v3. Il sépare trois sources, qui ne doivent jamais être
confondues :

- **TS001-1.0.4** : protocole et réponses MAC (LinkADRReq / LinkADRAns, bits ACK, ordre des bits) ;
- **RP002-1.0.5** : paramètres régionaux (canaux par défaut, plan de canaux, index de puissance,
  débits, plage ChMaskCntl) ;
- **Choix du simulateur** : tout ce qui n'est défini par aucune des deux normes. Ces choix sont
  marqués `SimulatorPolicy` dans la trace.

## 1. Ce que dit la norme (sources normatives)

- TS001-1.0.4 Table 22 : bit 0 `ChannelMaskACK`, bit 1 `DataRateACK`, bit 2 `PowerACK`.
- TS001-1.0.4 Table 23 : `ChannelMaskACK` = 0 si le masque active un canal non défini, impose tous les
  canaux désactivés, ou est incompatible avec le débit ou la puissance résultants. `DataRateACK` = 0 si
  le débit est inconnu ou non supporté par les canaux actifs.
- TS001-1.0.4 §5.2 : un bit à 0 signifie échec ; le terminal conserve alors **tout** son état
  précédent (validation et application atomiques).
- RP002-1.0.5 §3.4.5 (EU863-870, Table 14) : ChMaskCntl 0 à 4 désignent des blocs de 16 canaux,
  5 désigne des blocs de 8 par les 10 bits de poids faible, 6 active tous les canaux définis, 7 est
  réservé et refusé avec `ChannelMaskACK` = 0. Le plan de canaux compte entre 24 et 80 canaux.
- RP002-1.0.5 Table 8 : canaux par défaut 868,1 / 868,3 / 868,5 MHz, DR0 à DR5.

## 2. Attribution d'un refus (D5, D7)

Une réponse négative est attribuée avec les seuls bits ACK et l'état **connu du serveur** (jamais
l'état privé du terminal) :

| Bits | Attribution | Exclusion posée |
|---|---|---|
| `DataRateACK` = 0 | le débit, même si `ChannelMaskACK` vaut aussi 0 (D5) | débit `pend_dr` |
| `PowerACK` = 0 | la puissance | index `pend_power` |
| `ChannelMaskACK` = 0 et `DataRateACK` = 1 | les canaux demandés et non acquittés | un canal par suspect |

Règles de l'attribution des canaux (**choix du simulateur**, pas une règle TS001) :

- les suspects sont `applied \ confirmed` : canaux du bloc 0 demandé, non acquittés par le dernier
  masque confirmé ;
- sur-approximation documentée : un suspect peut être valide et être exclu à tort ;
- un refus par canal n'exclut pas le masque entier. Un refus global bloquerait tout changement de
  masque, ce qui a été écarté.

Un bit à 0 est toujours un refus (D7) : aucun paramètre n'est appliqué si l'un des trois bits vaut 0.
Chaque bit rapporte la validité de son propre paramètre.

## 3. Exclusions : durée, compteurs, renouvellement (choix du simulateur)

- **Durée : 100 uplinks admissibles reçus** (`kLoopExclusionUplinks`). Convention du simulateur :
  TS001 et RP002 ne fixent aucune durée. Une exclusion posée à l'uplink R bloque la demande pendant
  les uplinks R+1 à R+99 et redevient éligible à R+100.
- **Compteurs indépendants** par débit (16), par index de puissance (16) et par canal (16 blocs ou
  canaux). Un débit exclu n'exclut ni une puissance, ni un canal.
- **Renouvellement** : une exclusion posée alors qu'elle est encore active remet le compteur à 100 (la
  fonction retourne alors vrai, « renouvellement »). Pendant le cycle, un refus renégocié *après*
  expiration rouvre une exclusion (création) à partir de R' ; c'est le cas observé dans le scénario 001.
- **L'expiration ne déclenche jamais une commande.** Elle rend seulement le paramètre éligible à l'ADR
  suivant.
- Aucun tirage aléatoire (pas de RNG).
- Le serveur ne réémet jamais la configuration refusée tant que l'exclusion est active.

Limite connue : le cas « refus pendant une exclusion encore active » n'est pas produit par l'ADR du
simulateur (qui ne redemande pas un paramètre exclu). Le renouvellement est donc testé au niveau
unitaire, pas en bout en bout.

## 4. Candidat de masque

- Masque candidat = vue serveur privée de ses canaux exclus.
- Si le candidat est vide, repli sur le dernier masque **acquitté** (`confirmed`). C'est un choix du
  simulateur.

## 5. Changement de comportement (scénario 011)

Dans le scénario 011, le terminal refuse le masque (`ChannelMaskACK` = 0) mais accepte le débit et la
puissance. Avant l'étape 4, le refus excluait le masque entier et la requête suivante revenait à
l'état précédent. Après l'étape 4 :

- le canal non acquitté (5, dans le scénario) est exclu ;
- le débit et la puissance acceptés restent appliqués ;
- la requête suivante reprend le dernier masque acquitté.

C'est un **changement de comportement** du simulateur, documenté, et couvert par
`test_channel_refused_mask_excluded_then_acknowledged_mask_used`. Les empreintes historiques (dump,
trace) n'utilisent pas ce chemin et restent identiques.

## 6. Trace interne v3 (étape 5, interne au C++)

Activée par `LoopChannelIo::trace_v3` (désactivée par défaut, sortie vide). Elle n'influence ni les
radios, ni les réponses, ni les requêtes : `test_trace_v3_does_not_change_radio_or_answers`.
Elle est triée par temps, à temps égal dans l'ordre causal d'insertion. Déterministe :
`test_trace_v3_deterministic`.

| Événement | Origine | Contenu |
|---|---|---|
| `Uplink` | Normative | uplink admissible reçu |
| `LinkAdrAns` | Normative | statut 3 bits (`status`), masque et débit en attente |
| `Exclusion` | SimulatorPolicy | `action` = Created / Renewed / Expired, `target` = débit / puissance / canal, `value` |
| `AdrDecision` | SimulatorPolicy | décision ADR ; `flag` = demande en attente |
| `LinkAdrReq` | SimulatorPolicy | valeurs de la LinkADRReq placée dans la descente |
| `Apply` | Normative | application côté terminal, statut 3 bits et motifs D5 (`reason_*`) |

Ordre causal dans un même uplink : `Uplink` < `LinkAdrAns` < `Exclusion` < `AdrDecision`
(`test_trace_v3_causal_order_and_time_sorted`).

**Limite de frontière.** La trace v3 n'est pas exposée à Python. La frontière C v2 ne transporte que
les bits `answer_ok` (débit et puissance). Le bit `ChannelMaskACK` et les exclusions ne peuvent donc
pas être restitués sans une évolution d'ABI. Cette exposition relève de l'étape 6 (ABI v3 additive).
La trace par défaut (v1, v2) et les empreintes sont inchangées.

## 7. Résidus

- Un refus de canal exclut aussi un canal valide suspect (sur-approximation).
- La durée de 100 uplinks est une convention du simulateur, pas une norme.
- Renouvellement strict : non atteignable par l'ADR actuel, testé en unitaire.
- Trace v3 : interne au C++, non exposée à Python avant l'ABI v3.
- US915 et AU915 : hors périmètre de ce modèle (EU868 seulement).
