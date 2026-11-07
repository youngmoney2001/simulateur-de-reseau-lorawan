// Mise en forme des résultats de simulation et de notation (logique pure).

export function formatMs(value) {
  return value == null ? "—" : `${value.toFixed(1)} ms`;
}

export function formatPercent(value) {
  return value == null ? "—" : `${(value * 100).toFixed(1)} %`;
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
