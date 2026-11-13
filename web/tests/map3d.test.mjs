// La carte 3D du studio, exercée hors navigateur grâce au faux Cesium de
// `cesium-stub.mjs`. Ce qu'on vérifie ici, ce sont les **décisions** de la carte :
// quelles entités elle crée, posées où, et ce qu'elle fait quand une pièce manque.
import "./cesium-stub.mjs";
import test from "node:test";
import assert from "node:assert/strict";

const { createMap3D } = await import("../src/studio/map3d.js");

const ORIGINE = { lat: 4.0511, lon: 9.7679 };

function carte() {
  const c = createMap3D({}, null);
  c.setOrigin(ORIGINE);
  return c;
}

/**
 * Un MNT `lsim-dem-v1` de test : un plan incliné, lisible — l'altitude vaut `y` en
 * mètres, si bien qu'un pavé posé au nord est plus haut qu'un pavé posé au sud.
 * Mieux qu'une constante : la valeur attendue se déduit, elle ne se mémorise pas.
 */
function mnt({ nx = 9, ny = 9, cell = 100, x0 = -400, y0 = -400 } = {}) {
  const z = new Float32Array(nx * ny);
  for (let j = 0; j < ny; j += 1) {
    for (let i = 0; i < nx; i += 1) z[j * nx + i] = y0 + j * cell;
  }
  return {
    format: "lsim-dem-v1",
    origin: { latitude: ORIGINE.lat, longitude: ORIGINE.lon },
    origin_x_m: x0, origin_y_m: y0, cell_m: cell, nx, ny,
    encoding: "float32-le-base64",
    z: Buffer.from(z.buffer).toString("base64"),
  };
}

test("sans relief, la carte reste sur l'ellipsoide plate", () => {
  const c = carte();
  c.setTerrain(null);
  assert.equal(c.aRelief(), false);
  assert.equal(c.viewer.terrainProvider.plat, true);
});

test("un MNT valide arme le fournisseur de hauteurs local", () => {
  const c = carte();
  c.setTerrain({ terrain_id: "colline", dem: mnt() });
  assert.equal(c.aRelief(), true);
  // Pas un ellipsoïde : une grille locale, servie par nos propres tuiles.
  assert.equal(c.viewer.terrainProvider.plat, undefined);
  assert.equal(c.viewer.terrainProvider.width, 65);
});

test("un MNT illisible n'est pas avale en silence", () => {
  const c = carte();
  // Une carte restée plate en laissant croire à un relief chargé est pire qu'une
  // erreur franche : l'utilisateur chercherait la panne ailleurs.
  assert.throws(() => c.setTerrain({ dem: { format: "inconnu" } }), /lsim-dem-v1/);
  assert.equal(c.aRelief(), false);
});

test("chaque obstacle devient un pave pose sur le sol le plus bas de son emprise", () => {
  const c = carte();
  c.setObstacles([
    { x_min_m: -50, y_min_m: -50, x_max_m: 50, y_max_m: 50, height_m: 20, attenuation_db: 6 },
    { x_min_m: 100, y_min_m: 100, x_max_m: 200, y_max_m: 200, height_m: 8 },
  ]);
  const pav = c.obstacles();
  assert.equal(pav.length, 2);
  // Sans relief, le sol vaut zéro : le pavé part de zéro.
  assert.equal(pav[0].polygon.height, 0);
  assert.equal(pav[0].polygon.extrudedHeight, 20);
  // Une atténuation absente n'est pas un zéro inventé.
  assert.match(pav[1].description, /0 dB/);
  assert.match(pav[0].description, /6 dB/);
});

test("les obstacles refaits apres le relief reposent sur le sol, plus sur zero", () => {
  // Le pavé est au nord, donc sur la partie haute de la rampe : son sol vaut plus de
  // 100 m. Le même pavé au sud serait à une altitude négative — c'est le relief qui
  // décide, pas une constante.
  const c = carte();
  // Ordre réel d'un chargement : les murs arrivent avec la topologie, le relief ensuite,
  // par une requête séparée. Sans rattrapage, les pavés flotteraient.
  c.setObstacles([
    { x_min_m: -50, y_min_m: 100, x_max_m: 50, y_max_m: 200, height_m: 20 },
  ]);
  const plat = c.obstacles()[0];
  assert.equal(plat.polygon.height, 0);
  c.setTerrain({ terrain_id: "colline", dem: mnt() });
  const refait = c.obstacles();
  assert.equal(refait.length, 1);
  assert.ok(refait[0].polygon.height > 0, "le pavé doit reposer sur le sol, pas sur zéro");
  assert.equal(refait[0].polygon.extrudedHeight,
    refait[0].polygon.height + 20, "la hauteur s'ajoute au sol, elle ne le remplace pas");
});

test("un obstacle aux coordonnees inexploitables est ignore, pas trace n'importe ou", () => {
  const c = carte();
  c.setObstacles([
    { x_min_m: NaN, y_min_m: 0, x_max_m: 10, y_max_m: 10, height_m: 5 },
    { x_min_m: 0, y_min_m: 0, x_max_m: 10, y_max_m: 10, height_m: 5 },
  ]);
  assert.equal(c.obstacles().length, 1);
});

test("vider les obstacles les retire de la carte", () => {
  const c = carte();
  c.setObstacles([{ x_min_m: 0, y_min_m: 0, x_max_m: 10, y_max_m: 10, height_m: 5 }]);
  assert.equal(c.obstacles().length, 1);
  c.setObstacles([]);
  assert.equal(c.obstacles().length, 0);
});

test("une zone se trace par palier, posee sur le sol", () => {
  const c = carte();
  c.setNodes([{ id: "gw1", kind: "gateway", x_m: 0, y_m: 0 }]);
  c.setCoverage([{
    node_id: "gw1", modele: "environment",
    paliers: [
      { qualite: "limite", marge_db: 0, radii_m: Array(36).fill(900) },
      { qualite: "bon", marge_db: 6, radii_m: Array(36).fill(600) },
      { qualite: "excellent", marge_db: 12, radii_m: Array(36).fill(300) },
    ],
  }]);
  const zones = c.couvertures();
  assert.equal(zones.length, 3);
  // Du plus large au plus serré : le meilleur palier reste lisible par-dessus les autres.
  // 36 rayons, 37 sommets : l'anneau est refermé, sinon Cesium tracerait un secteur.
  assert.deepEqual(zones.map((z) => z.polygon.hierarchy.positions.length), [37, 37, 37]);
  for (const z of zones) assert.equal(z.polygon.clampToGround, true);
  assert.equal(zones[0].name, "Zone limite — gw1");
  assert.equal(zones[2].name, "Zone excellent — gw1");
  // Le modèle est dit en clair : une zone calculée avec le relief ne se présente pas
  // comme une zone calculée à plat.
  assert.match(zones[0].description, /relief et obstacles/);
});

test("une passerelle absente de la topologie ne trace aucune zone", () => {
  const c = carte();
  c.setNodes([{ id: "gw1", kind: "gateway", x_m: 0, y_m: 0 }]);
  c.setCoverage([{
    node_id: "fantome", modele: "log_distance",
    paliers: [{ qualite: "limite", marge_db: 0, radii_m: Array(36).fill(500) }],
  }]);
  assert.equal(c.couvertures().length, 0);
});

test("un palier aux rayons inexploitables est passe, pas trace a zero", () => {
  const c = carte();
  c.setNodes([{ id: "gw1", kind: "gateway", x_m: 0, y_m: 0 }]);
  c.setCoverage([{
    node_id: "gw1", modele: "log_distance", paliers: [
      { qualite: "limite", marge_db: 0, radii_m: Array(36).fill(500) },
      { qualite: "bon", marge_db: 6, radii_m: [1, 2] },        // trop court pour un anneau
      { qualite: "excellent", marge_db: 12, radii_m: Array(36).fill(Number.NaN) },
    ],
  }]);
  // Un disque de rayon nul dessinerait une tache au centre : ce serait une zone fausse.
  assert.equal(c.couvertures().length, 1);
});

test("la portee affichee est la plus grande des zones, et null sans zone", () => {
  const c = carte();
  assert.equal(c.porteeZone(), null);
  c.setNodes([{ id: "gw1", kind: "gateway", x_m: 0, y_m: 0 }]);
  c.setCoverage([{
    node_id: "gw1", modele: "log_distance",
    paliers: [{ qualite: "limite", marge_db: 0, radii_m: Array(36).fill(1200) }],
  }]);
  assert.equal(c.porteeZone(), 1200);
  c.setCoverage([]);
  assert.equal(c.porteeZone(), null);
});

test("les zones sont retracees quand le relief arrive apres les equipements", () => {
  const c = carte();
  c.setNodes([{ id: "gw1", kind: "gateway", x_m: 0, y_m: 0 }]);
  c.setCoverage([{
    node_id: "gw1", modele: "log_distance",
    paliers: [{ qualite: "limite", marge_db: 0, radii_m: Array(36).fill(700) }],
  }]);
  assert.equal(c.couvertures().length, 1);
  c.setTerrain({ terrain_id: "colline", dem: mnt() });
  // Le relief refait les obstacles ; les zones doivent suivre, pas disparaître.
  assert.equal(c.couvertures().length, 1);
  assert.equal(c.porteeZone(), 700);
});
