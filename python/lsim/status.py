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
    # 900 : erreur interne (exception interceptée à la frontière)
    900: "erreur interne du cœur",
}


def describe(code: int) -> str:
    """Libellé français d'un code de statut natif."""
    return _NAMES.get(code, "erreur inconnue")
