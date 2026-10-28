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
from itertools import islice
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


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


_DEM_BLOCK_ROWS = 100_000
_COLUMNS = ("x_m", "y_m", "z_m")


def _columns_arrow(path: Path) -> Optional[tuple[array, array, array]]:
    """Lecture colonne par colonne via PyArrow (C++ multi-thread). None si indisponible.

    Toute anomalie de forme (colonnes, types, valeurs) renvoie None : le lecteur
    Python, plus strict et au message précis par ligne, prend alors le relais.
    """
    try:
        import pyarrow as pa
        import pyarrow.csv as pacsv
    except ImportError:
        return None
    try:
        table = pacsv.read_csv(
            path,
            convert_options=pacsv.ConvertOptions(
                column_types={c: pa.float64() for c in _COLUMNS}, strings_can_be_null=False),
        )
    except (pa.ArrowInvalid, pa.ArrowTypeError, OSError):
        return None
    if tuple(table.column_names) != _COLUMNS:
        return None
    out: list[array] = []
    for name in _COLUMNS:
        col = table[name].combine_chunks()
        if col.null_count:
            return None
        values = array("d")
        values.frombytes(col.buffers()[1].to_pybytes()[col.offset * 8:(col.offset + len(col)) * 8])
        out.append(values)
    return out[0], out[1], out[2]


def _columns_python(path: Path) -> tuple[array, array, array]:
    """Lecteur CSV pur Python par blocs ; erreurs avec numéro de ligne exact."""
    xs = array("d")
    ys = array("d")
    zs = array("d")
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader, None)
        if header is None or tuple(h.strip() for h in header) != _COLUMNS:
            raise ValueError("MNT : en-tête attendu 'x_m,y_m,z_m'")
        lineno = 1
        while True:
            block = list(islice(reader, _DEM_BLOCK_ROWS))
            if not block:
                break
            if len(zs) + len(block) > MAX_TERRAIN_CELLS:
                raise ValueError(f"MNT trop grand (limite {MAX_TERRAIN_CELLS} points)")
            _parse_block(block, lineno + 1, xs, ys, zs)
            lineno += len(block)
    return xs, ys, zs


def _parse_block(block: list[list[str]], first_line: int, xs: array, ys: array,
                 zs: array) -> None:
    """Ajoute un bloc de lignes CSV aux tableaux (boucles C sur le chemin nominal)."""
    if set(map(len, block)) != {3}:
        for offset, row in enumerate(block):
            if len(row) != 3:
                raise ValueError(f"MNT ligne {first_line + offset} : 3 colonnes attendues")
    cols = list(zip(*block))
    try:
        bx = list(map(float, cols[0]))
        by = list(map(float, cols[1]))
        bz = list(map(float, cols[2]))
    except ValueError:
        for offset, row in enumerate(block):
            for v in row:
                try:
                    float(v)
                except ValueError as exc:
                    raise ValueError(
                        f"MNT ligne {first_line + offset} : valeur non numérique") from exc
        raise
    # sum() détecte NaN et infini ; faux positif par débordement : contrôle ligne à ligne.
    if not (math.isfinite(sum(bx)) and math.isfinite(sum(by)) and math.isfinite(sum(bz))):
        for offset in range(len(block)):
            if not (math.isfinite(bx[offset]) and math.isfinite(by[offset])
                    and math.isfinite(bz[offset])):
                raise ValueError(f"MNT ligne {first_line + offset} : valeur non finie")
    xs.extend(bx)
    ys.extend(by)
    zs.extend(bz)


def load_dem_csv(path: Path) -> Terrain:
    """Lit un MNT CSV (`x_m,y_m,z_m`) décrivant une grille régulière complète.

    Chemin rapide PyArrow, repli Python. Mémoire : trois tableaux `array('d')` et les
    valeurs distinctes de x et y (au plus la taille de la grille).
    """
    cols = _columns_arrow(path)
    if cols is None:
        cols = _columns_python(path)
    xs_in, ys_in, zs_in = cols
    n = len(zs_in)
    if n == 0:
        raise ValueError("MNT vide")
    if n > MAX_TERRAIN_CELLS:
        raise ValueError(f"MNT trop grand (limite {MAX_TERRAIN_CELLS} points)")
    if not (math.isfinite(sum(xs_in)) and math.isfinite(sum(ys_in)) and math.isfinite(sum(zs_in))):
        if not all(math.isfinite(v) for v in zs_in):
            raise ValueError("MNT : valeur non finie")
        if not all(math.isfinite(v) for v in xs_in) or not all(math.isfinite(v) for v in ys_in):
            raise ValueError("MNT : coordonnée non finie")

    xs = sorted(set(xs_in))
    ys = sorted(set(ys_in))
    nx, ny = len(xs), len(ys)
    if nx < 2 or ny < 2:
        raise ValueError("MNT : la grille doit compter au moins 2 x 2 points")
    if nx * ny != n:
        raise ValueError("MNT : grille incomplète ou points dupliqués")
    dx = xs[1] - xs[0]
    dy = ys[1] - ys[0]
    if dx <= 0 or dy <= 0:
        raise ValueError("MNT : pas non strictement positif")
    if abs(dx - dy) > _SPACING_TOL * max(dx, dy):
        raise ValueError("MNT : cellules non carrées non supportées")
    if any(abs((xs[i + 1] - xs[i]) - dx) > _SPACING_TOL * dx for i in range(nx - 1)):
        raise ValueError("MNT : pas en x non régulier")
    if any(abs((ys[i + 1] - ys[i]) - dy) > _SPACING_TOL * dy for i in range(ny - 1)):
        raise ValueError("MNT : pas en y non régulier")

    # Chemin rapide (fichier trié ligne par ligne, cas courant) : comparaisons par bloc, C.
    row_sorted = xs_in == array("d", xs) * ny and all(
        ys_in[k * nx:(k + 1) * nx] == array("d", [ys[k]]) * nx for k in range(ny))
    if row_sorted:
        z = array("f", zs_in)
    else:
        ix_of = {x: i for i, x in enumerate(xs)}
        iy_of = {y: i for i, y in enumerate(ys)}
        z = array("f", bytes(4 * n))
        seen = bytearray(n)
        for x, y, zv in zip(xs_in, ys_in, zs_in):
            pos = iy_of[y] * nx + ix_of[x]
            if seen[pos]:
                raise ValueError("MNT : points dupliqués")
            seen[pos] = 1
            z[pos] = zv
    # nx * ny points distincts, tous placés : grille complète, sans trou.
    return Terrain(origin_x_m=xs[0], origin_y_m=ys[0], cell_m=dx, nx=nx, ny=ny, z=z,
                   sha256=_sha256_file(path))


def check_obstacles(obstacles: Sequence[Obstacle]) -> tuple[Obstacle, ...]:
    if len(obstacles) > MAX_OBSTACLES:
        raise ValueError(f"au plus {MAX_OBSTACLES} obstacles")
    return tuple(obstacles)
