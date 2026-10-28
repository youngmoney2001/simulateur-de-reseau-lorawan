// Carte 3D des résultats de simulation (CesiumJS, Apache-2.0).
// Le calcul radio est fait par le cœur natif ; ici, seulement l'affichage.
import "./style.css";
import * as Cesium from "cesium";
import "cesium/Build/Cesium/Widgets/widgets.css";
import { parseMap, pdrColor, boundsOf } from "./model.js";

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
    viewer.entities.add({
      position: Cesium.Cartesian3.fromDegrees(parsed.gateway[0], parsed.gateway[1]),
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

  // Obstacles : pavés extrudés depuis le sol jusqu'à leur hauteur (mètres).
  for (const o of parsed.obstacles ?? []) {
    viewer.entities.add({
      name: "Obstacle",
      description: `hauteur ${o.height_m} m, atténuation ${o.attenuation_db ?? 0} dB`,
      polygon: {
        hierarchy: Cesium.Cartesian3.fromDegreesArray(o.ring.flat()),
        extrudedHeight: o.height_m,
        material: Cesium.Color.DARKSLATEGRAY.withAlpha(0.85),
        outline: false,
      },
    });
  }

  for (const c of parsed.coverage) {
    const flat = c.ring.flat();
    viewer.entities.add({
      name: `Couverture ${c.group}`,
      description: `SF${c.spreading_factor}, ${c.tx_power_dbm} dBm, portée ${c.range_m} m`,
      polygon: {
        hierarchy: Cesium.Cartesian3.fromDegreesArray(flat),
        material: Cesium.Color.DODGERBLUE.withAlpha(0.12),
        outline: true,
        outlineColor: Cesium.Color.DODGERBLUE.withAlpha(0.7),
      },
    });
  }

  // Dispositifs : PointPrimitiveCollection (un seul objet GPU, adapté à plusieurs milliers de points).
  for (const d of parsed.devices) {
    devices.add({
      position: Cesium.Cartesian3.fromDegrees(d.lonlat[0], d.lonlat[1], 0),
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

function loadText(text) {
  try {
    const parsed = parseMap(JSON.parse(text));
    $("error").textContent = "";
    render(parsed);
  } catch (err) {
    fail(err instanceof Error ? err.message : "Fichier illisible");
  }
}

$("file").addEventListener("change", async (event) => {
  const file = event.target.files?.[0];
  if (!file) return;
  if (file.size > 25 * 1024 * 1024) {
    fail("Fichier trop volumineux (25 Mo maximum)");
    return;
  }
  loadText(await file.text());
});

// Carte d'exemple, générée par `python -m lsim geojson examples/quartier_sf9.yaml`.
fetch("/sample.geojson")
  .then((r) => (r.ok ? r.text() : Promise.reject(new Error("exemple absent"))))
  .then(loadText)
  .catch((err) => fail(err.message));
