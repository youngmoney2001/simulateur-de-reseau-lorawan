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
  autonomieAns,
  autonomieTexte,
  dureeTexte,
  fenetreVerdictTexte,
  FENETRE_ETSI_S,
  occupationNs,
  indicateursReseau,
  repartitionPertes,
  indicateursPasserelle,
  ventilationGroupes,
  pdrParDispositif,
  planCanaux,
  ventilationTable,
  couleurPdr,
  echellePdr,
  ECHELLE_PDR,
  bilanAdr, bilanProtocole,
  resultatsParNoeud,
  lignesResultat,
  verdictDutyCycle,
  limitesParGroupe,
  RESERVE_DUTY_CYCLE,
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

test("aucun indicateur réseau ne prononce de conformité réglementaire", () => {
  // La garde porte sur les indicateurs **agrégés**, et c'est là sa raison d'être : un run peut
  // mêler des groupes de régions, de fréquences et donc de limites différents. Un verdict
  // unique au niveau du réseau n'aurait pas de référent. Le verdict légitime vit dans
  // `ventilationTable`, groupe par groupe, à côté de la limite et de sa source.
  //
  // Précision après relecture : EU868 **est** sourcé et vérifié (ETSI EN 300 220-2 V3.2.1,
  // PDF fournis ; sous-bandes K à QP, voir docs/REGULATORY_SOURCES.md). Ce qui n'est pas
  // confirmé, c'est le duty cycle RU864 de 868,7–869,2 MHz, conservé à 0,1 % par prudence.
  const liste = [...indicateursReseau(summary, devices),
    ...summary.gateways.flatMap((g) => indicateursPasserelle(g))];
  for (const i of liste) {
    for (const mot of ["conforme", "non conforme", "limite légale", "dépasse la limite"]) {
      assert.ok(!`${i.label} ${i.hint}`.toLowerCase().includes(mot),
        `verdict réglementaire sur un indicateur agrégé : « ${i.label} »`);
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
  assert.deepEqual(t.lignes[0], ["capt-1", "SF9", 4, 3, "75.0 %", 0, 1, "0.500 %", "—"]);
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

test("échelle de couleur : décroissante, bornée, et nommable", () => {
  const e = ECHELLE_PDR;
  assert.equal(e.length, 4);
  // Du meilleur au pire, sans trou ni recouvrement : un palier oublié laisserait un
  // équipement sans couleur, deux paliers qui se recouvrent rendraient le choix ambigu.
  for (let i = 1; i < e.length; i += 1) assert.ok(e[i].min < e[i - 1].min);
  assert.equal(e[e.length - 1].min, 0);
  for (const p of e) {
    assert.match(p.couleur, /^#[0-9a-f]{6}$/);
    assert.ok(p.label.length > 0);
  }
  assert.deepEqual(echellePdr().map((x) => x.couleur), e.map((x) => x.couleur));
});

test("couleur d'un taux de livraison : paliers et absence de mesure", () => {
  assert.equal(couleurPdr(1.0), ECHELLE_PDR[0].couleur);
  assert.equal(couleurPdr(0.95), ECHELLE_PDR[0].couleur);   // borne basse incluse
  assert.equal(couleurPdr(0.949), ECHELLE_PDR[1].couleur);
  assert.equal(couleurPdr(0.80), ECHELLE_PDR[1].couleur);
  assert.equal(couleurPdr(0.799), ECHELLE_PDR[2].couleur);
  assert.equal(couleurPdr(0.50), ECHELLE_PDR[2].couleur);
  assert.equal(couleurPdr(0.499), ECHELLE_PDR[3].couleur);
  assert.equal(couleurPdr(0), ECHELLE_PDR[3].couleur);
  // Non mesuré : null, pour que l'appelant garde la couleur de type au lieu de peindre
  // en rouge un équipement qui n'a simplement pas encore de résultat.
  assert.equal(couleurPdr(null), null);
  assert.equal(couleurPdr(undefined), null);
  assert.equal(couleurPdr(NaN), null);
});

test("résultats par équipement : jointure par le nom du groupe", () => {
  // Un run de session studio : study_compile.py nomme le groupe d'après le capteur.
  const lignes = [
    { group: "capt-a", sent: 10, received: 9, lost_collision: 1, lost_sensitivity: 0, airtime_ns: 5e8 },
    { group: "capt-b", sent: 10, received: 4, lost_collision: 6, lost_sensitivity: 0, airtime_ns: 9e8 },
  ];
  const noeuds = [{ id: "capt-a", kind: "sensor" }, { id: "capt-b", kind: "sensor" },
                  { id: "gw-nord", kind: "gateway" }];
  const r = resultatsParNoeud(lignes, noeuds);
  assert.equal(r.size, 2);
  assert.equal(r.get("capt-a").pdr, 0.9);
  assert.equal(r.get("capt-a").couleur, ECHELLE_PDR[1].couleur);
  assert.equal(r.get("capt-b").pdr, 0.4);
  assert.equal(r.get("capt-b").couleur, ECHELLE_PDR[3].couleur);
  // Une passerelle n'a pas de ligne de dispositif : elle garde sa couleur de type.
  assert.equal(r.has("gw-nord"), false);
});

test("résultats par équipement : un vrai groupe n'est pas coloré au hasard", () => {
  // Scénario YAML : un groupe de 12 dispositifs, sans équivalent dans la topologie.
  // Colorer un équipement avec la moyenne d'un groupe serait un chiffre inventé.
  const lignes = Array.from({ length: 12 }, () => ({ group: "capteurs", sent: 6, received: 5 }));
  const noeuds = [{ id: "capteurs", kind: "sensor" }];
  assert.equal(resultatsParNoeud(lignes, noeuds).size, 0);
});

test("résultats par équipement : entrées vides et dispositifs sans groupe", () => {
  assert.equal(resultatsParNoeud([], []).size, 0);
  assert.equal(resultatsParNoeud(undefined, undefined).size, 0);
  assert.equal(resultatsParNoeud([{ sent: 1, received: 1 }], [{ id: "a" }]).size, 0);
});

test("lignes de résultat d'un équipement : mêmes chiffres que la carte", () => {
  const r = { pdr: 0.9, pdrText: "90.0 %", couleur: ECHELLE_PDR[1].couleur,
    sent: 10, received: 9, lostSensitivity: 0, lostCollision: 1, airtimeNs: 5e8 };
  const l = lignesResultat(r, 1e9);
  assert.equal(l.couleur, ECHELLE_PDR[1].couleur);
  assert.equal(l.lignes[0].valeur, "90.0 %");
  assert.equal(l.lignes[1].valeur, "9 sur 10");
  assert.equal(l.lignes[3].valeur, "1");
  assert.equal(l.lignes[4].valeur, "50.000 %");   // 5e8 ns sur 1e9 ns
});

test("lignes de résultat : absentes sans résultat, et sans fenêtre", () => {
  assert.equal(lignesResultat(null, 1e9), null);
  assert.equal(lignesResultat(undefined), null);
  assert.equal(lignesResultat({ pdr: null }, 1e9), null);
  // Sans fenêtre d'observation, l'occupation est « — » mais le reste reste affiché :
  // le taux de livraison ne dépend pas de la fenêtre.
  const l = lignesResultat({ pdr: 0.5, pdrText: "50.0 %", couleur: "#000000",
    sent: 2, received: 1, lostSensitivity: 0, lostCollision: 1, airtimeNs: 5e8 }, null);
  assert.equal(l.lignes[0].valeur, "50.0 %");
  assert.equal(l.lignes[4].valeur, "—");
});

// --- Verdict de rapport cyclique ------------------------------------------------------------

const LIMITES = limitesParGroupe(FIXTURE.summary);

test("le fixture porte bien une limite EU868 sourcée", () => {
  assert.equal(LIMITES.size, 2);
  const d = LIMITES.get("capteurs-proches");
  assert.equal(d.region, "EU868");
  assert.equal(d.limit, 0.01);
  assert.ok(d.source.includes("ETSI EN 300 220-2 V3.2.1"));
});

test("verdict : conforme quand la mesure passe sous la limite", () => {
  // capteurs-proches : 0,014 % mesuré contre 1 % — marge 0,986 point.
  const g = Object.fromEntries(
    ventilationGroupes(FIXTURE.devices, FENETRE).map((x) => [x.name, x]));
  const v = verdictDutyCycle(g["capteurs-proches"], LIMITES.get("capteurs-proches"));
  assert.equal(v.verdict, "conforme");
  assert.equal(v.conforme, true);
  assert.equal(v.limite, 0.01);
  assert.ok(v.marge > 0);
  assert.match(v.verdictText, /^conforme, .* pt sous la limite$/);
});

test("verdict : dépassement franc, et marge exprimée en points", () => {
  const v = verdictDutyCycle({ occupancyMax: 0.02 }, { region: "EU868", limit: 0.01 });
  assert.equal(v.verdict, "depassement");
  assert.equal(v.conforme, false);
  // 2 % contre 1 % : un point de pourcentage, pas « le double » — l'unité compte près du seuil.
  assert.ok(Math.abs(v.marge + 1) < 1e-12);
  assert.match(v.verdictText, /^dépasse la limite de 1\.000 pt$/);
});

test("verdict : la borne est inclusive, un dépassement infime est un dépassement", () => {
  assert.equal(verdictDutyCycle({ occupancyMax: 0.01 }, { limit: 0.01 }).verdict, "conforme");
  assert.equal(verdictDutyCycle({ occupancyMax: 0.0101 }, { limit: 0.01 }).verdict, "depassement");
});

test("verdict : plan sans limite, ce n'est pas une limite à 100 %", () => {
  // US915, AU915, AS923, KR920, IN865 n'ont aucune sous-bande. La clé `limit` est absente.
  const v = verdictDutyCycle({ occupancyMax: 0.5 }, { region: "US915", channel_freq_hz: 903_900_000 });
  assert.equal(v.verdict, "sans_limite");
  assert.equal(v.limite, null);
  assert.equal(v.conforme, null);          // ni conforme ni en faute : on ne sait pas
  assert.notEqual(v.limiteText, "100 %");
  assert.notEqual(v.limiteText, "100.000 %");
});

test("verdict : sans région, rien n'est deviné", () => {
  const v = verdictDutyCycle({ occupancyMax: 0.9 }, undefined);
  assert.equal(v.verdict, "sans_region");
  assert.equal(v.conforme, null);
});

test("verdict : mesure absente", () => {
  const v = verdictDutyCycle({ occupancyMax: null }, { region: "EU868", limit: 0.01 });
  assert.equal(v.verdict, "non_mesure");
  assert.equal(v.conforme, null);
});

test("la réserve accompagne le verdict et n'en est pas séparable", () => {
  // La limite se compare à une occupation moyennée sur la fenêtre du texte réglementaire ;
  // le run s'observe sur la sienne. Un verdict sans cette réserve serait surinterprété.
  assert.ok(RESERVE_DUTY_CYCLE.includes("moyennage"));
  assert.ok(RESERVE_DUTY_CYCLE.includes("fenêtre du run"));
});

test("jointure des limites : groupe inconnu, résumé vide", () => {
  assert.equal(limitesParGroupe({}).size, 0);
  assert.equal(limitesParGroupe(undefined).size, 0);
  assert.equal(limitesParGroupe({ duty_cycle: [{ group: "a", limit: 0.01 }, { limit: 0.02 }] }).size, 1);
});

test("table de ventilation : la colonne Limite dit le verdict, pas seulement le nombre", () => {
  const g = Object.fromEntries(
    ventilationGroupes(FIXTURE.devices, FENETRE).map((x) => [x.name, x]));
  const t = ventilationTable([g["capteurs-proches"], g["capteurs-lointains"]], LIMITES);
  // Dix colonnes annoncées, dix cellules : une table désalignée se voit ici.
  for (const ligne of t.lignes) assert.equal(ligne.length, t.entetes.length);
  const limite = t.lignes[0].at(-1);
  assert.match(limite, /^1\.000 % · conforme$/);
});

test("table de ventilation : sans limite publiée, la case reste vide et non à 100 %", () => {
  const g = Object.fromEntries(
    ventilationGroupes(FIXTURE.devices, FENETRE).map((x) => [x.name, x]));
  const t = ventilationTable([g["capteurs-proches"]], new Map());
  const limite = t.lignes[0].at(-1);
  assert.equal(limite, "—");
  assert.notEqual(limite, "100 %");
});

// --- Fenetre de mesure, dite a cote du verdict ----------------------------------------------
//
// Le verdict compare une occupation mesuree sur la fenetre du run a une limite moyennee sur
// celle du texte reglementaire. Afficher l'ecart entre les deux fenetres ne corrige pas la
// comparaison, mais rend son interpretable : c'est tout l'objet de ces fonctions.

const NS = 1e9;

test("une duree se lit dans l'unite ou l'on parle d'une fenetre", () => {
  assert.equal(dureeTexte(40 * NS), "40 s");
  assert.equal(dureeTexte(400 * NS), "6 min 40 s");
  assert.equal(dureeTexte(3600 * NS), "1 h");
  assert.equal(dureeTexte(9000 * NS), "2 h 30 min");
});

test("une duree nulle ou non finie n'est pas une duree", () => {
  assert.equal(dureeTexte(0), null);
  assert.equal(dureeTexte(-5 * NS), null);
  assert.equal(dureeTexte(NaN), null);
  assert.equal(dureeTexte(null), null);
});

test("la fenetre du run est nommee, pas sous-entendue", () => {
  const texte = fenetreVerdictTexte(400 * NS);
  assert.match(texte, /6 min 40 s/);
});

test("l'ecart avec l'heure reglementaire est chiffre, pas suggere", () => {
  // « 9 fois plus long » : 3600 / 400. Un rapport donne sent la fenetre ; « plus court »
  // ne permettrait pas de juger.
  assert.match(fenetreVerdictTexte(400 * NS), /9 fois plus long/);
});

test("un run plus long que l'heure reglementaire rend la comparaison directe", () => {
  const texte = fenetreVerdictTexte(9000 * NS);
  assert.match(texte, /2 h 30 min/);
  assert.match(texte, /comparaison est directe/);
});

test("la fenetre de moyennage est nommee, pas sous-entendue", () => {
  // Le mot porte la reserve : c'est la grandeur du texte a laquelle on compare. Le test
  // d'integration le verifie aussi, et il s'est deja pris le verbe « moyenne » pour le nom.
  assert.match(fenetreVerdictTexte(400 * NS), /moyennage/);
  assert.match(fenetreVerdictTexte(9000 * NS), /moyennage/);
  assert.match(fenetreVerdictTexte(null), /moyennage/);
});

test("la reserve generale ne s'affiche pas quand la fenetre est connue", () => {
  // L'ancienne phrase disait « qui n'est pas forcement » : elle laissait croire au pire sans
  // rien mesurer. Avec la fenetre, on ne l'emploie plus.
  assert.doesNotMatch(fenetreVerdictTexte(400 * NS), /n'est pas forcement/);
  assert.doesNotMatch(fenetreVerdictTexte(9000 * NS), /n'est pas forcement/);
});

test("sans fenetre connue, on retombe sur la reserve", () => {
  // Mieux vaut une reserve qu'un silence : le verdict resterait surinterprete sans rien dire.
  const texte = fenetreVerdictTexte(null);
  assert.match(texte, /fenêtre du run/);
  assert.match(texte, /réglementaire/);
});

test("un run exactement a l'heure est traite comme couvrant la fenetre", () => {
  assert.match(fenetreVerdictTexte(FENETRE_ETSI_S * NS), /comparaison est directe/);
  assert.match(fenetreVerdictTexte((FENETRE_ETSI_S - 1) * NS), /fois plus long/);
});

// --- Autonomie ------------------------------------------------------------------------------
//
// Le simulateur fournit le courant moyen ; la capacite est celle de la pile que l'utilisateur
// enonce. Ni un cote ni l'autre n'invente une grandeur, et c'est ce qui distingue ce calcul
// d'une estimation. La fonction doit donc rester muette des qu'un terme manque : un chiffre
// d'autonomie sorti de rien aurait l'air mesure.

test("l'autonomie se calcule depuis un courant simule et une capacite enoncee", () => {
  // 51,96 uA est le courant moyen mesure sur un run reel (rak4631, SF9, periode 300 s).
  const ans = autonomieAns(2400, 51.96274176);
  assert.ok(Math.abs(ans - 5.27) < 0.01, `attendu ~5,27 ans, obtenu ${ans}`);
});

test("l'autonomie est proportionnelle a la capacite", () => {
  assert.ok(Math.abs(autonomieAns(4800, 52) - 2 * autonomieAns(2400, 52)) < 1e-9);
});

test("l'autonomie est inversement proportionnelle au courant", () => {
  assert.ok(Math.abs(autonomieAns(2400, 104) - autonomieAns(2400, 52) / 2) < 1e-9);
});

test("sans capacite, il n'y a pas d'autonomie : pas de pile devinee", () => {
  assert.equal(autonomieAns(null, 52), null);
  assert.equal(autonomieAns(0, 52), null);
  assert.equal(autonomieAns(-5, 52), null);
  assert.equal(autonomieAns(NaN, 52), null);
});

test("sans courant simule, il n'y a pas d'autonomie", () => {
  assert.equal(autonomieAns(2400, null), null);
  assert.equal(autonomieAns(2400, 0), null);
  assert.equal(autonomieAns(2400, -1), null);
});

test("une capacite a virgule est acceptee, c'est une grandeur reelle", () => {
  assert.ok(autonomieAns(2400.5, 52) > 0);
});

test("sous un an, on dit les mois : une division de tete epargnee", () => {
  // 0,5 an = 6 mois. « 0,5 an » obligerait a convertir pour sentir la duree.
  assert.equal(autonomieTexte(0.5), "6 mois");
  // Un an s'accorde au singulier : « 1,0 ans » se lit comme une faute et distrait du chiffre.
  assert.equal(autonomieTexte(1), "1,0 an");
  // Sous deux, le francais reste au singulier : « 1,5 ans » est une faute, pas un usage.
  assert.equal(autonomieTexte(1.5), "1,5 an");
  assert.equal(autonomieTexte(2.4), "2,4 ans");
});

test("sous un mois, on dit les jours", () => {
  assert.equal(autonomieTexte(0.02), "7 jours");
});

test("au-dela de dix ans, on arrondit : la decimale n'y veut rien dire", () => {
  assert.equal(autonomieTexte(12.4), "12 ans");
});

test("une autonomie non calculable ne s'affiche pas", () => {
  assert.equal(autonomieTexte(null), null);
  assert.equal(autonomieTexte(0), null);
  assert.equal(autonomieTexte(-3), null);
});

// --- Bilan ADR : le changement de débit, tel qu'observé ---------------------------------------
//
// Le but n'est pas de compter des lignes mais de garantir la règle qui rend l'encadré honnête :
// on n'annonce que ce que le run a observé, jamais ce que le formulaire a demandé.

test("le bilan ADR ne retient que les dispositifs dont le SF a changé", () => {
  const rows = [
    { device_index: 0, group: "c1", spreading_factor: 12, final_spreading_factor: 7 },
    { device_index: 1, group: "c2", spreading_factor: 12, final_spreading_factor: 12 },
  ];
  const bilan = bilanAdr(rows, []);
  assert.equal(bilan.length, 1);
  assert.equal(bilan[0].deviceIndex, 0);
  assert.equal(bilan[0].depart, 12);
  assert.equal(bilan[0].fin, 7);
  assert.equal(bilan[0].baisse, true);      // SF plus bas : le serveur l'a fait monter en débit
  assert.equal(bilan[0].hausse, false);
});

test("un SF final absent n'est pas un changement, même s'il diffère du départ", () => {
  // Voie multi-passerelles : le run n'observe pas la fin. Recopier le départ serait faire
  // croire à une mesure là où il n'y en a pas.
  const rows = [{ device_index: 0, group: "c1", spreading_factor: 12, final_spreading_factor: null }];
  assert.deepEqual(bilanAdr(rows, []), []);
  // Et une ligne sans champ du tout ne lève pas.
  assert.deepEqual(bilanAdr([{ device_index: 0 }], []), []);
});

test("le bilan nomme l'équipement plutôt que l'identifiant de groupe", () => {
  const rows = [{ device_index: 0, group: "capteur-1", spreading_factor: 9, final_spreading_factor: 12 }];
  const noeuds = [{ id: "capteur-1", name: "Capteur nord" }];
  const bilan = bilanAdr(rows, noeuds);
  assert.equal(bilan[0].nom, "Capteur nord");
  assert.equal(bilan[0].hausse, true);      // SF plus haut : le serveur l'a fait descendre
});

test("un run sans changement donne un bilan vide, pas un bilan nul", () => {
  const rows = [
    { device_index: 0, group: "c1", spreading_factor: 12, final_spreading_factor: 12 },
    { device_index: 1, group: "c2", spreading_factor: 7, final_spreading_factor: 7 },
  ];
  assert.deepEqual(bilanAdr(rows, []), []);
  assert.deepEqual(bilanAdr([], [{ id: "c1" }]), []);
});

// --- Idem pour la puissance : l'autre moitié de la commande -------------------------------------
//
// Le serveur décide le débit **et** la puissance. Ne montre que le débit, et l'atelier tait
// le versant autonomie : −14 dB, c'est l'essentiel de ce que l'ADR apporte à une pile.

test("une baisse de puissance seul suffit à retenir le dispositif", () => {
  // Débit inchangé : le terminal reste au SF7, mais le serveur lui a retiré 14 dB.
  const rows = [{ device_index: 0, group: "c1", spreading_factor: 7, final_spreading_factor: 7,
                  power_index: 0, final_power_index: 7, power_step_db: 2 }];
  const bilan = bilanAdr(rows, []);
  assert.equal(bilan.length, 1, "une baisse de puissance sans changement de SF doit se voir");
  assert.equal(bilan[0].puissance.reductionDb, 14);
  assert.equal(bilan[0].debitObserve, true);
  assert.equal(bilan[0].baisse, false);
  assert.equal(bilan[0].hausse, false);
});

test("la réduction vaut l'écart d'indices multiplié par le pas du plan", () => {
  const rows = [{ device_index: 0, group: "c1", spreading_factor: 12, final_spreading_factor: 7,
                  power_index: 1, final_power_index: 4, power_step_db: 2 }];
  const bilan = bilanAdr(rows, []);
  assert.equal(bilan[0].puissance.reductionDb, 6);        // (4 - 1) × 2 dB
  assert.equal(bilan[0].puissance.indexDepart, 1);
  assert.equal(bilan[0].puissance.indexFin, 4);
});

test("une hausse de puissance donne une réduction négative, pas une valeur cachée", () => {
  // Le serveur remonte la puissance : margin insuffisante. Le signe doit le dire.
  const rows = [{ device_index: 0, group: "c1", spreading_factor: 9, final_spreading_factor: 9,
                  power_index: 5, final_power_index: 2, power_step_db: 2 }];
  assert.equal(bilanAdr(rows, [])[0].puissance.reductionDb, -6);
});

test("un seul terme de puissance manquant et le bilan n'en parle pas", () => {
  // Mieux vaut ne rien dire qu'annoncer une réduction calculée sur un pas inconnu.
  const complet = { device_index: 0, group: "c1", spreading_factor: 12, final_spreading_factor: 7 };
  const cas = [
    { ...complet, power_index: 0, final_power_index: 7 },                 // pas de pas
    { ...complet, power_index: 0, power_step_db: 2 },                     // pas d'indice final
    { ...complet, final_power_index: 7, power_step_db: 2 },               // pas d'indiceinitial
    { ...complet, power_index: 0, final_power_index: 7, power_step_db: 0 },  // pas nul : division
    { ...complet, power_index: null, final_power_index: 7, power_step_db: 2 },
  ];
  for (const rows of cas) {
    const bilan = bilanAdr([rows], []);
    assert.equal(bilan.length, 1, "le changement de débit reste annoncé");
    assert.equal(bilan[0].puissance, null);
  }
});

test("ni débit ni puissance : le dispositif n'entre pas dans le bilan", () => {
  const rows = [{ device_index: 0, group: "c1", spreading_factor: 12, final_spreading_factor: 12,
                  power_index: 3, final_power_index: 3, power_step_db: 2 }];
  assert.deepEqual(bilanAdr(rows, []), []);
});

// --- Jointure OTAA et trames confirmées -------------------------------------------------------
//
// Les nombres de ce bloc sont ceux qu'on lirait à l'œil dans une trace. Le seul piège est de
// ne pas les confondre : une tentative n'est pas une acceptation, et un uplink sans ACK n'est
// pas un ACK perdu.

test("la jointure compte les tentatives et les acceptations séparément", () => {
  const ev = [
    { kind: "join_request" }, { kind: "join_accept" },
    { kind: "join_request" }, { kind: "join_accept" },
    { kind: "join_request" },          // une demande de plus : un terminal a dû recommencer
    { kind: "uplink" }, { kind: "uplink" },
  ];
  const { jointure } = bilanProtocole(ev);
  assert.equal(jointure.demandes, 3);
  assert.equal(jointure.acceptees, 2);
  assert.equal(jointure.tentativesDeplus, 1);
  assert.equal(jointure.aucune, false);
});

test("une flotte qui n'obtient aucune acceptation est signalée", () => {
  // Trente demandes, aucune acceptation : c'est le cas d'école (tout le monde joint au même
  // instant) et il doit sauter aux yeux plutôt que se lire comme « 0 jointure réussie ».
  const ev = Array.from({ length: 30 }, () => ({ kind: "join_request" }));
  const { jointure } = bilanProtocole(ev);
  assert.equal(jointure.demandes, 30);
  assert.equal(jointure.acceptees, 0);
  assert.equal(jointure.aucune, true);
});

test("les uplinks sans ACK sont comptés sans accuser la descente", () => {
  // Un `ack` n'existe que pour un uplink **reçu**. 24 acquittés sur 30 uplinks : les 6
  // manquants n'ont pas perdu leur ACK, ils ne sont jamais arrivés au serveur.
  const ev = [
    ...Array.from({ length: 30 }, () => ({ kind: "uplink" })),
    ...Array.from({ length: 24 }, () => ({ kind: "ack" })),
  ];
  const { confirme } = bilanProtocole(ev);
  assert.equal(confirme.uplinks, 30);
  assert.equal(confirme.acquittes, 24);
  assert.equal(confirme.sansReponse, 6);
});

test("un run sans jointure ni confirmation donne des compteurs nuls, pas d'erreur", () => {
  const { jointure, confirme } = bilanProtocole([{ kind: "uplink" }, { kind: "downlink" }]);
  assert.deepEqual(jointure, { demandes: 0, acceptees: 0, tentativesDeplus: 0, aucune: false });
  assert.deepEqual(confirme, { uplinks: 1, acquittes: 0, sansReponse: 1 });
  const vide = bilanProtocole([]);
  assert.equal(vide.jointure.aucune, false);   // aucune demande : pas « aucune acceptation »
  assert.equal(vide.confirme.uplinks, 0);
});

// --- Canaux laissés au terminal -------------------------------------------------------------
// Le plan de canaux vient de l'ABI v3 : c'est le même LinkADRReq qui porte le débit et le
// masque. Deux confusions sont à éviter, et elles sont testées ici : un canal défini n'est
// pas forcément actif, et un masque n'est pas forcément une plage contiguë de débits.

test("le plan de canaux est nul quand le run n'en porte pas", () => {
  // Hors boucle fermée, annoncer un plan ferait croire à une décision du serveur.
  assert.equal(planCanaux([]), null);
  assert.equal(planCanaux([{ device_index: 0 }]), null);
  assert.equal(planCanaux([{ enabled_channels: [] }]), null);
});

test("les canaux actifs sont ceux de l'émission, pas tous les canaux définis", () => {
  const plan = planCanaux([{ device_index: 0, enabled_channels: [0, 2],
                             channel_dr_masks: { 0: 0b111111, 1: 0b111111, 2: 0b111 } }]);
  assert.deepEqual(plan.actifs, [0, 2]);
  // Le canal 1 est défini mais absent d'`enabled_channels` : il ne doit pas paraître.
  assert.deepEqual(plan.parCanal.map((c) => c.canal), [0, 2]);
  assert.deepEqual(plan.parCanal[0].drs, [0, 1, 2, 3, 4, 5]);
  assert.deepEqual(plan.parCanal[1].drs, [0, 1, 2]);
});

test("un masque non contigu énumère les débits au lieu de tirer un trait", () => {
  // 0b10000001 : DR0 et DR7 admis, rien entre les deux. « DR0 à DR7 » serait un mensonge.
  const plan = planCanaux([{ device_index: 0, enabled_channels: [0],
                             channel_dr_masks: { 0: 0b10000001 } }]);
  assert.deepEqual(plan.parCanal[0].drs, [0, 7]);
});

test("les clés de masque arrivent en texte depuis la JSON, et sont quand même lues", () => {
  // La JSON n'a pas de clé entière : le serveur publie « 0 », pas 0.
  const plan = planCanaux([{ device_index: 0, enabled_channels: [1],
                             channel_dr_masks: { 1: 0b1111 } }]);
  assert.deepEqual(plan.parCanal[0].drs, [0, 1, 2, 3]);
});

test("un plan qui diverge d'un terminal à l'autre est signalé, pas masqué", () => {
  const identiques = planCanaux([
    { device_index: 0, enabled_channels: [0, 1], channel_dr_masks: { 0: 63, 1: 63 } },
    { device_index: 1, enabled_channels: [1, 0], channel_dr_masks: { 0: 63, 1: 63 } }]);
  assert.equal(identiques.homogene, true);      // même ensemble, ordre différent
  const divergents = planCanaux([
    { device_index: 0, enabled_channels: [0, 1], channel_dr_masks: { 0: 63, 1: 63 } },
    { device_index: 1, enabled_channels: [0], channel_dr_masks: { 0: 63 } }]);
  assert.equal(divergents.homogene, false);
  assert.equal(divergents.terminaux, 2);
});
