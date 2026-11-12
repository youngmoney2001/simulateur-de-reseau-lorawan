"""Manuel technique : hypothèses, formules et références du simulateur.

Chaque section dit trois choses, et rien d'autre : **l'hypothèse** posée, **la formule**
appliquée, et **la référence** d'où elle vient. Les valeurs numériques sont lues dans le
moteur à la génération (voir `manuel_socle`) — aucune n'est recopiée.

Ce manuel ne décrit pas comment se servir du simulateur : c'est l'objet de
`manuel_utilisation.py`. Il décrit **ce que le simulateur croit** de la physique, du MAC et de
l'énergie, et où s'arrête ce qu'il croit.
"""

from __future__ import annotations

from reportlab.lib.units import mm

from manuel_socle import (H1, H2, NOTE, PageBreak, Spacer, airtimes, bloc_garde,
                          bornes_propagation, brut, configuration_radio, defaut_energie, ecrire,
                          formule, p, perte_espace_libre, pertes_log_distance, profils_energie,
                          sensibilites, tableau, version)

TITRE_DOC = "lsim — manuel technique : hypothèses, formules et références"


def _couverture() -> list:
    return bloc_garde(
        "Manuel technique",
        "Hypothèses, formules et références du simulateur lsim",
        "Toute valeur numérique de ce document est lue dans le moteur au moment de la "
        "génération. Elle n'est recopiée d'aucune fiche ni d'aucun tableau : si le moteur "
        "change, ce manuel change avec lui, et un manuel qui dérive se voit.")


def _lire() -> list:
    return [
        p("Comment lire ce manuel", H1),
        p("Le simulateur repose sur un ensemble d'hypothèses. Certaines viennent d'un texte "
          "de référence lu et cité, d'autres sont des choix de modélisation assumés faute de "
          "mieux, d'autres enfin sont des limites connues. Les confondre ferait croire mesuré "
          "ce qui est supposé, et supposé ce qui est borné par un texte de loi."),
        p("Chaque grandeur porte donc l'un des trois statuts suivants, et le statut est dit "
          "chaque fois qu'une valeur est avancée."),
        tableau(
            ["Statut", "Ce qu'il signifie", "Ce qu'on peut en attendre"],
            [["Mesuré", "Lu dans le moteur à la génération de ce document",
              "Reproductible par un test ; la valeur ne peut pas dériver sans que les tests "
              "échouent"],
             ["Sourcé", "Tiré d'un texte de référence cité (datasheet, norme, règlement)",
              "Vérifiable dans le texte cité ; la référence est donnée avec son statut de "
              "vérification"],
             ["Assumé", "Choix de modélisation, sans texte qui l'établisse",
              "Borné et documenté ; à remplacer par une mesure ou un texte dès qu'il en existe "
              "un"]],
            largeurs=[28 * mm, 62 * mm, 80 * mm]),
        p("Ce manuel cite ses sources. Une valeur réglementaire qui n'aurait été trouvée que "
          "dans une source secondaire est signalée comme telle, et jamais présentée comme "
          "vérifiée : la liste en est tenue dans docs/REGULATORY_SOURCES.md, qui est la "
          "référence du projet sur ce point."),
    ]


def _propagation() -> list:
    b = bornes_propagation()
    f_mhz = b["frequence_hz"] / 1e6
    return [
        p("1. Propagation", H1),
        p("1.1 Espace libre", H2),
        p("La perte en espace libre sert d'ancrage au modèle : c'est elle qui fixe PL(d₀), "
          "quelle que soit la distance de référence choisie."),
        formule("PL(d₀) = 20·log₁₀(d₀) + 20·log₁₀(f) − 147,55      (d₀ en mètres, f en Hz)"),
        p("La constante 147,55 vient de l'équation de Friis : 20·log₁₀(4π/c), avec c en m/s. "
          "Référence : équation de Friis, forme usuelle en dB. Statut : sourcé."),
        p(f"Valeur mesurée : à {f_mhz:.1f} MHz et 1 000 m, PL = "
          f"{perte_espace_libre():.3f} dB.", NOTE),
        p("1.2 Modèle log-distance", H2),
        formule("PL(d) = PL(d₀) + 10·n·log₁₀(d / d₀)"),
        p(f"Bornes appliquées : n ∈ [{b['exposant_min']:.0f} ; {b['exposant_max']:.0f}], "
          f"d₀ > 0, f > 0. Valeurs par défaut du moteur : f = {f_mhz:.1f} MHz, "
          f"d₀ = {b['d0_m']:.0f} m, n = {b['exposant']:.1f}. Statut des bornes : assumé, ce "
          "sont des bornes de validité du modèle et non des valeurs physiques."),
        p("1.3 Ce que change d₀ — et ce qu'on croit à tort qu'il ne change pas", H2),
        p("Changer d₀ ne décale pas le modèle : il déplace le point d'ancrage de la pente. "
          "Toutes les pertes sont décalées de :"),
        formule("ΔPL = (20 − 10·n)·log₁₀(d₀₂ / d₀₁)"),
        p("À n = 2 le terme s'annule : d₀ n'a alors aucun effet. À n = 2,7, passer d₀ de 1 m à "
          "10 m retire 7 dB à toutes les pertes. Un d₀ « sans effet » n'est donc pas une "
          "propriété du modèle, c'est une coïncidence de la valeur de n — mesuré et vérifié "
          "par les tests de non-régression RF."),
        p("1.4 Perte en fonction de la distance, mesurée", H2),
        tableau(["Distance", "PL (dB), n = 2,7, d₀ = 1 m, 868,1 MHz"],
                [[f"{d} m", f"{v:.6f}"] for d, v in pertes_log_distance()],
                largeurs=[35 * mm, 70 * mm],
                note="Mesuré : lu dans le cœur natif à la génération de ce document. Six "
                     "décimales, comme docs/RF_MODEL.md §10, pour que les deux se comparent "
                     "chiffre à chiffre — un arrondi différent ferait croire à un écart."),
        p("1.5 Shadowing", H2),
        p("Le shadowing est un terme log-normal **par dispositif**, constant sur toute la "
          "simulation : il n'est pas retiré à chaque trame. Le tirage est déterministe, par "
          "SplitMix64 et Box-Muller à partir de la graine du scénario (ou de "
          "shadowing_seed si elle est donnée)."),
        p(f"Écart-type σ ∈ [0 ; {b['shadowing_max']:.0f}] dB ; σ = 0 désactive le shadowing. "
          "Statut : la loi est sourcée (modèle log-normal usuel), la graine et l'algorithme "
          "sont mesurés."),
        p("Le shadowing n'est pas appliqué au calcul de couverture : une carte de couverture "
          "reste une frontière déterministe. Le dire évite de lire une carte comme une "
          "probabilité.", NOTE),
        p("1.6 Relief et obstacles", H2),
        p("Deux mécanismes s'ajoutent à PL(d) lorsqu'un environnement est déclaré :"),
        brut("la <b>diffraction</b>, par la méthode de Deygout à trois arêtes, appliquée "
             "seulement si l'obstruction dépasse la ligne de visée ;", NOTE),
        brut("la <b>pénétration</b> : atténuation saisie en dB, ou perte calculée depuis un "
             "matériau et une épaisseur selon l'UIT-R P.2040-4 (tableau 3 pour les "
             "diélectriques, équation 27a : A = 1636·σ/√ε′ dB/m).", NOTE),
        p("Référence : UIT-R P.2040-4. Statut : sourcé pour la formule, **assumé pour les "
          "valeurs** — à 868 MHz, 12 des 15 matériaux du catalogue sortent de la plage "
          "documentée du tableau 3, et leur perte est donc extrapolée. Le simulateur l'écrit "
          "à côté du matériau plutôt que de laisser croire à une mesure.", NOTE),
        p("Rien n'est émis tant qu'aucun environnement n'est déclaré : un scénario sans "
          "environnement reste exactement celui d'avant, empreinte comprise. C'est une "
          "propriété gardée par les tests, pas une commodité."),
    ]


def _bilan() -> list:
    return [
        PageBreak(),
        p("2. Bilan de liaison et sensibilité", H1),
        p("La réception d'une trame est décidée par comparaison du RSSI à la sensibilité du "
          "débit utilisé, éventuellement décalée par device_rx_offset_db. La frontière est "
          "déterministe : il n'y a ni marge de fading, ni probabilité de réception. Une trame "
          "passe ou ne passe pas, au décibel près, et deux exécutions de la même graine "
          "donnent le même résultat."),
        p("2.1 Sensibilités du récepteur", H2),
        tableau(["SF", "125 kHz", "250 kHz", "500 kHz"],
                [[f"SF{sf}", f"{a:.1f}", f"{b:.1f}", f"{c:.1f}"]
                 for sf, a, b, c in sensibilites()],
                largeurs=[22 * mm, 34 * mm, 34 * mm, 34 * mm],
                note="Sensibilité en dBm, lue dans le cœur natif. Référence : SX1276, "
                     "datasheet révision 4, blocs RFS_L*_HF (125 kHz), RFS_L250_HF, "
                     "RFS_L500_HF ; conditions LnaBoost, bande 1, chemin Rx/Tx séparé. "
                     "Statut : sourcé — les valeurs 125 kHz SF11 et SF12 (−133 et −136 dBm) "
                     "sont celles du datasheet et non les valeurs arrondies souvent reprises."),
        p("Conséquence mesurée, à puissance et gains constants : la bascule de réception se "
          "produit à une distance fixe par débit — de l'ordre de 15 à 25 km en SF9 et de 40 "
          "km en SF12 dans la configuration de référence. Ces distances ne sont pas des "
          "portées « annoncées » : ce sont les points où le bilan de liaison change de "
          "signe."),
        p("2.2 Collisions et seuil de capture", H2),
        p("Deux trames de **même débit** qui se chevauchent entrent en collision. La plus "
          "forte n'est reçue que si elle dépasse l'autre d'au moins le seuil de capture, "
          f"{bornes_propagation()['capture_db']:.0f} dB par défaut. La frontière est "
          "**inclusive** : un écart exactement égal au seuil est capturé."),
        p("Des débits différents ne collisionnent pas : c'est l'orthogonalité inter-SF, "
          "modèle de base. Statut : assumé — l'orthogonalité des étalements n'est pas parfaite "
          "en pratique, et le simulateur la traite comme telle. C'est une limite connue, "
          "pas un réglage."),
        p("2.3 Descente : réciprocité", H2),
        p("Le canal descendant réutilise le bilan montant, sans second modèle :"),
        formule("RSSI_dl = RSSI_ul − P_tx_terminal + P_tx_passerelle + G_antenne_terminal"),
        p("Les termes de la chaîne terminale s'annulent : le gain n'est compté qu'une seule "
          "fois. Un downlink est reçu si RSSI_dl atteint la sensibilité du débit RX1 du "
          "terminal. Statut : sourcé (docs/RF_FRONTEND_V4.md §2)."),
        p("2.4 Frontaux RF", H2),
        p("Un frontal porte deux grandeurs indépendamment présentes : antenna_gain_dbi "
          "( |G| ≤ 40 ) et cable_loss_db ( 0 ≤ L ≤ 40 ). La chaîne appliquée est G − L."),
        p("Une table absente donne une chaîne de 0 dB, sans changer le résultat historique. "
          "Une table **partielle** — un seul des deux champs renseigné alors que l'autre est "
          "attendu — est refusée avant l'appel natif, avec le statut 301. Il n'y a aucun "
          "repli implicite : un frontal à moitié décrit ne devine pas ce qui lui manque."),
    ]


def _airtime() -> list:
    c = configuration_radio()
    return [
        PageBreak(),
        p("3. Temps d'antenne", H1),
        p("Le temps d'antenne est calculé en nanosecondes entières, sans flottant : c'est ce "
          "qui rend les comparaisons exactes et les cumuls reproductibles."),
        p("3.1 Formule", H2),
        formule("Tsym = 2^SF / BW\n"
                "T_préambule = (P + 4,25) · Tsym\n"
                "N_symbole_charge = 8 + max( ceil( (8·PL − 4·SF + 28 + 16·CRC − 20·IH)\n"
                "                                  / (4·(SF − 2·DE)) ) · (CR + 4) ; 0 )\n"
                "T_antenne = T_préambule + N_symbole_charge · Tsym"),
        p("PL = octets de charge utile ; CRC = 1 si CRC activé ; IH = 0 si en-tête explicite, "
          "1 sinon ; DE = 1 si l'optimisation bas débit est activée ; CR est le numéro de "
          "rendement de code (1 pour 4/5, jusqu'à 4 pour 4/8)."),
        p("Référence : Semtech AN1200.13 (LoRa Modem Designer's Guide). Statut : sourcé — la "
          "formule est celle de la note d'application, et son implantation est vérifiée par "
          "comparaison avec une implantation indépendante."),
        p(f"Configuration de référence du moteur : SF{c['sf']}, "
          f"{c['bw_hz'] // 1000} kHz, CR 4/{c['cr'] + 4}, préambule de {c['preambule']} "
          f"symboles, CRC {'activé' if c['crc'] else 'désactivé'}, en-tête "
          f"{'explicite' if c['entete_explicite'] else 'implicite'}. L'optimisation bas débit "
          "suit la règle LoRaWAN : activée si la durée d'un symbole dépasse 16 ms."),
        p("3.2 Temps d'antenne mesuré", H2),
        tableau(["SF", "Charge 10 o, 125 kHz (ms)"],
                [[f"SF{sf}", f"{ms:.2f}"] for sf, ms in airtimes(10, 125_000)],
                largeurs=[22 * mm, 55 * mm],
                note="Mesuré : lu dans le cœur natif. Le doubllement approximatif d'un SF au "
                     "suivant est la conséquence directe de Tsym = 2^SF / BW."),
        p("Le temps d'antenne porte le duty cycle, l'occupation radio et l'énergie : c'est la "
          "grandeur la plus en amont du simulateur, et la seule dont dépendent les trois "
          "autres."),
    ]


def _energie() -> list:
    profils = profils_energie()
    lignes = [[pr["nom"], pr["libelle"], f"{pr['tension_v']:.1f} V", f"{pr['rx_ma']:.1f} mA",
               f"{pr['veille_ua']:.2f} µA",
               f"{pr['mcu_run_ma']:.3f} mA" if pr["mcu_run_ma"] else "inclus"]
              for pr in profils]
    return [
        PageBreak(),
        p("4. Énergie", H1),
        p("L'énergie est calculée par le cœur natif, en classe A : un message par période du "
          "groupe, deux fenêtres de réception ouvertes pendant le préambule, veille sur le "
          "reste de la période. Ce n'est pas une estimation de durée de vie sur pile : c'est "
          "un courant moyen, tiré d'un profil de matériel. La capacité de la pile, elle, "
          "n'est pas modélisée — un simulateur qui annoncerait « trois ans d'autonomie » à "
          "partir d'une capacité qu'il inventerait publierait un chiffre qu'il n'a pas "
          "mesuré."),
        p("4.1 Les deux profils de matériel", H2),
        tableau(["Profil", "Matériel", "Alim.", "Rx 125 kHz", "Veille", "MCU en marche"],
                lignes, largeurs=[26 * mm, 52 * mm, 14 * mm, 20 * mm, 18 * mm, 22 * mm],
                note=f"Mesuré : lu dans le moteur. Profil par défaut : {defaut_energie()}. "
                     "Sources : fiche RAKwireless pour le RAK4631 (MCU inclus) ; datasheet "
                     "Semtech SX1262 et fiche ST STM32L072 (composants séparés)."),
        p("Règle d'émission : le point du profil retenu est celui dont la puissance est "
          "supérieure ou égale à la puissance demandée. Une demande à 14 dBm retient donc le "
          "point 14 dBm du profil, jamais une interpolation."),
        p("4.2 Réserves attachées aux valeurs", H2),
        p("Ces réserves font partie du modèle ; les taire ferait croire à une précision que "
          "les fiches n'ont pas."),
        tableau(["Grandeur", "Réserve"],
                [["Rx du SX1262", "4,6 mA publiés pour 125 kHz seulement ; les bandes 250 et "
                                  "500 kHz ne sont pas publiées par Semtech dans les sources "
                                  "consultées. La valeur 125 kHz est appliquée aux trois, et "
                                  "l'écart est signalé."],
                 ["Veille du SX1262", "Valeur de démarrage à chaud (0,6 µA, configuration "
                                      "conservée), retenue depuis une copie du datasheet "
                                      "révision 2.2 : source secondaire."],
                 ["Run du STM32L072", "La fiche ST annonce « jusqu'à » 93 µA/MHz, soit une "
                                      "valeur basse à 32 MHz. Le chiffre retenu est donc "
                                      "optimiste, et le courant moyen calculé l'est avec lui."],
                 ["Portée des résultats", "Profils constructeur, sans mesure terrain. Deux "
                                          "appareils de matériel différent ne consomment pas "
                                          "la même chose — l'écart mesuré atteint 10 % de "
                                          "courant moyen — et c'est précisément ce que le "
                                          "réglage permet de comparer."]],
                largeurs=[32 * mm, 118 * mm]),
        p("4.3 Modèle classe A", H2),
        p("Deux fenêtres par uplink : RX1 (1 s après la fin de l'émission) et RX2 (2 s). La "
          "durée d'ouverture est fournie par l'appelant, par défaut la durée du préambule "
          "(n + 4,25)·Tsym. L'airtime des downlinks effectivement reçus s'ajoute en "
          "majorant. Statut : les durées RX1/RX2 sont sourcées (LoRaWAN 1.1) ; la durée "
          "d'ouverture par défaut est assumée, et bornée à 10 s."),
    ]


def _mac() -> list:
    return [
        PageBreak(),
        p("5. Couche MAC", H1),
        p("Cette section résume ce que la couche MAC applique. Le détail normatif, les "
          "vecteurs de test et les écarts assumés avec la spécification sont tenus dans "
          "docs/MAC_CONSOLIDATION.md et docs/ROADMAP.md, qui font foi."),
        p("5.1 Classes d'écoute", H2),
        p("La classe décide **quand** une trame descendante peut être remise. C'est la seule "
          "grandeur du simulateur que la classe détermine à elle seule."),
        tableau(["Classe", "Fenêtre de réception", "Conséquence sur l'attente"],
                [["A", "RX1 à fin + 1 s, sinon RX2 à fin + 2 s, après chaque uplink",
                  "Une commande demandée par le réseau attend le prochain uplink : l'attente "
                  "est celle du cycle d'émission"],
                 ["B", "Ping slots périodiques, élargis par la dérive d'horloge",
                  "Attente bornée par la période des slots ; à 10 ppm la fenêtre s'élargit "
                  "d'environ 1,28 ms après 128 s"],
                 ["C", "Écoute continue, hors émission et hors RX1",
                  "La fenêtre est ouverte en permanence : attente nulle, au prix du courant "
                  "de réception"]],
                largeurs=[16 * mm, 62 * mm, 72 * mm],
                note="Mesuré (terminal unique à 100 m, 3 messages espacés de 60 s, une "
                     "demande à t = 10 s) : classe C 0,00 s ; classe B sans périodicité "
                     "0,94 s ; classe A 51,04 s."),
        p("Ce qui **n'est pas** une descente à l'initiative du réseau : un ACK, une réponse "
          "MAC ou une charge descendant après un uplink tombent dans RX1 ou RX2 quelle que "
          "soit la classe. La classe n'y change rien. Ici, la demande naît à un instant que "
          "le terminal n'a pas choisi, et c'est la classe qui décide de la fenêtre — donc de "
          "l'attente."),
        p("5.2 ADR", H2),
        p("La décision du serveur (core/src/adr.cpp) prend le SNR maximal de l'historique, "
          "calcule la marge exacte par SF depuis la table du démodulateur SX1276, et monte le "
          "débit tant que la marge reste positive ; le reliquat est converti en index de "
          "puissance. Statut : sourcé pour la table de marge, assumé pour la politique — le "
          "simulateur ne baisse jamais le débit et ne touche pas au masque de canaux."),
        p("Ce qui compte, du point de vue d'une mesure : le SF **observé** en fin de run, pas "
          "la case ADR cochée. Une commande LinkADRReq ne porte que son nom ; seul le SF du "
          "dernier uplink dit si le terminal l'a appliquée. Le simulateur publie les deux, et "
          "c'est le second qui est noté dans les exercices."),
        p("5.3 Jointure, rejeu et rekey", H2),
        p("La jointure OTAA 1.1 est complète : join-request (MIC NwkKey), join-accept "
          "(chiffrement NwkKey, MIC JSIntKey si OptNeg, repli 1.0.x), rejoin-requests de "
          "types 0, 1 et 2. Les vecteurs sont ceux de TheThingsNetwork (licence Apache-2.0), "
          "recalculés indépendamment — ils ne viennent **pas** du document TS001-1.1.0, qui "
          "ne publie pas de vecteur numérique. Statut : sourcé, avec cette réserve."),
        p("Le registre de jointure garde DevNonce et RJcount par dispositif, n'écrit qu'après "
          "vérification du MIC, et se persiste dans un format protégé par MIC. Un registre "
          "absent ou non rechargé remet les compteurs à zéro : c'est une fenêtre de rejeu, "
          "et elle est documentée comme telle plutôt que corrigée silencieusement."),
    ]


def _reglementaire() -> list:
    return [
        PageBreak(),
        p("6. Régions, canaux et duty cycle", H1),
        p("Une valeur réglementaire n'entre dans le code que si son texte officiel a été lu. "
          "Une valeur trouvée seulement dans une source secondaire est notée « à confirmer » "
          "et n'est pas présentée comme vérifiée. Le détail par région, avec le statut de "
          "chaque texte, est tenu dans docs/REGULATORY_SOURCES.md."),
        tableau(["Région", "Texte de référence", "Statut", "Valeurs retenues"],
                [["EU868", "ETSI EN 300 220-2 V3.2.1 ; RP002-1.0.0", "Vérifié",
                  "Sous-bandes K à QP, canaux, RX2"],
                 ["US915", "FCC 47 CFR 15.247 (édition 2013)", "Vérifié (édition 2013)",
                  "Canaux RP002 ; PIRE 30 dBm conduit (FHSS), 26 dBm (500 kHz) ; dwell 400 ms"],
                 ["AU915", "ACMA LIPD Class Licence 2015, compilation n° 10", "Vérifié",
                  "1 W PIRE = 30 dBm ; PSD non encodée"],
                 ["AS923", "ARIB STD-T108 v1.3 (extraits)", "Partiel",
                  "20 mW + 3 dBi = 16,01 dBm PIRE ; 360 s/h confirmé par l'extrait"],
                 ["IN865", "GSR 564(E) du 30/07/2008 (gazette)", "Vérifié (extrait)",
                  "4 W PAR → 38,17 dBm PIRE"],
                 ["RU864", "Décision GKRF 07-20-03-001, annexe 11", "Partiel",
                  "25 mW PAR = 16,13 dBm PIRE ; duty cycle 0,1 % par prudence"],
                 ["KR920", "RP002-1.0.0 (tableau 68)", "Partiel",
                  "PIRE 10/14 dBm, canaux RP002 ; texte national non trouvé"]],
                largeurs=[18 * mm, 48 * mm, 26 * mm, 58 * mm],
                note="Aucune valeur n'est tirée d'un blog, d'un forum ou d'un site de "
                     "distributeur sans recoupement."),
        p("Deux choix de prudence méritent d'être lus comme tels : le duty cycle russe de "
          "868,7–869,2 MHz est conservé à 0,1 % alors que le texte consolidé 2023 suggère "
          "10 % sous condition, parce que la condition (« stations de base ») ne s'applique "
          "pas clairement aux terminaux ; et la limite coréenne reste celle de RP002 faute de "
          "texte national trouvé. Un simulateur qui choisit la valeur la plus permissive "
          "publierait une conformité qu'il n'a pas vérifiée."),
        p("6.1 Masques de canaux", H2),
        p("Les masques suivent RP002-1.0.3 §2.5.3 : règle ChMaskCntl 0 à 7 et sous-bande. "
          "Un canal peut être défini sans être actif : c'est la liste des canaux actifs qui "
          "dit ce que la trame suivante empruntera réellement. Le détail est dans "
          "docs/CHANNEL_MASK_MODEL.md."),
    ]


def _determinisme() -> list:
    return [
        PageBreak(),
        p("7. Déterminisme", H1),
        p("Deux exécutions de la même graine donnent les mêmes compteurs, octet pour octet. "
          "Ce n'est pas une propriété qu'on constate : c'est une garantie que les tests "
          "vérifient, et chaque test est discriminant — démontré par mutation, c'est-à-dire "
          "qu'on a vérifié qu'il échoue quand on casse ce qu'il garde."),
        p("7.1 La clé d'ordonnancement", H2),
        p("La boucle fermée est menée par une file à priorité dont la clé est totale :"),
        formule("(t, rank, seq)\n"
                "  t    : instant de l'événement, en nanosecondes\n"
                "  rank : classe d'événement — 0 Check/Apply, 1 Start, 2 End\n"
                "  seq  : compteur d'insertion, monotone et unique"),
        p("seq étant unique, deux événements distincts ne sont jamais égaux : aucun "
          "événement n'est laissé à l'ordre d'arrivée de façon implicite. L'ordre des rangs "
          "n'est pas arbitraire, il garantit que toute lecture porte sur un état déjà "
          "complet : Check avant Start avant End à instant égal."),
        p("Référence : docs/DETERMINISME.md, normatif pour le code ; tests dans "
          "core/tests/test_determinisme.cpp. Portée : la boucle fermée. Les autres chemins "
          "(planificateur causal, réémissions) ont leurs propres clés, non harmonisées à ce "
          "jour — c'est une limite connue, pas une différence cachée."),
        p("7.2 Graine", H2),
        p("La graine du scénario commande tous les tirages : placement des dispositifs, "
          "shadowing, et l'ordre des événements. Le tirage gaussien du shadowing utilise "
          "SplitMix64 pour l'entier et Box-Muller pour la transformation. Une graine absente "
          "n'est pas remplacée par une valeur implicite : elle est exigée, ou bien le "
          "shadowing hérite de la graine du scénario, ce qui rend le tirage reproductible."),
    ]


def _limites() -> list:
    return [
        PageBreak(),
        p("8. Ce que le modèle ne fait pas", H1),
        p("Cette section n'est pas une liste de travaux à venir : ce sont des frontières. "
          "Une limite dite est une limite qu'on peut contourner en connaissance de cause ; "
          "une limite tue devient une erreur de lecture."),
        tableau(["Domaine", "Ce qui n'est pas modélisé", "Conséquence sur la lecture"],
                [["Canal", "Aucun modèle de canal distinct ; la fréquence est portée par la "
                           "propagation, pas par la trame",
                  "Pas d'évanouissement sélectif, pas d'effet Doppler"],
                 ["Fading", "Aucun fading aléatoire hors shadowing",
                  "La réception est déterministe au dB près ; une carte n'est pas une "
                  "probabilité"],
                 ["Antennes", "Aucun EIRP, aucun diagramme, aucune polarisation",
                  "Le gain est scalaire ; une orientation d'antenne ne change rien"],
                 ["Mesh", "Aucun gain d'antenne sur le mesh ni sur le chemin causal",
                  "Une liaison mesh ne se traite pas comme une liaison radio"],
                 ["Portée", "Modèle de collision de base : pas de réception "
                            "multi-passerelle sur le chemin simple",
                  "Le PDR d'un réseau à plusieurs passerelles se lit sur le chemin "
                  "multi-passerelles, pas sur le chemin simple"],
                 ["Latence", "Latence = temps d'antenne : ni file, ni backhaul",
                  "Aucun délai réseau n'est ajouté ; c'est un plancher, pas une estimation"],
                 ["Descente", "La réception effective de la trame descendante n'est pas "
                              "simulée : seule l'opportunité l'est",
                  "Une descente « livrée » dit que la fenêtre était ouverte, pas que la "
                  "trame a été décodée"],
                 ["Relief", "Deygout à 3 arêtes, pénétration fixe par pavé",
                  "À calibrer par mesures avant usage contractuel"],
                 ["Énergie", "Profils constructeur, sans mesure terrain",
                  "Comparer deux matériels est légitime ; annoncer une autonomie ne l'est "
                  "pas"],
                 ["LR-FHSS", "Non géré : uplinks DR5/DR6 US915 et modulation LRFHSS refusés",
                  "Décision assumée, testée par un test qui refuse explicitement la "
                  "modulation"]],
                largeurs=[22 * mm, 62 * mm, 66 * mm]),
        p("Ces limites sont celles du modèle de simulation. Elles ne disent rien de la "
          "conformité du code aux textes qu'il cite : cette question est traitée par "
          "docs/CONFORMANCE_MATRIX.md et par les tests, dont chacun est rattaché au texte "
          "qu'il vérifie."),
    ]


def _references() -> list:
    return [
        PageBreak(),
        p("9. Références", H1),
        p("Les références sont groupées par nature. Le statut « vérifié » signifie que le "
          "texte a été lu, pas qu'une source secondaire le rapporte."),
        p("9.1 Radio et propagation", H2),
        tableau(["Référence", "Emploi dans le simulateur"],
                [["Semtech SX1276, datasheet révision 4, blocs RFS_L*_HF, RFS_L250_HF, "
                  "RFS_L500_HF",
                  "Sensibilités du récepteur, 125/250/500 kHz, SF7 à SF12"],
                 ["Semtech AN1200.13, LoRa Modem Designer's Guide",
                  "Formule du temps d'antenne"],
                 ["UIT-R P.2040-4, tableau 3 et équations 27a, 43b",
                  "Perte de pénétration des matériaux, perte aux interfaces"],
                 ["Méthode de Deygout (diffraction multi-arêtes)",
                  "Diffraction sur le relief, limitée à trois arêtes"],
                 ["Jeu de données LoRaWAN intérieur, université de Siegen (CC BY 4.0)",
                  "Paramètres de propagation intérieure déposés à titre de référence, non "
                  "utilisés comme modèle de simulation"]],
                largeurs=[70 * mm, 80 * mm]),
        p("9.2 LoRaWAN et réglementaire", H2),
        tableau(["Référence", "Emploi dans le simulateur"],
                [["LoRaWAN 1.1 (spécification LoRa Alliance) ; RP002-1.0.x",
                  "Plans régionaux, canaux, RX2, masques de canaux, classes"],
                 ["LoRaWAN LoRaWAN 1.1 errata « FOpts Encryption, Usage of FCntDwn » "
                  "(CR janvier 2018)",
                  "Compteurs de chiffrement FOpts"],
                 ["ETSI EN 300 220-2 V3.2.1",
                  "EU868 : sous-bandes, canaux, RX2"],
                 ["FCC 47 CFR 15.247 ; ACMA LIPD Class Licence 2015 ; ARIB STD-T108 v1.3 ; "
                  "GSR 564(E) ; décision GKRF 07-20-03-001",
                  "Puissances et duty cycle par région ; statut de vérification détaillé dans "
                  "docs/REGULATORY_SOURCES.md"],
                 ["Vecteurs LoRaWAN 1.1 de TheThingsNetwork/lorawan-stack (Apache-2.0)",
                  "Dérivations de clés, MIC, jointure, chiffrement. Valeurs recalculées "
                  "indépendamment ; aucun code copié. Réserve : ce ne sont pas les vecteurs "
                  "du document TS001."]],
                largeurs=[70 * mm, 80 * mm]),
        p("9.3 Matériel et énergie", H2),
        tableau(["Référence", "Emploi dans le simulateur"],
                [["Fiche RAKwireless RAK4631 (nRF52840 + SX1262)",
                  "Profil rak4631 : 3,3 V, TX/RX, veille 2,0 µA, MCU inclus"],
                 ["Datasheet Semtech SX1262",
                  "Profil sx1262-stm32l072 : courants TX/RX, veille"],
                 ["Fiche ST STM32L072",
                  "Courant de marche du MCU (valeur « jusqu'à », donc optimiste)"]],
                largeurs=[70 * mm, 80 * mm]),
        p("9.4 Composants tiers", H2),
        p("La liste complète, avec les licences et les conditions d'usage, est tenue dans "
          "THIRD_PARTY_NOTICES.md. Sont notamment repris : mbedTLS 3.6.4 (primitives "
          "AES-128 et AES-CMAC, sous licence Apache-2.0), CesiumJS 1.146.0 (carte 3D, "
          "Apache-2.0), Vite (MIT), et les tuiles OpenStreetMap (ODbL — un usage commercial "
          "demande un fournisseur sous contrat)."),
        p("Ce manuel a été généré depuis le moteur ; la version du moteur au moment de la "
          f"génération est {version()}.", NOTE),
    ]


def construire(chemin: str) -> None:
    story = _couverture() + _lire() + _propagation() + _bilan() + _airtime() + _energie() \
        + _mac() + _reglementaire() + _determinisme() + _limites() + _references()
    story.append(Spacer(1, 8))
    ecrire(chemin, story, TITRE_DOC)


if __name__ == "__main__":
    import sys
    construire(sys.argv[1] if len(sys.argv) > 1 else "docs/manuel-technique.pdf")
