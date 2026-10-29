// Géométrie du plan et validation des formulaires (logique pure, sans DOM).
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
export function planBounds(nodes) {
  if (!nodes.length) return { minX: -500, maxX: 500, minY: -500, maxY: 500 };
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  for (const n of nodes) {
    minX = Math.min(minX, n.x_m);
    maxX = Math.max(maxX, n.x_m);
    minY = Math.min(minY, n.y_m);
    maxY = Math.max(maxY, n.y_m);
  }
  const cx = (minX + maxX) / 2, cy = (minY + maxY) / 2;
  const span = Math.max(maxX - minX, maxY - minY, 1000) * 1.2;
  return { minX: cx - span / 2, maxX: cx + span / 2, minY: cy - span / 2, maxY: cy + span / 2 };
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

export function nodeCaption(node) {
  return `${node.name} (${node.id})`;
}
