// Contrôleur du studio : câble les modules purs (api, topology, console, results) au DOM.
// Tout texte venant du serveur passe par textContent : aucune donnée n'est interprétée comme HTML.
import { createClient, ApiError } from "./api.js";
import {
  KIND_LABEL, CLI_KINDS, REGIONS, SENSOR_LIMITS, planBounds, toScreen, toMeters, gridStep,
  validateNewNode, validateNewNodeGeo, validateSensor, sensorFormFrom, nodeCaption,
  validateGateway, REGIONS_A_SOUS_BANDE, SOUS_BANDES, BANDES_MESH_KHZ,
  GATEWAY_LIMITS, AVANCE_EN_CLI, adrMessage, adrStatut, modelesAdmis, aideModele,
  CLASSES_ECOUTE, CLASSE_DEFAUT, DOWNLINK_LIMITS, CLASSE_A_PERIODICITE,
  attenteAttendue, classeBPlusLenteQueA,
} from "./topology.js";
import { protocoleMessage, protocoleStatut } from "./topology.js";
import { createHistory, promptText } from "./console.js";
import { gatewayRows, scoreLine, criteriaRows, formatPercent, frameRows, formatSecondes } from "./results.js";
import { indicateursReseau, ventilationGroupes, ventilationTable, fenetreObservationNs,
  resultatsParNoeud, echellePdr, lignesResultat,
  limitesParGroupe, fenetreVerdictTexte, texteFenetreACouvrir, messagesPourFenetre,
  autonomieAns, autonomieTexte, entier,
  bilanAdr, bilanProtocole, planCanaux } from "./metrics.js";
import { collectPages, deviceGroupsFromRows, segmentsFromEvents, segmentsDescentes } from "./animation.js";
import { createPlayer } from "./player.js";
// `toMeters` existe déjà dans topology.js (écran -> mètres) : on préfixe pour éviter
// toute confusion entre les deux conversions.
import { createMap3D, toMeters as degreesToMeters, toLonLat as metresVersDegres }
  from "./map3d.js";
// Conversion et lecture des coordonnées, sans dépendance : mêmes fonctions que la carte.
import { lireCoordonnees, formaterCoordonnees, distanceM } from "./geo.js";
import { drawDevice, DEVICE_SPECS } from "./device-art.js";
import { liaisonsObservees, etiquetteLiaison } from "./liaisons.js";
import { ChantierInvalide, lireChantier, nomFichier, serialiserChantier } from "./chantier.js";
// Zone de couverture : les rayons viennent du moteur, le tracé est un calcul pur, vérifiable
// hors navigateur. Le plan 2D et la carte 3D consomment le même, comme pour les liaisons.
import { COULEURS_QUALITE, anneauZone, etiquettePalier, etiquetteModele, porteeMax,
  bilanZone, etiquetteAntenne, porteeTexte }
  from "./zone.js";

const W = 800, H = 520, RUN_POLL_MS = 500, RUN_TIMEOUT_MS = 120_000;
// Borne des lignes de dispositifs ramenées pour les indicateurs : au-delà, l'agrégation par
// groupe cesse d'être lisible et le parcours cesse d'être instantané.
const MAX_METRIC_DEVICES = 20_000;
const SVG_NS = "http://www.w3.org/2000/svg";
const $ = (id) => document.getElementById(id);

const state = {
  client: null,
  sessions: [],
  sid: null,
  topo: null,
  selected: null,
  exercises: [],
  consoles: {},      // node_id -> { text, prompt, history }
  hints: {},         // exercise_id -> [HintOut]  (affichage seulement ; le serveur fait foi)
  result: null,      // dernière notation
  drag: null,
  busy: false,
  choixZone: false,  // le prochain clic sur la carte déplacera l'ancre de la zone
  events: [],        // evenements du run courant (inspecteur de trames)
  runId: null,       // dernier run reussi : la carte 3D situe ce resultat, pas un exemple
  deviceRows: [],    // lignes par dispositif du dernier run : matiere des indicateurs
  resultats: null,   // Map node_id -> resultat : la carte colore par la, plus par type
  couverture: null,  // zones de couverture du serveur : les rayons viennent du moteur
  reliefCle: null,   // "sid|lat|lon" du MNT deja charge : evite de le redemander a chaque sync
  couvertureCle: null, // meme idee pour les zones : la cle porte ce qui change une zone
  fenetreNs: null,   // fenetre d observation du dernier run : denominators des taux
  liens: [],         // GatewayLink[] du dernier run : equipement <-> passerelle du run
  passerelles: null, // summary.gateways : d'ou viennent les liaisons mesh observees
  rxMatrix: null,      // receptions par (dispositif, passerelle) : seule source des liaisons radio
  liaisonsObservees: [], // calculees une seule fois : le plan et la carte tracent la meme chose
  modelesMateriel: [],   // lus au moteur : les libelles viennent de lui, jamais recopies
  defautMateriel: "",    // le materiel du run, annonce par le moteur : « celui du run », dit
  modelesPasserelle: [], // catalogue du moteur : modele, seuil, et ce qu'il sait faire
  materiaux: [],         // catalogue du moteur : perte et caractere extrapole, a 868 MHz
  classesEcoute: [],     // classes d'ecoute : libelles, ouverture et creneaux viennent du moteur
  traceMur: false,       // mode « tracer un mur » : le plan attend un rectangle
  map: null,         // carte 3D, creee au premier affichage : Cesium est volumineux
  mapFailed: false,  // WebGL refuse : on ne retente pas et le plan 2D prend le relais
  courantMoyenUA: null, // dernier run : le seul terme de l'autonomie que le moteur mesure
  courantMinUA: null,   // bornes du meme run : une moyenne ne decrit personne si elles divergent
  courantMaxUA: null,
  capaciteMAh: null,    // l'autre terme est enonce par l'utilisateur, jamais devine ici
  terrains: [],         // catalogue du serveur : vide la plupart du temps, et c'est un fait
  terrainCharge: false, // le catalogue n'est demande qu'une fois, pas a chaque session
  mapError: null,    // raison du repli, affichée : un repli muet cacherait un défaut
  view: "map",      // vue courante : carte 3D (defaut) ou plan 2D
};

// --- DOM helpers ---------------------------------------------------------------------------
function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (v === undefined || v === null || v === false) continue;   // attribut absent, pas « undefined »
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const c of children) node.append(c);
  return node;
}
function svgEl(tag, attrs = {}) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, String(v));
  return node;
}
function clear(node) {
  node.replaceChildren();
}

function showError(err) {
  const text = err instanceof ApiError
    ? `${err.message} (${err.code})`
    : `Erreur : ${err?.message || err}`;
  // L'écran de lancement recouvre l'application : l'erreur doit y être visible aussi.
  const launch = $("launch"), launchErr = $("launch-error");
  if (launch && !launch.hidden && launchErr) {
    launchErr.textContent = text;
    launchErr.hidden = false;
  }
  const box = $("flash");
  box.textContent = text;
  box.hidden = false;
  clearTimeout(showError.timer);
  showError.timer = setTimeout(() => { box.hidden = true; }, 8000);
}

async function guard(action) {
  try {
    return await action();
  } catch (err) {
    showError(err);
    return undefined;
  }
}

// --- Sessions ------------------------------------------------------------------------------
async function connect() {
  const token = $("token").value.trim();
  if (!token) return showError(new Error("saisissez votre jeton"));
  sessionStorage.setItem("lsim-token", token);
  state.client = createClient({ token });
  const list = await guard(() => state.client.listSessions());
  if (!list) return;
  state.sessions = list.items;
  const exercises = await guard(() => state.client.exercises());
  if (exercises) {
    state.exercises = exercises.items;
    renderExerciseChoices();
  }
  // Les modèles de matériel se lisent au moteur : leurs libellés sont les siens, et les
  // recopier ici les laisserait dériver du matériel réellement modélisé. Liste vide si la
  // lecture échoue, et le réglage n'est alors pas proposé — plutôt rien qu'un faux choix.
  const modeles = await guard(() => state.client.energyProfiles());
  if (modeles) state.modelesMateriel = modeles.profiles ?? [];
  // Le matériel du run, annoncé par le moteur. L'écrire ici le recopierait, et il cesserait
  // de suivre le moteur le jour où celui-ci en change. Vide si la réponse ne le porte pas
  // (moteur plus ancien) : l'aide ne s'affiche pas, plutôt que d'afficher une devinette.
  if (modeles) state.defautMateriel = modeles.default ?? "";
  const passerelles = await guard(() => state.client.gatewayProfiles());
  if (passerelles) state.modelesPasserelle = passerelles.profiles ?? [];
  // Les matériaux se lisent à la fréquence de la bande : la perte dépend de la fréquence, et
  // son caractère extrapolé aussi. EU868 par défaut — c'est le plan de la plupart des runs.
  const materiaux = await guard(() => state.client.materials(868.1e6, 0.2));
  if (materiaux) state.materiaux = materiaux.materials ?? [];
  // Classes d'écoute : les intervalles entre créneaux de la classe B viennent du moteur, donc
  // l'interface ne peut pas annoncer une attente qu'il ne tiendrait pas.
  const classes = await guard(() => state.client.deviceClasses());
  if (classes) state.classesEcoute = classes.classes ?? [];
  // La palette et le formulaire d'ajout sont dessinés au chargement, avant que le moteur
  // ait répondu : ils se redessinent donc ici, sinon les capteurs resteraient un modèle
  // générique alors que le moteur en déclare deux.
  renderPalette();
  renderMaterielAjout();
  renderModeleAjout();
  renderSessionChoices();
  if (state.sessions.length) await selectSession(state.sessions[0].session_id);
  else await newSession(null);
  closeLaunch();
  setStatus(state.sessions.length ? "Session chargée" : "Nouvelle session");
  // Après la session : le sélecteur de relief a besoin de la topologie pour se positionner.
  await chargerTerrains();
}

function renderSessionChoices() {
  const select = $("session-select");
  clear(select);
  for (const s of state.sessions) {
    const label = `${s.session_id.slice(0, 8)} · ${s.nodes} équip.${s.exercise_id ? " · " + s.exercise_id : ""}`;
    select.append(el("option", { value: s.session_id, text: label, selected: s.session_id === state.sid ? "selected" : undefined }));
  }
}

function renderExerciseChoices() {
  const select = $("exercise-start");
  clear(select);
  for (const ex of state.exercises) select.append(el("option", { value: ex.id, text: `${ex.title} (${ex.max_points} pts)` }));
}

async function newSession(exerciseId) {
  const body = exerciseId ? { exercise_id: exerciseId, nodes: [] } : { nodes: [] };
  const created = await guard(() => state.client.createSession(body));
  if (!created) return;
  state.result = null;
  await refreshSessions();
  await selectSession(created.session_id);
}

// --- Chantier : enregistrer et ouvrir -------------------------------------------------------
//
// L'équivalent du `.pkt`. Un chantier n'est pas un résultat de simulation : un run se relance,
// un chantier se reprend. C'est ce qui permet de dire « voici le fichier, corrigez-le ».

async function sauvegarderChantier() {
  if (!state.sid) return showError(new Error("aucune session à enregistrer"));
  const chantier = serialiserChantier({ topo: state.topo, origine: readOrigin() });
  if (!chantier.equipements.length) {
    setStatus("Rien à enregistrer : cette session n'a aucun équipement");
    return;
  }
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(chantier, null, 2)], { type: "application/json" }));
  const lien = el("a", { href: url, download: nomFichier(state.sid) });
  document.body.append(lien);
  lien.click();
  lien.remove();
  // Révoquer tout de suite peut annuler le téléchargement : on laisse le tour de boucle.
  setTimeout(() => URL.revokeObjectURL(url), 0);
  const manque = chantier.origine ? "" : " (sans zone géographique)";
  setStatus(`Chantier enregistré : ${chantier.equipements.length} équipement(s)${manque}`);
}

async function chargerChantier(fichier) {
  const texte = await fichier.text().catch(() => null);
  if (texte === null) return showError(new Error(`fichier « ${fichier.name} » illisible`));
  // La validation passe avant toute création. Un chantier refusé coûte un message ; un
  // chantier à moitié chargé a l'air correct et ne l'est pas.
  let chantier;
  try {
    chantier = lireChantier(texte);
  } catch (err) {
    if (err instanceof ChantierInvalide) {
      showError(new Error(`« ${fichier.name} » : ${err.message}`));
      return;
    }
    throw err;
  }
  if (!chantier.equipements.length) {
    setStatus(`« ${fichier.name} » ne contient aucun équipement`);
    return;
  }
  // Les positions et les réglages capteur partent dans la création : un seul appel, donc un
  // seul moment où la session peut être refusée.
  const noeuds = chantier.equipements.map((eq) => ({
    id: eq.id, kind: eq.kind, name: eq.name, x_m: eq.x_m, y_m: eq.y_m,
    ...(eq.sensor ? { sensor: eq.sensor } : {}),
    // Le modèle de la passerelle : posé à la création, faute de quoi le chantier rouvert
    // repartait au seuil de référence sans rien dire.
    ...(eq.gateway_profile ? { gateway_profile: eq.gateway_profile } : {}),
  }));
  const created = await guard(() => state.client.createSession({ nodes: noeuds }));
  if (!created) return;
  state.result = null;
  // Les réglages passerelle passent par le même point d'écriture que la fenêtre de
  // configuration : le fichier n'a pas son propre chemin vers le serveur.
  for (const eq of chantier.equipements) {
    if (!eq.gateway) continue;
    const ok = await guard(() => state.client.setGateway(created.session_id, eq.id, eq.gateway));
    if (!ok) break;
  }
  // Le relief vient du fichier, mais c'est le serveur qui décide s'il le connaît. Un chantier
  // écrit ailleurs peut nommer un relief absent d'ici : on le signale au lieu de le taire,
  // sinon le chantier semblerait ouvert alors qu'il tournera sans relief.
  if (chantier.terrain_id) {
    const connu = state.terrains.some((t) => t.id === chantier.terrain_id);
    if (!connu) {
      setStatus(`Chantier ouvert sans relief : « ${chantier.terrain_id} » est inconnu de ce `
        + `serveur. Les équipements et la zone sont en place.`);
    } else {
      const t = await guard(() => state.client.setTerrain(created.session_id,
        chantier.terrain_id));
      if (t) state.topo = t;
    }
  }
  // L'environnement radio — obstacles, shadowing, hauteurs — vient du fichier, et le serveur
  // le valide comme le reste : un mur hors bornes est signalé, pas absorbé.
  if (chantier.environment) {
    const e = await guard(() => state.client.setEnvironment(
      created.session_id, chantier.environment));
    if (e) state.topo = e;
  }
  // La zone s'écrit avant de sélectionner la session, pas après : sinon la carte s'affiche
  // d'abord à l'ancre du chantier précédent, puis saute. Le saut est invisible sur un plan en
  // mètres, mais pas sur la carte 3D — et un saut qu'on voit ressemble à une hésitation.
  if (chantier.origine) writeOrigin(chantier.origine);
  await refreshSessions();
  await selectSession(created.session_id);
  setStatus(`Chantier ouvert : ${chantier.equipements.length} équipement(s), session neuve`);
  await restaurerNomsHotes(created.session_id, chantier.equipements);
}

/**
 * Le nom d'hôte vaut l'identifiant par défaut (`new_session`) : rien à faire dans le cas
 * courant. On ne joue les trois commandes du CLI que pour un équipement réellement renommé,
 * et un échec est signalé au lieu d'être avalé — sinon le chantier reviendrait rebaptisé
 * sans que rien ne le dise.
 */
async function restaurerNomsHotes(sid, equipements) {
  const renommes = equipements.filter((eq) => eq.hostname && eq.hostname !== eq.id);
  if (!renommes.length) return;
  const rates = [];
  for (const eq of renommes) {
    let ok = true;
    for (const commande of ["enable", "configure terminal", `hostname ${eq.hostname}`]) {
      const res = await guard(() => state.client.cli(sid, eq.id, commande));
      if (!res || res.error) { ok = false; break; }
    }
    if (!ok) rates.push(eq.id);
  }
  if (rates.length) {
    setStatus(`Chantier ouvert, mais nom d'hôte non restauré sur : ${rates.join(", ")}`);
  }
}

async function refreshSessions() {
  const list = await guard(() => state.client.listSessions());
  if (list) state.sessions = list.items;
  renderSessionChoices();
}

async function selectSession(sid) {
  state.sid = sid;
  state.selected = null;
  state.result = null;
  state.consoles = {};
  // Les liaisons observees appartiennent au run d'une session : les garder en changeant de
  // session afficherait le reseau d'un autre chantier, le temps d'un clic.
  state.liens = [];
  state.passerelles = null;
  state.rxMatrix = null;
  state.liaisonsObservees = [];
  // Le relief et les zones appartiennent à une session et à une ancre : les garder en
  // changeant de chantier afficherait la colline d'un autre, le temps d'un clic.
  state.couverture = null;
  state.couvertureCle = null;
  state.reliefCle = null;
  renderAdr();
  renderProtocole();
  renderSessionChoices();
  await loadTopology();
  const meta = state.sessions.find((s) => s.session_id === sid);
  $("session-meta").textContent = meta?.exercise_id ? `Exercice : ${meta.exercise_id}` : "Session libre";
  renderExercise();
  renderSimulationIdle();
}

async function deleteSession() {
  if (!state.sid || !window.confirm("Supprimer cette session et son journal ?")) return;
  const done = await guard(() => state.client.deleteSession(state.sid));
  if (done === undefined) return;
  state.sid = null;
  state.topo = null;
  await refreshSessions();
  if (state.sessions.length) await selectSession(state.sessions[0].session_id);
  else {
    refreshViews();
    renderDevice();
  }
}

// --- Plan ----------------------------------------------------------------------------------
async function loadTopology() {
  if (!state.sid) return;
  const topo = await guard(() => state.client.topology(state.sid));
  if (topo) state.topo = topo;
  renderTerrains();
  renderAdr();
  renderProtocole();
  refreshViews();
  renderDevice();
}

function stateOf(nodeId) {
  return state.topo?.states.find((s) => s.node_id === nodeId);
}

// Grille graduée : repère visuel et échelle en mètres. Sans elle, le plan n'est qu'un
// vide blanc où l'on ne peut juger ni les distances ni les positions relatives.
function renderGrid(bounds) {
  const g = svgEl("g", { class: "grid" });
  const span = Math.max(bounds.maxX - bounds.minX, bounds.maxY - bounds.minY);
  const step = gridStep(span);
  const premier = (v) => Math.ceil(v / step) * step;
  for (let x = premier(bounds.minX); x <= bounds.maxX; x += step) {
    const sx = toScreen({ x_m: x, y_m: 0 }, bounds, W, H).x;
    g.append(svgEl("line", { x1: sx.toFixed(1), y1: 0, x2: sx.toFixed(1), y2: H, class: "grid-line" }));
    const t = svgEl("text", { x: (sx + 3).toFixed(1), y: 12, class: "grid-label" });
    t.textContent = `${Math.round(x)} m`;
    g.append(t);
  }
  for (let y = premier(bounds.minY); y <= bounds.maxY; y += step) {
    const sy = toScreen({ x_m: 0, y_m: y }, bounds, W, H).y;
    g.append(svgEl("line", { x1: 0, y1: sy.toFixed(1), x2: W, y2: sy.toFixed(1), class: "grid-line" }));
    const t = svgEl("text", { x: 3, y: (sy - 3).toFixed(1), class: "grid-label" });
    t.textContent = `${Math.round(y)} m`;
    g.append(t);
  }
  return g;
}

// Marque intérieure : distingue les types au premier coup d'œil, sans dépendre de la couleur.
function nodeIcon(kind) {
  if (kind === "sensor") {
    return svgEl("circle", { r: 5, class: "icon" });
  }
  if (kind === "server") {
    return svgEl("rect", { x: -6, y: -6, width: 12, height: 12, class: "icon" });
  }
  // Passerelle ou frontière : antenne, trois barres de portée.
  const g = svgEl("g", { class: "icon-stroke" });
  g.append(svgEl("path", { d: "M 0 8 L 0 -6" }));
  g.append(svgEl("path", { d: "M -7 -1 A 9 9 0 0 1 7 -1" }));
  g.append(svgEl("path", { d: "M -12 5 A 15 15 0 0 1 12 5" }));
  return g;
}

// Rafraîchit les deux vues. Un seul point de passage : la carte et le plan montrent les
// mêmes équipements, ils ne peuvent donc pas être mis à jour séparément.
function refreshViews() {
  renderPlan();
  syncMap();
  majHistorique();
}

/**
 * Les boutons Annuler et Rétablir, depuis ce que la topologie dit de l'historique.
 *
 * Le serveur porte l'historique, et chaque réponse le résume : les boutons se mettent donc
 * à jour **après chaque opération**, et pas seulement après un annuler. Grisés avec leur
 * raison — « Rien à annuler » — plutôt que muets : un bouton désactivé sans explication
 * passe pour un bogue.
 *
 * Le libellé nomme l'opération (« annuler le déplacement de capteur-1 »). C'est ce qui
 * rend le geste sûr : on annule en sachant quoi.
 */
function majHistorique() {
  const annuler = $("undo");
  const retablir = $("redo");
  const peutAnnuler = Boolean(state.topo?.can_undo);
  const peutRetablir = Boolean(state.topo?.can_redo);
  if (annuler) {
    annuler.disabled = !peutAnnuler;
    annuler.title = peutAnnuler
      ? `Annuler : ${state.topo.undo_label} (Ctrl+Z)` : "Rien à annuler";
  }
  if (retablir) {
    retablir.disabled = !peutRetablir;
    retablir.title = peutRetablir
      ? `Rétablir : ${state.topo.redo_label} (Ctrl+Maj+Z)` : "Rien à rétablir";
  }
}

/**
 * Un annuler ou un rétablir.
 *
 * Toute la vue est rafraîchie, y compris les fenêtres d'équipement ouvertes : annuler une
 * commande `region US915` dans la console doit se voir dans la case « Région » de la
 * fenêtre, sinon l'interface continuerait d'afficher un état que le serveur a quitté.
 */
async function annulerOuRetablir(sens) {
  if (!state.sid) return;
  if (sens === "undo" && !state.topo?.can_undo) return;
  if (sens === "redo" && !state.topo?.can_redo) return;
  const topo = await guard(() => (sens === "undo"
    ? state.client.undo(state.sid) : state.client.redo(state.sid)));
  if (!topo) return;
  state.topo = topo;
  // Le résultat affiché a été calculé sur un réseau qui vient de changer : le garder
  // colorerait le plan avec des chiffres qui ne sont plus ceux d'aucun run de cette
  // topologie. On le retire, comme à l'ouverture d'un autre chantier.
  state.result = null;
  state.resultats = null;
  // Le résumé est celui d'un run calculé sur un autre réseau : le garder ferait dire au
  // serveur ce qu'il a vu d'un chantier qui n'existe plus.
  state.resume = null;
  state.rxMatrix = null;
  state.liens = [];
  state.passerelles = null;
  state.liaisonsObservees = [];
  // La session peut avoir perdu l'équipement que la fenêtre montrait : on la ferme plutôt
  // que de la laisser afficher un fantôme.
  for (const id of [...deviceWindows.keys()]) {
    if (!topo.nodes.some((n) => n.id === id)) closeDeviceWindow(id);
  }
  refreshTopologie();
  renderTerrains();
  renderDevice();
  // Le geste qu'on vient de faire est passé dans l'autre pile : après un annuler, c'est le
  // prochain rétablir qui le nomme, et l'inverse. Lire `undo_label` ici annoncerait
  // l'opération **suivante**, celle qu'on n'a pas encore annulée.
  const libelle = sens === "undo" ? topo.redo_label : topo.undo_label;
  setStatus(sens === "undo"
    ? (libelle ? `Annulé : ${libelle}` : "Annulé")
    : (libelle ? `Rétabli : ${libelle}` : "Rétabli"));
}

/**
 * Une topologie revenue du serveur : le plan **et** les réglages qu'elle conditionne.
 *
 * L'ADR et la jointure se lisent depuis `state.topo`. Ajouter une passerelle rend l'ADR
 * possible ; poser un relais le rend impossible ; régler une région sur la passerelle lève
 * le dernier obstacle. Ne rafraîchir que le plan laissait donc un réglage grisé **avec une
 * raison qui n'était plus la sienne** — mesuré dans le navigateur par l'étape ADR : après
 * l'ajout de la passerelle, l'atelier annonçait encore « 0 passerelles actives ici » alors
 * que le serveur répondait déjà « exige un plan régional ».
 *
 * Un réglage grisé sans explication coûte une heure ; un réglage grisé avec la mauvaise
 * explication en coûte davantage, parce qu'on cherche la passerelle manquante au lieu de
 * régler la région.
 */
function refreshTopologie() {
  refreshViews();
  renderAdr();
  renderProtocole();
  // Les obstacles vivent dans la topologie : le plan les dessine au même titre que les
  // équipements, et leur liste se relit après chaque retour du serveur.
  renderEnvironnement();
}

// --- Obstacles : les tracer sur le plan, les lister, dire ce qu'ils coutent -------------------

/**
 * L'environnement radio de la session, sous forme d'un objet toujours complet.
 *
 * Le serveur renvoie des valeurs par défaut quand rien n'a été réglé ; les traiter comme
 * « réglé » afficherait un shadowing de 0 dB que l'utilisateur croirait avoir choisi.
 */
function environnement() {
  const e = state.topo?.environment ?? {};
  return {
    shadowing_sigma_db: e.shadowing_sigma_db ?? 0,
    gateway_height_m: e.gateway_height_m ?? 15,
    device_height_m: e.device_height_m ?? 1.5,
    obstacles: e.obstacles ?? [],
    material_calibration: e.material_calibration ?? {},
  };
}

/** Ce qu'un obstacle coûte, en mots. Le matériau n'est pas une perte : il la calcule. */
function coutObstacle(o) {
  if (o.material) {
    const m = state.materiaux.find((x) => x.name === o.material);
    if (!m) return `${o.material}, ${o.thickness_m} m`;
    // La mention « extrapolé » n'est pas un détail : à 868 MHz, 12 des 15 matériaux sortent
    // de la plage documentée de l'UIT-R P.2040-4. Afficher la perte sans le dire la ferait
    // passer pour mesurée.
    return `${o.material} ${o.thickness_m} m — ${m.loss_db.toFixed(1)} dB`
      + (m.extrapolated ? " (hors plage documentée, extrapolé)" : "");
  }
  return `${o.attenuation_db} dB saisis`;
}

function renderObstacles(bounds) {
  const g = svgEl("g", { class: "obstacles" });
  for (const [i, o] of environnement().obstacles.entries()) {
    const a = toScreen({ x_m: o.x_min_m, y_m: o.y_max_m }, bounds, W, H);
    const b = toScreen({ x_m: o.x_max_m, y_m: o.y_min_m }, bounds, W, H);
    g.append(svgEl("rect", {
      class: "obstacle", x: Math.min(a.x, b.x).toFixed(1), y: Math.min(a.y, b.y).toFixed(1),
      width: Math.abs(b.x - a.x).toFixed(1), height: Math.abs(b.y - a.y).toFixed(1),
      "data-index": i,
    }));
  }
  return g;
}

function renderObstacleList() {
  const liste = $("obstacle-list");
  if (!liste) return;
  clear(liste);
  const env = environnement();
  if (!env.obstacles.length) {
    liste.append(el("li", { class: "muted",
      text: "Aucun obstacle : les liaisons ne sont atténuées que par la distance." }));
    return;
  }
  env.obstacles.forEach((o, i) => {
    const matiere = el("select", { class: "obstacle-mat" },
      el("option", { value: "", text: "atténuation saisie" }),
      ...state.materiaux.filter((m) => m.name !== "air").map((m) => el("option", {
        value: m.name, text: m.extrapolated ? `${m.name} (extrapolé)` : m.name,
        selected: o.material === m.name ? "selected" : undefined })));
    const epaisseur = el("input", { type: "number", class: "obstacle-ep", min: "0.01",
      max: "10", step: "0.05", value: o.thickness_m ?? 0.2 });
    const attenuation = el("input", { type: "number", class: "obstacle-att", min: "0",
      max: "200", step: "0.5", value: o.attenuation_db ?? 0 });
    // Atténuation saisie ou matériau : jamais les deux. Le sélecteur commande laquelle des
    // deux est visible, faute de quoi le formulaire afficherait un réglage sans effet.
    const bascule = () => {
      const parMatiere = matiere.value !== "";
      attenuation.hidden = parMatiere;
      epaisseur.hidden = !parMatiere;
    };
    matiere.addEventListener("change", bascule);
    bascule();
    const li = el("li", { class: "obstacle-row" },
      el("span", { text: `Mur ${i + 1} — ${coutObstacle(o)}` }),
      el("span", { class: "obstacle-ctrls" },
        matiere, epaisseur, attenuation,
        el("label", {}, "haut", el("input", { type: "number", class: "obstacle-h",
          min: "0.1", max: "1000", step: "0.5", value: o.height_m }), "m"),
        el("button", { type: "button", class: "obstacle-ok", text: "OK",
          onclick: () => modifierObstacle(i, {
            material: matiere.value || null,
            thickness_m: matiere.value ? Number(epaisseur.value) : null,
            attenuation_db: matiere.value ? undefined : Number(attenuation.value),
            height_m: Number(li.querySelector(".obstacle-h").value) }) }),
        el("button", { type: "button", class: "obstacle-del", text: "Retirer",
          onclick: () => supprimerObstacle(i) })));
    liste.append(li);
  });
}

function renderEnvironnement() {
  const env = environnement();
  const sigma = $("sigma"), gw = $("gw-height"), dev = $("dev-height");
  if (sigma && document.activeElement !== sigma) sigma.value = env.shadowing_sigma_db;
  if (gw && document.activeElement !== gw) gw.value = env.gateway_height_m;
  if (dev && document.activeElement !== dev) dev.value = env.device_height_m;
  renderObstacleList();
  renderCalibration();
}

/** Les matériaux posés sur ce chantier, dans l'ordre du catalogue. */
function materiauxPoses() {
  const poses = new Set(environnement().obstacles.map((o) => o.material).filter(Boolean));
  return state.materiaux.filter((m) => m.name !== "air" && poses.has(m.name));
}

/**
 * Une perte mesurée par matériau, à la place de la table P.2040-4.
 *
 * Seuls les matériaux **posés** sont proposés : calibrer un matériau absent des murs
 * n'aurait aucun effet sur ce chantier, et afficher un réglage sans effet est le piège que
 * le formulaire d'obstacle évite déjà entre atténuation et matériau.
 */
function renderCalibration() {
  const liste = $("calib-list");
  if (!liste) return;
  clear(liste);
  const calib = environnement().material_calibration ?? {};
  const poses = materiauxPoses();
  if (!poses.length) {
    liste.append(el("li", { class: "muted",
      text: "Aucun mur avec matériau : tracez un mur et choisissez sa matière." }));
    return;
  }
  for (const m of poses) {
    const mesure = calib[m.name];
    const perte = el("input", { type: "number", class: "calib-db", min: "0", max: "200",
      step: "0.5", value: mesure ? mesure.loss_db_per_m : "" });
    const origine = el("input", { type: "text", class: "calib-prov", maxlength: "200",
      placeholder: "d’où vient cette mesure ?", value: mesure ? mesure.provenance : "" });
    const appliquer = el("button", { type: "button", class: "calib-ok", text: "Appliquer",
      onclick: async () => {
        const db = Number(perte.value);
        if (!Number.isFinite(db) || db < 0 || db > 200) {
          setStatus("perte mesurée : entre 0 et 200 dB/m");
          return;
        }
        if (!origine.value.trim()) {
          // Même règle qu'un relevé d'énergie : un chiffre sans origine se présente comme
          // une donnée du moteur.
          setStatus("provenance obligatoire : d’où vient cette mesure ?");
          return;
        }
        const suivant = { ...calib,
          [m.name]: { loss_db_per_m: db, provenance: origine.value.trim() } };
        await ecrireEnvironnement({ material_calibration: suivant },
          `${m.name} : ${db} dB/m mesurés`);
      } });
    liste.append(el("li", { class: "calib-row" },
      el("span", { text: mesure
        ? `${m.name} — ${mesure.loss_db_per_m} dB/m mesurés (${mesure.provenance})`
        : `${m.name} — table P.2040-4`
          + (m.extrapolated ? `, ${m.loss_db.toFixed(1)} dB extrapolés` : "") }),
      el("span", { class: "calib-ctrls" }, perte, origine, appliquer,
        mesure && el("button", { type: "button", class: "calib-raz", text: "Revenir à la table",
          onclick: async () => {
            const suivant = { ...calib };
            delete suivant[m.name];
            await ecrireEnvironnement({ material_calibration: suivant },
              `${m.name} : retour à la table P.2040-4`);
          } }))));
  }
}

async function ecrireEnvironnement(partiel, message) {
  if (!state.sid) return;
  const topo = await guard(() => state.client.setEnvironment(state.sid, partiel));
  if (!topo) return;
  state.topo = topo;
  renderEnvironnement();
  refreshViews();          // met aussi l'historique à jour
  const ou = $("env-status");
  if (ou) ou.textContent = message;
}

async function modifierObstacle(index, changement) {
  const obstacles = environnement().obstacles.map((o, i) => {
    if (i !== index) return o;
    const n = { ...o, height_m: changement.height_m };
    if (changement.material) {
      n.material = changement.material;
      n.thickness_m = changement.thickness_m;
      delete n.attenuation_db;          // atténuation et matériau s'excluent côté serveur
    } else {
      n.attenuation_db = changement.attenuation_db;
      delete n.material;
      delete n.thickness_m;
    }
    return n;
  });
  await ecrireEnvironnement({ obstacles }, `Mur ${index + 1} modifié`);
}

async function supprimerObstacle(index) {
  const restants = environnement().obstacles.filter((_, i) => i !== index);
  await ecrireEnvironnement({ obstacles: restants },
    restants.length ? `Mur retiré : ${restants.length} restant(s)` : "Mur retiré : plus d'obstacle");
}

/**
 * Le mode « tracer un mur ».
 *
 * Le tracé se fait sur le plan métrique, pas sur la carte : c'est là qu'on règle une
 * distance, et un mur se mesure en mètres. Le rectangle est converti en emprise métrique
 * dès le relâchement — ce que le serveur reçoit, c'est l'emprise, pas des pixels.
 */
function toggleTraceMur(on) {
  state.traceMur = on ?? !state.traceMur;
  const bouton = $("draw-obstacle");
  const aide = $("obstacle-draw-aide");
  if (bouton) {
    bouton.setAttribute("aria-pressed", String(state.traceMur));
    bouton.classList.toggle("active", state.traceMur);
  }
  if (aide) {
    aide.textContent = state.traceMur
      ? "Tirez un rectangle sur le plan, puis relâchez. Échap annule."
      : "";
  }
  if (!state.traceMur) return;
  const plan = $("plan");
  if (!plan) return;
  // Sans équipement, le plan n'a pas de repère métrique : tracer y serait silencieusement
  // faux, l'emprise serait convertie depuis des bornes absentes. La topologie est la source,
  // pas le dessin — un plan non redessiné mentirait.
  if (!(state.topo?.nodes ?? []).length) {
    // Le message se pose **après** la sortie du mode : celle-ci vide l'aide, et l'écrire
    // avant l'effacerait.
    toggleTraceMur(false);
    if (aide) aide.textContent = "Ajoutez des équipements au plan avant de tracer un mur.";
    return;
  }
  const depart = (ev) => {
    if (ev.button !== 0 || !state.traceMur) return;
    if (ev.target.closest(".node")) return;    // un équipement se déplace, il ne trace pas
    const p0 = svgPoint(ev);
    const rect = svgEl("rect", { class: "obstacle-trace", x: p0.x, y: p0.y, width: 0, height: 0 });
    plan.append(rect);
    const bouger = (e) => {
      const p = svgPoint(e);
      rect.setAttribute("x", Math.min(p0.x, p.x).toFixed(1));
      rect.setAttribute("y", Math.min(p0.y, p.y).toFixed(1));
      rect.setAttribute("width", Math.abs(p.x - p0.x).toFixed(1));
      rect.setAttribute("height", Math.abs(p.y - p0.y).toFixed(1));
    };
    const finir = async (e) => {
      plan.removeEventListener("pointermove", bouger);
      plan.removeEventListener("pointerup", finir);
      document.removeEventListener("keydown", annuler);
      rect.remove();
      toggleTraceMur(false);
      const p1 = svgPoint(e);
      if (Math.abs(p1.x - p0.x) < 4 || Math.abs(p1.y - p0.y) < 4) return;   // un clic, pas un mur
      const a = toMeters({ x: Math.min(p0.x, p1.x), y: Math.max(p0.y, p1.y) }, state.bounds, W, H);
      const b = toMeters({ x: Math.max(p0.x, p1.x), y: Math.min(p0.y, p1.y) }, state.bounds, W, H);
      const mur = { x_min_m: a.x_m, y_min_m: b.y_m, x_max_m: b.x_m, y_max_m: a.y_m,
                    height_m: 12, attenuation_db: 6 };
      const obstacles = [...environnement().obstacles, mur];
      await ecrireEnvironnement({ obstacles },
        `Mur ajouté : ${obstacles.length} obstacle(s) — 6 dB saisis par défaut, modifiables ci-dessous`);
    };
    const annuler = (e) => {
      if (e.key !== "Escape") return;
      plan.removeEventListener("pointermove", bouger);
      plan.removeEventListener("pointerup", finir);
      document.removeEventListener("keydown", annuler);
      rect.remove();
      toggleTraceMur(false);
    };
    plan.addEventListener("pointermove", bouger);
    plan.addEventListener("pointerup", finir);
    document.addEventListener("keydown", annuler);
  };
  plan.addEventListener("pointerdown", depart, { once: true });
}

function renderPlan() {
  const svg = $("plan");
  clear(svg);
  const nodes = state.topo?.nodes ?? [];
  $("empty-plan").hidden = nodes.length > 0 || !state.sid;
  // La légende se rend avant la sortie anticipée : elle décrit des zones, et peut donc
  // exister sur un plan qui n'a pas encore d'équipement.
  renderCouvertureLegend();
  if (!nodes.length) return;
  const bounds = planBounds(nodes);
  state.bounds = bounds;
  svg.append(renderGrid(bounds));
  // La couverture se dessine **sous** les murs : c'est le fond du décor, et c'est le mur
  // qui explique pourquoi la zone s'arrête là où elle s'arrête.
  svg.append(renderCouverture(nodes, bounds));
  // Les obstacles se dessinent **sous** les équipements : un mur n'a pas à masquer ce qu'il
  // sépare, et c'est la position des équipements qu'on vient lire.
  svg.append(renderObstacles(bounds));
  // Les liaisons se tracent **sous** les équipements : un trait qui passe par-dessus une
  // icône la masque, et l'icône est ce qu'on vient lire.
  svg.append(renderLiaisons(nodes, bounds));
  for (const n of nodes) {
    const p = toScreen(n, bounds, W, H);
    // Atteignable au clavier : sans tabindex ni rôle, un équipement du plan ne s'ouvrait
    // qu'au pointeur, et la fenêtre d'un équipement restait inaccessible sans souris. Le
    // nœud est un bouton — Envoi ou Espace l'ouvre — et porte un nom lisible, faute de quoi
    // une technologie d'assistance n'annoncerait qu'un « groupe » sans identité.
    const g = svgEl("g", { class: `node${state.selected === n.id ? " selected" : ""}`, "data-id": n.id,
      tabindex: "0", role: "button", "aria-label": `${n.id} — ${KIND_LABEL[n.kind] ?? n.kind}`,
      transform: `translate(${p.x.toFixed(1)} ${p.y.toFixed(1)})` });
    // Équipements agrandis : à l'échelle précédente (9 px de rayon) un capteur était
    // quasiment invisible sur un plan de plus de mille pixels de large.
    const shape = n.kind === "sensor"
      ? svgEl("circle", { r: 15, class: "sensor" })
      : n.kind === "server" ? svgEl("rect", { x: -17, y: -17, width: 34, height: 34, transform: "rotate(45)", class: "server" })
      : svgEl("rect", { x: -18, y: -18, width: 36, height: 36, rx: 5, class: n.kind });
    // Même lecture sur les deux vues : le plan porte la couleur du résultat, comme
    // la carte. Sans résultat, la classe CSS du type continue de décider.
    const couleur = state.resultats?.get(n.id)?.couleur;
    if (couleur) shape.setAttribute("fill", couleur);
    g.append(shape);
    g.append(nodeIcon(n.kind));
    const label = svgEl("text", { x: 24, y: -16 });
    label.textContent = n.name;
    g.append(label);
    g.addEventListener("pointerdown", (ev) => startDrag(ev, n.id));
    svg.append(g);
  }
  player.refresh();   // le rendu du plan supprime la couche d'animation : on la remet
}

// Liaisons observées, calculées une fois : le plan 2D et la carte 3D tracent le même résultat.
/**
 * Les deux natures de liaisons, calculées une seule fois.
 *
 * Le plan et la carte consomment le même tableau : si chacun recalculait, ils pourraient
 * diverger sans que rien ne le signale — et deux vues qui ne disent pas la même chose sont
 * pires qu'une seule.
 *
 * Le calcul lui-même vit dans `liaisons.js`, sans `state` : il est donc vérifiable hors
 * navigateur. Il ne reste ici que l'assemblage des entrées.
 */
function calculerLiaisons() {
  return liaisonsObservees({
    passerelles: state.passerelles ?? [],
    liens: state.liens,
    noeuds: (state.topo?.nodes ?? []).map((n) => n.id),
    rxMatrix: state.rxMatrix,
    deviceRows: state.deviceRows,
  });
}

/**
 * Zones de couverture sur le plan, par palier de qualité.
 *
 * Les rayons sont ceux du moteur — mêmes valeurs que la carte 3D, même repère métrique —
 * si bien qu'une zone ne raconte pas une histoire différente selon la vue. On les projette
 * avec `toScreen`, exactement comme les équipements : pas de conversion propre à la zone,
 * donc pas d'écart possible entre ce que couvre la zone et ce qu'elle couvre.
 */
function renderCouverture(nodes, bounds) {
  const couche = svgEl("g", { class: "couverture" });
  const parId = new Map(nodes.map((n) => [n.id, n]));
  for (const z of state.couverture?.gateways ?? []) {
    const passerelle = parId.get(z.node_id);
    if (!passerelle) continue;         // passerelle inconnue : pas de zone dans le vide
    // Du plus large au plus serré : le meilleur palier reste lisible par-dessus les autres.
    const paliers = [...(z.paliers ?? [])].sort(
      (a, b) => Math.max(...(b.radii_m ?? [0])) - Math.max(...(a.radii_m ?? [0])));
    for (const palier of paliers) {
      const anneau = anneauZone(palier, passerelle);
      if (anneau.length < 4) continue;
      const points = anneau.map((p) => toScreen({ x_m: p.x, y_m: p.y }, bounds, W, H))
        .filter((p) => Number.isFinite(p.x) && Number.isFinite(p.y));
      // Un anneau amputé n'est pas un anneau : le tracé serait une zone fausse.
      if (points.length !== anneau.length) continue;
      const teinte = COULEURS_QUALITE[palier.qualite] ?? "#1f6feb";
      const forme = svgEl("polygon", {
        class: `zone zone-${palier.qualite}`,
        points: points.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" "),
        fill: teinte,
      });
      // Le palier est nommé dans un attribut : la légende et le survol le relisent ici,
      // sans recalculer. Une zone sans son modèle se prendrait pour une mesure, alors
      // qu'elle est un bilan de liaison.
      forme.setAttribute("data-palier", palier.qualite);
      forme.setAttribute("data-modele", z.modele);
      forme.setAttribute("aria-label",
        `${z.node_id} : ${etiquettePalier(palier)} (${etiquetteModele(z.modele)})`);
      couche.append(forme);
    }
  }
  return couche;
}

// Liaisons observées sur le plan. Elles n'existent qu'après un run : la topologie d'un réseau
// radio ne se déclare pas, elle se mesure. Avant le run, le plan ne montre aucun trait — et
// c'est voulu, voir le commentaire de `liaisons.js` sur ce qu'on refuse de tracer.
function renderLiaisons(nodes, bounds) {
  const couche = svgEl("g", { class: "liens" });
  if (!state.passerelles?.length) return couche;
  const liaisons = state.liaisonsObservees ?? [];
  if (!liaisons.length) return couche;
  const parId = new Map(nodes.map((n) => [n.id, n]));
  for (const l of liaisons) {
    const a = parId.get(l.de), b = parId.get(l.vers);
    if (!a || !b) continue;
    const p = toScreen(a, bounds, W, H), q = toScreen(b, bounds, W, H);
    // La classe suit la nature du lien : le plan et la carte doivent raconter la même
    // chose, sinon l'utilisateur lit deux réseaux différents selon la vue.
    couche.append(svgEl("line", { class: `lien lien-${l.genre === "radio" ? "radio" : "mesh"}`,
      x1: p.x.toFixed(1), y1: p.y.toFixed(1), x2: q.x.toFixed(1), y2: q.y.toFixed(1) }));
    // Le chiffre au milieu du trait : une liaison sans son nombre n'apprend rien qu'une
    // couleur ne dirait deja.
    const mx = (p.x + q.x) / 2, my = (p.y + q.y) / 2;
    // L'étiquette prend la teinte du trait qu'elle chiffre : sur un plan où deux natures se
    // croisent, un nombre sans couleur ne dit pas à quel lien il appartient.
    const sens = l.genre === "radio" ? "radio" : "mesh";
    const texte = svgEl("text", { class: `lien-etiquette lien-etiquette-${sens}`,
      x: mx.toFixed(1), y: (my - 5).toFixed(1) });
    texte.textContent = etiquetteLiaison(l);
    couche.append(texte);
  }
  return couche;
}

function svgPoint(ev) {
  const svg = $("plan");
  const rect = svg.getBoundingClientRect();
  return { x: ((ev.clientX - rect.left) / rect.width) * W, y: ((ev.clientY - rect.top) / rect.height) * H };
}

function startDrag(ev, nodeId) {
  if (ev.button !== 0) return;
  state.drag = { nodeId, moved: false, pointerId: ev.pointerId };
  $("plan").setPointerCapture?.(ev.pointerId);
  const onMove = (e) => {
    if (!state.drag) return;
    state.drag.moved = true;
    const p = svgPoint(e);
    const g = $("plan").querySelector(`g[data-id="${CSS.escape(nodeId)}"]`);
    if (g) g.setAttribute("transform", `translate(${p.x.toFixed(1)} ${p.y.toFixed(1)})`);
    state.drag.last = p;
  };
  const onUp = async () => {
    $("plan").removeEventListener("pointermove", onMove);
    $("plan").removeEventListener("pointerup", onUp);
    const drag = state.drag;
    state.drag = null;
    // Pas de déplacement : c'est une sélection. (La capture du pointeur empêche un « click » sur le groupe.)
    if (!drag?.moved) return selectNode(nodeId);
    if (!drag.last) return;
    const pos = toMeters(drag.last, state.bounds, W, H);
    const topo = await guard(() => state.client.moveNode(state.sid, nodeId, pos));
    if (topo) state.topo = topo;
    refreshViews();
    renderDevice();
  };
  $("plan").addEventListener("pointermove", onMove);
  $("plan").addEventListener("pointerup", onUp);
}

function selectNode(nodeId) {
  openDeviceWindow(nodeId);
  refreshViews();
}

// Ouvrir un équipement du plan au clavier. Le nœud est un bouton depuis qu'il porte
// tabindex et role : il doit donc répondre aux touches qui activent un bouton, et à elles
// seules — la barre d'espace fait défiler la page si on la laisse passer.
$("plan").addEventListener("keydown", (ev) => {
  if (ev.key !== "Enter" && ev.key !== " ") return;
  const g = ev.target.closest?.("g.node");
  if (!g) return;
  ev.preventDefault();
  selectNode(g.dataset.id);
});

// --- Fenêtres d'équipement flottantes (phase E) -------------------------------------------
// Une fenêtre par équipement, déplaçable et redimensionnable : on peut en ouvrir plusieurs
// pour comparer deux configurations côte à côte, ce qu'un panneau fixe interdisait.

const deviceWindows = new Map();   // node_id -> { el, body, title, tab }
let windowZ = 50;

function openDeviceWindow(nodeId) {
  let w = deviceWindows.get(nodeId);
  if (!w) {
    const modele = $("device-window-template");
    const elWin = modele.content.firstElementChild.cloneNode(true);
    elWin.dataset.nodeId = nodeId;
    w = {
      el: elWin,
      body: elWin.querySelector(".device-win-body"),
      title: elWin.querySelector(".device-win-title"),
      tab: "phys",
    };
    deviceWindows.set(nodeId, w);
    for (const b of elWin.querySelectorAll(".dtab")) {
      b.addEventListener("click", () => {
        w.tab = b.dataset.dtab;
        syncDeviceTabs(w);
        renderDevice();
      });
    }
    elWin.querySelector(".close").addEventListener("click", () => closeDeviceWindow(nodeId));
    wireTabs(elWin.querySelector(".device-tabs"));
    makeWindowDraggable(elWin, elWin.querySelector(".device-win-head"));
    $("windows").append(elWin);
    placeWindow(w);
  }
  for (const [id, autre] of deviceWindows) autre.el.classList.toggle("active", id === nodeId);
  w.el.style.zIndex = String(++windowZ);
  state.selected = nodeId;
  renderDevice();
  // Le clavier suit la fenêtre ouverte : on y place le focus sans voler celui d'une console
  // en cours de saisie, sinon taper une commande deviendrait impossible.
  if (!w.body.querySelector("input:focus")) w.el.querySelector(".device-tabs .dtab")?.focus();
}

function closeDeviceWindow(nodeId) {
  const w = deviceWindows.get(nodeId);
  if (!w) return;
  w.el.remove();
  deviceWindows.delete(nodeId);
  delete state.consoles[nodeId];
  if (state.selected === nodeId) state.selected = null;
  refreshViews();
}

// Disposition en cascade : chaque nouvelle fenêtre est décalée, sans sortir de l'écran.
function placeWindow(w) {
  const n = deviceWindows.size - 1;
  const pas = 26, largeur = 430;
  const x = Math.min(90 + n * pas, Math.max(8, window.innerWidth - largeur - 16));
  const y = Math.min(70 + n * pas, Math.max(8, window.innerHeight - 260));
  w.el.style.left = `${x}px`;
  w.el.style.top = `${y}px`;
  // Quand plusieurs fenêtres sont ouvertes, `y` grandit par pas de 26 px jusqu'à
  // `innerHeight - 260` : à cette position, la hauteur maximale de la CSS fait descendre la
  // fenêtre bien au-delà du bas de l'écran. On resserre donc la borne sur la place restante.
  //
  // La borne de la CSS est **lue**, jamais remplacée : fixer `max-height` sans la comparer
  // permet à la fenêtre de dépasser sa hauteur de conception — mesuré 805 px au lieu de
  // 678 px, soit 127 px de panneau d'observation recouvert en plus. On ne fait que la
  // resserrer quand la place manque. Le corps défile déjà, rien n'est donc caché.
  const borneCss = parseFloat(getComputedStyle(w.el).maxHeight);
  // La fenêtre survole le plan : c'est sa place, et c'est donc le bas du plan qui la borne,
  // pas le bas de l'écran. Sinon elle descend sur le panneau d'observation, juste en dessous,
  // et recouvre le bouton « Simuler » sans rien signaler : le clic ne part pas, aucun run
  // n'est lancé, et l'écran garde le statut du run précédent comme s'il était le sien.
  // Mesuré à 1400 px sur un écran de 1000 px de haut — plan de 66 à 735, fenêtre de 70 à
  // 830 (plafond CSS de 760 atteint), bouton « Simuler » vers 798 : recouvert.
  const plan = document.querySelector(".plan-area")?.getBoundingClientRect();
  const bas = plan ? Math.min(window.innerHeight - 16, plan.bottom - 8) : window.innerHeight - 16;
  const place = bas - y;
  if (!Number.isFinite(borneCss)) return;
  // La borne est resserrée quand la place manque, et **rendue** à la CSS dès qu'elle ne
  // manque plus : sans ce second sens, une fenêtre rouverte après avoir été réduite
  // resterait petite sans raison. Le corps défile déjà, rien n'est donc caché.
  w.el.style.maxHeight = place < borneCss ? `${Math.max(220, place)}px` : "";
}

function makeWindowDraggable(win, handle) {
  let ox = 0, oy = 0, actif = false;
  handle.addEventListener("pointerdown", (ev) => {
    if (ev.target.closest("button")) return;      // ne pas déplacer en fermant
    actif = true;
    const r = win.getBoundingClientRect();
    ox = ev.clientX - r.left;
    oy = ev.clientY - r.top;
    handle.setPointerCapture(ev.pointerId);
    win.style.zIndex = String(++windowZ);
  });
  handle.addEventListener("pointermove", (ev) => {
    if (!actif) return;
    const x = Math.min(Math.max(0, ev.clientX - ox), window.innerWidth - 40);
    const y = Math.min(Math.max(0, ev.clientY - oy), window.innerHeight - 30);
    win.style.left = `${x}px`;
    win.style.top = `${y}px`;
  });
  const stop = (ev) => {
    if (!actif) return;
    actif = false;
    handle.releasePointerCapture?.(ev.pointerId);
  };
  handle.addEventListener("pointerup", stop);
  handle.addEventListener("pointercancel", stop);
}

function syncDeviceTabs(w) {
  for (const b of w.el.querySelectorAll(".dtab"))
    b.classList.toggle("active", b.dataset.dtab === w.tab);
}

// Rafraîchit toutes les fenêtres ouvertes ; supprime celles d'un équipement disparu.
function renderDevice() {
  for (const [id, w] of [...deviceWindows]) {
    const existe = state.topo?.nodes.some((n) => n.id === id);
    if (!existe) { w.el.remove(); deviceWindows.delete(id); }
  }
  for (const [id, w] of deviceWindows) {
    const node = state.topo.nodes.find((n) => n.id === id);
    w.title.textContent = nodeCaption(node);
    syncDeviceTabs(w);
    const body = w.body;
    clear(body);
    if (w.tab === "phys") {
      body.append(el("div", { class: "device-info" }));
      renderDeviceInfo(node, body);
      body.append(el("button", {
        type: "button", class: "danger", text: "Retirer cet équipement",
        onclick: async () => {
          if (!window.confirm(`Retirer ${node.id} ?`)) return;
          const done = await guard(() => state.client.removeNode(state.sid, node.id));
          if (done === undefined) return;
          closeDeviceWindow(node.id);
          await loadTopology();
        },
      }));
    } else if (w.tab === "config") {
      if (node.kind === "sensor") renderSensorForm(node, body);
      else if (node.kind === "server") renderServeurConfig(node, body);
      else renderGatewayConfig(node, body);
    } else if (w.tab === "cli") {
      if (CLI_KINDS.includes(node.kind)) renderConsole(node, body);
      else body.append(el("p", { class: "no-cli", text: cliAbsentMessage(node.kind) }));
    }
  }
}

// Deux champs en séquence (liste déroulante + libellé), dans l'ordre de lecture français.
function champListe(nom, label, options, valeur, aide) {
  const select = el("select", { name: nom });
  for (const o of options) {
    select.append(el("option", {
      value: o.value, text: o.text, selected: String(valeur ?? "") === o.value ? "selected" : undefined,
      // Un choix qui ne peut pas être retenu reste **visible et nommé**, mais grisé : le
      // retirer de la liste ferait croire qu'il n'existe pas, et le laisser actif ferait
      // enregistrer une configuration qu'aucun run ne peut compiler.
      disabled: o.disabled ? "disabled" : undefined,
    }));
  }
  const bloc = el("label", { class: "gw-champ" }, label, select);
  if (aide) bloc.append(el("span", { class: "gw-aide", text: aide }));
  return bloc;
}

function champNombre(nom, label, bornes, valeur, step = "1") {
  const [lo, hi] = bornes;
  const input = el("input", {
    type: "number", name: nom, min: lo, max: hi, step,
    value: valeur === null || valeur === undefined ? "" : valeur,
  });
  return el("label", { class: "gw-champ" }, label, input,
    el("span", { class: "gw-aide", text: `${lo} à ${hi}` }));
}

function sectionChamps(titre, ...champs) {
  return el("fieldset", { class: "gw-section" },
    el("legend", { text: titre }), ...champs);
}

// Onglet Config d'une passerelle : les réglages que les exercices réclament, et rien de plus.
// Le reste reste au CLI, mais la fenêtre le *dit* et le nomme : taire l'existence d'un réglage
// serait plus grave que de ne pas l'exposer, l'apprenant chercherait un champ qui n'existe pas.
function renderGatewayConfig(node, body) {
  const st = stateOf(node.id);
  if (!CLI_KINDS.includes(node.kind)) {
    body.append(el("p", { class: "muted", text: `Rôle : ${KIND_LABEL[node.kind]}` }));
    body.append(el("p", { class: "no-cli",
      text: "Serveur de réseau : pas de configuration dans cette version." }));
    return;
  }

  const g = st?.gateway ?? {};
  const fields = {};
  const grid = el("div", { class: "gateway-form" });

  const region = champListe("region", "Plan régional",
    [{ value: "", text: "non configuré" },
      ...REGIONS.map((r) => ({ value: r, text: r }))],
    g.region);
  fields.region = region.querySelector("select");

  const sousBande = champListe("sub_band", "Sous-bande",
    [{ value: "", text: "aucune" },
      ...SOUS_BANDES.map((n) => ({ value: String(n), text: String(n) }))],
    g.sub_band ?? "");
  fields.sub_band = sousBande.querySelector("select");

  const puissance = champNombre("tx_power_dbm", "Puissance TX (dBm)",
    GATEWAY_LIMITS.tx_power_dbm, g.tx_power_dbm, "0.5");
  fields.tx_power_dbm = puissance.querySelector("input");

  // La sous-bande n'existe que sur US915 / AU915. On l'explique plutôt que de laisser un champ
  // muet : « désactivé » sans raison est le genre de silence qui fait perdre une heure.
  const aideSousBande = el("p", { class: "gw-aide gw-aide-bloc", text: "" });
  const appliquerSousBande = () => {
    const ok = REGIONS_A_SOUS_BANDE.includes(fields.region.value);
    fields.sub_band.disabled = !ok;
    sousBande.classList.toggle("gw-desactive", !ok);
    aideSousBande.textContent = ok
      ? "Une sous-bande groupe 8 canaux à 125 kHz et un canal à 500 kHz."
      : "La sous-bande n'existe que sur US915 et AU915 : choisissez l'un de ces plans.";
    // Quitter un plan à sous-bandes l'efface côté serveur : la fenêtre doit montrer la même
    // chose. Afficher « 2 » alors que le réglage est parti ferait croire à un enregistrement
    // qui n'a pas eu lieu.
    if (!ok) fields.sub_band.value = "";
  };
  fields.region.addEventListener("change", appliquerSousBande);

  grid.append(sectionChamps("Radio LoRa", region, sousBande, aideSousBande, puissance));

  // Un seul jeu de champs, référencé deux fois : `fields` pour la lecture, le DOM pour
  // l'affichage. Les créer deux fois donnait des valeurs lues hors du formulaire.
  // Le rôle de l'équipement n'est pas un réglage : une frontière ne devient pas relais en
  // choisissant un mode. Le mode qui le contredit est donc grisé, avec la raison écrite à
  // côté — l'enregistrer était accepté ici et refusé au lancement, trois gestes plus loin,
  // par un message (« mode mesh « relay » ne correspond pas au rôle border ») qui nomme un
  // réglage que l'utilisateur a depuis longtemps oublié avoir posé.
  const modeEtranger = node.kind === "border" ? "relay" : "border";
  const modeMesh = champListe("mesh_mode", "Mode",
    [{ value: "", text: "non configuré" },
      { value: "relay", text: "relay — relayer vers la frontière",
        disabled: modeEtranger === "relay" },
      { value: "border", text: "border — passerelle frontière",
        disabled: modeEtranger === "border" }],
    g.mesh_mode,
    `« ${modeEtranger} » est réservé aux équipements de rôle ${modeEtranger} ; celui-ci est `
    + `un ${node.kind}. Un run ne compilerait pas.`);
  const sautsMesh = champNombre("mesh_max_hops", "Sauts max",
    GATEWAY_LIMITS.mesh_max_hops, g.mesh_max_hops);
  const bandeMesh = champListe("mesh_bandwidth_khz", "Bande passante (kHz)",
    [{ value: "", text: "non configuré" },
      ...BANDES_MESH_KHZ.map((b) => ({ value: b, text: b }))],
    g.mesh_bandwidth_khz);
  fields.mesh_mode = modeMesh.querySelector("select");
  fields.mesh_max_hops = sautsMesh.querySelector("input");
  fields.mesh_bandwidth_khz = bandeMesh.querySelector("select");

  // Le modèle, et ce qu'il change. Il vient du catalogue du moteur, filtré sur ce que le
  // rôle permet : un relais exige une radio mesh documentée, un hôte sans radio publiée
  // n'entre pas dans une passerelle. Masqué si le moteur n'en déclare aucun.
  const modeleChamp = el("div", {});
  const modeleAide = el("p", { class: "gw-aide", text: "" });
  if (state.modelesPasserelle.length) {
    const admis = modelesAdmis(state.modelesPasserelle, node.kind);
    const modele = el("select", { name: "gateway_profile" },
      el("option", { value: "", text: "référence du moteur" }));
    for (const m of admis) {
      modele.append(el("option", { value: m.name, text: m.name,
        selected: node.gateway_profile === m.name ? "selected" : undefined }));
    }
    const dire = () => {
      modeleAide.textContent = aideModele(admis.find((m) => m.name === modele.value));
    };
    modele.addEventListener("change", dire);
    dire();
    fields.gateway_profile = modele;
    modeleChamp.append(el("label", {}, "Modèle", modele), modeleAide);
  }

  if (modeleChamp.childNodes.length) grid.append(sectionChamps("Matériel", modeleChamp));
  grid.append(sectionChamps("Relais (mesh)",
    modeMesh, sautsMesh, bandeMesh,
    el("p", { class: "gw-aide gw-aide-bloc",
      text: "Une bande plus large raccourcit l'émission mais réduit la portée." })));

  const message = el("p", { class: "muted", text: "" });
  const form = el("form", {
    novalidate: "",   // les messages sont ceux du studio, pas ceux du navigateur
    onsubmit: async (ev) => {
      ev.preventDefault();
      const raw = { region_actuelle: g.region ?? null };
      for (const [k, input] of Object.entries(fields)) {
        input.classList.remove("field-error");
        raw[k] = input.value;
      }
      const checked = validateGateway(raw);
      if (!checked.ok) {
        fields[checked.field]?.classList.add("field-error");
        message.textContent = checked.message;
        return;
      }
      const topo = await guard(() => state.client.setGateway(state.sid, node.id, checked.settings));
      if (topo) {
        state.topo = topo;
        // Le plan régional peut rendre l'ADR possible, ou le relais l'interdire : la case
        // doit se réévaluer ici, sinon l'utilisateur ne verrait le changement qu'en changeant
        // de session — et croirait l'ADR impossible alors qu'il vient de le rendre possible.
        refreshTopologie();
        message.textContent = "Réglages enregistrés.";
      }
    },
  }, grid, el("div", { class: "sensor-actions" },
    el("button", { type: "submit", class: "primary", text: "Enregistrer" })), message);

  body.append(form);

  // Le renvoi vers le CLI : ce qui reste, où le trouver, et pourquoi ce n'est pas ici.
  body.append(el("details", { class: "gw-avance" },
    el("summary", { text: "Réglages avancés" }),
    el("p", { class: "muted",
      text: `${AVANCE_EN_CLI.join(", ")} : ces réglages restent en ligne de commande, ` +
        "comme sur un équipement réel. Ouvrez l'onglet Console." })));
  appliquerSousBande();
}

// Pourquoi cet equipement n a pas de console, au lieu de masquer l onglet.
/**
 * Le serveur de réseau ne se configure pas : c'est lui qui commande.
 *
 * Sa fenêtre montre donc ce qu'il a **vu** du dernier run, par équipement : le débit qu'il a
 * commandé, les canaux qu'il a laissés, les commandes qu'il a envoyées. Rien n'y est recopié
 * depuis les formulaires — un champ que le run n'a pas observé reste vide, plutôt
 * d'afficher une valeur que personne n'a mesurée.
 */
function renderServeurConfig(node, body) {
  body.append(el("p", { class: "muted", text: `Rôle : ${KIND_LABEL[node.kind]}` }));
  const rows = state.deviceRows ?? [];
  if (!rows.length) {
    body.append(el("p", { class: "no-cli",
      text: "Le serveur n'a encore rien observé : lancez une simulation. Il ne se configure "
        + "pas — c'est lui qui commande le débit, les canaux et les descentes." }));
    return;
  }
  const noeuds = state.topo?.nodes ?? [];
  const nomDe = (row) => {
    const n = noeuds.find((x) => x.id === row.group);
    return n ? (n.name || n.id) : row.group;
  };
  const envoyees = rows.reduce((a, r) => a + (r.sent ?? 0), 0);
  const remises = rows.reduce((a, r) => a + (r.received ?? 0), 0);
  const bloc = el("div", { class: "serveur-vu" });
  bloc.append(el("p", { class: "muted",
    text: `${remises} trame(s) remise(s) au serveur sur ${envoyees} émise(s), `
      + `par ${rows.length} équipement(s).` }));
  // Les commandes sont l'action du serveur lui-même : c'est le seul endroit qui les compte
  // du point de vue de celui qui les envoie.
  const dl = state.resume?.downlink;
  if (dl) {
    bloc.append(el("p", { class: "muted",
      text: `Commandes envoyées : ${dl.delivered} sur ${dl.requested}`
        + (dl.latency_mean_s === null || dl.latency_mean_s === undefined
          ? "." : `, attendue ${formatSecondes(dl.latency_mean_s)} en moyenne.`) }));
  }
  body.append(bloc);

  const corps = el("tbody");
  for (const r of rows) {
    // Une flèche seulement si le serveur a commandé un changement **et** que le terminal
    // l'a appliqué : sinon le débit affiché recopierait le réglage de départ en laissant
    // croire à une décision du serveur.
    const commande = r.final_spreading_factor !== null && r.final_spreading_factor !== undefined
      && r.final_spreading_factor !== r.spreading_factor;
    corps.append(el("tr", {},
      el("th", { scope: "row", text: nomDe(r) }),
      el("td", { text: `${r.received} / ${r.sent}` }),
      el("td", { text: `${r.lost_sensitivity} / ${r.lost_collision}` }),
      el("td", { text: commande
        ? `SF${r.spreading_factor} → SF${r.final_spreading_factor}` : `SF${r.spreading_factor}` }),
      el("td", { text: r.enabled_channels?.length ? r.enabled_channels.join(" ") : "—" })));
  }
  const table = el("table", {},
    el("thead", {}, el("tr", {},
      el("th", { scope: "col", text: "Équipement" }),
      el("th", { scope: "col", text: "Reçues" }),
      el("th", { scope: "col", text: "Pertes" }),
      el("th", { scope: "col", text: "Débit" }),
      el("th", { scope: "col", text: "Canaux" }))), corps);
  body.append(table, el("p", { class: "gw-aide",
    text: "Reçues : remises sur émises. Pertes : hors portée, puis en collision. Canaux : "
      + "ceux que le serveur a laissés au terminal à la fin du run — vide si le run ne les a "
      + "pas observés." }));
}

function cliAbsentMessage(kind) {
  if (kind === "sensor") return "Un capteur ne se configure pas en ligne de commande : utilisez l'onglet Config pour ses réglages radio.";
  if (kind === "server") return "Le serveur de réseau n'expose pas de console dans cette version.";
  return "Cet équipement n'a pas de ligne de commande.";
}

// Infos seules (rafraîchies après une commande sans reconstruire la console, qui garde le focus).
// Vue physique de l'équipement : son illustration, puis le panneau de ce qu'il est
// réellement. Rien n'est avancé ici qui ne soit simulé ; les ports et voyants décrivent le
// matériel représenté, ils ne prétendent pas offrir des réglages inexistants.
/**
 * Déplace un équipement vers les coordonnées saisies dans sa fenêtre.
 * Mêmes garde-fous que l'ajout : domaine des degrés, puis éloignement raisonnable.
 */
async function deplacerParCoordonnees(node, form) {
  const o = readOrigin();
  if (!o || !state.sid) return;
  const lu = lireCoordonnees(`${form.lat.value}, ${form.lon.value}`);
  if (!lu) return showError(new Error(
    "coordonnées illisibles : deux nombres attendus, par exemple « 4.051100, 9.767900 »"));
  const pos = degreesToMeters(lu.lat, lu.lon, o);
  // La même borne qu'à l'ajout, pour la même raison : au-delà, l'équipement sort de
  // l'échelle du plan et devient introuvable sans que rien ne le signale.
  if (Math.abs(pos.x_m) > 1_000_000 || Math.abs(pos.y_m) > 1_000_000) {
    return showError(new Error("coordonnées trop éloignées de l'origine de la zone"));
  }
  const topo = await guard(() => state.client.moveNode(state.sid, node.id, pos));
  if (!topo) return;
  state.topo = topo;
  refreshViews();
  renderDevice();
}

function renderDeviceInfo(node, body) {
  // La zone n'existe que dans l'onglet Physique. Ailleurs (CLI, Config), il n'y a rien à
  // rafraîchir : on sort au lieu de construire un bloc fantôme, ce qui arrive quand une
  // commande CLI met à jour la topologie alors que l'onglet ouvert n'est pas Physique.
  const info = body?.querySelector(".device-info");
  if (!info) return;
  clear(info);
  const spec = DEVICE_SPECS[node.kind];
  const st = stateOf(node.id);

  info.append(el("div", { class: "phys-top" },
    el("div", { class: "phys-art" }, drawDevice(node.kind)),
    el("div", { class: "phys-id" },
      el("p", { class: "phys-role", text: spec?.role ?? KIND_LABEL[node.kind] }),
      el("p", { class: "muted", text: `Identifiant : ${node.id}` }),
      el("p", { class: "muted", text: `Type : ${KIND_LABEL[node.kind]}` }),
    ),
  ));

  // État réellement connu du serveur, et rien de plus.
  const etat = el("dl", { class: "phys-etat" });
  const ligne = (titre, valeur) => {
    etat.append(el("dt", { text: titre }), el("dd", { text: valeur }));
  };
  // La position est montrée en degrés : c'est ainsi qu'on relève un lieu, et c'est le seul
  // repère qui parle à qui connaît ses coordonnées. Les mètres restent le langage du moteur.
  const o = readOrigin();
  if (o) {
    const d = metresVersDegres(node.x_m, node.y_m, o);
    ligne("Position", formaterCoordonnees(d.lat, d.lon));
    const distance = distanceM(o, d);
    // La distance à l'origine donne l'échelle : « 0,012345° » ne dit rien, « 1,4 km » si.
    ligne("Éloignement", distance < 1000
      ? `${Math.round(distance)} m de l'origine`
      : `${(distance / 1000).toFixed(2)} km de l'origine`);
  } else {
    ligne("Position", `${node.x_m} m, ${node.y_m} m`);
  }
  if (st) {
    ligne("Nom d'hôte", st.hostname);
    ligne("Configuration", st.configured ? "configuré" : "non configuré");
    if (st.region) ligne("Plan régional", st.region);
  }
  // Le matériel, tel que le moteur le nomme : c'est lui qui décide du courant, et le voir
  // ici évite d'aller le chercher dans l'onglet Config. Sans modèle propre, le capteur suit
  // celui du run — il consomme donc bien quelque chose, et « aucun » serait un mensonge.
  if (node.kind === "sensor") {
    const nom = node.sensor?.energy_profile ?? "";
    const modele = state.modelesMateriel.find((m) => m.name === nom);
    // Sans modèle propre, on nomme celui du run au lieu de laisser « celui du run » en
    // suspens : c'est le matériel qui décide du courant, et le lecteur a besoin de savoir
    // lequel avant d'avoir lancé quoi que ce soit.
    const defaut = state.modelesMateriel.find((m) => m.name === state.defautMateriel);
    ligne("Matériel", modele?.label
      ?? (nom || (defaut ? `celui du run (${defaut.label})` : "celui du run")));
  }
  // Le serveur se pose et se dessine, mais le run ne le simule pas : le LNS est implicite
  // derrière la passerelle frontière. Le dire ici, parce que son rôle et ses ports, en haut
  // de cette fenêtre, décrivent un équipement qui a l'air de participer — et qu'un élève
  // conclurait qu'une trame lui arrive vraiment.
  if (node.kind === "server") {
    ligne("Dans le run", "représenté, non simulé : le serveur est implicite derrière la frontière");
  }
  // Le modèle de la passerelle, et surtout ce qu'il change : trois des quatre modèles du
  // catalogue ne décalent pas le seuil, leur fiche ne publiant pas le point de mesure. Le
  // voir ici évite de croire qu'un choix a été fait alors que le run calcule la référence.
  if (node.kind === "relay" || node.kind === "border") {
    const m = state.modelesPasserelle.find((x) => x.name === (node.gateway_profile ?? ""));
    ligne("Modèle", m ? `${m.name} (${m.model})` : "référence du moteur");
    if (m) {
      ligne("Seuil de réception", m.sensitivity_published
        ? `${m.sensitivity_offset_db.toFixed(1).replace("-", "−")} dB par rapport à la référence`
        : "référence : la fiche ne publie pas le point de mesure");
    }
  }
  info.append(el("h3", { class: "phys-titre", text: "État" }), etat);
  info.append(...blocCouverture(node));

  // Résultat du dernier run, sur l'équipement lui-même. La carte colore, la fenêtre chiffre :
  // les deux viennent du même `state.resultats`, donc ne peuvent pas se contredire.
  const res = lignesResultat(state.resultats?.get(node.id), state.fenetreNs);
  if (res) {
    const dl = el("dl", { class: "phys-etat phys-resultat" });
    for (const l of res.lignes) {
      dl.append(el("dt", { text: l.titre }), el("dd", { text: l.valeur }));
    }
    // La pastille rappelle la couleur de la carte : c'est le même équipement, vu deux fois.
    info.append(el("h3", { class: "phys-titre" },
      el("span", { class: "lg-rond", style: `background:${res.couleur}` }),
      document.createTextNode(" Résultat du dernier run")), dl);
  }

  // Second moyen de placer un équipement : saisir ses coordonnées au lieu de le tirer sur
  // la carte. Les deux gestes convergent vers les mêmes mètres, par la même conversion.
  if (o) info.append(el("form", { class: "phys-geo", onsubmit: (ev) => {
    ev.preventDefault();
    deplacerParCoordonnees(node, ev.target);
  } },
    el("h3", { class: "phys-titre", text: "Déplacer vers" }),
    el("div", { class: "row" },
      el("label", {}, document.createTextNode("Latitude"),
        el("input", { name: "lat", type: "text", inputmode: "decimal",
          value: metresVersDegres(node.x_m, node.y_m, o).lat.toFixed(6) })),
      el("label", {}, document.createTextNode("Longitude"),
        el("input", { name: "lon", type: "text", inputmode: "decimal",
          value: metresVersDegres(node.x_m, node.y_m, o).lon.toFixed(6) })),
    ),
    el("button", { type: "submit", text: "Déplacer" }),
    el("p", { class: "muted", text: "Ou tirez l'équipement sur la carte." }),
  ));

  // Ports, tels qu'illustrés : la description doit correspondre au dessin.
  if (spec?.ports?.length) {
    const liste = el("ul", { class: "phys-ports" });
    for (const p of spec.ports) {
      liste.append(el("li", {},
        el("span", { class: "phys-nom", text: p.label }),
        el("span", { class: "muted", text: p.note ?? "" })));
    }
    info.append(el("h3", { class: "phys-titre", text: "Connectique" }), liste);
  }
  if (spec?.leds?.length) {
    const liste = el("ul", { class: "phys-ports" });
    for (const l of spec.leds) {
      liste.append(el("li", {},
        el("span", { class: "phys-nom", text: l.label }),
        el("span", { class: "muted", text: l.etat ?? "" })));
    }
    info.append(el("h3", { class: "phys-titre", text: "Voyants" }), liste);
  }
}

/**
 * La zone de couverture de l'équipement, en chiffres. Vide s'il n'en a pas.
 *
 * La carte et le plan montrent la zone en couleurs ; la fenêtre la chiffre, et les deux
 * viennent du même objet, donc ne peuvent pas se contredire. Les portées sont des
 * **intervalles** dès que l'antenne est directive ou le relief accidenté : annoncer un
 * seul nombre décrirait un disque qui n'est pas celui qu'on voit.
 *
 * @returns {Element[]} zéro, un titre, ou un titre et une liste
 */
function blocCouverture(node) {
  const zone = (state.couverture?.gateways ?? []).find((z) => z.node_id === node.id);
  const bilan = bilanZone(zone);
  if (!bilan) return [];
  const dl = el("dl", { class: "phys-etat phys-couverture" });
  dl.append(el("dt", { text: "Antenne" }),
    el("dd", { text: etiquetteAntenne(zone.antenna) }));
  for (const p of bilan.paliers) {
    dl.append(el("dt", { text: etiquettePalier(p) }),
      el("dd", { text: porteeTexte(p) }));
  }
  // Le modèle dit ce que vaut la zone : un disque log-distance et une zone calculée avec
  // le relief ne sont pas la même promesse, et le voir évite de la surinterpréter.
  dl.append(el("dt", { text: "Calculée par" }),
    el("dd", { text: etiquetteModele(bilan.modele) }));
  const capteur = state.couverture;
  const source = { demande: "capteur demandé", capteurs: "capteur le plus défavorable",
    defaut: "cas d'école" }[capteur.source] ?? capteur.source;
  dl.append(el("dt", { text: "Pour un capteur en" }),
    el("dd", { text: `SF${capteur.sf} à ${capteur.tx_power_dbm} dBm (${source})` }));
  return [el("h3", { class: "phys-titre", text: "Couverture" }), dl];
}

function renderConsole(node, body) {
  if (!state.consoles[node.id]) {
    state.consoles[node.id] = {
      text: "Console de l'équipement. Tapez « ? » pour l'aide, « enable » pour le mode privilégié.\n",
      prompt: `${stateOf(node.id)?.hostname ?? node.id}>`,
      history: createHistory(),
    };
  }
  const c = state.consoles[node.id];
  const out = el("pre", { text: c.text });
  const input = el("input", { type: "text", autocomplete: "off", spellcheck: "false", "aria-label": "Commande CLI" });
  const promptNode = el("span", { class: "prompt", text: promptText({ prompt: c.prompt }) });
  const form = el("form", {
    onsubmit: async (ev) => {
      ev.preventDefault();
      const command = input.value;
      c.history.push(command);
      input.value = "";
      c.text += `${c.prompt} ${command}\n`;
      const res = await guard(() => state.client.cli(state.sid, node.id, command));
      if (!res) {
        out.textContent = c.text;
        return;
      }
      c.prompt = res.prompt;
      promptNode.textContent = res.prompt;
      if (res.output) c.text += res.output.endsWith("\n") ? res.output : res.output + "\n";
      if (res.error) c.text += `${" ".repeat(res.error.column)}^ ${res.error.message}\n`;
      out.textContent = c.text;
      out.scrollTop = out.scrollHeight;
      input.focus();
      // La configuration peut avoir changé (nom d'hôte, région) : on rafraîchit sans reconstruire
      // la console, pour ne pas perdre le focus ni le texte déjà saisi.
      const fresh = await guard(() => state.client.topology(state.sid));
      if (fresh && state.selected === node.id) {
        state.topo = fresh;
        // La console peut régler la région, dernier obstacle à l'ADR : le réglage doit se
        // réévaluer sans reconstruire la console — le focus et la saisie en cours comptent.
        refreshTopologie();
        // Le corps de la fenêtre est passé explicitement : renderDeviceInfo écrit dedans et ne
        // peut plus deviner un panneau unique. On ne rafraîchit que si la zone est toujours là —
        // la fenêtre a pu être refermée pendant l'aller-retour réseau.
        if (body.isConnected) renderDeviceInfo(node, body);
      }
    },
  }, promptNode, input);
  input.addEventListener("keydown", (ev) => {
    if (ev.key === "ArrowUp") { input.value = c.history.up(input.value); ev.preventDefault(); }
    if (ev.key === "ArrowDown") { input.value = c.history.down(input.value); ev.preventDefault(); }
  });
  body.append(el("div", { class: "console" }, out, form));
}

/**
 * Classe d'écoute et descentes à l'initiative du réseau : un seul bloc, parce que l'une sans
 * l'autre n'a pas de sens à montrer.
 *
 * Trois garde-fous, tous dictés par ce que le moteur calcule :
 * - la classe est accompagnée de ce qu'elle **ne** change pas (un ACK tombe dans RX1/RX2
 *   quelle que soit la classe), sinon le sélecteur se lit comme un réglage général ;
 * - la périodicité des créneaux n'apparaît qu'en classe B : ailleurs elle n'a aucun effet, et
 *   un champ sans effet n'est pas un champ grisé, c'est un champ absent ;
 * - dès que la classe B peut attendre **plus** que la classe A, le bloc le dit. Présenter
 *   « classe B » sans cette phrase laisse croire à une amélioration, ce qui est faux la
 *   plupart du temps : un créneau par période de 128 s attend plus qu'un uplink.
 */
function blocEcouteEtDescente(node, values, fields) {
  // Les libellés et les intervalles viennent du moteur. Sans sa réponse, le bloc ne s'affiche
  // pas : plutôt rien qu'un choix dont on inventerait le sens.
  const classes = state.classesEcoute;
  if (!classes.length) return [];

  const select = el("select", { name: "device_class" });
  for (const c of classes) {
    select.append(el("option", { value: c.name, text: c.label,
      selected: (values.device_class ?? CLASSE_DEFAUT) === c.name ? "selected" : undefined }));
  }
  fields.device_class = select;

  const ouverture = el("p", { class: "muted aide" });
  const neChangePas = el("p", { class: "muted aide" });
  const alerte = el("p", { class: "muted aide", hidden: "" });

  // --- Le bloc descente ---------------------------------------------------------------------
  const cocher = el("input", { type: "checkbox", name: "downlink_on",
    ...(values.downlink ? { checked: "checked" } : {}) });
  const champs = el("div", { class: "sensor-form", hidden: values.downlink ? undefined : "" });
  const dl = values.downlink ?? { count: 1, first_request_s: 0, request_period_s: 0, periodicity: 0 };
  const dlFields = {};
  const nombre = (key, label, step = "1") => {
    const [lo, hi] = DOWNLINK_LIMITS[key];
    const input = el("input", { type: "number", name: `downlink_${key}`, min: lo, max: hi,
      step, value: dl[key] ?? "" });
    dlFields[key] = input;
    return el("label", {}, label, input);
  };
  const rangPeriode = el("label", {}, "Écart entre deux envois (s)",
    (dlFields.request_period_s = el("input", { type: "number", name: "downlink_request_period_s",
      min: DOWNLINK_LIMITS.request_period_s[0], max: DOWNLINK_LIMITS.request_period_s[1],
      step: "any", value: dl.request_period_s ?? "" })));
  const choixPeriodicite = el("select", { name: "downlink_periodicity" });
  const rangPeriodicite = el("label", {}, "Fréquence des créneaux", choixPeriodicite);
  // La périodicité est un choix, pas un nombre : elle entre dans `dlFields` comme les autres,
  // sinon le validateur la verrait absente et refuserait la case cochée à coup sûr.
  dlFields.periodicity = choixPeriodicite;
  champs.append(
    nombre("count", "Nombre de commandes"),
    nombre("first_request_s", "Premier envoi à (s)", "any"),
    rangPeriode,
    rangPeriodicite,
  );

  // Le champ « écart » n'a de sens qu'à partir de deux commandes ; la périodicité n'en a qu'en
  // classe B. Les deux se masquent donc — un champ qui n'a pas d'effet ne se grise pas, il
  // disparaît.
  function rafraichir() {
    const classe = select.value;
    const info = classes.find((c) => c.name === classe);
    ouverture.textContent = info?.ouverture ?? "";
    neChangePas.textContent = info?.ne_change_pas ?? "";

    champs.hidden = !cocher.checked;
    rangPeriode.hidden = Number(dlFields.count.value) <= 1;

    const estB = classe === CLASSE_A_PERIODICITE;
    rangPeriodicite.hidden = !estB;
    // Les périodicités et leurs intervalles sont celles du moteur ; on ne recalcule rien.
    if (estB && !choixPeriodicite.options.length) {
      for (const p of info?.periodicites ?? []) {
        const texte = `un créneau toutes les ${formatSecondes(p.intervalle_s)}`
          + ` (${p.slots_par_periode} par période de 128 s)`;
        choixPeriodicite.append(el("option", { value: String(p.value), text: texte,
          selected: String(dl.periodicity ?? 0) === String(p.value) ? "selected" : undefined }));
      }
    }

    // L'avertissement qui compte : une classe B lente attend plus longtemps qu'une classe A.
    const intervalle = estB
      ? (info?.periodicites ?? []).find((p) => String(p.value) === choixPeriodicite.value)
          ?.intervalle_s
      : undefined;
    const periode = Number(fields.period_s?.value);
    const plusLente = estB ? classeBPlusLenteQueA(intervalle, periode) : null;
    if (plusLente === true) {
      alerte.textContent = `À cette fréquence, le terminal attend son créneau jusqu'à`
        + ` ${formatSecondes(intervalle)} — davantage que la classe A, qui n'attend que sa`
        + ` prochaine émission (${formatSecondes(periode)}). La classe B n'est pas une classe A`
        + ` plus rapide : c'est la fréquence des créneaux qui décide.`;
      alerte.hidden = undefined;
    } else {
      alerte.hidden = "";
    }
  }

  select.addEventListener("change", rafraichir);
  cocher.addEventListener("change", rafraichir);
  dlFields.count.addEventListener("input", rafraichir);
  choixPeriodicite.addEventListener("change", rafraichir);
  fields.period_s?.addEventListener("input", rafraichir);
  rafraichir();

  // Le champ `downlink` transmis n'existe que si la case est cochée : l'absence est publiée,
  // pas un bloc de zéros qui dirait « une commande à l'instant 0 ».
  const lire = () => {
    if (!cocher.checked) return null;
    const out = {};
    for (const [k, input] of Object.entries(dlFields)) out[k] = input.value;
    return out;
  };
  fields.__downlink = lire;
  fields.__downlinkChamps = dlFields;

  return [
    el("label", {}, "Classe d'écoute", select),
    ouverture,
    neChangePas,
    el("label", { class: "case" }, cocher, " Le serveur envoie une commande"),
    champs,
    alerte,
  ];
}

function renderSensorForm(node, body) {
  const values = sensorFormFrom(node);
  const fields = {};
  const grid = el("div", { class: "sensor-form" });
  const numberField = (key, label, step = "1") => {
    const [lo, hi] = SENSOR_LIMITS[key];
    const input = el("input", { type: "number", name: key, min: lo, max: hi, step, value: values[key] ?? "" });
    fields[key] = input;
    return el("label", {}, label, input);
  };
  grid.append(
    numberField("spreading_factor", "Facteur d'étalement (SF)"),
    numberField("payload_bytes", "Charge utile (octets)"),
    numberField("tx_power_dbm", "Puissance (dBm)", "0.5"),
    numberField("period_s", "Période (s)", "any"),
    numberField("messages", "Messages"),
    numberField("start_spread_s", "Dispersion du départ (s)", "any"),
    numberField("channel_freq_hz", "Fréquence (Hz, vide = défaut)"),
  );
  const regionSelect = el("select", { name: "region" }, el("option", { value: "", text: "plan des passerelles" }));
  for (const r of REGIONS) regionSelect.append(el("option", { value: r, text: r, selected: values.region === r ? "selected" : undefined }));
  fields.region = regionSelect;
  grid.append(el("label", {}, "Plan régional", regionSelect));
  grid.append(...blocEcouteEtDescente(node, values, fields));
  // Le matériel, par équipement. Deux capteurs de matériel différent ne consomment pas la
  // même chose (mesuré : 10 à 11 % de courant moyen), et pouvoir les comparer dans un même
  // run est précisément l'intérêt du réglage. « celui du run » est le défaut : un chantier
  // écrit avant cette distinction garde ses chiffres.
  if (state.modelesMateriel.length) {
    const modeleSelect = el("select", { name: "energy_profile" },
      el("option", { value: "", text: "celui du run" }));
    for (const m of state.modelesMateriel) {
      modeleSelect.append(el("option", { value: m.name, text: m.label,
        selected: values.energy_profile === m.name ? "selected" : undefined }));
    }
    fields.energy_profile = modeleSelect;
    grid.append(el("label", {}, "Matériel", modeleSelect));
    // « Celui du run » sans dire lequel est une devinette : les deux matériels diffèrent de
    // 10 % de courant moyen, et choisir entre eux sans savoir lequel on aura n'est pas
    // choisir. Le nom vient du moteur (`default`), seul à savoir ce que le run calcule.
    const defaut = state.modelesMateriel.find((m) => m.name === state.defautMateriel);
    if (defaut) grid.append(el("p", { class: "hint",
      text: `« celui du run » : ${defaut.label}` }));
  }
  const message = el("p", { class: "muted", text: "" });
  const form = el("form", {
    novalidate: "",   // les messages de validation sont ceux du studio, pas ceux du navigateur
    onsubmit: async (ev) => {
      ev.preventDefault();
      const raw = {};
      for (const [k, input] of Object.entries(fields)) {
        if (k.startsWith("__")) continue;
        input.classList.remove("field-error");
        raw[k] = input.value;
      }
      // Le bloc descente publie son absence (`null`) plutôt qu'un bloc de zéros.
      if (fields.__downlink) raw.downlink = fields.__downlink();
      const checked = validateSensor(raw);
      if (!checked.ok) {
        // Les champs du bloc descente sont nommés `downlink_*` dans le formulaire et `key`
        // dans le validateur : l'erreur retrouve donc son champ par ce préfixe.
        const champ = checked.field?.startsWith("downlink_")
          ? fields.__downlinkChamps?.[checked.field.slice("downlink_".length)]
          : fields[checked.field];
        champ?.classList.add("field-error");
        message.textContent = checked.message;
        return;
      }
      const topo = await guard(() => state.client.setSensor(state.sid, node.id, checked.settings));
      if (topo) {
        state.topo = topo;
        refreshViews();                       // le formulaire reste en place : il porte le message
        message.textContent = "Réglages enregistrés.";
      }
    },
  }, grid, el("button", { type: "submit", text: "Enregistrer les réglages" }), message);
  body.append(form);
}

// --- Ajout d'équipement --------------------------------------------------------------------
// Le matériel n'a de sens que pour un capteur : le champ se masque pour les autres types,
// comme la sous-bande se grise hors des plans qui en ont une. Mieux vaut un champ absent
// qu'un champ sans objet.
$("add-form").querySelector('[name="kind"]').addEventListener("change", () => {
  appliquerMaterielAjout();
  // Le rôle a pu changer : un relais n'accepte pas les mêmes modèles qu'une frontière.
  renderModeleAjout();
});
$("add-form").querySelector('[name="gateway_profile"]')
  .addEventListener("change", appliquerModeleAjout);

$("add-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  if (!state.sid) return showError(new Error("aucune session"));
  const f = new FormData(ev.target);
  const o = readOrigin();
  if (!o) return showError(new Error("origine de la zone absente : cliquez sur la carte"));
  // Degrés en façade, mètres au moteur (D2). Le message d'erreur parle donc de latitude et
  // de longitude, les seuls nombres que l'utilisateur a réellement tapés — lui annoncer
  // une « ordonnée en mètres » décrirait une valeur qu'il n'a jamais vue.
  const checked = validateNewNodeGeo(Object.fromEntries(f.entries()), o);
  if (!checked.ok) return showError(new Error(checked.message));
  const topo = await guard(() => state.client.addNode(state.sid, checked.node));
  if (topo) {
    state.topo = topo;
    state.selected = checked.node.id;
    ev.target.reset();
    // Le type est revenu à « passerelle » : le matériel n'a plus d'objet.
    appliquerMaterielAjout();
    appliquerModeleAjout();
    // Poser une passerelle rend l'ADR possible, poser un relais l'interdit : les réglages
    // qui en dépendent se réévaluent ici, sans quoi la case garderait l'état d'avant l'ajout.
    refreshTopologie();
    renderDevice();
    await refreshSessions();
  }
});

// --- Inspecteur de trames ------------------------------------------------------------------

// Affiche la trame LoRaWAN de l evenement actif, couche par couche. Les octets viennent du
// serveur (coeur C++ via frame_view) ; rien n est reconstruit ici.
function showFrame(index) {
  const box = $("frame-inspector");
  const body = $("frame-table")?.querySelector("tbody");
  const note = $("frame-note");
  if (!box || !body || !note) return;
  const ev = state.events[index];
  if (!ev || !ev.frame) {
    box.hidden = true;
    return;
  }
  box.hidden = false;
  while (body.firstChild) body.removeChild(body.firstChild);
  for (const r of frameRows(ev.frame.mac || {}, ev.frame.application || {})) {
    const tr = document.createElement("tr");
    const th = document.createElement("th");
    th.textContent = r.label;
    const td = document.createElement("td");
    td.textContent = r.value;
    const tn = document.createElement("td");
    tn.className = "muted";
    tn.textContent = r.note;
    tr.append(th, td, tn);
    body.append(tr);
  }
  const octets = ev.frame.phy ? ev.frame.phy.octets : "?";
  note.textContent = `${ev.kind} - dispositif ${ev.device_index} - ${octets} octets sur l air`;
}
// --- Simulation ----------------------------------------------------------------------------
const player = createPlayer({
  svg: $("plan"),
  panel: $("player"),
  positionOf: (id) => {
    const node = state.topo?.nodes?.find((n) => n.id === id);
    return node && state.bounds ? toScreen(node, state.bounds, W, H) : null;
  },
  // La vague prend la forme de l'antenne : il faut donc savoir projeter des mètres, pas
  // seulement des centres. Ces fonctions lisent la même topologie et les mêmes bornes que
  // le plan, donc la vague est exactement à l'échelle de ce qu'elle éclaire.
  project: (p) => (state.bounds ? toScreen(p, state.bounds, W, H) : null),
  metresOf: (id) => state.topo?.nodes?.find((n) => n.id === id) ?? null,
  antennaOf: (id) => state.topo?.nodes?.find((n) => n.id === id)?.antenna ?? null,
  // Le front s'arrête à la portée de la zone : une vague qui la franchirait démentirait
  // la zone affichée juste à côté.
  rayonVague: (id) => porteeVague(id),
  onActive: (index) => showFrame(index),
});

/**
 * Segments d'animation des descentes réseau, ou rien.
 *
 * `passerelle` : ces descentes ne sont publiées que sur un run mono-passerelle, donc la
 * première passerelle de la session est la bonne — il n'y en a pas d'autre.
 *
 * `capteurs` : l'instant voulu vient du réglage du capteur, pas d'une supposition. Un capteur
 * dont le réglage a changé depuis le run n'animerait rien, faute de pouvoir dater quoi que ce
 * soit : c'est voulu, mieux vaut pas de flèche qu'une flèche au mauvais endroit.
 */
function descentesSegments(deviceRows, deviceGroups) {
  const noeuds = state.topo?.nodes ?? [];
  const passerelle = noeuds.find((n) => n.kind === "border" || n.kind === "relay")?.id ?? null;
  const capteurs = new Map(noeuds.map((n) => [n.id, n.sensor]));
  return segmentsDescentes({ deviceRows, deviceGroups, capteurs, passerelle });
}

// Charge les événements et la table dispositif -> capteur du run, puis prépare le lecteur.
async function loadAnimation(runId) {
  try {
    const events = await collectPages((cursor) => state.client.eventsPage(runId, cursor));
    state.events = events;
    const rows = await collectPages((cursor) => state.client.devicesPage(runId, cursor));
    const groups = deviceGroupsFromRows(rows);
    // Les descentes réseau ne sont pas des événements de la trace : elles sont reconstituées
    // de l'instant voulu (scénario) et de l'attente mesurée (run). Elles s'ajoutent aux
    // segments, et le lecteur les montre comme les autres.
    const segs = segmentsFromEvents(events, groups).concat(descentesSegments(rows, groups));
    player.load({ events, segs, groups });
  } catch (err) {
    player.clear();
    $("sim-status").textContent += ` Animation indisponible : ${err.message}`;
  }
}

function renderSimulationIdle() {
  player.clear();
  $("sim-status").textContent = "";
  clear($("sim-notes"));
  $("sim-results").hidden = true;
  // Le retrait des traits se fait au prochain rendu (`refreshViews`), qui suit de toute
  // façon : appeler `syncMap` ici tracerait avec la topologie de la session précédente.
  state.rxMatrix = null;
  state.liaisonsObservees = [];
}

// --- Runs déjà lancés : revoir une simulation au lieu de n'avoir que la dernière -------------
// Le run auquel on compare, et la dernière liste lue : la comparaison se recalcule à partir
// de cette liste, pas d'un souvenir de ce qu'on avait cliqué.
let comparerAvec = null;
let dernierRuns = [];
//
// Comparer deux réglages suppose de revoir le premier. Sans cette liste, un run qu'on n'a pas
// noté est un run perdu : l'atelier ne connaissait que le dernier.

/** Une date courte : le jour et l'heure suffisent à retrouver un run, l'année encombre. */
function formatInstant(secondes) {
  if (!secondes) return "—";
  return new Date(secondes * 1000).toLocaleString("fr-FR",
    { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

async function renderRuns() {
  const vide = $("runs-vide"), table = $("runs-table"), lignes = $("runs-lignes");
  if (!vide || !table || !lignes) return;
  $("runs-note").textContent = "";
  if (!state.sid) {
    table.hidden = true;
    lignes.replaceChildren();
    vide.hidden = false;
    vide.textContent = "Aucun chantier sélectionné.";
    return;
  }
  const liste = await guard(() => state.client.runs(state.sid));
  if (!liste) return;
  const items = liste.items ?? [];
  table.hidden = items.length === 0;
  vide.hidden = items.length > 0;
  if (!items.length) {
    lignes.replaceChildren();
    vide.textContent = "Aucun run lancé depuis ce chantier.";
    return;
  }
  // Les lignes se construisent **avant** de remplacer : vider la table puis attendre le
  // serveur donnait un tableau vide pendant l'aller-retour, et un clic arrivant là ne
  // trouvait plus rien à ouvrir.
  dernierRuns = items;
  const rows = [];
  for (const r of items) {
    const tr = el("tr", { class: r.run_id === state.runId ? "affiche" : undefined });
    // Un run non terminé n'a pas de résultat : ses cases restent vides plutôt qu'à zéro.
    // « 0 reçu » se lirait comme une mesure, alors qu'il n'y en a pas eu.
    const fini = r.state === "done";
    tr.append(
      el("td", { text: r.seed === null || r.seed === undefined ? "—" : String(r.seed) }),
      el("td", { text: formatInstant(r.created_at) }),
      el("td", { text: r.state + (r.state === "done" ? "" : r.problem ? " : " + r.problem.message : "") }),
      el("td", { text: fini ? `${r.received} / ${r.sent}` : "—" }),
      el("td", { text: fini && r.pdr !== null && r.pdr !== undefined ? formatPercent(r.pdr) : "—" }),
      el("td", { text: fini && r.downlink ? formatSecondes(r.downlink.latency_mean_s) : "—" }),
    );
    // La ligne entière est cliquable à la souris ; le bouton est ce qui la rend atteignable
    // au clavier. Une ligne de tableau ne prend pas le focus : sans lui, revoir un run
    // demanderait la souris, et le clavier ne verrait jamais l'historique.
    const revoir = el("button", { type: "button", text: "Revoir",
      "aria-label": `Revoir le run de la graine ${r.seed ?? "?"}, lancé `
        + `${formatInstant(r.created_at)}`,
      ...(fini ? {} : { disabled: "disabled",
        title: "Ce run n'est pas terminé : il n'a pas de résultat." }) });
    revoir.addEventListener("click", (ev) => { ev.stopPropagation(); ouvrirRun(r); });
    tr.append(el("td", {}, revoir));
    tr.addEventListener("click", () => ouvrirRun(r));
    // Comparer vient après Revoir, dans l'ordre de l'en-tête : une colonne décalée ferait
    // lire l'écart sous le bouton, et inversement.
    if (fini && r.run_id !== state.runId) {
      const comparer = el("button", { type: "button", text: "Comparer",
        "aria-label": `Comparer le run affiché avec celui de la graine ${r.seed ?? "?"}` });
      comparer.addEventListener("click", (ev) => {
        ev.stopPropagation();
        comparerAvec = r;
        const affiche = dernierRuns.find((x) => x.run_id === state.runId);
        if (affiche) renderComparaison(affiche, r);
      });
      tr.append(el("td", {}, comparer));
    } else {
      tr.append(el("td", {}));
    }
    rows.push(tr);
  }
  lignes.replaceChildren(...rows);
  // La comparaison reste affichée tant qu'on ne change pas de run affiché : la relire à
  // chaque rendu la ferait disparaître au premier rafraîchissement.
  const affiche = items.find((r) => r.run_id === state.runId) ?? null;
  if (comparerAvec && affiche && comparerAvec.run_id !== affiche.run_id) {
    renderComparaison(affiche, comparerAvec);
  } else if (comparerAvec && comparerAvec.run_id === state.runId) {
    comparerAvec = null;
    $("runs-compare").hidden = true;
  }
  $("runs-note").textContent = items.length === 1
    ? "Un run gardé par ce chantier. Cliquez pour le revoir."
    : `${items.length} runs gardés par ce chantier. Cliquez pour en revoir un : `
      + "les chiffres affichés deviennent les siens.";
}

/**
 * Deux runs l'un à côté de l'autre, avec l'écart.
 *
 * Seules les grandeurs que **les deux** runs ont mesurées sont comparées. Un écart calculé
 * contre une case vide inventerait une différence : l'attente des descentes, par exemple, ne
 * se compare que si les deux runs en ont planifié — sinon la ligne n'apparaît pas.
 *
 * `a` est le run affiché, `b` celui qu'on lui compare : l'écart est lu de l'un vers l'autre,
 * et le sens est écrit dans l'en-tête plutôt que supposé.
 */
function renderComparaison(a, b) {
  const bloc = $("runs-compare");
  clear(bloc);
  const signe = (v, unite = "") => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v)}${unite}`;
  const lignes = [];
  if (a.pdr !== null && a.pdr !== undefined && b.pdr !== null && b.pdr !== undefined) {
    lignes.push(["Taux de réception (PDR)", formatPercent(a.pdr), formatPercent(b.pdr),
      signe(Math.round((b.pdr - a.pdr) * 1000) / 10, " pts")]);
  }
  if (a.received !== undefined && b.received !== undefined) {
    lignes.push(["Trames reçues", `${a.received} / ${a.sent}`, `${b.received} / ${b.sent}`,
      signe(b.received - a.received)]);
  }
  if (a.downlink && b.downlink) {
    const ecart = b.downlink.latency_mean_s - a.downlink.latency_mean_s;
    lignes.push(["Attente de la commande", formatSecondes(a.downlink.latency_mean_s),
      formatSecondes(b.downlink.latency_mean_s),
      // Une attente se lit en secondes, mais l'écart d'une classe B à l'autre se joue sur
      // des dizaines de secondes : garder deux décimales ici noierait la différence.
      signe(Math.round(ecart * 10) / 10, " s")]);
  }
  if (!lignes.length) {
    bloc.hidden = false;
    bloc.append(el("p", { class: "muted",
      text: "Ces deux runs n'ont aucune grandeur comparable : ils n'ont pas mesuré les mêmes"
        + " choses." }));
    return;
  }
  const table = el("table", {},
    el("thead", {}, el("tr", {},
      el("th", { scope: "col", text: "Grandeur" }),
      el("th", { scope: "col", text: `Affiché (graine ${a.seed ?? "?"})` }),
      el("th", { scope: "col", text: `Comparé (graine ${b.seed ?? "?"})` }),
      el("th", { scope: "col", text: "Écart" }))));
  const corps = el("tbody");
  for (const [nom, va, vb, ecart] of lignes) {
    corps.append(el("tr", {}, el("th", { scope: "row", text: nom }),
      el("td", { text: va }), el("td", { text: vb }), el("td", { text: ecart })));
  }
  table.append(corps);
  bloc.hidden = false;
  bloc.append(el("h3", { text: "Comparaison" }), table,
    el("p", { class: "muted", text: "L'écart est lu du run affiché vers le run comparé." }));
}

/**
 * Rouvre un run déjà lancé : ses résultats remplacent ceux de l'écran.
 *
 * Le run n'est **pas** relié à nouveau (`bind`) : relier sert à noter un exercice sur l'état
 * courant du chantier, alors qu'ici on ne fait que regarder un résultat passé. Le chantier ne
 * bouge donc pas.
 */
async function ouvrirRun(r) {
  if (r.state !== "done") {
    $("runs-note").textContent = `Le run ${r.run_id} n'est pas terminé : il n'a pas de résultat.`;
    return;
  }
  if (state.busy) {
    $("runs-note").textContent = "Un run est déjà en cours d'affichage.";
    return;
  }
  state.busy = true;
  try {
    const summary = await guard(() => state.client.summary(r.run_id));
    if (!summary) return;
    const rows = await guard(() => collectPages(
      (cursor) => state.client.devicesPage(r.run_id, cursor), MAX_METRIC_DEVICES));
    if (!rows) return;
    // Les bilans comptent les événements du run affiché : ceux du précédent n'ont plus rien à
    // dire ici, et les laisser ferait lire l'ancien résultat comme celui qu'on vient d'ouvrir.
    $("adr-bilan").hidden = true;
    clear($("adr-bilan-liste"));
    $("adr-bilan-aide").textContent = "";
    $("proto-bilan").hidden = true;
    clear($("proto-bilan-liste"));
    $("proto-bilan-aide").textContent = "";
    $("dl-bilan").hidden = true;
    clear($("dl-bilan-liste"));
    $("dl-bilan-aide").textContent = "";
    clear($("sim-notes"));

    state.runId = r.run_id;
    state.deviceRows = rows;
    state.resultats = resultatsParNoeud(rows, state.topo?.nodes ?? []);
    state.fenetreNs = fenetreObservationNs(summary);
    // Les liaisons viennent du run, pas de la session : le chantier a pu changer depuis, et
    // c'est le réseau d'alors qu'on veut revoir.
    state.liens = r.links ?? [];
    state.passerelles = summary.gateways ?? null;
    state.rxMatrix = summary.rx_matrix ?? null;
    state.liaisonsObservees = calculerLiaisons();
    state.resume = summary;
    renderResults(summary, (r.links ?? []).map((l) => l.gateway), rows);
    renderLegend();
    renderDevice();
    syncMap();
    await loadAnimation(r.run_id);
    renderBilanProtocole();
    // Le résultat se lit dans l'onglet Simulation : y ramener, sinon le clic semble sans effet.
    selectObservationTab("sim");
    $("sim-status").textContent = `Run ${r.run_id} (graine ${r.seed ?? "?"}) rouvert : `
      + "les chiffres affichés sont les siens.";
  } finally {
    state.busy = false;
    // La liste se relit à l'ouverture de l'onglet : la rafraîchir alors qu'elle est masquée
    // serait une requête pour un panneau qu'on ne regarde pas.
    const panneau = document.querySelector('.tab-body[data-panel="runs"]');
    if (panneau && !panneau.hidden) await renderRuns();   // la ligne affichée se marque
  }
}

$("sim-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  // Un run qui ne part pas en silence laisse à l'écran le statut du précédent, et fait croire
  // à un résultat qui n'est pas le sien. La raison est donc énoncée.
  if (!state.sid) { showError(new Error("aucune session : créez ou sélectionnez un chantier")); return; }
  if (state.busy) { $("sim-status").textContent = "Run déjà en cours."; return; }
  state.busy = true;
  $("simulate").disabled = true;
  try {
    const seed = Number($("seed").value);
    const started = await guard(() => state.client.simulate(state.sid, seed));
    if (!started) {
      // `guard` a déjà affiché la raison ; le statut doit cesser de parler du run d'avant.
      $("sim-status").textContent = "Run non lancé — voir le message d'erreur.";
      return;
    }
    clear($("sim-notes"));
    for (const note of started.notes) $("sim-notes").append(el("li", { text: note }));
    // Le bilan du run précédent ne survit pas au lancement : un encadré qui reste affiché
    // pendant que le nouveau run tourne ferait lire l'ancien résultat comme le nouveau.
    $("adr-bilan").hidden = true;
    clear($("adr-bilan-liste"));
    $("adr-bilan-aide").textContent = "";
    $("proto-bilan").hidden = true;
    clear($("proto-bilan-liste"));
    $("proto-bilan-aide").textContent = "";
    $("dl-bilan").hidden = true;
    clear($("dl-bilan-liste"));
    $("dl-bilan-aide").textContent = "";
    $("sim-status").textContent = `Run ${started.run_id} : ${started.state}…`;
    const status = await waitForRun(started.run_id);
    if (!status) return;
    if (status.state !== "done") {
      $("sim-status").textContent = `Run ${status.state}${status.problem ? " : " + status.problem.message : ""}`;
      return;
    }
    await guard(() => state.client.bind(state.sid, started.run_id));
    state.runId = started.run_id;   // la carte situera ce résultat, pas le jeu d'exemple
    refreshMapLink();
    const summary = await guard(() => state.client.summary(started.run_id));
    if (!summary) return;
    // Les indicateurs calculés agrègent les lignes par dispositif : sans elles, seuls les
    // totaux seraient affichés et la ventilation par groupe serait impossible.
    const deviceRows = await guard(() => collectPages(
      (cursor) => state.client.devicesPage(started.run_id, cursor), MAX_METRIC_DEVICES));
    state.deviceRows = deviceRows ?? [];
    state.resultats = resultatsParNoeud(state.deviceRows, state.topo?.nodes ?? []);
    state.fenetreNs = fenetreObservationNs(summary);
    // Deux choses que le plan doit retenir pour tracer les liaisons : la correspondance
    // equipement <-> passerelle, et le rapport de chaque passerelle. Sans elles, le plan
    // montrerait des equipements sans jamais dire qui parle a qui.
    state.liens = started.links ?? [];
    state.passerelles = summary.gateways ?? null;
    state.rxMatrix = summary.rx_matrix ?? null;
    // Un seul calcul pour les deux vues : si le plan et la carte le refaisaient chacun,
    // ils pourraient diverger sans que rien ne le signale.
    state.liaisonsObservees = calculerLiaisons();
    state.resume = summary;
    renderResults(summary, started.links.map((l) => l.gateway), state.deviceRows);
    renderLegend();
    renderDevice();             // la fenêtre ouverte chiffre le résultat
    syncMap();                  // la carte change de couleur : elle montre le run
    await loadAnimation(started.run_id);
    // Après le chargement des événements, et pas avant : le bilan des échanges les compte.
    // L'appeler depuis `renderResults` l'aurait fait lire ceux du run précédent.
    renderBilanProtocole();
    $("sim-status").textContent = `Run ${started.run_id} terminé (graine ${seed}).`;
    // Ce run est désormais dans l'historique du chantier : la liste le montre, sans quoi
    // « relancer » et « revoir » resteraient la même action.
    if (!document.querySelector('.tab-body[data-panel="runs"]').hidden) await renderRuns();
  } finally {
    state.busy = false;
    $("simulate").disabled = false;
  }
});

async function waitForRun(runId) {
  const deadline = Date.now() + RUN_TIMEOUT_MS;
  for (;;) {
    const status = await guard(() => state.client.run(runId));
    if (!status) return null;
    $("sim-status").textContent = `Run ${runId} : ${status.state} (${Math.round(status.progress * 100)} %)`;
    if (["done", "failed", "cancelled"].includes(status.state)) return status;
    if (Date.now() > deadline) {
      showError(new Error("délai dépassé en attendant le run"));
      return null;
    }
    await new Promise((resolve) => setTimeout(resolve, RUN_POLL_MS));
  }
}

function renderResults(summary, linkedNames, deviceRows = []) {
  const table = $("sim-results");
  const tbody = table.querySelector("tbody");
  clear(tbody);
  const rows = gatewayRows(summary, linkedNames);
  for (const r of rows) {
    tbody.append(el("tr", {},
      el("td", { text: r.linked ? r.name : `${r.name} (non liée)` }), el("td", { text: String(r.received) }),
      el("td", { text: String(r.lost) }), el("td", { text: r.latency + (r.latencySamples ? ` (${r.latencySamples})` : "") }),
      el("td", { text: r.mesh })));
  }
  table.hidden = rows.length === 0;
  renderAdrBilan(deviceRows);
  renderBilanDescentes(summary, deviceRows);
  renderMetrics(summary, deviceRows);
}

/**
 * Les commandes que le serveur a voulu envoyer, et l'attente qu'elles ont subie.
 *
 * Rien ne s'affiche si le run n'en a planifié aucune : un encadré de zéros se lirait comme
 * « aucune commande n'est arrivée », alors que la vérité est qu'aucune n'a été demandée.
 *
 * Les chiffres viennent du run, jamais du formulaire. En particulier l'attente affichée est
 * celle que le moteur a mesurée — ce n'est pas le « jusqu'à » annoncé au moment du réglage,
 * qui n'était qu'un ordre de grandeur de la fenêtre.
 */
function renderBilanDescentes(summary, deviceRows) {
  const bloc = $("dl-bilan");
  const liste = $("dl-bilan-liste");
  const aide = $("dl-bilan-aide");
  clear(liste);
  const d = summary?.downlink;
  if (!d) {
    bloc.hidden = true;
    aide.textContent = "";
    return;
  }
  const manquees = d.requested - d.delivered;
  liste.append(el("li", { text: `${d.requested} commande(s) envoyée(s) par le serveur, `
    + `${d.delivered} partie(s) de la passerelle.` }));
  if (d.delivered > 0) {
    liste.append(el("li", { text: `Attente avant l'émission : `
      + `${formatSecondes(d.latency_mean_s)} en moyenne, `
      + `${formatSecondes(d.latency_max_s)} au plus.` }));
  }
  if (manquees > 0) {
    // Une commande non acheminée n'est pas une panne : la fenêtre est arrivée après la fin de
    // l'observation, ou le terminal n'en a jamais ouvert. Le dire sans accuser.
    liste.append(el("li", { text: `${manquees} non acheminée(s) : la fenêtre n'est jamais `
      + `arrivée avant la fin du run.` }));
  }
  // Ce que la classe a réellement changé, lu dans le run : c'est la phrase qui compte, et
  // elle n'est pas écrite ici — ce sont les chiffres du run qui la composent.
  const parClasse = attendesParGroupe(deviceRows);
  if (parClasse.length > 1) {
    const [plusRapide, ... reste] = parClasse;
    const plusLent = reste[reste.length - 1];
    if (plusLent && plusLent.latence > plusRapide.latence) {
      aide.textContent = `Du premier au dernier : ${plusRapide.nom} `
        + `(${formatSecondes(plusRapide.latence)}) contre ${plusLent.nom} `
        + `(${formatSecondes(plusLent.latence)}). C'est la classe d'écoute, et elle seule, `
        + `qui explique cet écart — sur un ACK, les trois classes se comporteraient `
        + `exactement de la même façon.`;
    }
  } else if (parClasse.length === 1) {
    aide.textContent = "";
  }
  bloc.hidden = false;
}

/**
 * Attente moyenne par groupe, triée du plus rapide au plus lent.
 *
 * Les groupes sans descente demandée sont écartés : ils n'ont pas d'attente, et les mettre
 * à zéro les ferait gagner la comparaison sans avoir rien attendu.
 */
function attendesParGroupe(deviceRows) {
  const somme = new Map();
  for (const r of deviceRows ?? []) {
    if (r.downlink_latency_s == null) continue;
    const avant = somme.get(r.group) ?? { total: 0, n: 0 };
    avant.total += r.downlink_latency_s;
    avant.n += 1;
    somme.set(r.group, avant);
  }
  return [...somme.entries()]
    .map(([nom, v]) => ({ nom, latence: v.total / v.n }))
    .sort((a, b) => a.latence - b.latence);
}

/**
 * Les échanges avec le serveur, tels que le run les a produits.
 *
 * Deux règles tiennent ce bloc debout :
 *   - il ne s'ouvre que si le réglage était **simulé** (la session le dit, pas le comptage) ;
 *   - les chiffres viennent des événements du run, jamais des cases du formulaire.
 *
 * Les deux cas qui méritent d'être vus ne ressemblent pas à des succès : une flotte dont
 * aucune jointure n'aboutit n'émettra **aucune donnée**, et un uplink sans ACK n'est pas un
 * ACK perdu — c'est une trame qui n'est jamais arrivée au serveur.
 */
function renderBilanProtocole() {
  const bloc = $("proto-bilan");
  const liste = $("proto-bilan-liste");
  const aide = $("proto-bilan-aide");
  clear(liste);
  const topo = state.topo;
  // Ce que le run a **réellement** simulé : demandé **et** possible au moment du lancement.
  const joinSimule = topo?.join === true && topo?.join_possible === true;
  const confSimule = topo?.confirmed === true && topo?.confirmed_possible === true;
  if (!joinSimule && !confSimule) {
    bloc.hidden = true;
    aide.textContent = "";
    return;
  }
  const { jointure, confirme } = bilanProtocole(state.events ?? []);
  if (joinSimule) {
    if (jointure.aucune) {
      // Le cas d'école, et il doit se voir comme un échec franc : tout le monde a demandé,
      // personne n'a été accepté, et le run ne porte donc aucune donnée.
      liste.append(el("li", { text: `Jointure : ${jointure.demandes} demande(s), aucune `
        + `acceptée — aucun capteur n'a joint, et ce run n'a émis aucune donnée.` }));
      aide.textContent = "Tout le monde a demandé au même instant : les join-request se sont "
        + "collisionnées. Une dispersion du départ (champ « Dispersion du départ » du capteur) "
        + "les étale, et la jointure aboutit.";
    } else {
      const plus = jointure.tentativesDeplus > 0
        ? ` (${jointure.tentativesDeplus} demande(s) de plus que de capteurs : des terminaux ont dû recommencer)` : "";
      liste.append(el("li", { text: `Jointure : ${jointure.acceptees} acceptée(s)`
        + ` pour ${jointure.demandes} demande(s)${plus}.` }));
    }
  }
  if (confSimule) {
    if (confirme.sansReponse === 0) {
      liste.append(el("li", { text: `Trames confirmées : ${confirme.acquittes} ACK `
        + `pour ${confirme.uplinks} uplink(s) — le serveur a répondu à tout ce qu'il a reçu.` }));
    } else {
      // Pas « des ACK perdus » : un ACK n'existe que pour un uplink reçu. Ce qui manque,
      // ce sont des trames qui ne sont jamais arrivées.
      liste.append(el("li", { text: `Trames confirmées : ${confirme.acquittes} ACK pour `
        + `${confirme.uplinks} uplink(s) : ${confirme.sansReponse} sans réponse — elles n'ont `
        + `pas atteint le serveur.` }));
    }
    if (aide.textContent === "") {
      aide.textContent = "Un ACK n'est émis que pour une trame reçue : l'écart compte donc des "
        + "uplinks perdus à la montée, pas des acquittements perdus en vol.";
    }
  }
  bloc.hidden = false;
}

/**
 * Le débit que le serveur a effectivement commandé, lu dans le run — pas dans le formulaire.
 *
 * Le bloc reste masqué quand le bilan est vide : sur un run sans ADR, ou quand le serveur n'a
 * encore rien commandé faute d'assez d'uplinks, il n'y a rien à montrer, et un encadré vide
 * laisserait croire que la question a été traitée et qu'elle n'a rien donné — alors que la
 * réponse est « pas de changement observé », et qu'elle mérite son propre mot.
 */
/** Écart de puissance lisible : « 14 dB », pas « 14.000000000000002 dB ».
 *  Le pas du plan vaut 2 dB et l'index est entier, mais le produit flottant ne l'est pas
 *  toujours — et un utilisateur qui lit « 13.999999 dB » doute de la mesure à tort. */
function formaterDb(valeur) {
  const arrondi = Math.round(valeur * 10) / 10;
  return `${Number.isInteger(arrondi) ? arrondi : arrondi.toFixed(1)} dB`;
}

/**
 * Le plan de canaux, en une phrase.
 *
 * « Canaux actifs 0, 1, 2 (DR0 à DR5 sur chacun) » dit deux choses qu'il ne faut pas
 * confondre : les canaux sur lesquels le terminal émet, et les débits que chacun admet.
 * Un plan divergent d'un terminal à l'autre est dit, plutôt que de publier le premier.
 */
function texteCanaux(plan) {
  if (!plan) return "";
  const parCanal = plan.parCanal
    .map(({ canal, drs }) => (drs.length === 0 ? `${canal} (aucun débit)`
      : drs.length === 1 ? `${canal} : DR${drs[0]}`
        : `${canal} : DR${drs[0]} à DR${drs[drs.length - 1]}`))
    .join(", ");
  const tete = plan.homogene
    ? `Canaux laissés au terminal : ${parCanal}.`
    : `Canaux laissés au terminal (variables selon l'équipement, premier observé) : ${parCanal}.`;
  // Un canal défini mais non activé existe sans servir : le dire, sinon le nombre de canaux
  // affichés laisserait croire à une capacité que la trame suivante n'utilisera pas.
  return `${tete} Seuls les canaux actifs servent à l'émission.`;
}

function renderAdrBilan(deviceRows = []) {
  const bloc = $("adr-bilan");
  const liste = $("adr-bilan-liste");
  const aide = $("adr-bilan-aide");
  const canauxEl = $("adr-bilan-canaux");
  clear(liste);
  const changes = bilanAdr(deviceRows, state.topo?.nodes ?? []);
  if (changes.length === 0) {
    bloc.hidden = true;
    aide.textContent = "";
    canauxEl.textContent = "";
    return;
  }
  // Le plan de canaux se lit même quand aucun débit n'a bougé : la commande qui le porte est
  // la même (LinkADRReq), et un terminal à qui le serveur n'a rien retiré garde un plan.
  canauxEl.textContent = texteCanaux(planCanaux(deviceRows));
  for (const c of changes) {
    // Les deux décisions du serveur sont nommées séparément : dire « le débit a changé »
    // quand il a aussi retiré 14 dB taît le versant autonomie de la même commande.
    const parties = [];
    if (c.debitObserve && c.depart !== c.fin) {
      const sens = c.baisse
        ? "débit plus rapide : le lien le permettait"
        : "débit plus lent : la marge de liaison était insuffisante";
      parties.push(`SF${c.depart} → SF${c.fin} — ${sens}`);
    }
    if (c.puissance && c.puissance.reductionDb !== 0) {
      const dB = Math.abs(c.puissance.reductionDb);
      const texte = c.puissance.reductionDb > 0
        ? `puissance réduite de ${formaterDb(dB)}`
        : `puissance augmentée de ${formaterDb(dB)}`;
      // Une réduction, et non « X dBm → Y dBm » : la base du calcul est la puissance du
      // dispositif, pas la PIRE du plan, et le bas de l'échelle descend sous le minimum
      // régional. Afficher des dBm absolus donnerait un chiffre qu'aucun terminal n'a émis.
      parties.push(`${texte} — elle aussi décidée par le serveur`);
    }
    liste.append(el("li", { text: `${c.nom} : ${parties.join(" ; ")}` }));
  }
  // Combien n'ont pas bougé : sans ce chiffre, trois changements sur trente passeraient
  // pour une décision générale du serveur.
  const observes = deviceRows.filter((l) => Number.isFinite(l.final_spreading_factor)).length;
  const inchanges = observes - changes.length;
  aide.textContent = inchanges > 0
    ? `${changes.length} dispositif(s) sur ${observes} observés ont changé de débit ou de `
      + `puissance. ${inchanges} sont restés à leur réglage de départ : l'ADR agit à chaque `
      + `uplink reçu, il faut plusieurs messages avant qu'une commande parte.`
    : `Les ${observes} dispositifs observés ont changé de débit ou de puissance.`;
  bloc.hidden = false;
}

// Indicateurs calculés à partir des seuls compteurs du run. Chaque bloc affiche la formule
// qui le produit : le nombre reste vérifiable à la main sur les compteurs du tableau.
/**
 * L'autonomie, à partir du courant simulé et de la capacité énoncée.
 *
 * Trois états, et ils ne se confondent pas. Sans capacité saisie : rien n'est affiché — un
 * « — » à côté d'un champ vide dirait « autonomie nulle » à qui lit vite. Capacité illisible :
 * on le dit, plutôt que de calculer sur une conversion forcée. Les deux présents : le chiffre,
 * avec de quoi le refaire.
 */
function renderAutonomie() {
  const brut = $("battery-mah").value.trim().replace(",", ".");
  const out = $("autonomie-out");
  if (!brut) {
    state.capaciteMAh = null;
    out.textContent = "";
    return;
  }
  const mAh = Number(brut);
  if (!Number.isFinite(mAh) || mAh <= 0) {
    state.capaciteMAh = null;
    out.textContent = `« ${brut} » n'est pas une capacité`;
    return;
  }
  state.capaciteMAh = mAh;
  const ans = autonomieAns(mAh, state.courantMoyenUA);
  if (ans == null) {
    out.textContent = "courant moyen non simulé";
    return;
  }
  // Même règle que pour le courant affiché : si les dispositifs ne consomment pas la même
  // chose, une autonomie unique serait celle d'un matériel qui n'existe pas. On donne
  // l'intervalle, du plus gourmand au plus sobre — et non l'inverse, la plus forte
  // consommation donnant la plus courte autonomie.
  const etale = entier(state.courantMinUA) !== entier(state.courantMaxUA);
  const duree = etale
    ? `${autonomieTexte(autonomieAns(mAh, state.courantMaxUA))} à `
      + autonomieTexte(autonomieAns(mAh, state.courantMinUA))
    : autonomieTexte(ans);
  // « pour » et non « à » : « 2 400 mAh à de 16 à 2 503 µA » se télescope.
  const courantTexte = etale
    ? `pour ${entier(state.courantMinUA)} à ${entier(state.courantMaxUA)} µA`
    : `à ${entier(state.courantMoyenUA)} µA`;
  // Les deux termes sont rappelés : une autonomie sans son courant ni sa capacité ne se
  // vérifie pas. Et la limite est dite — une pile ne rend pas ce que le calcul promet.
  out.textContent = `${duree} — ${mAh} mAh ${courantTexte}, `
    + "hors vieillissement et hors autodécharge";
}

/**
 * Le relief, et le fait qu'il puisse ne pas y en avoir.
 *
 * Le catalogue vient du serveur et il est vide la plupart du temps : aucun relief n'est
 * livré avec le dépôt. Le champ est alors masqué — un sélecteur vide serait une promesse
 * non tenue — mais le serveur ne dit pas « zéro relief disponible », il dit « zéro relief
 * dans ce catalogue ». La nuance est celle qui sépare « pas configuré » de « pas possible »,
 * et c'est le genre de distinction que l'atelier doit porter : sinon l'utilisateur conclut
 * que le simulateur ne sait pas faire, quand c'est le serveur qui n'a rien à lui donner.
 */
async function chargerTerrains() {
  if (state.terrainCharge) return;
  state.terrainCharge = true;
  const liste = await guard(() => state.client.terrains());
  if (!liste) return;                       // l'erreur est déjà affichée ; on retentera plus tard
  state.terrains = liste.items ?? [];
  renderTerrains();
}

// Le matériel proposé à l'ajout : les modèles que le moteur a déclarés, et la mention
// « celui du run » pour qui ne choisit pas. Masqué si le moteur n'en déclare aucun, et pour
// les types qui ne sont pas des capteurs — un sélecteur sans objet serait un faux choix.
function renderMaterielAjout() {
  const champ = $("add-materiel");
  const select = champ?.querySelector("select");
  if (!champ || !select) return;
  if (select.options.length) {            // déjà rempli : on ne reconstruit pas à chaque fois
    appliquerMaterielAjout();
    return;
  }
  if (!state.modelesMateriel.length) { champ.hidden = true; return; }
  clear(select);
  select.append(el("option", { value: "", text: "celui du run" }));
  for (const m of state.modelesMateriel) {
    select.append(el("option", { value: m.name, text: m.label }));
  }
  appliquerMaterielAjout();
}

function renderModeleAjout() {
  const champ = $("add-modele");
  const select = champ?.querySelector("select");
  if (!champ || !select) return;
  if (!state.modelesPasserelle.length) { champ.hidden = true; return; }
  const role = $("add-form")?.querySelector('[name="kind"]')?.value;
  // Un relais exige une radio mesh documentée : le scénario le refuse sinon, autant ne pas
  // le proposer. Et un hôte sans radio publiée n'a rien à faire dans une passerelle.
  const admis = modelesAdmis(state.modelesPasserelle, role);
  clear(select);
  select.append(el("option", { value: "", text: "référence du moteur" }));
  for (const m of admis) select.append(el("option", { value: m.name, text: m.name }));
  const garde = select.value;
  appliquerModeleAjout();
  select.value = garde;
  appliquerModeleAjout();
}

function appliquerModeleAjout() {
  const champ = $("add-modele");
  const aide = $("add-modele-aide");
  const select = champ?.querySelector("select");
  const role = $("add-form")?.querySelector('[name="kind"]')?.value;
  if (!champ || !select) return;
  const passerelle = role === "relay" || role === "border";
  champ.hidden = !passerelle || state.modelesPasserelle.length === 0;
  if (aide) {
    const m = state.modelesPasserelle.find((x) => x.name === select.value);
    // L'aide ne s'affiche que si le champ est visible : une explication orpheline décrirait
    // un réglage absent.
    aide.hidden = champ.hidden;
    aide.textContent = champ.hidden ? "" : aideModele(m);
  }
}

function appliquerMaterielAjout() {
  const champ = $("add-materiel");
  const aide = $("add-materiel-aide");
  const kind = $("add-form")?.querySelector('[name="kind"]')?.value;
  if (champ) champ.hidden = kind !== "sensor" || state.modelesMateriel.length === 0;
  if (aide) {
    // Même discipline que l'aide du modèle de passerelle : elle ne s'affiche que si le champ
    // est visible, une explication orpheline décrivant un réglage absent. Et elle se tait si
    // le moteur n'a pas annoncé de défaut, plutôt que d'inventer un nom.
    aide.hidden = Boolean(champ?.hidden);
    const defaut = state.modelesMateriel.find((m) => m.name === state.defautMateriel);
    aide.textContent = (aide.hidden || !defaut) ? "" : `« celui du run » : ${defaut.label}`;
  }
}

function renderTerrains() {
  const champ = $("terrain-field");
  const select = $("terrain-select");
  if (!champ || !select) return;
  champ.hidden = state.terrains.length === 0;
  if (!state.terrains.length) return;
  clear(select);
  select.append(el("option", { value: "", text: "aucun (sans relief)" }));
  for (const t of state.terrains) select.append(el("option", { value: t.id, text: t.id }));
  select.value = state.topo?.terrain_id ?? "";
}

async function choisirTerrain(terrainId) {
  if (!state.sid) return;
  const vide = terrainId === "" ? null : terrainId;
  const topo = await guard(() => state.client.setTerrain(state.sid, vide));
  if (!topo) return;
  state.topo = topo;
  renderTerrains();
  majHistorique();               // choisir un relief est un geste annulable, comme un autre
  setStatus(vide ? `Relief « ${vide} » appliqué aux prochains runs` : "Relief retiré");
}

/**
 * La case ADR, et surtout ce qu'elle dit quand elle ne peut pas être cochée.
 *
 * Le réglage est grisé **avec sa raison**, sur le motif de la sous-bande du §1 : « désactivé »
 * sans explication est le genre de silence qui fait perdre une heure. La raison vient du
 * serveur, qui seul connaît la topologie — la recalculer ici serait une deuxième vérité.
 *
 * Le coût est affiché en permanence, pas seulement quand l'ADR est actif : l'utilisateur doit
 * savoir avant de cocher que ce run ne simulera ni relais ni liaisons radio.
 */
/**
 * Les trois réglages qui changent la forme du run : ADR, jointure, trames confirmées.
 *
 * Ils sont rendus ensemble et de la même façon parce qu'ils obéissent à la même règle — le
 * souhait est gardé, c'est le moteur qui décide, et la raison est affichée sous la case.
 */
function renderProtocole() {
  for (const [id, cle, nom] of [["join-toggle", "join", "Jointure OTAA"],
    ["confirmed-toggle", "confirmed", "Trames confirmées"]]) {
    const case_ = $(id);
    const aide = $(id.replace("-toggle", "-aide"));
    if (!case_ || !aide) continue;
    const possible = state.topo?.[`${cle}_possible`] === true;
    const raison = state.topo?.[`${cle}_raison`] ?? "";
    case_.checked = state.topo?.[cle] === true;
    case_.disabled = !possible;
    aide.textContent = protocoleMessage({ nom, possible, raison, actif: case_.checked });
  }
}

async function basculerProtocole(join, confirmed) {
  if (!state.sid) return;
  const topo = await guard(() => state.client.setProtocole(state.sid, join, confirmed));
  if (!topo) return;
  state.topo = topo;
  renderProtocole();
  majHistorique();
  // L'ADR et la jointure s'excluent : activer l'un peut griser l'autre, donc l'ADR est
  // relu lui aussi — sans quoi sa case garderait un état que le serveur vient de changer.
  renderAdr();
  const j = protocoleStatut({ nom: "Jointure OTAA", possible: topo.join_possible === true,
    raison: topo.join_raison ?? "", actif: topo.join === true });
  const c = protocoleStatut({ nom: "Trames confirmées",
    possible: topo.confirmed_possible === true, raison: topo.confirmed_raison ?? "",
    actif: topo.confirmed === true });
  setStatus(`${j} ${c}`);
}

function renderAdr() {
  const champ = $("adr-field");
  const case_ = $("adr-toggle");
  const aide = $("adr-aide");
  if (!champ || !case_ || !aide) return;
  const possible = state.topo?.adr_possible === true;
  const raison = state.topo?.adr_raison ?? "";
  case_.checked = state.topo?.adr === true;
  case_.disabled = !possible;
  // Les libellés vivent dans `topology.js`, sans DOM, donc vérifiables hors navigateur.
  aide.textContent = adrMessage({ possible, raison, actif: case_.checked });
}

async function basculerAdr(actif) {
  if (!state.sid) return;
  const topo = await guard(() => state.client.setAdr(state.sid, actif));
  if (!topo) return;
  state.topo = topo;
  renderAdr();
  majHistorique();
  renderProtocole();
  setStatus(adrStatut({ possible: topo.adr_possible === true, raison: topo.adr_raison ?? "",
    actif: topo.adr === true }));
}

function renderMetrics(summary, deviceRows) {
  const liste = indicateursReseau(summary, deviceRows);
  const boite = $("sim-metrics-list");
  clear(boite);
  for (const i of liste) {
    boite.append(el("div", { class: "metric", title: i.hint },
      el("span", { class: "m-label", text: i.label }),
      el("span", { class: "m-value", text: i.text }),
      el("span", { class: "m-formula", text: i.hint })));
  }
  $("sim-metrics").hidden = liste.length === 0;

  // L'autonomie n'apparait que si le courant moyen a ete simule : sans lui, un champ de
  // capacite inviterait a calculer quelque chose a partir de rien.
  // La valeur est reprise de l'indicateur deja calcule, pas recalculee : deux chemins vers
  // le meme chiffre finiraient par diverger sans que rien ne le signale.
  const bloc = liste.find((i) => i.id === "courant");
  const courant = bloc?.value ?? null;
  state.courantMoyenUA = courant;
  // Les bornes voyagent avec le courant : l'autonomie se calcule sur elles quand les
  // dispositifs ne consomment pas la même chose, sans quoi elle décrirait un matériel
  // intermédiaire qui n'existe pas.
  state.courantMinUA = bloc?.min ?? courant;
  state.courantMaxUA = bloc?.max ?? courant;
  $("sim-autonomie").hidden = courant == null;
  if (courant != null) {
    const champ = $("battery-mah");
    champ.value = state.capaciteMAh ?? "";
    champ.oninput = renderAutonomie;
    renderAutonomie();
  }

  const groupes = ventilationGroupes(deviceRows, fenetreObservationNs(summary));
  const table = $("sim-groups");
  const thead = table.querySelector("thead");
  const tbody = table.querySelector("tbody");
  clear(thead);
  clear(tbody);
  const limites = limitesParGroupe(summary);
  const { entetes, lignes } = ventilationTable(groupes, limites);
  thead.append(el("tr", {}, ...entetes.map((h) => el("th", { text: h }))));
  for (const cellules of lignes) {
    tbody.append(el("tr", {}, ...cellules.map((v) => el("td", { text: String(v) }))));
  }
  // Un seul groupe : la table n'apprend rien que les totaux ne disent déjà.
  table.hidden = groupes.length < 2;

  // La source d'une limite réglementaire fait partie de la limite : sans elle, « 1 % » est
  // une opinion. On la cite une fois par région, avec la réserve sur la fenêtre de mesure —
  // un verdict sans cette réserve serait surinterprété.
  const note = $("sim-duty-note");
  clear(note);
  const sources = new Map();
  for (const d of limites.values()) if (d.source) sources.set(d.region ?? "?", d.source);
  if (sources.size) {
    for (const [region, source] of sources) {
      note.append(el("span", { class: "strong", text: `${region} — ` }),
        document.createTextNode(source + " "));
    }
    // La fenêtre réelle du run, et non la réserve générale. Dire « la fenêtre du run n'est pas
    // forcément celle du texte » laissait l'utilisateur sans moyen d'évaluer l'écart ; dire
    // « mesuré sur 6 min 40 s, quand le texte moyenne sur 1 h » le lui donne.
    note.append(el("span", { text: fenetreVerdictTexte(fenetreObservationNs(summary)) }));
    // Dire l'écart entre les deux fenêtres sans dire comment le combler laisse
    // l'utilisateur avec un constat. On nomme donc le réglage et le nombre — à 60 s il
    // faut 61 messages et non 60, détail qui ne se devine pas et coûte un run entier.
    const capteurs = (state.topo?.nodes ?? [])
      .filter((n) => n.kind === "sensor")
      .map((n) => ({ id: n.id, periodeS: n.sensor?.period_s ?? null,
        messages: n.sensor?.messages ?? null }));
    const aCouvrir = texteFenetreACouvrir(fenetreObservationNs(summary), capteurs);
    if (aCouvrir) note.append(el("span", { text: " " + aCouvrir }));
    // Un constat sans geste laisse l'utilisateur refaire à la main ce qu'on vient de
    // calculer. Le bouton ne raccourcit jamais un run déjà assez long : il ne fait que
    // porter chaque capteur au nombre de messages qui couvre l'heure.
    const aProlonger = capteurs.filter(
      (c) => Number.isFinite(c.periodeS) && c.periodeS > 0
        && Number.isFinite(c.messages) && c.messages < messagesPourFenetre(c.periodeS)
        && messagesPourFenetre(c.periodeS) <= SENSOR_LIMITS.messages[1]);
    const bouton = $("prolonger-run");
    bouton.hidden = aProlonger.length === 0;
    bouton.onclick = () => prolongerRun(aProlonger);
  }
  note.hidden = sources.size === 0;
  if (note.hidden) $("prolonger-run").hidden = true;   // pas de verdict, pas de geste
}

/**
 * Légende du taux de livraison sur la carte.
 *
 * Affichée seulement quand un run colore effectivement des équipements : une légende sans
 * résultat décrirait des couleurs absentes. Le nom de chaque palier vient de `metrics.js`,
 * seule source de l'échelle — le recopier ici le laisserait dériver de la couleur réelle.
 */
/**
 * Porter chaque capteur au nombre de messages qui couvre la fenêtre réglementaire, puis
 * relancer le run.
 *
 * Le réglage est un **remplacement complet** côté serveur (`set_sensor` recopie l'objet
 * entier) : envoyer seulement `messages` remettrait la période, la charge utile et le SF à
 * leurs défauts. On renvoie donc la configuration lue dans la topologie, avec un seul champ
 * changé.
 *
 * Le run est relancé par le formulaire lui-même, et non par un second appel : c'est le même
 * chemin que le bouton « Simuler », donc le même statut, la même attente et le même rendu.
 * Le dupliquer donnerait deux façons de simuler, donc deux façons de se contredire.
 *
 * @param {Array<{id: string, periodeS: number, messages: number}>} capteurs à prolonger
 */
async function prolongerRun(capteurs) {
  if (!state.sid || state.busy) return;
  const bouton = $("prolonger-run");
  if (bouton) bouton.disabled = true;
  try {
    for (const c of capteurs) {
      const node = state.topo?.nodes.find((n) => n.id === c.id);
      if (!node?.sensor) continue;
      const vise = messagesPourFenetre(c.periodeS);
      if (!Number.isFinite(vise)) continue;
      const topo = await guard(
        () => state.client.setSensor(state.sid, c.id, { ...node.sensor, messages: vise }));
      // La topologie revient avec le run : la garder évite de relire un état qu'on vient
      // d'écrire, et le champ `messages` affiché dans la fenêtre du capteur suit.
      if (topo) state.topo = topo;
    }
  } finally {
    if (bouton) bouton.disabled = false;
  }
  // Chaque capteur visité a écrit un réglage : l'historique a bougé d'autant.
  majHistorique();
  renderDevice();               // la fenêtre ouverte chiffre le nouveau réglage
  $("sim-form").requestSubmit();
}

function renderLegend() {
  const boite = $("pdr-legend");
  clear(boite);
  const colores = state.resultats ? [...state.resultats.values()].filter((r) => r.couleur).length : 0;
  boite.hidden = colores === 0;
  if (boite.hidden) return;
  boite.append(el("span", { class: "lg-titre", text: "Taux de livraison" }));
  for (const p of echellePdr()) {
    boite.append(el("span", { class: "lg-item" },
      el("span", { class: "lg-rond", style: `background:${p.couleur}` }),
      el("span", { text: p.label })));
  }
}

/**
 * Légende des zones de couverture, commune au plan et à la carte.
 *
 * Affichée seulement si une zone est réellement tracée : une légende sans zone décrirait
 * des couleurs absentes. Elle porte aussi le **capteur de référence** et le modèle, parce
 * qu'une zone sans eux ne veut rien dire — à 14 dBm en SF7 on ne couvre pas la même chose
 * qu'en SF12, et un disque muet laisserait croire à une portée absolue.
 */
function renderCouvertureLegend() {
  const boite = $("cov-legend");
  clear(boite);
  const zones = state.couverture?.gateways ?? [];
  const paliers = zones.flatMap((z) => z.paliers ?? []);
  boite.hidden = paliers.length === 0;
  if (boite.hidden) return;
  const c = state.couverture;
  // Le plus large d'abord, comme sur le plan : on lit du dehors vers le centre.
  const ordre = [...paliers].sort(
    (a, b) => Math.max(...(b.radii_m ?? [0])) - Math.max(...(a.radii_m ?? [0])));
  boite.append(el("span", { class: "lg-titre", text: "Couverture" }));
  for (const p of ordre) {
    boite.append(el("span", { class: "lg-item" },
      el("span", { class: "lg-rond", style: `background:${COULEURS_QUALITE[p.qualite]}` }),
      el("span", { text: etiquettePalier(p) })));
  }
  // Le capteur de référence et sa provenance : « le plus défavorable de la session » n'est
  // pas la même promesse que « celui que vous avez demandé ».
  const source = { demande: "capteur demandé", capteurs: "capteur le plus défavorable",
    defaut: "cas d'école" }[c.source] ?? c.source;
  boite.append(el("span", { class: "lg-source",
    text: `SF${c.sf} à ${c.tx_power_dbm} dBm — ${source} — ${etiquetteModele(zones[0]?.modele)}` }));
}

// --- Exercices -----------------------------------------------------------------------------
function currentExercise() {
  const meta = state.sessions.find((s) => s.session_id === state.sid);
  return meta?.exercise_id ? state.exercises.find((e) => e.id === meta.exercise_id) : null;
}

function renderExercise() {
  const ex = currentExercise();
  $("ex-title").textContent = ex ? `${ex.title} — ${ex.max_points} pts` : "Aucun exercice dans cette session.";
  $("ex-statement").textContent = ex?.statement ?? "";
  $("hint").disabled = !ex;
  $("submit").disabled = !ex;
  const hints = ex ? state.hints[ex.id] ?? [] : [];
  const list = $("ex-hints");
  clear(list);
  for (const h of hints) list.append(el("li", { text: `${h.text} (−${h.penalty} pts)` }));
  renderAttemptsFromServer();
  clear($("ex-result"));
  if (state.result && ex && state.result.exercise_id === ex.id) renderResult(state.result);
}

$("start-exercise").addEventListener("click", () => {
  const id = $("exercise-start").value;
  if (id) newSession(id);
});

$("hint").addEventListener("click", async () => {
  const ex = currentExercise();
  if (!ex) return;
  const hint = await guard(() => state.client.hint(state.sid, ex.id));
  if (!hint) return;
  (state.hints[ex.id] ??= []).push(hint);
  renderExercise();
});

$("submit").addEventListener("click", async () => {
  const ex = currentExercise();
  if (!ex) return;
  const result = await guard(() => state.client.submit(ex.id, state.sid));
  if (!result) return;
  state.result = result;
  renderExercise();
  await renderAttemptsFromServer();
});

function renderResult(result) {
  const box = $("ex-result");
  clear(box);
  box.append(el("p", { class: "strong", text: `Note : ${scoreLine(result)}` }));
  const table = el("table", {}, el("tbody"));
  for (const c of criteriaRows(result)) {
    table.querySelector("tbody").append(el("tr", {},
      el("td", { text: c.passed ? "✔" : "✘" }), el("td", { text: c.label }), el("td", { text: c.points })));
  }
  box.append(table);
}

async function renderAttemptsFromServer() {
  if (!state.sid) return;
  const list = await guard(() => state.client.attempts(state.sid));
  const ol = $("ex-attempts");
  clear(ol);
  if (!list) return;
  for (const a of list.items) {
    ol.append(el("li", { text: `#${a.number} ${a.exercise_id} : ${a.score}/${a.max_score}${a.hints_used ? ` (${a.hints_used} indice(s))` : ""}${a.passed ? " — réussi" : ""}` }));
  }
}

// --- Jeton -----------------------------------------------------------------------------------
// Le serveur ne stocke que l'empreinte des jetons : il ne peut pas restituer un jeton déjà émis.
// La saisie automatique repose donc sur un jeton émis au démarrage (option --auto-token),
// transmis soit dans la page quand le serveur sert lui-même le studio, soit par un point
// d'accès dédié. Sans cette option, la route n'existe pas (404) et le champ reste affiché.
async function resolveToken() {
  if (typeof window.LSIM_TOKEN === "string" && window.LSIM_TOKEN) return window.LSIM_TOKEN;
  try {
    // On consulte /health : il indique si le jeton automatique existe, ce qui évite de
    // déclencher un 404 attendu à chaque ouverture quand l'option n'est pas activée.
    const sante = await fetch("/api/v1/health", { headers: { Accept: "application/json" } });
    if (!sante.ok) return null;
    const info = await sante.json();
    if (!info?.auto_token) return null;
    const res = await fetch("/api/v1/auto-token", { headers: { Accept: "application/json" } });
    if (!res.ok) return null;
    const body = await res.json();
    return typeof body?.token === "string" && body.token ? body.token : null;
  } catch {
    return null;   // serveur injoignable ou sans jeton automatique : saisie manuelle
  }
}

// Le jeton étant fourni, le champ n'a plus lieu d'être montré.
function markTokenAutomatic() {
  $("token-help").hidden = true;
  const field = $("token-field");
  if (field) field.hidden = true;
  const note = $("token-note");
  if (note) { note.textContent = "Jeton fourni automatiquement par le serveur."; note.hidden = false; }
}

// --- Mode : Conception / Étude ---------------------------------------------------------------
// Les deux pans existent réellement (réseau libre d'un côté, exercices notés de l'autre).
// Aucun rôle serveur n'existe : on ne prétend donc pas restreindre des droits (voir
// docs/UI_PT_CONCEPTION.md §2.1).
// --- Origine géographique -------------------------------------------------------------------
// Le plan travaille en mètres, la carte 3D en latitude/longitude. Ce point d'ancrage est ce
// qui permet de situer les résultats du studio ; sans lui, la carte retombe sur un exemple.
const ORIGIN_KEY = "lsim-origin";

/**
 * Coordonnées de la zone, telles que saisies dans le champ unique.
 *
 * L'analyse est celle de `geo.js`, déjà éprouvée : elle accepte « 4.0511, 9.7679 »,
 * « 4,0511 9,7679 », « 4.0511° N, 9.7679° E », avec ou sans espace après la virgule. Deux
 * champs `number` séparés, comme c'était le cas, refusaient tout collage depuis une carte —
 * alors que c'est ainsi qu'on relève un lieu.
 *
 * @returns {{lat: number, lon: number} | null} null si le champ est vide ou illisible
 */
function readOrigin() {
  return lireCoordonnees($("origin-coords").value);
}

function writeOrigin(o) {
  if (!o) return;
  $("origin-coords").value = formaterCoordonnees(o.lat, o.lon);
}

/**
 * Le champ est-il dans un état qui doit retenir l'attention ?
 * Vide ou illisible, la zone est perdue : tous les équipements seraient alors ancrés
 * nulle part. On le dit au lieu de laisser un champ rouge sans explication.
 */
function refreshOriginState() {
  const etat = $("origin-state");
  if (!etat) return;
  const brut = $("origin-coords").value.trim();
  if (!brut) {
    etat.textContent = "aucune zone : cliquez sur la carte ou saisissez des coordonnées";
    etat.classList.add("bad");
    return;
  }
  const o = readOrigin();
  if (!o) {
    etat.textContent = "coordonnées illisibles : deux nombres attendus";
    etat.classList.add("bad");
    return;
  }
  const nb = state.topo?.nodes?.length ?? 0;
  etat.textContent = nb
    ? `zone ancrée ici · ${nb} équipement(s) suivent l'ancre`
    : "zone ancrée ici";
  etat.classList.remove("bad");
}
// Les coordonnées demandées sont relatives à l'origine de la zone : le dire évite de saisir
// un lieu au hasard en croyant qu'il sera converti.
function refreshAddHint() {
  const h = $("add-hint");
  if (!h) return;
  const o = readOrigin();
  h.textContent = o
    ? `Origine de la zone : ${o.lat.toFixed(6)}, ${o.lon.toFixed(6)}.`
    : "Aucune origine : cliquez d'abord sur la carte pour choisir la zone.";
}

// Le lien porte l'origine et le dernier résultat : sans eux la carte ne peut rien situer.
function refreshMapLink() {
  const q = new URLSearchParams();
  const o = readOrigin();
  if (o) { q.set("lat", String(o.lat)); q.set("lon", String(o.lon)); }
  if (state.runId) q.set("run", state.runId);
  // La session donne la position des passerelles, que les seules lignes de dispositifs
  // ne portent pas.
  if (state.sid) q.set("sid", state.sid);
  const s = q.toString();
  $("map-link").href = s ? `/index.html?${s}` : "/index.html";
}

// --- Vue carte 3D ---------------------------------------------------------------------------
// La carte est la surface de travail ; le plan 2D reste la vue métrique de secours.
function ensureMap() {
  if (state.map) return state.map;
  // Cesium exige WebGL. Un navigateur sans accélération, ou un environnement qui la refuse,
  // doit continuer à fonctionner : on retombe alors sur le plan 2D au lieu de casser.
  if (state.mapFailed) return null;
  try {
    state.map = construireCarte();
    // La carte vient d'être créée : la caméra est encore au niveau planétaire. On la
    // cadrera sur la zone au premier `syncMap`, sans quoi un équipement déposé au centre
    // de l'écran atterrirait à des milliers de kilomètres de l'origine.
    state.mapNeedsFly = true;
  } catch (err) {
    state.mapFailed = true;
    // La raison est conservée et affichée : un repli silencieux empêcherait de savoir si la
    // carte est absente par limite de l'environnement ou par défaut de notre code.
    state.mapError = err instanceof Error ? err.message : String(err);
    console.error("carte 3D indisponible :", err);
    if (state.view === "map") showView("plan");
    const note = $("map-hint");
    if (note) note.textContent =
      `Carte 3D indisponible : ${state.mapError}. Le plan 2D reste utilisable.`;
    return null;
  }
  return state.map;
}

function construireCarte() {
  return createMap3D($("cesium"), (lat, lon) => {
    // Un clic ne déplace la zone que si le geste a été armé. Déplacer l'ancre déplace **tout
    // le réseau** (décision D3) : un clic égaré, ou un clic pour simplement regarder,
    // n'a pas à produire un tel effet. Le bouton « Choisir la zone » arme le coup suivant.
    if (!state.choixZone) return;
    desarmerChoixZone();
    // Arrondi au mètre : au-delà, l'affichage donne une précision que la conversion
    // mètres ↔ degrés ne porte pas réellement à cette échelle.
    appliquerZone({ lat: Math.round(lat * 1e6) / 1e6, lon: Math.round(lon * 1e6) / 1e6 });
    const nb = state.topo?.nodes?.length ?? 0;
    if (nb) {
      // Le dire : c'est un changement lourd de conséquences, et il vient de se produire.
      const note = $("map-hint");
      if (note) note.textContent =
        `Zone déplacée — ${nb} équipement(s) ont suivi, la géométrie du réseau est conservée.`;
    }
  });
}

// --- Choisir la zone -------------------------------------------------------------------------
// Le bouton arme le clic suivant. Sans cette étape, poser un équipement ou simplement
// regarder la carte risquait de déplacer l'ancre, donc le réseau entier.

function armerChoixZone() {
  state.choixZone = true;
  $("pick-origin").classList.add("active");
  $("cesium").classList.add("choix-zone");
  const hint = $("map-hint");
  if (hint) hint.textContent = "Cliquez sur la carte à l'endroit où installer la zone — Échap pour annuler.";
  document.addEventListener("keydown", toucheChoixZone);
}

function desarmerChoixZone() {
  state.choixZone = false;
  $("pick-origin").classList.remove("active");
  $("cesium").classList.remove("choix-zone");
  document.removeEventListener("keydown", toucheChoixZone);
}

function toucheChoixZone(ev) {
  if (ev.key === "Escape") desarmerChoixZone();
}

// Aligne la carte sur l'état : origine, équipements, sélection.
function syncMap(fly = false) {
  if (state.view !== "map") return;
  const carte = ensureMap();
  if (!carte) return;            // carte indisponible : le plan 2D a pris le relais
  const o = readOrigin();
  carte.setOrigin(o);
  if (o) carte.setZone(o.lat, o.lon, porteeDesEquipements());
  carte.setNodes(state.topo?.nodes ?? [], state.selected, state.resultats);
  // Mêmes liaisons sur les deux vues : le plan les trace, la carte aussi. Elles n'existent
  // qu'après un run — la topologie d'un réseau radio se mesure, elle ne se déclare pas.
  carte.setLiaisons(state.liaisonsObservees ?? [], state.topo?.nodes ?? []);
  // Le décor réel : relief, murs, zones. Sans lui la carte montrait un réseau posé à plat
  // alors que la couverture, elle, est calculée avec le relief et les obstacles — deux
  // vérités sur le même écran. Le relief et les zones sont des allers-retours réseau :
  // on les lance ici et la carte se redessinera à l'arrivée.
  carte.setObstacles(environnement().obstacles);
  carte.setCoverage(state.couverture?.gateways ?? []);
  renderCouvertureLegend();
  chargerRelief();
  chargerCouverture();
  // Deux raisons de recadrer : l'ancre a changé, ou la carte vient d'apparaître et montre
  // encore la planète entière. La seconde compte autant que la première — c'est elle qui
  // fait que « la carte est centrée sur le lieu choisi » dès l'ouverture.
  if (fly || state.mapNeedsFly) {
    state.mapNeedsFly = false;
    carte.flyToOrigin(porteeDesEquipements());
  }
  // L'indice est réécrit à chaque synchronisation, sauf pendant un choix de zone en cours :
  // il porte alors la consigne, qu'il ne faut pas effacer sous prétexte de rafraîchir.
  if (state.choixZone) return;
  const nb = state.topo?.nodes?.length ?? 0;
  const lieu = o ? `${o.lat.toFixed(5)}, ${o.lon.toFixed(5)}` : "aucune zone";
  $("map-hint").textContent = nb === 0
    ? `Zone : ${lieu} — « Choisir la zone » pour cliquer ailleurs, ou glissez un équipement depuis la palette.`
    : `Zone : ${lieu} · glissez un équipement depuis la palette pour le poser, tirez-le pour le déplacer.`;
}

// Encombrement du réseau, en mètres : sert à cadrer la caméra.
/**
 * Le relief de la session, demandé au serveur autour de l'ancre courante.
 *
 * L'ancre est envoyée en paramètre : c'est un repère d'affichage, il vit dans le
 * navigateur et ne regarde pas le serveur. Un chantier sans relief n'est **pas** une
 * erreur — `dem: null` est un chantier à plat, et la carte doit pouvoir le distinguer
 * d'un serveur qui n'a pas répondu.
 */
async function chargerRelief() {
  const carte = state.map;
  if (!carte || !state.sid) return;
  const o = readOrigin();
  if (!o) return;                     // sans ancre, pas de découpage possible
  // Arrondi au mètre : au-delà, on redemanderait le même MNT après chaque clic alors
  // que le serveur renverrait exactement la même grille.
  const cle = `${state.sid}|${o.lat.toFixed(6)}|${o.lon.toFixed(6)}`;
  if (cle === state.reliefCle) return;
  state.reliefCle = cle;
  try {
    carte.setTerrain(await state.client.dem(state.sid, o.lat, o.lon));
  } catch (err) {
    // Un échec ici ne doit pas vider la carte : on reste à plat, et on le dit. Avalé en
    // silence, un relief absent passerait pour un relief chargé.
    state.reliefCle = null;           // réessayer au prochain passage vaut mieux que rien
    console.error("relief indisponible :", err);
    const note = $("map-hint");
    if (note) note.textContent = `Relief indisponible : ${err.message}. La carte reste plane.`;
  }
}

/**
 * Les zones de couverture des passerelles, demandées au serveur.
 *
 * Les rayons sont calculés par le moteur, relief et obstacles compris : l'atelier ne sait
 * pas faire un bilan de liaison, et une zone qu'il devinerait serait une zone fausse. La
 * clé porte ce qui change la zone — position, antenne, obstacles, shadowing — pour ne pas
 * redemander après chaque clic sans conséquence.
 */
async function chargerCouverture() {
  if (!state.sid) return;
  const noeuds = (state.topo?.nodes ?? []).filter((n) => n.kind === "gateway" || n.antenna);
  if (!noeuds.length) { state.couverture = null; return; }
  const cle = JSON.stringify([state.sid, noeuds.map((n) =>
    [n.id, n.x_m, n.y_m, n.antenna ?? null]), environnement()]);
  if (cle === state.couvertureCle) return;
  state.couvertureCle = cle;
  try {
    state.couverture = await state.client.coverage(state.sid);
    // La vue a pu changer, et la carte n'est peut-être pas encore créée : la zone attend
    // patiemment dans l'état et se redessinera au prochain passage.
    if (state.view === "map") {
      state.map?.setCoverage(state.couverture?.gateways ?? []);
    } else {
      renderPlan();
    }
    // La fenêtre d'équipement ouverte chiffre la zone : elle doit suivre, sinon elle
    // afficherait les portées d'avant le déplacement qu'on vient de faire.
    renderDevice();
  } catch (err) {
    state.couvertureCle = null;
    // Une zone refusée n'est pas un disque : on ne trace rien plutôt que n'importe quoi.
    state.couverture = null;
    if (state.view === "map") state.map?.setCoverage([]);
    else renderPlan();
    renderDevice();
    console.error("couverture indisponible :", err);
  }
}

function porteeDesEquipements() {
  const ns = state.topo?.nodes ?? [];
  if (!ns.length) return 300;
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  for (const n of ns) {
    minX = Math.min(minX, n.x_m); maxX = Math.max(maxX, n.x_m);
    minY = Math.min(minY, n.y_m); maxY = Math.max(maxY, n.y_m);
  }
  const etale = Math.max(maxX - minX, maxY - minY, 60) * 1.4;
  // La zone de couverture compte aussi : un réseau serré peut couvrir loin, et cadrer sur
  // les seuls équipements couperait la zone qu'on vient justement de tracer.
  return Math.max(etale, state.couverture ? (porteeZoneAffichee() ?? 0) : 0);
}

/** Portée de la plus grande zone affichée, depuis la carte si elle existe. */
function porteeZoneAffichee() {
  return state.map?.porteeZone?.() ?? null;
}

/**
 * Jusqu'où s'étend la vague d'un émetteur, en mètres.
 *
 * La portée de la zone du moteur si elle existe : une vague qui la franchirait démentirait
 * la zone affichée juste à côté. Sinon un dixième de l'étendue du plan, parce qu'une vague
 * sans échelle ne veut rien dire, et qu'elle ne doit pas couvrir l'écran d'un seul coup.
 */
function porteeVague(id) {
  const zone = (state.couverture?.gateways ?? []).find((z) => z.node_id === id);
  const portee = zone ? porteeMax(zone) : null;
  if (Number.isFinite(portee)) return portee;
  const b = state.bounds;
  if (!b) return null;
  return Math.max(b.maxX - b.minX, b.maxY - b.minY) * 0.1;
}

// --- Pose des équipements (phase H) -------------------------------------------------------
// Deux gestes, comme dans un atelier réseau : on tire un équipement de la palette jusqu'à la
// carte pour le créer, et on déplace un équipement existant en le tirant sur la carte.
//
// Le canevas de Cesium porte ses propres écouteurs, posés à la création de la carte donc
// avant les nôtres : un `pointerdown` sur le canevas déclencherait une rotation du globe
// avant qu'on ait pu dire « non, c'est un équipement ». On écoute donc sur le conteneur en
// phase de capture, ce qui nous atteint avant le canevas, et `stopPropagation` y coupe la
// route. C'est ce qui rend le glisser d'un équipement possible sans casser la navigation.

// Préfixes d'identifiants, par type : un nom qu'on peut lire à voix haute dans une CLI.
const PREFIXE_ID = { border: "gw", relay: "relais", sensor: "capt", server: "srv" };

/** Un identifiant libre, lisible et stable : `capt-3`, `gw-2`… */
export function suggererId(kind, pris = new Set()) {
  const base = PREFIXE_ID[kind] ?? "n";
  for (let i = 1; i <= 9999; i++) {
    const id = `${base}-${i}`;
    if (!pris.has(id)) return id;
  }
  return `${base}-${Date.now()}`;
}

/** Les identifiants déjà utilisés, pour ne pas proposer un doublon. */
function idsPris() {
  return new Set((state.topo?.nodes ?? []).map((n) => n.id));
}

/**
 * Position du curseur en pixels CSS relatifs au canevas de la carte — le repère qu'attend
 * Cesium. `null` si la carte n'a pas encore de canevas.
 */
function pointCanevas(ev) {
  const c = $("cesium").querySelector("canvas");
  if (!c) return null;
  const r = c.getBoundingClientRect();
  return { x: ev.clientX - r.left, y: ev.clientY - r.top };
}

/** Le curseur est-il au-dessus de la carte ? */
function surLaCarte(ev) {
  const r = $("cesium").getBoundingClientRect();
  return !$("cesium").hidden
    && ev.clientX >= r.left && ev.clientX <= r.right
    && ev.clientY >= r.top && ev.clientY <= r.bottom;
}

// Le repère qui suit le curseur pendant le geste : on voit où l'équipement atterrira avant
// de lâcher, au lieu de poser à l'aveugle et de corriger ensuite.
function poserFantomeDOM(kind) {
  const g = el("div", { class: "pose-ghost" }, drawDevice(kind));
  document.body.append(g);
  return g;
}
function deplacerFantomeDOM(g, ev) {
  if (g) { g.style.left = `${ev.clientX}px`; g.style.top = `${ev.clientY}px`; }
}

/**
 * Fait glisser un équipement depuis la palette. Retourne une promesse résolue avec la
 * position géographique choisie, ou `null` si le geste est abandonné.
 *
 * Le geste est suivi sur `document` : le pointeur sort forcément du bouton de la palette,
 * et le capturer sur celui-ci bloquerait les événements de la carte.
 *
 * @param {PointerEvent} ev départ
 * @param {string} kind type d'équipement
 */
function glisserDepuisPalette(ev, kind) {
  // Toutes les issues rendent le même objet : l'appelant lit `cible` sans avoir à deviner
  // si le geste a seulement avorté.
  const rien = { cible: null };
  if (ev.button !== 0) return Promise.resolve(rien);
  // Pas de `preventDefault` ici, et c'est volontaire : sur un pointeur souris, empêcher le
  // défaut du `pointerdown` peut supprimer le `click` qui suit, ce qui rendrait le bouton
  // muet. Les deux voies restent alors disjointes d'elles-mêmes — un glisser relâche sur le
  // canevas, donc le `click` vise un ancêtre commun et pas le bouton ; un simple clic
  // relâche sur le bouton et l'atteint. La sélection de texte est bloquée en CSS à la place.
  const carte = state.map;
  if (!carte || state.view !== "map") return Promise.resolve(rien);

  const fantome = poserFantomeDOM(kind);
  deplacerFantomeDOM(fantome, ev);
  document.body.classList.add("en-pose");

  return new Promise((resoudre) => {
    let cible = null;

    const bouger = (e) => {
      deplacerFantomeDOM(fantome, e);
      const p = pointCanevas(e);
      const ll = surLaCarte(e) && p ? carte.lonLatAt(p) : null;
      cible = ll;
      // Le repère sur la carte montre le point exact ; sans lui on ne sait pas si le
      // relâchement tombera sur le globe ou dans le ciel.
      if (ll) carte.showGhost(ll.lat, ll.lon, kind); else carte.clearGhost();
    };

    const finir = (e) => {
      document.removeEventListener("pointermove", bouger);
      document.removeEventListener("pointerup", finir);
      document.removeEventListener("pointercancel", annuler);
      document.removeEventListener("keydown", touche);
      fantome.remove();
      document.body.classList.remove("en-pose");
      carte.clearGhost();
      carte.setDragging(false);
      // Relâché hors de la carte, ou dans le ciel : rien n'est créé, et surtout aucun
      // clic résiduel ne doit déplacer l'origine de la zone.
      carte.setIgnoreClick(true);
      resoudre({ cible: surLaCarte(e) ? cible : null });
    };

    const annuler = () => {
      document.removeEventListener("pointermove", bouger);
      document.removeEventListener("pointerup", finir);
      document.removeEventListener("pointercancel", annuler);
      document.removeEventListener("keydown", touche);
      fantome.remove();
      document.body.classList.remove("en-pose");
      carte.clearGhost();
      carte.setDragging(false);
      resoudre({ cible: null });
    };

    // Échap abandonne le geste : sans cette issue, un clic malencontreux sur la palette
    // oblige à relâcher n'importe où en espérant ne rien créer.
    const touche = (e) => { if (e.key === "Escape") annuler(); };

    document.addEventListener("pointermove", bouger);
    document.addEventListener("pointerup", finir);
    document.addEventListener("pointercancel", annuler);
    document.addEventListener("keydown", touche);
  });
}

/**
 * Pose un équipement là où le geste s'est relâché, à la position géographique donnée.
 *
 * @param {string} kind type d'équipement
 * @param {{lat: number, lon: number}} ll point de dépôt, en degrés
 * @param {string} [modele] matériel du capteur, quand la palette en présente un. `undefined`
 *   laisse l'équipement sans modèle propre : il suivra celui du run, comme avant.
 */
async function poserEquipement(kind, ll, modele) {
  const o = readOrigin();
  if (!o || !state.sid) return;
  const { x_m, y_m } = degreesToMeters(ll.lat, ll.lon, o);
  // Même borne qu'au formulaire, pour la même raison : au-delà d'un million de mètres,
  // l'équipement sort de l'échelle du plan et devient introuvable. L'appliquer ici aussi
  // évite qu'un dépôt égaré au niveau planétaire crée un nœud à l'autre bout du monde.
  if (Math.abs(x_m) > 1_000_000 || Math.abs(y_m) > 1_000_000) {
    return showError(new Error(
      "point trop éloigné de la zone : recentrez la carte sur votre zone de test"));
  }
  const id = suggererId(kind, idsPris());
  const noeud = { id, kind, name: `${KIND_LABEL[kind]} ${id.split("-").pop()}`, x_m, y_m };
  // Le matériel posé avec le capteur, sinon rien : un capteur sans modèle propre suit celui
  // du run, ce qui reste le comportement d'avant.
  if (kind === "sensor" && modele) noeud.sensor = { energy_profile: modele };
  const topo = await guard(() => state.client.addNode(state.sid, noeud));
  if (!topo) return;
  state.topo = topo;
  state.selected = id;
  refreshViews();
  renderDevice();
  await refreshSessions();
}

/**
 * Déplace un équipement existant, en le tirant sur la carte.
 * Appelé depuis l'écouteur en capture du conteneur : l'événement n'a pas encore atteint
 * le canevas, d'où `stopPropagation` pour que Cesium n'y voie pas une rotation.
 */
function demarrerDeplacement(ev, noeud) {
  const carte = state.map;
  if (!carte) return false;
  const depart = pointCanevas(ev);
  if (!depart) return false;

  ev.stopPropagation();
  ev.preventDefault();
  carte.setDragging(true);

  let cible = null;
  const bouger = (e) => {
    const p = pointCanevas(e);
    const ll = p ? carte.lonLatAt(p) : null;
    if (!ll) return;
    cible = ll;
    carte.showGhost(ll.lat, ll.lon, noeud.kind);
  };
  const finir = async () => {
    document.removeEventListener("pointermove", bouger);
    document.removeEventListener("pointerup", finir);
    document.removeEventListener("pointercancel", finir);
    carte.clearGhost();
    carte.setDragging(false);
    carte.setIgnoreClick(true);
    if (!cible) return;
    const o = readOrigin();
    if (!o) return;
    const pos = degreesToMeters(cible.lat, cible.lon, o);
    const topo = await guard(() => state.client.moveNode(state.sid, noeud.id, pos));
    if (topo) state.topo = topo;
    refreshViews();
    renderDevice();
  };
  document.addEventListener("pointermove", bouger);
  document.addEventListener("pointerup", finir);
  document.addEventListener("pointercancel", finir);
  return true;
}

/**
 * Le panneau « Obstacles » : tracer, lister, et régler ce qui s'applique à toutes les
 * liaisons. Le formulaire n'envoie que les champs affichés — les trois sont toujours là,
 * donc les trois partent toujours, et c'est voulu : c'est ce panneau qui les possède.
 */
function wireEnvironnement() {
  const bouton = $("draw-obstacle");
  bouton?.addEventListener("click", () => toggleTraceMur());
  $("env-form")?.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    await ecrireEnvironnement({
      shadowing_sigma_db: Number($("sigma").value),
      gateway_height_m: Number($("gw-height").value),
      device_height_m: Number($("dev-height").value),
    }, "Environnement appliqué aux prochains runs");
  });
  // Quitter l'onglet pendant un tracé laisserait le plan en attente du pointeur, sans
  // sortie visible : le mode tombe dès que le panneau se masque.
  for (const t of document.querySelectorAll(".tab")) {
    t.addEventListener("click", () => {
      if (t.dataset.tab !== "environment" && state.traceMur) toggleTraceMur(false);
    });
  }
}

function showView(view) {
  state.view = view;
  const estCarte = view === "map";
  $("cesium").hidden = !estCarte;
  // Si la carte a échoué, l'indice porte la raison du repli : il doit rester lisible même
  // sur le plan, sinon on cache précisément l'information qui explique l'absence de carte.
  $("map-hint").hidden = state.mapFailed ? false : !estCarte;
  $("plan").parentElement.hidden = estCarte;
  for (const b of document.querySelectorAll(".view-tab")) {
    const actif = b.dataset.view === view;
    b.classList.toggle("active", actif);
    b.setAttribute("aria-selected", actif ? "true" : "false");
  }
  if (estCarte) {
    syncMap(true);
    // La carte n'a pas de dimensions tant qu'elle est masquée : la bascule doit la recaler.
    state.map?.resize();
  } else {
    renderPlan();
  }
}

function applyMode(mode) {
  const m = mode === "study" ? "study" : "design";
  sessionStorage.setItem("lsim-mode", m);
  $("mode-select").value = m;
  for (const b of document.querySelectorAll(".mode-card"))
    b.setAttribute("aria-pressed", String(b.dataset.mode === m));
  selectObservationTab(m === "study" ? "exercise" : "sim");
  $("status-right").textContent = m === "study" ? "Mode Étude" : "Mode Conception";
}

// --- Onglets d'observation (bas à droite) ----------------------------------------------------
function selectObservationTab(name) {
  for (const b of document.querySelectorAll(".tab"))
    b.classList.toggle("active", b.dataset.tab === name);
  for (const p of document.querySelectorAll(".tab-body"))
    p.hidden = p.dataset.panel !== name;
}

// --- Onglets de la fenêtre d'équipement ------------------------------------------------------
// L'onglet est propre à chaque fenêtre (voir syncDeviceTabs) : plus d'état global.

// --- Palette d'équipements (bas à gauche) ----------------------------------------------------
// Le dessin réel remplace l'icône CSS : la palette montre l'équipement tel qu'il apparaîtra,
// ce qui la rend reconnaissable au lieu d'obliger à lire les étiquettes.
// Les capteurs de la palette sont les matériels que le moteur déclare, et non une liste
// recopiée ici : un modèle ajouté au moteur apparaît dans la palette sans qu'on y touche.
// Liste illisible : un seul « Capteur » sans matériel — plutôt un seul choix vrai qu'une
// promesse non tenue. L'étiquette courte est l'identifiant du moteur, comme Packet Tracer
// affiche « 2911 » ; le libellé complet reste en infobulle.
function palette() {
  const capteurs = state.modelesMateriel.length
    ? state.modelesMateriel.map((m) => ({ kind: "sensor", energy_profile: m.name,
                                          label: m.name, titre: m.label }))
    : [{ kind: "sensor", label: "Capteur" }];
  return [
    { cat: "Passerelles", models: [
        { kind: "border", label: "Passerelle frontière" },
        { kind: "relay",  label: "Passerelle relais" } ] },
    { cat: "Capteurs", models: capteurs },
    { cat: "Serveur", models: [
        { kind: "server", label: "Serveur de réseau" } ] },
  ];
}

function renderPalette() {
  const cats = $("cat-box"), models = $("model-box");
  clear(cats);
  const draw = (cat, active) => {
    clear(models);
    for (const m of cat.models) {
      models.append(el("button", {
        type: "button", class: "tool",
        title: `${m.titre ?? m.label} — glissez sur la carte, ou cliquez`,
        // Le geste part du `pointerdown` : attendre le `click` interdirait de connaître la
        // position du curseur au relâchement, donc où poser l'équipement.
        onpointerdown: (ev) => demarrerDepuisPalette(ev, m),
        // Le `click` garde la voie clavier (Entrée) et le raccourci d'ajout au formulaire.
        // On l'ignore juste après un dépôt réussi, sinon un glisser créerait deux fois.
        onclick: () => {
          if (Date.now() - (state.poseRecent ?? 0) < 600) return;
          addFromPalette(m);
        },
      }, el("span", { class: "tool-art" }, drawDevice(m.kind)),
         el("span", { class: "tool-label", text: m.label })));
    }
    for (const b of cats.children) b.classList.toggle("active", b === active);
  };
  const groupes = palette();
  groupes.forEach((cat, i) => {
    cats.append(el("button", {
      type: "button", class: "tool",
      onclick: () => draw(cat, cats.children[i]),
    }, el("span", { class: "tool-art" }, drawDevice(cat.models[0].kind)),
       el("span", { class: "tool-label", text: cat.cat })));
  });
  if (cats.children.length) draw(groupes[0], cats.children[0]);
}

// Clic sur un modèle : on remplit le formulaire existant et on le soumet. Aucune logique
// d'ajout dupliquée : validateNewNode et l'API restent seuls juges.
/**
 * Part d'un bouton de la palette : le geste pose l'équipement là où on le lâche.
 *
 * Le simple clic ne passe pas par ici mais par `onclick`, resté en place pour le clavier —
 * un bouton qui ne répond qu'au pointeur devient inutilisable sans souris. Les deux voies
 * sont disjointes : le geste ne pose que s'il aboutit, et le clic ne s'ouvre que s'il ne
 * suit pas un dépôt réussi (`poseRecent`, ci-dessous).
 */
async function demarrerDepuisPalette(ev, modele) {
  const r = await glisserDepuisPalette(ev, modele.kind);
  if (!r.cible) return;
  state.poseRecent = Date.now();
  await poserEquipement(modele.kind, r.cible, modele.energy_profile);
}

function addFromPalette(modele) {
  const f = $("add-form");
  f.querySelector('[name="kind"]').value = modele.kind;
  // Le matériel du modèle choisi suit dans le formulaire : c'est lui qui porte l'ajout, et
  // le formulaire est aussi la voie clavier. Le champ vit donc ici, pas seulement dans le
  // geste de la souris.
  const materiel = f.querySelector('[name="energy_profile"]');
  if (materiel) materiel.value = modele.energy_profile ?? "";
  const id = suggererId(modele.kind, idsPris());
  f.querySelector('[name="id"]').value = id;
  // Le formulaire propose l'origine de la zone : un nouvel équipement se pose là où la
  // scène est cadrée bien plus souvent qu'ailleurs, et des champs vides obligeraient à
  // recopier des coordonnées qu'on a déjà données en choisissant la zone.
  const o = readOrigin();
  if (o && !f.querySelector('[name="lat"]').value) {
    f.querySelector('[name="lat"]').value = o.lat.toFixed(6);
    f.querySelector('[name="lon"]').value = o.lon.toFixed(6);
  }
  f.requestSubmit();
}

// --- Accessibilité clavier -------------------------------------------------------------------
// Les onglets suivent le motif ARIA « tablist » : les flèches parcourent les onglets, ce qui
// évite de tabuler à travers chacun pour atteindre le suivant.
// Motif ARIA « tablist » : les flèches parcourent les onglets, Début et Fin vont aux
// extrémités. Sans cela, un groupe annoncé comme tablist par son `role` ne tient aucune des
// promesses que ce rôle porte, et le clavier y est plus pauvre que la souris.
function wireTabs(container) {
  if (!container) return;
  container.addEventListener("keydown", (ev) => {
    const onglets = [...container.querySelectorAll('[role="tab"]')];
    const i = onglets.indexOf(document.activeElement);
    if (i < 0) return;
    let j = i;
    if (ev.key === "ArrowRight") j = (i + 1) % onglets.length;
    else if (ev.key === "ArrowLeft") j = (i - 1 + onglets.length) % onglets.length;
    else if (ev.key === "Home") j = 0;
    else if (ev.key === "End") j = onglets.length - 1;
    else return;
    ev.preventDefault();
    onglets[j].focus();
    onglets[j].click();
  });
}

// Échap ferme la fenêtre d'équipement la plus récente : raccourci attendu d'une fenêtre.
document.addEventListener("keydown", (ev) => {
  if (ev.key !== "Escape" || deviceWindows.size === 0) return;
  const cible = ev.target.closest?.(".device-win");
  const id = cible?.dataset.nodeId ?? [...deviceWindows.keys()].at(-1);
  if (id && deviceWindows.has(id)) { closeDeviceWindow(id); ev.preventDefault(); }
});

// --- Barre d'état ---------------------------------------------------------------------------
function setStatus(text) {
  $("status-left").textContent = text;
}

// --- Écran de lancement ----------------------------------------------------------------------
function closeLaunch() {
  $("launch").hidden = true;
}

// --- Démarrage -----------------------------------------------------------------------------
$("connect").addEventListener("click", connect);
$("session-select").addEventListener("change", (ev) => selectSession(ev.target.value));
$("new-session").addEventListener("click", () => newSession(null));
$("delete-session").addEventListener("click", deleteSession);
$("terrain-select").addEventListener("change", (ev) => choisirTerrain(ev.target.value));
// `change` et non `click` : la case peut aussi basculer au clavier, et c'est le changement
// d'état qu'on veut, pas le geste.
$("adr-toggle").addEventListener("change", (ev) => basculerAdr(ev.target.checked));
// Les deux cases de protocole partagent un seul appel : elles sont rendues ensemble, et
// envoyer l'une sans l'autre reviendrait à effacer le souhait de sa voisine côté serveur.
for (const id of ["join-toggle", "confirmed-toggle"]) {
  $(id).addEventListener("change", () => basculerProtocole(
    $("join-toggle").checked, $("confirmed-toggle").checked));
}
$("save-chantier").addEventListener("click", sauvegarderChantier);
$("load-chantier").addEventListener("click", () => $("chantier-file").click());
// Vider la valeur après chaque lecture : sinon recharger le même fichier une deuxième fois
// ne déclenche rien, le navigateur croyant que rien n'a changé. Le piège est connu et coûte
// « le bouton ne marche plus » à qui l'ignore.
$("chantier-file").addEventListener("change", async (ev) => {
  const fichier = ev.target.files?.[0];
  ev.target.value = "";
  if (fichier) await chargerChantier(fichier);
});

// Onglets d'observation, onglets d'équipement, fermeture de la fenêtre.
wireEnvironnement();
// Annuler / rétablir : les deux boutons, et les raccourcis. Le raccourci est ignoré dans un
// champ de saisie, où Ctrl+Z appartient à la saisie — annuler la topologie pendant qu'on
// tape une commande effacerait la commande au lieu du réseau.
$("undo").addEventListener("click", () => annulerOuRetablir("undo"));
$("redo").addEventListener("click", () => annulerOuRetablir("redo"));
document.addEventListener("keydown", (ev) => {
  if (!(ev.ctrlKey || ev.metaKey) || ev.key.toLowerCase() !== "z") return;
  const cible = ev.target;
  if (cible instanceof HTMLInputElement || cible instanceof HTMLTextAreaElement) return;
  ev.preventDefault();
  annulerOuRetablir(ev.shiftKey ? "redo" : "undo");
});
for (const b of document.querySelectorAll(".tab"))
  b.addEventListener("click", () => {
    selectObservationTab(b.dataset.tab);
    // La liste se relit à l'ouverture : un run lancé depuis une autre session, ou il y a une
    // heure, ne serait pas connu autrement.
    if (b.dataset.tab === "runs") renderRuns();
  });
wireTabs(document.querySelector(".tabs"));
// Les onglets d'équipement et la fermeture sont câblés par fenêtre (openDeviceWindow).
$("windows").addEventListener("pointerdown", (ev) => {
  const win = ev.target.closest(".device-win");
  if (!win) return;
  for (const [id, w] of deviceWindows) w.el.classList.toggle("active", w.el === win);
  state.selected = win.dataset.nodeId;
  refreshViews();
});

// Choix du mode : sur l'écran de lancement, puis dans la barre du haut.
for (const b of document.querySelectorAll(".mode-card"))
  b.addEventListener("click", () => applyMode(b.dataset.mode));
$("mode-select").addEventListener("change", (ev) => applyMode(ev.target.value));

renderPalette();

// Tirer un équipement sur la carte pour le déplacer.
//
// L'écoute est posée sur le **conteneur en phase de capture** : l'événement nous atteint
// donc avant le canevas de Cesium, dont les écouteurs ont été enregistrés à la création de
// la carte. `stopPropagation` dans `demarrerDeplacement` l'empêche alors d'y arriver, et le
// geste déplace l'équipement au lieu de faire pivoter le globe. Écouter sur le canevas lui-
// même ne marcherait pas : nos écouteurs y seraient seconds dans l'ordre d'appel.
$("cesium").addEventListener("pointerdown", (ev) => {
  if (ev.button !== 0 || state.view !== "map") return;
  const carte = state.map;
  if (!carte) return;
  const p = pointCanevas(ev);
  const noeud = p ? carte.nodeAt(p) : null;
  if (noeud) demarrerDeplacement(ev, noeud);
}, { capture: true });

for (const b of document.querySelectorAll(".view-tab")) {
  b.addEventListener("click", () => showView(b.dataset.view));
}
// Ces onglets portent role="tab" et un aria-selected tenu à jour : le motif promet donc les
// flèches. Personne ne les câblait — seul le panneau d'observation l'était.
wireTabs(document.querySelector(".views"));
applyMode(sessionStorage.getItem("lsim-mode") || "design");

// Origine géographique : relue à l'ouverture, puis suivie à chaque modification.
try {
  const o = JSON.parse(sessionStorage.getItem(ORIGIN_KEY) ?? "null");
  if (o && Number.isFinite(o.lat) && Number.isFinite(o.lon)) writeOrigin(o);
} catch { /* valeur illisible : on garde le défaut */ }
// L'ancre a bougé : les équipements gardent leur géométrie mais changent de lieu (D3).
function appliquerZone(o, { garder = true, voler = true } = {}) {
  if (!o) return;
  // Le champ d'abord : c'est la source de vérité que relit `readOrigin`. L'écrire après
  // `sessionStorage`, comme le faisait le refactor, laissait l'ancre affichée inchangée —
  // le message annonçait « zone déplacée » alors que rien n'avait bougé.
  writeOrigin(o);
  // Le MNT est découpé autour de l'ancre : elle bouge, le relief chargé n'est plus le bon.
  state.reliefCle = null;
  if (garder) sessionStorage.setItem(ORIGIN_KEY, JSON.stringify(o));
  refreshAddHint();
  refreshOriginState();
  refreshMapLink();
  syncMap(voler);
}

$("origin-coords").addEventListener("change", () => {
  const o = readOrigin();
  refreshAddHint();
  refreshOriginState();
  if (!o) return;                      // saisie illisible : on ne déplace rien
  appliquerZone(o);
});
// À la frappe aussi, pour que le message d'état suive sans attendre la sortie du champ.
$("origin-coords").addEventListener("input", refreshOriginState);

// Choisir la zone au clic : on arme le geste au lieu de laisser chaque clic déplacer l'ancre.
$("pick-origin").addEventListener("click", () => {
  if (state.choixZone) { desarmerChoixZone(); syncMap(); return; }
  // La carte doit être visible pour qu'on puisse y cliquer.
  if (state.view !== "map") showView("map");
  armerChoixZone();
});

// Recentrer : après avoir exploré la carte, revenir sur la zone sans la déplacer.
$("recenter").addEventListener("click", () => {
  const o = readOrigin();
  if (!o) return;
  if (state.view !== "map") showView("map");
  state.map?.flyToOrigin(porteeDesEquipements());
});
refreshMapLink();
refreshAddHint();
refreshOriginState();

(async () => {
  // 1. jeton déjà saisi lors d'une visite précédente
  const saved = sessionStorage.getItem("lsim-token");
  if (saved) {
    $("token").value = saved;
    await connect();
    return;
  }
  // 2. jeton fourni par le serveur (option --auto-token) : aucune saisie
  const auto = await resolveToken();
  if (auto) {
    $("token").value = auto;
    markTokenAutomatic();
    await connect();
    return;
  }
  // 3. sinon, saisie manuelle : on indique alors où trouver un jeton, sans quoi la demande
  //    est sans réponse possible.
  $("token-help").hidden = false;
  $("launch").hidden = false;
})();
