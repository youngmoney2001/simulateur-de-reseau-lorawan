// Liaisons observées : ce qu'on trace, et surtout ce qu'on ne trace pas.
// Une liaison inventée serait pire qu'un plan muet — l'apprenant la croirait.
import { test } from "node:test";
import assert from "node:assert/strict";

import { liaisonsMesh, cumulerLiaisons, etiquetteLiaison }
  from "../src/studio/liaisons.js";

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
  assert.deepEqual(l[0], { de: "relais-1", vers: "frontiere", livrees: 12 });
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
  assert.deepEqual(l.map((x) => x.livrees), [40, 3]);
});

test("cumuler additionne sans perdre l'orientation", () => {
  const cumul = cumulerLiaisons([
    { de: "relais-1", vers: "frontiere", livrees: 5 },
    { de: "relais-1", vers: "frontiere", livrees: 7 },
    { de: "frontiere", vers: "relais-1", livrees: 2 },
  ]);
  assert.equal(cumul.length, 2);
  const aller = cumul.find((x) => x.de === "relais-1");
  const retour = cumul.find((x) => x.de === "frontiere");
  assert.equal(aller.livrees, 12);
  assert.equal(retour.livrees, 2);
});

test("l'étiquette nomme ce qu'elle compte", () => {
  assert.equal(etiquetteLiaison({ livrees: 1 }), "1 trame relayée");
  assert.equal(etiquetteLiaison({ livrees: 12 }), "12 trames relayées");
  // Un chiffre seul ne dit pas ce qu'il compte : « 12 » pourrait être des sauts.
  assert.match(etiquetteLiaison({ livrees: 12 }), /trames/);
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
