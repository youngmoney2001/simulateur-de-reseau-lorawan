// Conversion entre les mètres du moteur et les degrés de la carte.
//
// Le moteur radio raisonne en mètres autour d'une origine ; la carte, et l'utilisateur,
// raisonnent en degrés. Ce module est volontairement **sans dépendance** : ni Cesium, ni
// DOM. C'est ce qui permet de tester la conversion exactement, alors que `map3d.js` — qui
// importe Cesium — ne peut pas être chargé hors d'un navigateur.
//
// Les formules reprennent au signe près `_to_lonlat` et `_from_lonlat` du serveur
// (python/lsim/geo.py), pour qu'une position affichée ici soit celle que l'export produit.
// Toute divergence entre les deux ferait dériver la carte du plan sans que rien ne
// cloche visiblement : c'est l'invariant D2, et il est vérifié par un aller-retour.

/** Rayon terrestre sphérique, en mètres. Même constante que geo.py. */
export const EARTH_RADIUS_M = 6_371_000.0;

const DEG = Math.PI / 180;

/**
 * Mètres (plan) vers degrés (carte).
 * @param {number} x_m abscisse en mètres, positive vers l'est
 * @param {number} y_m ordonnée en mètres, positive vers le nord
 * @param {{lat: number, lon: number}} origine ancre géographique du plan
 */
export function metresVersDegres(x_m, y_m, origine) {
  const lat = origine.lat + (y_m / EARTH_RADIUS_M) / DEG;
  const lon = origine.lon + (x_m / (EARTH_RADIUS_M * Math.cos(origine.lat * DEG))) / DEG;
  return { lon, lat };
}

/**
 * Degrés (carte) vers mètres (plan). Inverse exact de `metresVersDegres`.
 * @param {number} lat
 * @param {number} lon
 * @param {{lat: number, lon: number}} origine
 */
export function degresVersMetres(lat, lon, origine) {
  const y_m = (lat - origine.lat) * DEG * EARTH_RADIUS_M;
  const x_m = (lon - origine.lon) * DEG * EARTH_RADIUS_M * Math.cos(origine.lat * DEG);
  return { x_m, y_m };
}

// Alias historiques : `map3d.js` et d'autres appellants utilisent les noms anglais.
export const toLonLat = metresVersDegres;
export const toMeters = degresVersMetres;

/** Une latitude est valide entre −90° et +90° ; une longitude entre −180° et +180°. */
export function estLatitude(v) {
  return Number.isFinite(v) && v >= -90 && v <= 90;
}

export function estLongitude(v) {
  return Number.isFinite(v) && v >= -180 && v <= 180;
}

/**
 * Distance en mètres entre deux points géographiques, par la formule de la sphère.
 * Sert à dire « cet équipement est à 320 m » — une mesure que l'utilisateur peut
 * confronter à ce qu'il voit sur la carte.
 */
export function distanceM(a, b) {
  const dLat = (b.lat - a.lat) * DEG;
  const dLon = (b.lon - a.lon) * DEG;
  const latM = (a.lat + b.lat) / 2 * DEG;
  // Formule des demi-versins : stable même pour deux points très proches, là où la
  // différence de cosinus perdrait ses décimales.
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(latM) ** 2 * Math.sin(dLon / 2) ** 2;
  return 2 * EARTH_RADIUS_M * Math.asin(Math.min(1, Math.sqrt(h)));
}

/**
 * Distingue la virgule décimale française de la virgule de séparation.
 *
 * Une virgule n'est décimale que si elle est collée à des chiffres des deux côtés **et** si
 * le nombre qu'elle coupe n'a pas déjà un point : dans « 4.0511,9.7679 » la virgule sépare
 * deux nombres à point, alors que dans « 4,0511 9,7679 » elle en sépare les décimales.
 * Sans cette seconde condition, « 4.0511,9.7679 » devenait « 4.0511.9.7679 » et était
 * refusé — une adresse copiée sans espace après la virgule échouait donc bêtement.
 *
 * @param {string} texte
 * @returns {string} la même chaîne, virgules décimales remplacées par des points
 */
function virgulesDecimals(texte) {
  let out = "";
  for (let i = 0; i < texte.length; i++) {
    const c = texte[i];
    if (c !== ",") { out += c; continue; }
    const avant = texte[i - 1];
    const apres = texte[i + 1];
    // Ni collée à deux chiffres : ce n'est pas une décimale.
    if (!avant || !apres || !/\d/.test(avant) || !/\d/.test(apres)) { out += " "; continue; }
    // Le nombre en cours de lecture a déjà un point : la virgule sépare.
    const debut = out.lastIndexOf(" ") + 1;
    if (out.slice(debut).includes(".")) { out += " "; continue; }
    // Celui qui suit en a un aussi : même conclusion.
    const suite = /^\d*/.exec(texte.slice(i + 1))[0];
    if (texte[i + 1 + suite.length] === ".") { out += " "; continue; }
    out += ".";
  }
  return out;
}

/**
 * Lit une coordonnée saisie à la main.
 *
 * On accepte large : « 4.0511, 9.7679 », « 4.0511 9.7679 », avec ou sans degré, avec une
 * virgule décimale. Refuser une saisie parce qu'elle emploie la virgule française est le
 * genre de rigidité qui fait perdre du temps sur le terrain.
 *
 * @param {string} texte
 * @returns {{lat: number, lon: number} | null}
 */
export function lireCoordonnees(texte) {
  if (typeof texte !== "string") return null;
  // La virgule sert aux deux usages : décimale en français (« 4,0511 ») et séparateur
  // (« 4.0511, 9.7679 »). On tranche donc d'abord : une virgule **collée entre deux
  // chiffres** est une décimale, toute autre est un séparateur. Remplacer toutes les
  // virgules par des espaces, comme on le faisait, découpait « 4,0511 9,7679 » en quatre
  // morceaux et le refusait.
  const propre = virgulesDecimals(texte)
    .replace(/,/g, " ")
    .replace(/[°'"NSEW]/gi, " ")
    .trim();
  const morceaux = propre.split(/\s+/).filter(Boolean);
  if (morceaux.length !== 2) return null;
  const lat = Number(morceaux[0]);
  const lon = Number(morceaux[1]);
  if (!estLatitude(lat) || !estLongitude(lon)) return null;
  return { lat, lon };
}

/** Affiche une coordonnée avec une précision qui reste lisible au niveau de la rue. */
export function formaterCoordonnees(lat, lon) {
  return `${lat.toFixed(6)}, ${lon.toFixed(6)}`;
}
