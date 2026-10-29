"""Chiffrement authentifié au repos des données sensibles du serveur (AES-256-GCM).

- Clé de données de 32 octets, fournie par l'appelant (variable LSIM_DATA_KEY), distincte de la
  clé d'intégrité du registre et stockée hors de la base.
- Nonce aléatoire de 96 bits par écriture ; le texte chiffré inclut le tag d'authenticité.
- AAD (données associées) : chaque enregistrement est lié à sa clé logique (DevAddr, DevEUI,
  nom de table). Un enregistrement copié vers une autre ligne est donc refusé.
- Bibliothèque : `cryptography` (dépendance optionnelle, extra « serve »). Aucune primitive
  maison : AES-GCM est la construction standard fournie par la bibliothèque.

Limites : un attaquant qui restaure une ancienne copie complète de la base (et de sa clé)
rétablit les compteurs anciens ; la protection contre ce cas relève de la sauvegarde et de la
gestion des clés, non de ce module. Rotation de clé : non implémentée.
"""

from __future__ import annotations

import os

NONCE_LEN = 12
KEY_LEN = 32


class IntegrityError(ValueError):
    """Enregistrement falsifié, déplacé, ou chiffré avec une autre clé."""


def _aesgcm():
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as exc:  # pragma: no cover - dépend de l'environnement
        raise RuntimeError(
            "module « cryptography » absent : pip install 'lsim[serve]' (chiffrement au repos)"
        ) from exc
    return AESGCM


class RecordSealer:
    def __init__(self, key: bytes) -> None:
        if not isinstance(key, (bytes, bytearray)) or len(key) != KEY_LEN:
            raise ValueError("clé de données : 32 octets attendus (AES-256)")
        self._aead = _aesgcm()(bytes(key))

    def seal(self, plaintext: bytes, aad: bytes) -> bytes:
        nonce = os.urandom(NONCE_LEN)
        return nonce + self._aead.encrypt(nonce, bytes(plaintext), bytes(aad))

    def open(self, blob: bytes, aad: bytes) -> bytes:
        if len(blob) < NONCE_LEN + 16:
            raise IntegrityError("enregistrement chiffré trop court")
        try:
            return self._aead.decrypt(bytes(blob[:NONCE_LEN]), bytes(blob[NONCE_LEN:]), bytes(aad))
        except Exception as exc:  # InvalidTag de cryptography ; message volontairement générique
            raise IntegrityError("enregistrement falsifié, déplacé, ou clé de données incorrecte") from exc
