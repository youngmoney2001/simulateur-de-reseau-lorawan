// Sauvegarde et chargement d'un chantier : l'équivalent du `.pkt`.
//
// Un chantier, c'est ce que l'utilisateur a construit : les équipements, leurs réglages, et
// l'endroit du monde où il les a posés. Ce n'est pas le résultat d'une simulation — un run se
// relance, un chantier se reprend.
//
// Ce module ne touche ni au DOM ni au réseau : il convertit et il valide. C'est ce qui permet
// de le tester, et surtout de refuser un fichier **avant** d'avoir créé quoi que ce soit côté
// serveur. Un chantier à moitié chargé a l'air correct et ne l'est pas.

import { estLatitude, estLongitude } from "./geo.js";

export const FORMAT = "lsim-chantier";
export const VERSION = 1;

// Mêmes bornes et mêmes motifs que `study_contract.py`. Reprises ici volontairement : refuser
// dans le studio un fichier que le serveur accepterait serait pire que l'inverse, et accepter
// un fichier qu'il refuserait donnerait une erreur incompréhensible à la fin du chargement.
export const MAX_EQUIPEMENTS = 64;
const MOTIF_ID = /^[a-z][a-z0-9-]{0,31}$/;
// Même motif que le serveur (`TERRAIN_ID_PATTERN`) : un identifiant accepté ici et
// refusé là-bas donnerait une erreur au moment du run, trop tard pour être comprise.
const MOTIF_TERRAIN = /^[a-z0-9_-]{1,64}$/;
const TYPES = ["sensor", "relay", "border", "server"];
const REGIONS = ["EU868", "US915", "AU915", "AS923", "KR920", "IN865", "RU864"];

/** Levée quand un fichier n'est pas un chantier exploitable. Le message est affiché tel quel. */
export class ChantierInvalide extends Error {
  constructor(message) {
    super(message);
    this.name = "ChantierInvalide";
  }
}

// --- Écriture --------------------------------------------------------------------------------

/**
 * Chantier sérialisable, depuis la topologie renvoyée par le serveur.
 *
 * `origine` peut être `null` : un chantier construit sans point géographique reste chargeable,
 * on ne perd pas les équipements parce qu'on n'a pas encore choisi la zone.
 */
export function serialiserChantier({ topo, origine = null }) {
  const etats = new Map((topo?.states ?? []).map((s) => [s.node_id, s]));
  const equipements = (topo?.nodes ?? []).map((n) => {
    const etat = etats.get(n.id);
    const eq = {
      id: n.id,
      kind: n.kind,
      name: n.name,
      x_m: n.x_m,
      y_m: n.y_m,
    };
    // `keys` n'est délibérément **pas** copié : il ne vaut de toute façon que « ****** », et un
    // fichier qui s'échange ne doit pas contenir de secret, même masqué.
    if (n.sensor) eq.sensor = nettoyer(n.sensor);
    if (etat?.gateway) eq.gateway = nettoyer(etat.gateway);
    if (etat && etat.hostname && etat.hostname !== n.id) eq.hostname = etat.hostname;
    return eq;
  });
  return {
    format: FORMAT,
    version: VERSION,
    origine: origine ? { lat: origine.lat, lon: origine.lon } : null,
    terrain_id: topo?.terrain_id ?? null,
    equipements,
  };
}

/** Copie sans les clés à `null` : un fichier se lit, il ne doit pas être encombré de vide. */
function nettoyer(objet) {
  const out = {};
  for (const [cle, valeur] of Object.entries(objet)) {
    if (valeur !== null && valeur !== undefined) out[cle] = valeur;
  }
  return out;
}

// --- Lecture ---------------------------------------------------------------------------------

/** Lit un chantier depuis le texte d'un fichier. Lève `ChantierInvalide` avec un message clair. */
export function lireChantier(texte) {
  let brut;
  try {
    brut = JSON.parse(texte);
  } catch {
    throw new ChantierInvalide("le fichier n'est pas du JSON valide");
  }
  if (!brut || typeof brut !== "object" || Array.isArray(brut)) {
    throw new ChantierInvalide("le fichier ne contient pas un chantier");
  }
  // Sans champ `format` du tout, le plus probable est que l'utilisateur a choisi un autre
  // fichier. Dire « format inconnu » laisserait croire que le fichier se réclame de quelque
  // chose ; on ne nomme le format que quand le fichier en revendique un.
  if (typeof brut.format !== "string") {
    throw new ChantierInvalide("le fichier ne contient pas un chantier");
  }
  if (brut.format !== FORMAT) {
    throw new ChantierInvalide(
      `format « ${brut.format} » non reconnu (attendu : ${FORMAT})`);
  }
  if (brut.version !== VERSION) {
    throw new ChantierInvalide(
      `version ${brut.version ?? "inconnue"} : ce studio lit la version ${VERSION}`);
  }
  if (!Array.isArray(brut.equipements)) {
    throw new ChantierInvalide("la liste des équipements est absente");
  }
  if (brut.equipements.length > MAX_EQUIPEMENTS) {
    throw new ChantierInvalide(
      `${brut.equipements.length} équipements : au plus ${MAX_EQUIPEMENTS}`);
  }
  return {
    format: FORMAT,
    version: VERSION,
    origine: lireOrigine(brut.origine),
    terrain_id: lireTerrain(brut.terrain_id),
    equipements: brut.equipements.map(lireEquipement),
  };
}

function lireOrigine(origine) {
  if (origine === null || origine === undefined) return null;
  // `estLatitude` / `estLongitude` bornent en plus de vérifier : 400 n'est pas une latitude,
  // et un chantier ancré à 400° placerait les équipements n'importe où sans rien signaler.
  if (!estLatitude(origine?.lat) || !estLongitude(origine?.lon)) {
    throw new ChantierInvalide(
      `origine géographique illisible (lat ${origine?.lat}, lon ${origine?.lon})`);
  }
  return { lat: origine.lat, lon: origine.lon };
}

/**
 * Le relief est un identifiant du catalogue serveur, pas un chemin : un chantier s'échange,
 * et un fichier ne doit jamais pouvoir désigner un fichier. Chargé sur un serveur qui ne
 * connaît pas ce relief, le chantier est refusé — bruyamment, avant toute création.
 */
function lireTerrain(id) {
  if (id === null || id === undefined) return null;
  if (typeof id !== "string" || !MOTIF_TERRAIN.test(id)) {
    throw new ChantierInvalide(`relief « ${id} » : identifiant invalide`);
  }
  return id;
}

function lireEquipement(eq, rang) {
  const ou = rang !== undefined ? ` équipement nº ${rang + 1}` : "";
  if (!eq || typeof eq !== "object" || Array.isArray(eq)) {
    throw new ChantierInvalide(`équipement${ou} : objet attendu`);
  }
  if (typeof eq.id !== "string" || !MOTIF_ID.test(eq.id)) {
    throw new ChantierInvalide(
      `équipement${ou} : identifiant « ${eq.id ?? "?"} » invalide ` +
      "(lettres minuscules, chiffres et tirets, qui commence par une lettre)");
  }
  if (!TYPES.includes(eq.kind)) {
    throw new ChantierInvalide(
      `« ${eq.id} » : type « ${eq.kind ?? "?"} » inconnu (attendu : ${TYPES.join(", ")})`);
  }
  if (typeof eq.name !== "string" || eq.name.length < 1 || eq.name.length > 64) {
    throw new ChantierInvalide(`« ${eq.id} » : nom vide ou trop long`);
  }
  for (const cle of ["x_m", "y_m"]) {
    if (!Number.isFinite(eq[cle]) || Math.abs(eq[cle]) > 1_000_000) {
      throw new ChantierInvalide(`« ${eq.id} » : ${cle} illisible ou hors bornes`);
    }
  }
  const out = {
    id: eq.id, kind: eq.kind, name: eq.name, x_m: eq.x_m, y_m: eq.y_m,
    sensor: null, gateway: null, hostname: null,
  };
  // Les réglages sont optionnels : un chantier sans réglage reste un chantier valide, on pose
  // l'équipement et c'est tout. Refuser serait punir un fichier écrit à la main.
  if (eq.sensor !== null && eq.sensor !== undefined) {
    if (eq.kind !== "sensor") {
      throw new ChantierInvalide(`« ${eq.id} » : réglages capteur sur un ${eq.kind}`);
    }
    out.sensor = lireCapteur(eq.sensor, eq.id);
  }
  if (eq.gateway !== null && eq.gateway !== undefined) {
    out.gateway = lirePasserelle(eq.gateway, eq.id);
  }
  if (eq.hostname !== null && eq.hostname !== undefined) {
    if (typeof eq.hostname !== "string" || eq.hostname.length < 1 || eq.hostname.length > 64) {
      throw new ChantierInvalide(`« ${eq.id} » : nom d'hôte vide ou trop long`);
    }
    out.hostname = eq.hostname;
  }
  return out;
}

function lireCapteur(s, id) {
  const bornes = {
    spreading_factor: [7, 12], payload_bytes: [0, 255], tx_power_dbm: [-10, 30],
    period_s: [0, 86400], messages: [1, 1000], start_spread_s: [0, 86400],
  };
  const out = {};
  for (const [cle, [min, max]] of Object.entries(bornes)) {
    if (s[cle] === undefined || s[cle] === null) continue;
    if (!Number.isFinite(s[cle]) || s[cle] < min || s[cle] > max) {
      throw new ChantierInvalide(`« ${id} » : ${cle} hors bornes (${min} à ${max})`);
    }
    out[cle] = s[cle];
  }
  // Une période nulle ferait taire le capteur : le moteur l'exclut, le fichier aussi.
  if (out.period_s !== undefined && out.period_s <= 0) {
    throw new ChantierInvalide(`« ${id} » : period_s doit être strictement positif`);
  }
  if (s.region !== undefined && s.region !== null) {
    if (!REGIONS.includes(s.region)) {
      throw new ChantierInvalide(`« ${id} » : région « ${s.region} » inconnue`);
    }
    out.region = s.region;
  }
  if (s.channel_freq_hz !== undefined && s.channel_freq_hz !== null) {
    if (!Number.isFinite(s.channel_freq_hz) ||
        s.channel_freq_hz < 137_000_000 || s.channel_freq_hz > 3_000_000_000) {
      throw new ChantierInvalide(`« ${id} » : fréquence hors bornes`);
    }
    out.channel_freq_hz = s.channel_freq_hz;
  }
  return out;
}

function lirePasserelle(g, id) {
  const out = {};
  if (g.region !== undefined && g.region !== null) {
    if (!REGIONS.includes(g.region)) {
      throw new ChantierInvalide(`« ${id} » : région « ${g.region} » inconnue`);
    }
    out.region = g.region;
  }
  if (g.sub_band !== undefined && g.sub_band !== null) {
    if (!Number.isFinite(g.sub_band) || g.sub_band < 1 || g.sub_band > 8) {
      throw new ChantierInvalide(`« ${id} » : sous-bande doit être entre 1 et 8`);
    }
    out.sub_band = g.sub_band;
  }
  if (g.tx_power_dbm !== undefined && g.tx_power_dbm !== null) {
    if (!Number.isFinite(g.tx_power_dbm) || g.tx_power_dbm < -10 || g.tx_power_dbm > 30) {
      throw new ChantierInvalide(`« ${id} » : puissance hors bornes (-10 à 30 dBm)`);
    }
    out.tx_power_dbm = g.tx_power_dbm;
  }
  if (g.mesh_mode !== undefined && g.mesh_mode !== null) {
    if (typeof g.mesh_mode !== "string") {
      throw new ChantierInvalide(`« ${id} » : mode mesh illisible`);
    }
    out.mesh_mode = g.mesh_mode;
  }
  if (g.mesh_max_hops !== undefined && g.mesh_max_hops !== null) {
    if (!Number.isFinite(g.mesh_max_hops) || g.mesh_max_hops < 1 || g.mesh_max_hops > 8) {
      throw new ChantierInvalide(`« ${id} » : nombre de sauts doit être entre 1 et 8`);
    }
    out.mesh_max_hops = g.mesh_max_hops;
  }
  return out;
}

/**
 * Nom de fichier proposé à l'enregistrement.
 * L'identifiant de session est coupé court : c'est un repère, pas une référence à recopier.
 */
export function nomFichier(sid, date = new Date()) {
  const jj = String(date.getDate()).padStart(2, "0");
  const mm = String(date.getMonth() + 1).padStart(2, "0");
  const aaaa = date.getFullYear();
  const court = (sid ?? "session").slice(0, 8);
  return `chantier-${court}-${aaaa}${mm}${jj}.json`;
}
