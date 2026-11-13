// Carte 3D du studio : la surface de travail.
//
// Le moteur radio raisonne en mètres autour d'une origine ; la carte raisonne en degrés. Ce
// module porte la conversion entre les deux, qui reprend exactement `_to_lonlat` du serveur
// (geo.py) pour que les positions coïncident avec l'export produit par celui-ci.
import * as Cesium from "cesium";
// La conversion mètres ↔ degrés vit dans `geo.js`, sans dépendance, pour être testée hors
// navigateur. On la réexporte ici : l'ancienne copie locale risquait de dériver de celle
// du serveur sans que rien ne le signale, ce qui est exactement la panne invisible que
// l'invariant D2 cherche à éviter.
import {
  EARTH_RADIUS_M,
  metresVersDegres as toLonLat,
  degresVersMetres as toMeters,
} from "./geo.js";
// Le calcul des liaisons vit dans `liaisons.js`, sans dépendance à Cesium : il est donc
// vérifiable hors navigateur, ce qu'un calcul enfoui dans cette carte ne serait pas.
import { boutsLiaison, etiquetteLiaison } from "./liaisons.js";
// Le relief et la zone : décodage du MNT et tracé des lobes, sans dépendance à Cesium
// (voir `../model.js` et `zone.js`). Les reprendre ici plutôt que de les recalculer
// évite deux vérités sur une même altitude.
import { footprintBase, heightmapTile, parseDem } from "../model.js";
import { COULEURS_QUALITE, anneauZone, etiquetteModele, etiquettePalier, porteeMax }
  from "./zone.js";

export { EARTH_RADIUS_M, toLonLat, toMeters };

// Ressources Cesium servies localement (public/cesium). Doit être posé avant tout import
// de widgets, sinon Cesium cherche ses ressources sur un serveur distant.
window.CESIUM_BASE_URL = "/cesium/";

// Deux natures de liaisons, deux teintes, et le trait reste tireté dans les deux cas :
// une liaison observée n'est pas un câble, qu'elle soit un acheminement ou une portée.
const STYLE_LIAISON = {
  mesh: { couleur: "#6b4fbb", largeur: 3, clair: "#e9e4fb", sombre: "#2a1d55" },
  radio: { couleur: "#0f9b8e", largeur: 2, clair: "#dff6f1", sombre: "#06332c" },
};

const BASEMAP_CREDIT =
  "Basemap : Esri, HERE, Garmin, © OpenStreetMap contributors, et partenaires SIG";

// Fond garanti : la texture mondiale fournie avec Cesium, servie depuis public/cesium.
// Le fond routier vient d'un service distant, que rien ne garantit accessible — depuis
// l'environnement de développement comme depuis la CI, il ne l'est pas, et le globe y
// restait désespérément vide. Cette texture, elle, est toujours là : la carte n'est donc
// jamais blanche, et son rendu devient vérifiable partout.
const FOND_LOCAL = window.CESIUM_BASE_URL + "Assets/Textures/NaturalEarthII";

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
    // Le fond local d'abord : il est toujours disponible. Le fond routier est ajouté
    // ensuite, par-dessus, et reste transparent s'il ne charge jamais — la carte dégrade
    // donc proprement au lieu de disparaître.
    baseLayer: Cesium.ImageryLayer.fromProviderAsync(
      Cesium.TileMapServiceImageryProvider.fromUrl(FOND_LOCAL),
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

  // Le fond routier, en surcouche : précis à l'échelle d'une ville, mais distant. On le tente
  // et on l'oublie s'il ne répond pas — le fond local reste visible en dessous.
  // Le constructeur direct ne crée pas la ressource du fournisseur : la première tuile
  // demandée appelle alors `getDerivedResource` sur un objet indéfini, et Cesium arrête
  // sa boucle de rendu — le globe restait vide sans qu'aucune erreur ne remonte. Il faut
  // `fromUrl`, puis une couche construite depuis la promesse.
  const routier = Cesium.ImageryLayer.fromProviderAsync(
    Cesium.ArcGisMapServerImageryProvider.fromUrl(
      "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer",
      { credit: new Cesium.Credit(BASEMAP_CREDIT) },
    ),
  );
  routier.readyEvent?.catch?.((err) => {
    // Service injoignable : le fond local reste visible, ce n'est pas un échec.
    console.warn("fond routier indisponible, le fond local suffit :", err);
  });
  viewer.scene.imageryLayers.add(routier);

  // Cesium émet cet événement quand sa boucle de rendu échoue et s'arrête. Sans lui, un globe
  // vide ne se distingue pas d'un défaut de notre code : on saurait que rien n'est peint, pas
  // pourquoi. La raison est exposée pour être lue par les mesures automatiques.
  viewer.scene.renderError.addEventListener((scene, erreur) => {
    window.__carteErreur = erreur instanceof Error ? erreur.message : String(erreur);
    console.error("rendu de la carte arrêté :", erreur);
  });

  const points = viewer.scene.primitives.add(new Cesium.PointPrimitiveCollection());
  const labels = viewer.scene.primitives.add(new Cesium.LabelCollection());

  // Repère fantôme : il montre où l'équipement atterrira pendant qu'on le fait glisser,
  // avant que la position ne soit envoyée au serveur. Sans lui, on lâche à l'aveugle.
  const fantome = viewer.scene.primitives.add(new Cesium.PointPrimitiveCollection());

  // Liaisons observées. Tiretées, jamais pleines : une liaison radio se mesure, elle ne se
  // câble pas — le plein laisserait croire à un lien qu'on pourrait débrancher.
  const liaisons = viewer.scene.primitives.add(new Cesium.PolylineCollection());
  const etiquettesLiens = viewer.scene.primitives.add(new Cesium.LabelCollection());

  // Repère de zone : l'ancre géographique du réseau. Elle était invisible, alors que c'est
  // le point auquel tout est rattaché — on voyait les équipements sans voir ce qui les fixe
  // au sol. On trace un cercle à l'échelle du réseau, et une croix au centre.
  const zone = viewer.scene.primitives.add(new Cesium.PolylineCollection());

  // Environnement réel : obstacles et relief. La carte travaillait sur une ellipsoïde
  // plate, si bien qu'un réseau posé sur une colline s'affichait comme sur une plaine —
  // alors que la couverture, elle, est calculée **avec** le relief. Les deux vues
  // racontaient donc deux réseaux différents.
  const obstacles = viewer.dataSources.add(new Cesium.CustomDataSource("obstacles"));
  const couvertures = viewer.dataSources.add(new Cesium.CustomDataSource("couvertures"));

  // Relief local, décodé. `null` : ellipsoïde plate, état valide — un chantier sans
  // relief n'est pas une erreur.
  let dem = null;
  const SCHEMA_TUILES = new Cesium.GeographicTilingScheme();
  const TAILLE_TUILE = 65;
  // Derniers obstacles et zones reçus, gardés pour être refaits si le relief arrive
  // après eux : un pavé calé sur un sol plat flotte dès que le sol s'élève.
  let obstaclesAttendus = null;
  let couvertureAttendue = null;
  let noeudsAttendus = null;

  let origine = { lat: 4.0511, lon: 9.7679 };

  // Les équipements affichés, gardés pour retrouver lequel est sous le curseur. On les
  // projette à l'écran plutôt que d'appeler `scene.pick` : le résultat ne dépend alors pas
  // de la manière dont Cesium construit ses objets de sélection d'une version à l'autre.
  let affiches = [];

  // Cesium mesure son conteneur à la construction. S'il le fait avant que la mise en page
  // soit stabilisée, il retient une hauteur trop faible et ses blocs internes, dimensionnés
  // en pourcentage, s'effondrent les uns sur les autres : 640 puis 329 puis 156. Le canevas
  // reste alors à sa taille par défaut de 300×150 et le globe n'est pas peint.
  // On recale donc après une frame, puis à chaque changement de taille du conteneur.
  const recaler = () => {
    try { viewer.resize(); } catch { /* conteneur pas encore prêt : on retentera */ }
  };
  requestAnimationFrame(recaler);
  const observateur = typeof ResizeObserver === "function" ? new ResizeObserver(recaler) : null;
  observateur?.observe(container);

  // Position géographique sous un point de l'écran, ou null si le rayon ne touche pas le
  // globe (ciel, ou caméra au ras de l'horizon). `position` est en pixels CSS, relatifs
  // au canevas — le repère que fournissent Cesium comme les événements du DOM convertis.
  function lonLatAt(position) {
    if (!position) return null;
    const p = position instanceof Cesium.Cartesian2
      ? position
      : new Cesium.Cartesian2(position.x, position.y);
    const cible = viewer.scene.pickPosition?.(p)
      ?? viewer.camera.pickEllipsoid(p, viewer.scene.globe.ellipsoid);
    if (!cible) return null;
    const carto = Cesium.Cartographic.fromCartesian(cible);
    if (!carto) return null;
    return {
      lat: Cesium.Math.toDegrees(carto.latitude),
      lon: Cesium.Math.toDegrees(carto.longitude),
    };
  }

  // Un clic sur le globe : on lève la position géographique. Un clic dans le vide (ciel)
  // ne produit rien de exploitable et doit être ignoré silencieusement.
  // Un glisser se termine par un relâchement du bouton, que Cesium lit aussi comme un clic.
  // Sans cette trappe, poser un équipement déplacerait l'origine de la zone par-dessus le
  // marché. On neutralise donc le clic pendant une courte fenêtre après un geste de pose.
  let ignorerClicJusqua = 0;

  const gestionnaire = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
  gestionnaire.setInputAction((mouvement) => {
    if (!onPick) return;
    if (Date.now() < ignorerClicJusqua) return;
    const ll = lonLatAt(mouvement.position);
    if (ll) onPick(ll.lat, ll.lon);
  }, Cesium.ScreenSpaceEventType.LEFT_CLICK);

  /** Position locale d'un équipement, en mètres. `null` si inconnu ou inexploitable. */
  function centreLocal(id) {
    const n = (noeudsAttendus ?? []).find((c) => c.id === id);
    if (!n || !Number.isFinite(n.x_m) || !Number.isFinite(n.y_m)) return null;
    return { x_m: n.x_m, y_m: n.y_m };
  }

  /**
   * Dessine les obstacles de l'environnement : pavés extrudés depuis le sol le plus bas
   * de leur emprise jusqu'à leur hauteur. Sans relief, le sol vaut 0.
   *
   * @param {Array<{x_min_m:number,y_min_m:number,x_max_m:number,y_max_m:number,
   *                height_m:number,attenuation_db?:number}>} liste
   */
  function setObstacles(liste = []) {
    obstaclesAttendus = liste;
    obstacles.entities.removeAll();
    for (const o of liste ?? []) {
      const coins = [[o.x_min_m, o.y_min_m], [o.x_max_m, o.y_min_m],
        [o.x_max_m, o.y_max_m], [o.x_min_m, o.y_max_m]].map(([x, y]) => {
          const d = toLonLat(x, y, origine);
          return [d.lon, d.lat];
        });
      if (!coins.every(([lo, la]) => Number.isFinite(lo) && Number.isFinite(la))) continue;
      const base = dem ? footprintBase(dem, coins) : 0;
      obstacles.entities.add({
        name: "Obstacle",
        description: `hauteur ${o.height_m} m, atténuation ${o.attenuation_db ?? 0} dB`,
        polygon: {
          hierarchy: Cesium.Cartesian3.fromDegreesArray(coins.flat()),
          height: base,
          extrudedHeight: base + Number(o.height_m ?? 0),
          material: Cesium.Color.DARKSLATEGRAY.withAlpha(0.85),
          outline: true,
          outlineColor: Cesium.Color.BLACK.withAlpha(0.4),
        },
      });
    }
  }

  /**
   * Trace la zone de couverture de chaque passerelle, par palier de qualité.
   *
   * Les rayons viennent du moteur : relief, obstacles et lobe d'antenne. La carte ne
   * fait que les projeter — un disque qu'elle devinerait serait une zone fausse, et la
   * seule vue qu'on ne pourrait pas croiser avec le plan 2D.
   *
   * @param {Array<{node_id:string, modele:string, paliers:Array, antenna?:object}>} zones
   */
  function setCoverage(zones = []) {
    couvertureAttendue = zones;
    couvertures.entities.removeAll();
    for (const z of zones ?? []) {
      const centre = centreLocal(z?.node_id);
      if (!centre) continue;      // passerelle inconnue : pas de zone dans le vide
      // Du plus large au plus serré : le meilleur palier reste ainsi lisible par-dessus
      // les autres, au lieu d'être recouvert.
      const ordonne = [...(z.paliers ?? [])].sort(
        (a, b) => Math.max(...(b.radii_m ?? [0])) - Math.max(...(a.radii_m ?? [0])));
      for (const palier of ordonne) {
        const anneau = anneauZone(palier, centre);
        if (anneau.length < 4) continue;
        const positions = anneau.map((p) => {
          const d = toLonLat(p.x, p.y, origine);
          return Cesium.Cartesian3.fromDegrees(d.lon, d.lat);
        });
        if (!positions.every(Boolean)) continue;
        const teinte = COULEURS_QUALITE[palier.qualite] ?? "#1f6feb";
        couvertures.entities.add({
          name: `Zone ${palier.qualite} — ${z.node_id}`,
          description: `${etiquettePalier(palier)} · ${etiquetteModele(z.modele)}`,
          polygon: {
            hierarchy: new Cesium.PolygonHierarchy(positions),
            // Posé sur le sol : une zone suspendue à l'altitude de la passerelle serait
            // un plafond, pas une couverture.
            clampToGround: true,
            material: Cesium.Color.fromCssColorString(teinte).withAlpha(0.14),
            outline: palier.qualite === "limite",
            outlineColor: Cesium.Color.fromCssColorString(teinte).withAlpha(0.7),
          },
        });
      }
    }
  }

  /**
   * Applique le relief de la session. `null` remet l'ellipsoïde plate.
   *
   * Le MNT vient du serveur, jamais d'un chemin : le client ne sait pas où sont les
   * fichiers, et ne doit pas le savoir. Un document illisible n'est pas avalé en
   * silence — la carte resterait plate en laissant croire à un relief chargé, ce qui
   * est pire qu'une erreur franche.
   *
   * @param {object|null} reponse `{"terrain_id": .., "dem": ..}` de la route
   */
  function setTerrain(reponse) {
    const brut = reponse?.dem ?? null;
    dem = brut ? parseDem(brut) : null;
    if (dem) {
      viewer.terrainProvider = new Cesium.CustomHeightmapTerrainProvider({
        width: TAILLE_TUILE,
        height: TAILLE_TUILE,
        tilingScheme: SCHEMA_TUILES,
        callback: (x, y, niveau) => {
          const r = SCHEMA_TUILES.tileXYToRectangle(x, y, niveau);
          return heightmapTile(dem,
            Cesium.Math.toDegrees(r.west), Cesium.Math.toDegrees(r.south),
            Cesium.Math.toDegrees(r.east), Cesium.Math.toDegrees(r.north),
            TAILLE_TUILE, TAILLE_TUILE);
        },
      });
    } else {
      viewer.terrainProvider = new Cesium.EllipsoidTerrainProvider();
    }
    // Les pavés et les zones posés avant le relief reposaient sur un sol plat : les
    // refaire, sinon ils flottent ou s'enfoncent.
    if (obstaclesAttendus) setObstacles(obstaclesAttendus);
    if (couvertureAttendue) setCoverage(couvertureAttendue);
  }

  return {
    viewer,
    setTerrain,
    setObstacles,
    setCoverage,

    /** Plus grande portée affichée, en mètres. `null` sans zone : l'atelier s'en sert
     *  pour cadrer la caméra, et ne doit pas cadrer sur zéro. */
    porteeZone() {
      let max = null;
      for (const z of couvertureAttendue ?? []) {
        const p = porteeMax(z);
        if (p !== null && (max === null || p > max)) max = p;
      }
      return max;
    },

    /** Le relief est-il chargé ? Sert à ne pas annoncer un sol plat comme un relief. */
    aRelief() {
      return dem !== null;
    },

    // Entités posées, telles quelles. Exposées parce qu'un décor invisible ne se débogue
    // pas : sans elles, un pavé absent et un pavé mal placé se ressemblent.
    obstacles() { return obstacles.entities.values.slice(); },
    couvertures() { return couvertures.entities.values.slice(); },

    /** Origine de la zone : ancre entre les mètres du plan et les degrés de la carte. */
    setOrigin(o) {
      if (o && Number.isFinite(o.lat) && Number.isFinite(o.lon)) origine = o;
    },
    getOrigin() {
      return { ...origine };
    },

    /** La caméra se place au-dessus de l'origine, à une hauteur qui cadre `porteeM` mètres. */
    flyToOrigin(porteeM = 1200) {
      // Une position non finie fait lever à Cesium un « normalized result is not a number »
      // qui ne nomme rien. On préfère dire ce qui cloche, et renoncer au vol plutôt que
      // d'interrompre le rafraîchissement de toute l'interface.
      if (!Number.isFinite(origine.lat) || !Number.isFinite(origine.lon)) {
        console.error("vol impossible, origine inexploitable :", origine);
        return;
      }
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
    setNodes(noeuds, selectionId = null, resultats = null) {
      points.removeAll();
      labels.removeAll();
      affiches = noeuds ?? [];
      // Gardés pour replacer les zones si le relief arrive après les équipements.
      noeudsAttendus = affiches;
      for (const n of noeuds ?? []) {
        const { lon, lat } = toLonLat(n.x_m, n.y_m, origine);
        // Un seul équipement inexploitable ne doit pas priver la carte de tous les autres :
        // on l'ignore en disant lequel, au lieu de laisser Cesium lever une erreur anonyme
        // qui interrompt le tracé du reste du réseau.
        if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
          console.error(`équipement ${n.id} non tracé, position inexploitable :`,
            { x_m: n.x_m, y_m: n.y_m, origine });
          continue;
        }
        const estCapteur = n.kind === "sensor";
        const selectionne = n.id === selectionId;
        // Après un run, la couleur dit le **résultat** (taux de livraison), plus seulement
        // le type : c'est là que se lit le comportement du réseau. Sans résultat pour cet
        // équipement, on garde la couleur de type — un équipement non mesuré n'est pas un
        // équipement en échec.
        const r = resultats?.get(n.id);
        const couleur = r?.couleur
          ? Cesium.Color.fromCssColorString(r.couleur)
          : COULEURS[n.kind] ?? COULEURS.sensor;
        points.add({
          position: Cesium.Cartesian3.fromDegrees(lon, lat),
          color: couleur,
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

    /** Position géographique sous un point de l'écran (pixels CSS relatifs au canevas). */
    lonLatAt,

    /**
     * L'équipement affiché le plus proche de ce point de l'écran, ou null.
     *
     * On projette chaque équipement et on garde le plus proche dans un rayon de
     * `tolerancePx`, plutôt que d'appeler `scene.pick` : c'est déterministe, ça marche
     * même quand le point est dessiné sans profondeur (disableDepthTestDistance), et ça ne
     * casse pas si Cesium change la forme de ses objets de sélection.
     *
     * @param {{x: number, y: number}} position pixels CSS relatifs au canevas
     * @param {number} [tolerancePx]
     */
    /**
     * Trace les liaisons observées entre les équipements affichés : relais -> frontière
     * (genre « mesh ») et capteur -> passerelle (genre « radio »).
     *
     *
     * @param liaisonsObservees [{ de, vers, genre, compte }] en identifiants d'équipements
     *
     * Une liaison dont un bout est absent ou inexploitable est sautée : la carte préfère
     * un trait manquant à un trait faux, et à une erreur anonyme de Cesium qui
     * interromprait le tracé du reste du réseau.
     */
    setLiaisons(liaisonsObservees = [], noeuds = []) {
      liaisons.removeAll();
      etiquettesLiens.removeAll();
      // Une primitive Cesium n'existe pas dans le DOM : rien ne peut la compter de
      // l'extérieur. On expose donc le compte, comme `window.__carteErreur` expose la raison
      // d'un rendu arrêté — sans cela, un trait jamais tracé ne se distinguerait pas d'un
      // trait que personne ne regarde.
      window.__liaisonsCarte = 0;
      const parId = new Map((noeuds ?? []).map((n) => [n.id, n]));
      for (const l of liaisonsObservees) {
        const bouts = boutsLiaison(l, parId, origine);
        if (!bouts) continue;
        // Légèrement au-dessus du sol : à l'altitude zéro, le relief et le fond de carte
        // avalent le trait dès qu'on zoome un peu.
        const hauteur = 40;
        const p = Cesium.Cartesian3.fromDegrees(bouts.de.lon, bouts.de.lat, hauteur);
        const q = Cesium.Cartesian3.fromDegrees(bouts.vers.lon, bouts.vers.lat, hauteur);
        // Deux natures, deux couleurs : un relais vers une frontière est un acheminement,
        // un capteur vers une passerelle est une portée. Les peindre pareil ferait lire
        // « ce capteur est raccordé » la où il est seulement entendu.
        const style = STYLE_LIAISON[l.genre] ?? STYLE_LIAISON.mesh;
        liaisons.add({
          positions: [p, q],
          width: style.largeur,
          material: Cesium.Material.fromType("PolylineDash", {
            color: Cesium.Color.fromCssColorString(style.couleur).withAlpha(0.9),
            gapColor: Cesium.Color.TRANSPARENT,
            dashLength: 18,
          }),
        });
        const milieu = Cesium.Cartesian3.fromDegrees(
          (bouts.de.lon + bouts.vers.lon) / 2, (bouts.de.lat + bouts.vers.lat) / 2, hauteur);
        etiquettesLiens.add({
          position: milieu,
          text: etiquetteLiaison(l),
          font: "600 12px system-ui, sans-serif",
          fillColor: Cesium.Color.fromCssColorString(style.clair),
          outlineColor: Cesium.Color.fromCssColorString(style.sombre),
          outlineWidth: 3,
          style: Cesium.LabelStyle.FILL_AND_OUTLINE,
          verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
          pixelOffset: new Cesium.Cartesian2(0, -6),
          disableDepthTestDistance: 0,
        });
        window.__liaisonsCarte += 1;
      }
    },

    nodeAt(position, tolerancePx = 22) {
      if (!position) return null;
      const scene = viewer.scene;
      let meilleur = null;
      let meilleurD = tolerancePx;
      for (const n of affiches) {
        const { lon, lat } = toLonLat(n.x_m, n.y_m, origine);
        const ecran = Cesium.SceneTransforms.worldToWindowCoordinates(
          scene, Cesium.Cartesian3.fromDegrees(lon, lat));
        // Derrière la caméra, ou hors écran : `worldToWindowCoordinates` rend undefined.
        if (!ecran) continue;
        const d = Math.hypot(ecran.x - position.x, ecran.y - position.y);
        if (d <= meilleurD) { meilleurD = d; meilleur = n; }
      }
      return meilleur;
    },

    /**
     * Positions à l'écran des équipements affichés, en pixels CSS relatifs au canevas.
     *
     * Sert à viser un point **vide** : un essai qui clique au hasard peut tomber sur un
     * équipement, dont l'écouteur en capture intercepte alors le geste — à juste titre,
     * puisque cliquer un équipement sert à le déplacer, pas à déplacer la zone. Sans cette
     * liste, on ne peut pas distinguer un défaut de l'application d'un clic mal placé.
     *
     * @returns {Array<{id: string, x: number, y: number}>}
     */
    nodeScreenPositions() {
      const out = [];
      for (const n of affiches) {
        // `toLonLat` prend { lat, lon }, pas deux nombres : passer `origine.lat, origine.lon`
        // faisait lever « origine inexploitable » à chaque appel. La fonction n'était pas
        // appelée, donc le défaut ne se voyait pas — un piège plutôt qu'une panne.
        const { lon, lat } = toLonLat(n.x_m, n.y_m, origine);
        const e = Cesium.SceneTransforms.worldToWindowCoordinates(
          viewer.scene, Cesium.Cartesian3.fromDegrees(lon, lat));
        if (e) out.push({ id: n.id, x: e.x, y: e.y });
      }
      return out;
    },

    /**
     * Montre un repère à l'endroit où l'équipement sera posé, pendant le glisser.
     * @param {number} lat @param {number} lon @param {string} [kind]
     */
    showGhost(lat, lon, kind = "sensor") {
      fantome.removeAll();
      if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;
      fantome.add({
        position: Cesium.Cartesian3.fromDegrees(lon, lat),
        color: (COULEURS[kind] ?? COULEURS.sensor).withAlpha(0.55),
        pixelSize: 22,
        outlineColor: Cesium.Color.WHITE,
        outlineWidth: 3,
        disableDepthTestDistance: 0,
      });
    },

    /** Retire le repère, le glisser est fini. */
    clearGhost() {
      fantome.removeAll();
    },

    /**
     * Empêche la caméra de pivoter pendant qu'on déplace un équipement. Sans ça, le
     * geste qui veut poser un capteur fait tourner le globe à la place.
     */
    setDragging(actif) {
      const c = viewer.scene.screenSpaceCameraController;
      if (c) c.enableInputs = !actif;
    },

    /**
     * Neutralise le clic pendant `dureeMs`. À appeler à la fin d'un glisser, pour que le
     * relâchement du bouton ne soit pas pris pour une demande de déplacer l'origine.
     */
    setIgnoreClick(dureeMs = 500) {
      ignorerClicJusqua = Date.now() + Math.max(0, dureeMs);
    },

    /**
     * Trace l'ancre de la zone : un cercle à l'échelle du réseau et une croix au centre.
     *
     * @param {number} lat @param {number} lon
     * @param {number} porteeM rayon représentant l'étendue du réseau, en mètres
     */
    setZone(lat, lon, porteeM = 300) {
      zone.removeAll();
      if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;
      const centre = Cesium.Cartesian3.fromDegrees(lon, lat);
      const rayon = Math.max(60, porteeM);

      // Le cercle : 96 segments, comme `coverage_ring` du serveur, pour rester rond même
      // sur plusieurs kilomètres.
      const anneau = [];
      for (let i = 0; i <= 96; i++) {
        const a = (i / 96) * Math.PI * 2;
        const d = toLonLat(Math.cos(a) * rayon, Math.sin(a) * rayon, { lat, lon });
        anneau.push(Cesium.Cartesian3.fromDegrees(d.lon, d.lat));
      }
      zone.add({
        positions: anneau,
        width: 2,
        material: Cesium.Material.fromType("Color", {
          color: Cesium.Color.fromCssColorString("#ffffff").withAlpha(0.55),
        }),
      });

      // La croix : elle marque le point exact, que le cercle seul laisserait au centre d'un
      // disque sans le désigner.
      const b = Math.max(12, rayon * 0.06);
      for (const [dx, dy] of [[b, 0], [-b, 0]]) {
        const d = toLonLat(dx, dy, { lat, lon });
        zone.add({
          positions: [centre, Cesium.Cartesian3.fromDegrees(d.lon, d.lat)],
          width: 3,
          material: Cesium.Material.fromType("Color", {
            color: Cesium.Color.fromCssColorString("#ff9f1c"),
          }),
        });
      }
      for (const [dx, dy] of [[0, b], [0, -b]]) {
        const d = toLonLat(dx, dy, { lat, lon });
        zone.add({
          positions: [centre, Cesium.Cartesian3.fromDegrees(d.lon, d.lat)],
          width: 3,
          material: Cesium.Material.fromType("Color", {
            color: Cesium.Color.fromCssColorString("#ff9f1c"),
          }),
        });
      }
    },

    /** À appeler quand la carte devient visible : elle n'a pas de taille quand elle est masquée. */
    resize() {
      recaler();
    },

    destroy() {
      observateur?.disconnect();
      fantome.removeAll();
      zone.removeAll();
      gestionnaire.destroy?.();
      viewer.destroy?.();
    },
  };
}
