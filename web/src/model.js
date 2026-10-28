// Logique pure de la carte : validation du GeoJSON, extraction, couleurs.
// Aucune dépendance à Cesium, pour pouvoir être testée sans navigateur.

export const MAX_FEATURES = 20000;

const KINDS = new Set(["gateway", "coverage", "device"]);

function isLonLat(c) {
  return (
    Array.isArray(c) &&
    c.length >= 2 &&
    Number.isFinite(c[0]) &&
    Number.isFinite(c[1]) &&
    c[0] >= -180 &&
    c[0] <= 180 &&
    c[1] >= -90 &&
    c[1] <= 90
  );
}

// Lève une erreur explicite si le document ne correspond pas au format attendu.
export function validateMap(doc) {
  if (!doc || doc.type !== "FeatureCollection" || !Array.isArray(doc.features)) {
    throw new Error("Fichier invalide : FeatureCollection attendue");
  }
  if (doc.features.length > MAX_FEATURES) {
    throw new Error(`Fichier trop volumineux : au plus ${MAX_FEATURES} entités`);
  }
  for (const f of doc.features) {
    const kind = f?.properties?.kind;
    if (!KINDS.has(kind)) throw new Error(`Entité de type inconnu : ${kind}`);
    const g = f.geometry;
    if (kind === "coverage") {
      if (g?.type !== "Polygon" || !Array.isArray(g.coordinates?.[0])) {
        throw new Error("Couverture : polygone attendu");
      }
      if (!g.coordinates[0].every(isLonLat)) throw new Error("Couverture : coordonnées invalides");
    } else {
      if (g?.type !== "Point" || !isLonLat(g.coordinates)) {
        throw new Error(`${kind} : point géographique attendu`);
      }
    }
  }
  return doc;
}

// Couleur selon le taux de livraison ; null (aucune émission) en gris.
export function pdrColor(pdr) {
  if (pdr === null || pdr === undefined || !Number.isFinite(pdr)) return "#9e9e9e";
  if (pdr >= 0.95) return "#2e7d32";
  if (pdr >= 0.8) return "#9ccc65";
  if (pdr >= 0.5) return "#ff9800";
  return "#d32f2f";
}

export function parseMap(doc) {
  validateMap(doc);
  const out = { gateway: null, coverage: [], devices: [], properties: doc.properties ?? {} };
  for (const f of doc.features) {
    const p = f.properties;
    if (p.kind === "gateway") {
      out.gateway = f.geometry.coordinates;
    } else if (p.kind === "coverage") {
      out.coverage.push({ ...p, ring: f.geometry.coordinates[0] });
    } else {
      out.devices.push({ ...p, lonlat: f.geometry.coordinates });
    }
  }
  return out;
}

// Rectangle englobante (ouest, sud, est, nord) de la passerelle, des couvertures et des dispositifs.
export function boundsOf(parsed) {
  let west = Infinity, south = Infinity, east = -Infinity, north = -Infinity;
  const add = ([x, y]) => {
    west = Math.min(west, x);
    east = Math.max(east, x);
    south = Math.min(south, y);
    north = Math.max(north, y);
  };
  if (parsed.gateway) add(parsed.gateway);
  for (const c of parsed.coverage) c.ring.forEach(add);
  for (const d of parsed.devices) add(d.lonlat);
  if (!Number.isFinite(west)) return null;
  return { west, south, east, north };
}
