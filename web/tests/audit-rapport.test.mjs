// Rapport de l'audit de mise en page : ce qu'il écrit, sans navigateur.
//
// L'audit ne tourne que sur la CI — Chromium est hors de portée de ce poste. Sa sortie n'était
// donc vérifiable par rien d'ici, et un rapport silencieusement vide se serait vu « vert »
// comme un rapport sain. La mise en forme est une fonction pure : on la vérifie ici.
import { test } from "node:test";
import assert from "node:assert/strict";

import { rapportMarkdown } from "../tests/e2e/rapport-audit.mjs";

const SAIN = {
  etat: "1400 · passerelle · Config",
  problemes: [],
  scrollHorizontal: false,
  geometrie: [{ quoi: "device-win", x: 12, y: 40, l: 430, h: 517 }],
};

const BLESSE = {
  etat: "900 · passerelle · Config",
  problemes: [
    { type: "débordement horizontal", quoi: "gw-form", detail: "sort de 34 px" },
    { type: "débordement horizontal", quoi: "gw-aide", detail: "sort de 12 px" },
    { type: "texte tronqué", quoi: "summary", detail: "contenu 120 px pour 90 px" },
  ],
  scrollHorizontal: true,
  geometrie: [{ quoi: "device-win", x: 8, y: 40, l: 400, h: 517 }],
};

test("le total compte les problèmes de tous les états, pas du dernier", () => {
  const md = rapportMarkdown([SAIN, BLESSE]);
  assert.match(md, /\*\*3 problème\(s\)\*\* sur 2 états mesurés/);
  assert.match(md, /TOTAL : 3 problème\(s\)/);
});

test("un état sain le dit, et ne fabrique pas de section de problèmes", () => {
  const md = rapportMarkdown([SAIN]);
  assert.match(md, /## 1400 · passerelle · Config/);
  assert.match(md, /0 problème\(s\)/);
  assert.match(md, /Aucun problème\./);
  assert.doesNotMatch(md, /### débordement/);
  // Le défilement horizontal est une mesure, pas une opinion : il est dit même quand il est bon.
  assert.match(md, /défilement horizontal : non/);
});

test("les problèmes sont groupés par type, avec le détail de chacun", () => {
  const md = rapportMarkdown([BLESSE]);
  assert.match(md, /### débordement horizontal \(2\)/);
  assert.match(md, /### texte tronqué \(1\)/);
  assert.match(md, /\| gw-form \| sort de 34 px \|/);
  assert.match(md, /défilement horizontal : oui/);
});

test("la géométrie reste présente : c'est elle qui fait foi, pas le verdict", () => {
  // Un rapport qui ne dirait que « 0 problème » serait un rapport auquel il manque la mesure.
  const md = rapportMarkdown([SAIN]);
  assert.match(md, /géométrie/);
  assert.match(md, /\| device-win \| 12 \| 40 \| 430×517 \|/);
});

test("un état non atteint est dit, pas compté comme sain", () => {
  // Un état qu'on n'a pas pu ouvrir n'est pas un état sans défaut : le taire ferait croire
  // à une mesure qui n'a pas eu lieu.
  const md = rapportMarkdown([{ etat: "900 · passerelle · Config", introuvable: true }]);
  assert.match(md, /état non atteint/);
  assert.match(md, /\*\*0 problème\(s\)\*\* sur 1 états mesurés/);
});

test("un rapport vide se tient : pas de total fabriqué", () => {
  // `[]` et « pas d'argument » : deux façons réelles d'appeler. `null` n'en est pas une —
  // `rapport` est construit par `push` dans l'audit, il est toujours un tableau. Couvrir
  // `null` annoncerait une robustesse qu'on n'a pas et qu'on n'a pas à avoir.
  for (const r of [[], undefined]) {
    const md = rapportMarkdown(r);
    assert.match(md, /\*\*0 problème\(s\)\*\* sur 0 états mesurés/);
    assert.match(md, /TOTAL : 0 problème\(s\)/);
  }
});

test("le rapport se termine par un saut de ligne : un fichier sans fin casse les diffs", () => {
  assert.ok(rapportMarkdown([SAIN]).endsWith("\n"));
});
