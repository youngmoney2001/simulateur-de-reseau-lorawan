// Audit clavier du studio dans un vrai navigateur.
//
// Même idée que l'audit de mise en page : remplacer un examen qu'on ne peut pas faire — ici,
// « essayer à la main avec un clavier » — par des mesures. Le navigateur connaît l'ordre de
// tabulation réel et le style calculé de l'élément focalisé : c'est donc lui qui répond, en
// nombres, aux questions qu'on se poserait en tapant.
//
// Défauts recherchés :
//   - **non atteignable** : un élément interactif visible que la tabulation n'atteint jamais ;
//   - **sans indicateur** : l'élément prend le focus, mais aucun style ne change — on tape
//     alors sans savoir où l'on est ;
//   - **focus invisible** : l'élément prend le focus alors qu'il n'est pas affiché ; le focus
//     part dans une zone que l'utilisateur ne voit pas, et la tabulation semble « sauter » ;
//   - **tablist sourde** : un groupe `role="tablist"` dont les flèches ne parcourent pas les
//     onglets, alors que le motif ARIA le promet.
//
// L'indicateur de focus est mesuré en comparant le style calculé **avant et après** le focus,
// au lieu de chercher un `outline` : un thème peut tout à fait signaler le focus par une
// bordure, un fond ou une ombre. Chercher l'outline raterait ces cas et les dirait fautifs.
import { spawn } from "node:child_process";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";
import puppeteer from "puppeteer-core";
import { rapportClavier } from "./rapport-clavier.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const webDir = join(here, "..", "..");
const repoDir = join(webDir, "..");

const python = process.env.PYTHON || "python3";
const chrome = process.env.CHROME_PATH;
if (!chrome) throw new Error("CHROME_PATH requis");
const API_PORT = 18768, WEB_PORT = 15177;
// Les ports diffèrent de ceux de l'audit de mise en page : les deux scripts ne doivent pas
// pouvoir se voler leur port s'ils tournent ensemble.
const work = mkdtempSync(join(tmpdir(), "studio-clavier-"));
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

// --- Mesures faites dans la page ------------------------------------------------------------

/** Attributs dont le changement signale « cet élément a le focus ». */
const PROPRIETES = ["outline-style", "outline-width", "outline-color", "box-shadow",
  "border-top-color", "border-bottom-color", "border-left-color", "border-right-color",
  "background-color", "color", "text-decoration-line", "filter"];

/** Ce qui peut recevoir le focus, d'après le navigateur : pas une liste écrite à la main. */
const INTERACTIFS = 'button, input, select, textarea, a[href], summary, [tabindex], [role="tab"], [role="button"]';

/** Marque chaque élément interactif d'un identifiant : les objets DOM ne traversent pas Node. */
const marquer = (sel) => {
  document.querySelectorAll(sel).forEach((e, i) => { e.dataset.kaId = String(i); });
  return document.querySelectorAll(sel).length;
};

/** Mesure l'élément focalisé : nom, rôle, visibilité, et ce que le focus change au style. */
const decrire = (props) => {
  const e = document.activeElement;
  if (!e || e === document.body || e === document.documentElement) return null;
  const s = getComputedStyle(e);
  const avant = Object.fromEntries(props.map((p) => [p, s.getPropertyValue(p)]));
  // Le style lu en entrant est déjà celui du focus. Pour savoir ce que le focus **change**,
  // il faut donc lire le style au repos, ce qui impose de retirer le focus puis de le
  // remettre : sans cet aller-retour on comparerait deux fois le même état, et tout
  // indicateur paraîtrait absent.
  e.blur();
  const repos = Object.fromEntries(props.map((p) => [p, getComputedStyle(e).getPropertyValue(p)]));
  e.focus();
  const changements = props.filter((p) => repos[p] !== avant[p]);
  const r = e.getBoundingClientRect();
  const cls = e.className && typeof e.className === "string"
    ? "." + e.className.trim().split(/\s+/).slice(0, 2).join(".") : "";
  return {
    id: e.dataset.kaId ?? "",
    quoi: e.tagName.toLowerCase() + cls + (e.id ? "#" + e.id : ""),
    role: e.getAttribute("role") || e.tagName.toLowerCase(),
    nom: (e.getAttribute("aria-label") || e.getAttribute("title") || e.getAttribute("placeholder")
      || (e.labels?.[0]?.textContent?.trim()) || e.textContent?.trim() || "")
      .replace(/\s+/g, " ").slice(0, 48),
    visible: s.display !== "none" && s.visibility !== "hidden" && r.width > 0 && r.height > 0,
    changements,
  };
};

/** Les éléments interactifs **visibles** dont l'identifiant n'a jamais été atteint. */
const nonAtteints = (sel, atteints) => {
  const vu = (e) => {
    const s = getComputedStyle(e);
    if (s.display === "none" || s.visibility === "hidden") return false;
    const r = e.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  return [...document.querySelectorAll(sel)]
    .filter((e) => vu(e) && !atteints.includes(e.dataset.kaId ?? ""))
    .map((e) => {
      const cls = e.className && typeof e.className === "string"
        ? "." + e.className.trim().split(/\s+/).slice(0, 2).join(".") : "";
      return {
        quoi: e.tagName.toLowerCase() + cls + (e.id ? "#" + e.id : ""),
        nom: (e.getAttribute("aria-label") || e.getAttribute("title") || e.textContent?.trim() || "")
          .replace(/\s+/g, " ").slice(0, 40),
      };
    });
};

let browser;
// Le rapport est rédigé hors du `try` : un audit qui s'interrompt doit publier ce qu'il a
// mesuré **et** la raison de l'interruption. Sans cela, une panne ne laisserait aucun
// rapport du tout, et l'absence de rapport se lit comme une absence de défaut — exactement
// le contresens que cet audit est fait pour éviter.
let echec = null;
const rapport = [];
let horsEtat = [];
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
    args: ["--no-sandbox", "--disable-gpu", "--enable-unsafe-swiftshader",
           "--use-gl=swiftshader", "--ignore-gpu-blocklist"] });
  const page = await browser.newPage();
  page.on("dialog", (d) => d.accept());
  await page.setViewport({ width: 1400, height: 1000 });
  await page.goto(`http://127.0.0.1:${WEB_PORT}/studio.html`, { waitUntil: "networkidle2" });

  const pause = (ms) => new Promise((r) => setTimeout(r, ms));
  const setValue = (sel, value) => page.$eval(sel, (e, v) => { e.value = v; }, value);
  const submitForm = (sel) => page.$eval(sel, (f) => f.requestSubmit());

  await page.type("#token", token);
  await page.click("#connect");
  await page.waitForFunction(() => document.querySelectorAll("#session-select option").length === 1, { timeout: 20_000 });

  // Même topologie que l'audit de mise en page : deux audits qui mesurent la même session
  // restent comparables, et un défaut trouvé par l'un se retrouve dans l'autre.
  await setValue('#add-form [name="id"]', "gw-nord");
  await submitForm("#add-form");
  await page.waitForSelector('g.node[data-id="gw-nord"]');
  for (const [id, lat, lon] of [["capteur-a", "4.051909", "9.770154"],
                                ["capteur-b", "4.054158", "9.773490"]]) {
    await setValue('#add-form [name="id"]', id);
    await page.select('#add-form [name="kind"]', "sensor");
    await setValue('#add-form [name="lat"]', lat);
    await setValue('#add-form [name="lon"]', lon);
    await submitForm("#add-form");
    await page.waitForSelector(`g.node[data-id="${id}"]`);
  }
  await pause(2500);

  // Un run, sans quoi les panneaux d'observation sont vides et l'audit déclarerait saine une
  // interface où la moitié des contrôles n'existe pas encore.
  // Le plan est la seule vue où l'on peut viser un nœud : la carte 3D est la vue par défaut,
  // et les fenêtres d'équipement s'ouvrent d'un clic sur un nœud du plan.
  await page.evaluate(() => {
    const b = [...document.querySelectorAll(".view-tab")].find((e) => e.textContent.includes("Plan"));
    if (b) b.click();
  });
  await page.waitForFunction(() => {
    const b = [...document.querySelectorAll(".view-tab")].find((e) => e.textContent.includes("Plan"));
    return b?.classList.contains("active");
  }, { timeout: 10_000 });

  await page.evaluate(() => {
    const b = [...document.querySelectorAll(".tab")].find((e) => e.textContent.includes("Simulation"));
    if (b) b.click();
  });
  // Même graine que l'audit de mise en page : deux audits qui mesurent la même session restent
  // comparables d'une tranche à l'autre.
  await page.$eval("#seed", (e) => { e.value = "7"; });
  await page.waitForFunction(() => {
    const b = document.getElementById("simulate");
    return b && !b.disabled && b.offsetParent !== null;
  }, { timeout: 20_000 });
  await page.click("#simulate");
  // Une attente qui expire sans dire ce qu'elle a lu est une panne aveugle : on ne saurait
  // pas si le run n'a pas démarré, s'il a échoué, ou s'il est simplement lent. Le statut
  // affiché est donc relu et publié avant de rendre la main.
  try {
    await page.waitForFunction(
      () => /terminé/.test(document.getElementById("sim-status")?.textContent ?? ""), { timeout: 120_000 });
  } catch (err) {
    const suivi = await page.evaluate(() => ({
      statut: document.getElementById("sim-status")?.textContent ?? "(vide)",
      bouton: document.getElementById("simulate")?.disabled ?? null,
      onglet: document.querySelector(".tab.active")?.textContent?.trim() ?? "(aucun)",
      metriques: document.querySelectorAll(".metric").length,
    }));
    console.log(`SIMULATION NON TERMINÉE : ${JSON.stringify(suivi)}`);
    throw err;
  }
  await page.waitForFunction(() => document.querySelectorAll(".metric").length >= 1, { timeout: 30_000 });
  await pause(600);

  const cliquerTexte = (selecteur, texte) => page.evaluate((sel, t) => {
    const b = [...document.querySelectorAll(sel)].find((e) => e.textContent.trim() === t);
    if (b) b.click();
    return Boolean(b);
  }, selecteur, texte);

  const etats = [
    { nom: "observation · Simulation", action: () => cliquerTexte(".tab", "Simulation") },
    { nom: "observation · Journal", action: () => cliquerTexte(".tab", "Journal") },
    { nom: "observation · Trame", action: () => cliquerTexte(".tab", "Trame") },
    { nom: "observation · Exercice", action: () => cliquerTexte(".tab", "Exercice") },
    { nom: "équipement · Physique", action: async () => {
      await page.evaluate(() => {
        document.querySelector('.device-win[data-node-id="capteur-a"] .close')?.click();
      });
      await page.click('g.node[data-id="capteur-a"] circle');
      await page.waitForSelector('.device-win[data-node-id="capteur-a"]');
      return cliquerTexte('.device-win[data-node-id="capteur-a"] .dtab', "Physique");
    } },
    { nom: "équipement · Config", action: () => cliquerTexte('.device-win[data-node-id="capteur-a"] .dtab', "Config") },
    { nom: "équipement · CLI", action: () => cliquerTexte('.device-win[data-node-id="capteur-a"] .dtab', "CLI") },
    { nom: "passerelle · Config", action: async () => {
      await page.evaluate(() => {
        document.querySelector('.device-win[data-node-id="capteur-a"] .close')?.click();
      });
      await pause(300);
      await page.click('g.node[data-id="gw-nord"] rect');
      await page.waitForSelector('.device-win[data-node-id="gw-nord"]');
      return cliquerTexte('.device-win[data-node-id="gw-nord"] .dtab', "Config");
    } },
  ];

  for (const etat of etats) {
    if (!await etat.action()) { rapport.push({ etat: etat.nom, ordre: [], problemes: [] }); continue; }
    await pause(400);
    await page.evaluate(marquer, INTERACTIFS);
    // On repart du début du document à chaque état, sinon l'ordre mesuré dépendrait de l'état
    // précédent et un même état donnerait deux rapports différents.
    await page.evaluate(() => {
      if (document.activeElement && document.activeElement !== document.body) document.activeElement.blur();
    });

    const ordre = [];
    const atteints = [];
    for (let i = 0; i < 250; i += 1) {
      // Une pression à la fois, comme le ferait un utilisateur : c'est le navigateur qui
      // décide de l'ordre, pas une liste d'éléments reconstituée.
      await page.keyboard.press("Tab");
      const info = await page.evaluate(decrire, PROPRIETES);
      if (!info) break;                                 // le focus a quitté le document
      if (info.id && atteints.includes(info.id)) break;  // cycle : on a fait le tour
      if (info.id) atteints.push(info.id);
      ordre.push({
        rang: ordre.length + 1,
        quoi: info.quoi,
        role: info.role,
        nom: info.nom,
        visible: info.visible,
        indicateur: info.changements.length > 0 ? "oui" : "non",
        par: info.changements.join(", "),
      });
    }

    const problemes = [];
    for (const o of ordre) {
      if (!o.visible) {
        problemes.push({ type: "focus invisible", quoi: o.quoi,
          detail: "prend le focus sans être affiché : la tabulation disparaît" });
      } else if (o.indicateur === "non") {
        problemes.push({ type: "sans indicateur de focus", quoi: o.quoi,
          detail: `« ${o.nom || "(sans nom)"} » prend le focus mais aucun style ne change` });
      }
    }
    // Contrôle inverse, et c'est le plus utile : un élément que la tabulation n'atteint pas
    // ne figure dans aucun ordre, donc aucun des contrôles ci-dessus ne peut le voir.
    for (const n of await page.evaluate(nonAtteints, INTERACTIFS, atteints)) {
      problemes.push({ type: "non atteignable au clavier", quoi: n.quoi,
        detail: `« ${n.nom || "(sans nom)"} » est affiché et interactif, mais absent de l'ordre` });
    }
    rapport.push({ etat: etat.nom, ordre, problemes });
  }

  // --- Les flèches sur les groupes d'onglets ------------------------------------------------
  // Le motif ARIA « tablist » promet que les flèches parcourent les onglets. `wireTabs`
  // l'implémente, mais rien ne vérifiait qu'il est branché sur **tous** les groupes.
  for (const [sel, label] of [[".tabs", ".tabs (panneau d'observation)"],
                              [".views", ".views (Carte 3D / Plan)"],
                              [".device-tabs", ".device-tabs (fenêtre d'équipement)"]]) {
    const bouge = await page.evaluate((s) => {
      const conteneur = document.querySelector(s);
      if (!conteneur) return null;                      // groupe absent de cet état : sans objet
      const onglets = [...conteneur.querySelectorAll('[role="tab"]')];
      if (onglets.length < 2) return null;
      const premier = onglets[0];
      premier.focus();
      const depart = document.activeElement;
      premier.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }));
      return document.activeElement !== depart;
    }, sel);
    if (bouge === false) {
      horsEtat.push({ type: "tablist sourde aux flèches", quoi: label,
        detail: "les onglets portent role=\"tab\" mais ArrowRight ne déplace pas le focus" });
    }
  }

} catch (err) {
  echec = err;
} finally {
  for (const c of children) { try { c.kill("SIGTERM"); } catch { /* déjà arrêté */ } }
  if (browser) await browser.close();
}

const markdown = rapportClavier({ etats: rapport, problemes: horsEtat, echec });
console.log(markdown);
const cible = new URL("../../../docs/audits/clavier.md", import.meta.url);
writeFileSync(cible, markdown);
console.log(`rapport déposé : ${fileURLToPath(cible)}`);
if (echec) {
  console.error(echec);
  process.exitCode = 1;
}
