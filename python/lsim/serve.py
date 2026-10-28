"""Commande `lsim serve` : passerelles Semtech UDP → serveur de jointure.

Secrets :
- clé d'intégrité du registre : variable d'environnement LSIM_INTEGRITY_KEY (32 caractères hex) ;
- clés des dispositifs : fichier JSON
  `{"devices": {"<DevEUI hex>": {"nwk_key": "<32 hex>", "app_key": "<32 hex, optionnel>"}}}`,
  refusé si accessible au groupe ou aux autres (mode 0600 attendu).
  Sans app_key : les uplinks FPort 0 sont vérifiés, mais FPort > 0 n'est pas déchiffré ni livré.
Aucun secret n'est écrit dans les journaux ; les charges utiles ne sont pas journalisées.

Couche données : plan EU868 uniquement (voir `lsim.eu868`). `lsim downlink` met un downlink en
file ; il est émis au prochain uplink du dispositif (classe A).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import stat
from pathlib import Path

from lsim.gwmp_server import JoinUplinkHandler, start_server
from lsim.join_server import DeviceKeys, JoinServer
from lsim.join_store import DurableJoinStore
from lsim.uplink import DataUplinkHandler, Delivery, UplinkRouter

INTEGRITY_ENV = "LSIM_INTEGRITY_KEY"
DEFAULT_PORT = 1700          # port conventionnel des passerelles Semtech (choix de déploiement)


def _hex(value: object, nbytes: int, what: str) -> bytes:
    if not isinstance(value, str) or len(value) != 2 * nbytes:
        raise ValueError(f"{what} : {2 * nbytes} caractères hexadécimaux attendus")
    try:
        return bytes.fromhex(value)
    except ValueError as exc:
        raise ValueError(f"{what} : hexadécimal invalide") from exc


def load_keys_file(path: Path) -> dict[bytes, DeviceKeys]:
    """Charge les clés des dispositifs. Refuse un fichier lisible par d'autres utilisateurs."""
    mode = stat.S_IMODE(os.stat(path).st_mode)
    if mode & 0o077:
        raise ValueError(f"fichier de clés trop ouvert ({oct(mode)}) : utiliser chmod 600")
    doc = json.loads(path.read_text(encoding="utf-8"))
    devices = doc.get("devices") if isinstance(doc, dict) else None
    if not isinstance(devices, dict):
        raise ValueError("fichier de clés : champ « devices » attendu")
    table: dict[bytes, DeviceKeys] = {}
    for dev_hex, entry in devices.items():
        dev_eui = _hex(dev_hex, 8, "DevEUI")
        if not isinstance(entry, dict):
            raise ValueError("entrée de dispositif non objet")
        nwk_key = _hex(entry.get("nwk_key"), 16, f"nwk_key {dev_hex}")
        app_key = None
        if entry.get("app_key") is not None:
            app_key = _hex(entry["app_key"], 16, f"app_key {dev_hex}")
        table[dev_eui] = DeviceKeys(nwk_key, app_key=app_key)
    return table


def open_store(db_path: Path) -> DurableJoinStore:
    integrity_hex = os.environ.get(INTEGRITY_ENV)
    if integrity_hex is None:
        raise ValueError(f"variable {INTEGRITY_ENV} absente")
    return DurableJoinStore(db_path, _hex(integrity_hex, 16, INTEGRITY_ENV))


def build_handler(store: DurableJoinStore, keys: dict[bytes, DeviceKeys], net_id: bytes
                  ) -> UplinkRouter:
    def provider(dev_eui: bytes) -> DeviceKeys:
        try:
            return keys[dev_eui]
        except KeyError:
            raise KeyError("dispositif inconnu") from None

    return UplinkRouter(JoinUplinkHandler(JoinServer(store, net_id, provider)),
                        DataUplinkHandler(store))


def enqueue_downlink(db_path: Path, dev_eui_hex: str, fport: int, payload_hex: str,
                     confirmed: bool) -> int:
    """Met un downlink en file pour un dispositif ; retourne la longueur de la file."""
    from lsim.eu868 import MAX_QUEUED_PAYLOAD

    dev_eui = _hex(dev_eui_hex, 8, "DevEUI")
    payload = bytes.fromhex(payload_hex) if payload_hex else b""
    if not 1 <= fport <= 223:
        raise ValueError("FPort applicatif : 1 à 223")
    if len(payload) > MAX_QUEUED_PAYLOAD:
        raise ValueError(f"charge limitée à {MAX_QUEUED_PAYLOAD} octets (DR0, plan EU868)")
    store = open_store(db_path)
    store.enqueue_downlink(dev_eui, fport, confirmed, payload)
    with store.transaction() as tx:
        return tx.queue_length(dev_eui)


def _log_delivery(delivery: Delivery) -> None:
    """Journal d'une livraison : sans contenu applicatif (seulement la taille)."""
    if delivery.payload is None:
        content = "non déchiffrée" if delivery.fport else "aucune"
    else:
        content = f"{len(delivery.payload)} octets"
    logging.getLogger("lsim.serve").info(
        "uplink dispositif %s : FCnt %d, FPort %s, %s, charge %s",
        delivery.dev_eui.hex(), delivery.fcnt,
        "-" if delivery.fport is None else delivery.fport,
        "confirmé" if delivery.confirmed else "non confirmé", content)


def run(host: str, port: int, db_path: Path, keys_path: Path, net_id_hex: str) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    # NetID écrit comme valeur (poids fort d'abord, ex. 000013) ; sur l'air, les champs
    # multi-octets sont en petit-boutiste (LoRaWAN 1.1 §4.3 : « little endian »).
    net_id = _hex(net_id_hex, 3, "NetID")[::-1]
    keys = load_keys_file(keys_path)
    handler = build_handler(open_store(db_path), keys, net_id)

    async def main() -> None:
        transport, protocol = await start_server(handler, host, port, on_delivery=_log_delivery)
        logging.getLogger("lsim.serve").info(
            "écoute UDP %s:%s, %d dispositif(s)", host, port, len(keys))
        try:
            await asyncio.Event().wait()
        finally:
            transport.close()
            await protocol.drain()
            logging.getLogger("lsim.serve").info("statistiques : %s", dict(protocol.stats))

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    return 0
