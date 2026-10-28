import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { validateMap, parseMap, pdrColor, boundsOf, MAX_FEATURES } from "../src/model.js";

const sample = JSON.parse(readFileSync(new URL("../public/sample.geojson", import.meta.url), "utf8"));

test("the sample map validates and parses", () => {
  const p = parseMap(sample);
  assert.ok(p.gateway);
  assert.equal(p.coverage.length, 1);
  assert.equal(p.devices.length, 500);
});

test("the relief sample carries obstacles that are extruded and bounded", () => {
  const relief = JSON.parse(readFileSync(new URL("../public/sample_relief.geojson", import.meta.url), "utf8"));
  const p = parseMap(relief);
  assert.equal(p.obstacles.length, 5);
  for (const o of p.obstacles) {
    assert.ok(o.height_m > 0 && o.height_m <= 1000);
    assert.ok(o.ring.length >= 4);
  }
  const b = boundsOf(p);
  for (const o of p.obstacles) {
    for (const [x, y] of o.ring) assert.ok(x >= b.west && x <= b.east && y >= b.south && y <= b.north);
  }
});

test("obstacles with invalid heights or shapes are refused", () => {
  const ring = [[9.7, 4.0], [9.71, 4.0], [9.71, 4.01], [9.7, 4.0]];
  const obs = (props, geometry) => ({ type: "FeatureCollection", features: [{ properties: { kind: "obstacle", ...props }, geometry }] });
  const poly = { type: "Polygon", coordinates: [ring] };
  assert.throws(() => validateMap(obs({ height_m: 0 }, poly)), /hauteur/);
  assert.throws(() => validateMap(obs({ height_m: 5000 }, poly)), /hauteur/);
  assert.throws(() => validateMap(obs({ height_m: 10 }, { type: "Point", coordinates: [9.7, 4] })), /polygone/);
  assert.throws(() => validateMap(obs({}, poly)), /hauteur/);
  assert.doesNotThrow(() => validateMap(obs({ height_m: 10 }, poly)));
});

test("pdr colours follow the thresholds", () => {
  assert.equal(pdrColor(1), "#2e7d32");
  assert.equal(pdrColor(0.95), "#2e7d32");
  assert.equal(pdrColor(0.84), "#9ccc65");
  assert.equal(pdrColor(0.6), "#ff9800");
  assert.equal(pdrColor(0.1), "#d32f2f");
  assert.equal(pdrColor(null), "#9e9e9e");
  assert.equal(pdrColor(Number.NaN), "#9e9e9e");
});

test("invalid documents are refused with explicit messages", () => {
  assert.throws(() => validateMap(null), /FeatureCollection/);
  assert.throws(() => validateMap({ type: "Feature" }), /FeatureCollection/);
  assert.throws(
    () => validateMap({ type: "FeatureCollection", features: [{ properties: { kind: "script" } }] }),
    /inconnu/,
  );
  assert.throws(
    () => validateMap({ type: "FeatureCollection", features: [{ properties: { kind: "device" }, geometry: { type: "Point", coordinates: [200, 0] } }] }),
    /point géographique/,
  );
  assert.throws(
    () => validateMap({ type: "FeatureCollection", features: [{ properties: { kind: "coverage" }, geometry: { type: "Point", coordinates: [0, 0] } }] }),
    /polygone/,
  );
});

test("too many features are refused before rendering", () => {
  const features = new Array(MAX_FEATURES + 1).fill({ properties: { kind: "device" } });
  assert.throws(() => validateMap({ type: "FeatureCollection", features }), /volumineux/);
});

test("bounds cover every entity", () => {
  const b = boundsOf(parseMap(sample));
  for (const d of parseMap(sample).devices) {
    const [x, y] = d.lonlat;
    assert.ok(x >= b.west && x <= b.east && y >= b.south && y <= b.north);
  }
  assert.equal(boundsOf({ gateway: null, coverage: [], devices: [] }), null);
});

// ---------------------------------------------------------------- relief (MNT)
import {
  parseDem,
  lonLatToLocal,
  localToLonLat,
  groundAtLocal,
  groundAtLonLat,
  footprintBase,
  heightmapTile,
  DEM_FORMAT,
} from "../src/model.js";

function demDocument({ nx, ny, cell, z, x0 = 0, y0 = 0, lat = 4.0511, lon = 9.7679 }) {
  const f32 = Float32Array.from(z);
  return {
    format: DEM_FORMAT,
    origin: { latitude: lat, longitude: lon },
    origin_x_m: x0,
    origin_y_m: y0,
    cell_m: cell,
    nx,
    ny,
    encoding: "float32-le-base64",
    z: Buffer.from(f32.buffer).toString("base64"),
    sha256: "abc",
  };
}

test("the DEM document decodes and validates", () => {
  const dem = parseDem(demDocument({ nx: 2, ny: 2, cell: 100, z: [1, 2, 3, 4] }));
  assert.equal(dem.nx, 2);
  assert.deepEqual(Array.from(dem.z), [1, 2, 3, 4]);
  assert.equal(dem.sha256, "abc");
});

test("invalid DEM documents are refused explicitly", () => {
  const good = demDocument({ nx: 2, ny: 2, cell: 100, z: [1, 2, 3, 4] });
  assert.throws(() => parseDem({ ...good, format: "other" }), /lsim-dem-v1/);
  assert.throws(() => parseDem({ ...good, cell_m: 0 }), /pas/);
  assert.throws(() => parseDem({ ...good, nx: 3 }), /taille/);
  assert.throws(() => parseDem({ ...good, nx: 4000, ny: 4000 }), /trop grand/);
  assert.throws(() => parseDem({ ...good, encoding: "text" }), /encodage/);
  const nan = demDocument({ nx: 2, ny: 2, cell: 100, z: [1, NaN, 3, 4] });
  assert.throws(() => parseDem(nan), /non finie/);
});

test("local projection round-trips and matches the scale of geo.py", () => {
  const dem = parseDem(demDocument({ nx: 2, ny: 2, cell: 100, z: [0, 0, 0, 0] }));
  const { x, y } = lonLatToLocal(dem, 9.7679 + 0.01, 4.0511 + 0.01);
  // 0,01° de latitude ~ 1113 m ; 0,01° de longitude ~ 1113 m x cos(4°).
  assert.ok(Math.abs(y - 1111.95) < 1.0);
  assert.ok(Math.abs(x - 1111.95 * Math.cos((4.0511 * Math.PI) / 180)) < 1.0);
  const back = localToLonLat(dem, x, y);
  assert.ok(Math.abs(back.lon - (9.7679 + 0.01)) < 1e-9);
  assert.ok(Math.abs(back.lat - (4.0511 + 0.01)) < 1e-9);
});

test("bilinear ground elevation and clamping outside the grid", () => {
  const dem = parseDem(demDocument({ nx: 2, ny: 2, cell: 100, z: [0, 10, 20, 30] }));
  assert.equal(groundAtLocal(dem, 0, 0), 0);
  assert.equal(groundAtLocal(dem, 100, 0), 10);
  assert.equal(groundAtLocal(dem, 50, 50), 15);
  assert.equal(groundAtLocal(dem, -500, -500), 0); // clamp
  assert.equal(groundAtLocal(dem, 900, 900), 30); // clamp
});

test("heightmap tiles put the north row first and sample the grid", () => {
  // z croît vers le nord : y = 100 (nord) doit donner la valeur la plus haute.
  const dem = parseDem(demDocument({ nx: 2, ny: 2, cell: 100, z: [0, 0, 100, 100] }));
  const { lat: north } = localToLonLat(dem, 0, 100);
  const { lat: south } = localToLonLat(dem, 0, 0);
  const { lon: west } = localToLonLat(dem, 0, 0);
  const { lon: east } = localToLonLat(dem, 100, 0);
  const tile = heightmapTile(dem, west, south, east, north, 3, 3);
  assert.equal(tile.length, 9);
  assert.ok(tile[0] > 99 && tile[2] > 99, "première ligne = nord");
  assert.ok(tile[6] < 1 && tile[8] < 1, "dernière ligne = sud");
});

test("obstacle base is the lowest ground under its footprint", () => {
  const dem = parseDem(demDocument({ nx: 2, ny: 2, cell: 100, z: [0, 0, 100, 100] }));
  const low = localToLonLat(dem, 10, 10);
  const high = localToLonLat(dem, 90, 90);
  const ring = [[low.lon, low.lat], [high.lon, low.lat], [high.lon, high.lat], [low.lon, low.lat]];
  // Sommet le plus bas de l'emprise : sol interpolé à y = 10 m, soit 10 m.
  assert.ok(Math.abs(footprintBase(dem, ring) - 10) < 0.5);
  assert.ok(groundAtLonLat(dem, high.lon, high.lat) > 50);
});
