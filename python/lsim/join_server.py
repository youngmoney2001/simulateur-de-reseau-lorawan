"""Serveur de jointure : acceptation des join-requests et rejoin-requests, persistance durable.

Pour chaque join-request valide, dans une seule transaction :
1. le MIC est vérifié et le DevNonce doit être strictement croissant (cœur natif) ;
2. le JoinNonce du dispositif est incrémenté (compteur persistant, jamais réutilisé) ;
3. une DevAddr est allouée : NwkID du NetID (7 bits) puis compteur de 25 bits ;
4. RJcount0 du dispositif est remis à zéro ;
5. le join-accept est chiffré avec NwkKey.
Si une étape échoue, la transaction est annulée : aucun DevNonce ni compteur n'est consommé.

Limite (source) : les rejoin-requests (types 0, 1, 2) sont vérifiés et comptés, mais ce module
ne génère pas le join-accept qui les suit. La spec LoRaWAN 1.1 (§6.2.4.1, §6.2.4.2, §6.2.3,
tableaux 13 et 14) ne définit ni DevNonce ni JoinEUI pour ce join-accept (type 0/2 : ni JoinEUI
ni DevNonce ; type 1 : pas de DevNonce) : le MIC JSIntKey et le chiffrement JSEncKey ne peuvent pas
être encodés sans entrée inventée. Levée par un erratum officiel, pas par ce module.
Les clés sont fournies par `key_provider` : ce module ne stocke aucune clé de racine.
La session de données (clés de session 1.1 et compteurs) est créée dans la même transaction que
le join-accept : une jointure acceptée sans session est impossible. Sans AppKey, AppSKey n'est
pas utilisable (FPort > 0 refusé par la couche données).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional, Union

from lsim.join_store import DurableJoinStore
from lsim.rejoin import Rejoin02, Rejoin1
from lsim.security import JoinAccept, derive_session_keys_11, encode_join_accept

_JOIN_REQUEST_LEN = 23
_REJOIN_02_LEN = 19
_REJOIN_1_LEN = 24
_JOIN_NONCE_LIMIT = 1 << 24      # JoinNonce : 3 octets
_NWK_ADDR_LIMIT = 1 << 25        # NwkAddr : 25 bits
_DL_SETTINGS_OPTNEG = 0x80        # bit 7 = OptNeg : mode LoRaWAN 1.1


@dataclass(frozen=True)
class DeviceKeys:
    """Clés d'un dispositif. Le join n'exige que `nwk_key` ; les rejoins exigent leur clé."""
    nwk_key: bytes = field(repr=False)                           # join-request, join-accept
    s_nwk_s_int_key: Optional[bytes] = field(default=None, repr=False)   # rejoin types 0 et 2
    js_int_key: Optional[bytes] = field(default=None, repr=False)        # rejoin type 1
    app_key: Optional[bytes] = field(default=None, repr=False)           # dérivation AppSKey

    def __post_init__(self) -> None:
        for name in ("nwk_key", "app_key", "s_nwk_s_int_key", "js_int_key"):
            value = getattr(self, name)
            if value is None and name != "nwk_key":
                continue
            if not isinstance(value, (bytes, bytearray)) or len(value) != 16:
                raise ValueError(f"{name} doit faire 16 octets")

    def __repr__(self) -> str:
        return "DeviceKeys(<secret>)"


@dataclass(frozen=True)
class JoinOutcome:
    dev_eui: bytes
    join_eui: bytes
    dev_nonce: bytes
    join_nonce: int
    dev_addr: int
    accept_wire: bytes = field(repr=False)


KeyProvider = Callable[[bytes], DeviceKeys]


class JoinServer:
    """Serveur de jointure au-dessus d'un `DurableJoinStore`."""

    def __init__(self, store: DurableJoinStore, net_id: bytes, key_provider: KeyProvider,
                 dl_settings: int = _DL_SETTINGS_OPTNEG, rx_delay: int = 1) -> None:
        if not isinstance(net_id, (bytes, bytearray)) or len(net_id) != 3:
            raise ValueError("net_id doit faire 3 octets (ordre de transmission)")
        if not 0 <= dl_settings <= 255 or not 0 <= rx_delay <= 255:
            raise ValueError("dl_settings et rx_delay doivent tenir sur 8 bits")
        self._store = store
        self._net_id = bytes(net_id)
        self._nwk_id = net_id[0] & 0x7F          # NwkID = 7 bits de poids faible du NetID
        self._keys = key_provider
        self._dl_settings = dl_settings
        self._rx_delay = rx_delay

    def handle_join_request(self, wire: bytes) -> JoinOutcome:
        """Accepte une join-request ; lève StatusError (MIC, rejeu) ou KeyError (dispositif inconnu)."""
        if not isinstance(wire, (bytes, bytearray)) or len(wire) != _JOIN_REQUEST_LEN:
            raise ValueError("join-request de 23 octets attendue")
        # EUI non vérifiés, utilisés seulement pour choisir la clé ; le MIC tranche ensuite.
        keys = self._keys(bytes(wire[9:17]))
        with self._store.transaction() as tx:
            req = tx.registry.accept_join_request(bytes(wire), keys.nwk_key)
            join_nonce = tx.next_value("join_nonce", req.dev_eui, _JOIN_NONCE_LIMIT)
            nwk_addr = tx.next_value("nwk_addr", b"", _NWK_ADDR_LIMIT)
            dev_addr = (self._nwk_id << 25) | nwk_addr
            tx.registry.on_join_accepted(req.dev_eui)
            tx.set_device_address(req.dev_eui, dev_addr)
            join_nonce_wire = join_nonce.to_bytes(3, "little")
            accept = encode_join_accept(
                JoinAccept(join_nonce=join_nonce_wire, net_id=self._net_id,
                           dev_addr=dev_addr, dl_settings=self._dl_settings,
                           rx_delay=self._rx_delay),
                keys.nwk_key, req.dev_eui, req.join_eui, req.dev_nonce)
            # AppSKey ne dépend que de AppKey : sans AppKey, elle n'est pas exploitable.
            session = derive_session_keys_11(
                keys.nwk_key, keys.app_key or bytes(16), join_nonce_wire, req.join_eui,
                req.dev_nonce)
            tx.put_session(req.dev_eui, dev_addr, session, has_app_key=keys.app_key is not None)
        return JoinOutcome(dev_eui=req.dev_eui, join_eui=req.join_eui, dev_nonce=req.dev_nonce,
                           join_nonce=join_nonce, dev_addr=dev_addr, accept_wire=accept)

    def handle_rejoin(self, wire: bytes) -> Union[Rejoin02, Rejoin1]:
        """Accepte une rejoin-request (types 0, 1, 2) : MIC et RJcount vérifiés, état persisté."""
        if not isinstance(wire, (bytes, bytearray)) or len(wire) < 2:
            raise ValueError("rejoin-request trop courte")
        rejoin_type = wire[1]
        if rejoin_type in (0, 2):
            if len(wire) != _REJOIN_02_LEN:
                raise ValueError("rejoin-request de type 0/2 : 19 octets attendus")
            keys = self._keys(bytes(wire[5:13]))
            if keys.s_nwk_s_int_key is None:
                raise ValueError("clé SNwkSIntKey absente : rejoin type 0/2 impossible")
            return self._store.accept_rejoin_02(bytes(wire), keys.s_nwk_s_int_key)
        if rejoin_type == 1:
            if len(wire) != _REJOIN_1_LEN:
                raise ValueError("rejoin-request de type 1 : 24 octets attendus")
            keys = self._keys(bytes(wire[10:18]))
            if keys.js_int_key is None:
                raise ValueError("clé JSIntKey absente : rejoin type 1 impossible")
            return self._store.accept_rejoin_1(bytes(wire), keys.js_int_key)
        raise ValueError("type de rejoin-request inconnu")
