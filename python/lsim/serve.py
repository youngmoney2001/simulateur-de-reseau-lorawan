"""Commande `lsim serve` : passerelles Semtech UDP → serveur de jointure.

Secrets :
- clé d'intégrité du registre : variable d'environnement LSIM_INTEGRITY_KEY (32 caractères hex) ;
- clé de données (chiffrement au repos des sessions et de la file, AES-256-GCM) :
  variable LSIM_DATA_KEY (64 caractères hex), distincte de la clé d'intégrité et hors de la base ;
- clés des dispositifs : fichier JSON
  `{"devices": {"<DevEUI hex, ordre d'affichage TTN>": {"nwk_key": "<32 hex>", "app_key": "<32 hex, optionnel>"}}}`,
  refusé si accessible au groupe ou aux autres (mode 0600 attendu).
  Sans app_key : les uplinks FPort 0 sont vérifiés, mais FPort > 0 n'est pas déchiffré ni livré.
Aucun secret n'est écrit dans les journaux ; les charges utiles ne sont pas journalisées.

Couche données : plan régional choisi au démarrage (`--region` : EU868 ou US915, voir `lsim.plan`).
La passerelle doit utiliser le même plan. `lsim downlink` met un downlink en file ; il est émis au
prochain uplink du dispositif (classe A).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import stat
from pathlib import Path
from typing import Optional

from lsim.basicstation import DEFAULT_HWSPEC, BasicStationServer, make_ssl_context, start_basicstation_server
from lsim.gwmp_server import JoinUplinkHandler, start_server
from lsim.join_server import DeviceKeys, JoinServer
from lsim.join_store import DurableJoinStore
from lsim.plan import Plan, get_plan
from lsim.uplink import DataUplinkHandler, Delivery, UplinkRouter

INTEGRITY_ENV = "LSIM_INTEGRITY_KEY"
DATA_ENV = "LSIM_DATA_KEY"
DEFAULT_REGION = "EU868"
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
        dev_eui = _hex(dev_hex, 8, "DevEUI")[::-1]     # ordre d'affichage TTN -> transmission
        if not isinstance(entry, dict):
            raise ValueError("entrée de dispositif non objet")
        nwk_key = _hex(entry.get("nwk_key"), 16, f"nwk_key {dev_hex}")
        app_key = None
        if entry.get("app_key") is not None:
            app_key = _hex(entry["app_key"], 16, f"app_key {dev_hex}")
        table[dev_eui] = DeviceKeys(nwk_key, app_key=app_key)
    return table


def open_store(db_path: Path) -> DurableJoinStore:
    """Ouvre le registre avec les deux clés d'environnement : intégrité et données (chiffrement)."""
    integrity_hex = os.environ.get(INTEGRITY_ENV)
    if integrity_hex is None:
        raise ValueError(f"variable {INTEGRITY_ENV} absente")
    data_hex = os.environ.get(DATA_ENV)
    if data_hex is None:
        raise ValueError(f"variable {DATA_ENV} absente (32 octets hex, chiffrement des sessions)")
    return DurableJoinStore(db_path, _hex(integrity_hex, 16, INTEGRITY_ENV),
                            data_key=_hex(data_hex, 32, DATA_ENV))


def build_handler(store: DurableJoinStore, keys: dict[bytes, DeviceKeys], net_id: bytes,
                  plan: Plan) -> UplinkRouter:
    def provider(dev_eui: bytes) -> DeviceKeys:
        try:
            return keys[dev_eui]
        except KeyError:
            raise KeyError("dispositif inconnu") from None

    join_server = JoinServer(store, net_id, provider, dl_settings=plan.dl_settings)
    return UplinkRouter(JoinUplinkHandler(join_server, plan), DataUplinkHandler(store, plan))


def enqueue_downlink(db_path: Path, dev_eui_hex: str, fport: int, payload_hex: str,
                     confirmed: bool, region: str = DEFAULT_REGION) -> int:
    """Met un downlink en file pour un dispositif ; retourne la longueur de la file."""
    plan = get_plan(region)
    dev_eui = _hex(dev_eui_hex, 8, "DevEUI")[::-1]     # ordre d'affichage TTN -> transmission
    try:
        payload = bytes.fromhex(payload_hex) if payload_hex else b""
    except ValueError as exc:
        raise ValueError("charge utile : hexadécimal invalide") from exc
    store = open_store(db_path)
    store.enqueue_downlink(dev_eui, fport, confirmed, payload, plan)
    with store.transaction() as tx:
        return tx.queue_length(dev_eui)


_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


def run_basicstation(host: str, port: int, db_path: Path, keys_path: Path, net_id_hex: str,
                     region: str, uri: str, tls_cert: Optional[str] = None,
                     tls_key: Optional[str] = None, hwspec: str = DEFAULT_HWSPEC) -> int:
    """Passerelles Basic Station (WebSocket). `uri` : adresse publique annoncée aux passerelles."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    log = logging.getLogger("lsim.serve")
    if not uri.startswith(("ws://", "wss://")):
        raise ValueError("--uri : schéma ws:// ou wss:// attendu")
    if not re.fullmatch(r"sx1301/[1-8]", hwspec):
        raise ValueError("--hwspec : « sx1301/N » attendu (N = 1 à 8), voir docs/USAGE.md")
    if (tls_cert is None) != (tls_key is None):
        raise ValueError("--tls-cert et --tls-key vont ensemble")
    if tls_cert is None and host not in _LOOPBACK_HOSTS:
        log.warning("WebSocket en clair sur %s : utiliser --tls-cert/--tls-key ou un proxy TLS", host)
    net_id = _hex(net_id_hex, 3, "NetID")
    keys = load_keys_file(keys_path)
    plan = get_plan(region)
    handler = build_handler(open_store(db_path), keys, net_id[::-1], plan)
    ssl_context = make_ssl_context(tls_cert, tls_key) if tls_cert else None
    server = BasicStationServer(handler, plan, net_id=int.from_bytes(net_id, "big"), uri=uri,
                                hwspec=hwspec, on_delivery=_log_delivery)

    async def main() -> None:
        listener = await start_basicstation_server(server, host, port, ssl_context)
        log.info("Basic Station : écoute %s:%s (%s), plan %s, %d dispositif(s)",
                 host, port, "TLS" if ssl_context else "clair", plan.name, len(keys))
        try:
            async with listener:
                await listener.serve_forever()
        finally:
            log.info("statistiques : %s", dict(server.stats))

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    return 0


def _log_delivery(delivery: Delivery) -> None:
    """Journal d'une livraison : sans contenu applicatif (seulement la taille)."""
    if delivery.payload is None:
        content = "non déchiffrée" if delivery.fport else "aucune"
    else:
        content = f"{len(delivery.payload)} octets"
    logging.getLogger("lsim.serve").info(
        "uplink dispositif %s : FCnt %d, FPort %s, %s, charge %s",
        delivery.dev_eui[::-1].hex(), delivery.fcnt,
        "-" if delivery.fport is None else delivery.fport,
        "confirmé" if delivery.confirmed else "non confirmé", content)


def run(host: str, port: int, db_path: Path, keys_path: Path, net_id_hex: str,
        region: str = DEFAULT_REGION) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    # NetID écrit comme valeur (poids fort d'abord, ex. 000013) ; sur l'air, les champs
    # multi-octets sont en petit-boutiste (LoRaWAN 1.1 §4.3 : « little endian »).
    net_id = _hex(net_id_hex, 3, "NetID")[::-1]
    keys = load_keys_file(keys_path)
    plan = get_plan(region)
    handler = build_handler(open_store(db_path), keys, net_id, plan)
    logging.getLogger("lsim.serve").info("plan régional : %s", plan.name)

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
