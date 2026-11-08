// Réglages passerelle exposés dans l'atelier : les bornes sont celles du CLI, sinon un réglage
// accepté dans la fenêtre serait refusé dans la console — deux vérités pour un même équipement.
// Et une sous-bande n'existe que sur US915 / AU915 : le refus doit être le même des deux côtés.
import { test } from "node:test";
import assert from "node:assert/strict";

import { validateGateway, REGIONS_A_SOUS_BANDE, AVANCE_EN_CLI, REGIONS }
  from "../src/studio/topology.js";


// --- Validation des réglages passerelle --------------------------------------------------------

test("sous-bande : refusée hors US915 et AU915, avec le même mot que le CLI", () => {
  for (const region of ["EU868", "AS923", "RU864", "KR920", "IN865"]) {
    const r = validateGateway({ region, sub_band: "2" });
    assert.equal(r.ok, false);
    assert.equal(r.field, "sub_band");
    assert.match(r.message, /US915 ou AU915/);
  }
});

test("sous-bande : acceptée sur US915 et AU915", () => {
  for (const region of REGIONS_A_SOUS_BANDE) {
    const r = validateGateway({ region, sub_band: "5" });
    assert.equal(r.ok, true, region);
    assert.equal(r.settings.sub_band, 5);
  }
});

test("sous-bande : la région déjà posée compte quand le formulaire ne la renvoie pas", () => {
  // La fenêtre envoie région et sous-bande ensemble, mais rien ne l'y oblige :
  // `region_actuelle` est la région déjà enregistrée sur l'équipement.
  const r = validateGateway({ sub_band: "3", region_actuelle: "US915" });
  assert.equal(r.ok, true);
  assert.equal(r.settings.sub_band, 3);
});

test("sous-bande : hors bornes refusée", () => {
  for (const v of ["0", "9", "abc"]) {
    const r = validateGateway({ region: "US915", sub_band: v });
    assert.equal(r.ok, false, v);
    assert.equal(r.field, "sub_band");
  }
});

test("un champ vide n'efface pas le réglage : il n'est simplement pas envoyé", () => {
  const r = validateGateway({ region: "EU868" });
  assert.equal(r.ok, true);
  assert.deepEqual(Object.keys(r.settings), ["region"]);
  assert.equal("sub_band" in r.settings, false);
});

test("les bornes de puissance et de sauts sont celles du CLI", () => {
  assert.equal(validateGateway({ tx_power_dbm: "31" }).ok, false);
  assert.equal(validateGateway({ tx_power_dbm: "-11" }).ok, false);
  assert.equal(validateGateway({ tx_power_dbm: "20" }).ok, true);
  assert.equal(validateGateway({ mesh_max_hops: "0" }).ok, false);
  assert.equal(validateGateway({ mesh_max_hops: "9" }).ok, false);
  assert.equal(validateGateway({ mesh_max_hops: "2" }).ok, true);
});

test("bande et mode du mesh : valeurs fermées", () => {
  assert.equal(validateGateway({ mesh_bandwidth_khz: "1625" }).ok, true);
  assert.equal(validateGateway({ mesh_bandwidth_khz: "500" }).ok, false);
  assert.equal(validateGateway({ mesh_mode: "relay" }).ok, true);
  assert.equal(validateGateway({ mesh_mode: "pont" }).ok, false);
});

test("les réglages avancés sont nommés, pas passés sous silence", () => {
  // Le renvoi vers le CLI doit énumérer : « voyez le CLI » sans la liste ne renseigne pas.
  assert.ok(AVANCE_EN_CLI.includes("gain d'antenne"));
  assert.ok(AVANCE_EN_CLI.includes("fréquence"));
  assert.ok(AVANCE_EN_CLI.length >= 4);
});
