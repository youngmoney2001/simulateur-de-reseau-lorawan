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
// Les bornes viennent de `topology.js`, qui est la seule source : les recopier ici, c'était
// accepter qu'un réglage refusé d'un côté soit accepté de l'autre — deux vérités sur une
// limite ne se lisent qu'au moment du run, trop tard pour être comprises.
import { SENSOR_LIMITS, DOWNLINK_LIMITS, DOWNLINK_INTEGER_KEYS, CLASSES_ECOUTE } from "./topology.js";

export const FORMAT = "lsim-chantier";
export const VERSION = 1;

// Mêmes bornes et mêmes motifs que `study_contract.py`. Reprises ici volontairement : refuser
// dans le studio un fichier que le serveur accepterait serait pire que l'inverse, et accepter
// un fichier qu'il refuserait donnerait une erreur incompréhensible à la fin du chargement.
export const MAX_EQUIPEMENTS = 64;
// Obstacles par chantier. Le serveur en accepte 200 par session (MAX_OBSTACLES_ATELIER) ;
// le fichier garde la même borne, pour la même raison : deux vérités sur une limite est une
// erreur qu'on ne lit qu'à la fin.
export const MAX_OBSTACLES = 200;
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
    // Le modèle de passerelle : sans lui, un chantier rouvert perdait le seuil de réception
    // choisi, et le run repartait à la référence sans rien dire.
    if (n.gateway_profile) eq.gateway_profile = n.gateway_profile;
    if (etat?.gateway) eq.gateway = nettoyer(etat.gateway);
    if (etat && etat.hostname && etat.hostname !== n.id) eq.hostname = etat.hostname;
    return eq;
  });
  return {
    format: FORMAT,
    version: VERSION,
    origine: origine ? { lat: origine.lat, lon: origine.lon } : null,
    terrain_id: topo?.terrain_id ?? null,
    // Obstacles, shadowing et hauteurs : ce qui sépare deux équipements que la distance
    // seule ne départagerait pas. Omis si rien n'a été réglé — un fichier se lit.
    ...(environnementACharger(topo?.environment) ?? {}),
    equipements,
  };
}

/**
 * L'environnement radio, ou `null` s'il est vierge.
 *
 * Écrit tel quel : les obstacles ont déjà été validés par le serveur à la pose, les relire
 * ici avec d'autres bornes ferait deux vérités. Seules les clés présentes sont gardées.
 */
function environnementACharger(env) {
  if (!env || typeof env !== "object") return null;
  const obstacles = (env.obstacles ?? []).map((o) => {
    const o2 = { x_min_m: o.x_min_m, y_min_m: o.y_min_m, x_max_m: o.x_max_m,
                 y_max_m: o.y_max_m, height_m: o.height_m };
    // Atténuation saisie ou matériau + épaisseur : jamais les deux, et c'est le serveur
    // qui le refuse à la pose. Le fichier garde la forme qu'il a reçue.
    if (o.material) { o2.material = o.material; o2.thickness_m = o.thickness_m; }
    else o2.attenuation_db = o.attenuation_db;
    return o2;
  });
  // Rien de réglé : on n'écrit rien plutôt qu'un bloc de valeurs par défaut. Un chantier
  // écrit avant cette fonctionnalité reste identique, octet pour octet.
  if (!obstacles.length && !env.shadowing_sigma_db
      && (env.gateway_height_m === undefined || env.gateway_height_m === 15)
      && (env.device_height_m === undefined || env.device_height_m === 1.5)) {
    return null;
  }
  return { environment: {
    shadowing_sigma_db: env.shadowing_sigma_db ?? 0,
    gateway_height_m: env.gateway_height_m ?? 15,
    device_height_m: env.device_height_m ?? 1.5,
    obstacles,
  } };
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
    environment: lireEnvironnement(brut.environment),
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

/**
 * L'environnement radio d'un chantier, ou `null` s'il est absent.
 *
 * Les bornes sont celles du contrat : refuser ici un fichier que le serveur accepterait
 * serait pire que l'inverse, et accepter l'inverse donnerait une erreur à la fin du
 * chargement, quand tout est déjà créé.
 */
export function lireEnvironnement(env) {
  if (env === null || env === undefined) return null;
  if (typeof env !== "object" || Array.isArray(env)) {
    throw new ChantierInvalide("environnement : objet attendu");
  }
  const lireNombre = (cle, min, max) => {
    const v = env[cle];
    if (v === undefined || v === null) return undefined;
    if (!Number.isFinite(v) || v < min || v > max) {
      throw new ChantierInvalide(`environnement : ${cle} hors bornes (${min} à ${max})`);
    }
    return v;
  };
  const out = {
    shadowing_sigma_db: lireNombre("shadowing_sigma_db", 0, 30) ?? 0,
    gateway_height_m: lireNombre("gateway_height_m", 0, 1000) ?? 15,
    device_height_m: lireNombre("device_height_m", 0, 1000) ?? 1.5,
    obstacles: [],
  };
  if (env.obstacles === undefined || env.obstacles === null) return out;
  if (!Array.isArray(env.obstacles)) {
    throw new ChantierInvalide("environnement : obstacles doit être une liste");
  }
  if (env.obstacles.length > MAX_OBSTACLES) {
    throw new ChantierInvalide(`${env.obstacles.length} obstacles : au plus ${MAX_OBSTACLES}`);
  }
  out.obstacles = env.obstacles.map(lireObstacle);
  return out;
}

function lireObstacle(o, rang) {
  const ou = `obstacle nº ${rang + 1}`;
  if (!o || typeof o !== "object" || Array.isArray(o)) {
    throw new ChantierInvalide(`${ou} : objet attendu`);
  }
  for (const cle of ["x_min_m", "y_min_m", "x_max_m", "y_max_m"]) {
    if (!Number.isFinite(o[cle])) throw new ChantierInvalide(`${ou} : ${cle} illisible`);
  }
  if (!(o.x_min_m < o.x_max_m) || !(o.y_min_m < o.y_max_m)) {
    throw new ChantierInvalide(`${ou} : emprise vide (min doit être < max)`);
  }
  if (!Number.isFinite(o.height_m) || o.height_m <= 0 || o.height_m > 1000) {
    throw new ChantierInvalide(`${ou} : hauteur hors bornes (0 à 1000 m)`);
  }
  const out = { x_min_m: o.x_min_m, y_min_m: o.y_min_m, x_max_m: o.x_max_m,
                y_max_m: o.y_max_m, height_m: o.height_m };
  if (o.material !== undefined && o.material !== null) {
    // Matériau et épaisseur vont ensemble, et excluent l'atténuation saisie : mêmes règles
    // que le contrat, pour que le fichier ne puisse pas porter un mur que le serveur refuse.
    if (!Number.isFinite(o.thickness_m) || o.thickness_m <= 0 || o.thickness_m > 10) {
      throw new ChantierInvalide(`${ou} : épaisseur hors bornes (0 à 10 m)`);
    }
    if (o.attenuation_db !== undefined && o.attenuation_db !== null) {
      throw new ChantierInvalide(`${ou} : atténuation et matériau s'excluent`);
    }
    out.material = o.material;
    out.thickness_m = o.thickness_m;
    return out;
  }
  if (!Number.isFinite(o.attenuation_db) || o.attenuation_db < 0 || o.attenuation_db > 200) {
    throw new ChantierInvalide(`${ou} : atténuation hors bornes (0 à 200 dB)`);
  }
  out.attenuation_db = o.attenuation_db;
  return out;
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
    sensor: null, gateway: null, hostname: null, gateway_profile: null,
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
  // Le modèle de la passerelle : choix de matériel, comme le profil d'énergie d'un capteur.
  // Non borné ici — le serveur connaît la liste, et un nom inconnu est refusé par lui, avec
  // la liste des modèles admis. Le recopier ici le laisserait dériver des fiches.
  if (eq.gateway_profile !== null && eq.gateway_profile !== undefined) {
    if (typeof eq.gateway_profile !== "string" || !eq.gateway_profile) {
      throw new ChantierInvalide(`« ${eq.id} » : modèle de passerelle illisible`);
    }
    if (eq.kind !== "border" && eq.kind !== "relay") {
      throw new ChantierInvalide(`« ${eq.id} » : modèle de passerelle sur un ${eq.kind}`);
    }
    out.gateway_profile = eq.gateway_profile;
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
  const out = {};
  for (const [cle, [min, max]] of Object.entries(SENSOR_LIMITS)) {
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
  // Classe d'écoute et descentes : sans ces deux lectures, un chantier enregistré en classe B
  // avec une commande réseau se rouvrait en classe A sans rien dire — le réglage disparaissait
  // au lieu d'être refusé, ce qui est la pire des deux issues.
  if (s.device_class !== undefined && s.device_class !== null) {
    if (!CLASSES_ECOUTE.includes(s.device_class)) {
      throw new ChantierInvalide(`« ${id} » : classe d'écoute « ${s.device_class} » inconnue`);
    }
    out.device_class = s.device_class;
  }
  if (s.downlink !== undefined && s.downlink !== null) {
    out.downlink = lireDescente(s.downlink, id);
  }
  return out;
}

/** Descentes réseau d'un chantier. `null` et champ absent y sont la même chose : pas de commande. */
function lireDescente(dl, id) {
  if (typeof dl !== "object" || Array.isArray(dl)) {
    throw new ChantierInvalide(`« ${id} » : réglage de descente illisible`);
  }
  const out = {};
  for (const [cle, [min, max]] of Object.entries(DOWNLINK_LIMITS)) {
    if (dl[cle] === undefined || dl[cle] === null) continue;
    const v = Number(dl[cle]);
    if (!Number.isFinite(v) || v < min || v > max) {
      throw new ChantierInvalide(`« ${id} » : ${cle} hors bornes (${min} à ${max})`);
    }
    // Un nombre de commandes se compte : 2,5 commandes ne veut rien dire, et le serveur
    // répondrait 422 au run, pas à l'ouverture du fichier.
    if (DOWNLINK_INTEGER_KEYS.has(cle) && !Number.isInteger(v)) {
      throw new ChantierInvalide(`« ${id} » : ${cle} doit être un nombre entier`);
    }
    out[cle] = v;
  }
  if (dl.clock_drift_ppm !== undefined && dl.clock_drift_ppm !== null) {
    const v = Number(dl.clock_drift_ppm);
    if (!Number.isFinite(v)) {
      throw new ChantierInvalide(`« ${id} » : dérive d'horloge illisible`);
    }
    out.clock_drift_ppm = v;
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
