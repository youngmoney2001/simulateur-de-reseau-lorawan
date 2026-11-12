"""Manuel d'utilisation complet : installer, écrire un scénario, commander, lire un résultat.

Tout ce qui peut être lu est lu : l'aide de chaque commande est celle que l'utilisateur
obtient en la tapant, les champs du scénario viennent du contrat Pydantic avec leurs
défauts, les régions et les exercices sont ceux que le serveur publie. Ce qui reste écrit à
la main, c'est la démarche — ce qu'on cherche à savoir, et dans quel ordre le chercher.

Les hypothèses de physique et leurs références sont dans le manuel technique, pas ici.
"""

from __future__ import annotations

from reportlab.lib.units import mm

from manuel_socle import (H1, H2, NOTE, PageBreak, Spacer, aide_cli, bloc_garde, brut, champs,
                          defaut_energie, ecrire, exercices, formule, p, profils_energie, regions,
                          tableau, version)

TITRE_DOC = "lsim — manuel d'utilisation"


def _couverture() -> list:
    return bloc_garde(
        "Manuel d'utilisation",
        "Installer, décrire un réseau, lancer une simulation, lire le résultat",
        "Les commandes et les champs décrits ici sont lus dans le logiciel au moment de la "
        "génération, et non recopiés d'une note : une option qui change, et ce manuel change "
        "avec elle.")


def _presentation() -> list:
    return [
        p("1. Ce que fait ce logiciel", H1),
        p("lsim simule un réseau LoRaWAN : des capteurs qui émettent, des passerelles qui "
          "écoutent, un serveur qui commande le débit, et un canal radio qui perd ou laisse "
          "passer les trames. Il répond à des questions qu'on pose avant de déployer : "
          "combien de trames arrivent, à quelle distance, avec quelle autonomie, et à quelle "
          "vitesse le réseau réagit à une commande."),
        p("Le résultat n'est pas une estimation : c'est un calcul déterministe. Deux "
          "exécutions de la même graine donnent les mêmes compteurs, octet pour octet. C'est "
          "ce qui permet de comparer deux réglages — si le hasard s'en mêlait, une différence "
          "entre deux runs ne voudrait rien dire."),
        p("1.1 Les quatre manières de s'en servir", H2),
        tableau(["Mode", "Pour quoi", "Où commencer"],
                [["Ligne de commande", "Lancer un scénario écrit à la main, produire un "
                                       "Parquet, un rapport ou une carte", "§3"],
                 ["Bibliothèque Python", "Enchaîner des variantes, balayer un paramètre",
                  "§4"],
                 ["Atelier 3D (studio web)", "Poser un réseau à la souris, le régler, "
                                             "observer le run, faire les exercices", "§6"],
                 ["Serveur d'intégration", "Raccorder de vraies passerelles (Semtech UDP ou "
                                           "Basic Station) et des jointures réelles", "§7"]],
                largeurs=[34 * mm, 76 * mm, 16 * mm]),
        p("1.2 Les trois idées à connaître avant de commencer", H2),
        brut("<b>Le scénario est validé strictement.</b> Un champ inconnu est refusé, au lieu "
             "d'être ignoré : une faute de frappe dans un nom de champ est signalée, elle ne "
             "devient pas un réglage absent.", NOTE),
        brut("<b>Rien n'est émis tant que rien n'est réglé.</b> Un scénario sans "
             "environnement, sans région et sans profil d'énergie reste exactement celui "
             "d'avant : ses chiffres et son empreinte ne bougent pas. Ajouter une option ne "
             "change jamais rétrospectivement un résultat déjà obtenu.", NOTE),
        brut("<b>Une grandeur non mesurée n'est pas publiée à zéro.</b> Un run qui n'a pas "
             "mesuré l'énergie n'a pas de colonne d'énergie ; un run sans descente n'a pas "
             "d'attente. Une case vide se lit « pas de mesure », un zéro se lirait « mesure "
             "nulle » — et les deux ne veulent pas dire la même chose.", NOTE),
    ]


def _installation() -> list:
    return [
        PageBreak(),
        p("2. Installation", H1),
        p("Prérequis : Python ≥ 3.10, CMake, et un compilateur C++17. mbedTLS est récupéré "
          "automatiquement par CMake — un accès à GitHub est donc nécessaire à la première "
          "configuration."),
        formule("cmake -S . -B build -DCMAKE_BUILD_TYPE=Release\n"
                "cmake --build build --parallel\n"
                "pip install -e \"python[data,report,test]\""),
        p("La bibliothèque native est cherchée dans build/. Si elle est ailleurs — paquet "
          "binaire, autre répertoire de construction — on l'indique par une variable "
          "d'environnement :"),
        formule("export LSIM_LIBRARY=/chemin/vers/liblsim_core.so"),
        p("Un paquet binaire du cœur natif (Linux) se construit avec scripts/package_native.sh "
          ": il produit une archive et son empreinte SHA-256 dans dist/. Les paquets macOS et "
          "Windows ne sont pas construits dans cet environnement."),
        p("2.1 Vérifier l'installation", H2),
        p("La commande suivante lance un scénario d'exemple et écrit un Parquet. Si elle "
          "aboutit, le cœur natif est trouvé et le scénario est valide."),
        formule("python -m lsim run examples/quartier_sf9.yaml -o resultats.parquet"),
    ]


def _cli() -> list:
    return [
        PageBreak(),
        p("3. Ligne de commande", H1),
        p("Les six commandes ci-dessous sont celles que la version installée accepte. Leur "
          "aide est reproduite telle que le logiciel la renvoie, et non réécrite : c'est "
          "exactement ce que vous obtenez en tapant la commande."),
        p("3.1 La commande et ses sous-commandes", H2),
        formule(aide_cli()),
        p("3.2 run — exécuter un scénario", H2),
        formule(aide_cli("run")),
        p("3.3 report — écrire un rapport PDF ou Excel", H2),
        formule(aide_cli("report")),
        p("Le format vient de l'extension du fichier de sortie : .pdf ou .xlsx. Sans option de "
          f"profil, report utilise {defaut_energie()} ; run, lui, n'ajoute les colonnes "
          "d'énergie que si le profil est demandé explicitement. La différence n'est pas une "
          "inconsistance : un rapport se lit, un Parquet se traite, et un traitement qui "
          "attend des colonnes préfère qu'elles n'apparaissent que lorsqu'elles sont "
          "demandées."),
        p("3.4 geojson — exporter une carte géoréférencée", H2),
        formule(aide_cli("geojson")),
        p("3.5 calibrate — ajuster la loi log-distance sur des mesures", H2),
        formule(aide_cli("calibrate")),
        p("3.6 downlink — mettre une commande en file pour un dispositif", H2),
        formule(aide_cli("downlink")),
        p("3.7 serve — serveur d'intégration des passerelles", H2),
        formule(aide_cli("serve")),
    ]


def _python() -> list:
    return [
        PageBreak(),
        p("4. Utilisation en Python", H1),
        p("La bibliothèque sert à ce qu'une ligne de commande ne sait pas faire : balayer un "
          "paramètre, comparer deux variantes, enchaîner des runs dans une seule session."),
        formule("from lsim.export import run_scenario\n"
                "from lsim.scenario import load_scenario\n"
                "\n"
                "scenario = load_scenario(\"examples/quartier_sf9.yaml\")\n"
                "result = run_scenario(scenario, energy_profile=\"rak4631\")\n"
                "print(result.pdr, result.totals.received)\n"
                "print(result.rows[0].energy_per_message_j)"),
        p("Le hash du scénario est stable : deux exécutions avec la même graine donnent les "
          "mêmes compteurs. C'est cette propriété qui rend légitime la comparaison de deux "
          "variantes — et c'est pour elle que l'empreinte du scénario est écrite dans les "
          "métadonnées du Parquet."),
        p("4.1 Ce qu'on peut interroger directement", H2),
        p("Chaque grandeur du modèle est exposée par une fonction, sans passer par une "
          "simulation. C'est ainsi qu'on vérifie une valeur avant de la croire :"),
        formule("from lsim import radio\n"
                "from lsim.lora import RadioConfig, time_on_air_ns\n"
                "\n"
                "radio.receiver_sensitivity_dbm(9, 125_000)          # sensibilité SF9 / 125 kHz\n"
                "radio.free_space_path_loss_db(1000, 868.1e6)        # perte en espace libre\n"
                "time_on_air_ns(RadioConfig(spreading_factor=9), 10) # temps d'antenne (ns)"),
    ]


def _sous_modeles() -> list:
    """Les objets imbriqués du scénario.

    La table du scénario renvoie à « objet (voir ci-dessous) » : cette section est ce
    « ci-dessous ». Sans elle, le manuel promettrait une description qu'il ne donne pas — et
    un lecteur chercherait en vain le champ qui l'intéresse.
    """
    from lsim.scenario import (EnergyModel, EnvironmentModel, GatewayModel, MacModel, MeshModel,
                               PropagationModel, RetransmissionsModel)
    blocs = []
    for titre, modele, note in [
        ("propagation — la loi radio", PropagationModel,
         "Les bornes sont celles de validité du modèle, pas des valeurs physiques."),
        ("gateway — la passerelle", GatewayModel,
         "Une seule passerelle : gateway. Plusieurs : gateways (même modèle, en liste)."),
        ("environment — relief et obstacles", EnvironmentModel,
         "Vide, il n'existe pas : le scénario reste celui d'avant, empreinte comprise."),
        ("energy — le profil de matériel", EnergyModel,
         "La priorité est : option de ligne de commande, puis ce bloc, puis le défaut."),
        ("mesh — les relais", MeshModel,
         "Le mesh exige des passerelles multiples et un profil de relais documenté."),
        ("mac — la couche MAC", MacModel,
         "Réglages de protocole ; la classe d'écoute, elle, se met par groupe."),
        ("retransmissions — uplinks confirmés", RetransmissionsModel,
         "Bloc facultatif : sans lui, aucune trame n'est réémise."),
    ]:
        blocs.append(p(titre, H2))
        blocs.append(tableau(["Champ", "Type", "Défaut"],
                             [[n, t, d] for n, t, d in champs(modele)],
                             largeurs=[32 * mm, 66 * mm, 52 * mm], note=note))
    return blocs


def _scenario() -> list:
    from lsim.scenario import GroupModel, ScenarioModel
    return [
        PageBreak(),
        p("5. Le scénario", H1),
        p("Un scénario est un fichier YAML validé strictement : un champ inconnu est refusé. "
          "Le tableau suivant est généré depuis le contrat de validation, avec le défaut de "
          "chaque champ — il ne peut donc omettre un champ qui existe, ni en inventer un qui "
          "n'existe pas."),
        p("5.1 Champs du scénario", H2),
        tableau(["Champ", "Type", "Défaut"],
                [[n, t, d] for n, t, d in champs(ScenarioModel)],
                largeurs=[32 * mm, 66 * mm, 52 * mm],
                note="« obligatoire » : le champ doit être présent. Les objets imbriqués sont "
                     "décrits plus bas."),
        p("5.2 Les objets imbriqués", H2),
        p("Chaque objet du scénario est décrit ci-dessous, avec le défaut de chacun de ses "
          "champs. Tous sont facultatifs : un scénario qui ne les mentionne pas garde les "
          "valeurs par défaut, et reste exactement celui d'avant."),
        *_sous_modeles(),
        p("5.3 Champs d'un groupe", H2),
        p("Un groupe est une population de capteurs : même réglage, placements tirés selon la "
          "graine. C'est l'unité de réglage du simulateur."),
        tableau(["Champ", "Type", "Défaut"],
                [[n, t, d] for n, t, d in champs(GroupModel)],
                largeurs=[32 * mm, 66 * mm, 52 * mm]),
        p("5.4 Les plans régionaux", H2),
        p("Régler une région sur un groupe lie le duty cycle effectif : c'est le plus "
          "restrictif entre le duty_cycle déclaré et la sous-bande du canal utilisé. Le "
          "tableau est lu dans le moteur."),
        tableau(["Région", "Canaux montants", "RX2", "Sous-bandes"],
                [[r["nom"], str(r["canaux"]),
                  f"{r['rx2_hz'] / 1e6:.3f} MHz {r['rx2_datr']}",
                  "oui" if r["sous_bandes"] else "non"] for r in regions()],
                largeurs=[20 * mm, 26 * mm, 60 * mm, 22 * mm],
                note="Les sources réglementaires de chaque région, avec leur statut de "
                     "vérification, sont dans docs/REGULATORY_SOURCES.md et résumées dans le "
                     "manuel technique §6."),
        p("5.5 Le profil d'énergie", H2),
        p("Deux matériels sont modélisés. Le profil se choisit par le scénario "
          "(energy.profile), par l'option --energy-profile, ou par défaut ; l'ordre de "
          "priorité est : option de ligne de commande, puis YAML, puis défaut."),
        tableau(["Profil", "Matériel", "Rx 125 kHz", "Veille"],
                [[pr["nom"], pr["libelle"], f"{pr['rx_ma']:.1f} mA",
                  f"{pr['veille_ua']:.2f} µA"] for pr in profils_energie()],
                largeurs=[30 * mm, 62 * mm, 22 * mm, 22 * mm],
                note=f"Profil par défaut : {defaut_energie()}. Les réserves attachées à ces "
                     "valeurs — notamment le Rx du SX1262 non publié au-delà de 125 kHz — "
                     "sont dans le manuel technique §4.2."),
        p("5.6 Ce que le YAML ne porte pas", H2),
        p("Aucun frontal RF : ni rf: à la racine, ni rf: dans un groupe — le champ est refusé. "
          "Les gains d'antenne et les pertes de câble se déclarent uniquement dans l'API "
          "Python, par DeviceRf et GatewayRf. Un scénario chargé depuis YAML décrit donc une "
          "population sans frontal ; pour mesurer un gain d'antenne, il faut passer par "
          "l'API. Ce n'est pas une restriction oubliée : c'est ce qui garantit qu'un scénario "
          "écrit avant l'introduction des frontaux garde exactement ses chiffres."),
    ]


def _atelier() -> list:
    return [
        PageBreak(),
        p("6. L'atelier 3D (studio)", H1),
        p("L'atelier est l'interface graphique : on y pose un réseau à la souris, on le règle, "
          "on lance un run, et on lit ce qui s'est passé. Il se lance en deux processus — "
          "l'API, puis le studio qui s'y adresse par un proxy."),
        formule("python -m lsim.api_server issue-token --tokens tokens.json --owner alice\n"
                "python -m lsim.api_server serve --tokens tokens.json --runs-db runs.sqlite "
                "--port 8765\n"
                "cd web && npm ci && LSIM_API_URL=http://127.0.0.1:8765 npx vite --port 5173"),
        p("Le studio est alors servi sur /studio.html. Le jeton est saisi dans la page ; il "
          "reste dans l'onglet et n'apparaît jamais dans une URL. Pour une instance locale "
          "sans saisie, l'option --auto-token <propriétaire> fait émettre un jeton au "
          "démarrage — à n'employer que sur une machine de développement, puisqu'elle "
          "désactive l'authentification."),
        p("6.1 Le tour de l'interface", H2),
        tableau(["Zone", "Ce qu'on y fait"],
                [["Barre d'outils", "Nouvelle session, suppression, annuler et rétablir, "
                                    "enregistrer et ouvrir un chantier"],
                 ["Palette", "Glisser un équipement sur la carte 3D pour le poser : "
                             "passerelle, relais, capteur, serveur"],
                 ["Vues", "Carte 3D (CesiumJS) et plan 2D métrique — les deux tracent les "
                          "liaisons observées"],
                 ["Panneau d'observation", "Simulation, Journal, Trame, Runs, Exercice, "
                                           "Obstacles"],
                 ["Fenêtres d'équipement", "Une par équipement, trois onglets : Physique, "
                                           "Config, CLI. Déplaçables, pour comparer deux "
                                           "configurations côte à côte"]],
                largeurs=[34 * mm, 116 * mm]),
        p("6.2 L'onglet Runs : revoir et comparer", H2),
        p("Un chantier garde ses seize derniers runs. L'onglet les liste du plus récent au "
          "plus ancien, avec la graine, la date, l'état et les grands nombres. Deux boutons "
          "par ligne :"),
        brut("<b>Revoir</b> rouvre un run : ses chiffres, son plan et son journal remplacent "
             "ceux de l'écran. Le chantier ne bouge pas.", NOTE),
        brut("<b>Comparer</b> met le run choisi face au run affiché, avec l'écart. Seules les "
             "grandeurs <b>mesurées par les deux</b> runs sont comparées : un écart calculé "
             "contre une case vide inventerait une différence.", NOTE),
        p("Un run non terminé ne publie aucun chiffre : ses colonnes restent vides plutôt "
          "qu'à zéro. Un run sorti des seize n'est pas effacé, il cesse d'être rattaché — il "
          "reste consultable par son identifiant."),
        p("6.3 Le serveur de réseau", H2),
        p("Le serveur ne se configure pas : c'est lui qui commande le débit, les canaux et "
          "les descentes. Sa fenêtre montre donc ce qu'il a **vu** du run, par équipement : "
          "trames remises sur émises, pertes hors portée puis en collision, débit commandé, "
          "canaux laissés au terminal, et les commandes envoyées quand le run en a planifié."),
        p("Rien n'y est recopié depuis les formulaires : un champ que le run n'a pas observé "
          "reste vide, et la flèche SF7 → SF9 n'apparaît que si le serveur a commandé un "
          "changement **et** que le terminal l'a appliqué. Sinon elle recopierait le réglage "
          "de départ en laissant croire à une décision du réseau.", NOTE),
        p("6.4 Obstacles, shadowing et hauteurs", H2),
        p("Un mur se trace au rectangle sur le plan métrique. Chaque mur porte une atténuation "
          "saisie en dB, ou un matériau et une épaisseur dont le moteur calcule la perte "
          "(UIT-R P.2040-4). Rien n'est émis tant que rien n'est réglé."),
        tableau(["Réglage", "Ordre de grandeur mesuré"],
                [["Mur en travers, 6 dB", "à 10 km SF10 : 20 reçues sur 20 → 0 sur 20"],
                 ["Hauteur de passerelle", "face à un mur de 12 m : 0 à 15 m, 20 sur 20 à 40 m"],
                 ["Shadowing σ = 8 dB", "à 10 km, 40 graines : 30 restent entendues"],
                 ["Matériau à 868 MHz", "12 des 15 hors plage documentée : perte extrapolée"]],
                largeurs=[45 * mm, 105 * mm],
                note="Le caractère extrapolé est affiché à côté du matériau, et l'atténuation "
                     "saisie reste le chemin par défaut."),
        p("6.5 Annuler et rétablir", H2),
        p("L'historique vit côté serveur, parce que le CLI y vit aussi : annuler « region "
          "US915 » restaure la configuration de l'équipement, pas seulement la case que "
          "l'interface affichait. Un geste par opération — ajout, retrait, déplacement, ligne "
          "CLI qui change la configuration, réglages de capteur, modèle de passerelle, "
          "relief, environnement, ADR, protocole. La navigation n'en est pas un, ni un geste "
          "sans effet : quatre lignes tapées pour régler une région s'annulent d'un seul "
          "coup, et déplacer un équipement sur place n'empile rien."),
        p("Les deux boutons sont grisés **avec leur raison**, et nomment l'opération qu'ils "
          "vont annuler. Profondeur 50. Les piles ne sont pas écrites dans le fichier de runs "
          ": une session rechargée après redémarrage repart sans historique."),
    ]


def _exercices() -> list:
    ex = exercices()
    return [
        PageBreak(),
        p("7. Les exercices notés", H1),
        p("L'atelier propose des exercices corrigés automatiquement. Les critères et la "
          "solution restent côté serveur : le navigateur n'envoie jamais de résultat, il "
          "soumet l'identifiant d'une session, et le serveur la note sur l'état qu'il "
          "détient. Tricher consisterait à modifier le serveur, pas la page."),
        p("Chaque exercice a deux indices, révélés un à un ; chaque indice retire deux points, "
          "avec un plancher à zéro. Le catalogue ci-dessous est lu dans le serveur."),
        tableau(["Exercice", "Titre", "Points", "Indices"],
                [[e["id"], e["titre"], str(e["points"]), str(e["indices"])] for e in ex],
                largeurs=[34 * mm, 86 * mm, 14 * mm, 16 * mm],
                note=f"{len(ex)} exercices, "
                     f"{sum(e['points'] for e in ex)} points au total."),
        p("7.1 Ce que les exercices exigent, et pourquoi", H2),
        p("Le plus exigeant n'est pas le plus long : c'est celui qui demande de prouver, et "
          "non de cocher. Dans « Faire changer le débit par le serveur, et le prouver », la "
          "case ADR cochée rapporte dix points ; les vingt autres ne tombent que si le run a "
          "**observé** un SF final plus bas que le SF de départ. À vingt messages la commande "
          "part mais le terminal ne l'applique pas encore : il en faut quarante, et c'est "
          "l'élève qui doit le découvrir en lisant le run."),
        p("De la même manière, « Une flotte qui joint au même instant n'émet rien » se "
          "corrige en étalant les départs : quatre capteurs qui émettent leur join-request à "
          "la même seconde sur le même canal se collisionnent, et personne n'est accepté. Le "
          "run passe alors de zéro à vingt uplinks de données — la leçon est dans le chiffre, "
          "pas dans l'énoncé."),
        p("7.2 Où se terminer", H2),
        p("Un exercice se termine dans l'atelier, pas seulement au clavier : les réglages "
          "qu'il demande sont atteignables par les fenêtres de configuration, et non par la "
          "seule console. C'est une propriété vérifiée par les tests, exercice par exercice — "
          "un exercice qui obligerait à ouvrir la console serait un exercice qui enseigne un "
          "outil au lieu d'enseigner un réseau."),
    ]


def _passerelles() -> list:
    return [
        PageBreak(),
        p("8. Raccorder de vraies passerelles", H1),
        p("Le simulateur sait aussi se comporter en serveur d'intégration : une passerelle "
          "réelle peut y envoyer ses trames, et le serveur de jointure répond. Deux protocoles "
          "sont servis."),
        tableau(["Protocole", "Transport", "État"],
                [["Semtech UDP (GWMP v2)", "UDP", "PUSH_ACK, routes PULL_DATA, join-accept en "
                                                  "PULL_RESP à tmst + 5 s"],
                 ["Basic Station", "WebSocket", "router-info, router_config, jreq, updf, "
                                                "dnmsg, dntxed, timesync"]],
                largeurs=[38 * mm, 24 * mm, 88 * mm],
                note="Le détail des formats, des bornes et des vecteurs officiels vérifiés "
                     "est dans docs/USAGE.md §5bis et §5ter."),
        p("Le registre de jointure garde DevNonce et RJcount par dispositif, n'écrit qu'après "
          "vérification du MIC, et se persiste dans une base SQLite protégée par MIC. Un "
          "registre absent ou non rechargé remet les compteurs à zéro : c'est une fenêtre de "
          "rejeu. Le serveur doit donc recharger sa sauvegarde avant de servir des jointures "
          "— la remarque vaut pour une mise en production, pas pour un essai."),
        p("LR-FHSS n'est pas géré : les uplinks DR5/DR6 de US915 et la modulation LRFHSS sont "
          "refusés explicitement, et un test le vérifie. Mieux vaut un refus clair qu'un "
          "silence qui laisserait croire à une modulation simulée."),
    ]


def _lire_resultats() -> list:
    return [
        PageBreak(),
        p("9. Lire un résultat sans se tromper", H1),
        p("La plupart des erreurs d'interprétation viennent de quatre confusions. Elles sont "
          "faciles à éviter, à condition de savoir qu'elles existent."),
        tableau(["On croit lire", "En réalité"],
                [["« Le PDR est de 0 % »", "Le run n'a peut-être mesuré aucune trame. Une "
                                           "colonne vide n'est pas un zéro ; le simulateur "
                                           "ne publie pas de zéro là où il n'y a pas eu de "
                                           "mesure"],
                 ["« L'ADR a changé le débit »", "La case dit ce qui a été demandé. Le SF "
                                                 "final, dans les résultats du run, dit ce "
                                                 "qui a été appliqué — et il peut être absent "
                                                 "sans que rien n'ait échoué"],
                 ["« La passerelle entend à 40 km »", "La bascule est le point où le bilan de "
                                                      "liaison change de signe, pas une "
                                                      "portée garantie : il n'y a ni fading "
                                                      "ni probabilité"],
                 ["« Ce matériau atténue de 8 dB »", "À 868 MHz, 12 des 15 matériaux sortent "
                                                     "de la plage documentée : la perte est "
                                                     "extrapolée, et l'interface le dit"]],
                largeurs=[52 * mm, 98 * mm]),
        p("9.1 Les indicateurs et ce qu'ils comptent", H2),
        tableau(["Indicateur", "Ce qu'il compte", "Ce qu'il ne compte pas"],
                [["PDR", "Trames reçues sur trames émises", "Les trames jamais émises faute "
                                                            "de canal disponible"],
                 ["Latence", "Le temps d'antenne", "Ni file d'attente, ni backhaul : c'est un "
                                                   "plancher, pas une estimation de bout en "
                                                   "bout"],
                 ["Occupation", "Le temps où la passerelle est occupée", "Les interférences "
                                                                         "venant d'un réseau "
                                                                         "tiers"],
                 ["Courant moyen", "Le courant d'un message par période, en classe A",
                  "La capacité de la pile, et donc l'autonomie en années"]],
                largeurs=[28 * mm, 62 * mm, 60 * mm]),
        p("9.2 Quand le résultat surprend", H2),
        p("Trois causes reviennent, dans cet ordre. Un canal hors du plan régional : le "
          "scénario est refusé au chargement, le message le dit. Un duty cycle trop "
          "restrictif pour la période demandée : les messages s'espacent d'eux-mêmes, et le "
          "nombre de trames émises baisse sans que rien n'échoue. Une distance de référence "
          "d₀ qui n'est pas celle qu'on croyait : à n = 2 elle n'a aucun effet, à n = 2,7 "
          "elle décale tout de 7 dB par décade."),
        p("Pour trancher, le plus court est de mesurer la grandeur directement plutôt que de "
          "raisonner sur le scénario : radio.receiver_sensitivity_dbm, "
          "free_space_path_loss_db et time_on_air_ns répondent en une ligne, et ce sont les "
          "mêmes fonctions que le simulateur appelle."),
        p("Ce manuel a été généré depuis le logiciel ; la version au moment de la génération "
          f"est {version()}. Les hypothèses de physique, leurs formules et leurs références "
          "sont dans le manuel technique.", NOTE),
    ]


def construire(chemin: str) -> None:
    story = _couverture() + _presentation() + _installation() + _cli() + _python() \
        + _scenario() + _atelier() + _exercices() + _passerelles() + _lire_resultats()
    story.append(Spacer(1, 8))
    ecrire(chemin, story, TITRE_DOC)


if __name__ == "__main__":
    import sys
    construire(sys.argv[1] if len(sys.argv) > 1 else "docs/manuel-utilisation.pdf")
