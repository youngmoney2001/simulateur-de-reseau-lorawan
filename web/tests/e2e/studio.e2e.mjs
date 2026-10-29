// Test de bout en bout du studio dans un vrai navigateur, contre le vrai serveur API.
// Prérequis : CHROME_PATH (binaire Chromium), LSIM_LIBRARY (bibliothèque native), PYTHON (interpréteur
// avec lsim importable via PYTHONPATH=python/). Lancer : `npm run test:e2e` depuis web/.
import { spawn } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";
import puppeteer from "puppeteer-core";

const here = dirname(fileURLToPath(import.meta.url));
const webDir = join(here, "..", "..");
const repoDir = join(webDir, "..");
const python = process.env.PYTHON || "python3";
const chrome = process.env.CHROME_PATH;
if (!chrome) throw new Error("CHROME_PATH requis");
const API_PORT = 18765, WEB_PORT = 15174;
const work = mkdtempSync(join(tmpdir(), "studio-e2e-"));
const tokens = join(work, "tokens.json");
const env = { ...process.env, PYTHONPATH: join(repoDir, "python") };

const token = execFileSync(python, ["-m", "lsim.api_server", "issue-token", "--tokens", tokens, "--owner", "alice"],
  { env, encoding: "utf8" }).trim();

const children = [];
function start(name, cmd, args, cwd, extraEnv = {}) {
  const child = spawn(cmd, args, { cwd, env: { ...env, ...extraEnv }, stdio: ["ignore", "pipe", "pipe"] });
  child.stderrLog = "";
  child.stderr.on("data", (d) => { child.stderrLog += d; });
  children.push(child);
  child.name = name;
  return child;
}
async function waitHttp(url, child, timeoutMs = 60_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) throw new Error(`${child.name} a quitté : ${child.stderrLog.slice(-800)}`);
    try {
      const res = await fetch(url);
      if (res.status < 500) return;
    } catch { /* pas encore prêt */ }
    await new Promise((r) => setTimeout(r, 300));
  }
  throw new Error(`${url} injoignable`);
}

let browser;
let failed = false;
try {
  const api = start("API", python, ["-m", "lsim.api_server", "serve", "--tokens", tokens,
    "--runs-db", join(work, "runs.sqlite"), "--port", String(API_PORT)], repoDir);
  await waitHttp(`http://127.0.0.1:${API_PORT}/api/v1/regions`, api);
  const vite = start("Studio", process.execPath, [join(webDir, "node_modules", "vite", "bin", "vite.js"),
    "--port", String(WEB_PORT), "--strictPort"], webDir, { LSIM_API_URL: `http://127.0.0.1:${API_PORT}` });
  await waitHttp(`http://127.0.0.1:${WEB_PORT}/studio.html`, vite);

  browser = await puppeteer.launch({ executablePath: chrome, headless: true,
    args: ["--no-sandbox", "--disable-gpu", "--no-zygote", "--single-process"] });
  const page = await browser.newPage();
  await page.setViewport({ width: 1400, height: 1000 });
  const pageErrors = [];
  page.on("pageerror", (e) => { pageErrors.push(e.message); console.error("pageerror:", e.message); });
  page.on("console", (m) => { if (m.type() === "error") console.error("console:", m.text()); });
  page.on("dialog", (d) => d.accept());
  await page.goto(`http://127.0.0.1:${WEB_PORT}/studio.html`, { waitUntil: "domcontentloaded" });

  const steps = [];
  const step = async (name, fn) => {
    try {
      await fn();
      steps.push(`ok   ${name}`);
    } catch (err) {
      steps.push(`FAIL ${name} : ${err.message}`);
      throw err;
    }
  };
  const textOf = (sel) => page.$eval(sel, (e) => e.textContent);
  const waitText = (sel, re, timeout = 20_000) => page.waitForFunction(
    (s, src) => new RegExp(src).test(document.querySelector(s)?.textContent ?? ""),
    { timeout }, sel, re.source);
  const setValue = (sel, value) => page.$eval(sel, (e, v) => { e.value = v; }, value);
  const submitForm = (sel) => page.$eval(sel, (f) => f.requestSubmit());

  await step("connexion et session créée automatiquement", async () => {
    await page.type("#token", token);
    await page.click("#connect");
    await page.waitForFunction(() => document.querySelectorAll("#session-select option").length === 1, { timeout: 20_000 });
  });

  await step("ajout d'une passerelle frontière et d'un capteur", async () => {
    await setValue('#add-form [name="id"]', "gw-nord");
    await setValue('#add-form [name="name"]', "Passerelle nord");
    await submitForm("#add-form");
    await page.waitForSelector('g.node[data-id="gw-nord"]');
    await setValue('#add-form [name="id"]', "capt-1");
    await page.select('#add-form [name="kind"]', "sensor");
    await setValue('#add-form [name="x_m"]', "300");
    await setValue('#add-form [name="y_m"]', "100");
    await submitForm("#add-form");
    await page.waitForSelector('g.node[data-id="capt-1"]');
  });

  await step("identifiant invalide refusé côté studio", async () => {
    await setValue('#add-form [name="id"]', "Gw Bad");
    await submitForm("#add-form");
    await waitText("#flash", /identifiant/);
  });

  await step("console : configuration CLI et erreur de syntaxe au caret", async () => {
    await page.click('g.node[data-id="gw-nord"] rect');
    await page.waitForSelector("#device-body .console input");
    const send = async (cmd) => {
      await page.click("#device-body .console input");
      await page.type("#device-body .console input", cmd);
      await page.keyboard.press("Enter");
      await page.waitForFunction((c) => !document.querySelector("#device-body .console input").value && (document.querySelector("#device-body .console pre").textContent.includes(c)), { timeout: 20_000 }, cmd);
    };
    await send("enable");
    await send("configure terminal");
    await send("hostname frontiere-nord");
    await send("end");
    await waitText("#device-body", /frontiere-nord/);
    await send("commande-inconnue");
    await page.waitForFunction(() => document.querySelector("#device-body .console pre").textContent.includes("^"), { timeout: 20_000 });
    await page.click("#device-body .console input");
    await page.keyboard.press("ArrowUp");
    const recalled = await page.$eval("#device-body .console input", (i) => i.value);
    if (recalled !== "commande-inconnue") throw new Error(`historique : ${recalled}`);
    await page.$eval("#device-body .console input", (i) => { i.value = ""; });
  });

  await step("capteur : refus d'un SF hors bornes au studio, puis enregistrement", async () => {
    await page.click('g.node[data-id="capt-1"] circle');
    await page.waitForSelector('#device-body .sensor-form input[name="spreading_factor"]');
    await setValue('#device-body .sensor-form input[name="spreading_factor"]', "13");
    await submitForm("#device-body form");
    await waitText("#device-body form", /spreading_factor/);
    await setValue('#device-body .sensor-form input[name="spreading_factor"]', "9");
    await setValue('#device-body .sensor-form input[name="messages"]', "2");
    await submitForm("#device-body form");
    await waitText("#device-body form", /enregistrés/);
  });

  await step("glisser-déposer : la position est enregistrée côté API", async () => {
    const box = await (await page.$('g.node[data-id="capt-1"] circle')).boundingBox();
    const x = box.x + box.width / 2, y = box.y + box.height / 2;
    await page.mouse.move(x, y);
    await page.mouse.down();
    await page.mouse.move(x - 60, y + 30, { steps: 8 });
    await page.mouse.move(x - 120, y + 60, { steps: 8 });
    await page.mouse.up();
    await new Promise((r) => setTimeout(r, 800));
    const sid = await page.$eval("#session-select", (s) => s.value);
    const res = await fetch(`http://127.0.0.1:${API_PORT}/api/v1/sessions/${sid}/topology`,
      { headers: { Authorization: `Bearer ${token}` } });
    const topo = await res.json();
    const capt = topo.nodes.find((n) => n.id === "capt-1");
    if (capt.x_m === 300 && capt.y_m === 100) throw new Error("position inchangée côté API");
  });

  await step("simulation : run terminé, résultats par passerelle", async () => {
    await setValue("#seed", "7");
    await page.click("#simulate");
    await waitText("#sim-status", /terminé/, 120_000);
    await page.waitForFunction(() => document.querySelectorAll("#sim-results tbody tr").length >= 1);
    const rows = await page.$$eval("#sim-results tbody tr", (trs) => trs.map((t) => t.textContent));
    if (!rows.some((r) => r.includes("frontiere-nord") || r.includes("gw-nord"))) throw new Error(rows.join(" | "));
  });

  await step("animation : lecteur chargé, horloge avance, trames dessinées, journal", async () => {
    await page.waitForFunction(() => !document.getElementById("player").hidden, { timeout: 60_000 });
    await page.waitForFunction(() => document.querySelectorAll("#journal > li").length >= 1);
    const before = await page.$eval("#play-time", (n) => n.textContent);
    await page.evaluate(() => document.getElementById("play-speed").value = "300");
    await page.evaluate(() => document.getElementById("play-speed").dispatchEvent(new Event("change")));
    await page.click("#play-toggle");
    await new Promise((r) => setTimeout(r, 800));
    await page.click("#play-toggle");
    const after = await page.$eval("#play-time", (n) => n.textContent);
    if (before === after) throw new Error(`horloge figée : ${before}`);
    // Le plan porte une couche d'animation (trames ou anneaux) dès qu'un événement est actif.
    // Parcours de l'horloge : au moins une trame (ou un anneau) doit être dessinée sur le plan.
    const drawn = await page.evaluate(() => {
      const slider = document.getElementById("play-clock");
      let max = 0;
      for (let v = 0; v <= 1000; v += 20) {
        slider.value = String(v);
        slider.dispatchEvent(new Event("input"));
        const n = document.querySelectorAll("#anim-layer > *").length;
        if (n > max) max = n;
      }
      return max;
    });
    if (drawn < 1) throw new Error("aucune trame dessinée sur le plan pendant la simulation");
  });

  await step("exercice : démarrage, indice avec pénalité, notation, journal", async () => {
    await page.select("#exercise-start", "eu868-passerelle");
    await page.click("#start-exercise");
    await waitText("#ex-title", /eu868|EU868|passerelle/i);
    await page.waitForFunction(() => document.getElementById("hint").disabled === false);
    await page.click("#hint");
    await waitText("#ex-hints", /−2 pts/);
    await page.click("#submit");
    await waitText("#ex-result", /Note :/);
    await waitText("#ex-attempts", /#1 /);
  });

  await step("suppression de la session", async () => {
    const before = await page.$$eval("#session-select option", (o) => o.length);
    await page.click("#delete-session");
    await page.waitForFunction((n) => document.querySelectorAll("#session-select option").length < n, { timeout: 20_000 }, before);
  });

  if (pageErrors.length) steps.push(`pageerror : ${pageErrors.join(" | ")}`);
  console.log(steps.join("\n"));
  if (pageErrors.length) throw new Error("erreurs de page");
  console.log("E2E STUDIO OK");
} catch (err) {
  failed = true;
  console.error(err);
  for (const c of children) console.error(`--- ${c.name} stderr ---\n${c.stderrLog.slice(-1500)}`);
} finally {
  if (browser) await browser.close();
  for (const c of children) c.kill("SIGTERM");
}
process.exit(failed ? 1 : 0);
