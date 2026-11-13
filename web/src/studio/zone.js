// Zone de couverture d'une antenne : la transformer en formes traçables.
//
// Ce module ne connaît ni Cesium ni le DOM, et c'est le sujet : le tracé d'un lobe est
// un calcul, pas un dessin. Le garder pur permet de le vérifier hors navigateur, comme
// `liaisons.js` le fait pour les liaisons observées.
//
// Deux formes sortent d'ici, et elles ne répondent pas à la même question :
//
//   * le **rayon de portée** par azimut, publié par le moteur (`GET /sessions/{sid}/coverage`).
//     C'est la vraie zone : relief, obstacles et lobe, le plus contraignant bornant. Le
//     plan 2D et la carte 3D tracent le même calcul, comme pour les liaisons — deux vues
//     qui ne disent pas la même chose sont pires qu'une seule.
//
//   * le **diagramme de rayonnement** seul, calculé ici en miroir du noyau C++
//     (`core/src/antenna.cpp`). C'est la forme du lobe, sans le terrain : elle sert aux
//     vagues de l'animation, qui doivent montrer **l'antenne**, pas la portée. Une vague
//     qui s'arrêterait à la portée exacte laisserait croire à un mur.

// Paliers de qualité, dans l'ordre du plus exigeant au plus large. Les marges sont
// celles du serveur (`COVERAGE_TIERS` de `study_contract`) : les recopier ici serait
// les figer deux fois, on se contente donc de connaître leurs noms.
export const QUALITES = ["excellent", "bon", "limite"];

// Teintes des paliers, du plus sûr au plus précaire. Une seule famille de couleurs pour
// que « meilleur » se lise d'un coup d'œil, sans avoir à interpréter une nuance.
export const COULEURS_QUALITE = {
  excellent: "#2ea043",
  bon: "#d29922",
  limite: "#cf6a3b",
};

/**
 * Anneau de points (mètres, repère local) décrivant la zone d'une passerelle.
 *
 * @param {{radii_m: number[], qualite: string}} palier
 * @param {{x_m: number, y_m: number}} passerelle position de la passerelle, en mètres
 * @returns {Array<{x: number, y: number}>} anneau fermé (le dernier point répète le premier)
 */
export function anneauZone(palier, passerelle) {
  const rayons = palier?.radii_m;
  if (!Array.isArray(rayons) || rayons.length < 3) return [];
  if (!Number.isFinite(passerelle?.x_m) || !Number.isFinite(passerelle?.y_m)) return [];
  const out = [];
  for (let k = 0; k < rayons.length; k += 1) {
    // Azimut 0 = l'est, sens trigonométrique : la convention du moteur, et il n'y a
    // aucune raison que la vue en invente une autre.
    const a = (2 * Math.PI * k) / rayons.length;
    const r = rayons[k];
    if (!Number.isFinite(r)) return [];
    out.push({ x: passerelle.x_m + r * Math.cos(a), y: passerelle.y_m + r * Math.sin(a) });
  }
  if (out.length) out.push({ ...out[0] });
  return out;
}

/**
 * Anneau de portée maximale, pour cadrer une vue. `null` si rien n'est traçable.
 */
export function porteeMax(coverage) {
  const paliers = coverage?.paliers ?? [];
  let max = 0;
  for (const p of paliers) {
    for (const r of p.radii_m ?? []) {
      if (Number.isFinite(r) && r > max) max = r;
    }
  }
  return max > 0 ? max : null;
}

// ---------------------------------------------------------------- diagramme

// Types d'antenne, et leurs entiers d'ABI. Les noms sont ceux du scénario, pas ceux du
// C++ : la vue parle la langue du fichier YAML.
const GENRES = new Set(["omnidirectionnelle", "unidirectionnelle", "bidirectionnelle",
  "sectorielle"]);

/**
 * Atténuation du lobe (dB, positive) dans une direction, miroir de `antenna.cpp`.
 *
 * La formule est celle du 3GPP TR 36.814 : `min(12 · (e / ouverture)², Am)`, où `e` est
 * mesuré depuis l'axe sur une directive et depuis le **bord du secteur** sur une
 * sectorielle — c'est cette différence qui donne un sommet plat à l'une et un pic à
 * l'autre.
 *
 * @returns {number} atténuation positive, ou `null` si l'antenne est inexploitable
 */
export function attenuationLobeDb(antenne, azimuthDeg) {
  if (!antenne) return 0;
  const genre = antenne.kind ?? "omnidirectionnelle";
  if (!GENRES.has(genre)) return null;
  if (!Number.isFinite(azimuthDeg)) return null;
  if (genre === "omnidirectionnelle") return 0;

  const ouverture = Number(antenne.beamwidth_deg);
  const plancher = Number(antenne.front_to_back_db);
  const axe = Number(antenne.pointing_deg);
  if (!Number.isFinite(ouverture) || !(ouverture > 0)) return null;
  if (!Number.isFinite(plancher)) return null;
  if (!Number.isFinite(axe)) return null;

  const secteur = genre === "sectorielle";
  const lobes = genre === "bidirectionnelle" ? [axe, axe + 180] : [axe];
  let meilleur = Infinity;
  for (const lobe of lobes) {
    let d = ((azimuthDeg - lobe) % 360 + 360) % 360;   // ramené à un tour
    if (d > 180) d = 360 - d;                          // on prend le côté le plus court
    const e = secteur ? Math.max(0, d - ouverture / 2) : d;
    meilleur = Math.min(meilleur, 12 * (e / ouverture) ** 2);
  }
  return Math.min(meilleur, plancher);
}

/**
 * Facteur de forme du lobe dans une direction, entre 0 et 1 (1 sur l'axe).
 *
 * Sert aux vagues : une vague sectorielle s'étire dans son secteur et meurt dans le dos
 * de l'antenne, au lieu de s'étaler en rond comme si l'antenne était un fouet.
 */
export function facteurLobe(antenne, azimuthDeg) {
  const db = attenuationLobeDb(antenne, azimuthDeg);
  if (db === null) return 0;
  return Math.pow(10, -db / 10);
}

/**
 * Contour du lobe à l'échelle `rayon` mètres : un anneau dont chaque point est à
 * `rayon · facteurLobe(θ)` de l'antenne. C'est le diagramme polaire de l'antenne, la
 * courbe qu'on voit sur une fiche technique — pas une zone de portée.
 *
 * @param {number} rayon échelle du tracé, en mètres
 * @param {number} azimuths nombre de points de l'anneau
 */
export function contourLobe(antenne, centre, rayon, azimuths = 180) {
  if (!Number.isFinite(rayon) || rayon <= 0) return [];
  if (!Number.isFinite(centre?.x_m) || !Number.isFinite(centre?.y_m)) return [];
  const out = [];
  for (let k = 0; k < azimuths; k += 1) {
    const a = (2 * Math.PI * k) / azimuths;
    const r = rayon * facteurLobe(antenne, (360 * k) / azimuths);
    out.push({ x: centre.x_m + r * Math.cos(a), y: centre.y_m + r * Math.sin(a) });
  }
  if (out.length) out.push({ ...out[0] });
  return out;
}

/**
 * Étiquette lisible d'un palier. Un nom seul (« bon ») ne dit pas de quoi il est la
 * mesure : c'est une marge au-dessus du seuil de sensibilité.
 */
export function etiquettePalier(palier) {
  const q = palier?.qualite ?? "";
  const marge = Number(palier?.marge_db);
  if (q === "limite") return "limite de réception (marge nulle)";
  if (!Number.isFinite(marge)) return q;
  return `${q} : ${marge} dB de marge`;
}

/**
 * Ce qu'on écrit sur la zone : le modèle employé, parce qu'une zone « relief et
 * obstacles » et une zone « log-distance seul » ne se lisent pas de la même manière.
 */
export function etiquetteModele(modele) {
  return modele === "environment" ? "relief et obstacles" : "log-distance seul";
}
