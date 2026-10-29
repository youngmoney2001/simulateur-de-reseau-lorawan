// Animation des trames et journal par saut : logique pure (sans DOM).
// Entrées : événements `TraceEvent` (GET /api/v1/runs/{id}/events) et lignes par dispositif
// (GET /api/v1/runs/{id}/devices) qui donnent le groupe, donc l'identifiant du capteur.
// Identifiants des sauts : « dev:<index> », « gw:<nom de passerelle> », « ns » (réseau).

// Durées de présentation, en temps simulé : déplacement visuel puis trait conservé.
export const TRAVEL_NS = 1_000_000_000n;
export const HOLD_NS = 4_000_000_000n;
// Vitesses de lecture proposées (secondes simulées par seconde réelle).
export const SPEEDS = [1, 10, 60, 300];

const LOST = new Set(["lost_sensitivity", "lost_collision", "lost_mesh", "lost_half_duplex",
  "lost_gateway_busy", "rx_window_missed"]);
const OK = new Set(["delivered"]);

// Classe visuelle d'un résultat : « ok », « lost » ou « neutral ».
export function outcomeClass(outcome) {
  if (OK.has(outcome)) return "ok";
  if (LOST.has(outcome)) return "lost";
  return "neutral";
}

// Identifiant de nœud d'un saut. `deviceGroups[i]` = identifiant du capteur d'indice i.
// Retourne null pour le réseau (« ns ») et pour un identifiant inconnu.
export function resolveId(id, deviceGroups) {
  if (typeof id !== "string") return null;
  if (id === "ns") return null;
  if (id.startsWith("gw:")) return id.slice(3) || null;
  if (id.startsWith("dev:")) {
    const index = Number(id.slice(4));
    if (!Number.isInteger(index) || index < 0) return null;
    const group = deviceGroups[index];
    return typeof group === "string" ? group : null;
  }
  return null;
}

// Un segment par saut, avec source et destination résolues. Les sauts sans source connue sont ignorés.
export function segmentsFromEvents(events, deviceGroups) {
  const out = [];
  for (const event of events) {
    for (const hop of event.hops ?? []) {
      const from = resolveId(hop.from_id, deviceGroups);
      if (from === null) continue;
      out.push({
        seq: event.seq,
        kind: event.kind,
        outcome: hop.outcome,
        cls: outcomeClass(hop.outcome),
        from,
        to: resolveId(hop.to_id, deviceGroups),
        t0: BigInt(hop.t_ns),
        rssi: hop.rssi_dbm ?? null,
      });
    }
  }
  return out;
}

// État visuel des segments à l'instant `clockNs` : position d'avancement (0 à 1) et visibilité.
export function activeAt(segments, clockNs) {
  const clock = BigInt(clockNs);
  const visible = [];
  for (const seg of segments) {
    const elapsed = clock - seg.t0;
    if (elapsed < 0n || elapsed > TRAVEL_NS + HOLD_NS) continue;
    const progress = elapsed >= TRAVEL_NS ? 1 : Number(elapsed) / Number(TRAVEL_NS);
    visible.push({ ...seg, progress });
  }
  return visible;
}

// Bornes temporelles des événements (pour le curseur de temps).
export function timelineBounds(events) {
  if (events.length === 0) return { startNs: 0n, endNs: 0n };
  let start = BigInt(events[0].t_ns);
  let end = start;
  for (const e of events) {
    const t = BigInt(e.t_ns);
    if (t < start) start = t;
    if (t > end) end = t;
  }
  return { startNs: start, endNs: end };
}

// Ligne de journal lisible pour un événement.
export function journalRow(event, deviceGroups) {
  const source = event.device_index !== undefined && event.device_index !== null
    ? (deviceGroups[event.device_index] ?? `dispositif ${event.device_index}`)
    : "";
  return {
    seq: event.seq,
    t_ns: BigInt(event.t_ns),
    time: `${(Number(event.t_ns) / 1e9).toFixed(3)} s`,
    kind: event.kind,
    source,
    outcome: event.outcome,
    cls: outcomeClass(event.outcome),
    hops: (event.hops ?? []).map((h) => `${h.from_id} → ${h.to_id} : ${h.outcome}`),
  };
}

// Dérive la table `index -> identifiant de capteur` à partir des lignes par dispositif.
export function deviceGroupsFromRows(rows) {
  const groups = [];
  for (const row of rows) {
    groups[row.device_index] = row.group;
  }
  return groups;
}

// Plafond de chargement côté interface : au-delà, l'animation n'est pas proposée.
export const MAX_ANIM_EVENTS = 20000;

// Lit toutes les pages d'une liste paginée (`{items, next_cursor}`). Lève une erreur au-delà de `maxItems`.
export async function collectPages(fetchPage, maxItems = MAX_ANIM_EVENTS) {
  const items = [];
  let cursor = 0;
  while (cursor !== null) {
    const page = await fetchPage(cursor);
    for (const item of page.items) {
      items.push(item);
      if (items.length > maxItems) {
        throw new Error(`trop d'événements pour l'animation (plus de ${maxItems})`);
      }
    }
    cursor = page.next_cursor ?? null;
  }
  return items;
}
