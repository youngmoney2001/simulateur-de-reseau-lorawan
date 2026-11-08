// Liaisons observées : ce qu'on trace, et surtout ce qu'on ne trace pas.
// Une liaison inventée serait pire qu'un plan muet — l'apprenant la croirait.
import { test } from "node:test";
import assert from "node:assert/strict";

import { liaisonsMesh, liaisonsRadio, liaisonsObservees, cumulerLiaisons,
  etiquetteLiaison } from "../src/studio/liaisons.js";

const LIENS = [
  { node_id: "frontiere", gateway: "frontiere" },
  { node_id: "relais-1", gateway: "relais-1" },
  { node_id: "relais-2", gateway: "relais-2" },
];

function resumeMesh(entrants) {
  return entrants.map(([name, inbound]) => ({ name, mesh_inbound: inbound }));
}

test("une liaison mesh est tracée quand le run l'a observée", () => {
  const passerelles = resumeMesh([
    ["frontiere", [{ from_gateway: "relais-1", delivered: 12 }]],
    ["relais-1", []],
  ]);
  const l = liaisonsMesh({ passerelles, liens: LIENS });
  assert.equal(l.length, 1);
  assert.deepEqual(l[0], { de: "relais-1", vers: "frontiere", genre: "mesh", compte: 12 });
});

test("un lien qui n'a rien livré n'est pas tracé : il n'a pas été observé", () => {
  const passerelles = resumeMesh([
    ["frontiere", [{ from_gateway: "relais-1", delivered: 0 }]],
  ]);
  assert.deepEqual(liaisonsMesh({ passerelles, liens: LIENS }), []);
});

test("un équipement ne se relaie pas lui-même", () => {
  const passerelles = resumeMesh([
    ["frontiere", [{ from_gateway: "frontiere", delivered: 5 }]],
  ]);
  assert.deepEqual(liaisonsMesh({ passerelles, liens: LIENS }), []);
});

test("un bout inconnu de la session n'est pas tracé : pas de trait dans le vide", () => {
  const passerelles = resumeMesh([
    ["frontiere", [{ from_gateway: "relais-fantome", delivered: 7 }]],
  ]);
  const avec = liaisonsMesh({ passerelles, liens: LIENS, noeuds: ["frontiere", "relais-1"] });
  assert.deepEqual(avec, []);
  // Sans la liste des nœuds, le nom du run reste un repli : mieux vaut un trait
  // éventuellement mal placé qu'une liaison passée sous silence.
  const sans = liaisonsMesh({ passerelles, liens: LIENS });
  assert.equal(sans.length, 1);
  assert.equal(sans[0].de, "relais-fantome");
});

test("sans mesh, aucune liaison : un run sans relais n'a rien à tracer", () => {
  const passerelles = [{ name: "frontiere", received: 24 }];
  assert.deepEqual(liaisonsMesh({ passerelles, liens: LIENS }), []);
  // `mesh_inbound` absent, pas vide : les deux cas doivent se comporter de même.
  assert.deepEqual(liaisonsMesh({ passerelles: [{ name: "frontiere", mesh_inbound: null }],
    liens: LIENS }), []);
});

test("les liaisons les mieux fournies d'abord : sur un plan chargé, l'essentiel se voit", () => {
  const passerelles = resumeMesh([
    ["frontiere", [{ from_gateway: "relais-1", delivered: 3 },
      { from_gateway: "relais-2", delivered: 40 }]],
  ]);
  const l = liaisonsMesh({ passerelles, liens: LIENS });
  assert.deepEqual(l.map((x) => x.compte), [40, 3]);
});

test("cumuler additionne sans perdre l'orientation", () => {
  const cumul = cumulerLiaisons([
    { de: "relais-1", vers: "frontiere", genre: "mesh", compte: 5 },
    { de: "relais-1", vers: "frontiere", genre: "mesh", compte: 7 },
    { de: "frontiere", vers: "relais-1", genre: "mesh", compte: 2 },
  ]);
  assert.equal(cumul.length, 2);
  const aller = cumul.find((x) => x.de === "relais-1");
  const retour = cumul.find((x) => x.de === "frontiere");
  assert.equal(aller.compte, 12);
  assert.equal(retour.compte, 2);
});

test("l'étiquette nomme ce qu'elle compte", () => {
  assert.equal(etiquetteLiaison({ genre: "mesh", compte: 1 }), "1 trame relayée");
  assert.equal(etiquetteLiaison({ genre: "mesh", compte: 12 }), "12 trames relayées");
  // Un chiffre seul ne dit pas ce qu'il compte : « 12 » pourrait être des sauts.
  assert.match(etiquetteLiaison({ genre: "mesh", compte: 12 }), /trames/);
  // Et le verbe suit la nature du lien : une trame décodée n'est pas une trame relayée.
  assert.equal(etiquetteLiaison({ genre: "radio", compte: 1 }), "1 trame décodée");
  assert.equal(etiquetteLiaison({ genre: "radio", compte: 9 }), "9 trames décodées");
});

// --- Bouts géographiques : la même liaison, sur la carte 3D ------------------------------------

import { boutsLiaison } from "../src/studio/liaisons.js";

const ORIGINE = { lat: 4.0511, lon: 9.7679 };

test("les bouts d'une liaison sont convertis en degrés", () => {
  const noeuds = new Map([
    ["frontiere", { x_m: 0, y_m: 0 }],
    ["relais-1", { x_m: 1500, y_m: 0 }],
  ]);
  const b = boutsLiaison({ de: "relais-1", vers: "frontiere" }, noeuds, ORIGINE);
  assert.ok(b);
  // Le relais est à l'est : sa longitude dépasse celle de la frontière, pas l'inverse.
  assert.ok(b.de.lon > b.vers.lon);
  assert.ok(Math.abs(b.vers.lon - ORIGINE.lon) < 1e-9);
});

test("une liaison dont un bout manque n'est pas traçable : pas de trait dans le vide", () => {
  const noeuds = new Map([["frontiere", { x_m: 0, y_m: 0 }]]);
  assert.equal(boutsLiaison({ de: "relais-1", vers: "frontiere" }, noeuds, ORIGINE), null);
  assert.equal(boutsLiaison({ de: "frontiere", vers: "relais-1" }, noeuds, ORIGINE), null);
});

test("une position inexploitable n'est pas tracée : un trait absent vaut mieux qu'un trait faux", () => {
  const noeuds = new Map([
    ["frontiere", { x_m: 0, y_m: 0 }],
    ["casse", { x_m: NaN, y_m: 0 }],
  ]);
  assert.equal(boutsLiaison({ de: "casse", vers: "frontiere" }, noeuds, ORIGINE), null);
});

test("sans nœuds du tout, rien n'est tracé plutôt que de lever", () => {
  assert.equal(boutsLiaison({ de: "a", vers: "b" }, null, ORIGINE), null);
  assert.equal(boutsLiaison({ de: "a", vers: "b" }, new Map(), ORIGINE), null);
});

// --- Liaisons radio : le masque dit « a décodé », pas « a entendu » --------------------------------

// Trois passerelles en triangle, deux capteurs. Le capteur lointain n'est décodé que par
// deux des trois : c'est la seule façon de vérifier qu'on trace les bonnes colonnes, et
// pas « toutes les passerelles pour tous les capteurs ».
const GATEWAYS = [{ name: "gw-ouest" }, { name: "gw-est" }, { name: "gw-nord" }];
const DEVICE_ROWS = [{ device_index: 0, group: "capt-1" }, { device_index: 1, group: "capt-2" }];
const NOEUDS = ["gw-ouest", "gw-est", "gw-nord", "capt-1", "capt-2"];

test("la matrice se lit par colonnes : l'ordre de `gateways`, pas l'alphabet", () => {
  const rx = [[5, 5, 5], [3, 0, 4]];
  const l = liaisonsRadio({ rxMatrix: rx, gateways: GATEWAYS, deviceRows: DEVICE_ROWS,
    liens: [], noeuds: NOEUDS });
  const parDe = (d) => l.filter((x) => x.de === d).map((x) => x.vers);
  assert.deepEqual(parDe("capt-1"), ["gw-ouest", "gw-est", "gw-nord"]);
  // capt-2 : 3 / 0 / 4 — la colonne du milieu est à zéro, elle ne se trace pas.
  assert.deepEqual(parDe("capt-2"), ["gw-nord", "gw-ouest"]);
  assert.ok(l.every((x) => x.genre === "radio"));
});

test("une trame décodée par trois passerelles compte trois liaisons, pas une", () => {
  // La macro-diversité est la propriété que les événements de trace masquaient : chaque
  // trame n'y cite que la meilleure passerelle. La matrice doit dire les trois.
  const l = liaisonsRadio({ rxMatrix: [[5, 5, 5]], gateways: GATEWAYS,
    deviceRows: DEVICE_ROWS.slice(0, 1), liens: [], noeuds: NOEUDS });
  assert.equal(l.length, 3);
  assert.deepEqual(l.map((x) => x.compte), [5, 5, 5]);
});

test("un couple à zéro n'est pas tracé : il n'a pas été observé", () => {
  const l = liaisonsRadio({ rxMatrix: [[0, 0, 0]], gateways: GATEWAYS,
    deviceRows: DEVICE_ROWS.slice(0, 1), liens: [], noeuds: NOEUDS });
  assert.deepEqual(l, []);
});

test("sans matrice, aucune liaison radio : un run mono-passerelle n'a rien à tracer", () => {
  for (const rx of [null, undefined, []]) {
    assert.deepEqual(liaisonsRadio({ rxMatrix: rx, gateways: GATEWAYS, deviceRows: DEVICE_ROWS,
      liens: [], noeuds: NOEUDS }), []);
  }
});

test("un capteur inconnu de la session n'est pas tracé : pas de trait dans le vide", () => {
  const l = liaisonsRadio({ rxMatrix: [[5, 5, 5]], gateways: GATEWAYS, deviceRows: DEVICE_ROWS,
    liens: [], noeuds: ["gw-ouest", "gw-est", "gw-nord"] });
  assert.deepEqual(l, []);
});

test("le nom de passerelle du run est traduit en équipement de la session", () => {
  // Le run nomme « gw-ouest », la session nomme « passerelle-ouest » : sans `GatewayLink`,
  // le trait atterrirait sur un équipement qui n'existe pas sur la carte.
  const l = liaisonsRadio({ rxMatrix: [[5]], gateways: [{ name: "gw-ouest" }],
    deviceRows: DEVICE_ROWS.slice(0, 1),
    liens: [{ node_id: "passerelle-ouest", gateway: "gw-ouest" }],
    noeuds: ["passerelle-ouest", "capt-1"] });
  assert.deepEqual(l, [{ de: "capt-1", vers: "passerelle-ouest", genre: "radio", compte: 5 }]);
});

test("cumuler ne mélange pas les natures : « relayées + décodées » n'est un total de rien", () => {
  const cumul = cumulerLiaisons([
    { de: "capt-1", vers: "gw-ouest", genre: "radio", compte: 5 },
    { de: "capt-1", vers: "gw-ouest", genre: "mesh", compte: 7 },
  ]);
  assert.equal(cumul.length, 2);
  assert.equal(cumul.find((x) => x.genre === "radio").compte, 5);
  assert.equal(cumul.find((x) => x.genre === "mesh").compte, 7);
});

// --- La composition : ce que la vue assemble, sans navigateur ------------------------------------
//
// `calculerLiaisons` de main.js ne fait qu'assembler cinq entrées ; le calcul est cette fonction.
// La tester ici ferme le trou entre « la matrice est servie » et « le trait est dessiné », sans
// avoir besoin de Chromium.

test("les deux natures se cumulent dans un seul tableau", () => {
  const l = liaisonsObservees({
    passerelles: [{ name: "frontiere", mesh_inbound: [{ from_gateway: "relais-1", delivered: 8 }] },
      { name: "gw-ouest" }, { name: "gw-est" }],
    liens: LIENS,
    noeuds: ["frontiere", "relais-1", "gw-ouest", "gw-est", "capt-1"],
    rxMatrix: [[5, 3, 0]],
    deviceRows: [{ device_index: 0, group: "capt-1" }],
  });
  // Colonnes dans l'ordre de `gateways` — frontière, ouest, est — et la troisième à zéro
  // ne se trace pas. C'est tout le contrat du tracé qui se joue sur cet ordre.
  assert.deepEqual(l.map((x) => `${x.genre}:${x.de}->${x.vers}:${x.compte}`), [
    "mesh:relais-1->frontiere:8", "radio:capt-1->frontiere:5", "radio:capt-1->gw-ouest:3",
  ]);
});

test("sans matrice, la composition ne rend que le mesh", () => {
  const l = liaisonsObservees({
    passerelles: [{ name: "frontiere", mesh_inbound: [{ from_gateway: "relais-1", delivered: 8 }] }],
    liens: LIENS, noeuds: ["frontiere", "relais-1"],
    rxMatrix: null, deviceRows: [],
  });
  assert.deepEqual(l, [{ de: "relais-1", vers: "frontiere", genre: "mesh", compte: 8 }]);
});

test("sans mesh ni matrice, la composition rend une liste vide", () => {
  // Un run sans relais, sur une session à une seule passerelle : rien à tracer, et surtout
  // pas d'erreur — c'est le cas de la session de l'audit de mise en page.
  assert.deepEqual(liaisonsObservees({ passerelles: [{ name: "gw-nord" }], liens: [],
    noeuds: ["gw-nord"], rxMatrix: null, deviceRows: [] }), []);
  assert.deepEqual(liaisonsObservees(), []);
});

test("des entrées vides rendent une liste vide : un run partiel ne casse pas la vue", () => {
  // La vue passe toujours des tableaux (`state.liens ?? []` et consorts) : ce qu'on vérifie
  // ici, c'est l'absence de clé, pas `null` à la place d'un tableau — cas qui n'arrive pas
  // et qu'on n'a donc aucune raison de prétendre couvrir.
  for (const entrees of [{}, { rxMatrix: null }, { passerelles: [] }, { deviceRows: [] },
    { liens: [] }, { noeuds: [] }]) {
    assert.deepEqual(liaisonsObservees(entrees), []);
  }
});
