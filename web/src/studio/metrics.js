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
export function ventilationTable(groupes = []) {
  const unParGroupe = groupes.length > 0 && groupes.every((g) => g.count === 1);
  const entetes = unParGroupe
    ? ["Équipement", "SF", "Émises", "Reçues", "PDR", "Sensibilité", "Collision", "Occupation"]
    : ["Groupe", "SF", "Dispositifs", "Émises", "Reçues", "PDR", "Sensibilité", "Collision", "Occupation"];
  const lignes = groupes.map((g) => (unParGroupe
    ? [g.name, g.spreadingFactor, g.sent, g.received, g.pdrText, g.lostSensitivity, g.lostCollision, g.occupancyMaxText]
    : [g.name, g.spreadingFactor, g.count, g.sent, g.received, g.pdrText, g.lostSensitivity, g.lostCollision, g.occupancyMaxText]));
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
