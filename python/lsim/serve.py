"""Commande `lsim serve` : passerelles Semtech UDP → serveur de jointure.

Secrets :
- clé d'intégrité du registre : variable d'environnement LSIM_INTEGRITY_KEY (32 caractères hex) ;
- clés des dispositifs : fichier JSON `{"devices": {"<DevEUI hex>": {"nwk_key": "<32 hex>"}}}`,
  refusé si accessible au groupe ou aux autres (mode 0600 attendu).
Aucun secret n'est écrit dans les journaux.
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
        table[dev_eui] = DeviceKeys(_hex(entry.get("nwk_key"), 16, f"nwk_key {dev_hex}"))
    return table


def build_handler(db_path: Path, keys: dict[bytes, DeviceKeys], net_id: bytes) -> JoinUplinkHandler:
    integrity_hex = os.environ.get(INTEGRITY_ENV)
    if integrity_hex is None:
        raise ValueError(f"variable {INTEGRITY_ENV} absente")
    integrity = _hex(integrity_hex, 16, INTEGRITY_ENV)
    store = DurableJoinStore(db_path, integrity)

    def provider(dev_eui: bytes) -> DeviceKeys:
        try:
            return keys[dev_eui]
        except KeyError:
            raise KeyError("dispositif inconnu") from None

    return JoinUplinkHandler(JoinServer(store, net_id, provider))


def run(host: str, port: int, db_path: Path, keys_path: Path, net_id_hex: str) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    # NetID écrit comme valeur (poids fort d'abord, ex. 000013) ; sur l'air, les champs
    # multi-octets sont en petit-boutiste (LoRaWAN 1.1 §4.3 : « little endian »).
    net_id = _hex(net_id_hex, 3, "NetID")[::-1]
    keys = load_keys_file(keys_path)
    handler = build_handler(db_path, keys, net_id)

    async def main() -> None:
        transport, protocol = await start_server(handler, host, port)
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
