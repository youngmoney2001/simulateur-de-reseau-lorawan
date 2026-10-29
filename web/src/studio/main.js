// Contrôleur du studio : câble les modules purs (api, topology, console, results) au DOM.
// Tout texte venant du serveur passe par textContent : aucune donnée n'est interprétée comme HTML.
import { createClient, ApiError } from "./api.js";
import {
  KIND_LABEL, CLI_KINDS, REGIONS, SENSOR_LIMITS, planBounds, toScreen, toMeters,
  validateNewNode, validateSensor, sensorFormFrom, nodeCaption,
} from "./topology.js";
import { createHistory, promptText } from "./console.js";
import { gatewayRows, scoreLine, criteriaRows, formatPercent } from "./results.js";
import { collectPages, deviceGroupsFromRows, segmentsFromEvents } from "./animation.js";
import { createPlayer } from "./player.js";

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
  const box = $("flash");
  box.textContent = err instanceof ApiError
    ? `${err.message} (${err.code})`
    : `Erreur : ${err?.message || err}`;
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
    renderPlan();
    renderDevice();
  }
}

// --- Plan ----------------------------------------------------------------------------------
async function loadTopology() {
  if (!state.sid) return;
  const topo = await guard(() => state.client.topology(state.sid));
  if (topo) state.topo = topo;
  renderPlan();
  renderDevice();
}

function stateOf(nodeId) {
  return state.topo?.states.find((s) => s.node_id === nodeId);
}

function renderPlan() {
  const svg = $("plan");
  clear(svg);
  const nodes = state.topo?.nodes ?? [];
  $("empty-plan").hidden = nodes.length > 0 || !state.sid;
  if (!nodes.length) return;
  const bounds = planBounds(nodes);
  state.bounds = bounds;
  for (const n of nodes) {
    const p = toScreen(n, bounds, W, H);
    const g = svgEl("g", { class: `node${state.selected === n.id ? " selected" : ""}`, "data-id": n.id, transform: `translate(${p.x.toFixed(1)} ${p.y.toFixed(1)})` });
    const shape = n.kind === "sensor"
      ? svgEl("circle", { r: 9, class: "sensor" })
      : n.kind === "server" ? svgEl("rect", { x: -10, y: -10, width: 20, height: 20, transform: "rotate(45)", class: "server" })
      : svgEl("rect", { x: -11, y: -11, width: 22, height: 22, rx: 3, class: n.kind });
    g.append(shape);
    const label = svgEl("text", { x: 14, y: -10 });
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
    renderPlan();
    renderDevice();
  };
  $("plan").addEventListener("pointermove", onMove);
  $("plan").addEventListener("pointerup", onUp);
}

function selectNode(nodeId) {
  state.selected = nodeId;
  renderPlan();
  renderDevice();
}

// --- Panneau équipement --------------------------------------------------------------------
function renderDevice() {
  const body = $("device-body");
  clear(body);
  const node = state.topo?.nodes.find((n) => n.id === state.selected);
  if (!node) {
    $("device-title").textContent = "Aucun équipement sélectionné";
    return;
  }
  $("device-title").textContent = nodeCaption(node);
  body.append(el("div", { id: "device-info" }));
  renderDeviceInfo(node);
  if (CLI_KINDS.includes(node.kind)) renderConsole(node);
  if (node.kind === "sensor") renderSensorForm(node);
  if (node.kind === "server") body.append(el("p", { class: "muted", text: "Serveur de réseau : pas de configuration dans cette version." }));
  body.append(el("button", {
    type: "button", class: "danger", text: "Retirer cet équipement",
    onclick: async () => {
      if (!window.confirm(`Retirer ${node.id} ?`)) return;
      const done = await guard(() => state.client.removeNode(state.sid, node.id));
      if (done === undefined) return;
      state.selected = null;
      delete state.consoles[node.id];
      await loadTopology();
    },
  }));
}

// Infos seules (rafraîchies après une commande sans reconstruire la console, qui garde le focus).
function renderDeviceInfo(node) {
  const info = $("device-info");
  clear(info);
  const st = stateOf(node.id);
  info.append(el("p", { class: "muted", text: `${KIND_LABEL[node.kind]} · x ${node.x_m} m · y ${node.y_m} m` }));
  if (st) info.append(el("p", { class: "muted", text: `Nom d'hôte : ${st.hostname} · ${st.configured ? "configuré" : "non configuré"}${st.region ? " · " + st.region : ""}` }));
}

function renderConsole(node) {
  const body = $("device-body");
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
      // La configuration peut avoir changé (nom d'hôte, région) : on rafraîchit sans reconstruire la console.
      const fresh = await guard(() => state.client.topology(state.sid));
      if (fresh && state.selected === node.id) {
        state.topo = fresh;
        renderPlan();
        renderDeviceInfo(node);
      }
    },
  }, promptNode, input);
  input.addEventListener("keydown", (ev) => {
    if (ev.key === "ArrowUp") { input.value = c.history.up(input.value); ev.preventDefault(); }
    if (ev.key === "ArrowDown") { input.value = c.history.down(input.value); ev.preventDefault(); }
  });
  body.append(el("div", { class: "console" }, out, form));
}

function renderSensorForm(node) {
  const body = $("device-body");
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
        renderPlan();                       // le formulaire reste en place : il porte le message
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
    renderPlan();
    renderDevice();
    await refreshSessions();
  }
});

// --- Simulation ----------------------------------------------------------------------------
const player = createPlayer({
  svg: $("plan"),
  panel: $("player"),
  positionOf: (id) => {
    const node = state.topo?.nodes?.find((n) => n.id === id);
    return node && state.bounds ? toScreen(node, state.bounds, W, H) : null;
  },
});

// Charge les événements et la table dispositif -> capteur du run, puis prépare le lecteur.
async function loadAnimation(runId) {
  try {
    const events = await collectPages((cursor) => state.client.eventsPage(runId, cursor));
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

// --- Démarrage -----------------------------------------------------------------------------
$("connect").addEventListener("click", connect);
$("session-select").addEventListener("change", (ev) => selectSession(ev.target.value));
$("new-session").addEventListener("click", () => newSession(null));
$("delete-session").addEventListener("click", deleteSession);

const saved = sessionStorage.getItem("lsim-token");
if (saved) {
  $("token").value = saved;
  connect();
}
