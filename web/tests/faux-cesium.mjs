// Faux Cesium : juste assez de surface pour exercer `map3d.js` hors navigateur.
//
// Le but n'est pas d'imiter Cesium — ce serait un mensonge — mais de vérifier ce que la
// carte **décide** : quelles entités elle crée, à quelle altitude, avec quels sommets. Un
// test qui tournerait dans un vrai navigateur dirait la même chose en cent fois plus lent,
// et seulement là où WebGL existe.

const V = (x, y, z = 0) => ({ x, y, z });

export class Cartesian2 { constructor(x, y) { this.x = x; this.y = y; } }

export class Cartesian3 {
  constructor(x, y, z) { this.x = x; this.y = y; this.z = z; }
  static fromDegrees(lon, lat, h = 0) { return new Cartesian3(lon, lat, h); }
  static fromDegreesArray(a) { return a.slice(); }
}
export class Color {
  constructor(hex) { this.hex = hex; }
  withAlpha(a) { const c = new Color(this.hex); c.alpha = a; return c; }
  static fromCssColorString(s) { return new Color(s); }
}
for (const nom of ["DARKSLATEGRAY", "BLACK", "WHITE"]) Color[nom] = new Color(nom.toLowerCase());

export class GeographicTilingScheme {
  tileXYToRectangle(x, y, niveau) {
    const n = Math.pow(2, niveau);
    return { west: (x / n) * 360 - 180, south: (y / n) * 180 - 90,
      east: ((x + 1) / n) * 360 - 180, north: ((y + 1) / n) * 180 - 90 };
  }
}
export class CustomHeightmapTerrainProvider { constructor(o) { Object.assign(this, o); } }
export class EllipsoidTerrainProvider { constructor() { this.plat = true; } }
export class CustomDataSource {
  constructor(nom) { this.nom = nom; this.entities = new Collection(); }
}
export class Collection {
  constructor() { this.items = []; }
  add(v) { this.items.push(v); return v; }
  removeAll() { this.items.length = 0; }
  get values() { return this.items; }
}
export class PolylineCollection { constructor() { this.lignes = []; } }

export class PolygonHierarchy { constructor(p) { this.positions = p; } }
export class ScreenSpaceEventHandler {
  constructor() { this.actions = new Map(); }
  setInputAction(cb, type) { this.actions.set(type, cb); }
}
export const ScreenSpaceEventType = { LEFT_CLICK: "LEFT_CLICK" };
export const Math_ = { toRadians: (d) => (d * Math.PI) / 180, toDegrees: (r) => (r * 180) / Math.PI };
export { Math_ as Math };

// --- Scene et Viewer -------------------------------------------------------------------
// On ne simule pas le rendu : on retient ce que la carte dépose dans la scène, ce qui
// est précisément ce qu'un test veut observer.

export class Credit { constructor(html) { this.html = html; } }
export class ImageryLayer {
  static fromProviderAsync(p) { const l = new ImageryLayer(); l.promesse = p; l.readyEvent = p; return l; }
}
export class TileMapServiceImageryProvider {
  static fromUrl(u) { return Promise.resolve(new TileMapServiceImageryProvider(u)); }
  constructor(u) { this.url = u; }
}
export class ArcGisMapServerImageryProvider {
  static fromUrl(u) { return Promise.resolve(new ArcGisMapServerImageryProvider(u)); }
  constructor(u) { this.url = u; }
}
export class Material { static fromType(t) { return new Material(t); } constructor(t) { this.type = t; } }
export const LabelStyle = { FILL_AND_OUTLINE: "FILL_AND_OUTLINE" };
export const VerticalOrigin = { BOTTOM: "BOTTOM" };
export class Cartographic {
  static fromDegrees(lon, lat, h) { return { longitude: lon, latitude: lat, height: h }; }
}
export class Cartesian { }
export const SceneTransforms = {
  worldToWindowCoordinates: () => null,
};
export class PointPrimitiveCollection extends Collection { add(v) { this.items.push(v); return v; } }
export class LabelCollection extends Collection { add(v) { this.items.push(v); return v; } }

class Camera {
  constructor() { this.vols = []; }
  flyTo(o) { this.vols.push(o); }
}

export class Viewer {
  constructor() {
    this.scene = {
      primitives: { add: (p) => p, remove: () => {} },
      // Altitude du sol : le faux relief répond ce qu'on lui a donné.
      sampleHeight: () => 0,
      globe: { depthTestAgainstTerrain: false },
      imageryLayers: { add: (l) => l },
      renderError: { addEventListener: (cb) => { this.scene.renderError.cb = cb; } },
      pickPosition: () => undefined,
      requestRender: () => {},
    };
    this.canvas = {};
    this.dataSources = { add: (d) => d, remove: () => {} };
    this.entities = new Collection();
    this.camera = new Camera();
    this.imageryLayers = { add: (l) => l };
    this.terrainProvider = null;
  }
}
