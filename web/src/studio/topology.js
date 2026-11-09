// Géométrie du plan et validation des formulaires (logique pure, sans DOM).
import { degresVersMetres, estLatitude, estLongitude } from "./geo.js";
// Les règles reprennent celles du serveur (`study_contract.py`) pour un retour immédiat ; le serveur
// reste l'autorité : une valeur refusée ici n'est jamais acceptée par défaut ailleurs.

export const KINDS = ["border", "relay", "sensor", "server"];
export const KIND_LABEL = {
  border: "Passerelle frontière",
  relay: "Passerelle relais",
  sensor: "Capteur",
  server: "Serveur",
};
export const CLI_KINDS = ["border", "relay"];
export const REGIONS = ["EU868", "US915", "AU915", "AS923", "KR920", "IN865", "RU864"];
export const ID_PATTERN = /^[a-z][a-z0-9-]{0,31}$/;
const COORD_LIMIT = 1_000_000;

// Bornes des réglages capteur, identiques à `SensorSettings` (study_contract.py).
export const SENSOR_LIMITS = {
  spreading_factor: [7, 12],
  payload_bytes: [0, 255],
  tx_power_dbm: [-10, 30],
  period_s: [0.001, 86400],
  messages: [1, 1000],
  start_spread_s: [0, 86400],
  channel_freq_hz: [137_000_000, 3_000_000_000],
};
export const SENSOR_DEFAULTS = {
  spreading_factor: 7,
  payload_bytes: 10,
  tx_power_dbm: 14,
  period_s: 600,
  messages: 1,
  start_spread_s: 0,
  region: "",
  channel_freq_hz: "",
};

// Cadre du plan : englobe les équipements, marge de 10 %, étendue minimale de 1 km.
// Cadrage du plan. La portée minimale était de 1000 m : un réseau de quatre capteurs
// distants de 300 m était donc noyé dans 1200 m de vide, et les équipements devenaient
// invisibles. On cadre désormais sur ce qui existe, avec une marge minimale.
export const PLAN_MIN_SPAN_M = 60;   // plan vide : 60 m de large, pour que la grille ait un sens
export const PLAN_MIN_MARGIN_M = 15; // marge minimale autour des équipements, même très serrés

export function planBounds(nodes) {
  if (!nodes.length) {
    const d = PLAN_MIN_SPAN_M / 2;
    return { minX: -d, maxX: d, minY: -d, maxY: d };
  }
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  for (const n of nodes) {
    minX = Math.min(minX, n.x_m);
    maxX = Math.max(maxX, n.x_m);
    minY = Math.min(minY, n.y_m);
    maxY = Math.max(maxY, n.y_m);
  }
  // Cadrage serré : 20 % de marge autour de l'encombrement réel, jamais moins de 15 m.
  const span = Math.max(maxX - minX, maxY - minY, 0.001);
  const pad = Math.max(span * 0.2, PLAN_MIN_MARGIN_M);
  return { minX: minX - pad, maxX: maxX + pad, minY: minY - pad, maxY: maxY + pad };
}

// Pas de la grille : un des paliers 1, 2 ou 5 × 10^n, choisi pour obtenir de 5 à 12 lignes.
export function gridStep(span) {
  if (!(span > 0) || !Number.isFinite(span)) return 10;
  const brut = span / 8;
  const puissance = Math.pow(10, Math.floor(Math.log10(brut)));
  const mantisse = brut / puissance;
  const palier = mantisse <= 1 ? 1 : mantisse <= 2 ? 2 : mantisse <= 5 ? 5 : 10;
  return palier * puissance;
}

// Mètres -> pixels (y vers le bas). `toMeters` est l'inverse, utilisé au glisser-déposer.
export function toScreen(point, bounds, width, height) {
  const sx = width / (bounds.maxX - bounds.minX);
  const sy = height / (bounds.maxY - bounds.minY);
  return {
    x: (point.x_m - bounds.minX) * sx,
    y: height - (point.y_m - bounds.minY) * sy,
  };
}

export function toMeters(screen, bounds, width, height) {
  const sx = width / (bounds.maxX - bounds.minX);
  const sy = height / (bounds.maxY - bounds.minY);
  return {
    x_m: Math.round((screen.x / sx + bounds.minX) * 10) / 10,
    y_m: Math.round(((height - screen.y) / sy + bounds.minY) * 10) / 10,
  };
}

function num(value) {
  if (typeof value === "string" && value.trim() === "") return NaN;
  return Number(value);
}

function bad(field, message) {
  return { ok: false, field, message };
}

// Formulaire d'ajout d'équipement -> corps de `POST /nodes`.
export function validateNewNode(form) {
  const id = String(form.id ?? "").trim();
  if (!ID_PATTERN.test(id)) {
    return bad("id", "identifiant : minuscules, chiffres et tirets, 1 à 32 caractères, commence par une lettre");
  }
  if (!KINDS.includes(form.kind)) return bad("kind", "type d'équipement inconnu");
  const name = String(form.name ?? "").trim() || id;
  if (name.length > 64) return bad("name", "nom : 64 caractères au plus");
  const x = num(form.x_m), y = num(form.y_m);
  if (!Number.isFinite(x) || Math.abs(x) > COORD_LIMIT) return bad("x_m", "abscisse : nombre attendu");
  if (!Number.isFinite(y) || Math.abs(y) > COORD_LIMIT) return bad("y_m", "ordonnée : nombre attendu");
  return { ok: true, node: { id, kind: form.kind, name, x_m: x, y_m: y } };
}

/**
 * Ajout par coordonnées géographiques : l'utilisateur saisit des degrés, le moteur reçoit
 * des mètres (invariant D2).
 *
 * La validation porte sur ce que l'utilisateur a **tapé**. Un refus doit parler de latitude
 * hors domaine, pas d'une ordonnée en mètres qu'il n'a jamais vue — sinon le message
 * d'erreur décrit un nombre que rien ne relie à sa saisie.
 *
 * @param {Record<string, string>} form champs `id`, `name`, `kind`, `lat`, `lon`
 * @param {{lat: number, lon: number}} origine ancre géographique de la zone
 */
export function validateNewNodeGeo(form, origine) {
  // Les champs communs (identifiant, type, nom) sont validés une seule fois : on passe des
  // coordonnées nulles, puis on remplace la position. Réécrire ces règles ici les ferait
  // diverger de `validateNewNode` à la première correction.
  const base = validateNewNode({ ...form, x_m: 0, y_m: 0 });
  if (!base.ok) return base;

  // Aucune coordonnée saisie : l'équipement se pose à l'origine de la zone. C'est le cas
  // le plus fréquent — on place d'abord, on ajuste ensuite — et refuser un champ vide
  // obligerait à recopier des degrés qu'on vient de donner en choisissant la zone.
  const vide = String(form.lat ?? "").trim() === "" && String(form.lon ?? "").trim() === "";
  const lat = vide ? origine.lat : num(form.lat);
  const lon = vide ? origine.lon : num(form.lon);
  if (!estLatitude(lat)) return bad("lat", "latitude : nombre attendu, entre −90 et 90");
  if (!estLongitude(lon)) return bad("lon", "longitude : nombre attendu, entre −180 et 180");

  const { x_m, y_m } = degresVersMetres(lat, lon, origine);
  // Un degré de longitude vaut 111 km : une zone reste petite, mais rien n'empêche de
  // saisir une coordonnée à l'autre bout du monde. La borne évite d'envoyer au moteur une
  // position que l'échelle du plan rendrait absurde.
  if (!Number.isFinite(x_m) || Math.abs(x_m) > COORD_LIMIT)
    return bad("lon", "longitude : trop éloignée de l'origine de la zone");
  if (!Number.isFinite(y_m) || Math.abs(y_m) > COORD_LIMIT)
    return bad("lat", "latitude : trop éloignée de l'origine de la zone");

  return { ok: true, node: { ...base.node, x_m, y_m } };
}

// Valeurs du formulaire capteur, à partir de l'équipement (défauts si aucun réglage n'est saisi).
export function sensorFormFrom(node) {
  const s = node?.sensor;
  if (!s) return { ...SENSOR_DEFAULTS };
  return {
    spreading_factor: s.spreading_factor,
    payload_bytes: s.payload_bytes,
    tx_power_dbm: s.tx_power_dbm,
    period_s: s.period_s,
    messages: s.messages,
    start_spread_s: s.start_spread_s,
    region: s.region ?? "",
    channel_freq_hz: s.channel_freq_hz ?? "",
  };
}

const INTEGER_SENSOR_KEYS = new Set(["spreading_factor", "payload_bytes", "messages", "channel_freq_hz"]);

// Formulaire capteur -> corps de `POST /nodes/{id}/sensor`.
export function validateSensor(form) {
  const out = {};
  for (const [key, [lo, hi]] of Object.entries(SENSOR_LIMITS)) {
    const raw = form[key];
    if (key === "channel_freq_hz" && (raw === "" || raw == null)) continue;
    const value = num(raw);
    if (!Number.isFinite(value) || value < lo || value > hi) {
      return bad(key, `${key} : entre ${lo} et ${hi}`);
    }
    out[key] = INTEGER_SENSOR_KEYS.has(key) ? Math.trunc(value) : value;
  }
  if (form.region) {
    if (!REGIONS.includes(form.region)) return bad("region", "plan régional inconnu");
    out.region = form.region;
  }
  return { ok: true, settings: out };
}

// --- Réglages passerelle exposés dans l'atelier ----------------------------------------------
// Mêmes bornes que le CLI (`study_cli.COMMANDS`) : un réglage refusé dans la fenêtre l'est
// aussi dans la console, avec le même mot. Les deux chemins écrivent la même configuration.

// Une sous-bande n'existe que sur ces deux plans. Ailleurs, le champ est sans objet — et non
// pas « à zéro », qui serait une valeur trompeuse.
export const REGIONS_A_SOUS_BANDE = ["US915", "AU915"];
export const SOUS_BANDES = [1, 2, 3, 4, 5, 6, 7, 8];
export const BANDES_MESH_KHZ = ["203", "406", "812", "1625"];
export const MODES_MESH = ["relay", "border"];
export const GATEWAY_LIMITS = {
  tx_power_dbm: [-10, 30],
  mesh_max_hops: [1, 8],
};

// Ce qui reste au CLI, et que la fenêtre doit dire plutôt que de le faire disparaître.
export const AVANCE_EN_CLI = [
  "gain d'antenne",
  "fréquence",
  "facteur d'étalement du mesh",
  "arrêt d'interface",
];

/**
 * Formulaire passerelle -> corps de `POST /nodes/{id}/gateway`.
 * Un champ vide emporte « ne pas toucher » : la fenêtre n'affiche pas l'antenne, elle ne
 * doit donc pas pouvoir l'effacer. Seuls les champs renseignés sont envoyés.
 */
export function validateGateway(form) {
  const out = {};
  if (form.region) {
    if (!REGIONS.includes(form.region)) return bad("region", "plan régional inconnu");
    out.region = form.region;
  }
  const region = out.region ?? form.region_actuelle ?? null;
  if (form.sub_band !== "" && form.sub_band != null) {
    if (!REGIONS_A_SOUS_BANDE.includes(region)) {
      return bad("sub_band", "sous-bande : région US915 ou AU915 requise");
    }
    const v = num(form.sub_band);
    if (!Number.isFinite(v) || !SOUS_BANDES.includes(Math.trunc(v))) {
      return bad("sub_band", "sous-bande : entre 1 et 8");
    }
    out.sub_band = Math.trunc(v);
  }
  for (const [key, [lo, hi]] of Object.entries(GATEWAY_LIMITS)) {
    if (form[key] === "" || form[key] == null) continue;
    const v = num(form[key]);
    if (!Number.isFinite(v) || v < lo || v > hi) {
      return bad(key, `${key} : entre ${lo} et ${hi}`);
    }
    out[key] = key === "mesh_max_hops" ? Math.trunc(v) : v;
  }
  if (form.mesh_mode) {
    if (!MODES_MESH.includes(form.mesh_mode)) return bad("mesh_mode", "mode de relais inconnu");
    out.mesh_mode = form.mesh_mode;
  }
  if (form.mesh_bandwidth_khz) {
    if (!BANDES_MESH_KHZ.includes(form.mesh_bandwidth_khz)) {
      return bad("mesh_bandwidth_khz",
        `bande : ${BANDES_MESH_KHZ.join(", ")} kHz`);
    }
    out.mesh_bandwidth_khz = form.mesh_bandwidth_khz;
  }
  return { ok: true, settings: out };
}

export function nodeCaption(node) {
  return `${node.name} (${node.id})`;
}

/**
 * Ce que la case ADR écrit à côté d'elle.
 *
 * Fonction pure, sans DOM ni `state` : c'est ce qui permet de la vérifier hors navigateur,
 * comme `validateGateway` l'est déjà. Seule reste à la vue la pose du texte.
 *
 * Deux règles, et elles viennent du §1 :
 *   - un réglage grisé porte **sa raison**, jamais un silence ;
 *   - quand l'ADR n'est pas possible mais reste demandé, on dit d'abord pourquoi, ensuite
 *     qu'on a gardé le souhait — et surtout on ne prétend pas qu'il sera simulé.
 *
 * @param possible l'ADR est-il simulable sur cette topologie (dit par le serveur) ?
 * @param raison   pourquoi il ne l'est pas, telle que le serveur l'énonce
 * @param actif    l'utilisateur l'a-t-il demandé ?
 */
export function adrMessage({ possible = false, raison = "", actif = false } = {}) {
  if (possible) {
    return actif
      ? "ADR activé : ce run ne simule ni relais ni liaisons radio par couple."
      : "Le serveur adaptera le débit et la puissance des capteurs (LinkADRReq).";
  }
  const garde = actif ? " — le souhait est gardé, mais ce run sera lancé sans ADR." : "";
  return `${raison}${garde}`;
}

/**
 * Ce qu'on annonce après une bascule : ce qui est **réellement** simulable, pas ce qui a été
 * demandé. Le serveur garde le souhait sans pouvoir l'appliquer ; le répéter tel quel
 * laisserait croire à un run qu'on n'aura pas.
 */
export function adrStatut({ possible = false, raison = "", actif = false } = {}) {
  if (actif && possible) {
    return "ADR du serveur activé : le prochain run simulera les LinkADRReq.";
  }
  if (actif) {
    return `ADR demandé mais non simulable : ${raison || "topologie incompatible"}`;
  }
  return "ADR désactivé.";
}
