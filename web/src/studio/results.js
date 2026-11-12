// Mise en forme des résultats de simulation et de notation (logique pure).

export function formatMs(value) {
  return value == null ? "—" : `${value.toFixed(1)} ms`;
}

export function formatPercent(value) {
  return value == null ? "—" : `${(value * 100).toFixed(1)} %`;
}

/**
 * Une durée en secondes, telle qu'on la lit sur un écran d'attente.
 *
 * Le saut d'unité à 90 s (« 2 min 8 s ») plutôt qu'à 60 s : en dessous, « 1 min 12 s » n'est
 * pas plus clair que « 72 s », et l'attente d'un créneau se compare mieux en secondes.
 * `null` devient « — », jamais « 0 s » — une attente inconnue n'est pas une attente nulle.
 */
export function formatSecondes(value) {
  if (value == null || !Number.isFinite(value)) return "—";
  if (value === 0) return "0 s";
  if (value < 1) return `${value.toFixed(2)} s`;
  if (value < 90) return `${value.toFixed(value < 10 ? 1 : 0)} s`;
  const min = Math.floor(value / 60);
  const sec = Math.round(value - min * 60);
  return sec ? `${min} min ${sec} s` : `${min} min`;
}

// Une ligne par passerelle du run : compteurs, latence p95, liens mesh observés.
export function gatewayRows(summary, linkedNames = []) {
  const linked = new Set(linkedNames);
  return (summary?.gateways ?? []).map((g) => {
    const lost = g.lost_sensitivity + g.lost_collision + g.lost_gateway_busy;
    return {
      name: g.name,
      linked: linked.has(g.name),
      received: g.received,
      lost,
      latency: formatMs(g.latency_p95_ms),
      latencySamples: g.latency_samples ?? 0,
      mesh: (g.mesh_inbound ?? []).map((m) => `${m.from_gateway} (${m.delivered})`).join(", ") || "—",
    };
  });
}

export function scoreLine(result) {
  const hints = result.hints_used ? ` · ${result.hints_used} indice(s)` : "";
  return `${result.score} / ${result.max_score} points${hints}`;
}

export function criteriaRows(result) {
  return (result.criteria ?? []).map((c) => ({
    label: c.label,
    passed: c.passed,
    points: `${c.points} / ${c.max_points}`,
  }));
}

// Une ligne par champ de la trame, pour l inspecteur.
export function frameRows(mac = {}, app = {}) {
  const rows = [
    ["MHDR", mac.mhdr_hex ?? "-", mac.mtype ?? "-"],
    ["DevAddr", mac.dev_addr_hex ?? "-", ""],
    ["FCtrl", mac.fctrl_hex ?? "-", "ADR=" + (mac.adr ? 1 : 0)],
    ["FCnt", mac.fcnt ?? "-", ""],
    ["FPort", app.fport ?? "-", ""],
    ["Charge", app.frm_payload_hex ?? "-", (app.frm_payload_octets ?? 0) + " octets"],
    ["MIC", mac.mic_hex ?? "-", ""],
  ];
  return rows.map((r) => ({ label: r[0], value: r[1], note: r[2] }));
}
