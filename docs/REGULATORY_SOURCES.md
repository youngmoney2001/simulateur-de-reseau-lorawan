# Sources réglementaires par région

Ce document recense, pour chaque région du simulateur, le texte réglementaire utilisé et son
statut de vérification. Une valeur n'entre dans `python/lsim/regions.py` que si son texte
officiel a été lu. Une valeur seulement trouvée dans une source secondaire est notée « à confirmer ».

Légende : **Vérifié** = texte officiel lu ; **Secondaire** = source tierce, à confirmer ;
**Non trouvé** = texte officiel introuvable avec les outils disponibles.

| Région | Texte officiel de référence | Statut | Valeurs retenues dans le code | Restant à confirmer |
|---|---|---|---|---|
| US915 | FCC 47 CFR 15.247 (govinfo, édition 2013) | Vérifié (édition 2013 ; contrôler l'eCFR actuel) | Canaux RP002 ; PIRE conduite 30 dBm (FHSS) et 26 dBm (500 kHz) ; dwell 400 ms | Édition courante de 15.247 |
| AU915 | ACMA, Radiocommunications (LIPD) Class Licence 2015, compilation n° 10 (F2023C00524, 19/05/2023) | **Vérifié** (PDF fourni) | PIRE 1 W EIRP = 30 dBm (item 58, modulation numérique 915–928 MHz) ; PSD ≤ 25 mW par 3 kHz (non encodée) | — |
| AS923 (Japon : `AS923JP`) | ARIB STD-T108 v1.3 (PDF officiel `arib.or.jp`, extraits lus) | Partiel | 20 mW + 3 dBi = 16,01 dBm EIRP ; canaux 923,2 / 923,4 ; 360 s/h sur 922,4–923,4 MHz, **confirmé** par l'extrait officiel (« total transmission time per hour … shall be 360 s or less ») | Écoute de porteuse (5 ms / 128 µs) non modélisée (LBT à implémenter côté dispositif) ; règle des 400 ms d'arrêt à modéliser ; autres pays AS923 (limites locales) |
| KR920 | RP002-1.0.0 (tableau 68) ; texte MSIT en vigueur non trouvé | Partiel (RP002 officiel) | PIRE 10 / 14 dBm ; canaux RP002 | Texte MSIT / RRA pour 920,9–923,3 MHz ; LBT AFA |
| IN865 | GSR 564(E) du 30/07/2008 (DoT, gazette officielle) | **Vérifié** (extrait OCR de la gazette officielle ; fichier complet non lu) | 1 W émetteur, 4 W ERP → PIRE 38,17 dBm EIRP ; carrier 200 kHz | Limite 1 W conduite (à respecter côté matériel) |
| RU864 | Décision GKRF 07-20-03-001, annexe 11 (textes Garant et meganorm, version consolidée 2023) | Partiel | 25 mW ERP = 16,13 dBm EIRP (constant dans toutes les versions lues) ; sous-bandes 864–865 (0,1 % ou LBT) et 868,7–869,2 MHz ; duty cycle 0,1 % conservé par prudence | Le texte consolidé 2023 indique « 10 % ou LBT » pour 868,7–869,2 MHz, mais assorti d'une condition « stations de base » : le régime applicable aux dispositifs terminaux reste à confirmer ; 0,1 % est plus restrictif, donc sûr |
| EU868 | ETSI EN 300 220-2 V3.2.1 ; RP002-1.0.0 | **Vérifié** (PDF fournis) | Sous-bandes K à QP, canaux, RX2 | — |

## Points de vigilance

- **Aucune valeur n'est tirée de blogs, forums ou sites de distributeurs** sans recoupement.
- **AU915** : 1 W EIRP confirmé par le texte ACMA. La limite PSD (25 mW par 3 kHz) n'est pas encore modélisée.
- **US915** : la limite FHSS de 1 W s'applique à la puissance conduite. Le gain d'antenne au-delà de 6 dBi
  réduit la puissance conduite autorisée (15.247(b)(4)). Le modèle ne l'applique pas encore.
- **IN865** : PIRE dérivée de 4 W ERP (GSR 564(E)). **RU864** : PIRE 16,13 dBm EIRP (25 mW ERP, annexe 11 lue en extraits concordants) ; duty cycle de 868,7–869,2 MHz non confirmé (0,1 % par prudence).
- **Corée** : aucun passage du texte en vigueur pour 920,9–923,3 MHz n'a pu être trouvé ; les valeurs RP002 restent sans confirmation nationale.
- **Accès aux textes** : le PDF complet de la gazette indienne (dms.dot.gov.in) n'a pas pu être téléchargé ; seul un extrait
  est vérifié. Le texte consolidé russe est tronqué avant l'annexe 11. ARIB : le PDF lu (v1.3) ne couvre que la partie 1 sur les pages récupérées ; la partie 2 n'est vue que dans des snippets (20 mW, LBT).
