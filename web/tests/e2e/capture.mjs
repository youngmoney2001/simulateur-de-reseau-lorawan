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
  /** Le bloc seul, et pas la page entière : sur une capture plein écran l'encadré tient
   *  dans une centaine de pixels et ses chiffres ne se lisent qu'à la loupe. Le recadrage
   *  est demandé au navigateur sur l'élément lui-même, donc il suit la mise en page au
   *  lieu de figer des coordonnées qui casseraient au premier changement de style. */
  const shootBloc = async (nom, sel) => {
    n += 1;
    const fichier = join(outDir, `${String(n).padStart(2, "0")}-${nom}.png`);
    const h = await page.$(sel);
    if (!h) throw new Error(`${sel} introuvable : le recadrage n'a rien à cadrer`);
    await h.screenshot({ path: fichier });
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
  for (const [id, lat, lon] of [["capteur-a", "4.051909", "9.770154"],
                                ["capteur-b", "4.054158", "9.773490"],
                                ["capteur-c", "4.054967", "9.769523"]]) {
    await setValue('#add-form [name="id"]', id);
    await page.select('#add-form [name="kind"]', "sensor");
    await setValue('#add-form [name="lat"]', lat);
    await setValue('#add-form [name="lon"]', lon);
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

  // 7. le protocole à l'œuvre : ce que les réglages CHANGENT, et pas seulement à quoi ils
  // ressemblent. Les captures 1 à 6 montrent l'atelier au repos ; celles-ci montrent trois
  // runs de la même flotte, seul le réglage différant :
  //   - départs simultanés : les join-request se collisionnent, la flotte ne joint pas ;
  //   - départs étalés de 60 s : les trois capteurs joignent, et les ACK suivent ;
  //   - ADR : le serveur commande un débit plus rapide — à condition que les uplinks lui
  //     parviennent, ce que la même dispersion permet.
  //
  // Chiffres mesurés sur cette flotte (graine 1, SF12), et que les images doivent porter :
  //   simultané : 41 join-request → 1 acceptée, 19 uplinks, 19 ACK
  //   étalé 60 s :  4 join-request → 3 acceptées, 56 uplinks, 56 ACK
  //   ADR       : les 3 capteurs passent SF12 → SF7
  // L'encadré ne s'ouvre que si le run les porte : une capture au bloc masqué est un échec,
  // et c'est voulu — une image vide ne prouverait rien.
  await page.setViewport({ width: 1400, height: 1000 });
  await pause(400);

  const sid = await page.$eval("#session-select option", (o) => o.value);
  const appeler = async (chemin, corps) => {
    const res = await fetch(`http://127.0.0.1:${API_PORT}${chemin}`, {
      method: corps === undefined ? "GET" : "POST",
      headers: { Accept: "application/json", Authorization: `Bearer ${token}`,
        ...(corps === undefined ? {} : { "Content-Type": "application/json" }) },
      body: corps === undefined ? undefined : JSON.stringify(corps),
    });
    if (!res.ok) throw new Error(`${chemin} : HTTP ${res.status} — ${await res.text()}`);
    return res.status === 204 ? null : res.json();
  };
  // `POST .../sensor` **remplace** les réglages : on renvoie donc l'objet entier, et non
  // un patch qui effacerait la période ou la charge utile à l'insu de la suite.
  const reglerFlotte = async ({ sf, messages, etale }) => {
    for (const id of ["capteur-a", "capteur-b", "capteur-c"]) {
      await appeler(`/api/v1/sessions/${encodeURIComponent(sid)}/nodes/${id}/sensor`,
        { spreading_factor: sf, payload_bytes: 10, tx_power_dbm: 14.0, period_s: 600,
          messages, start_spread_s: etale });
    }
  };
  // Plan régional sur la passerelle : l'ADR en a besoin (le moteur refuse sans lui) et la
  // jointure s'en accommode. Réglé une fois pour les trois runs.
  await appeler(`/api/v1/sessions/${encodeURIComponent(sid)}/nodes/gw-nord/gateway`,
    { region: "EU868" });

  /** Lance un run et attend qu'il soit **terminé**, en vidant le statut d'abord : sans cela
   *  le message du run précédent ferait croire que le nouveau est fini avant qu'il parte. */
  const lancerRun = async () => {
    await page.evaluate(() => { const s = document.querySelector("#sim-status"); if (s) s.textContent = ""; });
    await page.click("#simulate");
    await page.waitForFunction(
      () => (document.querySelector("#sim-status")?.textContent ?? "").includes("terminé"),
      { timeout: 180_000 });
    await pause(700);
  };
  /** Coche ou décoche une case et **attend que le serveur ait répondu**. Deux clics
   *  rapprochés partiraient en concurrence : le second lit l'état du premier, et rien ne
   *  garantit l'ordre d'arrivée — la dernière réponse gagne et peut remettre la case
   *  qu'on vient de cocher. Attendre la case rend la suite déterministe. */
  const basculer = async (id, etat) => {
    await page.click(id);
    await page.waitForFunction((s, v) => document.querySelector(s).checked === v,
      { timeout: 15_000 }, id, etat);
  };
  /** L'encadré `sel` doit être visible et porter au moins `min` lignes. C'est l'assertion
   *  qui donne son sens à la capture : un encadré masqué ou vide, et l'image ne prouve
   *  rien — le script échoue alors, au lieu de publier une case vide. */
  const attendre = (sel, min) => page.waitForFunction((s, n) => {
    const bloc = document.querySelector(s);
    return !!bloc && !bloc.hidden && bloc.querySelectorAll("li").length >= n;
  }, { timeout: 20_000 }, sel, min);

  // 7a. départs simultanés : la jointure n'aboutit pas
  await obsTab("Simulation");
  await reglerFlotte({ sf: 12, messages: 20, etale: 0 });
  await basculer("#join-toggle", true);
  await basculer("#confirmed-toggle", true);
  await lancerRun();
  await attendre("#proto-bilan", 2);
  await shoot("protocole-jointure-simultanee");
  await shootBloc("bloc-echanges-simultanee", "#proto-bilan");

  // 7b. même flotte, départs étalés de 60 s : la jointure aboutit, les ACK suivent
  await reglerFlotte({ sf: 12, messages: 20, etale: 60 });
  await lancerRun();
  await attendre("#proto-bilan", 2);
  await shoot("protocole-jointure-etalee");
  await shootBloc("bloc-echanges-etalee", "#proto-bilan");

  // 7c. ADR : l'ordre du serveur, et la condition pour qu'il parte
  await basculer("#confirmed-toggle", false);
  await basculer("#join-toggle", false);
  await reglerFlotte({ sf: 12, messages: 40, etale: 60 });
  await basculer("#adr-toggle", true);
  await lancerRun();
  await attendre("#adr-bilan", 1);
  await shoot("protocole-adr-debit");
  await shootBloc("bloc-adr-debit", "#adr-bilan");

  // On rend ce qu'on a emprunté : les trois cases retrouvent leur état de départ, pour que
  // la session capturée ne reste pas dans une configuration que personne n'a choisie.
  await basculer("#adr-toggle", false);

  // 8. Ce que la session a produit, relu : la liste des runs, puis deux d'entre eux face à
  // face. Trois runs viennent d'être lancés — la liste a donc de quoi se comparer, et une
  // liste d'une seule ligne ne montrerait rien de ce qui fait l'intérêt de l'onglet.
  await obsTab("Runs");
  await page.waitForFunction(() => document.querySelectorAll("#runs-table tbody tr").length >= 3,
    { timeout: 20_000 });
  await pause(400);
  await shoot("runs-liste");

  // Le comparé est la **deuxième** ligne : la première est le run affiché, et le comparer à
  // lui-même donnerait un écart de zéro partout — une image qui ne prouve rien.
  await page.evaluate(() => {
    const trs = document.querySelectorAll("#runs-table tbody tr");
    const bouton = [...trs[1].querySelectorAll("button")]
      .find((b) => b.textContent.trim() === "Comparer");
    if (!bouton) throw new Error("bouton Comparer introuvable sur la deuxième ligne");
    bouton.click();
  });
  await page.waitForFunction(() => !document.getElementById("runs-compare").hidden,
    { timeout: 10_000 });
  await pause(400);
  await shoot("runs-comparaison");

  // 9. Le serveur, tel qu'il a vu le run qu'on vient de lancer. Sa fenêtre ne se remplit
  // qu'avec des mesures : sans run, elle dirait « rien d'observé » — une image d'une case
  // vide. L'attente porte donc sur la table, pas sur la fenêtre.
  await setValue('#add-form [name="id"]', "lns");
  await page.select('#add-form [name="kind"]', "server");
  // Dans la boîte que les autres occupent déjà : un nœud posé au-delà élargit la boîte et
  // change l'échelle du plan, ce qui décalerait toutes les autres captures.
  await setValue('#add-form [name="lat"]', "4.050000");
  await setValue('#add-form [name="lon"]', "9.769500");
  await submitForm("#add-form");
  await page.waitForSelector('g.node[data-id="lns"]');
  // Au clavier : la fenêtre d'un équipement ouverte plus haut recouvre le nœud, et le clic
  // ouvrirait alors tout sauf celle du serveur.
  await page.evaluate(() => document.querySelector('g.node[data-id="lns"]').focus());
  await page.keyboard.press("Enter");
  await page.waitForSelector('.device-win[data-node-id="lns"]', { timeout: 20_000 });
  await deviceTab("Config", "lns");
  await page.waitForSelector('.device-win[data-node-id="lns"] table tbody tr',
    { timeout: 20_000 });
  await pause(400);
  await shoot("serveur-ce-qu-il-a-vu");

  console.log(`${n} captures dans ${outDir}`);
} finally {
  for (const c of children) { try { c.kill("SIGTERM"); } catch { /* déjà arrêté */ } }
  if (browser) await browser.close();
}
