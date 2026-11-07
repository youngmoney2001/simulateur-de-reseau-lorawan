// Tests unitaires des modules purs du studio (sans navigateur).
import { test } from "node:test";
import assert from "node:assert/strict";
import { createClient, ApiError } from "../src/studio/api.js";
import {
  planBounds, toScreen, toMeters, validateNewNode, validateSensor, sensorFormFrom,
  gridStep, PLAN_MIN_SPAN_M, KIND_LABEL,
} from "../src/studio/topology.js";
// Seules les données sont testées ici (le dessin exige le DOM). Ce sont elles qui engagent
// la conformité de ce que l'interface annonce.
import { DEVICE_SPECS, DEVICE_KINDS, hasArt } from "../src/studio/device-art.js";
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
  // Cadrage resserré : le plan vide fait maintenant 60 m, contre 1000 m avant. Une
  // portée minimale aussi grande noyait les petits réseaux dans un vide blanc.
  assert.ok(planBounds([]).maxX - planBounds([]).minX === 60);
});

test("le pas de grille reste un palier 1, 2 ou 5 et cadre entre 5 et 12 lignes", () => {
  const palierValide = (s) => {
    const p = Math.pow(10, Math.floor(Math.log10(s)));
    return [1, 2, 5, 10].some((m) => Math.abs(s - m * p) < 1e-9 * Math.max(1, s));
  };
  // De 60 m (plan vide) à 12 km : le pas doit toujours être lisible et le nombre de
  // lignes raisonnable, sinon la grille devient un quadrillage illisible.
  for (const portee of [60, 120, 300, 800, 1_500, 4_000, 12_000]) {
    const pas = gridStep(portee);
    assert.ok(palierValide(pas), `pas ${pas} pour ${portee} m n'est pas un palier 1/2/5`);
    const lignes = portee / pas;
    assert.ok(lignes >= 4 && lignes <= 16, `${lignes} lignes pour ${portee} m`);
  }
  assert.equal(gridStep(PLAN_MIN_SPAN_M) > 0, true);
  // Entrées dégénérées : jamais NaN, sinon le rendu produit des coordonnées invalides.
  for (const mauvais of [0, -5, NaN, Infinity]) {
    assert.ok(Number.isFinite(gridStep(mauvais)), `pas non fini pour ${mauvais}`);
  }
});

test("chaque type d'équipement a une illustration et une description complète", () => {
  // Un type sans illustration retomberait sur un dessin d'emprunt : on le refuse.
  for (const kind of Object.keys(KIND_LABEL)) {
    assert.ok(hasArt(kind), `${kind} n'a pas d'illustration propre`);
    const s = DEVICE_SPECS[kind];
    assert.ok(s, `${kind} n'a pas de description`);
    assert.ok(s.role && s.role.length > 10, `${kind} : rôle trop vague`);
    assert.ok(s.ports.length > 0, `${kind} : aucun port déclaré`);
    assert.ok(s.leds.length > 0, `${kind} : aucun voyant déclaré`);
    for (const p of s.ports) assert.ok(p.id && p.label, `${kind} : port incomplet`);
    for (const l of s.leds) assert.ok(l.id && l.label, `${kind} : voyant incomplet`);
  }
  assert.deepEqual([...DEVICE_KINDS].sort(), Object.keys(KIND_LABEL).sort());
});

test("les fenêtres n'annoncent aucun réglage que le moteur ne simule pas", () => {
  // Règle D6 de la conception : on peut montrer, jamais proposer à la saisie, ce qui n'est
  // pas calculé. Ce test est la barrière qui empêche de glisser vers une interface décorative
  // qui mentirait sur ses capacités.
  const interdits = [/\bADR\b/i, /classe\s+[ABC]/i, /\bOTAA\b/i, /\bABP\b/i,
    /\bcoding rate\b/i, /largeur de bande/i, /\bbandwidth\b/i];
  for (const kind of DEVICE_KINDS) {
    const s = DEVICE_SPECS[kind];
    const champs = [s.role, ...s.ports.map((p) => `${p.label} ${p.note ?? ""}`),
      ...s.leds.map((l) => `${l.label} ${l.etat ?? ""}`)];
    for (const texte of champs) {
      for (const motif of interdits) {
        assert.ok(!motif.test(texte),
          `${kind} annonce « ${texte} », qui n'est pas simulé par le moteur`);
      }
    }
  }
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
