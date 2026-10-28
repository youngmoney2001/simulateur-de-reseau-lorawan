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
} from "./model.js";

// Ressources Cesium servies localement (public/cesium, copiées au démarrage).
window.CESIUM_BASE_URL = "/cesium/";

// Fond de carte OpenStreetMap. Pour un usage commercial intensif, utiliser un
// fournisseur de tuiles sous contrat (la politique d'usage OSM le limite).
const viewer = new Cesium.Viewer("cesiumContainer", {
  baseLayer: new Cesium.ImageryLayer(
    new Cesium.OpenStreetMapImageryProvider({ url: "https://tile.openstreetmap.org/" }),
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
function show(mapText, demText) {
  try {
    const parsed = parseMap(JSON.parse(mapText));
    const next = demText ? parseDem(JSON.parse(demText)) : null;
    useDem(next);
    $("error").textContent = "";
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
  show(await file.text(), demText);
});

// Carte d'exemple (et MNT) : ?map=...&dem=... ou par défaut la carte sans relief.
const params = new URLSearchParams(window.location.search);
const mapName = params.get("map") ?? "sample.geojson";
const demName = params.get("dem");
const SAFE_NAME = /^[A-Za-z0-9_.-]+\.(geojson|json)$/;
if (!SAFE_NAME.test(mapName) || (demName !== null && !SAFE_NAME.test(demName))) {
  fail("Nom de fichier d'exemple refusé");
} else {
  Promise.all([
    fetch(`/${mapName}`).then((r) => (r.ok ? r.text() : Promise.reject(new Error("exemple absent")))),
    demName
      ? fetch(`/${demName}`).then((r) => (r.ok ? r.text() : Promise.reject(new Error("MNT absent"))))
      : Promise.resolve(null),
  ])
    .then(([mapText, demText]) => show(mapText, demText))
    .catch((err) => fail(err.message));
}
