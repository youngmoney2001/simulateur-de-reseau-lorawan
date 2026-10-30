# Modèle de masque de canaux (LinkADR ChannelMask), boucle fermée

Ce document décrit le modèle de canaux de la boucle fermée (passerelle unique, EU868) : refus,
attribution, exclusions, trace interne v3. Il sépare trois sources, qui ne doivent jamais être
confondues :

- **TS001-1.0.4** : protocole et réponses MAC (LinkADRReq / LinkADRAns, bits ACK, ordre des bits) ;
- **RP002-1.0.5** : paramètres régionaux (canaux par défaut, plan de canaux, index de puissance,
  débits, plage ChMaskCntl) ;
- **Choix du simulateur** (`SimulatorPolicy` dans la trace) : tout ce qui n'est défini par aucune des
  deux normes. Ces choix ne doivent jamais être présentés comme des exigences TS001 ou RP002.

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

**Ce que la norme ne dit pas** : `ChannelMaskACK` ne désigne pas le canal responsable d'un refus. Toute
attribution par canal est donc une heuristique du serveur.

## 2. Attribution d'un refus (D5, D7)

Une réponse négative est attribuée avec les seuls bits ACK et le **contenu acquitté** (la LinkADRReq
réellement reçue par le terminal), et l'état **connu du serveur**. Jamais l'état privé du terminal.

| Bits ACK | Attribution | Exclusion posée (SimulatorPolicy) |
|---|---|---|
| `DataRateACK` = 0 | le débit, même si `ChannelMaskACK` vaut aussi 0 (D5) | débit refusé (contenu acquitté) |
| `PowerACK` = 0 | la puissance | index de puissance refusé |
| `ChannelMaskACK` = 0, `DataRateACK` = 1, suspects non vides | les canaux demandés et non confirmés | un canal par suspect |
| `ChannelMaskACK` = 0, `DataRateACK` = 1, suspects vides | le masque demandé complet | masque exact, une seule case |
| `ChannelMaskACK` = 0, `DataRateACK` = 0 | le débit seulement (D5) ; aucun canal n'est exclu | débit |

Précisions :

- **Suspects** = canaux du masque demandé et non confirmés (`demandés \ confirmés`). Un canal confirmé
  a été accepté, donc il est défini.
- **Cas CM=0 et DR=0 (D5).** Le débit est exclu, les canaux ne le sont pas. Si le masque contient
  encore un canal indéfini, la requête suivante (débit accepté) le retrouve : le refus suivant a
  `DataRateACK` = 1, et le canal devient suspect et est exclu. Testé par
  `test_d5_cm0_dr0_then_channel_refusal`.
- **Sur-approximation.** Un suspect peut être valide. Le serveur ne sait pas quel canal est en cause.
  Un canal valide suspect est donc exclu pendant 100 uplinks. Testé par
  `test_valid_suspect_channel_excluded_by_over_approximation` (le canal 4 y est défini et exclu).
- Un bit à 0 est toujours un refus (D7) : aucun paramètre n'est appliqué si l'un des trois bits vaut 0.
  Chaque bit rapporte la validité de son propre paramètre.

## 3. Politique du masque demandé entier (suspects vides)

Lorsque `ChannelMaskACK` = 0, `DataRateACK` = 1 et qu'aucun suspect n'existe, le serveur exclut le
masque demandé complet. **Politique du simulateur (`SimulatorPolicy`)**, non fixée par TS001 ni RP002.

- Cette exclusion est **distincte** des exclusions par canal (case propre, cible `Mask`).
- Elle ne bloque que le masque exact. Elle ne bloque pas les autres masques.
- Durée : 100 uplinks admissibles, comme les autres exclusions.
- Renouvellement : le même masque refusé de nouveau pendant son exclusion remet le compteur à 100 et
  est signalé `Renewed`. Un refus après expiration est une création (`Created`).
- L'expiration ne déclenche aucune commande. Elle rend seulement le masque éligible.
- Repli : si le candidat est égal au masque exclu, le serveur demande le dernier masque **confirmé**.
- **Limite 1 : une seule case.** Un nouveau masque refusé à suspects vides remplace l'exclusion
  précédente. Ce cas n'est pas produit par l'ADR du simulateur.
- **Limite 2 : repli sur un masque confirmé refusé.** Si le dernier masque confirmé est lui-même refusé,
  le repli le renvoie. Ce cas exige un terminal qui ne définit pas les canaux par défaut (RP002 Table 8),
  donc un terminal non conforme. La configuration par défaut ne le produit pas.

Testé par : `test_mask_exclusion_is_exact_and_falls_back` (unitaire) ;
`test_empty_suspect_refusal_excludes_mask_without_repetition` (aucune requête du masque exclu pendant
100 uplinks, expiration au 100e, sans commande) ; `test_trace_v3_mask_exclusion_renewed_while_active`
(renouvellement en bout en bout).

Le test de non-répétition au niveau moteur utilise une requête forcée (test de robustesse). Sans forçage,
l'ADR ne produit pas de masque entièrement confirmé refusé ; la non-répétition repose donc surtout sur le
test unitaire de la fonction de repli.

## 4. Canaux : exclusions, compteurs, renouvellement (choix du simulateur)

- **Durée : 100 uplinks admissibles reçus** (`kLoopExclusionUplinks`). Convention du simulateur ; ni
  TS001 ni RP002 ne fixent de durée. Une exclusion posée à l'uplink R bloque la demande pendant les
  uplinks R+1 à R+99 et redevient éligible à R+100. Testé en unitaire et au 100e uplink en bout en bout.
- **Compteurs indépendants** par débit (16), par index de puissance (16), par canal (16) et pour le
  masque exact (une case). Un débit exclu n'exclut ni une puissance, ni un canal.
- **Renouvellement** : même exclusion posée alors qu'elle est active (`Renewed`). Refus renégocié après
  expiration : création (`Created`), à partir de R'.
- **Pas de tirage aléatoire** (RNG).
- **Attribution du débit et de la puissance** : sur le contenu acquitté. En chemin non forcé, c'est la
  demande en attente du serveur (vérifié : aucun écart sur les uplinks avec réponse). En requête forcée
  (test uniquement), c'est le contenu réellement reçu par le terminal.

## 5. Changement de comportement (scénario 011)

Dans le scénario 011, le terminal refuse le masque (`ChannelMaskACK` = 0) mais accepte le débit et la
puissance. Avant l'étape 4, le refus excluait le masque entier et la requête suivante revenait à
l'état précédent. Après l'étape 4 :

- le canal non confirmé (5, dans le scénario) est exclu, et lui seul ;
- le débit et la puissance acceptés restent appliqués ;
- la requête suivante reprend le dernier masque confirmé.

C'est un **changement de comportement** du simulateur, couvert par
`test_channel_refused_mask_excluded_then_acknowledged_mask_used`. Les empreintes historiques (dump,
trace ADR) n'utilisent pas ce chemin et restent identiques.

## 6. Trace interne v3 (interne au C++)

Activée par `LoopChannelIo::trace_v3` (désactivée par défaut, sortie vide). Elle n'influence ni les
radios, ni les réponses, ni les requêtes : `test_trace_v3_does_not_change_radio_or_answers` compare
uplink par uplink (issue, instants, débit, puissance, réponses), descente par descente (issue,
créneau, commandes) et les totaux. Elle est triée par temps, à temps égal dans l'ordre causal
d'insertion. Déterministe : `test_trace_v3_deterministic` compare la trace événement par événement.

Champs : `uplink` = uplink concerné (pour une descente : uplink déclencheur) ; `downlink` = indice de
descente (`kLoopNoIndex` si sans objet).

| Événement | Origine | Sens |
|---|---|---|
| `Uplink` | Radio | uplink admissible reçu |
| `LinkAdrAns` | Normative | bits ACK (`status`) ; débit, puissance et masque = **contenu acquitté** |
| `Exclusion` | SimulatorPolicy | `action` Created / Renewed / Expired ; `target` débit, puissance, canal ou masque ; `value` |
| `AdrDecision` | SimulatorPolicy | décision ADR ; `flag` = demande en attente |
| `LinkAdrReq` | SimulatorPolicy | **contenu planifié** d'une LinkADRReq, à la création de la descente (pas une transmission) |
| `Downlink` | Radio | issue radio de la descente : `flag` = reçue ; `loss` = cause si perdue ; `value` = commandes |
| `Apply` | Normative | application par le terminal d'une LinkADRReq reçue ; motifs D5 dans `reason_*` |

Causes de perte (`LoopDownlinkLoss`) : `DeviceTransmitting` (émission pendant la RX1),
`NoGatewaySlot` (pas de créneau passerelle), `BelowSensitivity` (sous la sensibilité du terminal).
Seule `BelowSensitivity` est exercée par un test (marge de réception de 110 dB). Les deux autres
exigent deux dispositifs ou une passerelle occupée : elles sont implémentées, non testées.

Invariants testés (`test_trace_v3_downlink_invariants`) : une issue par descente ; `Apply` = descentes
reçues portant une LinkADRReq ; une descente reçue n'a pas de cause de perte, une descente perdue en a
une.

Ordre causal dans un même uplink : `Uplink` < `LinkAdrAns` < `Exclusion` < `AdrDecision`
(`test_trace_v3_causal_order_and_time_sorted`).

**Limite de frontière.** La trace v3 n'est pas exposée à Python. La frontière C v2 ne transporte que
les bits `answer_ok` (débit et puissance). Le bit `ChannelMaskACK` et les exclusions ne peuvent donc
pas être restitués sans une évolution d'ABI. Cette exposition relève de l'étape 6 (ABI v3 additive),
non autorisée à ce stade. La trace par défaut (v1, v2) et les empreintes sont inchangées.

## 7. Requêtes forcées (robustesse, hors politique)

`forced_request` et `forced_sequence` imposent le contenu d'une LinkADRReq. Ils servent à atteindre des
combinaisons que l'ADR ne produit pas. Dans ce mode, l'exclusion vise la valeur réellement refusée, et
non la demande en attente du serveur. Conséquence : quelques scénarios forcés existants comptent davantage
de vérifications (+102 sur le total) ; aucune assertion historique n'a été modifiée, et le chemin non
forcé reste identique.

## 8. Résidus

- Un refus de canal exclut aussi un canal valide suspect (sur-approximation, testée).
- La durée de 100 uplinks est une convention du simulateur, pas une norme.
- Une seule case d'exclusion de masque : un nouveau masque refusé remplace l'exclusion précédente.
- Repli sur un masque confirmé refusé : possible seulement avec un terminal non conforme aux défauts.
- Causes de perte `DeviceTransmitting` et `NoGatewaySlot` : implémentées, non testées.
- Trace v3 : interne au C++, non exposée à Python avant l'ABI v3.
- US915 et AU915 : hors périmètre de ce modèle (EU868 seulement).
