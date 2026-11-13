// Tests de la zone de couverture et du diagramme d'antenne (sans DOM, sans Cesium).
// Lancer : `npm test` depuis web/.
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  COULEURS_QUALITE, QUALITES, anneauZone, attenuationLobeDb, contourLobe, etiquetteModele,
  etiquettePalier, facteurLobe, porteeMax,
} from "../src/studio/zone.js";

const UNI = { kind: "unidirectionnelle", beamwidth_deg: 90, pointing_deg: 0,
  front_to_back_db: 20 };
const SECTEUR = { kind: "sectorielle", beamwidth_deg: 120, pointing_deg: 0,
  front_to_back_db: 30 };

// ------------------------------------------------------------ diagramme

test("une omnidirectionnelle ne perd rien, quels que soient ses réglages", () => {
  // Une omni ne doit pas être refusée pour un réglage sans effet : l'exiger serait
  // un piège pour une antenne parfaitement valide.
  const omni = { kind: "omnidirectionnelle", beamwidth_deg: 1, pointing_deg: 200,
    front_to_back_db: 60 };
  for (let a = 0; a < 360; a += 13) assert.equal(attenuationLobeDb(omni, a), 0);
});

test("−3 dB à mi-ouverture : la convention qui fixe la pente", () => {
  for (const w of [30, 60, 90, 120]) {
    const a = { kind: "unidirectionnelle", beamwidth_deg: w, pointing_deg: 0,
      front_to_back_db: 60 };
    assert.ok(Math.abs(attenuationLobeDb(a, w / 2) - 3) < 1e-9);
    assert.ok(Math.abs(attenuationLobeDb(a, -w / 2) - 3) < 1e-9);
    assert.ok(Math.abs(attenuationLobeDb(a, w) - 12) < 1e-9);
  }
});

test("l'affaiblissement arrière est un plancher, pas une pente", () => {
  const a = { kind: "unidirectionnelle", beamwidth_deg: 60, pointing_deg: 0,
    front_to_back_db: 20 };
  assert.equal(attenuationLobeDb(a, 180), 20);
  // 90° vaudrait 27 dB sans le plancher : c'est bien lui qui écrête.
  assert.equal(attenuationLobeDb(a, 90), 20);
  const large = { ...a, front_to_back_db: 45 };
  assert.ok(Math.abs(attenuationLobeDb(large, 90) - 27) < 1e-9);
});

test("une bidirectionnelle a deux lobes opposés", () => {
  const a = { kind: "bidirectionnelle", beamwidth_deg: 60, pointing_deg: 0,
    front_to_back_db: 30 };
  assert.equal(attenuationLobeDb(a, 0), 0);
  assert.equal(attenuationLobeDb(a, 180), 0);      // le dos est un axe
  assert.ok(Math.abs(attenuationLobeDb(a, 90) - 27) < 1e-9);
  for (let d = 0; d < 180; d += 11) {
    assert.ok(Math.abs(attenuationLobeDb(a, d) - attenuationLobeDb(a, d + 180)) < 1e-9);
  }
});

test("une sectorielle a un sommet plat, une directive non", () => {
  for (const w of [60, 90, 120]) {
    const s = { kind: "sectorielle", beamwidth_deg: w, pointing_deg: 0, front_to_back_db: 30 };
    assert.equal(attenuationLobeDb(s, w / 2), 0);      // bord du secteur : au sommet
    assert.ok(Math.abs(attenuationLobeDb(s, w) - 3) < 1e-9);
    const u = { kind: "unidirectionnelle", beamwidth_deg: w, pointing_deg: 0,
      front_to_back_db: 30 };
    assert.ok(Math.abs(attenuationLobeDb(u, w / 2) - 3) < 1e-9);   // elle, décroît dès l'axe
  }
});

test("les azimuts sont ramenés à un tour, dans les deux sens", () => {
  for (let a = 0; a < 360; a += 17) {
    assert.ok(Math.abs(attenuationLobeDb(UNI, a) - attenuationLobeDb(UNI, a + 360)) < 1e-9);
    assert.ok(Math.abs(attenuationLobeDb(UNI, a) - attenuationLobeDb(UNI, a - 720)) < 1e-9);
  }
  // Pointage à 370° = pointage à 10°.
  const p = { ...UNI, pointing_deg: 370 };
  const q = { ...UNI, pointing_deg: 10 };
  for (let a = 0; a < 360; a += 19) {
    assert.ok(Math.abs(attenuationLobeDb(p, a) - attenuationLobeDb(q, a)) < 1e-9);
  }
});

test("une antenne inexploitable est signalée, pas dégradée en silence", () => {
  assert.equal(attenuationLobeDb({ kind: "paraboloide" }, 0), null);
  assert.equal(attenuationLobeDb(UNI, NaN), null);
  assert.equal(attenuationLobeDb({ ...UNI, beamwidth_deg: 0 }, 0), null);
  // Sans antenne du tout : omnidirectionnelle implicite.
  assert.equal(attenuationLobeDb(null, 37), 0);
  assert.equal(attenuationLobeDb(undefined, 37), 0);
});

test("le facteur de forme vaut 1 sur l'axe et décroît ailleurs", () => {
  assert.equal(facteurLobe(UNI, 0), 1);
  assert.ok(facteurLobe(UNI, 45) > 0.4 && facteurLobe(UNI, 45) < 0.6);   // −3 dB
  assert.ok(facteurLobe(UNI, 180) < 0.02);                                // −20 dB
  for (let a = 0; a < 360; a += 7) {
    const f = facteurLobe(UNI, a);
    assert.ok(f >= 0 && f <= 1);
  }
});

// ------------------------------------------------------------ contours

test("le contour du lobe part de l'axe et meurt dans le dos", () => {
  const c = contourLobe(UNI, { x_m: 0, y_m: 0 }, 100, 180);
  assert.equal(c.length, 181);                    // fermé
  assert.equal(c[0].x, c[180].x);
  // index 0 = est = axe du lobe : à pleine échelle.
  assert.ok(Math.abs(Math.hypot(c[0].x, c[0].y) - 100) < 1e-6);
  // index 90 = ouest = dos : bien plus court.
  assert.ok(Math.hypot(c[90].x, c[90].y) < 20);
});

test("un contour de secteur garde toute sa largeur à pleine échelle", () => {
  const c = contourLobe(SECTEUR, { x_m: 0, y_m: 0 }, 100, 360);
  // ±60° autour de l'est : indices 0, 60 et 300 (pas de 1°).
  for (const k of [0, 60, 300]) {
    assert.ok(Math.abs(Math.hypot(c[k].x, c[k].y) - 100) < 1e-6, `indice ${k}`);
  }
});

test("un contour n'est pas tracé sans échelle ni centre", () => {
  assert.deepEqual(contourLobe(UNI, { x_m: 0, y_m: 0 }, 0), []);
  assert.deepEqual(contourLobe(UNI, { x_m: NaN, y_m: 0 }, 100), []);
});

// ------------------------------------------------------------ zone du moteur

test("l'anneau de zone est fermé et centré sur la passerelle", () => {
  const anneau = anneauZone({ radii_m: [100, 100, 100, 100], qualite: "limite" },
    { x_m: 10, y_m: 20 });
  assert.equal(anneau.length, 5);
  assert.deepEqual(anneau[0], anneau[4]);
  assert.ok(Math.abs(anneau[0].x - 110) < 1e-9);      // est
  assert.ok(Math.abs(anneau[1].y - 120) < 1e-9);      // nord
  assert.ok(Math.abs(anneau[2].x - -90) < 1e-9);      // ouest
});

test("une zone inexploitable n'est pas tracée", () => {
  assert.deepEqual(anneauZone({ radii_m: [] }, { x_m: 0, y_m: 0 }), []);
  assert.deepEqual(anneauZone({ radii_m: [1, 2] }, { x_m: NaN, y_m: 0 }), []);
  // Un rayon non fini : mieux vaut ne rien tracer qu'un anneau troué.
  assert.deepEqual(anneauZone({ radii_m: [1, NaN, 3] }, { x_m: 0, y_m: 0 }), []);
});

test("la portée maximale cadre la vue", () => {
  assert.equal(porteeMax({ paliers: [{ radii_m: [1, 2] }, { radii_m: [5, 9] }] }), 9);
  assert.equal(porteeMax({ paliers: [] }), null);
  assert.equal(porteeMax(null), null);
});

// ------------------------------------------------------------ libellés

test("les libellés disent ce qu'ils mesurent", () => {
  assert.equal(QUALITES.length, 3);
  for (const q of QUALITES) assert.ok(COULEURS_QUALITE[q], `couleur manquante : ${q}`);
  assert.match(etiquettePalier({ qualite: "bon", marge_db: 10 }), /10 dB/);
  assert.match(etiquettePalier({ qualite: "limite", marge_db: 0 }), /marge nulle/);
  assert.equal(etiquetteModele("environment"), "relief et obstacles");
  assert.equal(etiquetteModele("log_distance"), "log-distance seul");
});
