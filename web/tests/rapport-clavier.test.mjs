// Rapport de l'audit clavier : ce qu'il écrit, sans navigateur.
//
// Même raison d'être que `audit-rapport.test.mjs` : l'audit clavier ne tourne que sur la CI,
// Chromium étant hors de portée de ce poste. Sa sortie n'était donc vérifiable par rien d'ici,
// et un rapport silencieusement vide se serait vu « vert » comme un rapport sain. La mise en
// forme est une fonction pure : on la vérifie ici.
import { test } from "node:test";
import assert from "node:assert/strict";

import { rapportClavier } from "../tests/e2e/rapport-clavier.mjs";

const SAIN = {
  etat: "observation · Journal",
  problemes: [],
  ordre: [
    { rang: 1, quoi: "button.tab", role: "tab", nom: "Simulation", indicateur: "oui" },
    { rang: 2, quoi: "button.tab", role: "tab", nom: "Journal", indicateur: "oui" },
  ],
};

const BLESSE = {
  etat: "équipement · Config",
  problemes: [
    { type: "sans indicateur de focus", quoi: "button.tool", detail: "« Déplacer » prend le focus mais aucun style ne change" },
    { type: "sans indicateur de focus", quoi: "button.dtab", detail: "« Config » prend le focus mais aucun style ne change" },
    { type: "non atteignable au clavier", quoi: "div.mode-card", detail: "« capteur » est affiché et interactif, mais absent de l'ordre" },
  ],
  ordre: [{ rang: 1, quoi: "button.dtab", role: "tab", nom: "Physique", indicateur: "oui" }],
};

test("le total compte les problèmes de tous les états et ceux hors état", () => {
  const md = rapportClavier({ etats: [SAIN, BLESSE], problemes: [{ type: "tablist sourde aux flèches", quoi: ".views", detail: "sans objet" }] });
  assert.match(md, /\*\*4 problème\(s\)\*\* sur 2 états mesurés/);
  assert.match(md, /TOTAL : 4 problème\(s\)/);
  // Les défauts hors état ne sont d'aucun état : les fondre dans l'un d'eux les ferait
  // disparaître dès qu'on ne mesure plus cet état-là.
  assert.match(md, /## Défauts hors état/);
  assert.match(md, /\| tablist sourde aux flèches \| \.views \| sans objet \|/);
});

test("un état sain le dit, et ne fabrique pas de section de problèmes", () => {
  const md = rapportClavier({ etats: [SAIN] });
  assert.match(md, /## observation · Journal/);
  assert.match(md, /0 problème\(s\)/);
  assert.match(md, /Aucun problème\./);
  assert.doesNotMatch(md, /### sans indicateur/);
});

test("les problèmes sont groupés par type, avec le détail de chacun", () => {
  const md = rapportClavier({ etats: [BLESSE] });
  assert.match(md, /### sans indicateur de focus \(2\)/);
  assert.match(md, /### non atteignable au clavier \(1\)/);
  assert.match(md, /\| button\.tool \| « Déplacer »/);
});

test("l'ordre de tabulation reste présent : c'est la mesure, pas le verdict", () => {
  // Un rapport qui ne dirait que « 0 problème » serait un rapport auquel il manque la mesure :
  // c'est l'ordre entier qui permet de voir un élément manquant.
  const md = rapportClavier({ etats: [SAIN] });
  assert.match(md, /ordre de tabulation/);
  assert.match(md, /\| rang \| élément \| rôle \| nom accessible \| indicateur \|/);
  assert.match(md, /\| 1 \| button\.tab \| tab \| Simulation \| oui \|/);
});

test("un nom accessible contenant un « | » ne casse pas le tableau", () => {
  const md = rapportClavier({ etats: [{ etat: "x", problemes: [], ordre: [{ rang: 1, quoi: "button", role: "button", nom: "A | B", indicateur: "oui" }] }] });
  assert.match(md, /\| A \\\| B \|/);
});

test("un audit interrompu le dit, et ne se lit pas comme un audit sain", () => {
  // C'est le cas réel qui a coûté un rapport entier : l'audit a expiré sur la simulation,
  // n'a rien écrit, et le dépôt est resté sans trace — une absence qu'on lit « aucun défaut ».
  const md = rapportClavier({ etats: [SAIN], problemes: [], echec: new Error("Waiting failed: 120000ms exceeded") });
  assert.match(md, /> \*\*Audit interrompu :\*\* Error : Waiting failed: 120000ms exceeded/);
  assert.match(md, /Les états manquants n'ont pas été mesurés/);
  // Les états mesurés avant la panne restent publiés : ce n'est pas parce qu'on s'est
  // arrêté qu'on n'a rien vu.
  assert.match(md, /## observation · Journal/);
});

test("un rapport sans échec ne fabrique pas de section d'interruption", () => {
  const md = rapportClavier({ etats: [SAIN], problemes: [] });
  assert.doesNotMatch(md, /Audit interrompu/);
});

test("un rapport vide se tient : pas de total fabriqué", () => {
  for (const d of [{ etats: [], problemes: [] }, undefined]) {
    const md = rapportClavier(d);
    assert.match(md, /\*\*0 problème\(s\)\*\* sur 0 états mesurés/);
    assert.match(md, /TOTAL : 0 problème\(s\)/);
  }
});

test("le rapport se termine par un saut de ligne : un fichier sans fin casse les diffs", () => {
  assert.ok(rapportClavier({ etats: [SAIN] }).endsWith("\n"));
});
