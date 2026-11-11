// Tests du module chantier : écriture, lecture, et surtout refus.
//
// Le refus est la partie la plus testée, et c'est voulu. Un chantier accepté à tort produit une
// session à moitié construite, qui a l'air correcte et ne l'est pas ; un chantier refusé à tort
// coûte un message. La charge de la preuve est du côté de l'acceptation.

import test from "node:test";
import assert from "node:assert/strict";
import { ChantierInvalide, FORMAT, MAX_EQUIPEMENTS, VERSION,
         lireChantier, nomFichier, serialiserChantier } from "../src/studio/chantier.js";

const TOPO = {
  session_id: "abcdefghijkl",
  nodes: [
    { id: "gw-nord", kind: "border", name: "Passerelle nord", x_m: 0, y_m: 0, sensor: null },
    { id: "capt-1", kind: "sensor", name: "Capteur 1", x_m: 120, y_m: -40,
      sensor: { spreading_factor: 9, payload_bytes: 12, tx_power_dbm: 14,
                period_s: 300, messages: 6, start_spread_s: 30, region: null,
                channel_freq_hz: null } },
  ],
  states: [
    { node_id: "gw-nord", hostname: "gw-nord", region: "EU868", configured: true,
      keys: "******",
      gateway: { region: "EU868", sub_band: null, tx_power_dbm: 14,
                 mesh_mode: "relay", mesh_max_hops: 3 } },
    { node_id: "capt-1", hostname: "capteur-1", region: null, configured: false,
      keys: null, gateway: null },
  ],
};

const ORIGINE = { lat: 4.0511, lon: 9.7679 };

function topoAvecRelief(terrainId) {
  return { ...TOPO, terrain_id: terrainId };
}

function ecrire(chantier) {
  return JSON.stringify(chantier);
}

// --- Écriture --------------------------------------------------------------------------------

test("un chantier porte le format, la version, l'origine et les équipements", () => {
  const c = serialiserChantier({ topo: TOPO, origine: ORIGINE });
  assert.equal(c.format, FORMAT);
  assert.equal(c.version, VERSION);
  assert.deepEqual(c.origine, ORIGINE);
  assert.equal(c.equipements.length, 2);
});

test("les positions sont en mètres, pas en degrés : D2 et D3", () => {
  const c = serialiserChantier({ topo: TOPO, origine: ORIGINE });
  const capt = c.equipements.find((e) => e.id === "capt-1");
  assert.equal(capt.x_m, 120);
  assert.equal(capt.y_m, -40);
  // L'origine n'est pas absorbée dans les positions : changer de zone doit déplacer le chantier.
  assert.equal(c.origine.lat, ORIGINE.lat);
});

test("aucune clé n'atteint le fichier, même masquée", () => {
  const texte = ecrire(serialiserChantier({ topo: TOPO, origine: ORIGINE }));
  assert.ok(!texte.includes("******"));
  assert.ok(!/"keys"/.test(texte));
});

test("un chantier sans origine reste écrit, avec une origine nulle", () => {
  const c = serialiserChantier({ topo: TOPO, origine: null });
  assert.equal(c.origine, null);
  assert.equal(c.equipements.length, 2);
});

test("le nom d'hôte n'est écrit que s'il diffère de l'identifiant", () => {
  const c = serialiserChantier({ topo: TOPO, origine: ORIGINE });
  const gw = c.equipements.find((e) => e.id === "gw-nord");
  const capt = c.equipements.find((e) => e.id === "capt-1");
  assert.equal(gw.hostname, undefined);        // hostname == id : le défaut le restaure
  assert.equal(capt.hostname, "capteur-1");    // renommé : à restaurer explicitement
});

test("un capteur emporte ses réglages, une passerelle les siens", () => {
  const c = serialiserChantier({ topo: TOPO, origine: ORIGINE });
  const capt = c.equipements.find((e) => e.id === "capt-1");
  const gw = c.equipements.find((e) => e.id === "gw-nord");
  assert.equal(capt.sensor.spreading_factor, 9);
  assert.equal(capt.sensor.messages, 6);
  assert.equal(gw.gateway.region, "EU868");
  assert.equal(gw.gateway.mesh_max_hops, 3);
});

test("les réglages à null ne sont pas écrits : un fichier se lit", () => {
  const c = serialiserChantier({ topo: TOPO, origine: ORIGINE });
  const capt = c.equipements.find((e) => e.id === "capt-1");
  assert.ok(!("region" in capt.sensor));
  assert.ok(!("channel_freq_hz" in capt.sensor));
  const gw = c.equipements.find((e) => e.id === "gw-nord");
  assert.ok(!("sub_band" in gw.gateway));
});

// --- Aller-retour ----------------------------------------------------------------------------

test("un chantier écrit se relit sans rien perdre", () => {
  // L'aller-retour n'est pas identique octet pour octet, et c'est voulu : l'écrivain omet un
  // champ vide pour que le fichier se lise, le lecteur le normalise en `null` pour que
  // l'importateur puisse compter sur le champ. Ce qui doit être conservé, c'est le sens —
  // c'est cela que ce test vérifie.
  const ecrit = serialiserChantier({ topo: TOPO, origine: ORIGINE });
  const relu = lireChantier(ecrire(ecrit));
  assert.deepEqual(relu.origine, ecrit.origine);
  assert.equal(relu.equipements.length, ecrit.equipements.length);
  for (const [i, attendu] of ecrit.equipements.entries()) {
    const obtenu = relu.equipements[i];
    assert.equal(obtenu.id, attendu.id);
    assert.equal(obtenu.kind, attendu.kind);
    assert.equal(obtenu.name, attendu.name);
    assert.equal(obtenu.x_m, attendu.x_m);
    assert.equal(obtenu.y_m, attendu.y_m);
    assert.deepEqual(obtenu.sensor, attendu.sensor ?? null);
    assert.deepEqual(obtenu.gateway, attendu.gateway ?? null);
    assert.equal(obtenu.hostname, attendu.hostname ?? null);
  }
});

test("le lecteur normalise les réglages absents en null, pas en undefined", () => {
  // L'importateur doit pouvoir écrire `if (eq.hostname)` sans se demander si la clé existe.
  const c = lireChantier(ecrire({ format: FORMAT, version: VERSION, origine: null,
    equipements: [{ id: "e-1", kind: "server", name: "S", x_m: 0, y_m: 0 }] }));
  assert.equal(c.equipements[0].sensor, null);
  assert.equal(c.equipements[0].gateway, null);
  assert.equal(c.equipements[0].hostname, null);
});

// --- Refus -----------------------------------------------------------------------------------

function refuse(texte, motif) {
  assert.throws(() => lireChantier(texte),
    (e) => {
      assert.ok(e instanceof ChantierInvalide, `attendu ChantierInvalide, reçu ${e}`);
      assert.ok(e.message.includes(motif), `message « ${e.message} » sans « ${motif} »`);
      return true;
    });
}

test("du texte qui n'est pas du JSON est refusé", () => {
  refuse("ceci n'est pas un fichier", "JSON");
});

test("un JSON valide qui n'est pas un chantier est refusé", () => {
  refuse('{"a": 1}', "ne contient pas un chantier");
  refuse("[1, 2, 3]", "ne contient pas un chantier");
});

test("un format inconnu est nommé dans le refus", () => {
  refuse('{"format": "autre", "version": 1, "equipements": []}', "autre");
});

test("une version future est refusée en disant laquelle est lue", () => {
  refuse(`{"format": "${FORMAT}", "version": 99, "equipements": []}`, "99");
});

test("une liste d'équipements absente est refusée", () => {
  refuse(`{"format": "${FORMAT}", "version": 1}`, "équipements");
});

test("trop d'équipements est refusé avant toute création", () => {
  const trop = Array.from({ length: MAX_EQUIPEMENTS + 1 }, (_, i) => ({
    id: `e-${i}`, kind: "sensor", name: `E ${i}`, x_m: 0, y_m: 0 }));
  refuse(ecrire({ format: FORMAT, version: VERSION, origine: null, equipements: trop }),
    `${MAX_EQUIPEMENTS + 1}`);
});

test("un identifiant invalide est refusé en le citant", () => {
  refuse(ecrire({ format: FORMAT, version: VERSION, origine: null,
    equipements: [{ id: "MAJUSCULES", kind: "sensor", name: "E", x_m: 0, y_m: 0 }] }),
    "MAJUSCULES");
});

test("un type inconnu est refusé en citant les types attendus", () => {
  refuse(ecrire({ format: FORMAT, version: VERSION, origine: null,
    equipements: [{ id: "e-1", kind: "switch", name: "E", x_m: 0, y_m: 0 }] }),
    "switch");
});

test("une position non finie est refusée", () => {
  refuse(ecrire({ format: FORMAT, version: VERSION, origine: null,
    equipements: [{ id: "e-1", kind: "sensor", name: "E", x_m: null, y_m: 0 }] }),
    "x_m");
});

test("une position hors bornes est refusée", () => {
  refuse(ecrire({ format: FORMAT, version: VERSION, origine: null,
    equipements: [{ id: "e-1", kind: "sensor", name: "E", x_m: 2_000_000, y_m: 0 }] }),
    "x_m");
});

test("une origine hors du monde est refusée : 400 n'est pas une latitude", () => {
  refuse(ecrire({ format: FORMAT, version: VERSION, origine: { lat: 400, lon: 0 },
    equipements: [] }), "origine");
});

test("des réglages capteur sur une passerelle sont refusés", () => {
  refuse(ecrire({ format: FORMAT, version: VERSION, origine: null,
    equipements: [{ id: "e-1", kind: "border", name: "E", x_m: 0, y_m: 0,
      sensor: { period_s: 60 } }] }), "capteur");
});

test("un facteur d'étalement hors bornes est refusé", () => {
  refuse(ecrire({ format: FORMAT, version: VERSION, origine: null,
    equipements: [{ id: "e-1", kind: "sensor", name: "E", x_m: 0, y_m: 0,
      sensor: { spreading_factor: 42 } }] }), "spreading_factor");
});

test("une période nulle est refusée : un capteur muet ne se voit pas", () => {
  refuse(ecrire({ format: FORMAT, version: VERSION, origine: null,
    equipements: [{ id: "e-1", kind: "sensor", name: "E", x_m: 0, y_m: 0,
      sensor: { period_s: 0 } }] }), "period_s");
});

test("une région inconnue est refusée", () => {
  refuse(ecrire({ format: FORMAT, version: VERSION, origine: null,
    equipements: [{ id: "e-1", kind: "border", name: "E", x_m: 0, y_m: 0,
      gateway: { region: "ZZ999" } }] }), "ZZ999");
});

test("un équipement sans réglage est accepté : on le pose, c'est tout", () => {
  const c = lireChantier(ecrire({ format: FORMAT, version: VERSION, origine: null,
    equipements: [{ id: "e-1", kind: "server", name: "Serveur", x_m: 0, y_m: 0 }] }));
  assert.equal(c.equipements[0].sensor, null);
  assert.equal(c.equipements[0].gateway, null);
});

// --- Nom de fichier --------------------------------------------------------------------------

test("le nom de fichier est daté et porte un repère de session", () => {
  const nom = nomFichier("abcdefghijkl", new Date(2026, 2, 5));
  assert.equal(nom, "chantier-abcdefgh-20260305.json");
});

test("le nom de fichier tient sans session", () => {
  assert.match(nomFichier(null, new Date(2026, 2, 5)), /^chantier-session-\d{8}\.json$/);
});

// --- Relief ----------------------------------------------------------------------------------

test("un chantier sans relief ecrit un terrain_id nul", () => {
  const c = serialiserChantier({ topo: TOPO, origine: ORIGINE });
  assert.equal(c.terrain_id, null);
});

test("le relief choisi fait partie du chantier : c'est le terrain, pas un decor", () => {
  const c = serialiserChantier({ topo: topoAvecRelief("crete"), origine: ORIGINE });
  assert.equal(c.terrain_id, "crete");
  assert.equal(lireChantier(ecrire(c)).terrain_id, "crete");
});

test("un identifiant de relief invalide est refuse en le citant", () => {
  refuse(ecrire({ format: FORMAT, version: VERSION, origine: null,
    terrain_id: "../../etc/passwd", equipements: [] }), "../../etc/passwd");
});

// --- Modèle de passerelle --------------------------------------------------------------------
// Le seuil de réception se choisit à la pose ; un chantier qui ne le porte pas repart à la
// référence du moteur sans rien dire.

test("le modele d'une passerelle fait partie du chantier", () => {
  const topo = { ...TOPO,
    nodes: TOPO.nodes.map((n) => (n.kind === "border"
      ? { ...n, gateway_profile: "rak5146-rak5148" } : n)) };
  const c = serialiserChantier({ topo, origine: ORIGINE });
  const gw = c.equipements.find((e) => e.id === "gw-nord");
  assert.equal(gw.gateway_profile, "rak5146-rak5148");
  assert.equal(lireChantier(ecrire(c)).equipements[0].gateway_profile, "rak5146-rak5148");
});

test("une passerelle sans modele n'ecrit rien : le chantier reste celui d'avant", () => {
  const c = serialiserChantier({ topo: TOPO, origine: ORIGINE });
  assert.ok(!("gateway_profile" in c.equipements[0]));
});

// --- Obstacles et environnement ---------------------------------------------------------------

const MUR = { x_min_m: 400, y_min_m: -300, x_max_m: 600, y_max_m: 300,
              height_m: 12, attenuation_db: 6 };

test("un environnement vierge n'ecrit rien : le fichier reste celui d'avant", () => {
  const c = serialiserChantier({ topo: { ...TOPO, environment: {
    shadowing_sigma_db: 0, gateway_height_m: 15, device_height_m: 1.5, obstacles: [] } },
    origine: ORIGINE });
  assert.ok(!("environment" in c), Object.keys(c).join(", "));
});

test("les murs et le shadowing font partie du chantier, et se relisent", () => {
  const c = serialiserChantier({ topo: { ...TOPO, environment: {
    shadowing_sigma_db: 4, gateway_height_m: 40, device_height_m: 1.5,
    obstacles: [MUR] } }, origine: ORIGINE });
  assert.equal(c.environment.shadowing_sigma_db, 4);
  assert.equal(c.environment.gateway_height_m, 40);
  assert.deepEqual(c.environment.obstacles[0], MUR);
  const relu = lireChantier(ecrire(c)).environment;
  assert.deepEqual(relu.obstacles[0], MUR);
  assert.equal(relu.gateway_height_m, 40);
});

test("un mur en materiau garde le materiau, pas une attenuation", () => {
  const mur = { ...MUR, material: "concrete", thickness_m: 0.2 };
  delete mur.attenuation_db;
  const c = serialiserChantier({ topo: { ...TOPO, environment: {
    shadowing_sigma_db: 0, gateway_height_m: 15, device_height_m: 1.5,
    obstacles: [mur] } }, origine: ORIGINE });
  const relu = lireChantier(ecrire(c)).environment.obstacles[0];
  assert.equal(relu.material, "concrete");
  assert.ok(!("attenuation_db" in relu));
});

test("un mur a l'emprise vide est refuse en disant lequel", () => {
  const texte = ecrire({ format: FORMAT, version: VERSION, origine: null,
    environment: { obstacles: [{ x_min_m: 10, y_min_m: 0, x_max_m: 10, y_max_m: 5,
                                 height_m: 12, attenuation_db: 6 }] },
    equipements: [] });
  assert.throws(() => lireChantier(texte), (err) => {
    assert.ok(err instanceof ChantierInvalide);
    assert.match(err.message, /obstacle nº 1 : emprise vide/);
    return true;
  });
});

test("un mur qui porte a la fois une attenuation et un materiau est refuse", () => {
  const texte = ecrire({ format: FORMAT, version: VERSION, origine: null,
    environment: { obstacles: [{ ...MUR, material: "concrete", thickness_m: 0.2 }] },
    equipements: [] });
  assert.throws(() => lireChantier(texte), /atténuation et matériau s'excluent/);
});

test("une attenuation hors bornes est refusee", () => {
  const texte = ecrire({ format: FORMAT, version: VERSION, origine: null,
    environment: { obstacles: [{ ...MUR, attenuation_db: 500 }] }, equipements: [] });
  assert.throws(() => lireChantier(texte), /atténuation hors bornes/);
});
