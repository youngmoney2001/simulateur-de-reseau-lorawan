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
    # 400..449 : jointure OTAA
    401: "join : longueur de message invalide",
    402: "join : type de message (MHDR) inattendu",
    403: "join : tampon de sortie trop petit",
    404: "join : MIC invalide, champs non exposés",
    405: "join : échec cryptographique",
    406: "join : champ hors domaine",
    # 900 : erreur interne (exception interceptée à la frontière)
    900: "erreur interne du cœur",
}


def describe(code: int) -> str:
    """Libellé français d'un code de statut natif."""
    return _NAMES.get(code, "erreur inconnue")
