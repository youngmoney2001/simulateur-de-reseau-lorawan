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
    // WebGL logiciel : sans lui Cesium ne peut pas créer son contexte, et le studio
    // retomberait sur le plan 2D sans que ce soit un défaut de l'application.
    // Ni --single-process ni --no-zygote : Cesium lance des web workers pour charger ses
    // tuiles, et ces deux options les empêchent de démarrer, ce qui fait échouer
    // l'initialisation du Viewer.
    args: ["--no-sandbox", "--disable-gpu", "--enable-unsafe-swiftshader",
           "--use-gl=swiftshader", "--ignore-gpu-blocklist"] });
  const page = await browser.newPage();
  await page.setViewport({ width: 1400, height: 1000 });
  const pageErrors = [];
  // La pile est conservée avec le message : « DeveloperError » seul ne dit pas d'où vient
  // l'erreur, et les journaux du runner sont hors de portée du réseau — c'est le seul
  // endroit où la cause est lisible.
  page.on("pageerror", (e) => {
    const pile = (e.stack ?? e.message ?? "").split("\n").slice(0, 6).join("\n      ");
    pageErrors.push(e.message);
    console.error("pageerror:", e.message, "\n      " + pile);
  });
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
  // L'interface est a onglets (disposition Packet Tracer) : on choisit l'onglet par son libelle.
  const clickTab = async (sel, label) => {
    await page.evaluate((s, txt) => {
      const b = [...document.querySelectorAll(s)].find((e) => e.textContent.includes(txt));
      if (!b) throw new Error(`onglet introuvable : ${txt}`);
      b.click();
    }, sel, label);
  };
  // Plusieurs fenetres peuvent etre ouvertes : l onglet doit viser celle de l equipement vise,
  // sinon on clique l onglet de la premiere fenetre venue.
  const deviceTab = (label, nodeId) =>
    clickTab('.device-win[data-node-id="' + nodeId + '"] .dtab', label);
  const obsTab = (label) => clickTab(".tab", label);
  // La carte 3D est la vue par défaut ; le plan 2D reste la vue métrique, celle qui permet
  // de régler des distances au pixel. Les essais de positionnement s'y font donc.
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

  await step("connexion et session créée automatiquement", async () => {
    await page.type("#token", token);
    await page.click("#connect");
    await page.waitForFunction(() => document.querySelectorAll("#session-select option").length === 1, { timeout: 20_000 });
  });

  await step("la carte 3D est la vue par défaut, ou repli franc sur le plan", async () => {
    const active = await page.$eval(".view-tab.active", (e) => e.textContent.trim());
    // Cesium exige WebGL, absent de certains navigateurs sans affichage. Le studio doit alors
    // retomber sur le plan au lieu de rester sur une carte vide : c'est ce qu'on vérifie ici.
    if (!active.includes("Carte") && !active.includes("Plan")) {
      throw new Error(`vue par défaut inattendue : ${active}`);
    }
    if (active.includes("Plan")) {
      steps[steps.length - 1] = "ok   repli sur le plan 2D (WebGL absent)";
      console.error("note : WebGL indisponible, repli sur le plan");
    }
  });

  await step("ajout d'une passerelle frontière et d'un capteur", async () => {
    await setValue('#add-form [name="id"]', "gw-nord");
    await setValue('#add-form [name="name"]', "Passerelle nord");
    await submitForm("#add-form");
    await page.waitForSelector('g.node[data-id="gw-nord"]');
    await setValue('#add-form [name="id"]', "capt-1");
    await page.select('#add-form [name="kind"]', "sensor");
    // Position en degrés (invariant D2) : 300 m à l'est et 100 m au nord de l'origine
    // 4.0511 / 9.7679 valent ces coordonnées, calculées par la formule de geo.py.
    await setValue('#add-form [name="lat"]', "4.051999");
    await setValue('#add-form [name="lon"]', "9.770600");
    await submitForm("#add-form");
    await page.waitForSelector('g.node[data-id="capt-1"]');
  });

  await step("aller-retour : la fenêtre réaffiche les degrés saisis", async () => {
    // Ce qu'on a tapé doit ressortir identique, redonnée par la conversion inverse. Si les
    // deux côtés divergent, l'équipement « saute » à chaque ouverture de sa fenêtre — c'est
    // précisément la panne que l'invariant D2 cherche à rendre impossible.
    await viewTab("Plan");
    await page.click('g.node[data-id="capt-1"] circle');
    await page.waitForSelector('.device-win[data-node-id="capt-1"]');
    const affiche = await page.$eval('.device-win[data-node-id="capt-1"]', (w) => w.textContent);
    const m = /(\d+\.\d{6}),\s*(\d+\.\d{6})/.exec(affiche);
    if (!m) throw new Error(`aucune coordonnée affichée : ${affiche.slice(0, 200)}`);
    // Saisi 4.051999 / 9.770600 : l'affichage doit le retrouver au cent-millième de degré,
    // soit une dizaine de mètres — l'épaisseur du trait sur la carte.
    if (Math.abs(Number(m[1]) - 4.051999) > 1e-4 || Math.abs(Number(m[2]) - 9.770600) > 1e-4)
      throw new Error(`aller-retour fautif : ${m[1]}, ${m[2]}`);
    // La fenêtre est refermée : elle recouvre le plan, et l'étape suivante clique un nœud
    // qui se trouve dessous — le clic atteindrait la fenêtre au lieu du nœud.
    await page.click('.device-win[data-node-id="capt-1"] .close');
    await page.waitForFunction(
      () => !document.querySelector('.device-win[data-node-id="capt-1"]'), { timeout: 10_000 });
  });

  await step("identifiant invalide refusé côté studio", async () => {
    await setValue('#add-form [name="id"]', "Gw Bad");
    await submitForm("#add-form");
    await waitText("#flash", /identifiant/);
  });

  await step("console : configuration CLI et erreur de syntaxe au caret", async () => {
    await viewTab("Plan");
    await page.click('g.node[data-id="gw-nord"] rect');
    await page.waitForSelector('.device-win[data-node-id="gw-nord"]');
    await deviceTab("CLI", "gw-nord");
    await page.waitForSelector('.device-win[data-node-id="gw-nord"] .console input');
    const send = async (cmd) => {
      await page.click('.device-win[data-node-id="gw-nord"] .console input');
      await page.type('.device-win[data-node-id="gw-nord"] .console input', cmd);
      await page.keyboard.press("Enter");
      await page.waitForFunction((c) => !document.querySelector('.device-win[data-node-id="gw-nord"] .console input').value && (document.querySelector('.device-win[data-node-id="gw-nord"] .console pre').textContent.includes(c)), { timeout: 20_000 }, cmd);
    };
    await send("enable");
    await send("configure terminal");
    await send("hostname frontiere-nord");
    await send("end");
    await waitText('.device-win[data-node-id="gw-nord"]', /frontiere-nord/);
    await send("commande-inconnue");
    await page.waitForFunction(() => document.querySelector('.device-win[data-node-id="gw-nord"] .console pre').textContent.includes("^"), { timeout: 20_000 });
    await page.click('.device-win[data-node-id="gw-nord"] .console input');
    await page.keyboard.press("ArrowUp");
    const recalled = await page.$eval('.device-win[data-node-id="gw-nord"] .console input', (i) => i.value);
    if (recalled !== "commande-inconnue") throw new Error(`historique : ${recalled}`);
    await page.$eval('.device-win[data-node-id="gw-nord"] .console input', (i) => { i.value = ""; });
  });

  await step("capteur : refus d'un SF hors bornes au studio, puis enregistrement", async () => {
    await viewTab("Plan");
    await page.click('g.node[data-id="capt-1"] circle');
    await page.waitForSelector('.device-win[data-node-id="capt-1"]');
    await deviceTab("Config", "capt-1");
    await page.waitForSelector('.device-win[data-node-id="capt-1"] .sensor-form input[name="spreading_factor"]');
    await setValue('.device-win[data-node-id="capt-1"] .sensor-form input[name="spreading_factor"]', "13");
    await submitForm('.device-win[data-node-id="capt-1"] form');
    await waitText('.device-win[data-node-id="capt-1"] form', /spreading_factor/);
    await setValue('.device-win[data-node-id="capt-1"] .sensor-form input[name="spreading_factor"]', "9");
    await setValue('.device-win[data-node-id="capt-1"] .sensor-form input[name="messages"]', "2");
    await submitForm('.device-win[data-node-id="capt-1"] form');
    await waitText('.device-win[data-node-id="capt-1"] form', /enregistrés/);
  });

  // La position de référence est relue **avant** le geste : la comparer à des valeurs
  // écrites en dur laissait passer un déplacement qui n'atteindrait pas le serveur.
  const positionDe = async (id) => {
    const sid = await page.$eval("#session-select", (s) => s.value);
    const res = await fetch(`http://127.0.0.1:${API_PORT}/api/v1/sessions/${sid}/topology`,
      { headers: { Authorization: `Bearer ${token}` } });
    const topo = await res.json();
    const n = topo.nodes.find((x) => x.id === id);
    if (!n) throw new Error(`équipement absent : ${id}`);
    return { x_m: n.x_m, y_m: n.y_m };
  };

  const lireZone = () => page.$eval("#origin-coords", (i) => i.value);

  const compterEquipements = async () => {
    const sid = await page.$eval("#session-select", (s) => s.value);
    const res = await fetch(`http://127.0.0.1:${API_PORT}/api/v1/sessions/${sid}/topology`,
      { headers: { Authorization: `Bearer ${token}` } });
    const topo = await res.json();
    return (topo.nodes ?? []).length;
  };

  await step("glisser-déposer sur le plan : la position est enregistrée côté API", async () => {
    await viewTab("Plan");
    const avant = await positionDe("capt-1");
    const box = await (await page.$('g.node[data-id="capt-1"] circle')).boundingBox();
    const x = box.x + box.width / 2, y = box.y + box.height / 2;
    await page.mouse.move(x, y);
    await page.mouse.down();
    await page.mouse.move(x - 60, y + 30, { steps: 8 });
    await page.mouse.move(x - 120, y + 60, { steps: 8 });
    await page.mouse.up();
    await new Promise((r) => setTimeout(r, 800));
    const apres = await positionDe("capt-1");
    if (Math.abs(apres.x_m - avant.x_m) < 1 && Math.abs(apres.y_m - avant.y_m) < 1)
      throw new Error(`position inchangée côté API : ${JSON.stringify(apres)}`);
  });

  await step("simulation : run terminé, résultats par passerelle", async () => {
    await setValue("#seed", "7");
    await page.click("#simulate");
    await waitText("#sim-status", /terminé/, 120_000);
    await page.waitForFunction(() => document.querySelectorAll("#sim-results tbody tr").length >= 1);
    const rows = await page.$$eval("#sim-results tbody tr", (trs) => trs.map((t) => t.textContent));
    if (!rows.some((r) => r.includes("frontiere-nord") || r.includes("gw-nord"))) throw new Error(rows.join(" | "));
  });

  // Indicateurs calculés : le bloc est rempli depuis les vrais compteurs du run. Une formule
  // vide ou une valeur « — » signifierait un champ mal lu côté serveur — le module pur ne
  // peut pas l'attraper, seul un run réel dans un navigateur le peut.
  await step("indicateurs calculés : bloc rempli et formules affichées", async () => {
    await obsTab("Simulation");
    await page.waitForFunction(() => !document.getElementById("sim-metrics").hidden, { timeout: 30_000 });
    const metriques = await page.$$eval(".metric", (blocs) => blocs.map((b) => ({
      label: b.querySelector(".m-label")?.textContent ?? "",
      valeur: b.querySelector(".m-value")?.textContent ?? "",
      formule: b.querySelector(".m-formula")?.textContent ?? "",
    })));
    if (metriques.length < 8) throw new Error(`${metriques.length} indicateur(s), 8 attendus au minimum`);
    for (const m of metriques) {
      if (!m.label) throw new Error("indicateur sans libellé");
      if (m.valeur === "—") throw new Error(`valeur non calculée : ${m.label}`);
      if (m.formule.length < 20) throw new Error(`formule absente : ${m.label}`);
    }
    const libelles = metriques.map((m) => m.label);
    // Les deux grandeurs d'occupation ne doivent pas être confondues (voir metrics.js).
    if (!libelles.includes("Charge offerte")) throw new Error(libelles.join(" | "));
    if (!libelles.includes("Occupation du canal")) throw new Error(libelles.join(" | "));
  });

  // Phase L : le résultat doit se lire sur la carte et sur le plan, pas seulement dans un
  // tableau. Un module pur peut vérifier l'échelle de couleurs ; seul un run réel dans un
  // navigateur vérifie que la couleur arrive jusqu'au pixel affiché.
  await step("visualisation : équipements colorés par leur résultat, légende affichée", async () => {
    const legende = await page.$eval("#pdr-legend", (e) => ({
      visible: !e.hidden,
      texte: e.textContent.replace(/\s+/g, " ").trim(),
      pastilles: e.querySelectorAll(".lg-rond").length,
    }));
    if (!legende.visible) throw new Error("légende masquée alors qu'un run colore des équipements");
    if (legende.pastilles !== 4) throw new Error(`${legende.pastilles} pastille(s), 4 attendues`);
    if (!legende.texte.includes("Taux de livraison")) throw new Error(legende.texte);

    // Le plan 2D porte la même lecture : un fill posé par le résultat, pas par le type.
    // `viewTab` est idempotent : l'étape de glisser-déposer a déjà basculé sur le plan.
    await viewTab("Plan");
    const peints = await page.$$eval("#plan g.node > *", (formes) => formes
      .map((f) => f.getAttribute("fill"))
      .filter((c) => c && c.startsWith("#")));
    if (peints.length < 1) throw new Error("aucun équipement coloré par son résultat sur le plan");

    // La fenêtre de l'équipement chiffre ce que la carte colore. Les deux viennent du même
    // objet en mémoire : si jamais ils divergent, c'est ce test qui le dira.
    // La fenêtre de « capteur-a » est ouverte depuis l'étape d'aller-retour ; on s'assure
    // seulement d'être sur son onglet Physique, où vit le bloc de résultat.
    await deviceTab("Physique", "capteur-a");
    await page.waitForSelector('.device-win[data-node-id="capteur-a"] .phys-etat', { timeout: 10_000 });
    const bloc = await page.$eval('.device-win[data-node-id="capteur-a"] .phys-resultat',
      (dl) => [...dl.querySelectorAll("dt")].map((dt, i) => [dt.textContent,
        dl.querySelectorAll("dd")[i]?.textContent]));
    if (bloc.length < 5) throw new Error(`${bloc.length} ligne(s) de résultat, 5 attendues`);
    const taux = bloc.find((l) => l[0].includes("Taux de livraison"));
    if (!taux) throw new Error(bloc.map((l) => l[0]).join(" | "));
    if (!/%/.test(taux[1])) throw new Error(`taux sans unité : ${taux[1]}`);
    const pastille = await page.$$eval('.device-win[data-node-id="capteur-a"] .phys-titre .lg-rond',
      (n) => n.length);
    if (pastille < 1) throw new Error("pastille de couleur absente de la fenêtre");
  });

  await step("animation : lecteur chargé, horloge avance, trames dessinées, journal", async () => {
    await obsTab("Journal");
    await page.waitForFunction(() => document.querySelectorAll("#journal > li").length >= 1, { timeout: 60_000 });
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
    await obsTab("Exercice");
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

  // Pose sur la carte 3D : on tire un équipement de la palette jusqu'au globe. C'est le
  // geste de la phase H, et il n'existe qu'ici — nul autre test ne fait tourner Cesium
  // avec une topologie réelle.
  //
  // Placé en dernier, juste avant la suppression de la session : l'équipement créé reste
  // dans la topologie, et les étapes de simulation et d'exercice ont été écrites pour un
  // réseau précis. Un nœud de plus les faisait dérailler.
  await step("glisser depuis la palette jusqu'à la carte : l'équipement est posé", async () => {
    await viewTab("Carte");
    const canvas = await page.$("#cesium canvas");
    if (!canvas) throw new Error("canevas de la carte absent : la carte n'a pas démarré");
    await new Promise((r) => setTimeout(r, 3500));

    const nbAvant = await compterEquipements();

    const modele = await page.$(".model-box button");
    if (!modele) throw new Error("aucun modèle dans la palette");
    const src = await modele.boundingBox();
    const dst = await canvas.boundingBox();
    if (!src || !dst) throw new Error("palette ou carte sans dimensions");

    const sx = src.x + src.width / 2, sy = src.y + src.height / 2;
    const dx = dst.x + dst.width / 2, dy = dst.y + dst.height / 2;

    await page.mouse.move(sx, sy);
    await page.mouse.down();
    await page.mouse.move((sx + dx) / 2, (sy + dy) / 2, { steps: 10 });
    await page.mouse.move(dx, dy, { steps: 10 });
    await new Promise((r) => setTimeout(r, 300));
    await page.mouse.up();
    await new Promise((r) => setTimeout(r, 1200));

    const nbApres = await compterEquipements();
    if (nbApres <= nbAvant)
      throw new Error(`aucun équipement créé : ${nbAvant} -> ${nbApres}`);
    steps[steps.length - 1] = `ok   glisser depuis la palette : ${nbAvant} -> ${nbApres} équipement(s)`;
  });

  // Choix de la zone. Placé en fin de scénario : déplacer l'ancre déplace tout le réseau
  // (décision D3), ce qui casserait les étapes de simulation écrites pour un réseau précis.
  await step("choisir la zone : un clic non armé ne déplace pas l'ancre", async () => {
    await viewTab("Carte");
    await new Promise((r) => setTimeout(r, 2500));
    const avant = await lireZone();
    const canvas = await page.$("#cesium canvas");
    const dst = await canvas.boundingBox();

    // Déplacer l'ancre déplace **tout le réseau**. Un clic pour regarder, ou un clic
    // égaré, ne doit donc rien produire : c'est la raison d'être du geste armé.
    await page.mouse.click(dst.x + dst.width * 0.35, dst.y + dst.height * 0.42);
    await new Promise((r) => setTimeout(r, 900));
    const apresClicNu = await lireZone();
    if (apresClicNu !== avant)
      throw new Error(`un clic non armé a déplacé la zone : « ${avant} » -> « ${apresClicNu} »`);
  });

  await step("choisir la zone : le geste armé pose l'ancre au point cliqué", async () => {
    const avant = await lireZone();
    await page.click("#pick-origin");
    await page.waitForFunction(
      () => document.getElementById("pick-origin").classList.contains("active"),
      { timeout: 10_000 });
    const canvas = await page.$("#cesium canvas");
    const dst = await canvas.boundingBox();
    await page.mouse.click(dst.x + dst.width * 0.62, dst.y + dst.height * 0.58);
    await new Promise((r) => setTimeout(r, 1500));

    const apres = await lireZone();
    if (apres === avant) {
      // Deux causes possibles, qu'il faut distinguer faute de navigateur local :
      // le geste a été consommé mais l'ancre n'a pas bougé, ou le clic n'est jamais
      // arrivé jusqu'à la carte. Le bouton encore armé tranche entre les deux.
      const encoreArme = await page.$eval("#pick-origin", (b) => b.classList.contains("active"));
      const indice = await page.$eval("#map-hint", (n) => n.textContent.trim());
      throw new Error(
        `le clic armé n'a pas déplacé la zone (${avant}) · geste ${encoreArme ? "NON consommé : le clic n'a pas atteint la carte" : "consommé, mais l'ancre est restée"} · indice : « ${indice} »`);
    }
    if (!/^-?\d+\.\d+,\s?-?\d+\.\d+$/.test(apres))
      throw new Error(`zone écrite dans un format inattendu : « ${apres} »`);
    // Le geste est à usage unique : il se désarme après le clic.
    await page.waitForFunction(
      () => !document.getElementById("pick-origin").classList.contains("active"),
      { timeout: 10_000 });
  });

  await step("la zone se saisit en collant une paire de coordonnées", async () => {
    // Le geste décrit par l'utilisateur : copier un point depuis une carte. Deux champs
    // `number` séparés, comme c'était le cas, refusaient ce collage.
    await setValue("#origin-coords", "4.060000, 9.780000");
    await page.$eval("#origin-coords", (i) =>
      i.dispatchEvent(new Event("change", { bubbles: true })));
    await new Promise((r) => setTimeout(r, 800));
    const lu = await lireZone();
    if (!/^4\.060000,\s?9\.780000$/.test(lu))
      throw new Error(`zone non retenue : « ${lu} »`);
    // Et la forme française, avec la virgule décimale.
    await setValue("#origin-coords", "4,0511 9,7679");
    await page.$eval("#origin-coords", (i) =>
      i.dispatchEvent(new Event("change", { bubbles: true })));
    await new Promise((r) => setTimeout(r, 800));
    const lu2 = await lireZone();
    if (!/^4\.051100,\s?9\.767900$/.test(lu2))
      throw new Error(`virgule décimale non traitée : « ${lu2} »`);
  });

  await step("suppression de la session", async () => {
    const before = await page.$$eval("#session-select option", (o) => o.length);
    await page.click("#delete-session");
    await page.waitForFunction((n) => document.querySelectorAll("#session-select option").length < n, { timeout: 20_000 }, before);
  });

  // Certaines erreurs ne viennent pas de l'application mais de l'environnement : les tuiles
  // du fond de carte sont chargées depuis un service distant, que l'exécuteur peut ne pas
  // atteindre. Elles sont écartées nominativement — toute erreur non listée reste fatale,
  // sinon cette tolérance deviendrait un moyen de ne rien voir.
  const environnementales = [
    /source image could not be decoded/i,   // tuile illisible, réseau absent
    /rendering has stopped/i,               // Cesium renonce à une frame après une tuile perdue
    /Failed to load resource/i,             // ressource distante injoignable
  ];
  const imputables = pageErrors.filter((e) => !environnementales.some((r) => r.test(e)));
  if (imputables.length) steps.push(`pageerror : ${imputables.join(" | ")}`);
  if (pageErrors.length > imputables.length) {
    steps.push(`note : ${pageErrors.length - imputables.length} erreur(s) environnementale(s) écartée(s)`);
  }
  console.log(steps.join("\n"));
  if (imputables.length) throw new Error("erreurs de page imputables à l'application");
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
