"""Outil d'acquisition du MNT libre (Copernicus GLO-30) : nommage, zone UTM, conversion."""

import importlib.util
from pathlib import Path

import pytest

from lsim.environment import load_dem_csv

pytestmark = pytest.mark.filterwarnings("ignore::PendingDeprecationWarning")  # rasterio

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("fetch_copernicus_dem",
                                               ROOT / "scripts" / "fetch_copernicus_dem.py")
fdem = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fdem)


def test_tile_key_matches_copernicus_naming():
    assert fdem.tile_key(3, 9) == "Copernicus_DSM_COG_10_N03_00_E009_00_DEM"
    assert fdem.tile_key(-1, -70) == "Copernicus_DSM_COG_10_S01_00_W070_00_DEM"


def test_tiles_for_bbox_covers_box():
    assert fdem.tiles_for_bbox(9.5, 3.8, 9.9, 4.2) == [(3, 9), (4, 9)]
    with pytest.raises(ValueError):
        fdem.tiles_for_bbox(10, 3, 9, 4)


def test_utm_zone_for_douala_and_yaounde():
    assert fdem.utm_epsg_for(9.7, 4.05) == 32632  # Douala : zone 32N
    assert fdem.utm_epsg_for(11.5, 3.87) == 32632  # Yaoundé : zone 32N
    with pytest.raises(ValueError):
        fdem.utm_epsg_for(9.7, -4.0)


def test_convert_synthetic_tile_to_engine_csv(tmp_path):
    rasterio = pytest.importorskip("rasterio")
    import numpy as np
    from rasterio.transform import from_origin

    # Tuile 1° (N03 E009) de synthèse : relief croissant vers le nord, 0,01° par pixel.
    cache = tmp_path / "cache"
    cache.mkdir()
    key = fdem.tile_key(3, 9)
    n = 100
    lat_centres = 4.0 - (np.arange(n) + 0.5) * 0.01
    data = np.tile(((lat_centres - 3.0) * 1000.0 + 100.0).astype("float32")[:, None], (1, n))
    with rasterio.open(cache / f"{key}.tif", "w", driver="GTiff", height=n, width=n, count=1,
                       dtype="float32", crs="EPSG:4326", transform=from_origin(9.0, 4.0, 0.01, 0.01),
                       nodata=0.0) as dst:
        dst.write(data, 1)

    out = tmp_path / "dem.csv"
    w, h = fdem.convert((9.6, 3.9, 9.65, 3.95), out, cache, allow_missing=False)
    assert w * h > 0
    terrain = load_dem_csv(out)
    assert terrain.nx == w and terrain.ny == h
    # Les coins de la grille UTM (rectangle englobant la boîte tournée) hors de la source valent
    # 0 m ; la zone intérieure porte le relief de la tuile (1000 à 1050 m).
    z = terrain.z
    inner = [z[row * terrain.nx + col] for row in range(h // 4, 3 * h // 4)
             for col in range(w // 4, 3 * w // 4)]
    assert min(inner) > 990 and max(inner) < 1060
    attribution = Path(f"{out}.ATTRIBUTION.txt").read_text(encoding="utf-8")
    assert "Copernicus" in attribution

