"""Passe mesh : relais des copies des passerelles vers la frontière, à partir de la trace.

Partagée par `run_scenario` (export) et par la trace API (`trace_events.build_multi_trace`) :
une seule implémentation, donc totaux et trace concordent par construction.

Entrée : les émissions de la trace multi (`decoded_mask` par passerelle, instants de fin) et la
liste des passerelles. Sortie : copies sur le mesh, issues par trame, journal des sauts (si
demandé) et fenêtres de descente d'acquittement.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Sequence

from lsim.gateway_profiles import get_profile
from lsim.mesh import (
    DOWNLINK_ACK_PHY_BYTES,
    MESH_ENVELOPE_DOWN_BYTES,
    MESH_ENVELOPE_UP_BYTES,
    MeshFrame,
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
class MeshPass:
    """Résultat de la passe mesh. Les ensembles sont des indices de trame (= indice de trace)."""

    seen_frames: int                  # trames décodées par au moins une passerelle
    direct_frames: frozenset          # remises sans saut mesh (passerelle à backhaul IP, ou frontière)
    via_mesh_frames: frozenset        # remises après au moins un saut mesh
    delivered_frames: frozenset       # remises au LNS (direct ∪ via mesh)
    copies_on_mesh: int               # copies confiées au mesh
    no_route: int                     # copies sans route vers la frontière
    mesh_result: MeshResult
    dl_counts: dict = field(default_factory=dict)   # fenêtres de l'acquittement : rx1/rx2/missed
    mesh_air_ns: int = 0              # temps d'antenne de l'acquittement mesh
    delivered_by_device: tuple = ()   # remises par dispositif (indexé comme `devices`)


def mesh_pass(scenario, devices, gw_models, trace: Sequence, with_hops: bool = False) -> MeshPass:
    """Relais mesh de la trace multi. `scenario.model.mesh` doit être renseigné."""
    mesh_cfg = scenario.model.mesh
    nodes, gw_index = [], {}
    for k, g in enumerate(gw_models):
        tx = get_profile(g.profile).tx_power_max_dbm if g.profile is not None else None
        if g.mesh and tx is None:
            raise ValueError(f"passerelle {g.name!r} : puissance d'émission mesh non publiée")
        nodes.append(MeshNode(gateway_id=g.name, x_m=g.x_m, y_m=g.y_m, mesh_capable=g.mesh,
                              tx_power_dbm=tx if tx is not None else 0.0,
                              antenna_gain_dbi=g.antenna_gain_dbi))
        gw_index[g.name] = k
    radio = MeshRadio(spreading_factor=mesh_cfg.spreading_factor,
                      bandwidth_khz=mesh_cfg.bandwidth_khz, coding_rate=mesh_cfg.coding_rate,
                      payload_bytes=mesh_cfg.payload_bytes, capture_db=mesh_cfg.capture_db)
    fixed_size = mesh_cfg.payload_bytes if mesh_cfg.frame_size == "fixed" else None
    # Le mesh vit à 2,4 GHz, même exposant que l'accès. Le shadowing mesh est un tirage par
    # paire de passerelles (`mesh.shadowing_sigma_db`), pas celui de l'accès. Avec environnement,
    # la perte entre passerelles (relief et obstacles, antennes à hauteur passerelle) est
    # calculée par le natif ; sans environnement, log-distance seul.
    mesh_prop = dataclasses.replace(scenario.propagation(), frequency_hz=2_400_000_000.0,
                                    shadowing_sigma_db=0.0)
    path_matrix = None
    if scenario.environment is not None:
        path_matrix = environment_path_loss_matrix(
            [(g.x_m, g.y_m) for g in gw_models], mesh_prop, scenario.environment)
    mesh_model = LogDistanceModel(frequency_hz=mesh_prop.frequency_hz,
                                  exponent=mesh_prop.exponent)
    graph = build_mesh(nodes, mesh_cfg.border, radio, path_loss=mesh_model,
                       max_hops=mesh_cfg.max_hops, path_loss_db=path_matrix,
                       shadowing_sigma_db=mesh_cfg.shadowing_sigma_db,
                       shadowing_seed=scenario.propagation().shadowing_seed)

    # Une copie par passerelle décodeuse. Passerelle sans mesh : backhaul IP, remise directe.
    # Relais : une émission par trame si la suppression est active (identifiant de trame),
    # après une attente déterministe de `relay_backoff_airtimes` temps d'antenne.
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
    backoff_ns = mesh_cfg.relay_backoff_airtimes * radio.airtime_ns
    mesh_result = forward_frames(frames, graph, radio,
                                 suppress_duplicates=mesh_cfg.suppress_duplicates,
                                 backoff_window_ns=backoff_ns, with_hops=with_hops)

    # « Direct » : remise sans saut mesh (passerelle à backhaul IP, ou frontière elle-même).
    delivered_frames: set[int] = set(direct_frame)
    via_mesh_frames: set[int] = set()
    no_route = 0
    for d in mesh_result.deliveries:
        if d.delivered:
            delivered_frames.add(d.frame_id)
            if d.hops == 0:
                direct_frame.add(d.frame_id)
            else:
                via_mesh_frames.add(d.frame_id)
        elif d.copy_state == "no_route":
            no_route += 1
    via_mesh_frames -= direct_frame
    # Descente : une réponse par trame remise. Le natif donne le même saut et la même
    # latence pour toutes les copies d'une trame ; une trame décodée par la frontière
    # elle-même a 0 saut.
    # Descente : acquittement seul sur le lien mesh (taille PHY 12 o + enveloppe 15 o).
    mesh_air = time_on_air_ns(mesh_cfg.spreading_factor, mesh_cfg.bandwidth_khz * 1000,
                              DOWNLINK_ACK_PHY_BYTES + MESH_ENVELOPE_DOWN_BYTES,
                              mesh_cfg.coding_rate)
    best_by_frame = {d.frame_id: d for d in mesh_result.deliveries if d.delivered}
    dl_counts = {"rx1": 0, "rx2": 0, "missed": 0}
    for frame_id in delivered_frames:
        if frame_id in direct_frame or frame_id not in best_by_frame:
            hops, latency = 0, 0
        else:
            hops, latency = best_by_frame[frame_id].hops, best_by_frame[frame_id].latency_ns or 0
        dl_counts[downlink_window(latency, hops, mesh_air)] += 1
    delivered_by_device = [0] * len(devices)
    for rec_index in delivered_frames:
        delivered_by_device[trace[rec_index].device_index] += 1

    return MeshPass(
        seen_frames=seen_frames,
        direct_frames=frozenset(direct_frame),
        via_mesh_frames=frozenset(via_mesh_frames),
        delivered_frames=frozenset(delivered_frames),
        copies_on_mesh=len(frames),
        no_route=no_route,
        mesh_result=mesh_result,
        dl_counts=dl_counts,
        mesh_air_ns=mesh_air,
        delivered_by_device=tuple(delivered_by_device),
    )
