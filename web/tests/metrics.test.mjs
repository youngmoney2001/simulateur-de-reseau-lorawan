// Indicateurs calculés : parité avec la sortie réelle du serveur.
//
// `fixtures/run-metrics.json` est la sortie brute de `GET /runs/{id}/summary` et
// `GET /runs/{id}/devices` sur un run à trois passerelles, deux groupes et profil énergie
// (`web/scripts/capture-metrics-fixture.py`, rejouable). Les valeurs
// attendues ci-dessous sont recalculées à la main depuis ces compteurs — les reprendre du
// module en ferait une reformulation, pas une vérification.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  ratio,
  somme,
  moyenne,
  fenetreObservationNs,
  occupationNs,
  indicateursReseau,
  repartitionPertes,
  indicateursPasserelle,
  ventilationGroupes,
  pdrParDispositif,
  ventilationTable,
} from "../src/studio/metrics.js";

const FIXTURE = JSON.parse(
  readFileSync(new URL("./fixtures/run-metrics.json", import.meta.url), "utf-8"));
const { summary, devices } = FIXTURE;
const FENETRE = 1_742_526_688_314;   // fenêtre d observation du run, lue dans le fixture

function parId(liste) {
  return Object.fromEntries(liste.map((i) => [i.id, i]));
}

test("le fixture est bien un run multi-passerelles avec énergie", () => {
  assert.equal(summary.gateways.length, 3);
  assert.equal(devices.length, 22);
  assert.equal(summary.totals.sent, 172);
  assert.ok(devices.every((d) => d.energy_per_message_j != null));
});

test("rapport protégé : null au lieu de NaN ou Infinity", () => {
  assert.equal(ratio(3, 4), 0.75);
  assert.equal(ratio(3, 0), null);
  assert.equal(ratio(3, undefined), null);
  assert.equal(ratio(NaN, 4), null);
});

test("somme et moyenne ignorent les champs optionnels absents", () => {
  assert.equal(somme([1, null, 2, undefined, NaN, 3]), 6);
  assert.equal(moyenne([1, null, 3]), 2);
  assert.equal(moyenne([null, undefined]), null);
});

test("fenêtre et occupation : le maximum des passerelles, jamais leur somme", () => {
  const fenetres = summary.gateways.map((g) => g.observation_ns);
  assert.equal(fenetreObservationNs(summary), Math.max(...fenetres));
  assert.equal(fenetreObservationNs(summary), 1_742_526_688_314);
  assert.equal(occupationNs(summary), Math.max(...summary.gateways.map((g) => g.busy_ns)));
  // Une somme compterait trois fois la même fenêtre : le débit serait trois fois trop faible.
  assert.notEqual(occupationNs(summary), somme(summary.gateways.map((g) => g.busy_ns)));
});

test("fenêtre d'observation : le bloc passerelle unique est lu aussi", () => {
  assert.equal(fenetreObservationNs({ gateway: { observation_ns: 5000 } }), 5000);
  assert.equal(fenetreObservationNs({}), null);
});

test("indicateurs réseau : parité avec les compteurs du run", () => {
  const i = parId(indicateursReseau(summary, devices));
  // 152 reçues sur 172 émises.
  assert.equal(i.pdr.text, "88.4 %");
  // 20 collisions sur 516 trames audibles (172 par passerelle × 3).
  assert.equal(i.collisions_audibles.text, "3.9 %");
  // 151 242 752 000 ns d'antenne sur 1 742 526 688 314 ns d'observation.
  assert.equal(i.charge.text, "0.087");
  // 134 229 210 100 ns d'occupation (union) sur la même fenêtre.
  assert.equal(i.occupation.text, "7.7 %");
  // 879 319 488 ns par trame.
  assert.equal(i.airtime.text, "879.3 ms");
  // 152 reçues sur 1 742,5 s d'observation.
  assert.equal(i.debit.text, "0.09 trame/s");
  assert.equal(i.simultaneite.text, "3 trames");
  // Profil énergie présent : moyenne des 22 dispositifs.
  assert.equal(i.energie_message.text, "233.94 mJ");
  assert.equal(i.energie_run.text, "50.703 J");
  assert.equal(i.courant.text, "1146 µA");
});

test("charge offerte et occupation sont deux grandeurs distinctes", () => {
  const i = parId(indicateursReseau(summary, devices));
  // Le fixture est peu chargé : G = 0,087 et l'occupation 7,7 % sont proches. Sur un run
  // saturé, G dépasse 1 (mesuré 4,60) alors que l'occupation plafonne à 100 % : un seul
  // indicateur ne peut pas dire les deux. Le test verrouille qu'ils sont bien séparés.
  assert.notEqual(i.charge.value, i.occupation.value);
  assert.notEqual(i.charge.id, i.occupation.id);
});

test("répartition des pertes : les parts somment à 100 % et l'invariant est cohérent", () => {
  const r = repartitionPertes(summary.totals);
  assert.equal(r.coherent, true);
  assert.equal(r.value, 1);
  const total = r.parts.reduce((a, p) => a + p.part, 0);
  assert.ok(Math.abs(total - 1) < 1e-12);
  assert.equal(r.text, "88 % reçues · 12 % collision");
});

test("répartition des pertes : aucune perte, et run vide", () => {
  const propre = repartitionPertes({ sent: 10, received: 10, lost_collision: 0 });
  assert.equal(propre.text, "100 % reçues");
  assert.equal(repartitionPertes({ sent: 0, received: 0 }), null);
  assert.equal(repartitionPertes({}), null);
});

test("répartition des pertes : une rupture de l'invariant est signalée, pas masquée", () => {
  const casse = repartitionPertes({ sent: 10, received: 4, lost_collision: 3 });
  assert.equal(casse.coherent, false);
  assert.equal(casse.value, 0.7);
});

test("sans profil énergie, les trois indicateurs d'énergie sont absents", () => {
  const sansEnergie = devices.map(({ energy_per_message_j, average_current_ua, ...reste }) => reste);
  const ids = indicateursReseau(summary, sansEnergie).map((i) => i.id);
  assert.ok(!ids.includes("energie_message"));
  assert.ok(!ids.includes("energie_run"));
  assert.ok(!ids.includes("courant"));
  // Les indicateurs réseau, eux, ne dépendent pas du profil.
  assert.ok(ids.includes("pdr"));
});

test("indicateurs sur un run vide : aucun nombre fabriqué de zéro", () => {
  assert.deepEqual(indicateursReseau({}, []), []);
  assert.deepEqual(indicateursReseau({ totals: { sent: 0, received: 0 } }, []), []);
});

test("chaque indicateur porte sa formule et une valeur exploitable", () => {
  const liste = indicateursReseau(summary, devices);
  assert.ok(liste.length >= 8);
  for (const i of liste) {
    assert.ok(i.label, `sans libellé : ${i.id}`);
    assert.ok(typeof i.hint === "string" && i.hint.length > 20, `formule absente : ${i.id}`);
    assert.notEqual(i.text, "—", `valeur non calculée : ${i.id}`);
    assert.ok(Number.isFinite(i.value), `valeur non finie : ${i.id}`);
  }
});

test("aucun indicateur ne prononce de conformité réglementaire", () => {
  // Cinq des huit régions du modèle n'ont aucune limite de rapport cyclique, et aucune
  // limite EU868 n'est sourcée dans docs/REGULATORY_SOURCES.md : un verdict serait inventé.
  const liste = [...indicateursReseau(summary, devices),
    ...summary.gateways.flatMap((g) => indicateursPasserelle(g))];
  for (const i of liste) {
    for (const mot of ["conforme", "non conforme", "limite légale", "dépasse la limite"]) {
      assert.ok(!`${i.label} ${i.hint}`.toLowerCase().includes(mot),
        `verdict réglementaire sur « ${i.label} »`);
    }
  }
});

test("indicateurs par passerelle : occupation et décodage sur audibles", () => {
  const nord = Object.fromEntries(
    indicateursPasserelle(summary.gateways[0]).map((i) => [i.label, i]));
  assert.equal(nord.Passerelle.text, "gw-nord");
  // 134 229 210 100 / 1 742 526 688 314.
  assert.equal(nord["Occupation"].text, "7.7 %");
  // 142 décodées sur 172 audibles à cette passerelle.
  assert.equal(nord["Décodées sur audibles"].text, "82.6 %");
  assert.equal(nord["Simultanéité maximale"].text, "3");
});

test("indicateurs par passerelle : rien sans trame audible", () => {
  const vide = indicateursPasserelle({ name: "muette", audible_frames: 0, observation_ns: 0 });
  assert.equal(vide.filter((i) => i.label !== "Passerelle").length, 0);
});

test("ventilation par groupe : deux groupes, deux SF, compteurs par groupe", () => {
  const groupes = Object.fromEntries(ventilationGroupes(devices).map((g) => [g.name, g]));
  assert.deepEqual(Object.keys(groupes).sort(), ["capteurs-lointains", "capteurs-proches"]);
  const proches = groupes["capteurs-proches"];
  assert.equal(proches.count, 12);
  assert.equal(proches.spreadingFactor, "SF7");
  assert.equal(proches.sent, 72);
  assert.equal(proches.received, 72);
  assert.equal(proches.pdrText, "100.0 %");
  const lointains = groupes["capteurs-lointains"];
  assert.equal(lointains.count, 10);
  assert.equal(lointains.spreadingFactor, "SF12");
  assert.equal(lointains.sent, 100);
  assert.equal(lointains.lostCollision, 20);
  assert.equal(lointains.pdrText, "80.0 %");
  // L'agrégation ne perd ni ne fabrique de trame.
  assert.equal(somme(Object.values(groupes).map((g) => g.sent)), summary.totals.sent);
  assert.equal(somme(Object.values(groupes).map((g) => g.received)), summary.totals.received);
});

test("ventilation par groupe : dispositifs sans groupe regroupés, liste vide vide", () => {
  const orphelins = ventilationGroupes([{ sent: 1, received: 0 }, { sent: 1, received: 1 }]);
  assert.equal(orphelins.length, 1);
  assert.equal(orphelins[0].name, "(sans groupe)");
  assert.equal(orphelins[0].pdrText, "50.0 %");
  assert.deepEqual(ventilationGroupes([]), []);
});

test("taux de livraison par dispositif : un par ligne, dans l'ordre", () => {
  const pdr = pdrParDispositif(devices);
  assert.equal(pdr.length, devices.length);
  assert.deepEqual(pdr.map((p) => p.deviceIndex), devices.map((d) => d.device_index));
  for (const p of pdr) assert.ok(p.pdr >= 0 && p.pdr <= 1, `PDR hors bornes : ${p.pdr}`);
});

test("table de ventilation : un équipement par groupe supprime la colonne inutile", () => {
  // Cas d'une session studio : study_compile.py nomme chaque groupe d'après le capteur.
  const un = [{ name: "capt-1", count: 1, spreadingFactor: "SF9", sent: 4, received: 3, pdrText: "75.0 %", lostSensitivity: 0, lostCollision: 1, occupancyMaxText: "0.500 %" }];
  const t = ventilationTable(un);
  assert.equal(t.unParGroupe, true);
  assert.ok(!t.entetes.includes("Dispositifs"));
  assert.equal(t.entetes[0], "Équipement");
  assert.deepEqual(t.lignes[0], ["capt-1", "SF9", 4, 3, "75.0 %", 0, 1, "0.500 %"]);
});

test("table de ventilation : de vrais groupes gardent la colonne Dispositifs", () => {
  const groupes = ventilationGroupes(FIXTURE.devices, FENETRE);
  const t = ventilationTable(groupes);
  assert.equal(t.unParGroupe, false);
  assert.ok(t.entetes.includes("Dispositifs"));
  assert.equal(t.entetes[0], "Groupe");
  // Huit colonnes annoncées, huit cellules par ligne : une table désalignée se voit ici.
  for (const ligne of t.lignes) assert.equal(ligne.length, t.entetes.length);
});

test("table de ventilation : vide, une forme définie plutôt qu'une exception", () => {
  const t = ventilationTable([]);
  assert.equal(t.unParGroupe, false);
  assert.ok(t.entetes.includes("Dispositifs"));
  assert.deepEqual(t.lignes, []);
});

test("occupation par groupe : le dispositif le plus émetteur, pas la moyenne", () => {
  // La limite réglementaire s'applique à chaque émetteur : c'est le maximum qui compte,
  // une moyenne laisserait passer un dispositif hors limite noyé dans les autres.
  const groupes = ventilationGroupes(FIXTURE.devices, FENETRE);
  const g = Object.fromEntries(groupes.map((x) => [x.name, x]));
  // capteurs-lointains : 10 dispositifs SF12, 148 275,2 ms d'antenne au total sur
  // 1 742,5 s d'observation. Le maximum par dispositif, pas la somme.
  const maxLointains = Math.max(...FIXTURE.devices
    .filter((d) => d.group === "capteurs-lointains").map((d) => d.airtime_ns));
  assert.equal(g["capteurs-lointains"].occupancyMax, maxLointains / FENETRE);
  // Un groupe de 10 dispositifs : la somme serait environ dix fois le maximum.
  assert.ok(g["capteurs-lointains"].occupancyMax
    < g["capteurs-lointains"].airtimeMs * 1000 * 1e6 / FENETRE);
  assert.equal(typeof g["capteurs-lointains"].occupancyMaxText, "string");
});

test("occupation par groupe : absente sans fenêtre d'observation", () => {
  const groupes = ventilationGroupes(FIXTURE.devices, null);
  for (const g of groupes) {
    assert.equal(g.occupancyMax, null);
    assert.equal(g.occupancyMaxText, "—");
  }
});
