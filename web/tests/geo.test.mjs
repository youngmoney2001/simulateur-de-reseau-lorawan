// La conversion mètres ↔ degrés est l'invariant D2 : degrés en façade, mètres au moteur.
// Si les deux côtés divergent, la carte dérive du plan sans que rien ne cloche visiblement —
// un équipement posé au clic n'est plus là où le moteur le calcule. D'où ces tests.
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  EARTH_RADIUS_M,
  metresVersDegres,
  degresVersMetres,
  lireCoordonnees,
  formaterCoordonnees,
  distanceM,
  estLatitude,
  estLongitude,
} from "../src/studio/geo.js";

const DOUALA = { lat: 4.0511, lon: 9.7679 };
const SYDNEY = { lat: -33.8688, lon: 151.2093 };

// Produites par `python/lsim/geo.py :: _to_lonlat`, seule fonction de conversion du serveur.
// Les reprendre telles quelles fait de ce test une vérification de parité, pas une
// reformulation de la formule qui tournerait juste avec elle-même.
const REFERENCE = [
  { origine: DOUALA, x: 0, y: 0, lon: 9.7679, lat: 4.0511 },
  { origine: DOUALA, x: 1500, y: -2200, lon: 9.781423613644945, lat: 4.031314924669788 },
  { origine: DOUALA, x: -800, y: 377.5, lon: 9.760687406056029, lat: 4.0544949390623435 },
  { origine: DOUALA, x: 12345.6, y: -9876.5, lon: 9.879204749743359, lat: 3.9622785015914364 },
  { origine: DOUALA, x: -50000, y: 50000, lon: 9.317112878501813, lat: 4.500760802959365 },
  { origine: SYDNEY, x: 1500, y: -2200, lon: 151.2255466170348, lat: -33.88858507533021 },
  { origine: SYDNEY, x: -800, y: 377.5, lon: 151.20063513758146, lat: -33.865405060937654 },
  { origine: SYDNEY, x: -50000, y: 50000, lon: 150.66774609884047, lat: -33.419139197040636 },
];

test("le rayon terrestre est celui du serveur", () => {
  assert.equal(EARTH_RADIUS_M, 6_371_000);
});

test("mètres vers degrés : parité bit à bit avec geo.py", () => {
  for (const r of REFERENCE) {
    const { lon, lat } = metresVersDegres(r.x, r.y, r.origine);
    // Strict : on compare les représentations littérales, pas à une tolérance près. Une
    // tolérance masquerait justement la lente dérive qu'on cherche à attraper.
    assert.equal(Object.is(lon, r.lon), true,
      `lon pour x=${r.x} : ${lon} au lieu de ${r.lon}`);
    assert.equal(Object.is(lat, r.lat), true,
      `lat pour y=${r.y} : ${lat} au lieu de ${r.lat}`);
  }
});

test("l'aller-retour mètres → degrés → mètres est exact", () => {
  const cas = [[0, 0], [1500, -2200], [-800, 377.5], [12345.6, -9876.5], [-50000, 50000]];
  for (const origine of [DOUALA, SYDNEY]) {
    for (const [x, y] of cas) {
      const { lon, lat } = metresVersDegres(x, y, origine);
      const m = degresVersMetres(lat, lon, origine);
      // Une erreur relative de 1e-9 sur 50 km reste sous le dixième de millimètre : c'est
      // l'épaisseur du trait sur la carte, donc invisible, et le test reste exigeant.
      const echelle = Math.max(1, Math.abs(x), Math.abs(y));
      assert.ok(Math.abs(m.x_m - x) / echelle < 1e-9,
        `x : ${m.x_m} au lieu de ${x}`);
      assert.ok(Math.abs(m.y_m - y) / echelle < 1e-9,
        `y : ${m.y_m} au lieu de ${y}`);
    }
  }
});

test("l'aller-retour degrés → mètres → degrés est exact", () => {
  const cas = [
    [4.0511, 9.7679], [4.0650, 9.7810], [4.0, 9.7],
    [-33.8688, 151.2093], [-33.9, 151.3],
  ];
  for (const origine of [DOUALA, SYDNEY]) {
    for (const [lat, lon] of cas) {
      const m = degresVersMetres(lat, lon, origine);
      const d = metresVersDegres(m.x_m, m.y_m, origine);
      assert.ok(Math.abs(d.lat - lat) < 1e-12, `lat : ${d.lat} au lieu de ${lat}`);
      assert.ok(Math.abs(d.lon - lon) < 1e-12, `lon : ${d.lon} au lieu de ${lon}`);
    }
  }
});

test("l'origine est le point fixe de la conversion", () => {
  for (const origine of [DOUALA, SYDNEY]) {
    const m = degresVersMetres(origine.lat, origine.lon, origine);
    assert.equal(m.x_m, 0);
    assert.equal(m.y_m, 0);
  }
});

// --- Saisie à la main -----------------------------------------------------------------------
// L'utilisateur entre ses coordonnées comme il les a : copiées d'un GPS, d'une carte, ou
// tapées au clavier français. Refuser la virgule décimale serait une rigidité gratuite.

test("la saisie accepte les formes courantes", () => {
  const cas = [
    ["4.0511, 9.7679", { lat: 4.0511, lon: 9.7679 }],
    ["4.0511 9.7679", { lat: 4.0511, lon: 9.7679 }],
    ["4.0511,9.7679", { lat: 4.0511, lon: 9.7679 }],
    [" 4.0511 , 9.7679 ", { lat: 4.0511, lon: 9.7679 }],
    ["4.0511° N, 9.7679° E", { lat: 4.0511, lon: 9.7679 }],
    ["-33.8688, 151.2093", { lat: -33.8688, lon: 151.2093 }],
  ];
  for (const [texte, attendu] of cas) {
    assert.deepEqual(lireCoordonnees(texte), attendu, `saisie « ${texte} »`);
  }
});

test("la virgule décimale française est acceptée", () => {
  assert.deepEqual(lireCoordonnees("4,0511 9,7679"), { lat: 4.0511, lon: 9.7679 });
  assert.deepEqual(lireCoordonnees("4,0511, 9,7679"), { lat: 4.0511, lon: 9.7679 });
  assert.deepEqual(lireCoordonnees("4,0511,9,7679"), { lat: 4.0511, lon: 9.7679 });
});

test("un nombre à point n'est pas pris pour une virgule décimale", () => {
  // Le piège : la virgule est collée à des chiffres des deux côtés, comme une décimale,
  // mais les deux nombres ont déjà leur point. C'est un séparateur sans espace derrière.
  assert.deepEqual(lireCoordonnees("4.0511,9.7679"), { lat: 4.0511, lon: 9.7679 });
  assert.deepEqual(lireCoordonnees("-33.8688,151.2093"), { lat: -33.8688, lon: 151.2093 });
});

test("un mélange de points et de virgules reste lisible", () => {
  assert.deepEqual(lireCoordonnees("4.0511, 9,7679"), { lat: 4.0511, lon: 9.7679 });
  assert.deepEqual(lireCoordonnees("4,0511, 9.7679"), { lat: 4.0511, lon: 9.7679 });
});

test("une saisie hors domaine ou incomplète est refusée", () => {
  for (const mauvais of [
    "", "   ", "4.0511", "4.0511 9.7679 12", "abc def",
    "91.5, 9.7679",      // latitude hors domaine
    "4.0511, 181",       // longitude hors domaine
    "4.0511, abc", null, undefined, 42,
  ]) {
    assert.equal(lireCoordonnees(mauvais), null, `accepté à tort : ${JSON.stringify(mauvais)}`);
  }
});

test("les bornes du domaine sont reconnues", () => {
  assert.equal(estLatitude(90), true);
  assert.equal(estLatitude(-90), true);
  assert.equal(estLatitude(90.1), false);
  assert.equal(estLongitude(180), true);
  assert.equal(estLongitude(-180), true);
  assert.equal(estLongitude(180.1), false);
  assert.equal(estLatitude(NaN), false);
  assert.equal(estLongitude(Infinity), false);
});

// --- Mesures --------------------------------------------------------------------------------

test("la distance entre deux points correspond à l'écart en mètres", () => {
  const origine = DOUALA;
  // 1 km vers l'est depuis l'origine, converti en degrés : la distance doit le retrouver.
  const { lon, lat } = metresVersDegres(1000, 0, origine);
  assert.ok(Math.abs(distanceM(origine, { lat, lon }) - 1000) < 0.01);

  // Même chose vers le nord.
  const nord = metresVersDegres(0, 2500, origine);
  assert.ok(Math.abs(distanceM(origine, nord) - 2500) < 0.01);

  // Diagonale : 3 km à l'est, 4 km au nord → 5 km, le triangle 3-4-5.
  const diag = metresVersDegres(3000, 4000, origine);
  assert.ok(Math.abs(distanceM(origine, diag) - 5000) < 0.05);
});

test("la distance d'un point à lui-même est nulle", () => {
  assert.equal(distanceM(DOUALA, DOUALA), 0);
});

test("l'affichage garde une précision au niveau de la rue", () => {
  // Six décimales valent environ 11 cm : assez pour poser un équipement, pas au point
  // d'encombrer la fenêtre de chiffres inutiles.
  assert.equal(formaterCoordonnees(4.0511, 9.7679), "4.051100, 9.767900");
});
