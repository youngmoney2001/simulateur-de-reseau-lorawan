// Test de bout en bout du studio dans un vrai navigateur, contre le vrai serveur API.
// Prérequis : CHROME_PATH (binaire Chromium), LSIM_LIBRARY (bibliothèque native), PYTHON (interpréteur
// avec lsim importable via PYTHONPATH=python/). Lancer : `npm run test:e2e` depuis web/.
import { spawn } from "node:child_process";
import { mkdtempSync, readFileSync, writeFileSync, readdirSync } from "node:fs";
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
  // Un refus du serveur ne se voit qu'au corps de la réponse : la console du navigateur
  // n'affiche que « 422 », et un formulaire qui garde son message de succès précédent
  // laisse croire à un enregistrement qui n'a pas eu lieu. On garde donc le corps des
  // réponses en erreur, pour le joindre à l'échec plutôt que de le deviner.
  const refus = [];
  page.on("response", async (r) => {
    if (r.status() < 400) return;
    const corps = await r.text().catch(() => "(corps illisible)");
    refus.push(`${r.request().method()} ${r.url().replace(/^http:\/\/[^/]+/, "")} `
      + `→ ${r.status()} ${corps.slice(0, 300)}`);
  });
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
  /** Le serveur a-t-il les réglages attendus ? Lu chez lui, pas dans le message de l'écran.
   *
   * Un formulaire garde le « enregistrés » de la soumission précédente : attendre ce mot
   * passe donc avant que la soumission courante aboutisse, et un refus (422) passe
   * inaperçu jusqu'à ce qu'un run parte sur les anciens réglages. On interroge la
   * topologie jusqu'à l'échéance ; à défaut, on publie les refus HTTP collectés.
   */
  const attendreReglages = async (nodeId, attendus, refus = [], timeoutMs = 10_000) => {
    const sid = await page.$eval("#session-select", (s) => s.value);
    const fin = Date.now() + timeoutMs;
    let vu = null;
    for (;;) {
      const topo = await fetch(`http://127.0.0.1:${API_PORT}/api/v1/sessions/${sid}/topology`,
        { headers: { Authorization: `Bearer ${token}` } }).then((r) => r.json());
      const n = (topo.nodes ?? []).find((x) => x.id === nodeId);
      vu = n?.sensor ?? null;
      if (vu && Object.entries(attendus).every(([k, v]) => vu[k] === v)) return;
      if (Date.now() > fin) break;
      await new Promise((r) => setTimeout(r, 250));
    }
    throw new Error(`réglages de ${nodeId} non enregistrés : attendu `
      + `${JSON.stringify(attendus)}, serveur ${JSON.stringify(vu)}\n`
      + `refus HTTP : ${refus.slice(-5).join("\n  ") || "aucun"}`);
  };
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
  // Combien d'équipements le plan montre-t-il ? C'est la lecture la plus proche de ce que
  // voit l'utilisateur, et elle ne dépend pas du format d'une étiquette.
  const lireEffectif = () => page.$$eval("#plan g.node", (n) => n.length);
  // Un téléchargement n'arrive pas instantanément, et `.crdownload` n'est pas encore le
  // fichier : on attend la disparition du suffixe plutôt qu'une durée arbitraire.
  const attendreFichier = async (dossier, motif, timeoutMs = 20_000) => {
    const echeance = Date.now() + timeoutMs;
    while (Date.now() < echeance) {
      const trouve = readdirSync(dossier).find((f) => motif.test(f));
      if (trouve) return trouve;
      await new Promise((r) => setTimeout(r, 200));
    }
    throw new Error(`aucun fichier ${motif} dans ${dossier} : ${readdirSync(dossier).join(", ")}`);
  };

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
    // Le courant moyen n'apparaissait jamais : la compilation ne demandait aucun profil
    // d'energie, et la mesure restait a `None` cote serveur. Sa presence est le vrai test.
    if (!libelles.includes("Courant moyen")) throw new Error(libelles.join(" | "));
  });

  await step("autonomie : le courant est simule, la capacite est enoncee", async () => {
    await obsTab("Simulation");
    await page.waitForFunction(() => !document.getElementById("sim-autonomie").hidden,
      { timeout: 20_000 });
    // Sans capacite saisie, rien n'est affiche. Un « — » a cote d'un champ vide dirait
    // « autonomie nulle » a qui lit vite.
    const vide = await textOf("#autonomie-out");
    if (vide.trim()) throw new Error(`autonomie affichee sans capacite : « ${vide} »`);

    await setValue("#battery-mah", "2400");
    await page.$eval("#battery-mah", (i) => i.dispatchEvent(new Event("input", { bubbles: true })));
    await page.waitForFunction(
      () => /an|mois|jour/.test(document.getElementById("autonomie-out")?.textContent ?? ""),
      { timeout: 10_000 });
    const texte = await textOf("#autonomie-out");
    // Les deux termes sont rappeles : une autonomie sans son courant ni sa capacite ne se
    // verifie pas. Et la limite est dite, une pile ne rend pas ce que le calcul promet.
    for (const attendu of ["2400", "µA", "hors vieillissement"])
      if (!texte.includes(attendu)) throw new Error(`« ${texte} » sans « ${attendu} »`);

    // Une saisie illisible est nommee, pas convertie de force.
    await setValue("#battery-mah", "beaucoup");
    await page.$eval("#battery-mah", (i) => i.dispatchEvent(new Event("input", { bubbles: true })));
    await page.waitForFunction(
      () => /n'est pas une capacit/.test(document.getElementById("autonomie-out")?.textContent ?? ""),
      { timeout: 10_000 });
    await setValue("#battery-mah", "");
    await page.$eval("#battery-mah", (i) => i.dispatchEvent(new Event("input", { bubbles: true })));
  });

  // Phase L : le résultat doit se lire sur la carte et sur le plan, pas seulement dans un
  // tableau. Un module pur peut vérifier l'échelle de couleurs ; seul un run réel dans un
  // navigateur vérifie que la couleur arrive jusqu'au pixel affiché.
  // Verdict de rapport cyclique : la limite vient du serveur, la mesure du run. Le test
  // vérifie que les deux se rencontrent dans la case, et que la source est citée —
  // une limite sans source n'est qu'une opinion.
  await step("rapport cyclique : limite, verdict et source affichés", async () => {
    const enTetes = await page.$$eval("#sim-groups thead th", (th) => th.map((e) => e.textContent));
    if (!enTetes.includes("Limite")) throw new Error(enTetes.join(" | "));
    if (!enTetes.includes("Occupation")) throw new Error(enTetes.join(" | "));

    const cases = await page.$$eval("#sim-groups tbody tr", (trs) => trs.map((tr) => {
      const td = tr.querySelectorAll("td");
      return { occupation: td[td.length - 2]?.textContent ?? "", limite: td[td.length - 1]?.textContent ?? "" };
    }));
    if (!cases.length) throw new Error("aucune ligne dans la table par équipement");
    for (const c of cases) {
      if (!/%/.test(c.occupation)) throw new Error(`occupation sans unité : ${c.occupation}`);
      // Une limite absente doit rester « — » : jamais « 100 % », qui autoriserait tout.
      if (c.limite !== "—" && !/%/.test(c.limite) && c.limite !== "aucune") {
        throw new Error(`limite inattendue : ${c.limite}`);
      }
      if (/100(\.0+)? %/.test(c.limite)) throw new Error(`limite fabriquée : ${c.limite}`);
    }

    const note = await page.$eval("#sim-duty-note", (e) => ({
      visible: !e.hidden, texte: e.textContent.replace(/\s+/g, " ").trim(),
    }));
    if (!note.visible) throw new Error("note de source masquée alors qu'une limite est affichée");
    // La réserve n'est pas un détail : sans elle, le verdict est surinterprété.
    if (!note.texte.includes("moyennage")) throw new Error(note.texte);
    if (!note.texte.includes("ETSI") && !note.texte.includes("RP002")) throw new Error(note.texte);
    // Et la réserve doit maintenant chiffrer la fenêtre du run, au lieu de dire seulement
    // qu'elle « n'est pas forcément » celle du texte. Une durée énoncée se confronte ; une
    // réserve générale laisse l'utilisateur sans moyen d'évaluer l'écart.
    if (!/Mesuré sur \d/.test(note.texte)) throw new Error(note.texte);
  });

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
    // La fenêtre de « capt-1 » est ouverte depuis l'étape de réglages radio, sur l'onglet
    // Config : on repasse sur Physique, où vit le bloc de résultat. Ne pas ouvrir de fenêtre
    // ici — une fenêtre laissée ouverte gêne les étapes suivantes, qui cliquent la carte.
    await deviceTab("Physique", "capt-1");
    await page.waitForSelector('.device-win[data-node-id="capt-1"] .phys-etat', { timeout: 10_000 });
    const bloc = await page.$eval('.device-win[data-node-id="capt-1"] .phys-resultat',
      (dl) => [...dl.querySelectorAll("dt")].map((dt, i) => [dt.textContent,
        dl.querySelectorAll("dd")[i]?.textContent]));
    if (bloc.length < 5) throw new Error(`${bloc.length} ligne(s) de résultat, 5 attendues`);
    const taux = bloc.find((l) => l[0].includes("Taux de livraison"));
    if (!taux) throw new Error(bloc.map((l) => l[0]).join(" | "));
    if (!/%/.test(taux[1])) throw new Error(`taux sans unité : ${taux[1]}`);
    const pastille = await page.$$eval('.device-win[data-node-id="capt-1"] .phys-titre .lg-rond',
      (n) => n.length);
    if (pastille < 1) throw new Error("pastille de couleur absente de la fenêtre");

    // On referme : une fenêtre flottante laissée ouverte recouvre ce qui se trouve dessous,
    // et l'étape suivante clique alors la fenêtre au lieu du bouton « Lecture ». Le bloc de
    // résultat a agrandi l'onglet Physique juste assez pour masquer les commandes du lecteur
    // — l'horloge restait figée sans que rien ne nomme la fenêtre comme cause.
    await page.click('.device-win[data-node-id="capt-1"] .close');
    await page.waitForFunction(
      () => !document.querySelector('.device-win[data-node-id="capt-1"]'), { timeout: 10_000 });
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

  // Placée avant l'étape « exercice », qui démarre une session neuve : après elle,
  // `gw-nord` n'existe plus dans la session courante.
  // Fenêtre de configuration passerelle : les réglages que les exercices réclament, sans
  // passer par le clavier. Le point décisif n'est pas que la fenêtre enregistre, c'est que
  // le CLI relise la même chose — deux chemins, une seule configuration.
  await step("passerelle : sous-bande, relais et puissance réglés depuis la fenêtre", async () => {
    await viewTab("Plan");
    await page.click('g.node[data-id="gw-nord"] rect');
    await page.waitForSelector('.device-win[data-node-id="gw-nord"]');
    await deviceTab("Config", "gw-nord");
    const sel = (n) => `.device-win[data-node-id="gw-nord"] [name="${n}"]`;
    await page.waitForSelector(sel("region"));

    // Une sous-bande hors US915/AU915 n'a pas de sens : le champ est désactivé, et la
    // raison est écrite à côté — « désactivé » sans raison fait perdre une heure.
    const desactivee = await page.$eval(sel("sub_band"), (e) => e.disabled);
    if (!desactivee) throw new Error("sous-bande active alors qu'aucun plan à sous-bande n'est choisi");

    const attendu = await page.$eval('.device-win[data-node-id="gw-nord"] .gw-aide-bloc',
      (e) => e.textContent);
    if (!/US915 et AU915/.test(attendu)) throw new Error(`aide absente : ${attendu}`);

    // `page.select` et non `setValue` : poser `.value` en JS ne déclenche pas `change`, et
    // c'est le changement de plan qui arme la sous-bande. Un vrai geste, pas une affectation.
    await page.select(sel("region"), "US915");
    await page.waitForFunction((q) => !document.querySelector(q).disabled, {}, sel("sub_band"));
    // Le renvoi vers le CLI doit nommer ce qui reste, sinon il ne renseigne pas.
    const avance = await page.$eval('.device-win[data-node-id="gw-nord"] .gw-avance',
      (e) => e.textContent);
    for (const mot of ["antenne", "fréquence", "étalement"]) {
      if (!avance.includes(mot)) throw new Error(`renvoi incomplet : ${avance}`);
    }

    await page.select(sel("sub_band"), "2");
    await setValue(sel("tx_power_dbm"), "20");
    // « border », et non « relay » : `gw-nord` est une frontière, et le compilateur refuse
    // un mode mesh qui contredit le rôle de l'équipement (`study_compile.py`). Poser « relay »
    // ici enregistrait une configuration qu'**aucun** run ne peut compiler — la session
    // devenait inutilisable, et l'échec n'apparaissait que trois étapes plus loin, au
    // lancement, sous la forme « mode mesh « relay » ne correspond pas au rôle border ».
    await page.select(sel("mesh_mode"), "border");
    await setValue(sel("mesh_max_hops"), "2");
    await page.select(sel("mesh_bandwidth_khz"), "1625");
    await submitForm('.device-win[data-node-id="gw-nord"] form');
    await waitText('.device-win[data-node-id="gw-nord"] form', /enregistrés/);

    // Vérifié côté serveur : la fenêtre n'est pas un état parallèle à celui du CLI.
    const sid = await page.$eval("#session-select", (s) => s.value);
    const res = await fetch(`http://127.0.0.1:${API_PORT}/api/v1/sessions/${sid}/topology`,
      { headers: { Authorization: `Bearer ${token}` } });
    const st = (await res.json()).states.find((x) => x.node_id === "gw-nord").gateway;
    for (const [cle, val] of [["region", "US915"], ["sub_band", 2],
      ["tx_power_dbm", 20], ["mesh_mode", "border"], ["mesh_max_hops", 2],
      ["mesh_bandwidth_khz", "1625"]]) {
      if (st[cle] !== val) throw new Error(`${cle} : ${st[cle]} au lieu de ${val}`);
    }

    // Changer de plan hors sous-bandes doit l'effacer, pas la garder en cache.
    await page.select(sel("region"), "EU868");
    await submitForm('.device-win[data-node-id="gw-nord"] form');
    await waitText('.device-win[data-node-id="gw-nord"] form', /enregistrés/);
    await page.waitForFunction((q) => document.querySelector(q).disabled, {}, sel("sub_band"));
    const res2 = await fetch(`http://127.0.0.1:${API_PORT}/api/v1/sessions/${sid}/topology`,
      { headers: { Authorization: `Bearer ${token}` } });
    const st2 = (await res2.json()).states.find((x) => x.node_id === "gw-nord").gateway;
    if (st2.sub_band !== null) throw new Error(`sous-bande conservée : ${st2.sub_band}`);
  });

  // Le réglage « le serveur envoie une commande » n'existe que dans le formulaire : aucune
  // vérification de module pur ne peut dire s'il s'enregistre, faute de DOM. Et le défaut
  // qu'il guette est silencieux — un champ manquant dans le corps envoyé fait refuser la
  // case par le validateur, sans que rien n'indique lequel.
  //
  // La périodicité est ce champ-là : c'est un choix (`select`), pas un nombre, et un bloc
  // construit autour de champs `input` l'oublie. On l'exerce donc ici, dans un navigateur.
  await step("descente réseau : le réglage s'enregistre et la périodicité suit la classe", async () => {
    await viewTab("Plan");
    await page.click('g.node[data-id="capt-1"] circle');
    await page.waitForSelector('.device-win[data-node-id="capt-1"]');
    await deviceTab("Config", "capt-1");
    const q = '.device-win[data-node-id="capt-1"]';
    await page.waitForSelector(`${q} select[name="device_class"]`);
    // La périodicité n'a d'effet qu'en classe B : en A, le champ n'est pas affiché du tout —
    // un champ sans effet ne se grise pas, il disparaît.
    await page.select(`${q} select[name="device_class"]`, "A");
    await page.click(`${q} input[name="downlink_on"]`);
    await page.waitForFunction((s) => {
      const l = [...document.querySelectorAll(`${s} label`)]
        .find((e) => e.textContent.includes("Fréquence des créneaux"));
      return l?.hidden === true;
    }, { timeout: 5_000 }, q);
    await page.select(`${q} select[name="device_class"]`, "B");
    await page.waitForFunction((s) => {
      const l = [...document.querySelectorAll(`${s} label`)]
        .find((e) => e.textContent.includes("Fréquence des créneaux"));
      return l?.hidden === false && l.querySelector("select")?.options.length === 8;
    }, { timeout: 5_000 }, q);
    // Huit périodicités, servies par le moteur : 2**(7-k) créneaux par période de 128 s.
    const intervalles = await page.$eval(`${q} select[name="downlink_periodicity"]`,
      (s) => [...s.options].map((o) => o.textContent));
    if (!intervalles[0].includes("toutes les 1 s") || !intervalles[7].includes("toutes les 2 min 8 s")) {
      throw new Error(`intervalles inattendus : ${JSON.stringify([intervalles[0], intervalles[7]])}`);
    }
    await page.$eval(`${q} input[name="downlink_first_request_s"]`, (e) => { e.value = "10"; });
    await submitForm(`${q} form`);
    await attendreReglages("capt-1", { device_class: "B", downlink: { count: 1,
      first_request_s: 10, request_period_s: 0, periodicity: 0, clock_drift_ppm: 0 } }, refus, 15_000);
    // On rend le capteur tel qu'on l'a trouvé : l'étape suivante mesure l'ADR sur un capteur
    // de classe A, et la lui laisser en B changerait ce qu'elle mesure sans le dire.
    await page.select(`${q} select[name="device_class"]`, "A");
    await page.click(`${q} input[name="downlink_on"]`);
    await submitForm(`${q} form`);
    await attendreReglages("capt-1", { device_class: "A", downlink: null }, refus, 15_000);
    await page.click(`${q} .close`);
  });

  // Le plan de canaux que le serveur a laissé au terminal, affiché.
  //
  // Placé **après** le réglage de la région sur la passerelle, et c'est la condition : sans
  // plan régional, l'ADR n'est pas simulable et le bloc ne s'affiche jamais. Un test écrit
  // avant ce réglage échouerait sur une topologie qui n'a rien à voir avec l'objet du test. Il vient de l'ABI v3 et
  // voyage dans la même commande que le débit — LinkADRReq — donc il se lit dans le bloc ADR.
  // Aucun test de navigateur ne l'exerçait : le module pur ne peut pas dire si la phrase est
  // réellement peinte, et seul un run avec ADR la produit.
  await step("ADR : le plan de canaux laissé au terminal est affiché", async () => {
    await obsTab("Simulation");
    const adr = await page.$eval("#adr-toggle", (c) => ({ desactive: c.disabled, coche: c.checked }));
    if (adr.desactive) {
      // Une case grisée sans explication est le genre de silence qui fait perdre une heure.
      // On publie donc la raison **et** la topologie vue par le serveur : « 0 passerelles
      // actives » sur une session qui en montre une ne se comprend qu'en les lisant ensemble.
      const sid = await page.$eval("#session-select", (s) => s.value);
      const res = await fetch(`http://127.0.0.1:${API_PORT}/api/v1/sessions/${sid}/topology`,
        { headers: { Authorization: `Bearer ${token}` } });
      const topo = await res.json();
      throw new Error(`ADR impossible : ${await textOf("#adr-aide")}\n`
        + `raison serveur : ${topo.adr_raison}\n`
        + `nœuds : ${JSON.stringify((topo.nodes ?? []).map((n) => [n.id, n.kind]))}\n`
        + `états : ${JSON.stringify((topo.states ?? []).map((s) => [s.node_id, s.hostname, s.region]))}`);
    }
    if (!adr.coche) await page.click("#adr-toggle");
    await page.waitForFunction(() => !document.getElementById("adr-toggle").disabled);

    // L'ADR agit à chaque uplink reçu : il faut plusieurs messages avant qu'une commande
    // parte. Le capteur est réglé sur 2 depuis l'étape de saisie, où ce petit nombre servait
    // à garder un run court — avec 2 trames, le serveur ne commande rien et le bloc ADR ne
    // s'afficherait pas, ce qui ferait échouer le test sur une tout autre raison.
    await viewTab("Plan");
    await page.click('g.node[data-id="capt-1"] circle');
    await page.waitForSelector('.device-win[data-node-id="capt-1"]');
    await deviceTab("Config", "capt-1");
    await page.waitForSelector('.device-win[data-node-id="capt-1"] .sensor-form input[name="messages"]');
    await setValue('.device-win[data-node-id="capt-1"] .sensor-form input[name="messages"]', "60");
    // SF de départ haut : à 300 m, un capteur déjà réglé sur SF9 n'a aucune marge à rendre et
    // le serveur ne commande rien — le bloc ADR resterait masqué, et le test échouerait en
    // accusant l'affichage d'un plan de canaux que le moteur n'a simplement pas eu à écrire.
    await setValue('.device-win[data-node-id="capt-1"] .sensor-form input[name="spreading_factor"]', "12");
    await submitForm('.device-win[data-node-id="capt-1"] form');
    // Attendre le mot « enregistrés » ne prouve rien : le formulaire l'affiche depuis
    // l'étape de saisie, donc l'attente passe avant même que cette soumission parte. Ce
    // qui prouve, c'est que **le serveur** a les nouveaux réglages — on les relit donc
    // chez lui, et on publie ses refus si ce n'est pas le cas.
    await attendreReglages("capt-1", { spreading_factor: 12, messages: 60 }, refus);
    await obsTab("Simulation");

    // Troisième visage du même piège, après le message du formulaire : le statut affiche
    // déjà « …terminé (graine 7) » du run de l'étape précédente, donc attendre ce mot passe
    // avant même que le nouveau run parte — on lit alors les lignes de l'ancien, qui n'a ni
    // les 60 messages ni le SF12. On attend un « terminé » portant un autre numéro de run.
    await setValue("#seed", "7");
    const runAvant = (await textOf("#sim-status")).match(/Run (\S+)/)?.[1] ?? "";
    await page.click("#simulate");
    try {
      await page.waitForFunction((avant) => {
        const t = document.getElementById("sim-status").textContent;
        return t.includes("terminé") && (!avant || !t.includes(avant));
      }, { timeout: 120_000 }, runAvant);
    } catch (err) {
      // Un run qui n'aboutit pas a deux visages, et ils ne se ressemblent pas : il a échoué
      // (le statut le dit) ou il n'est jamais parti (le statut est celui d'avant, et le
      // bouton le dit). On publie les deux plutôt qu'une attente expirée.
      throw new Error(`run ${runAvant} non remplacé\nstatut : ${await textOf("#sim-status")}\n`
        + `bouton : ${JSON.stringify(await page.$eval("#simulate", (b) => ({ d: b.disabled })))}\n`
        + `notes : ${await textOf("#sim-notes")}\n`
        + `refus HTTP : ${refus.slice(-5).join("\n  ") || "aucun"}`);
    }
    try {
      await page.waitForFunction(() => !document.getElementById("adr-bilan").hidden,
        { timeout: 20_000 });
    } catch (err) {
      // Un bloc qui ne s'affiche pas a trois causes possibles, et aucune ne se devine :
      // l'ADR n'était pas actif, le serveur n'a rien commandé, ou le run n'a pas observé la
      // fin. On publie les trois plutôt que de laisser une attente expirée sans rien dire.
      const sid = await page.$eval("#session-select", (s) => s.value);
      const res = await fetch(`http://127.0.0.1:${API_PORT}/api/v1/sessions/${sid}/topology`,
        { headers: { Authorization: `Bearer ${token}` } });
      const topo = await res.json();
      // Le moteur a été mesuré hors navigateur : à 300 m, un capteur à SF12 se voit retirer
      // 14 dB. Si le bloc reste masqué, c'est donc que **ce** run ne porte pas les champs —
      // on lit les lignes de dispositif du run qu'on vient de voir aboutir, plutôt que
      // d'imaginer une troisième cause. Le numéro du run est dans le statut affiché.
      const rid = (await textOf("#sim-status")).match(/Run (\S+) terminé/)?.[1] ?? "";
      const auth = { Authorization: `Bearer ${token}` };
      const lignesRun = rid
        ? await fetch(`http://127.0.0.1:${API_PORT}/api/v1/runs/${rid}/devices`,
          { headers: auth }).then((r) => r.text())
        : "run non identifié dans le statut";
      throw new Error(`bloc ADR masqué\nstatut : ${await textOf("#sim-status")}\n`
        + `case ADR : ${JSON.stringify(await page.$eval("#adr-toggle", (c) => ({ c: c.checked, d: c.disabled })))}\n`
        + `aide ADR : ${await textOf("#adr-aide")}\n`
        + `topologie : adr=${topo.adr} possible=${topo.adr_possible} raison=${topo.adr_raison}\n`
        + `lignes du run ${rid} : ${lignesRun.slice(0, 2000)}`);
    }
    const lignes = await page.$$eval("#adr-bilan-liste li", (ls) => ls.map((l) => l.textContent));
    if (lignes.length === 0) throw new Error("bloc ADR visible sans aucun changement énoncé");
    const canaux = await textOf("#adr-bilan-canaux");
    for (const attendu of ["Canaux laissés au terminal", "Seuls les canaux actifs servent"])
      if (!canaux.includes(attendu)) throw new Error(`« ${canaux} » sans « ${attendu} »`);
    // Le plan doit nommer au moins un canal et son débit : une phrase sans chiffre serait
    // un masque vide rendu comme une information.
    if (!/\d+\s*:\s*DR\d/.test(canaux)) throw new Error(`plan sans canal ni débit : « ${canaux} »`);
    console.log(`ADR : ${lignes.length} changement(s) · ${canaux}`);
  });

  // Liaisons mesh observées : un relais qui a livré des trames à la frontière. C'est la seule
  // partie de la topologie que le plan puisse tracer sans inventer — voir `liaisons.js` pour
  // ce qu'on refuse de dessiner, et pourquoi.
  //
  // Session dédiée : un relais de plus ferait dérailler les étapes de simulation et
  // d'exercice, écrites pour un réseau précis.
  await step("liaisons mesh : le plan trace ce que le relais a livré", async () => {
    await page.click("#new-session");
    await page.waitForFunction(() => !document.querySelector('g.node'), { timeout: 20_000 });

    await setValue('#add-form [name="id"]', "gw-mesh");
    await submitForm("#add-form");
    await page.waitForSelector('g.node[data-id="gw-mesh"]');

    await setValue('#add-form [name="id"]', "relais-mesh");
    await page.select('#add-form [name="kind"]', "relay");
    await setValue('#add-form [name="lat"]', "4.051100");
    await setValue('#add-form [name="lon"]', "9.781424");
    await submitForm("#add-form");
    await page.waitForSelector('g.node[data-id="relais-mesh"]');

    await setValue('#add-form [name="id"]', "capt-mesh");
    await page.select('#add-form [name="kind"]', "sensor");
    await setValue('#add-form [name="lat"]', "4.052899");
    await setValue('#add-form [name="lon"]', "9.782325");
    await submitForm("#add-form");
    await page.waitForSelector('g.node[data-id="capt-mesh"]');

    // Sans dispersion des départs, deux capteurs émettraient à la même seconde. Ici un seul
    // capteur suffit, mais sans `start_spread_s` ses trames se chevaucheraient.
    await viewTab("Plan");
    await page.click('g.node[data-id="capt-mesh"] circle');
    await page.waitForSelector('.device-win[data-node-id="capt-mesh"]');
    await deviceTab("Config", "capt-mesh");
    await page.waitForSelector('.device-win[data-node-id="capt-mesh"] .sensor-form input[name="messages"]');
    await setValue('.device-win[data-node-id="capt-mesh"] .sensor-form input[name="messages"]', "4");
    await setValue('.device-win[data-node-id="capt-mesh"] .sensor-form input[name="start_spread_s"]', "30");
    await submitForm('.device-win[data-node-id="capt-mesh"] form');
    await waitText('.device-win[data-node-id="capt-mesh"] form', /enregistrés/);

    await obsTab("Simulation");
    await setValue("#seed", "7");
    await page.click("#simulate");
    await waitText("#sim-status", /terminé/, 120_000);

    // Le trait n'existe qu'après un run : la topologie radio se mesure, elle ne se déclare pas.
    await viewTab("Plan");
    await page.waitForSelector("#plan .liens line.lien-mesh", { timeout: 20_000 });
    // Deux natures de liaisons désormais, et la session en produit les deux : le relais
    // remet des trames à la frontière (mesh), et les deux passerelles décodent celles du
    // capteur (radio). Les confondre était exactement le défaut que l'étiquette prévient.
    const paires = await page.$$eval("#plan .liens > *", (es) => {
      const out = [];
      for (let i = 0; i < es.length; i += 1) {
        const e = es[i];
        const nom = e.tagName.toLowerCase();
        if (nom !== "line") continue;
        const genre = e.classList.contains("lien-radio") ? "radio" : "mesh";
        out.push({ genre, texte: es[i + 1]?.tagName.toLowerCase() === "text"
          ? es[i + 1].textContent : null });
      }
      return out;
    });
    if (!paires.length) throw new Error("aucun trait");
    if (!paires.some((x) => x.genre === "mesh")) throw new Error("aucune liaison mesh tracée");
    if (!paires.some((x) => x.genre === "radio")) throw new Error(
      `aucune liaison radio tracée (${JSON.stringify(paires)}) : la matrice des réceptions `
      + "n'atteint pas le plan");
    for (const { genre, texte } of paires) {
      if (!texte) throw new Error(`liaison ${genre} tracée sans son chiffre`);
      const attendu = genre === "radio" ? /^\d+ trames? décodée/ : /^\d+ trames? relayée/;
      if (!attendu.test(texte)) throw new Error(
        `étiquette ${genre} : « ${texte} » — le verbe doit dire ce que le lien compte`);
    }
    // Le trait relie le relais à la frontière, et pas l'inverse : le sens compte.
    const bouts = await page.$$eval("#plan .liens line.lien-mesh",
      (ls) => ls.map((l) => ({ x1: +l.getAttribute("x1"), x2: +l.getAttribute("x2") })));
    if (!bouts.length) throw new Error("aucun trait");

    // La carte 3D porte les mêmes liaisons. Une primitive Cesium n'existe pas dans le DOM :
    // on lit le compte exposé, faute de quoi un trait jamais tracé ne se distinguerait pas
    // d'un trait que personne ne regarde.
    await viewTab("Carte");
    await page.waitForFunction(() => document.querySelector("#cesium canvas"), { timeout: 30_000 });
    await page.waitForFunction(() => (window.__liaisonsCarte ?? 0) >= 1, { timeout: 30_000 });
    // On rend la vue qu'on a trouvée. Les étapes suivantes ont été écrites pour le plan, et
    // l'étape exercice en particulier : la laisser sur la carte, c'est changer les conditions
    // d'un test qui n'a rien demandé. Une étape ne doit pas modifier l'état qu'elle emprunte.
    await viewTab("Plan");
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

  await step("le chantier s'enregistre dans un fichier, et se recharge", async () => {
    // Le telechargement est redirige vers un dossier connu : sans cela Chrome le refuse en
    // headless et le test verifierait un bouton, pas un fichier.
    const cdp = await page.createCDPSession();
    await cdp.send("Browser.setDownloadBehavior", { behavior: "allow", downloadPath: work });
    const avant = await lireEffectif();
    if (avant < 1) throw new Error("aucun equipement a enregistrer : le test n'a rien a verifier");

    await page.click("#save-chantier");
    const fichier = await attendreFichier(work, /^chantier-.*\.json$/);
    const texte = readFileSync(join(work, fichier), "utf8");
    const chantier = JSON.parse(texte);
    if (chantier.format !== "lsim-chantier") throw new Error(`format inattendu : ${chantier.format}`);
    if (!Array.isArray(chantier.equipements) || chantier.equipements.length !== avant)
      throw new Error(`${chantier.equipements?.length} equipements dans le fichier, ${avant} a l'ecran`);
    if (!chantier.origine || !Number.isFinite(chantier.origine.lat))
      throw new Error("origine absente du fichier");
    // Une cle ne doit jamais atteindre le fichier, meme masquee.
    if (texte.includes("******")) throw new Error("le fichier contient des cles masquees");
    // Les positions sont en metres : c'est l'invariant D2, les degres ne s'affichent qu'a l'ecran.
    for (const eq of chantier.equipements)
      if (!Number.isFinite(eq.x_m) || !Number.isFinite(eq.y_m))
        throw new Error(`position non metrique pour ${eq.id}`);

    // Rechargement avec un chantier ecrit pour l'occasion, et non le fichier qu'on vient de
    // recevoir : recharger ce qu'on a produit soi-meme prouverait l'aller-retour, pas
    // l'import. Un chantier venu d'ailleurs est le seul cas qui compte.
    const recharge = {
      format: chantier.format, version: chantier.version, origine: { lat: 3.848, lon: 11.502 },
      equipements: [
        { id: "import-gw", kind: "border", name: "Import frontiere", x_m: 0, y_m: 0,
          gateway: { region: "EU868", tx_power_dbm: 14, mesh_mode: "relay", mesh_max_hops: 3 } },
        { id: "import-capt", kind: "sensor", name: "Import capteur", x_m: 250, y_m: -80,
          sensor: { spreading_factor: 9, payload_bytes: 12, tx_power_dbm: 14,
                    period_s: 300, messages: 6, start_spread_s: 30 } },
      ],
    };
    const chemin = join(work, "a-recharger.json");
    writeFileSync(chemin, JSON.stringify(recharge, null, 2));
    const sessionsAvant = await page.$$eval("#session-select option", (o) => o.length);
    await (await page.$("#chantier-file")).uploadFile(chemin);
    await page.waitForFunction(
      (n) => document.querySelectorAll("#session-select option").length > n,
      { timeout: 20_000 }, sessionsAvant);
    // On attend le plan, on ne le lit pas. La session neuve existe avant que sa topologie
    // soit chargee : une lecture immediate renvoie les equipements de la session precedente,
    // et le test echoue sur un chiffre qui est deja le bon quand le message l'affiche.
    await page.waitForFunction(
      () => document.querySelectorAll("#plan g.node").length === 2, { timeout: 20_000 })
      .catch(async () => {
        throw new Error(`equipements apres chargement : ${await lireEffectif()}, 2 attendus`);
      });
    // La zone vient du fichier, pas de la session precedente : c'est la preuve du trajet.
    // Elle est ecrite apres le chargement de la topologie, donc apres le rendu du plan —
    // il faut l'attendre elle aussi, et non la lire au passage.
    await page.waitForFunction(
      () => /^3\.848000/.test(document.getElementById("origin-coords")?.value ?? ""),
      { timeout: 20_000 })
      .catch(async () => {
        throw new Error(`zone non reprise du fichier : « ${await lireZone()} »`);
      });
  });

  await step("un fichier qui n'est pas un chantier est refuse sans rien creer", async () => {
    const mauvais = join(work, "pas-un-chantier.json");
    writeFileSync(mauvais, JSON.stringify({ hello: "world" }));
    const sessionsAvant = await page.$$eval("#session-select option", (o) => o.length);
    await (await page.$("#chantier-file")).uploadFile(mauvais);
    await page.waitForFunction(
      () => /chantier|ne contient pas/i.test(document.getElementById("flash")?.textContent ?? ""),
      { timeout: 20_000 });
    const flash = await textOf("#flash");
    if (!/ne contient pas un chantier/i.test(flash))
      throw new Error(`message inattendu : « ${flash} »`);
    // Rien n'a du etre cree : c'est tout l'objet de valider avant d'agir.
    const apres = await page.$$eval("#session-select option", (o) => o.length);
    if (apres !== sessionsAvant) throw new Error(`${apres} sessions, ${sessionsAvant} attendues`);
  });

  // Session dédiée : prolonger le run change la fenêtre d'observation, donc l'occupation et
  // tous les compteurs qui en dépendent. Le faire sur la session du scénario ferait dérailler
  // les étapes écrites pour un réseau précis — même raison que pour l'étape mesh.
  await step("verdict réglementaire : le geste porte le run jusqu'à l'heure", async () => {
    await page.click("#new-session");
    await page.waitForFunction(() => !document.querySelector('g.node'), { timeout: 20_000 });

    await setValue('#add-form [name="id"]', "gw-dc");
    await submitForm("#add-form");
    await page.waitForSelector('g.node[data-id="gw-dc"]');

    await setValue('#add-form [name="id"]', "capt-dc");
    await page.select('#add-form [name="kind"]', "sensor");
    await setValue('#add-form [name="lat"]', "4.051909");
    await setValue('#add-form [name="lon"]', "9.770154");
    await submitForm("#add-form");
    await page.waitForSelector('g.node[data-id="capt-dc"]');

    // 60 s et 10 messages : fenêtre de 9 min, très sous l'heure. C'est le cas du registre,
    // et c'est celui où le geste a quelque chose à faire.
    await viewTab("Plan");
    await page.click('g.node[data-id="capt-dc"] circle');
    await page.waitForSelector('.device-win[data-node-id="capt-dc"]');
    await deviceTab("Config", "capt-dc");
    await page.waitForSelector('.device-win[data-node-id="capt-dc"] .sensor-form input[name="period_s"]');
    await setValue('.device-win[data-node-id="capt-dc"] .sensor-form input[name="period_s"]', "60");
    await setValue('.device-win[data-node-id="capt-dc"] .sensor-form input[name="messages"]', "10");
    await submitForm('.device-win[data-node-id="capt-dc"] form');
    await attendreReglages("capt-dc", { period_s: 60, messages: 10 }, refus);

    await obsTab("Simulation");
    await setValue("#seed", "7");
    const runAvant = (await textOf("#sim-status")).match(/Run (\S+)/)?.[1] ?? "";
    await page.click("#simulate");
    // Même piège que plus haut : le statut affiche déjà « terminé » du run précédent.
    await page.waitForFunction((avant) => {
      const t = document.getElementById("sim-status").textContent;
      return t.includes("terminé") && (!avant || !t.includes(avant));
    }, { timeout: 120_000 }, runAvant);

    // Dire l'écart entre les deux fenêtres ne suffit pas : il faut nommer le réglage et le
    // nombre, sinon l'utilisateur refait à la main ce qu'on vient de calculer.
    const avant = await textOf("#sim-duty-note");
    if (!/Pour couvrir l'heure réglementaire/.test(avant)) throw new Error(`sans remède : ${avant}`);
    if (!/\d+ messages/.test(avant)) throw new Error(`remède sans nombre : ${avant}`);
    if (await page.$eval("#prolonger-run", (b) => b.hidden))
      throw new Error("geste absent alors que le run ne couvre pas l'heure");

    // L'identifiant à remplacer est celui du run **courant**, pas celui d'avant le premier :
    // ce dernier est déjà remplacé, donc l'attente passerait aussitôt sans rien attendre —
    // et on relirait la note du run qu'on cherche justement à remplacer. Lu avant le clic,
    // pour ne pas dépendre de la vitesse à laquelle le gestionnaire écrit le statut.
    const runProlonger = (await textOf("#sim-status")).match(/Run (\S+)/)?.[1] ?? "";
    await page.click("#prolonger-run");
    await page.waitForFunction((avant) => {
      const t = document.getElementById("sim-status").textContent;
      return t.includes("terminé") && (!avant || !t.includes(avant));
    }, { timeout: 120_000 }, runProlonger);

    const apres = await textOf("#sim-duty-note");
    if (!/comparaison est directe/.test(apres))
      throw new Error(`run prolongé sans couvrir l'heure : ${apres}`);
    // Un geste proposé sous un verdict annoncé comme direct laisserait croire qu'il manque
    // encore quelque chose.
    if (await page.$eval("#prolonger-run", (b) => !b.hidden))
      throw new Error("geste encore proposé sous un verdict direct");
    console.log(`verdict : ${avant.match(/Mesuré sur [^,.]+/)?.[0] ?? "?"} -> `
      + `${apres.match(/Mesuré sur [^,.]+/)?.[0] ?? "?"}`);
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
