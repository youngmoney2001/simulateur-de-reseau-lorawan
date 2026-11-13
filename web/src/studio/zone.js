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
 * De combien la **portée** se réduit dans une direction, entre 0 et 1 (1 sur l'axe).
 *
 * Ce n'est pas `facteurLobe`, et la différence compte. Celui-ci est un rapport de
 * puissance : à −25 dB il vaut 0,003, si bien qu'une vague tracée à cette échelle
 * disparaîtrait dans le dos de l'antenne. Or une vague doit rester visible partout —
 * c'est justement **l'inégalité** de son étalement qu'on veut lire, pas une zone morte.
 *
 * Ce que la vue veut, c'est le rapport des portées : de combien le front recule quand
 * le budget perd `db`. Le moteur passe de l'un à l'autre par l'exposant de propagation
 * (log-distance), où l'atténuation vaut `10 n log10(d)` : une perte de `db` retire donc
 * `db / (10 n)` décades à la distance. Avec `n = 2,5`, −30 dB donne 0,063 au lieu de
 * 0,001 — le lobe se lit, et le front reste présent dans toutes les directions.
 *
 * Plus `n` est haut, plus le lobe paraît **doux** à l'écran : dans un milieu très
 * atténuant la portée est courte et varie moins vite avec le budget, donc l'écart relatif
 * entre l'axe et le dos se resserre. C'est conforme au modèle, ce n'est pas un lissage
 * qu'on se serait accordé pour faire joli.
 *
 * @param {number} exposant exposant de propagation du scénario (2,5 en urbain)
 * @returns {number|null} `null` si l'antenne ou l'exposant est inexploitable
 */
export const EXPOSANT_PROPAGATION = 2.5;

export function facteurPortee(antenne, azimuthDeg, exposant = EXPOSANT_PROPAGATION) {
  const db = attenuationLobeDb(antenne, azimuthDeg);
  if (db === null) return null;
  if (!Number.isFinite(exposant) || !(exposant > 0)) return null;
  return Math.pow(10, -db / (10 * exposant));
}

/**
 * Contour d'une vague : un anneau dont chaque point est à `rayon · facteurPortee(θ)`.
 *
 * Ni la zone de couverture, ni le diagramme de la fiche technique : c'est le front d'une
 * onde, à l'instant qu'on regarde. Il s'étire dans le secteur de l'antenne et recule dans
 * son dos — sans jamais s'annuler, faute de quoi une antenne directive semblerait ne rien
 * émettre du tout dans trois quarts des directions.
 *
 * @param {number} rayon échelle du tracé, en mètres
 * @param {number} azimuths nombre de points de l'anneau
 * @param {number} exposant exposant de propagation du scénario
 */
export function contourVague(antenne, centre, rayon, azimuths = 72, exposant) {
  if (!Number.isFinite(rayon) || rayon <= 0) return [];
  if (!Number.isFinite(centre?.x_m) || !Number.isFinite(centre?.y_m)) return [];
  const out = [];
  for (let k = 0; k < azimuths; k += 1) {
    const a = (2 * Math.PI * k) / azimuths;
    // Une antenne inexploitable donne `null` : on trace alors le rayon plein plutôt que
    // zéro, qui dessinerait une vague écrasée au centre. Omnidirectionnelle par défaut,
    // jamais silencieusement directive.
    const f = facteurPortee(antenne, (360 * k) / azimuths, exposant) ?? 1;
    out.push({ x: centre.x_m + rayon * f * Math.cos(a), y: centre.y_m + rayon * f * Math.sin(a) });
  }
  if (out.length) out.push({ ...out[0] });
  return out;
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
 * De quoi lire une zone en chiffres, pas seulement en couleurs.
 *
 * Une portée n'est pas un seul nombre dès que l'antenne est directive ou que le relief
 * n'est pas plat : `radii_m` compte un rayon par azimut. Donner le minimum et le maximum
 * dit « la zone va de 340 m à 1 200 m », ce qui est vrai ; n'en donner que la moyenne, ou
 * le maximum seul, décrirait une zone qui n'est pas celle qui est tracée.
 *
 * @param {object} couverture une `GatewayCoverage` du serveur
 * @returns {{modele: string, paliers: Array<{qualite: string, marge_db: number,
 *   min_m: number, max_m: number, circulaire: boolean}>}|null}
 */
export function bilanZone(couverture) {
  const paliers = couverture?.paliers ?? [];
  if (!paliers.length) return null;
  const out = [];
  for (const p of paliers) {
    const rayons = (p.radii_m ?? []).filter((r) => Number.isFinite(r));
    if (!rayons.length) continue;
    const min = Math.min(...rayons);
    const max = Math.max(...rayons);
    out.push({ qualite: p.qualite, marge_db: p.marge_db, min_m: min, max_m: max,
      // Assez proche d'un disque pour être annoncé comme tel : au-delà, dire « jusqu'à »
      // pour un seul nombre serait trompeur.
      circulaire: max > 0 && (max - min) / max < 0.02 });
  }
  return out.length ? { modele: couverture.modele ?? "", paliers: out } : null;
}

/** Portée d'un palier, en mots : un nombre si la zone est ronde, un intervalle sinon. */
export function porteeTexte(palier, { unite = "m" } = {}) {
  const arrondi = (v) => (v >= 1000 ? `${(v / 1000).toFixed(1)} km` : `${Math.round(v)} ${unite}`);
  if (palier.circulaire) return arrondi(palier.max_m);
  return `${arrondi(palier.min_m)} à ${arrondi(palier.max_m)}`;
}

/**
 * Étiquette lisible d'une antenne déclarée, ou `null` si elle n'a rien de particulier.
 *
 * Rien n'est inventé : une antenne absente est « omnidirectionnelle », pas une ligne vide —
 * le moteur la traite ainsi, la fenêtre doit le dire.
 */
export function etiquetteAntenne(antenne) {
  if (!antenne) return "omnidirectionnelle";
  const genre = antenne.kind ?? "omnidirectionnelle";
  if (genre === "omnidirectionnelle") return "omnidirectionnelle";
  const ouverture = Number(antenne.beamwidth_deg);
  const axe = Number(antenne.pointing_deg);
  const nom = { unidirectionnelle: "unidirectionnelle", bidirectionnelle: "bidirectionnelle",
    sectorielle: "sectorielle" }[genre] ?? genre;
  if (!Number.isFinite(ouverture)) return nom;
  const ouvertureTxt = `${ouverture}°`;
  // L'azimut n'a de sens que dans le repère du plan : 0° = l'est, comme le moteur.
  return Number.isFinite(axe)
    ? `${nom} ${ouvertureTxt}, axe à ${axe}°`
    : `${nom} ${ouvertureTxt}`;
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
