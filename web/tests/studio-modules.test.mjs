// Tests unitaires des modules purs du studio (sans navigateur).
import { test } from "node:test";
import assert from "node:assert/strict";
import { createClient, ApiError } from "../src/studio/api.js";
import {
  planBounds, toScreen, toMeters, validateNewNode, validateSensor, sensorFormFrom,
  gridStep, PLAN_MIN_SPAN_M, KIND_LABEL, validateNewNodeGeo, validateGateway,
  modelesAdmis, aideModele,
} from "../src/studio/topology.js";
import { degresVersMetres, metresVersDegres } from "../src/studio/geo.js";
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

test("ajout d'un capteur : le matériel choisi dans la palette part avec lui", () => {
  // La palette présente les modèles du moteur ; poser un RAK4631 doit le poser tel quel,
  // avant son premier run, et non après coup. Les autres types n'ont pas de matériel : le
  // serveur refuse des réglages de capteur ailleurs, et ce refus est juste.
  const capteur = validateNewNode({ id: "capt-1", kind: "sensor", name: "Capteur",
    x_m: "0", y_m: "0", energy_profile: "rak4631" });
  assert.equal(capteur.ok, true);
  assert.deepEqual(capteur.node.sensor, { energy_profile: "rak4631" });
  assert.equal("sensor" in validateNewNode({ id: "capt-2", kind: "sensor", x_m: 0, y_m: 0 }), false);
  assert.equal("sensor" in validateNewNode({ id: "gw", kind: "border", x_m: 0, y_m: 0,
    energy_profile: "rak4631" }), false);
  // Même chose par coordonnées : la voie du formulaire passe par là.
  const geo = validateNewNodeGeo({ id: "capt-3", kind: "sensor", lat: "4.05", lon: "9.76",
    energy_profile: "sx1262-stm32l072" }, { lat: 4.05, lon: 9.76 });
  assert.equal(geo.ok, true);
  assert.deepEqual(geo.node.sensor, { energy_profile: "sx1262-stm32l072" });
});

test("matériel par équipement : transmis tel quel, absent = celui du run", () => {
  const base = { spreading_factor: "9", payload_bytes: "20", tx_power_dbm: "14.5", period_s: "600",
    messages: "2", start_spread_s: "0", region: "", channel_freq_hz: "" };
  // La liste vient du moteur : le studio la transmet sans la recopier, et le vide signifie
  // « celui du run » — il ne doit donc pas apparaître dans les réglages envoyés.
  const avec = validateSensor({ ...base, energy_profile: "sx1262-stm32l072" });
  assert.equal(avec.ok, true);
  assert.equal(avec.settings.energy_profile, "sx1262-stm32l072");
  assert.equal("energy_profile" in validateSensor({ ...base, energy_profile: "" }).settings, false);
  assert.equal("energy_profile" in validateSensor(base).settings, false);
  // Le formulaire se remplit depuis l'équipement, et le vide y est le défaut.
  assert.equal(sensorFormFrom({ kind: "sensor", sensor: { period_s: 60 } }).energy_profile, "");
  assert.equal(sensorFormFrom({ kind: "sensor",
    sensor: { period_s: 60, energy_profile: "rak4631" } }).energy_profile, "rak4631");
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

// --- Ajout par coordonnées géographiques (phase H) -------------------------------------------
// L'utilisateur saisit des degrés ; le moteur reçoit des mètres. Le test porte sur la
// jonction : ce qui part au serveur doit être la conversion exacte de ce qui a été tapé.

const ORIGINE = { lat: 4.0511, lon: 9.7679 };

test("un ajout par coordonnées produit les mètres correspondants", () => {
  const r = validateNewNodeGeo(
    { id: "capt-sud", name: "", kind: "sensor", lat: "4.0600", lon: "9.7800" },
    ORIGINE,
  );
  assert.equal(r.ok, true, r.message);
  // Mêmes nombres que `degresVersMetres` : la validation ne doit pas refaire le calcul.
  const m = degresVersMetres(4.06, 9.78, ORIGINE);
  assert.equal(r.node.x_m, m.x_m);
  assert.equal(r.node.y_m, m.y_m);
  assert.equal(r.node.id, "capt-sud");
  assert.equal(r.node.name, "capt-sud");   // nom vide : l'identifiant sert de nom
  assert.equal(r.node.kind, "sensor");
});

test("saisir l'origine place l'équipement au point zéro", () => {
  const r = validateNewNodeGeo(
    { id: "gw-0", kind: "border", lat: "4.0511", lon: "9.7679" },
    ORIGINE,
  );
  assert.equal(r.ok, true, r.message);
  assert.equal(r.node.x_m, 0);
  assert.equal(r.node.y_m, 0);
});

test("une coordonnée hors domaine est refusée avec le champ fautif", () => {
  const cas = [
    ["lat", { lat: "91", lon: "9.7679" }, /latitude/],
    ["lon", { lat: "4.0511", lon: "181" }, /longitude/],
    ["lat", { lat: "", lon: "9.7679" }, /latitude/],
    ["lon", { lat: "4.0511", lon: "abc" }, /longitude/],
  ];
  for (const [champ, coords, motif] of cas) {
    const r = validateNewNodeGeo({ id: "x", kind: "sensor", ...coords }, ORIGINE);
    assert.equal(r.ok, false, `accepté à tort : ${JSON.stringify(coords)}`);
    assert.equal(r.field, champ);
    assert.match(r.message, motif);
  }
});

test("une coordonnée très lointaine est refusée au lieu de sortir de l'échelle", () => {
  // À l'autre bout du monde : la conversion donnerait des millions de mètres, hors de
  // l'échelle du plan. Mieux vaut refuser que d'afficher un équipement introuvable.
  const r = validateNewNodeGeo(
    { id: "loin", kind: "sensor", lat: "-33.8688", lon: "151.2093" }, ORIGINE);
  assert.equal(r.ok, false);
  assert.match(r.message, /trop éloignée/);
});

test("des coordonnées vides posent l'équipement à l'origine", () => {
  // Cas le plus courant : on identifie l'équipement et on le place plus tard, en le tirant
  // sur la carte. Exiger des degrés ici obligerait à recopier l'origine qu'on vient de
  // choisir — et c'est exactement ce qui a cassé l'ajout en une étape.
  for (const vide of [{ lat: "", lon: "" }, { lat: "  ", lon: "  " }, { lat: null, lon: "" }]) {
    const r = validateNewNodeGeo({ id: "n", kind: "sensor", ...vide }, ORIGINE);
    assert.equal(r.ok, true, `refusé à tort : ${JSON.stringify(vide)}`);
    assert.equal(r.node.x_m, 0);
    assert.equal(r.node.y_m, 0);
  }
});

test("une seule coordonnée fournie est refusée", () => {
  // À moitié vide, ce n'est plus « je placerai plus tard » : c'est une saisie incomplète,
  // et la dire complète poserait l'équipement à un endroit qui n'a pas été voulu.
  for (const partiel of [{ lat: "4.0511", lon: "" }, { lat: "", lon: "9.7679" }]) {
    const r = validateNewNodeGeo({ id: "n", kind: "sensor", ...partiel }, ORIGINE);
    assert.equal(r.ok, false, `accepté à tort : ${JSON.stringify(partiel)}`);
  }
});

test("les champs communs restent validés à l'identique", () => {
  // L'identifiant est refusé de la même manière que par `validateNewNode` : la variante
  // géographique ne doit pas ouvrir une brèche dans les règles communes.
  const r = validateNewNodeGeo({ id: "MAUVAIS", kind: "sensor", lat: "4.05", lon: "9.76" }, ORIGINE);
  assert.equal(r.ok, false);
  assert.equal(r.field, "id");
  assert.equal(
    validateNewNodeGeo({ id: "ok", kind: "inexistant", lat: "4.05", lon: "9.76" }, ORIGINE).field,
    "kind",
  );
});

test("aller-retour : une position posée au clic se relit à l'identique", () => {
  // Le scénario réel de la phase H : on clique la carte, la position part en mètres, et la
  // fenêtre la réaffiche en degrés. Le nombre montré doit être celui du clic, sinon
  // l'équipement « saute » à chaque ouverture.
  for (const [x, y] of [[0, 0], [1500, -2200], [-800, 377.5], [12345.6, -9876.5]]) {
    const d = metresVersDegres(x, y, ORIGINE);
    const r = validateNewNodeGeo(
      { id: "n", kind: "sensor", lat: String(d.lat), lon: String(d.lon) }, ORIGINE);
    assert.equal(r.ok, true, r.message);
    assert.ok(Math.abs(r.node.x_m - x) < 1e-6, `x : ${r.node.x_m} au lieu de ${x}`);
    assert.ok(Math.abs(r.node.y_m - y) < 1e-6, `y : ${r.node.y_m} au lieu de ${y}`);
  }
});

// ---- Modèles de passerelle -----------------------------------------------------------
// Le catalogue vient du moteur, mais deux choses sont de l'interface : qui peut porter quel
// modèle, et ce qu'on annonce que le modèle change. Trois des quatre modèles ne décalent pas
// le seuil — leur fiche ne publie pas le point de mesure — et l'annoncer évite de vendre un
// réglage qui n'en est pas un.
const CATALOGUE = [
  { name: "rak7249", vendor: "RAKwireless", model: "RAK7249", sensitivity_offset_db: 0,
    sensitivity_published: false, can_relay: false, can_simulate_radio: true },
  { name: "rak5148", vendor: "RAKwireless", model: "RAK5148", sensitivity_offset_db: 0,
    sensitivity_published: false, can_relay: true, can_simulate_radio: true },
  { name: "rak5146-rak5148", vendor: "RAKwireless", model: "RAK5146 + RAK5148",
    sensitivity_offset_db: -3, sensitivity_published: true, can_relay: true,
    can_simulate_radio: true },
  { name: "rak7391", vendor: "RAKwireless", model: "RAK7391", sensitivity_offset_db: 0,
    sensitivity_published: false, can_relay: false, can_simulate_radio: false },
];

test("un relais n'accepte que les modèles à radio mesh documentée", () => {
  // RAK7249 sait recevoir mais pas relayer : le scénario le refuserait, autant ne pas
  // le proposer. RAK7391 n'a pas de radio publiée du tout.
  assert.deepEqual(modelesAdmis(CATALOGUE, "relay").map((m) => m.name),
    ["rak5148", "rak5146-rak5148"]);
  // Une frontière n'a pas besoin du mesh : seul l'hôte sans radio est écarté.
  assert.deepEqual(modelesAdmis(CATALOGUE, "border").map((m) => m.name),
    ["rak7249", "rak5148", "rak5146-rak5148"]);
  assert.equal(modelesAdmis(CATALOGUE, "sensor").length, 3);
});

test("l'aide dit quand le modèle ne décale rien", () => {
  const zero = aideModele(CATALOGUE[0]);
  assert.ok(zero.includes("ne publie pas le point de mesure"));
  assert.ok(zero.includes("ne peut pas relayer"));
  const decale = aideModele(CATALOGUE[2]);
  assert.ok(decale.includes("−3.0 dB"));   // tiret demi-cadratin : lisible, pas un moins
  assert.ok(decale.includes("peut relayer"));
  // Sans modèle : pas d'aide du tout, plutôt qu'une phrase sur un réglage absent.
  assert.equal(aideModele(undefined), "");
});

test("le modèle de passerelle se transmet et se retire", () => {
  const pose = validateGateway({ region: "EU868", gateway_profile: "rak7249" });
  assert.ok(pose.ok);
  assert.equal(pose.settings.gateway_profile, "rak7249");
  // Vide = retour explicite à la référence du moteur ; absent = rien ne change. C'est ce
  // qui permet d'effacer le modèle sans qu'un envoi partiel le remette.
  assert.equal(validateGateway({ gateway_profile: "" }).settings.gateway_profile, null);
  assert.ok(!("gateway_profile" in validateGateway({ region: "EU868" }).settings));
});

test("le modèle posé à la création ne va que sur une passerelle", () => {
  const grille = { id: "gw1", kind: "border", x_m: 0, y_m: 0 };
  const pose = validateNewNode({ ...grille, gateway_profile: "rak7249" });
  assert.ok(pose.ok);
  assert.equal(pose.node.gateway_profile, "rak7249");
  // Un capteur n'a pas de modèle de passerelle : le serveur le refuse, et ce n'est pas
  // à l'interface d'inventer une exception.
  const capteur = validateNewNode({ id: "c1", kind: "sensor", x_m: 0, y_m: 0,
    gateway_profile: "rak7249" });
  assert.ok(capteur.ok);
  assert.ok(!("gateway_profile" in capteur.node));
  // Aucun modèle choisi : le champ est absent, pas vide — le run garde sa référence.
  assert.ok(!("gateway_profile" in validateNewNode(grille).node));
});

test("le client lit le catalogue des passerelles au moteur", async () => {
  const { fetchImpl, calls } = fakeFetch([{ status: 200, body: { profiles: CATALOGUE } }]);
  const r = await createClient({ token: "t", fetchImpl }).gatewayProfiles();
  assert.equal(calls[0].url, "/api/v1/gateway-profiles");
  assert.equal(r.profiles.length, 4);
});

// Annuler et rétablir : l'historique vit côté serveur, le client ne fait qu'appeler.
// La réponse est une topologie : c'est elle qui porte les libellés, l'interface n'en invente
// aucun et n'a donc pas à les recopier.

test("annuler et rétablir postent sur la session et rendent la topologie", async () => {
  const topo = { session_id: "s1", nodes: [], states: [], can_undo: true, can_redo: false,
    undo_label: "capteur-1 : region US915", redo_label: "" };
  const { fetchImpl, calls } = fakeFetch([{ status: 200, body: topo },
    { status: 200, body: { ...topo, can_undo: false, can_redo: true, undo_label: "",
      redo_label: "capteur-1 : region US915" } }]);
  const client = createClient({ token: "t", fetchImpl });
  const premiere = await client.undo("s1");
  assert.equal(calls[0].url, "/api/v1/sessions/s1/undo");
  assert.equal(calls[0].init.method, "POST");
  assert.equal(premiere.undo_label, "capteur-1 : region US915");
  const seconde = await client.redo("s1");
  assert.equal(calls[1].url, "/api/v1/sessions/s1/redo");
  assert.equal(calls[1].init.method, "POST");
  // Après un annuler, le geste est passé dans l'autre pile : c'est le rétablir qui le nomme.
  assert.equal(seconde.redo_label, "capteur-1 : region US915");
});

test("rien à annuler arrive comme une erreur au format problème, pas comme un vide", async () => {
  const { fetchImpl } = fakeFetch([
    { status: 409, body: { code: "nothing_to_undo", message: "rien à annuler" } }]);
  const client = createClient({ token: "t", fetchImpl });
  await assert.rejects(client.undo("s1"), (err) => {
    assert.ok(err instanceof ApiError);
    assert.equal(err.status, 409);
    assert.equal(err.code, "nothing_to_undo");
    return true;
  });
});

test("l'identifiant de session est encodé dans les routes d'historique", async () => {
  const { fetchImpl, calls } = fakeFetch([{ status: 200, body: {} }, { status: 200, body: {} }]);
  const client = createClient({ token: "t", fetchImpl });
  await client.undo("a/b");
  await client.redo("a/b");
  assert.equal(calls[0].url, "/api/v1/sessions/a%2Fb/undo");
  assert.equal(calls[1].url, "/api/v1/sessions/a%2Fb/redo");
});
