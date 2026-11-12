// Descentes à l'initiative du réseau : réglage, attente annoncée, et animation.
//
// Le fil rouge de ce fichier est une idée reçue : « la classe B est plus rapide que la classe
// A ». Elle est fausse la plupart du temps — un créneau rare attend plus longtemps qu'un
// uplink — et chaque test qui suit garde une facette de cette relation.
import { test } from "node:test";
import assert from "node:assert/strict";

import { validateSensor, attenteAttendue, classeBPlusLenteQueA, CLASSE_DEFAUT }
  from "../src/studio/topology.js";
import { segmentsDescentes } from "../src/studio/animation.js";
import { formatSecondes } from "../src/studio/results.js";

const BASE = {
  spreading_factor: "7", payload_bytes: "10", tx_power_dbm: "14", period_s: "600",
  messages: "1", start_spread_s: "0", region: "", channel_freq_hz: "",
};

const DOWNLINK = { count: "1", first_request_s: "10", request_period_s: "0", periodicity: "7" };

// --- Réglage : ce qui part, et ce qui ne part pas ---------------------------------------------

test("sans descente, rien n'est publié — ni bloc, ni classe", () => {
  const r = validateSensor({ ...BASE });
  assert.equal(r.ok, true);
  // L'absence est publiée, pas un bloc de zéros qui dirait « une commande à l'instant 0 ».
  assert.equal(r.settings.downlink, undefined);
  // « A » est le défaut : le publier écrirait dans le scénario compilé et changerait
  // l'empreinte d'un chantier écrit avant.
  assert.equal(r.settings.device_class, undefined);
});

test("la classe par défaut n'est pas envoyée, une classe choisie l'est", () => {
  assert.equal(validateSensor({ ...BASE, device_class: "A" }).settings.device_class, undefined);
  assert.equal(validateSensor({ ...BASE, device_class: "C" }).settings.device_class, "C");
  assert.equal(CLASSE_DEFAUT, "A");
});

test("plusieurs commandes sans écart sont refusées, avec le champ fautif", () => {
  const r = validateSensor({ ...BASE, downlink: { ...DOWNLINK, count: "3" } });
  assert.equal(r.ok, false);
  assert.equal(r.field, "downlink_request_period_s");
  // Deux commandes sans écart partiraient au même instant : c'est un non-sens, pas un réglage.
  const ok = validateSensor({ ...BASE, downlink: { ...DOWNLINK, count: "3",
    request_period_s: "30" } });
  assert.equal(ok.ok, true);
  assert.equal(ok.settings.downlink.request_period_s, 30);
});

test("les nombres sont bornés et les entiers tronqués", () => {
  assert.equal(validateSensor({ ...BASE, downlink: { ...DOWNLINK, periodicity: "9" } }).ok, false);
  assert.equal(validateSensor({ ...BASE, downlink: { ...DOWNLINK, count: "0" } }).ok, false);
  const r = validateSensor({ ...BASE, downlink: { ...DOWNLINK, count: "2.7",
    request_period_s: "30" } });
  assert.equal(r.ok, true);
  assert.equal(r.settings.downlink.count, 2);
});

// --- L'attente annoncée, avant le run ---------------------------------------------------------

test("classe C n'attend pas, classe A attend sa période", () => {
  assert.equal(attenteAttendue({ classe: "C" }), 0);
  assert.equal(attenteAttendue({ classe: "A", period_s: 60 }), 60);
});

test("classe B attend son créneau, et c'est la périodicité qui décide", () => {
  // Un créneau toutes les secondes : 1 s. Un créneau par période de 128 s : 128 s.
  assert.equal(attenteAttendue({ classe: "B", intervalleSlotS: 1 }), 1);
  assert.equal(attenteAttendue({ classe: "B", intervalleSlotS: 128 }), 128);
  // Sans intervalle servi par le moteur, on ne annonce rien plutôt qu'un chiffre inventé.
  assert.equal(attenteAttendue({ classe: "B" }), null);
});

test("une classe B peut attendre PLUS longtemps qu'une classe A", () => {
  // Le cas qui tue l'idée reçue : créneau de 128 s contre période d'émission de 60 s.
  assert.equal(classeBPlusLenteQueA(128, 60), true);
  assert.equal(classeBPlusLenteQueA(1, 60), false);
  // Grand classique : les intervalles servis par le moteur pour les deux extrêmes.
  assert.equal(classeBPlusLenteQueA(1.0, 60), false);   // périodicité 0
  assert.equal(classeBPlusLenteQueA(128.0, 60), true);  // périodicité 7
});

// --- Animation : on n'anime que ce qu'on peut dater -------------------------------------------

const capteurs = (...noms) => new Map(noms.map((n) => [n,
  { downlink: { count: 1, first_request_s: 10 } }]));

test("l'attente se voit : deux flèches, l'écart entre elles est l'attente", () => {
  const rows = [{ device_index: 0, group: "a", downlink_delivered: 1,
    downlink_latency_s: 51.041216 }];
  const segs = segmentsDescentes({ deviceRows: rows, deviceGroups: ["a"],
    capteurs: capteurs("a"), passerelle: "gw1" });
  assert.equal(segs.length, 2);
  assert.equal(segs[0].from, "ns");
  assert.equal(segs[0].to, "gw1");
  assert.equal(Number(segs[0].t0) / 1e9, 10);
  assert.equal(segs[1].from, "gw1");
  assert.equal(segs[1].to, "a");
  assert.equal(Number(segs[1].t0) / 1e9, 61.041216);
  assert.equal(segs[1].attenteS, 51.041216);
});

test("la classe C émet à l'instant voulu, la classe A bien après", () => {
  const rows = [
    { device_index: 0, group: "a", downlink_delivered: 1, downlink_latency_s: 51.041216 },
    { device_index: 1, group: "c", downlink_delivered: 1, downlink_latency_s: 0 },
  ];
  const segs = segmentsDescentes({ deviceRows: rows, deviceGroups: ["a", "c"],
    capteurs: capteurs("a", "c"), passerelle: "gw1" });
  const emissions = segs.filter((s) => s.kind === "downlink_emit");
  const parGroupe = Object.fromEntries(emissions.map((s) => [s.to, Number(s.t0) / 1e9]));
  assert.equal(parGroupe.c, 10);
  assert.equal(parGroupe.a, 61.041216);
});

test("plusieurs commandes ne s'animent pas : la latence est une moyenne", () => {
  // Dater chaque émission d'une moyenne inventerait un instant. Rien ne vaut mieux.
  const rows = [{ device_index: 0, group: "a", downlink_delivered: 3,
    downlink_latency_s: 20 }];
  const capteursMultiples = new Map([["a",
    { downlink: { count: 3, first_request_s: 10, request_period_s: 30 } }]]);
  const segs = segmentsDescentes({ deviceRows: rows, deviceGroups: ["a"],
    capteurs: capteursMultiples, passerelle: "gw1" });
  assert.equal(segs.length, 0);
});

test("une commande non acheminée ne trace pas de flèche vers le terminal", () => {
  // Rien n'a été émis : une flèche « perdue » laisserait croire à une trame partie et ratée.
  const rows = [{ device_index: 0, group: "a", downlink_delivered: 0,
    downlink_latency_s: 0 }];
  const segs = segmentsDescentes({ deviceRows: rows, deviceGroups: ["a"],
    capteurs: capteurs("a"), passerelle: "gw1" });
  assert.equal(segs.length, 1);
  assert.equal(segs[0].kind, "downlink_request");
});

test("sans latence publiée, ou sans passerelle, aucune animation", () => {
  const rows = [{ device_index: 0, group: "a", downlink_delivered: null,
    downlink_latency_s: null }];
  assert.equal(segmentsDescentes({ deviceRows: rows, deviceGroups: ["a"],
    capteurs: capteurs("a"), passerelle: "gw1" }).length, 0);
  assert.equal(segmentsDescentes({ deviceRows: [{ device_index: 0, group: "a",
    downlink_delivered: 1, downlink_latency_s: 5 }], deviceGroups: ["a"],
  capteurs: capteurs("a"), passerelle: null }).length, 0);
});

// --- Affichage --------------------------------------------------------------------------------

test("une durée se lit sans fausse précision, et une attente inconnue n'est pas nulle", () => {
  assert.equal(formatSecondes(null), "—");
  assert.equal(formatSecondes(0), "0 s");
  assert.equal(formatSecondes(0.94), "0.94 s");
  assert.equal(formatSecondes(51.041216), "51 s");
  assert.equal(formatSecondes(128), "2 min 8 s");
  assert.equal(formatSecondes(600), "10 min");
});
