#!/usr/bin/env python3
"""Télécharge un MNT libre (Copernicus DEM GLO-30, version publique) et le convertit en CSV.

Source : seau public `copernicus-dem-30m` (AWS, HTTPS, sans compte), licence Copernicus
(usage commercial autorisé avec attribution). Les tuiles sont des 1° x 1° en WGS84.

Sortie : un CSV `x_m,y_m,z_m` sur grille régulière en mètres (UTM), au format attendu par
`lsim.environment.load_dem_csv`, plus un fichier d'attribution `<sortie>.ATTRIBUTION.txt`.

Usage (depuis la racine du dépôt) :
    python scripts/fetch_copernicus_dem.py --bbox 9.5 3.8 9.9 4.2 --out data/douala_dem.csv

Dépendances (outil hors cœur) : rasterio, numpy. Le téléchargement a lieu sur le poste
qui lance le script ; le serveur de simulation ne télécharge rien.

La grille est le rectangle UTM englobant la boîte demandée : ses coins, hors de la source, valent
0 m (à traiter comme absence de donnée côté simulation ; le scénario ne doit pas s'appuyer dessus).

Une tuile absente (HTTP 404) arrête le script : elle peut être de l'océan (pas de tuile) ou une
tuile non publiée par Copernicus (liste à vérifier). `--allow-missing` la remplace par 0 m,
après avertissement explicite.
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
import urllib.error
import urllib.request
from pathlib import Path

BUCKET_URL = "https://copernicus-dem-30m.s3.amazonaws.com"
ATTRIBUTION = (
    "Copernicus DEM GLO-30 (version publique). Données : Copernicus DEM, "
    "© DLR e.V. et Airbus Defence and Space GmbH, fournies au titre de la licence Copernicus "
    "(ESA/Union européenne). Vérifier la formulation exacte sur dataspace.copernicus.eu avant "
    "diffusion."
)
MAX_CELLS = 4_000_000  # même borne que lsim.environment.MAX_TERRAIN_CELLS
CELL_M = 30.0


class MissingTile(RuntimeError):
    pass


def tile_key(lat: int, lon: int) -> str:
    """Nom de tuile Copernicus à partir du coin sud-ouest (degrés entiers)."""
    ns = "N" if lat >= 0 else "S"
    ew = "E" if lon >= 0 else "W"
    name = f"{ns}{abs(lat):02d}_00_{ew}{abs(lon):03d}_00"
    return f"Copernicus_DSM_COG_10_{name}_DEM"


def tiles_for_bbox(lon_min: float, lat_min: float, lon_max: float, lat_max: float) -> list[tuple[int, int]]:
    """Coins SW (lat, lon) des tuiles 1° couvrant la boîte."""
    if not (-180 <= lon_min < lon_max <= 180 and -90 <= lat_min < lat_max <= 90):
        raise ValueError("boîte invalide : lon_min < lon_max et lat_min < lat_max, dans les bornes")
    tiles = []
    for lat in range(math.floor(lat_min), math.ceil(lat_max)):
        for lon in range(math.floor(lon_min), math.ceil(lon_max)):
            tiles.append((lat, lon))
    return tiles


def utm_epsg_for(lon: float, lat: float) -> int:
    """EPSG UTM de l'hémisphère nord (la zone du centre de la boîte)."""
    zone = int((lon + 180.0) // 6.0) + 1
    if lat < 0:
        raise ValueError("ce script couvre l'hémisphère nord (zones UTM nord)")
    return 32600 + zone


def fetch_tile(key: str, cache: Path) -> Path:
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / f"{key}.tif"
    if target.exists() and target.stat().st_size > 0:
        return target
    url = f"{BUCKET_URL}/{key}/{key}.tif"
    try:
        with urllib.request.urlopen(url, timeout=120) as resp:  # noqa: S310 (URL fixe)
            data = resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise MissingTile(key) from exc
        raise
    tmp = target.with_suffix(".part")
    tmp.write_bytes(data)
    tmp.replace(target)
    return target


def convert(bbox: tuple[float, float, float, float], out: Path, cache: Path,
            allow_missing: bool) -> tuple[int, int]:
    import numpy as np
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.merge import merge
    from rasterio.transform import array_bounds
    from rasterio.warp import calculate_default_transform, reproject

    lon_min, lat_min, lon_max, lat_max = bbox
    tiles = tiles_for_bbox(*bbox)
    missing: list[str] = []
    sources = []
    for lat, lon in tiles:
        key = tile_key(lat, lon)
        try:
            sources.append(rasterio.open(fetch_tile(key, cache)))
        except MissingTile:
            if not allow_missing:
                raise
            missing.append(key)
    if missing:
        print("avertissement : tuiles absentes remplacées par 0 m :", *missing, sep="\n  ",
              file=sys.stderr)
    if not sources:
        raise ValueError("aucune tuile disponible pour cette boîte")

    try:
        mosaic, mtrans = merge(sources, bounds=(lon_min, lat_min, lon_max, lat_max),
                               nodata=0.0, dtype="float32")
        src_crs = sources[0].crs
    finally:
        for s in sources:
            s.close()
    src = mosaic[0]
    src_transform = mtrans
    dst_crs = f"EPSG:{utm_epsg_for((lon_min + lon_max) / 2, (lat_min + lat_max) / 2)}"
    west, south, east, north = array_bounds(src.shape[0], src.shape[1], src_transform)
    # Grille UTM de pas exact CELL_M (30 m) couvrant la zone source.
    dst_transform, width, height = calculate_default_transform(
        src_crs, dst_crs, src.shape[1], src.shape[0], west, south, east, north,
        resolution=CELL_M)
    left, top = dst_transform.c, dst_transform.f
    if width * height > MAX_CELLS:
        raise ValueError(f"MNT trop grand : {width} x {height} cellules (limite {MAX_CELLS})")
    dst = np.zeros((height, width), dtype="float32")
    reproject(source=src, destination=dst, src_transform=src_transform, src_crs=src_crs,
              dst_transform=dst_transform, dst_crs=dst_crs, resampling=Resampling.bilinear,
              src_nodata=0.0, dst_nodata=0.0)

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["x_m", "y_m", "z_m"])
        for row in range(height):
            y = top - (row + 0.5) * CELL_M
            for col in range(width):
                x = left + (col + 0.5) * CELL_M
                w.writerow([f"{x:.1f}", f"{y:.1f}", f"{float(dst[row, col]):.2f}"])
    Path(f"{out}.ATTRIBUTION.txt").write_text(
        ATTRIBUTION + f"\nCRS : {dst_crs}, pas {CELL_M:g} m, {width} x {height} cellules.\n",
        encoding="utf-8")
    return width, height


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    p.add_argument("--bbox", nargs=4, type=float, metavar=("LON_MIN", "LAT_MIN", "LON_MAX", "LAT_MAX"),
                   required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--cache", type=Path, default=Path("data/cache/copernicus_dem"))
    p.add_argument("--allow-missing", action="store_true")
    args = p.parse_args(argv)
    try:
        w, h = convert(tuple(args.bbox), args.out, args.cache, args.allow_missing)
    except MissingTile as exc:
        print(f"tuile absente : {exc} (voir --allow-missing)", file=sys.stderr)
        return 2
    print(f"{args.out} : {w} x {h} cellules de {CELL_M:g} m")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
