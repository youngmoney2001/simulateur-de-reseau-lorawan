"""Serveur de jointure : acceptation des join-requests et rejoin-requests, persistance durable.

Pour chaque join-request valide, dans une seule transaction :
1. le MIC est vérifié et le DevNonce doit être strictement croissant (cœur natif) ;
2. le JoinNonce du dispositif est incrémenté (compteur persistant, jamais réutilisé) ;
3. une DevAddr est allouée : NwkID du NetID (7 bits) puis compteur de 25 bits ;
4. RJcount0 du dispositif est remis à zéro ;
5. le join-accept est chiffré avec NwkKey.
Si une étape échoue, la transaction est annulée : aucun DevNonce ni compteur n'est consommé.

Rejoin-requests (1.1 §6.2.4) : `handle_rejoin` vérifie le MIC et le compteur (RJcount) sans
répondre. `accept_rejoin` produit en plus le join-accept de rejoin, dans la même transaction
(§6.2.4.4) : JSEncKey pour le chiffrement, JSIntKey pour le MIC, JoinReqType 0x00, 0x01 ou 0x02,
RJcount à la place de DevNonce (dérivation des clés de session). Pour les types 0 et 2, le
message ne porte pas le JoinEUI : il est fourni par `DeviceKeys.join_eui` (provisionné avec le
dispositif). Le join-accept réinitialise RJcount0 côté serveur, comme côté dispositif.
L'ancien contexte de sécurité reste valide : le nouveau est mis en attente, et devient la session
au premier uplink valide qui l'utilise (1.1 §6.2.4). Un uplink encore sur l'ancien contexte
n'y change rien. Une join-request complète remplace les deux.

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
from lsim.security import (
    JoinAccept,
    derive_session_keys_11,
    encode_join_accept,
    encode_rejoin_join_accept,
)

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
    # JoinEUI provisionné : requis pour rejoin type 0/2 (le message ne le porte pas).
    join_eui: Optional[bytes] = None

    def __post_init__(self) -> None:
        for name in ("nwk_key", "app_key", "s_nwk_s_int_key", "js_int_key"):
            value = getattr(self, name)
            if value is None and name != "nwk_key":
                continue
            if not isinstance(value, (bytes, bytearray)) or len(value) != 16:
                raise ValueError(f"{name} doit faire 16 octets")
        if self.join_eui is not None and (
                not isinstance(self.join_eui, (bytes, bytearray)) or len(self.join_eui) != 8):
            raise ValueError("join_eui doit faire 8 octets")

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


@dataclass(frozen=True)
class RejoinOutcome:
    """Rejoin accepté et join-accept de rejoin produit (même transaction)."""
    rejoin_type: int
    dev_eui: bytes
    join_eui: bytes
    rjcount: int
    join_nonce: int
    dev_addr: int
    accept_wire: bytes = field(repr=False)


KeyProvider = Callable[[bytes], DeviceKeys]


class JoinServer:
    """Serveur de jointure au-dessus d'un `DurableJoinStore`."""

    def __init__(self, store: DurableJoinStore, net_id: bytes, key_provider: KeyProvider,
                 dl_settings: int = _DL_SETTINGS_OPTNEG, rx_delay: int = 1,
                 on_join: Optional[Callable[[object, bytes], None]] = None) -> None:
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
        # Appelé dans la transaction de jointure, après persistance de la session (DevEUI).
        self._on_join = on_join

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
            if self._on_join is not None:
                self._on_join(tx, req.dev_eui)
        return JoinOutcome(dev_eui=req.dev_eui, join_eui=req.join_eui, dev_nonce=req.dev_nonce,
                           join_nonce=join_nonce, dev_addr=dev_addr, accept_wire=accept)

    def _issue_session(self, tx, dev_eui: bytes, join_eui: bytes, dev_nonce_slot: bytes,
                       keys: DeviceKeys, *, pending: bool) -> tuple[int, int, bytes, JoinAccept]:
        """JoinNonce, DevAddr et session. `pending` : rejoin, contexte mis en attente."""
        join_nonce = tx.next_value("join_nonce", dev_eui, _JOIN_NONCE_LIMIT)
        nwk_addr = tx.next_value("nwk_addr", b"", _NWK_ADDR_LIMIT)
        dev_addr = (self._nwk_id << 25) | nwk_addr
        tx.set_device_address(dev_eui, dev_addr)
        join_nonce_wire = join_nonce.to_bytes(3, "little")
        accept = JoinAccept(join_nonce=join_nonce_wire, net_id=self._net_id,
                            dev_addr=dev_addr, dl_settings=self._dl_settings,
                            rx_delay=self._rx_delay)
        session = derive_session_keys_11(
            keys.nwk_key, keys.app_key or bytes(16), join_nonce_wire, join_eui, dev_nonce_slot)
        store = tx.put_pending_session if pending else tx.put_session
        store(dev_eui, dev_addr, session, has_app_key=keys.app_key is not None)
        return join_nonce, dev_addr, join_nonce_wire, accept

    def accept_rejoin(self, wire: bytes) -> RejoinOutcome:
        """Accepte une rejoin-request et produit son join-accept (1.1 §6.2.4.4), atomiquement.

        Lève StatusError (MIC, RJcount), KeyError (dispositif inconnu) ou ValueError (clé ou
        JoinEUI absent) ; dans ces cas, aucun état n'est modifié.
        """
        if not isinstance(wire, (bytes, bytearray)) or len(wire) < 2:
            raise ValueError("rejoin-request trop courte")
        rejoin_type = wire[1]
        if rejoin_type in (0, 2):
            if len(wire) != _REJOIN_02_LEN:
                raise ValueError("rejoin-request de type 0/2 : 19 octets attendus")
            dev_eui = bytes(wire[5:13])
            keys = self._keys(dev_eui)
            if keys.s_nwk_s_int_key is None:
                raise ValueError("clé SNwkSIntKey absente : rejoin type 0/2 impossible")
            if keys.join_eui is None:
                raise ValueError("JoinEUI provisionné absent : rejoin type 0/2 impossible")
            join_eui = keys.join_eui
        elif rejoin_type == 1:
            if len(wire) != _REJOIN_1_LEN:
                raise ValueError("rejoin-request de type 1 : 24 octets attendus")
            dev_eui = bytes(wire[10:18])
            keys = self._keys(dev_eui)
            if keys.js_int_key is None:
                raise ValueError("clé JSIntKey absente : rejoin type 1 impossible")
            join_eui = bytes(wire[2:10])
        else:
            raise ValueError("type de rejoin-request inconnu")
        with self._store.transaction() as tx:
            if rejoin_type in (0, 2):
                check = tx.registry.accept_rejoin_02(bytes(wire), keys.s_nwk_s_int_key)
                rjcount = check.rjcount0
                # Le join-accept remet RJcount0 à zéro côté dispositif : même effet ici.
                tx.registry.on_join_accepted(dev_eui)
            else:
                check = tx.registry.accept_rejoin_1(bytes(wire), keys.js_int_key)
                rjcount = check.rjcount1
            slot = rjcount.to_bytes(2, "little")
            join_nonce, dev_addr, join_nonce_wire, accept = self._issue_session(
                tx, dev_eui, join_eui, slot, keys, pending=True)
            accept_wire = encode_rejoin_join_accept(
                accept, keys.nwk_key, dev_eui, join_eui, rejoin_type, rjcount)
            if rejoin_type in (0, 1):
                # Join-accept après rejoin type 0 ou 1 : paramètres MAC remis à leurs valeurs par
                # défaut (1.1 §6.2.3). Les commandes en attente ne s'appliquent plus. Type 2 :
                # paramètres radio conservés, commandes gardées. Fait avant on_join, qui peut
                # en émettre de nouvelles.
                tx.clear_mac_pending(dev_eui)
            if self._on_join is not None:
                self._on_join(tx, dev_eui)
        return RejoinOutcome(rejoin_type=rejoin_type, dev_eui=dev_eui, join_eui=join_eui,
                             rjcount=rjcount, join_nonce=join_nonce, dev_addr=dev_addr,
                             accept_wire=accept_wire)

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
