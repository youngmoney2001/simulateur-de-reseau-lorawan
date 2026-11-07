// Contrôleur du studio : câble les modules purs (api, topology, console, results) au DOM.
// Tout texte venant du serveur passe par textContent : aucune donnée n'est interprétée comme HTML.
import { createClient, ApiError } from "./api.js";
import {
  KIND_LABEL, CLI_KINDS, REGIONS, SENSOR_LIMITS, planBounds, toScreen, toMeters, gridStep,
  validateNewNode, validateSensor, sensorFormFrom, nodeCaption,
} from "./topology.js";
import { createHistory, promptText } from "./console.js";
import { gatewayRows, scoreLine, criteriaRows, formatPercent, frameRows } from "./results.js";
import { collectPages, deviceGroupsFromRows, segmentsFromEvents } from "./animation.js";
import { createPlayer } from "./player.js";
// `toMeters` existe déjà dans topology.js (écran -> mètres) : on préfixe pour éviter
// toute confusion entre les deux conversions.
import { createMap3D, toMeters as degreesToMeters } from "./map3d.js";
import { drawDevice, DEVICE_SPECS } from "./device-art.js";

const W = 800, H = 520, RUN_POLL_MS = 500, RUN_TIMEOUT_MS = 120_000;
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
  events: [],        // evenements du run courant (inspecteur de trames)
  runId: null,       // dernier run reussi : la carte 3D situe ce resultat, pas un exemple
  map: null,         // carte 3D, creee au premier affichage : Cesium est volumineux
  mapFailed: false,  // WebGL refuse : on ne retente pas et le plan 2D prend le relais
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
  renderSessionChoices();
  if (state.sessions.length) await selectSession(state.sessions[0].session_id);
  else await newSession(null);
  closeLaunch();
  setStatus(state.sessions.length ? "Session chargée" : "Nouvelle session");
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
}

function renderPlan() {
  const svg = $("plan");
  clear(svg);
  const nodes = state.topo?.nodes ?? [];
  $("empty-plan").hidden = nodes.length > 0 || !state.sid;
  if (!nodes.length) return;
  const bounds = planBounds(nodes);
  state.bounds = bounds;
  svg.append(renderGrid(bounds));
  for (const n of nodes) {
    const p = toScreen(n, bounds, W, H);
    const g = svgEl("g", { class: `node${state.selected === n.id ? " selected" : ""}`, "data-id": n.id, transform: `translate(${p.x.toFixed(1)} ${p.y.toFixed(1)})` });
    // Équipements agrandis : à l'échelle précédente (9 px de rayon) un capteur était
    // quasiment invisible sur un plan de plus de mille pixels de large.
    const shape = n.kind === "sensor"
      ? svgEl("circle", { r: 15, class: "sensor" })
      : n.kind === "server" ? svgEl("rect", { x: -17, y: -17, width: 34, height: 34, transform: "rotate(45)", class: "server" })
      : svgEl("rect", { x: -18, y: -18, width: 36, height: 36, rx: 5, class: n.kind });
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
      else renderGatewayConfig(node, body);
    } else if (w.tab === "cli") {
      if (CLI_KINDS.includes(node.kind)) renderConsole(node, body);
      else body.append(el("p", { class: "no-cli", text: cliAbsentMessage(node.kind) }));
    }
  }
}

// Onglet Config des passerelles et du serveur : l'etat reel, et ou le changer.
// Il n existe pas d endpoint de configuration hors CLI : on ne pretend pas le contraire.
function renderGatewayConfig(node, body) {
  const st = stateOf(node.id);
  body.append(el("p", { class: "muted", text: `Rôle : ${KIND_LABEL[node.kind]}` }));
  body.append(el("p", { class: "muted", text: `Nom d'hôte : ${st?.hostname ?? node.id}` }));
  body.append(el("p", { class: "muted", text: `Région : ${st?.region ?? "non configurée"}` }));
  body.append(el("p", { class: "muted", text: `État : ${st?.configured ? "configuré" : "non configuré"}` }));
  if (CLI_KINDS.includes(node.kind)) {
    body.append(el("p", { class: "no-cli",
      text: "La configuration des passerelles se fait en ligne de commande, comme sur un équipement réel. Ouvrez l'onglet CLI." }));
  } else {
    body.append(el("p", { class: "no-cli", text: "Serveur de réseau : pas de configuration dans cette version." }));
  }
}

// Pourquoi cet equipement n a pas de console, au lieu de masquer l onglet.
function cliAbsentMessage(kind) {
  if (kind === "sensor") return "Un capteur ne se configure pas en ligne de commande : utilisez l'onglet Config pour ses réglages radio.";
  if (kind === "server") return "Le serveur de réseau n'expose pas de console dans cette version.";
  return "Cet équipement n'a pas de ligne de commande.";
}

// Infos seules (rafraîchies après une commande sans reconstruire la console, qui garde le focus).
// Vue physique de l'équipement : son illustration, puis le panneau de ce qu'il est
// réellement. Rien n'est avancé ici qui ne soit simulé ; les ports et voyants décrivent le
// matériel représenté, ils ne prétendent pas offrir des réglages inexistants.
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
  ligne("Position", `${node.x_m} m, ${node.y_m} m`);
  if (st) {
    ligne("Nom d'hôte", st.hostname);
    ligne("Configuration", st.configured ? "configuré" : "non configuré");
    if (st.region) ligne("Plan régional", st.region);
  }
  info.append(el("h3", { class: "phys-titre", text: "État" }), etat);

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
        refreshViews();
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
  const message = el("p", { class: "muted", text: "" });
  const form = el("form", {
    novalidate: "",   // les messages de validation sont ceux du studio, pas ceux du navigateur
    onsubmit: async (ev) => {
      ev.preventDefault();
      const raw = {};
      for (const [k, input] of Object.entries(fields)) {
        input.classList.remove("field-error");
        raw[k] = input.value;
      }
      const checked = validateSensor(raw);
      if (!checked.ok) {
        fields[checked.field]?.classList.add("field-error");
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
$("add-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  if (!state.sid) return showError(new Error("aucune session"));
  const f = new FormData(ev.target);
  const checked = validateNewNode(Object.fromEntries(f.entries()));
  if (!checked.ok) return showError(new Error(checked.message));
  const topo = await guard(() => state.client.addNode(state.sid, checked.node));
  if (topo) {
    state.topo = topo;
    state.selected = checked.node.id;
    ev.target.reset();
    refreshViews();
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
  onActive: (index) => showFrame(index),
});

// Charge les événements et la table dispositif -> capteur du run, puis prépare le lecteur.
async function loadAnimation(runId) {
  try {
    const events = await collectPages((cursor) => state.client.eventsPage(runId, cursor));
    state.events = events;
    const rows = await collectPages((cursor) => state.client.devicesPage(runId, cursor));
    const groups = deviceGroupsFromRows(rows);
    player.load({ events, segs: segmentsFromEvents(events, groups), groups });
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
}

$("sim-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  if (!state.sid || state.busy) return;
  state.busy = true;
  $("simulate").disabled = true;
  try {
    const seed = Number($("seed").value);
    const started = await guard(() => state.client.simulate(state.sid, seed));
    if (!started) return;
    clear($("sim-notes"));
    for (const note of started.notes) $("sim-notes").append(el("li", { text: note }));
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
    renderResults(summary, started.links.map((l) => l.gateway));
    await loadAnimation(started.run_id);
    $("sim-status").textContent = `Run ${started.run_id} terminé (graine ${seed}).`;
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

function renderResults(summary, linkedNames) {
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
function readOrigin() {
  const lat = Number($("origin-lat").value);
  const lon = Number($("origin-lon").value);
  return Number.isFinite(lat) && Number.isFinite(lon)
    && lat >= -90 && lat <= 90 && lon >= -180 && lon <= 180 ? { lat, lon } : null;
}
function writeOrigin(o) {
  if (!o) return;
  $("origin-lat").value = String(o.lat);
  $("origin-lon").value = String(o.lon);
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
    // Un clic pose l'origine de la zone : c'est le premier des deux moyens de la choisir.
    writeOrigin({ lat: Math.round(lat * 1e5) / 1e5, lon: Math.round(lon * 1e5) / 1e5 });
    sessionStorage.setItem(ORIGIN_KEY, JSON.stringify(readOrigin()));
    refreshMapLink();
    syncMap();
    $("map-hint").textContent =
      `Origine : ${readOrigin().lat.toFixed(5)}, ${readOrigin().lon.toFixed(5)} — cliquez à nouveau pour la déplacer.`;
  });
}

// Aligne la carte sur l'état : origine, équipements, sélection.
function syncMap(fly = false) {
  if (state.view !== "map") return;
  const carte = ensureMap();
  if (!carte) return;            // carte indisponible : le plan 2D a pris le relais
  const o = readOrigin();
  carte.setOrigin(o);
  carte.setNodes(state.topo?.nodes ?? [], state.selected);
  if (fly) carte.flyToOrigin(porteeDesEquipements());
  $("map-hint").textContent = (state.topo?.nodes?.length ?? 0) === 0
    ? "Cliquez sur la carte pour y placer l'origine de votre zone de test."
    : `Origine : ${o.lat.toFixed(5)}, ${o.lon.toFixed(5)} — cliquez pour la déplacer.`;
}

// Encombrement du réseau, en mètres : sert à cadrer la caméra.
function porteeDesEquipements() {
  const ns = state.topo?.nodes ?? [];
  if (!ns.length) return 300;
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  for (const n of ns) {
    minX = Math.min(minX, n.x_m); maxX = Math.max(maxX, n.x_m);
    minY = Math.min(minY, n.y_m); maxY = Math.max(maxY, n.y_m);
  }
  return Math.max(maxX - minX, maxY - minY, 60) * 1.4;
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
const PALETTE = [
  { cat: "Passerelles", models: [
      { kind: "border", label: "Passerelle frontière" },
      { kind: "relay",  label: "Passerelle relais" } ] },
  { cat: "Capteurs", models: [
      { kind: "sensor", label: "Capteur" } ] },
  { cat: "Serveur", models: [
      { kind: "server", label: "Serveur de réseau" } ] },
];

function renderPalette() {
  const cats = $("cat-box"), models = $("model-box");
  clear(cats);
  const draw = (cat, active) => {
    clear(models);
    for (const m of cat.models) {
      models.append(el("button", {
        type: "button", class: "tool", title: m.label,
        onclick: () => addFromPalette(m.kind),
      }, el("span", { class: "tool-art" }, drawDevice(m.kind)),
         el("span", { class: "tool-label", text: m.label })));
    }
    for (const b of cats.children) b.classList.toggle("active", b === active);
  };
  PALETTE.forEach((cat, i) => {
    cats.append(el("button", {
      type: "button", class: "tool",
      onclick: () => draw(cat, cats.children[i]),
    }, el("span", { class: "tool-art" }, drawDevice(cat.models[0].kind)),
       el("span", { class: "tool-label", text: cat.cat })));
  });
  if (cats.children.length) draw(PALETTE[0], cats.children[0]);
}

// Clic sur un modèle : on remplit le formulaire existant et on le soumet. Aucune logique
// d'ajout dupliquée : validateNewNode et l'API restent seuls juges.
function addFromPalette(kind) {
  const f = $("add-form");
  f.querySelector('[name="kind"]').value = kind;
  const id = `${kind}-${Math.random().toString(36).slice(2, 6)}`;
  f.querySelector('[name="id"]').value = id;
  f.requestSubmit();
}

// --- Accessibilité clavier -------------------------------------------------------------------
// Les onglets suivent le motif ARIA « tablist » : les flèches parcourent les onglets, ce qui
// évite de tabuler à travers chacun pour atteindre le suivant.
function wireTabs(container) {
  container.addEventListener("keydown", (ev) => {
    const sens = ev.key === "ArrowRight" ? 1 : ev.key === "ArrowLeft" ? -1 : 0;
    if (!sens) return;
    const onglets = [...container.querySelectorAll('[role="tab"]')];
    const i = onglets.indexOf(document.activeElement);
    if (i < 0) return;
    ev.preventDefault();
    const suivant = onglets[(i + sens + onglets.length) % onglets.length];
    suivant.focus();
    suivant.click();
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

// Onglets d'observation, onglets d'équipement, fermeture de la fenêtre.
for (const b of document.querySelectorAll(".tab"))
  b.addEventListener("click", () => selectObservationTab(b.dataset.tab));
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
for (const b of document.querySelectorAll(".view-tab")) {
  b.addEventListener("click", () => showView(b.dataset.view));
}
applyMode(sessionStorage.getItem("lsim-mode") || "design");

// Origine géographique : relue à l'ouverture, puis suivie à chaque modification.
try {
  const o = JSON.parse(sessionStorage.getItem(ORIGIN_KEY) ?? "null");
  if (o && Number.isFinite(o.lat) && Number.isFinite(o.lon)) writeOrigin(o);
} catch { /* valeur illisible : on garde le défaut */ }
for (const id of ["origin-lat", "origin-lon"]) {
  $(id).addEventListener("change", () => {
    const o = readOrigin();
    if (o) sessionStorage.setItem(ORIGIN_KEY, JSON.stringify(o));
    refreshMapLink();
    // L'ancre a bougé : les équipements gardent leur géométrie mais changent de lieu.
    syncMap(true);
  });
}
refreshMapLink();

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
