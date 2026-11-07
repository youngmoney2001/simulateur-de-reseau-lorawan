// Capture d'écrans du studio dans un vrai navigateur, pour examiner le rendu réel.
// Mêmes prérequis que studio.e2e.mjs : CHROME_PATH, PYTHON (avec PYTHONPATH=python/).
// Les images sont écrites dans captures/ à la racine du dépôt.
import { spawn } from "node:child_process";
import { mkdtempSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";
import puppeteer from "puppeteer-core";

const here = dirname(fileURLToPath(import.meta.url));
const webDir = join(here, "..", "..");
const repoDir = join(webDir, "..");
const outDir = join(repoDir, "captures");
mkdirSync(outDir, { recursive: true });

const python = process.env.PYTHON || "python3";
const chrome = process.env.CHROME_PATH;
if (!chrome) throw new Error("CHROME_PATH requis");
const API_PORT = 18766, WEB_PORT = 15175;
const work = mkdtempSync(join(tmpdir(), "studio-capture-"));
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
try {
  const api = start("API", python, ["-m", "lsim.api_server", "serve", "--tokens", tokens,
    "--runs-db", join(work, "runs.sqlite"), "--port", String(API_PORT)], repoDir);
  await waitHttp(`http://127.0.0.1:${API_PORT}/api/v1/regions`, api);
  const vite = start("Studio", process.execPath, [join(webDir, "node_modules", "vite", "bin", "vite.js"),
    "--port", String(WEB_PORT), "--strictPort"], webDir, { LSIM_API_URL: `http://127.0.0.1:${API_PORT}` });
  await waitHttp(`http://127.0.0.1:${WEB_PORT}/studio.html`, vite);

  browser = await puppeteer.launch({ executablePath: chrome, headless: true,
    // WebGL logiciel : sans lui Cesium ne peut pas créer son contexte, et le studio
    // retomberait sur le plan 2D sans que ce soit un défaut de l'application.
    // Ni --single-process ni --no-zygote : Cesium lance des web workers pour charger ses
    // tuiles, et ces deux options les empêchent de démarrer, ce qui fait échouer
    // l'initialisation du Viewer.
    args: ["--no-sandbox", "--disable-gpu", "--enable-unsafe-swiftshader",
           "--use-gl=swiftshader", "--ignore-gpu-blocklist"] });
  const page = await browser.newPage();
  await page.setViewport({ width: 1400, height: 1000 });
  page.on("dialog", (d) => d.accept());
  await page.goto(`http://127.0.0.1:${WEB_PORT}/studio.html`, { waitUntil: "networkidle2" });

  let n = 0;
  const shoot = async (nom) => {
    n += 1;
    const fichier = join(outDir, `${String(n).padStart(2, "0")}-${nom}.png`);
    await page.screenshot({ path: fichier });
    console.log(`capture ${fichier}`);
  };
  const setValue = (sel, value) => page.$eval(sel, (e, v) => { e.value = v; }, value);
  const submitForm = (sel) => page.$eval(sel, (f) => f.requestSubmit());
  const clickTab = async (sel, label) => {
    await page.evaluate((s, txt) => {
      const b = [...document.querySelectorAll(s)].find((e) => e.textContent.includes(txt));
      if (!b) throw new Error(`onglet introuvable : ${txt}`);
      b.click();
    }, sel, label);
  };
  const deviceTab = (label, nodeId) => clickTab(`.device-win[data-node-id="${nodeId}"] .dtab`, label);
  const obsTab = (label) => clickTab(".tab", label);
  const viewTab = async (libelle) => {
    await page.evaluate((txt) => {
      const b = [...document.querySelectorAll(".view-tab")].find((e) => e.textContent.includes(txt));
      if (!b) throw new Error(`vue introuvable : ${txt}`);
      b.click();
    }, libelle);
    await page.waitForFunction((txt) => {
      const b = [...document.querySelectorAll(".view-tab")].find((e) => e.textContent.includes(txt));
      return b?.classList.contains("active");
    }, { timeout: 10_000 }, libelle);
  };
  const pause = (ms) => new Promise((r) => setTimeout(r, ms));

  // 1. écran d'accueil : choix du mode, avant toute connexion
  await shoot("accueil-modes");

  await page.type("#token", token);
  await page.click("#connect");
  await page.waitForFunction(() => document.querySelectorAll("#session-select option").length === 1, { timeout: 20_000 });
  await pause(400);
  await shoot("studio-vide");

  // 2. une topologie réaliste : une passerelle, trois capteurs
  await setValue('#add-form [name="id"]', "gw-nord");
  await setValue('#add-form [name="name"]', "Passerelle nord");
  await submitForm("#add-form");
  await page.waitForSelector('g.node[data-id="gw-nord"]');
  for (const [id, x, y] of [["capteur-a", "250", "90"], ["capteur-b", "620", "340"], ["capteur-c", "180", "430"]]) {
    await setValue('#add-form [name="id"]', id);
    await page.select('#add-form [name="kind"]', "sensor");
    await setValue('#add-form [name="x_m"]', x);
    await setValue('#add-form [name="y_m"]', y);
    await submitForm("#add-form");
    await page.waitForSelector(`g.node[data-id="${id}"]`);
  }
  await pause(3200);
  await shoot("carte-3d");

  // 3. fenêtre d'équipement : les trois onglets, sur le plan qui permet de viser un nœud
  await viewTab("Plan");
  await pause(400);
  await shoot("studio-topologie");
  await page.click('g.node[data-id="capteur-a"] circle');
  await page.waitForSelector('.device-win[data-node-id="capteur-a"]');
  await pause(300);
  await shoot("equipement-physique");

  await deviceTab("Config", "capteur-a");
  await page.waitForSelector('.device-win[data-node-id="capteur-a"] .sensor-form');
  await pause(300);
  await shoot("equipement-config");

  await deviceTab("CLI", "capteur-a");
  await pause(300);
  await shoot("equipement-cli");

  // 4. une session de ligne de commande remplie, sur la passerelle
  await viewTab("Plan");
  await page.click('g.node[data-id="gw-nord"] rect');
  await page.waitForSelector('.device-win[data-node-id="gw-nord"]');
  await deviceTab("CLI", "gw-nord");
  await page.waitForSelector('.device-win[data-node-id="gw-nord"] .console input');
  for (const cmd of ["enable", "configure terminal", "hostname frontiere-nord", "end", "commande-inconnue"]) {
    await page.type('.device-win[data-node-id="gw-nord"] .console input', cmd);
    await page.keyboard.press("Enter");
    await pause(600);
  }
  await pause(400);
  await shoot("console-cli");

  // 5. observation : simulation, puis exercice
  await obsTab("Simulation");
  await page.click("#simulate");
  await page.waitForSelector("#sim-results:not([hidden])", { timeout: 60_000 });
  await pause(900);
  await shoot("observation-simulation");

  await obsTab("Journal");
  await page.waitForSelector("#journal li", { timeout: 30_000 });
  await pause(500);
  await shoot("observation-journal");

  await obsTab("Trame");
  await pause(400);
  await shoot("observation-trame");

  await obsTab("Exercice");
  await page.waitForSelector("#ex-title");
  await pause(500);
  await shoot("observation-exercice");

  // 6. paliers étroits : la disposition doit tenir
  await page.setViewport({ width: 900, height: 1000 });
  await pause(600);
  await shoot("etroit-900");
  await page.setViewport({ width: 760, height: 1000 });
  await pause(600);
  await shoot("etroit-760");

  console.log(`${n} captures dans ${outDir}`);
} finally {
  for (const c of children) { try { c.kill("SIGTERM"); } catch { /* déjà arrêté */ } }
  if (browser) await browser.close();
}
