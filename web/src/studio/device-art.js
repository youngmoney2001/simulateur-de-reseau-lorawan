// Illustrations des équipements, pour l'onglet Physique des fenêtres de configuration.
//
// Deux parties volontairement séparées :
//   - `DEVICE_SPECS` : les données (rôle, ports, voyants). Pures, donc testables sans
//     navigateur, et seules à engager la conformité de ce qui est annoncé.
//   - `drawDevice` : le dessin, en SVG tracé à la main. Aucune image externe : le style
//     reste homogène et le rendu net à toute échelle.
//
// Règle de conformité : rien n'est dessiné ni annoncé qui ne corresponde à une fonction
// réellement simulée par le moteur. Les ports et voyants ci-dessous décrivent le matériel
// que l'équipement représente ; ils ne prétendent pas rendre des réglages inexistants.
const SVG_NS = "http://www.w3.org/2000/svg";

export const DEVICE_SPECS = {
  sensor: {
    role: "Capteur LoRaWAN — émetteur autonome sur pile",
    ports: [
      { id: "antenne", label: "Antenne", note: "fouet quart d'onde" },
      { id: "sonde", label: "Sonde", note: "mesure périodique" },
      { id: "pile", label: "Pile", note: "autonomie selon période et SF" },
    ],
    leds: [
      { id: "emission", label: "Émission", etat: "selon le trafic" },
    ],
  },
  border: {
    role: "Passerelle frontière — relie le réseau LoRa au serveur",
    ports: [
      { id: "antenne", label: "Antenne", note: "réception des trames" },
      { id: "ethernet", label: "Ethernet", note: "vers le serveur de réseau" },
      { id: "alim", label: "Alimentation", note: "secteur ou PoE" },
    ],
    leds: [
      { id: "alim", label: "Alimentation", etat: "allumée" },
      { id: "radio", label: "Radio", etat: "trafic reçu" },
      { id: "lien", label: "Lien", etat: "vers le serveur" },
    ],
  },
  relay: {
    role: "Passerelle relais — réémet vers une passerelle frontière",
    ports: [
      { id: "antenne-1", label: "Antenne accès", note: "vers les capteurs" },
      { id: "antenne-2", label: "Antenne retour", note: "vers la frontière" },
      { id: "alim", label: "Alimentation", note: "secteur ou PoE" },
    ],
    leds: [
      { id: "alim", label: "Alimentation", etat: "allumée" },
      { id: "relais", label: "Relais", etat: "trames réémises" },
    ],
  },
  server: {
    role: "Serveur de réseau — agrège les trames et tient le registre",
    ports: [
      { id: "reseau", label: "Réseau", note: "vers les passerelles" },
      { id: "alim", label: "Alimentation", note: "secteur redondée" },
    ],
    leds: [
      { id: "alim", label: "Alimentation", etat: "allumée" },
      { id: "activite", label: "Activité", etat: "trames traitées" },
    ],
  },
};

export const DEVICE_KINDS = Object.keys(DEVICE_SPECS);

function svg(tag, attrs = {}, ...children) {
  const n = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === null || v === false) continue;
    n.setAttribute(k, String(v));
  }
  for (const c of children) if (c) n.append(c);
  return n;
}

// Palette commune à tous les équipements : cohérente avec le plan et la carte 3D.
const BOITIER = "#dfe6ee";
const CONTOUR = "#8b98a5";
const FOND = "#ffffff";
const SOMBRE = "#5b6875";
const ANTENNE = "#3d4753";

/** Socle commun : ombre portée, pour que les boîtiers ne flottent pas. */
function socle(cx, y, largeur) {
  return svg("ellipse", { cx, cy: y, rx: largeur / 2, ry: 5, fill: "#00000012" });
}

/** Un boîtier : corps arrondi, façade plus claire, pied. */
function boitier(x, y, w, h, rayon = 6) {
  const g = svg("g", {});
  g.append(svg("rect", { x, y, width: w, height: h, rx: rayon, ry: rayon,
    fill: BOITIER, stroke: CONTOUR, "stroke-width": 1.5 }));
  g.append(svg("rect", { x: x + 4, y: y + 4, width: w - 8, height: h - 8, rx: rayon - 2,
    fill: FOND, opacity: 0.55 }));
  return g;
}

/** Un voyant : cercle coloré, plus un cercle plus clair pour le verre. */
function voyant(cx, cy, couleur) {
  const g = svg("g", {});
  g.append(svg("circle", { cx, cy, r: 4, fill: couleur, stroke: CONTOUR, "stroke-width": 0.8 }));
  g.append(svg("circle", { cx: cx - 1.2, cy: cy - 1.2, r: 1.4, fill: "#ffffff", opacity: 0.75 }));
  return g;
}

/** Un port : rectangle évidé, dans l'esprit des connecteurs. */
function port(x, y, w, h, remplissage = SOMBRE) {
  return svg("rect", { x, y, width: w, height: h, rx: 1.5,
    fill: remplissage, stroke: CONTOUR, "stroke-width": 0.8 });
}

/** Antenne fouet : tige, puis embout. */
function antenne(x, yBas, hauteur) {
  const g = svg("g", {});
  g.append(svg("line", { x1: x, y1: yBas, x2: x, y2: yBas - hauteur,
    stroke: ANTENNE, "stroke-width": 2.5, "stroke-linecap": "round" }));
  g.append(svg("circle", { cx: x, cy: yBas - hauteur, r: 2.5, fill: ANTENNE }));
  return g;
}

const VUES = {
  // Capteur : petit boîtier, antenne, sonde sur le côté, pile lisible.
  sensor() {
    const g = svg("g", {});
    g.append(socle(120, 148, 96));
    g.append(antenne(150, 62, 46));
    g.append(boitier(84, 62, 72, 78));
    // Sonde : cylindre déporté à gauche, relié par un fil.
    g.append(svg("path", { d: "M 84 100 L 62 100", stroke: ANTENNE, "stroke-width": 2 }));
    g.append(svg("rect", { x: 44, y: 90, width: 18, height: 20, rx: 3,
      fill: BOITIER, stroke: CONTOUR, "stroke-width": 1.5 }));
    g.append(svg("line", { x1: 53, y1: 110, x2: 53, y2: 124,
      stroke: ANTENNE, "stroke-width": 2, "stroke-linecap": "round" }));
    // Grille du haut-parleur ou de l'évent : repère visuel de boîtier.
    for (let i = 0; i < 4; i += 1) {
      g.append(svg("line", { x1: 96, y1: 78 + i * 5, x2: 132, y2: 78 + i * 5,
        stroke: CONTOUR, "stroke-width": 1, opacity: 0.5 }));
    }
    g.append(voyant(120, 120, "#2ea043"));
    // append() ne renvoie rien : l'élément doit exister avant d'être rempli.
    const etiquette = svg("text", { x: 120, y: 133, "text-anchor": "middle",
      "font-size": 8, fill: SOMBRE });
    etiquette.textContent = "LoRa";
    g.append(etiquette);
    return g;
  },

  // Passerelle frontière : boîtier plus haut, antenne à plan de masse, connecteurs.
  border() {
    const g = svg("g", {});
    g.append(socle(120, 148, 104));
    g.append(antenne(120, 40, 40));
    // Plan de masse : trois radians sous l'antenne.
    for (const d of [-16, 0, 16]) {
      g.append(svg("line", { x1: 120, y1: 44, x2: 120 + d, y2: 56,
        stroke: ANTENNE, "stroke-width": 1.6, "stroke-linecap": "round" }));
    }
    g.append(boitier(76, 56, 88, 84, 8));
    // Façade : baie d'aération.
    for (let i = 0; i < 5; i += 1) {
      g.append(svg("rect", { x: 86, y: 66 + i * 7, width: 68, height: 3, rx: 1.5,
        fill: CONTOUR, opacity: 0.35 }));
    }
    // Connecteurs en pied de façade.
    g.append(port(86, 112, 20, 14));
    g.append(port(112, 112, 14, 14));
    // Voyants.
    g.append(voyant(140, 116, "#2ea043"));
    g.append(voyant(140, 128, "#1f6feb"));
    return g;
  },

  // Relais : même gabarit, deux antennes — l'accès et le retour.
  relay() {
    const g = svg("g", {});
    g.append(socle(120, 148, 104));
    g.append(antenne(104, 40, 40));
    g.append(antenne(136, 46, 34));
    g.append(boitier(76, 56, 88, 84, 8));
    // Deux baies, pour marquer la double chaîne radio.
    for (let i = 0; i < 5; i += 1) {
      g.append(svg("rect", { x: 86, y: 66 + i * 7, width: 32, height: 3, rx: 1.5,
        fill: CONTOUR, opacity: 0.35 }));
      g.append(svg("rect", { x: 122, y: 66 + i * 7, width: 32, height: 3, rx: 1.5,
        fill: CONTOUR, opacity: 0.35 }));
    }
    // Flèche de réémission, de l'accès vers le retour.
    g.append(svg("path", { d: "M 104 60 L 136 60", stroke: "#9a6700", "stroke-width": 1.6,
      "stroke-dasharray": "3 2", fill: "none" }));
    g.append(svg("path", { d: "M 132 57 L 137 60 L 132 63 Z", fill: "#9a6700" }));
    g.append(port(86, 112, 20, 14));
    g.append(voyant(140, 116, "#2ea043"));
    g.append(voyant(140, 128, "#f2cc60"));
    return g;
  },

  // Serveur : châssis rack, baies de disques, grille, ports réseau.
  server() {
    const g = svg("g", {});
    g.append(socle(120, 148, 120));
    g.append(boitier(64, 52, 112, 88, 5));
    // Grille de ventilation sur la gauche.
    for (let i = 0; i < 7; i += 1) {
      g.append(svg("rect", { x: 72, y: 60 + i * 10, width: 40, height: 5, rx: 2,
        fill: CONTOUR, opacity: 0.3 }));
    }
    // Baies : trois tiroirs, chacun avec son voyant.
    for (let i = 0; i < 3; i += 1) {
      const y = 60 + i * 24;
      g.append(svg("rect", { x: 120, y, width: 46, height: 20, rx: 2,
        fill: BOITIER, stroke: CONTOUR, "stroke-width": 1.2 }));
      g.append(svg("rect", { x: 124, y: y + 5, width: 30, height: 4, rx: 1,
        fill: CONTOUR, opacity: 0.4 }));
      g.append(voyant(160, y + 10, i === 0 ? "#2ea043" : "#c9d1d9"));
    }
    // Deux ports réseau en pied.
    g.append(port(72, 126, 22, 12));
    g.append(port(100, 126, 22, 12));
    g.append(voyant(140, 132, "#1f6feb"));
    return g;
  },
};

/**
 * Dessine l'équipement. Retourne un élément SVG autonome.
 * @param {string} kind
 */
export function drawDevice(kind) {
  const dessin = VUES[kind] ?? VUES.sensor;
  const svgEl = svg("svg", {
    viewBox: "0 0 240 160",
    class: "device-art",
    role: "img",
    "aria-label": `${DEVICE_SPECS[kind]?.role ?? "Équipement"} (illustration)`,
  });
  svgEl.append(dessin());
  return svgEl;
}

/** Vrai si ce type possède une illustration propre. */
export function hasArt(kind) {
  return Object.prototype.hasOwnProperty.call(VUES, kind);
}
