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
