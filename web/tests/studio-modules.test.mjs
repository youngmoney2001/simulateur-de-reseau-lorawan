// Tests unitaires des modules purs du studio (sans navigateur).
import { test } from "node:test";
import assert from "node:assert/strict";
import { createClient, ApiError } from "../src/studio/api.js";
import {
  planBounds, toScreen, toMeters, validateNewNode, validateSensor, sensorFormFrom,
} from "../src/studio/topology.js";
import { createHistory } from "../src/studio/console.js";
import { gatewayRows, formatMs, scoreLine, criteriaRows } from "../src/studio/results.js";

function fakeFetch(responses) {
  const calls = [];
  const fetchImpl = async (url, init) => {
    calls.push({ url, init });
    const next = responses.shift();
    return {
      status: next.status,
      ok: next.status >= 200 && next.status < 300,
      text: async () => (next.body === undefined ? "" : JSON.stringify(next.body)),
    };
  };
  return { fetchImpl, calls };
}

test("le client envoie le jeton en en-tête, jamais dans l'URL", async () => {
  const { fetchImpl, calls } = fakeFetch([{ status: 200, body: { items: [] } }]);
  const client = createClient({ token: "secret-1", fetchImpl });
  await client.listSessions();
  assert.equal(calls[0].url, "/api/v1/sessions");
  assert.equal(calls[0].init.headers.Authorization, "Bearer secret-1");
  assert.ok(!calls[0].url.includes("secret-1"));
});

test("le client encode les identifiants et lit les erreurs au format problème", async () => {
  const { fetchImpl, calls } = fakeFetch([
    { status: 200, body: {} },
    { status: 422, body: { code: "validation_error", message: "id inconnu", field: "node_id" } },
  ]);
  const client = createClient({ token: "t", fetchImpl });
  await client.cli("s1", "gw-1", "show version");
  assert.equal(calls[0].init.method, "POST");
  assert.deepEqual(JSON.parse(calls[0].init.body), { node_id: "gw-1", command: "show version" });
  await assert.rejects(client.removeNode("s1", "a/b"), (err) => {
    assert.ok(err instanceof ApiError);
    assert.equal(err.status, 422);
    assert.equal(err.code, "validation_error");
    assert.equal(err.field, "node_id");
    return true;
  });
  assert.equal(calls[1].url, "/api/v1/sessions/s1/nodes/a%2Fb");
});

test("un 204 renvoie null", async () => {
  const { fetchImpl } = fakeFetch([{ status: 204 }]);
  assert.equal(await createClient({ token: "t", fetchImpl }).deleteSession("s1"), null);
});

test("les coordonnées aller-retour restent cohérentes et la boîte englobe les équipements", () => {
  const nodes = [{ x_m: -300, y_m: 0 }, { x_m: 500, y_m: 200 }];
  const b = planBounds(nodes);
  assert.ok(b.minX < -300 && b.maxX > 500 && b.minY < 0 && b.maxY > 200);
  const p = toScreen({ x_m: 100, y_m: 50 }, b, 800, 520);
  const back = toMeters(p, b, 800, 520);
  assert.ok(Math.abs(back.x_m - 100) < 0.2 && Math.abs(back.y_m - 50) < 0.2);
  assert.ok(planBounds([]).maxX - planBounds([]).minX >= 1000);
});

test("validation d'un équipement : identifiant, type, coordonnées", () => {
  const ok = validateNewNode({ id: "gw-nord", kind: "border", name: "", x_m: "10", y_m: "-4" });
  assert.equal(ok.ok, true);
  assert.equal(ok.node.name, "gw-nord");
  assert.equal(validateNewNode({ id: "GW", kind: "border", x_m: 0, y_m: 0 }).field, "id");
  assert.equal(validateNewNode({ id: "gw", kind: "switch", x_m: 0, y_m: 0 }).field, "kind");
  assert.equal(validateNewNode({ id: "gw", kind: "relay", x_m: "", y_m: 0 }).field, "x_m");
});

test("validation capteur : bornes, entiers, plan régional optionnel", () => {
  const base = { spreading_factor: "9", payload_bytes: "20", tx_power_dbm: "14.5", period_s: "600",
    messages: "2", start_spread_s: "0", region: "", channel_freq_hz: "" };
  const ok = validateSensor(base);
  assert.deepEqual(ok.settings, { spreading_factor: 9, payload_bytes: 20, tx_power_dbm: 14.5,
    period_s: 600, messages: 2, start_spread_s: 0 });
  assert.equal(validateSensor({ ...base, spreading_factor: "13" }).field, "spreading_factor");
  assert.equal(validateSensor({ ...base, region: "MARS" }).field, "region");
  assert.equal(validateSensor({ ...base, channel_freq_hz: "868100000" }).settings.channel_freq_hz, 868100000);
  assert.equal(sensorFormFrom({ kind: "sensor" }).spreading_factor, 7);
});

test("historique de console : flèches haut/bas, pas de doublons consécutifs", () => {
  const h = createHistory();
  h.push("enable"); h.push("enable"); h.push("show version");
  assert.equal(h.size(), 2);
  assert.equal(h.up(""), "show version");
  assert.equal(h.up(""), "enable");
  assert.equal(h.up(""), "enable");
  assert.equal(h.down(""), "show version");
  assert.equal(h.down(""), "");
});

test("mise en forme : latence absente, lien non lié, score avec indices", () => {
  assert.equal(formatMs(null), "—");
  assert.equal(formatMs(228.44), "228.4 ms");
  const rows = gatewayRows({ gateways: [
    { name: "frontiere", received: 5, lost_sensitivity: 1, lost_collision: 2, lost_gateway_busy: 0,
      latency_p95_ms: 228.4, latency_samples: 5, mesh_inbound: [{ from_gateway: "relais-1", delivered: 3 }] },
    { name: "relais-1", received: 0, lost_sensitivity: 0, lost_collision: 0, lost_gateway_busy: 0 },
  ] }, ["frontiere"]);
  assert.equal(rows[0].lost, 3);
  assert.equal(rows[0].mesh, "relais-1 (3)");
  assert.equal(rows[0].linked, true);
  assert.equal(rows[1].linked, false);
  assert.equal(rows[1].latency, "—");
  assert.equal(rows[1].mesh, "—");
  assert.equal(scoreLine({ score: 18, max_score: 20, hints_used: 1 }), "18 / 20 points · 1 indice(s)");
  assert.deepEqual(criteriaRows({ criteria: [{ label: "x", passed: true, points: 5, max_points: 5 }] })[0].points, "5 / 5");
});
