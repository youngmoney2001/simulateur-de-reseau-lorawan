// Audit de mise en page du studio dans un vrai navigateur.
//
// Objectif : remplacer l'examen visuel, impossible depuis un poste sans affichage, par des
// mesures objectives. Le navigateur connaît la position et la taille réelles de chaque boîte :
// c'est donc lui qui répond, en nombres, aux questions qu'on se poserait à l'œil.
//
// Défauts recherchés :
//   - débordement horizontal (une boîte sort de la fenêtre) ;
//   - texte tronqué (le contenu est plus large que la boîte, et le débordement est masqué) ;
//   - contraste insuffisant entre un texte et son fond ;
//   - boîte importante réduite à rien ;
//   - zones qui se recouvrent alors qu'elles ne le devraient pas.
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
const API_PORT = 18767, WEB_PORT = 15176;
const work = mkdtempSync(join(tmpdir(), "studio-audit-"));
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
    try { const res = await fetch(url); if (res.status < 500) return; } catch { /* pas prêt */ }
    await new Promise((r) => setTimeout(r, 300));
  }
  throw new Error(`${url} injoignable`);
}

// Mesures faites dans la page : tout ce qui suit s'exécute côté navigateur.
const mesurer = () => {
  const vu = (e) => {
    const s = getComputedStyle(e);
    return s.display !== "none" && s.visibility !== "hidden" && Number(s.opacity) !== 0;
  };
  const nom = (e) => e.id ? "#" + e.id
    : e.tagName.toLowerCase() + (e.className && typeof e.className === "string"
        ? "." + e.className.trim().split(/\s+/).slice(0, 2).join(".") : "");

  // Luminance relative, formule WCAG, à partir d'une couleur « rgb(r, g, b) ».
  const lum = (couleur) => {
    const m = couleur.match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    const [r, g, b] = m[1].split(",").map(Number).slice(0, 3).map((v) => {
      const s = v / 255;
      return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  // Fond effectif : on remonte les ancêtres jusqu'à trouver une couleur opaque.
  const fondDe = (e) => {
    let n = e;
    while (n && n !== document.documentElement) {
      const c = getComputedStyle(n).backgroundColor;
      const m = c.match(/rgba?\(([^)]+)\)/);
      if (m) {
        const parts = m[1].split(",").map(Number);
        const alpha = parts.length > 3 ? parts[3] : 1;
        if (alpha > 0.5) return c;
      }
      n = n.parentElement;
    }
    return getComputedStyle(document.body).backgroundColor;
  };
  const contraste = (e) => {
    const a = lum(getComputedStyle(e).color), b = lum(fondDe(e));
    if (a === null || b === null) return null;
    const clair = Math.max(a, b), sombre = Math.min(a, b);
    return Math.round(((clair + 0.05) / (sombre + 0.05)) * 100) / 100;
  };

  const problemes = [];
  const ajouter = (type, e, detail) => {
    const r = e.getBoundingClientRect();
    problemes.push({ type, quoi: nom(e), detail,
      x: Math.round(r.x), y: Math.round(r.y), l: Math.round(r.width), h: Math.round(r.height) });
  };

  const largeur = document.documentElement.clientWidth;

  // 1. débordement horizontal
  for (const e of document.querySelectorAll("body *")) {
    if (!vu(e)) continue;
    const r = e.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    if (r.right > largeur + 1 || r.left < -1) {
      ajouter("debordement", e, `sort de ${Math.round(Math.max(r.right - largeur, -r.left))}px`);
    }
  }

  // 2. texte tronqué : contenu plus large que la boîte, débordement masqué
  for (const e of document.querySelectorAll("body *")) {
    if (!vu(e)) continue;
    if (!e.textContent || e.children.length > 0) continue;
    const s = getComputedStyle(e);
    if (s.overflowX !== "hidden" && s.overflowX !== "clip") continue;
    if (e.scrollWidth > e.clientWidth + 1) {
      ajouter("texte-tronque", e, `${e.scrollWidth}px dans ${e.clientWidth}px`);
    }
  }

  // 3. contraste des textes visibles
  for (const e of document.querySelectorAll("body *")) {
    if (!vu(e)) continue;
    if (!e.textContent || !e.textContent.trim() || e.children.length > 0) continue;
    const r = e.getBoundingClientRect();
    if (r.width < 4 || r.height < 4) continue;
    const c = contraste(e);
    if (c !== null && c < 4.5) {
      ajouter("contraste", e, `rapport ${c} (seuil 4.5)`);
    }
  }

  // 4. régions attendues présentes, visibles et dimensionnées
  const attendues = [".tool", ".plan-area", ".observation", ".statusbar", "#plan", "#session-select"];
  for (const sel of attendues) {
    const e = document.querySelector(sel);
    if (!e) { problemes.push({ type: "region-absente", quoi: sel, detail: "introuvable" }); continue; }
    if (!vu(e)) { problemes.push({ type: "region-invisible", quoi: sel, detail: "présente mais masquée" }); continue; }
    const r = e.getBoundingClientRect();
    if (r.width < 40 || r.height < 12) {
      ajouter("region-ecrasee", e, `${Math.round(r.width)}x${Math.round(r.height)}`);
    }
  }

  // 5. géométrie des grandes régions, pour référence
  const geometrie = [...document.querySelectorAll(".tool, .plan-area, .observation, .statusbar, .device-win")]
    .filter(vu).map((e) => {
      const r = e.getBoundingClientRect();
      return { quoi: nom(e), x: Math.round(r.x), y: Math.round(r.y),
        l: Math.round(r.width), h: Math.round(r.height) };
    });

  return {
    largeur,
    hauteur: document.documentElement.clientHeight,
    scrollHorizontal: document.documentElement.scrollWidth > largeur + 1,
    geometrie,
    problemes,
  };
};

let browser;
const rapport = [];
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
  page.on("dialog", (d) => d.accept());
  await page.setViewport({ width: 1400, height: 1000 });
  await page.goto(`http://127.0.0.1:${WEB_PORT}/studio.html`, { waitUntil: "networkidle2" });

  const setValue = (sel, value) => page.$eval(sel, (e, v) => { e.value = v; }, value);
  const submitForm = (sel) => page.$eval(sel, (f) => f.requestSubmit());
  const pause = (ms) => new Promise((r) => setTimeout(r, ms));

  await page.type("#token", token);
  await page.click("#connect");
  await page.waitForFunction(() => document.querySelectorAll("#session-select option").length === 1, { timeout: 20_000 });

  await setValue('#add-form [name="id"]', "gw-nord");
  await submitForm("#add-form");
  await page.waitForSelector('g.node[data-id="gw-nord"]');
  for (const [id, x, y] of [["capteur-a", "250", "90"], ["capteur-b", "620", "340"]]) {
    await setValue('#add-form [name="id"]', id);
    await page.select('#add-form [name="kind"]', "sensor");
    await setValue('#add-form [name="x_m"]', x);
    await setValue('#add-form [name="y_m"]', y);
    await submitForm("#add-form");
    await page.waitForSelector(`g.node[data-id="${id}"]`);
  }
  // La carte 3D est la vue par défaut : le plan, seul endroit où l'on peut viser un nœud,
  // doit être affiché explicitement.
  await page.evaluate(() => {
    const b = [...document.querySelectorAll(".view-tab")].find((e) => e.textContent.includes("Plan"));
    if (b) b.click();
  });
  await page.waitForFunction(() => {
    const b = [...document.querySelectorAll(".view-tab")].find((e) => e.textContent.includes("Plan"));
    return b?.classList.contains("active");
  }, { timeout: 10_000 });
  await page.click('g.node[data-id="capteur-a"] circle');
  await page.waitForSelector('.device-win[data-node-id="capteur-a"]');
  await pause(400);

  // Sans WebGL, Cesium ne peut rien peindre : le globe reste une surface unie, ce qui n'est
  // pas un défaut de l'application mais une limite de l'environnement. On le mesure pour ne
  // pas attribuer à tort un globe vide à un défaut de code.
  const webgl = await page.evaluate(() => {
    const c = document.createElement("canvas");
    const gl = c.getContext("webgl2") || c.getContext("webgl") || c.getContext("experimental-webgl");
    if (!gl) return { disponible: false };
    const infos = gl.getExtension("WEBGL_debug_renderer_info");
    return {
      disponible: true,
      rendu: infos ? gl.getParameter(infos.UNMASKED_RENDERER_WEBGL) : "inconnu",
      fournisseur: infos ? gl.getParameter(infos.UNMASKED_VENDOR_WEBGL) : "inconnu",
    };
  });
  const cesium = await page.evaluate(() => {
    const zone = document.querySelector("#cesium");
    const toile = zone?.querySelector("canvas");
    const onglet = [...document.querySelectorAll(".view-tab")].find((e) => e.classList.contains("active"));
    const indice = document.querySelector("#map-hint");
    return {
      vueActive: onglet?.textContent.trim() ?? "aucune",
      zonePresente: Boolean(zone),
      zoneVisible: zone ? !zone.hidden : false,
      toile: toile ? `${toile.width}x${toile.height}` : "aucune",
      indice: indice && !indice.hidden ? indice.textContent.replace(/\s+/g, " ").trim() : "",
    };
  });
  console.log(`WebGL : ${webgl.disponible ? "disponible" : "ABSENT"}` +
    (webgl.disponible ? ` (${webgl.fournisseur} / ${webgl.rendu})` : ""));
  console.log(`Carte 3D : vue active = ${cesium.vueActive} · zone ${cesium.zoneVisible ? "visible" : "masquée"}` +
    ` · toile = ${cesium.toile}`);
  if (cesium.indice) console.log(`Carte 3D : ${cesium.indice}`);

  for (const largeur of [1400, 1180, 900, 760]) {
    await page.setViewport({ width: largeur, height: 1000 });
    await pause(700);
    rapport.push({ largeur, ...(await page.evaluate(mesurer)) });
  }

  // Résumé lisible
  for (const bloc of rapport) {
    const p = bloc.problemes;
    console.log(`\n=== ${bloc.largeur}px · ${p.length} problème(s) · défilement horizontal : ${bloc.scrollHorizontal ? "oui" : "non"} ===`);
    console.log("géométrie :");
    for (const g of bloc.geometrie) console.log(`  ${g.quoi.padEnd(28)} x=${String(g.x).padStart(5)} y=${String(g.y).padStart(4)} ${g.l}x${g.h}`);
    const parType = {};
    for (const x of p) (parType[x.type] ??= []).push(x);
    for (const [type, liste] of Object.entries(parType)) {
      console.log(`${type} (${liste.length}) :`);
      for (const x of liste.slice(0, 12)) console.log(`  ${x.quoi.padEnd(30)} ${x.detail}`);
      if (liste.length > 12) console.log(`  … et ${liste.length - 12} autre(s)`);
    }
  }
  console.log(`\nTOTAL : ${rapport.reduce((s, b) => s + b.problemes.length, 0)} problème(s)`);
} finally {
  for (const c of children) { try { c.kill("SIGTERM"); } catch { /* déjà arrêté */ } }
  if (browser) await browser.close();
}
