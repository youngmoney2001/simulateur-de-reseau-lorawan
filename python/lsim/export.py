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
from lsim.mesh_pass import mesh_pass
from lsim.simulator import (
    Counters,
    GatewayLoad,
    GatewayRxCounters,
    simulate_uplinks,
    simulate_uplinks_multi,
)


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
    copies_on_mesh: int  # copies confiées au mesh (une par relais qui a décodé l'accès)
    transmissions: int   # émissions mesh effectives (chaque saut compte une fois)
    suppressed: int      # copies abandonnées : un doublon avait déjà été relayé
    no_route: int        # copies sans route vers la frontière
    hop_losses: tuple[tuple[str, int], ...]  # sauts perdus par raison : collision, half_duplex
    # Descente (acquittement possible pour chaque trame remise), fenêtre atteignable :
    dl_rx1: int = 0      # réponse dans RX1 (+1 s)
    dl_rx2: int = 0      # réponse dans RX2 (+2 s) seulement
    dl_missed: int = 0   # aucune fenêtre : la descente arrive après RX2
    dl_mesh_airtime_ns: int = 0  # temps d'antenne mesh d'un saut de descente (lien mesh)

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
    # Multi-passerelles : une entrée par passerelle (même ordre que le fichier), charge de
    # réception sur les trames audibles. Vide en mono-passerelle.
    gateway_names: tuple[str, ...] = ()
    gateway_loads: tuple[GatewayRxCounters, ...] = ()

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
                         energy_profile=energy_profile,
                         gateway_names=_gateway_names(gw_models),
                         gateway_loads=tuple(result.per_gateway))

    mp = mesh_pass(scenario, devices, gw_models, result.trace)
    d_frames = mp.delivered_frames
    mesh_result = mp.mesh_result
    totals = Counters(result.network.sent, len(d_frames),
                      result.network.lost_sensitivity, result.network.lost_collision,
                      result.network.airtime_ns, result.network.lost_gateway_busy)
    summary = MeshSummary(
        frames=mp.seen_frames,
        delivered=len(d_frames),
        direct=len(mp.direct_frames),
        via_mesh=len(mp.via_mesh_frames),
        copies_on_mesh=mp.copies_on_mesh,
        transmissions=mesh_result.transmissions,
        suppressed=mesh_result.suppressed,
        no_route=mp.no_route,
        hop_losses=tuple(
            (reason, n) for reason, n in (
                ("collision", mesh_result.lost_collision),
                ("half_duplex", mesh_result.lost_half_duplex),
            ) if n
        ),
        dl_rx1=mp.dl_counts["rx1"],
        dl_rx2=mp.dl_counts["rx2"],
        dl_missed=mp.dl_counts["missed"],
        dl_mesh_airtime_ns=mp.mesh_air_ns,
    )
    rows = _rows(devices, groups, indices, energies, result.per_device, list(mp.delivered_by_device))
    return RunResult(scenario_name=scenario.name, scenario_sha256=scenario.sha256,
                     seed=scenario.model.seed, rows=rows, totals=totals, gateway=None,
                     energy_profile=energy_profile, mesh=summary,
                     gateway_names=_gateway_names(gw_models),
                     gateway_loads=tuple(result.per_gateway))


def _gateway_names(gw_models) -> tuple[str, ...]:
    return tuple(g.name or f"passerelle-{k + 1}" for k, g in enumerate(gw_models))


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
    if run.gateway_loads:
        import json

        per_gw = [
            {"name": name, "audible_frames": g.audible_frames, "busy_ns": g.busy_ns,
             "peak_concurrent": g.peak_concurrent, "utilization": g.utilization,
             "received": g.received, "lost_collision": g.lost_collision,
             "lost_gateway_busy": g.lost_gateway_busy}
            for name, g in zip(run.gateway_names, run.gateway_loads)
        ]
        metadata[b"lsim.gateways"] = json.dumps(per_gw, ensure_ascii=False).encode("utf-8")
    if run.mesh is not None:
        metadata[b"lsim.mesh_frames"] = str(run.mesh.frames).encode("ascii")
        metadata[b"lsim.mesh_delivered"] = str(run.mesh.delivered).encode("ascii")
        metadata[b"lsim.mesh_via_mesh"] = str(run.mesh.via_mesh).encode("ascii")
        metadata[b"lsim.mesh_transmissions"] = str(run.mesh.transmissions).encode("ascii")
        metadata[b"lsim.mesh_suppressed"] = str(run.mesh.suppressed).encode("ascii")
        metadata[b"lsim.mesh_dl_rx1"] = str(run.mesh.dl_rx1).encode("ascii")
        metadata[b"lsim.mesh_dl_rx2"] = str(run.mesh.dl_rx2).encode("ascii")
        metadata[b"lsim.mesh_dl_missed"] = str(run.mesh.dl_missed).encode("ascii")
    if run.energy_profile is not None:
        metadata[b"lsim.energy_profile"] = run.energy_profile.encode("ascii")
    table = table.replace_schema_metadata(metadata)
    pq.write_table(table, str(path), compression="zstd")
