"""Exécution d'un scénario et export des résultats (Parquet, métadonnées de traçabilité).

Les compteurs sont produits par le cœur natif ; ce module ne fait que les
assembler, calculer le taux de livraison (PDR) et les écrire.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

from lsim import __version__
from lsim.native_info import native_version
from lsim.scenario import SCHEMA_VERSION, Scenario
from lsim.simulator import Counters, simulate_uplinks


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

    @property
    def pdr(self) -> Optional[float]:
        return self.received / self.sent if self.sent else None


@dataclass(frozen=True)
class RunResult:
    scenario_name: str
    scenario_sha256: str
    seed: int
    rows: tuple[DeviceRow, ...]
    totals: Counters

    @property
    def pdr(self) -> Optional[float]:
        return self.totals.received / self.totals.sent if self.totals.sent else None


def run_scenario(scenario: Scenario) -> RunResult:
    """Déploie le scénario et lance la simulation native."""
    devices, groups, indices = scenario.deploy()
    result = simulate_uplinks(devices, scenario.gateway(), scenario.propagation())
    rows = tuple(
        DeviceRow(
            device_index=i,
            group=groups[i],
            index_in_group=indices[i],
            x_m=dev.x_m,
            y_m=dev.y_m,
            spreading_factor=dev.spreading_factor,
            sent=c.sent,
            received=c.received,
            lost_sensitivity=c.lost_sensitivity,
            lost_collision=c.lost_collision,
        )
        for i, (dev, c) in enumerate(zip(devices, result.per_device))
    )
    return RunResult(
        scenario_name=scenario.name,
        scenario_sha256=scenario.sha256,
        seed=scenario.model.seed,
        rows=rows,
        totals=result.totals,
    )


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
        "pdr": pa.array([r.pdr for r in rows], pa.float64()),
    })
    metadata = {
        b"lsim.scenario_name": run.scenario_name.encode("utf-8"),
        b"lsim.scenario_sha256": run.scenario_sha256.encode("ascii"),
        b"lsim.scenario_schema_version": str(SCHEMA_VERSION).encode("ascii"),
        b"lsim.seed": str(run.seed).encode("ascii"),
        b"lsim.package_version": __version__.encode("ascii"),
        b"lsim.native_version": native_version().encode("ascii"),
        b"lsim.total_sent": str(run.totals.sent).encode("ascii"),
        b"lsim.total_received": str(run.totals.received).encode("ascii"),
    }
    table = table.replace_schema_metadata(metadata)
    pq.write_table(table, str(path), compression="zstd")
