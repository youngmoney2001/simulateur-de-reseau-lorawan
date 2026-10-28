"""Environnement radio : relief (MNT en CSV) et obstacles (pavés verticaux).

Le relief est lu depuis un CSV `x_m,y_m,z_m` qui doit décrire une grille
régulière complète (chaque couple (x, y) présent une fois, pas constant en x et
en y). Le cœur natif revalide tout : cette couche Python ne fait que lire et
vérifier la forme des données, sans calcul radio.

Le fichier de relief est haché (SHA-256) pour la traçabilité des résultats.
"""

from __future__ import annotations

import csv
import hashlib
import math
from array import array
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

MAX_OBSTACLES = 10_000
MAX_TERRAIN_CELLS = 4_000_000
MAX_HEIGHT_M = 1_000.0
_SPACING_TOL = 1e-6


def _finite(name: str, value: float) -> float:
    if not math.isfinite(value):
        raise ValueError(f"{name} doit être un nombre fini")
    return value


@dataclass(frozen=True)
class Obstacle:
    """Pavé vertical : emprise rectangulaire, sommet à `height_m` au-dessus du sol local."""

    x_min_m: float
    y_min_m: float
    x_max_m: float
    y_max_m: float
    height_m: float
    attenuation_db: float = 0.0

    def __post_init__(self) -> None:
        for name in ("x_min_m", "y_min_m", "x_max_m", "y_max_m", "height_m", "attenuation_db"):
            _finite(name, getattr(self, name))
        if not (self.x_min_m < self.x_max_m and self.y_min_m < self.y_max_m):
            raise ValueError("emprise de l'obstacle vide (min doit être < max)")
        if not 0.0 < self.height_m <= MAX_HEIGHT_M:
            raise ValueError(f"height_m doit être dans ]0 ; {MAX_HEIGHT_M}]")
        if not 0.0 <= self.attenuation_db <= 200.0:
            raise ValueError("attenuation_db doit être dans [0 ; 200]")


@dataclass(frozen=True)
class Terrain:
    """Grille d'altitudes régulière, ligne par ligne (z[iy * nx + ix])."""

    origin_x_m: float
    origin_y_m: float
    cell_m: float
    nx: int
    ny: int
    z: array = field(repr=False)
    sha256: str = ""

    def __post_init__(self) -> None:
        _finite("origin_x_m", self.origin_x_m)
        _finite("origin_y_m", self.origin_y_m)
        if not (math.isfinite(self.cell_m) and self.cell_m > 0):
            raise ValueError("cell_m doit être un nombre fini strictement positif")
        if self.nx < 2 or self.ny < 2:
            raise ValueError("la grille doit compter au moins 2 x 2 points")
        if self.nx * self.ny > MAX_TERRAIN_CELLS:
            raise ValueError(f"grille trop grande (limite {MAX_TERRAIN_CELLS} points)")
        if len(self.z) != self.nx * self.ny or self.z.typecode != "f":
            raise ValueError("tableau d'altitudes incohérent avec les dimensions")


@dataclass(frozen=True)
class Environment:
    terrain: Optional[Terrain] = None
    obstacles: tuple[Obstacle, ...] = ()
    gateway_height_m: float = 15.0
    device_height_m: float = 1.5

    def __post_init__(self) -> None:
        if len(self.obstacles) > MAX_OBSTACLES:
            raise ValueError(f"au plus {MAX_OBSTACLES} obstacles")
        for name in ("gateway_height_m", "device_height_m"):
            v = _finite(name, getattr(self, name))
            if not 0.0 < v <= MAX_HEIGHT_M:
                raise ValueError(f"{name} doit être dans ]0 ; {MAX_HEIGHT_M}]")


def load_dem_csv(path: Path) -> Terrain:
    """Lit un MNT CSV (`x_m,y_m,z_m`) décrivant une grille régulière complète."""
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader, None)
        if header is None or [h.strip() for h in header] != ["x_m", "y_m", "z_m"]:
            raise ValueError("MNT : en-tête attendu 'x_m,y_m,z_m'")
        rows: list[tuple[float, float, float]] = []
        for lineno, row in enumerate(reader, start=2):
            if len(rows) >= MAX_TERRAIN_CELLS:
                raise ValueError(f"MNT trop grand (limite {MAX_TERRAIN_CELLS} points)")
            if len(row) != 3:
                raise ValueError(f"MNT ligne {lineno} : 3 colonnes attendues")
            try:
                x, y, z = (float(v) for v in row)
            except ValueError as exc:
                raise ValueError(f"MNT ligne {lineno} : valeur non numérique") from exc
            if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(z)):
                raise ValueError(f"MNT ligne {lineno} : valeur non finie")
            rows.append((x, y, z))
    if not rows:
        raise ValueError("MNT vide")

    xs = sorted({r[0] for r in rows})
    ys = sorted({r[1] for r in rows})
    nx, ny = len(xs), len(ys)
    if nx < 2 or ny < 2:
        raise ValueError("MNT : la grille doit compter au moins 2 x 2 points")
    if nx * ny != len(rows):
        raise ValueError("MNT : grille incomplète ou points dupliqués")
    dx = xs[1] - xs[0]
    dy = ys[1] - ys[0]
    if dx <= 0 or dy <= 0:
        raise ValueError("MNT : pas non strictement positif")
    tol_x = _SPACING_TOL * dx
    tol_y = _SPACING_TOL * dy
    if any(abs((xs[i + 1] - xs[i]) - dx) > tol_x for i in range(nx - 1)):
        raise ValueError("MNT : pas en x non régulier")
    if any(abs((ys[i + 1] - ys[i]) - dy) > tol_y for i in range(ny - 1)):
        raise ValueError("MNT : pas en y non régulier")
    if abs(dx - dy) > _SPACING_TOL * max(dx, dy):
        raise ValueError("MNT : cellules non carrées non supportées")

    ix_of = {x: i for i, x in enumerate(xs)}
    iy_of = {y: i for i, y in enumerate(ys)}
    z = array("f", bytes(4 * nx * ny))
    seen = bytearray(nx * ny)
    for x, y, zv in rows:
        pos = iy_of[y] * nx + ix_of[x]
        if seen[pos]:
            raise ValueError("MNT : points dupliqués")
        seen[pos] = 1
        z[pos] = zv
    if not all(seen):
        raise ValueError("MNT : grille incomplète")

    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return Terrain(origin_x_m=xs[0], origin_y_m=ys[0], cell_m=dx, nx=nx, ny=ny, z=z,
                   sha256=digest)


def check_obstacles(obstacles: Sequence[Obstacle]) -> tuple[Obstacle, ...]:
    if len(obstacles) > MAX_OBSTACLES:
        raise ValueError(f"au plus {MAX_OBSTACLES} obstacles")
    return tuple(obstacles)
