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
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";
import puppeteer from "puppeteer-core";
import { rapportMarkdown } from "./rapport-audit.mjs";

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
  const nom = (e) => {
    const cls = e.className && typeof e.className === "string"
      ? "." + e.className.trim().split(/\s+/).slice(0, 2).join(".") : "";
    return e.tagName.toLowerCase() + cls + (e.id ? "#" + e.id : "");
  };
  // Un élément sans classe ni identifiant est introuvable dans le code : on remonte alors
  // ses ancêtres. C'est le cas des nœuds injectés par Cesium, dont on ne connaît pas la
  // provenance sans ce chemin.
  const chemin = (e) => {
    const bouts = [];
    let n = e;
    while (n && n !== document.body && bouts.length < 4) {
      bouts.unshift(nom(n));
      n = n.parentElement;
    }
    return bouts.join(" > ");
  };

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

  // 4. contenu inaccessible : plus grand que sa boîte, avec un débordement masqué.
  //    C'est la classe de défaut qui manquait et qui a laissé passer trois fois la hauteur
  //    du panneau d'observation dans un panneau de 224 px : rien ne débordait en largeur,
  //    rien n'était tronqué, le rapport sortait vierge. Un contenu que l'utilisateur ne
  //    peut ni voir ni atteindre est un défaut certain — pas une question de goût.
  for (const e of document.querySelectorAll("body *")) {
    if (!vu(e)) continue;
    const s = getComputedStyle(e);
    const masqueY = s.overflowY === "hidden" || s.overflowY === "clip";
    const defileX = s.overflowX === "auto" || s.overflowX === "scroll";
    if (masqueY && e.scrollHeight > e.clientHeight + 1) {
      ajouter("contenu-inaccessible", e,
        `${e.scrollHeight}px de haut dans ${e.clientHeight}px, débordement vertical masqué`);
    }
    // En largeur, un défilement est un choix acceptable : seul le masque est un défaut.
    if (!defileX && (s.overflowX === "hidden" || s.overflowX === "clip")
        && e.scrollWidth > e.clientWidth + 1) {
      ajouter("contenu-inaccessible", e,
        `${e.scrollWidth}px de large dans ${e.clientWidth}px, débordement horizontal masqué`);
    }
  }

  // 5. cibles trop petites : l'atelier se pilote à la souris et au doigt (glisser-déposer,
  //    clic sur un équipement). Une cible de moins de 20 px est un défaut mesurable, pas
  //    une préférence de confort — viser juste devient un jeu de hasard.
  //   Garde de taille nulle indispensable : un enfant d'un conteneur masqué a lui-même un
  //   `display` calculé qui n'est pas « none », donc `vu` le laisse passer, mais son rectangle
  //   est 0×0 car rien ne le rend. Sans cette garde, 19 éléments non rendus (l'écran de
  //   lancement replié, le plein écran de Cesium) étaientsignalés comme trop petits — de
  //   fausses alertes noyant le seul défaut réel.
  for (const e of document.querySelectorAll("button, select, input, a[href], [role=tab]")) {
    if (!vu(e)) continue;
    if (e.disabled) continue;
    const r = e.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;      // non rendu, pas trop petit
    if (r.width < 20 || r.height < 20) {
      ajouter("cible-trop-petite", e, `${Math.round(r.width)}x${Math.round(r.height)} (seuil 20)`);
    }
  }

  // 6. commande sans nom : un bouton dont le libellé n'est lisible par personne — ni à
  //    l'œil (pas de texte), ni par une technologie d'assistance (pas d'aria-label ni de
  //    titre). Fréquent dès qu'une commande n'est plus qu'une icône.
  for (const e of document.querySelectorAll("button, a[href], [role=tab]")) {
    if (!vu(e)) continue;
    const r = e.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;      // non rendu : rien à nommer
    const texte = (e.textContent ?? "").trim();
    const libelle = e.getAttribute("aria-label") || e.getAttribute("title") || "";
    if (!texte && !libelle) {
      ajouter("commande-sans-nom", e, `ni texte, ni aria-label, ni titre — ${chemin(e)}`);
    }
  }

  // 7. fenêtre d'équipement sortant de l'écran. Une fenêtre flottante qui dépasse le bas
  //    recouvre le panneau d'observation, donc les commandes du lecteur : le clic part sur
  //    la fenêtre au lieu du bouton, et l'animation semble cassée sans que rien ne nomme la
  //    fenêtre. Trouvé parce qu'un bloc de résultat a suffi à allonger l'onglet Physique.
  const basEcran = document.documentElement.clientHeight;
  for (const e of document.querySelectorAll(".device-win")) {
    if (!vu(e)) continue;
    const r = e.getBoundingClientRect();
    if (r.bottom > basEcran + 1) {
      ajouter("fenetre-hors-ecran", e, `bas à ${Math.round(r.bottom)}px pour ${basEcran}px d'écran`);
    }
    if (r.right > largeur + 1) {
      ajouter("fenetre-hors-ecran", e, `droite à ${Math.round(r.right)}px pour ${largeur}px de large`);
    }
  }

  // 8. régions attendues présentes, visibles et dimensionnées
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

  // 9. géométrie des grandes régions, pour référence
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
  // Seconde passerelle : sans elle, la session de l'audit n'a qu'une frontière et le plan ne
  // trace donc **aucun** trait radio — les liaisons n'étaient mesurées que par l'étape e2e.
  // L'ajouter change la topologie mesurée, donc la ligne de base du rapport : c'est le but,
  // et c'est fait sciemment (registre, §3). 400 m à l'est et 350 m au sud de l'origine, donc
  // à portée des deux capteurs sans se confondre avec `gw-nord`.
  await setValue('#add-form [name="id"]', "gw-sud");
  await setValue('#add-form [name="lat"]', "4.047952");
  await setValue('#add-form [name="lon"]', "9.771506");
  await submitForm("#add-form");
  await page.waitForSelector('g.node[data-id="gw-sud"]');
  // Coordonnées en degrés, converties depuis les mètres par la formule de geo.py :
  // 250 m à l'est et 90 m au nord de l'origine 4.0511 / 9.7679.
  for (const [id, lat, lon] of [["capteur-a", "4.051909", "9.770154"],
                                ["capteur-b", "4.054158", "9.773490"]]) {
    await setValue('#add-form [name="id"]', id);
    await page.select('#add-form [name="kind"]', "sensor");
    await setValue('#add-form [name="lat"]', lat);
    await setValue('#add-form [name="lon"]', lon);
    await submitForm("#add-form");
    await page.waitForSelector(`g.node[data-id="${id}"]`);
  }
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
      // Lu même masqué : en cas d'échec de la carte, c'est là qu'est la raison du repli.
      indice: indice ? indice.textContent.replace(/\s+/g, " ").trim() : "",
      // Taille d'affichage, distincte de la taille du tampon : un canevas peut être étiré
      // par la CSS tout en restant peint en 300×150.
      toileCss: toile ? `${toile.clientWidth}x${toile.clientHeight}` : "aucune",
      // Raison d'arrêt du rendu, le cas échéant.
      erreurRendu: window.__carteErreur ?? "",
      // Si le conteneur lui-même n'a pas de dimensions, le canevas ne peut pas en avoir :
      // c'est la première chose à vérifier avant d'accuser Cesium.
      zoneTaille: zone ? `${zone.clientWidth}x${zone.clientHeight}` : "aucune",
      conteneurs: zone
        ? [...zone.querySelectorAll("div")].slice(0, 3)
            .map((d) => `${d.className || "(sans classe)"} ${d.clientWidth}x${d.clientHeight}`)
            .join(" | ")
        : "",
    };
  });
  console.log(`WebGL : ${webgl.disponible ? "disponible" : "ABSENT"}` +
    (webgl.disponible ? ` (${webgl.fournisseur} / ${webgl.rendu})` : ""));
  console.log(`Carte 3D : vue active = ${cesium.vueActive} · zone ${cesium.zoneVisible ? "visible" : "masquée"}` +
    ` · toile = ${cesium.toile} (affichée ${cesium.toileCss})`);
  if (cesium.erreurRendu) console.log(`Carte 3D : rendu arrêté — ${cesium.erreurRendu}`);
  console.log(`Carte 3D : conteneur ${cesium.zoneTaille} · internes : ${cesium.conteneurs}`);
  if (cesium.indice) console.log(`Carte 3D : ${cesium.indice}`);

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

  // Deux capteurs qui émettent à la même seconde se collisionnent : il n'en restait qu'une
  // seule trame décodée, donc une seule liaison tracée sur le plan — de quoi mesurer la
  // géométrie d'un trait, pas celle d'un réseau. Une dispersion des départs les décale, et
  // plusieurs trames chacun donnent à chaque passerelle de quoi entendre les deux capteurs.
  for (const id of ["capteur-a", "capteur-b"]) {
    await page.click(`g.node[data-id="${id}"] circle`);
    await page.waitForSelector(`.device-win[data-node-id="${id}"]`);
    await page.evaluate((n) => {
      const b = [...document.querySelectorAll(`.device-win[data-node-id="${n}"] .dtab`)]
        .find((e) => e.textContent.trim() === "Config");
      if (b) b.click();
    }, id);
    await page.waitForSelector(`.device-win[data-node-id="${id}"] .sensor-form input[name="messages"]`);
    await setValue(`.device-win[data-node-id="${id}"] .sensor-form input[name="messages"]`, "4");
    await setValue(`.device-win[data-node-id="${id}"] .sensor-form input[name="start_spread_s"]`, "30");
    await submitForm(`.device-win[data-node-id="${id}"] form`);
    await page.waitForFunction((n) => {
      const f = document.querySelector(`.device-win[data-node-id="${n}"] form`);
      return /enregistrés/.test(f?.textContent ?? "");
    }, { timeout: 10_000 }, id);
    // On referme : deux fenêtres ouvertes se recouvriraient, et l'audit lit un recouvrement
    // comme un défaut de mise en page. Ce n'est pas ce qu'on veut mesurer ici.
    await page.evaluate((n) => {
      document.querySelector(`.device-win[data-node-id="${n}"] .close`)?.click();
    }, id);
    await pause(200);
  }
  await page.click('g.node[data-id="capteur-a"] circle');
  await page.waitForSelector('.device-win[data-node-id="capteur-a"]');
  await pause(400);

  // Les indicateurs calculés ne sont rendus qu'après un run : sans cette étape, l'audit
  // mesurerait une interface où le bloc n'existe pas, et le déclarerait sain faute de
  // l'avoir vu. Le bloc reste affiché pendant toute la boucle de largeurs qui suit.
  const cliqueOnglet = (texte) => page.evaluate((t) => {
    const b = [...document.querySelectorAll(".tab")].find((e) => e.textContent.includes(t));
    if (b) b.click();
    return Boolean(b);
  }, texte);
  await cliqueOnglet("Simulation");
  await page.$eval("#seed", (e) => { e.value = "7"; });
  await page.click("#simulate");
  await page.waitForFunction(
    () => /terminé/.test(document.getElementById("sim-status")?.textContent ?? ""),
    { timeout: 120_000 });
  await page.waitForFunction(
    () => document.querySelectorAll(".metric").length >= 1, { timeout: 30_000 });
  const nbBlocs = await page.$$eval(".metric", (b) => b.length);
  const groupesVisible = await page.$eval("#sim-groups", (t) => !t.hidden);
  console.log(`Indicateurs : ${nbBlocs} bloc(s) · table par équipement ${groupesVisible ? "visible" : "masquée"}`);

  // Les liaisons radio tracées sur le plan. Elles n'existent qu'après un run, et il faut
  // deux passerelles pour qu'il y en ait une seule : avec une frontière unique, le plan
  // n'avait aucun trait et cette géométrie n'était jamais passée au gabarit. Le compte est
  // publié parce qu'un plan muet et un plan sans liaison se ressemblent trait pour trait.
  const cliquerVue = (texte) => page.evaluate((t) => {
    const b = [...document.querySelectorAll(".view-tab")].find((e) => e.textContent.includes(t));
    if (b) b.click();
    return Boolean(b);
  }, texte);
  await cliquerVue("Plan");
  await page.waitForFunction(() => {
    const b = [...document.querySelectorAll(".view-tab")].find((e) => e.textContent.includes("Plan"));
    return b?.classList.contains("active");
  }, { timeout: 10_000 });
  const liens = await page.$$eval("#plan .lien", (ls) => ls.map((l) => l.getAttribute("class")));
  const etiquettes = await page.$$eval("#plan .lien-etiquette", (ts) => ts.map((t) => t.textContent));
  console.log(`Plan : ${liens.length} liaison(s) tracée(s) · ${etiquettes.join(", ") || "aucune étiquette"}`);
  // On reste sur le plan : c'est la vue que la boucle de largeurs mesure, et la seule où le
  // nœud soit visable. Revenir à la carte la masquait, et l'audit signalait alors
  // « .plan-area présente mais masquée » et « svg#plan 0x0 » — 35 problèmes qui n'étaient
  // que le plan qu'on venait de cacher. La carte est déjà mesurée plus haut, à part.

  // 1040 est la largeur où le menu du haut disparaît et 1000 celle juste en dessous : le
  // défaut qu'on cherche à attraper est un en-tête qui déborde **entre** les seuils, donc
  // il faut mesurer de part et d'autre du repli, pas seulement largement au-dessus et
  // largement en dessous. C'est ainsi que six débordements à 900 px sont passés inaperçus.
  for (const largeur of [1400, 1180, 1100, 1040, 1000, 900, 760]) {
    await page.setViewport({ width: largeur, height: 1000 });
    await pause(700);
    rapport.push({ largeur, ...(await page.evaluate(mesurer)) });
  }

  // Balayage des états : la boucle ci-dessus ne mesure qu'un seul état — l'onglet
  // Simulation, juste après un run. Les autres onglets d'observation et les trois onglets
  // d'une fenêtre d'équipement n'ont jamais été mesurés par quoi que ce soit. Un défaut qui
  // n'existe que sur « Config » ou « Trame » passerait donc inaperçu indéfiniment.
  // Deux largeurs suffisent ici : 1400 (disposition large) et 900 (sous les seuils de repli).
  const cliquerTexte = (selecteur, texte) => page.evaluate((sel, t) => {
    const b = [...document.querySelectorAll(sel)].find((e) => e.textContent.trim() === t);
    if (b) b.click();
    return Boolean(b);
  }, selecteur, texte);

  const etats = [
    // Le plan porte les liaisons radio depuis que la session a deux passerelles : c'est une
    // géométrie que rien ne mesurait, les traits pouvant déborder du cadre sans que rien
    // ne le voie.
    { nom: "vue · Plan", action: () => cliquerVue("Plan") },
    { nom: "observation · Journal", action: () => cliquerTexte(".tab", "Journal") },
    { nom: "observation · Trame", action: () => cliquerTexte(".tab", "Trame") },
    { nom: "observation · Exercice", action: () => cliquerTexte(".tab", "Exercice") },
    { nom: "équipement · Physique", action: () => cliquerTexte(".dtab", "Physique") },
    { nom: "équipement · Config", action: () => cliquerTexte(".dtab", "Config") },
    { nom: "équipement · CLI", action: () => cliquerTexte(".dtab", "CLI") },
    // La fenêtre passerelle a son propre formulaire depuis qu'on l'a ouverte, et l'audit
    // ne mesure ici que celle d'un capteur : la nouvelle fenêtre serait la seule partie de
    // l'interface jamais passée au gabarit. On ferme donc le capteur et on ouvre la
    // passerelle — le formulaire le plus dense de l'atelier.
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
  for (const largeur of [1400, 900]) {
    await page.setViewport({ width: largeur, height: 1000 });
    for (const etat of etats) {
      const trouve = await etat.action();
      if (!trouve) { rapport.push({ etat: `${largeur} · ${etat.nom}`, introuvable: true, problemes: [] }); continue; }
      await pause(400);
      rapport.push({ etat: `${largeur} · ${etat.nom}`, ...(await page.evaluate(mesurer)) });
    }
  }

  // Résumé lisible, et déposé dans le dépôt : le journal du runner est hébergé hors de
  // portée de l'outillage, un rapport qui n'y vit que là est perdu à chaque exécution.
  const markdown = rapportMarkdown(rapport);
  console.log(markdown);
  const cible = new URL("../../../docs/audits/mise-en-page.md", import.meta.url);
  writeFileSync(cible, markdown);
  console.log(`rapport déposé : ${fileURLToPath(cible)}`);
} finally {
  for (const c of children) { try { c.kill("SIGTERM"); } catch { /* déjà arrêté */ } }
  if (browser) await browser.close();
}
