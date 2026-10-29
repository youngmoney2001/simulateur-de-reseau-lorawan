"""Compilation d'une session du panneau d'étude en scénario de simulation (`docs/STUDY_PANEL_SPEC.md` §7).

Entrées : les équipements de la session (topologie) et la configuration CLI de chaque passerelle.
Sortie : le corps d'un `POST /api/v1/runs` (un scénario validé ensuite par le moteur), les liaisons
à appliquer au résultat, et des notes (défauts appliqués, réglages non modélisés).

Règles :
- une passerelle est un `border` (backhaul IP) ou un `relay` (mesh sans IP) ; chaque capteur est un
  groupe de simulation nommé comme lui, avec ses réglages `sensor` ;
- une passerelle dont l'interface `lora` est arrêtée n'entre pas dans le run ; un relais dont
  l'interface `mesh` est arrêtée reste une passerelle d'accès ordinaire ;
- avec des relais actifs, il faut exactement une frontière active, dont l'interface mesh est
  active ; les réglages mesh (SF, bande, sauts) sont ceux de la frontière et des relais ; deux
  valeurs réglées et différentes sont refusées, les sauts prennent la plus petite valeur réglée ;
- le plan régional et la sous-bande sont ceux des passerelles (identiques pour toutes) ; un capteur
  qui en déclare un autre est refusé ; un plan non réglé vaut EU868 (et une sous-bande non réglée
  vaut 1 sur US915 / AU915), avec une note ;
- un réglage du type `mode` qui ne correspond pas au rôle est refusé.

Le compilateur est pur : il ne lit ni n'écrit d'état, et les validations du moteur (scénario,
charge descendante sur le mesh) restent à la création du run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from lsim.channel_mask import sub_band_channels
from lsim.gateway_profiles import get_profile, software_status
from lsim.plan import get_plan
from lsim.study_cli import SUB_BAND_REGIONS, GatewayConfig
from lsim.study_contract import Node, SensorSettings

DEFAULT_REGION = "EU868"
DEFAULT_SUB_BAND = 1
MESH_PROFILE = "rak5146-rak5148"  # relais : accès sous-GHz + lien mesh 2,4 GHz (gateway_profiles)
MESH_DEFAULTS = {"spreading_factor": 9, "bandwidth_khz": 203, "max_hops": 8}   # défauts de MeshModel
NOT_MODELLED = ("puissance d'émission des passerelles d'accès", "sensibilité des récepteurs : décalage uniforme "
                "par profil en réception montante (decalage-uniforme-v1, non calibré), descente et mesh inchangés",
                "fréquence réglée sur les passerelles",
                "interface Ethernet", "serveur réseau (le LNS est implicite derrière la frontière)")


class CompileError(Exception):
    def __init__(self, message: str, field_name: str = "nodes") -> None:
        super().__init__(message)
        self.message, self.field = message, field_name


@dataclass(frozen=True)
class Compiled:
    body: dict                      # corps de POST /api/v1/runs
    links: list                    # [{"node_id": ..., "gateway": ...}] : une par passerelle du run
    notes: list[str] = field(default_factory=list)


def _default_channel(region: str, sub_band: Optional[int]) -> int:
    channels = get_plan(region).uplink_channels_hz()
    if sub_band is None:
        return channels[0]
    return channels[min(sub_band_channels(sub_band))]


def compile_session(nodes: list[Node], configs: dict[str, GatewayConfig], seed: int) -> Compiled:
    notes: list[str] = []
    gateways = [n for n in nodes if n.kind in ("relay", "border")]
    sensors = [n for n in nodes if n.kind == "sensor"]
    if not gateways:
        raise CompileError("aucune passerelle dans la session : ajoutez une frontière (border)")
    if not sensors:
        raise CompileError("aucun capteur dans la session : ajoutez au moins un capteur")

    for n in gateways:
        mode = configs[n.id].mesh.mode
        if mode is not None and mode != n.kind:
            raise CompileError(f"{n.id} : mode mesh « {mode} » ne correspond pas au rôle {n.kind}")

    borders = [n for n in gateways if n.kind == "border"]
    relays = [n for n in gateways if n.kind == "relay"]
    active = [n for n in gateways if not configs[n.id].lora.shutdown]
    mesh_relays = [n for n in relays if n in active and not configs[n.id].mesh.shutdown]
    mesh_nodes: list[Node] = []
    border: Optional[Node] = None
    if mesh_relays:
        if len(borders) != 1:
            raise CompileError("un réseau mesh exige exactement une frontière (border)")
        border = borders[0]
        if border not in active:
            raise CompileError(f"{border.id} : frontière arrêtée (interface lora) alors que des relais "
                               "sont actifs")
        if configs[border.id].mesh.shutdown:
            raise CompileError(f"{border.id} : interface mesh arrêtée alors que des relais sont actifs")
        mesh_nodes = [border] + mesh_relays
    if not active:
        raise CompileError("toutes les passerelles sont arrêtées")

    # Plan régional et sous-bande : identiques pour toutes les passerelles d'accès.
    regions: dict[str, str] = {}
    for n in active:
        region = configs[n.id].lora.region
        if region is None:
            region = DEFAULT_REGION
            notes.append(f"{n.id} : plan non réglé, {DEFAULT_REGION} appliqué")
        regions[n.id] = region
    if len(set(regions.values())) > 1:
        detail = ", ".join(f"{k} {v}" for k, v in regions.items())
        raise CompileError(f"plans régionaux différents sur les passerelles ({detail})")
    region = next(iter(regions.values()))

    sub_band: Optional[int] = None
    if region in SUB_BAND_REGIONS:
        bands = {configs[n.id].lora.sub_band for n in active}
        if len(bands) > 1:
            raise CompileError("sous-bandes différentes sur les passerelles")
        sub_band = next(iter(bands))
        if sub_band is None:
            sub_band = DEFAULT_SUB_BAND
            notes.append(f"sous-bande non réglée, {DEFAULT_SUB_BAND} appliquée")

    scenario_gateways = []
    for n in active:
        cfg = configs[n.id]
        gw = {"name": n.id, "x_m": n.x_m, "y_m": n.y_m,
              "antenna_gain_dbi": cfg.lora.antenna_gain_dbi or 0.0}
        if n in mesh_nodes:
            gw["profile"] = MESH_PROFILE
            gw["mesh"] = True
        scenario_gateways.append(gw)

    mesh_block = None
    if mesh_nodes:
        values = {key: {} for key in MESH_DEFAULTS}
        for n in mesh_nodes:
            m = configs[n.id].mesh
            if m.spreading_factor is not None:
                values["spreading_factor"][n.id] = m.spreading_factor
            if m.bandwidth_khz is not None:
                values["bandwidth_khz"][n.id] = int(m.bandwidth_khz)
            if m.max_hops is not None:
                values["max_hops"][n.id] = m.max_hops
        for key, label in (("spreading_factor", "SF mesh"), ("bandwidth_khz", "bande mesh")):
            distinct = set(values[key].values())
            if len(distinct) > 1:
                raise CompileError(f"{label} différent entre la frontière et les relais")
        mesh_block = {
            "border": border.id,
            "spreading_factor": next(iter(values["spreading_factor"].values()),
                                     MESH_DEFAULTS["spreading_factor"]),
            "bandwidth_khz": next(iter(values["bandwidth_khz"].values()),
                                  MESH_DEFAULTS["bandwidth_khz"]),
            "max_hops": min(values["max_hops"].values(), default=MESH_DEFAULTS["max_hops"]),
        }

    groups = []
    for s in sensors:
        r = s.sensor or SensorSettings()
        if r.region is not None and r.region != region:
            raise CompileError(f"{s.id} : plan {r.region} ≠ plan des passerelles ({region})")
        channel = r.channel_freq_hz or _default_channel(region, sub_band)
        group = {
            "name": s.id,
            "placement": {"type": "explicit", "positions": [[s.x_m, s.y_m]]},
            "spreading_factor": r.spreading_factor,
            "payload_bytes": r.payload_bytes,
            "tx_power_dbm": r.tx_power_dbm,
            "period_s": r.period_s,
            "messages": r.messages,
            "start_spread_s": r.start_spread_s,
            "region": region,
            "channel_freq_hz": channel,
        }
        if sub_band is not None:
            group["sub_band"] = sub_band
        groups.append(group)

    scenario: dict = {
        "schema_version": 1,
        "name": "Session d'étude",
        "seed": seed,
        "gateways": scenario_gateways,
        "groups": groups,
    }
    if mesh_block is not None:
        scenario["mesh"] = mesh_block
    if mesh_nodes:
        prof = get_profile(MESH_PROFILE)
        if not prof.software_validated:
            notes.append(f"relais : profil {MESH_PROFILE} ({software_status(prof)}) : compatibilité "
                         "logicielle non confirmée (essai ChirpStack Gateway OS ou confirmation RAK)")
    notes.append("non modélisés (ignorés) : " + ", ".join(NOT_MODELLED))
    links = [{"node_id": n.id, "gateway": n.id} for n in active]
    return Compiled(body={"scenario": scenario, "protocol": {}}, links=links, notes=notes)

