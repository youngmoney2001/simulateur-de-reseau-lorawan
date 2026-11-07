// Carte 3D du studio : la surface de travail.
//
// Le moteur radio raisonne en mètres autour d'une origine ; la carte raisonne en degrés. Ce
// module porte la conversion entre les deux, qui reprend exactement `_to_lonlat` du serveur
// (geo.py) pour que les positions coïncident avec l'export produit par celui-ci.
import * as Cesium from "cesium";

export const EARTH_RADIUS_M = 6_371_000.0;

// Ressources Cesium servies localement (public/cesium). Doit être posé avant tout import
// de widgets, sinon Cesium cherche ses ressources sur un serveur distant.
window.CESIUM_BASE_URL = "/cesium/";

const BASEMAP_CREDIT =
  "Basemap : Esri, HERE, Garmin, © OpenStreetMap contributors, et partenaires SIG";

// Mètres (plan) vers degrés (carte). Même formule que geo.py.
export function toLonLat(x_m, y_m, originLat, originLon) {
  const lat = originLat + (y_m / EARTH_RADIUS_M) * (180 / Math.PI);
  const lon =
    originLon +
    (x_m / (EARTH_RADIUS_M * Math.cos((originLat * Math.PI) / 180))) * (180 / Math.PI);
  return { lon, lat };
}

// Degrés (carte) vers mètres (plan). Inverse exact de toLonLat.
export function toMeters(lat, lon, originLat, originLon) {
  const y_m = ((lat - originLat) * Math.PI / 180) * EARTH_RADIUS_M;
  const x_m =
    ((lon - originLon) * Math.PI / 180) *
    EARTH_RADIUS_M *
    Math.cos((originLat * Math.PI) / 180);
  return { x_m, y_m };
}

// Couleur d'un équipement par type. Reprend la palette du plan 2D, pour que la même forme
// garde la même couleur d'une vue à l'autre.
const COULEURS = {
  border: Cesium.Color.fromCssColorString("#2ea043"),
  gateway: Cesium.Color.fromCssColorString("#2ea043"),
  relay: Cesium.Color.fromCssColorString("#f2cc60"),
  server: Cesium.Color.fromCssColorString("#6e40c9"),
  sensor: Cesium.Color.fromCssColorString("#1f6feb"),
};

/**
 * Crée la carte 3D dans `container`.
 * @param {HTMLElement} container
 * @param {(lat: number, lon: number) => void} onPick appelé quand on clique le globe
 */
export function createMap3D(container, onPick) {
  const viewer = new Cesium.Viewer(container, {
    // Fournisseur asynchrone : le constructeur direct n'initialise pas ses ressources.
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

  const points = viewer.scene.primitives.add(new Cesium.PointPrimitiveCollection());
  const labels = viewer.scene.primitives.add(new Cesium.LabelCollection());
  let origine = { lat: 4.0511, lon: 9.7679 };

  // Un clic sur le globe : on lève la position géographique. Un clic dans le vide (ciel)
  // ne produit rien de exploitable et doit être ignoré silencieusement.
  const gestionnaire = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
  gestionnaire.setInputAction((mouvement) => {
    if (!onPick) return;
    const cible = viewer.scene.pickPosition?.(mouvement.position)
      ?? viewer.camera.pickEllipsoid(mouvement.position, viewer.scene.globe.ellipsoid);
    if (!cible) return;
    const carto = Cesium.Cartographic.fromCartesian(cible);
    if (!carto) return;
    onPick(
      Cesium.Math.toDegrees(carto.latitude),
      Cesium.Math.toDegrees(carto.longitude),
    );
  }, Cesium.ScreenSpaceEventType.LEFT_CLICK);

  return {
    viewer,

    /** Origine de la zone : ancre entre les mètres du plan et les degrés de la carte. */
    setOrigin(o) {
      if (o && Number.isFinite(o.lat) && Number.isFinite(o.lon)) origine = o;
    },
    getOrigin() {
      return { ...origine };
    },

    /** La caméra se place au-dessus de l'origine, à une hauteur qui cadre `porteeM` mètres. */
    flyToOrigin(porteeM = 1200) {
      const hauteur = Math.max(180, porteeM * 3.2);
      viewer.camera.flyTo({
        destination: Cesium.Cartesian3.fromDegrees(origine.lon, origine.lat, hauteur),
        orientation: { heading: 0, pitch: Cesium.Math.toRadians(-70), roll: 0 },
      });
    },

    /**
     * Affiche les équipements. `noeuds` porte x_m/y_m (mètres) ; la conversion en degrés
     * se fait ici, à partir de l'origine courante.
     */
    setNodes(noeuds, selectionId = null) {
      points.removeAll();
      labels.removeAll();
      for (const n of noeuds ?? []) {
        const { lon, lat } = toLonLat(n.x_m, n.y_m, origine.lat, origine.lon);
        const estCapteur = n.kind === "sensor";
        const selectionne = n.id === selectionId;
        points.add({
          position: Cesium.Cartesian3.fromDegrees(lon, lat),
          color: COULEURS[n.kind] ?? COULEURS.sensor,
          pixelSize: selectionne ? 20 : estCapteur ? 12 : 16,
          outlineColor: Cesium.Color.WHITE,
          outlineWidth: selectionne ? 3 : 2,
          // Les passerelles dominent : elles restent lisibles sous les capteurs.
          disableDepthTestDistance: 0,
        });
        if (!estCapteur || selectionne) {
          labels.add({
            position: Cesium.Cartesian3.fromDegrees(lon, lat, 0),
            text: n.name || n.id,
            font: "600 13px system-ui, sans-serif",
            fillColor: Cesium.Color.WHITE,
            outlineColor: Cesium.Color.fromCssColorString("#1d2630"),
            outlineWidth: 3,
            style: Cesium.LabelStyle.FILL_AND_OUTLINE,
            verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
            pixelOffset: new Cesium.Cartesian2(0, -14),
            disableDepthTestDistance: 0,
          });
        }
      }
    },

    destroy() {
      gestionnaire.destroy?.();
      viewer.destroy?.();
    },
  };
}
