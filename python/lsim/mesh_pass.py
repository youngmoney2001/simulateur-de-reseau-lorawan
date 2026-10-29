"""Passe mesh : relais des copies des passerelles vers la frontière, à partir de la trace.

Partagée par `run_scenario` (export) et par la trace API (`trace_events.build_multi_trace`) :
une seule implémentation, donc totaux et trace concordent par construction.

Entrée : les émissions de la trace multi (`decoded_mask` par passerelle, instants de fin) et la
liste des passerelles. Sortie : copies sur le mesh, issues par trame, journal des sauts (si
demandé) et fenêtres de descente d'acquittement.

Descentes (`downlinks`) : elles partagent la même passe que les uplinks, donc le même temps
d'antenne et la même suppression des doublons. Chaque descente part de la frontière vers son
relais cible (destination par trame). Ses identifiants de trame sont `len(trace) + clé`.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Optional, Sequence

from lsim.gateway_profiles import get_profile
from lsim.mesh import (
    DOWNLINK_ACK_PHY_BYTES,
    MESH_ENVELOPE_DOWN_BYTES,
    MESH_ENVELOPE_UP_BYTES,
    MeshFrame,
    MeshHop,
    MeshNode,
    MeshRadio,
    MeshResult,
    build_mesh,
    downlink_window,
    forward_frames,
    lorawan_phy_bytes,
    time_on_air_ns,
)
from lsim.radio import LogDistanceModel
from lsim.simulator import environment_path_loss_matrix


@dataclass(frozen=True)
class MeshDownlinkRoute:
    """Acheminement d'une descente de la frontière vers un relais cible.

    `arrival_ns` : instant de réception par le relais (None si perdue sur le mesh).
    `loss` : "" si remise ; sinon no_route, collision ou half_duplex (issue du dernier saut
    perdu). `hops` : sauts du journal natif de cette descente (sens descendant).
    """

    delivered: bool
    arrival_ns: Optional[int]
    loss: str
    hops: tuple = ()


@dataclass(frozen=True)
class MeshPass:
    """Résultat de la passe mesh. Les ensembles sont des indices de trame (= indice de trace).

    Vues montantes (uplinks) : `delivered_frames`, `direct_frames`, `via_mesh_frames`,
    `border_delay_ns`, `uplink_hops`, `delivered_by_device`. `mesh_result` contient la passe
    complète (montant et descente) : c'est elle qui porte le temps d'antenne et la charge.
    `downlinks` : route de chaque descente demandée, par clé.
    """

    delivered_frames: frozenset       # uplinks remis au LNS (direct ∪ via mesh)
    direct_frames: frozenset          # uplinks remis sans saut mesh
    via_mesh_frames: frozenset        # uplinks remis après au moins un saut mesh
    border_delay_ns: dict             # uplink remis -> délai de la copie utile jusqu'à la frontière
    copies_on_mesh: int               # copies montantes confiées au mesh
    no_route: int                     # copies montantes sans route vers la frontière
    mesh_result: MeshResult           # passe complète : montant + descente
    uplink_hops: tuple                # sauts du montant (MeshHop)
    downlinks: dict = field(default_factory=dict)   # clé -> MeshDownlinkRoute
    seen_frames: int = 0              # trames décodées par au moins une passerelle
    dl_counts: dict = field(default_factory=dict)   # fenêtres de l'acquittement : rx1/rx2/missed
    mesh_air_ns: int = 0              # temps d'antenne de l'acquittement mesh
    delivered_by_device: tuple = ()   # uplinks remis par dispositif (indexé comme `devices`)


def _mesh_radio(mesh_cfg):
    return MeshRadio(spreading_factor=mesh_cfg.spreading_factor,
                     bandwidth_khz=mesh_cfg.bandwidth_khz, coding_rate=mesh_cfg.coding_rate,
                     payload_bytes=mesh_cfg.payload_bytes, capture_db=mesh_cfg.capture_db)


def mesh_graph(scenario, gw_models, border_id: Optional[str] = None):
    """Graphe mesh : liens, puissances et routes vers la frontière (`border_id`, par défaut celle du
    scénario). Les routes vers les autres relais sont calculées à partir du même graphe."""
    mesh_cfg = scenario.model.mesh
    nodes = []
    for g in gw_models:
        tx = get_profile(g.profile).tx_power_max_dbm if g.profile is not None else None
        if g.mesh and tx is None:
            raise ValueError(f"passerelle {g.name!r} : puissance d'émission mesh non publiée")
        nodes.append(MeshNode(gateway_id=g.name, x_m=g.x_m, y_m=g.y_m, mesh_capable=g.mesh,
                              tx_power_dbm=tx if tx is not None else 0.0,
                              antenna_gain_dbi=g.antenna_gain_dbi))
    radio = _mesh_radio(mesh_cfg)
    mesh_prop = dataclasses.replace(scenario.propagation(), frequency_hz=2_400_000_000.0,
                                    shadowing_sigma_db=0.0)
    path_matrix = None
    if scenario.environment is not None:
        path_matrix = environment_path_loss_matrix(
            [(g.x_m, g.y_m) for g in gw_models], mesh_prop, scenario.environment)
    mesh_model = LogDistanceModel(frequency_hz=mesh_prop.frequency_hz,
                                  exponent=mesh_prop.exponent)
    return build_mesh(nodes, border_id or mesh_cfg.border, radio, path_loss=mesh_model,
                      max_hops=mesh_cfg.max_hops, path_loss_db=path_matrix,
                      shadowing_sigma_db=mesh_cfg.shadowing_sigma_db,
                      shadowing_seed=scenario.propagation().shadowing_seed)


def mesh_pass(scenario, devices, gw_models, trace: Sequence, with_hops: bool = False,
              downlinks: Sequence[tuple] = ()) -> MeshPass:
    """Relais mesh de la trace multi, montant et descentes dans la même passe.

    `downlinks` : (clé, relais cible, instant de départ à la frontière (ns), taille PHY en octets).
    Les clés doivent être des entiers distincts >= 0.
    """
    mesh_cfg = scenario.model.mesh
    fixed_size = mesh_cfg.payload_bytes if mesh_cfg.frame_size == "fixed" else None
    graph = mesh_graph(scenario, gw_models)
    base = len(trace)

    # Une copie par passerelle décodeuse. Passerelle sans mesh : backhaul IP, remise directe.
    # Relais : une émission par trame, la suppression et l'attente sont celles du mesh.
    frames: list[MeshFrame] = []
    direct_frame: set[int] = set()
    seen_frames = 0
    for rec_index, rec in enumerate(trace):
        if rec.decoded_mask == 0:
            continue
        seen_frames += 1
        for g, model in enumerate(gw_models):
            if not (rec.decoded_mask >> g) & 1:
                continue
            if model.mesh and model.name != mesh_cfg.border:
                # Un relais confie sa copie au mesh ; la frontière, elle, la remet directement.
                size = fixed_size if fixed_size is not None else (
                    lorawan_phy_bytes(devices[rec.device_index].payload_bytes)
                    + MESH_ENVELOPE_UP_BYTES)
                frames.append(MeshFrame(frame_id=rec_index, rx_gateway_id=model.name,
                                        t_ns=rec.end_ns, payload_bytes=size))
            else:
                direct_frame.add(rec_index)
    # Descentes : de la frontière vers le relais cible (15 o d'enveloppe, PHY fourni).
    for key, target, t_ns, phy_bytes in downlinks:
        if key < 0 or key >= 1 << 48:
            raise ValueError("clé de descente hors domaine")
        frames.append(MeshFrame(frame_id=base + key, rx_gateway_id=mesh_cfg.border, t_ns=t_ns,
                                payload_bytes=phy_bytes + MESH_ENVELOPE_DOWN_BYTES,
                                dest_id=target))
    radio = _mesh_radio(mesh_cfg)
    mesh_result = forward_frames(frames, graph, radio,
                                 suppress_duplicates=mesh_cfg.suppress_duplicates,
                                 backoff_window_ns=mesh_cfg.relay_backoff_airtimes * radio.airtime_ns,
                                 with_hops=with_hops)

    # Vue montante. « Direct » : remise sans saut mesh (passerelle à backhaul IP, ou frontière).
    up_deliveries = [d for d in mesh_result.deliveries if d.frame_id < base]
    delivered_frames: set[int] = set(direct_frame)
    via_mesh_frames: set[int] = set()
    no_route = 0
    for d in up_deliveries:
        if d.delivered:
            delivered_frames.add(d.frame_id)
            if d.hops == 0:
                direct_frame.add(d.frame_id)
            else:
                via_mesh_frames.add(d.frame_id)
        elif d.copy_state == "no_route":
            no_route += 1
    via_mesh_frames -= direct_frame
    best_by_frame = {d.frame_id: d for d in up_deliveries if d.delivered}
    border_delay = {}
    for frame_id in delivered_frames:
        if frame_id in direct_frame or frame_id not in best_by_frame:
            border_delay[frame_id] = 0
        else:
            border_delay[frame_id] = best_by_frame[frame_id].latency_ns or 0

    # Acquittement (fenêtres) : taille PHY 12 o + enveloppe mesh, comme avant.
    mesh_air = time_on_air_ns(mesh_cfg.spreading_factor, mesh_cfg.bandwidth_khz * 1000,
                              DOWNLINK_ACK_PHY_BYTES + MESH_ENVELOPE_DOWN_BYTES,
                              mesh_cfg.coding_rate)
    dl_counts = {"rx1": 0, "rx2": 0, "missed": 0}
    for frame_id in delivered_frames:
        if frame_id in direct_frame or frame_id not in best_by_frame:
            latency, hops = 0, 0
        else:
            latency, hops = best_by_frame[frame_id].latency_ns or 0, best_by_frame[frame_id].hops
        dl_counts[downlink_window(latency, hops, mesh_air)] += 1
    delivered_by_device = [0] * len(devices)
    for rec_index in delivered_frames:
        delivered_by_device[trace[rec_index].device_index] += 1

    # Descentes : route de chaque descente demandée.
    hops_by_frame: dict[int, list[MeshHop]] = {}
    for h in mesh_result.hops:
        hops_by_frame.setdefault(h.frame_id, []).append(h)
    best_dl = {}
    lost_dl = {}
    for d in mesh_result.deliveries:
        if d.frame_id < base:
            continue
        if d.delivered:
            cur = best_dl.get(d.frame_id)
            if cur is None or (d.latency_ns or 0) < (cur.latency_ns or 0):
                best_dl[d.frame_id] = d
        else:
            lost_dl[d.frame_id] = d.loss or "no_route"
    routes = {}
    for key, _target, t_ns, _phy in downlinks:
        fid = base + key
        hops = tuple(hops_by_frame.get(fid, ()))
        dv = best_dl.get(fid)
        if dv is None:
            routes[key] = MeshDownlinkRoute(False, None, lost_dl.get(fid, "no_route"), hops)
        else:
            routes[key] = MeshDownlinkRoute(True, t_ns + (dv.latency_ns or 0), "", hops)

    return MeshPass(
        delivered_frames=frozenset(delivered_frames),
        direct_frames=frozenset(direct_frame),
        via_mesh_frames=frozenset(via_mesh_frames),
        border_delay_ns=border_delay,
        copies_on_mesh=len(frames) - len(downlinks),
        no_route=no_route,
        mesh_result=mesh_result,
        uplink_hops=tuple(h for h in mesh_result.hops if h.frame_id < base),
        downlinks=routes,
        seen_frames=seen_frames,
        dl_counts=dl_counts,
        mesh_air_ns=mesh_air,
        delivered_by_device=tuple(delivered_by_device),
    )
