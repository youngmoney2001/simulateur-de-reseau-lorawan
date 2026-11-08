// Indicateurs calculés d'un run (logique pure : ni DOM, ni Cesium, ni réseau).
//
// Principe : chaque indicateur porte sa formule. Un nombre affiché sans sa formule est une
// opinion ; avec elle, il est vérifiable à la main sur les compteurs du run.
//
// Règle de source : rien n'est déduit que des compteurs publiés par le serveur
// (`summary.totals`, `summary.gateway` ou `summary.gateways[]`, lignes `devices`). Aucune
// constante réglementaire n'est appliquée ici — voir `docs/REGULATORY_SOURCES.md` : sur huit
// régions, cinq n'ont aucune limite de rapport cyclique dans le modèle, et aucune limite
// EU868 n'y est sourcée. La phase K **mesure**, elle ne prononce pas de conformité.

const NS_PER_S = 1e9;
const NS_PER_MS = 1e6;

/** Rapport protégé : `null` plutôt que `NaN` ou `Infinity` quand le dénominateur manque. */
export function ratio(numerateur, denominateur) {
  if (!Number.isFinite(numerateur) || !Number.isFinite(denominateur) || denominateur === 0) {
    return null;
  }
  return numerateur / denominateur;
}

/** Somme d'une liste, en ignorant les entrées non numériques (champs optionnels du run). */
export function somme(valeurs = []) {
  let total = 0;
  for (const v of valeurs) if (Number.isFinite(v)) total += v;
  return total;
}

/** Moyenne des valeurs définies ; `null` si aucune n'est exploitable. */
export function moyenne(valeurs = []) {
  const definies = valeurs.filter((v) => Number.isFinite(v));
  return definies.length ? definies.reduce((a, b) => a + b, 0) / definies.length : null;
}

function pct(valeur, decimales = 1) {
  return valeur == null ? "—" : `${(valeur * 100).toFixed(decimales)} %`;
}

function fixe(valeur, decimales) {
  return valeur == null ? "—" : valeur.toFixed(decimales);
}

function entier(valeur) {
  return valeur == null ? "—" : String(Math.round(valeur));
}

// Énergie : le joule seul donne des nombres à rallonge sur des trames de 20 mJ.
function energie(joules) {
  if (joules == null) return "—";
  if (joules !== 0 && Math.abs(joules) < 1) return `${(joules * 1e3).toFixed(2)} mJ`;
  return `${joules.toFixed(3)} J`;
}

/**
 * Fenêtre d'observation du run, en nanosecondes.
 *
 * Une seule passerelle : `summary.gateway.observation_ns`. Plusieurs : la plus longue fenêtre
 * déclarée — les passerelles partagent la même horloge de run, mais ne pas supposer qu'elles
 * publient la même valeur protège contre une passerelle muette (`observation_ns` à 0).
 */
export function fenetreObservationNs(summary) {
  if (summary?.gateway?.observation_ns) return summary.gateway.observation_ns;
  const fenetres = (summary?.gateways ?? [])
    .map((g) => g.observation_ns)
    .filter((v) => Number.isFinite(v) && v > 0);
  return fenetres.length ? Math.max(...fenetres) : null;
}

/** Intervalles d'occupation cumulés (union), en nanosecondes : voir `chargeOfferte`. */
export function occupationNs(summary) {
  if (summary?.gateway?.busy_ns) return summary.gateway.busy_ns;
  const busy = (summary?.gateways ?? []).map((g) => g.busy_ns).filter((v) => Number.isFinite(v));
  return busy.length ? Math.max(...busy) : null;
}

/**
 * Indicateurs réseau.
 *
 * `offeredLoad` et `channelBusy` sont deux grandeurs distinctes qu'il ne faut pas confondre :
 *  - `airtime_ns` **cumule** les trames, y compris celles qui se recouvrent. Rapporté à la
 *    fenêtre d'observation, il donne la charge offerte G d'un canal ALOHA — elle dépasse
 *    librement 1 (mesuré : 4,60 sur un run saturé dont le PDR s'effondre à 5 %).
 *  - `busy_ns` est l'**union** des intervalles d'occupation : c'est le temps d'antenne
 *    effectivement pris, borné par la fenêtre. Son rapport est donc dans [0, 1].
 * Publier le premier comme « occupation » ferait lire « 460 % d'occupation » — d'où les deux.
 */
export function indicateursReseau(summary, lignes = []) {
  const t = summary?.totals ?? {};
  const fenetre = fenetreObservationNs(summary);
  const occupation = occupationNs(summary);
  const envoyees = Number.isFinite(t.sent) ? t.sent : null;

  const parts = repartitionPertes(t);
  const audibles = somme((summary?.gateways ?? []).map((g) => g.audible_frames));
  const airtimeParTrame = ratio(t.airtime_ns, envoyees);
  const debitUtile = ratio(t.received, fenetre / NS_PER_S);
  const pics = (summary?.gateways ?? []).map((g) => g.peak_concurrent)
    .filter((v) => Number.isFinite(v));
  const pic = summary?.gateway?.peak_concurrent ?? (pics.length ? Math.max(...pics) : null);

  // Énergie : absente sans profil (`energy_profile`), ou si la période est trop courte pour
  // la trame (`energy_per_message_j` vaut alors null sur la ligne concernée).
  const energieParMessage = moyenne(lignes.map((l) => l.energy_per_message_j));
  const courantMoyen = moyenne(lignes.map((l) => l.average_current_ua));
  // Sans profil énergie, `somme` renverrait 0 et l'indicateur afficherait « 0.000 J » — un
  // nombre fabriqué, indiscernable d'une mesure nulle. L'absence de mesure doit rester
  // invisible : l'indicateur est alors écarté, pas affiché à zéro.
  const energieRun = energieParMessage == null ? null : somme(
    lignes.map((l) => (Number.isFinite(l.energy_per_message_j) ? l.energy_per_message_j * l.sent : null)));

  const out = [
    {
      id: "pdr",
      label: "Taux de livraison",
      value: ratio(t.received, envoyees),
      text: pct(ratio(t.received, envoyees)),
      hint: "reçues ÷ émises — part des trames arrivées au serveur, doublons dédupliqués",
    },
    parts && {
      id: "pertes",
      label: "Répartition des pertes",
      value: parts.value,
      text: parts.text,
      hint: parts.hint,
    },
    {
      id: "collisions_audibles",
      label: "Collisions parmi les audibles",
      value: ratio(t.lost_collision, audibles || null),
      text: pct(ratio(t.lost_collision, audibles || null)),
      hint: "collisions ÷ trames audibles — une trame hors de portée ne peut pas entrer en collision, d'où ce dénominateur",
    },
    {
      id: "charge",
      label: "Charge offerte",
      value: ratio(t.airtime_ns, fenetre),
      text: fixe(ratio(t.airtime_ns, fenetre), 3),
      hint: "Σ temps d'antenne ÷ fenêtre d'observation — charge ALOHA, dépasse 1 quand les trames se recouvrent",
    },
    {
      id: "occupation",
      label: "Occupation du canal",
      value: ratio(occupation, fenetre),
      text: pct(ratio(occupation, fenetre)),
      hint: "union des intervalles d'occupation ÷ fenêtre — temps d'antenne réellement pris, borné à 100 %",
    },
    {
      id: "airtime",
      label: "Temps d'antenne moyen",
      value: airtimeParTrame == null ? null : airtimeParTrame / NS_PER_MS,
      text: `${fixe(airtimeParTrame == null ? null : airtimeParTrame / NS_PER_MS, 1)} ms`,
      hint: "Σ temps d'antenne ÷ émises — durée moyenne d'une trame sur les ondes",
    },
    {
      id: "debit",
      label: "Débit utile",
      value: debitUtile,
      text: `${fixe(debitUtile, 2)} trame/s`,
      hint: "reçues ÷ durée d'observation — trames livrées par seconde, tous dispositifs confondus",
    },
    {
      id: "simultaneite",
      label: "Simultanéité maximale",
      value: pic ?? null,
      text: pic == null ? "—" : `${pic} trame${pic > 1 ? "s" : ""}`,
      hint: "plus grand nombre de trames audibles en cours au même instant, sur la fenêtre d'observation",
    },
  ];

  if (energieParMessage != null) {
    out.push({
      id: "energie_message",
      label: "Énergie par message",
      value: energieParMessage,
      text: energie(energieParMessage),
      hint: "moyenne des dispositifs — émission, écoute RX1/RX2 et veille ramenés à un message",
    });
  }
  if (energieRun != null) {
    out.push({
      id: "energie_run",
      label: "Énergie du run",
      value: energieRun,
      text: energie(energieRun),
      hint: "Σ (énergie par message × messages émis) — somme sur les dispositifs du run",
    });
  }
  if (courantMoyen != null) {
    out.push({
      id: "courant",
      label: "Courant moyen",
      value: courantMoyen,
      text: `${entier(courantMoyen)} µA`,
      hint: "moyenne des dispositifs — courant moyen sur la période d'émission, veille comprise",
    });
  }

  return out.filter((i) => i && i.value != null);
}

/**
 * Répartition des pertes en parts d'un tout.
 *
 * Repose sur un invariant vérifié sur le moteur : émises = reçues + sensibilité + collision +
 * passerelle occupée. Vérifié sur cinq configurations (chargée, saturée, hors portée,
 * dispositif unique, deux SF) avec une et trois passerelles : dix mesures, dix concordances.
 * Les parts somment donc à 100 % ; `sentinel` signale une rupture au lieu de l'afficher.
 */
export function repartitionPertes(totals = {}) {
  const cles = ["received", "lost_sensitivity", "lost_collision", "lost_gateway_busy"];
  const etiquettes = { received: "reçues", lost_sensitivity: "sensibilité", lost_collision: "collision", lost_gateway_busy: "passerelle occupée" };
  const valeurs = cles.map((k) => (Number.isFinite(totals[k]) ? totals[k] : 0));
  const total = valeurs.reduce((a, b) => a + b, 0);
  if (!Number.isFinite(totals.sent) || totals.sent === 0 || total === 0) return null;
  const parts = cles.map((k, i) => ({ cle: k, label: etiquettes[k], part: valeurs[i] / total }));
  return {
    value: total / totals.sent,
    coherent: total === totals.sent,
    text: parts.filter((p) => p.part > 0).map((p) => `${pct(p.part, 0)} ${p.label}`).join(" · ") || "aucune perte",
    hint: "reçues + sensibilité + collision + passerelle occupée = émises (invariant du moteur) — part de chaque cause",
    parts,
  };
}

/**
 * Indicateurs par passerelle. `lost_*` restent des compteurs bruts : les transformer en
 * pourcentage sans dénominateur clair produirait un taux qui ne veut rien dire.
 */
export function indicateursPasserelle(g = {}) {
  const out = [];
  const audible = Number.isFinite(g.audible_frames) && g.audible_frames > 0 ? g.audible_frames : null;
  if (g.name) out.push({ label: "Passerelle", value: g.name, text: g.name, hint: "nom déclaré dans le scénario" });
  out.push(
    { label: "Occupation", value: ratio(g.busy_ns, g.observation_ns), text: pct(ratio(g.busy_ns, g.observation_ns)), hint: "union des intervalles d'occupation ÷ fenêtre d'observation" },
    { label: "Décodées sur audibles", value: ratio(g.received, audible), text: pct(ratio(g.received, audible)), hint: "reçues ÷ trames audibles (RSSI ≥ sensibilité) à cette passerelle" },
    { label: "Simultanéité maximale", value: g.peak_concurrent ?? null, text: g.peak_concurrent == null ? "—" : String(g.peak_concurrent), hint: "plus grand nombre de trames audibles simultanées" },
  );
  return out.filter((i) => i.value != null);
}

/**
 * Ventilation par groupe : `group` et `index_in_group` sont publiés par le serveur sur chaque
 * ligne de dispositif, le regroupement est donc une agrégation de données du run, pas une
 * reconstitution devinée du scénario.
 */
export function ventilationGroupes(lignes = [], fenetreNs = null) {
  const groupes = new Map();
  for (const l of lignes) {
    const cle = l.group ?? "(sans groupe)";
    if (!groupes.has(cle)) {
      groupes.set(cle, { name: cle, spreadingFactors: new Set(), count: 0, sent: 0, received: 0,
        lostSensitivity: 0, lostCollision: 0, airtimeNs: 0, airtimeMax: 0 });
    }
    const g = groupes.get(cle);
    g.count += 1;
    if (Number.isFinite(l.spreading_factor)) g.spreadingFactors.add(l.spreading_factor);
    g.sent += l.sent ?? 0;
    g.received += l.received ?? 0;
    g.lostSensitivity += l.lost_sensitivity ?? 0;
    g.lostCollision += l.lost_collision ?? 0;
    g.airtimeNs += l.airtime_ns ?? 0;
    if (Number.isFinite(l.airtime_ns)) g.airtimeMax = Math.max(g.airtimeMax, l.airtime_ns);
  }
  return [...groupes.values()].map((g) => {
    const sf = [...g.spreadingFactors].sort((a, b) => a - b);
    const pdr = ratio(g.received, g.sent);
    return {
      name: g.name,
      count: g.count,
      spreadingFactor: sf.length ? sf.map((s) => `SF${s}`).join(", ") : "—",
      sent: g.sent,
      received: g.received,
      lostSensitivity: g.lostSensitivity,
      lostCollision: g.lostCollision,
      pdr,
      pdrText: pct(pdr),
      airtimeMs: g.airtimeNs / NS_PER_MS,
      // Rapport cyclique du dispositif le plus émetteur du groupe. C'est le maximum qui
      // importe face à une limite réglementaire : celle-ci s'applique à chaque émetteur,
      // pas à la moyenne du réseau. Mesure sur la fenêtre d'observation du run — qui n'est
      // pas nécessairement la fenêtre de moyennage du texte réglementaire.
      occupancyMax: ratio(g.airtimeMax, fenetreNs),
      occupancyMaxText: pct(ratio(g.airtimeMax, fenetreNs), 3),
    };
  });
}

/**
 * En-têtes et cellules de la table de ventilation.
 *
 * Une session studio compile **un groupe par équipement** (`study_compile.py` nomme le groupe
 * d'après l'identifiant du capteur) : la colonne « Dispositifs » y vaudrait 1 sur chaque ligne.
 * Un scénario YAML, lui, produit de vrais groupes. La table s'adapte aux deux.
 */
export function ventilationTable(groupes = [], limites = null) {
  // `limites` : Map groupe -> ligne DutyCycleOut du run. Sans elle, la colonne « Limite »
  // reste à « — » : une limite absente n'est pas une limite permissive.
  const unParGroupe = groupes.length > 0 && groupes.every((g) => g.count === 1);
  const entetes = unParGroupe
    ? ["Équipement", "SF", "Émises", "Reçues", "PDR", "Sensibilité", "Collision", "Occupation", "Limite"]
    : ["Groupe", "SF", "Dispositifs", "Émises", "Reçues", "PDR", "Sensibilité", "Collision", "Occupation", "Limite"];
  const lignes = groupes.map((g) => {
    const v = verdictDutyCycle(g, limites?.get(g.name));
    const limite = v.verdict === "sans_limite" ? "aucune"
      : v.verdict === "sans_region" ? "—"
      : `${v.limiteText} · ${v.conforme ? "conforme" : `+${Math.abs(v.marge).toFixed(3)} pt`}`;
    const fin = [g.occupancyMaxText, limite];
    return unParGroupe
      ? [g.name, g.spreadingFactor, g.sent, g.received, g.pdrText, g.lostSensitivity, g.lostCollision, ...fin]
      : [g.name, g.spreadingFactor, g.count, g.sent, g.received, g.pdrText, g.lostSensitivity, g.lostCollision, ...fin];
  });
  return { entetes, lignes, unParGroupe };
}

/** Taux de livraison par dispositif : la matière première du coloriage de la carte (phase L). */
export function pdrParDispositif(lignes = []) {
  return lignes.map((l) => ({
    deviceIndex: l.device_index,
    pdr: ratio(l.received, l.sent),
    sent: l.sent,
    received: l.received,
  }));
}

// --- Coloriage par résultat (phase L) -------------------------------------------------------
//
// La carte colorait chaque équipement selon son **type**. Après un run, elle doit colorer
// selon son **résultat** : c'est là que se lit le comportement du réseau. La décision de
// couleur vit ici, dans le module pur, où elle est testable sans Cesium ; la carte ne fait
// que l'appliquer.

/**
 * Échelle du taux de livraison, du meilleur au pire.
 *
 * Paliers francs plutôt que dégradé continu : un dégradé suggère une précision que la
 * mesure n'a pas, et rend deux équipements voisins indiscernables. Quatre étapes qu'on
 * peut nommer dans une légende.
 */
export const ECHELLE_PDR = [
  { min: 0.95, couleur: "#2ea043", label: "95 % et plus" },
  { min: 0.80, couleur: "#9a6700", label: "de 80 à 95 %" },
  { min: 0.50, couleur: "#bc4c00", label: "de 50 à 80 %" },
  { min: 0.00, couleur: "#b42318", label: "moins de 50 %" },
];

/** Couleur d'un taux de livraison. `null` (non mesuré) : l'appelant garde sa couleur de type. */
export function couleurPdr(pdr) {
  if (!Number.isFinite(pdr)) return null;
  for (const palier of ECHELLE_PDR) if (pdr >= palier.min) return palier.couleur;
  return ECHELLE_PDR[ECHELLE_PDR.length - 1].couleur;
}

/** Légende de l'échelle, pour l'affichage. */
export function echellePdr() {
  return ECHELLE_PDR.map((p) => ({ couleur: p.couleur, label: p.label }));
}

/**
 * Résultats par équipement de la topologie.
 *
 * Jointure par le nom du groupe : une session studio compile **un groupe par équipement**,
 * nommé d'après l'identifiant du capteur (`study_compile.py`). Un run issu d'un scénario
 * YAML, lui, a de vrais groupes sans équivalent dans la topologie : aucun équipement n'est
 * alors coloré, plutôt que de colorer au hasard.
 */
export function resultatsParNoeud(lignes = [], noeuds = []) {
  const parGroupe = new Map();
  for (const l of lignes ?? []) {
    if (l.group == null) continue;
    const a = parGroupe.get(l.group)
      ?? { sent: 0, received: 0, lostCollision: 0, lostSensitivity: 0, airtimeMax: 0, count: 0 };
    a.sent += l.sent ?? 0;
    a.received += l.received ?? 0;
    a.lostCollision += l.lost_collision ?? 0;
    a.lostSensitivity += l.lost_sensitivity ?? 0;
    if (Number.isFinite(l.airtime_ns)) a.airtimeMax = Math.max(a.airtimeMax, l.airtime_ns);
    a.count += 1;
    parGroupe.set(l.group, a);
  }
  const out = new Map();
  for (const n of noeuds ?? []) {
    const a = parGroupe.get(n.id);
    if (!a || a.count !== 1) continue;   // un seul dispositif par équipement, sinon pas de jointure
    const pdr = ratio(a.received, a.sent);
    out.set(n.id, {
      pdr,
      pdrText: pct(pdr),
      couleur: couleurPdr(pdr),
      sent: a.sent,
      received: a.received,
      lostCollision: a.lostCollision,
      lostSensitivity: a.lostSensitivity,
      airtimeNs: a.airtimeMax,
    });
  }
  return out;
}

/**
 * Lignes « Résultat » d'un équipement, pour sa fenêtre.
 *
 * Reprend exactement ce que porte la carte : le même taux de livraison, la même couleur.
 * Deux lectures du même nombre calculées séparément finiraient par diverger, et l'une des
 * deux serait crue — sans qu'on sache laquelle. `null` si l'équipement n'a pas de résultat.
 */
export function lignesResultat(resultat, fenetreNs = null) {
  if (!resultat || !Number.isFinite(resultat.pdr)) return null;
  const occupation = ratio(resultat.airtimeNs, fenetreNs);
  return {
    couleur: resultat.couleur,
    lignes: [
      { titre: "Taux de livraison", valeur: resultat.pdrText },
      { titre: "Trames reçues", valeur: `${resultat.received} sur ${resultat.sent}` },
      { titre: "Perte hors portée", valeur: String(resultat.lostSensitivity) },
      { titre: "Perte en collision", valeur: String(resultat.lostCollision) },
      { titre: "Occupation", valeur: pct(occupation, 3) },
    ],
  };
}

// --- Verdict de rapport cyclique ------------------------------------------------------------
//
// Le serveur publie la limite et sa source ; la comparaison se fait ici, sur la mesure.
// `info` est la ligne `DutyCycleOut` du groupe (absente si le groupe ne déclare pas de région,
// sans clé `limit` si le plan n'en définit aucune).

/** Le verdict est rendu, mais la réserve qui va avec ne l'est jamais : elle fait partie du verdict. */
export const RESERVE_DUTY_CYCLE =
  "Mesuré sur la fenêtre du run, qui n'est pas forcément la fenêtre de moyennage du texte "
  + "réglementaire (une heure chez ETSI).";

/**
 * Autonomie en années, depuis une capacité énoncée et un courant moyen simulé.
 *
 * Le simulateur fournit le courant (`average_current_ua`) ; la capacité est celle de la pile
 * que l'utilisateur a choisie, et lui seul la connaît. La division est de l'arithmétique :
 * ni un côté ni l'autre n'invente une grandeur. C'est ce qui distingue ce calcul d'une
 * estimation — et c'est pourquoi le champ reste vide plutôt que prérempli.
 *
 * @param {number|null} capaciteMAh capacité de la pile, en milliampères-heures
 * @param {number|null} courantMoyenUA courant moyen simulé, en microampères
 * @returns {number|null} années, ou `null` si l'un des deux termes manque.
 */
export function autonomieAns(capaciteMAh, courantMoyenUA) {
  if (!Number.isFinite(capaciteMAh) || capaciteMAh <= 0) return null;
  if (!Number.isFinite(courantMoyenUA) || courantMoyenUA <= 0) return null;
  return (capaciteMAh * 1000) / courantMoyenUA / (24 * 365);
}

/**
 * Autonomie lisible. En dessous d'un an, on dit les mois : « 0,4 an » demande une division
 * de tête que « 5 mois » épargne, et c'est justement le cas d'un capteur mal réglé.
 */
export function autonomieTexte(ans) {
  if (!Number.isFinite(ans) || ans <= 0) return null;
  if (ans < 1) {
    const mois = Math.round(ans * 12);
    return mois >= 1 ? `${mois} mois` : `${Math.max(1, Math.round(ans * 365))} jours`;
  }
  // « 1,0 ans » est un mauvais accord, et la décimale ne veut rien dire au-delà de dix ans.
  if (ans >= 10) return `${Math.round(ans)} ans`;
  return `${ans.toFixed(1).replace(".", ",")} ${ans < 2 ? "an" : "ans"}`;
}

/**
 * Fenêtre de moyennage du texte réglementaire, en secondes : une heure chez ETSI.
 *
 * Ce n'est pas une constante de l'interface, c'est une grandeur du texte qu'on cite. Elle est
 * nommée ici pour que la phrase qui la compare ne la répète pas de mémoire.
 */
export const FENETRE_ETSI_S = 3600;

/**
 * Durée lisible, depuis des nanosecondes. « 6 min 40 s » se confronte à une limite mieux que
 * « 400 s » ou que « 4,0e+11 ns » : c'est l'unité dans laquelle on parle d'une fenêtre.
 */
export function dureeTexte(ns) {
  if (!Number.isFinite(ns) || ns <= 0) return null;
  const total = Math.round(ns / 1e9);
  const h = Math.floor(total / 3600);
  const min = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) return min > 0 ? `${h} h ${min} min` : `${h} h`;
  if (min > 0) return s > 0 ? `${min} min ${s} s` : `${min} min`;
  return `${s} s`;
}

/**
 * La fenêtre de mesure, dite à côté du verdict — pas à sa place.
 *
 * Le verdict compare une occupation **mesurée sur la fenêtre du run** à une limite **moyennée
 * sur la fenêtre du texte réglementaire**. Comparer deux fenêtres différentes sans le dire est
 * ce qui rendait le verdict surinterprétable. On ne corrige pas la comparaison : on affiche
 * l'écart entre les deux fenêtres, et l'utilisateur juge.
 *
 * Cas où la fenêtre du run couvre l'heure réglementaire : la comparaison devient directe, et
 * il faut le dire aussi — sinon la réserve affichée à tort décrédibilise un verdict valide.
 *
 * @param {number|null} ns fenêtre d'observation du run, en nanosecondes
 * @returns {string} une phrase complète, jamais vide.
 */
export function fenetreVerdictTexte(ns) {
  const duree = dureeTexte(ns);
  if (duree === null) return RESERVE_DUTY_CYCLE;
  const secondes = Math.round(ns / 1e9);
  if (secondes >= FENETRE_ETSI_S) {
    return `Mesuré sur ${duree} : la fenêtre du run couvre la fenêtre de moyennage du texte `
      + `réglementaire (1 h chez ETSI). La comparaison est directe.`;
  }
  const rapport = (FENETRE_ETSI_S / Math.max(secondes, 1)).toFixed(0);
  // « Fenêtre de moyennage » et pas seulement « moyenne » : c'est le nom de la grandeur à
  // laquelle on compare, et c'est le mot qui porte la réserve. L'énoncer au passage la
  // affaiblirait ; la nommer rappelle qu'il s'agit d'un objet du texte réglementaire.
  return `Mesuré sur ${duree}, quand la fenêtre de moyennage du texte réglementaire est de `
    + `1 h (ETSI) — soit environ ${rapport} fois plus long. Le verdict porte sur la fenêtre `
    + `du run : sur une heure, l'occupation moyenne peut être plus basse comme plus haute.`;
}

/**
 * Compare l'occupation mesurée d'un groupe à la limite de son plan régional.
 *
 * Quatre issues, et elles ne se confondent pas :
 *  - `sans_region` : le groupe ne déclare pas de région. Aucune limite n'est devinable.
 *  - `sans_limite` : le plan est connu mais ne borne pas (US915, AU915, AS923, KR920, IN865).
 *    Ce n'est **pas** une limite à 100 % : l'afficher ainsi permettrait de dépasser sans alerte.
 *  - `conforme` / `depassement` : comparaison des deux nombres.
 */
export function verdictDutyCycle(groupe, info) {
  const mesure = groupe?.occupancyMax ?? null;
  if (!info) {
    return { verdict: "sans_region", mesure, limite: null, limiteText: "—",
      verdictText: "région non déclarée", source: null, region: null, freqMhz: null,
      conforme: null, marge: null };
  }
  const limite = Number.isFinite(info.limit) ? info.limit : null;
  const freqMhz = Number.isFinite(info.channel_freq_hz) ? info.channel_freq_hz / 1e6 : null;
  const commun = {
    mesure, limite, source: info.source ?? null, region: info.region ?? null, freqMhz,
    limiteText: limite == null ? "aucune" : pct(limite, 3),
  };
  if (limite == null) {
    return { ...commun, verdict: "sans_limite", verdictText: "plan sans limite",
      conforme: null, marge: null };
  }
  if (mesure == null) {
    return { ...commun, verdict: "non_mesure", verdictText: "non mesuré",
      conforme: null, marge: null };
  }
  // Marge en points de pourcentage : « 0,149 pt sous la limite » parle mieux que deux
  // pourcentages qu'il faut soustraire de tête — surtout près du seuil.
  const marge = (limite - mesure) * 100;
  const conforme = mesure <= limite;
  return {
    ...commun, conforme, marge,
    verdict: conforme ? "conforme" : "depassement",
    verdictText: conforme
      ? `conforme, ${Math.abs(marge).toFixed(3)} pt sous la limite`
      : `dépasse la limite de ${Math.abs(marge).toFixed(3)} pt`,
  };
}

/** Associe chaque ligne de groupe à l'éventuelle limite de son plan (jointure par le nom). */
export function limitesParGroupe(summary) {
  const out = new Map();
  for (const d of summary?.duty_cycle ?? []) if (d?.group != null) out.set(d.group, d);
  return out;
}
