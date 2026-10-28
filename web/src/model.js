// Logique pure de la carte : validation du GeoJSON, extraction, couleurs.
// Aucune dépendance à Cesium, pour pouvoir être testée sans navigateur.

export const MAX_FEATURES = 20000;

const KINDS = new Set(["gateway", "coverage", "device", "obstacle"]);
const MAX_OBSTACLE_HEIGHT_M = 1000;

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
    } else if (kind === "obstacle") {
      if (g?.type !== "Polygon" || !Array.isArray(g.coordinates?.[0])) {
        throw new Error("Obstacle : polygone attendu");
      }
      if (!g.coordinates[0].every(isLonLat)) throw new Error("Obstacle : coordonnées invalides");
      const h = f.properties.height_m;
      if (!Number.isFinite(h) || h <= 0 || h > MAX_OBSTACLE_HEIGHT_M) {
        throw new Error("Obstacle : hauteur invalide");
      }
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
  const out = {
    gateway: null,
    gatewayHeightM: 0,
    deviceHeightM: 0,
    coverage: [],
    devices: [],
    obstacles: [],
    properties: doc.properties ?? {},
  };
  const env = doc.properties?.environment;
  if (env) {
    out.gatewayHeightM = Number.isFinite(env.gateway_height_m) ? env.gateway_height_m : 0;
    out.deviceHeightM = Number.isFinite(env.device_height_m) ? env.device_height_m : 0;
  }
  for (const f of doc.features) {
    const p = f.properties;
    if (p.kind === "gateway") {
      out.gateway = f.geometry.coordinates;
    } else if (p.kind === "coverage") {
      out.coverage.push({ ...p, ring: f.geometry.coordinates[0] });
    } else if (p.kind === "obstacle") {
      out.obstacles.push({ ...p, ring: f.geometry.coordinates[0] });
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
  for (const o of parsed.obstacles ?? []) o.ring.forEach(add);
  for (const d of parsed.devices) add(d.lonlat);
  if (!Number.isFinite(west)) return null;
  return { west, south, east, north };
}

// ---------------------------------------------------------------- relief (MNT)
//
// Le MNT est un document `lsim-dem-v1` produit par `python -m lsim geojson --dem`.
// La projection locale (mètres autour de l'origine) et l'interpolation bilinéaire
// reprennent exactement celles du cœur (environment.cpp) et de geo.py.

export const EARTH_RADIUS_M = 6_371_000.0;
export const DEM_FORMAT = "lsim-dem-v1";
export const MAX_DEM_CELLS = 4_000_000;

function decodeFloat32LE(b64, count) {
  const bin = atob(b64);
  if (bin.length !== count * 4) throw new Error("MNT : taille des données incohérente");
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  const view = new DataView(bytes.buffer);
  const z = new Float32Array(count);
  for (let i = 0; i < count; i++) {
    const v = view.getFloat32(i * 4, true);
    if (!Number.isFinite(v)) throw new Error("MNT : valeur non finie");
    z[i] = v;
  }
  return z;
}

// Valide et décode un document MNT. Lève une erreur explicite sinon.
export function parseDem(doc) {
  if (!doc || doc.format !== DEM_FORMAT) throw new Error("MNT : format lsim-dem-v1 attendu");
  const { latitude, longitude } = doc.origin ?? {};
  if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) {
    throw new Error("MNT : origine géographique invalide");
  }
  if (!(Number.isFinite(latitude) && Math.abs(latitude) <= 80 && Math.abs(longitude) <= 180)) {
    throw new Error("MNT : origine hors domaine");
  }
  const { origin_x_m: x0, origin_y_m: y0, cell_m: cell, nx, ny } = doc;
  if (![x0, y0, cell].every(Number.isFinite) || !(cell > 0)) {
    throw new Error("MNT : origine ou pas invalide");
  }
  if (!Number.isInteger(nx) || !Number.isInteger(ny) || nx < 2 || ny < 2) {
    throw new Error("MNT : dimensions invalides");
  }
  if (nx * ny > MAX_DEM_CELLS) throw new Error("MNT trop grand");
  if (doc.encoding !== "float32-le-base64" || typeof doc.z !== "string") {
    throw new Error("MNT : encodage non supporté");
  }
  const z = decodeFloat32LE(doc.z, nx * ny);
  return {
    originLat: latitude,
    originLon: longitude,
    x0,
    y0,
    cell,
    nx,
    ny,
    z,
    sha256: typeof doc.sha256 === "string" ? doc.sha256 : null,
  };
}

// Projection locale identique à geo.py : x = R cos(lat0) Δlon, y = R Δlat (radians).
export function lonLatToLocal(dem, lon, lat) {
  const d2r = Math.PI / 180;
  return {
    x: (lon - dem.originLon) * d2r * EARTH_RADIUS_M * Math.cos(dem.originLat * d2r),
    y: (lat - dem.originLat) * d2r * EARTH_RADIUS_M,
  };
}

export function localToLonLat(dem, x, y) {
  const r2d = 180 / Math.PI;
  return {
    lon: dem.originLon + (x / (EARTH_RADIUS_M * Math.cos(dem.originLat * Math.PI / 180))) * r2d,
    lat: dem.originLat + (y / EARTH_RADIUS_M) * r2d,
  };
}

// Altitude bilinéaire au point local (x, y) ; bord le plus proche hors grille (clamp).
export function groundAtLocal(dem, x, y) {
  const fx = Math.min(Math.max((x - dem.x0) / dem.cell, 0), dem.nx - 1);
  const fy = Math.min(Math.max((y - dem.y0) / dem.cell, 0), dem.ny - 1);
  const ix = Math.min(Math.floor(fx), dem.nx - 2);
  const iy = Math.min(Math.floor(fy), dem.ny - 2);
  const tx = fx - ix;
  const ty = fy - iy;
  const at = (i, j) => dem.z[j * dem.nx + i];
  const top = at(ix, iy) * (1 - tx) + at(ix + 1, iy) * tx;
  const bottom = at(ix, iy + 1) * (1 - tx) + at(ix + 1, iy + 1) * tx;
  return top * (1 - ty) + bottom * ty;
}

// Altitude au point géographique (lon, lat) en degrés.
export function groundAtLonLat(dem, lon, lat) {
  const { x, y } = lonLatToLocal(dem, lon, lat);
  return groundAtLocal(dem, x, y);
}

// Hauteur minimale du sol sous l'emprise (sommets et centre) : base sûre d'un pavé.
export function footprintBase(dem, ring) {
  let min = Infinity;
  let cx = 0;
  let cy = 0;
  for (const [lon, lat] of ring) {
    const { x, y } = lonLatToLocal(dem, lon, lat);
    min = Math.min(min, groundAtLocal(dem, x, y));
    cx += x;
    cy += y;
  }
  const n = ring.length || 1;
  min = Math.min(min, groundAtLocal(dem, cx / n, cy / n));
  return Number.isFinite(min) ? min : 0;
}

// Tuile de hauteur pour CustomHeightmapTerrainProvider : width x height valeurs,
// ligne 0 = nord, colonne 0 = ouest (convention vérifiée dans le code de Cesium).
// Hors du MNT : bord le plus proche (cohérent avec le cœur).
export function heightmapTile(dem, west, south, east, north, width, height) {
  const out = new Float32Array(width * height);
  for (let j = 0; j < height; j++) {
    const lat = north - ((north - south) * j) / (height - 1);
    for (let i = 0; i < width; i++) {
      const lon = west + ((east - west) * i) / (width - 1);
      out[j * width + i] = groundAtLonLat(dem, lon, lat);
    }
  }
  return out;
}

