# Sources réglementaires par région

Ce document recense, pour chaque région du simulateur, le texte réglementaire utilisé et son
statut de vérification. Une valeur n'entre dans `python/lsim/regions.py` que si son texte
officiel a été lu. Une valeur seulement trouvée dans une source secondaire est notée « à confirmer ».

Légende : **Vérifié** = texte officiel lu ; **Secondaire** = source tierce, à confirmer ;
**Non trouvé** = texte officiel introuvable avec les outils disponibles.

| Région | Texte officiel de référence | Statut | Valeurs retenues dans le code | Valeurs à confirmer |
|---|---|---|---|---|
| US915 | FCC 47 CFR 15.247 (govinfo, édition 2013) | Vérifié (édition 2013 ; contrôler l'eCFR actuel) | Canaux RP002 ; PIRE conduite 30 dBm (FHSS) et 26 dBm (500 kHz) ; dwell 400 ms | Édition courante de 15.247 |
| AU915 | ACMA, Radiocommunications (LIPD) Class Licence 2015, art. 54 et 58 | Secondaire (powertec, r-spectrum, forum) ; texte ACMA non lu | PIRE 30 dBm (RP002) ; 20 fréquences minimum en FH | Article 58 : PSD 25 mW par 3 kHz ; texte ACMA officiel |
| AS923 | ARIB STD-T108 (Japon) et textes par pays | Non trouvé | Canaux par défaut 923,2 et 923,4 MHz ; PIRE par défaut 16 dBm | Limites par pays, LBT, duty cycle |
| KR920 | Règles des radiocommunications, article RFID/USN (MSIT), et KCC | Secondaire (TTN, RP002) ; texte coréen officiel non lu | PIRE 10 / 14 dBm, canaux RP002 | Texte MSIT en vigueur ; LBT AFA |
| IN865 | GSR 564(E) (WPC, 2008) | Secondaire (TEC pdf, PCN, identiumone) ; gazette non lue | Canaux par défaut seulement | PIRE : 1 W émetteur, 4 W ERP selon les sources secondaires (≈ 38,15 dBm EIRP à confirmer) |
| RU864 | Décision de la SCRF (Russie) | Secondaire, ancienne (décision de 2007 citée par ifcg) | Canaux par défaut seulement | Décision en vigueur (sous-bandes, ERP, 1 % ou LBT) |
| EU868 | ETSI EN 300 220-2 V3.2.1 ; RP002-1.0.0 | Vérifié (PDF fournis) | Sous-bandes K à QP, canaux, RX2 | — |

## Points de vigilance

- **Aucune valeur n'est tirée de blogs, forums ou sites de distributeurs** sans recoupement.
- **AU915** : la PIRE de 30 dBm est cohérente entre RP002 et les sources secondaires (1 W EIRP).
  Le plafond PSD de 25 mW par 3 kHz est à confirmer dans le texte ACMA avant tout encodage.
- **US915** : la limite FHSS de 1 W s'applique à la puissance conduite. Le gain d'antenne au-delà de 6 dBi
  réduit la puissance conduite autorisée (15.247(b)(4)). Le modèle ne l'applique pas encore.
- **IN865 et RU864** : tant que la PIRE n'est pas confirmée par le texte officiel, la validation de puissance
  est désactivée pour ces canaux (`max_eirp_dbm = None`).
- **Recherche de textes** : les URLs officielles ACMA (legislation.gov.au), gazette indienne (DoT), coréenne
  (law.go.kr, MSIT) et russe (SCRF) n'ont pas pu être lues avec les outils disponibles. Il faut les fournir
  en PDF ou les récupérer depuis un accès autorisé.
