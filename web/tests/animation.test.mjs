// Tests de la logique d'animation des trames (sans DOM). Lancer : `npm test` depuis web/.
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  HOLD_NS, TRAVEL_NS, activeAt, deviceGroupsFromRows, journalRow, outcomeClass,
  resolveId, segmentsFromEvents, timelineBounds,
} from "../src/studio/animation.js";

const GROUPS = ["capteur-a", "capteur-b"];

test("résolution des identifiants : capteur, passerelle, réseau", () => {
  assert.equal(resolveId("dev:1", GROUPS), "capteur-b");
  assert.equal(resolveId("dev:9", GROUPS), null);
  assert.equal(resolveId("dev:-1", GROUPS), null);
  assert.equal(resolveId("gw:frontiere", GROUPS), "frontiere");
  assert.equal(resolveId("ns", GROUPS), null);
  assert.equal(resolveId(42, GROUPS), null);
});

test("classes de résultat", () => {
  assert.equal(outcomeClass("delivered"), "ok");
  assert.equal(outcomeClass("lost_collision"), "lost");
  assert.equal(outcomeClass("sent"), "neutral");
});

test("un saut devient un segment, le saut vers le réseau n'a pas de destination", () => {
  const events = [{
    seq: 0, kind: "uplink", outcome: "delivered", device_index: 0, t_ns: 5_000_000_000,
    hops: [
      { from_id: "dev:0", to_id: "gw:frontiere", t_ns: 5_000_000_000, outcome: "delivered", rssi_dbm: -110 },
      { from_id: "gw:frontiere", to_id: "ns", t_ns: 5_100_000_000, outcome: "delivered", rssi_dbm: null },
    ],
  }];
  const segs = segmentsFromEvents(events, GROUPS);
  assert.equal(segs.length, 2);
  assert.deepEqual([segs[0].from, segs[0].to, segs[0].cls], ["capteur-a", "frontiere", "ok"]);
  assert.deepEqual([segs[1].from, segs[1].to], ["frontiere", null]);
  assert.equal(segs[0].rssi, -110);
});

test("activeAt : avancement linéaire, arrivée puis trait conservé, puis disparition", () => {
  const segs = segmentsFromEvents([{
    seq: 0, kind: "uplink", outcome: "delivered", t_ns: 10_000_000_000,
    hops: [{ from_id: "dev:0", to_id: "gw:frontiere", t_ns: 10_000_000_000, outcome: "delivered" }],
  }], GROUPS);
  const t0 = 10_000_000_000n;
  assert.equal(activeAt(segs, t0 - 1n).length, 0);
  const mid = activeAt(segs, t0 + TRAVEL_NS / 2n);
  assert.equal(mid.length, 1);
  assert.ok(Math.abs(mid[0].progress - 0.5) < 1e-9);
  assert.equal(activeAt(segs, t0 + TRAVEL_NS + 1n)[0].progress, 1);
  assert.equal(activeAt(segs, t0 + TRAVEL_NS + HOLD_NS + 1n).length, 0);
});

test("bornes de la chronologie et ligne de journal", () => {
  const events = [{ seq: 0, t_ns: 3_000_000_000, kind: "uplink", outcome: "lost_collision", device_index: 1, hops: [] },
    { seq: 1, t_ns: 1_000_000_000, kind: "ack", outcome: "delivered", hops: [] }];
  const bounds = timelineBounds(events);
  assert.equal(bounds.startNs, 1_000_000_000n);
  assert.equal(bounds.endNs, 3_000_000_000n);
  assert.deepEqual(timelineBounds([]), { startNs: 0n, endNs: 0n });
  const row = journalRow(events[0], GROUPS);
  assert.equal(row.time, "3.000 s");
  assert.equal(row.source, "capteur-b");
  assert.equal(row.cls, "lost");
});

test("table dispositif -> capteur à partir des lignes paginées", () => {
  const groups = deviceGroupsFromRows([
    { device_index: 0, group: "capteur-a" }, { device_index: 1, group: "capteur-b" },
  ]);
  assert.deepEqual(groups, ["capteur-a", "capteur-b"]);
});

test("collectPages lit toutes les pages et refuse un dépassement", async () => {
  const { collectPages } = await import("../src/studio/animation.js");
  const pages = { 0: { items: [1, 2], next_cursor: 2 }, 2: { items: [3], next_cursor: null } };
  assert.deepEqual(await collectPages(async (c) => pages[c]), [1, 2, 3]);
  await assert.rejects(() => collectPages(async (c) => pages[c], 2), /trop d'événements/);
});
