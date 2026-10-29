"""Table unique des codes de statut du cœur natif (voir c_api.h pour les plages)."""

from __future__ import annotations

_NAMES = {
    # 0..99 : PHY et lien radio
    0: "ok",
    1: "spreading_factor invalide (7..12)",
    2: "bande passante invalide (125/250/500 kHz)",
    3: "coding_rate invalide (1..4)",
    4: "taille de charge utile invalide (0..255)",
    5: "préambule invalide (>= 6)",
    6: "pointeur de sortie nul",
    7: "sensibilité non calibrée pour cette bande passante",
    8: "paramètre physique invalide",
    # 100..199 : crypto
    100: "crypto : longueur de message invalide",
    101: "crypto : erreur interne de la bibliothèque",
    # 200..249 : trame sécurisée
    201: "trame sécurisée : erreur de codec",
    202: "MIC invalide : trame rejetée, rien n'est déchiffré",
    203: "compteur de trame incohérent avec les 16 bits transmis",
    204: "échec cryptographique",
    205: "tampon de sortie trop petit",
    206: "charge utile hors bornes ou port réservé",
    # 250..299 : codec (statuts internes, non exposés directement)
    # 300..399 : simulateur
    301: "entrée de simulation invalide",
    302: "trop de dispositifs (limite 10 000)",
    303: "trop de transmissions (limite 5 000 000)",
    304: "file d'événements pleine",
    305: "environnement invalide (relief ou obstacles)",
    306: "environnement : travail de calcul trop grand (dispositifs x obstacles)",
    307: "trop de requêtes de downlink (limite 5 000 000)",
    308: "tampon de trace trop petit (taille requise dans record_count)",
    309: "trace trop grande (limite 200 000 émissions par simulation)",
    310: "périodes d'émission passerelle invalides (début < fin requis)",
    # 400..449 : jointure OTAA
    401: "join : longueur de message invalide",
    402: "join : type de message (MHDR) inattendu",
    403: "join : tampon de sortie trop petit",
    404: "join : MIC invalide, champs non exposés",
    405: "join : échec cryptographique",
    406: "join : champ hors domaine",
    # 500..599 : environnement (relief, obstacles)
    501: "relief invalide : grille incohérente ou valeurs non finies",
    502: "relief trop grand (limite 4 000 000 points)",
    503: "obstacle invalide (emprise vide, hauteur ou atténuation hors domaine)",
    504: "trop d'obstacles (limite 10 000)",
    505: "environnement : entrée invalide (pointeur nul avec obstacles déclarés)",
    506: "couverture : travail de calcul trop grand (azimuts x portée x obstacles)",
    # 600..649 : commandes MAC
    601: "commande MAC : tampon trop petit ou FOpts plein",
    602: "commande MAC : charge utile tronquée ou bit RFU non nul",
    603: "commande MAC : champ hors domaine",
    604: "commande MAC : CID non implémenté",
    # 650..699 : rejoin-request
    651: "rejoin : tampon de sortie trop petit",
    652: "rejoin : longueur de message invalide",
    653: "rejoin : MHDR inattendu",
    654: "rejoin : type de rejoin inconnu",
    655: "rejoin : MIC invalide, champs non exposés",
    656: "rejoin : échec cryptographique",
    657: "rejoin : champ hors domaine",
    # 700..749 : registre serveur (RegistryStatus + 700)
    701: "registre : message malformé",
    702: "registre : MIC invalide, aucun compteur enregistré",
    703: "registre : échec cryptographique",
    704: "registre : compteur non croissant (rejeu)",
    705: "registre : capacité atteinte (nouveau dispositif refusé)",
    706: "registre : tampon de sortie trop petit",
    707: "registre : sauvegarde falsifiée ou clé d'intégrité fausse (rien chargé)",
    708: "registre : format de sauvegarde inconnu",
    709: "registre : sauvegarde incohérente (tailles, doublons)",
    740: "registre : handle inconnu ou fermé",
    741: "registre : paramètre invalide",
    # 760..799 : ADR serveur
    761: "ADR : paramètre invalide (SNR, plan de débits ou puissance)",
    # 780..789 : moteur de session dispositif
    781: "session : aucune session active (join requis)",
    782: "session : cycle d'uplink mal ordonné",
    783: "session : compteur descendant déjà consommé (rejeu)",
    784: "session : paramètre invalide",
    785: "session : compteur FCntUp épuisé (rejoin requis)",
    786: "session : handle inconnu ou fermé",
    # 800..809 : moteur de classe B
    801: "classe B : paramètre invalide (périodicité, temps, trame trop courte, RFU)",
    802: "classe B : CRC-16 du beacon faux",
    803: "classe B : aucun beacon reçu",
    804: "classe B : balise perdue depuis 2 h (quitter la classe B)",
    # 900 : erreur interne (exception interceptée à la frontière)
    900: "erreur interne du cœur",
}


def describe(code: int) -> str:
    """Libellé français d'un code de statut natif."""
    return _NAMES.get(code, "erreur inconnue")
