"""Exécution d'un scénario et export des résultats (Parquet, métadonnées de traçabilité).

Les compteurs sont produits par le cœur natif ; ce module ne fait que les
assembler, calculer le taux de livraison (PDR) et les écrire.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

from lsim import __version__
from lsim.energy_report import device_energies
from lsim.native_info import native_version
from lsim.scenario import SCHEMA_VERSION, Scenario
from lsim.gateway_profiles import get_profile
from lsim.mesh import MeshFrame, MeshNode, MeshRadio, build_mesh, forward_frames
from lsim.radio import LogDistanceModel
from lsim.simulator import Counters, GatewayLoad, simulate_uplinks, simulate_uplinks_multi


@dataclass(frozen=True)
class DeviceRow:
    device_index: int
    group: str
    index_in_group: int
    x_m: float
    y_m: float
    spreading_factor: int
    sent: int
    received: int
    lost_sensitivity: int
    lost_collision: int
    airtime_ns: int
    # Énergie (profil choisi à run_scenario) : None si non demandée ou non calculable.
    energy_per_message_j: Optional[float] = None
    average_current_ua: Optional[float] = None

    @property
    def pdr(self) -> Optional[float]:
        return self.received / self.sent if self.sent else None


@dataclass(frozen=True)
class MeshSummary:
    """Bilan du relais mesh. Une trame est « remise » si au moins une copie atteint le LNS."""

    frames: int          # trames décodées par au moins une passerelle à l'accès
    delivered: int       # trames remises au LNS
    direct: int          # remises sans relais (passerelle à backhaul IP, ou frontière)
    via_mesh: int        # remises après au moins un saut mesh
    copies_on_mesh: int  # copies confiées au mesh (une par relais qui a décodé)
    losses: tuple[tuple[str, int], ...]  # raisons des copies perdues sur le mesh, triées

    @property
    def lost(self) -> int:
        return self.frames - self.delivered


@dataclass(frozen=True)
class RunResult:
    scenario_name: str
    scenario_sha256: str
    seed: int
    rows: tuple[DeviceRow, ...]
    totals: Counters
    gateway: Optional[GatewayLoad]   # None en multi-passerelles (charge par passerelle : à venir)
    energy_profile: Optional[str] = None  # nom CLI du profil énergie, ou None
    mesh: Optional[MeshSummary] = None    # présent si un backhaul mesh est déclaré

    @property
    def pdr(self) -> Optional[float]:
        return self.totals.received / self.totals.sent if self.totals.sent else None


def run_scenario(scenario: Scenario, energy_profile: Optional[str] = None) -> RunResult:
    """Déploie le scénario et lance la simulation native.

    `energy_profile` : « rak4631 » ou « sx1262-stm32l072 » ; ajoute l'énergie par message et
    le courant moyen à chaque dispositif. None : pas de calcul énergie.
    """
    devices, groups, indices = scenario.deploy()
    energies = (device_energies(devices, energy_profile)
                if energy_profile is not None else None)
    if scenario.is_multi_gateway:
        return _run_multi(scenario, devices, groups, indices, energies, energy_profile)
    result = simulate_uplinks(devices, scenario.gateway(), scenario.propagation(),
                              scenario.environment)
    rows = _rows(devices, groups, indices, energies, result.per_device, None)
    return RunResult(
        scenario_name=scenario.name,
        scenario_sha256=scenario.sha256,
        seed=scenario.model.seed,
        rows=rows,
        totals=result.totals,
        gateway=result.gateway,
        energy_profile=energy_profile,
    )


def _rows(devices, groups, indices, energies, per_device, delivered_by_device) -> tuple[DeviceRow, ...]:
    """Lignes par dispositif ; `delivered_by_device` remplace `received` s'il est fourni."""
    return tuple(
        DeviceRow(
            device_index=i,
            group=groups[i],
            index_in_group=indices[i],
            x_m=dev.x_m,
            y_m=dev.y_m,
            spreading_factor=dev.spreading_factor,
            sent=c.sent,
            received=(delivered_by_device[i] if delivered_by_device is not None else c.received),
            lost_sensitivity=c.lost_sensitivity,
            lost_collision=c.lost_collision,
            airtime_ns=c.airtime_ns,
            energy_per_message_j=energies[i].energy_per_message_j if energies else None,
            average_current_ua=energies[i].average_current_ua if energies else None,
        )
        for i, (dev, c) in enumerate(zip(devices, per_device))
    )


def _run_multi(scenario: Scenario, devices, groups, indices, energies,
               energy_profile: Optional[str]) -> RunResult:
    """Plusieurs passerelles, éventuellement avec relais mesh vers la frontière.

    Sans mesh : le serveur déduplique les copies reçues à l'accès (comportement
    de `simulate_uplinks_multi`). Avec mesh : une passerelle relais n'a pas de backhaul IP ;
    chacune de ses copies suit le mesh jusqu'à la frontière. Une trame est remise au LNS
    si au moins une copie y arrive.
    """
    gw_models = scenario.gateway_models()
    mesh_cfg = scenario.model.mesh
    result = simulate_uplinks_multi(devices, scenario.gateways(), scenario.propagation(),
                                    scenario.environment, with_trace=mesh_cfg is not None)
    if mesh_cfg is None:
        totals = Counters(result.network.sent, result.network.received,
                          result.network.lost_sensitivity, result.network.lost_collision,
                          result.network.airtime_ns, result.network.lost_gateway_busy)
        rows = _rows(devices, groups, indices, energies, result.per_device, None)
        return RunResult(scenario_name=scenario.name, scenario_sha256=scenario.sha256,
                         seed=scenario.model.seed, rows=rows, totals=totals, gateway=None,
                         energy_profile=energy_profile)

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
    # Le mesh vit à 2,4 GHz avec le même exposant que l'accès ; obstacles et relief ignorés.
    mesh_model = LogDistanceModel(frequency_hz=2_400_000_000.0,
                                  exponent=scenario.propagation().exponent)
    graph = build_mesh(nodes, mesh_cfg.border, radio, path_loss=mesh_model,
                       max_hops=mesh_cfg.max_hops)

    # Une copie par passerelle décodeuse. Passerelle sans mesh : backhaul IP, remise directe.
    trace = result.trace
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
                frames.append(MeshFrame(frame_id=rec_index, rx_gateway_id=model.name,
                                        t_ns=rec.end_ns))
            else:
                direct_frame.add(rec_index)
    mesh_result = forward_frames(frames, graph, radio)

    # « Direct » : remise sans saut mesh (passerelle à backhaul IP, ou frontière elle-même).
    delivered_frames: set[int] = set(direct_frame)
    via_mesh_frames: set[int] = set()
    losses: dict[str, int] = {}
    for d in mesh_result.deliveries:
        if d.delivered:
            delivered_frames.add(d.frame_id)
            if d.hops == 0:
                direct_frame.add(d.frame_id)
            else:
                via_mesh_frames.add(d.frame_id)
        else:
            losses[d.loss] = losses.get(d.loss, 0) + 1
    via_mesh_frames -= direct_frame
    delivered_by_device = [0] * len(devices)
    for rec_index in delivered_frames:
        delivered_by_device[trace[rec_index].device_index] += 1

    totals = Counters(result.network.sent, len(delivered_frames),
                      result.network.lost_sensitivity, result.network.lost_collision,
                      result.network.airtime_ns, result.network.lost_gateway_busy)
    summary = MeshSummary(
        frames=seen_frames,
        delivered=len(delivered_frames),
        direct=len(direct_frame),
        via_mesh=len(via_mesh_frames),
        copies_on_mesh=len(frames),
        losses=tuple(sorted(losses.items())),
    )
    rows = _rows(devices, groups, indices, energies, result.per_device, delivered_by_device)
    return RunResult(scenario_name=scenario.name, scenario_sha256=scenario.sha256,
                     seed=scenario.model.seed, rows=rows, totals=totals, gateway=None,
                     energy_profile=energy_profile, mesh=summary)


def write_parquet(run: RunResult, path: Union[str, Path]) -> None:
    """Écrit une ligne par dispositif. Les métadonnées portent le hash du scénario."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    rows = run.rows
    table = pa.table({
        "device_index": pa.array([r.device_index for r in rows], pa.uint32()),
        "group": pa.array([r.group for r in rows], pa.string()),
        "index_in_group": pa.array([r.index_in_group for r in rows], pa.uint32()),
        "x_m": pa.array([r.x_m for r in rows], pa.float64()),
        "y_m": pa.array([r.y_m for r in rows], pa.float64()),
        "spreading_factor": pa.array([r.spreading_factor for r in rows], pa.uint8()),
        "sent": pa.array([r.sent for r in rows], pa.uint64()),
        "received": pa.array([r.received for r in rows], pa.uint64()),
        "lost_sensitivity": pa.array([r.lost_sensitivity for r in rows], pa.uint64()),
        "lost_collision": pa.array([r.lost_collision for r in rows], pa.uint64()),
        "airtime_ns": pa.array([r.airtime_ns for r in rows], pa.uint64()),
        "pdr": pa.array([r.pdr for r in rows], pa.float64()),
    })
    if run.energy_profile is not None:
        table = table.append_column("energy_per_message_j", pa.array(
            [r.energy_per_message_j for r in rows], pa.float64()))
        table = table.append_column("average_current_ua", pa.array(
            [r.average_current_ua for r in rows], pa.float64()))
    metadata = {
        b"lsim.scenario_name": run.scenario_name.encode("utf-8"),
        b"lsim.scenario_sha256": run.scenario_sha256.encode("ascii"),
        b"lsim.scenario_schema_version": str(SCHEMA_VERSION).encode("ascii"),
        b"lsim.seed": str(run.seed).encode("ascii"),
        b"lsim.package_version": __version__.encode("ascii"),
        b"lsim.native_version": native_version().encode("ascii"),
        b"lsim.total_sent": str(run.totals.sent).encode("ascii"),
        b"lsim.total_received": str(run.totals.received).encode("ascii"),
        b"lsim.total_airtime_ns": str(run.totals.airtime_ns).encode("ascii"),
    }
    if run.gateway is not None:
        metadata[b"lsim.gateway_busy_ns"] = str(run.gateway.busy_ns).encode("ascii")
        metadata[b"lsim.gateway_peak_concurrent"] = str(run.gateway.peak_concurrent).encode("ascii")
        metadata[b"lsim.gateway_utilization"] = repr(run.gateway.utilization).encode("ascii")
    if run.mesh is not None:
        metadata[b"lsim.mesh_frames"] = str(run.mesh.frames).encode("ascii")
        metadata[b"lsim.mesh_delivered"] = str(run.mesh.delivered).encode("ascii")
        metadata[b"lsim.mesh_via_mesh"] = str(run.mesh.via_mesh).encode("ascii")
    if run.energy_profile is not None:
        metadata[b"lsim.energy_profile"] = run.energy_profile.encode("ascii")
    table = table.replace_schema_metadata(metadata)
    pq.write_table(table, str(path), compression="zstd")
