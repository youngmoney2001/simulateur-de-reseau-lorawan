// Carte 3D des résultats de simulation (CesiumJS, Apache-2.0).
// Le calcul radio est fait par le cœur natif ; ici, seulement l'affichage.
import "./style.css";
import * as Cesium from "cesium";
import "cesium/Build/Cesium/Widgets/widgets.css";
import {
  parseMap,
  parseDem,
  pdrColor,
  boundsOf,
  groundAtLonLat,
  footprintBase,
  heightmapTile,
  EARTH_RADIUS_M,
} from "./model.js";

// Ressources Cesium servies localement (public/cesium, copiées au démarrage).
window.CESIUM_BASE_URL = "/cesium/";

// Fond de carte : Esri World Street Map (tuiles raster, sans clé d'API). Choix provisoire
// d'un fournisseur gratuit : tuiles.openstreetmap.org refuse les requêtes de cette
// application (politique d'usage OSM). Conditions à vérifier avant mise en production
// commerciale : https://www.esri.com/en-us/legal/terms/full-master-agreement
const BASEMAP_CREDIT =
  "Basemap : Esri, HERE, Garmin, © OpenStreetMap contributors, et partenaires SIG";
const viewer = new Cesium.Viewer("cesiumContainer", {
  // Fournisseur asynchrone (fromUrl) : le constructeur direct n'initialise pas ses ressources.
  baseLayer: Cesium.ImageryLayer.fromProviderAsync(
    Cesium.ArcGisMapServerImageryProvider.fromUrl(
      "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer",
      { credit: new Cesium.Credit(BASEMAP_CREDIT) },
    ),
  ),
  baseLayerPicker: false,
  geocoder: false,
  homeButton: false,
  sceneModePicker: false,
  navigationHelpButton: false,
  animation: false,
  timeline: false,
  infoBox: false,
  selectionIndicator: false,
});

const devices = viewer.scene.primitives.add(new Cesium.PointPrimitiveCollection());
const $ = (id) => document.getElementById(id);

// Relief : MNT local (aucun service de terrain distant). `dem` est null sans relief.
const TILE_SCHEME = new Cesium.GeographicTilingScheme();
const TILE_SIZE = 65;
let dem = null;

function useDem(next) {
  dem = next;
  if (dem) {
    viewer.terrainProvider = new Cesium.CustomHeightmapTerrainProvider({
      width: TILE_SIZE,
      height: TILE_SIZE,
      tilingScheme: TILE_SCHEME,
      callback: (x, y, level) => {
        const r = TILE_SCHEME.tileXYToRectangle(x, y, level);
        return heightmapTile(
          dem,
          Cesium.Math.toDegrees(r.west),
          Cesium.Math.toDegrees(r.south),
          Cesium.Math.toDegrees(r.east),
          Cesium.Math.toDegrees(r.north),
          TILE_SIZE,
          TILE_SIZE,
        );
      },
    });
  } else {
    viewer.terrainProvider = new Cesium.EllipsoidTerrainProvider();
  }
}

// Altitude du sol (m) au point géographique ; 0 sans relief.
function groundAt(lon, lat) {
  return dem ? groundAtLonLat(dem, lon, lat) : 0;
}

function fmtPct(v) {
  return v === null || v === undefined ? "n/a" : `${(v * 100).toFixed(2)} %`;
}

function showSummary(parsed) {
  const p = parsed.properties;
  $("s-name").textContent = p.scenario_name ?? "—";
  $("s-hash").textContent = p.scenario_sha256 ? `${p.scenario_sha256.slice(0, 16)}…` : "—";
  $("s-counts").textContent = `${p.total_sent ?? "?"} / ${p.total_received ?? "?"}`;
  $("s-pdr").textContent = fmtPct(p.pdr);
  $("s-devices").textContent = String(parsed.devices.length);
}

function render(parsed) {
  viewer.entities.removeAll();
  devices.removeAll();

  if (parsed.gateway) {
    const [lon, lat] = parsed.gateway;
    const h = groundAt(lon, lat) + (dem ? parsed.gatewayHeightM : 0);
    viewer.entities.add({
      position: Cesium.Cartesian3.fromDegrees(lon, lat, h),
      point: { pixelSize: 14, color: Cesium.Color.WHITE, outlineColor: Cesium.Color.BLACK, outlineWidth: 2 },
      label: {
        text: "Passerelle",
        font: "14px sans-serif",
        pixelOffset: new Cesium.Cartesian2(0, -22),
        verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
        showBackground: true,
      },
    });
  }

  // Obstacles : pavés extrudés depuis le sol le plus bas de leur emprise jusqu'à leur hauteur.
  for (const o of parsed.obstacles) {
    const base = dem ? footprintBase(dem, o.ring) : 0;
    viewer.entities.add({
      name: "Obstacle",
      description: `hauteur ${o.height_m} m, atténuation ${o.attenuation_db ?? 0} dB`,
      polygon: {
        hierarchy: Cesium.Cartesian3.fromDegreesArray(o.ring.flat()),
        height: base,
        extrudedHeight: base + o.height_m,
        material: Cesium.Color.DARKSLATEGRAY.withAlpha(0.85),
        outline: false,
      },
    });
  }

  // Couvertures : posées sur le sol (le relief peut passer au-dessus ou en dessous du plan).
  for (const c of parsed.coverage) {
    const modelLabel = c.model === "environment" ? "relief et obstacles" : "log-distance seul";
    viewer.entities.add({
      name: `Couverture ${c.group}`,
      description: `SF${c.spreading_factor}, ${c.tx_power_dbm} dBm, portée max ${c.range_m} m (${modelLabel})`,
      polygon: {
        hierarchy: Cesium.Cartesian3.fromDegreesArray(c.ring.flat()),
        clampToGround: true,
        material: Cesium.Color.DODGERBLUE.withAlpha(0.12),
      },
    });
  }

  // Dispositifs : PointPrimitiveCollection (un seul objet GPU, adapté à plusieurs milliers de points).
  for (const d of parsed.devices) {
    const [lon, lat] = d.lonlat;
    devices.add({
      position: Cesium.Cartesian3.fromDegrees(lon, lat, groundAt(lon, lat) + (dem ? parsed.deviceHeightM : 0)),
      pixelSize: 7,
      color: Cesium.Color.fromCssColorString(pdrColor(d.pdr)),
      outlineColor: Cesium.Color.BLACK.withAlpha(0.6),
      outlineWidth: 1,
      id: d,
    });
  }

  showSummary(parsed);
  const b = boundsOf(parsed);
  if (b) {
    viewer.camera.flyTo({
      destination: Cesium.Rectangle.fromDegrees(b.west, b.south, b.east, b.north),
      duration: 1.0,
    });
  }
}

function showDetail(d) {
  const lines = [
    `Dispositif ${d.device_index} (groupe ${d.group})`,
    `SF${d.spreading_factor} — émises ${d.sent}, reçues ${d.received}`,
    `Sensibilité : ${d.lost_sensitivity}, collision : ${d.lost_collision}`,
    `PDR : ${fmtPct(d.pdr)}`,
  ];
  const box = $("detail");
  box.replaceChildren(...lines.map((t) => {
    const el = document.createElement("div");
    el.textContent = t;
    return el;
  }));
}

const handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
handler.setInputAction((click) => {
  const picked = viewer.scene.pick(click.position);
  if (picked && picked.primitive && picked.primitive.id && picked.primitive.id.kind === "device") {
    showDetail(picked.primitive.id);
  }
}, Cesium.ScreenSpaceEventType.LEFT_CLICK);

function fail(message) {
  $("error").textContent = message;
}

// Affiche la carte (et son relief, si fourni). Le relief est validé avant tout changement.
// `fromSample` : la carte ouvre d'office sur public/sample.geojson. Sans signalement, ces
// chiffres se lisent comme les resultats de l'utilisateur, qui n'a pourtant rien simule.
function show(mapText, demText, fromSample = false) {
  try {
    const parsed = parseMap(JSON.parse(mapText));
    const next = demText ? parseDem(JSON.parse(demText)) : null;
    useDem(next);
    $("error").textContent = "";
    $("sample-note").hidden = !fromSample;
    render(parsed);
  } catch (err) {
    fail(err instanceof Error ? err.message : "Fichier illisible");
  }
}

// Chargement manuel : GeoJSON, et MNT optionnel (si l'export contient du relief).
$("file").addEventListener("change", async (event) => {
  const file = event.target.files?.[0];
  if (!file) return;
  if (file.size > 25 * 1024 * 1024) {
    fail("Fichier trop volumineux (25 Mo maximum)");
    return;
  }
  const demFile = $("dem-file")?.files?.[0] ?? null;
  const demText = demFile ? await demFile.text() : null;
  show(await file.text(), demText, false);
});

// --------------------------------------------------------------- chargement au démarrage
//
// La carte ouvrait d'office sur un jeu d'exemple : on y lisait 500 compteurs et un taux de
// réussite qui n'étaient pas les vôtres, ce qui les faisait passer pour vos résultats. Elle
// n'affiche plus rien par elle-même. Trois cas :
//   1. `?run=...`  -> les résultats que vous venez de produire dans le studio ;
//   2. `?map=...`  -> un exemple nommé explicitement, signalé comme tel ;
//   3. rien        -> carte vide, invitation à ouvrir un fichier ou à passer par le studio.
const params = new URLSearchParams(window.location.search);
const mapName = params.get("map");
const demName = params.get("dem");
const runId = params.get("run");
const sid = params.get("sid");
const SAFE_NAME = /^[A-Za-z0-9_.-]+\.(geojson|json)$/;

// Mètres (plan du studio) vers degrés. Reprend exactement `_to_lonlat` de geo.py, pour que
// les positions coïncident avec celles de l'export produit par le serveur.
function toLonLat(x_m, y_m, originLat, originLon) {
  const lat = originLat + (y_m / EARTH_RADIUS_M) * (180 / Math.PI);
  const lon = originLon
    + (x_m / (EARTH_RADIUS_M * Math.cos((originLat * Math.PI) / 180))) * (180 / Math.PI);
  return [lon, lat];
}

function origine() {
  const lat = Number(params.get("lat"));
  const lon = Number(params.get("lon"));
  return Number.isFinite(lat) && Number.isFinite(lon) ? { lat, lon } : { lat: 4.0511, lon: 9.7679 };
}

// Le jeton ne transite jamais par l'URL : il serait écrit dans l'historique et les journaux.
// S'il est en mémoire de session (même onglet) ou fourni par le serveur (instance locale),
// la carte peut lire le run ; sinon elle le dit au lieu d'échouer en silence.
async function jetonDisponible() {
  const enMemoire = sessionStorage.getItem("lsim-token");
  if (enMemoire) return enMemoire;
  try {
    const h = await fetch("/api/v1/health", { headers: { Accept: "application/json" } });
    if (!h.ok) return null;
    if (!((await h.json()).auto_token === true)) return null;
    const r = await fetch("/api/v1/auto-token", { headers: { Accept: "application/json" } });
    if (!r.ok) return null;
    const corps = await r.json();
    return typeof corps?.token === "string" && corps.token ? corps.token : null;
  } catch {
    return null;
  }
}

async function lirePages(url, token) {
  const items = [];
  let cursor = null;
  do {
    const u = cursor === null ? url : `${url}${url.includes("?") ? "&" : "?"}cursor=${cursor}`;
    const r = await fetch(u, { headers: { Accept: "application/json", "Authorization": `Bearer ${token}` } });
    if (!r.ok) throw new Error(`API ${r.status} sur ${u.replace(/^.*\/api\/v1\//, "")}`);
    const page = await r.json();
    items.push(...(page.items ?? []));
    cursor = page.next_cursor ?? null;
  } while (cursor !== null && items.length < 20000);
  return items;
}

// Construit la FeatureCollection d'un run réel : passerelles issues de la topologie de la
// session, dispositifs issus des lignes du run. Sans relief ni couverture, que le serveur
// seul peut calculer — la carte montre donc les points et leur taux de réussite.
async function carteDepuisLeStudio() {
  const token = await jetonDisponible();
  if (!token) {
    fail("Aucun jeton disponible : ouvrez la carte depuis le studio, après une simulation.");
    return;
  }
  const o = origine();
  const base = "/api/v1";
  const entetes = { Accept: "application/json", "Authorization": `Bearer ${token}` };
  const dispositifs = await lirePages(`${base}/runs/${encodeURIComponent(runId)}/devices`, token);
  const features = [];
  if (sid) {
    const r = await fetch(`${base}/sessions/${encodeURIComponent(sid)}/topology`, { headers: entetes });
    if (r.ok) {
      const topo = await r.json();
      for (const n of topo.nodes ?? []) {
        if (n.kind === "sensor") continue;
        features.push({ type: "Feature",
          geometry: { type: "Point", coordinates: toLonLat(n.x_m, n.y_m, o.lat, o.lon) },
          properties: { kind: "gateway", name: n.name || n.id } });
      }
    }
  }
  let totalEnvoyes = 0, totalRecus = 0;
  for (const d of dispositifs) {
    totalEnvoyes += d.sent ?? 0;
    totalRecus += d.received ?? 0;
    features.push({ type: "Feature",
      geometry: { type: "Point", coordinates: toLonLat(d.x_m, d.y_m, o.lat, o.lon) },
      properties: { kind: "device", device_index: d.device_index, group: d.group,
        spreading_factor: d.spreading_factor, sent: d.sent, received: d.received,
        lost_sensitivity: d.lost_sensitivity, lost_collision: d.lost_collision,
        pdr: d.sent > 0 ? d.received / d.sent : 0 } });
  }
  if (!features.length) {
    fail("Ce run ne contient aucun dispositif.");
    return;
  }
  const doc = { type: "FeatureCollection", features,
    properties: { scenario_name: "Studio", origin: { latitude: o.lat, longitude: o.lon },
      total_sent: totalEnvoyes, total_received: totalRecus } };
  show(JSON.stringify(doc), null, false);
}

if (runId) {
  carteDepuisLeStudio().catch((err) => fail(err instanceof Error ? err.message : String(err)));
} else if (mapName !== null) {
  if (!SAFE_NAME.test(mapName) || (demName !== null && !SAFE_NAME.test(demName))) {
    fail("Nom de fichier d'exemple refusé");
  } else {
    Promise.all([
      fetch(`/${mapName}`).then((r) => (r.ok ? r.text() : Promise.reject(new Error("exemple absent")))),
      demName
        ? fetch(`/${demName}`).then((r) => (r.ok ? r.text() : Promise.reject(new Error("MNT absent"))))
        : Promise.resolve(null),
    ])
      .then(([mapText, demText]) => show(mapText, demText, true))
      .catch((err) => fail(err.message));
  }
} else {
  // Rien à afficher : on le dit, au lieu de substituer un exemple.
  $("empty-note").hidden = false;
}
