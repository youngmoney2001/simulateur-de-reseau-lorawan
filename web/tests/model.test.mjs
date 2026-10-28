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
